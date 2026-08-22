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
from dataclasses import dataclass, field
from fractions import Fraction

from ortools.sat.python import cp_model

from flab2bp.dsp import catalog
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
    for r in range(len(rows)):
        for items, near, far in (
            (sorted(consumes[r]), r, r + 1),
            (sorted(produces[r]), r + 1, r),
        ):
            for i, item in enumerate(items):
                c = near if i < reach else far
                if c >= n_corr or c < 0:
                    c = near
                lo, hi = span[item]
                widen(item, min(lo, c), max(hi, c))
                # Corridor r sits above row r, so the row taps it from below;
                # corridor r+1 sits below, so the row taps it from above.
                (tap_below if c == r else tap_above)[c].add(item)

    for item, (lo, hi) in span.items():
        for c in range(max(lo, 0), min(hi, n_corr - 1) + 1):
            crossing[c].add(item)

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


def _solve_plan(spec: BuildSpec, *, time_budget_s: float, workers: int) -> _Plan | None:
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
        return None

    widths = _candidate_widths(groups, base)
    best: _Plan | None = None
    best_area = math.inf
    per_solve = max(time_budget_s / max(len(widths), 1), 0.25)

    for w_cap in widths:
        try:
            plan = _solve_one(spec, groups, edges, depth, n, w_cap, per_solve, workers)
        except ValueError:
            # This width produced a row packing that cannot be routed within
            # sorter reach.  Skip it and keep sweeping rather than abandoning
            # every remaining width.
            continue
        if plan is None:
            continue
        area = _measure(spec, plan)
        if area < best_area:
            best_area, best = area, plan
    return best


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
    """Cheapest sorter tier and count carrying ``rate`` across ``span`` tiles."""
    for tier in SORTER_TIERS:
        per = catalog.sorter_rate(tier, span)
        count = math.ceil(rate / per) if rate > 0 else 1
        if count <= available:
            return tier, max(count, 1)
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
                        y=row_y[r],
                        width=s.width,
                        height=th,
                    )
                )
                towers += 1
                continue
            g = groups[s.key]
            machine_at[s.key].append(len(buildings))
            buildings.append(
                PlacedBuilding(
                    item_id=g.item_id,
                    model_index=g.model_index,
                    x=s.x,
                    y=row_y[r],
                    width=g.width,
                    height=g.height,
                    recipe_id=0,
                )
            )
        row_widths.append(width)
    content_w = max([*row_widths, 1])

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
    lane_tiles: dict[tuple[int, str], list[int]] = {}
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
                    )
                )
            # Forward-link the run west to east, matching what the game emits.
            for a, b in zip(indices, indices[1:], strict=False):
                buildings[a] = _with_output(buildings[a], b)
            lane_tiles[c, item] = indices

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
        # Pair each consumer with its nearest producer in x.  Rows are packed
        # independently from x=0, so equal-footprint groups line up naturally.
        pairs: list[tuple[int, int, int]] = []
        for ci in cons:
            cb = buildings[ci]
            pi = min(prod, key=lambda p: abs(buildings[p].x - cb.x))
            span = abs(buildings[pi].x - cb.x) + dy
            if 1 <= span <= CONSTANTS.sorter_max_reach:
                pairs.append((pi, ci, span))
        rate = rate_of.get((src, dst, item), Fraction(0))
        if not pairs:
            raise ValueError(
                f"direct insert {src} -> {dst} ({item}) has no machine pair within "
                f"sorter reach {CONSTANTS.sorter_max_reach}"
            )
        worst = max(s for _, _, s in pairs)
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
        for pi, ci, _span in pairs:
            buildings.append(
                PlacedBuilding(
                    item_id=tier,
                    model_index=tier_model,
                    x=buildings[pi].x,
                    y=y_src,
                    width=1,
                    height=1,
                    x2=buildings[ci].x,
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
            pick = _pick_sorter(rate, tap.span, g.block_width)
            if pick is None:
                continue
            tier, count = pick
            sorters += _place_sorters(
                buildings,
                lane_tiles[tap.corridor, item],
                machine_at[key],
                lane_y=tap.lane_y,
                machine_y=tap.machine_y,
                tier=tier,
                count=count,
                into_machine=into_machine,
            )

    # --- spray coaters ----------------------------------------------------
    # A coater is a belt addon: it consumes no grid tile, which is what makes
    # proliferation nearly free in area.  The cost is the proliferator lane.
    coaters = 0
    spray = catalog.building(CONSTANTS.spray_item_id)
    for item in spec.spray_lanes:
        for (_c, lane_item), indices in lane_tiles.items():
            if lane_item != item or not indices:
                continue
            mid = buildings[indices[len(indices) // 2]]
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
            break

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
    return PlacedBuilding(
        item_id=b.item_id,
        model_index=b.model_index,
        x=b.x,
        y=b.y,
        z=b.z,
        width=b.width,
        height=b.height,
        yaw=b.yaw,
        recipe_id=b.recipe_id,
        output_obj=target,
        input_obj=b.input_obj,
    )


@dataclass(frozen=True, slots=True)
class _Tap:
    """A reachable connection between one machine row and one corridor lane."""

    corridor: int
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
        j = lanes.index(item)
        lane_y = corr_y[c] + j
        if from_corridor_above:
            span, machine_y = len(lanes) - j, top
        else:
            span, machine_y = j + 1, bottom
        if 1 <= span <= CONSTANTS.sorter_max_reach:
            return _Tap(corridor=c, lane_y=lane_y, machine_y=machine_y, span=span)
    return None


def _place_sorters(
    buildings: list[PlacedBuilding],
    lane: list[int],
    machines: list[int],
    *,
    lane_y: int,
    machine_y: int,
    tier: int,
    count: int,
    into_machine: bool,
) -> int:
    """Connect a lane to a group's machines with ``count`` sorters.

    Anchors sit on the connected tiles and the ``input_obj`` / ``output_obj``
    indices carry the real semantics -- which is how the game itself does it.
    Measured on real blueprints, a sorter's anchors never coincide with a belt
    *building*, so sorters are overlays and do not consume build tiles.
    """
    model_index = catalog.building(tier).model_index
    placed = 0
    for i in range(count):
        if not machines:
            break
        m_idx = machines[i % len(machines)]
        m = buildings[m_idx]
        x = m.x + min(i, m.width - 1)
        belt_idx = _lane_tile_at(buildings, lane, x)
        if belt_idx is None:
            continue
        if into_machine:
            src, dst = belt_idx, m_idx
            ax, ay, bx, by = x, lane_y, m.x, machine_y
        else:
            src, dst = m_idx, belt_idx
            ax, ay, bx, by = m.x, machine_y, x, lane_y
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


def _lane_tile_at(buildings: list[PlacedBuilding], lane: list[int], x: int) -> int | None:
    for idx in lane:
        if buildings[idx].x == x:
            return idx
    return lane[0] if lane else None


def _horizontal_reach(r: int, row_heights: list[int], corridor_heights: list[int]) -> int:
    """Horizontal supply reach available to a tower sitting in row ``r``.

    A tower in row ``r`` must also power the sorters and spray coaters in the
    corridors on either side, so the worst-case vertical offset is half the row
    height plus the taller neighbouring corridor.  Evaluating the circle at that
    offset is exact, unlike an inscribed square.
    """
    table = _REACH_TABLE
    above = corridor_heights[r] if r < len(corridor_heights) else 0
    below = corridor_heights[r + 1] if r + 1 < len(corridor_heights) else 0
    dy_max = math.ceil(row_heights[r] / 2) + max(above, below)
    if dy_max >= len(table):
        raise ValueError(
            f"row {r} sits {dy_max} tiles from its corridors, beyond the "
            f"{CONSTANTS.supply_radius}-tile supply radius; no tower can cover it"
        )
    hr = table[dy_max]
    if hr <= 0:
        raise ValueError(f"row {r} is uncoverable at vertical offset {dy_max}")
    return hr


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
        if time_budget_s > 0:
            try:
                plan = _solve_plan(spec, time_budget_s=time_budget_s, workers=self.workers)
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
                placement, rejected = None, 1.0
        if placement is None:
            placement = _emit(spec, fallback_plan(spec), power=self.power)
        placement.stats["solver_rejected"] = rejected
        return placement


def machine_group_footprint(group: MachineGroup) -> tuple[int, int]:
    """Footprint of the building a ``MachineGroup`` runs on, in tiles."""
    item_id = MACHINE_ITEM_IDS[group.machine_item_id]
    return catalog.footprint(item_id)
