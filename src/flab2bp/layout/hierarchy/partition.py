"""Rate-weighted partition of a ``BuildSpec``'s recipe DAG into blocks.

The design, and where it departs from the brief:

* Nodes are *units*: one per ``MachineGroup``, pre-split so no unit exceeds the
  machine cap.  A unit is ``(recipe_id, count)`` -- splitting a group is exact,
  because every rate in a ``MachineGroup`` is per-machine.
* Edges are rate-weighted: the item flow from producer unit to consumer unit,
  apportioned by share when several units make or take the same item.
* Blocks come from agglomerative merging on the heaviest edge, capped by
  machines per block.
* Cuts are read off NET per-block balances, not off "who produces this
  anywhere", because a block that both makes and takes an item can still be
  short of it after integer rounding.

See ``docs/superpowers/evidence/2026-09-06-exp-hierarchical/README.md`` ("The
repair that does not work") for why there is no repair loop here: rate-
splitting an item's producing units into each consuming block to remove a
multi-consumer cut does not converge -- every move plants the producer's own
ingredient demand in new blocks, creating fresh multi-consumer cuts one level
upstream. A production version has to build the splitter, not dodge it.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from fractions import Fraction

from flab2bp.spec import BuildSpec, MachineGroup

STRIP_CAP_DEFAULT = 12


@dataclass
class Unit:
    """A rate-splittable slice of one ``MachineGroup``."""

    uid: int
    group: MachineGroup
    count: int

    @property
    def recipe(self) -> str:
        return self.group.recipe_id

    def produces(self, item: str) -> Fraction:
        return self.group.outputs_per_machine.get(item, Fraction(0)) * self.count

    def consumes(self, item: str) -> Fraction:
        return self.group.inputs_per_machine.get(item, Fraction(0)) * self.count


@dataclass(frozen=True)
class Cut:
    item: str
    src: int
    dst: int
    rate: Fraction


@dataclass
class Partition:
    blocks: list[list[Unit]]
    #: Every item that crosses a cut, read off the ordered blocks.
    cuts: list[Cut]
    notes: list[str] = field(default_factory=list)


class _UidCounter:
    """A unit-id generator passed explicitly so partitions are deterministic
    and re-entrant, rather than sharing module-level mutable state."""

    def __init__(self, start: int = 0) -> None:
        self._next = start

    def __call__(self) -> int:
        uid = self._next
        self._next += 1
        return uid


def _flow_between(a: list[Unit], b: list[Unit]) -> Fraction:
    """Rate-weighted coupling between two unit sets, both directions."""
    total = Fraction(0)
    for src, dst in ((a, b), (b, a)):
        made: dict[str, Fraction] = defaultdict(Fraction)
        for u in src:
            for item in u.group.outputs_per_machine:
                made[item] += u.produces(item)
        for u in dst:
            for item in u.group.inputs_per_machine:
                if item in made:
                    total += min(made[item], u.consumes(item))
    return total


def _machines(block: list[Unit]) -> int:
    return sum(u.count for u in block)


def agglomerate(units: list[Unit], cap: int) -> list[list[Unit]]:
    """Merge units into blocks on the heaviest rate-weighted coupling.

    Split any unit that is on its own bigger than the cap first, so the cap is
    a real bound rather than an aspiration.
    """
    uid = _UidCounter(1_000_000)
    seeds: list[list[Unit]] = []
    for u in units:
        parts = max(1, math.ceil(u.count / cap))
        base, extra = divmod(u.count, parts)
        for i in range(parts):
            count = base + (1 if i < extra else 0)
            if count:
                seeds.append([Unit(uid(), u.group, count)])
    blocks = seeds
    while True:
        best: tuple[Fraction, int, int] | None = None
        for i in range(len(blocks)):
            for j in range(i + 1, len(blocks)):
                if _machines(blocks[i]) + _machines(blocks[j]) > cap:
                    continue
                w = _flow_between(blocks[i], blocks[j])
                if w <= 0:
                    continue
                if best is None or w > best[0]:
                    best = (w, i, j)
        if best is None:
            return blocks
        _, i, j = best
        blocks[i] = blocks[i] + blocks[j]
        del blocks[j]


def coalesce(blocks: list[list[Unit]]) -> list[list[Unit]]:
    """One ``MachineGroup`` per recipe inside each block."""
    uid = _UidCounter(2_000_000)
    out: list[list[Unit]] = []
    for block in blocks:
        by_recipe: dict[str, Unit] = {}
        for u in block:
            got = by_recipe.get(u.recipe)
            if got is None:
                by_recipe[u.recipe] = Unit(uid(), u.group, u.count)
            else:
                got.count += u.count
        if by_recipe:
            out.append(sorted(by_recipe.values(), key=lambda u: u.recipe))
    return out


def derive_cuts(blocks: list[list[Unit]]) -> tuple[list[int], list[Cut]]:
    """Topological order for ``blocks``, and every item that crosses a cut.

    Returns the permutation rather than the reordered blocks so a caller that
    carries per-block state (a solved ``Placement``) can reorder it in step.
    Cut indices are in the NEW numbering.
    """
    # Cuts are read off NET balances, never off set membership.  A block that
    # both makes and takes an item can still be SHORT of it -- integer rounding
    # when a group is split guarantees a few such blocks -- and `sub_spec` then
    # declares the item an external input.  Treating "produces it somewhere in
    # the block" as "needs no lane" leaves that entry lane unfed, which the
    # composed `flow.conservation` correctly convicts.
    surplus: dict[str, dict[int, Fraction]] = defaultdict(dict)
    deficit: dict[str, dict[int, Fraction]] = defaultdict(dict)
    for i, block in enumerate(blocks):
        made: dict[str, Fraction] = defaultdict(Fraction)
        took: dict[str, Fraction] = defaultdict(Fraction)
        for u in block:
            for item in u.group.outputs_per_machine:
                made[item] += u.produces(item)
            for item in u.group.inputs_per_machine:
                took[item] += u.consumes(item)
        for item in set(made) | set(took):
            net = made.get(item, Fraction(0)) - took.get(item, Fraction(0))
            if net > 0:
                surplus[item][i] = net
            elif net < 0:
                deficit[item][i] = -net

    edges: set[tuple[int, int]] = set()
    cuts: list[Cut] = []
    for item, wants in deficit.items():
        gives = surplus.get(item, {})
        for dst, want in wants.items():
            for src, give in gives.items():
                edges.add((src, dst))
                cuts.append(Cut(item, src, dst, min(give, want)))
    order = _topo_order(len(blocks), edges)
    remap = {old: new for new, old in enumerate(order)}
    return order, sorted(
        (Cut(c.item, remap[c.src], remap[c.dst], c.rate) for c in cuts),
        key=lambda c: (c.item, c.src, c.dst, c.rate),
    )


def _topo_order(n: int, edges: set[tuple[int, int]]) -> list[int]:
    """Kahn order; any cycle is broken by lowest index so this always returns."""
    indeg = dict.fromkeys(range(n), 0)
    adj: dict[int, list[int]] = defaultdict(list)
    for s, d in edges:
        if s == d:
            continue
        adj[s].append(d)
        indeg[d] += 1
    order: list[int] = []
    ready = sorted(i for i in range(n) if indeg[i] == 0)
    seen: set[int] = set()
    while len(order) < n:
        if not ready:
            leftover = sorted(i for i in range(n) if i not in seen)
            ready = [leftover[0]]
        node = ready.pop(0)
        if node in seen:
            continue
        seen.add(node)
        order.append(node)
        for peer in adj[node]:
            indeg[peer] -= 1
            if indeg[peer] == 0 and peer not in seen:
                ready.append(peer)
        ready = sorted(set(ready) - seen)
    return order


def boundary_balances(
    blocks: list[list[Unit]],
) -> tuple[dict[str, dict[int, Fraction]], dict[str, dict[int, Fraction]]]:
    """``(surplus, deficit)`` per item per block: exactly what crosses a cut.

    The composed judgement needs these, not the aggregate production, so an item
    handed back to the player is declared at the rate the CUTS carry rather than
    at everything the factory makes of it.  Declaring the larger figure would
    hand ``flow.conservation``'s lane balance a supply that does not exist and
    quietly excuse lanes that are genuinely broken.
    """
    surplus: dict[str, dict[int, Fraction]] = defaultdict(dict)
    deficit: dict[str, dict[int, Fraction]] = defaultdict(dict)
    for i, block in enumerate(blocks):
        made: dict[str, Fraction] = defaultdict(Fraction)
        took: dict[str, Fraction] = defaultdict(Fraction)
        for u in block:
            for item in u.group.outputs_per_machine:
                made[item] += u.produces(item)
            for item in u.group.inputs_per_machine:
                took[item] += u.consumes(item)
        for item in set(made) | set(took):
            net = made.get(item, Fraction(0)) - took.get(item, Fraction(0))
            if net > 0:
                surplus[item][i] = net
            elif net < 0:
                deficit[item][i] = -net
    return surplus, deficit


def sub_spec(spec: BuildSpec, block: list[Unit], index: int) -> BuildSpec:
    """A self-contained ``BuildSpec`` for one block.

    Boundary items become ``external_inputs`` (consumed here, made elsewhere)
    and ``outputs`` (made here, leaves).  Everything else -- belt tiers, sorter
    ladder, stack, piler unlock -- travels verbatim, so a block is laid out
    against exactly the save the whole spec describes.
    """
    groups = tuple(
        MachineGroup(
            recipe_id=u.group.recipe_id,
            machine_item_id=u.group.machine_item_id,
            count=u.count,
            proliferator_mode=u.group.proliferator_mode,
            inputs_per_machine=dict(u.group.inputs_per_machine),
            outputs_per_machine=dict(u.group.outputs_per_machine),
        )
        for u in block
    )
    made: dict[str, Fraction] = defaultdict(Fraction)
    took: dict[str, Fraction] = defaultdict(Fraction)
    for u in block:
        for item in u.group.outputs_per_machine:
            made[item] += u.produces(item)
        for item in u.group.inputs_per_machine:
            took[item] += u.consumes(item)

    external_inputs: dict[str, Fraction] = {}
    for item, rate in sorted(took.items()):
        deficit = rate - made.get(item, Fraction(0))
        if deficit > 0:
            external_inputs[item] = deficit

    outputs: dict[str, Fraction] = {}
    for item, rate in sorted(made.items()):
        surplus = rate - took.get(item, Fraction(0))
        if surplus > 0:
            outputs[item] = surplus

    recipes = {u.recipe for u in block}
    # Recomputed, never inherited.  ``spray_lanes[item]`` is True exactly when
    # the lane exists anyway because the item is belted IN, and an item that was
    # internal to the whole spec is external to a block that does not make it.
    # Filtering the parent's flags instead ships False for those lanes, and
    # every block then refuses on `prolif.sprayed_cargo_reaches_machines`.
    spray_lanes: dict[str, bool] = {}
    for u in block:
        if not u.group.is_proliferated:
            continue
        for item in u.group.inputs_per_machine:
            if item not in spec.spray_lanes:
                continue
            is_external = item not in made
            spray_lanes[item] = spray_lanes.get(item, True) and is_external
    if spray_lanes:
        # A Spray Coater is fed like any other machine and proliferator is never
        # made inside a block, so a spraying block must belt it in.  Apportioned
        # by sprayed-machine share, so the block rates sum to the whole spec's.
        sprayed_here = sum(u.count for u in block if u.group.is_proliferated)
        sprayed_all = sum(g.count for g in spec.groups if g.is_proliferated)
        for item, rate in spec.external_inputs.items():
            if item.startswith("proliferator") and sprayed_all:
                external_inputs[item] = rate * Fraction(sprayed_here, sprayed_all)

    return BuildSpec(
        groups=groups,
        external_inputs=external_inputs,
        outputs=outputs,
        surplus_outputs={},
        belt_item_id=spec.belt_item_id,
        belt_items_per_second=spec.belt_items_per_second,
        belt_upgrades=spec.belt_upgrades,
        sorter_item_ids=spec.sorter_item_ids,
        belt_stack=spec.belt_stack,
        sorter_pick_stacks=spec.sorter_pick_stacks,
        sorter_place_stacks=spec.sorter_place_stacks,
        piler_unlocked=spec.piler_unlocked,
        machine_rank=spec.machine_rank,
        machine_moves=spec.machine_moves,
        label=f"{spec.label}#block{index}",
        belt_required_edges=frozenset(
            edge for edge in spec.belt_required_edges if edge[0] in recipes and edge[1] in recipes
        ),
        spray_lanes=spray_lanes,
        lanes_requiring_split=frozenset(
            item
            for item in spray_lanes
            if any(
                item in u.group.inputs_per_machine and not u.group.is_proliferated for u in block
            )
        ),
        coproduct_buffer_proofs=tuple(
            p
            for p in spec.coproduct_buffer_proofs
            if p.producer_recipe_id in recipes and p.consumer_recipe_id in recipes
        ),
        self_loop_seeds=tuple(s for s in spec.self_loop_seeds if s.recipe_id in recipes),
    )


def composed_spec(
    spec: BuildSpec,
    blocks: list[list[Unit]],
    *,
    player_fed: frozenset[tuple[int, str]] = frozenset(),
) -> BuildSpec:
    """The whole spec re-derived from the blocks, so composition is judged
    against what was actually built rather than against the original counts.

    Splitting can round counts up per (recipe, block), so the composed machine
    count can exceed the original by a few machines.  That over-production is
    real and must be visible to ``flow.conservation``, which is why this is
    re-derived instead of reusing ``spec``.

    ``player_fed`` names every (block index, item) whose entry head
    ``contracts.allocate_cuts`` left unwired because the parent already belts
    that item in.  The overall make/take balance below stays net-zero for such
    an item -- it IS produced somewhere in the build, just not routed to this
    particular block -- so each player-fed block's OWN local deficit is added
    on top, on the understanding that the player closes exactly that lane by
    hand.
    """
    by_recipe: dict[str, tuple[MachineGroup, int]] = {}
    for block in blocks:
        for u in block:
            got = by_recipe.get(u.recipe)
            by_recipe[u.recipe] = (u.group, (got[1] if got else 0) + u.count)
    groups = tuple(
        MachineGroup(
            recipe_id=g.recipe_id,
            machine_item_id=g.machine_item_id,
            count=count,
            proliferator_mode=g.proliferator_mode,
            inputs_per_machine=dict(g.inputs_per_machine),
            outputs_per_machine=dict(g.outputs_per_machine),
        )
        for g, count in (by_recipe[r] for r in sorted(by_recipe))
    )
    made: dict[str, Fraction] = defaultdict(Fraction)
    took: dict[str, Fraction] = defaultdict(Fraction)
    for g in groups:
        for item, rate in g.outputs_per_machine.items():
            made[item] += rate * g.count
        for item, rate in g.inputs_per_machine.items():
            took[item] += rate * g.count
    external_inputs = {
        item: rate for item, rate in spec.external_inputs.items() if not item.startswith("__")
    }
    for item in sorted(took):
        deficit = took[item] - made.get(item, Fraction(0))
        if deficit > 0:
            external_inputs[item] = max(external_inputs.get(item, Fraction(0)), deficit)
    for block_index, item in sorted(player_fed):
        block = blocks[block_index]
        block_made = sum((u.produces(item) for u in block), Fraction(0))
        block_took = sum((u.consumes(item) for u in block), Fraction(0))
        block_deficit = block_took - block_made
        if block_deficit > 0:
            external_inputs[item] = external_inputs.get(item, Fraction(0)) + block_deficit
    outputs = dict(spec.outputs)
    surplus = {}
    for item in sorted(made):
        left = made[item] - took.get(item, Fraction(0)) - outputs.get(item, Fraction(0))
        if left > 0:
            surplus[item] = left
    return BuildSpec(
        groups=groups,
        external_inputs=external_inputs,
        outputs=outputs,
        surplus_outputs=surplus,
        belt_item_id=spec.belt_item_id,
        belt_items_per_second=spec.belt_items_per_second,
        belt_upgrades=spec.belt_upgrades,
        sorter_item_ids=spec.sorter_item_ids,
        belt_stack=spec.belt_stack,
        sorter_pick_stacks=spec.sorter_pick_stacks,
        sorter_place_stacks=spec.sorter_place_stacks,
        piler_unlocked=spec.piler_unlocked,
        machine_rank=spec.machine_rank,
        machine_moves=spec.machine_moves,
        label=f"{spec.label}#composed",
        belt_required_edges=spec.belt_required_edges,
        spray_lanes=spec.spray_lanes,
        lanes_requiring_split=spec.lanes_requiring_split,
        coproduct_buffer_proofs=spec.coproduct_buffer_proofs,
        self_loop_seeds=spec.self_loop_seeds,
    )


def strip_count(spec: BuildSpec, block: list[Unit]) -> int:
    """How many strips freeform actually packs for ``block`` on its own.

    Freeform packs more strips than the logical plan count -- a strip's
    machines are capped at ``strip_len`` and split further by shared-lane and
    clearance limits -- so counting logical plans understates what a block
    costs to lay out and lets oversized blocks slip past ``strip_cap``.
    Import lazily, the same import-cycle shape ``initial_partition`` uses for
    ``depth_pressure_blocks``: ``freeform`` is a ~22k-line module and nothing
    else in this file needs it paid for up front.
    """
    from flab2bp.layout.freeform import plan_strips

    return len(plan_strips(sub_spec(spec, block, 0)))


def initial_partition(spec: BuildSpec, *, strip_cap: int = STRIP_CAP_DEFAULT) -> Partition:
    """Cut at pressure minima, then split any block over ``strip_cap`` strips."""
    from flab2bp.layout.hierarchy.pressure import depth_pressure_blocks

    seeds, _cut_after, _profile = depth_pressure_blocks(spec)
    blocks: list[list[Unit]] = []
    todo = list(seeds)
    while todo:
        block = todo.pop()
        if strip_count(spec, block) <= strip_cap or len(block) == 1 and block[0].count == 1:
            blocks.append(block)
            continue
        children = split_block(block, attempt=0)
        if len(children) < 2:
            blocks.append(block)
            continue
        todo.extend(children)
    blocks = coalesce(blocks)
    order, cuts = derive_cuts(blocks)
    return Partition(blocks=[blocks[i] for i in order], cuts=cuts, notes=[])


def split_block(block: list[Unit], *, attempt: int) -> list[list[Unit]]:
    """Two or more children of ``block``; ``attempt`` varies WHERE it is cut.

    Block size interacts with the placers non-monotonically (six machines
    refused, three plus three placed), so a refusing block is not only shrunk
    but re-cut: attempt 0 halves by machines on the heaviest edge, attempt 1
    cuts at one third, attempt 2 splits every unit's count in two, attempt 3
    isolates each recipe.
    """
    machines = sum(u.count for u in block)
    if attempt == 0:
        cap = max(1, machines // 2)
    elif attempt == 1:
        cap = max(1, machines // 3)
    elif attempt == 2:
        halves: list[list[Unit]] = []
        for u in block:
            a, b = u.count // 2, u.count - u.count // 2
            halves.append([Unit(u.uid * 2, u.group, a)] if a else [])
            halves.append([Unit(u.uid * 2 + 1, u.group, b)] if b else [])
        return [h for h in halves if h]
    else:
        return [[u] for u in block]
    return coalesce(agglomerate(block, cap))
