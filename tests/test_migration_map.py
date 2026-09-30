"""Migration-map destinations, reference provenance, and maintainer-only build inputs."""
from pathlib import Path

import yaml


MAP = Path(__file__).resolve().parents[1] / "tools" / "migration-map.yaml"
REFERENCE_DESTINATIONS = {
    "references/fonts/pairing-and-role-systems.md": "partial",
    "references/fonts/display-and-expressive-type.md": "done",
    "references/fonts/multilingual-font-selection.md": "done",
    "references/fonts/monospace-and-numeric-typography.md": "done",
    "references/typography/multiscript-typesetting.md": "partial",
    "references/typography/paragraphs-and-reading.md": "partial",
    "references/typography/responsive-typesetting.md": "done",
    "assets/display-type-selection-card.md": "partial",
    "assets/type-scale-cheatsheet.md": "partial",
    "references/color/palette-art-direction.md": "partial",
    "references/color/perceptual-authoring-and-tokens.md": "partial",
}


# Sources of the layout and archetype references: (status, done destinations). A source whose other
# destination (a rule) is still open stays partial.
LAYOUT_REFERENCES = {
    "lapis/references/layout.md": {
        "references/layout/layout-decision-procedure.md": ("done", ["schema", "reference"]),
        "references/fundamentals/spacing-and-grids.md": ("done", ["merge"]),
        "assets/spacing-and-grid-cheatsheet.md": ("done", ["merge"]),
        "assets/shape-line-and-layout-cheatsheet.md": ("done", ["merge"]),
        "references/fundamentals/visual-hierarchy-and-composition.md": ("partial", ["reference"]),
        "references/layout/responsive-and-adaptive.md": ("partial", ["reference"]),
        "references/layout/density-and-data-heavy-ui.md": ("done", ["reference"]),
    },
    "lapis/references/archetypes.md": {
        "references/layout/page-and-screen-archetypes.md": ("done", ["reference"]),
        "assets/layout-archetype-cards.md": ("done", ["merge"]),
        "references/layout/marketing-sections-and-rhythm.md": ("partial", ["reference"]),
        **{f"references/product-types/{name}.md": ("done", ["merge"]) for name in (
            "consumer-mobile-app", "content-editorial-and-docs", "developer-tools", "e-commerce",
            "fintech-and-regulated", "games-and-entertainment", "internal-tools", "marketing-and-landing",
            "portfolio-and-personal", "saas-dashboard-and-admin")},
    },
}


# Sources of the lps-system, lps-ux, and ulm-release references, same shape. The two other recorded sources
# of theming.md go to tokens.md, so only their tokens.md destination is tracked.
SYSTEM_REFERENCES = {
    "lps-system/references/tokens.md": {
        "references/design-systems/design-tokens.md": ("done", ["merge"]),
        "references/interop/design-tokens-dtcg.md": ("done", ["merge"]),
        "references/color/perceptual-authoring-and-tokens.md": ("partial", ["reference"]),
    },
    "lps-system/references/theming.md": {
        "references/design-systems/theming-and-dark-mode.md": ("done", ["merge"]),
    },
    "lps-ux/references/navigation.md": {
        "references/ux-methodology/information-architecture.md": ("done", ["reference"]),
        "references/layout/navigation-patterns.md": ("done", ["reference"]),
    },
    "ulm-release/references/visual-regression.md": {
        "references/design-feedback/comparison-and-regression.md": ("done", ["reference"]),
        "references/production/design-qa-and-visual-regression.md": ("done", ["reference"]),
    },
}


# Sources of the lps-copy interface-copy reference, same shape. The two readability sources that also list a
# rule destination stay partial until it is done. user-messages-and-feedback and i18n-l10n-and-rtl give the
# reference only their copy-facing parts, so their other targets keep them todo and they are not tracked.
COPY_REFERENCES = {
    "lps-copy/references/interface-copy.md": {
        "references/fundamentals/ux-writing-and-microcopy.md": ("done", ["merge"]),
        "references/ux-methodology/content-design.md": ("done", ["merge"]),
        "references/readability/diagnosis-and-editing.md": ("done", ["reference"]),
        "references/readability/interface-copy-and-meta-text.md": ("partial", ["reference"]),
        "references/readability/korean-editing.md": ("partial", ["reference"]),
        "references/readability/locale-and-surface-review.md": ("done", ["reference"]),
        "assets/brand-voice-by-locale-cheatsheet.md": ("done", ["reference"]),
        "assets/readability-review-card.md": ("done", ["reference"]),
    },
}


