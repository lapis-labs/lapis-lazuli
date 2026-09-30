"""Calibration scores independent measured width and form without silently scoring missing faces."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "calibration"))
import calibrate
from fontTools import unicodedata as unicode_data
from lazuli import db


def test_report_records_measured_unicode_version_and_previous_baseline(tmp_path):
    conn = db.connect(tmp_path / "calibration.db")
    try:
        text = calibrate.report(conn)
    finally:
        conn.close()
    assert f"Unicode {unicode_data.unidata_version}" in text.split("## Sources")[0]
    assert text.index("## Comparison with 14a985c") < text.index("## Comparison with 1497d3f")



def test_mono_serif_scores_as_serif_while_monospace_is_separate():
    def family(name, *, serif=None, mono=None):
        metrics = {} if serif is None else {"serif": serif, "monospaced": mono}
        return {"family": name, "faces": [{"kind": "text", "metrics": metrics, "panose": {}, "cjk": {}}]}

    families = [family("Fixed Serif", serif=True, mono=True), family("Wide Serif", serif=True, mono=False),
                family("Fixed Sans", serif=False, mono=True), family("Unknown Serif"), family("Catalog Mono",
                serif=False, mono=True)]
    labels = {"Fixed Serif": {"google-fonts": {"serif", "mono"}},
              "Wide Serif": {"google-fonts": {"serif"}},
              "Fixed Sans": {"google-fonts": {"sans"}},
              "Unknown Serif": {"google-fonts": {"serif"}},
              "Catalog Mono": {"google-fonts": {"mono"}}}
    latin = "\n".join(calibrate.latin_section(families, labels))
    mono = "\n".join(calibrate.mono_section(families, labels))
    assert "| **serif** | 2 | 0 | 1 | 3 |" in latin
    assert "| **sans** | 0 | 1 | 0 | 1 |" in latin
    assert "| serif | 2 | 2 | 1.000 | 1.000 |" in latin
    assert "| sans | 1 | 1 | 1.000 | 1.000 |" in latin
    assert "| google-fonts | 4 | 2 | 2 | 1 | 0 | 1 | 0.667 | 1.000 |" in mono
    assert "Fixed Sans (google-fonts): catalog not mono, measured mono" in mono



def test_comparison_reports_missing_measurements_beside_each_score():
    families = [
        {"family": "Known Serif", "faces": [{"kind": "text", "metrics": {"serif": True, "monospaced": True}}]},
        {"family": "Missing Serif", "faces": [{"kind": "text", "metrics": {}}]},
        {"family": "Known Sans", "faces": [{"kind": "text", "metrics": {"serif": False, "monospaced": False}}]},
    ]
    labels = {
        "Known Serif": {"google-fonts": {"serif", "mono"}},
        "Missing Serif": {"google-fonts": {"serif"}},
        "Known Sans": {"google-fonts": {"sans"}},
    }
    comparison = "\n".join(calibrate.comparison_section(families, labels, labels))
    assert "13ba6c5" in comparison
    assert "| Latin serif (google-fonts) | 0.952 / 0.952; not measured 6 | 1.000 / 1.000; not measured 1 |" in comparison
    assert "| Monospace (google-fonts) | 0.600 / 1.000; not measured 110 | 1.000 / 1.000; not measured 1 |" in comparison
    assert "| Latin sans (fontsource) | 1.000 / 0.931; not measured 102 | — / —; not measured 0 |" in comparison
    assert "| Monospace (sandoll) | — / —; not measured 3 | — / —; not measured 0 |" in comparison


def test_comparison_with_previous_report_scores_symbol_and_hand_on_same_labeled_cohort():
    families = [
        {"family": "True Hand", "faces": [{"kind": "hand", "metrics": {}}]},
        {"family": "False Hand", "faces": [{"kind": "hand", "metrics": {}}]},
        {"family": "Missed Symbol", "faces": [{"kind": "symbol", "metrics": {}}]},
        {"family": "Not Measured", "faces": [{"kind": None, "metrics": {}}]},
    ]
    labels = {
        "True Hand": {"fontsource": {"hand"}},
        "False Hand": {"fontsource": {"sans"}},
        "Missed Symbol": {"fontsource": {"serif"}},
        "Not Measured": {"fontsource": {"sans"}},
    }
    comparison = "\n".join(calibrate.comparison_section(families, labels, labels))
    assert comparison.startswith("## Comparison with 14a985c")
    assert "| Symbol misclassifications | 1; not measured 1 | 1; not measured 1 |" in comparison
    assert "| Hand precision | 1.000; not measured 1 | 0.500; not measured 1 |" in comparison
    assert "| Latin serif (google-fonts) | 0.955 / 1.000; not measured 6 | — / —; not measured 0 |" in comparison
    assert "| Symbol misclassifications | 7; not measured 1 | 1; not measured 1 |" in comparison
    assert "| Hand precision | 0.500; not measured 1 | 0.500; not measured 1 |" in comparison