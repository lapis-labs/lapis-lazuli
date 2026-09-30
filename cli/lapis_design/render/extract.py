"""Assemble render extracts and reject schema-invalid documents before writing."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import jsonschema
import yaml

from lapis_design import __version__, shared_dir
from lapis_design.text_sig import key_id


def assemble(url: str, task: str | None, viewports: list[dict], key: bytes, *, dark_theme: bool) -> dict:
    parsed = urlsplit(url)
    document = {
        "version": 1,
        "meta": {"extractor": {"name": "render_check", "version": __version__},
                 "generated_at": datetime.now(timezone.utc).isoformat(), "sig_key_id": key_id(key),
                 "dark_theme": dark_theme},
        "source": {"kind": "render", "url": urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))},
        "viewports": viewports,
    }
    if task is not None:
        document["source"]["task"] = task
    return document


def validate(document: dict) -> list[str]:
    schema = yaml.safe_load((shared_dir() / "render" / "extract.schema.yaml").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    return [f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
            for error in sorted(validator.iter_errors(document), key=lambda e: list(map(str, e.absolute_path)))[:5]]


def write_extract(document: dict, path: Path) -> list[str]:
    problems = validate(document)
    if problems:
        return problems
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return []
