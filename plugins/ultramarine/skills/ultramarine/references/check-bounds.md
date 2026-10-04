# Check bounds

## Sections

Read the section for the finding being interpreted, by heading; the rest are other findings.

- Motion at rest and under the reduced preference: what the motion checks see at rest and under reduced motion
- Motion inventory and scrolling: what the motion inventory, animation-package, and scroll probes can and cannot reach
- Data-region extraction and contrast: the contrast minimums, compact access and controls, long rendered lists
- Status results and form recovery: announced results, timed work, duplicate commits, and urgency or scarcity claims
- Related wording boundaries: how urgency and quoted-proof wording is recognized, and where recognition stops

Read this when interpreting a motion, data-region, or form finding. These are observation boundaries,
not values to design toward. A missing match can mean that the surface was outside the probe's reach.
Use the rule's evidence and coverage before deciding whether to repair. Names and attributes describe
real content; changing them to influence recognition does not settle the underlying requirement.

The generating references keep the decision and what is read; this reference owns the numerical
bounds and recognition vocabulary. The executable definitions remain authoritative:
`../shared/slop/rules.yaml` declares detector parameters, and the implementation applies them.
The implementation paths below are relative to `cli/lapis_design/` in the source checkout.

## Motion at rest and under the reduced preference

| Decision being reviewed | Plan field | Check and input |
|---|---|---|
| Keep the reduced composition useful | `tokens.motion.reduced_motion`, `tokens.motion.principles` | `motion.reduced-motion-missing` reads moving boxes in reduced-preference behavior contexts |
| Give automatic movement a reachable control | `tokens.motion.principles` | `motion.uncontrolled-marquee` reads automatic movement and pause-control observations |
| Keep content available before scrolling | `tokens.motion.principles` | `motion.scroll-gated-content` reads hidden-at-rest and reveal observations |

The render matrix includes an extra **390 px**, light-theme reduced-preference capture. Motion
inventory reads ordinary captures instead of comparing that pair; stills do not measure timing.

The motion probe observes **5,000 ms** after loading, in each base context and a reduced-preference
twin. It samples at **100 ms** intervals. Position changes exceeding **0.5 px**, changed transforms,
and opacity changes exceeding **0.03** can establish movement when a running animation owns the box.
Pixel changes also allow media movement to be recorded. The resulting kinds are `transform`,
`opacity`, `scroll-linked`, `video`, `canvas`, and `other`. A moving fade is spatial motion, not a
stationary fade. `motion.reduced-motion-missing` reads nonessential `transform`, `scroll-linked`,
`video`, and `canvas`; it does not flag `opacity` or `other` merely because they changed.

A canvas counts as content when it is within a `figure`, has role `img`, `figure`, or `application`
with a name, or its name matches the content pattern. The pattern reads whole English words
`chart`, `graph`, `plot`, `map`, `visualization`, `visualisation`, or `diagram`, with optional plural
`s`, and Korean `차트`, `그래프`, `지도`, `시각화`, or `도표`. Names come from `aria-label`,
`aria-labelledby`, and `title`. An `aria-hidden` ancestor or another element covering its center
makes the canvas decorative regardless of that presentation. A video never counts as essential in
this no-input window. These observations classify presentation, not whether motion is necessary.

Automatic movement is followed beyond the initial window, up to **60 s** after load. The marquee
rule requires a control when recorded movement lasts **more than 5 s**. The control must be enabled,
keyboard-reachable, visible, and either a sibling button or a control whose `aria-controls` names
that element. Its accessible name matches whole English `pause` or `stop`, or Korean
`일시정지`, `일시 정지`, `일시중지`, `일시 중지`, `정지`, `중지`, `멈춤`, or `멈추기`.
A control's presence does not prove its playback action works.

For hidden content below the first viewport, the probe reads opacity **below 0.05**, hidden
visibility, or a clip-path beginning `inset(50%` or `inset(100%`. It scrolls each candidate into view
and looks for opacity **above 0.9**, visible visibility, and removal of those clipping patterns,
for up to **5,000 ms**, checking every **100 ms**. The rule reports the original hidden state;
there is no allowed reveal-delay threshold that turns it into an acceptable enhancement.

