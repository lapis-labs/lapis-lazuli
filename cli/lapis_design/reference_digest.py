"""The reference digest: what each reference gives the page and what it leaves out, written with the references record.

The digest is part of the references record (`references.py`): each reference carries a `take` list and a `leave` list.

    take:   - {id: M1, element: <a specific element of the reference>, at: <where it goes on our page>, why: <why>}
    leave:  - {id: M2, what: <what is attractive and excluded>, why: <why: its brand's own identity, a trend kit, ...>}

An id is `M<n>`, unique in the record. The record is the one place the digest is written; the plan's `references[]` is
derived from it (`lapis-design references digest --plan`) and checked against it (`plan_check.check_references`), a rough's
card names the take ids it uses, the owner sees the digest at the first direction turn, and the critic packet carries it.

What the CLI checks (`problems`, run by `references.problems`):

- every reference has at least one take item and at least one leave item, each item with an id and words of its own;
- a take item's `at` names a page location: a section id of the plan, an object id of the direction proposal, the heading
  of a section of the owner's brief, or a named region (`REGIONS_EN`, `REGIONS_KO`: hero, header, footer, first view,
  price table, form, button, ...);
- a leave item that matches a requirement row of the owner (a `[declared]` item of the brief record, or a row of their own
  brief file) is refused with the row quoted, unless the owner dropped that row (`[declared] R3f2a1c: drop — ...`).

The match is lexical: the content words of the leave item's `what` (lower-cased, plural `s` and Hangul particles taken off,
stop words left out, Han and kana read as character pairs) against each row, and it holds when the item has one content word
and the row has it, or when two of its content words stand within four words of each other in the row. A row id quoted in the
item's `what` or `why` holds too. It reads words, not meaning: a leave item that agrees with a row that forbids the thing
matches it all the same, and a reworded item that shares no content word gets through. It is a guard against a feature the
owner asked for sliding into `leave` unseen, not a judge.

The owner's replies (`[declared] take M3: <where it goes> — "<words>"`, `[declared] leave M2: — "<words>"`) are lines of the
brief record under `## Direction <n>`; the latest per id wins and `effective` applies them over the record. An owner's own
word is not matched against the rows.

Stdlib and PyYAML only: `next` and the stop hook import this through `references`.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

import yaml

from lapis_design import owner_text, requirements, waiting

ID = re.compile(r"M[1-9][0-9]*")
MIN_WORDS = waiting.MIN_WORDS
WINDOW = 4            # two content words of a leave item match a row when they stand this close, in words

REGIONS_EN = (
    "hero", "header", "masthead", "navigation", "nav", "menu", "footer", "sidebar", "banner", "first view", "first screen",
    "above the fold", "fold", "headline", "heading", "title", "subhead", "intro", "lede", "card", "list", "grid", "table",
    "row", "form", "field", "input", "button", "cta", "toolbar", "search", "filter", "modal", "dialog", "drawer", "toast",
    "tab", "gallery", "carousel", "slider", "pricing", "price", "testimonial", "faq", "contact", "caption", "label",
    "background", "overlay", "map", "chart", "diagram", "timeline", "logo", "cover", "opening")
REGIONS_KO = (
    "히어로", "헤더", "푸터", "메뉴", "내비게이션", "네비게이션", "내비", "사이드바", "배너", "첫 화면", "첫화면", "폴드", "제목",
    "헤드라인", "소제목", "소개", "카드", "목록", "리스트", "그리드", "폼", "입력", "버튼", "모달", "대화상자", "다이얼로그",
    "서랍", "토스트", "탭", "갤러리", "캐러셀", "슬라이더", "가격", "후기", "문의", "캡션", "라벨", "배경", "오버레이", "지도",
    "차트", "다이어그램", "타임라인", "로고", "표지", "도입부", "상단", "하단", "검색", "필터")

_WORD = re.compile(r"[^\W_]+")
_REGION_EN = re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(t).replace(r"\ ", r"\s+") for t in REGIONS_EN) + r")(?:e?s)?(?![\w-])",
                        re.IGNORECASE)
_REGION_KO = re.compile(r"(?<![가-힣])(?:" + "|".join(map(re.escape, REGIONS_KO)) + ")")
_ROW_ID = re.compile(r"(?<![\w])R[0-9a-f]{6}(?:[0-9a-f]{2})?(?![\w])")
_FLIP = re.compile(r"^(?P<side>take|leave)\s+(?P<id>M[1-9][0-9]*)\s*:\s*(?P<rest>.*)$", re.IGNORECASE | re.DOTALL)
_WHERE_END = re.compile(r"\s*(?:—|–|--|\s-\s|[\"“])")
_DROPPED_ANSWER = re.compile(r"^(?:C\d+\.)?[SKOGT]\d+\b.*:\s*drop\b", re.IGNORECASE | re.DOTALL)
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]+")
_HANGUL = re.compile(r"[\uac00-\ud7a3]")
_PARTICLES = ("에서", "으로", "에게", "까지", "부터", "처럼", "보다", "이나", "은", "는", "이", "가", "을", "를", "의", "에", "와", "과",
              "도", "로", "만")
_STOP = frozenset("""a an the of to in on for and or with its it is are be our we i my me you your this that no not as at by
from into like want wants need needs have has make use add page site should must please any all so but if than then them
they their there too also one more""".split())


def _words(value: Any) -> int:
    return len(_WORD.findall(value)) if isinstance(value, str) else 0


def _said(value: Any) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


# ---------------------------------------------------------------- the record's digest

def _record(root: Path, task: str) -> dict | None:
    from lapis_design import references

    try:
        data, _ = references.parse(references.record_path(root, task).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    return data


def _item_id(item: Any) -> str | None:
    found = item.get("id") if isinstance(item, dict) else None
    return found if isinstance(found, str) and ID.fullmatch(found) else None


def _entries(data: dict) -> list[dict]:
    """The references of the record as digest entries: `{id, source, maker, kind, direction, take, leave}`, an item as
    `{id, element, at, why, by}` or `{id, what, why, by}` with `by: agent`. A reference or item that is not shaped for it
    is left out (`problems` says so)."""
    found = []
    for ref in data.get("references") or ():
        if not isinstance(ref, dict) or not isinstance(ref.get("id"), str):
            continue
        take = [{"id": i["id"], "element": _said(i.get("element")), "at": _said(i.get("at")), "why": _said(i.get("why")),
                 "by": "agent"} for i in ref.get("take") or () if _item_id(i)]
        leave = [{"id": i["id"], "what": _said(i.get("what")), "why": _said(i.get("why")), "by": "agent"}
                 for i in ref.get("leave") or () if _item_id(i)]
        found.append({"id": ref["id"], "source": ref.get("url") or ref.get("source") or "", "maker": _said(ref.get("maker")),
                      "kind": ref.get("kind"), "direction": ref.get("direction") if isinstance(ref.get("direction"), str) else "none",
                      "take": take, "leave": leave})
    return found


# ---------------------------------------------------------------- the words of the owner

def _stem(word: str) -> str:
    if _HANGUL.search(word):
        for particle in _PARTICLES:
            if word.endswith(particle) and len(word) - len(particle) >= 2:
                return word[:-len(particle)]
        return word
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def sequence(text: str) -> list[str]:
    """The content words of `text`, in order: NFKC and case folded, a plural `s` and a Hangul particle taken off, stop
    words and one-letter words left out, and a run of Han or kana read as pairs of characters."""
    out: list[str] = []
    for word in _WORD.findall(requirements.norm(text)):
        for part in re.split("(" + _CJK.pattern + ")", word):
            if not part:
                continue
            if _CJK.fullmatch(part):
                out += [part[i:i + 2] for i in range(max(1, len(part) - 1))]
            elif len(stem := _stem(part)) >= 2 and stem not in _STOP:
                out.append(stem)
    return out


def shared_words(leave: list[str], row: list[str]) -> list[str]:
    """The content words that make a leave item match a row, or [] when it does not (see the module doc)."""
    wanted = list(dict.fromkeys(leave))
    where: dict[str, list[int]] = {}
    for index, word in enumerate(row):
        where.setdefault(word, []).append(index)
    present = [word for word in wanted if word in where]
    if len(wanted) == 1:
        return present
    for a, b in combinations(present, 2):
        if any(abs(i - j) < WINDOW for i in where[a] for j in where[b]):
            return [a, b]
    return []


def owner_rows(root: Path, task: str) -> list[dict]:
    """The owner's requirement rows a leave item may not take away, `{id, text}`: the rows of the requirement record and the
    `[declared]` items of the brief record as they are now, less the rows the owner dropped, the owner's own take and leave
    replies, and a direction answer that drops its item."""
    rows: dict[str, dict] = {}
    dropped: set[str] = set()
    record = requirements.record(root, task)
    if record is not None:
        for row in record["rows"]:
            rows[requirements.norm(row["text"])] = {"id": row["id"], "text": row["text"]}
        dropped |= {d["row"] for d in record["owner_decisions"] if d["decision"] == "drop"}
    try:
        text = waiting.answers_path(root, task).read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    declared, decisions = requirements._declared(text, requirements.answers_name(task))
    for row in declared:
        key = requirements.norm(row["text"])
        rows.setdefault(key, {"id": "R" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:6], "text": row["text"]})
    dropped |= {d["row"] for d in decisions if d["decision"] == "drop"}
    return [row for row in rows.values()
            if row["id"] not in dropped and not _FLIP.match(row["text"]) and not _DROPPED_ANSWER.match(row["text"])]


def _match(item: dict, rows: list[dict]) -> tuple[dict, list[str]] | None:
    """The row a leave item takes away and the words that show it, or None."""
    said = f"{item.get('what', '')} {item.get('why', '')}" if isinstance(item, dict) else ""
    for row in rows:
        if row["id"] in _ROW_ID.findall(said):
            return row, [row["id"]]
    wanted = sequence(item.get("what")) if isinstance(item.get("what"), str) else []
    for row in rows:
        if shared := shared_words(wanted, sequence(row["text"])):
            return row, shared
    return None


# ---------------------------------------------------------------- where on the page

def place_ids(root: Path, task: str) -> list[str]:
    """The ids a take item's `at` may name besides a region: the plan's `layout.sections[].id`, the object ids of the
    direction proposal, and the headings of the owner's requirement rows."""
    found: list[str] = []
    for name, keys in ((f".lapis/plans/{task}.yaml", ("layout", "sections")), (f".lapis/direction/{task}.yaml", ("objects",))):
        try:
            doc = yaml.safe_load((root / name).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError, ValueError):
            continue
        for key in keys:
            doc = doc.get(key) if isinstance(doc, dict) else None
        found += [i["id"] for i in doc or () if isinstance(i, dict) and isinstance(i.get("id"), str)]
    record = requirements.record(root, task)
    found += [r["section"] for r in (record or {}).get("rows", ()) if isinstance(r.get("section"), str) and len(r["section"]) >= 3]
    return list(dict.fromkeys(found))


