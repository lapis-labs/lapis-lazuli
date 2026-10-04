"""`lazuli hints`: rotating starting points for a task's reference search, not a canon."""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from lapis_design import hints


def main(argv: list[str] | None = None, prog: str = "lazuli hints") -> int:
    ap = argparse.ArgumentParser(prog=prog, description=__doc__, allow_abbrev=False)
    ap.add_argument("--field", choices=[*hints.load()["fields"], "none"], help="nearest field; none only when no field fits")
    ap.add_argument("--task", help="the task id whose offer is recorded")
    ap.add_argument("--date", default=date.today().isoformat(), help="rotation date YYYY-MM-DD (default: today)")
    args = ap.parse_args(argv)
    if bool(args.field) != bool(args.task):
        ap.error("--field and --task go together")
    if args.field is None:
        for field, data in hints.load()["fields"].items():
            print(f"{field}: {data['means']}")
        print("none: no field fits; record an empty offer and search independently")
        return 0
    try:
        offered = hints.draw(Path("."), args.task, args.field, args.date)
    except (OSError, ValueError) as exc:
        ap.error(str(exc))
    record = hints.read(Path("."), args.task)
    print(f"Hints for {args.task}: {args.field}, {record['date']} (starting points, not a canon)")
    for entry in offered:
        print(f"\n{entry['site']} — {entry['url']}\n  Maker: {entry['maker']}\n  Recognition: {entry['recognition']}")
        if entry.get("recognition_url"):
            print(f"  Recognition source: {entry['recognition_url']}")
        print(f"  What to study: {entry['study']}")
    print(f"\nRecorded {hints.path(Path('.'), args.task).as_posix()}. Need at least {len(offered)} agent-found references "
          "beyond the whole hints list, not just this offer. Hints do not waive access policies; look at captures "
          "and source before writing a relation. Existing six-reference, kind, and study-only rules still apply.")
    return 0
