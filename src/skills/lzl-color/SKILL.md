---
name: lzl-color
description: Checks color system codes and keeps the user's own values for them - normalizes a code, flags an incomplete one, gives its reference link, approximates coordinate codes, and lists nearest codes by distance. Use for codes from brand guides or paint and ink specs, "which code is this color", and physical or print color facts.
license: MIT AND CC-BY-4.0
---

# lzl-color

lzl-color supplies facts about color system codes: what a code is, where its reference lives, which
value the user holds for it, and where that value came from. It never chooses a color and never
writes plan decisions; `lapis` decides and records them in `tokens.color`. Without a plan, answer the
user directly. With one, read each role's `system_code` and `source_class` and the plan's
`output_condition` first.

## What never happens

- Never state a proprietary standard's value from memory, a web page's chip, or a third-party
  table. Values come from the user's records or owner data the user holds.
- Never build a conversion table between systems; a code has no exact counterpart in another.
- Never sign in to an owner's account, buy a guide, or accept terms for the user. When the numbers
  sit behind an account, give the link and ask the user.

## The systems

These ids are the command arguments and the values `system_code.system` takes; notes are in
`shared/vocab/color.yaml` (`systems`).

- **Code and link:** `pantone` (the owner's data or a measured chip; screen samples only for
  detection), `ral-classic`, `ncs`, and `munsell` (the owner's data or a measured sample), and
  `freetone` (an unofficial third-party table only; nothing to record).
- **Coordinate:** `hlc` (computed from the code, or a measured chip) and `ral-design-plus`
  (computed, the owner's data, or a measured chip).

A coordinate code is three numbers for hue, lightness, and chroma, so lazuli can compute where it
sits. A code-and-link code identifies a physical sample; its digits are not coordinates. `ncs`
percentages describe perceived blackness and chromaticness, not pigment shares, and neither `ncs` nor
`munsell` maps axis by axis onto OKLCH. The open `hlc` atlas files may not be shared modified.

`lazuli sources --type color` lists other places to look (`shared/sources/registry.yaml`); entries
marked `refused` or `browser-link` are links for the user, never requested.

## Check a code

`lazuli color lookup <system> <code>` does four things, then lists the user's records for it:

1. **Normalize.** Case, spacing, and trademark signs are cleaned; a code that breaks its system's
   structure is rejected (exit 2). `ral` picks the collection by digit count: four digits are
   `ral-classic`, seven are `ral-design-plus`.
2. **Completeness.** A `pantone` code without its suffix is incomplete (exit 1): the suffix names
   the library and stock (`C`, `U`, `CP`, `TCX`, ...). Copy it from the user's source; never infer
   it. An incomplete code gets no values and cannot be recorded.
3. **Link.** The system's registry entry with its access policy. `pantone` and `freetone` are
   `browser-link`: hand the link to the user.
4. **Computed approximation**, for `hlc` and `ral-design-plus` only, labeled `computed`: approximate,
   never a spec value. It reads the code as a lightness, chroma, and hue position under an assumed
   reference white and observer. The `ral-design-plus` owner publishes no reference conditions, so
   that reading follows secondary sources and the measuring geometry is unknown; say so when you pass
   the value on.

## Record the user's value

`lazuli color record <system> <code> --oklch L C H --source-class <class>`, or `--hex RRGGBB` in
place of `--oklch`.

- `provider`: published by the standard's owner and obtained by the user (an account, a printed
  guide). `measured`: from a physical sample; put the instrument, geometry, light, and sample (never
  account details) in `--note`. Both are `spec` unless `--use detection_only`. `screen-sample`: from
  a screen or photo, always `detection_only`.
- `--hex` is read as sRGB: use it only when the source says sRGB. A bare "RGB" label needs the user
  to confirm the space.
- The class must be one the system allows (`values_from` in the vocabulary); the command refuses
  any other.
- One value per class per code; recording again replaces it and says so.
- Records stay in the lazuli database in the user cache (`LAZULI_DB` sets its path), never in a
  project. Record only a value the user gave you and wants kept.

## Nearest codes

`lazuli search --type color <value>` takes `#RRGGBB`, `oklch(L C H)`, or another CSS color function
(a system code goes to lookup) and lists the nearest computed `hlc` and `ral-design-plus` codes and
the user's recorded values, three per group by default (`--limit`), each with ΔE_OK, the distance in
Oklab. Computed codes are grid points; check that the collection holds the code before naming it. A
nearest candidate is a lead to compare against the physical sample, never an identity or a spec
value.

## Value source classes

`value_source_classes` in the vocabulary labels every value, and only `authored`, `provider`,
`brand-approved`, `measured`, and `published` may become a spec value; `computed`, `converted`,
`nearest-match`, `screen-sample`, and `unofficial` serve detection and comparison. A brand-approved
value comes from the brand owner (`DESIGN.md`, a brand guide), not from lazuli; a converted value
carries the transform that made it. Report every value with its class.

## Two masters

A project can hold a physical specification (code, sample, finish) and an approved screen value:
two records, neither converted from the other, which may differ on purpose. Report both; overwrite
neither.

## Finish, substrate, and light

- A code names a sample on a stock or material: coated and uncoated libraries differ because the
  stock changes the ink, and a guide chip is not the product's surface. Metallic, fluorescent,
  pearlescent, and textured finishes cannot live in one flat value.
- Samples that match under one light can part under another. A measured value holds for its stated
  conditions; guides age, so note the guide's condition and date.

## Print output conditions

Process-color numbers mean something only inside an output condition the printer names with its
profile; lazuli has no profile lookup. Never guess a profile or convert by arithmetic; when none is
named, report the gap and the question for the printer.

For mismatches between tools, tags, displays, or physical samples, read `references/color-management.md`.

## Hand back

Per code, return one of these to `lapis` or the user; never fill a gap with a guess:

- the normalized code, its system id, and the reference link with its access policy;
- the user's recorded value with its class, use, and note;
- a computed approximation or nearest candidates with ΔE_OK, labeled as such;
- an unresolved gap (incomplete code, no value on record, a value behind an account, no named output
  condition) with the link and the question to ask.
