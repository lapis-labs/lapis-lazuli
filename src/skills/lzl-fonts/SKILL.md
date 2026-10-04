---
name: lzl-fonts
description: Gives font facts with evidence - the local inventory, catalog labels, ranked candidates per role and script, license and delivery facts, Hangul, kana, and Han coverage and fallbacks - researches a font's license before judging it, fetches open-licensed families with their license text, and writes the fonts lock for a family already chosen. Use for "which fonts do I have", font candidates, font licenses and license research, downloading an open font, web font delivery, and lazuli lock.
license: MIT AND CC-BY-4.0
---

# lzl-fonts

lzl-fonts says where a font's files came from, what they may be used for, and how they reach the
target. It returns candidates and facts; `lapis` or the user chooses, and only `lapis` writes the
plan. It locks only a family already chosen.

- Open-licensed fonts (OFL and similar redistributable licenses) may be searched for online, downloaded
  from the family's official source, added to the project with their license text, and locked
  (Open fonts, below). A locally installed font may be used when its license is verified. A font whose
  license cannot be verified is not shipped; one whose license was not found at first is researched
  before it is judged (License research, below).
- Commercial fonts need the user's approval to license. Adobe Fonts stay as `references/adobe-fonts.md`
  says: used through the user's Adobe account and web project, their files never copied, opened, parsed,
  or sent anywhere.
- Never sign in, get around a paywall or a block, buy, or accept terms for the user; activate a font only
  when the user asks for that font. For a `refused` or `browser-link` source, hand the user the link.
  Every request keeps to the source registry, robots.txt, and a human pace; `lazuli fetch` does, and a
  download by hand does the same.
- The lock never holds credentials, keys, account or payment data. Report only the families the
  task needs.

## Inventory - `lazuli local fonts`

- A read-only scan into the lazuli database in the user cache; `--rescan` reopens unchanged files.
  `--summary` gives the overview, `--family <text>` matching families' faces, classes, and labels.
- `origin` is where a face came from: `system` (shipped with the operating system), `user`
  (provenance unknown; the lock says `user-installed`), or `adobe-sync` (an Adobe Fonts activation:
  read through the operating system's font API on macOS and measured from glyphs the system draws,
  never from its files; not listed on Windows). Installed means usable here for authoring and local
  tests; no origin is a license to ship, and a verified license is (License research, below).
- `--origin system|user|adobe-sync` keeps only the faces from that origin. `--json` gives every face
  its `postscript_name` and `subfamily`, plus the fields below, `null` or empty where the font does not
  say; a family entry holds the union of its listed faces' `languages` and `vertical`, so read the
  face before relying on them. For Adobe's own record of an `adobe-sync` face beyond these (designers,
  foundry, supported languages, weight and style names, variable or not), read
  `references/adobe-fonts.md`.
- Face fields: `version`, `manufacturer`, `designer`; `languages`, the tags whose whole character set
  the face maps, one rule for every origin (conservative repertoire hints, not shaping proof; `en`
  means plain A-Z); `axes` (`tag`, `min`, `default`, `max`; empty means not variable); `features`
  (OpenType tags) and `vertical` (`vert`, `vrt2`, `vhal`, `vkna`); `x_height`, `cap_height`,
  `units_per_em` in font units; and the font's own class as declared (`family_class`, `class_id`,
  `class_name`, `class_source`; 0 is unclassified and common), and `os2_ranges`, its declared Unicode
  and code-page bits, which are declarations, not support. `family_class` means something different per
  `class_source`: `os2` is the file's class and subclass word, `coretext` (an `adobe-sync` face) is the
  system's class bits without a subclass, so compare `class_id` across origins, never `family_class`.
  Declared classes and ranges never replace the measured classes, a user class, or coverage.
