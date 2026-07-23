#!/usr/bin/env python3
"""Bounded AI helper for Sensei's Action-first bootstrap flow.

The model never receives a shell and never chooses arbitrary paths. It may only
populate empty starter invariants/failure modes and write an architect-question
report. Every proposal is checked by Sensei before it can be committed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

MAX_MODEL_FILE_BYTES = 64 * 1024
MAX_QUESTIONS_BYTES = 32 * 1024
DEFAULT_MAX_CONTEXT_BYTES = 180_000
MAX_TREE_ENTRIES = 1_200

INVARIANTS_PATH = Path("docs/awareness/invariants.yaml")
FAILURE_MODES_PATH = Path("docs/awareness/failure_modes.yaml")
QUESTIONS_PATH = Path("docs/awareness/BOOTSTRAP_QUESTIONS.md")
PROPOSAL_PATH = Path(".sensei/ai-bootstrap-proposal.json")
RECEIPT_PATH = Path(".sensei/ai-bootstrap-receipt.json")

LIVE_ID_RE = re.compile(r"^\s*-\s+id\s*:\s*[^#\s].*$", re.MULTILINE)
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
FORBIDDEN_TEXT = ("!!python", "!<", "${{", "{{", "../", "\\..\\")


class BootstrapError(RuntimeError):
    pass


@dataclass(frozen=True)
class BaselinePolicy:
    allow_invariants: bool
    allow_failure_modes: bool


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_text(path: Path, limit: int | None = None) -> str:
    data = path.read_bytes()
    if limit is not None and len(data) > limit:
        data = data[:limit] + b"\n\n[truncated by Sensei bootstrap context]\n"
    return data.decode("utf-8", errors="replace")


def has_live_entries(text: str) -> bool:
    uncommented = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    return bool(LIVE_ID_RE.search(uncommented))


def parse_model_response(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise BootstrapError("model response did not contain a JSON object")
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise BootstrapError(f"model response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise BootstrapError("model response must be one JSON object")

    allowed_keys = {
        "summary",
        "invariants_yaml",
        "failure_modes_yaml",
        "questions_markdown",
        "evidence",
        "uncertainties",
    }
    extras = sorted(set(payload) - allowed_keys)
    if extras:
        raise BootstrapError(f"unexpected model response keys: {', '.join(extras)}")
    if not isinstance(payload.get("summary"), str) or not payload["summary"].strip():
        raise BootstrapError("model response requires a non-empty summary")
    for key in ("invariants_yaml", "failure_modes_yaml", "questions_markdown"):
        value = payload.get(key)
        if value is not None and not isinstance(value, str):
            raise BootstrapError(f"{key} must be a string or null")
    for key in ("evidence", "uncertainties"):
        value = payload.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise BootstrapError(f"{key} must be an array of strings")
        payload[key] = value
    return payload


def validate_yaml_document(text: str, root_key: str, allowed_statuses: set[str]) -> None:
    data = text.encode("utf-8")
    if len(data) > MAX_MODEL_FILE_BYTES:
        raise BootstrapError(f"{root_key} document exceeds {MAX_MODEL_FILE_BYTES} bytes")
    if "\t" in text:
        raise BootstrapError(f"{root_key} document contains tab indentation")
    lowered = text.lower()
    for marker in FORBIDDEN_TEXT:
        if marker.lower() in lowered:
            raise BootstrapError(f"{root_key} document contains forbidden marker {marker!r}")

    meaningful = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not meaningful or meaningful[0].strip() != f"{root_key}:":
        raise BootstrapError(f"{root_key} document must begin with '{root_key}:'")

    ids: list[str] = []
    statuses: list[str] = []
    for line in meaningful[1:]:
        id_match = re.match(r"^\s*-\s+id\s*:\s*([^#\s]+)\s*$", line)
        if id_match:
            ids.append(id_match.group(1))
        status_match = re.match(r"^\s+status\s*:\s*([^#\s]+)\s*$", line)
        if status_match:
            statuses.append(status_match.group(1))

    if not ids:
        raise BootstrapError(f"{root_key} document must contain at least one entry")
    invalid_ids = [item for item in ids if not ID_RE.match(item)]
    if invalid_ids:
        raise BootstrapError(f"{root_key} contains invalid ids: {', '.join(invalid_ids)}")
    if len(ids) != len(set(ids)):
        raise BootstrapError(f"{root_key} contains duplicate ids")
    invalid_statuses = [item for item in statuses if item not in allowed_statuses]
    if invalid_statuses:
        raise BootstrapError(
            f"{root_key} contains unsupported statuses: {', '.join(sorted(set(invalid_statuses)))}"
        )


def safe_questions_markdown(text: str) -> str:
    data = text.encode("utf-8")
    if len(data) > MAX_QUESTIONS_BYTES:
        raise BootstrapError(f"questions_markdown exceeds {MAX_QUESTIONS_BYTES} bytes")
    for marker in ("${{", "<script", "javascript:"):
        if marker.lower() in text.lower():
            raise BootstrapError(f"questions_markdown contains forbidden marker {marker!r}")
    if not text.lstrip().startswith("#"):
        text = f"# Sensei bootstrap questions\n\n{text.strip()}\n"
    return text.rstrip() + "\n"


def run(command: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if check and result.returncode != 0:
        raise BootstrapError(f"command failed ({' '.join(command)}):\n{result.stdout}")
    return result


def git_output(root: Path, *args: str) -> str:
    return run(["git", *args], root).stdout.strip()


def tracked_files(root: Path) -> list[str]:
    result = run(["git", "ls-files", "-co", "--exclude-standard"], root)
    files: list[str] = []
    for raw in result.stdout.splitlines():
        value = raw.strip().replace("\\", "/")
        if not value or value.startswith(".git/"):
            continue
        parts = set(Path(value).parts)
        if parts.intersection({"node_modules", "vendor", "dist", "build", ".cache"}):
            continue
        files.append(value)
    return sorted(dict.fromkeys(files))[:MAX_TREE_ENTRIES]


def context_candidates(files: Iterable[str]) -> list[str]:
    selected: list[str] = []
    manifest_names = {
        "go.mod",
        "go.work",
        "package.json",
        "pyproject.toml",
        "Cargo.toml",
        "pom.xml",
        "build.gradle",
        "Makefile",
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
    }
    for path in files:
        p = Path(path)
        lower = path.lower()
        if p.name in manifest_names:
            selected.append(path)
        elif p.name.lower().startswith("readme"):
            selected.append(path)
        elif lower.startswith("docs/") and p.suffix.lower() in {".md", ".yaml", ".yml"}:
            selected.append(path)
        elif p.suffix.lower() in {".proto", ".graphql"}:
            selected.append(path)
    return sorted(dict.fromkeys(selected))


def build_context(root: Path, deterministic_report: Path, max_bytes: int) -> dict[str, Any]:
    files = tracked_files(root)
    context: dict[str, Any] = {
        "schema": "sensei.ai_bootstrap.context.v1",
        "repository": os.environ.get("GITHUB_REPOSITORY", root.name),
        "source_revision": git_output(root, "rev-parse", "HEAD"),
        "tree": files,
        "documents": [],
        "deterministic_bootstrap_report": deterministic_report.read_text(
            encoding="utf-8", errors="replace"
        )
        if deterministic_report.exists()
        else "",
    }
    used = len(json.dumps(context, ensure_ascii=False).encode("utf-8"))
    for relative in context_candidates(files):
        path = root / relative
        if not path.is_file():
            continue
        remaining = max_bytes - used
        if remaining <= 1024:
            break
        content = read_text(path, min(remaining, 24_000))
        item = {"path": relative, "content": content}
        encoded = json.dumps(item, ensure_ascii=False).encode("utf-8")
        if used + len(encoded) > max_bytes:
            continue
        context["documents"].append(item)
        used += len(encoded)
    context["context_bytes"] = used
    return context


def snapshot_file(root: Path, state_dir: Path, relative: Path) -> dict[str, Any]:
    source = root / relative
    entry: dict[str, Any] = {"path": relative.as_posix(), "existed": source.exists()}
    if source.exists():
        data = source.read_bytes()
        entry["sha256"] = sha256_bytes(data)
        backup = state_dir / "baseline" / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(data)
    return entry


def restore_baseline(root: Path, state_dir: Path, manifest: dict[str, Any]) -> None:
    for entry in manifest["baseline_files"]:
        relative = Path(entry["path"])
        target = root / relative
        backup = state_dir / "baseline" / relative
        if entry["existed"]:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(backup.read_bytes())
        elif target.exists():
            target.unlink()


def baseline_policy(root: Path) -> BaselinePolicy:
    inv = read_text(root / INVARIANTS_PATH) if (root / INVARIANTS_PATH).exists() else ""
    failures = read_text(root / FAILURE_MODES_PATH) if (root / FAILURE_MODES_PATH).exists() else ""
    return BaselinePolicy(
        allow_invariants=not has_live_entries(inv),
        allow_failure_modes=not has_live_entries(failures),
    )


def build_prompt(context: dict[str, Any], policy: BaselinePolicy) -> str:
    return f"""You are the bounded architectural candidate drafter inside Sensei bootstrap.