def names_place(text: str, ids: list[str]) -> bool:
    """Whether `text` names a page location: a known id or section heading, or a named region."""
    if _REGION_EN.search(text) or _REGION_KO.search(text):
        return True
    return any(re.search(r"(?<![\w-])" + re.escape(i) + r"(?![\w-])", text, re.IGNORECASE) for i in ids if i.strip())


# ---------------------------------------------------------------- the checks

def problems(data: dict, root: Path, task: str) -> list[str]:
    """What the references of `data` (the record's mapping) lack of a digest, one line each."""
    found: list[str] = []
    ids = place_ids(root, task)
    rows = owner_rows(root, task)
    used: dict[str, str] = {}

    def own(item: Any, who: str, kind: str, number: int) -> str | None:
        """The id of `item` when it has one of its own; a problem is added otherwise."""
        if not isinstance(item, dict):
            found.append(f"{who}: `{kind}` item {number} is not a mapping")
            return None
        name = item.get("id")
        if not isinstance(name, str) or not ID.fullmatch(name):
            found.append(f"{who}: `{kind}` item {number} has no `id` of the form M1, M2, ... (got {name!r})")
            return None
        if name in used:
            found.append(f"{who}: the digest id {name} is used twice (also in {used[name]})")
        used.setdefault(name, who)
        return name

    for index, ref in enumerate(data.get("references") or (), start=1):
        if not isinstance(ref, dict):
            continue
        name = ref.get("id") if isinstance(ref.get("id"), str) and ref["id"].strip() else None
        who = f"reference {name}" if name else f"reference {index}"
        take, leave = ref.get("take"), ref.get("leave")
        if not isinstance(take, list) or not take:
            found.append(f"{who} has no `take` items; give one or more, each `id`, `element` (a specific element of it), `at` "
                         "(where it goes on our page) and `why`")
        if not isinstance(leave, list) or not leave:
            found.append(f"{who} has no `leave` item; every reference leaves something: give one or more, each `id`, `what` "
                         "(what is attractive and excluded) and `why` (its brand's own identity, a trend kit, the owner's words, "
                         "the wrong genre)")
        for number, item in enumerate(take if isinstance(take, list) else (), start=1):
            ident = own(item, who, "take", number)
            if ident is None:
                continue
            for field in ("element", "why"):
                if _words(item.get(field)) < MIN_WORDS:
                    found.append(f"{who}: take {ident} has no `{field}` (two words at least)")
            at = item.get("at")
            if not isinstance(at, str) or not names_place(at, ids):
                found.append(f"{who}: take {ident} names no page location in `at` ({at!r}); name a section or object id of the "
                             f"brief or plan{' (' + ', '.join(ids[:6]) + ')' if ids else ''}, or a region such as hero, header, "
                             "footer, first view, price table, form, or button")
        for number, item in enumerate(leave if isinstance(leave, list) else (), start=1):
            ident = own(item, who, "leave", number)
            if ident is None:
                continue
            for field in ("what", "why"):
                if _words(item.get(field)) < MIN_WORDS:
                    found.append(f"{who}: leave {ident} has no `{field}` (two words at least)")
            if (hit := _match(item, rows)) is not None:
                row, shared = hit
                text = " ".join(row["text"].split())
                found.append(f"{who}: leave {ident} ({item.get('what')!r}) takes away the owner's row {row['id']} "
                             f"\"{text[:160]}{'…' if len(text) > 160 else ''}\" (matched on {', '.join(shared)}). What the owner asked "
                             "for is not the run's to leave: move it to `take` with where it goes, or word the leave by what "
                             "differs; the row goes only when the owner's own reply drops it "
                             f"(`[declared] {row['id']}: drop — \"<their words>\"`)")
    return found


