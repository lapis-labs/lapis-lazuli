"""slop_lint v0 — run the slop rules' detectors and report findings.

Reads the rules (default: slop/rules.yaml in the CLI's shared contracts) and whichever inputs are
given: the plan, a source tree, a render extract, a behavior session, the asset ledger and fonts
lock, reference profiles, a typicality corpus, and the lazuli database. The lock defaults to
./.lapis/fonts.lock.json when present; the database defaults to $LAZULI_DB, else the user cache
file when present. Explicit paths take precedence. Each input is checked against its schema first.
A keep's design evidence is looked up in the file the plan declares as context.design, read from the
working directory.
Layers default to every layer whose input was given (plan, source, render, behavior), plus review
in review mode when a plan or an extract was given.

Output follows src/shared/slop/finding.schema.yaml with tool `slop_lint`. The printed result is a summary: the
verdict line, every blocking finding with its fix, and the other findings by rule id; `-o OUT` writes the full
report as JSON and `--json` prints it. A run narrowed by
--layer or --rule belongs in .lapis/lint/<task>.narrow.json, not in the full report the release gate reads.
When an optional CJK analyzer runs, `analyzers` names its locale and installed version.
A source or corpus file that is a link resolving outside the folder it was found in is not read, and a
folder that is a link in the source tree is never followed; the report's `scope.unread_links` lists
them (a folder with a trailing `/`) and a warning on stderr names them.
Exit code 1 when any finding is blocking, 2 when an input cannot be used.

Usage:
  lapis-design slop lint [--rules RULES] [--plan PLAN] [--extract EXTRACT] [--session SESSION]
                         [--source DIR] [--ledger LEDGER] [--lock LOCK] [--ref PROFILE ...]
                         [--corpus DIR|FILE] [--lazuli-db DB] [--mode create|review]
                         [--layer LAYER ...] [--rule ID ...] [-o OUT] [--json]
"""
from __future__ import annotations

import argparse
import fnmatch
import functools
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable
from dataclasses import replace

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from lapis_design import shared_dir
from lapis_design.lint import engine
from lapis_design.lint.types import Context
from lapis_design.plan_check import (default_lazuli_db, default_lock, expansion_problem, non_string_key_paths,
                                     read_design_text, read_plan)
from lapis_design.summary import DISPUTE_FOOTER, finding_lines, floor_lines, rest_lines, skipped_note

SCHEMAS = {
    "rules": ("slop", "rules.schema.yaml"),
    "plan": ("plan", "schema.yaml"),
    "extract": ("render", "extract.schema.yaml"),
    "session": ("behavior", "session.schema.yaml"),
    "ledger": ("assets", "ledger.schema.yaml"),
    "lock": ("fonts", "lock.schema.yaml"),
    "report": ("slop", "finding.schema.yaml"),
}
DOC_SUFFIXES = {".json", ".yaml", ".yml"}


class LintError(Exception):
    """An input that cannot be used, or a report that does not match the finding schema."""


@functools.cache
def _validator(kind: str) -> Draft202012Validator:
    folder, name = SCHEMAS[kind]
    schema = yaml.load((shared_dir() / folder / name).read_text(encoding="utf-8"),
                       Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def problems(doc: Any, kind: str) -> list[str]:
    """Schema problems of a document, as `pointer: message` lines."""
    if kind == "plan":
        if problem := expansion_problem(doc):
            return [f"(root): {problem}"]
        keys = list(non_string_key_paths(doc))
        if keys:
            return [f"{path}: plan mapping key must be a string" for path in keys]
    try:
        errors = sorted(_validator(kind).iter_errors(doc), key=lambda e: list(map(str, e.absolute_path)))
        return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in errors]
    except RecursionError:
        if kind != "plan":
            raise
        return ["(root): plan nesting is too deep to validate"]
    except (ValueError, TypeError, OverflowError):
        return ["(root): document could not be validated against its schema"]


def _load(path: Path, kind: str, label: str | None = None) -> Any:
    label = label or kind
    if not path.is_file():
        raise LintError(f"{label} not found: {path}")
    try:
        if kind == "plan":       # the reader and limits every plan entry point shares
            doc = read_plan(path)
        else:
            text = path.read_text(encoding="utf-8")
            doc = (json.loads(text) if path.suffix.lower() == ".json"
                   else yaml.load(text, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader)))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise LintError(f"{label} {path} cannot be read: {exc}") from exc
    found = problems(doc, kind)
    if found:
        more = f" (and {len(found) - 3} more)" if len(found) > 3 else ""
        raise LintError(f"{label} {path} does not match its schema: {'; '.join(found[:3])}{more}")
    return doc


