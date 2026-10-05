"""Select the shown page's source set and preserve specimen/deferred findings outside its verdict."""
from pathlib import Path

from lapis_design import draft
from lapis_design.lint.detectors.source import _source_name


def select(record: Path, source: Path | None, extract: dict | None, url: str | None):
    root = record.resolve().parents[2]
    doc = draft.read(root, record.stem)
    if source is None or source.resolve() != root:
        raise ValueError("draft lint --source must name the project root, not the specimen folder")
    pages = doc["pages"]
    if url is None and len(pages) != 1:
        raise ValueError("draft lint with several shown pages needs --page <exact-url>")
    page = next((p for p in pages if url is None or p["url"] == url), None)
    if page is None:
        raise ValueError("--page is not a shown page in the draft record")
    if extract is None:
        raise ValueError("draft lint needs the shown page's --extract")
    if (draft._url(extract["source"].get("url", "")) != draft._url(page["url"])
            or extract["source"].get("task") != page["render_task"]):
        raise ValueError("draft extract captured a different page or render task")
    files = [draft.local(root, name) for name in page["sources"]]
    selected = {file.relative_to(root).as_posix() for file in files}
    specimens = sorted(file.relative_to(root).as_posix() for file in (root / ".lapis/specimens").rglob("*")
                       if file.is_file() and _source_name(file.name) and file.resolve().is_relative_to(root)
                       and file.relative_to(root).as_posix() not in selected)
    aliases = sorted({(font.get("requested", ""), font.get("rendered", ""))
                      for view in extract.get("viewports", []) for run in view.get("text", [])
                      if (font := run.get("font"))}, key=lambda pair: pair)
    scope = {"task": doc["task"], "url": page["url"], "sources": sorted(selected),
             "excluded_sources": specimens, "aliases": [{"requested": a, "rendered": b} for a, b in aliases]}
    return root, scope


def partition(findings):
    shown, deferred = [], []
    for finding in findings:
        target = deferred if finding["rule_id"].startswith(("system.", "rights.")) and finding["class"] != "requirement" else shown
        target.append(finding)
    return shown, deferred
