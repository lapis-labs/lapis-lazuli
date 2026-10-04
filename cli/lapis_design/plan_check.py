"""plan_check v0 — validate a LapisLazuli plan file.

Checks, in order:
  1. schema     JSON Schema validation against src/shared/plan/schema.yaml
  2. defaults   evaluate plan-layer detectors from rules.yaml; every hit needs a `defaults` entry. A keep
                waives a hit only when it names, as `keep_when`, one of the ids the rule lists and, when that
                case lists evidence (keep_evidence), carries evidence that holds; a rule that lists none takes
                no keep. Detectors this module does not implement run from the slop_lint registry
                (cli/lapis_design/lint), with the lazuli database for font features.
  3. contract   when DESIGN.md is declared, token values must come from it or be proposed changes
  4. fonts      every type role must be in the fonts lock with a delivery path for the platform, files
                from a channel that may ship them, and a recorded grant for each planned use
  5. references reference profiles must exist; study-mode references are flagged for the release gate
  6. flows      flow ids are unique; an exit flow's pair names an existing flow of a joining kind

Output follows src/shared/slop/finding.schema.yaml. Exit code 1 when any finding is blocking.

By default, plan-layer rules come from the CLI's shared slop/rules.yaml. A font lock is read from
ROOT/.lapis/fonts.lock.json when present, and a keep's design evidence is looked up in the file the plan
declares as context.design, under ROOT. Font measurements use $LAZULI_DB when set, otherwise the lazuli
user-cache database when present. Explicit --rules, --lock, and --lazuli-db paths take precedence.

A plan larger than 1,000,000 bytes, or nested more than 100 levels deep, is not parsed (`parse_plan`):
it gets one schema.invalid finding. The exit-plan hook, the release gate, and the slop lint layer
`plan` apply the same limits.

Usage:
  lapis-design plan check PLAN [--rules RULES] [--lock LOCK] [--schema SCHEMA]
                               [--root ROOT] [--lazuli-db DB] [--format json|text]
  lapis-design plan check --from-markdown HARNESS_PLAN.md [...]   # validate the
         lapis-plan block embedded in a harness plan (read-only; "-" reads stdin)
  lapis-design plan check PLAN --summary   # markdown summary for harness plans; a plan that fails
         the schema gets the findings report (exit 1) instead of a summary
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import sqlite3
import sys
from pathlib import Path
from itertools import chain
from typing import Any, Iterable, NamedTuple

import yaml
from jsonschema import Draft202012Validator

from lapis_design import __version__, shared_dir, system_fonts

_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

VERSION = __version__
WEB_DELIVERY = {"self-host", "adobe-web-project", "google-fonts-api"}
APP_PLATFORMS = {"ios", "android", "desktop", "embedded"}
# Channels whose files cannot be the shipped files: a subscription client's synced copy, an OS copy,
# or an install of unknown provenance (fonts/lock.schema.yaml, source).
NON_SHIPPABLE_SOURCES = {"adobe-sync", "sandoll", "system", "user-installed"}


class LazuliDBOpenError(Exception):
    """A selected lazuli database could not be opened."""


class LazuliDBUpgradeError(sqlite3.DatabaseError):
    """An older schema, with its version retained for selection-specific guidance."""

    def __init__(self, path: Path, current: int, required: int):
        self.path = path
        self.current = current
        self.required = required
        super().__init__(self.message())

    def message(self, *, explicit: bool = False) -> str:
        return lazuli_db_upgrade_message(self.path, self.current, self.required, explicit=explicit)

# ---------------------------------------------------------------- plan path grammar

_SEGMENT = re.compile(r"([a-z_][a-z0-9_]*)((?:\[[^\]]*\])*)")
_SELECTOR = re.compile(r"\[([^\]]*)\]")


def resolve(doc: Any, path: str) -> list[Any]:
    """Resolve a plan path (see detectors.yaml) to a flat list of values."""
    current = [doc]
    for part in path.split("."):
        m = _SEGMENT.fullmatch(part)
        if not m:
            raise ValueError(f"bad path segment: {part!r}")
        name, selectors = m.group(1), m.group(2)
        nxt = []
        for node in current:
            if isinstance(node, dict) and name in node:
                nxt.append(node[name])
        for sel in _SELECTOR.findall(selectors):
            filtered = []
            for node in nxt:
                if not isinstance(node, list):
                    continue
                if sel == "*":
                    filtered.extend(node)
                elif sel.isdigit():
                    idx = int(sel)
                    if idx < len(node):
                        filtered.append(node[idx])
                elif sel.startswith("?") and "=" in sel:
                    field, values = sel[1:].split("=", 1)
                    allowed = set(values.split("|"))
                    filtered.extend(i for i in node if isinstance(i, dict) and str(i.get(field)) in allowed)
                else:
                    raise ValueError(f"bad selector: [{sel}]")
            nxt = filtered
        current = nxt
    return current


# ---------------------------------------------------------------- helpers

def load_yaml(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return yaml.load(fh, Loader=_YAML_LOADER)

_UNLOADED_PLAN = object()


# ---------------------------------------------------------------- plan input

MAX_PLAN_BYTES = 1_000_000
MAX_PLAN_DEPTH = 100
PLAN_TOO_LARGE = f"the plan is larger than {MAX_PLAN_BYTES:,} bytes and was not parsed"
PLAN_TOO_DEEP = f"the plan is nested more than {MAX_PLAN_DEPTH} levels deep and was not parsed"


class PlanOverLimit:
    """Stands for a plan that was not parsed because it is too large or too deep. It is neither a mapping
    nor a list, so `expansion_problem` reports `problem` as the one schema.invalid finding; every entry
    point that reads a plan runs that check before it reads a section."""

    def __init__(self, problem: str):
        self.problem = problem


class _Scan(NamedTuple):
    too_deep: bool                       # collections nest deeper than the limit
    question: int | None                 # index of the first `?` in a plain scalar of a flow collection
    explicit_key: int | None             # index of the first `?` key indicator that opens a pair in a flow list
    quoted: list[tuple[int, int]]        # spans of the quoted scalars, kept only when the text has a tab


def _scan(text: str, limit: int, spans: bool = False) -> _Scan:
    """What the C parser's events say about `text`, in one pass.

    `too_deep`: the scan stops at the first event past the limit, so a 50,000-level block costs no more than a
    shallow one. Tokens would undercount: an indentless block list makes no token per level.

    `question` and `explicit_key`: the two readings of a `?` in a flow collection that libyaml 0.2.5 accepts and
    PyYAML's pure-Python scanner, and so every tool built on `yaml.safe_load`, does not. A plain scalar that holds
    one (`{ answers: What now? }`): libyaml keeps the text, PyYAML ends the scalar at the `?` and then fails, always.
    An explicit key opening a pair inside a flow list (`[? a: b]`, `[?]]`: libyaml also lets a stray `]` through):
    PyYAML reads the first and refuses the second. Both are found even when the text is too deep."""
    depth = flow = 0
    question = explicit_key = None
    quoted: list[tuple[int, int]] = []
    for event in yaml.parse(text, Loader=_YAML_LOADER):
        if isinstance(event, yaml.ScalarEvent):
            if event.style in ("'", '"'):
                if spans:              # a span starts at the quote: an anchor or tag before it is not quoted text
                    start, end = event.start_mark.index, event.end_mark.index
                    quoted.append((max(text.find(event.style, start, end), start), end))
            elif flow and question is None and "?" in event.value:     # plain: '' from libyaml, None from PyYAML
                question = max(text.find("?", event.start_mark.index, event.end_mark.index), event.start_mark.index)
        elif isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
            depth += 1
            if event.flow_style:
                index = event.start_mark.index
                if flow and explicit_key is None and isinstance(event, yaml.MappingStartEvent) \
                        and text[index:index + 1] == "?":
                    explicit_key = index
                flow += 1
            if depth > limit:
                return _Scan(True, question, explicit_key, quoted)
        elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
            depth -= 1
            flow -= bool(flow)             # a flow collection holds only flow ones, so an end seen inside one is its own
    return _Scan(False, question, explicit_key, quoted)


def _stray_tab(text: str, quoted: list[tuple[int, int]]) -> int | None:
    """Index of the first tab that is not inside a quoted scalar, or None. PyYAML's pure-Python scanner refuses
    such a tab (outside a comment) and libyaml reads it as blank space; a tab inside a quoted scalar is text to both."""
    at = 0
    for start, end in [*quoted, (len(text), len(text))]:
        found = text.find("\t", at, start)
        if found >= 0:
            return found
        at = end
    return None


def _refusal(text: str, index: int, problem: str) -> yaml.parser.ParserError:
    """The error PyYAML would give for `problem` at `text[index]`, with its line and column."""
    column = index - (text.rfind("\n", 0, index) + 1)
    mark = yaml.error.Mark("<unicode string>", index, text.count("\n", 0, index), column, text, index)
    return yaml.parser.ParserError(None, None, problem, mark)


PURE_READ_MAX = 64 * 1024     # a text up to this size may be read by the pure-Python loader (about 0.15 s here)


def parse_plan(text: str) -> Any:
    """Parse plan YAML text; the one reader of a plan for every entry point. Text over MAX_PLAN_BYTES or
    nested deeper than MAX_PLAN_DEPTH is not parsed: the result is a PlanOverLimit. A YAML error
    propagates as yaml.YAMLError.

    A plan reads as `yaml.safe_load` reads it, and a plan another tool refuses is refused here, wherever libyaml
    would read more. The document is read with libyaml when it is installed (800 KB of padding costs about 0.5 s
    where the pure-Python loader takes seconds), and the readings `_scan` and `_stray_tab` find libyaml accepting
    and PyYAML refusing are refused at their position without reading the text again: a `?` inside a plain
    scalar of a flow collection, an explicit `?` key in a flow list, and a tab outside a quoted scalar. Of the
    last two PyYAML reads some (`[? a: b]`; a tab in a comment), so a text up to PURE_READ_MAX is left to the
    pure-Python loader, which then decides and names the fault; a larger one is refused. A text libyaml cannot
    read goes to the pure-Python loader the same way, and a larger one gets libyaml's own error. The pure-Python
    loader never sees a text over the limits or nested deeper than the limit, so no padding makes a read slow."""
    if len(text) > MAX_PLAN_BYTES or len(text.encode("utf-8", "surrogatepass")) > MAX_PLAN_BYTES:
        return PlanOverLimit(PLAN_TOO_LARGE)
    small = len(text) <= PURE_READ_MAX
    tabbed = "\t" in text
    try:
        scan = _scan(text, MAX_PLAN_DEPTH, tabbed)
    except yaml.YAMLError:
        if small:
            return yaml.safe_load(text)         # PyYAML names the fault, or reads what libyaml refuses
        raise
    if scan.too_deep:
        return PlanOverLimit(PLAN_TOO_DEEP)
    if scan.question is not None:
        raise _refusal(text, scan.question, "found a `?` inside a plain scalar of a flow collection; "
                       "quote the value")
    if scan.explicit_key is not None:
        if small:
            return yaml.safe_load(text)
        raise _refusal(text, scan.explicit_key, "found a `?` key indicator inside a flow list; "
                       "write the pair as `key: value`")
    if tabbed and (tab := _stray_tab(text, scan.quoted)) is not None:
        if small:
            return yaml.safe_load(text)
        raise _refusal(text, tab, "found a tab outside a quoted string; indent and separate with spaces")
    return yaml.load(text, Loader=_YAML_LOADER)


def read_plan(path: Path) -> Any:
    """`parse_plan` of a file, read only as far as the size limit. OSError, ValueError (bad UTF-8), and
    yaml.YAMLError propagate."""
    with open(path, "rb") as fh:
        data = fh.read(MAX_PLAN_BYTES + 1)
    if len(data) > MAX_PLAN_BYTES:
        return PlanOverLimit(PLAN_TOO_LARGE)
    return parse_plan(data.decode("utf-8"))


def read_plan_or_raise(path: Path) -> Any:
    """`read_plan` for a caller that stops on a plan it cannot use: an over-limit plan is a ValueError."""
    plan = read_plan(path)
    if isinstance(plan, PlanOverLimit):
        raise ValueError(f"{path}: {plan.problem}")
    return plan


def yaml_reason(exc: Exception) -> str:
    """One line for an unreadable document. A YAML error leads with its problem and where it is
    (line:column), not the context PyYAML puts first ("while parsing a flow sequence")."""
    if isinstance(exc, yaml.MarkedYAMLError) and exc.problem:
        problem = exc.problem.splitlines()[0]
        mark = exc.problem_mark
        return f"{problem} at {mark.line + 1}:{mark.column + 1}" if mark else problem
    return str(exc).splitlines()[0] if str(exc) else type(exc).__name__


class LockError(ValueError):
    """The fonts lock cannot be used; the message is one line."""


def load_lock(path: Path) -> dict:
    """The fonts lock, validated against fonts/lock.schema.yaml as `slop lint` validates it."""
    from lapis_design.lint.cli import LintError, _load     # lint.cli imports this module

    try:
        return _load(path, "lock")
    except LintError as exc:
        raise LockError(str(exc).splitlines()[0]) from exc


def in_range(value: float, bounds: list[float] | None, wrap: bool = False) -> bool:
    if bounds is None:
        return True
    lo, hi = bounds
    if wrap and lo > hi:                      # hue ranges may wrap around 360
        return value >= lo or value <= hi
    return lo <= value <= hi


def oklch_in_region(oklch: list[float], bounds: dict) -> bool:
    l, c, h = oklch
    return (in_range(l, bounds.get("l")) and in_range(c, bounds.get("c"))
            and in_range(h, bounds.get("h"), wrap=True))


def edit_distance(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def finding(rule_id: str, cls: str, observed: str, *, blocking: bool, create: str, review: str | None = None,
            path: str | None = None, fix: str | None = None, status: str = "open",
            evidence: str = "plan", waiver: str | None = None, file: str | None = None) -> dict:
    f: dict[str, Any] = {
        "rule_id": rule_id,
        "class": cls,
        "severity": {"create": create, **({"review": review} if review else {})},
        "layer": "plan",
        "observed": observed,
        "blocking": blocking,
        "evidence": {"type": evidence},
        "status": status,
    }
    loc = {k: v for k, v in (("file", file), ("path", path)) if v}
    if loc:
        f["location"] = loc
    if fix:
        f["fix"] = fix
    if waiver:
        f["waiver"] = waiver
    return f


# ---------------------------------------------------------------- checks

EXPANSION_LIMIT = ("the plan expands to more than 10,000 keys and values or 1,000,000 characters "
                   "and bytes; aliases count each time they are used")
UNSUPPORTED_PLAN_VALUE = "the plan contains an unsupported YAML value outside top-level extensions"
MAX_PLAN_INTEGER = 10**4300


def expansion_problem(plan: Any) -> str | None:
    """Count keys and values at each alias use outside top-level extensions."""
    if isinstance(plan, PlanOverLimit):
        return plan.problem
    values = characters = 0
    active: set[int] = set()
    stack = [(iter((plan,)), None)]
    while stack:
        children, parent_id = stack[-1]
        try:
            node = next(children)
        except StopIteration:
            stack.pop()
            if parent_id is not None:
                active.remove(parent_id)
            continue
        values += 1
        if isinstance(node, (str, bytes)):
            characters += len(node)
        if values > 10_000 or characters > 1_000_000:
            return EXPANSION_LIMIT
        if isinstance(node, (dict, list)):
            identity = id(node)
            if identity in active:
                return EXPANSION_LIMIT
            active.add(identity)
            if node is plan and isinstance(node, dict):
                items = ((key, value) for key, value in node.items()
                         if not isinstance(key, str) or not key.startswith("x-"))
                children = chain.from_iterable(items)
            else:
                children = chain.from_iterable(node.items()) if isinstance(node, dict) else iter(node)
            stack.append((children, identity))
        elif isinstance(node, bytes):
            return UNSUPPORTED_PLAN_VALUE
        elif isinstance(node, float):
            if not math.isfinite(node):
                return UNSUPPORTED_PLAN_VALUE
        elif isinstance(node, int):
            if abs(node) >= MAX_PLAN_INTEGER:
                return UNSUPPORTED_PLAN_VALUE
        elif node is not None and not isinstance(node, (str, bool)):
            return UNSUPPORTED_PLAN_VALUE
    return None


def check_expansion(plan: Any, plan_file: str) -> list[dict]:
    problem = expansion_problem(plan)
    return ([finding("schema.invalid", "requirement", problem, blocking=True, create="gate",
                     review="P1", file=plan_file)] if problem else [])


def non_string_key_paths(document: Any, path: str = "") -> Iterable[str]:
    """Build paths only for offending keys; aliases are visited once."""
    visited: set[int] = set()
    stack = [(document, None, False)]
    while stack:
        node, link, bad_key = stack.pop()
        if bad_key:
            parts = []
            cursor = link
            while cursor is not None:
                cursor, key = cursor
                parts.append(str(key))
            parts.reverse()
            yield "/".join((path, *parts)) if path else "/".join(parts)
        if not isinstance(node, (dict, list)) or id(node) in visited:
            continue
        visited.add(id(node))
        if isinstance(node, dict):
            for key, value in reversed(node.items()):
                if node is document and isinstance(key, str) and key.startswith("x-"):
                    continue
                stack.append((value, (link, key), not isinstance(key, str)))
        else:
            for index in range(len(node) - 1, -1, -1):
                stack.append((node[index], (link, index), False))


def check_non_string_keys(plan: Any, plan_file: str) -> list[dict]:
    return [finding("schema.invalid", "requirement", "plan mapping key must be a string",
                    blocking=True, create="gate", review="P1", path=path, file=plan_file)
            for path in non_string_key_paths(plan)]


def check_schema(plan: dict, schema: dict, plan_file: str) -> list[dict]:
    out = []
    try:
        for err in sorted(Draft202012Validator(schema).iter_errors(plan), key=lambda e: list(e.path)):
            loc = "/".join(str(p) for p in err.path) or "(root)"
            out.append(finding("schema.invalid", "requirement", err.message, blocking=True, create="gate",
                               review="P1", path=loc, file=plan_file))
    except RecursionError:
        return [finding("schema.invalid", "requirement", "plan nesting is too deep to validate",
                        blocking=True, create="gate", review="P1", file=plan_file)]
    except (ValueError, TypeError, OverflowError):
        return [finding("schema.invalid", "requirement", "plan could not be validated against its schema",
                        blocking=True, create="gate", review="P1", file=plan_file)]
    return out


# Plan-layer detectors implemented here; every other plan-layer name runs from the slop_lint
# detector registry (lint/engine.run_detector).
PLAN_DETECTORS = frozenset({"plan-distinct-values", "plan-value-range", "plan-missing", "package-hit",
                            "plan-palette-region", "plan-section-sequence"})


def distinct_families(families: list[str]) -> list[str]:
    """The distinct values among family names, one entry each: letter case is ignored, and the names
    the platform answers with its own sans (fonts/system-fonts.yaml `platform_sans`) are one value,
    shown with the spellings the plan used."""
    sans = system_fonts.platform_sans()
    groups: dict[str | None, dict[str, str]] = {}
    for family in families:
        name = family.strip()
        groups.setdefault(None if name.casefold() in sans else name.casefold(), {}).setdefault(name.casefold(), name)
    return sorted("/".join(spellings.values()) for spellings in groups.values())


def evaluate_plan_detector(plan: dict, det: dict, rules: dict | None = None, *, rule: dict | None = None,
                           ctx: Any = None) -> tuple[bool | None, str]:
    """Return (hit, detail). hit is None when the detector cannot run here. Names outside
    PLAN_DETECTORS run from the detector registry with `ctx` (lint/types.Context; a plan-only
    context when omitted) and `rule`, the rule whose detect.plan entry `det` is."""
    name = det.get("detector")
    path = det.get("path")
    threshold = det.get("threshold") or {}
    params = det.get("params") or {}
    if name == "plan-distinct-values":
        values = [str(v) for v in resolve(plan, path)]
        distinct = distinct_families(values) if str(path).endswith(".family") else sorted(set(values))
        hit = len(values) >= params.get("min_items", 1) and len(distinct) < threshold.get("distinct_min", 2)
        return (hit, f"{len(values)} values, {len(distinct)} distinct: {distinct}" if hit else "")
    if name == "plan-value-range":
        values = [v for v in resolve(plan, path) if isinstance(v, (int, float)) and not isinstance(v, bool)]
        lo, hi = threshold.get("min"), threshold.get("max")
        out = [v for v in values if (lo is not None and v < lo) or (hi is not None and v > hi)]
        return (bool(out), f"{out} outside [{lo}, {hi}]" if out else "")
    if name == "plan-missing":
        modes = params.get("modes")
        if modes and plan.get("mode") not in modes:
            return (False, "")
        missing = not [v for v in resolve(plan, path) if v not in (None, "", [], {})]
        return (missing, f"{path} is missing" if missing else "")
    if name == "package-hit":
        return evaluate_package(plan, params.get("package"), rules or {}, ctx)
    if name == "plan-palette-region":
        bounds = (det.get("region") or {}).get("bounds", {})
        values = [v for v in resolve(plan, path) if isinstance(v, list) and len(v) == 3]
        hits = [v for v in values if oklch_in_region(v, bounds)]
        return (bool(hits), f"{len(hits)} of {len(values)} colors fall in the region: {hits}" if hits else "")
    if name == "plan-section-sequence":
        seq = [str(v) for v in resolve(plan, path)]
        templates = (det.get("params") or {}).get("templates", [])
        max_d = float((det.get("params") or {}).get("max_distance", 0.34))
        if not seq or not templates:
            return (False, "")
        best = min(templates, key=lambda t: edit_distance(seq, t) / max(len(seq), len(t)))
        dist = edit_distance(seq, best) / max(len(seq), len(best))
        return (dist <= max_d, f"sequence {seq} is {dist:.2f} from template {best}")
    return _registry(plan, det, rules or {}, rule, ctx)


def _registry(plan: dict, det: dict, rules: dict, rule: dict | None, ctx: Any) -> tuple[bool | None, str]:
    from lapis_design.lint.engine import run_detector   # lazy: the detector modules import this module
    from lapis_design.lint.types import Context

    result = run_detector(ctx or Context(rules=rules, plan=plan), det, rule or {"detect": {"plan": det}}, "plan")
    if result.hits:
        return (True, "; ".join(h.observed for h in result.hits))
    if result.skipped:
        return (None, result.skipped)
    return (False, "")


def evaluate_package(plan: dict, package: str | None, rules: dict, ctx: Any = None) -> tuple[bool | None, str]:
    """A package hits when enough member rules hit at the plan layer (hit_when.min_members)."""
    spec = (rules.get("packages") or {}).get(package or "")
    if not spec:
        return (None, f"package {package!r} is not defined")
    by_id = {r.get("id"): r for r in rules.get("rules", [])}
    need = (spec.get("hit_when") or {}).get("min_members", 2)
    hits, unknown = [], []
    for member in spec.get("members", []):
        member_rule = by_id.get(member) or {}
        det = (member_rule.get("detect") or {}).get("plan")
        if not det or det.get("detector") == "package-hit":
            unknown.append(member)
            continue
        hit, _ = evaluate_plan_detector(plan, det, rules, rule=member_rule, ctx=ctx)
        if hit:
            hits.append(member)
        elif hit is None:
            unknown.append(member)
    if len(hits) >= need:
        return (True, f"package {package}: {len(hits)} of {need} needed members hit: {hits}")
    if len(hits) + len(unknown) >= need:
        return (None, f"package {package}: {len(hits)} members hit, {unknown} could not be evaluated")
    return (False, "")


def keep_ids(rule: dict) -> list[str]:
    """The ids of the cases a rule's `keep_when` lists."""
    return [case["id"] for case in rule.get("keep_when") or [] if isinstance(case, dict) and "id" in case]


