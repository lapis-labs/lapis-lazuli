"""How far a locked font's license was researched (fonts/lock.schema.yaml, `license.research`).

`plan_check`, `rights_check`, the release gate, and `lazuli lock` read the same four states:

  researched   `license.research.outcome` is `verified` or `restricted`: a document was read and recorded
  unknown      `license.research.outcome` is `unknown-after-research`: the search was made and found nothing
  unresearched the license kind is unknown and no research is recorded, so the search has not been made
  recorded     a known license with no research record (a lock written before research was recorded, or a
               declaration the user made): judged by its kind, grants, and source class as before
"""
from __future__ import annotations

DOCUMENT_EVIDENCE = {"license-file": "rights-holder", "rights-holder-page": "rights-holder",
                     "distributor-page": "provider", "installer-terms": "provider"}
HINT_CLASSES = {"catalog-summary", "file-metadata"}


def implied_class(evidence: list[dict]) -> str | None:
    """The license source class the evidence items imply: the rights holder's own document wins over a
    provider's terms; None when no item is a document (a name record or a search is a hint)."""
    classes = {DOCUMENT_EVIDENCE[item["via"]] for item in evidence if item.get("via") in DOCUMENT_EVIDENCE}
    return "rights-holder" if "rights-holder" in classes else "provider" if classes else None


def state(entry: dict) -> str:
    lic = entry.get("license") or {}
    outcome = (lic.get("research") or {}).get("outcome")
    if outcome == "unknown-after-research":
        return "unknown"
    if outcome in ("verified", "restricted"):
        return "researched"
    return "unresearched" if lic.get("kind", "unknown") == "unknown" else "recorded"
