"""`lazuli adobe activate` and `kit`: the owner's quoted words, one named tool with exact arguments, and the stream as the
proof that exactly that call happened. Stub runner, invented fonts; nothing starts Codex or reaches Adobe."""
from __future__ import annotations

import json

import pytest

from lazuli.adobe import cli as adobe_cli, config, relay, store
from procedure_support import TASK
from test_adobe_relay import FAMILY, PS, FakeCodex, project, run, stream, tool_item

QUOTE = f"yes, activate {FAMILY} so we can compare it"
KIT_QUOTE = f"yes, publish a kit with {FAMILY} for example.com"
ACTIVATE_ARGS = {"font_identifier": {"postscript_name": PS}}
KIT_ARGS = {"domains": ["example.com"], "font_identifiers": [{"postscript_name": PS}]}
DONE = {"success": True, "user_message": "Added to your library.", "steps": [{"ok": True}], "summary": "internal"}


@pytest.fixture
def owner_project(tmp_path, monkeypatch):
    config.enable()
    monkeypatch.setattr(relay, "codex_binary", lambda: "/opt/codex-stub")
    return project(tmp_path,
                   f'[declared] Activate {FAMILY} for comparison: yes — "{QUOTE}"',
                   f'[declared] Publish the kit for example.com with {FAMILY}: yes — "{KIT_QUOTE}"')


def activate(root, fake, capsys, basis=QUOTE, *more):
    argv = ["activate", "--font", PS, "--task", TASK, "--project", str(root), *more]
    return run(argv + (["--basis", basis] if basis is not None else []), fake, capsys)


def test_activate_refuses_without_a_basis_and_starts_nothing(owner_project, capsys):
    fake = FakeCodex(stream([tool_item("activate", ACTIVATE_ARGS, DONE)]))
    code, out, err = activate(owner_project, fake, capsys, basis=None)
    assert (code, out) == (2, "") and "--basis is required" in err and fake.runs == []


@pytest.mark.parametrize("basis, reason", [
    ("the owner said it was fine to activate it", "is not in the owner's words"),
    ("yes", "too short"),
    (f"activate {FAMILY} right away", "is not in the owner's words"),                  # close to the record, not in it
])
def test_activate_refuses_a_basis_the_records_do_not_hold(owner_project, capsys, basis, reason):
    fake = FakeCodex(stream([tool_item("activate", ACTIVATE_ARGS, DONE)]))
    code, _, err = activate(owner_project, fake, capsys, basis=basis)
    assert code == 2 and "refused" in err and reason in err and fake.runs == []
    assert store.actions() == []


def test_activate_refuses_a_statement_that_names_another_font(owner_project, capsys):
    fake = FakeCodex(stream([tool_item("activate", {"font_identifier": {"postscript_name": "OtherFace-Regular"}}, DONE)]))
    code, _, err = run(["activate", "--font", "OtherFace-Regular", "--basis", QUOTE, "--task", TASK, "--project", str(owner_project)], fake, capsys)
    assert code == 2 and "does not name OtherFace-Regular" in err and fake.runs == []


def test_activate_refuses_where_the_project_records_no_owner_words(tmp_path, monkeypatch, capsys):
    config.enable()
    monkeypatch.setattr(relay, "codex_binary", lambda: "/opt/codex-stub")
    fake = FakeCodex("")
    code, _, err = activate(tmp_path, fake, capsys)
    assert code == 2 and "records no owner statement" in err and fake.runs == []


def test_activate_with_the_owners_words_makes_one_call_and_reports_the_stream(owner_project, capsys):
    fake = FakeCodex(stream([tool_item("activate", ACTIVATE_ARGS, DONE)]))
    code, out, err = activate(owner_project, fake, capsys)
    assert code == 0, err
    (call,) = fake.runs
    prompt = call["argv"][-1]
    assert "adobe_font_activate" in prompt and json.dumps(ACTIVATE_ARGS) in prompt
    assert prompt.count("mcp__codex_apps__adobe_font_") == 1 and "create_kit" not in prompt and "search" not in prompt
    assert "exactly one connector call, adobe.font_activate" in out and QUOTE in out and "done: Added to your library." in out
    (row,) = store.actions()
    assert (row["action"], row["task"], row["basis"], row["result"], row["calls_in_stream"]) == ("activate", TASK, QUOTE, "done", 1)
    assert row["provenance"] == "adobe-connector" and row["arguments"] == ACTIVATE_ARGS and row["outcome"] == {"success": True, "message": "Added to your library."}
    assert "bearer_token" not in json.dumps(row)
    assert store.records() == []                                                        # an action is not a search record


def test_activate_json_reports_the_call_the_stream_showed(owner_project, capsys):
    code, out, _ = activate(owner_project, FakeCodex(stream([tool_item("activate", ACTIVATE_ARGS, DONE)])), capsys, QUOTE, "--json")
    doc = json.loads(out)
    assert code == 0 and doc["tool"] == "adobe.font_activate" and doc["calls_in_stream"] == 1 and doc["arguments"] == ACTIVATE_ARGS
    assert doc["basis"] == QUOTE and doc["outcome"]["success"] is True


