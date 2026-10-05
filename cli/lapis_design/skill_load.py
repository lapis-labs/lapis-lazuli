"""Cross-harness attestations of the exact skill sections loaded for the current phase/context."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from lapis_design import attempts

REQUIRED = {
    "lps-copy": ("SKILL.md", "references/interface-copy.md#One owner for every string"),
    "lps-system": ("SKILL.md", "references/tokens.md#Type tokens",
                   "references/tokens.md#Space, radius, surfaces, and icons", "references/tokens.md#Motion tokens"),
    "ultramarine": ("SKILL.md", "references/pre-show-review.md#Evidence"),
}

def required(root: Path, task: str, skill: str) -> tuple[str, ...]:
    if skill == "lps-copy":
        from lapis_design.plan_check import read_plan
        import yaml

        try:
            plan = read_plan(root / ".lapis/plans" / f"{task}.yaml")
            if isinstance(plan, dict) and any(str(locale).casefold().split("-")[0] == "ko"
                                             for locale in (plan.get("brief") or {}).get("locales", [])):
                return (*REQUIRED[skill], "references/interface-copy.md#Korean")
        except (OSError, ValueError, yaml.YAMLError):
            pass
    return REQUIRED[skill]


def path(root: Path, task: str, skill: str) -> Path:
    return root / ".lapis/skills" / task / f"{skill}.json"


def section(file: Path, heading: str | None) -> str:
    text = file.read_text(encoding="utf-8")
    if heading is None:
        return text
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if re.fullmatch(r"#{1,6} " + re.escape(heading) + r"\s*", line)), None)
    if start is None:
        raise ValueError(f"{file} has no section {heading!r}")
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"#{1," + str(level) + r"} ", lines[i])), len(lines))
    return "".join(lines[start:end])


def _digest(file: Path, heading: str | None) -> str:
    return hashlib.sha256(section(file, heading).encode()).hexdigest()


def missing(root: Path, task: str, skill: str) -> bool:
    try:
        doc = json.loads(path(root, task, skill).read_text(encoding="utf-8"))
        if doc["task"] != task or doc["skill"] != skill or not doc["context"]:
            return True
        if os.environ.get("LAPIS_CONTEXT") and doc["context"] != os.environ["LAPIS_CONTEXT"]:
            return True
        records = {r["section"]: r for r in doc["reads"]}
        for name in required(root, task, skill):
            row = records[name]
            if row["sha256"] != _digest(Path(row["file"]), row["heading"]):
                return True
    except (OSError, ValueError, KeyError, TypeError):
        return True
    return False


def needed(root: Path, task: str, result: dict) -> tuple[str, ...]:
    step = (result.get("step") or {}).get("id", "done")
    if step in ("brief", "references") or (step == "waiting-for-user" and not result.get("draft_review")):
        return ()
    primary = []
    if step in ("plan", "plan-fix", "plan-explorations", "plan-order"):
        primary += ["lps-copy", "lps-system"]
    elif step == "fonts-lock":
        primary += ["lps-system"]
    elif step in ("draft-review", "render", "behavior", "behavior-wait", "lint", "critic", "release", "done") or result.get("draft_review"):
        primary += ["ultramarine"]
    # Reaching a later phase cannot erase the load owed for copy/tokens already written in the plan.
    from lapis_design.plan_check import read_plan
    import yaml

    try:
        plan = read_plan(root / ".lapis/plans" / f"{task}.yaml")
        if step == "plan-fix" and not isinstance(plan, dict):
            return ()
        if isinstance(plan, dict):
            if plan.get("content"):
                primary.append("lps-copy")
            if plan.get("tokens"):
                primary.append("lps-system")
    except (OSError, ValueError, yaml.YAMLError):
        if step == "plan-fix":
            return ()  # an unreadable plan is repaired before any load or record request
    return tuple(dict.fromkeys(primary))


def apply(root: Path, task: str, result: dict) -> dict:
    skills = needed(root, task, result)
    result["skills"] = [{"name": s, "loaded": not missing(root, task, s), "sections": list(required(root, task, s))} for s in skills]
    absent = next((s for s in result["skills"] if not s["loaded"]), None)
    if absent is None:
        return result
    skill = absent["name"]
    step = {"id": "skill-load", "skill": skill, "command": None,
            "why": f"Load {skill} for this phase, read {', '.join(absent['sections'])}, then follow its first step to record "
                   f"the files/sections with `lapis-design skill loaded --task {task} --skill {skill} --context "
                   "<current-context> --read <skill-path/SKILL.md> --read '<reference-path>#<heading>'` "
                   "(repeat --read). This is a procedure step, not a review or quality pass."}
    return {**result, "state": "needs-step", "step": step, "then": result["step"], "reason": step["why"]}


def main(argv=None, prog="lapis-design skill loaded") -> int:
    parser = argparse.ArgumentParser(prog=prog, description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--task", required=True)
    parser.add_argument("--skill", required=True, choices=REQUIRED)
    parser.add_argument("--context", required=True)
    parser.add_argument("--read", required=True, action="append", dest="reads")
    args = parser.parse_args(argv)
    if not attempts.TASK.fullmatch(args.task):
        parser.error("--task must be a task id")
    try:
        records = []
        for name in args.reads:
            filename, mark, heading = name.partition("#")
            file = Path(filename).resolve()
            skill_root = file.parent if file.name == "SKILL.md" else file.parent.parent
            if skill_root.name != args.skill:
                raise ValueError(f"{file} is not inside the {args.skill} skill")
            relative = file.relative_to(skill_root).as_posix() + ("#" + heading if mark else "")
            records.append({"section": relative, "file": str(file), "heading": heading if mark else None,
                            "sha256": _digest(file, heading if mark else None)})
        missing_sections = set(required(args.root, args.task, args.skill)) - {r["section"] for r in records}
        if missing_sections:
            raise ValueError("read the required sections: " + "; ".join(sorted(missing_sections)))
        target = path(args.root, args.task, args.skill)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"version": 0, "task": args.task, "skill": args.skill,
                                     "context": args.context, "reads": records}, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"skill loaded: {exc}", file=sys.stderr)
        return 2
    print(f"skill loaded: {args.skill} ({args.context}) -> {target}")
    return 0
