"""Fixture contract, effects, transport, and in-browser routing behavior."""
from __future__ import annotations

import copy
import ipaddress
import json
import socket
import ssl
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from jsonschema import Draft202012Validator

from lapis_design import ours
from lapis_design.behavior_check.session import Session
from lapis_design.ours import SourcePin
from lapis_design.stub.engine import StubEngine
from lapis_design.stub.playwright import respond
from lapis_design.stub.remote import RemoteStub
from lapis_design.stub.server import make_server

ROOT = Path(__file__).resolve().parents[1] / "src" / "shared" / "behavior"
FIXTURE = ROOT / "example.stub.yaml"


def engine():
    return StubEngine.load(FIXTURE)


def call(stub, method, path, body=None, headers=None):
    return stub.handle(method, path, "", headers or {}, json.dumps(body).encode() if body is not None else None)


def content(response):
    return json.loads(response.body)

@pytest.mark.parametrize("addresses", [[], ["8.8.8.8"], ["127.0.0.1", "8.8.8.8"]])
def test_behavior_rejects_unverified_test_source_without_browser(monkeypatch, capsys, addresses):
    from lapis_design.behavior_check import main
    monkeypatch.setattr(ours, "resolve_addresses", lambda host: addresses)
    with pytest.raises(SystemExit) as error:
        main(["http://app.test/", "--task", "demo", "--stub", str(FIXTURE)])
    assert error.value.code == 2
    assert "host that is ours" in capsys.readouterr().err


@pytest.mark.parametrize("host", ["app.local", "app.internal"])
def test_behavior_rejects_other_names_without_resolving(monkeypatch, host):
    from lapis_design.behavior_check import main
    def cannot_resolve(host):
        raise AssertionError("unexpected DNS")
    monkeypatch.setattr(ours, "resolve_addresses", cannot_resolve)
    with pytest.raises(SystemExit) as error:
        main([f"http://{host}/", "--task", "demo", "--stub", str(FIXTURE)])
    assert error.value.code == 2


@pytest.mark.parametrize("addresses", [[], ["127.0.0.1", "8.8.8.8"]])
def test_behavior_rejects_unverified_test_stub_without_browser(monkeypatch, capsys, addresses):
    from lapis_design.behavior_check import main
    monkeypatch.setattr(ours, "resolve_addresses", lambda host: addresses)
    with pytest.raises(SystemExit) as error:
        main(["http://127.0.0.1/", "--task", "demo", "--stub-url", "http://stub.test:9000/"])
    assert error.value.code == 2
    assert "--stub-url must use HTTP(S) on a host that is ours" in capsys.readouterr().err


def test_behavior_session_requires_addresses_exactly_for_test_source():
    session = Session("http://app.test/", "demo", engine=engine())
    with pytest.raises(ValueError, match="invalid behavior session"):
        session.document()
    session.source["addresses"] = ["127.0.0.1"]
    assert session.document()["source"]["addresses"] == ["127.0.0.1"]
    session.source["url"] = "http://localhost/"
    with pytest.raises(ValueError, match="invalid behavior session"):
        session.document()



def test_fixture_schema_accepts_example_and_rejects_invalid_route():
    schema = yaml.safe_load((ROOT / "stub.schema.yaml").read_text())
    Draft202012Validator.check_schema(schema)
    fixture = yaml.safe_load(FIXTURE.read_text())
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors(fixture)) == []
    broken = copy.deepcopy(fixture)
    broken["routes"][0]["operation"] = "send-money"
    assert list(validator.iter_errors(broken))
    broken = copy.deepcopy(fixture)
    broken["values"]["v2"]["valid"] = "actual@personal.test"
    assert list(validator.iter_errors(broken))
    broken = copy.deepcopy(fixture)
    broken["values"]["v5"]["valid"] = "4111 1111 1111 1111"
    assert list(validator.iter_errors(broken))


def _renamed_fixture(**rename):
    fixture = yaml.safe_load(FIXTURE.read_text())
    for old, new in rename.items():
        fixture["values"][new] = fixture["values"].pop(old)
        fixture["accounts"] = {field: new if ref == old else ref for field, ref in fixture["accounts"].items()}
    return fixture