def test_a_refused_entitlement_is_reported_as_not_done(owner_project, capsys):
    payload = {"success": False, "error_code": "not_entitled", "user_message": "Your plan does not include this font."}
    code, out, _ = activate(owner_project, FakeCodex(stream([tool_item("activate", ACTIVATE_ARGS, payload)])), capsys)
    assert code == 1 and "not done (not_entitled): Your plan does not include this font." in out
    assert store.actions()[0]["result"] == "failed"


@pytest.mark.parametrize("items", [
    [tool_item("activate", ACTIVATE_ARGS, DONE), tool_item("activate", ACTIVATE_ARGS, DONE, item_id="item_2")],
    [tool_item("activate", ACTIVATE_ARGS, DONE), tool_item("create_kit", KIT_ARGS, {}, item_id="item_2")],
    [tool_item("search", {"user_query": "x"}, {"results": []}), tool_item("activate", ACTIVATE_ARGS, DONE, item_id="item_2")],
    [tool_item("create_kit", KIT_ARGS, {"success": True})],
    [tool_item("activate", {"font_identifier": {"postscript_name": "Sneaky-Bold"}}, DONE)],
    [tool_item("activate", {**ACTIVATE_ARGS, "bearer_token": "t"}, DONE)],
    [{"id": "c", "type": "command_execution", "command": "ls"}, tool_item("activate", ACTIVATE_ARGS, DONE)],
])
def test_a_stream_with_a_different_or_extra_call_is_refused_and_says_the_call_may_have_happened(owner_project, capsys, items):
    code, out, err = activate(owner_project, FakeCodex(stream(items)), capsys)
    assert code == 1 and out == "" and "result is not used" in err and "may already have happened" in err
    (row,) = store.actions()
    assert row["result"] == "refused-stream" and row["action"] == "activate"


def test_a_call_that_never_happened_is_logged_as_no_result(owner_project, capsys):
    code, _, err = activate(owner_project, FakeCodex(stream([], said="I could not find the tool")), capsys)
    assert code == 1 and "no connector call" in err and store.actions()[0]["result"] == "no-result"


def kit(root, fake, capsys, basis=KIT_QUOTE, fonts=(PS,), domains=("example.com",), *more):
    argv = ["kit", "--fonts", *fonts, "--domains", *domains, "--task", TASK, "--project", str(root), *more]
    return run(argv + (["--basis", basis] if basis is not None else []), fake, capsys)


def test_kit_refuses_without_the_words_the_font_or_the_domain(owner_project, capsys):
    fake = FakeCodex(stream([tool_item("create_kit", KIT_ARGS, {"success": True})]))
    assert kit(owner_project, fake, capsys, basis=None)[0] == 2
    assert "is not in the owner's words" in kit(owner_project, fake, capsys, basis="please publish the kit for me")[2]
    assert "does not name example.org" in kit(owner_project, fake, capsys, domains=("example.org",))[2]
    assert "does not name OtherFace-Regular" in kit(owner_project, fake, capsys, fonts=(PS, "OtherFace-Regular"))[2]
    assert "bare host names" in kit(owner_project, fake, capsys, domains=("https://example.com/",))[2]
    assert fake.runs == []


def test_kit_with_the_owners_words_makes_one_call_and_keeps_the_css_address_only(owner_project, capsys):
    payload = {"success": True, "user_message": "Kit published.", "kit": {
        "id": "abc1def", "name": "Kiln", "domains": ["example.com"], "families": [{"name": FAMILY}],
        "css_embed_code": '<link rel="stylesheet" href="https://use.typekit.net/abc1def.css">', "embed_code": "<script>x()</script>"}}
    fake = FakeCodex(stream([tool_item("create_kit", KIT_ARGS, payload)]))
    code, out, err = kit(owner_project, fake, capsys)
    assert code == 0, err
    prompt = fake.runs[0]["argv"][-1]
    assert "adobe_font_create_kit" in prompt and json.dumps(KIT_ARGS) in prompt and "activate" not in prompt
    assert "exactly one connector call, adobe.font_create_kit" in out and "https://use.typekit.net/abc1def.css" in out
    assert "<script>" not in out and "<script>" not in store.actions_path().read_text()
    assert store.actions()[0]["outcome"]["kit"]["id"] == "abc1def"


def test_a_kit_with_a_refused_font_lists_it(owner_project, capsys):
    payload = {"success": False, "error_code": "not_entitled", "user_message": "No kit was created.", "kit": None,
               "failures": [{"postscript_name": PS, "reason": "not_entitled"}]}
    code, out, _ = kit(owner_project, FakeCodex(stream([tool_item("create_kit", KIT_ARGS, payload)])), capsys)
    assert code == 1 and f"refused font {PS}: not_entitled" in out


def test_the_read_commands_cannot_name_an_action_tool():
    """`search`, `similar`, `details`, `styles`, and `preview` cannot name an action tool: their parsers have no such flag
    and `relay.READ_TOOLS` lists no action."""
    assert not set(relay.READ_TOOLS) & set(relay.ACTION_TOOLS)
    parser = adobe_cli._parser("x")
    for verb in relay.READ_TOOLS:
        with pytest.raises(SystemExit):
            parser.parse_args([verb, PS, "--basis", "x"])
