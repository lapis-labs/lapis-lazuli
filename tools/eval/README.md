# Skill-effectiveness evaluation kit

Maintainer tooling for one question: **whether and how the LapisLazuli skills change what an agent builds,
compared with the same agent, model, and prompt without them.** It runs paired sessions of a coding
agent, scores what each session built with the repository's own checkers, and prepares a blind review
sheet for a human or a critic. It is not part of the wheel or the sdist (`pyproject.toml` packages only
`cli/` and ships `src/shared`) and is never called by a skill. Its tests run in CI; CI never starts an
agent.

With two replicates per task the result is an anecdote with numbers, not a benchmark: read it as
"where do the arms differ and why", never as a percentage.

## Protocol

1. **Paired runs.** Each task runs in two arms, *with* and *without* skills, with the same model,
   reasoning effort, sandbox, and prompt (`tasks.yaml`, sent unchanged). Runs are sequential. For each
   replicate the order of the tasks and, per task, of the two arms is shuffled from a recorded seed.
2. **Harness.** `codex exec --ignore-user-config --ignore-rules --sandbox workspace-write --ephemeral
   --json -o last-message.txt -c features.apps=false -C <project> -m <model> -` with the prompt on stdin.
   Auth stays the user's own login: nothing is copied, and the runner stops when `codex login status`
   fails. `features.apps=false` switches off the connector apps of the operator's account in every run, so
   no agent can call a tool of that account. The agent gets an allow-listed environment, not the
   operator's: `PATH`, `LANG`, `LC_*`, `TERM`, a scratch `HOME` and `TMPDIR`, and `CODEX_HOME` (where the
   login is; `--ignore-user-config` still reads `auth.json` there). API keys, tokens, proxy settings, and
   the user name are not passed on.
3. **Isolated project.** Every run gets its own empty folder (`project/`, a git repository so Codex
   takes it as the project root) under the out folder, never inside this repository.