def default_verdict(rule: dict, decision: dict | None, sources: Any) -> tuple[bool, str | None]:
    """Whether a plan's `defaults` entry waives a hit of `rule`, and why an entry that cannot does not apply.
    A rule that is a requirement or whose waiver scope is none takes no entry. A keep waives only when the
    entry names one of the ids the rule lists as `keep_when` and, when that case lists evidence, carries
    evidence that holds in `sources` (keep_evidence.Sources: the plan, the asset ledger, the design text); a
    rule that lists no case takes no keep. A reject, or no entry, is (False, None): the finding stays as it was."""
    if not decision:
        return False, None
    name = rule.get("id")
    if rule.get("class") == "requirement" or (rule.get("waiver") or {}).get("scope") == "none":
        return False, f"{name} takes no defaults entry"
    if decision.get("decision") != "keep":
        return False, None
    ids = keep_ids(rule)
    named = decision.get("keep_when")
    if named in ids:
        from lapis_design import keep_evidence   # imports this module's resolve, so not at load time

        case = next(c for c in rule["keep_when"] if isinstance(c, dict) and c.get("id") == named)
        missing = keep_evidence.gap(case, decision, sources)
        return (False, missing) if missing else (True, None)
    if not ids:
        return False, f"{name} lists no keep_when case, so no keep fits it"
    accepted = ", ".join(ids)
    if named is None:
        return False, f"the keep names no keep_when id; {name} accepts: {accepted}"
    return False, f"keep_when {named!r} is not one of {name}'s ids; it accepts: {accepted}"


