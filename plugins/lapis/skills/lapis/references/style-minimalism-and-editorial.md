# Minimalism and editorial surfaces

## Interpret the requested restraint

| Decision | Plan field | What checks it |
| --- | --- | --- |
| Separate a request for task clarity, reading structure, or evidence of care | `direction.read.style_frame`, `direction.read.style_name`, `direction.read.text`, `claims.declared` | The schema requires `style_name` when the frame is named; the interpretation is not checked |

Minimal and clean can ask for an obvious next action, fewer competing signals, or a coherent reading path. Editorial can ask for authorship, a paced account, or images explained by captions. Preserve the user's words in the declared claims and specify which meaning the content supports. None automatically chooses a pale field, a serif, or empty margins.

Premium is not a structural instruction. Translate the aspiration into product evidence and proposed decisions, excluding unsupported promises from known claims.

## Establish the content logic

| Decision | Plan field | What checks it |
| --- | --- | --- |
| Rank information before reducing emphasis, and identify the unit being published | `layout.procedure.content_inventory`, `layout.procedure.priority`, `layout.procedure.relationships`, `layout.procedure.grid` | `type.flat-hierarchy` reads type scale and rendered heading/body distinction; the critic judges reading relationships |

Minimalism makes competition deliberate. Each region needs a recognizable priority, but secondary information must remain available when the task depends on it. Removing a surface boundary is different from removing a status, instruction, or way back. Record which items belong together before deciding which visual cues can disappear.

Editorial composition begins with a publication unit: a report, interview, collection entry, or documented process. Establish the relationship among title, explanatory opening, sustained text, images, and attribution. Decide where a side note belongs in the reading path. A display headline cannot supply the missing account beneath it.

A geological field report may place a rock photograph beside its location and a caption explaining the visible fracture. The reading column carries the interpretation; an annotation rail carries supporting observations. A musical instrument workshop may instead publish a repair account ordered around diagnosis and intervention, with close views at the point each detail matters. The relation determines the image scale and pauses. Neither requires simulated paper or decorative issue labels.

## Fit restraint to the job

| Decision | Plan field | What checks it |
| --- | --- | --- |
| Choose how much explanation and density each surface needs | `direction.read.surface_mode`, `brief.product_frame`, `direction.dials.density`, `layout.procedure.responsive` | The critic's vision check examines captured widths against priority; a rule does not determine task suitability |

An operate surface can be quiet and information-rich. A read surface can give imagery space while keeping the text's place clear. A persuade surface needs decision-making facts. Set density from those needs, not a preference for sparsity.

A public swimming facility's membership settings must retain eligibility, renewal state, and cancellation controls. A dance archive's essay can vary photograph scale to distinguish a production from a rehearsal detail. On a compact screen, move notes beside the relevant passage and preserve labels. Do not shrink an article rail or hide controls to protect a desktop composition.

## Challenge the generic package

| Decision | Plan field | What checks it |
| --- | --- | --- |
| Decide which detected conventions are earned and which must change | `defaults[].id`, `defaults[].decision`, `defaults[].basis`, `defaults[].reason` | Each cited rule observes its own inputs; the critic's counterfactual test assesses whether the reason survives a different subject |

A default card is a prompt to inspect a choice, not a demand to invert it. Replacing warmth with black, or a serif with a sans, can preserve the same generic structure. Record rule-specific decisions with a real basis. Do not enter a card name as a rule ID.

| Card to examine | Rule and what it reads |
| --- | --- |
| `warm-editorial` | `color.warm-editorial` combines package member findings; `color.cream-base` reads field colors and `color.terracotta-accent` reads identity or interaction colors |
| `premium-serif` | `type.serif-luxury-display` reads planned display/heading families and measured rendered family features, including italic display usage |
| `one-neutral-voice` | `type.single-neutral-sans` counts distinct families; it does not inspect the reason for a single-family system |
| `label-above-heading` | `type.eyebrow-kicker` reads repeated small heading lead-ins; `layout.decorative-numbering` reads marker order and whether markers span separate sections |
| `global-habit-values` | `color.pure-endpoints` reads exact rendered black/white palette entries; `surface.uniform-large-radius` reads large corners across containers |

