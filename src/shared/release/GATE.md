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
  before it is parsed; `plan check`, lint, the exit-plan hook, and MCP apply the same limits.
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
