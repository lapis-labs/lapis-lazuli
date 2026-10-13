"""What a rough carries of the owner's declared words: its type, its motion, and its style answers.

`diverge check` used to ask that a rough's records exist and agree. A rough could still ignore every word the owner gave:
system-font stacks where they asked for geometric sans and installed trial faces, no animation where they asked for kinetic
type, and no trace of the styles they answered at the first direction turn. These checks read what the rough renders and
contains, with nothing to rely on but the files the CLI already writes:

- **Type.** The card names a family for the headline and one for the body (`card.type`). The render extract records, per text
  run, the family that painted most of its glyphs (`font.rendered`) and the run's `type_role`; the headline is the `display`
  and `heading` runs, the body the `body` runs, at 1440 and 390. A role whose runs a system default paints (the list and the
  share are `rough_carry.type` in `diverge/pools.yaml`), or whose dominant family is not the card's, is refused. The card's
  family must be installed (the lazuli inventory, `local_font`) or in the project's fonts lock; a card may choose a system
  face only by quoting an owner `[declared]` line that asks for it. When the owner named a typeface or a type class (the
  taste file, a `[declared]` row, an answered style), the card has to say how its type answers it. Whether the type fits the
  owner's words stays theirs to judge.
- **Motion.** The shared brief says `motion: required` or `none`. `contract` refuses `none` while the owner's words ask for
  motion; `check` then refuses a rough whose `render motion` capture shows no change between its settled and its
  reduced-motion frames.
- **Style.** For each style item the owner answered at the first turn (`S<n>`, and each kit item `K<n>` they kept) the card
  names a selector, what the element does, and which capture shows it. `check` refuses an item left out and a selector that
  matches no element of the rough's markup; for a width the card says shows it, the element's text has to be in that
  render.

Every term list and number is in the pools file. The matching is lexical and a lead, never a verdict on taste.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from functools import cached_property, lru_cache
from pathlib import Path
from typing import Any, Mapping

from lapis_design import diverge, direction, motion, requirements, rough_selectors, system_fonts, taste, waiting

HEADLINE_ROLES = ("display", "heading")
BODY_ROLES = ("body",)
ROLES = {"headline": HEADLINE_ROLES, "body": BODY_ROLES}
MOTION_TASTE = ("likes", "feel", "fixed", "references")      # what the owner wants; `dislikes` and `avoid` are the opposite
DASH = re.compile(r"\s[—–]\s|\s-\s")
QUESTION = re.compile(r"^Q\d+\b[^?]*\?\s*(?:[-–—]\s*)?(?P<answer>.+)$", re.DOTALL)


def rules() -> dict[str, Any]:
    return diverge.pools()["rough_carry"]


def _norm(name: str | None) -> str:
    return re.sub(r"[\W_]+", "", name.casefold()) if name else ""


def _squash(text: str) -> str:
    return " ".join(text.split()).casefold()


@lru_cache(maxsize=32)
def _terms(terms: tuple[str, ...]) -> re.Pattern[str]:
    parts = []
    for term in terms:
        escaped = re.escape(" ".join(term.split()))
        if term.isascii():
            parts.append(r"(?<![a-z0-9])" + escaped + (r"(?![a-z0-9])" if len(term) < 4 else ""))
        else:
            parts.append(escaped)
    return re.compile("|".join(parts), re.IGNORECASE)


def _find(text: str, terms: list[str]) -> str | None:
    """The first term of `terms` in `text`, as written there, or None."""
    found = _terms(tuple(terms)).search(" ".join(text.split()))
    return found.group(0) if found else None


def _excerpt(text: str, term: str, width: int = 70) -> str:
    flat = " ".join(text.split())
    at = flat.casefold().find(term.casefold())
    start = max(0, at - width // 2)
    cut = flat[start:start + width + len(term)]
    return ("…" if start else "") + cut + ("…" if start + len(cut) < len(flat) else "")


# ---------------------------------------------------------------- the owner's words

def declared_words(root: Path, task: str) -> list[tuple[str, str]]:
    """`(where, the owner's words)` of each `[declared]` item of the brief record. A direction answer
    (`S1 name: choice — "<words>"`) gives the words after the dash, since the id, name, and choice are the run's; a
    brief answer (`Q1 <question>? - <words>`) gives the words after the question."""
    try:
        text = waiting.answers_path(root, task).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found = []
    for item, _, body in requirements._declared_items(text):
        where = f"{waiting.answers_path(Path('.'), task).as_posix()}:{item['lines'][0]}"
        if direction._answer(body) or direction._PICK.match(body):
            parts = DASH.split(body, 1)
            words = parts[1] if len(parts) == 2 else ""
        elif asked := QUESTION.match(body):
            words = asked.group("answer")
        else:
            words = body
        if words.strip():
            found.append((where, words.strip()))
    return found


def taste_words(root: Path, sections: tuple[str, ...] | None = None) -> list[tuple[str, str]]:
    """`(where, line)` of the taste file's lines in `sections` (every section by default)."""
    data = taste.read(root)
    return [(f"{taste.path(Path('.')).as_posix()} ({name})", line) for name in sections or taste.SECTIONS
            for line in data.get(name) or ()]


