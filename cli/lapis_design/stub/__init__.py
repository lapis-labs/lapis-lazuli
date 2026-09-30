"""Run an isolated synthetic API server from a project fixture."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jsonschema.exceptions import ValidationError

from .engine import SessionClock, StubEngine, StubResponse
from .remote import RemoteStub
from .server import make_server


def main(argv: list[str] | None = None, prog: str = "lapis-design stub serve") -> int:
    parser = argparse.ArgumentParser(prog=prog, description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--variant")
    args = parser.parse_args(argv)
    try:
        engine = StubEngine.load(args.fixture, variant=args.variant)
        server = make_server(engine, host=args.host, port=args.port)
    except (OSError, ValueError, KeyError, ValidationError) as exc:
        print(f"stub serve: {exc}", file=sys.stderr)
        return 2
    print(f"Stub serving at http://{server.server_address[0]}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
