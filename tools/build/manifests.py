"""Emitters for the JSON outputs in install/OUTPUTS.md, plus the Hermes manifest shape.

Pure functions from install/harnesses.yaml (and a release version) to the documents the build
writes. tools/build/build.py, the one entry, adds skills, agents, the extension, the Hermes plugin,
and the snippet; this module fixes the manifest, catalog, hook, MCP, and package shapes.
"""
from __future__ import annotations

import json

# shared: hooks/hooks.json, read by Claude Code and Codex. claude: inline in .claude-plugin/plugin.json,
# because Codex would ask users to trust a hook that never fires there.
HOOKS = {
    "session-start": {"event": "SessionStart", "matcher": "startup|resume|clear|compact|fork", "timeout": 10,
                      "file": "shared"},
    "exit-plan": {"event": "PermissionRequest", "matcher": "ExitPlanMode", "timeout": 30, "file": "claude"},
    # Stop takes no matcher in either harness; the gate runs `lapis-design next`, which reads the plan and the
    # reports, so its timeout is longer than a session summary's
    "stop": {"event": "Stop", "matcher": None, "timeout": 60, "file": "shared"},
    # PreToolUse on the file-edit tools: Claude Code names Write, Edit, and MultiEdit; Codex reports every file edit
    # as `apply_patch`, which its matchers also accept as Edit or Write. Both read the matcher as an alternation, and
    # a tool the hook has no page file for (an MCP tool that happens to match) gets no answer. The hook reads the
    # plan and the records, as the gate does, so it has a timeout of its own
    "pre-write": {"event": "PreToolUse", "matcher": "Write|Edit|MultiEdit|apply_patch", "timeout": 30,
                  "file": "shared"},
}
# The extension each hook has under pi and Oh-My-Pi, which have no hooks.json; the file is under the plugin's
# extensions/ folder and its source is named by the output that emits it (install/harnesses.yaml). The exit-gate
# extension also registers the tool_call handler that runs `pre-write`, so that hook has no entry of its own.
EXTENSIONS = {"session-start": "session-start.ts", "stop": "exit-gate.ts"}
# Antigravity has its own hooks.json (a hook name maps to events; install/OUTPUTS.md, Antigravity) and no ExitPlanMode
# tool, so `exit-plan` has no entry. A hook that fails, prints a field Antigravity does not know, or prints `{}` stops
# the tool or the model call it ran for, so each command ends in `|| exit 0` (sh and cmd.exe both read it): a missing or
# crashed runner then prints nothing and the agent goes on. `pre-write` gets the file-edit tools. Antigravity has
# no session-start event, and PreInvocation's ephemeral message fades after a few steps, so `session-start` has no entry.
ANTIGRAVITY_SCHEMA = "https://antigravity.google/schemas/v1/plugin.json"
ANTIGRAVITY_WRITE_TOOLS = "write_to_file|replace_file_content|multi_replace_file_content|notebook_edit"
ANTIGRAVITY_HOOKS = {
    "stop": {"event": "Stop", "matcher": None, "timeout": 60},
    "pre-write": {"event": "PreToolUse", "matcher": ANTIGRAVITY_WRITE_TOOLS, "timeout": 30},
}
MCP_COMMAND = {"command": "lapis-design", "args": ["mcp"]}
# The first sentence of the repository's GitHub About text, which the maintainers set by hand.
ABOUT = "Design skills for coding agents, plus two CLIs."


def _repo_url(doc: dict) -> str:
    return f"https://github.com/{doc['repo']['owner']}/{doc['repo']['name']}"


def _title(name: str) -> str:
    return name[:1].upper() + name[1:]


def _hooks(plugin: dict, file: str, version: str) -> dict | None:
    events: dict[str, list] = {}
    for name in plugin.get("hooks", []):
        h = HOOKS[name]
        if h["file"] != file:
            continue
        # a plain command on PATH parses the same in sh, PowerShell, and cmd
        handler = {"type": "command", "command": f"lapis-design-hook --plugin-version {version} {name}",
                   "timeout": h["timeout"]}
        group = {"matcher": h["matcher"]} if h["matcher"] else {}
        events.setdefault(h["event"], []).append({**group, "hooks": [handler]})
    return {"hooks": events} if events else None


