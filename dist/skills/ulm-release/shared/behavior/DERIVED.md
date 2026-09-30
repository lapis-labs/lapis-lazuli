# Behavior session: how values are observed and derived (v0)

This document defines the fields of `behavior/session.schema.yaml`. behavior_check writes the session;
behavior-layer detectors read it through the paths listed as `reads_session` in `slop/detectors.yaml`.
Derived values (the `derived` blocks, `effect.outcome`, and `stop.focus_visible`) have a reference
implementation in `cli/lapis_design/behavior.py`, and the tests recompute the example session's.

Numbers below (settle windows, tolerances, profiles) are v0 definitions of this contract. They make
sessions comparable; they are not claims about perception or law. Rule thresholds live in `rules.yaml`.

## Scope and safety

- **Own output only.** `source.kind` is always `render`, and `source.url` must be on a host that is
  ours as render/DERIVED.md **Target hosts** defines it. The driver presses destructive controls,
  submits forms, and completes purchases, so it never runs against a third-party or reference site.
  Reference behavior is out of scope for v0.
- **Other hosts are blocked.** Requests to a host other than the source host or a host that is ours
  are blocked and recorded with `blocked: true` (third-party checkout, analytics, and chat SDKs
  included), except GET requests for scripts, styles, fonts, and images, which load normally. A
  render that needs an outside service for a flow uses the stub's stand-in. A navigation to another
  host is stopped there and recorded as a navigation with `external: true`. Console messages the
  blocking itself causes are dropped.
- **Backend.** `meta.backend` is `stub` (scripted responses, failure injection, and an effect
  counter) or `local-dev`: the project's own backend running as an isolated instance with synthetic
  data only. With `local-dev`, `meta.outbound` says whether the backend can reach any outside network
  (`restricted`) or none (`none`). Destructive probes and failure injection run only on the stub, and
  commits and flows with a commit step run only on the stub or on `local-dev` with outbound `none`;
  the schema enforces both. Anything left out is recorded as `partial` in `coverage`.
  A local fixture-based session records the `--stub` file in `meta.stub`, as a POSIX path relative to
  the directory the check ran in, so the release gate can compare modification times; checks run
  from the project root. A stub the check cannot express that way (another drive) is left out, and
  `--stub-url` has no local file.
- **Data.** The driver uses synthetic fixtures: names, addresses, emails at reserved example domains,
  and the stub's test payment tokens. It never uses real accounts, credentials, or payment methods.
  Typed values are not stored; `value_id` names the fixture value (`v1`, `v2`, ...). Any stored text
  (labels, names, announcements, console messages) that contains a fixture value has it replaced by
  `{v1}` and so on, wherever the value stands as a whole token: not joined to another ASCII letter
  or digit on either side. So a short value such as `0000` never rewrites part of `30000ms`, while a
  value followed by a Korean particle or suffix (`김도예님`) is still replaced.
- **Paths.** URL paths are templated: a segment with four or more digits, a UUID, or 16 or more
  letters and digits including a digit becomes `:id` (`/reservations/r-2409-031` →
  `/reservations/:id`). Query strings and fragments are never recorded.
- **Requests** keep method, host, and templated path. Headers (except whether an
  `Idempotency-Key` was sent) and bodies are not recorded.
- **Console messages** keep their text with URLs reduced to host and templated path, and any run of
  16 or more letters and digits that includes a digit replaced by `…`.

## Contexts

A context is one browser profile with fixed settings. Every probe names the context it ran in.

| Field | Meaning |
|---|---|
| `width`, `height`, `dpr`, `theme` | As in the render extract's viewports. The default matrix is `m` (390×844, coarse pointer) and `d` (1440×900, fine pointer), light theme, DPR 2. |
| `reduced_motion` | `prefers-reduced-motion: reduce` emulated. The motion probe runs a reduced context against its full-motion twin (`compare_to`). |
| `pointer` | `coarse` emulates touch input (`tap`); `fine` a mouse. Keyboard is an action modality, not a context. |
| `network` | `normal`: no shaping. `slow`: 400 ms added to every response and 400 kbit/s download. `offline`: all requests fail at the network layer after load. |
| `dir` | The document's writing direction; reading-order comparisons mirror for `rtl`. |
| `clock` | `controlled`: timers and `Date` are driven by the driver, which advances them explicitly (`clock-advance`). All contexts of a session and the stub share one controlled timeline, so a reading in a fresh profile is comparable with one taken earlier and fixture deadlines expire on it. |
| `storage` | `fresh`: a new profile with empty storage and cookies. `persisted`: storage kept from earlier probes in the run. |
| `timezone` | The IANA time zone the profile runs in (what `Date` and `Intl` report). `UTC` unless `behavior check --timezone` names another; every context of a session has the same zone. Absolute times on the page that name no zone are read in it, with the zone's offset on the date they name. |

## Stub backend contract

The stub answers the app's requests from fixtures and counts **effects**: state changes it applied
(an order created, a subscription changed, a record deleted). `request.effects` is that count for one
request. It is the backend's only client during a session. Injected failures, recorded in
`request.injected`:

| Injection | Backend effect | Client sees |
|---|---|---|
| `none` | applied as normal | the normal response |
| `delay` | applied | the response after the added delay |
| `fail-5xx` | not applied | HTTP 503 |
| `fail-network` | not applied | connection refused before the request is read |
| `hang` | **applied** | no response; the connection closes after 10 s of controlled time |
| `forbidden` | not applied | HTTP 403 |
| `not-found` | not applied | HTTP 404 |

`hang` models an outcome the client cannot know: the change happened, the answer never arrived; the
connection closes once the session's controlled clock passes 10 s after the request. The
stub honors `Idempotency-Key`: a repeated request with the same key returns the first result and adds
no effect.

## Stub fixture file

`stub.schema.yaml` validates a YAML fixture (`version: 0`) supplied to `behavior check --stub`
or `stub serve FIXTURE`; `example.stub.yaml` illustrates the pottery shop in the example plan.
Fixtures are synthetic, not copied from a live service. Both transports use one engine and the
same controlled `clock.start` (UTC ISO 8601); advancing the clock does not reset backend state.

