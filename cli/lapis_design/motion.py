"""Record the motion of a rendered page for the critic: `lapis-design render motion URL --task T [--lang TAG]`.

A still capture of a page that moves hides what the owner judges: a pinned scene looks like one frame in a page that is
three screens of empty scroll, and a flattened full-page screenshot says nothing about dwell. This command records, for
the build it opens, at 390 and at 1440:

- a scripted scroll as a `.webm` playback at a fixed speed (`px_per_s`), the way `lazuli ref capture --motion` records a
  reference, so a scene's dwell is its scroll runway over that speed;
- representative settled-state screenshots (top, each pinned scene's start, middle, and end, and the bottom), taken after
  the page stood still;
- the same screenshots with `prefers-reduced-motion: reduce`.

It also measures the pinned scenes (a sticky element whose container is much taller than it, or a `pin-spacer` child): the
content the scene holds and the empty scroll runway around it. The build's identity is the sha256 of the main document
as served, which `render check` records in its extract (`source.document_sha256`) from the same kind of request. The
result is `.lapis/renders/<task>.motion.json` and the files in `.lapis/renders/<task>.motion/`; running it again for
another locale (`--lang ko`) replaces that locale's entry and keeps the others. `critic packet` reads the manifest, and
`slice` counts a page's height without the pinned runway.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lapis_design.render import hosts

WIDTHS = ((390, 844), (1440, 900))
PX_PER_S = 600                    # speed of the scripted scroll; a scene's dwell is its runway over this
STEP_MS = 100
MIN_SECONDS, MAX_SECONDS = 6, 60
SETTLE_MS = 1200                  # how long the page stands still before a settled capture
MAX_STILLS = 9                    # settled captures per width and mode
MIN_RUNWAY = 0.25                 # a pinned scene's empty runway counts from this many viewport heights

_SCENES = """() => {
  const vh = innerHeight, out = [], seen = new Set();
  for (const el of document.querySelectorAll('body *')) {
    const parent = el.parentElement;
    if (!parent || parent === document.body) continue;
    const pinned = getComputedStyle(el).position === 'sticky' || /(^|\\s)pin-spacer(\\s|$)/.test(parent.className || '');
    if (!pinned || seen.has(parent)) continue;
    const box = parent.getBoundingClientRect(), inner = el.getBoundingClientRect();
    if (box.height - inner.height < vh * %s) continue;
    seen.add(parent);
    const mark = (el.id ? '#' + el.id : '') || (typeof el.className === 'string' && el.className.trim()
      ? '.' + el.className.trim().split(/\\s+/)[0] : '');
    out.push({top: box.top + scrollY, container_px: box.height, content_px: inner.height,
              selector: el.tagName.toLowerCase() + mark,
              text: (el.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 120)});
  }
  return out.sort((a, b) => a.top - b.top);
}""" % MIN_RUNWAY


def manifest_path(root: Path, task: str) -> Path:
    return root / ".lapis" / "renders" / f"{task}.motion.json"


def folder(root: Path, task: str) -> Path:
    return root / ".lapis" / "renders" / f"{task}.motion"


def read(root: Path, task: str) -> dict | None:
    """The motion manifest of `task` as a mapping, or None when there is none or it cannot be read."""
    try:
        found = json.loads(manifest_path(root, task).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def runway(root: Path, task: str, document_sha256: str | None) -> int:
    """The empty scroll runway of the pinned scenes at 1440, in px, summed over the first locale of the manifest: the part of
    a page's height that is waiting, not content. 0 with no manifest, and when `document_sha256` (the build the page's extract
    captured) is None or names another build than the recording."""
    found = read(root, task)
    entries = (found or {}).get("locales") or ()
    for block in (entries[0].get("widths") or ()) if entries else ():
        if document_sha256 and block.get("width") == 1440 and block.get("document_sha256") == document_sha256:
            return round(sum(s.get("runway_px", 0) for s in block.get("scenes") or ()))
    return 0


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _positions(scenes: list[dict], travel: int) -> list[int]:
    """Where the settled captures scroll to: the top, each scene's start, middle, and end, and the bottom."""
    wanted = [0]
    for scene in scenes:
        start = round(scene["top"])
        wanted += [start, start + round(scene["runway_px"] / 2), start + round(scene["runway_px"])]
    wanted.append(travel)
    seen: list[int] = []
    for y in wanted:
        y = max(0, min(y, travel))
        if y not in seen:
            seen.append(y)
    if len(seen) > MAX_STILLS:                      # keep the ends and spread the rest
        step = (len(seen) - 1) / (MAX_STILLS - 1)
        seen = [seen[round(i * step)] for i in range(MAX_STILLS)]
    return seen