def _defaults_fix(rule: dict) -> str:
    """What to write in `defaults` for a hit nothing has decided yet."""
    better = rule.get("better") or ""
    if rule.get("class") == "requirement" or (rule.get("waiver") or {}).get("scope") == "none":
        return better
    ids = keep_ids(rule)
    if not ids:
        return f"Add a defaults entry for {rule['id']} that rejects it with a reason; it lists no keep_when case. {better}".rstrip()
    return (f"Add a defaults entry for {rule['id']}: reject it with a reason, or keep it naming one keep_when id "
            f"({', '.join(ids)}). {better}").rstrip()


def read_design_text(plan: dict, root: Path) -> str | None:
    """The text of the design contract the plan declares in `context.design`, or None when none is declared
    or the file cannot be read."""
    design = (plan.get("context") or {}).get("design")
    if not design:
        return None
    try:
        return (root / design["path"]).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def check_defaults(plan: dict, rules: dict, plan_file: str, lazuli_db: Path | None = None,
                   sources: Any = None) -> list[dict]:
    """Plan-layer rules; registry detectors share one context, with the lazuli DB for font features.
    `sources` (keep_evidence.Sources) is where a keep's evidence is looked up; the plan alone when absent."""
    if sources is None:
        from lapis_design.keep_evidence import Sources

        sources = Sources(plan)
    names = {det.get("detector") for r in rules.get("rules", []) if (det := (r.get("detect") or {}).get("plan"))}
    ctx = None
    if names - PLAN_DETECTORS:
        from lapis_design.lint.engine import open_lazuli
        from lapis_design.lint.types import Context

        try:
            lazuli = open_lazuli(lazuli_db) if lazuli_db else None
        except LazuliDBUpgradeError as exc:
            raise LazuliDBOpenError(str(exc)) from exc
        except (RuntimeError, sqlite3.Error, OSError) as exc:
            raise LazuliDBOpenError(f"lazuli database {lazuli_db} cannot be opened: {exc}") from exc
        ctx = Context(rules=rules, plan=plan, plan_path=plan_file, lazuli=lazuli)
    try:
        return _check_defaults(plan, rules, plan_file, ctx, sources)
    finally:
        if ctx is not None and ctx.lazuli is not None:
            ctx.lazuli.close()


