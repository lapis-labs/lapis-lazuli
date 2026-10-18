"""Roughs, cards, and narrow renders for the `diverge` tests, made the way the agent and `render check` leave them: files
under `.lapis/diverge/<task>/C<n>/`, and `.lapis/renders/<task>-C<n>.narrow.json` with small screenshots whose pixels follow
the color stance each rough drew. Nothing here replaces a check: the CLI reads these files as it reads real ones."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
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
FACES = {"headline": "Gowun Batang", "body": "Pretendard"}      # the families of the shared example lock: fetched, so locked
SHARED = Path(__file__).resolve().parents[1] / "src" / "shared"


def lock_fonts(root: Path) -> None:
    """The project's fonts lock, as a run that fetched `FACES` leaves it (the shared example lock, which validates)."""
    target = root / ".lapis" / "fonts.lock.json"
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(SHARED / "fonts" / "example.fonts.lock.json", target)


def inventory(path: Path, *families: str, system: tuple[str, ...] = ()) -> Path:
    """A lazuli database holding only `local_font` rows: `families` as installed by the owner, `system` ones as the OS's."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE local_font (id INTEGER PRIMARY KEY, path TEXT, family TEXT, names_i18n_json TEXT, origin TEXT)")
    rows = [(f"/fonts/{name}.otf", name, None, "user") for name in families] + [(f"/sys/{name}.ttc", name, None, "system") for name in system]
    conn.executemany("INSERT INTO local_font (path, family, names_i18n_json, origin) VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()
    return path


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


def _runs(number: int, fonts: dict[str, str]) -> list[dict]:
    """The text runs of `rough_html(number)` as `render check` records them: the heading and the first paragraph, each with the
    family that painted it."""
    def run(index: int, text: str, role: str, family: str) -> dict:
        return {"id": f"b{index}-t0", "box": f"b{index}", "text": text, "chars": len(text.replace(" ", "")), "type_role": role,
                "font": {"requested": family, "rendered": family, "fallback": False, "synthetic": "none"}}
    return [run(1, f"Kiln {number}", "heading", fonts["headline"]), run(2, "Text 0", "body", fonts["body"])]


def write_render(root: Path, task: str, candidate: str, stance: str, number: int, fresh: float | None = None,
                 fonts: dict[str, str] | None = None) -> None:
    """The narrow extract of a rough with its two screenshots, newer than the rough's markup. `fonts` is the family that
    painted each role (`FACES` when left out)."""
    stem = f"{task}-{candidate}.narrow"
    extract = root / ".lapis" / "renders" / f"{stem}.json"
    views = []
    for width, size in ((1440, (288, 180)), (390, (78, 169))):
        shot = root / ".lapis" / "renders" / f"{stem}.shots" / f"{width}-light.png"
        paint(shot, size, stance, number)
        views.append({"width": width, "theme": "light", "reduced_motion": False, "browser_chrome": False,
                      "screenshot": shot.relative_to(extract.parent).as_posix(), "boxes": _view_boxes(number, width),
                      "text": _runs(number, fonts or FACES)})
    extract.parent.mkdir(parents=True, exist_ok=True)
    extract.write_text(json.dumps({"version": 1, "source": {"kind": "render", "url": f"http://127.0.0.1/{candidate}/",
                                                            "task": f"{task}-{candidate}"}, "viewports": views}), encoding="utf-8")
    rough = root / ".lapis" / "diverge" / task / candidate / "index.html"
    later = (rough.stat().st_mtime if fresh is None else fresh) + 5
    for file in (extract, *extract.parent.joinpath(f"{stem}.shots").iterdir()):
        os.utime(file, (later, later))


def brief_for(root: Path, task: str, **changes) -> dict:
    """The shared rough brief: every core object may open the page, and each has the scene it plays later. It requires motion
    when the owner's words ask for it, as the contract reads them, and then says what moves."""
    from lapis_design import rough_carries

    moves = ({"motion": "required", "motion_moves": "the headline's letters keep shifting weight, and the band under it scrolls"}
             if rough_carries.motion_asked(root, task, {"LAPIS_UNATTENDED": "1"}) else {"motion": "none"})
    rows = [{"id": item["id"], "first_view": "allowed", "later": f"{item['label']} comes back in its own scene below"}
            for item in direction.items(root, task, {"LAPIS_UNATTENDED": "1"}) if item["kind"] == "O"]
    found = {"version": 0, "opening": {"job": "say who the kiln is, show the one decisive object, and offer the booking",
                                       "carries": ["identity", "decisive-object", "primary-action"]},
             "objects": rows,
             "key_copy": [{"slot": "headline", "text": "Twenty-four pieces from this firing"},
                          {"slot": "cta", "text": "Reserve a piece"}],
             "phone": {"composition": "the headline, the one reserve button, and a cropped piece; the object follows the copy"},
             **moves, "resolved": []}
    return {**found, **changes}


