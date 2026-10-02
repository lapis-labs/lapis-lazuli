---
name: lzl-research
description: Finds where to look and reads what the user asks for - the source registry and its access policies, single pages as Markdown, reference profiles of pages, images, and design systems, reference notes, and claims labeled confirmed or lead. Use for references, "make it like this site", competitor, trend, and art research, and checking a source.
license: MIT AND CC-BY-4.0
metadata:
  plugin: lazuli
  version: 0.1.4
---

# lzl-research

lzl-research supplies sources, page text, reference profiles, and claims with their evidence. It
never decides the design: it hands `lapis` profiles and notes, which `lapis` records in the plan's
`references`. Without a plan, give the user the same notes.

## Limits that always hold

- Capture only pages, images, and files the user named; read only pages the user asked for. Search
  results and registry entries are leads: give them as links, and read the ones the user picks.
- Sources marked `refused` or `browser-link` are never requested; give the link and the reason.
- Never sign in, submit a form, or get around a block, CAPTCHA, or rate limit. Never buy access or
  accept terms for the user.
- A listing is not a license: each item's own terms decide reuse.

## The source registry

`lazuli sources` (`--type font|color|asset|search`) lists `shared/sources/registry.yaml`: what each
source is good for and how lazuli may reach it. `lazuli search --type source <words>` finds entries
by name, use, or site; `--kind` narrows by type and `--access` by policy.

- `adapter`: a lazuli catalog collects it at a human pace; `lazuli read` may also read a page.
- `read`: `lazuli read` and `lazuli ref` may fetch a page the user asked for, within robots.txt.
- `browser-link`: a link for the user only; the entry's `reason` says why.
- `refused`: the terms forbid automated access; nothing is requested, and the entry cites them.

A host the registry does not list may be read within robots.txt.

## Read a page

`lazuli read <url>` returns one page as Markdown. The registry decides first, then robots.txt, a
user agent naming lazuli, and a human pace per host, for the address you give and for every
redirect hop. A refusal, sign-in page, or block stops it with
the link to open (exit 1).

- Without `--render` nothing runs. `--render` runs the page's own scripts in a headless browser,
  GET only, without images, fonts, media, stylesheets, or frames, and checks every host a request
  reaches against the registry. Use it when the output says the page needs its scripts.
- It keeps the title, headings, paragraphs, lists, tables, quotes, code, and links, from the main or
  article element when there is one, and drops navigation, asides, footers, forms, dialogs, and
  hidden elements. Legacy Korean, Japanese, and Chinese encodings are decoded as browsers do.
- Pages are cached in the user cache for a day, never in a project; refusals and failures are not.

Paraphrase what you read; never paste page text into the interface.

## Capture a reference

Each command takes `--rights own|licensed|reference-only` and writes
`<project>/.lapis/refs/<slug>.json`, validated against `shared/render/extract.schema.yaml` (the
format of our own renders); `shared/render/DERIVED.md` defines each value.

- `lazuli ref capture <url>`: the page at 390, 768, and 1440 px, at the site's pace; it follows no
  links and types nothing. What the page embeds (images, stylesheets, fonts, frames) loads unless it
  comes from a `refused` or `browser-link` host; the profile's notes count what was left out.
- `lazuli ref profile <image>`: an OKLCH palette with area shares from a local image.
- `lazuli ref system <path-or-url>`: type scale, color roles, and state rules from design-token JSON
  or a `DESIGN.md` in a known dialect.

Take the rights from the user: `own` for their material, `licensed` when a license covers this use,
`reference-only` otherwise. A reference-only profile keeps no copy, alt text, accessible names, or
screenshots: text only as keyed signatures, images only as perceptual hashes. Screenshots and image
copies stay in the lazuli cache.

## Reference notes

- **Take** relations that survive new content: rhythm, ratios (type scale steps, column
  proportions), sequence (the order in which the page answers its reader), hierarchy, and density.
  The profile's type fingerprint, sections, and palette shares put numbers on them.
- **Leave** brand colors, illustrations, photography, copy, logos, the exact type pairing, and any
  signature composition or interaction.

Name the relations each reference offers; `lapis` chooses which to take, usually one or two per
reference, because a result close to one reference in layout, palette, type, and copy at once is a
clone. Hand `lapis` the note, rights, and profile path. Reference-only material lends relations
only; it is never reused wholesale or fed to a generator.

## Claims and their sources

Prefer, for what each can support:

1. standards and official specifications, for conformance;
2. official documentation, source code, and release notes, for product behavior;
3. original authors, publishers, museums, and archives, for concepts and history;
4. practitioners and public design systems, for context and worked examples;
5. galleries and other collections, for discovery only, never proof of usability.

Label each claim **confirmed** (you read the supporting text; give the URL and date) or **lead**
(a snippet, a summary, a source named elsewhere). Reposts of one work are one source. Never invent
quotations, page numbers, counts, or percentages.

## Competitive and comparative analysis

- Name the decision, then the set: direct competitors, alternatives, adjacent tasks, and platform
  references, each seen under the same task, user state, width, locale, and date.
- Record only what the read or captured page shows. What you did not see is "not observed", never
  "absent". Mark interpretation as yours.
- Group findings into conventions, constraint responses, differentiators, and gaps. Frequency is not
  correctness; name no winner.

## Trend research

- What is typical is what to avoid copying, not a target.
- Separate the durable principle, the dated signal, and the move: adopt, pilot, monitor, avoid, or
  preserve. A platform release, read from its owner, applies to that platform; a gallery cluster is
  a lead; a prevalence claim needs a sample you counted.
- One language's galleries are not the world: for Korean, Japanese, or Chinese products, study
  local products and institutions, or state the gap.

## Art research

- Trace a gallery item to its credited maker and a live source or museum or archive record; the
  claim ends where the chain does. Record maker, date, medium, and holder.
- A scan or photograph and the work it shows carry separate rights, and public-domain status varies
  by place and date. Link rather than rehost; profile an image only when the user supplies it.
- Sacred, ceremonial, or community-owned expression needs its community's permission; without it,
  suggest another direction grounded in the subject.
