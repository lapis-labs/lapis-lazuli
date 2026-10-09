# Interface copy

## Sections

Read the section for the string being written, by heading; the rest are other strings.

- One owner for every string: each line's role, form, speaker, length, and who owns it
- Decide what the screen must show: the information before the words - the decision the reader makes next, what the genre always shows, what a dashboard counts, and a flow that narrates itself
- Labels, buttons, and fields: naming controls, fields, and headings
- Errors: what an error names, and what it keeps
- Empty, loading, success, and other states: the cause behind each state and its text
- Confirmations and destructive actions: naming the object, the consequence, and each button
- Consent, price, and leaving: price, renewal, consent, and cancellation wording at the decision
- Claims, proof, and real content: the strength a claim may state and the fact behind it
- Preserve the proposition when editing: routing a complaint before rewriting copy
- Reject the writer's own voice: whose "I" is on the page, session narration, and source wording that is not the product's
- Headlines: compress the proposition, not the ending; breaks and joins
- Register and language: the voice policy per locale and role; then the section for the language you write in
- Korean: register levels, role forms across genres, honorific and wording conventions
- Japanese: politeness level (desu-masu or da-dearu), role forms, and script mix
- Chinese: script and region first, vocabulary by market, punctuation
- Translate, or write again: the meaning contract and what each locale rewrites
- One state in four languages: one state written in English, Korean, Japanese, and Chinese
- Messages with variables, numbers, and dates: whole messages per case, plurals, dates
- One voice, one term per thing: voice and terminology across the product
- The kiln shop: the worked copy example
- Check: the copy rules `plan check` and lint apply

This file backs the skill's **Interface text** and the plan's `content`: `content.voice` (the speaker and the form
of each role, per locale, and notes) and the `content.key_copy` slots `cta`, `nav`, `empty-state`, and `error`. Where a
message appears, how long it stays, what is announced, and where focus goes belong to the `lps-ux` skill; this
file decides the words, the register, and the facts the words may state. Examples continue the example
plan's pottery shop: one firing of twenty-four pieces, reserved mostly on phones, in ko-KR with `haeyo`
sentences, with Japanese and Chinese candidates where a second locale shows the same decision. Product
facts in the examples are synthetic; a real project supplies its own.

## One owner for every string

A string earns its place by answering a question the reader has on this surface, in this state. Name
its role before writing it; each role has one place, one test, and its own form. Read the rendered
outline, not the markup: a paragraph can be a deck, a heading can be a dialog's instruction, and font
size alone does not name a role.

Choose the form of each role, then the register of the roles that carry sentences. `compact` is a form,
not a speech level: a noun phrase, an action phrase, or an ending left off, and it never conflicts with a
polite product voice. The plan's `content.voice.locales.<language>` holds `prose` (the register of deck, body,
help, status, and legal), an optional `speaker`, and `by_role` where a role differs. Say who speaks only where
the page could mistake it: the product states what it is or can do, the visitor labels an action, an
instruction asks the visitor, and a disclosure speaks for the maker.

| Role | Visitor question | Form (Korean) | Length and composition | Never lose |
|---|---|---|---|---|
| Headline, display | What is this, or what does it claim? | a content name, a compact proposition, a noun phrase, an ending left off; a full sentence when the genre or the claim earns it | one proposition, set to fit its narrow block | object, contrast, scope, certainty |
| Deck, summary | What is it, and for whom? | a full explanation in the publication's register, not the chat's | definition first, one or two short sentences; implementation detail goes to the body | what the product is, whom it serves, the material qualification |
| Body | What does it do, and how? | the publication's register: consumer guidance, formal service facts, or an article's written form | paragraphs that each make a move; no quota of short sentences | qualifications, transitions, facts |
| Label, navigation | What is this thing or place? | a noun or status phrase, an ordinary compact action; no speech-level ending | identifiable at a glance, parallel with its peers | the term; visible and accessible names agreeing |
| Action (button) | What happens if I choose this? | the outcome as an action phrase: 설치 명령 복사, 예약 내용 확인, 삭제; never stretched into 복사해요 to sound friendly | fits the control, tells different outcomes apart | object, destination, consequence |
| Instruction, help | What must I do here? | addressed to the visitor: 해 주세요, 선택하세요 | one task at a time; longer when it prevents an error | the required format or condition, the actor, the object |
| Error, status | What happened, and what now? | the surface's operational voice; a compact diagnosis as the title, a sentence as the detail | the cause or state and a way forward | kept work, the actual outcome, uncertainty, recovery |
| Legal, consent, price | What am I agreeing to, or paying? | the approved legal register, never converted from help text | no cosmetic ceiling; hierarchy and disclosure carry the length | obligation, possibility, price, renewal, refusal rights |

The table sets starting points, not required fields: the same polite register may serve several roles while
naming, acting, and narrating keep their own forms, and no role is made different only to look varied. Changing
`haeyo` to `hapnida` alone repairs no hierarchy. Keep the real subject, facts, and claim strength. Page copy
explains the subject or product for the visitor; this website's own font, palette, layout, and workflow rationale
belongs in the plan unless the brief asks to show it. A design product may explain typography as a capability,
but the site's font pairing alone is not an example of that product's actual output. Review the rendered text
for that substitution.


| Role | The reader asks | It goes | Test |
|---|---|---|---|
| Label | What is this thing or action? | on the control, field, or destination | stands alone in a scan and in a screen reader's list |
| Helper | What format or limit prevents a mistake? | beside the field, before it can fail | the person acts differently because of it |
| Error | What failed, what does it touch, what now? | at the problem | specific, tied to its cause, has a way forward |
| Status | What is true now? | where the changed thing is watched | reflects the product's real state |
| Consequence or policy | What will this cost, delete, send, or commit; which term applies? | beside the decision, before it | removing it would change the choice; scope and force kept exactly |
| Help | How does this work beyond now? | linked and findable | durable, reachable from where it is needed |
| Nothing | (nothing is unclear) | leave it | added text would only narrate the interface |

