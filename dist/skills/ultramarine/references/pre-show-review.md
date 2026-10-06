# Review before showing a draft

## Sections

- Presentation — bind every shown page to its source, render task, and affected widths.
- Evidence — observe the exact draft, dispose its findings, and have a fresh critic judge it, without a release rerun.
- Critic packet — what the critic is given, and what makes its report count for this draft.
- Owner report — the block the CLI writes for the owner, not a summary of your own.

## Presentation

Before asking the owner to look at or approve a rendered page, write `.lapis/drafts/<task>.yaml` (`version: 1`)
against `../shared/release/draft.schema.yaml`. `pages` lists every page linked in the questions file,
including comparison pages if the owner is asked to judge them. A page under `.lapis/specimens/`
can be the actual draft: location does not exempt it. Each entry names its exact `url`, the
`render_task` used for its extracts, its `sources` (the HTML and the styles/scripts it depends on),
`direction: new|iteration`, changed `area`, `widths`, and whether `behavior_changed`.

A new direction uses 390 and 1440. A small iteration keeps that direction and reviews only the changed
area and affected widths; keep previous evidence for unchanged areas. A new structure, locale, or
interaction refreshes its affected evidence. A pure question about the brief or contract shows no
rendered draft and needs none of this. Add pages before collecting evidence; add `review` afterwards.
A version 0 record carries maker prose (`summary`, `making_of`, `walkthroughs`, `claim_evidence`,
`critic.context`, `critic.independent`, `resolution_kind`) that nothing reads any more: rewrite it as
version 1, which keeps only what the CLI and the critic can check.

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
   (`fixed`, `justified-keep`, or `unresolved`), reason, and capture/box/source `refs`. The reason is for
   the owner: the critic never sees it. A finding you believe is wrong goes in
   `.lapis/disputes/<task>.yaml` (`../shared/review/disputes.schema.yaml`) instead of into the disposition or
   the page's markup; the critic re-judges it on the captures, the owner sees both, and a dispute does not
   clear the finding. Fixes need observed evidence; a keep explains the actual page, not a new blanket
   waiver. Skipped checks remain not checked. Unresolved defects may be shown honestly; they never become a pass.
3. When behavior changed, add scoped smoke/behavior evidence in `review.behavior` with existing file
   refs and what was observed. Motion needs actual playback and its control feedback, interruption,
   and reduced-motion branch, not only a still screenshot. Copy/color-only edits do not rerun all flows.
4. A new direction needs a critic that did not make the page. Build its packet from the shown captures and lint
   report, `lapis-design critic packet --task <task> --extract <extract> --lint <review.lint> --out
   .lapis/critic/<render-task>.packet.json` (repeat `--extract` per file), run the critic as `critic.md` says,
   giving it that packet and the files it lists, and record `review.critic.report`. Dispose its findings too. If
   none ran, the draft is not reviewed; report the missing prerequisite, never invent a pass. A small iteration
   needs no critic; one attached to it is checked the same way.

## Critic packet

The packet is deterministic JSON (`../shared/review/critic-packet.schema.yaml`): the owner's requirement rows, the plan's
design fields without your reasons, a digest of every file the critic may read, the lint findings, the edits to
protected plan fields that were reactive, touched an open finding, or came after the owner approved the slice, and your
disputes without their reasons. The critic's report names it in `target.packet` (`path` and `sha256`), and a report
counts only for that packet: the CLI rebuilds the packet from the arguments it records. A changed capture, lint report,
requirement row, protected plan value, or change row, and a packet rebuilt after the critic ran, make the report stale,
so rebuild the packet and run the critic again. An edit to something the packet leaves out (a reason you wrote, the
concept, a layout field it does not carry) does not.

The report must also judge every requirement row, every listed change, and every dispute exactly once, cite only files
that exist, and quote facts that are in the lines it cites. For a new direction it holds a walkthrough at every shown
width. This proves which inputs the critic was given, never what it read or that it was independent.

The critic reports the outcome of each requirement row (`met`, `partly`, `missing`, `not-in-slice`, `not-observable`),
every factual sentence of the shown copy with its source, a verdict on each change, a verdict on each dispute, and its
own visitor walks. Whether visible text describes this page's own making (its font choices, palette, layout
decisions, or compliance with the procedure) is its finding `review.making-of`: product copy addresses the visitor's
subject and task, and design rationale belongs in the plan unless a requirement asks for it on this page.

A core product-explanation finding (`approval_impact: core-product-explanation`, including `review.world-materials`
unless the critic marks it ordinary) that is still open in the current critic report blocks the approval wait,
whatever your disposition says. A settings display or a partial fix leaves it open; it closes once a fresh critic no
longer reports it open, after real product output resolves it. Showing current settings or adding a candidate button is
not that repair.

`lapis-design draft check --task <task>` validates this narrow record. `next` will not turn a draft approval question
into `waiting-for-user` until it is current. Editing a shown source invalidates its evidence; refresh only the affected
area. The unattended exit gate requests this step; an attended gate warns and records the unreviewed stop without
taking away the person's ability to stop. Neither case calls the draft a release.

## Owner report

The owner reads the block `draft check` writes to `.lapis/owner/<task>.md`, not a summary you wrote: paste it
into the questions file unchanged, including its `lapis-owner-block` line. It names the exact pages and widths, the
requirement outcomes, the facts with their sources, the protected changes, your disputes beside the critic's verdicts,
and what did not run. List unresolved findings before requesting approval, and distinguish actual playback from captures
and source inspection. Check totals and zero blockers are not design quality or approval. Full widths/probes, rights
and license checks, and full token enforcement remain at release.
