# Platform contracts

Use this file when a requested surface crosses platform boundaries. Keep platform guidance,
product implementation choices, and behavior verified on the installed target separate. A shared
API name or a screenshot proves no platform parity. `implementation.md` owns stack preservation;
`email.md` owns delivered messages and host-controlled surfaces.

## Share meaning, adapt behavior

Share domain rules, content intent, semantic roles, and component outcomes where they remain true.
Choose outcome and data parity before visual parity. If a target lacks a capability, expose the real
difference rather than an inert control. Resolve each behavior-heavy seam to its maintained target
owner: navigation, permissions, files, input, accessibility, lifecycle, and system services.

Verify one consequential task per supported target through entry, completion, interruption, and
return. Include actual available window space, enlarged localized text, relevant input and assistive
technology, and system preferences. A framework's support list is not evidence for a dependency's
feature depth, spoken announcements, or background behavior. Capability does not authorize access.

## Target-specific seams

| Target | Preserve or adapt | Proof that matters |
|---|---|---|
| Browser | Resource links retain URLs, history, deep links, refresh and open/copy-link behavior; forms retain submission, autofill and input semantics | Direct route load, Back/forward, keyboard submission, delayed scripts and actual focus order; do not patch DOM order with positive tabindex |
| Android | Maintained navigation and system Back; role-matched foregrounds, scalable text, optional dynamic color with a branded fallback | Resize/fold while a destination is open; retained selection and Back stack; light/dark and actual dynamic palettes, not fixed device labels |
| Apple mobile | System navigation/presentation, semantic text scaling, safe areas, supported symbol variants | Large text reflows without shrinking; dismissal preserves drafts; columns collapse without losing destination or focus. Do not project mobile scaling APIs onto desktop |
| Desktop | Current window rather than monitor size; menus and discoverable commands; close window, close document, sign out and quit remain distinct | Resize, reopen, multi-window state, unsaved/sync/conflict handling; actual platform and keyboard-layout shortcuts; file operations with their real permissions |

Prefer maintained controls for behavior-heavy work. Custom chrome makes the product responsible
for platform focus, window dragging/buttons, scaling, system integration and access behavior.
A command palette accelerates known commands; it does not replace a discoverable task route.
Hover and gestures reinforce an operable alternative, never supply the sole action.

System materials belong to the layer and platform that own their behavior. A web blur is not a
native material; native control/navigation materials do not justify translucent content cards.
Check the real changing backdrop and reduced-transparency/contrast settings, not one preview.

## Guidelines

A platform's design guideline has two layers, and the plan treats them differently.

- **Behavior** is what the guideline asks a screen or flow to do: target sizes, focus, text scale and reflow, safe areas, dialogs,
  navigation and Back, input. It is always followed. Each checklist item is a requirement row (`G:<guideline>/<item>`) in the
  requirement record that the critic judges, and an item with a mechanical check also has findings that name it.
- **Visual** is the guideline's look: color, type, shape, motion. The owner chooses, per guideline, `follow` (build in its look),
  `consult` (read it, depart where this design has a reason; the default), or `none` (leave its look aside). It is asked in the
  direction conversation, one plain-words item per guideline, and the plan's `brief.guidelines[].visual` carries the answer.
  WCAG 2.2 has no visual layer and is never asked.

The checklists, each in our own words with the source section and its URL, the day it was read, the route it was read by, and a
licence line where the source asks for one:

| Guideline | Id | Covers | Checklist |
|---|---|---|---|
| WCAG 2.2 | `wcag-2.2` | web | [wcag-2.2.yaml](../shared/guidelines/wcag-2.2.yaml) |
| Material 3 | `material-3` | Android, web | [material-3.yaml](../shared/guidelines/material-3.yaml) |
| Fluent 2 and Windows apps | `fluent-2` | Windows desktop, web | [fluent-2.yaml](../shared/guidelines/fluent-2.yaml) |
| KRDS | `krds` | Korean government web and mobile web | [krds.yaml](../shared/guidelines/krds.yaml) |
| Apple HIG | `apple-hig` | iOS | [apple-hig.yaml](../shared/guidelines/apple-hig.yaml); it names the 2026 sections its index does not hold, so it is not the HIG's current state |
| Toss TDS, Daangn SEED | `toss-tds`, `daangn-seed` | consult only | [toss-tds.yaml](../shared/guidelines/toss-tds.yaml), [daangn-seed.yaml](../shared/guidelines/daangn-seed.yaml): links, no checklist, because their documents are one product's and the TDS kit license limits reuse |

The shape of a file is [guideline.schema.yaml](../shared/guidelines/guideline.schema.yaml); an `other` guideline needs a name and a
URL and has no checklist.

**Choosing.** `plan check` suggests from the brief: ios apple-hig, android material-3, web wcag-2.2 always, desktop on Windows
fluent-2 (it asks which system when the brief does not say), a Korean public service krds. Add what the owner names, as
`basis: declared` with their row; never drop a default silently, say why it does not apply. Cover only the platforms the entry
is for: an Android item never becomes a row of a web-only plan.

**Routes.** Record how each guideline's documents were read in `route` (`context7` with its library id, `official-docs` with a URL,
`repo`, or `owner-saved`). The file's `route.used` is the route it was written from and `route.alternative` the second route for
when the first is not available: the official pages for WCAG, Material 3, KRDS, and Fluent 2. Apple's HIG is read through the
index the file names, or by the owner in an ordinary browser, who writes their own checklist and section links; no program fetches
Apple's pages, and no saved Apple page goes to a model. A section that a file lists under `not_covered` has not been read, so
say so rather than guess it.

**Units.** A threshold stays in the guideline's own unit: Apple points, Android dp, Windows epx, CSS px. For a web prototype the
checks map each one 1:1 to CSS px (`../shared/guidelines/units.yaml` gives the basis; a typographic point is not an Apple
point), and a finding states the factor it used. That mapping says nothing about a native build, which gets the platform's own
units and no render check.

**What is measured.** Target size against the guideline's own minimum, reflow at 320 CSS px, focus indicator and focus not
obscured, and WCAG's 24 px target minimum already have checks; their findings name the item. Text at 200% has no capture in the
render matrix and stays with the critic, as does everything marked `judge`, and the safe area, which needs a host that gives
insets. A native build gets static checks only.
