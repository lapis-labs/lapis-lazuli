"""`lazuli adobe`: an opt-in relay to the Adobe Fonts connector through the owner's own Codex CLI.

Nothing here reads, opens, or sends a font file, and nothing here calls an Adobe address: lazuli starts
`codex exec` with a prompt that names one connector tool and its exact arguments, reads that tool's result
from Codex's event stream, and keeps a sanitized copy in the user cache beside the lazuli database (never
in it). What comes back is Adobe's catalog data about names; it is provenance `adobe-connector`, shown to
the owner and used to recommend, and never an input of measurement, calibration, evaluation, or a label.

Modules: `config` (the owner's opt-in), `relay` (one call, verified against the event stream), `clean`
(what is kept of a result), `store` (the user-cache records), `consent` (the owner's words that an action
needs), `cli` (`lazuli adobe ...`).
"""

PROVENANCE = "adobe-connector"
