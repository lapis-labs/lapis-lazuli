# Visual regression

## Sections

Read the section for the step you are on, by heading; the rest are other steps.

- The baseline: which earlier build to compare with and how to capture it
- Write down what may change first: the intended differences, written before opening a screenshot
- Hold the conditions: data, dates, fonts, and state held fixed so a difference is real
- Pair the captures: pairing viewports by width, theme, reduced motion, and browser chrome
- Compare in this order: from state and structure down to pixels
- Noise or change: telling rendering noise from a real change
- Mask only what cannot be held still: when a masked region is acceptable
- Coverage: the pairs the gate requires and the ones to say were not compared
- Korean text: checking rendered fonts before reading any difference in Hangul
- Classify and report: the class of each difference and what happens to it
- Worked example: the pottery page after a repair: one difference followed through to the report

This file backs the render step of the full set and the part of the report that says what changed
and what was not checked. Of the render, the gate (`../shared/release/GATE.md`) asks only that every
width and theme is in the extract; lint judges that render against the rules and the plan, and the
critic judges whether its choices are earned. Nothing compares it with the build that shipped
before. There is no diff command, no baseline input to any check, and no report field for the
result: you compare two render extracts and their screenshots by hand. The comparison never fixes
the design and never touches a gate input. Each change it finds goes to the maker and the plan.

| Question | Answered by | Recorded in |
|---|---|---|
| Is every width and dark capture there? | `release check` (`release.width-missing`, `release.theme-missing`) | `.lapis/release/<task>.json` |
| Does the render break a rule? | `slop lint`, render layer | `.lapis/lint/<task>.json` |
| Is each choice earned by this subject? | the critic | `.lapis/critic/<task>.json` |
| What changed since the last approved build, and was it meant? | you, by hand | your report to the user |

## The baseline

A baseline is a render extract of the build that last shipped or was approved, captured by
`render check` on a host that is ours. Use the `<task>-before` capture that the `lapis` skill makes
before a redesign and `ulm-maintain` makes before a change: `.lapis/renders/<task>-before.json`,
its screenshots in `.lapis/renders/<task>-before.shots/`, and, when it was linted then,
`.lapis/lint/<task>-before.json`.

When there is none, serve the previous build from the project's history on a host that is ours and
capture it at every width:

```bash
lapis-design render check http://127.0.0.1:8001/ --task <task>-before \
  --plan .lapis/plans/<task>.yaml
```

- Never capture a production site as the baseline. The rule for the build to ship holds for the
  baseline too, and `render check` refuses a public host unless given `--public`.
- Never write a baseline or a second capture to `.lapis/renders/<task>.json`. That file is the
  gate's render. A newer one makes the lint and critic reports stale (`release.input-stale`), and a
  capture of the wrong build would pass under the task's name. Use `--task <task>-before`, or
  `--out <path>` for any other capture.
- An approved mockup or a screenshot someone sent shows intent, but no check can measure it. Compare
  it by eye at the width it shows, and say so. A first release has no baseline; a reference profile
  from `lazuli ref capture` is someone else's page and never stands in for one.

## Write down what may change first

Before opening a screenshot, write the intended differences from the plan. Once you have seen a
result, it must not change what counts as success.

| Situation | Intended differences | Everything else |
|---|---|---|
| `mode: repair` | the parts the findings named, as the plan's changed part describes them | protected: must match the baseline |
| `mode: redesign` | what the plan says changes | what the plan says stays is protected; the rest is judged against the plan |
| `mode: create`, after an approved render | the plan's changes since that render | protected |
| a behavior-preserving change | none | every difference is explained or undone |

Add `key_copy` changes and each `proposed_design_changes` entry the user approved. A region the
plan does not mention is protected. If the list turns out wrong, the maker changes the plan with
the user; you do not widen it to fit the result.

## Hold the conditions

`render check` fixes most capture conditions itself. Hold the rest, or a difference may not be the
build's.

| Condition | Held by `render check` | What you do |
|---|---|---|
| widths, heights, pixel ratio 2, full-page screenshots | yes | nothing |
| color scheme per capture; reduced motion at 390 | yes | nothing |
| animations: finite ones stopped at the end of their current iteration, infinite ones paused at their start | yes | nothing |
| loading: network idle plus 1 s, a scroll pass in viewport steps, then 1 s of idle network, at most 10 s | yes | content arriving later is missing on either side; check `media.loaded` |
| browser build, operating system, installed fonts | not recorded | capture both sides on the same computer with the same lapis-design (`meta.extractor.version`) |
| the data the page shows | no: `render check` takes no stub | serve both builds with the same data |
| clock, random values, timers, video frames, embedded third-party content | no | find them with a noise run; hold them at the source or mask them |
| text signature key | per user | compare `text_sig` only when `meta.sig_key_id` matches |

