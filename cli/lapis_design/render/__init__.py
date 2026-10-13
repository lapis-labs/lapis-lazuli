"""Capture owned web renders as schema-validated extracts; public hosts require --public."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from lapis_design import attempts, check_cache, check_summary, chromium, local_site, narrow, ours
from lapis_design.render import hosts
from lapis_design.sig_key import load_key
from lapis_design.text_sig import key_id


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


def _read_json(path: Path) -> dict | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) else None


def _request_params(args: argparse.Namespace) -> dict | None:
    """What a capture reads besides the served files: the task, the plan's signature, phone task, and references, the
    signing key. None when one of them cannot be read (the capture then reports why, and the cache is off)."""
    try:
        plan = hosts.load_plan(hosts.plan_path(args.plan, args.task))
        layout = (plan or {}).get("layout") or {}
        return {"task": args.task, "public": args.public, "references": (plan or {}).get("references"),
                "signature": layout.get("signature"), "phone_task": layout.get("phone_task"),
                "sig_key": key_id(load_key())}
    except (OSError, ValueError, yaml.YAMLError):
        return None


def _widths_since(project: Path, report: Path, served: check_cache.Served | None,
                  params: dict | None) -> tuple[list[int] | None, str]:
    """`(widths, why)` for `--changed-since REPORT`: the widths the change since that report's build can reach, `[]` when
    none, and None (every width) whenever the dependency cannot be proven."""
    if served is None or params is None:
        return None, "this page's build cannot be identified, so every width is captured"
    before = check_cache.previous(project, report)
    if before is None:
        return None, f"{report} is not a report this CLI stored (edited, replaced, or pruned), so every width is captured"
    if (before.get("kind") != "render" or sorted((before.get("selection") or {}).get("widths") or []) != list(check_cache.WIDTHS)):
        return None, f"{report} is not a full render check, so every width is captured"
    now = check_cache.make_key("render", served, params)
    if before.get("params") != now.params:
        return None, "the request, plan signature, or tool differ from that report's, so every width is captured"
    reached, why = check_cache.affected_widths(before, served)
    if reached is None:
        return None, f"{why}; every width is captured"
    if reached and len(reached) == len(check_cache.WIDTHS):
        return None, f"{why}; the change reaches every width"
    return sorted(reached), why


def main(argv: list[str] | None = None, prog: str = "lapis-design render check") -> int:
    parser = argparse.ArgumentParser(prog=prog, description="Capture a rendered page as a render extract.")
    parser.add_argument("url", help="the page: an http(s) URL, or a file:// URL or path of an HTML file (its "
                        "folder is served on 127.0.0.1 for the run, and the extract records that address)")
    parser.add_argument("--task")
    parser.add_argument("--plan", type=Path, help="the task's plan; hosts in its references are never "
                        "captured (default: .lapis/plans/<task>.yaml when it exists)")
    parser.add_argument("--public", action="store_true", help="capture a public host of ours; source-registry "
                        "and plan-reference hosts stay refused (use `lazuli ref capture` for those)")
    parser.add_argument("--out", type=Path,
                        help="where to write the extract (default .lapis/renders/<task>.json, with the screenshots "
                             "in <task>.shots/ beside it; .lapis/renders/<task>.narrow.json and <task>.narrow.shots/ "
                             "when --width narrows the run, which is refused the full path the release gate reads)")
    parser.add_argument("--width", type=int, choices=(320, 390, 768, 1440), action="append",
                        help="a width to capture; repeatable (default: all four, with their themes). The release "
                             "gate needs all four, so this narrows the run")
    parser.add_argument("--changed-since", type=Path, metavar="REPORT",
                        help="the full extract of an earlier build of this page: capture only the widths the files "
                             "changed since then can reach. A stylesheet change confined to width-bounded @media "
                             "blocks narrows to those widths (written beside the full extract, as --width does); a "
                             "changed page, script, font, image, or any rule outside a width query, and anything this "
                             "cannot prove, captures every width")
    parser.add_argument("--fresh", action="store_true",
                        help="capture again even when a stored result exists for this build and request; the new "
                             "result replaces it")
    args = parser.parse_args(argv)
    if not args.out and args.task and ("/" in args.task or "\\" in args.task or args.task in (".", "..")):
        parser.error("task must be a filename component when --out is omitted")
    if args.changed_since and (args.width or args.fresh):
        parser.error("--changed-since chooses the widths itself and reuses nothing; leave out --width and --fresh")
    project = Path.cwd()
    started = datetime.now(timezone.utc)
    clock = time.monotonic()
    command = prog.removeprefix("lapis-design ")
    info = check_summary.RunInfo(command=command)
    served = params = None
    try:
        served = check_cache.served(args.url, project)
        params = _request_params(args) if served is not None else None
    except OSError:
        served = None
    if args.changed_since:
        widths, why = _widths_since(project, args.changed_since, served, params)
        if widths == []:
            return _nothing_to_capture(args, info, served, params, why, started, clock)
        if widths:
            args.width, info.scope_note = widths, f"--changed-since {args.changed_since}: widths {', '.join(map(str, widths))}; {why}"
        else:
            info.scope_note = None
            print(f"render check: --changed-since: {why}", file=sys.stderr)
    elif args.width:
        info.scope_note = f"--width {', '.join(map(str, sorted(args.width)))}"
    args.out = narrow.output_path(parser, args.out, "renders", args.task or "render", ["--width"] if args.width else [])
    args.command = attempts.command_line(prog, argv)
    args.full_run = bool(args.task) and not args.width and args.out == Path(".lapis") / "renders" / f"{args.task}.json"
    info.scope = "narrow" if args.width else "full"
    key = None
    if served is not None and params is not None:
        key = check_cache.make_key("render", served, params,
                                   {"widths": sorted(args.width or check_cache.WIDTHS), "out": args.out.name})
        info.build_id, info.state_key = key.build_id, key.state_key
    previous = _read_json(args.out)
    target = args.url
    shots = args.out.parent / f"{args.out.stem}.shots"

    def produce() -> int:
        try:
            with local_site.serve(target) as url:
                args.url = url
                args.page_origin = f"{urlsplit(url).scheme}://{urlsplit(url).netloc}"
                return _capture(parser, args)
        except local_site.NotServable as exc:      # raised on entry; the run itself never raises it
            parser.error(str(exc))

    def stable() -> str | None:
        if check_cache.tree_manifest(served.folder) != served.manifest:
            return "the served files changed while the capture ran"
        if foreign := check_cache.foreign_origins(getattr(args, "origins", ()), args.page_origin):
            return f"the page asked other origins ({', '.join(foreign[:3])}); their answers are not part of the build"
        return None

    try:
        outcome = check_cache.run(project, key, out=args.out, shots=shots, fresh=args.fresh, produce=produce, stable=stable)
    except SystemExit as stop:                 # a usage error found once the run began: still one line in the log
        check_summary.record_run(info, task=args.task, started=started, exit_code=stop.code if isinstance(stop.code, int) else 2,
                                 output_chars=0, report_path=args.out)
        raise
    info.cache, info.reason, info.run_seconds = outcome.cache, outcome.reason, outcome.run_seconds
    info.created, info.waited, info.wall_seconds = outcome.created, outcome.waited, time.monotonic() - clock
    printed = 0
    if outcome.exit == 0:
        if args.full_run:
            attempts.clear(args.task, "render")
        extract = _read_json(args.out)
        if extract is not None:
            printed = check_summary.emit(check_summary.render_lines(extract, args.out, info, previous))
    check_summary.record_run(info, task=args.task, started=started, exit_code=outcome.exit, output_chars=printed,
                             report_path=args.out)
    return outcome.exit


def _nothing_to_capture(args: argparse.Namespace, info: check_summary.RunInfo, served: check_cache.Served | None,
                        params: dict | None, why: str, started: datetime, clock: float) -> int:
    """`--changed-since` found no width the change reaches: say so, with the build, and run no browser."""
    info.scope, info.cache = "narrow", "hit"
    info.scope_note = f"--changed-since {args.changed_since}: no width to capture"
    if served is not None:
        info.build_id = served.build_id
        if params is not None:
            info.state_key = check_cache.make_key("render", served, params).state_key
    info.wall_seconds = time.monotonic() - clock
    lines = [f"render check: nothing to capture; {why} (build {info.build_id}); no browser run",
             check_summary.scope_line(info),
             f"  {args.changed_since} still describes this build at every width; the release gate still needs a full "
             "extract of the final build"]
    printed = check_summary.emit(lines)
    check_summary.record_run(info, task=args.task, started=started, exit_code=0, output_chars=printed,
                             report_path=args.changed_since)
    return 0


def _capture(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    from playwright.sync_api import Error as PlaywrightError
    from lapis_design.render.capture import capture, has_dark_theme
    from lapis_design.render.extract import assemble, write_extract
    out = args.out
    screenshots = out.parent / f"{out.stem}.shots"
    guard = None
    identity: dict = {}
    try:
        url = ours.canonical_start_url(args.url)
        plan = hosts.load_plan(hosts.plan_path(args.plan, args.task))
        pin = ours.pin_source(url)
        policy = hosts.HostPolicy(public=args.public, plan=plan, pins=[pin] if pin else [])
        policy.check(url)                     # before the browser opens
        signature = ((plan or {}).get("layout") or {}).get("signature")
        phone_task = ((plan or {}).get("layout") or {}).get("phone_task")
        key = load_key()
        with sync_playwright() as playwright:
            browser = chromium.launch(playwright, launch_args([pin] if pin else []))
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
                    vp = capture(guard, url, config, shot, key, plan_signature=signature, phone_task=phone_task,
                                 identity=identity)
                    guard.check()
                    vp["screenshot"] = shot.relative_to(out.parent).as_posix()
                    viewports.append(vp)
            finally:
                args.origins = set(guard.origins)
                browser.close()
        document = assemble(url, args.task, viewports, key, dark_theme=dark)
        if pin:
            document["source"]["addresses"] = list(pin.addresses)
        if identity:
            document["source"].update(identity)
        if problems := write_extract(document, out):
            for problem in problems:
                print(f"render extract invalid: {problem}", file=sys.stderr)
            return 2
    except (hosts.Refused, chromium.BrowserUnavailable, OSError, ValueError, PlaywrightError, yaml.YAMLError) as exc:
        # a navigation the guard blocked surfaces as a Playwright error; report the refusal instead
        refused = guard.refused if guard and guard.refused else exc
        print(refused if isinstance(refused, hosts.WrongScheme) else f"render check: {refused}", file=sys.stderr)
        if refused is exc:
            attempts.record_failure(exc, task=args.task, step="render", command=args.command, exit_code=2,
                                    full_run=args.full_run)
        return 2
    return 0
