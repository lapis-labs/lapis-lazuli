---
name: lps-copy
description: Writes and edits interface copy - headlines, calls to action, labels, errors, empty states, consent and pricing text - in the target language with one register per surface, built from the subject's facts instead of sales voice. Use for UI text and microcopy, Korean, Japanese, or Chinese copy, "this sounds generated", and copy passes before code.
license: MIT AND CC-BY-4.0
metadata:
  plugin: lapis
  version: 0.2.0
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

1. Read the plan's `brief`, `world_materials`, `flows`, and `content`, then `PRODUCT.md` for the
   facts and claims the product can support.
2. Collect the real content: product names, prices, terms, record names, error cases, the words
   users already use. Where it does not exist yet, write synthetic content that is clearly
   synthetic, with long and local names, and say so in `content.source`.
3. Never present invented metrics, customers, quotes, reviews, or logos as real.

## Set the voice - `content.voice`

- Choose one register per surface and locale. Record the main one in `content.voice.register` -
  `haeyo` or `hapnida` for Korean, `desu-masu` or `da-dearu` for Japanese, `zh-formal` or
  `zh-casual`, `en-formal` or `en-casual` - and any split by surface or locale in
  `content.voice.notes`. Legal, payment, and account text often takes the more formal register of
  the same product.
- Name each thing once: the product, the user's objects, the actions. Keep one term per concept
  across screens, and use the project's glossary when there is one.
- Say who speaks and to whom, in `content.voice.notes`: the product addressing the user, or the
  user labeling their own action.

## Write in the target language

Write directly in each locale in `brief.locales`. When copy starts in another language, translate
the meaning, then rewrite it as a native writer would: never ship a line-by-line translation.

- **Korean.** Let particles and endings carry the relations, keep the meaningful parts of a
  sentence, and keep one register per surface.
- **Japanese.** Keep です・ます and だ・である apart on one surface.
- **Chinese.** Keep one written register on one surface.
- **English.** Plain verbs, concrete nouns, sentence case unless the contract says otherwise.
- **Every language.** Read the sentence aloud as a native reader would. A sentence that only makes
  sense when turned back into the language it came from gets rewritten.

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
   and certainty as the source has them.
5. **Two candidates.** For the headline, subhead, and cta, write a second line that comes from a
   different material or fact and set both in the real layout. Record the pair and why the loser lost
   in `explorations` (decision `copy`, `covers` the slot); `plan.uncompared-decision` reads that it is there.

## Interface text

For the roles a string can have, error and empty-state wording by cause, confirmations, consent and price
copy, register notes for Korean, Japanese, and Chinese, messages with variables, and what an edit must
preserve, read `references/interface-copy.md`.

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

## Check

Run `lapis-design plan check .lapis/plans/<task>.yaml` after writing key copy; it tests the plan's
copy. Rendered copy is checked by `lapis-design slop lint` with a render extract, which the
`ultramarine` skill runs. You wrote the copy, so the critic, not you, judges whether it is earned.

## Reporting

Tell the user the register per surface, the key copy in each locale, each copy default kept or
rejected with its route, and any claim that needs a source the product has not given.
