# Direction conversation

The owner decides direction item by item, before the plan, on things they can see. This is not plan approval and not a
vote on adjectives: every option is a job, a representation, or a carried meaning. `lapis-design next` names
`owner-direction` until each item has an owner answer.

## Sections

- When the turns happen — turn one after the references, turn two after `diverge`; more only while an answer opens something.
- The three questions — what a named style does, how each core object is represented, what a signature element carries.
- The proposal — `.lapis/direction/<task>.yaml`, written before you ask.
- Asking — one message per turn, in the owner's language, naming every open item.
- Recording answers — `## Direction <n>` in the brief record, one line per item.
- Unattended — nobody to ask: `[assumed]` with a basis, nothing waits.
- What it is not — limits, so a turn never becomes a progress check-in.

## When the turns happen

- **Turn one** comes after the references record passes. Ask about every open style, kit, object, and brief-named signature
  item in one message, with the reference sheet (`lapis-design references sheet --task <task>`) attached.
- **Turn two** comes after `diverge` is sealed (`diverge.md`). Show the contact sheet and ask for the pick and
  for the picked rough's signature items. It may also ask about color role and area for the pick; what you do not ask goes
  to the gap list the owner sees at the slice.
- **More turns** only while an answer opens something: a variant they want, a narrowing that needs another look, a pool
  they reject. `next` does not wait on a direction question when no item is open, so ask only about what is open.
- **The conversation ends** when every item has an owner answer, or when the owner accepts the defaults with
  `- Defaults accepted (direction <n>): "<their words>"`.

## The three questions

Write them in the owner's language. Each item is one line plus its options, and a default you would stand behind.

**1. A named style: what should it DO here?** For every style named in the owner's words (the request, the taste answer, a
`[declared]` row):

- `S<n>`: two or three **jobs** for the style on this subject, plus a default. A job says what the style does for the
  visitor ("borders show where one record ends and the next begins"). "Thick borders" is a look, not a job.
- `K<n>`: one item per element of the **trend kit** the style decodes to today, each with `seen_in` (the reference ids
  where you saw it), a default `keep` or `drop`, and a one-line reason. The owner keeps or drops each.

**2. Core objects: how is each represented?** `O<n>` covers one to four core objects, taken from the world materials and
the brief's one job. Each object has two or three representation options. Every option says what the visitor can do with it
and where it came from: a reference id, a world material, or `own`. Aim for a fresh representation that is also good UX: a
clock face to pick a time, a route drawn to show a delay, dropdowns inside the booking sentence. The default explores every
option across the roughs; the owner may narrow (`a,c`) or decide (`b`).

**3. Signature elements: what does each carry?** `G<n>` covers elements the brief already names; the roughs add their own at
turn two (`C<k>.G<n>`). Ask what information or job the element carries, not how it looks.

An example of turn one:

```text
lapis-questions: direction
Direction 1 — references: .lapis/references/<task>.sheet.png (directions A, B, C)

S1 neo-brutalism — what should it do here?
   a) expose the record: every brief, plan and finding is a bordered block with its raw text (default)
   b) collision: display words and the stone image overlap and break the grid on purpose
   c) bare HTML: system type, underlined links, only real output as imagery
   Today's kit, keep or drop each (seen in byooooob, dublab, gumroad):
   K1 full-bleed slabs with drawn line fields — keep: they can carry the three plugins
   K2 ticker band between slabs — drop: moves without carrying information

O1 what the skills change in an agent's work — a) one page fading into its other version under a fader
   b) the same component stepping through brief → plan → check  c) an annotated diff   (default: try all three)

G1 procedure animation — carries: a) which step is current and what it produced (default)  b) only the order
```

## The proposal

Write `.lapis/direction/<task>.yaml` against `../shared/direction/schema.yaml` before you ask. The CLI checks form only: ids are
unique and well formed, each style has two or three options and at least one kit item, every `seen_in` names a reference of
the references record, each object names a pool kind of `../shared/diverge/pools.yaml` and has two or three options (each with
`does` and `source`), and each default is an option id (`all` for an object). It never judges whether the options are good;
the owner and the critic do.

## Asking

- Write `.lapis/questions/<task>.md` with `lapis-questions: direction` on its first line, name every open item id in it, and
  stop with it as your last message. A harness with a question tool may ask through it; the file is the record either way.
- Paste the owner block `next` writes (`.lapis/owner/<task>.md`, last line `lapis-owner-block <sha8>`) unchanged into the
  file, as at an approval: a direction file without the current line comes back as `owner-direction`, with the paste step.
- The file waits only when at least one item is open and every open id is named. Otherwise `next` names the step it would
  name, so a turn cannot be a check-in.
- Do not write a line such as `Round 3 of 3.` in the message or the answers: the brief reads it as a third brief round.

## Recording answers

Put the owner's replies in the brief record `.lapis/answers/<task>.md`, under `## Direction 1`, `## Direction 2`, and so on,
one line per item, keeping what the file holds. The fact cap of the brief (six questions a round, two rounds) counts only
`## Answers` headings and does not apply here.

```text
- [declared] K2 ticker band: drop — "<owner words>"
- [declared] O1 the comparison: a,c — "<owner words>"           narrowed: diverge explores a and c
- [declared] S1 neo-brutalism: other — expose the record, but no borders on body text — "<owner words>"
- [declared] Pick: C2 — "<owner words>"                          turn two only
- [declared] C2.G1 crystal stone: a — "<owner words>"            turn two: the picked rough's signature item
- Defaults accepted (direction 2): "<owner words>"               untagged; every open item takes its default
```

The choice after the colon is an option id, a comma list of option ids, `keep`, `drop`, `default`, or `other`. A name may
itself hold colons (`S1 neo-brutalism: bold and dynamic: a`): the choice is the first word after a colon that ends the line
or goes on with `—`, `–`, a quote, or `- `. Each `[declared]`
item becomes a requirement row the critic judges (`K2 …: drop` is `met` when no ticker is shown); `Pick:` and the untagged
line are the owner's decisions and are listed in the owner block, not rows. The critic reads the options by their texts, not
by their letters. Record only what the owner said: never write a `[declared]` line for a reply they did not give.

## Unattended

With nobody to ask (`LAPIS_UNATTENDED=1`), nothing waits. Answer each open item yourself under `## Direction <n>`:
`- [assumed] K2 ticker band: drop — Basis: <why, from the brief and the references>`, and the pick as
`- [assumed] Pick: C2 — Basis: <why>`. An `[assumed]` line with no `Basis:` does not count. The owner block at `done` lists
every decision made without the owner.

## What it is not

- It is not plan approval: approval stays on the rendered slice.
- It is not an adjective or palette vote.
- It is not `lps-brief`'s work: the brief still decides nothing visual and asks facts only the owner has.
- It does not ask what the brief, the references, or an earlier answer already settled.
