"""The frozen contract between the layout stage and the encoder.

A ``Placement`` is deliberately dumb: it is a flat list of buildings pinned to
integer grid coordinates, carrying no strategy-specific state.  That is what
lets a single validator judge every layout strategy and a single encoder
serialise them.

Coordinate system
-----------------
Layout works in **integer tile space**.  ``(x, y)`` is the *minimum corner* of a
building's footprint, ``z`` is the altitude *level* (0 = ground).  Translating
tile space into the float ``localOffset`` triple that DSP blueprints actually
store -- including the centre-vs-corner convention and the half-tile offsets
that differ between odd- and even-sized footprints -- is the encoder's job and
happens in exactly one place.

Connections
-----------
``output_obj`` / ``input_obj`` are indices into ``Placement.buildings``.  The
encoder rewrites them into DSP's ``index`` space.  ``None`` means unconnected
and is encoded as ``-1``.

For a belt, ``output_obj`` names the next tile downstream; belt chains are
forward-linked only, matching what the game emits.  For a sorter, ``input_obj``
is where it picks up and ``output_obj`` is where it puts down.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from flab2bp.spec import BuildSpec


#: CP-SAT search workers for layout solves.  ``0`` lets CP-SAT use every core.
#:
#: This was pinned to 1 so the bake-off would be reproducible, which turned out
#: to cost real density rather than just speed: on the magnetic-ring spec,
#: 8 workers reach area 1435 where 1 worker plateaus at 1885 -- 23% worse.
#: Parallel CP-SAT runs a portfolio of differing strategies, so the extra
#: workers explore genuinely different regions rather than merely going faster.
#:
#: The bake-off deliberately does NOT pin this.  Pinning would make the
#: comparison reproducible and wrong -- it would measure both strategies under a
#: configuration neither would ship.  Solves take about a second, so the harness
#: absorbs the variance by repeating each cell and reporting median and spread.
#:
#: :data:`DETERMINISTIC_WORKERS` exists for the few tests that assert identical
#: output across runs, which is the one place reproducibility is the property
#: under test rather than an obstacle to measuring one.
DEFAULT_SEARCH_WORKERS = 0
DETERMINISTIC_WORKERS = 1


class Facing(Enum):
    """Cardinal direction in tile space, as a DSP yaw in degrees."""

    NORTH = 0.0
    EAST = 90.0
    SOUTH = 180.0
    WEST = 270.0

    @property
    def delta(self) -> tuple[int, int]:
        return {
            Facing.NORTH: (0, 1),
            Facing.EAST: (1, 0),
            Facing.SOUTH: (0, -1),
            Facing.WEST: (-1, 0),
        }[self]

    def opposite(self) -> Facing:
        return {
            Facing.NORTH: Facing.SOUTH,
            Facing.EAST: Facing.WEST,
            Facing.SOUTH: Facing.NORTH,
            Facing.WEST: Facing.EAST,
        }[self]


@dataclass(frozen=True, slots=True)
class PlacedBuilding:
    """One building pinned to the grid.

    ``item_id`` and ``model_index`` are DSP catalog ids.  ``width``/``height``
    are the build-grid footprint in tiles, cached here so geometry checks never
    need the catalog.
    """

    item_id: int
    model_index: int
    x: int
    y: int
    z: int = 0
    width: int = 1
    height: int = 1
    yaw: float = 0.0

    #: Second anchor, used by buildings that span two tiles (sorters).  ``None``
    #: for everything else, in which case the encoder mirrors the first anchor.
    x2: int | None = None
    y2: int | None = None
    z2: int | None = None
    yaw2: float | None = None

    recipe_id: int = 0
    filter_id: int = 0

    output_obj: int | None = None
    input_obj: int | None = None
    output_to_slot: int = 0
    input_from_slot: int = 0
    output_from_slot: int = 0
    input_to_slot: int = 0
    output_offset: int = 0
    input_offset: int = 0

    parameters: tuple[int, ...] = ()

    #: For a belt, the FactorioLab item id this lane carries; ``None`` elsewhere
    #: or when the strategy does not know.
    #:
    #: Not part of the DSP record -- it is layout knowledge that would otherwise
    #: be thrown away at emission and cannot be recovered afterwards.  Two things
    #: need it: the belt marker icons that label external inputs, and the
    #: validator's exact per-item max-flow check, which is currently unimplemented
    #: precisely because a ``Placement`` carried no lane labelling.
    carries_item: str | None = None

    def tiles(self) -> list[tuple[int, int, int]]:
        """Every grid cell this building's footprint occupies."""
        return [
            (self.x + dx, self.y + dy, self.z)
            for dx in range(self.width)
            for dy in range(self.height)
        ]


@dataclass(frozen=True, slots=True)
class Placement:
    """A complete, encodable layout."""

    buildings: tuple[PlacedBuilding, ...]
    #: Free-text provenance, surfaced in the blueprint description.
    description: str = ""
    short_desc: str = ""
    #: Item ids shown as the blueprint's icons, at most five.
    icons: tuple[int, ...] = ()
    #: Diagnostics from the strategy that produced this, for the bake-off.
    stats: dict[str, float] = field(default_factory=dict)

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        """``(min_x, min_y, max_x, max_y)`` inclusive of every footprint tile."""
        if not self.buildings:
            return (0, 0, 0, 0)
        xs = [b.x for b in self.buildings] + [b.x + b.width - 1 for b in self.buildings]
        ys = [b.y for b in self.buildings] + [b.y + b.height - 1 for b in self.buildings]
        return (min(xs), min(ys), max(xs), max(ys))

    @property
    def area(self) -> int:
        """Bounding-box area in tiles -- the bake-off's primary density metric."""
        min_x, min_y, max_x, max_y = self.bounds
        return (max_x - min_x + 1) * (max_y - min_y + 1)


class LayoutStrategy(Protocol):
    """What every layout backend implements.

    Implementations must be pure: same ``BuildSpec`` in, same ``Placement`` out,
    modulo the solver time budget.
    """

    name: str

    def lay_out(self, spec: BuildSpec, *, time_budget_s: float = 60.0) -> Placement:
        """Lay out ``spec``, returning the densest valid ``Placement`` found.

        Must always return a valid ``Placement``, even on solver timeout -- every
        strategy carries a guaranteed-feasible fallback construction, because the
        bake-off can only compare strategies that always produce something.
        """
        ...
