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

from flab2bp.dsp import catalog
from flab2bp.layout import markers
from flab2bp.layout.base import PlacedBuilding, Placement
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


def _machines_behind(buildings: tuple[PlacedBuilding, ...], strip: int) -> int:
    """Production machines (not belts, sorters, or splitters) in one strip.

    A machine building is the only kind that carries a real recipe, so
    ``recipe_id != 0`` picks it out: every ``PlacedBuilding`` constructor that
    sets a nonzero ``recipe_id`` does so from a ``MachineGroup``, and every
    belt/sorter/splitter/piler constructor leaves it at the default 0.
    """
    return sum(1 for b in buildings if b.owner_strip == strip and b.recipe_id != 0)


def _apportion(
    total: Fraction, buildings: tuple[PlacedBuilding, ...], indices: list[int]
) -> list[Fraction]:
    """Split ``total`` across ``indices``' lanes, sum preserved exactly.

    Rated by machines behind each lane's strip (``owner_strip``) only when
    EVERY lane in this group traces to one. A lane missing that provenance has
    no machine count to weight it, and giving it weight 0 would zero-rate a
    real lane -- a zero-rated entry head is one the assignment never feeds,
    which the validator later convicts as unfed -- so a group with even one
    strip-less lane falls back to an even split for the WHOLE group, not just
    that lane. (A group all present but whose machine counts still sum to 0
    falls back the same way, defensively.) Either way the split is exact
    ``Fraction`` arithmetic, so the parts always sum back to ``total``.
    """
    n = len(indices)
    if any(buildings[i].owner_strip is None for i in indices):
        return [total / n for _ in range(n)]
    weights: list[int] = []
    for i in indices:
        strip = buildings[i].owner_strip
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

    Lifts the endpoint catalogue from
    ``docs/superpowers/evidence/2026-09-06-exp-hierarchical/proto/compose.py``
    (lines 315-348): ``markers.output_belt_tails``/``input_belt_heads`` answer
    "where could an icon go", a superset of "where does the block's boundary
    lane start/end" -- an INTERNAL lane (a machine's sorter onto a belt, along,
    off into another machine's sorter) has a head with no belt predecessor and
    a tail with no belt successor, so both marker functions return it. A
    boundary output tail is one no sorter draws from; a boundary entry head is
    one no sorter feeds.
    """
    buildings = placement.buildings
    sorter_fed = {
        b.output_obj for b in buildings if catalog.is_sorter(b.item_id) and b.output_obj is not None
    }
    sorter_drawn = {
        b.input_obj for b in buildings if catalog.is_sorter(b.item_id) and b.input_obj is not None
    }

    tail_indices: dict[str, list[int]] = defaultdict(list)
    for i in markers.output_belt_tails(placement):
        item = buildings[i].carries_item
        if item is not None and i not in sorter_drawn:
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
            indices, _apportion(sub.outputs.get(item, Fraction(0)), buildings, indices), strict=True
        )
    ]
    heads = [
        LaneEnd(block=block, building=i, item=item, rate=rate)
        for item, indices in sorted(head_indices.items())
        for i, rate in zip(
            indices,
            _apportion(sub.external_inputs.get(item, Fraction(0)), buildings, indices),
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
