"""Scoped browser evidence for behavior driver, safety, and session validation."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import jsonschema
import pytest
import yaml

from lapis_design import shared_dir
from lapis_design.behavior_check.driver import Driver
from lapis_design.behavior_check.redact import console, path, text
from lapis_design.behavior_check.session import Session
from lapis_design.ours import SourcePin
from lapis_design.render.capture import capture
from lapis_design.stub.engine import StubEngine
from lapis_design.stub.remote import RemoteStub

SHOP = Path(__file__).parent / "fixtures" / "behavior" / "shop"
FIXTURE = SHOP / "shop.stub.yaml"


@pytest.fixture
def shop_server():
    class ShopHandler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/products":
                body = json.dumps(yaml.safe_load(FIXTURE.read_text())["collections"]["products"]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                super().do_GET()
    handler = partial(ShopHandler, directory=str(SHOP))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


@pytest.fixture
def shop_driver(browser, shop_server):
    session = Session(shop_server, "shop", engine=StubEngine.load(FIXTURE))
    driver = Driver(browser, session, "d")
    driver.open()
    try:
        yield driver
    finally:
        driver.close()


def test_paths_and_fixture_values():
    assert path("/reservations/r-2409-031?token=private#frag") == "/reservations/:id"
    assert path("/products/123e4567-e89b-12d3-a456-426614174000") == "/products/:id"
    assert path("/key/abcDEF0123456789xyz") == "/key/:id"
    assert path("/products/vase") == "/products/vase"
    assert path("/users/shopper%40example.com?x=secret", {"v1": "shopper@example.com"}) == "/users/{v1}"
    assert text("Hi shopper@example.com", {"v1": "shopper@example.com"}) == "Hi {v1}"
    assert text("Other alternate@example.com", {"v1:alternate": "alternate@example.com"}) == "Other {v1}"
    code = {"v3:invalid": "0000"}
    assert text("Timeout 30000ms exceeded", code) == "Timeout 30000ms exceeded"        # not inside another number
    assert text("Card 0000 was declined", code) == "Card {v3} was declined"
    assert text("김도예님, 환영해요", {"v4": "김도예"}) == "{v4}님, 환영해요"            # Korean particles still redact
    assert console("fetch https://test.invalid/orders/123e4567-e89b-12d3-a456-426614174000?q=secret abcDEF0123456789xyz") == "fetch test.invalid/orders/:id …"


def test_network_scope_without_live_external_connections(shop_driver):
    net = shop_driver.network
    class Request:
        def __init__(self, url, method="POST", kind="fetch", navigation=False):
            self.url, self.method, self.resource_type = url, method, kind
            self.headers, self._navigation, self.post_data_buffer = {}, navigation, None
            self.frame = shop_driver.page.main_frame
        def is_navigation_request(self):
            return self._navigation
    class Route:
        result = None
        def abort(self, reason):
            self.result = ("aborted", reason)
        def continue_(self):
            self.result = ("continued",)
    request = Request("https://unowned.example.invalid/api/charge")
    route = Route()
    net._route(route, request)
    assert route.result[0] == "aborted" and net.entries[-1]["blocked"] is True
    request = Request("https://unowned.example.invalid/image.png", "GET", "image")
    route = Route()
    net._route(route, request)
    assert route.result == ("continued",)
    request = Request("https://unowned.example.invalid/checkout", "GET", "document", True)
    route = Route()
    net._route(route, request)
    assert route.result[0] == "aborted" and net.external is True
    net.source = "app.test"
    shop_driver.session.source["addresses"] = ["127.0.0.1"]
    request = Request("https://app.test/api/unknown")
    route = Route()
    net._route(route, request)
    assert route.result == ("continued",)
    for hostname in ("www.app.test", "other.test", "app.local", "app.internal"):
        request = Request(f"https://{hostname}/api/charge")
        route = Route()
        net._route(route, request)
        assert route.result[0] == "aborted" and net.entries[-1]["blocked"] is True


def test_network_allows_exact_pinned_remote_stub_host(shop_driver):
    net = shop_driver.network
    shop_driver.session.engine = RemoteStub(
        "http://stub.test:8787", pin=SourcePin("stub.test", ("127.0.0.1",), "127.0.0.1"))

    class Request:
        method = "POST"
        resource_type = "fetch"
        headers = {}
        post_data_buffer = None
        frame = shop_driver.page.main_frame

        def __init__(self, url):
            self.url = url

        def is_navigation_request(self):
            return False

    class Route:
        def abort(self, reason):
            self.result = ("aborted", reason)

        def continue_(self):
            self.result = ("continued",)

    for host, expected in (("stub.test", "continued"), ("other.test", "aborted"),
                           ("www.stub.test", "aborted")):
        route = Route()
        net._route(route, Request(f"http://{host}:8787/api/orders"))
        assert route.result[0] == expected


def _box(driver, name):
    return next(box["id"] for box in driver.boxes() if box["name"] == name and box["role"] == "button")


def test_cart_live_status_dialog_and_noop(shop_driver):
    added = shop_driver.act({"kind": "click", "target": _box(shop_driver, "Add to cart")})
    assert added["outcome"] == "state-changed"
    assert any(r["method"] == "POST" and r["effects"] == 1 and r["path"] == "/api/cart"
               for r in added["requests"])
    assert shop_driver.page.locator("#status").get_attribute("data-lapis-box") in added["status_changed"]
    assert any(a["channel"] == "live-polite" and "Added" in a["text"] for a in added["announcements"])
    opened = shop_driver.act({"kind": "click", "target": _box(shop_driver, "Open shipping dialog")})
    assert opened["outcome"] == "dialog" and opened["dialog_opened"] in shop_driver.session.nodes
    shop_driver.act({"kind": "click", "target": _box(shop_driver, "Close dialog")})
    noop = shop_driver.act({"kind": "click", "target": _box(shop_driver, "No-op")})
    assert noop["outcome"] == "no-effect"


def test_layout_animation_tracks_geometry_frames(shop_driver):
    target = shop_driver.page.locator("#animated").get_attribute("data-lapis-box")
    effect = shop_driver.act({"kind": "click", "target": _box(shop_driver, "Expand card")})
    assert target in effect["layout_animated"]


@pytest.mark.parametrize(("button", "element", "animated"), [
    ("Expand instantly", "#instant", False),     # an instant expansion is a resize, not an animation
    ("Expand quickly", "#quick", False),         # a 30 ms transition: shorter than 50 ms
    ("Grow panel", "#growing", True),            # element.animate() on height
])
def test_layout_animation_needs_a_running_layout_animation(shop_driver, button, element, animated):
    target = shop_driver.page.locator(element).get_attribute("data-lapis-box")
    before = shop_driver.page.locator(element).bounding_box()
    effect = shop_driver.act({"kind": "click", "target": _box(shop_driver, button)})
    assert shop_driver.page.locator(element).bounding_box() != before   # the geometry did change
    assert (target in effect["layout_animated"]) is animated


@pytest.mark.parametrize("button", ["Expand instantly", "Expand quickly"])
def test_instant_and_short_expansions_are_resized_state_changes(shop_driver, button):
    element = {"Expand instantly": "#instant", "Expand quickly": "#quick"}[button]
    target = shop_driver.page.locator(element).get_attribute("data-lapis-box")
    effect = shop_driver.act({"kind": "click", "target": _box(shop_driver, button)})
    assert effect["resized"] == [target]                       # its section keeps its size
    assert effect["layout_animated"] == [] and effect["outcome"] == "state-changed"


def test_resized_leaves_out_animated_boxes_and_what_they_push(shop_driver):
    target = shop_driver.page.locator("#growing").get_attribute("data-lapis-box")
    effect = shop_driver.act({"kind": "click", "target": _box(shop_driver, "Grow panel")})
    assert effect["layout_animated"] == [target] and effect["resized"] == []
    assert shop_driver.act({"kind": "click", "target": _box(shop_driver, "No-op")})["resized"] == []


def test_fixture_input_actions_are_redacted(shop_driver):
    contact = shop_driver.page.locator("#contact").get_attribute("data-lapis-box")
    typed_action = {"kind": "type", "target": contact, "value": "valid"}
    typed = shop_driver.act(typed_action)
    assert shop_driver.page.locator("#contact").input_value() == "shopper@example.com"
    assert typed_action["value_id"] == "v1"
    assert any(change["attr"] == "value" and change["to"] == "{v1}" for change in typed["aria_changes"])
    assert "shopper@example.com" not in json.dumps(typed)
    checkbox = shop_driver.page.locator("#subscribe").get_attribute("data-lapis-box")
    checked = shop_driver.act({"kind": "check", "target": checkbox})
    assert any(change["attr"] == "aria-checked" and change["to"] == "true"
               for change in checked["aria_changes"])
    shop_driver.act({"kind": "uncheck", "target": checkbox})
    assert not shop_driver.page.locator("#subscribe").is_checked()
    pick = shop_driver.page.locator("#pick").get_attribute("data-lapis-box")
    selected = shop_driver.act({"kind": "select", "target": pick, "value_id": "v1"})
    assert shop_driver.page.locator("#pick").input_value() == "shopper@example.com"
    assert any(change["attr"] == "value" and change["to"] == "{v1}" for change in selected["aria_changes"])
    shop_driver.open()
    contact = shop_driver.page.locator("#contact").get_attribute("data-lapis-box")
    pasted = shop_driver.act({"kind": "paste", "target": contact, "value_id": "v1"})
    assert shop_driver.page.locator("#contact").input_value() == "shopper@example.com"
    assert "shopper@example.com" not in json.dumps(pasted)


def test_history_navigation_and_controlled_clock(shop_driver):
    link = next(box["id"] for box in shop_driver.boxes() if box["name"] == "Other route")
    effect = shop_driver.act({"kind": "click", "target": link})
    assert effect["navigation"] == "same-document" and effect["path"] == "/second"
    before = shop_driver.page.evaluate("Date.now()")
    assert shop_driver.session.engine.clock.now_ms() == before
    shop_driver.advance_clock(1200)
    assert shop_driver.page.evaluate("Date.now()") == before + 1200
    assert shop_driver.session.engine.clock.now_ms() == before + 1200


def test_external_navigation_stops_before_leaving_source(shop_driver, shop_server):
    link = next(box["id"] for box in shop_driver.boxes() if box["name"] == "External checkout")
    effect = shop_driver.act({"kind": "click", "target": link})
    assert effect["external"] is True
    assert effect["navigation"] == "document" and effect["outcome"] == "navigated"
    assert effect["path"] == "/reservations/:id"
    assert shop_driver.page.url == shop_server
    assert any(r.get("blocked") for r in effect["requests"])


def test_box_ids_match_render_capture(browser, shop_driver, shop_server, tmp_path):
    config = {"width": 1440, "layout_height": 900, "height": 900, "theme": "light",
              "reduced_motion": False, "browser_chrome": False, "dpr": 2}
    extract = capture(browser, shop_server, config, tmp_path / "shop.png", b"t" * 32)
    render_ids = {box["id"] for box in extract["boxes"]}
    driver_ids = {box["id"] for box in shop_driver.boxes()}
    assert render_ids == driver_ids

def test_extract_membership_and_context_variants(browser, shop_server, tmp_path):
    engine = StubEngine.load(FIXTURE)
    extract = tmp_path / "render.json"
    extract.write_text(json.dumps({"viewports": [{"boxes": [{"id": "b000000000001"}]}]}))
    session = Session(shop_server, "shop", engine=engine, extract=str(extract))
    session.node("b000000000001", role="button", context="m")
    assert session.document()["nodes"]["b000000000001"]["in_extract"] is True
    session.context("m-rm", reduced_motion=True, theme="dark", network="offline")
    driver = Driver(browser, session, "m-rm")
    try:
        driver.open()
        assert driver.page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
        assert driver.page.evaluate("matchMedia('(prefers-color-scheme: dark)').matches")
        assert driver.ctx["dir"] == "ltr"
        response = driver.page.evaluate("""async () => {
            try {await fetch('/api/products');return 'connected'} catch (_) {return 'offline'}
        }""")
        assert response == "offline"
    finally:
        driver.close()


def test_contexts_run_in_utc_unless_a_zone_is_given(browser, shop_server):
    for zone in (None, "Asia/Seoul"):
        session = Session(shop_server, "shop", engine=StubEngine.load(FIXTURE), **({"timezone": zone} if zone else {}))
        assert {ctx["timezone"] for ctx in session.contexts.values()} == {zone or "UTC"}
        driver = Driver(browser, session, "d")
        try:
            driver.open()
            assert driver.page.evaluate("Intl.DateTimeFormat().resolvedOptions().timeZone") == (zone or "UTC")
        finally:
            driver.close()


def test_cli_records_the_timezone_and_rejects_unknown_zones(shop_server, tmp_path):
    script = "import sys\nfrom lapis_design.behavior_check import main\nraise SystemExit(main(sys.argv[1:]))"
    command = [sys.executable, "-c", script, shop_server, "--task", "shop", "--stub", str(FIXTURE),
               "--probe", "console", "--context", "d"]
    output = tmp_path / "seoul.json"
    result = subprocess.run(command + ["--timezone", "Asia/Seoul", "--out", str(output)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert [ctx["timezone"] for ctx in json.loads(output.read_text())["contexts"]] == ["Asia/Seoul"]
    bad = subprocess.run(command + ["--timezone", "Mars/Olympus", "--out", str(tmp_path / "bad.json")],
                         capture_output=True, text=True)
    assert bad.returncode == 2 and "--timezone" in bad.stderr and not (tmp_path / "bad.json").exists()


def test_cli_pins_local_test_source_and_records_addresses(shop_server, tmp_path):
    script = """import sys
