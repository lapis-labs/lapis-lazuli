---
name: lapis
description: Plans new interfaces, redesigns, and visual direction before code - brief, world materials, type and color roles, layout, key copy, the candidates compared for each open decision, and keep-or-reject decisions on named defaults - in a plan file that lapis-design checks. Use for landing pages, app screens, dashboards, restyles, and "this looks generic".
license: MIT AND CC-BY-4.0
---


# lapis

## Done

- Done is when `lapis-design next --task <task>` says done. Run it before you report, do the one step it names, and
  repeat; a plan, a check, or a page that merely looks finished is not done.
- A missing or invalid input, a plan blocker, and a timeout are not done: that step comes back. Only a failure of the
  environment, such as a browser that cannot start, counts, and the tool records it itself.
- The release gate may say the work does not ship. Report that verdict; it is not a step to repeat, and never a reason
  to edit a report or waive a finding.
- A passing gate and a `next` that says done are a floor: they say no defects were found, not that the page fits its
  genre, shows the right information, or lets a visitor finish their task at phone and desktop width. Say that
  when you report, and do not call a pass good.
- With nobody to ask (`LAPIS_UNATTENDED=1`), record `approval: {state: assumed, reason: ...}` in the plan and go on;
  `approved` is only a person's.
- When a person will answer, a user or an operator who relays replies, write the questions to
  `.lapis/questions/<task>.md`, marked with their kind on the first line (see Questions and kinds), and stop with them
  as your last message: `next` says `waiting-for-user` and the exit gate lets that stop pass. A file with no kind does
  not wait. Record the replies in `.lapis/answers/<task>.md`, the brief record: keep what it holds, add replies under
  their own headings, cite it in the plan (`context.other`), and run `next` again.
- At `done` and at every approval wait, `next` returns an owner block (`--json`: `owner_block`) and writes it to
  `.lapis/owner/<task>.md`: the requirement states, the owner's decisions, the facts shown with their sources, protected
  changes, disputes, and what did not run. It ends in a `lapis-owner-block <sha8>` line. Paste it unchanged ahead of your
  own summary at `done`, and into the questions file of an approval ask (an ask without the current line comes back as
  `draft-review`). Never edit, shorten, or write it yourself. It lists `## Decisions you have not made`: what you filled
  in that the owner never decided (style, objects, signature, color and where each color sits, layout, motion, type,
  copy). Nothing is sealed or approved until the owner's reply acknowledges that block by its digest, as the untagged
  line `- Gaps seen (lapis-owner-block <sha8>): "<their words>"`, or decides the items (`- [declared] color: <what they
  decided>`, `layout:`, `motion:`, `signature:`, `type <role>:`); a plan approved without it comes back as
  `approval-gaps`.
- Report whether taste was given and cited, not given (the direction is your own reading), or unrecorded;
  `.lapis/taste.md` and `direction.taste` are described in `lps-brief`'s record guide.
- Follow the user's words. When they forbid network use, lookups, or downloads during the work and nobody can be
  asked, do not look things up and do not stop: decline the references step with their line, as the brief record
  holds it (`lapis-design next --task <task> --declined references --brief-line "<the line>"`), and plan from local
  material. Render and behavior checks serve the page on 127.0.0.1 and run locally.
- The order is brief, requirements, references, direction, plan, then code: write no markup, style, script, or component
  file while `next` names `brief`, `requirements`, `references`, `owner-direction`, `diverge`, or a plan step. Page
  code written first comes back as `plan-order`, and an unattended run's page writes may be refused until then. With a person to answer, the first code is a thin slice
  (see Slice).
- The owner's words are kept by the CLI, not by you. `requirements seal` (see `lps-brief`) copies their brief files and
  `[declared]` answers into `.lapis/requirements/<task>.json` as rows with stable ids, and the critic judges every row
  against what is shown. Paraphrase in the plan as you need to; a row you narrow or leave out still shows as `partly`
  or `missing`, and only an owner's reply that quotes its id drops it. `lapis-design` alone writes
  `.lapis/requirements/`, `state/`, `changes/`, and `owner/`; a hand edit is detected and shown to the owner. It also logs
  each change to the plan's protected fields in `.lapis/changes/<task>.jsonl`: a change is never forbidden, and the owner
  sees the ones made while a related finding was open or after the slice was approved.

lapis turns a request into a design contract - the plan file `.lapis/plans/<task>.yaml` - and then
into an implementation that follows it. The plan is written before code, checked by
`lapis-design plan check`, approved by the user, and read by every later check.

