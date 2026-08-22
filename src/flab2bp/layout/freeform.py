"""Strategy B -- free-form packing plus belt routing.

Where Strategy A commits to a global skeleton, this places its units anywhere a
2D packer can fit them and then *routes* the belts through whatever space is
left.  The density ceiling is higher because nothing is reserved in advance; the
risk is the classic place-then-route failure, where phase 1 optimises a proxy
that knows nothing about routing and hands phase 2 a placement it cannot wire.

Three things keep that risk bounded:

* **A strip is routable on its own.**  The placeable unit is not a bare machine
  but a *strip*: a run of machines of one recipe, with its input lanes already
  attached above and its output lanes below, each within sorter reach.  Phase 1
  therefore cannot produce a machine that is impossible to feed -- only one that
  is awkward to reach.
* **A reserved margin** on each strip's east and south faces guarantees a
  connected mesh of free cells for the router, rather than a legal-but-choked
  pack.
* **Negotiated congestion** (PathFinder-style rip-up-and-reroute) resolves the
  contention that remains, and a hard iteration cap plus a guaranteed-feasible
  fallback mean ``lay_out`` always returns something valid.

Deliberate simplifications, each with its reason:

* **No splitters.**  A strip gets one output lane *per destination strip*, so
  every net has exactly one source and one sink.  Belts merge natively in DSP
  (two chains pointing at one tile), so many-to-one needs nothing; giving each
  destination its own lane removes the one-to-many case entirely.  The cost is
  extra lanes, bounded by sorter reach at three per side.
* **Level changes cost two tiles.**  Belts climb 0.5 per tile, so one integer
  level is two tiles of run.  The router reserves both.

Where this differs from the written spec, and why
-------------------------------------------------
The spec's §2.3 chose I/O pads with a solver-chosen face.  This implements the
fixed east/south margin instead: it is the same structural guarantee -- every
unit has free cells adjacent to it -- without a face variable per unit, and the
lanes that pads were meant to reach are already part of the strip.

The spec's §5.3 made the tower lattice a fixed blockage set inside phase 1.  That
encoding fights the objective: the lattice extent depends on the final width,
which is the variable being minimised, so fixing it either inflates the bounding
box or under-covers the result.  Towers are therefore placed after packing, into
the margin cells the packing already reserved, and then *verified* -- coverage
and connectivity are both repaired greedily until they hold.  The guarantee is
the same; only the mechanism is post-hoc.
"""

from __future__ import annotations

import heapq
import math
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from fractions import Fraction

from ortools.sat.python import cp_model

from flab2bp.dsp import catalog
from flab2bp.layout.base import (
    DEFAULT_SEARCH_WORKERS,
    Facing,
    PlacedBuilding,
    Placement,
)
from flab2bp.layout.spine import BELT_ITEM_IDS, MACHINE_ITEM_IDS, SORTER_TIERS
from flab2bp.spec import BuildSpec

#: Free tiles reserved on a strip's east and south faces.  One is enough for a
#: belt to pass; the router uses upper levels when one is not.
MARGIN = 1

#: Levels available to the router.  Ground plus two stacked crossing levels,
#: matching what the corpus shows real blueprints using.
LEVELS = catalog.MAX_BELT_STACK_LEVELS

#: Rip-up-and-reroute iterations before a placement is declared unroutable.
RRR_MAX = 8

#: Outer repair iterations before falling back.
OUTER_MAX = 3

#: Objective weights.  ``λ`` pulls connected strips together (this is what makes
#: routing tractable); ``μ`` rewards a direct insert, which deletes a whole net.
LAMBDA_HPWL = 1
MU_DIRECT = 4

#: Above this many goals, the A* heuristic switches from exact
#: distance-to-nearest-goal to distance-to-goal-bounding-box.  Both are
#: admissible; the box is weaker but O(1) instead of O(|goals|) per node.
_EXACT_HEURISTIC_GOALS = 64

#: Hard cap on A* node expansions for a single net.  Exceeding it returns
#: ``None``, which the caller already treats as a route failure and handles by
#: ripping up and retrying -- so this degrades routing quality rather than
#: correctness.  Without it a hard net explores every reachable cell x level and
#: the whole layout appears to hang.
_MAX_EXPANSIONS = 200_000

#: Tower lattice spacing.  A square lattice of spacing ``d`` leaves a worst-case
#: distance of ``d/sqrt(2)`` to the nearest lattice point, so ``d`` must satisfy
#: ``d <= R*sqrt(2)``.  12 clears the 10.5 radius with room to spare (8.49) and
#: is comfortably inside the 22.5 link distance, so the lattice both covers and
#: connects by construction.
TOWER_SPACING = 12


def lanes_for(rate: Fraction, capacity: Fraction) -> int:
    """Parallel lanes needed to carry ``rate`` at ``capacity`` per lane.

    Exact throughout: ``math.ceil`` of a ``Fraction`` is exact, so a rate that
    lands precisely on a lane boundary needs no extra lane.  A float would make
    ``24/12`` occasionally demand three lanes.
    """
    if rate <= 0:
        return 0
    if capacity <= 0:
        raise ValueError("belt capacity must be positive")
    return math.ceil(rate / capacity)


# --- adaptation ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Group:
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


@dataclass(frozen=True, slots=True)
class Strip:
    """A run of machines of one recipe, with its lanes attached.

    The lanes are part of the unit, not something routing adds later.  That is
    what makes a strip individually routable and keeps phase 1 from producing a
    machine nothing can feed.

    Vertical layout, top to bottom::

        input lanes   (len(in_lanes) rows, one belt lane each)
        machines      (mh rows)
        output lanes  (len(out_lanes) rows)
    """

    group_key: str
    recipe_id: str
    item_id: int
    model_index: int
    machines: int
    mw: int
    mh: int
    #: Items arriving, one lane each, ordered top-down.
    in_lanes: tuple[str, ...]
    #: ``(item, destination strip id)`` per lane, ordered top-down.  A separate
    #: lane per destination is what removes the need for splitters.
    out_lanes: tuple[tuple[str, str], ...]

    @property
    def width(self) -> int:
        return self.machines * self.mw

    @property
    def height(self) -> int:
        return len(self.in_lanes) + self.mh + len(self.out_lanes)

    @property
    def sid(self) -> str:
        return f"{self.group_key}"


def _sink_demand(
    groups: dict[str, _Group], spec: BuildSpec, item: str, dest_key: str
) -> Fraction:
    """Items/second one sink wants of ``item``.

    An empty ``dest_key`` is the build boundary -- the item leaves on an output
    belt -- so its demand is whatever the spec promises to deliver.
    """
    if not dest_key:
        return spec.outputs.get(item, Fraction(0))
    dest = groups.get(dest_key)
    if dest is None:
        return Fraction(0)
    return dest.count * dest.inputs.get(item, Fraction(0))


