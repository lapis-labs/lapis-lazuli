# Review before showing a draft

## Sections

- Presentation: bind every shown page to its source, render task, and affected widths.
- Evidence: observe the exact draft, dispose its findings, and have a fresh critic judge it, without a release rerun.
- Critic packet: what the critic is given, what makes its report count for this draft, and when a delta review is enough.
- Owner report: the summary the CLI writes for the owner, the full block it links, not a summary of your own.

## Presentation

Before asking the owner to look at or approve a rendered page, write `.lapis/drafts/<task>.yaml` (`version: 1`)
against `../shared/release/draft.schema.yaml`. `pages` lists every page linked in the questions file,
including comparison pages if the owner is asked to judge them. A page under `.lapis/specimens/`
can be the actual draft: location does not exempt it. Each entry names its exact `url`, the
`render_task` used for its extracts, its `sources` (the HTML and the styles/scripts it depends on),
`direction: new|iteration`, changed `area`, `widths`, and whether `behavior_changed`. A linked address on this
computer has to answer HTTP 200 when you ask: serve the folder with `lapis-design preview start --task <task>`, a
server that keeps running after the command that started it, and capture that address; `next` does not wait on a link
that answers nothing.

A new direction uses 390 and 1440. A small iteration keeps that direction and reviews only the changed
area and affected widths; keep previous evidence for unchanged areas. A new structure, locale, or
interaction refreshes its affected evidence. A pure question about the brief or contract shows no
rendered draft and needs none of this. Add pages before collecting evidence; add `review` afterwards.
A version 0 record carries maker prose (`summary`, `making_of`, `walkthroughs`, `claim_evidence`,
`critic.context`, `critic.independent`, `resolution_kind`) that nothing reads any more: rewrite it as
version 1, which keeps only what the CLI and the critic can check.

### Evidence links are not pages

A local link in the questions counts as a shown page that needs its own review, whatever it points at. A link the owner
is shown as evidence for a page (a type specimen, a reference capture, a `?query` variant of the shown page) is declared
in `supporting` of the record instead, as `{kind, link, path, claim}` (`specimen`, `reference-capture`, or `query-variant`):
`link` is the address as the questions show it, `path` the project file that carries what the claim says (for a variant,
a capture of it, newer than the page's sources), and `claim` what the file shows. A query variant also names the shown
page it varies, `page: <url of that page's entry>`, and is evidence only for that build. `draft check` records each file's
hash, the critic packet lists the file and the claim to the critic, and the link is not reviewed as a page. Evidence
does not make approval: a link to a page of the record, to an alternate direction or state you ask the owner to approve, to
a source of a shown page, or to a file that is not there is a problem, not evidence, and a link that is not declared is a
shown page as before. A file edited after the review makes the review and the critic's report stale.

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
   Review the page's findings against its actual captures. For each `open` finding (a `fixed` or `waived` one the check
   itself closed needs no entry; a skipped one is not checked) write a `handled` entry with its report path, zero-based
   `finding` index, `disposition` (`fixed`, `justified-keep`, or `unresolved`), reason, and capture/box/source `refs`.
   `draft check` lists every open finding still without one in a single message, with the entry to add. The reason is for
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
   giving it that packet and the files it lists, and record `review.critic.report`. A page that moves (an animation, a
   box that moves at rest, or one hidden until scroll) needs its motion recorded from the same build first:
   `lapis-design render motion <url> --task <task> [--lang <tag>]`, once for each locale shown, writes the scripted-scroll
   playback, settled and reduced-motion captures at 390 and 1440, and the pinned scenes' content and runway
   (`../shared/render/motion.schema.yaml`); the packet refuses a moving page without it, or with a recording of another
   build, and the critic judges each pinned scene by content and dwell. The critic's task carries the delegated-work rules
   (`../shared/review/worker-rules.md`), which `critic packet` prints; run `lapis-design worker check --task <task>
   --transcript <file>` on each delegated agent's transcript you can read, and tell the owner what you could not check.
   Dispose its findings too. If
   none ran, the draft is not reviewed; report the missing prerequisite, never invent a pass. A small iteration
   needs no critic; one attached to it is checked the same way. When the owner's reply only changes requirement rows, the
   delta below is enough for the next review of the same build.

## Critic packet

