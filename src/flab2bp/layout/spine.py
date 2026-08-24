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
* One item per lane -- **except** where that will not fit.  A row taps two
  corridors and a sorter reaches 3 lanes into each, so six LANES is a hard cap;
  ``universe-matrix`` takes five matrices plus antimatter and makes a product,
  which is seven ITEMS.  Two items ride one lane with each tapping sorter
  filtered to its own item, which cuts lanes without cutting items.  Tried only
  after one-per-lane fails, so every spec that already fits keeps its exact
  shape -- measured identical in area and building count on all 66 other corpus
  cells.  See :func:`_shareable` for the terms and
  :func:`_merge_shared_risers` for the trunk the two items have to share.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from fractions import Fraction

from ortools.sat.python import cp_model

from flab2bp.dsp import catalog, params
from flab2bp.layout import junction, validate
from flab2bp.layout import slots as sorter_slots
from flab2bp.layout.base import (
    DEFAULT_SEARCH_WORKERS,
    RETRY_BUDGET_S,
    Facing,
    NoValidLayout,
    PlacedBuilding,
    Placement,
)
from flab2bp.layout.geometry import band_offsets, height_waste, lane_order, reach_table
from flab2bp.layout.slots import SlotUndetermined, assign_sorter_slots
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


#: Pack every machine in a row at the row's widest clearance, or at each type's
#: own?  Set by measurement -- see the note beside it where it is read.
UNIFORM_ROW_PITCH = False


def _charged_pitch(groups: dict[str, _Group], key: str) -> int:
    """The pitch the width model charges ``key``, matching what `_pack_row` does.

    Under uniform pitch a row's width depends on WHICH types share it, which is
    not linear in the row-membership variables CP-SAT has -- so the model is
    charged the widest pitch in the build. That over-states a row of narrow
    machines and never under-states one, which is the safe direction for a bound.
    """
    if not UNIFORM_ROW_PITCH:
        return groups[key].pitch_w
    return max((g.pitch_w for g in groups.values()), default=1)

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
    #: Grid extents AS BUILT -- already swapped when ``yaw`` is a quarter turn,
    #: so nothing downstream has to remember to swap them.
    width: int
    height: int
    #: Which way this machine is turned.  Chosen from its own insert poses by
    #: :func:`flab2bp.layout.slots.lane_orientation`, because a building with no
    #: pose facing the lane cannot be wired at all however it is packed.
    yaw: float
    #: Tiles to RESERVE per machine, from the rotated collider -- see
    #: `catalog.clearance`.  An Assembling Machine covers 3 tiles and needs 4,
    #: because its 3.82-unit collider does not fit a 3-tile pitch at 1.2566
    #: units per tile.  Packing uses these; everything geometric uses
    #: `width`/`height`, which stay the tiles the building actually covers.
    pitch_w: int
    pitch_h: int
    inputs: dict[str, Fraction]
    outputs: dict[str, Fraction]
    proliferated: bool

    @property
    def block_width(self) -> int:
        return self.pitch_w * self.count


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
    #: ``(corridor, depth) -> every item riding that lane``, for the lanes that
    #: carry more than one.  ``lanes`` keeps the lane's PRIMARY item -- the label
    #: the belt is emitted with -- so everything that only needs one name is
    #: unchanged, and everything that has to know the truth asks
    #: :func:`_lane_items`.  See :func:`_shareable` for why a lane may be shared
    #: at all.
    mixed: dict[tuple[int, int], tuple[str, ...]] = field(default_factory=dict)
    direct: set[tuple[str, str, str]] = field(default_factory=set)
    solver_status: str = "fallback"
    hit_budget: bool = False
    #: True when this packing forced ``_lane_requirements`` to give up splitting
    #: an over-capacity item across parallel lanes.  It is a PREFERENCE ORDER,
    #: nothing more: ``_solve_plan`` sorts degraded plans last so an undegraded
    #: width always wins.
    #:
    #: This said "the build will ship with an honest ``flow.belt_capacity``
    #: error.  Still worth emitting -- a build reported as too slow can be
    #: pasted and widened by hand and a build that does not exist cannot."
    #: That argument is dead, and it was self-defeating even when written:
    #: ``flow.belt_capacity`` is ``Severity.ERROR``, ``_rejected`` returns
    #: ``certify``'s errors, and ``lay_out`` turns any non-empty result into
    #: ``FALLBACK_SELF_CHECK``.  A plan that really is over capacity is REFUSED,
    #: not shipped -- so the trade it describes was never available.
    #:
    #: Giving up the split is still worth trying, because a looser allocation
    #: often turns out to be under capacity after all and then certifies clean.
    #: What is not on offer is emitting one that is not.  Do not restore the
    #: reasoning above; it reads as sanctioning a fallback and the project has
    #: deleted two of those.
    degraded: bool = False


def _lane_items(plan: _Plan, c: int, depth: int) -> tuple[str, ...]:
    """Every item lane ``depth`` of corridor ``c`` carries, primary first."""
    return plan.mixed.get((c, depth)) or (plan.lanes[c][depth],)


def _share_column(plan: _Plan, c: int, depth: int, item: str) -> int:
    """How far along a machine ``item``'s sorters start on this lane.

    Zero for a lane with one item on it, which is every lane on every spec that
    does not need sharing.  On a shared lane each item gets its own column, and
    both the lane's extent and the sorter pass derive it from here so the two
    cannot disagree about which column a sorter will stand in.
    """
    carried = _lane_items(plan, c, depth)
    return carried.index(item) if len(carried) > 1 and item in carried else 0


def _adapt(spec: BuildSpec) -> tuple[dict[str, _Group], list[_Edge]]:
    """Resolve a ``BuildSpec`` into DSP-id groups and a producer/consumer graph."""
    groups: dict[str, _Group] = {}
    for i, mg in enumerate(spec.groups):
        item_id = MACHINE_ITEM_IDS.get(mg.machine_item_id)
        if item_id is None:
            raise KeyError(f"no DSP building known for machine {mg.machine_item_id!r}")
        b = catalog.building(item_id)
        key = f"{mg.recipe_id}#{i}"
        yaw = sorter_slots.lane_orientation(item_id)
        w, h = catalog.oriented_footprint(item_id, yaw)
        pw, ph = catalog.clearance(item_id, yaw)
        groups[key] = _Group(
            key=key,
            recipe_id=mg.recipe_id,
            item_id=item_id,
            model_index=b.model_index,
            count=mg.count,
            width=w,
            height=h,
            yaw=yaw,
            pitch_w=pw,
            pitch_h=ph,
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
    return {
        item: max(1, math.ceil(rate / cap))
        for item, rate in _item_flow(groups, edges, direct, spec).items()
    }


def _item_flow(
    groups: dict[str, _Group],
    edges: list[_Edge],
    direct: set[tuple[str, str, str]],
    spec: BuildSpec,
) -> dict[str, Fraction]:
    """Items/s each item has to move on belt, after direct inserts are removed.

    The larger of supply and demand, because a lane has to carry whichever end
    is bigger: a surplus still has to reach the edge and a shortfall still has
    to reach the machines.  Shared by :func:`_lane_copies`, which turns it into
    parallel lanes, and by :func:`_shareable`, which uses it to refuse a pairing
    two items would overload one belt with.
    """
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
        item: max(supply[item], demand.get(item, Fraction(0)))
        for item in set(supply) | set(demand)
    }


def _lane_filter(item: str) -> int:
    """The DSP item id a sorter on a SHARED lane must filter to.

    Raises rather than falling back to zero, exactly as freeform's namesake
    does: an unfiltered sorter on a shared lane grabs whatever passes and
    starves the machine that wanted the other item, and the blueprint still
    pastes perfectly cleanly.  :func:`_shareable` refuses to pair an item this
    would raise on, so reaching the raise is a bug rather than a spec's fault.
    """
    got = catalog.get_item_id(item)
    if got is None:
        raise KeyError(
            f"{item!r} shares a belt lane but has no DSP item id, so its sorter "
            f"cannot be filtered; it would take whatever passed instead"
        )
    return got


def _shareable(
    groups: dict[str, _Group],
    edges: list[_Edge],
    direct: set[tuple[str, str, str]],
    spec: BuildSpec,
    copies: dict[str, int],
) -> dict[str, tuple[str, Fraction]]:
    """Items that may ride a lane with a second item, and on what terms.

    A row touches two corridors and a sorter reaches ``sorter_max_reach`` lanes
    into each, so a machine can tap **six LANES** whatever is packed around it.
    ``universe-matrix`` wants seven ITEMS.  Two items on one lane, each tapping
    sorter filtered to its own item, cuts the lane count without cutting the
    item count -- which is exactly the quantity that is over budget.  Freeform
    has done this since ``six_input_spec`` and the validator already reads it:
    ``_sorter_item`` trusts ``filter_id`` above every other source.

    The value is ``(kind, flow)``.  ``kind`` is what the lane's ENDS look like
    and whether a coater has to ride it, and only items whose kinds match may
    share -- the ends are the only way anything gets onto the belt, and a coater
    sprays everything that passes it rather than a chosen item:

    * ``external`` -- the player feeds it at ``x = 0``.  Two external items on
      one lane are two things the player puts on one belt, which is what
      ``validate._entry_items`` was taught to expect.
    * ``internal`` -- one producer group, one consumer group, so the item has
      exactly one source lane and one destination lane and therefore exactly one
      trunk.  Two such trunks that must deliver into the SAME lane are merged
      into one by :func:`_merge_shared_risers`; more than one destination each
      and the merged trunk would leak the other item onto a lane no sorter
      filters it off, which stalls the belt with nothing to see it.
    * the ``sprayed`` suffix keeps a proliferated item off a plain item's lane.
      Two sprayed items share happily -- a coater on their lane is exactly what
      they both wanted -- but pairing one with an unsprayed item would either
      coat something the rate solve costed unproliferated or strand a coater.

    Everything else is refused rather than reasoned about:

    * an item needing parallel lanes -- ``_lane_copies`` already spent the
      corridor on it, and pairing a split lane would make the trunk ranks
      disagree at the two ends;
    * the proliferator itself, whose lane is a pass-through utility that no
      machine taps and that ``_cover_sprayed`` may duplicate at a band boundary;
    * an item leaving the block, which owns its lane's east or west end;
    * an item with no DSP id, which :func:`_lane_filter` could not filter.

    Note this says which items MAY share, not which will.  The caller adds the
    decisive restriction: only an item the seating row CONSUMES is ever put on a
    shared lane, so a shared lane is only ever a trunk's destination.  A shared
    SOURCE would need one trunk to serve two different destinations, and the
    second item would arrive on a lane whose sorters filter it out.
    """
    prolif = proliferator_item(spec)
    leaving = _leaving_items(groups, spec)
    flow = _item_flow(groups, edges, direct, spec)
    sprayed = set(spec.spray_lanes)
    producers: dict[str, int] = defaultdict(int)
    consumers: dict[str, int] = defaultdict(int)
    for g in groups.values():
        for item in g.outputs:
            producers[item] += 1
        for item in g.inputs:
            consumers[item] += 1

    out: dict[str, tuple[str, Fraction]] = {}
    for item in set(producers) | set(consumers) | set(spec.external_inputs):
        if copies.get(item, 1) != 1:
            continue
        if item == prolif or item in leaving:
            continue
        if catalog.get_item_id(item) is None:
            continue
        coat = ":sprayed" if item in sprayed else ""
        rate = flow.get(item, Fraction(0))
        if item in spec.external_inputs:
            # An externally fed item that is ALSO sprayed keeps its own lane.
            # A coater is found by the lane's primary item, and such an item has
            # no second lane to find one on -- it enters at ``x = 0`` on the
            # shared lane and nowhere else -- so riding along could leave it
            # uncoated while the rate solve had costed it proliferated.  An
            # internal one is safe: its source lane is unshared and carries the
            # coater, so it arrives already sprayed.
            if not coat:
                out[item] = ("external", rate)
        elif producers[item] == 1 and consumers[item] == 1:
            out[item] = ("internal" + coat, rate)
    return out