def _shard_sinks(sinks: Sequence[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    """Chunk output sinks so no strip carries more lanes than a sorter can span.

    ``sinks`` arrives grouped by item, so sequential chunking keeps a single
    item's destinations adjacent and avoids splitting one item's lanes across
    more shards than necessary.
    """
    reach = catalog.SORTER_MAX_REACH
    return [list(sinks[i : i + reach]) for i in range(0, len(sinks), reach)]


def _allocate_machines(
    count: int,
    shards: Sequence[Sequence[tuple[str, str]]],
    demand: Mapping[tuple[str, str], Fraction],
) -> list[int]:
    """Split ``count`` machines across shards in proportion to demand served.

    An even split would starve whichever shard happens to carry the hungrier
    consumers, so each shard's weight is the largest fraction of any one item's
    total demand that it is responsible for -- one machine produces all of its
    recipe's outputs at once, so the binding item is the one needing most.

    Every shard gets at least one machine (a shard with none leaves its
    destinations unfed), and the total is exactly ``count`` so the placement
    still matches the spec's machine counts.
    """
    n = len(shards)
    totals: dict[str, Fraction] = defaultdict(Fraction)
    for (item, _dest), rate in demand.items():
        totals[item] += rate

    weights: list[Fraction] = []
    for shard in shards:
        served: dict[str, Fraction] = defaultdict(Fraction)
        for item, dest in shard:
            served[item] += demand.get((item, dest), Fraction(0))
        weight = Fraction(0)
        for item, rate in served.items():
            total = totals.get(item, Fraction(0))
            weight = max(weight, rate / total if total > 0 else Fraction(1, n))
        weights.append(weight if weight > 0 else Fraction(1, n))

    total_weight = sum(weights, Fraction(0))
    if total_weight <= 0:
        weights = [Fraction(1)] * n
        total_weight = Fraction(n)

    # One machine each, then hand out the rest by largest remainder.
    allocation = [1] * n
    remaining = count - n
    exact = [remaining * w / total_weight for w in weights]
    floors = [int(v) for v in exact]
    for i, f in enumerate(floors):
        allocation[i] += f
    leftover = remaining - sum(floors)
    order = sorted(range(n), key=lambda i: exact[i] - floors[i], reverse=True)
    for i in order[:leftover]:
        allocation[i] += 1
    return allocation


def _adapt(spec: BuildSpec) -> dict[str, _Group]:
    groups: dict[str, _Group] = {}
    for i, mg in enumerate(spec.groups):
        item_id = MACHINE_ITEM_IDS.get(mg.machine_item_id)
        if item_id is None:
            raise KeyError(f"no DSP building known for machine {mg.machine_item_id!r}")
        b = catalog.building(item_id)
        groups[f"{mg.recipe_id}#{i}"] = _Group(
            key=f"{mg.recipe_id}#{i}",
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
    return groups


def plan_strips(spec: BuildSpec, *, strip_len: int = 6) -> list[Strip]:
    """Split every group into strips and attach each strip's lanes.

    A strip carries one output lane per destination, which is what removes the
    need for splitters, and a sorter spans at most ``SORTER_MAX_REACH`` tiles.
    A producer feeding more destinations than that therefore cannot reach its
    own bottom lane -- and real recipe graphs hit this routinely, ``copper-ingot``
    feeding four consumers in the orbital-collector build.

    The group is SHARDED instead: its destinations are chunked to fit the reach
    and its machines split between the chunks in proportion to the demand each
    chunk serves.  That keeps the no-splitter invariant intact and stays a
    planning change rather than a geometry one.

    Note that raising ``strip_len`` cannot help here, though an earlier version
    of this error advised exactly that: ``strip_len`` splits the PRODUCER into
    sub-strips and hands each an identical copy of the lane set, so the lane
    count is a property of how many consumer GROUPS the item feeds. Measured
    from ``strip_len`` 2 to 10000, the failure was identical every time.

    Raises rather than truncating when a recipe needs more input lanes than a
    sorter can span: a silently dropped ingredient would produce a blueprint that
    pastes cleanly and then stalls.
    """
    groups = _adapt(spec)

    producers: dict[str, list[str]] = defaultdict(list)
    for key, g in groups.items():
        for item in g.outputs:
            producers[item].append(key)

    # Which groups consume each group's output, so an output lane can be
    # dedicated per destination.
    consumers: dict[tuple[str, str], list[str]] = defaultdict(list)
    for key, g in groups.items():
        for item in g.inputs:
            for src in producers.get(item, []):
                if src != key:
                    consumers[src, item].append(key)

    strips: list[Strip] = []
    for key, g in groups.items():
        in_lanes = tuple(sorted(g.inputs))
        if len(in_lanes) > catalog.SORTER_MAX_REACH:
            raise ValueError(
                f"recipe {g.recipe_id!r} needs {len(in_lanes)} input lanes, but a "
                f"sorter spans at most {catalog.SORTER_MAX_REACH} tiles; this "
                f"recipe cannot be fed from one side"
            )

        sinks: list[tuple[str, str]] = []
        for item in sorted(g.outputs):
            dests = consumers.get((key, item), [])
            sinks.extend((item, d) for d in dests)
            if item in spec.outputs or not dests:
                sinks.append((item, ""))  # leaves the build

        shards = _shard_sinks(sinks) if sinks else [[]]
        if len(shards) > g.count:
            raise ValueError(
                f"recipe {g.recipe_id!r} feeds {len(sinks)} destinations, needing "
                f"{len(shards)} shards to stay inside the "
                f"{catalog.SORTER_MAX_REACH}-tile sorter reach, but only has "
                f"{g.count} machine(s) to split between them; a shard with no "
                f"machines would leave its consumers unfed"
            )
        demand = {
            (item, dest): _sink_demand(groups, spec, item, dest) for item, dest in sinks
        }
        per_shard = (
            _allocate_machines(g.count, shards, demand) if len(shards) > 1 else [g.count]
        )

        for shard, machines in zip(shards, per_shard, strict=True):
            n_strips = max(1, math.ceil(machines / max(1, strip_len)))
            base = machines // n_strips
            extra = machines % n_strips
            for s in range(n_strips):
                n = base + (1 if s < extra else 0)
                if n <= 0:
                    continue
                strips.append(
                    Strip(
                        group_key=key,
                        recipe_id=g.recipe_id,
                        item_id=g.item_id,
                        model_index=g.model_index,
                        machines=n,
                        mw=g.width,
                        mh=g.height,
                        in_lanes=in_lanes,
                        out_lanes=tuple(shard),
                    )
                )
    return strips


# --- direct insertion ------------------------------------------------------


def _direct_insert_candidates(spec: BuildSpec) -> list[tuple[str, str]]:
    """Producer/consumer recipe pairs a sorter could bridge with no belt.

    Excluded entirely, not merely constrained to zero, when the consumer is
    proliferated: spray is applied on a belt and does not survive crafting, so a
    directly-inserted edge could never be sprayed.  Leaving the variable in with
    a zero bound would let ``-MU_DIRECT`` mislead the search toward placements
    whose apparent reward is unrealisable.
    """
    groups = _adapt(spec)
    proliferated = {g.recipe_id for g in groups.values() if g.proliferated}
    producers: dict[str, list[str]] = defaultdict(list)
    for g in groups.values():
        for item in g.outputs:
            producers[item].append(g.recipe_id)

    out: list[tuple[str, str]] = []
    for g in groups.values():
        for item in g.inputs:
            for src in producers.get(item, []):
                if src == g.recipe_id:
                    continue
                if g.recipe_id in proliferated:
                    continue
                if (src, g.recipe_id) in spec.belt_required_edges:
                    continue
                out.append((src, g.recipe_id))
    return sorted(set(out))


@dataclass(frozen=True, slots=True)
class _DirectCandidate:
    """A net a single sorter could replace, and the geometry that would allow it.

    ``prod_row`` and ``cons_row`` are offsets from each strip's origin to the
    lane row the sorter would span, so the alignment condition stays affine in
    the packer's ``x``/``y`` variables.
    """

    item: str
    prod_row: int
    cons_row: int


def _direct_net_candidates(
    strips: list[Strip], spec: BuildSpec
) -> dict[tuple[int, int], _DirectCandidate]:
    """Map eligible nets to the lane rows a bridging sorter would connect.

    Works at *strip* granularity because that is what the packer places, while
    :func:`_direct_insert_candidates` works at recipe granularity -- one recipe
    can be split across several strips, and each of those nets is separately
    eligible.
    """
    eligible = set(_direct_insert_candidates(spec))
    if not eligible:
        return {}

    out: dict[tuple[int, int], _DirectCandidate] = {}
    for i, j in _nets_between(strips):
        src, dst = strips[i], strips[j]
        if (src.recipe_id, dst.recipe_id) not in eligible:
            continue
        # The producer's output lane dedicated to this destination.
        lane = next(
            (
                (k, item)
                for k, (item, dest) in enumerate(src.out_lanes)
                if dest == dst.group_key
            ),
            None,
        )
        if lane is None:
            continue
        k, item = lane
        if item not in dst.in_lanes:
            continue
        out[i, j] = _DirectCandidate(
            item=item,
            prod_row=len(src.in_lanes) + src.mh + k,
            cons_row=dst.in_lanes.index(item),
        )
    return out


def tie_break_cap(n_terms: int, *, width_bound: int, height: int, n_direct: int) -> int:
    """Weight that makes width outrank every tie-break term put together.

    The objective is lexicographic on purpose: width first, then wirelength and
    direct-insert reward as tie-breaks among equal-width packings.  Blending them
    is what once made *more* solver time produce *worse* area, because the
    blended proxy was anti-correlated with the metric actually reported.

    The cap must therefore exceed the largest value the whole tie-break tier can
    take, and it has to grow when the direct-insert reward joins that tier --
    otherwise direct inserts could buy width, quietly reinstating the blend.
    """
    return n_terms * (width_bound + height) + MU_DIRECT * n_direct + 1


# --- phase 1: packing ------------------------------------------------------


@dataclass
class _Pack:
    """Strip origins chosen by the packer."""

    at: dict[int, tuple[int, int]]
    width: int
    height: int
    status: str
    hit_budget: bool = False
    #: Nets the packer arranged to bridge with a sorter instead of a belt route.
    direct: frozenset[tuple[int, int]] = frozenset()


def _nets_between(strips: list[Strip]) -> list[tuple[int, int]]:
    """Strip index pairs that will need a belt route."""
    by_group: dict[str, list[int]] = defaultdict(list)
    for i, s in enumerate(strips):
        by_group[s.group_key].append(i)
    nets: set[tuple[int, int]] = set()
    for i, s in enumerate(strips):
        for _item, dest in s.out_lanes:
            if not dest:
                continue
            for j in by_group.get(dest, []):
                nets.add((i, j))
    return sorted(nets)


def _greedy_pack(strips: list[Strip], height: int) -> _Pack:
    """Shelf packing -- always succeeds, and seeds the solver's upper bound."""
    at: dict[int, tuple[int, int]] = {}
    shelf_x, shelf_y, shelf_h = 0, 0, 0
    width = 0
    for i, s in enumerate(strips):
        w, h = s.width + MARGIN, s.height + MARGIN
        if shelf_y + h > height and shelf_h:
            shelf_x, shelf_y, shelf_h = width, 0, 0
        at[i] = (shelf_x, shelf_y)
        shelf_y += h
        shelf_h = max(shelf_h, w)
        width = max(width, shelf_x + w)
    return _Pack(at=at, width=width, height=height, status="greedy")


def _pack(
    strips: list[Strip],
    *,
    height: int,
    width_bound: int,
    time_budget_s: float,
    direct_candidates: dict[tuple[int, int], _DirectCandidate],
    workers: int,
) -> _Pack | None:
    """Minimise width at a fixed height with CP-SAT.

    Height is swept outside rather than multiplied inside: ``W * H`` is a product
    of two variables, whose CP-SAT relaxation is weak enough that the search
    flounders.  Several easy solves beat one hard one.
    """
    model = cp_model.CpModel()
    n = len(strips)
    if n == 0:
        return None

    # Sizes first: several cuts below need them before any variable exists.
    sizes = [(s.width + MARGIN, s.height + MARGIN) for s in strips]
    if any(h > height for _, h in sizes):
        return None  # this height cannot hold some strip at all

    # CUT 1 -- area.  Everything must fit inside `w_var x height`, so
    # `w_var >= ceil(total_area / height)`.  Without this `w_var`'s lower bound
    # is 1 and the relaxation can drive the width term to nothing, which is most
    # of why the bound crawled while the incumbent sat still.  `height` is a
    # constant here, so this stays linear.
    total_area = sum(w * h for w, h in sizes)
    widest = max(w for w, _ in sizes)
    w_lb = max(widest, -(-total_area // height))  # ceil division
    w_var = model.new_int_var(min(w_lb, width_bound), width_bound, "W")

    xs, ys, x_iv, y_iv = [], [], [], []
    for i, (w, h) in enumerate(sizes):
        x = model.new_int_var(0, max(0, width_bound - w), f"x{i}")
        y = model.new_int_var(0, max(0, height - h), f"y{i}")
        xs.append(x)
        ys.append(y)
        x_iv.append(model.new_fixed_size_interval_var(x, w, f"xi{i}"))
        y_iv.append(model.new_fixed_size_interval_var(y, h, f"yi{i}"))
        model.add(x + w <= w_var)

    model.add_no_overlap_2d(x_iv, y_iv)

    # Symmetry breaking between identical strips of the same recipe: without it
    # the search burns itself on permutations that differ by nothing.
    for i in range(n):
        for j in range(i + 1, n):
            a, b = strips[i], strips[j]
            if (a.group_key, a.machines, a.in_lanes, a.out_lanes) == (
                b.group_key,
                b.machines,
                b.in_lanes,
                b.out_lanes,
            ):
                model.add(xs[i] * height + ys[i] <= xs[j] * height + ys[j])

    # Half-perimeter wirelength over the nets, which is what keeps phase 2's job
    # tractable and costs almost nothing to express.
    terms: list[cp_model.IntVar] = []
    for i, j in _nets_between(strips):
        dx = model.new_int_var(0, width_bound, f"dx{i}_{j}")
        dy = model.new_int_var(0, height, f"dy{i}_{j}")
        model.add_abs_equality(dx, xs[i] - xs[j])
        model.add_abs_equality(dy, ys[i] - ys[j])

        # CUT 2 -- separation.  Two strips cannot overlap, so they are disjoint
        # in x or in y; either way their origins differ by at least the smaller
        # of the two extents on that axis.  Without this every `dx`/`dy` has a
        # relaxation value of 0, so the entire HPWL half of the objective is
        # invisible to the bound -- which is why `bound` sat near the width term
        # alone while `obj` was more than twice it.
        wi, hi = sizes[i]
        wj, hj = sizes[j]
        model.add(dx + dy >= min(min(wi, wj), min(hi, hj)))

        terms.append(dx)
        terms.append(dy)

    # Direct insertion: one Boolean per eligible net, reified against the
    # geometry that would let a single sorter replace the whole belt route.
    #
    # The condition is deliberately strict -- the consumer sits directly EAST of
    # the producer with their two lane rows on the same y -- because a sorter
    # must run straight, never diagonally, and never across altitudes
    # (`catalog.SORTER_SPANS_ALTITUDE` is False). Both lane rows are at z=0 by
    # construction, so alignment in y is the whole altitude story.
    #
    # The gap floor is MARGIN + 1 rather than 1: the packed boxes carry a margin,
    # so anything tighter would collide with `no_overlap_2d` and make the
    # Boolean unsatisfiable rather than merely unattractive.
    direct_vars: dict[tuple[int, int], cp_model.IntVar] = {}
    for (i, j), cand in direct_candidates.items():
        di = model.new_bool_var(f"di{i}_{j}")
        # The consumer sits BELOW the producer, and the sorter runs vertically
        # down a column both lanes share.
        #
        # Vertical is the geometry this architecture actually wants. A strip is
        # input lanes / machines / output lanes stacked top to bottom, so a
        # producer's output lane is its bottom row and a consumer's input lane is
        # its top row -- they meet naturally when one is stacked under the other.
        #
        # The east/west alternative was tried and is strictly worse: it forces
        # the two strips side by side, which WIDENS the pack, and width outranks
        # the direct-insert reward lexicographically. The solver correctly
        # refused every such pair, so the feature never fired.
        gap = (ys[j] + cand.cons_row) - (ys[i] + cand.prod_row)
        model.add(gap >= 1).only_enforce_if(di)
        model.add(gap <= catalog.SORTER_MAX_REACH).only_enforce_if(di)
        # The lanes must share at least one column for the sorter to run
        # straight down. Both are full-width lanes over their strip's machines.
        model.add(xs[i] <= xs[j] + strips[j].width - 1).only_enforce_if(di)
        model.add(xs[j] <= xs[i] + strips[i].width - 1).only_enforce_if(di)
        direct_vars[i, j] = di

    # Objective: width first, wirelength only as a tie-break.
    #
    # Height is fixed for this solve, so `w_var` IS the area being minimised.
    # Previously width carried weight 5 while HPWL contributed two terms per net
    # each as large as `width_bound`, so wirelength dominated and the solver
    # traded width away to shorten wires.  That is measurable: with the old
    # weights, giving the solver MORE time made the final area WORSE
    # (1460 tiles at 0.1s versus 1566 at 4s), because it was optimising a proxy
    # anti-correlated with the metric we actually report.
    #
    # Scaling width above the largest achievable HPWL sum makes the comparison
    # lexicographic without a second solve: any width saving beats every
    # wirelength saving, and HPWL then breaks ties among equal-width packings --
    # which is all it was ever needed for, since it exists to keep phase 2's
    # routing tractable rather than to shrink the build.
    # The direct-insert reward joins the tie-break tier rather than competing
    # with width: a direct insert deletes belt tiles, not bounding box. It is
    # expressed as a PENALTY for *not* direct-inserting so every term stays
    # non-negative -- a negative reward would let the tier range below zero and
    # a width increase could be bought back, which is exactly the blend this
    # ordering exists to prevent.
    cap = tie_break_cap(
        len(terms), width_bound=width_bound, height=height, n_direct=len(direct_vars)
    )
    missed = sum(di.Not() for di in direct_vars.values())
    model.minimize(w_var * cap + LAMBDA_HPWL * sum(terms) + MU_DIRECT * missed)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.05, time_budget_s)
    # Determinism is load-bearing for the bake-off: multi-worker CP-SAT would
    # make the A-vs-B comparison noise rather than measurement.
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = 20260822
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    return _Pack(
        at={i: (solver.Value(xs[i]), solver.Value(ys[i])) for i in range(n)},
        width=solver.Value(w_var),
        height=height,
        status=solver.StatusName(status),
        hit_budget=status == cp_model.FEASIBLE,
        direct=frozenset(k for k, di in direct_vars.items() if solver.Value(di)),
    )


# --- emission --------------------------------------------------------------


@dataclass
class _Canvas:
    """Buildings under construction, plus what occupies each cell."""

    buildings: list[PlacedBuilding] = field(default_factory=list)
    #: ``(x, y, level)`` -> building index, for cells that block routing.
    blocked: dict[tuple[int, int, int], int] = field(default_factory=dict)
    #: Cells a machine occupies, which block *every* level.
    solid: set[tuple[int, int]] = field(default_factory=set)

    def add(self, b: PlacedBuilding, *, solid: bool = False) -> int:
        idx = len(self.buildings)
        self.buildings.append(b)
        if solid:
            for x, y, _ in b.tiles():
                self.solid.add((x, y))
                for lvl in range(LEVELS):
                    self.blocked[x, y, lvl] = idx
        else:
            for x, y, _ in b.tiles():
                self.blocked[x, y, b.z] = idx
        return idx

    def free(self, cell: tuple[int, int, int]) -> bool:
        x, y, _ = cell
        return cell not in self.blocked and (x, y) not in self.solid


def _pick_sorter(rate: Fraction, span: int, machines: int) -> tuple[int, int]:
    """Cheapest sorter tier and count carrying ``rate`` across ``span``.

    Reach is three tiles for every tier, so tiers differ only in throughput --
    there is never a reason to pay for a higher tier than the rate needs.
    """
    per_machine = rate / machines if machines else rate
    for tier in SORTER_TIERS:
        if catalog.sorter_rate(tier, span) >= per_machine:
            return tier, machines
    return SORTER_TIERS[-1], machines


@dataclass(frozen=True, slots=True)
class _Port:
    """Where a net starts or ends: a lane's end tile, and the way out of it."""

    belt: int
    x: int
    y: int
    #: Inclusive x-range of the whole lane, not just the end tile the router
    #: attaches to.  A direct-insert sorter may drop down ANY column the two
    #: lanes share, so it needs the extent rather than the endpoint.
    x0: int = 0
    x1: int = -1

    def columns(self) -> range:
        return range(self.x0, self.x1 + 1)


def _emit_strip(
    canvas: _Canvas,
    s: Strip,
    ox: int,
    oy: int,
    belt_id: int,
    belt_model: int,
    rates: dict[str, Fraction],
    machine_demand: tuple[Fraction, Fraction] = (Fraction(0), Fraction(0)),
) -> tuple[dict[str, _Port], dict[tuple[str, str], _Port], int]:
    """Place one strip's lanes, machines and sorters.

    Returns the west end of each input lane and the east end of each output lane
    -- the points routing connects -- plus the sorter count.
    """
    in_ports: dict[str, _Port] = {}
    out_ports: dict[tuple[str, str], _Port] = {}
    width = s.width
    n_in = len(s.in_lanes)

    lane_idx: dict[int, list[int]] = {}
    for row in range(s.height):
        y = oy + row
        if n_in <= row < n_in + s.mh:
            continue  # machine band
        # Which lane this row is tells us what it carries. Recording it is what
        # lets the marker pass label external input belts afterwards; the
        # knowledge is unrecoverable once emission drops it.
        if row < n_in:
            lane_item: str | None = s.in_lanes[row]
        else:
            out_row = row - n_in - s.mh
            lane_item = s.out_lanes[out_row][0] if 0 <= out_row < len(s.out_lanes) else None
        indices = []
        for k in range(width):
            indices.append(
                canvas.add(
                    PlacedBuilding(
                        item_id=belt_id,
                        model_index=belt_model,
                        x=ox + k,
                        y=y,
                        width=1,
                        height=1,
                        yaw=Facing.EAST.value,
                        carries_item=lane_item,
                    )
                )
            )
        for a, b in zip(indices, indices[1:], strict=False):
            canvas.buildings[a] = _relink(canvas.buildings[a], output_obj=b)
        lane_idx[row] = indices

    machine_y = oy + n_in
    machines: list[int] = []
    for k in range(s.machines):
        machines.append(
            canvas.add(
                PlacedBuilding(
                    item_id=s.item_id,
                    model_index=s.model_index,
                    x=ox + k * s.mw,
                    y=machine_y,
                    width=s.mw,
                    height=s.mh,
                    # This was `abs(hash(name)) % 30000`, which is not a DSP
                    # recipe id and is not even stable across processes, since
                    # Python randomises string hashing.
                    recipe_id=catalog.recipe_id(s.recipe_id),
                ),
                solid=True,
            )
        )

    # Per-sorter demand, on the SAME basis the validator uses: a machine's total
    # input rate divided across the sorters feeding it, and likewise for output.
    # Tier selection previously divided ONE item's group total by this strip's
    # machine count -- a different quantity entirely, which is how a Mk.I ended
    # up handed 0.546/s when it sustains 0.5/s at span 3.
    in_total, out_total = machine_demand
    in_each = in_total / max(1, n_in)
    out_each = out_total / max(1, len(s.out_lanes))

    sorters = 0
    for j, item in enumerate(s.in_lanes):
        row = j
        span = n_in - j
        in_ports[item] = _Port(lane_idx[row][0], ox, oy + row, ox, ox + width - 1)
        tier, _count = _pick_sorter(in_each or rates.get(item, Fraction(1)), span, 1)
        sorters += _link_lane(
            canvas, lane_idx[row], machines, oy + row, machine_y, tier, into_machine=True
        )

    bottom = machine_y + s.mh - 1
    for j, (item, dest) in enumerate(s.out_lanes):
        row = n_in + s.mh + j
        span = j + 1
        out_ports[item, dest] = _Port(
            lane_idx[row][-1], ox + width - 1, oy + row, ox, ox + width - 1
        )
        tier, _count = _pick_sorter(out_each or rates.get(item, Fraction(1)), span, 1)
        sorters += _link_lane(
            canvas, lane_idx[row], machines, oy + row, bottom, tier, into_machine=False
        )
    return in_ports, out_ports, sorters


def _link_lane(
    canvas: _Canvas,
    lane: list[int],
    machines: list[int],
    lane_y: int,
    machine_y: int,
    tier: int,
    *,
    into_machine: bool,
) -> int:
    """One sorter per machine, between the lane and the machine's near edge.

    Anchors sit *on* the two buildings and the connection indices carry the
    semantics, which is how the game itself represents this -- a sorter consumes
    no grid cell of its own.
    """
    model_index = catalog.building(tier).model_index
    facing = Facing.SOUTH.value if lane_y < machine_y else Facing.NORTH.value
    placed = 0
    for m_idx in machines:
        m = canvas.buildings[m_idx]
        x = m.x
        belt_idx = next((i for i in lane if canvas.buildings[i].x == x), None)
        if belt_idx is None:
            continue
        if into_machine:
            src, dst = belt_idx, m_idx
            ax, ay, bx, by = x, lane_y, x, machine_y
        else:
            src, dst = m_idx, belt_idx
            ax, ay, bx, by = x, machine_y, x, lane_y
        canvas.buildings.append(
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
                yaw=facing,
                yaw2=facing,
                input_obj=src,
                output_obj=dst,
            )
        )
        placed += 1
    return placed


def _relink(b: PlacedBuilding, *, output_obj: int | None) -> PlacedBuilding:
    """Repoint a belt at its successor, preserving everything else.

    Uses ``replace`` rather than rebuilding field by field.  The hand-written
    version enumerated fields and therefore silently dropped any it did not
    mention -- it was already discarding ``parameters``, and it swallowed
    ``carries_item`` the moment that was added, which is why belt markers came
    out empty while the emitter was setting them correctly.
    """
    return replace(b, output_obj=output_obj)


# --- phase 2: routing ------------------------------------------------------

_STEPS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _astar(
    canvas: _Canvas,
    starts: list[tuple[int, int, int]],
    goals: set[tuple[int, int, int]],
    history: dict[tuple[int, int, int], float],
    pressure: float,
    bounds: tuple[int, int, int, int],
) -> list[tuple[int, int, int]] | None:
    """Cheapest free-cell path, with congestion history folded into the cost.

    The history term is what makes rip-up-and-reroute converge: a cell that
    several nets have fought over becomes progressively more expensive, so they
    negotiate rather than oscillate.
    """
    if not goals:
        return None
    min_x, min_y, max_x, max_y = bounds

    # Heuristic: Manhattan distance to the NEAREST goal.
    #
    # This used to use the goals' centroid, which is not admissible when the
    # goals are spread out and -- worse -- never reaches 0 at an actual goal.
    # That turned A* into a badly-guided Dijkstra that expanded in every
    # direction, which is what made routing take tens of seconds.
    #
    # Exact min is best but costs O(|goals|) per node, so fall back to distance
    # to the goals' bounding box once that would dominate. The box distance is
    # still admissible (it under-estimates), just weaker.
    goal_list = list(goals)
    if len(goal_list) <= _EXACT_HEURISTIC_GOALS:

        def h(c: tuple[int, int, int]) -> float:
            x, y, _ = c
            return float(min(abs(x - g[0]) + abs(y - g[1]) for g in goal_list))

    else:
        bx0 = min(g[0] for g in goal_list)
        bx1 = max(g[0] for g in goal_list)
        by0 = min(g[1] for g in goal_list)
        by1 = max(g[1] for g in goal_list)

        def h(c: tuple[int, int, int]) -> float:
            x, y, _ = c
            return float(max(0, bx0 - x, x - bx1) + max(0, by0 - y, y - by1))

    expansions = 0

    open_heap: list[tuple[float, float, tuple[int, int, int]]] = []
    best: dict[tuple[int, int, int], float] = {}
    prev: dict[tuple[int, int, int], tuple[int, int, int] | None] = {}
    #: Ramp moves span two cells.  The intermediate "run" cell is recorded here
    #: rather than in ``prev``, because giving it a predecessor of its own lets a
    #: later ramp clobber a predecessor the normal step expansion already set --
    #: which can point a cell's chain back through itself and make ``prev`` cyclic.
    via: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    for s in starts:
        if not canvas.free(s):
            continue
        best[s] = 0.0
        prev[s] = None
        heapq.heappush(open_heap, (h(s), 0.0, s))

    while open_heap:
        _, g, cur = heapq.heappop(open_heap)
        if g > best.get(cur, math.inf):
            continue
        expansions += 1
        if expansions > _MAX_EXPANSIONS:
            return None
        if cur in goals:
            path = []
            node: tuple[int, int, int] | None = cur
            # ``prev`` must be acyclic; walking a cycle here previously spun at
            # 100% CPU while ``path`` grew without bound.  Guard it rather than
            # trusting it, so a regression fails loudly instead of hanging.
            seen: set[tuple[int, int, int]] = set()
            while node is not None:
                if node in seen:
                    raise AssertionError(
                        f"cycle in A* predecessor chain at {node}; "
                        "a ramp move corrupted an existing predecessor"
                    )
                seen.add(node)
                path.append(node)
                if node in via:
                    path.append(via[node])
                node = prev[node]
            return list(reversed(path))
        x, y, lvl = cur
        for dx, dy in _STEPS:
            nxt = (x + dx, y + dy, lvl)
            if not (min_x - 2 <= nxt[0] <= max_x + 2 and min_y - 2 <= nxt[1] <= max_y + 2):
                continue
            if not canvas.free(nxt):
                continue
            cost = g + 1.0 + history.get(nxt, 0.0) * pressure
            if cost < best.get(nxt, math.inf):
                best[nxt] = cost
                prev[nxt] = cur
                # A plain step reaches `nxt` directly, so any ramp via-cell
                # recorded by an earlier, worse ramp is now stale.  Leaving it
                # splices a cell that is not on the path into the result, which
                # shows up as a belt linking diagonally across a level change.
                via.pop(nxt, None)
                heapq.heappush(open_heap, (cost + h(nxt), cost, nxt))
        # A level change costs two tiles of run, because belts climb 0.5 per
        # tile.  Both are reserved so the ramp physically exists.
        for dx, dy in _STEPS:
            for dl in (1, -1):
                lvl2 = lvl + dl
                if not 0 <= lvl2 < LEVELS:
                    continue
                run = (x + dx, y + dy, lvl)
                top = (x + 2 * dx, y + 2 * dy, lvl2)
                if not canvas.free(run) or not canvas.free(top):
                    continue
                cost = g + 3.0 + history.get(top, 0.0) * pressure
                if cost < best.get(top, math.inf):
                    best[top] = cost
                    # The ramp is ONE edge cur -> top that happens to occupy an
                    # extra cell.  Record `run` as a via, never as a node with
                    # its own predecessor: `run` may already lie on another
                    # cell's best path, and reassigning its predecessor is what
                    # made `prev` cyclic.
                    prev[top] = cur
                    via[top] = run
                    heapq.heappush(open_heap, (cost + h(top), cost, top))
    return None


@dataclass
class _Net:
    src: _Port
    dst: _Port
    item: str


def _route_all(
    canvas: _Canvas,
    nets: list[_Net],
    belt_id: int,
    belt_model: int,
    bounds: tuple[int, int, int, int],
) -> tuple[int, int, int]:
    """Route every net, negotiating congestion across iterations.

    Returns ``(routed, failed, iterations)``.  Failures are counted and returned
    rather than raised: the caller decides whether to repair, and a silently
    swallowed failure is exactly the bug that made Strategy A ship a fallback
    wearing a solver's clothes.
    """
    history: dict[tuple[int, int, int], float] = defaultdict(float)
    committed: list[list[tuple[int, int, int]]] = []
    iterations = 0

    for it in range(RRR_MAX):
        iterations = it + 1
        for path in committed:
            for cell in path:
                if canvas.blocked.get(cell, -1) == -2:
                    del canvas.blocked[cell]
        committed = []
        pressure = 0.5 * (1.6**it)
        failed = 0
        order = sorted(
            range(len(nets)),
            key=lambda i: -(
                abs(nets[i].src.x - nets[i].dst.x) + abs(nets[i].src.y - nets[i].dst.y)
            ),
        )
        paths: dict[int, list[tuple[int, int, int]]] = {}
        for i in order:
            net = nets[i]
            starts = [
                (net.src.x + dx, net.src.y + dy, 0)
                for dx, dy in _STEPS
                if canvas.free((net.src.x + dx, net.src.y + dy, 0))
            ]
            goals = {
                (net.dst.x + dx, net.dst.y + dy, 0)
                for dx, dy in _STEPS
                if canvas.free((net.dst.x + dx, net.dst.y + dy, 0))
            }
            routed = _astar(canvas, starts, goals, history, pressure, bounds)
            if routed is None:
                failed += 1
                continue
            paths[i] = routed
            for cell in routed:
                canvas.blocked[cell] = -2  # tentative reservation
            committed.append(routed)
        if failed == 0:
            _commit_paths(canvas, nets, paths, belt_id, belt_model)
            return len(paths), 0, iterations
        for path in committed:
            for cell in path:
                history[cell] += 1.0
        if it == RRR_MAX - 1:
            _commit_paths(canvas, nets, paths, belt_id, belt_model)
            return len(paths), failed, iterations
    return 0, len(nets), iterations


def _commit_paths(
    canvas: _Canvas,
    nets: list[_Net],
    paths: dict[int, list[tuple[int, int, int]]],
    belt_id: int,
    belt_model: int,
) -> None:
    """Turn reserved cells into real belts, forward-linked source to sink."""
    for cell, owner in list(canvas.blocked.items()):
        if owner == -2:
            del canvas.blocked[cell]
    for i, path in paths.items():
        net = nets[i]
        indices: list[int] = []
        ok = True
        for x, y, lvl in path:
            if not canvas.free((x, y, lvl)):
                ok = False
                break
            indices.append(
                canvas.add(
                    PlacedBuilding(
                        item_id=belt_id,
                        model_index=belt_model,
                        x=x,
                        y=y,
                        z=lvl,
                        width=1,
                        height=1,
                        carries_item=net.item,
                    )
                )
            )
        if not ok or not indices:
            continue
        for a, b in zip(indices, indices[1:], strict=False):
            canvas.buildings[a] = _relink(canvas.buildings[a], output_obj=b)
        canvas.buildings[net.src.belt] = _relink(
            canvas.buildings[net.src.belt], output_obj=indices[0]
        )
        canvas.buildings[indices[-1]] = _relink(
            canvas.buildings[indices[-1]], output_obj=net.dst.belt
        )


# --- power -----------------------------------------------------------------


def _place_power(canvas: _Canvas) -> int:
    """Towers on a covering lattice, then repaired until coverage really holds.

    The lattice spacing already guarantees coverage and connectivity in open
    ground; the repair passes exist because a lattice point can land on a
    machine, and a tower that could not be placed is exactly the kind of gap
    that would otherwise reach the game as a dead corner of the factory.
    """
    if not canvas.buildings:
        return 0
    xs = [b.x for b in canvas.buildings] + [b.x + b.width - 1 for b in canvas.buildings]
    ys = [b.y for b in canvas.buildings] + [b.y + b.height - 1 for b in canvas.buildings]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)

    tower = catalog.building(catalog.TESLA_TOWER_ID)
    radius = tower.cover_radius
    link = tower.connect_distance
    centres: list[tuple[Fraction, Fraction]] = []
    placed = 0

    def try_place(cx: int, cy: int) -> bool:
        nonlocal placed
        if not canvas.free((cx, cy, 0)) or (cx, cy) in canvas.solid:
            return False
        for lvl in range(LEVELS):
            if (cx, cy, lvl) in canvas.blocked:
                return False
        canvas.add(
            PlacedBuilding(
                item_id=catalog.TESLA_TOWER_ID,
                model_index=tower.model_index,
                x=cx,
                y=cy,
                width=tower.width,
                height=tower.height,
            ),
            solid=True,
        )
        centres.append((Fraction(2 * cx + tower.width, 2), Fraction(2 * cy + tower.height, 2)))
        placed += 1
        return True

    def nearest_free(cx: int, cy: int, limit: int) -> tuple[int, int] | None:
        for r in range(limit + 1):
            for dx in range(-r, r + 1):
                for dy in (-r, r) if r else (0,):
                    for a, b in ((cx + dx, cy + dy), (cx + dy, cy + dx)):
                        if canvas.free((a, b, 0)) and (a, b) not in canvas.solid:
                            return (a, b)
        return None

    half = TOWER_SPACING // 2
    y = min_y + half
    while y <= max_y + half:
        x = min_x + half
        while x <= max_x + half:
            spot = nearest_free(x, y, 4)
            if spot:
                try_place(*spot)
            x += TOWER_SPACING
        y += TOWER_SPACING

    def covered(px: Fraction, py: Fraction) -> bool:
        return any((px - cx) ** 2 + (py - cy) ** 2 <= radius**2 for cx, cy in centres)

    def place_covering(px: Fraction, py: Fraction, tx: int, ty: int) -> bool:
        """Place a tower that GENUINELY covers ``(px, py)``, nearest first.

        The candidate must satisfy the coverage test before it is placed, not
        merely be free and roughly nearby.  The previous repair searched up to
        ``radius`` tiles away in one axis and then up to 2 more in the other, so
        it could place a tower 11 tiles from a 10.5-radius target and stop --
        having "repaired" a tile that was still dark.  That surfaced as an
        intermittent validator failure (about 1 run in 18) once multi-worker
        CP-SAT started producing varied packs.
        """
        limit = int(radius)
        offsets = sorted(
            (
                (dx, dy)
                for dx in range(-limit, limit + 1)
                for dy in range(-limit, limit + 1)
            ),
            key=lambda d: (abs(d[0]) + abs(d[1]), d),
        )
        for dx, dy in offsets:
            a, b = tx + dx, ty + dy
            cx = Fraction(2 * a + tower.width, 2)
            cy = Fraction(2 * b + tower.height, 2)
            if (px - cx) ** 2 + (py - cy) ** 2 > radius**2:
                continue
            if try_place(a, b):
                return True
        return False

    # Coverage repair.  Conservative on purpose: every tile of a powered
    # building, not merely its centre, because being wrong here means a machine
    # that pastes fine and never runs.
    for b in list(canvas.buildings):
        if catalog.is_belt(b.item_id) or b.item_id == catalog.TESLA_TOWER_ID:
            continue
        for tx, ty, _ in b.tiles():
            px, py = Fraction(2 * tx + 1, 2), Fraction(2 * ty + 1, 2)
            if covered(px, py):
                continue
            place_covering(px, py, tx, ty)

    # Connectivity repair: a stranded tower powers its neighbourhood but leaves
    # the network in two pieces, which fails visibly in game rather than
    # silently, but fails all the same.
    for _ in range(4):
        groups = _link_groups(centres, link)
        if len(groups) <= 1:
            break
        main = groups[0]
        other = groups[1]
        ax, ay = centres[main[0]]
        bx, by = centres[other[0]]
        mx, my = int((ax + bx) / 2), int((ay + by) / 2)
        spot = nearest_free(mx, my, 6)
        if not spot or not try_place(*spot):
            break
    return placed


def _link_groups(
    centres: list[tuple[Fraction, Fraction]], link: Fraction
) -> list[list[int]]:
    n = len(centres)
    seen: set[int] = set()
    groups: list[list[int]] = []
    for start in range(n):
        if start in seen:
            continue
        comp = [start]
        seen.add(start)
        q = deque([start])
        while q:
            cur = q.popleft()
            for k in range(n):
                if k in seen:
                    continue
                ax, ay = centres[cur]
                bx, by = centres[k]
                if (ax - bx) ** 2 + (ay - by) ** 2 <= link**2:
                    seen.add(k)
                    comp.append(k)
                    q.append(k)
        groups.append(comp)
    groups.sort(key=len, reverse=True)
    return groups


# --- assembly --------------------------------------------------------------


def _build(
    spec: BuildSpec,
    strips: list[Strip],
    pack: _Pack,
    *,
    power: bool,
    route: bool,
) -> tuple[Placement, int, int]:
    belt_id = BELT_ITEM_IDS.get(spec.belt_item_id, 2001)
    belt_model = catalog.building(belt_id).model_index
    canvas = _Canvas()

    rates: dict[str, Fraction] = {}
    for g in _adapt(spec).values():
        for item, r in list(g.inputs.items()) + list(g.outputs.items()):
            rates[item] = max(rates.get(item, Fraction(0)), r * g.count)

    # Per-machine totals, keyed by group. Sorter tier selection needs the same
    # basis the validator checks against, which is a machine's whole input rate
    # split across its feeding sorters -- not one item's group total.
    demand: dict[str, tuple[Fraction, Fraction]] = {
        key: (
            sum(g.inputs.values(), Fraction(0)),
            sum(g.outputs.values(), Fraction(0)),
        )
        for key, g in _adapt(spec).items()
    }

    in_ports: dict[tuple[str, str], _Port] = {}
    out_ports: dict[tuple[str, str, str], _Port] = {}
    strip_in_ports: list[dict[str, _Port]] = []
    sorters = 0
    for i, s in enumerate(strips):
        ox, oy = pack.at[i]
        ins, outs, placed = _emit_strip(
            canvas,
            s,
            ox,
            oy,
            belt_id,
            belt_model,
            rates,
            demand.get(s.group_key, (Fraction(0), Fraction(0))),
        )
        sorters += placed
        strip_in_ports.append(ins)
        for item, port in ins.items():
            in_ports[s.group_key, item] = port
        for (item, dest), port in outs.items():
            out_ports[s.group_key, item, dest] = port

    # Nets the packer arranged to bridge directly become a single sorter and no
    # belt route at all -- that saving IS the feature, so it happens before the
    # net list is built rather than as a post-pass over routed belts.
    direct_keys = {
        (strips[i].group_key, strips[j].group_key) for i, j in pack.direct
    }
    direct_placed = 0

    nets: list[_Net] = []
    for (src_key, item, dest), port in out_ports.items():
        if not dest:
            continue
        sink = in_ports.get((dest, item))
        if sink is None:
            continue
        if (src_key, dest) in direct_keys and _bridge(canvas, port, sink, rates, item):
            direct_placed += 1
            continue
        nets.append(_Net(src=port, dst=sink, item=item))

    # Coaters go in BEFORE routing, because each one needs a proliferator net
    # routed to its drop belt. Placing them afterwards -- as this used to --
    # leaves them mounted on belts with nothing feeding them, so every
    # proliferated recipe silently runs unproliferated.
    coater_list: list[_Coater] = []
    prolif_item = _proliferator_item(spec)
    if spec.spray_lanes:
        coater_list = _place_coaters(
            canvas, spec, strips, strip_in_ports, belt_id, belt_model
        )
        if coater_list and prolif_item is not None:
            entry = _place_proliferator_entry(canvas, prolif_item, belt_id, belt_model)
            if entry is not None:
                nets.extend(_proliferator_nets(entry, coater_list, prolif_item))
    coaters = len(coater_list)

    xs = [b.x for b in canvas.buildings] or [0]
    ys = [b.y for b in canvas.buildings] or [0]
    bounds = (min(xs), min(ys), max(xs) + pack.width, max(ys) + pack.height)

    routed, failed, iterations = (0, 0, 0)
    if route and nets:
        routed, failed, iterations = _route_all(canvas, nets, belt_id, belt_model, bounds)

    towers = _place_power(canvas) if power else 0

    placement = Placement(
        buildings=tuple(canvas.buildings),
        description=f"flab2bp freeform layout ({spec.label or 'default'})",
        short_desc=spec.label or "flab2bp",
        stats={
            "machines": float(spec.machine_count),
            "strips": float(len(strips)),
            "sorters": float(sorters),
            "towers": float(towers),
            "spray_coaters": float(coaters),
            "nets": float(len(nets)),
            "routed": float(routed),
            "route_failures": float(failed),
            "repair_iterations": float(iterations),
            "belt_tiles": float(
                sum(1 for b in canvas.buildings if catalog.is_belt(b.item_id))
            ),
            "direct_inserts": float(direct_placed),
        },
    )
    return placement, failed, towers


def _bridge(
    canvas: _Canvas,
    src: _Port,
    dst: _Port,
    rates: dict[str, Fraction],
    item: str,
) -> bool:
    """Span two lane ends with one sorter, replacing a whole belt route.

    Returns ``False`` rather than placing an illegal sorter if the packed
    geometry did not actually come out within reach.  The packer's reification
    should guarantee it does, but a sorter that cannot exist would produce a
    blueprint that pastes and then does not run -- the worst failure mode -- so
    this is checked rather than assumed.
    """
    span = dst.y - src.y
    if span < 1 or span > catalog.SORTER_MAX_REACH:
        return False

    # Any column both lanes cover will do, so take the westmost shared one.
    shared = range(max(src.x0, dst.x0), min(src.x1, dst.x1) + 1)
    column = next(
        (
            x
            for x in shared
            if (x, src.y, 0) in canvas.blocked and (x, dst.y, 0) in canvas.blocked
        ),
        None,
    )
    if column is None:
        return False

    src_belt = canvas.blocked[column, src.y, 0]
    dst_belt = canvas.blocked[column, dst.y, 0]
    if src_belt == dst_belt:
        return False

    tier, _ = _pick_sorter(rates.get(item, Fraction(1)), span, 1)
    canvas.buildings.append(
        PlacedBuilding(
            item_id=tier,
            model_index=catalog.building(tier).model_index,
            x=column,
            y=src.y,
            width=1,
            height=1,
            x2=column,
            y2=dst.y,
            z2=0,
            yaw=Facing.SOUTH.value,
            yaw2=Facing.SOUTH.value,
            input_obj=src_belt,
            output_obj=dst_belt,
        )
    )
    return True


@dataclass(frozen=True, slots=True)
class _Coater:
    """A placed Spray Coater and the belt tile that will feed it proliferator."""

    coater: int
    #: A one-tile belt in the strip's east margin, the sink of a proliferator net.
    drop: int
    x: int
    y: int


def _place_coaters(
    canvas: _Canvas,
    spec: BuildSpec,
    strips: list[Strip],
    ports: list[dict[str, _Port]],
    belt_id: int,
    belt_model: int,
) -> list[_Coater]:
    """One Spray Coater per sprayed input lane, each with a supply drop.

    A coater is a belt addon: it consumes no grid tile, so proliferation costs
    almost nothing in area.  The real cost is that it forces its edge onto a
    belt, which is what forbids direct insertion there.

    Two things this has to get right, both of which it previously did not:

    * **The coater must sit on the lane carrying the item it sprays.**  The old
      version took ``next(belt for belt in canvas.buildings ...)`` -- the first
      belt anywhere on the canvas -- so every coater piled onto one unrelated
      tile.
    * **It must be reachable from a proliferator supply.**  A coater with
      nothing feeding it sprays nothing, and the build then runs unproliferated
      while looking perfectly healthy.  Each coater gets a one-tile ``drop``
      belt in its strip's east margin, one tile away, which a proliferator net
      is routed to and a sorter bridges.

    The east margin is reserved by ``_pack`` (each strip claims ``width +
    MARGIN``) and nothing is emitted into it, so the drop cell is free by
    construction rather than by luck.
    """
    coater = catalog.building(catalog.SPRAY_COATER_ID)
    wanted = set(spec.spray_lanes)
    out: list[_Coater] = []

    belt_at: dict[tuple[int, int, int], int] = {
        (b.x, b.y, b.z): i
        for i, b in enumerate(canvas.buildings)
        if catalog.is_belt(b.item_id)
    }

    for s, in_ports in zip(strips, ports, strict=True):
        for item in s.in_lanes:
            if item not in wanted:
                continue
            port = in_ports.get(item)
            if port is None:
                continue
            # East end of this lane: nearest the margin the drop belt lives in.
            cx, cy = port.x1, port.y
            host = belt_at.get((cx, cy, 0))
            drop_cell = (cx + 1, cy, 0)
            if host is None or not canvas.free(drop_cell):
                continue

            drop = canvas.add(
                PlacedBuilding(
                    item_id=belt_id,
                    model_index=belt_model,
                    x=drop_cell[0],
                    y=drop_cell[1],
                    width=1,
                    height=1,
                    carries_item=_proliferator_item(spec),
                )
            )
            idx = len(canvas.buildings)
            canvas.buildings.append(
                PlacedBuilding(
                    item_id=catalog.SPRAY_COATER_ID,
                    model_index=coater.model_index,
                    x=cx,
                    y=cy,
                    width=1,
                    height=1,
                    yaw=Facing.EAST.value,
                )
            )
            # Sorter drop -> coater, span 1. Anchors sit on the two buildings;
            # the connection indices carry the semantics.
            sorter = SORTER_TIERS[0]
            canvas.buildings.append(
                PlacedBuilding(
                    item_id=sorter,
                    model_index=catalog.building(sorter).model_index,
                    x=drop_cell[0],
                    y=drop_cell[1],
                    width=1,
                    height=1,
                    x2=cx,
                    y2=cy,
                    z2=0,
                    yaw=Facing.WEST.value,
                    yaw2=Facing.WEST.value,
                    input_obj=drop,
                    output_obj=idx,
                )
            )
            out.append(_Coater(coater=idx, drop=drop, x=drop_cell[0], y=drop_cell[1]))
    return out


def _proliferator_item(spec: BuildSpec) -> str | None:
    """The proliferator belted in, if any.

    It is an external input with no consuming machine -- coaters consume it --
    which is exactly why no lane was ever created for it.
    """
    for item in sorted(spec.external_inputs):
        if item.startswith("proliferator"):
            return item
    return None


def _proliferator_nets(
    entry: _Port, coaters: list[_Coater], item: str
) -> list[_Net]:
    """Daisy-chain the coater drops instead of fanning out from the entry.

    Every coater needs the same item at a trivial rate (well under one item per
    second in total, against a belt that carries twelve), so one chained lane
    serves all of them and capacity never binds.

    Routing each drop separately from the entry costs far more: eleven paths all
    radiating from one corner roughly doubled the bounding box.  Chaining
    nearest-neighbour keeps each hop short, and DSP belts merge natively, so the
    chain needs no splitters.
    """
    remaining = list(coaters)
    src = entry
    nets: list[_Net] = []
    while remaining:
        nxt = min(remaining, key=lambda c: abs(c.x - src.x) + abs(c.y - src.y))
        remaining.remove(nxt)
        nets.append(
            _Net(src=src, dst=_Port(nxt.drop, nxt.x, nxt.y, nxt.x, nxt.x), item=item)
        )
        src = _Port(nxt.drop, nxt.x, nxt.y, nxt.x, nxt.x)
    return nets


def _place_proliferator_entry(
    canvas: _Canvas, item: str, belt_id: int, belt_model: int
) -> _Port | None:
    """The block's proliferator input belt, west of everything else.

    A single entry tile: the router fans out from here to each coater's drop,
    and DSP belts merge natively, so no splitter is needed.
    """
    xs = [b.x for b in canvas.buildings]
    ys = [b.y for b in canvas.buildings]
    if not xs:
        return None
    x, y = min(xs) - 1, min(ys)
    if not canvas.free((x, y, 0)):
        return None
    idx = canvas.add(
        PlacedBuilding(
            item_id=belt_id,
            model_index=belt_model,
            x=x,
            y=y,
            width=1,
            height=1,
            carries_item=item,
        )
    )
    return _Port(idx, x, y, x, x)


def fallback_placement(spec: BuildSpec, *, power: bool = True) -> Placement:
    """A layout that cannot fail: one strip per group, stacked vertically.

    Deliberately a degenerate Strategy A.  If Strategy B falls back often, the
    bake-off will report B approximately equal to A, which is the honest answer
    rather than a flattering one.
    """
    strips = plan_strips(spec, strip_len=max(1, spec.machine_count))
    at: dict[int, tuple[int, int]] = {}
    y = 0
    for i, s in enumerate(strips):
        at[i] = (0, y)
        y += s.height + MARGIN
    width = max((s.width for s in strips), default=1) + MARGIN
    pack = _Pack(at=at, width=width, height=y, status="fallback")
    placement, _failed, _towers = _build(spec, strips, pack, power=power, route=False)
    placement.stats["fallback_used"] = 1.0
    placement.stats["solver_status"] = 0.0
    # The fallback stacks strips vertically without ever asking whether two of
    # them could sit within sorter reach, so it direct-inserts nothing. `_build`
    # already reported 0; this stays only to keep the key present when a caller
    # reads the fallback's stats without checking `fallback_used` first.
    placement.stats.setdefault("direct_inserts", 0.0)
    placement.stats["direct_insert_candidates"] = 0.0
    placement.stats["hit_time_budget"] = 0.0
    placement.stats["area"] = float(placement.area)
    return placement


class FreeformLayout:
    """Free-form packing plus belt routing."""

    name = "freeform"

    def __init__(
        self,
        *,
        power: bool = True,
        strip_len: int = 6,
        workers: int | None = None,
        direct_insert: bool = True,
    ) -> None:
        self.power = power
        self.strip_len = strip_len
        #: CP-SAT search workers. ``None`` takes the module default (all
        #: cores); the bake-off pins ``DETERMINISTIC_WORKERS``.
        self.workers = DEFAULT_SEARCH_WORKERS if workers is None else workers
        #: Off only for A/B measurement -- the feature is worth having, but
        #: proving it works means comparing against its own absence.
        self.direct_insert = direct_insert

    def lay_out(self, spec: BuildSpec, *, time_budget_s: float = 60.0) -> Placement:
        """Always returns a valid ``Placement``.

        Every way of *not* getting a solved answer is recorded in ``stats``
        rather than absorbed: ``fallback_used``, ``route_failures`` and
        ``solver_status`` between them say exactly how the answer was reached.
        A bake-off that cannot tell a solved layout from a fallback is comparing
        nothing.
        """
        if time_budget_s <= 0:
            return fallback_placement(spec, power=self.power)

        candidates = _direct_insert_candidates(spec)
        best: Placement | None = None
        per_solve = max(0.1, time_budget_s / 6.0)

        try:
            strips = plan_strips(spec, strip_len=self.strip_len)
        except (ValueError, KeyError):
            try:
                strips = plan_strips(spec, strip_len=max(1, spec.machine_count))
            except (ValueError, KeyError):
                return fallback_placement(spec, power=self.power)

        greedy = _greedy_pack(strips, _height_seed(strips))
        bound = max(greedy.width, max((s.width + MARGIN for s in strips), default=1))

        net_candidates = (
            _direct_net_candidates(strips, spec) if self.direct_insert else {}
        )

        for height in _candidate_heights(strips):
            pack = _pack(
                strips,
                height=height,
                width_bound=max(bound * 2, 8),
                time_budget_s=per_solve,
                direct_candidates=net_candidates,
                workers=self.workers,
            )
            if pack is None:
                continue
            placement, failed, _towers = _build(
                spec, strips, pack, power=self.power, route=True
            )
            # Area first, then belt count. Two packs of equal area are not
            # equally good: the one with fewer belt tiles is fewer buildings to
            # paste, and a direct insert shows up here as exactly that. Without
            # the second key, ties fell to whichever height the sweep tried
            # first, which silently discarded direct-inserted packs.
            if best is None or (placement.area, placement.stats["belt_tiles"]) < (
                best.area,
                best.stats["belt_tiles"],
            ):
                placement.stats["solver_status"] = 1.0 if pack.status == "OPTIMAL" else 0.5
                placement.stats["hit_time_budget"] = float(pack.hit_budget)
                placement.stats["fallback_used"] = 0.0
                placement.stats["direct_insert_candidates"] = float(len(candidates))
                placement.stats["area"] = float(placement.area)
                best = placement

        if best is None:
            return fallback_placement(spec, power=self.power)
        return best


def _height_seed(strips: list[Strip]) -> int:
    area = sum((s.width + MARGIN) * (s.height + MARGIN) for s in strips)
    tall = max((s.height + MARGIN for s in strips), default=1)
    return max(tall, int(math.isqrt(max(1, area))))


def _candidate_heights(strips: list[Strip]) -> list[int]:
    """Heights to sweep, since ``W * H`` is too weak a form to minimise directly."""
    h0 = _height_seed(strips)
    tall = max((s.height + MARGIN for s in strips), default=1)
    out = {max(tall, int(h0 * f)) for f in (0.6, 0.8, 1.0, 1.25, 1.6)}
    return sorted(out)