- `routes` lists `method` and `path` templates (`:id` matches one segment). Each route has either
  `response: {status, json}` for a literal response or `collection` and `operation` (`list`, `get`,
  `create`, `update`, `delete`). `effects` overrides the default applied effect count (1 for
  create/update/delete, 0 for reads and literal responses). Missing records yield 404 with no effect;
  a create returns its new `id`. Requests with the same `Idempotency-Key` replay the first result
  without another effect, including a retry after a committed but unanswered hang.
- `collections` maps names to arrays of initial JSON records with unique string `id`s. `variants`
  maps variant names to replacement arrays per collection; unlisted collections keep base records.
  `reset(variant=...)` restores those records, the effect count, injection queue, and replay history
  without rewinding the clock. Use `empty` and `partial` variants to exercise state transitions.
- `values` maps synthetic value ids to `kind` (`name`, `email`, `phone`, `address`, `postal-code`,
  `card`, `card-expiry`, `card-cvc`, `password`, `code`, `text`, `number`, `date`, `url`, `search`)
  and three text samples: `valid`, `invalid`, `alternate`. Empty input is synthesized separately.
  `values_for(kind, variant)` chooses a value id; suffixes `:invalid`, `:alternate`, `:empty`
  select its sample while the bare id selects `valid`. Use only reserved example.com/example.org
  emails and stub test card numbers, never real accounts or payment data.
- `accounts: {username, password}` refers to value ids for one synthetic sign-in. `auth.sign_in`
  identifies its route; `auth.cookie` names the session cookie it sets when credentials match.
  Routes marked `require_session: true` return 401 without that cookie. The cookie is scoped to
  the fixture server and cleared by reset.
- `urgency.countdown.at` and `urgency.deadline.at` are UTC expiry instants;
  `urgency.hold.hold_s` runs from `clock.start`, not from page load. `urgency.stock` and
  `urgency.demand` map item ids to counts; `urgency.activity` lists `{event, count}` entries
  recording actual events. A claim is backed if its remaining seconds agree with the controlled
  clock within the larger of 2 seconds and its display resolution, or its count matches a
  recorded stock/demand/activity count. The backing API accepts a numeric reading but no item
  identity, so a count can match any listed item; attribution is not inferred.
- `outside` lists stand-ins with `host`, `method`, `path`, `response: {status, json}`. The driver
  fulfills these locally rather than connecting to that outside host.

The browser adapter fulfills routes in-page by default. `stub serve` answers them over HTTP for
server-rendered apps (loopback by default); unknown API routes return 404. Its `/__lapis/` JSON
endpoints provide inject, clear, reset, clock read/advance, effects, values, backed, and account
controls through `RemoteStub`. Injection queue entries match a method/path template for `times`
requests; `delay` adds 400 ms and `hang` applies the effect but closes without an answer after
10 seconds of controlled time. The other failure modes have no effect, as in the table above.

For `behavior check --stub-url` over HTTPS, a dev server using a local certificate authority needs
Python to trust that authority for stub control requests. For example, set `SSL_CERT_FILE` to the
authority's PEM certificate before starting the check; pinning the host does not disable TLS
certificate or hostname verification.

## Nodes and ids