def _check_defaults(plan: dict, rules: dict, plan_file: str, ctx: Any, sources: Any) -> list[dict]:
    out = []
    decided = {d["id"]: d for d in plan.get("defaults", []) if isinstance(d, dict) and "id" in d}
    for rule in rules.get("rules", []):
        det = (rule.get("detect") or {}).get("plan")
        if not det:
            continue
        sev = rule.get("severity", {})
        hit, detail = evaluate_plan_detector(plan, det, rules, rule=rule, ctx=ctx)
        if hit is None:
            out.append(finding(rule["id"], rule["class"], detail, blocking=False, create="info",
                               status="skipped", evidence="not-verified", file=plan_file))
            continue
        if not hit:
            continue
        decision = decided.get(rule["id"])
        waived, unfit = default_verdict(rule, decision, sources)
        if waived or (decision and decision["decision"] == "reject" and unfit is None):
            out.append(finding(rule["id"], rule["class"], detail, blocking=False, create="info",
                               status="waived" if waived else "open",
                               waiver=f'{decision["decision"]} ({decision["basis"]}): {decision["reason"]}',
                               path=det.get("path"), file=plan_file))
        else:
            blocking = sev.get("create") == "gate"
            out.append(finding(rule["id"], rule["class"], f"{detail}; the plan's defaults entry does not apply: {unfit}" if unfit
                               else detail, blocking=blocking, create=sev.get("create", "warn"),
                               review=sev.get("review"), path=det.get("path"), file=plan_file,
                               fix=_defaults_fix(rule)))
    return out


