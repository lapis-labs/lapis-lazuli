# Theming

This file backs `tokens.color.themes`, the `theme` of each color role entry, and the skill's rule
that semantic color tokens map to ramp steps per theme, with dark as its own mapping. The `lapis`
skill decides each theme's role values and the order in which a dark or high-contrast theme is
re-decided; `tokens.md` holds the graph, the names, the renditions, and the write-back of every
rendered value to the plan. This file covers how themes are structured, selected, delivered,
exported, and checked. The examples continue the pottery shop, whose plan lists `light` and `dark`:
`paper` from the firing-log sheet by day, `kiln-night` after dark.

## A theme reassigns roles

A theme is a coherent assignment of semantic roles, not a filter over finished screens. Components
read the same token names in every theme; only the values behind them change. No component carries a
`dark` flag, its own media query, or its own literals.

| Concept | What it is | Changes |
|---|---|---|
| mode | light, dark, high-contrast within one identity | color assignments |
| brand | an identity | color, type mappings, shape, imagery, voice |
| preference | the user's stored setting | which mode applies |

A brand change that also swaps type and logos is not a dark mode; do not model it as one.

**Pairs before values.** A role is incomplete until its neighbors and states are known. From the
components, list what each color meets: body text on the canvas and on raised surfaces; the label on
the reserve fill at rest, hover, pressed, and disabled; the focus ring against the control and the
surface around it; each surface tier against the one below. Do not infer a pair from a name such as
`weak`, `solid`, or `contrast`. Define only the roles the product uses.

**Where the variation lives.** Pick one architecture and write it in `DESIGN.md`:

- *Fixed primitives*: ramp steps keep one value; each theme maps semantic tokens to different steps.
  This is what `tokens.md` builds, and the default.
- *Adaptive scales*: the steps themselves change per theme, and semantic tokens keep one mapping.

Both work. Do not combine them unless tooling resolves both layers the same way every time, and never
call an adaptive step a primitive in documentation or exports. A data scale that `lapis` reverses in
dark gets its own per-theme assignment in the token source, never a flip at run time.

## Selecting a theme

One precedence, written down:

```text
forced platform mode or product policy
  > the user's stored choice > the system preference > the documented default
```

- Store the setting (`light`, `dark`, `system`), not the resolved theme. Under `system`, follow
  `prefers-color-scheme` as it changes; a system change never overrides an explicit choice.
- A page without an in-page switch, as the pottery page can be, simply follows the system.

`light-dark()` with `color-scheme` expresses this without duplicating selectors. The function picks
its first or second color by the color scheme in use where the token is read, so an explicit choice
only sets `color-scheme` on the root:

```css
:root {                                     /* derived sRGB renditions, light only */
  --color-field-canvas: #F8F5EE;
  --color-foreground-primary: #25211D;
}
@supports (color: light-dark(#000, #fff)) {
  :root {
    color-scheme: light dark;
    --color-field-canvas: light-dark(oklch(0.97 0.01 85), oklch(0.22 0.01 60));
    --color-foreground-primary: light-dark(oklch(0.25 0.01 60), oklch(0.93 0.01 84));
  }
  :root[data-theme="light"] { color-scheme: light; }
  :root[data-theme="dark"] { color-scheme: dark; }
}
```

A browser without `light-dark()` gets the light renditions; add a `prefers-color-scheme: dark` block
with dark renditions if it must get dark too. Either way the file is generated from the token source.
`light-dark()` holds two schemes only, so a high-contrast theme is a separate assignment (below).

The render check turns on dark only through the color-scheme preference: at 390 px it loads the page
in the light and the dark scheme and compares the computed colors of the root, the body, and the first
sections, and only when they differ does it capture dark at 390, 768, and 1440 px. So with no stored
choice, the page must follow `prefers-color-scheme`. A theme reachable only through a switch is never
captured: when the plan lists `dark`, the gate blocks the release as `release.theme-missing`;
otherwise nothing checks it.

**First paint.** The server's render and the first client render agree on the theme: read a cookie on
the server and render the attribute, or run a small inline script before styles paint; with neither,
render the system-following default. Never animate the palette during that first resolution. An inline
script that sets the root attribute before hydration makes that one attribute differ from the server
render; suppress the warning only for that attribute, since a mismatch in rendered content means
server and client disagree. A transition on a user's switch is
motion and follows `tokens.motion`.

**Native parts.** Set `color-scheme` per theme so form controls, scrollbars, and the default canvas
follow; it does not make a product palette. A `theme-color` meta element with a `media` attribute
follows the system preference only.

## What a theme covers besides tokens

A theme is incomplete when the shell changes but part of the task stays in the other theme. Theme,
or check, each of these the product has: selection and caret colors, autofilled fields, native
selects and date pickers, embedded frames, code blocks, charts, and maps. On the pottery page that is
the reservation sheet: the address fields with autofill and any native control in it.