- A label is not a small help article, helper text is not a hidden label, and help is not a place for a
  consequence to wait. Price, renewal, deletion, and data use sit beside the decision, never behind
  hover or a help link; hover content fails on touch and from the keyboard (`ux.hover-content`).
- Two nearby strings that make the same claim for the same reader in the same state are one too many:
  keep the one that owns the claim. The same consequence at two different decisions, when a person
  enters a flow and when they commit, stays in both.

```text
Before: 작품 예약
        아래 버튼을 눌러 작품을 예약할 수 있어요.
        [예약하기]
After:  작품 예약
        [예약하기]
```

The middle line narrates the button; replace it only with something the button does not say, and only
when that is true.

- **Builder-facing text** (service and queue names, request IDs, retry counts, feature flags, build
  labels, notes for a reviewer) stays out of the interface unless this audience uses it to decide,
  recover, or reach support. Say the effect instead: 파일을 가져오지 못했어요. 바뀐 항목은 없어요. On an
  operator surface the exact terms are the vocabulary and stay: the audience decides, not "technical"
  against "human". `copy.meta-text` reads copy addressed to the builder or to QA.
- **Sample data, simulation, and non-delivery** are consequential facts, not decoration. State each once,
  where it changes what someone believes or does: sample records at first exposure, a simulated action
  beside the action, work that will be lost before the save, close, or reset. The same notice as a chip
  on every card or a suffix on every toast is `copy.decorative-metadata` and `copy.meta-text`. Test
  setup and reviewer instructions belong to the developer handoff.
- **What the page must show, and what it must not.** Decide first what the visitor needs: the subject and the
  task. Leave out how the page was made, that it is a demo beyond one notice, and what changed since the last
  version. When the brief requires a notice that the data is fictional, write one short line in the footer or a
  small persistent label, in the page's language, never in the hero, a heading, or beside each section; a
  translation beside it is the same notice. Cut each of these in any language (`copy.meta-text`): "this is not
  a real exhibition" under the title, a demo or fake-data warning repeated per section or in a questions list,
  change-log narration ("We updated...", "I fixed...", "...has been improved"; 수정했어요, 개선되었습니다;
  修正しました, 改善されました), the page explaining itself ("This section shows...", "Click the button below to...";
  이 섹션에서는 …, このセクションでは…), developer and test notes, and an apology for a part that was never built.

## Decide what the screen must show

Decide the information before the words. Ask what this reader has to decide or do next on this surface, what they
must see to do it, and what the genre of the surface always shows: a booking, the choice so far and what comes next;
an exhibition, the dates, place, hours, and admission; a news page, the headline, deck, byline, and date. A line that
stays true when the subject is swapped carries none of it.

- **A dashboard counts what a decision hangs on.** What is late, full, or failing, the next arrival, a queue against
  its limit, each with its limit or its change. For every number ask which decision changes with it; with no answer,
  there is no number. Totals nobody acts on (vehicles running, routes in service) suit a report, not the first view
  of a console.
- **A flow does not describe itself.** "In the next step you will enter your details" (다음 단계에서 정보를 입력합니다)
  says what the next screen says anyway. The step title, the field labels, and the button name the work. Say only
  what the screen cannot: what to have ready, what will be shared, what happens after the commit
  (`copy.meta-text`).
- **A repeated slogan gives nothing to decide with.** Cut it, or replace it with the fact: a time, a price, a place,
  a state.

## Labels, buttons, and fields

Read neighboring headings or result titles without paragraphs. Put differentiating words early
where the language allows: "Delayed transfers" distinguishes sooner than "Information about
delayed transfers." Support returning readers as well as first-pass scanning. Preserve natural
grammar, governed terms, and locale information order; never frontload away a qualification or
shorten a heading into a noun pile.

**Actions name outcomes.** A verb and its object, or the destination: the label says what will happen,
not that a click will.

| Weak | Stronger | The stronger label says |
|---|---|---|
| 제출 | 예약하기 | the outcome of pressing it |
| 확인 | 예약 내역 보기 | where the person lands |
| 예 (in a confirmation) | 예약 취소 | which action a "yes" commits |

`copy.vague-cta` (a gate at P1) reads a whole control label: "계속" alone is vague and "예약 내용 확인"
names its outcome. A plain "계속" beside a step title that states the outcome is a `keep_when` case
(`step-title-states-outcome`) the check cannot see, so record a `keep` in the plan's `defaults` with
that id and reason; the case also needs a multi-step flow in `flows` (`max_steps` of two or more). The same rule reads
duplicate labels. Two actions with different outcomes never share one: on a piece card 작품 보기
opens the piece, and 예약하기 on the sheet commits.

- One word per intent. If 저장, 적용, and 수정 all commit the same settings, choose one; if they differ,
  make the difference visible in the words.
- The visible label starts the accessible name, so a voice-control user says what they see. A visible
  `Download photos` with the accessible name `Download photos of the September firing` matches; `Get
  files` with that name does not. No check compares the two, so keep them together by hand; a control
  with no name at all is `component.unnamed-icon-button` (icons) or `component.unlabeled-input` (fields).
- **Fields.** A persistent visible label; a placeholder may show an example but is never the label
  (`component.unlabeled-input`). Put a format, limit, or eligibility rule before the field can fail.
  State units, currency, time zone, and date format where the answer would otherwise be ambiguous, and
  mark optional fields as optional; do not repeat "required" on every field of a form where all are.
