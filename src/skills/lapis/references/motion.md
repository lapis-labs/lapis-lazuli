# Motion

This file backs the plan's motion decisions: the motion dial in `direction.dials`, and `tokens.motion`,
where `reduced_motion: respect` is required and `principles` holds one string per decision. `lps-system`
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

Pick the band the surface needs, then write what it means here as a `principles` line, as the example does.
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
in `principles`, author the control points for this subject, and judge them on the rendered result. Keep
the vertical control values between 0 and 1 unless overshoot is a decision. Overshoot, spring, and bounce
are voices, not defaults: they fit a release after a physical drag or a playful subject, not routine
destructive, financial, medical, or frequent actions. When the subject earns one, keep
`motion.bounce-default` in `defaults` with the reason.

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

**Focus follows the interaction's semantics, not the visual timeline.** Opening: commit the open state,
put the destination in the accessibility tree, move focus where the pattern needs it, then animate.
Closing: move focus out of content about to become unavailable, commit the closed state, stop that content
from taking input (`inert` or the pattern's equivalent), run the optional exit, then hide or unmount with a
fallback that survives cancellation. An entrance never blocks Escape or Back, and an error announcement
never waits for a fade.

**Sequence** only when the order explains cause or grouping. A stagger of 50-100 ms can group a small set;
on a long list it makes later content wait, so move the group as one. At 7 or more, allow one authored
moment per ordinary surface; only a piece where motion is the medium has several. A gesture starts from the
current position and velocity and has a button or keyboard route.

**Feedback.** A press acknowledges accepted input briefly; it is neither the new state nor proof that async
work succeeded, and a surface color change is its robust baseline. Match loading feedback to what is known:
inline status for a short wait, a labeled determinate indicator for known progress, a skeleton shaped like
the final layout for structured content. Never show a made-up percentage. A skeleton that pulses across the
screen forever is ambient motion: limit it to the wait, and make it still under reduced motion.

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
.log-row { opacity: 1; transform: none; }

@media (prefers-reduced-motion: no-preference) {
  @supports (animation-timeline: view()) {
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

**View transitions.** Detect support before wrapping a DOM update, let the fallback commit the same update
directly, and skip or simplify the transition under reduced motion. The transition owns none of URL and
history, title, loading and error state, focus and announcements, or scroll restoration.

## Reduced motion

`reduced_motion: respect` is a requirement, never traded for the dial, the brief, or a signature. It covers
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
- Nothing may flash more than three times in a second unless it stays within the general and red flash
  limits, decorative content included. Motion as input (tilt, shake) needs a conventional control and a
  way to turn it off. Anything that moves by itself for more than five seconds needs a way to pause, stop,
  or hide it.

**What the tools observe.** State only this in a report.

- `render check` takes one extra capture at 390 px, light theme, with reduced motion emulated (its
  screenshot name ends `-reduced`). The motion rules read the plain capture at each width, so none compares
  the two. Screenshots come after finite animations end and endless ones are paused at their start, so none
  shows timing or easing.
- `behavior check --probe motion` runs in each base context and in a twin with reduced motion emulated. In
  each it watches five seconds after load with no input and lists the elements that moved, by kind:
  `transform`, `opacity`, `scroll-linked`, `video`, `canvas`, or `other`. An element whose position or
  transform changed is `transform` even while it also fades; `opacity` is a fade that stays in place.
  `motion.reduced-motion-missing` gates when, in the twin, an element that is not essential still moves by
  `transform`, a scroll-linked animation, `video`, or `canvas`. A canvas is essential when it is presented
  as content (in a figure, or named as a chart, map, or diagram); a video in that window never is, because
  no one has acted.
- Not observed: a transition that a hover, press, or open starts; movement a script produces by rewriting
  styles every frame (the window lists elements with a running CSS or Web animation, and canvas, video, and
  image changes); shapes animated inside an `svg` (an `svg` element that itself moves is listed, its child
  paths and rects are not); whether focus and status survive the reduced branch; a setting change while the
  page is open; flashing. A fade that stays in place does not gate. No source rule looks for a
  reduced-motion media query, and one in the source proves nothing.
- Without a behavior session the requirement is not checked. Say so, and list it among the checks that did
  not run. After a motion change, run `lapis-design behavior check <url> --task <task> --plan
  .lapis/plans/<task>.yaml --stub .lapis/stub.yaml --probe motion`, then lint again with `--session`.

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

An animation file does not settle how to ship it. Decide the job and the control it needs, then take the
smallest representation that keeps the job.

| Representation | Choose it for | Fallback |
|---|---|---|
| CSS on real UI | state feedback and simple geometry | the final state, shown directly |
| SVG animated by CSS or script | diagrams and icons with live text | a static SVG |
| exported vector sequence or state machine | a designer-authored flourish, or a control whose states are the deliverable | a poster, or semantic UI |
| video | footage, cinematic sequences, complex raster effects | poster and transcript |
| animated image | a small, non-interactive loop | the first frame |
| canvas or WebGL | procedural or high-volume drawing | semantic DOM, a still, or a data table |

"Vector" does not mean small or fast: measure the artifact. A real control or message never lives inside an
asset. For each asset write its trigger (eager, visible, user-started), its reserved box (a missing one
causes layout shift, which `code.image-dimensions` reads), autoplay and loop, whether it pauses when
hidden, and the no-script and load-error result. Under reduced motion serve a still instead of starting a
heavy runtime. The checks measure none of frame pacing, long tasks, or bytes, so a claim of smoothness
needs a trace.

Rights are separate records for the editor and exporter terms, the runtime's license, the artwork, each
embedded font, image, and audio clip, and the approval for this product. Record the artwork in the asset
ledger and its fonts in the fonts lock. The scan of shipped files matches known image, video, audio, and 3D
extensions, so an animation file with another extension needs its ledger entry by hand.

## What the checks read

Each row states only what the check reads; `motion.reduced-motion-missing` is described above. A match by
pattern in the source is a lead: it stays open only when the render or behavior layer hits the same rule,
and is otherwise reported as skipped. The `code.*` rows are evidence of their own. No detector judges
choreography, interruption, or whether motion explains a change; the critic judges whether a decision is
earned by the subject, from the plan and still screenshots, and sees no timing.

| Rule | Reads |
|---|---|
| `motion.pulse-without-status` | source: pulse and ping utility class names, with a skeleton placeholder as the rule's keep case; render: an element of 32 px or less with an endless pulse in opacity, transform, scale, shadow, or filter |
| `motion.decorative-cursor` | source: blink class and keyframe names; render: an endless stepped or blink-named animation |
| `motion.uncontrolled-marquee` | render: an element that moves on its own between 0 and 2 s after load (a lead until the behavior layer agrees); behavior: content still moving after 5 s with no reachable button, beside it or naming it in `aria-controls`, whose accessible name says pause or stop (English or Korean words) |
| `motion.bounce-default` | source: bounce, elastic, and back easing names, and curve control values outside 0 to 1; render: such curves on more than half of the animated elements |
| `motion.transition-all` | source: `transition: all`; render: a running transition of all properties |
| `motion.layout-property-animation` | source: transitions naming layout properties; render: computed transitions and keyframes on them; behavior: activating a control animates geometry through such a property for 50 ms or longer |
| `motion.hover-zoom-everything` | behavior, fine-pointer context: more than four in five images and videos change `transform` on hover |
| `motion.ambient-loops` | render: more than one element with an endless animation |
| `motion.scroll-gated-content` | behavior: elements below the first viewport that start nearly invisible, clipped away, or hidden, and the time each takes to become readable once scrolled into view |
| `ux.scroll-hijack` | behavior: three scroll inputs of one kind against what the browser scrolls by default; flagged when the distance is under half or over twice that, when the page did not move, or when the document snapped to sections |
| `code.continuous-value-in-state` | source: a state hook's setter called inside a pointer-move, touch-move, scroll, wheel, or drag handler |
| `code.animation-package-mismatch` | source: imports of the animation packages it knows, against `package.json`, lockfiles, and the installed package's exports; and two animation stacks imported together |

## Handoff to lps-system

Hand over each purpose with its proposed duration and curve role: feedback is feedback, orientation and
continuity are transition, expression is emphasis. Add the distance that goes to 0 under reduced motion and
what remains, and the interruption and focus contract of each overlay. The tokens carry values;
interruption, focus, and fallback are behavior that the implementation and the checks still have to honor.
