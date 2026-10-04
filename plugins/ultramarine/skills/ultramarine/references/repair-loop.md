# Repair loop

## Enter for an observed finding

| Decision | Plan field or record | What checks it |
|---|---|---|
| Repair only the requested surface and retain its obligations | `mode`, `brief.constraints`; authorization in the user report | Not checked: these fields do not authorize editing or enforce a loop |

Use a loop when repair is requested, a finding remains open, and an available check can observe the property after editing. A review request alone permits inspection, not changes. Reuse the finding's evidence and the user's account; do not repeat a reported failure merely to establish that it happened.

A `skipped` finding asks for evidence, not a speculative repair. Run its missing check first. If an authorized correction is useful but no runnable check observes the property, make one fix, report its effect as not verified, and do not loop. A preference with no rule or agreed criterion belongs to the user's decision, not repeated attempts to satisfy the maker's taste.

## Record the target before editing

| Decision | Plan field or record | What checks it |
|---|---|---|
| Keep the disappearance condition and protected behavior fixed | `brief.constraints`; finding and comparison conditions in the user report | Not checked: no rule validates this repair record |

Write the finding id, location and state; the check and observation that would show it gone; what must continue to pass; and whether an unsuccessful candidate will be reversed. Use the existing report rather than inventing another ledger. Include the content, locale, theme, input and width needed for a meaningful comparison. Protect relationships as well as values: a repair can retain a palette yet destroy the distinction between a primary action and a supporting detail.

For a seed library's exchange screen, the target might be a recovery action covered by a fixed summary. Preserve the selected seed varieties, reading order and saved selection. For a chamber ensemble's programme, the target might be captions escaping the reading column. Preserve the distinction between movement titles and performer credits. These are different repair scopes, not invitations to restyle both surfaces.

## Spend a finite budget

| Decision | Plan field or record | What checks it |
|---|---|---|
| Set the task bound and count attempts against the same finding | User report; no plan field for a repair budget | Not checked: the checks do not count rounds or critic calls |

Unless the user specifies another bound, allow at most three rounds for the task and two fixes for a finding. Never extend the bound yourself. A round contains one diagnosis, one coherent correction for one cause, and one rerun of the narrowest check that observes it. Supporting edits may serve that cause; unrelated cleanup does not belong in the candidate. Use the independent critic at most twice, including the final review, rather than after every value adjustment.

The pilot repeatedly returned to enlarged-text wrapping through critic, fix and recheck without a rule that measured that property. Repetition did not establish closure. The limit prevents that failure mode; it is not a quality measure. When no rule observes the appearance at issue, make one correction and reserve the critic for the end. Report any unsupported outcome as unverified even if the final review supplies useful visual judgment.

## Refine a direction once

| Decision | Plan field or record | What checks it |
|---|---|---|
| Read the rendered direction once, refine it once, then stop and report | `direction.concept`, `direction.levers`, `layout.signature`; the user report | Not checked: no rule counts direction passes; the critic reads the captured appearance against the plan |

A new visual direction has no check that says it is finished, so taste can keep a loop open for ever. Bound it. Once behavior and the responsive facts hold on a render, read that render one time against the written concept and the visitor's task: hierarchy, rhythm, type, contrast, feedback, and what remains of the defaults. Make one refinement pass over everything that read names, and rerun the narrowest render once. Then stop. Report what still looks unresolved as findings, each with its place, what was seen, and what would decide it, and leave the choice to the user instead of starting another round. The pass spends one of the task's rounds; it is never an extra one.

A defect that a rule or the brief names is not part of this pass and follows the budget above. A preference only the maker holds is not a finding to iterate on, and a surface that the project's contract or an approved design already fixes is not a new direction: it gets no refinement pass, and a restyle of it needs the user's approval.

## Select the observing check

