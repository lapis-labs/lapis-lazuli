"""CSS selectors over a rough's markup, with no browser: which elements of an `index.html` a card's selector names.

A card names, for each style item the owner answered, the element that carries it (`card.schema.yaml`, `style`). `diverge
check` reads the page as served (static markup: `html.parser`, no script runs) and refuses a selector that matches nothing.
The render extract's boxes carry hashed ids, not selectors, so the markup is the only source of a selector's elements.

The grammar is the part of Selectors Level 3 a card needs: a type or `*`, `#id`, `.class`, `[attr]`, `[attr=v]` with the
operators `~= |= ^= $= *=` and the `i` flag, `:first-child`, `:last-child`, `:only-child`, `:nth-child(n | odd | even)`,
`:root`, `:not(<list>)`, the combinators ` ` `>` `+` `~`, and a comma list. State pseudo-classes (`:hover`, `:focus`,
`:active`, `:focus-visible`, `:focus-within`, `:visited`, `:link`) and pseudo-elements (`::before`, `::after`, ...) name no
other element, so they match as if absent. Anything else (`:has`, `:is`, `:nth-of-type`, namespaces) is a `SelectorError`,
not a silent miss.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Iterator

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
SKIPPED_TEXT = {"script", "style", "template"}
STATE = {"hover", "focus", "active", "focus-visible", "focus-within", "visited", "link"}
IGNORED_ELEMENTS = {"before", "after", "marker", "placeholder", "selection", "first-line", "first-letter", "backdrop"}


class SelectorError(ValueError):
    """The selector is not one this matcher reads; the message says which part."""


class Node:
    """One element: its tag, attributes, parent, and element children."""

    __slots__ = ("tag", "attrs", "parent", "children", "pieces")

    def __init__(self, tag: str, attrs: dict[str, str], parent: "Node | None") -> None:
        self.tag, self.attrs, self.parent = tag, attrs, parent
        self.children: list[Node] = []
        self.pieces: list[str | Node] = []          # text and child elements in document order

    def strings(self) -> list[str]:
        """Each text piece of the element and its descendants (script, style, and template content left out), whitespace collapsed."""
        found: list[str] = []

        def walk(node: Node) -> None:
            for piece in node.pieces:
                if isinstance(piece, str):
                    if piece.strip():
                        found.append(" ".join(piece.split()))
                elif piece.tag not in SKIPPED_TEXT:
                    walk(piece)

        walk(self)
        return found

    def descendants(self) -> Iterator["Node"]:
        for child in self.children:
            yield child
            yield from child.descendants()


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document", {}, None)
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, {name: value or "" for name, value in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        self.stack[-1].pieces.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, {name: value or "" for name, value in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        self.stack[-1].pieces.append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].pieces.append(data)


def parse(markup: str) -> Node:
    """The element tree of `markup`; the returned node is a `#document` holding the top-level elements."""
    parser = _Parser()
    parser.feed(markup)
    parser.close()
    return parser.root


# ---------------------------------------------------------------- the selector grammar

_IDENT = r"(?:\\.|[\w\u0080-\uffff-])+"
_TOKEN = re.compile(rf"""
    (?P<ws>\s+)
  | (?P<comma>,)
  | (?P<comb>[>+~])
  | (?P<hash>\#{_IDENT})
  | (?P<cls>\.{_IDENT})
  | (?P<attr>\[\s*(?P<an>{_IDENT})\s*(?:(?P<op>[~|^$*]?=)\s*(?P<av>"[^"]*"|'[^']*'|{_IDENT})(?:\s+(?P<flag>[iIsS]))?)?\s*\])
  | (?P<pseudo>::?{_IDENT})(?P<arg>\((?:[^()]|\([^()]*\))*\))?
  | (?P<type>\*|{_IDENT})
""", re.VERBOSE)


def _unescape(text: str) -> str:
    return re.sub(r"\\(.)", r"\1", text)


class _Compound:
    __slots__ = ("tag", "tests")

    def __init__(self) -> None:
        self.tag: str | None = None
        self.tests: list = []                       # callables Node -> bool

    def matches(self, node: Node) -> bool:
        return (self.tag is None or node.tag == self.tag) and all(test(node) for test in self.tests)


def _index(node: Node) -> tuple[int, int]:
    """The 1-based position of `node` among its parent's element children, and how many there are."""
    siblings = node.parent.children if node.parent is not None else [node]
    return siblings.index(node) + 1, len(siblings)


def _nth(arg: str):
    text = arg.strip().lower()
    if text == "odd":
        return lambda position: position % 2 == 1
    if text == "even":
        return lambda position: position % 2 == 0
    if re.fullmatch(r"\d+", text):
        return lambda position, want=int(text): position == want
    raise SelectorError(f":nth-child({arg}) is not read: write a number, odd, or even")


def _attr_test(name: str, op: str | None, value: str | None, flag: str | None):
    key, want = name.lower(), None if value is None else _unescape(value.strip("\"'"))
    fold = bool(flag) and flag.lower() == "i"

    def test(node: Node) -> bool:
        have = node.attrs.get(key)
        if have is None:
            return False
        if op is None:
            return True
        a, b = (have.lower(), want.lower()) if fold and want is not None else (have, want)
        return {"=": a == b, "~=": b in a.split(), "|=": a == b or a.startswith(b + "-"), "^=": bool(b) and a.startswith(b),
                "$=": bool(b) and a.endswith(b), "*=": bool(b) and b in a}[op]

    return test


def _pseudo(name: str, arg: str | None, compound: _Compound) -> None:
    lowered = name.lower().lstrip(":")
    if lowered in IGNORED_ELEMENTS or lowered in STATE:
        return
    if name.startswith("::"):
        raise SelectorError(f"the pseudo-element ::{lowered} is not read")
    if lowered == "first-child":
        compound.tests.append(lambda node: _index(node)[0] == 1)
    elif lowered == "last-child":
        compound.tests.append(lambda node: _index(node)[0] == _index(node)[1])
    elif lowered == "only-child":
        compound.tests.append(lambda node: _index(node)[1] == 1)
    elif lowered == "root":
        compound.tests.append(lambda node: node.tag == "html" and node.parent is not None and node.parent.tag == "#document")
    elif lowered == "nth-child" and arg is not None:
        position = _nth(arg[1:-1])
        compound.tests.append(lambda node: position(_index(node)[0]))
    elif lowered == "not" and arg is not None:
        inner = _parse_list(arg[1:-1])
        compound.tests.append(lambda node: not any(_match_complex(node, chain) for chain in inner))
    else:
        raise SelectorError(f":{lowered} is not read: use a tag, #id, .class, [attribute], :first-child, :last-child, "
                            ":nth-child(n), :not(...), and the combinators space, >, +, ~")


def _parse_list(text: str) -> list[list[tuple[str, _Compound]]]:
    """Each complex selector of the comma list as `[(combinator-before, compound), ...]`, left to right."""
    text = text.strip()
    if not text:
        raise SelectorError("the selector is empty")
    chains: list[list[tuple[str, _Compound]]] = []
    chain: list[tuple[str, _Compound]] = []
    compound: _Compound | None = None
    comb: str | None = None                          # the combinator written before the compound being built
    space = False                                    # whitespace since the last part of the compound being built

    def push() -> None:
        nonlocal compound, comb
        chain.append((comb or " ", compound))
        compound, comb = None, None

    position = 0
    while position < len(text):
        found = _TOKEN.match(text, position)
        if found is None:
            raise SelectorError(f"the selector has `{text[position]}` where a selector part was expected")
        position = found.end()
        if found.group("ws"):
            space = space or compound is not None
        elif found.group("comma"):
            if compound is None:
                raise SelectorError("the selector has a comma with nothing before it")
            push()
            chains.append(chain)
            chain, space = [], False
        elif found.group("comb"):
            if compound is None:
                raise SelectorError(f"the selector has the combinator `{found.group('comb')}` with nothing before it")
            push()
            comb, space = found.group("comb"), False
        else:
            if compound is not None and space:
                push()
            if compound is None:
                compound = _Compound()
            space = False
            if found.group("hash"):
                want = _unescape(found.group("hash")[1:])
                compound.tests.append(lambda node, want=want: node.attrs.get("id") == want)
            elif found.group("cls"):
                want = _unescape(found.group("cls")[1:])
                compound.tests.append(lambda node, want=want: want in (node.attrs.get("class") or "").split())
            elif found.group("an"):
                compound.tests.append(_attr_test(found.group("an"), found.group("op"), found.group("av"), found.group("flag")))
            elif found.group("pseudo"):
                _pseudo(found.group("pseudo"), found.group("arg"), compound)
            else:
                word = found.group("type")
                if compound.tests or compound.tag is not None:
                    raise SelectorError(f"the selector has the type `{word}` after another part of the same compound")
                compound.tag = None if word == "*" else word.lower()
    if compound is None:
        raise SelectorError("the selector ends where a selector part was expected")
    push()
    chains.append(chain)
    return chains


def _match_complex(node: Node, chain: list[tuple[str, _Compound]]) -> bool:
    """Whether `node` is the subject (the last compound) of `chain`, checked right to left."""
    def at(current: Node, index: int) -> bool:
        combinator, compound = chain[index]
        if not compound.matches(current):
            return False
        if index == 0:
            return True
        if combinator == ">":
            return current.parent is not None and at(current.parent, index - 1)
        if combinator == " ":
            ancestor = current.parent
            while ancestor is not None:
                if at(ancestor, index - 1):
                    return True
                ancestor = ancestor.parent
            return False
        siblings = current.parent.children if current.parent is not None else []
        before = siblings[:siblings.index(current)]
        if combinator == "+":
            return bool(before) and at(before[-1], index - 1)
        return any(at(sibling, index - 1) for sibling in before)
    return at(node, len(chain) - 1)


def select(root: Node, selector: str) -> list[Node]:
    """The elements of the tree `root` that `selector` matches, in document order. Raises `SelectorError`."""
    chains = _parse_list(selector)
    return [node for node in root.descendants() if any(_match_complex(node, chain) for chain in chains)]
