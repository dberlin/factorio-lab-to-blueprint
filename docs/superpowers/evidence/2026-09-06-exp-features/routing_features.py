"""A routing-difficulty feature vector computable BEFORE any placement runs.

The dispatch question the orchestrator design (§3 of
``docs/superpowers/specs/2026-09-06-multi-solver-orchestrator-design.md``) has
to answer is *which placer, at what budget, for this spec* -- and it has to
answer it without paying for a layout to find out.  Everything here is derived
from a solved :class:`~flab2bp.spec.BuildSpec` plus the strip plan, both of
which the pipeline computes anyway and both of which are cheap: a full corpus
sweep of these features is seconds, against minutes for one layout cell.

THE HYPOTHESIS THIS MODULE ENCODES

The user's framing, verbatim:

    "The ingredients that appear in the most positions are the ones that will
    be hardest to route.  If you have to get copper ingot to 6 or 7 different
    parts of the same production block (early and late pieces), that is a lot
    more difficult to route than something that starts off with magnet and
    immediately uses it."

Two things are being claimed, and they are separable.  *Fan-out* -- how many
consumers an item has -- the router already knows about: `_route_all` orders
nets fan-out-first.  *Depth span* -- how far apart in the chain those consumers
sit -- it does not: the router has no topological notion at all, so an item
consumed at depth 1 and again at depth 7 is, to it, just two more nets.  Span
is the part of the idea that is new information, so ``spread`` multiplies the
two rather than reporting either alone: an item with six consumers all in one
layer is a wide but *local* bus, and an item with two consumers eight layers
apart is a long thin one.  Both are harder than magnet-into-coil; neither is
what raw fan-out measures.

WHY DEPTH IS PER-GROUP AND NOT PER-ITEM

An item's own depth says where it is *made*.  What routing pays for is where it
is *used*, so a consumer's depth is the depth of the consuming group, and
``span`` is the spread of those consumer depths.  Copper ingot made once at
depth 1 and eaten at depths 1, 2 and 6 has span 5 -- five layers of block to
cross -- even though its own depth never changes.

CYCLES

DSP's oil chain is genuinely cyclic (refined oil and hydrogen produce each
other), so a naive longest-path walk does not terminate.  Back edges are cut at
0 rather than raising: a cycle is a real spec the placer must still handle, and
a feature vector that refuses to score it would be useless exactly where the
MILP does its most interesting work.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING, Any

from flab2bp.spec import BuildSpec

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters for typing
    from flab2bp.layout.freeform import Strip

#: Items whose id starts with this are the proliferator sprays.  Called out
#: separately because on an ``all-products`` spec the spray is, by
#: construction, the widest item in the block: every proliferated group eats
#: it, at every depth.  Left inside the ordinary aggregates it would swamp
#: them, so it is reported both ways.
PROLIFERATOR_PREFIX = "proliferator"

#: What ``plan_strips`` is asked for.  Matches the production call sites in
#: ``freeform.py`` and ``sequence_solver.py`` so the strip count here is the
#: strip count a placer would actually be handed.
STRIP_LEN = 6


@dataclass(frozen=True, slots=True)
class ItemProfile:
    """One item's routing shape: how many places want it, and how far apart."""

    item_id: str
    #: Groups that consume this item.
    consumers: int
    #: Groups that produce it.  Zero means it arrives on an external belt.
    producers: int
    #: Depth of the shallowest and deepest consuming group; ``-1`` when nothing
    #: consumes the item (a final output or a pure surplus).
    earliest_consumer_depth: int
    latest_consumer_depth: int
    #: Whether the item also arrives at the block boundary.
    external: bool

    @property
    def span(self) -> int:
        """Chain layers between the earliest and latest consumer."""
        if self.consumers == 0:
            return 0
        return self.latest_consumer_depth - self.earliest_consumer_depth

    @property
    def spread(self) -> int:
        """``consumers * span`` -- the user's "many positions, far apart".

        Deliberately zero for a one-consumer item and for an item whose
        consumers all sit in one layer: neither is the shape the hypothesis is
        about, and keeping fan-out visible separately (``consumers``) means
        nothing is lost by making this term strict.
        """
        return self.consumers * self.span

    def as_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "consumers": self.consumers,
            "producers": self.producers,
            "earliest_consumer_depth": self.earliest_consumer_depth,
            "latest_consumer_depth": self.latest_consumer_depth,
            "span": self.span,
            "spread": self.spread,
            "external": self.external,
        }


