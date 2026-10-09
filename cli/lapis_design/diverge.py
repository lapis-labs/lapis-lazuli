"""`diverge`: rough first views that differ in the core objects' representation and in color allocation.

Between the first and the second turn of the direction conversation (`direction.py`) a create run makes K rough first
views (`start`, three by default), each on a different reference direction. The CLI owns the draws; the agent writes each
rough as `.lapis/diverge/<task>/C<n>/index.html` with its card `card.yaml` (`diverge/card.schema.yaml`); the CLI
measures the renders, makes the contact sheet, and seals the set. Everything the CLI writes is under
`.lapis/state/diverge/<task>/`, a folder only `lapis-design` writes (`order.CLI_OWNED`).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

STEP = "diverge"


def folder(root: Path, task: str) -> Path:
    """Where the agent's roughs and cards live."""
    return root / ".lapis" / "diverge" / task


def state_dir(root: Path, task: str) -> Path:
    """Where the CLI keeps the seed, draws, fingerprints, distances, contact sheet, and seal."""
    return root / ".lapis" / "state" / "diverge" / task


def sealed(root: Path, task: str) -> dict[str, Any] | None:
    """`seal.json` of `task`, or None while the set is not sealed."""
    try:
        found = json.loads((state_dir(root, task) / "seal.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) and isinstance(found.get("candidates"), dict) else None


def draw_records(root: Path, task: str) -> list[dict[str, Any]]:
    """The lines of `draws.jsonl` in order; a line that is no mapping is left out (`check` reports a broken chain)."""
    try:
        lines = (state_dir(root, task) / "draws.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    found = []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            found.append(item)
    return found


def candidate_ids(root: Path, task: str) -> list[str]:
    """The candidates the draws gave, in the order they were first drawn."""
    return list(dict.fromkeys(d["candidate"] for d in draw_records(root, task) if isinstance(d.get("candidate"), str)))


def variant_floor(root: Path, task: str) -> int:
    """How many `Pick:` lines the answers held when the latest owner-requested variant was added, or -1 when there is
    none: a pick counts for the second turn only when it comes after that many."""
    seen = [d.get("picks_seen") for d in draw_records(root, task) if d.get("variant")]
    return max([n for n in seen if isinstance(n, int)], default=-1)


def card(root: Path, task: str, candidate: str) -> dict[str, Any] | None:
    """The card of `candidate` as written, or None when it is missing or not a mapping."""
    try:
        found = yaml.safe_load((folder(root, task) / candidate / "card.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return found if isinstance(found, dict) else None
