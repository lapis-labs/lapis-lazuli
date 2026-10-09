# Ask on doubt

## Sections

- Triggers: the six reasons to ask, who notices each, and what a CLI-raised ask is.
- Shape: the questions file of kind `ask`, the example, and what makes it not wait.
- Pausing: how the question reaches the owner in a harness with a question tool and in one without.
- Answers: where the reply goes, and the line that records a default taken.
- Unattended: nobody to ask, so the run answers and records why.
- Not nagging: one ask per checkpoint, batching, nothing already settled, no reports.

## Triggers

An ask is one short question when the work hits a conflict or a doubt. Ask for one of these six reasons, and name it on
the `Trigger:` line.

| Trigger | Ask when | Noticed by |
|---|---|---|
| `requirement-unmeetable` | a row cannot be met as written: a fact, a license, a tool limit | you |
| `requirement-conflict` | two rows cannot both hold | you; the critic's `partly` notes help |
| `finding-vs-decision` | a finding's fix would change something the owner decided, or a core finding needs the owner's decision | you, and `next` |
| `new-direction` | the work moves to a direction the sealed slice does not cover | `next` |
| `reference-vs-brief` | a reference's `leave` or `take` contradicts a row | you, when you write the `leave` |
| `budget` | you have worked alone past the budget, or a job will run over 30 minutes or spend paid or remote compute | `next` for time; you for jobs |

`next` raises three of these itself, as a step named `ask`: an after-slice change to a direction field
(`new-direction`), a change to a decided area while a finding about it is open (`finding-vs-decision`), and agent-alone
time past the budget (`budget`). Its text names the rows. Answer it with an ask that carries the same trigger, or undo
the change; either lifts it. A CLI-raised ask is exempt from the one-per-checkpoint rule.

## Shape

The first line is `lapis-questions: ask`. Then:

```text
lapis-questions: ask
Trigger: finding-vs-decision — critic review.taste-conflict on the seven plates; your K5 "keep ruled index rows"
1. Give each plate its own composition, or keep the repeated plate?
   a) one composition per plate  b) keep the repetition
   Default: a — I build plate 1 and 2 differently and keep the rest until you see them.
Unless you object: the install strip moves under the hero (the 390 capture hid it).
```

The file does not wait when any of these fails, and `next` says which:

- exactly one numbered question;
- a `Trigger:` line with one of the six ids;
- a `Default:` line;
- at most two "unless you object" lines;
- at most 150 words, not counting the kind line.

An ask has no owner block, no draft review, and no "here is what I did" paragraph. A question about a rendered page is
kind `approval`, not `ask`.

## Pausing

The questions file is the record in every harness; a question tool only changes how it is shown.

- With a question tool: write the file, ask the question with its options (the default first), record the reply, and
  run `next`.
- Without one: stop with the file's text as your last message. `next` says `waiting-for-user`, and an attended exit gate
  only prints a notice.

## Answers

Record the reply in `.lapis/answers/<task>.md` under `## Asks`, in the owner's words:

```text
- [declared] Ask finding-vs-decision: one composition per plate, but keep plate 6 as it is — "<their words>"
- [declared] Ask finding-vs-decision: default — "<their words>"
```

Both are requirement rows the critic judges. The second says the owner took your default.

## Unattended

With `LAPIS_UNATTENDED=1` nothing waits. Take the default and record it under `## Asks`:

```text
- [assumed] Ask finding-vs-decision: <the question> — took a. Basis: nobody to ask; a is the change that is cheaper to undo.
```

`next` returns `brief` when the `Basis:` is missing. The owner block lists these as questions the run answered itself.

## Not nagging

- **One ask per checkpoint.** A checkpoint is the step `next` would name. A second ask you raise at a checkpoint that
  already has an answered ask does not wait: take your default, record it as `[assumed]` with its `Basis:` under
  `## Asks`, and the owner sees it at the next approval wait, the next ask, or `done`.
- **Batching.** One question that needs the owner, and at most two defaults stated as "unless you object".
- **Nothing already settled.** Do not ask what a brief, direction, or approval answer settled, unless you quote that
  answer's row id, which makes it a `requirement-conflict` or a `finding-vs-decision`.
- **Short.** At most 150 words.
