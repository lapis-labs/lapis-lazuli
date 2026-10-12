"""The owner's opt-in for `lazuli adobe`, kept in the user cache (`adobe/config.json`).

The relay starts Codex and talks to a connector that belongs to the owner's account, so it stays off until
the owner turns it on. `lazuli adobe enable` asks on a terminal and refuses without one, so an agent that
runs commands without a person at the keyboard cannot turn it on for the owner. `disable` needs no terminal.
The file holds only the switch, the time, and the Codex model the relay asks for.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from lazuli import paths

DEFAULT_MODEL = "gpt-6-luna"
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
ENABLE_HOW = "run `lazuli adobe enable` yourself in a terminal"


class NotEnabled(Exception):
    """The relay is off; the message says how the owner turns it on."""


def adobe_dir() -> Path:
    return paths.cache_dir() / "adobe"


def config_path() -> Path:
    return adobe_dir() / "config.json"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load() -> dict:
    """The stored settings, or {} when none were stored or the file is unreadable."""
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def is_enabled() -> bool:
    return load().get("enabled") is True


def model() -> str:
    value = load().get("model")
    return value if isinstance(value, str) and _MODEL.fullmatch(value) else DEFAULT_MODEL


def require_enabled() -> dict:
    """The settings, or NotEnabled when the owner has not turned the relay on."""
    found = load()
    if found.get("enabled") is not True:
        raise NotEnabled("`lazuli adobe` is off. It starts Codex to ask the Adobe Fonts connector of your own account, "
                         f"so only you can turn it on: {ENABLE_HOW} (`lazuli adobe status` says what it needs).")
    return found


def check_model(value: str) -> str:
    if not _MODEL.fullmatch(value):
        raise ValueError(f"{value!r} is not a Codex model id (letters, digits, dots, hyphens)")
    return value


def owner_present() -> bool:
    """Whether a person is at a terminal: both standard input and output are terminals."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def owner_confirms(prompt: str) -> bool:
    """Ask on the terminal and take only a typed `yes`."""
    if not owner_present():
        return False
    try:
        return input(prompt + " Type yes to continue: ").strip().lower() == "yes"
    except EOFError:
        return False


def write(settings: dict) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=1) + "\n", encoding="utf-8")
    return path


def enable(chosen_model: str | None = None) -> Path:
    return write({"version": 1, "enabled": True, "enabled_at": now(), "model": check_model(chosen_model or model())})


def disable() -> Path:
    return write({**load(), "version": 1, "enabled": False, "disabled_at": now()})
