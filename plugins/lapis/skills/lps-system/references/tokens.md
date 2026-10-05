# Tokens

## Sections

Read the section for the token layer being written, by heading; the rest are other layers.

- From authorized assets to roles: starting a provisional direction from one authoritative asset
- The token graph: layers of tokens and which may point at which
- Names: naming by purpose and state, never by appearance or position
- Color: from roles to ramps and aliases: ramps, semantic aliases, and per-theme mappings from `tokens.color.roles`
- Masters and renditions: the OKLCH master and the values derived from it for each target
- Type tokens: one composite token per role, stacks, sizes, and fallbacks
- Space, radius, surfaces, and icons: space primitives and semantic tokens, shape, surfaces, icon sizes
- Motion tokens: durations and easings by purpose
- The interchange file: exporting in the design-tokens interchange format
- DESIGN.md entries: what `DESIGN.md` records about tokens, roles, and reasons
- Check before handing over: the pairs, states, and themes to measure

This file backs the skill's token layers, color, type, space, shape and surfaces, motion, and
`DESIGN.md` sections. It turns the plan's `tokens` fields (`color`, `type`, `space`, `shape`,
`surface`, `icons`, `motion`) into a token graph, token files, and `DESIGN.md` entries, and reads
`context.design`, `proposed_design_changes`, and `defaults` along the way. Field shapes are in
`../shared/plan/schema.yaml`, value source classes in `../shared/vocab/color.yaml`. How one graph
serves light, dark, and high-contrast themes is in `theming.md`.

The `lapis` skill decides the color roles, their values, and the rules behind them, and the type
roles, families, and scale; this file turns those decisions into tokens. When a decision is
missing, send it back to `lapis` or record a reversible assumption in `claims.proposed`; never settle
it inside a token file.

For document dialects, supplied tool exports, generated specifications or implementation handoff,
read `interop.md`; it separates acquired evidence from format interpretation and runtime proof.

```yaml
tokens:
  color:
    roles:
      - { name: paper, role: field, oklch: [0.97, 0.01, 85] }
      - { name: ink, role: foreground, oklch: [0.25, 0.01, 60] }
      - { name: reserve, role: interaction, oklch: [0.45, 0.09, 250], source_class: authored }
      - { name: kiln-night, role: field, oklch: [0.22, 0.01, 60], theme: dark }
    themes: [light, dark]
  type: { scale: { base_px: 16, ratio: 1.25 } }
  space: { base_px: 4, scale: [4, 8, 12, 16, 24, 32, 48, 64, 96] }
  shape: { radius: { scale: [0, 4, 8], by_role: { control: 4, card: 8, image: 0 } } }
```

The examples continue the example plan's pottery shop, `kiln-shop-landing`: twenty-four pieces
from one firing, reserved mostly on phones, Korean copy. Its warm log-sheet frame was compared
with a cool kiln-shelf frame at matched L/C and unchanged reserve roles; these values are that
case's, not a starter palette. Keep the candidate mappings and inspected captures in its palette
`explorations` when writing token files; ramp/pair rules remain prose, not comparison evidence.

## From authorized assets to roles

One authoritative asset can start a reversible provisional direction; it does not prove a
complete system. Reuse the supplied-asset grammar in `lapis`'s visual-assets reference, name
sample limits in `claims.proposed`, and protect the artwork. Missing mark clear-space, size,
recolor, or lockup rules remain owner questions, not numbers borrowed from another brand.

To promote an asset color, keep the observed source and its authority separate from the proposed
UI role. A logo hue may inform an identity or action family without recoloring the logo itself.
Derive only the roles the task needs, then test their resolved pairs, states, and themes; status
and data meanings must remain distinct. Promote repeated decisions that survive the real slice,
keep local exceptions local, and freeze only the disputed dependency rather than all system work.

## The token graph

A token set is a directed graph, not a bag of variables. Every edge points from a more specific
decision to a more reusable one:

```text
component state   -> semantic role                    -> primitive  -> output value
button.bg.pressed -> color.interaction.action-pressed -> reserve.36 -> #173F65 / oklch(0.36 0.08 250)
```

- References run downward only. A primitive never points at a semantic token, and no chain loops;
  check for cycles before every export.
