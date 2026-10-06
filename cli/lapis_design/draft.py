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
    if isinstance(doc, dict) and doc.get("version") == 0:
        raise ValueError("a v0 draft review carries maker prose fields (summary, making_of, walkthroughs, claim_evidence, "
                         "critic.context, critic.independent, handled[].resolution_kind) that are no longer read; "
                         "rewrite it as version 1 without them (release/draft.schema.yaml): the critic's report, "
                         "built on `lapis-design critic packet`, now holds the walkthroughs and the requirement states")
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


def _brief(problems: list[str], limit: int = 3) -> str:
    return "; ".join(problems[:limit]) + (f"; and {len(problems) - limit} more" if len(problems) > limit else "")


def _judged(root: Path, name: str, file: Path, report: dict, page: dict, review: dict) -> str:
    """The sha256 of the packet a critic report judged, when that report counts for this page: it names the current
    packet, judges every row, change, and dispute in it, was built on this page's captures and lint report, and, for
    a new direction, walks a visitor task at every shown width."""
    from lapis_design import critic_packet

    verdict = critic_packet.check(root, file)
    if verdict.problems:
        raise ValueError(f"{name}: {_brief(verdict.problems)}")
    args = verdict.packet["args"]
    if ({local(root, p) for p in args["extracts"]} != {local(root, p) for p in review["extracts"]}
            or local(root, args["lint"]) != local(root, review["lint"])):
        raise ValueError(f"{name}: its packet was built from other captures or another lint report than this page's review")
    if page["direction"] == "new":
        walked = {w.get("viewport") for w in report.get("walkthroughs") or [] if isinstance(w, dict)}
        if missing := sorted(set(page["widths"]) - walked):
            raise ValueError(f"{name}: the critic walks a visitor task at every shown width; it has no walkthrough at "
                             f"{', '.join(map(str, missing))}")
    return report["target"]["packet"]["sha256"]


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
            reports = [(review["lint"], "slop_lint")]
            critic = review.get("critic")
            if page["direction"] == "new" and not critic:
                raise ValueError("a new direction needs a critic report built on `lapis-design critic packet` "
                                 "(review.critic.report), with a walkthrough per shown width")
            if critic:
                reports.append((critic["report"], "critic"))
            inputs = sources + extracts
            dispositions, packet_sha = [], None
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
                if tool == "critic":
                    packet_sha = _judged(root, name, file, report, page, review)
                handled = {h["finding"]: h for h in review["handled"] if h["report"] == name}
                for i, finding in enumerate(report["findings"]):
                    if finding["status"] == "skipped":
                        dispositions.append({"rule_id": finding["rule_id"], "disposition": "not-checked", "reason": finding["observed"]})
                        continue
                    if i not in handled:
                        raise ValueError(f"{name} finding {i} ({finding['rule_id']}) has no fixed/justified-keep/unresolved disposition")
                    # the critic's own report decides: an open core finding blocks whatever the maker answered
                    core = (tool == "critic" and finding["status"] == "open" and
                            (finding.get("approval_impact") == "core-product-explanation" or
                             (finding["rule_id"] == "review.world-materials" and finding.get("approval_impact") != "ordinary")))
                    if core:
                        errors.append(f"{page['url']}: core product explanation {finding['rule_id']} is still open in the "
                                      "current critic report; a fresh critic stops reporting it once real product output "
                                      "resolves it, whatever the disposition says")
                    state = {"rule_id": finding["rule_id"], "approval_blocking": core, "status": finding["status"], **handled[i]}
                    if core:
                        state.update(disposition="unresolved", reported_disposition=handled[i]["disposition"])
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
                              "findings": dispositions,
                              "critic": {"report": critic["report"], "packet_sha256": packet_sha} if critic else None})
        except (OSError, ValueError, KeyError, LintError, yaml.YAMLError) as exc:
            errors.append(f"{page['url']}: {exc}")
    return errors, summaries


def main(argv=None, prog="lapis-design draft check") -> int:
    parser = argparse.ArgumentParser(prog=prog, description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--task", required=True)
    args = parser.parse_args(argv)
    errors, summaries = check(args.root.resolve(), args.task)
    print(json.dumps({"task": args.task, "reviewed": not errors, "problems": errors, "pages": summaries}, ensure_ascii=False, indent=2))
    return 1 if errors else 0