def _corpus(path: Path, skipped: list[str]) -> list[dict]:
    """Corpus entries tagged `_corpus` with their corpus name: the first folder under a corpus
    directory (entries directly in it take the directory's name), or a single file's folder. Inside a
    directory, a file that is a link resolving outside it is not read; its path is added to `skipped`."""
    if path.is_file():
        files = [(path, path.parent.name)]
    elif path.is_dir():
        files = []
        base = path.resolve()
        for f in sorted(path.rglob("*")):
            if f.is_file() and f.suffix.lower() in DOC_SUFFIXES:
                if not f.resolve().is_relative_to(base):
                    skipped.append(f.relative_to(path).as_posix())
                    continue
                parts = f.relative_to(path).parts
                files.append((f, parts[0] if len(parts) > 1 else path.name))
    else:
        raise LintError(f"corpus not found: {path}")
    return [{**_load(f, "extract", "corpus entry"), "_corpus": name} for f, name in files]


def _warn_links(kind: str, skipped: list[str], folder: Path | None) -> None:
    """Say on stderr which links were passed over: a file link leading out of `folder`, or a folder link
    (ending in `/`), which is never followed."""
    if skipped:
        shown = ", ".join(skipped[:5]) + (f" (and {len(skipped) - 5} more)" if len(skipped) > 5 else "")
        print(f"warning: {len(skipped)} {kind} link(s) in {folder} were not read: file links that point "
              f"outside it and folder links (ending in /) are not followed: {shown}", file=sys.stderr)


def default_layers(*, plan: bool, source: bool, extract: bool, session: bool, mode: str) -> list[str]:
    given = {"plan": plan, "source": source, "render": extract, "behavior": session,
             "review": mode == "review" and (plan or extract)}
    return [layer for layer in engine.LAYERS if given[layer]]


