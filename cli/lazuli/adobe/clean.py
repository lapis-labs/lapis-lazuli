"""What lazuli keeps of a connector result: a short list of fields, each cleaned, and nothing else.

A connector result is text from another party that ends up in the owner's cache and in an agent's context, so
every string is cleaned (escape sequences, control and format characters, markup characters, length) and every
field is taken by name; the connector's own guidance to the model (`instructions`), group descriptions and
links, and `preview_url` (its query carries the connector's key) are never kept. A value that is not the
expected kind is dropped rather than repaired. No font file, table, or measurement is ever involved: these are
names and catalog facts.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

MAX_ROWS = 100
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-_]")
_MARKUP = re.compile(r"[<>`]")
_DROPPED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})
POSTSCRIPT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+~-]{0,126}")
FONT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}")
LANGUAGE = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3}")
AXIS = re.compile(r"[A-Za-z0-9]{4}")
DETAIL_URL = re.compile(r"https://fonts\.adobe\.com/fonts/[a-z0-9][a-z0-9-]{0,80}")
KIT_ID = re.compile(r"[a-z0-9]{3,16}")
KIT_CSS = re.compile(r"https://use\.typekit\.net/[a-z0-9]{3,16}\.css")
ERROR_CODE = re.compile(r"[a-z_]{3,40}")
SLANTS = ("normal", "italic", "oblique")


def text(value: Any, limit: int = 120) -> str | None:
    """`value` as one clean line of at most `limit` characters, or None when it is no string or nothing is left."""
    if not isinstance(value, str):
        return None
    value = _MARKUP.sub("", _ANSI.sub("", unicodedata.normalize("NFC", value)))
    value = "".join(" " if ch in "\t\n\r\x0b\x0c" or unicodedata.category(ch) == "Zs" else ch
                    for ch in value if unicodedata.category(ch) not in _DROPPED_CATEGORIES or ch in "\t\n\r\x0b\x0c")
    value = " ".join(value.split())
    if not value:
        return None
    return value if len(value) <= limit else value[:limit - 1].rstrip() + "…"


def _match(pattern: re.Pattern[str], value: Any) -> str | None:
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def _flag(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _count(value: Any, low: int, high: int) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high else None


def _strings(value: Any, limit: int, each: int = 80) -> list[str]:
    if not isinstance(value, list):
        return []
    return [t for item in value[:limit] if (t := text(item, each))]


def _drop_empty(row: dict) -> dict:
    return {k: v for k, v in row.items() if v not in (None, [], {}, "")}


def identity(row: dict) -> tuple[str | None, str | None]:
    """(PostScript name, font id) of a result row, in whichever of the connector's shapes it came."""
    ident = row.get("font_identifier") if isinstance(row.get("font_identifier"), dict) else {}
    ps = _match(POSTSCRIPT, ident.get("postscript_name") or row.get("postscript_name"))
    font_id = _match(FONT_ID, ident.get("font_id") or row.get("font_id") or row.get("fontId"))
    return ps, font_id


def font(row: Any) -> dict | None:
    """One font row as kept: names, makers, the catalog's own language list, weight, tier, and its page. None when
    the row names no font (no PostScript name and no family)."""
    if not isinstance(row, dict):
        return None
    ps, font_id = identity(row)
    lib = row.get("library_availability") if isinstance(row.get("library_availability"), dict) else {}
    slant = row.get("style") if row.get("style") in SLANTS else None
    kept = _drop_empty({
        "postscript_name": ps, "font_id": font_id,
        "family": text(row.get("family_name") or row.get("familyName"), 80),
        "style": text(row.get("style_name") or row.get("styleName"), 60),
        "full_name": text(row.get("full_name") or row.get("label"), 100),
        "designers": _strings(row.get("designers"), 8),
        "foundry": text(row.get("foundry"), 80),
        "url": _match(DETAIL_URL, row.get("detail_url") or row.get("detailUrl")),
        "languages": [t for t in _strings(row.get("language_support"), 80, 20) if LANGUAGE.fullmatch(t)],
        "weight": _count(row.get("weight"), 1, 1000),
        "slant": slant,
        "library": _drop_empty({k: _flag(lib.get(k)) for k in ("full", "trial") if _flag(lib.get(k)) is not None}),
        "variable": _flag(row.get("is_variable_font") if "is_variable_font" in row else row.get("isVariableFont")),
        "axes": [a for a in _strings(row.get("axes"), 12, 8) if AXIS.fullmatch(a)],
        "premium": _flag(row.get("isPremium")),
    })
    return kept if ps or kept.get("family") else None


def fonts(rows: Any) -> list[dict]:
    """The font rows of a result list, nested groups flattened (a group's name is kept as `group`)."""
    out: list[dict] = []

    def walk(items: Any, group: str | None) -> None:
        for row in items[:MAX_ROWS] if isinstance(items, list) else ():
            if len(out) >= MAX_ROWS or not isinstance(row, dict):
                continue
            if isinstance(row.get("results"), list) and "font_identifier" not in row and "postscript_name" not in row:
                walk(row["results"], text(row.get("name"), 60) or group)
            elif kept := font(row):
                out.append({**kept, "group": group} if group else kept)

    walk(rows, None)
    return out


