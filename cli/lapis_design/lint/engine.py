"""slop_lint engine: run each rule's detectors and turn what they observe into findings.

Detectors (lint/types.py) report observations; the engine decides everything else from the rule and
the run (slop/rules.yaml header, behavior/DERIVED.md "Coverage"):

- skipped result     one `skipped` finding with evidence `not-verified`, never blocking
- each hit           one finding with the rule's class and create severity; the review severity is
                     that of the first `severity.adjust` whose `when` the hit satisfies, else the
                     rule's; blocking on create `gate` in create mode, on review P0/P1 in review mode
- plan `defaults`    a `keep` entry waives the rule's hits when it names one of the rule's `keep_when` ids
                     and carries the evidence that case lists (`plan_check.default_verdict`, `keep_evidence`),
                     except for requirement rules and rules whose waiver scope is `none`
- rule `locales`     the rule runs only when the plan's brief.locales or the extract's text runs
                     include one of them; detectors restrict their own text runs (`in_locales`)
- package-hit        hits when at least `hit_when.min_members` member rules hit at the same layer
- leads              source-pattern hits, and render hits of motion-inventory auto-moving-content and
                     accessibility-tree pointer-only-control, stay open only when the same rule hits at
                     a later layer; refuted there, they are dropped; otherwise they are skipped.
                     separator-shape hits have no later layer and stay open with verdict unknown.
- behavior coverage  each probe the detector depends on (detectors.yaml `probes`) that ran partly,
                     was skipped, or has no coverage entry adds one skipped finding naming it

Plan-layer detectors that plan_check implements run through plan_check; `asset-ledger` runs through
rights_check; every other name runs from the registry in lint/detectors.
"""
from __future__ import annotations

import datetime as dt
import fnmatch
import functools
import sqlite3
from pathlib import Path
from typing import Iterable, Mapping

import yaml

from lapis_design import __version__, plan_check, shared_dir
from lapis_design.keep_evidence import Sources
from lapis_design.lint import detectors
from lapis_design.lint.types import DETECTORS, Context, Hit, Result

VERSION = __version__
LAYERS = ("plan", "source", "render", "behavior", "review")
LAYER_EVIDENCE = {"plan": "plan", "source": "source", "render": "measurement", "behavior": "runtime",
                  "review": "review"}
BLOCKING_REVIEW = {"P0", "P1"}
COVERAGE_GAPS = {"partial", "skipped"}

# Locales of rules.schema.yaml. A text run belongs to its script's locale and its language's.
_CJK = {"ko", "ja", "zh"}
_SCRIPT_LOCALE = {"latn": "latin", "cyrl": "cyrl", "grek": "grek", "arab": "arab", "hebr": "hebr",
                  "thai": "thai", "hang": "ko", "kana": "ja"}
_SUBTAG_LOCALE = {"latn": "latin", "cyrl": "cyrl", "grek": "grek", "arab": "arab", "hebr": "hebr",
                  "thai": "thai", "hang": "ko", "kore": "ko", "jpan": "ja", "hira": "ja", "kana": "ja",
                  "hans": "zh", "hant": "zh", "hani": "zh"}
_LANG_LOCALE = {"ko": "ko", "ja": "ja", "zh": "zh", "el": "grek", "he": "hebr", "yi": "hebr", "th": "thai",
                **dict.fromkeys(("ar", "fa", "ur", "ps", "sd", "ug"), "arab"),
                **dict.fromkeys(("ru", "uk", "be", "bg", "mk", "sr", "kk", "ky", "mn", "tg", "tt", "ba", "cv"),
                                "cyrl")}
# Languages written in scripts outside the rules' locales: they match no locale but `all`
_OTHER_SCRIPT_LANGS = {"hi", "bn", "ta", "te", "mr", "gu", "kn", "ml", "pa", "si", "ne", "my", "km", "lo", "ka",
                       "hy", "am", "bo", "dv"}


