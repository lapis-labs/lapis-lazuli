# Archetypes

This file backs plan step 8 at its archetype step. The plan holds `layout.procedure.archetype` (one id
for the screen), `layout.sections[].archetype` (one id per section), and each section's `answers`; the
last part lists what each `brief.product_frame` adds. The other eight steps, grids, spacing, hierarchy
relations, responsive primitives, and density are in `layout.md`.

An archetype is a recurring task structure, such as a dashboard, a checkout, or an editor. It fixes
which regions a screen has and how they relate. It is not a visual style: type, color, surfaces, and
the signature make the screen this product's, and two screens with one archetype can look nothing
alike.

## Choose the screen archetype

1. Start from `brief.one_job` and the ranked inventory in `layout.procedure.priority`. The frame
   suggests likely archetypes; the job decides. A pottery studio's sales page whose job is "see this
   firing's pieces and reserve one" is `list-detail` with persuading sections inside it, not `landing`.
2. Name the content relationship and the primary task, and find the row below. Never choose an
   archetype because a screenshot of it has the look you want.
3. Compare the choice with the neighbor in the last column, and write in `claims.proposed` why the
   neighbor lost, so it does not return unexamined.
4. Write one id in `layout.procedure.archetype`. A screen has one primary archetype; combine others
   only at a task seam, and describe secondary regions in `layout.procedure.relationships`.
5. Check the entry's **Needs** against `layout.procedure.content_inventory`. What is missing becomes an
   `unresolved` claim or a labeled slot; never invent metrics, plans, customers, or records to fill a
   region.

| id | Content relationship | Primary task | Take the neighbor when |
|---|---|---|---|
| `landing` | narrative and evidence | understand and decide | the reader must learn a system: `docs` |
| `pricing` | packages and differences | compare and choose | one simple offer: a `pricing` section |
| `dashboard` | signals and exceptions | monitor and route | the work is editing records: `table` |
| `list-detail` | a collection and one item | browse and inspect | detail is deep, switching rare: `entity-detail` |
| `table` | repeated structured records | compare and act | items are narrative: a list |
| `form` | ordered input | provide and commit | values are durable preferences: `settings` |
| `settings` | durable preferences | configure behavior | order and dependency matter: `form` |
| `feed` | ordered events | follow and continue | comparison or bulk action dominates: `table` |
| `editor` | one mutable artifact | create and manipulate | only a few properties change: `form` |
| `checkout` | items, costs, fulfillment, payment | review and commit a purchase | nothing is bought: `form` |
| `auth` | identity and access | sign in, create, recover | the page mainly sells: `landing` |
| `onboarding` | first-use progress | reach first value | the interface explains itself: a first-use state |
| `search` | a query and its matches | find and judge | the set is small and known: filtering |
| `entity-detail` | one entity and its relations | understand and act | many entities are monitored: `dashboard` |
| `empty-error` | absence or failure | recover | the absence belongs to another screen (nearly always): a state of that host archetype |
| `docs` | structured knowledge | learn, look up, do | the page argues for a product: `landing` |

A surface none of these fits, such as a play view or an authored sequence of work, takes a kebab-case
id of your own that names its task structure; describe its regions in `layout.procedure.relationships`.

## Screen archetypes

In each entry, regions read in order: `→` is sequence, `|` is side by side on a wide screen, `+` is
together in one region. **Needs**
is what the inventory must hold first; **Question** is the default to question.

### `landing`

- **Job.** Explain a proposition, earn belief with evidence, lead to one action.
- **Regions.** `navigation → opening: proposition + action → proof → sections the reader's questions call for → final decision → footer`.
- **Decide.** Audience and promise, evidence order, product view or subject imagery, what the action
  commits to, each section's kind.
- **Needs.** The argument, a proof inventory with provenance, the objections, one primary action.
- **Question.** An opening shell chosen before the content was ranked, and the category's usual order.
  Walk `template-page`.

### `pricing`

- **Job.** Compare offers and choose a purchase or contact route.
- **Regions.** `heading + billing scope → plan summaries → decisive differences → full comparison → procurement and terms`.
- **Decide.** The billing interval control; a recommended plan only with evidence; comparison groups;
  self-serve and sales routes; a compact comparison that keeps every plan and feature reachable.
- **Needs.** Prices with currency, unit, interval, taxes, and fees; limits; the features that differ;
  renewal and cancellation terms.
