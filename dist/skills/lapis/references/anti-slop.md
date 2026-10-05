# Recurring defaults on generated pages

## Sections

Read the section whose default the plan or draft meets, by heading; the rest are other decisions.

- Opening: whether the split hero, product mock, and floating panels stay or the opening comes from the content, and what to do when the object is removed and an empty column is left
- Phone width: the wide page stacked into a column, a rail or bar kept, an object pushed below the heading, bands with nothing in them
- Section order and the close: the feature, steps, plans, questions, banner, footer sequence
- Page rhythm: one ground and one shape from top to bottom, and stripes by rote
- Cards and modules: cards everywhere with no rank, nested cards, icon tiles that outweigh their headings, bento filler, sections that repeat one shape
- Plans: the three-card price row with a lifted middle plan
- Palette: the recurring palettes (sage and cream, indigo, near-black with acid green, teal), and green as a default of its own
- Type and headline treatment: one neutral sans, tracked capital labels, one accented word or a closing phrase switched to italic or serif
- Headlines and wording: two-sentence, negation, and less-more headline moves
- What the page says about itself: demo and fictional-data notices, how often and where, and a flow that narrates its next step
- Icons and imagery: thin icon sets, cloud and shield proof, pictures drawn from CSS shapes
- Data and fixtures: invented files, a row of totals, which numbers a dashboard shows, a chart with no question
- Motion: idle loops, a reveal on every section, hover zoom
- Per-genre packages: the defaults that arrive together for a kind of page, and the counter-package that worked

What generated pages share before the subject has been read, why each shared choice weakens a page, and what to
do instead. Read it with the default cards (`../shared/slop/cards.yaml`) and the rules they name
(`../shared/slop/rules.yaml`). It describes pages from a corpus of about 120 generated landing pages, booking forms,
dashboards, and editorial pages; a count is a sign that a choice is a default, not a rate for any other site.

A default is a choice that needs a reason, not a ban. For each one your plan or draft meets, record `keep` with
one of the rule's `keep_when` cases and the evidence it lists, or `reject` and take a route that spends a world
material, the signature, or a plan decision. Replacing one named package with another (calm green for violet,
cream and serif for dark glass) is not a route; compare a replacement as a structure without its finish
(`layout.md`, step 6). When a default is the honest answer, say what makes it so.

Judge a split, a centered title, a serif, or a green by why it is here: the same choice is right when the content or
the subject asks for it and a default when it came with the category. Passing the checks is not the result either.
Look at the first view and at the whole page at each width, as the visitor does, and say what is still wrong.

The cards judge a direction this task chooses: a new surface, a redesign, or the part of one that is still open. A
system the project already has, a `DESIGN.md` contract or an approved design the surface continues, wins. A choice it
fixes is kept with that basis and not rejected, and a small edit inside it walks no card.

Each entry: what it looks like, why it reads as generated, what to do instead, honest exceptions, and the rules
that see it. Rules marked * are statistical or lexical leads; the critic judges them against the page.

## Opening

