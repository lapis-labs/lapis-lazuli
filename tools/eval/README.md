# Skill-effectiveness evaluation kit

Maintainer tooling that answers one question: **does an agent given the LapisLazuli skills produce
better work than the same agent, model, and prompt without them?** It runs paired sessions of a coding
agent, scores what each session built with the repository's own checkers, and prepares a blind review
sheet for a human or a critic. It is not part of the wheel or the sdist (`pyproject.toml` packages only
`cli/` and ships `src/shared`), not run in CI, and never called by a skill.

With two replicates per task the result is an anecdote with numbers, not a benchmark: read it as
"where do the arms differ and why", never as a percentage.

## Protocol

1. **Paired runs.** Each task runs in two arms, *with* and *without* skills, with the same model,
   reasoning effort, sandbox, and prompt (`tasks.yaml`, sent unchanged). Runs are sequential. For each
   replicate the order of the tasks and, per task, of the two arms is shuffled from a recorded seed.
2. **Harness.** `codex exec --ignore-user-config --ignore-rules --sandbox workspace-write --ephemeral
   --json -o last-message.txt -C <project> -m <model> -` with the prompt on stdin. Auth stays the
   user's own login: nothing is copied, and the runner stops when `codex login status` fails.
3. **Isolated project.** Every run gets its own empty folder (`project/`, a git repository so Codex
   takes it as the project root) under the out folder, never inside this repository.
