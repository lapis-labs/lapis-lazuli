# Product lifecycles

Use this file for role-aware adoption and exit, AI-assisted work, moderation, or support handoffs.
Reuse the existing plan's `flows` and `claims`; `forms-and-recovery.md` owns confirmed, failed,
partial, unknown, retry, and consent semantics. `notifications-and-attention.md` owns delivery.
These are design questions and manual acceptance paths, not new probes or product capabilities.

## First value, return, and exit

Define first value as a useful outcome recognized by the actor, then repeat value under the job's
natural cadence. Signup, tour completion, invitation count, and return visits are not that outcome
by default. Name the goal, observable signal, counter-signal, and evaluation window before a metric.
A naturally episodic service may succeed without frequent return; inactivity is no permission to
contact someone or infer dissatisfaction.

For an iteration decision, define eligibility/exposure, numerator and denominator, time window,
exclusions, segments and known blind spots before reading results. Keep task outcome separate
from diagnostic, operational and harm/access guardrails; more clicks, time or return visits can
mean friction. Changing exclusions or attribution after seeing results is exploratory analysis,
not the original test.

Preserve existing event meaning during visual changes. A client attempt, server acceptance and
authoritative completion are different events; a screenshot or handler declaration cannot prove
one correctly deduplicated result. The existing instrumentation owner exercises controlled paths
and checks missing/duplicate/delayed events, eligibility and concurrent release effects under the
supplied privacy policy. This guidance authorizes no new telemetry or live experiment.

Analytics can locate frequency and sequence, not explain motivation; studies can expose a mechanism,
not population prevalence without suitable sampling. Review outcome and guardrails together at
the product's natural cadence, accounting for outages, seasonality and exposure. Do not wait for
a metric to repair an already reproduced consequential task or accessibility failure.

Give owners, contributors, and reviewers paths to their own outcome. A shared task may need another
person; explain whose participation and authority are needed, preview the invite, and preserve work
when it expires or is declined. Do not require contact import. Returning actors need current role,
valid pending work, material changes, and direct resume—not a replayed welcome tour.

Pause, downgrade, cancel renewal, export, leave a workspace, delete data, delete an account, and
rejoin have different scopes. Use supplied policy for effective time, billing, retained/transferred
content, collaborators, pending jobs, and supported recovery. An export is not confirmed until its
scope and result are known. Missing policy blocks the new commitment depending on it, not an
existing approved exit. Preserve a direct exit and the skill's joining/leaving parity; a survey,
offer, or staffed conversation cannot become a retention gate.

## AI proposals and actions

Choose the work object's surface: inline field suggestion, selected-content diff, per-row review,
artifact editor, or an activity/result view. Conversation earns its place only when intent develops
over turns; accepted work remains findable through the normal product object model.

Keep provided input, generated proposal, tool observation, attempted action, and authoritative
result distinct. An attachment can be attached but unread, parsed but unused, truncated, or stale.
Show the actual source/selection and intended change scope; a citation supports its specific claim,
not the whole answer. No invented confidence percentage, cost, connector, background capability,
or “verified” badge replaces evidence. Separate insufficient evidence, policy refusal, operation
failure, and user stop so the recovery names the real barrier.

Stop prevents only the later work the runtime can prevent; it does not undo confirmed effects.
Retry repeats a failed stage, regenerate creates a new candidate, accept commits a named proposal,
and undo invokes a supported reversal. Preserve accepted human edits and per-item outcomes.
Approval identifies target, scope, consequences, and base revision; it is not server authorization.
Recheck identity, revision, role, and service authority at commit. Preserve a changed-base patch for
the supported conflict flow and renew approval when that changes scope or consequence.

Persist only the objects the workflow and policy require; deleting a conversation does not imply
accepted revisions, external effects, or audit records disappeared. Show durable background status
when supported, keep stop reachable, retain focus while streaming, and announce meaningful
milestones rather than every token. Exercise wrong-but-plausible output, stale/unread input,
stop during an operation, partial results, rejected approval, and save conflict with synthetic data.
The built-in probes establish neither AI output correctness nor provider/tool execution.

## Reports, personal controls, and moderation

A report asks for policy review; block, ignore, and mute affect personal interaction or delivery;
enforcement changes the service's policy state. Preview confirmed effects by surface—including
shared spaces, search, previous threads, and reversal—rather than promising universal invisibility.
Policy findings, system receipt/action state, and what the current person may see remain separate.
Report count, automated category, and prior allegations are not guilt.

Use the supplied policy version, action scope, confidentiality exceptions, evidence/retention rules,
roles, escalation, and appeal support. Receipt means received, not reviewed or safe. Provide durable
notices and policy-supported appeal access even when normal access is restricted. A correction names
what is restored, dependent effects still pending, and the allowed audit history; a short undo window
is not an appeal process. Do not invent sanctions, response times, or emergency protocols.

Preserve relevant product context only when authorized. Do not force repeated exposure, indiscriminate
screenshots, or redistribution of harmful material. Use intentional reveal, not autoplay; keep report
text, identities, and sensitive evidence out of routine analytics and notification previews. Reviewer
recusal, reassignment, stale-case reconciliation, and drafts stay distinct from committed findings.
Bulk preview identifies all selected items and exceptions; show action and notice outcomes separately,
retry only safe failures, and verify downstream restoration rather than assuming it propagated.

## Help and service continuity

Choose the lowest capable layer: contextual correction for a known safe fix, an explanation for a
stable requirement, self-service for an inspectable procedure/status, and staffed support for actual
discretion or protected intervention. An assistant must disclose its limits and offer a real exit.
Closed or absent support is not live chat; show only supplied hours, charges, and expectations.
An unknown outcome goes to authority reconciliation before retry, never generic troubleshooting.

When a request moves, preserve goal, object/scope, known state, attempted actions and confirmed
results, minimum authorized context, next responsible actor, and a real route back. Show recipients
and optional material before transfer; consent to one recipient does not authorize all later sharing.
If transfer is impossible, provide a safe copyable summary and distinguish old/new requests rather
than pretending the recipient sees history. Never request secrets or send full logs by default.
Contact or an article sent is not resolution: name the confirmed outcome or durable terminal limit.
A prototype cannot prove staff access, message delivery, service capacity, or a response promise.
