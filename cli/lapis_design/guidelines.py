"""Design guidelines: the behavior checklists in `shared/guidelines/`, the plan's `brief.guidelines`, and what follows from them.

A plan names the guidelines its work follows (`brief.guidelines`: the guideline, the platforms it covers, whether the owner
wants its look followed, consulted, or left, and the route its documents were read by). The behavior layer of each is a
checklist in our own words (`shared/guidelines/<id>.yaml`, `guideline.schema.yaml`); the visual layer is the owner's choice
and has no checklist. This module reads the files and answers four questions for the rest of the CLI:

- `suggest(brief)`: which guidelines the brief's platform, locale, and words call for (the defaults `plan check` offers);
- `rows(plan)`: the checklist items of the plan's guidelines as requirement rows from a lapis source (`requirements.py`
  keeps them next to the owner's rows, and the critic judges each);
- `rule_items(plan)`: which existing lint rules measure which item, so a finding of such a rule names the item;
- `css_px(value, unit)`: a threshold's length in CSS px by the mapping in `shared/guidelines/units.yaml`.

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

# What names a guideline in the owner's words. Narrow on purpose: a bare "material" or "seed" is not a guideline.
_ALIASES = {
    "apple-hig": (r"\bhuman interface guidelines?\b", r"\bapple\s+hig\b", r"\bhig\b", r"휴먼\s*인터페이스\s*가이드라인"),
    "material-3": (r"\bmaterial\s*(?:3|design|you)\b", r"머티리얼\s*디자인"),
    "fluent-2": (r"\bfluent\s*(?:2|design|ui)\b", r"플루언트"),
    "krds": (r"\bkrds\b", r"범정부\s*ui\s*/?\s*ux"),
    "wcag-2.2": (r"\bk?wcag\b", r"웹\s*접근성\s*지침"),
    "toss-tds": (r"\btds\b", r"\btoss\s+design\s+system\b", r"토스\s*(?:디자인\s*시스템|tds)"),
    "daangn-seed": (r"\bseed\s+design\b", r"\bdaangn\s+seed\b", r"당근\s*seed"),
}
_NAMED = {gid: re.compile("|".join(patterns), re.IGNORECASE) for gid, patterns in _ALIASES.items()}
_PUBLIC_SERVICE = re.compile(
    r"정부|공공|행정|민원|지자체|시청|구청|군청|도청|부처|\bgovernment\b|\bgov\b|public[\s-]service|public[\s-]sector|\bmunicipal|\bministry\b"
    r"|city\s+hall|civil\s+service|\.go\.kr", re.IGNORECASE)
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
    once, with the platforms of both entries). Each row: `id`, `guideline`, `item`, `text` (the requirement), `section`, `url`,
    `measure`, `platforms`, and, when the item has them, `rules`, `check`, `threshold`, `limits`, and `needs_review`."""
    found: dict[str, dict] = {}
    for entry in entries(plan):
        for item in applicable(entry):
            row = row_for(entry, item)
            if row["id"] in found:
                found[row["id"]]["platforms"] = sorted(set(found[row["id"]]["platforms"]) | set(row["platforms"]))
            else:
                found[row["id"]] = row
    return list(found.values())


def rule_items(plan: Any) -> dict[str, list[str]]:
    """Each lint rule id that measures a checklist item of the plan's guidelines, with the `<guideline>/<item>` names it measures."""
    found: dict[str, list[str]] = {}
    for row in rows(plan):
        for rule in row.get("rules") or ():
            found.setdefault(rule, []).append(item_ref(row["guideline"], row["item"]))
    return found


def checks(plan: Any, check: str) -> list[dict]:
    """The rows of the plan whose item runs the mechanical check `check`, with the items' own `viewports`."""
    out = []
    for entry in entries(plan):
        for item in applicable(entry):
            if item.get("check") == check:
                out.append({**row_for(entry, item), "viewports": item.get("viewports")})
    return out


def row_for(entry: dict, item: dict) -> dict:
    gid = entry["id"]
    row = {"id": row_id(gid, item["id"]), "guideline": gid, "item": item["id"], "text": item["requirement"],
           "section": item["source"]["section"], "url": item["source"]["url"], "measure": item["measure"],
           "platforms": sorted(set(entry.get("platforms") or ()) & set(item["platforms"]))}
    for key in ("rules", "check", "threshold", "limits", "needs_review"):
        if key in item:
            row[key] = item[key]
    return row


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
    """Whether the brief reads as a Korean public service: Korean among its locales and a word of government in what it says.
    `product_frame` has no value for it, so the words decide."""
    locales = [str(x).lower() for x in brief.get("locales") or ()]
    return any(x == "ko" or x.startswith("ko-") for x in locales) and bool(_PUBLIC_SERVICE.search(_words(brief)))


def suggest(brief: Any) -> tuple[list[dict], list[str]]:
    """The defaults the brief calls for, and the questions it leaves: (`[{id, platforms, why}]`, `[question]`).
    ios gives apple-hig, android material-3, web wcag-2.2 (always), desktop on Windows fluent-2, a Korean public service krds.
    A desktop whose operating system the brief does not name is a question, not a guess. `product_frame` is not a signal
    for any of them."""
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
                      "why": "the brief reads as a Korean public service: Korean locale and a word of government in its subject, job, audience, or constraints"})
    return found, questions


def named(text: str) -> list[str]:
    """The guidelines of `IDS` the words name, in `IDS` order."""
    return [gid for gid in IDS if _NAMED[gid].search(text)]


def default_entry(guideline: str, platforms: Iterable[str], basis: str = "suggested") -> dict:
    """An entry the plan can hold for a guideline of `IDS`, with the route this file was read by."""
    doc = load(guideline) or {}
    route = (doc.get("route") or {}).get("used") or {"kind": "official-docs", "ref": "?"}
    return {"id": guideline, "platforms": list(platforms), "basis": basis, "visual": DEFAULT_VISUAL if has_visual_layer(guideline) else "none",
            "route": {"kind": route["kind"], "ref": route["ref"]}}