def check_contract(plan: dict, root: Path, plan_file: str) -> list[dict]:
    design = (plan.get("context") or {}).get("design")
    if not design:
        return []
    out = []
    design_path = root / design["path"]
    if not design_path.exists():
        return [finding("contract.missing-design", "contract", f"{design['path']} is declared but not found",
                        blocking=True, create="gate", review="P1", path="context.design.path", file=plan_file)]
    text = design_path.read_text(encoding="utf-8")
    proposed = {c.get("path", "") for c in plan.get("proposed_design_changes", []) or []}
    for i, role in enumerate(resolve(plan, "tokens.color.roles[*]")):
        name = role.get("name", f"#{i}")
        if "ref" in role:
            anchor = role["ref"].split("#", 1)[-1].split(".")[-1]
            if anchor and anchor not in text:
                out.append(finding("contract.unknown-ref", "contract", f"color role {name!r} references {role['ref']!r}, "
                                   f"which does not appear in {design['path']}", blocking=True, create="gate",
                                   review="P2", path=f"tokens.color.roles[{i}].ref", file=plan_file))
        elif not any(name in p for p in proposed):
            out.append(finding("contract.value-outside-contract", "contract",
                               f"color role {name!r} defines its own value while {design['path']} is the contract",
                               blocking=True, create="gate", review="P2", path=f"tokens.color.roles[{i}]",
                               file=plan_file, fix="Reference the contract token, or list the change in "
                                                   "proposed_design_changes with a reason."))
    return out


