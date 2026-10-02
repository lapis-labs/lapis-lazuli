# Measured and derived values in the render extract (v1)

This document defines how `render_check` and `lazuli ref` compute the values in
`extract.schema.yaml`: the measured fields on boxes and text runs, and the `derived` block. The
schema fixes the shape; this file fixes the meaning. Thresholds that decide pass or fail live in
`rules.yaml`, not here. Two implementations that follow this file should produce values that lead
every rule to the same outcome.

## Capture

**Viewports.** Each capture is one entry in `viewports`.

| Width | Height | Captures |
| --- | --- | --- |
| 320 | 568 | light theme only, for reflow checks |
| 390 | 844 | light and dark themes; light with reduced motion; light with `browser_chrome: true` (below) |
| 768 | 1024 | light and dark themes |
| 1440 | 900 | light and dark themes |

**Dark theme.** At 390 px the page is loaded once in the light and once in the dark color scheme,
and the computed background and text colors of `html`, `body`, and the first four `section`
elements in document order (`main > section, section`) are compared. If any of them differ, the
page has a dark theme, and dark captures run at 390, 768, and 1440; otherwise there are none.
`meta.dark_theme` records whether the page offered a dark theme when the capture started; dark
captures exist at 390, 768, and 1440 only when it is true.

Every capture uses a device pixel ratio of 2. Boxes and text cover the full page; "first viewport"
below means the region from the top of the page down to the viewport height.

The `browser_chrome` capture emulates mobile browser UI covering 180 px: the page is laid out in
a 390 × 844 layout viewport, so `vh` units resolve against 844 px, while only the top 664 px are
visible and `height` records 664. A full-height shell whose controls sit below 664 px is what
`code.mobile-100vh` looks for.

**Target hosts.** The page URL uses `http` or `https`. Any other scheme (`file:`, `data:`, `about:`)
is refused: a page opened from a file does not load modules or root-relative paths the way a served
page does, and its URL carries a local path. Serve the folder on loopback instead. Hosts that are
ours (defined below) are captured without a flag. A public host is
captured only with `--public`. Even then, every host in the source registry
(`sources/registry.yaml`), whatever its access policy, and every host in the plan's `references` is
refused, including when a redirect lands there. `render check` takes an optional `--plan PATH`;
without it, `--task` finds `.lapis/plans/<task>.yaml`; with no plan, only the registry check
applies. Pages that are not ours are captured only with `lazuli ref capture`.

A host is ours when it is `localhost`, a name under `.localhost`, or a loopback or private IP
literal (127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 0.0.0.0, ::1, fc00::/7).
The host of a URL a run starts with (the page for `render check`; the source URL and
`--stub-url` for `behavior check`) is also ours when it is a name under `.test` and every
address it resolves to when the run starts is one of those. Only that exact name, lowercased
and without a trailing dot, is ours; `www.` and other variants are other names. The name is
pinned to the first resolved address that accepts a TCP connection on the URL's port at the
start: the browser gets a host-resolver rule for it (IPv6 in brackets) and a proxy bypass for
it, and the run's own HTTP clients connect to that address with no proxy and send the name as
Host. So the name cannot reach another address during the run. Any other name under `.test`,
and every other host name (`.local` and `.internal` included), is public.

