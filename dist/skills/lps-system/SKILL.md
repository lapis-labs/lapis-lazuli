---
name: lps-system
description: Turns a plan's decisions into a design system - color ramps and semantic tokens in OKLCH, type scale, spacing, radius, elevation and surfaces, icons, motion, themes - and writes or converts DESIGN.md and token files. Use for tokens, theming, dark mode, design-system setup, DESIGN.md, and "our components drift".
license: MIT AND CC-BY-4.0
metadata:
  plugin: lapis
  version: 0.2.0
---

# lps-system

lps-system makes the plan's decisions repeatable. It turns `tokens` in the plan into token files
and a `DESIGN.md` the project can keep, so every component draws from the same values and later
work has a contract to follow.

## Order of authority

1. Requirements: contrast, focus visibility, reduced motion, text resizing. A token set that fails
   them is not finished.
2. The project's existing contract: `DESIGN.md` and its tokens. Changing it needs a
   `proposed_design_changes` entry the user approves; never rewrite it silently.
3. Platform and framework conventions: the platform's text styles, the framework's theme API.
4. Named defaults (the cards).

## At the start

1. Read the plan's `tokens`, `direction`, and `defaults`, and `DESIGN.md` if it exists. Identify its
   dialect and record it in the plan's `context.design.dialect`, using the values the plan schema
   lists; `unknown` when none fits.
2. Find the adopted primitives: component library, theme API, CSS custom properties, native style
   objects. New tokens plug into them; nothing bypasses them.

For source-family adoption, system scope, or component APIs, read `references/system-contracts.md`;
for a supplied design document, tool export, or generated specification, `references/interop.md`.

## Token layers

- **Primitives** hold values: color ramp steps, type sizes, space steps, radii, durations. Nothing
  in a component reads a primitive directly.
- **Semantic tokens** name a role: `color.field.canvas`, `color.interaction.action`,
  `type.body`, `space.stack.section`, `radius.control`. Components read these.
- **Component tokens** only where a component needs a value no role gives, and they alias
  semantic tokens.
- One value per role and theme. A value that repeats with a real role becomes a token; a one-off
  value needs a written optical reason.

For names, the token graph, turning each `tokens` field into ramps, aliases, and token files, the
interchange format, `DESIGN.md` entries, and what the checks read, read `references/tokens.md`.

References open with a `## Sections` index; read the section for the token layer at hand, found by its heading, not the whole file.

## Color

Start from `tokens.color` in the plan: the OKLCH value of each role and the rules behind them
(chroma tapering, hue adjustments, which pairs meet which minimum).

- Keep the OKLCH value as the master. Derived renditions (hex for older targets, a wide-gamut value
  where the medium supports it) are generated from it and never edited by hand and read back.
- Build ramps in OKLCH: fix the lightness of each step first, taper chroma where the gamut narrows,
  and adjust hue only in one direction along a ramp. Check the rendered steps, not the numbers.
- Map semantic color tokens to ramp steps per theme. Dark is its own mapping, with surfaces that
  get lighter as they rise, not an inversion.
- Check contrast on the resolved values of every foreground and background pair, in every theme and
  state, after conversion to the target.
- Values from a physical color standard come only from the user's records or `DESIGN.md`; a
  computed approximation is labeled as such and never becomes the standard's value.

For theme architecture, selecting a theme and the first paint, native controls and media per theme,
high contrast and forced colors, brand combinations, and exporting themes, read
`references/theming.md`.

## Type

Start from `tokens.type`: the families per role and script, `scale.base_px`, and `scale.ratio`.

- Generate size, line height, and weight tokens per role; keep line height unitless.
- Font stacks per locale, with the fallback faces the lock records (`lazuli lock --fallback`) and
  metric overrides so the fallback does not reflow the page.
- Sizes use relative units so the reader's text size applies, and change with width by scale steps,
  not by interpolation.
- Korean text keeps the face's default tracking at body sizes and `word-break: keep-all`.

## Space, shape, and surfaces

- **Space** from `tokens.space`: a base and a scale; name steps by use (inset, stack, inline,
  section). Layout gaps come from the scale.
- **Radius** from `tokens.shape`: a small scale and a step per component role. Different roles may
  have different corners; the reason lives in `tokens.shape.rule`.
- **Surfaces** from `tokens.surface`: elevation levels and what each means, border treatment, and
  every decorative treatment (translucency, texture, heavy outlines, offset shadows) with the job it
  does. A treatment without a job is not tokenized. A treatment that a card names is also decided in
  `defaults`: the token records the value, and the keep entry with its `keep_when` id, the evidence that
  case lists, and a reason is what stops a check from gating it.
- **Icons** from `tokens.icons`: one family, its source, style, stroke, and sizes. Mixed icon
  sources and drawn stand-ins are a decision, recorded in `defaults`.

## Motion

From `tokens.motion`: write durations and easings by purpose (feedback, transition, emphasis) as
`tokens.motion.principles`, with the reduced-motion branch for each, and generate the motion tokens
from them. `reduced_motion: respect` is required; motion that is not essential stops or becomes a
fade.

## DESIGN.md

- Write or update `DESIGN.md` as the contract later work reads: the token values (or the path to
  the token file), the roles, the reasons behind decisions that are not obvious, and the patterns
  components follow.
- Convert between dialects only when asked; keep every value, and report what the target dialect
  cannot express.
- Export tokens in the design-tokens interchange format with `$value` and `$type` when the project
  uses one, with the color space named and hex renditions marked as derived.

## Named defaults to walk

The cards in `shared/slop/cards.yaml` that live in token values - `global-habit-values`,
`starter-surface`, `ornamental-surface`, `hard-edge`, `improvised-icons` - are decided here and
recorded in the plan's `defaults` as keep or reject, whatever the token fields also say. A new
primary color on an unchanged starter theme is not a system.

## Check

Run `lapis-design plan check .lapis/plans/<task>.yaml` after updating `tokens`, and
`lapis-design slop lint --source <source dir>` after writing or changing code; add
`--plan .lapis/plans/<task>.yaml` when a plan exists. The source layer finds literal colors,
off-scale values, and bypassed primitives (`system.*` rules) and needs no browser. It runs without a
plan; then `system.off-scale-value` is judged only against token definitions in the project itself,
and is skipped, never passed, when there are none. Fix what it reports before handing off; the
`ultramarine` skill runs the full lint with the render and behavior layers.

## Reporting

Tell the user the token layers and where they live, what `DESIGN.md` now says, contract changes
that need approval, and the pairs or states whose contrast was checked.
