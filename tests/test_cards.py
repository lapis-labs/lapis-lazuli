"""Keep generator cards complete and free of checker-only lexicons."""

from collections import Counter
from pathlib import Path
import re

import yaml


SHARED = Path(__file__).resolve().parents[1] / "src" / "shared"


def load(path):
    return yaml.safe_load((SHARED / path).read_text(encoding="utf-8"))


def test_every_default_rule_appears_on_exactly_one_card():
    rules = load("slop/rules.yaml")["rules"]
    cards = load("slop/cards.yaml")["cards"]
    expected = {rule["id"] for rule in rules if rule["class"] == "default"}
    counts = Counter(rule_id for card in cards for rule_id in card["rules"])
    assert {rule_id: counts[rule_id] for rule_id in sorted(expected) if counts[rule_id] != 1} == {}


def test_card_rules_exist_and_are_defaults():
    rules = {rule["id"]: rule for rule in load("slop/rules.yaml")["rules"]}
    bad = [(card["id"], rule_id) for card in load("slop/cards.yaml")["cards"]
           for rule_id in card["rules"] if rule_id not in rules or rules[rule_id]["class"] != "default"]
    assert bad == []


def test_cues_and_routes_keep_out_bounds_and_locale_terms():
    doc = load("slop/rules.yaml")
    terms = {term.casefold() for group in doc["lists"].values()
             for locale, values in group["values"].items() if locale not in {"all", "latin"}
             for term in values}
    patterns = [(term, re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE))
                for term in sorted(terms)]
    leaks = []
    for card in load("slop/cards.yaml")["cards"]:
        for text in [card["cue"], *card["routes"]]:
            if re.search(r"\d", text):
                leaks.append((card["id"], "digit", text))
            leaks.extend((card["id"], term, text) for term, pattern in patterns if pattern.search(text))
    assert leaks == []


def test_every_decision_path_exists_in_plan_schema():
    schema = load("plan/schema.yaml")
    missing = []
    for card in load("slop/cards.yaml")["cards"]:
        for path in card["decide"]:
            node = schema
            for part in path.split("."):
                while "$ref" in node:
                    node = schema["$defs"][node["$ref"].rsplit("/", 1)[-1]]
                node = node.get("properties", {}).get(part)
                if node is None:
                    missing.append((card["id"], path))
                    break
    assert missing == []
