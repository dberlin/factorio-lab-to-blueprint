"""Strategy A -- structured spine with a CP-SAT arrangement.

The skeleton is *routable by construction*.  Machines live in rows; belts live in
corridors between rows; every lane an item could need has a reserved,
collision-free channel before the solver runs.  CP-SAT therefore only ever
chooses *how much* structure to spend, never *whether a route exists* -- there is
no place-then-route repair loop and no infeasible-placement dead end.

    corridor C0   ═══ external inputs ═══════════════ │
    row 0         [ smelter ][ smelter ][T]           │ ← riser margin
    corridor C1   ═══ iron-ingot ══════════════════╤══╡
    row 1         [ assembler ][ assembler ]       │  │
    corridor C2   ═══ iron-ingot ══════════════════╧══╡

Three structural facts do most of the work:

* **Rows hold machines, corridors hold belts**, so a Tesla tower placed in a row
  blocks no belt.  Power is just another block in the row's 1D packing.
* **A corridor lane is within sorter reach of every machine on both sides of it**,
  so a distribution problem costs one lane per corridor rather than one route per
  machine.  Proliferator and power both ride on this.
* **An item's copies in different corridors are joined by a trunk riser** in a
  margin east of the block.  Without one the copies are independent horizontal
  runs, which is what an earlier version of this docstring called "correct and
  routable" and what the validator called eleven ``flow.lane_sourced`` errors on
  one nine-group spec.  See :func:`_plan_risers`.

The riser margin is the whole area cost of joining the copies.  Trunks are
coloured like an interval graph, so their number is the deepest pile-up of
simultaneously live trunks -- 2 on graphene, 3 on processor, 4 on
casimir-crystal -- and the margin is twice that, because each trunk also gets
the ramp column a belt needs to change altitude at the speed a belt can.  It is
never taller than the block already was.  See :func:`_trunk_x`.

Deliberate scope reductions, each documented where it appears:

* All machines of a group share one row.
* Corridor lanes are never stacked: sorters cannot span altitudes, so a raised
  lane could not be tapped.  The one thing that does leave the ground is a
  riser's horizontal bridge, which only ever *crosses* another trunk -- see
  :data:`_BRIDGE_Z`.
* Machines sit at the top of their row, so a machine shorter than its row cannot
  always reach the corridor below it.  ``_lane_requirements`` allocates around
  that rather than moving the machine.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field, replace
from fractions import Fraction

from ortools.sat.python import cp_model

from flab2bp.dsp import catalog, params
from flab2bp.layout import junction
from flab2bp.layout.base import (
    DEFAULT_SEARCH_WORKERS,
    RETRY_BUDGET_S,
    Facing,
    NoValidLayout,
    PlacedBuilding,
    Placement,
)
from flab2bp.layout.geometry import band_offsets, height_waste, lane_order, reach_table
from flab2bp.spec import BuildSpec, MachineGroup

# --- lab id -> DSP item id -------------------------------------------------
# BuildSpec speaks FactorioLab's string ids; the catalog speaks DSP's integer
# item ids.  This adapter is the only place the two meet, exactly as the design
# intended -- if BuildSpec's shape changes, only this table and _adapt move.

MACHINE_ITEM_IDS: dict[str, int] = {
    "arc-smelter": 2302,
    "plane-smelter": 2315,
    "df-negentropy-smelter": 2319,
    "assembling-machine-1": 2303,
    "assembling-machine-2": 2304,
    "assembling-machine-3": 2305,
    "df-recomposing-assembler": 2318,
    "chemical-plant": 2309,
    "quantum-chemical-plant": 2317,
    "oil-refinery": 2308,
    "matrix-lab": 2901,
    "df-self-evolution-lab": 2902,
    "miniature-particle-collider": 2310,
    "fractionator": 2314,
    "energy-exchanger": 2209,
    "ray-receiver": 2208,
    "ray-receiver-pro": 2208,
    "orbital-collector": 2105,
    # Mining machines are cut upstream (ore arrives belted), but map them so a
    # spec that does include one fails on geometry rather than on a lookup.
    "mining-machine": 2301,
    "advanced-mining-machine": 2316,
    "water-pump": 2306,
    "oil-extractor": 2307,
}

BELT_ITEM_IDS: dict[str, int] = {
    "conveyor-belt-1": 2001,
    "conveyor-belt-2": 2002,
    "conveyor-belt-3": 2003,
}

#: Sorter tiers cheapest-first.  Reach is 3 for every tier (measured over 1,288
#: real sorters), so tiers differ only in throughput -- pick the cheapest that
#: carries the rate.
SORTER_TIERS = (2011, 2012, 2013, 2014)


@dataclass(frozen=True, slots=True)
class LayoutConstants:
    """Everything geometric, read from the catalog rather than hardcoded."""

    sorter_max_reach: int = catalog.SORTER_MAX_REACH
    tesla_item_id: int = catalog.TESLA_TOWER_ID
    supply_radius: Fraction = catalog.TESLA_COVER_RADIUS
    link_distance: Fraction = catalog.TESLA_LINK_DISTANCE
    spray_item_id: int = catalog.SPRAY_COATER_ID

    @property
    def tower_size(self) -> tuple[int, int]:
        b = catalog.building(self.tesla_item_id)
        return (b.width, b.height)


CONSTANTS = LayoutConstants()

#: Precomputed once: horizontal reach by vertical offset.
_REACH_TABLE = reach_table(CONSTANTS.supply_radius)


@dataclass(frozen=True, slots=True)
class _Group:
    """A ``MachineGroup`` resolved into DSP ids and tile geometry."""

    key: str
    recipe_id: str
    item_id: int
    model_index: int
    count: int
    width: int
    height: int
    inputs: dict[str, Fraction]
    outputs: dict[str, Fraction]
    proliferated: bool

    @property
    def block_width(self) -> int:
        return self.width * self.count


def proliferator_item(spec: BuildSpec) -> str | None:
    """The proliferator arriving on an input belt, if this build sprays at all.

    Proliferator is always belted in, never produced inside the blueprint, so it
    is found among the external inputs rather than among the groups.
    """
    if not spec.spray_lanes:
        return None
    return next(
        (i for i in sorted(spec.external_inputs) if i.startswith("proliferator")), None
    )


def _leaving_items(groups: dict[str, _Group], spec: BuildSpec) -> set[str]:
    """Items that must be belted out of the block: the targets AND the byproducts.

    ``spec.outputs`` names only what the build is *for*.  A recipe with two
    products emits the other one regardless -- ``plasma-refining`` yields refined
    oil and hydrogen -- and if nothing consumes it, ``_lane_requirements`` gave
    it no lane, so no sorter drained it and the machine backed up.  The
    validator's ``machine.output_removed`` says so in as many words, on graphene,
    plastic and energy-matrix.

    A byproduct is treated exactly like a target: a lane from its maker to the
    east edge, where the player belts it away or voids it.  That is the only
    honest option -- the alternative, leaving it unbelted, stalls the machine
    that makes the thing the build is actually for.
    """
    consumed = {item for g in groups.values() for item in g.inputs}
    produced = {item for g in groups.values() for item in g.outputs}
    return set(spec.outputs) | (produced - consumed)


@dataclass(frozen=True, slots=True)
class _Edge:
    """``item`` flowing from group ``src`` to group ``dst`` at ``rate`` items/s."""

    src: str
    dst: str
    item: str
    rate: Fraction


@dataclass
class _Plan:
    """Row assignment and lane assignment -- everything before coordinates."""

    rows: list[list[str]]
    lanes: list[list[str]] = field(default_factory=list)
    direct: set[tuple[str, str, str]] = field(default_factory=set)
    solver_status: str = "fallback"
    hit_budget: bool = False


def _adapt(spec: BuildSpec) -> tuple[dict[str, _Group], list[_Edge]]:
    """Resolve a ``BuildSpec`` into DSP-id groups and a producer/consumer graph."""
    groups: dict[str, _Group] = {}
    for i, mg in enumerate(spec.groups):
        item_id = MACHINE_ITEM_IDS.get(mg.machine_item_id)
        if item_id is None:
            raise KeyError(f"no DSP building known for machine {mg.machine_item_id!r}")
        b = catalog.building(item_id)
        key = f"{mg.recipe_id}#{i}"
        groups[key] = _Group(
            key=key,
            recipe_id=mg.recipe_id,
            item_id=item_id,
            model_index=b.model_index,
            count=mg.count,
            width=b.width,
            height=b.height,
            inputs=dict(mg.inputs_per_machine),
            outputs=dict(mg.outputs_per_machine),
            proliferated=mg.is_proliferated,
        )

    producers: dict[str, list[str]] = defaultdict(list)
    for key, g in groups.items():
        for item in g.outputs:
            producers[item].append(key)

    edges: list[_Edge] = []
    for key, g in groups.items():
        for item, per_machine in g.inputs.items():
            demand = per_machine * g.count
            if demand <= 0:
                continue
            sources = producers.get(item, [])
            if not sources:
                continue  # external input; enters on corridor C0
            # Split demand evenly across producers of the item.
            share = demand / len(sources)
            for src in sources:
                if src != key:
                    edges.append(_Edge(src=src, dst=key, item=item, rate=share))
    return groups, edges


def _topological_rows(groups: dict[str, _Group], edges: list[_Edge]) -> list[list[str]]:
    """One group per row, producers strictly above consumers.

    Raises on a cycle rather than silently mis-ordering rows.
    """
    incoming: dict[str, set[str]] = {k: set() for k in groups}
    outgoing: dict[str, set[str]] = {k: set() for k in groups}
    for e in edges:
        if e.src in groups and e.dst in groups:
            incoming[e.dst].add(e.src)
            outgoing[e.src].add(e.dst)

    ready = sorted(k for k, deps in incoming.items() if not deps)
    order: list[str] = []
    remaining = {k: set(v) for k, v in incoming.items()}
    while ready:
        key = ready.pop(0)
        order.append(key)
        for nxt in sorted(outgoing[key]):
            remaining[nxt].discard(key)
            if not remaining[nxt] and nxt not in order and nxt not in ready:
                ready.append(nxt)
    if len(order) != len(groups):
        cyclic = sorted(set(groups) - set(order))
        raise ValueError(f"recipe graph is cyclic; cannot order rows: {cyclic}")
    return [[k] for k in order]


def _row_index(rows: list[list[str]]) -> dict[str, int]:
    return {key: r for r, row in enumerate(rows) for key in row}


def _fits_below(
    slot: set[str], item: str, gaps: dict[str, int], reach: int, copies: dict[str, int]
) -> bool:
    """Could the corridor BELOW a row take ``item`` as well and stay tappable?

    Lane ``j`` of the corridor below sits ``gap + j + 1`` tiles from a machine
    whose bottom edge is ``gap`` above its row's floor.  The slot's lanes are
    emitted worst-gap-first -- see ``_lane_requirements``, which sorts the
    corridor's top band the same way -- so the shortest machine gets the shallow
    lane and the check is exactly that greedy assignment being feasible.

    Charging the worst gap to the whole slot instead would be far too strict: a
    corridor happily holds three lanes for a gap of 2 (spans 3, 2, 3) where a
    flat ``reach - gap`` cap allows one.

    An item needing ``copies[item]`` parallel lanes takes that many slots, not
    one.  Counting items rather than lanes here would let the allocation accept a
    band ``lane_order`` then refuses, which shows up as the whole width being
    skipped rather than as anything nameable.
    """
    combined = sorted(
        (gaps.get(i, 0) for i in {*slot, item} for _ in range(copies.get(i, 1))),
        reverse=True,
    )
    return all(g + j + 1 <= reach for j, g in enumerate(combined))


def belt_capacity(spec: BuildSpec) -> Fraction:
    """Items per second one belt of this build's tier sustains."""
    return catalog.BELT_RATE.get(BELT_ITEM_IDS.get(spec.belt_item_id, 2001), Fraction(6))


def _lane_copies(
    groups: dict[str, _Group],
    edges: list[_Edge],
    direct: set[tuple[str, str, str]],
    spec: BuildSpec,
) -> dict[str, int]:
    """Parallel lanes each item needs, so no belt is asked to carry too much.

    A belt is one pipe.  Putting an item's whole flow on a single lane -- and on
    the single trunk that joins that lane's copies -- silently caps the build at
    the belt's rate, which is the same failure mode as an undersized sorter:
    it pastes, it runs, and it misses the number the spec promised.

    Measured on the corpus this is not hypothetical.  ``quantum-chip`` moves
    48 crude-oil/s and 48 refined-oil/s where a Mk.III belt sustains 30, and
    ``flow.belt_capacity`` reports both on every candidate that reaches them.

    The count is per ITEM rather than per corridor on purpose.  A trunk joins
    copy ``k`` of a lane in one corridor to copy ``k`` in another, so the copies
    have to exist in matching numbers at both ends; letting a shallow corridor
    hold fewer would leave the extra trunks with nothing to drain into.  The
    price is a lane a corridor does not strictly need, and it is only paid by
    items that overflow a belt at all -- one item in twelve corpus builds.
    """
    cap = belt_capacity(spec)
    supply: dict[str, Fraction] = defaultdict(Fraction)
    demand: dict[str, Fraction] = defaultdict(Fraction)
    for g in groups.values():
        for item, rate in g.outputs.items():
            supply[item] += rate * g.count
        for item, rate in g.inputs.items():
            demand[item] += rate * g.count
    for item, rate in spec.external_inputs.items():
        supply[item] += rate
    for item, rate in spec.outputs.items():
        demand[item] += rate
    # A direct-inserted edge never touches a belt, so its rate is not on any lane.
    for e in edges:
        if (e.src, e.dst, e.item) in direct:
            supply[e.item] -= e.rate
            demand[e.item] -= e.rate
    return {
        item: max(1, math.ceil(max(supply[item], demand.get(item, Fraction(0))) / cap))
        for item in set(supply) | set(demand)
    }


