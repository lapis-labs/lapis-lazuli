"""Decide release readiness from a plan, existing reports, and refreshed catalog license facts."""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from lapis_design import __version__, attempts, font_license, gate, order, references, shared_dir
from lapis_design.lint.cli import LintError, _load, problems
from lapis_design.lint.engine import open_lazuli
from lapis_design.plan_check import (LazuliDBUpgradeError, PlanOverLimit, check_expansion, check_non_string_keys,
                                     check_schema, default_lazuli_db, default_lock, load_yaml, read_plan,
                                     run as check_plan, yaml_reason)
from lapis_design.summary import finding_lines

PROBES = ("controls", "commits", "keyboard", "dialogs", "choices", "forms", "states", "urgency",
          "time_limits", "history", "pointer", "motion", "scroll", "permissions", "media", "flows", "console")
CATALOGS = {"google-fonts", "fontsource", "fontshare", "sandoll"}
UNCONFIRMED = {"adobe-sync", "user-installed", "foundry-purchase", "open-source-other", "noonnu"}
OPEN_CHANNELS = {"open-source-other", "noonnu"}      # a license read from its own document needs no second reading
LICENSE_KINDS = {"OFL-1.1": "ofl", "Apache-2.0": "apache", "KOGL-1": "kogl-1", "system": "system",
                 "commercial": ("commercial-subscription", "commercial-perpetual")}
# The gate's own blocking findings that report a check that did not run or an input that is missing
# (release/GATE.md): rule -> (key in `summary.not_run`, how the printed result names it). The rest of
# the blocking findings are defects.
NO_EVIDENCE = {
    "release.input-missing": ("inputs", "inputs missing"),
    "release.input-stale": ("stale", "inputs stale"),
    "release.width-missing": ("widths", "widths not captured"),
    "release.theme-missing": ("themes", "themes not captured"),
    "release.probe-incomplete": ("probes", "probes incomplete"),
    "release.backend-insufficient": ("backend", "backend insufficient"),
    "release.layer-missing": ("layers", "lint layers not run"),
    "release.requirement-unverified": ("requirements", "requirements not verified"),
    "release.critic-missing": ("critic", "critic reports missing"),
    "release.license-unchecked": ("licenses", "licenses unchecked"),
}


def _finding(rule: str, observed: str, *, layer: str = "review", refs: tuple[str, ...] = (),
             asset: str | None = None, warning: bool = False, source: bool = False) -> dict:
    result = {"rule_id": f"release.{rule}", "class": "quality" if warning else "requirement",
              "severity": {"create": "warn" if warning else "gate", "review": "P2" if warning else "P0"},
              "layer": layer, "observed": observed, "blocking": not warning, "status": "open",
              "evidence": {"type": "source" if source else "not-verified", "refs": list(refs)}}
    if asset is not None:
        result["location"] = {"asset": asset}
    return result


def lint_lacks_target(name: str) -> str:
    """What `release.layer-missing` says of a lint report whose target lacks the task's `name`; `next` reads it."""
    return f"lint target lacks the task's {name}"


def lint_lacks_layer(layer: str) -> str:
    """What `release.layer-missing` says of a lint scope that did not run `layer`; `next` reads it."""
    return f"lint scope did not run {layer}"


def _copy_blocking(document: dict | None, origin: Path) -> list[dict]:
    return [_copy(item, origin) for item in document["findings"] if item["blocking"]] if document else []


def _copy(original: dict, origin: Path) -> dict:
    item = copy.deepcopy(original)
    item["evidence"].setdefault("refs", []).append(str(origin))
    return item


def _same(root: Path, actual: str | None, expected: Path) -> bool:
    return bool(actual) and (root / actual).resolve() == expected.resolve()


def _input(path: Path, kind: str, task: str) -> tuple[dict | None, str | None]:
    try:
        document = _load(path, kind)
    except LintError as exc:
        return None, str(exc)
    actual = ((document.get("source") or {}).get("task") if kind in ("extract", "session") else
              (document.get("target") or {}).get("task") if kind == "report" else None)
    if actual is not None and actual != task:
        return None, f"{path} names task {actual!r}, not {task!r}"
    return document, None


