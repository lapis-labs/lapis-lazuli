"""Real browser journeys through synthetic pottery checkout and notices."""
from __future__ import annotations

import copy
import json
import re
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import jsonschema
import pytest
import yaml

from lapis_design import shared_dir
from lapis_design.behavior_check.driver import Driver
from lapis_design.behavior_check.probes import flows
from lapis_design.behavior_check.session import Session
from lapis_design.stub.engine import StubEngine

APP = Path(__file__).parent / "fixtures" / "behavior" / "flows-pottery"
STUB = APP / "pottery.stub.yaml"
PLAN = Path(__file__).parents[1] / "src" / "shared" / "plan" / "example.plan.yaml"


HINT = re.compile(r'\s?data-[a-z-]+="[^"]*"')


def _serve(plain):
    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?")[0] == "/app.js" and plain:
                body = HINT.sub("", (APP / "app.js").read_text()).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/javascript")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path.split("?")[0] not in ("/", "/index.html", "/app.js"):
                self.path = "/index.html"
            super().do_GET()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(APP)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    return server, worker


@pytest.fixture(params=["annotated", "plain"])
def any_server(request):
    server, worker = _serve(request.param == "plain")
    try:
        yield request.param, f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


@pytest.fixture
def pottery_server():
    server, worker = _serve(False)
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def test_plain_copy_has_no_hints():
    source = (APP / "app.js").read_text()
    assert "data-lapis-price" in source and not re.search(r"data-[a-z-]+=", HINT.sub("", source))


def execute(browser, url, plan, *, contexts=("m", "d")):
    session = Session(url, "kiln-shop-landing", engine=StubEngine.load(STUB), plan=plan)
    session.contexts = {name: session.contexts[name] for name in contexts}
    def open_driver(context):
        driver = Driver(browser, session, context)
        driver.open()
        return driver
    start = time.monotonic()
    flows.run(session, open_driver)
    document = session.document()
    return document, time.monotonic() - start, session.engine.effects_total


