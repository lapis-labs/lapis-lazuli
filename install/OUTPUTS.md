# Build outputs — v0

What the build (`tools/build`) emits from `src/` for each output in `install/harnesses.yaml`.
Reference code for the manifests, catalogs, hooks, and MCP files: `tools/build/manifests.py`.

`src/` is the only place people edit. Every output is generated and committed, because marketplace
installs read the repository as it is. CI regenerates into a temporary directory and fails when the
result differs from the committed files. JSON cannot carry a "generated" comment, so the sync check
is the guard.

## Versions and channels

One version per release, taken from the release tag, goes into every manifest, both catalogs, the
pi package, the Hermes plugin, and the Antigravity hook commands (its `plugin.json` has no version key). A plugin `version` pins Claude Code users until it changes, so
the build refuses to emit a release whose version equals the previous tag's. Codex caches plugins by
version as well.

Installs follow the `release` branch, which is moved by hand to each release tag (`{ref}` in
harnesses.yaml): the Claude Code and Codex catalogs are added at that ref, the CLI installs from it,
pi and the skills CLI read it, and Hermes pins its commit. Development happens on the default branch,
whose committed outputs may be ahead of the last release. Oh-My-Pi's catalog command takes no ref
that we could confirm, so it follows the default branch until that is settled.

## Skills — `flat-skills`, `plugin-skills`

- `dist/skills/<skill>/` holds `SKILL.md`, `references/` (one level), the shared views that
  `src/shared/index.yaml` gives that skill, under `shared/`, and the two license texts (see
  Licenses). Generators get the `names-and-alternatives` view of rules; `provenance` is stripped
  from every rule in every view.
