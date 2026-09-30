"""Localized family names of Adobe Fonts faces: one helper process per language (`coretext.localized_names`).

No test reads a real Adobe font. The logic runs against a scripted stand-in for the helper process; the fake font
list of the other Adobe tests supplies the faces; the macOS tests run the real helper on system fonts that have
Korean, Japanese, and Chinese names (Hiragino Sans, PingFang, Apple SD Gothic Neo) and skip a font that is not
installed. `LAZULI_FONT_ROOTS` is set for every scan here, as everywhere in the test suite.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys

import pytest

from lazuli import cli, coretext, db, scan
from fake_adobe import FakeAdobe
from synthetic_fonts import build

macos = pytest.mark.skipif(sys.platform != "darwin", reason="Core Text exists only on macOS")
FIRST, SECOND = "SyncSans-Regular", "SyncSerif-Regular"


def said(name: str, language: str | None) -> dict:
    return {"name": name, "language": language}


class Helpers:
    """A scripted stand-in for `run_names_helper`: per language, the answer it returns or the exception it
    raises, and a record of what each call was asked."""

    def __init__(self, answers: dict | None = None) -> None:
        self.answers = answers or {}
        self.calls: list[tuple[str, list[str]]] = []

    def __call__(self, language: str, postscripts: list[str]):
        self.calls.append((language, list(postscripts)))
        answer = self.answers.get(language, {})
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def asked(self) -> dict[str, list[str]]:
        return dict(sorted(self.calls))


# ---------------------------------------------------------------- what is kept and how it is merged

@pytest.mark.parametrize("language, reported, kept", [
    ("ko", "ko", True), ("ko", "ko-KR", True), ("ja", "ja_JP", True),
    ("zh-Hans", "zh-Hans", True), ("zh-Hans", "zh-CN", True), ("zh-Hans", "zh", True),
    ("zh-Hant", "zh-Hant", True), ("zh-Hant", "zh-TW", True), ("zh-Hant", "zh-Hant-HK", True),
    ("zh-Hant", "zh-Hans", False), ("zh-Hans", "zh-Hant", False), ("zh-Hans", "zh-TW", False),
    ("ko", "en-US", False), ("ja", "en", False), ("ko", "ja", False), ("ko", "kok", False),
    ("ko", None, False), ("ko", "", False),
])
def test_a_name_is_kept_only_when_core_text_reports_the_language_asked_for(language, reported, kept):
    """Core Text falls back to English (or to another language) for a face with no name in the language asked
    for; that fallback must never be stored as a Korean, Japanese, or Chinese name."""
    names, problems = coretext.localized_names([FIRST], Helpers({language: {FIRST: said("이름", reported)}}))
    assert problems == []
    assert names == ({FIRST: {language: "이름"}} if kept else {})


def test_every_language_gets_one_call_with_every_name_and_the_answers_merge_per_face():
    helpers = Helpers({
        "ko": {FIRST: said("가", "ko"), SECOND: said("나", "ko"), "Other-Regular": said("다", "ko")},
        "ja": {FIRST: said("あ", "ja")},
        "zh-Hans": {SECOND: said("乙", "zh-Hans")},
        "zh-Hant": {SECOND: said("Second Serif", "en-US")},                # a fallback: dropped
    })
    names, problems = coretext.localized_names([SECOND, FIRST, FIRST], helpers)
    assert problems == []
    assert names == {FIRST: {"ko": "가", "ja": "あ"}, SECOND: {"ko": "나", "zh-Hans": "乙"}}   # nothing for a face not asked
    assert helpers.asked() == {language: [FIRST, SECOND] for language in coretext.NAMES_LANGUAGES}
    assert len(helpers.calls) == 4                                          # one process per language, not per face


def test_nothing_is_asked_when_there_are_no_faces():
    helpers = Helpers()
    assert coretext.localized_names([], helpers) == ({}, []) and helpers.calls == []


def test_a_helper_that_fails_leaves_its_language_absent_and_the_other_languages_stay():
    helpers = Helpers({
        "ko": subprocess.TimeoutExpired("helper", 60),
        "ja": subprocess.CalledProcessError(1, "helper"),
        "zh-Hans": [],                                                      # not the object the helper writes
        "zh-Hant": {FIRST: said("乙", "zh-Hant")},
    })
    names, problems = coretext.localized_names([FIRST], helpers)
    assert names == {FIRST: {"zh-Hant": "乙"}}
    assert problems == ["Adobe Fonts: ko names not read (TimeoutExpired)",
                        "Adobe Fonts: ja names not read (CalledProcessError)",
                        "Adobe Fonts: zh-Hans names not read (ValueError)"]


def test_a_helper_that_outlives_its_time_is_killed_and_every_language_is_reported(monkeypatch):
    """The real runner with a time no interpreter can start in: each helper is killed, none is waited for."""
    monkeypatch.delenv("LAZULI_FONT_ROOTS", raising=False)
    monkeypatch.setattr(coretext, "NAMES_TIMEOUT", 0.001)
    names, problems = coretext.localized_names(["Menlo-Regular"])
    assert names == {}
    assert problems == [f"Adobe Fonts: {language} names not read (TimeoutExpired)" for language in coretext.NAMES_LANGUAGES]


@pytest.mark.parametrize("args, stdin", [([], ""), (["--names"], "not json"), (["--names"], '{"a": 1}'), (["--names"], "[1, 2]")])
def test_the_helper_refuses_input_it_does_not_understand_before_it_asks_core_text(args, stdin):
    done = subprocess.run([sys.executable, "-P", "-m", "lazuli.coretext", *args], input=stdin,
                          capture_output=True, encoding="utf-8", timeout=60)
    assert (done.returncode, done.stdout) == (2, "") and "--names" in done.stderr


# ---------------------------------------------------------------- the scan

class NamedAdobe(FakeAdobe):
    """The fake font list, with the localized names of `CoreText` (identity to PostScript name and back) from a
    scripted helper instead of Core Text. `runner` None keeps the real one."""
    localized_names = coretext.CoreText.localized_names

    def __init__(self, folder, runner=None) -> None:
        super().__init__(folder)
        self.names_runner = runner


@pytest.fixture
def roots(tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("LAZULI_FONT_ROOTS", f"user={user}")
    monkeypatch.setenv("LAZULI_DB", str(tmp_path / "cache" / "lazuli.db"))
    return user


def listing(tmp_path, monkeypatch, runner=None) -> NamedAdobe:
    fake = NamedAdobe(tmp_path / "os-fonts", runner)
    monkeypatch.setattr(coretext, "provider", lambda: fake)
    return fake


def stored_names(tmp_path) -> dict[str, dict]:
    conn = db.connect(tmp_path / "cache" / "lazuli.db")
    return {row["family"]: json.loads(row["names_i18n_json"] or "{}") for row in conn.execute("SELECT * FROM local_font")}


def test_helper_names_are_stored_under_the_keys_files_use_and_find_the_face_like_a_file_face(roots, tmp_path,
                                                                                            monkeypatch, capsys):
    helpers = Helpers({"ko": {FIRST: said("다른 이름", "ko")}, "ja": {FIRST: said("シンク", "ja")},
                       "zh-Hans": {FIRST: said("同步", "zh-Hans")}, "zh-Hant": {FIRST: said("同步", "zh-Hant")}})
    fake = listing(tmp_path, monkeypatch, helpers)
    fake.add("Sync Sans", names_ko="싱크 산스")                                # the name the scan's own process learned
    build(roots / "Plain.ttf", family="Plain Sans", names_ko="보통 산스")
    assert cli.main(["local", "fonts", "--json", "--no-measure", "--family", "산스"]) == 0
    assert {family["family"] for family in json.loads(capsys.readouterr().out)} == {"Sync Sans", "Plain Sans"}
    names = stored_names(tmp_path)
    assert names["Sync Sans"] == {"ko": "싱크 산스", "ja": "シンク", "zh-Hans": "同步", "zh-Hant": "同步"}
    assert set(names["Sync Sans"]) <= set(scan.MAC_LANGS.values()) and names["Plain Sans"] == {"ko": "보통 산스"}
    assert cli.main(["local", "fonts", "--json", "--no-measure", "--family", "シンク"]) == 0
    assert [family["family"] for family in json.loads(capsys.readouterr().out)] == ["Sync Sans"]


def test_helpers_run_once_for_the_new_or_changed_faces_only(roots, tmp_path, monkeypatch):
    helpers = Helpers()
    fake = listing(tmp_path, monkeypatch, helpers)
    first, second = fake.add("Sync Sans"), fake.add("Sync Serif")
    conn = db.connect(tmp_path / "cache" / "lazuli.db")
    scan.scan(conn)
    assert helpers.asked() == {language: [FIRST, SECOND] for language in coretext.NAMES_LANGUAGES}
    helpers.calls.clear()
    scan.scan(conn)                                                         # nothing changed: nothing asked
    assert helpers.calls == []
    fake.entries[first] = (fake.entries[first][0], "Version 2.000")         # an update of one face
    scan.scan(conn)
    assert helpers.asked() == {language: [FIRST] for language in coretext.NAMES_LANGUAGES}
    helpers.calls.clear()
    conn.execute("UPDATE local_font SET metadata_json = NULL WHERE path = ?", (second,))   # a migration's refresh mark
    conn.commit()
    scan.scan(conn)
    assert helpers.asked() == {language: [SECOND] for language in coretext.NAMES_LANGUAGES}
    helpers.calls.clear()
    scan.scan(conn, rescan=True)
    assert helpers.asked() == {language: [FIRST, SECOND] for language in coretext.NAMES_LANGUAGES}


def test_a_failed_helper_is_reported_once_and_the_scan_goes_on(roots, tmp_path, monkeypatch, capsys):
    helpers = Helpers({"ko": subprocess.TimeoutExpired("helper", 60), "ja": {FIRST: said("シンク", "ja")}})
    listing(tmp_path, monkeypatch, helpers).add("Sync Sans")
    assert cli.main(["local", "fonts", "--json", "--no-measure"]) == 0
    captured = capsys.readouterr()
    assert [family["family"] for family in json.loads(captured.out)] == ["Sync Sans"]
    assert captured.err.count("skipped Adobe Fonts: ko names not read (TimeoutExpired)") == 1
    assert captured.err.count("names not read") == 1
    assert stored_names(tmp_path) == {"Sync Sans": {"ja": "シンク"}}


def test_font_roots_start_no_helper(roots, tmp_path, monkeypatch):
    """A test or an evaluation (`LAZULI_FONT_ROOTS` set) never starts a helper, even when the font list gives
    faces; without it the same call does, so the trap is what would have caught one."""
    started = []

    def trap(*args, **kwargs):
        started.append(args)
        raise AssertionError("a helper process was started")

    monkeypatch.setattr(subprocess, "Popen", trap)
    listing(tmp_path, monkeypatch).add("Sync Sans")                         # the real runner, `LAZULI_FONT_ROOTS` set
    result = scan.scan(db.connect(tmp_path / "cache" / "lazuli.db"))
    assert (result.adobe, result.unreadable, started) == (1, [], [])
    assert stored_names(tmp_path) == {"Sync Sans": {}}
    monkeypatch.delenv("LAZULI_FONT_ROOTS")
    with pytest.raises(AssertionError, match="helper process"):
        coretext.run_names_helper("ko", [FIRST])
    assert len(started) == 1


# ---------------------------------------------------------------- macOS: the real helper on system fonts

SYSTEM_FACES = [
    ("HiraginoSans-W3", "ja", r"[\u3040-\u30ff\u4e00-\u9fff]"),
    ("PingFangSC-Regular", "zh-Hans", r"[\u4e00-\u9fff]"),
    ("PingFangTC-Regular", "zh-Hant", r"[\u4e00-\u9fff]"),
    ("AppleSDGothicNeo-Regular", "ko", r"[\uac00-\ud7a3]"),
]


@macos
@pytest.mark.parametrize("postscript, language, script", SYSTEM_FACES)
def test_the_helper_answers_in_the_language_its_arguments_set(postscript, language, script, monkeypatch):
    """A new process with `-AppleLanguages (xx)` gets the localized family name Core Text has in that language,
    and reports that language; a face without one comes back in English, which the scan then discards."""
    monkeypatch.delenv("LAZULI_FONT_ROOTS", raising=False)
    english = coretext.run_names_helper("en", [postscript, "Menlo-Regular"])
    if postscript not in english:
        pytest.skip(f"{postscript} is not installed")
    answer = coretext.run_names_helper(language, [postscript, "Menlo-Regular"])
    assert coretext.language_key(answer[postscript]["language"]) == language
    assert re.search(script, answer[postscript]["name"]) and answer[postscript]["name"] != english[postscript]["name"]
    if "Menlo-Regular" in answer:                                           # no name in this language: a fallback
        assert coretext.language_key(answer["Menlo-Regular"]["language"]) is None


@macos
def test_the_provider_gives_names_by_identity_and_only_in_the_language_they_exist_in(monkeypatch):
    monkeypatch.delenv("LAZULI_FONT_ROOTS", raising=False)
    present = {postscript: (language, script) for postscript, language, script in SYSTEM_FACES
               if postscript in coretext.run_names_helper("en", [postscript])}
    if not present:
        pytest.skip("none of the system fonts with Korean, Japanese, and Chinese names is installed")
    identities = [coretext.IDENTITY_PREFIX + postscript for postscript in present] + ["coretext:Menlo-Regular", "not-an-identity"]
    names, problems = coretext.CoreText().localized_names(identities)
    assert problems == [] and "coretext:Menlo-Regular" not in names and "not-an-identity" not in names
    for postscript, (language, script) in present.items():
        found = names[coretext.IDENTITY_PREFIX + postscript]
        assert re.search(script, found[language])
        assert set(found) <= set(coretext.NAMES_LANGUAGES)
    if "AppleSDGothicNeo-Regular" in present:
        assert set(names["coretext:AppleSDGothicNeo-Regular"]) == {"ko"}    # no Japanese or Chinese name: none stored