Sources: `behavior_check/probes/motion.py` (`FRAME`, `HIDDEN`, `_measure`, `_auto`, `_pause_control`,
`_scroll_reveal`), `behavior_check/probes/_decision.py` (`PAUSE`), and
`lint/detectors/behavior.py` (`reduced_motion_respected`). Interaction-triggered transitions,
animated graphic child shapes, focus preservation, mid-session preference changes, and flashing
remain outside these motion observations.

## Motion inventory and scrolling

| Decision being reviewed | Plan field | Check and input |
|---|---|---|
| Scope repetition and easing to their purpose | `direction.dials.motion`, `tokens.motion.principles` | Motion inventory rules read source patterns or computed animation records, not purpose |
| Name the properties a state change owns | `tokens.motion.principles` | `motion.transition-all` and `motion.layout-property-animation` read declarations and animation observations |
| Preserve native scrolling | `tokens.motion.principles`, `flows[]` | `ux.scroll-hijack` reads distances, blocked input, and snapping |

| Rule | Executable boundary |
|---|---|
| `motion.pulse-without-status` | Source patterns: `animate-pulse`, `animate-ping`. Render: the larger box dimension is at most **32 px**; a positive-duration, infinite, non-stepped animation touches `opacity`, `transform`, `scale`, `box-shadow`, or `filter` |
| `motion.decorative-cursor` | Source patterns: `@keyframes` followed by `blink`, or `animate-blink`. Render: positive-duration infinite animation that is stepped or whose name contains `blink`, `caret`, or `cursor` |
| `motion.bounce-default` | Source recognizes `animate-bounce`, `elastic`, `back.in`, `back.out`, `back.inOut`, and certain out-of-range cubic-bezier declarations. Render checks cubic-bezier vertical controls or linear-easing output values outside **[0, 1]**, on **more than 0.5** of boxes with positive-duration animations or transitions |
| `motion.transition-all` | Source: `transition: all` or `transition-all`. Render: positive-duration transition with property `all` |
| `motion.layout-property-animation` | Source transition pattern names `width`, `height`, `top`, `left`, `right`, `bottom`, `margin`, or `padding`. Render additionally reads individual margin and padding sides in transitions and keyframes. Behavior records layout-property animations lasting **at least 50 ms** whose ending rectangle differs from the starting one |
| `motion.hover-zoom-everything` | Fine-pointer behavior: **more than 0.8** of visible `img` and `video` boxes have a changed computed transform after hover; the hover observation waits **180 ms** |
| `motion.ambient-loops` | Render: **more than 1** box has a positive-duration infinite animation |
| `ux.scroll-hijack` | Actual/native distance ratio **below 0.5** or **above 2.0**, blocked movement, or section snapping. The probe sends **3** inputs of each available kind: wheel, Space, ArrowDown, and touch in coarse-pointer contexts |

Render movement-at-rest evidence samples a **2,000 ms** no-input interval after loading and its
initial wait; it is not a measurement from navigation time zero. The sampler is
`render/fields/interaction.py` (`observe_rest`).

Source patterns are not equivalent to computed animation behavior. A source motion lead needs the
corresponding rendered or behavior observation; lack of that observation is not a runtime pass.
Neither preset recognition nor a numerical boundary establishes choreography quality.

Sources: `../shared/slop/rules.yaml`, `lint/detectors/render_layout.py` (`_motion_render`,
`_motion_behavior`, `_overshoots`), `behavior_check/probes/motion.py` (`_hover_media`), and
`behavior_check/probes/scroll.py`, and `behavior_check/settle.py`. `code.continuous-value-in-state`
reads state-hook setter calls in handlers for `mousemove`, `pointermove`, `touchmove`, `scroll`,
`wheel`, `drag`, `dragover`, or `pointerrawupdate`. `code.animation-package-mismatch` checks imports
against dependencies. Neither establishes runtime cost or interaction suitability.

## Data-region extraction and contrast

