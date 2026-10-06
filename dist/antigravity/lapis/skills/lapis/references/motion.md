# Motion

## Sections

Read the section a motion decision needs, by heading; the rest are other decisions.

- What motion is for: the job each moving element has, and what to remove when it has none
- Motion as a system: state change and control feedback together, continuity, timing scale, cancellation, and playback
- Timing and easing: durations, easing, and distance by purpose
- Interruption and choreography: stable states, legal transitions, interruption, sequencing
- Scroll, navigation, and transitions: scroll and route enhancement that still works with animation off
- Reduced motion: what `respect` covers, each effect's branch, and optional product motion modes
- Choosing a layer and delivering authored motion: native or library animation, and delivering authored moments
- What the checks read: which motion rules read what, and what they cannot see
- Handoff to lps-system: the purposes, durations, and curve roles to pass on

This file backs the plan's motion decisions: the motion dial in `direction.dials`, and `tokens.motion`,
where `respect` is the only accepted value for `reduced_motion` and `principles` holds one string per decision. `lps-system`
turns the principles into duration, easing, and distance tokens; this file decides what they say, what
happens around them, and what the checks can tell you.

```yaml
direction:
  dials: { variance: 5, motion: 2, density: 4 }
tokens:
  motion:
    reduced_motion: respect      # the only value the schema accepts
    principles:                  # one string per purpose: job, timing, interruption, reduced branch
      - "dial 2, feedback only: the reserve control acknowledges a press by color in 120 ms; unchanged when reduced"
      - "sheet: enters in 240 ms, decelerating; dismissal acts at once; reduced: appears directly"
```

## What motion is for

Give every moving element a job, and take the first that explains it: **feedback** (the input registered),
**orientation** (where a surface came from or went), **continuity** (the same object before and after a
change), **expression** (character that belongs to the subject). An effect with no job comes out, and so
does motion that only performs liveness. A color change often does what a transform would, and a line of
status text does what both would; status, meaning, and completion stay understandable without motion.

| Dial | The plan holds |
|---|---|
| 1-3 | Feedback only: press, focus, a state change, the entry of one overlay. No entrance staging, no scroll-linked effect |
| 4-6 | Transitions that explain a change: an overlay related to its origin, one region replacing another, a layout change that would lose identity. Nothing moves only to be seen: a fade-up on every section as it scrolls in explains no change, so a marketing page at 6 does not owe one |
| 7-10 | Authored moments made for the subject. Each has a complete static composition, a pause or skip, and a reduced branch, and reading or operating never waits for a scene |

Pick the band the surface needs, compare it with the band next to it on one real interaction and record the comparison in `explorations` (decision `motion`), then write what it means here as a `principles` line, as the example does.
The dial is a proposal that the brief and an existing design override, and no value relaxes the
reduced-motion requirement, status clarity, or interruption. An `operate` surface values latency over
staging and gives data no entrance animation; on a `read` surface, motion between the reader and the text
is subtraction. On the pottery page at dial 2, the firing log's temperature curve, drawn as the page
scrolls, was proposed and rejected; at 7 or more it would be the page's one authored moment, complete at
rest and whole under reduced motion.

Take the character of motion from how the subject's own things move: a drawer, a page turned, a valve
opened, a curve drawn by a recorder. A ready-made package (elastic on every control, a fade-up on every
section, a pulsing dot for "live") is the `ambient-motion` and `global-habit-values` cards: reject it with
a route, or keep it in `defaults` with a reason.

## Motion as a system

Start from the stable states and the input that changes them, not from one entrance effect reused
across the page. Observe the changed content and the accepting control as one unit: the semantic
state commits at input, the control acknowledges that input, and motion explains continuity or
expression without delaying reading, focus, or the outcome. A content fade with no control response
is not a complete interaction system; a responsive control without meaningful content is not proof
of the product's claim.

Keep a compact table in the plan's motion principles or linked design notes:

| Purpose/state transition | Content and control response | Duration/curve/distance role | Interruption and reduced branch | Playback evidence |
|---|---|---|---|---|
| Feedback: idle → pressed/selected | accepting control changes immediately; visible selected state remains | short feedback token; state-change curve; movement only when useful | repeated input keeps latest selection; reduced retains the cue | press, keyboard select, and repeat |
| Continuity: record A → record B | marker and related content explain the same object's change | transition token; enter/exit/standard curve by phase; distance tied to relation | cancel/retarget from current presentation; reduced changes state directly | reverse midway, then show the stable result |
| Expression: requested authored sequence | subject-specific moment; its controls, pause/skip and useful resting frame remain available | authored duration/curve; no universal fade-up preset | cancel/skip without stale state; reduced uses a complete static composition | normal playback, interruption, and reduced playback |

