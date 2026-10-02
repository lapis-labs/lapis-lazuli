# Form levers

This file backs plan step 4. The plan holds `direction.concept`, `direction.levers`, and `layout.signature`; the sections below also reach the fields where a lever lands. Each section names a decision, the plan field that records it, and what checks it, or says that nothing does. Examples come from invented subjects: a ferry timetable, a seed library, and a lighthouse museum.

## Write each lever as one sentence

| Decision | Plan field | What checks it |
| --- | --- | --- |
| Which lever, what visibly changes, and the world material it comes from | `direction.levers[]` | `layout.unanchored-lever` reads whether each sentence shares a word with an entry of `world_materials` or with `layout.signature`; the critic's counterfactual test judges the rest |

The levers are scale, density, rhythm, tension, material, type as form, and motif. A bare name or a style adjective shows a reader nothing and comes from nothing in the subject. With the ferry materials `[sailing timetable, tide gauge, deck plan, lifejacket tag]` and the seed-library materials `[drawer label, seed packet, sowing calendar, germination notes]`:

- scale: one departure time, set in the tide gauge's tall numerals, is the largest thing in the opening
- density: the sailing timetable keeps ledger density while the deck plan beside it stays open
- rhythm: one drawer-label row for each variety, with the sowing calendar as the only interruption

The comparison is by word, so a lever and a material written in different languages share none; write the sentence in the materials' language. The check does not read whether a material is concrete, a change visible, or a lever good. A plan whose form is fixed by contract or brief records a keep for this rule in `defaults`, with the basis. A plan whose surface modes are operate alone may write no lever.

## Start from a tension, write a concept

| Decision | Plan field | What checks it |
| --- | --- | --- |
| The live tension in the subject, and the relation that answers it | `direction.concept` | The critic's counterfactual test after rendering; not checked at plan time |

A concept is a relation that changes order, emphasis, or labels, not a mood or a theme laid over finished styling. Start from what the brief and supplied material already hold: the action the surface must enable, what the reader knows and what stays uncertain, the real sequences, exceptions, and states. State the tension plainly. "The timetable is dense, yet every sailing looks equally urgent" is a tension; "make it feel nautical" is not.

Choose a method for the blocked question: reframe the wrong unit of work; map an unclear relation;
temporarily invert a convention hiding alternatives; test a disposable brief-linked constraint
when too many moves compete. Without obvious visual material, transfer an adjacent operation
such as sorting or repairing, not its props. Stop when it changes order, emphasis, or labels.
State the mismatch limiting the analogy in `claims.proposed`.

A concept earns its place when it changes a consequential choice. Write two that differ in what governs order or emphasis, not in palette, choose one, and record the loser and the reason in `explorations` (decision `direction`); `plan.uncompared-decision` reads that both are recorded, not whether the concept is good. Invent no history to make a concept sound deep; a guess about the subject goes in `claims.proposed`.

## Compare an open direction

To tune a suspected cause, hold content, viewport, state, and surrounding choices fixed; change
the smallest coherent set, such as size with leading. To explore a governing relation, let type,
grid, imagery, and pacing move together while brief and protected contracts stay fixed. Name the
relation and expected cost; tune a promising whole afterward. Neither comparison proves trust,
comprehension, or preference without audience evidence.

| Open decision | Smallest useful specimen |
|---|---|
| content relation | annotated sequence or content map |
| type idea | real titles, paragraph, and difficult label |
| palette/state relation | existing components in real states |
| image direction | authorized crop and sequence study |
| density | one populated ordinary region |
| motion continuity | minimal interaction with its reduced branch |
| direction beyond the opening | opening, ordinary content, and one utility state |

State what observation would reject the direction before making the specimen. Use real material
or label its limit. A polished hero alone settles no system.

