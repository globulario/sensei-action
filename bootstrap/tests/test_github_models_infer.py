import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "github_models_infer.py"
spec = importlib.util.spec_from_file_location("github_models_infer", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class GitHubModelsInferTests(unittest.TestCase):
    def test_payload_is_bounded_and_json_only(self):
        payload = module.build_payload("Return JSON", "openai/gpt-4.1", 4000)
        self.assertEqual(payload["model"], "openai/gpt-4.1")
        self.assertEqual(payload["max_tokens"], 4000)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertFalse(payload["stream"])

    def test_empty_prompt_is_rejected(self):
        with self.assertRaises(module.InferenceError):
            module.build_payload("  ", "openai/gpt-4.1", 4000)

    def test_success_extracts_message_content(self):
        response = FakeResponse({"choices": [{"message": {"content": '{"ok":true}'}}]})
        with mock.patch.object(module.urllib.request, "urlopen", return_value=response):
            content = module.infer("prompt", "secret", "openai/gpt-4.1", 4000)
        self.assertEqual(content, '{"ok":true}')

    def test_token_is_sent_only_as_authorization_header(self):
        captured = {}

        def fake_open(request, timeout):
            captured["authorization"] = request.headers["Authorization"]
            captured["body"] = request.data.decode("utf-8")
            captured["timeout"] = timeout
            return FakeResponse({"choices": [{"message": {"content": "{}"}}]})

        with mock.patch.object(module.urllib.request, "urlopen", side_effect=fake_open):
            module.infer("prompt", "top-secret", "openai/gpt-4.1", 4000)
        self.assertEqual(captured["authorization"], "Bearer top-secret")
        self.assertNotIn("top-secret", captured["body"])
        self.assertEqual(captured["timeout"], 180)


if __name__ == "__main__":
    unittest.main()