@dataclass(frozen=True, slots=True)
class RoutingFeatures:
    """The dispatch key candidate: one spec in, one flat vector out."""

    # -- size, the things a dispatcher would reach for first --------------
    machines: int
    groups: int
    recipes: int
    strips: int
    distinct_items: int

    # -- strip shape ------------------------------------------------------
    max_ingredients_per_strip: int
    mean_ingredients_per_strip: float

    # -- belt pressure ----------------------------------------------------
    coaters: int
    items_above_one_belt: int
    both_fed_items: int

    # -- topology, the part the router does not currently see -------------
    chain_depth: int
    max_spread: int
    sum_spread: int
    max_consumers: int
    items_with_3plus_consumers: int
    top_spread: tuple[tuple[str, int], ...]

    # -- the spray, separately, because it dominates all-products ---------
    proliferator_consumers: int
    proliferator_span: int
    proliferator_spread: int

    # -- and the same aggregates with the spray taken out -----------------
    max_spread_no_prolif: int
    sum_spread_no_prolif: int

    items: tuple[ItemProfile, ...]

    def as_dict(self) -> dict[str, Any]:
        """Flat, JSON-safe, ``items`` last so a row stays readable."""
        return {
            "machines": self.machines,
            "groups": self.groups,
            "recipes": self.recipes,
            "strips": self.strips,
            "distinct_items": self.distinct_items,
            "max_ingredients_per_strip": self.max_ingredients_per_strip,
            "mean_ingredients_per_strip": round(self.mean_ingredients_per_strip, 4),
            "coaters": self.coaters,
            "items_above_one_belt": self.items_above_one_belt,
            "both_fed_items": self.both_fed_items,
            "chain_depth": self.chain_depth,
            "max_spread": self.max_spread,
            "sum_spread": self.sum_spread,
            "max_consumers": self.max_consumers,
            "items_with_3plus_consumers": self.items_with_3plus_consumers,
            "top_spread": [list(pair) for pair in self.top_spread],
            "proliferator_consumers": self.proliferator_consumers,
            "proliferator_span": self.proliferator_span,
            "proliferator_spread": self.proliferator_spread,
            "max_spread_no_prolif": self.max_spread_no_prolif,
            "sum_spread_no_prolif": self.sum_spread_no_prolif,
            "items": [item.as_dict() for item in self.items],
        }


def group_depths(spec: BuildSpec) -> tuple[int, ...]:
    """Longest-path depth of every group, aligned with ``spec.groups``.

    Depth 0 is a group all of whose ingredients arrive from outside the block
    (or that has no ingredients at all).  Otherwise a group sits one layer
    below its deepest ingredient.  Back edges through a production cycle
    contribute 0, so the oil chain scores as the shallow thing it physically
    is rather than diverging.
    """
    producers: dict[str, list[int]] = {}
    for index, group in enumerate(spec.groups):
        for item_id in group.outputs_per_machine:
            producers.setdefault(item_id, []).append(index)

    memo: dict[int, int] = {}
    on_stack: set[int] = set()

    def depth(index: int) -> int:
        cached = memo.get(index)
        if cached is not None:
            return cached
        if index in on_stack:
            # A back edge.  Cut it at 0; see the module docstring on cycles.
            return 0
        on_stack.add(index)
        best = 0
        for item_id in spec.groups[index].inputs_per_machine:
            for producer in producers.get(item_id, ()):
                if producer == index:
                    continue
                best = max(best, depth(producer) + 1)
        on_stack.discard(index)
        memo[index] = best
        return best

    return tuple(depth(index) for index in range(len(spec.groups)))