def _stale(newer: Path, older: Path, findings: list[dict]) -> None:
    if newer.is_file() and older.is_file() and older.stat().st_mtime < newer.stat().st_mtime:
        findings.append(_finding("input-stale", f"{older} is older than {newer}", refs=(str(older), str(newer))))


def _license_kind(license_id: str | None) -> str | tuple[str, str]:
    return LICENSE_KINDS.get(license_id, "unknown")


def _matches(record: Any, font: dict, source: str) -> bool:
    from lazuli.scan import norm
    match = font.get("catalog_match") or {}
    return ((match.get("catalog") == source and match.get("key") == record.source_key)
            or norm(record.family) == norm(font["family"]))


def _licenses(fonts: list[dict], offline: bool) -> list[dict]:
    """Refresh each source once. Snapshot adapters fetch all families; Sandoll looks up one family."""
    from lazuli import catalog, db, paths
    from lazuli.catalog import net, store
    from lazuli.scan import norm

    output = []
    catalog_results: list[tuple[str, dict]] = []
    sources = {module.NAME: module for module in catalog.SOURCES}
    conn = None
    snapshots: dict[str, list[Any]] = {}
    blocked_sources: dict[str, str] = {}
    try:
        for font in fonts:
            source = font["source"]
            family = font["family"]
            if source == "system":
                continue
            research = font["license"].get("research") or {}
            verified = (font_license.state(font) == "researched" and research["outcome"] == "verified"
                        and font["license"].get("source_class") in ("rights-holder", "provider"))
            if research.get("outcome") == "restricted":
                output.append(_finding("license-unconfirmed", f"{family}: the license is restricted "
                                       f"({'; '.join(research.get('restrictions', []))}); the user confirms the use",
                                       layer="source", asset=family, warning=True, source=True))
            elif ((source in UNCONFIRMED and not (verified and source in OPEN_CHANNELS)) or source == "sandoll"
                    or font["license"].get("source_class") == "user-declared"):
                output.append(_finding("license-unconfirmed", f"{family}: license needs user confirmation",
                                       layer="source", asset=family, warning=True, source=True))
            if source not in CATALOGS:
                continue
            reason = "offline: catalog license was not refreshed" if offline else blocked_sources.get(source)
            record = None
            if not offline and reason is None:
                module = sources[source]
                try:
                    if conn is None:
                        conn = db.connect(paths.db_path())
                    store.ensure_source(conn, module)
                    conn.commit()
                    if module.KIND == "snapshot":
                        if source not in snapshots:
                            fetcher = net.Fetcher(source, min_interval_s=module.MIN_INTERVAL_S, conn=conn)
                            families = module.fetch(fetcher)
                            store.replace_snapshot(conn, module, families)
                            snapshots[source] = families
                        record = next((item for item in snapshots[source] if _matches(item, font, source)), None)
                    else:
                        fetcher = net.Fetcher(source, min_interval_s=module.MIN_INTERVAL_S, conn=conn)
                        record = module.lookup(fetcher, family,
                                               postscript_name=next(iter(font.get("postscript_names") or ()), None))
                        store.save_lookup(conn, module, norm(family), record, module.TTL_DAYS)
                    if record is not None:
                        expected = _license_kind(record.license)
                        if font["license"]["kind"] not in (
                                expected if isinstance(expected, tuple) else (expected,)):
                            catalog_results.append((source, _finding(
                                "license-changed",
                                f"{family}: lock kind {font['license']['kind']} differs from catalog "
                                f"{record.license or 'unknown'} ({expected})", layer="source",
                                asset=family, source=True)))
                        elif expected == "unknown" and font["license"]["kind"] == "unknown" and not (
                                source == "sandoll" or font["license"].get("source_class") == "user-declared"):
                            catalog_results.append((source, _finding(
                                "license-unconfirmed", f"{family}: catalog license is unknown",
                                layer="source", asset=family, warning=True, source=True)))
                except Exception as exc:
                    reason = f"{type(exc).__name__}: {exc}"
                    blocked_sources[source] = reason
                    if conn is not None:
                        try:
                            store.mark(conn, module, "failed", reason)
                        except Exception:
                            pass  # The refresh failure still belongs in the release report.
            if record is None and reason is None:
                reason = "family not found in refreshed catalog"
            if reason:
                catalog_results.append((source, _finding("license-unchecked", f"{family}: {reason}",
                                                         layer="source", asset=family, source=True)))
    finally:
        if conn is not None:
            conn.close()
    output.extend(item for source, item in catalog_results if source not in blocked_sources)
    for font in fonts:
        if reason := blocked_sources.get(font["source"]):
            output.append(_finding("license-unchecked", f"{font['family']}: {reason}",
                                   layer="source", asset=font["family"], source=True))
    return output


