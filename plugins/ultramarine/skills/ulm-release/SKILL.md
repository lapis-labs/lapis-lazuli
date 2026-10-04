---
name: ulm-release
description: Runs the release gate for LapisLazuli work - every width, theme, and probe, all lint layers with rights records, font license facts rechecked, the critic's report - and writes the gate report that says whether the output may ship. Use before shipping, handing off, publishing, or merging a page or app.
license: MIT AND CC-BY-4.0
metadata:
  plugin: ultramarine
  version: 0.2.0
---

# ulm-release

The release gate decides whether a task's output may ship. It runs the full set of checks that
iterations skip, and it blocks on every requirement that has no execution evidence. It never
fixes the design; blocking findings go back to the maker.

The gate's rules are in `shared/release/GATE.md`. `lapis-design release check` applies them and
writes `.lapis/release/<task>.json`.

## Before the gate

- The plan `.lapis/plans/<task>.yaml` exists and was approved. The design being shipped is the one
  the plan describes; if implementation changed it, the plan changed first.
- The build to ship is served on a host that is ours: loopback, a private address, or a `.test`
  name that resolves only to them. Never a production site with real users or data.
- Interactive surfaces have a stub: `.lapis/stub.yaml`, or the same stub served with
  `lapis-design stub serve` for server-rendered apps. A local development backend is for
  iterations; the gate reports that it does not exercise failures and repeated commits.

## Run the full set

Run these in order from the project root, on the build that will ship, into fresh reports.
Nothing here uses `--width`, `--probe`, `--context`, `--box`, `--limit`, `--layer`, or `--rule`; the
gate needs everything, and it never reads the `<task>.narrow.json` files that narrowed runs write.

1. **Render.** `lapis-design render check <url> --task <task>` - every width, and dark where the
   page has a dark theme.
2. **Behavior.** `lapis-design behavior check <url> --task <task> --plan .lapis/plans/<task>.yaml
   --stub .lapis/stub.yaml` (or `--stub-url <url>`) - every probe. A surface whose plan has no
   `flows` and that has no interaction skips this step.
3. **Lint.** `lapis-design slop lint --plan .lapis/plans/<task>.yaml --extract
   .lapis/renders/<task>.json --session .lapis/behavior/<task>.json --source . --ledger
   .lapis/assets.ledger.json --lock .lapis/fonts.lock.json -o .lapis/lint/<task>.json`, with
   `--ref .lapis/refs/<slug>.json` for each reference the plan borrows from, and `--mode review` for
   an existing surface. Leave out `--session` when step 2 was skipped. Lint also checks the asset
   ledger and fonts lock against the shipped files.
4. **Critic.** Run the critic on its listed inputs as the `ultramarine` skill describes, in a fresh
   context, writing `.lapis/critic/<task>.json`.
5. **Gate.** `lapis-design release check --task <task>`, adding `--static` when step 2 was
   skipped. It runs the plan checks itself and refreshes the license facts of locked catalog
   fonts over the network; without network it cannot pass.

If a sandbox or permission prevents a check from starting Chromium or reading lazuli's user cache,
ask the user for permission once; if refused or impossible, list the check as not run with the exact
error. The host's own browser tool may supply `image` or `review` evidence of what you saw, never a
render or behavior record; never move `LAZULI_DB` into the project to bypass the restriction, and if
a project-local database is unavoidable, keep it outside version control and tell the user.

The gate never compares the render with an earlier build. Once the full set has run, compare the
shipping render with a baseline - the `.lapis/renders/<task>-before.json` capture of the build that
last shipped or was approved, or one captured from the project's history - and report the
differences the plan does not explain right after the verdict; `references/visual-regression.md`
says how.

For product-specific manual acceptance and operational handoff beyond built-in checks, read `references/production-evidence.md`.

## What blocks

- Any blocking finding from the plan checks, lint, or the critic.
- A requirement or contract rule that lint skipped and the critic did not resolve: a check that
  could not run is not evidence.
- A missing width or dark capture (including a dark theme the plan lists that the render did not
  find), a probe that ran partly or not at all, a lint input left out, or a stale report.
- A study-mode reference in the plan.
- A locked catalog font whose license changed since it was locked, or whose license could not be
  rechecked.
- No critic report, or one for a different render.

Fonts whose licenses the user declared, and fonts synced to this computer by a subscription, are
listed for the user to reconfirm; the gate cannot confirm them itself. A synced desktop font never
ships in web files; its web delivery is the provider's own web project (`adobe-web-project` in the
lock). A `high-contrast` theme in the plan is not captured, so the user checks it by hand.

## When something blocks

- Report each blocker with the fix its finding names, grouped by plan field. The maker fixes the
  plan first, then the code, then reruns the whole set: the gate flags any report older than what
  it depends on.
- Never mark a requirement `waived`, delete a report, or edit a finding to pass the gate.

## Reporting

Start with the verdict: ships, or does not ship and why. Then the blockers with their fixes, the
differences from the baseline that the plan does not explain, the fonts and assets the user must
reconfirm, and what was not checked and why. Point to
`.lapis/release/<task>.json` for the full record.
