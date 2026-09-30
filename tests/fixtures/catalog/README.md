# Catalog fixtures

Test data for the `lazuli` catalog adapters. A fake transport serves these files, so no test reaches
a network. The tests read them through `tests/test_catalog_open.py`, `tests/test_catalog_cjk.py`,
`tests/test_catalog_core.py`, and `tests/test_release_check.py`.

**What may be in here.** Nothing copies a third party's page or data set. Responses recorded from an
open catalog on 2026-09-26 were trimmed to a few families. Only facts stayed as recorded: family
names, ids and slugs, categories, subset and weight lists, axis ranges, and license identifiers.
Every value that a catalog curates or measures, such as tag scores, metrics, dates, popularity,
designer and foundry credits, publisher records, per-family tags, language lists, ids, and links, is
synthetic. Family names can be trademarks; they name the fonts and nothing more. Synthetic URLs use
the reserved `example.test` domain. The HTML pages and the `core/` files are hand-written samples
shaped like the pages they stand for, and say so in a comment.

| Fixture | Recorded from | Kept from the record | Synthetic | Original's license |
|---|---|---|---|---|
| `google-fonts/metadata-fonts.json` | `https://fonts.google.com/metadata/fonts` | Family names, category, stroke, subsets, weights, axes | Designers, sizes, dates, popularity, metrics | None stated for this undocumented endpoint, so no value is kept that it curated or measured. |
| `google-fonts/families.csv` | `tags/all/families.csv` in the `google/fonts` repository, through `api.github.com` | Family names, axis positions, tag names | Every score | The repository README says its top-level directories give the license of the files in them (checked 2026-09-30); `tags/` gives none, so the scores are synthetic. |
| `google-fonts/tree-ofl.json`, `tree-apache.json`, `tree-ufl.json` | `git/trees/main:<directory>` of the `google/fonts` repository | Family directory names; the shas are zeroed | Which family sits where: one family under two directories and one under an older name, on purpose | Directory names are facts. The README states the fonts' licenses per top-level directory: OFL-1.1 in `ofl/`, Apache-2.0 in `apache/`, UFL-1.0 in `ufl/`. |
| `fontshare/v2-fonts-offset-0.json`, `v2-fonts-offset-100.json` | `https://api.fontshare.com/v2/fonts` | Names, slugs, categories, license types, weights, axes | Ids, publisher, designers, tags, languages, insert dates, file URLs | No license for the API data found (the terms page needs JavaScript to show); the fonts themselves are under the ITF Free Font License, which is not a license for this data. |
| `fontsource/v1-fonts.json` | `https://api.fontsource.org/v1/fonts` | Ids, family names, subsets, weights, styles, categories, SPDX license ids | Modified dates | The Fontsource repository is MIT (Copyright (c) 2024 Ayuhito). The API page (checked 2026-09-30) says any HTTP client may read the API and states no separate data license, so only facts stay. |
| `sandoll/robots.txt`, `anshim/robots.txt` | Hand-written | The rules the two sites' `robots.txt` files describe | The wording and the other user agents | None: not a copy. |
| `sandoll/*.html`, `anshim/*.html` | Hand-written samples shaped like the pages, trimmed | Element structure the parsers read, with the short labels, font names, and license holders they extract | The rest of the page | None for the samples. The kept labels and names are facts about the page. |
| `core/*` | Hand-written | The shapes the core tests need (challenge, sign-in, CAPTCHA, robots) | All text | None: written for these tests. |

To add a fixture: record the response once at human pace, trim it, replace every curated or measured
value, add a row above with the source and the date, and check that no real designer, publisher,
score, or id is left.
