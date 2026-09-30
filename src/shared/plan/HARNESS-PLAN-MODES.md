# LapisLazuli plans and harness plan modes (v0)

Many harnesses have their own plan mode. This guide keeps the LapisLazuli plan file compatible
with them. Skills read this file as a reference; the rules below are what the agent follows.

## Two plans, two jobs

| | Harness plan | LapisLazuli plan |
| --- | --- | --- |
| Format | Markdown, owned by the harness | YAML, `src/shared/plan/schema.yaml` |
| Job | Workflow: read-only exploration, steps, user approval before edits | Design contract: brief, direction, tokens, layout, defaults decisions, references |
| Location | Wherever the harness keeps plans | `.lapis/plans/<task-id>.yaml` |
| Checked by | The user, at approval | `plan_check`, then `ultramarine` |

Never replace one with the other. The harness plan carries the LapisLazuli plan inside it while
writes are blocked, and the LapisLazuli plan file becomes the single source once execution starts.

## Rules

1. **Embed while in plan mode.** Plan modes block or discourage file writes, so write the
   LapisLazuli plan as a fenced block inside the harness plan. Mark it so tools can find it:

   ````markdown
   ```yaml lapis-plan
   # lapis-plan: .lapis/plans/kiln-shop-landing.yaml
   version: 0
   mode: create
   ...
   ```
   ````

2. **Summarize above the block.** Put a short human summary right before the block so the user
   approves decisions, not just YAML:
   `lapis-design plan check --from-markdown <harness-plan.md> --summary` (or a plan file in place
   of `--from-markdown`) prints one (job, Design Read, dials, world materials, signature, type
   roles, references with rights, defaults decisions). A plan that fails the schema gets the
   findings report instead, and a summary does not mean the plan has no blocking findings.

3. **Validate before approval when the harness allows it.** Run
   `lapis-design plan check --from-markdown <harness-plan.md>` (read-only, `-` reads stdin). Where
   commands are blocked in plan mode, rely on the harness hook below or run it as the first
   execution step.

4. **Standard execution steps.** The harness plan's step list starts with these, in order:
   1. Write the block verbatim to `.lapis/plans/<task-id>.yaml`
   2. `plan_check` (stop on blocking findings)
   3. Implement
   4. `render_check`
   5. `slop_lint` and the critic
   6. Release gate (for shipped work)

5. **Keep one source after approval.** After the file is written, decisions change only in the
   YAML file. If execution forces a change, update the file and tell the user; do not let the
   harness step list and the YAML drift apart. Step-list tools (for example Codex `update_plan`)
   mirror execution steps only, never design decisions.

6. **Re-planning.** When entering plan mode again, read the existing LapisLazuli plan for the same
   task first. Continue it if the task is the same; start a new task id if not. Always rewrite the
   embedded block before submitting the plan, so an old plan is never shown as the new proposal.

7. **Cross-link.** The embedded block's first comment names the target path. After writing, the
   YAML may record the harness plan location in `x-harness-plan`.

8. **Keep directories apart.** Do not point a harness plans directory at `.lapis/plans/`; harness
   markdown and LapisLazuli YAML stay in separate folders.

## Per harness

| Harness | Plan mode | How it fits |
| --- | --- | --- |
| Claude Code | Read-only plan mode (`/plan`, Shift+Tab); the plan is markdown saved under `~/.claude/plans/` or a project `plansDirectory`; `ExitPlanMode` asks for approval | Embed the block. The `lapis` plugin registers a `PermissionRequest` hook on `ExitPlanMode` (`lapis-design hook exit-plan`) that denies when the block has blocking findings or cannot be read or checked, and never approves on the user's behalf |
| Codex | `/plan` mode proposes a plan without writing; `update_plan` is an opt-in step list | Embed the block in the proposed plan; mirror only execution steps in `update_plan` |
| Oh-My-Pi | Plan mode (toggle) with read-only tools; the plan lives in session storage and is submitted for approval, then executed from the approved plan | Embed the block in the plan; write the file as the first step after approval |
| pi | No built-in plan mode; community extensions add a read-only `/plan` | With an extension, embed; without one, write the YAML directly and ask the user to approve the summary before implementing |
| Hermes Agent | `/plan [task]` writes a markdown plan to `.hermes/plans/` without executing | Embed the block in that plan; write the file when execution starts |
| Others | Varies or none | Write the YAML directly, run `plan_check`, and ask for approval of the summary before implementing |

## Why a gate even without plan mode

`lapis` asks for approval at the plan point in every harness: the summary plus the blocking
findings from `plan_check`. Plan modes make that gate structural where they exist; the skill makes
it behavioral where they do not.
