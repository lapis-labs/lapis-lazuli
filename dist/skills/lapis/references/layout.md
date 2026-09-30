# Layout

This file backs plan step 8. The plan holds the nine fields of `layout.procedure`, `layout.sections`
(`id`, `archetype`, `answers`), `layout.signature`, and `tokens.space` (`base_px`, `scale`). Measure,
leading, and the type scale are in `type.md`; what each screen and section archetype is made
of is in `archetypes.md`.

```yaml
layout:
  procedure:
    content_inventory: [...]
    priority: [...]
    screen_mode: "..."
    reading_order: [...]
    relationships: [...]
    archetype: "..."
    grid: "..."
    responsive: "..."
    density_and_checks: "..."
  sections:
    - { id: ..., archetype: ..., answers: "..." }
  signature: "..."
tokens:
  space: { base_px: 4, scale: [4, 8, 12, 16, 24, 32, 48, 64, 96] }
```

The examples continue the example plan's pottery page: twenty-four pieces from one firing, reserved
mostly on phones, Korean copy, the firing log row as the signature.

## The nine steps

Work in order; each step narrows the next. A structure picked before steps 1 to 5 is a template, and
the `template-page` card is the way back.

### 1. Content inventory - `content_inventory`

*What is really on this screen, and how large can each item get?*

Write one entry per real item or action, not per box: what it is, its length range (the shortest and
longest real value in each locale), whether it is required, and its states (empty, loading, error,
sold out, selected). Use real content, or clearly synthetic domain content with long and local names;
placeholder text and identical items hide the risks layout must absorb.

```yaml
content_inventory:
  - "24 pieces: photo (portrait or landscape), name, glaze number, size, price, open or reserved"
  - "piece names from 2 to 18 Hangul syllables; one clay name in long unbroken Latin"
  - "firing log: date, peak temperature, cone, hours, notes; the kiln temperature curve"
  - "reservation: pickup or delivery (regions unresolved), address, reservation number"
  - "next-firing notice: email signup and its withdrawal"
```

### 2. Priority - `priority`

*Which item decides whether this screen did its one job?*

Write the inventory ranked by the reader's task and the cost of missing each item, not by who asked for
it: the item that serves `brief.one_job`, then evidence and comparison, secondary actions, detail and
exceptions, utilities and legal context. Two items claiming first place mean the brief is unresolved;
ask, or record an assumption in `claims.proposed`. Note what may move to a later view but must stay.
When siblings in one group differ in rank, such as a recommended option, write each one's `priority`
entry as its visible label exactly as it renders, in the page's language, even when the rest of the plan
is in English: the render comparison finds ranked items by matching that text.

```yaml
priority: [pieces still open, reserving one piece, how this firing went, next-firing notice]
```

### 3. Screen mode - `screen_mode`

*What does a reader of this screen mainly do: decide, work, read, or take in?*

Write this screen's mode from `direction.read.surface_mode`, and name the region where a second mode
takes over. The mode sets what layout emphasizes.

| Mode | Layout emphasis | The reader's first question |
|---|---|---|
| persuade | narrative, evidence, one clear decision | why this, for whom, what next? |
| operate | state, controls, scan speed, recovery | what is happening, and what can I do now? |
| read | measure, hierarchy, wayfinding, resumption | how do I follow this and come back to it? |
| experience | the subject, pacing, exploration | what should I notice, without losing control? |

Mode belongs to the screen, not the product: a shop's collection page persuades, its order history
operates.

```yaml
screen_mode: "persuade from the log row through the gallery; operate from piece detail through reservation"
```

### 4. Reading order - `reading_order`

*In what order must a reader, a screen reader, and the keyboard meet the content?*

Write the sequence before placing anything in columns. The one-column state usually shows it most
clearly; wider layouts may set supporting regions beside the main one, but the sequence stays.
Source order, focus order, and visual order agree: no CSS reordering (`order`, grid placement,
`flex-direction: row-reverse`) that makes focus jump, and never a positive `tabindex`. Reading-pattern
studies describe tendencies, not laws. A heading and the text that depends on it stay in one reading
path, not in separate columns. Navigation models and information architecture belong to the `lps-ux`
skill.

```yaml
reading_order:
  - "firing log row: date, peak temperature, pieces out"
  - gallery of pieces
  - piece detail with price and reserve
  - full firing log with the kiln curve
  - next-firing notice
```

### 5. Relationships - `relationships`