Read each proposition, then test obligations. Reject premises requiring false evidence,
inaccessible behavior, or unowned capability. Compare viable studies against the brief, ordinary
content, and operating cost, not polish or novelty. Choose one governing relation; combine only
what strengthens it. Keep candidates, comparison, chosen relation, and runner-up reason in
`explorations`; optional keep/rework/discard/combine observations belong in `claims.proposed`.

## Allocate the levers

| Decision | Plan field | What checks it |
| --- | --- | --- |
| Which sections carry a lever, how far it spreads, what is pushed, what stays steady | `direction.levers`, `direction.dials.variance`, `direction.read.surface_mode` | `layout.unanchored-lever` reads the sentence's words; the critic's trace of world materials looks for each material in the render. What stays conventional has no field: say it inside the sentence; not checked |

Four decisions are independent. Placement: where interpretation is affordable because the next action stays visible. Material: what changes, such as a crop, a scale relation, or an interval, not navigation, sound, and cursor together. Coverage: one place, a recurring relation, or the whole grammar. Intensity: which visible property is pushed and what holds still. A quiet, recurring change can be an entire identity; a strong local one need not spread to every control. The variance dial opens a conversation; it is not a budget.

Allocation follows the surface mode. Persuade and experience surfaces can carry levers in openings and story sections. Operate surfaces keep levers off working controls, because repeated work needs stable positions and state distinctions. A page that persuades and operates splits: the ferry's opening carries the scale lever, its departure rows carry none, and the sentence says so. A request for bolder may mean stronger hierarchy, not more elements. Name the change and what stays fixed.

## Scale and space

| Decision | Plan field | What checks it |
| --- | --- | --- |
| The largest element and what it is set against | `tokens.type.scale`, `layout.procedure.priority` | `type.flat-hierarchy`: the plan check reads the scale ratio, the render check whether headings differ from body in size, weight, or contrast. `type.oversized-display`: display text's share of the first viewport and its lines on a narrow screen |

Scale is a relation, not a size. A tiny complete object in a wide field beside one readable sentence suggests exposure; under a slightly larger headline it is ordinary hierarchy. Name both sides, taking the larger from the priority list. Area alone does not decide force; contrast, isolation, and a specific subject carry weight too.

Empty space must read as finished, not loading: identity, a visible next step, and promised content stay reachable. Time-critical content never sits under a large slogan; the next sailing stays on the first screen. The checks cannot tell intended emptiness from missing content; the critic's vision check looks. The quiet version removes labels competing with the strongest element.

## Density

| Decision | Plan field | What checks it |
| --- | --- | --- |
| Where the page is dense and where it is open, by task | `direction.dials.density`, `layout.procedure.density_and_checks` | `layout.card-everything`: how much of the content area sits inside card-like boxes. `layout.monotonous-spacing`: whether gaps between sections exceed gaps inside groups. The rest is the critic's |

Density comes from how much is visible at once, how strongly items group, row rhythm, layers of annotation, and the step from overview to detail. Smaller text is the weakest of these. Dense can be the direction: seed varieties in compact aligned rows are legible and have a beat, and open cards would remove the reason for the index.

Match density to the task: a reader new to the categories needs explanation beside the data; an expert hunting one variety needs compactness and stable positions. Decide against real content with long names, and record it in `density_and_checks`. A dense surface still needs group boundaries stronger than item boundaries and a selected state that does not rest on color alone.

## Rhythm and order

| Decision | Plan field | What checks it |
| --- | --- | --- |
| What returns and what changes across sections | `layout.sections`, `tokens.space` | `layout.template-section-sequence`: the plan check compares the order of the archetype names the plan states with common landing sequences, the render check the section kinds on the page. `layout.zigzag`: media and text rows alternating sides in succession |

`archetypes.md` (Rhythm and variation) ties rhythm to changes in what the reader needs; this section covers what a lever sentence must decide. A still page has time: order can run from whole to detail and back, dense blocks can alternate with open ones, a caption format can return over a changed crop. Variation registers only against recurrence; when every unit differs, the page has events and no rhythm.

