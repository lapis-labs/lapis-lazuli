"""`diverge`: rough first views that differ in the core objects' representation and in color allocation.

Between the first and the second turn of the direction conversation (`direction.py`) a create run makes K rough first
views (`start`, three by default; two to four), each on a different reference direction of the references record
(`references.directions`). The CLI owns the randomness, so the agent cannot pick: `start` writes `seed.json` (the task's
hash and OS entropy, recorded) and appends the draws to `draws.jsonl`, each `{id, candidate, slot, pool, item, reason,
prev}` in a hash chain, before any card exists. Candidate *i* gets reference direction *i*, for each open core object a
representation family drawn without replacement across candidates (first from the object's options of the direction
conversation, narrowed or all, then from the pool of its kind in `shared/diverge/pools.yaml`), and one color allocation
stance drawn without replacement. `resample` replaces one draw, twice per candidate at most, each with its reason;
`variant` adds a rough the owner asked for (`reason: owner`).

The agent writes each rough as `.lapis/diverge/<task>/C<n>/index.html` with its card `card.yaml`
(`shared/diverge/card.schema.yaml`) and renders it narrow (`lapis-design render check <index.html> --task <task>-C<n>
--width 390 --width 1440`). `check` reads the cards against the draws and the renders, then writes `fingerprints.json`,
`distances.json`, and `contact.png`; `seal` records the digests of cards, roughs, captures, and draws in `seal.json`,
and `next` names `diverge` until it exists. Everything the CLI writes is under `.lapis/state/diverge/<task>/`, a
folder only `lapis-design` writes (`order.CLI_OWNED`).

The distance between two roughs is `0.55·d_struct + 0.20·d_mass + 0.25·d_repr` (weights in the pools file, calibrated over the E1b
roughs against the owner's verdicts). `d_struct` is the IoU distance of the first view's occupancy by text, media, and control boxes on a
12x8 grid at 1440 and a 4x10 grid at 390, and whether the markup structure (`alternatives.signature`) is equal;
`d_mass` is the mean absolute difference of the field's lightness and chroma, the share of pixels with chroma of 0.12 or
more, the share of dark pixels, the media box share, and the line-ink share; `d_repr` is the share of open core objects
whose declared family differs. Only a pair with the same markup structure and a mass distance under the pools'
`reject_mass_below` is refused, as differing in order or finish only. Every other number is reported, never gated, and
is a fact on the contact sheet, not a quality score.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml

from lapis_design import references, requirements, shared_dir

STEP = "diverge"
MIN_K, MAX_K = 2, 4                    # roughs a `start` makes
MAX_TOTAL = 6                          # roughs of a task, owner-requested variants included
RESAMPLES = 2                          # draws an agent may replace per candidate
VIEWS = {1440: (1440, 900), 390: (390, 844)}     # the first view at each width
GRIDS = {1440: (12, 8), 390: (4, 10)}            # columns and rows of the occupancy grid
KINDS = {"text": {"heading", "text", "list"}, "media": {"media", "icon"}, "control": {"button", "input", "link", "nav"}}
OCCUPIED = 0.15                        # the share of a grid cell a kind of box must cover to occupy it
DARK, CHROMA = 0.35, 0.12              # lightness under which a pixel is dark, chroma from which it is vivid
MASS_RASTER = (720, 450)               # the first view as raster, for the mass shares
LINE_RUN, LINE_THICK = 35, 4           # a line is a run of this many pixels no thicker than this, on that raster
CHROMA_SPAN = 0.4                      # the chroma that counts as the whole range in the mass distance


class DivergeError(ValueError):
    """A `diverge` command cannot go on: the message says what to do."""


def folder(root: Path, task: str) -> Path:
    """Where the agent's roughs and cards live."""
    return root / ".lapis" / "diverge" / task


def state_dir(root: Path, task: str) -> Path:
    """Where the CLI keeps the seed, draws, fingerprints, distances, contact sheet, and seal."""
    return root / ".lapis" / "state" / "diverge" / task


def _rel(root: Path, file: Path) -> str:
    return file.relative_to(root).as_posix()


def extract_path(root: Path, task: str, candidate: str) -> Path:
    """The narrow render extract of a rough, as `render check --task <task>-<candidate> --width ...` writes it."""
    return root / ".lapis" / "renders" / f"{task}-{candidate}.narrow.json"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest(file: Path) -> str | None:
    try:
        return _sha(file.read_bytes())
    except OSError:
        return None


def _json(file: Path) -> Any:
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(file: Path, text: str) -> None:
    requirements.write_atomic(file, text)


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------- what the files say (read by `direction.py` too)

def seed(root: Path, task: str) -> dict[str, Any] | None:
    found = _json(state_dir(root, task) / "seed.json")
    return found if isinstance(found, dict) and isinstance(found.get("entropy"), str) else None


def sealed(root: Path, task: str) -> dict[str, Any] | None:
    """`seal.json` of `task`, or None while the set is not sealed."""
    found = _json(state_dir(root, task) / "seal.json")
    return found if isinstance(found, dict) and isinstance(found.get("candidates"), dict) else None


