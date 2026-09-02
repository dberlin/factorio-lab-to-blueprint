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
from typing import TYPE_CHECKING, Protocol, TypedDict

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

#: Search stops at the requested wall. Once every net is wired, exact
#: compaction, projection, and certification may finish atomically under load.
ATOMIC_COMPLETION_GRACE_S = 5.0


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

    #: FactorioLab item id carried by a belt or moved by a sorter; ``None`` when
    #: the strategy does not know.
    #:
    #: Not part of the DSP record -- it is layout knowledge that would otherwise
    #: be thrown away at emission and cannot be recovered afterwards.  Belt
    #: markers, exact flow validation, and multi-product output-sorter filters
    #: all consume it before encoding.
    carries_item: str | None = None

    #: Packing provenance for exact projected-collision feedback.  This is not a
    #: DSP record field: the encoder ignores it, while layout may use it to map a
    #: rejected static object back to the strip origin that placed it.
    owner_strip: int | None = None

    def tiles(self) -> list[tuple[int, int, Fraction]]:
        """Every grid cell this building's footprint occupies."""
        return [
            (self.x + dx, self.y + dy, self.z)
            for dx in range(self.width)
            for dy in range(self.height)
        ]


@dataclass(frozen=True, slots=True)
class AreaFrame:
    """Finalized single-area dimensions and their certified latitude bands."""

    width: int
    height: int
    primary_band: int
    certified_bands: tuple[int, ...]
    rotated: bool

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("area frame dimensions must be positive")
        if not self.certified_bands:
            raise ValueError("area frame requires at least one certified band")
        if self.certified_bands[0] != self.primary_band:
            raise ValueError("area frame primary band must be the first certified band")


class PlacementCompletion(Enum):
    """Externally visible geometry has passed both completion transforms."""

    COMPACTED_AND_FINALIZED = "compacted-and-finalized"


class PlacementStats(TypedDict, total=False):
    """Complete cross-strategy schema for observational layout diagnostics."""

    accelerator: str
    accepted_moves: float
    anneal_stages: float
    archive_categories: list[str]
    archive_category: str
    area: float
    backend: str
    belt_tiles: float
    best_overflow: float
    best_stranded: float
    boundary_belts_removed: float
    boundary_cleanup_time_s: float
    box_area: float
    cache_hits: float
    compact_seed_attempt: float
    compact_seed_base_seed: int
    compact_seed_closure_backend: str
    compact_seed_closure_exact: float
    compact_seed_closure_status: str
    compact_seed_closures: float
    compact_seed_decoded_height: float
    compact_seed_decoded_width: float
    compact_seed_deterministic_time_s: float
    compact_seed_height: float
    compact_seed_solved_width: float
    compact_seed_status: str
    compact_seed_wall_time_s: float
    compilation_time_s: float
    corridor_tiles: float
    decoded_candidates: float
    detailed_expansions: float
    detailed_route_time_s: float
    detailed_routes: float
    direct_candidates: float
    direct_insert_candidates: float
    direct_inserts: float
    direct_sorters: float
    elevated_coater_routes: float
    expansion_allowance: float
    expansions: float
    fallback_reason: float
    fallback_used: float
    feedback_cells: float
    feedback_decays: float
    feedback_nets: float
    final_reserved: float
    gap_area: float
    global_expansions: float
    global_route_time_s: float
    global_routes: float
    global_skip_reason: str
    global_skips: float
    hard_outline_overflow: float
    height_waste: float
    heights: float
    history_cost: float
    hit_time_budget: float
    input_markers: int
    island_result_reserve_s: float
    islands_completed: float
    islands_refused: float
    islands_requested: float
    junctions: float
    last_mile_bounded: float
    last_mile_commit_rejected: float
    last_mile_expansions: float
    last_mile_invocations: float
    last_mile_nodes: float
    last_mile_proved: float
    last_mile_relation_skipped_siblings: float
    last_mile_relation_strips: float
    last_mile_restore_mismatch: float
    last_mile_seconds: float
    last_mile_solved: float
    lns_invocations: float
    lns_max_size: float
    lns_total_size: float
    machines: float
    max_quality_stagnation: float
    merge_count: float
    missed_direct_inserts: float
    moves: float
    nets: float
    objective_mode: str
    pack_width: float
    placement_time_s: float
    planning_time_s: float
    pose_count: float
    pose_feasibility_rejects: float
    pose_yaw_0: float
    pose_yaw_180: float
    pose_yaw_270: float
    pose_yaw_90: float
    power: float
    power_uncovered: float
    preparation_time_s: float
    quality_entries: float
    quality_exits: float
    quality_stages: float
    repair_iterations: float
    restarts: float
    riser_columns: float
    risers: float
    route_backend: str
    route_failures: float
    routed: float
    rows: float
    projection_collider_pairs: int
    projection_count: int
    projection_frame_candidates: int
    projection_power_pairs: int
    projection_sorters: int
    search_energy: float
    seed: int
    seeds: float
    shared_pack_candidates: float
    shared_pack_closures: float
    shared_pack_wall_time_s: float
    solver_rejected: float
    solver_status: float
    sorters: float
    split_count: float
    spray_coaters: float
    stages: float
    starved_taps: float
    strips: float
    target_height: float
    termination: str
    termination_cause: str
    topology_beam_candidates: float
    topology_beam_closures: float
    topology_beam_height: float
    topology_beam_wall_time_s: float
    total_time_s: float
    towers: float
    used_height: float
    validation_clean: float
    validation_status: str
    validation_time_s: float
    validator_clean: float
    variant_moves: float
    weighted_hpwl: float
    winner_island_id: int
    winner_island_seed: int


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
    stats: PlacementStats = field(default_factory=PlacementStats)
    #: Finalized area authority. ``None`` while geometry is still being laid out.
    frame: AreaFrame | None = None
    #: Explicit ownership handoff: pipeline completion is skipped only when set.
    completion: PlacementCompletion | None = None

    def __post_init__(self) -> None:
        if self.completion is not None and self.frame is None:
            raise ValueError("completed placement requires a finalized area frame")

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
        """Finalized frame area, or the search-time building-bounds area."""
        if self.frame is not None:
            return self.frame.width * self.frame.height
        min_x, min_y, max_x, max_y = self.bounds
        return (max_x - min_x + 1) * (max_y - min_y + 1)




