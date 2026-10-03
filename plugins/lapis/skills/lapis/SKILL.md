---
name: lapis
description: Plans new interfaces, redesigns, and visual direction before code - brief, world materials, type and color roles, layout, key copy, the candidates compared for each open decision, and keep-or-reject decisions on named defaults - in a plan file that lapis-design checks. Use for landing pages, app screens, dashboards, restyles, and "this looks generic".
license: MIT AND CC-BY-4.0
metadata:
  plugin: lapis
  version: 0.2.0
---


# lapis

## Done

- Done is when `lapis-design next --task <task>` says done. Run it before you report, do the one step it names, and
  repeat; a plan, a check, or a page that merely looks finished is not done.
- A missing or invalid input, a plan blocker, and a timeout are not done: that step comes back. Only a failure of the
  environment, such as a browser that cannot start, counts, and the tool records it itself.
- The release gate may say the work does not ship. Report that verdict; it is not a step to repeat, and never a reason
  to edit a report or waive a finding.
- With nobody to ask (`LAPIS_UNATTENDED=1`), record `approval: {state: assumed, reason: ...}` in the plan and go on;
  `approved` is only a person's.
- When a person will answer, a user or an operator who relays replies, write the questions the plan needs (grilling
  before it, or its approval) to `.lapis/questions/<task>.md` and stop with them as your last message: `next` says
  `waiting-for-user` and the exit gate lets that stop pass, twice before a plan and once after, never for a file of
  fewer than two words. Record the replies in `.lapis/answers/<task>.md`, cite them in the plan (`context.other`,
  `claims.declared`), and run `next` again.
- A brief's no-network line limits what the page loads; checks on 127.0.0.1 are not network use.

lapis turns a request into a design contract - the plan file `.lapis/plans/<task>.yaml` - and then
into an implementation that follows it. The plan is written before code, checked by
`lapis-design plan check`, approved by the user, and read by every later check.

## Order of authority

1. Requirements: accessibility, working behavior, honest behavior, rights, reduced motion. Never traded.
2. The project's contract: `DESIGN.md` and its tokens. A different value needs a
   `proposed_design_changes` entry that the user approves.
3. Platform and framework conventions.
4. Named defaults (the cards). A card is an editorial signal, judged keep or reject; it never
   outranks the three above.

## Modes

- **create** - a new surface. The plan needs `world_materials`, `sources`, `direction`, and `layout`.
- **redesign** - an existing surface. Capture it first
  (`lapis-design render check <url> --task <task>-before --plan .lapis/plans/<task>.yaml`; add
  `--public` when the URL is a live site of ours, since public hosts are refused without it), read
  `DESIGN.md`, and write in the plan
  what stays, what changes, and why.
