# Type

This file backs plan step 7. The plan holds `tokens.type.roles` (role, family, weights, scripts,
source), `tokens.type.scale` (`base_px`, `ratio`), `tokens.type.lock`, and the comparison behind each
choice in `explorations`; measure, leading, tracking, numerals, and font stacks become implementation
tokens.

## Exploring and shipping

A brief's no-network, no-external-assets, or offline line limits what the page ships and loads. It
never limits what you explore. Always read the local inventory and the catalogs, and take
open-licensed libraries, commercial foundries, and Adobe Fonts as candidates to explore and
brainstorm with. Their licensing, purchase, or activation goes to the user for approval; nothing is
bought, downloaded, or activated for them.

Offline shipping leaves three outcomes: an installed named face with a fallback stack, OFL files the
user supplies for the project, or a generic family that won a recorded comparison against a named
face. A generic family alone is a choice, not a fallback: it has to win the comparison in
`explorations`.

## Roles per script

Name the roles the surface needs before naming any family.

| Role | Job | Choose for | Test with |
|---|---|---|---|
| display | rare, large, carries the subject's voice | fit to world materials; behavior at large sizes | the real title, names, figures, a two-line wrap at the narrowest width |
| heading | marks structure, repeats per section | legibility at heading sizes in every locale | the longest real heading in each locale |
| body | sustained reading | open forms, even texture, full coverage | a real paragraph with links, emphasis, numbers, and mixed-script terms |
| ui | labels, controls, navigation, fields | stable metrics, a real medium or semibold, default spacing | the longest label, an error message, compact and wrapped states |
| data | values that are compared or change | tabular lining figures, signs, currency | signed decimals, currency, dates, empty and extreme values |
| code | source, identifiers, paths, logs | fixed advances, distinct look-alike glyphs | real identifiers, operators, comments in each locale |
| caption | secondary text beside a figure or value | legibility at the smallest size used | the longest caption at its real size |

Writing the roles:

- One `tokens.type.roles` entry per family per role. `scripts` lists only the scripts that family
  draws in that role. A Korean body with a separate Latin companion is two `body` entries, one with
  `[hang]` and one with `[latn]`; a face that draws both gets one entry with both.
- `weights` lists only weights with a named job, usually two or three per surface, and each must
  exist as a real face or variable instance.
- `source` is `contract` (named in `DESIGN.md`), `inventory` (installed locally), or `catalog`. A
  contract face stays unless a named requirement fails; a replacement goes to
  `proposed_design_changes`.
- Roles can share a family; split one off only when another family does a named job better.

What `lazuli search --script <code> --role <role>` coverage means:

- Composite codes expand to plan codes: `kore` is `hang`, `jpan` is `kana` plus `hani`, and `hans`
  and `hant` are both `hani`.
- The Hangul group guarantees the 2,350 common syllables; modern Hangul has 11,172, and names, user
  input, and rare words reach the rest. Where people type text, confirm full coverage or a fallback
  that has it.
- Korean and Chinese sets carry kana, so kana coverage does not make a face Japanese. `hans` and
  `hant` prove only Han coverage; Simplified or Traditional forms, and Taiwan or Hong Kong
  conventions, are yours to check.
- `--role code` returns monospaced families; reading roles leave out display-only and hand-only
  families. `--category` narrows by genre or class (`serif`, `sans`, `bu-ri`, `min-bu-ri.rounded`,
  and so on) and `--license open` to open licenses. When the user classes a face differently,
  `lazuli class set "<family>" --genre <id>` records their class, which outranks catalogs.

## Choosing a face for each role

Work down the rows. "Not checked" means only the report shows the work.