def item_profiles(spec: BuildSpec) -> tuple[ItemProfile, ...]:
    """Every item the block moves, with its consumer count and depth span.

    Sorted by descending spread then item id, so ``top_spread`` is just a
    prefix and two runs of the same spec cannot disagree about ties.
    """
    depths = group_depths(spec)
    consumer_depths: dict[str, list[int]] = {}
    producer_count: dict[str, int] = {}
    for index, group in enumerate(spec.groups):
        for item_id in group.inputs_per_machine:
            consumer_depths.setdefault(item_id, []).append(depths[index])
        for item_id in group.outputs_per_machine:
            producer_count[item_id] = producer_count.get(item_id, 0) + 1

    seen: set[str] = set(consumer_depths) | set(producer_count)
    seen |= set(spec.external_inputs) | set(spec.outputs) | set(spec.surplus_outputs)

    profiles = []
    for item_id in sorted(seen):
        depths_here = consumer_depths.get(item_id, [])
        profiles.append(
            ItemProfile(
                item_id=item_id,
                consumers=len(depths_here),
                producers=producer_count.get(item_id, 0),
                earliest_consumer_depth=min(depths_here) if depths_here else -1,
                latest_consumer_depth=max(depths_here) if depths_here else -1,
                external=item_id in spec.external_inputs,
            )
        )
    return tuple(sorted(profiles, key=lambda p: (-p.spread, p.item_id)))


def lane_capacity(spec: BuildSpec) -> Fraction:
    """Items per second the FASTEST belt the save can build carries.

    The fastest tier, not the floor: ``layout/belt_tiers.py`` raises a run to
    the cheapest tier that carries its demand, so an item is only genuinely
    "above one belt" when the best available belt still cannot hold it.  This
    is the same threshold the validator's ``flow.belt_capacity`` finding uses,
    which is what makes the count comparable to a refusal reason.
    """
    best = max(tier.items_per_second for tier in spec.belt_tiers)
    return best * spec.belt_stack


def items_above_one_belt(spec: BuildSpec) -> tuple[str, ...]:
    """Items whose block-wide flow cannot fit on a single best-tier belt.

    Flow is the larger of what the block makes and what it eats, because
    either side can be the one that needs splitting.
    """
    capacity = lane_capacity(spec)
    produced: dict[str, Fraction] = {}
    consumed: dict[str, Fraction] = {}
    for group in spec.groups:
        for item_id, rate in group.outputs_per_machine.items():
            produced[item_id] = produced.get(item_id, Fraction(0)) + rate * group.count
        for item_id, rate in group.inputs_per_machine.items():
            consumed[item_id] = consumed.get(item_id, Fraction(0)) + rate * group.count
    for item_id, rate in spec.external_inputs.items():
        produced[item_id] = max(produced.get(item_id, Fraction(0)), rate)

    over = {
        item_id
        for item_id in set(produced) | set(consumed)
        if max(produced.get(item_id, Fraction(0)), consumed.get(item_id, Fraction(0))) > capacity
    }
    return tuple(sorted(over))


def both_fed_items(spec: BuildSpec) -> tuple[str, ...]:
    """Items that arrive on an external belt AND are made inside the block.

    Two supplies for one demand is the case that forces the planner to seat a
    lane reachable from both sides; ``strip_variants`` has a whole seating rule
    for it (``_seat_both_fed_outermost``), which is why it is worth a feature.
    """
    produced = {item_id for group in spec.groups for item_id in group.outputs_per_machine}
    return tuple(sorted(produced & set(spec.external_inputs)))


def strip_shape(strips: Sequence[Strip]) -> tuple[int, int, float]:
    """``(count, max ingredients on any strip, mean ingredients per strip)``.

    Ingredients are DISTINCT input items reaching the strip from either side.
    Lane count would double-count an item split across two lanes, and it is the
    number of different things that have to arrive that makes a strip's local
    routing hard, not how many belts they came in on.
    """
    if not strips:
        return 0, 0, 0.0
    counts = [
        len({item for lane in (*strip.in_above, *strip.in_below) for item in lane})
        for strip in strips
    ]
    return len(strips), max(counts), sum(counts) / len(counts)


def plan_strips_for(spec: BuildSpec) -> list[Strip]:
    """The strip plan a placer would receive, with no placer run.

    Imported lazily: ``freeform`` is a large module and the graph half of this
    file is useful (and unit-testable) without it.
    """
    from flab2bp.layout.band_policy import BandPolicy
    from flab2bp.layout.freeform import plan_strips

    return plan_strips(spec, strip_len=STRIP_LEN, band_policy=BandPolicy("portable"))


