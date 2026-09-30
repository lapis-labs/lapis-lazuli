"""The keyed text signatures in render/DERIVED.md, pinned with test vectors."""
import pytest

from lapis_design.text_sig import (key_id, normalize, page_sig, run_sig, shingles, similarity)

KEY = bytes(32)            # test key only; real keys are random and stay in the user's local cache


def test_key_id():
    assert key_id(KEY) == "66687aad"


def test_normalization():
    assert normalize("  Ｏｎｌｉｎｅ\tSALES​ ") == "online sales"      # NFKC, casefold, Cf removed
    assert normalize("Straße") == normalize("STRASSE")                      # case folding, not lowercasing
    assert normalize("a 　b") == "a b"                             # Unicode White_Space collapses


def test_shingles_by_script():
    assert shingles("Hi", "latn") == {"hi"}
    assert shingles("소성분", "hang") == {"소성", "성분"}
    assert shingles("🚀 go", "mixed") == {"🚀 ", " g", "go"}                  # code points, beyond the BMP too
    with pytest.raises(ValueError):
        shingles(" ​ ", "latn")                                         # nothing visible: no signature


def test_run_signature_vector():
    sig = run_sig("9월 소성분, 스물네 점이 나왔어요", "hang", KEY)
    assert sig == ("0c568fe4032194b90de609b6045d6a0e1c3e5a0c0392bbd610faf56e11231d27"
                   "1ea9d27113375be4023f5f8015519eb20ef96ef50680585a02e298b40acd0328")
    assert similarity(sig, sig) == 1.0


def test_signatures_ignore_case_spacing_and_invisible_characters():
    assert run_sig("Straße", "latn", KEY) == run_sig("STRASSE", "latn", KEY)
    assert run_sig("예약​하기", "hang", KEY) == run_sig("예약하기", "hang", KEY)


def test_signatures_depend_on_the_key():
    assert run_sig("예약하기", "hang", KEY) != run_sig("예약하기", "hang", b"\x01" * 32)


def test_page_signature_length_and_comparability():
    page = page_sig([("9월 소성분, 스물네 점이 나왔어요", "hang"), ("예약하기", "hang")], KEY)
    assert len(page) == 1024
    with pytest.raises(ValueError):
        similarity(page, run_sig("예약하기", "hang", KEY))


def test_page_signature_vector():
    import hashlib
    page = page_sig([("9월 소성분, 스물네 점이 나왔어요", "hang"), ("Reserve", "latn"), ("예약하기", "hang")], KEY)
    assert page.startswith("0c568fe4032194b90de609b6045d6a0e0a9b0da40392bbd6")
    assert hashlib.sha256(page.encode()).hexdigest() == "edd67ce0bb80f13e813babf85dd93bbcdae0eace44690bb024b23be89b092621"


def test_page_dominant_script_ties_follow_the_script_order():
    # 2 chars each: latn wins the tie, so the whole page is shingled in 5-grams
    assert page_sig([("ab", "latn"), ("가나", "hang")], KEY) == page_sig([("ab", "latn"), ("가나", "latn")], KEY)
