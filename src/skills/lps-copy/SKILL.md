---
name: lps-copy
description: Writes and edits interface copy - headlines, decks, calls to action, labels, errors, empty states, consent and pricing text - in the target language, deciding each line's job and speaker before its register, built from the subject's facts instead of sales voice or the writer's own voice. Use for UI text and microcopy, Korean, Japanese, or Chinese copy, "this sounds generated", and copy passes before code.
license: MIT AND CC-BY-4.0
---

# lps-copy

Copy is part of the design. lps-copy writes the plan's `content` - voice and key copy - and then
the interface text, in the language the reader reads, from facts the product can stand behind.

## Order of authority

1. Requirements: honest prices, terms, and consent; errors that name the problem and a way
   forward; accessible names that match visible labels; nothing invented presented as real.
2. The project's contract: the voice and terms in `DESIGN.md` or `PRODUCT.md`. A change goes to
   `proposed_design_changes`.
3. Platform conventions for system actions and dialogs.
4. Named defaults (the cards). The copy cards are editorial signals, judged keep or reject.

## At the start

Read `references/interface-copy.md` → **One owner for every string** first, and **Korean** for Korean copy.
Then record this load with `lapis-design skill loaded --task <task> --skill lps-copy --context <current-context>
--read <skill-path/SKILL.md> --read '<skill-path/references/interface-copy.md>#One owner for every string'`;
add the Korean section as another `--read` when used. This attests the sections loaded, not copy quality.

1. Read the plan's `brief`, `world_materials`, `flows`, and `content`, then `PRODUCT.md` for the
   facts and claims the product can support.
2. Collect the real content: product names, prices, terms, record names, error cases, the words
   users already use. Where it does not exist yet, write synthetic content that is clearly
   synthetic, with long and local names, and say so in `content.source`.
3. Never present invented metrics, customers, quotes, reviews, or logos as real.
4. Take facts from a README or a document, never its narrator or its register: a README speaks to
   a developer, and the chat with the owner is not the product's voice.

## Set the voice - `content.voice`

Decide each line's job, then its speaker, then its form. The roles are headline, deck, body, label,
action, help, status, and legal; read them from the rendered outline when there is one, not from font
size alone.

- Record the policy per locale in `content.voice.locales.<language>`: `prose`, the sentence register of
  the roles that carry sentences (Korean `haeyo`, `hapnida`, `haera`; Japanese `desu-masu`, `da-dearu`; Chinese
  `zh-formal`, `zh-casual`; English `en-formal`, `en-casual`), a `speaker` (`brand`, `product`, `editorial`,
  `user`) where a page could mistake who speaks, and `by_role` for a role that differs.
- `compact` is a form, not a speech level: a noun phrase, an action phrase, or an ending left off. Headline,
  label, and action are compact unless `by_role` says otherwise; the other roles take `prose`. A deliberate
  difference between roles is not register mixing; keep one policy within a speaker, a role, and a locale.
  Legal, payment, and account text often keep the more formal register of the same product.
- `content.voice.notes` is for people: who speaks to whom and why. No check reads it.
- Name each thing once: the product, the user's objects, the actions. Keep one term per concept
  across screens, and use the project's glossary when there is one.
- Copy explains the product for its visitor, not this website's making; design rationale stays in the
  plan unless requested.

## Write in the target language

Keep one meaning contract across locales: names, figures, obligations, destinations, recovery, and
certainty are translated faithfully. Headlines and decks are written again around the same proposition and
genre; operational and legal copy moves little. Write directly in each locale in `brief.locales`; when
copy starts in another language, translate the meaning, then rewrite it as a native writer would:
never ship a line-by-line translation, and carry no line break, character count, or "you" frequency from one
locale into another.

- **Korean.** Let particles and endings carry the relations, keep the meaningful parts of a
  sentence, and choose the form by role: a headline may leave its ending off only when it still reads as
  intentional Korean.
- **Japanese.** Keep です・ます and だ・である apart in running text; titles are noun phrases and buttons action forms.
- **Chinese.** Keep one written register for running text.
- **English.** Plain verbs, concrete nouns, sentence case without a final period on headings unless the contract says otherwise.
- **Every language.** Read the sentence aloud as a native reader would. A sentence that only makes
  sense when turned back into the language it came from gets rewritten.
- **Reviewer.** The English and Japanese guidance here has not been read by a proficient reader. Report
  naturalness, register, and title craft in any locale as unconfirmed until one has read the rendered text.

## Writing pass

After a draft, read the page as if no conversation with the owner existed.

- **Who speaks.** Who is "I", "we", "my", "내"? Unless it is the brand, a labeled quotation, or the visitor
  in a control that says so, resolve it. A line that reports what you did to build the page belongs in the plan.
