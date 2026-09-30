"""Stable DOM-path box identities; generated element IDs use sibling indices instead."""
from __future__ import annotations

import hashlib
import re

_GENERATED = re.compile(r"\d{4,}|^(?::r|radix-|mui-|react-|__next|ember-|headlessui-)", re.I)
DOM_PATH_JS = r"""function path(el) {
    const result = [];
    for (let x=el; x; x=x.parentElement) {
      let index = 0;
      for (let sib=x.previousElementSibling; sib; sib=sib.previousElementSibling)
        if (sib.localName === x.localName) index++;
      result.unshift([x.localName, index, x.id || null]);
    }
    return result;
 }"""



def generated_id(value: str) -> bool:
    return bool(_GENERATED.search(value))


def box_id(steps: list[tuple[str, int, str | None]]) -> str:
    """Hash each root-to-element step, using a stable id in place of its tag/index."""
    path = "/".join(
        f"#{identifier}" if identifier and not generated_id(identifier) else f"{tag.lower()}:{index}"
        for tag, index, identifier in steps
    )
    return "b" + hashlib.sha256(path.encode("utf-8")).hexdigest()[:12]
