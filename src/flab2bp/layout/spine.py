"""Strategy A -- structured spine with a CP-SAT arrangement.

The skeleton is *routable by construction*.  Machines live in rows; belts live in
corridors between rows; every lane an item could need has a reserved,
collision-free channel before the solver runs.  CP-SAT therefore only ever
chooses *how much* structure to spend, never *whether a route exists* -- there is
no place-then-route repair loop and no infeasible-placement dead end.

    corridor C0   ═══ external inputs ═══════════════
    row 0         [ smelter ][ smelter ][T]
    corridor C1   ═══ iron-ingot ═══════════════════
    row 1         [ assembler ][ assembler ]
    corridor C2   ═══ product out ═════════════════

Two structural facts do most of the work:

* **Rows hold machines, corridors hold belts**, so a Tesla tower placed in a row
  blocks no belt.  Power is just another block in the row's 1D packing.
* **A corridor lane is within sorter reach of every machine on both sides of it**,
  so a distribution problem costs one lane per corridor rather than one route per
  machine.  Proliferator and power both ride on this.

Deliberate v1 scope reductions, each documented where it appears:

* No trunk risers (``T = 0``).  An item spanning non-adjacent rows takes a lane in
  every corridor between, which is correct and routable, just taller than a riser
  would be.  See ``_lane_requirements``.
* All machines of a group share one row.
* Corridor lanes are never stacked at ``z = 1``: the catalog confirms sorters
  never span altitudes, so a raised lane could not be tapped.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field, replace
from fractions import Fraction

from ortools.sat.python import cp_model

from flab2bp.dsp import catalog, params
from flab2bp.layout.base import (
    DEFAULT_SEARCH_WORKERS,
    Facing,
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


def _lane_requirements(
    groups: dict[str, _Group],
    edges: list[_Edge],
    rows: list[list[str]],
    direct: set[tuple[str, str, str]],
    spec: BuildSpec,
) -> list[list[str]]:
    """Which item occupies a lane in which corridor, ordered by sorter reach.

    With no trunk risers, an edge spanning rows ``r`` to ``s`` takes a lane in
    every corridor ``r+1 .. s``.  Corridor ``c`` sits above row ``c``.
    """
    at = _row_index(rows)
    n_corr = len(rows) + 1
    reach = CONSTANTS.sorter_max_reach

    # item -> set of corridors it must cross, and where it is tapped.
    crossing: list[set[str]] = [set() for _ in range(n_corr)]
    tap_above: list[set[str]] = [set() for _ in range(n_corr)]
    tap_below: list[set[str]] = [set() for _ in range(n_corr)]

    # What each row consumes and produces, and the corridor span each item needs.
    consumes: list[set[str]] = [set() for _ in rows]
    produces: list[set[str]] = [set() for _ in rows]
    span: dict[str, list[int]] = {}

    def widen(item: str, lo: int, hi: int) -> None:
        cur = span.setdefault(item, [lo, hi])
        cur[0], cur[1] = min(cur[0], lo), max(cur[1], hi)

    for e in edges:
        if (e.src, e.dst, e.item) in direct:
            continue
        r, s = at[e.src], at[e.dst]
        widen(e.item, r + 1, s)
        produces[r].add(e.item)
        consumes[s].add(e.item)

    for item in spec.external_inputs:
        consumers = [at[k] for k, g in groups.items() if item in g.inputs]
        if consumers:
            widen(item, 0, max(consumers))
            for r in consumers:
                consumes[r].add(item)

    for item in spec.outputs:
        sources = [at[k] for k, g in groups.items() if item in g.outputs]
        if sources:
            widen(item, min(sources) + 1, n_corr - 1)
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
        for items, first, second in (
            (sorted(consumes[r]), slot_below, slot_above),
            (sorted(produces[r]), slot_above, slot_below),
        ):
            for item in items:
                if item in slot_below or item in slot_above:
                    continue  # already reachable from this row
                target = first if len(first) < reach else second
                if len(target) >= reach:
                    raise ValueError(
                        f"row {r} taps {len(consumes[r] | produces[r])} distinct items, "
                        f"exceeding the {2 * reach} its two corridors can reach"
                    )
                target.add(item)
        for c, slot_items in ((r, slot_below), (r + 1, slot_above)):
            if not 0 <= c < n_corr:
                continue
            for item in slot_items:
                lo, hi = span[item]
                widen(item, min(lo, c), max(hi, c))
                (tap_below if c == r else tap_above)[c].add(item)

    for item, (lo, hi) in span.items():
        for c in range(max(lo, 0), min(hi, n_corr - 1) + 1):
            crossing[c].add(item)

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
        above = sorted(tap_above[c] & crossing[c])
        below = sorted(tap_below[c] & crossing[c])
        through = sorted(crossing[c] - set(above) - set(below))
        order = lane_order(above, below, through, reach)
        if order is None:
            raise ValueError(
                f"corridor {c} needs {len(above)} taps above and {len(below)} below, "
                f"exceeding sorter reach {reach}"
            )
        ordered.append(order)
    return ordered


def fallback_plan(spec: BuildSpec) -> _Plan:
    """Deterministic, always-feasible: one group per row, no direct insertion.

    Also the CP-SAT warm start and width-sweep seed, so it runs on every solve
    and cannot rot.
    """
    groups, edges = _adapt(spec)
    rows = _topological_rows(groups, edges)
    lanes = _lane_requirements(groups, edges, rows, set(), spec)
    return _Plan(rows=rows, lanes=lanes, solver_status="fallback")


#: Why a placement used the greedy fallback instead of a solved plan, reported
#: as ``stats["fallback_reason"]``.  Three different failure modes used to be
#: indistinguishable behind ``fallback_used=1``, which is how a strategy that had
#: stopped solving entirely on real specs went unnoticed.
FALLBACK_NONE = 0.0  # a solved plan was used; no fallback
FALLBACK_NO_BUDGET = 1.0  # time_budget_s <= 0, so the solver was never asked
FALLBACK_EMPTY_SPEC = 2.0  # nothing to lay out
FALLBACK_UNROUTABLE = 3.0  # every candidate width packed rows that cannot be wired
FALLBACK_NO_SOLUTION = 4.0  # CP-SAT found neither OPTIMAL nor FEASIBLE
FALLBACK_EMISSION = 5.0  # a plan solved, but emitting it raised


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
    tapped_by: dict[str, list[str]] = defaultdict(list)
    for k, g in groups.items():
        for item in set(g.inputs) | set(g.outputs):
            tapped_by[item].append(k)
    for r in range(n):
        flags = []
        for item, holders in tapped_by.items():
            t = model.new_bool_var(f"tap_{r}_{item}")
            model.add_max_equality(t, [in_row[k, r] for k in holders])
            flags.append(t)
        if flags:
            model.add(sum(flags) <= 2 * tap_reach)

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
    lane_items = sorted({e.item for e in edges} | set(spec.external_inputs) | set(spec.outputs))
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
            if item in spec.outputs:
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
        ch = model.new_int_var(0, len(lane_items), f"corr_{c}")
        model.add(ch == sum(used))
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
    lanes = _lane_requirements(groups, edges, rows, direct, spec)
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


def _realizable_direct(
    spec: BuildSpec,
    groups: dict[str, _Group],
    edges: list[_Edge],
    plan: _Plan,
    *,
    power: bool,
) -> tuple[set[tuple[str, str, str]], list[list[str]]]:
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
        lanes = _lane_requirements(groups, edges, plan.rows, current, spec)
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
            dy = row_y[r_dst] - (row_y[r_src] + row_heights[r_src] - 1)
            prod, cons = xs.get(src, []), xs.get(dst, [])
            if not prod or not cons or dy < 1:
                excess = reach + 1
            else:
                # At least one consumer must have a producer near enough in x, or
                # the lane would vanish with nothing able to replace it.
                best = min(min(abs(p - c) for p in prod) + dy for c in cons)
                excess = best - reach
            if excess > 0 and (worst is None or excess > worst[0]):
                worst = (excess, ek)
        if worst is None:
            return current, lanes
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

    direct, lanes = _realizable_direct(spec, groups, edges, plan, power=power)
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

    # --- lane extents -----------------------------------------------------
    # A lane only needs belt where something actually taps it, plus a run to the
    # block edge when it carries an external input in or a product out.  Full
    # width costs no extra *area*, but it triples the building count, which
    # matters when pasting.  Untapped pass-through lanes keep their full width:
    # they reserve a channel that a future trunk riser will use.
    extents: dict[tuple[int, str], tuple[int, int]] = {}

    def _extend(c: int, item: str, lo: int, hi: int) -> None:
        cur = extents.get((c, item))
        extents[c, item] = (lo, hi) if cur is None else (min(cur[0], lo), max(cur[1], hi))

    for key, g in groups.items():
        r = at[key]
        xs = [buildings[i].x for i in machine_at[key]]
        if not xs:
            continue
        lo, hi = min(xs), max(xs) + g.width - 1
        for item, into in [(i, True) for i in g.inputs] + [(o, False) for o in g.outputs]:
            tap = _find_tap(plan, r, item, corr_y, row_y, row_heights, out=not into)
            if tap is not None:
                _extend(tap.corridor, item, lo, hi)

    for c, order in enumerate(plan.lanes):
        for item in order:
            if (c, item) not in extents:
                continue
            if item in spec.external_inputs:
                _extend(c, item, 0, 0)
            if item in spec.outputs:
                _extend(c, item, content_w - 1, content_w - 1)

    # --- corridor lanes ---------------------------------------------------
    # Keyed by (corridor, DEPTH), not (corridor, item): an item may occupy
    # several lanes in one corridor for capacity, and keying by item made the
    # second lane overwrite the first.  `_find_tap` then returned the first
    # lane's y while this dict held the last lane's tiles, so every sorter on
    # a duplicated item anchored on one belt and named another.
    lane_tiles: dict[tuple[int, int], list[int]] = {}
    lane_item_of: dict[tuple[int, int], str] = {}
    for c, order in enumerate(plan.lanes):
        for depth_i, item in enumerate(order):
            y = corr_y[c] + depth_i
            lo, hi = extents.get((c, item), (0, content_w - 1))
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
                        yaw=Facing.EAST.value,
                        # Which item this lane carries is layout knowledge that
                        # nothing can recover once emission drops it.  The belt
                        # marker pass needs it to tag external-input runs, and
                        # the validator's per-item flow check needs it too.
                        carries_item=item,
                    )
                )
            # Forward-link the run west to east, matching what the game emits.
            for a, b in zip(indices, indices[1:], strict=False):
                buildings[a] = _with_output(buildings[a], b)
            lane_tiles[c, depth_i] = indices
            lane_item_of[c, depth_i] = item

    # --- direct inserts ---------------------------------------------------
    # A direct-inserted edge has no lane, so the sorter must reach machine to
    # machine.  This runs before the belt taps so that a connection served
    # entirely by direct insertion can be skipped there rather than sprouting a
    # second, redundant feed.
    rate_of = {(e.src, e.dst, e.item): e.rate for e in edges}
    fully_direct_in: set[tuple[str, str]] = set()
    fully_direct_out: set[tuple[str, str]] = set()
    in_edges: dict[tuple[str, str], list[_Edge]] = defaultdict(list)
    out_edges: dict[tuple[str, str], list[_Edge]] = defaultdict(list)
    for e in edges:
        in_edges[e.dst, e.item].append(e)
        out_edges[e.src, e.item].append(e)
    for (k, item), es in in_edges.items():
        if item not in spec.external_inputs and all(
            (e.src, e.dst, e.item) in plan.direct for e in es
        ):
            fully_direct_in.add((k, item))
    for (k, item), es in out_edges.items():
        if item not in spec.outputs and all((e.src, e.dst, e.item) in plan.direct for e in es):
            fully_direct_out.add((k, item))

    sorters = 0
    direct_sorters = 0
    for src, dst, item in sorted(plan.direct):
        r_src, r_dst = at[src], at[dst]
        y_src = row_y[r_src] + row_heights[r_src] - 1
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
        for ci in cons:
            cb = buildings[ci]
            best: tuple[int, int, int, int] | None = None
            for pi in sorted(prod, key=lambda p: abs(buildings[p].x - cb.x)):
                pb = buildings[pi]
                lo = max(pb.x, cb.x)
                hi = min(pb.x + pb.width, cb.x + cb.width) - 1
                if lo > hi:
                    continue  # no shared column: unreachable in a straight line
                span = abs(dy)
                if 1 <= span <= CONSTANTS.sorter_max_reach:
                    best = (pi, ci, span, lo)
                    break
            if best is not None:
                pairs.append(best)
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
        r = at[key]
        connections = [(item, rate * g.count, True) for item, rate in g.inputs.items()]
        connections += [(item, rate * g.count, False) for item, rate in g.outputs.items()]
        for item, rate, into_machine in connections:
            if rate <= 0:
                continue
            # Already fed (or drained) entirely by direct insertion.
            if into_machine and (key, item) in fully_direct_in:
                continue
            if not into_machine and (key, item) in fully_direct_out:
                continue
            tap = _find_tap(
                plan, r, item, corr_y, row_y, row_heights, out=not into_machine
            )
            if tap is None:
                continue
            machines = machine_at[key]
            if not machines:
                continue
            # Size against THIS item's per-machine rate. `rate` here is the
            # group total, so divide it back out: a sorter serves one machine.
            # Sizing against the machine's average across its ingredients
            # under-provisions whichever one is hot -- see _pick_sorter.
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

    return Placement(
        buildings=tuple(buildings),
        description=f"flab2bp spine layout ({spec.label or 'default'})",
        short_desc=spec.label or "flab2bp",
        stats={
            "area": float(_bbox_area(buildings)),
            "machines": float(sum(g.count for g in groups.values())),
            "belt_tiles": float(sum(len(v) for v in lane_tiles.values())),
            "sorters": float(sorters),
            "direct_sorters": float(direct_sorters),
            "spray_coaters": float(coaters),
            "towers": float(towers),
            # Powered buildings the top-up could not reach because every tile
            # within a supply radius of them was occupied. Non-zero means the
            # build is genuinely under-powered, and the validator will say so.
            "power_uncovered": float(uncovered),
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


def _find_tap(
    plan: _Plan,
    r: int,
    item: str,
    corr_y: list[int],
    row_y: list[int],
    row_heights: list[int],
    *,
    out: bool,
) -> _Tap | None:
    """Find a lane carrying ``item`` within sorter reach of row ``r``.

    Corridor ``c`` sits *above* row ``c``, so row ``r`` touches corridor ``r``
    with its top edge and corridor ``r + 1`` with its bottom edge.  The two sides
    measure depth in opposite directions, which is exactly what ``lane_order``
    arranges for:

    * from the corridor above, lane ``j`` of ``L`` is ``L - j`` tiles away;
    * from the corridor below, lane ``j`` is ``j + 1`` tiles away.

    Returns ``None`` when no lane is in reach rather than emitting a sorter that
    cannot physically connect.
    """
    top = row_y[r]
    bottom = row_y[r] + row_heights[r] - 1
    # Outputs prefer the corridor below (natural top-to-bottom flow); inputs the
    # corridor above.  Either is legal, so both are tried.
    order = [(r + 1, False), (r, True)] if out else [(r, True), (r + 1, False)]
    for c, from_corridor_above in order:
        if c < 0 or c >= len(plan.lanes) or item not in plan.lanes[c]:
            continue
        lanes = plan.lanes[c]
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
            if from_corridor_above:
                span, machine_y = len(lanes) - j, top
            else:
                span, machine_y = j + 1, bottom
            if 1 <= span <= CONSTANTS.sorter_max_reach:
                return _Tap(
                    corridor=c,
                    depth=j,
                    lane_y=corr_y[c] + j,
                    machine_y=machine_y,
                    span=span,
                )
    return None


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
        """Always returns a valid ``Placement``, solver or no solver.

        A solver plan that turns out to be unroutable degrades to the fallback,
        but never silently: ``stats["solver_rejected"]`` records it, so a
        regression that quietly disables the solver shows up in the bake-off
        rather than hiding behind a plausible-looking area.
        """
        placement: Placement | None = None
        rejected = 0.0
        reason = FALLBACK_NO_BUDGET
        if time_budget_s > 0:
            try:
                plan, reason = _solve_plan(
                    spec, time_budget_s=time_budget_s, workers=self.workers
                )
                if plan is not None:
                    # Emission is inside the guard on purpose.  A direct insert
                    # the solver believed in may turn out to have no machine pair
                    # within reach once real x positions exist, and dropping that
                    # lane without emitting its replacement sorter would starve
                    # the consumer.  Degrade to the fallback instead -- and record
                    # it, so a regression that quietly disables the solver shows
                    # up in the bake-off rather than hiding behind a plausible
                    # area.
                    placement = _emit(spec, plan, power=self.power)
            except (ValueError, KeyError):
                placement, rejected, reason = None, 1.0, FALLBACK_EMISSION
        if placement is None:
            placement = _emit(spec, fallback_plan(spec), power=self.power)
        else:
            reason = FALLBACK_NONE
        placement.stats["solver_rejected"] = rejected
        placement.stats["fallback_reason"] = reason
        return placement


def machine_group_footprint(group: MachineGroup) -> tuple[int, int]:
    """Footprint of the building a ``MachineGroup`` runs on, in tiles."""
    item_id = MACHINE_ITEM_IDS[group.machine_item_id]
    return catalog.footprint(item_id)
