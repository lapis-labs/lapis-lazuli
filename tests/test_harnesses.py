"""install/harnesses.yaml: schema, internal references, and the reference emitters."""
import json
import re
import sys
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator as V

from lapis_design.hooks import HOOKS as CLI_HOOKS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "build"))

import manifests  # noqa: E402

PLACEHOLDERS = {"repo", "catalog", "plugin", "skill", "agent", "ref", "sha"}
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
        for key in ("session_start", "critic", "mcp"):
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
        assert ("hooks" in m) == (manifests.hooks_json(p) is not None)
        assert ("mcpServers" in m) == bool(p.get("mcp"))
        claude = manifests.claude_manifest(d, p, "0.1.0", LICENSE)
        assert m["license"] == claude["license"] == LICENSE
        assert not {"skills", "mcpServers", "agents", "commands"} & set(claude)


def _handlers(hooks):
    for groups in (hooks or {}).values():
        for g in groups:
            yield from g["hooks"]


def test_hooks_call_the_cli_on_path():
    d = doc()
    for p in d["plugins"]:
        shared = (manifests.hooks_json(p) or {}).get("hooks")
        inline = manifests.claude_manifest(d, p, "0.1.0", LICENSE).get("hooks")
        names = [h["command"].split()[-1] for h in [*_handlers(shared), *_handlers(inline)]]
        assert sorted(names) == sorted(p.get("hooks", [])), p["name"]
        assert set(names) <= set(CLI_HOOKS), p["name"]                 # the installed CLI runs each one
        for h in [*_handlers(shared), *_handlers(inline)]:
            assert h["command"].startswith("lapis-design hook ") and "$" not in h["command"] and "%" not in h["command"]


def test_codex_never_sees_claude_only_hooks():
    for p in doc()["plugins"]:
        shared = (manifests.hooks_json(p) or {}).get("hooks", {})
        assert "PermissionRequest" not in shared                        # ExitPlanMode exists only in Claude Code
    outs = outputs()
    assert set(outs["plugin-hooks"]["only"]) == {p["name"] for p in doc()["plugins"] if manifests.hooks_json(p)}


def test_mcp_uses_the_cli_on_path():
    for p in doc()["plugins"]:
        m = manifests.mcp_json(p)
        if m:
            assert "CLAUDE_PLUGIN_ROOT" not in json.dumps(m)


def test_packages_point_at_emitted_paths():
    d, outs = doc(), outputs()
    pi = manifests.pi_package(d, "0.1.0", LICENSE)
    assert pi["pi"]["skills"] == ["./" + outs["flat-skills"]["path"].split("{")[0].rstrip("/")]
    assert pi["pi"]["extensions"] == ["./" + outs["session-extension"]["path"]]
    host = next(p for p in d["plugins"] if manifests.omp_package(p, "0.1.0", LICENSE))
    omp = manifests.omp_package(host, "0.1.0", LICENSE)
    assert pi["license"] == omp["license"] == LICENSE
    assert f"plugins/{host['name']}/" + omp["omp"]["extensions"][0][2:] == outs["session-extension"]["path"]
    assert omp["version"] == "0.1.0"          # omp lists a linked package as name@version


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
