"""`lazuli ref ... --task`: the study copies a run looks at, and the rules they keep.

The page is a fake site (no network, no browser) as in test_lazuli_ref: robots.txt asks for a 7 second delay, the
browser capture is replaced, and every request goes through the polite fetcher, so what these tests show is which
requests the study copies add and how they are paced, refused, and kept."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lapis_design.render.extract import validate
from lazuli.catalog import net
from lazuli.ref import study
from test_lazuli_ref import (URL, cache, fake_capture, files, project, registry, run,  # noqa: F401 (fixtures)
                             synthetic_image)

PAGE = """<!doctype html><html lang="en"><head>
<link rel="stylesheet" href="/a.css"><link rel="stylesheet" href="https://closed.invalid/x.css">
<style>.note { color: #8a3b12 }</style>
<meta property="og:image" content="/card.png"></head>
<body><header class="top bar"><nav>Menu</nav></header>
<main><section class="hero big"><p>one<p>two</section><section class="plan"></section></main><footer></footer>
</body></html>"""
CSS = ("/* the page's type */ :root{--ink:#1a1a1a;--paper:#f4f0e8} "
       "body{font-family:'Source Serif 4',Georgia,serif;font-size:17px;line-height:1.55;color:#1a1a1a} "
       "h1{font-size:2.5rem;letter-spacing:-0.02em;font-family:'Source Serif 4',Georgia,serif} "
       ".grid{display:grid;grid-template-columns:repeat(12,1fr);gap:24px;max-width:62ch} "
       "@media (min-width:768px){.grid{gap:32px}} @font-face{font-family:'Source Serif 4';src:url(x.woff2)}")
SHEET = "https://ref.invalid/a.css"
FOLDER = ".lapis/references/kiln-shop"


def css(address: str, text: str = CSS, kind: str = "text/css") -> net.Response:
    return net.Response(address, 200, {"content-type": kind}, text.encode())


@pytest.fixture
def site_with_sheet(fake_capture):
    fake_capture.site.pages.update({URL: PAGE, SHEET: css(SHEET)})
    return fake_capture


def kept_names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def test_a_capture_with_a_task_keeps_the_screenshots_the_html_and_the_css_for_study(site_with_sheet, registry, project):
    assert run(project, "capture", URL, "--rights", "reference-only", "--task", "kiln-shop") == 0
    study_folder = project / FOLDER
    kept = study_folder / "ref-invalid-work"
    assert kept_names(kept) == ["1440.png", "390.png", "768.png", "facts.md", "page.html", "style-1.css"]
    assert all((kept / f"{w}.png").read_bytes() == site_with_sheet.png for w in (390, 768, 1440))
    assert (kept / "page.html").read_text(encoding="utf-8") == PAGE
    assert (kept / "style-1.css").read_text(encoding="utf-8") == CSS
    assert (study_folder / ".gitignore").read_text(encoding="utf-8").splitlines()[-1] == "*"
    profile = json.loads((project / ".lapis/refs/ref-invalid-work.json").read_text(encoding="utf-8"))
    assert profile["reference"]["captured_by"] == "agent-exploration"        # the run chose this page, not the user
    assert validate(profile) == []
    assert {p for p in files(project)} == {
        project / ".lapis/refs/ref-invalid-work.json", study_folder / ".gitignore",
        *(kept / name for name in kept_names(kept))}


def test_the_digest_counts_what_the_source_states_not_what_it_rendered(site_with_sheet, registry, project):
    assert run(project, "capture", URL, "--rights", "reference-only", "--task", "kiln-shop") == 0
    facts = (project / FOLDER / "ref-invalid-work" / "facts.md").read_text(encoding="utf-8")
    for part in ["Source Serif 4, Georgia, serif ×2", "Source Serif 4 ×1", "font-size: 17px ×1, 2.5rem ×1",
                 "line-height: 1.55 ×1", "letter-spacing: -0.02em ×1", "#1a1a1a ×2", "#f4f0e8 ×1", "#8a3b12 ×1",
                 "--ink: #1a1a1a", "--paper: #f4f0e8", "grid-template-columns: repeat(12,1fr) ×1", "max-width: 62ch ×1",
                 "gap: 24px ×1, 32px ×1", "display: grid ×1", "min-width 768px", "a.css"]:
        assert part in facts, part
    outline = facts.split("```")[1].split("\n")
    assert outline[1:7] == ["header.top.bar", "  nav", "main", "  section.hero.big", "  section.plan", "footer"]
    assert "https://ref.invalid/card.png" in facts                          # a picture the page names, to look at next


def test_the_stylesheets_are_read_through_the_registry_and_at_the_site_pace(site_with_sheet, registry, project):
    assert run(project, "capture", URL, "--rights", "reference-only", "--task", "kiln-shop") == 0
    log = site_with_sheet.site.log
    assert [url for url, _, _ in log] == ["https://ref.invalid/robots.txt", URL, "https://ref.invalid/robots.txt", SHEET]
    assert not any("closed.invalid" in url for url, _, _ in log)            # a refused host is never requested
    assert log[3][2] - log[2][2] >= 7                                       # the robots.txt Crawl-delay
    assert log[2][2] - (site_with_sheet.loads[-1]["at"] + 2) >= 3           # after the last page load, at the pace
    facts = (project / FOLDER / "ref-invalid-work" / "facts.md").read_text(encoding="utf-8")
    assert "not read: x.css: the terms forbid automated collection" in facts


def test_only_the_first_stylesheets_are_read_and_the_rest_are_named(fake_capture, project):
    links = "".join(f'<link rel="stylesheet" href="/s{n}.css">' for n in range(1, 9))
    fake_capture.site.pages[URL] = f"<html><head>{links}</head><body></body></html>"
    fake_capture.site.pages.update({f"https://ref.invalid/s{n}.css": css(f"https://ref.invalid/s{n}.css", f"a{{gap:{n}px}}")
                                    for n in range(1, 9)})
    assert run(project, "capture", URL, "--rights", "reference-only", "--task", "kiln-shop") == 0
    kept = project / FOLDER / "ref-invalid-work"
    assert [n for n in kept_names(kept) if n.startswith("style-")] == [f"style-{n}.css" for n in range(1, 7)]
    facts = (kept / "facts.md").read_text(encoding="utf-8")
    assert "s7.css: past the first 6" in facts and "s8.css: past the first 6" in facts
    assert len([url for url, _, _ in fake_capture.site.log if url.endswith(".css")]) == 6


def test_a_stylesheet_that_is_missing_or_no_css_is_named_and_not_kept(fake_capture, project):
    fake_capture.site.pages[URL] = ('<html><head><link rel="stylesheet" href="/gone.css">'
                                    '<link rel="stylesheet" href="/soft.css"></head><body></body></html>')
    fake_capture.site.pages["https://ref.invalid/soft.css"] = css("https://ref.invalid/soft.css", "<html>sorry</html>",
                                                                  "text/html")
    assert run(project, "capture", URL, "--rights", "reference-only", "--task", "kiln-shop") == 0
    kept = project / FOLDER / "ref-invalid-work"
    assert kept_names(kept) == ["1440.png", "390.png", "768.png", "facts.md", "page.html"]
    facts = (kept / "facts.md").read_text(encoding="utf-8")
    assert "gone.css: " in facts and "soft.css: answered text/html, not CSS" in facts


def test_a_second_capture_replaces_the_folder_instead_of_adding_to_it(site_with_sheet, project):
    assert run(project, "capture", URL, "--rights", "reference-only", "--task", "kiln-shop") == 0
    kept = project / FOLDER / "ref-invalid-work"
    (kept / "style-9.css").write_text("stale", encoding="utf-8")
    assert run(project, "capture", URL, "--rights", "reference-only", "--task", "kiln-shop") == 0
    assert "style-9.css" not in kept_names(kept) and "style-1.css" in kept_names(kept)
    assert [p.name for p in (project / FOLDER).iterdir() if p.name != ".gitignore"] == ["ref-invalid-work"]


def test_without_a_task_nothing_but_the_profile_reaches_the_project_and_no_stylesheet_is_requested(
        site_with_sheet, project):
    assert run(project, "capture", URL, "--rights", "reference-only") == 0
    assert files(project) == [project / ".lapis/refs/ref-invalid-work.json"]
    assert [url for url, _, _ in site_with_sheet.site.log] == ["https://ref.invalid/robots.txt", URL]


def test_a_capture_the_registry_refuses_leaves_no_study_folder(fake_capture, registry, project, capsys):
    assert run(project, "capture", "https://closed.invalid/page", "--rights", "reference-only", "--task", "kiln-shop") == 1
    assert fake_capture.site.log == [] and files(project) == []


def test_study_copies_that_cannot_be_written_are_reported_and_the_profile_stays(site_with_sheet, project, monkeypatch,
                                                                              capsys):
    def full_disk(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(study, "keep", full_disk)
    assert run(project, "capture", URL, "--rights", "reference-only", "--task", "kiln-shop") == 2
    assert "written, but the study copies could not be put under .lapis/references/kiln-shop/" in capsys.readouterr().err
    assert (project / ".lapis/refs/ref-invalid-work.json").is_file()


def test_a_task_that_is_no_plan_task_is_a_usage_error(project):
    with pytest.raises(SystemExit) as exit_:
        run(project, "capture", URL, "--rights", "own", "--task", "../elsewhere")
    assert exit_.value.code == 2
    assert files(project) == []


def test_a_design_system_has_no_study_copy_to_keep(project, tmp_path, capsys):
    tokens = tmp_path / "tokens.json"
    tokens.write_text(json.dumps({"color": {"$type": "color", "brand": {"$value": "#2251CC"}}}), encoding="utf-8")
    assert run(project, "system", str(tokens), "--rights", "own", "--task", "kiln-shop") == 2
    assert "a design system has none" in capsys.readouterr().err and files(project) == []


# ------------------------------------------------------------------ a picture at an address

PICTURE = "https://ref.invalid/plates/plate-4.png"


def test_a_picture_at_an_address_is_profiled_and_kept_for_study(fake_capture, registry, project, cache, tmp_path):
    png = synthetic_image(tmp_path / "plate.png").read_bytes()
    fake_capture.site.pages[PICTURE] = net.Response(PICTURE, 200, {"content-type": "image/png"}, png)
    assert run(project, "profile", PICTURE, "--rights", "reference-only", "--task", "kiln-shop") == 0
    slug = "ref-invalid-plates-plate-4-png"
    profile = json.loads((project / f".lapis/refs/{slug}.json").read_text(encoding="utf-8"))
    assert profile["source"] == {"kind": "image", "url": PICTURE}
    assert (cache / "refs" / slug / "image.png").read_bytes() == png
    assert (project / FOLDER / slug / "image.png").read_bytes() == png
    assert [url for url, _, _ in fake_capture.site.log] == ["https://ref.invalid/robots.txt", PICTURE]


def test_a_picture_without_a_task_stays_in_the_cache(fake_capture, project, cache, tmp_path):
    png = synthetic_image(tmp_path / "plate.png").read_bytes()
    fake_capture.site.pages[PICTURE] = net.Response(PICTURE, 200, {"content-type": "image/png"}, png)
    assert run(project, "profile", PICTURE, "--rights", "reference-only") == 0
    assert files(project) == [project / ".lapis/refs/ref-invalid-plates-plate-4-png.json"]


def test_a_page_is_no_picture_and_is_sent_to_capture(fake_capture, project, capsys):
    fake_capture.site.pages[PICTURE] = "<html>a viewer page</html>"
    assert run(project, "profile", PICTURE, "--rights", "reference-only", "--task", "kiln-shop") == 2
    assert "not a picture; capture a page with `lazuli ref capture`" in capsys.readouterr().err
    assert files(project) == []


def test_bytes_that_are_no_picture_are_refused_even_when_the_site_says_image(fake_capture, project, capsys):
    fake_capture.site.pages[PICTURE] = net.Response(PICTURE, 200, {"content-type": "image/png"}, b"not a picture")
    assert run(project, "profile", PICTURE, "--rights", "reference-only", "--task", "kiln-shop") == 2
    assert "cannot read the image" in capsys.readouterr().err and files(project) == []


def test_a_picture_on_a_refused_source_is_never_requested(fake_capture, registry, project):
    assert run(project, "profile", "https://closed.invalid/plate.png", "--rights", "reference-only") == 1
    assert fake_capture.site.log == [] and files(project) == []


def test_a_local_picture_is_kept_for_study_under_its_own_name(project, tmp_path):
    image = synthetic_image(tmp_path / "Hero Shot.png")
    assert run(project, "profile", str(image), "--rights", "own", "--task", "kiln-shop") == 0
    assert (project / FOLDER / "hero-shot" / "image.png").read_bytes() == image.read_bytes()


# ------------------------------------------------------------------ the digest on its own

def test_the_css_scan_reads_declarations_and_skips_selectors_and_data_urls():
    lines = study.css_facts(["a:hover, b:focus { color: red } .x { background: url(data:image/png;base64,AAAA) }"
                             " :root { --logo: url(data:x;y) } p { font: 16px/1.5 Inter }"])
    text = "\n".join(lines)
    assert "font: 16px/1.5 Inter ×1" in text and "--logo" not in text and "hover" not in text
    assert "font-size: none found" in text and "media-query breakpoints: none found" in text