def _summary(findings: list[dict]) -> dict:
    """`blocking` is `defects` + `no_evidence`; `total` is `blocking` + `to_confirm`; `not_run` breaks
    `no_evidence` down by cause, leaving out zero counts."""
    blocking = [f for f in findings if f["blocking"]]
    not_run = {key: count for rule, (key, _) in NO_EVIDENCE.items()
               if (count := sum(f["rule_id"] == rule for f in blocking))}
    no_evidence = sum(not_run.values())
    return {"blocking": len(blocking), "total": len(findings), "defects": len(blocking) - no_evidence,
            "no_evidence": no_evidence, "to_confirm": len(findings) - len(blocking), "not_run": not_run}


def _result_lines(report: dict, output: Path) -> list[str]:
    """The printed result: the counts in two parts, then what did not run, so a reader can tell a check
    to run from a defect to repair, then each finding: defects, the checks and inputs still missing, and what the
    user confirms."""
    summary, findings = report["summary"], report["findings"]
    lines = [f"release_gate: {summary['blocking']} blocking = {summary['defects']} defects + "
             f"{summary['no_evidence']} without evidence, {summary['total']} findings -> {output}"]
    if summary["no_evidence"]:
        causes = [f"{summary['not_run'][key]} {name}" for key, name in NO_EVIDENCE.values()
                  if key in summary["not_run"]]
        lines.append(f"  without evidence: {', '.join(causes)}")
    here = report["target"].get("plan")
    blocking = [f for f in findings if f["blocking"]]
    lines += finding_lines((f for f in blocking if f["rule_id"] not in NO_EVIDENCE), "BLOCK", here)
    lines += finding_lines((f for f in blocking if f["rule_id"] in NO_EVIDENCE), "NOT RUN", here)
    lines += finding_lines((f for f in findings if not f["blocking"]), "CONFIRM", here)
    return lines


def _report(paths: dict[str, Path], task: str, interactive: bool, findings: list[dict]) -> dict:
    report = {"version": 0, "tool": {"name": "release_gate", "version": __version__},
              "target": {"plan": str(paths["plan"]), "extract": str(paths["extract"]),
                         **({"session": str(paths["session"])} if interactive else {}), "task": task},
              "findings": findings, "summary": _summary(findings)}
    if errors := problems(report, "report"):
        raise ValueError("release report invalid: " + "; ".join(errors[:5]))
    return report


def input_paths(root: Path, task: str) -> dict[str, Path]:
    """Where the gate reads each input of `task` (the table in release/GATE.md); `next` reads the same files."""
    return {name: root / ".lapis" / rel for name, rel in (
        ("plan", f"plans/{task}.yaml"), ("extract", f"renders/{task}.json"),
        ("session", f"behavior/{task}.json"), ("lint", f"lint/{task}.json"),
        ("critic", f"critic/{task}.json"), ("lock", "fonts.lock.json"),
        ("ledger", "assets.ledger.json"))}


