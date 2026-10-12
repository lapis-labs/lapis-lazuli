"""`lazuli adobe`: ask the Adobe Fonts connector of the owner's own Codex for names, and keep what it says apart.

Read commands (each one relay call, one connector tool; results are cleaned and stored in the user cache with
provenance `adobe-connector`, never in the lazuli database):
  search    a name (`--name`), or filters: styles, moods, topics, script, language, text hierarchy, group, foundry
  similar   fonts like the PostScript names given (the best way to find neighbours), optionally covering a language
  details   language support, weight, library tier, makers, page, for PostScript names
  styles    every style of the family of each PostScript name
  preview   the connector's specimen cards (metadata only; no image comes back)
Guarded actions (each names one connector tool and its exact arguments, and refuses without the owner's words):
  activate  add one font to the owner's Creative Cloud library: --font PS --basis "<owner's words>" --task T
  kit       publish a web kit: --fonts PS ... --domains HOST ... --basis "<owner's words>" --task T
Setup: `status`, `enable` (the owner, at a terminal), `disable`.

Off until the owner runs `lazuli adobe enable`. What comes back is names and the catalog's own facts, labeled
as such; it never feeds measurement, calibration, evaluation, or a catalog label (`lazuli.adobe` docstring).
Exit codes: 0 done; 1 the call gave no result, or the stream did not show exactly the call asked for; 2 usage,
the relay is off, or the owner's words are missing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from lazuli import owned
from lazuli.adobe import PROVENANCE, clean, config, consent, relay, store

RUNNER = relay.run_codex
LIMIT_MAX = 50
FONTS_MAX = {"similar": 5, "details": 10, "styles": 10, "preview": 10, "kit": 10}
SORTS = ("relevance", "name", "newest")
_SCRIPTS = re.compile(r"[a-z]{4}(?:,[a-z]{4})*")
_LANGS = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3}(?:,[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3})*")
_LOCALE = re.compile(r"[a-z]{2}(?:[_-][A-Z]{2})?")
_DOMAIN = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?(?::[0-9]{1,5})?")


class UsageError(ValueError):
    pass


# ---------------------------------------------------------------- arguments

def _free(label: str, value: str | None, limit: int = 150) -> str | None:
    if value is None:
        return None
    kept = clean.text(value, limit)
    if kept is None or kept != " ".join(value.split()):
        raise UsageError(f"{label} must be plain text of at most {limit} characters (no control or markup characters)")
    return kept


def _postscript(name: str) -> str:
    if not clean.POSTSCRIPT.fullmatch(name):
        raise UsageError(f"{name!r} is not a PostScript name (for example FuturaPT-Book). Find the name of a family with "
                         "`lazuli adobe search --name \"Futura PT\"`, or read it with `lazuli local fonts --json --family`")
    return name


def _fonts(names: list[str], tool: str) -> list[dict]:
    flat = [part for name in names for part in name.split(",") if part]
    if not flat:
        raise UsageError("give at least one PostScript name")
    if len(flat) > FONTS_MAX[tool]:
        raise UsageError(f"at most {FONTS_MAX[tool]} fonts per `{tool}` call (each call takes ten seconds and a long prompt)")
    return [{"postscript_name": _postscript(n)} for n in dict.fromkeys(flat)]


def _locale(value: str | None) -> str | None:
    if value is not None and not _LOCALE.fullmatch(value):
        raise UsageError("--locale takes a locale such as en_US or ko_KR")
    return value


def _languages(value: str | None) -> list[str] | None:
    if value is None:
        return None
    if not _LANGS.fullmatch(value):
        raise UsageError("--lang takes language tags separated by commas, such as ko or ja,zh-Hans")
    return value.split(",")


def _limit(value: int) -> int:
    if not 1 <= value <= LIMIT_MAX:
        raise UsageError(f"--limit takes 1 to {LIMIT_MAX}")
    return value


def _put(args: dict, **pairs) -> dict:
    args.update({k: v for k, v in pairs.items() if v is not None})
    return args


def search_arguments(ns: argparse.Namespace) -> dict:
    if ns.name and not ns.query:
        raise UsageError("--name says the query is a font name; give the name as QUERY")
    if ns.script is not None and not _SCRIPTS.fullmatch(ns.script):
        raise UsageError("--script takes four-letter ISO 15924 codes separated by commas, such as latn or hang,hani")
    filters = (ns.query, ns.styles, ns.moods, ns.topics, ns.doc_type, ns.hierarchy, ns.group, ns.script, ns.lang,
               ns.foundry, ns.designer)
    if not any(filters):
        raise UsageError("give QUERY or at least one filter")
    args: dict = {}
    _put(args, user_query=_free("QUERY", ns.query), font_query=True if ns.name else None,
         styles=_free("--styles", ns.styles), moods=_free("--moods", ns.moods), topics=_free("--topics", ns.topics),
         doc_type=_free("--doc-type", ns.doc_type), text_hierarchy=ns.hierarchy, font_group=_free("--group", ns.group),
         writing_systems=ns.script, supported_languages=_languages(ns.lang), foundry=_free("--foundry", ns.foundry),
         designers=_free("--designer", ns.designer), exclude_variable_fonts=True if ns.exclude_variable else None,
         sort=ns.sort, page=ns.page if ns.page and ns.page > 1 else None, per_page=_limit(ns.limit),
         library=ns.library, locale=_locale(ns.locale))
    return args


def similar_arguments(ns: argparse.Namespace) -> dict:
    return _put({"font_identifiers": _fonts(ns.font, "similar")}, per_page=_limit(ns.limit),
                supported_languages=_languages(ns.lang), exclude_variable_fonts=True if ns.exclude_variable else None,
                library=ns.library, locale=_locale(ns.locale))


def listed_arguments(tool: str):
    def build(ns: argparse.Namespace) -> dict:
        return _put({"font_identifiers": _fonts(ns.font, tool)}, locale=_locale(ns.locale))
    return build


# ---------------------------------------------------------------- text output

def _list(items: list[str], limit: int) -> str:
    return ", ".join(items[:limit]) + (f", +{len(items) - limit}" if len(items) > limit else "")


def _tiers(font: dict) -> str:
    lib = font.get("library") or {}
    return ", ".join(f"{k}: {'yes' if lib[k] else 'no'}" for k in ("full", "trial") if k in lib)


def _families(fonts: list[dict]) -> list[dict]:
    """Rows with a family name grouped by family in first-seen order; the rest are names only."""
    grouped: dict[str, dict] = {}
    for f in fonts:
        if f.get("family"):
            g = grouped.setdefault(f["family"], {"family": f["family"], "rows": []})
            g["rows"].append(f)
    return list(grouped.values())


def _family_line(g: dict) -> str:
    rows = g["rows"]
    first = rows[0]
    parts = [g["family"]]
    if first.get("foundry"):
        parts.append(first["foundry"])
    designers = next((r["designers"] for r in rows if r.get("designers")), [])
    if designers:
        parts.append(_list(designers, 3))
    styles = [r["style"] for r in rows if r.get("style")]
    if styles:
        parts.append("styles " + _list(styles, 6))
    ps = next((r["postscript_name"] for r in rows if r.get("postscript_name")), None)
    if ps:
        parts.append("PS " + ps)
    tiers = next((_tiers(r) for r in rows if r.get("library")), "")
    if tiers:
        parts.append(tiers)
    if first.get("url"):
        parts.append(first["url"])
    return " · ".join(parts)


def _font_rows(fonts: list[dict], indent: str = "") -> list[str]:
    lines = []
    for i, g in enumerate(_families(fonts), 1):
        lines.append(f"{indent}{i:2}. {_family_line(g)}")
    bare = [f["postscript_name"] for f in fonts if not f.get("family") and f.get("postscript_name")]
    if bare:
        lines.append(f"{indent}    names only, no metadata (run `lazuli adobe details`): {_list(bare, 12)}")
    return lines


def _detail_line(f: dict) -> str:
    if "error" in f:
        return f"  {f.get('postscript_name', '?')}: {f['error']}" + (f" ({f['message']})" if f.get("message") else "")
    parts = [f.get("postscript_name") or "?", f.get("full_name") or " ".join(x for x in (f.get("family"), f.get("style")) if x)]
    for key, label in (("foundry", ""), ("weight", "weight "), ("slant", "")):
        if f.get(key) is not None:
            parts.append(f"{label}{f[key]}")
    if "variable" in f:
        parts.append("variable" if f["variable"] else "static")
    if f.get("library"):
        parts.append(_tiers(f))
    if f.get("languages"):
        parts.append(f"{len(f['languages'])} languages: {_list(f['languages'], 12)}")
    if f.get("designers"):
        parts.append(_list(f["designers"], 4))
    if f.get("url"):
        parts.append(f["url"])
    return "  " + " · ".join(p for p in parts if p)


def render(tool: str, kept: dict) -> list[str]:
    if tool == "search":
        shown = len(kept.get("fonts", []))
        total = kept.get("total")
        fams = _families(kept.get("fonts", []))
        lines = [f"search: {shown} result rows" + (f" of {total} matches" if total is not None else "")
                 + f", {len(fams)} families named. `per_page` counts styles, so a family fills several rows"]
        return lines + _font_rows(kept.get("fonts", []))
    if tool == "similar":
        lines = []
        for seed in kept.get("seeds", []):
            if "error" in seed:
                lines.append(f"similar to {seed.get('seed', '?')}: {seed['error']}" + (f" ({seed['message']})" if seed.get("message") else ""))
                continue
            lines.append(f"similar to {seed.get('seed', '?')}: {len(seed.get('fonts', []))} fonts")
            lines += _font_rows(seed.get("fonts", []))
        return lines or ["similar: no seed came back"]
    if tool == "details":
        return [f"details: {len(kept.get('fonts', []))} fonts"] + [_detail_line(f) for f in kept.get("fonts", [])]
    if tool == "styles":
        lines = []
        for fam in kept.get("families", []):
            if "error" in fam:
                lines.append(_detail_line({"postscript_name": fam.get("postscript_name"), **fam}))
                continue
            head = " · ".join(x for x in (fam.get("family"), fam.get("foundry"), _list(fam.get("designers", []), 3),
                                          fam.get("url")) if x)
            lines.append(f"styles of {head} ({len(fam.get('styles', []))}; {len(fam.get('languages', []))} languages: "
                         f"{_list(fam.get('languages', []), 12)})")
            for s in fam.get("styles", []):
                lines.append("  " + " · ".join(x for x in (s.get("postscript_name"), s.get("style"),
                                                           f"weight {s['weight']}" if s.get("weight") else None, s.get("slant"),
                                                           "variable" if s.get("variable") else None, _tiers(s)) if x))
        return lines or ["styles: no family came back"]
    if tool == "preview":
        return [f"preview: {len(kept.get('cards', []))} cards (metadata only; this surface returns no image)"] + [
            "  " + " · ".join(x for x in (c.get("postscript_name"), c.get("full_name"),
                                          "premium" if c.get("premium") else None, c.get("url")) if x)
            for c in kept.get("cards", [])]
    return [json.dumps(kept, ensure_ascii=False)]


def _header(row: dict, stored: Path) -> str:
    tokens = row.get("tokens", {})
    cost = f", {tokens['input_tokens']} input tokens" if "input_tokens" in tokens else ""
    return (f"Adobe Fonts connector result ({PROVENANCE}; the catalog's own facts, not lazuli's measurement), "
            f"{row['fetched_at']}, {row['seconds']} s via {row['model']}{cost}; kept in {stored}")


# ---------------------------------------------------------------- commands

def _fail(message: str, code: int = 1) -> int:
    print(message, file=sys.stderr)
    return code


def run_read(tool: str, arguments: dict, as_json: bool, runner) -> int:
    try:
        config.require_enabled()
    except config.NotEnabled as exc:
        return _fail(str(exc), 2)
    try:
        outcome = relay.relay(tool, arguments, model=config.model(), runner=runner)
    except relay.RelayError as exc:
        return _fail(f"adobe {tool}: {exc}")
    if (bad := clean.failure(outcome.payload)):
        return _fail(f"adobe {tool}: the connector answered with an error ({bad[0]}): {bad[1]}")
    kept = clean.NORMALIZERS[tool](outcome.payload)
    row = store.save_record(outcome, kept)
    if as_json:
        json.dump({**row, "stored": str(store.records_path())}, sys.stdout, ensure_ascii=False, indent=1)
        print()
    else:
        print(_header(row, store.records_path()))
        print("\n".join(render(tool, kept)))
    return 0


def _kit_name_arg(value: str | None) -> str | None:
    return _free("--kit-name", value, 80)


def run_action(action: str, ns: argparse.Namespace, runner) -> int:
    """`activate` and `kit`: gate on the opt-in and the owner's words, make the one call, and report from the stream."""
    try:
        config.require_enabled()
    except config.NotEnabled as exc:
        return _fail(str(exc), 2)
    try:
        if action == "activate":
            names = [_postscript(ns.font)]
            domains: list[str] = []
            tool, arguments = "activate", {"font_identifier": {"postscript_name": names[0]}}
        else:
            names = [f["postscript_name"] for f in _fonts(ns.fonts, "kit")]
            domains = [d for d in (p for item in ns.domains for p in item.split(",")) if d]
            if not domains or len(domains) > 5 or not all(_DOMAIN.fullmatch(d) for d in domains):
                raise UsageError("--domains takes one to five bare host names in lower case, such as example.com or localhost:5173")
            tool = "create_kit"
            arguments = _put({"domains": list(dict.fromkeys(domains)), "font_identifiers": [{"postscript_name": n} for n in names]},
                             kit_name=_kit_name_arg(ns.kit_name))
    except UsageError as exc:
        return _fail(str(exc), 2)
    why = consent.problem(ns.basis, Path(ns.project), ns.task, names, domains)
    if why:
        return _fail(f"adobe {action} refused: {why}", 2)
    basis = " ".join(ns.basis.split())
    shown = json.dumps(arguments, ensure_ascii=False)
    try:
        outcome = relay.relay(tool, arguments, model=config.model(), runner=runner)
    except relay.Refused as exc:
        store.log_action({"action": action, "task": ns.task, "arguments": arguments, "basis": basis, "result": "refused-stream",
                          "detail": str(exc)})
        return _fail(f"adobe {action}: {exc}. The connector call may already have happened; check the owner's Adobe account "
                     "before running this again.")
    except relay.RelayError as exc:
        store.log_action({"action": action, "task": ns.task, "arguments": arguments, "basis": basis, "result": "no-result",
                          "detail": str(exc)})
        return _fail(f"adobe {action}: {exc}")
    kept = clean.NORMALIZERS[tool](outcome.payload)
    store.log_action({"action": action, "task": ns.task, "tool": relay.tool_name(tool), "calls_in_stream": 1,
                      "arguments": arguments, "basis": basis, "result": "done" if kept.get("success") else "failed",
                      "outcome": kept})
    if ns.json:
        json.dump({"provenance": PROVENANCE, "action": action, "tool": relay.tool_name(tool), "calls_in_stream": 1,
                   "arguments": arguments, "basis": basis, "outcome": kept}, sys.stdout, ensure_ascii=False, indent=1)
        print()
    else:
        print(f"{action}: the stream shows exactly one connector call, {relay.tool_name(tool)} {shown}")
        print(f"basis (the owner's words, found in the project's records): {basis!r}")
        print(("done: " if kept.get("success") else f"not done ({kept.get('error_code', 'no error code')}): ")
              + (kept.get("message") or "no message"))
        if (kit := kept.get("kit")):
            print("kit: " + " · ".join(x for x in (kit.get("id"), kit.get("name"), _list(kit.get("domains", []), 5),
                                                    kit.get("css_url")) if x))
        for f in kept.get("failures", []):
            print(f"  refused font {f.get('postscript_name')}: {f.get('reason')}")
        print(f"logged in {store.actions_path()}")
    return 0 if kept.get("success") else 1


