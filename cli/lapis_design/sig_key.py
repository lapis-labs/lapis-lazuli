"""A persistent per-user 32-byte signature key kept outside project directories."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def key_path() -> Path:
    if path := os.environ.get("LAPIS_SIG_KEY_FILE"):
        return Path(path).expanduser()
    from lazuli.paths import cache_dir

    return cache_dir() / "sig.key"


def load_key() -> bytes:
    path = key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        fd, temporary = tempfile.mkstemp(prefix=".sig-", dir=path.parent)
        temp_path = Path(temporary)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(os.urandom(32))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temp_path, path)
            except FileExistsError:
                pass
        finally:
            temp_path.unlink(missing_ok=True)
    key = path.read_bytes()
    if len(key) != 32:
        raise ValueError(f"signature key at {path} must be 32 bytes")
    return key