from lapis_design import ours
from lapis_design.behavior_check import main
ours.resolve_addresses = lambda host: ["127.0.0.1"]
raise SystemExit(main(sys.argv[1:]))
"""
    url = shop_server.replace("127.0.0.1", "app.test")
    output = tmp_path / "app.json"
    result = subprocess.run([sys.executable, "-c", script, url, "--task", "shop", "--stub", str(FIXTURE),
                             "--context", "d", "--probe", "console", "--out", str(output)],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text())["source"]["addresses"] == ["127.0.0.1"]
    stub_path = json.loads(output.read_text())["meta"]["stub"]
    assert stub_path == FIXTURE.relative_to(Path.cwd()).as_posix()
    assert not Path(stub_path).is_absolute()


def test_cli_pins_test_stub_url_without_proxy(shop_server, tmp_path):
    from lapis_design.stub.server import make_server
    server = make_server(StubEngine.load(FIXTURE), port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        script = """import sys
from lapis_design import ours
from lapis_design.behavior_check import main
ours.resolve_addresses = lambda host: ["127.0.0.1"]
raise SystemExit(main(sys.argv[1:]))
"""
        output = tmp_path / "remote.json"
        result = subprocess.run(
            [sys.executable, "-c", script, shop_server.replace("127.0.0.1", "app.test"),
             "--task", "shop", "--stub-url", f"http://stub.test:{server.server_port}",
             "--context", "d", "--probe", "console", "--out", str(output)],
            capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stderr
        assert json.loads(output.read_text())["source"]["addresses"] == ["127.0.0.1"]
        assert "stub" not in json.loads(output.read_text())["meta"]
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def test_cli_runs_every_probe_into_a_valid_session(shop_server, tmp_path):
    output = tmp_path / "shop.json"
    result = subprocess.run(["uv", "run", "lapis-design", "behavior", "check", shop_server, "--task", "shop",
                             "--stub", str(FIXTURE), "--out", str(output)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    document = json.loads(output.read_text())
    schema = yaml.safe_load((shared_dir() / "behavior" / "session.schema.yaml").read_text())
    jsonschema.Draft202012Validator(schema).validate(document)
    assert document["meta"]["stub"] == FIXTURE.relative_to(Path.cwd()).as_posix()
    assert not Path(document["meta"]["stub"]).is_absolute()
    from lapis_design.behavior_check.probes import PROBES
    expected = {name for module in PROBES for name in module.NAMES} | {"console"}
    assert {row["probe"] for row in document["coverage"]} == expected         # every probe says what ran
    assert document["nodes"] and {row["id"] for row in document["contexts"]} >= {"m", "d"}
    result = subprocess.run(["uv", "run", "lapis-design", "behavior", "check", "https://public.example.invalid/",
                             "--task", "shop", "--stub", str(FIXTURE), "--out", str(tmp_path / "invalid.json")],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert not (tmp_path / "invalid.json").exists()


def test_local_dev_values_only_and_missing_values_are_partial(shop_server, tmp_path):
    script = """