def status_text() -> list[str]:
    settings = config.load()
    on = config.is_enabled()
    codex = relay.codex_binary()
    return [f"lazuli adobe: {'on' if on else 'off'}" + (f" since {settings['enabled_at']}" if on and settings.get("enabled_at") else ""),
            f"model: {config.model()}",
            f"codex: {codex or 'not found on PATH (set LAZULI_CODEX, or install the Codex CLI and sign in with the ChatGPT account whose Adobe app is connected)'}",
            f"records: {len(store.records())} in {store.records_path()}; actions: {len(store.actions())} in {store.actions_path()}",
            f"owned names: {len(owned.load())} (`lazuli owned list`)"]


def run_enable(ns: argparse.Namespace) -> int:
    try:
        model = config.check_model(ns.model) if ns.model else config.model()
    except ValueError as exc:
        return _fail(str(exc), 2)
    if not config.owner_present():
        return _fail("`lazuli adobe enable` needs a person at a terminal: it turns on a relay to the Adobe Fonts connector of "
                     f"your own account. {config.ENABLE_HOW} (an agent cannot answer for you).", 2)
    explain = ("This lets lazuli start your Codex CLI (read-only, no session kept) to call your Adobe Fonts connector: search, "
               "similar, details, styles, preview, and, only with your quoted words, activate and kit. Results are names and "
               "catalog facts, kept in the user cache; no font file or glyph data is read or sent. Each call costs about "
               "70,000 input tokens of your ChatGPT usage.")
    print(explain)
    if not config.owner_confirms("Turn it on?"):
        return _fail("not enabled", 2)
    config.enable(model)
    print("\n".join(status_text()))
    return 0