Box ids follow the render extract (render/DERIVED.md, Capture): `b` plus the first 12 hex digits of
SHA-256 of the element's DOM path. Elements created by an action get ids the same way when they
appear. `nodes` describes every id used anywhere in the session: role (the extract's role enum),
accessible name, rect in page coordinates with the page scrolled to the top, and the context of that
first observation. `in_extract` is true when the id also appears in the extract of the same build.
Probes that depend on geometry (keyboard stops and containers) carry their own rects for their
context.

## Actions, timing, and the settle window

Each probe starts from a fresh page load, and `t_ms` counts from that load. Flow runs count from the
load of their first step.

An **action** is one input: `click`/`tap` on a box, `key` (a named key or chord), `type` (a whole
field value, entered with 30 ms between characters), `paste`, `select`, `check`/`uncheck`, `hover`,
`focus`, `drag`, `scroll`, history moves, `navigate`, `wait`, `clock-advance`, and `pointer-leave`
(the pointer exits through the top edge of the viewport, as exit-intent scripts expect).

After each action the driver waits for the **settle window**: until no DOM mutation and no pending
request for 500 ms, capped at 5 s (10 s of controlled time when a `hang` is injected: the driver
advances the controlled clock in 1 s steps and checks the page after each, so app timeouts fire in
order). The **effect** records what changed in that window:

- `navigation`: `document` (new document), `same-document` (a history push, or a hash change to an
  element that exists), `new-window`, `download`, or `none`. A link to `#` or to a missing fragment
  records `none`. `external` when the navigation went to another host. `path` is the templated path
  afterward.
- `text_changed`: boxes whose visible text changed. `status_changed`: those of them, or new boxes,
  whose text reports a result: text that appears in a toast, snackbar, or status banner; a count or
  result summary that changed (items in a cart, results found); or text next to the control that names
  its result (saved, added, sent). Panels opened by a disclosure or tab are not status.
  `aria_changes`: state attributes that changed, including a media element's `paused`.
  `dom_mutations`: count of mutated nodes, including cosmetic class changes.
- `focus_to`: the focused box after the window (`null` for the document body). `scroll_y_delta`:
  how far the page scrolled.
- `requests`, `announcements` (below), `console_errors` (count in the window).
- `layout_shift`: the sum of layout-shift entries in the window **including** those flagged as
  following input, with the boxes that moved in `shift_sources`. The render extract's CLS excludes
  them; here they are the point.
- `layout_animated`: boxes whose geometry changed through a transition, CSS animation, or
  `Element.animate()` on a layout property (width, height, inset, top, right, bottom, left, margin,
  padding) that lasted 50 ms or longer (three frames at 60 Hz), and whose rect at the end of the
  window differs from its rect when the animation started. The driver learns of animations from
  `transitionrun`, `animationstart`, and calls to `Element.animate`, not by sampling frames: page
  timers and `requestAnimationFrame` run on the controlled clock, so frame counts would depend on how
  the driver advances it. An instant change, or a shorter transition, is not an animation.
- `resized`: boxes present before and after the window whose width or height changed by more than
  0.5 px, other than boxes in `layout_animated` and the boxes that contain one or sit inside one
  (they changed with the animation). Boxes whose change came with a new document are not compared.

**Announcements** are the ways assistive technology would learn of a change: text added to a polite
or assertive live region (`live-polite`, `live-assertive`), an element with `role=alert` inserted
(`alert`), or focus moved to the changed content (`focus`). A live region is an element whose
`aria-live` is `polite` or `assertive`, or that has no `aria-live` and an explicit or implicit role
that implies one (`status` and `log` polite, `alert` assertive; `<output>` has the role `status`).
Text added anywhere inside counts for the nearest enclosing element that has `aria-live` or a role
with a live default, so an inner `aria-live="off"`, `timer`, or `marquee` silences it. Text inside
an `aria-hidden` subtree is not announced.

**Wording.** The dialog, choice, flow, state, and commit-result probes read labels, dialog text, and
messages in English and Korean; the other probes (control kinds, forms, permissions) read English
only. Each kind of wording (confirm, cancel, close, decline, refuse, put off, retry, a problem, and
each commit result) has one shared list holding both languages, which every probe judging that kind
reads, so a language added for one probe is not missing from another. Where this document names
words, the English ones stand for the kind, and the Korean examples show counterparts (확인, 취소,
닫기, 거절, 나중에, 다시 시도, and so on). A control's wording is read from its accessible name.
Other languages are not read, so a page in another language gets fewer matches, not different
ones.

## Controls

The driver exercises every box that is visible and enabled and has an interactive role, a pointer
handler, or `cursor: pointer`, plus any such box an action creates. Between probes the page is
reloaded with storage reset, so one control's effect does not leak into the next. A box whose click
does exactly what a focusable descendant does (a card whose link is the real control) is probed
through that descendant.

`promise` is what the control looks like it will do, from role, name, and recognized icon action:
a link to another location promises `navigate`; a submit button `submit`; `aria-pressed` or a switch
`toggle`; `aria-expanded` or a disclosure icon `expand`; options and tabs `select`; a dialog opener
`open`; media controls `play`; download links `download`; names and icons for delete, remove, cancel
subscription, or leave `destructive`; everything else `other`.

**`effect.outcome`** (derived) is the first class that applies:

1. `navigated`: navigation is `document`, `same-document`, or `new-window`.
2. `download`.
3. `dialog`: a dialog opened.
4. `state-changed`: an ARIA state or visible text changed, or a box other than the control changed
   geometry (it is in `layout_animated`, `shift_sources`, or `resized`). DOM mutations alone are
   cosmetic and do not count.
5. `moved`: the page scrolled, or focus moved to a box other than the control.
6. `data-requested`: requests were sent, not counting beacons and blocked requests.
7. `error`: console errors, and nothing above.
8. `no-effect`.

**`derived.matches_promise`**: false for `no-effect` and `error`; otherwise true when the outcome is
in the promise's set: navigate → navigated, moved, or download; submit → data-requested, navigated,
state-changed, or dialog; toggle, expand, play → state-changed; select → state-changed or navigated;
open → dialog, state-changed, or navigated; download → download or navigated; destructive → dialog,
state-changed, data-requested, or navigated; other → any.

**`keyboard.activation`**: the control is focused with Tab (or programmatically when it is
unreachable) and activated with its platform keys: Enter and Space for buttons and switches, Space
for checkboxes and radios, Enter for everything else. `same` when the outcome class and the changed
boxes match the pointer effect (a control that does nothing with either is `same`: the dead-control
finding covers it); `different` when something else happens; `none` when the pointer did something
and the key did nothing.

## Commits

A commit is an action that sent a request with a state-changing method (POST, PUT, PATCH, DELETE)
whose response reported effects, or the action on a flow's commit step.

Every measurement starts from a reset stub and a fresh load, and replays what exposed the control:
the control probe's actions that revealed it, or, for a flow's commit, the flow's actions before
the commit action. The commit control of an exit flow exists only in the state its pair created (the
subscription to cancel), so the pair's completed run in the same context is replayed first, from the
pair's first step, and the exit flow's actions follow from where the pair started. Only the direct
pair is replayed, not the pair's own pair. Without a completed pair run the commit is not measured
and `commits` coverage is `partial`. For each commit control:

- **Double activation.** Two activations 80 ms apart (two taps, then separately two Enter presses;
  the worse result is kept). `requests` counts state-changing requests sent, `effects` the effects
  applied. `pending_shown`: the control or its region showed a pending state before the response.
  `name_kept`: the control's accessible name was not empty while pending.
- **Outcomes.** The commit is repeated with each injection. `claimed` is what the page says within
  the settle window, from the text and state of the control's region and any toast or dialog:
  `success` (done, saved, confirmed, and the completed forms of subscribe, sign up, register,
  submit, pay, book, and place), `failure` (failed, not saved, try again), `pending` (in progress),
  `unknown` (the page says it is checking or cannot confirm), `saved-locally` (the page says the
  change is kept on this device), `none` (nothing said). Only text the region did not show before
  the commit is read, so a standing note ("this cannot be undone") is not a claim. A negated result
  reads as a failure (not saved, 저장하지 않았어요, 결제를 완료하지 않았어요), unless it says the
  result cannot be confirmed (could not confirm, 확인하지 못했어요), which is `unknown`; a
  conditional or future one (once saved, 완료되면, 완료 후) is no claim. `actual` follows the stub
  contract: applied for `none` and `hang`, not applied for the rest; `unknown` only with
  `local-dev`.
  `retry_offered`: a retry or resubmit control appeared. `retry_effects`: effects added by
  activating it once. `auto_resent`: the client sent the same state-changing request again without
  user action and without an idempotency key. `input_kept`: entered values survived. `announced`:
  an announcement carried the result.
- **Confirmation and undo** for destructive commits. `confirm.names_object`: the confirmation text
  names the thing affected. `initial_focus`: the control focused when the confirmation opens.
  `undo.restores`: after undo the object is back, checked again after reload (`survives_reload`).
  `keyboard_reachable`: the undo control can be reached with Tab before it disappears.
  `dismissed_while_focused`: the undo surface disappeared while it had focus or pointer hover.

The effects of one intended commit are the double-activation `effects`, and for each outcome
`(1 if actual is applied else 0) + retry_effects`, plus one more when `auto_resent` is true.

## Keyboard

A walk is one traversal of one route (`path`) in one context. Walks run on the entry route and on up
to four more routes, so repeated blocks can be compared: first the routes the plan's flows reach, then
same-origin links among the entry walk's stops, preferring paths whose first segment differs from
routes already walked (a different page template). Each walk starts with focus on the document (after load settles), presses Tab
until focus passes the last stop or 3 × (focusable boxes) + 10 presses, then repeats with Shift+Tab
from the end. `reverse_matches` when the Shift+Tab walk visits the same stops in reverse order.

- **Stops**: each box that received focus, in order, with its accessible name, its nearest landmark
  ancestor (`landmark`, `none` outside every landmark), whether it lies inside `main` at any depth
  (`in_main`), its rect in the context, and its
  `container`: the nearest ancestor that is a card, list item, list, section with a heading,
  landmark (`header`, `nav`, `main`, `aside`, `footer`, `form`), or dialog. `containers` lists each
  container with its own nearest grouping ancestor (`parent`, null at the top) and rect.
- **`indicator`**: screenshots of the box inflated by 8 px, before and after it receives focus;
  `area_px` is the area of changed pixels in CSS px², `contrast` the median contrast ratio between
  the changed pixels' before and after colors, and `contrast_area_px` the area of the changed pixels
  whose own before and after colors reach 3:1. The walk measures a stop when its Tab press did not
  scroll the page and the inflated box lies inside the visual viewport (or is cut only where the
  document ends). The other stops are measured on one replay of the walk: before the Tab press that
  reaches such a stop, the driver scrolls the target into the middle of the viewport with
  `window.scrollTo`, then takes both screenshots with the view unchanged. It does not use
  `scrollIntoView`, which moves the browser's sequential focus starting point and would change where
  Tab goes. Regions are measured in visual-viewport CSS px, so a page without a viewport meta tag,
  drawn zoomed out in a coarse-pointer context, is scaled back.
- **`focus_visible`** (derived, project policy): `contrast_area_px` ≥ 2 × the box's longer side (a
  2 CSS px line along it, so a 2 px underline or a 1 px ring passes); absent when the indicator or
  rect was not measured. Counting only the pixels that reach the non-text contrast level follows the
  focus-appearance method, so a two-tone ring (a dark outer and a light inner line, as browsers draw
  by default) passes on its contrasting part; a median over all changed pixels would reject it. The
  area floor is looser than that method's perimeter.
