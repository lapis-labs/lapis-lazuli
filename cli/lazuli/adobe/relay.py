"""One relay call: Codex is asked to call exactly one Adobe Fonts connector tool, and the event stream proves it.

lazuli never reads what the model says back. The prompt names one tool and its exact arguments, and the
answer is a fixed `{"done": true}`; the result is read from the `mcp_tool_call` item of Codex's `--json`
event stream. A stream that shows anything else (another connector call, a second call of the same tool, a
command, a file change, a web search, a different server, tool, or arguments) is refused and nothing from it
is kept or reported as a result. For a read tool that costs nothing; for an action, the message says what the
stream showed, since the call may already have happened.

Codex runs with the user config ignored (so a `notify` hook or a wide sandbox of the owner's does not
apply), a read-only sandbox, no session file, and an empty folder as its working root.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from lazuli.adobe import clean

SERVER = "codex_apps"
READ_TOOLS = ("search", "similar", "details", "styles", "preview")
ACTION_TOOLS = ("activate", "create_kit")
TOOLS = READ_TOOLS + ACTION_TOOLS
TIMEOUT_S = 240.0
EFFORT = "low"
# item types of a stream that carry no action of their own
HARMLESS_ITEMS = frozenset({"agent_message", "reasoning", "error", "todo_list"})
ANSWER_SCHEMA = {"type": "object", "properties": {"done": {"type": "boolean"}}, "required": ["done"],
                 "additionalProperties": False}


class RelayError(Exception):
    """A call that gave no result; the message says why."""


class Refused(RelayError):
    """The stream did not show exactly the call that was asked for; the message says what it showed."""


@dataclass(frozen=True)
class Completed:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class Outcome:
    tool: str
    arguments: dict
    payload: dict            # the connector's own JSON, before cleaning
    usage: dict | None
    seconds: float
    model: str


Runner = Callable[[Sequence[str], str, float], Completed]


def tool_name(tool: str) -> str:
    return f"adobe.font_{tool}"


def codex_binary() -> str | None:
    """`$LAZULI_CODEX` when set, else the `codex` on PATH."""
    return os.environ.get("LAZULI_CODEX") or shutil.which("codex")


def prompt_for(tool: str, arguments: dict) -> str:
    return (f"Call exactly one tool, mcp__{SERVER}__adobe_font_{tool}, with exactly these JSON arguments: "
            f"{json.dumps(arguments, ensure_ascii=False)}. Call no other tool and run no shell command. "
            'After that single call returns, reply {"done":true} and nothing else.')


def argv_for(codex: str, model: str, schema: Path, prompt: str) -> list[str]:
    return [codex, "exec", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules",
            "--sandbox", "read-only", "-m", model, "-c", f"model_reasoning_effort={EFFORT}", "--json",
            "--output-schema", str(schema), prompt]


def run_codex(argv: Sequence[str], cwd: str, timeout: float) -> Completed:
    try:
        done = subprocess.run(list(argv), cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", stdin=subprocess.DEVNULL, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise RelayError(f"Codex could not be started ({exc.filename or argv[0]}); install the Codex CLI and sign in with "
                         "the ChatGPT account whose Adobe app is connected") from exc
    except subprocess.TimeoutExpired as exc:
        raise RelayError(f"Codex did not finish within {int(timeout)} s; the call may or may not have happened") from exc
    return Completed(done.returncode, done.stdout, done.stderr)


# ---------------------------------------------------------------- reading the stream

@dataclass
class Stream:
    calls: dict[str, dict]            # connector call items by id, the latest state of each
    others: list[str]                 # item types that are actions of another kind
    errors: list[str]
    usage: dict | None
    said: str


def read_stream(stdout: str) -> Stream:
    found = Stream({}, [], [], None, "")
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        item = event.get("item") if isinstance(event.get("item"), dict) else None
        if kind == "turn.completed" and isinstance(event.get("usage"), dict):
            found.usage = event["usage"]
        elif kind in ("turn.failed", "error"):
            found.errors.append(clean.text(json.dumps(event.get("error") or event.get("message") or event), 300) or "")
        elif item is not None and kind in ("item.started", "item.updated", "item.completed"):
            what = item.get("type")
            if what == "mcp_tool_call":
                found.calls[str(item.get("id"))] = item
            elif what == "agent_message":
                found.said = clean.text(item.get("text"), 300) or found.said
            elif what == "error":
                found.errors.append(clean.text(item.get("message"), 300) or "")
            elif what not in HARMLESS_ITEMS and str(what) not in found.others:
                found.others.append(str(what))
    return found


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def verify(stream: Stream, tool: str, arguments: dict) -> dict:
    """The one completed call item when the stream shows exactly the call asked for; Refused or RelayError otherwise."""
    if stream.others:
        raise Refused("Codex did more than the one connector call: its stream also shows "
                      f"{', '.join(stream.others)}; the result is not used")
    if not stream.calls:
        why = next((e for e in stream.errors if e and not e.startswith("Under-development")), "")
        hint = (f" Codex reported: {why}." if why else "") + (f" It said: {stream.said!r}." if stream.said else "")
        raise RelayError("Codex made no connector call, so there is no result." + hint + " Check that Codex is signed in "
                         "with the account whose Adobe app is connected (run `codex` once and look for the Adobe app).")
    if len(stream.calls) > 1:
        names = ", ".join(str(c.get("tool")) for c in stream.calls.values())
        raise Refused(f"the stream shows {len(stream.calls)} connector calls ({names}), not the one asked for; the "
                      "result is not used")
    call = next(iter(stream.calls.values()))
    if call.get("server") != SERVER or call.get("tool") != tool_name(tool):
        raise Refused(f"the stream shows a call of {call.get('server')}/{call.get('tool')}, not {SERVER}/"
                      f"{tool_name(tool)}; the result is not used")
    if _canonical(call.get("arguments")) != _canonical(arguments):
        raise Refused(f"the call's arguments were {_canonical(call.get('arguments'))[:300]}, not the ones asked for "
                      f"({_canonical(arguments)[:300]}); the result is not used")
    if call.get("status") not in ("completed", "failed"):
        raise RelayError(f"the call did not finish (status {call.get('status')!r}); there is no result")
    return call


def payload_of(call: dict) -> dict:
    """The connector's JSON object from a verified call item; RelayError for a failed call or text that is none."""
    result = call.get("result") if isinstance(call.get("result"), dict) else {}
    content = result.get("content") if isinstance(result.get("content"), list) else []
    body = next((c.get("text") for c in content if isinstance(c, dict) and isinstance(c.get("text"), str)), None)
    if call.get("status") == "failed" or body is None:
        message = clean.text(body or json.dumps(call.get("error")), 300) or "no message"
        raise RelayError(f"the connector call failed: {message}")
    try:
        payload = json.loads(body)
    except ValueError:
        raise RelayError(f"the connector's answer is not JSON: {clean.text(body, 200)!r}") from None
    if not isinstance(payload, dict):
        raise RelayError("the connector's answer is not a JSON object")
    return payload


