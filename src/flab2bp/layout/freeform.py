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
import time
from collections import defaultdict, deque
from collections.abc import Collection, Mapping, Sequence
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

#: Rip-up rounds with no improvement in the failure count before giving up.
#:
#: Three, not one: pressure grows geometrically (``0.5 * 1.6**it``), so a round
#: that buys nothing at low pressure can still break a deadlock two rounds
#: later. Measured on the magnetic-ring chain, where routing a pack that cannot
#: be wired was the strategy's single largest cost.
_RRR_STALE_ROUNDS = 3

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

#: Total A* expansions across ALL nets and ALL rip-up rounds of one routing
#: pass.  `_MAX_EXPANSIONS` bounds a single search; this bounds their product,
#: which is what actually runs away at scale.
_ROUTING_BUDGET = 2_000_000

#: Rings of ground reserved around the packed block, decided BEFORE anything
#: routes.
#:
#: The block's boundary used to MOVE during emission while several passes each
#: assumed it was fixed: the external input runs computed the edge, ran out to
#: it and thereby moved it; the router was then free to lay belts two tiles
#: beyond that, wrapping the runs that had just defined it; the proliferator
#: entry was placed one tile west of whatever the edge happened to be at that
#: moment.  Every entry lane the validator reported as walled in was a tile that
#: had been on the boundary when it was placed and interior by the time the
#: placement was finished.
#:
#: Fixing the extent up front removes the whole class.  ``_ENTRY_RING`` is the
#: outermost ring anything may occupy, and only external entry belts -- the
#: input runs and the proliferator entry -- are ever placed there.  Everything
#: else, the router and the power lattice included, is confined to
#: ``_ROUTE_RING`` by :attr:`_Canvas.limit`.  The ring one beyond
#: ``_ENTRY_RING`` is therefore empty by construction, which is exactly the
#: precondition ``flow.external_entry_reachable`` flood-fills for: a belt
#: sitting on the outermost occupied ring always has open ground on its outward
#: side.
#:
#: Two rings for the router rather than one: that is what it had before on the
#: west and north faces, so the fix costs it no freedom there.
_ROUTE_RING = 2
_ENTRY_RING = _ROUTE_RING + 1

#: Unrouted nets below which a failed height is worth rebuilding without the
#: power lattice's claimed cells.  A handful of failures can be one tower
#: standing in one corridor; thirty cannot.
_POWER_RETRY_NETS = 3

#: Consumer lanes one producer lane END can hand items to.
#:
#: ``_tap_source`` builds a splitter on that tile and a splitter has
#: :data:`junction.MAX_PORTS` sides: the lane feeding it, the belt carrying the
#: lane onward past it, and one stub per branch.  Three branches fill it, and
#: the fourth is reported as a failure rather than mis-linked -- so a pairing
#: that asks for a fourth has already lost a net.
_MAX_LANE_TAPS = junction.MAX_PORTS - 1

#: Tower lattice spacing.  A square lattice of spacing ``d`` leaves a worst-case
#: distance of ``d/sqrt(2)`` to the nearest lattice point, so ``d`` must satisfy
#: ``d <= R*sqrt(2)``.
#:
#: Nine, not the twelve the bare covering argument allows.  A lattice point
#: routinely lands on a machine, and ``nearest_free`` then places the tower up
#: to FOUR tiles away -- at which point the guarantee is 8.49 + 4 = 12.49
#: against a 10.5 radius, and no longer a guarantee at all.  That is what the
#: coverage repair pass is for, and on a dense block it has nothing to work
#: with: measured on ``information-matrix``, a matrix lab with 349 tiles inside
#: tower range had FOUR of them free.  At nine the worst case is 6.36 + 4 =
#: 10.36, so the lattice still covers even when every point has to be displaced
#: as far as displacement goes, and 9 is still comfortably inside the 22.5 link
#: distance.  Towers are placed after routing, so the extra ones cost buildings
#: and nothing else.
TOWER_SPACING = 9


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
    #: Parameter block for a machine selected by MODE rather than recipe id.
    #: Empty for an ordinary craft.
    mode_params: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class Strip:
    """A run of machines of one recipe, with its lanes attached.

    The lanes are part of the unit, not something routing adds later.  That is
    what makes a strip individually routable and keeps phase 1 from producing a
    machine nothing can feed.

    Vertical layout, top to bottom::

        in_above      (len(in_above) rows, one belt lane each)
        machines      (mh rows)
        out_lanes     (len(out_lanes) rows)
        in_below      (len(in_below) rows)

    Inputs are fed from BOTH sides.  A sorter spans ``SORTER_MAX_REACH`` tiles,
    so the limit is three lanes per *side*, not three per strip -- lanes above
    and below are reached by different sorters.  Stacking every input above
    made a four-ingredient recipe unbuildable, and four ingredients is ordinary:
    ``orbital-collector`` takes accumulator-full, interstellar-logistics-station,
    reinforced-thruster and super-magnetic-ring.

    Outputs sit immediately below the machines and the overflow inputs below
    them, so when ``in_below`` is empty every row index is exactly what it was
    when inputs were above-only.  That is what keeps the change additive.

    An input LANE carries one or more items.  One item per lane is our
    simplification, not a DSP rule -- belts carry mixed items natively and a
    filtered sorter picks off the one it wants, which is how bus designs work
    (236 of 1,288 sorters in the fixture corpus carry a filter, and
    ``falk-v7-mall-full`` filters all 196 of its own).  Mixing is used ONLY as
    overflow, when one item per lane would not fit, because
    ``layout/validate.py`` decomposes its throughput check into independent
    single-commodity flows exactly BECAUSE a lane normally carries one item.
    """

    group_key: str
    recipe_id: str
    item_id: int
    model_index: int
    machines: int
    mw: int
    mh: int
    #: Lanes arriving on the north side, ordered top-down.  Each lane holds one
    #: or more items; more than one means a shared lane whose sorters filter.
    in_above: tuple[tuple[str, ...], ...]
    #: ``(item, destination group key)`` per lane, ordered top-down, starting
    #: directly under the machine band.  A separate lane per destination is what
    #: removes the need for splitters.
    #:
    #: The destination field may name SEVERAL groups, joined by
    #: :data:`DEST_SEP`.  That is the escape hatch for a producer with fewer
    #: machines than the sorter reach needs shards -- see :func:`_merge_lanes`.
    #: Use :func:`_dests` to read it; comparing it to a group key directly is
    #: how the two representations drift apart.
    out_lanes: tuple[tuple[str, str], ...]
    #: Lanes arriving on the south side, below ``out_lanes``.  Non-empty only
    #: when a recipe has more ingredients than one side can reach.
    in_below: tuple[tuple[str, ...], ...] = ()
    #: Parameter block for a machine configured by a MODE rather than a recipe
    #: (Energy Exchanger, Ray Receiver).  Empty for an ordinary craft.
    mode_params: tuple[int, ...] = ()

    @property
    def in_lanes(self) -> tuple[str, ...]:
        """Every ingredient, regardless of which side or lane feeds it."""
        return tuple(item for lane in self.in_above + self.in_below for item in lane)

    @property
    def width(self) -> int:
        return self.machines * self.mw

    @property
    def height(self) -> int:
        return len(self.in_above) + self.mh + len(self.out_lanes) + len(self.in_below)

    @property
    def machine_row(self) -> int:
        """Row index of the machine band's top edge, relative to the strip."""
        return len(self.in_above)

    @property
    def is_mode_driven(self) -> bool:
        return bool(self.mode_params)

    def lane_of_input(self, item: str) -> tuple[str, ...]:
        """The lane carrying ``item``, including anything sharing it."""
        for lane in self.in_above + self.in_below:
            if item in lane:
                return lane
        raise KeyError(f"{item!r} is not an ingredient of {self.recipe_id!r}")

    def input_is_shared(self, item: str) -> bool:
        """Does ``item`` ride a lane with other items?

        A sorter drawing from a shared lane MUST set a filter, or it takes
        whatever passes and starves the machine that wanted the other item.
        """
        return len(self.lane_of_input(item)) > 1

    def slot_of_input(self, item: str) -> int:
        """Position within its lane, which fixes the sorter's column.

        Two sorters serving one machine from one lane cannot share an anchor, so
        each item on a shared lane takes its own column across the machine's
        width.  That caps a lane at ``mw`` items.
        """
        return self.lane_of_input(item).index(item)

    def row_of_input(self, item: str) -> int:
        """Row index carrying ``item``, relative to the strip's top."""
        for j, lane in enumerate(self.in_above):
            if item in lane:
                return j
        for j, lane in enumerate(self.in_below):
            if item in lane:
                return len(self.in_above) + self.mh + len(self.out_lanes) + j
        raise KeyError(f"{item!r} is not an ingredient of {self.recipe_id!r}")

    def row_of_output(self, k: int) -> int:
        """Row index of the ``k``-th output lane, relative to the strip's top."""
        return len(self.in_above) + self.mh + k

    def input_lane_tiles(self, lane: tuple[str, ...]) -> int:
        """Belt tiles an INPUT lane actually needs, counted from its west end.

        An input lane is fed at its head and flows east, and every tile past the
        last sorter drawing from it carries items nothing will ever take -- dead
        belt, one building each to paste and one more cell the router has to path
        around.  ``_link_lane`` puts a sorter at ``machine.x + min(slot, mw - 1)``
        for each machine, so the last tile that does any work is the last
        machine's column plus the highest slot on this lane.

        Output lanes are NOT trimmable the same way: they are filled at every
        machine column and drained at the east end, so every tile between the
        first sorter and the port carries flow.
        """
        last_slot = min(len(lane) - 1, self.mw - 1)
        return (self.machines - 1) * self.mw + last_slot + 1

    def east_of_input(self, item: str) -> int:
        """Offset from the strip's west edge to the last tile of ``item``'s lane."""
        return self.input_lane_tiles(self.lane_of_input(item)) - 1

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


#: Separator joining several destination group keys onto ONE output lane.
#:
#: A group key is ``f"{recipe_id}#{index}"`` and a recipe id never contains a
#: pipe, so the join is unambiguous and reversible.
DEST_SEP = "|"


def _dests(dest: str) -> tuple[str, ...]:
    """The destination group keys one output lane serves.

    Empty for a lane that leaves the build, which is what an empty ``dest``
    means everywhere in this module.
    """
    return tuple(dest.split(DEST_SEP)) if dest else ()


def _shard_sinks(
    sinks: Sequence[tuple[str, str]],
    *,
    cap: int | None = None,
    max_shards: int | None = None,
) -> list[list[tuple[str, str]]]:
    """Chunk output sinks so no strip carries more lanes than a sorter can span.

    EVERY shard drains EVERY product.  One machine makes all of its recipe's
    outputs at once, so a shard that carries lanes for only some of them has
    machines that back up on the rest and stop -- and the strip looks perfectly
    healthy, because the lanes it does have are all connected.  Sequential
    chunking did exactly that: ``plasma-refining`` yields refined-oil and
    hydrogen, its four destinations chunked into a shard of three and a shard of
    one, and the second shard's five machines had nowhere to put their hydrogen.

    So the split is per ITEM rather than across the flat list: each product's
    destinations are divided between the shards, and a shard that would come out
    with none of some product is given a repeat of one of that product's
    destinations instead.  A repeat is not waste -- a sharded producer already
    feeds one consumer from several strips, and the router merges them -- it is
    the only way a shard can drain a product whose consumers are fewer than the
    shards.

    ``cap`` is the room left on the south side once any overflow input lanes are
    seated there; it defaults to the full sorter reach.

    ``max_shards`` is the number of MACHINES available.  A shard with no machine
    leaves its destinations unfed, so the split can never be finer than that --
    and a producer with one machine and four consumers is ordinary
    (``mass-energy-storage`` in the universe-matrix build).  Rather than refuse,
    the chunking stops at ``max_shards`` and hands back shards that may exceed
    ``cap`` lanes; :func:`_merge_lanes` then puts several destinations on ONE
    lane, which is the other axis the geometry actually has.  Callers that pass
    ``max_shards`` must therefore call :func:`_merge_lanes` on every shard.
    """
    reach = catalog.SORTER_MAX_REACH if cap is None else cap
    if reach <= 0:
        raise ValueError("no room left on the south side for any output lane")

    by_item: dict[str, list[str]] = {}
    for item, dest in sinks:
        by_item.setdefault(item, []).append(dest)
    if not by_item:
        return []
    if len(by_item) > reach:
        raise ValueError(
            f"a machine yields {len(by_item)} distinct products but only {reach} "
            f"output lane(s) fit inside the {catalog.SORTER_MAX_REACH}-tile sorter "
            "reach, so one of them could never be drained"
        )

    n = 1
    while sum(max(1, math.ceil(len(d) / n)) for d in by_item.values()) > reach:
        if max_shards is not None and n >= max_shards:
            break
        n += 1

    out: list[list[tuple[str, str]]] = [[] for _ in range(n)]
    for item, dests in by_item.items():
        per = math.ceil(len(dests) / n)
        for s in range(n):
            chunk = dests[s * per : (s + 1) * per] or [dests[s % len(dests)]]
            out[s].extend((item, d) for d in chunk)
    return out


