#!/usr/bin/env python3
"""Build a blind review sheet from scored runs: candidates without arm labels, for a human or a critic.

    uv run --no-sync python tools/eval/review.py OUT [--seed N]

Writes OUT/review/: `sheet.md` (candidates per task with screenshot and site paths, the task's
acceptance notes as a rubric, and a critic prompt), `scores.csv` (a blank score table to fill in), and
anonymous `<task>/<label>/{shots,site}` folders. The answer key (label -> run and arm) goes to
OUT/review.key.json, next to the review folder and never in it, so the folder can be handed to a
reviewer as is; keep the key closed until every candidate is judged. Screenshots and a copy of each
site (without hidden folders) are copied under anonymous names, so no path, file name, score, plan,
or agent message in the sheet says which arm produced a candidate. A link in a site that points
outside the run's project stops the build. The page's own source can still show habits of one arm;
judge the screenshots first.
"""
from __future__ import annotations

import argparse
import csv
import random
import shutil
import sys
from pathlib import Path

import evalkit as kit
from evalkit import KitError

SCALE = "0 = not met, 1 = partly, 2 = met"
CRITIC_PROMPT = """You are reviewing candidate designs for one task. You see only screenshots and the site folder of \
each candidate, labeled A, B, C, ... Do not try to work out how a candidate was made. For every acceptance note \
below, score each candidate 0 (not met), 1 (partly), or 2 (met) and give one sentence of evidence that names what \
you saw in a screenshot (file name) or in the site. Then rank the candidates from best to worst overall and say \
which single difference decided it. Judge the Korean text as a native reader would. Report in the format of \
scores.csv."""


def _candidates(out: Path) -> dict[str, list[dict]]:
    """Scored runs grouped by task: run folder, its score, and the render extract when there is one."""
    by_task: dict[str, list[dict]] = {}
    runs = kit.list_runs(out)
    kit.refuse_adobe_calls(runs, "build a review")
    for run_dir in runs:
        if not (run_dir / "score.json").is_file():
            continue
        run = kit.read_json(run_dir / "run.json")
        score = kit.read_json(run_dir / "score.json")
        extract_file = run_dir / "score" / "render.json"
        by_task.setdefault(run["task"], []).append({
            "dir": run_dir, "run": run, "score": score,
            "extract": kit.read_json(extract_file) if extract_file.is_file() else None})
    return by_task


def screenshot_plan(extract: dict | None) -> list[tuple[str, str]]:
    """(path relative to the extract, anonymous file name) for each width and theme, without the
    reduced-motion and browser-chrome variants."""
    plan = []
    for viewport in (extract or {}).get("viewports") or []:
        if viewport.get("reduced_motion") or viewport.get("browser_chrome") or not viewport.get("screenshot"):
            continue
        plan.append((viewport["screenshot"], f"{viewport['width']}-{viewport.get('theme', 'light')}.png"))
    return plan


def key_path(out: Path) -> Path:
    """Where the answer key goes: beside the review folder, so handing over `review/` never hands it over."""
    return out / "review.key.json"


def _hidden(name: str) -> bool:
    return name.startswith(".") or name == "node_modules"


def _refuse_outside_links(root: Path, project: Path | None) -> None:
    outside = kit.links_outside(root, project, skip=_hidden)
    if outside == ["."]:
        raise KitError(f"{root} is itself a link that points outside its project; the site folder must be "
                       "inside the project, then build the review again")
    if outside:
        raise KitError(f"{root} holds links that point outside its project: {', '.join(outside)}; "
                       "remove them, then build the review again")


def _copy_site(root: Path, target: Path, project: Path | None = None) -> None:
    """Copy a site folder without hidden entries or node_modules. Links are copied as links, never
    followed, and a link whose target is outside `project` (default: the folder) refuses the copy."""
    _refuse_outside_links(root, project)
    shutil.copytree(root, target, symlinks=True,
                    ignore=lambda _folder, names: [n for n in names if _hidden(n)])