- **Question.** Equal cards with an unsupported badge, and terms truncated to keep heights equal.

### `dashboard`

- **Job.** Show current state and exceptions, and route to the work.
- **Regions.** `navigation + scope and time range → exceptions → primary measure | context → required actions → secondary trends → routes to detail`.
- **Decide.** Time range, the baseline per measure, thresholds and owners, drill-down routes, how stale
  data looks, spans by importance. On compact screens exceptions and actions come before trends.
- **Needs.** The decisions it supports and, per measure, its period, unit, comparison, source, and
  freshness.
- **Question.** A grid of equal metric cards and charts that support no decision.

### `list-detail`

- **Job.** Browse a collection while acting on one item, without losing the collection.
- **Regions.** `navigation | list + filters | selected item: title, actions, sections, history`.
- **Decide.** Row content and list width, the empty selection, where filters live, next and previous,
  bulk actions. On compact screens a list route and a detail route that restore filters, scroll, and
  selection on return.
- **Needs.** The real collection with its count and longest names, the detail's sections, how often
  people switch items.
- **Question.** A preview sheet standing in for the full detail.

### `table`

- **Job.** Scan, compare, sort, filter, and act across many records.
- **Regions.** `title + search + filters → bulk bar on selection → header + rows → position and paging`.
- **Decide.** Column priority and alignment (figures in `type.md`), units in headers, sticky
  header or first column, row versus cell actions, selection scope. On compact screens the table
  scrolls in its own region while comparison stays primary; otherwise priority columns plus a full
  record view.
- **Needs.** Fields with types and units, row counts, the longest values, row and bulk actions.
- **Question.** Rows turned into cards on compact screens, which destroys comparison.

### `form`

- **Job.** Collect, check, and commit structured input.
- **Regions.** `title + outcome (+ progress for real stages) → sections → label, control, help, error → back + commit → support, save and resume`.
- **Decide.** One reading path; grouping; which short, familiar pairs share a row on wide screens;
  stages only for dependency, complexity, or resuming; where the error summary sits; the commit action
  after the fields it commits.
- **Needs.** Each field's label, requirement, dependency, and sensitivity; the outcome of committing.
- **Question.** Two columns with an ambiguous order, and a short form split into steps to look easier.

### `settings`

- **Job.** Configure durable preferences, properties, integrations, and destructive controls.
- **Regions.** `settings index | category: scope → groups → save feedback → separated destructive controls`.
- **Decide.** Categories; scope (personal, workspace, organization) in the page title; one save model
  per page. On compact screens the index becomes a route and each category keeps its own.
- **Needs.** The real settings with scope, permissions, and defaults, destructive ones marked.
- **Question.** A dumping ground for unrelated features. Controls used mid-task stay with that task.

### `feed`

- **Job.** Present ordered events, posts, or messages to scan and continue.
- **Regions.** `title + filters + compose → date groups → items: author, time, content, actions → end`.
- **Decide.** Direction, grouping, the unread marker, item anatomy, where new items are announced
  without moving the reader, an end state. One readable column; wide screens add context beside it.
- **Needs.** Real items, long and short, with media; volume and update rate.
- **Question.** A stream with no end or restored position, and actions that outweigh the content.

### `editor`

- **Job.** Create or change an artifact with tools, selection, and history.
- **Regions.** `document + save state → tools | working surface | inspector → status: zoom, position, errors`.
- **Decide.** Which panels persist or collapse, and their minimum useful sizes; where save and conflict
  state show; a compact form that focuses the surface with context sheets, or a reduced set labeled as
  reduced.
- **Needs.** The document model, what can be selected, tools versus properties, the save model.
- **Question.** A three-pane desktop editor squeezed into icon rails on a phone.

### `checkout`

- **Job.** Review an order, give delivery and payment details, understand the total, commit.
- **Regions.** `contact → delivery → payment | summary: items, discounts, fees, total → commit with total → returns, privacy, support`.
- **Decide.** The summary beside the form on wide screens and expandable near payment on compact ones;
  every fee visible before commitment; where legal context sits.
- **Needs.** Items and variants, every price component, fulfillment options, payment methods, return
  terms.
- **Question.** A coupon field that dominates the page, and a summary hidden on compact screens.

### `auth`