A baseline captured on another computer or with another lapis-design version differs in ways the
build did not cause. Recapture it here when the old build can still be served; otherwise label the
comparison cross-environment and compare measured fields, not pixels. A field present on one side
only is not a change: a pass that cannot measure a field leaves it out.

**Noise run.** Before judging any difference, capture the build that ships a second time, into a
path the gate does not read:

```bash
lapis-design render check <url> --task <task> --out .lapis/renders/<task>-noise.json
```

Whatever differs between two captures of one build is noise under these conditions. It sets your
tolerances and your masks.

## Pair the captures

- Pair viewports by `width`, `theme`, `reduced_motion`, and `browser_chrome`, never by file name.
  Screenshot names start with a running index, so a capture is renamed when the page gains or
  loses a dark theme: with one, 768 light is `05-768-light`; without, it is `04-768-light` and `05`
  is 1440 light.
- The shots folder is not emptied between runs, so files from an earlier run can remain. Open only
  the files named in `viewports[].screenshot`, relative to the extract's folder.
- 390 has up to four captures. The reduced-motion capture must show everything without motion: a
  box that the build shows in its other 390 captures but not in its reduced one, while the
  baseline's reduced capture showed it, is a regression. The `browser_chrome` capture lays out the
  same page and counts only the top 664 px as the first viewport; compare what sits above 664 px,
  such as the main action, not its pixels a second time.
- A pair present on one side only is a finding. The one to catch is a lost dark theme: the
  baseline says `meta.dark_theme: true` and the build `false`. When the plan lists `dark` in
  `tokens.color.themes` or as a color role's `theme`, the gate blocks it as `release.theme-missing`; when the plan does not, only
  this comparison sees it, and it is a regression unless the plan says the dark theme was dropped.
- `render check` finds a dark theme at 390 by comparing the background and text colors of `html`,
  `body`, and the first four sections in the light and dark color schemes. A dark theme that only a
  control on the page switches on is never captured: when the plan lists `dark`, the gate blocks it
  as `release.theme-missing`; otherwise report it as not checked, as the gate does for
  `high-contrast`.

## Compare in this order

A large pixel difference can hide a small change that matters more, so read from state to pixels.

1. **Same page, same state.** The same `source.url`, the same data, images loaded on both sides. If
   the two show different states, fix the setup before reading anything else.
2. **Structure.** Box ids are hashes of DOM paths: tag and sibling index, or an id that is not
   generated. A wrapper added high in the tree changes every id below it with nothing visible
   changing, and a moved element reads as one removed and one added. Pair unmatched boxes by role,
   text, and position. Compare `derived.section_sequence` only within one pairing: its archetype
   cues depend on viewport height, so a section growing past 40% of the height stops reading as
   `cta` without changing. Even one page's 390 light and `browser_chrome` captures can name the same
   sections differently.
3. **Measured fields**, from the table below.
4. **Pixels**, region by region.
5. **Lint reports**, finding by finding.

| Field | A difference means | Look at |
|---|---|---|
| `scroll_width` above `width` | the page scrolls sideways | at 320 and 390 a requirement; lint's `layout.compact-overflow` blocks it already |
| `metrics.cls`, `metrics.shift_sources` | content moves while loading | boxes new in `shift_sources` |
| run `text` | copy changed | `content.key_copy` and the plan |
| `font.rendered`, `font.fallback` | another face painted | a fallback on one side only |
| `size_px`, `weight`, `line_height`, `lines` | type changed or rewrapped | `derived.type_fingerprint` for the page-wide view |
| `word_break`, `lang` | Korean breaking or glyph choice changed | the Korean section below |
| box `rect` | size or position changed | the first box that moved; boxes below moving by the same amount are consequences |
| box `style.background`, run `color`, `backdrop`, `states` | a color changed | the checks treat two colors within ΔE_OK 0.02 as one token |
| `a11y.focus_indicator`, `a11y.name` | focus became invisible, or a name changed | a lost focus indicator is a requirement regression, however few pixels it is |
| `media.loaded`, `media.phash` | an image failed or differs | differing bits out of 64; the rights checks count 6 or fewer as the same image resized or re-encoded |
| `derived.gaps` | spacing levels moved | inside group < between groups < between sections still holds |
| `derived.signature_found`, `signature_evidence` | the signature went missing or lost its marker | the plan's `layout.signature`; the rule is `layout.missing-signature` |
| `palette` | the page-wide color mix moved | eight clusters over the whole screenshot; a changed photo moves them, so read box and run colors instead |
| viewport `text_sig` | how much visible copy changed | the share of equal values estimates similarity, only with matching keys; our own renders carry `text`, so read that first |

