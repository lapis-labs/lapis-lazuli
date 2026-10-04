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