- `SKILL.md` frontmatter keeps to the portable fields: `name` (equal to the directory, the slug rule
  in harnesses.schema.yaml), `description` (at most 1024 characters, trigger words in the first
  sentence), `license` (required, and equal to the project's license expression), and `metadata`
  (string values only: `plugin`, `version`). No harness-specific keys, so one file serves every
  harness.
- `plugins/<plugin>/skills/<skill>/` is a byte-identical copy for the skills that plugin lists.
- Skill bodies must work without hooks, agents, or MCP. Where a hook would help, the body says what
  to run by hand (for example the session summary command).

## Plugin manifests

Each plugin directory carries two manifests, because Codex reads the first manifest it finds and
never merges, and Oh-My-Pi never reads the Codex one.

`plugins/<plugin>/.claude-plugin/plugin.json` (Claude Code, Oh-My-Pi):

```json
{ "name": "lapis", "version": "0.2.0", "description": "…",
  "author": { "name": "lapis-labs" }, "homepage": "https://github.com/lapis-labs/lapis-lazuli",
  "repository": "https://github.com/lapis-labs/lapis-lazuli", "license": "MIT AND CC-BY-4.0",
  "hooks": { "PermissionRequest": [ { "matcher": "ExitPlanMode", "hooks": [
    { "type": "command", "command": "lapis-design-hook --plugin-version 0.2.0 exit-plan", "timeout": 30 } ] } ] } }
```

No component paths: the default layout (`skills/`, `agents/`, `hooks/hooks.json`, `.mcp.json`)
applies, and `agents` or `commands` paths would replace their defaults. Hooks only Claude Code runs
sit inline under `hooks`, which merges with `hooks/hooks.json` (see Hooks). Unknown keys are stripped
with a warning, so none are added.

`plugins/<plugin>/.codex-plugin/plugin.json` (Codex) repeats the components explicitly, because a
Codex manifest's `hooks` replaces the default file rather than adding to it:

```json
{ "name": "lazuli", "version": "0.2.0", "description": "…", "license": "MIT AND CC-BY-4.0",
  "skills": "./skills/", "hooks": "./hooks/hooks.json", "mcpServers": "./.mcp.json",
  "interface": { "displayName": "Lazuli", "shortDescription": "…", "developerName": "lapis-labs" } }
```

`hooks` appears only for plugins with a `hooks/hooks.json` and `mcpServers` only for plugins with
MCP. Codex plugins cannot carry agents.

No root Agent Plugins `plugin.json` is emitted in v0. Codex would take it before `.codex-plugin`
(OpenAI hooks would then move under `extensions.com.openai.hooks`), Oh-My-Pi would hand skills and
MCP to its agent-plugins provider, and Claude Code would ignore it. Revisit when Claude Code reads
the format; one portable manifest could then replace the Codex manifest.

## Catalogs — `claude-catalog`, `codex-catalog`

Both are named `lapis-lazuli`, list the three plugins with `./plugins/<plugin>` sources, and always
include `owner` (Claude Code and Oh-My-Pi require it; Codex ignores it). A `github` source is never
used: Codex skips that type.

- `.claude-plugin/marketplace.json`: `name`, `owner.name`, `description`, and per plugin `name`,
  `source`, `description`, `version`, `category`.
- `.agents/plugins/marketplace.json`: the same, plus per plugin
  `policy: { installation: AVAILABLE, authentication: ON_INSTALL }`, and `interface.displayName`.
  Codex resolves `./` sources from the marketplace root (the repository root), not from
  `.agents/plugins/`.

Entries carry no `license`: that key is not confirmed against a harness's catalog documentation, and
the license is stated in every manifest, every skill, and every installable folder instead.

## Hooks — `plugin-hooks` and inline Claude Code hooks

Every hook is a plain command on PATH, `lapis-design-hook --plugin-version VERSION <name>`: no
path placeholders, shell operators, or quoting, so it parses the same in sh, PowerShell (Claude
Code on Windows without Git Bash), and cmd. The CLI package installs the dedicated executable
on every OS. Old CLI installs lack it, so a plugin update gets a non-blocking command-not-found
diagnostic instead of argparse exit 2 (which blocks PreToolUse and continues Stop). The runner
never uses exit 2 for unknown hooks/options: it exits 0 with only a one-line `systemMessage`.
The build embeds the plugin version in every command, extension, and Hermes module. A version
different from the runner's CLI package version skips the hook with the same fail-open output,
once per session and version pair, claimed atomically under `.lapis/hooks/` (per project without
a session id; an unwritable project may repeat the notice). Update the CLI and plugins together.
The public `lapis-design hook <name>` command uses the same fail-open parser for manual calls.
The CLI carries the full `src/shared` as package data (`lapis_design/shared`), not plugin views,
so the plan check has complete rules wherever the plugin is cached.

Exit status sources: [Claude Code](https://code.claude.com/docs/en/hooks#exit-code-output) and
[Codex](https://learn.chatgpt.com/docs/hooks#stop); Codex's
[Stop parser](https://github.com/openai/codex/blob/main/codex-rs/hooks/src/events/stop.rs)
turns exit 2 stderr into a continuation and other execution failures into failed, non-blocking runs.

| Plugin | Where | Event | Matcher | Name | CLI behavior |
|---|---|---|---|---|---|
| lazuli | `hooks/hooks.json` (Claude Code and Codex) | `SessionStart` | `startup\|resume\|clear\|compact\|fork` | `session-start` | prints the inventory summary as context |
| lapis | inline in `.claude-plugin/plugin.json` (Claude Code only) | `PermissionRequest` | `ExitPlanMode` | `exit-plan` | denies with findings when the plan's lapis-plan block has blocking findings, and denies when the block cannot be read or checked (cli/lapis_design/hooks.py) |
| lapis | `hooks/hooks.json` (Claude Code and Codex) | `Stop` | none | `stop` | the exit gate (cli/lapis_design/gate.py): with a plan under the project and `LAPIS_UNATTENDED=1`, continues the agent with the step `lapis-design next` still asks for (`{"decision": "block", "reason": …}`), at most three times in a row for one step and fifteen in a session; an unattended run with no plan is continued to write one (step `plan`, task named for the project folder unless `LAPIS_TASK` is set); a run waiting for its user's answers (`.lapis/questions/<task>.md` newer than `.lapis/answers/<task>.md`) is let stop, two sets of questions before a plan and one after; otherwise prints a one-line `systemMessage` and never blocks; prints nothing with no plan and no unattended run, or when it fails |
| lapis | `hooks/hooks.json` (Claude Code and Codex) | `PreToolUse` | `Write\|Edit\|MultiEdit\|apply_patch` | `pre-write` | the write guard (cli/lapis_design/order.py): in every session, refuses with the same JSON a write to `.lapis/requirements/`, `.lapis/state/`, `.lapis/changes/`, or `.lapis/owner/`, the records only `lapis-design` writes (no cap; it stops the agent's tool, not a person, and a shell write is detected afterwards, never prevented); with `LAPIS_UNATTENDED=1` and a create run whose brief, references, or plan `lapis-design next` still asks for (or whose plan has blockers), refuses a write of a page source file with `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": …}}` naming the step, at most three times in a row for one step; other writes under `.lapis/`, to other files, and outside the project pass; a person's session gets one `systemMessage` the first time; prints nothing on any failure of ours |

| lapis | `dist/antigravity/lapis/hooks.json` (Antigravity only) | `Stop` | none | `stop` | the same gate; answers `{"decision": "continue", "reason": …}` instead of `block`, and only when the agent chose to stop, in the person's own conversation (see Antigravity) |
| lapis | `dist/antigravity/lapis/hooks.json` (Antigravity only) | `PreToolUse` | `write_to_file\|replace_file_content\|multi_replace_file_content\|notebook_edit` | `pre-write` | the same guard; answers `{"decision": "deny", "reason": …}`, and nothing otherwise |

Codex reads `hooks/hooks.json` by default, and its matchers are regular expressions, so the
`fork` alternative never matches there. The plan check stays out of that file: Codex has no
ExitPlanMode tool, and a hook in the file would still ask Codex users to trust it. The lapis plugin's
`hooks/hooks.json` therefore holds the `stop` and `pre-write` hooks, and its Codex manifest names that file.
`Stop` takes no matcher in either harness, so that hook has none. Claude Code's file-edit tools are `Write`,
`Edit`, and `MultiEdit`; Codex reports every file edit as `apply_patch` (its matchers also take `Edit` and
`Write`) with the patch text in `tool_input.command`, and the hook reads the files from that text.

## MCP — `plugin-mcp`

`plugins/lazuli/.mcp.json`: `{"mcpServers": {"lapis-lazuli": {"command": "lapis-design", "args": ["mcp"]}}}`.
The command is the CLI on PATH, not a path under the plugin root, because the Codex plugin loader
does not substitute `${CLAUDE_PLUGIN_ROOT}` in `.mcp.json`. Hermes registers the same command with
`hermes mcp add`; pi has no MCP. The server (`cli/lapis_design/mcp_server.py`, official MCP Python
SDK 2.x) answers both the `initialize` handshake of protocol versions up to 2025-11-25 and the
per-request versions from 2026-07-28, so older and newer harness clients connect.

## Agents — `claude-agents`, `codex-agents`

- `plugins/ultramarine/agents/critic.md`: Claude Code agent file from `src/agents/critic.md`, with
  `name` and `description` frontmatter and no `permissionMode`, `hooks`, or `mcpServers` (plugin
  agents ignore them).
- `dist/codex/agents/ulm-critic.toml`: `name = "ulm-critic"`, `description`, and
  `developer_instructions` (the same body), `sandbox_mode = "read-only"`. The installer copies it
  to `~/.codex/agents/` after asking.
- `references/critic.md` in the ultramarine skill: the body of `src/agents/critic.md` without its
  frontmatter, so a harness without agents can run the critic in a fresh context from the skill.

## Session and gate extensions and packages — `session-extension`, `gate-extension`, `omp-package`, `pi-package`

- `plugins/lazuli/extensions/session-start.ts` exports a default factory that listens for
  `session_start` and runs `lapis-design-hook --plugin-version VERSION session-start`. It imports
  the host API with `import type` only, so the same module loads under pi and Oh-My-Pi, whose
  package names differ. The event on stdin includes the session id and project for notice deduplication.
- `plugins/lapis/extensions/exit-gate.ts` (from `src/extensions/exit-gate.ts`) is the `stop` hook for the two
  harnesses that have no hooks.json. It starts `lapis-design-hook --plugin-version VERSION stop` with the event JSON (`cwd`,
  `session_id`) on stdin and translates the answer: Oh-My-Pi's `session_stop` takes `{ decision: "block",
  reason }`, pi's `agent_before_settle` takes a `custom_message` entry with `continue: true`, and a
  `systemMessage` goes to `ctx.ui.notify` when the host has a UI. Each host never fires the other's event,
  so both are registered, and a registration the host does not know is ignored. The CLI holds the rules
  (unattended switch, limits, state); a missing CLI, a failure, or output that is not JSON lets the agent stop.
  The same file registers a `tool_call` handler, the write guard: for the write and edit tools it starts
  `lapis-design-hook --plugin-version VERSION pre-write` with the event JSON (`cwd`, `session_id`, `tool_name`, `tool_input`) and answers `{ block: true,
  reason }` for a refusal. Both hosts block the tool when a `tool_call` handler fails or times out (30 seconds in
  Oh-My-Pi), so the handler answers within 20 seconds and treats every failure as no answer.
  A `systemMessage` is shown through `ctx.ui.notify`, or stderr in a headless session; missing
  runners fail open with a visible notice, never a thrown handler error.
- `plugins/lapis/package.json` and `plugins/lazuli/package.json`: `{"name": "@lapis-labs/<plugin>-omp",
  "license": "MIT AND CC-BY-4.0", "private": true, "omp": {"extensions": ["./extensions/<file>.ts"]}}` with the
  extension each plugin's hooks name (`exit-gate.ts` for lapis, `session-start.ts` for lazuli).
- `package.json` at the repository root: `{"name": "lapis-lazuli", "version": …,
  "license": "MIT AND CC-BY-4.0", "private": true, "keywords": ["pi-package"], "pi": {"skills":
  ["./dist/skills"], "extensions": ["./plugins/lapis/extensions/exit-gate.ts",
  "./plugins/lazuli/extensions/session-start.ts"]}}`. pi's git installs have no subdirectory selector, so
  the root carries the key.

## Hermes — `hermes-plugin`

`plugins/hermes/lapis-lazuli/` holds `plugin.yaml` (`name`, `version`, `description`, `author`,
`provides_hooks: [pre_llm_call]`) and `__init__.py` with `register(ctx)`. The hook adds the session
summary on the first turn (`is_first_turn`); `on_session_start` cannot add context. It runs the
versioned hook-only entry point, passes the session id, and prints version/missing-runner notices
to stderr without adding model context or a blocking decision. Skills are not bundled in the
plugin: plugin skills get a `plugin:` namespace and stay out of the skill index, so they install
flat from `dist/skills`.

## Antigravity — `antigravity-plugin-manifest`, `antigravity-skills`, `antigravity-hooks`, `antigravity-mcp`, `antigravity-agents`

`dist/antigravity/<plugin>/` is the folder `agy plugin install <folder>` copies: one per plugin, in a tree of its own so that
`plugins/<plugin>/` (read by Claude Code, Codex, and Oh-My-Pi) never holds a root `plugin.json`. agy 1.2.17 puts the copy under
`~/.gemini/config/plugins/<name>/`, though its documentation says `~/.gemini/antigravity-cli/plugins/<name>/`, and a second
install of the same plugin replaces the whole folder (checked 2026-10-06 under an isolated HOME). There is no marketplace of
our own: Antigravity installs only from a local folder, so `install.sh` clones the release branch into a temporary folder for the
`{checkout}` placeholder and deletes it afterwards.

- `plugin.json`: `{"$schema": "https://antigravity.google/schemas/v1/plugin.json", "name", "description"}` and nothing else, since
  the schema allows no other key. The version lives in the hook commands and the skills' `metadata`, not here.
- `skills/<skill>/`: byte-identical copies of the flat skills the plugin lists, with the same license texts.
- `hooks.json`, lapis only: a hook name maps to its event. `lapis-stop` is `Stop` (handlers listed directly, no matcher) and
  `lapis-pre-write` is `PreToolUse` with the matcher `write_to_file|replace_file_content|multi_replace_file_content|notebook_edit`
  (the file is `TargetFile`, or `NotebookPath` for `notebook_edit`; `sed_file` is in agy's tool list but a custom agent that names
  it fails with `not found in registry`, so it is not guarded); each runs
  `lapis-design-hook --plugin-version VERSION --host antigravity <name> || exit 0`. There is no `exit-plan` (no ExitPlanMode tool)
  and no `session-start`: Antigravity has no such event, and a PreInvocation hook's `ephemeralMessage` reaches the model for a few
  steps only (checked 2026-10-06: answered after one tool call, gone after three), so the lazuli skill's by-hand command stands in.
- `mcp_config.json`, lazuli only: the same server as `.mcp.json`. Antigravity lists its tool as `slop_lint` on the server
  `lazuli_lapis-lazuli`.
- `agents/critic.md`: the critic's body, with `name`, `description`, and `tools` (`view_file`, `list_dir`, `grep_search`,
  `find_by_name`, `write_to_file`: it reads the packet's files and writes its report, with no shell, web, or browser). The main
  agent starts it with `invoke_subagent` (type name `critic`), or `agy --agent critic` runs it as the session's agent.
- `LICENSE`, `LICENSE-docs`, `NOTICE`, copied byte for byte like every other installable folder.

What Antigravity does with a hook's answer, as observed with agy 1.2.17 in headless runs (2026-10-06); `cli/lapis_design/antigravity.py`
keeps to it:

| Hook | Answer | Result |
|---|---|---|
| `PreToolUse` | no output, exit 0 | the tool runs |
| `PreToolUse` | `{"decision": "deny", "reason": …}` | the call is refused and the model reads the reason, also under `--dangerously-skip-permissions` |
| `PreToolUse` | `{}`, JSON with a field it does not know (`systemMessage`), text that is not JSON, or exit 1 or 2 | the call fails with that error: fail closed |
| `Stop` | `{"decision": "continue", "reason": …}` | the loop continues and the reason is shown to the model as a system message |
| `Stop`, `PreInvocation` | `{}`, an unknown field, or exit 1 | ignored |

A hook's working directory is the plugin's folder, so the event's `workspacePaths` names the project. `Stop`'s `terminationReason`
is `NO_TOOL_CALL` when the agent chose to stop (the documentation says `model_stop`); a cancel, an error, and the limits have
their own values, and the gate continues none of them. `Stop` also fires when a subagent (the critic) ends, with an event of the
same shape; its transcript (`transcriptPath`) opens with a system message from its parent where the person's conversation opens
with their own message (`source` `USER_EXPLICIT`), and the gate answers nothing for any other conversation, so it never
continues the critic with the procedure's next step. A successful hook's stderr is written to the CLI log
(`~/.gemini/antigravity-cli/cli.log`) and is not shown to the person, which is where a skipped hook's one-line notice goes. The
`|| exit 0` is why a missing or crashed `lapis-design-hook` costs nothing (a CLI older than the plugin does not know `--host`
and prints its `systemMessage` once per hook, which fails that one tool call).

## Licenses

`[project] license` in `pyproject.toml` is the one place the SPDX expression is written (`MIT AND
CC-BY-4.0`: Markdown files are CC BY 4.0, everything else MIT). The build reads it, refuses a skill
source whose `license` is missing or differs, and writes it into both plugin manifests, the Oh-My-Pi
package, and the pi package. The Hermes `plugin.yaml` has no license key.

`LICENSE` (MIT), `LICENSE-docs` (the CC BY 4.0 legal code), and `NOTICE` (the third-party material that
keeps its owner's terms) at the repository root are copied byte for byte into every folder a harness
installs on its own: `plugins/<plugin>/`, `plugins/hermes/lapis-lazuli/`, and every skill folder
(`dist/skills/<skill>/` and its identical copy under `plugins/<plugin>/skills/<skill>/`). They are not
harness outputs, so `harnesses.yaml` does not list them; `--check` treats them as generated, and editing
a root text without rebuilding shows up as drift in every copy. The wheel and sdist list the same three
files as `License-File`.

## Instructions snippet — `agents-md-snippet`

`dist/AGENTS.snippet.md`: a few lines for harnesses without hooks or MCP support in our outputs —
run `lazuli local fonts --summary` at the start of a design task, and register `lapis-design mcp`
with the harness's own MCP setting. The installer prints it and never edits an instructions file
itself.