| Decision | Plan field | Checked by |
|---|---|---|
| Character first: each role's job, the real text per locale, what the world materials suggest. A tide table needs aligned figures; a letterpress shop can take its voice from its proof sheets | `world_materials`, `brief.locales`, `brief.platform`, `claims.proposed` | not checked |
| Candidates: installed families (`lazuli local fonts --summary`, and `--origin adobe-sync` for activated Adobe Fonts), catalog families (`lazuli search --script <code> --role <role>`, after `lazuli catalog sync` when `lazuli catalog status` shows none), and foundry or commercial faces named for exploration. At least one is a named face, whatever the delivery | `explorations[*].candidates` | `plan.uncompared-decision` reads two or more candidates, at least one not a generic family |
| For each open role group, set two or three candidates in the real copy of every locale (see Specimen below), read their measured facts (`why`, class, weights, scripts, delivery), and record the choice and why the runner-up lost | `explorations[*]`: `compared_on`, `chosen`, `runner_up_lost` | the same rule reads a `chosen` among the candidates, a specimen or render in `compared_on`, and a `runner_up_lost` |
| Hangul and Latin: one face that draws both, or a Hangul face with a Latin companion as two entries | `tokens.type.roles[*].scripts` | `type.font-fallback` reads a rendered page for text drawn in a face other than the requested one. `scripts` also limits the neutral-grotesque region to Latin |
| Record each choice: `role`, one `family` name, `weights`, `scripts`, `source` | `tokens.type.roles[*]` | the schema; `type.single-neutral-sans` reads whether two or more roles all name one family; `type.overused-neutral-grotesque`, `type.serif-luxury-display`, and `type.costume-monospace` read measured features, so they need the lazuli database |
| Lock with the delivery path: `lazuli lock "<family>" --role <role> --task <task>`. An Adobe face on a web plan adds `--source adobe-sync --delivery adobe-web-project` | `tokens.type.lock` | `font.no-lock` (no lock given), `font.not-locked` (a family missing from it), `font.no-web-delivery` (no web delivery path), `font.channel-mismatch` (files from a source that cannot ship them), `font.use-unknown` (no recorded grant for a planned use) |
| An intended `system-ui` (an operate screen, a tight budget, email) is a candidate like any other: it wins by comparison on each platform in `brief.platform`, against a named face | `explorations` (`chosen: system-ui`); `defaults`: `type.overused-neutral-grotesque`, `keep`, `keep_when: won-comparison`, a `basis`, and a `reason` naming the platforms seen | the generic-family finding below |
| No database: set `LAZULI_DB` to a writable path, run `lazuli local fonts` and `lazuli catalog sync`, then `lazuli search --license open --delivery web`, and lock a family the user or `DESIGN.md` names with `--source`, `--delivery`, `--postscript`. With nothing to name, use `system-ui`, add one `claims.unresolved` line, report it first, and ask the user to name a face or to fix the platform's own face in the brief (`fixed_by: brief`) | `claims.unresolved` | `plan.uncompared-decision` and the finding below stay open until then |

**Specimen.** One throwaway page per task under `.lapis/specimens/`, never shipped. For each
candidate, one column with the page's own title, a real paragraph, a control, an error line, and the
figures, in every locale of `brief.locales`, at the sizes the roles will use; keep the system face or
the current face as a control. Installed faces draw by name. A catalog face that is not installed
cannot be drawn without fetching it, so compare it on `lazuli search` evidence and let `compared_on`
cover only what was drawn. Capture it with `lapis-design render check .lapis/specimens/<task>.html
--task <task>-specimen --width 390` and view the screenshots beside the extract at size.

Before changing a face over a complaint, sort it into one of five conditions.

| Condition | Where the response goes | Checked by |
|---|---|---|
| A measured defect: fallback text, a synthesized weight | the role's entry | `type.font-fallback`, `type.synthetic-style` |
| A face that does not suit its role, like monospace on prose | the entry's `role` | `type.costume-monospace` |
| A signal the subject has not earned | `world_materials` | `type.serif-luxury-display`; otherwise the critic |
| Sameness across the whole system | `tokens.type.roles`, `direction.levers` | `type.single-neutral-sans`, `type.overused-neutral-grotesque` |
| A kept convention or a missing file | a `defaults` entry's `basis` and `keep_when`; `claims.unresolved` | the waiver; `font.not-locked` |

