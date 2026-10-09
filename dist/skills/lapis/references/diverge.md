# Diverge: rough first views before the plan

Between the two turns of the direction conversation, a create run makes two to four rough first views that differ in what
matters, and the owner picks one before the plan exists. `lapis-design next` names `diverge` until the set is sealed.

## Sections

- Place and who — when the step runs and who makes each rough.
- What differs and what may not — representation, color allocation, reference direction; never decoration.
- The commands — `start`, `resample`, `variant`, `check`, `seal`, `show`.
- The rough and its card — what to make and what the card says.
- Distances and the contact sheet — facts for the owner, not a score.
- After the seal — turn two, the plan, and the slice.
- Unattended — nobody to pick.

## Place and who

`diverge` runs after the first turn of the direction conversation (`direction-conversation.md`) and before the
second, in a create run only. Three roughs by default (`--k 2` to `--k 4`); each draws on a different lettered direction of
the references record, so there are at least as many directions as roughs.

Make each rough in a fresh context where the harness has one (a subagent): it sees only the brief record, the direction
answers, its own draws, and the captures of its reference direction, never the other roughs. That keeps the roughs from
settling on one idea. A harness without subagents makes them in sequence, and the card says `made_in: main`. Aim for about
ten minutes a rough.

## What differs and what may not

The roughs differ in three ways: how the open core objects are represented, how color is allocated (which color owns how much
of the first view), and which reference direction each draws on. They may not differ only in decoration, order, or finish: a
pair with the same markup structure and almost the same color mass is refused. Keep items the owner kept (`K`) only where they
carry a job.

A rough is the first view at 1440 and at 390, with the real headline and the core objects on real or clearly synthetic content.
Keep the decisive medium (a diagram, a control, an image, a motion state) instead of a gray box: a flat rough hides exactly
what the owner is choosing between.

## The commands

`lapis-design diverge start --task <task> [--k 3]` writes the seed (the task's hash and OS entropy) and the draws before any card
exists. The draws are the CLI's: you cannot choose them. Each candidate gets a reference direction, for each open core object a
representation family (first from the options the owner left open at turn one, then from the object's kind in
`../shared/diverge/pools.yaml`), and one color allocation stance. Families and stances are drawn without replacement across
candidates; the pale default (`high-key-one-signal`) goes to at most one.

`lapis-design diverge resample --task <task> --candidate C2 --slot O1 --reason "<why this draw does not fit the subject>"`
replaces one draw, twice per candidate at most, and records why.

`lapis-design diverge variant --task <task> --words "<the owner's words>"` adds a rough the owner asked for at turn two or on a
direction-level reply to the slice (a reply that rejects the composition or the core object's representation is a direction
reply; one that changes a value, copy, or a component is a slice revision). It is drawn with `reason: owner`, and the pick is
asked again after the set is sealed again.

`lapis-design diverge check --task <task>` reads the cards against the draws and the renders; `lapis-design diverge seal --task
<task>` records the digests; `lapis-design diverge show --task <task>` prints the draws and distances.

## The rough and its card

Write each rough as `.lapis/diverge/<task>/C<n>/index.html` and its card `.lapis/diverge/<task>/C<n>/card.yaml`
(`../shared/diverge/card.schema.yaml`). The card names the direction it draws on, the draws it spends, the representation of each
open core object (the family drawn, the medium, the share of the first view it owns, and what the visitor sees and can do), the
color roles of the plan's shape with the area each owns (a `field` and an `identity` role need one), and the signature elements
the rough adds (what each carries, not how it looks). Render each rough narrow:

```text
lapis-design render check .lapis/diverge/<task>/C<n>/index.html --task <task>-C<n> --width 390 --width 1440
```

`check` refuses a card whose direction, draws, or object families disagree with the draws, an object the owner decided that the
card shows another way, a missing or stale render, and a pair that differs in order or finish only.

## Distances and the contact sheet

`check` writes `fingerprints.json`, `distances.json`, and `contact.png` under `.lapis/state/diverge/<task>/`. The distance of two
roughs is a weighted sum of how their first views are laid out (text, media, and control boxes on a grid, and the markup
structure), how the color mass is allocated (the field's lightness and chroma, the share of vivid and of dark pixels, the media
share, the line share), and how many core objects are represented differently. The weights (`diverge/pools.yaml`) were calibrated on the E1b roughs and the owner's verdicts there; structure leads. The
numbers are facts shown next to the contact sheet; they are never a quality score, and there is no novelty target.

## After the seal

Show the owner `contact.png` at turn two and ask for the pick and the picked rough's signature items. Then:

- The `explorations` entries of decision `direction` list C1 to Ck, and those of `layout` or `palette` when the roughs settle
  them. Each candidate has `artifact: .lapis/diverge/<task>/C<n>/index.html`, `compared_on: [render]`, and the 1440 captures in
  `comparisons`. `chosen` is the pick and `runner_up_lost` quotes the owner's words.
- The picked card's color roles move into `tokens.color.roles` unchanged, area included.
- The slice shows one page, built from the pick. Choosing among candidates happened here, not at the slice.
- An edit to a rough, its card, or its captures after the seal shows in `diverge check` and in the owner block.

## Unattended

The steps and records are the same. The pick is `- [assumed] Pick: C2 — Basis: <why>` under `## Direction 2`. The critic packet
carries the contact sheet, so the critic sees the alternatives that lost.