The packet is deterministic JSON (`../shared/review/critic-packet.schema.yaml`): the owner's requirement rows, the plan's
design fields without your reasons, a digest of every file the critic may read, the lint findings, the edits to
protected plan fields that were reactive, touched an open finding, or came after the owner approved the slice, and your
disputes without their reasons, the decisions the owner has not made, the asks put to the owner during the work, and the direction conversation with its ids resolved (each item's option texts, who chose, the
owner's pick among the rough first views). The critic's report names it in `target.packet` (`path` and `sha256`), and a report
counts only for that packet: the CLI rebuilds the packet from the arguments it records. A changed capture, lint report,
requirement row, protected plan value, or change row, and a packet rebuilt after the critic ran, make the report stale,
so rebuild the packet and run the critic again. An edit to something the packet leaves out (a reason you wrote, the
concept, a layout field it does not carry) does not.

The report must also judge every requirement row, every listed change, and every dispute exactly once, cite only files
that exist, and quote facts that are in the lines it cites. For a new direction it holds a walkthrough at every shown
width. This proves which inputs the critic was given, never what it read or that it was independent.

### A delta review after an owner's reply

When the owner's reply changes or adds requirement rows (the record, its change rows, a dispute) and nothing else on the
same shown build, the critic need not read everything again. Run `lapis-design critic packet --task <task> --prior
<its last report> --out .lapis/critic/<name>.delta.packet.json`: the delta packet lists only the new and changed rows
(with the owner's words on them), the changed change rows and disputes, the prior report's findings those rows affect
(every open core finding among them), the digest of the prior report, and the unchanged evidence by digest. The prior report
must be a full report that judged its own packet completely, and stays byte for byte as it was. The critic judges exactly
what the delta lists, and writes a finding with `supersedes: <the prior finding's index>` for each prior finding it
re-judges: an open core finding stays open as a core finding, or is `fixed`. The prior report and the delta report count
together as one review of the whole when all of that holds (`draft check` and the slice seal accept them, and read them as one
report). Any other change (a screenshot, a state, a locale, the lint report, a plan or direction field, the implementation,
the critic's rules, the packet format) makes the command refuse and say what changed: that is a full review, as before. The
release's critic is always a full review of its own packet: a delta, or a report that follows one, never counts there.

The critic reports the outcome of each requirement row (`met`, `partly`, `missing`, `not-in-slice`, `not-observable`),
every factual sentence of the shown copy with its source, a verdict on each change, a verdict on each dispute, and its
own visitor walks. Whether visible text describes this page's own making (its font choices, palette, layout
decisions, or compliance with the procedure) is its finding `review.making-of`: product copy addresses the visitor's
subject and task, and design rationale belongs in the plan unless a requirement asks for it on this page.

A core product-explanation finding (`approval_impact: core-product-explanation`, including `review.world-materials`
unless the critic marks it ordinary) that is still open in the current critic report no longer blocks showing: the owner
summary lists it among the defects (the block under `## Open core findings: your decision`), and you put it to the owner as a decision in the approval
question. The slice is not sealed while it is open and undecided: a fresh critic report that no longer reports it open
closes it (after real product output resolves it; a settings display, a partial fix, or a candidate button is not that
repair), or the owner decides it and you record `- [declared] Ask finding-vs-decision: <rule id> — <their words>`.

`lapis-design draft check --task <task>` validates this narrow record. `next` will not turn a draft approval question
into `waiting-for-user` until it is current. Editing a shown source invalidates its evidence; refresh only the affected
area. The unattended exit gate requests this step; an attended gate warns and records the unreviewed stop without
taking away the person's ability to stop. Neither case calls the draft a release.

## Owner report

The owner reads the summary `draft check` and `next` write to `.lapis/owner/<task>.summary.md` (`owner_summary` in `next
--json`), not one you wrote: paste it into the questions file unchanged, including its `lapis-owner-block` line. It carries
one `Decision:` line, what the owner's last reply changed, every decision you have not made, every defect of the shown build,
every font role with its source and license, what was shown, and the path and digest of the full block
(`.lapis/owner/<task>.<sha8>.md`), which the owner reads by link. A file that drops one of those lines, or asks twice, comes
back to this step with what is missing. The block names the exact pages and widths, the
capture files of those widths (and, for a plain static page, the HTML file) that open without a server, the
requirement outcomes, the facts with their sources, the protected changes, your disputes beside the critic's verdicts,
and what did not run. List unresolved findings before requesting approval, and distinguish actual playback from captures
and source inspection. Check totals and zero blockers are not design quality or approval. Full widths/probes, rights
and license checks, and full token enforcement remain at release.