def test_pottery_flows_report_drip_system_line_phone_exit_and_pair(browser, any_server):
    mode, url = any_server
    stub_schema = yaml.safe_load((shared_dir() / "behavior" / "stub.schema.yaml").read_text())
    jsonschema.Draft202012Validator(stub_schema).validate(yaml.safe_load(STUB.read_text()))
    document, runtime, effects = execute(browser, url, yaml.safe_load(PLAN.read_text()))
    schema = yaml.safe_load((shared_dir() / "behavior" / "session.schema.yaml").read_text())
    jsonschema.Draft202012Validator(schema).validate(document)
    assert document["coverage"] == [{"probe": "flows", "status": "ran", "contexts": ["m", "d"]}], [
        (r["id"], r["context"], r["status"], [(s["path"], [(a["kind"], document["nodes"].get(a.get("target"), {}).get("name")) for a in s["actions"]]) for s in r["steps"]]) for r in document["flows"]]
    total = "order-total" if mode == "annotated" else "total"
    for context in ("m", "d"):
        runs = {r["id"]: r for r in document["flows"] if r["context"] == context}
        assert {r["status"] for r in runs.values()} == {"completed"}, runs
        reserve, subscribe, exit_run = (runs[k] for k in ("reserve-piece", "firing-notices", "stop-firing-notices"))
        assert reserve["derived"]["drip"] == ["service-fee"]
        assert reserve["derived"]["sneaked"] == ["kiln-handling"]
        assert {line["key"]: (line["added_by"], line["removable"]) for entry in reserve["cart"] for line in entry["lines"]} == {
            "insurance": ("preselected", True), "kiln-handling": ("system", False)}
        assert reserve["prices"][0]["components"][0]["amount"] == 30
        assert {c["key"]: (c["kind"], c["amount"], c["state"], c["mandatory"], c["placement"], c["user_caused"])
                for c in reserve["prices"][-1]["components"]} == {
            "celadon-cup": ("item", 30, "known", True, "primary", False),
            "service-fee": ("fee", 3, "known", True, "primary", False),
            "insurance": ("add-on", 5, "known", False, "primary", False),
            "kiln-handling": ("add-on", 4, "known", True, "primary", False),
            total: ("total", 42, "known", True, "primary", False)}
        fee = next(d for d in reserve["disclosures"] if d["kind"] == "fee")
        assert (fee["placement"], fee["at_commit"]) == ("near-commit", True)
        assert reserve["review_before_commit"] is True
        assert reserve["commit_step"] == next(s["index"] for s in reserve["steps"] if any(
            action.get("target") and document["nodes"][action["target"]].get("name") == "Confirm reservation"
            for action in s["actions"]))
        assert {(g["kind"], g["declared"]) for g in reserve["gates"]} == {("address", True), ("payment", False)}
        assert reserve["effort"]["fields"] == 2
        assert (subscribe["effort"]["steps"], subscribe["effort"]["interactions"]) == (2, 3)
        assert (exit_run["effort"]["steps"], exit_run["effort"]["interactions"]) == (4, 4)
        assert {r["commit_step"] for r in runs.values()} == {1, 2, 3}
        assert exit_run["effort"]["channel"] == "phone"
        assert [o["kind"] for s in exit_run["steps"] for o in s.get("offers", [])] == ["retention"]
        assert exit_run["effort"]["offers"] == exit_run["effort"]["blocking_offers"] == 1
        assert exit_run["derived"]["exit"] == {"pair": "firing-notices", "extra_steps": 2,
                                                "extra_interactions": 1, "added_reauth": False}
        assert {action["value_id"] for run in runs.values() for step in run["steps"]
                for action in step["actions"] if "value_id" in action} == {"v1", "v2", "v3"}
        assert {g["kind"] for g in exit_run["gates"]} == {"contact"}
        assert "gates" not in subscribe and not subscribe.get("cart")
    assert effects == 3  # reserve, subscribe, cancel; stub reset per context
    assert "hint_mismatch" not in json.dumps(document)   # the fixture's hints agree with the page
    for secret in ("10 Fictional Street", "potter@example.com", "4242"):
        assert secret not in json.dumps(document)
    print(f"{mode} pottery flows 2 contexts, 3 runs each: {runtime:.2f}s")


def test_clean_pottery_has_no_drip_sneak_or_exit_detour(browser, pottery_server):
    plan = copy.deepcopy(yaml.safe_load(PLAN.read_text()))
    for flow in plan["flows"]:
        flow["start"] = "/good"
        if "route" in flow["done"]:
            flow["done"]["route"] = "/good/reservations/*"
    document, runtime, effects = execute(browser, pottery_server, plan)
    for ctx in ("m", "d"):
        runs = {r["id"]: r for r in document["flows"] if r["context"] == ctx}
        assert all(r["status"] == "completed" for r in runs.values()), runs
        assert runs["reserve-piece"]["derived"]["drip"] == []
        assert runs["reserve-piece"]["derived"]["sneaked"] == []
        assert runs["stop-firing-notices"]["effort"]["channel"] == "self-serve"
        assert runs["stop-firing-notices"]["effort"]["offers"] == 0
        assert effects == 3
        assert runs["stop-firing-notices"]["derived"]["exit"]["pair"] == "firing-notices"
    print(f"clean flows 2 contexts, 3 runs each: {runtime:.2f}s")


