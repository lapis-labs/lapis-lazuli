# Forms and recovery

## Sections

Read the section the form or recovery decision needs, by heading; the rest are other decisions.

- Operating conditions: recording a situation that changes the form in `brief.constraints`
- From the goal to the fields: which fields to ask, in what order and grouping
- Checking and messages: when to validate and how to word what the person sees
- Waiting, retrying, and not knowing: pending states, duplicate submits, offline and unknown outcomes
- Review and consent: the review step before a binding commit and how the commit is named
- Korean forms: name, phone, address, and similar field conventions for a Korean service
- The kiln shop: the worked reservation example
- Check: the behavior probes to run and the findings to read

This file backs the skill's **Flows**, **States**, **Commitments**, **Choices without pressure**, the
form bullet under **Interaction**, and the stub's `values`. The plan has no form field, so the
decisions land in existing ones: what a flow may demand in `flows[].requires`, open questions in
`claims.unresolved`, and the stub. Wording is the `lps-copy` skill's interface copy reference;
placement and look are the `lapis` layout step's. Examples continue the pottery shop: reserving one
piece, on a phone, in Korean.

## Operating conditions

For a consequential operating condition, record the supplied or observed situation and affected
task in `brief.constraints`, not a demographic preference. Name the visible symptom, a competing
cause, and what observation would reject the proposed change in `claims.proposed`.
Glare can require different treatment without proving dark mode is better; gloves require the
issued input/device, not a universal thumb zone. Preserve access floors and test safely on the
intended equipment. Simulated impairment is not lived-experience evidence.
Interruption, offline work, shared devices, and helpers expose state or policy questions:
do not invent autosave, queueing, retention, or delegated access. Keep operator, affected person,
current identity, and authority distinct; a helper relationship grants no account permission.
Continue independent work while the named owner resolves those questions.

For a misunderstood action, distinguish unnoticed control, misleading term, and wrong model of
ownership or state. Ask for a pre-action prediction, then compare it with the real result; one
failed click establishes no mental model. Repair the signifier, vocabulary, or behavior at its
actual owner. Teaching a changed model must preserve identifiers, routes, and permissions unless
separately authorized. Keep required and frequent expert controls visible; disclosure is for
optional detail, not a mechanical menu-item limit or a way to hide inherent task complexity.

## From the goal to the fields

Start from the goal, not the data model. For each field ask whether the goal fails without it, whether
it must be asked now, whether the product already knows it, and whether the person can supply it
accurately. Remove, defer, prefill, or explain it accordingly.

A compound field keeps a persistent question, value or picker trigger, and associated help/error.
Unit, reveal, clear, and attachment-retry controls are separate named targets with their own states.
Group labels identify the question; option labels identify answers. A checkbox row may toggle one
choice, but its "Read terms" link opens terms without toggling it. Do not enclose unrelated actions
in one input-shaped surface. A count belongs only where the product has a real limit.

- Ask only for what the goal needs. A step that demands an account, an optional consent, a permission, a
  share, an install, or a survey before the person can continue is `ux.forced-action`. Only an account
  can be declared, in `requires` with `requires_reason`; the rest must be skippable. An identity check
  or reauthentication in `requires` needs its reason too. Keep a guest path when the goal needs no
  account.
- One column, grouped by the person's task. Every field has a visible label that stays once it has a
  value; a placeholder may show an example, never the label or the only rule
  (`component.unlabeled-input`). Put format and limits in helper text before the field can fail.
- The real `type`, `autocomplete` token, and `inputmode`, and paste allowed everywhere, password and
  code fields included (`ux.inaccessible-auth`).
- Changing a select, radio, checkbox, or switch does not navigate, submit, open a dialog, or move focus
  before the person submits (`ux.unexpected-context-change`).
- Compare a single path with stages only when tasks, dependency, branching, external verification,
  or resuming change the work; never one field per step (`ux.excess-steps`, with `max_steps`).
  Name stages for tasks. If branching changes what remains, show the known stage and uncertainty,
  not an invented completion percentage. Keep entries on Back and warn before an earlier answer
  clears later ones. Preserve a short coherent form when splitting adds only navigation.

## Checking and messages

- Check after the person leaves a field, once the rule is stable (a finished email, not a half-typed
  one), or on submit. Never on load, never on an untouched field, never per keystroke
  (`ux.premature-validation`); a live aid such as characters remaining is the exception. Set
  `aria-invalid` only on a field that failed a check.
- Keep submit enabled and explain on submit; if it must stay disabled, say beside it what is still
  missing (`ux.disabled-submit-unexplained`).
- A field error says what is wrong, where, and how to fix it, in text beside the field, tied to it with
  `aria-describedby` or `aria-errormessage`. Color or an icon is never the only sign.