## Questions and kinds

The first line of `.lapis/questions/<task>.md` says what the file is: `lapis-questions: brief|direction|approval|ask`.
A file without it, or with another word, does not wait; `next` names its step and says to mark the kind.

| Kind | Holds | Limits |
|---|---|---|
| `brief` | facts only the owner has (`lps-brief`) | at most 6 numbered questions a round, 2 rounds; the exit gate lets a run wait twice before a plan and once after |
| `direction` | what a named style, a core object, or a signature element should do (the direction conversation) | none; every turn needs an open item |
| `approval` | the rendered slice, with the owner block (see Slice) | the exit gate lets a run wait once after a plan |
| `ask` | one doubt during the work (see Ask on doubt) | one question, at most 150 words, one per checkpoint |

### Ask on doubt

When the work hits a conflict or a doubt, ask one short question instead of settling it alone or burying it in a report.
Ask for one of six reasons: a requirement that cannot be met as written, two requirements that conflict, a finding whose
fix would change what the owner decided, a move to a direction the sealed slice does not cover, a reference that
contradicts a requirement, or agent-alone time or a job past its budget. `next` raises three of them itself as the step
`ask`. An ask is one numbered question with a `Trigger:`, a `Default:`, and at most two "unless you object" lines, and it
has no owner block. Only one ask is allowed per checkpoint; past it, take your default and record it as `[assumed]` with
its `Basis:` under `## Asks`. With nobody to ask, take the default and record it the same way. Read
`references/asks.md` for the triggers, the file shape, how the question is shown with or without a question tool, and
how answers are recorded.

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
4. Before the plan of a new surface or a redesign, run `lps-brief`: it reads, looks up, asks only what stays open
   (a relayed run: see Done), and writes `.lapis/answers/<task>.md`, which `next` asks for until it exists on a
   create plan. For a create plan it then seals the owner's own words with `requirements seal` (`next` asks for that
   as `requirements`). Assumed answers go to `claims.proposed`, never `known` or `declared`. A repair asks only what its
   findings leave open.
   Read project taste once and reuse it; without given taste, record `Taste: not given`, never an assumed preference.
5. Before the plan of a create run, look at references yourself: `next` names `references` until
   `.lapis/references/<task>.md` passes. Search, capture with `lazuli ref ... --task <task>`, open the
   captures, and read a page's HTML and CSS, as the `lzl-research` skill's exploration guide describes. If the
   user's words forbid the lookups, decline the step with their line instead (see Done).
6. After the references, hold the direction conversation (`references/direction-conversation.md`): `next` names
   `owner-direction` until the owner has decided, item by item, what each named style does, how each core object is
   represented, and what each signature element carries. Write `.lapis/direction/<task>.yaml`, ask in one message
   (`lapis-questions: direction`), record the answers under `## Direction <n>`, and never decode a named style alone.
   With nobody to ask, record `[assumed]` answers with their basis.
7. Then make the rough first views (`references/diverge.md`): `next` names `diverge` until
   `lapis-design diverge start`, the roughs and their cards, `check`, and `seal` are done. The CLI draws each rough's
   reference direction, core-object representation, and color allocation, so you cannot pick them; the owner picks one at
   the second turn of the direction conversation, and the plan starts from that pick.

For supplied design sources or a role transfer, read `shared/handoff/HANDOFF.md` → **Intake and authority**
and **Projection annotations** before reconciling them; read **Export** and **Return and freshness** when
sending/receiving a packet. Keep the canonical plan; source access and export success grant no approval.

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
  whether it does.

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
and needs no candidates. `contract` holds only when `context.design` is set. A create plan whose open
decision has no comparison, or whose type candidates are all generic families, is blocked.
For role/script boundaries, matched rendered relations, and implemented motion alternatives,
read `references/explorations.md` before recording a comparison. Names and reordered sections alone
are not alternative structures; a motion sketch is a proposal, not an observed comparison.

## Write the plan

Work in this order; each step fills the named plan fields. The schema is
`shared/plan/schema.yaml`.

Each reference opens with a `## Sections` index, one line per section with the decision it serves. Read the index, then only the
sections the step needs, found by their headings; do not read a whole reference file.
`next` names the phase's required sub-skill and checks its load record: copy needs `lps-copy`,
tokens/system needs `lps-system`, and pre-show review/release needs `ultramarine`. Load the named sections
and follow that skill's first step; a missing load is `skill-load`, never a silent pass. Use the current
session/context identifier consistently (set `LAPIS_CONTEXT` to enforce context reuse across commands).