*How are these items related, and what will show that relation?*

Choose the relation before the container. Write one line per region: the relation, the structure it
starts from, and the boundary that shows it.

| Relation | Starting structure | Boundary |
|---|---|---|
| continuous reading | document flow with headings in a reading measure | space and type hierarchy; boxes interrupt it |
| comparable repeated fields | semantic table or aligned rows | shared columns first; a rule or row tint only where tracking needs it |
| ordered sequence | ordered list, steps, timeline | order in the source; connectors only where continuation is unclear |
| independently browsed rich objects | list, gallery, or card collection | a card when each object needs its own browsing surface; a card need not be clickable |
| one object inspected from a set | list plus detail | selection and the way back stay visible |
| structural region | header, navigation, aside, pane, section | alignment, a plane change, or one divider, not an object look |
| temporary layer | menu, popover, sheet, or dialog, chosen by behavior | containment and elevation, with focus, dismissal, and return |

A boundary claims that things belong together. Space with shared alignment, a rule, a tonal plane, and
a container are alternatives, not a ladder: pick the one that states the relation. Enclose only true
groups; an action inside a region acts on exactly what it holds. When cards become the whole structure,
nest, or exist to complete a shape, walk the `boxed-everything` card. When a grouping stays unresolved,
render two viable groupings with the same content and choose by the task.

```yaml
relationships:
  - "pieces: independently browsed peers - a gallery of equal cells, the photo edge is the boundary"
  - "piece facts: comparable fields - glaze number, size, price on the same lines under every photo"
  - "firing log: comparable repeated fields - a table in the log sheet's own columns, ruled like the sheet"
  - "reservation: temporary layer - a sheet opened from piece detail"
  - "notice signup: structural region - one rule above it, no box"
```

### 6. Archetype - `archetype`

*Which recurring task structure carries the first priority?*

Choose by the shape of the task (compare, monitor, browse and inspect, edit records, give input,
create, commit), never by visual style. Take the simplest archetype that supports the first priority,
and combine two only at a clear boundary, such as an overview that leads to a separate record view.
`archetypes.md` describes each screen archetype and the section archetypes that
`layout.sections` uses. Record the runner-up and why it lost in `claims.proposed`, so the same
structure does not return under another name.

```yaml
archetype: list-detail
# claims.proposed: "A shop-grid landing lost: it hides the log and puts reserving behind a shell"
```

### 7. Grid - `grid`

*Which lines coordinate the content, and how wide may each kind of content run?*

Write the grid kind, columns, gutters, outer margins, maximum content width, the reading measure, and
the alignment lines that headings, body, controls, and data share. A grid coordinates decisions; it
does not make them.

```yaml
grid: "log-sheet grid: 4, 8, or 12 columns, changing where a 20rem gallery cell stops fitting; gutters
  16/24/24 and side margins 16/24/32 in those states;
  content max 1280; log notes in a reading column set by type measure; gallery cells and the log table
  share one start edge and the same column lines; the sheet's ruled rows set the rhythm of piece facts"
```

### 8. Responsive - `responsive`

*What happens to each region as the width changes?*

For each region and width, write its order, whether it reflows, stacks, changes presentation, scrolls
inside its own labeled region, moves to a secondary view or disclosure, or is removed because it was a
decorative duplicate, and its density. Name the intrinsic primitive each region uses and its
parameters.

```yaml
responsive: >
  log row: switcher, one row when wide, a stacked record when narrow; the full log table scrolls in
  its own labeled region, date column fixed. gallery: grid, 20rem minimum track, so 1/2/3 columns at
  390/768/1440; photos in a 4:5 frame. price and reserve: cluster, reserve beside the price at every
  width. piece detail: sidebar that stacks when the photo would drop below half the width; reservation
  a full-height sheet at 390, a side panel at 1440. notice last at every width.
```

### 9. Density and checks - `density_and_checks`

*How much sits in each view, and what will show the layout holds?*

Write the density decision per screen or region, starting from `direction.dials.density`, then what
you will verify: the real minimum and maximum content, every state, the narrowest and widest widths,
text at 200%, each locale, and the inputs the product promises.

```yaml
density_and_checks: "dial 4: gallery open, log table compact with tabular figures. Check 24 real pieces
  and a sold-out one, the 18-syllable name and the Latin clay name at 320, text at 200%, reserving by
  keyboard alone, and the log table scrolling inside its region while the page does not"
```

