#!/usr/bin/env python3
"""Call GitHub Models with an explicit, inspectable REST contract."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = "https://models.github.ai/inference/chat/completions"
API_VERSION = "2026-03-10"


class InferenceError(RuntimeError):
    pass


def build_payload(prompt: str, model: str, max_tokens: int) -> dict:
    if not prompt.strip():
        raise InferenceError("prompt is empty")
    if max_tokens < 256 or max_tokens > 8000:
        raise InferenceError("max-tokens must be between 256 and 8000")
    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are Sensei's bounded architectural candidate drafter. "
                    "Follow the supplied output contract exactly and return only the requested JSON object."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "stream": False,
    }


def infer(prompt: str, token: str, model: str, max_tokens: int, endpoint: str = ENDPOINT) -> str:
    if not token:
        raise InferenceError("Models token is empty")
    body = json.dumps(build_payload(prompt, model, max_tokens)).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": API_VERSION,
            "Content-Type": "application/json",
            "User-Agent": "globulario-sensei-action",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:4000]
        raise InferenceError(f"GitHub Models HTTP {exc.code}: {detail or '<no response body>'}") from exc
    except urllib.error.URLError as exc:
        raise InferenceError(f"GitHub Models transport error: {exc.reason}") from exc

    try:
        payload = json.loads(raw)
        content = payload["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise InferenceError(f"GitHub Models returned an unexpected response: {raw[:2000]}") from exc
    if not isinstance(content, str) or not content.strip():
        raise InferenceError("GitHub Models returned empty content")
    return content


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--response-file", required=True)
    parser.add_argument("--model", default="openai/gpt-4.1")
    parser.add_argument("--max-tokens", type=int, default=4000)
    parser.add_argument("--endpoint", default=ENDPOINT)
    args = parser.parse_args()

    target = Path(args.response_file)
    error_target = target.with_suffix(target.suffix + ".error.txt")
    try:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8")
        content = infer(
            prompt,
            os.environ.get("SENSEI_MODELS_TOKEN", ""),
            args.model,
            args.max_tokens,
            args.endpoint,
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content.rstrip() + "\n", encoding="utf-8")
        error_target.unlink(missing_ok=True)
        print(target)
        return 0
    except (OSError, InferenceError) as exc:
        message = f"Sensei GitHub Models inference: {exc}"
        target.parent.mkdir(parents=True, exist_ok=True)
        error_target.write_text(message + "\n", encoding="utf-8")
        print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
