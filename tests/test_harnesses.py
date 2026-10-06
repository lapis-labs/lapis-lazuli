"""install/harnesses.yaml: schema, internal references, and the reference emitters."""
import json
import re
import sys
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator as V

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "build"))

import manifests  # noqa: E402

PLACEHOLDERS = {"repo", "catalog", "plugin", "skill", "agent", "ref", "sha", "checkout"}
LICENSE = "LicenseRef-test"          # any expression: the emitters only pass the project's through


def doc():
    return yaml.safe_load((ROOT / "install/harnesses.yaml").read_text(encoding="utf-8"))


def outputs():
    return {o["id"]: o for o in doc()["outputs"]}


def steps(harness):
    for phase in ("install", "update", "uninstall", "verify"):
        yield from harness.get(phase, [])


def test_harnesses_pass_the_schema():
    schema = yaml.safe_load((ROOT / "install/harnesses.schema.yaml").read_text(encoding="utf-8"))
    V.check_schema(schema)
    assert list(V(schema).iter_errors(doc())) == []


def test_outputs_and_consumers_match():
    d, outs = doc(), outputs()
    consumed = {o for h in d["harnesses"] for o in h["consumes"]}
    assert consumed - set(outs) == set()
    assert set(outs) - consumed == set()
    for o in d["outputs"]:
        assert [f for f in o["from"] if not f.startswith(("src/", "install/")) and f not in outs] == [], o["id"]


def test_mechanism_outputs_are_consumed_by_their_harness():
    for h in doc()["harnesses"]:
        for key in ("session_start", "critic", "exit_gate", "mcp"):
            out = h[key].get("output")
            assert out is None or out in h["consumes"], (h["id"], key)


def test_plugins_follow_the_naming_rules():
    d = doc()
    names = [s for p in d["plugins"] for s in p["skills"]]
    assert len(names) == len(set(names))
    for p in d["plugins"]:
        assert p["skills"][0] == p["name"]
        assert all(s.startswith(p["prefix"]) for s in p["skills"][1:]), p["name"]
    plugins = {p["name"] for p in d["plugins"]}
    assert [o["id"] for o in d["outputs"] if set(o.get("only", [])) - plugins] == []


def test_steps_use_known_placeholders():
    bad = []
    for h in doc()["harnesses"]:
        for st in steps(h):
            text = json.dumps(st)
            for name in re.findall(r"\{([a-z]+)\}", text):
                if name not in PLACEHOLDERS:
                    bad.append((h["id"], name))
                if name == "plugin" and h["form"] not in ("plugin",):
                    bad.append((h["id"], "plugin placeholder outside a plugin harness"))
                if name == "agent" and not h.get("agents"):
                    bad.append((h["id"], "agent placeholder without agents"))
    assert bad == []


def test_copied_files_come_from_outputs():
    d, outs = doc(), outputs()
    agent_names = {f"{p['prefix']}{a}" for p in d["plugins"] for a in p.get("agents", [])}
    for h in d["harnesses"]:
        for st in steps(h):
            if "copy" in st:
                src = st["copy"]["from"]
                assert any(src.startswith(o["path"]) for o in outs.values() if o["path"].endswith("/")), src
                assert Path(src).stem in agent_names


def test_catalogs_point_at_plugin_directories():
    d = doc()
    for catalog in (manifests.claude_catalog(d, "0.1.0"), manifests.codex_catalog(d, "0.1.0")):
        assert catalog["name"] == d["repo"]["catalog"] and catalog["owner"]["name"]
        assert [e["source"] for e in catalog["plugins"]] == [f"./plugins/{p['name']}" for p in d["plugins"]]
        assert all(isinstance(e["source"], str) for e in catalog["plugins"])   # never a github source object


def test_codex_manifest_repeats_components():
    d = doc()
    for p in d["plugins"]:
        m = manifests.codex_manifest(d, p, "0.1.0", LICENSE)
        assert m["skills"] == "./skills/"
        assert ("hooks" in m) == (manifests.hooks_json(p, "0.1.0") is not None)
        assert ("mcpServers" in m) == bool(p.get("mcp"))
        claude = manifests.claude_manifest(d, p, "0.1.0", LICENSE)
        assert m["license"] == claude["license"] == LICENSE
        assert not {"skills", "mcpServers", "agents", "commands"} & set(claude)






def test_codex_never_sees_claude_only_hooks():
    for p in doc()["plugins"]:
        shared = (manifests.hooks_json(p, "0.1.0") or {}).get("hooks", {})
        assert "PermissionRequest" not in shared                        # ExitPlanMode exists only in Claude Code
    outs = outputs()
    assert set(outs["plugin-hooks"]["only"]) == {p["name"] for p in doc()["plugins"] if manifests.hooks_json(p, "0.1.0")}


def test_mcp_uses_the_cli_on_path():
    for p in doc()["plugins"]:
        m = manifests.mcp_json(p)
        if m:
            assert "CLAUDE_PLUGIN_ROOT" not in json.dumps(m)


