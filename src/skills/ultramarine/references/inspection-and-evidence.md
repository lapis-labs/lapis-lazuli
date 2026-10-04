# Inspection and evidence

## Sections

Read the section for what you have in hand, by heading; the rest are other cases.

- Inspect, do not change: what an inspection request allows
- What each kind of evidence supports: the claim a screenshot, source, live site, or report can carry
- Route by what you have: the steps to run for a build, a screenshot, source only, or a page that is not ours
- Manual accessibility scope: choosing a sample and what a manual pass covers
- Heuristic inspection: inspecting a consequential task and its failure path
- Write down each finding: the smallest record someone else could repeat
- When the critic did not run: how to report a judgment made without the critic
- Conflicts, failures, and when to stop: what to do when surfaces disagree or a check fails
- What not to say: claims the evidence does not support
- Rules to read: source rules that find things themselves

This file backs a review of something that already exists: a build of ours, a screenshot, a page
that is not ours, a native screen, or a problem the user describes. It says what you may touch, what
each kind of evidence supports, which route fits what you have, and how to report what was not
checked. The critic's steps are in `critic.md`.

## Inspect, do not change

A request to inspect, review, or audit allows looking and recommending. It does not allow editing
source or tokens, rewriting the plan, acting on an account, or deploying, even when you could and
even when you have just seen a defect. Write reports under `.lapis/` and change nothing else. When
the user also asks for fixes, finish the inspection first, then hand the maker the findings, the
evidence behind each, and what is unknown.

## What each kind of evidence supports

`evidence.type` in `../shared/slop/finding.schema.yaml` says how a finding was established.

| Type | Supports | Does not support |
|---|---|---|
| `plan` | what the plan or `DESIGN.md` decided | that the build follows it |
| `source` | what the code declares | what renders or activates |
| `image` | one frame you or the critic saw: emphasis, grouping, crop, copy | state, semantics, focus, timing, other widths, exact contrast, absence |
| `runtime` | what probes did in our render, against a stub or local backend | other devices, assistive technology, the real backend |
| `measurement` | a render extract's named quantity at its widths and themes | uncaptured states; whether it is good |
| `review` | the critic's judgment of whether a choice is earned here | proof |
| `not-verified` | that it was not judged: a skipped check, or your admission | pass or fail |

The user's report is not a type. Write "reported by the user: ..." and treat it as ground truth
about what they saw. It becomes `runtime` only when you reproduce it. Do not rerun anything to
decide whether to believe it, and a passing check on another device does not refute it: keep both.
A reported clip, a fixed height in the source, and no runtime check are three entries, never
"reproduced".

## Route by what you have

With a host that is ours, a plan, and a stub, run the sequence in `SKILL.md`. For less:

- **Project files, no browser.** `lapis-design slop lint --source . --mode review -o
  .lapis/lint/<task>.json`, plus `--plan` when there is one. Without a plan only the source layer
  runs (the review layer needs a plan or an extract), so read `scope.layers` before calling
  anything clean. A rule that reads the code itself reports what it matches as an open `source`
  finding. A match for a pattern rule such as `code.focus-outline-removed` comes back `skipped` with
  `skip_cause: layer`: a lead for a render or behavior check, not a finding. `skip_cause: input`
  means the rule lacked what it needs, as `system.font-outside-contract` does without a plan or
  fonts lock. The layer reads web source as text and judges no `var()` or `calc()` value. Say that
  nothing rendered and the critic did not run.
- **Only a screenshot or recording.** `render check`, `behavior check`, and `slop lint` take no
  image, so none can check it. Safe to say: what is visible and where; emphasis, grouping, crop;
  whether copy is legible at the supplied scale; apparent clipping, called apparent. Not safe:
  exact contrast (a sampled pair, before compositing); keyboard, focus, hover, timing, or
  announcements; that a state or error path is missing (a frame is one instant); why it looks
  wrong. An export from a design file shows no layers or prototype behavior. State scale and crop
  where they matter, never infer a viewport from bitmap size, and name what would settle it: the
  uncropped export with its frame size, the component's source, or a capture at a named width.
  Write what you saw as `image`, and list `color.text-contrast` and `component.small-target`, which
  run only on an extract, as not run.
- **A page that is not ours.** `render check` captures hosts that are ours; `--public` is for a
  public host of ours and never reaches a source-registry or `references` host. Behavior check
  drives no other page. Read it with `lazuli read`, or record measured relations (type scale,
  section order, density, palette shares) with `lazuli ref capture --rights
  <own|licensed|reference-only>`, the rights from the user; that says nothing on whether the page
  works. A reference-only profile keeps no screenshot, copy, alt text, or accessible names, and lint
  takes a profile only as `--ref`. What you did not see is not observed, never absent.
- **The user's live site.** `lapis-design render check <url> --public` captures it. Behavior check
  does not run there; it drives only hosts that are ours, against a stub or an isolated backend with
  synthetic data. Say so, and serve the same build locally with a stub if the question needs it.
