"""Design guidelines: the behavior checklists in `shared/guidelines/`, the plan's `brief.guidelines`, and what follows from them.

A plan names the guidelines its work follows (`brief.guidelines`: the guideline, the platforms it covers, whether the owner
wants its look followed, consulted, or left, and the route its documents are read by). The behavior layer of each is a
checklist in our own words (`shared/guidelines/<id>.yaml`, `guideline.schema.yaml`); the visual layer is the owner's choice
and has no checklist. This module reads the files and answers four questions for the rest of the CLI:

- `suggest(brief)`: which guidelines the brief's platform, locale, and product frame call for (the defaults `plan check` offers);
- `rows(plan)`: the checklist items of the plan's guidelines as requirement rows from a lapis source (`requirements.py`
  keeps them next to the owner's rows, and the critic judges each);
- `rule_items(plan)`: which existing lint rules measure which item, so a finding of such a rule names the item;
- `css_px(value, unit)`: a threshold's length in CSS px by the mapping in `shared/guidelines/units.yaml`;
- `route(guideline)`: where a maker reads the guideline's documents, Context7 with the recorded library id first and the
  official source when none is recorded.

Stdlib only until a file is read: the stop hook reaches `requirements`, which reaches this lazily.
"""
from __future__ import annotations

import functools
import hashlib
import re
from pathlib import Path
from typing import Any, Iterable

IDS = ("apple-hig", "material-3", "fluent-2", "krds", "wcag-2.2", "toss-tds", "daangn-seed")
PLAN_IDS = (*IDS, "other")
VISUAL = ("follow", "consult", "none")
DEFAULT_VISUAL = "consult"                  # an entry with no `visual` reads as this
ROW_PREFIX = "G:"                           # a guideline row's id is `G:<guideline>/<item>`
ROW_ID = re.compile(r"^G:[a-z0-9.-]+/[a-z0-9-]+$")
PUBLIC_SERVICE_FRAME = "public-service"     # the `brief.product_frame` the owner states outright for a public service

# What names a guideline in the owner's words. Narrow on purpose: a bare "material" or "seed" is not a guideline.
_ALIASES = {
    "apple-hig": (r"human interface guidelines?", r"apple\s+hig", r"hig", r"휴먼\s*인터페이스\s*가이드라인"),
    "material-3": (r"material\s*(?:3|design|you)", r"머티리얼\s*디자인"),
    "fluent-2": (r"fluent\s*(?:2|design|ui)", r"플루언트"),
    "krds": (r"krds", r"범정부\s*ui\s*/?\s*ux"),
    "wcag-2.2": (r"k?wcag", r"웹\s*접근성\s*지침"),
    "toss-tds": (r"tds", r"toss\s+design\s+system", r"토스\s*(?:디자인\s*시스템|tds)"),
    "daangn-seed": (r"seed\s+design", r"daangn\s+seed", r"당근\s*seed"),
}
# A name ends at a letter or digit of the Latin alphabet, not at Hangul: "KRDS를" names KRDS where `\b` would not see it.
_NAMED = {gid: re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(patterns) + r")(?![A-Za-z0-9])", re.IGNORECASE)
          for gid, patterns in _ALIASES.items()}
_OS = {"windows": re.compile(r"\bwindows\b|윈도우", re.IGNORECASE),
       "other": re.compile(r"\bmac(?:os)?\b|\blinux\b|\bubuntu\b|\bchromeos\b|맥\s*os|맥북|리눅스", re.IGNORECASE)}


def folder() -> Path:
    from lapis_design import shared_dir

    return shared_dir() / "guidelines"


@functools.lru_cache(maxsize=32)
def _parsed(path: str, mtime_ns: int) -> Any:
    import yaml

    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _file(name: str) -> Path:
    return folder() / name


def load(guideline: str) -> dict | None:
    """The parsed file of a guideline of `IDS`, or None for `other` and for a name that is no guideline. Do not change it."""
    if guideline not in IDS:
        return None
    path = _file(f"{guideline}.yaml")
    return _parsed(str(path), path.stat().st_mtime_ns)


def sha256(guideline: str) -> str | None:
    """The SHA-256 of the guideline file's bytes, or None when there is no such file."""
    if guideline not in IDS:
        return None
    try:
        return hashlib.sha256(_file(f"{guideline}.yaml").read_bytes()).hexdigest()
    except OSError:
        return None


