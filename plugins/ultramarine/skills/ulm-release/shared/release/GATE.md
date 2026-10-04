# Release gate — v0

What `lapis-design release check` reads, what blocks, and what it writes. The `ulm-release` skill
runs the checks; the command runs the plan checks itself, reads the other reports, rechecks font
license facts, and decides. It never captures, drives the page, or edits anything.

## Inputs

Paths are relative to `--root` (default `.`). Every check runs from the project root, because the
reports record the paths they read as given and the gate resolves them against `--root`.

| Input | Path | Written by |
|---|---|---|
| plan | `.lapis/plans/<task>.yaml` | lapis |
| render extract | `.lapis/renders/<task>.json` | `lapis-design render check <url> --task <task>` |
| behavior session | `.lapis/behavior/<task>.json` | `lapis-design behavior check <url> --task <task> --stub ...` |
| lint report | `.lapis/lint/<task>.json` | `lapis-design slop lint ... -o .lapis/lint/<task>.json` |
| critic report | `.lapis/critic/<task>.json` | the critic |
| fonts lock | `.lapis/fonts.lock.json` | `lazuli lock` |
| asset ledger | `.lapis/assets.ledger.json` | lapis and the user |

- The gate runs the plan checks on the plan itself, exactly as `lapis-design plan check` does with
  its default rules, lock, and lazuli database, so there is no plan report to read. A plan that
  parses to a mapping but fails the schema, including one with a key that is not a string (YAML
  reads `yes:` as a boolean), gets the same `schema.invalid` findings in a report with exit 1; the
  gate's other checks run only on a plan that passes the schema. A plan that expands to more than
  10,000 keys and values or more than 1,000,000 characters and bytes outside its top-level `x-` keys,
  counting each use of an alias, or that holds there anything other than mappings, lists, strings,
  booleans, null, finite numbers, and integers of at most 4,300 digits (YAML can also produce bytes,
  dates, times, sets, and pairs), gets one `schema.invalid` finding and no further schema check.
  A plan larger than 1,000,000 bytes, or nested more than 100 levels deep, gets that one finding
  before it is parsed; `plan check`, lint, the exit-plan hook, and MCP apply the same limits. The plan is
  parsed with PyYAML's pure-Python safe loader whether or not libyaml is installed, so every install and every
  other tool built on `yaml.safe_load` reads it the same way: text that loader refuses is exit 2 and `plan-fix`
  with its line and column, among them a `?` inside a plain scalar of a `{ }` or `[ ]` collection (quote it).
- The lazuli database is `LAZULI_DB` when set, else the user cache. The checks read measured features
  from it read-only and never create or migrate it for that; the license refresh (below) opens it
  through the lazuli catalog layer, as `lazuli catalog lookup` does, which creates or upgrades it when
  needed and stores what it looked up. A database named by `LAZULI_DB` that cannot be opened, or that
  is older than this version of lapis-design, is exit 2, as it is for `plan check` and lint; the error
  names the command that upgrades it. A user-cache database that exists but cannot be read, is not a
  regular file, or is older counts as absent, with one warning on standard error; a missing one counts
  as absent without a warning. Either way the checks that need measured features are skipped.
- Rights records are checked inside lint, which runs the asset-ledger detector. That is why lint
  must run with `--ledger`, `--lock`, and `--source`.
- `--static` is a flag that declares a surface without interaction. It is accepted only when the
  plan has no `flows`; then no session is needed and lint runs without `--session`. With flows,
  `--static` is refused with exit 2.

## Output

`.lapis/release/<task>.json`, in the findings format (`slop/finding.schema.yaml`), with
`tool: {name: release_gate, version: <lapis-design version>}` and
`target: {plan, extract, session, task}`. The command creates `.lapis/release/` when needed, writes
the report to a temporary file there, gives it the permissions a newly created file would get, and
moves it into place, so a symbolic link at the report path is replaced, never written through.

The report holds the gate's own `release.*` findings, every blocking finding from the plan checks
and the lint report, and from the critic report every blocking finding whose verdict is not
`earned` plus every `unearned` finding that resolves a skipped lint finding (below). Each finding is
copied once. A copied finding keeps every field; the path of the report it came from is appended to
its `evidence.refs`. `summary.blocking` counts every blocking finding in the output, in two parts.
`summary.no_evidence` counts the blocking `release.*` findings that report a check that did not run
or an input that is missing (`input-missing`, `input-stale`, `width-missing`, `theme-missing`,
`probe-incomplete`, `backend-insufficient`, `layer-missing`, `requirement-unverified`,
`critic-missing`, `license-unchecked`), and `summary.not_run` breaks that count down by cause.
`summary.defects` counts the other blocking findings: those copied from the plan checks, the lint
report, and the critic, plus `study-reference` and `license-changed`. `summary.to_confirm` counts the
findings that do not block, so `total = blocking + to_confirm`. The printed result gives both parts
and then names what did not run, so a reader can tell a check to run from a defect to repair:

```text
release_gate: <blocking> blocking = <defects> defects + <no_evidence> without evidence, <total> findings -> .lapis/release/<task>.json
  without evidence: <n> inputs missing, <n> lint layers not run, <n> requirements not verified, ...
```

Exit codes: 0 when `summary.blocking` is 0, 1 when it is not, 2 when the plan cannot be read (a
missing file, text that does not parse, or a document that is not a mapping), the plan's `task.id`
is not `--task`, the database `LAZULI_DB` names cannot be opened or is older than this lapis-design,
or an option is invalid. Options
are spelled in full; an abbreviation is an invalid option. An unexpected error is also exit 2, with
the error on standard error. Exit 2 writes no report. When `--task` is a valid task id (the plan
schema's pattern), exit 2 also removes an earlier `.lapis/release/<task>.json` under `--root` (`.`
when `--root` was not given), so a skill never reads an old result as current; an invalid id touches
no file. An error while refreshing a source never ends the run; it becomes
`release.license-unchecked`.

## Gate findings

Unless the table says otherwise, a `release.*` finding has class `requirement`, severity
`{create: gate, review: P0}`, is blocking, and has `evidence.type: not-verified` (`source` for
license facts). Its `layer` is where the evidence is missing: `render` for widths and themes,
`behavior` for probes and the backend, `plan` for the plan and references, `source` for fonts, and
`review` for the critic and for whole reports.

| rule_id | Fires when |
|---|---|
| `release.input-missing` | an input the task needs, other than the plan, is absent, cannot be parsed, or names another task |
| `release.input-stale` | a report is older than an input it depends on, by file modification time: the session older than the plan or the stub file; the lint report older than the plan, extract, session, lock, or ledger; the critic report older than the lint report or the extract |
| `release.width-missing` | the extract has no light capture at one of 320, 390, 768, 1440 |
| `release.theme-missing` | the extract records a dark theme (`meta.dark_theme: true`) and has no dark capture at one of 390, 768, 1440, or the plan lists `dark` in `tokens.color.themes` or as a color role's `theme` and the extract records no dark theme (`meta.dark_theme` false or absent) |
| `release.theme-unchecked` | the plan lists `high-contrast` in `tokens.color.themes` or as a color role's `theme`, which render check does not capture. Class `quality`, `{create: warn, review: P2}`, not blocking: the user checks it by hand |
| `release.probe-incomplete` | a probe the session schema names has no coverage entry, or its entry is `partial` or `skipped`. `not-applicable` counts as covered |
| `release.backend-insufficient` | the session ran against the local development backend instead of a stub, so failure modes and repeated commits were not exercised |
| `release.layer-missing` | the lint report's target lacks the plan, extract, ledger, lock, or source tree, or lacks the session for an interactive surface; or its `scope` is absent, leaves out a layer those inputs call for (`plan`, `source`, `render`, `behavior` when interactive), lists `rules` because `--rule` narrowed the run, names a `rules_file` other than the packaged rules, or lists `unread_links.source` because the source walk passed links over |
| `release.requirement-unverified` | a requirement or contract rule has a `skipped` finding in the lint report that the critic did not resolve (below) |
| `release.critic-missing` | there is no critic report, or its target names another extract |
| `release.study-reference` | the plan uses a reference in study mode |
| `release.approval-assumed` | the plan's `approval.state` is `assumed`: no person approved the plan, and its `reason` says why. Class `quality`, `{create: warn, review: P2}`, not blocking, layer `plan`: the user confirms the plan, which the gate never counts as approved |
| `release.procedure-order` | a plan in `mode: create` whose page code came before its brief, references, or plan, by one of two readings: the first-write record `.lapis/order/<task>.json`, which `lapis-design hook pre-write` writes when a page write goes through while `next` still asked for one of them, or, with no such record, every page source file (markup, style, and script files outside hidden and generated folders) last modified before the brief record or the references record. A plan revised after the page says nothing, so the plan's own time is not read. Lifted by a plan that cites `.lapis/answers/<task>.md` in `context.other` and lists the existing code as a candidate (`source: existing-code`) of a `direction` exploration. Layer `plan`, `evidence.type: source`; blocking, class `requirement`, only when `LAPIS_UNATTENDED=1`, and then a defect, not a missing input; otherwise class `quality`, `{create: warn, review: P2}`, not blocking |
| `release.license-changed` | a catalog font's current license kind differs from the lock |
| `release.license-unchecked` | a catalog font's license could not be refreshed: the source blocked the request, answered in a form the adapter cannot read, the family was not found, or `--offline` was given |
| `release.license-unconfirmed` | a font's license is declared by the user (`license.source_class: user-declared`), comes with a subscription sync, or is unknown, including a catalog font whose lock and refreshed catalog both say `unknown`. Class `quality`, `{create: warn, review: P2}`, not blocking: listed first so the user reconfirms it |