def _lane_requirements(
    groups: dict[str, _Group],
    edges: list[_Edge],
    rows: list[list[str]],
    direct: set[tuple[str, str, str]],
    spec: BuildSpec,
) -> tuple[list[list[str]], dict[str, int]]:
    """Corridor lanes, and how many parallel copies each item ended up with.

    Splitting an over-capacity item across parallel lanes deepens a corridor,
    and a corridor deep enough to put a lane out of sorter reach cannot be wired
    at all.  When that happens the split is given up rather than the spec: one
    lane and an honest ``flow.belt_capacity`` error from the validator is worth
    more than a refusal, because a build that is reported as too slow can still
    be pasted and widened by hand, and a build that does not exist cannot.

    Measured: without this retry, splitting ``quantum-chip``'s 48/s crude-oil and
    refined-oil onto two lanes each made the no-proliferator candidate refuse
    outright -- trading two reported errors for a whole missing layout.
    """
    wanted = _lane_copies(groups, edges, direct, spec)
    if any(v > 1 for v in wanted.values()):
        try:
            return _allocate_lanes(groups, edges, rows, direct, spec, wanted), wanted
        except ValueError:
            pass
    flat = dict.fromkeys(wanted, 1)
    return _allocate_lanes(groups, edges, rows, direct, spec, flat), flat


def _allocate_lanes(
    groups: dict[str, _Group],
    edges: list[_Edge],
    rows: list[list[str]],
    direct: set[tuple[str, str, str]],
    spec: BuildSpec,
    copies: dict[str, int],
) -> list[list[str]]:
    """Which item occupies a lane in which corridor, ordered by sorter reach.

    Corridor ``c`` sits above row ``c``.  **A corridor holds exactly the lanes it
    is tapped for**, plus the proliferator utility lane.

    That is a consequence of risers, and it used not to be.  Before them, an edge
    from row ``r`` to row ``s`` took a lane in every corridor ``r+1 .. s``,
    because a horizontal run in each corridor was the only way for the item to
    travel down the block.  A riser joins the copies through the east margin
    instead, so the intermediate copies stopped carrying anything the moment
    :func:`_plan_risers` landed -- and :func:`_plan_risers` skips them precisely
    because nothing fills or drains them.

    They were not free.  Measured over the 33 powered corpus runs while they were
    still emitted: **321 of 975 lanes were pass-through, holding 34,372 of 80,620
    lane belt tiles** -- 43% of all lane belt was joined to nothing at either end.
    And a lane is a tile of corridor height, so they cost *area*, not just
    buildings.
    """
    at = _row_index(rows)
    n_corr = len(rows) + 1
    reach = CONSTANTS.sorter_max_reach

    # item -> set of corridors it must cross, and where it is tapped.
    crossing: list[set[str]] = [set() for _ in range(n_corr)]
    tap_above: list[set[str]] = [set() for _ in range(n_corr)]
    tap_below: list[set[str]] = [set() for _ in range(n_corr)]
    #: How far the machine tapping corridor ``c`` from ABOVE stops short of its
    #: row's floor.  Sets the order of the corridor's top band: worst gap gets
    #: the shallowest lane, which is what ``_fits_below`` assumes when it decides
    #: the band can hold one more.
    above_gap: list[dict[str, int]] = [{} for _ in range(n_corr)]

    # What each row consumes and produces.  There is deliberately no corridor
    # *span* here any more: a lane is needed where it is tapped and nowhere else,
    # and the trunk carries the item between those points.
    consumes: list[set[str]] = [set() for _ in rows]
    produces: list[set[str]] = [set() for _ in rows]

    for e in edges:
        if (e.src, e.dst, e.item) in direct:
            continue
        produces[at[e.src]].add(e.item)
        consumes[at[e.dst]].add(e.item)

    for item in spec.external_inputs:
        for r in (at[k] for k, g in groups.items() if item in g.inputs):
            consumes[r].add(item)

    for item in _leaving_items(groups, spec):
        sources = [at[k] for k, g in groups.items() if item in g.outputs]
        if sources:
            produces[min(sources)].add(item)

    # A machine presents edge tiles to the corridor above *and* the one below, so
    # a row with more taps than one corridor can reach spills into the other.
    # This is what lets a row hold several groups at once -- without it the
    # solver's denser row packings are silently unroutable.
    #
    # Row ``r`` owns exactly two tap slots and shares them with nobody:
    # ``tap_below[r]`` (corridor r, above the row) and ``tap_above[r + 1]``
    # (corridor r + 1, below it).  Each holds at most ``reach`` lanes.
    #
    # The allocation has to be JOINT across consumes and produces.  Assigning
    # each stream its own near/far independently let both overflow into the same
    # slot: on a real 16-group spec, corridor 0 took three consumed items at its
    # preference plus two produced items spilling the other way, for five taps
    # against a reach of three -- so every width in the sweep raised and the
    # whole strategy silently degraded to its greedy fallback.
    for r in range(len(rows)):
        slot_below: set[str] = set()  # corridor r, tapped from below by this row
        slot_above: set[str] = set()  # corridor r + 1, tapped from above by it
        # Machines are pinned to the TOP of their row, and a row is as tall as
        # its tallest group, so a short group stops short of the row's bottom
        # edge -- a 3-tall smelter sharing a row with a 7-tall refinery ends four
        # tiles above the floor.  Its top edge is still flush, so the corridor
        # ABOVE costs it nothing, but every lane in the corridor BELOW is that
        # gap further away.  ``_fits_below`` decides what that leaves room for,
        # and the corridor's top band is ordered worst-gap-first to match.
        #
        # Getting this wrong is silent in the worst way: the lane is allocated
        # below, `_find_tap` correctly refuses to wire something out of reach,
        # and the machine simply gets no sorter for that item at all.  That is
        # how graphene, plastic, energy-matrix and casimir-crystal each ended up
        # with a smelter nothing drained.
        row_h = max((groups[k].height for k in rows[r]), default=1)
        gaps: dict[str, int] = {}
        for k in rows[r]:
            gap = row_h - groups[k].height
            for item in set(groups[k].inputs) | set(groups[k].outputs):
                gaps[item] = max(gaps.get(item, 0), gap)

        prefers_above: dict[str, bool] = dict.fromkeys(sorted(consumes[r]), True)
        for item in sorted(produces[r]):
            prefers_above.setdefault(item, False)
        # Most constrained first: an item whose tapper is short has fewer places
        # it can go, so it has to choose before the ones that can go anywhere.
        for item in sorted(prefers_above, key=lambda i: (-gaps.get(i, 0), i)):
            top_ok = (
                sum(copies.get(i, 1) for i in slot_below) + copies.get(item, 1) <= reach
            )
            bottom_ok = _fits_below(slot_above, item, gaps, reach, copies)
            if prefers_above[item]:
                target = slot_below if top_ok else (slot_above if bottom_ok else None)
            else:
                target = slot_above if bottom_ok else (slot_below if top_ok else None)
            if target is None:
                raise ValueError(
                    f"row {r} taps {len(consumes[r] | produces[r])} distinct items, "
                    f"exceeding what its two corridors can reach"
                )
            target.add(item)
        for c, slot_items in ((r, slot_below), (r + 1, slot_above)):
            if not 0 <= c < n_corr:
                continue
            for item in slot_items:
                if c == r:
                    tap_below[c].add(item)
                else:
                    tap_above[c].add(item)
                    above_gap[c][item] = gaps.get(item, 0)

    for c in range(n_corr):
        crossing[c] |= tap_above[c] | tap_below[c]

    # The proliferator utility lane.  Spray Coaters mount on the lanes they
    # spray, so the proliferator that feeds them has to reach into the same
    # corridor -- one lane per corridor serves every coater in it, which is the
    # whole reason this skeleton suits proliferation.  It taps no machine row,
    # so it is pass-through and `lane_order` is free to place it anywhere.
    # Only corridors that actually carry a sprayed lane need it.  Adding it
    # everywhere made every corridor a tile taller, which on a deeper spec
    # pushed a machine row outside any tower's supply radius and aborted the
    # layout -- height in this skeleton is never free.
    prolif = proliferator_item(spec)
    if prolif is not None:
        sprayed = set(spec.spray_lanes)
        for c in range(n_corr):
            if crossing[c] & sprayed:
                crossing[c].add(prolif)

    ordered: list[list[str]] = []
    for c in range(n_corr):
        # Worst gap shallowest: a machine that stops two tiles above its row's
        # floor can only reach the corridor's first lane or two, so it takes one.
        # Expanded to one entry per parallel lane, so every downstream consumer
        # -- reach checks, depth indices, riser planning -- counts lanes rather
        # than items and the two can never disagree.
        def _lanes(items: list[str]) -> list[str]:
            return [i for i in items for _ in range(copies.get(i, 1))]

        above = _lanes(
            sorted(tap_above[c] & crossing[c], key=lambda i: (-above_gap[c].get(i, 0), i))
        )
        below = _lanes(sorted(tap_below[c] & crossing[c]))
        through = _lanes(sorted(crossing[c] - set(above) - set(below)))
        order = lane_order(above, below, through, reach)
        if order is None:
            raise ValueError(
                f"corridor {c} needs {len(above)} taps above and {len(below)} below, "
                f"exceeding sorter reach {reach}"
            )
        if prolif is not None and prolif in order:
            order = _cover_sprayed(
                order, prolif, set(spec.spray_lanes), len(above), len(below), reach
            )
        ordered.append(order)
    return ordered


def _cover_sprayed(
    order: list[str], prolif: str, sprayed: set[str], n_above: int, n_below: int, reach: int
) -> list[str]:
    """Add proliferator copies until every sprayed item has a coatable lane.

    ``lane_order`` puts the pass-through lanes -- proliferator among them -- in
    the middle, between the band the row above taps and the band the row below
    taps.  On a boundary corridor there is no band above, so the proliferator
    lands at depth 0 while the sprayed lanes sit five or six tiles down, and no
    sorter reaches from one to the other: ``prolif.coaters_are_supplied``, on
    graphene and casimir-crystal.

    A copy may only be inserted at a BAND BOUNDARY.  Taps into the band above
    are measured from the corridor's top edge and taps into the band below from
    its bottom, so an insert between the two moves neither -- while an insert
    inside a band would push its far lane out of reach and break the very thing
    that made the corridor routable.  Both boundaries are within ``reach`` of
    their whole band, since a band is at most ``reach`` lanes deep, so at most
    two copies settle any corridor.
    """

    def uncovered(lanes: list[str]) -> set[str]:
        spots = [j for j, i in enumerate(lanes) if i == prolif]
        reachable = {
            i
            for j, i in enumerate(lanes)
            if any(1 <= abs(j - p) <= reach for p in spots)
        }
        return {i for i in lanes if i in sprayed} - reachable

    for cut in (len(order) - n_below, n_above):
        if not uncovered(order):
            break
        order = [*order[:cut], prolif, *order[cut:]]
    return order


def fallback_plan(spec: BuildSpec) -> _Plan:
    """Deterministic, always-*constructible*: one group per row, no direct inserts.

    Named for the role it used to have.  It is no longer a fallback -- returning
    it when the solver found nothing was returning something that had never been
    checked for routability, and usually was not.  Its real value was always the
    other two jobs it does, which it keeps: the CP-SAT warm start in
    :func:`_solve_one` and the width-sweep seed in :func:`_candidate_widths`.
    Because it runs on every solve, it cannot rot.
    """
    groups, edges = _adapt(spec)
    rows = _topological_rows(groups, edges)
    lanes, _copies = _lane_requirements(groups, edges, rows, set(), spec)
    return _Plan(rows=rows, lanes=lanes, solver_status="fallback")


#: Why no solved plan was produced.  These began as fallback *reasons*, reported
#: as ``stats["fallback_reason"]`` on a degraded placement; the degradation is
#: gone and they are now refusal reasons, carried in the :class:`NoValidLayout`
#: message instead.  The distinction they draw is what earns them their keep:
#: three different failure modes used to be indistinguishable behind
#: ``fallback_used=1``, which is how a strategy that had stopped solving entirely
#: on real specs went unnoticed.  The names are unchanged so the existing
#: ``fallback_reason`` stat, which still marks a solved plan as such, keeps its
#: meaning.
FALLBACK_NONE = 0.0  # a solved plan was used; nothing to report
FALLBACK_NO_BUDGET = 1.0  # time_budget_s <= 0, so the solver was never asked
FALLBACK_EMPTY_SPEC = 2.0  # nothing to lay out
FALLBACK_UNROUTABLE = 3.0  # every candidate width packed rows that cannot be wired
FALLBACK_NO_SOLUTION = 4.0  # CP-SAT found neither OPTIMAL nor FEASIBLE
FALLBACK_EMISSION = 5.0  # a plan solved, but emitting it raised

_REFUSAL_TEXT = {
    FALLBACK_NO_BUDGET: "no time budget was given, so the solver was never asked",
    FALLBACK_EMPTY_SPEC: "the spec contains no machine groups",
    FALLBACK_UNROUTABLE: (
        "every candidate width packed rows that no sorter could wire "
        "(a structural limit in the row model, not a search failure)"
    ),
    FALLBACK_NO_SOLUTION: "CP-SAT found no feasible row assignment at any candidate width",
    FALLBACK_EMISSION: "a plan solved but could not be emitted onto the grid",
}


def _refusal(reason: float) -> str:
    return _REFUSAL_TEXT.get(reason, f"unknown reason {reason}")