def write_brief(root: Path, task: str, **changes) -> None:
    """The shared brief, and the contract check that has to pass on it before the roughs are made."""
    path = diverge.brief_path(root, task)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(brief_for(root, task, **changes), sort_keys=False), encoding="utf-8")
    diverge.contract(root, task)


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
                        "medium": "css-drawing", "first_view_share": 0.3 if not objects else 0,
                        "representation": f"{item['label']} shown as {family}, with a control to try it",
                        "later": f"{item['label']} comes back in its own scene below the first view"})
    _, oklch, area = STANCES[standing["color"]["item"]]
    color = [{"name": "field", "role": "field", "oklch": oklch, "area": area},
             {"name": "identity", "role": "identity", "oklch": SIGNAL[1], "area": SIGNAL[2]}]
    found = {"version": 0, "id": candidate, "brief_sha256": diverge.brief_digest(root, task) or "0" * 12,
             "direction": standing["direction"]["item"],
             "draws": sorted((r["id"] for r in standing.values()), key=lambda d: int(d[1:])),
             "hierarchy": standing["hierarchy"]["item"], "objects": objects,
             "color": color, "type": {role: {"family": family} for role, family in FACES.items()},
             "style": style_rows(root, task), "takes": takes_for(root, task, standing["direction"]["item"]),
             "signature": [], "made_in": "subagent"}
    return {**found, **changes}


def style_rows(root: Path, task: str) -> list[dict]:
    """A row for each style item the owner answered and kit item they kept: the rough's heading carries it, in both captures."""
    from lapis_design import rough_carries

    return [{"id": item["id"], "selector": "h1", "does": f"the heading carries {item['label']}", "shown": [1440, 390]}
            for item in rough_carries.style_items(root, task, {"LAPIS_UNATTENDED": "1"})]


def takes_for(root: Path, task: str, letter: str) -> list[str]:
    """The take ids a rough of direction `letter` puts on its page: the digest's takes of that direction's references."""
    from lapis_design import reference_digest

    digest = reference_digest.effective(root, task)
    if digest is None:
        return []
    return [i["id"] for r in digest["references"] if r["direction"] == letter for i in r["take"]]


def signature(candidate: str) -> list[dict]:
    """One signature element a rough adds in its card: what the owner decides at the second turn."""
    return [{"id": "G1", "element": f"mark of {candidate}", "carries": f"what {candidate} shows first: the next free piece"}]


def write_motion(root: Path, task: str, candidate: str, moving: bool = True) -> None:
    """The capture `render motion` leaves for a rough: per width a settled and a reduced-motion frame of the one scroll position;
    they differ in a band when the rough `moving`, and are the same frame when it is still."""
    name = f"{task}-{candidate}"
    folder = root / ".lapis" / "renders" / f"{name}.motion"
    folder.mkdir(parents=True, exist_ok=True)
    blocks = []
    for width, size in ((1440, (288, 180)), (390, (78, 169))):
        rows = []
        for kind in ("settled", "reduced"):
            image = Image.new("RGB", size, (30, 30, 40))
            if moving and kind == "settled":
                ImageDraw.Draw(image).rectangle((0, size[1] // 3, size[0], size[1] // 2), fill=(240, 240, 90))
            file = folder / f"en-{width}-{kind}-01.png"
            image.save(file)
            rows.append({"kind": kind, "width": width, "scroll_y": 0, "path": file.relative_to(root).as_posix(), "sha256": "0" * 64})
        blocks.append({"width": width, "document_sha256": "0" * 64, "scroll_height": size[1], "scenes": [], "recordings": rows})
    manifest = root / ".lapis" / "renders" / f"{name}.motion.json"
    manifest.write_text(json.dumps({"version": 1, "task": name, "source": {"url": f"http://127.0.0.1/{candidate}/"}, "meta": {},
                                    "locales": [{"lang": "en", "widths": blocks}]}), encoding="utf-8")
    rough = root / ".lapis" / "diverge" / task / candidate / "index.html"
    later = rough.stat().st_mtime + 5
    for file in (manifest, *folder.iterdir()):
        os.utime(file, (later, later))


def write_rough(root: Path, task: str, candidate: str, number: int | None = None, **changes) -> None:
    """The rough, its card, and its render for `candidate`, as an agent leaves them."""
    number = int(candidate[1:]) if number is None else number
    folder = root / ".lapis" / "diverge" / task / candidate
    folder.mkdir(parents=True, exist_ok=True)
    if not diverge.brief_path(root, task).is_file():
        write_brief(root, task)
    (folder / "index.html").write_text(rough_html(number), encoding="utf-8")
    found = card_for(root, task, candidate, **changes)
    (folder / "card.yaml").write_text(yaml.safe_dump(found, sort_keys=False), encoding="utf-8")
    stance = diverge.effective(diverge.draw_records(root, task))[candidate]["color"]["item"]
    write_render(root, task, candidate, stance, number)
    if (diverge.brief(root, task) or {}).get("motion") == "required":
        write_motion(root, task, candidate)


def complete(root: Path, task: str, k: int = 3) -> None:
    """The whole of `diverge` for `task`: draw, make each rough, check, and seal."""
    import tempfile

    env = {**os.environ, "LAZULI_DB": str(inventory(Path(tempfile.mkdtemp(prefix="inventory-")) / "lazuli.db", *FACES.values()))}
    diverge.start(root, task, k, entropy="fixture")
    for candidate in diverge.candidate_ids(root, task):
        write_rough(root, task, candidate)
    found = diverge.check(root, task, env)
    assert not found["problems"], found["problems"]
    diverge.seal(root, task, env)