def build(out: Path, seed: int, tasks: dict) -> dict:
    """Write the review folder; returns the key."""
    by_task = _candidates(out)
    if not by_task:
        raise KitError(f"no scored runs under {out}; run score.py first")
    for members in by_task.values():        # refuse before anything is written
        for member in members:
            if member["score"]["site"]["root"]:
                _refuse_outside_links(member["dir"] / member["score"]["site"]["root"],
                                      member["dir"] / member["run"]["project"])
    review = out / "review"
    if review.exists():
        shutil.rmtree(review)
    rng = random.Random(seed)
    key: dict = {"seed": seed, "candidates": {}}
    sheet = ["# Blind review sheet", "",
             "Judge each candidate from its screenshots first, then its site folder. Labels carry no meaning. "
             "The answer key is not in this folder; do not ask for it until every candidate is scored.", "",
             f"Score every acceptance note per candidate ({SCALE}), then rank the candidates of the task.", ""]
    rows = []
    for task_id, members in sorted(by_task.items()):
        rng.shuffle(members)
        task = tasks.get(task_id, {})
        sheet += [f"## {task_id}", "", task.get("title", ""), "", "### Candidates", ""]
        labels = []
        for index, member in enumerate(members):
            label = chr(ord("A") + index)
            labels.append(label)
            folder = review / task_id / label
            shots = folder / "shots"
            shots.mkdir(parents=True)
            copied = []
            for relative, name in screenshot_plan(member["extract"]):
                source = member["dir"] / "score" / relative
                if source.is_file():
                    shutil.copy2(source, shots / name)
                    copied.append(f"{task_id}/{label}/shots/{name}")
            site = member["score"]["site"]["root"]
            site_path = None
            if site:
                _copy_site(member["dir"] / site, folder / "site", member["dir"] / member["run"]["project"])
                site_path = f"{task_id}/{label}/site/index.html"
            key["candidates"][f"{task_id}/{label}"] = {
                "run": member["run"]["id"], "arm": member["run"]["arm"], "replicate": member["run"]["replicate"]}
            sheet += [f"**{label}**", "",
                      f"- Site: `{site_path}`" if site_path else "- Site: none (the run left no index.html)",
                      "- Screenshots: " + (", ".join(f"`{p}`" for p in copied) if copied else "none (no render)"), ""]
        sheet += ["### Acceptance notes", "",
                  "| # | note | " + " | ".join(labels) + " |", "|---|---|" + "---|" * len(labels)]
        for number, note in enumerate(task.get("acceptance", []), 1):
            sheet.append(f"| {number} | {note} | " + " | ".join("" for _ in labels) + " |")
        sheet += ["", "Rank (best to worst): ", ""]
        for label in labels:
            rows.append({"task": task_id, "label": label, "rank": "",
                         **{f"note_{n}": "" for n in range(1, len(task.get("acceptance", [])) + 1)}, "evidence": ""})
    sheet += ["## Critic prompt", "", "```text", CRITIC_PROMPT, "```", ""]
    (review).mkdir(exist_ok=True)
    (review / "sheet.md").write_text("\n".join(sheet), encoding="utf-8")
    width = max((len(t.get("acceptance", [])) for t in tasks.values()), default=0)
    columns = ["task", "label", "rank", *[f"note_{n}" for n in range(1, width + 1)], "evidence"]
    with open(review / "scores.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, restval="")
        writer.writeheader()
        writer.writerows(rows)
    kit.write_json(key_path(out), key)
    return key


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="review.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("out", type=Path, help="the folder run.py wrote; score it first with score.py")
    ap.add_argument("--seed", type=int, help="seed for the candidate labels (default: random, kept in review.key.json)")
    args = ap.parse_args(argv)
    try:
        out = args.out.expanduser().resolve()
        tasks = kit.load_tasks()
        seed = args.seed if args.seed is not None else random.SystemRandom().randrange(1 << 31)
        key = build(out, seed, tasks)
    except KitError as exc:
        print(f"review.py: {exc}", file=sys.stderr)
        return 2
    print(f"{len(key['candidates'])} candidates -> {out / 'review' / 'sheet.md'}\n"
          f"answer key (keep closed, never hand out with review/): {key_path(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