# ---------------------------------------------------------------- the owner's replies

def flips(root: Path, task: str) -> list[dict]:
    """The owner's `[declared] take|leave M<n>: ...` replies under `## Direction <n>` of the brief record, in file order:
    `{side, id, where, said, quote, turn}`."""
    from lapis_design import direction

    found = []
    for line in direction._lines(root, task):
        match = _FLIP.match(line["text"]) if line["tag"] == "declared" else None
        if match is None:
            continue
        rest = match.group("rest").strip()
        end = _WHERE_END.search(rest)
        where = rest[:end.start()].strip() if end else rest
        found.append({"side": match.group("side").lower(), "id": match.group("id"), "where": where, "said": rest.lstrip(" —–-"),
                      "quote": " ".join(line["item"].split()), "turn": line["turn"]})
    return found


def _find(refs: list[dict], ident: str) -> tuple[dict, str, dict] | None:
    for ref in refs:
        for side in ("take", "leave"):
            for item in ref[side]:
                if item["id"] == ident:
                    return ref, side, item
    return None


def _apply(refs: list[dict], ids: list[str], replies: list[dict]) -> list[str]:
    """The replies applied to `refs` in order, the problems of those that cannot be applied."""
    held: list[str] = []
    for reply in replies:
        at = _find(refs, reply["id"])
        if at is None:
            held.append(f"the owner's reply `{reply['side']} {reply['id']}` names an item the digest does not list")
            continue
        ref, side, item = at
        quote = reply["quote"]
        if reply["side"] == "take":
            if not names_place(reply["said"], ids):
                if side == "leave":
                    held.append(f"the owner moved {reply['id']} to what we take but said nothing of where it goes: ask where "
                                f"on the page ({quote[:100]})")
                continue
            place = reply["where"] if names_place(reply["where"], ids) else reply["said"]
            if side == "leave":
                ref["leave"].remove(item)
                ref["take"].append({"id": item["id"], "element": item["what"], "at": place, "why": reply["said"], "by": "owner"})
                ref["take"].sort(key=lambda i: int(i["id"][1:]))
            else:
                item.update(at=place, by="owner")
        elif side == "take":
            ref["take"].remove(item)
            ref["leave"].append({"id": item["id"], "what": item["element"], "why": reply["said"] or item["why"], "by": "owner"})
            ref["leave"].sort(key=lambda i: int(i["id"][1:]))
        else:
            item.update(by="owner")
    return held


