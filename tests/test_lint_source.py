"""slop_lint source-layer detectors on small project trees written into each test's temp folder.

Every rule that detects at the source layer with css-font-family, css-literal-color,
css-off-scale-value, source-pattern, source-ast, or dependency-check has a firing case in
FIRING below (the parametrized test runs each rule in rules.yaml), and the tests after it cover
the non-firing, boundary, and skip cases per detector.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
import yaml

import lapis_design.lint.detectors.source  # noqa: F401  (registers the source detectors)
from lapis_design import shared_dir
from lapis_design.lint.types import DETECTORS, Context, Result

SHARED = shared_dir()
RULES = yaml.safe_load((SHARED / "slop" / "rules.yaml").read_text(encoding="utf-8"))
RULE = {r["id"]: r for r in RULES["rules"]}
SOURCE_DETECTORS = {"css-font-family", "css-literal-color", "css-off-scale-value", "source-pattern", "source-ast",
                    "dependency-check"}
SOURCE_RULES = sorted(rid for rid, r in RULE.items()
                      if ((r.get("detect") or {}).get("source") or {}).get("detector") in SOURCE_DETECTORS)
PLAN = yaml.safe_load((SHARED / "plan" / "example.plan.yaml").read_text(encoding="utf-8"))
LOCK = json.loads((SHARED / "fonts" / "example.fonts.lock.json").read_text(encoding="utf-8"))


def project(root: Path, files: dict[str, str | dict]) -> Path:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(content) if isinstance(content, dict) else textwrap.dedent(content)
        path.write_text(text, encoding="utf-8")
    return root


def lint(rule_id: str, root: Path | None, plan: dict | None = None, lock: dict | None = None,
         det: dict | None = None) -> Result:
    rule = RULE[rule_id]
    det = det or rule["detect"]["source"]
    ctx = Context(rules=RULES, source_root=root, plan=plan, lock=lock)
    return DETECTORS[det["detector"]].fn(ctx, det, rule, "source")


def observed(result: Result) -> str:
    return "\n".join(h.observed for h in result.hits)


def plan_with(**tokens) -> dict:
    plan = yaml.safe_load(yaml.safe_dump(PLAN))
    plan["tokens"].update(tokens)
    return plan


SCALES = {"space": {"scale": [0, 4, 8, 12, 16, 24, 32]}}

# rule id -> (files, plan, lock, text the hit's observation contains)
FIRING_HEADING_BREAK = {
    "index.html": "<h1>여백의<br>형태</h1>",
    "styles.css": "@media (max-width: 560px) { h1 br { display: none; } }",
}

FIRING: dict[str, tuple[dict, dict | None, dict | None, str]] = {
    "system.font-outside-contract": ({"src/app.css": "body {\n  font-family: \"Inter\", sans-serif;\n}\n"},
                                     PLAN, LOCK, "'Inter' is not a contract family"),
    "system.literal-color": ({"src/components/card.css": ".card { background: #1F2937; }\n"}, None, None,
                             "literal color #1f2937"),
    "system.off-scale-value": ({"src/app.css": ".card { padding: 13px; }\n"}, plan_with(**SCALES), None,
                               "padding 13px"),
    "system.bypassed-primitive": ({
        "src/components/ui/button.tsx": "export function Button(props) {\n  return <button className=\"btn\" {...props} />\n}\n",
        "src/app/page.tsx": "import { Button } from \"@/components/ui/button\"\n"
                            "export default function Page() {\n  return <div><Button>Ok</Button><button onClick={go}>Go</button></div>\n}\n",
    }, None, None, "raw <button> while the project has a Button primitive"),
    "type.negative-tracking": ({"src/app.css": "h1 { letter-spacing: -0.05em; }\n"}, None, None, "letter-spacing"),
    "surface.glass-everywhere": ({"src/Nav.tsx": "export const Nav = () => <nav className=\"backdrop-blur-md\" />\n"},
                                 None, None, "'backdrop-blur'"),
    "component.emoji-icons": ({"src/features.ts": "export const features = [{ icon: \"🚀\", title: \"Fast deploys\" }]\n"},
                              None, None, "'🚀'"),
    "component.hand-drawn-icons": ({"src/Dialog.tsx": "export const Close = () => (\n  <button aria-label=\"Close\">\n"
                                                      "    <svg viewBox=\"0 0 24 24\"><path d=\"M18 6 6 18M6 6l12 12\" /></svg>\n"
                                                      "  </button>\n)\n"}, None, None, "standard action (close)"),
    "component.mixed-icon-families": ({
        "package.json": {"dependencies": {"lucide-react": "^0.400.0", "@heroicons/react": "^2.1.0"}},
        "src/A.tsx": "import { Search } from \"lucide-react\"\nexport const A = () => <Search />\n",
        "src/B.tsx": "import { XMarkIcon } from \"@heroicons/react/24/outline\"\nexport const B = () => <XMarkIcon />\n",
    }, None, None, "2 icon families imported"),
    "component.unlabeled-input": ({"src/Form.tsx": "export const F = () => <input type=\"email\" placeholder=\"Email\" />\n"},
                                  None, None, "whose only label is its placeholder 'Email'"),
    "motion.pulse-without-status": ({"src/Dot.tsx": "export const Dot = () => <span className=\"animate-pulse\" />\n"},
                                    None, None, "'animate-pulse'"),
    "motion.decorative-cursor": ({"src/app.css": "@keyframes blink { 50% { opacity: 0 } }\n"}, None, None,
                                 "'@keyframes blink'"),
    "motion.bounce-default": ({"src/app.css": ".pop { transition: transform 300ms cubic-bezier(0.34, 1.56, 0.64, 1); }\n"},
                              None, None, "cubic-bezier"),
    "motion.layout-property-animation": ({"src/app.css": ".panel { transition: width 200ms ease; }\n"}, None, None,
                                         "width"),
    "motion.transition-all": ({"src/app.css": ".btn { transition: all .2s; }\n"}, None, None, "'transition: all'"),
    "imagery.missing-content-image": ({"index.html": "<main><img src=\"/pots/1.jpg\"></main>\n"}, None, None,
                                      "<img> without an alt attribute"),
    "code.mobile-100vh": ({"src/app.css": ".shell { min-height: 100vh; }\n"}, None, None, "'100vh'"),
    "code.focus-outline-removed": ({"src/app.css": "button:focus { outline: none; }\n"}, None, None, "outline: none;"),
    "code.clickable-non-interactive": ({"src/Card.tsx": "export const Card = () => <div onClick={open}>Open</div>\n"},
                                       None, None, "<div> has a onClick handler without an interactive role, tabindex"),
    "code.image-dimensions": ({"index.html": "<img src=\"/pots/1.jpg\" alt=\"A bowl\">\n"}, None, None,
                              "<img> without width or height"),
    "code.locale-time-rendering": ({"src/Posted.tsx": "export const P = ({ d }) => <time>{d.toLocaleDateString()}</time>\n"},
                                   None, None, "toLocaleDateString without a locale"),
    "code.continuous-value-in-state": ({
        "src/Spot.tsx": "export function Spot() {\n  const [x, setX] = useState(0)\n"
                        "  return <div onMouseMove={(e) => setX(e.clientX)} />\n}\n",
    }, None, None, "setX() runs in the onMouseMove handler"),
    "code.animation-package-mismatch": ({
        "package.json": {"dependencies": {"framer-motion": "^11.0.0"}},
        "src/Fade.tsx": "import { motion } from \"motion/react\"\nexport const Fade = () => <motion.div />\n",
    }, None, None, "imports motion (1 file), which is not installed"),
    "type.hidden-heading-break": (FIRING_HEADING_BREAK, None, None, "joins heading text"),
}


@pytest.mark.parametrize("rule_id", SOURCE_RULES)
def test_every_source_rule_fires_on_its_case(tmp_path, rule_id):
    files, plan, lock, expected = FIRING[rule_id]
    result = lint(rule_id, project(tmp_path, files), plan=plan, lock=lock)
    assert result.hits, result.skipped
    assert expected in observed(result)
    assert all(h.evidence == "source" and h.location.get("file") for h in result.hits)


@pytest.mark.parametrize("detector_name", sorted(SOURCE_DETECTORS))
def test_no_source_tree_is_skipped(detector_name):
    rule_id = next(r for r in SOURCE_RULES if RULE[r]["detect"]["source"]["detector"] == detector_name)
    result = lint(rule_id, None, plan=PLAN, lock=LOCK)
    assert result.skipped == "no source tree given" and not result.hits



@pytest.mark.parametrize("heading, css, fires", [
    ("<h1>여백의<br>형태</h1>", "@media (max-width:560px){h1 br{display:none}}", True),
    ("<h1>여백의 <br>형태</h1>", "@media (max-width:560px){h1 br{display:none}}", False),
    ("<h1>여백의<br> 형태</h1>", "@media (max-width:560px){h1 br{display:none}}", False),
    ("<h1>여백의&nbsp;<br>형태</h1>", "@media (max-width:560px){h1 br{display:none}}", False),
    ("<h1>여백의<br>형태</h1>", "h1 br{display:none}", False),
    ("<h1>여백의<br>형태</h1>", "@media (max-width:560px){h2 br{display:none}}", False),
    ("<h1><em>Quiet</em><br class='phone'><span>forms</span></h1>",
     "@media (width < 600px){h1 > br.phone{display:none!important}}", True),
])
def test_hidden_heading_break_preserves_word_separation(tmp_path, heading, css, fires):
    from lapis_design.lint.engine import lint as findings

    root = project(tmp_path, {"index.html": heading, "style.css": css})
    result = findings(Context(rules=RULES, source_root=root), ["source"], ["type.hidden-heading-break"])
    assert [(f["severity"], f["blocking"]) for f in result] == (
        [({"create": "warn", "review": "P2"}, False)] if fires else [])

# ---------------------------------------------------------------- reading the tree

def test_locations_are_the_file_line(tmp_path):
    root = project(tmp_path, {"src/app.css": "/* shell */\n\n.shell {\n  min-height: 100vh;\n}\n"})
    [hit] = lint("code.mobile-100vh", root).hits
    assert hit.location == {"file": "src/app.css:4"}


def test_comments_are_not_read_but_strings_are(tmp_path):
    root = project(tmp_path, {
        "src/a.css": "/* no backdrop-filter here */\n.a { color: red }\n",
        "src/b.tsx": "// backdrop-filter was removed\nconst url = \"https://example.com/x\"; const c = 'backdrop-blur'\n",
        "src/c.html": "<!-- <div class=\"backdrop-blur\"> -->\n<p>plain</p>\n",
    })
    result = lint("surface.glass-everywhere", root)
    assert [h.location["file"] for h in result.hits] == ["src/b.tsx:2"]


def test_dependency_and_build_folders_are_not_read(tmp_path):
    root = project(tmp_path, {
        "node_modules/pkg/index.css": ".x { min-height: 100vh }\n",
        "dist/app.css": ".x { min-height: 100vh }\n",
        "src/app.min.css": ".x{min-height:100vh}\n",
        "src/app.test.tsx": "const x = 'h-screen'\n",
        "src/app.css": ".x { min-height: 100dvh }\n",
    })
    assert lint("code.mobile-100vh", root).hits == []


# ---------------------------------------------------------------- css-font-family

def test_contract_families_and_system_fallbacks_pass(tmp_path):
    root = project(tmp_path, {"src/app.css": """
        body { font-family: Pretendard, "Apple SD Gothic Neo", "Malgun Gothic", system-ui, sans-serif; }
        h1 { font: 700 2rem/1.2 'Gowun Batang', serif; }
        code { font-family: var(--font-code); }
        :root { --font-body: "Pretendard Variable", sans-serif; --font-size-lg: 1.25rem; }
        @font-face { font-family: "Local Alias"; src: url(/fonts/a.woff2); }
        """})
    result = lint("system.font-outside-contract", root, plan=PLAN, lock=LOCK)
    assert result.hits == [] and result.skipped is None

def test_css_generic_keywords_are_case_insensitive(tmp_path):
    root = project(tmp_path, {"src/app.css": """
        body { font-family: Pretendard, SYSTEM-UI; }
        h1 { font: 700 2rem/1.2 'Gowun Batang', System-UI; }
        code { font: SYSTEM-UI; }
        """})
    result = lint("system.font-outside-contract", root, plan=PLAN, lock=LOCK)
    assert result.hits == [] and result.skipped is None


def test_css_generic_keywords_are_those_of_the_font_table(tmp_path, house_generics):
    root = project(tmp_path / "app", {"src/app.css": """
        body { font-family: Pretendard, House-Stack; }
        h1 { font: 700 2rem/1.2 'Gowun Batang', HOUSE-STACK; }
        code { font: house-stack; }
        """})
    result = lint("system.font-outside-contract", root, plan=PLAN, lock=LOCK)
    assert result.hits == [] and result.skipped is None


def test_css_wide_keywords_are_not_font_families(tmp_path):
    root = project(tmp_path, {"src/app.css": """
        body { font-family: Pretendard, Inherit; }
        h1 { font: INHERIT; }
        h2 { font: 700 2rem/1.2 'Gowun Batang', revert-layer; }
        """})
    result = lint("system.font-outside-contract", root, plan=PLAN, lock=LOCK)
    assert result.hits == [] and result.skipped is None


def test_font_outside_contract_in_every_declaration_form(tmp_path):
    root = project(tmp_path, {
        "src/app.css": ":root { --font-sans: 'Space Grotesk', sans-serif; }\n.a { font: 600 1rem/1.5 Manrope, sans-serif; }\n",
        "src/layout.tsx": "import { Inter } from \"next/font/google\"\nconst s = { fontFamily: 'Roboto Mono, monospace' }\n",
        "tailwind.config.js": "module.exports = { theme: { extend: { fontFamily: { display: ['Fraunces', 'serif'] } } } }\n",
        "src/Hero.tsx": "export const H = () => <h1 className=\"font-['DM_Serif_Display']\" />\n",
        "index.html": "<link href=\"https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700&display=swap\">\n",
    })
    text = observed(lint("system.font-outside-contract", root, plan=PLAN, lock=LOCK))
    for family in ("Space Grotesk", "Manrope", "Inter", "Roboto Mono", "Fraunces", "DM Serif Display",
                   "Playfair Display"):
        assert f"'{family}' is not a contract family" in text


def test_font_fallback_outside_contract_and_locked_fallbacks(tmp_path):
    root = project(tmp_path, {"src/app.css": "body { font-family: Pretendard, Roboto, sans-serif; }\n"})
    [hit] = lint("system.font-outside-contract", root, plan=PLAN, lock=LOCK).hits
    assert hit.observed.startswith("fallback font family 'Roboto'")
    lock = json.loads(json.dumps(LOCK))
    lock["fonts"][1]["fallback"] = ["Roboto", "sans-serif"]
    assert lint("system.font-outside-contract", root, plan=PLAN, lock=lock).hits == []


def test_font_recorded_as_proposed_design_change_passes(tmp_path):
    root = project(tmp_path, {"src/app.css": "body { font-family: Inter, sans-serif; }\n"})
    plan = yaml.safe_load(yaml.safe_dump(PLAN))
    plan["proposed_design_changes"] = [{"path": "DESIGN.md#type.body", "from": "Pretendard", "to": "Inter",
                                        "reason": "Latin-heavy data tables"}]
    assert lint("system.font-outside-contract", root, plan=plan, lock=LOCK).hits == []


def test_font_family_uses_are_grouped_per_family(tmp_path):
    root = project(tmp_path, {"src/a.css": ".a { font-family: Inter }\n", "src/b.css": ".b { font-family: 'inter', serif }\n"})
    [hit] = lint("system.font-outside-contract", root, plan=PLAN, lock=LOCK).hits
    assert "2 uses" in hit.observed and hit.refs == ["src/a.css:1", "src/b.css:1"]


def test_font_family_without_contract_is_skipped(tmp_path):
    root = project(tmp_path, {"src/app.css": "body { font-family: Inter }\n"})
    result = lint("system.font-outside-contract", root)
    assert result.skipped.startswith("no contract families") and not result.hits


# ---------------------------------------------------------------- css-literal-color

def test_literal_colors_in_token_definitions_do_not_fire(tmp_path):
    root = project(tmp_path, {
        "src/styles/tokens.css": ".x { color: #111; }\n",
        "src/theme/palette.ts": "export const ink = { color: '#222222' }\n",
        "tailwind.config.js": "module.exports = { theme: { colors: { ink: '#333' } } }\n",
        "src/app.css": ":root { --ink: #1f2937; }\n@theme { --color-brand: oklch(0.6 0.1 250); }\n"
                       ".tip { --tip-bg: #abcdef; background: var(--tip-bg); }\n"
                       "$accent: #ff0000;\n.card { color: var(--ink); background: url(#grad) }\n",
    })
    assert lint("system.literal-color", root).hits == []


def test_literal_colors_in_every_source_form(tmp_path):
    root = project(tmp_path, {
        "src/Card.tsx": "export const Card = () => (\n  <div style={{ backgroundColor: '#fafafa' }} className=\"bg-[#ff0000] hover:text-[rgb(0,0,0)]\">\n"
                        "    <svg><path fill=\"#123456\" d=\"M0 0h1\" /></svg>\n  </div>\n)\n",
        "src/Button.tsx": "const Btn = styled.button`\n  border: 1px solid hsl(210 40% 50%);\n`\n",
        "index.html": "<p style=\"color: oklch(0.5 0.1 30)\">x</p>\n",
    })
    text = observed(lint("system.literal-color", root))
    for literal in ("#fafafa", "#ff0000", "rgb(0,0,0)", "#123456", "hsl(210 40% 50%)", "oklch(0.5 0.1 30)"):
        assert f"literal color {literal} " in text


def test_literal_color_uses_are_grouped_per_value(tmp_path):
    root = project(tmp_path, {"src/a.css": ".a { color: #FFF }\n.b { border-color: #fff }\n"})
    [hit] = lint("system.literal-color", root).hits
    assert "2 uses" in hit.observed and hit.refs == ["src/a.css:1", "src/a.css:2"]


def test_literal_color_without_source_files_is_skipped(tmp_path):
    root = project(tmp_path, {"README.md": "# nothing to read\n"})
    assert lint("system.literal-color", root).skipped


# ---------------------------------------------------------------- css-off-scale-value

def test_on_scale_values_pass(tmp_path):
    root = project(tmp_path, {"src/app.css": """
        .a { padding: 8px 1rem; margin: 0 auto -24px; gap: 0.75rem; font-size: 1.25rem; }
        .b { padding: calc(1rem + 3px); margin: 1.5em; font-size: clamp(1rem, 2vw, 2rem); }
        """, "src/A.tsx": "const s = { paddingTop: 16, fontSize: '25px' }\n",
        "src/B.tsx": "export const B = () => <div className=\"p-[12px] text-[#fff] gap-4\" />\n"})
    plan = plan_with(**SCALES)
    plan["tokens"].pop("shape")
    result = lint("system.off-scale-value", root, plan=plan)
    assert result.hits == []
    assert result.skipped == ("border-radius: no contract radius scale (plan tokens or project token definitions)")


def test_off_scale_values_in_every_source_form(tmp_path):
    root = project(tmp_path, {
        "src/app.css": ".a { margin: 0 -10px; font-size: 15px; }\n",
        "src/A.tsx": "const s = { paddingTop: 13, gap: '18px' }\n",
        "src/B.tsx": "export const B = () => <div className=\"-mt-[6px] text-[17px] space-y-[5px]\" />\n",
    })
    text = observed(lint("system.off-scale-value", root, plan=plan_with(**SCALES)))
    for fragment in ("margin -10px", "font-size 15px", "padding-top 13", "gap 18px", "-mt-[6px] 6px",
                     "text-[17px] 17px", "space-y-[5px] 5px"):
        assert fragment in text


def test_type_scale_tolerance_boundary(tmp_path):
    # steps 16 * 1.25^n: 20px has a tolerance of max(0.5px, 2%) = 0.5px
    plan = plan_with(**SCALES)
    ok = project(tmp_path / "ok", {"a.css": ".a { font-size: 20.5px }\n"})
    off = project(tmp_path / "off", {"a.css": ".a { font-size: 20.6px }\n"})
    assert lint("system.off-scale-value", ok, plan=plan).hits == []
    assert "font-size 20.6px" in observed(lint("system.off-scale-value", off, plan=plan))


def test_radius_scale_from_project_tokens(tmp_path):
    root = project(tmp_path, {
        "src/app.css": ":root { --radius-sm: 4px; --radius-lg: 0.75rem; }\n",
        "src/card.css": ".a { border-radius: 4px 12px; }\n.b { border-radius: 6px; }\n.pill { border-radius: 9999px; }\n",
    })
    plan = plan_with(**SCALES)
    plan["tokens"].pop("shape")
    result = lint("system.off-scale-value", root, plan=plan)
    assert result.skipped is None
    [hit] = result.hits
    assert hit.observed.startswith("border-radius 6px") and "project token definitions" in hit.observed


def test_authored_media_contour_does_not_expand_the_repeated_control_radius_scale(tmp_path):
    root = project(tmp_path, {"app.css": """
        :root { --media-contour-radius-story: 3px 120px 3px 3px; }
        .story img { border-radius: var(--media-contour-radius-story); }
        button { border-radius: 6px; }
        .card { border-radius: 8px; }
        """})
    shape = {"radius": {"scale": [0, 4, 8], "by_role": {"control": 4, "card": 8}},
             "media_contours": [{"token": "--media-contour-radius-story", "value": "3px 120px 3px 3px",
                                "where": ".story img", "reason": "One open corner anchors the caption beside the product."}]}
    result = lint("system.off-scale-value", root, plan=plan_with(**SCALES, shape=shape))
    assert [hit.observed.split(" is off")[0] for hit in result.hits] == ["border-radius 6px"]
    assert result.skipped is None

    root = project(tmp_path / "drift", {"app.css": """
        :root { --media-contour-radius-story: 120px; }
        .story img { border-radius: var(--media-contour-radius-story); }
        button { border-radius: 120px; }
        """})
    assert "border-radius 120px" in observed(lint("system.off-scale-value", root, plan=plan_with(shape=shape)))

def test_space_multiples_of_the_base(tmp_path):
    root = project(tmp_path, {"a.css": ".a { padding: 12px 20px; margin: 14px }\n"})
    result = lint("system.off-scale-value", root, plan=plan_with(space={"base_px": 4}))
    assert [h.observed for h in result.hits] == [
        "margin 14px is off the contract space scale: multiples of 4px from plan tokens.space.base_px; 1 use"]


def test_off_scale_without_any_scale_is_skipped(tmp_path):
    root = project(tmp_path, {"a.css": ".a { padding: 13px }\n"})
    result = lint("system.off-scale-value", root)
    assert not result.hits and "padding: no contract space scale" in result.skipped


# ---------------------------------------------------------------- source-pattern

def test_negative_tracking_boundary(tmp_path):
    root = project(tmp_path, {"a.css": "h1 { letter-spacing: -0.04em; }\nh2 { letter-spacing: -0.02em }\n"})
    assert lint("type.negative-tracking", root).hits == []


@pytest.mark.parametrize("rule_id, text", [
    ("motion.bounce-default", ".a { transition-timing-function: cubic-bezier(0.4, 0, 0.2, 1); }\n"),
    ("motion.layout-property-animation", ".a { transition: transform 200ms, max-width 1s; }\n"),
    ("code.focus-outline-removed", "button:focus-visible { outline: 2px solid currentColor; }\n"),
    ("code.mobile-100vh", ".a { min-height: 100dvh; }\n"),
    ("motion.transition-all", ".a { transition: opacity .2s; }\n"),
])
def test_patterns_do_not_fire_on_the_fix(tmp_path, rule_id, text):
    assert lint(rule_id, project(tmp_path, {"src/a.css": text})).hits == []


def test_pattern_matches_in_one_file_form_one_hit(tmp_path):
    root = project(tmp_path, {"src/a.css": ".a { height: 100vh }\n.b { max-height: 100vh }\n.c { top: 0 }\n"})
    [hit] = lint("code.mobile-100vh", root).hits
    assert hit.observed == "'100vh' in src/a.css; 2 matches" and hit.refs == ["src/a.css:1", "src/a.css:2"]


def test_emoji_outside_icon_slots_does_not_fire(tmp_path):
    root = project(tmp_path, {"src/Post.tsx": "export const P = () => (\n"
                                              "  <p>We shipped a lot this year 🎉 and more is coming soon for everyone</p>\n"
                                              "  <small>© 2026 Kiln Studio</small>\n)\n"})
    assert lint("component.emoji-icons", root).hits == []


@pytest.mark.parametrize("text", [
    "export const B = () => <button>✨ Generate</button>\n",
    "export const B = () => <span aria-hidden=\"true\">✅</span>\n",
    "export const B = () => <i className=\"icon\">⚙️</i>\n",
    "const next = 'Next →'\n",
])
def test_emoji_in_icon_slots_fires(tmp_path, text):
    assert lint("component.emoji-icons", project(tmp_path, {"src/B.tsx": text})).hits


def test_css_content_glyph_is_an_icon_slot(tmp_path):
    root = project(tmp_path, {"src/a.css": ".tick::before { content: \"✔\"; }\n"})
    assert lint("component.emoji-icons", root).hits


def test_a_glyph_both_patterns_match_counts_once(tmp_path):
    # U+2728 is pictographic and inside the dingbat range the rule's second pattern lists
    root = project(tmp_path, {"index.html": "<span class=\"icon\">✨</span>\n"})
    [hit] = lint("component.emoji-icons", root).hits
    assert hit.observed == "'✨' in index.html (icon slots); 1 match"


def test_unsupported_pattern_is_named_and_the_rest_still_run(tmp_path):
    root = project(tmp_path, {"src/a.ts": "const s = 'foo'\n"})
    det = {"detector": "source-pattern", "params": {"patterns": [r"\p{Script=Hangul}", "fo{2}"]}}
    result = lint("code.mobile-100vh", root, det=det)
    assert len(result.hits) == 1 and "Script=Hangul" in result.skipped


def test_ecmascript_pattern_syntax(tmp_path):
    root = project(tmp_path, {"src/a.ts": "const a = 'ab-ab 가'\n"})
    det = {"detector": "source-pattern", "params": {"patterns": [r"(?<w>ab)-\k<w>", r"\u{AC00}", r"\p{Lo}"]}}
    result = lint("code.mobile-100vh", root, det=det)
    assert result.skipped is None and "'ab-ab', '가'" in observed(result)


# ---------------------------------------------------------------- source-ast

def test_bypassed_primitive_needs_an_adopted_primitive(tmp_path):
    root = project(tmp_path, {"src/Page.tsx": "export const P = () => <form><button>Go</button><input name=\"q\" /></form>\n"})
    assert lint("system.bypassed-primitive", root).hits == []


def test_primitive_definition_file_may_use_the_raw_element(tmp_path):
    root = project(tmp_path, {
        "src/components/ui/input.tsx": "export const Input = (p) => <input className=\"in\" {...p} />\n",
        "src/components/ui/checkbox.tsx": "export function Checkbox(p) { return <input type=\"checkbox\" {...p} /> }\n",
        "src/Search.tsx": "export const S = () => <><input type=\"checkbox\" /><input type=\"hidden\" name=\"t\" /></>\n",
    })
    [hit] = lint("system.bypassed-primitive", root).hits
    assert hit.location["file"] == "src/Search.tsx:1"
    assert "raw <input type=checkbox> while the project has a Checkbox primitive" in hit.observed


def test_hand_drawn_icon_needs_standard_action_naming_and_icon_geometry(tmp_path):
    logo = "M" + " L".join(f"{i} {i}" for i in range(400))
    root = project(tmp_path, {
        "src/Logo.tsx": f"export const Logo = () => <a href=\"/\" aria-label=\"Home\"><svg><path d=\"{logo}\" /></svg></a>\n",
        "src/Art.tsx": "export const Art = () => <figure><svg><path d=\"M0 0h10v10z\" /></svg></figure>\n",
    })
    assert lint("component.hand-drawn-icons", root).hits == []


@pytest.mark.parametrize("text, action", [
    ("export function ChevronDownIcon() {\n  return <svg><polyline points=\"6 9 12 15 18 9\" /></svg>\n}\n", "chevron"),
    ("export const T = () => <button><svg><path d=\"M3 6h18\" /></svg>삭제</button>\n", "삭제"),
    ("export const S = () => <svg className=\"icon-search\"><path d=\"M11 11l5 5\" /></svg>\n", "search"),
])
def test_hand_drawn_icon_naming_sources(tmp_path, text, action):
    [hit] = lint("component.hand-drawn-icons", project(tmp_path, {"src/I.tsx": text})).hits
    assert action in hit.observed


def test_labeled_inputs_pass_and_spread_inputs_are_not_judged(tmp_path):
    root = project(tmp_path, {
        "src/Form.tsx": """
        export const F = ({ id, ...rest }) => (
          <form>
            <label htmlFor="email">Email</label><input id="email" type="email" />
            <label>Name <input name="name" /></label>
            <input aria-label="Search" />
            <input type="hidden" name="t" /><input type="submit" />
            <Label htmlFor={id}>Code</Label><input id={id} />
            <textarea {...rest} />
          </form>
        )
        """,
        "index.html": "<select id=\"size\"></select><label for=\"size\">Size</label>\n",
    })
    result = lint("component.unlabeled-input", root)
    assert result.hits == []
    assert result.skipped.startswith("1 form field not judged") and "src/Form.tsx:9" in result.skipped


def test_select_without_label(tmp_path):
    root = project(tmp_path, {"index.html": "<select name=\"size\"><option>S</option></select>\n"})
    [hit] = lint("component.unlabeled-input", root).hits
    assert hit.observed == "<select name=size> without an associated label"


def test_images_with_alt_or_intrinsic_size_pass(tmp_path):
    root = project(tmp_path, {"src/G.tsx": """
        export const G = ({ src, ...p }) => (
          <div>
            <img src="/a.jpg" alt="" width={640} height={480} />
            <img src={src} alt="Glaze detail" className="aspect-square w-full" />
            <img src="/c.jpg" alt="Kiln" style="aspect-ratio: 4 / 3" />
            <img src="/d.jpg" alt="Foot ring" className="h-10 w-10" />
          </div>
        )
        """})
    assert lint("imagery.missing-content-image", root).hits == []
    assert lint("code.image-dimensions", root).hits == []


def test_spread_images_are_not_judged(tmp_path):
    root = project(tmp_path, {"src/Img.tsx": "export const Img = (p) => <img {...p} />\n"})
    for rule_id in ("imagery.missing-content-image", "code.image-dimensions"):
        result = lint(rule_id, root)
        assert result.hits == [] and result.skipped.startswith("1 image not judged")


def test_image_queries_without_markup_are_skipped(tmp_path):
    root = project(tmp_path, {"src/a.css": ".a { color: red }\n", "src/util.ts": "export const a = 1\n"})
    assert lint("imagery.missing-content-image", root).skipped.startswith("no markup files")


@pytest.mark.parametrize("text", [
    "export const A = () => <button onClick={open}>Open</button>\n",
    "export const A = () => <a href=\"/x\" onClick={track}>X</a>\n",
    "export const A = () => <div role=\"button\" tabIndex={0} onClick={open} onKeyDown={key}>Open</div>\n",
    "export const A = () => <div className=\"panel\" onClick={(e) => e.stopPropagation()}>x</div>\n",
    "export const A = () => <div className=\"backdrop\" aria-hidden=\"true\" onClick={close} />\n",
    "export const A = () => <Card onClick={open} />\n",
])
def test_clickable_elements_that_pass(tmp_path, text):
    assert lint("code.clickable-non-interactive", project(tmp_path, {"src/A.tsx": text})).hits == []


@pytest.mark.parametrize("name, text, observation", [
    ("A.vue", "<template><li @click=\"pick(item)\">{{ item }}</li></template>\n",
     "<li> has a @click handler without an interactive role, tabindex, or a key handler"),
    ("A.svelte", "<span role=\"button\" on:click={open}>Open</span>\n",
     "<span> has a on:click handler without tabindex or a key handler"),
    ("A.tsx", "export const A = () => <a onClick={go}>Go</a>\n",
     "<a> has a onClick handler without an interactive role, tabindex, or a key handler"),
])
def test_clickable_non_interactive_across_template_syntaxes(tmp_path, name, text, observation):
    [hit] = lint("code.clickable-non-interactive", project(tmp_path, {f"src/{name}": text})).hits
    assert hit.observed == observation


def test_locale_strings_follow_the_plan_locales(tmp_path):
    root = project(tmp_path, {
        "src/Price.tsx": "export const a = (n) => n.toLocaleString('ko-KR')\n"
                         "export const b = (d) => new Intl.DateTimeFormat('en-US').format(d)\n",
        "index.html": "<html lang=\"en\"><body></body></html>\n",
    })
    text = observed(lint("code.locale-time-rendering", root, plan=PLAN))
    assert "hard-codes the locale 'en-US' (plan locales: ko-KR)" in text
    assert "'ko-KR'" not in text
    assert "<html lang='en'> is hard-coded outside the plan locales" in text


def test_hard_coded_dates_and_render_time_in_markup(tmp_path):
    root = project(tmp_path, {
        "src/Footer.tsx": "export const F = () => (\n  <footer>\n    <p>© 2024 Kiln Studio</p>\n"
                          "    <p>Updated September 3, 2025</p>\n    <p>Trusted by 12,000 potters</p>\n"
                          "    <p>{new Date().getFullYear()}</p>\n  </footer>\n)\n",
        "src/ok.html": "<style>.a { color: rgb(255,255,255) }</style><pre>2024-01-01</pre><p>Since the first firing</p>\n",
    })
    hits = lint("code.locale-time-rendering", root).hits
    assert [(h.location["file"], h.observed.split(":")[0]) for h in hits] == [
        ("src/Footer.tsx:3", "a hard-coded copyright year in markup text"),
        ("src/Footer.tsx:4", "a hard-coded date in markup text"),
        ("src/Footer.tsx:5", "a hand-formatted number in markup text"),
        ("src/Footer.tsx:6", "{new Date().getFullYear()} renders the current time into markup, so server and client output differ"),
    ]


def test_state_setters_outside_continuous_handlers_pass(tmp_path):
    root = project(tmp_path, {"src/A.tsx": """
        export function A() {
          const [open, setOpen] = useState(false)
          const x = useMotionValue(0)
          return <div onClick={() => setOpen(true)} onMouseMove={(e) => x.set(e.clientX)} />
        }
        """})
    assert lint("code.continuous-value-in-state", root).hits == []


def test_state_setter_in_a_named_scroll_listener(tmp_path):
    root = project(tmp_path, {"src/useScrollY.ts": """
        export function useScrollY() {
          const [y, setY] = useState(0)
          useEffect(() => {
            const onScroll = () => { setY(window.scrollY) }
            window.addEventListener('scroll', onScroll, { passive: true })
          }, [])
          return y
        }
        """})
    [hit] = lint("code.continuous-value-in-state", root).hits
    assert hit.observed.startswith("setY() runs in a scroll listener")


def test_unknown_query_is_skipped(tmp_path):
    root = project(tmp_path, {"a.css": ".a{}\n"})
    det = {"detector": "source-ast", "params": {"query": "no-such-query"}}
    assert lint("code.image-dimensions", root, det=det).skipped == "unknown source-ast query 'no-such-query'"


# ---------------------------------------------------------------- dependency-check

def test_one_icon_family_passes(tmp_path):
    root = project(tmp_path, {
        "package.json": {"dependencies": {"lucide-react": "^0.400.0", "@heroicons/react": "^2.1.0"}},
        "src/A.tsx": "import { Search, X } from \"lucide-react\"\n",
        "src/B.tsx": "import { Menu } from 'lucide-react'\n",
    })
    assert lint("component.mixed-icon-families", root).hits == []


def test_icon_families_through_one_package(tmp_path):
    root = project(tmp_path, {
        "src/A.tsx": "import { FaBeer } from 'react-icons/fa'\nimport { FaHome } from 'react-icons/fa6'\n",
        "src/B.tsx": "import { MdHome } from 'react-icons/md'\n",
        "src/C.tsx": "import { FaStar } from 'react-icons/fa'\n",
    })
    [hit] = lint("component.mixed-icon-families", root).hits
    # the family in the fewest files comes first and gives the location: it is the likely stray
    assert hit.observed == "2 icon families imported: react-icons/md (1 file); react-icons/fa, react-icons/fa6 (2 files)"
    assert hit.location == {"file": "src/B.tsx:1"}


def test_icon_families_from_the_manifest_when_no_imports_can_be_read(tmp_path):
    root = project(tmp_path, {
        "package.json": {"dependencies": {"@phosphor-icons/web": "^2.0.0", "bootstrap-icons": "^1.11.0"}},
        "index.css": ".a{}\n",
    })
    [hit] = lint("component.mixed-icon-families", root).hits
    assert hit.location == {"file": "package.json"}
    assert hit.observed == "2 icon families declared in package.json: @phosphor-icons/web; bootstrap-icons"
    assert lint("component.mixed-icon-families", project(tmp_path / "empty", {"a.css": ".a{}\n"})).skipped


def test_animation_import_matching_the_installed_package_passes(tmp_path):
    root = project(tmp_path, {
        "package.json": {"dependencies": {"motion": "^11.11.0"}},
        "package-lock.json": {"lockfileVersion": 3, "packages": {"": {}, "node_modules/motion": {"version": "11.11.0"}}},
        "node_modules/motion/package.json": {"name": "motion", "version": "11.11.0",
                                             "exports": {".": "./dist/index.js", "./react": "./dist/react.js"}},
        "src/Fade.tsx": "import { motion } from 'motion/react'\n",
    })
    assert lint("code.animation-package-mismatch", root).hits == []


@pytest.mark.parametrize("files, expected", [
    ({"package.json": {"dependencies": {"motion": "^11.11.0"}},
      "node_modules/motion/package.json": {"name": "motion", "version": "11.11.0", "exports": {".": "./i.js"}},
      "src/Fade.tsx": "import { motion } from 'motion/react'\n"},
     "imports 'motion/react', but the installed motion 11.11.0 has no ./react export"),
    ({"package.json": {"dependencies": {"motion": "^11.11.0"}},
      "yarn.lock": "motion@^11.11.0:\n  version \"11.11.0\"\nframer-motion@^11.11.0:\n  version \"11.11.0\"\n",
      "src/Fade.tsx": "import { motion } from 'framer-motion'\n"},
     "imports framer-motion (1 file), which no package.json declares; it is only a transitive dependency in yarn.lock"),
    ({"package.json": {"dependencies": {"gsap": "^3.12.0"}},
      "pnpm-lock.yaml": "lockfileVersion: '9.0'\npackages:\n  react@18.3.1:\n    resolution: {integrity: x}\n",
      "src/Hero.tsx": "import gsap from 'gsap'\n"},
     "package.json declares ^3.12.0 but no lockfile lists it"),
    ({"package.json": {"dependencies": {"framer-motion": "^11.0.0", "gsap": "^3.12.0"}},
      "src/A.tsx": "import { motion } from 'framer-motion'\n", "src/B.tsx": "import { gsap } from 'gsap'\n"},
     "2 animation stacks imported: framer-motion (1 file); gsap (1 file)"),
])
def test_animation_mismatches(tmp_path, files, expected):
    assert expected in observed(lint("code.animation-package-mismatch", project(tmp_path, files)))


def test_animation_check_skips_when_imports_or_manifest_cannot_be_read(tmp_path):
    no_code = project(tmp_path / "a", {"package.json": {"dependencies": {"gsap": "^3.12.0"}}, "a.css": ".a{}\n"})
    result = lint("code.animation-package-mismatch", no_code)
    assert result.skipped.startswith("imports could not be read") and result.skipped.endswith("not-verified")
    no_manifest = project(tmp_path / "b", {"src/A.tsx": "import { gsap } from 'gsap'\n"})
    assert lint("code.animation-package-mismatch", no_manifest).skipped.startswith("no package.json")