A familiar family is not a defect by its name; write the convention that keeps it (the brief, the
contract, a requirement) as the `basis` of its `defaults` entry, with the rule's `keep_when` id.

**Generic families.** A role's `family` is one name: the schema refuses a comma, and fallbacks go in
the lock (`--fallback`) and the implementation tokens. CSS keywords and the vendor aliases of the
system UI face name no face. They need no lock entry, are never looked up in the database, and match
in any letter case. Five of them, `system-ui` and `sans-serif` among them, resolve to a sans the
platform picks, and `type.single-neutral-sans` counts those as one family. When a web plan's
display, heading, body, and ui roles all use them, `type.overused-neutral-grotesque` reports that no
face was chosen, a finding about the plan rather than a measurement. A generic family can win a
comparison; it is never the answer for lack of one, and with no named face among the candidates
`plan.uncompared-decision` blocks the plan.

Fonts the user is licensed for are candidates like any other, Adobe Fonts included: recommend,
compare, choose, and lock them. On the web an Adobe face is delivered through the user's own Adobe
web project (`--delivery adobe-web-project`). What is limited is how font data is reached, not which
fonts are used: lazuli lists and measures an activated face through the operating system's font
interface and stores names, the metadata the system reports, and measured numbers. It does not open
synced font files by path, extract or store outlines or tables, send font files or font data
anywhere (a family name sent to a catalog lookup is not font data), commit or self-host the files,
or collect anything from Adobe's sites, and nothing derived from an Adobe face is used to train,
evaluate, calibrate, or test. This is lazuli's reading of the terms, not legal advice.

## Reading faces and voice faces

A reading face (body, ui, caption, usually data) is chosen for reading on the target platform, a
voice face (display, sometimes heading) for the subject. Choose them separately, even when one
family ends up doing both.

On rendered real text, a reading face keeps its counters open at the smallest size used, keeps
look-alikes (I, l, 1 and O, 0) distinct, has a real regular and a real heavier weight (and a real
italic when Latin prose needs one), covers every locale in `brief.locales` down to punctuation and
names, and gives a full paragraph an even texture.

- **Latin.** Sans and serif both read well on current screens; subject and density decide. A large
  x-height helps compact UI but makes Latin look oversized beside Hangul or Han at the same size.
- **Hangul.** `min-bu-ri` faces carry UI, dense screens, and small sizes. `bu-ri` faces suit long
  editorial reading at comfortable sizes, where their thin horizontals and brush-shaped terminals
  hold up. The `rounded` min-bu-ri subclass reads as soft; use it when the subject is. At heavy
  weights, check that dense syllables such as 뷁 and 쀍 keep their inner spaces.
- **Japanese.** Use a face drawn for Japanese, so kana and kanji share one design and Han forms
  follow Japanese conventions. Gothic faces (class `min-bu-ri`) are the usual UI choice; Mincho faces
  (`bu-ri`) suit long reading.
- **Chinese.** Choose per locale. A Simplified face on Traditional text, or the reverse, shows wrong
  forms and misplaced punctuation. Hei faces (`min-bu-ri`) for UI, Song or Ming faces (`bu-ri`) for
  reading.

A system face can be the right body or ui choice. Choose it only after seeing it on the platforms
in `brief.platform`, and note which you saw, because it differs by device.

One family can serve every role when it varies by size, weight, width, or optical size, has the
scripts, and its display range carries the subject. Add a voice face when the reading face cannot
carry the voice, the voice face would not survive reading, or their scripts differ. When one
featureless grotesque carries every role with the same habits, walk the `one-neutral-voice` card.

## Pairing across roles and scripts

