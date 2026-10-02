"""Capture owned web renders as schema-validated extracts; public hosts require --public."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from lapis_design import local_site, ours
from lapis_design.render import hosts
from lapis_design.sig_key import load_key


def sync_playwright():
    """Browser launch seam; importing the render package does not import Playwright."""
    from playwright.sync_api import sync_playwright as start
    return start()


def launch_args(pins: list[ours.SourcePin]) -> list[str]:
    """Compose render Chromium arguments; tests can swap this function for their own trust pin."""
    return ours.chromium_args(pins)


def _configs(dark: bool, widths: list[int] | None) -> list[dict]:
    selected = set(widths or (320, 390, 768, 1440))
    captures = []
    for width, height in ((320, 568), (390, 844), (768, 1024), (1440, 900)):
        if width not in selected:
            continue
        for theme, reduced, chrome in (
            [("light", False, False)] +
            ([("dark", False, False)] if dark and width != 320 else []) +
            ([("light", True, False), ("light", False, True)] if width == 390 else [])
        ):
            captures.append({"width": width, "layout_height": height,
                             "height": 664 if chrome else height, "theme": theme,
                             "reduced_motion": reduced, "browser_chrome": chrome, "dpr": 2})
    return captures


def main(argv: list[str] | None = None, prog: str = "lapis-design render check") -> int:
    parser = argparse.ArgumentParser(prog=prog, description="Capture a rendered page as a render extract.")
    parser.add_argument("url", help="the page: an http(s) URL, or a file:// URL or path of an HTML file (its "
                        "folder is served on 127.0.0.1 for the run, and the extract records that address)")
    parser.add_argument("--task")
    parser.add_argument("--plan", type=Path, help="the task's plan; hosts in its references are never "
                        "captured (default: .lapis/plans/<task>.yaml when it exists)")
    parser.add_argument("--public", action="store_true", help="capture a public host of ours; source-registry "
                        "and plan-reference hosts stay refused (use `lazuli ref capture` for those)")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--width", type=int, choices=(320, 390, 768, 1440), action="append")
    args = parser.parse_args(argv)
    try:
        with local_site.serve(args.url) as url:
            args.url = url
            return _capture(parser, args)
    except local_site.NotServable as exc:      # raised on entry; the run itself never raises it
        parser.error(str(exc))


def _capture(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    from playwright.sync_api import Error as PlaywrightError
    from lapis_design.render.capture import capture, has_dark_theme
    from lapis_design.render.extract import assemble, write_extract
    if not args.out and args.task and ("/" in args.task or "\\" in args.task or args.task in (".", "..")):
        parser.error("task must be a filename component when --out is omitted")
    out = args.out or Path(".lapis") / "renders" / f"{args.task or 'render'}.json"
    screenshots = out.parent / f"{out.stem}.shots"
    guard = None
    try:
        url = ours.canonical_start_url(args.url)
        plan = hosts.load_plan(hosts.plan_path(args.plan, args.task))
        pin = ours.pin_source(url)
        policy = hosts.HostPolicy(public=args.public, plan=plan, pins=[pin] if pin else [])
        policy.check(url)                     # before the browser opens
        signature = ((plan or {}).get("layout") or {}).get("signature")
        key = load_key()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(args=launch_args([pin] if pin else []))
            guard = hosts.GuardedBrowser(browser, policy)
            try:
                dark = has_dark_theme(guard, url)
                guard.check()
                viewports = []
                for index, config in enumerate(_configs(dark, args.width)):
                    filename = f"{index:02d}-{config['width']}-{config['theme']}"
                    if config["reduced_motion"]:
                        filename += "-reduced"
                    if config["browser_chrome"]:
                        filename += "-chrome"
                    shot = screenshots / f"{filename}.png"
                    vp = capture(guard, url, config, shot, key, plan_signature=signature)
                    guard.check()
                    vp["screenshot"] = shot.relative_to(out.parent).as_posix()
                    viewports.append(vp)
            finally:
                browser.close()
        document = assemble(url, args.task, viewports, key, dark_theme=dark)
        if pin:
            document["source"]["addresses"] = list(pin.addresses)
        if problems := write_extract(document, out):
            for problem in problems:
                print(f"render extract invalid: {problem}", file=sys.stderr)
            return 2
    except (hosts.Refused, OSError, ValueError, PlaywrightError, yaml.YAMLError) as exc:
        # a navigation the guard blocked surfaces as a Playwright error; report the refusal instead
        print(f"render check: {guard.refused if guard and guard.refused else exc}", file=sys.stderr)
        return 2
    print(f"{len(viewports)} viewports, {sum(len(v['boxes']) for v in viewports)} boxes, "
          f"{sum(len(v['text']) for v in viewports)} runs -> {out}")
    return 0