- Equal values do not merge meanings. A focus ring and an informational stroke can share a value
  today and keep separate nodes, so either can change alone.
- A token earns its place when a value is reused, changes per theme, is audited, or must change
  together with others. Anything else is a local value, and off a scale it carries a written optical
  reason.
- Component tokens alias semantic tokens or do not exist. A component layer that copies literals has
  the cost of tokens and none of the benefit.

| Worth a component token | Not worth one |
|---|---|
| `button.primary.bg.default -> color.interaction.action` | `button.padding.left`, `button.padding.right` |
| `button.primary.bg.pressed -> color.interaction.action-pressed` | `button.icon.margin.right` |
| `button.primary.fg -> color.interaction.on-action` | one token per CSS property of a component |

Before changing a shared step, list what depends on it: the semantic tokens that alias it in each
theme, the component states that read them, the generated files that change, and the pairs to
measure again. When only one meaning needs the change, remap that semantic token to another step
instead of moving the step under every other meaning.

## Names

Name by purpose and state, never by appearance or position: `blue-button`, `left-panel-gray`, and
`card-shadow-2` leak the current look, while `color.interaction.action` survives a new palette.

```text
<category>.<role>.<name>[-<variant>][-<state>]

color.field.canvas        color.foreground.muted        color.interaction.action-pressed
color.field.raised        color.interaction.on-action   color.status.error-container
type.body                 space.stack.group             radius.control
motion.duration.feedback  elevation.1                   icon.size.control
```

- Color tokens use the plan's roles `field`, `foreground`, `identity`, `interaction`, `status`, and
  `data`; `content` entries never become interface tokens. An established project vocabulary wins;
  map to it rather than renaming a working system.
- Name primitive steps so an insertion renames nothing: the step's target lightness times 100
  (`neutral.97`, `reserve.45`), or sparse numbers with room between.
- Keep the conceptual path apart from each serializer's spelling, with a reversible name table:
  `color.field.canvas` is `--color-field-canvas` in CSS and the nested groups `color`, `field`,
  `canvas` in the interchange file. When two paths spell the same in one target, as
  `color.action.primary` and `color-action.primary` do in CSS, stop and ask; never let the later one
  win silently.

## Color: from roles to ramps and aliases

Start from `tokens.color.roles`: each entry is a role with an OKLCH value or a `DESIGN.md`
reference, an optional `theme`, and a `source_class`. The rules `lapis` hands over with them
(chroma tapering, hue direction along a ramp, which scale reverses in which theme, which pairs meet
which minimum) arrive as prose in `claims.proposed` or `DESIGN.md`; the plan has no field for them.

1. **Inventory by theme.** For each role and each theme in `tokens.color.themes`, note whether it
   has a value, only a rule, or nothing. An entry without `theme` applies to every theme; when its
   value cannot work in another listed theme, as the example's `paper` and `ink` cannot in dark, the
   decision is unfinished: set `theme: light` on it, add a dark entry with the same `name` or map it
   to an existing dark entry of the same role (such as `kiln-night` for `paper`), and say which. Values of class `brand-approved`, `provider`, or `measured` are used exactly as given.
   `content` entries describe what the interface lives beside and never become interface tokens.
2. **Build a ramp per family that needs steps**: the neutrals, the action family, each status the
   product has. The plan's values are anchor steps and stay exact. Fix each step's lightness first,
   taper chroma where the gamut narrows, and move hue in one direction only. Judge the rendered
   steps, not the numbers.
3. **Map semantic tokens to steps per theme.** Components read only semantic tokens. Dark is its own
   mapping, with surfaces that get lighter as they rise.
4. **Write the rendered values back to the plan.** Every semantic color that renders gets a role
   entry, with its own entry for each theme where it differs. The render layer of
   `system.literal-color` compares every rendered text, background, and border color with the
   `oklch` values of the plan's roles and reports a color close to none of them, so a surface tier
   missing from the plan shows up as a literal. Hover, focus, and pressed colors are not compared, so
   check those pairs yourself.
5. **Generate renditions and check the pairs** (the next and last sections).