def run(root: Path, task: str, *, static: bool = False, offline: bool = False,
        unattended: bool | None = None) -> dict:
    """Return the release report; ValueError only for an unreadable plan or invalid option. `unattended` says
    whether nobody is at the keyboard (default: `LAPIS_UNATTENDED=1`): only then does `release.procedure-order`
    block."""
    paths = input_paths(root, task)
    try:
        plan = read_plan(paths["plan"])
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ValueError(f"{paths['plan']} cannot be read: {yaml_reason(exc)}") from exc
    if not isinstance(plan, (dict, PlanOverLimit)):
        raise ValueError(f"{paths['plan']} is not a plan mapping")
    schema_findings = check_expansion(plan, str(paths["plan"]))
    if not schema_findings:
        schema_findings = check_non_string_keys(plan, str(paths["plan"]))
    if not schema_findings:
        schema_findings = check_schema(plan, load_yaml(shared_dir() / "plan/schema.yaml"), str(paths["plan"]))
    if schema_findings:
        return _report(paths, task, not static, [_copy(f, paths["plan"]) for f in schema_findings])
    if plan["task"]["id"] != task:
        raise ValueError(f"{paths['plan']} names task {plan['task']['id']!r}, not {task!r}")
    if static and plan.get("flows"):
        raise ValueError("--static cannot be used when the plan has flows")
    interactive = not static
    docs: dict[str, dict | None] = {"plan": plan}
    findings: list[dict] = []
    for name, kind in (("extract", "extract"), ("session", "session"), ("lint", "report"),
                       ("critic", "report"), ("lock", "lock"), ("ledger", "ledger")):
        if name == "session" and not interactive:
            continue
        doc, problem = _input(paths[name], kind, task)
        docs[name] = doc
        if problem:
            if name == "critic" and not paths[name].is_file():
                findings.append(_finding("critic-missing", problem, refs=(str(paths[name]),)))
            else:
                findings.append(_finding("input-missing", problem,
                                         layer={"extract": "render", "session": "behavior",
                                                "lock": "source", "ledger": "source"}.get(name, "review"),
                                         refs=(str(paths[name]),)))
    critic = docs.get("critic")
    critic_valid = critic is not None and _same(root, critic["target"].get("extract"), paths["extract"])
    if critic is not None and not critic_valid:
        findings.append(_finding("critic-missing", f"{paths['critic']} targets another extract",
                                 refs=(str(paths["critic"]),)))
    # The order below is the contract's dependency order; report each stale edge separately.
    if interactive:
        _stale(paths["plan"], paths["session"], findings)
        # Behavior check records the fixture relative to the project's working directory.
        stub = ((docs.get("session") or {}).get("meta") or {}).get("stub")
        if stub:
            stub_path = root / stub
            if not stub_path.is_file():
                findings.append(_finding("input-missing", f"stub fixture not found: {stub_path}",
                                         layer="behavior", refs=(str(stub_path),)))
            else:
                _stale(stub_path, paths["session"], findings)
    for name in ("plan", "extract", "session", "lock", "ledger"):
        if name != "session" or interactive:
            _stale(paths[name], paths["lint"], findings)
    for name in ("lint", "extract"):
        _stale(paths[name], paths["critic"], findings)
    shared = shared_dir()
    lazuli_db, from_user_cache = default_lazuli_db(None)
    if lazuli_db is not None:
        try:
            open_lazuli(lazuli_db).close()
        except (OSError, RuntimeError, sqlite3.Error) as exc:
            if not from_user_cache:
                if isinstance(exc, LazuliDBUpgradeError):
                    raise ValueError(str(exc)) from exc
                raise ValueError(f"lazuli database {lazuli_db} cannot be opened: {exc}") from exc
            print(f"release check: lazuli database {lazuli_db} cannot be opened; "
                  f"this run checks without measured font features: {exc}", file=sys.stderr)
            lazuli_db = None
    lock = default_lock(root, None)
    plan_report = check_plan(paths["plan"], shared / "slop/rules.yaml", lock if docs.get("lock") else None,
                             shared / "plan/schema.yaml", root, plan=plan, lazuli_db=lazuli_db)
    findings.extend(_copy_blocking(plan_report, paths["plan"]))
    lint = docs.get("lint")
    if lint:
        needed = ("plan", "extract", "ledger", "lock", "source") + (("session",) if interactive else ())
        target = lint["target"]
        for name in needed:
            correct = ((root / target[name]).is_dir() if name == "source" and target.get(name) else
                       _same(root, target.get(name), paths[name]) if name != "source" else False)
            if not correct:
                findings.append(_finding("layer-missing", lint_lacks_target(name),
                                         refs=(str(paths["lint"]),)))
        scope = lint.get("scope")
        required_layers = {"plan", "source", "render"} | ({"behavior"} if interactive else set())
        if not scope:
            findings.append(_finding("layer-missing", "lint report has no scope",
                                     refs=(str(paths["lint"]),)))
        else:
            for layer in sorted(required_layers - set(scope["layers"])):
                findings.append(_finding("layer-missing", lint_lacks_layer(layer),
                                         refs=(str(paths["lint"]),)))
            for narrow in ("rules", "rules_file"):
                if narrow in scope:
                    findings.append(_finding("layer-missing", f"lint scope was narrowed by {narrow}",
                                             refs=(str(paths["lint"]),)))
            if unread := (scope.get("unread_links") or {}).get("source"):
                shown = ", ".join(unread[:5]) + (f" (and {len(unread) - 5} more)" if len(unread) > 5 else "")
                findings.append(_finding("layer-missing", f"lint did not read {len(unread)} source link(s): {shown}",
                                         refs=(str(paths["lint"]),)))
        findings.extend(_copy_blocking(lint, paths["lint"]))
    extract = docs.get("extract")
    colors = ((plan.get("tokens") or {}).get("color") or {})
    if extract:
        captured = {(v["theme"], v["width"]) for v in extract.get("viewports") or ()}
        for width in (320, 390, 768, 1440):
            if ("light", width) not in captured:
                findings.append(_finding("width-missing", f"no light capture at {width} px", layer="render",
                                         refs=(str(paths["extract"]),)))
        if extract["meta"].get("dark_theme"):
            for width in (390, 768, 1440):
                if ("dark", width) not in captured:
                    findings.append(_finding("theme-missing", f"no dark capture at {width} px", layer="render",
                                             refs=(str(paths["extract"]),)))
        elif ("dark" in (colors.get("themes") or ())
              or any(role.get("theme") == "dark" for role in colors.get("roles") or ())):
            findings.append(_finding("theme-missing", "the plan set a dark theme and the render found none",
                                     layer="render", refs=(str(paths["plan"]), str(paths["extract"]))))
    if ("high-contrast" in (colors.get("themes") or ())
            or any(role.get("theme") == "high-contrast" for role in colors.get("roles") or ())):
        findings.append(_finding("theme-unchecked", "high-contrast theme needs a manual check",
                                 layer="render", warning=True, refs=(str(paths["plan"]),)))
    session = docs.get("session")
    if session:
        covered = {name: [] for name in PROBES}
        for entry in session["coverage"]:
            covered[entry["probe"]].append(entry["status"])
        for probe, statuses in covered.items():
            if not statuses or any(s in ("partial", "skipped") for s in statuses):
                findings.append(_finding("probe-incomplete", f"{probe} coverage: {', '.join(statuses) or 'missing'}",
                                         layer="behavior", refs=(str(paths["session"]),)))
        if session["meta"]["backend"] == "local-dev":
            findings.append(_finding("backend-insufficient", "local-dev backend did not exercise stub failure modes",
                                     layer="behavior", refs=(str(paths["session"]),)))
    decisions = critic["findings"] if critic_valid else []
    resolved_unearned: set[int] = set()
    if lint:
        for skipped in lint["findings"]:
            if skipped["status"] != "skipped" or skipped["class"] not in ("requirement", "contract"):
                continue
            matches = [(index, decision) for index, decision in enumerate(decisions)
                       if skipped.get("skip_cause") == "reviewer"
                       and decision["rule_id"] == skipped["rule_id"]
                       and (not skipped.get("location") or decision.get("location") == skipped["location"])
                       and (decision.get("context") or {}).get("verdict") in ("earned", "unearned")]
            if not matches:
                findings.append(_finding("requirement-unverified",
                                         f"{skipped['rule_id']}: {skipped['observed']}",
                                         layer=skipped["layer"], refs=(str(paths["lint"]),)))
            else:
                resolved_unearned.update(index for index, decision in matches
                                         if decision["context"]["verdict"] == "unearned")
    for index, decision in enumerate(decisions):
        if (decision.get("context") or {}).get("verdict") != "earned" and (
                decision["blocking"] or index in resolved_unearned):
            findings.append(_copy(decision, paths["critic"]))
    for index, ref in enumerate(plan.get("references") or ()):
        if ref.get("mode") == "study":
            findings.append(_finding("study-reference", f"reference {index} is used in study mode",
                                     layer="plan", refs=(str(paths["plan"]),)))
    if found := order.violation(root, task, plan):
        blocks = gate.is_unattended() if unattended is None else unattended
        findings.append(_finding("procedure-order", order.describe(found) + ("" if blocks else
                                 "; an unattended run is held to the order, a person's session only sees this"),
                                 layer="plan", warning=not blocks, source=True,
                                 refs=(found["path"], str(paths["plan"]))))
    if (plan.get("approval") or {}).get("state") == "assumed":
        findings.append(_finding("approval-assumed", f"no person approved this plan: {plan['approval']['reason']}",
                                 layer="plan", warning=True, refs=(str(paths["plan"]),)))
    if plan.get("mode") == "create" and references.problems(root, task) and (
            declined := references.declined(root, task, plan)):
        findings.append(_finding("references-declined",
                                 f"no reference was researched: the run declined the references step with the user's "
                                 f"line \"{declined['brief_line']}\" ({declined['at']}), so nothing outside was looked at and "
                                 "the plan's explorations rest on local material (installed fonts, the project, the "
                                 "brief's facts)", layer="plan", warning=True, source=True,
                                 refs=(str(attempts.path(root, task, references.STEP)),)))
    if docs.get("lock"):
        findings.extend(_licenses([font for font in docs["lock"]["fonts"] if task in font["used_by"]], offline))
    # Put license uncertainty ahead of blocking results so the user can reconfirm it.
    findings.sort(key=lambda item: item["rule_id"] != "release.license-unconfirmed")
    return _report(paths, task, interactive, findings)