def claude_manifest(doc: dict, plugin: dict, version: str, license_id: str) -> dict:
    url = _repo_url(doc)
    out = {"name": plugin["name"], "version": version, "description": plugin["description"],
           "author": {"name": doc["repo"]["owner"]}, "homepage": url, "repository": url, "license": license_id}
    inline = _hooks(plugin, "claude", version)
    if inline:
        out["hooks"] = inline["hooks"]
    return out


def codex_manifest(doc: dict, plugin: dict, version: str, license_id: str) -> dict:
    out = {"name": plugin["name"], "version": version, "description": plugin["description"], "license": license_id,
           "skills": "./skills/"}
    if _hooks(plugin, "shared", version):
        out["hooks"] = "./hooks/hooks.json"
    if plugin.get("mcp"):
        out["mcpServers"] = "./.mcp.json"
    out["interface"] = {"displayName": _title(plugin["name"]), "shortDescription": plugin["description"],
                        "developerName": doc["repo"]["owner"]}
    return out


def antigravity_manifest(plugin: dict) -> dict:
    """plugin.json for Antigravity: `name` and `description` only (the schema allows nothing else)."""
    return {"$schema": ANTIGRAVITY_SCHEMA, "name": plugin["name"], "description": plugin["description"]}


def _catalog_entry(plugin: dict, version: str) -> dict:
    return {"name": plugin["name"], "source": f"./plugins/{plugin['name']}", "description": plugin["description"],
            "version": version, "category": "design"}


def claude_catalog(doc: dict, version: str) -> dict:
    return {"name": doc["repo"]["catalog"], "owner": {"name": doc["repo"]["owner"]},
            "description": ABOUT, "plugins": [_catalog_entry(p, version) for p in doc["plugins"]]}


