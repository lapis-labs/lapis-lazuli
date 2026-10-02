"""The flow driver makes the choices a screen needs (DERIVED.md, Flows, Choices) and reads a price the way the
choices probe does. Loopback pages: required terms, privacy, and radio groups behind visually hidden inputs, custom
ARIA radios, a fee that appears after the terms are agreed to, a commit that asks for terms after it, and price rows
with a leading ISO code or a leading Korean period."""
from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from lapis_design.behavior_check.driver import Driver
from lapis_design.behavior_check.probes import commits, flows
from lapis_design.behavior_check.session import Session
from lapis_design.stub.engine import StubEngine

APP = Path(__file__).parent / "fixtures" / "behavior" / "flows-choices"
STUB = APP / "choices.stub.yaml"
CONSENT = "결과: plan=basic;cycle=monthly;channel=-;terms=1;privacy=1;all=0;marketing=0;notify=0"
TERMS = "[필수] 서비스 이용약관에 동의"
PRIVACY = "[필수] 개인정보 수집·이용에 동의"


@pytest.fixture(scope="module")
def site():
    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(APP)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def _run(browser, site, page, done, *, kind="primary", goal="Join and continue", probes=(flows,)):
    plan = {"flows": [{"id": "flow", "kind": kind, "goal": goal, "start": f"/{page}",
                       "done": {"text": done}, "requires": []}]}
    session = Session(site + page, "flow-choices", engine=StubEngine.load(STUB), plan=plan)
    session.contexts = {"d": session.contexts["d"]}
    drivers = []

    def open_driver(ctx):
        driver = Driver(browser, session, ctx)
        driver.open()
        drivers.append(driver)
        return driver

    try:
        for probe in probes:
            probe.run(session, open_driver)
        return session.document()               # validates the document against session.schema.yaml
    finally:
        for driver in drivers:
            driver.close()


def _acted(document):
    """(kind, name of the target, choice) of every action of the one run, in order. A label's box has no accessible
    name, so it is shown as its role."""
    (run,) = document["flows"]
    nodes = document["nodes"]
    return [(action["kind"], nodes[action["target"]]["name"] or f"<{nodes[action['target']]['role']}>",
             action.get("choice")) for step in run["steps"] for action in step["actions"]]


def _status(document):
    (run,) = document["flows"]
    return run["status"]


def test_flow_tries_forward_then_makes_every_choice_in_document_order_then_tries_forward_again(browser, site):
    document = _run(browser, site, "consent.html", CONSENT)
    assert _status(document) == "completed"
    # 다음 first (nothing happens), the plan that is free, then the two required checkboxes, then 다음 again. The
    # links in main were never followed, the preselected 결제 주기 and the optional 알림 채널 were left alone,
    # and 전체 동의, the marketing checkbox, and the switch were not pressed (CONSENT says so).
    assert _acted(document) == [
        ("click", "다음", None), ("check", "Basic 무료", "required-radio"),
        ("check", TERMS, "required-checkbox"), ("check", PRIVACY, "required-checkbox"), ("click", "다음", None)]
    (run,) = document["flows"]
    assert {step["path"] for step in run["steps"]} == {"/consent.html"}
    assert run["effort"]["interactions"] == 5
    assert next(c for c in document["coverage"] if c["probe"] == "flows")["status"] == "ran"


def test_flow_answers_an_agreement_group_agreeing_a_priced_offer_declined_and_the_lowest_price(browser, site):
    document = _run(browser, site, "agree.html", "결과: terms=agree;wrap=none;size=small")
    assert _status(document) == "completed"
    # The wrapping choices are transparent inputs, which have no box: the option is pressed through its label's box.
    assert [(kind, name) for kind, name, _ in _acted(document)] == [
        ("click", "다음"), ("check", "동의해요"), ("check", "<text>"), ("check", "Small ₩20,000"), ("click", "다음")]


def test_flow_chooses_custom_aria_radios_and_a_checkbox_the_page_marked_invalid_after_the_first_try(browser, site):
    document = _run(browser, site, "aria.html", "결과: shipping=standard;terms=1")
    assert _status(document) == "completed"
    assert _acted(document) == [
        ("click", "다음", None), ("check", "일반 배송 무료", "required-radio"),
        ("check", "이용약관에 동의합니다", "required-checkbox"), ("click", "다음", None)]


def test_a_terms_checkbox_does_not_make_the_fee_after_it_user_caused(browser, site):
    document = _run(browser, site, "fee.html", "주문 완료", kind="purchase", goal="도자기 컵 결제하기")
    assert _status(document) == "completed"
    # The terms input is transparent: it has no box, and the choice is pressed through its label's box.
    assert _acted(document) == [("click", "결제하기", None), ("check", "<text>", "required-checkbox"),
                                ("click", "결제하기", None)]
    (run,) = document["flows"]
    components = {c["kind"]: c for price in run["prices"] for c in price["components"]}
    assert components["fee"]["amount"] == 1000 and components["fee"]["user_caused"] is False


def test_the_choices_are_recorded_and_replayed_with_the_step_for_the_commit_probe(browser, site):
    document = _run(browser, site, "fee.html", "주문 완료", kind="purchase", goal="도자기 컵 결제하기",
                    probes=(flows, commits))
    (run,) = document["flows"]
    assert run["commit_step"] == 0
    (commit,) = document["probes"]["commits"]
    assert document["nodes"][commit["box"]]["name"] == "결제하기" and commit["flow"] == "flow"
    reason = next(entry for entry in document["coverage"] if entry["probe"] == "commits").get("reason") or ""
    assert "could not be reached" not in reason


def test_a_choice_after_the_commit_is_not_taken_for_the_commit_control(browser, site):
    document = _run(browser, site, "late-choice.html", "배송 약관을 확인했어요", kind="purchase",
                    goal="도자기 컵 결제하기", probes=(flows, commits))
    # The first press of 결제하기 sent the order and changed the page, so it was pressed again before the choice.
    assert _acted(document)[-1] == ("check", "[필수] 배송 약관에 동의", "required-checkbox")
    (commit,) = document["probes"]["commits"]
    assert document["nodes"][commit["box"]]["name"] == "결제하기"


def test_flow_reads_a_price_with_a_leading_iso_code_and_a_period_before_the_amount(browser, site):
    usd = _run(browser, site, "price-usd.html", "Done", goal="Continue")
    (run,) = usd["flows"]
    components = {c["key"]: c for c in run["prices"][0]["components"]}
    assert run["prices"][0]["currency"] == "USD"
    assert (components["pro-plan"]["kind"], components["pro-plan"]["amount"], components["pro-plan"]["cadence"]) == (
        "recurring", 12.0, "month")
    assert components["setup-fee"]["kind"] == "fee" and components["setup-fee"]["amount"] == 5.0

    korean = _run(browser, site, "price-ko.html", "완료", goal="계속")
    (run,) = korean["flows"]
    assert run["prices"][0]["currency"] == "KRW"
    recurring = next(c for c in run["prices"][0]["components"] if c["kind"] == "recurring")
    assert (recurring["amount"], recurring["cadence"]) == (9900.0, "month")