- **Case and punctuation** are the project's system decisions; sentence case is the English default here.
  Pick one final-punctuation rule per role (for example none on labels and buttons, a period on full
  sentences) and keep it across screens, in every language.
- **Navigation labels** (`slot: nav`) use the plainest word the reader already uses and carry no voice.
  The `lps-ux` skill decides which destinations exist and how they group; this skill words them.

## Errors

An error names what happened, what it touches, what the person can do next, and what was kept, in that
order and in as few sentences as the facts need.

```text
예약을 저장하지 못했어요. 입력한 내용은 그대로 남아 있어요.
[다시 시도]
```

Say only what the product knows. A plain retry (`[다시 시도]`) is honest when the product knows only that
the request failed; a cause it cannot confirm ("네트워크 문제로") is invented. The copy also agrees with the
behavior: "입력한 내용은 그대로 남아 있어요" is false when the form cleared (`ux.lost-input`).

`copy.error-without-recovery` (a gate) reads an error or offline state that says nothing about the
problem or offers no working way forward; a state with no way forward is also `ux.dead-end`. Make the
way forward a real button or link with its own label, not a sentence telling the person to reload.

Diagnose the cause before wording it; the cause decides what the copy may claim.

| Known | Say | Never |
|---|---|---|
| Input unusable under a known rule | at the field, the rule as an instruction: 연락처는 숫자만 입력해 주세요. | a page-level "저장 실패" for a field problem; a message while the person is still typing (`ux.premature-validation`) |
| The operation failed, confirmed | what failed, that entries stayed, the retry | an invented cause or fix |
| Permission or sign-in is missing or expired | what the person may do, and who can grant more | marking valid input invalid; telling whether a protected item exists |
| Connection lost | only what is confirmed saved or sent | 저장됐어요 when the text sits only in page memory |
| Outcome unknown | that it is unconfirmed, and where to check | "failed" (`ux.false-status`), or a retry that may charge twice (`ux.duplicate-submit`) |
| Some items succeeded | per-item results and a retry for the failed item only | one generic failure |

For an unknown outcome:

```text
예약이 접수됐는지 확인하지 못했어요. 예약 내역에 없을 때만 다시 신청해 주세요.
```

The line is only as good as the check it points to; write it when 예약 내역 exists.

- A field error is text tied to its field, beside it, never color alone (`ux.input-error-unidentified`);
  the `lps-ux` skill places and announces it.
- No blame, no jokes, no apology in place of the fix. An apology may open a serious failure but never
  replaces the sentence that helps; a cheerful interjection has no place in a payment, health, or
  repeated-failure state.
- A support reference belongs in an error only when someone can look it up; label it as one (문의 번호),
  and keep stack traces, queries, and internal host names out.
- Positive framing must not erase a failure: 잔액이 없어요 cannot become 충전할 수 있어요 when the missing
  balance is why payment failed, though the second may follow the first.

## Empty, loading, success, and other states

Empty states are causes, not one template. Say which one it is, and write only the entries the flows can
reach (`ux.missing-states` gates a reachable state that was never designed).

| State | The reader asks | Write | Example |
|---|---|---|---|
| First use | What belongs here, how do I begin? | what it holds and the first action | 예약한 작품이 아직 없어요. 9월 소성분에서 작품을 골라 예약할 수 있어요. |
| No results | Why nothing, how do I recover? | the active filter or query, and how to clear it | 선택한 조건에 맞는 작품이 없어요. 필터를 지우면 9월 소성분 전체가 보여요. |
| No access | Why can't I see it? | why it may not show, and how to check, without revealing what it holds or that it exists | 예약을 찾을 수 없어요. 예약한 계정으로 로그인했는지 확인해 주세요. |
| Unavailable | Is it late or gone? | what is missing and a retry | 가마 온도 그래프를 불러오지 못했어요. [다시 불러오기] |

- **Loading** says what is happening and whether the person can go on: 작품 24점을 불러오고 있어요. Show
  progress only when it is real (사진 12장 중 7장을 올렸어요), never a percentage guessed from elapsed
  time. A bare spinner over a region or page is `component.generic-spinner`.
- **Success** confirms the outcome and where it shows. For a consequential step, say it only after the
  system confirms it; a page that says done while the change failed or is unknown is `ux.false-status`.
  Exclamation marks and celebration are tone, not proof that the outcome is good.
- **Partial:** 작품 3점 중 2점을 예약했어요. 1점은 이미 예약돼 있어요. **Offline:** 연결이 끊겼어요. 지금
  보이는 목록은 9시 42분 기준이에요. A state needs no added copy when the result is visible in place; a
  toggle does not need a toast.

## Confirmations and destructive actions

A confirmation names the object and the consequence, and each button names its own outcome.

```text
9월 소성 예약을 취소할까요?
취소하면 이 작품을 다른 사람이 예약할 수 있어요.
[예약 유지] [예약 취소]
```

- Name what is lost or changed, with the true reversibility. "되돌릴 수 없어요" only when it is true; when
  the shop restores a cancelled reservation for a day, say that. Never advertise an undo that does not
  exist. `ux.destructive-without-undo` accepts either a confirmation that names what is lost or a
  working undo, and lets a step the person can redo in one move, such as clearing a filter, pass.
- 취소 beside a decision that is itself a cancellation reads two ways: cancel the reservation, or cancel
  this window. Word the buttons by what they do (예약 유지, 예약 취소) and keep 닫기 for leaving a dialog
  that decided nothing.
- An estimate stays an estimate: 9월 소성분은 27일 전후로 나올 예정이에요, not 27일에 나와요.
- Before a binding step, show what is being agreed to and the total, in the words the person saw on the
  way in (`ux.no-review-before-commit`).
- A title may quote what it asks about (‘9월 소성 예약’을 취소할까요?). In running copy, though, a line
  that opens with a quotation mark reads as a customer quote (`copy.fabricated-proof`); quote a real
  person only with a source the plan names.