def proliferator_profile(spec: BuildSpec) -> ItemProfile:
    """The spray's routing shape -- which the RECIPE GRAPH does not contain.

    This was the experiment's first surprise, and it is worth stating plainly:
    proliferator is never an ingredient.  It reaches machines through
    ``spray_lanes`` and a belt-mounted coater, so it appears in
    ``external_inputs`` and in nobody's ``inputs_per_machine``, and the ordinary
    :func:`item_profiles` walk therefore scores the widest item on every
    ``all-products`` spec as spread 0.

    The physical demand is real all the same: one coater per sprayed lane, each
    needing spray belted to it.  So the spray's "consumers" are the sprayed
    lanes, and its depth span is measured over those lanes' earliest consuming
    group -- the layer of the block each coater has to sit in.  On a spec with
    no spray this is an empty profile, which is exactly right.
    """
    spray_item = next(
        (item for item in sorted(spec.external_inputs) if item.startswith(PROLIFERATOR_PREFIX)),
        PROLIFERATOR_PREFIX,
    )
    if not spec.spray_lanes:
        return ItemProfile(
            item_id=spray_item,
            consumers=0,
            producers=0,
            earliest_consumer_depth=-1,
            latest_consumer_depth=-1,
            external=spray_item in spec.external_inputs,
        )
    by_item = {profile.item_id: profile for profile in item_profiles(spec)}
    lane_depths = [
        by_item[item].earliest_consumer_depth
        for item in spec.spray_lanes
        if item in by_item and by_item[item].consumers > 0
    ]
    if not lane_depths:
        lane_depths = [0]
    return ItemProfile(
        item_id=spray_item,
        consumers=len(spec.spray_lanes),
        producers=0,
        earliest_consumer_depth=min(lane_depths),
        latest_consumer_depth=max(lane_depths),
        external=spray_item in spec.external_inputs,
    )


def routing_features(
    spec: BuildSpec,
    *,
    strips: Sequence[Strip] | None = None,
) -> RoutingFeatures:
    """Score one spec.  Pass ``strips`` to reuse a plan the caller already has."""
    planned = plan_strips_for(spec) if strips is None else list(strips)
    strip_count, max_ing, mean_ing = strip_shape(planned)
    profiles = item_profiles(spec)
    depths = group_depths(spec)
    spray = proliferator_profile(spec)
    plain = [p for p in profiles if not p.item_id.startswith(PROLIFERATOR_PREFIX)]

    return RoutingFeatures(
        machines=sum(group.count for group in spec.groups),
        groups=len(spec.groups),
        recipes=len({group.recipe_id for group in spec.groups}),
        strips=strip_count,
        distinct_items=len(profiles),
        max_ingredients_per_strip=max_ing,
        mean_ingredients_per_strip=mean_ing,
        coaters=len(spec.spray_lanes),
        items_above_one_belt=len(items_above_one_belt(spec)),
        both_fed_items=len(both_fed_items(spec)),
        chain_depth=max(depths) if depths else 0,
        max_spread=max((p.spread for p in profiles), default=0),
        sum_spread=sum(p.spread for p in profiles),
        max_consumers=max((p.consumers for p in profiles), default=0),
        items_with_3plus_consumers=sum(1 for p in profiles if p.consumers >= 3),
        top_spread=tuple((p.item_id, p.spread) for p in profiles[:3]),
        proliferator_consumers=spray.consumers,
        proliferator_span=spray.span,
        proliferator_spread=spray.spread,
        max_spread_no_prolif=max((p.spread for p in plain), default=0),
        sum_spread_no_prolif=sum(p.spread for p in plain),
        items=profiles,
    )


def feature_row(
    spec: BuildSpec,
    *,
    key: Mapping[str, Any],
    strips: Sequence[Strip] | None = None,
) -> dict[str, Any]:
    """One ``features.jsonl`` line: identity keys first, then the vector."""
    row = dict(key)
    row.update(routing_features(spec, strips=strips).as_dict())
    return row
