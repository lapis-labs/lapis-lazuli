---
name: lps-ux
description: Designs flows, states, and navigation - sign-up, checkout, subscriptions, consent, cancellation, errors, empty and loading states, dialogs, notifications, forms, site structure and menus - so they work, recover, and never push people, then writes the stub that lets them be checked. Use for flow design, information architecture and navigation, form and error handling, dark-pattern reviews, and "what happens when this fails".
license: MIT AND CC-BY-4.0
---

# lps-ux

lps-ux designs what happens between screens: the flows people take, the states each part can be
in, and how the product recovers. It writes the plan's `flows`, the states each component needs,
and the stub (`.lapis/stub.yaml`) that `behavior check` drives.

## Order of authority

1. Requirements: keyboard and screen reader access, honest choices, recoverable errors, no lost
   input, reduced motion. The behavior rules in `shared/slop/rules.yaml` of class requirement are
   never traded.
2. The project's contract: `DESIGN.md` patterns and components.
3. Platform conventions: system back, dialogs, permission prompts, form behavior.
4. Named defaults (the cards).

## At the start

1. Read the plan's `brief`, `flows`, `content`, and `layout`, and `PRODUCT.md` for the real rules:
   prices, renewal terms, what an account is needed for, what can be undone.
2. List what a person comes to do (the goal), where they start, and how they know it is done.
3. When the surface has more than one destination, or the task adds, renames, or moves one, settle
   the structure before the flows: which destinations exist, what they are called, and how people
   move among them and back. For grouping and labels, the navigation model at each width, current
   location, Back and deep links, search with Korean input, and long collections, read
   `references/navigation.md`.
4. When a flow collects input or can fail partway - a form, sign-up, booking, checkout, a slow or
   unanswered request - read `references/forms-and-recovery.md` for the fields, when they are checked,
   messages, retry and unknown outcomes, consent inside a form, Korean form conventions, and the stub's
   values.
5. For consequential operating conditions, read `references/forms-and-recovery.md`.

## Flows - `flows`

Write one entry per flow the surface starts or finishes: the primary flow, and every flow that
signs up, pays, subscribes, consents, withdraws consent, unsubscribes, deletes an account, cancels,
or recovers.

- `goal` in the user's words, `start` and `done` as routes or the confirmation text.
- **Pairs.** Every flow that leaves names, in `pair`, the joining flow it reverses:
  cancel-subscription pairs with subscribe, withdraw-consent with grant-consent, delete-account with
  signup. The joining flow has no `pair`. Leaving takes no more effort than joining - the same
  channel, a similar number of steps, no call or chat required.
- **Requirements.** List what the flow needs in `requires` (account, sign-in, identity, payment,
  address, age, reauth) and give `requires_reason` for an account, identity, or reauthentication.
  Do not require what the goal does not need.
- `max_steps` when the flow should stay short; the behavior check counts steps against it.

## States

For every component and screen a flow reaches, design the states the task can reach: empty,
loading, partial, error, offline, success, and for controls default, hover, focus, active,
disabled, and busy. Each state says what happened and offers the next action.

- **Errors.** Tie each error to its field in text, announce it, keep what was typed, and name the
  fix. A request that may have succeeded is "unknown", with a way to check, never "failed".
- **Commitments.** Before a purchase or other binding step, show what is being agreed to and the
  total. Protect against double submission; a retry never creates a second order.
- **Destructive actions.** Name what is lost in the confirmation, or give a working undo.
- **Status messages.** A result that appears on screen (item added, saved, count changed) is also
  announced to assistive technology.
- **Returning.** Back and signing in again keep filters, position, and the destination.

## Choices without pressure

- Accept and decline carry the same visual weight and effort; a refusal is worded neutrally.
- Nothing optional, consenting, or costlier is preselected.
- The full price, fees, renewal, and cancellation are visible where the decision is made.
- A declined request does not return in the same visit.
- Countdowns, stock, and demand claims come only from facts the stub's `urgency` records.
- Permission prompts come after the user does something that needs them, never on load.

## Interaction

- Everything works from the keyboard in a logical order, focus is visible and never hidden
  behind sticky bars, and modal dialogs take focus, keep it inside only while open, return it when
  they close, and close with Escape.
- Gestures have a single-pointer or button alternative.
- Modals are for decisions that must interrupt; routine navigation and long tasks stay in the page.
- Forms validate on submit or after leaving a field, never while the person is still typing; a
  disabled submit says what is missing.
- Timeouts warn and offer more time before work is lost.
- Motion explains a change of state and has a reduced-motion branch.

For notification channels, permissions, and lifecycles, read `references/notifications-and-attention.md`.
For adoption/exit, AI-assisted work, moderation, or support handoffs, read `references/product-lifecycles.md`.

## Write the stub

`behavior check` needs `.lapis/stub.yaml` (`shared/behavior/stub.schema.yaml`) or an isolated
local backend. Write it with the flows, in this order: `version` and `clock`, `routes` for every
endpoint the UI calls, `collections` with edge cases (a long name, zero stock, an item that sells
out), `variants` with `empty` and `partial`, `values` with `valid`, `invalid`, and `alternate`
synthetic inputs (example.com addresses, fictional streets, a payment provider's published test
numbers), `accounts` and `auth` when a flow signs in, `outside` stand-ins for third-party calls, and
`urgency` for every countdown, stock, or demand claim on the page. Never real people, accounts, or
cards.

## Named defaults to walk

Walk the cards in `shared/slop/cards.yaml` whose cues concern flows and motion - `ambient-motion`,
`global-habit-values` for motion - and record keep or reject in `defaults`. Deceptive patterns are
not defaults: they are requirements and are never kept.

## Check

Run `lapis-design plan check .lapis/plans/<task>.yaml`; it checks flow pairs, requirements, and
reasons. The `ultramarine` skill runs `lapis-design behavior check` with the stub and reads the
session against the behavior rules. You designed the flows, so a separate critic judges them.

## Reporting

Tell the user each flow with its pair, the states designed per component, the navigation model and
the one it was chosen over, what each flow requires and why, and which checks can run now that the
stub exists.