The rows are examples, not required effects. Choose the purposes the actual surface needs. Use a
small related easing/duration scale rather than independently inventing timings on each element;
keep input acknowledgement shorter than a region transition unless this interaction supplies a
reason. Judge the scale and choreography by actual playback on phone and desktop, not a timing
number, a still screenshot, or a `prefers-reduced-motion` declaration. For each implemented candidate
record what happened under quick repeated/reversed input, cancellation, hidden-tab stop where
relevant, and reduced motion. Only that observed alternative counts in the comparison.

## Timing and easing

Durations are proposals until a trace shows them running, and none of these ranges is a perceptual law.
Frame rate, distance, size, input method, and the product's character move them.

| Change | Start in | Note |
|---|---|---|
| press, hover, small state change | 100-200 ms | acknowledge first |
| popover, tooltip, small enter or exit | 150-250 ms | an exit can run shorter when it clears the way |
| dialogs, sheets, route regions | 200-300 ms | focus and dismissal never wait for it |
| large layout change | 300-500 ms | only when the continuity explains something |
| authored moment | case by case | skippable, or never blocking |

An arrival decelerates, so most of its travel happens early; a departure accelerates; a state change takes
a balanced curve; `linear` fits progress tied to time or input. Name curves by role (enter, exit, standard)
in `principles`, author the control points for this subject, and judge them on the rendered result.
Keep overshoot deliberate rather than inheriting it from a preset. Spring and bounce can fit a physical
release or a playful subject, but not every routine action. Record an earned exception to
`motion.bounce-default` in `defaults`, with its reason.

- **Transition or keyframes.** A transition takes one state to the next when the person acts; keyframes
  suit a bounded authored sequence. Name every property you animate: `transition: all` animates whatever a
  later edit adds (`motion.transition-all`).
- **Properties.** Reach for `transform` and `opacity` first. Width, height, inset, margin, and padding
  trigger layout: use them for a reason, or through a tool that measures and then transforms
  (`motion.layout-property-animation`). That is a performance preference, not a ban, and a transform never
  makes the visual order differ from the reading and keyboard order.
- **Continuous input.** Pointer and scroll values drive compositor-friendly properties or refs, never
  component state on every event (`code.continuous-value-in-state`).

## Interruption and choreography

Write the stable states and the legal transitions before any keyframe. The semantic state changes when the
person acts; an opening or closing phase belongs to the animation, not the domain. For an interaction that
does more than give feedback, answer in one `principles` sentence: when the state commits (at the input,
never at the end of a transition); what a repeated or reversed input does; where focus goes, and whether
content on its way out can still take it; what is announced; what changes under reduced motion; what stays
usable if the animation never runs.

**Latest intent wins** for routine controls and direct manipulation. A disclosure reopened mid-exit turns
back toward open from where it is. Three quick tab selections end on the third. A sheet dismissed during
its entrance starts leaving at once. Back is never queued behind a route flourish. Retarget from the value
on screen when the destination changes, reverse when the motion is reversible, cut to the end state when
continuity adds nothing, and queue only a rare authored narrative. A `transitionend` callback or an
animation promise never holds the only copy of a state change: a cancelled, reduced, hidden-tab, or
zero-duration animation may never complete.

**Focus follows meaning.** Make the destination accessible and place focus before its entrance; on
closing, return focus and remove departing content from input before its optional exit. Cancellation
must still reach the stable state. Neither dismissal nor an error announcement waits for animation.

**Sequence** only when the order explains cause or grouping. A stagger of 50-100 ms can group a small set;
on a long list it makes later content wait, so move the group as one. At 7 or more, allow one authored
moment per ordinary surface; only a piece where motion is the medium has several. A gesture starts from the
current position and velocity and has a button or keyboard route.

**Feedback.** A pressed state acknowledges accepted input, not completion. Respond at the control
that accepted it. A single-action surface may respond as a whole; a card with open, save, and
dismiss actions responds only at the invoked target. If scaling a wide row breaks shared
alignment, compare color or a local content response instead. Do not multiply parent and child
contractions. Keep selection, warning, and on/off cues intact; under reduced motion retain a
visible state cue without travel or scale. Use this comparison in the motion `explorations`.

| What is known | Feedback to compare |
|---|---|
| a local change has committed | the new state itself |
| the wait is uncertain | local status, not a page takeover |
| measured work has a total | determinate progress with its unit |
| incoming structure is known | a layout-shaped placeholder |
| old content remains valid during refresh | keep it, labeled as updating |
| work can continue elsewhere | durable status and a safe way away |

