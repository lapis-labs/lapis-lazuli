"""Serve a local HTML file's folder on loopback, so a check runs against an address that is ours.

`behavior check` and `render check` take a page as an http(s) URL, a `file://` URL, or the path of an
HTML file. A file URL has no host, so a behavior session cannot record it as `source.url`
(behavior/DERIVED.md, Scope and safety), and a page that links `/app.css`, loads modules, or fetches
JSON does not behave from `file:` as it does when served. For a file, the checks serve its folder on
127.0.0.1 for the length of the run and start from `http://127.0.0.1:<port>/<file>`; any other target
passes through untouched.

The server answers GET and HEAD only, and only for what lies under the folder: a path whose real
location (links followed) is outside it, a name that starts with a dot (`.env`, `.git`, `.lapis`),
and a folder without an index file (there is no listing) are all 404.
"""
from __future__ import annotations

import contextlib
import mimetypes
import os
import re
import shutil
import sys
import threading
from collections.abc import Iterator
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from urllib.request import url2pathname

INDEX_FILES = ("index.html", "index.htm")


class NotServable(ValueError):
    """The target names a local file the checks cannot serve."""


def _segments(url_path: str) -> list[str]:
    return [segment for segment in re.split(r"[\\/]", url_path) if segment]


class _Server(ThreadingHTTPServer):
    def __init__(self, root: Path):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.root = root

    def locate(self, url_path: str) -> Path | None:
        """The real path a request path names, or None when nothing is served there: the path does
        not resolve, resolves outside the root once links are followed, or has a dotted name below it."""
        try:
            real = self.root.joinpath(*_segments(url_path)).resolve()
        except (OSError, ValueError, RuntimeError):     # a NUL byte, a link loop
            return None
        if not real.is_relative_to(self.root) or any(part.startswith(".") for part in real.relative_to(self.root).parts):
            return None
        return real

    def handle_error(self, request, client_address) -> None:
        if not isinstance(sys.exception(), ConnectionError):       # a page that navigates away drops its requests
            super().handle_error(request, client_address)


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    server_version = "lapis-local-site"

    def log_message(self, *_) -> None:
        pass

    def do_GET(self) -> None:
        self._answer(body=True)

    def do_HEAD(self) -> None:
        self._answer(body=False)

    def _answer(self, *, body: bool) -> None:
        request = urlsplit(self.path)
        path = unquote(request.path)
        found = self.server.locate(path)
        if found is not None and found.is_dir():
            if not path.endswith("/"):           # relative links in its index resolve against the folder
                self.send_response(HTTPStatus.MOVED_PERMANENTLY)
                self.send_header("Location", urlunsplit(("", "", quote("/" + "/".join(_segments(path)) + "/"),
                                                         request.query, "")))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            found = next((hit for name in INDEX_FILES
                          if (hit := self.server.locate(path + name)) is not None and hit.is_file()), None)
        try:
            handle = found.open("rb") if found is not None and found.is_file() else None
        except OSError:
            handle = None
        if handle is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        with handle:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mimetypes.guess_type(found.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(os.fstat(handle.fileno()).st_size))
            self.end_headers()
            if body:
                shutil.copyfileobj(handle, self.wfile)


def _file_target(target: str) -> tuple[Path, str, str, str] | None:
    """(folder, file name, query, fragment) when `target` is a `file:` URL or a path to a file; None for
    any other URL. Raises NotServable for a file that cannot be served."""
    parts = urlsplit(target)
    if parts.scheme == "file":
        if parts.netloc not in ("", "localhost"):
            raise NotServable(f"file URL names the host {parts.netloc!r}; name a file on this computer")
        file, query, fragment = Path(url2pathname(parts.path)), parts.query, parts.fragment
    elif "://" not in target and (Path(target).exists() or target.lower().endswith((".html", ".htm"))):
        file, query, fragment = Path(target), "", ""
    else:
        return None
    file = file.absolute()
    if file.is_dir():
        raise NotServable(f"{file} is a folder; name the HTML file in it")
    if not file.is_file():
        raise NotServable(f"no such file: {file}")
    if file.name.startswith("."):
        raise NotServable(f"{file} starts with a dot; files like that are never served")
    root = file.parent.resolve()
    if not (root / file.name).resolve().is_relative_to(root):
        raise NotServable(f"{file} is a link to a file outside its folder")
    return root, file.name, query, fragment


@contextlib.contextmanager
def serve(target: str) -> Iterator[str]:
    """The address to run a check against: `target` itself unless it names a local file, in which case
    the file's folder is served read-only on 127.0.0.1 until the block ends, however it ends."""
    found = _file_target(target)
    if found is None:
        yield target
        return
    root, name, query, fragment = found
    server = _Server(root)
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                              name="lapis-local-site", daemon=True)
    worker.start()
    try:
        yield urlunsplit(("http", f"127.0.0.1:{server.server_port}", "/" + quote(name), query, fragment))
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