## Consent, price, and leaving

- Price, fees, renewal, trial end, and how to cancel appear where the person decides, at reading size
  (`ux.hidden-subscription`, `ux.drip-pricing`). When a charge depends on input still to come, such as a
  delivery address, name it as pending where the price first appears.
- Consent copy is specific, voluntary, and reversible where the choice is. It names who uses what, for
  what purpose, what is optional, and where to change it, and every clause matches what the product does.

```text
알림 메일 받기
다음 소성분이 올라오면 이메일로 알려드려요. 메일 아래쪽 링크나 설정에서 언제든 끌 수 있어요.
[다음에] [알림 받기]
```

- Optional consents are never preselected and purposes are not bundled (`ux.preselected-option`,
  `ux.consent-steering`). The way to turn it off exists as named; the example plan pairs
  `stop-firing-notices` with `firing-notices` for that reason.
- Refusal and acceptance carry the same weight in words and in size: 다음에 beside 알림 받기. A refusal
  worded to shame, guilt, or scare is `ux.confirmshaming`, a requirement that gates. Effort and visual
  weight (`ux.asymmetric-decline`, `ux.false-hierarchy`) belong to the `lps-ux` skill and the `lapis`
  layout step.
- Leaving takes no more words, steps, or channels than joining (`ux.obstructed-exit`): 알림을 신청했어요
  and 알림을 껐어요 are the same length and the same plainness.
- Urgency, scarcity, and demand words come only from facts the stub's `urgency` records
  (`ux.false-urgency`). A permission prompt's own copy names the need and follows an action that needs it
  (`ux.permission-on-load`).
- Onboarding and permission steps state the next concrete action, why a permission or connection is
  needed, whether the step can be skipped and what skipping changes, and show progress only when the
  sequence matters.
- Friendly wording does not make consent valid, and legal text is a qualified reviewer's. Keep the force
  and scope words exactly (must, may, the period, the exceptions), list wording that needs review as
  unresolved, and never soften a term to fit a button. Legal text keeps its own fixed register: name it in
  `content.voice.locales.<language>.by_role.legal`, and the register check accepts it in body copy. When it
  still reads as a slip, record a `keep` with `keep_when: fixed-legal-register`, that reason, and the `evidence`
  (the legal source in `sources`, or a quoted brief line). Payment and account text more often take the
  product's formal register, set the same way in `by_role`.

## Claims, proof, and real content

State each claim at the strength the evidence supports, with a fact behind it: a capability someone can
verify, a number the plan records, or a world material. A line that stays true when another product's
name replaces yours says nothing (`copy.name-swap`); sales words, unsupported importance, and stacked
hedges are the `sales-voice` card.

```text
Before: 흙과 불이 빚어낸 특별한 순간을 만나보세요.
After:  9월 소성분 스물네 점을, 가마에서 꺼낸 그대로 찍은 사진과 함께 보여 드리고 예약을 받아요.
```

The after line uses only what the brief supplies: a monthly firing, twenty-four pieces, photographs taken
straight out of the kiln. Where those facts are missing, ask for them; never sharpen a line by
invention. On a landing page, name the audience when the product is not self-evident, put proof next to
the claim it supports, and state price, trial, account, or compatibility conditions before they
surprise. Drop internal release labels unless availability changes the decision (`copy.meta-text`).

- Proof is never invented. A metric, customer name, quote, logo, or credit that the plan's `claims` and
  `content.source` do not back reads as invented (`copy.fabricated-proof`, a requirement). Use real,
  permissioned proof, disclose sample data once where it is shown, or leave the slot plainly neutral.
- Placeholder people and firms hide the edge cases copy has to survive. Use synthetic content from the
  domain with long and local names (`copy.placeholder-content`, the `generic-content` card).

## Preserve the proposition when editing

Route the complaint before rewriting. Restore a missing actor, action, or state from evidence;
change order for a buried fact, placement for a distant consequence, and the label for an
unpredictable outcome. Keep sound wording when wrapping, clipping, or hierarchy needs type or
layout repair. Existing string ownership settles duplication. Rewrite stock rhythm at paragraph
level, not through flagged-word swaps. For open key copy, compare candidates against the diagnosed
failure in the copy `explorations`.

Before changing existing copy, list what must survive; afterward, compare.

Inspect meaning before typesetting: read headings alone, check each paragraph's move, and keep
qualifications beside their claims. List items must be true peers or steps. Semantic emphasis marks
importance or stress; a quotation identifies a source, not merely a sentence worth enlarging.
A decorative pull quote must not make the reader encounter the same passage twice nonvisually.

| Keep | The failure |
|---|---|
| Facts and values: people, objects, status, cause, scope, numbers, dates, prices, units | a smoother sentence invents a cause or drops an exception; "about" replaces an exact amount |
| Force: must, need, may, can, cannot, optional | a requirement becomes advice, or an option becomes mandatory |
| Action and consequence: actor, verb, object, destination, deletion, charge, access, timing, reversibility | "계속" replaces "예약 내용 확인"; a short confirmation hides permanent loss |
| Recovery and uncertainty: the fix, retry, kept input; known against estimated | an error is cut down to a diagnosis; an estimate becomes a promise |
| Terms and links: governed vocabulary, destination, visible purpose | a precise term becomes a friendly, wrong one |
| Names: visible label, accessible name, role, state | the text changes and the `aria-label` stays stale |

Then write down what was **added** (each new claim, with its evidence), **dropped**, and changed in
**force**, **state**, and **names**. An unsupported addition is an error, and so is a dropped item unless
it duplicated another string for the same reader and state. Fix the worst problems first: a wrong
action, a missing consequence, or an unsupported claim comes before rhythm or dashes.

