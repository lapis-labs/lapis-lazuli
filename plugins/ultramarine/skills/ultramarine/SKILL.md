---
name: ultramarine
description: Checks interfaces that exist - render capture at every width, behavior probes against a stub, slop lint over plan, source, render, and behavior, and a separate critic - then turns findings into fixes for the maker. Use to review a page or app, check work in progress, answer "does this look generic", or loop until nothing blocks.
license: MIT AND CC-BY-4.0
metadata:
  plugin: ultramarine
  version: 0.2.0
---

# ultramarine

ultramarine checks designs; it does not make them. It runs the `lapis-design` checks on our own
render, reads the findings in order of authority, has a separate critic judge what measurement
cannot, and hands each fix back to the maker. It reports what its checks found; it does not certify
accessibility or legal conformance. The full pre-ship gate is `ulm-release`.

## Order of authority

1. Requirements: accessibility, working behavior, honest behavior, rights, reduced motion. Never
   traded, never waived.
2. The project's contract: `DESIGN.md` and its tokens. A finding against it is fixed in the code,
   or the plan records a `proposed_design_changes` entry that the user approves.
3. Platform and framework conventions.
4. Named defaults (the cards). A default the plan keeps with a basis and reason is waived unless
   the render contradicts the reason.

## What the checks may touch

- `render check` captures hosts that are ours without a flag: loopback, private addresses, and a
  `.test` name that resolves only to them. A public host of ours needs `--public`. A host in the
  source registry or in the plan's `references` is never captured; pages that are not ours go
  through `lazuli ref capture`.
- `behavior check` drives only our render, against a stub (`.lapis/stub.yaml`, or one served by
  `lapis-design stub serve` and given with `--stub-url`) or an isolated local backend with
  synthetic values (`--backend local-dev --outbound none --values <file>`). Never real accounts,
  credentials, or payment methods.
- When something can only be checked by crossing these limits, report it as not checked.

## Modes

- **create** - work in progress, after the plan gate. Findings use their create severity (`gate`
  blocks, `warn` informs).
- **review** - an existing surface, with or without a plan. Run lint with `--mode review`;
  findings use review severity, and P0-P1 block. When you have only a screenshot, source files, a
  live site, a page that is not ours, a native screen, or a user's report, read
  `references/inspection-and-evidence.md` first: it says what each can support and what to list as
  not checked.

## Files

| What | Path |
|---|---|
| plan | `.lapis/plans/<task>.yaml` |
| render extract and screenshots | `.lapis/renders/<task>.json`, `.lapis/renders/<task>.shots/` |
| behavior session | `.lapis/behavior/<task>.json` |
| lint report | `.lapis/lint/<task>.json` |
| critic report | `.lapis/critic/<task>.json` |
| fonts lock, asset ledger | `.lapis/fonts.lock.json`, `.lapis/assets.ledger.json` |
| reference profiles | `.lapis/refs/<slug>.json` |

Every report follows `shared/slop/finding.schema.yaml`.

A narrowed run (below) writes `<task>.narrow.json` beside its full report, and its screenshots to
`<task>.narrow.shots/`. The release gate reads only the paths above, so a narrowed run never stands
for a full one and never overwrites it.

## Run the checks

1. **Render.** `lapis-design render check <url> --task <task>` captures 320, 390, 768, and 1440
   px in light, and the wider widths in dark when the page has a dark theme. While iterating on one
   layout, add `--width <px>`: the run writes `.lapis/renders/<task>.narrow.json`, and the release gate
   still needs the full one. For a page of plain files, `<url>` may be the HTML file's path; render
   and behavior check serve its folder on 127.0.0.1 for the run.
