# Adobe Fonts metadata

This file backs the inventory part of `lzl-fonts` when an answer needs Adobe's own record of a font
lazuli marks `adobe-sync` (an Adobe Fonts activation): its designers, foundry, supported languages,
weight and style names, whether it is variable, and its Adobe Fonts page. lazuli's font listing and
measurement never contact Adobe, and the source registry refuses `fonts.adobe.com` and the Typekit hosts
it lists. lazuli never opens those fonts' files: it lists them through the operating system's font API
and measures the glyphs the system draws, and `lazuli sources` keeps Adobe Fonts `refused`. The
provider's record comes only from an official Adobe integration the user has already connected to
this host, or from the user's own browser.

## What to look up

- Read the face's entry first. Its `designer`, `manufacturer`, `languages`, and `axes` (not empty
  means variable) are lazuli's own values, read through the system font list; they are not Adobe's
  statement, and `languages` is a repertoire hint, not Adobe's language list. Ask the integration only
  for what an answer needs beyond them: Adobe's own designers, foundry, languages, weight and style
  names, variable status, or page links, or a value the entry leaves `null` or empty.
- Only faces lazuli marks `adobe-sync`, and only for the families the answer names. Never walk the
  library or every installed Adobe face to fill a table.
- Take the names from lazuli, never from memory:
  `lazuli local fonts --json --origin adobe-sync --family "<text>"`. Each entry gives the `family`,
  and each of its faces a `subfamily` and a `postscript_name`. The output holds names and lazuli's
  own values, read from the font list or measured; these faces have no file and no path.
  `--origin` also takes `system` and `user`, which this file does not look up.

## Routes

1. **An Adobe integration connected to this host.** Hosts call it a connector, an app, or an
   integration, and differ in how the agent reaches its tools: some list them, others show them
   only through tool discovery or search. Search for the integration's font tools before deciding
   there are none. Use only its read tools:
   - the font-details tool, keyed by PostScript name: one entry per face the answer needs, in one
     call when the tool takes a list, with the answer's locale when it takes one;
   - the font-styles tool, when the answer needs the styles of a family rather than one face.

   If the integration says an initialization tool must run before its others, run that first. The
   details give the family, style, and full name, designers, foundry, supported languages, weight,
   style, whether the font is variable, and links to its Adobe Fonts page and preview. They give no
   classification and no width. Call nothing that activates, syncs, or installs a font, and nothing
   that searches the library or recommends fonts: the lookup is for the faces lazuli listed.
2. **No such integration, or it is not connected.** Say that Adobe Fonts metadata is unavailable
   here and answer from lazuli's own results. Give the user `https://fonts.adobe.com/` to open in
   their browser and search for the family. Never fill a value from memory or a guess, never fetch
   that site or any other Adobe address yourself, and never sign in or connect the integration for
   the user.

A face the integration does not know, and a permission, sign-in, or rate-limit error, are
unavailable metadata for that face: say so, and do not retry in a loop or try another route.

## Using what comes back

- Label every value "Adobe Fonts metadata" in the answer, font by font, apart from lazuli's own
  values and catalog labels. Where they disagree, as for a weight or the languages, show both and do
  not reconcile them.
- The values are for display in the current answer. Never use them as a classifier label, an
  evaluation criterion, a test fixture, or training data, and never write them to a class
  (`lazuli class set`), the fonts lock, the plan, or any project file.
- Classification, similarity, coverage, and ranking stay lazuli's measurements (`lazuli search`,
  `--similar-to`). The metadata never changes a score, a class, or the order of candidates.
- Send the integration the PostScript name and the locale, nothing more: no font file, table,
  outline, or measurement. Those never leave the computer.
- No access token, authorization header, or account detail goes into the answer, a log, a note, or a
  file.
- lazuli stores none of what the integration returns, and it drops the Adobe faces it no longer
  lists. Notes you keep yourself stay on this computer and are deleted once `--origin adobe-sync`
  no longer lists the font or the subscription ends.
- None of these values is a license fact. License and delivery stay as `SKILL.md` says: a synced
  desktop font never ships as web files.