An HTTPS development app opens in the browser only when the operating system trusts the local
certificate authority that signed its certificate (for example after that tool's install step), or
serve the app over HTTP on loopback instead. Pinning a `.test` name never disables certificate or
hostname verification.

An own render extract records `source.addresses` for a pinned `.test` source. Reference profiles
do not decide whether a page is ours and never carry `source.addresses`.

Hosts compare as the registry compares them (case, a trailing dot, and a leading `www.` do not
count), and a registry entry covers every path on its hosts. The check runs on every document
request of the page's main frame, redirect hops and script navigations included, and a refused
request is never sent; a refusal ends the run without an extract.

A page the captured page opens (window.open, a target=_blank navigation, or any other new page
in its browser context) is held to the same rule before its first request is sent. It is never
captured, and it is closed as soon as it opens. A refused request from such a page is failed
before it is sent and noted on stderr; unlike a refusal in the captured page, it does not end
the run.

**Sequence.** For each capture:

1. Load the page and wait for network idle plus one second.
2. Record the motion observations that need the page at rest (`moves_at_rest`,
   `hidden_until_scroll`).
3. Scroll to the bottom in steps of one viewport height, waiting 300 ms per step so lazy content
   loads and scroll-triggered reveals run. After the last step (at once when the page fits in one
   viewport), wait until the network has been idle for 1 s (at most 10 s when it never goes idle),
   then return to the top. Layout shift is recorded from navigation start to the end of that idle
   second (`metrics`), so shifts caused by lazy loading during the scroll pass count, and shifts
   caused by returning to the top do not.
4. Let animations finish their current iteration (infinite animations are paused at their start
   state) and measure everything else.

**Box ids.** Box id = "b" + the first 12 hex digits of SHA-256 over the UTF-8 bytes of the box's
DOM path. The path joins root-to-element steps with "/". Each step is "<localName>:<index>"
(lowercase local name; index counts earlier siblings with the same local name, from 0), or
"#<id>" when the element's id is stable. An id is generated, and therefore not used, when it
contains four or more consecutive digits or starts (case-insensitively) with ":r", "radix-",
"mui-", "react-", "__next", "ember-", or "headlessui-". For example, `<main id="content">` inside
`body` gives the path `html:0/body:0/#content`. `render check`, `behavior check`, and
`lazuli ref` share one implementation, `cli/lapis_design/render/ids.py`, so their ids agree.
Hashing keeps page-specific names out of reference profiles. The same element gets the same id
across themes of one capture run; across widths, elements a breakpoint inserts can shift indexes,
so `theme-pair` matches by id and `responsive-structure` falls back to role and reading order when
ids do not match.

**Colors.** Computed colors (sRGB or wider gamut) are converted to OKLCH. A fourth value is the
alpha when it is below 1.

**Palette.** Downsample the full-page screenshot to 256 px wide by area averaging in linear light,
then convert to OKLab. Pixels that are pure black or pure white (L ≤ 0.005 or L ≥ 0.995, and
C ≤ 0.002) are counted separately and reported as their own entries with `exact: true`; the rules
read these entries rather than re-deriving them. The rest are clustered with k-means, k = 8,
initialized deterministically with the 8 most frequent colors after quantizing OKLab to a 0.02
grid, and iterated until assignments stop changing (at most 50 iterations). `share` is the share
of all pixels. `role_guess` assigns each color by where its
pixels come from: `field` (backgrounds of sections and the page), `foreground` (text), `interaction`
(buttons, links, inputs, and focus rings), `status` (alerts, badges with state), `data` (table
cells; a box whose own `class` or `id` holds chart, graph, plot, or sparkline as a whole word, split
at hyphens, underscores, and case changes, so `typography` and `paragraph` do not match; and an
`svg` or `canvas` at least 48 CSS px on its shorter side that has role `img`, `figure`, or
`graphics-document` and an accessible name that names a chart, graph, plot, or visualization (차트,
그래프), or, for an `svg`, holds at least three sibling shapes of one element type and at least two
`text` labels),
`content` (inside media), `identity` (logos and colored headings or accents that are none of the
above), otherwise `unknown`. The role covering most of the color's pixels wins.

**URLs and rights.** `source.url` is stored without query or fragment; `media.host` keeps the
hostname only. For reference-only captures the profile stores no copy, alt text, accessible names,
or screenshots: text runs and viewports carry `text_sig` only, and screenshots and image files stay
in the user's local cache, outside the project. Free-text fields written by our tools, such as an
image `composition`, describe the reference in our own words and never quote its text.

media.host is the host of the URL the browser loaded for the item. When that URL is on the
page's own host and its query carries another absolute http(s) URL (image optimizers such as
/_next/image?url=...), host is the host of that inner URL, so the item stays remote.

## Measured fields on text runs

**Runs.** A text run is a maximal stretch of text inside one box with uniform computed style.
Adjacent inline elements with identical computed style merge into one run. Runs with no visible
characters are not recorded.

**chars.** The number of Unicode code points in the run, whitespace excluded.

**script.** Count the code points of each script, ignoring digits, punctuation, symbols, and
whitespace. In order, the first match wins: `hang` when Hangul and Han together make up at least
half of the counted code points and Hangul is present; `kana` when kana and Han together make up at
least half and kana is present; `hani` when Han alone makes up at least half; otherwise the script
with at least 80% of the counted code points, `mixed` when none reaches 80%, or `other` when
nothing was counted. Korean or Japanese copy with some Latin words therefore keeps its script.