Never remove for length or looks: eligibility, price, renewal, cancellation, retention, consent, or
legal-force detail; safety instructions and regulated terms; an error's cause, scope, kept work,
recovery, and reference; accessibility instructions and alternatives; uncertainty and a last-updated
time; help for a task question that recurs. When it does not fit, change the hierarchy, the disclosure,
or the component, never the meaning.

```text
Before: 사진을 올리지 못했어요. 문제가 발생했습니다.
Known:  12장 중 7장을 올렸고, 8번째 파일이 크기 제한을 넘었어요. 나머지는 올리지 않았고, 8번째부터 이어서 올릴 수 있어요.
After:  사진 12장 중 7장을 올렸어요. 8번째 파일이 크기 제한을 넘어서 나머지는 올리지 못했어요. 파일 크기를 줄이면 8번째부터 이어서 올릴 수 있어요.
```

The edit adds detail only because the product state supplies it, and it fixes the mixed endings on the
way. Leave copy alone when it is already exact: a real contrast that corrects a likely misreading
(보관하면 사이드바에서만 사라지고, 기록은 그대로 남아요.; if `copy.contrast-frame` counts a contrast
like it, record a `keep` with `keep_when: scope-or-misconception` and the reason that it carries
scope), a precise term for its audience, legal
scope with its exception, and a short true consequence such as 삭제하면 되돌릴 수 없어요.

## Reject the writer's own voice

Read the page as if no conversation with the owner existed, then ask of every suspect line:

- **Who is "I", "we", "my", "내"?** If it is not the brand, a labeled quotation, or the visitor in a control that
  says so, resolve it. Do not delete every pronoun: a brand's "we" and a visitor's 내 예약 are right where the
  speaker is established. `copy.unanchored-speaker` leads to a possessive in running copy; set `speaker` in the
  plan when the page speaks as the user.
- **Does it describe the product, instruct the visitor, or report what you did to build the page?** Production
  reasoning stays in the plan. A limit of the evidence, or a disclosure the reader needs, stays once, where it applies.
- **Would it still sound right if the owner had spoken in another register in chat?** If not, the chat register
  is leaking: the language of a report to the owner is not the page's voice.
- **Does a term help this audience decide?** Keep the product's own vocabulary (finding, critic, world material)
  where the visitor needs it and explain it at the right depth; do not swap in a euphemism.
- **Read the headings alone, then the buttons alone.** If both sound like an assistant narrating a checklist,
  give them back their separate jobs.

Facts come from a README or a document; its narrator does not. A sentence lifted whole carries the document's
"I", its reader, and its register with it:

```text
Before: 구현이 끝나면 ultramarine이 내 렌더에 lapis-design을 돌려요.
After:  ultramarine은 렌더된 화면과 동작을 검사해요.
```

The after line drops the possessor and keeps the product's action. The wider explanation still has to say which
command runs and under what conditions, and promise nothing the source does not support.

## Headlines

A long or sentence-shaped headline is a role problem before it is an ending problem: an explanation is doing a
title's job. Work in this order:

1. Write the literal proposition.
2. Keep its subject, object, scope, and certainty.
3. Put the strongest piece of information in the headline and the condition or detail in the deck beside it.
4. Compare two candidates that really differ, set in the real layout at the narrow and the wide width.
5. Leave an ending off only when what remains reads as intentional in the language. Stripping 요 from
   계획이 먼저예요 does not make a headline.

Candidates to compare, not approved copy:

```text
휴대폰에는 휴대폰의 순서가 있어요        →  휴대폰에 맞는 정보 순서
눌러도 아무 일 없는 버튼은 지적 대상이에요  →  동작하지 않는 버튼도 검사   (the checker's detail goes in the line below)
```

For a product hero, compare a proposition (코드보다 먼저, 화면 계획) with a factual line (코딩 에이전트용 화면 계획과
검사); the facts do not pick the winner. Never turn a promise into a noun phrase that hides whether it is
possible, mandatory, or only proposed, and never cut a medical or legal possibility for rhythm.

A length is a lead, not a limit: no source sets a number. `copy.headline-budget` starts at 32 characters in
Korean, Japanese, and Chinese or 12 words in English, and at three lines for a display heading or two for any other
heading at phone width, and it reads a title set as word spans as one title. A deliberate exception needs a
rendered reason, not a field in the plan. A 19-character line can still dominate the wrong part of the page, so
look at the render.

**Breaks and joins.** A forced break is not a word separator. Keep the phrase, a particle with its noun, a proper
name, and a number with its unit together, and never add or remove a Korean space to fix a line.
`word-break: keep-all` is not a pass: it still allows an emergency break, so read the actual lines. For a title with
a `<br>`, check the canonical string, the visible lines, the extracted text, and the accessible name. Do not shrink
body text to hide a long title.

## Register and language

`content.voice.locales.<language>` holds the voice of one locale. `prose` is the sentence register of the roles that
carry sentences; `speaker` says who they speak as (`brand`, `product`, `editorial`, `user`); `by_role` sets one role
(`headline`, `deck`, `body`, `label`, `action`, `help`, `status`, `legal`) to `compact` or to a register of its own. A
role the plan names nothing for keeps its form: headline, label, and action are compact, the rest take `prose`.
`content.voice.notes` is free text for writers and reviewers; no check reads it.

The checks read what the plan holds, per locale and role:

- `copy.register-mix` (P2) reads the sentence endings of each locale against the register of that role. It does not
  classify a compact role, a sentence that opens with a quotation mark, or a role the plan sets nothing for, and it
  reads Korean, Japanese, and Chinese: an English `prose` value is for writers and the critic. The render tells a
  headline, a label, an action, and a status the page marks as an alert or status; a deck, help text, or legal text
  reads as body, so body copy may end in any register the plan names for those roles. With no sentence register in
  the plan, the page's majority stands in.