def _solve_plan(
    spec: BuildSpec, *, time_budget_s: float, workers: int
) -> tuple[_Plan | None, float]:
    """Pack groups into rows and choose direct inserts, minimising area.

    Area is ``W * H``, a variable product with a weak relaxation, so instead of
    ``AddMultiplicationEquality`` we sweep candidate widths and minimise ``H``
    under each -- a handful of easy solves rather than one hard one.
    """
    groups, edges = _adapt(spec)
    base = fallback_plan(spec)
    order = [row[0] for row in base.rows]
    depth = {key: i for i, key in enumerate(order)}
    n = len(order)
    if n == 0:
        return None, FALLBACK_EMPTY_SPEC

    widths = _candidate_widths(groups, base)
    best: _Plan | None = None
    best_area = math.inf
    per_solve = max(time_budget_s / max(len(widths), 1), 0.25)
    unroutable = 0

    for w_cap in widths:
        try:
            plan = _solve_one(spec, groups, edges, depth, n, w_cap, per_solve, workers)
        except ValueError:
            # This width produced a row packing that cannot be routed within
            # sorter reach.  Skip it and keep sweeping rather than abandoning
            # every remaining width.
            unroutable += 1
            continue
        if plan is None:
            continue
        area = _measure(spec, plan)
        if area < best_area:
            best_area, best = area, plan
    if best is not None:
        return best, FALLBACK_NONE
    # Distinguish "packed rows nothing could wire" from "CP-SAT found nothing",
    # because they call for opposite fixes: the first is a structural limit in
    # the model, the second a search or feasibility problem.
    return None, FALLBACK_UNROUTABLE if unroutable else FALLBACK_NO_SOLUTION


def _candidate_widths(groups: dict[str, _Group], base: _Plan) -> list[int]:
    """Descending widths to sweep, seeded from the fallback's own width."""
    widest = max((g.block_width for g in groups.values()), default=1)
    total = sum(g.block_width for g in groups.values())
    seed = max(widest, total)
    out: list[int] = []
    w = seed
    while w >= widest and len(out) < 8:
        out.append(w)
        w = int(w * 0.7)
    if widest not in out:
        out.append(widest)
    return out


def _solve_one(
    spec: BuildSpec,
    groups: dict[str, _Group],
    edges: list[_Edge],
    depth: dict[str, int],
    n: int,
    w_cap: int,
    budget_s: float,
    workers: int,
) -> _Plan | None:
    """One CP-SAT solve: assign groups to rows, minimise total height."""
    model = cp_model.CpModel()
    keys = list(groups)
    row = {k: model.new_int_var(0, n - 1, f"row_{k}") for k in keys}

    # Preserve topological order; producers strictly above consumers.
    for e in edges:
        if e.src in row and e.dst in row:
            model.add(row[e.src] < row[e.dst])

    # in_row[k][r] reifies the assignment so widths and heights can be summed.
    in_row: dict[tuple[str, int], cp_model.IntVar] = {}
    for k in keys:
        flags = []
        for r in range(n):
            b = model.new_bool_var(f"in_{k}_{r}")
            model.add(row[k] == r).only_enforce_if(b)
            model.add(row[k] != r).only_enforce_if(~b)
            in_row[k, r] = b
            flags.append(b)
        model.add_exactly_one(flags)

    max_h = max(g.height for g in groups.values())
    row_w, row_h = [], []
    for r in range(n):
        ww = model.new_int_var(0, w_cap, f"ww_{r}")
        model.add(ww == sum(groups[k].block_width * in_row[k, r] for k in keys))
        hh = model.new_int_var(0, max_h, f"hh_{r}")
        for k in keys:
            model.add(hh >= groups[k].height * in_row[k, r])
        row_w.append(ww)
        row_h.append(hh)

    # --- tap capacity ------------------------------------------------------
    # Row r reaches exactly two corridors -- r from below and r+1 from above --
    # each holding at most ``sorter_max_reach`` lanes.  So a row can tap at most
    # ``2 * reach`` DISTINCT items, counting an item once however many groups in
    # the row touch it.
    #
    # This has to live in the model.  Without it CP-SAT freely packed five
    # groups into one row, `_lane_requirements` correctly refused the result,
    # and `_solve_plan` skipped every width in the sweep and returned None --
    # so the strategy fell back to its greedy layout on every real spec while
    # reporting only `fallback_used=1`.  Rejecting after the fact cannot work
    # here: routability is a property of the packing, so the packer has to know.
    tap_reach = CONSTANTS.sorter_max_reach
    lane_copies = _lane_copies(groups, edges, set(), spec)
    tapped_by: dict[str, list[str]] = defaultdict(list)
    for k, g in groups.items():
        for item in set(g.inputs) | set(g.outputs):
            tapped_by[item].append(k)
    for r in range(n):
        # Weighted by parallel-lane count, because the budget is LANES.  An item
        # that needs two lanes to carry its rate takes two of the row's slots,
        # and pricing it at one let the solver pack rows whose split
        # `_lane_requirements` then had to abandon -- silently putting the flow
        # back on one belt.  Measured on quantum-chip, where crude-oil and
        # refined-oil each move 48/s against a 30/s belt.
        terms = []
        for item, holders in tapped_by.items():
            t = model.new_bool_var(f"tap_{r}_{item}")
            model.add_max_equality(t, [in_row[k, r] for k in holders])
            terms.append(lane_copies.get(item, 1) * t)
        if terms:
            model.add(sum(terms) <= 2 * tap_reach)

    # --- direct insertion --------------------------------------------------
    # A producer within sorter reach of its consumer is joined by a sorter alone,
    # so the edge needs no lane at all.  There is deliberately no reward term for
    # this in the objective: dropping the lane shrinks a corridor, and corridors
    # are already counted in the height being minimised.  A separate bonus would
    # be a proxy competing with the real metric, which is exactly the mistake
    # that made Strategy B's objective anti-correlated with its own area.
    reach = CONSTANTS.sorter_max_reach
    di: dict[tuple[str, str, str], cp_model.IntVar] = {}
    for e in edges:
        ek = (e.src, e.dst, e.item)
        if ek in di:
            continue
        d = model.new_bool_var(f"di_{e.src}_{e.dst}_{e.item}")
        di[ek] = d
        recipes = (groups[e.src].recipe_id, groups[e.dst].recipe_id)
        # A proliferated consumer's input is sprayed by a belt-mounted coater, so
        # it MUST arrive belted; direct-inserting it would paste cleanly and then
        # silently under-produce.
        #
        # `spray_lanes` is checked as well as `belt_required_edges`, not instead:
        # an item that needs a coater needs a belt for the coater to sit on, and
        # deriving that here means a caller cannot violate the physical
        # constraint by setting one field and forgetting the other.
        if recipes in spec.belt_required_edges or e.item in spec.spray_lanes:
            model.add(d == 0)
            continue
        # Only adjacent rows can be within reach of one another.
        model.add(row[e.dst] == row[e.src] + 1).only_enforce_if(d)

    def _reified(var: cp_model.IntVar, bound: int, *, less: bool) -> cp_model.IntVar:
        """A bool that is true exactly when ``var < bound`` (or ``>=``).

        Both directions are enforced.  Enforcing only the true branch would let
        the solver read any lane as absent and minimise a fiction.
        """
        b = model.new_bool_var("")
        if less:
            model.add(var < bound).only_enforce_if(b)
            model.add(var >= bound).only_enforce_if(~b)
        else:
            model.add(var >= bound).only_enforce_if(b)
            model.add(var < bound).only_enforce_if(~b)
        return b

    # A corridor's height is its lane count.
    leaving = _leaving_items(groups, spec)
    lane_items = sorted({e.item for e in edges} | set(spec.external_inputs) | leaving)
    corridor_h = []
    for c in range(n + 1):
        used = []
        for item in lane_items:
            contribs: list[cp_model.IntVar] = []
            for e in edges:
                if e.item != item:
                    continue
                # Crosses corridor c iff src is above it, dst is at or below it,
                # and the edge was not direct-inserted.
                a = _reified(row[e.src], c, less=True)
                z = _reified(row[e.dst], c, less=False)
                d = di[e.src, e.dst, e.item]
                x = model.new_bool_var("")
                model.add_bool_and([a, z, ~d]).only_enforce_if(x)
                model.add_bool_or([~a, ~z, d]).only_enforce_if(~x)
                contribs.append(x)
            if item in spec.external_inputs:
                # Enters at the top and runs down to its deepest consumer.
                for k, g in groups.items():
                    if item in g.inputs:
                        contribs.append(_reified(row[k], c, less=False))
            if item in leaving:
                # Leaves at the bottom, so it occupies corridors below its maker.
                for k, g in groups.items():
                    if item in g.outputs:
                        contribs.append(_reified(row[k], c, less=True))
            b = model.new_bool_var(f"lane_{c}_{item}")
            if contribs:
                model.add_max_equality(b, contribs)
            else:
                model.add(b == 0)
            used.append(b)
        # Weighted by parallel-lane count: an item that overflows a belt costs
        # the corridor a tile per copy, and a model that priced it at one would
        # pick row assignments whose real height it had never seen.
        ch = model.new_int_var(0, sum(lane_copies.values()), f"corr_{c}")
        model.add(
            ch
            == sum(
                lane_copies.get(i, 1) * b
                for i, b in zip(lane_items, used, strict=True)
            )
        )
        corridor_h.append(ch)

    # A direct insert spans the corridor between the two rows, so that corridor
    # must be shallow enough for a sorter to cross it: the span is its lane count
    # plus one.
    for (src, _dst, _item), d in di.items():
        for r in range(n - 1):
            model.add(corridor_h[r + 1] <= reach - 1).only_enforce_if([d, in_row[src, r]])

    total_h = model.new_int_var(0, (max_h + len(lane_items)) * (n + 1), "H")
    model.add(total_h == sum(row_h) + sum(corridor_h))
    model.minimize(total_h)

    # Warm start from the fallback so the sweep is monotone by construction.
    for k in keys:
        model.add_hint(row[k], depth[k])

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = budget_s
    # Multi-worker CP-SAT is not deterministic, and the bake-off compares
    # strategies -- reproducibility outweighs the speedup.
    solver.parameters.num_search_workers = workers
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    buckets: dict[int, list[str]] = defaultdict(list)
    for k in keys:
        buckets[solver.value(row[k])].append(k)
    rows = [sorted(buckets[r]) for r in sorted(buckets)]
    direct = {ek for ek, d in di.items() if solver.value(d)}
    lanes, _copies = _lane_requirements(groups, edges, rows, direct, spec)
    return _Plan(
        rows=rows,
        lanes=lanes,
        direct=direct,
        solver_status=solver.status_name(status),
        hit_budget=status == cp_model.FEASIBLE,
    )


def _measure(spec: BuildSpec, plan: _Plan) -> int:
    groups, _ = _adapt(spec)
    heights = [max((groups[k].height for k in r), default=0) for r in plan.rows]
    widths = [sum(groups[k].block_width for k in r) for r in plan.rows]
    h = sum(heights) + sum(len(c) for c in plan.lanes)
    return max(widths, default=1) * h


def _pick_sorter(rate: Fraction, span: int, available: int) -> tuple[int, int] | None:
    """Cheapest tier and per-machine count carrying ONE ITEM's ``rate``.

    ``rate`` is what a single machine consumes (or produces) of the single item
    this feed moves -- not the machine's total across its ingredients.

    Sizing against the average was a real under-build, and a self-concealing
    one.  A machine's ingredients have different rates: ``electric-motor`` takes
    iron-ingot, gear and magnetic-coil, and charging each feed the mean lets the
    hot ingredient's sorter come up short while the cold one's is oversized, so
    the pair averages out to something that reads as fine.  The starved sorter
    then throttles the machine, the build pastes and runs, and it quietly misses
    its rate.  Measured on the example URL: 12 sorters asked for 1 item/s of
    iron-ingot across 2 tiles, where a Mk.I sustains 3/4.

    Prefers the fewest sorters, then the cheapest tier: extra sorters are extra
    buildings to paste, while a higher tier costs nothing spatially.  Note a
    longer span costs throughput linearly (``rate_at_1 / span``), so shortening
    a span is as valid a remedy as upgrading a tier, and usually cheaper.
    """
    if rate <= 0:
        return SORTER_TIERS[0], 1
    for count in range(1, max(1, available) + 1):
        share = rate / count
        for tier in SORTER_TIERS:
            if catalog.sorter_rate(tier, span) >= share:
                return tier, count
    return None


def _share(machines: list[int], lanes: int, j: int, rota: int = 0) -> list[int]:
    """The machines of a group that use parallel lane ``j`` of ``lanes``.

    Dealt round-robin so each lane gets as near an equal share of the group's
    rate as the machine count allows -- which is what keeps every lane inside a
    belt once :func:`_lane_copies` has decided how many there are.

    ``rota`` rotates where the deal STARTS, and it is what stops the remainders
    stacking.  Five machines across two lanes is 3 and 2 whatever you do; if
    every group starts at lane 0 then every remainder lands there, and a spec
    with two five-machine consumer groups asks lane 0 for 6/s while lane 1
    carries 4 -- ``flow.conservation``, on a spec whose totals balance exactly.
    Rotating by the group's position spreads them instead.

    Dealing MACHINES rather than sorters is a deliberate limit: a group with
    fewer machines than lanes leaves the surplus lanes empty and puts its whole
    rate on the ones it fills.  That cannot bite in practice, because a single
    machine's throughput is far below a belt's -- an item only needs parallel
    lanes when many machines share it.
    """
    if lanes <= 1:
        return list(machines)
    return machines[(j + rota) % lanes :: lanes]


@dataclass(frozen=True, slots=True)
class _Slot:
    """One block in a row's 1D packing. ``key`` is ``None`` for a Tesla tower."""

    key: str | None
    x: int
    width: int