- **Job.** Does the line describe the product, instruct the visitor, or narrate a task list? Read the
  headings alone, then the buttons alone; if both sound like an assistant reporting, give each its own job.
- **Headline.** State its proposition, keep the subject, object, scope, and certainty, and move the
  explanation to the deck beside it. A word that only restates the sentence goes; a meaning never does.
- **Terms.** Keep a term the visitor needs (finding, critic, world material) and explain it at the right depth.

## Write key copy - `content.key_copy`

Draft the headline, subhead, calls to action, navigation, empty states, and main errors in the plan
before code, one entry per slot and locale.

1. **Statement first.** Write the literal claim; add a figure only when it carries the claim
   better. An image from the subject's own world (the firing log of a pottery shop) is welcome; a
   metaphor that fits any subject is not.
2. **Name-swap test.** Swap the product's name for another product's. A line that stays true says
   nothing; rewrite it around a fact, a number, or a world material.
3. **Say what happens.** A call to action names its outcome ("Book the 7:30 lane"), not the act of
   clicking. Two actions with different outcomes never share a label.
4. **Keep the strength.** Do not raise a claim's strength while editing; keep the facts, numbers,
   and certainty as the source has them. Keeping a source's certainty is not verifying it: what a
   document says about history, origin, naming, or third parties is a claim for the owner to confirm,
   not a fact. Put it in the questions you send as unconfirmed, with the document it came from.
5. **Two candidates.** For the headline, subhead, and cta, write a second line that comes from a
   different material or fact and set both in the real layout, at the narrow and the wide width. Record the pair
   and why the loser lost in `explorations` (decision `copy`, `covers` the slot); `plan.uncompared-decision` reads that it is there.
6. **Provisional.** Key copy is provisional until the owner has seen it rendered. Never call it final in
   a spec, an assignment to another agent, or a handoff before then; hand it over as a proposal. After the
   owner approves a rendered slice, an edit to key copy is listed to the owner as a change.

## Interface text

For the roles a string can have and each role's form, error and empty-state wording by cause, confirmations,
consent and price copy, headlines and breaks, register notes for Korean, Japanese, and Chinese, translating
against writing again, messages with variables, and what an edit must preserve, read `references/interface-copy.md`.

The reference opens with a `## Sections` index; read the section for the string being written, found by its heading, not the whole file.

- **What to show.** Decide the information before the words: what the reader decides next and what the genre always
  shows. A dashboard counts what a decision hangs on, and a flow asks for the next thing instead of announcing it.
- **Labels and buttons.** Short, parallel, and the same word as the destination or result. The
  visible label is the start of the accessible name.
- **Errors.** Name what happened and what to do next, near the field or action, without blame,
  jokes, or apology in place of a fix. Keep what the user typed.
- **Empty states.** Say why it is empty and give the first action.
- **Loading and success.** Say what is happening or what changed, not that something is "done"
  when the outcome is unknown.
- **Consent, pricing, and leaving.** State the full price, renewal, and cancellation plainly where
  the decision is made. A refusal is worded as neutrally as the acceptance, with the same weight;
  never shame the user for declining. These are requirements, and the `lps-ux` flows depend on them.
- **Numbers and dates.** Format them for each locale; never build a sentence by joining translated
  fragments around a number.

## Named defaults to walk

Walk the copy cards in `shared/slop/cards.yaml` - `sales-voice`, `rhetorical-shells`,
`mechanical-rhythm`, `formatting-by-rule`, `generic-content` - and the copy rules they name in
`shared/slop/rules.yaml`. For each card whose cue matches the draft, keep it with a basis and
reason in `defaults`, or take one of its routes. Replacing one stock phrase with its synonym is
still the default.

## Editing existing copy

- Keep the proposition: facts, numbers, stance, and strength of evidence stay.
- Replace figures with plain statements; keep a single figure when it is the point.
- Never add a figure, claim, or intensity the original did not have.
- Report terms that conflict across screens instead of silently choosing one.
- A source's statement about history, origin, naming, or third parties stays a claim for the owner to confirm.

## Check

Run `lapis-design plan check .lapis/plans/<task>.yaml` after writing key copy; it tests the plan's
copy. Rendered copy is checked by `lapis-design slop lint` with a render extract, which the
`ultramarine` skill runs: endings per role against the plan's voice, a headline that speaks in the body's
register, heading length and lines, an unanchored "my", and translated constructions, each a lead for review.
You wrote the copy, so the critic, not you, judges whether it is earned.

## Reporting

Tell the user the speaker and form per role and locale, the key copy in each locale, each copy default kept or
rejected with its route, any claim that needs a source the product has not given, and every statement
about history, origin, naming, or third parties with the document it came from, for the owner to confirm.
Say which English or Japanese wording no proficient reader has confirmed.