def _merge_lanes(
    shard: Sequence[tuple[str, str]],
    reach: int,
    demand: Mapping[tuple[str, str], Fraction],
    capacity: Fraction,
) -> list[tuple[str, str]]:
    """Fold a shard's destinations onto at most ``reach`` output lanes.

    Sharding splits a producer's destinations across STRIPS and needs one
    machine per shard.  A producer with one machine and four destinations has no
    second shard to give, so the other axis has to move: one lane serves several
    destinations, each consumer tapping the same lane end, and ``_tap_source``
    turns the second and later taps into a junction there.  That is the same
    mechanism a lane already uses when one destination group is sharded into
    several consumer strips, so it costs no new machinery -- only the
    bookkeeping that a lane's destination field is now a SET.

    Which destinations share a lane is a bin-packing question, and the bin is a
    belt: two consumers whose combined draw exceeds the tier would jam the lane
    however it is routed.  Destinations are therefore packed largest-demand
    first into the least-loaded lane, and a lane that still comes out over
    capacity raises -- refusing is honest, while emitting it would produce a
    blueprint that pastes and then starves whichever consumer loses the race.

    Lanes are handed out one per product first (a shard must drain every
    product, or its machines back up on the one it cannot) and the spares go to
    whichever product has the most destinations per lane so far.
    """
    if len(shard) <= reach:
        return list(shard)

    by_item: dict[str, list[str]] = {}
    for item, dest in shard:
        by_item.setdefault(item, []).append(dest)
    if len(by_item) > reach:
        raise ValueError(
            f"a machine yields {len(by_item)} distinct products but only {reach} "
            f"output lane(s) fit inside the {catalog.SORTER_MAX_REACH}-tile sorter "
            "reach, so one of them could never be drained"
        )

    alloc = dict.fromkeys(by_item, 1)
    for _ in range(reach - len(by_item)):
        room = [item for item in by_item if alloc[item] < len(by_item[item])]
        if not room:
            break
        alloc[max(room, key=lambda i: (Fraction(len(by_item[i]), alloc[i]), i))] += 1

    out: list[tuple[str, str]] = []
    for item in sorted(by_item):
        k = alloc[item]
        bins: list[list[str]] = [[] for _ in range(k)]
        loads = [Fraction(0)] * k
        order = sorted(
            by_item[item], key=lambda d: (-demand.get((item, d), Fraction(0)), d)
        )
        for dest in order:
            b = min(range(k), key=lambda i: (loads[i], i))
            bins[b].append(dest)
            loads[b] += demand.get((item, dest), Fraction(0))
        for b, group in enumerate(bins):
            if not group:
                continue
            if loads[b] > capacity:
                raise ValueError(
                    f"{item}: destinations {sorted(group)} have to share one "
                    f"output lane carrying {loads[b]} items/s, over the "
                    f"{capacity}/s the belt sustains"
                )
            out.append((item, DEST_SEP.join(sorted(group))))
    return out


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
        # A mode-driven recipe names its machine in the catalog registry rather
        # than through the spec's producer, and carries no DSP recipe id at all.
        mode = catalog.MODE_DRIVEN_MACHINE.get(mg.recipe_id)
        if mode is not None:
            item_id = mode.machine_item_id
            mode_params = params.parameters_for(mg.recipe_id)
        else:
            resolved = MACHINE_ITEM_IDS.get(mg.machine_item_id)
            if resolved is None:
                raise KeyError(
                    f"no DSP building known for machine {mg.machine_item_id!r}"
                )
            item_id = resolved
            mode_params = ()
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
            mode_params=mode_params,
        )
    return groups


def _check_shared_lane_capacity(
    g: _Group, lanes: tuple[tuple[str, ...], ...], machines: int, spec: BuildSpec
) -> None:
    """A shared lane must carry the SUM of its items within the belt tier.

    Only shared lanes are checked.  A single-item lane is left exactly as it
    was, so this cannot reject a spec that already worked -- mixing is the new
    thing, so mixing is what gets the new constraint.

    Exact ``Fraction`` throughout: a float here would let a lane that lands
    precisely on the tier's limit read as over capacity, or worse, the reverse.
    """
    cap = spec.belt_items_per_second
    for lane in lanes:
        if len(lane) < 2:
            continue
        total = sum(
            (g.inputs.get(item, Fraction(0)) * machines for item in lane),
            Fraction(0),
        )
        if total > cap:
            raise ValueError(
                f"recipe {g.recipe_id!r}: lane carrying {list(lane)} needs "
                f"{total} items/s across {machines} machine(s), over the "
                f"{cap}/s a {spec.belt_item_id} sustains; these ingredients "
                f"cannot share a belt at this rate"
            )


