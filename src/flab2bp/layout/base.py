"""The frozen contract between the layout stage and the encoder.

A ``Placement`` is deliberately dumb: it is a flat list of buildings pinned to
integer grid coordinates, carrying no strategy-specific state.  That is what
lets a single validator judge every layout strategy and a single encoder
serialise them.

Coordinate system
-----------------
Layout works in **integer tile space** in ``x`` and ``y``: ``(x, y)`` is the
*minimum corner* of a building's footprint.  ``z`` is NOT a level index -- it is
the altitude in world units, tiles of height, exactly the number the game reads,
and it is a ``Fraction`` because a belt on a ramp rests at ``1/2``.  A strategy
that routes on an integer lattice converts at emission; see
:attr:`PlacedBuilding.z`.  Translating tile space into the float ``localOffset``
triple that DSP blueprints actually store -- including the centre-vs-corner
convention and the half-tile offsets that differ between odd- and even-sized
footprints -- is the encoder's job and happens in exactly one place.

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
from fractions import Fraction
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

    #: Altitude in blueprint WORLD units -- tiles of height, the number the game
    #: reads.  **Never a level index.**  It is a multiple of
    #: :data:`catalog.BELT_Z_QUANTUM`, so a belt halfway up a ramp is
    #: ``Fraction(1, 2)`` and NOT the integer level it is climbing from.  How
    #: high it may go is a property of the player's save, not a constant here.
    #:
    #: Writing a routing level index in here is what shipped belts the game drew
    #: red: ``freeform`` routes on an integer lattice and used to hand the
    #: lattice index straight to the encoder, so a belt went 0 -> 1 across ONE
    #: horizontal tile -- which is neither of the two changes the game allows,
    #: a ramp at half a tile of height per tile of run or a vertical step at a
    #: whole one for no run at all.  The lattice is still integers; the
    #: conversion is at emission and this field is what it converts INTO.
    #:
    #: ``Fraction`` rather than ``float`` so that ``1/2`` is exact and safe as a
    #: dict key: occupancy is keyed on ``(x, y, z)`` throughout.  It is also
    #: hash-compatible with ``int`` -- ``Fraction(0) == 0`` and the two hash
    #: alike -- so integer ground cells and ``Fraction`` ones share a key.
    z: Fraction = Fraction(0)
    width: int = 1
    height: int = 1
    yaw: float = 0.0

    #: Second anchor, used by buildings that span two tiles (sorters).  ``None``
    #: for everything else, in which case the encoder mirrors the first anchor.
    x2: int | None = None
    y2: int | None = None
    z2: Fraction | None = None
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

    def tiles(self) -> list[tuple[int, int, Fraction]]:
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


#: Seconds granted to a retry when the first attempt finds nothing feasible.
#:
#: The escalation is deliberately once, and generous.  If a spec is genuinely
#: solvable, a solver that found nothing in the normal budget will usually find
#: something here; if fifteen seconds still yields nothing, the working
#: assumption is a defect in our model rather than a hard instance, and the
#: error says so.  Treating it as "just a big problem" is how an unroutable
#: model gets excused indefinitely.
RETRY_BUDGET_S = 15.0


class NoValidLayout(Exception):
    """No layout satisfying the constraints was found.

    Raised instead of returning something invalid.  There used to be a fallback
    construction here, guaranteeing ``lay_out`` "always returns a valid
    Placement" -- a promise made so the bake-off would always have two things to
    compare.  It optimised for the measurement rather than the deliverable, and
    it was not even true: the fallback was never routable, so it returned
    neither a valid layout nor an honest failure.

    It also quietly softened the constraint it was meant to backstop.  A solver
    that knows something will catch it can afford to treat routability as a
    preference; with nothing to catch it, routability is what it should be --
    a condition for existing at all.

    The construction that used to serve as the fallback is now a warm start:
    same code, opposite role, bounding the search instead of replacing it.
    """

    def __init__(self, reason: str, *, spec_label: str = "", budget_s: float = 0.0) -> None:
        super().__init__(
            f"no valid layout for {spec_label or 'this spec'} after "
            f"{budget_s:g}s: {reason}. A spec that cannot be laid out in "
            f"{RETRY_BUDGET_S:g}s is more likely a defect in the layout model "
            f"than a hard instance -- treat it as our bug until shown otherwise."
        )
        self.reason = reason
        self.spec_label = spec_label
        self.budget_s = budget_s


class LayoutStrategy(Protocol):
    """What every layout backend implements.

    Implementations must be pure: same ``BuildSpec`` in, same ``Placement`` out,
    modulo the solver time budget.

    ``lay_out`` returns a placement that satisfies the constraints, or raises
    :class:`NoValidLayout`.  It never returns a degraded one.  On finding nothing
    feasible it retries ONCE at :data:`RETRY_BUDGET_S` before giving up.
    """

    name: str

    def lay_out(self, spec: BuildSpec, *, time_budget_s: float = 60.0) -> Placement:
        """Lay out ``spec``, returning the densest valid ``Placement`` found.

        Raises :class:`NoValidLayout` rather than returning a degraded result.
        The bake-off can only compare strategies that produce something, but the
        answer to that is to report the refusal as a refusal -- not to
        manufacture a placement so the table has a number in it.
        """
        ...
