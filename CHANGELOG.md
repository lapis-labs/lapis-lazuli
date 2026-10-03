# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/) once 1.0 is released. Before then, contracts are
`version: 0` drafts and may change between minor versions.

## Unreleased

### Contracts

Local contract changes, made here and not from a kit diff; the handoff records each one with its before and
after text.

- `slop/rules.yaml` (186 rules, 91 detectors): every `keep_when` entry is `{ id, when }` with an id that is unique
  within its rule (140 entries in 99 rules); `type.overused-neutral-grotesque` gains the case `won-comparison`; the
  new rule `plan.uncompared-decision` (domain `plan`, quality, gate in create mode, no waiver) and its detector
  `plan-candidates`. `slop/rules.schema.yaml` takes the new `keep_when` shape and the domain `plan`.
- `slop/rules.yaml` (197 `keep_when` entries in 137 rules): 38 of the 47 rules that are not requirements and listed no
  case now list one to three, each a condition the plan has to show: a contract that fixes the value
  (`contract-scale`, `contract-leading`, `contract-pair`, ...), a brief requirement (`brief-fixed-opening`), or an
  exception the plan can state and a reviewer can check (`cleared-secret`, `dvh-fallback`, `data-cells`, ...), among them
  all 12 rules that gate in create mode. Nine still list none, so a keep waives nothing there: `type.synthetic-style`,
  `type.ko.keep-all-missing`, `motion.transition-all`, `rights.license-hint-only`, `rights.generated-unreviewed`,
  `rights.unapproved-mark-symbol`, and the packages `ux.subscription-trap`, `ux.pressure-selling`, and
  `ux.consent-steering`; the way out of those is the fix.
- `plan/schema.yaml`: the top-level `explorations` and `keep_when` on a `defaults` entry; `plan/example.plan.yaml`
  records both, and `docs/examples` stay unfinished on purpose.
- `slop/rules.yaml` and `slop/rules.schema.yaml`: each of the 175 `keep_when` cases on a rule that takes a keep lists
  `evidence`, the alternatives a plan can hold for its premise (a `design` token, a quoted line of `brief`, a
  `material`, a `source`, a won `exploration`, a ledger `asset`, or a `plan` condition such as
  `brief.platform lacks web`), or `none`. 88 cases list evidence (50 accept a brief line, 28 a design token, 24 a
  plan condition, 16 a source, 4 a material, 4 a ledger asset, 2 a won comparison; a case may accept several) and 87
  list `none`: nothing a plan, a design contract, or the ledger holds shows their premise, so the keep waives on its
  reason as before and the critic reads it. The 22 cases on requirement and `scope: none` rules, which take no keep,
  carry no `evidence`. `plan/schema.yaml`: a `defaults` entry takes `evidence` (`design`, `brief`, `material`,
  `source`, `exploration`, `asset`); `plan/example.plan.yaml` cites the face that won and the world material.
- `plan/schema.yaml`: the optional top-level `approval` (`state: approved|assumed`, and a `reason` when `assumed`);
  `plan/example.plan.yaml` records it. `release/GATE.md`: the non-blocking finding `release.approval-assumed`, which
  lists a plan nobody approved for the user to confirm, and the section on failure records and `next`.
  `install/harnesses.yaml`: the plugin hook `stop`, the output `gate-extension`, and the harness mechanism
  `exit_gate`.

### Added

- `lapis/references/visual-assets.md`: image-job selection, protected crops and coherent sets, semantic icon contact sheets, and fact/inference/proposal separation for supplied assets.

- `explorations` in the plan records, for each open decision, two or more candidates with their sources (for type:
  `local`, `catalog:<name>`, `adobe`, `commercial:<foundry>`, `generic`), what they were compared on (`specimen`,
  `render`, `sketch`), the chosen one, and why the runner-up lost. A decision the contract or the brief fixes is
  marked `fixed_by`; `contract` holds only when `context.design` is set, and a type role whose `source` is
  `contract` is exempt only then too.
- `plan.uncompared-decision`: in a create plan, an open decision with no such comparison blocks. The open decisions
  are each type role, the palette, the layout, the motion dial, the direction, and the headline, subhead, and cta.
  For type it also blocks when every candidate is a generic family (`system-ui` and the other generic names, or
  source `generic`), or when the face was never compared on a specimen or a render. A `defaults` entry cannot lift it.
  `plan check --summary` prints each comparison and each decision the contract or the brief fixes.
- `behavior check --box ID` (repeatable) and `--limit N` narrow the per-box probes, `controls` and `pointer`,
  to the named boxes, or to the first N boxes of each context in document order. A probe that leaves boxes
  out has `partial` coverage whose reason says how many (and names any `--box` id that matched nothing);
  `commits`, which works from the controls that ran, says the same. `--box` takes ids from the session's
  `nodes`, and a control that only an action reveals is reached when the control that reveals it is named too.
- `lapis-design next --task <task> [--url PAGE] [--json]` returns the one step of the procedure still to take, with
  its exact command or schema, or `done`: `plan`, `plan-fix`, `plan-flows`, `plan-explorations`, `fonts-lock`, `stub`,
  `ledger`, `render`, `behavior`, `lint`, `critic`, `release`. It reads `release check --offline`'s classification
  of the files, so a missing input, an invalid input, a plan blocker, a narrowed report, a stale report, or a lint run
  that left out an input sends the agent back to the step that makes it. `done` means the procedure is complete, not
  that the gate passes: a blocking release report ends it too. The behavior check is started in the background with
  a log, and `next` waits for it. Without `--task` it takes `$LAPIS_TASK`, else the newest plan.
- Failure records: `render check`, `behavior check`, and `release check` write
  `.lapis/attempts/<task>/<step>.json` (reason, command, exit, time) when a full run cannot start because the browser
  is missing or will not start, or the sandbox denies a path. `next` counts a record newer than the step's inputs as
  that step done; an input error, a timeout, a finding, and a plan blocker are never recorded. A harness that cannot
  start a separate context for the critic records it with `lapis-design next --unavailable critic --reason ...`, and
  the gate still reports the critic as missing.
- Exit gates: `lapis-design hook stop` is the `Stop` hook of the lapis plugin in Claude Code and Codex, and
  `exit-gate.ts` is its `session_stop` (Oh-My-Pi) and `agent_before_settle` (pi) extension. Only with
  `LAPIS_UNATTENDED=1` does it continue an agent that is about to stop with the step `next` returns, at most three
  times in a row for one step and fifteen in a session, then it lets the agent stop and records the step left in
  `.lapis/gate/<task>.json`; otherwise it prints one line and never blocks. An unattended run that wrote no plan is
  continued to write one (step `plan`, task named for the project folder unless `LAPIS_TASK` is set), under the same
  limits. Codex runs the hook only once you trust it in `/hooks`; an untrusted hook is skipped without a message.

### Changed

- `lapis` and `ultramarine` open with a short Done block: done is when `lapis-design next` says done, a missing or
  invalid input is never done, a blocking release verdict is a result to report, a run with nobody to ask records
  `approval: {state: assumed, reason: ...}` and goes on, and checks on 127.0.0.1 are not network use. The plan gate
  records `approved` once the user approves.