def validate(doc: Any) -> list[str]:
    """The problems `guideline.schema.yaml` finds in a guideline file's content, and an item id used twice, which a schema cannot say."""
    import yaml
    from jsonschema import Draft202012Validator

    schema = yaml.safe_load(_file("guideline.schema.yaml").read_text(encoding="utf-8"))
    problems = [f"{'/'.join(map(str, e.absolute_path)) or 'it'}: {e.message}" for e in Draft202012Validator(schema).iter_errors(doc)]
    if not problems and isinstance(doc, dict):
        ids = [item["id"] for item in doc.get("items") or ()]
        problems += [f"item id {i} is used twice" for i in sorted({i for i in ids if ids.count(i) > 1})]
    return problems


def units() -> dict[str, dict]:
    """`units.yaml`: each unit of a threshold with its meaning and `css_px_per_unit` (None for a unit that is no length)."""
    path = _file("units.yaml")
    return _parsed(str(path), path.stat().st_mtime_ns)["units"]


def css_px(value: float, unit: str) -> float | None:
    """`value` of `unit` in CSS px by the stated mapping, or None when the unit is no length (percent, count) or unknown. Never a guess."""
    factor = (units().get(unit) or {}).get("css_px_per_unit")
    return None if factor is None else value * factor


def plain_name(guideline: str, entry: dict | None = None) -> str:
    """How a question to the owner names the guideline."""
    doc = load(guideline)
    if doc:
        return doc["short_name"]
    return str((entry or {}).get("name") or guideline)


def has_visual_layer(guideline: str) -> bool:
    """Whether the owner is asked how closely the look follows it (`other` always is)."""
    doc = load(guideline)
    return True if doc is None else bool(doc["visual_layer"])


# ---------------------------------------------------------------- the plan's entries

def entries(plan: Any) -> list[dict]:
    """The plan's `brief.guidelines` entries that are mappings, in order."""
    brief = plan.get("brief") if isinstance(plan, dict) else None
    found = brief.get("guidelines") if isinstance(brief, dict) else None
    return [e for e in found or () if isinstance(e, dict)]


def visual_of(entry: dict) -> str:
    return entry.get("visual") if entry.get("visual") in VISUAL else DEFAULT_VISUAL


def item_ref(guideline: str, item: str) -> str:
    """The name a finding or a report gives an item: `<guideline>/<item>`."""
    return f"{guideline}/{item}"


def row_id(guideline: str, item: str) -> str:
    return ROW_PREFIX + item_ref(guideline, item)


def applicable(entry: dict) -> list[dict]:
    """The checklist items of the guideline the entry names that apply to the platforms it covers, in file order."""
    doc = load(str(entry.get("id")))
    if not doc or doc["kind"] != "checklist":
        return []
    covered = set(entry.get("platforms") or ())
    return [item for item in doc["items"] if covered & set(item["platforms"])]


def rows(plan: Any) -> list[dict]:
    """The requirement rows the plan's guidelines give, one per applicable checklist item (a guideline named twice gives each item
    once, with the platforms of both entries). A row is `{id, text, section, guideline}`: `text` is the item's requirement,
    `section` the source's section name, and `guideline` holds `id`, `item`, `url`, `measure`, `platforms`, and, when the item
    has them, `rules`, `check`, `threshold`, `limits`, and `needs_review`."""
    found: dict[str, dict] = {}
    for entry in entries(plan):
        for item in applicable(entry):
            row = row_for(entry, item)
            if row["id"] in found:
                held = found[row["id"]]["guideline"]
                held["platforms"] = sorted(set(held["platforms"]) | set(row["guideline"]["platforms"]))
            else:
                found[row["id"]] = row
    return list(found.values())


def row_for(entry: dict, item: dict) -> dict:
    gid = entry["id"]
    detail: dict[str, Any] = {"id": gid, "item": item["id"], "url": item["source"]["url"], "measure": item["measure"],
                              "platforms": sorted(set(entry.get("platforms") or ()) & set(item["platforms"]))}
    for key in ("rules", "check", "threshold", "limits", "needs_review"):
        if key in item:
            detail[key] = item[key]
    return {"id": row_id(gid, item["id"]), "text": item["requirement"], "section": item["source"]["section"], "guideline": detail}


def rule_items(plan: Any) -> dict[str, list[str]]:
    """Each lint rule id that measures a checklist item of the plan's guidelines, with the `<guideline>/<item>` names it measures."""
    found: dict[str, list[str]] = {}
    for row in rows(plan):
        detail = row["guideline"]
        for rule in detail.get("rules") or ():
            found.setdefault(rule, []).append(item_ref(detail["id"], detail["item"]))
    return found