4. **Skills.** The with arm receives copies of the task's `dist/skills/<skill>/` trees in
   `project/.agents/skills/` (Codex's project-local skill folder, `install/harnesses.yaml`); the
   without arm receives none. `run.json` records the sha256 of the copied tree, per skill and in total,
   and each copy is compared with `dist/`.
5. **Nothing else teaches the agent.** Codex would also load skills from the user's own folders
   (`~/.agents/skills`, `$CODEX_HOME/skills`, bundled system and plugin skills). The runner gives each
   agent a scratch `HOME` and `TMPDIR` (the real `CODEX_HOME` is kept for the login), switches off
   every skill outside the project with `skills.config`, and reads the list back from the model-free
   `codex debug prompt-input`. If any run's skill list is not exactly its arm's (with: the task's
   skills; without: none), the runner stops before the first session. The same probe records whether
   Codex injects a global `AGENTS.md`.
6. **No local fonts, no local inventory.** The scratch `HOME` hides the user's caches; the lazuli
   font roots point at an empty folder, so an agent that runs `lazuli local fonts` sees no fonts and
   nothing about the maintainer's machine goes to the model.
7. **Same tools for both arms.** `lapis-design` and `lazuli` are put on the agent's `PATH` through
   `OUT/bin` for both arms, so the with arm can run the commands its skills name.
8. **Scoring happens afterwards, on this machine, by us.** `score.py` serves the produced site on a
   loopback port and runs the checkers; the agent's own claims are not read. The checkers get the same
   environment allow-list as the agents (plus a scratch `HOME` and the pinned variables below), and read a
   font database built from OFL fonts only and never the maintainer's own lazuli database (see "The
   evaluation font database").

### What the checkers do here

| Step | Command | Recorded |
|---|---|---|
| Render | `lapis-design render check URL --task <task> [--plan <plan>]`, default widths | ok, or `not scored` with the reason |
| Behavior | `lapis-design behavior check URL --task <task> --stub <stub> [--plan] --extract` (tasks that name a stub) | ok, probe coverage (`ran`, `partial`, `skipped`), or the reason |
| Lint | `lapis-design slop lint --source <project> [--plan] [--extract] [--session] [--lock]` | blocking, total, open, and skipped findings per layer (`plan`, `source`, `render`, `behavior`) |
| Copy | open `copy.*` findings of the lint's render layer | findings per 1,000 words, with the word count |

- The plan layer runs only when the agent wrote `.lapis/plans/<task>.yaml` inside the project (the prompt
  names the task id, which the `lapis` skill uses as the plan's file name). Otherwise the cell says
  `no plan`; any other plan file is listed under `plan.other_plans` in `score.json` and is not scored. A
  plan that stops the render, behavior, or lint step is dropped for a retry and the reason is kept, and
  the plan layer reads `plan rejected`. A plan, or a `.lapis/fonts.lock.json`, that is a link resolving
  outside the project is not given to any checker: `plan.status` or `lock.status` says `outside`, and
  the plan layer reads `plan outside`.
- `total` counts every finding of a layer, including findings a rule could not judge (`skipped`);
  `open` counts the judged ones. A run without a plan has more skipped findings, so compare `blocking`
  and `open` before `total`.
- When `slop lint` reports source links it did not read (`scope.unread_links.source`: a link out of the
  project, or a folder that is a link), the source layer reads `source links unread` and counts for
  nothing, because its numbers would describe only the part of the project that was read. The paths are
  kept under `checkers.lint.unread_links` in `score.json`.
- **Words** are counted as the copy detectors count them: whitespace-separated tokens that hold a letter
  or digit, over the viewport with the most text (ties to the widest), without `code` and `data` runs.
  Copy findings use the render layer only, because the plan's strings have another denominator (they are
  reported as `plan_findings`).
- A checker that could not run is `not scored` with its reason and appears as an empty cell in the CSV,
  never as zero. Means use only the runs that scored a column, and say how many did.
- Copy detection is lexical for Korean unless the optional analyzers are installed
  (`uv sync --extra cjk`, ~340 MB); the lint report records which analyzers ran under `analyzers`. Score
  every run of one comparison with the same environment. The font rules read the evaluation font database
  (below) and never the maintainer's own; `score.json` records its sha256 under `font_db`, so scores made
  with different databases can be told apart. A `score.json` with no `font_db` record was made before
  that, with the checkers reading the maintainer's own database: it counts as not scored. `score.py`
  scores it again (and needs `--font-db`), and the summaries, the export, and the review refuse it.

## Tasks

| Id | Prompt | Skills (with arm) | Checks |
|---|---|---|---|
| `kiln-landing-ko` | Korean mobile-first landing for a pottery class studio with a reservation call to action; facts are given, nothing else may be invented; concept differs from `src/shared/plan/example.plan.yaml` (classes, not a firing log). **In-domain:** the same field as the skills' own examples (pottery), so a difference here says less about other fields | `lapis`, `lps-copy`, `lps-system` | render, lint |
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

# 3. Score every run, then build the blind sheet. --font-db is the evaluation font database (below).
uv run --no-sync python tools/eval/score.py ~/.cache/lapis-eval/NAME --font-db /path/to/eval-fonts.db
uv run --no-sync python tools/eval/review.py ~/.cache/lapis-eval/NAME

# 4. To hand results to someone: numbers, codes, and hashes only, built from an allow-list (see below).
uv run --no-sync python tools/eval/share.py ~/.cache/lapis-eval/NAME /tmp/lapis-eval-share
```

- `run.py --dry-run` still runs the model-free `codex debug prompt-input` probe, so the skill isolation
  is verified; it never runs `codex exec`.
- `--resume` (with the same `--out`) skips runs that completed, failed, or timed out and prepares the
  rest again, so a run recorded as `interrupted` is repeated. An option left out takes the manifest's
  value; a `--model`, `--effort`, `--sandbox`, or `--network` that is given and differs from the
  manifest is refused, because every run of a comparison shares one setting. `--resume` also refuses,
  changing nothing, while a run recorded as `running` has a Codex process (`pid` in `run.json`) that is
  still alive: wait for it or stop it. A process that has ended but is not yet collected by its parent (a
  zombie) does not count; when only members of its process group are left, the refusal names
  `kill -- -PID`. `--timeout` (default 2400 s) stops a session and records
  `timed_out`. The runner exits 1 when any session did not complete; the records are kept and still
  scorable.
- Ctrl-C, SIGTERM, and SIGHUP stop a session the same way: Codex's whole process group is stopped, the
  run is recorded `interrupted`, and the runner exits with 128 plus the signal number (130, 143, 129).
  SIGKILL cannot be caught; Codex then keeps running and `--resume` refuses until it ends.
- `--tasks ID[,ID]` and `--replicates N` narrow a run; a first real run of one task with one replicate
  shows whether the event stream parses (token usage, skills read) before the full set.
- `score.py` skips runs that already have a `score.json` with a `font_db` record (`--rescore` redoes them,
  `--run ID` picks one, `--summary-only` rebuilds the tables). A `score.json` without that record is
  scored again, which needs `--font-db`; `--summary-only` refuses it. A run is scored whatever its
  status, so a folder from `--dry-run` can be filled by hand (copy a site into `runs/<id>/project/`) to
  try the whole pipeline.
- `review.py --seed N` makes the candidate labels reproducible. The answer key goes to
  `OUT/review.key.json`, beside `review/` and never in it.

### The evaluation font database

The font rules of the lint read measured fonts from a lazuli database. `score.py` does not use yours: it
requires `--font-db`, a database built from OFL fonts only, and runs every checker with that file as
`LAZULI_DB`, with HOME and the cache folders pointing at an empty scratch folder, so no code path can find
your own database at its usual place, and with `LAZULI_FONT_ROOTS` naming one empty folder there, so no
checker lists the fonts on this computer. Measurements of Adobe Fonts faces never reach the lint's font rules
that way. Build the database once, outside this repository, from a folder of OFL fonts (the
`lazuli-models` dataset keeps one):

```bash
LAZULI_FONT_ROOTS="user=/path/to/ofl-fonts" LAZULI_DB=/path/to/eval-fonts.db \
  uv run --no-sync lazuli local fonts --summary
```

`LAZULI_FONT_ROOTS` replaces lazuli's font folders with that one and turns the Core Text listing of Adobe
Fonts off; `LAZULI_DB` is a new file, so your own database is neither read nor written. `score.py` refuses
a database that is missing, holds no fonts, holds an Adobe Fonts face, or has writes that are not in the
file yet, and prints its face and family counts. It cannot tell an OFL font from another font in a folder,
so the folder is the check: put nothing else in it. The hash in `score.json` names the exact file.

### Sandbox

`--sandbox workspace-write` is the default. Verified with `codex sandbox` on macOS (Codex 0.158.0):
inside it Chromium cannot start, and loopback needs `--network`. So an agent there **cannot run
`render check` or `behavior check`**; it can still run `plan check`, `slop lint --plan/--source`, and
`lazuli` (with a writable scratch `HOME`). The skills tell agents to close the loop with a render check, so
the with arm is measured without that step. `--sandbox danger-full-access` gives the agents the whole
machine (the scratch `HOME` and the empty font roots are conventions, not a boundary); use it only when
you accept that and want the skills' full loop.

`--sandbox danger-full-access` and `--network` are for an **evaluation-only account**: a separate macOS
user or a virtual machine with its own Codex login and nothing else on it. The agent runs with the login
in `CODEX_HOME` readable, and with either option it can send what it reads anywhere. The allow-listed
environment keeps the operator's other credentials out; it does not hide what the account's files hold.
Do not use either option in the account that holds your own keys, mail, or repositories.

## Run records and sharing

Run records never go into the repository or a bundle. A run folder holds the agent's whole conversation
(`events.jsonl`), its projects, and, in folders from older versions, paths and skill names that identify
the user. `run.json` and `isolation.json` count the user's own skills (`outside_before`,
`disabled_count`) and never name them, and `command.txt` shows paths relative to the run folder with the
`skills.config` list reduced to a count. What leaves the machine goes through the export:

```bash
uv run --no-sync python tools/eval/share.py OUT DEST
```

`DEST` is a new or empty folder outside this repository and outside `OUT`. The export writes
`manifest.json`, `summary.md`, `summary.csv`, and per run `run.json`, `score.json`, `isolation.json`,
`command.txt`, and `prompt.txt`, and it copies none of them. It builds each again from an allow-list:
the fields the file may hold, and for each field a type (a count or a number, a flag, one word of a short
list, a hash, a timestamp, a short token such as a model name, or the name of one of this kit's own
skills). A field that is not on the list, or whose value is not of its type, is left out wherever it
sits, keys included, so a field added later or text an agent wrote cannot leave by being overlooked.
Reasons become the `code` words `score.py` writes; errors, other plan files, refused links, skipped
folders, and shared Codex files become counts; `thread_id`, `pid`, and the Codex executable are not
exported; skill names that are not this kit's own become `<other-skill>`. `command.txt` keeps only the
lines `run.py` writes, with the executable shown as `codex`. `prompt.txt` becomes `Task id: <id>` when it is
this kit's prompt for that task (compared by hash) and is left out otherwise. The two summaries are built
again from the exported records and never copied. Project trees, scratch homes, transcripts, stderr logs,
last messages, `score/`, and the review folder with its key are not exported. The export refuses a run
whose event log shows an Adobe tool call and a `score.json` with no `font_db` record, and it stops, writing
nothing, when a model name or version holds the name of the account that ran the evaluation.

## Layout of an out folder

```text
OUT/
  manifest.json            model, effort, seed, codex version, repo commit, skill digests, planned order
  bin/                     lapis-design and lazuli links on the agents' PATH
  runs/<task>.r<n>.<arm>/
    project/               the agent's folder (.git, and .agents/skills/ in the with arm)
    home/                  the scratch HOME (with an empty fonts/ folder and tmp/, the agent's TMPDIR)
    prompt.txt  command.txt  isolation.json      what was sent, run, and verified
    events.jsonl  stderr.log  last-message.txt   Codex output (after a real run)
    run.json               arm, digests, isolation, model, harness, Codex pid, start/end, exit, usage, skills read
    score.json  score/     checker results; render.json + render.shots/, behavior.json, lint.json, logs/
  summary.md  summary.csv  per-run rows, arm means, and with-minus-without
  review/                  sheet.md, scores.csv, and anonymous <task>/<A|B|...>/{shots,site}
  review.key.json          label -> run and arm; beside review/ so that handing over review/ never hands over the key
  .sig.key                 the signature key scoring uses, so scoring never touches the user cache
```

## Reading the results

- **`run.json`**: `status` (`completed`, `failed`, `timed_out`, `interrupted`), `exit_code`,
  `duration_s`, `pid` (Codex's process id; `--resume` checks it while the status is `running`), `usage`
  (Codex's summed `turn.completed` counts, null when Codex reports none), and `session`: `skills_read`
  (skills the agent opened; a with-arm run that never opened a skill was not really treated),
  `tools_run` (`lapis-design plan check`, ... counts), `commands`, `errors`. `isolation` says how many
  skills of the user's own Codex saw and switched off, which project skills the run saw, and whether
  that was verified.
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
  per task). Only then open `review.key.json` (beside `review/`; label to run and arm). A page's own
  source can still show an arm's habits (naming, comments); judge screenshots first.

## Known limits

- **Shared instructions.** `$CODEX_HOME/AGENTS.md`, hooks there, and Codex's built-in instructions load
  in both arms; the manifest lists which shared files exist (by short hash). If such a file carries design
  guidance it narrows the difference. For a case study, run on a machine without one.
- **The probe is not the run.** `codex debug prompt-input` has no `--ignore-user-config`, so it may list
  plugin skills that the real run would not load; that only over-disables. Whether `skills.config`
  matches a folder or a `SKILL.md` path differs from the documentation on 0.158.0 (the file matches), so
  both are listed and the result is read back.
- **What real sessions showed.** Twelve real sessions have run (Codex 0.158.0, `workspace-write`, no
  network, 2026-09-29: eight paired sessions of both tasks, then four with-arm sessions). Their event
  streams held `thread.started`, `turn.started`, `turn.completed`, and `item.*` events of
  `command_execution`, `file_change`, `agent_message`, and `web_search`, and the parser read usage, commands,
  and skills from them. Not observed: any other model, harness version, or sandbox; a session that calls a
  connector tool; and that a scratch `HOME` leaves the model session untouched, which stays an assumption.
- **Connector tools.** Codex can offer the apps (connectors) of the operator's account to an agent, and the
  `apps` feature is on by default (`codex features list`). `run.py` passes `-c features.apps=false` in
  every run, both arms, and `command.txt` shows it; the twelve sessions above ran before it did. Whether
  that leaves the model with no tool of that kind was checked only through `codex features list`, which
  shows `apps` off with the flag. `score.py`, the summaries, the export, and the review also refuse a run
  whose event log shows a call to an Adobe tool, because what such a call returns is Adobe data; move that
  run folder out and go on with the rest.
- **Rendering account.** Chromium on macOS finds the font names of a page's CSS through the operating
  system's font list, and that list can include Adobe Fonts activated for the account (not checked).
  Render in an account where no Adobe Fonts are activated; until such an account is in use, scores made
  where they are can include their shapes in the page measurements, and `score.json` cannot tell.
- **Sandbox** (see above), **no network** by default, and **a single model and effort**: results say
  nothing about other models or harnesses.
- Behavior checks depend on the page calling `POST /api/signup`; a page that renders the form but posts
  elsewhere gets probe coverage `partial` or `skipped`, which the table shows.
- **Links.** A link in the produced site whose target is outside the project is answered with 403 by the
  scoring server and listed under `site.refused_links` in `score.json`; `review.py` refuses to copy a site
  that holds one. A conventional site folder (`public`, `dist`, ...) that is itself a link out of the
  project is passed over and listed under `site.skipped_roots`; if nothing else is left, the run is
  `no site`. A plan or fonts lock that is a link resolving outside the project is not given to the
  checkers (`plan.status` and `lock.status` say `outside`). The lint step (`slop lint --source`) does not
  read a source file that is a link resolving outside the project or follow a folder that is a link, and
  says so on stderr, which `score/logs/lint.txt` keeps; the source layer of such a run reads
  `source links unread`.
- The prompts are English with Korean names and copy; a fully Korean prompt may behave differently.
- Ranking and counts from two runs per arm are anecdotal; add replicates before believing a difference.