- README and INSTALLATION recommend reasoning or thinking at high or above for the agent that makes the work,
  because a low setting skipped the procedure in our runs, and describe unattended runs and the Codex hook trust.
- Recovered direction guidance bounds mixed influences by ownership, adapts native behavior without
  equating platform units, preserves maintained stacks, and carries compositional relations into
  real-content production rather than copying study dimensions.
- UX guidance distinguishes walkthrough, participant, regression, and analytics evidence; records
  contextual constraints without invented persistence or delegated authority; and specifies notification
  usefulness, effective permission, deferred delivery, badge lifecycle, and current-state deep links.
- System and asset guidance separates single-source observations from proposed UI roles, preserves
  snapshot unknowns and losses, and makes icon directionality, delivery failure, notices, and state
  semantics explicit. No plan, rights, access, telemetry, or automated-coverage contract changes.
- Recovered branch-specific procedures live in references, including implementation and notifications;
  the `lapis` and `lps-ux` skill bodies keep only conditional pointers to them.

- Direction explorations distinguish controlled tuning from whole-relation hypotheses, choose the smallest disprovable specimen, and converge by consequence rather than novelty.

- Research notes choose comparison media by their evidence claim and pair each transferred relation with a local disproof; requested-page access policy remains unchanged.

- Form levers gain blocked-question method selection, one expressive/quiet comparison with concrete failure conditions, and temporal structure choices before motion.

- Inspection guidance gains risk-based manual accessibility samples and task/assistive-technology, zoom, clipping, and keyboard evidence limits; automated release coverage is unchanged.

- Data visualization guidance gains encoding-cost tradeoffs and a selection-by-selection manual equivalence check, without expanding machine coverage claims.

- Forms guidance gains compound-field target ownership and dependency-led stages with honest branch progress; the immediate-switch commitment proposal remains outside the contract.

- Copy guidance routes complaints to wording, order, placement, or visual treatment before editing and frontloads differentiators without imposing English grammar.

- Layout and token guidance gains conflict-led grouping comparisons, bounded contour construction, and structural separation choices rather than blanket cards, shadows, or flatness.

- Motion guidance chooses acknowledgement targets and waiting feedback from accepted input, measured work, and usable context, with reduced-motion cues preserved.

- Color guidance gains variable-matched dominance studies and goal-led physical renditions without changing OKLCH masters or adding profile operations.

- Type guidance gains descriptive display lanes, complaint-sized comparisons tied to `explorations`, and a copy-owned meaning pass before typesetting.

- The critic gains paired earned/unearned grouping examples and a content-level test for replacement-package repairs.

- A `defaults` keep waives a finding only when its `keep_when` names one of the rule's ids, in `plan check` and in
  `slop lint`. A keep with no id, an id of another rule, or an id nobody lists leaves the finding at its severity,
  and the message lists the accepted ids. A rule that lists no `keep_when` case takes no keep (nine rules that are not
  requirements list none), and a requirement or a rule whose waiver scope is `none` takes no entry at all: a reject
  no longer lowers such a plan finding to INFO. The `fix` text of an undecided finding lists the ids.
- A `defaults` keep also needs the evidence its case lists, in `plan check` and in `slop lint`. The skill-only run in
  the gate experiment kept `color.terracotta-accent` as `brand-color` with `context.design` null and an orange it
  authored itself, and the blocker became INFO; now that keep stays blocking and the finding says `keep_when
  'brand-color' needs evidence`: `evidence.design` (a token of the file `context.design` declares, found in its
  text) or `evidence.brief` (a line quoted from `brief`). A `won-comparison` keep needs `evidence.exploration`, the
  face that a complete type comparison in `explorations` chose for a role that uses it. A case that lists `evidence:
  none` waives on the reason alone, as before. `slop lint` reads the declared design file from the working
  directory (`Context.design_text`); `plan check` reads it under `--root`. The ledger asset cases are checked in
  `slop lint` only, which gets the ledger; no plan-layer rule lists one.
