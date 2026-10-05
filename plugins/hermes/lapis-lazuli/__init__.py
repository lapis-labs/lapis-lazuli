"""LapisLazuli session summary for Hermes Agent (install/OUTPUTS.md, Hermes).

On the first turn of a session, pre_llm_call runs `lapis-design-hook --plugin-version VERSION session-start`, the command the
lazuli SessionStart hook runs in Claude Code and Codex, and returns what it prints as context for
that turn's user message. on_session_start ignores return values, so the summary comes with the
first turn instead. A missing CLI, a failure, a timeout, or empty output adds nothing.
"""
from __future__ import annotations

import json
import subprocess
import sys

COMMAND = ["lapis-design-hook", "--plugin-version", "0.2.0", "session-start"]
TIMEOUT_S = 10   # the SessionStart hook's timeout in plugins/lazuli/hooks/hooks.json


def session_summary(event: dict) -> str:
    try:
        done = subprocess.run(COMMAND, input=json.dumps(event), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError):   # not installed, not runnable, or too slow
        print("LapisLazuli hooks skipped: lapis-design-hook is unavailable; update the CLI and plugins together.",
              file=sys.stderr)
        return ""
    text = done.stdout.strip() if done.returncode == 0 else ""
    try:
        notice = json.loads(text)
    except ValueError:
        return text
    if isinstance(notice, dict) and isinstance(notice.get("systemMessage"), str):
        print(notice["systemMessage"], file=sys.stderr)
        return ""
    return text


def pre_llm_call(is_first_turn: bool = False, **kwargs) -> dict | None:
    if not is_first_turn:
        return None
    text = session_summary({"session_id": kwargs.get("session_id"), "cwd": kwargs.get("cwd") or "."})
    return {"context": text} if text else None


def register(ctx) -> None:
    ctx.register_hook("pre_llm_call", pre_llm_call)
