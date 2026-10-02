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
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from jsonschema import ValidationError
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from lapis_design import chromium, local_site, ours, shared_dir
from lapis_design.behavior_check import probes, redact
from lapis_design.behavior_check.driver import Driver, MissingSyntheticValues
from lapis_design.behavior_check.session import PROBE_NAMES, Session
from lapis_design.plan_check import read_plan_or_raise


def _stub_reference(path: Path) -> str | None:
    """Record a local stub relative to the project working directory when representable."""
    try:
        return Path(os.path.relpath(path, Path.cwd())).as_posix()
    except ValueError:  # Windows cannot make a relative path across drives.
        return None


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
    parser.add_argument("--out", type=Path)
    parser.add_argument("--context", choices=("m", "d"), action="append")
    parser.add_argument("--probe", action="append", choices=PROBE_NAMES)
    parser.add_argument("--timezone", default="UTC",
                        help="IANA zone the browser contexts run in (default UTC); absolute times without "
                             "a zone are read in it")
    args = parser.parse_args(argv)
    try:
        with local_site.serve(args.url) as url:
            args.url = url
            return _check(parser, args)
    except local_site.NotServable as exc:      # raised on entry; the run itself never raises it
        parser.error(str(exc))


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
    if not args.out and ("/" in args.task or "\\" in args.task or args.task in (".", "..")):
        parser.error("task must be a filename component when --out is omitted")
    output = args.out or Path(".lapis") / "behavior" / f"{args.task}.json"
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
                          timezone=args.timezone, addresses=list(source_pin.addresses) if source_pin else None)
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
        return 2
    print(f"{len(document['contexts'])} contexts, {len(document['nodes'])} nodes, "
          f"{len(document['coverage'])} coverage entries -> {output}")
    return 0


def _known_zone(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError):
        return False
    return True