- The `lapis` skill and `type.md` say that a brief's no-network, no-external-assets, or offline line limits what the
  page ships, never what is explored. Type has explicit exploration steps (`lazuli local fonts`, `lazuli search`,
  `lazuli catalog sync`, a specimen of the page's real copy captured with `render check`), a generic family is a
  choice that must win a comparison, and direction, palette, layout, motion, and key copy each get a comparison
  step, a self-review pass at the plan gate, and a line in the critic's vision check.
- A narrowed run writes beside the full report and no longer replaces it. `render check --width` writes
  `.lapis/renders/<task>.narrow.json` with its screenshots in `<task>.narrow.shots/`, and `behavior check` with
  `--probe`, `--context`, `--box`, or `--limit` writes `.lapis/behavior/<task>.narrow.json`; full runs keep
  `<task>.json`. A narrowed run given the full path with `--out` is refused (exit 2) before anything starts,
  because the release gate reads that path as the evidence of a full run; any other `--out` still wins.
  `slop lint --layer` and `--rule` have no task-derived path, so write them with
  `-o .lapis/lint/<task>.narrow.json`. The release gate reads only the full paths. The repair loop, the
  `lapis`, `ultramarine`, `ulm-maintain`, and `ulm-release` skills, and `--help` say so.
- `behavior check` takes box snapshots in about a third of the time (104 ms to 38 ms on the pilot pages) and
  looks at an unchanged page once: the capture no longer hands over the text runs and styles that the driver
  never reads, the attribute events of the DOM domain are off while the tree is read, the boxes that carry a
  single control and the place of each changed box are asked of the page in one call each, and a snapshot
  stands while the document, its mutation count, its scroll position, the controlled clock, and the events
  that reached it (input, focus, scroll, transitions, animations, fonts, loads) are all unchanged, so a hover or
  focus reveal with no mutation is still seen. The session JSON is the same as 0.2.0 wrote, apart from timings;
  those snapshot changes made the two pilot pages' full runs take 78% and 84% of the time and `flows` about 62%,
  before the settle-window change below.
- The motion probe's scroll reveal no longer waits in real time for a box that nothing can reveal. For every box
  hidden at rest it moved the page clock 100 ms and slept 100 ms, up to 51 times; the clinic pilot page has nine
  such boxes that never reveal, in four contexts, and the probe took 253 s. The clock now moves 100 ms a step
  with no real wait while no transition or animation reaches the box or an ancestor and no request is pending,
  and follows real time as before once one does. `reveal_delay_ms` is still the controlled time from the box
  entering the viewport to its being readable, and a box a timer reveals reads the timer's delay. The probe's
  output on the two pilot pages is the same, and the clinic page's takes 48 s.
- The settle window again measures the page's controlled time: the clock follows real time while a request is
  pending, an animation or media element runs, the document is loading, or the page changed in the last 100 ms.
  In the quiet remainder it advances 16 ms per poll without waiting. A page that constructs a Web Worker or
  SharedWorker, compiles or instantiates WebAssembly (including the synchronous constructors), or registers a
  service worker keeps real-time settling for the rest of the run; that work finishes on a clock the driver
  does not control. `settle_ms` records controlled milliseconds, while `t_ms` remains real time since load.
  On the stillvault and clinic pilot pages, isolated `controls` probes take 133 s and 332 s rather than 266 s
  and 534 s. The contract wording is proposed separately; `src/shared/behavior/DERIVED.md` is unchanged.

## 0.2.0 (2026-10-02)

Direction: the plan's form levers must be tied to the subject, a font left to the platform counts as a
choice, and the repair loop has an end. Five new references and one new rule.

### Contracts

- Contract diff 6: the rule `layout.unanchored-lever` and its detector `plan-anchored-text` (185 rules,
  90 detectors), the plan schema's direction fields, the generic families in `fonts/system-fonts.yaml`,
  and the example plan.

### Added

- `layout.unanchored-lever`: in create mode, a `direction.levers` sentence that shares no word with
  `world_materials` or `layout.signature` blocks the plan; no levers at all also blocks unless the
  surface only operates. Redesign, repair, and `style_frame: inherit` are skipped, and a `defaults` entry
  lifts the block. `plan check --summary` prints the concept and each lever.
- `lapis/references/form-levers.md`, the direction principles, and new step 3 and 4 sentences in the
  `lapis` skill.
- `lapis/references/style-bento-and-modern-saas.md` and `style-minimalism-and-editorial.md`: what each
  style assumes about the content, mapped to plan fields and checks.
- `type.md`: "Choosing a face for each role", including activated Adobe Fonts as candidates (locked
  with `adobe-web-project` for the web).
- `ultramarine/references/repair-loop.md`: bounded repair rounds per task, per finding, and for the
  critic; one cause per change with its own recheck; a final full run after narrowed runs; what a host
  browser can stand for.
- `ultramarine/references/check-bounds.md`: the thresholds and word lists the checks use. The generating
  references (`motion.md`, `data-viz.md`, `forms-and-recovery.md`) now describe in words what the checks
  read and leave out.

### Changed

- A role set to a generic family (`system-ui`, `sans-serif`) counts as the platform's own neutral
  grotesque, read from one generic-family table in the plan, source, and render checks. A web plan
  whose text roles are all generic now meets `type.overused-neutral-grotesque` and
  `type.single-neutral-sans` instead of an INFO that the family was not measured. `font.no-lock` names
  the faces to lock.
- A plan with `style_frame: named` and no `style_name`, or a role `family` holding a comma-separated
  stack, fails the schema; fallbacks go in the fonts lock. The plan version stays `0`.

### Known limits

- `layout.unanchored-lever` blocks a concrete lever that names no material ("asymmetric two-column split
  with a narrow left rail"), and an English lever against Korean materials; tie it to a material, move it
  to the layout procedure, or record a keep. It passes a vague lever that shares one word with a material,
  and it shows only that a lever names a material, not that the lever is good; the critic judges that.
- `src/shared/index.yaml` still says 184 rules; the count changes with the next contract diff.

## 0.1.4 (2026-10-02)

The behavior probes read wording, choices, exits, urgency, and quotations as contract diff 5 says; the flow
driver makes the choices a screen requires; the release gate tells defects from missing evidence.

### Contracts

- Contract diff 5: wording and urgency rules, the flow driver's choices of required radios and terms
  checkboxes, kinds and outcomes, status text, unread links in the report scope, and the release gate's
  `defects`, `no_evidence`, `to_confirm`, and `not_run` counts.

### Changed

- The flow driver makes the choices a screen needs. After it has tried every forward control, it ticks
  each required terms, privacy, or age-confirmation checkbox and answers each required radio group, in
  document order, then tries the screen's controls again. A group that asks for agreement gets the
  agreeing option; any other gets the first option that turns the offer down, else the first with no
  amount above zero, else the cheapest. Optional items, select-all checkboxes, switches, and checkboxes
  whose name carries marketing, an add-on, or an amount are left alone. Each choice is a `check` action
  with `choice` set and is replayed with the step.
- `slop lint` does not follow folder links in the source tree either, and lists them with file links in
  the report's `scope.unread_links` (`source`, `corpus`; a folder ends with `/`). The release gate raises
  `release.layer-missing` when `unread_links.source` is not empty. The MCP `slop_lint` result carries the
  same field.
- The release gate's summary counts `defects`, `no_evidence`, `to_confirm`, and `not_run`
  (`blocking = defects + no_evidence`, `total = blocking + to_confirm`), and its output says defects and
  missing evidence apart and names what did not run. `plan check` and `slop lint` summaries gain
  `skipped`; their output line adds `N skipped: not judged` when there are any.
- A bare `mm:ss` is an urgency claim only when its value falls between the load and the later reading;
  with no claim left, `urgency` coverage is `not-applicable`.
- With a plan, colors the render guesses as `data` count as accents for `color.competing-accents` unless
  the plan lists `data_scales` or a `role: data` color.

### Fixed

- Wording: "You are no longer subscribed" and "Order no 1234 confirmed" are no longer failures. Refusing
  consent (do not agree, I don't agree, disagree, deny, do not allow, continue without accepting, 동의 안 함,
  동의하지 않고 계속, 필수 항목만 동의, allow necessary cookies) is a decline and earns no agree points, so
  the driver agrees to terms. A whole-name No, Never, 아니요, 싫어요, 안 할래요, or 나가기 is a decline,
  except in a dialog that asks about leaving itself. A required mark counts only on an agreement item.
  Put-offs are read by their shape (Ask me later and 나중에 볼게요 put off; Pay later and 나중에 결제 do not).
- Exits: in an exit flow, names that negate leaving (Don't cancel, Keep my plan, 해지 취소, 취소 안 함,
  유지할게요) back out and are not exit commits, and a dialog whose question is the exit itself no longer
  gets its stay side pressed. Unsubscribe, 구독 해지, and 주문 취소 commits are cancels; 수신 거부되었습니다
  and 삭제됨 complete an exit; "An unknown error occurred" is a failure; 알림 허용 안내 is not a refusal.
- Prices: flow and choice prices share one reader for `$`, `€`, `£`, `₩`, `원`, and `USD`, `EUR`, `GBP`,
  `KRW` before or after the amount, and for 월/연 before a price (`월 9,900원`) as well as `/월`, `매월`, and
  English periods. A fee that appears with a ticked terms checkbox is not `user_caused`.
- Labels with a link or button inside are pressed beside it, one press at a time; a press that leaves
  the page is not a check. A control the driver could not press is named in the flows coverage reason
  even when the run finishes, and an error after a press is no longer called unreachable.
- `ux.status-not-announced` reads only the text a box gained, and Korean results and counts; an
  always-visible label such as "Cart" no longer makes every change a status.
- Urgency: clock-time words count only next to the time (at, from, until, by before it; 부터, 까지 after
  it); 마감까지, 종료까지, and 만료까지 mean time is running out. Steps, characters, attempts, questions,
  tasks, and "left a/the" are not stock. Korean demand and activity need their subject (명이, 분이, a
  buyer). "for the next N hours", "2일 후 마감", and "마감까지 3일" are read; payment, cancellation, and
  refund periods are not. Numbers with commas are read whole, and Korean stock wording ("3명 남았어요",
  "잔여 좌석 2석", "재고 3개") is read.
- `copy.fabricated-proof`: after a quotation, a blank leads to an attribution only when what follows is
  name-shaped (a name, a name and place in brackets, or 2–4 Hangul syllables with 님, 고객님, or 씨); a
  Korean particle after the blank continues the sentence.
- `render check`: a run whose text still paints while the backdrop render hides text (an `!important`
  fill or stroke, a shadow tree's `::slotted` rule, an SVG fill) is left without a `backdrop` instead of
  one holding its own ink, for states too. `color(a98-rgb 1 1 1)` is a neutral white. The palette
  `data` role matches chart, graph, plot, and sparkline as whole words of the box's own class or id
  (`MuiTypography-root`, `paragraph`, and `hero-graphic` are not data) and reads an `svg` or `canvas` of
  48 px or more as a chart by role and accessible name, or by repeated marks with text labels. The
  `data-viz` and `motion` references no longer suggest naming elements to change a result.
- A source folder replaced by a link no longer passes lint with exit 0 and no warning.

### Evaluation kit

- `share.py` builds every exported file again from an allow-list of fields and field types instead of
  copying records and scrubbing known shapes; a field, key, or value outside the list never leaves.
  Reasons become `code` words, errors and file names become counts, `thread_id`, `pid`, and the Codex
  executable are dropped, and `prompt.txt` becomes `Task id: <id>` when it is the kit's own prompt.
- A `score.json` without a `font_db` record counts as not scored; `score.py --summary-only`,
  `share.py`, and `review.py` refuse it.
- `score.py` gives `slop lint` the plan and the fonts lock only when they resolve inside the project,
  and leaves the source layer unscored when the lint reports unread source links.
- `run.py` passes `-c features.apps=false` in every run, and `score.py` starts its checkers with the
  agents' environment allow-list.
- The evaluation wording test also reads code blocks, table rows, and `docs/eval/README.md`, and
  catches figures beside runs, tasks, findings, or tokens, "N of M", factors, and comparisons.

### Known limits

- A count of minutes or seconds alone ("5 minutes left", "5분 남았어요") and a time-of-day deadline
  without a date ("Sale ends 11:59 PM tonight", "오늘 23:59까지 주문") are not read. Korean stock with a
  unit outside the list (2대, 3벌, 5권) is not read.
- After a quotation, a dash, bar, or comma is still read as leading to an attribution
  (`“Export” — CSV, JSON, or PDF`).
- The flow driver ticks only required terms, privacy, and age checkboxes and answers required radio
  groups; a flow that needs an optional, marketing, or add-on item, a select-all box, or a switch ends
  `blocked`, and so does a group that asks for agreement but offers no agreeing option. Currency codes
  other than USD, EUR, GBP, and KRW are not read.
- The forms probe reads the kind of form, sign-in text, error reasons, cleared-field explanations, and
  same-as-offered text in English only; the media probe reads the control that starts a sound in English
  only; a flow kind's own vocabulary is English.
- A `primary` flow run that commits only on the client has no `commit_step`, so its recurring terms are
  neither judged nor reported as not verified.
- If Playwright's driver itself cannot start, the checks still print Playwright's error.
- The source registry's Adobe reasons and the comment of migration 0004 still state Adobe's terms as
  facts; they change with a later contract diff.
- `tools/reference-provenance.yaml` still lists 31 `verify_before_release` items.

## 0.1.3 (2026-10-02)

Adobe Fonts wording that reads as "usable, not reachable by file", fixes to the probes and renders the demo
pilot found, local HTML files served on loopback, clearer sandbox guidance, and contract diff 4. The probe
wording regressions listed under Known limits are fixed in 0.1.4.

### Contracts

- `behavior/DERIVED.md`: the wording exceptions, the exit-commit definition, `hidden_terms` of a run with
  no commit, `input_blocked_ms` recorded only, and how time limits reach a step. `render/DERIVED.md`:
  the page URL uses `http` or `https`. `slop/detectors.yaml`: the source-layer wording matches the
  engine. `behavior/stub.schema.yaml`: value ids are `v1`, `v2`, ….

### Added and fixed

- The Korean section of `lps-ux/references/forms-and-recovery.md` was confirmed by a native Korean
  reader on 2026-10-01 and again on 2026-10-02 after the identity, phone-number, and birth-date bullets
  were rewritten.
- `lzl-fonts/references/adobe-fonts.md` now opens by saying that activated Adobe Fonts are fonts like
  any other to recommend, choose, and lock (web delivery through the user's Adobe web project), and
  that its limits concern how lazuli and the agent reach Adobe's data: no file access, no extracted
  glyph data, nothing sent, no Adobe-derived values in training, evaluation, or tests. Its metadata
  lookup still never activates a font; the integration's search and recommendation tools may suggest
  families when the user asks, and a font is activated only on the user's request.
- `behavior check`: the time-limits probe moves one page forward through a flow run's steps, applying each
  recorded action once, instead of loading a fresh page and replaying a growing prefix of the run for
  every step. A page it has idled or typed into is
  still reloaded for the next step, so the limits found and their numbers are unchanged.
- `render check` now measures text backdrops, line ink extents (`density`, `symmetry`), and
  interactive-state colors on pages whose Content-Security-Policy sets `style-src` without
  `'unsafe-inline'`. The text-free render used an injected `<style>` that such a policy silently
  blocked, so every text run read 1.00:1 against itself and `color.text-contrast` fired on ordinary
  text; it now uses constructed style sheets, which the policy does not block. `color(a98-rgb …)`
  converts correctly.
- `behavior check`: a control no pointer can hit no longer times out for 30 s and skips its probe. A
  form control visually hidden behind a visible label (a clipped or 1 px radio or checkbox, an
  off-screen input) is acted on through its label or nearest visible wrapper and must change state; a
  link that only slides in on focus (a skip link) is focused, then pressed; a control nothing visible
  toggles or shows is recorded as `not reachable by pointer` in the probe's coverage reason. One
  control's failure is a gap in the controls, forms, and flows probes, and the other controls, forms,
  flows, and contexts still run.
- The urgency probe reads a count of days or hours as time left only when words beside it say so
  (left, remaining, ends in, 남음, 후 마감, or a cut-off such as "order within the next 3 hours"), or
  when days come with hours ("2 days 4 hours"). A period the page describes ("Keep 30 days of
  changes", "valid for 90 days", "14일 무료 체험", "24시간 고객센터") is no longer a countdown and no
  longer trips `ux.false-urgency`.
- `ux.hidden-subscription` no longer judges a flow run that reached no commit. Before, a local preview
  that never charged was flagged for terms "not readable at the commit" whenever the page showed a
  monthly price elsewhere; a declared `purchase` or `subscribe` flow with no commit is now reported as
  not verified.
- `INSTALLATION.md` and the `lapis`, `ultramarine`, `ulm-release`, and `lazuli` skills say what to do
  when an agent sandbox stops the checks from starting Chromium or reading lazuli's user cache: ask
  the user once, otherwise report the check as not run with the exact error; a host's own browser may
  supply `image` or `review` evidence but never a render or behavior record; and `LAZULI_DB` is never
  moved into the project. The Codex section gives the 0.159.3 flags and the error a headless
  `codex exec` under `workspace-write` showed in the 2026-10-01 pilot (0.159.2).
- `behavior check` and `render check` take an HTML file's path or a `file://` URL: they serve that
  file's folder read-only on 127.0.0.1 for the run (GET and HEAD only; nothing outside the folder, no
  dot-named files, no listings) and record the loopback address. Before, `behavior check` refused
  such a target (exit 2), and `render check` loaded it as `file:`, where root-relative links such as
  `/site.css` did not load and the extract was silently wrong. The `lapis` and `ultramarine` skills
  say so.
- `behavior check` runs the controls probe faster with the same observations: a snapshot reads every
  box in a few browser calls instead of several per box, and an unchanged page is not snapshotted
  again.
- The README example plans are available in `docs/examples/`; a DB-less CLI check verifies the
  console excerpts in both READMEs. The introductions distinguish render and behavior capture from
  linting their result files, and list `git` among the installation requirements.
- The installation guide explains browser-start and unwritable-cache limits in sandboxed and headless
  hosts, retains the sandbox permission guidance, and shows loopback serving and local file inputs.
  Codex's install and update blocks include the critic copy command; its checks also ask whether the
  installed critic file matches the release.
- Skill references correct claims about SVG contrast, drag direction, timeout alternatives,
  English-only form heuristics, and manual data-scale checks; clarify Korean identity and phone-number
  verification, consent, and date examples; and correct reference overlaps and migration metadata.
- `NOTICE` narrows the text-comparison claim to material published through 0.1.1; references added in
  0.1.2 and later were outside that comparison.

### Changed

- Stub value ids must be `v1`, `v2`, …, including values used by synthetic accounts. Other `values`
  keys (`patient-name`, `a:b`) or account references to them are refused when the stub loads, with the
  offending names and "value ids are v1, v2, …". Before, the driver received an id the session schema
  rejects, or a key with a colon failed later with a bare `KeyError`. Rename the keys under `values`
  and the `accounts` entries that name them.
- `render check` refuses non-HTTP(S) schemes other than a local HTML file path or `file://` URL,
  which it serves on loopback. `behavior check` follows the same policy; other schemes (`data:`,
  `about:`, `ftp:`, or a bare `localhost:3000`) are refused before a browser starts with one line
  explaining how to serve the folder on loopback. Both checks record only the loopback HTTP URL
  for local file inputs.
- `tools/calibration/calibrate.py` no longer prints the three comparison tables against older reports
  or the values written in its code; those reports counted Adobe Fonts faces. The next report is the
  new baseline.
- Wording only: Adobe's terms are written as lazuli reads them (not legal advice) in `AGENTS.md`, the
  `lzl-fonts` skill, the READMEs, and the `adobe-cjk` catalog message, with the note that the collection
  limit has nothing to do with recommending, choosing, or locking Adobe Fonts. The Adobe Fonts
  reference now says that a family name sent to a catalog lookup is not font data, that search and
  recommendation tools get only what the user said, that a font is activated only when the user asks
  for it, and that `render check` and `behavior check` do not block a page's own font requests while
  `lazuli ref capture` and `lazuli read --render` refuse the Adobe and Typekit hosts.

### Fixed

- The `hidden_terms` of a flow run that reached no commit step is empty. Before, the derived value
  listed every required term as hidden although no point where terms are due existed; the lint rule
  already skipped such runs, but the recorded session said otherwise. A `purchase` or `subscribe`
  run that showed a recurring charge and reached no commit is still reported by
  `ux.hidden-subscription` as not verified.
- When the browser is missing or cannot start (an agent sandbox, a missing permission), `render check`
  and `behavior check` print one line of their own and exit 2, instead of Playwright's
  `playwright install` banner (not on PATH after `uv tool install`) or its launch flags and logs.
  A missing browser gets the exact install command for the CLI's own Python; a browser that cannot
  start gets Playwright's first line and the advice to allow it or report the check as not run.
- A `..` after a symbolic link is judged from where the link leads. Paths were cleaned by text before
  any link was followed, so `lazuli lock --notice link/../…` could read a file in Adobe's font folders
  and a `LAZULI_FONT_ROOTS` entry spelled that way was accepted as a `user` root; both are refused now,
  like the link itself.
- `lazuli local fonts` stores design metadata again for a row whose `metadata_json` is empty, `{}`,
  `null`, or has no `axes` key, instead of leaving it to wait for `--rescan`; `measure` no longer fails
  on a stored `null`, a list, or text that is not JSON, and neither does `lazuli local fonts --family`.
- `tools/eval/score.py` runs its checkers with `LAZULI_FONT_ROOTS` set to an empty folder in its scratch
  directory, so no checker lists the fonts on the computer.

### Known limits

- A bare clock time (`09:30`) is read as a countdown.
- A countdown with time-of-day words, such as "마감까지 02:15:10", is not read.
- "3 steps left" and "250 characters remaining" are read as stock claims.
- Interface instructions containing quotations can be read as testimonials.
- "You are no longer subscribed" is read as a failure.
- "Ask me later" and "나중에 볼래요" are not read as deferrals.
- Acting through a label that contains a link can follow that link. The list of unreachable controls
  is reported only when a run does not finish.
- "Offer valid for 48 hours only", "Free shipping for the next 3 hours", and "48시간 한정 특가" are
  not read.
- The contract's Urgency paragraph will be aligned with the probe code in 0.1.4; urgency, action-choice,
  flow, and copy probe behavior is unchanged in 0.1.3.
- `tools/reference-provenance.yaml` still lists 31 `verify_before_release` items that await verification.
- Only browser launch is caught. If Playwright's driver itself cannot start (no Node binary, a blocked
  subprocess), the check still prints Playwright's error.
- A `primary` flow run that commits only on the client (no state-changing request) has no `commit_step`,
  so its recurring terms are neither judged nor reported as not verified; a `purchase` or `subscribe`
  run is reported.
- The source registry's Adobe reasons (`registry.yaml`: Adobe Fonts, Adobe Color, Behance) and the
  comment of migration 0004 still state Adobe's terms as facts; they are contract and data files and
  change with a later contract diff.

## 0.1.2 (2026-10-01)

Four new references, behavior probes that read Korean and exit flows as written, Adobe Fonts kept out
of calibration and evaluation, and a README that starts with what the tool prints.

### References and skill bodies

- `ultramarine` gains `references/inspection-and-evidence.md`: what a review may touch, what each
  evidence type can and cannot support, which route to take with only a screenshot, source files, a
  live site, a page that is not ours, or a native screen, how to record a finding and a user's report,
  and what to list as not checked.
- `lapis` gains `references/motion.md`: what the motion dial's three bands mean (feedback only,
  transitions that explain a change, authored moments), durations and easing by purpose as proposals,
  interruption and focus, scroll and route enhancement that keeps content visible at rest, a
  reduced-motion branch for each effect, choosing a layer and delivering authored animation, and what
  render check and the motion probe read for each motion rule.
- `lapis` gains `references/data-viz.md`: choosing a chart form from the question, honest scales,
  labels and uncertainty, dashboard region jobs, data color, text and keyboard access to a chart's
  values, build decisions, and what the checks do and do not read about charts. `layout.md` and
  `archetypes.md` point to it.
- `lps-ux` gains `references/forms-and-recovery.md`: fields from the goal, when to check and how to
  word what is checked, reading a server answer by cause, waiting and unknown outcomes, consent inside
  a form, Korean form conventions (new writing, to be read by a native Korean reader), the stub's
  values, and what the form, flow, commit, state, and time-limit checks do and do not read.
- The `lapis` body names example form levers, the asset ledger schema
  (`shared/assets/ledger.schema.yaml`), `--public` for capturing a live site of ours before a
  redesign, and that render and behavior checks and the critic do not run on a native screen.
- `lzl-fonts` says that `lazuli catalog lookup` sends an unmatched `adobe-sync` face's family name,
  and its Korean name where the system gives one, to Sandoll as the search term, and nothing else
  about the face; and that `family_class` means different things per `class_source`.

### `lapis-design`

- `render check` no longer stops on a page with a scroll-driven animation (`animation-timeline`);
  such an animation is recorded without `duration_ms`, since its computed duration is `auto`.
- `behavior check` starts every probe at the URL it was given, path and query included (a fragment is kept
  for driving too); before, the probes that only took the shared opener (motion, scroll, media, permissions,
  pointer, forms, states, dialogs, choices) loaded the origin's `/`. The session still records only host
  and path, never the query or fragment. A flow still starts at its own `start` route.
- The motion probe lists a box as `transform` whenever its position or transform changed, even while it
  also fades, and when a position property such as `left` or `margin` animates; before, any animation with
  `opacity` keyframes was `opacity`, so `motion.reduced-motion-missing` let an unguarded fade-and-slide
  pass. A fade that stays in place is still `opacity` and does not gate.
- Pause and stop controls of moving content (`pause_control`) and of media (`controls`) are read by
  accessible name and in Korean too (일시정지, 일시 중지, 정지, 중지, 멈춤, 멈추기; 음소거, 볼륨, 음량,
  재생 for media); before, only English words in a label or text counted.
- A dialog counts as asking for agreement only when its text asks (agree or accept near terms,
  `[required]`, 약관 동의, 필수 항목). An offer's own terms ("Terms apply", "혜택 약관"), "No card
  required", and the dialog's button names no longer make it required. Agree wording (Agree, 동의)
  wins where agreement is asked, and refusing wording (동의 안 함) never does.
- In an exit flow, the control named for leaving (Unsubscribe, Withdraw, Stop emails, Cancel plan,
  해지, 탈퇴, 철회, 수신 거부) is the confirm control, and 해지 ends a contract instead of backing out.
- Reject, 거부, necessary-only choices (필수 쿠키만 허용), skip, 건너뛰기, and leave form one shared
  decline list for flows, dialogs, and choices; 알림 받기 is an acceptance; 나중에 결제 is an action,
  not a put-off; refusing an add-on (옵션 추가 안 함, 없이) declines, and 추가 옵션 보기 customizes.
- Flows, states, time limits, history, commit focus, and the pointer probe read a control by its
  accessible name (a button's value, an image's alt); the pointer probe reads Korean step and menu
  words, and a plan goal matches Hangul words of two or more syllables.
- The flow driver no longer reads a postal-code field as a one-time code, and types a second address
  line from free text, so an address form no longer trips `ux.redundant-entry`.
- The commits probe reads "cannot be confirmed" as `unknown`; "Cannot be saved", "Nothing was saved",
  "No changes saved", "Not all items were saved", and "Your subscription was not cancelled" as
  `failure`; and the completed forms of leaving (unsubscribed, cancelled, withdrawn, deleted,
  해지됐어요, 취소됐어요, 탈퇴했어요, 삭제했어요) as `success` only for a commit that leaves something.
  After a payment, "Payment cancelled" is not a success.
- The urgency probe reads a count with the thing it counts ("Only 2 sites left", "2곳 남았어요",
  "잔여 2석", "마지막 1자리"), viewers with words between ("14명이 이 날짜를 보고 있어요", "14 people
  are viewing this site"), and "booked" notices. A look-back window ("최근 3시간 동안", "in the last 7
  days") is no longer a countdown, and a Korean activity count ("5명이 예약했어요") is read.
- The urgency probe no longer reads a clock time of day as a countdown: "입실 14:00부터", "11:00까지",
  "6:00 PM UTC", "6:00–7:00 PM", and "Doors open at 18:30" are not urgency claims, and neither is a
  time set apart in its own element inside such words; before, each was a countdown of minutes and
  seconds, and `ux.false-urgency` reported it as unbacked. A time with words that say it is running
  out ("ends in 14:59", "남은 시간 14:00") is still a countdown.
- `copy.fabricated-proof` reads a name after a quotation's closing mark as an attribution whatever
  separator it follows (a bracket, a middle dot, a bar, a slash, a comma, a blank, or a speech verb
  such as says), so such a quotation stays a lead in headings, display runs, labels, UI lines, and
  dialogs. Only a Korean, Japanese, or Chinese letter right on the closing mark (a particle) or a
  lowercase Latin word that is not a speech verb marks a sentence that carries on.
- `slop lint` no longer reads a source or corpus file that is a link resolving outside its folder, and
  warns on stderr.

### `lazuli` and Adobe Fonts

- `tools/calibration/calibrate.py` leaves Adobe Fonts faces (`adobe-sync`) out of every count, label,
  and sweep; its comparisons with older reports say those reports were made while Adobe Fonts faces
  were still counted.
- `lazuli lock --files` no longer lists a folder through a link in the project that leads into
  Adobe's font folders, and `--notice` refuses a path there; before, such a link was listed and a
  notice behind it was read.
- An Adobe Fonts face whose design metadata is not stored yet is not measured until a scan stores it,
  since its optical size axis is unknown.
- The localized-name helper accepts only a language tag (`ko`, `zh-Hans`) as its language.
- Every test starts with `LAZULI_FONT_ROOTS` set to an empty folder, and a source-level test keeps
  the Core Text calls on the allow-list.
- The source registry first refused `use.typekit.net`, `p.typekit.net`, and `fonts.typekit.net` in
  0.1.2. The 0.1.1 entry below is corrected to avoid attributing that refusal to the earlier release.

### Evaluation kit

- `tools/eval/score.py` needs `--font-db`, an evaluation font database built from OFL fonts only; the
  checkers run with `LAZULI_DB` pinned to it and a scratch home and cache, and `score.json` records its
  sha256 under `font_db`.
- Scoring, summaries, the export, and the blind review refuse a run whose event log shows a call to an
  Adobe tool.
- `share.py` no longer stops when the account is called `root`, `copy`, or `site` because of a JSON
  key, stops instead of rewriting an ordinary word when the account name is one, removes user names
  from paths and whole values only, and builds `summary.md` and `summary.csv` again from the cleaned
  records so no private skill name reaches them.
- Scoring and the blind review no longer take a site folder that is itself a link out of the project;
  `score.json` lists it under `site.skipped_roots`.
- `run.py --resume` counts a zombie as ended and names `kill -- -PID` when only the process group is
  left.
- `docs/eval/README.md` sets what evaluation and benchmark output may say and where: methods only, no
  results.

### Documentation, packaging, and CI

- The README opens with the `plan check` output for an example plan, then the install lines; the
  plugin table, harness table, and the rest follow, and `README.ko.md` has the same order.
- The Claude Code and Codex catalogs describe the repository as "Design skills for coding agents, plus
  two CLIs."; the package keywords list the repository topics.
- The generated `INSTALLATION.md` says, before the per-harness commands and under each harness's
  install step, that plugin commands do not install the CLI, and that hooks, extensions, and MCP need
  `lapis-design` on PATH.
- `NOTICE` states that the comparison covered the standards, guidelines, and agent-skill repositories
  the previous repository draws on, and that passages shared with the previous repository are the
  author's own writing.
- Workflow actions are pinned to commit SHAs with their version beside them; the cjk job runs every
  test but the browser ones; browser tests are split over four runners by recorded duration.

### Contracts

- `DERIVED.md` states how the probes choose an action in a dialog or exit flow, which commit kinds
  exist, how outcomes are read for an exit commit, and that the Typekit hosts are refused.

### Known limits

- The forms probe reads the kind of form, sign-in text (alternatives and cognitive tests), error
  reasons, cleared-field explanations, and same-as-offered text in English only. The media probe reads
  the control that starts a sound in English only. A flow kind's own vocabulary is English, and choice
  prices are read from $, €, £, and ISO codes, with recurrence from English periods.
- The flow driver never ticks a checkbox, so a flow with a required terms checkbox ends `blocked`. A
  409 or 422 comes only from a stub route with that literal status, and no probe presses one.
- The motion probe watches five seconds after load with no input and lists only boxes with a running
  CSS or Web animation, plus canvas, video, and image content that changes. Movement a script writes
  into styles every frame, a transition that a hover, press, or open starts, and shapes animated inside
  an `svg` are not seen, so `motion.reduced-motion-missing` misses them.
- `ux.gesture-only` drags a recognized target straight down and compares only that target's own group;
  `ux.status-not-announced` passes every changed result in an action once anything in it is announced;
  `code.unvirtualized-list` counts direct children, so a long table's rows are never counted; an
  unnamed inline `svg` chart reads as identity ink. Nothing reads `tokens.color.data_scales`.
- The urgency probe reads one claim per box and only counts that carry a unit or noun; it records a
  reservation hold timer but does not judge it, and recognizes look-back windows only in hours and,
  in English, days. A bare time such as "14:00" with no words around it in its box or the box that
  holds it is still read as a countdown.
- A quotation followed after a blank by up to ten words that start with a letter reads as an
  attribution, so an interface sentence that quotes a term and goes on stays a `copy.fabricated-proof`
  lead (evidence `not-verified`).
- A commit leaves something when its kind is cancel or delete, it belongs to an exit flow, or its name
  leads with Cancel, ends with 취소, or carries an exit action; another control that leaves something
  (for example "Clear all") reads its "cancelled" message as no claim.
- No check reads a screenshot, a recording, or a native screen, and `slop lint --source` reads web
  source only. The findings schema has no evidence type for a user's report; the reference writes it
  in `observed`.
- The calibration comparisons with older reports are not like for like: those baselines counted
  Adobe Fonts faces, and the current column leaves them out.
- `lazuli catalog lookup` sends an Adobe Fonts face's family name, and its Korean name where there is
  one, to Sandoll as a search term.
- The lint's link check covers files read by the tree walk; folder links are not followed or listed,
  and `node_modules/<pkg>/package.json` reads for the dependency check still follow links.
- Evaluation scores made in an account where Adobe Fonts are activated may include their shapes in
  page measurements (not checked); render in an account without them. One model session saw no Adobe
  tool; that is the model's own list, and runs that call one are refused at scoring.
- The Korean section of `forms-and-recovery.md` awaits a native reader.

## 0.1.1 (2026-09-30)

Font metadata for every local font, Adobe Fonts handled through the operating system only, and
install fixes. Contracts are unchanged.

- `lazuli local fonts` stores and shows, for every face, supported languages (by character
  repertoire, the same rule on every platform), variation axes, OpenType feature tags and vertical
  writing support, version, x-height, cap height, units per em, and the OS/2 family class. Adobe
  Fonts faces get these through Core Text only. Existing databases fill them on the next scan.
- `lazuli local fonts --origin system|user|adobe-sync` lists only the faces from one origin.
- On macOS, Adobe Fonts faces also store Korean, Japanese, and Simplified and Traditional Chinese
  family names where the font has them, read by short helper processes that ask Core Text in each
  language; before, only the system language was stored.
- The `lzl-fonts` reference `adobe-fonts.md` tells agents how to add Adobe Fonts metadata through the
  host's official Adobe integration, for display only; lazuli's font listing and measurement never
  contact Adobe, and the source registry refuses fonts.adobe.com. Refusal of the Typekit hosts was
  added in 0.1.2, not in this release.
- Adobe Fonts faces with an optical size (`opsz`) axis are no longer measured through Core Text, which
  sets that axis from the point size; they stay unmeasured ("optical size not pinned"), and
  `lazuli local fonts` says so in one line with their count. Files are unaffected.
- `NOTICE` ships next to the license texts: every plugin, skill, and Hermes folder carries it, and the
  wheel and sdist list it as a `License-File`, so a folder-only install keeps the third-party terms.
- `lazuli doctor` and `lazuli read --render` print the browser install command as
  `"<python>" -m playwright install chromium-headless-shell` for the Python that is running, which
  fits a uv tool, pip, and a checkout; before, they named `playwright` and `uv run playwright`.
- Reports from `lapis-design` and `lazuli` name tool version 0.1.1.
- Installs from the public repository were checked on 2026-09-30 in Claude Code, Codex, and Oh-My-Pi
  (all three plugins at the release commit, all eleven skills listed in a new session), and
  `npx skills add --list` lists exactly the eleven skills; `install/harnesses.yaml` records the versions.

## 0.1.0 (2026-09-30)

The first release. This entry sums up what 0.1.0 can do.

### Skills and plugins

- Eleven skills in three plugins, built from one source (`src/`): `lapis` (`lapis`, `lps-ux`,
  `lps-copy`, `lps-system`), `ultramarine` (`ultramarine`, `ulm-maintain`, `ulm-release`), and
  `lazuli` (`lazuli`, `lzl-fonts`, `lzl-color`, `lzl-research`), plus a separate critic agent.
- Plan-first design: `lapis` writes a plan file (`.lapis/plans/<task>.yaml`) with a brief, world
  materials, type and color roles, layout, key copy, flows, and keep-or-reject decisions on named
  defaults, and every later check reads it.
- Every skill works without hooks, agents, or MCP and says what to run by hand.
- Licensed `MIT AND CC-BY-4.0`: Markdown files under CC BY 4.0 and everything else under MIT, except
  the third-party material listed in `NOTICE`. `LICENSE` and `LICENSE-docs` ship in every plugin,
  skill, and Hermes folder, and in the wheel and sdist.

### Harnesses and installation

- Generated outputs for Claude Code, OpenAI Codex CLI, Oh-My-Pi, and other Agent Skills harnesses.
  Checked on 2026-09-27: installs on Claude Code 2.1.274, Codex 0.157.x, and Oh-My-Pi 18.3.1, and
  the `skills` CLI 1.7.0 listing for other harnesses. pi and Hermes Agent are marked `experimental`
  in `install/harnesses.yaml`: no real install has confirmed them, and the install scripts set them
  up only when named with `--harness`.
- Install scripts for macOS and Linux (`install.sh`) and Windows (`install.ps1`) and a generated
  `INSTALLATION.md`, all from `install/harnesses.yaml`. The scripts preview with `--dry-run`, ask
  before steps that change harness settings, and support `--update` and `--uninstall`.
- The CLI installs as the `lapis-design` package with the `lapis-design` and `lazuli` commands; the
  full contracts travel inside it as `lapis_design/shared`. It needs Python 3.12 or later. The
  guide installs the browser only from the installed tool (`uv tool run --offline`), never by
  looking the package name up on an index.

### `lapis-design`

- `plan check`: schema, defaults, contracts, fonts, references, and flow pairs, plus the check of a
  `lapis-plan` block inside a harness plan (`--from-markdown`) and a summary (`--summary`).
  Every plan reader refuses a plan over 1,000,000 bytes or 100 levels deep before parsing it, with
  one `schema.invalid` finding; unreadable schemas, corrupt fonts locks, and YAML errors are one line.
- `rights check`: compares an asset ledger and a fonts lock against license scope and expiry,
  credits, notices, reserved font names, third-party marks, generated media, and likeness or
  property consent. It compares records and states no legal conclusion.
- `render check`: captures your own page under up to nine conditions (320 to 1440 px, light and dark,
  reduced motion, a mobile browser frame) into a render extract, with measured fields and derived
  values defined in `render/DERIVED.md`.
- `behavior check` and `stub serve`: drive your own render against a stub backend or an isolated
  local backend with synthetic data, and record a behavior session that detects deceptive and
  pressuring patterns, focus and keyboard problems, missing states and recovery, and friction.
  Korean and English wording is read for dialogs, choices, flows, commit outcomes, and undo; commit
  outcomes read only text that appeared after the commit, and announcements count for the nearest
  live region.
- `slop lint`: 184 rules and 89 detectors across plan, source, render, behavior, and review layers;
  a detector that cannot judge reports why it skipped, so a missing input never reads as a pass.
  `copy.fabricated-proof` reads a quote-only line as a possible customer quote in any role.
- `release check`: the release gate, which reruns the plan checks, reads the lint, session, extract,
  and critic reports, rechecks catalog font licenses, and writes the gate report.
- `hook exit-plan` and `hook session-start` for harness hooks, and `mcp`, an MCP server with the
  `slop_lint` tool.

### `lazuli`

- `local fonts`: a read-only scan of system and user font folders, with PANOSE Latin measurements
  and a Korean, Japanese, and Chinese extension, kept in a database in your user cache. Adobe Fonts
  activations are never opened as files: on macOS lazuli lists them through the operating system's
  font API (Core Text) and measures glyphs the system draws, keeping only derived numbers, and drops
  a face once Core Text stops listing it. `LAZULI_FONT_ROOTS` turns that listing off.
- `catalog`, `search`, `lock`, `class`: catalog labels and licenses (Google Fonts, Fontsource,
  Fontshare, the Korea Copyright Commission's safe-font lists, a bundled system-font table, and
  Sandoll Cloud on request), ranked font candidates with evidence, a fonts lock that pins source,
  license, and delivery, and your own font classes that outrank catalogs.
- `color`: color system codes with reference links. HLC and RAL DESIGN SYSTEM plus values are
  computed as OKLCH approximations; Pantone, RAL CLASSIC, NCS, Munsell, and Freetone values come only
  from the ones you record.
- `sources`, `read`, `ref`: a registry of 80 sources with access policies, single pages as Markdown,
  and reference profiles that keep only what a source's rights allow.
  A capture's profile and screenshots are replaced together or not at all.
- `doctor` checks the install; `setup` is reserved for an optional style embedding model and exits 1
  until a model is published.
- Migrations run inside one transaction that refuses their own `BEGIN`, `COMMIT`, `ROLLBACK`, or
  savepoint statements, so a migration is applied whole or not at all.

### Network boundaries

- Render and behavior checks capture only hosts that are yours, and block every other host.
- Reference capture runs its browser without a proxy, cannot reach hosts the source registry marks
  as refused or link-only, disables peer-to-peer connections, and stops as blocked when a page ends
  on a document lazuli did not fetch. `read --render` gives its browser no network of its own, so
  only what lazuli fetches reaches the page, and it reads only global unicast addresses.
- Every URL lazuli handles is first turned into the address the browser would request: encoded
  hosts are decoded, dot segments resolved, and credentials and unusable hosts refused, so the
  source registry, `robots.txt`, and each redirect hop judge the host that is actually contacted.
  `read --render` reads the final page from an isolated world that page scripts cannot change.
- Requests lazuli sends follow redirects one checked hop at a time, and a hop to a refused or
  link-only host is never sent. They keep a human pace and stated crawl delays, name lazuli in their
  headers, stop at blocks and sign-in pages, and honor `robots.txt`. Sources whose terms forbid
  automated collection get no requests, only links.
- Changes to these boundaries come with tests that attack them from a page, and tests reach only
  loopback or recorded responses.

### Evaluation kit

- `tools/eval/` compares agent runs with and without the skills. Its results are exploratory and are
  not performance claims. Run records never go into the repository or a bundle; `share.py` exports a
  stripped copy. Network and full-access options are for an evaluation-only account.

### Known limits

- Contracts are `version: 0` drafts and may change.
- pi and Hermes Agent are experimental.
- No style embedding model is published, so `lazuli setup` cannot install one.
- Python 3.11 is not supported.
- Oh-My-Pi and Hermes Agent take skills from the repository's default branch, which is `release`;
  neither documents a way to pin another ref.
- Unicode host names outside common Latin, CJK, Hangul, and fullwidth ranges are refused, even
  where a browser would accept them.
- The behavior probes still read some wording in English only: form error reasons, sign-in
  alternatives, cleared-field explanations, and same-as-offered text in the forms probe, and API path
  stems for commit kinds. A Korean plan goal rarely matches a dialog by shared words, and the states
  probe can read a fixed present-tense note ("취소할 수 없어요") as a problem.
- The Japanese and Chinese guidance in the skill references has not yet been confirmed by proficient
  readers, and the Traditional Chinese example awaits a chosen region. The Korean guidance was
  confirmed by a native reader, except the example sentences corrected on 2026-09-30. Rendering
  claims were checked only in Chromium.
- On Windows and Linux, Adobe Fonts activations are absent from `lazuli local fonts`. On macOS their
  localized names follow the system's preferred language.