- **Job.** Establish, create, recover, or strengthen access.
- **Regions.** `service identity → identifier and credentials → primary action → other methods, each named → recovery → privacy, support`.
- **Decide.** Method order, how the identifier and credential steps split, where errors and recovery
  sit, a measure that stays narrow on wide screens and fills compact ones.
- **Needs.** The methods offered, recovery routes, the return destination, support.
- **Question.** A decorative side panel, and a form buried under a sales page.

### `onboarding`

- **Job.** Reach a first real success, asking only for necessary setup.
- **Regions.** `welcome + outcome → one step: reason, input → continue | defer when safe → progress → first result`.
- **Decide.** Required and deferrable steps; where a permission is explained before the platform asks;
  sample or real data; an ending in the product's real empty or populated state.
- **Needs.** The activation outcome, the steps that truly block value, each permission and its moment.
- **Question.** A carousel tour before any value, and every preference asked up front.

### `search`

- **Job.** Refine a query, judge the matches, continue with a result.
- **Regions.** `query → count, scope, sort → filters | results: title, excerpt, metadata → active filters + paging`.
- **Decide.** Result anatomy, how matches are marked, facets, recovery from zero results. On compact
  screens an active-filter summary plus a filter sheet, with sort and scope visible.
- **Needs.** The corpus and who may see what, real results with long titles, the metadata people judge
  by.
- **Question.** Results without a useful excerpt, and filters that vanish on compact screens.

### `entity-detail`

- **Job.** Present one person, product, order, or record with its identity, status, attributes,
  relations, and actions. Profiles and product pages are entity details.
- **Regions.** `identity + status + primary action → summary → views or sections → main detail | side context`.
- **Decide.** Tabs or sections, the primary action per role, public and private fields, view and edit
  states. On compact screens side context becomes ordered sections; identity and status stay on top.
- **Needs.** The canonical name with its long forms, status values, attributes, relations, actions by
  role.
- **Question.** Attributes in an arbitrary card grid, a dominating avatar, and many peer tabs.

### `empty-error`

- **Job.** Explain why expected content is absent and offer a recovery, inside the host archetype's
  navigation and context.
- **Regions.** `existing context → what happened → safe, useful cause → primary recovery | secondary route → details, support`.
- **Decide.** Which states need a structure of their own (first use, no matches, no permission, failure,
  offline, removed, unknown route), what entered work is kept, whether navigation and search stay.
- **Needs.** Per state, its cause, its recovery, and who owns support.
- **Question.** One illustration and one route home for every absence.

### `docs`

- **Job.** Support learning, look-up, and task completion across versioned content.
- **Regions.** `navigation + search + version → section navigation | article | on-this-page → previous and next, feedback`.
- **Decide.** The content type per page, the column's measure, where version shows, how code and tables
  overflow. On compact screens the article comes first and both navigations become labeled controls.
- **Needs.** Content types, supported versions, the heading outline with anchors, real code with its
  environment.
- **Question.** One three-region shell for every page type, and prose widened to fit code.

## Combine at a task seam

A dashboard links to a `table` for bulk work; search results open an `entity-detail`; a checkout is a
specialized `form` with a persistent summary; a docs page embeds a small working example without
becoming an editor. A secondary region keeps only what it needs from its full archetype: a short
preview of recent invoices on a dashboard does not need the table's toolbar.

## Inside the archetype

- The archetype sets the regions; the relation inside each region (flow, comparable rows, a sequence,
  independent objects, an overlay) comes from the content, as in `layout.md`. Cards are for
  independent, comparable objects; when equal boxes hold unequal content, boxes nest, or cells only
  complete a shape, walk `boxed-everything`.
- A starter template's structure is not an archetype decision. When the plan keeps one and changes only
  its colors, walk `starter-surface`.
- States are part of the structure. For each region, name where loading, empty, partial, error, and
  no-permission appear and what stays visible around them; a skeleton follows the real layout. How each
  state behaves belongs to the `lps-ux` skill.
- Consequence sets an action's emphasis; staying visible does not. An action enabled by a selection
  sits next to it, a long subordinate task gets its own route, and a final commitment follows the
  content it commits. When several fixed things compete for one edge (a sticky action, a banner, bottom
  navigation, the keyboard), decide their stacking in the plan.

## Requirements and locales at every width

The width requirements and the Korean, Japanese, and Chinese rules in `layout.md` hold for every
archetype and are never traded for a composition. Per archetype, decide in the plan:

- each region's compact form as a transformation: every item, action, price, term, and legal route
  stays reachable;
- which fixed or sticky regions share an edge, so none covers the focused element, a field, an error,
  or the text being typed;
- a second form (wrapping, a contained scroll region, another navigation model) for tabs, segmented
  controls, one-line navigation, and equal-width plan or table columns that fit one locale, and where
  long names in list rows, table cells, and entity headers wrap and show in full. A composition that
  depends on a heading's length fails in another locale; balance by content.

## Section archetypes

Every section answers one question the reader brings; on a persuading page those questions also set
the order. `layout.sections[].answers` holds that question in the reader's words, and `archetype` names
the section's kind.

Use the render check's names for the kinds it recognizes, so plan and render compare the same thing:
`cta`, `faq`, `feature-grid`, `footer`, `hero`, `logo-strip`, `pricing`, `testimonial`. A familiar kind
under another name is still that kind. For a kind the render does not recognize, write a kebab-case id
that names its content relation, as in the second table. Never write `other`: name what the section is.
On operate and read screens, a region that is a reduced instance of a screen archetype takes that id
(`table`, `feed`, `form`).

Rows are alphabetical. A page's order comes from its reader's questions (below), never from this table.

| id | Answers | Needs before it exists | Compact form |
|---|---|---|---|
| `cta` | what do I do, now that I know this | the earlier action's outcome, alternatives, required context | stacked, every route kept |
| `faq` | what else would stop me | questions taken from support, sales, search, or research | the same column; answers may grow |
| `feature-grid` | what can it do, among peers | peer capabilities at one level, with similar evidence | one column, or an intrinsic two and one |
| `footer` | where else can I go, who runs this | what the product owes and offers: legal, contact, locale, site routes | stacked groups, legal and contact reachable |
| `hero` | what is this, is it for me, what next | audience, outcome, one primary action | proposition, then action, then evidence |
| `logo-strip` | who else uses or connects to this | real, approved marks and the stated relation (customers, integrations, supported systems, press); it proves nothing more | a static wrapping list |
| `pricing` | what does it cost, which option fits | what the `pricing` archetype needs | stacked summaries plus a reachable comparison |
| `testimonial` | does it work for people like me | attributed quotes, permission, a reason they apply | one column, attribution beside each quote |

| id | Answers | Needs before it exists |
|---|---|---|
| `signature` | the question the subject's own element answers best | the `layout.signature` element, built from a world material |
| `list` | what is there to choose from | the real collection: count, names, prices, states |
| `demonstration` | how does it work | a real capture, recording, diagram, or safe live demo with task, start, action, outcome |
| `steps` | what happens, in what order | a real sequence and its result |
| `comparison` | how does it compare, which fits me | criteria and a value for each option |
| `modules` | what are its unequal parts | independent capabilities that differ in size or importance, one cell per real item |
| `case` | what changed for someone, under which conditions | problem, intervention, result, conditions, source |

### Order sections by the reader's questions

1. Write the argument before any section: who it is for, what changes for them, why they should believe
   it, why this rather than another, the next action, and what could block the decision. Each line
   points to material you have or to an `unresolved` claim.
2. List the questions this reader brings and rank them by when this reader needs each answer. Someone
   starting a public service first asks whether they qualify and what to bring; a developer wants a
   request and its response right after the proposition; a buyer of this month's firing asks what came
   out of the kiln.
3. Give each question one section, in rank order, with the question in `answers`. When two adjacent
   sections answer one question with the same kind of evidence, merge them.
4. Choose each section's kind from its content, never from what usually comes next.
5. Place the signature where its question falls. It can be the opening itself: the pottery page opens
   on the firing log.
6. Walk the `template-page` card. When the sequence you reached matches the category's usual order,
   keep it only when the reader's questions genuinely run in that order, and record why in `defaults`;
   otherwise return to step 2.

### The opening

The opening holds the proposition and the action; nothing else in it competes with them.

- It says who it is for, what changes, and what to do next, with one primary action and at most one
  secondary route. When a small label sits above the heading, walk `label-above-heading`.
- Proof comes right after the opening, not inside it. A logo strip, metrics, and extra copy packed into
  the opening bury the proposition.
- A split opening works when its second region is evidence, media, or a distinct decision. A heading on
  one side with its explanation on the other is one reading path cut in two.