def _seat_inputs(
    items: tuple[str, ...], n_sinks: int, reach: int, max_per_lane: int
) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...]]:
    """Seat ingredients into lanes above and below the machine band.

    Tries one item per lane FIRST and only mixes when that will not fit, which
    is what makes this additive: every spec that already worked seats exactly as
    it did before, so mixing opens new territory rather than trading anything.

    Mixing is capped at ``max_per_lane`` -- the machine's width -- because two
    sorters serving one machine from one lane cannot share an anchor, so each
    item on a shared lane needs its own column across that width.

    Returns ``(above, below)``.  ``below`` shares the south side with the output
    lanes, so it is kept as small as possible.
    """
    n = len(items)
    if n == 0:
        return (), ()
    for k in range(1, max(1, max_per_lane) + 1):
        lanes = [tuple(items[i : i + k]) for i in range(0, n, k)]
        above, below = tuple(lanes[:reach]), tuple(lanes[reach:])
        if len(below) > reach:
            continue  # more lanes than two sides can hold; mix harder
        if n_sinks and reach - len(below) <= 0:
            continue  # no room left below for an output lane
        return above, below
    raise ValueError(
        f"{n} ingredients cannot be seated: two sides of {reach} lanes carrying "
        f"at most {max_per_lane} items each leaves no room for the output lane"
    )


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

    INPUTS are handled the other way about.  Sharding cannot help them: a machine
    needs all its ingredients simultaneously, so splitting two ingredients into
    one shard and two into another leaves both shards stalled.  Instead the strip
    is fed from BOTH sides, and where two sides of single-item lanes still will
    not fit, ingredients SHARE a lane and their sorters filter -- see
    :func:`_seat_inputs`.

    Raises rather than truncating: a silently dropped ingredient would produce a
    blueprint that pastes cleanly and then stalls.
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

    reach = catalog.SORTER_MAX_REACH
    strips: list[Strip] = []
    for key, g in groups.items():
        in_items = tuple(sorted(g.inputs))

        sinks: list[tuple[str, str]] = []
        for item in sorted(g.outputs):
            dests = consumers.get((key, item), [])
            sinks.extend((item, d) for d in dests)
            if item in spec.outputs or not dests:
                sinks.append((item, ""))  # leaves the build

        try:
            in_above, in_below = _seat_inputs(
                in_items, len(sinks), reach, max_per_lane=g.width
            )
        except ValueError as exc:
            raise ValueError(f"recipe {g.recipe_id!r}: {exc}") from None

        # Output lanes share the south side with any overflow inputs, so the
        # shard size is what is left after those are seated.
        out_cap = reach - len(in_below)
        shards = (
            _shard_sinks(sinks, cap=out_cap, max_shards=g.count) if sinks else [[]]
        )
        demand = {
            (item, dest): _sink_demand(groups, spec, item, dest) for item, dest in sinks
        }
        per_shard = (
            _allocate_machines(g.count, shards, demand) if len(shards) > 1 else [g.count]
        )
        # Machines bound the number of shards, so a producer that still has more
        # destinations than lanes folds several of them onto one lane instead.
        # Merging AFTER the allocation keeps `_allocate_machines` looking at the
        # per-destination demand it was written against.
        try:
            lanes = [
                _merge_lanes(shard, out_cap, demand, spec.belt_items_per_second)
                for shard in shards
            ]
        except ValueError as exc:
            raise ValueError(f"recipe {g.recipe_id!r}: {exc}") from None

        for shard, machines in zip(lanes, per_shard, strict=True):
            n_strips = max(1, math.ceil(machines / max(1, strip_len)))
            base = machines // n_strips
            extra = machines % n_strips
            for s in range(n_strips):
                n = base + (1 if s < extra else 0)
                if n <= 0:
                    continue
                _check_shared_lane_capacity(g, in_above + in_below, n, spec)
                strips.append(
                    Strip(
                        group_key=key,
                        recipe_id=g.recipe_id,
                        item_id=g.item_id,
                        model_index=g.model_index,
                        machines=n,
                        mw=g.width,
                        mh=g.height,
                        in_above=in_above,
                        in_below=in_below,
                        out_lanes=tuple(shard),
                        mode_params=g.mode_params,
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
    #: Belt tiles each lane occupies, counted east from its strip's west edge.
    #: The sorter needs a column both lanes cover, and an input lane is trimmed
    #: to its last sorter, so the consumer's span is usually SHORTER than its
    #: strip.  Using the strip width for both would let the packer commit a pair
    #: whose lanes share no tile, which ``_bridge`` would then refuse -- a
    #: rewarded promise the emission stage cannot keep.
    prod_span: int = 1
    cons_span: int = 1


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
                if dst.group_key in _dests(dest)
            ),
            None,
        )
        if lane is None:
            continue
        k, item = lane
        if item not in dst.in_lanes:
            continue
        # Ask the strip for the rows rather than recomputing the layout here:
        # inputs may sit above or below the machine band, and duplicating that
        # arithmetic is how the two drift apart.
        out[i, j] = _DirectCandidate(
            item=item,
            prod_row=src.row_of_output(k),
            cons_row=dst.row_of_input(item),
            prod_span=src.width,
            cons_span=dst.input_lane_tiles(dst.lane_of_input(item)),
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
            for d in _dests(dest):
                for j in by_group.get(d, []):
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
    seed: _Pack | None = None,
) -> _Pack | None:
    """Minimise width at a fixed height with CP-SAT.

    Height is swept outside rather than multiplied inside: ``W * H`` is a product
    of two variables, whose CP-SAT relaxation is weak enough that the search
    flounders.  Several easy solves beat one hard one.

    ``seed`` is a shelf packing at this same height -- feasible by construction,
    so it does two things no heuristic guess could.  It hints every ``x``/``y``,
    which gives the search an incumbent immediately instead of after it finds
    one; and its width is a proven upper bound on ``w_var``, which cuts the
    domain the bound has to climb through.  This is the construction that used
    to be the fallback, put to the one use it is genuinely good for.
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
        # straight down, and each lane's span is its own -- an input lane stops
        # at its last sorter, so it is generally narrower than its strip.
        model.add(xs[i] <= xs[j] + cand.cons_span - 1).only_enforce_if(di)
        model.add(xs[j] <= xs[i] + cand.prod_span - 1).only_enforce_if(di)
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

    # Warm start.  The seed is feasible at this height by construction, so its
    # width bounds `w_var` from above and its positions give the search an
    # incumbent to improve on rather than one to find.  Values are clamped into
    # each variable's domain: an out-of-domain hint is not a tighter hint, it is
    # a discarded one.
    if seed is not None:
        model.add(w_var <= min(seed.width, width_bound))
        for i, (hx, hy) in seed.at.items():
            if i >= n:
                continue
            w, h = sizes[i]
            model.add_hint(xs[i], min(max(hx, 0), max(0, width_bound - w)))
            model.add_hint(ys[i], min(max(hy, 0), max(0, height - h)))

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

    #: ``cell -> port (x, y)``: one way in or out, held for that port's nets.
    #:
    #: A port is a lane's end tile, so it has at most three free neighbours and
    #: often one.  Without a reservation an earlier net's path takes the last
    #: one, and every net using that port is then handed an EMPTY start or goal
    #: set: A* returns ``None`` having expanded zero nodes.  That is
    #: indistinguishable from congestion in the counters and cannot be
    #: negotiated away, because a net that expands nothing never registers a
    #: conflict for the history term to price.  Measured on the magnetic-ring
    #: spec: 48 of 128 searches failed at zero expansions, at every candidate
    #: height, with two thirds of the routing budget still unspent.
    reserved: dict[tuple[int, int, int], tuple[int, int]] = field(default_factory=dict)
    #: Ports the net currently being routed owns; it may use their reservations.
    routing_ports: frozenset[tuple[int, int]] = frozenset()
    #: ``(min_x, min_y, max_x, max_y)`` no building may leave, once the packed
    #: block's extent is known.
    #:
    #: This is the one thing that makes the block's boundary hold still.  Every
    #: later pass -- coater drops, the router, the external input runs, the
    #: power lattice -- asks ``free`` before it places, so the final bounding box
    #: is decided once, by the packer, instead of being pushed outward by
    #: whichever pass ran last.  ``None`` while the extent is still being
    #: established, which is exactly the window in which the strips are emitted.
    limit: tuple[int, int, int, int] | None = None
    #: Cells held for the tower lattice, at every level.
    #:
    #: Claimed before the router runs and released just before the towers go in.
    #: Power used to take whatever was left over once every belt was laid, which
    #: on a dense block is nothing: measured on ``casimir-crystal``, a matrix lab
    #: had FOUR free cells among the 349 inside tower range, and thirteen
    #: buildings shipped unpowered.  A lattice point is one cell in eighty-one;
    #: the router can afford to path around it, and coverage cannot afford to be
    #: whatever is left.
    keep_out: set[tuple[int, int]] = field(default_factory=set)

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
        if cell in self.blocked or (x, y) in self.solid or (x, y) in self.keep_out:
            return False
        if self.limit is not None:
            min_x, min_y, max_x, max_y = self.limit
            if not (min_x <= x <= max_x and min_y <= y <= max_y):
                return False
        port = self.reserved.get(cell)
        return port is None or port in self.routing_ports


def _core_bounds(canvas: _Canvas) -> tuple[int, int, int, int]:
    """The INCLUSIVE tile box the packed block occupies.

    Tile extents, not origins.  ``_build`` used to take ``max(b.x)`` and add the
    pack width to it, which over-estimated the east face by a whole block and
    under-estimated it by a machine's width -- so the router had a field to roam
    in on one side and none on the other, and "the edge" meant something
    different depending on which pass asked.
    """
    if not canvas.buildings:
        return (0, 0, 0, 0)
    return (
        min(b.x for b in canvas.buildings),
        min(b.y for b in canvas.buildings),
        max(b.x + b.width - 1 for b in canvas.buildings),
        max(b.y + b.height - 1 for b in canvas.buildings),
    )


def _grow(box: tuple[int, int, int, int], rings: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    return (x0 - rings, y0 - rings, x1 + rings, y1 + rings)


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
    """Where a net starts or ends: a lane tile, and the way out of it."""

    belt: int
    x: int
    y: int
    #: Inclusive x-range of the whole lane, not just the tile the router
    #: attaches to.  A direct-insert sorter may drop down ANY column the two
    #: lanes share, so it needs the extent rather than the endpoint.
    x0: int = 0
    x1: int = -1
    #: Every belt index in this lane, west to east.
    #:
    #: Carried so that a lane feeding several consumers can give each of them
    #: its OWN tile to leave from.  They used to share the lane's end tile, and
    #: a belt tile has one ``output_obj``, so only one net could be linked --
    #: see ``_commit_paths``.  A tap partway along the lane becomes a junction;
    #: the tiles are what makes choosing distinct taps possible.
    tiles: tuple[int, ...] = ()
    #: Machines behind this lane.
    #:
    #: A strip's lane carries its OWN machines' share of the group's rate, and
    #: the shards of one group are rarely the same size.  Pairing producer lanes
    #: against consumer lanes without knowing this is what let a four-machine
    #: shard be handed eleven of a sixteen-machine consumer group -- see
    #: :func:`_staircase`.
    machines: int = 1

    def columns(self) -> range:
        return range(self.x0, self.x1 + 1)

    def at_tile(self, k: int) -> _Port:
        """This port moved to the ``k``-th tile of its own lane.

        Out-of-range or an unknown tile list leaves the port alone, so a caller
        that asks for more taps than the lane has tiles degrades to sharing --
        which the fan-out check then reports honestly rather than mis-linking.
        """
        if not self.tiles or not 0 <= k < len(self.tiles):
            return self
        return _Port(
            self.tiles[k],
            self.x0 + k,
            self.y,
            self.x0,
            self.x1,
            self.tiles,
            self.machines,
        )


def _lane_filter(item: str) -> int:
    """The DSP item id a sorter on a shared lane must filter to.

    Raises rather than falling back to zero: an unfiltered sorter on a shared
    lane grabs whatever passes and starves the machine that wanted the other
    item, and the blueprint still pastes cleanly.
    """
    got = catalog.get_item_id(item)
    if got is None:
        raise KeyError(
            f"{item!r} shares a belt lane but has no DSP item id, so its sorter "
            f"cannot be filtered; it would take whatever passed instead"
        )
    return got


def _emit_strip(
    canvas: _Canvas,
    s: Strip,
    ox: int,
    oy: int,
    belt_id: int,
    belt_model: int,
    rates: dict[str, Fraction],
    in_rates: Mapping[str, Fraction] | None = None,
    out_rates: Mapping[str, Fraction] | None = None,
) -> tuple[dict[str, _Port], dict[tuple[str, str], _Port], int]:
    """Place one strip's lanes, machines and sorters.

    Returns the west end of each input lane and the east end of each output lane
    -- the points routing connects -- plus the sorter count.

    Inputs may sit on either side of the machine band; ``Strip.row_of_input``
    owns that arithmetic so it is stated once rather than re-derived here.

    Where a lane carries several items, each gets its OWN sorter, filtered to
    that item and offset into its own column across the machine's width.  Two
    sorters serving one machine from one lane cannot share an anchor, and an
    unfiltered sorter on a shared lane takes whatever passes -- starving the
    machine that wanted the other item, with nothing about the paste looking
    wrong.

    Sorter tiers are sized from the rate of the ITEM EACH SORTER MOVES, per
    machine.  Sizing from a machine's average across its sorters is wrong and
    hid a real starvation bug: ``circuit-board`` takes copper at 1/s and iron at
    2/s, and charging both sorters the 1.5/s average exactly meets a Mk.I, so it
    read as clean while the sorter actually carrying the iron starved the
    machine.  An overloaded sorter hides behind an underloaded one whenever
    ingredient rates differ, which is most of the time.
    """
    in_rates = in_rates or {}
    out_rates = out_rates or {}
    in_ports: dict[str, _Port] = {}
    out_ports: dict[tuple[str, str], _Port] = {}
    width = s.width
    n_above = len(s.in_above)

    # Row -> the item that row's belt is labelled with. On a shared lane this is
    # the FIRST item; the authoritative set is the sorters' filters, which is
    # what the validator keys on. Building it up front removes the
    # branch-per-row this used to need, and it is what lets the marker pass
    # label external input belts later: the knowledge is unrecoverable once
    # emission drops it.
    lane_item_of: dict[int, str] = {}
    #: Row -> belt tiles that row's lane actually needs.  Input lanes stop at
    #: their last sorter (see ``Strip.input_lane_tiles``); output lanes run the
    #: full width because their port is the east end.
    lane_tiles_of: dict[int, int] = {}
    for lane in s.in_above + s.in_below:
        row = s.row_of_input(lane[0])
        lane_item_of[row] = lane[0]
        lane_tiles_of[row] = s.input_lane_tiles(lane)
    for k, (item, _dest) in enumerate(s.out_lanes):
        lane_item_of[s.row_of_output(k)] = item
        lane_tiles_of[s.row_of_output(k)] = width

    lane_idx: dict[int, list[int]] = {}
    for row in range(s.height):
        y = oy + row
        if n_above <= row < n_above + s.mh:
            continue  # machine band
        indices = []
        for k in range(lane_tiles_of.get(row, width)):
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
                        carries_item=lane_item_of.get(row),
                    )
                )
            )
        for a, b in zip(indices, indices[1:], strict=False):
            canvas.buildings[a] = _relink(canvas.buildings[a], output_obj=b)
        lane_idx[row] = indices

    machine_y = oy + n_above
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
                    # A mode-driven machine carries no recipe id at all: its job
                    # is the word in the parameter block. This was once
                    # `abs(hash(name)) % 30000`, which is not a DSP recipe id and
                    # is not even stable across processes, since Python
                    # randomises string hashing.
                    recipe_id=0 if s.is_mode_driven else catalog.recipe_id(s.recipe_id),
                    parameters=s.mode_params,
                ),
                solid=True,
            )
        )

    bottom = machine_y + s.mh - 1
    sorters = 0

    def item_rate(item: str, table: Mapping[str, Fraction]) -> Fraction:
        """What ONE sorter moves: one machine's rate for this one item."""
        got = table.get(item)
        if got is not None and got > 0:
            return got
        return rates.get(item, Fraction(1))

    def feed(lane: tuple[str, ...], row: int, span: int, near_edge: int) -> int:
        """One filtered sorter per (item, machine) for this lane."""
        placed = 0
        shared = len(lane) > 1
        for slot, item in enumerate(lane):
            in_ports[item] = _Port(
                lane_idx[row][0],
                ox,
                oy + row,
                ox,
                ox + len(lane_idx[row]) - 1,
                tuple(lane_idx[row]),
                s.machines,
            )
            tier, _count = _pick_sorter(item_rate(item, in_rates), span, 1)
            placed += _link_lane(
                canvas,
                lane_idx[row],
                machines,
                oy + row,
                near_edge,
                tier,
                into_machine=True,
                filter_id=_lane_filter(item) if shared else 0,
                column=slot,
            )
        return placed

    for j, lane in enumerate(s.in_above):
        sorters += feed(lane, row=j, span=n_above - j, near_edge=machine_y)

    for j, (item, dest) in enumerate(s.out_lanes):
        row = s.row_of_output(j)
        span = j + 1
        out_ports[item, dest] = _Port(
            lane_idx[row][-1],
            ox + width - 1,
            oy + row,
            ox,
            ox + width - 1,
            tuple(lane_idx[row]),
            s.machines,
        )
        tier, _count = _pick_sorter(item_rate(item, out_rates), span, 1)
        sorters += _link_lane(
            canvas, lane_idx[row], machines, oy + row, bottom, tier, into_machine=False
        )

    # Overflow ingredients, seated below the output lanes and reaching up to the
    # machine band's south edge.
    for j, lane in enumerate(s.in_below):
        row = s.row_of_input(lane[0])
        sorters += feed(
            lane, row=row, span=len(s.out_lanes) + j + 1, near_edge=bottom
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
    filter_id: int = 0,
    column: int = 0,
) -> int:
    """One sorter per machine, between the lane and the machine's near edge.

    Anchors sit *on* the two buildings and the connection indices carry the
    semantics, which is how the game itself represents this -- a sorter consumes
    no grid cell of its own.

    ``column`` offsets the sorter across the machine's width so several items
    sharing one lane each get their own anchor; ``filter_id`` pins which item
    this sorter moves, which is mandatory on a shared lane and left at zero on a
    plain one.  That zero-versus-set distinction is the signal the validator
    uses to tell the two apart, so do not set a filter where none is needed.
    """
    model_index = catalog.building(tier).model_index
    facing = Facing.SOUTH.value if lane_y < machine_y else Facing.NORTH.value
    placed = 0
    for m_idx in machines:
        m = canvas.buildings[m_idx]
        x = m.x + min(column, m.width - 1)
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
                filter_id=filter_id,
            )
        )
        placed += 1
    return placed


