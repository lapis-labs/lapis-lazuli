"""Validated behavior session assembly and shared probe state."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import yaml

from lapis_design import __version__, shared_dir
from lapis_design.behavior import derive_session

PROBE_NAMES = ("controls", "commits", "keyboard", "dialogs", "choices", "forms", "states",
               "urgency", "time_limits", "history", "pointer", "motion", "scroll",
               "permissions", "media", "flows", "console")


class Session:
    def __init__(self, url: str, task: str, *, engine=None, plan: dict | None = None,
                 plan_path: str | None = None, backend: str = "stub", outbound: str | None = None,
                 build: str | None = None, extract: str | None = None, values_engine=None,
                 stub_path: str | None = None, timezone: str = "UTC", addresses: list[str] | None = None):
        self.engine = engine
        self.timezone = timezone                         # IANA zone every context runs in
        self.values_engine = values_engine or engine
        self.fixture_values = self.values_engine.all_values() if self.values_engine is not None else {}
        from lapis_design.stub.engine import SessionClock
        self.clock = engine.clock if engine is not None else SessionClock(int(datetime.now(UTC).timestamp() * 1000))
        self.plan = plan
        self.contexts: dict[str, dict] = {}
        self.nodes: dict[str, dict] = {}
        self.probes: dict[str, list] = {}
        self.flows: list[dict] = []
        self.coverage: list[dict] = []
        self.console_entries: list[dict] = []
        self.extract_ids: set[str] = set()
        if extract:
            import json
            data = json.loads(Path(extract).read_text())
            self.extract_ids = {box["id"] for vp in data.get("viewports", []) for box in vp.get("boxes", [])}
        self.meta = {"driver": {"name": "behavior_check", "version": __version__},
                     "generated_at": datetime.now(UTC).isoformat(), "backend": backend}
        for key, value in (("outbound", outbound), ("build", build), ("extract", extract),
                           ("stub", stub_path)):
            if value is not None:
                self.meta[key] = value
        self.source = {"kind": "render", "url": url, "task": task}
        if addresses is not None:
            self.source["addresses"] = addresses
        if plan_path is not None:
            self.source["plan"] = plan_path
        self.context("m", width=390, height=844, pointer="coarse")
        self.context("d", width=1440, height=900, pointer="fine")
        self.drivers: set = set()
        self._matrix_ids = tuple(self.contexts)          # the base matrix, before any probe adds twins

    def context(self, id: str, **overrides) -> str:
        base = dict(self.contexts.get("m", {"width": 390, "height": 844, "dpr": 2,
                                          "theme": "light", "pointer": "coarse", "network": "normal",
                                          "reduced_motion": False, "clock": "controlled", "storage": "fresh",
                                          "timezone": self.timezone}))
        base.update(overrides)
        base["id"] = id
        self.contexts[id] = base
        return id

    @property
    def matrix(self) -> list[str]:
        """The selected base contexts. Twins a probe adds (reduced motion, slow, offline, locales)
        appear in `contexts` but never widen the matrix other probes iterate."""
        return [ctx_id for ctx_id in self._matrix_ids if ctx_id in self.contexts]

    def advance_clock(self, ms: int, *, jump: bool = False) -> None:
        """Advance the one controlled timeline: the backend clock and every open page.

        `jump` fires each due timer once at its final instant (Playwright `fast_forward`), for long
        idles such as urgency expiry or session limits; otherwise every timer tick runs (`run_for`)."""
        if ms <= 0:
            return
        self.clock.advance(ms)
        for driver in tuple(self.drivers):
            if driver.page is not None:
                if jump:
                    driver.page.clock.fast_forward(ms)
                else:
                    driver.page.clock.run_for(ms)

    def node(self, box_id, *, role, name=None, rect=None, context=None, appears="load") -> str:
        data = self.nodes.setdefault(box_id, {"role": role, "appears": appears})
        if box_id in self.extract_ids:
            data["in_extract"] = True
        for key, value in (("name", name), ("rect", rect), ("context", context)):
            if value is not None and (key not in data or key == "name" and not data[key]):
                data[key] = value
        return box_id

    def add_probe(self, name: str, probe: dict) -> None:
        self.probes.setdefault(name, []).append(probe)

    def add_flow_run(self, run: dict) -> None:
        self.flows.append(run)

    def cover(self, probe: str, status: str, *, contexts=None, reason=None) -> None:
        entry = {"probe": probe, "status": status}
        if contexts is not None:
            entry["contexts"] = list(contexts)
        if reason is not None:
            entry["reason"] = reason
        self.coverage.append(entry)

    def console(self, entry: dict) -> None:
        self.console_entries.append(entry)

    def document(self) -> dict:
        doc = {"version": 0, "meta": self.meta, "source": self.source,
               "contexts": list(self.contexts.values()), "nodes": self.nodes,
               "probes": self.probes, "coverage": self.coverage, "console": self.console_entries}
        if self.flows:
            doc["flows"] = self.flows
        doc = derive_session(doc, (self.plan or {}).get("flows"))
        schema = yaml.safe_load((shared_dir() / "behavior" / "session.schema.yaml").read_text())
        errors = sorted(jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
                        .iter_errors(doc), key=lambda e: (list(map(str, e.absolute_path)), e.message))
        if errors:
            raise ValueError("invalid behavior session: " + "; ".join(
                f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}" for error in errors[:5]))
        return doc