- The opening grows with larger text, longer translations, and legal qualifications; never clip,
  shrink, or hide content to hold a first-screen composition.

| Content need | Opening |
|---|---|
| a clear product with visual proof | the proposition beside a real product view |
| a service with consequential prerequisites | narrow and content-first: what it does, who qualifies, what is needed, cost and time, then start |
| a familiar product with a short message | a concise centered opening |
| a technical tool | the proposition with a real artifact: a request and its response, a command and its output |
| a portfolio or an experience | the work or the subject first, identity and controls clear |

### Proof after the claim

- Put each piece of evidence directly after the claim it supports; a testimonial carousel far from its
  claim hides the connection.
- Plan only real, approved, attributed proof. When it does not exist yet, plan a labeled slot and an
  `unresolved` claim, never invented names, numbers, quotes, or a drawn product window (walk
  `stand-in-imagery`). When only two customers can be named, a short attributed block serves better than a sparse strip.
- When most readers need an answer before acting (price, security, eligibility, migration), put it in
  the main sequence, not only in `faq`, and keep consequential terms outside a collapsed disclosure.

### Rhythm and variation

- Rhythm follows changes in reading demand: compression (a short claim or proof summary), expansion
  (a demonstration, a case, a comparison), a pause (one statement or image), acceleration (short
  repeated steps), and decision (pricing, eligibility, sign-up). Change a section's structure when its
  content relation changes; three equal grids in a row make no rhythm, whatever their backgrounds.
- Spacing states the argument: tight inside one claim, wider between evidence units, widest at a turn in
  the argument. The proximity relations and the scale are in `layout.md`.
- A new background or surface marks a real turn, such as proposition to proof, story to customer
  evidence, or decision to support and legal. It never exists only to stripe the page. Variety comes
  from spans and relations on one shared grid, not from arbitrary offsets.
- Repetition is earned by repeated content. When one capability needs a demonstration and another is a
  policy note, give them different kinds. Alternating media and text rows fit while each row answers a
  distinct question with a real artifact; after a short run, change the structure, and never reverse
  source order to keep the alternation.

## Product frames

Constraints that change a layout or the plan, keyed by `brief.product_frame`; the archetype entries
still apply. Classify by the surface's task, not the company: a developer tool's product page is
`marketing-landing`, its trace view `developer-tools`. Navigation models and flows belong to the
`lps-ux` skill, wording to the `lps-copy` skill.

### `marketing-landing`

- A technical audience gets a real artifact right after the proposition. A complex, high-consideration,
  or regulated offer puts method and evidence before price, and its opening may run longer.
- In a redesign, existing routes, heading meaning, and indexed copy are constraints: write them in
  `brief.constraints`.

### `saas-dashboard-admin`

- Scope (personal, workspace, organization) sits in the page title or header, not only as a sidebar
  highlight.
- An overview answers what changed, what needs attention, what can be resumed, and where to go next;
  nothing else earns a module.
- A redesign keeps the learned shell and navigation unless the user authorizes the change.

### `consumer-mobile-app`

- Navigation bars, back behavior, sheets, pickers, and safe areas follow the platform's guidelines.
  Share concepts, priorities, and tokens across platforms, not identical rendering.
- Choose one home model, resume, status, explore, or act, and write it in
  `layout.procedure.relationships`.
- One vertical flow by default, without nested vertical scrolling; a carousel never holds essential
  content after its first item.
- Frequent, low-risk actions sit within comfortable reach, destructive ones stay deliberate, and nothing
  essential exists only as a gesture. With the software keyboard open or large text on, the focused
  field and the commit action stay visible.
- Name the connectivity mode (online only, readable offline, queued writes, offline first); it decides
  where freshness and pending status sit.

### `e-commerce`

- On the product page, price, variant choice, availability for that variant and place, the delivery
  estimate, and the commit action form one group; changing the variant updates price and availability
  beside the selector.
- Returns, warranty, and policy sit near the decision; related products come after it.
- Order media by the purchase questions (fit, scale, texture; ports, dimensions, included items);
  lifestyle imagery does not replace that evidence.
- In listings, name, price, and availability are never truncated to keep a grid uniform, and
  sponsored placement and marketplace sellers are marked.

### `content-editorial-docs`

- Name each page's reading task; it chooses the structure. Learn: a sequence with examples. Complete:
  prerequisites, steps, result, recovery. Look up: anchored reference. Decide: criteria and tradeoffs.
  Troubleshoot: symptom, cause, fix. Explore: authored pacing and onward paths.
