"""render check target hosts (render/DERIVED.md, Capture, **Target hosts.**).

The CLI runs in a subprocess whose Chromium resolves every host name to a loopback test server, so a
fake public host (and any registry host a regression let through) never leaves this computer. The
server's request log shows whether a refused host was ever requested.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import ssl
import sys
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
import pytest
import yaml

from lapis_design.render.hosts import HostPolicy, WrongScheme, plan_path
from lapis_design import ours
from lapis_design.render.extract import validate

from lazuli.sources import load_registry

# Replaces the render module's sync_playwright so its Chromium maps every host name to the test server.
_MAPPED_MAIN = """
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import lapis_design.render as render

rules, argv = sys.argv[1], sys.argv[2:]
real = render.sync_playwright


@contextmanager
def mapped():
    with real() as playwright:
        launch = playwright.chromium.launch
        def launch_with_rules(**options):
            import lapis_design.ours as ours
            options["args"] = ours.chromium_args([], [*options.pop("args", []), rules])
            return launch(**options)
        yield SimpleNamespace(chromium=SimpleNamespace(launch=launch_with_rules))


if "--fake-test-resolver" in argv:
    import lapis_design.ours as ours
    ours.resolve_addresses = lambda host: ["127.0.0.1"]
    argv.remove("--fake-test-resolver")
if "--test-spki" in argv:
    import lapis_design.ours as ours
    index = argv.index("--test-spki")
    spki_hash = argv.pop(index + 1)
    argv.pop(index)
    render.launch_args = lambda pins: ours.chromium_args(
        pins, [f"--ignore-certificate-errors-spki-list={spki_hash}"])
render.sync_playwright = mapped
sys.exit(render.main(argv))
"""

_PAGE = b"""<!doctype html><html lang="en"><head><title>Ours</title></head>
<body><main><h1>Our page</h1><p>Rendered by the test server.</p></main></body></html>"""


class _Site(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        self.server.log.append((host, self.path))
        redirects = {"/hop": "http://ours.invalid/to-registry", "/to-registry": "http://noonnu.cc/",
                     "/to-reference": "http://www.ref-site.invalid/archive/", "/to-public": "http://ours.invalid/",
                     "/to-other-test": "http://www.app.test/"}
        if location := redirects.get(self.path):
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = _PAGE
        if self.path == "/navigates":
            body = _PAGE.replace(b"</body>", b"<script>setTimeout(() => { location.href = 'http://noonnu.cc/'; }, 50)"
                                 b"</script></body>")
        if self.path == "/popups":
            body = b"""<!doctype html><html lang="en"><body><main><h1>Main capture OK</h1>
<p id="popup-state">Popups pending</p><a id="open" target="_blank" href="http://refused.invalid/">Open</a>
<script>
window.__opened = window.open('http://refused.invalid/', '_blank');
document.querySelector('#open').click();
setTimeout(() => {
  document.querySelector('#popup-state').textContent =
    window.__opened?.closed ? 'Popup closed' : 'Popup remained open';
}, 400);
</script></main></body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    server.log = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

@pytest.fixture
def https_site(tmp_path: Path):
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test CA")])
    ca_cert = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
               .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
               .not_valid_before(datetime(2020, 1, 1, tzinfo=UTC))
               .not_valid_after(datetime(2035, 1, 1, tzinfo=UTC))
               .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
               .sign(ca_key, hashes.SHA256()))
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "app.test")]))
            .issuer_name(ca_cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime(2020, 1, 1, tzinfo=UTC))
            .not_valid_after(datetime(2035, 1, 1, tzinfo=UTC))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("app.test")]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    cert_path, key_path = tmp_path / "server.pem", tmp_path / "server.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    spki = cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    spki_hash = base64.b64encode(hashlib.sha256(spki).digest()).decode("ascii")

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    server.log = []
    server.sni = []
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    context.set_servername_callback(lambda _socket, name, _context: server.sni.append(name))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, spki_hash
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _render_check(site, cwd: Path, *argv: str) -> subprocess.CompletedProcess:
    rules = f"--host-resolver-rules=MAP * 127.0.0.1:{site.server_port}, EXCLUDE localhost"
    env = {**os.environ, "LAPIS_SIG_KEY_FILE": str(cwd / "sig.key")}
    return subprocess.run([sys.executable, "-c", _MAPPED_MAIN, rules, *argv, "--width", "320",
                           "--out", str(cwd / "out.json")],
                          cwd=cwd, env=env, capture_output=True, text=True, timeout=120)