- **`obscured_share`**: the share of the focused box's rect covered by content painted above it
  (sticky and fixed elements, open banners), sampled on a 4 px grid with `elementsFromPoint`,
  rounded down to two decimals, so 1.0 means entirely hidden. `obscured_by` is the largest cover.
- **`context_change`**: within 500 ms of receiving focus, and with no other input, the page
  navigated, opened a window or dialog, submitted a form, or moved focus elsewhere.
- **Traps**: a cycle of stops that repeats three times while focusable boxes outside it stay
  unvisited, and that is not a modal dialog's contained focus. The driver then presses Escape;
  `escape_leaves` records whether focus left the cycle.
- **Unreachable**: visible, enabled boxes that have an interactive role, a pointer handler, or
  `cursor: pointer`, and never received focus, excluding boxes whose click does what a focusable
  descendant does. `semantic` is true for native controls and ARIA widget roles, false for other
  elements (a clickable `div`).
- **Skip link**: a same-page link among the first three stops. The driver activates it and presses Tab
  once; `lands_at` is the index of the stop reached, or null when activation moved neither focus nor
  the sequential focus starting point. The link's target does not matter, only where focus goes.
  `presses_to_main`: plain Tab presses from the document start until focus is inside `main`, without
  activating the skip link; absent without a main landmark.
- **`landmarks`**: `main` when a visible `main` element or `role="main"` exists; `roles` lists the
  landmark roles present. **`headings`**: visible headings in the accessibility tree in document
  order, each with its level and `next_stop`, the index of the first stop that follows it in document
  order (null when none does), and its nearest landmark. Site furniture below means the `banner`,
  `navigation`, `complementary`, and `contentinfo` landmarks.
- **`derived.repeated_stops`**: the repeated block before the primary content. Take the longest run
  of leading stops that this walk shares with the walk of another route in the same context, where
  two stops match when both box id and accessible name match (box ids are DOM-path hashes, so a
  shared header gives the same ids on every route, and so does a shared page template). Then cut the
  run before the first stop that is `in_main` and not in site furniture (a search form at the top of
  main counts as content; a navigation inside main does not), and before the `next_stop` of the first
  level-1 heading outside site furniture that has a stop before it: both mark where the page's own
  content starts. Absent when the context has only one walked route.
- **`derived.bypass`**, present with `repeated_stops`: `skip-link` when `lands_at` is at least
  `repeated_stops` and past the stop after the link; `main-landmark` when `landmarks.main` and no
  repeated stop is `in_main` (a main landmark that wraps the navigation skips nothing); `heading`
  when a heading outside site furniture follows every repeated stop: its `next_stop` is at least
  `repeated_stops`, or null. A footer heading does not bypass anything.
  With one walked route per context, the bypass checks report a skipped finding with evidence
  `not-verified`; a skip link whose `lands_at` is null is still reported as broken.
- **`derived.order_inversions`**: consecutive stops (by `index`) are compared unless exactly one of
  them is inside a dialog. Stops in different containers where neither container holds the other are
  compared by the two branches that are children of their closest common ancestor (the topmost
  containers when there is none). All other pairs, including stops without a listed container and
  stops in nested containers, are compared by their own rects. Two rects share a row when
  their vertical overlap is at least half the smaller height. The second is a backward jump when they
  share a row and its horizontal center lies left of the first's left edge (mirrored for `rtl`), or
  when they do not share a row and its vertical center lies above the first's top edge. So a card
  grid walked card by card, or a main column followed by a sidebar, is in order.
  `inversion_pairs` lists each jump by stop box.

## Dialogs and choices

A **dialog** is an element with role `dialog` or `alertdialog`, `aria-modal`, a `<dialog>`, or an
overlay that appears after load, paints above the content, and covers at least 30% of the viewport
(`interstitial`). `banner` is a bar fixed to a viewport edge that asks for a decision; `sheet` a
dialog anchored to the bottom edge; `popover` a non-modal panel anchored to a control.

One dialog probe covers **one request**: appearances belong together when they share the box and the
purpose, even when the wording changes. A portal container reused for prompts of different purposes
yields separate probes.