- `copy.role-collapse` (P3) is a lead when most headlines end in the same sentence register as the body: one narrator
  in two jobs. Uniform voice alone is no defect; a deliberately conversational product records a `keep` with
  `keep_when: conversational-product`, saying so.
- `copy.headline-budget`, `copy.unanchored-speaker`, and `copy.translationese` (P3) lead to the headline rules, the
  speaker, and translated constructions below.

The counts route a review. No ending count approves a text, and no check replaces a proficient reader. Register
follows the product, the surface, and the reader, never a nationality. Read the notes below as decisions to
confirm, not settled style: a reader proficient in the locale confirms product terms and tone, and the report says
so when none has.

### Korean

| Register | Recognize it by | Fits, not a mandate |
|---|---|---|
| `haeyo` | -아요/-어요, -해요, 이에요/예요; requests 해 주세요 | help, onboarding, most consumer interfaces |
| `hapnida` | -습니다/-ㅂ니다, 입니다; questions -습니까; requests -해 주십시오 or -해 주시기 바랍니다 | formal notices, public, finance, and enterprise services, a formal product voice |
| `haera` | plain written -다/-이다, -었다 | definitions, reports, explanatory articles |

- **Labels are not sentences.** 저장, 검토 중, 결제 내역, and 필수 need no ending, and a label expanded into
  a sentence is a mistake: the label 배송지 stays a label, and the instruction 주문을 받을 주소를 입력해
  주세요 is a separate string. A label promises the destination or the action; the register applies to
  sentences.
- **Role before ending.** A title can name content, a definition says what the product is, a
  capability states a verifiable fact, an instruction names what the visitor should do, and an
  action label names their chosen outcome. Do not turn all of them into "~해요" sentences because
  `prose` is `haeyo`: "화면을 계획해요" cannot stand indiscriminately for a product definition, a feature,
  and a button. Keep the speaker and the statement/request distinction visible. A noun phrase is a form, not a
  speech level.
- **Choose by speaker and role, then keep it.** `haeyo` is common in consumer interfaces; `hapnida` in public,
  financial, enterprise, and cultural surfaces and in a formal product voice; `haera` in definitions, reports, and
  articles. Roles may rightly differ, as below; inside one speaker, role, and locale, keep one. Formality is no
  safety mechanism: an alert or a destructive decision keeps the surface's register and adds the object, the
  consequence, and the recovery, never jokes or a softened consequence.

  | Job | Consumer booking | Exhibition | Public service | Developer product |
  |---|---|---|---|---|
  | Headline | 진료 예약 | 빛이 머무는 자리 | 주민등록 등본 발급 | 코딩 에이전트용 화면 계획과 검사 |
  | Deck | 원하는 날짜를 고르면 가능한 시간이 나와요. | 재료가 다른 작품 서른 점을 전시합니다. | 수수료와 처리 기간을 확인한 뒤 신청합니다. | 스킬은 코드를 쓰기 전에 요청을 계획 파일로 정리하고, CLI는 렌더된 화면을 그 계획과 대조한다. |
  | Action | 예약 내용 확인 | 관람 예약 | 발급 신청 | 설치 명령 복사 |
  | Error | 예약을 저장하지 못했어요. 입력한 내용은 그대로 남아 있어요. | 예약이 저장되지 않았습니다. 입력한 내용은 그대로 남아 있습니다. | 신청이 접수되지 않았습니다. 잠시 후 다시 시도해 주십시오. | 명령을 복사하지 못했어요. 직접 선택해 복사해 주세요. |

  The facts are synthetic and a native Korean reader has not confirmed these lines. The point is the spread: four
  genres, four mixes of compact and sentence forms, no shared ending.
- **Never convert by suffix.** The same facts in each register:

  ```text
  haeyo:    예약이 저장됐어요. 예약 내역에서 바꿀 수 있어요.
  hapnida:  예약이 저장되었습니다. 예약 내역에서 변경할 수 있습니다.
  haera:    예약이 저장되었다. 예약 내역에서 변경할 수 있다.
  ```

  Check the predicate class (action verb, descriptive verb, noun with the copula) and keep tense,
  negation, possibility, and obligation: 저장해요 does not become 저장이다, and 커요 does not become 큰다.
  Decide requests apart: 확인해 주세요 and 확인하십시오 differ in tone, while 확인한다 is a statement and
  확인하라 a bare command, and neither is a neutral request to a customer. 저장합니다 is a `hapnida`
  statement, not the formal form of 저장해 주세요.
- **Do not mix by accident.** 파일을 올려 주세요. 업로드가 완료되었습니다. 확인해. becomes 파일을 올려
  주세요. 업로드가 완료됐어요. 내용을 확인해 주세요. A casual brand voice (`other`) is an explicit
  decision with its own boundaries.
- **Honorifics follow real roles.** The subject honorific `-시-` is separate from sentence-final
  politeness: 등록할 수 있어요 and 등록하실 수 있어요 are both `haeyo`. Do not stack it onto staff or
  add it when converting registers. 고객님께서 입력해 주신 정보를 담당자분께서 확인해 주실 예정이에요
  becomes 입력하신 정보는 담당자가 확인할 예정이에요: respect for the reader stays, the staff role
  drops its stack.
- **Particles and endings carry the relations.** Restore them where a compressed line hides an action:
  계정 삭제 시 프로젝트 접근 불가 becomes 계정을 삭제하면 이 프로젝트에 접근할 수 없어요. Restore only
  what the product supplies: from 승인 대기. 게시 불가., write 승인을 기다리고 있어요. 지금은 게시할 수
  없어요.; the stronger 관리자가 승인하기 전에는 게시할 수 없어요 is written only when the rule and the
  actor are confirmed.