def _hosts(site) -> set[str]:
    return {host for host, _ in site.log}


def test_extract_lint_and_render_import_leave_playwright_unloaded() -> None:
    code = """import sys
from pathlib import Path
import lapis_design.render
assert not any(name.startswith('playwright') for name in sys.modules)
from lapis_design.lint.cli import run
run(extract=Path('src/shared/render/example.extract.json'))
assert not any(name.startswith('playwright') for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def _write_plan(path: Path, *sources: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"references": [
        {"source": source, "kind": "site", "rights": "reference-only", "mode": "study",
         "take": ["row rhythm"], "leave": ["copy"]} for source in sources]}), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------------- the policy itself


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000/", "http://localhost:3000/a", "http://app.localhost/",
                                 "http://10.0.0.5/", "http://192.168.1.20:8080/", "http://172.16.4.1/",
                                 "http://[::1]:8000/"])
def test_loopback_and_private_addresses_need_no_flag(url: str) -> None:
    assert HostPolicy(public=False, plan=None).refusal(url) is None


ONE_LINE = ("render check takes an http or https URL; serve the folder on loopback, for example "
            "`python3 -m http.server 8000 --bind 127.0.0.1`, and check `http://127.0.0.1:8000/`")


@pytest.mark.parametrize("url", ["data:text/html,<p>x</p>", "about:blank", "ftp://127.0.0.1/page.html",
                                 "localhost:3000", "127.0.0.1:8000/a"])
def test_only_http_and_https_pages_are_captured_whatever_the_host(url: str) -> None:
    # A local HTML file (path or file:// URL) never reaches the policy: local_site serves its folder first.
    for policy in (HostPolicy(public=False, plan=None), HostPolicy(public=True, plan=None)):
        assert policy.refusal(url) == ONE_LINE
        with pytest.raises(WrongScheme) as refused:
            policy.check(url)
        assert str(refused.value) == ONE_LINE                    # no `lazuli ref capture` advice: there is no host


def test_public_host_needs_the_public_flag() -> None:
    assert "--public" in HostPolicy(public=False, plan=None).refusal("https://ours.invalid/")
    assert HostPolicy(public=True, plan=None).refusal("https://ours.invalid/") is None

def test_public_registry_alias_uses_idna_and_invalid_reference_host_is_skipped() -> None:
    policy = HostPolicy(public=True, plan={"references": [
        {"source": "https://" + "x" * 64 + ".invalid/"},
        {"source": "https://valid.invalid/"}]},
        registry=[{"id": "closed", "url": "https://localhost.example/", "access": "refused"}])
    assert "source registry" in policy.refusal("https://lºcalhost.example/")
    assert "references[1]" in policy.refusal("https://valid.invalid/")
    assert "references[0]" not in (policy.refusal("https://else.invalid/") or "")
    assert "IDNA" in policy.refusal("https://" + "x" * 64 + ".invalid/")

def test_test_source_is_pinned_only_when_every_address_is_private(monkeypatch) -> None:
    monkeypatch.setattr(ours, "resolve_addresses", lambda host: ["127.0.0.1", "10.0.0.1"])
    monkeypatch.setattr(ours.socket, "create_connection", lambda address, timeout: type("Connection", (), {"close": lambda self: None})())
    pin = ours.pin_source("http://app.test:8080/")
    assert pin is not None and pin.address == "127.0.0.1"
    assert list(pin.addresses) == ["127.0.0.1", "10.0.0.1"]
    assert HostPolicy(public=False, plan=None, pins=[pin]).refusal("http://app.test:8080/") is None
    assert "--public" in HostPolicy(public=False, plan=None, pins=[pin]).refusal("http://www.app.test/")
    assert "--public" in HostPolicy(public=False, plan=None, pins=[pin]).refusal("http://other.test/")
    args = ours.chromium_args([pin], ["--host-resolver-rules=MAP * 127.0.0.1:8080, EXCLUDE localhost"])
    assert len([arg for arg in args if arg.startswith("--host-resolver-rules=")]) == 1
    assert "MAP app.test 127.0.0.1" in args[0]
    assert "MAP * 127.0.0.1:8080" in args[0]
    assert "--proxy-bypass-list=app.test" in args
    ipv6 = ours.SourcePin("v6.test", ("::1",), "::1")
    assert "MAP v6.test [::1]" in ours.chromium_args([ipv6])[0]


def test_pin_uses_first_address_accepting_tcp_and_does_not_resolve_other_names(monkeypatch) -> None:
    looked_up, connected = [], []
    def resolver(host):
        looked_up.append(host)
        return ["127.0.0.2", "127.0.0.1"]
    def connect(address, timeout):
        connected.append(address)
        if address[0] == "127.0.0.2":
            raise ConnectionRefusedError()
        return type("Connection", (), {"close": lambda self: None})()
    monkeypatch.setattr(ours, "resolve_addresses", resolver)
    monkeypatch.setattr(ours.socket, "create_connection", connect)
    pin = ours.pin_source("http://app.test:1234/")
    assert pin is not None and pin.address == "127.0.0.1"
    assert looked_up == ["app.test"] and connected == [("127.0.0.2", 1234), ("127.0.0.1", 1234)]
    assert HostPolicy(public=False, plan=None, pins=[pin]).refusal("http://app.test./") is None
    assert HostPolicy(public=False, plan=None, pins=[pin]).refusal("http://www.app.test/") is not None



def test_two_start_urls_on_same_test_host_reuse_dns_and_address(monkeypatch) -> None:
    looked_up = []
    monkeypatch.setattr(ours, "resolve_addresses", lambda host: looked_up.append(host) or ["127.0.0.1"])
    monkeypatch.setattr(ours.socket, "create_connection",
                        lambda address, timeout: type("Connection", (), {"close": lambda self: None})())
    source = ours.pin_source("http://app.test:8000/")
    stub = ours.pin_source("http://app.test:9000/", resolved=list(source.addresses),
                           pinned_address=source.address)
    assert source.address == stub.address == "127.0.0.1" and looked_up == ["app.test"]


@pytest.mark.parametrize("addresses", [[], ["8.8.8.8"], ["127.0.0.1", "8.8.8.8"]])
def test_public_or_unresolved_test_source_never_belongs_to_us(monkeypatch, addresses) -> None:
    monkeypatch.setattr(ours, "resolve_addresses", lambda host: addresses)
    assert ours.pin_source("http://app.test:8080/") is None
    assert "--public" in HostPolicy(public=False, plan=None).refusal("http://app.test:8080/")
    for host in ("app.local", "app.internal"):
        assert "--public" in HostPolicy(public=False, plan=None).refusal(f"http://{host}/")


def test_failed_test_dns_resolution_is_public_without_a_connection(monkeypatch) -> None:
    import socket
    def unresolved(host):
        raise socket.gaierror("name not found")
    monkeypatch.setattr(ours, "resolve_addresses", unresolved)
    monkeypatch.setattr(ours.socket, "create_connection",
                        lambda *args, **kwargs: pytest.fail("must not connect on DNS failure"))
    assert ours.pin_source("http://app.test:1234/") is None


def test_own_render_requires_addresses_exactly_for_pinned_test_sources() -> None:
    from lapis_design.render.extract import assemble
    document = assemble("http://app.test/", None, [], b"x" * 32, dark_theme=False)
    assert validate(document)
    document["source"]["addresses"] = ["127.0.0.1"]
    assert not validate(document)
    document["source"]["url"] = "http://127.0.0.1/"
    assert validate(document)

def test_reference_test_hosts_are_never_pinned_or_given_source_addresses() -> None:
    from lapis_design.render.extract import assemble
    document = assemble("https://ref.test/work", None, [], b"x" * 32, dark_theme=False)
    document["source"]["kind"] = "site"
    document["reference"] = {"rights": "own"}
    assert not validate(document)
    document["source"]["addresses"] = ["127.0.0.1"]
    assert validate(document)


def test_every_registry_host_is_refused_whatever_its_access() -> None:
    policy = HostPolicy(public=True, plan=None)
    registry = load_registry()
    assert {entry["access"] for entry in registry} >= {"adapter", "read", "browser-link", "refused"}
    for entry in registry:
        for url in [entry["url"], *(f"https://{host}/" for host in entry.get("hosts", ()))]:
            assert "source registry" in (policy.refusal(url) or ""), url
    # a registry entry owns its whole host, not only the page it links
    assert "source registry" in policy.refusal("https://github.com/someone/else")
    assert "source registry" in policy.refusal("http://WWW.noonnu.cc./fonts")


def test_plan_reference_hosts_are_refused() -> None:
    plan = {"references": [{"source": "https://www.ref-site.invalid/archive"}, {"source": "bare-host.invalid/gallery"},
                           {"source": "Material Design 3"}, {"source": "images/hero.png"}]}
    policy = HostPolicy(public=True, plan=plan)
    assert "references[0]" in policy.refusal("http://ref-site.invalid/other")
    assert "references[1]" in policy.refusal("https://bare-host.invalid/")
    assert policy.refusal("https://ours.invalid/") is None
    # a local address stays ours even when a reference names it
    assert HostPolicy(public=False, plan={"references": [{"source": "http://127.0.0.1:3000/"}]}).refusal(
        "http://127.0.0.1:3000/") is None


def test_plan_path_prefers_plan_then_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    found = _write_plan(Path(".lapis/plans/demo.yaml"), "https://ref-site.invalid/")
    assert plan_path(None, "demo") == found
    assert plan_path(tmp_path / "other.yaml", "demo") == tmp_path / "other.yaml"
    assert plan_path(None, "missing") is None
    assert plan_path(None, "../demo") is None


# ------------------------------------------------------------------------------------- render check


def test_registry_host_is_refused_before_any_request(site, tmp_path: Path) -> None:
    for url in ("http://noonnu.cc/", "http://fonts.google.com/specimen/X", "http://www.morisawa.co.jp/"):
        result = _render_check(site, tmp_path, url, "--public")
        assert result.returncode == 2, result.stderr
        assert "source registry" in result.stderr and "lazuli ref capture" in result.stderr
    assert site.log == []
    assert not (tmp_path / "out.json").exists()


def test_reference_host_is_refused(site, tmp_path: Path) -> None:
    plan = _write_plan(tmp_path / "plan.yaml", "https://www.ref-site.invalid/archive")
    result = _render_check(site, tmp_path, "http://ref-site.invalid/", "--public", "--plan", str(plan))
    assert result.returncode == 2
    assert "references[0]" in result.stderr and "lazuli ref capture" in result.stderr
    assert site.log == []


def test_task_finds_the_plan(site, tmp_path: Path) -> None:
    _write_plan(tmp_path / ".lapis" / "plans" / "demo.yaml", "https://ref-site.invalid/")
    result = _render_check(site, tmp_path, "http://ref-site.invalid/", "--public", "--task", "demo")
    assert result.returncode == 2
    assert "references[0]" in result.stderr and "lazuli ref capture" in result.stderr
    assert site.log == []


def test_missing_plan_is_an_error(site, tmp_path: Path) -> None:
    result = _render_check(site, tmp_path, "http://ours.invalid/", "--public", "--plan", str(tmp_path / "no.yaml"))
    assert result.returncode == 2
    assert result.stderr.startswith("render check:") and "no.yaml" in result.stderr
    assert site.log == []


def test_public_host_without_flag_is_refused(site, tmp_path: Path) -> None:
    result = _render_check(site, tmp_path, "http://ours.invalid/")
    assert result.returncode == 2
    assert "--public" in result.stderr and "lazuli ref capture" in result.stderr
    assert site.log == []


@pytest.mark.browser
def test_public_flag_captures_our_public_host(site, tmp_path: Path) -> None:
    result = _render_check(site, tmp_path, "http://ours.invalid/", "--public", "--task", "demo")
    assert result.returncode == 0, result.stderr
    document = json.loads((tmp_path / "out.json").read_text())
    assert document["source"]["url"] == "http://ours.invalid/"
    assert any(run["text"] == "Our page" for run in document["viewports"][0]["text"])
    assert _hosts(site) == {"ours.invalid"}

@pytest.mark.browser
@pytest.mark.parametrize("hostname", ["app.test", "APP.TEST", "app.test."])
def test_verified_test_source_captures_without_public_and_records_resolved_addresses(
        site, tmp_path: Path, hostname: str) -> None:
    result = _render_check(site, tmp_path, f"http://{hostname}:{site.server_port}/", "--fake-test-resolver")
    assert result.returncode == 0, result.stderr
    document = json.loads((tmp_path / "out.json").read_text())
    assert document["source"]["addresses"] == ["127.0.0.1"]
    assert _hosts(site) == {"app.test"}


def test_default_render_launch_args_do_not_bypass_certificate_checks() -> None:
    import lapis_design.render as render

    assert not any(arg.startswith(("--ignore-certificate-errors", "--allow-insecure-localhost"))
                   for arg in render.launch_args([]))


@pytest.mark.browser
def test_pinned_https_test_source_captures_with_test_only_spki_exception(
        https_site, tmp_path: Path) -> None:
    server, spki_hash = https_site
    url = f"https://app.test:{server.server_port}/"
    result = _render_check(server, tmp_path, url, "--fake-test-resolver", "--test-spki", spki_hash)
    assert result.returncode == 0, result.stderr
    document = json.loads((tmp_path / "out.json").read_text())
    assert document["source"]["url"] == url
    assert document["source"]["addresses"] == ["127.0.0.1"]
    assert any(run["text"] == "Our page" for run in document["viewports"][0]["text"])
    assert _hosts(server) == {"app.test"}
    assert server.sni and set(server.sni) == {"app.test"}


@pytest.mark.browser
def test_page_opened_popups_are_refused_before_request_and_do_not_end_capture(site, tmp_path: Path) -> None:
    result = _render_check(site, tmp_path, f"http://127.0.0.1:{site.server_port}/popups")
    assert result.returncode == 0, result.stderr
    assert "refused.invalid" not in _hosts(site)
    assert result.stderr.count("refused http://refused.invalid/") >= 2
    document = json.loads((tmp_path / "out.json").read_text())
    texts = [run["text"] for run in document["viewports"][0]["text"]]
    assert "Main capture OK" in texts and "Popup closed" in texts


@pytest.mark.browser
def test_redirect_from_pinned_test_source_to_another_test_name_is_refused(site, tmp_path: Path) -> None:
    result = _render_check(site, tmp_path, f"http://app.test:{site.server_port}/to-other-test",
                           "--fake-test-resolver")
    assert result.returncode == 2
    assert "refused http://www.app.test/" in result.stderr
    assert "www.app.test" not in _hosts(site)
    assert not (tmp_path / "out.json").exists()


@pytest.mark.browser
@pytest.mark.parametrize(("path", "plan", "flags", "refused"), [
    ("http://ours.invalid/hop", None, ["--public", "--width", "390"], "noonnu.cc"),
    ("http://ours.invalid/to-reference", "https://ref-site.invalid/", ["--public"], "www.ref-site.invalid"),
    ("http://ours.invalid/navigates", None, ["--public"], "noonnu.cc"),
    ("http://127.0.0.1:{port}/to-public", None, [], "ours.invalid"),
])
def test_redirect_into_a_refused_host_is_refused(site, tmp_path: Path, path: str, plan: str | None,
                                                 flags: list[str], refused: str) -> None:
    if plan:
        flags = [*flags, "--plan", str(_write_plan(tmp_path / "plan.yaml", plan))]
    result = _render_check(site, tmp_path, path.format(port=site.server_port), *flags)
    assert result.returncode == 2, result.stderr
    assert f"refused http://{refused}/" in result.stderr and "lazuli ref capture" in result.stderr
    assert refused not in _hosts(site)                  # blocked before the request left the browser
    assert site.log                                     # the page we may capture was requested
    assert not (tmp_path / "out.json").exists()