def draw_records(root: Path, task: str) -> list[dict[str, Any]]:
    """The lines of `draws.jsonl` in order; a line that is no mapping is left out (`chain_problem` reports it)."""
    try:
        lines = (state_dir(root, task) / "draws.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    found = []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            found.append(item)
    return found


def candidate_ids(root: Path, task: str) -> list[str]:
    """The candidates the draws gave, in the order they were first drawn."""
    return list(dict.fromkeys(d["candidate"] for d in draw_records(root, task) if isinstance(d.get("candidate"), str)))


def variant_floor(root: Path, task: str) -> int:
    """How many `Pick:` lines the answers held when the latest owner-requested variant was added, or -1 when there is
    none: a pick counts for the second turn only when it comes after that many."""
    seen = [d.get("picks_seen") for d in draw_records(root, task) if d.get("variant")]
    return max([n for n in seen if isinstance(n, int)], default=-1)


def card(root: Path, task: str, candidate: str) -> dict[str, Any] | None:
    """The card of `candidate` as written, or None when it is missing or not a mapping."""
    try:
        found = yaml.safe_load((folder(root, task) / candidate / "card.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return found if isinstance(found, dict) else None


def effective(records: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    """The draw each candidate stands on, by slot: the latest of a slot, a resample replacing the one before."""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for rec in records:
        if isinstance(rec.get("candidate"), str) and isinstance(rec.get("slot"), str):
            out.setdefault(rec["candidate"], {})[rec["slot"]] = rec
    return out


# ---------------------------------------------------------------- the pools and the draws

@lru_cache(maxsize=16)
def _load(path: str, mtime_ns: int) -> Any:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def shared_yaml(name: str) -> Any:
    """A contract under `shared/`, read once for as long as the file is unchanged."""
    file = shared_dir() / name
    return _load(str(file), file.stat().st_mtime_ns)


def pools() -> dict[str, Any]:
    return shared_yaml("diverge/pools.yaml")


def _line(rec: Mapping[str, Any]) -> str:
    return json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _rng(entropy: str, task: str, label: str) -> random.Random:
    return random.Random(int(_sha(f"{entropy}|{_sha(task.encode())}|{label}".encode()), 16))


def chain_problem(root: Path, task: str) -> str | None:
    """Why `draws.jsonl` is not the chain `start` wrote from the seed, or None when it is."""
    found = seed(root, task)
    if found is None:
        return "seed.json is missing or unreadable"
    try:
        lines = (state_dir(root, task) / "draws.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return "draws.jsonl is missing"
    prev = _digest(state_dir(root, task) / "seed.json")
    for n, line in enumerate(lines, start=1):
        try:
            rec = json.loads(line)
        except ValueError:
            return f"draws.jsonl line {n} is not JSON"
        if not isinstance(rec, dict) or rec.get("id") != f"d{n}":
            return f"draws.jsonl line {n} is not draw d{n}"
        if rec.get("prev") != prev or _line(rec) != line:
            return f"draw d{n} does not follow draw d{n - 1} in the hash chain, so the draws were edited"
        prev = _sha(line.encode("utf-8"))
    return None


def _append(root: Path, task: str, new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add `new` draws to the chain; each gets its id and `prev`. Returns them as written."""
    old = draw_records(root, task)
    prev = _sha(_line(old[-1]).encode("utf-8")) if old else _digest(state_dir(root, task) / "seed.json")
    written = []
    for rec in new:
        rec = {**rec, "id": f"d{len(old) + len(written) + 1}", "prev": prev}
        prev = _sha(_line(rec).encode("utf-8"))
        written.append(rec)
    text = "".join(_line(r) + "\n" for r in [*old, *written])
    _write(state_dir(root, task) / "draws.jsonl", text)
    return written


def _objects(root: Path, task: str, env: Mapping[str, str]) -> list[dict[str, Any]]:
    """The core objects of the direction conversation as `diverge` treats them: `{"id", "kind", "label", "options",
    "fixed"}`, where `fixed` is the option id the owner decided (no draw), else None, and `options` the options the owner
    left to explore (every option, the narrowed ones, or none when they asked for something `other`)."""
    from lapis_design import direction

    found = []
    for item in direction.items(root, task, env):
        if item["kind"] != "O":
            continue
        choice = item["choice"] or ["all"]
        options = {o["id"]: o for o in item["options"]}
        if len(choice) == 1 and choice[0] in options:
            found.append({"id": item["id"], "kind": item["object_kind"], "label": item["label"], "fixed": choice[0],
                          "options": [options[choice[0]]]})
        else:
            explore = (list(options.values()) if choice == ["all"] else [] if choice == ["other"]
                       else [options[c] for c in choice if c in options])
            found.append({"id": item["id"], "kind": item["object_kind"], "label": item["label"], "fixed": None,
                          "options": explore})
    return found


def _deck(obj: dict[str, Any], rng: random.Random) -> list[dict[str, Any]]:
    """The families a rough may take for `obj`: the options the owner left open first, in a drawn order, then the
    families of the object's kind that no option names, in a drawn order. `{"family", "option", "pool"}` each."""
    seen: dict[str, dict[str, Any]] = {}
    options = list(obj["options"])
    rng.shuffle(options)
    for option in options:
        seen.setdefault(option["family"], {"family": option["family"], "option": option["id"], "pool": f"options:{obj['id']}"})
    rest = [f["id"] for f in pools()["representation"][obj["kind"]]["families"] if f["id"] not in seen]
    rng.shuffle(rest)
    for family in rest:
        seen[family] = {"family": family, "option": None, "pool": f"representation.{obj['kind']}"}
    return list(seen.values())


def _stances(rng: random.Random) -> list[str]:
    deck = [e["id"] for e in pools()["color_allocation"]]
    rng.shuffle(deck)
    return deck


def _draws_for(root: Path, task: str, entropy: str, candidate: str, number: int, letters: list[str],
               objects: list[dict[str, Any]], taken: Mapping[str, list[Any]], reason: str, extra: Mapping[str, Any]
               ) -> list[dict[str, Any]]:
    """The draws of candidate number `number` (0-based): its direction, each open object's family, its color stance.
    `taken` holds what the other candidates already stand on, by slot, so that nothing is drawn twice while a fresh item
    is left."""
    def pick(slot: str, deck: list[Any], key=lambda x: x) -> Any:
        used = taken.setdefault(slot, [])
        chosen = min(deck, key=lambda d: used.count(key(d)))           # the first item nobody stands on; else the least used
        used.append(key(chosen))
        return chosen

    out = []
    if letters:
        order = list(letters)
        _rng(entropy, task, "direction").shuffle(order)
        letter = pick("direction", order)
        out.append({"candidate": candidate, "slot": "direction", "pool": "directions", "item": letter, "reason": reason, **extra})
    else:
        out.append({"candidate": candidate, "slot": "direction", "pool": "directions", "item": "none",
                    "reason": reason, **extra})
    for obj in objects:
        if obj["fixed"] is not None:
            continue
        chosen = pick(obj["id"], _deck(obj, _rng(entropy, task, f"object:{obj['id']}")), key=lambda d: d["family"])
        out.append({"candidate": candidate, "slot": obj["id"], "pool": chosen["pool"], "item": chosen["family"],
                    "option": chosen["option"], "reason": reason, **extra})
    stance = pick("color", _stances(_rng(entropy, task, "color")))
    out.append({"candidate": candidate, "slot": "color", "pool": "color_allocation", "item": stance, "reason": reason,
                **extra})
    return out


def _held(records: list[dict[str, Any]]) -> dict[str, list[Any]]:
    """What the candidates stand on now, by slot."""
    held: dict[str, list[Any]] = {}
    for slots in effective(records).values():
        for slot, rec in slots.items():
            held.setdefault(slot, []).append(rec["item"])
    return held


def start(root: Path, task: str, k: int = 3, entropy: str | None = None,
          env: Mapping[str, str] = os.environ) -> list[dict[str, Any]]:
    """Draw the roughs of `task`: write the seed and the draws of `k` candidates. `entropy` is for tests; a run gets OS
    entropy, and cannot start again once the seed is written. Returns the draws."""
    from lapis_design import direction

    if seed(root, task) is not None or draw_records(root, task):
        raise DivergeError("the roughs were already drawn for this task; `diverge resample` replaces one draw and "
                           "`diverge variant` adds the rough an owner asked for")
    if not MIN_K <= k <= MAX_K:
        raise DivergeError(f"K is {k}; a run makes {MIN_K} to {MAX_K} roughs (three by default)")
    if owed := direction.owed(root, task, 1, env):
        raise DivergeError(f"the direction conversation is not finished, so there is nothing to draw on: {owed}")
    letters = references.direction_letters(root, task)
    if letters and k > len(letters):
        raise DivergeError(f"K is {k} and the references record defines {len(letters)} directions ({', '.join(letters)}): "
                           "each rough draws on a different one, so add a direction or lower K")
    entropy = entropy or os.urandom(16).hex()
    state = state_dir(root, task)
    _write(state / "seed.json", _dump({"version": 0, "task": task, "task_sha256": _sha(task.encode()),
                                       "entropy": entropy, "k": k}))
    objects = _objects(root, task, env)
    taken: dict[str, list[Any]] = {}
    new: list[dict[str, Any]] = []
    for number in range(k):
        new += _draws_for(root, task, entropy, f"C{number + 1}", number, letters, objects, taken, "start", {})
    return _append(root, task, new)


def resample(root: Path, task: str, candidate: str, slot: str, reason: str,
             env: Mapping[str, str] = os.environ) -> dict[str, Any]:
    """Replace the draw of `slot` of `candidate` with another item nobody stands on yet. At most `RESAMPLES` times per
    candidate, each with its reason. Returns the new draw."""
    found = seed(root, task)
    if found is None:
        raise DivergeError("nothing was drawn yet: run `lapis-design diverge start` first")
    if not reason.strip():
        raise DivergeError("a resample records why: give --reason")
    if len(reason.split()) < 3:
        raise DivergeError("give the reason in a few words: what is wrong with the draw for this subject")
    records = draw_records(root, task)
    standing = effective(records).get(candidate)
    if standing is None:
        raise DivergeError(f"there is no candidate {candidate}: {', '.join(candidate_ids(root, task))}")
    if slot not in standing:
        raise DivergeError(f"{candidate} has no draw for {slot}: {', '.join(standing)}")
    used = sum(1 for r in records if r.get("candidate") == candidate and r.get("replaces"))
    if used >= RESAMPLES:
        raise DivergeError(f"{candidate} was resampled {used} times, and a candidate is resampled at most {RESAMPLES}")
    taken = _held(records)
    label = f"resample:{candidate}:{slot}:{used}"
    rng = _rng(found["entropy"], task, label)
    if slot == "direction":
        letters = references.direction_letters(root, task)
        deck = [{"item": letter} for letter in letters if letter not in taken.get("direction", [])]
        pool, option = "directions", None
    elif slot == "color":
        deck = [{"item": s} for s in _stances(rng) if s not in taken.get("color", [])]
        pool, option = "color_allocation", None
    else:
        obj = next((o for o in _objects(root, task, env) if o["id"] == slot and o["fixed"] is None), None)
        if obj is None:
            raise DivergeError(f"{slot} is no object left to explore: the owner decided it or it is no object")
        deck = [{"item": d["family"], "option": d["option"], "pool": d["pool"]} for d in _deck(obj, rng)
                if d["family"] not in taken.get(slot, [])]
        pool, option = None, None
    if not deck:
        raise DivergeError(f"every item of {slot} is already in use by a candidate: nothing is left to draw")
    if slot in ("direction", "color"):
        rng.shuffle(deck)
    chosen = deck[0]
    rec = {"candidate": candidate, "slot": slot, "pool": chosen.get("pool", pool), "item": chosen["item"],
           "option": chosen.get("option", option), "reason": reason.strip(), "replaces": standing[slot]["id"]}
    if rec["option"] is None:
        del rec["option"]
    return _append(root, task, [rec])[0]


def variant(root: Path, task: str, words: str, env: Mapping[str, str] = os.environ) -> list[dict[str, Any]]:
    """Add the rough an owner asked for (at turn two or on a direction-level reply to the slice): a new candidate with
    fresh draws, `reason: owner`, and the number of `Pick:` lines the answers held, so the pick is asked again."""
    from lapis_design import direction

    found = seed(root, task)
    if found is None:
        raise DivergeError("nothing was drawn yet: run `lapis-design diverge start` first")
    if not words.strip():
        raise DivergeError("a variant records what the owner asked for: give --words")
    records = draw_records(root, task)
    ids = candidate_ids(root, task)
    if len(ids) >= MAX_TOTAL:
        raise DivergeError(f"there are {len(ids)} roughs already, and a task has at most {MAX_TOTAL}")
    candidate = f"C{max(int(c[1:]) for c in ids) + 1}"
    letters = references.direction_letters(root, task)
    taken = _held(records)
    number = len(ids)
    extra = {"variant": True, "picks_seen": direction.pick_count(root, task, env), "owner_words": " ".join(words.split())}
    new = _draws_for(root, task, found["entropy"], candidate, number, letters, _objects(root, task, env), taken, "owner", extra)
    return _append(root, task, new)


# ---------------------------------------------------------------- the cards

def _card_problems(root: Path, task: str, candidate: str, slots: Mapping[str, Mapping[str, Any]],
                   letters: list[str], objects: list[dict[str, Any]]) -> list[str]:
    from jsonschema import Draft202012Validator

    where = f".lapis/diverge/{task}/{candidate}"
    found = card(root, task, candidate)
    if found is None:
        return [f"{where}/card.yaml is missing or is not a mapping"]
    errors = sorted(Draft202012Validator(shared_yaml("diverge/card.schema.yaml")).iter_errors(found), key=lambda e: (len(list(e.absolute_path)), e.message))
    if errors:
        first = errors[0]
        return [f"{where}/card.yaml does not match diverge/card.schema.yaml: "
                f"{'/'.join(map(str, first.absolute_path)) or 'it'}: {first.message[:140]}"]
    problems = []
    if found["id"] != candidate:
        problems.append(f"{where}/card.yaml names itself {found['id']}")
    drawn = slots["direction"]["item"]
    if found["direction"] != drawn:
        problems.append(f"{candidate} draws on direction {drawn} (draw {slots['direction']['id']}) and its card says "
                        f"{found['direction']}")
    elif letters and drawn not in letters:
        problems.append(f"{candidate}'s direction {drawn} is not one of the references record's ({', '.join(letters)})")
    standing = {r["id"] for r in slots.values()}
    if set(found["draws"]) != standing:
        problems.append(f"{candidate}'s card spends the draws {', '.join(sorted(found['draws']))}; the ones it stands on are "
                        f"{', '.join(sorted(standing, key=lambda d: int(d[1:])))}")
    on_card = {o["id"]: o for o in found["objects"]}
    for obj in objects:
        got = on_card.get(obj["id"])
        if got is None:
            problems.append(f"{candidate}'s card shows no representation of {obj['id']} ({obj['label']})")
        elif obj["fixed"] is not None:
            chosen = obj["options"][0]
            if got.get("option") != obj["fixed"] or got["family"] != chosen["family"]:
                problems.append(f"{candidate}: the owner decided {obj['id']} as option {obj['fixed']} ({chosen['family']}); "
                                f"the card shows {got.get('option') or 'no option'} ({got['family']})")
        else:
            draw = slots.get(obj["id"])
            if draw is not None and (got["family"] != draw["item"] or got.get("option") != draw.get("option")):
                problems.append(f"{candidate}: {obj['id']} was drawn as {draw['item']}"
                                f"{' (option ' + draw['option'] + ')' if draw.get('option') else ''}; the card shows "
                                f"{got['family']}{' (option ' + got['option'] + ')' if got.get('option') else ''}")
    for ident in on_card:
        if ident not in {o["id"] for o in objects}:
            problems.append(f"{candidate}'s card shows {ident}, which is no core object of the direction conversation")
    roles = {c["role"] for c in found["color"]}
    if not {"field", "identity"} <= roles:
        problems.append(f"{candidate}'s color has no `field` and `identity` role with an area each")
    ids = [g["id"] for g in found["signature"]]
    if len(ids) != len(set(ids)):
        problems.append(f"{candidate}'s card repeats a signature id")
    if not (folder(root, task) / candidate / "index.html").is_file():
        problems.append(f"{where}/index.html is missing")
    return problems


# ---------------------------------------------------------------- fingerprints, distance, contact sheet

def _viewport(extract: Any, width: int) -> dict[str, Any] | None:
    """The light, full-motion, unframed capture of `width` in a narrow extract."""
    best, score = None, None
    for view in (extract or {}).get("viewports") or ():
        if isinstance(view, dict) and view.get("width") == width and isinstance(view.get("screenshot"), str):
            mark = (view.get("theme") == "light", not view.get("reduced_motion"), not view.get("browser_chrome"))
            if score is None or mark > score:
                best, score = view, mark
    return best


def _raster(boxes: list[Any], size: tuple[int, int], cell: int) -> dict[str, Any]:
    """For each kind of box, a boolean raster of the first view (`size` pixels, `cell` pixels to a raster cell)."""
    import numpy as np

    width, height = size
    masks = {kind: np.zeros((-(-height // cell), -(-width // cell)), dtype=bool) for kind in KINDS}
    for box in boxes:
        rect = box.get("rect") if isinstance(box, dict) else None
        kind = next((k for k, roles in KINDS.items() if box.get("role") in roles), None)
        if kind is None or not isinstance(rect, dict):
            continue
        try:
            x0, y0 = max(0.0, float(rect["x"])), max(0.0, float(rect["y"]))
            x1, y1 = min(float(width), float(rect["x"]) + float(rect["w"])), min(float(height), float(rect["y"]) + float(rect["h"]))
        except (KeyError, TypeError, ValueError):
            continue
        if x1 > x0 and y1 > y0:
            masks[kind][int(y0 // cell):-(-int(y1) // cell), int(x0 // cell):-(-int(x1) // cell)] = True
    return masks


def _occupancy(masks: dict[str, Any], grid: tuple[int, int]) -> dict[str, list[str]]:
    """Per kind, the grid rows as strings of 0 and 1: a cell is occupied when boxes of the kind cover `OCCUPIED` of it."""
    cols, rows = grid
    out = {}
    for kind, mask in masks.items():
        height, width = mask.shape
        lines = []
        for r in range(rows):
            y0, y1 = r * height // rows, max((r + 1) * height // rows, r * height // rows + 1)
            lines.append("".join("1" if mask[y0:y1, c * width // cols:max((c + 1) * width // cols, c * width // cols + 1)].mean() >= OCCUPIED
                                 else "0" for c in range(cols)))
        out[kind] = lines
    return out


def _oklab(rgb: Any) -> Any:
    """OKLab of sRGB values in 0..1, any leading shape."""
    import numpy as np

    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    lms = np.cbrt(linear @ np.array([[0.4122214708, 0.2119034982, 0.0883024619],
                                     [0.5363325363, 0.6806995451, 0.2817188376],
                                     [0.0514459929, 0.1073969566, 0.6299787005]]))
    return lms @ np.array([[0.2104542553, 1.9779984951, 0.0259040371],
                           [0.7936177850, -2.4285922050, 0.7827717662],
                           [-0.0040720468, 0.4505937099, -0.8086757660]])


def _runs(mask: Any, length: int, axis: int) -> Any:
    """The pixels of `mask` that lie in a run of `length` or more along `axis`."""
    import numpy as np

    work = mask if axis == 1 else mask.T
    total = np.concatenate([np.zeros((work.shape[0], 1), dtype=np.int32), np.cumsum(work, axis=1, dtype=np.int32)], axis=1)
    starts = (total[:, length:] - total[:, :-length]) == length if work.shape[1] >= length else np.zeros((work.shape[0], 0), bool)
    marks = np.concatenate([np.zeros((work.shape[0], 1), dtype=np.int32), np.cumsum(starts, axis=1, dtype=np.int32)], axis=1)
    positions = np.arange(work.shape[1])
    lo, hi = np.maximum(0, positions - length + 1), np.minimum(positions, starts.shape[1] - 1)
    covered = (marks[:, hi + 1] - marks[:, lo] > 0) & (hi >= lo)
    return covered if axis == 1 else covered.T


def _mass(shot: Path, scale_to: int, media_share: float) -> dict[str, float]:
    """The shares of the first view that `d_mass` compares, read from its screenshot: the field (the largest 4-bit RGB
    bucket, represented by its median color), the share of vivid pixels, of dark pixels, of media boxes, and of thin
    horizontal or vertical lines."""
    import numpy as np
    from PIL import Image

    with Image.open(shot) as image:
        image = image.convert("RGB")
        scale = image.width / scale_to
        crop = image.crop((0, 0, image.width, min(image.height, round(VIEWS[1440][1] * scale))))
        raster = np.asarray(crop.resize(MASS_RASTER, Image.Resampling.BILINEAR), dtype=np.uint8)
    pixels = raster.reshape(-1, 3)
    keys = (pixels[:, 0] >> 4).astype(np.int32) * 256 + (pixels[:, 1] >> 4).astype(np.int32) * 16 + (pixels[:, 2] >> 4)
    top = np.bincount(keys).argmax()
    field = np.median(pixels[keys == top], axis=0)
    lab = _oklab(raster.astype(np.float64) / 255.0)
    chroma = np.hypot(lab[..., 1], lab[..., 2])
    field_lab = _oklab(field / 255.0)
    ink = np.linalg.norm(lab - field_lab, axis=-1) > 0.10
    lines = (_runs(ink, LINE_RUN, 1) & ~_runs(ink, LINE_THICK, 0)) | (_runs(ink, LINE_RUN, 0) & ~_runs(ink, LINE_THICK, 1))
    return {"field_lightness": round(float(field_lab[0]), 4), "field_chroma": round(float(np.hypot(field_lab[1], field_lab[2])), 4),
            "vivid_share": round(float((chroma >= CHROMA).mean()), 4), "dark_share": round(float((lab[..., 0] < DARK).mean()), 4),
            "media_share": round(media_share, 4), "line_share": round(float(lines.mean()), 4)}


def _structure_digest(root: Path, task: str, candidate: str) -> str | None:
    from lapis_design import alternatives

    try:
        tree, relations = alternatives.signature(folder(root, task) / candidate / "index.html", root)
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return _sha(repr((tree, sorted(map(repr, relations)))).encode("utf-8"))


def _extract_problem(root: Path, task: str, candidate: str) -> str | None:
    """Why the render of `candidate` is not one to measure, or None."""
    path = extract_path(root, task, candidate)
    name = _rel(root, path)
    command = (f"`lapis-design render check .lapis/diverge/{task}/{candidate}/index.html --task {task}-{candidate} "
               "--width 390 --width 1440`")
    extract = _json(path)
    if not isinstance(extract, dict):
        return f"{candidate} has no render extract {name}: run {command}"
    if (extract.get("source") or {}).get("task") != f"{task}-{candidate}":
        return f"{name} is a capture of another task: run {command}"
    rough = folder(root, task) / candidate / "index.html"
    if rough.is_file() and path.stat().st_mtime_ns < rough.stat().st_mtime_ns:
        return f"{name} is older than {candidate}'s index.html: run {command} again"
    for width in VIEWS:
        view = _viewport(extract, width)
        if view is None or not (path.parent / view["screenshot"]).is_file():
            return f"{name} has no screenshot at {width}: run {command}"
    return None


def fingerprint(root: Path, task: str, candidate: str) -> dict[str, Any]:
    """The structure and mass of one rough, read from its narrow render extract and screenshots. Raises DivergeError
    when there is none to read."""
    if problem := _extract_problem(root, task, candidate):
        raise DivergeError(problem)
    path = extract_path(root, task, candidate)
    extract = _json(path)
    grids, mass = {}, {}
    for width, size in VIEWS.items():
        view = _viewport(extract, width)
        cell = 10 if width == 1440 else 5
        masks = _raster(view.get("boxes") or [], size, cell)
        grids[str(width)] = _occupancy(masks, GRIDS[width])
        if width == 1440:
            mass = _mass(path.parent / view["screenshot"], width, float(masks["media"].mean()))
    return {"candidate": candidate, "structure": _structure_digest(root, task, candidate), "grids": grids, "mass": mass}


def _iou_distance(a: list[str], b: list[str]) -> float | None:
    cells_a = {(r, c) for r, row in enumerate(a) for c, ch in enumerate(row) if ch == "1"}
    cells_b = {(r, c) for r, row in enumerate(b) for c, ch in enumerate(row) if ch == "1"}
    union = cells_a | cells_b
    return None if not union else 1.0 - len(cells_a & cells_b) / len(union)


def _grid_distance(a: dict[str, list[str]], b: dict[str, list[str]]) -> float:
    found = [d for kind in KINDS if (d := _iou_distance(a[kind], b[kind])) is not None]
    return sum(found) / len(found) if found else 0.0


def _mass_distance(a: dict[str, float], b: dict[str, float]) -> float:
    parts = [abs(a["field_lightness"] - b["field_lightness"]),
             min(1.0, abs(a["field_chroma"] - b["field_chroma"]) / CHROMA_SPAN)]
    parts += [abs(a[k] - b[k]) for k in ("vivid_share", "dark_share", "media_share", "line_share")]
    return sum(parts) / len(parts)


def distances(fingerprints: Mapping[str, Mapping[str, Any]], families: Mapping[str, Mapping[str, str]]) -> dict[str, Any]:
    """The pairwise distances of the roughs and the pairs refused as order or finish only. `families` is each
    candidate's family by open object."""
    weights = pools()["distance"]
    w, s = weights["weights"], weights["struct"]
    ids = sorted(fingerprints, key=lambda c: int(c[1:]))
    pairs = []
    for n, a in enumerate(ids):
        for b in ids[n + 1:]:
            fa, fb = fingerprints[a], fingerprints[b]
            same = fa["structure"] is not None and fa["structure"] == fb["structure"]
            struct = (s["grid_1440"] * _grid_distance(fa["grids"]["1440"], fb["grids"]["1440"])
                      + s["grid_390"] * _grid_distance(fa["grids"]["390"], fb["grids"]["390"])
                      + s["signature"] * (0.0 if same else 1.0))
            mass = _mass_distance(fa["mass"], fb["mass"])
            slots = sorted(set(families[a]) & set(families[b]))
            repr_ = sum(families[a][o] != families[b][o] for o in slots) / len(slots) if slots else 0.0
            total = w["struct"] * struct + w["mass"] * mass + w["repr"] * repr_
            refused = same and mass < weights["reject_mass_below"]
            pairs.append({"a": a, "b": b, "struct": round(struct, 4), "mass": round(mass, 4), "repr": round(repr_, 4),
                          "total": round(total, 4), "same_structure": same, "refused": refused})
    return {"calibrated": weights["calibrated"], "weights": w, "pairs": pairs,
            "minimum_pair": min((p["total"] for p in pairs), default=None),
            "close": [[p["a"], p["b"]] for p in pairs if weights["minimum_pair"] is not None and p["total"] < weights["minimum_pair"]]}


def _font(size: int):
    from PIL import ImageFont

    return ImageFont.load_default(size=size)


def contact_sheet(root: Path, task: str, labels: Mapping[str, list[str]], out: Path) -> None:
    """Each rough at 1440 (its first view) with its 390 first view as an inset, and its labels under it: the candidate,
    its reference direction, its families, its color stance."""
    from PIL import Image, ImageDraw

    cell_w, shot_w, inset_w, gap = 560, 540, 120, 16
    shot_h = round(shot_w * VIEWS[1440][1] / VIEWS[1440][0])
    inset_h = round(inset_w * VIEWS[390][1] / VIEWS[390][0])
    line_h = 24
    cell_h = shot_h + gap + line_h * 4 + gap
    ids = sorted(labels, key=lambda c: int(c[1:]))
    per_row = 3 if len(ids) > 4 else min(len(ids), 4)
    rows = -(-len(ids) // per_row)
    sheet = Image.new("RGB", (cell_w * per_row + gap, cell_h * rows + gap), (236, 236, 238))
    draw = ImageDraw.Draw(sheet)
    font = _font(18)
    for n, candidate in enumerate(ids):
        x, y = gap + (n % per_row) * cell_w, gap + (n // per_row) * cell_h
        extract = _json(extract_path(root, task, candidate))
        base = extract_path(root, task, candidate).parent
        for width, (size, at) in {1440: ((shot_w, shot_h), (x, y)),
                                  390: ((inset_w, inset_h), (x + shot_w - inset_w - 8, y + shot_h - inset_h - 8))}.items():
            view = _viewport(extract, width)
            with Image.open(base / view["screenshot"]) as image:
                image = image.convert("RGB")
                scale = image.width / width
                crop = image.crop((0, 0, image.width, min(image.height, round(VIEWS[width][1] * scale))))
                shown = crop.resize((size[0], max(1, round(size[0] * crop.height / crop.width))), Image.Resampling.LANCZOS)
                shown = shown.crop((0, 0, size[0], min(shown.height, size[1])))
            if width == 390:
                draw.rectangle((at[0] - 3, at[1] - 3, at[0] + size[0] + 2, at[1] + shown.height + 2), fill=(255, 255, 255))
            sheet.paste(shown, at)
        for index, text in enumerate(labels[candidate]):
            draw.text((x, y + shot_h + gap + index * line_h), text, fill=(30, 30, 34), font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)


# ---------------------------------------------------------------- check and seal

def _candidate_set(root: Path, task: str) -> dict[str, dict[str, dict[str, Any]]]:
    return effective(draw_records(root, task))


def check(root: Path, task: str, env: Mapping[str, str] = os.environ) -> dict[str, Any]:
    """Read the cards against the draws and the renders. `{"problems", "candidates", "distances"}`; when there are no
    problems, `fingerprints.json`, `distances.json`, and `contact.png` are written."""
    problems: list[str] = []
    if (broken := chain_problem(root, task)) is not None:
        return {"problems": [broken, "run `lapis-design diverge start --task " + task + "` to draw"
                             if seed(root, task) is None else "the draws are the CLI's; do not edit them"],
                "candidates": [], "distances": None}
    letters = references.direction_letters(root, task)
    standing = _candidate_set(root, task)
    ids = sorted(standing, key=lambda c: int(c[1:]))
    objects = _objects(root, task, env)
    for candidate in ids:
        problems += _card_problems(root, task, candidate, standing[candidate], letters, objects)
    first = [c for c in ids if not any(r.get("variant") for r in draw_records(root, task) if r.get("candidate") == c)]
    drawn = [standing[c]["direction"]["item"] for c in first]
    if letters and len(set(drawn)) != len(drawn):
        problems.append("the first roughs must draw on different reference directions; their draws repeat one")
    prints, found = {}, False
    for candidate in ids:
        if problem := _extract_problem(root, task, candidate):
            problems.append(problem)
        else:
            prints[candidate] = fingerprint(root, task, candidate)
    families = {c: {slot: rec["item"] for slot, rec in standing[c].items() if slot.startswith("O")} for c in ids}
    report = distances(prints, families) if len(prints) == len(ids) and ids else None
    if report:
        problems += [f"{p['a']} and {p['b']} keep the same structure and differ in color mass by {p['mass']:.2f}: they differ "
                     "in order or finish only, so change the representation or the color allocation of one"
                     for p in report["pairs"] if p["refused"]]
    if not problems and report is not None:
        state = state_dir(root, task)
        _write(state / "fingerprints.json", _dump({"version": 0, "candidates": prints}))
        _write(state / "distances.json", _dump({"version": 0, **report}))
        labels = {}
        for c in ids:
            stance = standing[c]["color"]["item"]
            labels[c] = [f"{c}  direction {standing[c]['direction']['item']}",
                         f"families: {', '.join(families[c].values()) or 'none drawn'}", f"color: {stance}",
                         "owner variant" if any(r.get("variant") for r in draw_records(root, task) if r.get("candidate") == c)
                         else ""]
        contact_sheet(root, task, labels, state / "contact.png")
    return {"problems": problems, "candidates": ids, "distances": report}


def _row(root: Path, task: str, candidate: str) -> dict[str, Any]:
    """What `seal` records of one rough, and what `drift` compares: the digests of its card, its markup, and its captures."""
    base = folder(root, task) / candidate
    extract = _json(extract_path(root, task, candidate))
    shots = {}
    for width in VIEWS:
        view = _viewport(extract, width)
        if view:
            shot = extract_path(root, task, candidate).parent / view["screenshot"]
            shots[str(width)] = {"path": _rel(root, shot), "sha256": _digest(shot)}
    return {"card": {"path": _rel(root, base / "card.yaml"), "sha256": _digest(base / "card.yaml")},
            "rough": {"path": _rel(root, base / "index.html"), "sha256": _digest(base / "index.html")},
            "captures": shots}


def seal(root: Path, task: str, env: Mapping[str, str] = os.environ) -> dict[str, Any]:
    """Write `seal.json`: the digests of the cards, roughs, captures, and draws, and of what the CLI measured. Refused
    while `check` has a problem. Sealing again (after an owner-requested variant) keeps the number of direction turns
    the first seal recorded."""
    from lapis_design import direction

    found = check(root, task, env)
    if found["problems"]:
        raise DivergeError("the roughs cannot be sealed: " + "; ".join(found["problems"][:3])
                           + (f"; and {len(found['problems']) - 3} more" if len(found["problems"]) > 3 else ""))
    state = state_dir(root, task)
    before = sealed(root, task)
    record = {"version": 0, "task": task,
              "d1_turns": before["d1_turns"] if before and isinstance(before.get("d1_turns"), int) else direction.turns(root, task),
              "draws_sha256": _digest(state / "draws.jsonl"), "fingerprints_sha256": _digest(state / "fingerprints.json"),
              "distances_sha256": _digest(state / "distances.json"),
              "contact": {"path": _rel(root, state / "contact.png"), "sha256": _digest(state / "contact.png")},
              "candidates": {c: {**_row(root, task, c), "direction": _candidate_set(root, task)[c]["direction"]["item"]}
                             for c in found["candidates"]}}
    _write(state / "seal.json", _dump(record))
    return record


def drift(root: Path, task: str) -> list[str]:
    """What changed after the seal: each rough whose card, markup, or captures no longer hash as sealed, and each draw
    that is not the sealed set's. Empty while nothing sealed or nothing changed."""
    record = sealed(root, task)
    if record is None:
        return []
    found = []
    for candidate, row in sorted(record["candidates"].items()):
        now = _row(root, task, candidate)
        changed = [name for name in ("card", "rough") if now[name]["sha256"] != (row.get(name) or {}).get("sha256")]
        if now["captures"] != row.get("captures"):
            changed.append("captures")
        if changed:
            found.append(f"{candidate}: {', '.join(changed)} changed after the seal")
    if _digest(state_dir(root, task) / "draws.jsonl") != record.get("draws_sha256"):
        found.append("the draws changed after the seal")
    return found


def owner_lines(root: Path, task: str) -> list[str]:
    """The lines the owner block shows about the roughs: what was sealed, and what changed after the seal. Empty when
    there is no seal."""
    record = sealed(root, task)
    if record is None:
        return []
    lines = [f"- Rough first views sealed: {', '.join(sorted(record['candidates'], key=lambda c: int(c[1:])))} "
             f"(contact sheet {record['contact']['path']})"]
    return lines + [f"- Rough {line}" for line in drift(root, task)]


# ---------------------------------------------------------------- what is owed

def owed(root: Path, task: str, env: Mapping[str, str] = os.environ) -> str | None:
    """What the `diverge` step says while the roughs are not drawn, made, and sealed, or None when they are: the draws
    exist, and the seal holds every candidate and these draws."""
    command = f"lapis-design diverge start --task {task}"
    if seed(root, task) is None:
        return (f"The direction conversation is done, so make the rough first views: run `{command}` (three roughs; `--k` 2 to 4). "
                "The CLI draws, for each rough, a different reference direction of the references record, a representation "
                "family for each open core object, and a color allocation stance, and records the draws; you cannot choose "
                f"them (`resample` replaces one, twice per rough at most, with its reason). {_how(task)}")
    record = sealed(root, task)
    ids = candidate_ids(root, task)
    if record is None or set(record["candidates"]) != set(ids) or record.get("draws_sha256") != _digest(state_dir(root, task) / "draws.jsonl"):
        missing = [c for c in ids if not (folder(root, task) / c / "card.yaml").is_file() or not (folder(root, task) / c / "index.html").is_file()
                   or not extract_path(root, task, c).is_file()]
        left = f" Still missing a card, a rough, or a render: {', '.join(missing)}." if missing else ""
        what = "Seal the set again" if record else "Seal the set"
        return (f"The rough first views {', '.join(ids)} are drawn but not sealed.{left} {_how(task)} Then run "
                f"`lapis-design diverge check --task {task}` (it reads the cards against the draws and the renders and writes "
                f"the contact sheet) and `lapis-design diverge seal --task {task}`. {what} before you ask the owner to pick.")
    return None


def _how(task: str) -> str:
    return (f"Make each rough in a fresh context where the harness has one, seeing only the brief record, the direction "
            f"answers, its own draws, and its reference direction's captures, never the other roughs: its first view at 1440 "
            f"and 390 as `.lapis/diverge/{task}/C<n>/index.html` with real or clearly synthetic content and the decisive "
            f"medium (diagram, control, image, or motion state) instead of a gray box, and its card `card.yaml` "
            f"(shared/diverge/card.schema.yaml) next to it. Render each: `lapis-design render check "
            f".lapis/diverge/{task}/C<n>/index.html --task {task}-C<n> --width 390 --width 1440`. The roughs differ in how "
            "the core objects are represented and how color is allocated, not in decoration, order, or finish.")


def step(root: Path, task: str, reason: str) -> dict[str, Any]:
    verb = "check" if seed(root, task) is not None else "start"
    return {"id": STEP, "why": reason, "command": f"lapis-design diverge {verb} --task {task}"}


def show(root: Path, task: str, env: Mapping[str, str] = os.environ) -> str:
    """The draws and standing of each rough, as text."""
    found = seed(root, task)
    if found is None:
        return f"No rough was drawn for {task} yet: `lapis-design diverge start --task {task}`."
    standing = _candidate_set(root, task)
    records = draw_records(root, task)
    lines = [f"{task}: {len(standing)} roughs, seed {found['task_sha256'][:8]}"]
    for candidate in sorted(standing, key=lambda c: int(c[1:])):
        slots = standing[candidate]
        used = sum(1 for r in records if r.get("candidate") == candidate and r.get("replaces"))
        mark = " (owner variant)" if any(r.get("variant") for r in records if r.get("candidate") == candidate) else ""
        lines.append(f"{candidate}{mark}: direction {slots['direction']['item']}; " + "; ".join(
            f"{slot} {rec['item']}" for slot, rec in slots.items() if slot != "direction") + f"; resamples {used}/{RESAMPLES}")
    report = _json(state_dir(root, task) / "distances.json")
    if isinstance(report, dict):
        lines += [f"{p['a']}-{p['b']}: total {p['total']:.2f} (struct {p['struct']:.2f}, mass {p['mass']:.2f}, repr {p['repr']:.2f})"
                  for p in report.get("pairs", [])]
        lines += [f"{a}-{b}: below the calibrated minimum pair distance (reported, not gated)" for a, b in report.get("close") or ()]
        lines.append("distances are facts, not a quality score" + ("" if report.get("calibrated") else "; weights not calibrated"))
    record = sealed(root, task)
    lines.append("sealed" if record else "not sealed")
    lines += [f"changed: {line}" for line in drift(root, task)]
    return "\n".join(lines)


def main(argv: list[str] | None = None, prog: str = "lapis-design diverge start") -> int:
    verb = prog.rsplit(" ", 1)[-1]
    ap = argparse.ArgumentParser(prog=prog, allow_abbrev=False, description=__doc__.split("\n")[0])
    ap.add_argument("--task", required=True, help="the task id")
    ap.add_argument("--root", type=Path, default=Path("."), help="the project folder (default: the current one)")
    if verb == "start":
        ap.add_argument("--k", type=int, default=3, help=f"roughs to make, {MIN_K} to {MAX_K} (default 3)")
    if verb == "resample":
        ap.add_argument("--candidate", required=True, help="the rough, for example C2")
        ap.add_argument("--slot", required=True, help="direction, color, or a core object id such as O1")
        ap.add_argument("--reason", required=True, help="why the draw does not fit this subject")
    if verb == "variant":
        ap.add_argument("--words", required=True, help="what the owner asked for, in their words")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    try:
        if verb == "start":
            draws = start(root, args.task, args.k)
            print(show(root, args.task))
            print(f"{len(draws)} draws recorded in {_rel(root, state_dir(root, args.task) / 'draws.jsonl')}")
        elif verb == "resample":
            rec = resample(root, args.task, args.candidate, args.slot, args.reason)
            print(f"{rec['id']}: {rec['candidate']} {rec['slot']} is now {rec['item']} (replaces {rec['replaces']})")
        elif verb == "variant":
            draws = variant(root, args.task, args.words)
            print(f"{draws[0]['candidate']} added for the owner; make it, render it, then check and seal again")
            print(show(root, args.task))
        elif verb == "check":
            found = check(root, args.task)
            for problem in found["problems"]:
                print(f"diverge check: {problem}", file=sys.stderr)
            if found["problems"]:
                return 1
            print(show(root, args.task))
        elif verb == "seal":
            record = seal(root, args.task)
            print(f"sealed {', '.join(record['candidates'])}; contact sheet {record['contact']['path']}")
        else:
            print(show(root, args.task))
    except DivergeError as exc:
        print(f"diverge {verb}: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
