"""Run records the capture builds from browser font reports (render/DERIVED.md, font)."""
from __future__ import annotations

import pytest

from lapis_design.render.capture import _run


class _FontReport:
    """Answers the two DevTools calls the run builder makes with a fixed list of used faces."""

    def __init__(self, *faces: tuple[str, int]) -> None:
        self.faces = [{"familyName": name, "postScriptName": name.replace(" ", "-"), "isCustomFont": False,
                       "glyphCount": count} for name, count in faces]

    def send(self, method: str, params: dict) -> dict:
        if method == "DOM.pushNodesByBackendIdsToFrontend":
            return {"nodeIds": [1] * len(params["backendNodeIds"])}
        assert method == "CSS.getPlatformFontsForNode"
        return {"fonts": self.faces}


def _font(report: _FontReport, stack: str = "Pretendard, system-ui, sans-serif") -> dict:
    data = {"text": "48,000원", "original": "48,000원", "fontNodes": [[3, 0]], "lines": 1,
            "style": {"fontFamily": stack, "size": "16px", "weight": "600", "lineHeight": "24px",
                      "letterSpacing": "normal", "transform": "none", "style": "normal", "color": "rgb(0, 0, 0)",
                      "wordBreak": "keep-all", "lang": "ko-KR"}}
    return _run(data, "b000000000001", 0, report, {(3, 0): 11}, bytes(range(32)), set())["font"]


@pytest.mark.parametrize("face", ["Pretendard SemiBold", "Pretendard Semi Bold", "pretendard-bold italic"])
def test_static_face_named_with_its_weight_is_the_requested_family(face):
    assert _font(_FontReport((face, 8))) == {"requested": "Pretendard", "rendered": "Pretendard",
                                             "fallback": False}


def test_other_family_is_a_fallback_even_when_it_shares_a_prefix():
    assert _font(_FontReport(("Apple SD Gothic Neo", 8))) == {
        "requested": "Pretendard", "rendered": "Apple SD Gothic Neo", "fallback": True}
    assert _font(_FontReport(("Pretendard JP", 8)))["fallback"] is True
    assert _font(_FontReport(("Pretendard Bold", 2), ("Apple SD Gothic Neo", 6)))["rendered"] == "Apple SD Gothic Neo"