def assert_sources_track_their_reference(references):
    root = MAP.parents[1]
    entries = {entry["path"]: entry for entry in yaml.safe_load(MAP.read_text(encoding="utf-8"))["entries"]}
    provenance = yaml.safe_load((root / "tools/reference-provenance.yaml").read_text(encoding="utf-8"))
    recorded = {reference["reference"]: {source["path"] for source in reference["sources"]}
                for reference in provenance["references"]}
    for reference, sources in references.items():
        assert (root / "src/skills" / reference).is_file(), reference
        assert set(sources) <= recorded[reference], reference
        for path, (status, done) in sources.items():
            entry = entries[path]
            assert entry["status"] == status, path
            assert entry["done"] == done, path
            assert set(done) <= set(entry["dest"]), path
            assert reference in entry["target"], path


def test_layout_and_archetype_sources_track_their_reference():
    assert_sources_track_their_reference(LAYOUT_REFERENCES)


def test_system_navigation_and_regression_sources_track_their_reference():
    assert_sources_track_their_reference(SYSTEM_REFERENCES)


def test_copy_sources_track_their_reference():
    assert_sources_track_their_reference(COPY_REFERENCES)


def test_each_style_reference_has_its_own_flat_destination():
    entries = yaml.safe_load(MAP.read_text(encoding="utf-8"))["entries"]
    style_references = [entry for entry in entries if entry.get("target") == "lapis/references/styles/"
                        or entry["path"] == "assets/style-cards.md"
                        or (entry["path"].startswith("references/styles/") and "reference" in entry["dest"]
                            and entry["target"].startswith("lapis/references/style-"))]
    assert len(style_references) == 9
    for entry in style_references:
        source = Path(entry["path"])
        name = "cards" if source.name == "style-cards.md" else source.stem
        assert entry["target"] == f"lapis/references/style-{name}.md"


def test_type_and_color_sources_track_completed_reference_destinations():
    entries = {entry["path"]: entry for entry in yaml.safe_load(MAP.read_text(encoding="utf-8"))["entries"]}
    for path, status in REFERENCE_DESTINATIONS.items():
        entry = entries[path]
        assert entry["status"] == status, path
        assert entry["done"] == ["reference"], path
        assert "reference" in entry["dest"], path
        if status == "done":
            assert entry["dest"] == ["reference"], path
        else:
            assert len(entry["dest"]) > 1, path


def test_reference_provenance_accounts_for_migrated_sources():
    root = MAP.parents[1]
    tracked = set(REFERENCE_DESTINATIONS)
    provenance = yaml.safe_load((root / "tools/reference-provenance.yaml").read_text(encoding="utf-8"))
    sources = {source["path"] for reference in provenance["references"] for source in reference["sources"]}
    assert tracked <= sources


def test_build_does_not_read_maintainer_only_tools(tmp_path, monkeypatch):
    import shutil
    import sys

    root = MAP.parents[1]
    sys.path.insert(0, str(root / "tools/build"))
    import build

    test_root = tmp_path / "repo"
    for directory in ("src", "install"):
        shutil.copytree(root / directory, test_root / directory)
    for name in ("pyproject.toml", *build.LICENSE_FILES):      # the build reads the license and copies its texts
        shutil.copy(root / name, test_root / name)
    (test_root / "tools").mkdir()
    (test_root / "tools/reference-provenance.yaml").write_text("not: [valid yaml\n", encoding="utf-8")

    original_open = Path.open
    original_iterdir = Path.iterdir

    def guarded_open(path, *args, **kwargs):
        assert not path.is_relative_to(test_root / "tools"), path
        return original_open(path, *args, **kwargs)

    def guarded_iterdir(path):
        assert not path.is_relative_to(test_root / "tools"), path
        return original_iterdir(path)

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(Path, "iterdir", guarded_iterdir)
    assert build.collect(test_root, "0.1.0")