| System shape | Use when | Watch |
|---|---|---|
| One family, or a superfamily with sans, serif, and mono members | its members cover the roles and locales | a strong house character; unused faces shipped |
| Quiet reading face plus a rare voice face | persuade and experience surfaces with a subject voice | the voice face lacks other scripts or leaks into controls |
| Per-script companions | no single family draws every script well | locales drifting into separate hierarchies and line boxes |
| System faces plus one delivered face | tight budgets, operate surfaces | platform variation |

For each open role, compare two or three materially different candidates, one of which can be the
existing or system face, with the same real content, size, and state in every locale. Stop when each
role has a winner or a named blocker, and record in `explorations` why the runner-up lost, so the
same default does not return under another name.

### Matching Latin with Hangul, kana, and Han

Render one line of real mixed content at the real size, for example
`Account 계정 アカウント 账户 12,480 Aa가ア直`, and compare:

1. **Apparent size.** Hangul and Han fill most of the em square; Latin lowercase fills only its
   x-height. Match the Latin x-height (and cap height for capital-heavy titles) to the visual body
   of the Hangul or Han, not the font-size numbers. Scale a companion once, for example with
   `size-adjust` in its `@font-face`, never element by element. A per-locale size or line-height
   difference is a token decision; record it in `claims.proposed`.
2. **Baseline and line box.** Put Latin acronyms, digits, currency, and parentheses inside Hangul or
   kana text in a button, a table row, and a two-line label. If the Latin sits high or low, change
   the companion or the line-height token; never nudge glyphs with offsets.
3. **Stroke weight.** Equal weight numbers do not mean equal darkness: Hangul and Han often look
   darker because each square holds more strokes. Choose companion weights by eye per role; the
   Latin side often needs a heavier step.
4. **Contrast and terminals.** Pair a `bu-ri` face with a Latin face of related contrast and
   terminal shape, not with any serif; a `min-bu-ri` face with a sans of similar stroke contrast and
   width. Class names do not translate across scripts; match the traits.
5. **Width and punctuation.** Compare the longest navigation label in each locale, and check which
   face draws quotes, brackets, dashes, and digits in mixed text.

`lazuli search --similar-to "<family>"` ranks installed families by measured distance, which
shortlists a companion or a fallback; the rendered comparison decides.

In a stack such as `"Latin face", "Hangul face"`, the first face draws every character it has,
including digits, quotes, and spaces. That suits Latin words and digits, but a Latin face's narrow
quotes and baseline ellipsis look wrong in Japanese or Chinese text that expects full-width
punctuation. Order each locale's stack on purpose, or limit the Latin face with `unicode-range`.

## Setting Korean, Japanese, and Chinese

Tag authored copy with language tags (`ko`, `ja`, `zh-Hans`, `zh-Hant`; a region such as
`zh-Hant-HK` only when it changes forms or punctuation) and select stacks and breaking rules with
`:lang()`, which inherits. `lang` helps a face pick locale forms but cannot supply missing glyphs.
Never guess a user name's language from its characters.

**Korean**

- Set `word-break: keep-all` on Korean text blocks, with `overflow-wrap: anywhere` so long URLs and
  identifiers can still break. Scope it to Korean; applied globally it removes the ordinary break
  points of Japanese and Chinese.
- When a word does not fit a narrow control or cell, let the component grow, shorten the label, or
  change the layout, and keep `keep-all`.
- Body text keeps the face's default tracking. Tighten Hangul only at display sizes, as far as the
  face holds up.
- Word spaces carry meaning; never add or remove them to fix a line. Justified Korean opens wide
  word gaps in narrow columns, so keep body text ragged unless a Korean reader has reviewed it.

**Japanese**

- Use `word-break: normal` with `line-break: strict`. Lines break between most characters; closing
  brackets and 、。 never start a line, opening brackets never end one, and `strict` also keeps small
  kana and the prolonged sound mark off line starts. Justified body text is normal practice.
