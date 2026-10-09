# The brief record, and what it seeds

## Sections

Read the section for the part of the record being written, by heading; the rest are other parts.

- Shape: the headings and items of the brief record
- Rounds: one message of at most six questions and its answers
- Requirements and owner decisions: sealing the owner's own words, and the lines that drop or narrow a row or pick a slice
- Project taste: the user's reusable taste file, absent taste, and the plan's stance on refusals
- The plan seed: the plan file written from what the record settled
- The DESIGN.md seed: when a `DESIGN.md` may be proposed and what it holds

The record is `.lapis/answers/<task>.md`: the file the exit gate reads a relayed person's replies from, so a
person's answers and a run's own sit together. `lapis-design next` counts it as a brief record when it has a
`## Found` section and an `## Answers` section with text, and when every `[assumed]` item gives its `Basis:`. It
also counts the rounds (below) and returns the step `brief` when a round holds more than six items or a third
round appears. It judges nothing else.

## Shape

```markdown
# Brief: <task title>

Round 1 of 2. How it was answered: <a person in the session | relayed by an operator | nobody to ask>

## Found

- <fact> - <path, or URL and date> (confirmed)
- <fact> - <URL and date> (lead)
- Not looked up: <reason, when a lookup could not run>
- Not found: <what you looked for>
- Taste: .lapis/taste.md | not given

## Answers

- [declared] Q1 <question> - <the answer, in the user's words>. Basis: the request | the user, round 1.
- [known] Q2 <question> - <the answer>. Basis: <path or URL>.
- [assumed] Q3 <question> - <the answer you chose>. Basis: <why this one, and what you looked at>.
- [open] Q4 <question> - <no default fits>; the page says nothing about it.

## Plan seed

Seeded `.lapis/plans/<task>.yaml` with brief, context, claims, and world_materials. | A plan already exists; nothing seeded.

## DESIGN.md seed

<a seed for DESIGN.md as described below, or why none>
```

Each item starts with its tag.

| Tag | Means | Goes to the plan's |
|---|---|---|
| `[declared]` | The user said it: in the request or a reply | `claims.declared` |
| `[known]` | A source you read says it | `claims.known`, with the source |
| `[assumed]` | Your own choice, from the research or because nobody could answer | `claims.proposed` |
| `[open]` | Unresolved; no default fits | `claims.unresolved` |

`[assumed]` is the only tag for a choice you made. It never moves up: an assumed price is not a known price,
and the copy checks read `claims.known` and `claims.declared` as what backs a number or proof line on the page.
A `Basis:` says why that answer and not another: the lookup it came from, or "category norm; nobody to ask".

A relayed run's replies go in as `[declared]` items under their question, in a later round's own
`## Answers (round 2)` heading. When the plan exists and asks for approval, add those replies under their own
heading and keep what the file holds; overwriting the record sends the run back to `brief`.

## Rounds

A round is one message of at most six questions and the answers to it. In the record a round is the list items
under one answers heading:

| Round | Heading |
|---|---|
| 1 | `## Answers` |
| 2 | `## Answers (round 2)` |

`next` counts the items under each heading, tagged or not, and returns the step `brief` when one holds more than
six, or when a third round appears (`## Answers (round 3)`, or a line such as `Round 3 of 3.`). Items all under
`## Answers` are round 1, so put a second round's under its own heading. An answer is one item: the request's own
statements share one `[declared]` item per question they settle, not one item per fact, and what the project or a
lookup gave belongs in `Found`. A sub-list inside an item is not counted. `.lapis/questions/<task>.md` of kind `brief`
(its first line is `lapis-questions: brief`) holds the round being asked; its numbered questions are counted the same
way, and more than six returns `brief` instead of `waiting-for-user`. The cap reads only that kind: questions of the
other kinds are not the brief's.

## Requirements and owner decisions

`lapis-design requirements seal --task <task> --from <the owner's brief file>` copies the owner's words into
`.lapis/requirements/<task>.json`, and `lapis-design requirements show --task <task>` lists the rows. The record's
format is the `requirements-record` item in `../shared/index.yaml`. Only `lapis-design` writes it.

- **What it reads.** At most five `--from` files: project files outside `.lapis/`, UTF-8, 200 KB each, that the
  owner wrote as their brief. It also reads every top-level `[declared]` item of this record. Each list item (a
  parent without its children), table row, fenced code block, and run of prose lines is one row, and the heading above
  it is the row's section. More than 300 rows is refused: name the owner's brief, not product documentation, which
  belongs in the plan's `context.product` or `context.other`.
- **What it makes of an item.** A `[declared]` item is a requirement row, so tag as `[declared]` only what the owner said,
  in their words. What you read from a source is `[known]`; what you chose is `[assumed]`.
- **Ids.** A row's id comes from its text (`R3f2a1c`). The same text keeps its id when the files are read again; changed
  text is a new row, and the old one moves to `removed` and is shown to the owner.