def _lane_requirements(
    groups: dict[str, _Group],
    edges: list[_Edge],
    rows: list[list[str]],
    direct: set[tuple[str, str, str]],
    spec: BuildSpec,
) -> tuple[list[list[str]], dict[tuple[int, int], tuple[str, ...]], dict[str, int]]:
    """Corridor lanes, and how many parallel copies each item ended up with.

    Splitting an over-capacity item across parallel lanes deepens a corridor,
    and a corridor deep enough to put a lane out of sorter reach cannot be wired
    at all.  When that happens the split is given up and the flatter allocation
    is tried instead, because it is frequently under capacity anyway once the
    lanes are actually laid out -- and then it certifies clean.

    Measured: without this retry, splitting ``quantum-chip``'s 48/s crude-oil and
    refined-oil onto two lanes each made the no-proliferator candidate refuse
    outright.

    **This is not permission to emit an over-capacity build.**  The docstring
    used to argue that "one lane and an honest ``flow.belt_capacity`` error is
    worth more than a refusal, because a build reported as too slow can still be
    pasted and widened by hand".  That trade does not exist:
    ``flow.belt_capacity`` is ``Severity.ERROR``, ``_rejected`` returns
    ``certify``'s errors, and ``lay_out`` refuses on any of them.  A flatter
    allocation that is genuinely over capacity is refused exactly like the
    unwirable one -- the retry buys the cases that turn out to FIT, and nothing
    else.  ``_Plan.degraded`` records which happened so an undegraded width
    always wins the sort.
    """
    wanted = _lane_copies(groups, edges, direct, spec)
    if any(v > 1 for v in wanted.values()):
        try:
            lanes, mixed = _allocate_lanes(groups, edges, rows, direct, spec, wanted)
        except ValueError:
            pass
        else:
            return lanes, mixed, wanted
    flat = dict.fromkeys(wanted, 1)
    lanes, mixed = _allocate_lanes(groups, edges, rows, direct, spec, flat)
    return lanes, mixed, flat


def _allocate_lanes(
    groups: dict[str, _Group],
    edges: list[_Edge],
    rows: list[list[str]],
    direct: set[tuple[str, str, str]],
    spec: BuildSpec,
    copies: dict[str, int],
) -> tuple[list[list[str]], dict[tuple[int, int], tuple[str, ...]]]:
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
    shareable = _shareable(groups, edges, direct, spec, copies)
    cap = belt_capacity(spec)
    #: ``(corridor, is_above_band) -> {host item: the item riding its lane}``.
    #: Recorded per BAND because a corridor's top band is tapped only by the row
    #: above it and its bottom band only by the row below, so a host name is
    #: unambiguous within one band even when the same item holds a lane in both.
    mix_by_band: dict[tuple[int, bool], dict[str, str]] = defaultdict(dict)

    for r in range(len(rows)):
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
        row_h = max((groups[k].pitch_h for k in rows[r]), default=1)
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
        ordered_items = sorted(prefers_above, key=lambda i: (-gaps.get(i, 0), i))
        # Every machine on this row needs its own anchor COLUMN per item it draws
        # off a shared lane -- two sorters serving one machine from one belt
        # cannot stand in the same column -- so the narrowest machine on the row
        # bounds how much sharing is physical.  Two items per lane needs two.
        widest_share = min((groups[k].width for k in rows[r]), default=1)

        def _seat(
            allow_mix: bool,
            gap_first: bool,
            items: list[str] = ordered_items,
            prefers: dict[str, bool] = prefers_above,
            gaps: dict[str, int] = gaps,
            share_cap: int = widest_share,
            drawn: frozenset[str] = frozenset(consumes[r] - produces[r]),
        ) -> tuple[set[str], set[str], dict[str, str], dict[str, str]] | None:
            """Seat every item this row taps, one per lane unless ``allow_mix``.

            One item per lane is tried FIRST and mixing only opens what that
            cannot reach, which is freeform's rule and worth copying for the
            same reason: every spec that already fits keeps the exact shape it
            had, so sharing can add territory but never trade any away.
            """
            below: set[str] = set()  # corridor r, tapped from below by this row
            above: set[str] = set()  # corridor r + 1, tapped from above by it
            rides_below: dict[str, str] = {}
            rides_above: dict[str, str] = {}

            def _room(item: str, slot: set[str]) -> bool:
                if slot is below:
                    return sum(copies.get(i, 1) for i in slot) + copies.get(item, 1) <= reach
                return _fits_below(slot, item, gaps, reach, copies)

            def _compatible(a: str, b: str) -> bool:
                # Only an item this row DRAWS may share.  A lane the row fills is
                # a trunk's source, and one trunk carrying two items has to
                # deliver both to every stop it makes -- so a shared source would
                # put the other item on a lane whose sorters filter it out, where
                # it backs up behind them and stalls with nothing able to see it.
                if a not in drawn or b not in drawn:
                    return False
                ka, kb = shareable.get(a), shareable.get(b)
                # Equal gaps, because the two items end up at ONE depth: a lane
                # the shorter machine can reach is the only lane the pair can
                # take, and unequal gaps would put one of them out of reach of
                # the very sorter the sharing exists to place.
                return (
                    ka is not None
                    and kb is not None
                    and ka[0] == kb[0]
                    and ka[1] + kb[1] <= cap
                    and gaps.get(a, 0) == gaps.get(b, 0)
                )

            def _pair_off(slot: set[str], rides: dict[str, str]) -> bool:
                """Move two of ``slot``'s items onto one lane, freeing a lane."""
                taken = set(rides) | set(rides.values())
                loose = sorted(i for i in slot if i not in taken)
                for i, host in enumerate(loose):
                    for rider in loose[i + 1 :]:
                        if _compatible(host, rider):
                            slot.discard(rider)
                            rides[host] = rider
                            return True
                return False

            def _squeeze(item: str, slot: set[str], rides: dict[str, str]) -> bool:
                """Seat ``item`` in a full ``slot`` by sharing a lane somewhere.

                Two moves, and the second is the one that matters: the item that
                overflows is often not one that MAY share -- on
                ``universe-matrix`` it is the product, which owns its lane's exit
                -- while two of the ingredients already seated pair perfectly
                well and free the lane it needs.  Trying only "can the newcomer
                ride along" seats nothing on exactly the spec this exists for.
                """
                if share_cap < 2:
                    return False
                keep, kept = set(slot), dict(rides)
                taken = set(rides) | set(rides.values())
                if item not in taken:
                    for host in sorted(slot):
                        if host not in taken and _compatible(host, item):
                            rides[host] = item
                            return True
                while _pair_off(slot, rides):
                    if _room(item, slot):
                        slot.add(item)
                        return True
                slot.clear()
                slot |= keep
                rides.clear()
                rides.update(kept)
                return False

            for item in items:
                # A machine is flush with the TOP of its row, so the corridor
                # above it costs nothing however short the machine is, while
                # every lane in the corridor below is the machine's gap further
                # away.  Under ``gap_first`` an item carrying a gap therefore
                # goes up whatever the flow would prefer: leaving it to the
                # preference put two gapped items in one bottom band, where the
                # second sits ``gap + 2`` tiles down and no sorter reaches it.
                # Consume-above/produce-below is only a mild flow preference --
                # `_find_taps` tries both sides anyway -- and reach is not
                # negotiable, so where the two disagree reach wins.
                if prefers[item] or (gap_first and gaps.get(item, 0) > 0):
                    order = ((below, rides_below), (above, rides_above))
                else:
                    order = ((above, rides_above), (below, rides_below))
                target = next((s for s, _rides in order if _room(item, s)), None)
                if target is not None:
                    target.add(item)
                    continue
                if not allow_mix or not any(_squeeze(item, *pair) for pair in order):
                    return None
            return below, above, rides_below, rides_above

        # Four greedies, cheapest and most conservative first.  The first is the
        # allocation this function has always made, so any row that used to seat
        # still seats identically and the other three only ever open ground the
        # first could not reach: a band preference that respects reach ahead of
        # flow, and then lane sharing on top of each.
        seated = next(
            (
                s
                for mix, gap_first in ((0, 0), (0, 1), (1, 0), (1, 1))
                if (s := _seat(allow_mix=bool(mix), gap_first=bool(gap_first))) is not None
            ),
            None,
        )
        if seated is None:
            need = sum(copies.get(i, 1) for i in consumes[r] | produces[r])
            who = "+".join(rows[r])
            if need > 2 * reach:
                raise ValueError(
                    f"row {r} ({who}) taps {need} lanes, more than the "
                    f"{2 * reach} two corridors put within sorter reach"
                )
            raise ValueError(
                f"row {r} ({who}) taps {need} lanes that no ordering of its two "
                f"corridors puts in reach; machine heights differ by up to "
                f"{max(gaps.values(), default=0)} tiles"
            )
        slot_below, slot_above, rides_below, rides_above = seated
        if 0 <= r < n_corr:
            mix_by_band[r, False].update(rides_below)
        if 0 <= r + 1 < n_corr:
            mix_by_band[r + 1, True].update(rides_above)
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
    mixed: dict[tuple[int, int], tuple[str, ...]] = {}
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
        # Band position survives `_cover_sprayed`, which only ever inserts at a
        # band BOUNDARY -- so the top band is still `order[:len(above)]` and the
        # bottom band still `order[-len(below):]`, and a rider can be attached to
        # its host's depth by name within its own band.
        for band, span in (
            (True, range(len(above))),
            (False, range(len(order) - len(below), len(order))),
        ):
            riders = mix_by_band.get((c, band), {})
            for d in span:
                rider = riders.get(order[d])
                if rider is not None:
                    mixed[c, d] = (order[d], rider)
        ordered.append(order)
    return ordered, mixed


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
    lanes, mixed, _copies = _lane_requirements(groups, edges, rows, set(), spec)
    return _Plan(rows=rows, lanes=lanes, mixed=mixed, solver_status="fallback")


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
#: A group that cannot be wired even alone in its own row.  Distinct from
#: :data:`FALLBACK_UNROUTABLE`, which is about a *packing*: one group per row is
#: the loosest packing there is, so a row that fails there fails at every width,
#: and the limit is the RECIPE rather than the search.  Telling them apart is the
#: difference between "try a different width" and "this skeleton cannot hold this
#: recipe", and the two used to arrive as the same refusal -- in fact as
#: ``FALLBACK_EMISSION``, which was a plain lie: nothing had been emitted, and
#: nothing had even been solved.
FALLBACK_SEED_UNWIRABLE = 6.0
#: The placement was built and then FAILED ITS OWN VALIDATION.
#:
#: `lay_out` promises a valid `Placement` or an exception. That promise used to
#: be argued: a fallback was documented as always valid, was not, and returned a
#: layout that pasted cleanly and then did not run. Deleting the fallback helped
#: but did not make the promise true -- the solved path can be wrong too, and
#: nothing downstream was obliged to look. Now it looks, and a rejected
#: placement becomes a refusal.
FALLBACK_SELF_CHECK = 7.0