- **Translationese.** `copy.translationese` warns when, by density, constructions carried over from
  English accumulate. In Korean it counts five: double passives (되어지다, 쓰여지다), ~에 있어서, ~를 통해, ~에 의해,
  and ~것이 가능. One instance alone is never counted, since one construction that names a real route stays correct:
  시스템을 통해 목록을 만들어요 names the system the list passes through. A surface made of them reads as
  translated: 요청은 시스템에 의해 처리됩니다 becomes 시스템이 요청을 처리해요, and 이 화면을 통해 예약 내역을 변경하는
  것이 가능해요 becomes 이 화면에서 예약 내역을 바꿀 수 있어요. Agentless passives (이해됩니다, 확인됩니다) are
  grammatical, so repeating them is a style question for the writer, not a count. The check does not see chains of
  nouns, a compressed relation (대상의 사실로, 그 언어로 화면 문구를 써요: whose facts, which language?), or an
  abstract actor with a long modifier (검사가 들여다보는 완성된 작업); the writer and the critic catch those. A
  needless pronoun goes too: 우리는 결제를 처리하지 못했어요 becomes 결제를 처리하지 못했어요. Keep a passive when
  the result matters more than the actor.

### Japanese

- Use `desu-masu` for explanatory sentences addressed to the reader on most product surfaces and `da-dearu` for
  definitions, reports, and explanatory articles. Never both in running text. Screen titles and item names are
  noun phrases and buttons are action forms, and the choice is the product's: 予約を確認 (object and
  verbal noun) or 予約の確認 (noun phrase). Pick one pattern for buttons and keep it; です・ます belongs to the
  explanation, not the title.
- Use the direct potential form. `copy.translationese` counts the nominal ability construction
  することができる, and ことができる without する, by density: この画面から予約内容を変更することができます becomes この画面で予約内容を変更できます.
- A polite request stays polite in a formal flow: 送信前に内容をご確認ください. Do not drop ご or slide
  into plain speech to sound lighter.
- Japanese omits a recoverable subject; do not add あなた to fill the gap, and name the object when the
  actor is ambiguous. Use the counter that goes with the noun (作品24点, 3件).
- An error keeps the same shape as in Korean: 予約を保存できませんでした。入力した内容はそのまま残って
  います。もう一度お試しください。
- No proficient Japanese reader has read these notes. Genre, honorific level, title wording, and button convention
  need one before they are called settled.

### Chinese

- Fix script and region first. `zh-Hans` and `zh-Hant` name scripts, not markets; vocabulary differs by
  market, and converting characters is not localizing. A pair such as 保存 and 儲存 is two regional
  choices, so terms come from the project's termbase.
- The plan's `zh-formal` and `zh-casual` name the address form the check reads: 您 reads as formal, 你 as
  casual, and a sentence with neither is left unjudged. Which a product uses is a documented product and
  market decision, and a plain 你 voice is not a careless one; omitting the pronoun is common in
  interface Chinese.
- Cut what English syntax adds. `copy.translationese` counts every 进行 and 被 by density and cannot
  tell a needed one from filler: 您可以通过点击下面的按钮来进行预约的取消 becomes 点击“取消预约”即可取消.
  If the button already says 取消预约, the sentence goes. A short true consequence stays short:
  删除后无法恢复。
- Punctuation follows the region: curly quotes “ ” on the mainland, corner brackets 「 」 in Taiwan (Hong
  Kong varies), full-width marks inside Chinese sentences, half-width in Latin runs. Choose the measure
  word by the noun (一件作品, 一个订单) and do not reuse one across nouns.
- An error: 没能保存预约。已填写的内容仍然保留，请重试。

### Translate, or write again

Keep one meaning and facts contract across locales, not one rhythm. Names, figures, obligations, destinations,
recovery, and uncertainty are translated faithfully. Headlines and decks are written again around the same
proposition and genre; operational and legal copy permits much less movement.

- Korean may leave off a headline's ending and a recoverable subject; Japanese may use a noun title and an action
  button, with です・ます only in explanation; English may use a task verb and sentence case without a final period.
- Carry no forced line break, "you" frequency, italic closing phrase, or character count from another locale, and
  never put あなた or 당신 in everywhere because the English source said "you". Compare each locale's own layout, not a
  back-translated elegance.
- Back-translation checks for drift in meaning; it is no evidence that the target reads as native.
- Naturalness, register, and title craft in English and Japanese need a proficient reader of that language. Say in
  the report that none has read the text until one has.

### One state in four languages

Exercise facts: the reservation is saved; it can be changed on its page until the firing closes. No
other promise is supplied.

| Locale | Copy |
|---|---|
| ko-KR, `haeyo` | 예약이 저장됐어요. 소성 예약이 마감되기 전까지 예약 내역에서 바꿀 수 있어요. |
| ja-JP, `desu-masu` | 予約を保存しました。焼成の受付が終わるまでは、予約内容のページで変更できます。 |
| zh-Hans | 预约已保存。烧制预约截止前，可在预约详情页修改。 |
| en, `en-casual` | Reservation saved. You can change it on the reservation page until the firing closes. |

The structures differ and none adds a promise. Write each locale from the facts, then read it as a reader
of that language would; a line that only makes sense turned back into English gets rewritten.

Hand a language reviewer the locale and region, surface and state, trigger, variables with example
values, the action and its consequence, the visible and accessible names, the register and terms, and the
width limit with its reason. Report naturalness, honorific level, and terminology as unconfirmed until
someone proficient has judged them.

## Messages with variables, numbers, and dates

