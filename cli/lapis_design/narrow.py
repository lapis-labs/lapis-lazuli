"""Where a check writes its report: a run that checks less than everything never writes the full report."""
from __future__ import annotations

import argparse
from pathlib import Path


def output_path(parser: argparse.ArgumentParser, out: Path | None, folder: str, stem: str,
                narrowed_by: list[str]) -> Path:
    """The report's path: `.lapis/<folder>/<stem>.json` for a full run, `<stem>.narrow.json` beside it for a run
    that `narrowed_by` the given flags, and `out` when the caller named a file.

    The release gate and lint read the full path as the evidence of a full run, so a narrowed run told to write
    exactly that file is refused, before anything starts: its unselected parts would read as missing evidence."""
    full = Path(".lapis") / folder / f"{stem}.json"
    if not narrowed_by:
        return out or full
    narrow = full.with_name(f"{stem}.narrow.json")
    if out is None:
        return narrow
    if out.resolve() == full.resolve():
        parser.error(f"{' '.join(narrowed_by)} narrows the run, so it cannot write the full report {full.as_posix()}; "
                     f"leave out --out to write {narrow.as_posix()}, or name another file")
    return out
