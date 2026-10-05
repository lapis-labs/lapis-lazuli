"""tools/build/build.py: generated outputs, the sync check, skill validation, views, versions, Hermes."""
import json
import posixpath
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "build"))

import build  # noqa: E402

VERSION = "0.1.0"
PROJECT_LICENSE = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["license"]
LICENSE_LINE = f"license: {PROJECT_LICENSE}\n"


def make_root(tmp_path: Path, skills: bool = False, critic: bool = False) -> Path:
    """A copy of the sources, optionally with a synthetic SKILL.md for every listed skill and a critic."""
    root = tmp_path / "repo"
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")
    for part in ("src", "install"):
        shutil.copytree(ROOT / part, root / part, ignore=ignore)
    for name in ("pyproject.toml", *build.LICENSE_FILES):      # the build reads the license expression and texts
        shutil.copy(ROOT / name, root / name)
    if skills:
        for p in harnesses(root)["plugins"]:
            for s in p["skills"]:
                write_skill(root, s, f"name: {s}\ndescription: Use for {s} work in tests.\n{LICENSE_LINE}")
    if critic:
        (root / "src/agents").mkdir(parents=True, exist_ok=True)
        (root / "src/agents/critic.md").write_text(
            "---\nname: critic\ndescription: Reviews a render as a separate critic\n---\n\nReview it.\n")
    return root


def harnesses(root: Path) -> dict:
    return yaml.safe_load((root / "install/harnesses.yaml").read_text(encoding="utf-8"))


def write_skill(root: Path, name: str, frontmatter: str, body: str = "\n# Skill\n\nDo the work.\n") -> Path:
    d = root / "src/skills" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8")
    return d


def problems(root: Path) -> list[tuple[str, str]]:
    return build.check(build.collect(root, VERSION), root)


def test_check_passes_on_a_fresh_build(tmp_path, capsys):
    root = make_root(tmp_path, skills=True, critic=True)
    assert build.main(["--version", VERSION], root=root) == 0
    assert build.main(["--check", "--version", VERSION], root=root) == 0
    assert "match the sources" in capsys.readouterr().out


def test_check_lists_every_drift(tmp_path, capsys):
    root = make_root(tmp_path, skills=True)
    assert build.main(["--version", VERSION], root=root) == 0
    (root / "plugins/lazuli/.mcp.json").write_text("{}\n")                           # hand-edited output
    (root / "plugins/lapis/skills/lps-ux/notes.md").write_text("stray\n")             # extra file
    (root / "dist/AGENTS.snippet.md").unlink()                                       # missing output
    ext = root / "src/extensions/session-start.ts"                                   # changed source
    ext.write_text(ext.read_text(encoding="utf-8") + "// changed\n", encoding="utf-8")
    assert problems(root) == [
        ("missing", "dist/AGENTS.snippet.md"),
        ("extra", "plugins/lapis/skills/lps-ux/notes.md"),
        ("differs", "plugins/lazuli/.mcp.json"),
        ("differs", "plugins/lazuli/extensions/session-start.ts"),
    ]
    capsys.readouterr()
    assert build.main(["--check", "--version", VERSION], root=root) == 1
    err = capsys.readouterr().err
    assert "4 generated file(s) out of sync" in err
    assert re.search(r"differs\s+plugins/lazuli/\.mcp\.json", err) and re.search(r"extra\s+plugins/lapis/skills", err)


def test_a_changed_skill_source_is_drift_and_the_build_removes_what_it_no_longer_emits(tmp_path):
    root = make_root(tmp_path, skills=True)
    assert build.main(["--version", VERSION], root=root) == 0
    write_skill(root, "lps-copy", f"name: lps-copy\ndescription: Use for copy in tests.\n{LICENSE_LINE}", "\nNew body.\n")
    assert problems(root) == [("differs", "dist/skills/lps-copy/SKILL.md"),
                              ("differs", "plugins/lapis/skills/lps-copy/SKILL.md")]
    shutil.rmtree(root / "src/skills/lps-copy")
    stale = [p for p in problems(root) if p[0] == "extra"]
    assert stale and all("/lps-copy/" in rel for _, rel in stale)
    assert build.main(["--version", VERSION], root=root) == 0
    assert not (root / "dist/skills/lps-copy").exists() and not (root / "plugins/lapis/skills/lps-copy").exists()
    assert problems(root) == []


