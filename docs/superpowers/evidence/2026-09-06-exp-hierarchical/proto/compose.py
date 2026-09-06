"""Translate block placements onto one canvas and wire the inter-block belts.

Throwaway spike code.

Why this router and not ``freeform._route_all``: that router is not callable
standalone.  It is a method on ``FreeformLayout`` whose nets, grid, lane plan,
merge frontier and rip-up state are all built inside ``lay_out`` from a single
``BuildSpec`` -- there is no entry point that takes "a prepared canvas plus a
list of nets".  The closest existing pattern, ``_plan_shared_external_inputs`` /
``_place_shared_external_input_trunks``, is likewise internal to one placement's
grid.  So this is the simplest deterministic corridor router that can be
certified by the same validator: a Dijkstra over the composed free space at
half-tile altitude quanta, one net at a time, in topological order, with the
tiles it lays becoming obstacles for the next net.

It only ever travels over columns with NO building in them, at any altitude.
That is deliberately conservative: ``game.belt_crossing`` prices a belt over an
Assembling Machine at z > 3.53, and a prototype has no business guessing which
crossings clear.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field, replace
from fractions import Fraction

from flab2bp.dsp import catalog
from flab2bp.layout import markers
from flab2bp.layout.base import Facing, PlacedBuilding, Placement

_STEPS = ((1, 0, 90.0), (-1, 0, 270.0), (0, 1, 0.0), (0, -1, 180.0))
#: Altitude in half-tile quanta; ``BELT_CLIMB_PER_TILE`` is 1/2.
_QUANTUM = catalog.BELT_CLIMB_PER_TILE
#: Latitude rows in the tallest band; a deeper placement pastes on no band.
BAND_MAX_ROWS = 160


def _yaw_for(dx: int, dy: int) -> float:
    for sx, sy, yaw in _STEPS:
        if (sx, sy) == (dx, dy):
            return yaw
    raise ValueError(f"not a unit step: {(dx, dy)}")


@dataclass
class BlockPlaced:
    index: int
    placement: Placement
    base: int
    offset: tuple[int, int]
    width: int
    height: int


@dataclass
class ComposeResult:
    placement: Placement
    blocks: list[BlockPlaced]
    routed: list[tuple[str, int, int, int]]
    unrouted: list[tuple[str, int, int, str]]
    corridor_tiles: int
    #: ``(block, item) -> (entry lanes wired, entry lanes present)``.  A cut can
    #: be PARTIALLY wired -- three lanes out, two of them routed -- and the
    #: unfed third has to be declared or `flow.lane_sourced` convicts it.
    entry_status: dict[tuple[int, str], tuple[int, int]] = field(default_factory=dict)


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


def _shelf(
    sizes: list[tuple[int, int]], gap: int, *, single_row: bool
) -> tuple[list[tuple[int, int]], int, int]:
    """Place blocks along one axis, optionally wrapping into shelves.

    ``single_row=True`` keeps every block anchored at y = 0.  That is not a
    cosmetic choice: ``finalize.finalize_placement`` projects tile rows onto
    latitude rows, and a block certified at one latitude is not certified at
    another, so moving a block DOWN re-prices every east-west gap inside it.
    A single row preserves each block's own rows and its power-pole spacings;
    a shelf pack does not, and refuses on ``game.power_too_close``.

    Shelves are packed tallest-first (best-fit decreasing height), which trades
    strict topological order along the bus for much less shelf waste.  The
    corridor router does not need the order -- it searches the whole canvas --
    so the order only matters to how far a trunk has to travel.
    """
    if single_row:
        offsets: list[tuple[int, int]] = []
        x = 0
        for w, _h in sizes:
            offsets.append((x, 0))
            x += w + gap
        return offsets, x - gap, max(h for _, h in sizes)

    # The tallest DSP latitude band holds 160 rows, and `finalize_placement`
    # refuses anything deeper with `game.blueprint_area`
    # (EBuildCondition.BlueprintAreaCrossTropic).  On the 935-machine mall the
    # minimum-AREA packing was 247x205 and could not be pasted at all, so the
    # sweep prefers a legal shape over a small one and only falls back to the
    # smallest illegal shape when nothing fits.
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


def _columns(buildings: list[PlacedBuilding]) -> set[tuple[int, int]]:
    """Every (x, y) column holding any building at any altitude."""
    taken: set[tuple[int, int]] = set()
    for b in buildings:
        for dx in range(b.width):
            for dy in range(b.height):
                taken.add((b.x + dx, b.y + dy))
        if b.x2 is not None and b.y2 is not None:
            taken.add((b.x2, b.y2))
    return taken


def _route(
    start_from: PlacedBuilding,
    goal_into: PlacedBuilding,
    blocked: set[tuple[int, int]],
    penalty: dict[tuple[int, int], int],
    bounds: tuple[int, int, int, int],
    max_zq: int,
    node_cap: int = 600_000,
) -> list[tuple[int, int, int]] | None:
    """Dijkstra a belt path from beside ``start_from`` to beside ``goal_into``.

    Returns cells as ``(x, y, altitude quanta)``, first cell adjacent to the
    source tail and last adjacent to the destination head, or ``None``.
    """
    lo_x, lo_y, hi_x, hi_y = bounds
    sq = int(start_from.z / _QUANTUM)
    gq = int(goal_into.z / _QUANTUM)

    def free(x: int, y: int) -> bool:
        return lo_x <= x <= hi_x and lo_y <= y <= hi_y and (x, y) not in blocked

    starts: list[tuple[int, int, int]] = []
    for dx, dy, _ in _STEPS:
        x, y = start_from.x + dx, start_from.y + dy
        if not free(x, y):
            continue
        for dz in (-1, 0, 1):
            zq = sq + dz
            if 0 <= zq <= max_zq:
                starts.append((x, y, zq))
    goals: dict[tuple[int, int, int], None] = {}
    for dx, dy, _ in _STEPS:
        x, y = goal_into.x + dx, goal_into.y + dy
        if not free(x, y):
            continue
        for dz in (-1, 0, 1):
            zq = gq + dz
            if 0 <= zq <= max_zq:
                goals[(x, y, zq)] = None
    if not starts or not goals:
        return None

    gx, gy = goal_into.x, goal_into.y

    def h(node: tuple[int, int, int]) -> int:
        return abs(node[0] - gx) + abs(node[1] - gy)

    dist: dict[tuple[int, int, int], int] = {}
    prev: dict[tuple[int, int, int], tuple[int, int, int] | None] = {}
    heap: list[tuple[int, int, tuple[int, int, int]]] = []
    for node in starts:
        dist[node] = 0
        prev[node] = None
        heapq.heappush(heap, (h(node), 0, node))
    expanded = 0
    while heap:
        _, cost, node = heapq.heappop(heap)
        if cost > dist.get(node, 1 << 60):
            continue
        if node in goals:
            path: list[tuple[int, int, int]] = []
            cursor: tuple[int, int, int] | None = node
            while cursor is not None:
                path.append(cursor)
                cursor = prev[cursor]
            return list(reversed(path))
        expanded += 1
        if expanded > node_cap:
            return None
        x, y, zq = node
        for dx, dy, _ in _STEPS:
            nx, ny = x + dx, y + dy
            if not free(nx, ny):
                continue
            for dz in (0, -1, 1):
                nz = zq + dz
                if not 0 <= nz <= max_zq:
                    continue
                # Ground is dear, altitude is cheap.  `flow.external_entry_reachable`
                # floods each ALTITUDE PLANE separately, so a corridor that runs
                # at z >= 1/2 cannot wall in a block's z = 0 entry lane, while a
                # ground-level one demonstrably does (11 errors on belt3).  The
                # toll makes the router climb out of a block, cross elevated,
                # and come down only at the far end.
                step = 1 + (3 if dz else 0) + penalty.get((nx, ny), 0) + (12 if nz == 0 else 0)
                peer = (nx, ny, nz)
                if cost + step < dist.get(peer, 1 << 60):
                    dist[peer] = cost + step
                    prev[peer] = node
                    heapq.heappush(heap, (cost + step + h(peer), cost + step, peer))
    return None


def compose(
    placements: list[Placement],
    cuts: list[tuple[str, int, int, Fraction]],
    *,
    gap: int = 6,
    max_belt_z: Fraction,
    single_row: bool = False,
) -> ComposeResult:
    normalized: list[tuple[Placement, int, int]] = [_normalize(p) for p in placements]
    offsets, _, _ = _shelf([(w, h) for _, w, h in normalized], gap, single_row=single_row)

    buildings: list[PlacedBuilding] = []
    blocks: list[BlockPlaced] = []
    for i, ((placement, w, h), (ox, oy)) in enumerate(zip(normalized, offsets, strict=True)):
        base = len(buildings)
        buildings.extend(_translate(placement, base, ox, oy))
        blocks.append(BlockPlaced(i, placement, base, (ox, oy), w, h))

    # Endpoint catalogues, per block, in the COMPOSED index space.
    #
    # `markers.input_belt_heads` and `output_belt_tails` answer "where could an
    # icon go", which is a superset of "where does the block's boundary lane
    # start/end".  An INTERNAL lane -- machine sorter onto a belt, along, off
    # into another machine's sorter -- has a head with no belt predecessor and a
    # tail with no belt successor, so both functions return it.  For a block
    # that both makes and takes an item (every block does, after the escalation
    # split) that doubles the apparent lane count on one or both sides, and the
    # boundary pairing then reads a mismatch that is not there.  A boundary
    # entry head is one NO sorter feeds; a boundary output tail is one NO sorter
    # draws from.
    tails: list[dict[str, list[int]]] = []
    heads: list[dict[str, list[int]]] = []
    for blk in blocks:
        bs = blk.placement.buildings
        sorter_fed = {
            b.output_obj for b in bs if catalog.is_sorter(b.item_id) and b.output_obj is not None
        }
        sorter_drawn = {
            b.input_obj for b in bs if catalog.is_sorter(b.item_id) and b.input_obj is not None
        }
        t: dict[str, list[int]] = {}
        for i in markers.output_belt_tails(blk.placement):
            item = bs[i].carries_item
            if item and i not in sorter_drawn:
                t.setdefault(item, []).append(i + blk.base)
        h: dict[str, list[int]] = {}
        for i in markers.input_belt_heads(blk.placement):
            item = bs[i].carries_item
            if item and i not in sorter_fed:
                h.setdefault(item, []).append(i + blk.base)
        tails.append(t)
        heads.append(h)

    blocked = _columns(buildings)
    # `game.belt_collide` prices a belt against a neighbour's build collider,
    # and a Splitter's reaches beyond its 2x2 footprint -- a corridor tile laid
    # flush against one is convicted.  A one-tile halo around every non-belt
    # building keeps the corridor clear of all of them without modelling each
    # collider; the halo costs corridor room, never block area.
    halo: set[tuple[int, int]] = set()
    for b in buildings:
        if catalog.is_belt(b.item_id):
            continue
        for dx in range(-1, b.width + 1):
            for dy in range(-1, b.height + 1):
                halo.add((b.x + dx, b.y + dy))
    # A block's external-input lanes must stay reachable from outside
    # (`flow.external_entry_reachable`).  The corridor is free to cross the gaps
    # but not to wall off somebody else's entry, so every boundary endpoint's
    # own free neighbours are reserved and only released to the net that uses
    # them.
    endpoints: list[int] = []
    for t, h in zip(tails, heads, strict=True):
        endpoints.extend(i for lanes in t.values() for i in lanes)
        endpoints.extend(i for lanes in h.values() for i in lanes)
    reserved: dict[tuple[int, int], set[int]] = {}
    for i in endpoints:
        b = buildings[i]
        for dx, dy, _ in _STEPS:
            reserved.setdefault((b.x + dx, b.y + dy), set()).add(i)
    # A soft moat one tile wide around every block, plus a mild toll on the
    # whole packed interior.  Both are COSTS, not walls: a corridor still dips
    # into the moat to leave its own block, but it will not run along one, and
    # it prefers the free plane outside the packing to the gaps between blocks.
    # Without this the router's own tiles wall in somebody else's
    # external-input lane and `flow.external_entry_reachable` -- an ERROR --
    # fires on an item that had been perfectly reachable a moment before.
    penalty: dict[tuple[int, int], int] = {}
    for blk in blocks:
        ox, oy = blk.offset
        for x in range(ox - 1, ox + blk.width + 1):
            for y in (oy - 1, oy + blk.height):
                penalty[(x, y)] = 24
        for y in range(oy - 1, oy + blk.height + 1):
            for x in (ox - 1, ox + blk.width):
                penalty[(x, y)] = 24
    for cell, owners in reserved.items():
        penalty[cell] = max(penalty.get(cell, 0), 40) if owners else penalty.get(cell, 0)

    min_x = min(b.x for b in buildings) - gap
    min_y = min(b.y for b in buildings) - gap
    max_x = max(b.x + b.width - 1 for b in buildings) + gap
    max_y = max(b.y + b.height - 1 for b in buildings) + gap
    max_zq = int(max_belt_z / _QUANTUM)

    routed: list[tuple[str, int, int, int]] = []
    unrouted: list[tuple[str, int, int, str]] = []
    corridor_tiles = 0
    fed_heads: set[int] = set()

    # One lane is not one net.  A rate above one belt makes the placer emit
    # several lanes on BOTH sides, and wiring only the first starves the rest --
    # `flow.lane_sourced` and `flow.conservation` both convict it.  Lanes are
    # paired one-to-one; a surplus on either side is reported, not hidden.
    pairs: list[tuple[str, int, int, int, int]] = []
    for item, src, dst, _rate in cuts:
        src_tails = list(tails[src].get(item, []))
        dst_heads = list(heads[dst].get(item, []))
        if not src_tails:
            unrouted.append((item, src, dst, "no output lane on the producing block"))
            continue
        if not dst_heads:
            unrouted.append((item, src, dst, "no entry lane on the consuming block"))
            continue
        if len(src_tails) != len(dst_heads):
            unrouted.append(
                (
                    item,
                    src,
                    dst,
                    f"lane count differs: {len(src_tails)} out, {len(dst_heads)} in; "
                    "a splitter or merge is needed to reconcile them",
                )
            )
            continue
        for tail_i, head_i in zip(src_tails, dst_heads, strict=True):
            pairs.append((item, src, dst, tail_i, head_i))

    for item, src, dst, tail_i, head_i in pairs:
        tolls = dict(penalty)
        for cell, owners in reserved.items():
            if owners <= {tail_i, head_i}:
                tolls[cell] = 0
        # A boundary belt stands inside its own block's collider halo, so the
        # halo has to release this net's own access cells or there is no way
        # out of the block at all.
        access = {
            (buildings[i].x + dx, buildings[i].y + dy)
            for i in (tail_i, head_i)
            for dx, dy, _ in _STEPS
        }
        path = _route(
            buildings[tail_i],
            buildings[head_i],
            (blocked | halo) - (access - blocked),
            tolls,
            (min_x, min_y, max_x, max_y),
            max_zq,
        )
        if path is None:
            unrouted.append((item, src, dst, "no corridor path over free ground"))
            continue
        template = buildings[tail_i]
        first = len(buildings)
        for k, (x, y, zq) in enumerate(path):
            if k + 1 < len(path):
                nx, ny, _ = path[k + 1]
                yaw = _yaw_for(nx - x, ny - y)
                nxt: int | None = first + k + 1
            else:
                # The goal set is built from the head's own free neighbours, so
                # the final corridor cell is always one step from it.
                head = buildings[head_i]
                yaw = _yaw_for(head.x - x, head.y - y)
                nxt = head_i
            buildings.append(
                replace(
                    template,
                    x=x,
                    y=y,
                    z=zq * _QUANTUM,
                    x2=None,
                    y2=None,
                    z2=None,
                    yaw=yaw,
                    yaw2=None,
                    output_obj=nxt,
                    input_obj=None,
                    # The placers' own belt chains write (own 0, peer 1); the
                    # defaults (0, 0) put two records in one `entityConnPool`
                    # cell and `game.slot_occupancy` convicts every corridor
                    # tile.  Copying the tail's fields is not enough: a tail has
                    # no output link, so its slots are unset.
                    output_from_slot=0,
                    output_to_slot=1,
                    input_from_slot=0,
                    input_to_slot=0,
                    output_offset=0,
                    input_offset=0,
                    parameters=(),
                    carries_item=item,
                    owner_strip=None,
                )
            )
            blocked.add((x, y))
        # The producing tail now feeds the corridor instead of terminating.
        fx, fy, _ = path[0]
        buildings[tail_i] = replace(
            buildings[tail_i],
            output_obj=first,
            output_from_slot=0,
            output_to_slot=1,
            yaw=_yaw_for(fx - buildings[tail_i].x, fy - buildings[tail_i].y),
        )
        corridor_tiles += len(path)
        fed_heads.add(head_i)
        routed.append((item, src, dst, len(path)))

    placement = Placement(
        buildings=tuple(buildings),
        description="hierarchical block composition (spike)",
    )
    entry_status: dict[tuple[int, str], tuple[int, int]] = {}
    for index, lanes_by_item in enumerate(heads):
        for lane_item, lane_indices in lanes_by_item.items():
            fed = sum(1 for i in lane_indices if i in fed_heads)
            entry_status[(index, lane_item)] = (fed, len(lane_indices))

    return ComposeResult(
        placement=placement,
        blocks=blocks,
        routed=routed,
        unrouted=unrouted,
        corridor_tiles=corridor_tiles,
        entry_status=entry_status,
    )


__all__ = ["ComposeResult", "compose", "Facing"]
