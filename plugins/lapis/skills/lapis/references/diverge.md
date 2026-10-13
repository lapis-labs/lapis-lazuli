# Diverge: rough first views before the plan

Between the two turns of the direction conversation, a create run makes two rough first views that differ in what
matters (two to four; the default is two), and the owner picks one before the plan exists. `lapis-design next` names
`diverge` until the set is sealed.

## Sections

- Place and who: when the step runs and who makes each rough.
- What differs and what may not: representation, color allocation, hierarchy, reference direction; never decoration.
- The shared brief and its contract: written once and checked once before the fan-out; what the first view carries and what comes later.
- The commands: `start`, `contract`, `resample`, `variant`, `check`, `seal`, `show`.
- The rough and its card: what to make, what the card says, and how much a rough may carry before the pick.
- Distances and the contact sheet: facts for the owner, not a score.
- After the seal: turn two, the plan, and the slice.
- Unattended: nobody to pick.

## Place and who

`diverge` runs after the first turn of the direction conversation (`direction-conversation.md`) and before the
second, in a create run only. Two roughs by default (`--k 2` to `--k 4`): start with two, and add a third or a variant with
`lapis-design diverge variant` when the owner asks for one, or `resample` a draw that does not fit; more candidates do not make
up for a shared error, since every one inherits it. Each rough draws on a different lettered direction of the references
record, so there are at least as many directions as roughs. The owner may take parts of two roughs (the flow of one and the
impact of another): the pick names the base rough and quotes their words, and the slice builds what they said.

Make each rough in a fresh context where the harness has one (a subagent): it sees only the brief record, the direction
answers, its own draws, and the captures of its reference direction, never the other roughs. That keeps the roughs from
settling on one idea. A harness without subagents makes them in sequence, and the card says `made_in: main`. Aim for about
ten minutes a rough.

## What differs and what may not

The roughs differ in how the open core objects are represented, how color is allocated (which color owns how much
of the first view), what the first view carries against the later scenes (the hierarchy), and which reference direction each
draws on. They may not differ only in decoration, order, or finish: a
pair with the same markup structure and almost the same color mass is refused. Keep items the owner kept (`K`) only where they
carry a job.

A rough is bounded: the core composition (the first view at 1440 and at 390, with the real headline and the core object it opens
with on real or clearly synthetic content), one representative motion state, and one phone state, as the one page `index.html`.
Keep the decisive medium (a diagram, a control, an image, a motion state) instead of a gray box: a flat
rough hides exactly what the owner is choosing between. Every other device width (320, 768), the dark theme, further states,
and polish wait for the pick; the slice brings the picked rough up to the full set of widths and states.
`diverge check` refuses a render at another device width, a full `render check` run of a rough (all widths and themes), and a
second page in its folder (`rough_bound` in `../shared/diverge/pools.yaml`). Render a rough once, and again only after it
changed: a second capture of an unchanged file shows the owner nothing new.

The first view is the opening of a page that unfolds in scenes, not a summary of every part. Its job is three things: who and
what (identity, the claim), one decisive object, and the primary action. A core object that is not the decisive one owns none
of it (`first_view_share: 0`) and plays its part later; the card says which part, in `later`, apart from its share of the
first view. "Show the core at once" in an owner's answer means the core impression, not every comparison, procedure, and
install step on one screen; read it that way unless the owner said they want the evidence in the first screen, and then name
that answer in the brief (`demanded_by`).

## The shared brief

Before any rough worker starts, write `.lapis/diverge/<task>/brief.yaml` once (`../shared/diverge/brief.schema.yaml`) and give
every worker that file unchanged. It holds the opening's job and what it carries, one row per core object (`first_view`:
`required`, `allowed`, or `later`, and the scene it plays later), the one headline and action every rough opens with
(`key_copy`), how the phone opening is composed on its own (`phone`), and `resolved`: each contradiction you found among the brief
record, the direction answers, and your own instructions, with the way the brief settles it. Read those three sources against
each other first (comparisons "lead the page" and a hero that holds three actions do not mean all of it in one screen). The
workers do not resolve contradictions; they would resolve them three different ways, or all the same wrong way.

Then run `lapis-design diverge contract --task <task>` once, before the fan-out. It is the one check of what every rough
inherits, and it refuses while any of these is missing or wrong:

- the hierarchy: the opening carries `identity` and `primary-action` (the hero), a process (`process-sequence`) object is not
  required in the first view without an owner answer in `demanded_by`, and the brief does not require every core object there;
- no meta text: `key_copy` has a `headline` and a `cta`, and the meta-text rule (`copy.meta-text`) opens no finding on them
  (a demo notice, producer-facing words, a page that describes itself);
- the phone as its own composition: `phone.composition` says what the 390 opening holds and what it moves after the content;
- the core objects' representation slots: one brief row per core object, and a draw for each open object of each rough.

When it passes, it writes `contract.json` and prints the `brief_sha256` each card names. `diverge check` and `seal` refuse a
set whose contract has not passed on the brief as it is now, and a card made from another brief. The owner block shows the
brief's digest, what the opening carries, and the phone composition, so the owner can see what the roughs were made from.

Two things a command cannot read, so you say them in the first direction message (turn one): how you read the owner's words
about the opening ("show the core at once" is the core impression, not every step on one screen, unless they say otherwise) and
that the phone is composed on its own. One line each, in the owner's language, so a wrong reading is corrected before the
roughs, not after them. Whether the copy is good for the subject stays your judgment and the critic's.