The action family shows why chroma tapers. The plan fixes `reserve` at `[0.45, 0.09, 250]`. Held at
chroma 0.09, the ramp leaves sRGB above lightness 0.83 and below 0.32, because blues reach their
highest chroma at middle lightness. Tapered, every step fits:

| Step | OKLCH | sRGB rendition | Used for |
|---|---|---|---|
| `reserve.97` | `[0.97, 0.012, 250]` | `#EFF6FD` | selected-row tint, light, beside a non-color selection mark |
| `reserve.80` | `[0.80, 0.07, 250]` | `#9CC2EA` | action pressed, dark |
| `reserve.72` | `[0.72, 0.08, 250]` | `#7EA9D5` | action, dark |
| `reserve.45` | `[0.45, 0.09, 250]` | `#2A5885` | action, light (the plan's anchor) |
| `reserve.36` | `[0.36, 0.08, 250]` | `#173F65` | action pressed, light |

The neutrals run from `paper` to `kiln-night` with a small steady chroma, hue moving one way from 85
at the light end to 60 at `ink`, so both anchors stay exact:

| Semantic token | Plan role entry | Light | Dark | Pair measured, light / dark |
|---|---|---|---|---|
| `color.field.canvas` | `paper` / `kiln-night` | `neutral.97` | `neutral.22` | |
| `color.field.raised` | `raised` (field), new | `neutral.97` and a hairline | `neutral.27` | |
| `color.field.hairline` | `hairline` (field), new | `neutral.86` | `neutral.35` | decorative, no minimum |
| `color.foreground.primary` | `ink` | `neutral.25` | `neutral.93` | on canvas 14.6:1 / 14.1:1 |
| `color.foreground.muted` | `muted` (foreground), new | `neutral.50` | `neutral.70` | on canvas 5.5:1 / 6.4:1 |
| `color.interaction.action` | `reserve` | `reserve.45` | `reserve.72` | fill on canvas 6.8:1 / on raised 6.1:1 |
| `color.interaction.on-action` | `on-reserve` (interaction), new | `neutral.97` | `neutral.22` | on action 6.8:1 / 7.0:1 |

Elevation reads differently per theme: the light theme keeps piece cards on the page's paper with a
hairline, as `tokens.surface.borders` asks; the dark theme lifts them a step. Pressed goes darker in
light and lighter in dark here because the interaction language says so, not by habit.

## Masters and renditions

The OKLCH value is the master; everything a target consumes is derived from it, one way:

| Layer | Example | Authority |
|---|---|---|
| approved source | a brand value supplied in a named space | the brand record; never regenerated |
| master | `reserve.45 = oklch(0.45 0.09 250)` with its role and reason | the token source |
| semantic alias | `color.interaction.action -> reserve.45` (light) | the token source, per theme |
| target rendition | sRGB hex, a wide-gamut CSS value, native platform values | generated, reviewed, pinned |
| captured sample | a screenshot, a printed proof | evidence for that instance only |

- Never replace a master with its hex rendition, and never rebuild one from a hex export, a
  screenshot, or a photo sample: delivery's rounding and gamut decisions would become authoring data.
- Never hand-edit a generated file. A target that needs art direction gets a named sibling rendition
  with its target and approval.
- Record each transform: source, destination, method (mapped or clipped; clipping can shift hue and
  merge neighboring steps), tool and version, reviewer. Pin reviewed outputs so a converter upgrade
  cannot change production silently.
- For a profile-based rendition, also record the source/destination profiles, reproduction goal,
  rendering intent, and black-point policy. Physical output conditions belong to `lapis`'s color reference.
- Keep precision until final serialization, and compare adjacent steps after conversion.

```text
tokens/color.tokens.json         masters, in OKLCH or the approved source space
tokens/roles.light.tokens.json   semantic aliases for the light theme, aliases only
tokens/roles.dark.tokens.json    semantic aliases for the dark theme (one file per theme, see theming.md)
build/tokens.css                 generated renditions and custom properties
```

**Fallback first.** Custom properties accept any token stream, so an unsupported color function
replaces the fallback declared before it and fails only where it is read: the property that reads it
takes its inherited or initial value, not the fallback. Gate the master rendition:

```css
:root {
  --color-field-canvas: #F8F5EE;          /* derived sRGB rendition of neutral.97 */
  --color-interaction-action: #2A5885;    /* derived sRGB rendition of reserve.45 */
}
@supports (color: oklch(0 0 0)) {
  :root {
    --color-field-canvas: oklch(0.97 0.01 85);
    --color-interaction-action: oklch(0.45 0.09 250);
  }
}
```

Add a wide-gamut rendition only when it differs materially and someone approved it, gated by
`@supports` and `@media (color-gamut: p3)`. The pottery page needs none: its interface colors sit
well inside sRGB, and the saturated glazes are content in photographs.

When edited hex was converted back into masters, recover the last approved masters and transform
record, treat the edits as proposed sRGB art direction, decide whether they change the master or stay
a sibling rendition, and regenerate every target. If no master survives, label the hex as the
observed source of a new decision; do not invent the lost precision.

## Type tokens

Start from `tokens.type` and the fonts lock. Each role becomes one composite token: a family stack,
a size, a unitless line height, a weight, and tracking.

- **Sizes** are `base_px` times `ratio` to a whole power, in `rem` so the reader's text size applies.
  Round once, at output: with base 16 and ratio 1.25 the steps above body are 1.25rem, 1.563rem, and
  1.953rem.
- **Line height** is unitless and set per role and script; `lapis` gives the starting values.
- **Weights** are only those the role lists in `tokens.type.roles`, each a real face or variable
  instance; any other weight renders as the nearest loaded face, or as synthesized bold when no bold
  face is loaded.
- **Tracking** on Hangul body text is the face's default. A negative value there is the
  `global-habit-values` card (`type.ko.body-negative-tracking`).

| Token | Size | Line height | Weight | Stack |
|---|---|---|---|---|
| `type.heading.page` | 1.953rem | 1.3 | 700 | heading |
| `type.heading.section` | 1.563rem | 1.35 | 700 | heading |
| `type.body` | 1rem | 1.7 | 400; 600 for emphasis | body |
| `type.body.figures` | 1rem | 1.7 | 400 | body, with `font-variant-numeric: tabular-nums lining-nums` |

**Per locale.** Treat locale as a small mode for the values that differ by script (stack, line
height, tracking): reassign them under `:lang()` and keep one role name.

```css
:root, :lang(en) { --type-body-leading: 1.5; }
:lang(ko) {
  --type-body-leading: 1.7;
  word-break: keep-all;
  overflow-wrap: anywhere;
}
```

`keep-all` with `overflow-wrap: anywhere` is a base style of Korean text, not a token value; without
it, the rule `type.ko.keep-all-missing` applies. Scope it to Korean, since applied globally it removes
the ordinary break points of Japanese and Chinese. On the pottery page everything inherits `ko`, so
Latin clay names in Korean sentences stay whole and a long one still breaks as an emergency. A
mixed-script paragraph takes the leading of the script with the fuller glyphs.

**Stacks.** Write each stack as the role's contract family, the fallbacks recorded with
`lazuli lock --fallback`, then a generic family. The source layer of `system.font-outside-contract`
reads font custom properties and `font-family` declarations, and reports a first family outside the
contract and a fallback that is neither a contract family, a locked fallback, nor a system font. A
fallback face you declare in `@font-face` with metric overrides (`size-adjust`, `ascent-override`,
`descent-override`, so the swap does not reflow) has its own family name; lock that name with
`--fallback` too.

**Fluid sizes.** A `clamp()` size passes through values between steps. The render layer of
`system.off-scale-value` compares each rendered text size with the plan's scale and reports one that
falls between steps at a captured width. Where a role must change size with width, give it another
step per width or container state. A `defaults` keep entry for the rule would waive every off-scale
value it finds, spacing and radius included, so do not use one to let interpolation through.

## Space, radius, surfaces, and icons

**Space.** Primitives from `tokens.space.scale`, output in `rem`. Semantic tokens name the use:
`space.inset.*` inside a component, `space.inline.*` along a line, `space.stack.*` between siblings
and groups, `space.stack.section` between sections; which step serves which relation is decided in the
plan's layout. A density mode remaps a few semantic tokens (row height, control padding, group and
section gaps), never the scale, target size, or focus. The source layer of `system.off-scale-value`
judges literal padding, margin, gap, and font sizes against `tokens.space.scale` (or multiples of
`base_px`) and the type scale; a value read through `var()` is not judged.

