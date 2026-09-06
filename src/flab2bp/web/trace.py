"""Search snapshots as JSON the viewer can draw, and the ring that holds them.

A frame is a LIGHTWEIGHT PLACEMENT ENCODING and never a blueprint.
``codec.encode`` asserts a finalized frame (dsp/codec.py:281) that a mid-search
pack does not have, and costs seconds on the large placements that are exactly
the ones worth watching.  So a frame carries positional building rows -- ten
numbers each -- which is all ``buildSceneModel`` (web/src/model/layout.ts:44)
ever reads.

Rows are positional and not objects because a 3000-building placement is ~240kB
as arrays and ~1.1MB as objects, and the server's existing gzip
(server.py:143) takes the former to about 30kB.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Final, cast

from flab2bp.layout.base import PlacedBuilding
from flab2bp.layout.observe import SearchEvent
from flab2bp.web.payload import Json

#: The row order.  Positional, so the client decodes with a zod tuple and the
#: names live in exactly one place: here.
TRACE_BUILDING_FIELDS: Final = (
    "item_id",
    "model_index",
    "x",
    "y",
    "z",
    "yaw",
    "recipe_id",
    "filter_id",
    "output_obj",
    "input_obj",
)

TRACE_RING_FRAMES: Final = 256
TRACE_RING_BYTES: Final = 32 * 1024 * 1024
TRACE_MAX_BUILDINGS: Final = 6000
TRACE_PAGE_FRAMES: Final = 8

#: A rough per-row cost used for the byte bound.  Ten numbers plus separators;
#: exact enough to bound memory, and far cheaper than serializing to measure.
_ROW_BYTES: Final = 80


def building_row(building: PlacedBuilding) -> list[float]:
    """One building as ten positional numbers, in ``TRACE_BUILDING_FIELDS`` order."""
    return [
        building.item_id,
        building.model_index,
        building.x,
        building.y,
        float(building.z),
        building.yaw,
        building.recipe_id,
        building.filter_id,
        -1 if building.output_obj is None else building.output_obj,
        -1 if building.input_obj is None else building.input_obj,
    ]


def frame_json(seq: int, at_s: float, event: SearchEvent) -> Json:
    """Project one event into the wire frame.

    THE ONLY PLACE that walks ``placement.buildings``.  It runs on the parent's
    trace thread, never on a search thread.
    """
    placement = event.placement
    buildings = () if placement is None else placement.buildings
    truncated = len(buildings) > TRACE_MAX_BUILDINGS
    if truncated:
        # Every Nth building rather than the first N: a prefix of a packed
        # placement is one corner of it, which reads as a smaller layout instead
        # of a sampled one.
        step = (len(buildings) + TRACE_MAX_BUILDINGS - 1) // TRACE_MAX_BUILDINGS
        buildings = buildings[::step]
    return {
        "seq": seq,
        "t": at_s,
        "strategy": event.strategy,
        "candidate": event.candidate,
        "phase": str(event.phase),
        "height": event.height,
        "arrangement": event.arrangement,
        "restart": event.restart,
        "stage": event.stage,
        "island": event.island,
        "round": event.round_index,
        "block": event.block,
        "area": event.area,
        "belt_tiles": event.belt_tiles,
        "incumbent": event.incumbent,
        "reason": event.reason,
        "bounds": list(placement.bounds) if placement is not None else [0, 0, 0, 0],
        "buildings": cast(Json, [building_row(b) for b in buildings]),
        "truncated": truncated,
        "stranded": [list(pair) for pair in event.stranded],
        "no_goods": [list(group) for group in event.no_goods],
    }


@dataclass
class TraceRing:
    """The newest frames for one job, bounded by count AND by bytes.

    Both bounds, because 256 frames of 6000 buildings is memory this process
    does not have, and a byte bound alone would let a stream of tiny frames
    grow without limit.
    """

    max_frames: int = TRACE_RING_FRAMES
    max_bytes: int = TRACE_RING_BYTES
    _frames: deque[tuple[Json, int]] = field(default_factory=deque, init=False)
    _bytes: int = field(default=0, init=False)
    _dropped: int = field(default=0, init=False)

    @property
    def dropped(self) -> int:
        return self._dropped

    def append(self, frame: Json) -> None:
        rows = frame.get("buildings")
        size = (len(rows) if isinstance(rows, list) else 0) * _ROW_BYTES + 512
        self._frames.append((frame, size))
        self._bytes += size
        while len(self._frames) > self.max_frames or (
            self._bytes > self.max_bytes and len(self._frames) > 1
        ):
            _evicted, evicted_size = self._frames.popleft()
            self._bytes -= evicted_size
            self._dropped += 1

    def since(self, cursor: int, *, limit: int = TRACE_PAGE_FRAMES) -> tuple[list[Json], int]:
        """Frames with ``seq > cursor``, and the cursor to pass back next time.

        The cursor is EXCLUSIVE and the returned one is the highest seq held
        plus one, so a caller that asks again with it gets nothing until
        something new arrives -- and a caller whose cursor has aged out of the
        ring gets the oldest retained frame rather than an error.
        """
        held = [frame for frame, _size in self._frames]
        fresh = [frame for frame in held if int(cast(int, frame["seq"])) > cursor]
        page = fresh[:limit]
        if held:  # noqa: SIM108
            nxt = int(cast(int, held[-1]["seq"])) + 1
        else:
            nxt = cursor + 1
        if page:
            nxt = int(cast(int, page[-1]["seq"])) + 1
        return page, nxt