### 1. Brief and claims - `brief`, `claims`

`product_frame` is the surface's task, not the company's category. `one_job` is the single job this
screen must do. Keep `claims` apart: known (evidence), declared (the user said), proposed (you
suggest), unresolved (open).

### 2. World materials - `world_materials`

Concrete things from the subject: objects, records, processes, numbers, marks, places, tools.
Never adjectives or moods. Find them in `PRODUCT.md`, the user's content, real photographs, and the
subject's own documents. Four to six is a good start; create mode needs at least one. These are
what replace every default you reject, so collect them before choosing type, color, or layout.
Supplied materials are optional inventory; decide each image's role and compare no photo before
letting it set identity or structure (`references/visual-assets.md`).


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
style word - it is decoded with the owner, not alone (start, step 6;
`references/direction-conversation.md`) - set `style_frame: named`, write the word in `direction.read.style_name`, and
keep it in `claims.declared`. When a style file matches, read it before step 4:
`references/style-bento-and-modern-saas.md` when the word is bento, or modern or professional for a
software product's page or tool; `references/style-minimalism-and-editorial.md` when it is minimal,
clean, or editorial. When none matches, write in `direction.read.text` what the word assumes about
the content. A style file says what the style assumes about the content and which plan fields make it
this subject's; it is not a look to reproduce.

For mixed style influences and their ownership, read `references/form-levers.md`; for a named style
or regional reference that is still an open direction, read `references/style-branches.md`.

The motion dial has three bands: 1-3 feedback only, 4-6 transitions that explain a change, 7-10 authored
moments. Write the band into `tokens.motion.principles` with a reduced-motion branch for each effect
(`respect` is the only accepted value for `reduced_motion`). Read `references/motion.md` → **Motion as a
system** first, then the timing, interruption, scroll/route, or delivery section the interaction needs.
Implement the picked band and its neighbor on the same real interaction, observe playback, and record
the comparison in `explorations` (decision `motion`).

### 4. Concept and signature - `direction.concept`, `direction.levers`, `layout.signature`

Before committing, compare directions that differ in relationship or structure - the page organized
around a different thing from the subject, not the same layout in another palette. In a create run they
are the `diverge` roughs (start, step 7) with the pick the owner made at the second turn; keep them in
`explorations` (decision `direction`), each named by its relation. Otherwise write two. The pick
becomes `direction.concept`; the others say why they lost.

Write the concept as a relation that changes order, emphasis, or labels, starting from a live tension
in the subject: a pottery shop's sales page becomes the record of one kiln firing. A mood or a style
word is not a concept. Write each lever as one sentence: the lever (scale, density, rhythm, tension,
material, type as form, or motif), what visibly changes, and the world material it comes from, named
as it is written in `world_materials`. A lever's bare name, or words such as clean, modern, and bold,
are not levers; `plan check` blocks a lever that names no world material. For how each lever works
and where it lands in the plan, read `references/form-levers.md`. The signature is the one element
only this task has, built from a world material; the page is organized around it, not around a hero
shell. Once the page renders and works, read it once against the concept and refine it once; then stop and report
what is still unresolved, in place of another round on taste (`ultramarine`'s `repair-loop.md`, Refine a direction
once). A surface that the contract in `context.design` already fixes is not a new direction and gets no such pass.


### 5. References - `references`

Pages the user gave, and the references you looked at in the `references` step (cite
`.lapis/references/<task>.md` in `context.other`). Capture a page the user gave with
`lazuli ref capture <url> --rights <rights>`; the run's own captures already have profiles in
`.lapis/refs/`. Record rights, mode, what to take (relations: rhythm, ratios, sequence, a label's
job), and what to leave (brand colors, illustrations, copy, the type pairing). References inform
relations and decisions: take relations, never assets, text, or a layout wholesale, and name the
reference as the `source` of the `explorations` candidate it shaped.

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

Give every `field` and `identity` role an `area`: where the color sits and roughly how much of the screen it owns
(a picked rough's card carries it, and the plan takes the card's roles unchanged). A value survives into the CSS; its area
does not unless the plan says it.

For an open decision, run `references/color.md` → **Run the color comparison**: fixed/open inputs,
role hypotheses, two palettes on matched real-screen specimens, then remove role failures, choose,
and stop. Record candidate artifacts/values and same-context captures in `explorations`.

