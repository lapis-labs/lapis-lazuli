# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/) once 1.0 is released. Before then, contracts are
`version: 0` drafts and may change between minor versions.

## Unreleased

- The Korean section of `lps-ux/references/forms-and-recovery.md` was confirmed by a native Korean
  reader on 2026-10-01 (listed under 0.1.2's known limits as awaiting one).
- `lzl-fonts/references/adobe-fonts.md` now opens by saying that activated Adobe Fonts are fonts like
  any other to recommend, choose, and lock (web delivery through the user's Adobe web project), and
  that its limits concern how lazuli and the agent reach Adobe's data: no file access, no extracted
  glyph data, nothing sent, no Adobe-derived values in training, evaluation, or tests. Its metadata
  lookup still never activates a font; the integration's search and recommendation tools may suggest
  families when the user asks, and a font is activated only on the user's request.
- `behavior check`: the time-limits probe moves one page forward through a flow run's steps, applying each
  recorded action once, instead of loading a fresh page and replaying every earlier action for every step
  (time quadratic in the run: 820 replayed actions per context for a 40-action run, so a full run on a small
  page with an abandoned flow did not finish in 30 minutes). A page it has idled or typed into is still
  reloaded for the next step, so the limits found and their numbers are unchanged.
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
  contact Adobe, and the source registry refuses fonts.adobe.com and the Typekit hosts it lists.
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
