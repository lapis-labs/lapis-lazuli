"""GitHub foundries: a snapshot of the font repositories of a fixed list of GitHub accounts.

The accounts are the registry entries (`src/shared/sources/registry.yaml`) whose adapter is
`github-foundries`; the account is the entry's url path, and the entry may say which `scripts` its families
cover and whether it ships font packages as `releases`. Independent foundries keep each family in a
repository of its own, so one repository list per account gives its families with a license each.

Requests, through the unauthenticated GitHub REST API (60 an hour; api.github.com has no robots.txt, and
GitHub's terms, section H, allow API use within the rate limits; checked 2026-10-16):
1. `GET /users/<account>/repos?per_page=100&sort=pushed` once per account (`users` answers for
   organizations too; further pages only for a longer list, at most MAX_PAGES).
2. `GET /repos/<repo>/license`, only for a repository the list reports as NOASSERTION: GitHub reports that for
   a license file it does not recognize by its text, such as `OFL.md` or a `LICENSE` holding the OFL.
3. `GET /repos/<repo>/releases/latest`, only for an account marked `releases`, for the MAX_RELEASE_LOOKUPS
   most-starred of its families across accounts, and only while the quota leaves RESERVE requests unspent; the
   rest fall back to the repository archive as their download address.
The pace is 3 s. Every response carries the quota (`x-ratelimit-remaining`, `x-ratelimit-reset`): a required
request waits for the reset when it is at most MAX_WAIT_S away and otherwise stops the sync with RateLimited (the
previous rows stay); an optional one is skipped. A 403 or 429 that reports the quota used up is a rate limit,
not a block (`net.RateLimited`). Nothing is signed in, no token is read or sent.

A repository is a family when it is not a fork, is not disabled, is not named as a collection (`...fonts`),
does not read as tooling or a website, and reads as a font: an OFL-1.1 SPDX id, a font topic, or a font word in
its name or description. The family name is the repository name, `-` and `_` as spaces, a trailing `font` or
`typeface` removed, an all-lowercase word capitalized (`league-gothic` is League Gothic).

License, as found, with its source in `details["license_source"]`: the SPDX id the list reports; else, for
NOASSERTION, the license file's name when it is the OFL's (`OFL`, `OFL.txt`, `OFL.md`) or its text when it is the
SIL Open Font License 1.1 (a `LICENSE` file); else none, and the family has no license. SPDX ids map through
`labels.map_spdx` (OFL-1.1 and Apache-2.0 as they are, MIT, CC0-1.0, and Unlicense to `free-other`); any other id
stays raw text with no mapped license. Nothing is called open that its SPDX id or license file does not say.

Details: the description, the homepage, a download address (the latest release's archive asset, else the
repository's default-branch archive; `download_kind` says which), the repository name, and the latest release
tag. Scripts come from the repository's topics and description (`latin`, `korean`, `japanese`, ... as plain words;
a description word that an influence phrase leads into, as in `inspired by korean writing`, `derived from`, `based
on`, `revival of a`, names a model and is skipped) and from the account's `scripts` hint; each `script:` label's raw
text says which. They are also the family's primary scripts (`details.primary_scripts`, `primary_basis`): the ones
the repository names itself, so `Korean Version of LXGW WenKai` is a Korean family in a Han account and `A Latin font`
is a Latin one; when the repository names none, the account's hint, so `scripts: [hang, latn]` makes Pretendard
and Spoqa Han Sans designed for both. The words are lexical, so a description that names no script says nothing, and
one that mentions a script the family does not cover in other words than the influence phrases is read as covering it.
Signals: `date_added` (repository creation) and `last_modified` (last push); the snapshot has no popularity, so
familiarity is unknown.
Responses are kept in `raw_payload`, so `from_raw` re-applies the mapping with no request.
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from lazuli import sources
from lazuli.catalog import labels, net, store
from lazuli.catalog.google_fonts import JSON_HEADERS
from lazuli.catalog.net import Fetcher
from lazuli.catalog.store import CatalogFamily, CatalogLabel

NAME = "github-foundries"
KIND = "snapshot"
PRIORITY = 22
TTL_DAYS = 30
MIN_INTERVAL_S = 3.0

API = "https://api.github.com"
REPOS_URL = API + "/users/{login}/repos"
LICENSE_URL = API + "/repos/{full_name}/license"
RELEASE_URL = API + "/repos/{full_name}/releases/latest"
ARCHIVE_URL = "https://github.com/{full_name}/archive/refs/heads/{branch}.zip"
PER_PAGE = 100
MAX_PAGES = 3
RESERVE = 5                      # requests an optional lookup leaves unspent
MAX_RELEASE_LOOKUPS = 12         # a full run stays about 10 lists, the NOASSERTION license files, and these
MAX_WAIT_S = 120                 # the longest a required request waits for the quota to reset

_COLLECTION = re.compile(r"fonts$", re.I)
_FONT_TOPIC = re.compile(r"(?:^|-)(?:fonts?|typefaces?)$|^(?:opentype|truetype|ofl)$")        # font, cjk-font, variable-font
_FONT_WORDS = re.compile(r"\b(?:fonts?|typefaces?|type ?famil(?:y|ies)|opentype|truetype|ofl|sans|serif|slab|mono(?:space)?"
                         r"|gothic|mincho|grotesk|display|variable|handwrit\w*|calligraph\w*)\b", re.I)
_TOOL_WORDS = re.compile(r"\b(?:web ?sites?|docs?|documentation|toolkit|tooling|generator|template|plugin|pipeline"
                         r"|specimens?|landing page|blog|icons?|iconset)\b", re.I)         # icon sets are no text faces
_TOOL_TOPICS = frozenset({"website", "documentation", "tool", "tools", "toolkit", "build-tool", "generator", "icons",
                          "iconset", "icon-font"})
_OFL_FILE = re.compile(r"^(?:ofl|open-?font-?licen[cs]e)(?:-1\.1)?(?:\.(?:txt|md))?$", re.I)
_OFL_TEXT = re.compile(r"SIL OPEN FONT LICENSE,? Version 1\.1", re.I)
_SCRIPT_WORDS = {"latin": "latn", "cyrillic": "cyrl", "greek": "grek", "korean": "hang", "hangul": "hang",
                 "japanese": "jpan", "kana": "kana", "kanji": "hani", "chinese": "hani", "hanzi": "hani",
                 "arabic": "arab", "hebrew": "hebr", "thai": "thai", "devanagari": "deva"}
_INFLUENCE = re.compile(r"(?:inspired by|derived from|based on|reminiscent of|revival of|after|from|like|by)"
                        r"(?:\s+[a-z'-]+){0,2}\s*$")       # a description names a model here, not what the family covers
_ARCHIVE_ASSETS = (re.compile(r"\.zip$", re.I), re.compile(r"\.(?:tar\.gz|tgz|tar\.xz|7z)$", re.I),
                   re.compile(r"\.(?:otf|ttf|woff2?)$", re.I))
_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')
_SKIPPED = object()              # an optional lookup the quota did not leave room for


@dataclass(frozen=True)
class Account:
    login: str
    name: str
    scripts: tuple[str, ...] = ()
    releases: bool = False


def accounts(registry: list[dict] | None = None) -> list[Account]:
    """The registry's GitHub foundry accounts, in registry order."""
    entries = sources.load_registry() if registry is None else registry
    return [Account(urlsplit(e["url"]).path.strip("/"), e["name"], tuple(e.get("scripts", ())), bool(e.get("releases")))
            for e in entries if e.get("adapter") == NAME]


