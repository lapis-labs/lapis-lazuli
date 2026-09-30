"""lazuli color: code normalization, system-specific LCh → OKLCH, records, and search."""
from __future__ import annotations

import itertools
import json
import math
import sqlite3

import pytest

from lapis_design.render.color import delta_e_ok, to_oklch
from lazuli import cli, color, db


@pytest.fixture
def env(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    database = tmp_path / "cache" / "lazuli.db"
    monkeypatch.setenv("LAZULI_DB", str(database))
    return {"project": project, "db": database}


def close(a, b, tol):
    assert a[0] == pytest.approx(b[0], abs=tol) and a[1] == pytest.approx(b[1], abs=tol)
    assert (a[2] is None) == (b[2] is None)
    if a[2] is not None:
        assert (a[2] - b[2] + 180) % 360 - 180 == pytest.approx(0, abs=tol)


# ---------------------------------------------------------------- conversion

# Full-precision OKLCH digits for the synthetic sRGB input #336699, derived in double precision.
REFERENCE_336699 = (0.49931445292373877, 0.09866435965710138, 250.43305370947127)


def test_srgb_conversion_reproduces_the_reference_example():
    close(color.srgb_hex_to_oklch("#336699"), REFERENCE_336699, 1e-12)


def test_the_lch_d50_route_reaches_the_reference_value():
    """OKLCH → XYZ D65 → Bradford → Lab D50 → LCh and back lands on the reference digits."""
    lch = color.oklch_to_lch_d50(*REFERENCE_336699)
    assert 0 < lch[0] < 100 and lch[1] > 0
    close(color.lch_d50_to_oklch(*lch), REFERENCE_336699, 1e-12)


def test_round_trip_over_the_code_space():
    """Chromatic codes return to full precision; neutrals lose only the few 1e-8 of Oklab b that the
    published LMS → Oklab coefficients leave on the white axis and the powerless-hue rule drops."""
    for l, c, h in itertools.product((5, 20, 50, 80, 95), (0, 10, 40, 80), range(0, 360, 30)):
        source = (float(l), float(c), float(h) if c else None)
        close(color.oklch_to_lch_d50(*color.lch_d50_to_oklch(*source)), source, 1e-9 if c else 1e-6)


def test_bradford_adapts_white_to_white_and_inverts():
    for got, want in zip(color._mv(color.D50_TO_D65, color.D50), color.D65):
        assert got == pytest.approx(want, abs=1e-12)
    for i, j in itertools.product(range(3), range(3)):
        assert color._mm(color.D65_TO_D50, color.D50_TO_D65)[i][j] == pytest.approx(float(i == j), abs=1e-12)
    l, c, h = color.lch_d50_to_oklch(100, 0, None)       # D50 white is OKLCH white, and neutrals stay neutral
    assert (l, c, h) == (pytest.approx(1, abs=1e-6), 0.0, None)
    assert color.lch_d50_to_oklch(50, 0, None)[1:] == (0.0, None)


@pytest.mark.parametrize("lch", [(60, 40, 40), (40, 20, 180), (80, 60, 90), (30, 50, 300), (70, 5, 250)])
def test_conversion_agrees_with_the_render_path(lch):
    """The render extractor's CSS lch() path uses its own white points and rounded Bradford constants."""
    ours = color.lch_d50_to_oklch(*lch)
    assert delta_e_ok(list(ours), to_oklch("lch({} {} {})".format(*lch))) < 3e-4


def test_the_lch_d65_10_inverse_round_trips_its_own_forward_route():
    for source in ((55, 40, 270), (65, 30, 40), (80, 60, 180), (20, 0, None)):
        close(color.oklch_to_lch_d65_10(*color.lch_d65_10_to_oklch(*source)),
              source, 1e-9 if source[1] else 1e-6)


@pytest.mark.parametrize("seed", [1, 7, 424242, 99991, 20260927])
def test_nearest_grid_codes_cover_the_exhaustive_four_step_minimum(seed):
    import random

    rng = random.Random(seed)
    samples = [color.srgb_hex_to_oklch(f"#{rng.randrange(0x1000000):06X}") for _ in range(1000)]
    for system, steps in color.GRIDS.items():
        misses = []
        forward = color.lch_d50_to_oklch if system == "hlc" else color.lch_d65_10_to_oklch
        inverse = color.oklch_to_lch_d50 if system == "hlc" else color.oklch_to_lch_d65_10
        for index, value in enumerate(samples):
            l, c, h = inverse(*value)
            axes = []
            for coordinate, step, maximum in zip((h or 0, l, c), steps,
                                                  (350, 100 if system == "hlc" else 90,
                                                   990 if system == "hlc" else 90)):
                center = round(coordinate / step)
                axes.append({(n * step) % 360 if maximum == 350 else min(maximum, max(0, n * step))
                             for n in range(center - 4, center + 5)})
            best_distance, best_code = float("inf"), None
            for lightness in axes[1]:
                for chroma in axes[2]:
                    for hue in (axes[0] if chroma else {0}):
                        candidate = forward(lightness, chroma, hue if chroma else None)
                        distance = color._distance(value, candidate)
                        if distance < best_distance:
                            best_distance = distance
                            best_code = color.normalize(
                                system, f"{hue:03d} {lightness:02d} {chroma:02d}").code
            actual = color.nearest_codes(system, value, 1)[0]
            if actual["code"] != best_code:
                misses.append((index, actual["code"], best_code, round(actual["delta_e_ok"] - best_distance, 6)))
        assert not misses, (seed, system, misses)


# ---------------------------------------------------------------- codes

@pytest.mark.parametrize("system, raw, code", [
    ("hlc", "H040 L60 C40", "H040 L60 C40"),
    ("hlc", "hlc 40 60 40", "H040 L60 C40"),
    ("freiefarbe", "0406040", "H040 L60 C40"),
    ("ral", "ral 180 40 20", "RAL 180 40 20"),
    ("ral", "RAL3020", "RAL 3020"),
    ("ral-design-plus", "1804020", "RAL 180 40 20"),
    ("ncs", "s 1040-r20b", "NCS S 1040-R20B"),
    ("ncs", "NCS 0500-N", "NCS 0500-N"),
    ("munsell", "5r 4/14", "5R 4/14"),
    ("munsell", "2.5YR 6/8", "2.5YR 6/8"),
    ("munsell", "N5", "N 5/"),
    ("pantone", "PMS 185c", "185 C"),
    ("pantone", "Pantone® 19-4052 TCX", "19-4052 TCX"),
    ("pantone", "warm red u", "Warm Red U"),
    ("pantone", "100 CP", "100 CP"),
    ("freetone", "Freetone ft 100", "FT 100"),
])
def test_codes_normalize(system, raw, code):
    assert color.normalize(system, raw).code == code


@pytest.mark.parametrize("system, raw", [
    ("pantone", "19-4052 C"),          # an FHI number with a Graphics suffix
    ("pantone", "185 TCX"),            # a Graphics number with an FHI suffix
    ("pantone", "P 1-8 XGC"),
    ("ncs", "S 6050-R20B"),            # blackness + chromaticness above 100
    ("ncs", "S 1040-R20Y"),            # red is followed by blue, not yellow
    ("ncs", "S 1000-R"),               # no chromaticness is a neutral
    ("munsell", "12R 4/14"),
    ("hlc", "H360 L60 C40"),
    ("ral", "RAL 0999"),
    ("ral-design-plus", "RAL 400 40 20"),
    ("tailwind", "orange-700"),        # a name-and-value palette, not a code system
])
def test_invalid_codes_are_refused(system, raw):
    with pytest.raises(color.CodeError):
        color.normalize(system, raw)


def test_every_code_system_in_the_vocabulary_can_be_read():
    assert set(color.SYSTEMS) == set(color.PARSERS)


def test_a_pantone_number_without_suffix_is_incomplete():
    code = color.normalize("pantone", "185")
    assert not code.complete and "incomplete spec" in code.problem and "185 C" in code.problem


# ---------------------------------------------------------------- lookup and record

def test_lookup_computes_only_coordinate_codes(env, capsys):
    assert cli.main(["color", "lookup", "hlc", "H040 L60 C40", "--json"]) == 0
    hlc = json.loads(capsys.readouterr().out)
    assert hlc["computed"]["source_class"] == "computed" and hlc["computed"]["approximate"] is True
    assert hlc["computed"]["spec"] is False
    close(hlc["computed"]["oklch"], color.lch_d50_to_oklch(60, 40, 40), 1e-12)
    assert hlc["reference"]["url"].startswith("https://freiefarbe.de/")
    assert cli.main(["color", "lookup", "ncs", "NCS S 1040-R20B", "--json"]) == 0
    ncs = json.loads(capsys.readouterr().out)
    assert ncs["computed"] is None and ncs["records"] == [] and ncs["store"] == "code-and-link"
    assert not env["db"].exists()                                  # a lookup never creates the database


def test_coordinate_lookups_use_their_own_observer_and_white(env, capsys):
    assert cli.main(["color", "lookup", "ral-design-plus", "RAL 270 30 40", "--json"]) == 0
    ral = json.loads(capsys.readouterr().out)["computed"]
    close(ral["oklch"], (0.3948528636246044, 0.12846190304025193, 242.20783306994377), 1e-12)
    assert "D65/10°" in ral["method"] and "no chromatic adaptation" in ral["method"]
    assert "D65" in ral["note"] and "10°" in ral["note"]

    assert cli.main(["color", "lookup", "hlc", "H040 L60 C40", "--json"]) == 0
    hlc = json.loads(capsys.readouterr().out)["computed"]
    close(hlc["oklch"], (0.662509977784703, 0.10620743051385514, 35.55786320083996), 1e-12)
    assert "D50/2°" in hlc["method"] and "D50" in hlc["note"]


def test_incomplete_pantone_lookup_says_so_and_links_the_finder(env, capsys):
    assert cli.main(["color", "lookup", "pantone", "185"]) == 1
    out = capsys.readouterr().out
    assert "incomplete spec" in out and "https://www.pantone.com/color-finder" in out
    assert cli.main(["color", "lookup", "pantone", "19-4052 C"]) == 2


def test_records_keep_spec_and_detection_apart(env, capsys):
    base = ["color", "record", "pantone", "185 C"]
    assert cli.main([*base, "--hex", "336699", "--source-class", "screen-sample", "--use", "spec"]) == 2
    assert cli.main([*base, "--hex", "336699", "--source-class", "screen-sample", "--json"]) == 0
    sample = json.loads(capsys.readouterr().out)
    assert sample["use"] == "detection_only" and sample["hex"] == "#336699" and not sample["replaced"]
    assert cli.main([*base, "--oklch", "0.58", "0.23", "25", "--source-class", "provider", "--note", "Connect"]) == 0
    capsys.readouterr()
    assert cli.main([*base, "--oklch", "59%", "0.23", "25", "--source-class", "provider", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["replaced"] is True       # one value per source class
    capsys.readouterr()
    assert cli.main(["color", "lookup", "pantone", "pms 185c", "--json"]) == 0
    records = {r["source_class"]: r for r in json.loads(capsys.readouterr().out)["records"]}
    assert set(records) == {"screen-sample", "provider"}
    assert records["provider"]["use"] == "spec" and records["provider"]["oklch"][0] == pytest.approx(0.59)
    assert records["screen-sample"]["use"] == "detection_only"
    assert env["db"].exists() and list(env["project"].iterdir()) == []   # the user cache, never the project


@pytest.mark.parametrize("system, code, source_class, reason", [
    ("hlc", "H040 L60 C40", "provider", "does not allow provider"),
    ("freetone", "FT 100", "provider", "has no recordable class"),
])
def test_record_rejects_classes_not_allowed_by_the_system(env, capsys, system, code, source_class, reason):
    assert cli.main(["color", "record", system, code, "--hex", "336699",
                     "--source-class", source_class]) == 2
    output = capsys.readouterr()
    assert output.out == "" and len(output.err.splitlines()) == 1
    assert reason in output.err and not env["db"].exists()


def test_pantone_accepts_a_measured_record(env, capsys):
    assert cli.main(["color", "record", "pantone", "185 C", "--hex", "336699",
                     "--source-class", "measured", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["source_class"] == "measured"


@pytest.mark.parametrize("extra", [[], ["--hex", "336699", "--oklch", "0.5", "0.1", "20"], ["--hex", "E40"],
                                   ["--oklch", "1.5", "0.1", "20"]])
def test_record_needs_exactly_one_valid_value(env, extra):
    assert cli.main(["color", "record", "pantone", "185 C", *extra, "--source-class", "provider"]) == 2


def test_record_refuses_an_incomplete_code(env):
    assert cli.main(["color", "record", "pantone", "185", "--hex", "336699", "--source-class", "provider"]) == 2
    assert not env["db"].exists()


def test_the_database_refuses_a_screen_sample_spec(env):
    conn = db.connect(env["db"])
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("""INSERT INTO color_record (system, code, source_class, use, l, c, h, recorded_at)
                        VALUES ('pantone', '185 C', 'screen-sample', 'spec', 0.5, 0.2, 20, '2026-09-26')""")


# ---------------------------------------------------------------- search

def test_search_by_value_returns_nearest_candidates_with_delta_e(env, capsys):
    assert cli.main(["color", "record", "ncs", "S 1050-Y90R", "--hex", "D2462D", "--source-class", "measured"]) == 0
    capsys.readouterr()
    assert color.search_main(["#336699", "--json", "--limit", "4"]) == 0
    result = json.loads(capsys.readouterr().out)
    close(result["oklch"], REFERENCE_336699, 1e-12)
    by_group: dict[str, list] = {}
    for c in result["candidates"]:
        assert c["label"] == "nearest candidate"
        by_group.setdefault(c["source_class"] if c["source_class"] != "computed" else c["system"], []).append(c)
    assert set(by_group) == {"hlc", "ral-design-plus", "measured"}
    for group in by_group.values():
        distances = [c["delta_e_ok"] for c in group]
        assert distances == sorted(distances) and len(group) <= 4
    best = by_group["hlc"][0]
    close(best["oklch"], color.computed(color.normalize("hlc", best["code"]))["oklch"], 1e-12)
    assert best["delta_e_ok"] == pytest.approx(delta_e_ok(list(REFERENCE_336699), best["oklch"]))
    assert best["delta_e_ok"] < 0.03                                   # a grid step away at most
    assert by_group["measured"][0]["use"] == "spec"                   # records keep their own class and use


def test_search_by_code_routes_to_lookup(env, capsys):
    assert color.search_main(["RAL", "180", "40", "20"]) == 0
    routed = capsys.readouterr().out
    assert cli.main(["color", "lookup", "ral-design-plus", "RAL 180 40 20"]) == 0
    assert routed == capsys.readouterr().out
    assert color.search_main(["Pantone", "185"]) == 1
    assert color.search_main(["not", "a", "color"]) == 2


def test_search_reads_css_colors(env, capsys):
    assert color.search_main(["oklch(0.6 0.12 40)", "--json", "--limit", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["oklch"] == [0.6, 0.12, 40.0]
    assert color.search_main(["rgb(51 102 153)", "--json"]) == 0
    close(json.loads(capsys.readouterr().out)["oklch"], REFERENCE_336699, 1e-4)
    assert color.parse_color("#fff") == (pytest.approx(1, abs=1e-6), 0.0, None)   # white has no hue