- **A native app.** `render check` and `behavior check` capture web pages, and the critic stops
  without an extract. A source tree without CSS, markup, or scripts, a Swift tree for one, gives
  `slop lint --source` nothing to read: every rule comes back `skipped` and the exit code is 0,
  which is not a pass. List the checks as not run. Your evidence is the source you read and any
  recording the user supplies (`image`). Say which a claim rests on: a real device, a simulator, a
  recording, source only, or nothing. A simulator does not prove haptics, camera or thermal
  behavior, pointer precision, or all of a screen reader's output. Keep the user's report as given
  and describe the device exercise that would settle it.

## Manual accessibility scope

Choose a sample by distinct templates, shared controls, task consequence, and interaction risk.
Include critical commitments/recovery, complex inputs, charts or drag behavior, relevant themes
and locales, and content extremes. Exercise states that can occur, not a fixed screen catalog.
Record the task and component each route represents. Unvisited pages remain outside the claim;
automated results and a sample count establish neither conformance nor custom-interaction usability.

Name the actual browser/platform and assistive-technology pairing. Orient through title, language,
regions, headings, and current location; then complete a critical task and recovery. Check names,
roles, values, states, associated errors, updates without stolen focus, unavailable hidden layers,
and meaningful focus return on closing. Walk the same task with the pointer set aside. Record the
exact input sequence and heard or observed result. A source role or browser tree is not speech evidence.

Apply the type reference's resize, reflow, and text-spacing conditions to that task. Inspect fixed
regions, overlays, and media clips: sticky controls can consume the viewport, and clipping ancestors
can remove descendant focus indicators without page overflow. Confine exceptional two-dimensional
content to a navigable region. Include the on-screen keyboard on temporary input surfaces when in
scope. Record width, text setting, orientation, route, and state. Preserve authored relations that
survive; change the failed constraint, not the whole visual grammar by default.

## Heuristic inspection

Inspect a consequential task and failure/return path, not random screens. Separate an orientation
pass from an inspection pass; when several reviewers participate, retain independent observations
before merging. Merge by behavior, consequence, and remedy, not by heuristic name; one issue need
not appear under ten labels. “Minimalist” means removing task-irrelevant competition, not making
every professional workspace sparse. Prioritize with the existing severity contract; do not mix
positive craft ratings with oppositely directed problem scales or average them into usability.
Expert inspection predicts plausible problems, not prevalence, audience preference, or success
rates. Re-exercise the affected task after a remedy; cleaner default appearance is not resolution.

## Write down each finding

Put the smallest record someone else could repeat beside the finding, in the report. A bare
"verified" is not one.

```text
State: <route or component, width, theme, locale, and the data or account state when they matter>
Action: <what you did or inspected>
Observed: <what happened or what was there>
Evidence: <a type from the table, or reported by the user, each with its reference>
Limit: <the state, device, tool, or claim you did not exercise>
```

Locate the finding at a region or state and name the property and its effect ("the three piece
prices match in size and weight, so the open piece has no priority", not "feels generic"); the
cause stays a hypothesis until evidence supports it. Keep credentials and personal data out; use a
fixture.

A hypothetical example, not an observed result:

```text
State: pottery page, reserve panel, 390 px, Korean, text enlarged to 200% as the user described
Action: read the stylesheet; no browser was available
Observed: `.reserve-button { height: 44px; overflow: hidden }` at styles.css:212
Evidence: reported by the user: the label 예약하기 is cut off; source: styles.css:212
Limit: runtime not verified, so a fixed height is a risk to test, not proof of this clip
```

## When the critic did not run

When you judge a design you did not make and the critic cannot run, write what you saw in
screenshots as `image` and what you concluded from the plan or extract as `review`, and say that no
independent review ran: `.lapis/critic/<task>.json` exists, or it does not. A second look in a fresh
context is a new inspection, not stronger proof, and a reviewer's silence is not a pass.

## Conflicts, failures, and when to stop

When surfaces disagree, compare revision, state, width, and content, then prefer the surface that
observed that claim; keep a conflict you cannot resolve, with the smallest check that would settle
it. A refused host, a browser that will not start, or a missing stub is a result: record it, finish
the source and supplied-file inspection, mark the blocked part not checked, and do not repeat the
same command unchanged. Stop when the judgment holds within its evidence or when more looking would
only repeat it.

## What not to say

- That `skipped` is a pass, that a run is clean beyond `scope.layers`, or that a source match is a
  finding when its rule names a later layer that did not run.
- That any route certifies accessibility. Each reports what ran, at the widths, themes, and states
  it ran.
- That a reference-only profile holds a screenshot or copy, or that a report was reproduced because
  the code looks consistent with it.
- That one number stands in for the decision: a contrast ratio covers one pair, and a finding count
  is not a quality grade.

## Rules to read

Source rules that find things themselves, so a finding states what the code declares:
`system.literal-color`, `system.off-scale-value`, `system.font-outside-contract`,
`system.bypassed-primitive` (its `verify` is `review`, so the critic gives the verdict),
`component.unlabeled-input`, `code.image-dimensions`, `code.clickable-non-interactive`, and
`imagery.missing-content-image`. Source rules that only lead: `code.focus-outline-removed`,
`code.mobile-100vh`, `component.emoji-icons`, and `motion.transition-all`. Rules that run only on a
render extract: `color.text-contrast` and `component.small-target`. A judgment no rule covers is the
critic's own finding under a `review.*` id, listed in `critic.md`. Rule text is in
`../shared/slop/rules.yaml`.