def _state(root: Path, task: str) -> tuple[dict, list[str]] | None:
    data = _record(root, task)
    if data is None:
        return None
    refs = _entries(data)
    if not any(ref["take"] or ref["leave"] for ref in refs):
        return None
    names = data.get("directions") if isinstance(data.get("directions"), dict) else {}
    held = _apply(refs, place_ids(root, task), flips(root, task))
    return {"directions": {k: v for k, v in names.items() if isinstance(k, str) and isinstance(v, str)}, "references": refs}, held


def effective(root: Path, task: str) -> dict | None:
    """The digest as it stands: the record's, with the owner's replies applied. `{directions: {letter: name}, references:
    [{id, source, maker, kind, direction, take, leave}]}`; None when the run has no references record with a digest (a run
    that declined the step, or a record written before the digest)."""
    state = _state(root, task)
    return None if state is None else state[0]


def flip_problems(root: Path, task: str) -> list[str]:
    """The owner's take and leave replies that cannot be applied: an id the digest does not list, or a move to what we take
    with no word of where it goes."""
    state = _state(root, task)
    return [] if state is None else state[1]


def take_ids(root: Path, task: str) -> set[str] | None:
    """The ids of the take items that stand, or None when there is no digest."""
    digest = effective(root, task)
    return None if digest is None else {i["id"] for ref in digest["references"] for i in ref["take"]}