@pytest.mark.parametrize("make,named", [
    (lambda: _renamed_fixture(v1="patient-name"), "values key 'patient-name' is not a value id"),
    (lambda: _renamed_fixture(v5="a:b"), "values key 'a:b' is not a value id"),
    (lambda: _renamed_fixture(v1="patient-name", v5="a:b"), "values keys 'patient-name', 'a:b' are not value ids"),
    (lambda: _renamed_fixture(v2="patient-email"),
     "values key 'patient-email', accounts.username 'patient-email' are not value ids"),
    (lambda: {**_renamed_fixture(), "accounts": {"username": "v2", "password": "secret"}},
     "accounts.password 'secret' is not a value id"),
])
def test_stub_values_must_be_named_v_n_and_the_error_says_which_and_how(tmp_path, make, named):
    fixture = make()
    with pytest.raises(ValueError, match="value ids are v1, v2, …") as direct:
        StubEngine(fixture)
    assert named in str(direct.value)
    path = tmp_path / "bad.stub.yaml"
    path.write_text(yaml.safe_dump(fixture, allow_unicode=True, sort_keys=False))
    with pytest.raises(ValueError, match="value ids are v1, v2, …") as loaded:
        StubEngine.load(path)                       # not the schema's own multi-line dump
    assert named in str(loaded.value) and "\n" not in str(loaded.value)


def test_behavior_check_reports_a_stub_whose_values_are_not_v_n_before_starting_a_browser(tmp_path, capsys):
    from lapis_design.behavior_check import main
    path = tmp_path / "bad.stub.yaml"
    path.write_text(yaml.safe_dump(_renamed_fixture(v1="patient-name")))
    assert main(["http://127.0.0.1:9/", "--task", "demo", "--stub", str(path), "--out", str(tmp_path / "out.json")]) == 2
    err = capsys.readouterr().err
    assert "values key 'patient-name' is not a value id" in err and "value ids are v1, v2, …" in err
    assert not (tmp_path / "out.json").exists()


def test_collection_effects_and_idempotency_replay():
    stub = engine()
    assert len(content(call(stub, "GET", "/api/pieces"))) == 2
    assert content(call(stub, "GET", "/api/pieces/p1"))["glaze"] == "celadon"
    created = call(stub, "POST", "/api/reservations", {"piece_id": "p1"}, {"Idempotency-Key": "reserve-1"})
    rid = content(created)["id"]
    assert created.status == 201 and created.effects == 1 and rid
    replay = call(stub, "POST", "/api/reservations", {"piece_id": "p2"}, {"Idempotency-Key": "reserve-1"})
    assert content(replay) == content(created) and replay.effects == 0
    assert len(content(call(stub, "GET", "/api/reservations"))) == 1
    assert content(call(stub, "PATCH", f"/api/reservations/{rid}", {"note": "gift", "id": "ignored"}))["id"] == rid
    assert call(stub, "DELETE", f"/api/reservations/{rid}").effects == 1
    assert call(stub, "DELETE", f"/api/reservations/{rid}").effects == 0
    assert stub.effects_total == 3
    assert call(stub, "GET", "/unmatched") is None


def test_collection_effect_override_counts_configured_changes():
    fixture = yaml.safe_load(FIXTURE.read_text())
    next(r for r in fixture["routes"] if r["method"] == "POST" and r["path"] == "/api/reservations")["effects"] = 2
    stub = StubEngine(fixture)
    created = call(stub, "POST", "/api/reservations", {"piece_id": "p1"})
    assert created.effects == 2 and stub.effects_total == 2
    assert content(call(stub, "GET", f"/api/reservations/{content(created)['id']}"))["piece_id"] == "p1"


@pytest.mark.parametrize("mode,status,effects", [
    ("delay", 201, 1), ("fail-5xx", 503, 0), ("fail-network", 0, 0),
    ("hang", 201, 1), ("forbidden", 403, 0), ("not-found", 404, 0),
])
def test_each_injection_applies_only_contract_effect(mode, status, effects):
    stub = engine()
    stub.inject(mode, method="POST", path="/api/reservations", times=2)
    for _ in range(2):
        response = call(stub, "POST", "/api/reservations", {"piece_id": "p1"})
        assert (response.status, response.injected, response.effects) == (status, mode, effects)
        assert (response.hang_ms == 10_000) == (mode == "hang")
        assert (response.delay_ms == 400) == (mode == "delay")
    assert stub.effects_total == 2 * effects
    assert call(stub, "POST", "/api/reservations", {"piece_id": "p1"}).injected == "none"