Give each `field` and `identity` role an `area`: where the color sits and about how much of the screen it owns, as in
"canvas of every section, about 70% of the first view" or "the stone and the primary action only, about 3%". The values
survive into CSS and their areas do not, and the area is what makes a palette a different one; a create plan without
it is `plan.color-area-missing`.

### 7. Type - `tokens.type`

Decide roles - display, heading, body, ui, data, code, caption - per script, then explore faces before
choosing one:

1. Inventory: `lazuli local fonts --summary`; `--family <text>` for one family's faces, scripts, and
   measurements; `--origin adobe-sync` for the Adobe Fonts activated here.
2. Candidates: `lazuli search --script <script> --role <role>`, narrowed with `--category`,
   `--license open`, `--delivery web`, `--installed`, or `--similar-to "<family>"`; run
   `lazuli catalog sync` when `lazuli catalog status` shows no snapshot. Open-licensed libraries,
   commercial foundries, and Adobe Fonts are all candidates to explore and brainstorm with; an
   open-licensed family may be fetched and bundled, and a commercial license or an Adobe activation goes
   to the user.
3. Specimen: set two or three candidates, at least one a named face, in the page's real copy (title,
   paragraph, control, figures, every locale) on a throwaway page under `.lapis/specimens/`, and look
   at it: `lapis-design render check .lapis/specimens/<task>.html --task <task>-specimen --width 390`
   leaves screenshots beside its extract.
4. Record the comparison in `explorations`; lock each chosen named face with
   `lazuli lock "<family>" --role <role> --task <task>`, which records source, license, and delivery path.
   Files that ship are fetched from the family's official source with their license text
   (`lazuli fetch`), and the license behind any font that ships is researched and recorded
   (`lzl-fonts`); a font whose license stays unknown after that does not ship.

Offline, shipping leaves three outcomes: an installed named face with a fallback stack, open-licensed
files already in the project or installed with a verified license, or a generic family that won the
comparison. A generic family alone is a choice that must win it, not a fallback. Body faces are chosen
for reading on the target platform; display faces for the subject's voice. For Korean text keep the
face's default tracking at body sizes and set `word-break: keep-all` on Korean text blocks. For roles
per script, choosing a face for each role, pairing Latin with Hangul, kana, or Han, CJK line breaking,
measure and leading, scale, numerals, and display type, read `references/type.md`.

### 8. Layout - `layout.procedure`, `layout.sections`

Follow the nine steps in order: content inventory, priority, screen mode, reading order,
relationships, archetype, grid, responsive behavior, density and checks. Choose how content is
related before choosing a container. Every section answers one question a reader brings
(`answers`). For the nine fields with worked examples, the spacing scale (`tokens.space`), grids,
responsive primitives, density, and what to check after rendering, read `references/layout.md`; for
choosing the screen archetype, section kinds and their order, what a content unit is, and what each product frame
adds, read `references/archetypes.md`.

Sketch two structures that group the content differently and compare them on the real content before
choosing (`explorations`, decision `layout`); `references/layout.md`, step 6, says how to compare them apart from
their finish.

Derive the opening from the content's own relation, the subject's own objects, or the sequence the
visitor follows. A column with the large heading beside a column with an image or mock is a named
default (`split-opening`); it stays only when it won a rendered comparison against an opening built
without it, or another `keep_when` of `layout.split-hero` holds.

Open on the surface's own task, document, or work before a category hero; a genre has a structure of its own (a
news page, an exhibition, a booking in steps; `references/archetypes.md`, Genre structures). Compose the phone as its
own arrangement of the task, not the wide page in one column, and look at its first view and its length yourself: a
rail or a bar of items does not carry over (`references/layout.md`, the phone as its own arrangement).

A chart, map, or other data view inside a section has its own decisions: choosing the form from the
question, scales and annotation, text and keyboard access to its values, data color, and what an
implementation must satisfy. For those, read `references/data-viz.md`.

For an image's job, crop/set continuity, icon-family contact sheets, or grammar inferred from
supplied assets, read `references/visual-assets.md`. Use authorized material and existing records.

### 9. Content - `content`