def _pack_row(
    row: list[str], groups: dict[str, _Group], *, hr: int, power: bool
) -> tuple[list[_Slot], int]:
    """Lay one row out left to right, interleaving towers among the machines.

    A tower in a row blocks no belt -- that is what makes power nearly free in
    this skeleton -- but it does consume row width, so it has to be packed *with*
    the machines rather than overlaid afterwards.

    This is the single source of truth for x positions: emission materialises
    these slots, and the direct-insert feasibility check measures against them.
    Computing x twice is how a sorter ends up spanning further than it can reach.
    """
    tw, _th = CONSTANTS.tower_size
    slots: list[_Slot] = []
    x = 0
    next_tower = 0
    covered_to = -1
    for key in row:
        g = groups[key]
        for _ in range(g.count):
            if power and x >= next_tower:
                slots.append(_Slot(None, x, tw))
                covered_to = x + tw - 1 + hr
                x += tw
                next_tower = x + 2 * hr
            slots.append(_Slot(key, x, g.width))
            x += g.width
    # The greedy pass covers left to right; a trailing block may extend past the
    # last tower's reach, so close the gap explicitly.
    while power and covered_to < x - 1:
        slots.append(_Slot(None, x, tw))
        covered_to = x + tw - 1 + hr
        x += tw
    return slots, x


def _column_overlap(ax: int, aw: int, bx: int, bw: int) -> int | None:
    """Leftmost column both footprints cover, or ``None``.

    A DSP sorter runs in a straight line, so a direct insert is only physical
    when the two machines share a column and both anchors sit in it.
    """
    lo, hi = max(ax, bx), min(ax + aw, bx + bw) - 1
    return lo if lo <= hi else None


def _every_machine_pairs(prod: list[int], w_src: int, cons: list[int], w_dst: int) -> bool:
    """Does every producer AND every consumer have a partner in a shared column?

    Both directions, which is the half that was missing.  The old test asked only
    whether SOME consumer could be reached, and emission then paired each
    consumer with a producer -- so when producers outnumbered consumers, or when
    two consumers picked the same producer, the leftover producers got no sorter
    at all.  Their belt lane had already been dropped, so they simply backed up:
    ``machine.output_removed`` on plastic, processor, energy-matrix,
    information-matrix and quantum-chip.

    Dropping the insert instead restores the lane, which costs a tile of corridor
    and drains every producer.
    """
    return all(
        any(_column_overlap(p, w_src, c, w_dst) is not None for c in cons) for p in prod
    ) and all(
        any(_column_overlap(p, w_src, c, w_dst) is not None for p in prod) for c in cons
    )


def _realizable_direct(
    spec: BuildSpec,
    groups: dict[str, _Group],
    edges: list[_Edge],
    plan: _Plan,
    *,
    power: bool,
) -> tuple[set[tuple[str, str, str]], list[list[str]], dict[str, int]]:
    """Shrink ``plan.direct`` to the inserts real geometry can actually carry.

    The solver bounds the corridor between a direct-inserted pair, but it models
    lane counts approximately -- ``_lane_requirements`` is the truth, and it can
    return more lanes than the model believed, pushing the two rows further apart
    than a sorter can span.

    Dropping an insert only ever *adds* lanes, which only ever pushes rows
    further apart, so the set shrinks monotonically and the loop terminates.
    Returning the lanes alongside keeps the two consistent -- computing them
    separately is what would let a lane vanish with no sorter to replace it.
    """
    at = _row_index(plan.rows)
    reach = CONSTANTS.sorter_max_reach
    current = set(plan.direct)
    while True:
        lanes, copies = _lane_requirements(groups, edges, plan.rows, current, spec)
        row_heights = [max((groups[k].height for k in r), default=1) for r in plan.rows]
        corridor_heights = [len(c) for c in lanes]
        row_y, _corr_y, _h = band_offsets(row_heights, corridor_heights)

        xs: dict[str, list[int]] = defaultdict(list)
        for r, row in enumerate(plan.rows):
            hr = _horizontal_reach(r, row_heights, corridor_heights) if power else 0
            slots, _w = _pack_row(row, groups, hr=hr, power=power)
            for s in slots:
                if s.key is not None:
                    xs[s.key].append(s.x)

        worst: tuple[int, tuple[str, str, str]] | None = None
        for ek in sorted(current):
            src, dst, _item = ek
            r_src, r_dst = at[src], at[dst]
            # The producer's OWN bottom edge, not its row's: a short machine in a
            # tall row stops well above the row's floor, and measuring from the
            # floor understates the gap the sorter has to cross.
            dy = row_y[r_dst] - (row_y[r_src] + groups[src].height - 1)
            prod, cons = xs.get(src, []), xs.get(dst, [])
            w_src, w_dst = groups[src].width, groups[dst].width
            physical = (
                prod
                and cons
                and 1 <= dy <= reach
                and _every_machine_pairs(prod, w_src, cons, w_dst)
            )
            excess = dy - reach if physical else reach + 1
            if excess > 0 and (worst is None or excess > worst[0]):
                worst = (excess, ek)
        if worst is None:
            return current, lanes, copies
        # Drop ONE at a time, worst first. Removing an insert restores its lane,
        # which pushes every other pair further apart -- so discarding the whole
        # infeasible set at once cascades and can lose inserts that would have
        # survived on their own. Measured: dropping both of the magnetic-ring
        # candidates together left zero, where dropping only the unreachable one
        # keeps the other.
        current.discard(worst[1])


def _machine_config(factoriolab_recipe_id: str) -> tuple[int, tuple[int, ...]]:
    """``(recipe_id, parameters)`` for the machine running this recipe.

    Most machines are told what to make through ``recipe_id`` and carry no
    parameters.  A few are configured by a MODE in their parameter block
    instead, with ``recipe_id`` left at zero -- an Energy Exchanger's
    charge/discharge, a Ray Receiver's photon/power.  FactorioLab models both
    kinds as ordinary recipes with real item flow, so they belt, sort and lay
    out identically; only this one decision differs.

    Resolved here rather than at the call site so a machine can never be emitted
    half-configured: every placement gets exactly one of the two, and a recipe
    that is neither raises rather than pasting an idle machine.
    """
    if factoriolab_recipe_id in catalog.MODE_DRIVEN_MACHINE:
        return 0, params.parameters_for(factoriolab_recipe_id)
    return catalog.recipe_id(factoriolab_recipe_id), ()


