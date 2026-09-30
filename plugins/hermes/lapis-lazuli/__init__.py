"""LapisLazuli session summary for Hermes Agent (install/OUTPUTS.md, Hermes).

On the first turn of a session, pre_llm_call runs `lapis-design hook session-start`, the command the
lazuli SessionStart hook runs in Claude Code and Codex, and returns what it prints as context for
that turn's user message. on_session_start ignores return values, so the summary comes with the
first turn instead. A missing CLI, a failure, a timeout, or empty output adds nothing.
"""
from __future__ import annotations

import subprocess

COMMAND = ["lapis-design", "hook", "session-start"]
TIMEOUT_S = 10   # the SessionStart hook's timeout in plugins/lazuli/hooks/hooks.json


def session_summary() -> str:
    try:
        done = subprocess.run(COMMAND, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError):   # not installed, not runnable, or too slow
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def pre_llm_call(is_first_turn: bool = False, **kwargs) -> dict | None:
    if not is_first_turn:
        return None
    text = session_summary()
    return {"context": text} if text else None


def register(ctx) -> None:
    ctx.register_hook("pre_llm_call", pre_llm_call)