def _relink(
    b: PlacedBuilding,
    *,
    output_obj: int | None = None,
    input_obj: int | None = None,
) -> PlacedBuilding:
    """Repoint a belt at its successor or its feeder, preserving everything else.

    Uses ``replace`` rather than rebuilding field by field.  The hand-written
    version enumerated fields and therefore silently dropped any it did not
    mention -- it was already discarding ``parameters``, and it swallowed
    ``carries_item`` the moment that was added, which is why belt markers came
    out empty while the emitter was setting them correctly.

    Only the arguments actually passed are applied, so ``_relink(b,
    input_obj=j)`` cannot clear an ``output_obj`` set moments earlier.
    """
    changes: dict[str, int] = {}
    if output_obj is not None:
        changes["output_obj"] = output_obj
    if input_obj is not None:
        changes["input_obj"] = input_obj
    return replace(b, **changes)  # type: ignore[arg-type]


# --- phase 2: routing ------------------------------------------------------

_STEPS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _cut_loops(path: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    """Remove any cell that appears twice, keeping the walk connected.

    A ramp edge occupies an extra "run" cell, spliced in from ``via`` during
    reconstruction.  That cell can already lie on the path -- the route leaves
    it, wanders, and comes back to climb from it -- and then the same tile
    appears twice.  Committing such a path fails: the second occurrence finds
    the cell already built and the whole net is dropped, silently until
    ``_commit_paths`` learned to count.  Measured on the magnetic-ring chain, 3
    of 19 routed paths had a repeat.

    Cutting the loop between the two occurrences is safe, and cheaper than
    rerouting: consecutive cells in the walk are adjacent (or a ramp pair) by
    construction, so splicing out everything between a repeat and its first
    occurrence leaves a walk whose consecutive cells were already consecutive.
    The result is also shorter, which is strictly better.
    """
    first: dict[tuple[int, int, int], int] = {}
    out: list[tuple[int, int, int]] = []
    for cell in path:
        seen_at = first.get(cell)
        if seen_at is not None:
            for dropped in out[seen_at + 1 :]:
                first.pop(dropped, None)
            del out[seen_at + 1 :]
            continue
        first[cell] = len(out)
        out.append(cell)
    return out


def _astar(
    canvas: _Canvas,
    starts: list[tuple[int, int, int]],
    goals: set[tuple[int, int, int]],
    history: dict[tuple[int, int, int], float],
    pressure: float,
    bounds: tuple[int, int, int, int],
    budget: dict[str, int] | None = None,
) -> list[tuple[int, int, int]] | None:
    """Cheapest free-cell path, with congestion history folded into the cost.

    The history term is what makes rip-up-and-reroute converge: a cell that
    several nets have fought over becomes progressively more expensive, so they
    negotiate rather than oscillate.

    ``bounds`` is the INCLUSIVE box the path may occupy.  It used to be the
    block's bounding box with two tiles of slack added here, which meant the
    caller could not say where the router was allowed to go -- and the router
    going two tiles past a boundary the caller had already promised to somebody
    else is what walled in the external entry lanes.  Start cells are exempt:
    an external input run begins on the entry ring, outside the routing box, and
    works inward.
    """
    if not goals:
        return None
    min_x, min_y, max_x, max_y = bounds

    def inside(cell: tuple[int, int, int]) -> bool:
        return min_x <= cell[0] <= max_x and min_y <= cell[1] <= max_y

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
    if budget is not None and budget["left"] <= 0:
        return None
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
        if budget is not None:
            budget["left"] -= 1
            if budget["left"] <= 0:
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
            return _cut_loops(list(reversed(path)))
        x, y, lvl = cur
        for dx, dy in _STEPS:
            nxt = (x + dx, y + dy, lvl)
            if not inside(nxt):
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
                # Both halves of the ramp are bounds-checked, not just tested
                # for freedom.  They were not, which let a ramp step two tiles
                # clear of the routing box and put a belt in the margin the
                # external entry runs rely on being empty.
                if not inside(run) or not inside(top):
                    continue
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


def _merge_frontier(
    canvas: _Canvas,
    paths: dict[int, list[tuple[int, int, int]]],
    siblings: tuple[int, ...],
) -> set[tuple[int, int, int]]:
    """Free cells beside a sibling net's path -- somewhere to merge into.

    Two belts feeding one is a side merge, which the game allows and
    ``_build_runs`` already models (a tile with two predecessors heads its own
    run).  Reaching a sibling's belt is therefore as good as reaching the lane
    it feeds, and it is the ONLY option when the lane itself is walled in.

    The sibling's own cells are not offered as goals: they are occupied, so A*
    could never step onto them.  Their free neighbours are what a merging belt
    actually needs.
    """
    out: set[tuple[int, int, int]] = set()
    for s in siblings:
        for x, y, lvl in paths.get(s, ()):
            for dx, dy in _STEPS:
                cell = (x + dx, y + dy, lvl)
                if canvas.free(cell):
                    out.add(cell)
    return out


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
    # A TOTAL expansion budget across every net and every rip-up round.
    #
    # `_MAX_EXPANSIONS` bounds one search; nothing bounded the product. At
    # 470-machine scale that is ~50 nets x 8 rounds x 200k = up to 80M
    # expansions, which ran for over fifteen minutes -- not a hang, just work
    # nobody had bounded. A shared budget is deterministic (no wall clock, so
    # runs stay reproducible) and degrades honestly: an exhausted search returns
    # None, which is already the route-failure path the caller repairs from and
    # records in `route_failures`.
    budget = {"left": _ROUTING_BUDGET}
    fewest_failed = len(nets) + 1
    stale = 0
    #: The BEST round's paths, not the last round's.
    #:
    #: What gets committed used to be whichever round the loop happened to stop
    #: on, and the shared expansion budget makes the last round systematically
    #: the WORST one: round 1 spends the budget, every round after it has
    #: nothing left to search with, and `_astar` returns `None` for every net
    #: before expanding a node. Committing that round throws away a perfectly
    #: good routing and reports the pack unwireable.
    #:
    #: Measured on universe-matrix/max-proliferation: two of the five candidate
    #: heights reported `routed=0 failed=115` -- every net -- while their first
    #: round had routed roughly seventy of them. Rip-up-and-reroute is a search
    #: over rounds; keeping the incumbent is what makes it one.
    best_paths: dict[int, list[tuple[int, int, int]]] = {}

    _reserve_port_access(canvas, nets)

    # Nets that end at the same lane. Ordered, so "the ones before me" is
    # well defined however the router chooses to sequence a round.
    same_dst: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, net in enumerate(nets):
        same_dst[net.dst.x, net.dst.y].append(i)
    dst_group = {
        i: tuple(g for g in same_dst[net.dst.x, net.dst.y] if g != i)
        for i, net in enumerate(nets)
    }
    # The same story on the producer side, and it needs the same answer. An
    # out-lane sandwiched between its neighbours is only reachable at its ends,
    # so walking it tile by tile hands the later nets a walled-in start. They
    # BRANCH instead: leave from a sibling's path, which becomes a splitter on
    # that path at commit time. Keyed by the LANE (row and west edge), not the
    # port, because `at_tile` moves the port along the lane it belongs to.
    same_src: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, net in enumerate(nets):
        same_src[net.src.y, net.src.x0].append(i)
    src_group = {
        i: tuple(g for g in same_src[net.src.y, net.src.x0] if g != i)
        for i, net in enumerate(nets)
    }
    # Chained nets -- one net leaving the belt another delivers to, which is what
    # `_proliferator_nets` builds -- used to be allowed to merge into each
    # other's paths in both directions. Neither direction survives inspection.
    #
    # Arriving at a path that LEAVES a belt does not fill that belt: flow runs
    # the other way. A net that "reached" its destination that way carried its
    # items PAST the drop rather than into it, so the coater sprayed nothing and
    # the drop read as an entry lane the player must fill, buried mid-block.
    #
    # Leaving from a path that ARRIVES at the belt does deliver the items, but
    # it builds a SPLITTER on that path to do it, and a branch drawn off a
    # splitter is a belt run of its own that nothing inside the blueprint fills
    # -- the same unreachable entry lane by a different route.
    #
    # What both were standing in for is a drop with two ways in, one for the hop
    # arriving and one for the hop leaving. `_reserve_port_access` holds both,
    # and `_proliferator_nets` links neighbouring drops directly rather than
    # routing between them, so a drop with only one free neighbour never needs a
    # second. That leaves the chain a single linear run, which is the only shape
    # that is both correct and reachable.

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
            # Claim this net's port reservations for the duration of its search,
            # so its own way in and out reads as free while every other port's
            # stays held.
            canvas.routing_ports = frozenset(
                {(net.src.x, net.src.y), (net.dst.x, net.dst.y)}
            )
            starts = [
                (net.src.x + dx, net.src.y + dy, 0)
                for dx, dy in _STEPS
                if canvas.free((net.src.x + dx, net.src.y + dy, 0))
            ]
            # Leaving from a sibling's belt is as good as leaving from the lane,
            # and it is the only option when the lane is walled in. `_tap_source`
            # turns the attachment into a splitter on that belt.
            starts.extend(
                sorted(_merge_frontier(canvas, paths, src_group.get(i, ())) - set(starts))
            )
            goals = {
                (net.dst.x + dx, net.dst.y + dy, 0)
                for dx, dy in _STEPS
                if canvas.free((net.dst.x + dx, net.dst.y + dy, 0))
            }
            # A lane head has one way in. When several producers feed the same
            # lane, only the first can use it; the rest MERGE into whatever
            # already got there, which is what converging belts do in game. The
            # goal set therefore grows to include the free cells beside every
            # path already laid this round for the same destination -- reaching
            # one of those is reaching the lane.
            for cell in _merge_frontier(canvas, paths, dst_group.get(i, ())):
                goals.add(cell)
            routed = _astar(canvas, starts, goals, history, pressure, bounds, budget)
            canvas.routing_ports = frozenset()
            if routed is None:
                failed += 1
                continue
            paths[i] = routed
            for cell in routed:
                canvas.blocked[cell] = -2  # tentative reservation
            committed.append(routed)
        if failed == 0:
            unlinked = _commit_paths(canvas, nets, paths, belt_id, belt_model)
            return len(paths) - unlinked, unlinked, iterations
        for path in committed:
            for cell in path:
                history[cell] += 1.0
        # Give up once raising the pressure has stopped buying anything.
        #
        # Rip-up-and-reroute converges by making contested cells progressively
        # dearer, so a round that fails no fewer nets than the best round so far
        # is evidence the failures are not contention. Running the remaining
        # rounds anyway is the single largest cost in this strategy when a pack
        # cannot be wired -- and a pack that cannot be wired is exactly when
        # every round runs. Three rounds of no improvement before quitting,
        # because pressure grows geometrically and a late round can still break
        # a deadlock that earlier ones could not.
        if failed < fewest_failed:
            fewest_failed, stale, best_paths = failed, 0, paths
        else:
            stale += 1
        # An exhausted expansion budget ends the search as surely as a stale
        # round does: every further round would re-run every net against a
        # budget of zero and fail all of them, and the counters would read as
        # congestion rather than as work nobody had left to do.
        if stale >= _RRR_STALE_ROUNDS or it == RRR_MAX - 1 or budget["left"] <= 0:
            break
    unlinked = _commit_paths(canvas, nets, best_paths, belt_id, belt_model)
    return len(best_paths) - unlinked, fewest_failed + unlinked, iterations


def _reserve_port_access(
    canvas: _Canvas, nets: list[_Net], *, twice: Collection[tuple[int, int]] = ()
) -> int:
    """Hold a cell next to every port, so no net can be walled in by another.

    Returns the number of ports that had no free neighbour to reserve -- those
    are genuinely boxed in by the packing and no routing order can save them,
    which is worth knowing separately from a net that merely lost a race.

    Reservations are per PORT, not per net: several nets can share one lane end
    (a lane feeding two consumers), and they can share its access cell too,
    because they all leave from the same tile.  Reserving per net would hand the
    second net a different cell it does not need and take it away from someone
    who does.

    A port that both RECEIVES and SENDS gets two cells without being asked for.
    A coater's drop belt is one: the proliferator chain arrives at it from the
    previous coater and leaves it for the next, so one access cell cannot serve
    both -- whichever net routed first took it and built on it, and the other
    found the drop walled in.  It did not fail loudly, because the router will
    settle for merging into a sibling net's path; the belts that came out of
    that merge carried proliferator PAST the drop instead of INTO it, leaving a
    coater mounted on a belt nothing fills.  The drop then reads as an entry
    lane the player must fill, buried inside the block -- which is exactly what
    ``flow.external_entry_reachable`` was reporting.

    ``twice`` names ports that need one MORE approach on top of that, which is
    what an input lane fed from both outside and inside is.  ``_seat_inputs``
    mixes two ingredients onto one lane when they will not fit one per lane, and
    one of them can be an external input while the other is produced internally;
    the external run then arrives on the lane head's one open side and the
    internal net finds an empty goal set.  Both claims are legitimate and they
    are not the same cell, so both are staked.

    Ports are served shortest-lane-first within a round, which is arbitrary and
    deliberately so: what decides whether a port gets an access cell at all is
    the ROUND, not the position in it, and every port has taken its first before
    any port asks for a second.
    """
    canvas.reserved.clear()
    ports: dict[tuple[int, int], int] = {}
    roles: dict[tuple[int, int], set[str]] = defaultdict(set)
    for net in nets:
        for role, port in (("src", net.src), ("dst", net.dst)):
            key = (port.x, port.y)
            ports[key] = max(ports.get(key, 0), len(port.columns()))
            roles[key].add(role)

    order = sorted(ports, key=lambda k: (ports[k], k))
    wants = {k: len(roles[k]) + (1 if k in twice else 0) for k in order}
    held: dict[tuple[int, int], int] = defaultdict(int)

    # EVERY port gets its first cell before any port gets its second.
    #
    # One pass in want-order does not do this: ports are served shortest-lane
    # first, a coater drop is a one-tile lane, and a drop wanting two cells would
    # take both before a strip lane head -- which may have exactly one free
    # neighbour in the world -- had asked for its first.  Losing that cell is not
    # a worse route, it is an empty goal set and a net that cannot be routed at
    # all; it turned four candidates from wrong into unbuildable.  Second claims
    # are a convenience for a port that has two jobs, and they yield.
    for round_no in range(max(wants.values(), default=0)):
        for key in order:
            if wants[key] <= round_no:
                continue
            px, py = key
            # `free` already refuses a cell reserved for another port, since
            # `routing_ports` is empty here.
            got = next(
                (
                    c
                    for c in ((px + dx, py + dy, 0) for dx, dy in _STEPS)
                    if canvas.free(c)
                ),
                None,
            )
            if got is None:
                continue
            canvas.reserved[got] = key
            held[key] += 1

    return sum(1 for key in order if not held[key])


def _commit_paths(
    canvas: _Canvas,
    nets: list[_Net],
    paths: dict[int, list[tuple[int, int, int]]],
    belt_id: int,
    belt_model: int,
) -> int:
    """Turn reserved cells into real belts, forward-linked source to sink.

    Returns the number of routed nets that could NOT be linked to their source.

    A belt tile has ONE ``output_obj``.  When a lane serves several consumers,
    each of them taps a different tile of it (see ``_Port.at_tile``), and a tap
    partway along a lane is a JUNCTION: the lane has to keep flowing east *and*
    hand items to the branch.  ``_tap_source`` builds that as a splitter, which
    is what the game uses and what the fixture corpus shows.

    Before splitters existed, every such net rewrote the same lane-end tile and
    the last to commit won silently.  The earlier paths stayed on the grid as
    belts nothing fed: real buildings, real area, no items.
    """
    for cell, owner in list(canvas.blocked.items()):
        if owner == -2:
            del canvas.blocked[cell]
    # Release the port reservations. They exist to stop one net's path from
    # taking the last cell another net needs to leave its port, and routing is
    # over -- but `free()` refuses a cell reserved for a port that is not being
    # routed, and nothing is being routed here. Leaving them held made every
    # path that ran through its OWN start or goal cell fail the free() check
    # below and get dropped. Silently, until `_commit_paths` learned to count.
    canvas.reserved.clear()
    canvas.routing_ports = frozenset()
    unlinked = 0
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
            unlinked += 1
            continue
        for a, b in zip(indices, indices[1:], strict=False):
            canvas.buildings[a] = _relink(canvas.buildings[a], output_obj=b)
        feeder = _source_for(canvas, indices[0], net, set(indices))
        if not _tap_source(canvas, feeder, indices[0], belt_id, belt_model):
            unlinked += 1
            continue
        canvas.buildings[indices[-1]] = _relink(
            canvas.buildings[indices[-1]],
            output_obj=_sink_for(canvas, indices[-1], net, set(indices)),
        )
    return unlinked


def _source_for(canvas: _Canvas, first: int, net: _Net, own: set[int]) -> int:
    """What this path actually left from: the lane tap, or a sibling to branch off.

    The mirror of :func:`_sink_for`.  A path that could not start beside its own
    lane was routed from a sibling's belt instead, and feeding it from
    ``net.src.belt`` regardless would name a building it is nowhere near.
    """
    head = canvas.buildings[first]
    src = canvas.buildings[net.src.belt]
    if abs(src.x - head.x) + abs(src.y - head.y) <= 1 and src.z == head.z:
        return net.src.belt
    for dx, dy in _STEPS:
        cell = (head.x + dx, head.y + dy, head.z)
        who = canvas.blocked.get(cell)
        if who is None or not 0 <= who < len(canvas.buildings) or who in own:
            # Never attach to a belt of THIS path. The cell before the one we
            # are linking is adjacent and carries the same item, so it always
            # matches -- and pointing at it makes a two-belt cycle, which
            # `belt.acyclic` then reports.
            continue
        if who == net.dst.belt:
            # Nor to the lane this net DELIVERS to. A short path that ends up
            # beside its own destination satisfies "a belt carrying my item is
            # next to my head" perfectly, and taking it makes the lane feed the
            # branch that feeds the lane -- through the splitter `_tap_source`
            # builds, so a link-following eye slides straight past it. This was
            # the intermittent `belt.acyclic` on the magnetic-ring fixture:
            # feeder 597 -> splitter -> stub -> branch 1192 -> 597.
            continue
        other = canvas.buildings[who]
        if catalog.is_belt(other.item_id) and other.carries_item == net.item:
            return who
    return net.src.belt


def _leads_back(canvas: _Canvas, start: int, own: set[int]) -> bool:
    """Does flow leaving ``start`` come back to this path?

    Merging into a neighbouring belt is only legal when that belt runs AWAY from
    us.  Two nets that share a source lane and a destination lane end up beside
    each other twice -- the second branches off the first to leave, and then
    finds the first again at the far end -- and merging both ways closes the
    loop.  The validator reports it as ``belt.acyclic``, and it is a real fault:
    the game would run items round it forever.

    Splitters are followed, not stopped at: they carry no ``output_obj`` of
    their own, so a link-following walk misses exactly the loops a fan-out
    router most easily builds.  Same rule as ``validate._belt_successors``, so
    what this refuses to build is what that refuses to accept.
    """
    from_junction: dict[int, list[int]] = defaultdict(list)
    for i, b in enumerate(canvas.buildings):
        feed = b.input_obj
        if (
            feed is not None
            and 0 <= feed < len(canvas.buildings)
            and canvas.buildings[feed].item_id == catalog.SPLITTER_ID
        ):
            from_junction[feed].append(i)

    seen: set[int] = set()
    stack = [start]
    while stack:
        i = stack.pop()
        if i in own:
            return True
        if i in seen or not 0 <= i < len(canvas.buildings):
            continue
        seen.add(i)
        b = canvas.buildings[i]
        if b.item_id == catalog.SPLITTER_ID:
            stack.extend(from_junction.get(i, ()))
        elif catalog.is_belt(b.item_id) and b.output_obj is not None:
            stack.append(b.output_obj)
    return False


def _sink_for(canvas: _Canvas, last: int, net: _Net, own: set[int]) -> int:
    """What this path actually reached: the lane head, or a sibling to merge into.

    A path that could not get to the lane head was routed to a sibling's belt
    instead (see ``_merge_frontier``), so linking it to ``net.dst.belt``
    regardless would name a building it is nowhere near -- which
    ``belt.link_adjacent`` would then, correctly, report as an error.

    Preference order is the lane head first, so the common case is unchanged and
    a merge only happens where one was actually routed.
    """
    tail = canvas.buildings[last]
    dst = canvas.buildings[net.dst.belt]
    if abs(dst.x - tail.x) + abs(dst.y - tail.y) <= 1 and dst.z == tail.z:
        return net.dst.belt
    for dx, dy in _STEPS:
        cell = (tail.x + dx, tail.y + dy, tail.z)
        who = canvas.blocked.get(cell)
        if who is None or not 0 <= who < len(canvas.buildings) or who in own:
            # Never attach to a belt of THIS path. The cell before the one we
            # are linking is adjacent and carries the same item, so it always
            # matches -- and pointing at it makes a two-belt cycle, which
            # `belt.acyclic` then reports.
            continue
        other = canvas.buildings[who]
        if catalog.is_belt(other.item_id) and other.carries_item == net.item:
            if _leads_back(canvas, who, own):
                continue  # merging here would close a loop
            return who
    # Nothing adjacent carries this item. Name the lane head anyway so the
    # failure is visible as `belt.link_adjacent` rather than as a belt that
    # quietly ends nowhere.
    return net.dst.belt


def _tap_source(
    canvas: _Canvas, belt_idx: int, branch: int, belt_id: int, belt_model: int
) -> bool:
    """Make ``belt_idx`` hand items to ``branch``, junctioning if it must.

    Three cases, and the distinction is the whole point:

    * The tile has no onward link -- it is a lane end -- so it can simply point
      at the branch.
    * The tile already flows onward to the next lane tile.  It cannot also point
      at the branch, so a splitter goes on the tile: the lane feeds it, a new
      co-located belt carries the lane onward from it, and the branch draws from
      it too.  Co-location is not a liberty; it is exactly what the corpus does,
      a belt running *through* a junction being recorded as two belts on the
      tile.
    * The tile already feeds a splitter, because another branch got here first.
      Attach to that same junction if it has a spare side, otherwise report the
      failure rather than exceed a splitter's four ports, which pastes as a
      junction quietly dropping a connection.

    Returns ``False`` when the branch could not be attached.
    """
    b = canvas.buildings[belt_idx]
    onward = b.output_obj
    if onward is None:
        canvas.buildings[belt_idx] = _relink(b, output_obj=branch)
        return True

    if canvas.buildings[onward].item_id == catalog.SPLITTER_ID:
        junction_idx = onward
    else:
        junction_idx = canvas.add(
            junction.make_splitter(b.x, b.y, b.z, carries_item=b.carries_item)
        )
        canvas.buildings[belt_idx] = _relink(b, output_obj=junction_idx)
        # Carry the lane onward FROM the junction, so everything downstream of
        # the tap stays fed. Dropping this would starve the rest of the lane in
        # order to feed the branch -- trading one silent break for another.
        # `replace`, not a fresh PlacedBuilding: the carry belt IS the lane belt
        # continuing past the junction, so every field it does not change should
        # come across untouched. Listing fields by hand is how `carries_item`
        # and `parameters` got silently dropped elsewhere in this file.
        carry = canvas.add(replace(b, input_obj=junction_idx, output_obj=onward))
        del carry  # linked by construction; the index is not needed again

    attached = sum(
        1
        for c in canvas.buildings
        if c.output_obj == junction_idx or c.input_obj == junction_idx
    )
    if attached >= junction.MAX_PORTS:
        return False

    # The branch belt is ADJACENT to the junction, not on it, and every belt
    # attached to a splitter must be CO-LOCATED with it -- that is what the
    # corpus shows and what `junction.colocated` enforces. So the junction gets
    # a stub on its own tile which then runs out to the branch. This is exactly
    # the shape the game records: a splitter's port is a belt on the junction
    # tile, and the route starts from there.
    stub = canvas.add(
        replace(
            b,
            yaw=canvas.buildings[branch].yaw,
            input_obj=junction_idx,
            output_obj=branch,
        )
    )
    del stub  # linked by construction
    return True


# --- power -----------------------------------------------------------------


def _straight_to_edge(
    canvas: _Canvas, port: _Port, bounds: tuple[int, int, int, int]
) -> list[tuple[int, int, int]] | None:
    """A clear straight run from just outside the block to ``port``'s tile.

    Four directions are tried, nearest edge first, and the run must be clear the
    whole way -- a partial run is not a connection.  Returns the cells in FLOW
    order (edge first, lane last) or ``None`` when every direction is blocked,
    at which point the caller falls back to routing.
    """
    min_x, min_y, max_x, max_y = bounds
    options: list[list[tuple[int, int, int]]] = [
        [(x, port.y, 0) for x in range(min_x - 1, port.x)],
        [(x, port.y, 0) for x in range(max_x + 1, port.x, -1)],
        [(port.x, y, 0) for y in range(min_y - 1, port.y)],
        [(port.x, y, 0) for y in range(max_y + 1, port.y, -1)],
    ]
    clear = [
        cells
        for cells in options
        if cells and all(canvas.free(c) for c in cells)
    ]
    if not clear:
        return None
    return min(clear, key=len)


def _route_external_inputs(
    canvas: _Canvas,
    spec: BuildSpec,
    strip_in_ports: list[dict[str, _Port]],
    belt_id: int,
    belt_model: int,
    core: tuple[int, int, int, int],
) -> int:
    """Run every outside input from the block edge to the lane that wants it.

    Returns the number of lanes that could not be reached.

    Without this, an external input was just a lane wearing a marker icon.  On a
    packed build that lane is frequently WALLED IN -- above it another lane,
    below it the machine band, either side the lane itself -- so no belt could
    be run to it, by the router or by the player standing in front of it.  The
    icon said "connect here" pointing at a tile nothing can connect to.

    Routing to the boundary fixes three things at once: the lane is reachable,
    the marker now sits on a belt the player can actually see the end of, and
    the blueprint describes its own inputs instead of relying on the operator to
    work out which of forty belts is the iron-ore one.

    Belts flow INWARD here -- from the edge to the lane -- which is the opposite
    direction to every other net, so the path is committed head-first with the
    last belt feeding the lane.

    Runs terminate on the ENTRY RING, the outermost ring anything may occupy.
    That is what makes each of them reachable: nothing else can be placed
    further out, so a run's head is on the finished bounding box and has open
    ground on its outward side whatever the router does afterwards.  Running out
    to "one tile past the current edge" -- which is what this did -- put the head
    on a boundary that later passes moved, and the head then sat interior.
    """
    bounds = _grow(core, _ENTRY_RING - 1)
    min_x, min_y, max_x, max_y = bounds
    # The fallback search may travel ALONG the entry ring, which the straight
    # runs already use; a cell on the outermost ring cannot wall anything in,
    # because outward of it is ground no pass can reach.
    astar_bounds = _grow(core, _ENTRY_RING)
    # One ring outside the block: where the player's belt meets ours.
    edge = [
        (x, y, 0)
        for x in range(min_x - 1, max_x + 2)
        for y in (min_y - 1, max_y + 1)
    ] + [
        (x, y, 0)
        for y in range(min_y, max_y + 1)
        for x in (min_x - 1, max_x + 1)
    ]
    starts = [c for c in edge if canvas.free(c)]
    if not starts:
        return 0

    history: dict[tuple[int, int, int], float] = defaultdict(float)
    budget = {"left": _ROUTING_BUDGET}
    # Deduplicate: several strips of one group each want the same item, and each
    # of their lanes needs its own way in.
    # Keyed by LANE, not by item. `_seat_inputs` mixes two ingredients onto one
    # lane when they will not fit one-per-lane, and both then report the same
    # port. Routing per item would try to build a second run to a lane that
    # already has one, find the cell taken, and count a miss -- which is what
    # made the six-ingredient spec refuse outright. One lane needs one way in;
    # what travels on it is the marker pass's business.
    wanted: dict[int, _Port] = {}
    for ports in strip_in_ports:
        for item, port in sorted(ports.items()):
            if item in spec.external_inputs:
                wanted.setdefault(port.belt, port)
    carried = {
        port.belt: item
        for ports in strip_in_ports
        for item, port in sorted(ports.items(), reverse=True)
        if item in spec.external_inputs
    }
    missed = 0
    for belt, port in wanted.items():
        item = carried[belt]
        # Spend exactly ONE of this lane's access reservations and leave the
        # rest held. Every other port's stays held too, so bringing one input in
        # cannot wall another lane up -- measured as `belt:external` sitting on
        # the single open side of a lane head, on a canvas that had been clean a
        # moment earlier.
        #
        # Releasing rather than claiming (`routing_ports`) is the point: a lane
        # that also receives an internal net holds TWO cells, and claiming would
        # let one straight run take both. The internal net would then be handed
        # the empty goal set this exists to prevent.
        mine = next(
            (c for c, k in canvas.reserved.items() if k == (port.x, port.y)), None
        )
        if mine is not None:
            del canvas.reserved[mine]
        # Straight out to the edge first. A lane head sits on the west face of
        # its strip, so the run west along its own row is usually clear, costs
        # one belt per tile, and -- unlike a routed path -- cannot compete with
        # the other input lanes for the margin outside the block. That mattered:
        # routing six lanes of a six-ingredient strip through a two-tile margin
        # failed outright, while six parallel straight runs do not interact at
        # all. It is also what spine does, and for the same reason.
        path = _straight_to_edge(canvas, port, bounds)
        if path is None:
            goals = {
                (port.x + dx, port.y + dy, 0)
                for dx, dy in _STEPS
                if canvas.free((port.x + dx, port.y + dy, 0))
            }
            if not goals:
                missed += 1
                continue
            live = [c for c in starts if canvas.free(c)]
            path = _astar(canvas, live, goals, history, 1.0, astar_bounds, budget)
        if path is None:
            missed += 1
            continue
        indices: list[int] = []
        for x, y, lvl in path:
            if not canvas.free((x, y, lvl)):
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
                        carries_item=item,
                    )
                )
            )
        if not indices:
            missed += 1
            continue
        for a, b in zip(indices, indices[1:], strict=False):
            canvas.buildings[a] = _relink(canvas.buildings[a], output_obj=b)
        canvas.buildings[indices[-1]] = _relink(
            canvas.buildings[indices[-1]], output_obj=port.belt
        )
    return missed


