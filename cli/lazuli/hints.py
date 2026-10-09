"""`lazuli hints`: rotating starting points for a task's reference search on three axes, not a canon."""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from lapis_design import hints, requirements


def _list() -> None:
    axes = hints.load()["axes"]
    print("genre (--genre; pages of the subject's own kind):")
    for field, data in axes["genre"].items():
        print(f"  {field}: {data['means']}")
    print("  none: no field fits; record an empty offer and search independently")
    print("expression (--expression, at most two; work that does what the owner's words ask for):")
    for mode, data in axes["expression"].items():
        print(f"  {mode}{' [motion]' if data['motion'] else ''}: {data['means']} (owner words: {', '.join(data['words'])})")
    print("beyond-web (--beyond-web, at most two; never a web-ui reference):")
    for medium, data in axes["beyond-web"].items():
        print(f"  {medium} [{data['kind']}]: {data['means']}")


def _suggest(root: Path, task: str) -> int:
    texts = []
    for path in (root / ".lapis/taste.md",):
        try:
            texts.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    texts += [str(row.get("text", "")) for row in requirements.rows(root, task) or []]
    found = hints.suggest("\n".join(texts))
    if not found:
        print(f"No expression mode's words occur in .lapis/taste.md or the requirement rows of {task}. "
              "That is a lexical lead only: read the brief yourself, and choose a mode only if the owner asked for one.")
        return 0
    print("Expression modes whose words occur in the owner's lines (a lexical lead, not a verdict; you choose, and D1 "
          "states the choice):")
    for mode, words in found.items():
        print(f"  {mode}: {', '.join(words)}")
    return 0


def _names(value: str | None) -> list[str]:
    return [] if not value or value == "none" else [part.strip() for part in value.split(",") if part.strip()]


def _show(entry: dict) -> None:
    print(f"\n{entry['site']} — {entry['url']}\n  Maker: {entry['maker']}\n  Recognition: {entry['recognition']}")
    if entry.get("recognition_url"):
        print(f"  Recognition source: {entry['recognition_url']}")
    if entry.get("shows"):
        print(f"  Shows: {entry['shows']}")
    print(f"  What to study: {entry['study']}")


def main(argv: list[str] | None = None, prog: str = "lazuli hints") -> int:
    ap = argparse.ArgumentParser(prog=prog, description=__doc__, allow_abbrev=False)
    ap.add_argument("--genre", help="nearest genre field, or none when no field fits")
    ap.add_argument("--expression", help="expression mode or two, comma-separated (none or omitted: no offer)")
    ap.add_argument("--beyond-web", dest="beyond_web", help="beyond-web medium or two, comma-separated "
                                                           "(none or omitted: no offer)")
    ap.add_argument("--suggest", action="store_true", help="list the expression modes whose words occur in "
                    ".lapis/taste.md and the requirement rows of --task")
    ap.add_argument("--task", help="the task id whose offer is recorded")
    ap.add_argument("--date", default=date.today().isoformat(), help="rotation date YYYY-MM-DD (default: today)")
    args = ap.parse_args(argv)
    if args.suggest:
        if not args.task or args.genre or args.expression or args.beyond_web:
            ap.error("--suggest takes --task and nothing else")
        return _suggest(Path("."), args.task)
    if args.genre is None and args.task is None and not (args.expression or args.beyond_web):
        _list()
        return 0
    if args.genre is None or args.task is None:
        ap.error("--genre and --task go together (--genre none when no field fits)")
    axes = hints.load()["axes"]
    expression, beyond = _names(args.expression), _names(args.beyond_web)
    if args.genre != "none" and args.genre not in axes["genre"]:
        ap.error(f"--genre must be one of {', '.join([*axes['genre'], 'none'])}")
    try:
        offered = hints.draw(Path("."), args.task, args.genre, args.date, expression, beyond)
    except (OSError, ValueError) as exc:
        ap.error(str(exc))
    record = hints.read(Path("."), args.task)
    print(f"Hints for {args.task}: genre {args.genre}; expression {', '.join(expression) or 'none'}; "
          f"beyond-web {', '.join(beyond) or 'none'}; {record['date']} (starting points, not a canon)")
    sections = [("genre", hints.COUNT if args.genre != "none" else 0),
                *(("expression/" + name, hints.PER_NAME) for name in expression),
                *(("beyond-web/" + name, hints.PER_NAME) for name in beyond)]
    for label, count in sections:
        print(f"\n== {label} ==" if count else f"\n== {label}: no offer ==")
        for entry in offered[:count]:
            _show(entry)
        offered = offered[count:]
    print(f"\nRecorded {hints.path(Path('.'), args.task).as_posix()}. Need at least one agent-found reference per axis "
          "(genre, expression, beyond-web) beyond the whole hints list, not just this offer, and at least two "
          "references seen as images per axis. Hints do not waive access policies; look at captures and source "
          "before writing a relation. Existing six-reference, kind, and study-only rules still apply.")
    return 0