def main(argv: list[str] | None = None, prog: str = "lapis-design release check") -> int:
    parser = argparse.ArgumentParser(prog=prog, description=__doc__.split("\n")[0],
                                     allow_abbrev=False)
    parser.add_argument("--task", required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--static", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--json", action="store_true",
                        help="print the full report as JSON instead of the summary (the report file is written "
                             "either way)")
    argv = sys.argv[1:] if argv is None else argv
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code == 2:
            def option(name: str) -> str | None:
                selected = None
                for index, value in enumerate(argv):
                    if value == name and index + 1 < len(argv) and not argv[index + 1].startswith("-"):
                        selected = argv[index + 1]
                    elif value.startswith(name + "="):
                        selected = value[len(name) + 1:]
                return selected

            candidate = option("--task")
            if candidate and re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", candidate):
                root = Path(option("--root") or ".")
                try:
                    (root / ".lapis" / "release" / f"{candidate}.json").unlink(missing_ok=True)
                except OSError as cleanup:
                    print(f"release check: previous report cannot be removed: {cleanup}", file=sys.stderr)
        raise
    output = args.root / ".lapis" / "release" / f"{args.task}.json"
    valid_task = re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", args.task) is not None
    if not valid_task:
        print("release check: --task must be a plan task id and a filename component", file=sys.stderr)
        return 2
    try:
        result = run(args.root, args.task, static=args.static, offline=args.offline)
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent,
                                           prefix=f".{output.name}.", suffix=".tmp", delete=False)
        temporary = Path(temp.name)
        try:
            with temp:
                temp.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            mask = os.umask(0)
            os.umask(mask)
            temporary.chmod(0o666 & ~mask)
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
    except Exception as exc:
        try:
            output.unlink(missing_ok=True)
        except OSError:
            pass  # Preserve the original failure as the single actionable reason.
        print(f"release check: {str(exc) or type(exc).__name__}", file=sys.stderr)
        attempts.record_failure(exc, task=args.task, step="release", command=attempts.command_line(prog, argv),
                                exit_code=2, full_run=True, root=args.root)
        return 2
    attempts.clear(args.task, "release", args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json
          else "\n".join(_result_lines(result, output)))
    return 1 if result["summary"]["blocking"] else 0


if __name__ == "__main__":
    sys.exit(main())