def failure(payload: Any) -> tuple[str, str] | None:
    """(error code, message) when a result is the connector's business-error envelope, else None."""
    if isinstance(payload, dict) and payload.get("error_code") and "results" not in payload and "success" not in payload:
        code = _match(ERROR_CODE, payload.get("error_code")) or "error"
        return code, text(payload.get("user_message") or payload.get("error"), 300) or "no message"
    return None


def _entry_error(row: dict) -> dict:
    return _drop_empty({"error": _match(ERROR_CODE, row.get("error_code")) or "error",
                        "message": text(row.get("user_message"), 200)})


def _requested(row: dict) -> str | None:
    req = row.get("requested") if isinstance(row.get("requested"), dict) else {}
    return _match(POSTSCRIPT, req.get("postscript_name") or row.get("postscript_name"))


def search(payload: dict) -> dict:
    total = payload.get("total")
    return _drop_empty({"total": _count(total, 0, 10**9), "fonts": fonts(payload.get("results"))})


def similar(payload: dict) -> dict:
    seeds = []
    for row in (payload.get("results") if isinstance(payload.get("results"), list) else [])[:20]:
        if isinstance(row, dict):
            seeds.append(_drop_empty({"seed": _requested(row), **(_entry_error(row) if row.get("error_code") else {}),
                                      "fonts": fonts(row.get("similar_fonts"))}))
    return {"seeds": seeds}


def details(payload: dict) -> dict:
    out = []
    for row in (payload.get("results") if isinstance(payload.get("results"), list) else [])[:MAX_ROWS]:
        if not isinstance(row, dict):
            continue
        if row.get("error_code"):
            out.append(_drop_empty({"postscript_name": _requested(row), **_entry_error(row)}))
        elif kept := font(row):
            out.append(kept)
    return {"fonts": out}


def styles(payload: dict) -> dict:
    out = []
    for row in (payload.get("results") if isinstance(payload.get("results"), list) else [])[:20]:
        if not isinstance(row, dict):
            continue
        if row.get("error_code"):
            out.append(_drop_empty({"postscript_name": _requested(row), **_entry_error(row)}))
            continue
        fam = row.get("family") if isinstance(row.get("family"), dict) else {}
        family = _drop_empty({
            "family": text(fam.get("name"), 80), "foundry": text(fam.get("foundry"), 80),
            "designers": _strings(fam.get("designers"), 8), "url": _match(DETAIL_URL, fam.get("detail_url")),
            "languages": [t for t in _strings(fam.get("language_support"), 80, 20) if LANGUAGE.fullmatch(t)]})
        rows = [s for s in (font({**r, "family_name": fam.get("name")}) for r in (row.get("styles") or [])[:MAX_ROWS]
                            if isinstance(r, dict)) if s]
        out.append(_drop_empty({"requested": _requested(row), **family, "styles": rows}))
    return {"families": out}


def preview(payload: dict) -> dict:
    return {"cards": [c for c in (font(r) for r in (payload.get("cards") or [])[:10] if isinstance(r, dict)) if c]}


def action(payload: dict) -> dict:
    """The outcome of `activate`: whether it worked, the connector's error code, and its message."""
    return _drop_empty({"success": _flag(payload.get("success")),
                        "error_code": _match(ERROR_CODE, payload.get("error_code")),
                        "message": text(payload.get("user_message"), 300)})


def kit(payload: dict) -> dict:
    """The outcome of `create_kit`: the kit's id, name, domains, family names and CSS address (never the embed
    markup), or the fonts that were refused."""
    out = action(payload)
    found = payload.get("kit") if isinstance(payload.get("kit"), dict) else None
    if found:
        css = _match(KIT_CSS, next((m.group(0) for m in KIT_CSS.finditer(str(found.get("css_embed_code") or ""))), None))
        fams = found.get("families") if isinstance(found.get("families"), list) else []
        out["kit"] = _drop_empty({
            "id": _match(KIT_ID, found.get("id")), "name": text(found.get("name"), 80),
            "domains": _strings(found.get("domains"), 10, 100),
            "families": [t for f in fams[:20] if (t := text(f.get("name") if isinstance(f, dict) else f, 80))],
            "css_url": css})
    failed = payload.get("failures") if isinstance(payload.get("failures"), list) else []
    out["failures"] = [_drop_empty({"postscript_name": _match(POSTSCRIPT, f.get("postscript_name")),
                                    "reason": _match(ERROR_CODE, f.get("reason"))})
                       for f in failed[:10] if isinstance(f, dict)]
    return _drop_empty(out)


NORMALIZERS = {"search": search, "similar": similar, "details": details, "styles": styles, "preview": preview,
               "activate": action, "create_kit": kit}
