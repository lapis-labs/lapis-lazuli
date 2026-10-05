# Review before showing a draft

## Sections

- Presentation — bind every shown page to its source, render task, and affected widths.
- Evidence — observe the exact draft and dispose its findings, without a release rerun.
- Claim-to-evidence map — distinguish actual product output from this site's study and missing proof.
- Owner report — summarize what was reviewed and what remains, not a quality score.

## Presentation

Before asking the owner to look at or approve a rendered page, write `.lapis/drafts/<task>.yaml`
against `shared/release/draft.schema.yaml`. `pages` lists every page linked in the questions file,
including comparison pages if the owner is asked to judge them. A page under `.lapis/specimens/`
can be the actual draft: location does not exempt it. Each entry names its exact `url`, the
`render_task` used for its extracts, its `sources` (the HTML and the styles/scripts it depends on),
`direction: new|iteration`, changed `area`, `widths`, and whether `behavior_changed`.

A new direction uses 390 and 1440. A small iteration keeps that direction and reviews only the changed
area and affected widths; keep previous evidence for unchanged areas. A new structure, locale, or
interaction refreshes its affected evidence. A pure question about the brief or contract shows no
rendered draft and needs none of this. Add pages before collecting evidence; add `review` afterwards.

## Evidence

1. Capture the exact URL at each shown width with `render check --task <render-task> --width ...`.
   Open the screenshots. Record the extracts in `review.extracts`; different width-specific files
   are allowed. Extracts must name that page and render task, and their screenshots must exist.
   Extract URLs omit query strings for privacy: retain the presentation URL/locale in this review
   record and verify the rendered locale yourself; do not infer it from the stripped URL.
2. Run `lapis-design slop lint --draft .lapis/drafts/<task>.yaml --page '<shown-url>' --source .
   --plan .lapis/plans/<task>.yaml --extract <extract> -o .lapis/lint/<render-task>.narrow.json`
   from the project root (`--page` is optional with one page). Put its path in `review.lint`.
   Main findings/summary concern the shown page. `specimen_findings` holds other candidate sources,
   `deferred_findings` retains non-requirement token/rights enforcement for release, and
   `scope.draft.aliases` shows requested/rendered font names without treating an alias as a new face.
   Review the page's findings against its actual captures. For each non-skipped
   finding write a `handled` entry with its report path, zero-based `finding` index, `disposition`
   (`fixed`, `justified-keep`, or `unresolved`), reason, and capture/box/source `refs`.
   For core product-explanation findings, also record `resolution_kind`; settings and the site's
   design study are not actual product-output repairs. `review.world-materials` is approval-blocking
   unless the critic explicitly scopes it as an ordinary non-core detail. Do not downgrade a
   missing core explanation to a warning or a partial fix; other ordinary warnings stay ordinary.
   Fixes need observed evidence; a keep explains the actual page, not a new blanket waiver. Skipped
   checks remain not checked. Unresolved defects may be shown honestly; they never become a pass.
3. Walk one to three visitor tasks from the brief at each shown width. Record `walkthroughs`: task,
   viewport, first look, material read or scrolled past, where stuck (empty if nowhere), completion
   (`yes`, `partly`, `no`), and evidence refs. A screenshot alone cannot prove clipboard or submission.
4. Ask whether any visible text describes this page's own making: its font choices, palette,
   layout decisions, or compliance with the procedure. Record the observation in `review.making_of`.
   Product copy addresses the visitor's subject and task. Design rationale belongs in the plan,
   unless the brief explicitly asks for it on this page. A product about design can still describe
   its capabilities without replacing them with the implementation choices of its own website.
5. When behavior changed, add scoped smoke/behavior evidence in `review.behavior` with existing file
   refs and what was observed. Motion needs actual playback and its control feedback, interruption,
   and reduced-motion branch, not only a still screenshot. Copy/color-only edits do not rerun all flows.
6. A new direction needs one independent fresh-context critic. Follow `critic.md`, give it only the
   shown inputs, and record `review.critic` (report, context identifier, `independent: true`). Dispose
   its findings too. If none ran, the draft is not reviewed; report the missing prerequisite, never
   invent a pass. A small iteration reuses the direction's previous critic rather than rerunning it.

### Claim-to-evidence map

Before asking for approval, add `review.claim_evidence`: each brief-required claim/proof quotes
its `requirement`, names the actual visible example/output in `shown` (existing files, optionally
with a selector/box anchor), its `kind` (`product-output`, `site-study`, `not-shown`), its `state`
(`shown`, `partial`, `missing`), and the evidence still `missing`. Include component before/after,
process comparison, and real CLI output separately when the brief requires them. The critic checks
this map's completeness against the brief; the tool verifies citations and record consistency.

An interactive website design study can support the website's direction; it does not satisfy a
product-proof requirement. It stays partial/missing in that map, never shown/satisfied. Not every
secondary example must exist before a direction approval, but the report lists all missing proof.
A core product-explanation finding stays open until real results address it; showing current
settings or adding a candidate button is not the same repair.

Write `review.summary` after the checks and observations. `lapis-design draft check --task <task>`
validates this narrow record. `next` will not turn a draft approval question into `waiting-for-user`
until it is current. Editing a shown source invalidates its evidence; refresh only the affected area.
The unattended exit gate requests this step; an attended gate warns and records the unreviewed stop
without taking away the person's ability to stop. Neither case calls the draft a release.

## Owner report

Name the exact pages, widths, and changed area, summarize the visitor walk and findings as fixed,
justified keep, unresolved, or not checked, and include the independent critic's scope for a new
direction. Distinguish actual playback from captures and source inspection. List unresolved items
before requesting approval. Check totals and zero blockers are not design quality or approval.
Full widths/probes, rights and license checks, and full token enforcement remain at release.