**Radius.** One token per role in `tokens.shape.radius.by_role`: `radius.control` 4 px,
`radius.card` 8 px, `radius.image` 0, with the reason from `tokens.shape.rule` in `DESIGN.md`. Define
each as a custom property with `radius` in its name: the source check builds its radius scale from
those definitions, and no check reads `tokens.shape` yet. One large radius on every container is the
`global-habit-values` card.

Describe the painted contour: silhouette, open or enclosed edge, stroke or fill, symmetry, void,
and join. A 50% radius on a wide rectangle makes an ellipse; oversized circular radii make
semicircular ends with a straight middle. For adjacent circular corners with equal positive insets
smaller than the outer radius, inner radius equal to outer radius minus inset shares a center.
Include the border in that inset. Do not generalize to unequal offsets or continuous curves, or
create off-scale values from it. Compare apparent gaps
at actual size, long labels, and narrow widths. Exercise focus separately from media clipping.
Smoothness is a construction choice, not a quality score.

**Surfaces.** Each level in `tokens.surface.elevation` gets a token per theme for its surface color,
border, and shadow if any. Write shadows as structured layers (color, offsets, blur, spread);
flattened into one string they lose that, so list it as a loss in the conversion report. Each treatment in
`tokens.surface.treatments` becomes a token named by its job, such as `surface.treatment.paper-grain`,
used only in the firing log. A treatment a card names (`ornamental-surface`, `hard-edge`) is also
decided in `defaults`.