# ---------------------------------------------------------------- mapping

def family_name(repo_name: str) -> str:
    parts = [p for p in re.split(r"[-_\s]+", repo_name) if p]
    if len(parts) > 1 and parts[-1].lower() in ("font", "typeface"):
        parts = parts[:-1]
    return " ".join(p[:1].upper() + p[1:] if p.islower() else p for p in parts)


def _spdx(repo: dict) -> str | None:
    return (repo.get("license") or {}).get("spdx_id") or None


def _is_family(repo: dict) -> bool:
    if repo.get("fork") or repo.get("disabled") or _COLLECTION.search(repo["name"]) \
            or re.fullmatch(r"licen[cs]es?", repo["name"], re.I):
        return False
    text = " ".join([re.sub(r"[-_]+", " ", repo["name"]), repo.get("description") or ""])
    topics = set(repo.get("topics") or ())
    if _TOOL_WORDS.search(text) or topics & _TOOL_TOPICS:
        return False
    return _spdx(repo) == "OFL-1.1" or any(_FONT_TOPIC.search(t) for t in topics) or bool(_FONT_WORDS.search(text))


def _license(repo: dict, lookup: dict | None) -> tuple[str | None, str | None, str]:
    """(license id or None, raw text or None, where it was read) for a repository; `lookup` is the license file
    GitHub returned for a NOASSERTION repository, or None."""
    spdx = _spdx(repo)
    if spdx and spdx != "NOASSERTION":
        return labels.map_spdx(spdx), spdx, f"SPDX id {spdx} reported by the GitHub API"
    if not spdx:
        return None, None, "the GitHub API reports no license"
    if lookup is None:
        return None, None, "the GitHub API reports NOASSERTION and no license file was found"
    name = lookup.get("name") or lookup.get("path") or "the license file"
    note = "the GitHub API reports NOASSERTION"
    if _OFL_FILE.match(name):
        return "OFL-1.1", name, f"license file {name}: its name is the OFL's ({note})"
    text = ""
    if lookup.get("encoding") == "base64" and lookup.get("content"):
        text = re.sub(r"\s+", " ", base64.b64decode(lookup["content"]).decode("utf-8", errors="replace"))
    if _OFL_TEXT.search(text):
        return "OFL-1.1", f"{name} (text)", f"license file {name}: its text is the SIL Open Font License 1.1 ({note})"
    return None, None, f"license file {name} was read and does not name a license lazuli knows ({note})"


