# Color decisions

The procedure behind plan step 6. The result is `tokens.color`; turning it into ramps, aliases, and files is the job of `lps-system`.

```yaml
tokens:
  color:
    decision:            # {answer, status} for each of the six axes
      medium: { answer: "...", status: known }
    roles:               # oklch or ref, never both
      - { name: canvas, role: field, oklch: [L, C, H], source_class: authored }
      - { name: canvas, role: field, theme: dark, oklch: [L, C, H], source_class: authored }
      - { name: action, role: interaction, ref: "DESIGN.md#colors.primary" }
    relations: [near-monochrome, opposing]
    themes: [light, dark]
    data_scales: [sequential]
```

## Answer the six axes

An answer removes options. "Modern", "clean", and "digital" remove nothing.

| Axis | A usable answer names |
|---|---|
| `medium` | every output (browser, native app, projection, e-ink, office print, production print, packaging), the gamut you can count on, and whether color must survive grayscale or a poor copy |
| `task_structure` | what people must find, compare, monitor, or act on; which signals come first and which stay quiet until needed |
| `content_colors` | the photos, products, data, maps, and user media that bring their own color, with their extremes |
| `identity` | fixed colors with source and space, permitted backgrounds, prohibited uses, roles the identity hue must not be mistaken for. "No fixed identity" is a valid answer |
| `environment` | ambient light and glare, viewing distance, session length, display quality, age range, color-vision differences, and the settings to honor: theme choice, increased contrast, forced colors, reduced transparency |
| `tone` | the feel, translated into the variables below and tied to world materials |

Statuses follow `claims`: `known` (evidence such as PRODUCT.md, DESIGN.md, the content, a brand guide), `declared` (the user said it), `proposed` (your reversible assumption, also written to `claims.proposed`), `unresolved` (open). Keep what an unresolved axis controls as named candidates, not a silent pick, and ask when an unresolved `medium` or `identity` would change values, as print or an existing brand usually does.

Tone words are a brief, not a hue lookup; no industry, mood, or audience maps to a hue. Write the tone answer as variables:

- lightness range: broad or compressed, high-key or low-key, where the extremes sit;
- chroma distribution: which roles may carry high chroma, on how much area;
- hue relation: from the relations below;
- dominance: which color owns the most area, which colors interrupt it;
- hierarchy: what is seen first, next, and only on demand;
- edges and material: flat, printed, layered, translucent, textured.

"Quiet" can be a low-chroma field with one strong signal, or broad lightness steps across several muted hues; pick what the subject supports. Polarity (light or dark field) belongs to the environment and tone answers; neither wins everywhere, so ship both when users choose or conditions vary.

For a pool lane-booking screen, "phones at the poolside, sRGB; the timetable also printed in grayscale for the notice board" answers `medium`, and "a pale field from the tile grout, one saturated signal from the lane-rope floats on small areas" answers `tone`. "Fresh and energetic" answers neither.

## Content colors first

List what the content brings before choosing any interface color: product finishes, photography, illustration, maps, charts, user uploads. Decide the interface's stance toward each:

| Stance | The interface | Fits when |
|---|---|---|
| frame | stays low in chroma and leaves color to the content | content varies widely or is the product |
| echo | takes a relation (temperature, lightness order) from it | content is consistent and characteristic |
| oppose | contrasts with it on purpose | content is uniform and needs figure-ground |
| avoid | keeps its hues away from content hues | content colors carry meaning, such as product variants |

1. Collect the range: the darkest, lightest, most saturated, and most muted items, not one flattering image.
2. Sample relationships across several areas of each item, never one pixel. A screen or photo sample informs a value you author; it never becomes a spec value.
3. Put each candidate field and accent beside the whole range. Reject a field that swallows low-key images and an accent that competes with the product's color.
4. Give content you cannot see in advance, such as uploads, a controlled frame, outline, or scrim.

Role `content` entries record what the interface must live beside, usually with `source_class: screen-sample`, so the maker and the critic can compare against them. They are the one role where a detection-only value may appear, and they never become interface colors. A product swatch shown as data comes from the product record, not the palette.

## Roles and how many colors each needs

Every color has exactly one role. Keep roles separately assignable until rendered states show a merge is harmless. The count follows the jobs.

