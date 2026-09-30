# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/) once 1.0 is released. Before then, contracts are
`version: 0` drafts and may change between minor versions.

## Unreleased

- `lazuli local fonts` stores and shows, for every face, supported languages (by character
  repertoire, the same rule on every platform), variation axes, OpenType feature tags and vertical
  writing support, version, x-height, cap height, units per em, and the OS/2 family class. Adobe
  Fonts faces get these through Core Text only. Existing databases fill them on the next scan.
- `lazuli local fonts --origin system|user|adobe-sync` lists only the faces from one origin.
- On macOS, Adobe Fonts faces also store Korean, Japanese, and Simplified and Traditional Chinese
  family names where the font has them, read by short helper processes that ask Core Text in each
  language; before, only the system language was stored.
- The `lzl-fonts` reference `adobe-fonts.md` tells agents how to add Adobe Fonts metadata through the
  host's official Adobe integration, for display only; lazuli itself sends nothing.
- Adobe Fonts faces with an optical size (`opsz`) axis are no longer measured through Core Text, which
  sets that axis from the point size; they stay unmeasured ("optical size not pinned"), and
  `lazuli local fonts` says so in one line with their count. Files are unaffected.
- `NOTICE` ships next to the license texts: every plugin, skill, and Hermes folder carries it, and the
  wheel and sdist list it as a `License-File`, so a folder-only install keeps the third-party terms.
- `lazuli doctor` and `lazuli read --render` print the browser install command as
  `"<python>" -m playwright install chromium-headless-shell` for the Python that is running, which
  fits a uv tool, pip, and a checkout; before, they named `playwright` and `uv run playwright`.

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