def check_fonts(plan: dict, lock: dict | None, plan_file: str) -> list[dict]:
    roles = resolve(plan, "tokens.type.roles[*]")
    if not roles:
        return []
    families = [role.get("family", "") for role in roles]
    generic = [system_fonts.is_generic(family) for family in families]
    named = list(dict.fromkeys(family for family, is_keyword in zip(families, generic) if not is_keyword))
    if not named:
        return []
    task = plan.get("task", {}).get("id")
    platforms = set(plan.get("brief", {}).get("platform", []))
    if lock is None:
        fix = f"Run `lazuli lock` for each named face: {', '.join(named)}."
        if any(generic):
            fix += " A generic keyword in a role needs no lock entry."
        return [finding("font.no-lock", "requirement", "type roles are set but no fonts lock was given",
                        blocking=True, create="gate", review="P1", path="tokens.type.lock", file=plan_file,
                        fix=fix)]
    out = []
    for i, role in enumerate(roles):
        if generic[i]:
            continue
        entries = [f for f in lock.get("fonts", []) if f.get("family") == role.get("family")]
        where = f"tokens.type.roles[{i}]"
        if not entries:
            out.append(finding("font.not-locked", "requirement", f"{role.get('family')!r} ({role.get('role')}) "
                               "is not in the fonts lock", blocking=True, create="gate", review="P1",
                               path=where, file=plan_file, fix="Lock the font with `lazuli lock`."))
            continue
        entry = entries[0]
        if task and task not in entry.get("used_by", []):
            out.append(finding("font.lock-task", "quality", f"{entry['family']!r} is locked but not for task {task!r}",
                               blocking=False, create="warn", review="P3", path=where, file=plan_file))
        lic = entry.get("license", {})
        delivery = entry.get("delivery")
        needed = []                                 # (use, ships font files)
        if "web" in platforms:
            if delivery not in WEB_DELIVERY:
                out.append(finding("font.no-web-delivery", "requirement",
                                   f"{entry['family']!r} has delivery {delivery!r} on a web target",
                                   blocking=True, create="gate", review="P1", path=where, file=plan_file,
                                   fix="Choose a font with a web delivery path, or keep it as a local fallback only."))
            else:
                needed.append(("web", delivery == "self-host"))
        if platforms & APP_PLATFORMS and delivery != "system-only":
            needed.append(("app", True))
        if any(ships for _, ships in needed) and entry.get("source") in NON_SHIPPABLE_SOURCES:
            out.append(finding("font.channel-mismatch", "requirement",
                               f"{entry['family']!r} would ship files from source {entry.get('source')!r}",
                               blocking=True, create="gate", review="P0", path=where, file=plan_file,
                               fix="Ship files from the upstream release or a purchased license that covers the use, "
                                   "or use a hosted delivery path."))
        for use, ships in needed:
            grant = "unknown" if lic.get("kind") == "unknown" else (lic.get("uses") or {}).get(use, "unknown")
            if grant == "not-allowed":
                out.append(finding("font.use-not-granted", "requirement",
                                   f"the license of {entry['family']!r} does not allow {use} use",
                                   blocking=True, create="gate", review="P0", path=where, file=plan_file,
                                   fix="Obtain a license for this use or choose another font."))
            elif grant == "unknown":
                if ships:
                    out.append(finding("font.use-unknown", "requirement",
                                       f"no recorded {use} grant for {entry['family']!r}, whose files would ship",
                                       blocking=True, create="gate", review="P1", path=where, file=plan_file,
                                       fix="Read the governing license for this use and record it with `lazuli lock`."))
                else:
                    out.append(finding("font.use-unknown", "quality",
                                       f"no recorded {use} grant for {entry['family']!r}",
                                       blocking=False, create="warn", review="P2", path=where, file=plan_file,
                                       fix="Confirm the hosted delivery terms cover this use."))
        if lic.get("source_class") in ("catalog-summary", "file-metadata"):
            out.append(finding("font.license-hint-only", "quality",
                               f"the license of {entry['family']!r} comes from a {lic['source_class']}",
                               blocking=False, create="warn", review="P2", path=where, file=plan_file,
                               fix="Confirm the original license before release."))
    return out


def check_references(plan: dict, root: Path, plan_file: str) -> list[dict]:
    out = []
    for i, ref in enumerate(plan.get("references", []) or []):
        where = f"references[{i}]"
        profile = ref.get("profile")
        if profile and not (root / profile).exists():
            out.append(finding("reference.profile-missing", "quality", f"profile {profile!r} does not exist",
                               blocking=False, create="warn", review="P2", path=where, file=plan_file,
                               fix="Run `lazuli ref capture` for this reference."))
        if ref.get("mode") == "study":
            out.append(finding("reference.study-artifact", "requirement",
                               f"{ref.get('source')!r} is used in study mode; the release gate will block this output",
                               blocking=False, create="info", path=where, file=plan_file))
    return out


# Exit flows and the kinds of flow each may reverse (behavior/DERIVED.md, Flows)
EXIT_PAIRS = {
    "cancel-subscription": {"subscribe", "purchase"},
    "delete-account": {"signup"},
    "withdraw-consent": {"grant-consent"},
    "unsubscribe": {"grant-consent", "signup", "subscribe"},
}


