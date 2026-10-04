---
name: lazuli
description: Runs the lazuli CLI that supplies facts for design work - local fonts, font catalogs, color system codes, pages and reference profiles, the fonts lock - and maps plan fields to the commands that look them up. Use for lazuli setup and health checks, where lazuli keeps state, its network rules, and turning a plan into lookups.
license: MIT AND CC-BY-4.0
---

# lazuli

`lazuli` gathers facts about local fonts, catalogs, color system codes, pages, and references, and
pins chosen fonts in a lock. It never decides a design: `lapis` decides and writes the plan;
`lazuli` and the `lzl-*` skills return candidates, evidence, and locks. Every command works without
a plan; when `.lapis/plans/<task>.yaml` exists, read it first.

## Health and setup

1. `lazuli doctor` prints ok, warn, or fail per check and exits 1 only on a failure: the local
   database engine is too old for lazuli's search index, or the user cache is not writable.
   Warnings do not fail: no inventory or an older database (run `lazuli local fonts`), no font
   folder, or no headless browser for `lapis-design` render and behavior checks. Installing that
   browser installs software; ask first.
2. When the session did not start with a font inventory summary, run
   `lazuli local fonts --summary` (a read-only scan, then the summary).
3. `lazuli setup` is for an optional font style embedding model. None is published, so it installs
   nothing and exits 1; everything else works without a model. `shared/models/SETUP.md` and
   `shared/models/manifest.schema.yaml` describe the checks for a future release; their options
   are not in this CLI yet, so pass only `--json`.

## Where state lives

- **User cache**, per user: the lazuli database (inventory and measurements, catalog rows and
  lookup answers, the user's font classes and color records, each source's last request time),
  pages `lazuli read` cached for a day, and screenshots from `lazuli ref`. By operating system it
  is `~/Library/Caches/lazuli`, `%LOCALAPPDATA%\lazuli\Cache`, or `$XDG_CACHE_HOME/lazuli`
  (`~/.cache/lazuli`). `LAZULI_DB` names another database. The same folder holds `sig.key`, the
  per-user key that signs reference text. The user's color records and classes, and that key,
  cannot be rebuilt by a rescan and resync (a new key makes earlier reference profiles
  incomparable); never delete them unasked.
- **Project** `.lapis/`: lazuli writes only `fonts.lock.json` (`lazuli lock`,
  `shared/fonts/lock.schema.yaml`) and `refs/<slug>.json` (`lazuli ref`, validated against
  `shared/render/extract.schema.yaml`; an invalid profile is never written).
- Never move `LAZULI_DB` into the project to work around sandbox or permission limits; if a
  project-local database is unavoidable, keep it outside version control and tell the user.
  It holds this machine's font inventory, including Adobe-derived rows, and is not a project asset.
- Nothing else from the user cache goes into a project, repository, ledger, or bundle. The lock
  holds facts about chosen fonts, never their files.
- `lapis-design plan check` and `slop lint` read measured features from the database
  (`--lazuli-db`, else `LAZULI_DB`, else the user cache). Without it, rules that need them are
  skipped, not passed.

## Every request follows these rules

One module reaches the network, and only when a command asks; `lazuli search` and `lazuli lock`
never do. The rules below hold for every request lazuli sends itself. What a captured reference
page embeds (images, stylesheets, fonts, frames) is checked against the registry only.

- **Registry first** (`lazuli sources`; `shared/sources/registry.yaml`, fields in
  `shared/sources/registry.schema.yaml`). `adapter`: a catalog adapter collects it on command
  (`lazuli catalog sync` or `lookup`). `read`: `lazuli read` may fetch one page the user asked
  for. `browser-link`: never requested; the user gets the link. `refused`: the terms forbid tools;
  nothing is sent. An unlisted host may be read. Every redirect hop is judged again, by the
  registry and by that host's robots.txt, before it is requested.
- **robots.txt first.** A disallowed path, or a robots.txt answered with 401, 403, 429, or a
  server error, blocks the request. A robots.txt that redirects is followed hop by hop, up to five.
- **Pace.** Requests to one source, and each redirect hop to its own host, wait for the larger of
  lazuli's interval and the site's stated crawl delay or request rate, across runs. Each names
  lazuli and carries no cookies or credentials.
- **Stop on a block.** 401, 403, 429, a CAPTCHA or bot-challenge page, or a sign-in page stops the
  request; a blocked catalog source is marked failed and a plain rerun skips it. Report the block
  with the link; never sign in or reach the page another way.
- `lazuli catalog lookup` lists the requests it will send and asks before more than 10; pass
  `--yes` only after the user agrees to that list.

## Exit codes

Exit 2 is a usage error or missing input everywhere. Exit 1 means:

- `doctor`: a check failed; warnings exit 0.
- `setup`: nothing was installed, which is every run today.
- `read`: refused, blocked, or failed. A URL carrying credentials is exit 2.
- `ref`: refused by the registry, robots.txt, a block or sign-in page, or rights the page cannot
  meet.
- `lock`: the existing lock is unreadable or invalid. An unchanged entry and `--dry-run` exit 0.
- `class remove`: no class to remove.
- `color lookup`: an incomplete code, such as one without its library suffix.
- `catalog sync` or `lookup`: a source failed or was blocked, the user declined the requests, or
  `--family` matched no installed family.
- `search` exits 0 even with no candidates.

## From the plan to commands

Paths use the plan path grammar; `shared/plan/schema.yaml` holds the lookup fields.

| Plan field | Command | Owner |
|---|---|---|
| `tokens.type.roles[*]` with `brief.platform` | `lazuli search --script <code> --role <role>`, plus `--delivery web` for `web`, `--delivery app` for `ios`, `android`, `desktop`, `embedded` | `lzl-fonts` |
| `brief.locales`, `tokens.type.roles[*].scripts` | `--script`: `kore` Korean, `jpan` Japanese, `hans` or `hant` Chinese, or the plan's own code | `lzl-fonts` |
| `tokens.type.roles[*].family` once chosen, `task.id` | `lazuli lock "<family>" --role <role> --task <task.id>` into `.lapis/fonts.lock.json`, the default `tokens.type.lock` | `lzl-fonts` |
| `tokens.color.roles[*].system_code` | `lazuli color lookup <system> <code>`; `lazuli color record` for a value the user has | `lzl-color` |
| `tokens.color.roles[*].oklch` near a standard | `lazuli search --type color "oklch(<L> <C> <H>)"`: nearest codes, never an identity | `lzl-color` |
| `references[*]` by `kind`, with `rights` | `lazuli ref capture <url>`, `profile <image-or-url>`, or `system <path-or-url>`, with `--rights <rights>`; in the `references` step also `--task <task>` for study copies | `lzl-research` |
| `sources[*].ref`, paths or URLs | `lazuli sources` or `lazuli search --type source <words>`, then `lazuli read <url>` | `lzl-research` |

Choosing a font or color, and writing any plan field, including `references[*].profile`, stays
with `lapis`.

## Without a plan

Take role, script, platform, and pages from the user's words and say what you assumed.
`lazuli lock` needs `--task`: use an id the user accepts, in the plan's form (lowercase letters,
digits, hyphens), so a later plan can claim the entry, and run `--dry-run` first.

## Reporting

Give each fact with its source: installed and measured, a catalog label (a hint), the user's own
record, or a page read. Name every refused or blocked request with its link, and say what was not
looked up and why.
