# Asset rights checks — v0

How the `asset-ledger` detector (slop/detectors.yaml) reads the asset ledger
(`assets/ledger.schema.yaml`), the fonts lock (`fonts/lock.schema.yaml`), the shipped files, and our
own render extracts. Reference code: `cli/lapis_design/rights_check.py`. Each check below names the
rule it feeds (`rights.*` in slop/rules.yaml).

The checks compare records with each other and with the shipped files. They do not decide whether a
use is lawful: a hit means a record is missing, a recorded use goes beyond a recorded grant, or a
recorded condition is not met. When the record itself is wrong, the fix is to correct the record from
the governing document, not to edit the check.

## Inputs

| Input | Where | Notes |
|---|---|---|
| Asset ledger | `.lapis/assets.ledger.json` | Media other than fonts. Absent ledger = no entries. |
| Fonts lock | `.lapis/fonts.lock.json` | Fonts only; `files`, `notices`, `modified`, `reserved_names`, `shipped_names`, `license.source_class`, `license.research`. |
| Shipped files | the scan roots | Default roots `public`, `static`, `assets`, `src/assets`, `app`, `src/app`, `ios`, `android/app/src/main/res`, `android/app/src/main/assets`; the ledger's `scan` replaces them and adds excludes. Hidden directories, `node_modules`, `Pods`, and `build` are skipped. |
| Render extracts | render/extract.schema.yaml | Only extracts with `source.kind: render`. Reference captures are never checked. |
| Today | the run date | Used for expiry only. |

Globs are shell-style and repo-relative; `*` also crosses `/`.

## Coverage — `rights.no-provenance`

- **Source.** Every file under the scan roots with a media extension (images, video, audio, 3D and
  environment files) must match a ledger entry's `files` path glob or `sha256`. Every file with a font
  extension must match a fonts lock entry's `files` glob. Code-bundled assets are not files under the
  scan roots; record them with `library` (icon sets) and they are checked at render.
- **Render.** Remote media (a media box whose `host` is set, except, when the extract's source host
  is ours as render/DERIVED.md **Target hosts** defines it, a host that is the source host,
  `localhost`, a `.localhost` name, or a loopback or private IP literal) that is not placeholder media is
  covered item by item: its `phash` must be within 6 of 64 bits of a value in some entry's `phashes`
  (resized or re-encoded copies stay that close).
  Media left out this way is left to the Source rule over the scan roots; a file the development
  server serves from outside the scan roots is not checked.
  Two exceptions: every item from a `hosts` value of
  a `user-content` entry is covered, because the product's own terms govern what users upload (such
  an entry must use `license: user-terms`, list `hosts`, and cover no files or library); and a
  box without a perceptual hash (video without a poster, for example) falls back to any entry's
  `hosts`. An icon box whose `library` is set must have a ledger entry with the same `library`
  (case-insensitive). One hit per item or library per extract.

## License — `rights.license-unknown`, `rights.license-hint-only`

- `license: unknown` or `origin: unknown` → `license-unknown`.
- A license whose grant lives in a document of its own (`commissioned`, `permission`,
  `stock-standard`, `stock-extended`, `editorial`, `proprietary`, `provider-terms`, `user-terms`)
  without `rights.evidence` → `license-unknown`: the record must say where the document is kept.
- Otherwise `source_class` `catalog-summary` or `file-metadata` → `license-hint-only`: a catalog badge or
  embedded metadata is a lead to the governing document, not the grant.

## Use — `rights.use-outside-license`

Restrictions are the entry's `rights.restrictions` plus those its license id implies:

| License | Implied |
|---|---|
| `cc-by-sa` | share-alike |
| `cc-by-nc` | non-commercial |
| `cc-by-nd` | no-derivatives |
| `cc-by-nc-sa` | non-commercial, share-alike |
| `cc-by-nc-nd` | non-commercial, no-derivatives |
| `editorial` | editorial-only |

Conflicts, each one hit:

- `non-commercial` with `use.commercial`.
- `editorial-only` unless `use.editorial` is true and `use.promotional` is false. Reporting inside a
  commercial publication is editorial use; a shop page or an advertisement is not.
- `no-derivatives` with `modified` `edited` or `composited`, or with `modified` not recorded.
  Resizing, cropping, and format conversion are not counted.
- `platform-bound` with any `use.channels` platform value (`web`, `ios`, `android`, `desktop`,
  `email`, `embedded`) outside `rights.platforms`.

- `no-generator-input` on an asset listed in another entry's `generated.input_assets` → a hit on the
  input asset. An `input_assets` id that is not in the ledger → `rights.no-provenance`.

`share-alike`, `no-standalone-redistribution`, and `no-endorsement` are recorded for review; no check
reads them in v0.

## Expiry — `rights.license-expired`

`rights.expires` before today. It covers term-limited licenses, approvals, and relationships (a
partner mark allowed while an integration exists).

## Credit and notices — `rights.attribution-missing`, `rights.notice-missing`

