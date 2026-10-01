#!/usr/bin/env python3
"""Export what is safe to share from an eval folder: numbers and settings, no paths, user names, or skill names.

    uv run --no-sync python tools/eval/share.py OUT DEST

Run records never go into the repository or a bundle: a run folder holds the agent's whole conversation
(`events.jsonl`), its project, and paths that name the user. This command is the one way results leave it.
It writes to DEST (a new or empty folder, outside the repository and outside OUT) only `manifest.json`,
`summary.md`, `summary.csv`, and per run `run.json`, `score.json`, `isolation.json`, `command.txt`, and
`prompt.txt`. The JSON and text files are rewritten: paths under OUT become `<out>`, home directories `~`,
a user name inside a path or a value that is the name and nothing else `<user>`, the names of skills that
are not the kit's own `<other-skill>`, and lists of the user's own skills (older records held them, as
`outside_before` and `disabled`) become counts. The two summaries are not copied: they are built again
from the rewritten records. Nothing else is copied.

Before it writes anything it reads its own output again; if a run path or home directory is still in a
file, or a user name or the name of a skill of the user's own is still in a value, it writes nothing and
exits 2. A user name inside ordinary text is not rewritten, because that would also rewrite ordinary
words when the account is called `plan` or `copy`; it stops the export instead. Common account names
(`root`, `runner`, ...) are not looked for as words.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path

import evalkit as kit
import score
from evalkit import KitError

TOP_FILES = ("manifest.json",)
SUMMARY_FILES = ("summary.md", "summary.csv")
RUN_FILES = ("run.json", "score.json", "isolation.json", "command.txt", "prompt.txt")
LEFT_OUT = ("project trees, scratch homes, transcripts (events.jsonl), stderr logs, last messages, "
            "score/ reports, the review folder and its key")
SKILL_LISTS = ("skills", "skills_read", "skills_not_read", "expected", "visible")
GENERIC_ACCOUNTS = frozenset({"root", "runner", "admin", "user", "ubuntu", "vscode", "node"})
_HOME_PATH = re.compile(r"(?<![\w.\-~])(?:/Users|/home)/([^/\s\"'\\:]+)")
_SKILLS_CONFIG = re.compile(r"skills\.config=\[.*\]")
_SKILL_DIR = re.compile(r"(\.agents/skills|/skills)/([A-Za-z0-9_.\-]+)/")
_MIN_NAME = 3        # shorter user names are only removed from paths; as words they would eat ordinary text


def _user_names(texts: list[str]) -> set[str]:
    names = {Path.home().name}
    for text in texts:
        names.update(_HOME_PATH.findall(text))
    try:
        names.add(getpass.getuser())
    except (OSError, KeyError, ImportError):
        pass
    return {n for n in names if n}


def _walk(node, key: str | None = None) -> Iterator[tuple[str | None, object]]:
    """Every (key of the list or entry it sits in, value) of a JSON document; keys themselves are not values."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, k)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item, key)
    else:
        yield key, node


def _strings(document) -> list[str]:
    return [v for _, v in _walk(document) if isinstance(v, str)]


def _global_skill_names(documents: list) -> set[str]:
    """Names of the user's own skills that older records listed (`outside_before`, and the paths in `disabled`)."""
    found: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "outside_before" and isinstance(value, list):
                    found.update(v for v in value if isinstance(v, str))
                elif key == "disabled" and isinstance(value, list):
                    for path in value:
                        if isinstance(path, str):
                            folder = os.path.dirname(path) if path.endswith("SKILL.md") else path
                            found.add(os.path.basename(folder.rstrip("/")))
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for document in documents:
        walk(document)
    return found


def _skills_read(documents: list) -> set[str]:
    """Every skill name a record lists as read; the ones that are not the kit's own are hidden skills."""
    return {v for document in documents for key, v in _walk(document)
            if key == "skills_read" and isinstance(v, str)}