Use real copy, or synthetic content from the domain that is clearly synthetic - long and local
names included. Set the voice per locale and role (`content.voice.locales`: sentence register, speaker, compact roles). Write key copy (headline, subhead, cta, empty
state, error) in the target locale. Test each key line by swapping the product's name for another
product's: if it stays true, rewrite it around a fact, number, or world material. Write two candidates
for the headline, subhead, and cta and keep the stronger (`explorations`, decision `copy`). Detailed
copy work belongs to the `lps-copy` skill.

Decide what the page must show - the subject and the visitor's task - and what it must not: how it
was made, that it is a demo, what changed. A notice the brief requires, such as "this page uses
fictional example data", appears once, as a short line in the footer or a small persistent label,
never in the hero, a heading, or beside each section (`copy.meta-text`).

For a dashboard or a report, choose what to count from the decisions the reader makes; a total nobody acts on does
not earn the first view.

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
  `context.design`, a world material, a source, the face or the opening that won a rendered
  comparison in `explorations`, or a ledger asset. A keep whose id is not the rule's, or whose case
  lists evidence the keep lacks, waives
  nothing; a rule that lists no case takes no keep, and no entry lifts `plan.uncompared-decision`.
- **reject** and take one of the card's routes. A route spends a world material, the signature, or
  a plan decision; it never swaps one card for another (rejecting the dark luminous package by
  switching to the warm editorial one is still a default).

`plan check` asks about the defaults it can see in the plan. Record the others as you meet them; a
`keep` entry with a fitting `keep_when` is what stops a later check from gating that default.

For what these defaults look like on a page, why they read as generated, and the per-genre packages, read
`references/anti-slop.md`.

### 12. Sources - `sources`

List every document, page, and file the plan relied on.

## Plan gate

1. Read the plan once as a reviewer: for each decision, is it what a page of this kind usually gets -
   the same type voice, palette, section order, motion level, or headline that would fit another
   subject? If so, add a candidate from a different source to `explorations`, or write what makes the
   default win here.
2. Run `lapis-design plan check .lapis/plans/<task>.yaml` and fix every blocking finding.
3. Run `lapis-design plan check .lapis/plans/<task>.yaml --summary` and read the summary with the defaults decisions
   yourself. In a create run that a person answers, do not ask them to approve the plan on that text: build the slice
   and ask on the rendered page (see Slice); the direction was decided with them before the plan (start, step 6). In any
   other run show the user the summary and the defaults decisions
   and wait for approval before code (a relayed run asks it as Done says). Once the user approves, record
   `approval: {state: approved}` in the plan; with nobody to ask, record `assumed` (see Done). In a harness plan
   mode, embed the plan as described in `shared/plan/HARNESS-PLAN-MODES.md`.

## Slice

In a create run that a person answers (`LAPIS_UNATTENDED` unset), `next` names `slice` once the plan steps pass,
before `fonts-lock`. The owner approves on a rendered page, because composition and copy are judged by seeing them. The
slice is one page, built from the pick the owner made at the direction turns.

1. Declare the slice page first: a `pages[]` entry with `direction: new`, its `url`, and its `sources` (at most 12
   files) in `.lapis/drafts/<task>.yaml`. From the first time `next` names `slice` until the slice is sealed you may
   write only those files; any other page file is refused, and so is every page file when no page is declared.
2. Build the first view and the one section the brief puts first, not the whole page, and capture both at 390 and
   1440, at most 3,600 px tall at 1440 (a taller page comes back as `slice`). Serve the folder with
   `lapis-design preview start --task <task>` and capture that address.
3. Run the critic on `lapis-design critic packet` and `lapis-design draft check` (`ultramarine`'s
   `pre-show-review.md`). Open core findings no longer block the question: they go to the owner as decisions.