Visible credit and traveling notices are separate obligations and are checked separately.

- **Credit.** A `cc-by*` license needs `attribution.required: true` with `text`, `placement`, and
  `license_url`; the placement must be one a viewer sees (`adjacent`, `credits-page`,
  `about-screen`, not `docs`); and when `modified` is `cropped`, `edited`, or `composited`, the credit
  must say so (`indicates_changes`). Any other entry with `attribution.required: true` needs `text`
  and `placement`.
- **Notices, ledger.** License `mit`, `isc`, `bsd`, `apache`, or `ofl`, on an entry that ships
  (`files` or `library`) → `notices` must be non-empty and each path must exist, unless
  `notices_embedded` records that the notices sit inside the shipped files and survive the build
  (a font's name records, a header comment kept in each file). `apache` always needs a file: it asks
  for a copy of the license text.
- **Notices, fonts.** A fonts lock entry with `files` and license kind `ofl` or `apache` → the same,
  and a notice file that exists must name the license it stands for (`open font license` or `apache
  license`, ignoring case and spacing); when files exist and none does, `notice-missing`. An empty
  file, a page that was not found, or a README is no license text.

## Reserved font names — `rights.reserved-font-name`

A fonts lock entry with license kind `ofl` and `modified` `subset`, `converted`, or `rebuilt`: a hit
when `reserved_names` is not recorded; otherwise, with declared names and no permission, a hit when
any `shipped_names` value contains a reserved name (case-insensitive) or when `shipped_names` is not
recorded. `woff-unchanged` (compressed only, data and metadata kept) is not a modification.

## Fonts at release — `rights.use-outside-license`, `rights.license-unknown`, `rights.license-unresearched`, `rights.license-hint-only`

plan_check judges fonts when the plan is written (`font.*` findings). The lock can change afterwards,
so a fonts lock entry with `files` is checked again as shipped: `source` `adobe-sync`, `sandoll`,
`system`, or `user-installed` → `use-outside-license`; with delivery `self-host` (the web grant) or
`app-bundle` (the app grant), a `not-allowed` grant → `use-outside-license` and an absent or `unknown`
one → `license-unknown`; `license.source_class` `catalog-summary` or `file-metadata` →
`license-hint-only`. Server, document, and editor grants are recorded for review.

License kind `unknown` is read with the research record (`license.research`, fonts/lock.schema.yaml):

| `license.research` | Meaning | Hit on shipped files | plan_check finding |
|---|---|---|---|
| absent | nobody looked | `license-unresearched` | `font.license-unresearched` |
| `outcome: unknown-after-research` (with `evidence` and a `note`) | looked, found nothing; a candidate only | `license-unknown`, naming the note | `font.license-unknown` |
| `outcome: verified` | a document was read and grants the planned uses; needs `source_class` `rights-holder` or `provider`, a known kind, and an evidence item that is a document, not a name record or a search | none by itself | none |
| `outcome: restricted` | the document grants use only within `restrictions` | none by itself: the grants decide; the release gate lists it for the user | `font.license-restricted` (a warning) |

A known license with no research record (an older lock, or a declaration the user made) is judged by its
kind, grants, and class as before. Evidence `license-file` on an entry with `files` needs its copy in
`notices`. The record is what the agent says it read; the checks compare it with the files and each
other, and `lazuli lock` checks a quote from a license file against the notice file.

## Marks — `rights.unverified-mark`

For entries whose `mark.relationship` is not `own`: `authorization: unknown` → hit; `customer`,
`partner`, or `press` with anything but `confirmed` → hit, because the page claims a relationship.
`integration` and `compatibility` references may be `not-needed` when the owner's guidance allows
plain reference.

## Generated media — `rights.generated-as-evidence`, `rights.generated-from-reference`, `rights.generated-unreviewed`

- `role: evidentiary` → hit: generated media must not stand in for proof that something real exists
  or happened.
- `generated.inputs` contains `reference-only` → hit.
- `generated.reviewed: false` → hit (quality).

## Releases — `rights.release-missing`

`kind` `photo` or `video` in commercial or promotional use: `releases.people` or `releases.property`
`needed`, `unknown`, or not recorded → hit. `none-depicted` and `obtained` pass; `synthetic` passes
for generated media only. `user-content` entries are not checked: the product's terms govern uploads.

## Mark symbols — `rights.unapproved-mark-symbol`

A render text run containing the registered sign (U+00AE) or the trademark sign (U+2122) → hit,
unless the text right before the sign is the `mark.name` of a ledger entry whose mark is `own` or
`confirmed` and whose `mark.symbols` lists that sign. One approved mark does not approve the sign
after another name.

## Not checked in v0

- Brand glyphs inside an icon library: record each brand glyph the product uses as its own `mark`
  entry; the library entry does not cover the marks.
- Content of credit text beyond the fields above, share-alike scope, standalone redistribution, and
  endorsement: recorded for review.