# ---------------------------------------------------------------- parser

def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="machine output")
    p.add_argument("--locale", metavar="LOCALE", help="language of the returned names, such as en_US or ko_KR")


def _filters(p: argparse.ArgumentParser) -> None:
    p.add_argument("--lang", metavar="TAGS", help="language tags every result must support, such as ko or ja")
    p.add_argument("--limit", type=int, default=10, help=f"results per call, 1 to {LIMIT_MAX} (default 10); search counts styles")
    p.add_argument("--exclude-variable", action="store_true", help="leave out variable fonts")
    p.add_argument("--library", choices=("full", "trial"), help="catalog tier (the connector clamps `full` to your plan)")


def _parser(prog: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog=prog, description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="verb", required=True)
    sub.add_parser("status", help="whether the relay is on, and what it needs")
    en = sub.add_parser("enable", help="turn the relay on (the owner, at a terminal)")
    en.add_argument("--model", help=f"the Codex model the relay asks for (default {config.DEFAULT_MODEL})")
    sub.add_parser("disable", help="turn the relay off")
    s = sub.add_parser("search", help="search the Adobe Fonts catalog by name or filters")
    s.add_argument("query", nargs="?", help="a font name with --name, else a description (at most 150 characters)")
    s.add_argument("--name", action="store_true", help="QUERY is a font or family name: a literal name search")
    s.add_argument("--styles")
    s.add_argument("--moods")
    s.add_argument("--topics")
    s.add_argument("--doc-type")
    s.add_argument("--hierarchy", choices=("heading", "body"))
    s.add_argument("--group", help="font group, such as 'Sans Serif' or 'Serif'")
    s.add_argument("--script", help="ISO 15924 codes the fonts must cover, such as latn, hang, jpan")
    s.add_argument("--foundry")
    s.add_argument("--designer")
    s.add_argument("--sort", choices=SORTS)
    s.add_argument("--page", type=int)
    _filters(s)
    _common(s)
    sim = sub.add_parser("similar", help="fonts like the given PostScript names")
    sim.add_argument("font", nargs="+", metavar="POSTSCRIPT_NAME")
    _filters(sim)
    _common(sim)
    for name, text in (("details", "language support, weight, tier, makers, and page of PostScript names"),
                       ("styles", "every style of the families of the PostScript names"),
                       ("preview", "specimen cards of the PostScript names (metadata only)")):
        p = sub.add_parser(name, help=text)
        p.add_argument("font", nargs="+", metavar="POSTSCRIPT_NAME")
        _common(p)
    for name, text in (("activate", "add one font to your Creative Cloud library (needs the owner's quoted words)"),
                       ("kit", "publish a web kit under your Adobe account (needs the owner's quoted words)")):
        p = sub.add_parser(name, help=text)
        if name == "activate":
            p.add_argument("--font", required=True, metavar="POSTSCRIPT_NAME")
        else:
            p.add_argument("--fonts", nargs="+", required=True, metavar="POSTSCRIPT_NAME")
            p.add_argument("--domains", nargs="+", required=True, metavar="HOST")
            p.add_argument("--kit-name")
        p.add_argument("--basis", help="the owner's words, quoted exactly as the project's records hold them")
        p.add_argument("--task", help="the run whose brief or requirement record holds those words")
        p.add_argument("--project", default=".", help="the project folder (default: here)")
        p.add_argument("--json", action="store_true")
    return ap


def main(argv: list[str] | None = None, prog: str = "lazuli adobe", runner=None) -> int:
    ns = _parser(prog).parse_args(sys.argv[1:] if argv is None else argv)
    run = runner or RUNNER
    if ns.verb == "status":
        print("\n".join(status_text()))
        return 0
    if ns.verb == "enable":
        return run_enable(ns)
    if ns.verb == "disable":
        config.disable()
        print("lazuli adobe: off")
        return 0
    if ns.verb in ("activate", "kit"):
        return run_action(ns.verb, ns, run)
    builders = {"search": search_arguments, "similar": similar_arguments, "details": listed_arguments("details"),
                "styles": listed_arguments("styles"), "preview": listed_arguments("preview")}
    try:
        arguments = builders[ns.verb](ns)
    except UsageError as exc:
        return _fail(str(exc), 2)
    return run_read(ns.verb, arguments, ns.json, run)


if __name__ == "__main__":
    sys.exit(main())