def _nearest_free(canvas: _Canvas, cx: int, cy: int, limit: int) -> tuple[int, int] | None:
    """The closest cell to ``(cx, cy)`` nothing stands on, within ``limit``."""
    for r in range(limit + 1):
        for dx in range(-r, r + 1):
            for dy in (-r, r) if r else (0,):
                for a, b in ((cx + dx, cy + dy), (cx + dy, cy + dx)):
                    if canvas.free((a, b, 0)) and (a, b) not in canvas.solid:
                        return (a, b)
    return None


def _claim_power_sites(canvas: _Canvas, core: tuple[int, int, int, int]) -> list[tuple[int, int]]:
    """Hold a cell for every lattice point, BEFORE anything routes.

    Power is the last pass, and on a dense block "last" means "gets nothing".
    Every belt the router lays is a cell the lattice cannot use, and the coverage
    repair then searches a full tower radius and finds the ground solid:
    measured on ``casimir-crystal``, a matrix lab with 349 tiles inside range had
    four of them free, and thirteen buildings shipped unpowered -- a blueprint
    that pastes and then sits there.

    So the lattice claims its ground while the ground is still empty, and the
    router paths around one cell in eighty-one.  Only machines, sorters and
    coaters draw power, and all of those are inside ``core``, so the lattice is
    laid over the core rather than over the finished bounding box -- the entry
    ring holds nothing but belts, which are unpowered.
    """
    min_x, min_y, max_x, max_y = core
    half = TOWER_SPACING // 2
    sites: list[tuple[int, int]] = []
    y = min_y + half
    while y <= max_y + half:
        x = min_x + half
        while x <= max_x + half:
            spot = _nearest_free(canvas, x, y, 4)
            # Strictly inside the core. A lattice point near the east or south
            # face can be displaced onto the entry ring, and the ring belongs to
            # the input runs: a tower standing in one would break the straight
            # run out to it for no reason, when the machine it was covering has
            # the whole block to be covered from.
            if spot is not None and not (
                min_x <= spot[0] <= max_x and min_y <= spot[1] <= max_y
            ):
                spot = None
            if spot is not None:
                sites.append(spot)
                canvas.keep_out.add(spot)
            x += TOWER_SPACING
        y += TOWER_SPACING
    return sites