**lang.** The nearest ancestor `lang` attribute, canonicalized (language lowercase, region
uppercase, underscores to hyphens); omitted when none is set or it is not a valid tag.

**text.** The run's string as rendered, after CSS text-transform. Stored for our own renders and
for own or licensed references; never for reference-only captures.

**font.** `requested` is the first family in the CSS `font-family` stack; `rendered` is the family
that painted the most glyphs of the run (a web font is named by the first family in the stack with
a loaded `@font-face`, because the name inside its file can be empty or scrambled; a local face whose
family name is a stack family plus weight or slope words, such as a static face named "Pretendard
SemiBold", is named by that stack family); `fallback` is true when the two differ.

`font.synthetic` is `none` for runs below weight 600 in normal style. For a heavier or italic run
set in a loaded web font, bold (or italic) is synthesized when no loaded face of the requested
family covers the requested weight (or style) and CSS `font-synthesis` allows it. For a system font
the browser reports only the used face's PostScript name, and a name with the matching weight or
style token means `none`. In every other case the browser gives no signal, and `synthetic` is
omitted.

**text_sig (runs) and text_sig (viewports).** Keyed MinHash signatures, computed from the DOM
text before CSS text-transform:

1. Normalize: Unicode NFKC, then full case folding, then remove format characters (general
   category Cf, such as zero-width space and soft hyphen), then replace Unicode White_Space
   characters with a space, collapse runs of spaces, and trim.
2. Shingle: substrings of code points, 5 long for latn, cyrl, grek, arab, and hebr, 2 long for
   every other script value (hang, hani, kana, thai, mixed, other). A normalized string no longer
   than one shingle is one shingle. A string with nothing left after normalizing has no
   signature.
3. Hash: h_i(s) = the first 4 bytes, big-endian, of HMAC-SHA256(key, UTF-8 of "i:s"), where i is
   the value index in decimal.
4. MinHash: value i = the minimum of h_i over all shingles. Runs use i = 1..16 (128 hex
   characters); the viewport signature uses i = 1..128 (1,024 hex characters) over the visible
   text of all runs in reading order joined by one space, shingled for the script whose runs have
   the most `chars` (ties go to the earlier of latn, cyrl, grek, arab, hebr, hang, kana, hani,
   thai, mixed, other).
5. Encode each value as 8 lowercase hex digits, concatenated.

The key is 32 random bytes created once per user, with file mode 0600, and kept in the user cache,
never in a project: `~/Library/Caches/lazuli/sig.key` on macOS, `$XDG_CACHE_HOME/lazuli/sig.key`
(else `~/.cache/lazuli/sig.key`) on Linux, and `%LOCALAPPDATA%\lazuli\Cache\sig.key` on Windows.
`LAPIS_SIG_KEY_FILE` overrides the path (`cli/lapis_design/sig_key.py`). `meta.sig_key_id` is the
first 8 hex digits of SHA-256 of the key. Signatures are comparable only when their key ids match.
The estimated Jaccard similarity of two signatures is the share of equal values. The reference
implementation is `cli/lapis_design/text_sig.py`, pinned by test vectors in `tests/test_text_sig.py`.

**type_role.** Assigned in this order; the first match wins. "Body size" is the size of the body
group defined in the last row. A run's text block is the nearest element, from the run's own
element up, that is not laid out inline (computed `display` other than `inline` or `contents`).

| Role | Rule |
| --- | --- |
| code | inside `code`, `pre`, `kbd`, or `samp` |
| data | table cells and elements whose text is mostly digits, currency, or units, aligned in a column |
| nav | inside `nav` or an element with role navigation |
| ui | inside `button`, `input`, `select`, `textarea`, `label`, or an element with role button, textbox, searchbox, listbox, combobox, checkbox, radio, switch, or slider; or inside a link (`a` with `href`, or role link), except that a link whose text block has other runs outside links, all of them `body`, is `body` |
| display | the largest heading in the first section, when it is at least 1.5 times the next heading size |
| heading | `h1`–`h6`, role heading, or a run of at most 80 characters that starts a block, is followed by body text in the same section, and is at least 1.1 times the body size or at least 200 heavier than body |
| label | a run of at most 40 characters directly before a heading or a value, smaller than body size |
| caption | `figcaption`, `small`, or runs smaller than body size inside media, cards, or footers |
| body | runs in the size group (size rounded to 0.5 px) with the most characters among paragraph-like blocks (`p`, `li`, `dd`, `blockquote`, or text blocks of two or more lines); when there are none, the size group with the most characters overall |
| other | anything else |

**measure_chars.** The median number of code points per rendered line of the run, spaces included
(unlike `chars`), so the rules' line-length limits read as usual.

**fill.** `gradient` when the text is painted through a background with `background-clip: text`,
`transparent` when the fill is fully transparent without a gradient, otherwise `solid`. For
gradient text, `color` records the gradient stop with the lowest contrast ratio against the
backdrop median, so contrast checks test the weakest part of the fill.

**backdrop.** Render the capture a second time with every text color set to transparent and every
`background-clip: text` background removed. For the run's glyph boxes, sample the backdrop pixels:
`oklch` is the median color and `worst` the sampled color with the lowest WCAG 2 contrast ratio
against the text color. `kind` is `solid` when every sample is within ΔE_OK 0.02 of the median,
`image` when most samples come from a media box, `gradient` when they come from a box with a
gradient layer, and `mixed` otherwise.

**states.** For runs inside links, buttons, and inputs: the text color and backdrop median with
`:hover`, `:focus-visible`, and `:active` forced on the interactive box. An input has no `states`:
its typed value and placeholder are not text nodes, so they form no text run.

## Measured fields on boxes

**role, role_basis, role_confidence.** A recognized ARIA `role` decides the role first (`aria`),
then the tag (`semantic`); otherwise the role is a guess (`heuristic`): `other` for `html` and
`body`, `icon` for icon fonts and emoji, `card` for a box with a visible boundary (a background
that differs from its parent's, a border, a shadow, or a background image), and `other` for the
rest. `role_confidence` is 1.0 for `semantic` and `aria`, 0.7 for a heuristic box with a visible
boundary, and 0.5 for other heuristic boxes.

**paint_order.** The rank of the box in the browser's paint order, as reported by the browser's
DOM snapshot (Chrome DevTools Protocol `DOMSnapshot.captureSnapshot` with paint order). Of two
overlapping boxes, the one with the higher rank is painted on top.

**clipped.** `overflow` when the content's scroll size exceeds the box and the overflow is hidden
or clipped, `ellipsis` when `text-overflow: ellipsis` is active, `line-clamp` when a line clamp cut
the text, otherwise `none`. Ellipsis and line clamp are deliberate truncation; overflow is not.

**style.shadows.** Every layer of `box-shadow`, `filter: drop-shadow()`, and `text-shadow`, with the
color in OKLCH and alpha as its fourth value.

**style.gradients.** Every gradient layer in `background-image`, `border-image`, `mask-image`, and
text painted with `background-clip: text`. Stop positions are fractions of the gradient line
(pixel positions are converted); they may fall outside 0–1. `area_share` is the painted area of
the layer divided by the full page area; `first_viewport_share` is its painted area inside the
first viewport divided by the first viewport's area. `blur_px` is the blur
radius of a `filter: blur()` on the same element. `behind` names the box, among those painted
above the layer, whose rect overlaps it most.

**style.filter_blur_px.** The blur radius of `filter: blur()` on the element, so blurred solid
shapes (halos drawn without gradients) are visible.

**style.backdrop_filter.** The blur radius of `backdrop-filter`, plus the other filter functions as
computed strings.

**style.background_pattern.** A repeating decorative background classified from its geometry:
`grid` (two families of parallel lines at right angles), `dot-grid` (isolated dots on a lattice),
`crosshair` (plus marks on a lattice), `stripes` (one family of lines), `noise` (no period), or
`other`. `cell_px` is the lattice period and `contrast` the OKLCH L difference between the marks and
the ground.

**style.border_sides.** Width and color of each side, so an accent on one side is visible.

**style.clip.** The `clip-path` shape. For polygons, `vertices` is the vertex count and `jaggedness`
the share of consecutive turn pairs whose directions alternate (a zigzag scores near 1, a rotated
rectangle 0).

**a11y.** Read from the browser's accessibility tree. `name_source` says where the accessible name
came from; `placeholder` means the placeholder was the only source. `pointer_handler` is true for
click or pointer handlers on the element itself, including handlers a framework attaches through
event delegation when the framework's element props can be read (for example React props on the
element's fiber). `pointer_cursor` is true when the element shows `cursor: pointer` without being
natively interactive, a lead when handlers cannot be read. `focus_indicator` is true when forcing
`:focus-visible` changes the outline, border, box-shadow, or background by ΔE_OK above 0.1 or by at
least 2 px.

**icon.** `library` is guessed from the module that rendered it, the class prefix, or the sprite id;
it is null for an inline path that matches none. `glyph` is set for emoji and Unicode symbols as
`U+` and uppercase hex. `action` (the standard action the icon stands for, such as close, search,
or menu) and its `confidence` are omitted until an icon set is chosen to compare shapes against.

**media.** A box has one `media` slot: the topmost `url()` layer of its CSS background when it has
one, otherwise the element's own image (`img`, `picture`, `video`, `canvas`, or `svg`); gradient
layers above that `url()` layer count as overlay. `loaded` is false for images that failed or are
still empty after the scroll pass. `placeholder` is true for known placeholder services, lorem
images, and unresolved template slots. `overlay` measures the layers painted above the image
inside its rect: `alpha_max` is the highest overlay opacity and `coverage` the share of the image
they cover. `phash` is the DCT perceptual hash of the box's region in the full-page screenshot, as
displayed (after object-fit, clipping, and overlays), not of the source file, downsampled to
32 × 32 grayscale, as 16 hex digits.

**scroll.** For boxes that scroll their own content (`x`, `y`, or `both`), and for list boxes
taller than three viewport heights that scroll with the page (`page`): the number of direct
children in the DOM (`items`), the scrollable length, and the gaps between the container edge and
the first and last items.

**motion.** Property names are longhand CSS names in kebab-case (`margin-top`, not `margin` or
`marginTop`); a shorthand in the source is expanded. Transitions and animations are the computed
values; an animation's `properties` are the properties its keyframes change. `hover_changes` lists
properties that change when `:hover` is forced on the box. `moves_at_rest` compares the box rect at
0 and 2,000 ms with no input and animations running. `hidden_until_scroll` is true when the box
starts invisible (opacity below 0.05 or translated more than 20 px from its final place) and
becomes visible only after it is scrolled into view.

## Measured fields on viewports

**scroll_width.** The document's scroll width. A value above the viewport width means the page
scrolls horizontally.

**metrics.** `cls` is the cumulative layout shift, counting shifts without recent input, from
navigation start until the network has been idle for 1 s after the last scroll step (Capture,
Sequence step 3), so shifts caused by lazy loading during the scroll pass count. `shift_sources`
lists the boxes that moved in that window.

## Derived values

**Capture-time values.** Most derived values can be recomputed from the boxes and text runs in the
extract. These cannot, because they read inputs the extract does not store; consumers read the
stored values and do not recompute them:

- `symmetry`: per-line ink rectangles of the text.
- `density`: per-line ink rectangles of the text and the document height.

### type_fingerprint

1. Group text runs by (size rounded to 0.5 px, weight rounded to 100, tracking rounded to
   0.01 em, text-transform).
2. Weight each group by character count; `share` is the group's share of all characters.
3. Sort groups by size, descending. These are the type roles as rendered.
4. `adjacent_ratios[i] = size[i] / size[i + 1]` for consecutive roles.
5. `measure_chars` is the median characters per line of the runs whose `type_role` is `body`.

Used by: flat hierarchy (small ratios between heading and body), oversized hero (first role's
area share of the first viewport), eyebrow detection, plan scale checks.

### sections and section_sequence

Top-level sections are `section`-role boxes, or direct children of `main` (or of `body` when there
is no `main`) taller than 30% of the viewport height; `main` itself is a container, not a section.
A section is split only at its direct child boxes that are taller than 30% of the viewport height,
at least half the section's width, and have a solid background: when there are two or more such
children and two consecutive ones differ in background (ΔE_OK > 0.02), those children replace the
section.

Each section gets one archetype from these cues; `confidence` is the share of cues satisfied. The
archetype with the highest confidence wins when it reaches 0.5; ties go to the earlier row. Rows
run from the most specific to the most general, so a pricing section with three cards is not
called a feature grid. An empty section, one with no text runs and no media, icon, button, link,
or input boxes, matches no archetype: `other` with confidence 0. The numbers in the cues are seed
values.

| Archetype | Cues |
| --- | --- |
| hero | first section; contains the page's largest text; height ≥ 60% of the viewport |
| pricing | a price: a currency symbol ($ € £ ¥ ₩ ₹) before or after a number, or a number followed by `원`, `usd`, `eur`, `krw`, `/mo`, `/month`, `/yr`, `/year`, `/월`, or `/년` (case-insensitive; one-time prices match too); ≥ 2 sibling cards with a button each |
| testimonial | quotation marks or blockquote; for each quote, a person name, caption, label, `cite`, or avatar that overlaps it horizontally and is at most max(100 px, quote height) away vertically |
| faq | ≥ 3 question-like headings, or details/summary elements |
| logo-strip | one cue: ≥ 3 image or svg boxes (role `media`, or an `svg` element; a box inside another counted box is not counted) in one row (vertical centers within the first box's height), each at most 15% of the viewport height, the smallest at least 80% of the largest (heights within 20% of each other), and at most one text run in the section |
| feature-grid | ≥ 3 sibling cards that each have a heading and a short feature blurb (a `body` run with `chars` ≤ 160); ≥ 3 sibling cards |
| cta | short section (≤ 40% viewport height); a heading and ≤ 2 buttons |
| footer | last section; links make up more than half of its text runs; `footer` element or role contentinfo |
| other | none of the above reaches 0.5, or the section is empty |

`section_sequence` lists archetypes in document order. Template matching uses normalized edit
distance (edits / max length).

### sibling_groups

Siblings are boxes with the same parent and the same role. For each group of three or more:

```
similarity = mean over pairs of
  0.4 * size_similarity        (1 - |Δwidth| / max width, same for height, averaged)
+ 0.4 * structure_similarity   (1 - normalized edit distance of child role sequences)
+ 0.2 * text_length_similarity (1 - |Δchars| / max chars)
```

A group with similarity above the rule's threshold while the plan ranks its members differently
(for example a recommended pricing tier) is an "identical siblings despite unequal content" hit.

### card_nesting_max

The deepest chain of card-like boxes. A box is card-like when all three hold: its role is not
button, link, or input; its area is at least 2% of the first viewport; and it has a visible
boundary, meaning a background that differs from the nearest ancestor with a background
(ΔE_OK > 0.02), a border, or a shadow.

### gaps

Vertical gaps between consecutive siblings that are stacked (their horizontal extents overlap by
at least half of the narrower one); side-by-side siblings are skipped. Gaps are classified by level:

- `inside_group`: siblings inside the same card or group container
- `between_groups`: siblings inside the same section
- `between_sections`: consecutive sections

Each level reports median, p10, p90, and coefficient of variation (`cv`). Proximity order holds
when `median(inside_group) < median(between_groups) < median(between_sections)`. `level_ratio` is
`median(between_sections) / median(inside_group)`; a ratio near 1 means every relationship gets the
same space (monotonous spacing). It is omitted when there are no `inside_group` gaps or their
median is 0, and a rule that needs it reports the check as skipped.

### symmetry

Area-weighted mean over text lines and media boxes of `1 - |center_x - W/2| / (W/2)`, where W is
the viewport width and a text line's center is the center of its inked extent, not of its box.
Full-width left-aligned text therefore does not count as centered. 1.0 means everything is centered
on the vertical axis. A capture-time value (above).

### density

The area of the union of the text's per-line ink rectangles and the media and control (button,
link, input) boxes, divided by the page area (viewport width × document height), so nested boxes are
not counted twice. A ratio between 0 and 1. A capture-time value (above).

### signature_found and signature_evidence

`signature_found` is true when an element carries the `data-lapis-signature` attribute; then
`signature_evidence` is `verified`. Implementations mark the plan's `layout.signature` element with
this attribute. Otherwise, when the plan's `layout.signature` text appears in the page's text runs
(case-insensitive), `signature_found` is true and `signature_evidence` is `not-verified`: text
matching is only a fallback. When neither holds, `signature_found` is false and
`signature_evidence` is omitted. `render check` takes `layout.signature` from the plan it reads for
the target-host check, so without a plan only the attribute counts.