def relay(tool: str, arguments: dict, *, model: str, runner: Runner = run_codex, codex: str | None = None,
          timeout: float = TIMEOUT_S) -> Outcome:
    """Ask Codex for one connector call and return the verified result. `runner` starts the process (tests give it
    a recorded stream)."""
    if tool not in TOOLS:
        raise ValueError(f"unknown connector tool {tool!r}")
    binary = codex or codex_binary()
    if binary is None:
        raise RelayError("the Codex CLI is not on PATH (`codex`); `lazuli adobe` asks the Adobe Fonts connector through it. "
                         "Install Codex and sign in with the ChatGPT account whose Adobe app is connected, or set "
                         "LAZULI_CODEX to its path")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="lazuli-adobe-") as work:
        schema = Path(work) / "answer.schema.json"
        schema.write_text(json.dumps(ANSWER_SCHEMA), encoding="utf-8")
        done = runner(argv_for(binary, model, schema, prompt_for(tool, arguments)), work, timeout)
    stream = read_stream(done.stdout)
    call = verify(stream, tool, arguments)
    try:
        payload = payload_of(call)
    except RelayError as exc:
        if tool not in ACTION_TOOLS:
            raise
        # the verified call did happen: report its failure as the outcome instead of hiding the call
        payload = {"success": False, "error_code": "relay_error", "user_message": str(exc)}
    return Outcome(tool, arguments, payload, stream.usage, round(time.monotonic() - started, 1), model)