- Use semantic `<ruby>` and `<rt>` for readings. Ruby enlarges the line box, so leave room in the
  leading and test at increased text size.
- Emphasize with emphasis marks (`text-emphasis`) or weight, not italics.

**Chinese**

- Use `word-break: normal`; test `line-break: strict` for the same line-edge prohibitions.
- Region changes punctuation. Taiwan and Hong Kong center commas and full stops in the character
  square; Mainland Simplified sets them low at the left. Traditional text usually quotes with corner
  brackets, Simplified with curly quotes. Keep punctuation in the localized copy; a face set to the
  wrong locale draws it in the wrong place.
- Emphasis marks sit below horizontal Chinese text and above Japanese.

**Mixed runs**

- Space between a Hangul, kana, or Han run and a Latin word or number comes from the copy, the
  face, or `text-autospace`. Treat `text-autospace` and `text-spacing-trim` as enhancements the page
  must read without. Never put spaces inside identifiers, codes, or URLs.
- Hangul, kana, and Han faces rarely have italics, and browsers slant them synthetically. In CJK
  locales restyle `em` and `i` to normal style and use weight or emphasis marks.

**Vertical text.** Only when a world material or the medium calls for it, such as Japanese or
Traditional Chinese editorial pages. It needs a face with vertical forms, `writing-mode:
vertical-rl`, `text-combine-upright` for short numbers, and checks of punctuation, ruby, and Latin.

## Paragraphs and reading

**Measure**

- Latin continuous reading: 45 to 75 characters per line, about 65 in the middle. `ch` (the width
  of the zero) approximates it.
- Hangul, kana, and Han: nothing converts from the Latin count, because each character is wide, about
  0.85 to 1 em depending on the face. Use `ic` (the advance of 水 in the active face) with `em` as
  the fallback, and set the width by reading: narrow it until line returns come too often, widen it
  until finding the next line takes effort.
- Set measure per locale. Tables and data rows follow their own grid.

**Leading** (unitless, so it scales with size)

| Text | Start at | Raise it when |
|---|---|---|
| Latin body | 1.4 to 1.6 | the measure is long, the x-height large, or the face dark |
| Hangul, kana, Han body | 1.6 to 1.8 | the measure is long, the face dense or heavy, or ruby and emphasis marks appear |
| Latin display | about 1.0 to 1.15 | descenders, accents, or two lines touch |
| Hangul, kana, Han display | above the Latin display value, since every glyph fills the em | stacked lines touch |
| UI labels | what fits the component on one line | the label wraps; then use body leading |

A mixed-script paragraph takes the leading of the script with the fuller glyphs.

**Rhythm.** Paragraph spacing reads as more than line spacing and less than a section break.
Headings get more space above than below, so they belong to what follows. Mark paragraphs with an
indent or a gap, not both, unless the voice asks for both.

**Rag, justification, hyphenation**

- Set Latin ragged right on screens. Use `text-wrap: pretty` on body text and `text-wrap: balance`
  on short headings; never insert `<br>` to fix one width.
- Justified Latin needs hyphenation and a generous measure; without them it opens rivers.
- `hyphens: auto` needs the correct `lang` and a browser dictionary. Keep it off headings, names,
  and code; it does nothing for Hangul, kana, or Han.
- Never set `word-break: break-all` on prose; long URLs and identifiers get
  `overflow-wrap: anywhere`.

**Capitals.** Keep them for short Latin labels whose role is established, with a little added
tracking. Hangul, kana, and Han have no case, so a capital label has no counterpart there; use
weight or size, never tracking alone.

## Scale and responsive type

`tokens.type.scale.base_px` is the body size and `ratio` the step between sizes.

- **Base.** Start at the platform's default reading size. On the web that is 1rem, 16 CSS px unless
  the reader changed it; never shrink the root font size to make rem values smaller. Native apps use
  the platform's scalable text styles and units so the reader's text-size setting applies.