- **`trigger`**: `load` (appeared within 1 s of load settling, before any input), `timer` (later,
  before any input; `trigger_after_ms`), `scroll` (after scrolling, `trigger_scroll_share` of the
  page height), `exit-intent` (after `pointer-leave`), `control` (`trigger_box`), `navigation` (on a
  new route before input), `idle` (after 30 s without input). `path` is where it first appeared;
  `flow` when it appeared during a flow run.
- **`blocks_content`**: the page behind cannot be scrolled or activated while it is open.
  `area_share`: the share of the viewport it covers.
- **`purpose`**: `plan` when a plan flow names the decision; otherwise from the dialog's text and its
  choices (`text`), or layout alone (`heuristic`). Consent covers data processing and cookies;
  marketing covers newsletters and promotional contact.
- **Focus**: `moved_in` (focus inside within 500 ms), `initial`, `contained` (for dialogs that block
  content: Tab and Shift+Tab for focusable count + 2 presses, at most 20, stay inside),
  `escape_closes`, `close_control` (a visible control that closes or cancels), `returns_to` (after
  closing: the invoker, a logical next box when the invoker is gone, the body, or elsewhere),
  `background_inert`. Moving and containing focus is expected of dialogs that block content,
  whatever their kind; `returns_to` is meaningful for `control` triggers. Containment breaks only
  when focus lands on page content outside the dialog: a native modal lets Tab pass through the
  browser's own interface, where the document reports focus on the body, and that counts as inside.
  Pressing Escape uses up the driver's answer, so the driver presses it only on a dialog a control
  opened (it reopens the dialog with that control afterwards) or on one it would dismiss or leave
  unanswered anyway and that offers no manage, settings, preferences, or customize control. For any
  other dialog `escape_closes` is absent.
- **Appearances** are logged over the dialog probe window: after the first appearance the driver
  answers it, then visits two other routes, returns, reloads once, and idles 60 s of controlled
  time. Each appearance records what preceded it and how the driver answered: `accept`, `decline`
  (a route that leaves the business-favored state unapplied, including a close control that does
  so), `dismiss` (closed while the page keeps the question open, such as a banner that stays
  minimized), `later` (an explicit remind-me-later control), or `none`. The driver declines when a
  decline route exists, otherwise answers later when offered, otherwise dismisses.
- **`dont_show_again`**: whether the dialog offered not to ask again, and for how many days.
- **`derived.reasks_after_decline`**: appearances after the first decline, dismissal, or `later` that
  were not preceded by the user opening it (`control`). Within one visit, later is not now.

A **choice set** is a decision offered to the user: a dialog's actions, a consent banner, an offer
with accept and decline, a group of optional add-ons, or a plan picker. **Options are routes**: each
way to complete a choice is one option, with `layer` (1 when its first control is visible without
opening anything else) and `interactions` (the fewest actions that complete it, counting typing a
field as one). Leaving an optional add-on unchecked is a `decline` route with 0 interactions and no
`visual`. A reject-all reached through "manage settings" is a `decline` option on layer 2 with its
full interaction count, and the "manage settings" control is a `customize` option on layer 1.