def test_injection_queue_matches_method_and_template_before_mutation():
    stub = engine()
    created = call(stub, "POST", "/api/reservations", {"piece_id": "p1"})
    rid = content(created)["id"]
    stub.inject("fail-5xx", method="PATCH", path="/api/reservations/:id")
    stub.inject("forbidden", method="PATCH", path="/api/reservations/:id")
    path = f"/api/reservations/{rid}"
    assert [call(stub, "PATCH", path, {"piece_id": "p2"}).status for _ in range(2)] == [503, 403]
    assert content(call(stub, "GET", path))["piece_id"] == "p1"
    assert call(stub, "PATCH", path, {"piece_id": "p2"}).effects == 1
    assert content(call(stub, "GET", path))["piece_id"] == "p2"


def test_hang_commits_once_and_replay_returns_result():
    stub = engine()
    stub.inject("hang", path="/api/reservations")
    first = call(stub, "POST", "/api/reservations", {}, {"Idempotency-Key": "once"})
    again = call(stub, "POST", "/api/reservations", {}, {"Idempotency-Key": "once"})
    assert first.injected == "hang" and again.injected == "none"
    assert content(first) == content(again) and again.effects == 0 and stub.effects_total == 1


def test_variants_reset_clock_backing_and_value_variants():
    stub = engine()
    start = stub.clock.now_ms()
    assert stub.backed("countdown", 3600, now_ms=start)
    assert stub.backed("hold", 300, now_ms=start)
    assert stub.backed("stock", 3, now_ms=start)
    assert stub.backed("demand", 2, now_ms=start)
    assert stub.backed("activity", 1, now_ms=start)
    stub.clock.advance(120_000)
    assert stub.backed("countdown", 3480, now_ms=stub.clock.now_ms())
    assert not stub.backed("countdown", 3600, now_ms=stub.clock.now_ms())
    assert stub.backed("countdown", 3485, now_ms=stub.clock.now_ms(), resolution_s=5)
    assert not stub.backed("stock", 500, now_ms=start)
    stub.reset(variant="empty")
    assert content(call(stub, "GET", "/api/pieces")) == []
    stub.reset(variant="partial")
    assert len(content(call(stub, "GET", "/api/pieces"))) == 1
    assert stub.clock.now_ms() == start + 120_000 and stub.effects_total == 0
    assert stub.value(stub.values_for("email", "alternate")) == "collector@example.org"
    assert stub.value(stub.values_for("email", "empty")) == ""
    assert "potter@example.com" in stub.all_values().values()
    assert stub.account() == {"username": "v2", "password": "v3"}
    assert content(stub.standin("delivery.example.com", "GET", "/rates")) == {"available": True}


def test_auth_requires_matching_fixture_credentials_and_cookie():
    stub = engine()
    assert call(stub, "GET", "/api/account").status == 401
    assert call(stub, "POST", "/api/sign-in", {"username": "no", "password": "no"}).status == 401
    login = call(stub, "POST", "/api/sign-in", {"username": stub.value("v2"), "password": stub.value("v3")})
    assert login.status == 200
    cookie = login.headers["Set-Cookie"].split(";", 1)[0]
    assert call(stub, "GET", "/api/account", headers={"Cookie": cookie}).status == 200
    stub.reset()
    assert call(stub, "GET", "/api/account", headers={"Cookie": cookie}).status == 401
    new_login = call(stub, "POST", "/api/sign-in", {"username": stub.value("v2"), "password": stub.value("v3")})
    assert new_login.headers["Set-Cookie"] != login.headers["Set-Cookie"]
    assert call(stub, "GET", "/api/account", headers={"Cookie": cookie}).status == 401


