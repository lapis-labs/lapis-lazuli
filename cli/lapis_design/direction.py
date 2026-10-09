"""The direction conversation: the owner decides what a named style does, how each core object is represented, and
what each signature element carries, item by item, before the plan.

The run writes a proposal, `.lapis/direction/<task>.yaml` (`shared/direction/schema.yaml`): per named style `S<n>` two or
three jobs and the trend-kit items `K<n>` it decodes to today, per core object `O<n>` two or three representations, and
per signature element the brief names `G<n>` what it carries. It asks the owner about every open item in one message
(`.lapis/questions/<task>.md`, first line `lapis-questions: direction`), and records the answers in the brief record
`.lapis/answers/<task>.md` under `## Direction <n>` headings:

    - [declared] K2 ticker band: drop — "<owner words>"
    - [declared] O1 the comparison: a,c — "<owner words>"          (narrowed: `diverge` explores a and c)
    - [declared] S1 neo-brutalism: other — <their own words>
    - [declared] Pick: C2 — "<owner words>"                         (the second turn, after `diverge`)
    - [declared] C2.G1 crystal stone: a — "<owner words>"           (the second turn: the picked rough's signature)
    - Defaults accepted (direction 2): "<owner words>"              (untagged: every open item takes its default)

`items` reads the proposal and the answers and gives each item a state (`open`, `narrowed`, `decided`, `delegated`) and
who gave it (`owner`, or `assumed` in an unattended run, which never waits and records `[assumed] ... Basis: ...`). The
step `owner-direction` (`owed`) is owed while the proposal is missing or malformed or an item is open: at the first turn
any style, kit, or object item; at the second turn, after the `diverge` seal, the pick or a signature item of the picked
rough. A `direction` questions file waits only when it names every open item and at least one is open
(`questions_problem`), so a turn cannot be a progress check-in. Every `[declared]` item stays a requirement row, except
`Pick:`, which is the owner's decision, not a requirement.

Nothing here judges whether the options are good: it keeps the conversation from being skipped, an answer from being an
agent's guess, and the critic from judging a bare letter (`packet`).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Mapping

import yaml

from lapis_design import brief, diverge, gate, references, waiting

STEP = "owner-direction"
KIND = "direction"
PICK_ID = "Pick"                       # the id the second turn's questions name for the pick

_HEAD = re.compile(r"^direction\s+(\d+)\b", re.IGNORECASE)
_ANSWER = re.compile(r"^(?:(?P<cand>C\d+)\.)?(?P<id>[SKOG]\d+)\b[^:\n]*:\s*"
                     r"(?P<choice>keep|drop|default|other|all|[a-e](?:\s*,\s*[a-e])*)\b", re.IGNORECASE)
_PICK = re.compile(r"^pick\s*:\s*(?P<cand>C\d+)\b", re.IGNORECASE)
_DEFAULTS = re.compile(r"^defaults\s+accepted\s*\(\s*direction\s+(?P<turn>\d+)\s*\)\s*:\s*(?P<words>\S.*)$",
                       re.IGNORECASE | re.DOTALL)
_LEAD = re.compile(r"^[\s*_`:\-–—]+")
_ID = re.compile(r"^(?:C\d+\.)?[SKOG]\d+$")


def path(root: Path, task: str) -> Path:
    return root / ".lapis" / "direction" / f"{task}.yaml"


def _read(file: Path) -> str:
    try:
        return file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ---------------------------------------------------------------- the proposal

def proposal(root: Path, task: str) -> dict[str, Any] | None:
    """The proposal as written (a mapping), or None when the file is missing, unreadable, or no mapping."""
    try:
        found = yaml.safe_load(path(root, task).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return found if isinstance(found, dict) else None


def pool_kinds() -> list[str]:
    """The kinds of core object `diverge/pools.yaml` has representation families for."""
    return list((diverge.pools().get("representation") or {}))


def _reference_ids(root: Path, task: str) -> set[str]:
    data, _ = references.parse(_read(references.record_path(root, task)))
    return {str(r.get("id")) for r in (data or {}).get("references") or () if isinstance(r, dict) and r.get("id")}


def _row_ids(root: Path, task: str) -> set[str] | None:
    from lapis_design import requirements

    rows = requirements.rows(root, task)
    return None if rows is None else {r["id"] for r in rows}


def _duplicates(ids: list[str]) -> list[str]:
    return sorted({i for i in ids if ids.count(i) > 1})


def proposal_problem(root: Path, task: str) -> str | None:
    """Why `.lapis/direction/<task>.yaml` is not a proposal, or None when it is. Form, never quality."""
    from jsonschema import Draft202012Validator

    where = path(root, task).relative_to(root).as_posix()
    try:
        found = yaml.safe_load(path(root, task).read_text(encoding="utf-8"))
    except OSError:
        return f"{where} does not exist"
    except yaml.YAMLError as exc:
        return f"{where} cannot be read: {(str(exc).splitlines() or [''])[0]}"
    errors = sorted(Draft202012Validator(diverge.shared_yaml("direction/schema.yaml")).iter_errors(found), key=lambda e: (len(list(e.absolute_path)), e.message))
    if errors:
        first = errors[0]
        return f"{where} does not match direction/schema.yaml: {'/'.join(map(str, first.absolute_path)) or 'it'}: {first.message[:160]}"
    if found["task"] != task:
        return f"{where} is for task {found['task']!r}, not {task!r}"
    styles, objects, signature = found["styles"], found["objects"], found["signature"]
    kit = [k for s in styles for k in s["kit"]]
    for label, ids in (("style", [s["id"] for s in styles]), ("kit", [k["id"] for k in kit]),
                       ("object", [o["id"] for o in objects]), ("signature", [g["id"] for g in signature])):
        if dup := _duplicates(ids):
            return f"{where} repeats the {label} id {', '.join(dup)}"
    for item in (*styles, *objects, *signature):
        options = [o["id"] for o in item["options"]]
        if dup := _duplicates(options):
            return f"{where}: {item['id']} repeats the option id {', '.join(dup)}"
        allowed = [*options, "all"] if item["id"].startswith("O") else options
        if item["default"] not in allowed:
            return f"{where}: the default of {item['id']} is {item['default']!r}, which is none of its options ({', '.join(allowed)})"
    kinds = pool_kinds()
    for item in objects:
        if item["kind"] not in kinds:
            return f"{where}: {item['id']} has the kind {item['kind']!r}; the pools have {', '.join(kinds)}"
    known = _reference_ids(root, task)
    for k in kit:
        if missing := [r for r in k["seen_in"] if r not in known]:
            return (f"{where}: {k['id']} `seen_in` names {', '.join(missing)}, which the references record "
                    f"{references.record_path(Path('.'), task).as_posix()} does not list"
                    + ("" if known else " (it lists no reference)"))
    rows = _row_ids(root, task)
    for style in styles:
        if rows is not None and (missing := [r for r in style.get("rows") or () if r not in rows]):
            return f"{where}: {style['id']} `rows` names {', '.join(missing)}, which the requirement record does not hold"
    return None


# ---------------------------------------------------------------- the answers

def _env_unattended(env: Mapping[str, str]) -> bool:
    return gate.is_unattended(env)


def _turns(text: str) -> list[tuple[int, list[str]]]:
    """The list items under each `## Direction <n>` heading, as (n, items): the body runs to the next heading of the same
    or a higher level, a continuation line going on with its item."""
    lines = text.splitlines()
    heads = [(i, len(m.group(1)), m.group(2)) for i, line in enumerate(lines) if (m := brief._HEADING.match(line))]
    found = []
    for n, (start, level, title) in enumerate(heads):
        if match := _HEAD.match(title.strip()):
            end = next((i for i, other, _ in heads[n + 1:] if other <= level), len(lines))
            found.append((int(match.group(1)), brief.items("\n".join(lines[start + 1:end]))))
    return found


def _lines(root: Path, task: str) -> list[dict[str, Any]]:
    """Every answer line of the direction sections, in file order: `{"turn", "tag" (declared, assumed, or None), "text"
    (after the tag), "item" (the whole item), "basis" (the item gives a Basis)}`."""
    found = []
    for turn, items in _turns(_read(waiting.answers_path(root, task))):
        for item in items:
            tag = brief._TAG.match(item)
            text = _LEAD.sub("", item[tag.end():]) if tag else item.strip()
            basis = bool((b := brief._BASIS.search(item)) and waiting.words(b.group(1)) >= waiting.MIN_WORDS)
            found.append({"turn": turn, "tag": tag.group(1).lower() if tag else None, "text": text, "item": item,
                          "basis": basis})
    return found


def _counts(line: dict[str, Any], unattended: bool) -> bool:
    """Whether `line` stands as an answer: the owner's `[declared]`, or, in an unattended run, an `[assumed]` one that
    gives its `Basis:`."""
    return line["tag"] == "declared" or (unattended and line["tag"] == "assumed" and line["basis"])


def _clean(words: str) -> str:
    return " ".join(words.split())


def turns(root: Path, task: str) -> int:
    """The highest `## Direction <n>` number in the answers, 0 when there is none."""
    return max((n for n, _ in _turns(_read(waiting.answers_path(root, task)))), default=0)


def next_turn(root: Path, task: str) -> int:
    return turns(root, task) + 1


def _choice_ok(item: dict[str, Any], choice: list[str]) -> bool:
    options = {o["id"] for o in item["options"]}
    if item["kind"] == "K":
        return len(choice) == 1 and choice[0] in ("keep", "drop", "default", "other")
    if choice == ["default"] or choice == ["other"]:
        return True
    if item["kind"] == "O" and choice == ["all"]:
        return True
    return all(c in options for c in choice) and len(choice) == len(set(choice)) and (item["kind"] == "O" or len(choice) == 1)


def _proposal_items(doc: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for style in doc.get("styles") or ():
        out.append({"id": style["id"], "kind": "S", "label": style["name"], "candidate": None,
                    "options": [{"id": o["id"], "text": o["text"]} for o in style["options"]], "default": style["default"]})
        for k in style["kit"]:
            out.append({"id": k["id"], "kind": "K", "label": k["item"], "candidate": None, "style": style["id"],
                        "options": [{"id": "keep", "text": "keep it"}, {"id": "drop", "text": "drop it"}],
                        "default": k["default"], "seen_in": list(k["seen_in"])})
    for obj in doc.get("objects") or ():
        out.append({"id": obj["id"], "kind": "O", "label": obj["object"], "candidate": None, "object_kind": obj["kind"],
                    "options": [{"id": o["id"], "text": o["text"], "does": o["does"], "family": o["family"]}
                                for o in obj["options"]], "default": obj["default"]})
    for sig in doc.get("signature") or ():
        out.append({"id": sig["id"], "kind": "G", "label": sig["element"], "candidate": None,
                    "options": [{"id": o["id"], "text": o["text"]} for o in sig["options"]], "default": sig["default"]})
    return out


def candidate_items(root: Path, task: str) -> list[dict[str, Any]]:
    """The signature items of each rough of the sealed set, `C<k>.G<n>`: what the element carries is the card's own
    text (option `a`); the owner takes it, or says what it should carry instead."""
    out = []
    for cid in (diverge.sealed(root, task) or {}).get("candidates", {}):
        card = diverge.card(root, task, cid) or {}
        for g in card.get("signature") or ():
            if isinstance(g, dict) and isinstance(g.get("id"), str) and isinstance(g.get("element"), str):
                out.append({"id": f"{cid}.{g['id']}", "kind": "G", "label": g["element"], "candidate": cid,
                            "options": [{"id": "a", "text": str(g.get("carries", ""))}], "default": "a"})
    return out


def _d1_turns(root: Path, task: str) -> int | None:
    seal = diverge.sealed(root, task)
    value = seal.get("d1_turns") if seal else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def items(root: Path, task: str, env: Mapping[str, str] = os.environ) -> list[dict[str, Any]]:
    """The items of the conversation with their state: the proposal's, and, once `diverge` is sealed, each rough's
    signature items. `{"id", "kind", "label", "candidate", "options", "default", "state", "by", "choice", "quote"}`
    (a kit item also has `style` and `seen_in`, an object `object_kind`). `state` is `open` while no answer stands,
    `narrowed` for an object the owner cut to two or more options, `decided` for any other answer, and `delegated`
    for an item an untagged `Defaults accepted` line took; `by` is `owner`, or `assumed` in an unattended run; `choice`
    is the option ids, `keep`, `drop`, `all`, or `other` that stand (the default's, when delegated)."""
    doc = proposal(root, task)
    if doc is None:
        return []
    unattended = _env_unattended(env)
    entries = [*_proposal_items(doc), *candidate_items(root, task)]
    lines = _lines(root, task)
    answers: dict[str, dict[str, Any]] = {}
    for line in lines:
        found = _ANSWER.match(line["text"])
        if not found or not _counts(line, unattended):
            continue
        key = (f"{found.group('cand').upper()}." if found.group("cand") else "") + found.group("id").upper()
        choice = [c.strip().lower() for c in found.group("choice").split(",")]
        answers[key] = {"choice": choice, "by": "owner" if line["tag"] == "declared" else "assumed",
                        "quote": _clean(line["item"]), "turn": line["turn"]}
    d1 = _d1_turns(root, task)
    defaults = [ln for ln in lines if ln["tag"] is None and _DEFAULTS.match(ln["text"])]
    out = []
    for entry in entries:
        given = answers.get(entry["id"])
        if given and _choice_ok(entry, given["choice"]):
            choice = [entry["default"]] if given["choice"] == ["default"] else given["choice"]
            state = "narrowed" if entry["kind"] == "O" and len(choice) >= 2 else "decided"
            out.append({**entry, "state": state, "by": given["by"], "choice": choice, "quote": given["quote"]})
            continue
        taken = next((_clean(d["item"]) for d in defaults
                      if entry["candidate"] is None or (d1 is not None and int(_DEFAULTS.match(d["text"]).group("turn")) > d1)),
                     None)
        if taken is not None:
            out.append({**entry, "state": "delegated", "by": "owner", "choice": [entry["default"]], "quote": taken})
        else:
            out.append({**entry, "state": "open", "by": None, "choice": None, "quote": None})
    return out


def _pick_lines(root: Path, task: str, env: Mapping[str, str]) -> list[dict[str, Any]]:
    unattended = _env_unattended(env)
    found = []
    for line in _lines(root, task):
        match = _PICK.match(line["text"])
        if match and _counts(line, unattended):
            found.append({"candidate": match.group("cand").upper(), "by": "owner" if line["tag"] == "declared" else "assumed",
                          "quote": _clean(line["item"]), "turn": line["turn"]})
    return found


def pick_count(root: Path, task: str, env: Mapping[str, str] = os.environ) -> int:
    """How many `Pick:` lines the answers hold now (an owner-requested variant records it, so the pick is asked again)."""
    return len(_pick_lines(root, task, env))


def pick(root: Path, task: str, env: Mapping[str, str] = os.environ) -> dict[str, Any] | None:
    """The last `[declared] Pick: C<n>` of the answers (`[assumed]` with its `Basis:` in an unattended run) that comes
    after the latest owner-requested variant: `{"candidate", "by", "quote"}`, or None."""
    lines = _pick_lines(root, task, env)
    if len(lines) <= diverge.variant_floor(root, task):
        return None
    last = lines[-1] if lines else None
    return {k: last[k] for k in ("candidate", "by", "quote")} if last else None


def decisions(root: Path, task: str) -> list[dict[str, Any]]:
    """What the owner decided in the conversation outside the item rows, for the owner block: each `Pick:` line
    (`{"kind": "pick", "text": "C2", ...}`) and each `Defaults accepted` line (`{"kind": "defaults", "turn": n, ...}`),
    with `by` and the item as written in `quote`. Items are requirement rows and need no listing here."""
    found = []
    for line in _lines(root, task):
        if line["tag"] == "declared" and (m := _PICK.match(line["text"])):
            found.append({"kind": "pick", "turn": line["turn"], "text": m.group("cand").upper(), "by": "owner",
                          "quote": _clean(line["item"])})
        elif line["tag"] is None and _DEFAULTS.match(line["text"]):
            found.append({"kind": "defaults", "turn": int(_DEFAULTS.match(line["text"]).group("turn")), "text": "defaults",
                          "by": "owner", "quote": _clean(line["item"])})
    return found


def _unbased(root: Path, task: str) -> list[str]:
    """The `[assumed]` direction items with no `Basis:`, as written (short), which never count."""
    return [" ".join(ln["item"].split())[:60] for ln in _lines(root, task) if ln["tag"] == "assumed" and not ln["basis"]]


# ---------------------------------------------------------------- what is owed

def _open(root: Path, task: str, env: Mapping[str, str]) -> list[dict[str, Any]]:
    return [i for i in items(root, task, env) if i["state"] == "open"]


def asked(root: Path, task: str, env: Mapping[str, str] = os.environ) -> list[str]:
    """The ids the next direction message has to name: before the `diverge` seal every open style, kit, object, and
    signature item; after it, `Pick` while the pick is missing, and the open signature items of the picked rough (of every
    rough while none is picked) and of the proposal."""
    found = _open(root, task, env)
    if diverge.sealed(root, task) is None:
        return [i["id"] for i in found]
    chosen = pick(root, task, env)
    ids = [PICK_ID] if chosen is None else []
    for i in found:
        if i["kind"] != "G" or i["candidate"] is None or chosen is None or i["candidate"] == chosen["candidate"]:
            ids.append(i["id"])
    return ids


def owed(root: Path, task: str, phase: int, env: Mapping[str, str] = os.environ) -> str | None:
    """What the `owner-direction` step says at turn `phase` (1 before `diverge`, 2 after), or None when that turn has
    nothing owed. Turn 1: the proposal is missing or fails its checks, or a style, kit, or object item is open. Turn 2
    (only once `diverge` is sealed): the pick is missing or names a rough the set does not have, or a signature item of the
    picked rough is open."""
    unattended = _env_unattended(env)
    if phase == 1:
        if problem := proposal_problem(root, task):
            return _why(task, 1, f"the proposal is not in order: {problem}", unattended)
        if found := [i for i in _open(root, task, env) if i["kind"] in "SKO"]:
            return _why(task, 1, f"{len(found)} items have no owner answer: {_names(found)}", unattended,
                        _unbased(root, task))
        return None
    seal = diverge.sealed(root, task)
    if seal is None:
        return None
    chosen = pick(root, task, env)
    if chosen is None:
        return _why(task, 2, "no `Pick:` of the owner stands for the rough set as it is sealed now", unattended,
                    _unbased(root, task))
    if chosen["candidate"] not in seal["candidates"]:
        return _why(task, 2, f"`Pick: {chosen['candidate']}` names no rough of the set ({', '.join(seal['candidates'])})",
                    unattended)
    if found := [i for i in _open(root, task, env) if i["candidate"] == chosen["candidate"]]:
        return _why(task, 2, f"the picked rough {chosen['candidate']} has signature items without an owner answer: "
                    f"{_names(found)}", unattended, _unbased(root, task))
    return None


def _names(found: list[dict[str, Any]], limit: int = 6) -> str:
    shown = ", ".join(f"{i['id']} {i['label']}" for i in found[:limit])
    return shown + (f", and {len(found) - limit} more" if len(found) > limit else "")


def _why(task: str, phase: int, reason: str, unattended: bool, unbased: list[str] | None = None) -> str:
    proposal_file = path(Path("."), task).as_posix()
    answers = waiting.answers_path(Path("."), task).as_posix()
    questions = waiting.questions_path(Path("."), task).as_posix()
    guide = "the lapis skill's direction-conversation.md"
    turn = f"## Direction <n>"
    if unattended:
        how = (f"Nobody can be asked, so decide for the owner and say so: under `{turn}` in {answers}, one item per open id, "
               "`- [assumed] <id> <name>: <choice> — Basis: <why this choice, from the brief and the references>`"
               + (" and `- [assumed] Pick: C<n> — Basis: <why>`" if phase == 2 else "")
               + ". Nothing waits, and the owner block at `done` lists these as decisions made without the owner.")
    else:
        how = (f"Ask the owner in one message in {questions}, with `lapis-questions: direction` on its first line, naming "
               "every open item id and attaching "
               + (f"the contact sheet `.lapis/state/diverge/{task}/contact.png`" if phase == 2 else
                  f"the reference sheet (`lapis-design references sheet --task {task}`)")
               + ", and stop with it as your last message; no fixed number of turns, but each turn needs an open item. "
               f"Record the answers in {answers} under `{turn}` as `- [declared] <id> <name>: <choice> — \"<their words>\"`"
               + (", the pick as `- [declared] Pick: C<n> — \"<their words>\"`, " if phase == 2 else ", ")
               + "or one untagged `- Defaults accepted (direction <n>): \"<their words>\"` line when they take every default.")
    if phase == 1:
        what = (f"Write the proposal {proposal_file} (shared/direction/schema.yaml) from the owner's own words, the brief, and "
                "the references: for each named style what it should DO here (two or three jobs) and the trend-kit items "
                "it decodes to, for each core object two or three representations, and for each signature element the "
                "brief names what it carries. ")
    else:
        what = "The `diverge` set is sealed: show the owner the contact sheet and ask for the pick and the picked rough's signature items. "
    note = (f" ({len(unbased)} [assumed] items give no `Basis:` and do not count: {'; '.join(unbased[:2])})" if unbased else "")
    return (f"Direction conversation, turn {'one' if phase == 1 else 'two'}: {reason}{note}. {what}{how} Format and examples: {guide}.")


def step(task: str, reason: str) -> dict[str, Any]:
    return {"id": STEP, "why": reason, "command": None}


def questions_problem(root: Path, task: str, env: Mapping[str, str] = os.environ) -> str | None:
    """Why the `direction` questions file does not wait, or None when it does: at least one item must be open, and the
    file has to name every open item (`asked`)."""
    ids = asked(root, task, env)
    if not ids:
        return "no item of the direction conversation is open, so there is nothing to ask"
    text = waiting.question_text(_read(waiting.questions_path(root, task)))
    missing = [i for i in ids if not re.search(r"(?<![\w.])" + re.escape(i) + r"(?![\w])", text)]
    if missing:
        return f"it does not name the open items {', '.join(missing)}"
    return None


# ---------------------------------------------------------------- what the critic sees

def packet(root: Path, task: str) -> dict[str, Any]:
    """The `direction` section of the critic packet: each item with its label, option texts, the chosen option, and who
    decided it (no maker reason: a kit item's `why` is left out), the pick, and the picked rough's card and captures. The
    critic judges `O1: a,c` against the option texts, not against bare letters. An `[assumed]` answer with its `Basis:`
    is listed (`by: assumed`) whatever the environment, so the packet's bytes do not depend on it."""
    env = {gate.ENV: "1"}
    listed = [{"id": i["id"], "label": i["label"], "state": i["state"], "by": i["by"], "choice": i["choice"],
               "options": [{k: v for k, v in o.items() if k in ("id", "text", "does")} for o in i["options"]]}
              for i in items(root, task, env)]
    chosen = pick(root, task, env)
    seal = diverge.sealed(root, task)
    found: dict[str, Any] | None = None
    if chosen and seal and chosen["candidate"] in seal["candidates"]:
        row = seal["candidates"][chosen["candidate"]]
        card = diverge.card(root, task, chosen["candidate"]) or {}
        found = {"candidate": chosen["candidate"], "by": chosen["by"], "card": card,
                 "captures": [c["path"] for c in (row.get("captures") or {}).values() if isinstance(c, dict) and "path" in c]}
    contact = (seal or {}).get("contact")
    return {"items": listed, "pick": found,
            "contact": contact["path"] if isinstance(contact, dict) and isinstance(contact.get("path"), str) else None}
