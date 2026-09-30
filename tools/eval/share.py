#!/usr/bin/env python3
"""Export what is safe to share from an eval folder: numbers and settings, no paths, user names, or skill names.

    uv run --no-sync python tools/eval/share.py OUT DEST

Run records never go into the repository or a bundle: a run folder holds the agent's whole conversation
(`events.jsonl`), its project, and paths that name the user. This command is the one way results leave it.
It writes to DEST (a new or empty folder, outside the repository and outside OUT) only `manifest.json`,
`summary.md`, `summary.csv`, and per run `run.json`, `score.json`, `isolation.json`, `command.txt`, and
`prompt.txt`, each rewritten: paths under OUT become `<out>`, home directories `~`, user names `<user>`,
the names of skills that are not the kit's own `<other-skill>`, and lists of the user's own skills
(older records held them, as `outside_before` and `disabled`) become counts. Nothing else is copied. Before
it writes anything it reads its own output again; if a home directory, run path, or user name is still
there it writes nothing and exits 2.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
from pathlib import Path

import evalkit as kit
from evalkit import KitError

TOP_FILES = ("manifest.json", "summary.md", "summary.csv")
RUN_FILES = ("run.json", "score.json", "isolation.json", "command.txt", "prompt.txt")
LEFT_OUT = ("project trees, scratch homes, transcripts (events.jsonl), stderr logs, last messages, "
            "score/ reports, the review folder and its key")
SKILL_LISTS = ("skills", "skills_read", "skills_not_read", "expected", "visible")
_HOME_PATH = re.compile(r"(?<![\w.\-~])(?:/Users|/home)/([^/\s\"'\\:]+)")
_SKILLS_CONFIG = re.compile(r"skills\.config=\[.*\]")
_SKILL_DIR = re.compile(r"(\.agents/skills|/skills)/([A-Za-z0-9_.\-]+)/")
_MIN_NAME = 3        # shorter user names are only removed from paths; as words they would eat ordinary text


def _user_names(texts: list[str]) -> set[str]:
    names = {Path.home().name}
    for text in texts:
        names.update(_HOME_PATH.findall(text))
    names.add(Path.home().name)
    try:
        names.add(getpass.getuser())
    except (OSError, KeyError, ImportError):
        pass
    return {n for n in names if len(n) >= _MIN_NAME}


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


class Scrubber:
    def __init__(self, out: Path, public_skills: set[str], users: set[str]):
        self.folders = sorted({str(out), os.path.realpath(out)}, key=len, reverse=True)
        self.public = public_skills
        self.users = sorted(users, key=len, reverse=True)

    def text(self, value: str) -> str:
        value = _SKILLS_CONFIG.sub(
            lambda m: f"skills.config=[... {m.group(0).count('enabled=false')} paths switched off ...]", value)
        for folder in self.folders:
            value = value.replace(folder, "<out>")
        value = _HOME_PATH.sub("~", kit.redact_home(value))
        value = _SKILL_DIR.sub(
            lambda m: m.group(0) if m.group(2) in self.public else f"{m.group(1)}/<other-skill>/", value)
        for user in self.users:
            value = re.sub(r"(?<![\w-])" + re.escape(user) + r"(?![\w-])", "<user>", value, flags=re.I)
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
        return self.text(node) if isinstance(node, str) else node

    def leftover(self, text: str, hidden_skills: set[str]) -> str | None:
        """What an exported text still holds that it must not, or None."""
        if any(folder in text for folder in self.folders):
            return "a path under the run folder"
        if kit.redact_home(text) != text or _HOME_PATH.search(text):
            return "a home directory"
        for user in self.users:
            if re.search(r"(?<![\w-])" + re.escape(user) + r"(?![\w-])", text, flags=re.I):
                return "a user name"
        for name in hidden_skills:
            if f'"{name}"' in text or f"/{name}/" in text:
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
    sources = [out / n for n in TOP_FILES if (out / n).is_file()]
    for run_dir in kit.list_runs(out):
        sources += [run_dir / n for n in RUN_FILES if (run_dir / n).is_file()]
    texts = {path: path.read_text(encoding="utf-8", errors="replace") for path in sources}
    documents = {path: json.loads(text) for path, text in texts.items() if path.suffix == ".json"}
    scrub = Scrubber(out, _public_skills(out, documents.get(out / "manifest.json", {})),
                     _user_names(list(texts.values())))
    hidden = _global_skill_names(list(documents.values())) - scrub.public
    written: dict[Path, str] = {}
    for path in sources:
        relative = path.relative_to(out)
        if path in documents:
            written[relative] = json.dumps(scrub.document(documents[path]), ensure_ascii=False, indent=2) + "\n"
        else:
            written[relative] = scrub.text(texts[path])
    for relative, text in written.items():
        problem = scrub.leftover(text, hidden)
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