- After a failed submit show a summary linking each field, and move focus to it or to the first invalid
  field. One event gets one announcement owner: the focused summary or a live region, not both plus
  every inline message (`ux.input-error-unidentified`, `ux.status-not-announced`).
- Read a server answer by its cause. A 422 becomes messages on the fields it names. A 409 says what
  changed and opens a recovery path with entries kept: the piece was just reserved, so offer the others
  from this firing. A 401 or 403 is about access, not invalid input. A 5xx or a lost connection never
  says the input was wrong.

## Waiting, retrying, and not knowing

- A commit shows a pending state: the control keeps its name, a second activation is ignored, and the
  request carries an `Idempotency-Key`, so a repeat is the same order (`ux.duplicate-submit`).
- A confirmed failure says so, keeps every entry (a password or code may clear, with the reason beside
  it), and offers a retry that cannot duplicate (`ux.lost-input`).
- No answer is unknown, not failed. Say it is unconfirmed, name where to check (the reservation list),
  and offer a retry only after that check or with the same key (`ux.false-status`). Report only what
  the backend confirmed; "saved on this device" is true of storage, not page memory.
- A multi-step form, or one that promises a draft, keeps entries through reload, Back, and signing in
  again.
- A session or hold that can expire needs a timely warning and repeatable simple extensions, or a way
  to remove or substantially adjust its limit. `ux.timeout-without-warning` reads those alternatives,
  warning lead, and successful extensions; it does not establish that a deadline is essential.

## Review and consent

Before a binding step, show what is being agreed to, each part with a link back that keeps entries:
piece, date and time with the weekday, total, cancellation terms. Name the commit for its outcome.
Success says what happened and what comes next, somewhere that outlasts a toast: the reservation
number if the system made one, where to change it, until when. `ux.no-review-before-commit` reads
commits that show a price; a free booking gets the review anyway.

- Required terms and optional marketing are separate controls, none checked in advance, each naming its
  purpose and never bundled (`ux.preselected-option`, `ux.consent-steering`). Declining an optional one
  never blocks the form.
- A "select all" is a person's shortcut: it mirrors the boxes it covers, and every box works alone.

## Korean forms

Defaults for a Korean service; a reader of Korean settles what the audience expects.

- **Name:** one 이름 field, `autocomplete="name"`. No split into family and given name, no length cap, no
  Hangul-only rule: compound family names and Latin names exist. Ask for the legal name only when
  verification needs it.
- **Phone:** one `type="tel"` field. Accept 010-1234-5678 and 01012345678 alike, strip hyphens and spaces
  before checking, and show one form after the person leaves. Three boxes break autofill.
- **Address:** a 우편번호 찾기 button opens an address search; a result fills the 우편번호 and the
  road-name address, then focus moves to a separate 상세 주소 field. Offer direct entry when the search
  finds nothing. A search in a layer is a dialog (`ux.dialog-focus`).
- **Dates:** show the weekday with the date, 9월 26일(토), in choices and in the review. Set `lang="ko"`;
  store ISO values.
- **Required and optional:** mark every consent item [필수] or [선택]; elsewhere mark only the optional
  fields (선택) and set `required` on the rest.
- **Consent list:** [필수] 이용약관 동의, [필수] 개인정보 수집·이용 동의, [선택] 마케팅 정보 수신 동의,
  each channel (email, text message, push) its own box. 전체 동의 comes first as the shortcut and includes
  optional items too; each item has a 보기 that opens its full text in place or in a scrollable panel.
- **Identity verification (본인인증):** use it only when the goal needs verified identity, such as an age
  limit or a financial step. The verification provider's window returns the confirmed name and birth date;
  it is a separate method from phone-number verification, and banking or government steps may require a
  certificate (공동인증서) or a verification app instead. Declare `requires: [identity]` with a reason and
  give people without the supported device a path. Unless the law requires a resident registration number
  (주민등록번호), ask for a birth date (생년월일) instead; the steps that need the full number (government,
  banking, payment) usually hand it to a certificate or a verification app rather than a form field.
- **Birth date:** two forms are common. The resident-number style is YYMMDD with the gender digit in a
  separate box (YYMMDD-X); ask for it only where the service's own rules need that digit. The calendar
  style is YYYY-MM-DD, as one field that accepts 19950315 and 1995-03-15 alike, or year, month, and day
  dropdowns.
- **Phone-number verification (번호 인증):** a text-message code confirms only that the person can receive
  messages at that number, not their identity. A reservation needs a name and a working number, not
  identity verification by default. The code field takes `autocomplete="one-time-code"`,
  `inputmode="numeric"`, and paste, and shows a real expiry and a resend.
- **Simple authentication (간편인증):** a messenger, carrier, or bank app that the person approves on their
  phone. Providers offer it for both identity and phone-number verification; say which one the step needs,
  and offer it beside the text-message code rather than in place of it.