- **repair** - start from findings (lint, critic, or the user's report). Change only what they name;
  the plan can stay short: brief, the changed part, and `defaults`.

A small edit inside an established system needs no plan. Say so and make the edit.

## At the start of a task

1. Read `PRODUCT.md` and `DESIGN.md`: the app root first in a monorepo, then the repository root;
   in each, the root, then `.agents/context/`, then `docs/`. Record what you read in `context`,
   including the `DESIGN.md` dialect. Report conflicting records instead of merging them.
2. Read `.lapis/plans/<task>.yaml` if it exists and continue it; a different task gets a new id.
3. If this session has no font inventory summary, run `lazuli local fonts --summary`.
4. Ask only questions whose answers change the plan, as the smallest independent set (a relayed run: see Done).
   Otherwise write a reversible assumption into `claims.proposed` and continue.

## Direction principles

Five principles steer the direction steps below. Each names the plan field that holds it and what,
if anything, checks it.

- `subject-first` - A decision that fits any other subject unchanged is a default: record it in
  `defaults` with a reason, or change it from a `world_materials` entry. The critic's counterfactual
  test judges it; `copy.name-swap` reads key copy for a material, term, number, or name of this subject.
- `relation-not-mood` - `direction.concept` states a relation that changes order, emphasis, or labels.
  A mood or a style word is not one. The critic judges it; `plan check` does not.
- `lever-has-address` - Each entry of `direction.levers` says what changes, from which material, and
  where it lands. `layout.unanchored-lever` reads whether the sentence shares a word with a material.
- `mode-sets-the-measure` - Persuade, operate, read, and experience measure different things, so one
  lever fits one mode and misleads in another. Set `direction.read.surface_mode` and
  `direction.dials` for each screen. The critic's vision check judges it; no rule reads it.
- `explore-then-choose` - An open decision is made between candidates: two or more, compared on the
  page's own content, before one wins. `explorations` holds them and `plan.uncompared-decision` reads
  whether it does. A brief's no-network, no-external-assets, or offline line limits what the page
  ships and loads, never what you explore: read the local inventory and the catalogs whatever the
  brief says.

## Explorations

`explorations` holds one entry per open decision: each group of type roles (`covers` lists them), the
palette, the layout structure, the motion level, the direction, and the headline, subhead, and cta
(`covers`). An entry has at least two `candidates` (`name`, `source`), `compared_on` (`specimen`: the
page's real copy set in each candidate; `render`; `sketch`), the `chosen` name, and `runner_up_lost`:
why the closest alternative lost. A face's `source` is `local`, `catalog:<name>`, `adobe`,
`commercial:<foundry>`, or `generic` (a generic family); for the other decisions it says what the
candidate came from: a world material, a reference, a sketch of your own, or `generic`, the stock
choice for this kind of page.

A decision the contract or the brief fixes is marked `fixed_by: contract` or `brief` with a `reason`
and needs no candidates. `contract` holds only when `context.design` is set, and the brief fixes
what the page ships, so "offline" or "no external assets" fixes no face. A create plan whose open
decision has no comparison, or whose type candidates are all generic families, is blocked.

## Write the plan

Work in this order; each step fills the named plan fields. The schema is
`shared/plan/schema.yaml`.

### 1. Brief and claims - `brief`, `claims`

`product_frame` is the surface's task, not the company's category. `one_job` is the single job this
screen must do. Keep `claims` apart: known (evidence), declared (the user said), proposed (you
suggest), unresolved (open).

### 2. World materials - `world_materials`

Concrete things from the subject: objects, records, processes, numbers, marks, places, tools.
Never adjectives or moods. Find them in `PRODUCT.md`, the user's content, real photographs, and the
subject's own documents. Four to six is a good start; create mode needs at least one. These are
what replace every default you reject, so collect them before choosing type, color, or layout.


### 3. Design Read and dials - `direction.read`, `direction.dials`

Write one line and put it in `direction.read.text`:

```text
Reading this as: <product frame> / <surface mode> on <platform> for <audience>,
<style frame> language, constrained by <constraints>; dials V/M/D = x/y/z.
```

Surface modes are per screen: persuade, operate, read, experience. The style frame is inherit,
named, undecided, or subject-derived. Dials are proposal controls, not quality scores: variance 1
conventional to 10 experimental, motion 1 static to 10 cinematic, density 1 airy to 10 cockpit.
Starting points, which the brief and existing designs override:

| Product frame | Starting mode | V/M/D |
|---|---|---|
| marketing-landing | persuade | 7/6/4 |
| saas-dashboard-admin | operate | 3/3/7 |
| consumer-mobile-app | operate | 5/5/5 |
| e-commerce | persuade + operate | 4/4/6 |
| content-editorial-docs | read | 5/2/4 |
| forms-onboarding-checkout | operate | 2/3/5 |
| developer-tools | operate | 4/4/7 |
| data-visualization | operate + read | 3/3/8 |
| fintech-regulated | operate | 2/2/6 |
| internal-tools | operate | 2/2/8 |
| portfolio-personal | experience | 8/7/3 |
| games-entertainment | experience | 8/8/5 |

"Premium" in a brief is not a style. Never turn it silently into low density, cream, and serif.

When the request names a look - modern, professional, minimal, clean, editorial, bento, or another
style word - set `style_frame: named`, write the word in `direction.read.style_name`, and keep it in
`claims.declared`. When a style file matches, read it before step 4:
`references/style-bento-and-modern-saas.md` when the word is bento, or modern or professional for a
software product's page or tool; `references/style-minimalism-and-editorial.md` when it is minimal,
clean, or editorial. When none matches, write in `direction.read.text` what the word assumes about
the content. A style file says what the style assumes about the content and which plan fields make it
this subject's; it is not a look to reproduce.

For mixed style influences and their ownership, read `references/form-levers.md`.

The motion dial has three bands: 1-3 feedback only, 4-6 transitions that explain a change, 7-10 authored
moments. Write the band into `tokens.motion.principles` with a reduced-motion branch for each effect
(`respect` is the only accepted value for `reduced_motion`). For timing and easing, interruption, scroll and route
enhancement, choosing between native and library animation, and delivering authored animation, read
`references/motion.md`. Compare the band you pick with the one next to it on one real interaction and
record the pick (`explorations`, decision `motion`).

### 4. Concept and signature - `direction.concept`, `direction.levers`, `layout.signature`

Before committing, write two directions that differ in relationship or structure - the page organized
around a different thing from the subject, not the same layout in another palette - and keep both in
`explorations` (decision `direction`), each named by its relation. The pick becomes
`direction.concept`; the other says why it lost.

Write the concept as a relation that changes order, emphasis, or labels, starting from a live tension
in the subject: a pottery shop's sales page becomes the record of one kiln firing. A mood or a style
word is not a concept. Write each lever as one sentence: the lever (scale, density, rhythm, tension,
material, type as form, or motif), what visibly changes, and the world material it comes from, named
as it is written in `world_materials`. A lever's bare name, or words such as clean, modern, and bold,
are not levers; `plan check` blocks a lever that names no world material. For how each lever works
and where it lands in the plan, read `references/form-levers.md`. The signature is the one element
only this task has, built from a world material; the page is organized around it, not around a hero
shell.


### 5. References - `references`

Only pages the user gave. Capture each with `lazuli ref capture <url> --rights <rights>` and record
rights, mode, what to take (relations: rhythm, ratios, sequence), and what to leave (brand colors,
illustrations, copy). Take relations, never surfaces.

### 6. Color - `tokens.color`

Answer the six decision axes with a status each: medium, task structure, content colors, identity,
environment, tone. Then assign roles - field, foreground, identity, interaction, status, data,
content - as OKLCH values or `DESIGN.md` references, choose relations, and list themes. Content
colors (product photos, data, glazes) come first; the interface serves them. For a physical color
standard, `lazuli color lookup <system> <code>` checks a code the user has and gives its reference
link, `lazuli search --type color <value>` lists the nearest computed codes, and values come only from
the user's records (`lazuli color record`) or `DESIGN.md`; a computed approximation of a coordinate
code can seed a value you author, labeled as yours. Never invent a standard's value. For what counts
as an answer on each axis, how many colors each role needs, building from world materials, OKLCH
ramps, themes, data scales, and physical standards, read `references/color.md`.

Build two palettes from different world materials and compare them on the page's real content before
choosing (`explorations`, decision `palette`).

### 7. Type - `tokens.type`

Decide roles - display, heading, body, ui, data, code, caption - per script, then explore faces before
choosing one. The brief's no-network, no-external-assets, or offline line limits what the page ships;
it never limits this exploration, which always runs:

1. Inventory: `lazuli local fonts --summary`; `--family <text>` for one family's faces, scripts, and
   measurements; `--origin adobe-sync` for the Adobe Fonts activated here.
2. Candidates: `lazuli search --script <script> --role <role>`, narrowed with `--category`,
   `--license open`, `--delivery web`, `--installed`, or `--similar-to "<family>"`; run
   `lazuli catalog sync` when `lazuli catalog status` shows no snapshot. Open-licensed libraries,
   commercial foundries, and Adobe Fonts are all candidates to explore and brainstorm with; licensing,
   purchase, or activation goes to the user.
3. Specimen: set two or three candidates, at least one a named face, in the page's real copy (title,
   paragraph, control, figures, every locale) on a throwaway page under `.lapis/specimens/`, and look
   at it: `lapis-design render check .lapis/specimens/<task>.html --task <task>-specimen --width 390`
   leaves screenshots beside its extract.
4. Record the comparison in `explorations`; lock each chosen named face with
   `lazuli lock "<family>" --role <role> --task <task>`, which records source, license, and delivery path.

Offline shipping leaves three outcomes: an installed named face with a fallback stack, OFL files the
user supplies for the project, or a generic family that won the comparison. A generic family alone is a
choice that must win it, not a fallback. Body faces are chosen for reading on the target platform;
display faces for the subject's voice. For Korean text keep the face's default tracking at body sizes
and set `word-break: keep-all` on Korean text blocks. For roles per script, choosing a face for each
role, pairing Latin with Hangul, kana, or Han, CJK line breaking, measure and leading, scale, numerals,
and display type, read `references/type.md`.

### 8. Layout - `layout.procedure`, `layout.sections`

Follow the nine steps in order: content inventory, priority, screen mode, reading order,
relationships, archetype, grid, responsive behavior, density and checks. Choose how content is
related before choosing a container. Every section answers one question a reader brings
(`answers`). For the nine fields with worked examples, the spacing scale (`tokens.space`), grids,
responsive primitives, density, and what to check after rendering, read `references/layout.md`; for
choosing the screen archetype, section kinds and their order, and what each product frame adds, read
`references/archetypes.md`.

Sketch two structures that group the content differently and compare them on the real content before
choosing (`explorations`, decision `layout`).

A chart, map, or other data view inside a section has its own decisions: choosing the form from the
question, scales and annotation, text and keyboard access to its values, data color, and what an
implementation must satisfy. For those, read `references/data-viz.md`.

For an image's job, crop/set continuity, icon-family contact sheets, or grammar inferred from
supplied assets, read `references/visual-assets.md`. Use authorized material and existing records.

### 9. Content - `content`

Use real copy, or synthetic content from the domain that is clearly synthetic - long and local
names included. Set the voice register per surface. Write key copy (headline, subhead, cta, empty
state, error) in the target locale. Test each key line by swapping the product's name for another
product's: if it stays true, rewrite it around a fact, number, or world material. Write two candidates
for the headline, subhead, and cta and keep the stronger (`explorations`, decision `copy`). Detailed
copy work belongs to the `lps-copy` skill.

### 10. Flows and stub - `flows`, `.lapis/stub.yaml`

For interactive work, list the primary flow and every flow that joins, pays, consents, or leaves.
Pair each exit flow with the flow it reverses, and give a reason for any account, identity, or
reauthentication requirement. Then write the stub (below). Flow design belongs to `lps-ux`.

### 11. Defaults - `defaults`

Walk the cards in `shared/slop/cards.yaml`. For each card whose cue matches the plan or the draft,
decide each of its rules that applies:

- **keep** with a basis - `brief`, `contract`, or `requirement` - a `keep_when` naming one of the
  rule's ids in `shared/slop/rules.yaml`, a reason that says how this plan meets that case, and the
  `evidence` that case lists: a quoted line of `brief`, a `DESIGN.md#token` of the contract in
  `context.design`, a world material, a source, the face that won in `explorations`, or a ledger
  asset. A keep whose id is not the rule's, or whose case lists evidence the keep lacks, waives
  nothing; a rule that lists no case takes no keep, and no entry lifts `plan.uncompared-decision`.
- **reject** and take one of the card's routes. A route spends a world material, the signature, or
  a plan decision; it never swaps one card for another (rejecting the dark luminous package by
  switching to the warm editorial one is still a default).

`plan check` asks about the defaults it can see in the plan. Record the others as you meet them; a
`keep` entry with a fitting `keep_when` is what stops a later check from gating that default.

### 12. Sources - `sources`

List every document, page, and file the plan relied on.

## Plan gate

1. Read the plan once as a reviewer: for each decision, is it what a page of this kind usually gets -
   the same type voice, palette, section order, motion level, or headline that would fit another
   subject? If so, add a candidate from a different source to `explorations`, or write what makes the
   default win here.
2. Run `lapis-design plan check .lapis/plans/<task>.yaml` and fix every blocking finding.
3. Run `lapis-design plan check .lapis/plans/<task>.yaml --summary`, show the user the summary and
   the defaults decisions, and wait for approval before code (a relayed run asks it as Done says). Once the user
   approves, record `approval: {state: approved}` in the plan; with nobody to ask, record `assumed` (see Done). In a
   harness plan mode, embed the plan as described in `shared/plan/HARNESS-PLAN-MODES.md`.

## Implement

For stack choice or platform adaptation, read `references/implementation.md`.

- Follow the plan. When implementation forces a change, change the YAML first and tell the user.
- Tokens become variables; no raw values in components.
- Build every state a component has: default, hover, focus, active, disabled, loading, empty, error.
- Record each image, icon set, or generated asset in `.lapis/assets.ledger.json`
  (`shared/assets/ledger.schema.yaml`) when you choose it.
- Never present invented metrics, customers, quotes, or logos as real.


## Check while working

Checks during work stay small; the full set runs once at the release gate.
When repeating a repair, follow the bounds and final full run in `ultramarine`'s
`repair-loop.md` reference; do not turn a missing check into another edit.


1. `lapis-design slop lint --plan .lapis/plans/<task>.yaml --source <source dir> -o .lapis/lint/<task>.json`.
   It needs no browser, so run it after every change to styles or markup: it finds literal colors,
   off-scale spacing, and bypassed primitives in the code (`system.*`) while they are cheap to fix.
2. `lapis-design render check <url> --task <task> --width 390`, which writes
   `.lapis/renders/<task>.narrow.json` and leaves the full extract alone, then rerun the lint with
   `--extract .lapis/renders/<task>.narrow.json` added and `-o .lapis/lint/<task>.narrow.json`.
   A page of plain files needs no server: give the
   HTML file's path (or a `file://` URL) as `<url>`, and both checks serve its folder on 127.0.0.1
   for the run, with that folder as the site root. When the render cannot run, keep the
   source-layer lint and list the render check among the checks that did not run.
3. Only when the change touched behavior: `lapis-design behavior check <url> --task <task>
   --plan .lapis/plans/<task>.yaml --stub .lapis/stub.yaml --probe <probe>`, one `--probe` per
   area you changed (forms, dialogs, choices, flows, keyboard, ...); for one control add
   `--box <id>`, with the id from the session's `nodes`. It writes `.lapis/behavior/<task>.narrow.json`.
   Then rerun the lint with `--session .lapis/behavior/<task>.narrow.json` added to the same command,
   so the report keeps every layer that has run.
4. Hand the plan, extract, and lint report to the separate critic (the `ultramarine` skill runs it).
   You wrote the design, so you do not judge it. When `ultramarine` is not installed, tell the user
   that no independent review ran and list it among the checks that did not run.

All widths, all probes, the rights check, and fresh license lookups belong to the release gate
(`ulm-release`), not to each iteration.

If a sandbox or permission prevents a check from starting Chromium or reading lazuli's user cache,
ask the user for permission once; if refused or impossible, list the check as not run with the exact
error. When the bundled browser cannot start and the host has its own way to view the page, view it
there, record what you saw as `image` or `review` evidence, and keep render check on the list of
checks that did not run; this is never a render or behavior record. Never move `LAZULI_DB` into the
project to bypass the restriction, and if a project-local database is unavoidable, keep it outside
version control and tell the user.

Render and behavior checks capture web pages; for a native screen they and the critic do not run, so
list them as not run.

## Write the stub

When the plan has flows, write `.lapis/stub.yaml` (`shared/behavior/stub.schema.yaml`) with the flows:
you know the API you are building, and `behavior check` needs a stub or a local backend to run. A page
without an API still gets a minimal stub: `version`, `clock`, empty `routes`, `collections`, and
`values`, and `variants` with empty `empty` and `partial` entries.

1. `version: 0` and `clock.start`, the moment the checker's clock starts; urgency facts are read on it.
2. `routes`: every endpoint the UI calls, as a collection operation (list, get, create, update,
   delete) or a fixed response.
3. `collections`: synthetic records, including edge cases - a long name, zero stock, an item that
   sells out.
4. `variants`: `empty` and `partial` (both required), so the empty and partial states can be driven.
5. `values`: synthetic inputs with `valid`, `invalid`, and `alternate` forms - example.com
   addresses, fictional streets, a payment provider's published test numbers. Never real people,
   accounts, or cards. Value ids are `v1`, `v2`, … and each value is keyed by one; any other key
   (`patient-name`) is refused.
6. `accounts` and `auth` when a flow signs in; `outside` stand-ins for every third-party call.
7. `urgency`: the facts behind every countdown, stock, demand, or activity claim on the page, so
   the checker can compare the claim with them.

## Reporting

Tell the user the Design Read, the signature, each rejected default with the route taken, the
checks that ran with their results, and the checks that did not run. Keep planning notes, rule
ids, and check output out of the interface itself.