def run(*, rules: Path | None = None, plan: Path | None = None, extract: Path | None = None,
        session: Path | None = None, source: Path | None = None, ledger: Path | None = None,
        lock: Path | None = None, refs: Iterable[Path] = (), corpus: Path | None = None,
        lazuli_db: Path | None = None, mode: str = "create", layers: Iterable[str] | None = None,
        rule_ids: Iterable[str] = (), draft: Path | None = None, page: str | None = None) -> dict:
    """Load the inputs, lint, and return a schema-valid findings report; LintError otherwise."""
    if mode not in ("create", "review"):
        raise LintError(f"mode must be create or review, not {mode!r}")
    lock = default_lock(Path("."), lock)
    explicit_db = lazuli_db is not None
    lazuli_db, from_user_cache = default_lazuli_db(lazuli_db)
    rules_doc = _load(rules or shared_dir() / "slop" / "rules.yaml", "rules")
    plan_doc = _load(plan, "plan") if plan else None
    extract_doc = _load(extract, "extract", "render extract") if extract else None
    session_doc = _load(session, "session", "behavior session") if session else None
    if session_doc is not None and plan_doc is not None:
        from lapis_design.behavior import derive_session

        session_doc = derive_session(session_doc, plan_doc.get("flows"))
    if source and not source.is_dir():
        raise LintError(f"source tree not found: {source}")
    draft_scope = None
    if draft:
        from lapis_design.draft_scope import select

        try:
            _, draft_scope = select(draft, source, extract_doc, page)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            raise LintError(str(exc)) from exc
    layers = list(layers or default_layers(plan=bool(plan), source=bool(source), extract=bool(extract),
                                           session=bool(session), mode=mode))
    if not layers:
        raise LintError("nothing to lint: give a plan, a source tree, a render extract, or a behavior session")
    unknown = [layer for layer in layers if layer not in engine.LAYERS]
    if unknown:
        raise LintError(f"unknown layer: {', '.join(unknown)}")
    available = set(default_layers(plan=bool(plan), source=bool(source), extract=bool(extract),
                                   session=bool(session), mode=mode))
    missing = [layer for layer in engine.LAYERS if layer in layers and layer not in available]
    if missing:
        required = {"plan": "a plan (--plan)", "source": "a source tree (--source)",
                    "render": "a render extract (--extract)", "behavior": "a behavior session (--session)",
                    "review": "review mode (--mode review) and a plan (--plan) or render extract (--extract)"}
        raise LintError("; ".join(f"layer {layer} requires {required[layer]}" for layer in missing))
    layers = [layer for layer in engine.LAYERS if layer in layers]
    rule_ids = list(rule_ids)
    ids = [r.get("id", "") for r in rules_doc.get("rules") or []]
    unmatched = [p for p in rule_ids if not any(fnmatch.fnmatchcase(i, p) for i in ids)]
    if unmatched:
        raise LintError(f"no rule matches: {', '.join(unmatched)}")
    if lazuli_db and not lazuli_db.is_file():
        raise LintError(f"lazuli database not found: {lazuli_db}")
    corpus_links: list[str] = []
    ctx = Context(
        rules=rules_doc, mode=mode,
        plan=plan_doc, plan_path=str(plan) if plan else None,
        extract=extract_doc, extract_path=str(extract) if extract else None,
        session=session_doc, session_path=str(session) if session else None,
        source_root=source,
        project_root=source.resolve() if source else Path.cwd(),
        source_files=draft_scope["sources"] if draft_scope else None,
        ledger=_load(ledger, "ledger", "asset ledger") if ledger else None,
        lock=_load(lock, "lock", "fonts lock") if lock else None,
        design_text=read_design_text(plan_doc, Path(".")) if plan_doc else None,
        refs=[_load(p, "extract", "reference profile") for p in refs],
        corpus=_corpus(corpus, corpus_links) if corpus else [],
    )
    if lazuli_db:
        try:
            ctx.lazuli = engine.open_lazuli(lazuli_db)
        except (RuntimeError, sqlite3.Error, OSError) as exc:
            if isinstance(exc, engine.plan_check.LazuliDBUpgradeError):
                if not from_user_cache:
                    raise LintError(exc.message(explicit=explicit_db)) from exc
                print(f"warning: {exc}; this run checks without font measurements", file=sys.stderr)
            elif not from_user_cache:
                raise LintError(f"lazuli database {lazuli_db} cannot be opened: {exc}") from exc
            else:
                print(f"warning: lazuli database {lazuli_db} cannot be opened; "
                      f"font measurements unavailable: {exc}", file=sys.stderr)
    try:
        findings = engine.lint(ctx, layers, rule_ids)
        specimen_findings = []
        deferred_findings = []
        if draft_scope:
            from lapis_design.draft_scope import partition

            findings, deferred_findings = partition(findings)
            specimens = replace(ctx, source_files=draft_scope["excluded_sources"], cache={})
            specimen_findings = engine.lint(specimens, ["source"], rule_ids) if specimens.source_files else []
    finally:
        if ctx.lazuli is not None:
            ctx.lazuli.close()
    unread = {kind: sorted(set(links)) for kind, links in
              (("source", ctx.cache.get("source.skipped_links") or []), ("corpus", corpus_links)) if links}
    _warn_links("source", unread.get("source", []), source)
    _warn_links("corpus", unread.get("corpus", []), corpus)
    report = engine.report(ctx, findings, ledger_path=str(ledger) if ledger else None,
                           lock_path=str(lock) if lock else None)
    report["scope"] = {"layers": layers}
    if draft_scope:
        report["target"]["task"] = draft_scope["task"]
        report["scope"]["draft"] = draft_scope
        report["specimen_findings"] = specimen_findings
        report["deferred_findings"] = deferred_findings
    if rule_ids and any(not any(fnmatch.fnmatchcase(i, pattern) for pattern in rule_ids) for i in ids):
        report["scope"]["rules"] = rule_ids
    if rules is not None and rules.resolve() != (shared_dir() / "slop" / "rules.yaml").resolve():
        report["scope"]["rules_file"] = str(rules)
    if unread:
        report["scope"]["unread_links"] = unread
    found = problems(report, "report")
    if found:
        raise LintError("the report does not match slop/finding.schema.yaml: " + "; ".join(found[:5]))
    return report