def _measure(page: Any, width: int, height: int) -> tuple[int, list[dict]]:
    total = int(page.evaluate("Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"))
    scenes = []
    for number, scene in enumerate(page.evaluate(_SCENES), 1):
        run = max(0.0, scene["container_px"] - scene["content_px"])
        scenes.append({"id": f"S{number}", "selector": scene["selector"], "top": round(scene["top"]),
                       "content_px": round(scene["content_px"]), "runway_px": round(run),
                       "text": scene["text"], "viewports": round(scene["container_px"] / height, 2)})
    return total, scenes


def _load(context: Any, url: str, guard: hosts.GuardedBrowser, wait_ms: int = 800) -> tuple[Any, str]:
    """A page opened on `url` through the guarded context, and the sha256 of the main document as served."""
    page = context.new_page()
    response = page.goto(url, wait_until="load")
    guard.check()
    page.wait_for_timeout(wait_ms)
    return page, hashlib.sha256(response.body() if response else b"").hexdigest()


def _stills(guard: hosts.GuardedBrowser, url: str, width: int, height: int, lang: str | None, reduced: bool,
            positions: list[int], out: Path, stem: str) -> list[dict]:
    options: dict[str, Any] = {"viewport": {"width": width, "height": height}, "device_scale_factor": 1,
                               "reduced_motion": "reduce" if reduced else "no-preference"}
    if lang:
        options["locale"] = lang
    context = guard.new_context(**options)
    rows = []
    try:
        page, _ = _load(context, url, guard)
        for number, y in enumerate(positions, 1):
            page.evaluate("y => window.scrollTo(0, y)", y)
            page.wait_for_timeout(SETTLE_MS)
            name = f"{stem}-{'reduced' if reduced else 'settled'}-{number:02d}.png"
            page.screenshot(path=str(out / name), type="png")
            rows.append({"kind": "reduced" if reduced else "settled", "width": width, "scroll_y": y, "file": name})
    finally:
        context.close()
    return rows


def _playback(guard: hosts.GuardedBrowser, url: str, width: int, height: int, lang: str | None, out: Path,
              stem: str, travel: int) -> dict:
    seconds = max(MIN_SECONDS, min(MAX_SECONDS, travel / PX_PER_S))
    steps = round(seconds * 1000 / STEP_MS)
    video_dir = out / f".video-{stem}"
    options: dict[str, Any] = {"viewport": {"width": width, "height": height}, "device_scale_factor": 1,
                               "record_video_dir": str(video_dir), "record_video_size": {"width": width, "height": height}}
    if lang:
        options["locale"] = lang
    context = guard.new_context(**options)
    try:
        page, _ = _load(context, url, guard)
        for step in range(steps + 1):
            page.evaluate("y => window.scrollTo(0, y)", round(travel * step / steps))
            page.wait_for_timeout(STEP_MS)
        video = page.video
    finally:
        context.close()                                     # the recording is finished only now
    name = f"{stem}-playback.webm"
    try:
        shutil.move(video.path(), out / name)
    finally:
        shutil.rmtree(video_dir, ignore_errors=True)
    return {"kind": "playback", "width": width, "file": name, "seconds": round(seconds, 1),
            "px_per_s": round(travel / seconds) if travel else 0}