Choose against real latency and consequence, not a universal indicator delay. Keep cues bounded
by the wait, including the reduced branch. Failure preserves work and exposes recovery;
animation time never determines completion, and progress is never invented.

## Scroll, navigation, and transitions

Start from a page that works with every animation off: real links, headings and landmarks, fragment ids,
scrolling owned by the user agent, back and forward that restore position, content visible before any
animation script runs, and sticky elements that never cover a focused or targeted element. Add continuity
where the engines and the reduced preference allow. What history keeps and what a route change does with
title and focus belong to the `lps-ux` navigation decisions; a transition adds none of them.

**No scroll hijack.** Never replace wheel or touch distance with a custom camera or a fixed-duration tween:
it breaks learned acceleration, platform settings, and assistive input. A cinematic piece takes explicit,
bounded controls (a step control, a play button). Snap only step-based panes and bounded carousels;
free-form content gets proximity at most, never mandatory snapping (`ux.scroll-hijack`). Keep a sticky bar off
a target with `scroll-padding` and `scroll-margin`, keep the browser's scroll restoration (a returned-to
list shows its earlier position at once), and enable smooth scrolling only under
`prefers-reduced-motion: no-preference`.

**Nothing hidden at rest.** An enhancement starts from the usable final state. Base styles show the
content, and motion arrives only inside both guards:

```css
.log-row { transform: none; opacity: 1; }

@supports (animation-timeline: view()) {
  @media (prefers-reduced-motion: no-preference) {
    .log-row {
      animation: settle linear both;
      animation-timeline: view();        /* after the shorthand, which resets it */
      animation-range: entry 0% cover 30%;
    }
  }
}

@keyframes settle {
  from { opacity: 0.4; transform: translateY(0.6rem); }
  to   { opacity: 1;   transform: none; }
}
```

The content stays visible when the feature is missing, a stylesheet or script fails, or reduced motion is
on. Start keyframes from a readable state: an element below the first viewport that begins nearly invisible
is what `motion.scroll-gated-content` reports. Tie scroll to reading progress or a restrained cue on
nonessential content, never to hiding essential copy. A pinned sequence earns its place by relating to
the content, such as a legend beside its chart, and releases before it covers later content.

**View transitions** enhance an update that already works. Guard support and the reduced preference;
navigation, focus, history, and failure handling remain the application's responsibility.

## Reduced motion

`respect` is the only accepted value for `reduced_motion`, never traded for the dial, the brief, or a signature. It covers
every shipped effect that is not essential, meaning motion that is itself the content, such as a chart
drawn from live data. Decide the reduced branch when you decide the effect.

| The default effect | The reduced branch |
|---|---|
| travel across more than a small part of the screen, parallax, a moving camera | a direct change of state or a brief fade; or a moving indicator over stationary content |
| zoom, rotation, depth, blur morphs | a cross-fade, or nothing |
| spring settle | direct positioning plus a state cue |
| looping decoration | a static frame, or nothing |
| indeterminate progress | a still indicator with status text |
| shared-element or route transition | direct navigation with the same URL, focus, and scroll |
| autoplaying video | the poster with a play control |

- Replacing is not shortening. Travel that runs faster is still travel, and zeroing every duration is a
  global switch, not a branch. Keep distance apart from time so the branch can set movement to 0 and keep
  a brief fade.
- Keep progress, selection, focus, status, reading order, and the way to recover; opacity and color
  feedback stay. Reduced motion removes movement, never information.
- Support two moments: at load, and when the setting changes while the page is open. A CSS media query
  follows both; script-owned animations and player runtimes must observe the change and settle, with the
  preference branch in one place.

For a motion-rich product with a real need for user control, define modes in
`tokens.motion.principles`: **full** includes earned authored moments; **basic** keeps
task-explaining transitions without expressive staging; **minimal** uses direct updates with
non-spatial feedback; **none** removes animation. Every mode preserves essential feedback:
input acknowledgement, selection, progress, focus, status, and recovery, using static cues when
needed. A product setting never overrides the system's reduced-motion preference; apply the
less-motion branch and settle safely if either changes during an interaction. Exercise the
same task in every offered mode. Do not add preference UI to routine screens merely to expose
these modes; token implementation stays with `lps-system`.

Flashing must stay within the applicable flash-safety limits. Motion input needs an ordinary control
and a way to disable it; continued automatic movement needs a pause, stop, or hide route. Record these
safety decisions in `tokens.motion.principles`. Flashing and motion-input safety are not checked;
`motion.uncontrolled-marquee` reads continued movement and whether a pause control is reachable.