- **Kinds**: `accept` gives the business what it asks for (consent, subscribe, add, upgrade, stay);
  `decline` refuses it (including a refusal of consent, such as do not agree); `dismiss` closes or
  puts the question off while leaving it open (maybe later, remind me later); `customize` opens
  finer choices; `neutral` when the choice has no business-favored side (a confirmation of the
  user's own action, a size picker).
- **`visual`**: `area_px` is the painted area: the background or border box when the control is
  `filled` (a background differing from its surroundings by at least 0.05 OKLCH L) or `bordered` (an
  outline without a fill), otherwise the bounding box of its label text or icon. `contrast` is the
  label's contrast ratio on its backdrop; `size_px` and `weight` describe the label;
  `in_first_viewport` whether it is visible without scrolling.
- **Prices**: `price` and `currency` are what the option adds; `cadence` for recurring prices.
  Plans are compared by annualized price (day × 365, week × 52, month × 12, year × 1); one-time
  prices, and `other` cadences, are compared only with their own kind.
- **Prominence** of an option: `area_px × style × min(contrast, 7) / 7`, where style is 2 for filled,
  1.5 for bordered, and 1 otherwise.
- **`derived`** exists only for choice sets with at least one accept option.
  `decline_found` is true when any decline route exists, and then `decline_extra_interactions` is
  the fewest interactions of a decline route minus the fewest of an accept route.
  `prominence_ratio` is present when layer 1 shows both an accept control and an entry to declining:
  the largest prominence among layer-1 accept controls divided by the largest among layer-1 decline
  controls, or else customize controls, or else dismiss controls. Routes with 0 interactions have no
  control, and icon-only close controls are a convention rather than a labeled choice, so neither is
  compared. A zero denominator gives 1000, the cap.

## Forms

For each form, in a fresh reload per step:

1. **Load**: `untouched_invalid_on_load` when a field shows an error or `aria-invalid` before input.
2. **Typing**: each field gets an invalid value one character at a time, on its own fresh load.
   Its stage is `keystroke` when an error appeared during an input event while typing, else `blur`
   when errors changed after Tab left the field, else `submit` when they changed after a submit (only
   where submitting is safe), else `never`. The form's `first_error` is the earliest stage any field
   reached, in the order keystroke, blur, submit, never; it is `load` when an error already showed
   before input.
3. **Invalid submit**: valid values everywhere except one field, then submit. `errors` counts error
   messages; `described_in_text` (the problem is in text, not only an icon or color);
   `associated` (each message is tied to its field by `aria-describedby`, `aria-errormessage`, or
   the label); `color_only` (only a color changed on the invalid field); `focus_to`; `announced`;
   `new_requirement` (the message states a format or length rule absent from the visible text
   before entry; a lead for review).
4. **Preservation**: after the invalid submit, after a `fail-5xx` submit, and for multi-step or
   draft-promising forms after reload, Back, and a forced re-sign-in. The counts cover fields that
   held an entered value (text entry and selects); checkboxes and radios are not counted. `kept`
   and `cleared` count non-sensitive fields; `cleared_sensitive` counts passwords, codes, and payment
   fields; `explained` when the page says why those were cleared; `cleared_boxes` lists the emptied
   fields. The forced re-sign-in fills the form, clears the cookies, signs in again through the
   stub fixture's `auth.sign_in` route with its synthetic account, and reloads keeping storage.
   Without `auth` in the fixture it is not measured and `forms` coverage is `partial`.
5. **Paste**: each field receives a pasted value; `paste_blocked` when the value does not arrive.
   **Change**: each select, radio, checkbox, and switch is changed once with no submit; `on_change`
   records a navigation, new window, submission, dialog, or focus move within 500 ms.
6. **Submit control**: `disabled_until_valid`, `reason_visible` (text next to it or in the form says
   what is missing, not a hover-only tooltip), `disabled_sends` (it looks disabled but still sends).

Field `purpose` separates data fields from choices: `consent` (processing beyond the task),
`marketing`, `add-on` (a paid extra), `terms`. `checked_on_load` records the initial state of
checkboxes and switches. `label.visible` (a visible label), `label.persists_after_input` (it stays
once the field has a value, unlike a placeholder), `label.programmatic` (it is the accessible name).
**Redundant entry**: within a flow, a field whose `value_id` matches an earlier field of the same
flow records that field in `repeats`; `prefilled` when it arrived filled, `same_as_offered` when a
"same as" control was offered.

`auth.cognitive_test` names a test met while signing in: `puzzle`, `transcription`, `memory`
(recalling something the browser or a password manager cannot fill, such as a security answer; a
password or code field that allows paste and autofill is not a memory test), `object-recognition`,
or `personal-content` (the last two are recognition tasks, not recall), or `none`; `alternative`
when another sign-in method without such a test exists.

## States

For each data surface the driver attempts every state the plan and task make reachable, and records
one state probe per attempt, including attempts where nothing distinct appeared (`shown: false`).
Inducers: `fixture` (empty and partial data from the stub), `action` (a successful user action, for
`success`), `delay` (the `slow` profile), `fail-5xx`, `fail-network`, `offline`, `hang`, `forbidden`,
`not-found`. A relevant state the driver could not induce makes the `states` coverage `partial`.

A **data surface** is found from the page load: each GET the page sent with `fetch` or
`XMLHttpRequest` that got a response is one surface. Its box is the section in `main` whose id,
marker (`data-state-surface` or `data-surface`), first heading, or accessible name contains the
request path's last segment in the singular, else a section that holds a list or table, else a list
or table in `main`, else `main`. A state may re-render the surface under another DOM path and so
another box id; the driver finds it again by marker, then heading, then position among elements of
the same tag in `main`. When the surface is gone, the probe observes what `main` shows in its place,
so a surface that disappears is recorded too (`shown`, `blank`).

- `on_action`: the state appeared in response to a user action (a search, a submit, a filter),
  not with the page load.
- `shown`: the surface renders something the user can tell apart from its resting state.
- `same_as`: other states of the same surface whose rendering is indistinguishable (visible text
  identical after normalization and the same boxes shown).
- `blank`: only persistent chrome remains.
- `indicator`: what showed while waiting; `indicator_delay_ms` from the request to its first paint,
  `indicator_shown_ms` how long it stayed.
- `scope`: what the wait or failure blocks (`object`, `region`, `page`).
- `problem_text`, `recovery_action`, `recovery_works` (the action leads to a working state once the
  injection is lifted), `announced`, `input_kept`.

## Urgency claims

Candidates are boxes whose text matches a countdown (`mm:ss`, `hh:mm:ss`, days and hours), an
absolute deadline, a hold the page names as one (a seat or item held for you), a stock claim ("N
left"), a demand claim ("N people viewing"), or an activity notice ("someone just bought"), in any
locale of the plan. `value` is seconds remaining for countdowns, deadlines, and holds, and a count
otherwise. An absolute date or time that names no zone is read in the context's `timezone`, and a
date without a time runs to the end of that day. Korean `N일` counts days only before an hour count
or `남` (remaining), so a date such as `9월 30일` is not a claim. `backed` is true when the value or
event matches the stub's fixture data (a deadline, a stock level, a recorded purchase); a number or
event that exists only in the page's code or template is not backed. Counts are compared by number
alone: the fixture's records carry no item identity, so a count that matches any listed item is
backed. The stub evaluates fixture deadlines and holds on the shared controlled clock.

Readings: `load` (always present); `later` (30 s of controlled time after the load reading);
`reload`; `fresh-profile` (a new profile); `after-expiry` (the clock advanced past zero plus 5 s).
Before the reload and fresh-profile readings the driver advances the clock by at least 120 s and
twice the display resolution, up to seven days, so a timer that restarts per visitor shows it.
`elapsed_ms` is time on the shared controlled clock since the load reading. `resolution_s` is the
display's granularity (1 for `mm:ss`, 60 for minutes, 3600 for hours, 86400 for days).

- **`derived.resets`** (countdowns and deadlines): some reading taken later, after reload, or in a
  fresh profile shows more time than the load reading minus the elapsed time, by more than the
  larger of 2 s and the readings' resolution. Holds never count as resets.
- **`derived.drifts`** (stock, demand, activity): the load, later, reload, and fresh-profile readings
  do not all agree. The driver buys nothing between readings and is the backend's only client.
- **`at_expiry`**: `offer-ends` (the price or offer changes or closes), `restarts`, `unchanged`, or
  `not-reached` (the end is more than seven days away).

## Time limits

During each flow the driver idles and advances the controlled clock to the next scheduled timer, one
timer at a time, checking the page after each, until 20 hours have passed. A limit is found when the
page ends the session, releases a hold, or discards input. `limit_s` is when that happened.
`warned` when a warning appeared before it, `warn_lead_s` how long before, `extendable` when the
warning offered a simple way to extend, `extensions` how many times extension worked (tried up to
ten), `turn_off` and `adjustable` when settings reached before the limit let the user switch it off
or lengthen it at least tenfold, `input_after_expiry` what happened to entered values.

## History

- **Back** from a page reached by navigation: `restored` records whether filters, pagination, scroll
  position (within 100 px), entered values, and selection came back.
- **Back from the entry page**, arriving from a blank start page: up to three presses. `left_page`
  when the start page is reached, `presses` how many it took, `overlay_closed_first` when the first
  press closed an open overlay and `overlay_opened_by` whether the user or the page had opened it,
  `pushed_entries` history entries the page added without a navigation by the user.
- **Reload** of a page reached by a form submission: `resubmit_prompt` when the browser offered to
  send the form again.
- **Deep link after sign-in**: open a protected route signed out, sign in, and record where it lands.

## Pointer

- **Drag, path gestures, multipoint gestures**: boxes that change state from pointer movement
  (sortable lists, sliders, swipe actions, pinch). `alternative` records a single-pointer way to
  reach the same result without dragging: `buttons`, a `menu`, or an `input`; `keyboard-only` when
  only keys offer another way, `none` when nothing does.
- **Hover reveal**: each interactive box is hovered; boxes that appear are `revealed`.
  `on_focus_too` when keyboard focus reveals them as well; `obscures` when they cover other content;
  `dismissible` when Escape hides them without moving pointer or focus; `hoverable` when moving the
  pointer onto them keeps them; `persistent` when they stay 5 s while hover remains.

## Motion and scrolling

- **Motion window**: 5 s at rest, sampled with `document.getAnimations()` and 10 fps frame diffs.
  `moving` lists boxes that moved; `kind` says how (`opacity` for fades); `travel_px` is the largest
  displacement; `essential` when the motion conveys the content itself. A video is essential only
  when it plays after a user action of the driver, so video moving in the window at rest (autoplay,
  a background video) is not. A canvas is essential when it is presented as content and is not
  decorative: not `aria-hidden` itself or through an ancestor, not covered at its center by another
  element, and either inside a `figure`, or with role `img`, `figure`, or `application` and an
  accessible name, or with an accessible name (`aria-label`, `aria-labelledby`, `title`) that names
  a chart, graph, plot, map, visualization, or diagram (in English or Korean). Nothing else is
  essential. With `compare_to`, the probe ran with reduced motion and the other context without.
- **`auto_moving`**: content that moves by itself (marquees, auto-advancing carousels), observed for
  up to 60 s; `seconds` how long it kept moving without input, `pause_control` a reachable pause or
  stop.
- **`hover_media`**: images and videos hovered, and how many of them transform on hover.
- **`scroll_reveal`**: boxes hidden at rest (opacity near 0 or clipped) until scrolled into view,
  and the delay between entering the viewport and becoming readable.
- **`input_blocked_ms`**: the longest time an input was ignored while an animation ran.
- **Scroll probe**: runs with no dialog open and at least three times the expected distance left to
  scroll. Three inputs of one kind (wheel 100 px, Space, ArrowDown, or a touch flick). `expected_px`
  is what the browser scrolls by default for those inputs: the driver replays the same three inputs,
  pointer at the viewport's center, on a blank page 20000 px tall in the same context (in Chromium,
  for three inputs: 300 px by wheel, 120 by ArrowDown, and by Space 2412 at `m` and 2580 at `d`).
  `actual_px` is what happened; `snapped` when the document scroller snapped to section boundaries; `blocked`
  when it did not move; `animated_ms` how long the page kept scrolling after the last input.
  `derived.ratio` is actual over expected.

## Permissions and media

The driver wraps the permission APIs (Notification, geolocation, camera and microphone, clipboard
read, persistent storage). `user_gesture` is `navigator.userActivation.isActive` at the call.
`after_denial` when the page asks again after the driver denied it; `preprompt` is a custom dialog
shown just before the browser prompt.

Media: `autoplay` when playback started without a user gesture; `audible` when it played unmuted at
non-zero volume (or an AudioContext produced output); `audible_s` the seconds of audible playback
observed, up to 10, loops included; `controls` when a pause, stop, or volume control is reachable
by pointer and keyboard.

## Flows

The driver runs each flow in the plan's `flows` until `done` matches (the route glob, where `*`
matches one templated segment, or the visible text), choosing actions toward the goal. An exit flow
with a `pair` starts where its pair starts, so finding the way out counts as effort; its own `start`
is used only when it has no pair. The driver stops as `blocked` when no action advances, `dead-end`
when a screen offers no way forward or back, and `abandoned` after 40 actions.