def _stated_scripts(repo: dict) -> dict[str, str]:
    """{ISO 15924 code: where it is said} for the scripts a repository's own topics and description name. A topic
    names a script; a description word does too unless an influence phrase leads into it (`inspired by korean
    writing`, `derived from`, `based on`, `revival of a`, `after`, `from`, `like`, `by`), which names a model,
    not what the family covers."""
    found: dict[str, str] = {}
    where = "in the repository's description or topics"
    for topic in repo.get("topics") or ():
        for word in re.findall(r"[a-z]+", topic.lower()):
            if word in _SCRIPT_WORDS:
                found.setdefault(_SCRIPT_WORDS[word], f"{word} {where}")
    text = (repo.get("description") or "").lower()
    for hit in re.finditer(r"[a-z]+", text):
        if hit[0] in _SCRIPT_WORDS and not _INFLUENCE.search(text[:hit.start()]):
            found.setdefault(_SCRIPT_WORDS[hit[0]], f"{hit[0]} {where}")
    return found


def _scripts(account: Account, repo: dict) -> tuple[list[CatalogLabel], dict]:
    """(script labels, primary-script details). Coverage: every script the repository names, plus the account's
    `scripts` hint. Primary: the scripts the repository names itself, else the hint; a repository that says `Korean
    Version` is a Korean family whatever its account's hint says, and one that says nothing takes the hint."""
    stated = _stated_scripts(repo)
    found = dict(stated)
    for code in account.scripts:
        found.setdefault(code, "account hint in the source registry")
    labels = [CatalogLabel("property", raw, f"script:{code}") for code, raw in found.items()]
    if stated:
        return labels, {"primary_scripts": list(stated), "primary_basis": "repository description or topics"}
    if account.scripts:
        return labels, {"primary_scripts": list(account.scripts), "primary_basis": "registry scripts hint"}
    return labels, {}


def _download(repo: dict, release: dict | None) -> tuple[str, str]:
    """(address, "release-asset" | "archive"): the latest release's package, else the default branch's archive."""
    assets = [a for a in (release or {}).get("assets") or () if a.get("browser_download_url")]
    for pattern in _ARCHIVE_ASSETS:
        if asset := next((a for a in assets if pattern.search(a.get("name") or "")), None):
            return asset["browser_download_url"], "release-asset"
    return ARCHIVE_URL.format(full_name=repo["full_name"], branch=repo.get("default_branch") or "main"), "archive"


def _family(account: Account, repo: dict, lookup: dict | None, release: dict | None) -> CatalogFamily:
    license_id, raw, license_source = _license(repo, lookup)
    download, kind = _download(repo, release)
    script_labels, primary = _scripts(account, repo)
    homepage = (repo.get("homepage") or "").strip()
    details = {"repository": repo["full_name"], "license_source": license_source, "download_url": download,
               "download_kind": kind, **primary}
    if repo.get("description"):
        details["description"] = repo["description"]
    if homepage.startswith(("http://", "https://")):
        details["homepage"] = homepage
    if release and release.get("tag_name"):
        details["release_tag"] = release["tag_name"]
    if repo.get("archived"):
        details["archived"] = True
    signals = {key: repo[field][:10] for key, field in (("date_added", "created_at"), ("last_modified", "pushed_at"))
               if isinstance(repo.get(field), str) and repo[field]}
    return CatalogFamily(
        source_key=repo["full_name"], family=family_name(repo["name"]), foundry=account.name, license=license_id or raw,
        url=repo.get("html_url") or f"https://github.com/{repo['full_name']}",
        labels=[*([CatalogLabel("license", raw, license_id)] if raw else []), *script_labels],
        signals=signals, details=details)


def families_from(accts: list[Account], repos: dict[str, list[dict]], licenses: dict[str, dict | None],
                  releases: dict[str, dict | None]) -> list[CatalogFamily]:
    """The snapshot from the kept responses: each account's repositories, the license files fetched by repository
    full name, and the latest releases fetched by repository full name."""
    families: dict[str, CatalogFamily] = {}
    for account in accts:
        for repo in repos.get(account.login, ()):
            if _is_family(repo):
                families.setdefault(repo["full_name"], _family(
                    account, repo, licenses.get(repo["full_name"]), releases.get(repo["full_name"])))
    return list(families.values())