def test_recurring_trial_discloses_or_hides_terms_at_commit(browser, any_server):
    mode, pottery_server = any_server
    plan = {"flows": [
        {"id": "opaque-membership", "kind": "subscribe", "goal": "Subscribe to studio membership",
         "start": "/membership", "done": {"text": "Membership started"}},
        {"id": "clear-membership", "kind": "subscribe", "goal": "Subscribe to studio membership",
         "start": "/membership-good", "done": {"text": "Membership started"}}]}
    document, runtime, effects = execute(browser, pottery_server, plan)
    expected = {"cadence", "cancellation-method", "renewal-price", "trial-conversion", "trial-end"}
    for context in ("m", "d"):
        runs = {r["id"]: r for r in document["flows"] if r["context"] == context}
        opaque, clear = runs["opaque-membership"], runs["clear-membership"]
        assert opaque["status"] == clear["status"] == "completed"
        assert opaque["trial"] is clear["trial"] is True
        assert opaque["prices"][0]["components"][0]["cadence"] == "month"
        assert opaque["prices"][0]["components"][0]["kind"] == "recurring"
        assert set(opaque["derived"]["hidden_terms"]) == expected
        assert {d["kind"]: (d["placement"], d["at_commit"]) for d in opaque["disclosures"]} == {
            kind: ("absent", False) for kind in expected}
        assert clear["derived"]["hidden_terms"] == []
        assert {d["kind"] for d in clear["disclosures"] if d["at_commit"]} == expected
        assert opaque["commit_step"] == clear["commit_step"] == 0
    assert effects == 2
    assert "hint_mismatch" not in json.dumps(document)
    print(f"{mode} membership trials 2 contexts, 2 runs each: {runtime:.2f}s")


def test_modal_offer_prefers_decline_and_does_not_fake_completion(browser, any_server):
    _, pottery_server = any_server
    plan = {"flows": [
        {"id": "optional-offer", "kind": "primary", "goal": "Reserve a piece",
         "start": "/dialog-good", "done": {"text": "Offer declined"}},
        {"id": "unanswerable-offer", "kind": "primary", "goal": "Reserve a piece",
         "start": "/dialog-bad", "done": {"text": "Offer declined"}}]}
    document, _, effects = execute(browser, pottery_server, plan)
    for context in ("m", "d"):
        runs = {r["id"]: r for r in document["flows"] if r["context"] == context}
        good, bad = runs["optional-offer"], runs["unanswerable-offer"]
        assert good["status"] == "completed" and bad["status"] == "blocked"
        assert good["steps"][0]["dialog"] in document["nodes"]
        assert document["nodes"][good["steps"][0]["actions"][0]["target"]]["name"] == "No thanks"
        assert good["steps"][-1]["actions"] == []
        assert good["effort"]["offers"] == good["effort"]["blocking_offers"] == 1
        assert bad["effort"]["offers"] == bad["effort"]["blocking_offers"] == 1
    assert effects == 0


def test_unpriced_commit_and_unclassified_exit_make_coverage_partial(browser, pottery_server):
    plan = {"flows": [
        {"id": "mystery-buy", "kind": "purchase", "goal": "Buy the piece", "start": "/silent-buy",
         "done": {"text": "Purchased"}},
        {"id": "stuck-exit", "kind": "unsubscribe", "goal": "Unsubscribe", "start": "/dead-end",
         "done": {"text": "Unsubscribed"}}]}
    document, _, effects = execute(browser, pottery_server, plan, contexts=("d",))
    runs = {r["id"]: r for r in document["flows"]}
    assert runs["mystery-buy"]["status"] == "completed" and "prices" not in runs["mystery-buy"]
    assert "channel" not in runs["stuck-exit"]["effort"]
    coverage = document["coverage"][0]
    assert coverage["status"] == "partial"
    assert "d/mystery-buy: commit reached without an observed price" in coverage["reason"]
    assert "d/stuck-exit: exit channel not classified" in coverage["reason"]
    assert effects == 1


def test_inline_shipping_choice_is_user_caused_not_drip(browser, any_server):
    _, pottery_server = any_server
    plan = {"flows": [{"id": "delivery", "kind": "purchase", "goal": "Choose delivery and continue",
                       "start": "/inline-shipping", "done": {"text": "Delivery chosen"}}]}
    document, _, effects = execute(browser, pottery_server, plan)
    for run in document["flows"]:
        assert run["status"] == "completed"
        assert [price["step"] for price in run["prices"]] == [0, 0]
        shipping = next(c for c in run["prices"][-1]["components"] if c["key"] == "express-shipping")
        assert shipping["user_caused"] is True and shipping["amount"] == 6
        assert run["derived"]["drip"] == []
    assert effects == 0