4. **Skills.** The with arm receives copies of the task's `dist/skills/<skill>/` trees in
   `project/.agents/skills/` (Codex's project-local skill folder, `install/harnesses.yaml`); the
   without arm receives none. `run.json` records the sha256 of the copied tree, per skill and in total,
   and each copy is compared with `dist/`.
5. **Nothing else teaches the agent.** Codex would also load skills from the user's own folders
   (`~/.agents/skills`, `$CODEX_HOME/skills`, bundled system and plugin skills). The runner gives each
   agent a scratch `HOME` (the real `CODEX_HOME` is kept for the login), switches off every skill
   outside the project with `skills.config`, and reads the list back from the model-free
   `codex debug prompt-input`. If any run's skill list is not exactly its arm's (with: the task's
   skills; without: none), the runner stops before the first session. The same probe records whether
   Codex injects a global `AGENTS.md`.
6. **No local fonts, no local inventory.** The scratch `HOME` hides the user's caches; the lazuli
   font roots point at an empty folder, so an agent that runs `lazuli local fonts` sees no fonts and
   nothing about the maintainer's machine goes to the model.
7. **Same tools for both arms.** `lapis-design` and `lazuli` are put on the agent's `PATH` through
   `OUT/bin` for both arms, so the with arm can run the commands its skills name.
8. **Scoring happens afterwards, on this machine, by us.** `score.py` serves the produced site on a
   loopback port and runs the checkers; the agent's own claims are not read.

### What the checkers do here

| Step | Command | Recorded |
|---|---|---|
| Render | `lapis-design render check URL --task <task> [--plan <plan>]`, default widths | ok, or `not scored` with the reason |
| Behavior | `lapis-design behavior check URL --task <task> --stub <stub> [--plan] --extract` (tasks that name a stub) | ok, probe coverage (`ran`, `partial`, `skipped`), or the reason |
| Lint | `lapis-design slop lint --source <project> [--plan] [--extract] [--session] [--lock]` | blocking, total, open, and skipped findings per layer (`plan`, `source`, `render`, `behavior`) |
| Copy | open `copy.*` findings of the lint's render layer | findings per 1,000 words, with the word count |

- The plan layer runs only when the agent wrote `.lapis/plans/<task>.yaml` (the prompt names the task
  id, which the `lapis` skill uses as the plan's file name). Otherwise the cell says `no plan`; any other
  plan file is listed under `plan.other_plans` in `score.json` and is not scored. A plan that stops the
  render, behavior, or lint step is dropped for a retry and the reason is kept, and the plan layer reads
  `plan rejected`.
- `total` counts every finding of a layer, including findings a rule could not judge (`skipped`);
  `open` counts the judged ones. A run without a plan has more skipped findings, so compare `blocking`
  and `open` before `total`.
- **Words** are counted as the copy detectors count them: whitespace-separated tokens that hold a letter
  or digit, over the viewport with the most text (ties to the widest), without `code` and `data` runs.
  Copy findings use the render layer only, because the plan's strings have another denominator (they are
  reported as `plan_findings`).
- A checker that could not run is `not scored` with its reason and appears as an empty cell in the CSV,
  never as zero. Means use only the runs that scored a column, and say how many did.
- Copy detection is lexical for Korean unless the optional analyzers are installed
  (`uv sync --extra cjk`, ~340 MB); the lint report records which analyzers ran under `analyzers`. Score
  every run of one comparison with the same environment. The font rules read the maintainer's lazuli
  database when one exists; `score.json` does not hide that.

## Tasks

| Id | Prompt | Skills (with arm) | Checks |
|---|---|---|---|
| `kiln-landing-ko` | Korean mobile-first landing for a pottery class studio with a reservation call to action; facts are given, nothing else may be invented; concept differs from `src/shared/plan/example.plan.yaml` (classes, not a firing log) | `lapis`, `lps-copy`, `lps-system` | render, lint |
| `signup-recovery-ko` | Korean sign-up flow: field errors, server error, kept input, success state; one fixed endpoint, `POST /api/signup` | `lapis`, `lps-ux`, `lps-copy` | render, lint, behavior with `stubs/signup-recovery-ko.stub.yaml` |

`tasks.yaml` holds, per task: `prompt`, `skills`, `checks` (`render`, `lint`, `behavior: null | {stub}`)
and `acceptance` notes that only the reviewer sees. Add a task by adding an entry: the id is lowercase
words joined by hyphens, and the prompt must contain `Task id: <id>`. `evalkit.load_tasks` rejects
anything else.

The sign-up stub answers `POST /api/signup` with 201 and gives the driver synthetic name, email, and
password values; the failure answers (409, 422, 5xx) the prompt describes come from the driver's own
probes, not from the stub.

## How to run

```bash
cd lapis-lazuli
uv run --no-sync python tools/build/build.py --check          # dist/skills must match src/

# 1. Look before you spend anything: builds the folders and prints every command, starts no model.
uv run --no-sync python tools/eval/run.py --model MODEL --dry-run --out /tmp/lapis-eval-dry

# 2. The runs (2 tasks x 2 arms x 2 replicates = 8 sessions, in a shuffled order).
uv run --no-sync python tools/eval/run.py --model MODEL --effort LEVEL --replicates 2 --out ~/.cache/lapis-eval/NAME

# 3. Score every run, then build the blind sheet.
uv run --no-sync python tools/eval/score.py ~/.cache/lapis-eval/NAME
uv run --no-sync python tools/eval/review.py ~/.cache/lapis-eval/NAME
```

- `run.py --dry-run` still runs the model-free `codex debug prompt-input` probe, so the skill isolation
  is verified; it never runs `codex exec`.
- `--resume` (with the same `--out`) skips runs that completed, failed, or timed out and prepares the
  rest again, so a run recorded as `interrupted` is repeated. `--timeout` (default 2400 s) stops a
  session and records `timed_out`. The runner exits 1 when any session did not complete; the
  records are kept and still scorable.
- `--tasks ID[,ID]` and `--replicates N` narrow a run; a first real run of one task with one replicate
  shows whether the event stream parses (token usage, skills read) before the full set.
- `score.py` skips runs that already have a `score.json` (`--rescore` redoes them, `--run ID` picks
  one, `--summary-only` rebuilds the tables). A run is scored whatever its status, so a folder from
  `--dry-run` can be filled by hand (copy a site into `runs/<id>/project/`) to try the whole pipeline.
- `review.py --seed N` makes the candidate labels reproducible.

### Sandbox

`--sandbox workspace-write` is the default. Verified with `codex sandbox` on macOS (Codex 0.158.0):
inside it Chromium cannot start, and loopback needs `--network`. So an agent there **cannot run
`render check` or `behavior check`**; it can still run `plan check`, `slop lint --plan/--source`, and
`lazuli` (with a writable scratch `HOME`). The skills tell agents to close the loop with a render check, so
the with arm is measured without that step. `--sandbox danger-full-access` gives the agents the whole
machine (the scratch `HOME` and the empty font roots are conventions, not a boundary); use it only when
you accept that and want the skills' full loop.

## Layout of an out folder

```text
OUT/
  manifest.json            model, effort, seed, codex version, repo commit, skill digests, planned order
  bin/                     lapis-design and lazuli links on the agents' PATH
  runs/<task>.r<n>.<arm>/
    project/               the agent's folder (.git, and .agents/skills/ in the with arm)
    home/                  the scratch HOME (with an empty fonts/ folder)
    prompt.txt  command.txt  isolation.json      what was sent, run, and verified
    events.jsonl  stderr.log  last-message.txt   Codex output (after a real run)
    run.json               arm, digests, isolation, model, harness, start/end, exit, usage, skills read
    score.json  score/     checker results; render.json + render.shots/, behavior.json, lint.json, logs/
  summary.md  summary.csv  per-run rows, arm means, and with-minus-without
  review/                  sheet.md, scores.csv, key.json, and anonymous <task>/<A|B|...>/{shots,site}
  .sig.key                 the signature key scoring uses, so scoring never touches the user cache
```

## Reading the results

- **`run.json`**: `status` (`completed`, `failed`, `timed_out`, `interrupted`), `exit_code`,
  `duration_s`, `usage` (Codex's summed `turn.completed` counts, null when Codex reports none), and
  `session`: `skills_read` (skills the agent opened; a with-arm run that never opened a skill was not
  really treated), `tools_run` (`lapis-design plan check`, ... counts), `commands`, `errors`.
  `isolation` says which skills the run saw and whether that was verified.
- **`summary.md`**: one table per task. Each run row shows the render step, the four lint layers as
  `blocking/total (open)`, copy findings per 1,000 words (`n in W w`), tokens, and the skills read. The
  arm-means table follows, with a with-minus-without row. Read `blocking` first: requirement and
  contract rules gate, quality rules gate at P0-P1. A lower count for the with arm shows the skills' rules
  are met more often, not that the design is better; the checkers are the skills' own rules, so this is
  agreement with the skills, not independent validation. The review sheet is the independent part.
- **`summary.csv`**: the same numbers, one row per run plus `mean` and `delta` rows; empty means not
  scored, and the `*_status` columns say why.
- **Blind review**: give `review/sheet.md` and the candidate folders to a person or a critic that has
  seen neither the arms nor the scores. They fill `scores.csv` (each acceptance note 0-2, plus a rank
  per task). Only then open `key.json` (label to run and arm). A page's own source can still show an
  arm's habits (naming, comments); judge screenshots first.

## Known limits

- **Shared instructions.** `$CODEX_HOME/AGENTS.md`, hooks there, and Codex's built-in instructions load
  in both arms; the manifest lists which shared files exist (by short hash). If such a file carries design
  guidance it narrows the difference. For a number to publish, run on a machine without one.
- **The probe is not the run.** `codex debug prompt-input` has no `--ignore-user-config`, so it may list
  plugin skills that the real run would not load; that only over-disables. Whether `skills.config`
  matches a folder or a `SKILL.md` path differs from the documentation on 0.158.0 (the file matches), so
  both are listed and the result is read back.
- **Not yet observed on a real session** (none was started while building the kit): the exact fields of
  `codex exec --json` beyond the documented sample (the parser skips what it does not know), that a
  scratch `HOME` leaves the model session untouched, and how often the with arm opens its skills.
- **Sandbox** (see above), **no network** by default, and **a single model and effort**: results say
  nothing about other models or harnesses.
- Behavior checks depend on the page calling `POST /api/signup`; a page that renders the form but posts
  elsewhere gets probe coverage `partial` or `skipped`, which the table shows.
- The prompts are English with Korean names and copy; a fully Korean prompt may behave differently.
- Ranking and counts from two runs per arm are anecdotal; add replicates before believing a difference.
