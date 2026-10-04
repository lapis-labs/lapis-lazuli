---
name: ulm-maintain
description: Maintains an existing frontend - behavior-preserving refactors and cleanup, dead code, dependency and framework upgrades, performance, and design debt against DESIGN.md - from a captured baseline in small checked steps. Use for refactors, upgrades, "it got slow", token drift, duplicated components, and LapisLazuli findings that look wrong.
license: MIT AND CC-BY-4.0
---

# ulm-maintain

ulm-maintain changes an existing frontend without changing what it promises, in small steps
checked against a baseline. It decides no design; a redesign goes to the `lapis` skill.

## Order of authority

1. Requirements: accessibility, working and honest behavior, rights, reduced motion. Never traded.
2. The project's contract: `DESIGN.md` and its tokens. Drift is fixed in the code; a stale contract
   gets a proposed change.
3. Platform and framework conventions.
4. Named defaults (the cards in `shared/slop/cards.yaml`).

## Scope the change

- Name its kind: **behavior-preserving** (refactor, cleanup, upgrade, speedup) or **intended** (a
  fix, a removal), one kind per change. An intended change names what differs and how to tell it
  worked.
- Name the boundary (the files, the surfaces using them, what stays out); problems outside it are
  reported, not fixed.
- Protect what users and other code rely on: states, focus, copy, URLs and history, form payloads,
  analytics events, storage keys, public exports. Matching screenshots do not prove these.

For shared component/token migrations and consumer release evidence, read `references/system-governance.md`.

## Capture a baseline

Serve the current build on a host that is ours (loopback, a private address, or a `.test` name
resolving only to them), then:

1. `lapis-design render check <url> --task <task>-before`, plus `--plan .lapis/plans/<task>.yaml`
   when a plan exists. It writes `.lapis/renders/<task>-before.json` and screenshots in
   `.lapis/renders/<task>-before.shots/`.
2. If interactive, `lapis-design behavior check <url> --task <task>-before --stub .lapis/stub.yaml
   --build <commit>`, plus `--plan .lapis/plans/<task>.yaml` when a plan exists (the flows probe
   reads its flows), with a `--probe` per area the change touches, which makes it write
   `.lapis/behavior/<task>-before.narrow.json` instead of `<task>-before.json`; or `--backend
   local-dev --outbound none --values <file>` with synthetic values. Never real accounts or payment
   methods. Without either, behavior is not checked.
3. `lapis-design slop lint --source . --extract .lapis/renders/<task>-before.json --mode review
   -o .lapis/lint/<task>-before.json`, plus `--session` with the file step 2 wrote and `--plan` when
   a plan exists. Without the extract and session, source matches stay unconfirmed leads.
4. The project's own build, type checks, and tests; note what already fails.

## Work in small steps

- One thing per step, undone by reversing only your own edits. Never discard work you did not make.
- After each step, run the build, tests, and the narrowest check that sees it: `render check` with
  `--width <px>`, `behavior check` with `--probe <name>` (and `--box <id>` for one control), or lint
  with `--rule <id>`.
- Finally, rerun the baseline set under `--task <task>` with the same widths, probes, data, and
  stub. Narrowed runs write `<task>.narrow.json`; the release gate reads only the full reports
  `ulm-release` makes.

## Compare two captures

There is no diff command. Read both extracts viewport by viewport, pairing `width` and `theme`
(fields in `shared/render/extract.schema.yaml`, values defined in `shared/render/DERIVED.md`):
`metrics.cls` and `metrics.shift_sources` for stability, `scroll_width` for overflow,
`derived.type_fingerprint`, `derived.gaps`, and `palette` for type, spacing, and color, and
`font.fallback` on text runs. Box ids follow DOM paths, so a moved element reads as removed and
added. Then view the paired screenshots. Compare lint reports by `rule_id` and `location`: a new
finding is a regression; a missing one is fixed only if no `skipped` finding took its place. In a
behavior-preserving change, explain every difference or undo the step.

## Upgrades

- Read the lockfile for installed versions, and the changelogs the user points to with
  `lazuli read <url>`. A source marked `refused` or `browser-link`, or a blocked page, goes to the
  user as a link.
- Never cross a major version without saying so and getting the user's yes; never add or swap a
  dependency without approval.
- A clean build proves compilation, not behavior. `code.animation-package-mismatch` catches
  animation imports that no longer match the installed package.
- Say when data the new version writes cannot be read after a rollback.

## Performance

Name the symptom: surface, action, metric, and condition (device class, network, data size, cold or
warm). Measure with the project's own tools or give the user steps; change one thing; measure again
under the same conditions. Lab numbers, `metrics.cls` included, are never field data.

Some causes have rules: `code.image-dimensions` (unsized images shift content),
`code.unvirtualized-list` (virtualize only for measured volume, keeping focus and find-in-page),
and `type.font-fallback` (text left in a fallback face; late swaps show in `shift_sources`). Font
files enter the project as open-licensed files bundled with their license text and locked
(`lzl-fonts`), or as files the user supplies for shipping; a subset keeping a reserved
name trips `rights.reserved-font-name`. A speedup that drops content, labels, states, or reduced
motion is a regression.

## Design debt

Lint with `--rule 'system.*' --rule 'code.*'`. `system.literal-color` finds color literals outside
the token files; `system.off-scale-value`, radius, size, and spacing off the plan's or project's
token scale; `system.font-outside-contract`, families outside the plan's type roles and fonts lock;
`system.bypassed-primitive`, raw elements where an adopted primitive exists. `code.*` finds
implementation defects that pile up, such as removed focus outlines (`code.focus-outline-removed`).
The font check needs a plan or fonts lock, and render-side comparisons the plan's tokens; the
`lapis` skill can write a short repair plan with them.

- Map literals to the token for their role, not one that merely shares their value.
- Group by root cause; fix the shared owner once, not each copy.
- When the code is right and the contract stale, draft a `proposed_design_changes` entry (`path`,
  `from`, `to`, `reason`) for the maker; the contract changes only after the user approves.

## Dead code and ownership

- Find a module's owner first: an owners file, the manifest, the repository history, or the user.
- Delete only what nothing references: search symbols and strings (routes, class names, storage
  keys, event names), then build and test. Lint skips tests and stories; search those too.
- An old path kept for other consumers needs an owner and a removal condition.

## Keep findings useful

- A report older than its code is not evidence; rerun it. `skipped` means not judged.
- Kept defaults go in the plan's `defaults`, by the maker. Never edit a report, mark a finding
  waived, or drop an input to silence one.
- When a finding looks wrong, write it up for the LapisLazuli maintainers: `rule_id`, `observed`,
  `location` (fields in `shared/slop/finding.schema.yaml`), the input it read, the context, and why
  it is wrong. Never edit
  `shared/slop/rules.yaml` or other installed shared files, or lint with a modified rules copy.

## Reporting

Tell the user the change's kind and boundary, results before and after, each difference and whether
it was intended, what was not checked, and what awaits approval or the maintainers' review.
