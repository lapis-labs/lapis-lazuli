"""`lapis-design references sheet --task <task>`: one picture of the references record for the owner at D1.

The sheet is `.lapis/references/<task>.sheet.png`: a column per lettered direction (the relation it would organize
the page around as its heading), and in each column the captures of its references, each labelled with its axis and
id. References with `direction: none` or no readable capture are listed by id under the sheet's last line; nothing is
copied into the page, and the sheet is as much for study only as the captures it is made of.
"""
from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from lapis_design import attempts, references

CELL_W, CELL_H, GAP, PAD = 360, 270, 18, 24
BACKGROUND, INK, MUTED = (246, 244, 239), (28, 28, 30), (110, 108, 102)
AXIS_COLORS = {"genre": (47, 94, 160), "expression": (168, 64, 40), "beyond-web": (46, 112, 78)}


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def _thumb(path: Path) -> Image.Image | None:
    try:
        with Image.open(path) as image:
            image.load()
            picture = image.convert("RGB")
    except (OSError, ValueError):
        return None
    if picture.width * 3 // 2 < picture.height:                    # a tall page capture: its first screen
        picture = picture.crop((0, 0, picture.width, picture.width * 3 // 4))
    picture.thumbnail((CELL_W, CELL_H))
    return picture


def compose(root: Path, task: str) -> Path:
    """Write the sheet and return its path. Raises ValueError when there is no record or no direction to group by."""
    groups = references.directions(root, task)
    if not groups:
        raise ValueError(f"{references.record_path(root, task).as_posix()} has no readable `directions`; write the "
                         "record's directions first")
    base = references.folder(root, task)
    head, label, small = _font(22), _font(15), _font(13)
    columns = []
    for letter, group in groups.items():
        cells = []
        for ref in group["refs"]:
            capture = ref.get("capture")
            target = (root / capture) if isinstance(capture, str) else None
            picture = _thumb(target) if target is not None and target.resolve().is_relative_to(base.resolve()) else None
            cells.append((ref, picture))
        columns.append((letter, group["name"], cells))
    title_lines = {letter: textwrap.wrap(f"{letter} — {name}", 30) or [letter] for letter, name, _ in columns}
    head_h = max(len(lines) for lines in title_lines.values()) * 28 + 12
    rows = max((len(cells) for _, _, cells in columns), default=0)
    cell_total = CELL_H + 44
    width = PAD * 2 + len(columns) * CELL_W + (len(columns) - 1) * GAP
    height = PAD * 2 + head_h + rows * (cell_total + GAP)
    sheet = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    for index, (letter, _, cells) in enumerate(columns):
        x = PAD + index * (CELL_W + GAP)
        for line_no, line in enumerate(title_lines[letter]):
            draw.text((x, PAD + line_no * 28), line, fill=INK, font=head)
        y = PAD + head_h
        for ref, picture in cells:
            if picture is not None:
                sheet.paste(picture, (x, y))
            else:
                draw.rectangle((x, y, x + CELL_W, y + CELL_H), outline=MUTED)
                draw.text((x + 12, y + 12), "no readable capture", fill=MUTED, font=small)
            axis = ref.get("axis") if ref.get("axis") in references.AXES else "?"
            draw.text((x, y + CELL_H + 6), axis, fill=AXIS_COLORS.get(axis, MUTED), font=label)
            draw.text((x, y + CELL_H + 25), str(ref.get("id", "?"))[:44], fill=INK, font=small)
            y += cell_total + GAP
    out = root / ".lapis" / "references" / f"{task}.sheet.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def main(argv: list[str] | None = None, prog: str = "lapis-design references sheet") -> int:
    ap = argparse.ArgumentParser(prog=prog, description=__doc__.split("\n\n")[0], allow_abbrev=False)
    ap.add_argument("--task", required=True, help="the task id of the references record")
    ap.add_argument("--project", type=Path, default=Path("."), help="project folder (default: .)")
    args = ap.parse_args(argv)
    if not attempts.TASK.fullmatch(args.task):
        ap.error("task must be lowercase letters, digits, and hyphens")
    try:
        out = compose(args.project, args.task)
    except (OSError, ValueError) as exc:
        print(f"{prog}: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {out}: one column per direction, each capture labelled with its axis and id; for study only")
    return 0
