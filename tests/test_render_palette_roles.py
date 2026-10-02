"""The data role a palette color can be guessed to have, from the painting box's own class and id."""
from __future__ import annotations

import pytest

from lapis_design.render.fields.palette import _role


def guess(tag: str = "div", box_role: str = "card", **attrs: str) -> str:
    return _role({"id": "b1", "role": box_role}, {"tag": tag, "attrs": attrs})


@pytest.mark.parametrize("attrs", [
    {"class": "chart"}, {"class": "card bar-chart"}, {"class": "lineChart"}, {"class": "revenue_graph"},
    {"id": "Sparkline"}, {"class": "plot-area"}, {"class": "JSChart"}, {"class": "chart-2"},
])
def test_a_box_that_holds_a_chart_word_in_its_class_or_id_paints_data(attrs):
    assert guess(**attrs) == "data"


@pytest.mark.parametrize("attrs", [
    {"class": "MuiTypography-root"}, {"class": "paragraph"}, {"class": "hero-graphic"},
    {"class": "photograph-frame"}, {"id": "geography"}, {"class": "charting"}, {"role": "graphics-document"},
    {"role": "chart"},
])
def test_a_chart_word_inside_a_longer_word_or_in_the_role_names_nothing(attrs):
    assert guess(**attrs) != "data"


def test_table_cells_paint_data():
    assert guess(tag="td", box_role="text") == "data"
    assert guess(tag="th", box_role="text") == "data"