Name each separation's job before its values; layout's **Lines** owns the structural choice.
Compare treatments beside actual content in each theme. Decorative dividers have no universal
contrast minimum; boundaries needed to identify a control or state follow the color requirement.

**Icons.** Sizes and stroke from `tokens.icons`, named by use: `icon.size.inline` 16 beside text,
`icon.size.control` 24 in controls, `icon.stroke` 1.5. Icons take the text color, so themes recolor
them through the foreground tokens. Stand-in glyphs and drawn paths beside a family are the
`improvised-icons` card.

## Motion tokens

Write durations and easings by purpose from `tokens.motion.principles`: `motion.duration.feedback`,
`motion.duration.transition`, `motion.duration.emphasis`, `motion.easing.enter`,
`motion.easing.exit`. Keep movement apart from time with distance tokens, so the reduced-motion
branch sets movement to zero and keeps a short fade:

```css
@media (prefers-reduced-motion: reduce) {
  :root { --motion-distance-enter: 0px; --motion-duration-emphasis: 0ms; }
}
```

Motion without that branch is the rule `motion.reduced-motion-missing`; an overshooting easing on
every transition is the `global-habit-values` card. On the pottery page, with its low motion dial,
feedback on the reserve control and the sheet's entry are enough.

## The interchange file

Export in the design-tokens interchange format when the project uses one. Its rules decide what the
file can say:

- A token is an object with `$value`; a group is an object without one; nothing is both. Tokens may
  carry `$type`, `$description`, `$extensions`, and `$deprecated`; groups also `$extends`.
- Names are case-sensitive, never start with `$`, and never contain `.`, `{`, or `}`; a conceptual
  path becomes nested groups, never one dotted name.
- The type comes from the token's `$type`, then the type of the token it aliases, then the nearest
  group's `$type`. Never infer it from a value; when nothing says what a number is, ask.
- Aliases in braces (`{color.neutral.97}`) point at a whole token; a `$ref` path such as
  `#/color/neutral/97/$value/components/0` can reach part of a value. Keep aliases until a consumer
  needs resolved values.
- Tool-specific data goes in `$extensions` under a reverse-domain key its producer owns; unknown
  extension data is kept.