- Flow when content grows, reorders, or is translated; a fixed frame only when placement carries
  meaning and the frame is known; otherwise a flowing body with bounded fixed figures.
- Wide tables and code get a contained region; the prose keeps its measure (`type.md`).
- With several supported versions, version and applicability sit in the article header, never over
  the title.
- In a named receiving editor, author with its own headings, anchors, and blocks.

### `developer-tools`

- The context (project, environment, region, branch, identity) is visible at the point of action, not
  only in a breadcrumb; color supplements the label and never replaces it.
- Size the workbench to the task: a request-and-result workspace for one action; each extra panel needs
  a job, a minimum useful size, and a collapsed state that keeps its errors.
- The output region separates validation, transport, and runtime failures from partial, empty,
  truncated, stale, and complete results, with request, duration, and time beside each result.
- Logs keep timestamp, source, and severity columns and can pause following.
- Code samples sit with their language, environment, and version; documentation links stay pinned to
  the version in use.

### `fintech-regulated`

- Total, available, pending, and limit amounts are separate labeled figures.
- A transaction row holds counterparty, signed amount with currency, domain status, date, and
  instrument, with signs and decimals aligned.
- Before a consequential commit, one review region shows source, recipient, amount, fees and rate,
  timing with its basis, recurrence, and cancellation boundary; disclosures sit beside the decision they
  qualify. No material value hides in a disclosure opened after the action.
- The result is a durable receipt with status, reference, and next expected state, with room for a
  status timeline.
- Carry the frame as a constraint when another dominates: a staff fraud review is `internal-tools` with
  it. Disclosure text and eligibility rules come from their owners; plan a slot and an `unresolved`
  claim.

### `internal-tools`

- Scan-then-decide work is `list-detail`: a queue beside a case. Draft notes survive switching items,
  and new arrivals never reorder the row under the pointer.
- The case separates source data, staff notes, derived indicators, outside messages, policy, and earlier
  decisions, and shows conflicting sources; the material chooses sections, tables, timelines, or
  document views.
- Decisions, notes, handoff, and escalation share one action region beside the evidence, with the audit
  timeline in reach.
- Structure the exceptions (contradictory data, claimed by another worker, overdue, reopened, waiting)
  before any decorative empty state.
- Density comes from alignment and grouping, never from removed labels or hover-only state.

### `portfolio-personal`

- The first view names the person or studio, the practice, and a route to the work.
- Proof fits the practice: interface work shows role, decisions, and shipped behavior; brand work the
  system in use; development live behavior; writing excerpts in context; photography a sequenced series.
- The work index is a grid when imagery drives recognition, a list when titles and context do; scale
  and order follow importance (walk `boxed-everything`).
- Keep a visible contact route that needs no social account, and a reliable way back from immersive
  pages.

### `games-entertainment`

- The play view is an experience surface with an id of its own, such as `hud`. Inventory, settings,
  lobby, store, and account take operate archetypes; a lore archive reads like `docs`.
- A heads-up display holds only what is useful now, in stable regions ordered by consequence, away from
  edges the display may cut off; critical text sits on a treatment that survives the busiest scene.
- A pause menu says whether the world is actually paused and puts the resume path first.
- On a television or with a controller, directional focus follows the visual layout, and type is sized
  for the viewing distance.
- Inventory is a grid for recognizable item art and a list or table for compared statistics. A store
  shows price, quantity, recurrence, and scope beside the purchase action.

### `forms-onboarding-checkout`

The screen archetype is `form`, `checkout`, `onboarding`, or `auth`, and those entries hold the
structure. The frame adds one logical column on compact screens and when zoomed, and stages only where
the task has real stages. Step sequences, validation, sign-in, and consent flows belong to the `lps-ux`
skill and the behavior checks.

### `data-visualization`

The screen archetype is usually `dashboard`. A single analysis view takes an id of its own, such as
`analysis`, with regions `question title → scope: population, filters, time range, freshness → primary
view | controls beside what they change → the annotation that explains the signal → details, table, and
definitions on demand`. Each chart region names its period, unit, comparison, source, and freshness, and its values
stay available as text or a table; a compact chart may simplify its annotation but keeps its values.
Which chart answers each question, and how it is scaled, colored, and read without sight, is decided in `data-viz.md`.