## Sections and the signature

`layout.sections` lists the page's sections in order. Each has an `id` the implementation reuses, an
`archetype` from `archetypes.md`, and `answers`: the one question a reader brings to that
section, in the reader's words.

- Order sections by the questions readers bring, in the order they arise. An order that could be
  shuffled without changing the argument follows a template; walk `template-page`.
- One question per section: a section answering two splits, a section answering none goes.
- Give each section the structure its relation needs (step 5). Change composition when the relation
  changes, never only to vary the page; repeated structure is right for repeated data.
- Image and text rows alternating by rule, background bands that mark no new question, and the same
  small label or number opening every section are defaults (`template-page`, `label-above-heading`).
  Number sections only when they are real steps, ranks, or records.
- Section headings and other key copy are the `lps-copy` skill's work.

`layout.signature` names the one element only this task has, built from a world material, which the
page is organized around (plan step 4). Write it as the element's plain name, give it a place in
`reading_order` and in a section, and mark that element with `data-lapis-signature` in the
implementation. A signature that only decorates, or that fills the image slot of a stock opening,
organizes nothing; opening the page on the signature is different when the sections that follow grow
from it.

```yaml
sections:
  - { id: firing-log, archetype: signature, answers: "Which firing is this, and how did it go?" }
  - { id: works, archetype: list, answers: "Which pieces can I still reserve?" }
signature: firing log row
```

## Spacing - `tokens.space`

Space states relationships; the scale makes them repeatable.

- `base_px` is the unit every step is a multiple of. A 4 px base suits interfaces with compact controls
  and half steps; an 8 px base suits surfaces composed in larger steps. Both are conventions. Native
  apps use the platform's own unit and spacing grid.
- `scale` lists the steps in use, in px, ascending. A typical 4 px scale is 4, 8, 12, 16, 24, 32, 48,
  64, 96, 128. List only steps with a job: checks compare rendered gaps with `scale` when it is present,
  and with multiples of `base_px` otherwise.
- `DESIGN.md` spacing wins: copy its base and steps, and put a new step in `proposed_design_changes`.
  A starter theme's spacing kept unchanged beside a new palette is the `starter-surface` card.
- Turning the scale into token files and component spacing is the `lps-system` skill's work.

Assign steps to relation levels, and keep each level clearly larger than the one inside it:

| Level | Examples | Pottery page at 390 / 1440 |
|---|---|---|
| inside a component | icon to label, label to field | 8 / 8 |
| between siblings | form fields, the facts under a photo | 16 / 16 |
| between groups | the gallery and its sort control, piece facts and reserve | 32 / 48 |
| between sections | log row to gallery, gallery to notice | 64 / 96 |

Roughly doubling at the major levels is a common start; content, density, and width decide the rest.
When the padding inside a card equals the space between sections, the page loses its grouping.

- Ownership: a component owns its padding, a layout parent owns the gaps between its children (`gap`),
  and the page shell owns outer insets and maximum widths. Children carry no external margin made to
  fit one caller.
- Record px in the plan; implement in `rem` where space should follow the reader's text size.
- The density dial moves each level to a smaller or larger step; it does not rescale the scale. A
  compact mode remaps a few tokens (row height, control padding, panel gap, section gap) and never
  touches target size, focus visibility, or the difference between levels.
- Optical corrections use existing steps or a component token recorded beside the component, and never
  shrink a hit area or clip a focus outline.

## Relations the composition holds

Hierarchy makes priority visible before the words are read. Write it as relations that can be checked on
the render, not as adjectives.

| Relation | Holds when |
|---|---|
| proximity order | gap inside a group < gap between groups < gap between sections, at every width |
| heading attachment | more space above a heading than below it, so it belongs to what follows |
| same role, same line | items with one role share a start edge or baseline; the page uses a few alignment lines, not many near misses |
| no false alignment | unrelated values do not share an axis that invites comparing them |
| importance follows area and contrast | the higher an item stands in `priority`, the more area, weight, or contrast it gets in its group; only true peers look identical |
| one focal point | each screen state has one strongest element, serving the first priority |
| true enclosure | every surface marks a real group; a surface inside a surface has its own role, such as a plot area in a data module |
| symmetry where balanced | centered axes and mirrored halves only where the content is balanced (a ceremonial or single-message screen, true peers); elsewhere placement follows reading order and weight |
| rank without color | with color removed, size, weight, and position still show the order |

