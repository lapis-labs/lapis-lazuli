# Reading and looking up before asking

Research is a step with a result, not advice. The record's `Found` section holds what it produced, or why
it produced nothing. Whatever it finds is never asked.

## The request

Take it apart line by line before opening anything else.

| In the request | Goes to the record as |
|---|---|
| A named product, number, place, price, or person | `[declared]`, as written |
| A delivery rule ("plain files, no build step"), a limit ("no network requests", "no real company names"), a duty ("state once that the data is fictional") | `[declared]`, as written; a line that forbids network use, lookups, or downloads is kept word for word, since declining a lookup quotes it |
| A look word ("modern", "professional", "clean") | `[declared]` as a named style, in the user's words; unpack what it assumes about the content and ask only if that is open |
| What is absent: no audience, no offer, no name, no outcome | An open area for `questions.md` |

## The project

Read before asking, in this order, and stop at the first level that answers:

1. `PRODUCT.md` and `DESIGN.md`: the app folder first in a monorepo, then the repository root; in each,
   the root, then `.agents/context/`, then `docs/`. Record each file and, for `DESIGN.md`, its dialect.
2. `README`, `docs/`, changelogs, license and legal pages, pricing and policy pages: facts and limits the
   product can stand behind.
3. What exists on the surface: current pages, styles, copy, translations, assets and brand folders,
   package manifests (stack, locales), earlier `.lapis/` plans, records, and references.
4. The commit log for names and decisions; never private data about people.

Each fact found is recorded with its path. A file that contradicts another is reported as a conflict, not
merged.

## The subject's world

Look up what a page about this subject would otherwise get wrong or leave generic. Look for:

- **How the thing works**: the mechanism, in the field's own terms and numbers (what a backup keeps, how long,
  how a restore is chosen; how a kiln firing is scheduled; what a clearing house settles and when).
- **What people lose or risk**: the common failure, cost, or delay, from primary sources and incident
  write-ups, not from advertising.
- **Rules that limit the page**: advertising and pricing claims, privacy and consent, accessibility, sector
  regulation. A rule found here becomes a constraint; a claim it forbids goes to the list of what the page
  must not say.
- **The audience's own words**: the terms they use for the thing and its failure, from documentation, forums
  and standards bodies, as vocabulary, not as copy.
- **World materials**: concrete things of the subject (objects, records, processes, numbers, marks, places,
  tools) that `lapis` can build the page from.

Prefer, in this order: standards and official specifications; the product's or vendor's official
documentation; original authors, publishers, and archives; practitioners and public design systems.
Marketing pages and galleries are not evidence of how a thing works.

Label each item **confirmed** (you read the supporting text; give the URL and the date) or **lead** (a
snippet or a source named elsewhere). A lead is recorded as a lead and never as `[known]`. Never invent a
quotation, count, or percentage. Reposts of one source are one source.

Keep it bounded: a few reads, chosen by the open areas, and stop when they are covered.

### What stops a lookup

- The request forbids network use, lookups, or downloads, and nobody can be asked: follow it. Write
  `Not looked up: "<the request's line, as the user wrote it>"` under `Found`, and go on from what the project
  and your own knowledge give; the `references` step that follows is declined with the same line
  (`lzl-research`, the exploration guide, section 5).
- The harness has no search or fetch, or the call fails: write `Not looked up: <reason>` under `Found`, and go
  on. Do not retry in a loop.
- A source the `lazuli sources` registry marks `refused` or `browser-link` is never requested; give the
  link and the reason.
- Never sign in, submit a form, get past a block or CAPTCHA, or accept terms for the user.
- Pages the user named, such as their site or a competitor they pointed at, are read with `lazuli read`,
  and captured as references only through `lazuli ref capture` with the rights the user gives. Another
  site's design is not looked up here: the `references` step that follows the brief does that (`lzl-research`).
- What you know without a source is still useful: it becomes an `[assumed]` answer whose basis says it is
  general knowledge of the field, never a `[known]` fact.

## Ask or look up

| The open fact is | Do |
|---|---|
| A fact about the product, in a file | Read it |
| A fact about the field, public | Look it up; ask only what it leaves open |
| A decision or belief of the owner | Ask |
| A preference between looks | Do not ask; `lapis` compares candidates on the page's content |
| A fact only the owner has (price, name, customers, region) and nobody can answer | Assume a labeled placeholder with its basis |