def _emit(spec: BuildSpec, plan: _Plan, *, power: bool) -> Placement:
    """Turn a row/lane plan into concrete buildings on the grid."""
    groups, edges = _adapt(spec)
    at = _row_index(plan.rows)
    belt_id = BELT_ITEM_IDS.get(spec.belt_item_id, 2001)
    belt_model = catalog.building(belt_id).model_index

    direct, lanes, copies = _realizable_direct(spec, groups, edges, plan, power=power)
    plan = _Plan(
        rows=plan.rows,
        lanes=lanes,
        direct=direct,
        solver_status=plan.solver_status,
        hit_budget=plan.hit_budget,
    )

    row_heights = [max((groups[k].height for k in r), default=1) for r in plan.rows]
    corridor_heights = [len(c) for c in plan.lanes]
    row_y, corr_y, total_h = band_offsets(row_heights, corridor_heights)

    # A boundary corridor has only one neighbouring row, and measurement shows
    # powered buildings reach its FULL depth -- sorters tap the deepest external
    # input lane, so a 9-lane top corridor puts them 9 tiles from row 0.  Row 0's
    # towers cannot cover that and share it with nobody, which is what made the
    # two largest corpus specs uncoverable outright.
    #
    # Give the top corridor its own tower band.  One tile of height buys the
    # second neighbour that interior corridors get for free.
    top_band = _top_band_height(row_heights, corridor_heights)
    if top_band:
        row_y = [y + top_band for y in row_y]
        corr_y = [y + top_band for y in corr_y]
        total_h += top_band

    buildings: list[PlacedBuilding] = []
    machine_at: dict[str, list[int]] = defaultdict(list)
    towers = 0

    # --- machines, with towers interleaved as blocks in the row -----------
    # A tower placed in a row blocks no belt, which is what makes power nearly
    # free here.  Towers must therefore be packed *with* the machines rather
    # than overlaid on top of them.
    _tw, th = CONSTANTS.tower_size
    tower_model = catalog.building(CONSTANTS.tesla_item_id).model_index
    row_widths: list[int] = []
    for r, row in enumerate(plan.rows):
        hr = _horizontal_reach(r, row_heights, corridor_heights) if power else 0
        slots, width = _pack_row(row, groups, hr=hr, power=power)
        for s in slots:
            if s.key is None:
                buildings.append(
                    PlacedBuilding(
                        item_id=CONSTANTS.tesla_item_id,
                        model_index=tower_model,
                        x=s.x,
                        # Centred in the row, not pinned to its top edge.
                        # `_horizontal_reach` budgets half the row height, which
                        # only holds for a centred tower: at the top edge the far
                        # side is `row_height - 1` away, so an 11-tall row spends
                        # the entire 10.5 radius before any corridor is counted.
                        y=row_y[r] + max(0, (row_heights[r] - th) // 2),
                        width=s.width,
                        height=th,
                    )
                )
                towers += 1
                continue
            g = groups[s.key]
            machine_at[s.key].append(len(buildings))
            # A machine with no recipe pastes into the game and then sits idle.
            # Mode-driven machines are the exception: their job lives in the
            # parameter block and recipe_id stays zero.
            recipe_id, parameters = _machine_config(g.recipe_id)
            buildings.append(
                PlacedBuilding(
                    item_id=g.item_id,
                    model_index=g.model_index,
                    x=s.x,
                    y=row_y[r],
                    width=g.width,
                    height=g.height,
                    recipe_id=recipe_id,
                    parameters=parameters,
                )
            )
        row_widths.append(width)
    content_w = max([*row_widths, 1])

    # --- top tower band ---------------------------------------------------
    # Sits above the first corridor, covering the external input lanes that row 0
    # alone cannot reach.  Spacing comes from the same reach table, evaluated at
    # the depth of the deepest lane it has to serve.
    if power and top_band:
        band_dy = min(corridor_heights[0], _max_dy())
        band_hr = max(1, _REACH_TABLE[band_dy])
        x = band_hr
        while x < content_w + band_hr:
            buildings.append(
                PlacedBuilding(
                    item_id=CONSTANTS.tesla_item_id,
                    model_index=tower_model,
                    x=min(x, max(0, content_w - 1)),
                    y=0,
                    width=1,
                    height=th,
                )
            )
            towers += 1
            x += 2 * band_hr

    # --- what taps what ---------------------------------------------------
    # Which lane each group reaches, for each of its items, computed ONCE.  The
    # extent trim, the riser planner and the sorter pass all need the same
    # answer; deriving it three times is how a sorter came to anchor on one lane
    # copy while the trim shortened a different one.
    #
    # Edges served entirely by direct insertion are left out, because they get
    # no sorter at all.  Counting them would have the riser planner joining a
    # lane nothing fills to a lane nothing drains.
    leaving = _leaving_items(groups, spec)
    rate_of = {(e.src, e.dst, e.item): e.rate for e in edges}
    in_edges: dict[tuple[str, str], list[_Edge]] = defaultdict(list)
    out_edges: dict[tuple[str, str], list[_Edge]] = defaultdict(list)
    for e in edges:
        in_edges[e.dst, e.item].append(e)
        out_edges[e.src, e.item].append(e)
    fully_direct_in = {
        (k, item)
        for (k, item), es in in_edges.items()
        if item not in spec.external_inputs
        and all((e.src, e.dst, e.item) in plan.direct for e in es)
    }
    fully_direct_out = {
        (k, item)
        for (k, item), es in out_edges.items()
        if item not in leaving and all((e.src, e.dst, e.item) in plan.direct for e in es)
    }

    taps: dict[tuple[str, str, bool], list[_Tap]] = {}
    #: Where each group starts its round-robin deal across parallel lanes, so
    #: two groups of the same size do not both hand their remainder to lane 0.
    rota = {key: i for i, key in enumerate(groups)}
    for key, g in groups.items():
        r = at[key]
        for item, into in [(i, True) for i in g.inputs] + [(o, False) for o in g.outputs]:
            if (key, item) in (fully_direct_in if into else fully_direct_out):
                continue
            found = _find_taps(
                plan,
                r,
                item,
                corr_y,
                row_y,
                g.height,
                out=not into,
                want=copies.get(item, 1),
            )
            if found:
                taps[key, item, into] = found

    # --- lane extents -----------------------------------------------------
    # A lane only needs belt where something actually taps it, plus a run to the
    # block edge when it carries an external input in or a product out, plus a
    # run to the east margin when a riser has to reach it.  Full width costs no
    # extra *area*, but it triples the building count, which matters when
    # pasting.  Untapped pass-through lanes keep their full width; they stop at
    # ``content_w - 1``, so they never reach into the riser margin.
    extents: dict[tuple[int, str], tuple[int, int]] = {}
    #: Columns at which each lane is filled and drained, keyed by (corridor,
    #: depth) rather than by item, because a direction is a property of ONE lane
    #: and an item may hold two of them.  ``_lane_direction`` reads these.
    fill_at: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    drain_at: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)

    def _extend(c: int, item: str, lo: int, hi: int) -> None:
        cur = extents.get((c, item))
        extents[c, item] = (lo, hi) if cur is None else (min(cur[0], lo), max(cur[1], hi))

    for key, g in groups.items():
        if not machine_at[key]:
            continue
        for item, into in [(i, True) for i in g.inputs] + [(o, False) for o in g.outputs]:
            found = taps.get((key, item, into), [])
            if not found:
                continue
            # A machine's sorters do not spread over its whole footprint:
            # ``_place_sorters`` anchors the i-th at ``m.x + i``, so a group
            # served by one sorter per machine only ever touches each machine's
            # LEFT column.  Charging the lane the full footprint left the tiles
            # past the last sorter dangling with nothing to draw from them --
            # which is what ``belt.termination`` was warning about on every run.
            #
            # The count comes from the same call the sorter pass makes, with the
            # same arguments, so the two cannot disagree about how many columns
            # get used.
            rate = (g.inputs if into else g.outputs)[item]
            for j, tap in enumerate(found):
                share = _share(machine_at[key], len(found), j, rota[key])
                if not share:
                    continue
                xs = [buildings[i].x for i in share]
                pick = _pick_sorter(rate, tap.span, g.width)
                cols = g.width if pick is None else min(pick[1], g.width)
                lo, hi = min(xs), max(xs) + cols - 1
                _extend(tap.corridor, item, lo, hi)
                (drain_at if into else fill_at)[tap.corridor, tap.depth].append((lo, hi))

    for c, order in enumerate(plan.lanes):
        for item in order:
            if (c, item) not in extents:
                continue
            if item in spec.external_inputs:
                _extend(c, item, 0, 0)
            if item in leaving:
                _extend(c, item, content_w - 1, content_w - 1)

    # --- trunk risers -----------------------------------------------------
    # The copies of an item's lane in different corridors used to be independent
    # horizontal runs with nothing between them, so a producer's sorters filled
    # corridor r + 1 while its consumers drained corridor s and the item never
    # arrived.  Every `flow.lane_sourced` error on every corpus spec was this.
    filled: set[tuple[int, int]] = set()
    drained: set[tuple[int, int]] = set()
    for (key, _item, into), found in taps.items():
        for j, tap in enumerate(found):
            if _share(machine_at[key], len(found), j, rota[key]):
                (drained if into else filled).add((tap.corridor, tap.depth))

    risers = _plan_risers(
        plan, corr_y, filled, drained, set(spec.external_inputs), copies
    )
    fed_from_trunk: set[tuple[int, int]] = set()
    hands_to_trunk: set[tuple[int, int]] = set()
    joined: set[tuple[int, int]] = set()
    for riser in risers:
        for _y, c, d, is_source in riser.taps:
            joined.add((c, d))
            (hands_to_trunk if is_source else fed_from_trunk).add((c, d))
    for c, d in joined:
        _extend(c, plan.lanes[c][d], content_w - 1, content_w - 1)

    # --- corridor lanes ---------------------------------------------------
    # Keyed by (corridor, DEPTH), not (corridor, item): an item may occupy
    # several lanes in one corridor for capacity, and keying by item made the
    # second lane overwrite the first.  `_find_tap` then returned the first
    # lane's y while this dict held the last lane's tiles, so every sorter on
    # a duplicated item anchored on one belt and named another.
    lane_tiles: dict[tuple[int, int], list[int]] = {}
    lane_item_of: dict[tuple[int, int], str] = {}
    starved_taps = 0
    for c, order in enumerate(plan.lanes):
        for depth_i, item in enumerate(order):
            y = corr_y[c] + depth_i
            lo, hi = extents.get((c, item), (0, content_w - 1))
            fills = fill_at[c, depth_i]
            drains = drain_at[c, depth_i]
            westward = _lane_direction(
                (c, depth_i),
                fed_from_trunk=fed_from_trunk,
                hands_to_trunk=hands_to_trunk,
                pinned_west_edge=item in spec.external_inputs,
                pinned_east_edge=item in leaving,
                fills=fills,
                drains=drains,
            )
            # What the chosen direction still cannot serve.  A lane whose drains
            # straddle its fills is unservable either way -- see the stat's note
            # in the returned ``Placement``.
            supply = list(fills)
            if (c, depth_i) in fed_from_trunk:
                supply.append((content_w - 1, content_w - 1))
            if item in spec.external_inputs:
                supply.append((0, 0))
            starved_taps += _lane_flow_gaps(supply, drains, westward=westward)
            indices: list[int] = []
            for x in range(lo, hi + 1):
                indices.append(len(buildings))
                buildings.append(
                    PlacedBuilding(
                        item_id=belt_id,
                        model_index=belt_model,
                        x=x,
                        y=y,
                        width=1,
                        height=1,
                        yaw=(Facing.WEST if westward else Facing.EAST).value,
                        # Which item this lane carries is layout knowledge that
                        # nothing can recover once emission drops it.  The belt
                        # marker pass needs it to tag external-input runs, and
                        # the validator's per-item flow check needs it too.
                        carries_item=item,
                    )
                )
            # Forward-link the run along its direction of travel, matching what
            # the game emits.  ``indices`` stays in x order whichever way the
            # lane runs, because everything else looks a tile up by column.
            chain = indices[::-1] if westward else indices
            for a, b in zip(chain, chain[1:], strict=False):
                buildings[a] = _with_output(buildings[a], b)
            lane_tiles[c, depth_i] = indices
            lane_item_of[c, depth_i] = item

    riser_belts, junctions = _emit_risers(
        buildings,
        risers,
        lane_tiles,
        content_w=content_w,
        belt_id=belt_id,
        belt_model=belt_model,
    )

    # --- direct inserts ---------------------------------------------------
    # A direct-inserted edge has no lane, so the sorter must reach machine to
    # machine.  This runs before the belt taps so that a connection served
    # entirely by direct insertion can be skipped there rather than sprouting a
    # second, redundant feed.
    sorters = 0
    direct_sorters = 0
    for src, dst, item in sorted(plan.direct):
        r_src, r_dst = at[src], at[dst]
        y_src = row_y[r_src] + groups[src].height - 1
        y_dst = row_y[r_dst]
        dy = y_dst - y_src
        prod, cons = machine_at[src], machine_at[dst]
        if not prod or not cons:
            continue
        # Pair each consumer with a producer it SHARES A COLUMN with.  A sorter
        # runs in a straight line, so a direct insert is only physical when the
        # two footprints overlap in x and the anchors sit in that overlap.
        # Pairing by nearest-x and anchoring at each machine's own left edge
        # produced diagonals; the span was also computed Manhattan
        # (``|dx| + dy``) where the validator measures Chebyshev, so a pair
        # could pass here and fail there.  With dx pinned to 0 the two agree.
        pairs: list[tuple[int, int, int, int]] = []
        span = abs(dy)

        def _pair(a: int, others: list[int], span: int = span) -> tuple[int, int] | None:
            ab = buildings[a]
            if not 1 <= span <= CONSTANTS.sorter_max_reach:
                return None
            for b in sorted(others, key=lambda o: abs(buildings[o].x - ab.x)):
                bb = buildings[b]
                col = _column_overlap(ab.x, ab.width, bb.x, bb.width)
                if col is not None:
                    return b, col
            return None

        for ci in cons:
            got = _pair(ci, prod)
            if got is not None:
                pairs.append((got[0], ci, span, got[1]))
        # And every PRODUCER, not just every consumer.  A producer left out has
        # no belt lane either -- the insert removed it -- so it backs up, which
        # is what `machine.output_removed` was reporting on five corpus specs.
        # Pairing it with a consumer it already shares a column with costs one
        # more sorter and nothing else; the consumer simply gets fed twice.
        wired = {pi for pi, _ci, _s, _c in pairs}
        for pi in prod:
            if pi in wired:
                continue
            got = _pair(pi, cons)
            if got is not None:
                pairs.append((pi, got[0], span, got[1]))
        rate = rate_of.get((src, dst, item), Fraction(0))
        if not pairs:
            raise ValueError(
                f"direct insert {src} -> {dst} ({item}) has no machine pair within "
                f"sorter reach {CONSTANTS.sorter_max_reach}"
            )
        worst = max(s for _, _, s, _x in pairs)
        tier = next(
            (t for t in SORTER_TIERS if catalog.sorter_rate(t, worst) * len(pairs) >= rate),
            None,
        )
        if tier is None:
            raise ValueError(
                f"direct insert {src} -> {dst} ({item}) needs {rate} items/s but "
                f"{len(pairs)} sorters at span {worst} cannot carry it"
            )
        tier_model = catalog.building(tier).model_index
        for pi, ci, _span, col in pairs:
            buildings.append(
                PlacedBuilding(
                    item_id=tier,
                    model_index=tier_model,
                    x=col,
                    y=y_src,
                    width=1,
                    height=1,
                    x2=col,
                    y2=y_dst,
                    z2=0,
                    yaw=Facing.SOUTH.value,
                    yaw2=Facing.SOUTH.value,
                    input_obj=pi,
                    output_obj=ci,
                )
            )
            direct_sorters += 1
    sorters += direct_sorters

    # --- sorters ----------------------------------------------------------
    for key, g in groups.items():
        connections = [(item, rate * g.count, True) for item, rate in g.inputs.items()]
        connections += [(item, rate * g.count, False) for item, rate in g.outputs.items()]
        for item, rate, into_machine in connections:
            if rate <= 0:
                continue
            # ``taps`` already dropped the connections served entirely by direct
            # insertion, and the risers were planned against exactly this map --
            # so a sorter here can never disagree with the lane a riser joined.
            found = taps.get((key, item, into_machine), [])
            if not found or not machine_at[key]:
                continue
            for j, tap in enumerate(found):
                machines = _share(machine_at[key], len(found), j, rota[key])
                if not machines:
                    continue
                # Size against THIS item's per-machine rate. `rate` here is the
                # group total, so divide it back out: a sorter serves one
                # machine.  Sizing against the machine's average across its
                # ingredients under-provisions whichever one is hot -- see
                # _pick_sorter.
                pick = _pick_sorter(rate / g.count, tap.span, g.width)
                if pick is None:
                    continue
                tier, per_machine = pick
                sorters += _place_sorters(
                    buildings,
                    lane_tiles[tap.corridor, tap.depth],
                    machines,
                    lane_y=tap.lane_y,
                    machine_y=tap.machine_y,
                    tier=tier,
                    per_machine=per_machine,
                    into_machine=into_machine,
                )

    # --- spray coaters ----------------------------------------------------
    # A coater is a belt addon: it consumes no grid tile, which is what makes
    # proliferation nearly free in area.  The cost is the proliferator lane.
    coaters = 0
    spray = catalog.building(CONSTANTS.spray_item_id)
    prolif = proliferator_item(spec)
    for item in spec.spray_lanes:
        # Mount on a lane copy the proliferator can reach.  An item may have
        # several lanes in a corridor, and taking the first one stranded a
        # coater whenever that copy sat further from the proliferator lane than
        # a sorter can span, even though a reachable copy existed.
        for lane_key, indices in _coater_lane_candidates(
            lane_tiles, lane_item_of, item, prolif
        ):
            if not indices:
                continue
            c, depth = lane_key
            # Mount the coater where the proliferator lane can actually reach
            # it. Defaulting to the lane's midpoint stranded any coater whose
            # column the proliferator lane did not extend to.
            mid = buildings[
                _coater_tile(buildings, indices, lane_tiles, lane_item_of, c, prolif)
            ]
            coater_idx = len(buildings)
            buildings.append(
                PlacedBuilding(
                    item_id=CONSTANTS.spray_item_id,
                    model_index=spray.model_index,
                    x=mid.x,
                    y=mid.y,
                    width=spray.width,
                    height=spray.height,
                    yaw=Facing.EAST.value,
                )
            )
            coaters += 1
            # Feed it. A coater with no proliferator sprays nothing, so every
            # proliferated recipe would quietly run unproliferated and the build
            # would miss its rate while looking perfectly healthy.
            sorters += _feed_coater(
                buildings,
                lane_tiles,
                lane_item_of,
                coater_idx=coater_idx,
                corridor=c,
                coater_depth=depth,
                corr_y=corr_y,
                prolif=prolif,
            )
            break

    # --- coverage top-up --------------------------------------------------
    # The analytic reach model budgets a worst-case vertical offset, which is
    # sound for machines and sorters but cannot bound a Spray Coater: coaters
    # ride whichever lane needs spraying, at any depth in a corridor, and
    # measurement found them 22 tiles from the nearest tower on a 19-group
    # build.  No closed form fixes that, so verify the real geometry and add
    # towers where it actually falls short.
    uncovered = 0
    if power:
        extra, uncovered = _top_up_coverage(buildings, tower_model)
        towers += extra
        towers += _link_towers(buildings, tower_model)

    return Placement(
        buildings=tuple(buildings),
        description=f"flab2bp spine layout ({spec.label or 'default'})",
        short_desc=spec.label or "flab2bp",
        stats={
            "area": float(_bbox_area(buildings)),
            "machines": float(sum(g.count for g in groups.values())),
            "belt_tiles": float(sum(len(v) for v in lane_tiles.values()) + riser_belts),
            "risers": float(len(risers)),
            "riser_columns": float(max((r.column for r in risers), default=-1) + 1),
            "junctions": float(junctions),
            "sorters": float(sorters),
            "direct_sorters": float(direct_sorters),
            "spray_coaters": float(coaters),
            "towers": float(towers),
            # Powered buildings the top-up could not reach because every tile
            # within a supply radius of them was occupied. Non-zero means the
            # build is genuinely under-powered, and the validator will say so.
            "power_uncovered": float(uncovered),
            # Sorters drawing from a lane that never carries anything past
            # them, because the lane's producers all sit downstream of the
            # consumer.  Non-zero means a machine pastes and silently does not
            # run, and NOTHING else can see it: every link resolves, the sorter
            # is in reach, the belt is continuous, so the validator reads the
            # build as clean.  `_lane_direction` removes every case a direction
            # can remove; what is left is a lane drained on both sides of where
            # it is filled, which wants a second lane rather than a different
            # arrow.
            "starved_taps": float(starved_taps),
            "direct_inserts": float(len(plan.direct)),
            "corridor_tiles": float(sum(corridor_heights)),
            "height_waste": float(
                sum(
                    height_waste(
                        row_heights[r],
                        [(groups[k].width, groups[k].height, groups[k].count) for k in row],
                    )
                    for r, row in enumerate(plan.rows)
                )
            ),
            "rows": float(len(plan.rows)),
            "solver_status": float(plan.solver_status == "OPTIMAL"),
            "hit_time_budget": float(plan.hit_budget),
            "fallback_used": float(plan.solver_status == "fallback"),
        },
    )


