"""Skeletons of the records a run writes by hand: the shape, never the judgment.

  lapis-design plan skeleton [--section NAME] [--task T] [--mode M]   the plan, or one of its sections, from plan/schema.yaml
  lapis-design draft skeleton --task T                     the pre-show review record, one page per shown link
  lapis-design critic dispositions --skeleton --report F   the `review.handled` entries a critic or lint report needs
  lapis-design answers skeleton --task T                   the answer rows the conversation has open

A record skeleton is made from the schema the record is checked against, so it cannot drift from it: every key the
schema requires is there, each value is `null` (a list that must hold something holds one template item), and a comment
names what goes in, with the allowed values. It parses as the shape of the record and fails the record's own check until
it is filled: no `fixed`, no `justified-keep`, no `waived`, no reason, no owner words, and no tag that says the owner
said it is written for the run. Only what the files already hold is filled in: the task id, a constant the schema
fixes, a page address the questions link, a finding's number, the report's path. Nothing here is read back by a check.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from lapis_design import shared_dir

MAX_DEPTH = 6
_TEXT_CAP = 90


# ---------------------------------------------------------------- a schema as a skeleton

def _pointer(root: dict, ref: str) -> Any:
    node: Any = root
    for part in ref.removeprefix("#/").split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def _flat(root: dict, node: Any, seen: tuple[str, ...] = ()) -> dict:
    """`node` with its `$ref` followed, its `allOf` merged in, and, for a `oneOf`, its first branch that is no `null`."""
    if not isinstance(node, dict):
        return {}
    if ref := node.get("$ref"):
        if ref in seen:
            return {}
        merged = {**_flat(root, _pointer(root, ref), (*seen, ref)), **{k: v for k, v in node.items() if k != "$ref"}}
        return _flat(root, merged, (*seen, ref))
    out = {k: v for k, v in node.items() if k not in ("allOf", "oneOf", "anyOf")}
    for part in node.get("allOf") or ():
        part = _flat(root, part, seen)
        for key, value in part.items():
            if key == "properties":
                out["properties"] = {**out.get("properties", {}), **value}
            elif key == "required":
                out["required"] = list(dict.fromkeys([*out.get("required", []), *value]))
            else:
                out.setdefault(key, value)
    for key in ("oneOf", "anyOf"):
        branches = [b for b in (_flat(root, b, seen) for b in node.get(key) or ()) if b.get("type") != "null"]
        if branches and "properties" not in out and "type" not in out and "enum" not in out:
            first = branches[0]
            out = {**first, **{k: v for k, v in out.items() if k not in first}}
    return out


def _quote(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _hint(node: dict) -> str:
    """What may be written where the skeleton has `null`, as one comment."""
    if "enum" in node:
        return "one of: " + " | ".join(str(v) for v in node["enum"])
    kind = node.get("type")
    kind = " or ".join(kind) if isinstance(kind, list) else kind
    parts = [kind or "value"]
    if "minLength" in node:
        parts.append(f"{node['minLength']}+ characters")
    if "pattern" in node:
        parts.append(f"pattern {node['pattern']}")
    if "minimum" in node and "maximum" in node:
        parts.append(f"{node['minimum']} to {node['maximum']}")
    elif "minimum" in node:
        parts.append(f"at least {node['minimum']}")
    elif "maximum" in node:
        parts.append(f"at most {node['maximum']}")
    if kind == "array" and isinstance(node.get("items"), dict):
        inner = node["items"]
        parts = ["list of: " + " | ".join(str(v) for v in inner["enum"]) if inner.get("enum")
                 else f"list of {inner.get('type', 'values')}"]
    text = ", ".join(parts)
    return text if len(text) <= _TEXT_CAP * 2 else text[:_TEXT_CAP * 2] + "..."


def _is_object(node: dict) -> bool:
    return node.get("type") == "object" or "properties" in node


class _Ctx:
    """What the lines of one skeleton share: the schema, the values the files hold (by key path, a list as `*`), and the
    optional keys shown as if required."""

    def __init__(self, root: dict, fill: dict[tuple, Any], include: set[tuple], notes: dict[tuple, str]):
        self.root, self.fill, self.include, self.notes = root, fill, include, notes

    def object_lines(self, node: dict, indent: int, path: tuple, depth: int, all_keys: bool = False) -> list[str]:
        """The `key: value` lines of an object: the keys it requires and those `include` names, or, with `all_keys`, every
        key it names."""
        required = node.get("required") or []
        props = node.get("properties") or {}
        lines: list[str] = []
        for name in props:
            if all_keys or name in required or (*path, name) in self.include:
                lines += self.entry(name, props[name], indent, (*path, name), depth + 1)
        return lines

    def optional_note(self, node: dict, path: tuple, all_keys: bool) -> str:
        required = node.get("required") or []
        left = [name for name in (node.get("properties") or {})
                if name not in required and (*path, name) not in self.include] if not all_keys else []
        return f"  # optional: {', '.join(left)}" if left else ""

    def entry(self, name: str, raw: Any, indent: int, path: tuple, depth: int, all_keys: bool = False) -> list[str]:
        node = _flat(self.root, raw)
        pad = " " * indent
        if (given := self.fill.get(path)) is not None:
            return [f"{pad}{name}: {_quote(given)}"]
        if "const" in node:
            return [f"{pad}{name}: {_quote(node['const'])}"]
        if depth > MAX_DEPTH:
            return [f"{pad}{name}: null  # {_hint(node)}"]
        if _is_object(node):
            body = self.object_lines(node, indent + 2, path, depth, all_keys)
            note = self.optional_note(node, path, all_keys) or (f"  # {self.notes[path]}" if path in self.notes else "")
            return [f"{pad}{name}:{note}", *body] if body else [f"{pad}{name}: {{}}{note}"]
        if node.get("type") == "array":
            item = _flat(self.root, node.get("items"))
            if _is_object(item):
                body = self.object_lines(item, indent + 4, (*path, "*"), depth)
                note = self.optional_note(item, (*path, "*"), False)
                if not body:
                    return [f"{pad}{name}: []{note}"]
                body[0] = f"{pad}  - " + body[0].lstrip()
                return [f"{pad}{name}:{note}", *body]
            if node.get("minItems", 0) >= 1:
                return [f"{pad}{name}:", f"{pad}  - null  # {_hint(item) if item else 'value'}"]
            return [f"{pad}{name}: []  # {_hint(node)}"]
        return [f"{pad}{name}: null  # {_hint(node)}"]


def _holds(condition: dict, known: dict[str, Any]) -> bool:
    props = condition.get("properties") or {}
    return bool(props) and all("const" in rule and known.get(key) == rule["const"] for key, rule in props.items())


def _conditions(schema: dict) -> list[tuple[str, Any, list[str]]]:
    """`(key, value, required)` for each top-level `if key is value then require ...` of the schema."""
    found = []
    for part in schema.get("allOf") or ():
        condition, then = part.get("if") or {}, part.get("then") or {}
        props = condition.get("properties") or {}
        if len(props) == 1 and then.get("required"):
            (key, rule), = props.items()
            if "const" in rule:
                found.append((key, rule["const"], list(then["required"])))
    return found


def from_schema(schema: dict, *, fill: dict[tuple, Any] | None = None, include: set[tuple] | None = None,
                notes: dict[tuple, str] | None = None, section: str | None = None,
                known: dict[str, Any] | None = None) -> str:
    """The skeleton of a record that `schema` describes. `fill` gives the values the files already hold, by key path (a
    list is `"*"`); `include` names optional keys to show as if required, `notes` says when one applies; `section` limits
    the skeleton to one top-level key and shows every key the section names, one level down. A top-level rule of the
    schema that requires more keys when one key has a value (`known`) adds them; when `known` does not say, a comment
    names the keys it would add."""
    known = known or {}
    ctx = _Ctx(schema, fill or {}, include or set(), notes or {})
    props = schema.get("properties") or {}
    if section is not None:
        if section not in props:
            raise KeyError(section)
        lines = ctx.entry(section, props[section], 0, (section,), 0, all_keys=True)
    else:
        top = _flat(schema, schema)
        required = list(top.get("required") or [])
        comments = []
        for key, value, more in _conditions(schema):
            if _holds({"properties": {key: {"const": value}}}, known):
                required += [name for name in more if name not in required]
            else:
                comments.append(f"# with {key}: {value}, also required: {', '.join(name for name in more if name not in required)}"
                                f" (`--{key} {value}` shows them)")
        lines = ctx.object_lines({**top, "required": required}, 0, (), 0)
        left = [name for name in props if name not in required and (name,) not in ctx.include]
        if left:
            lines.append(f"# optional sections, each with `--section NAME`: {', '.join(left)}")
        lines += comments
    return "\n".join(lines) + "\n"


def _schema(name: str) -> dict:
    return yaml.safe_load((shared_dir() / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- the records

def plan(task: str | None = None, section: str | None = None, mode: str | None = None) -> str:
    """The plan (required keys only), or one section with every key it names; `task` fills the task id, `mode` the mode
    and the keys that mode requires."""
    schema = _schema("plan/schema.yaml")
    fill: dict[tuple, Any] = {("task", "id"): task} if task and section in (None, "task") else {}
    if mode and section is None:
        fill[("mode",)] = mode
    body = from_schema(schema, fill=fill, section=section, known={"mode": mode} if mode else None)
    where = f".lapis/plans/{task or '<task>'}.yaml"
    head = (f"# The plan {where}" + (f", section `{section}`" if section else "") + " (shared plan/schema.yaml).\n"
            "# Every null is yours to fill; a list shows one item to repeat. Rules that depend on another value (if/then in the\n"
            "# schema) and the plan's code checks are not shown: `lapis-design plan check` names what is still missing.\n")
    return head + body


def draft(root: Path, task: str) -> str:
    """The pre-show review record: one page per link the questions show, its address filled in."""
    from lapis_design import draft as draft_module

    links = draft_module.shown(root, task)
    fill: dict[tuple, Any] = {("task",): task}
    include = {("pages", "*", "review", "critic"), ("pages", "*", "review", "behavior"), ("pages", "*", "review")}
    notes = {("pages", "*", "review", "critic"): "required when direction is new",
             ("pages", "*", "review", "behavior"): "required when behavior_changed is true"}
    body = from_schema(_schema("release/draft.schema.yaml"), fill=fill, include=include, notes=notes)
    if len(links) > 1:                                    # one page per shown link: repeat the page item of the first
        lines = body.splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith("pages:"))
        end = next((i for i in range(start + 1, len(lines)) if lines[i] and not lines[i].startswith(" ")), len(lines))
        item = lines[start + 1:end]
        body = "\n".join([*lines[:start + 1], *item * len(links), *lines[end:]]) + "\n"
    if links:
        out, url = [], iter(links)
        for line in body.splitlines():
            if re.match(r"^\s*(- )?url: null", line):
                line = re.sub(r"url: null.*$", f"url: {_quote(next(url))}", line)
            out.append(line)
        body = "\n".join(out) + "\n"
    head = (f"# The pre-show review record .lapis/drafts/{task}.yaml (shared release/draft.schema.yaml), one page per link the\n"
            "# questions show. Every null is yours to fill from what you observed. `review.handled` takes one entry per open\n"
            "# finding of each report the page names: `lapis-design critic dispositions --skeleton --report FILE` lists them.\n"
            "# Declare a specimen or a reference capture the questions link as `supporting`, never as a page.\n")
    return head + body


def dispositions(report_file: Path, report_name: str) -> str:
    """The `review.handled` entries the report at `report_file` needs: one per open finding, its disposition, reason, and
    refs empty, and a comment for every other finding. `report_name` is the path as the page's review names it."""
    document = json.loads(report_file.read_text(encoding="utf-8")) if report_file.suffix.lower() == ".json" else \
        yaml.safe_load(report_file.read_text(encoding="utf-8"))
    findings = document.get("findings") if isinstance(document, dict) else None
    if not isinstance(findings, list):
        raise ValueError(f"{report_file} has no `findings` list: it is not a critic or lint report")
    schema = _schema("release/draft.schema.yaml")
    handled = _flat(schema, _pointer(schema, "#/properties/pages")["items"]["properties"]["review"]["properties"]["handled"])
    item = _flat(schema, handled["items"])
    allowed = " | ".join(item["properties"]["disposition"]["enum"])
    open_ = [(i, f) for i, f in enumerate(findings) if isinstance(f, dict) and f.get("status") == "open"]
    lines = [f"# {len(open_)} open finding{'s' if len(open_) != 1 else ''} of {len(findings)} in {report_name}: one entry each, "
             f"in `review.handled` of the page whose review names this report (.lapis/drafts/<task>.yaml).",
             f"# disposition is one of {allowed}. reason: {item['properties']['reason'].get('minLength', 1)}+ characters, for the owner. "
             "refs: a file that shows it.",
             "# The skeleton decides nothing: a disposition left null fails `lapis-design draft check`."]
    for number, finding in open_:
        lines += [f"- report: {_quote(report_name)}",
                  f"  finding: {number}  # {finding.get('rule_id')}: {_one_line(finding.get('observed'))}",
                  "  disposition: null",
                  "  reason: null",
                  "  refs: []"]
    others = [f"# finding {i} ({f.get('rule_id')}) is {f.get('status')}: it needs no entry" for i, f in enumerate(findings)
              if isinstance(f, dict) and f.get("status") != "open"]
    return "\n".join([*lines, *others]) + "\n"