- **Looks like.** A split hero, either way round: the large heading, a short paragraph, and two buttons in one
  column; a product mock, an illustration, or a picture in the other. The mock is a small invented app (title bar,
  file rows, a storage bar, a "Synced" line). Short status panels float over its edge ("Backup complete", "Always
  protected", a file card). Sometimes a vault, cloud, or shield mascot stands in for the product. The buttons are a
  filled start action and a quiet "see how it works". A strip of three short assurances or logos follows.
- **Reads as generated because** the composition was picked before the content was ranked. Two columns, a big
  heading, and an object fit any subject, so changing the product changes a noun and nothing else; it is the
  commonest opening in the corpus, on nearly every landing page for software and on museum, craft, and product
  pages alike. Mock chrome and floating panels are plausibility, not a fact the visitor can use; the mascot
  restates the claim.
- **Instead.** Do not swap in another layout from a list of layouts; derive the opening, from one of three things.
  The relation inside the content: the thing and its state, a question and its answer, before and after, a claim
  and the record that proves it - the composition is whatever puts that relation on the screen (the restore point
  and its time as the heading's own sentence, the route on the map with the arrival below it). The subject's own
  objects: the firing log row, the ticket, the timetable, the printed page, at their real scale and arrangement
  (`world_materials`), which no other subject could reuse. The sequence the visitor follows: what they see, what
  they decide, what they do, set in that order down or across the screen instead of divided into columns. Keep a
  second button only when it serves a different intent right now, such as evaluating versus starting. If the split
  is still what the derivation gives, say which of the three gave it and compare it with an opening built without
  it, rendered with the page's copy (`explorations`, decision `layout`).
- **Exceptions.** A real capture of the subject itself beside its name (the product at work, the artwork, the
  object on sale), recorded as evidence. The interface the visitor came to use, such as a booking panel or a
  search, with the first column saying what it is for. One record of the subject's real state beside the claim it
  supports. A contract or brief that fixes a two-column opening. A split that won a rendered comparison against an
  opening without it. A working preview labelled as an illustration is evidence; a real confirmation inside a
  captured task is not decoration; an annotated diagram names its parts. A strip of comparable, verified facts
  (supported platforms, a stated retention) helps an immediate evaluation.
- **When the object is only removed.** The same short column of heading, a few lines, and a button now stands beside
  empty space or beside a drawn stand-in, and that is not a new opening. Ask what the space stands for. Pull the
  content the page is about into the first view - the record, list, search, booking, comparison, or the work itself -
  and recompose the opening's width, height, and order around it, so the introduction is short and the content has
  the width. Centering the column, or putting a mock, chips, or a drawing back, only moves the gap. Left alignment and
  open space are not the defect: keep them where type large enough to carry the width, a record or picture already
  visible in the first view, or a poster-like composition (an exhibition, a venue, a release) holds them, and show it
  in the first view at desktop width.
- **Rules.** `layout.split-hero`, `layout.unearned-empty-opening`, `layout.hero-before-priority`,
  `component.fake-app-window`, `component.floating-chips`, `imagery.css-illustration`, `copy.vague-cta`.

## Phone width

- **Looks like.** The wide page in one column. The top bar and the icon sidebar stay on the phone, or a row of five
  items runs off the edge or wraps inside its labels. The picture that stood beside the heading drops under it and
  fills a third of the first screen, so the page gets longer and the first view shows its least useful part. Bands a
  quarter of the screen tall with nothing to read or press between the sections.
- **Reads as generated because** nothing was decided for the width: columns collapse and whatever was large on the
  wide layout pushes the task down. A page can pass the overflow check and still be this.
- **Instead.** Compose the phone view as its own arrangement of the task. Decide what the first view shows (the task,
  or the heading and the one action), what moves to a secondary view, and which object is cropped, shrunk, moved
  after the content it supports, or dropped at this width. Count the screens the page runs and what each large object
  costs in scroll before the first action. Give navigation its phone form: a few destinations in one place the thumb
  reaches, the current place named at the top. Run a booking or another task in steps as one step per view with a
  visible current step (`archetypes.md`, Genre structures).
  Read the actual heading at 390, not only its overflow result. Hiding `여백의<br>형태` must not produce
  `여백의형태`: preserve the word space before the `br`, or use a span with explicit spacing.
- **Exceptions.** A tool whose phone use is a persistent rail, such as a map or an editor, when the brief or contract
  says so. An image that is the subject itself. A long page whose length is its content.
- **Rules.** `layout.compact-desktop-navigation`, `layout.compact-object-opening`, `layout.compact-empty-length`,
  `layout.shrunk-desktop`, `layout.compact-overflow`, `layout.edge-flush`.

## Section order and the close

- **Looks like.** Feature cards, "three steps", plans, a short questions list, a closing banner that repeats the
  hero's action, then a footer with Product, Company, Resources, and Legal columns.
- **Reads as generated because** the sections exist because the category has them, and the same order would answer
  any product's page. The closing banner extends the template after the visitor already has the action.
- **Instead.** List the questions this visitor brings, in the order they ask them, and order and size the sections
  by those. Leave out proof and explanation nobody asked for. End on the next step and the one condition still
  open. Group the footer by real destinations; a small useful footer beats invented departments.
- **Exceptions.** A buyer may truly weigh features, cost, and questions in this order. A long evaluation page can
  earn a final action. A multi-product site needs real link groups.
- **Rules.** `layout.template-section-sequence`, `layout.reassurance-landing`.

## Page rhythm

- **Looks like.** Every section on one background, each a heading over the same row of cards; or the background
  alternated by rote, light, tint, light, tint.
- **Reads as generated because** nothing marks where the reader's question changes, so a long page reads as one
  slab. Stripes by rote are the same flatness with a color on it.
- **Instead.** Change the ground, the density, and the structure where the question changes: claim to evidence,
  evidence to decision, decision to terms. A contrast between sections marks a real change of content and nothing
  else. Give the section that carries more the room or the structure it needs, and cut or merge sections that only
  repeat a shape.
- **Exceptions.** One continuous reading (an article, a document, a form). A contract that fixes one field and
  carries the rhythm in scale and space.
- **Rules.** `layout.flat-section-rhythm`, `layout.repeated-section-shape`, `layout.monotonous-spacing`,
  `layout.zigzag`.

## Cards and modules

- **Looks like.** Every item in a rounded card; cards inside cards; every region of an application screen boxed as a
  panel of the same surface, none ranked above another. An icon tile, a heading, and one sentence repeated six times
  at equal weight, the tile larger than the heading it introduces. A bento grid where some cells only complete the
  shape. The same heading over a row of cards, three times, with new words.
- **Reads as generated because** the module came first and the content was poured in, so unequal ideas get equal
  weight and the page cannot show which one decides. A box is not a rank: equal containers say nothing about what to
  read first.
- **Instead.** Decide the form from the content: text to be read is a document with a deck and running text; fields
  to compare are rows or a table; one operated region is one deck; independent products are a gallery. Rank panels
  with surface, size, and position, one primary panel and quiet context. Group with space, rules, and headings. Give
  the deciding capability the room it needs and let the supporting ones become a list, a diagram, or prose. Set an
  icon at the text's scale beside its heading or drop it. Keep a surface only where it has its own role: a selectable
  record, a chart plot, an independent state.
- **Exceptions.** Comparable peer items read well as equal modules. A collection of independent objects is a
  collection of cards. Sections that hold parallel sets, such as the same facts for each of several places.
- **Rules.** `layout.card-everything`, `layout.nested-cards`, `layout.equal-siblings`, `layout.bento-filler`,
  `type.icon-tile-heading`, `type.oversized-icon-tile`, `layout.repeated-section-shape`.

## Plans

- **Looks like.** Exactly three priced cards. The middle one is lifted or filled, outlined in the brand color,
  wears a ribbon ("Most popular", "The sweet spot", "A little more room"), and owns the only filled button.
- **Reads as generated because** the count and the recommendation arrive together and survive a change of
  product. They invent an offering structure and a popularity nobody measured.
- **Instead.** Start from the plans that exist and use their number. Put the difference that decides between
  them first (the limit, the seats, the history). Set one apart only for a fit the buyer can check, and call a plan
  popular only with data.
- **Exceptions.** Three real plans with real differences are ordinary. A recommendation the brief or the sales
  data supports, stated on the card, is information.
- **Rules.** `layout.pricing-trio-recommendation`, `layout.equal-siblings`.

## Palette

- **Looks like.** Four families recur. Sage or forest green with cream or a mist-tinted white. Indigo or violet
  with white. Near-black with an acid yellow-green. Teal on a pale field. Beside them: cream, a clay accent, and a
  serif display as one package; violet-to-blue gradients, a halo behind the hero, and glow on dark.
- **Reads as generated because** the color came with the category (calm green for care and safety, indigo for
  software, acid for anything young) rather than from the subject, and swapping one family for another is the same
  preset. Green has become a default of its own: it arrives on software, transit, shops, and wellness alike because
  it feels safe and fresh, not because the subject is green. A brand green is also a status color, so a green
  "protected" chip stops meaning anything.
- **Instead.** Take the field and the accent from `world_materials`: the subject's objects, paper, packaging,
  places. Give the accent the one role the page needs it for. Build two palettes from different materials and
  compare them on the page's own content. Keep status colors apart from the brand accent.
- **Exceptions.** A brand that owns its color. A subject that is green, teal, or paper. A genre that owns its
  pairing (a club night, a music release, a game). Light as the subject.
- **Rules.** `color.sage-soft-field`, `color.violet-indigo-accent`, `color.acid-on-black`, `color.teal-accent`,
  `color.cream-base`, `color.terracotta-accent`, `color.warm-editorial`, `color.violet-blue-gradient`,
  `color.hero-halo`, `color.neon-glow`, `color.dark-luminous`.

## Type and headline treatment

- **Looks like.** One neutral sans for every role. A small tracked capital label above most headings. One word or the
  closing phrase of a title in the accent color, in a gradient, or in an italic serif; a line, a break, and then the
  phrase in italic or another typeface. A colored full stop or glyph at the end of a heading.
- **Reads as generated because** the label repeats the title or fills a slot, and one emphasized word stands in
  for a title that does not say what is different. A neutral sans is often right; what reads as default is that no
  role was compared. A rendered page can also show a container's fallback face rather than a choice, so check
  what rendered before judging.
- **Instead.** Let the title carry the proposition in one voice. Check a plain label or chip directly above the
  first-view title even when it appears once. Keep it only with the rule's `keep_when`: real category, scope, dates,
  authoritative state, or a process step absent from the heading, not a topic echo or a slogan. Exhibition type and
  dates or a live status can earn that place. Give an accent color a role the reader can name, and change type
  inside a title only for a title, quotation, or term. Compare display and reading faces on the page's copy.
- **Exceptions.** A real ordered process, an exhibition type, a service name. A word colored for a state it
  encodes. A neutral body face chosen for readability on the platform.
- **Rules.** `type.eyebrow-kicker`, `type.heading-badge`, `type.headline-emphasis-formula`, `color.gradient-headline`,
  `type.single-neutral-sans`, `type.overused-neutral-grotesque`, `type.serif-luxury-display`, `type.font-fallback`.

## Headlines and wording

- **Looks like.** Headings built as two short sentences ("Your files. Safe, always."), often with a quantity
  ("A little backup. A lot of calm."), a negation ("Built to be there. Not in the way."), or a "less, more" pair,
  on the title and again on three or more section headings. Comfort vocabulary (peace of mind, worry-free, life
  happens, breathe easy; in Korean, 마음 편히, 걱정 없이, 건강한 일상). Trial terms stacked under each button (a free
  trial, no card, cancel anytime). Round, precise proof: 99.9% uptime, 10,000+ teams, 4.9/5, a row of logos. A brand
  invented from one safety vocabulary.
- **Reads as generated because** the cadence and the nouns swap between products without changing the sentence;
  precise numbers imply a measurement nobody made; stacked terms promise commitments nobody set; a feeling is
  promised where the outcome could be named.
- **Instead.** Give each heading one fact in whatever shape that fact has. Name what is kept, when, and how it
  comes back; let the comfort follow. State the terms the business has, once, beside the action they qualify.
  Use sourced numbers, and say once that sample data is sample data (see "What the page says about itself").
- **Exceptions.** A campaign line the brief fixes. Real terms and measurements. A fictional exercise name. A
  contrast that corrects a real misconception.
- **Rules.** `copy.uniform-rhythm`, `copy.stock-reassurance`*, `copy.template-offer-terms`*,
  `copy.fabricated-proof`, `copy.contrast-frame`, `copy.placeholder-content`, `copy.name-swap`.

## What the page says about itself

- **Looks like.** A notice that the page is a demo or uses fictional data, in the hero, under a heading, beside a
  form, in an answer of the questions list ("Does this demo upload my files?"), and again in the footer, each time
  in new words; a "Demo", "Live preview", or "Concept" badge on the mock and in the logo line; "not a real
  exhibition" under the title. Sentences that explain the page instead of its subject ("This section shows...",
  "Click the button below to try it"). A flow that narrates its next step ("In the next step you will enter your
  details", 다음 단계에서 정보를 입력합니다) instead of asking for it. Narration of what changed ("We updated the layout",
  "the spacing has been improved"). Developer and test notes ("test data only", "replace with real content"). An
  apology for a part nobody built ("not available in the demo"). Korean and Japanese pages do the same in their own
  register (이 페이지는 가상의 …입니다, このページは架空の…です).
- **Reads as generated because** the writer addressed whoever asked for the page and not the visitor, so the page
  keeps explaining how it was made. The visitor of the exhibition came for the exhibition and the visitor of the
  shop for the sweets; every notice is a sentence about something else, and each repeat weakens the one that
  matters.
- **Instead.** Before writing a line, decide what the page has to show - the subject and the visitor's task - and
  what it must not carry: how it was made, that it is a demo beyond one notice, what changed since the last
  version, what the next screen will ask. Let the control, the field label, and the step title do that work. When
  the brief requires a notice, write it once, short, in a quiet place: the footer or a small persistent label.
  Never put it in the hero, a heading, or beside each section. A notice and its translation beside it are one
  notice. The rest of a demo's limits belong in the handoff, not on the page.
  For a dot-separated strip, ask what changes in the visitor's decision if it goes. `조각 · 설치 · 공간` and
  `FORM · SPACE · STILLNESS` repeat the page topic; remove them or justify a real filter with `decision-metadata`.
  Route/date/direction, chart scope and units, artwork artist/year/material/dimensions, and source/byline records
  qualify facts rather than decorate a topic. Keep those facts beside the object they describe.
- **Exceptions.** A consequential disclosure the visitor needs where they decide (a simulated payment, a form that
  sends nothing while the visitor may type private details), said once there and not again. A version or build
  label where compatibility depends on it. A brief that gives the notice's wording.
- **Rules.** `copy.meta-text`, `copy.decorative-metadata`, `copy.placeholder-content`.

## Icons and imagery

- **Looks like.** A set of thin rounded inline icons; cloud, shield, lock, and vault repeated as proof; check, star,
  and sparkle glyphs standing in for icons; an arrow on every button; pictures assembled from CSS shapes (leaves,
  a calendar, a building, a chair by a window).
- **Reads as generated because** the symbols assert protection or care without showing a mechanism, and the
  drawn scene is the category's scene, not this clinic's or this shop's.
- **Instead.** Use one maintained icon family for recognizable actions and label icon-only buttons. Show the
  mechanism: what is copied where, and when. Draw custom artwork only for subject concepts the family lacks, from
  the subject's real objects.
- **Exceptions.** One coherent icon system. A glyph that speeds recognition. Arrows for a real direction or an
  external destination. Art-directed illustration the subject earns.
- **Rules.** `component.emoji-icons`, `component.hand-drawn-icons`, `component.mixed-icon-families`,
  `imagery.css-illustration`, `imagery.generic-stock`.

## Data and fixtures

- **Looks like.** The same invented files (brand assets, project notes, a proposal, a quarterly report), tidy sizes,
  and "Synced" on every row. A dashboard of sidebar, top bar, four equal metric cards, and a chart; the cards count
  what is in service (vehicles running, routes open) and nobody acts on the count. A chart with no question.
- **Reads as generated because** every product of the kind shows the same demo, so the page cannot show what is
  hard about this one. A total fits a hero or a report; on a console it takes the first view from the exception.
- **Instead.** Write fixtures from the domain and the scenario: long, local, and awkward names, mixed states,
  versions that differ in a way you can read. Choose what to quantify from the decisions the operator makes: what is
  late, full, or failing, the next arrival, the queue against its limit. Put that first and promote the record or map
  it needs; a number earns a tile when a decision hangs on it and shows its limit or change. A chart states its
  question, period, and units, or a sentence replaces it.
- **Exceptions.** A dashboard the task asks for. Real series. Documentation that needs realistic names.
- **Rules.** `layout.typical-composition`, `layout.card-everything`, `layout.metric-tile-opening`,
  `copy.placeholder-content`, `component.fake-app-window`.

## Motion

- **Looks like.** Idle floating and pulsing, looping decoration, a reveal on every section, a zoom on every image
  on hover.
- **Reads as generated because** motion performs liveness instead of marking a change of state.
- **Instead.** Move at the state change or the subject's moment, keep reading stable, honor reduced motion.
- **Exceptions.** Real progress, live status, a scene the brief earns with a control to stop it.
- **Rules.** `motion.ambient-loops`, `motion.pulse-without-status`, `motion.scroll-gated-content`,
  `motion.hover-zoom-everything`.

## Per-genre packages

A package is a set of defaults that arrive together for a kind of page. Several findings on one package are one
decision. These are small corpora and many prompts named the style; read them as warnings to check, never as
forbidden genres.

- **Cloud backup, security, and similar software.** Split hero with a mock and floating panels, a trust strip, the
  section order above, three plans with a recommended middle, a closing banner, comfort wording, green or indigo.
  The counter-package that worked: a restore-first opening, a title naming the time or version restored, and a
  real record (a timeline, a timestamped panel) in the first screen.
- **Korean appointment booking.** Sage form, calendar, and summary column; a warm headline in place of the plain
  task title; small English labels over Korean headings; a leaf or calendar picture; a flow that tells the next step
  in prose. Name the task, show availability and recovery states, take character from the clinic, and on phones run
  it as one step per view with the choice so far kept in sight (`archetypes.md`, Genre structures).
- **Operations dashboards.** Sidebar, top bar, a row of total tiles, equal panels, chart; the sidebar and top bar
  still there on the phone. Lead with the failure, route, or arrival the operator acts on, quantify what a decision
  needs, and give the phone its own order.
- **Editorial features.** Paper field, serif display, a red accent, a line illustration of the subject, a headline
  with its last phrase in italic. Follow the publication's own structure (masthead, headline and deck, byline and
  date, lead, body in running text; for news, a front page by news value) and let the reporting (places, figures,
  quotations) set the picture.
- **Exhibitions.** Geometric stand-ins for the artworks in a split opening. Lead with the visit (dates, place, hours,
  admission) and the works themselves, authorized, or frame the picture as illustration.
- **Japanese craft shops.** Seasonal one-line slogans, soft paper, modeled sweets on a plate, vertical captions.
  Genre-earned; check kana and Han faces in the rendered page and use the shop's actual products and constraints.
- **Music and sound catalogs.** Hardware nostalgia, a pastel three-pack, a bundle, a free sample. Order by what the
  sounds are, what they run on, and how they are licensed.
- **Dental and care sites.** Calm serif, cream and green, a chair and a plant, a price list, clinician cards.
  Lead with the visit decision, fees, and availability.
- **Reading apps.** A collection rail over warm book covers. Lead with reading state, import, and annotation.
- **Nightlife and period styles.** Gold on emerald or black, arches, a cocktail. Compliance with a brief that names
  the period is not a default; check that the venue's menu, view, and booking terms set the order.
- **Acid and chrome releases.** Black and acid, a floating chrome object, a ticker. Keep playback, reading, and
  narrow-layout access ahead of the material.