def record(root: Path, guard: hosts.GuardedBrowser, url: str, task: str, lang: str | None,
           widths: tuple[tuple[int, int], ...] = WIDTHS) -> dict:
    """One locale's entry: for each width the playback, the settled and reduced-motion stills, the pinned scenes, and the
    build identity. Files go to `.lapis/renders/<task>.motion/`."""
    out = folder(root, task)
    out.mkdir(parents=True, exist_ok=True)
    blocks, observed = [], None
    for width, height in widths:
        measure = guard.new_context(viewport={"width": width, "height": height}, device_scale_factor=1,
                                    **({"locale": lang} if lang else {}))
        try:
            page, document = _load(measure, url, guard)
            observed = observed or page.evaluate("document.documentElement.lang || ''") or None
            total, scenes = _measure(page, width, height)
        finally:
            measure.close()
        tag = lang or observed or "und"
        stem = f"{tag}-{width}"
        travel = max(total - height, 0)
        positions = _positions([{**s, "runway_px": s["runway_px"]} for s in scenes], travel)
        files = [_playback(guard, url, width, height, lang, out, stem, travel),
                 *_stills(guard, url, width, height, lang, False, positions, out, stem),
                 *_stills(guard, url, width, height, lang, True, positions, out, stem)]
        for row in files:
            row["path"] = (out / row["file"]).relative_to(root).as_posix()
            row["sha256"] = sha256(out / row["file"])
            del row["file"]
        blocks.append({"width": width, "document_sha256": document, "scroll_height": total, "scenes": scenes,
                       "recordings": files})
    return {"lang": lang or observed or "und", "widths": blocks}


def merge(root: Path, task: str, url: str, entry: dict) -> dict:
    """Write the manifest with `entry` in place of the same locale's, keeping the other locales."""
    old = read(root, task) or {}
    kept = [e for e in old.get("locales") or () if e.get("lang") != entry["lang"]]
    document = {"version": 1, "task": task, "source": {"url": url},
                "meta": {"generated_at": datetime.now(timezone.utc).isoformat(), "px_per_s": PX_PER_S},
                "locales": sorted([*kept, entry], key=lambda e: e["lang"])}
    path = manifest_path(root, task)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return document


def main(argv: list[str] | None = None, prog: str = "lapis-design render motion") -> int:
    import yaml
    from playwright.sync_api import Error as PlaywrightError

    from lapis_design import chromium, local_site, ours, render
    from lapis_design.render import hosts

    parser = argparse.ArgumentParser(prog=prog, description="Record a page's scripted-scroll playback, settled and "
                                     "reduced-motion captures, and pinned scenes for the critic.")
    parser.add_argument("url", help="the page: an http(s) URL, or a file:// URL or path of an HTML file")
    parser.add_argument("--task", required=True)
    parser.add_argument("--lang", help="the locale this run shows (a BCP 47 tag): set as the browser locale and the entry's "
                        "name; default the page's own <html lang>. Run once per locale the owner is shown")
    parser.add_argument("--plan", type=Path, help="the task's plan (default: .lapis/plans/<task>.yaml when it exists)")
    parser.add_argument("--public", action="store_true", help="record a public host of ours")
    args = parser.parse_args(argv)
    if "/" in args.task or "\\" in args.task or args.task in (".", ".."):
        parser.error("task must be a filename component")
    root = Path.cwd()
    guard = None
    try:
        with local_site.serve(args.url) as url:
            canonical = ours.canonical_start_url(url)
            plan = hosts.load_plan(hosts.plan_path(args.plan, args.task))
            pin = ours.pin_source(canonical)
            policy = hosts.HostPolicy(public=args.public, plan=plan, pins=[pin] if pin else [])
            policy.check(canonical)
            with render.sync_playwright() as playwright:
                browser = chromium.launch(playwright, render.launch_args([pin] if pin else []))
                guard = hosts.GuardedBrowser(browser, policy)
                try:
                    entry = record(root, guard, canonical, args.task, args.lang)
                finally:
                    browser.close()
            document = merge(root, args.task, canonical.partition("?")[0].partition("#")[0], entry)
    except local_site.NotServable as exc:
        parser.error(str(exc))
    except (hosts.Refused, chromium.BrowserUnavailable, OSError, ValueError, PlaywrightError, yaml.YAMLError) as exc:
        refused = guard.refused if guard and guard.refused else exc
        print(f"render motion: {refused}", file=sys.stderr)
        return 2
    scenes = sum(len(b["scenes"]) for b in entry["widths"])
    print(f"render motion: {entry['lang']}: {sum(len(b['recordings']) for b in entry['widths'])} files, {scenes} pinned scenes "
          f"-> {manifest_path(root, args.task).relative_to(root)} ({len(document['locales'])} locale"
          f"{'' if len(document['locales']) == 1 else 's'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
