"""Lay every solved block on one canvas and route the cuts with the real router.

The prototype
(``docs/superpowers/evidence/2026-09-06-exp-hierarchical/proto/compose.py``)
wired the cuts with its own corridor Dijkstra, on the reading that
``freeform._route_all`` "is not callable standalone".  That reading is wrong:
``_route_all`` takes a prepared :class:`~flab2bp.layout.freeform._Canvas` and a
list of :class:`~flab2bp.layout.freeform._Net`, and ``tests/layout/
test_freeform.py`` already calls it that way.  What the prototype had to invent
to compensate -- a collider halo, a soft moat, an altitude toll to stop a
ground-level corridor walling in somebody else's entry lane -- is exactly what
the router's own port-access reservations and crossing bands do properly, so
none of it survives here.

The packing does survive, verbatim: ``_normalize``, :func:`pack_blocks` (the
prototype's ``_shelf`` without its single-row mode), :func:`_skyline` and
``_translate``.  Its two hard-won constants come with it -- a two-tile floor
under the gap, because ``game.belt_collide`` prices a belt against a
neighbour's build collider, and :data:`BAND_MAX_ROWS`, because
``finalize.finalize_placement`` refuses a deeper paste with
``game.blueprint_area``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from flab2bp.dsp import catalog
from flab2bp.layout.base import PlacedBuilding, Placement
from flab2bp.layout.freeform import (
    _Canvas,
    _lane_stacks_for,
    _Net,
    _Port,
    _port_access_inventory,
    _reserve_port_access,
    _route_all,
    _sorter_stacks_for,
    _sorter_tiers_for,
)
from flab2bp.layout.hierarchy.contracts import LaneFlow
from flab2bp.layout.route_feedback import NetId, NetRole
from flab2bp.layout.strip_variants import CargoDomain
from flab2bp.spec import BuildSpec

#: Latitude rows in the tallest band; a deeper placement pastes on no band.
BAND_MAX_ROWS = 160

#: The narrowest gap a packing may leave between two blocks.
#:
#: ``game.belt_collide`` prices a belt against a neighbour's build collider and
#: a Splitter's reaches beyond its 2x2 footprint, so blocks laid flush against
#: each other convict on contact alone.
MIN_GAP = 2


@dataclass
class BlockPlaced:
    """One solved block, and where it landed on the composed canvas."""

    index: int
    placement: Placement
    base: int
    offset: tuple[int, int]
    width: int
    height: int


@dataclass
class ComposeResult:
    """The composed placement plus an honest account of every cut."""

    placement: Placement
    blocks: list[BlockPlaced]
    routed: int
    #: One line per unrouted flow: item, source block, destination block, and
    #: the router's own failure kind.  A cut that did not wire is REPORTED, not
    #: quietly dropped -- an unwired entry lane is a block that starves, and the
    #: validator convicts it several errors later with no way back to the cause.
    failures: tuple[str, ...]


def _normalize(placement: Placement) -> tuple[Placement, int, int]:
    min_x, min_y, max_x, max_y = placement.bounds
    shifted = tuple(
        replace(
            b,
            x=b.x - min_x,
            y=b.y - min_y,
            x2=None if b.x2 is None else b.x2 - min_x,
            y2=None if b.y2 is None else b.y2 - min_y,
        )
        for b in placement.buildings
    )
    return (
        replace(placement, buildings=shifted, frame=None, completion=None),
        max_x - min_x + 1,
        max_y - min_y + 1,
    )


def pack_blocks(sizes: list[tuple[int, int]], gap: int) -> tuple[list[tuple[int, int]], int, int]:
    """Pack the blocks bottom-left, preferring a band-legal shape to a small one.

    Shelves are packed tallest-first (best-fit decreasing height), which trades
    strict topological order along the bus for much less shelf waste.  The
    router searches the whole canvas, so the order only decides how far a trunk
    has to travel.

    The tallest DSP latitude band holds :data:`BAND_MAX_ROWS` rows, and
    ``finalize_placement`` refuses anything deeper with ``game.blueprint_area``
    (``EBuildCondition.BlueprintAreaCrossTropic``).  On the 935-machine mall the
    minimum-AREA packing was 247x205 and could not be pasted at all, so the
    sweep prefers a legal shape over a small one and only falls back to the
    smallest illegal shape when nothing fits.
    """
    gap = max(gap, MIN_GAP)
    best: tuple[int, list[tuple[int, int]], int, int] | None = None
    fallback: tuple[int, list[tuple[int, int]], int, int] | None = None
    widest = max(w for w, _ in sizes) + gap
    total = sum((w + gap) * (h + gap) for w, h in sizes)
    for scale in (0.85, 1.0, 1.15, 1.3, 1.5, 1.8, 2.2, 2.8, 3.6):
        target = max(widest, int((total**0.5) * scale))
        packed = _skyline(sizes, gap, target)
        if packed is None:
            continue
        offsets, width, height = packed
        candidate = (width * height, offsets, width, height)
        if fallback is None or candidate[0] < fallback[0]:
            fallback = candidate
        if min(width, height) > BAND_MAX_ROWS:
            continue
        if best is None or candidate[0] < best[0]:
            best = candidate
    chosen = best or fallback
    assert chosen is not None
    return chosen[1], chosen[2], chosen[3]


def _skyline(
    sizes: list[tuple[int, int]], gap: int, target: int
) -> tuple[list[tuple[int, int]], int, int] | None:
    """Bottom-left skyline packing, tallest first, into a ``target`` wide strip.

    Shelf packing wasted 40 % of the composed canvas on belt3 because block
    heights differ by 3x.  A skyline keeps the same left-to-right sweep and
    fills the notches, which is what brings the composition overhead down to
    something a decision can be made on.
    """
    if any(w > target for w, _ in sizes):
        return None
    order = sorted(range(len(sizes)), key=lambda i: (-sizes[i][1], -sizes[i][0], i))
    heights = [0] * target
    offsets: list[tuple[int, int]] = [(0, 0)] * len(sizes)
    used_w = used_h = 0
    for i in order:
        w, h = sizes[i]
        span = min(target, w + gap)
        best_spot: tuple[int, int] | None = None
        for x in range(target - w + 1):
            top = max(heights[x : min(target, x + span)])
            if best_spot is None or (top, x) < best_spot:
                best_spot = (top, x)
        assert best_spot is not None
        top, x = best_spot
        offsets[i] = (x, top)
        used_w = max(used_w, x + w)
        used_h = max(used_h, top + h)
        for k in range(x, min(target, x + span)):
            heights[k] = top + h + gap
    return offsets, used_w, used_h


def _translate(placement: Placement, base: int, ox: int, oy: int) -> list[PlacedBuilding]:
    """``placement`` moved to ``(ox, oy)`` with its links rebased onto ``base``."""
    out: list[PlacedBuilding] = []
    for b in placement.buildings:
        out.append(
            replace(
                b,
                x=b.x + ox,
                y=b.y + oy,
                x2=None if b.x2 is None else b.x2 + ox,
                y2=None if b.y2 is None else b.y2 + oy,
                output_obj=None if b.output_obj is None else b.output_obj + base,
                input_obj=None if b.input_obj is None else b.input_obj + base,
            )
        )
    return out


def canvas_for(
    spec: BuildSpec, buildings: list[PlacedBuilding], *, ramped: bool, margin: int
) -> _Canvas:
    """The composed buildings as a routing canvas, sized to their own extent."""
    canvas = _Canvas(
        ramped=ramped,
        sorter_tiers=_sorter_tiers_for(spec),
        sorter_stacks=_sorter_stacks_for(spec),
        lane_stacks=_lane_stacks_for(spec),
    )
    for b in buildings:
        # Mirror `_prepare_routing_problem`: machines and addons are solid
        # (their crossing band goes into `blocked`), belts hold their own level.
        canvas.add(b, solid=not catalog.is_belt(b.item_id))
    min_x, min_y, max_x, max_y = Placement(buildings=tuple(buildings)).bounds
    canvas.limit = (min_x - margin, min_y - margin, max_x + margin, max_y + margin)
    return canvas


def _lane(buildings: list[PlacedBuilding], index: int) -> tuple[int, ...]:
    """Every belt index of the run containing ``index``, west to east."""
    prev = {b.output_obj: i for i, b in enumerate(buildings) if b.output_obj is not None}
    head = index
    while head in prev and catalog.is_belt(buildings[prev[head]].item_id):
        head = prev[head]
    run = [head]
    while True:
        onward = buildings[run[-1]].output_obj
        if onward is None or not catalog.is_belt(buildings[onward].item_id):
            break
        run.append(onward)
    # ONE ROW of that run, the port's own.  A boundary lane in a freeform block
    # is east-west (`_prepare_routing_problem` builds its ports as
    # `x0 = head.x, x1 = head.x + len(lane) - 1`), but the run reached through
    # `output_obj` also takes in the north-south sorter drop columns spliced
    # into it.  `_Port.at_tile` reads the k-th tap off as `x0 + k`, so a tile
    # list wider than the column span would hand the router a tap at a cell no
    # belt of this lane stands on.
    row = buildings[index].y
    return tuple(sorted((i for i in run if buildings[i].y == row), key=lambda i: buildings[i].x))


def _port(buildings: list[PlacedBuilding], index: int, machines: int) -> _Port:
    """The router's view of one boundary lane, attached at ``index``."""
    tiles = _lane(buildings, index)
    b = buildings[index]
    return _Port(
        belt=index,
        x=b.x,
        y=b.y,
        x0=buildings[tiles[0]].x,
        x1=buildings[tiles[-1]].x,
        tiles=tiles,
        machines=machines,
        z=int(b.z),
        cargo_domain=CargoDomain.UNSPRAYED,
    )