**Action choice** is deterministic. With a dialog open the driver considers only the dialog's
controls, otherwise only controls outside dialogs. It first fills one empty field that is required,
or, once no untried forward control is left, an empty name, email, phone, address, postal code,
card, or password field, with the fixture's `valid` value of that kind; without such a value the run
stops as `blocked` with a `note`. Otherwise it ranks the enabled controls not yet tried on this
screen, leaving out fields, checkboxes, radios, switches, and `tel:` and `mailto:` links: 30 points
when the accessible name shares a word with the goal or the flow kind's vocabulary (for `purchase`:
buy, checkout, continue, pay, place, order) and 5 more per shared word, where a Korean word shares
a goal word of two or more syllables when it begins with it (해지하기 shares 해지); 14 for forward
wording (continue, next, checkout, confirm, submit, pay, and the like; cancel wording is forward
only in an exit flow); 4 inside `main`; 30 fewer for back wording and, outside a dialog, 25 fewer
for sign-in, support, or help. On a screen that offers a confirm control (confirm, submit, save,
done, OK, and the like), a control whose whole name, punctuation aside, is cancel, close, or put-off
wording (Cancel, 취소, Not now) gets neither the forward points nor the goal-word points; a name
with more words (Cancel subscription, 구독 취소) keeps them. In a dialog, confirm, continue, accept,
yes, okay, close, or dismiss wording adds 20, and a decline (no thanks, decline, not now, maybe
later, skip, leave) adds 100 when the dialog is an optional offer (its text speaks of an offer,
retention, upsell, marketing, cookies, a discount, or staying). A dialog that asks for consent the
flow needs, such as agreeing to terms or a required item, is not an offer, even when it also offers
optional consent such as marketing; the word consent alone does not make a dialog an offer.
Put-off wording is a phrase that puts the offer off (maybe later, remind me later), not a word
inside another action (pay later, save for later). The highest score wins, earlier in document
order on a tie; when no control scores above zero the run stops. An action after
which the path, the main region's text, and the open dialog are all unchanged is not tried again on
that screen.

- **Steps**: a new step starts at a new URL path, when a dialog that must be answered opens, or when
  the main region is replaced (its text changes by more than half). The screen that satisfies `done`
  is recorded as the last step with no actions. `back_available` when the step offers an in-page way
  back.
- **Interactions**: actions of kinds click, tap, key (activation keys only; Tab and arrows used to
  move focus do not count), type (one per field), paste, select, check, uncheck, and drag.