def lang_locale(tag: str | None) -> str | None:
    """The rules locale of a BCP 47 tag: a script subtag decides, then the language."""
    if not tag:
        return None
    parts = tag.lower().split("-")
    for sub in parts[1:]:
        if len(sub) == 4 and sub in _SUBTAG_LOCALE:
            return _SUBTAG_LOCALE[sub]
    if parts[0] in _OTHER_SCRIPT_LANGS:
        return None
    return _LANG_LOCALE.get(parts[0], "latin")


def run_locales(run: dict) -> set[str]:
    """Rules locales of one render text run, from its `script` and its `lang`."""
    lang = lang_locale(run.get("lang"))
    script = run.get("script")
    out = {lang} if lang else set()
    if script == "hani":
        out.add(lang if lang in _CJK else "zh")
    elif script in _SCRIPT_LOCALE:
        out.add(_SCRIPT_LOCALE[script])
    return out


def in_locales(run: dict, locales: Iterable[str] | None) -> bool:
    """Whether a text run is content of a rule's `locales` (no locales, or `all`, takes every run)."""
    wanted = set(locales or ())
    return not wanted or "all" in wanted or bool(run_locales(run) & wanted)


@functools.cache
def detector_probes() -> dict[str, tuple[str, ...]]:
    """Session coverage probes each detector depends on (detectors.yaml `probes`)."""
    doc = yaml.load((shared_dir() / "slop" / "detectors.yaml").read_text(encoding="utf-8"),
                    Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
    return {d["name"]: tuple(d.get("probes") or ()) for d in doc["detectors"]}


def open_lazuli(path: Path) -> sqlite3.Connection:
    """Open measured font features read-only, refusing an older lazuli schema."""
    if not Path(path).is_file():
        raise FileNotFoundError(f"lazuli database not found: {path}")
    from lazuli import db

    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        required = db.latest_version()
        if current < required:
            raise plan_check.LazuliDBUpgradeError(path, current, required)
        conn.row_factory = sqlite3.Row
    except Exception:
        conn.close()
        raise
    return conn


# ---------------------------------------------------------------- dispatch

def run_detector(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    """Run one rule's detector at one layer, outside a full lint run (plan_check uses this)."""
    if det.get("detector") == "package-hit":
        return _Run(ctx, (layer,), {}).package(det, layer)
    return _dispatch(ctx, det, rule, layer)


def _dispatch(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    name = det.get("detector")
    if layer == "plan" and name in plan_check.PLAN_DETECTORS:
        return _plan_check(ctx, det, rule)
    if name == "asset-ledger":
        return _asset_ledger(ctx, det, rule, layer)
    if name not in DETECTORS:
        detectors.load(layer)           # each module registers its names when it loads
        if name not in DETECTORS:       # a name from another layer, or none: every module decides
            detectors.load()
    spec = DETECTORS.get(name)
    if spec is None:
        return Result(skipped=f"detector {name!r} is not registered")
    if layer not in spec.layers:
        return Result(skipped=f"detector {name!r} does not run at the {layer} layer")
    try:
        return spec.fn(ctx, det, rule, layer)
    except Exception as exc:          # one broken detector must not hide every other rule's result
        return Result(skipped=f"detector {name!r} failed: {type(exc).__name__}: {exc}")


def _plan_check(ctx: Context, det: dict, rule: dict) -> Result:
    if ctx.plan is None:
        return Result(skipped="no plan given")
    hit, detail = plan_check.evaluate_plan_detector(ctx.plan, det, ctx.rules, rule=rule, ctx=ctx)
    if hit is None:
        return Result(skipped=detail)
    if not hit:
        return Result()
    location = {k: v for k, v in (("file", ctx.plan_path), ("path", det.get("path"))) if v}
    return Result(hits=[Hit(observed=detail, location=location, evidence="plan")])


def _asset_ledger(ctx: Context, det: dict, rule: dict, layer: str) -> Result:
    """rights_check is the reference implementation; its hits carry the rules.yaml rule id."""
    from lapis_design import rights_check

    check = (det.get("params") or {}).get("check")
    if ctx.ledger is None:
        return Result(skipped="no asset ledger given")
    if layer == "source" and check == "coverage" and ctx.source_root is None:
        return Result(skipped="no source tree given to look for shipped files")
    if layer == "render" and ctx.extract is None:
        return Result(skipped="no render extract given")
    if "engine:rights" not in ctx.cache:
        shipped = rights_check.shipped_files(ctx.source_root, ctx.ledger) if ctx.source_root else []
        hits = rights_check.check(ctx.ledger, ctx.lock, ctx.source_root, dt.date.today(),
                                  [ctx.extract] if ctx.extract else None, shipped=shipped)
        ctx.cache["engine:rights"] = (hits, {f["path"] for f in shipped})
    hits, files = ctx.cache["engine:rights"]
    out = []
    for h in hits:
        if h["rule_id"] != rule.get("id") or h["layer"] != layer:
            continue
        if layer == "render":
            out.append(Hit(observed=h["observed"], location={"box": h["subject"]}))
        else:
            key = "file" if h["subject"] in files else "asset"
            out.append(Hit(observed=h["observed"], location={key: h["subject"]}, evidence="source"))
    skipped = None
    if layer == "source" and check == "notices" and ctx.source_root is None:
        skipped = "recorded notice files were not looked for: no source tree given"
    return Result(hits=out, skipped=skipped)


def _lead_layers(rule: dict, layer: str, det: dict) -> tuple[str, ...] | None:
    """Later layers that confirm this detector's hits, or None when its hits are evidence of their own."""
    name, check = det.get("detector"), (det.get("params") or {}).get("check")
    checks = set(check) if isinstance(check, list) else {check}
    if layer == "source" and name == "source-pattern":
        later: tuple[str, ...] = ("render", "behavior")
    elif layer == "render" and (name == "motion-inventory" and "auto-moving-content" in checks
                                or name == "accessibility-tree" and "pointer-only-control" in checks):
        later = ("behavior",)
    elif name == "separator-shape":
        later = ()
    else:
        return None
    detect = rule.get("detect") or {}
    return tuple(c for c in later if c in detect)


# ---------------------------------------------------------------- one run

class _Run:
    def __init__(self, ctx: Context, layers: Iterable[str], probes: Mapping[str, Iterable[str]]):
        self.ctx = ctx
        wanted = set(layers)
        self.layers = tuple(layer for layer in LAYERS if layer in wanted)
        self.probes = probes
        rules = [r for r in ctx.rules.get("rules") or [] if isinstance(r, dict) and "id" in r]
        self.by_id = {r["id"]: r for r in rules}
        defaults = (ctx.plan or {}).get("defaults") or []
        self.decisions = {d["id"]: d for d in defaults if isinstance(d, dict) and "id" in d}
        self.evidence = Sources(ctx.plan or {}, ctx.ledger, ctx.design_text)
        self.memo: dict[tuple[str, str], Result | None] = {}
        self._content: set[str] | None = None

    # -- evaluation

    def outcome(self, rule: dict, layer: str) -> Result | None:
        """The rule's result at a layer, or None when the rule does not apply to this content."""
        key = (rule["id"], layer)
        if key not in self.memo:
            self.memo[key] = None                    # a package that names itself cannot recurse
            det = (rule.get("detect") or {}).get(layer)
            if det is not None and self.applies(rule):
                self.memo[key] = (self.package(det, layer) if det.get("detector") == "package-hit"
                                  else _dispatch(self.ctx, det, rule, layer))
        return self.memo[key]

    def applies(self, rule: dict) -> bool:
        wanted = set(rule.get("locales") or ("all",))
        if "all" in wanted:
            return True
        known = self.content_locales()
        return not known or bool(known & wanted)

    def content_locales(self) -> set[str]:
        """Locales of the run's content: the plan's brief.locales and the extract's text runs."""
        if self._content is None:
            brief = (self.ctx.plan or {}).get("brief") or {}
            found = {loc for tag in brief.get("locales") or [] if (loc := lang_locale(tag))}
            for vp in (self.ctx.extract or {}).get("viewports") or []:
                for run in vp.get("text") or []:
                    found |= run_locales(run)
            self._content = found
        return self._content

    def package(self, det: dict, layer: str) -> Result:
        name = (det.get("params") or {}).get("package")
        spec = (self.ctx.rules.get("packages") or {}).get(name or "")
        if not spec:
            return Result(skipped=f"package {name!r} is not defined")
        need = (spec.get("hit_when") or {}).get("min_members", 2)
        members = spec.get("members") or []
        hits, unknown = [], []
        for member in members:
            rule = self.by_id.get(member)
            if rule is None:
                unknown.append(member)
                continue
            result = self.outcome(rule, layer)       # None: not detected at this layer, cannot hit here
            if result is None:
                continue
            if result.hits:
                hits.append(member)
            elif result.skipped:
                unknown.append(member)
        if len(hits) >= need:
            return Result(hits=[Hit(observed=f"package {name}: {len(hits)} of {len(members)} members hit at the "
                                             f"{layer} layer ({need} needed): {', '.join(hits)}",
                                    evidence=LAYER_EVIDENCE[layer], refs=hits)])
        if len(hits) + len(unknown) >= need:
            return Result(skipped=f"package {name}: {len(hits)} of {need} needed members hit; "
                                  f"not judged: {', '.join(unknown)}")
        return Result()

    # -- findings

    def findings(self, rule: dict, layer: str) -> list[dict]:
        result = self.outcome(rule, layer)
        if result is None:
            return []
        det = rule["detect"][layer]
        out: list[dict] = []
        hits = list(result.hits)
        context = None
        confirm = _lead_layers(rule, layer, det)
        if hits and confirm is not None:
            if not confirm:
                context = {"verdict": "unknown", "basis": f"{det['detector']} lead; review it before acting"}
            else:
                later = [self.outcome(rule, c) if c in self.layers else None for c in confirm]
                if not any(r is not None and r.hits for r in later):
                    if not all(r is not None and not r.skipped for r in later):
                        where = " or ".join(confirm)
                        out += [self.skipped(rule, layer, f"lead not confirmed at {where}: {h.observed}",
                                             location=h.location, refs=h.refs, cause="layer") for h in hits]
                    hits = []                        # refuted where every later layer judged it
        out += [self.hit(rule, layer, det, h, context) for h in hits]
        if result.skipped:
            out.append(self.skipped(rule, layer, result.skipped, cause=result.cause))
        if layer == "behavior" and self.ctx.session is not None:
            out += self.coverage(rule, det)
        return out

    def coverage(self, rule: dict, det: dict) -> list[dict]:
        entries = self.ctx.session.get("coverage") or []
        out = []
        for probe in self.probes.get(det.get("detector"), ()):
            mine = [e for e in entries if e.get("probe") == probe]
            if not mine:
                note = f"{probe} probe has no coverage entry, so it did not run"
            else:
                gaps = [e for e in mine if e.get("status") in COVERAGE_GAPS]
                if not gaps:
                    continue
                note = "; ".join(f"{probe} probe {e['status']}"
                                 + (f" in {', '.join(e['contexts'])}" if e.get("contexts") else "")
                                 + (f": {e['reason']}" if e.get("reason") else "") for e in gaps)
            out.append(self.skipped(rule, "behavior", f"not verified: {note}", cause="probe"))
        return out

    def _base(self, rule: dict, layer: str, review: str | None, observed: str, location: dict | None) -> dict:
        severity = {"create": (rule.get("severity") or {}).get("create")}
        if review:
            severity["review"] = review
        f = {"rule_id": rule["id"], "class": rule.get("class"), "severity": severity, "layer": layer}
        if location:
            f["location"] = dict(location)
        f["observed"] = observed
        return f

    def skipped(self, rule: dict, layer: str, reason: str, location: dict | None = None,
                refs: Iterable[str] = (), cause: str = "input") -> dict:
        f = self._base(rule, layer, (rule.get("severity") or {}).get("review"), reason, location)
        refs = list(refs)
        f.update(blocking=False, evidence={"type": "not-verified", **({"refs": refs} if refs else {})},
                 status="skipped", skip_cause=cause)
        return f

    def hit(self, rule: dict, layer: str, det: dict, hit: Hit, context: dict | None) -> dict:
        sev = rule.get("severity") or {}
        create, review = sev.get("create"), sev.get("review")
        for adjust in sev.get("adjust") or []:
            if adjust.get("when") in hit.conditions:
                create = adjust.get("create", create)
                review = adjust.get("review", review)
                break
        f = self._base(rule, layer, review, hit.observed, hit.location)
        f["severity"]["create"] = create
        consequence = hit.consequence or rule.get("why")
        if consequence:
            f["consequence"] = consequence
        if rule.get("better"):
            f["fix"] = rule["better"]
        if det.get("detector") == "package-hit":
            f["package"] = (det.get("params") or {}).get("package")
        if hit.distance is not None:
            f["distance"] = hit.distance
        f["evidence"] = {"type": hit.evidence, **({"refs": list(hit.refs)} if hit.refs else {})}
        decision = self.decisions.get(rule["id"])
        waived, unfit = plan_check.default_verdict(rule, decision, self.evidence)
        if waived:
            f["context"] = {"verdict": "earned", "basis": f"plan defaults entry ({decision.get('basis')}, {decision.get('keep_when')})"}
            f.update(blocking=False, status="waived",
                     waiver=f"{decision['decision']} ({decision.get('basis')}): {decision.get('reason')}")
            return f
        if unfit:
            context = {"verdict": "unearned", "basis": f"the plan's defaults entry does not apply: {unfit}"}
        elif decision and decision.get("decision") == "reject":
            context = {"verdict": "unearned",
                       "basis": f"the plan rejects this default ({decision.get('basis')}): {decision.get('reason')}"}
        if context:
            f["context"] = context
        blocking = ((self.ctx.mode == "create" and create == "gate")
                    or (self.ctx.mode == "review" and review in BLOCKING_REVIEW))
        f.update(blocking=blocking, status="open")
        return f


# ---------------------------------------------------------------- entry points

def lint(ctx: Context, layers: Iterable[str], rules: Iterable[str] | None = None, *,
         probes: Mapping[str, Iterable[str]] | None = None) -> list[dict]:
    """Findings for every rule (ids or glob patterns in `rules`, all when empty) at the given layers,
    in rules-document order. `probes` replaces detectors.yaml's probe lists."""
    run = _Run(ctx, layers, detector_probes() if probes is None else probes)
    patterns = list(rules or ())
    out: list[dict] = []
    for rule in run.by_id.values():
        if patterns and not any(fnmatch.fnmatchcase(rule["id"], p) for p in patterns):
            continue
        if ctx.mode == "create" and (rule.get("severity") or {}).get("create") == "off":
            continue
        for layer in run.layers:
            if layer in (rule.get("detect") or {}):
                out += run.findings(rule, layer)
    return out


def report(ctx: Context, findings: list[dict], *, ledger_path: str | None = None,
           lock_path: str | None = None) -> dict:
    """A findings report (slop/finding.schema.yaml) for one lint run."""
    task = (((ctx.plan or {}).get("task") or {}).get("id")
            or ((ctx.extract or {}).get("source") or {}).get("task")
            or ((ctx.session or {}).get("source") or {}).get("task"))
    target = {k: v for k, v in (("plan", ctx.plan_path), ("extract", ctx.extract_path),
                                ("session", ctx.session_path), ("ledger", ledger_path),
                                ("source", str(ctx.source_root) if ctx.source_root else None),
                                ("lock", lock_path), ("task", task)) if v}
    output = {
        "version": 0,
        "tool": {"name": "slop_lint", "version": VERSION},
        "target": target,
        "summary": {"blocking": sum(1 for f in findings if f["blocking"]), "total": len(findings),
                    "skipped": sum(1 for f in findings if f["status"] == "skipped")},
        "findings": findings,
    }
    if ctx.cache.get("analyzers"):
        output["analyzers"] = dict(sorted(ctx.cache["analyzers"].items()))
    return output