def _lane_flow_gaps(
    fills: list[tuple[int, int]],
    drains: list[tuple[int, int]],
    *,
    westward: bool,
) -> int:
    """Drain taps this direction leaves with nothing upstream of them.

    Each range is one group's sorter columns on that lane.  A drain group is
    served when some fill group starts at or before it in the direction of
    travel; measuring at group granularity matches how the sorters are placed
    (every machine of a group taps the same lane at its own column) and is what
    makes the answer a small integer worth putting in ``stats``.
    """
    if westward:
        return sum(1 for _lo, hi in drains if not any(f[1] >= hi for f in fills))
    return sum(1 for lo, _hi in drains if not any(f[0] <= lo for f in fills))


def _lane_direction(
    key: tuple[int, int],
    *,
    fed_from_trunk: set[tuple[int, int]],
    hands_to_trunk: set[tuple[int, int]],
    pinned_west_edge: bool,
    pinned_east_edge: bool,
    fills: list[tuple[int, int]],
    drains: list[tuple[int, int]],
) -> bool:
    """Should this lane run east to west?  ``True`` for westward.

    Belts are one-way, so a lane's direction decides which of its taps are
    physically upstream of which.  Lanes used to run east unconditionally, with
    taps dropped at machine columns in whatever order the columns happened to
    fall -- so a consumer standing WEST of the producer that fills the lane got
    a sorter reaching into a belt that never carries anything past it.  It
    pastes, it looks right, and that machine simply never runs.  The validator
    cannot see it: every link resolves, the sorter is in reach, the belt is
    continuous.

    Four of the five cases have their direction forced by something physical,
    and they are checked first:

    * a lane the trunk FEEDS takes its items at its eastmost tile, so it must
      flow away westward or they would arrive at the far end and stop;
    * a lane that HANDS UP to the trunk must reach it, so it flows east;
    * an external input enters at ``x = 0``, the block's west edge;
    * a product leaves at the east edge.

    Only the fifth case -- a lane whose taps are all local -- is free, and there
    the direction is whichever leaves fewer drains with nothing upstream, ties
    going east so the common case is unchanged.

    Measured over the 33 powered corpus runs: three lanes were served the wrong
    way round, on magnetic-coil, plastic and processor.  Rare -- 3 of 656 lanes
    -- but each one is a machine that silently does not run.  Two are free lanes
    and this fixes them.  The third, ``plastic``'s refined-oil lane, is drained
    at columns 1, 10 and 20 while being filled only at 4 and 7: no single
    direction can serve drains on BOTH sides of the fills, so one tap stays
    unserved and is counted in ``stats["starved_taps"]`` rather than hidden.
    """
    if key in fed_from_trunk:
        return True
    if key in hands_to_trunk or pinned_west_edge or pinned_east_edge:
        return False
    return _lane_flow_gaps(fills, drains, westward=True) < _lane_flow_gaps(
        fills, drains, westward=False
    )


#: Altitude a riser's horizontal bridge rides at while it crosses the trunks of
#: other items.  Everything else in this skeleton is at ``z = 0``; a bridge is
#: the one thing that has to pass over something, and belts are the only class of
#: building that may.  One level is enough for any number of trunks, because a
#: bridge only ever crosses trunks, never another bridge -- two bridges would
#: have to share a lane's ``y``, and a lane holds one item.
_BRIDGE_Z = 1


def _trunk_x(content_w: int, column: int) -> int:
    """Where trunk ``column`` stands in the east margin.

    Trunks are spaced two columns apart, with a free RAMP column west of each.
    That gap is not decoration: ``catalog.RAMP_TILES_PER_LEVEL`` is 2, so a belt
    needs a tile of level run-up before it changes altitude -- exactly what
    ``freeform``'s A\\* reserves when it takes a ramp edge.  A bridge that leaves
    a lane at ``z = 0`` and is already at ``z = 1`` on the next tile is climbing
    twice as fast as a belt can, and the same on the way back down.

    The gap has to be a whole column because both ends of a bridge need one and
    they are at opposite ends:

    * a bridge running EAST leaves the lane at ``z = 0``, so its run-up tile is
      the one at ``content_w`` -- the ramp column west of trunk 0;
    * a bridge running WEST leaves the trunk at ``z = 0``, so its run-up tile is
      the one immediately west of that trunk -- which, without a gap, would be
      the *previous trunk's* column and would collide with it at ``z = 0``.

    Packing the trunks tightly and letting the bridges jump a level in one tile
    is what this used to do.  ``geom.altitude_step`` permits it -- it only bounds
    the step at one level per tile and knows nothing about run-up -- so the
    validator was complicit and neither side of the build ever complained.
    """
    return content_w + 2 * column + 1


@dataclass(frozen=True, slots=True)
class _Riser:
    """One item's vertical trunk, joining the lane copies it is tapped at.

    ``taps`` is ``(y, corridor, depth, is_source)`` per joined lane, ordered top
    to bottom.  A *source* lane is one a producer's sorters fill, and it hands
    items to the trunk; every other lane is fed FROM the trunk.

    ``column`` is an index into the east margin, not an x -- :func:`_trunk_x`
    turns it into one.  Trunks are coloured like an interval graph, two whose
    vertical spans do not overlap sharing a column, so their count is the deepest
    pile-up of simultaneously-live trunks: 2 on graphene, 3 on processor, 4 on
    casimir-crystal.

    An item that overflows a belt gets a trunk PER PARALLEL LANE -- see
    :func:`_lane_copies` -- which is why the colouring is over trunks rather than
    over items.
    """

    item: str
    taps: tuple[tuple[int, int, int, bool], ...]
    column: int = 0


def _plan_risers(
    plan: _Plan,
    corr_y: list[int],
    filled: set[tuple[int, int]],
    drained: set[tuple[int, int]],
    external: set[str],
    copies: dict[str, int],
) -> list[_Riser]:
    """Which items need their corridor copies joined, and over what span.

    External inputs are deliberately excluded.  Every tapped copy of an external
    item is run out to ``x = 0``, so each copy is its own entry at the block
    boundary -- the player belts the ore in three times rather than once, which
    is both physical and free.  Risering them instead would double the margin
    for no gain: on casimir-crystal it is the difference between 4 columns and
    6.

    A destination lying ABOVE every source is left alone rather than reached for.
    A downward trunk cannot serve it, and quietly emitting one that does not
    would trade a reported error for an unreported one.
    """
    # Keyed by (item, COPY RANK), not by item.  An item that needs parallel
    # lanes gets a trunk per copy: trunk k joins copy k in one corridor to copy
    # k in the next, so each carries its own share.  Joining every copy to one
    # trunk would put the whole flow back on a single belt -- the exact
    # bottleneck the copies exist to remove -- and would also blow past a
    # splitter's four sides.
    lanes_of: dict[tuple[str, int], list[tuple[int, int, int, bool]]] = defaultdict(list)
    for c, order in enumerate(plan.lanes):
        run: dict[str, int] = defaultdict(int)
        for d, item in enumerate(order):
            # Position within this item's CONTIGUOUS block of lanes, modulo how
            # many parallel copies it has.  Parallel copies sit next to each
            # other and want separate trunks; the top-band and bottom-band copies
            # of one stream want the SAME trunk, and the modulo hands them the
            # same rank however the two blocks happen to abut.
            run[item] = 0 if d and order[d - 1] != item else run[item]
            k = run[item] % max(copies.get(item, 1), 1)
            run[item] += 1
            if item in external:
                continue
            is_source = (c, d) in filled
            if not is_source and (c, d) not in drained:
                continue
            lanes_of[item, k].append((corr_y[c] + d, c, d, is_source))

    risers: list[_Riser] = []
    for (item, _k), lanes in sorted(lanes_of.items()):
        lanes.sort()
        first = next((i for i, t in enumerate(lanes) if t[3]), None)
        if first is None:
            continue  # nothing fills this item anywhere; not a riser's problem
        last = next(
            (i for i in range(len(lanes) - 1, first, -1) if not lanes[i][3]), None
        )
        if last is None:
            continue  # every copy below the first source is itself a source
        risers.append(_Riser(item=item, taps=tuple(lanes[first : last + 1])))
    return _assign_columns(risers)


def _assign_columns(risers: list[_Riser]) -> list[_Riser]:
    """Colour the trunks' vertical spans, leftmost free column first.

    Greedy by start point is optimal on an interval graph, so this uses the
    fewest columns any assignment could -- and the margin's width is the whole
    area cost of risering.
    """
    free_from: list[int] = []
    out: list[_Riser] = []
    for riser in sorted(risers, key=lambda r: (r.taps[0][0], r.item)):
        lo, hi = riser.taps[0][0], riser.taps[-1][0]
        col = next((i for i, y in enumerate(free_from) if y <= lo), None)
        if col is None:
            col = len(free_from)
            free_from.append(hi + 1)
        else:
            free_from[col] = hi + 1
        out.append(replace(riser, column=col))
    return out


def _emit_risers(
    buildings: list[PlacedBuilding],
    risers: list[_Riser],
    lane_tiles: dict[tuple[int, int], list[int]],
    *,
    content_w: int,
    belt_id: int,
    belt_model: int,
) -> tuple[int, int]:
    """Build every trunk and the bridges that reach it.  Returns (belts, junctions).

    Geometry, all of it forced:

    * The trunk is a column of belts in the margin at :func:`_trunk_x`, running
      the full height of its span.  Nothing else is out there -- lanes stop at
      ``content_w - 1`` -- so a trunk can never collide with a lane.
    * A lane reaches its trunk along its own ``y``, across the ramp column beside
      it.  For the first trunk that bridge is a single tile on the ground.
      Otherwise the intervening columns hold OTHER items' trunks, and the
      connection crosses them on a
      belt at :data:`_BRIDGE_Z`.  This is the escape the row model needs: on
      magnetic-ring ``iron-ingot`` spans corridors 1-3 while ``magnet`` spans
      2-5, which properly cross, so no left-to-right column order avoids a
      crossing and one has to go over the other.
    * A lane handing items UP to the trunk is a plain belt merge, which DSP does
      natively.  A trunk that must feed a lane AND carry on downwards cannot,
      because a belt has one ``output_obj`` -- that is exactly what a splitter
      is for, and it is the only place one is needed.
    """
    belts = 0
    junctions = 0
    for riser in risers:
        xr = _trunk_x(content_w, riser.column)
        stops = {y: (c, d, src) for y, c, d, src in riser.taps}
        last_y = riser.taps[-1][0]

        def _trunk_belt(x: int, y: int, item: str = riser.item) -> int:
            idx = len(buildings)
            buildings.append(
                PlacedBuilding(
                    item_id=belt_id,
                    model_index=belt_model,
                    x=x,
                    y=y,
                    width=1,
                    height=1,
                    yaw=Facing.SOUTH.value,
                    carries_item=item,
                )
            )
            return idx

        upstream: int | None = None
        for y in range(riser.taps[0][0], last_y + 1):
            stop = stops.get(y)
            branch = -1
            if stop is not None and not stop[2] and y != last_y:
                # The trunk must feed this lane AND carry on down, which one
                # belt cannot: a belt has a single ``output_obj``.  That is
                # exactly what a junction is for, and the only place one is
                # needed.  All three belts sit ON the splitter's tile, because
                # that is how the corpus records a belt running through one.
                arriving = _trunk_belt(xr, y)
                junction_idx = len(buildings)
                buildings.append(junction.make_splitter(xr, y, carries_item=riser.item))
                junctions += 1
                buildings[arriving] = _with_output(buildings[arriving], junction_idx)
                here = _trunk_belt(xr, y)
                buildings[here] = replace(buildings[here], input_obj=junction_idx)
                branch = _trunk_belt(xr, y)
                buildings[branch] = replace(buildings[branch], input_obj=junction_idx)
                belts += 3
                if upstream is not None:
                    buildings[upstream] = _with_output(buildings[upstream], arriving)
            else:
                here = _trunk_belt(xr, y)
                belts += 1
                if upstream is not None:
                    buildings[upstream] = _with_output(buildings[upstream], here)
            upstream = here

            if stop is None:
                continue
            c, d, is_source = stop
            end = _lane_tile_at(buildings, lane_tiles[c, d], content_w - 1)
            if end is None:
                continue  # the lane never reached the margin; nothing to join
            head, tail, added = _bridge(
                buildings,
                y,
                content_w,
                xr,
                riser.item,
                belt_id,
                belt_model,
                toward_trunk=is_source,
            )
            belts += added
            if is_source:
                # Lane hands up to the trunk.  Two belts pointing at one tile is
                # a merge, which DSP does natively and the validator models.
                if added:
                    buildings[end] = _with_output(buildings[end], head)
                    buildings[tail] = _with_output(buildings[tail], here)
                else:
                    buildings[end] = _with_output(buildings[end], here)
                continue
            source = branch if branch >= 0 else here
            if added:
                buildings[source] = _with_output(buildings[source], head)
                buildings[tail] = _with_output(buildings[tail], end)
            else:
                buildings[source] = _with_output(buildings[source], end)
    junction.check_ports(buildings)
    return belts, junctions