def _one_line(text: Any, limit: int = 110) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def answers(root: Path, task: str) -> str:
    """The answer rows the conversation has open: the direction items and the pick with the choices each takes, and the
    open core findings of the critic reports shown. No row is tagged and none holds a choice: a row the owner did not
    answer stays open, and the tag that says the owner said it is the run's to write for what they said."""
    from lapis_design import direction, diverge, owner

    answers_file = f".lapis/answers/{task}.md"
    out = [f"# Answer rows for {answers_file}. Nothing here is an answer: a row with no choice does not count.",
           "# Replace `[TAG]` with `[declared]` for a reply the owner gave (their words after the choice, kept as said), or, in an",
           "# unattended run with nobody to ask, with `[assumed]` and a `Basis:`. Leave out a row the owner did not answer."]
    rows: list[str] = []
    choices: list[str] = []
    seal = diverge.sealed(root, task)
    turn = direction.turns(root, task) + 1
    chosen = direction.pick(root, task)
    open_items = [i for i in direction.items(root, task) if i["state"] == "open"
                  and (i["candidate"] is None or (chosen is not None and i["candidate"] == chosen["candidate"]))]
    if open_items:
        rows += [f"## Direction {turn}", ""]
        for item in open_items:
            rows.append(f"- [TAG] {item['id']} {item.get('role') or item['label']}: ")
            choices.append(f"#   {item['id']}: {_choices(item)}")
    if seal is not None and chosen is None and not open_items:      # the pick is asked once every item of turn one stands
        if not rows:
            rows += [f"## Direction {turn}", ""]
        rows.append("- [TAG] Pick: ")
        choices.append(f"#   Pick: {' | '.join(seal['candidates'])}")
    core = owner.core_findings(root, task)
    if core:
        rows += ["", "## Open core findings", ""]
        rows += [f"- [TAG] Ask finding-vs-decision: {rule_id} — " for rule_id, _ in core]
        choices += [f"#   {rule_id}: {_one_line(observed)}" for rule_id, observed in core]
    if not rows:
        out.append("# No row is open: the direction items have answers and no core finding waits on the owner.")
        return "\n".join(out) + "\n"
    if choices:
        out += ["# Choices (the choice follows the last colon of the name; for an object, letters as `a,c`):", *choices]
    return "\n".join([*out, "", *rows]) + "\n"


