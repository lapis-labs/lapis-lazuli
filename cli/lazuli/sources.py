"""`lazuli sources` and `lazuli search --type source`: the source registry (sources/registry.yaml).

The registry lists where people look for fonts, colors, assets, and design references, what each is
good for, and how lazuli may reach it: `adapter` (a catalog adapter collects it), `read` (`lazuli
read` may fetch a page the user asked for), `browser-link` (a link for the user only), or `refused`
(the terms forbid tools; `clause` cites them). `find(url)` is the lookup `lazuli read` uses before
it fetches anything.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from lapis_design import shared_dir

_SCHEMA = yaml.safe_load((shared_dir() / "sources" / "registry.schema.yaml").read_text(encoding="utf-8"))
TYPES = tuple(_SCHEMA["$defs"]["source"]["properties"]["type"]["items"]["enum"])
ACCESS = tuple(_SCHEMA["$defs"]["source"]["properties"]["access"]["enum"])
# When no entry's path covers a URL on a listed host, the host's strictest entry decides: terms cover
# the whole site, not the page the registry happens to link. An access value outside the schema counts
# as stricter than refused, so a bad entry fails closed.
_STRICTNESS = {"read": 0, "adapter": 1, "browser-link": 2, "refused": 3}
_UNKNOWN_STRICTNESS = max(_STRICTNESS.values()) + 1


class RegistryError(ValueError):
    """The registry file breaks its schema in a way lazuli cannot act on safely."""


def load_registry(path: Path | None = None) -> list[dict]:
    """Every registry entry in file order; read on each call (the file is small).

    Raises RegistryError when an entry's `access` is not one the schema allows, so no caller ever acts
    on a policy it does not know.
    """
    path = path or shared_dir() / "sources" / "registry.yaml"
    entries = yaml.safe_load(path.read_text(encoding="utf-8"))["sources"]
    if bad := [f"{e.get('id', '?')}: {e.get('access')!r}" for e in entries if e.get("access") not in ACCESS]:
        raise RegistryError(f"{path}: access must be one of {', '.join(ACCESS)}; got {'; '.join(bad)}")
    return entries


def ascii_host(host: str) -> str:
    """The host `browser_url` would request, without a trailing dot for registry and pace comparisons.

    Import here rather than at module scope: net's Fetcher also reads the source registry.
    """
    from lazuli.catalog.net import browser_url

    if not host or any(char in host for char in "/\\?#@"):
        raise ValueError("invalid host")
    authority = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return (urlsplit(browser_url(f"http://{authority}/")).hostname or "").rstrip(".")


def _host(host: str) -> str:
    return ascii_host(host).removeprefix("www.")


def find(url: str, registry: list[dict] | None = None) -> dict | None:
    """The registry entry a URL belongs to, or None when its host is not listed.

    Hosts compare without a leading `www.`; an entry owns its url's host and every host in `hosts`.
    Among the entries on the URL's host, the one whose url path is the longest prefix of the URL's
    path wins (github.com/google/fonts before github.com/); when none covers the path, the host's
    strictest entry decides.
    """
    from lazuli.catalog.net import InvalidURL, browser_url

    try:
        parts = urlsplit(url)
        if not parts.hostname:
            return None
        if parts.scheme.lower() in ("http", "https"):
            parts = urlsplit(browser_url(url))
        host = _host(parts.hostname or "")
    except ValueError as exc:
        detail = (f"the URL host {exc.detail}" if isinstance(exc, InvalidURL) and exc.kind == "host"
                  else "the URL host cannot be converted to an IDNA name")
        return {"id": "invalid-host", "name": "Invalid host", "access": "refused",
                "reason": f"{detail}; request not sent"}
    path = parts.path or "/"
    on_host: list[dict] = []
    best, best_len = None, -1
    for entry in load_registry() if registry is None else registry:
        own = urlsplit(entry["url"])
        try:
            own_host = _host(own.hostname or "")
        except ValueError:
            own_host = None
        if host == own_host:
            on_host.append(entry)
            prefix = own.path.rstrip("/")
            if (not prefix or path == prefix or path.startswith(prefix + "/")) and len(prefix) > best_len:
                best, best_len = entry, len(prefix)
        else:
            for extra in entry.get("hosts", ()):
                try:
                    match = host == _host(extra)
                except ValueError:
                    continue
                if match:
                    on_host.append(entry)
                    if best_len < 0:               # an extra host covers every path on it
                        best, best_len = entry, 0
                    break
    if best is not None:
        return best
    return max(on_host, key=lambda e: _STRICTNESS.get(e.get("access"), _UNKNOWN_STRICTNESS), default=None)


def for_color_system(system: str, registry: list[dict] | None = None) -> dict | None:
    """The registry entry that is the reference for a vocab/color.yaml color system."""
    entries = load_registry() if registry is None else registry
    return next((e for e in entries if e.get("color_system") == system), None)


def _access_label(entry: dict) -> str:
    return f"adapter:{entry['adapter']}" if entry["access"] == "adapter" else entry["access"]


def render(entries: list[dict]) -> str:
    """Two lines per source (id, access, types, url; then name and use), plus why for links and refusals."""
    lines = []
    for e in entries:
        lines.append(f"{e['id']:26} {_access_label(e):22} {','.join(e['type']):12} {e['url']}")
        lines.append(f"    {e['name']}: {e['good_for']}")
        if e["access"] == "refused":
            lines.append(f"    refused: {e['reason']} ({e['clause']}; {e['terms_url']})")
        elif e["access"] == "browser-link":
            lines.append(f"    browser link only: {e['reason']}")
    return "\n".join(lines)


def _summary(entries: list[dict]) -> str:
    counts = ", ".join(f"{sum(e['access'] == a for e in entries)} {a}" for a in ACCESS)
    return f"{len(entries)} sources ({counts})"


def main(argv: list[str], prog: str = "lazuli sources") -> int:
    ap = argparse.ArgumentParser(prog=prog, description="List the source registry: where to look for fonts, "
                                 "colors, assets, and design references, and how lazuli may reach each.")
    ap.add_argument("--type", choices=TYPES, help="only sources of this type")
    ap.add_argument("--json", action="store_true", help="the registry entries as JSON")
    args = ap.parse_args(argv)
    entries = [e for e in load_registry() if args.type is None or args.type in e["type"]]
    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
        return 0
    print(_summary(entries) + "; access policies as checked on each entry's date")
    print(render(entries))
    return 0


def _score(entry: dict, token: str) -> int:
    """How well one query word matches an entry: name or id 3, use or site 2, notes 1, else 0."""
    if token in entry["id"] or token in entry["name"].lower():
        return 3
    if token in entry["good_for"].lower() or any(token in h for h in [entry["url"], *entry.get("hosts", ())]):
        return 2
    extra = " ".join(str(entry.get(k, "")) for k in ("note", "license", "color_system", "adapter")).lower()
    return 1 if token in extra or token in entry["type"] else 0


def search(query: str, entries: list[dict]) -> list[tuple[int, dict]]:
    """Entries matching any query word: those matching the most words first, then by match strength."""
    tokens = query.lower().split()
    scored = []
    for entry in entries:
        scores = [_score(entry, t) for t in tokens]
        if any(scores):
            scored.append((sum(1 for s in scores if s), sum(scores), entry))
    scored.sort(key=lambda hit: (-hit[0], -hit[1], hit[2]["id"]))
    return [(score, entry) for _, score, entry in scored]


def search_main(argv: list[str], prog: str = "lazuli search --type source") -> int:
    ap = argparse.ArgumentParser(prog=prog, description="Find sources in the registry by name, use, or site.")
    ap.add_argument("query", nargs="+", help="words to match against name, use, site, and notes")
    ap.add_argument("--kind", choices=TYPES, help="only sources of this type")
    ap.add_argument("--access", choices=ACCESS, help="only sources with this access policy")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    entries = [e for e in load_registry() if (args.kind is None or args.kind in e["type"])
               and (args.access is None or e["access"] == args.access)]
    hits = search(" ".join(args.query), entries)[:max(args.limit, 0)]
    if args.json:
        print(json.dumps([{"score": score, **entry} for score, entry in hits], ensure_ascii=False, indent=2))
        return 0
    if not hits:
        print(f"no source matches {' '.join(args.query)!r}; `lazuli sources` lists them all")
        return 0
    print(render([entry for _, entry in hits]))
    return 0
