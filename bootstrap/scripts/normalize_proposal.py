#!/usr/bin/env python3
"""Normalize model-authored Sensei claims to non-authoritative review-only state."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

STATUS_RE = re.compile(r"(?m)^(\s+status\s*:\s*)([^#\s]+)(\s*(?:#.*)?)$")


def load_bootstrap_agent():
    module_path = Path(__file__).with_name("bootstrap_agent.py")
    spec = importlib.util.spec_from_file_location("sensei_bootstrap_agent", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load bootstrap_agent.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def normalize(path: Path) -> bool:
    agent = load_bootstrap_agent()
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        payload = agent.parse_model_response(raw)
    except agent.BootstrapError:
        # The bounded apply step owns malformed-response diagnosis and repair.
        return False

    changed = False
    for key in ("invariants_yaml", "failure_modes_yaml"):
        value = payload.get(key)
        if not isinstance(value, str):
            continue
        normalized, count = STATUS_RE.subn(r"\1review_only\3", value)
        if count:
            payload[key] = normalized
            changed = True

    if not changed:
        return False

    uncertainties = payload.setdefault("uncertainties", [])
    note = "Sensei normalized all model-authored claim statuses to review_only; human promotion is required."
    if note not in uncertainties:
        uncertainties.append(note)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: normalize_proposal.py <response-file>", file=sys.stderr)
        return 2
    changed = normalize(Path(sys.argv[1]))
    print("normalized review-only statuses" if changed else "no status normalization needed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