def _place_power(canvas: _Canvas, sites: Sequence[tuple[int, int]]) -> int:
    """Towers on the claimed lattice, then repaired until coverage really holds.

    The lattice spacing already guarantees coverage and connectivity in open
    ground; the repair passes exist because a claim can still fail -- a lattice
    point may have had no free cell within reach even before routing -- and a
    tower that could not be placed is exactly the kind of gap that would
    otherwise reach the game as a dead corner of the factory.
    """
    if not canvas.buildings:
        return 0
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

    for site in sites:
        try_place(*site)

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
        spot = _nearest_free(canvas, mx, my, 6)
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


def _pair_lanes(
    srcs: Sequence[_Port], sinks: Sequence[_Port]
) -> list[tuple[_Port, _Port]]:
    """Pair one item's producer lanes against its consumer lanes.

    Every reuse of a lane stays on that lane's END TILE.  Walking inward was
    tried and is worse: a mid-lane tile is WALLED IN -- lane either side,
    machines above, another lane below -- so the branch it was meant to serve has
    nowhere to leave from.  Measured on the free-proliferation chain: three of
    the five walled-in ports were taps this had moved, each with all four
    neighbours occupied on a clean canvas.

    Sharing the end tile is safe because ``_tap_source`` builds a junction there:
    the first net links directly, the second turns the link into a splitter, and
    further nets attach to it until the four sides run out -- at which point it
    reports the failure instead of mis-linking.

    Only the PRODUCER side is ever reused this way.  Walking the consumer lane
    inward was tried and is strictly worse: a strip's inner input lane is walled
    in the same way, and only the lane HEAD is reachable because its west
    neighbour lies outside the strip.  So several producers feeding one consumer
    lane cannot each reach it -- they converge instead, the first net routing to
    the head and the rest merging into that net's path, which is what belts do
    anyway.
    """
    return [
        (srcs[i], sinks[j])
        for i, j in _staircase(
            [p.machines for p in srcs], [p.machines for p in sinks]
        )
    ]