Sensei has already run deterministic structural extraction. Your task is not to edit code and not to invent certainty. Produce a small first architectural memory from evidence in the supplied context.

Writable outputs are structurally fixed by the caller:
- invariants_yaml: {'allowed because the starter file is empty' if policy.allow_invariants else 'MUST be null because an established invariants corpus already exists'}
- failure_modes_yaml: {'allowed because the starter file is empty' if policy.allow_failure_modes else 'MUST be null because an established failure-mode corpus already exists'}
- questions_markdown: architect questions and unresolved ambiguities

Rules:
1. Return exactly one JSON object and no prose or Markdown fence.
2. Use only these keys: summary, invariants_yaml, failure_modes_yaml, questions_markdown, evidence, uncertainties.
3. Never propose source-code edits or arbitrary paths.
4. Every invariant/failure mode must be grounded in named files, contracts, generated components, tests, README claims, or manifest evidence.
5. Use status review_only unless the evidence proves an active enforced rule.
6. Prefer 2-6 high-value entries over a large speculative list.
7. Questions must clearly separate what the repository proves from what only an architect can answer.
8. YAML must use the exact Sensei starter schemas below.

Invariants schema:
invariants:
  - id: unique.dotted.identifier
    title: short title
    severity: critical | high | medium | low
    status: active | deprecated | review_only
    protects:
      files:
        - repository/path
      symbols: []
    forbidden_fixes: []
    required_tests: []
    related_failure_modes: []