**What the checks observe.** Render captures show settled appearances, including a reduced-preference
capture, not timing or easing. The behavior motion probe records movement at rest in ordinary contexts
and their reduced-preference counterparts. `motion.reduced-motion-missing` reads spatial movement and
moving media that the probe does not classify as essential content. Content presentation and decoration
affect that classification; an accessible name is not proof that motion is necessary.

The probe does not exercise an entrance triggered by a control, inspect animated shapes within a
graphic, establish focus or status preservation, or change the preference mid-interaction. A stationary
fade does not establish spatial movement. A source preference guard proves no rendered behavior.
Without the behavior session, report the requirement as not checked. After changing motion, rerun its
behavior probe and lint with that session. Exact sampling bounds and recognition patterns belong to
`ultramarine`'s check-bounds reference, not to the motion decision.

Exercise the rest by hand: load with the preference on, switch it while a sheet is open and moving, and
repeat the interaction quickly.

## Choosing a layer and delivering authored motion

Choose from the behavior and who owns it, not from a demo. Inspect the project's animation layer and how it
handles reduced motion first: a working layer stays, and a second one multiplies bundle, lifecycle, and
accessibility contracts (`code.animation-package-mismatch`). Starting with CSS, take the first layer that
carries the behavior without bending its semantics: a CSS transition for one state becoming another;
CSS keyframes for a bounded sequence; the browser's animation object when script needs cancel, reverse, or
a finished signal; native view transitions or scroll-driven CSS where supported, behind a guard; the project's
framework layer for mount, exit, and gesture integration; an imperative timeline library for many parts in
precise order; a player when a designer-authored asset is the deliverable. Before adding a dependency,
answer what the native layer failed to do, who owns the state, which cleanup removes its handles on
unmount, where the one reduced branch lives, and what it adds in bytes and long tasks.

Choose an asset representation by its job: semantic UI for controls, vector markup for diagrams with
live labels, footage for recorded scenes, a still for decoration, or procedural drawing with a text or
table alternative. Keep messages and controls outside opaque assets.

For each asset, record its trigger, reserved dimensions, playback controls, behavior while hidden,
and outcomes when loading or script fails. `code.image-dimensions` reads reserved image dimensions;
the other delivery decisions are not checked here. The reduced branch must remain useful without
starting the normal animation runtime.

Rights remain separate for the artwork, its embedded media and fonts, the editor and exporter, and
the runtime. Put shipped artwork in the asset ledger and fonts in the lock. The rights scan recognizes
file types rather than all animation formats, so record unrecognized assets explicitly.

## What the checks read

Each row states only what the check reads; `motion.reduced-motion-missing` is described above. A match by
pattern in the source is a lead: it stays open only when the render or behavior layer hits the same rule,
and is otherwise reported as skipped. The `code.*` rows are evidence of their own. No detector judges
choreography, interruption, or whether motion explains a change; the critic judges whether a decision is
earned by the subject, from the plan and still screenshots, and sees no timing.

| Rule | Reads |
|---|---|
| `motion.pulse-without-status` | source: utility signals for pulsing; render: small boxes with continuous non-stepped pulsing properties; neither reads whether the status is true |
| `motion.decorative-cursor` | source: blinking signals; render: continuous stepped or cursor-like animations; neither establishes a real input caret |
| `motion.uncontrolled-marquee` | render: movement at rest; behavior: continued automatic movement without a reachable pause control |
| `motion.bounce-default` | source: preset easing signals; render: how widely easing overshoots across animated boxes |
| `motion.transition-all` | source declarations and computed transitions that leave their properties unrestricted |
| `motion.layout-property-animation` | source and render: layout-affecting properties; behavior: animated geometry after a control action |
| `motion.hover-zoom-everything` | behavior with a fine pointer: the share of hovered media whose transform changes |
| `motion.ambient-loops` | render: how many boxes animate continuously; not whether their purpose is earned |
| `motion.scroll-gated-content` | behavior: hidden content below the opening viewport and its readability after scrolling |
| `ux.scroll-hijack` | behavior: input distance against native scrolling, blocked movement, and section snapping |
| `code.continuous-value-in-state` | source: state updates inside continuous-input handlers; not their runtime cost |
| `code.animation-package-mismatch` | source imports against declared and installed dependencies; not whether the chosen layer fits the interaction |

## Handoff to lps-system

Hand over each purpose with its proposed duration and curve role: feedback is feedback, orientation and
continuity are transition, expression is emphasis. Add the distance that goes to 0 under reduced motion and
what remains, and the interruption and focus contract of each overlay. The tokens carry values;
interruption, focus, and fallback are behavior that the implementation and the checks still have to honor.