def check_flows(plan: dict, plan_file: str) -> list[dict]:
    out = []
    flows = plan.get("flows", []) or []
    by_id: dict[str, dict] = {}
    for i, flow in enumerate(flows):
        if flow["id"] in by_id:
            out.append(finding("flow.duplicate-id", "requirement", f"flow id {flow['id']!r} is used more than once",
                               blocking=True, create="gate", review="P1", path=f"flows[{i}]", file=plan_file,
                               fix="Give each flow its own id."))
        by_id.setdefault(flow["id"], flow)
    for i, flow in enumerate(flows):
        where, kind, pair = f"flows[{i}]", flow["kind"], flow.get("pair")
        if pair is None:
            if kind in EXIT_PAIRS:
                out.append(finding("flow.pair-missing", "quality",
                                   f"exit flow {flow['id']!r} does not name the flow it reverses",
                                   blocking=False, create="warn", review="P2", path=where, file=plan_file,
                                   fix="Add `pair` with the joining flow so leaving can be compared with joining."))
        elif kind not in EXIT_PAIRS:
            out.append(finding("flow.pair-unexpected", "requirement",
                               f"{kind} flow {flow['id']!r} has a pair; only exit flows reverse another flow",
                               blocking=True, create="gate", review="P1", path=where, file=plan_file,
                               fix="Remove `pair`, or give the flow an exit kind."))
        elif pair not in by_id:
            out.append(finding("flow.pair-unknown", "requirement", f"flow {flow['id']!r} pairs with unknown flow {pair!r}",
                               blocking=True, create="gate", review="P1", path=where, file=plan_file,
                               fix="Point `pair` at a flow id in this plan."))
        elif by_id[pair]["kind"] not in EXIT_PAIRS[kind]:
            out.append(finding("flow.pair-kind", "requirement",
                               f"{kind} flow {flow['id']!r} pairs with {by_id[pair]['kind']} flow {pair!r}",
                               blocking=True, create="gate", review="P1", path=where, file=plan_file,
                               fix=f"Pair it with a flow of kind {' or '.join(sorted(EXIT_PAIRS[kind]))}."))
    return out


# ---------------------------------------------------------------- harness plan modes

_FENCE = re.compile(r"^```yaml[^\n]*\n(.*?)^```", re.M | re.S)


def extract_lapis_block(markdown: str) -> str | None:
    """Return the first ```yaml block whose info string or first line marks it as a lapis plan."""
    for m in _FENCE.finditer(markdown):
        header = markdown[m.start():markdown.index("\n", m.start())]
        body = m.group(1)
        first = body.lstrip().splitlines()[0] if body.strip() else ""
        if "lapis-plan" in header or first.startswith("# lapis-plan"):
            return body
    return None


def summarize(plan: dict) -> str:
    """Human-readable summary for a harness plan (Claude Code, Codex, Oh-My-Pi, Hermes)."""
    b = plan.get("brief", {})
    d = plan.get("direction", {})
    read = (d.get("read") or {})
    dials = d.get("dials") or {}
    lines = [f"### Design decisions — {plan.get('task', {}).get('title', '')} (`{plan.get('task', {}).get('id', '')}`)", ""]
    lines.append(f"- **Job:** {b.get('one_job', '')}")
    if read:
        lines.append(f"- **Read:** {read.get('text') or ', '.join(read.get('surface_mode', []))}")
    if dials:
        lines.append("- **Dials:** " + ", ".join(f"{k} {v}" for k, v in dials.items()))
    if plan.get("world_materials"):
        lines.append("- **World materials:** " + ", ".join(plan["world_materials"]))
    if d.get("concept"):
        lines.append(f"- **Concept:** {d['concept']}")
    for lever in d.get("levers") or []:
        lines.append(f"- **Lever:** {lever}")
    sig = (plan.get("layout") or {}).get("signature")
    if sig:
        lines.append(f"- **Signature:** {sig}")
    for r in resolve(plan, "tokens.type.roles[*]"):
        lines.append(f"- **Type ({r.get('role')}):** {r.get('family')}")
    for ex in plan.get("explorations") or []:
        subject = " ".join([str(ex.get("decision")), *(ex.get("covers") or [])])
        if ex.get("fixed_by"):
            lines.append(f"- **Fixed ({subject}):** by the {ex['fixed_by']} — {ex.get('reason', '')}")
            continue
        options = ", ".join(f"{c.get('name')} ({c.get('source')})" for c in ex.get("candidates") or [])
        lines.append(f"- **Compared ({subject}):** {options}; chose {ex.get('chosen')}; "
                     f"runner-up lost: {ex.get('runner_up_lost')}")
    for ref in plan.get("references", []) or []:
        lines.append(f"- **Reference:** {ref.get('source')} — {ref.get('rights')}, {ref.get('mode')}; "
                     f"take {', '.join(ref.get('take', []))}")
    for dft in plan.get("defaults", []) or []:
        kept = f" ({dft['keep_when']})" if dft.get("keep_when") else ""
        lines.append(f"- **Default {dft.get('id')}:** {dft.get('decision')}{kept} — {dft.get('reason')}")
    return "\n".join(lines)


# ---------------------------------------------------------------- entry point

def check_structure(plan: Any, schema_path: Path, plan_file: str) -> list[dict]:
    """schema.invalid findings from the first failing structural check. Every later check, and the
    summary, reads the plan's sections and assumes this returned nothing."""
    findings = check_expansion(plan, plan_file)
    if not findings:
        findings = check_non_string_keys(plan, plan_file)
    if not findings:
        findings = check_schema(plan, load_yaml(schema_path), plan_file)
    return findings


def _target_task(plan: Any) -> dict:
    """The report target's task id, when the plan names one; a wrong-typed plan names none."""
    task = plan.get("task") if isinstance(plan, dict) else None
    task_id = task.get("id") if isinstance(task, dict) else None
    return {"task": task_id} if isinstance(task_id, str) else {}


def run(plan_path: Path | None, rules_path: Path | None, lock_path: Path | None, schema_path: Path,
        root: Path, plan: Any = _UNLOADED_PLAN, plan_label: str | None = None,
        lazuli_db: Path | None = None) -> dict:
    if plan is _UNLOADED_PLAN:
        plan = read_plan(plan_path)
    plan_file = plan_label or str(plan_path)
    findings = check_structure(plan, schema_path, plan_file)
    if not findings:                           # code checks assume a structurally valid plan
        if rules_path:
            from lapis_design.keep_evidence import Sources

            sources = Sources(plan, design_text=read_design_text(plan, root))
            findings += check_defaults(plan, load_yaml(rules_path), plan_file, lazuli_db, sources)
        findings += check_contract(plan, root, plan_file)
        lock = load_lock(lock_path) if lock_path and lock_path.exists() else None
        findings += check_fonts(plan, lock, plan_file)
        findings += check_references(plan, root, plan_file)
        findings += check_flows(plan, plan_file)
    blocking = sum(1 for f in findings if f["blocking"])
    return {
        "version": 0,
        "tool": {"name": "plan_check", "version": VERSION},
        "target": {"plan": plan_file, **_target_task(plan)},
        "summary": {"blocking": blocking, "total": len(findings),
                    "skipped": sum(1 for f in findings if f["status"] == "skipped")},
        "findings": findings,
    }