@pytest.fixture
def running_stub():
    server = make_server(engine(), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_pinned_remote_stub_connects_to_verified_address_and_sends_original_host(monkeypatch):
    seen = []

    class StubHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            seen.append((self.headers["Host"], self.path))
            payload = b'{"now_ms": 1000}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
        pin = SourcePin("stub.test", ("127.0.0.1",), "127.0.0.1")
        remote = RemoteStub(f"http://stub.test:{server.server_port}", pin=pin)
        assert remote.clock.now_ms() == 1000
        assert seen == [(f"stub.test:{server.server_port}", "/__lapis/clock")]
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def test_pinned_https_stub_verifies_ca_name_and_sni(tmp_path, monkeypatch):
    def authority():
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test CA")])
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(datetime(2020, 1, 1, tzinfo=UTC))
                .not_valid_after(datetime(2035, 1, 1, tzinfo=UTC))
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .sign(key, hashes.SHA256()))
        return key, cert

    ca_key, ca_cert = authority()
    _, wrong_ca = authority()
    server_key = ec.generate_private_key(ec.SECP256R1())
    server_cert = (x509.CertificateBuilder()
                   .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "stub.test")]))
                   .issuer_name(ca_cert.subject).public_key(server_key.public_key())
                   .serial_number(x509.random_serial_number())
                   .not_valid_before(datetime(2020, 1, 1, tzinfo=UTC))
                   .not_valid_after(datetime(2035, 1, 1, tzinfo=UTC))
                   .add_extension(x509.SubjectAlternativeName([
                       x509.DNSName("stub.test"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                       critical=False)
                   .sign(ca_key, hashes.SHA256()))
    cert_file = tmp_path / "server.pem"
    key_file = tmp_path / "server.key"
    cert_file.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(server_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))

    sni = []
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert_file, key_file)
    server_context.set_servername_callback(lambda _socket, name, _context: sni.append(name))
    server = make_server(engine(), port=0)
    server.socket = server_context.wrap_socket(server.socket, server_side=True)
    server.handle_error = lambda *_: None  # The expected rejected handshakes are not server failures.
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with socket.socket() as unavailable_proxy:
            unavailable_proxy.bind(("127.0.0.1", 0))
            monkeypatch.setenv("HTTPS_PROXY", f"http://127.0.0.1:{unavailable_proxy.getsockname()[1]}")
            monkeypatch.setenv("NO_PROXY", "")
            trusted = ssl.create_default_context(cadata=ca_cert.public_bytes(serialization.Encoding.PEM).decode())
            direct = RemoteStub(f"https://127.0.0.1:{server.server_port}", ssl_context=trusted)
            assert direct.clock.now_ms() == engine().clock.now_ms()
        pin = SourcePin("stub.test", ("127.0.0.1",), "127.0.0.1")
        url = f"https://stub.test:{server.server_port}"
        assert sni == [None]
        remote = RemoteStub(url, pin=pin, ssl_context=trusted)
        assert remote.clock.now_ms() == engine().clock.now_ms()
        assert sni == [None, "stub.test"]
        ca_file = tmp_path / "ca.pem"
        ca_file.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
        monkeypatch.setenv("SSL_CERT_FILE", str(ca_file))
        assert RemoteStub(url, pin=pin).clock.now_ms() == engine().clock.now_ms()

        untrusted = ssl.create_default_context(cadata=wrong_ca.public_bytes(serialization.Encoding.PEM).decode())
        with pytest.raises(ssl.SSLCertVerificationError):
            RemoteStub(url, pin=pin, ssl_context=untrusted).clock.now_ms()
        wrong_name = SourcePin("other.test", ("127.0.0.1",), "127.0.0.1")
        with pytest.raises(ssl.SSLCertVerificationError):
            RemoteStub(url, pin=wrong_name, ssl_context=trusted).clock.now_ms()
        assert sni == [None, "stub.test", "stub.test", "stub.test", "other.test"]
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def test_every_remote_control_bypasses_environment_proxies(running_stub, monkeypatch):
    with socket.socket() as unavailable_proxy:
        unavailable_proxy.bind(("127.0.0.1", 0))
        proxy = f"http://127.0.0.1:{unavailable_proxy.getsockname()[1]}"
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            monkeypatch.setenv(name, proxy)
        for name in ("NO_PROXY", "no_proxy"):
            monkeypatch.setenv(name, "")

        remote = RemoteStub(running_stub)
        start = remote.clock.now_ms()
        remote.clock.advance(20)
        assert remote.clock.now_ms() == start + 20
        remote.inject("not-found", method="POST", path="/api/reservations")
        remote.clear_injections()
        remote.reset(variant="empty")
        assert remote.effects_total == 0
        assert remote.all_values()
        value_id = remote.values_for("email", "alternate")
        assert remote.value(value_id) == "collector@example.org"
        assert isinstance(remote.backed("hold", 295, now_ms=remote.clock.now_ms()), bool)
        assert remote.account()["username"] == "v2"