| Decision being reviewed | Plan field | Check and input |
|---|---|---|
| Separate text, action, and data colors | `tokens.color.roles`, `tokens.color.data_scales` | `color.text-contrast` reads text and backdrop; `color.competing-accents` reads palette evidence and declared data colors |
| Preserve compact access and controls | `layout.procedure.responsive` | `layout.compact-overflow`, `component.small-target`, and `layout.shrunk-desktop` read geometry |
| Avoid a large unbounded rendered list | `layout.procedure.density_and_checks` | `code.unvirtualized-list` reads direct child counts, not the data's meaning |

For normal text the minimum ratio is **4.5:1**; the large-text minimum is **3:1**. The detector
uses the unrounded result. Large text is at least **24 CSS px**, or at least **18.66 CSS px**
with weight at least **700**. The rule requests light and dark themes and rest, hover, and focus
states, excluding disabled controls. It reads the weakest available backdrop sample, including
captured gradient and image samples. Vector text is measured from CSS text color, not a separate
fill. No graphic-mark contrast or color-vision simulation follows from a text-contrast pass.

A pointer target whose width or height is **below 24 px** is a candidate for
`component.small-target`; the detector also reads space around it and neighboring targets.
`layout.compact-overflow` requests **320** and **390 px** captures. `layout.shrunk-desktop`
compares **390** with **1440 px**. `layout.card-everything` reads whether cards enclose **more than
0.8** of measured content area. `code.unvirtualized-list` reports **more than 500** direct children
in a scrolling box or a list taller than **3 viewport heights**. Nested table rows are not direct
children of the table and are therefore outside that count.

The palette extraction can recognize data from table cells, whole class or id words `chart`,
`graph`, `plot`, and `sparkline`, or the presentation/structure of vector and canvas boxes. Class
and id words are split at whitespace, hyphens, underscores, and case changes, not arbitrary
substrings. A vector or canvas candidate must be at least **48 CSS px** on its shorter side.
Presentation requires first role token `img`, `figure`, or `graphics-document` and a name containing
whole English `chart`, `graph`, `plot`, `visualization`, or `visualisation` with optional plural,
or Korean `차트` or `그래프`. Vector structure can instead supply **3 sibling shapes** of one type
and **2 nonempty text labels**. Interaction and status role hints take precedence over data.
This classification alone does not exempt a hue from competing-accent analysis: declared data
colors in the plan are also read.

Sources: `lint/detectors/render_type.py` (`is_large`, `contrast_wcag`, `target_size`),
`lint/detectors/render_layout.py`, `render/fields/palette.py`, and `../shared/slop/rules.yaml`.
There is no automated comparison of chart and table values, axis honesty, uncertainty, or the
usefulness of a summary. For a river-level view, inspect the plotted reference against its table;
for a seed inventory, check that filtered totals and the export name the same selection. Those
checks are manual and do not acquire a rule verdict from the examples.

## Status results and form recovery

| Decision being reviewed | Plan field | Check and input |
|---|---|---|
| Announce a meaningful result | `content.key_copy`, `flows[].done` | `ux.status-not-announced` reads new result text, announcements, and focus |
| Keep timed work recoverable | `flows[]`, `claims.unresolved` | `ux.timeout-without-warning` reads the behavior session's time limits |
| Prevent duplicate commitment | `flows[].kind` | `ux.duplicate-submit` reads repeated activation and commit outcomes |

Outside status, alert, live, output, toast, or snackbar regions, status recognition reads only text
newly gained after an action. English result words are `saved`, `added`, `removed`, `sent`,
`reserved`, `copied`, `updated`, `applied`, `deleted`, `booked`, and `submitted`. Korean stems are
`저장`, `추가`, `삭제`, `전송`, `발송`, `복사`, `적용`, `예약`, `신청`, `등록`, `변경`, `취소`,
`해지`, and `결제`, followed by optional particles and a completion form (`했`, `하였`, `됐`,
`되었`, `완료`); `담았`, `담겼`, `보냈`, `지웠`, and `비웠` also match.

