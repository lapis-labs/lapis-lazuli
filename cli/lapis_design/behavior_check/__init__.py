"""Run scoped behavior checks against an owned, locally served render.

For a local-dev backend, --values reads only synthetic fixture values/accounts; its routes
and collections are not attached to browser requests. Without it, input probes are partial.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from jsonschema import ValidationError
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from lapis_design import attempts, check_cache, check_summary, chromium, local_site, narrow, ours, shared_dir
from lapis_design.behavior_check import probes, redact
from lapis_design.behavior_check.driver import Driver, MissingSyntheticValues
from lapis_design.behavior_check.scope import PER_BOX, BoxScope
from lapis_design.behavior_check.session import PROBE_NAMES, Session
from lapis_design.plan_check import read_plan_or_raise


def _stub_reference(path: Path) -> str | None:
    """Record a local stub relative to the project working directory when representable."""
    try:
        return Path(os.path.relpath(path, Path.cwd())).as_posix()
    except ValueError:  # Windows cannot make a relative path across drives.
        return None


def _box_id(text: str) -> str:
    if not re.fullmatch(r"b[0-9a-f]{12}", text):
        raise argparse.ArgumentTypeError(f"{text!r} is not a box id (b and 12 hex digits, as in the session's nodes)")
    return text


def _count(text: str) -> int:
    if not text.isdecimal() or int(text) < 1:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number of at least 1")
    return int(text)


def main(argv: list[str] | None = None, prog: str = "lapis-design behavior check") -> int:
    parser = argparse.ArgumentParser(prog=prog, description="Exercise a locally served render safely.")
    parser.add_argument("url", help="the page: an http(s) URL on a host that is ours, or a file:// URL or path "
                        "of an HTML file (its folder is served on 127.0.0.1 for the run, and the session "
                        "records that address)")
    parser.add_argument("--task", required=True)
    parser.add_argument("--plan", type=Path)
    backend = parser.add_mutually_exclusive_group(required=True)
    backend.add_argument("--stub", type=Path)
    backend.add_argument("--stub-url")
    backend.add_argument("--backend", choices=("local-dev",))
    parser.add_argument("--outbound", choices=("none", "restricted"))
    parser.add_argument("--values", type=Path, help="synthetic fixture values for local-dev input actions")
    parser.add_argument("--extract", type=Path)
    parser.add_argument("--build")
    parser.add_argument("--out", type=Path,
                        help="where to write the session (default .lapis/behavior/<task>.json, or "
                             ".lapis/behavior/<task>.narrow.json when --probe, --context, --box, or --limit narrows "
                             "the run; a narrowed run is refused the full path, which the release gate reads)")
    parser.add_argument("--context", choices=("m", "d"), action="append",
                        help="a context to run, m (390 px, touch) or d (1440 px, mouse); repeatable "
                             "(default: both). Narrows the run")
    parser.add_argument("--probe", action="append", choices=PROBE_NAMES,
                        help="a probe to run; repeatable (default: every probe). The others are recorded as "
                             "skipped. Narrows the run")
    parser.add_argument("--box", action="append", type=_box_id, metavar="ID",
                        help=f"a box id, as in the session's nodes, for the per-box probes ({', '.join(PER_BOX)}) to "
                             "exercise; repeatable. Other boxes are left out, and each probe's coverage is partial "
                             "with a reason that counts them. A control an action reveals is reached only when the "
                             "control that reveals it is named too. Narrows the run")
    parser.add_argument("--limit", type=_count, metavar="N",
                        help="exercise at most N boxes per context in each per-box probe, in document order; the "
                             "rest are left out and counted as with --box. Narrows the run")
    parser.add_argument("--timezone", default="UTC",
                        help="IANA zone the browser contexts run in (default UTC); absolute times without "
                             "a zone are read in it")
    parser.add_argument("--changed-since", type=Path, metavar="REPORT",
                        help="the full session of an earlier build of this page: run only the contexts the files "
                             "changed since then can reach (m is 390 px, d is 1440 px). A stylesheet change confined "
                             "to width-bounded @media blocks narrows to those contexts, or to none when it reaches "
                             "neither width (written beside the full session, as --context does); anything else, and "
                             "anything this cannot prove, runs both")
    parser.add_argument("--fresh", action="store_true",
                        help="run the probes again even when a stored result exists for this build and request; the "
                             "new result replaces it")
    args = parser.parse_args(argv)
    if (args.box or args.limit) and args.probe and not set(args.probe) & set(PER_BOX):
        parser.error(f"--box and --limit narrow the per-box probes ({', '.join(PER_BOX)}), and --probe selects none")
    if not args.out and ("/" in args.task or "\\" in args.task or args.task in (".", "..")):
        parser.error("task must be a filename component when --out is omitted")
    if args.changed_since and (args.context or args.probe or args.box or args.limit or args.fresh):
        parser.error("--changed-since chooses the contexts itself, runs every probe, and reuses nothing; leave out "
                     "--context, --probe, --box, --limit, and --fresh")
    project = Path.cwd()
    started = datetime.now(timezone.utc)
    clock = time.monotonic()
    info = check_summary.RunInfo(command=prog.removeprefix("lapis-design "))
    served = _served(args, project)
    if args.changed_since:
        contexts, why = _contexts_since(project, args, served)
        if contexts == []:
            return _nothing_to_run(args, info, served, why, started, clock)
        if contexts:
            args.context, info.scope_note = contexts, f"--changed-since {args.changed_since}: context {', '.join(contexts)}; {why}"
        else:
            print(f"behavior check: --changed-since: {why}", file=sys.stderr)
    narrowed_by = [flag for flag, given in (("--probe", args.probe), ("--context", args.context),
                                            ("--box", args.box), ("--limit", args.limit)) if given]
    if narrowed_by and not info.scope_note:
        info.scope_note = "; ".join(part for part in (
            args.context and "--context " + ", ".join(sorted(args.context)),
            args.probe and "--probe " + ", ".join(args.probe),
            args.box and f"--box {len(args.box)} box(es)", args.limit and f"--limit {args.limit}") if part)
    args.out = narrow.output_path(parser, args.out, "behavior", args.task, narrowed_by)
    args.command = attempts.command_line(prog, argv)
    args.full_run = not narrowed_by and args.out == Path(".lapis") / "behavior" / f"{args.task}.json"
    info.scope = "narrow" if narrowed_by else "full"
    key = _key(args, served)
    if key is not None:
        info.build_id, info.state_key = key.build_id, key.state_key
    previous = _read_json(args.out)
    target = args.url

    def produce() -> int:
        try:
            with local_site.serve(target) as url:
                args.url = url
                return _check(parser, args)
        except local_site.NotServable as exc:      # raised on entry; the run itself never raises it
            parser.error(str(exc))

    def stable() -> str | None:
        if check_cache.tree_manifest(served.folder) != served.manifest:
            return "the served files changed while the probes ran"
        return None

    try:
        outcome = check_cache.run(project, key, out=args.out, shots=None, fresh=args.fresh, produce=produce, stable=stable)
    except SystemExit as stop:                 # a usage error found once the run began: still one line in the log
        check_summary.record_run(info, task=args.task, started=started, exit_code=stop.code if isinstance(stop.code, int) else 2,
                                 output_chars=0, report_path=args.out)
        raise
    info.cache, info.reason, info.run_seconds = outcome.cache, outcome.reason, outcome.run_seconds
    info.created, info.waited, info.wall_seconds = outcome.created, outcome.waited, time.monotonic() - clock
    printed = 0
    if outcome.exit == 0:
        if args.full_run:
            attempts.clear(args.task, "behavior")
        session = _read_json(args.out)
        if session is not None:
            printed = check_summary.emit(check_summary.behavior_lines(session, args.out, info, previous))
    check_summary.record_run(info, task=args.task, started=started, exit_code=outcome.exit, output_chars=printed,
                             report_path=args.out)
    return outcome.exit


def _read_json(path: Path) -> dict | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) else None


def _served(args: argparse.Namespace, project: Path) -> check_cache.Served | None:
    """The identity of the page, when it is one we serve and every input the run reads is a file we can hash. A
    `--stub-url` or `--backend local-dev` run reads state this CLI does not hold: no identity, so no cache."""
    if args.stub_url or args.backend:
        return None
    try:
        served = check_cache.served(args.url, project)
    except OSError:
        return None
    inputs = check_cache.file_params(plan=args.plan, stub=args.stub, values=args.values, extract=args.extract)
    return served if served is not None and all(item["sha256"] for item in inputs.values()) else None


def _params(args: argparse.Namespace) -> dict:
    return {"task": args.task, "timezone": args.timezone, "outbound": args.outbound, "build": args.build,
            **check_cache.file_params(plan=args.plan, stub=args.stub, values=args.values, extract=args.extract)}


def _key(args: argparse.Namespace, served: check_cache.Served | None) -> check_cache.Key | None:
    if served is None:
        return None
    return check_cache.make_key("behavior", served, _params(args), {
        "contexts": sorted(args.context or ["m", "d"]), "probes": sorted(args.probe or []),
        "boxes": sorted(args.box or []), "limit": args.limit, "out": args.out.name})


CONTEXT_WIDTHS = {"m": 390, "d": 1440}          # the widths the two behavior contexts run at


def _contexts_since(project: Path, args: argparse.Namespace,
                    served: check_cache.Served | None) -> tuple[list[str] | None, str]:
    """`(contexts, why)` for `--changed-since REPORT`: the contexts the change since that report's build can reach,
    `[]` when none, and None (both) whenever the dependency cannot be proven."""
    if served is None:
        return None, "this page's build cannot be identified, so both contexts run"
    before = check_cache.previous(project, args.changed_since)
    if before is None:
        return None, f"{args.changed_since} is not a report this CLI stored (edited, replaced, or pruned), so both contexts run"
    full = {"contexts": ["d", "m"], "probes": [], "boxes": [], "limit": None}
    if before.get("kind") != "behavior" or {k: (before.get("selection") or {}).get(k) for k in full} != full:
        return None, f"{args.changed_since} is not a full behavior check, so both contexts run"
    if before.get("params") != check_cache.make_key("behavior", served, _params(args)).params:
        return None, "the request, plan, stub, values, or tool differ from that report's, so both contexts run"
    reached, why = check_cache.affected_widths(before, served)
    if reached is None:
        return None, f"{why}; both contexts run"
    contexts = [name for name, width in CONTEXT_WIDTHS.items() if width in reached]
    if len(contexts) == len(CONTEXT_WIDTHS):
        return None, f"{why}; the change reaches both contexts"
    if not contexts:
        widths = ", ".join(map(str, sorted(reached))) or "none"
        return [], f"{why}; it reaches widths {widths}, and behavior runs only 390 and 1440"
    return contexts, why


def _nothing_to_run(args: argparse.Namespace, info: check_summary.RunInfo, served: check_cache.Served | None, why: str,
                    started: datetime, clock: float) -> int:
    """`--changed-since` found no context the change reaches: say so, with the build, and run no browser."""
    info.scope, info.cache = "narrow", "hit"
    info.scope_note = f"--changed-since {args.changed_since}: no context to run"
    if served is not None:
        info.build_id = served.build_id
        info.state_key = check_cache.make_key("behavior", served, _params(args)).state_key
    info.wall_seconds = time.monotonic() - clock
    printed = check_summary.emit([
        f"behavior check: nothing to run; {why} (build {info.build_id}); no browser run",
        check_summary.scope_line(info),
        f"  {args.changed_since} still describes this build in both contexts; the release gate still needs a full "
        "session of the final build"])
    check_summary.record_run(info, task=args.task, started=started, exit_code=0, output_chars=printed,
                             report_path=args.changed_since)
    return 0


def _check(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    try:
        args.url = ours.canonical_start_url(args.url)
        url = urlsplit(args.url)
    except ValueError:
        parser.error("invalid source URL")
    schema = yaml.safe_load((shared_dir() / "behavior" / "session.schema.yaml").read_text())
    zone_pattern = schema["$defs"]["context"]["properties"]["timezone"]["pattern"]
    if not re.fullmatch(zone_pattern, args.timezone) or not _known_zone(args.timezone):
        parser.error(f"--timezone {args.timezone!r} is not an IANA time zone")
    if url.scheme not in ("http", "https"):
        parser.error(local_site.http_only("behavior check"))
    source = urlunsplit((url.scheme, url.netloc, url.path or "/", "", ""))
    source_pattern = schema["properties"]["source"]["properties"]["url"]["pattern"]
    if not url.hostname or url.username or url.password or not re.fullmatch(source_pattern, source):
        parser.error("source URL must use HTTP(S) on a host that is ours and accepted by the session schema")
    source_pin = ours.pin_source(args.url)
    if not ours.source_is_ours(url.hostname.rstrip("."), list(source_pin.addresses) if source_pin else None):
        parser.error("source URL must use HTTP(S) on a host that is ours")
    stub_pin = None
    if args.stub_url:
        try:
            args.stub_url = ours.canonical_start_url(args.stub_url)
            remote = urlsplit(args.stub_url)
            same_host = source_pin is not None and remote.hostname and remote.hostname.rstrip(".") == source_pin.host
            stub_pin = ours.pin_source(
                args.stub_url, resolved=list(source_pin.addresses) if same_host else None,
                pinned_address=source_pin.address if same_host else None)
        except ValueError:
            parser.error("invalid --stub-url")
        if (remote.scheme not in ("http", "https") or not remote.hostname or remote.username or remote.password or
                not ours.source_is_ours(remote.hostname.rstrip("."), list(stub_pin.addresses) if stub_pin else None)):
            parser.error("--stub-url must use HTTP(S) on a host that is ours")
    if args.backend and not args.outbound:
        parser.error("--backend local-dev requires --outbound none|restricted")
    if args.outbound and not args.backend:
        parser.error("--outbound is only valid with --backend local-dev")
    if args.values and not args.backend:
        parser.error("--values is only valid with --backend local-dev")
    output = args.out
    # Do not reach the browser until the source address has passed the session contract.
    try:
        plan = read_plan_or_raise(args.plan) if args.plan else None
        engine = None
        values_engine = None
        if args.stub or args.values:
            from lapis_design.stub.engine import StubEngine
            if args.stub:
                engine = StubEngine.load(args.stub)
            else:
                values_engine = StubEngine.load(args.values)
        elif args.stub_url:
            from lapis_design.stub.remote import RemoteStub
            engine = RemoteStub(args.stub_url, pin=stub_pin)
        session = Session(args.url, args.task, engine=engine, values_engine=values_engine, plan=plan,
                          plan_path=str(args.plan) if args.plan else None,
                          backend="local-dev" if args.backend else "stub", outbound=args.outbound,
                          build=args.build, extract=str(args.extract) if args.extract else None,
                          stub_path=_stub_reference(args.stub) if args.stub else None,
                          timezone=args.timezone, addresses=list(source_pin.addresses) if source_pin else None,
                          scope=BoxScope(args.box or (), args.limit))
        selected = args.context or ["m", "d"]
        # Probes iterate session.matrix; unselected default contexts must not run or appear.
        session.contexts = {ctx_id: session.contexts[ctx_id] for ctx_id in selected}
        with sync_playwright() as playwright:
            pins = [pin for pin in (source_pin, stub_pin) if pin is not None]
            pins = list({pin.host: pin for pin in pins}.values())
            browser = chromium.launch(playwright, ours.chromium_args(pins))
            try:
                def open_driver(ctx_id):
                    driver = Driver(browser, session, ctx_id)
                    try:
                        driver.open()
                        return driver
                    except Exception:
                        driver.close()
                        raise

                for ctx_id in selected:
                    driver = open_driver(ctx_id)
                    driver.close()
                for probe in probes.PROBES:
                    names = probe.NAMES
                    if args.probe and not set(names).intersection(args.probe):
                        continue
                    try:
                        probe.run(session, open_driver)
                    except MissingSyntheticValues:
                        for name in names:
                            session.cover(name, "partial", reason="no synthetic values (--values)")
                    except Exception as exc:
                        # the first line names the failure; Playwright call logs stay out of the session
                        first = f"{type(exc).__name__}: {exc}".splitlines()[0]
                        for name in names:
                            session.cover(name, "skipped", reason=redact.console(first, session.fixture_values))
                    finally:
                        for driver in tuple(session.drivers):
                            driver.close()
                selected_names = {name for probe in probes.PROBES for name in probe.NAMES
                                  if not args.probe or set(probe.NAMES).intersection(args.probe)}
                for name in PROBE_NAMES:
                    if name == "console":
                        session.cover("console", "ran", contexts=selected)
                    elif not any(entry["probe"] == name for entry in session.coverage):
                        session.cover(name, "skipped", reason="probe recorded no coverage" if name in selected_names
                                      else "not selected (--probe)")
            finally:
                for driver in tuple(session.drivers):
                    driver.close()
                browser.close()
        document = session.document()
        payload = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent,
                                             prefix=output.name + ".", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
            temporary.replace(output)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    except (chromium.BrowserUnavailable, OSError, ValueError, PlaywrightError, ValidationError, yaml.YAMLError) as exc:
        print(f"behavior check: {exc}", file=sys.stderr)
        attempts.record_failure(exc, task=args.task, step="behavior", command=args.command, exit_code=2,
                                full_run=args.full_run)
        return 2
    return 0


def _known_zone(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError):
        return False
    return True