import sys
from lapis_design.behavior_check import main, probes
class InputProbe:
    NAMES = ('forms',)
    @staticmethod
    def run(session, open_driver):
        assert session.engine is None
        driver = open_driver('d')
        target = driver.page.locator('#contact').get_attribute('data-lapis-box')
        action = {'kind': 'type', 'target': target, 'value': 'valid'}
        effect = driver.act(action)
        assert driver.page.locator('#contact').input_value() == 'shopper@example.com'
        assert action['value_id'] == 'v1'
        assert any(c['attr'] == 'value' and c['to'] == '{v1}' for c in effect['aria_changes'])
        assert not any(r['path'] == '/api/products' and r.get('effects') for r in driver.network.entries)
        session.cover('forms', 'ran', contexts=['d'])
probes.PROBES = (InputProbe,)
raise SystemExit(main(sys.argv[1:]))
"""
    for use_values in (True, False):
        output = tmp_path / ("local-values.json" if use_values else "local-missing.json")
        command = [sys.executable, "-c", script, shop_server, "--task", "shop",
                   "--backend", "local-dev", "--outbound", "none", "--out", str(output)]
        if use_values:
            command += ["--values", str(FIXTURE)]
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        document = json.loads(output.read_text())
        forms = next(row for row in document["coverage"] if row["probe"] == "forms")
        assert forms["status"] == ("ran" if use_values else "partial")
        if not use_values:
            assert forms["reason"] == "no synthetic values (--values)"
        schema = yaml.safe_load((shared_dir() / "behavior" / "session.schema.yaml").read_text())
        jsonschema.Draft202012Validator(schema).validate(document)
