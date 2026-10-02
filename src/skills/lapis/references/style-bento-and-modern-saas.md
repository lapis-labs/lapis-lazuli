# Bento and modern software surfaces

## Read the request beneath the style word

| Decision | Plan field | What checks it |
| --- | --- | --- |
| Identify what the requested look promises about the content | `direction.read.style_frame`, `direction.read.style_name`, `direction.read.text`, `claims.declared` | The schema requires `style_name` for a named frame; the interpretation is not checked |

A request for bento may mean an overview of unlike things, not rounded containers. Modern or professional may mean dependable working states, a precise explanation, or a restrained voice. Record the requested words without turning them into a concept. Write the content assumption in the design read: what needs comparing, what needs explaining, and what the reader already knows.

A modular composition, a theme, and a working interface are separate decisions. None requires the others. These labels authorize no borrowed identity and supply no evidence about this particular subject.

## Let the content establish the logic

| Decision | Plan field | What checks it |
| --- | --- | --- |
| Decide which unlike items belong together and rank their importance | `layout.procedure.content_inventory`, `layout.procedure.priority`, `layout.procedure.relationships` | `layout.bento-filler` reads rendered cells for content; `layout.equal-siblings` compares rendered sibling similarity with plan priority |

A mosaic is useful when distinct units need a shared view: an image explains something different from a list, and a diagram answers something different from a quotation. Inventory those units before selecting spans. Describe why they belong together and which evidence deserves attention. A rectangular outline is not a reason to add another item. Alignment can express membership without surrounding every item with a panel.

For a marine survey's overview, a coastline map, habitat photograph, and sampling record may need simultaneous inspection. The map can carry the widest field because locations connect the other records. A costume-rental service might instead place garment views beside availability and care conditions. Its comparison may need repeated rows rather than a mosaic. Put the relationship, not the desired silhouette, in the plan.

Professional software has another logic: repeated work needs stable locations for actions, meaningful state distinctions, and enough context to understand consequences. A compact queue and a broad visual overview need not share a composition.

## Fit the language to the surface

| Decision | Plan field | What checks it |
| --- | --- | --- |
| Separate explanation from repeated work and set density accordingly | `direction.read.surface_mode`, `brief.product_frame`, `direction.dials.density`, `layout.procedure.density_and_checks` | The critic's vision check compares appearance with priority; task suitability is not checked by a rule |

A persuade surface can select evidence and leave room for an unfamiliar reader's questions. An operate surface must keep common actions, current state, and exceptions available. A read surface organizes sustained attention. Set density from those jobs, not from the software category.

A rehearsal-planning tool's public page might explain the relationship between cast availability and the rehearsal order. Its working schedule needs participants, conflicts, and editable times together. A laboratory instrument service might lead with a real maintenance record, while its working queue keeps fault details beside assignment controls. Neither needs decorative command imagery. Preserve task controls when the public page has an expressive opening; the visitor's first explanation is not the operator's daily workspace.

## Notice where the style becomes a default

| Decision | Plan field | What checks it |
| --- | --- | --- |
| Keep or reject a detected convention with an actual basis | `defaults[].id`, `defaults[].decision`, `defaults[].basis`, `defaults[].reason` | The rule for the card reads its own inputs; the critic tests whether the retained choice belongs to the subject |

Use the cards as questions, not as a new preset. Store decisions against rule IDs rather than card names. A retained choice needs a brief, contract, or requirement that explains its role; a rejection needs a replacement that reaches the implementation.

| Card to examine | Rule and what it reads |
| --- | --- |
| `boxed-everything` | `layout.card-everything` reads rendered content enclosed by card boundaries; `layout.bento-filler` reads cells lacking text, meaningful media, or controls |
| `template-page` | `layout.template-section-sequence` compares planned section archetypes and derived rendered section order with template sequences |
| `starter-surface` | `component.library-default-theme` compares rendered type, corners, spacing, color roles, and states with a supplied starter-theme corpus |
| `dark-luminous` | `color.dark-luminous` combines package member findings at the same layer |
| `stand-in-imagery` | `component.fake-app-window` looks for constructed window dots or textless data bars in rendered boxes |
| `one-neutral-voice` | `type.single-neutral-sans` counts planned and rendered families, not the usefulness of their role distinctions |