def _word(name: str) -> re.Pattern:
    return re.compile(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", re.I)


class Scrubber:
    def __init__(self, out: Path, public_skills: set[str], users: set[str]):
        self.folders = sorted({str(out), os.path.realpath(out)}, key=len, reverse=True)
        self.public = public_skills
        users = sorted(users, key=len, reverse=True)
        # a user name inside a path: between separators, or ending at a quote, a space, or a punctuation mark
        self.in_paths = [re.compile(r"(?<=[/\\])" + re.escape(u) + r"(?=[/\\\s\"'`:;,)\]}>]|$)", re.I)
                         for u in users]
        # the names that can be looked for as words: not short, not an account every machine has
        names = {u.casefold() for u in users if len(u) >= _MIN_NAME and u.casefold() not in GENERIC_ACCOUNTS}
        self.names = names
        self.words = [_word(n) for n in sorted(names)]

    def text(self, value: str) -> str:
        value = _SKILLS_CONFIG.sub(
            lambda m: f"skills.config=[... {m.group(0).count('enabled=false')} paths switched off ...]", value)
        for folder in self.folders:
            value = value.replace(folder, "<out>")
        value = _HOME_PATH.sub("~", kit.redact_home(value))
        value = _SKILL_DIR.sub(
            lambda m: m.group(0) if m.group(2) in self.public else f"{m.group(1)}/<other-skill>/", value)
        for pattern in self.in_paths:
            value = pattern.sub("<user>", value)
        return value

    def document(self, node, key: str | None = None):
        if isinstance(node, dict):
            if "verified" in node and "expected" in node:        # an isolation record
                node = kit.public_isolation(node)
            return {k: self.document(v, k) for k, v in node.items()}
        if isinstance(node, list):
            if key in SKILL_LISTS and all(isinstance(n, str) for n in node):
                return [n if n in self.public else "<other-skill>" for n in node]
            return [self.document(item) for item in node]
        if isinstance(node, str):
            return "<user>" if node.strip().casefold() in self.names else self.text(node)
        return node

    def leftover(self, text: str, hidden_skills: set[str], values: list[str] | None = None,
                 *, skill_words: bool = False) -> str | None:
        """What an exported file still holds that it must not, or None.

        The whole text, keys included, is searched for the run folder and home directories only. Inside
        `values` (the string values of a JSON file; for any other file the text itself) a user name must
        not be in a path, and in JSON values it must also not be a whole value or a word of one; the name of
        a skill of the user's own must not be in a path or a whole value. `skill_words` looks for those
        skill names as words of the whole text (the summaries, which have no values)."""
        if any(folder in text for folder in self.folders):
            return "a path under the run folder"
        if kit.redact_home(text) != text or _HOME_PATH.search(text):
            return "a home directory"
        for value in [text] if values is None else values:
            if any(pattern.search(value) for pattern in self.in_paths):
                return "a user name"
            if any(f"/{name}/" in value for name in hidden_skills):
                return "the name of a skill of the user's own"
        for value in values or []:
            if value.strip().casefold() in self.names or any(word.search(value) for word in self.words):
                return "a user name"
            if value in hidden_skills:
                return "the name of a skill of the user's own"
        if skill_words and any(_word(name).search(text) for name in hidden_skills):
            return "the name of a skill of the user's own"
        return None


def _public_skills(out: Path, manifest: dict) -> set[str]:
    names = set(manifest.get("skill_digests", {}))
    for task in (manifest.get("tasks") or {}).values():
        names.update(task.get("skills", []))
    dist = kit.REPO / "dist" / "skills"
    if dist.is_dir():
        names.update(p.name for p in dist.iterdir() if p.is_dir())
    return names


def _summaries(out: Path, runs: list[Path], cleaned: dict[Path, object]) -> dict[Path, str]:
    """The summaries that `out` holds, built again from the cleaned manifest, run, and score documents."""
    wanted = [name for name in SUMMARY_FILES if (out / name).is_file()]
    if not wanted:
        return {}
    rows = []
    try:
        for run_dir in runs:
            relative = run_dir.relative_to(out)
            rows.append(score.row_from(cleaned[relative / "run.json"], cleaned.get(relative / "score.json")))
        files = score.summary_files(cleaned.get(Path("manifest.json")), rows)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise KitError(f"the summaries cannot be built from the run records ({type(exc).__name__}: {exc}); "
                       "nothing was exported") from exc
    return {Path(name): files[name] for name in wanted}


def export(out: Path, dest: Path) -> list[str]:
    """Write the shareable records of `out` to `dest`; returns the files written, relative to `dest`."""
    out = Path(out).expanduser().resolve()
    dest = kit.ensure_outside_repo(dest)
    if not (out / "manifest.json").is_file():
        raise KitError(f"{out} has no manifest.json; give the folder run.py wrote")
    if dest == out or out in dest.parents or dest in out.parents:
        raise KitError(f"{dest} and {out} must be separate folders")
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise KitError(f"{dest} is not empty; give a new folder")
    runs = kit.list_runs(out)
    kit.refuse_adobe_calls(runs, "export")
    sources = [out / n for n in TOP_FILES if (out / n).is_file()]
    for run_dir in runs:
        sources += [run_dir / n for n in RUN_FILES if (run_dir / n).is_file()]
    texts = {path: path.read_text(encoding="utf-8", errors="replace") for path in sources}
    documents = {path: json.loads(text) for path, text in texts.items() if path.suffix == ".json"}
    public = _public_skills(out, documents.get(out / "manifest.json", {}))
    scrub = Scrubber(out, public, _user_names(list(texts.values())))
    raw = list(documents.values())
    hidden = (_global_skill_names(raw) | _skills_read(raw)) - scrub.public
    written: dict[Path, str] = {}
    values: dict[Path, list[str] | None] = {}
    cleaned: dict[Path, object] = {}
    for path in sources:
        relative = path.relative_to(out)
        if path in documents:
            cleaned[relative] = scrub.document(documents[path])
            written[relative] = json.dumps(cleaned[relative], ensure_ascii=False, indent=2) + "\n"
            values[relative] = _strings(cleaned[relative])
        else:
            written[relative] = scrub.text(texts[path])
            values[relative] = None
    summaries = _summaries(out, runs, cleaned)
    for relative, text in summaries.items():
        written[relative] = text
        values[relative] = None
    for relative, text in written.items():
        problem = scrub.leftover(text, hidden, values[relative], skill_words=relative in summaries)
        if problem:
            raise KitError(f"{relative} would still hold {problem}; nothing was exported")
    for relative, text in written.items():
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return sorted(p.as_posix() for p in written)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="share.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("out", type=Path, help="the folder run.py wrote")
    ap.add_argument("dest", type=Path, help="a new or empty folder outside the repository and OUT")
    args = ap.parse_args(argv)
    try:
        files = export(args.out, args.dest)
    except KitError as exc:
        print(f"share.py: {exc}", file=sys.stderr)
        return 2
    print(f"{len(files)} files -> {args.dest.expanduser().resolve()}\nleft out: {LEFT_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
