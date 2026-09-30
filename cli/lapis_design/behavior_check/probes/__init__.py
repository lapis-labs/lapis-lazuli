"""Ordered behavior probe modules.

Each module declares NAMES: tuple[str, ...] and run(session, open_driver).
open_driver(context_id) returns a fresh, already-loaded Driver for that context.

Order matters: flows run before commits (commit steps come from flow runs), forms (repeated entry
within a flow), and time limits (limits are found during flows).
"""
from lapis_design.behavior_check.probes import (choices, commits, controls, dialogs, flows, forms, history,
                                                keyboard, media, motion, permissions, pointer, scroll, states,
                                                time_limits, urgency)

PROBES: tuple = (controls, keyboard, dialogs, choices, permissions, media, flows, commits, forms, states,
                 urgency, time_limits, history, pointer, motion, scroll)