def _rejected(placement: Placement, spec: BuildSpec, *, power: bool) -> str:
    """Named checks this placement fails, or ``""`` when it is clean.

    Cheap next to the CP-SAT sweep that produced the placement, and it is the
    one thing that makes ``lay_out``'s contract enforceable rather than
    asserted.
    """
    report = validate.certify(placement, spec, expect_power=power)
    return ", ".join(sorted({f.check for f in report.errors}))


_REFUSAL_TEXT = {
    FALLBACK_NO_BUDGET: "no time budget was given, so the solver was never asked",
    FALLBACK_EMPTY_SPEC: "the spec contains no machine groups",
    FALLBACK_UNROUTABLE: (
        "every candidate width packed rows that no sorter could wire "
        "(a structural limit in the row model, not a search failure)"
    ),
    FALLBACK_NO_SOLUTION: "CP-SAT found no feasible row assignment at any candidate width",
    FALLBACK_EMISSION: (
        "every plan the width sweep solved could not be emitted onto the grid"
    ),
    FALLBACK_SELF_CHECK: (
        "every plan that emitted was rejected by our own validator"
    ),
    FALLBACK_SEED_UNWIRABLE: (
        "a group cannot be wired even alone in its own row, so no packing can "
        "help it"
    ),
}


def _refusal(reason: float, detail: str = "") -> str:
    text = _REFUSAL_TEXT.get(reason, f"unknown reason {reason}")
    return f"{text}: {detail}" if detail else text


def _solve_plan(
    spec: BuildSpec, *, time_budget_s: float, workers: int
) -> tuple[list[_Plan], float, str]:
    """Pack groups into rows and choose direct inserts, minimising area.

    Area is ``W * H``, a variable product with a weak relaxation, so instead of
    ``AddMultiplicationEquality`` we sweep candidate widths and minimise ``H``
    under each -- a handful of easy solves rather than one hard one.

    Returns EVERY plan the sweep solved, densest first, not just the densest.
    The caller has two more gates left to pass -- emission, then our own
    validator -- and neither is visible from in here.  Handing back a single
    plan meant a width whose plan failed either gate discarded the other widths
    that had solved perfectly well in the same sweep, and at a budget at or
    above ``RETRY_BUDGET_S`` there is no second attempt to recover in.

    These are all SOLVED plans from one sweep, in area order.  Trying the second
    one is continuing the search, not falling back to something the solver never
    proposed -- there is no seed here and there is not going to be one.

    HOW OFTEN THIS MATTERS TODAY: never, and that is stated rather than assumed.
    Measured over the 24 ``universe-matrix`` cells -- three candidates, both
    power settings, budgets 1, 2, 4 and 15, the sweep returning between 2 and 7
    plans each -- the densest plan passed emission and the self-check on the
    first try in all 24.  Nothing in the corpus currently reaches past the head.

    So this is insurance against gates the sweep cannot see, not a repair for a
    cell that is failing, and it is worth being clear which of those it is.  It
    is kept because discarding solved work on the first failure is wrong whether
    or not it is costing a cell this week, and because it costs nothing while the
    head keeps winning.  If it ever DOES fire, that is not this loop earning its
    keep -- it is the packer producing a densest plan its own validator rejects,
    and the thing to do is go and find that, not be satisfied with the green.

    The third element is a DETAIL string naming what went wrong, empty when a
    plan came back.
    """
    groups, edges = _adapt(spec)
    seed_rows = _topological_rows(groups, edges)
    order = [row[0] for row in seed_rows]
    depth = {key: i for i, key in enumerate(order)}
    n = len(order)
    if n == 0:
        return [], FALLBACK_EMPTY_SPEC, ""

    # The seed's lane allocation is a DIAGNOSTIC here, not a gate.  It used to be
    # the gate by accident: `_solve_plan` opened with `fallback_plan(spec)`, whose
    # allocation raises on a row nothing can wire, and `lay_out` caught the
    # ValueError as FALLBACK_EMISSION.  So a spec with one unwirable recipe was
    # refused before CP-SAT was asked a single question, under a reason that said
    # a plan had solved and failed to emit -- when none had solved at all.  That
    # is exactly the class of mislabelled failure this module's refusal codes
    # exist to prevent, and it hid the real one on `universe-matrix` for a while.
    #
    # Running the solve anyway costs a handful of propagations: the tap-capacity
    # constraint holds the same arithmetic, so CP-SAT proves the same
    # infeasibility, and it does so at every width in milliseconds.  What it buys
    # is that a row the SEED cannot wire but a real packing could -- direct
    # insertion removes lane taps, and the seed takes none -- is no longer thrown
    # away unexamined.
    seed_error = ""
    try:
        _lane_requirements(groups, edges, seed_rows, set(), spec)
    except ValueError as exc:
        seed_error = str(exc)

    widths = _candidate_widths(groups)
    # Two pools, because a packing that forced `_lane_requirements` to abandon a
    # belt-capacity split is worth shipping but is not worth PREFERRING.  With
    # one pool the smallest area won outright, so a width whose split survived
    # could lose to a slightly narrower one that quietly put 46 items/s back on
    # a 30/s belt -- `flow.belt_capacity` errors on `universe-matrix` that
    # another width in the very same sweep did not have.
    found: list[tuple[int, int, _Plan]] = []  # (degraded?, area, plan)
    per_solve = max(time_budget_s / max(len(widths), 1), 0.25)
    unroutable = 0

    for w_cap in widths:
        try:
            plan, infeasible = _solve_one(
                spec, groups, edges, depth, n, w_cap, per_solve, workers
            )
        except ValueError:
            # This width produced a row packing that cannot be routed within
            # sorter reach.  Skip it and keep sweeping rather than abandoning
            # every remaining width.
            unroutable += 1
            continue
        if infeasible:
            # PROVED infeasible, not merely unsolved in the time given -- and the
            # sweep is descending, with every width at least the widest single
            # block.  A larger ``w_cap`` only ever ADMITS row assignments (the
            # one-group-per-row assignment is feasible at every width in the
            # list), so nothing narrower can be feasible when the widest is not.
            # Sweeping on regardless cost eight model builds per refusal on a
            # 40-group spec -- about 2s each attempt, paid by exactly the specs
            # that were going to be refused anyway.
            break
        if plan is None:
            continue
        found.append((int(plan.degraded), _measure(spec, plan), plan))
    if found:
        # Degraded last, then densest first: the two pools above, expressed as
        # one sort key now that the caller consumes the whole ordering rather
        # than only its head.
        found.sort(key=lambda t: (t[0], t[1]))
        return [p for _deg, _area, p in found], FALLBACK_NONE, ""
    # Distinguish "packed rows nothing could wire" from "CP-SAT found nothing",
    # because they call for opposite fixes: the first is a structural limit in
    # the model, the second a search or feasibility problem.  A seed row that
    # cannot be wired outranks both: one group per row is the loosest packing
    # there is, so nothing a wider or narrower sweep does can rescue it, and the
    # refusal should say which recipe and by how much rather than blaming the
    # search.
    if seed_error:
        return [], FALLBACK_SEED_UNWIRABLE, seed_error
    return [], (FALLBACK_UNROUTABLE if unroutable else FALLBACK_NO_SOLUTION), ""


