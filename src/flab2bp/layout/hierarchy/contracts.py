"""The lane contract between two solved blocks.

A ``Cut`` (``hierarchy.partition``) names an item and a net rate crossing from
one block to another, but that is not enough to wire a belt: each block sizes
its own lanes independently from its own rates, and they do not agree in count
or in per-lane rate (README ``2026-09-06-exp-hierarchical`` section 1, "The
block interface is a LANE CONTRACT, not an item name" -- on ``zurl2``, ten of
eleven point-to-point cuts fail on lane-count mismatch alone).

This module turns a cut into the thing a router actually needs: an exact
transportation assignment from the producing block's rated output tails to the
consuming block's rated entry heads. Fan-out (one tail feeding several heads)
and fan-in (several tails filling one head) are both legal -- the composer
(``hierarchy.compose``, Task 5) treats a shared source port as one family of
taps and merges a second feed into an existing lane, so a ``LaneFlow`` is
simply one edge of the assignment, not a claim that one tail wires one head.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction

from flab2bp.layout import markers
from flab2bp.layout.base import Placement
from flab2bp.layout.buildings import Buildings
from flab2bp.layout.hierarchy.partition import Cut
from flab2bp.spec import BuildSpec


@dataclass(frozen=True)
class LaneEnd:
    """One rated lane at a block's boundary."""

    block: int  # block index in the composed order
    building: int  # belt index INSIDE the block's own placement
    item: str
    rate: Fraction  # what this lane carries (tail) or wants (head)


@dataclass(frozen=True)
class LaneFlow:
    """One edge of the transportation assignment between two blocks' lanes."""

    item: str
    src: LaneEnd  # a tail on the producing block
    dst: LaneEnd  # a head on the consuming block
    rate: Fraction


class ContractError(ValueError):
    """A consuming block's entry lane cannot be filled from what is offered."""


def _machines_behind(buildings: Buildings, strip: int) -> int:
    """Production machines (not belts, sorters, or splitters) in one strip.

    A machine building is the only kind that carries a real recipe, so
    ``recipe_id != 0`` picks it out.  Reapply that exact predicate over the
    indexed owner-strip bucket: the Buildings kind bucket is deliberately
    coarser and also contains power nodes and belt addons.
    """
    records = buildings.all()
    return sum(1 for i in buildings.by_owner_strip(strip) if records[i].recipe_id != 0)


def _machines_on_lane(buildings: Buildings, index: int, *, puts_on: bool) -> int:
    """Machines docked on the run through lane ``index``.

    Drive from the run's belts into their incident sorter buckets rather than
    scanning every building once per boundary lane.
    """
    run = buildings.belt_run(index, forward=not puts_on, through_any_host=True)
    records = buildings.all()
    machines: set[int] = set()
    for belt in run:
        sorters = buildings.sorters_into(belt) if puts_on else buildings.sorters_out_of(belt)
        for sorter_index in sorters:
            sorter = records[sorter_index]
            machine = sorter.input_obj if puts_on else sorter.output_obj
            candidate = buildings.by_index(machine)
            if machine is not None and candidate is not None and candidate.recipe_id != 0:
                machines.add(machine)
    return len(machines)


def _apportion(
    total: Fraction,
    buildings: Buildings,
    indices: list[int],
    *,
    puts_on: bool = True,
) -> list[Fraction]:
    """Split ``total`` across ``indices``' lanes, sum preserved exactly.

    A lane's share is the share of the block's machines standing behind it, and
    there are two records of that.  ``owner_strip`` is the precise one and is
    used whenever EVERY lane in the group carries it.  A freeform block's
    boundary belts are router trunks and carry none, which used to send the
    whole group to an EVEN split -- a split that is fiction whenever the lanes
    are not equally backed, and fiction with a consequence: ``assign_lanes``
    builds the transportation assignment on these rates, ``compose`` realises
    exactly that bipartite structure in belt, and ``flow.conservation`` then
    convicts the component whose promised rate exceeds the machines actually
    wired into it.  So the fallback is the machines DOCKED on each lane's belt
    run instead, which no router pass erases.

    Only when neither record yields a weight -- no strips and no docked
    machines -- is the split even.  Giving one lane weight 0 would zero-rate a
    real lane, and a zero-rated entry head is one the assignment never feeds,
    which the validator convicts as unfed.  Every branch is exact ``Fraction``
    arithmetic, so the parts always sum back to ``total``.
    """
    n = len(indices)
    records = buildings.all()
    weights: list[int]
    if any(records[i].owner_strip is None for i in indices):
        weights = [_machines_on_lane(buildings, i, puts_on=puts_on) for i in indices]
    else:
        weights = []
        for i in indices:
            strip = records[i].owner_strip
            assert strip is not None  # every lane checked above
            weights.append(_machines_behind(buildings, strip))
    total_weight = sum(weights)
    if total_weight == 0:
        return [total / n for _ in range(n)]
    return [total * Fraction(w, total_weight) for w in weights]