def _answered(root: Path, task: str, env: Mapping[str, str]) -> list[dict[str, Any]]:
    """The direction items that have an answer standing."""
    return [i for i in direction.items(root, task, env) if i["state"] != "open"]


def style_items(root: Path, task: str, env: Mapping[str, str]) -> list[dict[str, Any]]:
    """The style items a card has to map: each style `S<n>` the owner answered at turn one and each kit item `K<n>` they
    kept (or took by default as kept). A dropped kit item is none of them."""
    return [i for i in _answered(root, task, env)
            if i["candidate"] is None and (i["kind"] == "S" or (i["kind"] == "K" and i["choice"] == ["keep"]))]


def _chosen_text(item: dict[str, Any]) -> str:
    options = {o["id"]: o["text"] for o in item["options"]}
    return " ".join(options.get(c, "") for c in item["choice"] or ())


def motion_asked(root: Path, task: str, env: Mapping[str, str]) -> list[str]:
    """What in the owner's words asks for motion, as `where: "excerpt"`: a `[declared]` row, the taste file's wants, a style
    they answered, a kit item they kept, a signature element they took."""
    terms = rules()["motion"]["words"]
    found = []
    candidates = [*declared_words(root, task), *taste_words(root, MOTION_TASTE)]
    for item in _answered(root, task, env):
        if item["candidate"] is not None:
            continue
        if item["kind"] == "S" or (item["kind"] == "K" and item["choice"] == ["keep"]):
            candidates.append((f"direction item {item['id']}", item["label"]))
        elif item["kind"] == "G":
            candidates.append((f"signature item {item['id']}", f"{item['label']} {_chosen_text(item)}"))
    for where, words in candidates:
        if term := _find(words, terms):
            found.append(f'{where}: "{_excerpt(words, term)}"')
    return found


# ---------------------------------------------------------------- what the machine has