def codex_catalog(doc: dict, version: str) -> dict:
    plugins = [{**_catalog_entry(p, version), "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}}
               for p in doc["plugins"]]
    return {"name": doc["repo"]["catalog"], "owner": {"name": doc["repo"]["owner"]},
            "description": ABOUT, "interface": {"displayName": "LapisLazuli"}, "plugins": plugins}


def hooks_json(plugin: dict, version: str) -> dict | None:
    """hooks/hooks.json: hooks both Claude Code and Codex run."""
    return _hooks(plugin, "shared", version)


def antigravity_hooks_json(plugin: dict, version: str) -> dict | None:
    """hooks.json for Antigravity: one named hook per hook the plugin lists that Antigravity can run. The events
    that take no matcher (Stop) hold their handlers directly; PreToolUse wraps them in a group."""
    out: dict[str, dict] = {}
    for name in plugin.get("hooks", []):
        h = ANTIGRAVITY_HOOKS.get(name)
        if h is None:
            continue
        handler = {"type": "command", "timeout": h["timeout"],
                   "command": f"lapis-design-hook --plugin-version {version} --host antigravity {name} || exit 0"}
        out[f"{plugin['name']}-{name}"] = {h["event"]: [{"matcher": h["matcher"], "hooks": [handler]}]
                                           if h["matcher"] else [handler]}
    return out or None


def mcp_json(plugin: dict) -> dict | None:
    if not plugin.get("mcp"):
        return None
    return {"mcpServers": {name: dict(MCP_COMMAND) for name in plugin["mcp"]}}


def omp_package(plugin: dict, version: str, license_id: str) -> dict | None:
    extensions = [f"./extensions/{EXTENSIONS[h]}" for h in plugin.get("hooks", []) if h in EXTENSIONS]
    if not extensions:
        return None
    return {"name": f"@lapis-labs/{plugin['name']}-omp", "version": version, "license": license_id, "private": True,
            "omp": {"extensions": extensions}}


def pi_package(doc: dict, version: str, license_id: str) -> dict:
    extensions = [f"./plugins/{p['name']}/extensions/{EXTENSIONS[h]}" for p in doc["plugins"]
                  for h in p.get("hooks", []) if h in EXTENSIONS]
    return {"name": doc["repo"]["name"], "version": version, "license": license_id, "private": True,
            "keywords": ["pi-package"], "pi": {"skills": ["./dist/skills"], "extensions": extensions}}


def hermes_plugin(doc: dict, version: str, source: dict) -> dict:
    """plugin.yaml: name, version, and author from harnesses.yaml; the rest from src/hermes/plugin.yaml."""
    return {"name": doc["repo"]["name"], "version": version, "description": source["description"],
            "author": doc["repo"]["owner"], "provides_hooks": list(source["provides_hooks"])}


def _toml_multiline(text: str) -> str:
    """A TOML multi-line string: literal when possible, so backslashes stay as written."""
    text = text.rstrip() + "\n"
    if "'''" not in text:
        return "'''\n" + text + "'''"
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return '"""\n' + escaped + '"""'


def codex_agent_toml(name: str, description: str, instructions: str) -> str:
    return (f"name = {json.dumps(name)}\ndescription = {json.dumps(description)}\n"
            f"sandbox_mode = \"read-only\"\ndeveloper_instructions = {_toml_multiline(instructions)}\n")


# output format -> document; per-repo formats take (doc, version, license), per-plugin ones
# (doc, plugin, version, license). The license is the project's SPDX expression; catalog entries
# carry none, because the harness docs this repository records do not name the key.
REPO_FORMATS = {
    "claude-catalog": lambda doc, version, license_id: claude_catalog(doc, version),
    "codex-catalog": lambda doc, version, license_id: codex_catalog(doc, version),
    "pi-package": pi_package,
}
PLUGIN_FORMATS = {
    "claude-plugin-manifest": claude_manifest,
    "codex-plugin-manifest": codex_manifest,
    "antigravity-plugin-manifest": lambda doc, plugin, version, license_id: antigravity_manifest(plugin),
    "hooks-json": lambda doc, plugin, version, license_id: hooks_json(plugin, version),
    "antigravity-hooks-json": lambda doc, plugin, version, license_id: antigravity_hooks_json(plugin, version),
    "mcp-json": lambda doc, plugin, version, license_id: mcp_json(plugin),
    "omp-package": lambda doc, plugin, version, license_id: omp_package(plugin, version, license_id),
}
FORMATS = frozenset(REPO_FORMATS) | frozenset(PLUGIN_FORMATS)


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def emit(doc: dict, version: str, license_id: str) -> dict[str, str]:
    """Map of repo-relative path -> file text for every output whose format is in FORMATS.

    Paths come from the output templates in harnesses.yaml. A per-plugin output goes to the plugins
    its `only` lists (every plugin without `only`), and those must be exactly the plugins the shape
    applies to, so a plugin fact (hooks, mcp) and its output list cannot drift apart.
    """
    files: dict[str, str] = {}
    for out in doc["outputs"]:
        fmt = out["format"]
        if fmt in REPO_FORMATS:
            files[out["path"]] = _json(REPO_FORMATS[fmt](doc, version, license_id))
        elif fmt in PLUGIN_FORMATS:
            only = out.get("only")
            for p in doc["plugins"]:
                value = PLUGIN_FORMATS[fmt](doc, p, version, license_id)
                listed = only is None or p["name"] in only
                if value is None and listed:
                    raise ValueError(f"output {out['id']} lists plugin {p['name']}, which has nothing for it")
                if value is not None and not listed:
                    raise ValueError(f"output {out['id']} leaves out plugin {p['name']}; add it to `only`")
                if value is not None:
                    files[out["path"].format(plugin=p["name"])] = _json(value)
    return files