# ---------------------------------------------------------------- requests

class _Api:
    """GitHub API requests within the quota: required ones wait for the reset or stop, optional ones are skipped."""

    def __init__(self, fetcher: Fetcher):
        self.fetcher = fetcher
        self.remaining: int | None = None
        self.reset: float | None = None

    def _note(self, response: net.Response) -> None:
        left, reset = response.headers.get("x-ratelimit-remaining", ""), response.headers.get("x-ratelimit-reset", "")
        if left.isdigit():
            self.remaining = int(left)
        if reset.isdigit():
            self.reset = float(reset)

    def _ready(self, optional: bool) -> bool:
        floor = RESERVE if optional else 0
        if self.remaining is None or self.remaining > floor:
            return True
        if optional:
            return False
        wait = (self.reset or 0) - net._clock()
        if self.reset is None or wait > MAX_WAIT_S:
            raise net.RateLimited(API, self.reset)
        net._sleep(max(wait, 0) + 1)
        self.remaining = None
        return True

    def get(self, url: str, *, params: dict | None = None, store_as: str | None = None, optional: bool = False):
        """The response, or the _SKIPPED sentinel when an optional request had no quota to spend."""
        for _ in range(2):
            if not self._ready(optional):
                return _SKIPPED
            try:
                response = self.fetcher.get(url, params=params, headers=JSON_HEADERS, store_as=store_as)
            except net.RateLimited as limited:
                self.remaining, self.reset = 0, limited.reset
                if optional:
                    return _SKIPPED
                continue
            self._note(response)
            return response
        raise net.RateLimited(url, self.reset)

    def lookup(self, url: str, *, store_as: str, optional: bool = False):
        """The JSON of a resource that may not exist: None for a 404 (it still spends one request)."""
        try:
            response = self.get(url, store_as=store_as, optional=optional)
        except net.FetchError as error:
            if error.status != 404:
                raise
            if self.remaining:
                self.remaining -= 1
            return None
        return response if response is _SKIPPED else response.json()


def _list_repos(api: _Api, account: Account) -> list[dict]:
    out: list[dict] = []
    url, params = REPOS_URL.format(login=account.login), {"per_page": PER_PAGE, "sort": "pushed"}
    for page in range(1, MAX_PAGES + 1):
        response = api.get(url, params=params, store_as=_repos_key(account.login, page))
        out += response.json()
        if not (match := _NEXT.search(response.headers.get("link", ""))):
            break
        url, params = match[1], None
    return out


def _repos_key(login: str, page: int) -> str:
    return f"repos/{login}" + (f"?page={page}" if page > 1 else "")


def fetch(fetcher: Fetcher, accts: list[Account] | None = None) -> list[CatalogFamily]:
    accts = accounts() if accts is None else accts
    api = _Api(fetcher)
    repos = {a.login: _list_repos(api, a) for a in accts}
    chosen = [(a, r) for a in accts for r in repos[a.login] if _is_family(r)]
    if not chosen:
        # Never replace the snapshot with an empty list because the API answered something unexpected
        raise ValueError("no font repositories found in the listed accounts; the API answers may have changed")
    licenses = {r["full_name"]: api.lookup(LICENSE_URL.format(full_name=r["full_name"]),
                                           store_as=f"license/{r['full_name']}")
                for _, r in chosen if _spdx(r) == "NOASSERTION"}
    releases: dict[str, dict | None] = {}
    ranked = sorted(((a, r) for a, r in chosen if a.releases), key=lambda ar: -ar[1].get("stargazers_count", 0))
    for _, repo in ranked[:MAX_RELEASE_LOOKUPS]:
        release = api.lookup(RELEASE_URL.format(full_name=repo["full_name"]), store_as=f"release/{repo['full_name']}",
                             optional=True)
        if release is _SKIPPED:                       # the quota is down to its reserve; the rest keep the archive
            break
        releases[repo["full_name"]] = release
    return families_from(accts, repos, licenses, releases)


def from_raw(conn) -> list[CatalogFamily] | None:
    """The snapshot re-mapped from the kept responses (no request), or None when an account's list was not kept."""
    accts = accounts()
    repos: dict[str, list[dict]] = {}
    for account in accts:
        for page in range(1, MAX_PAGES + 1):
            body = store.load_raw(conn, NAME, _repos_key(account.login, page))
            if body is None:
                break
            repos.setdefault(account.login, []).extend(json.loads(body))
        if account.login not in repos:
            return None
    kept = {}
    for kind in ("license", "release"):
        kept[kind] = {r["full_name"]: json.loads(body) for rs in repos.values() for r in rs
                      if (body := store.load_raw(conn, NAME, f"{kind}/{r['full_name']}")) is not None}
    return families_from(accts, repos, kept["license"], kept["release"])
