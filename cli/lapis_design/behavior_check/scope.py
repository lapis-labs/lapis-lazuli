"""Which boxes the per-box probes exercise: every one, or only those a narrowed run asked for."""
from __future__ import annotations

# Probes that exercise one box at a time (`controls` acts on each interactive box; `pointer` hovers each one and
# tries the drag and gesture widgets). `--box` and `--limit` narrow these; every other probe works on the page,
# a route, or a named kind of control and ignores them.
PER_BOX = ("controls", "pointer")

# Probes that work from the boxes another probe exercised, so they were narrowed with it.
FED_BY = {"commits": ("controls",)}


class BoxScope:
    """`--box ID` (repeatable) keeps a probe to those boxes; `--limit N` keeps it to the first N boxes, in document
    order, of each context. A box a probe leaves out is counted, and `Session.cover` turns the count into a
    `partial` entry that says how many. Without either option every box is admitted and nothing is counted."""

    def __init__(self, ids=(), limit: int | None = None):
        self.ids = tuple(dict.fromkeys(ids))
        self.limit = limit
        self._taken: dict[tuple[str, str], set[str]] = {}       # (probe, context) -> boxes admitted
        self._left_out: dict[tuple[str, str], set[str]] = {}    # (probe, context) -> boxes left out
        self._matched: dict[str, set[str]] = {}                 # probe -> --box ids a box was found for

    @property
    def active(self) -> bool:
        return bool(self.ids) or self.limit is not None

    def admit(self, probe: str, ctx_id: str, box_id: str) -> bool:
        """Whether the probe exercises this box in this context; asking again about a box gives the same answer."""
        if not self.active:
            return True
        taken = self._taken.setdefault((probe, ctx_id), set())
        if box_id in taken:
            return True
        named = not self.ids or box_id in self.ids
        if named:
            self._matched.setdefault(probe, set()).add(box_id)
        if named and (self.limit is None or len(taken) < self.limit):
            taken.add(box_id)
            return True
        self._left_out.setdefault((probe, ctx_id), set()).add(box_id)
        return False

    def pick(self, probe: str, ctx_id: str, boxes: list[dict]) -> list[dict]:
        """The boxes (each a dict with an `id`, in document order) the probe exercises."""
        return [box for box in boxes if self.admit(probe, ctx_id, box["id"])]

    def _left(self, probe: str) -> tuple[str, str] | None:
        """How many boxes the probe left out, as `3 boxes` and `m: 1, d: 2`."""
        counts = {ctx_id: len(ids) for (name, ctx_id), ids in self._left_out.items() if name == probe and ids}
        if not counts:
            return None
        total = sum(counts.values())
        return f"{total} {'box' if total == 1 else 'boxes'}", ", ".join(f"{ctx}: {n}" for ctx, n in counts.items())

    def left_out(self, probe: str) -> list[str]:
        """What narrowing cost this probe, for its coverage reason: the boxes left out, and any `--box` id the
        probe found no box for. Empty when the run is not narrowed or the probe lost nothing."""
        reasons = []
        if probe in PER_BOX:
            if left := self._left(probe):
                reasons.append(f"{left[0]} left out by --box/--limit ({left[1]})")
            reasons += [f"--box {box_id} matched no box the probe exercised"
                        for box_id in self.ids if box_id not in self._matched.get(probe, ())]
        for source in FED_BY.get(probe, ()):
            if left := self._left(source):
                reasons.append(f"{source} left out {left[0]} by --box/--limit ({left[1]})")
        return reasons
