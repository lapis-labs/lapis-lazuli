# LapisLazuli

Skills that make a coding agent write a plan for an interface before it writes code, and a CLI
that checks the plan, the rendered page, and the page's behavior against that plan.

For developers who build web interfaces with Claude Code, Codex, Oh-My-Pi, or another Agent Skills
harness and want each blocking finding tied to a named rule and a fix. [한국어](README.ko.md)

An [example plan for a campsite booking page](docs/examples/site-booking-en.yaml), checked before any
code exists, on a machine without a lazuli font database (four of seven findings left out):

```console
$ lapis-design plan check docs/examples/site-booking-en.yaml
plan_check 0.1.3: 2 blocking, 7 total
  [WARN] copy.buzzwords content.key_copy[*].text — "elevate" (buzzwords) in the headline key copy: "Elevate your camping experience"
          fix: Add a defaults entry for copy.buzzwords (keep or reject with a reason). Name the user action, the handoff removed, or the verifiable capability
  [BLOCK] copy.vague-cta content.key_copy[?slot=cta].text — "continue" (vague_cta) in the cta key copy: "Continue"
          fix: Add a defaults entry for copy.vague-cta (keep or reject with a reason). Name the outcome of the action in the label
  [BLOCK] font.no-lock tokens.type.lock — type roles are set but no fonts lock was given
          fix: Run `lazuli lock` after choosing fonts.
```

Once the page runs on localhost, `lapis-design render check` captures it in Chromium from 320 to
1440 px, and `lapis-design behavior check` records a scripted session against a stub backend.
`lapis-design slop lint` reads those result files, with rules such as `color.text-contrast`,
`type.ko.keep-all-missing`, `ux.preselected-option`, `ux.false-urgency`, and `rights.no-provenance`.

## Install

```sh
sh -c "$(curl -fsSL https://raw.githubusercontent.com/lapis-labs/lapis-lazuli/release/install/install.sh)" install.sh --dry-run
sh -c "$(curl -fsSL https://raw.githubusercontent.com/lapis-labs/lapis-lazuli/release/install/install.sh)" install.sh
lazuli doctor
```

The first line prints every command and changes nothing. Windows, single harnesses, and Chromium:
[INSTALLATION.md](INSTALLATION.md). Then start with `/lapis:lapis` (Claude Code), `$lapis:lapis`
(Codex), or `/skill:lapis` (Oh-My-Pi).

