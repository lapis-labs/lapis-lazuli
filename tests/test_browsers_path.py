"""tests/conftest.py: the Playwright browser folder that tests hand to CLI subprocesses running in other folders."""
from __future__ import annotations

import pytest

import conftest


def installed_browsers(monkeypatch, value):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", value)
    return conftest._installed_browsers()


def test_relative_folder_becomes_absolute_against_the_current_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert installed_browsers(monkeypatch, "browsers") == str(tmp_path / "browsers")


def test_zero_stays_zero_because_it_means_the_browsers_inside_the_package(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert installed_browsers(monkeypatch, "0") == "0"


def test_absolute_folder_stays_as_it_is(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    folder = str(tmp_path / "elsewhere" / "pw")
    assert installed_browsers(monkeypatch, folder) == folder


@pytest.mark.parametrize("value", ["~", "~/pw"])
def test_home_shorthand_is_not_expanded_because_playwright_does_not_either(tmp_path, monkeypatch, value):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert installed_browsers(monkeypatch, value) == str(tmp_path / value)