- **Ratio.** Choose a ratio whose adjacent steps look clearly different at the sizes used. Dense
  operate surfaces (high density dial) take a smaller ratio; sparse persuade surfaces and read
  openers (low density, higher variance) a larger one. Judge it on the rendered steps.
- **Steps.** The scale is a vocabulary: give each role the step it needs, skip the rest, and correct
  a step by eye where a face needs it. Adjacent roles differ by one clear lever: size, weight,
  contrast, or space.

**Fluid sizing**

- Map each role to a step per container or breakpoint, so a page title can drop a step on narrow
  screens without turning into body text. Give the steps in rem, so text settings still apply; a size
  driven only by the viewport ignores them.
- Change size by steps, not by interpolation: a `clamp()` size passes through values between steps,
  and lint's render layer reports those as `system.off-scale-value` at the widths render check
  captures. A `defaults` keep entry for that rule would waive every off-scale value, spacing and
  radius included, so it is not the way out.
- On narrow widths, shrink display and heading sizes first; keep body and labels at size.
- Leading stays unitless and does not vary with the viewport.
- With an `opsz` axis, keep `font-optical-sizing: auto` and check the rendered result.
- Small text uses regular weight or heavier, never light. Hangul, kana, and Han need slightly more
  size than Latin at small sizes, because their strokes are denser.

**Requirements**

- Text resizes to 200% without losing content or function.
- Content reflows at 320 CSS px width without scrolling in two directions, except content that
  needs two dimensions, such as data tables.
- Layout survives when the reader sets line height to 1.5 times the font size, paragraph spacing to
  2 times, letter spacing to 0.12 times, and word spacing to 0.16 times. So: no fixed heights around
  text, `min-block-size` rather than `height` on controls, and `overflow-wrap: anywhere` on long
  headings.
- Prices, conditions, consent, errors, and status are never truncated, and no text except a logo is
  set as an image.

## Numerals, data, and code

| Figures | Behavior | Use for |
|---|---|---|
| `proportional-nums` | each digit has its own width | prose, headings, dates in sentences |
| `tabular-nums` | every digit has one width | columns, timers, counters, compared prices |
| `lining-nums` | digits at cap height | UI and data |
| `oldstyle-nums` | digits with ascenders and descenders | editorial prose, when the face has them |

- Give the data role `font-variant-numeric: tabular-nums lining-nums`, then check the rendered
  output: the property does nothing when the face lacks the feature.
- Test signed values with a real minus sign, decimals, each locale's grouping separator, currency
  symbols (₩ ¥ € $), percent, and parentheses. End-align numeric columns; align on the decimal point
  when values have decimals.
- Keep the data role in the body or ui family when it has tabular figures; a separate number face
  adds seams in baseline, cap height, and punctuation. Hangul and Han faces draw their own digits:
  check them, or give the data role to the Latin companion (`scripts: [latn]`). Aligned numbers need
  tabular figures, not a monospaced font.

**Code**

- Use mono for source, identifiers, hashes, paths, logs, diffs, and fixed-column text. Mono on
  prose and headings is the `type-costume` card.
- Test 0 and O, 1, l, I and |, braces, quotes, operators, and a comment in each locale at the real
  size.
- Hangul or Han in comments falls back from the mono face to a locale face; choose that fallback on
  purpose. When CJK and Latin must line up in columns, as in terminal views or text tables, pick a
  mono whose CJK glyphs are exactly two Latin cells wide and test it in the real renderer; combining
  marks and emoji can still break columns.
- A width axis or a condensed face is still proportional.
- Decide ligatures explicitly: acceptable in an editor view when copying yields the source, off in
  diffs and logs.
- Code blocks scroll horizontally and never shrink to fit. Inline code breaks with
  `overflow-wrap: anywhere`.

## Display and expressive type

Display is a role, not a style. It is earned when:

- the surface mode is persuade or experience, or a read opener where the title is the content;
- it appears rarely, a few times per surface;
- a world material or the contract gives the voice: the subject's own lettering (stamped labels,
  signage, forms, packaging, a handwritten log), its period, or its tools.