| Role | Members | How many |
|---|---|---|
| `field` | canvas, surface tiers, overlay, border, divider | one per layer that exists |
| `foreground` | primary, secondary, disabled, inverse, an on-color per filled surface | on-colors tuned to each fill's hue; neutral gray on a saturated fill looks muddy and often fails |
| `identity` | fixed masters, on-identity foreground, signature accent | what the identity supplies |
| `interaction` | action (default, hover, pressed), on-action, link, focus, selection | one action family; focus and selection distinct from it and each other |
| `status` | per status: foreground, container, on-container; solid and on-solid only for a justified strong badge | only the statuses the product uses |
| `data` | per scale in `data_scales` | per scale type, below |
| `content` | observed content colors | as listed |

- Identity is not automatically the action color. When a brand master fails contrast as text or as a fill carrying text, keep it for identity moments and derive the action color near it as `proposed`. Never alter an approved master.
- One intense color on links, buttons, badges, focus, charts, and ornament makes everything compete. Give each accent a role; there is no universal accent count.
- Keep one neutral family, or zone warm and cool neutrals on purpose and record the zones.
- Choose endpoints per role, not by habit. Pure black and white fit high-contrast themes, e-ink and print, and an approved brand pair.
- A gradient or a colored word in a headline is emphasis without meaning unless it encodes a category or state.
- A new primary on an unchanged starter theme is not a palette decision.

When DESIGN.md defines colors, a role takes `ref` instead of `oklch`, and a different value needs a `proposed_design_changes` entry.

## Relations and palettes from world materials

`relations` describes how members relate, to be tested, not followed as a recipe. List more than one when true, such as a near-monochrome field with an opposing signal.

| Relation | Meaning | Demands |
|---|---|---|
| `tonal` | one hue family, structured by lightness and chroma | hierarchy from lightness; status and data still need their own hues |
| `neighboring` | adjacent hues sharing a temperature | separation by lightness and chroma; watch action beside status |
| `opposing` | hues from opposite sides of the circle | one side dominates by area, the other signals; differ in lightness too, since some opposing pairs merge for common color-vision deficiencies |
| `temperature-contrast` | warm against cool, as zones or field against signal | a stated zone per role; neutrals follow their zone |
| `near-monochrome` | chroma near zero almost everywhere | content or one signal carries color; lightness carries hierarchy |
| `multi-hue` | several families at once | a written job and bounded area per family, stable assignment |

Build from `world_materials`, not mood words:

1. For each material with color (a surface, finish, printed record, mark, light condition), note its lightness order, where its chroma sits and on how much area, its temperature, its edges, and how it changes (wet and dry, worn, day and night).
2. The material around the content usually suggests the field, a small recurring meaningful mark the signal, and how they relate the relation.
3. A mood word no material supports becomes a `proposed` answer to confirm, not a value.
4. Author the values yourself in OKLCH, informed by the samples.

A ready-made package is a default, not a derivation: cream field, clay or brass accent, and serif display for "premium"; dark field, violet-to-blue gradients, and glow for "technical". Trading one for the other is still a default; the cards `warm-editorial` and `dark-luminous` give the routes out.

Make only as many candidates as the open decision needs, each changing one variable: polarity, chroma concentration, temperature relation, or number of families. Show them with the same content, type, and states, and judge four things separately, because they disagree: harmony (do the colors belong together), preference (will this audience like it), figure-ground (does the figure separate), and discrimination (can people tell roles, states, and values apart). Reject for a concrete reason: roles collide, hierarchy is lost, content disappears, a pair fails, a scale reverses, or it works in only one theme or with one image.

Visual weight comes from area, repetition, lightness edges, chroma, type mass, and isolation together: a mark color can dominate as a panel, and an accent repeated in every row becomes a stripe. Judge the densest real view.

## Author in OKLCH

Write new values as OKLCH `[L, C, H]`. Rewriting a color in OKLCH neither changes nor improves it; the space pays off when you edit: stepping a ramp, lowering chroma, holding hue, interpolating. Approved brand values stay as supplied.

