---
name: lzl-fonts
description: Gives font facts with evidence - the local inventory, catalog labels, ranked candidates per role and script, license and delivery facts, Hangul, kana, and Han coverage and fallbacks - and writes the fonts lock for a family already chosen. Use for "which fonts do I have", font candidates, font licenses, web font delivery, and lazuli lock.
license: MIT AND CC-BY-4.0
metadata:
  plugin: lazuli
  version: 0.1.0
---

# lzl-fonts

lzl-fonts says where a font's files came from, what they may be used for, and how they reach the
target. It returns candidates and facts; `lapis` or the user chooses, and only `lapis` writes the
plan. It locks only a family already chosen.

- Font files are read, never copied or converted into a project; only files the user supplies for
  shipping enter it. Never sign in, get around a block, download, activate, buy, or accept terms
  for the user; for a `refused` or `browser-link` source, hand the user the link.
- The lock never holds credentials, keys, account or payment data. Report only the families the
  task needs.

## Inventory - `lazuli local fonts`

- A read-only scan into the lazuli database in the user cache; `--rescan` reopens unchanged files.
  `--summary` gives the overview, `--family <text>` matching families' faces, classes, and labels.
- `origin` is where a face came from: `system` (shipped with the operating system), `user`
  (provenance unknown; the lock says `user-installed`), or `adobe-sync` (an Adobe Fonts activation:
  read through the operating system's font API on macOS and measured from glyphs the system draws,
  never from its files; not listed on Windows). Installed means usable here for authoring and local
  tests; no origin is a license to ship.
- Groups count coverage, not language: Hangul is the 2,350 common syllables or more, Han 6,000
  ideographs or more. Korean and Chinese sets carry kana, so kana alone does not make a face
  Japanese.
- Measurement reads outlines (weight, contrast, proportions, serifs, the Hangul or Han stroke-head
  class), never the font's own classification bytes.

## Catalogs - `lazuli catalog`

- `sync` refreshes expired snapshots (`google-fonts`, `fontsource`, `fontshare`, `anshim`) and the
  bundled `system-table` (`shared/fonts/system-fonts.yaml`, no network); `--force` ignores
  freshness. A failed source is skipped until named with `--source`.
- `lookup` asks the on-request `sandoll`, at its stated crawl delay, about installed families no
  snapshot matched (`--family` or `--unmatched`). `status` shows freshness and state.
- Sources whose terms forbid tools send nothing: `adobe-cjk` is disabled, and
  `lookup --source noonnu --unmatched` prints browser links. `yoon-design` is a browser link with no
  adapter. A class the user reads there goes in with
  `lazuli class set "<family>" --genre <id> [--subclass <id>] [--url <link>]`; it outranks catalogs
  for genre and subclass only and never leaves the user cache. Ids are in `shared/vocab/type.yaml`,
  source policies in `shared/sources/registry.yaml`.

## Candidates - `lazuli search`

`lazuli search --script <code> --role <role>` ranks installed and catalog families from the
database; narrow with `--category`, `--license open`, `--delivery web|app`, or `--installed`. Each
candidate's `why` says whether its script came from installed coverage or catalog subsets; how the
role fit (`code` keeps monospaced families, reading roles drop display-only and hand-only ones,
known weights adjust the rank, "class not known" means nothing decided); the catalog license,
marked a hint that narrows the search but is never a license fact; and `web` or `app` paths
inferred from listings, labels, and origins. `--similar-to "<family>"` ranks installed families by
measured distance, naming close and far features. The score only orders; return several candidates
with their evidence.

## License facts

- Facts belong to the exact files and channel, never to a family name: one family can ship under
  several channels with different terms.
- Declared classes: `rights-holder` (the license shipped with the files, or the foundry's text),
  `provider` (the delivering service's terms), `user-declared` (the default). `catalog-summary` and
  `file-metadata` (the files' own license records) are hints, never promoted.
- Grants are per use (`web`, `app`, `server`, `document`, `editor`): `allowed`,
  `allowed-with-conditions`, `not-allowed`, or `unknown`, the value of any unrecorded use. Artwork
  rights say nothing about any other use.
- Confirmed means `rights-holder` or `provider`, read from the document `--license-url` names, with
  a grant for every planned use; pass `--license-class` when you read that document. The default
  `user-declared` is not confirmed, and the release gate lists it for the user to reconfirm.
  `lapis-design plan check` blocks shipped files whose use is unknown.
- A subset, converted, or rebuilt `ofl` font is modified: record its reserved font names and
  whether the user holds written permission to keep them (`--reserved-name-permission`). Only
  compression that leaves data and names untouched is `woff-unchanged`. Notices travel with shipped
  files; visible credit is separate.

## Delivery paths

- `self-host`: files from an upstream release or a purchase that grants web use; never
  `adobe-sync`, `sandoll`, `system`, or `user-installed` files.
- `adobe-web-project`: the provider's hosted project, the only web path for `adobe-sync`. A synced
  desktop font never ships as web files.
- `google-fonts-api`: provider-hosted; the project's privacy and security rules must allow it.
- `app-bundle`: an `app` grant, with the `self-host` channel limits.
- `system-only`: never shipped and present only where the device has it, so it needs a
  `--fallback` stack. On the web it goes inside another face's `--fallback`.
- `not-deliverable`: authoring and local tests only.

## Fallbacks and scripts

- `shared/fonts/system-fonts.yaml` lists system faces by platform, script, and Chinese locale.
  Confirm `unverified` entries with `lazuli local fonts` on the target system, never add a CJK name
  from memory, and fall back to `system-ui` when unsure.
- Han characters are shared: the first face in a stack that has one decides its regional form, so
  each locale needs its own stack.
- Modern Hangul has 11,172 syllables; where people type names, the face or its fallback needs them.
- A subset cut to today's copy breaks on names and translations; split by `unicode-range` instead,
  and lock any subset as `--modified subset`.
- Line breaking and stack order are `lapis`'s decisions.

## Writing the lock - `lazuli lock`

`lazuli lock "<family>" --role <role> --task <task.id>` pins one family and role in
`.lapis/fonts.lock.json` (`shared/fonts/lock.schema.yaml`).

1. Run `--dry-run` first and show the difference.
2. Flags win; other facts come from the existing entry and the database: `--source` only when the
   user knows where the shipped files come from (otherwise `user-installed` stays, the honest
   record), `--delivery`, `--files` with `--modified`, `--notice`, `--license-kind`,
   `--license-url`, `--use <use>=<grant>` as the license reads, `--license-class`,
   `--reserved-name`, `--fallback`, and `--postscript` for an unknown family.
3. One entry per family and role; locking it for another task adds that task to `used_by`.
4. Pass on every `note:` line. When the lock uses the database's name for the family, the plan's
   `tokens.type.roles[*].family` must match it.

## Reporting

Per family: evidence and its class, the delivery path per platform, uses still unknown, and links
the user must open. Mark every hint.