Write what is stable (a question, a caption position, an interval), what varies, and when repetition should stop. No field holds these, so they go in the lever sentence and are not checked.

Decide who controls order: an authored sequence, visitor-chosen comparison, a documented external
condition, or a static field with several entry paths. Each changes adjacency, recurrence, and
return. Whole/detail order can carry time without motion. Do not invent a triumph narrative for
an unresolved collection or add sensing/live data for temporal interest. Use only existing
capabilities and provenance; put order in `layout.sections` and return in the lever sentence.

## Tension and asymmetry

| Decision | Plan field | What checks it |
| --- | --- | --- |
| The axis, the anchor, and where edges, crops, and overlaps occur | `layout.procedure.grid`, `layout.procedure.relationships` | `layout.symmetry-excess`: how much content centers on one vertical axis. `layout.equal-siblings`: siblings the plan ranks differently that look alike. `layout.occluded-text`, a requirement: anything painted above that covers text |

Balance is a perceived relation, neither mirror symmetry nor a computed center of mass. Weight rises with contrast, isolation, edge position, and a specific subject, and falls with clustering; one small isolated sailing number can counter a large pale photograph. Weight also follows meaning: a price, warning, or selected state keeps its prominence whatever a composition diagram prefers. Choose an axis on purpose: a baseline, a strong edge, a corner anchor, or the center. If every alignment is broken nothing reads; if all share one axis, rank cannot show.

An implied continuation that collides with content or looks clipped is breakage. Crop only as far as subject and task survive. Overlap joins and ranks, but never over text. Write the axis and anchor in `grid`, the unequal peers in `relationships`.

## Material and texture

| Decision | Plan field | What checks it |
| --- | --- | --- |
| Each treatment, the job it does, and where it applies | `tokens.surface.treatments[]` (`name`, `job`, `where`), `tokens.shape.rule` | `surface.decorative-grid-texture`: background patterns of grid kinds. `surface.glass-everywhere`: backdrop blur in source and how many panels use it. The `rights.*` rules read the asset ledger's provenance, license, and use for each shipped asset |

"Add texture" is not a decision. Name what varies: grain scale, direction, density, contrast against the ground, edge character, depth cue, and whether it is local or global. Grain that suits a large image turns to noise at small size, so judge it at the rendered size.

Prefer a trace from the subject to an overlay: a scanned log sheet, a measured mark, a real tool edge. Say whether each trace is documented, commissioned, or purely graphic, and imply no age, wear, or provenance the material lacks. Keep documentary photographs untreated and text clear of texture. Test by removing it: if nothing specific remains, the content never was specific. `job` is where the plan says what a treatment tells the reader; one that only sets atmosphere can say so.

## Type as form

| Decision | Plan field | What checks it |
| --- | --- | --- |
| Whether the form lives in the glyph, the word, the line or block, or the sequence | `tokens.type.roles` (the display role) | `type.oversized-display`: display text only. `type.caps-prose`: long runs of capital letters in any text. `type.costume-monospace`: in the plan, a monospace face on a display, heading, body, or ui role (it needs the lazuli database); in the render, monospace text outside code and data |

Choosing faces is in `type.md` (Display and expressive type). A heading is not type as form because it is larger; that is the scale lever. Form begins when the shape of the word, the proportion of the block, or the order of lines changes. Decide the level: a glyph (a documented alternate cut), a word (a short title against a long one), a block (measure, rag, width contrast between neighbors), or a sequence (a phrase returning in a changed context).

Test with the real text in every locale: shortest and longest titles, numerals, names. A direction built on one short Latin word may vanish in Hangul. Never split a label that carries a price, status, or action, and keep a complete text route for any treatment that breaks words.

Hypothetical comparison: a repair journal aligns its complete title to process-photo edges.
A stronger version splits a short display word around a documented joint, keeping the full name
and meaningful order. A quiet version carries modest title-width rhythm into rules and captions.
Compare that relation on this subject's material in `explorations`, not as a page template.
Reject missing essential letters, an unreadable translation, or navigation competing at that scale.