Failure modes schema:
failure_modes:
  - id: unique.dotted.identifier
    title: short title
    severity: critical | high | degraded
    status: active | fixed | review_only
    symptoms: []
    root_cause: |-
      Evidence-grounded explanation.
    trigger: |-
      Trigger condition.
    architecture_fix: |-
      Correct architectural response.
    forbidden_fixes: []
    related_invariants: []

Required JSON shape:
{{
  "summary": "...",
  "invariants_yaml": "invariants:\\n  - id: ...\\n" or null,
  "failure_modes_yaml": "failure_modes:\\n  - id: ...\\n" or null,
  "questions_markdown": "# Sensei bootstrap questions\\n...",
  "evidence": ["path or structural fact", "..."],
  "uncertainties": ["...", "..."]
}}

Repository context follows as JSON:
{json.dumps(context, ensure_ascii=False, indent=2)}
"""


def build_repair_prompt(
    context: dict[str, Any],
    policy: BaselinePolicy,
    prior_response: str,
    errors: str,
) -> str:
    base = build_prompt(context, policy)
    return f"""{base}

The first proposal was rejected. Repair only the schema/evidence problems below and return a complete replacement JSON object.

Validation findings:
{errors[:20_000]}

Rejected response:
{prior_response[:60_000]}
"""


def command_prepare(args: argparse.Namespace) -> int:
    root = Path(args.repo).resolve()
    state_dir = Path(args.state_dir).resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    max_bytes = int(args.max_context_bytes)
    if max_bytes < 20_000 or max_bytes > 500_000:
        raise BootstrapError("max-context-bytes must be between 20000 and 500000")

    policy = baseline_policy(root)
    context = build_context(root, Path(args.deterministic_report), max_bytes)
    context_path = state_dir / "context.json"
    context_path.write_text(json.dumps(context, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    baseline_files = [
        snapshot_file(root, state_dir, INVARIANTS_PATH),
        snapshot_file(root, state_dir, FAILURE_MODES_PATH),
        snapshot_file(root, state_dir, QUESTIONS_PATH),
        snapshot_file(root, state_dir, PROPOSAL_PATH),
        snapshot_file(root, state_dir, RECEIPT_PATH),
    ]
    manifest = {
        "schema": "sensei.ai_bootstrap.state.v1",
        "policy": {
            "allow_invariants": policy.allow_invariants,
            "allow_failure_modes": policy.allow_failure_modes,
        },
        "baseline_files": baseline_files,
        "context_sha256": sha256_bytes(context_path.read_bytes()),
    }
    (state_dir / "state.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (state_dir / "attempt-1.prompt.txt").write_text(build_prompt(context, policy), encoding="utf-8")
    print(json.dumps(manifest["policy"]))
    return 0


def write_proposal_files(
    root: Path,
    payload: dict[str, Any],
    policy: BaselinePolicy,
    attempt: int,
    model: str,
) -> list[str]:
    changed: list[str] = []
    invariants = payload.get("invariants_yaml")
    failures = payload.get("failure_modes_yaml")
    questions = payload.get("questions_markdown") or ""

    if policy.allow_invariants:
        if not invariants:
            raise BootstrapError("invariants_yaml is required while the starter corpus is empty")
        validate_yaml_document(invariants, "invariants", {"active", "deprecated", "review_only"})
        target = root / INVARIANTS_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(invariants.rstrip() + "\n", encoding="utf-8")
        changed.append(INVARIANTS_PATH.as_posix())
    elif invariants not in (None, ""):
        raise BootstrapError("model attempted to overwrite an established invariants corpus")

    if policy.allow_failure_modes:
        if not failures:
            raise BootstrapError("failure_modes_yaml is required while the starter corpus is empty")
        validate_yaml_document(failures, "failure_modes", {"active", "fixed", "review_only"})
        target = root / FAILURE_MODES_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(failures.rstrip() + "\n", encoding="utf-8")
        changed.append(FAILURE_MODES_PATH.as_posix())
    elif failures not in (None, ""):
        raise BootstrapError("model attempted to overwrite an established failure-mode corpus")

    if not questions.strip():
        raise BootstrapError("questions_markdown is required")
    target = root / QUESTIONS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(safe_questions_markdown(questions), encoding="utf-8")
    changed.append(QUESTIONS_PATH.as_posix())

    proposal = {
        "schema": "sensei.ai_bootstrap.proposal.v1",
        "attempt": attempt,
        "model": model,
        "summary": payload["summary"].strip(),
        "evidence": payload.get("evidence", []),
        "uncertainties": payload.get("uncertainties", []),
        "written_files": changed,
    }
    proposal_target = root / PROPOSAL_PATH
    proposal_target.parent.mkdir(parents=True, exist_ok=True)
    proposal_target.write_text(json.dumps(proposal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    changed.append(PROPOSAL_PATH.as_posix())
    return changed


def command_apply(args: argparse.Namespace) -> int:
    root = Path(args.repo).resolve()
    state_dir = Path(args.state_dir).resolve()
    manifest = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))
    context = json.loads((state_dir / "context.json").read_text(encoding="utf-8"))
    policy = BaselinePolicy(**manifest["policy"])
    restore_baseline(root, state_dir, manifest)

    raw = Path(args.response_file).read_text(encoding="utf-8", errors="replace")
    errors = ""
    changed: list[str] = []
    valid = False
    try:
        payload = parse_model_response(raw)
        changed = write_proposal_files(root, payload, policy, int(args.attempt), args.model)
        check_result = run(["sensei", "check"], root, check=False)
        freshness_result = run(
            ["sensei", "bootstrap", "--path", str(root), "--skip-history", "--check"],
            root,
            check=False,
        )
        combined = (
            "sensei check:\n"
            + check_result.stdout
            + "\nsensei bootstrap --check:\n"
            + freshness_result.stdout
        )
        if check_result.returncode != 0 or freshness_result.returncode != 0:
            raise BootstrapError(combined)
        valid = True
        validation_output = combined
    except BootstrapError as exc:
        errors = str(exc)
        validation_output = errors

    result = {
        "schema": "sensei.ai_bootstrap.attempt_result.v1",
        "attempt": int(args.attempt),
        "valid": valid,
        "changed_files": changed,
        "validation_output": validation_output[-30_000:],
        "response_sha256": sha256_bytes(raw.encode("utf-8")),
    }
    Path(args.result_file).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    if not valid and args.repair_prompt:
        (state_dir / args.repair_prompt).write_text(
            build_repair_prompt(context, policy, raw, errors), encoding="utf-8"
        )
    print(json.dumps({"valid": valid, "attempt": int(args.attempt)}))
    return 0


def file_digest(root: Path, relative: str) -> dict[str, str]:
    data = (root / relative).read_bytes()
    return {"path": relative, "sha256": sha256_bytes(data)}


def command_finalize(args: argparse.Namespace) -> int:
    root = Path(args.repo).resolve()
    state_dir = Path(args.state_dir).resolve()
    result = json.loads(Path(args.result_file).read_text(encoding="utf-8"))
    if not result.get("valid"):
        raise BootstrapError("cannot finalize an invalid bootstrap proposal")
    manifest = json.loads((state_dir / "state.json").read_text(encoding="utf-8"))

    status = run(["git", "status", "--porcelain"], root).stdout.splitlines()
    changed_paths = sorted(
        {
            line[3:].strip().replace("\\", "/")
            for line in status
            if len(line) >= 4 and line[3:].strip()
        }
    )
    digest_paths = [
        path
        for path in changed_paths
        if (root / path).is_file() and path != RECEIPT_PATH.as_posix()
    ]
    receipt = {
        "schema": "sensei.ai_bootstrap.receipt.v1",
        "repository": os.environ.get("GITHUB_REPOSITORY", root.name),
        "source_revision": git_output(root, "rev-parse", "HEAD"),
        "workflow_run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "workflow_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
        "model": args.model,
        "accepted_attempt": result["attempt"],
        "context_sha256": manifest["context_sha256"],
        "proposal_response_sha256": result["response_sha256"],
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "files": [file_digest(root, path) for path in digest_paths],
    }
    target = root / RECEIPT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(target)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--repo", required=True)
    prepare.add_argument("--state-dir", required=True)
    prepare.add_argument("--deterministic-report", required=True)
    prepare.add_argument("--max-context-bytes", default=str(DEFAULT_MAX_CONTEXT_BYTES))
    prepare.set_defaults(func=command_prepare)

    apply = sub.add_parser("apply")
    apply.add_argument("--repo", required=True)
    apply.add_argument("--state-dir", required=True)
    apply.add_argument("--response-file", required=True)
    apply.add_argument("--result-file", required=True)
    apply.add_argument("--attempt", required=True, type=int)
    apply.add_argument("--model", required=True)
    apply.add_argument("--repair-prompt", default="")
    apply.set_defaults(func=command_apply)

    finalize = sub.add_parser("finalize")
    finalize.add_argument("--repo", required=True)
    finalize.add_argument("--state-dir", required=True)
    finalize.add_argument("--result-file", required=True)
    finalize.add_argument("--model", required=True)
    finalize.set_defaults(func=command_finalize)
    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
        return args.func(args)
    except BootstrapError as exc:
        print(f"Sensei AI bootstrap: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
