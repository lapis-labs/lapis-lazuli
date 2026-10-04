# System governance

Use this file for a shared component or token migration. It does not authorize dependency upgrades,
contract edits, or publishing; the skill's existing approval boundaries still hold. Use the project's
current owners, change records, and release process rather than creating a parallel bureaucracy.

## Classify by consumer effect

Public contracts include supported imports, token names/types/aliases/units, modes, slots, keyboard
and focus behavior, form semantics, density, wrapping, themes, and runtime support—not only props.
A compiled change can still break a consumer. Describe the changed promise, affected consumers,
editable authority, generated outputs, owner, and rollback limits before classifying the release.
Keep design generations, package versions, and dated migrations distinct; equal numbers do not
prove compatibility. A compatibility record distinguishes supported, unsupported, and unverified
combinations and names the consumer exercise supporting each tested boundary.

## Choose migration evidence separately from the mechanism

| Change | Mechanism | Evidence needed |
|---|---|---|
| Exact rename | Deterministic edit | Complete caller inventory and reviewed mapping |
| One old value maps to several roles | Flag candidate uses, classify each by meaning | Actual theme/state pairs and consumer intent |
| Component anatomy or focus changes | Guided consumer migration | Task, keyboard, dismissal, focus return, and relevant assistive technology |
| Type metrics, density, or palette changes | Regenerate from the authority | Wrapping, locale, contrast, layout, and matched-state visual review |
| Runtime support or coordinated packages | Version/environment change | Tested combination and approved support boundary |

A successful transform establishes changed syntax, not preserved semantics or behavior. Keep
warnings as owned review work. Prove the hardest affected consumer first, repair the mapping from
observed failures, then finish every authorized family and caller. Remove obsolete styles, wrappers,
aliases, and documentation after consumer cutover; temporary internal adapters need a named owner
and removal boundary, never an indefinite second public API.

## Make the change discoverable

Documentation answers when to use the component, its neighboring alternative, supported states,
content/localization limits, guarantees versus caller duties, stable seams, and migration. Specimens
use the actual supported API and consequential states, not only a default screenshot. An example's
label is explanatory documentation, not product copy and not a reason to wrap everything in cards.

A material change record names what changed, why, who is affected, consumer actions, verification,
known limits, and rollback owner. If an existing supported release requires a deprecation window,
state the real replacement or removal, reason, detection route, before/after mapping, approved
window, and owner; invent no date or urgency. Do not introduce a shim just to imitate this model.
Exceptions name the failed shared use case, scope, evidence, and owner; recurring exceptions may
show a wrong system boundary. Artifact generation and a documentation claim of “tested” are not
consumer evidence unless the exercised release, task, conditions, and observed result are named.

## Decisions and handoff

Separate requirements, reproduced defects, evidence gaps, goal tradeoffs, direction preferences,
implementation risks and new scope before acting on feedback. Owners resolve tradeoffs; silence
is not consensus and an author's intention is not runtime evidence. Keep the approved direction
and protected consumer contracts visible while repairing a real failure.

Use an existing decision record only when rediscovery or cross-consumer ambiguity has material
cost. Name the question, selected relation and evidence, rejected alternative, affected scope,
owner, reversal limit and condition for revisiting. Supersede a changed decision rather than
rewriting its history. Do not create a committee, new ledger or remote destination for a local fix.

A handoff retains the task, current authoritative state, confirmed work and attempted actions,
protected decisions, consequential unknowns and next owner. State the observed engineering
constraint and its effect before proposing a substitution. A screenshot with redlines cannot
specify behavior; acceptance names the actual task/state/input and evidence still required.