## Motif

| Decision | Plan field | What checks it |
| --- | --- | --- |
| What stays fixed in the recurring element and what may change, tied to the signature | `layout.signature`, `direction.levers` | `layout.missing-signature`: the plan check reads only that a signature is written; the render check looks for an element the page marks as the signature and counts its words in page text as weaker evidence. The critic traces the signature |

A motif is recurrence with memory: it registers because something returns, changed. Its variables are the unit (a shape, phrase, crop, interval, or label format), how often it returns, where it sits, its scale, how it transforms, and what interrupts it. Fix the invariant and the freedom in the sentence: a museum's beam-log row, time left and bearing right, recurs on every exhibit; its width may vary; it never marks a selected item. No count is right.

A motif must not read as state: a split field that also looks selected misleads. From a metaphor take the relation (the beam's turn, one interval after the next), leave the costume (brass, lens glass), and say what the borrowed relation falsely implies. The motif is how the signature recurs. Mark the signature element as `layout.md` describes.

## Response as a lever

| Decision | Plan field | What checks it |
| --- | --- | --- |
| What an action changes and how the visitor sees it (experience surfaces only) | `tokens.motion.principles` | The behavior check feeds `motion.reduced-motion-missing` (motion without a reduced-motion branch), `ux.gesture-only` (actions that work only through a drag or multi-point gesture), and `ux.scroll-hijack` (the page taking over scrolling) |

Response is a lever only when an action changes something a visitor can perceive through a relation they can learn; a trail that follows the cursor and changes nothing is atmosphere, so call it that. Write in `principles` what the visitor can do, what the work changes, and what it does not do. Keep trials reversible with a visible stop. Timing and interruption are in `motion.md`.

## Open meaning, fixed consequences

| Decision | Plan field | What checks it |
| --- | --- | --- |
| What no lever may touch: price, state, promise, destination, recovery | `brief.constraints`, `brief.locales` | The requirement rules `layout.occluded-text`, `color.text-contrast`, and `layout.compact-overflow` read the render. How a symbol reads in each locale is not checked |

Form may leave interpretation open and consequences never. A repeated mark can stay ambiguous between mourning and celebration; whether a sailing is cancelled, whether a value is missing or zero, and whether an action saves or deletes must be plain. Write what the levers must not touch in `constraints`. Assume no symbol has a universal reading: a color, animal, or gesture can shift meaning by locale, so list the locales and ask who recognizes the mark. An icon asked to carry an unlabeled action is a control, not decoration.

## What the checks read

| Check | Reads | Does not read |
| --- | --- | --- |
| `layout.unanchored-lever` | shared words with materials or signature | whether a material is concrete or a lever good |
| `type.flat-hierarchy`, `type.oversized-display` | heading against body; display text's share of the first screen | whether the scale suits the content |
| `layout.card-everything`, `layout.monotonous-spacing` | share of content in cards; section against group gaps | whether density suits the task |
| `layout.template-section-sequence`, `layout.zigzag` | order of section kinds; alternating media and text rows | whether the order follows the reader's questions |
| `layout.symmetry-excess`, `layout.equal-siblings` | centering on one axis; look-alike siblings the plan ranks differently | whether tension is intended |
| `surface.decorative-grid-texture`, `surface.glass-everywhere` | grid-like background patterns; backdrop blur on panels | whether a treatment has a job |
| `type.caps-prose`, `type.costume-monospace` | runs of capital letters; monospace outside code and data | whether a type treatment fits its word |
| `layout.missing-signature` | a written signature; a marked element | whether it carries the page |
| `motion.reduced-motion-missing`, `ux.gesture-only`, `ux.scroll-hijack` | motion without a branch; gesture-only actions; taken-over scrolling | whether a response is meaningful |

A passing check is a bounded observation, not a verdict on the lever. Intended emptiness, lever quality, and meaning in each locale are judged after rendering, by the critic or the user.