def _bridge(
    buildings: list[PlacedBuilding],
    y: int,
    content_w: int,
    xr: int,
    item: str,
    belt_id: int,
    belt_model: int,
    *,
    toward_trunk: bool,
) -> tuple[int, int, int]:
    """Belts spanning ``content_w .. xr - 1`` at row ``y``, ramped honestly.

    Returns ``(head, tail, count)`` in flow order: ``head`` is the tile the
    upstream side hands to and ``tail`` the one that hands on.

    The altitude profile spends :data:`catalog.RAMP_TILES_PER_LEVEL` tiles on
    every level change, which for a belt climbing half a level per tile means one
    tile of RUN-UP at the old level before the tile that arrives at the new one.
    Written from the flow's point of view, so it reverses with the flow:

    * eastward (lane -> trunk) the run-up is the first tile, at ``z = 0``,
      sitting in the ramp column west of trunk 0; everything after it rides at
      :data:`_BRIDGE_Z`, and the last two of those are the run-out for the drop
      onto the trunk;
    * westward (trunk -> lane) the run-up is the LAST tile in ``x`` order -- the
      one beside the trunk, in that trunk's own ramp column -- and the drop back
      onto the lane runs out across the two tiles nearest ``content_w``.

    A trunk in column 0 needs no bridge at altitude at all: there is nothing
    between it and the lane to cross, so its single tile stays on the ground.
    """
    made: list[int] = []
    xs = list(range(content_w, xr))
    if not xs:
        return -1, -1, 0
    #: The run-up tile stays on the ground; every other tile is over a trunk and
    #: has to clear it.  A one-tile bridge is entirely run-up: flat, no crossing.
    ramp_x = content_w if toward_trunk else xr - 1
    for x in xs:
        made.append(len(buildings))
        buildings.append(
            PlacedBuilding(
                item_id=belt_id,
                model_index=belt_model,
                x=x,
                y=y,
                z=0 if (x == ramp_x or len(xs) == 1) else _BRIDGE_Z,
                width=1,
                height=1,
                yaw=(Facing.EAST if toward_trunk else Facing.WEST).value,
                carries_item=item,
            )
        )
    order = made if toward_trunk else made[::-1]
    for a, b in zip(order, order[1:], strict=False):
        buildings[a] = _with_output(buildings[a], b)
    return order[0], order[-1], len(made)


def _with_output(b: PlacedBuilding, target: int) -> PlacedBuilding:
    """Relink a belt to its downstream tile, preserving everything else.

    ``dataclasses.replace`` rather than a field-by-field rebuild on purpose: the
    old version enumerated nine fields and silently dropped the rest, so it was
    already discarding ``parameters``, ``filter_id``, both slot groups and the
    second anchor -- and it would have swallowed ``carries_item`` the moment
    that was set, making the belt marker pass come out empty and look like a
    marker bug rather than a relink one.  Any new field is now carried for free.
    """
    return replace(b, output_obj=target)


@dataclass(frozen=True, slots=True)
class _Tap:
    """A reachable connection between one machine row and one corridor lane."""

    corridor: int
    #: Index of the lane within the corridor. Identifies the lane uniquely
    #: where the item alone does not, because an item may occupy several.
    depth: int
    lane_y: int
    machine_y: int
    span: int


def _find_taps(
    plan: _Plan,
    r: int,
    item: str,
    corr_y: list[int],
    row_y: list[int],
    mach_h: int,
    *,
    out: bool,
    want: int = 1,
) -> list[_Tap]:
    """Up to ``want`` lanes carrying ``item`` within sorter reach of row ``r``.

    Plural because an item may need more than one lane to carry its rate -- see
    :func:`_lane_copies`.  Those parallel copies are emitted consecutively inside
    one band, so they are collected by walking outwards from the nearest lane and
    stopping at ``want``.

    The cap is what keeps the two KINDS of copy apart.  An item can also hold two
    lanes in one corridor for an unrelated reason -- a copy near the top serving
    the row above and one near the bottom serving the row below -- and those are
    the SAME stream reached from opposite sides, not parallel capacity.  Taking
    both here would deal half of a group's machines onto a lane meant for the
    other row's, which is how ``flow.lane_sourced`` came back on five corpus
    specs the first time this was written without the cap.

    Corridor ``c`` sits *above* row ``c``, so row ``r`` touches corridor ``r``
    with its top edge and corridor ``r + 1`` with its bottom edge.  The two sides
    measure depth in opposite directions, which is exactly what ``lane_order``
    arranges for:

    * from the corridor above, lane ``j`` of ``L`` is ``L - j`` tiles away;
    * from the corridor below, lane ``j`` is ``j + 1`` tiles away *from the row's
      bottom edge*, which is NOT the same as from the machine.

    ``mach_h`` is the height of the machine being wired, not the height of the
    row it sits in.  A row is as tall as its tallest group, so a 3-tall smelter
    sharing a row with a 7-tall refinery stops four tiles short of the row's
    bottom edge.  Measuring from the edge put every one of that smelter's output
    sorters' anchors on empty space -- ``sorter.endpoints`` caught it on three
    corpus specs -- and understated the span, so the reach test passed for
    sorters that could not physically reach.
    """
    top = row_y[r]
    bottom = row_y[r] + mach_h - 1
    # Outputs prefer the corridor below (natural top-to-bottom flow); inputs the
    # corridor above.  Either is legal, so both are tried.
    order = [(r + 1, False), (r, True)] if out else [(r, True), (r + 1, False)]
    for c, from_corridor_above in order:
        if c < 0 or c >= len(plan.lanes) or item not in plan.lanes[c]:
            continue
        lanes = plan.lanes[c]
        found: list[_Tap] = []
        # An item may occupy SEVERAL lanes in one corridor -- deliberately, when
        # the corridor is tapped from both sides: a copy near the top serves the
        # row above and a copy near the bottom serves the row below, because no
        # single lane is within reach of both once the corridor is deeper than
        # ``2 * reach - 1``.  Taking ``lanes.index(item)`` returned the FIRST
        # copy regardless of which side was asking, so a row needing the bottom
        # copy was handed the top one at a span far beyond reach, failed the
        # test, and silently got no sorter for that ingredient at all.
        for j, carried in enumerate(lanes):
            if carried != item:
                continue
            lane_y = corr_y[c] + j
            if from_corridor_above:
                span, machine_y = top - lane_y, top
            else:
                span, machine_y = lane_y - bottom, bottom
            if 1 <= span <= CONSTANTS.sorter_max_reach:
                found.append(
                    _Tap(
                        corridor=c,
                        depth=j,
                        lane_y=lane_y,
                        machine_y=machine_y,
                        span=span,
                    )
                )
        if not found:
            continue
        # Nearest first, then outward along the band, stopping at ``want``.
        # Sorting by span walks away from the tapping row, which is the
        # direction the parallel copies lie in; anything beyond ``want`` is the
        # other band's copy of the same stream and is not ours to take.
        found.sort(key=lambda t: (t.span, t.depth))
        return sorted(found[:want], key=lambda t: t.depth)
    return []


def _place_sorters(
    buildings: list[PlacedBuilding],
    lane: list[int],
    machines: list[int],
    *,
    lane_y: int,
    machine_y: int,
    tier: int,
    per_machine: int,
    into_machine: bool,
) -> int:
    """Connect a lane to EVERY machine of a group, ``per_machine`` sorters each.

    Anchors sit on the connected tiles and the ``input_obj`` / ``output_obj``
    indices carry the real semantics -- which is how the game itself does it.
    Measured on real blueprints, a sorter's anchors never coincide with a belt
    *building*, so sorters are overlays and do not consume build tiles.
    """
    model_index = catalog.building(tier).model_index
    placed = 0
    for m_idx in machines:
        m = buildings[m_idx]
        used: set[int] = set()
        for i in range(per_machine):
            # ONE column for both anchors.  This sorter is vertical -- the lane
            # sits in a corridor above or below the machine row -- so the two
            # anchors must share an x.  Deriving the belt side from
            # ``m.x + min(i, width - 1)`` while anchoring the machine side at
            # bare ``m.x`` skewed every sorter after the first by exactly that
            # offset, which is why 100 of 118 came out diagonal with dx of only
            # ever 1 or 2.
            x = _shared_column(buildings, lane, m, prefer=i, avoid=used)
            if x is None:
                continue
            belt_idx = _lane_tile_at(buildings, lane, x)
            if belt_idx is None:
                continue
            used.add(x)
            if into_machine:
                src, dst = belt_idx, m_idx
                ax, ay, bx, by = x, lane_y, x, machine_y
            else:
                src, dst = m_idx, belt_idx
                ax, ay, bx, by = x, machine_y, x, lane_y
            buildings.append(
                PlacedBuilding(
                    item_id=tier,
                    model_index=model_index,
                    x=ax,
                    y=ay,
                    width=1,
                    height=1,
                    x2=bx,
                    y2=by,
                    z2=0,
                    yaw=Facing.SOUTH.value if lane_y < machine_y else Facing.NORTH.value,
                    yaw2=Facing.SOUTH.value if lane_y < machine_y else Facing.NORTH.value,
                    input_obj=src,
                    output_obj=dst,
                )
            )
            placed += 1
    return placed


def _coater_lane_candidates(
    lane_tiles: dict[tuple[int, int], list[int]],
    lane_item_of: dict[tuple[int, int], str],
    item: str,
    prolif: str | None,
) -> list[tuple[tuple[int, int], list[int]]]:
    """Lanes carrying ``item``, reachable-from-proliferator ones first."""
    keys = [k for k, v in lane_item_of.items() if v == item and lane_tiles.get(k)]
    if prolif is None:
        return [(k, lane_tiles[k]) for k in keys]
    supply: dict[int, list[int]] = defaultdict(list)
    for (c, depth), _ in lane_tiles.items():
        if lane_item_of.get((c, depth)) == prolif:
            supply[c].append(depth)

    def reachable(k: tuple[int, int]) -> int:
        c, depth = k
        spans = [abs(depth - p) for p in supply.get(c, [])]
        return 0 if any(1 <= s <= CONSTANTS.sorter_max_reach for s in spans) else 1

    return [(k, lane_tiles[k]) for k in sorted(keys, key=reachable)]


