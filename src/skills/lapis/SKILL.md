---
name: lapis
description: Plans new interfaces, redesigns, and visual direction before code - brief, world materials, type and color roles, layout, key copy, and keep-or-reject decisions on named defaults - in a plan file that lapis-design checks. Use for landing pages, app screens, dashboards, restyles, and "this looks generic".
license: MIT AND CC-BY-4.0
---


# lapis

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
4. Ask only questions whose answers change the plan, as the smallest independent set. Otherwise
   write a reversible assumption into `claims.proposed` and continue.

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

The motion dial has three bands: 1-3 feedback only, 4-6 transitions that explain a change, 7-10 authored
moments. Write the band into `tokens.motion.principles` with a reduced-motion branch for each effect
(`reduced_motion: respect` is required). For timing and easing, interruption, scroll and route
enhancement, choosing between native and library animation, and delivering authored animation, read
`references/motion.md`.

### 4. Concept and signature - `direction.concept`, `direction.levers`, `layout.signature`

Start the concept from a live tension in the subject: a pottery shop's sales page can become the
record of one kiln firing. Name the form levers you will pull: scale contrast, density, rhythm,
tension and asymmetry, material and texture, type as form, or a motif from the subject. The signature
is the one element only this task has, built from a world material; the page is organized around it,
not around a hero shell.


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

### 7. Type - `tokens.type`

Decide roles - display, heading, body, ui, data, code, caption - per script. Get candidates with
`lazuli search --script <script> --role <role>`, choose, and lock each choice with
`lazuli lock "<family>" --role <role> --task <task>`, which records source, license, and delivery
path. Body faces are chosen for reading on the target platform; display faces for the subject's
voice. For Korean text keep the face's default tracking at body sizes and set `word-break: keep-all`
on Korean text blocks. For roles per script, pairing Latin with Hangul, kana, or Han, CJK line
breaking, measure and leading, scale, numerals, and display type, read `references/type.md`.

### 8. Layout - `layout.procedure`, `layout.sections`

Follow the nine steps in order: content inventory, priority, screen mode, reading order,
relationships, archetype, grid, responsive behavior, density and checks. Choose how content is
related before choosing a container. Every section answers one question a reader brings
(`answers`). For the nine fields with worked examples, the spacing scale (`tokens.space`), grids,
responsive primitives, density, and what to check after rendering, read `references/layout.md`; for
choosing the screen archetype, section kinds and their order, and what each product frame adds, read
`references/archetypes.md`.

A chart, map, or other data view inside a section has its own decisions: choosing the form from the
question, scales and annotation, text and keyboard access to its values, data color, and what an
implementation must satisfy. For those, read `references/data-viz.md`.

### 9. Content - `content`

Use real copy, or synthetic content from the domain that is clearly synthetic - long and local
names included. Set the voice register per surface. Write key copy (headline, subhead, cta, empty
state, error) in the target locale. Test each key line by swapping the product's name for another
product's: if it stays true, rewrite it around a fact, number, or world material. Detailed copy
work belongs to the `lps-copy` skill.

### 10. Flows and stub - `flows`, `.lapis/stub.yaml`

For interactive work, list the primary flow and every flow that joins, pays, consents, or leaves.
Pair each exit flow with the flow it reverses, and give a reason for any account, identity, or
reauthentication requirement. Then write the stub (below). Flow design belongs to `lps-ux`.

### 11. Defaults - `defaults`

Walk the cards in `shared/slop/cards.yaml`. For each card whose cue matches the plan or the draft,
decide each of its rules that applies:

- **keep** with a basis - `brief`, `contract`, or `requirement` - and a reason that names what
  earns it here. The rule's `keep_when` lines in `shared/slop/rules.yaml` say what usually does.
- **reject** and take one of the card's routes. A route spends a world material, the signature, or
  a plan decision; it never swaps one card for another (rejecting the dark luminous package by
  switching to the warm editorial one is still a default).

`plan check` asks about the defaults it can see in the plan. Record the others as you meet them;
a `keep` entry is what stops a later check from gating that default.

### 12. Sources - `sources`

List every document, page, and file the plan relied on.

## Plan gate

1. Run `lapis-design plan check .lapis/plans/<task>.yaml` and fix every blocking finding.
2. Run `lapis-design plan check .lapis/plans/<task>.yaml --summary`, show the user the summary and
   the defaults decisions, and wait for approval before code. In a harness plan mode, embed the
   plan as described in `shared/plan/HARNESS-PLAN-MODES.md`.

## Implement

- Follow the plan. When implementation forces a change, change the YAML first and tell the user.
- Tokens become variables; no raw values in components.
- Build every state a component has: default, hover, focus, active, disabled, loading, empty, error.
- Record each image, icon set, or generated asset in `.lapis/assets.ledger.json`
  (`shared/assets/ledger.schema.yaml`) when you choose it.
- Never present invented metrics, customers, quotes, or logos as real.


## Check while working

Checks during work stay small; the full set runs once at the release gate.

1. `lapis-design slop lint --plan .lapis/plans/<task>.yaml --source <source dir> -o .lapis/lint/<task>.json`.
   It needs no browser, so run it after every change to styles or markup: it finds literal colors,
   off-scale spacing, and bypassed primitives in the code (`system.*`) while they are cheap to fix.
2. `lapis-design render check <url> --task <task> --width 390`, then rerun the lint with
   `--extract .lapis/renders/<task>.json` added. A page of plain files needs no server: give the
   HTML file's path (or a `file://` URL) as `<url>`, and both checks serve its folder on 127.0.0.1
   for the run, with that folder as the site root. When the render cannot run, keep the
   source-layer lint and list the render check among the checks that did not run.
3. Only when the change touched behavior: `lapis-design behavior check <url> --task <task>
   --plan .lapis/plans/<task>.yaml --stub .lapis/stub.yaml --probe <probe>`, one `--probe` per
   area you changed (forms, dialogs, choices, flows, keyboard, ...), then rerun the lint with
   `--session .lapis/behavior/<task>.json` added to the same command, so the report keeps every
   layer that has run.
4. Hand the plan, extract, and lint report to the separate critic (the `ultramarine` skill runs it).
   You wrote the design, so you do not judge it. When `ultramarine` is not installed, tell the user
   that no independent review ran and list it among the checks that did not run.

All widths, all probes, the rights check, and fresh license lookups belong to the release gate
(`ulm-release`), not to each iteration.

If a sandbox or permission prevents a check from starting Chromium or reading lazuli's user cache,
ask the user for permission once; if refused or impossible, list the check as not run with the exact
error. The host's own browser tool may supply `image` or `review` evidence of what you saw, never a
render or behavior record; never move `LAZULI_DB` into the project to bypass the restriction, and if
a project-local database is unavoidable, keep it outside version control and tell the user.

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
   accounts, or cards.
6. `accounts` and `auth` when a flow signs in; `outside` stand-ins for every third-party call.
7. `urgency`: the facts behind every countdown, stock, demand, or activity claim on the page, so
   the checker can compare the claim with them.

## Reporting

Tell the user the Design Read, the signature, each rejected default with the route taken, the
checks that ran with their results, and the checks that did not run. Keep planning notes, rule
ids, and check output out of the interface itself.