def _choices(item: dict[str, Any]) -> str:
    options = [o["id"] for o in item["options"]]
    kind = item["kind"]
    if kind == "K":
        return "keep | drop | default | other"
    extra = ["all"] if kind == "O" else []
    return " | ".join([*options, *extra, "default", "other"]) + (" (several letters as a,c)" if kind == "O" else "")


# ---------------------------------------------------------------- the commands

def main(argv: list[str] | None = None, prog: str = "lapis-design plan skeleton") -> int:
    noun, verb = prog.split()[-2:]
    ap = argparse.ArgumentParser(prog=prog, allow_abbrev=False, description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--root", type=Path, default=Path("."), help="the project folder (default: .)")
    if (noun, verb) == ("plan", "skeleton"):
        ap.add_argument("--task", help="the task id to fill in")
        ap.add_argument("--section", help="one top-level section, with every key it names")
        ap.add_argument("--mode", choices=_schema("plan/schema.yaml")["properties"]["mode"]["enum"],
                        help="the plan's mode: fills it in and shows the keys that mode requires")
    elif (noun, verb) == ("critic", "dispositions"):
        ap.add_argument("--skeleton", action="store_true", required=True,
                        help="print the entries to fill (the only form: a disposition is a judgment this command never makes)")
        ap.add_argument("--report", type=Path, required=True,
                        help="the critic or lint report, as the page's review names it")
    else:
        ap.add_argument("--task", required=True, help="the task id")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    try:
        if (noun, verb) == ("plan", "skeleton"):
            text = plan(args.task, args.section, args.mode)
        elif (noun, verb) == ("draft", "skeleton"):
            text = draft(root, args.task)
        elif (noun, verb) == ("answers", "skeleton"):
            text = answers(root, args.task)
        else:
            file = args.report if args.report.is_absolute() else args.root / args.report
            text = dispositions(file, args.report.as_posix())
    except KeyError as exc:
        print(f"{prog}: the plan has no section {exc.args[0]}; its sections are "
              f"{', '.join(_schema('plan/schema.yaml')['properties'])}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"{prog}: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