| Asset | Per theme |
|---|---|
| logo and marks | an approved variant per theme; never recolor one |
| screenshots | captured in the theme they appear in |
| illustrations | transparent edges and embedded text checked on each canvas |
| photographs | no blanket dark overlay; the kiln photographs stay as shot |
| user uploads | a neutral frame or outline for unknown transparency |
| charts and code | every category, selection, and focus state rethemed |

Never invert raster images. A `<picture>` source with `media="(prefers-color-scheme: dark)"` follows
the system preference, not a stored choice; when users can choose, switch assets by the theme
attribute instead. Icons that take the text color follow on their own.

**Korean text.** A theme changes colors, not metrics: size, line height, tracking, and `keep-all` stay
the same in every theme, so switching never reflows a paragraph. Light text on a dark field looks
heavier, and dense syllables with double finals such as 읽, 않, 없, or 짧 in a bold heading can close up. Judge Korean headings
and body in each theme at their real size. If a heading needs a lighter stroke in dark, a grade axis,
where the face has one, changes stroke weight without changing advance widths; a weight change
reflows the text and must use a weight the plan's type role lists.

## High contrast, forced colors, and other preferences

`lapis` decides the high-contrast values. Here they become a separate assignment, selected by
`@media (prefers-contrast: more)` and by an explicit choice; decide its polarity, or ship both, and
name it in `DESIGN.md`. It is listed in `tokens.color.themes` only when the product ships it; the
pottery plan does not, so no high-contrast combination is supported, and the platform's forced colors
still apply.

In forced colors (`@media (forced-colors: active)`) the platform replaces author colors: shadows
compute to none, background images other than `url()` images are dropped, and backgrounds keep only
their alpha. So:

- Draw boundaries and focus with borders and outlines. A transparent border or outline becomes visible
  in the system color; a focus ring made only of `box-shadow` disappears, so pair it with a transparent
  outline.
- Make any adjustment inside that media query with system colors (`CanvasText`, `LinkText`,
  `Highlight`, `GrayText`), never with tokens.
- Set `forced-color-adjust: none` only on an element whose colors are the content, such as a glaze
  swatch on a piece's detail; never on the page to keep brand colors.

Reduced transparency (`@media (prefers-reduced-transparency: reduce)`, where the browser reports it)
swaps each translucent surface token, such as the scrim behind the reservation sheet, for its opaque
version. Reduced motion is the motion branch in `tokens.md`.

Of these preferences the render check emulates only the color scheme and reduced motion. Check
forced colors, increased contrast, and reduced transparency by hand, with the browser emulating each.

## Brands and supported combinations

When several brands share components, vary only the identity seams: color assignments, approved
families and type mappings, radius and surface language, the icon family where a host requires it,
imagery, a little motion personality, voice. Keep shared the component anatomy and API, role names,
focus, keyboard, target, and screen-reader behavior, the states, and responsive and localization
behavior. A brand that needs different anatomy or task behavior is a product extension, not a theme.

Name the supported combinations of brand, theme, and platform with an owner for each. A missing
combination is unsupported, never derived automatically; publishing every theoretical combination
produces files nobody maintains.

## Themes in files

- **Plan.** Every value that renders in a theme is a role entry with that `theme`, as `tokens.md`
  says; the render checks compare against those entries.
- **DESIGN.md.** When its dialect holds one value per token, write the default theme's values there,
  name every supported theme and where its values live, and never present the default as the whole
  system.
- **Interchange file.** The format has no theme construct, so choose and name one: one file per theme
  with aligned names (`roles.light.tokens.json`, `roles.dark.tokens.json`), the default here; a
  flattened default with the omitted themes named; theme values in `$extensions` for a consumer known
  to read them; or themes kept in the token source with resolved files per theme. Never infer "one
  theme" from a source that has no theme data.
- **Imports.** Keep the collection and theme identity of a design-tool import across the boundary,
  and settle authority per family as `tokens.md` describes.

## Check a theme

For each component in each supported theme, exercise the states it has (default, hover, focus,
active, selected, disabled, loading, error, success), its text and non-text pairs on the surfaces it
actually sits on, its native parts, the icons, charts, images, and shadows inside it, text at 200%,
reduced motion and reduced transparency, and a theme switch while the reservation sheet is open.
Then run one real task, reserving a piece, in every supported theme. A switch that flips colors
proves nothing by itself.

When one pair fails in one theme, fix that meaning only. Suppose the label on the dark reserve fill
failed while links and the focus ring, which read the same `reserve.72`, passed. Remap
`color.interaction.action` for dark to another step, and leave the shared step alone. If the pressed
state shared the default's assignment and no longer can, give it its own token
(`color.interaction.action-pressed`); never branch on the theme inside the button. Record the
resolved pair and its ratio for each state in both themes, and check the focus ring against the
control and the surface around it.

The render checks read what the captures show: `color.text-contrast` measures text on its backdrop in
the light and dark captures at rest, hover, and focus, and `color.inverted-dark-theme` compares the two
captures element by element and reports a literal inversion and, with it, how many raised surfaces
turned darker than what they sit on.