- For an `adobe-sync` face these come from the operating system, and some are partial: `features`
  (`features_source: coretext`) lists only the tags it maps, `vertical` can show `vert` and `vkna` but
  never `vhal`, `os2_ranges` is null, and heights are the system's own numbers. An absent tag is
  unknown, not missing from the font.
- `lazuli catalog lookup` sends the family name of an `adobe-sync` face that no snapshot catalog matched,
  and its Korean name where the system gives one, as the search term to the lookup catalog the source
  registry allows (`sandoll`), and nothing else about the face: no PostScript name, other-language name,
  coverage, or measurement.
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
- Sources whose terms forbid tools, as lazuli reads them (not legal advice), send nothing: `adobe-cjk` is
  disabled (that is about collecting the Adobe Fonts site's listing, not about recommending, choosing, or
  locking Adobe Fonts), and `lookup --source noonnu --unmatched` prints browser links. `yoon-design` is a
  browser link with no adapter. A class the user reads there goes in with
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

Fonts the user has activated are candidates like any other, Adobe Fonts included (origin `adobe-sync`,
listed by `lazuli local fonts --origin adobe-sync`): recommend, compare, choose, and lock them. On the
web an Adobe face is delivered through the user's own Adobe web project (`--delivery adobe-web-project`).

## Open fonts - find, fetch, bundle

An open-licensed family is bundled, not linked: its files and license text enter the project, and the
lock records where they came from.

1. **Find.** `lazuli search --license open` ranks candidates; its license label is a hint, never the
   license. The official source is where the family's own project publishes its release: for a Google
   Fonts family, its folder in the `google/fonts` repository; otherwise the foundry's or author's
   repository or release page. A mirror, a font-sharing site, and a "free download" aggregator are not.
2. **Fetch a Google Fonts family** with `lazuli fetch "<family>" --into <folder in the project>`. It
   reads the family's repository folder at one pinned commit through the catalog request layer (the
   registry, robots.txt, the 3 s pace), takes the top-level `.ttf` and `.otf` files and the license
   text, and writes nothing unless every file checks out: the repository's own hash, the first bytes of
   a font, the license text naming the license. A file that exists and differs is never overwritten.
   Static instances kept in a `static/` subfolder are not fetched, and a family under a license the lock
   has no kind for (the Ubuntu Font License) is refused. It prints the facts for `lazuli lock`.
3. **Fetching by hand**, for any other official release: read the release page with `lazuli read <url>`;
   download over HTTPS, one request at a time with seconds between them, with no sign-in and no cookies;
   on a 401, 403, 429, challenge, or sign-in page, stop and hand the user the link. Put only the font
   files and the license text in a project folder, keeping the license file's own name. Check that each
   file opens as a font (an HTML page saved as `.ttf` is the usual failure), that the license text names
   the license, and that its copyright line names the project the page belongs to.
4. **Read** the license text, with its reserved font names, and research anything the files do not
   settle (License research, below).
5. **Lock** the files: `--source`, `--source-url`, `--delivery self-host` (`app-bundle` for an app),
   `--files`, `--modified none` (`subset` or `converted` for a changed copy, with its reserved names),
   `--notice` the license text, `--license-kind`, `--use` as the text reads, `--research verified`, and
   `--evidence license-file <url of the text> --quote "<the words that grant the use>"`. Then
   `lapis-design rights check` and `plan check` read the lock against the files.