4. Ask within 60 minutes or 40 page writes of `next` naming `slice` (or of the owner's last reply): write
   `.lapis/questions/<task>.md`, first line `lapis-questions: approval`, link the page, paste the owner block, put each
   open core finding to the owner as a decision, and say that copy is provisional until it has been seen rendered. Past
   either limit every page write is refused until that question exists; it is never refused to write under `.lapis/`.
5. Record the owner's reply in `.lapis/answers/<task>.md` under its own heading, in their words. A plain approval is an
   untagged item (`- Approved the slice: <their words>`); feedback that changes what the owner wants is `[declared]`;
   their acknowledgment of the gaps is `- Gaps seen (lapis-owner-block <sha8>): "<their words>"`; their decision on an
   open core finding is `- [declared] Ask finding-vs-decision: <rule id> — <their words>`. If they say to skip the
   slice, record `- Slice skipped: "<their words>"`, which lifts the hold.
6. A reply that rejects the composition or the core-object representation is a direction reply: go back to the second
   direction turn instead of rebuilding the slice blind. A reply that changes a value, copy, or a component is a slice
   revision: `next` names round 2 (and so on), the hold and the clock go on, revise within the declared files and ask
   again. There is no round limit.
7. Record `approval: {state: approved}` only when the owner approved, then run `next`, which seals the slice. The seal
   keeps the page, digests of what was shown, and the protected values, so the owner block lists later protected
   changes as changed since the owner approved. A new critic report or draft record makes the pasted block's marker
   stale: run `lapis-design draft check` and paste the block again.

## Implement

For stack choice or platform adaptation, read `references/implementation.md`; for a surface that
crosses platforms, `references/platforms.md`; for email or a host-controlled surface,
`references/email.md`; for an authorized 3D asset, `references/3d.md`.

- Follow the plan. When implementation forces a change, change the YAML first and tell the user.
- Edit the part that changes, one block of a file or one field of the plan; do not rewrite a whole file or the plan, which
  would also overwrite what the plan records as approved, kept, or waived.
- Tokens become variables; no raw values in components.
- Build every state a component has: default, hover, focus, active, disabled, loading, empty, error.
- Record each image, icon set, or generated asset in `.lapis/assets.ledger.json`
  (`shared/assets/ledger.schema.yaml`) when you choose it.
- Never present invented metrics, customers, quotes, or logos as real.
- Copy is provisional until the owner has seen it rendered. Never call it final in a spec, an assignment to another
  agent, or a handoff before then.
- Give a delegated build one section, or one handoff scope, per worker, as a handoff packet or as text that cites the
  requirement ids (`lapis-design requirements show --task <task>`) and the sealed slice. A free-form site spec is not
  the transfer.


## Check while working

Checks during work stay small; the full set runs once at the release gate.
Before asking the owner to look at or approve a rendered draft, load `ultramarine` and follow its
`pre-show-review.md` reference. Record the exact shown pages and narrow review in
`.lapis/drafts/<task>.yaml`; `next` requires `draft-review` before that approval wait. A pure question
with no draft stays allowed. This checkpoint is not the full release gate.
When repeating a repair, follow the bounds and final full run in `ultramarine`'s
`repair-loop.md` reference; do not turn a missing check into another edit.
While fixing, rerun the narrowest check that observes the change (one width, one probe, one lint layer or rule) and run the
full set once, after the last change.

Before you report, walk the page yourself as its visitor: take one to three tasks from the brief (find today's hours
and book; see which line is delayed now) and do them on the 1440 and 390 captures, noting where you looked first,
what you had to read or scroll past, and where you got stuck. A page that passes every check can still fail the walk.
Nothing records this walk; the critic's walkthroughs are the ones the owner sees.
Read `.lapis/taste.md` against the plan and captures too; report a conflict or an `against` stance as a non-blocking
`review.taste-conflict` finding for the user to confirm, not as permission to override their words.
After the walk, compare ours beside two or three of your own reference captures at 390 and 1440; say why a visitor
would not choose ours, following the critic's reference-comparison step, without turning it into a score or gate.


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
4. Build the critic's input with `lapis-design critic packet --task <task>` (for a draft, add its narrow `--extract`,
   `--lint`, and `--session`) and hand the separate critic that packet; the `ultramarine` skill runs it. You wrote the
   design, so you do not judge it. The packet leaves out your reasons on purpose, and a critic report counts only
   for the packet it names. When `ultramarine` is not installed, tell the user that no independent review ran and
   list it among the checks that did not run.

Do not open the `lapis_design` source to argue with a finding. Put a finding you believe is wrong in
`.lapis/disputes/<task>.yaml` (`{report, rule_id, location?, observed, reason, refs}`, schema
`shared/review/disputes.schema.yaml`): the critic re-judges it on the captures without your reason, and the owner sees
both. A dispute does not clear the finding.

Never stop a process by pattern (`pkill`, `killall`, or a `pgrep` piped to `kill`): other work shares the machine. Stop
only a process id a command recorded, such as the one in `.lapis/logs/<task>.behavior.pid`.

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

Start with the owner block `next` returned at done, unchanged. Then tell the user the Design Read, the signature, each
rejected default with the route taken, the checks that ran with their results, and the checks that did not run. Keep
planning notes, rule ids, and check output out of the interface itself.