def _candidate_widths(groups: dict[str, _Group]) -> list[int]:
    """Descending widths to sweep, seeded from the fallback's own width."""
    widest = max(
        (g.block_width for g in groups.values()),
        default=1,
    )
    total = sum(
        g.block_width for g in groups.values()
    )
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
) -> tuple[_Plan | None, bool]:
    """One CP-SAT solve: assign groups to rows, minimise total height.

    The second element says the model was PROVED infeasible, as opposed to
    merely unsolved inside ``budget_s``.  The sweep in :func:`_solve_plan` needs
    the difference: a proof holds at every narrower width, an exhausted budget
    holds at none.
    """
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

    max_h = max(g.pitch_h for g in groups.values())
    row_w, row_h = [], []
    for r in range(n):
        ww = model.new_int_var(0, w_cap, f"ww_{r}")
        model.add(
            ww
            == sum(
                groups[k].block_width * in_row[k, r]
                for k in keys
            )
        )
        hh = model.new_int_var(0, max_h, f"hh_{r}")
        for k in keys:
            model.add(hh >= groups[k].pitch_h * in_row[k, r])
        row_w.append(ww)
        row_h.append(hh)

    # --- tap capacity ------------------------------------------------------
    # Row r reaches exactly two corridors -- r from below and r+1 from above --
    # each holding at most ``sorter_max_reach`` lanes.  So a row can tap at most
    # ``2 * reach`` DISTINCT items, counting an item once however many groups in
    # the row touch it.  That much is height-blind and only the whole truth for
    # a row of equal-height machines; the section after this one adds what a
    # shorter machine loses, and the two together are Hall's condition.
    #
    # This has to live in the model.  Without it CP-SAT freely packed five
    # groups into one row, `_lane_requirements` correctly refused the result,
    # and `_solve_plan` skipped every width in the sweep and came back empty --
    # so the strategy fell back to its greedy layout on every real spec while
    # reporting only `fallback_used=1`.  Rejecting after the fact cannot work
    # here: routability is a property of the packing, so the packer has to know.
    tap_reach = CONSTANTS.sorter_max_reach
    lane_copies = _lane_copies(groups, edges, set(), spec)
    tapped_by: dict[str, list[str]] = defaultdict(list)
    for k, g in groups.items():
        for item in set(g.inputs) | set(g.outputs):
            tapped_by[item].append(k)

    # Items the budget may count at HALF a lane, because two of them can share
    # one -- see `_shareable`.  Deliberately narrowed to the items of a group
    # that cannot be seated one-per-lane at all: those are the only groups
    # `_allocate_lanes` will ever mix for, since it tries one item per lane
    # first, so pricing anything else at a half would loosen the model where
    # the allocator has not loosened to match and cost widths to packings it
    # then refuses.  On every corpus spec but `universe-matrix` this set is
    # empty and the constraint is bit-for-bit the one that came before.
    over: set[str] = set()
    for g in groups.values():
        items = set(g.inputs) | set(g.outputs)
        if sum(lane_copies.get(i, 1) for i in items) > 2 * tap_reach:
            over |= items
    can_share = set(_shareable(groups, edges, set(), spec, lane_copies)) & over

    for r in range(n):
        # Weighted by parallel-lane count, because the budget is LANES.  An item
        # that needs two lanes to carry its rate takes two of the row's slots,
        # and pricing it at one let the solver pack rows whose split
        # `_lane_requirements` then had to abandon -- silently putting the flow
        # back on one belt.  Measured on quantum-chip, where crude-oil and
        # refined-oil each move 48/s against a 30/s belt.
        terms = []
        shared = []
        for item, holders in tapped_by.items():
            t = model.new_bool_var(f"tap_{r}_{item}")
            model.add_max_equality(t, [in_row[k, r] for k in holders])
            if item in can_share:
                shared.append(t)
            else:
                terms.append(lane_copies.get(item, 1) * t)
        if shared:
            # ``ceil(shared / 2)`` lanes, expressed exactly: minimising height
            # drives the variable down and the doubling pins it from below.
            pairs = model.new_int_var(0, len(shared), f"shared_lanes_{r}")
            model.add(2 * pairs >= sum(shared))
            terms.append(pairs)
        if terms:
            model.add(sum(terms) <= 2 * tap_reach)

    # --- tap capacity, height-aware ----------------------------------------
    # The flat ``2 * tap_reach`` above is only the truth when every machine in
    # the row is the same height.  Machines are pinned to the TOP of their row,
    # so a group ``gap`` tiles shorter than the row's tallest is still flush
    # with the corridor ABOVE it and sits ``gap`` further from the one BELOW:
    # lane ``j`` of the lower corridor is ``gap + j + 1`` tiles away, so a
    # gapped lane may only take one of that corridor's first ``tap_reach - gap``
    # positions.  ``_fits_below`` is exactly that rule.
    #
    # Measured, on the URL this was found with: row
    # ``energetic-graphite + iron-ingot + reforming-refine`` taps six lanes, and
    # four of them are tapped by 3-tall arc smelters in a row a 7-tall oil
    # refinery makes 7 tall.  A gap of 4 against a reach of 3 fits in the upper
    # corridor or nowhere, and the upper corridor holds three -- so the row is
    # unwirable, `_lane_requirements` said so, and every width in the sweep was
    # skipped for it.  Six is exactly ``2 * tap_reach``, so the flat bound saw
    # nothing wrong.
    #
    # Every lane may use any of the upper corridor's ``tap_reach`` slots plus a
    # PREFIX of the lower corridor, and those prefixes NEST by gap.  A nested
    # family needs Hall's condition checked only on the nesting, which is one
    # inequality per gap threshold:
    #
    #     lanes with gap >= t   <=   tap_reach + max(0, tap_reach - t)
    #
    # ``t = 0`` is the constraint above.  Thresholds stop at ``tap_reach``,
    # where the bound goes flat while the count only falls, so no larger
    # threshold forbids anything the ``tap_reach`` one does not.
    #
    # This is `_fits_below`'s own greedy and deliberately not a cruder flat
    # ``tap_reach - gap`` cap: a corridor holds three lanes at a gap of 2 (spans
    # 3, 2, 3) where the flat cap allows one, and charging that would split rows
    # that pack perfectly well today.
    #
    # Gap is ``row_h[r] - height`` and ``row_h[r]`` is a variable, so each
    # threshold is enforced under a REIFIED row height: in a row ``h`` tall,
    # item ``i`` carries a gap of at least ``t`` exactly when some group no
    # taller than ``h - t`` in that row taps it.  ``row_h[r]`` is only bounded
    # from below, but the objective minimises it, and an over-large value only
    # ever ADDS terms -- so the bound can be too strict for an assignment the
    # solver was going to reject on height anyway, and never too loose.
    heights = sorted({grp.height for grp in groups.values()})
    # Only differences some pair of groups can actually realise.  A spec whose
    # machines are all one height has none at all, and its model stays
    # bit-for-bit the one that came before.
    thresholds = sorted({min(b - a, tap_reach) for a in heights for b in heights if b > a})
    if thresholds:
        by_height: dict[str, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
        for k, grp in groups.items():
            for item in set(grp.inputs) | set(grp.outputs):
                by_height[item][grp.height].append(k)
        for r in range(n):
            #: ``(item, ceiling) -> does row r tap item through a group that
            #: short?``  Keyed by the tallest height at or below the ceiling,
            #: because the handful of ``h - t`` values collapse onto far fewer
            #: distinct group sets and the literal is reusable across ``t``.
            short_tap: dict[tuple[str, int], cp_model.IntVar] = {}
            for h in heights:
                #: Built on first use, so a height no threshold can bind at --
                #: the shortest one, where nothing is shorter still -- costs the
                #: model nothing.
                is_h: cp_model.IntVar | None = None
                for thr in thresholds:
                    under = [x for x in heights if x <= h - thr]
                    if not under:
                        continue  # nothing in this spec is that much shorter
                    ceiling = max(under)
                    bound = tap_reach + max(0, tap_reach - thr)
                    gapped = {
                        item: short
                        for item, holders in by_height.items()
                        if (
                            short := [
                                k for hh, ks in holders.items() if hh <= ceiling for k in ks
                            ]
                        )
                    }
                    # Skip a threshold that cannot bind even if the row took
                    # every gapped item in the spec.  On the small corpus specs
                    # this is most of them, and the variables are never built.
                    if sum(lane_copies.get(i, 1) for i in gapped) <= bound:
                        continue
                    gap_terms: list[cp_model.LinearExpr] = []
                    for item, short in sorted(gapped.items()):
                        v = short_tap.get((item, ceiling))
                        if v is None:
                            # A single holder needs no reification at all: its
                            # `in_row` literal already IS "row r taps this item
                            # through a group that short".  Measured, this is
                            # most of the small specs and about a quarter of the
                            # big ones -- `universe-matrix` (40 groups) drops
                            # from 3,400 added Booleans to 2,600, and
                            # `graphene` from 28 to 8.
                            if len(short) == 1:
                                v = in_row[short[0], r]
                            else:
                                v = model.new_bool_var(f"short_{r}_{ceiling}_{item}")
                                model.add_max_equality(v, [in_row[k, r] for k in short])
                            short_tap[item, ceiling] = v
                        gap_terms.append(lane_copies.get(item, 1) * v)
                    if is_h is None:
                        is_h = model.new_bool_var(f"rowh_{r}_{h}")
                        model.add(row_h[r] == h).only_enforce_if(is_h)
                        model.add(row_h[r] != h).only_enforce_if(~is_h)
                    model.add(sum(gap_terms) <= bound).only_enforce_if(is_h)

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
    # Presolve PROBING is where this model's budget went, and it bought nothing.
    #
    # Measured on `universe-matrix` (40 groups, 68 edges, n=40, 64 workers,
    # w=276, 15s):
    #
    #     default                      presolve 3.70s   first solution 4.97s
    #     cp_model_probing_level = 0    presolve 0.67s   first solution 0.75s
    #     symmetry_level = 0            presolve 3.64s   first solution 5.11s
    #
    # Probing is the whole of it; symmetry detection is free by comparison.  A
    # sweep of six widths divides the call's budget six ways, so at the audit's
    # 4s budget each solve got 0.5s -- and presolve had not finished, let alone
    # started searching.  That is why every `universe-matrix` cell refused with
    # "CP-SAT found no feasible row assignment at any candidate width": the
    # model is feasible at every width and was never asked.
    #
    # Probing pays off on models where implications between Booleans are hidden.
    # Here they are not: `in_row` is an explicit exactly-one, and every corridor
    # and tap literal is already a reification the model states outright.  So the
    # probe walks ~10,900 Booleans to rediscover what was written down.
    solver.parameters.cp_model_probing_level = 0
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, status == cp_model.INFEASIBLE

    buckets: dict[int, list[str]] = defaultdict(list)
    for k in keys:
        buckets[solver.value(row[k])].append(k)
    rows = [sorted(buckets[r]) for r in sorted(buckets)]
    direct = {ek for ek, d in di.items() if solver.value(d)}
    lanes, mixed, got = _lane_requirements(groups, edges, rows, direct, spec)
    wanted = _lane_copies(groups, edges, direct, spec)
    return (
        _Plan(
            rows=rows,
            lanes=lanes,
            mixed=mixed,
            direct=direct,
            solver_status=solver.status_name(status),
            hit_budget=status == cp_model.FEASIBLE,
            degraded=any(got.get(i, 1) < v for i, v in wanted.items()),
        ),
        False,
    )


def _measure(spec: BuildSpec, plan: _Plan) -> int:
    groups, _ = _adapt(spec)
    heights = [max((groups[k].pitch_h for k in r), default=0) for r in plan.rows]
    widths = [
        sum(groups[k].block_width for k in r)
        for r in plan.rows
    ]
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


def _insert_pitch(
    groups: dict[str, _Group], direct: Iterable[tuple[str, str, str]]
) -> dict[str, int]:
    """Effective pitch per group, raised so direct-insert partners stay aligned.

    A machine-to-machine sorter runs in a straight line, so machine ``i`` of the
    producer has to share a COLUMN with machine ``i`` of the consumer.  Two
    groups packed at different pitches drift by their difference each machine:
    an Arc Smelter at 3 and an Assembling Machine at 4 line up for the first
    three pairs and miss on the fourth, which loses the insert for the whole
    edge.

    Raising the narrower partner to the wider pitch fixes it and costs width
    only on the groups that are actually paired.  The alternative measured worse:
    one pitch per ROW cost 14.68% area over seven specs and bought no inserts at
    all -- see the note above `_pack_row`.
    """
    pitch = {k: g.pitch_w for k, g in groups.items()}
    for src, dst, _item in direct:
        if src not in pitch or dst not in pitch:
            continue
        want = max(pitch[src], pitch[dst])
        pitch[src] = pitch[dst] = want
    return pitch


def _pack_row(
    row: list[str],
    groups: dict[str, _Group],
    *,
    hr: int,
    power: bool,
    pitch_of: dict[str, int] | None = None,
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
        pitch = g.pitch_w if pitch_of is None else pitch_of.get(key, g.pitch_w)
        for _ in range(g.count):
            if power and x >= next_tower:
                slots.append(_Slot(None, x, tw))
                covered_to = x + tw - 1 + hr
                x += tw
                next_tower = x + 2 * hr
            slots.append(_Slot(key, x, pitch))
            x += pitch
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
) -> tuple[
    set[tuple[str, str, str]],
    list[list[str]],
    dict[tuple[int, int], tuple[str, ...]],
    dict[str, int],
]:
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
        lanes, mixed, copies = _lane_requirements(groups, edges, plan.rows, current, spec)
        row_heights = [max((groups[k].pitch_h for k in r), default=1) for r in plan.rows]
        corridor_heights = [len(c) for c in lanes]
        row_y, _corr_y, _h = band_offsets(row_heights, corridor_heights)

        xs: dict[str, list[int]] = defaultdict(list)
        for r, row in enumerate(plan.rows):
            hr = _horizontal_reach(r, row_heights, corridor_heights) if power else 0
            slots, _w = _pack_row(
                row, groups, hr=hr, power=power, pitch_of=_insert_pitch(groups, current)
            )
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
            return current, lanes, mixed, copies
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

    direct, lanes, mixed, copies = _realizable_direct(spec, groups, edges, plan, power=power)
    plan = _Plan(
        rows=plan.rows,
        lanes=lanes,
        mixed=mixed,
        direct=direct,
        solver_status=plan.solver_status,
        hit_budget=plan.hit_budget,
    )

    row_heights = [max((groups[k].pitch_h for k in r), default=1) for r in plan.rows]
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
        slots, width = _pack_row(
            row, groups, hr=hr, power=power, pitch_of=_insert_pitch(groups, plan.direct)
        )
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
                    yaw=g.yaw,
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
                item_id_of=g.item_id,
                yaw_of=g.yaw,
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
    #
    # All of it is per LANE, not per item -- see ``extents`` below for what
    # conflating the two cost.
    #: Keyed by (corridor, DEPTH), like everything else that describes one lane.
    #: It used to be keyed by (corridor, item), and that was the same mistake
    #: ``lane_tiles`` records two blocks below: an item holds SEVERAL lanes in one
    #: corridor -- a copy in the top band serving the row above and one in the
    #: bottom band serving the row below, plus a copy per parallel lane -- and
    #: unioning their spans gave every copy the widest one's extent.  A bottom-band
    #: copy tapped at columns 5..30 was emitted from 5 to 280 because its
    #: top-band sibling reached that far, and the 250 tiles in between carried
    #: nothing: 261 ``belt.termination`` warnings naming 6,928 dead tiles, 7.0%
    #: of all belt emitted.
    extents: dict[tuple[int, int], tuple[int, int]] = {}
    #: The union, kept only as the fallback for a copy with no taps of its own --
    #: an item with more parallel lanes than a group has machines leaves one
    #: empty.  Such a lane is waste either way; inheriting the sibling's span is
    #: what it did before and is narrower than the full-width default.
    item_extents: dict[tuple[int, str], tuple[int, int]] = {}
    #: Columns at which each lane is filled and drained, keyed by (corridor,
    #: depth) rather than by item, because a direction is a property of ONE lane
    #: and an item may hold two of them.  ``_lane_direction`` reads these.
    fill_at: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    drain_at: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)

    def _extend(c: int, depth: int, lo: int, hi: int) -> None:
        cur = extents.get((c, depth))
        extents[c, depth] = (lo, hi) if cur is None else (min(cur[0], lo), max(cur[1], hi))
        item = plan.lanes[c][depth]
        was = item_extents.get((c, item))
        item_extents[c, item] = (
            (lo, hi) if was is None else (min(was[0], lo), max(was[1], hi))
        )

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
                # The COLUMNS the sorter pass will actually use, from each
                # machine's own insert poses -- not its left edge. A seven-wide
                # Oil Refinery offers only its middle three and a nine-wide
                # Chemical Plant four of nine, so a lane charged from the left
                # edge stops short of the only columns that can be wired and the
                # machine gets no sorter at all. That was `machine.inputs_supplied`
                # on exactly one machine per group, which is what it looks like
                # when a lane ends one machine early.
                reachable = [
                    sorted(sorter_slots.attachable_columns(buildings[i], tap.lane_y))
                    for i in share
                ]
                reachable = [r for r in reachable if r]
                if not reachable:
                    continue
                pick = _pick_sorter(rate, tap.span, max(len(r) for r in reachable))
                cols = min(pick[1], max(len(r) for r in reachable)) if pick else 1
                # A rider on a shared lane starts one column further along the
                # machine, because two sorters serving one machine off one belt
                # cannot stand in the same column.  Charged to the EXTENT as
                # well as to the sorter pass: the lane is emitted from the taps
                # it is charged for, so a rider whose column the lane never
                # reached simply got no sorter -- `machine.inputs_supplied`, on
                # the very spec the sharing exists for.
                off = _share_column(plan, tap.corridor, tap.depth, item)
                lo = min(r[min(off, len(r) - 1)] for r in reachable)
                hi = max(r[min(off + cols - 1, len(r) - 1)] for r in reachable)
                _extend(tap.corridor, tap.depth, lo, hi)
                (drain_at if into else fill_at)[tap.corridor, tap.depth].append((lo, hi))

    # --- trunk risers -----------------------------------------------------
    # The copies of an item's lane in different corridors used to be independent
    # horizontal runs with nothing between them, so a producer's sorters filled
    # corridor r + 1 while its consumers drained corridor s and the item never
    # arrived.  Every `flow.lane_sourced` error on every corpus spec was this.
    #
    # Planned BEFORE the boundary runs, because a lane joined to a trunk has its
    # east end spoken for and cannot choose which way it leaves the block.
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
        _extend(c, d, content_w - 1, content_w - 1)

    # --- boundary runs ----------------------------------------------------
    # A product leaves at whichever edge is NEARER its last producer, not at the
    # east one by convention.  Both edges are equally physical -- the player
    # belts the output away from either -- and the block is as wide as its widest
    # row, so a product made by a narrow row at the west end used to pay the
    # whole width in belt to reach an edge it had no reason to prefer.  Measured
    # on ``quantum-chip``: the product lane ran 288 tiles with its four taps in
    # the first ten, so 278 of them existed only to reach the east side.
    #
    # A lane a riser joined does not get the choice: its east end is already
    # committed to the trunk.
    #: Lanes whose product exit was put at the WEST edge, so ``_lane_direction``
    #: pins them the matching way round.  A belt is one-way, and pinning a lane
    #: east while running it out to ``x = 0`` would fill the wrong end.
    exits_west: set[tuple[int, int]] = set()
    for c, order in enumerate(plan.lanes):
        for depth_i in range(len(order)):
            carried = _lane_items(plan, c, depth_i)
            item = carried[0]
            # Only a lane something actually taps is run out to the boundary.
            # A copy with no taps has nothing to carry in or out, and reaching
            # the edge would make it look like an entry the player has to feed.
            tapped = extents.get((c, depth_i))
            if tapped is None:
                continue
            if any(i in spec.external_inputs for i in carried):
                _extend(c, depth_i, 0, 0)
            if item not in leaving:
                continue
            # An item that is BOTH externally supplied and a leaving byproduct
            # keeps its east exit unconditionally: the west edge is already its
            # entry, so the surplus has nowhere else to go and would back up
            # against the last tap -- a stall no validator check can see.
            west_cost, east_cost = tapped[0], content_w - 1 - tapped[1]
            if (
                (c, depth_i) not in joined
                and item not in spec.external_inputs
                and west_cost < east_cost
            ):
                exits_west.add((c, depth_i))
                _extend(c, depth_i, 0, 0)
            else:
                _extend(c, depth_i, content_w - 1, content_w - 1)

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
        for depth_i in range(len(order)):
            carried = _lane_items(plan, c, depth_i)
            item = carried[0]
            external_here = any(i in spec.external_inputs for i in carried)
            y = corr_y[c] + depth_i
            reach_span = extents.get((c, depth_i)) or item_extents.get((c, item))
            lo, hi = reach_span if reach_span is not None else (0, content_w - 1)
            fills = fill_at[c, depth_i]
            drains = drain_at[c, depth_i]
            westward = _lane_direction(
                (c, depth_i),
                fed_from_trunk=fed_from_trunk,
                hands_to_trunk=hands_to_trunk,
                pinned_west_edge=external_here,
                pinned_east_edge=item in leaving and (c, depth_i) not in exits_west,
                exits_west=(c, depth_i) in exits_west and not external_here,
                fills=fills,
                drains=drains,
            )
            # What the chosen direction still cannot serve.  A lane whose drains
            # straddle its fills is unservable either way -- see the stat's note
            # in the returned ``Placement``.
            supply = list(fills)
            if (c, depth_i) in fed_from_trunk:
                supply.append((content_w - 1, content_w - 1))
            if external_here:
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
        # The rows the two bands sit on are no longer where the sorter anchors:
        # `direct_anchors` reads that off each machine's own slot table, and a
        # Chemical Plant's is a row inside its footprint rather than its edge.
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
        #: ``(producer, consumer, span, column, producer_row, consumer_row)``.
        #: The two rows are the anchors the slot tables give, which are the
        #: machines' edge rows only when they happen to be -- a Chemical Plant's
        #: is a row inside its footprint.
        pairs: list[tuple[int, int, int, int, int, int]] = []

        def _pair(
            a: int, others: list[int], *, a_produces: bool
        ) -> tuple[int, int, int, int] | None:
            """A partner for ``a``, on a column BOTH can actually be wired on.

            Every column of the footprint overlap is tried, not just its middle:
            with the real tables an overlap can be wide and the attachable part
            of it narrow, and a machine-to-machine sorter needs a column that
            works at both ends at once.
            """
            ab = buildings[a]
            for b in sorted(others, key=lambda o: abs(buildings[o].x - ab.x)):
                bb = buildings[b]
                lo = max(ab.x, bb.x)
                hi = min(ab.x + ab.width, bb.x + bb.width) - 1
                mid = (lo + hi) // 2
                for col in sorted(range(lo, hi + 1), key=lambda c: (abs(c - mid), c)):
                    src_b, dst_b = (ab, bb) if a_produces else (bb, ab)
                    got = sorter_slots.direct_anchors(src_b, dst_b, col)
                    if got is None:
                        continue
                    out_row, in_row = got[0].cell[1], got[1].cell[1]
                    reach = abs(in_row - out_row)
                    if not 1 <= reach <= CONSTANTS.sorter_max_reach:
                        continue
                    return b, col, out_row, in_row
            return None

        for ci in cons:
            got = _pair(ci, prod, a_produces=False)
            if got is not None:
                pairs.append((got[0], ci, abs(got[3] - got[2]), got[1], got[2], got[3]))
        # And every PRODUCER, not just every consumer.  A producer left out has
        # no belt lane either -- the insert removed it -- so it backs up, which
        # is what `machine.output_removed` was reporting on five corpus specs.
        # Pairing it with a consumer it already shares a column with costs one
        # more sorter and nothing else; the consumer simply gets fed twice.
        wired = {pi for pi, _ci, _s, _c, _oy, _iy in pairs}
        for pi in prod:
            if pi in wired:
                continue
            got = _pair(pi, cons, a_produces=True)
            if got is not None:
                pairs.append((pi, got[0], abs(got[3] - got[2]), got[1], got[2], got[3]))
        rate = rate_of.get((src, dst, item), Fraction(0))
        if not pairs:
            raise ValueError(
                f"direct insert {src} -> {dst} ({item}) has no machine pair within "
                f"sorter reach {CONSTANTS.sorter_max_reach}"
            )
        worst = max(s for _, _, s, _x, _oy, _iy in pairs)
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
        for pi, ci, _span, col, out_row, in_row in pairs:
            buildings.append(
                PlacedBuilding(
                    item_id=tier,
                    model_index=tier_model,
                    x=col,
                    y=out_row,
                    width=1,
                    height=1,
                    x2=col,
                    y2=in_row,
                    z2=Fraction(0),
                    yaw=Facing.SOUTH.value,
                    yaw2=Facing.SOUTH.value,
                    input_obj=pi,
                    output_obj=ci,
                )
            )
            direct_sorters += 1
    sorters += direct_sorters

    # --- sorters ----------------------------------------------------------
    #: Anchor columns already spent on each lane, per machine.  Two items riding
    #: one belt need one column each across the machine's width; without this the
    #: second item's sorters landed on top of the first's.
    lane_columns: dict[tuple[int, int], dict[int, set[int]]] = defaultdict(dict)
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
                # How many sorters will FIT, which is the count of columns this
                # machine's insert poses reach from this lane -- not its width.
                # A Matrix Lab is five wide and offers three; a Chemical Plant
                # nine and offers four; an Oil Refinery served from above offers
                # none. Sizing against the width asked for more sorters than
                # there were columns, and the surplus was silently dropped by
                # `_place_sorters` -- a capacity shortfall that looked like a
                # routing problem. Fewer columns simply means a higher tier.
                widest = max(
                    (len(sorter_slots.attachable_columns(buildings[m], tap.lane_y))
                     for m in machines),
                    default=0,
                )
                if widest == 0:
                    continue
                pick = _pick_sorter(rate / g.count, tap.span, widest)
                if pick is None:
                    continue
                tier, per_machine = pick
                lane_key = (tap.corridor, tap.depth)
                shared = len(_lane_items(plan, *lane_key)) > 1
                sorters += _place_sorters(
                    buildings,
                    lane_tiles[lane_key],
                    machines,
                    lane_y=tap.lane_y,
                    machine_y=tap.machine_y,
                    tier=tier,
                    per_machine=per_machine,
                    into_machine=into_machine,
                    filter_id=_lane_filter(item) if shared else 0,
                    column=_share_column(plan, *lane_key, item),
                    reserved=lane_columns[lane_key] if shared else None,
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

    # Slot indices are geometry, so they are derived here once rather than at
    # each of the several places a sorter gets created. Every sorter this
    # strategy emitted before carried a defaulted zero in all four fields, which
    # the game rejects outright.
    #
    # A sorter whose slot cannot be derived is a REFUSAL, not a crash and not a
    # guess. The one case that reaches this today is a Spray Coater: it ships
    # zero slot poses, and `BuildTool_Inserter` will not even let a sorter
    # target a building with none, so the connection this strategy wants does
    # not exist in the game. Refusing says so; emitting an index the game never
    # writes would not.
    try:
        slotted = assign_sorter_slots(buildings)
    except SlotUndetermined as exc:
        raise NoValidLayout(f"a sorter's slot could not be derived: {exc}") from exc

    return Placement(
        buildings=slotted,
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
                        [
                            (groups[k].pitch_w, groups[k].pitch_h, groups[k].count)
                            for k in row
                        ],
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
    exits_west: bool = False,
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
    * a product leaves at whichever edge ``_emit`` sent it to -- east by
      default, west when that is the nearer boundary and no riser has claimed
      the lane's east end.  ``exits_west`` is the one flag here that means
      "flows towards ``x = 0``"; ``pinned_west_edge`` is an ENTRY at that edge
      and therefore flows the opposite way, which is why the two are separate
      arguments rather than one side.

    Only the last case -- a lane whose taps are all local -- is free, and there
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
    if key in fed_from_trunk or exits_west:
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
#: A bridge only ever crosses a ground-level trunk, so it needs exactly
#: ``BELT_CROSSING_CLEARANCE`` and no more.  This is NOT the game's ceiling:
#: a belt goes as high as the save's vertical-construction unlocks allow.
_BRIDGE_Z = catalog.BELT_CROSSING_CLEARANCE

#: Altitude of a bridge's run-up tile: one tile of run buys one tile's worth of
#: climb, so the tile the change happens across sits at half a level.  This is
#: the ``0.5`` that every real elevated run has and that both strategies used to
#: omit.
_RAMP_Z = catalog.BELT_CLIMB_PER_TILE


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
            is_source = (c, d) in filled
            if not is_source and (c, d) not in drained:
                continue
            # A rider on a shared lane always has ``copies == 1`` -- `_shareable`
            # refuses to pair a split item -- so its rank is 0 and it needs none
            # of the contiguity bookkeeping above.
            for it, rank in ((item, k), *((x, 0) for x in _lane_items(plan, c, d)[1:])):
                if it in external:
                    continue
                lanes_of[it, rank].append((corr_y[c] + d, c, d, is_source))

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
    return _assign_columns(_merge_shared_risers(risers))


def _merge_shared_risers(risers: list[_Riser]) -> list[_Riser]:
    """Join the trunks that have to deliver into the SAME lane.

    Two items sharing one corridor lane each need their contents brought down to
    it, and two independent trunks would both bridge across the margin *at that
    lane's y* -- the same tiles claimed twice, which is an overlap the validator
    reports and the game would refuse to paste.

    One trunk collecting both sources and delivering once is the only geometry
    that fits, and the riser model already expresses it: ``taps`` may hold
    several sources, each merging into the column at its own y, and DSP merges
    belts natively.  ``is_source`` is a property of the LANE rather than of the
    item -- it says whether anything's sorters FILL that lane -- so the shared
    destination arrives from both sides as the identical tuple and dedupes.

    Merging is safe only because :func:`_shareable` pairs items with exactly one
    destination each.  A merged trunk carries both items past every stop it
    makes, so a second, unshared destination would silently take delivery of the
    other item too, back up behind a sorter that filters it out, and stall.
    """
    if len(risers) < 2:
        return risers
    parent = list(range(len(risers)))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    owner: dict[tuple[int, int], int] = {}
    for i, riser in enumerate(risers):
        for _y, c, d, is_source in riser.taps:
            if is_source:
                continue
            j = owner.setdefault((c, d), i)
            parent[find(i)] = find(j)

    members: dict[int, list[int]] = defaultdict(list)
    for i in range(len(risers)):
        members[find(i)].append(i)

    out: list[_Riser] = []
    for group in members.values():
        if len(group) == 1:
            out.append(risers[group[0]])
            continue
        taps = sorted({t for i in group for t in risers[i].taps})
        first = next((i for i, t in enumerate(taps) if t[3]), None)
        if first is None:
            continue
        last = next((i for i in range(len(taps) - 1, first, -1) if not taps[i][3]), None)
        if last is None:
            continue
        # Named for one of the items it carries.  That is what a mixed belt can
        # be labelled, and it is enough: every sorter drawing off the shared
        # lane is FILTERED, and `validate._sorter_item` reads a filter before it
        # reads any label.
        out.append(
            _Riser(
                item=min(risers[i].item for i in group),
                taps=tuple(taps[first : last + 1]),
            )
        )
    return sorted(out, key=lambda r: (r.taps[0][0], r.item))


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
    #: BOTH ends of a bridge meet the ground -- a lane on one side, a trunk on
    #: the other -- so both are run-up tiles and both sit half way up.  Only one
    #: of them used to, which left the far end dropping a whole tile of height
    #: across one tile of run: the same illegal step freeform emitted, and the
    #: one ``geom.altitude_step`` now refuses.  The profile reads
    #: ``0, 1/2, 1, ..., 1, 1/2, 0`` counting the ground at each end, exactly as
    #: every elevated run in the corpus does.
    #:
    #: Both end tiles land in the free ramp column ``_trunk_x`` reserves, so a
    #: run-up tile never has to clear anything -- which it could not do at half
    #: height anyway.  A one-tile bridge is entirely run-up: flat, no crossing.
    ramp_xs = {content_w, xr - 1}
    for x in xs:
        made.append(len(buildings))
        buildings.append(
            PlacedBuilding(
                item_id=belt_id,
                model_index=belt_model,
                x=x,
                y=y,
                z=(
                    Fraction(0)
                    if len(xs) == 1
                    else _RAMP_Z
                    if x in ramp_xs
                    else _BRIDGE_Z
                ),
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


def _anchor_span(
    item_id: int, yaw: float, mach_h: int, gap: int, *, above: bool
) -> int | None:
    """Tiles a sorter must span to reach ``item_id`` from a lane ``gap`` clear of it.

    Not ``gap``: the anchor is wherever the insert pose is, and for a Chemical
    Plant that is a row INSIDE the footprint.  ``None`` when no pose can be
    reached from that side at all, which an Oil Refinery answers for a lane
    above it.

    Asked of a type rather than a placed machine, because taps are chosen while
    planning, before anything has an address.  The shortest span over the
    attachable columns is the answer, since the sorter pass is free to pick the
    column and will pick one that works.
    """
    probe = sorter_slots.probe_building(item_id, yaw)
    lane_y = -gap if above else (mach_h - 1) + gap
    reachable = sorter_slots.attachable_columns(probe, lane_y)
    if not reachable:
        return None
    return min(a.span for a in reachable.values())


def _find_taps(
    plan: _Plan,
    r: int,
    item: str,
    corr_y: list[int],
    row_y: list[int],
    mach_h: int,
    *,
    item_id_of: int,
    yaw_of: float,
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
        if c < 0 or c >= len(plan.lanes):
            continue
        lanes = plan.lanes[c]
        # Not ``item in lanes``: a lane may carry a second item that ``lanes``
        # does not name -- see :attr:`_Plan.mixed` -- and skipping the corridor
        # on the label alone left the rider with no sorter at all.
        if not any(item in _lane_items(plan, c, j) for j in range(len(lanes))):
            continue
        found: list[_Tap] = []
        # An item may occupy SEVERAL lanes in one corridor -- deliberately, when
        # the corridor is tapped from both sides: a copy near the top serves the
        # row above and a copy near the bottom serves the row below, because no
        # single lane is within reach of both once the corridor is deeper than
        # ``2 * reach - 1``.  Taking ``lanes.index(item)`` returned the FIRST
        # copy regardless of which side was asking, so a row needing the bottom
        # copy was handed the top one at a span far beyond reach, failed the
        # test, and silently got no sorter for that ingredient at all.
        for j in range(len(lanes)):
            if item not in _lane_items(plan, c, j):
                continue
            lane_y = corr_y[c] + j
            if from_corridor_above:
                machine_y, gap = top, top - lane_y
            else:
                machine_y, gap = bottom, lane_y - bottom
            # The span is to the ANCHOR, not to the machine's edge. A Chemical
            # Plant's southern poses sit a row inside a footprint five deep, so
            # a sorter reaching one is a tile longer than the gap suggests and a
            # lane three clear of the building is already past reach. Measuring
            # from the edge accepted taps that then had no sorter placed, which
            # is a wide machine's version of the smelter-in-a-tall-row bug the
            # docstring above records: the same mistake, one layer further in.
            span = _anchor_span(item_id_of, yaw_of, mach_h, gap, above=from_corridor_above)
            if span is not None and 1 <= span <= CONSTANTS.sorter_max_reach:
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
    filter_id: int = 0,
    column: int = 0,
    reserved: dict[int, set[int]] | None = None,
) -> int:
    """Connect a lane to EVERY machine of a group, ``per_machine`` sorters each.

    Anchors sit on the connected tiles and the ``input_obj`` / ``output_obj``
    indices carry the real semantics -- which is how the game itself does it.
    Measured on real blueprints, a sorter's anchors never coincide with a belt
    *building*, so sorters are overlays and do not consume build tiles.

    ``filter_id`` pins which item this sorter moves, mandatory on a shared lane
    and left at zero on a plain one -- that zero-versus-set distinction is the
    signal the validator uses to tell the two apart, so do not set one where
    none is needed.  ``reserved`` carries the columns already spent on a lane
    across CALLS, keyed by machine: two items on one belt cannot be drawn by two
    sorters standing in the same column, and ``used`` alone only ever saw the
    one item it was called for.
    """
    model_index = catalog.building(tier).model_index
    placed = 0
    for m_idx in machines:
        m = buildings[m_idx]
        used: set[int] = set() if reserved is None else reserved.setdefault(m_idx, set())
        # The columns this machine can be served on FROM THIS LANE, computed
        # once. An Oil Refinery served from above yields none at all -- it has
        # no insert pose on that face -- and the loop below then places nothing
        # rather than anchoring where the game has no slot.
        reachable = sorter_slots.attachable_columns(m, lane_y)
        for i in range(per_machine):
            # ONE column for both anchors.  This sorter is vertical -- the lane
            # sits in a corridor above or below the machine row -- so the two
            # anchors must share an x.  Deriving the belt side from
            # ``m.x + min(i, width - 1)`` while anchoring the machine side at
            # bare ``m.x`` skewed every sorter after the first by exactly that
            # offset, which is why 100 of 118 came out diagonal with dx of only
            # ever 1 or 2.
            x = _shared_column(
                buildings, lane, m, prefer=column + i, avoid=used, allowed=set(reachable)
            )
            if x is None:
                continue
            belt_idx = _lane_tile_at(buildings, lane, x)
            if belt_idx is None:
                continue
            # WHERE on the machine, from the machine's own insert poses. The
            # near edge row is right for a 3x3 and wrong for most else: a
            # Chemical Plant's southern slots are a row inside its footprint.
            att = reachable[x]
            used.add(x)
            anchor_y = att.cell[1]
            if into_machine:
                src, dst = belt_idx, m_idx
                ax, ay, bx, by = x, lane_y, x, anchor_y
            else:
                src, dst = m_idx, belt_idx
                ax, ay, bx, by = x, anchor_y, x, lane_y
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
                    z2=Fraction(0),
                    # `assign_sorter_slots` derives the real yaw from the two
                    # anchors on the way out; this is a placeholder that keeps
                    # the record well-formed until it does.
                    yaw=Facing.SOUTH.value if lane_y < anchor_y else Facing.NORTH.value,
                    yaw2=Facing.SOUTH.value if lane_y < anchor_y else Facing.NORTH.value,
                    input_obj=src,
                    output_obj=dst,
                    filter_id=filter_id,
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
    """A Spray Coater is fed by BELT, and this cannot yet build the belt.

    It used to run a sorter from the corridor's proliferator lane into the
    coater.  That connection does not exist in the game.  A coater ships zero
    insert poses, ``BuildTool_Inserter`` refuses to target a building with none,
    and all eight coaters in the fixture corpus carry no connection at all --
    ``input_obj`` and ``output_obj`` both unset, with the addon pair ``(15, 14)``
    in their four slot fields.

    What the game does instead is positional.  On build it reads
    ``PrefabDesc.addonAreaPoses`` and attaches the nearest belt within 1.0 of
    each: area 0 is the cargo belt the coater rides, area 1 the proliferator
    supply, and for a coater area 1 is at
    :attr:`~flab2bp.dsp.catalog.Building.addon_areas` ``(0, -1.25, 1)`` -- a tile
    and a quarter behind it and exactly one altitude level UP.  The corpus
    agrees: every coater there has a belt one level above and one tile to the
    side.

    So the feed is a BELT in that area, and this places it: one tile behind the
    coater and one level up, linked from the nearest tile of the corridor's
    proliferator lane.  That link is a single step of climb, which
    ``beltVerticalConstruction`` makes free -- and where the save lacks it,
    ``geom.altitude_step`` refuses the step and the candidate with it, rather
    than this guessing a ramp it has no room for.

    Returns the number of BELTS placed, not sorters.  A coater is wired to
    nothing at all.
    """
    if prolif is None:
        return 0
    coater = buildings[coater_idx]
    adx, ady, adz = catalog.building(coater.item_id).addon_areas[1]
    wx, wy = sorter_slots.to_world((adx, ady), coater.yaw)
    cell = (coater.x + round(wx), coater.y + round(wy))
    level = Fraction(round(adz))
    if any(b.x == cell[0] and b.y == cell[1] and b.z == level for b in buildings):
        return 0
    # A source on the same corridor, orthogonally adjacent to the drop, so the
    # climb is one tile of run and one level -- and it must be the lane's TAIL.
    # Taking a mid-lane tile's output for the drop orphans everything downstream
    # of it: the lane stops there, its remaining sorters draw from a belt nothing
    # fills, and `flow.external_entry_reachable` reports the proliferator as
    # unreachable. A tail has no output to steal.
    for (c, depth), indices in lane_tiles.items():
        if c != corridor or lane_item_of.get((c, depth)) != prolif:
            continue
        for src in indices:
            b = buildings[src]
            if b.output_obj is not None:
                continue
            if abs(b.x - cell[0]) + abs(b.y - cell[1]) != 1:
                continue
            drop = len(buildings)
            buildings.append(
                PlacedBuilding(
                    item_id=b.item_id,
                    model_index=b.model_index,
                    x=cell[0],
                    y=cell[1],
                    z=level,
                    width=1,
                    height=1,
                    carries_item=prolif,
                )
            )
            buildings[src] = _relink_output(buildings[src], drop)
            return 1
    return 0


def _relink_output(b: PlacedBuilding, out: int) -> PlacedBuilding:
    """``b`` forwarding to ``out``.  Uses ``replace`` so no field is dropped."""
    return replace(b, output_obj=out)


def _shared_column(
    buildings: list[PlacedBuilding],
    lane: list[int],
    machine: PlacedBuilding,
    *,
    prefer: int,
    avoid: set[int] | None = None,
    allowed: set[int] | None = None,
) -> int | None:
    """An x covered by both the machine's footprint and the lane.

    A straight-line sorter needs one column, not two.  ``prefer`` spreads
    successive sorters across the machine's width and ``avoid`` keeps two
    sorters on the same machine off the same column.  ``allowed`` narrows the
    choice to the columns the machine's insert poses actually reach -- the
    middle three of a Matrix Lab's five, four of a Chemical Plant's nine -- so a
    wide machine is served on a column it HAS rather than skipped on one it does
    not.  Returns ``None`` rather than emitting a sorter whose ends do not line
    up, or one anchored where the game has no slot.
    """
    lane_xs = {buildings[i].x for i in lane}
    if not lane_xs:
        return None
    taken = avoid or set()
    covered = [
        machine.x + d
        for d in range(machine.width)
        if machine.x + d in lane_xs
        and machine.x + d not in taken
        and (allowed is None or machine.x + d in allowed)
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


def _tower_keep_out(buildings: list[PlacedBuilding]) -> set[tuple[int, int]]:
    """Cells a Tesla Tower may not stand on, footprints AND clearance halos.

    Footprints alone are not enough, and a Splitter is why.  It is
    belt-integrated, so it reports no occupied tile at all -- but its collider is
    a CROSS whose arms reach 1.19 world units, and a tower reaches 0.3, which is
    more than the 1.2566 units in one tile.  A tower placed on the tile next to a
    junction intersects it, and `geom.collide` refuses the whole placement for
    that one pair.

    So every building contributes a halo of the separation its clearance
    requires against a tower's, measured centre to centre in tiles.  For a
    Splitter that is 1.5, which takes out the four neighbours and the four
    diagonals; for a machine the halo is inside its own footprint and adds
    nothing.
    """
    tower_cl = max(catalog.clearance(CONSTANTS.tesla_item_id, 0.0))
    out: set[tuple[int, int]] = set()
    for b in buildings:
        try:
            info = catalog.building(b.item_id)
        except KeyError:
            continue
        need = (max(catalog.clearance(b.item_id, b.yaw)) + tower_cl) / 2.0
        reach = math.ceil(need - 1e-9) - 1
        tiles = (
            [(b.x + dx, b.y + dy) for dx in range(b.width) for dy in range(b.height)]
            if info.occupies_tiles
            else [(b.x, b.y)]
        )
        for tx, ty in tiles:
            out.add((tx, ty))
            for hx in range(tx - reach, tx + reach + 1):
                for hy in range(ty - reach, ty + reach + 1):
                    if math.hypot(hx - tx, hy - ty) < need:
                        out.add((hx, hy))
    return out


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
    occupied = _tower_keep_out(buildings)

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

    Repaired by stepping toward the network rather than by refusing: a relay on
    the segment between the stranded tower and its nearest linked neighbour
    shortens the gap, so a bounded number of steps closes it.

    The relay is placed within ``link`` of the LINKED end, not at the midpoint.
    A midpoint only works while the gap is under twice the link distance; past
    that the relay reaches neither end, so ``seen`` never grows, the next pass
    picks the same stray tower and the same midpoint, and the loop spends its
    whole bound piling unconnected towers on one spot.  Measured on
    ``universe-matrix``, where a top-up tower in the riser margin landed 67
    tiles from the network: 226 towers placed, 126 of them stray, against 110
    towers and none stray on the runs that did not hit it.  Stepping from the
    linked end instead makes every relay join the network as it is placed, so
    each pass advances the frontier and the walk terminates.
    ``power.connectivity`` still judges the result.
    """
    link = float(CONSTANTS.link_distance)
    # The same halo the coverage pass uses: a relay tower next to a junction
    # collides with it exactly as a coverage tower does.
    occupied = _tower_keep_out(buildings)

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
        gap = math.dist(towers[j], towers[near])
        if not gap:
            break  # two towers on one tile; nothing a relay can add
        # Aim 60% of a link out from the linked end, and allow the search to
        # drift up to 30% more.  The relay is then at most 90% of a link from
        # the network -- connected for certain -- while still advancing the
        # frontier by at least 30% of a link every pass.
        along = min(0.5, link * 0.6 / gap)
        spot = _nearest_free(
            int(nx + (sx - nx) * along),
            int(ny + (sy - ny) * along),
            occupied,
            link * 0.3,
        )
        if spot is None:
            break  # nowhere to stand; the validator reports the split network
        centre = (spot[0] + 0.5, spot[1] + 0.5)
        if math.dist(centre, towers[near]) > link:
            break  # the relay would be stranded too; say so rather than pile up
        occupied.add(spot)
        towers.append(centre)
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
        :data:`RETRY_BUDGET_S` before refusing.  Deterministic refusals -- no
        budget, empty spec, and a recipe no row can wire -- skip the retry:
        repeating them cannot change them.

        Within one attempt, :func:`_solve_plan` hands back every plan its width
        sweep solved, densest first, and each is emitted and self-checked in turn
        until one passes.  Emission and the validator are gates the sweep cannot
        see, so a plan failing one says nothing about the plans behind it.  Note
        what this is not: every element of that list is a plan CP-SAT returned
        under the same constraints, so reaching past the head is continuing the
        search, not reaching for a seed.  There is no seed here.

        In practice the head always wins -- measured over every ``universe-matrix``
        cell at four budgets, exactly one plan was ever emitted -- so this loop
        adds no measurable time.  :func:`_solve_plan` has the numbers and says
        what to conclude if that ever stops being true.

        ``time_budget_s`` bounds ALL the SEARCH in this call, not each solve
        inside it.  It used to bound each one separately, so the phases summed:
        a 4s budget bought 4s of search and then 15s more on the retry.  A
        budget nothing enforces is not a budget, and a caller who cannot
        predict how long this takes cannot build a gate out of it -- the full
        audit ran 100 minutes and was killed twice before it finished.

        The search ceiling is ``max(time_budget_s, RETRY_BUDGET_S)``: the retry
        still happens, it just draws from the same clock as the first attempt
        instead of starting a fresh one.

        Emission and the self-check sit OUTSIDE that ceiling, because neither
        is a search and neither can be abandoned half-done -- a partly
        validated placement cannot be called clean.  They are proportional to
        the result, not to the seconds allowed, and on the largest spec in the
        corpus they are the whole overrun: ``universe-matrix`` at a 4s budget
        measures 4.2s + 10.1s of search (correctly clamped -- the retry got
        10.75s, not a fresh 15), then 0.3s to emit and 3.8s to check 92,907
        tiles, for 18.4s total.  So expect roughly the ceiling plus a few
        seconds on a big spec.

        Read that figure as core-allocation-dependent, though, not absolute: the
        same cell measures 22-26s with 8 search workers and 50s under the audit
        at ``--jobs 16``, because emission and the check are real work that
        contends like any other.  What stays true across all of them is the
        SHAPE -- search clamped to the ceiling, then a fixed emit-and-check tail
        proportional to the tile count.  A cell whose SEARCH runs past the
        ceiling is the defect worth chasing; a slow tail is just a big spec on a
        busy machine.
        """
        if time_budget_s <= 0:
            raise NoValidLayout(
                _refusal(FALLBACK_NO_BUDGET),
                spec_label=spec.label,
                budget_s=time_budget_s,
            )

        deadline = time.monotonic() + max(time_budget_s, RETRY_BUDGET_S)
        budgets = [time_budget_s]
        if time_budget_s < RETRY_BUDGET_S:
            budgets.append(RETRY_BUDGET_S)

        reason = FALLBACK_NO_SOLUTION
        detail = ""
        spent = 0.0
        for budget in budgets:
            # Never ask for more seconds than the call has left.  Clamping here
            # rather than skipping the phase keeps the retry meaningful when the
            # first attempt returned early, which is the common case.
            budget = min(budget, deadline - time.monotonic())
            if budget <= 0:
                reason, detail = FALLBACK_NO_SOLUTION, "budget exhausted"
                break
            spent = budget
            plans, reason, detail = _solve_plan(
                spec, time_budget_s=budget, workers=self.workers
            )
            if not plans:
                if reason == FALLBACK_SEED_UNWIRABLE:
                    break  # structural -- more seconds cannot change a recipe
                if reason == FALLBACK_EMPTY_SPEC:
                    break  # deterministic -- more seconds cannot help
                continue
            # Densest first, and every one of them a plan the solver actually
            # returned.  Emission and the self-check are gates the sweep could
            # not see, so a plan failing one is not evidence against the plans
            # behind it.  Measured, no cell in the corpus reaches past the head
            # -- see `_solve_plan` -- so read a second iteration here as a
            # defect in the packer to go and find, not as this loop paying off.
            for plan in plans:
                try:
                    # Emission stays inside the guard on purpose.  A direct
                    # insert the solver believed in may turn out to have no
                    # machine pair within reach once real x positions exist, and
                    # dropping that lane without emitting its replacement sorter
                    # would starve the consumer.  So a plan that will not emit is
                    # not a layout: try the next one, then a longer budget, and
                    # refuse if neither works.
                    placement = _emit(spec, plan, power=self.power)
                except (ValueError, KeyError) as exc:
                    reason, detail = FALLBACK_EMISSION, str(exc)
                    continue
                placement.stats["solver_rejected"] = 0.0
                placement.stats["fallback_reason"] = FALLBACK_NONE
                bad = _rejected(placement, spec, power=self.power)
                if bad:
                    # Solved, emitted, and still wrong. Keep sweeping rather than
                    # hand back something the validator will refuse anyway: this
                    # method's contract is a VALID placement or an exception, and
                    # until now that was argued rather than enforced.
                    reason, detail = FALLBACK_SELF_CHECK, bad
                    continue
                return placement

        # THERE IS NO FALLBACK HERE, AND THERE IS NOT GOING TO BE ONE.
        #
        # This is the second time the seed has been removed.  The first removal
        # took out a path that returned `fallback_plan`'s greedy stacking
        # unexamined; it came back wearing a self-check, on the argument that a
        # CHECKED seed is different in kind from an unchecked one, and that a
        # valid-but-loose blueprint beats no blueprint.
        #
        # Both halves of that argument are wrong.
        #
        # The check only proves the seed is not broken.  It says nothing about
        # why the solver had nothing to hand back, and that is the only question
        # worth answering: a spec that reaches this line has a packer producing
        # rows its own allocator cannot wire.  Emitting the seed makes that
        # defect invisible -- the cell goes green, the audit says CLEAN, and the
        # thing that needs fixing is never looked at again.  The measurement
        # that was offered in its defence is the case against it: 50,512 tiles
        # against roughly 39,000 for a solved plan on
        # `universe-matrix`/`free-proliferation`.  Density is the objective of
        # this whole program.  Buying a green cell with 30% more area is not a
        # rescue, it is the failure being paid for in the currency we are here
        # to minimise.
        #
        # So an unroutable plan is a REFUSAL.  If that loses cells, the packer
        # is what to fix -- routability belongs in the model as a constraint,
        # not in a rescue after the fact.  A refusal names a bug; a fallback
        # hides one.
        raise NoValidLayout(
            _refusal(reason, detail), spec_label=spec.label, budget_s=spent
        )


def machine_group_footprint(group: MachineGroup) -> tuple[int, int]:
    """Footprint of the building a ``MachineGroup`` runs on, in tiles."""
    item_id = MACHINE_ITEM_IDS[group.machine_item_id]
    return catalog.footprint(item_id)
