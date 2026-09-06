"""What a search is doing, told to someone who is only watching.

Deliberately NOT ``pipeline.ProgressSink`` (pipeline.py:529-532).  That sink
reports pair boundaries to a caller with a progress bar and is allowed to raise,
because a progress sink that raises is a bug in the caller.  This one reports
SEARCH INTERIOR to a debugging view, fires orders of magnitude more often, and
must never take a real build down with it.

The two-method protocol is the whole performance story: ``due`` decides whether
a sample is wanted BEFORE ``SearchEvent`` is built, so the cost at a call site
that is not sampling is one attribute lookup, one set membership test, one
``time.monotonic()`` and one float compare -- and nothing ever touches
``placement.buildings``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Protocol

from flab2bp.layout.base import Placement


class SearchPhase(StrEnum):
    """What kind of moment an event describes."""

    PACKED = "packed"
    ROUTED = "routed"
    CERTIFIED = "certified"
    INCUMBENT = "incumbent"
    REFUSED = "refused"
    BLOCK = "block"
    RECUT = "recut"
    COMPOSED = "composed"


#: Phases rare and load-bearing enough to bypass the sample gate.  An incumbent
#: is the one frame nobody wants dropped, and there is at most a handful per
#: build; composition happens once.
ALWAYS_SAMPLE: Final[frozenset[SearchPhase]] = frozenset(
    {SearchPhase.INCUMBENT, SearchPhase.COMPOSED}
)


#: Fixed for v1, not a UI control -- settled by the user (design §10). 250 ms
#: keeps every Rule W cell comfortably inside the 1% budget; a configurable
#: interval is a follow-on, only worth taking up if Task 13's baseline leaves
#: headroom to spend.
TRACE_SAMPLE_INTERVAL_S: Final = 0.25

#: Doubled across a spawn boundary: the queue's feeder thread does the
#: pickling (§9 R2), and that CPU is the child's own, not free background work.
TRACE_CHILD_SAMPLE_INTERVAL_S: Final = 0.5


@dataclass(frozen=True, slots=True)
class SearchEvent:
    """One thing a search did, as an immutable reference to state it already holds.

    ``placement`` is a REFERENCE and never a copy: ``Placement`` (base.py:423)
    and every ``PlacedBuilding`` in it (base.py:93) are frozen, so holding one
    costs a pointer and cannot be mutated out from under a reader.
    """

    strategy: str
    candidate: str
    phase: SearchPhase
    placement: Placement | None = None
    height: int | None = None
    arrangement: int | None = None
    restart: int | None = None
    stage: int | None = None
    island: int | None = None
    round_index: int | None = None
    block: int | None = None
    area: int | None = None
    belt_tiles: int | None = None
    incumbent: bool = False
    reason: str | None = None
    stranded: tuple[tuple[int, int, int, int], ...] = ()
    no_goods: tuple[tuple[int, ...], ...] = ()


class SearchObserver(Protocol):
    """Told what a search is doing.  Read-only, by construction."""

    def due(self, phase: SearchPhase, /) -> bool:
        """Would ``note`` do anything for this phase right now?  O(1)."""
        ...

    def note(self, event: SearchEvent, /) -> None:
        """Record ``event``.  O(1), and never raises."""
        ...


@dataclass(slots=True)
class SampledObserver:
    """Rate-limits by wall time and hands survivors to an O(1) sink.

    ``sink`` is ``deque.append`` in-process and ``TraceChannel.offer`` across a
    process boundary.  Both are non-blocking; a full destination drops and counts
    rather than waiting, exactly as ``RaceChannels._put`` does
    (strategy_race.py:199-203), because a dropped frame costs a picture and never
    a result.
    """

    sink: Callable[[SearchEvent], None]
    min_interval_s: float = TRACE_SAMPLE_INTERVAL_S
    monotonic: Callable[[], float] = time.monotonic
    _last_s: float = field(default=float("-inf"), init=False)

    def due(self, phase: SearchPhase, /) -> bool:
        if phase in ALWAYS_SAMPLE:
            return True
        return self.monotonic() - self._last_s >= self.min_interval_s

    def note(self, event: SearchEvent, /) -> None:
        self._last_s = self.monotonic()
        try:  # noqa: SIM105
            self.sink(event)
        except Exception:  # noqa: BLE001 -- R3: a view must never kill a build.
            pass


def stranded_endpoints(result: object) -> tuple[tuple[int, int, int, int], ...]:
    """Endpoint pairs for the nets a routing result could not wire.

    Typed ``object`` and read defensively for one reason only: this runs on a
    debugging path, and a shape change in ``DetailedRouteResult`` must degrade
    the picture, never the build (observe.SampledObserver's R3 in the caller is
    the second net, not an excuse to skip this one).
    """
    failures = getattr(result, "failures", ())
    pairs: list[tuple[int, int, int, int]] = []
    for failure in failures:
        source = getattr(failure, "source", None)
        destination = getattr(failure, "destination", None)
        if source is None or destination is None:
            continue
        pairs.append((int(source[0]), int(source[1]), int(destination[0]), int(destination[1])))
    return tuple(pairs)