A subject-earned warm field or shared family can remain. Explain the material or role relation instead of treating detection as proof that the choice is wrong. Regional histories of restraint require a separate inquiry; they are not palette instructions supplied by these style words.

## Give restraint a subject-specific address

| Decision | Plan field | What checks it |
| --- | --- | --- |
| Locate care in evidence: an instrument's repair joints or a textile collection's weave details, then resolve field, foreground, and accent roles separately | `world_materials`, `tokens.color.roles` | `color.warm-editorial` reads package members; `color.cream-base` and `color.terracotta-accent` read role colors; `type.serif-luxury-display` reads family feature regions, not the evidence of care |
| Assign text jobs before selecting families: sustained account, short title, navigation, captions, or tabular data | `tokens.type.roles`, `tokens.type.scale` | `type.single-neutral-sans` counts families; `type.flat-hierarchy` checks planned scale ratio and rendered size, weight, and contrast distinctions |
| Make labels carry scope, authorship, or a genuine sequence rather than a repeated decorative prefix | `content.key_copy`, `layout.sections` | `type.eyebrow-kicker` detects heading lead-in repetition; `layout.decorative-numbering` detects out-of-order markers or numbers applied across separate sections; neither establishes their meaning |
| Make quietness through grouping and hierarchy while retaining readable foregrounds and captions | `tokens.color.roles`, `tokens.type.roles` | `color.text-contrast` reads captured text/backdrop pairs in the specified themes and states; `type.tiny-ui-text` reads body, interface, and caption sizes by script |
| Use symmetry for genuinely balanced content, or position unequal material according to its reading weight | `layout.procedure.grid`, `layout.procedure.priority` | `layout.symmetry-excess` reads rendered centering on the vertical axis; balance and its purpose require the critic |

For the field report, a heading might establish the surveyed formation while captions identify the photographed feature. For the workshop account, a data role can carry tuning observations while the body explains the intervention. These are different distributions of attention, not mandatory family pairings. Read `type.md` for role and face selection and `layout.md` for reading measure and spatial relationships.

A plan can record explanatory captions in `content.key_copy` with the `other` slot. It has no dedicated publication-unit or line-measure field: describe those choices in `layout.procedure.content_inventory` and `layout.procedure.grid`. Their editorial adequacy remains a critic judgement rather than a schema guarantee.

## Combine without blurring ownership

| Decision | Plan field | What checks it |
| --- | --- | --- |
| Identify which surface and variable each influence controls | `direction.read.style_name`, `direction.read.text` | The critic's package-drift check reports substitution by another named package; ownership boundaries are not checked |

A task-led service can reserve editorial image pacing for its documented case studies while keeping settings and forms conventional. A publication can use plain utility controls for searching the archive without turning articles into dashboard panels. Write those boundaries into the design read. Restrained controls do not require restrained storytelling, and expressive titles need not govern error messages.

## Keep the verdict bounded

| Decision | Plan field | What checks it |
| --- | --- | --- |
| Record unanswered decisions separately from observed defects | `claims.unresolved` | The critic reviews supplied evidence; an unresolved claim is not a passed check |

| Check family | Reads | Leaves open |
| --- | --- | --- |
| Palette and package rules | Planned role colors, rendered palette roles, member findings | Why warmth belongs to the material |
| Type rules | Family counts or available measured features, heading/body metrics, script-specific sizes | Whether a face supports the publication's voice and sustained reading |
| Labels and symmetry | Lead-in relationships, index placement, axis centering | Whether attribution, sequence, and balance are meaningful |
| Critic | Screenshots, declared choices, material traces, and counterfactuals | Anything missing from the supplied view or record |

A family-region check without the needed measurements is skipped, not a finding about taste. `type.tiny-ui-text`, `layout.symmetry-excess`, and `color.cream-base` are warnings. Requirements such as readable text contrast still apply when delicacy is the intended voice.