**Pixels.** Screenshots are full-page at pixel ratio 2, so a box's region in the screenshot is its
`rect` times `dpr`; the capture crops images for `phash` the same way. Do not diff whole pages whose
heights differ: everything below the first height change shifts, and the diff reports the rest of
the page. Find the first box whose height changed, compare above it directly, and compare below it
region by region, each anchored on its paired box. Use a pixel diff with a tolerance per region,
counting pixels whose color moved more than a small step, and a perceptual hash for photographs. A
whole-page similarity score says nothing about where. Look at every differing region yourself; the
count locates it and never decides it.

**Lint reports.** Compare only findings with `layer: render`: the plan and source layers read
today's plan and source for both sides. Each render finding merges every capture where the same
thing was seen: `location.viewport` is the first of them, and `observed` ends with the list of
captures. Pair findings by `rule_id`, `location.box`, and the start of `observed`, then compare the
capture lists. Use the baseline's own lint report only when it was made with the same `--mode`,
`--plan`, and `--lock` as the gate's run; otherwise lint the baseline extract with those options,
writing to `-o .lapis/lint/<task>-before.json`, never to the gate's report. A finding new in the build is a candidate
regression. A finding gone from the build counts as fixed only if no `skipped` finding took its
place. Never give the baseline to lint as `--ref`: that option is for the references the plan
borrows from, and the rules that read it skip a render extract, so nothing would be compared.

## Noise or change

| You see | Usually | Before calling it |
|---|---|---|
| speckle along glyph edges across the page, measured fields equal | rendering noise from another computer or browser build | the noise run shows it too, or recapture the baseline here |
| everything below one point moved by the same amount | one height change above it | the first box whose `rect.h` changed; judge that box, and call the rest its consequence |
| text in another face | a fallback, or a font still loading | `font.rendered` and `font.fallback` on both sides |
| a Korean line more at 320 | a width change moving a whole word under `keep-all` | `lines`, `word_break`, and the box's `rect.w` on both sides |
| an image region differs | new content, a crop change, or a failed load | `media.loaded`, the differing bits |
| a date, count, or clip that differs between captures | dynamic content | it differs in the noise run too; hold it or mask it |
| a section's archetype label changed | a height crossing a cue | the section's `rect`, not its label |

**Tolerances are judgement.** No pixel threshold is right for every page. Set each one from the
noise run, per region, just above what two captures of one build differ by. Keep controls, focus
indicators, prices, and text near zero: a share that is harmless across a photograph can hide a
whole button. Never raise a tolerance until a difference disappears. Record each tolerance with its
region, its reason, and what it could hide. The size of a difference is not its severity: a few
pixels can be a lost focus indicator, and a large area can be the approved new section.

## Mask only what cannot be held still

- Hold a moving source still first: serve both builds the same data, the same fixed dates, the
  same images.
- Mask only a region the noise run shows moving, and only the smallest box that covers it. Record
  the box id, width, theme, reason, and what the mask hides.
- Never mask the task's risk. On the pottery page, the prices, the reserve action (`예약하기`), the
  piece photographs, and the firing log row, which is the signature, stay unmasked.
- A masked region is not checked. List it under what was not checked; its behavior belongs to the
  behavior session, not to pixels.

## Coverage

Compare every pair the gate requires, light at 320, 390, 768, and 1440 and dark at 390, 768, and
1440 when the page has a dark theme, plus the two extra 390 captures. Start where regressions
usually land: 320 for reflow and Korean wrapping, 390 because most visits are on phones, then dark,
then the wider widths. Compare dark on its own: a light token changed without its dark counterpart,
or a new element with a fixed light background, shows only there.

The screenshots show one URL at rest. States reached by interaction belong to the behavior session;
hover, focus, and active appear only as measured values, the colors in `states` and
`a11y.focus_indicator`. Other routes and a `high-contrast` theme are not captured. Say so under what
was not checked.