Counts read `results`, `items`, `matches`, their singular forms and `no` forms; `cart`, `basket`,
or `bag` within **24 characters** of a number also count. Korean reads a result count with `건`,
`개`, `명`, or `곳`, `총` or `모두` before a count, an absent-result phrase, or `장바구니` within
**16 characters** of a number. A changed measurement alone is not a result. Any announcement
from the same action, or focus reaching a changed status box, prevents a controls finding; this
is not proof that every result was announced. Commit and state outcomes have their own observations.

Time limits **over 72,000 s** are excluded by the detector; a recorded turn-off or substantial
adjustment also excludes the limit. Otherwise it needs a warning at least **20 s** before expiry
and at least **10** successful simple extensions. The probe regards an adjustment to at least
**10 times** the current limit as substantial and watches up to **20 hours** of controlled time.
The commit probe repeats activation **80 ms** apart; this is an observation interval, not a debounce
recommendation. Form purpose is recognized from its id, accessible label, and first **150 characters**
of text using English patterns for sign-in, signup, checkout, reservation, search, contact,
settings, and consent. Disabled-submit explanation recognition is English-only: `required`,
`must`, `please`, `missing`, `complete`, `enter`, or `fill`.
Sign-in alternatives recognize `passkey`, `magic link`, `other method`, and `sign in with`.
Cognitive-test recognition reads `puzzle` or `captcha`, a transcription stem, image-selection or
object-recognition wording, personal-question wording, and security-question or maiden-name wording.
Repeated-entry shortcuts read `same as`, `copy from`, or `use previous`; these explanation patterns
are English-only too.

Sources: `behavior_check/probes/_decision.py` (`STATUS_*`), `behavior_check/driver.py`,
`lint/detectors/behavior.py` (`status_announcement`, `time_limit`), and
`behavior_check/probes/forms.py`, `commits.py`, and `time_limits.py`. Recognition of form purpose
is not field validation. The flow driver leaves optional, bulk, promotional, and switch choices
untouched; blocked paths stay unexercised. Screen-reader speech, external identity services, and
address lookups are not observed by these probes.

## Related wording boundaries

| Decision being reviewed | Plan field | Check and input |
|---|---|---|
| State genuine time and scarcity | `content.key_copy`, `claims.declared` | `ux.false-urgency` reads clock, reload, fresh-profile, expiry, and backing observations; backing comes from the stub |
| Trace quoted proof | `content.key_copy`, `claims.declared` | `copy.fabricated-proof` reads quotations against plan support, not whether the attributed person exists |

Urgency recognition is not a ban on numbers or time wording. It reads a box of at most **180
characters**. For a day or hour span to become time left, qualifying countdown or deadline wording
must occur within **40 characters**, without an intervening sentence boundary. A hold or a combined
day-and-hour count can qualify without that wording. Absolute dates and colon-form clocks have
separate recognition paths. A stock count does not turn a nearby service duration into time left.
Payment, cancellation, and refund periods stay terms unless nearby wording actually says time is
running out. A bare clock becomes a tentative countdown only when its value decreases; a clock
qualified as time of day stays a clock. Retrospective activity windows are not countdowns.
Unbacked checks apply to `stock`, `demand`, and `activity`, not every recognized time claim.
Hold expiry does not use the ordinary countdown-expiry failure condition.
See `behavior_check/probes/urgency.py` and `lint/detectors/behavior.py` (`urgency_integrity`).

A quotation opening a text run is not automatically safe because it is a heading or in a dialog.
A standalone or attributed quotation remains a proof lead; a testimonial section always remains
one. Interface text quoting an object inside a continuing sentence can be excluded. Buttons and
inputs are excluded unless attributed or inside a testimonial section. Attribution after the
closing mark is bounded to **10 tokens** and must have the relevant name shape when separated by
whitespace. Speech verbs are `says`, `said`, `writes`, and `wrote`; Korean name-suffix recognition
reads **2–4 Hangul syllables** followed by `님`, `고객님`, or `씨`. These patterns distinguish a
quoted object from a speaker claim; they are not a license to fabricate either. See
`lint/detectors/copy.py` (`_after_quotation`, `_reads_as_quote`, `_fabricated_proof`).