class Inventory:
    """The families lazuli's inventory (`local_font`) lists, read once; or why it cannot be read."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.families: dict[str, str] = {}             # normalized name -> name
        self.owned: list[str] = []                     # families that came from the owner (user, adobe-sync), not the system
        self.problem: str | None = None
        if not path.is_file():
            self.problem = f"lazuli has no font inventory at {path}"
            return
        try:
            conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                rows = conn.execute("SELECT family, names_i18n_json, origin FROM local_font "
                                    "WHERE family IS NOT NULL AND family NOT LIKE '.%'").fetchall()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            self.problem = f"lazuli's font inventory {path} cannot be read ({exc})"
            return
        owned: set[str] = set()
        for family, names, origin in rows:
            try:
                translated = [str(v) for v in json.loads(names or "{}").values()]
            except (ValueError, AttributeError):
                translated = []
            for name in (family, *translated):
                self.families.setdefault(_norm(name), name)
            if origin != "system":
                owned.add(family)
        self.owned = sorted(owned)

    def has(self, family: str) -> bool:
        return _norm(family) in self.families


def _lock_families(root: Path) -> dict[str, str]:
    try:
        found = json.loads((root / ".lapis" / "fonts.lock.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {_norm(f["family"]): f["family"] for f in (found.get("fonts") if isinstance(found, dict) else None) or ()
            if isinstance(f, dict) and isinstance(f.get("family"), str)}


def is_system(name: str) -> bool:
    """Whether `name` is a family a browser or an OS picks when nobody chose one: a generic keyword, a dotted system
    name, or one of `rough_carry.type.system_defaults`."""
    defaults = {_norm(n) for n in rules()["type"]["system_defaults"]}
    return name.strip().startswith(".") or system_fonts.is_generic(name) or _norm(name) in defaults


# ---------------------------------------------------------------- type

def _role_runs(extract: Any, roles: tuple[str, ...]) -> list[dict[str, Any]]:
    runs = []
    for width in diverge.VIEWS:
        view = diverge._viewport(extract, width)
        runs += [r for r in (view or {}).get("text") or ()
                 if isinstance(r, dict) and r.get("type_role") in roles and isinstance(r.get("font"), dict)]
    return runs


def rendered_families(extract: Any, role: str) -> Counter[str]:
    """The characters of `role`'s runs (headline: display and heading; body: body) by the family that painted them, at 1440
    and 390, as the render extract recorded: `font.rendered`, the family that painted the most glyphs of a run."""
    found: Counter[str] = Counter()
    for run in _role_runs(extract, ROLES[role]):
        name = run["font"].get("rendered") or run["font"].get("requested")
        if isinstance(name, str) and name:
            found[name] += int(run.get("chars") or len(run.get("text") or "")) or 1
    return found


def _percent(share: float) -> str:
    return f"{round(share * 100)}%"


class Carry:
    """The owner's words and the machine's facts a card is read against; each is read once and only when a check needs it."""

    def __init__(self, root: Path, task: str, env: Mapping[str, str]) -> None:
        self.root, self.task, self.env = root, task, env

    @cached_property
    def brief(self) -> dict[str, Any]:
        return diverge.brief(self.root, self.task) or {}

    @cached_property
    def inventory(self) -> Inventory:
        from lazuli import paths

        named = self.env.get("LAZULI_DB")
        return Inventory(Path(named).expanduser() if named else paths.db_path())

    @cached_property
    def lock(self) -> dict[str, str]:
        return _lock_families(self.root)

    @cached_property
    def declared(self) -> list[tuple[str, str]]:
        return declared_words(self.root, self.task)

    @cached_property
    def style(self) -> list[dict[str, Any]]:
        return style_items(self.root, self.task, self.env)

    @cached_property
    def type_named(self) -> list[str]:
        """What in the owner's words names a typeface or a type class, as `where: "excerpt"`."""
        terms = rules()["type"]["words"]
        texts = [*self.declared, *taste_words(self.root)]
        texts += [(f"direction item {i['id']}", i["label"]) for i in self.style]
        found = []
        for where, words in texts:
            if term := _find(words, terms):
                found.append(f'{where}: "{_excerpt(words, term)}"')
            elif (inventory := self.inventory).problem is None:
                flat = _squash(words)
                if name := next((n for n in inventory.owned if len(n) >= 4 and
                                 re.search(rf"(?<![\w]){re.escape(n.casefold())}(?![\w])", flat)), None):
                    found.append(f'{where}: "{_excerpt(words, name)}"')
        return found

    @property
    def motion_required(self) -> bool:
        return self.brief.get("motion") == "required"

    # -- type

    def asks_for_system(self, quote: str) -> str | None:
        """Why `quote` does not stand as the owner's `[declared]` line that asks for a system face, or None when it does."""
        wanted = _squash(quote)
        lines = [_squash(words) for _, words in self.declared]
        if not any(wanted in line for line in lines):
            return "is in no `[declared]` line of the brief record"
        terms = [*rules()["type"]["system_asks"], *(n for n in rules()["type"]["system_defaults"]
                                                    if len(n) >= 4 and not n.startswith("."))]
        if _find(wanted, terms) is None:
            return "does not ask for a system face (it names none of the terms in `rough_carry.type.system_asks`)"
        return None

    def availability(self, family: str) -> str | None:
        """Why `family` is not one this machine has or the run fetched, or None when it is: in the project's fonts lock, or
        installed (lazuli's inventory)."""
        if _norm(family) in self.lock:
            return None
        inventory = self.inventory
        if inventory.problem is not None:
            return (f"{family} is not in .lapis/fonts.lock.json, and {inventory.problem}: run `lazuli local fonts` to read "
                    "the installed fonts into it, or fetch the family and lock it (`lazuli fetch`, `lazuli lock`)")
        if not inventory.has(family):
            return (f"{family} is not installed (lazuli's inventory, {inventory.path}, has no such family) and not in "
                    ".lapis/fonts.lock.json: choose an installed family (`lazuli local fonts`), or fetch one and lock it "
                    "(`lazuli fetch`, `lazuli lock`)")
        return None

    def _role_problems(self, candidate: str, role: str, spec: Mapping[str, Any], extract: Any) -> list[str]:
        family = spec["family"]
        counts = rendered_families(extract, role)
        total = sum(counts.values())
        where = f"{candidate}'s {role}"
        if not total:
            return [f"{where} has no {'/'.join(ROLES[role])} text in its render, so its family cannot be read: give the rough "
                    f"a {role} and render it again"]
        keys: dict[str, str] = {}
        by_key: Counter[str] = Counter()
        for name, chars in counts.items():
            keys.setdefault(_norm(name), name)
            by_key[_norm(name)] += chars
        dominant = keys[by_key.most_common(1)[0][0]]
        if is_system(family):
            if "system_asked_by" not in spec:
                return [f"{where} names {family}, a system face, with no owner `[declared]` line that asks for it "
                        "(`system_asked_by`): choose an installed or fetched family"]
            if reason := self.asks_for_system(spec["system_asked_by"]):
                return [f"{where} quotes \"{spec['system_asked_by'][:60]}\" as the owner asking for a system face, and it {reason}"]
            if not is_system(dominant):
                return [f"{where} says the system face {family} and the render shows {dominant}"]
            return []
        system = {keys[k]: n for k, n in by_key.items() if is_system(keys[k])}
        share = sum(system.values()) / total
        if share > rules()["type"]["system_share"]:
            painted = ", ".join(f"{name} ({_percent(n / total)})" for name, n in sorted(system.items(), key=lambda p: -p[1]))
            return [f"{where} renders {_percent(share)} of its text in a system default, {painted}, not in {family}: a system "
                    "stack or a face the browser could not load paints it. Name the chosen family first in `font-family` "
                    "and load it (an installed face, or a locked file through @font-face), and give a Hangul or CJK page a "
                    "face that covers it; a card may choose a system face only by quoting an owner `[declared]` line that "
                    "asks for it (`system_asked_by`)"]
        if _norm(dominant) != _norm(family):
            return [f"{where} renders in {dominant} and its card names {family}"]
        if why := self.availability(family):
            return [f"{where}: {why}"]
        return []

    def type_problems(self, candidate: str, card: Mapping[str, Any], extract: Any) -> list[str]:
        spec = card["type"]
        problems = []
        if isinstance(extract, dict):
            for role in ROLES:
                problems += self._role_problems(candidate, role, spec[role], extract)
        if self.type_named and not spec.get("answers"):
            problems.append(f"{candidate}'s card does not say how its type answers the owner's own words about type, "
                            f"{'; '.join(self.type_named[:2])}: say it in `type.answers`, in a sentence")
        return problems

    # -- style

    def style_rows(self, candidate: str, card: Mapping[str, Any], extract: Any) -> tuple[list[str], list[dict[str, Any]]]:
        """`(problems, rows)` of the card's `style` against the answered items and the rough's markup. A row is `{"id",
        "selector", "does", "claimed", "shown"}` where `shown` is the claimed widths the render bears out."""
        where = f"{candidate}'s card"
        problems: list[str] = []
        need = {i["id"]: i for i in self.style}
        entries = card.get("style") or []
        ids = [e["id"] for e in entries]
        for ident in sorted({i for i in ids if ids.count(i) > 1}):
            problems.append(f"{where} maps {ident} twice")
        answered = {i["id"]: i for i in direction.items(self.root, self.task, self.env)}
        for ident in need:
            if ident not in ids:
                problems.append(f"{where} leaves out {ident} ({need[ident]['label']}), which the owner answered at the first "
                                "direction turn: name the element that carries it in `style` (a selector, what it does, and "
                                "the captures that show it)")
        for ident in dict.fromkeys(ids):
            if ident not in need:
                known = answered.get(ident)
                problems.append(f"{where} maps {ident}, "
                                + ("which the owner dropped" if known and known["kind"] == "K" and known["choice"] == ["drop"]
                                   else "which is no style item the owner answered or kit item they kept"))
        page = diverge.folder(self.root, self.task) / candidate / "index.html"
        try:
            tree = rough_selectors.parse(page.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            tree = None                                     # a missing page is the card check's problem
        rows = []
        for entry in entries:
            row = {"id": entry["id"], "selector": entry["selector"], "does": entry["does"],
                   "claimed": list(entry["shown"]), "shown": [], "matched": None}
            rows.append(row)
            if tree is None:
                continue
            try:
                nodes = rough_selectors.select(tree, entry["selector"])
            except rough_selectors.SelectorError as exc:
                problems.append(f"{where}: the selector `{entry['selector']}` of {entry['id']} cannot be read: {exc}")
                continue
            row["matched"] = len(nodes)
            if not nodes:
                problems.append(f"{where}: the selector `{entry['selector']}` of {entry['id']} matches no element of "
                                f"{candidate}'s index.html: name an element the markup holds (a script-made element is not "
                                "in it; name its container)")
                continue
            for width in entry["shown"]:
                if self._shown_at(nodes, diverge._viewport(extract, width)) is False:
                    problems.append(f"{where} says the {width} capture shows {entry['id']} (`{entry['selector']}`), and that "
                                    f"render has none of the element's text: it may be hidden at {width}. Say which captures "
                                    "show it")
                else:
                    row["shown"].append(width)
        return problems, rows

    @staticmethod
    def _shown_at(nodes: list[rough_selectors.Node], view: Any) -> bool | None:
        """Whether the element's text is among the text runs of `view`: True, False, or None when the element has no text
        to look for (a drawn or decorative element) or the render has no view of that width."""
        if not isinstance(view, dict):
            return None
        pieces = [p for node in nodes for p in node.strings()]
        if not pieces:
            return None
        blob = "".join(_squash(str(r.get("text") or "")) for r in view.get("text") or () if isinstance(r, dict)).replace(" ", "")
        whole = "".join(_squash(p) for p in pieces).replace(" ", "")
        return whole in blob or any(len(p.replace(" ", "")) >= 3 and _squash(p).replace(" ", "") in blob for p in pieces)

    # -- motion

    def motion_problems(self, candidate: str) -> list[str]:
        task = f"{self.task}-{candidate}"
        command = f"`lapis-design render motion .lapis/diverge/{self.task}/{candidate}/index.html --task {task}`"
        moves = self.brief.get("motion_moves", "")
        need = f"the shared brief requires motion ({moves[:80]})"
        manifest = motion.read(self.root, task)
        if manifest is None:
            return [f"{candidate} has no motion capture, and {need}: run {command}"]
        path = motion.manifest_path(self.root, task)
        rough = diverge.folder(self.root, self.task) / candidate / "index.html"
        if rough.is_file() and path.stat().st_mtime_ns < rough.stat().st_mtime_ns:
            return [f"{candidate}'s motion capture is older than its index.html: run {command} again"]
        blocks = [b for e in manifest.get("locales") or () if isinstance(e, dict) for b in e.get("widths") or ()
                  if isinstance(b, dict)]
        extract = diverge._json(diverge.extract_path(self.root, self.task, candidate))
        build = ((extract or {}).get("source") or {}).get("document_sha256") if isinstance(extract, dict) else None
        if build and blocks and not any(b.get("document_sha256") == build for b in blocks):
            return [f"{candidate}'s motion capture is of another build of the page than its render: run {command} again"]
        best = _best_change(self.root, blocks)
        wanted = rules()["motion"]["changed_share"]
        if best is None:
            return [f"{candidate}'s motion capture holds no pair of settled and reduced-motion frames to compare: run {command}"]
        if best < wanted:
            return [f"{candidate}'s motion capture shows no change: its settled and reduced-motion frames differ in "
                    f"{best:.2%} of their pixels at most, and {wanted:.2%} count; {need}. Make the motion play by itself "
                    "after load (a loop or a timed sequence, which `prefers-reduced-motion` stops), then capture it again: "
                    f"{command}"]
        return []

    def card_problems(self, candidate: str, card: Mapping[str, Any]) -> list[str]:
        extract = diverge._json(diverge.extract_path(self.root, self.task, candidate))
        problems = self.type_problems(candidate, card, extract)
        problems += self.style_rows(candidate, card, extract)[0]
        if self.motion_required:
            problems += self.motion_problems(candidate)
        return problems


def _changed_share(first: Path, second: Path) -> float | None:
    import numpy as np
    from PIL import Image

    try:
        a = np.asarray(Image.open(first).convert("RGB"), dtype=np.int16)
        b = np.asarray(Image.open(second).convert("RGB"), dtype=np.int16)
    except OSError:
        return None
    if a.shape != b.shape:
        return 1.0
    return float((np.abs(a - b).max(axis=2) > rules()["motion"]["pixel_delta"]).mean())


def _best_change(root: Path, blocks: list[dict[str, Any]]) -> float | None:
    """The largest share of pixels that differ between a settled and a reduced-motion frame of one scroll position, over the
    widths of a motion manifest; None when no pair could be read."""
    best: float | None = None
    for block in blocks:
        frames = [r for r in block.get("recordings") or () if isinstance(r, dict) and isinstance(r.get("path"), str)]
        settled = {r.get("scroll_y"): r for r in frames if r.get("kind") == "settled"}
        for frame in frames:
            if frame.get("kind") == "reduced" and (other := settled.get(frame.get("scroll_y"))) is not None:
                share = _changed_share(root / other["path"], root / frame["path"])
                if share is not None:
                    best = share if best is None else max(best, share)
    return best


# ---------------------------------------------------------------- the contract

def contract_problems(root: Path, task: str, found: Mapping[str, Any], env: Mapping[str, str]) -> list[str]:
    """What is wrong with the brief's `motion`: `none` while the owner's words ask for motion, unless `motion_still_by` quotes
    their `[declared]` line that asks for stillness."""
    where = f".lapis/diverge/{task}/brief.yaml"
    if found["motion"] != "none":
        return []
    asked = motion_asked(root, task, env)
    if not asked:
        return []
    quote = found.get("motion_still_by")
    if quote:
        wanted = _squash(quote)
        lines = [_squash(words) for _, words in declared_words(root, task)]
        if not any(wanted in line for line in lines):
            return [f"{where}: motion_still_by quotes \"{quote[:60]}\", which is in no `[declared]` line of the brief record"]
        if _find(wanted, rules()["motion"]["still_words"]) is None:
            return [f"{where}: motion_still_by quotes \"{quote[:60]}\", which asks for no stillness (it has none of the terms "
                    "in `rough_carry.motion.still_words`)"]
        return []
    return [f"{where}: motion is none, and the owner's words ask for it ({'; '.join(asked[:2])}"
            f"{'; and ' + str(len(asked) - 2) + ' more' if len(asked) > 2 else ''}): set `motion: required` with "
            "`motion_moves` (what moves in the first view), so every rough carries it; keep `none` only with "
            "`motion_still_by`, the owner's `[declared]` line that asks for stillness, quoted"]


# ---------------------------------------------------------------- what the owner is shown

def _cut(text: str, limit: int = 160) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit - 1] + "…"