- **Lightness.** L runs from 0 (black) to 1 (white) and follows perceived lightness far better than HSL lightness. Fix the L of each role first (canvas, surfaces, borders, muted text, text), then fill the gaps. Steps people must tell apart need a visible difference at their real size; steps that only mark elevation can sit closer.
- **Chroma near the gamut edge.** Displayable chroma shrinks toward zero as L nears 0 or 1, and each hue peaks at a different lightness: yellows only when light, blues and violets at mid-to-low lightness. A constant-C ramp leaves the gamut at one end, so taper C step by step to keep every step inside sRGB; clipping shifts hue and can merge neighboring steps. A wide-gamut value is an extra rendition, never the only value.
- **Hue drift.** Holding H keeps hue steadier than older spaces, not perfectly, and some families change character with lightness in any space: dark yellows read olive, dark oranges brown. When a step leaves its family, move H a few degrees, in one direction along the ramp. At very low chroma hue hardly shows; for tinted neutrals keep one hue and a small, steady chroma.
- **Evenness.** Equal L steps are a start, not a guarantee. On the rendered ramp, fix a step that jumps, a band that stands out, or two steps that merge.
- **Interpolation.** Use Oklab through neutrals and OKLCH with a stated hue direction around the circle; encoded sRGB gives gray or dark midpoints. A gradient needs a job: a spectrum, a mask, light as the subject, an approved brand gradient.
- **L is not contrast.** An L gap does not predict a contrast ratio; compute contrast from the resolved colors.

## Themes

List in `themes` (`light`, `dark`, `high-contrast`) only what the product ships, chosen from the environment axis and platform. Each theme is its own set of role decisions. A role entry without `theme` applies to every theme; a value decided for one theme gets its own entry with the same `name` and `theme: dark` or `theme: high-contrast`. When you decide only the rule, state it and leave the value to `lps-system`.

**Dark is not inversion.** Inversion breaks elevation, images, focus, and status. Decide in order:

1. canvas lightness and temperature, from the same materials as the light theme;
2. surface tiers that get lighter as they rise, since shadows barely read on dark;
3. foreground and muted foreground, readable without glare;
4. accents, which usually need higher L and often lower C so they do not vibrate;
5. borders, focus, and disabled states, rebuilt for their new neighbors;
6. status, charts, logos (approved dark variants only), illustrations, and photography, checked again.

Glow and halos are not dark-theme materials; mark focus and state with borders and contrast unless emitted light is the subject.

**High contrast** is its own constraint, not a more saturated dark theme. Drop decorative distinctions, make every boundary a visible line, allow pure endpoints, and aim text at the enhanced level (7:1 normal, 4.5:1 large). Map the user's increased-contrast preference to it.

**Forced colors.** When the platform substitutes system colors, meaning must survive: focus, selection, and component boundaries need real borders or outlines, not only backgrounds or shadows, and icons follow the text color. Never opt the whole page out to keep brand colors; opt out only an element whose colors are the content, such as a color swatch, and let charts read through labels and patterns. Your own high-contrast theme does not replace this.

**Reduced transparency.** Every translucent surface needs an opaque version for users who ask, and its contrast is checked on every backdrop it can cover.

## Interaction and status

- Action, link, focus, and selection stay distinguishable from one another, and from identity and status, wherever they meet.
- The focus indicator needs 3:1 against adjacent colors on every surface it can land on, including identity fills and images; when one color cannot do that, use an inner and an outer ring.
- Hover and pressed need not be darker; the theme and interaction language set the direction.
- Disabled styling is exempt from contrast minimums, so never put needed information in it.
- Mark links in running text with more than color, usually an underline. Show selection with a mark, border, or weight change, not a tint alone.
- Define only the statuses the product has, with the domain's meanings: a price drop is not an error, and a finished task is not a rising trend.
- Pair every status color with an icon, text naming the state, and a position next to what it describes.
- When identity or action shares a hue with a status, such as a red brand and an error, separate them by lightness, form, and wording, or move the status hue. Keep status colors out of categorical sequences.

## Data scales

Choose each scale from what the data means, list it in `data_scales`, and run its check.

| Scale | Data | Build | Check |
|---|---|---|---|
| `categorical` | unordered groups | hues that also differ in lightness; same assignment across views and themes | every pair distinguishable at real mark size, including simulated color-vision deficiencies |
| `sequential` | ordered low to high | one lightness direction; the task decides which end stands out | OKLCH lightness monotonic across steps |
| `diverging` | two directions from a meaningful midpoint (zero, a target) | two branches around a neutral center | lightness symmetric around the midpoint |
| `cyclic` | values that wrap (angle, hour, phase) | even steps around the circle | continuity where end meets start |