LapisLazuli reports what its checks found. It does not certify accessibility or legal conformance;
the full list is under [What it will not do](#what-it-will-not-do).

## Supported harnesses

| Harness | Status | Notes |
|---|---|---|
| [Claude Code](INSTALLATION.md#claude-code) | Verified (2.1.274, 2026-09-27; public install 2.1.277, 2026-09-30) | Plugins, session-start hook, plan-mode hook, MCP server, critic subagent. |
| [OpenAI Codex CLI](INSTALLATION.md#openai-codex-cli) | Verified (0.157.x, 2026-09-27; public install 0.159.0, 2026-09-30) | Plugins, session-start hook (you trust it in `/hooks`), MCP server, critic as an agent file the installer copies. |
| [Oh-My-Pi](INSTALLATION.md#oh-my-pi) | Verified (18.3.1, 2026-09-27; public install 18.4.4, 2026-09-30) | Plugins through its marketplace, session-start extension, MCP server, critic as a task agent. |
| [Other Agent Skills harnesses](INSTALLATION.md#other-agent-skills-harnesses) (Cursor, Gemini CLI, GitHub Copilot, opencode, Windsurf, Kiro CLI) | Listing verified through the `skills` CLI (1.7.0, 2026-09-30) | Skills only, plus an `AGENTS.md` snippet for the session summary and MCP setup. Each agent was not tested on its own. |
| [pi](INSTALLATION.md#pi) | Experimental | Skills and a session-start extension; not yet confirmed on a real install. |
| [Hermes Agent](INSTALLATION.md#hermes-agent) | Experimental | Skills, a Hermes plugin, and MCP; not yet confirmed on a real install. |

The status comes from `install/harnesses.yaml`; the exact commands for each harness are in
[INSTALLATION.md](INSTALLATION.md). The install script installs the CLI with `uv` or `pipx`, then
registers the plugins in each harness it finds (pi and Hermes Agent only when you name them with
`--harness`). Plugin commands run by hand install the plugins only; the hooks and the MCP server
need the CLI on your PATH (see [CLI and optional components](INSTALLATION.md#cli-and-optional-components)).

## How it works

1. Before any code, `lapis` turns a request into a plan file, `.lapis/plans/<task>.yaml`: brief,
   world materials, type and color roles, layout, key copy, and a keep-or-reject decision on every
   named default. `lapis-design plan check` validates it.
2. While the agent builds, it follows the plan; `lps-ux`, `lps-copy`, and `lps-system` cover flows,
   copy, and the design system.
3. After it builds, `ultramarine` runs `lapis-design` on your own render: capture under up to nine
   conditions (320 to 1440 px wide, light and dark, reduced motion, a mobile browser frame); drive
   flows against a stub backend; lint for generic-looking and deceptive patterns and for missing
   rights records; and hand what measurement cannot judge to a separate critic. `ulm-release` is the
   final gate.
4. At any step, `lazuli` supplies facts on request: fonts on your computer, catalog labels and
   licenses, color system codes, single pages, and reference profiles.

## Plugins and skills

`lapis` is the stone you start from: the plan, made from the subject's own materials. `ultramarine`
is the pigment ground from it: the finished work, which the checks look at. The name `lazuli` comes
from Lajward, the place the stone was mined, and it is where fonts, colors, licenses, and sources
come from. `lapis-design` runs the checks for `lapis` and `ultramarine`; `lazuli` runs lookups.

| Plugin | Skill | What it does |
|---|---|---|
| `lapis` | `lapis` | Plans new interfaces, redesigns, and visual direction before code, in a plan file the CLI checks. |
| | `lps-ux` | Designs flows, states, and navigation so they work and recover, then writes the stub that lets them be checked. |
| | `lps-copy` | Writes interface copy from the subject's facts, in the target language, with one register per surface. |
| | `lps-system` | Turns a plan's decisions into a design system: OKLCH color ramps, type scale, spacing, motion, themes, `DESIGN.md`. |
| `ultramarine` | `ultramarine` | Checks interfaces that exist: render capture, behavior probes, slop lint, and a separate critic. |
| | `ulm-maintain` | Maintains an existing frontend (refactors, upgrades, performance, design debt) in small checked steps from a captured baseline. |
| | `ulm-release` | Runs the release gate and writes the report that says whether the checks it ran allow shipping. |
| `lazuli` | `lazuli` | Runs the `lazuli` CLI and maps plan fields to its lookups. |
| | `lzl-fonts` | Gives font facts with evidence: inventory, catalog labels, ranked candidates, licenses, script coverage; writes the fonts lock. |
| | `lzl-color` | Checks color system codes and keeps your own values for them. |
| | `lzl-research` | Finds where to look and reads what you ask for: source registry, single pages, reference profiles, notes. |

Every skill works without hooks, agents, or MCP; where one would help, the skill says what to run by
hand.

## Command-line tools

- `lapis-design`: `plan check`, `rights check`, `render check`, `behavior check`, `stub serve`,
  `slop lint`, `release check`, and the `hook` and `mcp` entry points that harnesses call.
- `lazuli`: `local fonts`, `catalog`, `search`, `lock`, `class`, `sources`, `color`, `read`, `ref`,
  `doctor`, and `setup`. State lives in your user cache; `lazuli doctor` checks the install.

Run either with `--help` for the commands and options.

## Requirements

- Python 3.12 or later.
- `uv` or `pipx` to install the CLI.
- `git` to install the CLI and plugins from the repository.
- Chromium, through Playwright's `chromium-headless-shell`, for `render check`, `behavior check`,
  `lazuli read --render`, and `lazuli ref capture`. The rest works without it.
- SQLite 3.34 or later with FTS5 trigram support, for the `lazuli` database.
- Optional: the `cjk` extra (Korean, Japanese, and Chinese word analyzers, about 340 MB), installed
  from a checkout with `uv sync --extra cjk`.

## What it will not do

- **Scrape live sites.** `lazuli read` reads one page you ask for, within the source registry's
  policy and the site's `robots.txt`. Catalog lookups keep a human pace and any stated crawl delay,
  name lazuli in their request headers, and never get around a block or a sign-in. Where a site's
  terms forbid automated collection as lazuli reads the terms (not legal advice; the Adobe Fonts
  site and noonnu, terms read on 2026-09-26), the source registry refuses its hosts: lazuli sends nothing to
  them and gives you a link. This collection limit does not restrict recommending, choosing, or
  locking fonts, including licensed Adobe Fonts.
- **Open Adobe Fonts files.** Fonts an Adobe Fonts subscription activates are listed through the
  operating system's font API on macOS (Core Text) and measured from glyphs the system draws; only
  derived numbers are kept, and the files are never opened. Windows has no such listing, so Adobe
  Fonts are absent from the inventory there. When you run `lazuli catalog lookup`, the family name
  of an Adobe Fonts face that no catalog snapshot matched, and its Korean name where the system
  gives one, go to Sandoll Cloud as the search term, like those of any other installed family;
  nothing else about the face is sent.
- **Drive pages that are not yours.** Render and behavior checks capture only your own pages:
  `localhost`, loopback and private addresses, and `.test` names that resolve privately. Only
  `render check` takes a public address of yours, with `--public`, and never a source-registry host
  or a host your plan lists as a reference. Every other host is blocked. An HTML file path or
  `file://` URL also works: the checks serve its folder read-only on loopback and record only that
  HTTP URL.
- **Touch real accounts.** Behavior checks use a stub or an isolated local backend with synthetic
  data, never real accounts, credentials, or payment methods, and they never store typed values,
  query strings, headers, or request bodies.
- **Keep more of a reference than its rights allow.** Reference captures load only URLs you give,
  never sign in or submit forms, and keep only what the source's rights allow. A reference-only
  capture keeps no copy, alt text, accessible names, or screenshots, only keyed signatures and
  perceptual hashes.
- **Take your fonts, or act for you on font sites.** Font files are read, never copied or converted
  into a project; only files you supply for shipping enter one. lazuli never signs in, downloads,
  activates, buys, or accepts terms for you. The database of your fonts stays in your user cache.
- **Give legal advice.** Rights checks compare the records you keep and never state a legal
  conclusion. Ledgers and locks never hold credentials, license keys, payment data, or private
  receipts.
- **Certify conformance.** LapisLazuli reports what its checks found. It does not certify
  accessibility or legal conformance.
- **Approve for you.** The plan-mode hook only denies a plan that has blocking findings; approval
  stays with you.

## Status

Early releases: the contracts are `version: 0` drafts and may change between releases; see
[CHANGELOG.md](CHANGELOG.md) for the current version.
`lazuli setup` installs an optional font-style embedding model, and no model is published yet, so it
exits 1 for now. CI runs the contract tests, the Chromium tests, and the optional CJK tests on
Linux.

The repository includes the kit we use to study how agents work with the skills (`tools/eval/`).
Its results are case studies, not measurements of quality; see [`docs/eval/`](docs/eval/README.md).

## Working on the repository

Edit `src/`; `plugins/`, `dist/`, the catalogs, and the install scripts are generated by
`uv run python tools/build/build.py`, and CI fails when they drift. [AGENTS.md](AGENTS.md) has the
repository rules and the commands. [README.ko.md](README.ko.md) also holds the contract and tool
reference in Korean.

Most of the knowledge in `src/skills/` and `src/shared/` was migrated from the author's previous
repository, `design-and-frontend`, which is not part of this repository. Sources named `memo:` in
`src/shared/slop/rules.yaml` are the author's unpublished memos. The third-party material this
repository keeps is listed in [NOTICE](NOTICE).

## License

Markdown files are licensed under CC BY 4.0 and everything else under MIT, except third-party material listed in NOTICE.

The SPDX expression is `MIT AND CC-BY-4.0`. [LICENSE](LICENSE) holds the MIT text,
[LICENSE-docs](LICENSE-docs) the CC BY 4.0 legal code, and [NOTICE](NOTICE) says which third-party
material keeps its owner's terms. Every plugin folder, every skill folder, and the Hermes plugin
folder carries all three files, so a folder installed on its own still does.

To reuse a Markdown file, credit it, link the license, and say if you changed it. For example:

> `<file>` from LapisLazuli by lapis-labs, CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/),
> https://github.com/lapis-labs/lapis-lazuli
