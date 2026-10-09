"""`lapis-design next`: the one step of the LapisLazuli procedure that is still missing, read from the files.

The procedure is: the brief record for a create run (`brief.py`: what the request, the project, and the subject
say, with the answers a person gave or the run assumed), the references record for a create run
(`references.py`: what the run looked at, with captures to show it), the plan, the plan check without a blocking
finding, the inputs the checks need (fonts lock, stub for an interactive page, asset ledger), the full render, the
behavior check for an interactive page, the full lint over every input, the critic, and the release gate's report.
`next` returns the first step that is not done, with the exact command or schema to follow, or `done`.

What counts as done is what the release gate already decides: `release_check.run(..., offline=True)` is
run on the files, and its findings that report a check that did not run or an input that is missing
(`release.NO_EVIDENCE`) say which step comes back. Nothing else is judged here, with three additions the
gate does not make: the plan check's own findings pick the plan step, a stub is validated before a
behavior check needs it, and a page with controls but no `flows` in the plan is sent back to the plan.

Done means the procedure is complete, not that the release passes: a blocking verdict is a result to
report. A step is also done when its failure record is fresh (`attempts.py`): the check was tried and
the environment, not an input, stopped it. So is the references step when the run declined it with a line of its
brief (`references.declined`): the user's own words forbade the lookups. A missing input, an invalid input, a timeout,
a finding, or a plan blocker never counts as done; the step that creates or fixes it comes back. So does a plan that
cannot be read: it is read the way every other tool reads YAML (`plan_check.parse_plan`), never leniently, and its
fault is named with its line and column. A blocking `release.procedure-order` (an unattended run whose page code
came before its brief, references, or plan, `order.py`) sends the run to `plan-order`.

While questions the run wrote for its user are unanswered (`waiting.py`), the state is `waiting-for-user`
instead: its step says to stop and wait, and `then` is the step that comes after the answers.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import yaml

from lapis_design import (asks, attempts, brief, critic_packet, draft, gaps, gate, owner, preview, references,
                          release_check, requirements, shared_dir, slice_step, taste, waiting)
from lapis_design.lint.cli import problems
from lapis_design.plan_check import PlanOverLimit, read_plan, yaml_reason
from lapis_design.summary import NOT_JUDGED

PAGES = ("index.html", "dist/index.html", "build/index.html", "public/index.html", "out/index.html")
CONTROLS = {"button", "input", "select", "textarea", "details", "dialog", "form"}
CONTROL_ROLES = {"button", "input", "dialog"}      # extract box roles of a page a visitor can act on
JOB_MAX_AGE_S = 2 * 3600                           # a background run older than this is not assumed alive
# the plan check's findings that name a step of their own; every other blocker is a plan fix
PLAN_STEPS = {"font.no-lock": "fonts-lock", "plan.uncompared-decision": "plan-explorations"}
# release.input-missing / input-stale, by the file the finding names: the step that makes it again
MISSING = {"extract": "render", "session": "behavior", "lint": "lint", "critic": "critic",
           "lock": "fonts-lock", "ledger": "ledger"}
STALE = {"session": "behavior", "lint": "lint", "critic": "critic"}
GENERIC_LOCK = ('Lock each named face the page uses with `lazuli lock "<family>" --role <role> --task {task}` (it '
                'records source, license, and delivery). A generic family has no file to lock: lock the named face '
                'it was compared with, as the lzl-fonts skill describes.')


class NextError(Exception):
    """The files cannot be read as a procedure state (a lazuli database that cannot be opened)."""


def resolve_task(root: Path, task: str | None = None) -> str | None:
    """`task`, else $LAPIS_TASK, else the task of the most recently written plan, set of questions, brief
    record, or references record under `root` (a run that has asked its questions or recorded its brief has no
    plan yet, and names the task by them)."""
    task = task or os.environ.get("LAPIS_TASK") or None
    if task:
        return task
    written = [*(root / ".lapis" / "plans").glob("*.yaml"),
               *(p for folder in ("questions", "answers", "references") for p in (root / ".lapis" / folder).glob("*.md")
                 if waiting.counts(p))]
    written.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return next((p.stem for p in written if attempts.TASK.fullmatch(p.stem)), None)


class _Controls(HTMLParser):
    found = False

    def handle_starttag(self, tag, attrs):
        if tag in CONTROLS:
            self.found = True


def _page(root: Path, given: str | None, task: str | None = None) -> tuple[str | None, Path | None]:
    """The page as the commands name it, and its file when it is one: the given page, else the first
    of the usual entry files (`PAGES`) that exists."""
    if task and draft.path(root, task).is_file():
        try:
            pages = draft.read(root, task)["pages"]
            shown = next((p for p in pages if given is None or p["url"] == given), None)
            if shown:
                file = next((root / p for p in shown["sources"] if Path(p).suffix == ".html"), None)
                return shown["url"], file
        except (OSError, ValueError, yaml.YAMLError):
            pass
    if given:
        return given, (root / given if "://" not in given else None)
    found = next((name for name in PAGES if (root / name).is_file()), None)
    return found, (root / found if found else None)


def _interactive(plan: dict, page: Path | None, extract: Any) -> bool:
    """Whether the page has something to act on: flows in the plan, a control in the page's markup, or a
    button, input, or dialog box in the render."""
    if plan.get("flows"):
        return True
    if page is not None and page.is_file():
        parser = _Controls()
        try:
            parser.feed(page.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            pass
        if parser.found:
            return True
    boxes = (box for view in (extract or {}).get("viewports", []) if isinstance(view, dict)
             for box in view.get("boxes", []) if isinstance(box, dict))
    return any(box.get("role") in CONTROL_ROLES for box in boxes)


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _newer(path: Path, inputs: list[Path]) -> bool:
    """`path` exists and no input is newer (the gate's own freshness test, by modification time)."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return False
    return all(not p.is_file() or mtime >= p.stat().st_mtime for p in inputs)


def _recorded(root: Path, task: str, step: str, inputs: list[Path]) -> bool:
    """A failure record of the environment for `step`, newer than what the step reads."""
    return attempts.read(root, task, step) is not None and _newer(attempts.path(root, task, step), inputs)


def _references_owed(root: Path, task: str, plan: Any = None) -> list[str]:
    """Why the references record is not one, or nothing when it is, when a fresh failure record of the
    environment (no network) stands in for it, or when the run declined the step with a line of its brief."""
    found = references.problems(root, task)
    if found and (_recorded(root, task, references.STEP, [references.record_path(root, task)])
                  or references.declined(root, task, plan)):
        return []
    return found


def _plan_or_none(root: Path, task: str) -> dict | None:
    """The task's plan when it exists and reads, else None: the plan's words only add to what the brief record says."""
    try:
        plan = read_plan(release_check.input_paths(root, task)["plan"])
    except (OSError, ValueError, yaml.YAMLError):
        return None
    return plan if isinstance(plan, dict) else None


def _stub_problem(path: Path) -> str | None:
    """Why `path` is not a stub `behavior check --stub` would load, or None."""
    if not path.is_file():
        return f"{path.as_posix()} does not exist"
    try:
        from lapis_design.stub.engine import StubEngine

        StubEngine.load(path)
    except Exception as exc:        # whatever stops the loader, the stub cannot be used as it is
        return f"{type(exc).__name__}: {(str(exc).splitlines() or [''])[0]}"
    return None


def job_running(root: Path, task: str, step: str = "behavior") -> bool:
    """Whether the background run of `step` that the step's command started is still going.

    The command writes `.lapis/logs/<task>.<step>.pid`. The run is over when its report or its failure
    record is newer than that file, when the process is gone or a zombie, or when the file is older than
    two hours, since a process id can be reused."""
    pidfile = root / ".lapis" / "logs" / f"{task}.{step}.pid"
    try:
        started = pidfile.stat().st_mtime
        pid = int(pidfile.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    if os.name == "nt" or pid <= 0 or time.time() - started > JOB_MAX_AGE_S:
        return False
    outputs = [release_check.input_paths(root, task)["session"], attempts.path(root, task, step)]
    if any(p.is_file() and p.stat().st_mtime >= started for p in outputs):
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    try:
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True,
                               timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return True
    return not state.startswith("Z")


def _step(step_id: str, why: str, command: str | None = None, schema: Path | None = None) -> dict:
    return {"id": step_id, "why": why, "command": command, **({"schema": str(schema)} if schema else {})}


def _requirements_step(task: str, reason: str) -> dict:
    return _step(requirements.STEP, requirements.why(task, reason), f"lapis-design requirements seal --task {task}")


def _brief(items: list[str], limit: int = 3) -> str:
    shown = "; ".join(items[:limit])
    return shown + (f"; and {len(items) - limit} more" if len(items) > limit else "")


def _finding_line(finding: dict) -> str:
    return f"{finding['rule_id']}: {finding['observed']}"


def _lock_commands(plan: dict, task: str) -> list[str]:
    roles = (((plan.get("tokens") or {}).get("type") or {}).get("roles")) or []
    commands: list[str] = []
    for role in roles:
        if isinstance(role, dict) and role.get("family") and role.get("role"):
            command = f"lazuli lock {shlex.quote(str(role['family']))} --role {role['role']} --task {task}"
            if command not in commands:
                commands.append(command)
    return commands


def evaluate(root: Path, task: str, page: str | None = None) -> dict:
    from lapis_design import integrity, skill_load

    root = root.resolve()
    observed = integrity.observe_task(root, task, "next")
    return skill_load.apply(root, task, _evaluate(root, task, page, observed["error"]))


def _evaluate(root: Path, task: str, page: str | None = None, integrity_error: str | None = None) -> dict:
    """The state of `task` under `root`: `{"task", "state", "step", "interactive", "reason"}`.

    `state` is `needs-step` with the one `step` to take (`id`, `why`, `command` or None, and `schema`
    when a file has to be written), or `done`. While the run's questions for its user wait for an
    answer, `state` is `waiting-for-user`, `step` says to stop, `then` is the step that comes after, and
    `waiting` names the questions and answers files. `page` is the page the render and behavior commands
    name; without it the usual entry file is used, and a page that cannot be found stays `<page>`. `done` and
    every wait on approval questions carry the owner block (`owner_block`, `owner.py`); `integrity_error` is what
    `integrity.observe` could not record, if anything.
    Raises NextError when the files cannot be read as a state."""
    root = root.resolve()
    result = _steps(root, task, page, integrity_error)
    step = result["step"]
    plan_exists = (root / ".lapis" / "plans" / f"{task}.yaml").exists()
    found = waiting.pending(root, task, "approval" if plan_exists else "plan", gate.load(root, task).get("waits"))
    asks.observe(root, task, step["id"] if step else "done", found)
    if found is None:
        return _marked(root, task, result)
    kind = found["kind"]
    approval = kind == "approval"
    shown = draft.links(root, task) if approval else []
    if approval and not shown and step is not None and slice_step.owed(root, task, _plan_or_none(root, task)):
        if step["id"] == slice_step.STEP:                    # approval questions with no rendered page ask for the slice
            return result
        asked = slice_step.step(task)
        return {**result, "state": "needs-step", "step": asked, "reason": asked["why"]}
    if approval and (shown or draft.path(root, task).is_file()):
        errors, summaries = draft.check(root, task, asked=shown)
        if errors:
            review = _step(draft.STEP, "Before showing the draft, review the exact page: " + _brief(errors)
                           + ". Record the review and summarize it, including unresolved findings, to the owner.",
                           f"lapis-design draft check --task {task}", shared_dir() / "release/draft.schema.yaml")
            return {**result, "state": "needs-step", "step": review, "reason": review["why"], "draft_review": summaries}
        result["draft_review"] = summaries
    if step is None:
        return result
    if kind == "brief" and (over := brief.questions_problem(root, task)):
        cut = _step(brief.STEP, brief.over_why(task, over))
        return {**result, "step": cut, "reason": cut["why"]}
    if unfit := _unfit(root, task, kind, step["id"]):
        return _prefixed(result, f"The questions in {found['questions']} (kind {kind}) do not wait: {unfit}.")
    if approval:
        block, sha8 = owner.write(root, task, {"integrity_error": integrity_error})
        result["owner_block"] = block
        if not owner.carries(_read_text(root / found["questions"]), sha8):
            paste = _step(draft.STEP, f"The questions for the owner must carry the owner block that lapis-design wrote "
                          f"from the files: paste .lapis/owner/{task}.md into {found['questions']} unchanged, so that "
                          f"its last line `{owner.MARKER} {sha8}` is in the file, and stop with the questions as your "
                          "last message. A block that is missing, or out of date because a record it reports changed "
                          f"since, does not count; run `lapis-design draft check --task {task}` after changing one.",
                          f"lapis-design draft check --task {task}")
            return {**result, "state": "needs-step", "step": paste, "reason": paste["why"]}
        if dead := preview.unreachable(shown):
            serve = _step(draft.STEP, preview.why(task, dead), preview.command(task, dead))
            return {**result, "state": "needs-step", "step": serve, "reason": serve["why"]}
        if (cut := slice_step.tall(root, task, shown)) and slice_step.owed(root, task, _plan_or_none(root, task)):
            return {**result, "state": "needs-step", "step": slice_step.step(task, cut), "reason": cut}
    wait = _step(waiting.STEP, waiting.why(task, found, step["id"]) +
                 (" Include the recorded draft review summary and every unresolved finding in that message."
                  if result.get("draft_review") else ""))
    return {**result, "state": waiting.STEP, "step": wait, "then": step, "waiting": found, "reason": wait["why"]}


def _prefixed(result: dict, text: str) -> dict:
    """`result` with `text` ahead of what its step says: the step is the one `next` would name anyway."""
    step = {**result["step"], "why": f"{text} {result['step']['why']}"}
    return {**result, "step": step, "reason": step["why"]}


def _marked(root: Path, task: str, result: dict) -> dict:
    """`result`, with the reminder to mark the kind of the questions file when it holds unanswered questions of no
    kind: such a file does not wait."""
    found = waiting.unmarked(root, task)
    if found is None or result["step"] is None:
        return result
    named = waiting.declared(_read_text(root / found))
    now = f"names `{named}`, which is no kind" if named else "declares no kind"
    return _prefixed(result, f"The questions in {found} {now}, so they do not wait. Mark the questions file's kind: "
                     f"its first line is `lapis-questions: {'|'.join(waiting.KINDS)}`, and the kind says what the file "
                     "holds (the lapis skill's \"Questions and kinds\" section).")


def _unfit(root: Path, task: str, kind: str, then: str) -> str | None:
    """Why the questions of `kind` are not in the shape that waits (the step stays `then`, the one `next` would name), or
    None when they are."""
    if kind == "ask":
        return (asks.shape_problem(_read_text(waiting.questions_path(root, task)))
                or asks.checkpoint_problem(root, task, then))
    return None


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _steps(root: Path, task: str, page: str | None, integrity_error: str | None = None) -> dict:
    """`evaluate` without the waiting state: the step the files call for."""
    paths = release_check.input_paths(root, task)
    paths["release"] = root / ".lapis" / "release" / f"{task}.json"
    stub = root / ".lapis" / "stub.yaml"
    shared = shared_dir()
    plan_rel = f".lapis/plans/{task}.yaml"
    check = f"lapis-design plan check {plan_rel}"
    shown, page_file = _page(root, page, task)
    target = shlex.quote(shown) if shown else "<page>"

    def state(step: dict | None, interactive: bool, reason: str | None = None) -> dict:
        return {"task": task, "state": "needs-step" if step else "done", "step": step, "interactive": interactive,
                "reason": reason or (step["why"] if step else "")}

    try:
        plan = read_plan(paths["plan"])
    except FileNotFoundError:
        if owed := brief.owed(root, task, planned=False):
            return state(_step(brief.STEP, owed), False)
        if reason := requirements.owed(root, task):
            return state(_requirements_step(task, reason), False)
        if found := _references_owed(root, task):
            return state(_step(references.STEP, references.why(task, found, planned=False)), False)
        answers = waiting.answers_path(Path('.'), task).as_posix()
        if declined := references.declined(root, task) if references.problems(root, task) else None:
            cited = (f"the brief record {answers} in its `context.other`: the brief, and the decisions with the candidates "
                     f"compared for each. The references were declined with the user's own line, \"{declined['brief_line']}\", "
                     "so nothing is looked up: take the candidates from local material (installed fonts with `lazuli "
                     "local fonts`, the project, the brief's facts) and say so in their `source`, and keep or reject "
                     "every default that applies.")
        else:
            cited = (f"the brief record {answers} and the references record "
                     f"{references.record_path(Path('.'), task).as_posix()} in its `context.other`: the brief, the "
                     "decisions and the candidates compared for each, what the references taught (in `references` "
                     "and the candidates' sources), and a keep or reject on every default that applies.")
        return state(_step("plan", f"Write the plan at {plan_rel} before any code or check, and cite {cited} The "
                           f"schema is below and an example is {shared / 'plan/example.plan.yaml'}. "
                           "Then run the command to see what blocks.", check, shared / "plan" / "schema.yaml"), False)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        hint = (" Fix the YAML at that position (quote a string that holds `?`, `:`, `#`, or `,` inside `{ }` or "
                "`[ ]`, or write the mapping in block style), then run the command." if isinstance(exc, yaml.YAMLError)
                else "")
        return state(_step("plan-fix", f"{plan_rel} cannot be read: {yaml_reason(exc)}.{hint}", check,
                           shared / "plan" / "schema.yaml"), False)
    if isinstance(plan, PlanOverLimit) or not isinstance(plan, dict):
        why = plan.problem if isinstance(plan, PlanOverLimit) else "the plan is not a mapping"
        return state(_step("plan-fix", f"{plan_rel}: {why}", check, shared / "plan" / "schema.yaml"), False)
    if plan.get("mode") == "create":
        if owed := brief.owed(root, task, planned=True):
            return state(_step(brief.STEP, owed), False)
        if reason := requirements.owed(root, task):
            return state(_requirements_step(task, reason), False)
        if found := _references_owed(root, task, plan):
            return state(_step(references.STEP, references.why(task, found, planned=True)), False)

    interactive = _interactive(plan, page_file, _json(paths["extract"]))
    try:
        gate = release_check.run(root, task, static=not interactive, offline=True)
    except ValueError as exc:
        if not str(exc).startswith(str(paths["plan"])):
            raise NextError(str(exc)) from exc
        return state(_step("plan-fix", str(exc), check, shared / "plan" / "schema.yaml"), interactive)

    findings = [f for f in gate["findings"] if f["blocking"]]

    def origin(finding: dict) -> str | None:
        refs = finding["evidence"].get("refs") or []
        return refs[-1] if refs else None

    # the plan check's findings are copied into the gate's report with the plan's path appended last
    from_plan = [f for f in findings if not f["rule_id"].startswith("release.") and origin(f) == str(paths["plan"])]
    if schema_findings := [f for f in from_plan if f["rule_id"].startswith("schema.")]:
        return state(_step("plan-fix", "The plan does not match its schema: "
                           + _brief([_finding_line(f) for f in schema_findings]), check,
                           shared / "plan" / "schema.yaml"), interactive)
    if interactive and not plan.get("flows"):
        return state(_step("plan-flows", "The page has controls (a button, an input, or a dialog) and the plan lists "
                           "no `flows`. Record each real flow with its goal, its start route, and how it ends: "
                           "without them the behavior check is not required, and that is not a reason to leave "
                           "them out.", check, shared / "plan" / "schema.yaml"), interactive)

    # which failure records stand in for a step, and the gaps in later reports they leave
    recorded = {
        "render": _recorded(root, task, "render", [paths["plan"]]),
        "behavior": interactive and _recorded(root, task, "behavior", [paths["plan"], stub]),
        "critic": _recorded(root, task, "critic", [paths["lint"], paths["extract"]]),
    }
    expected = set()
    if recorded["render"]:
        expected |= {release_check.lint_lacks_target("extract"), release_check.lint_lacks_layer("render")}
    if recorded["behavior"]:
        expected |= {release_check.lint_lacks_target("session"), release_check.lint_lacks_layer("behavior")}

    by_path = {str(paths[name]): name for name in ("extract", "session", "lint", "critic", "lock", "ledger")}
    dark = ((_json(paths["extract"]) or {}).get("meta") or {}).get("dark_theme") is True
    need: set[str] = set()
    out_of_order = ""
    for finding in findings:
        rule, observed = finding["rule_id"], finding["observed"]
        refs = finding["evidence"].get("refs") or []
        name = by_path.get(refs[0]) if refs else None
        if rule == "release.input-missing":
            need.add("stub" if observed.startswith("stub fixture not found") else MISSING.get(name, ""))
        elif rule == "release.input-stale":
            need.add(STALE.get(name, ""))
        elif rule == "release.width-missing" or (rule == "release.theme-missing" and dark):
            need.add("render")
        elif rule == "release.layer-missing" and observed not in expected:
            need.add("lint")
        elif rule == "release.critic-missing":
            need.add("critic")
        elif rule == "release.procedure-order":
            need.add("plan-order")
            out_of_order = observed
    if requirements.uncovered(root, task, _json(paths["critic"])):           # a critic that judged no row, or not every one
        need.add("critic")
    need -= {step for step, done in recorded.items() if done} | {""}
    from_plan_steps = {PLAN_STEPS.get(f["rule_id"], "plan-fix") for f in from_plan}

    if "plan-fix" in from_plan_steps:
        blockers = [f for f in from_plan if f["rule_id"] not in PLAN_STEPS]
        return state(_step("plan-fix", "The plan check blocks: " + _brief([_finding_line(f) for f in blockers])
                           + ". Run the command for the fix each finding names.", check,
                           shared / "plan" / "schema.yaml"), interactive)
    if "plan-explorations" in from_plan_steps:
        return state(_step("plan-explorations", "`plan.uncompared-decision` blocks: record each open decision in "
                           "`explorations` with two or more candidates, what they were compared on, the one chosen, and "
                           "why the runner-up lost. Compare them for real; do not invent a `fixed_by` or a keep to lift "
                           "it.", check, shared / "plan" / "schema.yaml"), interactive)
    if "plan-order" in need:
        return state(_step("plan-order", f"Page code came before the direction it should follow: {out_of_order}. Redo "
                           f"the direction from the brief. Read the brief record .lapis/answers/{task}.md and the "
                           "references record, and write the plan's `direction`, `layout`, and `explorations` as if the "
                           "page did not exist, citing the brief record in `context.other`. Then add the existing code as "
                           "one candidate (`source: existing-code`) of a `direction` exploration, compared on the same "
                           "terms as the others and with a reason the runner-up lost. Keep the code only if it wins; "
                           "rebuild the parts that lose. This step lifts when the plan cites the brief record and holds "
                           "that candidate; it does not judge whether the comparison was fair.", check,
                           shared / "plan" / "schema.yaml"), interactive)
    if why := slice_step.check(root, task, plan):
        return state(slice_step.step(task, why), interactive)
    if why := gaps.approval_problem(root, task, plan):
        return state(_step("approval-gaps", why), interactive)
    if "fonts-lock" in from_plan_steps or "fonts-lock" in need:
        commands = _lock_commands(plan, task)
        why = GENERIC_LOCK.format(task=task) + " " + (
            "The plan's roles: " + "; ".join(commands) + "." if commands else "")
        return state(_step("fonts-lock", why.strip() + " A missing or invalid lock is an input to make; never write "
                           "`.lapis/fonts.lock.json` by hand.", "; ".join(commands) or None,
                           shared / "fonts" / "lock.schema.yaml"), interactive)
    stub_problem = (_stub_problem(stub) if interactive and not recorded["behavior"] and {"behavior", "stub"} & need
                    else None)
    if stub_problem:
        return state(_step("stub", "Write .lapis/stub.yaml for the page's real flows, with synthetic data only (a page "
                           f"without an API still gets the minimal stub). Problem: {stub_problem}. An example is "
                           f"{shared / 'behavior/example.stub.yaml'}.", None,
                           shared / "behavior" / "stub.schema.yaml"), interactive)
    if "stub" in need:
        need.add("behavior")        # the last session names a stub that is gone; the one here is valid, so run again
    if "ledger" in need:
        return state(_step("ledger", "Write .lapis/assets.ledger.json listing every image, icon set, and generated "
                           "asset the page ships, with its origin and rights; a page with none lists none. An example "
                           f"is {shared / 'assets/example.assets.ledger.json'}.", None,
                           shared / "assets" / "ledger.schema.yaml"), interactive)

    log = f".lapis/logs/{task}.behavior.log"
    if "render" in need:
        return state(_step("render", "Capture every width (320, 390, 768, 1440 px, and dark where the page has a dark "
                           f"theme). A run narrowed by `--width` writes {task}.narrow.json and never counts.",
                           f"lapis-design render check {target} --task {task}"), interactive)
    if interactive and not recorded["behavior"] and job_running(root, task):
        return state(_step("behavior-wait", "The behavior check is still running in the background. Wait for it, then "
                           f"run `lapis-design next --task {task}` again; do not start a second run, and do not stop "
                           "while it runs.", f"sleep 60; tail -n 3 {log}"), interactive)
    if "behavior" in need:
        launch = (f"mkdir -p .lapis/logs && nohup lapis-design behavior check {target} --task {task} --plan {plan_rel} "
                  f"--stub .lapis/stub.yaml > {log} 2>&1 < /dev/null & echo $! > .lapis/logs/{task}.behavior.pid")
        return state(_step("behavior", "Run the full behavior check in the background, since it takes minutes and a "
                           f"tool call that waits for it can time out: run the command, then poll with `sleep 60; tail "
                           f"-n 3 {log}` until the report exists, and run `lapis-design next --task {task}`. If a "
                           f"run ended with no report, read {log}. A run narrowed by `--probe`, `--context`, `--box`, "
                           "or `--limit` never counts.", launch), interactive)
    if "lint" in need:
        refs = "".join(f" --ref {shlex.quote(str(ref['profile']))}" for ref in plan.get("references") or ()
                       if isinstance(ref, dict) and ref.get("profile"))
        extract = "" if recorded["render"] else f" --extract .lapis/renders/{task}.json"
        session = f" --session .lapis/behavior/{task}.json" if interactive and not recorded["behavior"] else ""
        mode = " --mode review" if plan.get("mode") in ("redesign", "repair") else ""
        return state(_step("lint", "Run the full lint with every input: a run left without one, or narrowed by "
                           "`--layer` or `--rule`, never counts.",
                           f"lapis-design slop lint --plan {plan_rel}{extract}{session} --source . "
                           f"--ledger .lapis/assets.ledger.json --lock .lapis/fonts.lock.json{refs}{mode} "
                           f"-o .lapis/lint/{task}.json"), interactive)
    if "critic" in need:
        packet = critic_packet.has_record(root, task)
        rows = requirements.rows(root, task)
        counted = (f"{len(rows)} rows, {len(requirements.uncovered(root, task, _json(paths['critic'])))} not judged yet"
                   if rows else "")
        owed = [f["observed"] for f in findings if f["rule_id"] in ("release.critic-missing", "release.input-stale")
                and (f["evidence"].get("refs") or [None])[0] == str(paths["critic"])]
        if packet:
            how = (f"Build the packet with `lapis-design critic packet --task {task}`, and run the critic on it in a "
                   "context that did not make the design, as the ultramarine skill describes (the `critic` agent, or "
                   "references/critic.md in a fresh session): give it the packet and the files it lists, nothing else. "
                   f"Its report, saved to .lapis/critic/{task}.json, names the packet in `target.packet` and judges "
                   f"every requirement row, change, and dispute in it ({counted or 'no requirement rows'})."
                   + (f" Now: {_brief(owed, 1)}." if owed else ""))
        else:
            how = ("Run the critic in a context that did not make the design, as the ultramarine skill describes (the "
                   "`critic` agent, or references/critic.md in a fresh session), and save its report to "
                   f".lapis/critic/{task}.json.")
        return state(_step("critic", f"{how} Only when this harness cannot start a separate "
                           f"context, record that with `lapis-design next --task {task} --unavailable critic --reason "
                           "\"<why>\"`; the release gate still reports the critic as missing and no independent "
                           "review ran, and the owner block says the requirements were not judged.",
                           f"lapis-design critic packet --task {task}" if packet else None,
                           shared / "slop" / "finding.schema.yaml"), interactive)

    release_inputs = [paths[n] for n in ("plan", "lock", "ledger", "extract", "session", "lint", "critic")]
    release_inputs += [attempts.path(root, task, s) for s in ("render", "behavior", "critic")]
    document = _json(paths["release"])
    current = (isinstance(document, dict) and not problems(document, "report")
               and (document.get("target") or {}).get("task") == task and _newer(paths["release"], release_inputs))
    release_record = attempts.read(root, task, "release") if _recorded(root, task, "release", release_inputs) else None
    if not current and not release_record:
        static = "" if interactive else " --static"
        return state(_step("release", "Run the release gate on these reports; it can find that the work does not "
                           "ship, and that verdict is the result to report, not a step to repeat. Add `--offline` "
                           "when the network is not available (catalog font licenses then stay unchecked).",
                           f"lapis-design release check --task {task}{static}"), interactive)

    if current:
        summary = document["summary"]
        verdict = (f"the release gate's report has {summary['blocking']} blocking findings ({summary['defects']} "
                   f"defects, {summary['no_evidence']} without evidence)")
    else:
        verdict = f"the release check could not run here ({release_record['reason']})"
    looked = ""
    if plan.get("mode") == "create" and references.problems(root, task):
        if declined := references.declined(root, task, plan):
            looked = (f" No references were looked at: the user's line \"{declined['brief_line']}\" declined the "
                      "lookups, so the plan rests on local material.")
        elif skipped := attempts.read(root, task, references.STEP):
            looked = f" No references were looked at: {skipped['reason']}."
    floor = ""
    if current and not document["summary"]["blocking"]:
        floor = f" No defects found; not judged by any check: {NOT_JUDGED}."
    reason = (f"The procedure is complete; {verdict}.{looked}{floor}{taste.done(root, task, plan)} Report that verdict, "
              "the checks that did not run and why, and what remains for the user. Passing the gate is not required "
              "to stop, and a pass says nothing about whether the page is good.")
    block, sha8 = owner.write(root, task, {"verdict": verdict, "integrity_error": integrity_error})
    return {**state(None, interactive, f"{reason} Paste the owner block unchanged ahead of your own summary: it is in "
                    f"`owner_block` and in .lapis/owner/{task}.md, and its last line is `{owner.MARKER} {sha8}`."),
            "owner_block": block}


def _text(result: dict) -> str:
    step = result["step"]
    shown = f"\n\n{result['owner_block'].rstrip()}" if result.get("owner_block") and (
        not step or step["id"] == draft.STEP) else ""
    if not step:
        return f"next: done ({result['task']})\n  {result['reason']}{shown}"
    lines = [f"next: {step['id']} ({result['task']})"]
    if step["command"]:
        lines.append(f"  run: {step['command']}")
    if step.get("schema"):
        lines.append(f"  schema: {step['schema']}")
    lines.append(f"  why: {step['why']}")
    return "\n".join(lines) + shown


def main(argv: list[str] | None = None, prog: str = "lapis-design next") -> int:
    ap = argparse.ArgumentParser(prog=prog, description=__doc__.split("\n")[0], allow_abbrev=False)
    ap.add_argument("--task", help="the plan's task id (default: $LAPIS_TASK, else the newest plan under --root)")
    ap.add_argument("--root", type=Path, default=Path("."), help="the project folder (default: .)")
    ap.add_argument("--url", help="the page the render and behavior commands name: an HTML file or an address on a "
                    "host that is ours (default: index.html, or one in dist/, build/, public/, out/)")
    ap.add_argument("--json", action="store_true", help="print the state as JSON")
    ap.add_argument("--unavailable", choices=["critic", "references"],
                    help="record that this step cannot run here, with --reason: a harness that cannot start a "
                    "separate context for the critic, or no network for the references")
    ap.add_argument("--reason", help="why --unavailable applies")
    ap.add_argument("--declined", choices=list(attempts.DECLINABLE),
                    help="decline this step with the user's own words, with --brief-line: the request forbids the "
                    "lookups the step needs and nobody can be asked")
    ap.add_argument("--brief-line", help="the line of the request that forbids them, exactly as the brief record or "
                    "the plan's brief.constraints holds it")
    args = ap.parse_args(argv)
    task = resolve_task(args.root, args.task)
    if not task:
        ap.error("no plan found under .lapis/plans; pass --task")
    if not attempts.TASK.fullmatch(task):
        ap.error("--task must be a plan task id (lowercase letters, digits, and hyphens)")
    if bool(args.unavailable) != bool(args.reason and args.reason.strip()):
        ap.error("--unavailable and --reason go together")
    if bool(args.declined) != bool(args.brief_line and args.brief_line.strip()):
        ap.error("--declined and --brief-line go together")
    if args.unavailable and args.declined:
        ap.error("--unavailable and --declined are two different records; give one")
    if args.unavailable:
        reason = args.reason.strip().splitlines()[0]
        if args.unavailable == references.STEP:
            if (probe := references.unreachable()) is None:
                print(f"next: the network is reachable from here ({references.PROBE_URL} answered), so no record of an "
                      "unreachable network was written. If the user's words forbid the lookups, decline the step with "
                      f"their line: `lapis-design next --task {task} --declined references --brief-line \"<the line>\"`; "
                      "otherwise run the step", file=sys.stderr)
                return 2
            reason = f"{reason} (probe of {references.PROBE_URL}: {probe})"
        command = ["lapis-design", "next", "--task", task, "--unavailable", args.unavailable]
        if attempts.record(args.root, task, args.unavailable, command, None, reason) is None:
            print(f"next: the {args.unavailable} record cannot be written under {args.root / '.lapis'}", file=sys.stderr)
            return 2
    if args.declined:
        line = references.clean_line(args.brief_line)
        if problem := references.declined_problem(line, args.root, task, _plan_or_none(args.root, task)):
            print(f"next: the {args.declined} step was not declined: {problem}", file=sys.stderr)
            return 2
        command = ["lapis-design", "next", "--task", task, "--declined", args.declined, "--brief-line", line]
        if attempts.record_declined(args.root, task, args.declined, command, line) is None:
            print(f"next: the {args.declined} record cannot be written under {args.root / '.lapis'}", file=sys.stderr)
            return 2
    try:
        result = evaluate(args.root, task, args.url)
    except NextError as exc:
        print(f"next: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else _text(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