def checks(plan: Any, check: str) -> list[dict]:
    """The items of the plan's guidelines that run the mechanical check `check`, as `{ref, text, threshold, platforms, viewports}`
    (`viewports` is None for every layout capture)."""
    out: dict[str, dict] = {}
    for entry in entries(plan):
        for item in applicable(entry):
            if item.get("check") != check:
                continue
            ref = item_ref(entry["id"], item["id"])
            platforms = sorted(set(entry.get("platforms") or ()) & set(item["platforms"]))
            if ref in out:
                out[ref]["platforms"] = sorted(set(out[ref]["platforms"]) | set(platforms))
            else:
                out[ref] = {"ref": ref, "text": item["requirement"], "threshold": item["threshold"], "platforms": platforms,
                            "viewports": item.get("viewports"), "limits": item.get("limits")}
    return list(out.values())


# ---------------------------------------------------------------- what the brief calls for

def _words(brief: dict) -> str:
    parts = [str(brief.get(k) or "") for k in ("subject", "one_job", "audience")]
    parts += [str(c) for c in brief.get("constraints") or ()]
    return "\n".join(parts)


def desktop_os(brief: dict) -> str | None:
    """`windows` or `other` when the brief's words name a desktop operating system, else None (not known)."""
    text = _words(brief)
    for name, pattern in _OS.items():
        if pattern.search(text):
            return name
    return None


def public_service(brief: dict) -> bool:
    """Whether the owner said this is a public service (`brief.product_frame`) and Korean is among the brief's locales. KRDS is
    the Korean government's system, so a public service in another language alone is not taken to be Korean: no words are guessed."""
    locales = [str(x).lower() for x in brief.get("locales") or ()]
    return brief.get("product_frame") == PUBLIC_SERVICE_FRAME and any(x == "ko" or x.startswith("ko-") for x in locales)


def suggest(brief: Any) -> tuple[list[dict], list[str]]:
    """The defaults the brief calls for, and the questions it leaves: (`[{id, platforms, why}]`, `[question]`).
    ios gives apple-hig, android material-3, web wcag-2.2 (always), desktop on Windows fluent-2, the `public-service` product
    frame with a Korean locale krds. A desktop whose operating system the brief does not name is a question, not a guess.
    No other product frame is a signal, and no word of the brief says public service: the owner states the frame."""
    if not isinstance(brief, dict):
        return [], []
    platform = [p for p in brief.get("platform") or () if isinstance(p, str)]
    found: list[dict] = []
    questions: list[str] = []
    if "ios" in platform:
        found.append({"id": "apple-hig", "platforms": ["ios"], "why": "the brief's platform includes ios"})
    if "android" in platform:
        found.append({"id": "material-3", "platforms": ["android"], "why": "the brief's platform includes android"})
    if "desktop" in platform:
        os_name = desktop_os(brief)
        if os_name == "windows":
            found.append({"id": "fluent-2", "platforms": ["desktop"], "why": "the brief's platform includes desktop and its words name Windows"})
        elif os_name is None:
            questions.append("Which desktop operating system is this for? A Windows app follows Fluent 2 and the Windows design "
                             "documents; for another system no guideline here applies, and the plan says which it follows.")
    if "web" in platform:
        found.append({"id": "wcag-2.2", "platforms": ["web"], "why": "the brief's platform includes web, and WCAG 2.2 is always the floor there"})
    if public_service(brief):
        covered = [p for p in platform if p in ("web", "ios", "android")] or ["web"]
        found.append({"id": "krds", "platforms": ["web"] if "web" in covered else covered,
                      "why": "the brief's product frame is public-service and its locales include Korean"})
    return found, questions


def named(text: str) -> list[str]:
    """The guidelines of `IDS` the words name, in `IDS` order."""
    return [gid for gid in IDS if _NAMED[gid].search(text)]


def route(guideline: str) -> dict:
    """Where a maker reads the guideline's documents, as the plan's `route` entry (`{kind, ref}`): Context7 with its library id
    when the file records one, else the official source. No file for the name gives `{kind: official-docs, ref: "?"}`."""
    doc = load(guideline)
    if not doc:
        return {"kind": "official-docs", "ref": "?"}
    context7 = doc["route"].get("context7")
    if context7:
        return {"kind": "context7", "ref": context7["library_id"]}
    official = doc["route"]["official"]
    return {"kind": official["kind"], "ref": official["ref"]}


def default_entry(guideline: str, platforms: Iterable[str], basis: str = "suggested") -> dict:
    """An entry the plan can hold for a guideline of `IDS`, with the route a maker reads its documents by."""
    return {"id": guideline, "platforms": list(platforms), "basis": basis, "visual": DEFAULT_VISUAL if has_visual_layer(guideline) else "none",
            "route": route(guideline)}
