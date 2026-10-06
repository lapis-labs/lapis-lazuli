# System contracts

Use this file when adopting a supplied system, bootstrapping shared components, or changing their
public contract. `tokens.md` owns value graphs and conversion; `theming.md` owns modes. The plan's
existing `claims`, `sources`, and `proposed_design_changes` hold decisions and unresolved scope;
this reference introduces no inventory schema or additional approval mechanism.

## Reconcile the authorized source

Inventory the families declared by the supplied source inside the requested boundary, not the
primitives a similar public kit usually contains. For each family distinguish inspected/present,
inspected/absent, unread, and an authorized addition. Unread is not absent. Account for every
declared member, variant, and meaningful state before claiming the requested family is complete;
a representative slice proves fit, not full adoption.

Preserve exact supplied dimensions, metrics, colors, and names unless their owner approves a change.
Do not snap them to the nearest local scale. Expose a font or icon substitution with requested source,
replacement, reason, affected families, and review status. Reuse the existing project record; invent
no mark or component to make an unread area look finished.

## Adopt, extend, or build

Keep the working host system and supported theme seams first. Compare alternatives only for an
actual failure: implement the hardest affected task in the current stack, including the relevant
state, theme, locale, input, and density. Include license, shipped cost, maintenance, and reversal
cost when they decide fit. A button showcase cannot settle a data-heavy or overlay-heavy system.

- Adopt when supported behavior and tokens fit with bounded theming.
- Extend when a product-specific pattern is missing; preserve the underlying behavior contract.
- Build only the owned layer no suitable system supplies. Keep native or maintained primitives.

One styled vocabulary owns each product layer. A domain chart or native primitive may sit beneath
it without introducing a competing dialog, form, or state language. Unsupported internal selectors
are not a stable theming seam; pervasive overrides are evidence to reconsider the boundary.

A bootstrap is complete relative to its agreed consumers and artifacts, not a conventional catalog.
Keep a one-app system local. Promote a shared decision when repetition creates material cost,
non-obvious interaction/access behavior needs one owner, or themes must change coherently.
Product routing and business policy stay with the product; a one-off composition need not become a
foundational token. A package needs real consumers, a release owner, and a migration path.

## Component seams

Start with anatomy and the platform control. Separate the interaction engine, styled parts, and
local recipe; copied source assigns update responsibility to the local maintainer. Encapsulate
label/error associations, native form identity, keyboard/focus behavior, and required state; expose
only meaningful content and bounded variation. Independent axes need not become every possible
variant combination. Close a seam that repeatedly permits invalid combinations.

For a slotted or polymorphic wrapper, identify the node receiving the name, role, ID, handlers, and
focus ref; distinguish a measurement ref from the native input ref. Read the installed primitive's
handler order and cancellation contract. Map value, event, and ref deliberately rather than
spreading a form field object onto a composite root. Rich options need a localized plain-text
identity apart from their machine key and decoration.

Prove the seam with a real consumer: replace its trigger with the project's wrapper, operate by
keyboard, change the value, submit/reset the form, and focus a failed field. Verify the submitted
value, one intended transition, and returned focus. Responsive presentation changes preserve state
identity. Document what the component guarantees and what the consumer supplies; screenshots and
matching token names prove none of these behaviors.
