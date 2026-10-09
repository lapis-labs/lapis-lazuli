"""Roughs, cards, and narrow renders for the `diverge` tests, made the way the agent and `render check` leave them: files
under `.lapis/diverge/<task>/C<n>/`, and `.lapis/renders/<task>-C<n>.narrow.json` with small screenshots whose pixels follow
the color stance each rough drew. Nothing here replaces a check: the CLI reads these files as it reads real ones."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import yaml
from PIL import Image, ImageDraw

from lapis_design import direction, diverge

# the field and the identity color a rough with that stance paints, as (rgb, oklch) and the first-view area it owns
STANCES = {
    "identity-as-field": ((40, 70, 200), [0.45, 0.2, 265], "the canvas of the whole first view, about 80%"),
    "content-carries-color": ((245, 244, 240), [0.97, 0.005, 90], "the canvas of every section, about 70%"),
    "dark-field": ((18, 20, 28), [0.2, 0.03, 265], "the canvas of the whole first view, about 85%"),
    "two-zone-temperature": ((236, 200, 160), [0.85, 0.07, 70], "the left half of the first view, about 50%"),
    "material-field": ((190, 160, 120), [0.7, 0.07, 75], "the canvas, tinted like the paper, about 75%"),
    "high-key-one-signal": ((250, 250, 252), [0.98, 0.003, 260], "the canvas of the whole first view, about 90%"),
}
SIGNAL = ((220, 60, 40), [0.6, 0.2, 30], "the one action and its mark only, about 3%")


def rough_html(number: int) -> str:
    """Markup whose structure differs by `number`: the number of sections and how the first one is laid out."""
    sections = "".join(f"<section class='s{i}'><h2>Part {i}</h2><p>Text {i}</p></section>" for i in range(number + 2))
    layout = ("display: grid; grid-template-columns: 1fr 1fr" if number % 2 else "display: flex; flex-direction: row")
    return (f"<!doctype html><html><head><style>.s0 {{ {layout}; border: 1px solid #000 }}</style></head>"
            f"<body><main><h1>Kiln {number}</h1>{sections}</main></body></html>\n")


def _view_boxes(number: int, width: int) -> list[dict]:
    """Boxes of the first view: where text, media, and controls sit differs with `number`."""
    h = 900 if width == 1440 else 844
    kinds = ("heading", "media", "button") if number % 3 == 0 else ("media", "text", "link") if number % 3 == 1 else (
        "text", "button", "media")
    boxes = []
    for i, role in enumerate(kinds):
        if width == 1440:
            boxes.append({"role": role, "rect": {"x": 60 + 450 * ((i + number) % 3), "y": 100 + 200 * i, "w": 400, "h": 160}})
        else:
            boxes.append({"role": role, "rect": {"x": 20 + 40 * ((i + number) % 2), "y": 60 + 240 * i, "w": 300, "h": 200}})
    boxes.append({"role": "section", "rect": {"x": 0, "y": 0, "w": width, "h": h}})
    return boxes


def paint(path: Path, size: tuple[int, int], stance: str, number: int) -> None:
    """A screenshot: the stance's field, a block where the media box sits, and the signal for a high-key page."""
    field, _, _ = STANCES[stance]
    image = Image.new("RGB", size, field)
    draw = ImageDraw.Draw(image)
    ink = (255, 255, 255) if sum(field) < 300 else (20, 20, 24)
    draw.rectangle((size[0] // 6, size[1] // 5, size[0] // 2, size[1] // 2), fill=SIGNAL[0] if stance == "high-key-one-signal" else ink)
    draw.line((0, size[1] * 4 // 5, size[0], size[1] * 4 // 5), fill=ink, width=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def write_render(root: Path, task: str, candidate: str, stance: str, number: int, fresh: float | None = None) -> None:
    """The narrow extract of a rough with its two screenshots, newer than the rough's markup."""
    stem = f"{task}-{candidate}.narrow"
    extract = root / ".lapis" / "renders" / f"{stem}.json"
    views = []
    for width, size in ((1440, (288, 180)), (390, (78, 169))):
        shot = root / ".lapis" / "renders" / f"{stem}.shots" / f"{width}-light.png"
        paint(shot, size, stance, number)
        views.append({"width": width, "theme": "light", "reduced_motion": False, "browser_chrome": False,
                      "screenshot": shot.relative_to(extract.parent).as_posix(), "boxes": _view_boxes(number, width)})
    extract.parent.mkdir(parents=True, exist_ok=True)
    extract.write_text(json.dumps({"version": 1, "source": {"kind": "render", "url": f"http://127.0.0.1/{candidate}/",
                                                            "task": f"{task}-{candidate}"}, "viewports": views}), encoding="utf-8")
    rough = root / ".lapis" / "diverge" / task / candidate / "index.html"
    later = (rough.stat().st_mtime if fresh is None else fresh) + 5
    for file in (extract, *extract.parent.joinpath(f"{stem}.shots").iterdir()):
        os.utime(file, (later, later))


def card_for(root: Path, task: str, candidate: str, **changes) -> dict:
    """A card that agrees with the draws of `candidate` and with the owner's answers about each core object."""
    standing = diverge.effective(diverge.draw_records(root, task))[candidate]
    objects = []
    for item in direction.items(root, task, {"LAPIS_UNATTENDED": "1"}):
        if item["kind"] != "O":
            continue
        draw = standing.get(item["id"])
        if draw is not None:
            family, option = draw["item"], draw.get("option")
        else:                                                    # decided by the owner: the option's own family
            option = item["choice"][0]
            family = next(o["family"] for o in item["options"] if o["id"] == option)
        objects.append({"id": item["id"], **({"option": option} if option else {}), "family": family,
                        "medium": "css-drawing", "first_view_share": 0.3,
                        "representation": f"{item['label']} shown as {family}, with a control to try it"})
    _, oklch, area = STANCES[standing["color"]["item"]]
    color = [{"name": "field", "role": "field", "oklch": oklch, "area": area},
             {"name": "identity", "role": "identity", "oklch": SIGNAL[1], "area": SIGNAL[2]}]
    found = {"version": 0, "id": candidate, "direction": standing["direction"]["item"],
             "draws": sorted((r["id"] for r in standing.values()), key=lambda d: int(d[1:])), "objects": objects,
             "color": color, "signature": [], "made_in": "subagent"}
    return {**found, **changes}


def signature(candidate: str) -> list[dict]:
    """One signature element a rough adds in its card: what the owner decides at the second turn."""
    return [{"id": "G1", "element": f"mark of {candidate}", "carries": f"what {candidate} shows first: the next free piece"}]


def write_rough(root: Path, task: str, candidate: str, number: int | None = None, **changes) -> None:
    """The rough, its card, and its render for `candidate`, as an agent leaves them."""
    number = int(candidate[1:]) if number is None else number
    folder = root / ".lapis" / "diverge" / task / candidate
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.html").write_text(rough_html(number), encoding="utf-8")
    found = card_for(root, task, candidate, **changes)
    (folder / "card.yaml").write_text(yaml.safe_dump(found, sort_keys=False), encoding="utf-8")
    stance = diverge.effective(diverge.draw_records(root, task))[candidate]["color"]["item"]
    write_render(root, task, candidate, stance, number)


def complete(root: Path, task: str, k: int = 3) -> None:
    """The whole of `diverge` for `task`: draw, make each rough, check, and seal."""
    diverge.start(root, task, k, entropy="fixture")
    for candidate in diverge.candidate_ids(root, task):
        write_rough(root, task, candidate)
    found = diverge.check(root, task)
    assert not found["problems"], found["problems"]
    diverge.seal(root, task)