def leave_ids(root: Path, task: str) -> set[str]:
    digest = effective(root, task)
    return set() if digest is None else {i["id"] for ref in digest["references"] for i in ref["leave"]}


# ---------------------------------------------------------------- what the owner and the critic see

def _cell(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "/")


def summary_lines(root: Path, task: str, lang: str = "en") -> list[str]:
    """The digest as the owner summary carries it: a note, and per direction a compact table, in the owner's language
    (`owner_text.py`); the text of an item is the record's own. [] when there is no digest."""
    digest = effective(root, task)
    return [] if digest is None else render(digest, lang)


def render(digest: dict, lang: str = "en") -> list[str]:
    say = owner_text.say
    lines = [say(lang, "digest.note")]
    letters = [*digest["directions"], "none"]
    groups = {letter: [r for r in digest["references"] if r["direction"] == letter] for letter in letters}
    stray = [r for r in digest["references"] if r["direction"] not in letters]
    groups["none"] += stray
    for letter in letters:
        refs = groups[letter]
        if not refs or not any(r["take"] or r["leave"] for r in refs):
            continue
        title = (say(lang, "digest.group", letter=letter, name=digest["directions"][letter]) if letter in digest["directions"]
                 else say(lang, "digest.group.none"))
        lines += ["", f"**{_cell(title)}**", "", say(lang, "digest.columns"), "|---|---|---|---|---|"]
        by_owner = say(lang, "digest.owner")
        for ref in refs:
            for item in ref["take"]:
                detail = f"{_cell(item['at'])} — {_cell(item['why'])}" + (by_owner if item["by"] == "owner" else "")
                lines.append(f"| {item['id']} | {_cell(ref['id'])} | {say(lang, 'digest.take')} | {_cell(item['element'])} | {detail} |")
            for item in ref["leave"]:
                detail = _cell(item["why"]) + (by_owner if item["by"] == "owner" else "")
                lines.append(f"| {item['id']} | {_cell(ref['id'])} | {say(lang, 'digest.leave')} | {_cell(item['what'])} | {detail} |")
    return lines


def packet(root: Path, task: str) -> dict:
    """The `reference_digest` section of the critic packet: per reference its direction, the take items that stand (with
    where each goes and why) and the leave items, `by` saying whether the owner moved or confirmed it. {} when there is no
    digest, so a packet of a run without one is as it was."""
    digest = effective(root, task)
    if digest is None:
        return {}
    return {"references": [
        {"id": ref["id"], "direction": ref["direction"],
         "take": [{k: i[k] for k in ("id", "element", "at", "why", "by")} for i in ref["take"]],
         "leave": [{k: i[k] for k in ("id", "what", "why", "by")} for i in ref["leave"]]} for ref in digest["references"]]}


# ---------------------------------------------------------------- the plan's references

def item_id(text: Any) -> str | None:
    """The digest id a plan `take` or `leave` string starts with (`M3: the ruled rows`), or None."""
    found = re.match(r"\s*(M[1-9][0-9]*)\b", text) if isinstance(text, str) else None
    return found.group(1) if found else None