## Skipped findings and the critic

A `skipped` lint finding on a requirement or contract rule with `skip_cause: reviewer` is resolved
when the critic report has a finding with the same `rule_id` - and the same `location` when the
skipped finding has one - whose `context.verdict` is `earned` or `unearned`. An `earned` verdict
resolves it and never blocks. An `unearned` finding is copied into the report whether or not it
blocks, and its own `blocking` decides. When several critic findings match, any `unearned` verdict
wins over `earned`, whatever their order, and every matching `unearned` finding is copied. A verdict
of `unknown`, or no critic finding, leaves it unverified. A skipped finding whose `skip_cause` is
`input`, `layer`, or `probe`, or that has no `skip_cause`, is never resolved by the critic; that
check has to run. The gate reads the cause from this field, never from the wording of `observed`.

## Font license facts

For each lock family this task uses (`used_by`) whose `source` is `google-fonts`, `fontsource`,
`fontshare`, or `sandoll`, the gate refreshes that source's record through the lazuli catalog layer,
with its usual robots.txt, pacing, and sign-in rules, and maps the catalog's license id to a lock
`license.kind`:

| Catalog license id | Lock kind |
|---|---|
| `OFL-1.1` | `ofl` |
| `Apache-2.0` | `apache` |
| `KOGL-1` | `kogl-1` |
| `system` | `system` |
| `commercial` | `commercial-subscription` or `commercial-perpetual` (either matches) |
| anything else | `unknown` |

A different kind is `release.license-changed`. Per-use grants are not compared, because catalogs
carry none. Families whose source is `adobe-sync`, `user-installed`, `foundry-purchase`,
`open-source-other`, or `noonnu` get `release.license-unconfirmed`. `sandoll` families are refreshed
and, because their grants depend on the user's subscription, also get `release.license-unconfirmed`.
Families whose `source` is `system` are left to the plan checks whatever their
`license.source_class`, since the plan checks already block a system face with no delivery path for
the platform. The gate never stores license keys, receipts, or account details.

## Failure records and `lapis-design next`

`render check`, `behavior check`, and `release check` write a record themselves when a full run cannot
start because of its environment: `.lapis/attempts/<task>/<step>.json` (`step` is `render`, `behavior`,
or `release`), holding `version`, `task`, `step`, `failure_kind: environment`, `reason` (the one line the
check printed), `command` (its argv), `exit`, and `at` (UTC). The environment is a browser that is not
installed or cannot start, or a path the sandbox denies. A run narrowed by a flag, or one that writes
somewhere other than the task's own path, leaves no record, and a full run that writes its report removes
an older record. Nothing else is recorded: a missing or invalid input, a stub or plan that does not
validate, a timeout, a finding, and a plan blocker are never the environment. A harness that cannot start
a separate context for the critic, or a harness with no network for the references, records that with
`lapis-design next --task <task> --unavailable critic|references --reason <why>`, which writes the same record for
that step.

`lapis-design next --task <task>` runs this gate offline on the files and returns the one step still to
take, with its exact command or schema: `brief`, `references`, `plan`, `plan-fix`, `plan-flows`, `plan-explorations`,
`plan-order`, `fonts-lock`, `stub`, `ledger`, `render`, `behavior`, `lint`, `critic`, `release`, or `done`. The gate's
own findings that report a check that did not run or an input that is missing (the ten under
`summary.not_run`, except `probe-incomplete`, `backend-insufficient`, `requirement-unverified`, and
`license-unchecked`, which are results of a check that ran) say which step comes back; the plan checks'
findings pick the plan steps. A record newer than what its step reads (the plan, and the stub for
`behavior`) stands in for that step, and the lint gaps it leaves are expected. `done` means the procedure is
complete, not that the gate passes: a blocking report ends it too, and the verdict is what the agent reports.

`brief` comes first: a run with no plan file, or a plan in `mode: create`, whose `.lapis/answers/<task>.md` is not
a brief record gets it, and a redesign or repair plan never does. The file is a brief record when it has a
`## Found` and an `## Answers` section with text and every answer that starts with `[assumed]` gives a `Basis:`
(`[declared]`, `[known]`, and `[open]` are the other tags); nothing else about it is judged. The record is not a
report of this gate, and the plan cites it from `context.other`.

