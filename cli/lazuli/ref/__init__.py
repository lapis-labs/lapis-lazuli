"""`lazuli ref capture|profile|system`: reference profiles in the render extract format.

capture URL          the page the user named, at 390, 768, and 1440 px, through the render capture code
profile IMAGE        an OKLCH palette with area shares from a local image or one at an address
system PATH_OR_URL   type scale, color roles, and state rules from DTCG tokens or a DESIGN.md

Each writes `.lapis/refs/<slug>.json` in the project, validated against render/extract.schema.yaml;
an invalid profile is never written. --rights is required. A URL is checked against the source
registry first, as `lazuli read` does: a source marked `refused` or `browser-link` is never requested.
A reference-only profile keeps no copy, alt text, accessible names, or screenshots: text only as keyed
signatures, images only as perceptual hashes. Screenshots and image copies stay in the lazuli cache,
outside the project, unless --task TASK asks for study copies: a capture then also keeps its screenshots,
the page's own HTML and stylesheets, and facts.md (a digest of what they state about type, color, and
layout), a picture its file, in PROJECT/.lapis/references/TASK/SLUG/. Those are for study only, git-ignored,
and never shipped or copied into a page. A capture's screenshots and its profile change together: they are
put in place one after the other and, if a step fails, the earlier profile and screenshots stay.
Exit codes: 0 written, 1 refused (the source registry, robots.txt, a block or sign-in page, or rights
the page cannot meet), 2 usage, unreadable input, or a profile that could not be written.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from lapis_design import attempts
from lapis_design.render.extract import write_extract
from lazuli.ref import study
from lazuli.ref.common import RIGHTS, SLUG, InputError, Profile, Refused, is_url, path_slug, url_slug

if TYPE_CHECKING:
    from lazuli.ref.site import Capture


def _slug(value: str) -> str:
    if not SLUG.fullmatch(value):
        raise argparse.ArgumentTypeError("lowercase letters, digits, and hyphens, at most 64")
    return value


def _task(value: str) -> str:
    if not attempts.TASK.fullmatch(value):
        raise argparse.ArgumentTypeError("lowercase letters, digits, and hyphens, 2 to 64 characters")
    return value


def _study_files(result: Profile, capture: Capture | None) -> dict[str, bytes | Path]:
    """What `--task` keeps: a capture's screenshots, HTML, stylesheets, and digest, or a picture's file."""
    if capture is None:
        return dict(result.files)
    from lazuli.ref import site

    files: dict[str, bytes | Path] = {f"{width}.png": capture.shots / f"{width}.png" for width, _ in site.VIEWPORTS}
    if capture.source:
        files["page.html"] = capture.source.html
        files.update({f"style-{n}.css": body for n, (_, body) in enumerate(capture.source.sheets, start=1)})
        files["facts.md"] = capture.source.facts.encode("utf-8")
    return files


def _parser(prog: str) -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--rights", required=True, choices=RIGHTS,
                        help="what you may do with the source; reference-only keeps no copy, alt text, "
                             "accessible names, or screenshots")
    common.add_argument("--project", type=Path, default=Path("."),
                        help="project folder; the profile goes to PROJECT/.lapis/refs/SLUG.json (default: .)")
    common.add_argument("--slug", type=_slug, help="profile file name (default: from the URL or file name)")
    common.add_argument("--notes", help="your note, kept in reference.notes")
    common.add_argument("--task", type=_task,
                        help="plan task id: also keep study copies in PROJECT/.lapis/references/TASK/SLUG/ (a "
                             "capture's screenshots, HTML, stylesheets, and a digest of its CSS; a picture's file)")
    common.add_argument("--json", action="store_true", help="machine-readable result")
    ap = argparse.ArgumentParser(prog=prog, description=__doc__.split("\n\n")[0].split(": ", 1)[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 1)[1])
    sub = ap.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("capture", parents=[common], help="capture a page you name (robots.txt respected)")
    capture.add_argument("url")
    profile = sub.add_parser("profile", parents=[common], help="palette of a local image or one at an address")
    profile.add_argument("image", metavar="IMAGE_OR_URL")
    system = sub.add_parser("system", parents=[common], help="type scale, colors, and states of a design system")
    system.add_argument("source", metavar="PATH_OR_URL")
    return ap


def _fail(args: argparse.Namespace, prog: str, message: str) -> int:
    """Usage or input the command cannot use: exit 2."""
    if args.json:
        print(json.dumps({"status": "error", "reason": message}, ensure_ascii=False))
    else:
        print(f"{prog} {args.command}: {message}", file=sys.stderr)
    return 2


def _refused(args: argparse.Namespace, prog: str, refusal: Refused) -> int:
    """A refusal the user acts on (exit 1), reported as `lazuli read` reports its refusals and blocks."""
    if args.json:
        result = {"status": refusal.status, "reason": refusal.reason}
        if refusal.browser_link:
            result["browser_link"] = refusal.browser_link
        if refusal.registry:
            result["registry"] = refusal.registry
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    name, registry = f"{prog} {args.command}", refusal.registry
    if registry:
        print(f"{name}: {registry.get('name') or registry['id']} is `{registry['access']}` in the source "
              f"registry: {refusal.reason}")
        if terms := registry.get("terms_url"):
            print(f"terms: {terms}" + (f" ({registry['clause']})" if registry.get("clause") else ""))
        print(f"open it in your browser: {refusal.browser_link}")
    elif refusal.browser_link:
        print(f"{name}: blocked: {refusal.reason}")
        print(f"lazuli does not get around blocks or sign in; open it in your browser: {refusal.browser_link}")
    else:
        print(f"{name}: {refusal.reason}")
    return 1


def _show(value) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{k.replace('_', ' ')} {_show(v)}" for k, v in value.items())
    if isinstance(value, list):
        return ", ".join(map(str, value))
    return str(value)


def _discard(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def _publish(document: dict, out: Path, capture: Capture | None) -> list[str]:
    """Write the profile `out` and, for a capture, put its screenshots in place, or change nothing.

    Returns the schema problems that stopped it; raises OSError when the disk does. The profile is
    validated and written to a temporary file beside `out` first, so an invalid or half-written profile
    never replaces the earlier one. The screenshots' folder then takes the place of the old folder (the
    old one moved aside, the staging folder renamed into its place) and only then does the profile
    replace the old file; the old folder is deleted last. A failure in any step puts back what the
    earlier steps moved."""
    temp = out.with_name(f".{out.name}.{uuid.uuid4().hex}.tmp")
    try:
        if problems := write_extract(document, temp):
            return problems
        if capture is None:
            os.replace(temp, out)
            return []
        shots, staging = capture.shots, capture.staging
        aside = shots.with_name(f".{shots.name}-old-{uuid.uuid4().hex}")
        had_old = os.path.lexists(shots)
        if had_old:
            os.rename(shots, aside)
        try:
            os.rename(staging, shots)
            try:
                os.replace(temp, out)
            except BaseException:
                os.rename(shots, staging)          # the run's screenshots go back to be discarded
                raise
        except BaseException:
            if had_old:
                os.rename(aside, shots)
            raise
        _discard(aside)
        return []
    finally:
        temp.unlink(missing_ok=True)


def main(argv: list[str] | None = None, prog: str = "lazuli ref") -> int:
    args = _parser(prog).parse_args(argv)
    if not args.project.is_dir():
        return _fail(args, prog, f"project folder not found: {args.project}")
    if args.task and args.command == "system":
        return _fail(args, prog, "--task keeps study copies of a captured page or a picture; a design system has none")
    with contextlib.ExitStack() as stack:
        capture = None
        try:
            if args.command == "capture":
                from lazuli.ref import site

                slug = args.slug or url_slug(args.url)
                capture = site.capture_site(args.url, args.rights, slug, with_source=bool(args.task))
                stack.callback(capture.discard)     # the staging folder, unless it was put in place
                result: Profile = capture.profile
            elif args.command == "profile":
                from lazuli.ref import image

                slug = args.slug or (url_slug(args.image) if is_url(args.image) else path_slug(Path(args.image)))
                result = image.profile_image(args.image, args.rights, slug)
            else:
                from lazuli.ref import system

                slug = args.slug or (url_slug(args.source) if is_url(args.source) else path_slug(Path(args.source)))
                result = system.profile_system(args.source, args.rights)
        except Refused as refusal:
            return _refused(args, prog, refusal)
        except InputError as exc:
            return _fail(args, prog, str(exc))
        document = result.document
        if args.task:
            document["reference"]["captured_by"] = "agent-exploration"     # the run chose this source itself
        if notes := [note for note in (args.notes, *result.notes) if note]:
            document["reference"]["notes"] = " ".join(notes)
        out = args.project / ".lapis" / "refs" / f"{slug}.json"
        try:
            problems = _publish(document, out, capture)
        except OSError as exc:
            return _fail(args, prog, f"could not write {out}: {exc}; the earlier profile and screenshots, "
                         "if any, are unchanged")
        if problems:
            return _fail(args, prog, "the profile does not match the extract schema, so nothing was written: "
                         + "; ".join(problems))
        kept = None
        if args.task:
            try:
                kept = study.keep(args.project, args.task, slug, _study_files(result, capture))
            except OSError as exc:
                return _fail(args, prog, f"the profile {out} was written, but the study copies could not be put under "
                             f".lapis/references/{args.task}/: {exc}")
    if args.json:
        print(json.dumps({"status": "written", "path": str(out), "slug": slug, "kind": document["source"]["kind"],
                          "rights": args.rights, "summary": result.summary,
                          "omitted": [{"field": name, "reason": why} for name, why in result.omitted],
                          "notes": result.notes,
                          **({"study": {"folder": str(kept), "files": sorted(p.name for p in kept.iterdir())}}
                             if kept else {})}, ensure_ascii=False, indent=2))
        return 0
    print(f"wrote {out} ({document['source']['kind']} reference, {args.rights})")
    for key, value in result.summary.items():
        print(f"  {key.replace('_', ' ')}: {_show(value)}")
    for name, why in result.omitted:
        print(f"  left out {name}: {why}")
    for note in result.notes:
        print(f"  note: {note}")
    if kept:
        print(f"  study copies: {kept} ({', '.join(sorted(p.name for p in kept.iterdir()))})")
        pictures = [p for p in sorted(kept.iterdir()) if p.suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp")
                    and p.name != "768.png"]
        print(f"  look before you cite it: open {', '.join(str(p) for p in pictures)} with your image viewer "
              "(Claude Code: Read the path); a relation that describes a picture you did not open is invented")
        print("  for study only: never ship the copies or copy them into a page")
    return 0