- **Typing:** validate and reformat Korean text after `compositionend` or when the person leaves the
  field, not while it composes (`navigation.md`, Korean input).

## The kiln shop

Reserving opens from 예약하기 on the piece page: 이름, 연락처, and for delivery the address fields, then
a review, then the commit; `reserve-piece` lists `requires: [address]`. If the piece is taken, the server
answers 409 and the sheet keeps the entries and links the other pieces. The stub needs a value for every
kind of field the page uses, plain `text` for 상세 주소 included; a missing kind turns `forms` coverage
`partial` and skips the invalid submit:

```yaml
values:
  v1: { kind: name, valid: 홍길동, invalid: '!', alternate: 김가마 }
  v2: { kind: phone, valid: 010-0000-0000, invalid: 010-12, alternate: 010-0000-0001 }
  v3: { kind: postal-code, valid: '00000', invalid: '1234', alternate: '00001' }
  v4: { kind: address, valid: 가나시 다라로 1, invalid: '', alternate: 가나시 다라로 2 }
  v5: { kind: text, valid: 101동 101호, invalid: '', alternate: 102동 102호 }
```

`invalid` must break a rule the page enforces, or the invalid submit has no error to judge. Failure
injection gives a 503, a lost connection, an applied but unanswered request (`hang`), a 403, and a
404. A 409 or 422 comes only from a fixture route whose literal `response` has that status, which no
probe presses: test those by hand and list them as not run. Add `accounts` and `auth` when a
multi-step or draft form should survive signing in again, and `outside` stand-ins for an address
search or identity service.

## Check

```text
lapis-design behavior check <url> --task <task> --plan .lapis/plans/<task>.yaml --stub .lapis/stub.yaml \
  --probe flows --probe forms --probe commits --probe states --probe time_limits \
  --probe choices --probe history --probe controls --probe dialogs
```

Without `flows`, `forms`, `commits`, and `time_limits` lose what comes from flow runs (repeated entry,
commit steps, limits met during a flow). The run writes `.lapis/behavior/<task>.narrow.json`, because
`--probe` narrows it; the full session at `<task>.json` is the release gate's.

| Probe | Records | Rules |
|---|---|---|
| `flows` | each plan flow to its `done`: steps, gates, a review before the commit | `ux.forced-action`, `ux.no-review-before-commit`, `ux.dead-end` |
| `forms` | labels, the stage of the first error, an invalid submit, entries kept or cleared after it and after a 503, paste, changed choices, a disabled submit | `component.unlabeled-input`, `ux.premature-validation`, `ux.input-error-unidentified`, `ux.lost-input`, `ux.disabled-submit-unexplained`, `ux.redundant-entry`, `ux.preselected-option`, `ux.consent-steering` |
| `commits` | rapid repeated activation, each injected outcome against what the page claims, retry, kept input | `ux.duplicate-submit`, `ux.false-status`, `ux.status-not-announced` |
| `states` | for each surface the page fills from a GET: empty, partial, loading, error, offline, timeout, forbidden, not found, success | `ux.missing-states`, `copy.error-without-recovery` |
| `time_limits` | idle time until a session, hold, or entry ends, and whether it warned | `ux.timeout-without-warning` |

For a consequential path, review material transitions rather than every possible combination.
Include an alternative entry, Back/exit, permission change, stale data, unknown outcome, and
return with preserved work; combine axes where their interaction changes the consequence.
For each manual gap, record synthetic fixture, role and starting state, actions, expected
observable result, actual result, and evidence location. Map findings to the existing flow or
transition description; introduce no project-wide ID or analytics convention.

Match evidence to the question. A cognitive walkthrough predicts whether the actor will seek,
notice, connect, and understand an action; it is not participant behavior. A moderated task gives
context, motive, safe data, and an outcome without teaching labels or a route; record assistance
separately from independent completion. Regression checks establish the defined contract,
not usability; analytics shows only instrumented states, not motive or causality. A protocol
is planned coverage until executed, never a participant finding or population rate.

What no check does:

- Form-purpose and explanation recognition is language-limited. An unrecognized form still has its
  fields, errors, and retained entries checked; a missing purpose is not proof that its task is absent.
- The flow driver fills inputs, accepts recognized required consent, and answers required radio groups.
  It leaves optional and bulk choices, switches, and recognized promotional requirements untouched;
  when that stops the flow, report the blocked path as not run rather than a completed form check.
- An announcement is text entering a live region, an alert appearing, or focus moving there; no screen
  reader output is checked. Address search and identity verification are never called, and failure
  injection runs only on the stub.
- A form's own error is not a data surface, so `states` does not read it. `plan check` checks flow
  pairs, `requires`, and reasons, and does not judge fields.