def skipped_note(summary: dict) -> str:
    """`, 21 skipped: not judged` for a summary with skipped findings, else nothing: a skipped finding
    was not judged and is never a defect."""
    return f", {summary['skipped']} skipped: not judged" if summary.get("skipped") else ""


def _format_text(report: dict) -> Iterable[str]:
    s = report["summary"]
    yield f"plan_check {report['tool']['version']}: {s['blocking']} blocking, {s['total']} total{skipped_note(s)}"
    for f in report["findings"]:
        mark = "BLOCK" if f["blocking"] else f["severity"]["create"].upper()
        where = f.get("location", {}).get("path", "")
        yield f"  [{mark}] {f['rule_id']} {where} — {f['observed']}"
        if f.get("fix"):
            yield f"          fix: {f['fix']}"


def default_lock(root: Path, explicit: Path | None) -> Path | None:
    """Choose an explicit font lock or the project lock when it exists."""
    if explicit is not None:
        return explicit
    candidate = root / ".lapis" / "fonts.lock.json"
    return candidate if candidate.is_file() else None


def lazuli_db_upgrade_message(path: Path, current: int, required: int, *, explicit: bool = False) -> str:
    command = f"LAZULI_DB={shlex.quote(str(path))} lazuli local fonts" if explicit else "lazuli local fonts"
    return (f"lazuli database {path} is at migration {current}; this lapis-design needs {required}; "
            f"upgrade it with `{command}`")


def default_lazuli_db(explicit: Path | None) -> tuple[Path | None, bool]:
    """Choose the DB path and whether it came from the optional user cache."""
    if explicit is not None:
        return explicit, False
    from lazuli.paths import db_path

    candidate = db_path()
    if os.environ.get("LAZULI_DB"):
        return candidate, False
    if not candidate.exists():
        return None, False
    if not candidate.is_file():
        print(f"warning: lazuli database {candidate} cannot be opened; font measurements unavailable",
              file=sys.stderr)
        return None, False
    try:
        from lazuli import db

        conn = sqlite3.connect(candidate.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            current = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
        required = db.latest_version()
        if current < required:
            print(f"warning: {lazuli_db_upgrade_message(candidate, current, required)}; "
                  "this run checks without font measurements", file=sys.stderr)
            return None, False
    except (RuntimeError, sqlite3.Error, OSError):
        print(f"warning: lazuli database {candidate} cannot be opened; font measurements unavailable",
              file=sys.stderr)
        return None, False
    return candidate, True


def main(argv: list[str] | None = None, prog: str = "lapis-design plan check") -> int:
    ap = argparse.ArgumentParser(prog=prog, description=__doc__.split("\n")[0])
    ap.add_argument("plan", type=Path, nargs="?")
    ap.add_argument("--from-markdown", dest="from_markdown",
                    help="harness plan markdown containing a lapis-plan block ('-' for stdin)")
    ap.add_argument("--summary", action="store_true",
                    help="print a markdown summary of the plan and exit; a plan that fails the schema gets "
                         "the findings report (per --format) and exit 1 instead, and a summary does not "
                         "mean the plan has no blocking findings")
    ap.add_argument("--rules", type=Path, help="default: slop/rules.yaml in the CLI's shared contracts")
    ap.add_argument("--lock", type=Path, help="default: ROOT/.lapis/fonts.lock.json when present")
    ap.add_argument("--schema", type=Path, help="default: plan/schema.yaml in the CLI's shared contracts")
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--lazuli-db", type=Path,
                    help="lazuli database with font measurements (default: $LAZULI_DB, else user cache if present)")
    ap.add_argument("--format", choices=["json", "text"], default="text")
    args = ap.parse_args(argv)
    plan, label = _UNLOADED_PLAN, None
    if args.from_markdown:
        label = f"{args.from_markdown}#lapis-plan"
    elif args.plan is None:
        ap.error("give a plan file or --from-markdown")
    else:
        label = str(args.plan)
    try:
        if args.from_markdown:
            md = sys.stdin.read() if args.from_markdown == "-" else Path(args.from_markdown).read_text(encoding="utf-8")
            block = extract_lapis_block(md)
            if block is None:
                print("no lapis-plan block found; nothing to check")
                return 0
            plan = parse_plan(block)
        else:
            plan = read_plan(args.plan)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"plan check: {label} cannot be read: {yaml_reason(exc)}", file=sys.stderr)
        return 2
    shared = shared_dir()
    schema = args.schema or shared / "plan" / "schema.yaml"
    try:
        load_yaml(schema)                       # every run below reads it; an unreadable one is not a finding
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"plan check: schema {schema} cannot be read: {yaml_reason(exc)}", file=sys.stderr)
        return 2
    # A plan that fails the structural checks (empty, not a mapping, a wrong-typed section) has nothing
    # safe to summarize; the checks below report it as schema.invalid.
    if args.summary and not check_structure(plan, schema, label):
        print(summarize(plan))
        return 0
    lazuli_db, from_user_cache = default_lazuli_db(args.lazuli_db)
    if lazuli_db and not lazuli_db.is_file():
        ap.error(f"lazuli database not found: {lazuli_db}")
    rules = args.rules if args.rules is not None else shared / "slop" / "rules.yaml"
    lock = default_lock(args.root, args.lock)
    try:
        try:
            report = run(args.plan, rules, lock, schema, args.root, plan=plan, plan_label=label,
                         lazuli_db=lazuli_db)
        except LazuliDBOpenError as exc:
            if not from_user_cache:
                if isinstance(exc.__cause__, LazuliDBUpgradeError):
                    print(exc.__cause__.message(explicit=args.lazuli_db is not None), file=sys.stderr)
                    return 2
                ap.error(str(exc))
            print(f"warning: {exc}; this run checks without font measurements", file=sys.stderr)
            report = run(args.plan, rules, lock, schema, args.root, plan=plan, plan_label=label,
                         lazuli_db=None)
    except LockError as exc:
        print(f"plan check: {exc}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("\n".join(_format_text(report)))
    return 1 if report["summary"]["blocking"] else 0


if __name__ == "__main__":
    sys.exit(main())