- **A drop or a narrowing.** A row leaves the list or is narrowed only when the owner's reply says so and quotes its id.
  Record that reply, one line each, in the owner's words, under the heading of the replies to the approval ask, not
  under an answers heading:

  ```markdown
  - [declared] R3f2a1c: drop — <the owner's words>
  - [declared] R9b40de: narrow — <the owner's words>
  ```

  Never write such a line for a reply the owner did not give. The owner block shows every decision line back to the owner.
- **A slice pick.** When the owner picked one of several slice candidates, record it under the same reply heading as
  `- [declared] Slice: <the chosen page's URL exactly as the questions file links it> — <the owner's words>`. Feedback
  without a pick is an ordinary `[declared]` item with no `Slice:` line.
- **Approval is not a requirement.** Every other top-level `[declared]` item, under any heading, becomes a row that the
  critic must judge before `done`. Record an owner's plain approval ("looks right, go on") as an untagged item
  (`- Approved the slice: <the owner's words>`), and tag `[declared]` only a reply that says what the owner wants.

## Project taste

Read `.lapis/taste.md` before asking. It belongs to the project, not the task: reuse given items on the next
task without asking again. Only the person's words go here, from the request, a session reply, or an operator's
relay. A look word such as "modern" is not a preference to invent. Update the file when the user changes it.

```markdown
# Taste
Given by: <the user in the session | relayed by an operator | the request>, <YYYY-MM-DD>

## Likes
- <the user's words>
## Dislikes
- <the user's words>
## References
- <a name or URL the user gave>
## Avoid
- <the user's words>
## Feel
<one or two lines in the user's words; a list is also fine>
## Fixed
- <the user's words>
```

Leave ungiven sections empty. With nobody to ask, or when the user skips taste, do not create an empty or
invented taste file: write `Taste: not given` under the task brief's `Found` and the unanswered question as
`[open]`. A given file has at least one item; otherwise the task is `not-given` when that Found line exists,
and `unrecorded` when neither exists.

In the plan, set `direction.taste.source` to `.lapis/taste.md`, `follows` to the lines the direction follows,
and cite the file in `context.other`. Without given taste, use `source: own-reading`. When the direction
mentions a Dislikes or Avoid item, quote it exactly in `direction.taste.dislikes` with `stance: clear`
(the choice avoids it) or `against` (the choice conflicts), and a `why` of at least eight characters.
`against` is not permission: the critic and self-check report the conflict as a non-blocking finding for the
user to confirm. The lexical plan check is only a lead; it cannot read negation or synonyms.


## The plan seed

When `.lapis/plans/<task>.yaml` does not exist, write that file with only the fields the record settled, so the
plan starts from it; `lapis` fills the rest. The record's own `## Plan seed` section only says it was seeded:
the YAML lives in the plan file, not in the record.

```yaml
version: 0
mode: create
task: { id: <task>, title: <title> }
context:
  product: <PRODUCT.md, or null>
  design: <{ path, dialect } of the DESIGN.md that was read, or null>
  other: [.lapis/answers/<task>.md]
brief:
  subject: <what the product is, in a clause>
  one_job: <the single job this screen must do>
  audience: <the person and the moment, from the record>
  platform: [web]
  locales: [en]
  product_frame: <marketing-landing | saas-dashboard-admin | ... | other>
  constraints: [<each fixed limit from the record>]
claims:
  known: [<fact, with its source>]
  declared: [<what the user said>]
  proposed: [<assumed answer; basis>]
  unresolved: [<open item>]
world_materials: [<concrete things of the subject, four to six>]
defaults: []
```

- Leave `context.design` as the task found it: `null` when no `DESIGN.md` existed. A `DESIGN.md` this task
  writes is the next task's contract.
- `world_materials` are things, never adjectives. Take them from the lookups and the project; with none
  found, from the mechanism the research describes.
- A fact that only the record states stays traceable: end each claim with `(answers: Q<n>)`.
- Add `.lapis/taste.md` to `context.other` only when it holds user-given items; carry its provenance and refusals
  into `direction.taste` as described in "Project taste", not into assumed claims.

## The DESIGN.md seed

Propose one only when no `DESIGN.md` exists and the task makes a lasting product surface (a product, a site
that will be kept and extended), not a one-off page. Write the proposal into the record and say where it
would go. It holds what the brief settled and nothing visual:

- the subject and its one job, the audience, and the situation they arrive in;
- the voice: register, the words to avoid, the terms to use for the product's own objects;
- constraints and protected assets: marks, colors, faces, duties, delivery format;
- visual decisions as open: "decided in the plan's explorations; `lps-system` writes them to `DESIGN.md`
  after the plan".

Do not create `DESIGN.md` yourself and do not put token values in the seed: type, color, spacing, and motion
come from `lapis` explorations, and `lps-system` writes the file from the plan. If a `DESIGN.md` exists, the
record says so, names its dialect, and lists the values it fixes; none of them is a question.