- **Effort**: `steps` counts steps with at least one action; `interactions`; `fields` filled;
  `single_field_steps` the longest run of consecutive steps whose only input was one field;
  `offers` (retention, upsell, cross-sell, or survey blocks shown between start and done) and
  `blocking_offers` (the way forward stayed hidden or disabled until the offer was answered);
  `reauth` when the flow asked for the password or a code again; `channel` how the flow could be
  finished: `self-serve`, or only by `phone`, `chat`, `email`, or a `request-form` that promises a
  later human action.
- **Dead end**: a step with no enabled control that advances or goes back other than browser Back,
  including an error with no recovery action.
- **`commit_step`**: the step whose action charges, subscribes, reserves, cancels, or deletes.
  **`review_before_commit`**: a step at or before the commit shows the total and the chosen items or
  terms with a way to change them.

**Prices** are recorded at every step that shows money; a total shown on a step is a component of
kind `total`. Components keep a stable `key` across steps. `state` is `known`, `pending` (shown as
to be calculated), or `estimated` (shown with an amount marked as approximate). `mandatory`
components cannot be removed without abandoning the purchase. `user_caused` when user input since
the component's last observation added or changed it (a delivery method, an address entered on an
earlier step that now sets shipping or tax, a quantity). Components are the charges the order would
carry if committed at that step; unselected options are not components.
`placement` as for disclosures below. `cadence` for recurring charges; `other` is a recurring period
not listed (every four weeks), and `once` a one-time charge.

**Cart** lines record who added them: `user` (the user's own add action), `preselected` (a
pre-checked option the user left alone), `system` (appeared without any control the user touched).
`removable` when the line can be removed in place.

**Disclosures** of material terms, one entry per kind: `placement` is the best placement the term had
at or before the commit step, in this order: `near-commit` (on the commit step, without expanding,
within one viewport height of the commit control), `primary` (in the main decision area at body size
or larger), `secondary` (visible without expanding, elsewhere), `collapsed` (behind a disclosure or
accordion), `tooltip`, `after-commit`, `absent`. `step` is the first step with that placement.
`at_commit` when the term is readable on the commit step without expanding anything.

**Gates** are requirements before continuing: `account`, `sign-in`, `identity`, `payment`,
`address`, `age`, `reauth`, `optional-consent` (an optional consent that must be given to
continue), `permission`, `share`, `install`, `survey`, `contact` (the flow must continue through a
support contact). `declared` when the kind is in the plan flow's `requires`.

**Hints.** A page may mark elements with optional hints, like `data-lapis-signature` in the render
extract: `data-lapis-price` (component kind) with `data-lapis-key`, `data-lapis-state`,
`data-lapis-mandatory`, `data-lapis-cadence`, and `data-lapis-placement`; `data-lapis-cart-line`
(line key) with `data-lapis-added-by`; `data-lapis-disclosure` (term kind) with
`data-lapis-placement`; `data-lapis-gate` (gate kind) with `data-lapis-skippable`; and
`data-lapis-offer` (offer kind) with `data-lapis-blocks`. A hint only locates and groups: a hinted
element is read even where the reading above would not look, and `data-lapis-key` and the cart-line
key become the component and line `key`. Everything else (kind, state, mandatory, cadence,
placement, added_by, skippable, blocks) comes from the reading above, exactly as on a page without
hints. When a hint's value differs from that reading, the observation lists the differing field
names in `hint_mismatch`. When the reading finds nothing for a hinted element (its wording names no
term, fee, or total; the step shows no gate of the hinted kind; its text reads as no offer), the
observation keeps the hinted kind and lists `kind`. A component without a cadence reading counts as
`once`. Detectors do not judge an observation with `hint_mismatch`, whether it would pass or fail:
they report it as a skipped finding with evidence `not-verified` and judge the others. Probes work
without hints.

**Derived** (`flow_run.derived`):

- **`drip`**: the first price step is the first step showing a known item price. A component seen at
  or before it is disclosed when its placement was primary or secondary (as known, estimated, or
  pending). After it, a component that is not user-caused is drip-priced when it is a mandatory
  charge (fee, shipping, tax, deposit, recurring) that was not disclosed; when a mandatory charge, an
  item, or the total rises above its last amount; when a charge that was only ever pending becomes an
  amount; or when a discount shrinks, or leaves a step that shows a total. A mandatory charge still
  pending on the last price step at or before the commit is drip-priced too. Amounts are compared
  only within one currency.
- **`sneaked`**: cart lines added by `system` with an amount above zero.
- **`hidden_terms`**: only for flows with a recurring charge (a `recurring` component or a cadence
  other than once). Required terms are renewal price, cadence, and cancellation method, plus trial
  end and trial conversion when `trial` is true. Renewal price, cadence, and the trial terms are
  hidden unless `at_commit`; the cancellation method is hidden unless shown (near-commit, primary, or
  secondary) at or before the commit step. Other disclosure kinds are recorded but not required.
- **`exit`**: for exit flows (cancel-subscription, delete-account, withdraw-consent, unsubscribe)
  whose plan `pair` completed in the same context: `extra_steps` and `extra_interactions` (this flow
  minus the pair), and `added_reauth` (this flow asked for reauthentication, the pair did not, and the
  exit flow does not list `reauth` in `requires`). Without such a pair run, the comparison is
  reported as skipped. Deriving `exit` needs the plan's flows.

## Console

Errors and warnings from every context: uncaught exceptions, unhandled rejections, hydration
mismatches (framework messages that say server and client output differ), failed requests, and CSP
violations. Messages are redacted as described under Scope and safety.

## Coverage

One entry per probe: `ran`, `partial` (some contexts, states, or steps could not run; `reason`),
`skipped` (did not run; `reason`), or `not-applicable` (nothing on the page for it). An empty probe
list with `ran` means the probe looked and found nothing.

Detectors report every hit they observe as `open`, whatever the coverage. When a probe a detector
depends on (its `probes` in `slop/detectors.yaml`) is `partial` or `skipped`, the rule also gets one
`skipped` finding with evidence `not-verified` naming what did not run, so a missing observation never
reads as a pass. A flow run with status `skipped` counts the same way for flow-analysis, and so does
a check whose input a probe that ran could not produce (the keyboard bypass checks with one walked
route per context), and a flow observation with `hint_mismatch` (Flows, Hints), which is reported in
place of any hit on it.
