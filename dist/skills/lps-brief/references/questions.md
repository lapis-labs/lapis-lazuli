# Choosing and asking the questions

A round is one message of at most six questions, ordered by how much the answer changes the page. The
list below is a starting order. Re-rank it for the task: a question the project or a lookup already
answered is gone, and one whose answer would only move a value (a color, a radius) is not asked.

## What each area changes

| # | Area | Ask when it is open | It changes |
|---|---|---|---|
| 1 | **The business**: what it sells, how it works, how it is paid for, what it does that the usual alternative does not | The request names a category and nothing else | The page's subject, its signature object, what the sections explain |
| 2 | **Audience and the moment**: who decides, who uses, what is happening when they arrive, on what device, under what pressure | The audience is a category ("teams", "customers") | The first screen, density, tone, section order |
| 3 | **What they lose**: the concrete worst case without the product, how fast it happens, what they use today | No incident, cost, or failure is named | The headline's claim, the opening object, which proof is shown |
| 4 | **The one action and its terms**: what the visitor does next, price and plan count, trial, what happens after | The call to action is generic | The pricing section (or none), the CTA's outcome, `flows` |
| 5 | **What can be claimed**: facts, figures, customers, certifications, regions, guarantees the product can stand behind, and what it must never say | The project holds no claims list | The proof section, any figure strip, the limits of the copy |
| 6 | **Beliefs and refused words**: what the owner thinks the field gets wrong, the sentence they would defend, phrases and looks they refuse (competitors' clichés, styles they were burned by) | Only a look word is given | `direction.concept`, the copy register, which defaults are rejected |
| 7 | **Constraints and fixed assets**: marks, colors, faces that must stay, `DESIGN.md`, stack and delivery format, locales, accessibility or legal duties, what the page may not load | No contract file; the request lists only some limits | What is fixed and what is open for exploration |
| 8 | **Success**: the one measure, when someone will look at it, what failure looks like | The request has no outcome | `brief.one_job`, what gets cut |
| 9 | **References the owner already has**: pages, screens, or ads they like or dislike, and what in each they mean | The request names none | `references` (the user's pages only, each with what to take and what to leave) |
| 10 | **What exists**: real photos, product screens, copy, logos, data, and who supplies them | The project holds no assets | The asset ledger, drawn versus real imagery, what is labeled synthetic |

Rank by consequence. An answer that changes what the page is about and asks of the visitor (1 to 4) outranks
one that changes what it may say (5 and 6), which outranks one that changes what is fixed (7), which outranks
one that changes how it is judged or sourced (8 to 10). Two questions that cannot be answered independently
are not asked in one round: ask the first and let the second wait for round two.

## Shape of a question

One decision, at most two clauses. Concrete enough to answer in a sentence. Never an adjective menu.

```text
2. Who opens this page, and what has just happened to them?
   Why: sets the first screen's subject and the order of everything under it.
   If you skip it, I assume: an IT lead at a 10-to-200-person company, a day after a deleted folder, on a laptop.
```

- **Why** names what the answer changes in the page, in the page's terms, never "to understand you better".
- **The default** is the most specific answer the research supports, never "something neutral". It goes into
  the plan if the question goes unanswered, so write one you could stand behind.
- A question that cannot have a sensible default says so ("no default; the page will say nothing about
  it"), and an unanswered one is recorded `[open]`.

## The message

```text
Before I plan, here is what I took from your request and the folder, with sources. Correct anything wrong.

Found
- <fact> (<path or URL>)
- <fact> (<path or URL>)
- Not found: <what you looked for and could not find>

Questions (answer by number; "skip" keeps my default)
1. <question>
   Why: <what it changes>
   If you skip it, I assume: <default>
...
```

The findings come first so the reader corrects them instead of repeating them; five lines at most.

## Rounds

- **Round one**: the top six open questions.
- **Round two**: only for what the replies opened (an answer such as "we have no brand yet" opens the
  branch of question 7), or for a skipped question whose default would be a guess about what the page is
  for. Not to confirm, not to ask for approval, not to restate round one.
- After round two the plan starts, whatever remains open.

## Redesign

The existing page answers areas 1, 5, 7, and 10 by itself: read it, `DESIGN.md`, and the capture first. Ask
what only the owner knows: what the page must keep, what it must fix and why now, and what visitors lose on
it today (area 3).
