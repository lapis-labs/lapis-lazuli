"""Narrow pre-show review: bind an approval question to the exact rendered pages and their findings."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import yaml
from jsonschema import Draft202012Validator

from lapis_design import shared_dir, waiting

STEP = "draft-review"
_LINK = re.compile(r"https?://[^\s<>`]+|(?:\.?\.?/)?[\w./-]+\.html(?:\?[^\s<>`]+)?")


def path(root: Path, task: str) -> Path:
    return root / ".lapis" / "drafts" / f"{task}.yaml"


def links(root: Path, task: str) -> list[str]:
    """Local presentation links in questions also cover older runs without a draft record."""
    try:
        text = waiting.questions_path(root, task).read_text(encoding="utf-8")
    except OSError:
        return []
    return list(dict.fromkeys(m.group().rstrip(".,);]") for m in _LINK.finditer(text)
                             if "://" not in m.group() or urlsplit(m.group()).hostname in
                             ("localhost", "127.0.0.1", "::1")))


def read(root: Path, task: str) -> dict:
    doc = yaml.safe_load(path(root, task).read_text(encoding="utf-8"))
    schema = yaml.safe_load((shared_dir() / "release/draft.schema.yaml").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(doc))
    if errors:
        raise ValueError("; ".join(f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in errors[:3]))
    if doc["task"] != task:
        raise ValueError("draft task does not match the requested task")
    return doc


def local(root: Path, name: str) -> Path:
    file = (root / name).resolve()
    if not file.is_relative_to(root.resolve()) or not file.is_file():
        raise ValueError(f"review input is not a file inside the project: {name}")
    return file


def _url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _fresh(file: Path, inputs: list[Path]) -> bool:
    return all(file.stat().st_mtime_ns >= p.stat().st_mtime_ns for p in inputs)


def _proof(root: Path, task: str, review: dict) -> list[dict]:
    from lapis_design.plan_check import read_plan

    rows = review.get("claim_evidence")
    if not rows:
        raise ValueError("record claim_evidence: required brief claims/proof -> actual shown output -> missing evidence")
    plan = read_plan(root / ".lapis/plans" / f"{task}.yaml")
    if not isinstance(plan, dict):
        raise ValueError("the plan cannot supply the brief's required claims")
    given = json.dumps({"brief": plan.get("brief"), "declared": (plan.get("claims") or {}).get("declared")}, ensure_ascii=False)
    try:
        given += " " + waiting.answers_path(root, task).read_text(encoding="utf-8")
    except OSError:
        pass
    given = " ".join(given.casefold().split())
    for row in rows:
        cited = given
        if source := row.get("source"):
            context = plan.get("context") or {}
            if source not in [context.get("product"), *(context.get("other") or [])]:
                raise ValueError("claim_evidence source is not a brief document declared in context")
            cited = " ".join(local(root, source).read_text(encoding="utf-8").casefold().split())
        if " ".join(row["requirement"].casefold().split()) not in cited:
            raise ValueError("claim_evidence requirement is not quoted from the brief or declared requirements")
        if row["state"] == "shown" and (row["kind"] != "product-output" or not row["shown"] or row["missing"].strip()):
            raise ValueError("a site study or missing output cannot satisfy a product-proof requirement")
        if row["state"] != "shown" and len(row["missing"].strip()) < 8:
            raise ValueError("partial/missing product proof must name the evidence still missing")
        for ref in row["shown"]:
            local(root, ref.partition("#")[0])
    return rows


def check(root: Path, task: str, *, asked: list[str] | None = None) -> tuple[list[str], list[dict]]:
    """Problems and owner-facing summaries. Open findings may remain, but none may go unreported."""
    from lapis_design.lint.cli import LintError, _load

    try:
        doc = read(root, task)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return [f"{path(Path('.'), task)}: {exc}"], []
    errors, summaries = [], []
    urls = {p["url"] for p in doc["pages"]}
    for url in asked or []:
        if url not in urls:
            errors.append(f"shown page has no review record: {url}")
    for page in doc["pages"]:
        try:
            review = page.get("review")
            if not review:
                raise ValueError("no review recorded")
            proof = _proof(root, task, review)
            sources = [local(root, p) for p in page["sources"]]
            if page["direction"] == "new" and not {390, 1440}.issubset(page["widths"]):
                raise ValueError("a new direction needs 390 and 1440")
            extracts, widths = [], set()
            for name in review["extracts"]:
                file = local(root, name)
                extract = _load(file, "extract")
                if extract["source"].get("task") != page["render_task"] or _url(extract["source"].get("url", "")) != _url(page["url"]):
                    raise ValueError(f"{name} captured a different page/task")
                if not _fresh(file, sources):
                    raise ValueError(f"{name} is older than the shown source")
                for view in extract.get("viewports", []):
                    if view["width"] in page["widths"]:
                        shot = file.parent / view.get("screenshot", "")
                        local(root, str(shot.relative_to(root.resolve())))
                        widths.add(view["width"])
                extracts.append(file)
            if not set(page["widths"]).issubset(widths):
                raise ValueError("captures do not cover the shown widths")
            walks = {w["viewport"] for w in review["walkthroughs"]}
            if not set(page["widths"]).issubset(walks):
                raise ValueError("walk one visitor task per shown width, including friction and completion")
            reports = [(review["lint"], "slop_lint")]
            if page["direction"] == "new":
                critic = review.get("critic") or {}
                if not critic.get("independent") or not critic.get("context"):
                    raise ValueError("a new direction needs an independent fresh-context critic")
            if review.get("critic"):
                reports.append((review["critic"]["report"], "critic"))
            inputs = sources + extracts
            dispositions = []
            for name, tool in reports:
                file = local(root, name)
                report = _load(file, "report")
                if report["tool"]["name"] != tool or local(root, report["target"].get("extract", "")) not in extracts:
                    raise ValueError(f"{name} did not review this page's capture")
                if tool == "slop_lint" and not {"source", "render"}.issubset(report.get("scope", {}).get("layers", [])):
                    raise ValueError("draft lint needs the shown source and render layers")
                if tool == "slop_lint":
                    scope = report.get("scope", {}).get("draft") or {}
                    if scope.get("url") != page["url"] or scope.get("task") != task or set(scope.get("sources", [])) != set(page["sources"]):
                        raise ValueError("lint must use draft scope for exactly the shown URL/task/source set")
                    dispositions.extend({"rule_id": f["rule_id"], "disposition": "release-deferred",
                                         "reason": f["observed"]} for f in report.get("deferred_findings", []))
                if not _fresh(file, extracts + sources):
                    raise ValueError(f"{name} is stale")
                inputs.append(file)
                handled = {h["finding"]: h for h in review["handled"] if h["report"] == name}
                for i, finding in enumerate(report["findings"]):
                    if finding["status"] == "skipped":
                        dispositions.append({"rule_id": finding["rule_id"], "disposition": "not-checked", "reason": finding["observed"]})
                        continue
                    if i not in handled:
                        raise ValueError(f"{name} finding {i} ({finding['rule_id']}) has no fixed/justified-keep/unresolved disposition")
                    core = (tool == "critic" and
                            (finding.get("approval_impact") == "core-product-explanation" or
                             (finding["rule_id"] == "review.world-materials" and finding.get("approval_impact") != "ordinary")))
                    resolved = (finding["status"] == "fixed" and handled[i]["disposition"] == "fixed"
                                and handled[i].get("resolution_kind") == "product-output"
                                and any(row["kind"] == "product-output" and row["state"] == "shown" for row in proof))
                    if core and not resolved:
                        errors.append(f"{page['url']}: core product explanation {finding['rule_id']} is still open "
                                      f"({finding['status']}, {handled[i]['disposition']}); current settings/site-study "
                                      "or a partial fix are not real product results")
                    state = {"rule_id": finding["rule_id"], "approval_blocking": core and not resolved,
                             "status": finding["status"], **handled[i]}
                    if core and not resolved:
                        state.update(status="open", disposition="unresolved", reported_status=finding["status"],
                                     reported_disposition=handled[i]["disposition"])
                    dispositions.append(state)
                if set(handled) - set(range(len(report["findings"]))):
                    raise ValueError(f"{name} disposition names a nonexistent finding")
            if page["behavior_changed"]:
                behavior = review.get("behavior") or {}
                if not behavior.get("observed") or not behavior.get("refs"):
                    raise ValueError("changed behavior needs scoped playback/smoke evidence")
                inputs.extend(local(root, name) for name in behavior["refs"])
            if not _fresh(path(root, task), inputs):
                raise ValueError("review record is older than its evidence; review the changed area again")
            summaries.append({"url": page["url"], "area": page["area"], "widths": page["widths"],
                              "summary": review["summary"], "making_of": review["making_of"],
                              "walkthroughs": review["walkthroughs"], "claim_evidence": proof, "findings": dispositions})
        except (OSError, ValueError, KeyError, LintError, yaml.YAMLError) as exc:
            errors.append(f"{page['url']}: {exc}")
    return errors, summaries


def main(argv=None, prog="lapis-design draft check") -> int:
    parser = argparse.ArgumentParser(prog=prog, description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--task", required=True)
    args = parser.parse_args(argv)
    from lapis_design import integrity

    integrity.observe_task(args.root.resolve(), args.task, "draft check")    # before anything is computed from the plan
    errors, summaries = check(args.root.resolve(), args.task)
    print(json.dumps({"task": args.task, "reviewed": not errors, "problems": errors, "pages": summaries}, ensure_ascii=False, indent=2))
    return 1 if errors else 0