def _machines_behind(buildings: list[PlacedBuilding], block: BlockPlaced, index: int) -> int:
    """Production machines behind one lane, for :attr:`_Port.machines`.

    A machine building is the only kind carrying a real recipe, so
    ``recipe_id != 0`` picks it out (the same rule ``contracts`` rates lanes
    by).  A lane that kept its ``owner_strip`` is credited with that strip's
    machines; one that lost it falls back to the whole block's, which is the
    coarse answer rather than a wrong precise one.
    """
    strip = buildings[index].owner_strip
    stop = block.base + len(block.placement.buildings)
    return max(
        1,
        sum(
            1
            for b in buildings[block.base : stop]
            if b.recipe_id != 0 and (strip is None or b.owner_strip == strip)
        ),
    )


def compose(
    placements: list[Placement],
    flows: list[LaneFlow],
    spec: BuildSpec,
    *,
    gap: int,
    ramped: bool,
    deadline: float | None,
    _limit_margin: int = 8,
) -> ComposeResult:
    """Pack the solved blocks side by side and wire every ``LaneFlow`` between them.

    ``_limit_margin`` is how much free ground outside the packed boxes the
    router may use; it exists so a test can wall the composition in at 0 and
    see the router NAME the cut it cannot make.
    """
    normalized = [_normalize(p) for p in placements]
    offsets, _width, _height = pack_blocks([(w, h) for _, w, h in normalized], gap)

    buildings: list[PlacedBuilding] = []
    blocks: list[BlockPlaced] = []
    for i, ((placement, w, h), (ox, oy)) in enumerate(zip(normalized, offsets, strict=True)):
        base = len(buildings)
        buildings.extend(_translate(placement, base, ox, oy))
        blocks.append(BlockPlaced(i, placement, base, (ox, oy), w, h))

    canvas = canvas_for(spec, buildings, ramped=ramped, margin=_limit_margin)
    bounds = canvas.limit
    assert bounds is not None  # canvas_for always sets it

    nets: list[_Net] = []
    for ordinal, flow in enumerate(flows):
        src_block = blocks[flow.src.block]
        dst_block = blocks[flow.dst.block]
        src_index = flow.src.building + src_block.base
        dst_index = flow.dst.building + dst_block.base
        nets.append(
            _Net(
                src=_port(buildings, src_index, _machines_behind(buildings, src_block, src_index)),
                dst=_port(buildings, dst_index, _machines_behind(buildings, dst_block, dst_index)),
                item=flow.item,
                # The strip fields carry the BLOCK indices here: they are the
                # router's stable identity for a net, and the only thing a
                # returned `NetFailure` can be read back through to say which
                # cut failed.
                net_id=NetId(
                    source_strip=flow.src.block,
                    destination_strip=flow.dst.block,
                    item=flow.item,
                    role=NetRole.INTERNAL,
                    ordinal=ordinal,
                ),
            )
        )

    # Stake every port's approach before any path commits, the way
    # `_prepare_routing_problem` does.  A boundary lane's end tile has at most
    # three free neighbours and often one; without the reservation an earlier
    # net's path takes the last one and every later net using that port is
    # handed an empty start set -- a search that expands nothing and so
    # registers no congestion for the negotiation to price.
    _reserve_port_access(canvas, _port_access_inventory(nets).demands, bounds=bounds)

    belt_id = catalog.get_item_id(spec.belt_item_id) or 2001
    belt_model = catalog.building(belt_id).model_index
    result = _route_all(canvas, nets, belt_id, belt_model, bounds, deadline=deadline)

    failures = [
        f"{failure.net_id.item}: block {failure.net_id.source_strip} -> "
        f"block {failure.net_id.destination_strip}: {failure.kind.name}"
        for failure in result.failures
    ]
    # A net that neither routed nor failed is one the pass never reached -- a
    # deadline or a spent budget. It is still an unwired cut and is reported as
    # one, under the status that stopped the pass.
    accounted = set(result.routed) | {failure.net_id for failure in result.failures}
    failures.extend(
        f"{net.item}: block {net.net_id.source_strip} -> "
        f"block {net.net_id.destination_strip}: {result.status.name}"
        for net in nets
        if net.net_id is not None and net.net_id not in accounted
    )

    return ComposeResult(
        Placement(buildings=tuple(canvas.buildings), description="hierarchical composition"),
        blocks,
        len(result.routed),
        tuple(failures),
    )


__all__ = ["BAND_MAX_ROWS", "BlockPlaced", "ComposeResult", "canvas_for", "compose", "pack_blocks"]