def boundary_lanes(
    placement: Placement, sub: BuildSpec, block: int
) -> tuple[list[LaneEnd], list[LaneEnd]]:
    """(output tails, entry heads) of one solved block, rated.

    ``markers.output_belt_tails`` owns exposed producer-fed output terminals,
    including surplus branches beyond Splitters and excluding consumer-drawn
    tails. Input marker heads can still be fed by a producer sorter, so exclude
    those internal lanes here before rating the remaining boundary entries.

    A HEAD IS RATED AT THE BLOCK'S WHOLE DEFICIT, WHICH OVERSTATES WHAT THE CUTS
    OWE IT.  ``sub.external_inputs[item]`` is everything the block is short of,
    and for an item that is ALSO in the PARENT's ``external_inputs`` part of
    that share is belted in by the player at the parent level rather than by any
    cut.  ``partition.derive_cuts`` knows the difference -- it sizes each cut at
    ``min(surplus, deficit)`` -- but the heads rated here do not, so a naive
    assignment would ask the internal tails to cover the player's share too and
    raise :class:`ContractError` when they cannot.  That was the
    ``zurl2/all-products`` hydrogen refusal (``hydrogen: block 0 supply
    exhausted; block 7 entry lane 1042 short by 4319/1875 items/s``), reached
    only after every block placed.  :func:`allocate_cuts` is what now stands
    between these heads and :func:`assign_lanes`: it leaves a block's WHOLE
    demand for that item to the player -- not a remainder of it; a (block,
    item) is wired entirely or not at all -- instead of demanding the internal
    tails cover it too, exactly when the parent's ``external_inputs`` already
    promises the item from outside.
    """
    buildings = placement.buildings
    building_index = Buildings.of(placement)
    sorter_fed = {
        buildings[i].output_obj
        for i in building_index.sorters()
        if buildings[i].output_obj is not None
    }

    tail_indices: dict[str, list[int]] = defaultdict(list)
    for i in markers.output_belt_tails(placement):
        item = buildings[i].carries_item
        if item is not None:
            tail_indices[item].append(i)

    head_indices: dict[str, list[int]] = defaultdict(list)
    for i in markers.input_belt_heads(placement):
        item = buildings[i].carries_item
        if item is not None and i not in sorter_fed:
            head_indices[item].append(i)

    tails = [
        LaneEnd(block=block, building=i, item=item, rate=rate)
        for item, indices in sorted(tail_indices.items())
        for i, rate in zip(
            indices,
            _apportion(
                sub.outputs.get(item, Fraction(0)),
                building_index,
                indices,
                puts_on=True,
            ),
            strict=True,
        )
    ]
    heads = [
        LaneEnd(block=block, building=i, item=item, rate=rate)
        for item, indices in sorted(head_indices.items())
        for i, rate in zip(
            indices,
            _apportion(
                sub.external_inputs.get(item, Fraction(0)),
                building_index,
                indices,
                puts_on=False,
            ),
            strict=True,
        )
    ]
    return tails, heads


def assign_lanes(
    cuts: list[Cut], tails: dict[int, list[LaneEnd]], heads: dict[int, list[LaneEnd]]
) -> list[LaneFlow]:
    """Exact transportation assignment from producer tails to consumer heads.

    Per item, tails are sorted by rate descending and heads by demand
    descending; the two lists are walked north-west-corner style, emitting one
    ``LaneFlow`` per positive amount assigned (at most ``n + m - 1`` flows per
    item across all its cuts). Raises :class:`ContractError` naming the item
    and the two blocks when a head cannot be filled from what its cuts' source
    blocks offer.
    """
    flows: list[LaneFlow] = []
    by_item: dict[str, list[Cut]] = defaultdict(list)
    for cut in cuts:
        by_item[cut.item].append(cut)
    for item, item_cuts in sorted(by_item.items()):
        # Pooled across every cut of this item, not solved cut-by-cut: `derive_cuts`
        # emits one `Cut` per (surplus block, deficit block) PAIR, so an item with
        # several producing or consuming blocks has several cuts here, and their
        # tails/heads must be assigned together for fan-out/fan-in to work at all.
        supply = sorted(
            (t for src in {c.src for c in item_cuts} for t in tails.get(src, ()) if t.item == item),
            key=lambda t: (-t.rate, t.block, t.building),
        )
        demand = sorted(
            (h for dst in {c.dst for c in item_cuts} for h in heads.get(dst, ()) if h.item == item),
            key=lambda h: (-h.rate, h.block, h.building),
        )
        left: dict[LaneEnd, Fraction] = {t: t.rate for t in supply}
        i = 0
        for head in demand:
            want = head.rate
            while want > 0 and i < len(supply):
                tail = supply[i]
                take = min(want, left[tail])
                if take > 0:
                    flows.append(LaneFlow(item=item, src=tail, dst=head, rate=take))
                    left[tail] -= take
                    want -= take
                if left[tail] == 0:
                    i += 1
            if want > 0:
                srcs = sorted({c.src for c in item_cuts})
                src_label = ", ".join(str(s) for s in srcs) if len(srcs) > 1 else str(srcs[0])
                raise ContractError(
                    f"{item}: block {src_label} supply exhausted; "
                    f"block {head.block} entry lane {head.building} short by {want} items/s"
                )
    return flows