- Write a whole message per case, with named variables. Never join fragments around a variable or a count.
  English needs plural rules; Korean, Japanese, and Chinese need the counter that goes with the noun
  (점 for pieces, 건 for cases, 명 for people; 点, 件; 件, 个), and the numeral stays a figure beside it:
  24점.
- **Korean particles after a variable** depend on how the value is read, so a suffix rule is wrong for
  Latin letters, digits, counters, and mixed text. In order of preference:
  1. Rewrite so the variable takes no particle: 예약한 작품: {pieceName}.
  2. Put a stable noun after the variable: {pieceName} 작품을 예약했어요, not {pieceName}을 예약했어요.
  3. Store the approved spoken form or class beside the value.
  4. Use the project's vetted Korean message tool, within its documented limits.
  5. For plain Hangul only, test the last syllable: `(code point − 0xAC00) mod 28` is nonzero when it has a
     final consonant. `로` follows a vowel or a final ㄹ (서울로, 길로) and `으로` other finals (집으로).
  6. For Latin, digits, mixed script, and trailing punctuation, get the reading or rewrite the message.
  The last syllable never decides the meaning: 은/는 against 이/가, 에 against 에서, and 으로서 against
  으로써 are choices of meaning.
- Format dates, numbers, currency, time zones, and lists for the locale with the platform's own tools,
  and keep values numeric until display. Show a currency code where the symbol is ambiguous, and never
  round money for display. `code.locale-time-rendering` reads hard-coded locale strings at the source.
- Give translators context: name each string by meaning (`reservation.cancel.confirm_body`), and say the
  surface, the state, what each variable is, and the register. A bare 완료 could be a status or an
  action; do not make anyone guess. A component grows or wraps for a longer string; carry no character
  budget from one language into another.

## One voice, one term per thing

- Voice is the stable character of the product; tone changes with the situation. A routine message is
  plain, a failure specific, a high-stakes one restrained and explicit, with no jokes. A voice
  description earns its place only when it changes decisions about strings.
- Keep a term record and use it across navigation, headings, labels, help, emails, and locale files. The
  glossary in `../shared/vocab/glossary.yaml` covers design terms with Korean equivalents for your own
  plan and report; product vocabulary comes from `PRODUCT.md` and the user.

| Concept | Use | Avoid | Why |
|---|---|---|---|
| a firing's pieces | 소성분 | 이번 달 컬렉션 | the shop's own word, and the firing log uses it |
| holding a piece | 예약 | 주문 | 주문 promises payment and shipping, and the plan lists delivery regions as unresolved |

- When a term changes, search every place it appears, and report conflicts between screens rather than
  choosing silently. Synonyms belong in search matching, not on screen.

## The kiln shop

The example plan already holds the headline, a compact title, and the 예약하기 call to action, a compact action.
Add the source note, the voice, a deck, and the states the flows can reach:

```yaml
content:
  source: Synthetic wording written from the brief; the studio has supplied none yet
  voice:
    notes: The studio speaks to a visitor. Terms: 소성분, 예약 (not 주문).
    locales:
      ko:
        prose: haeyo
        speaker: brand
        by_role: { headline: compact, label: compact, action: compact }
  key_copy:
    - { slot: headline, text: 9월 소성분 스물네 점, locale: ko-KR }
    - { slot: subhead, text: "한 달에 한 번 가마를 열어요. 이번에는 청자 사발과 찻잔이 나왔어요.", locale: ko-KR }
    - { slot: cta, text: 작품 보기, locale: ko-KR }
    - { slot: empty-state, text: "선택한 조건에 맞는 작품이 없어요. 필터를 지우면 9월 소성분 전체가 보여요.", locale: ko-KR }
    - { slot: error, text: "예약을 저장하지 못했어요. 입력한 내용은 그대로 남아 있어요.", locale: ko-KR }
```

The title names the firing, the deck says what the shop does in the studio's own sentence voice, the action
names its outcome with no ending, and the empty and error lines speak as the studio does in operation. Each open
headline, subhead, and cta takes a second candidate in `explorations`.

The cancel confirmation and the notice signup are interface text written with the code, in the wording
shown above; the flows' `done.text` values (알림을 신청했어요, 알림을 껐어요) match what the interface
shows. If ja-JP and zh-Hant join `brief.locales`, each gets its own `key_copy` entries, written from the
same facts, and its own entry in `content.voice.locales` with its `prose`, `speaker`, and `by_role`.

## Check

After writing key copy, run `lapis-design plan check .lapis/plans/<task>.yaml`. It applies `copy.vague-cta`
to `cta` entries (a gate), `copy.name-swap` to `headline`, `subhead`, and `other` entries, and reads every
entry for `copy.meta-text`, `copy.placeholder-content`, and `copy.buzzwords`. `lapis-design slop lint`
with a render extract, which the `ultramarine` skill runs, reads the rendered copy: sentence endings per role
against the plan's voice, headlines that speak in the body's register, heading length and lines, an unanchored
"my", translated constructions, rhetorical habits, proof, and repeated notices. The P3 copy rules warn; walk each card
and keep or reject it with a reason. The `keep_when` cases of a rule, such as a legal register or a
contrast that carries scope, are decisions the check cannot see: record each `keep` with its id, its reason, and
the `evidence` the case lists; a case that lists `evidence: none` takes the reason alone.

Error, offline, and empty states are read from a behavior session. `behavior check` with the `states`
probe induces them from the stub and records whether each says what went wrong and offers a way forward;
the `forms` probe reads field errors and kept input; the `commits` probe compares a success or failure
claim with what happened and looks for a confirmation that names the object, or an undo. No check reads
whether Korean, Japanese, or Chinese wording is natural, whether an honorific level suits the reader, whether a
term is the right one, or whether a rewrite kept a possibility or an obligation; an ending count approves nothing.
Say which of those a proficient reader has confirmed, and which not.