def _staircase(supply: Sequence[int], demand: Sequence[int]) -> list[tuple[int, int]]:
    """A CONNECTED pairing of producer lanes to consumer lanes, by machine count.

    Two properties, and the first is the one that makes ``flow.conservation``
    hold structurally rather than by luck.

    **Connected.**  ``flow.conservation``'s placement clause is a CUT argument:
    within every ISLAND an item can travel across, production must cover
    consumption.  A pairing that partitions the two sides into disjoint pairs
    partitions the item's flow graph into that many islands, and each island
    then has to balance on its own -- which a shard split cannot promise, since
    the shard sizes and the consumer sizes are two independent integer
    partitions of two different totals.  Measured on ``quantum-chip``: the
    four-machine ``titanium-glass`` shard was cyclically handed eleven of
    ``plane-filter``'s sixteen machines, needing 11/4 of a machine's output
    where seven machines covering sixteen can only reach 16/7.

    A staircase from ``(0, 0)`` to ``(n-1, m-1)`` uses ``n + m - 1`` pairs, which
    is the fewest that can connect ``n + m`` nodes, so there is exactly ONE
    island for the edge and the spec's own arithmetic decides it.  The cost is
    ``min(n, m) - 1`` extra nets, and only where BOTH sides have more than one
    lane -- when either side is a single lane the walk degenerates to exactly the
    cyclic pairing this replaces, so nothing that already worked pays anything.

    **Weighted.**  The step advances whichever side has fallen behind in
    MACHINES, so a shard with twice the machines is handed roughly twice the
    consumers.  Even round-robin was what let the imbalance above happen at all.

    **Capped.**  ``_MAX_LANE_TAPS`` bounds how many consumer lanes hang off one
    producer lane end: the splitter there has four sides and a fourth branch is
    refused, so the walk moves on to the next producer lane rather than build a
    tap ``_tap_source`` would reject.  Where the cap is arithmetically
    unreachable -- ``n + m - 1`` taps across ``n`` lanes can exceed it however
    they are dealt -- the walk spreads them evenly instead, which is the best
    any pairing can do and no worse than the round-robin it replaces.
    """
    n, m = len(supply), len(demand)
    if n == 0 or m == 0:
        return []

    def prefix(ws: Sequence[int]) -> list[int]:
        out, run = [], 0
        for w in ws:
            run += max(0, w)
            out.append(run)
        return out

    sup_pre, dem_pre = prefix(supply), prefix(demand)
    sup_tot = sup_pre[-1] or 1
    dem_tot = dem_pre[-1] or 1

    # The walk lays n + m - 1 taps across n producer lanes, so a cap below
    # their even share cannot be met by any dealing of them; take the larger.
    cap = max(_MAX_LANE_TAPS, -(-(n + m - 1) // n))

    i = j = 0
    taps = 1
    out = [(0, 0)]
    while i < n - 1 or j < m - 1:
        if j >= m - 1:
            advance_src = True
        elif i >= n - 1:
            advance_src = False
        else:
            advance_src = taps >= cap or (
                Fraction(sup_pre[i], sup_tot) <= Fraction(dem_pre[j], dem_tot)
            )
        if advance_src:
            i += 1
            taps = 1
        else:
            j += 1
            taps += 1
        out.append((i, j))
    return out


def _build(
    spec: BuildSpec,
    strips: list[Strip],
    pack: _Pack,
    *,
    power: bool,
    route: bool,
    claim_power: bool = True,
) -> tuple[Placement, int, int]:
    belt_id = BELT_ITEM_IDS.get(spec.belt_item_id, 2001)
    belt_model = catalog.building(belt_id).model_index
    canvas = _Canvas()

    rates: dict[str, Fraction] = {}
    for g in _adapt(spec).values():
        for item, r in list(g.inputs.items()) + list(g.outputs.items()):
            rates[item] = max(rates.get(item, Fraction(0)), r * g.count)

    # PER-ITEM per-machine rates, keyed by group. One sorter serves one machine
    # and moves one item, so that item's per-machine rate is exactly what the
    # sorter must sustain.
    #
    # This used to be the machine's TOTAL split evenly across its sorters, which
    # under-sizes whenever ingredient rates differ -- and they usually do.
    # `circuit-board` takes copper at 1/s and iron at 2/s; the 1.5/s average
    # exactly meets a Mk.I, so it read as clean while the sorter carrying the
    # iron starved the machine. The overloaded sorter hid behind the underloaded
    # one, and the validator averaged the same way so it never caught it.
    per_item: dict[str, tuple[Mapping[str, Fraction], Mapping[str, Fraction]]] = {
        key: (dict(g.inputs), dict(g.outputs)) for key, g in _adapt(spec).items()
    }

    # EVERY strip of a group keeps its port, not just the last one emitted.
    #
    # `out_lanes` names a destination GROUP, but a group is sharded into as many
    # strips as its machine count needs, and each shard carries its own input
    # lanes. Keying this by `(group_key, item)` alone let the second shard
    # overwrite the first, so exactly one shard became a net sink and every other
    # shard's lane was left orphaned -- belts in place, sorters in place, nothing
    # ever putting items onto them, and the machines behind them starving.
    #
    # It reported `route_failures == 0` throughout, because the nets that existed
    # did route; the missing ones were never created to fail.
    in_ports: dict[tuple[str, str], list[_Port]] = defaultdict(list)
    # The producer side collides the same way: sharding a producer gives several
    # strips the SAME destination set, so keying on (group, item, dest) alone
    # kept only the last strip's output lane. The others were emitted, drained by
    # nobody, and left as dead belts.
    out_ports: dict[tuple[str, str, str], list[_Port]] = defaultdict(list)
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
            *per_item.get(s.group_key, ({}, {})),
        )
        sorters += placed
        strip_in_ports.append(ins)
        for item, port in ins.items():
            in_ports[s.group_key, item].append(port)
        for (item, dest), port in outs.items():
            out_ports[s.group_key, item, dest].append(port)

    # Nets the packer arranged to bridge directly become a single sorter and no
    # belt route at all -- that saving IS the feature, so it happens before the
    # net list is built rather than as a post-pass over routed belts.
    direct_keys = {
        (strips[i].group_key, strips[j].group_key) for i, j in pack.direct
    }
    direct_placed = 0

    nets: list[_Net] = []
    for (src_key, item, dest_group), srcs in out_ports.items():
        # One output lane may serve SEVERAL destination groups -- see
        # `_merge_lanes` -- and each of them is its own set of consumer strips to
        # pair against. They all tap the same lane end, where `_tap_source`
        # builds the junction, exactly as it already does when ONE destination is
        # sharded across several consumer strips.
        for dest in _dests(dest_group):
            sinks = in_ports.get((dest, item), [])
            if not srcs or not sinks:
                continue
            for port, sink in _pair_lanes(srcs, sinks):
                if (src_key, dest) in direct_keys and _bridge(
                    canvas, port, sink, rates, item
                ):
                    direct_placed += 1
                    continue
                nets.append(_Net(src=port, dst=sink, item=item))

    # Hold one cell beside every port BEFORE anything else can take it.
    #
    # Coater drop belts and external input runs are placed onto a canvas that is
    # otherwise empty, so they take whatever cell suits them -- and a lane head's
    # only free neighbour is exactly the sort of cell that suits them. The net
    # that needed it is then handed an EMPTY goal set: A* returns None having
    # expanded nothing, and no amount of rip-up can negotiate for a cell that is
    # occupied by a building rather than contested by another path.
    #
    # Measured across the trivial+small+mid corpus, before this: every boxed-in
    # port on the refusing candidates had a coater drop or an external belt on
    # its one open side, and the boxed-in count equalled the failure count
    # exactly. `_route_all` re-derives these once every path is laid, so this is
    # a claim staked early rather than a second source of truth.
    def hold_ports() -> None:
        # A lane carrying an external ingredient AND an internally produced one
        # has two feeds to accept, not one, so it needs two ways in.
        net_ports = {(p.x, p.y) for n in nets for p in (n.src, n.dst)}
        shared_feed = {
            (port.x, port.y)
            for ports in strip_in_ports
            for item, port in ports.items()
            if item in spec.external_inputs
        } & net_ports
        _reserve_port_access(canvas, nets, twice=shared_feed)

    if route:
        hold_ports()

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
    coaters = len(coater_list)

    # THE EXTENT IS DECIDED HERE, and nothing after this point may move it.
    #
    # Every pass that follows -- the proliferator entry, the external input
    # runs, the router, the power lattice -- used to compute "the edge" for
    # itself, from a canvas the previous pass had just extended. Each was
    # correct about where the boundary was when it looked, and wrong by the time
    # the placement was finished; the entry tiles the validator reports as
    # walled in are precisely the ones that were on the boundary when placed.
    #
    # Reordering the passes cannot fix that, and two orderings were measured
    # proving it. Fixing the box can: the strips and their coaters define the
    # core, `_ENTRY_RING` rings of margin are reserved around it, and
    # `canvas.limit` refuses any cell beyond. The ring one further out is then
    # empty by construction, which is what makes an entry belt reachable from
    # outside no matter what else the router does.
    core = _core_bounds(canvas)
    canvas.limit = _grow(core, _ENTRY_RING)
    route_bounds = _grow(core, _ROUTE_RING)
    power_sites = _claim_power_sites(canvas, core) if power and claim_power else []

    # The proliferator entry is staked BEFORE the ports are held, not after the
    # external runs have settled. It can be: its cell is reserved ground that no
    # other pass can reach, so it no longer matters who runs first. Having its
    # nets exist at reservation time is what the previous ordering gave up --
    # the coater drops those nets sink into then went unheld, and the external
    # runs walled them in instead.
    if coater_list and prolif_item is not None:
        entry = _place_proliferator_entry(
            canvas, prolif_item, belt_id, belt_model, core
        )
        if entry is not None:
            nets.extend(
                _proliferator_nets(canvas, entry, coater_list, prolif_item)
            )

    # Again, now that every port exists -- strip lanes, coater drops and the
    # proliferator entry alike. A drop is a one-tile lane and the sink of a
    # proliferator net, so it is a port like any other, and it did not exist
    # when the first claim was staked.
    if route:
        hold_ports()

    # Bring the outside inputs in FIRST. They have no alternative: an internal
    # net can be routed around an obstacle, but an external lane can only be
    # reached from beyond the block, and a strip's inner lanes have exactly one
    # way in. Routing the internal nets first let them take those cells -- on
    # the graphene chain two external lanes were walled in by belts that had a
    # dozen other routes available. First claim goes to the side that has no
    # second choice.
    unreachable = 0
    if route:
        unreachable = _route_external_inputs(
            canvas, spec, strip_in_ports, belt_id, belt_model, core
        )

    routed, failed, iterations = (0, 0, 0)
    if route and nets:
        routed, failed, iterations = _route_all(
            canvas, nets, belt_id, belt_model, route_bounds
        )
    failed += unreachable

    # Port access reservations are spent once the last net is committed. Holding
    # them into the power pass costs coverage for nothing: a reserved cell reads
    # as occupied to `free`, so the tower that would have covered a machine
    # cannot be placed there, and the machine ships unpowered. That got sharply
    # worse once a port with two jobs began holding two cells -- twenty coater
    # drops became forty cells the lattice could not use, and the repair pass
    # then failed to cover fourteen buildings on a block with room to spare.
    canvas.reserved.clear()
    # Tentative path markers outlive the round that made them: the round that
    # succeeds commits and returns without clearing its own, and any cell
    # `_commit_paths` decided not to build on keeps a marker with no building
    # under it. `free` reads those as occupied, so the lattice treats empty
    # ground as taken.
    for cell in [c for c, owner in canvas.blocked.items() if owner == -2]:
        del canvas.blocked[cell]
    canvas.keep_out.clear()
    towers = _place_power(canvas, power_sites) if power else 0

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
    canvas: _Canvas, entry: _Port, coaters: list[_Coater], item: str
) -> list[_Net]:
    """Thread ONE belt from the entry through every coater drop in turn.

    Every coater needs the same item at a trivial rate (well under one item per
    second in total, against a belt that carries twelve), so one lane serves all
    of them and capacity never binds.

    Chained rather than fanned out, for two independent reasons.

    Routing each drop separately from the entry costs far more: eleven paths all
    radiating from one corner roughly doubled the bounding box.

    And a fan-out cannot be built without splitters, which is worse than
    expensive.  A branch drawn off a splitter is a belt run of its own, fed by
    the junction rather than by a belt, and nothing inside the blueprint fills
    it -- so every branch reads as a separate lane the player must belt
    proliferator into, buried in the middle of the block where no belt can
    reach.  Measured: fanning out turned one entry lane into twenty unreachable
    ones across the corpus.  A chain has no junctions at all; it is a single
    linear run that starts at the entry belt, out on the reserved ring where the
    player can get to it.

    Nearest-neighbour order keeps each hop short, and a hop of length one is
    LINKED RATHER THAN ROUTED.  Two coaters on neighbouring lanes of one strip
    put their drops in the same margin column, one directly above the other, and
    the lower one then has a single free neighbour in the world -- the margin is
    one tile wide, the lane is west of it and a machine south.  A chain needs two
    ways into such a drop, one for the hop arriving and one for the hop leaving,
    and there is only ever one: whichever hop routed first took it and the other
    was handed an empty goal set.  Linking the pair directly costs no cell at
    all and leaves each of them needing exactly one.
    """
    remaining = list(coaters)
    src = entry
    nets: list[_Net] = []
    while remaining:
        nxt = min(remaining, key=lambda c: abs(c.x - src.x) + abs(c.y - src.y))
        remaining.remove(nxt)
        dst = _Port(nxt.drop, nxt.x, nxt.y, nxt.x, nxt.x)
        if abs(nxt.x - src.x) + abs(nxt.y - src.y) == 1:
            canvas.buildings[src.belt] = _relink(
                canvas.buildings[src.belt], output_obj=dst.belt
            )
        else:
            nets.append(_Net(src=src, dst=dst, item=item))
        src = dst
    return nets