def test_hints_locate_and_group_but_the_page_reading_decides(browser, any_server):
    mode, url = any_server
    hinted = mode == "annotated"
    plan = {"flows": [{"id": "hinted-buy", "kind": "purchase", "goal": "Buy the piece",
                       "start": "/hinted", "done": {"text": "Purchased"}}]}
    document, _, effects = execute(browser, url, plan)
    total = "order-total" if hinted else "total"                  # data-lapis-key groups; it is not checked
    for run in document["flows"]:
        assert run["status"] == "completed" and run["commit_step"] == 0
        assert {c["key"]: (c["kind"], c["mandatory"], c["placement"], c.get("hint_mismatch"))
                for c in run["prices"][0]["components"]} == {
            "celadon-cup": ("item", True, "primary", None),
            "studio-fee": ("fee", True, "primary", ["mandatory", "placement"] if hinted else None),
            total: ("total", True, "primary", None)}
        assert [(o["kind"], o["blocks"], o.get("hint_mismatch")) for o in run["steps"][0]["offers"]] == [
            ("upsell", False, ["blocks"] if hinted else None)]
        disclosures = {d["kind"]: d.get("hint_mismatch") for d in run["disclosures"]}
        if hinted:
            # A hint the page reading cannot confirm keeps its value and names the field
            assert [(g["kind"], g["skippable"], g["hint_mismatch"]) for g in run["gates"]] == [
                ("payment", False, ["kind", "skippable"])]
            assert disclosures == {"renewal-price": ["kind"], "fee": None, "total": None}
        else:
            assert "gates" not in run and disclosures == {"fee": None, "total": None}
    assert effects == 1


def test_unreachable_goal_is_dead_end_not_success(browser, pottery_server):
    plan = {"flows": [{"id": "unreachable", "kind": "recover", "goal": "Recover a piece",
                       "start": "/dead-end", "done": {"text": "Recovered"}}]}
    document, _, effects = execute(browser, pottery_server, plan)
    assert document["coverage"][0]["status"] == "partial"
    assert {r["status"] for r in document["flows"]} == {"dead-end"}
    assert all(r["steps"][-1]["dead_end"] and r["effort"]["steps"] == 0 for r in document["flows"])
    assert effects == 0


def test_looping_flow_abandons_after_forty_actions(browser, pottery_server):
    plan = {"flows": [{"id": "endless", "kind": "recover", "goal": "Recover a piece",
                       "start": "/loop", "done": {"text": "Recovered"}}]}
    document, runtime, effects = execute(browser, pottery_server, plan, contexts=("m",))
    assert document["coverage"][0]["status"] == "partial"
    assert {r["status"] for r in document["flows"]} == {"abandoned"}
    assert all(r["effort"]["interactions"] == r["effort"]["steps"] == 40 and
               len(r["steps"][-1]["actions"]) == 0 for r in document["flows"])
    assert effects == 0
    print(f"loop flow 1 context, 40 actions: {runtime:.2f}s")


def test_local_dev_flows_remain_partial_without_activating_controls(pottery_server):
    plan = yaml.safe_load(PLAN.read_text())
    session = Session(pottery_server, "kiln-shop-landing", plan=plan, backend="local-dev", outbound="none",
                      values_engine=StubEngine.load(STUB))
    def must_not_open(_):
        pytest.fail("local-dev flow action would risk a commit")
    flows.run(session, must_not_open)
    document = session.document()
    assert "flows" not in document
    assert document["coverage"][0]["status"] == "partial"
    assert "require the stub backend" in document["coverage"][0]["reason"]