An installed font may ship the same way once its license is verified: copy the files and the license
text it came with into the project, and lock them under the real source (`--source open-source-other` or
the catalog's) with the evidence; the `user-installed` label itself never ships.

## License research

A license not found at first is not "no license". Research it before judging the font; the lock records
what was looked at, so the checks tell "never looked" (`rights.license-unresearched`,
`font.license-unresearched`) from "looked and found nothing" (`rights.license-unknown`,
`font.license-unknown`).

1. **The font's own records.** `lazuli license "<family>"` prints, read-only and without a request, the
   copyright, license text, license URL, trademark, manufacturer, designer, vendor and designer URLs of
   each installed file, the license-looking files beside it, the folder's likely installer, the catalog
   labels, and the research the lock already holds. These are hints (`font-metadata`): they say where to
   look, never what is granted. For an `adobe-sync` face lazuli reads no file; use only what
   `lazuli local fonts --family` reports, never open Adobe's files.
2. **The files' own license.** A license file in the folder or package the files came from
   (`license-file`); when the files ship, its copy is the notice.
3. **What installed or delivers it.** The operating system (its license agreement; a system font is not
   one to ship), Adobe Fonts through Creative Cloud (the subscription's terms: desktop, and the web
   through the user's own web project), a font manager such as FontBase, RightFont, Monotype Fonts, or
   Fontstand (its terms and the font's own license both apply), or a project or company folder (ask the
   user where it came from). `lazuli license` infers the manager from the path; confirm it with the user.
   Record the terms that grant the use as `installer-terms`.
4. **The rights holder and the distributor.** Search the web for the foundry's or author's license page
   (`"<family>" font license`, `"<family>" <maker> EULA`, the maker's repository) and the catalog or
   store that delivers it (`rights-holder-page`, `distributor-page`). Read only pages the source registry
   lets you read; for a `refused` or `browser-link` source, hand the user the link and record what they
   report.
5. **Decide and record**, with each place looked at as `--evidence <via> [url]` and its words as
   `--quote` (or yours as `--evidence-note`); the date is added:
   - `verified` (`--research verified`): a document grants the planned uses. The files may ship, with
     the license text as the notice.
   - `restricted` (`--research restricted --restriction "<each condition>"`): the document grants use
     only within conditions (one domain, desktop only, no embedding, internal use). Ship within them or
     with the user's approval; the plan check warns and the release gate lists it for the user.
   - `unknown-after-research` (`--license-kind unknown --research unknown-after-research` with a
     `web-search` item and `--research-note` saying what was searched and what was found): the font
     stays a candidate. Ask the user, who may hold a license, or choose another family; never ship it.
   Evidence is a document's address and words, never metadata an Adobe integration returned about a font.

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
  a grant for every planned use; pass `--license-class` when you read that document, or record the
  research (`--research verified` with a document as `--evidence` implies the class). The default
  `user-declared` is not confirmed, and the release gate lists it for the user to reconfirm.
  `lapis-design plan check` blocks shipped files whose use is unknown.
- A subset, converted, or rebuilt `ofl` font is modified: record its reserved font names and
  whether the user holds written permission to keep them (`--reserved-name-permission`). Only
  compression that leaves data and names untouched is `woff-unchanged`. Notices travel with shipped
  files; visible credit is separate.

## Delivery paths

- `self-host`: files from an upstream release or a purchase that grants web use; never
  `adobe-sync`, `sandoll`, or `system` files, and `user-installed` files only after their license is
  verified and the files are locked under their real source.
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
   record) with `--source-url` naming the page, folder, or release they came from, `--delivery`,
   `--files` with `--modified`, `--notice` (the license text that came with them), `--license-kind`,
   `--license-url`, `--use <use>=<grant>` as the license reads, `--license-class`, the research
   (`--research`, `--evidence <via> [url]` each with `--quote` or `--evidence-note`, `--restriction`,
   `--research-note`), `--reserved-name`, `--fallback`, and `--postscript` for an unknown family.
   A quote from a license file is checked against the `--notice` files, and an inconsistent research
   record (a search taken for a document, a `restricted` outcome without its restrictions) is refused.
3. One entry per family and role; locking it for another task adds that task to `used_by`.
4. Pass on every `note:` line. When the lock uses the database's name for the family, the plan's
   `tokens.type.roles[*].family` must match it.

## Reporting

Per family: evidence and its class, where the license research stands (never researched, verified,
restricted with its restrictions, or unknown after research, and the places looked at), the delivery path
per platform, uses still unknown, and links the user must open. Mark every hint.