@dataclass(frozen=True, slots=True)
class ProjectionFailureRecord:
    """Immutable, JSON-ready evidence for one authoritative projection refusal."""

    band: int
    check: str
    buildings: tuple[int, ...]
    detail: str


@dataclass(frozen=True, slots=True)
class LayoutAttemptFailure:
    """One candidate/strategy refusal with its projection evidence boundary."""

    candidate: str
    strategy: str | None
    reason: str
    projection_failures: tuple[ProjectionFailureRecord, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "projection_failures",
            tuple(dict.fromkeys(self.projection_failures)),
        )

    def __str__(self) -> str:
        pair = "/".join(part for part in (self.strategy, self.candidate) if part)
        return f"{pair}: {self.reason}" if pair else self.reason


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

    def __init__(
        self,
        reason: str,
        *,
        spec_label: str = "",
        budget_s: float = 0.0,
        attempt_reasons: tuple[str, ...] = (),
        attempt_failures: tuple[LayoutAttemptFailure, ...] = (),
        projection_failures: tuple[ProjectionFailureRecord, ...] = (),
    ) -> None:
        super().__init__(
            f"no valid layout for {spec_label or 'this spec'} after "
            f"{budget_s:g}s: {reason}. Treat a spec that cannot be laid out in "
            "the requested budget as a layout-model defect until shown otherwise."
        )
        self.reason = reason
        self.spec_label = spec_label
        self.budget_s = budget_s
        self.attempt_reasons = attempt_reasons
        self.attempt_failures = tuple(attempt_failures)
        self.projection_failures = tuple(dict.fromkeys(projection_failures))


class LayoutStrategy(Protocol):
    """What every layout backend implements.

    Implementations must be pure: same ``BuildSpec`` in, same ``Placement`` out,
    modulo the solver time budget.

    ``lay_out`` returns a placement that satisfies the constraints, or raises
    :class:`NoValidLayout`. It never returns a degraded one.
    """
    name: str

    def lay_out(self, spec: BuildSpec, *, time_budget_s: float = 15.0) -> Placement:
        """Lay out ``spec``, returning the densest valid ``Placement`` found.

        Raises :class:`NoValidLayout` rather than returning a degraded result.
        The bake-off can only compare strategies that produce something, but the
        answer to that is to report the refusal as a refusal -- not to
        manufacture a placement so the table has a number in it.
        """
        ...