def test_http_server_and_remote_control_end_to_end(running_stub):
    remote = RemoteStub(running_stub)
    start = remote.clock.now_ms()
    remote.clock.advance(5000)
    assert remote.clock.now_ms() == start + 5000
    assert remote.backed("hold", 295, now_ms=remote.clock.now_ms())
    assert remote.value(remote.values_for("email", "alternate")) == "collector@example.org"
    assert remote.account()["username"] == "v2"
    with urlopen(running_stub + "/api/pieces") as response:
        assert len(json.load(response)) == 2
    remote.inject("not-found", method="POST", path="/api/reservations")
    request = Request(running_stub + "/api/reservations", data=b'{}', method="POST")
    with pytest.raises(HTTPError) as err:
        urlopen(request)
    assert err.value.code == 404 and remote.effects_total == 0
    # A connection failure must arrive before this deliberately absent request body.
    remote.inject("fail-network", method="POST", path="/api/reservations")
    for _ in range(2):
        with socket.create_connection(("127.0.0.1", int(running_stub.rpartition(":")[2])), timeout=1) as connection:
            connection.sendall(b"POST /api/reservations HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                               b"Idempotency-Key: lost\r\nContent-Length: 100\r\n\r\n")
            assert connection.recv(1) == b""
    assert remote.effects_total == 0
    remote.clear_injections()
    with urlopen(request) as response:
        assert json.load(response)["id"]
    assert remote.effects_total == 1
    remote.reset(variant="empty")
    assert remote.effects_total == 0
    with urlopen(running_stub + "/api/pieces") as response:
        assert json.load(response) == []
    with pytest.raises(HTTPError) as err:
        urlopen(running_stub + "/missing")
    assert err.value.code == 404


def test_http_hang_closes_only_when_the_remote_clock_passes_its_deadline(running_stub):
    remote = RemoteStub(running_stub)
    remote.inject("hang", method="POST", path="/api/reservations")
    outcome = []

    def post():
        try:
            urlopen(Request(running_stub + "/api/reservations", data=b'{}', method="POST"), timeout=30)
            outcome.append("answered")
        except Exception:
            outcome.append("closed")

    client = threading.Thread(target=post, daemon=True)
    client.start()
    deadline = time.monotonic() + 5
    while remote.effects_total == 0 and time.monotonic() < deadline:
        time.sleep(.02)
    assert remote.effects_total == 1                     # the effect applies before any answer
    remote.clock.advance(9_999)
    client.join(.3)
    assert client.is_alive() and not outcome            # real time and 9.999 s never close it
    remote.clock.advance(1)
    client.join(5)
    assert outcome == ["closed"]


def test_public_bind_is_refused():
    with pytest.raises(ValueError, match="loopback or private"):
        make_server(engine(), host="0.0.0.0", port=0)


@pytest.fixture
def tiny_page():
    class PageHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            content = b'<html><body><div id="pieces"></div><script>fetch("/api/pieces").then(r=>r.json()).then(xs=>document.querySelector("#pieces").textContent=xs[0].name)</script></body></html>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(content)

    server = ThreadingHTTPServer(("127.0.0.1", 0), PageHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_playwright_adapter_fulfills_page_fetch(browser, tiny_page):
    stub = engine()
    page = browser.new_page()
    results = []

    def route_request(route, request):
        result = respond(route, request, stub, now_ms=stub.clock.now_ms())
        if result is None:
            route.continue_()
        else:
            results.append(result)

    try:
        page.route("**/api/**", route_request)
        page.goto(tiny_page)
        assert page.locator("#pieces").inner_text() == "Celadon cup"
        assert [(r.status, r.injected, r.effects) for r in results] == [(200, "none", 0)]
    finally:
        page.close()


def test_playwright_hang_closes_on_the_controlled_clock_without_blocking_other_fetches(browser, tiny_page):
    stub = engine()
    stub.inject("hang", method="POST", path="/api/reservations")
    page = browser.new_page()
    results = []

    def route_request(route, request):
        result = respond(route, request, stub, now_ms=stub.clock.now_ms())
        if result is None:
            route.continue_()
        else:
            results.append(result)

    try:
        page.route("**/api/**", route_request)
        page.goto(tiny_page)
        other = page.evaluate("""async () => {
            window.__hang = 'pending';
            fetch('/api/reservations', {method: 'POST', body: '{}'})
                .then(() => { window.__hang = 'unexpected response'; }, () => { window.__hang = 'connection closed'; });
            return fetch('/api/pieces').then(r => r.json()).then(xs => xs[0].name);
        }""")
        assert other == "Celadon cup"
        page.wait_for_timeout(200)
        assert page.evaluate("window.__hang") == "pending"   # real time alone never closes it
        stub.clock.advance(9_999)
        page.wait_for_timeout(100)
        assert page.evaluate("window.__hang") == "pending"
        stub.clock.advance(1)
        page.wait_for_function("window.__hang !== 'pending'", timeout=2000)
        assert page.evaluate("window.__hang") == "connection closed"
        assert stub.effects_total == 1
        assert any(r.injected == "hang" and r.status == 0 and r.effects == 1 for r in results)
    finally:
        page.close()
