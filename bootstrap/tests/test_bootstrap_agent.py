import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
MODULE_PATH = SCRIPTS_DIR / "bootstrap_agent.py"
spec = importlib.util.spec_from_file_location("bootstrap_agent", MODULE_PATH)
bootstrap_agent = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = bootstrap_agent
spec.loader.exec_module(bootstrap_agent)

NORMALIZER_PATH = SCRIPTS_DIR / "normalize_proposal.py"
normalizer_spec = importlib.util.spec_from_file_location("normalize_proposal", NORMALIZER_PATH)
normalize_proposal = importlib.util.module_from_spec(normalizer_spec)
assert normalizer_spec.loader is not None
sys.modules[normalizer_spec.name] = normalize_proposal
normalizer_spec.loader.exec_module(normalize_proposal)


class BootstrapAgentTests(unittest.TestCase):
    def test_has_live_entries_ignores_commented_example(self):
        text = """invariants:\n#  - id: example.not_real\n#    status: active\n"""
        self.assertFalse(bootstrap_agent.has_live_entries(text))
        self.assertTrue(bootstrap_agent.has_live_entries("invariants:\n  - id: real.rule\n"))

    def test_parse_model_response_accepts_fenced_json(self):
        payload = {
            "summary": "Grounded draft",
            "invariants_yaml": "invariants:\n  - id: repo.rule\n    status: review_only\n",
            "failure_modes_yaml": "failure_modes:\n  - id: repo.failure\n    status: review_only\n",
            "questions_markdown": "# Questions\n\n- Who owns state?",
            "evidence": ["README.md"],
            "uncertainties": ["Runtime owner is unclear"],
        }
        raw = "```json\n" + json.dumps(payload) + "\n```"
        self.assertEqual(bootstrap_agent.parse_model_response(raw)["summary"], "Grounded draft")

    def test_parse_model_response_rejects_arbitrary_files(self):
        payload = {
            "summary": "Bad",
            "files": [{"path": "src/main.go", "content": "changed"}],
        }
        with self.assertRaises(bootstrap_agent.BootstrapError):
            bootstrap_agent.parse_model_response(json.dumps(payload))

    def test_validate_yaml_document_rejects_path_escape(self):
        text = """invariants:\n  - id: repo.rule\n    status: review_only\n    protects:\n      files:\n        - ../secret\n"""
        with self.assertRaises(bootstrap_agent.BootstrapError):
            bootstrap_agent.validate_yaml_document(
                text, "invariants", {"active", "deprecated", "review_only"}
            )

    def test_established_corpus_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs/awareness").mkdir(parents=True)
            (root / bootstrap_agent.INVARIANTS_PATH).write_text(
                "invariants:\n  - id: existing.rule\n    status: active\n", encoding="utf-8"
            )
            (root / bootstrap_agent.FAILURE_MODES_PATH).write_text(
                "failure_modes:\n", encoding="utf-8"
            )
            policy = bootstrap_agent.baseline_policy(root)
            self.assertFalse(policy.allow_invariants)
            self.assertTrue(policy.allow_failure_modes)
            payload = {
                "summary": "Attempted overwrite",
                "invariants_yaml": "invariants:\n  - id: replacement.rule\n    status: review_only\n",
                "failure_modes_yaml": "failure_modes:\n  - id: repo.failure\n    title: Failure\n    severity: degraded\n    status: review_only\n",
                "questions_markdown": "# Questions\n",
                "evidence": [],
                "uncertainties": [],
            }
            with self.assertRaises(bootstrap_agent.BootstrapError):
                bootstrap_agent.write_proposal_files(root, payload, policy, 1, "test/model")
            self.assertIn("existing.rule", (root / bootstrap_agent.INVARIANTS_PATH).read_text())

    def test_model_statuses_are_forced_to_review_only(self):
        payload = {
            "summary": "Grounded draft",
            "invariants_yaml": "invariants:\n  - id: repo.rule\n    status: active\n",
            "failure_modes_yaml": "failure_modes:\n  - id: repo.failure\n    status: fixed\n",
            "questions_markdown": "# Questions\n",
            "evidence": ["README.md"],
            "uncertainties": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            response = Path(tmp) / "response.json"
            response.write_text(json.dumps(payload), encoding="utf-8")
            self.assertTrue(normalize_proposal.normalize(response))
            normalized = json.loads(response.read_text(encoding="utf-8"))
            self.assertNotIn("status: active", normalized["invariants_yaml"])
            self.assertNotIn("status: fixed", normalized["failure_modes_yaml"])
            self.assertEqual(normalized["invariants_yaml"].count("status: review_only"), 1)
            self.assertEqual(normalized["failure_modes_yaml"].count("status: review_only"), 1)
            self.assertTrue(any("human promotion" in item for item in normalized["uncertainties"]))

    def test_questions_are_normalized(self):
        result = bootstrap_agent.safe_questions_markdown("Who owns persistence?")
        self.assertTrue(result.startswith("# Sensei bootstrap questions"))
        self.assertTrue(result.endswith("\n"))


if __name__ == "__main__":
    unittest.main()