def test_check_ignores_what_git_ignores_in_a_work_tree(tmp_path):
    root = make_root(tmp_path)
    (root / ".gitignore").write_text("node_modules/\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    assert build.main(["--version", VERSION], root=root) == 0
    (root / "plugins/lazuli/node_modules").mkdir()
    (root / "plugins/lazuli/node_modules/types.d.ts").write_text("export {};\n")      # ignored: not committed
    assert problems(root) == []
    (root / "plugins/lazuli/notes.txt").write_text("untracked\n")                       # would be committed
    assert problems(root) == [("extra", "plugins/lazuli/notes.txt")]


def _keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from _keys(v)


def test_shared_views_never_carry_provenance_and_generators_get_names_and_alternatives(tmp_path):
    root = make_root(tmp_path, skills=True)
    files = build.collect(root, VERSION)
    views = {rel: text for rel, text in files.items() if re.match(r"(dist|plugins/[^/]+)/skills/[^/]+/shared/.+\.yaml$", rel)}
    assert "dist/skills/ultramarine/shared/slop/rules.yaml" in views
    assert "plugins/lapis/skills/lapis/shared/vocab/type.yaml" in views          # a full view of a data file
    for rel, text in views.items():
        assert "provenance" not in set(_keys(yaml.safe_load(text))), rel
    index = yaml.safe_load((root / "src/shared/index.yaml").read_text(encoding="utf-8"))
    rules = next(i for i in index["items"] if i["kind"] == "rules")
    generators = [s for s, v in rules["consumers"].items() if v == "names-and-alternatives"]
    assert generators
    for skill in generators:
        view = yaml.safe_load(files[f"dist/skills/{skill}/shared/{rules['path']}"])
        assert set(view) == {"version", "as_of", "rules"}                  # no lists, packages, or bounds
        assert {k for r in view["rules"] for k in r} == {"id", "why", "better", "keep_when"}
    checker = yaml.safe_load(files[f"dist/skills/ultramarine/shared/{rules['path']}"])
    assert all("detect" in r for r in checker["rules"])


PROVENANCE = "provenance:\n  - { kind: taxonomy, source: \"a maintainer-only source\" }\n  - kind: method\n    source: other\n\n"


def test_full_views_of_other_files_drop_top_level_provenance_and_keep_comments(tmp_path):
    root = make_root(tmp_path, skills=True)
    table = root / "src/shared/fonts/system-fonts.yaml"
    source = table.read_text(encoding="utf-8")
    table.write_text(source.replace("\ndefaults:", "\n" + PROVENANCE + "defaults:", 1), encoding="utf-8")
    files = build.collect(root, VERSION)
    for rel in ("dist/skills/lzl-fonts/shared/fonts/system-fonts.yaml",
                "plugins/lazuli/skills/lzl-fonts/shared/fonts/system-fonts.yaml"):
        assert files[rel] == source                                          # comments and layout kept


def test_nested_provenance_outside_rules_is_refused(tmp_path):
    root = make_root(tmp_path, skills=True)
    table = root / "src/shared/fonts/system-fonts.yaml"
    text = table.read_text(encoding="utf-8")
    table.write_text(text.replace("\ncomposition:\n", "\ncomposition:\n  provenance: [{ kind: method, source: x }]\n", 1),
                     encoding="utf-8")
    with pytest.raises(build.BuildError, match=r"fonts/system-fonts\.yaml: provenance must be a top-level key"):
        build.collect(root, VERSION)


def test_lookup_view_takes_its_fields_from_the_index(tmp_path):
    root = make_root(tmp_path, skills=True)
    index_path = root / "src/shared/index.yaml"
    index = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    plan = next(i for i in index["items"] if i["id"] == "plan-schema")
    assert plan["lookup_fields"] == ["version", "task", "brief", "references", "tokens", "sources"]
    schema = yaml.safe_load((root / "src/shared/plan/schema.yaml").read_text(encoding="utf-8"))
    full = yaml.safe_load(build.collect(root, VERSION)["dist/skills/lazuli/shared/plan/schema.yaml"])
    assert list(full["properties"]) == plan["lookup_fields"]
    assert set(full["$defs"]) < set(schema["$defs"])                         # only the definitions they reach

    plan["lookup_fields"] = ["version", "task"]
    index_path.write_text(yaml.safe_dump(index, sort_keys=False, allow_unicode=True), encoding="utf-8")
    view = yaml.safe_load(build.collect(root, VERSION)["dist/skills/lazuli/shared/plan/schema.yaml"])
    assert list(view["properties"]) == ["version", "task"] and "$defs" not in view

    del plan["lookup_fields"]
    index_path.write_text(yaml.safe_dump(index, sort_keys=False, allow_unicode=True), encoding="utf-8")
    with pytest.raises(build.BuildError, match=r"index\.yaml: plan-schema has a fields-for-lookup consumer but no lookup_fields"):
        build.collect(root, VERSION)


def test_skill_copies_are_byte_identical_and_carry_build_metadata(tmp_path):
    root = make_root(tmp_path)
    shutil.rmtree(root / "src/skills/lzl-color", ignore_errors=True)   # stands for a skill with no source yet
    shutil.rmtree(root / "src/skills/lzl-fonts")                       # replaced by a synthetic skill and reference
    write_skill(root, "lzl-fonts", f"name: lzl-fonts\ndescription: 'Use for fonts: local ones first.'\n{LICENSE_LINE}")
    (root / "src/skills/lzl-fonts/references").mkdir()
    (root / "src/skills/lzl-fonts/references/pairing.md").write_text("Pairing notes.\n")
    files = build.collect(root, "1.0")
    flat = {rel.removeprefix("dist/skills/lzl-fonts/"): v for rel, v in files.items() if rel.startswith("dist/skills/lzl-fonts/")}
    copy = {rel.removeprefix("plugins/lazuli/skills/lzl-fonts/"): v for rel, v in files.items()
            if rel.startswith("plugins/lazuli/skills/lzl-fonts/")}
    assert flat == copy and "references/pairing.md" in flat and "shared/index.yaml" in flat
    meta, _ = build._split_frontmatter(flat["SKILL.md"], "SKILL.md")
    assert meta == {"name": "lzl-fonts", "description": "Use for fonts: local ones first.", "license": PROJECT_LICENSE,
                    "metadata": {"plugin": "lazuli", "version": "1.0"}}             # a string, not the float 1.0
    assert "dist/skills/lapis/SKILL.md" in files
    assert not any(rel.startswith("dist/skills/lzl-color/") for rel in files)  # unwritten skills are skipped


@pytest.mark.parametrize(("name", "frontmatter", "message"), [
    ("lapis", "name: lps-ux\ndescription: Use for tests.\n", "must equal the directory name"),
    ("Lapis", "name: Lapis\ndescription: Use for tests.\n", "skill names are lowercase"),
    ("lps-extra", "name: lps-extra\ndescription: Use for tests.\n", "no plugin in install/harnesses.yaml lists"),
    ("lapis", f"name: lapis\ndescription: {'d' * 1025}\n", "1025 characters; the limit is 1024"),
    ("lapis", "name: lapis\ndescription: '  '\n", "description must be a non-empty string"),
    ("lapis", "name: lapis\ndescription: Use for tests.\nallowed-tools: Read\n", "not portable"),
    ("lapis", "name: lapis\ndescription: Use for tests.\nmetadata: {plugin: lapis}\n", "not portable"),
    ("lapis", "name: lapis\ndescription: [unclosed\n", "frontmatter is not YAML"),
    ("lapis", "name: lapis\ndescription: Use for tests.\n", "license None must be the project's"),
    ("lapis", "name: lapis\ndescription: Use for tests.\nlicense: MIT\n", "license 'MIT' must be the project's"),
    ("lapis", "name: lapis\ndescription: Use for tests.\nlicense: ''\n", "license '' must be the project's"),
])
def test_frontmatter_validation_rejects_a_bad_skill(tmp_path, name, frontmatter, message):
    root = make_root(tmp_path)
    if name == "Lapis":
        shutil.rmtree(root / "src/skills/lapis")  # isolate the invalid slug from the real lapis skill
    write_skill(root, name, frontmatter)
    with pytest.raises(build.BuildError, match=re.escape(message)):
        build.collect(root, VERSION)


def test_description_limit_is_inclusive(tmp_path):
    root = make_root(tmp_path)
    write_skill(root, "lapis", f"name: lapis\ndescription: {'d' * 1024}\n{LICENSE_LINE}")
    assert "dist/skills/lapis/SKILL.md" in build.collect(root, VERSION)


@pytest.mark.parametrize(("setup", "message"), [
    (lambda d: (d / "scripts").mkdir(), "holds only SKILL.md and references/"),
    (lambda d: (d / "shared").mkdir(), "holds only SKILL.md and references/"),
    (lambda d: (d / "references" / "deep").mkdir(parents=True), "references keep one level"),
    (lambda d: (d / "SKILL.md").write_text("# no frontmatter\n"), "must start with a --- frontmatter block"),
])
def test_skill_layout_is_validated(tmp_path, setup, message):
    root = make_root(tmp_path)
    setup(write_skill(root, "lapis", "name: lapis\ndescription: Use for tests.\n"))
    with pytest.raises(build.BuildError, match=re.escape(message)):
        build.collect(root, VERSION)


def test_agent_frontmatter_keeps_to_name_and_description(tmp_path):
    root = make_root(tmp_path, critic=True)
    (root / "src/agents/critic.md").write_text("---\nname: critic\ndescription: Reviews\npermissionMode: plan\n---\nx\n")
    with pytest.raises(build.BuildError, match="permissionMode"):
        build.collect(root, VERSION)


def test_critic_body_is_a_reference_when_ultramarine_skill_exists(tmp_path):
    root = make_root(tmp_path, critic=True)
    shutil.rmtree(root / "src/skills/ultramarine", ignore_errors=True)
    without_skill = build.collect(root, VERSION)
    assert not any(rel.endswith("/references/critic.md") for rel in without_skill)
    write_skill(root, "ultramarine", f"name: ultramarine\ndescription: Review designs.\n{LICENSE_LINE}",
                "\n# Skill\n\nRead `references/critic.md` before reviewing.\n")
    files = build.collect(root, VERSION)
    _, body = build._split_frontmatter((root / "src/agents/critic.md").read_text(encoding="utf-8"),
                                       "src/agents/critic.md")
    reference = body.lstrip("\n")
    assert files["dist/skills/ultramarine/references/critic.md"] == reference
    assert files["plugins/ultramarine/skills/ultramarine/references/critic.md"] == reference


def test_skill_body_reference_links_are_in_the_generated_skill():
    files = build.collect(ROOT, VERSION)
    missing = []
    for rel, body in files.items():
        if not re.fullmatch(r"dist/skills/[^/]+/SKILL\.md", rel):
            continue
        for target in re.findall(r"(?<![\w/])references/[A-Za-z0-9._-]+\.md\b", body):
            linked = (Path(rel).parent / target).as_posix()
            if linked not in files:
                missing.append((rel, target))
    assert missing == []


def test_reference_links_to_other_references_resolve_from_the_reference():
    # Links in a reference are relative to the reference itself, as for shared paths below: a sibling
    # is `type.md`, and `references/type.md` would point inside references/references/.
    files = build.collect(ROOT, VERSION)
    missing = []
    for rel, body in files.items():
        if not re.fullmatch(r"dist/skills/[^/]+/references/[^/]+\.md", rel):
            continue
        for target in re.findall(r"(?<![\w/.-])(?:\.\.?/)*(?:references/)?[a-z0-9][a-z0-9_-]*\.md\b", body):
            linked = posixpath.normpath(posixpath.join(posixpath.dirname(rel), target))
            if linked not in files:
                missing.append((rel, target))
    assert missing == []


def test_every_reference_is_named_in_its_skill_body():
    files = build.collect(ROOT, VERSION)
    unnamed = []
    for rel in files:
        if m := re.fullmatch(r"(dist/skills/[^/]+)/(references/[^/]+\.md)", rel):
            if m[2] not in files[f"{m[1]}/SKILL.md"]:
                unnamed.append(rel)
    assert unnamed == []


def _missing_shared_paths(files: dict[str, str]) -> list[tuple[str, str]]:
    """Collect links from generated skill bodies that do not resolve to a file of the same skill."""
    missing = []
    for rel, body in files.items():
        if not (m := re.fullmatch(r"(dist/skills/[^/]+)/(?:SKILL\.md|references/[^/]+\.md)", rel)):
            continue
        skill_dir = m[1] + "/"
        for target in re.findall(
            r"(?<![\w/.])(?:\.\.?/)*shared/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_.-]+)*\.(?:ya?ml|md|json)\b",
            body,
        ):
            linked = posixpath.normpath(posixpath.join(posixpath.dirname(rel), target))
            if not linked.startswith(skill_dir) or linked not in files:
                missing.append((rel, target))
    return missing


def test_skill_body_shared_paths_are_in_the_generated_skill():
    assert _missing_shared_paths(build.collect(ROOT, VERSION)) == []


@pytest.mark.parametrize(("source", "target", "exists"), [
    ("SKILL.md", "shared/vocab/type.yaml", True),
    ("SKILL.md", "./shared/vocab/type.yaml", True),
    ("SKILL.md", "./shared/vocab/missing.yaml", False),
    ("references/notes.md", "../shared/vocab/type.yaml", True),
    ("references/notes.md", "../shared/vocab/missing.yaml", False),
    ("references/notes.md", "shared/vocab/type.yaml", False),
    ("SKILL.md", "../../shared/vocab/type.yaml", False),
    ("references/notes.md", "./../shared/vocab/type.yaml", True),
])
def test_shared_links_resolve_from_each_skill_body(source, target, exists):
    rel = f"dist/skills/lapis/{source}"
    files = {rel: f"Read `{target}` before editing.\n",
             "dist/skills/lapis/shared/vocab/type.yaml": "version: 0\n"}
    assert _missing_shared_paths(files) == ([] if exists else [(rel, target)])


def test_shared_link_outside_its_skill_is_missing_even_when_the_file_exists():
    rel = "dist/skills/lapis/references/notes.md"
    files = {rel: "Read `../../shared/vocab/type.yaml` before editing.\n",
             "dist/skills/shared/vocab/type.yaml": "version: 0\n"}
    assert _missing_shared_paths(files) == [(rel, "../../shared/vocab/type.yaml")]


def test_plugin_skill_copies_equal_the_flat_skills():
    # `npx skills add <checkout>` reads plugins/*/skills through the Claude catalog, the documented
    # install reads dist/skills; both must hand out the same skills with the same bytes.
    files = build.collect(ROOT, VERSION)
    flat, plugin = {}, {}
    for rel, body in files.items():
        if m := re.fullmatch(r"dist/skills/([^/]+)/(.+)", rel):
            flat.setdefault(m[1], {})[m[2]] = body
        elif m := re.fullmatch(r"plugins/[^/]+/skills/([^/]+)/(.+)", rel):
            assert m[1] not in plugin or m[2] not in plugin[m[1]], f"{m[1]} is in two plugins"
            plugin.setdefault(m[1], {})[m[2]] = body
    assert sorted(plugin) == sorted(flat)
    assert {s: sorted(c for c in flat[s] if plugin[s].get(c) != flat[s][c]) for s in flat} == {s: [] for s in flat}
    assert {s: sorted(set(plugin[s]) - set(flat[s])) for s in flat} == {s: [] for s in flat}


def _installable_folders(doc: dict) -> list[str]:
    """Every generated folder that a harness can install on its own."""
    return [*(f"plugins/{p['name']}" for p in doc["plugins"]), "plugins/hermes/lapis-lazuli",
            *(f"dist/skills/{s}" for p in doc["plugins"] for s in p["skills"]),
            *(f"plugins/{p['name']}/skills/{s}" for p in doc["plugins"] for s in p["skills"])]


def test_every_installable_folder_carries_both_license_texts_and_the_notice_byte_for_byte():
    texts = ("LICENSE", "LICENSE-docs", "NOTICE")                     # NOTICE names the quoted third-party terms
    files = build.collect(ROOT, VERSION)
    wrong = [f"{folder}/{name}" for folder in _installable_folders(harnesses(ROOT)) for name in texts
             if files.get(f"{folder}/{name}") != (ROOT / name).read_bytes()]
    assert wrong == []
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["license-files"] == list(texts)      # the wheel and sdist carry the same files


def test_every_generated_skill_and_manifest_states_the_project_license():
    files = build.collect(ROOT, VERSION)
    plugins = harnesses(ROOT)["plugins"]
    skills = {rel: build._split_frontmatter(body, rel)[0].get("license") for rel, body in files.items()
              if re.fullmatch(r"(dist/skills|plugins/[^/]+/skills)/[^/]+/SKILL\.md", rel)}
    assert len(skills) == 2 * sum(len(p["skills"]) for p in plugins)
    assert set(skills.values()) == {PROJECT_LICENSE}
    manifest = re.compile(r"(plugins/[^/]+/)?(\.claude-plugin/plugin\.json|\.codex-plugin/plugin\.json|package\.json)")
    found = {rel for rel in files if manifest.fullmatch(rel)}
    assert {"package.json", *(f"plugins/{p['name']}/{m}" for p in plugins
                              for m in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"))} <= found
    assert {json.loads(files[rel]).get("license") for rel in found} == {PROJECT_LICENSE}


def test_the_license_comes_from_pyproject_and_every_skill_source_must_agree(tmp_path):
    root = make_root(tmp_path, skills=True)
    pyproject = root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text(encoding="utf-8").replace(
        f'license = "{PROJECT_LICENSE}"', 'license = "Apache-2.0"'), encoding="utf-8")
    with pytest.raises(build.BuildError, match=re.escape("must be the project's 'Apache-2.0'")):
        build.collect(root, VERSION)                                  # the skill sources still say the old one
    for p in harnesses(root)["plugins"]:
        for s in p["skills"]:
            write_skill(root, s, f"name: {s}\ndescription: Use for {s} work in tests.\nlicense: Apache-2.0\n")
    files = build.collect(root, VERSION)
    manifests = [rel for rel in files if rel.endswith(("plugin.json", "package.json"))]
    assert manifests and {json.loads(files[rel])["license"] for rel in manifests} == {"Apache-2.0"}
    assert build._split_frontmatter(files["dist/skills/lapis/SKILL.md"], "SKILL.md")[0]["license"] == "Apache-2.0"


@pytest.mark.parametrize(("edit", "message"), [
    (lambda root: (root / "LICENSE-docs").unlink(), "LICENSE-docs: the license text is missing"),
    (lambda root: (root / "pyproject.toml").write_text('[project]\nlicense = { text = "MIT" }\n'),
     "must be an SPDX expression string"),
    (lambda root: (root / "pyproject.toml").write_text('[project]\nname = "x"\n'), "cannot read [project] license"),
])
def test_a_missing_license_text_or_expression_stops_the_build(tmp_path, edit, message):
    root = make_root(tmp_path)
    edit(root)
    with pytest.raises(build.BuildError, match=re.escape(message)):
        build.collect(root, VERSION)


def test_a_changed_license_text_is_drift_in_every_copy_until_rebuilt(tmp_path):
    root = make_root(tmp_path, skills=True)
    assert build.main(["--version", VERSION], root=root) == 0
    (root / "LICENSE").write_text("Changed.\n", encoding="utf-8")
    assert problems(root) == [("differs", rel) for rel in
                              sorted(f"{folder}/LICENSE" for folder in _installable_folders(harnesses(root)))]
    assert build.main(["--version", VERSION], root=root) == 0
    assert problems(root) == []


def _matches(template: str, rel: str, doc: dict, out: dict) -> bool:
    plugins = out.get("only") or [p["name"] for p in doc["plugins"]]
    skills = [s for p in doc["plugins"] for s in p["skills"]]
    pattern = re.escape(template).replace(r"\{plugin\}", "(" + "|".join(plugins) + ")")
    pattern = pattern.replace(r"\{skill\}", "(" + "|".join(skills) + ")")
    return re.fullmatch(pattern + (".+" if template.endswith("/") else ""), rel) is not None


def test_every_output_in_harnesses_yaml_is_emitted_at_its_path(tmp_path):
    root = make_root(tmp_path, skills=True, critic=True)
    doc = harnesses(root)
    files = build.collect(root, VERSION)
    owners = {rel: [o["id"] for o in doc["outputs"] if _matches(o["path"], rel, doc, o)] for rel in files}
    licenses = {f"plugins/{p['name']}/{name}" for p in doc["plugins"] for name in build.LICENSE_FILES}
    assert {rel: ids for rel, ids in owners.items()
            if len(ids) != 1 and rel not in build.INSTALLER_PATHS and rel not in licenses} == {}   # texts: not outputs
    assert {o["id"] for o in doc["outputs"]} == {i for ids in owners.values() for i in ids}


def test_an_output_list_that_misses_a_plugin_is_an_error(tmp_path):
    root = make_root(tmp_path)
    path = root / "install/harnesses.yaml"
    doc = harnesses(root)
    next(p for p in doc["plugins"] if p["name"] == "lapis")["mcp"] = ["lapis-lazuli"]   # but plugin-mcp only: [lazuli]
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    with pytest.raises(build.BuildError, match=r"plugin-mcp leaves out plugin lapis"):
        build.collect(root, VERSION)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", "-c", "core.hooksPath=/dev/null",
                    *args], check=True, capture_output=True)


def test_a_release_version_equal_to_the_previous_tag_is_refused(tmp_path, capsys):
    root = make_root(tmp_path)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "first release")
    _git(root, "tag", "v0.1.0")
    assert build.main(["--version", "0.1.0"], root=root) == 0          # rebuilding a release at its own tag
    (root / "src/hermes/plugin.yaml").write_text("description: Changed\nprovides_hooks: [pre_llm_call]\n")
    _git(root, "commit", "-qam", "change")
    capsys.readouterr()
    assert build.main(["--version", "0.1.0"], root=root) == 2
    assert "v0.1.0 is the previous release tag" in capsys.readouterr().err
    assert build.main(["--version", "0.2.0"], root=root) == 0