@dataclass(frozen=True)
class CutAllocation:
    """A wired assignment, plus what was left for the player instead."""

    flows: list[LaneFlow]
    #: (block index, item) pairs whose entry heads are left to the player.
    player_fed: frozenset[tuple[int, str]]


def allocate_cuts(
    spec: BuildSpec,
    cuts: list[Cut],
    tails: dict[int, list[LaneEnd]],
    heads: dict[int, list[LaneEnd]],
) -> CutAllocation:
    """Wire what the internal supply covers; leave a both-fed block's whole
    demand to the player instead of demanding the tails stretch to cover it.

    Per item, ``S`` is the total internal supply -- the tails of every block
    the cuts name as a producer.  Consumer blocks are visited IN BLOCK-INDEX
    ORDER and served WHOLE OR NOT AT ALL: a block is served only while what is
    left of ``S`` still covers its whole deficit ``D_b``.  That makes which
    blocks get served DETERMINISTIC AND ORDER-STABLE rather than dependent on
    whichever one a less careful pass happened to reach first -- but it is
    FIRST-FIT, not a suffix rule: the pass does not stop at the first block it
    cannot serve, so a later SMALL block is still served out of what a skipped
    earlier LARGE one left behind.  A block that cannot be served is handed to
    the player -- its heads are simply never offered to :func:`assign_lanes` --
    exactly when ``item`` is one the parent spec already belts in
    (``spec.external_inputs``).  Otherwise nothing supplies that head at all,
    and that is a genuine :class:`ContractError`.
    """
    by_item: dict[str, list[Cut]] = defaultdict(list)
    for cut in cuts:
        by_item[cut.item].append(cut)

    player_fed: set[tuple[int, str]] = set()
    served_heads: dict[int, list[LaneEnd]] = defaultdict(list)
    for item, item_cuts in sorted(by_item.items()):
        supply_blocks = sorted({c.src for c in item_cuts})
        supply = sum(
            (t.rate for src in supply_blocks for t in tails.get(src, ()) if t.item == item),
            Fraction(0),
        )
        consumer_blocks = sorted({c.dst for c in item_cuts})
        remaining = supply
        for block in consumer_blocks:
            block_heads = [h for h in heads.get(block, ()) if h.item == item]
            deficit = sum((h.rate for h in block_heads), Fraction(0))
            # THE THRESHOLD IS MEASURED AGAINST AN OVERSTATED DEMAND, KNOWINGLY.
            # `boundary_lanes` rates a head at the block's WHOLE deficit (see
            # its docstring), and for an item the PARENT also belts in, part of
            # that share arrives from outside rather than from any cut --
            # `derive_cuts` knows the difference and sizes each cut at
            # `min(surplus, deficit)`.  So `deficit` here can exceed what the
            # cuts actually owe this block, and a block short of 100/s with 1/s
            # belted in by the parent and 99/s available internally is handed
            # ENTIRELY to the player while the producer's 99/s tail dead-ends.
            # The alternative would be to compare `remaining` against what
            # `derive_cuts` sized for this (src, dst) pair instead of against
            # the head sum.  It is deliberately NOT taken here: the plan
            # mandates whole-or-nothing per (block, item), so this is not a
            # contract violation but a coarser threshold, and changing it
            # changes WHICH builds become player-fed -- with no measurement on
            # this branch that could validate the change, the gate having seen
            # exactly one player-fed pair.  Controller Ruling R16.
            if remaining >= deficit:
                remaining -= deficit
                served_heads[block].extend(block_heads)
            elif item in spec.external_inputs:
                player_fed.add((block, item))
            else:
                raise ContractError(
                    f"{item}: internal supply {supply} cannot cover block {block}'s "
                    f"{deficit}; the parent does not belt it in"
                )

    flows = assign_lanes(cuts, tails, served_heads)
    return CutAllocation(flows=flows, player_fed=frozenset(player_fed))