def owner_lines(root: Path, task: str, candidates: list[str], env: Mapping[str, str]) -> list[str]:
    """Per rough, what its card says it carries and the render bears out, for the owner block and the pick question: the
    faces its headline and body render in and how they answer the owner's type words, and the style items its elements
    carry and show, with the ones the card claims and no capture shows."""
    carry = Carry(root, task, env)
    lines = []
    for candidate in candidates:
        card = diverge.card(root, task, candidate)
        if not card:
            continue
        extract = diverge._json(diverge.extract_path(root, task, candidate))
        spec = card.get("type")
        if isinstance(spec, dict) and isinstance(extract, dict):
            faces = []
            for role in ROLES:
                counts = rendered_families(extract, role)
                shown = counts.most_common(1)[0][0] if counts else "no text read"
                named = (spec.get(role) or {}).get("family", "none")
                faces.append(f"{role} {shown}" if _norm(shown) == _norm(named) else f"{role} {shown} (card: {named})")
            says = f"; answers the owner's type words: \"{_cut(spec['answers'])}\"" if spec.get("answers") else ""
            lines.append(f"- Rough {candidate} type, as rendered: {', '.join(faces)}{says}")
        if isinstance(card.get("style"), list) and carry.style:
            _, rows = carry.style_rows(candidate, card, extract)
            have = {r["id"] for r in rows}
            shown = [f"{r['id']} `{r['selector']}` ({', '.join(map(str, r['shown']))})" for r in rows
                     if r["shown"] and r["matched"]]
            claimed = [f"{r['id']} `{r['selector']}`" for r in rows if not r["shown"] and r["matched"]]
            dead = [f"{r['id']} `{r['selector']}`" for r in rows if r["matched"] == 0]
            missing = [i["id"] for i in carry.style if i["id"] not in have]
            parts = [f"carried and shown: {'; '.join(shown) or 'none'}"]
            if claimed:
                parts.append(f"claimed, not shown: {'; '.join(claimed)}")
            if dead:
                parts.append(f"claimed, matches no element: {'; '.join(dead)}")
            if missing:
                parts.append(f"not on the card: {', '.join(missing)}")
            lines.append(f"- Rough {candidate} style items, {'; '.join(parts)}")
    return lines