`references` comes next, the same way: a run with no plan file, or a plan in `mode: create`, whose
`.lapis/references/<task>.md` is not a references record gets it after the brief, and a redesign or repair plan never
does. The record is Markdown with one fenced `yaml` block holding `captures: study-only` and a `references` list. Each
entry gives `url` (or `source`), `maker`, `kind` (`web-ui`, `print`, `signage`, `physical-object`, `archive`, or
`media`), `decision`, `relation`, `id`, and a `capture`: an existing file under `.lapis/references/<task>/`, a different
file for each reference; a `web-ui` entry also gives `source_facts` that state a value read from its HTML or CSS. A
capture that is an image (PNG, JPEG, GIF, or WebP by its first bytes, at least 1 KB) is a reference seen; a capture that
is anything else, or a page on an encyclopedia host, is text-only. The record needs at least six references, at most
two text-only, and, among those seen as images, at least three kinds and two outside `web-ui`: a text-only reference
counts toward the six and toward nothing else. The check reads the record and the files, not whether the looking was
good, and a brief's no-network or no-external-assets line never excuses it. A run that cannot reach the network
records that with `lapis-design next --task <task> --unavailable references --reason <why>`; the command sends one
plain GET first and refuses the record when it works. The record is the same as for the critic: `next` goes on to the
plan, and when the procedure is `done` its reason says no references were looked at. The captures are for study only,
git-ignored, and never shipped or copied into the page.

`plan-order` comes after the plan's own blockers and before the fonts lock: a blocking `release.procedure-order` (an
unattended run whose page code came before the brief, references, or plan) sends the run back to redo the direction
from the brief, citing the brief record and comparing the existing code as one candidate of a `direction`
exploration; the code stays only if it wins. A person's session is only told. Where a harness can ask before a
file is written (Claude Code and Codex `PreToolUse`, the `tool_call` event of Oh-My-Pi and pi), `lapis-design hook
pre-write` refuses an unattended create run's write of a page source file while `next` names `brief`, `references`,
`plan`, `plan-fix`, or `plan-explorations`: `permissionDecision: deny` with the step named, at most three times in a
row for one step, after which the write goes through and a write that came before the brief, references, or plan is
recorded in `.lapis/order/<task>.json`. Writes under `.lapis/`, to files that are not page source, and outside the
project are never refused. With no plan file the run counts as create only while the folder holds no page source. A
session without `LAPIS_UNATTENDED=1` gets one `systemMessage` the first time and is never refused. The hook sees the
harness's file-edit tools, so a page written through the shell is found afterwards, by file times.

While questions the run wrote for its user are unanswered, `next` returns the state `waiting-for-user` instead
of a step: `step.id` is `waiting-for-user` (stop, and wait for the answers), `then` is the step that comes
after them, and `waiting` names the files and the `phase`, `plan` while there is no plan file and `approval`
once there is one. The questions are in `.lapis/questions/<task>.md` and count when the file has two words or
more outside its heading lines (an empty or one-word file is no question); the answers are in
`.lapis/answers/<task>.md`, the brief record, where the plan can cite them from `context.other` and `claims.declared`. The
questions are unanswered when no answers file with a word in it is at least as new, by modification time, as the
questions file. A procedure that is `done` stays `done`. The exit gate (`lapis-design hook stop` with
`LAPIS_UNATTENDED=1`) lets a waiting run stop without counting a continue, and counts each set of questions it let
pass in `.lapis/gate/<task>.json` under `waits` (`plan`, `approval`, and `last`, the set's id): at most two sets
while there is no plan file and one after it. A set is one text written once, so writing the same words again is a
new set. Past the cap `next` and the gate name the step the files call for, as without questions. Without
`--task`, `next` takes the task of the newest plan, counted questions file, counted answers file, or counted references
record.

## What the gate does not do

It does not rerun captures, probes, or lint, judge design quality, or state a legal conclusion.
Rights findings compare records; the user decides what a license allows.

## Contract fields this gate reads

- `slop/finding.schema.yaml`: `target.source` and `target.lock` (what lint read), the report's
  `scope` (what lint ran), and each finding's `skip_cause`, all written by `slop lint`.
- `render/extract.schema.yaml` `meta.dark_theme`, written by `render check` from its dark-theme
  detection.
- `behavior/session.schema.yaml` `meta.stub`, written by `behavior check --stub`.
- `rule_id` comment: `release.*` ids come from this file.
