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


# Sources of the ultramarine inspection-and-evidence reference, same shape. ui-audit-procedure gives the
# reference only its evidence labels and their combination rule, so its card destination keeps it partial.
INSPECTION_REFERENCES = {
    "ultramarine/references/inspection-and-evidence.md": {
        "references/design-feedback/inspection-and-evidence.md": ("done", ["reference"]),
        "references/quality/ui-audit-procedure.md": ("partial", ["reference"]),
    },
}


# Sources of the lapis motion reference, same shape. fundamentals/motion.md also goes to the engine-principles
# card, so its reference destination alone keeps it partial.
MOTION_REFERENCES = {
    "lapis/references/motion.md": {
        "references/animation/animation-assets-and-delivery.md": ("done", ["merge"]),
        "references/animation/interaction-choreography.md": ("done", ["merge"]),
        "references/animation/scroll-navigation-and-transitions.md": ("done", ["merge"]),
        "references/technology/animation-and-motion-libraries.md": ("done", ["merge"]),
        "assets/motion-cheatsheet.md": ("done", ["merge"]),
        "assets/motion-delivery-cheatsheet.md": ("done", ["merge"]),
        "references/fundamentals/motion.md": ("partial", ["reference"]),
    },
}


# Sources of the lps-ux forms-and-recovery reference, same shape. interaction-design, the state-transition card, and
# user-messages-and-feedback give it only parts and keep destinations it does not serve (cards, rules, a later
# interaction reference, the lps-copy split), so they stay todo and are not tracked.
FORMS_REFERENCES = {
    "lps-ux/references/forms-and-recovery.md": {
        "references/product-types/forms-onboarding-and-checkout.md": ("done", ["reference"]),
    },
}


# Sources of the lapis data-viz reference, same shape. The data-scale source also keeps a rule destination and the
# token mechanics of lps-system, so it stays partial.
DATA_VIZ_REFERENCES = {
    "lapis/references/data-viz.md": {
        "references/product-types/data-visualization.md": ("done", ["merge"]),
        "references/technology/data-visualization-implementation.md": ("done", ["merge"]),
        "assets/chart-accessibility-card.md": ("done", ["merge"]),
        "references/color/semantic-and-data-palettes.md": ("partial", ["reference"]),
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


def test_inspection_sources_track_their_reference():
    assert_sources_track_their_reference(INSPECTION_REFERENCES)


def test_motion_sources_track_their_reference():
    assert_sources_track_their_reference(MOTION_REFERENCES)


def test_forms_sources_track_their_reference():
    assert_sources_track_their_reference(FORMS_REFERENCES)


def test_data_viz_sources_track_their_reference():
    assert_sources_track_their_reference(DATA_VIZ_REFERENCES)




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


def test_repair_sources_track_their_reference():
    assert_sources_track_their_reference({
        "ultramarine/references/repair-loop.md": {
            "references/design-feedback/bounded-closed-loop.md": ("done", ["card", "reference"]),
            "references/creative-workflows/revision-and-feedback-loops.md": ("done", ["merge"]),
            "references/design-feedback/diagnosis-and-repair.md": ("done", ["merge"]),
            "references/quality/critique-and-feedback.md": ("partial", ["reference"]),
            "references/quality/improvement-playbook.md": ("done", ["merge"]),
            "assets/diagnostic-checklists.md": ("done", ["reference"]),
            "assets/ui-audit-rubric.md": ("done", ["reference"]),
        },
    })


def test_bento_and_editorial_sources_track_their_reference():
    assert_sources_track_their_reference({
        "lapis/references/style-bento-and-modern-saas.md": {
            "references/styles/bento-and-modern-saas.md": ("done", ["reference"]),
        },
        "lapis/references/style-minimalism-and-editorial.md": {
            "references/styles/minimalism-and-editorial.md": ("done", ["reference"]),
        },
    })


def test_check_bounds_tracks_its_split_destinations():
    root = MAP.parents[1]
    reference = "ultramarine/references/check-bounds.md"
    entries = {entry["path"]: entry for entry in yaml.safe_load(MAP.read_text(encoding="utf-8"))["entries"]}
    provenance = yaml.safe_load((root / "tools/reference-provenance.yaml").read_text(encoding="utf-8"))
    recorded = next(item for item in provenance["references"] if item["reference"] == reference)
    sources = {
        "references/fundamentals/motion.md": "reference",
        "references/product-types/data-visualization.md": "merge",
        "references/product-types/forms-onboarding-and-checkout.md": "reference",
    }
    assert (root / "src/skills" / reference).is_file()
    assert set(sources) == {source["path"] for source in recorded["sources"]}
    for source, destination in sources.items():
        entry = entries[source]
        assert reference in entry["target"], source
        assert entry["status"] in ("partial", "done"), source
        assert destination in entry["done"], source
        assert destination in entry["dest"], source


def test_form_lever_sources_track_their_reference():
    assert_sources_track_their_reference({
        "lapis/references/form-levers.md": {
            "references/art-direction/bold-expression-and-restraint.md": ("partial", ["reference"]),
            "references/art-direction/concept-development.md": ("partial", ["card", "reference"]),
            **{f"references/artistic-methods/{name}.md": ("partial", ["merge"]) for name in (
                "form-meaning-and-experience", "metaphor-motif-and-symbol", "participation-and-interaction",
                "rhythm-time-and-narrative", "tension-balance-and-asymmetry",
                "texture-materiality-and-tactility", "typography-as-form")},
        },
    })


def test_direction_principle_sources_close_their_card_destination():
    entries = {entry["path"]: entry for entry in yaml.safe_load(MAP.read_text(encoding="utf-8"))["entries"]}
    closed = {
        "references/fundamentals/color.md": "done",
        "references/fundamentals/typography.md": "done",
        "assets/response-templates.md": "done",
        "references/fundamentals/what-design-is.md": "partial",
        "references/quality/what-good-design-is.md": "partial",
        "assets/color-and-contrast-cheatsheet.md": "partial",
    }
    for path, status in closed.items():
        entry = entries[path]
        assert "lapis card" in entry["target"], path
        assert entry["status"] == status, path
        assert entry["done"] == ["merge"], path
        assert (status == "done") == (entry["dest"] == ["merge"]), path


def test_font_choice_sources_track_the_type_reference():
    assert_sources_track_their_reference({
        "lapis/references/type.md": {
            "references/fonts/font-fit-and-overuse.md": ("partial", ["reference"]),
            "references/fonts/pairing-and-role-systems.md": ("partial", ["reference"]),
            "assets/multilingual-font-stacks.md": ("partial", ["reference"]),
        },
    })