- When categories stop being distinguishable, use direct labels, grouping, filtering, or small multiples, not more hues.
- Missing, suppressed, and out-of-range values get their own treatment, such as a hatch or labeled neutral, never the lowest class or the midpoint.
- Without a meaningful midpoint a scale is not diverging. Red for bad and green for good are domain conventions, not rules.
- Chart selection and focus use outlines and weight, never a series color.
- In a dark theme, check every scale again on the plot surface. Reversing a sequential scale is a recorded decision, not an automatic flip.

## Contrast and color vision

These are requirements. Measure the resolved pair: the actual foreground on the actual background, after gamut mapping, with transparency composited on every possible backdrop, at the worst point of any gradient or image, in every theme and state.

| What | Minimum |
|---|---|
| Normal text | 4.5:1 |
| Large text: 18 pt (24 CSS px) regular, or 14 pt (about 18.7 CSS px) bold | 3:1 |
| Parts of controls and states needed to identify them, focus indicators, graphics needed to understand content | 3:1 against adjacent colors |
| Enhanced level, when the project claims it | 7:1 normal, 4.5:1 large |

- Ratios are not rounded: 4.49:1 fails 4.5:1.
- Disabled controls, pure decoration, and logotypes fall outside the text minimums.
- Thin or small type can be hard to read at a nominal pass; give it more contrast.
- Saturated colors can look brighter than their luminance; the ratio still decides.
- Color never carries meaning alone: status, required fields, links, selection, and chart series each get a second cue (text, icon, shape, dash, position), and essential chart values are available as text.
- Color-vision simulations and grayscale views are diagnostics, not proof. Redundant cues are the fix.

## Physical color standards and print

A physical standard enters when the user has a code (a brand guide, a paint or ink specification), the medium includes print or material, or the subject is a physical finish.

1. Check the code: `lazuli color lookup <system> <code>` normalizes it, says whether it is complete (a code missing its library suffix is not), and gives the reference link. For coordinate systems (`hlc`, `ral-design-plus`) it adds a computed OKLCH approximation labeled as computed; other systems get codes and links only.
2. Get the value from the user. Owner-published data or a measurement of the physical sample is recorded with `lazuli color record <system> <code> --oklch L C H --source-class <class>`, class `provider` or `measured`; a screen or photo sample is `screen-sample`, detection only. Records stay in the user's cache, never in the project.
3. Without such a value, do not fill the gap: use a brand-approved value from DESIGN.md, author a screen value labeled as yours, or leave `identity` `unresolved` and ask. A computed approximation may seed an authored value; the value is then yours, not the standard's.
4. To see which codes lie near a screen color, run `lazuli search --type color <value>`, which lists the nearest computed codes and the user's recorded values. A nearest candidate is never an identity.

Never write a standard's value from memory, and never build a table converting one system into another. Outside the `content` role, only spec-path classes may become a role's `oklch`: `authored`, `provider`, `brand-approved`, `measured`, `published`. `computed`, `converted`, `nearest-match`, `screen-sample`, and `unofficial` serve detection and comparison. Record each value's class in the role entry's `source_class`, and list the document it came from in `sources`.

Put a code in `system_code` only when it is that role's physical specification. `system_code.system` takes the same ids as the commands: `pantone`, `ral-classic`, `ral-design-plus`, `ncs`, `munsell`, `hlc`, `freetone`, or `other`.

A project can keep two masters, a physical specification and an approved screen value; record both and overwrite neither. Finish, substrate, and lighting change appearance, and metallic, fluorescent, or textured finishes cannot live in one flat value.

For print, fill `output_condition` with the medium and the profile the printer names. Do not guess a profile or convert by arithmetic; keep the OKLCH master and let the print workflow convert. Check that roles survive the smaller gamut: saturated accents dull, and pairs separated only by chroma can merge.

## Handoff to lps-system

`lps-system` turns `tokens.color` into ramps, semantic aliases, per-theme assignments, fallback renditions, and DESIGN.md entries. Besides the fields above, hand over each value's `source_class` and the decisions that are rules rather than values: chroma tapering, hue adjustments along a ramp, which scale reverses in which theme, which pairs must meet which minimum. The OKLCH value stays the master; a hex fallback is derived from it and never edited and read back.