The levers are size, weight, color and contrast, and position with space; motion and ornament come
after them. When the cause of a flat or noisy hierarchy is unclear, change one lever at a time on the
same content. Visual weight adds up across channels (`color.md`); judge the densest real view.

## Grids, lines, and margins

### Grid kinds

| Grid | What it is | Fits |
|---|---|---|
| manuscript | one text block with margins, optionally a side rail for notes | long reading, documentation, a single-message screen |
| column | repeated columns and gutters that content spans | pages mixing text, media, and controls; form plus context rail |
| modular | columns crossed by rows into modules; items take one or more | galleries, catalogs, monitoring screens |
| baseline | a vertical unit recurring lines sit on | editorial and print-like pages; optional in interfaces |

- Twelve columns wide, eight medium, and four compact is a widely used convention (twelve divides by
  two, three, four, and six), not a requirement; minimum useful widths set the count.
- A maximum page width around 1,200 to 1,440 CSS px is a common web band. Reading columns are far
  narrower (measure: `type.md`); tables and media may span wider, within the shell.
- Span follows priority and minimum useful width. Equal tracks do not mean equal cells, and a module
  that exists only to complete the shape is filler. Data tables take intrinsic column widths inside
  their own scroll region.
- Take the grid from a world material when one has it: a log sheet's ruled columns, a ledger's rows, a
  specimen card's fields. The example plan's lever "log-sheet grid" is this move.
- A baseline grid never justifies clipping or fixed heights; wrapped headings, larger text,
  translations, and error messages push it.
- Size by content (`minmax()`, `fit-content`) before any fixed height, and use logical properties
  (`margin-inline`, `padding-block`) so right-to-left and vertical writing adapt.

### Margins, safe areas, and hit areas

- Text, controls, and cards keep an inset from the viewport and from scroller edges; about 16 CSS px at
  phone width is common practice. Media meant to bleed may run to the edge.