## Korean text

- Check `font.rendered` on every Hangul run before reading any difference in Korean text. A
  fallback face has other advance widths and line heights, so a run gains or loses a line and every
  box below it moves. A baseline from a computer with other Korean faces installed can fall back
  where this one does not; recapture it here.
- With `word_break: keep-all`, Korean breaks only at spaces and punctuation, so a word moves whole.
  A few pixels of padding at 320 can add a line to a heading and push the page down. Compare `lines`
  and the box's `rect.w`, and trace the width change to its cause.
- A run whose `word_break` changed from `keep-all` to `normal` now breaks inside words, sometimes at
  the same line count. Lint reports the missing `keep-all` (`type.ko.keep-all-missing`); the
  comparison adds that it was there before.
- A changed `lang` can select other glyph forms or another face through per-locale font rules.
  Compare it along with `font.rendered`.

## Classify and report

| Class | Meaning | What happens |
|---|---|---|
| intended | on the list you wrote first, and it meets the plan | note it |
| consequence | follows from an intended change, such as boxes moving below a taller section | note it with its cause |
| noise | differs between two captures of one build | note the tolerance or mask |
| unexplained | not on the list, and its effect is not yet known | the maker explains it: the plan records it, or the code restores it |
| regression | breaks a requirement, something the plan protects, or `DESIGN.md` | the maker fixes it, and the full set runs again |
| trade-off | improves one protected thing and weakens another | the user decides with the maker |
| not checked | masked, not captured, or not comparable | list it with the reason |

An unexplained difference is not automatically a regression, and never automatically accepted.

Only `release check` writes the gate report; never add comparison results to it or edit a finding.
No contract field holds a baseline or an accepted difference yet, so the record goes in your report:

```text
Baseline: <path>, <which build>, <computer and lapis-design version>
Build: .lapis/renders/<task>.json
Pairs compared: <width/theme/reduced/chrome>; missing on one side: <...>
Noise run: <clean, or the regions that moved>; masks and tolerances: <box, reason, what it hides>
Intended: <...>   Consequences: <...>
Unexplained: <...>   Regressions: <...>
Not checked: <...>
```

Start with the gate's verdict as its report states it, then one line on the comparison. An open
regression means the maker has work before release, whatever the gate said. A change that alters
the design goes into the plan through the maker, and into `proposed_design_changes`, for the user
to approve, when it departs from `DESIGN.md`. Never replace the baseline to make a difference go
away; the next baseline is a capture of the build that shipped, after the user accepted its
differences.

## Worked example: the pottery page after a repair

The critic found that the kiln temperature curve, one of the world materials, never appears. The
repair plan (`mode: repair`) adds the curve to the firing-log section at 768 and 1440 and tightens
the log rows at 390. Intended: the firing-log section at 390, 768, and 1440; everything else is
protected. The baseline is the approved render, `.lapis/renders/kiln-shop-landing-before.json`,
captured on this computer. The noise run of the new build is clean.

The baseline has nine captures and the build six, because the build's `meta.dark_theme` is
`false`. Paired by fields, the six light captures line up, although index `03` is the
`browser_chrome` capture in the build and the reduced-motion one in the baseline.

| Pair | Observed | Class |
|---|---|---|
| 1440 and 768 light | firing-log section taller with a new media box; every box below lower by the same amount, otherwise equal | intended, and its consequence |
| 390 light | log rows 4 px closer; the section 12 px shorter, and everything below 12 px higher | intended, and its consequence |
| 320 light | the headline `9월 소성분, 스물네 점이 나왔어요` goes from 2 to 3 `lines`, `keep-all` on both sides; its box narrows from 280 to 272 px because the shared page container gained 4 px of padding on each side | unexplained |
| dark at 390, 768, 1440 | absent: the baseline offered a dark theme, the build does not, and the plan lists `dark` | regression; the gate blocks it too |
| piece photographs | 0 to 1 of 64 hash bits differ | unchanged |

`release check` exits 1 with `release.theme-missing`, because the plan lists `dark` and the build
records no dark theme. The report reads: the page does not ship; the dark theme the plan protects is
gone, and, found only by the comparison, the 320 headline now wraps to three lines, which the plan
does not explain. The maker restores the dark styles, either returns the padding or records the new wrapping
in the plan, and reruns the full set. You fix neither.
