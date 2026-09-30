# Build outputs — v0

What the build (`tools/build`) emits from `src/` for each output in `install/harnesses.yaml`.
Reference code for the manifests, catalogs, hooks, and MCP files: `tools/build/manifests.py`.

`src/` is the only place people edit. Every output is generated and committed, because marketplace
installs read the repository as it is. CI regenerates into a temporary directory and fails when the
result differs from the committed files. JSON cannot carry a "generated" comment, so the sync check
is the guard.

## Versions and channels

One version per release, taken from the release tag, goes into every manifest, both catalogs, the
pi package, and the Hermes plugin. A plugin `version` pins Claude Code users until it changes, so
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
{ "name": "lapis", "version": "0.1.0", "description": "…",
  "author": { "name": "lapis-labs" }, "homepage": "https://github.com/lapis-labs/lapis-lazuli",
  "repository": "https://github.com/lapis-labs/lapis-lazuli", "license": "MIT AND CC-BY-4.0",
  "hooks": { "PermissionRequest": [ { "matcher": "ExitPlanMode", "hooks": [
    { "type": "command", "command": "lapis-design hook exit-plan", "timeout": 30 } ] } ] } }
```

No component paths: the default layout (`skills/`, `agents/`, `hooks/hooks.json`, `.mcp.json`)
applies, and `agents` or `commands` paths would replace their defaults. Hooks only Claude Code runs
sit inline under `hooks`, which merges with `hooks/hooks.json` (see Hooks). Unknown keys are stripped
with a warning, so none are added.

`plugins/<plugin>/.codex-plugin/plugin.json` (Codex) repeats the components explicitly, because a
Codex manifest's `hooks` replaces the default file rather than adding to it:

```json
{ "name": "lazuli", "version": "0.1.0", "description": "…", "license": "MIT AND CC-BY-4.0",
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

Every hook is a plain command on PATH, `lapis-design hook <name>`: no path placeholders and no
quoting, so it parses the same in sh, PowerShell (Claude Code on Windows without Git Bash), and cmd,
and plugins ship no scripts. The CLI reads the event on stdin and prints what the harness expects.
When the CLI is missing, Claude Code shows a non-blocking hook error at each session start; the
skills still work, and INSTALLATION.md and `lazuli doctor` say to install the CLI. The CLI never
reads the plugin's skill views: it carries the full `src/shared` as package data
(`lapis_design/shared`) and finds it with `lapis_design.shared_dir()`, so the plan check has the
complete rules and schemas wherever the plugin is cached.

| Plugin | Where | Event | Matcher | Name | CLI behavior |
|---|---|---|---|---|---|
| lazuli | `hooks/hooks.json` (Claude Code and Codex) | `SessionStart` | `startup\|resume\|clear\|compact\|fork` | `session-start` | prints the inventory summary as context |
| lapis | inline in `.claude-plugin/plugin.json` (Claude Code only) | `PermissionRequest` | `ExitPlanMode` | `exit-plan` | denies with findings when the plan's lapis-plan block has blocking findings, and denies when the block cannot be read or checked (cli/lapis_design/hooks.py) |

Codex reads `hooks/hooks.json` by default, and its matchers are regular expressions, so the
`fork` alternative never matches there. The plan check stays out of that file: Codex has no
ExitPlanMode tool, and a hook in the file would still ask Codex users to trust it. The lapis plugin
therefore has no `hooks/hooks.json`, and its Codex manifest has no `hooks` key.

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

## Session extension and packages — `session-extension`, `omp-package`, `pi-package`

- `plugins/lazuli/extensions/session-start.ts` exports a default factory that listens for
  `session_start` and runs `lapis-design hook session-start`. It imports the host API with
  `import type` only, so the same module loads under pi and Oh-My-Pi, whose package names differ.
- `plugins/lazuli/package.json`: `{"name": "@lapis-labs/lazuli-omp", "license": "MIT AND CC-BY-4.0",
  "private": true, "omp": {"extensions": ["./extensions/session-start.ts"]}}`.
- `package.json` at the repository root: `{"name": "lapis-lazuli", "version": …,
  "license": "MIT AND CC-BY-4.0", "private": true, "keywords": ["pi-package"], "pi": {"skills":
  ["./dist/skills"], "extensions": ["./plugins/lazuli/extensions/session-start.ts"]}}`. pi's git
  installs have no subdirectory selector, so the root carries the key.

## Hermes — `hermes-plugin`

`plugins/hermes/lapis-lazuli/` holds `plugin.yaml` (`name`, `version`, `description`, `author`,
`provides_hooks: [pre_llm_call]`) and `__init__.py` with `register(ctx)`. The hook adds the session
summary on the first turn (`is_first_turn`); `on_session_start` cannot add context. Skills are not
bundled in the plugin: plugin skills get a `plugin:` namespace and stay out of the skill index, so
they install flat from `dist/skills`.

## Licenses

`[project] license` in `pyproject.toml` is the one place the SPDX expression is written (`MIT AND
CC-BY-4.0`: Markdown files are CC BY 4.0, everything else MIT). The build reads it, refuses a skill
source whose `license` is missing or differs, and writes it into both plugin manifests, the Oh-My-Pi
package, and the pi package. The Hermes `plugin.yaml` has no license key.

`LICENSE` (MIT) and `LICENSE-docs` (the CC BY 4.0 legal code) at the repository root are copied byte
for byte into every folder a harness installs on its own: `plugins/<plugin>/`,
`plugins/hermes/lapis-lazuli/`, and every skill folder (`dist/skills/<skill>/` and its identical
copy under `plugins/<plugin>/skills/<skill>/`). They are not harness outputs, so `harnesses.yaml`
does not list them; `--check` treats them as generated, and editing the root text without rebuilding
shows up as drift in every copy.

## Instructions snippet — `agents-md-snippet`

`dist/AGENTS.snippet.md`: a few lines for harnesses without hooks or MCP support in our outputs —
run `lazuli local fonts --summary` at the start of a design task, and register `lapis-design mcp`
with the harness's own MCP setting. The installer prints it and never edits an instructions file
itself.