def _coater_tile(
    buildings: list[PlacedBuilding],
    lane: list[int],
    lane_tiles: dict[tuple[int, int], list[int]],
    lane_item_of: dict[tuple[int, int], str],
    corridor: int,
    prolif: str | None,
) -> int:
    """Index of the lane tile to mount a coater on.

    Prefers a column the corridor's proliferator lane also covers, so the feed
    sorter has somewhere to come from; falls back to the lane midpoint when no
    such column exists, leaving the validator to report the unfed coater rather
    than hiding it.
    """
    midpoint = lane[len(lane) // 2]
    if prolif is None:
        return midpoint
    supply_xs: set[int] = set()
    for (c, depth), indices in lane_tiles.items():
        if c == corridor and lane_item_of.get((c, depth)) == prolif:
            supply_xs |= {buildings[i].x for i in indices}
    if not supply_xs:
        return midpoint
    shared = [i for i in lane if buildings[i].x in supply_xs]
    if not shared:
        return midpoint
    want = buildings[midpoint].x
    return min(shared, key=lambda i: abs(buildings[i].x - want))


def _feed_coater(
    buildings: list[PlacedBuilding],
    lane_tiles: dict[tuple[int, int], list[int]],
    lane_item_of: dict[tuple[int, int], str],
    *,
    coater_idx: int,
    corridor: int,
    coater_depth: int,
    corr_y: list[int],
    prolif: str | None,
) -> int:
    """Run a sorter from the corridor's proliferator lane into a coater.

    Both ends sit in the same corridor, so the span is the difference in lane
    depth and the sorter stays vertical -- which it must, since sorters cannot
    change altitude and cannot run diagonally.  Returns the number placed (0 or
    1) rather than raising: a corridor with no proliferator lane in reach is
    reported by the validator, which is more useful than aborting the layout.
    """
    if prolif is None:
        return 0
    coater = buildings[coater_idx]
    for (c, depth), indices in lane_tiles.items():
        if c != corridor or lane_item_of.get((c, depth)) != prolif or not indices:
            continue
        span = abs(depth - coater_depth)
        if not 1 <= span <= CONSTANTS.sorter_max_reach:
            continue
        source = _lane_tile_at(buildings, indices, coater.x)
        if source is None:
            continue
        tier = SORTER_TIERS[0]  # rate is negligible; cheapest tier suffices
        buildings.append(
            PlacedBuilding(
                item_id=tier,
                model_index=catalog.building(tier).model_index,
                x=coater.x,
                y=corr_y[c] + depth,
                width=1,
                height=1,
                x2=coater.x,
                y2=coater.y,
                z2=0,
                yaw=Facing.SOUTH.value,
                yaw2=Facing.SOUTH.value,
                input_obj=source,
                output_obj=coater_idx,
            )
        )
        return 1
    return 0


def _shared_column(
    buildings: list[PlacedBuilding],
    lane: list[int],
    machine: PlacedBuilding,
    *,
    prefer: int,
    avoid: set[int] | None = None,
) -> int | None:
    """An x covered by both the machine's footprint and the lane.

    A straight-line sorter needs one column, not two.  ``prefer`` spreads
    successive sorters across the machine's width and ``avoid`` keeps two
    sorters on the same machine off the same column.  Returns ``None`` rather
    than emitting a sorter whose ends do not line up.
    """
    lane_xs = {buildings[i].x for i in lane}
    if not lane_xs:
        return None
    taken = avoid or set()
    covered = [
        machine.x + d
        for d in range(machine.width)
        if machine.x + d in lane_xs and machine.x + d not in taken
    ]
    if not covered:
        return None
    wanted = machine.x + max(0, min(prefer, machine.width - 1))
    return min(covered, key=lambda x: abs(x - wanted))


def _lane_tile_at(buildings: list[PlacedBuilding], lane: list[int], x: int) -> int | None:
    """The lane's belt tile at column ``x``, or ``None``.

    No fallback to ``lane[0]``: returning a tile in a different column made the
    sorter's anchor disagree with the belt it actually connects to, which is a
    second way to produce a diagonal.
    """
    for idx in lane:
        if buildings[idx].x == x:
            return idx
    return None


#: Extra tiles charged beyond half an interior corridor.
#:
#: Measured, not assumed: powered buildings sit deeper into a corridor than the
#: midpoint, because a sorter tapping the deepest lane it can reach lands one
#: tile past it.  Across the corpus the deepest powered building sat 4 tiles into
#: an 8-lane corridor and 6 into a 9-lane one -- ``ceil(h/2) + 1`` in both cases.
#: Without this margin a sorter in casimir-crystal landed 10.82 tiles from its
#: nearest tower against a 10.5 radius, which the validator caught.
_CORRIDOR_DEPTH_MARGIN = 1


def _max_dy() -> int:
    """Largest vertical offset at which a tower still has positive reach."""
    return len(_REACH_TABLE) - 2


def _top_band_height(row_heights: list[int], corridor_heights: list[int]) -> int:
    """Height of a dedicated tower band above the top corridor, or 0.

    Needed when row 0's towers cannot reach the deepest powered building in the
    top corridor.  Interior corridors are shared between two rows; the top one is
    not, and measurement shows sorters do tap its deepest lane, so nothing
    covers the far side unless a band is added.
    """
    if not row_heights or not corridor_heights:
        return 0
    _tw, th = CONSTANTS.tower_size
    reach_needed = math.ceil(row_heights[0] / 2) + corridor_heights[0]
    return th if reach_needed > _max_dy() else 0


def _corridor_charge(
    ci: int, corridor_heights: list[int], *, has_top_band: bool = False
) -> int:
    """Vertical distance a bordering row's towers must cover into corridor ``ci``.

    Corridor ``ci`` lies between row ``ci - 1`` above it and row ``ci`` below it,
    so an *interior* corridor is bordered by two rows, each with its own towers.
    Neither row has to reach the far edge: each covers its own half and they meet
    in the middle.  Only the first and last corridors have a single neighbour and
    must be covered outright.

    Charging every row the full height of its corridors was the bug.  It is
    harmless while corridors are short -- the 9-group calibration spec never
    exceeds a few lanes -- but a 27-group build reaches 14-lane corridors, and
    charging those in full put 21 of 27 rows past the 10.5-tile supply radius, so
    Strategy A could not lay out a real URL at all.
    """
    height = corridor_heights[ci]
    shared = 0 < ci < len(corridor_heights) - 1 or (ci == 0 and has_top_band)
    if not shared:
        return height
    return min(height, math.ceil(height / 2) + _CORRIDOR_DEPTH_MARGIN)


def _horizontal_reach(r: int, row_heights: list[int], corridor_heights: list[int]) -> int:
    """Horizontal supply reach available to a tower sitting in row ``r``.

    A tower in row ``r`` must also power the sorters and spray coaters in the
    corridors on either side, so the worst-case vertical offset is half the row
    height plus its share of the taller neighbouring corridor.  Evaluating the
    circle at that offset is exact, unlike an inscribed square.

    Half the row height is only correct because ``_emit`` centres the tower
    vertically within its row; a tower at the row's top edge would be
    ``row_height - 1`` from the far side, which for an 11-tall row is already the
    whole radius before any corridor is counted.
    """
    table = _REACH_TABLE
    top_band = bool(_top_band_height(row_heights, corridor_heights))
    above = (
        _corridor_charge(r, corridor_heights, has_top_band=top_band)
        if r < len(corridor_heights)
        else 0
    )
    below = (
        _corridor_charge(r + 1, corridor_heights, has_top_band=top_band)
        if r + 1 < len(corridor_heights)
        else 0
    )
    dy_max = math.ceil(row_heights[r] / 2) + max(above, below)

    # Clamp rather than refuse.  A boundary corridor has only one neighbouring
    # row, so a very tall one can exceed the radius outright -- but returning the
    # tightest positive spacing still produces a layout, and the validator's
    # power.coverage check decides whether it is actually good enough.  Raising
    # here instead meant a whole candidate was thrown away over a corridor whose
    # deep lanes are pass-through belts, which are unpowered anyway.
    #
    # This deliberately trades a hard failure for one the neutral judge catches:
    # it can under-cover, never silently -- an under-covered build is rejected by
    # the validator before it is ever emitted as a blueprint.
    clamped = min(dy_max, len(table) - 2)
    hr = table[clamped]
    if hr <= 0:
        raise ValueError(f"row {r} is uncoverable at vertical offset {dy_max}")
    return hr


def _nearest_free(
    gx: int, gy: int, occupied: set[tuple[int, int]], radius: float
) -> tuple[int, int] | None:
    """The unoccupied tile closest to ``(gx, gy)`` and within ``radius`` of it.

    Rings expand in Chebyshev distance but the acceptance test is EUCLIDEAN: a
    tower at the corner of a ring of side 10 is 14.1 tiles away, so it would not
    actually cover the tile it was placed for.  Filtering on the ring index alone
    silently produced towers that powered nothing.
    """
    limit = int(radius)
    for ring in range(limit + 1):
        best: tuple[float, tuple[int, int]] | None = None
        for dx in range(-ring, ring + 1):
            for dy in range(-ring, ring + 1):
                if ring and max(abs(dx), abs(dy)) != ring:
                    continue  # interior of this ring was covered by a smaller one
                dist = math.hypot(dx, dy)
                if dist > radius:
                    continue
                spot = (gx + dx, gy + dy)
                if spot in occupied:
                    continue
                if best is None or dist < best[0]:
                    best = (dist, spot)
        if best is not None:
            return best[1]
    return None


def _top_up_coverage(buildings: list[PlacedBuilding], tower_model: int) -> tuple[int, int]:
    """Add towers until every powered building is genuinely inside a supply radius.

    Verification rather than prediction.  ``_horizontal_reach`` budgets a
    worst-case offset and spaces towers accordingly, which holds for machines
    and sorters but not for Spray Coaters -- those mount on whichever lane needs
    spraying, at any corridor depth, so no analytic bound covers them.

    Coverage is measured over EVERY tile of a building's footprint, not its
    centre, matching ``validate.power.coverage``.  Belts are unpowered and skipped;
    a tower is placed only on a tile nothing else occupies, so this can never
    introduce an overlap.

    Returns ``(towers_added, still_uncovered)``.  The second number must reach
    the caller: a building with no free tile within a radius of it cannot be
    powered at all, and swallowing that would be exactly the silent degradation
    ``fallback_reason`` exists to prevent.
    """
    radius = float(CONSTANTS.supply_radius)
    occupied: set[tuple[int, int]] = set()
    for b in buildings:
        try:
            if not catalog.building(b.item_id).occupies_tiles:
                continue
        except KeyError:
            continue
        for dx in range(b.width):
            for dy in range(b.height):
                occupied.add((b.x + dx, b.y + dy))

    towers = [(b.x, b.y) for b in buildings if b.item_id == CONSTANTS.tesla_item_id]

    def covered(tx: int, ty: int) -> bool:
        return any(math.hypot(tx - ox, ty - oy) <= radius for ox, oy in towers)

    added = 0
    unfixable = 0
    for b in list(buildings):
        if catalog.is_belt(b.item_id) or b.item_id == CONSTANTS.tesla_item_id:
            continue
        gaps = [
            (b.x + dx, b.y + dy)
            for dx in range(b.width)
            for dy in range(b.height)
            if not covered(b.x + dx, b.y + dy)
        ]
        if not gaps:
            continue
        gx, gy = gaps[0]
        # Nearest free tile, searched outward, so the tower lands beside the
        # thing it powers rather than somewhere that inflates the bounding box.
        spot = _nearest_free(gx, gy, occupied, radius)
        if spot is None:
            unfixable += 1
            continue
        occupied.add(spot)
        towers.append(spot)
        buildings.append(
            PlacedBuilding(
                item_id=CONSTANTS.tesla_item_id,
                model_index=tower_model,
                x=spot[0],
                y=spot[1],
                width=1,
                height=1,
            )
        )
        added += 1
    return added, unfixable


def _link_towers(buildings: list[PlacedBuilding], tower_model: int) -> int:
    """Add relay towers until every tower is in one network.  Returns how many.

    The coverage top-up places a tower beside whatever it found stranded, and in
    the riser margin that can be far from anything -- on casimir-crystal a tower
    covering a junction landed 24.2 tiles from its nearest neighbour against a
    22.5-tile link distance, so it powered the splitter and nothing powered it.

    Repaired by stepping toward the network rather than by refusing: a tower
    placed on the segment between the stranded one and its nearest linked
    neighbour halves the gap, so a bounded number of steps always closes it.
    ``power.connectivity`` still judges the result.
    """
    link = float(CONSTANTS.link_distance)
    occupied: set[tuple[int, int]] = set()
    for b in buildings:
        try:
            if not catalog.building(b.item_id).occupies_tiles:
                continue
        except KeyError:
            continue
        for dx in range(b.width):
            for dy in range(b.height):
                occupied.add((b.x + dx, b.y + dy))

    towers = [
        (b.x + b.width / 2, b.y + b.height / 2)
        for b in buildings
        if b.item_id == CONSTANTS.tesla_item_id
    ]
    added = 0
    # Bounded: every pass either links a tower or gives up on it, and each relay
    # halves a finite gap, so this cannot spin.
    for _ in range(4 * len(towers) + 1):
        seen = {0} if towers else set()
        frontier = [0] if towers else []
        while frontier:
            i = frontier.pop()
            for j, t in enumerate(towers):
                if j not in seen and math.dist(towers[i], t) <= link:
                    seen.add(j)
                    frontier.append(j)
        stray = [j for j in range(len(towers)) if j not in seen]
        if not stray:
            break
        j = stray[0]
        near = min(seen, key=lambda k: math.dist(towers[j], towers[k]))
        sx, sy = towers[j]
        nx, ny = towers[near]
        spot = _nearest_free(
            int((sx + nx) / 2), int((sy + ny) / 2), occupied, link / 2
        )
        if spot is None:
            break  # nowhere to stand; the validator reports the split network
        occupied.add(spot)
        towers.append((spot[0] + 0.5, spot[1] + 0.5))
        buildings.append(
            PlacedBuilding(
                item_id=CONSTANTS.tesla_item_id,
                model_index=tower_model,
                x=spot[0],
                y=spot[1],
                width=1,
                height=1,
            )
        )
        added += 1
    return added


def _bbox_area(buildings: list[PlacedBuilding]) -> int:
    if not buildings:
        return 0
    xs = [b.x for b in buildings] + [b.x + b.width - 1 for b in buildings]
    ys = [b.y for b in buildings] + [b.y + b.height - 1 for b in buildings]
    return (max(xs) - min(xs) + 1) * (max(ys) - min(ys) + 1)


class SpineLayout:
    """Structured-spine layout strategy."""

    name = "spine"

    def __init__(self, *, power: bool = True, workers: int | None = None) -> None:
        self.power = power
        #: CP-SAT search workers. ``None`` takes the module default (all
        #: cores); the bake-off pins ``DETERMINISTIC_WORKERS`` for
        #: reproducibility.
        self.workers = DEFAULT_SEARCH_WORKERS if workers is None else workers

    def lay_out(self, spec: BuildSpec, *, time_budget_s: float = 60.0) -> Placement:
        """Return a solved, emitted ``Placement``, or raise :class:`NoValidLayout`.

        There used to be a fallback here.  A solver plan that turned out to be
        unroutable degraded to :func:`fallback_plan`'s greedy stacking, and this
        method promised it "always returns a valid Placement".  The promise was
        false -- the greedy plan is not routable either -- so the degradation
        traded a visible failure for an invisible one, and did it while
        *shrinking* the reported area, because a lane that was never wired is a
        corridor that does not exist.

        :func:`fallback_plan` still runs on every solve, in the role it is
        actually good at: warm start and width-sweep seed inside
        :func:`_solve_plan`.  Same construction, opposite role -- bounding the
        search instead of replacing it.

        A budget that finds nothing feasible is retried ONCE at
        :data:`RETRY_BUDGET_S` before refusing.  Deterministic refusals (no
        budget, empty spec) skip the retry: repeating them cannot change them.
        """
        if time_budget_s <= 0:
            raise NoValidLayout(
                _refusal(FALLBACK_NO_BUDGET),
                spec_label=spec.label,
                budget_s=time_budget_s,
            )

        budgets = [time_budget_s]
        if time_budget_s < RETRY_BUDGET_S:
            budgets.append(RETRY_BUDGET_S)

        reason = FALLBACK_NO_SOLUTION
        spent = 0.0
        for budget in budgets:
            spent = budget
            try:
                plan, reason = _solve_plan(
                    spec, time_budget_s=budget, workers=self.workers
                )
                if plan is None:
                    if reason == FALLBACK_EMPTY_SPEC:
                        break  # deterministic -- more seconds cannot help
                    continue
                # Emission stays inside the guard on purpose.  A direct insert
                # the solver believed in may turn out to have no machine pair
                # within reach once real x positions exist, and dropping that
                # lane without emitting its replacement sorter would starve the
                # consumer.  So a plan that will not emit is not a layout: retry
                # it under a longer budget, and refuse if that fails too.
                placement = _emit(spec, plan, power=self.power)
            except (ValueError, KeyError):
                reason = FALLBACK_EMISSION
                continue
            placement.stats["solver_rejected"] = 0.0
            placement.stats["fallback_reason"] = FALLBACK_NONE
            return placement

        raise NoValidLayout(_refusal(reason), spec_label=spec.label, budget_s=spent)


def machine_group_footprint(group: MachineGroup) -> tuple[int, int]:
    """Footprint of the building a ``MachineGroup`` runs on, in tiles."""
    item_id = MACHINE_ITEM_IDS[group.machine_item_id]
    return catalog.footprint(item_id)