Otherwise the heading role in the body family, varied by size, weight, width, or optical size, is the
better answer. Before searching, write the display job: where and how often it appears, its real
text in every locale, its size range and maximum lines, and what shows if the face fails to load.

**From material to form.** Describe what the material shows (contrast, stress, width, terminals,
weight, construction), then search for those traits: stamped metal points toward even strokes and
heavy block or flared terminals, an engraved scale toward fine, even lines and precise figures.
Latin genres (`serif`, `sans`, `slab`, `mono`, `display`, `hand`) are search vocabulary, not a
ranking. Hangul display subclasses are chosen the same way: `high-contrast`, `reverse-contrast`,
`tal-nemo` (syllables leave the square frame, so the line looks lively and informal), `full-square`
(syllables fill the frame, dense and poster-like), `terminal-ornament`, and the `hand` class for
brush and handwriting.

**Text and display drawings.** A text cut has sturdier strokes, a larger x-height, and looser spacing;
a display cut has finer detail, more contrast, and tighter spacing. A display cut breaks up at body
size, and an enlarged text cut looks blunt. Pin a variable family's instance in the implementation
tokens, because some default to a heavy display instance. Use a family's own expressive axis in one
authored moment with a fixed value, animated only under `tokens.motion.reduced_motion`. Tighten
display tracking only as far as the face tolerates at that size.

**Per-locale boundary.** Most Latin display faces have no Hangul, kana, or Han. For each locale in
`brief.locales`, decide between a display companion in that script (its own `display` entry) and that
locale's body face at a heading weight. Write the decision down; never let fallback choose. For
Hangul titles, check syllable density at heavy weights and any Latin names or numbers in the title.

Named defaults to walk here:

- `premium-serif`: a high-contrast or italic serif display chosen to look premium when nothing in the
  subject asks for it. Compare a subject-earned serif, a sans, and a mixed route on the real title;
  the same test applies to a high-contrast `bu-ri` display.
- `type-costume` (capitals or monospace worn for mood) and `label-above-heading` (a small tracked
  label before every heading).
- A title that fills the first screen fits only when the title is the content.

## Delivery that changes the choice

- **CJK payload.** Full Japanese, Chinese, and Hangul faces run to megabytes per weight. Load only
  the weights the roles name, and pick the lightest route that serves them: the `system-ui` generic
  for body and ui, which ships no file (named system faces go in its fallback stack, never in a web
  role of their own), with only the voice face delivered; files split into `unicode-range` chunks so
  the browser fetches only what a page uses; or a fixed subset, only for text that never changes,
  such as a display title. Never subset body or ui to today's copy; names, translations, and user
  input bring new characters. Subsetting modifies the font, and `lazuli lock` records that.
- **Fallback stacks.** Give each locale its own stack through `:lang()`: the chosen face, that
  locale's system faces, then the generic family. Never share one CJK order across `ko`, `ja`,
  `zh-Hans`, and `zh-Hant`; a Japanese page that falls back to a Chinese face shows Chinese forms.
  Record the stack with `--fallback` on `lazuli lock`, and view the page with the primary faces
  blocked: the fallback is part of the design.
- **Loading.** Keep text visible while fonts load, and give the fallback metric overrides
  (`size-adjust`, `ascent-override`, `descent-override`) so the swap does not reflow the page.
- **Real styles.** Load every weight and style the roles use; otherwise the browser synthesizes bold
  and slanted italics. Set `font-synthesis: none` only after the real faces exist.
- **Platforms.** A face must be deliverable on every platform in `brief.platform`; a system face on
  one operating system does not exist on another. For `email`, web fonts load only in some clients,
  so design in system stacks and treat any delivered face as an enhancement. A face with no licensed
  delivery path for the target platforms is not a candidate; `lazuli lock` records the path.
