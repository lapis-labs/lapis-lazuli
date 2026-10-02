"""Calibration scores independent measured width and form without silently scoring missing faces."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "calibration"))
import calibrate
from fontTools import unicodedata as unicode_data
from lazuli import db


def test_report_records_the_measured_unicode_version_and_compares_with_no_older_report(tmp_path):
    conn = db.connect(tmp_path / "calibration.db")
    try:
        text = calibrate.report(conn)
    finally:
        conn.close()
    assert f"Unicode {unicode_data.unidata_version}" in text.split("## Sources")[0]
    assert "## Comparison with" not in text and "Baseline" not in text      # the old values were made with Adobe faces



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
