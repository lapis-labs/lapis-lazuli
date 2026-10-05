"""The detector interface shared by slop_lint and plan_check (fixed; change only with every caller).

A detector is a function registered by name and layers:

    @detector("font-fallback", layers=("render",))
    def font_fallback(ctx: Context, det: dict, rule: dict, layer: str) -> Result: ...

`det` is the rule's `detect.<layer>` entry (detector, params, threshold, region, anchors, list,
family, path); `rule` is the whole rule. The detector reports what it observed and never decides
severity, waivers, or blocking: the engine does that from the rule. It returns
`Result(hits=[...])`, or `Result(skipped="why")` when its input is missing or it cannot judge here,
so a missing observation never reads as a pass.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class Hit:
    observed: str                                   # the visible or measured property, >= 3 characters
    location: dict[str, Any] = field(default_factory=dict)
    # finding.schema location keys: file, path, viewport, box, context, flow, step, asset
    evidence: str = "measurement"                   # plan | source | image | runtime | measurement | review | not-verified
    refs: list[str] = field(default_factory=list)   # evidence references (paths, box ids, URLs)
    distance: float | None = None                   # typicality or reference distance, when used
    conditions: frozenset[str] = frozenset()        # severity.adjust `when` texts this hit satisfies
    consequence: str | None = None                  # effect on the user, when the detector knows it


@dataclass
class Result:
    hits: list[Hit] = field(default_factory=list)
    skipped: str | None = None                      # why the detector could not judge (input missing, ...)
    cause: str = "input"                             # input | layer | probe | reviewer, for skipped findings


@dataclass
class Context:
    rules: dict                                     # the whole rules document (lists, packages, rules)
    mode: str = "create"                            # create | review
    plan: dict | None = None
    plan_path: str | None = None
    extract: dict | None = None                     # render extract (render/extract.schema.yaml)
    extract_path: str | None = None
    session: dict | None = None                     # behavior session, derived values filled
    session_path: str | None = None
    source_root: Path | None = None                 # project source tree for source-layer detectors
    ledger: dict | None = None
    lock: dict | None = None
    design_text: str | None = None                  # text of the file the plan declares as context.design
    refs: list[dict] = field(default_factory=list)     # reference profiles (extract format with `reference`)
    corpus: list[dict] = field(default_factory=list)   # typicality corpus entries (extract format)
    lazuli: sqlite3.Connection | None = None           # the user's lazuli DB, for font features
    project_root: Path = field(default_factory=Path.cwd) # base for implementation/capture evidence in explorations
    source_files: list[str] | None = None             # draft's exact source set; None means the ordinary whole tree
    cache: dict[str, Any] = field(default_factory=dict)  # per-run memo shared by detectors

    def list_values(self, key: str, locale: str | None = None) -> list[str]:
        """Values of a rules `lists` entry, for one locale or scope key, or all of them."""
        values = ((self.rules.get("lists") or {}).get(key) or {}).get("values") or {}
        if locale is not None:
            return list(values.get(locale, []))
        return [v for items in values.values() for v in items]


DetectorFn = Callable[[Context, dict, dict, str], Result]


@dataclass(frozen=True)
class Detector:
    name: str
    layers: tuple[str, ...]
    fn: DetectorFn


DETECTORS: dict[str, Detector] = {}


def detector(name: str, *, layers: tuple[str, ...]) -> Callable[[DetectorFn], DetectorFn]:
    def register(fn: DetectorFn) -> DetectorFn:
        if name in DETECTORS:
            raise ValueError(f"detector {name!r} registered twice")
        DETECTORS[name] = Detector(name, tuple(layers), fn)
        return fn
    return register