2. **Behavior**, for anything interactive. `lapis-design behavior check <url> --task <task> --plan
   .lapis/plans/<task>.yaml --stub .lapis/stub.yaml`. Every probe runs by default; `--probe <name>`,
   `--context m|d`, `--box <id>` (a box id from the session's `nodes`), and `--limit <n>` narrow it
   while iterating, and the run writes `.lapis/behavior/<task>.narrow.json`. `--box` and `--limit`
   narrow `controls` and `pointer`, which exercise one box at a time (and `commits`, which works from
   the controls that ran): their coverage is `partial`, and the reason counts the boxes left out.
   Without a stub, write the minimal one that
   `shared/behavior/stub.schema.yaml` allows (version, clock, empty routes, collections, values,
   and `empty` and `partial` variants) and tell the maker to complete it.
3. **Lint.** `lapis-design slop lint --plan .lapis/plans/<task>.yaml --extract
   .lapis/renders/<task>.json --session .lapis/behavior/<task>.json --source . --ledger
   .lapis/assets.ledger.json --lock .lapis/fonts.lock.json -o .lapis/lint/<task>.json`. Leave out
   inputs that do not exist yet, add `--ref .lapis/refs/<slug>.json` for each reference the plan
   borrows from, and add `--mode review` for an existing surface. Lint narrowed by `--layer` or
   `--rule`, or run over a narrowed extract or session, takes `-o .lapis/lint/<task>.narrow.json`.
4. **Critic**, below.

If a sandbox or permission prevents a check from starting Chromium or reading lazuli's user cache,
ask the user for permission once; if refused or impossible, list the check as not run with the exact
error. When the bundled browser cannot start and the host has its own way to view the page, view it
there, record what you saw as `image` or `review` evidence, and keep render check on the list of
checks that did not run; this is never a render or behavior record. Never move `LAZULI_DB` into the
project to bypass the restriction, and if a project-local database is unavoidable, keep it outside
version control and tell the user.

## Read the findings

- Blocking findings first, then open findings by severity.
- `skipped` means the check could not judge, never that it passed. A skip for a missing input
  names the check to run; a skip that asks for a reviewer goes to the critic. Report the rest as
  not checked.
- `waived` means the plan keeps that default. It stays waived unless the critic finds the render
  contradicts the keep's reason.
- A finding's `rule_id` leads to its `why`, `better`, and `keep_when` in
  `shared/slop/rules.yaml`, and a default rule belongs to one card in `shared/slop/cards.yaml`,
  whose routes are the ways out.
- Several findings on one package are one decision, not several fixes.
- For numerical bounds, recognition vocabulary, and what a missed match cannot establish in motion,
  data regions, and forms, read `references/check-bounds.md`.

## Run the critic

The critic judges in a context that did not make the design, reading only the inputs listed in
`references/critic.md`.

- When the harness can start the `critic` agent (installed as `ulm-critic` where agents are
  global), start it with the task id and those paths.
- Otherwise run `references/critic.md` in a fresh context: a new subtask or session that has not
  seen the design conversation, given only those files.
- Never judge in the context that made the design. If no fresh context is possible, say that no
  independent review ran.
- A critic that cannot write files returns its report as JSON; save it to
  `.lapis/critic/<task>.json`.

## Hand fixes back

1. Group the fixes by the plan field they change. The maker changes the plan first (the `lapis`
   skill in repair mode), then the code.
2. Each fix spends a world material, the signature, or a plan decision. A different named default
   is not a fix.
3. A repair loop is three rounds at most per task unless the user set another number; a round is
   one diagnosis, one fix for one cause, and one rerun of the narrowest check that can observe that
   finding.
4. Before the first fix, write down the finding, the check and condition that will show it is gone,
   and what must stay unchanged; if no check you can run observes it, make one fix, list it as not
   verified, and do not loop.
5. After a fix, rerun only that width, probe, box, or lint layer, into the `.narrow.json` reports. A
   narrowed run leaves the other widths and probes without evidence, so run the full set once, in
   order, when the last round ends; it writes the full reports.
6. A finding that is still open after two fixes goes to the user with both attempts and the cause
   you now suspect; do not try a third variation of the same change.
7. Stop when the target finding is gone and nothing that was passing now blocks, when the rounds
   are spent, or when a check cannot run; unused rounds are not a reason to keep polishing.
8. End by sorting the report into defects that remain, checks that did not run with the reason for
   each, and items the user must decide; a check that did not run is never reported as passed, and
   missing evidence is not a defect to repair.

Before repeating a repair, read `references/repair-loop.md` for the finding record, observing check,
critic bound, candidate disposition, and final full run.

## Reporting

Tell the user, in this order: blocking findings with their fixes; the most consequential unearned
choices from the critic; what was not checked (widths, themes, probes, layers, skipped rules) and
why; and the next step, another loop or the release gate (`ulm-release`). Leave rule text and
raw output in the report files.