| Decision | Plan field or record | What checks it |
|---|---|---|
| Match the rerun to the changed decision, then restore full coverage | Changed plan field; `.lapis/renders`, `.lapis/behavior`, `.lapis/lint`, `.lapis/critic` reports, and their `<task>.narrow.json` files | `release.input-stale` reads dependency modification times; `release.width-missing` reads extract viewports; `release.probe-incomplete` reads session coverage; `release.layer-missing` reads lint targets and scope; the gate reads only the full-path reports |

A plan correction needs `plan check`. A style correction at a captured width needs `render check --width`, then lint with `--layer render --rule <id>` and that extract. An interaction correction needs `behavior check --probe`, then lint with `--layer behavior` and that session; when the finding names a box, add `--box <id>` (the finding's `location.box`, a key of the session's `nodes`) so the probe leaves the other controls alone, or `--limit <n>` to cap them. A source-only correction needs lint with `--layer source`. A font correction needs `plan check` and lint with `--lock` pointing to the updated lock. Pass the other inputs that the chosen detector needs; narrowing does not remove its dependencies.

Inner rounds write beside the full reports, never over them. `render check --width` and `behavior check --probe`, `--context`, `--box`, or `--limit` write `.lapis/renders/<task>.narrow.json` (screenshots in `<task>.narrow.shots/`) and `.lapis/behavior/<task>.narrow.json` without being asked, and refuse the full path. Give the narrowed lint `-o .lapis/lint/<task>.narrow.json` and point its `--extract` and `--session` at the `.narrow.json` files. A selected width leaves other widths absent from the narrowed extract; selected probes leave the others `skipped`; `--box` and `--limit` leave the probe's coverage `partial` with the count of boxes left out; selected lint layers or rules leave a narrowed scope. Absence in a narrowed report does not establish a new defect or erase an earlier one, and the full reports from before the loop stay as they were, stale until the final run replaces them.

After the last round, run the full applicable set once, in order: render, behavior for an interactive surface, lint with every available input, then the independent critic. Do not narrow this final run: it writes the full reports at the task's own paths, which the release gate reads. The critic needs the extract and lint report; host-browser viewing cannot substitute for those inputs. The release checks describe missing or stale evidence, not the merit of the repair itself.

## Decide from each result

| Decision | Plan field or record | What checks it |
|---|---|---|
| Retain, reverse, continue or stop from the actual observation | User report; changed plan fields remain the owning decisions | Critic reads captured appearance and plan intent; candidate disposition is not checked |

Stop when the target is gone and nothing previously passing now blocks. If it improves but remains, continue only when the new observation supports a different cause and the bounds permit another attempt. If it disappears but a protected condition fails, reverse only your attributable edits. Preserve concurrent work. Distinguish reversal in source from restoration actually observed on screen.

Stop when candidates alternate which condition fails, produce no useful new information, exhaust the rounds, or lose the observing check. Unspent rounds are not a polishing quota. Do not hide the symptom, disable a rule, or change the disappearance condition to fit the easiest edit.

## Leave unresolved findings open

| Decision | Plan field or record | What checks it |
|---|---|---|
| Report an unresolved cause without manufacturing a waiver | `claims.unresolved`; finding `status` remains `open` | Lint reports a finding again when its detector still hits; the claim's explanation is not checked |

After two fixes leave the finding open, send both attempts and the suspected cause to the user. Add the unresolved line before the final full run: a later plan edit can make dependent reports stale. A `defaults` keep entry needs a justified decision about a default; it is not a way to end an unsuccessful repair. Requirements cannot be waived.

## End with coverage and a handoff

| Decision | Plan field or record | What checks it |
|---|---|---|
| Separate remaining defects, missing checks and user decisions | `claims.unresolved`; lint `scope.layers`, finding `skip_cause`, session `coverage`; user report | Lint creates `skipped` findings with `not-verified` evidence; release checks inspect report coverage, not the completeness of the handoff prose |

Finish with three lists: defects still present; checks that did not run and each reason; decisions the user must make. A missing input or unavailable browser is not a defect to repair. For each handoff item, name its location, evidence kind, attempted corrections, required decision and the check that could distinguish the remaining causes. State which candidate remains applied and what was actually observed. Never report an unrun check as passed.