- Measure outer margins from the safe area (`env(safe-area-inset-*)` on the web, non-zero once the page
  opts in with `viewport-fit=cover`; the platform's layout guides natively); each edge's inset is independent and can change at run time. Backgrounds may bleed;
  text and fixed controls stay inside, and a scroller's first and last items can rest wholly inside.
- The grid aligns visible edges; target size belongs to the hit area. An icon aligned to a column can sit
  in a larger hit area, and aligned targets whose hit areas collide fail.

### Lines

A line is a layout claim. Give each one a role.

| Role | Use for | Check |
|---|---|---|
| rule or divider | a real boundary that space alone leaves unclear | does it repeat what the space already says? |
| frame or border | a region, a control, an independent object | does it enclose every paragraph or item? |
| connector | a true path, dependency, or sequence | are the endpoints and the direction clear? |
| emphasis or annotation | pointing at one span | could it be mistaken for a control or a data line? |
| focus or state | keyboard focus, selection | does it survive clipping ancestors and scrolling? |

Grouping cues (proximity, alignment, similarity, common region, connection) cooperate or compete:
equal gaps hide different relations, a narrow width changes which neighbor is nearest, and nested
regions imply more levels of ownership than exist. Borders that identify a control or state meet the
non-text contrast in `color.md`; decorative dividers need not.

Corner radius and elevation are surface decisions (`tokens.shape`, `tokens.surface`), made once the
relation is settled.

## Responsive behavior

Responsive layout is not the wide composition shrunk: at each width, every region keeps its task and
meaning while its order, collapse, and density change. Start from content order and intrinsic layout.

### Transformations

For each region, choose one per width:

- reflows in place;
- stacks, in a named order;
- changes presentation and keeps its function (a side panel becomes a sheet, a table becomes a labeled
  record view);
- scrolls inside its own labeled region, for content that needs two dimensions or a sequential row;
- moves to a secondary view or disclosure, with a visible route to it;
- is removed, only when it was a decorative duplicate.

Density can move either way per width: one record at a time on a phone, more context in a wide window.
Navigation transformations belong to the `lps-ux` skill.

### Where a width change goes

Render the minimum and maximum real content, then narrow and widen the container until hierarchy,
measure, target spacing, or the task breaks. Put the change at that boundary as a named state (a few
states beat many pixel patches), and check just below, at, and just above it, with 200% text and the
longest locale. Device names are test categories, not layout inputs; the available window changes
while a page is open.

### Viewport or container

- Viewport queries decide the page shell: the navigation model, outer margins, the collapse of the main
  columns.
- Container queries (`container-type: inline-size` with `@container`) decide a component placed in
  regions of different widths, such as a piece cell in the gallery and in a narrow side rail.
- Intrinsic primitives come before either. Do not make every element a query container, and name
  containers when several contexts nest.

### Intrinsic primitives

These adapt to the space they get without a breakpoint. Build regions from them, and write in
`responsive` which one a region uses and with which parameters.

| Primitive | Arranges | Parameters | Changes when |
|---|---|---|---|
| stack | children in one column, one space step apart | the step; optionally one child pushed to the end | never; any region can fall back to it |
| cluster | a wrapping row of tags, actions, or metadata | gap, alignment along the row | an item no longer fits; it wraps, one item at a time |
| sidebar | a set-width side part beside a main part that takes the rest | side width, the main part's minimum share, gap | the main part would fall below its share; both stack |
| switcher | equal items in one row, or all in one column | switch width of the container, maximum item count, gap | the container narrows past the switch width or items exceed the count; all switch at once, no orphan row |
| center | a centered column of limited inline size | maximum inline size (often a measure), side gutters | never; the gutters keep content off the edges |
| cover | a minimum-height region with one centered principal element | minimum block size, the principal element, padding | content outgrows the minimum; the region grows and never clips |
| grid | as many equal tracks as fit | minimum track width, gap | the container resizes; tracks are added or removed. Cap the minimum, `repeat(auto-fit, minmax(min(20rem, 100%), 1fr))`, so one track never overflows |
| frame | media cropped to an aspect ratio | ratio, focal point | the ratio may change per width when a crop would lose the subject |
| reel | a row scrolling inside itself | item width, gap, snap points, a partly visible next item | never; it stays its own scroll region, keyboard-reachable and visibly scrollable |

### Requirements

- Content reflows at 320 CSS px width without scrolling in two directions, except regions whose content
  needs two dimensions (data tables, maps, diagrams); those scroll inside themselves while their
  headings, filters, labels, and actions reflow.
- Content, actions, labels, errors, prices, and legal text are never lost at any width.
- Text resizes to 200% and survives text-spacing overrides (`type.md`): no fixed heights
  around text, and `min-inline-size: 0` on flexible children so they shrink instead of overflowing. Zoom
  stays enabled.
- Focus order and reading order match the visual order at every width.
- Pointer targets are at least 24 by 24 CSS px. A smaller target passes when a 24 CSS px circle
  centered on it touches no other target and no other small target's circle, or when it sits inside
  a sentence. The criterion also excepts an equivalent control elsewhere on the page, a target the
  browser controls, and a size that is essential. Touch-first surfaces follow the platform's
  recommended control size, which is larger.
- No text is covered by decoration, and sticky or fixed regions never hide the focused element.
- Full-height shells use `min-block-size: 100dvh` and allow overflow, since browser bars, the on-screen
  keyboard, and zoom change the usable height.
- One document serves every width; duplicated compact and wide markup doubles the focusable controls.

### Korean, Japanese, and Chinese in layout

- Text length changes by locale in both directions; lay out with the longest real string in each
  locale, and let components grow rather than truncate.
- Korean text blocks keep `word-break: keep-all` with `overflow-wrap: anywhere` (`type.md`), so lines
  break between words and a word wider than its column breaks only as an emergency. Size narrow
  columns, cells, and buttons for the longest Korean word, or change the layout (a switcher stacks, a
  cluster wraps).
- Long unbroken strings (codes, identifiers, URLs, long Latin names inside CJK text) get
  `overflow-wrap: anywhere` and a column that can grow; check them at 320.
- Mixed-script lines change line boxes and wrapped heights, so never lock a height to one locale's line
  count.
- Measure and leading are set per locale in `type.md`. Vertical writing, when a world
  material calls for it, swaps the inline and block axes, and logical properties follow.

## Density and data-heavy screens

### Density

Density is how much information and interaction a view holds; on dense screens the aim is fewer steps
per decision, not smaller type. `direction.dials.density` sets the starting point. Decide density per
screen and often per region, so an overview can be moderate while its full comparison is compact, from
task frequency, expertise, consequence, data shape, and input. It never trades legible text, target
size, visible focus, or the difference between spacing levels; compact views gain more from alignment,
shorter repeated labels, prioritized columns, and disclosure than from smaller text. A user density
preference (comfortable, compact) earns its place on screens used for repeated daily work, not on a
checkout.

### Choose the collection

| Need | Structure | Avoid |
|---|---|---|
| read-only comparison across records | semantic table | a card grid that repeats every label |
| editing cells and moving between them by keyboard | an interactive grid with managed focus | a plain table dressed as a spreadsheet |
| records with few shared fields, read in turn | list | a table full of empty columns |
| objects identified by their image | gallery | thumbnails squeezed into table rows |
| one object with recurring metadata | list plus detail | expanding every row into a second screen |
| repeated high-level measures | monitoring modules | a card for every number |

Rows and tables win when fields repeat, comparison across records is central, or volume is high; cards
win when each member is a rich object browsed on its own.

### Columns, rows, and alignment

- The identifying field comes first and stays visible when the table scrolls sideways.
- Numbers align by place value: end-aligned, on the decimal point when they have decimals, in tabular
  figures (`type.md`). Text categories align to the start edge, and each header aligns with
  its column's content.
- A shared unit goes in the header; a unit that varies goes beside each value. Dates, currencies,
  percentages, and missing values keep one format each, and a dash never means zero, unavailable, and
  not applicable at once.
- Status is a finite vocabulary written as text, with its color as a second cue.
- Wrap meaningful text where rows may vary in height. Truncate only when the full value has a route that
  keyboard and touch can reach; prices, conditions, errors, and status are never truncated.
- Row height tiers: about 48 px comfortable and 36 to 40 px compact are common web values; go lower only
  with legibility and targets intact. In every tier the gap between groups stays larger than the gap
  between rows.

### Sticky context

- Keep fixed what a reader needs to interpret a row while scrolling: column headers, the identifying
  column, the active filter summary with the result count, the selection count with its actions.
- A `position: sticky` header helps only when it does not cover the focused row and still works with
  text at 200%; a fixed first column needs a visible edge.
- A header inside a region that scrolls sideways sticks only within that region; to keep it in view on a
  long table, give the region a bounded height so it scrolls in both directions.
- A bar that appears on selection reserves its space or overlays without covering headers, focus, or
  content; the table never jumps under the pointer.

### Scanning and comparison

- Keep compared fields on shared alignment lines at every density and width. When space shrinks, add
  headers, a restrained rule, or a row tint rather than relying on memory.
- At compact widths, choose by task: a contained horizontal scroll with the identifying column fixed
  when columns must stay aligned; priority columns plus a detail view when one record at a time works;
  labeled record cards only when comparing across rows is not the task.
- Each measure shown has a label, unit, time scope, and comparison; no number is invented to fill a
  module.
- Which chart answers a question is a data visualization choice outside this step; here, decide only a
  chart's place, span, and rank.
- Filters, saved views, selection scope, bulk-action states, and paging belong to the `lps-ux` skill.

## Check after rendering

Read the render extract against the plan: the checker owns the bounds, and you check that what rendered
is what you planned. Comparing widths needs a capture at each width.

| Measured | Check against the plan |
|---|---|
| proximity order in `gaps` | `inside_group`, `between_groups`, and `between_sections` rise in that order at every width and sit near the steps you gave siblings, groups, and sections in `tokens.space` |
| heading proximity | each heading sits closer to what follows than to what precedes it |
| `sibling_groups` similarity | siblings that `priority` ranks differently come out distinguishable; only the peers named in `relationships` look alike |
| `card_nesting_max` | each level past the first is a surface whose role `relationships` names |
| `symmetry` | high only on screens whose content is balanced |
| `density` | one page-wide ratio per capture: compare it across widths against `responsive`; a wide capture much emptier than the compact one means the layout stretched instead of adding context |
| `signature_found` | true with `verified` evidence: the signature element carries `data-lapis-signature` |
| `sections` and `section_sequence` | the rendered sections follow `layout.sections` in order. The render names only its own kinds, so a section with your own id (`signature`, `list`) shows as `other` or as the nearest kind: a gallery of priced cards with buttons can read as `pricing`. Treat a kind you did not plan as a question about that section's structure, never as a label to work around |
| structure between widths | regions reorder, collapse, and change density as `responsive` says, not only scale |
| the 320 capture | no page-level horizontal scroll, no clipped or covered text, every region and action still present |

When a measurement disagrees with the plan, change the implementation, or change the plan and say why;
never adjust the plan to fit an accident. Independent review belongs to `ultramarine`.