def test_packages_point_at_emitted_paths():
    d, outs = doc(), outputs()
    pi = manifests.pi_package(d, "0.1.0", LICENSE)
    assert pi["pi"]["skills"] == ["./" + outs["flat-skills"]["path"].split("{")[0].rstrip("/")]
    assert pi["pi"]["extensions"] == ["./" + outs["gate-extension"]["path"], "./" + outs["session-extension"]["path"]]
    omp = {p["name"]: manifests.omp_package(p, "0.1.0", LICENSE) for p in d["plugins"]}
    assert {name for name, package in omp.items() if package} == set(outs["omp-package"]["only"])
    assert [f"plugins/lapis/{path[2:]}" for path in omp["lapis"]["omp"]["extensions"]] == [outs["gate-extension"]["path"]]
    assert [f"plugins/lazuli/{path[2:]}" for path in omp["lazuli"]["omp"]["extensions"]] == [
        outs["session-extension"]["path"]]
    assert pi["license"] == omp["lapis"]["license"] == omp["lazuli"]["license"] == LICENSE
    assert omp["lazuli"]["version"] == "0.1.0"          # omp lists a linked package as name@version


def test_every_hook_a_plugin_lists_has_the_extension_pi_and_oh_my_pi_load():
    for p in doc()["plugins"]:
        extensions = (manifests.omp_package(p, "0.1.0", LICENSE) or {}).get("omp", {}).get("extensions", [])
        listed = [h for h in p.get("hooks", []) if h in manifests.EXTENSIONS]
        assert [Path(e).name for e in extensions] == [manifests.EXTENSIONS[h] for h in listed], p["name"]




def test_emit_writes_every_json_output_it_owns():
    files = manifests.emit(doc(), "0.1.0", LICENSE)
    for rel, text in files.items():
        if rel.endswith(".json"):
            json.loads(text)
    assert ".claude-plugin/marketplace.json" in files and ".agents/plugins/marketplace.json" in files


@pytest.mark.parametrize("body", ['Say """no""" when needed', "Match \\d+ in C:\\Users", "Mixed \'\'\' and \\n"])
def test_codex_agent_toml_round_trips(body):
    import tomllib
    parsed = tomllib.loads(manifests.codex_agent_toml("ulm-critic", "Separate critic", body))
    assert parsed["name"] == "ulm-critic" and parsed["developer_instructions"].rstrip("\n") == body


def test_catalog_removal_waits_for_the_last_plugin():
    for h in doc()["harnesses"]:
        for st in h.get("uninstall", []):
            if "marketplace" in st.get("run", []) and "remove" in st.get("run", []):
                assert st.get("when") == "all-plugins", h["id"]


def test_antigravity_manifest_holds_only_what_its_schema_allows():
    for p in doc()["plugins"]:
        m = manifests.antigravity_manifest(p)
        assert m == {"$schema": manifests.ANTIGRAVITY_SCHEMA, "name": p["name"], "description": p["description"]}


def test_antigravity_hooks_carry_only_the_hooks_it_can_run_and_never_fail():
    plugins = {p["name"]: p for p in doc()["plugins"]}
    # no ExitPlanMode tool, and no session-start event that holds an injected summary
    assert manifests.antigravity_hooks_json(plugins["lazuli"], "0.1.0") is None
    assert manifests.antigravity_hooks_json(plugins["ultramarine"], "0.1.0") is None
    hooks = manifests.antigravity_hooks_json(plugins["lapis"], "0.1.0")
    assert set(hooks) == {"lapis-stop", "lapis-pre-write"}
    assert outputs()["antigravity-hooks"]["only"] == ["lapis"]
    stop = hooks["lapis-stop"]["Stop"]
    assert len(stop) == 1 and "matcher" not in stop[0] and stop[0]["type"] == "command"      # flat, no matcher group
    group = hooks["lapis-pre-write"]["PreToolUse"][0]
    assert set(group["matcher"].split("|")) == {"write_to_file", "replace_file_content", "multi_replace_file_content",
                                                "notebook_edit"}
    for handler in [stop[0], *group["hooks"]]:
        # a hook that exits non-zero stops the tool call, so a missing runner must not
        assert handler["command"].startswith("lapis-design-hook --plugin-version 0.1.0 --host antigravity ")
        assert handler["command"].endswith(" || exit 0")
        assert isinstance(handler["timeout"], int)


def test_antigravity_mcp_is_the_same_server_under_its_own_file_name():
    outs = outputs()
    assert outs["antigravity-mcp"]["path"] == "dist/antigravity/{plugin}/mcp_config.json"
    assert outs["antigravity-mcp"]["only"] == outs["plugin-mcp"]["only"]
    assert outs["antigravity-mcp"]["format"] == "mcp-json"


def test_antigravity_outputs_are_emitted_where_the_installer_installs_from():
    d = doc()
    files = manifests.emit(d, "0.1.0", LICENSE)
    for p in d["plugins"]:
        assert f"dist/antigravity/{p['name']}/plugin.json" in files
    assert "dist/antigravity/lapis/hooks.json" in files and "dist/antigravity/lazuli/mcp_config.json" in files
    assert "dist/antigravity/lazuli/hooks.json" not in files
    antigravity = next(h for h in d["harnesses"] if h["id"] == "antigravity")
    install = [st for st in antigravity["install"] if "run" in st]
    assert [st["run"] for st in install] == [["agy", "plugin", "install", "{checkout}/dist/antigravity/{plugin}"]]
    assert antigravity["status"] == "experimental"
