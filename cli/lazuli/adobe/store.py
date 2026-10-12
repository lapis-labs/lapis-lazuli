"""The records of connector calls, in the user cache beside the lazuli database and never in it.

`adobe/records.jsonl` holds one cleaned result per read call, with provenance `adobe-connector`, the tool, the
arguments lazuli sent, and the time. `adobe/actions.jsonl` holds one row per guarded action (activate, kit): the
font, the owner's quoted words, what the stream showed, and the outcome. Neither file is read by measurement,
calibration, evaluation, catalog labels, `local fonts`, or `search --similar-to`; the lazuli database has no table
for them. A test reads every module of those paths and fails when one imports this package.
"""
from __future__ import annotations

import json
from pathlib import Path

from lazuli.adobe import PROVENANCE, config
from lazuli.adobe.relay import Outcome

SCHEMA = 1


def records_path() -> Path:
    return config.adobe_dir() / "records.jsonl"


def actions_path() -> Path:
    return config.adobe_dir() / "actions.jsonl"


def _append(path: Path, row: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return path


def _usage(outcome: Outcome) -> dict:
    usage = outcome.usage or {}
    return {k: usage[k] for k in ("input_tokens", "cached_input_tokens", "output_tokens") if isinstance(usage.get(k), int)}


def save_record(outcome: Outcome, kept: dict) -> dict:
    """Append the cleaned result of a read call and return the row."""
    row = {"schema": SCHEMA, "provenance": PROVENANCE, "fetched_at": config.now(), "tool": outcome.tool,
           "model": outcome.model, "arguments": outcome.arguments, "seconds": outcome.seconds,
           "tokens": _usage(outcome), "result": kept}
    _append(records_path(), row)
    return row


def log_action(row: dict) -> dict:
    """Append one row about a guarded action and return it (with its provenance and time)."""
    row = {"schema": SCHEMA, "provenance": PROVENANCE, "at": config.now(), **row}
    _append(actions_path(), row)
    return row


def _read(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def records() -> list[dict]:
    return _read(records_path())


def actions() -> list[dict]:
    return _read(actions_path())