def _place_proliferator_entry(
    canvas: _Canvas,
    item: str,
    belt_id: int,
    belt_model: int,
    core: tuple[int, int, int, int],
) -> _Port | None:
    """The block's proliferator input belt, on the reserved entry ring.

    A single entry tile: the router fans out from here to each coater's drop,
    and DSP belts merge natively, so no splitter is needed.

    It goes on the NORTH-WEST CORNER of the entry ring, and the corner is the
    point.  Nothing else can ever be placed further out -- the router and the
    power lattice are held inside ``_ROUTE_RING`` and the external input runs
    stop on the entry ring itself -- so this tile is on the finished block's
    bounding box in two directions at once and has open ground beside it by
    construction.  It used to be placed one tile west of wherever the buildings
    happened to reach at that moment, which was the boundary right up until the
    next pass moved it; the tile then sat interior, walled in on four sides,
    with an icon on it telling the player to belt proliferator into somewhere
    they cannot reach.

    A corner also keeps it clear of the straight input runs, which leave along
    strip rows and columns and so never use one.
    """
    x, y = core[0] - _ENTRY_RING, core[1] - _ENTRY_RING
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


def _fanout_shortfall(strips: list[Strip]) -> list[str]:
    """Producer lanes with fewer tiles than the consumers they must tap.

    ``_build`` pairs the two sides of an edge cyclically -- ``srcs[k % len(srcs)]``
    against ``sinks[k % len(sinks)]`` -- so whichever side is sharded further is
    fully served.  More sinks than sources means a producer lane is reused, and
    each reuse taps a different tile of that lane and junctions there.

    That works right up to the point where the lane runs out of tiles: two taps
    on one tile would need two splitters on one square.  A lane is as wide as
    its strip, so this is rare -- but it is a property of the STRIP PLAN, decided
    before any packing exists, and worth knowing before the height sweep rather
    than after.  A spec that trips it refuses at every height and every budget,
    and each attempt costs a full sweep plus the retry at
    :data:`RETRY_BUDGET_S`.

    Returns one description per offending edge, empty when the plan is servable.
    """
    src_lanes: dict[tuple[str, str, str], int] = defaultdict(int)
    src_tiles: dict[tuple[str, str, str], int] = {}
    sink_lanes: dict[tuple[str, str], int] = defaultdict(int)
    for s in strips:
        for item, dest in s.out_lanes:
            for d in _dests(dest):
                key = (s.group_key, item, d)
                src_lanes[key] += 1
                src_tiles[key] = min(src_tiles.get(key, s.width), s.width)
        for item in s.in_lanes:
            sink_lanes[s.group_key, item] += 1

    out: list[str] = []
    for (src_key, item, dest), n_src in sorted(src_lanes.items()):
        n_sink = sink_lanes.get((dest, item), 0)
        if n_sink <= n_src:
            continue
        # Taps land on the narrowest lane of the group, so that is the one that
        # can run out. Ceiling division: the reuse is spread round-robin.
        per_lane = -(-n_sink // n_src)
        tiles = src_tiles[src_key, item, dest]
        if per_lane > tiles:
            out.append(
                f"{item}: {src_key} lane is {tiles} tile(s) wide but must tap "
                f"{per_lane} consumer lane(s) of {dest}"
            )
    return out


def fallback_placement(spec: BuildSpec, *, power: bool = True) -> Placement:
    """One strip per group, stacked vertically.  NOT a usable layout.

    It cannot fail to *construct*, which is a different and much weaker property
    than the "always valid" it was once documented with.  It calls
    ``_build(route=False)``: it never attempts the wiring, so it cannot report
    that the wiring is impossible, and on real specs it is not routable.  That
    is why :class:`FreeformLayout` no longer falls back to it -- returning it
    when the solver found nothing returned a smaller *broken* layout in place of
    an honest refusal.

    Kept only because :mod:`flab2bp.layout.packsolver`, the rejected
    PackingSolver experiment, still calls it.  Do not add callers; if you want
    the construction for its bounding value, use :func:`_greedy_pack`, which is
    what :func:`_pack` warm-starts from.
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
        """Return the densest ROUTABLE ``Placement``, or raise :class:`NoValidLayout`.

        Routability is a condition for existing, not a ranking key.  It used to
        be the latter -- packs were ordered ``(routable, area, belt_tiles)`` and
        the least-bad one was returned even when every height failed to wire --
        which meant a pack nothing could connect still came back, still got
        measured, and measured *small*: an unrouted net is a belt run that does
        not exist, so the broken pack has the tighter bounding box and wins.
        That is how a build with 119 unrouted nets scored as the densest
        candidate on offer.

        The old escape hatch, :func:`fallback_placement`, is gone from this path.
        It was documented as routable by construction and is not -- it calls
        ``_build(route=False)``, so it never even attempts the wiring it claims.
        On the calibration spec it returned 3162 tiles against the solver's 2208
        while carrying the same unsourced lanes, so it traded area away for
        nothing.  What replaces it is the shelf packing it was built on, handed
        to :func:`_pack` as a warm start: same construction, bounding the search
        instead of substituting for it.

        A sweep that produces no routable pack is retried ONCE at
        :data:`RETRY_BUDGET_S` before refusing.
        """
        if time_budget_s <= 0:
            raise NoValidLayout(
                "no time budget was given, so the packer was never asked",
                spec_label=spec.label,
                budget_s=time_budget_s,
            )

        try:
            strips = plan_strips(spec, strip_len=self.strip_len)
        except (ValueError, KeyError) as exc:
            # One retry with every machine of a group on a single strip. That is
            # the coarsest legal strip plan, so if it also fails the spec cannot
            # be turned into strips at all and no budget will change that.
            try:
                strips = plan_strips(spec, strip_len=max(1, spec.machine_count))
            except (ValueError, KeyError):
                raise NoValidLayout(
                    f"the spec cannot be split into strips: {exc}",
                    spec_label=spec.label,
                    budget_s=time_budget_s,
                ) from exc
        if not strips:
            raise NoValidLayout(
                "the spec contains no machine groups",
                spec_label=spec.label,
                budget_s=time_budget_s,
            )

        # Refuse a strip plan that no packing can serve BEFORE sweeping heights.
        # This is not an optimisation of the failure path, it is the difference
        # between an error that names the cause and one that blames the packer:
        # the sweep would try every height, retry the lot at RETRY_BUDGET_S, and
        # report "left nets unrouted" -- 51s on the magnetic-ring chain to
        # rediscover something fixed the moment the strips were planned.
        #
        # Fan-out itself is no longer a shortfall: a lane serving several
        # consumers taps a different tile for each and junctions there. What
        # remains unservable is a lane with fewer TILES than taps to make, since
        # two taps on one tile would need two splitters on one square.
        shortfall = _fanout_shortfall(strips)
        if shortfall:
            raise NoValidLayout(
                "a producer lane has fewer tiles than the consumers it must tap, "
                "so two junctions would have to share one tile. " + "; ".join(shortfall[:3]),
                spec_label=spec.label,
                budget_s=0.0,
            )

        budgets = [time_budget_s]
        if time_budget_s < RETRY_BUDGET_S:
            budgets.append(RETRY_BUDGET_S)

        for budget in budgets:
            best = self._sweep(spec, strips, budget)
            if best is not None:
                return best

        raise NoValidLayout(
            f"no packing of {len(strips)} strips could be wired at any candidate "
            "height; every pack the sweep produced left nets unrouted",
            spec_label=spec.label,
            budget_s=budgets[-1],
        )

    def _sweep(
        self, spec: BuildSpec, strips: list[Strip], time_budget_s: float
    ) -> Placement | None:
        """Try every candidate height, returning the best FULLY ROUTED placement.

        ``None`` means no height produced one -- which is a refusal, not a
        degraded answer.  Packs with unrouted nets are discarded here rather than
        ranked below routed ones, so an unwireable pack can never be what this
        returns.

        ``time_budget_s`` bounds the WHOLE sweep, not just CP-SAT.  It used to
        bound only the packing: routing is limited by an expansion count, not a
        clock, so a 1s budget could spend 13.5s and a 4s budget 68.6s -- both on
        specs that then refused.  A caller who says one second and waits over a
        minute has not been given a budget, and the bake-off cannot sweep a
        parameter the code ignores.

        The deadline is checked between heights rather than inside them: a
        half-routed pack is not a result, so interrupting one wastes the work
        without producing anything.  Whatever has already been found is
        returned, which is why the heights most likely to pay off are tried
        first.
        """
        candidates = _direct_insert_candidates(spec)
        greedy = _greedy_pack(strips, _height_seed(strips))
        bound = max(greedy.width, max((s.width + MARGIN for s in strips), default=1))
        net_candidates = (
            _direct_net_candidates(strips, spec) if self.direct_insert else {}
        )

        heights = _candidate_heights(strips)
        per_solve = max(0.1, time_budget_s / max(len(heights), 1))
        deadline = time.monotonic() + time_budget_s

        best: Placement | None = None
        best_key: tuple[int, float] | None = None
        for height in heights:
            # The deadline stops us IMPROVING, never FINDING. A refusal means
            # the model could not lay the spec out; a clock must not be able to
            # manufacture one. Breaking on time alone did exactly that: heights
            # are tried shortest-first and the free-proliferation chain only
            # wires at the tallest, so a 2s budget refused a spec that routes
            # every net cleanly given the chance to reach it.
            if best is not None and time.monotonic() >= deadline:
                break
            pack = _pack(
                strips,
                height=height,
                width_bound=max(bound * 2, 8),
                time_budget_s=per_solve,
                direct_candidates=net_candidates,
                workers=self.workers,
                seed=_greedy_pack(strips, height),
            )
            if pack is None:
                continue
            placement, failed, _towers = _build(
                spec, strips, pack, power=self.power, route=True
            )
            if 0 < failed <= _POWER_RETRY_NETS and self.power:
                # The power lattice claims its ground before the router runs,
                # because taking what is left over on a dense block means taking
                # nothing. Sometimes what it took was the one corridor a net
                # needed. Preferring a covered pack and ACCEPTING an uncovered
                # one is the right order: a build that cannot be wired is worth
                # nothing, and coverage still has its repair pass to fall back
                # on. Only a height that already failed pays for the retry, and
                # only one that failed by a few nets: a pack that leaves thirty
                # nets unrouted is not failing over one tower, and paying a
                # second full build to find that out doubled the cost of every
                # refusal on the stress tier.
                placement, failed, _towers = _build(
                    spec, strips, pack, power=self.power, route=True, claim_power=False
                )
            if failed:
                continue
            # Area, then belt count. Two packs of equal area are not equally
            # good: the one with fewer belt tiles is fewer buildings to paste,
            # and a direct insert shows up here as exactly that. Without the
            # second key, ties fell to whichever height the sweep tried first,
            # which silently discarded direct-inserted packs.
            key = (placement.area, float(placement.stats["belt_tiles"]))
            if best_key is None or key < best_key:
                placement.stats["solver_status"] = 1.0 if pack.status == "OPTIMAL" else 0.5
                placement.stats["hit_time_budget"] = float(pack.hit_budget)
                placement.stats["fallback_used"] = 0.0
                placement.stats["direct_insert_candidates"] = float(len(candidates))
                placement.stats["area"] = float(placement.area)
                best, best_key = placement, key
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