`layout.typical-composition` and `component.library-default-theme` are warnings, not creation gates. A dark background alone establishes neither professionalism nor a package finding.

## Make decisions this subject can own

Record what changes visibly and why the content requires it. Treat the following as alternatives to resolve, not a bundle to adopt.

| Decision | Plan field | What checks it |
| --- | --- | --- |
| Make a genuine product record the signature: a theatre tool's conflict timeline or a repair service's annotated fault sequence | `world_materials`, `layout.signature` | `component.fake-app-window` detects constructed stand-ins; authenticity and the material's rendered role need the critic |
| Give each meaningful item space according to its relation and importance, allowing equal treatment for true peers | `layout.procedure.relationships`, `layout.procedure.priority` | `layout.bento-filler` checks content presence; `layout.equal-siblings` reads sibling similarity and matches their text against ranked plan entries |
| Organize sections around evaluation questions: whether a specimen record is traceable, or whether a garment is available for the intended event | `layout.sections[].answers`, `layout.sections[].archetype` | `layout.template-section-sequence` reads archetype order, not whether the answers are persuasive |
| Specify the narrow reading order and which relationships become stacked or disclosed | `layout.procedure.responsive`, `layout.procedure.reading_order` | `layout.shrunk-desktop` compares matched boxes across compact and wide captures for retained scaled columns; it does not judge the chosen reading order |
| Choose brightness from the viewing environment and required theme coverage, then resolve foreground and status roles separately | `tokens.color.decision.environment`, `tokens.color.themes`, `tokens.color.roles` | `color.inverted-dark-theme` compares matched light and dark colors for literal inversion; the critic judges whether the environment decision fits |
| Distinguish permanent content, temporary overlays, and controls through appropriate surface levels and corners | `tokens.surface.elevation`, `tokens.surface.borders`, `tokens.shape.radius.by_role` | `surface.uniform-large-radius` reads the share of rendered containers with large corners, not the quality of the surface hierarchy |

An unavailable product record belongs in `claims.unresolved`; a proposed explanatory drawing belongs in `claims.proposed`. Do not present either as observed product evidence. A clearly identified schematic can explain the intended relationship without pretending the software has shipped.

## Combine with bounded ownership

| Decision | Plan field | What checks it |
| --- | --- | --- |
| State which influence owns which variable or surface | `direction.read.style_name`, `direction.read.text` | The critic's package-drift check notices substitution by another named package; ownership itself is not checked |

A working tool may borrow editorial pacing for case studies while keeping task navigation and state language stable. An exhibition page may use a mosaic for object comparison without applying panels to every paragraph. Name the boundary in the read. If both influences claim typography, palette, corners, and composition everywhere, resolve the conflict before implementation.

## Know what the checks leave open

| Decision | Plan field | What checks it |
| --- | --- | --- |
| Separate automatic findings from decisions requiring rendered judgement | `claims.unresolved` | The critic reviews open items; recording an uncertainty does not verify it |

| Check family | Reads | Does not establish |
| --- | --- | --- |
| Content and sibling checks | Cell contents, sibling geometry, matched plan priorities | Whether the evidence deserves its allotted attention |
| Theme and surface checks | Paired theme colors and container corners | Whether darkness or a particular material suits use |
| Typicality warnings | Comparable captured features and a supplied corpus | Originality outside that corpus; without it the comparison is skipped |
| Critic | Screenshots, plan decisions, material traces, and open findings | A verified outcome for anything not visible in the supplied evidence |

For layout reasoning beyond this style, read `layout.md`; for page and screen roles, read `archetypes.md`. A passing check is a bounded observation, not an endorsement of the style.