def plan_entries(root: Path, task: str, letter: str | None = None) -> list[dict]:
    """The plan's `references[]` entries the digest gives, one per reference with a take item that stands: `record_id`, the
    `source`, and `take` and `leave` strings that start with their ids."""
    digest = effective(root, task)
    out = []
    for ref in (digest or {}).get("references", ()):
        if not ref["take"] or (letter and ref["direction"] != letter):
            continue
        out.append({"source": ref["source"], "kind": "site" if ref["kind"] == "web-ui" else "image", "rights": "reference-only",
                    "mode": "analyze", "record_id": ref["id"],
                    "take": [f"{i['id']}: {i['element']} — at {i['at']}" for i in ref["take"]],
                    "leave": [f"{i['id']}: {i['what']} — {i['why']}" for i in ref["leave"]]})
    return out


def plan_problems(root: Path, task: str, entries: list[Any]) -> list[tuple[int | None, str]]:
    """What the plan's `references` lack of or contradict in the digest, as (index of the plan entry or None, sentence). An
    entry with `record_id` has to carry exactly the ids of that reference's take items and leave items that stand; every
    reference with a take item that stands needs an entry."""
    digest = effective(root, task)
    if digest is None:
        return []
    by_id = {ref["id"]: ref for ref in digest["references"]}
    found: list[tuple[int | None, str]] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        record_id = entry.get("record_id") if isinstance(entry, dict) else None
        if record_id is None:
            continue
        ref = by_id.get(record_id)
        if ref is None:
            found.append((index, f"`record_id` {record_id!r} is no reference of the references record"))
            continue
        seen.add(record_id)
        for side in ("take", "leave"):
            given = [item_id(s) for s in entry.get(side) or ()]
            want = {i["id"] for i in ref[side]}
            if None in given:
                found.append((index, f"a `{side}` string does not start with a digest id (`{next(iter(sorted(want)), 'M1')}: ...`)"))
            if missing := sorted(want - set(given), key=lambda i: int(i[1:])):
                found.append((index, f"`{side}` leaves out {', '.join(missing)} of {record_id}"
                              + (" (the owner moved it)" if any(i["by"] == "owner" for i in ref[side] if i["id"] in missing) else "")))
            if extra := sorted({g for g in given if g and g not in want}, key=lambda i: int(i[1:])):
                other = "leave" if side == "take" else "take"
                found.append((index, f"`{side}` names {', '.join(extra)}, which {record_id} "
                              + ("holds as a " + other + " item" if all(e in {i['id'] for i in ref[other]} for e in extra)
                                 else "does not hold")))
    for ref in digest["references"]:
        if ref["take"] and ref["id"] not in seen:
            found.append((None, f"the reference {ref['id']} has take items ({', '.join(i['id'] for i in ref['take'])}) and no "
                          "entry with `record_id` in `references`"))
    return found


# ---------------------------------------------------------------- the command

def main(argv: list[str] | None = None, prog: str = "lapis-design references digest") -> int:
    ap = argparse.ArgumentParser(prog=prog, description="Print the reference digest as it stands: the record's take and leave items "
                                 "with the owner's replies applied, grouped by direction (or, with --plan, the plan's `references` "
                                 "entries it gives).", allow_abbrev=False)
    ap.add_argument("--task", required=True, help="the task id of the references record")
    ap.add_argument("--project", type=Path, default=Path("."), help="project folder (default: .)")
    ap.add_argument("--direction", help="only the references of this direction letter")
    ap.add_argument("--plan", action="store_true", help="print the `references` entries of the plan the digest gives, as YAML")
    args = ap.parse_args(argv)
    digest = effective(args.project, args.task)
    if digest is None:
        print(f"{prog}: the references record {args.project / '.lapis' / 'references' / (args.task + '.md')} has no digest "
              "(`take` and `leave` items on its references)", file=sys.stderr)
        return 1
    if args.plan:
        print(yaml.safe_dump(plan_entries(args.project, args.task, args.direction), sort_keys=False, allow_unicode=True, width=120), end="")
        return 0
    for held in flip_problems(args.project, args.task):
        print(f"{prog}: {held}", file=sys.stderr)
    if args.direction:
        digest = {**digest, "directions": {k: v for k, v in digest["directions"].items() if k == args.direction},
                  "references": [r for r in digest["references"] if r["direction"] in (args.direction, "none")]}
    print("\n".join(render(digest, "en")))
    return 0