| `$type` | Value | Note |
|---|---|---|
| `color` | `{ colorSpace, components, alpha?, hex? }` | name the space (`oklch` for masters); `hex` is an optional, derived six-digit fallback |
| `dimension` | `{ value, unit }` | `px` or `rem`, zero included; never `em` |
| `number` | a number | unitless line height, ratios, counts |
| `fontFamily` | a string or an ordered list | the stack |
| `fontWeight` | 1 to 1000, or a named weight | |
| `duration` | `{ value, unit }` | `ms` or `s` |
| `cubicBezier` | `[x1, y1, x2, y2]` | x values from 0 to 1 |

Composites (`typography`, `shadow`, `border`, `transition`, `gradient`, `strokeStyle`) are structured
objects, never CSS shorthand. The typography composite holds family, size, weight, letter spacing, and
line height; line breaking, font features, variation settings, and per-locale stacks have no field, so
they stay in the style layer and `DESIGN.md` and are listed as losses. A gradient token holds stops
only: name its job and keep its geometry with the component. The format has no theme construct;
`theming.md` covers exporting themes. Report each conversion per token (preserved, renamed with its
mapping, split, or lost, and the consequence); "converted with warnings" is not a report.

## DESIGN.md entries

`DESIGN.md` holds the selected tokens, the roles, and the reasons, and names the token source files as
the authority for full values.

- Write colors as CSS color strings; `oklch()` is valid, so never force masters to hex for a tool that
  reads only hex.
- Beside each color, give its source class from the color vocabulary (`authored`, `brand-approved`,
  and so on), its source space, the generated fallback files and gamut policy, whether it is fixed and
  never regenerated, and the transform owner with the review date.
- Give each token a stable name a plan can cite, as in `ref: DESIGN.md#colors.<name>`.
- For each family, name the authority and how its outputs are regenerated. A component library's
  starter theme kept with only the primary swapped is the `starter-surface` card, not a system.

The plan and `DESIGN.md` meet in `plan check`. While `context.design` names a `DESIGN.md`, a color role
whose `ref` anchor is not in that file is `contract.unknown-ref`, and a role with its own value is
`contract.value-outside-contract` unless a `proposed_design_changes` entry names it; both gate. So leave
`context.design` as it was when the task started: a `DESIGN.md` this task writes is the contract of the
next task, whose plan cites it with `ref`. A new token in an existing `DESIGN.md` goes to
`proposed_design_changes`.

A design-tool importer is not the release authority by default. Per family, find out who owns the
decision, whether the importer merges or replaces, and whether repository-only entries share an
overwritten file; record the direction. A one-way importer is not a two-way sync.

An imported snapshot records only what its source can express. Absent or empty mode data means
unknown, not a verified single theme; a bare number does not establish spacing, radius, or time.
Preserve source names, aliases, and producer-owned unknown data where the destination permits,
and report unsupported data as losses. Add no invented snapshot keys or claim rendered contrast,
direction fit, or state completeness from a normalized token list.

To replace scattered literals: inventory values and callers, cluster by role rather than exact value,
define only the primitives those roles need and the semantic tokens their uses show, migrate one
component family first to expose mapping errors, then finish every agreed family, and remove old
aliases only after every caller has moved. Never keep two public naming systems for good.

## Check before handing over

- **Pairs.** Take pairs from the components, not from token names: each foreground on each background
  it can land on, each control boundary and focus ring against its neighbors, in every theme and state.
  Resolve both colors in the target rendition, composite transparency on every backdrop it can cover,
  compute contrast on that pair, and look at the render. An OKLCH lightness gap predicts no ratio; the
  minimums are in `lapis`.
- **Graph.** No cycles, no upward references, every semantic token resolves in every theme, every unit
  is legal in every destination.
- **Plan.** `lapis-design plan check .lapis/plans/<task>.yaml` after writing values back.
- **Code.** The `ultramarine` skill's lint reads the files as described above. Keep literal colors in
  token definitions: custom properties, preprocessor variables, a framework theme block, or files the
  source check treats as token files (named like `tokens`, `theme`, `palette`, `colors`, or
  `variables`, or inside a `tokens/` or `theme/` folder). The source layer of `system.literal-color`
  skips those and reports literals elsewhere, inline styles and SVG `fill` and `stroke` attributes
  included. A component that sidesteps the adopted primitive or theme API is
  `system.bypassed-primitive`.

Report which pairs, states, and themes were measured and how; a passing pair proves only that pair.