`diverge check` also refuses a missing or invalid brief, one that requires every core object in the first view with no owner
answer in `demanded_by`, and a card whose first view disagrees with it (an object it puts later that the card shows, one it
requires that the card leaves out) or carries more objects than its drawn hierarchy allows.

## The commands

`lapis-design diverge start --task <task> [--k 2]` writes the seed (the task's hash and OS entropy) and the draws before any card
exists. The draws are the CLI's: you cannot choose them. Each candidate gets a reference direction, for each open core object a
representation family (first from the options the owner left open at turn one, then from the object's kind in
`../shared/diverge/pools.yaml`), one color allocation stance, and one hierarchy stance (`one-decisive-object`, `object-led`,
`claim-led`, `relation-pair`: what the opening carries against the later scenes, and how many core objects it may carry). Families and stances are drawn without replacement across
candidates; the pale default (`high-key-one-signal`) goes to at most one.

`lapis-design diverge resample --task <task> --candidate C2 --slot O1 --reason "<why this draw does not fit the subject>"`
replaces one draw, twice per candidate at most, and records why.

`lapis-design diverge variant --task <task> --words "<the owner's words>"` adds a rough the owner asked for at turn two or on a
direction-level reply to the slice (a reply that rejects the composition or the core object's representation is a direction
reply; one that changes a value, copy, or a component is a slice revision). It is drawn with `reason: owner`, and the pick is
asked again after the set is sealed again.

`lapis-design diverge contract --task <task>` checks the shared brief once, after you wrote it and before any rough is made
(see The shared brief); `lapis-design diverge check --task <task>` reads the cards against the draws and the renders;
`lapis-design diverge seal --task <task>` records the digests; `lapis-design diverge show --task <task>` prints the draws and
distances. Each of these writes one line to `.lapis/telemetry/checks.jsonl`, local to the project.

## The rough and its card

Write each rough as `.lapis/diverge/<task>/C<n>/index.html` and its card `.lapis/diverge/<task>/C<n>/card.yaml`
(`../shared/diverge/card.schema.yaml`). The card names the shared brief it was made from (`brief_sha256`, the digest `diverge contract` printed), the direction it draws on, the draws it spends, the representation of each
open core object (the family drawn, the medium, the share of the first view it owns, which may be 0, what the visitor sees and can do, and its role in a later scene), the hierarchy drawn, the
color roles of the plan's shape with the area each owns (a `field` and an `identity` role need one), and the signature elements
the rough adds (what each carries, not how it looks). Render each rough narrow:

```text
lapis-design render check .lapis/diverge/<task>/C<n>/index.html --task <task>-C<n> --width 390 --width 1440
```

`check` refuses a card whose direction, draws, or object families disagree with the draws, one made from another brief, an object
the owner decided that the card shows another way, a missing or stale render, a rough beyond its bound (see What differs: a render
at another device width, a full capture run, a second page), and a pair that differs in order or finish only.

A card claims more than its captures show unless you make them match. The captures are what the owner and the critic see, so
each rough's capture has to show its own representation in the state that decides it (the annotated diff with a change
marked, the ledger with rows, the tray after a tag was moved), not an empty state shared with the other roughs; where that
state needs an action, take one more 1440 capture after it, the one representative state of the rough. Say in the owner's message, per rough, what its captures show and
what its card claims beyond them ("claimed, not shown"), so the pick is not made on a difference only the card names.

## Distances and the contact sheet

`check` writes `fingerprints.json`, `distances.json`, and `contact.png` under `.lapis/state/diverge/<task>/`. The distance of two
roughs is a weighted sum of how their first views are laid out (text, media, and control boxes on a grid, and the markup
structure), how the color mass is allocated (the field's lightness and chroma, the share of vivid and of dark pixels, the media
share, the line share), and how many core objects are represented differently. The weights (`diverge/pools.yaml`) were calibrated on the E1b roughs and the owner's verdicts there; structure leads. The
numbers are facts shown next to the contact sheet; they are never a quality score, and there is no novelty target.
The representation part of a distance compares the card's family names; it does not read the captures, so it is no evidence
that the captures show that difference.

## After the seal

Show the owner `contact.png` at turn two and ask for the pick and the picked rough's signature items. Then:

- The `explorations` entries of decision `direction` list C1 to Ck, and those of `layout` or `palette` when the roughs settle
  them. Each candidate has `artifact: .lapis/diverge/<task>/C<n>/index.html`, `compared_on: [render]`, and the 1440 captures in
  `comparisons`. `chosen` is the pick and `runner_up_lost` quotes the owner's words.
- The picked card's color roles move into `tokens.color.roles` unchanged, area included.
- The slice shows one page, built from the pick. Choosing among candidates happened here, not at the slice. The slice also brings
  the picked rough up to the full device coverage the release gate reads (320, 390, 768, and 1440, with their themes and
  states); the rough captured only 390 and 1440.
- An edit to a rough, its card, or its captures after the seal shows in `diverge check` and in the owner block, and so does a
  change to the shared brief.

## Unattended

The steps and records are the same. The pick is `- [assumed] Pick: C2 — Basis: <why>` under `## Direction 2`. The critic packet
carries the contact sheet, so the critic sees the alternatives that lost.