def _scope_line(scope: dict) -> str:
    """What ran: the layers, and whatever left part of the input out (a narrowed rule set, links that were not read)."""
    parts = ["layers " + ", ".join(scope["layers"])]
    if "rules" in scope:
        parts.append("narrowed by --rule " + ", ".join(scope["rules"]))
    if "rules_file" in scope:
        parts.append(f"rules from {scope['rules_file']}")
    if draft := scope.get("draft"):
        parts.append(f"draft {draft['url']}; {len(draft['sources'])} shown sources; "
                     f"{len(draft['excluded_sources'])} specimen sources separate")
    for kind, links in (scope.get("unread_links") or {}).items():
        shown = ", ".join(links[:3]) + (f" (+{len(links) - 3} more)" if len(links) > 3 else "")
        parts.append(f"{len(links)} {kind} link(s) not read: {shown}")
    return "  scope: " + "; ".join(parts)


def _summary_lines(report: dict, out: Path | None) -> list[str]:
    """The printed result: the verdict, the scope, each blocking finding with its fix, the others by rule id."""
    s, findings = report["summary"], report["findings"]
    lines = [f"slop_lint: {s['blocking']} blocking, {s['total']} findings{skipped_note(s)}"
             + (f" -> {out}" if out else "")]
    if report.get("scope"):
        lines.append(_scope_line(report["scope"]))
    lines += finding_lines((f for f in findings if f["blocking"]), here=report["target"].get("plan"))
    lines += rest_lines(findings)
    if report.get("scope", {}).get("draft"):
        lines.append(f"  separately: {len(report['specimen_findings'])} specimen findings; "
                     f"{len(report['deferred_findings'])} contract/token findings deferred to release")
    if findings and not out:
        lines.append("  every finding in full: --json, or -o PATH to write the report")
    return lines + floor_lines(s) + [DISPUTE_FOOTER]


def main(argv: list[str] | None = None, prog: str = "lapis-design slop lint") -> int:
    ap = argparse.ArgumentParser(prog=prog, description=__doc__.split("\n")[0])
    ap.add_argument("--rules", type=Path, help="default: slop/rules.yaml in the CLI's shared contracts")
    ap.add_argument("--plan", type=Path)
    ap.add_argument("--extract", type=Path, help="render extract (render check)")
    ap.add_argument("--session", type=Path, help="behavior session (behavior check)")
    ap.add_argument("--source", type=Path, help="project source tree")
    ap.add_argument("--draft", type=Path, help="pre-show record .lapis/drafts/<task>.yaml; scope the shown page, not its candidates")
    ap.add_argument("--page", help="exact shown URL when --draft lists several pages")
    ap.add_argument("--ledger", type=Path, help="asset ledger")
    ap.add_argument("--lock", type=Path, help="default: ./.lapis/fonts.lock.json when present")
    ap.add_argument("--ref", type=Path, action="append", default=[], help="reference profile (repeatable)")
    ap.add_argument("--corpus", type=Path, help="typicality corpus: a directory of entries, or one entry")
    ap.add_argument("--lazuli-db", type=Path,
                    help="lazuli database with font measurements (default: $LAZULI_DB, else user cache if present)")
    ap.add_argument("--mode", choices=("create", "review"), default="create")
    ap.add_argument("--layer", choices=engine.LAYERS, action="append",
                    help="layer to run (repeatable; requires its input; default: every layer whose input was given). "
                         "Narrows the run: write it with -o .lapis/lint/<task>.narrow.json")
    ap.add_argument("--rule", action="append", default=[],
                    help="rule id or glob pattern (repeatable). Narrows the run: write it with "
                         "-o .lapis/lint/<task>.narrow.json")
    ap.add_argument("-o", "--out", type=Path,
                    help="write the full report as JSON here (the full report is .lapis/lint/<task>.json, "
                         "which the release gate reads, so a run narrowed by --layer or --rule goes elsewhere)")
    ap.add_argument("--json", action="store_true",
                    help="print the full report as JSON instead of the summary")
    args = ap.parse_args(argv)
    try:
        report = run(rules=args.rules, plan=args.plan, extract=args.extract, session=args.session,
                     source=args.source, ledger=args.ledger, lock=args.lock, refs=args.ref, corpus=args.corpus,
                     lazuli_db=args.lazuli_db, mode=args.mode, layers=args.layer, rule_ids=args.rule,
                     draft=args.draft, page=args.page)
        text = json.dumps(report, ensure_ascii=False, indent=2)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text + "\n", encoding="utf-8")
    except (LintError, OSError) as exc:
        print(f"slop lint: {exc}", file=sys.stderr)
        return 2
    s = report["summary"]
    if args.json:
        print(text)
    else:
        print("\n".join(_summary_lines(report, args.out)))
    return 1 if s["blocking"] else 0


if __name__ == "__main__":
    sys.exit(main())
