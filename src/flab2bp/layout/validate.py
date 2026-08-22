"""The neutral judge.

Two layout strategies compete here, so every judgement about correctness lives
outside both of them.  Nothing in this module may depend on how a placement was
produced -- it sees only the frozen ``Placement`` contract and, when available,
the ``BuildSpec`` that placement was supposed to realise.

Checks return structured :class:`Finding` objects rather than booleans, because
a failure that cannot be debugged from the report alone is barely better than no
check at all.  Rates in ``detail`` are exact ``Fraction`` values rendered as
strings -- never floats, since rounding is precisely what these checks exist to
catch.

Two tiers of check
------------------
Geometry, sorter, belt and power checks need only a ``Placement``, so they run
against anything -- including real blueprints decoded from the game, which is
what makes a negative control possible.  Spec-conformance, proliferator and flow
checks additionally need a ``BuildSpec`` and an :class:`IdMap`; without those
they are reported in ``Report.skipped`` rather than silently passing.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from fractions import Fraction

from flab2bp.dsp import catalog as cat
from flab2bp.layout.base import PlacedBuilding, Placement
from flab2bp.spec import BuildSpec, MachineGroup

__all__ = [
    "CHECKS",
    "Finding",
    "IdMap",
    "Report",
    "Severity",
    "validate",
]


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class Finding:
    check: str
    severity: Severity
    message: str
    buildings: tuple[int, ...] = ()
    detail: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Report:
    findings: tuple[Finding, ...]
    #: Check ids that were evaluated.
    checks_run: tuple[str, ...] = ()
    #: Check ids that could NOT be evaluated, and are therefore neither passed
    #: nor failed.  Surfaced explicitly so an unvalidated build never reads as a
    #: clean one.
    skipped: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not any(f.severity is Severity.ERROR for f in self.findings)

    @property
    def errors(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.WARNING)

    def by_check(self, check: str) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.check == check)


@dataclass(frozen=True, slots=True)
class IdMap:
    """Bridges FactorioLab's string ids to DSP's numeric ones.

    ``BuildSpec`` speaks in FactorioLab ids (``"assembling-machine-2"``);
    ``PlacedBuilding`` speaks in DSP ids (``2304``).  Something has to translate,
    and the validator refuses to guess.
    """

    recipes: Mapping[str, int] = field(default_factory=dict)
    items: Mapping[str, int] = field(default_factory=dict)

    def recipe_name(self, rid: int) -> str | None:
        for name, value in self.recipes.items():
            if value == rid:
                return name
        return None

    def item_name(self, iid: int) -> str | None:
        for name, value in self.items.items():
            if value == iid:
                return name
        return None


class Kind(Enum):
    MACHINE = "machine"
    BELT = "belt"
    SORTER = "sorter"
    SPLITTER = "splitter"
    POWER = "power"
    ADDON = "addon"
    OTHER = "other"


def _kind(b: PlacedBuilding) -> Kind:
    if cat.is_belt(b.item_id):
        return Kind.BELT
    if cat.is_sorter(b.item_id):
        return Kind.SORTER
    if b.item_id == cat.SPLITTER_ID:
        return Kind.SPLITTER
    try:
        info = cat.building(b.item_id)
    except KeyError:
        return Kind.OTHER
    if info.cover_radius > 0:
        return Kind.POWER
    if info.is_belt_addon:
        return Kind.ADDON
    return Kind.MACHINE


#: Kinds that draw power.  Belts are unpowered in DSP; power nodes supply rather
#: than consume.
_POWERED = {Kind.MACHINE, Kind.SORTER, Kind.SPLITTER, Kind.ADDON}


@dataclass(frozen=True, slots=True)
class BeltRun:
    """A maximal forward-linked chain of belt tiles."""

    indices: tuple[int, ...]
    tier_item_id: int

    @property
    def head(self) -> int:
        return self.indices[0]

    @property
    def tail(self) -> int:
        return self.indices[-1]


@dataclass(frozen=True)
class Context:
    placement: Placement
    spec: BuildSpec | None
    ids: IdMap | None
    soft_width: int
    kinds: tuple[Kind, ...]
    #: cell -> building indices standing on it.  Sorters are absent by design:
    #: their anchors sit *on* the buildings they serve, and the tiles they span
    #: are not exclusively theirs in this model.  Belts and splitters ARE here,
    #: so sorter anchors and belt links can be resolved against them.
    occupancy: Mapping[tuple[int, int, int], tuple[int, ...]]
    #: cell -> building indices that exclusively *reserve* it.  Belt-integrated
    #: buildings (belts, sorters, splitters) are absent; this is what
    #: ``geom.overlap`` judges.
    blocking: Mapping[tuple[int, int, int], tuple[int, ...]]
    runs: tuple[BeltRun, ...]
    run_of: Mapping[int, int]

    def of_kind(self, kind: Kind) -> Iterator[tuple[int, PlacedBuilding]]:
        for i, b in enumerate(self.placement.buildings):
            if self.kinds[i] is kind:
                yield i, b

    def group_for(self, index: int) -> MachineGroup | None:
        """The ``MachineGroup`` a placed machine belongs to, if determinable."""
        if self.spec is None or self.ids is None:
            return None
        b = self.placement.buildings[index]
        name = self.ids.recipe_name(b.recipe_id)
        if name is None:
            return None
        for g in self.spec.groups:
            if g.recipe_id == name:
                return g
        return None


def _occupied_tiles(b: PlacedBuilding, kind: Kind) -> list[tuple[int, int, int]]:
    if kind is Kind.SORTER:
        return []
    try:
        if not cat.building(b.item_id).occupies_tiles:
            return []  # belt addon: mounts on a belt, consumes no cell
    except KeyError:
        pass
    return b.tiles()


def _build_runs(
    buildings: Sequence[PlacedBuilding], kinds: Sequence[Kind]
) -> tuple[tuple[BeltRun, ...], dict[int, int]]:
    is_belt = [k is Kind.BELT for k in kinds]
    succ: dict[int, int] = {}
    preds: dict[int, list[int]] = defaultdict(list)
    for i, b in enumerate(buildings):
        if not is_belt[i]:
            continue
        o = b.output_obj
        if o is not None and 0 <= o < len(buildings) and is_belt[o]:
            succ[i] = o
            preds[o].append(i)

    def starts_run(i: int) -> bool:
        return len(preds[i]) != 1

    runs: list[BeltRun] = []
    run_of: dict[int, int] = {}
    seen: set[int] = set()
    heads = [i for i in range(len(buildings)) if is_belt[i] and starts_run(i)]
    for h in heads:
        chain: list[int] = []
        cur: int | None = h
        while cur is not None and cur not in seen:
            seen.add(cur)
            chain.append(cur)
            nxt = succ.get(cur)
            cur = nxt if nxt is not None and len(preds[nxt]) == 1 else None
        if chain:
            idx = len(runs)
            runs.append(BeltRun(tuple(chain), buildings[chain[0]].item_id))
            for c in chain:
                run_of[c] = idx
    # Any belt not reached above sits on a pure cycle; give each cycle its own
    # run so belt.acyclic can report it rather than the run builder crashing.
    for i in range(len(buildings)):
        if is_belt[i] and i not in seen:
            chain = []
            cur = i
            while cur not in seen:
                seen.add(cur)
                chain.append(cur)
                nxt = succ.get(cur)
                if nxt is None:
                    break
                cur = nxt
            if chain:
                idx = len(runs)
                runs.append(BeltRun(tuple(chain), buildings[chain[0]].item_id))
                for c in chain:
                    run_of[c] = idx
    return tuple(runs), run_of


def _context(
    placement: Placement, spec: BuildSpec | None, ids: IdMap | None, soft_width: int
) -> Context:
    kinds = tuple(_kind(b) for b in placement.buildings)
    occ: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    blocking: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for i, b in enumerate(placement.buildings):
        for cell in _occupied_tiles(b, kinds[i]):
            occ[cell].append(i)
            if not cat.is_belt_integrated(b.item_id):
                blocking[cell].append(i)
    runs, run_of = _build_runs(placement.buildings, kinds)
    return Context(
        placement=placement,
        spec=spec,
        ids=ids,
        soft_width=soft_width,
        kinds=kinds,
        occupancy={k: tuple(v) for k, v in occ.items()},
        blocking={k: tuple(v) for k, v in blocking.items()},
        runs=runs,
        run_of=run_of,
    )


# --- registry --------------------------------------------------------------

Check = Callable[[Context], Iterable[Finding]]
CHECKS: dict[str, Check] = {}
#: Check ids that require a ``BuildSpec`` and an ``IdMap``.
NEEDS_SPEC: set[str] = set()


def check(cid: str, *, needs_spec: bool = False) -> Callable[[Check], Check]:
    def register(fn: Check) -> Check:
        CHECKS[cid] = fn
        if needs_spec:
            NEEDS_SPEC.add(cid)
        return fn

    return register


# --- geometry --------------------------------------------------------------


@check("geom.overlap")
def _overlap(ctx: Context) -> Iterable[Finding]:
    """No two buildings claim the same cell -- except those that share by design.

    Belts, sorters and splitters are *belt-integrated*: they share a tile rather
    than reserving one.  Splitters sit exactly co-located with a belt (measured
    dx = dy = 0.00) and a sorter's anchors rest on the buildings it serves, so
    none of them enter the blocking map at all.  Counting them would flag
    blueprints the game itself produced -- in the corpus this is what accounts
    for a splitter's footprint reaching into an adjacent Matrix Lab and a belt
    running through a Storage Tank, both of which appear in blueprints that work
    in game.

    Belt-on-belt collisions are still caught, by ``geom.belt_single_occupancy``.
    """
    for cell, occupants in sorted(ctx.blocking.items()):
        if len(occupants) > 1:
            yield Finding(
                "geom.overlap",
                Severity.ERROR,
                f"{len(occupants)} buildings share cell {cell}",
                tuple(occupants),
                {"cell": str(cell)},
            )


@check("geom.belt_single_occupancy")
def _belt_single(ctx: Context) -> Iterable[Finding]:
    for cell, occupants in sorted(ctx.occupancy.items()):
        belts = [i for i in occupants if ctx.kinds[i] is Kind.BELT]
        if len(belts) > 1:
            yield Finding(
                "geom.belt_single_occupancy",
                Severity.ERROR,
                f"{len(belts)} belts share cell {cell}; one belt per tile",
                tuple(belts),
                {"cell": str(cell)},
            )


@check("geom.machine_ground")
def _machine_ground(ctx: Context) -> Iterable[Finding]:
    for i, b in ctx.of_kind(Kind.MACHINE):
        if b.z != 0:
            yield Finding(
                "geom.machine_ground",
                Severity.ERROR,
                f"machine {i} sits at altitude {b.z}; only belts may leave the ground",
                (i,),
                {"z": b.z},
            )


@check("geom.altitude_range")
def _altitude_range(ctx: Context) -> Iterable[Finding]:
    for i, b in enumerate(ctx.placement.buildings):
        if b.z < 0 or b.z >= cat.MAX_BELT_STACK_LEVELS:
            yield Finding(
                "geom.altitude_range",
                Severity.ERROR,
                f"building {i} at altitude {b.z}, outside 0..{cat.MAX_BELT_STACK_LEVELS - 1}",
                (i,),
                {"z": b.z, "max": cat.MAX_BELT_STACK_LEVELS - 1},
            )


@check("geom.altitude_step")
def _altitude_step(ctx: Context) -> Iterable[Finding]:
    bs = ctx.placement.buildings
    for i, b in ctx.of_kind(Kind.BELT):
        o = b.output_obj
        if o is None or not (0 <= o < len(bs)) or ctx.kinds[o] is not Kind.BELT:
            continue
        dz = abs(bs[o].z - b.z)
        if dz > 1:
            yield Finding(
                "geom.altitude_step",
                Severity.ERROR,
                f"belt {i} steps {dz} altitude levels to belt {o}; at most one per tile",
                (i, o),
                {"dz": dz},
            )


@check("geom.bounds")
def _bounds(ctx: Context) -> Iterable[Finding]:
    n = len(ctx.placement.buildings)
    if n > 1_048_576:
        yield Finding(
            "geom.bounds",
            Severity.ERROR,
            f"{n} buildings exceeds the format cap of 1048576",
            (),
            {"buildings": n},
        )
    for i, b in enumerate(ctx.placement.buildings):
        if len(b.parameters) > 32768:
            yield Finding(
                "geom.bounds",
                Severity.ERROR,
                f"building {i} carries {len(b.parameters)} parameters, cap is 32768",
                (i,),
                {"parameters": len(b.parameters)},
            )
    if not ctx.placement.buildings:
        return
    min_x, min_y, max_x, max_y = ctx.placement.bounds
    w, h = max_x - min_x + 1, max_y - min_y + 1
    if max(w, h) > ctx.soft_width:
        yield Finding(
            "geom.bounds",
            Severity.WARNING,
            f"extent {w}x{h} exceeds {ctx.soft_width} tiles; a blueprint this wide "
            f"distorts with planet curvature and may fail to paste near the poles",
            (),
            {"width": w, "height": h, "soft_width": ctx.soft_width},
        )


# --- sorters ---------------------------------------------------------------


def _anchors(b: PlacedBuilding) -> tuple[tuple[int, int, int], tuple[int, int, int]] | None:
    if b.x2 is None or b.y2 is None or b.z2 is None:
        return None
    return ((b.x, b.y, b.z), (b.x2, b.y2, b.z2))


@check("sorter.anchors_present")
def _anchors_present(ctx: Context) -> Iterable[Finding]:
    for i, b in ctx.of_kind(Kind.SORTER):
        if _anchors(b) is None:
            yield Finding(
                "sorter.anchors_present",
                Severity.ERROR,
                f"sorter {i} is missing its second anchor",
                (i,),
            )


@check("sorter.reach")
def _reach(ctx: Context) -> Iterable[Finding]:
    for i, b in ctx.of_kind(Kind.SORTER):
        a = _anchors(b)
        if a is None:
            continue
        (x1, y1, _), (x2, y2, _) = a
        dx, dy = abs(x2 - x1), abs(y2 - y1)
        if dx and dy:
            yield Finding(
                "sorter.reach",
                Severity.ERROR,
                f"sorter {i} runs diagonally ({dx},{dy}); DSP sorters are straight-line",
                (i,),
                {"dx": dx, "dy": dy},
            )
            continue
        # Chebyshev, not Manhattan. Measured over all 1,288 sorters in the
        # fixture corpus: Manhattan (dx+dy) reports spans of 4 on blueprints the
        # game itself produced -- four sorters in falk-v7-mall-full sit at
        # dx~3.3, dy~0.2, where summing the orthogonal jitter pushes them past
        # the limit. Chebyshev tops out at exactly 3, matching SORTER_MAX_REACH,
        # as does Euclidean. Manhattan was flagging valid blueprints as broken.
        span = max(dx, dy)
        if span < 1 or span > cat.SORTER_MAX_REACH:
            yield Finding(
                "sorter.reach",
                Severity.ERROR,
                f"sorter {i} spans {span} tiles, outside 1..{cat.SORTER_MAX_REACH}",
                (i,),
                {"span": span, "max": cat.SORTER_MAX_REACH},
            )


@check("sorter.altitude")
def _sorter_altitude(ctx: Context) -> Iterable[Finding]:
    if cat.SORTER_SPANS_ALTITUDE:
        return
    for i, b in ctx.of_kind(Kind.SORTER):
        a = _anchors(b)
        if a is None:
            continue
        (_, _, z1), (_, _, z2) = a
        if z1 != z2:
            yield Finding(
                "sorter.altitude",
                Severity.ERROR,
                f"sorter {i} spans altitudes {z1}->{z2}; sorters never change level "
                f"(z2-z is exactly 0 for all 1288 sorters in the real corpus)",
                (i,),
                {"z": z1, "z2": z2},
            )


@check("sorter.endpoints")
def _endpoints(ctx: Context) -> Iterable[Finding]:
    for i, b in ctx.of_kind(Kind.SORTER):
        a = _anchors(b)
        if a is None:
            continue
        for label, cell in (("input", a[0]), ("output", a[1])):
            occupants = [j for j in ctx.occupancy.get(cell, ()) if j != i]
            if not occupants:
                yield Finding(
                    "sorter.endpoints",
                    Severity.ERROR,
                    f"sorter {i}'s {label} anchor at {cell} lands on empty space",
                    (i,),
                    {"end": label, "cell": str(cell)},
                )


def _addon_at(ctx: Context, link: int, cell: tuple[int, int, int]) -> bool:
    """Is ``link`` a belt addon mounted at ``cell``?

    Belt addons -- the Spray Coater is the one that matters -- consume no grid
    tile, so ``_occupied_tiles`` deliberately excludes them and they never appear
    in the occupancy map.  A sorter feeding a coater therefore names a building
    the anchor cell appears not to hold, while the cell lists only the belt
    underneath it.  That is the correct geometry, not a violation: the coater and
    the belt genuinely share the tile.
    """
    if not (0 <= link < len(ctx.placement.buildings)):
        return False
    if ctx.kinds[link] is not Kind.ADDON:
        return False
    b = ctx.placement.buildings[link]
    return (b.x, b.y, b.z) == cell


@check("sorter.endpoint_pair")
def _endpoint_pair(ctx: Context) -> Iterable[Finding]:
    for i, b in ctx.of_kind(Kind.SORTER):
        a = _anchors(b)
        if a is None:
            continue
        for label, cell, link in (
            ("input", a[0], b.input_obj),
            ("output", a[1], b.output_obj),
        ):
            if link is None:
                continue
            occupants = [j for j in ctx.occupancy.get(cell, ()) if j != i]
            if occupants and link not in occupants and not _addon_at(ctx, link, cell):
                yield Finding(
                    "sorter.endpoint_pair",
                    Severity.ERROR,
                    f"sorter {i} names building {link} as its {label}, but that anchor "
                    f"sits on {occupants}",
                    (i, link),
                    {"end": label, "named": link, "under_anchor": str(occupants)},
                )


@check("sorter.filter")
def _filter(ctx: Context) -> Iterable[Finding]:
    bs = ctx.placement.buildings
    for i, b in ctx.of_kind(Kind.SORTER):
        if b.filter_id == 0:
            continue
        for link in (b.input_obj, b.output_obj):
            if link is None or not (0 <= link < len(bs)):
                continue
            if ctx.kinds[link] is Kind.BELT and bs[link].item_id == b.filter_id:
                yield Finding(
                    "sorter.filter",
                    Severity.WARNING,
                    f"sorter {i} filters on {b.filter_id}, which is a belt tier id, "
                    f"not an item -- almost certainly a bug",
                    (i,),
                    {"filter_id": b.filter_id},
                )


# --- belts -----------------------------------------------------------------


@check("belt.continuity")
def _continuity(ctx: Context) -> Iterable[Finding]:
    bs = ctx.placement.buildings
    for i, b in ctx.of_kind(Kind.BELT):
        o = b.output_obj
        if o is None:
            continue
        if not (0 <= o < len(bs)):
            yield Finding(
                "belt.continuity",
                Severity.ERROR,
                f"belt {i} links to {o}, which is not a building index",
                (i,),
                {"output_obj": o},
            )


@check("belt.link_adjacent")
def _link_adjacent(ctx: Context) -> Iterable[Finding]:
    bs = ctx.placement.buildings
    for i, b in ctx.of_kind(Kind.BELT):
        o = b.output_obj
        if o is None or not (0 <= o < len(bs)):
            continue
        target = bs[o]
        cells = _occupied_tiles(target, ctx.kinds[o]) or [(target.x, target.y, target.z)]
        if not any(abs(cx - b.x) + abs(cy - b.y) <= 1 for cx, cy, _ in cells):
            yield Finding(
                "belt.link_adjacent",
                Severity.ERROR,
                f"belt {i} at ({b.x},{b.y}) links to building {o}, which is not adjacent",
                (i, o),
                {"from": f"({b.x},{b.y})", "to": f"({target.x},{target.y})"},
            )


@check("belt.acyclic")
def _acyclic(ctx: Context) -> Iterable[Finding]:
    bs = ctx.placement.buildings
    colour: dict[int, int] = {}

    def walk(start: int) -> list[int] | None:
        """Follow a belt chain, reporting a genuine cycle only.

        Colour 1 means "on the path currently being walked", colour 2 means
        "settled, provably not on a cycle".  Every exit therefore has to settle
        the path it walked: leaving nodes at colour 1 after returning made the
        NEXT chain that merged into them look like a cycle, and DSP belts merge
        natively -- two chains pointing at one tile is how many-to-one is built,
        and the router prefers exactly that -- so this fired on correct layouts.
        """
        path: list[int] = []
        cur = start
        while True:
            if colour.get(cur) == 1:
                # Colour 1 is only ever set by THIS walk, so reaching it means a
                # real cycle, and `cur` is necessarily on `path`.
                cycle = path[path.index(cur) :] if cur in path else [cur]
                for p in path:
                    colour[p] = 2
                return cycle
            if colour.get(cur) == 2:
                for p in path:  # merged into settled ground: settle this path too
                    colour[p] = 2
                return None
            colour[cur] = 1
            path.append(cur)
            nxt = bs[cur].output_obj
            if nxt is None or not (0 <= nxt < len(bs)) or ctx.kinds[nxt] is not Kind.BELT:
                for p in path:
                    colour[p] = 2
                return None
            cur = nxt

    for i, _ in ctx.of_kind(Kind.BELT):
        if colour.get(i):
            continue
        cycle = walk(i)
        if cycle:
            yield Finding(
                "belt.acyclic",
                Severity.ERROR,
                f"belt chain forms a cycle through {cycle}",
                tuple(cycle),
                {"cycle": str(cycle)},
            )
            for c in cycle:
                colour[c] = 2


@check("belt.termination")
def _termination(ctx: Context) -> Iterable[Finding]:
    bs = ctx.placement.buildings
    consumers: set[int] = set()
    for _, s in ctx.of_kind(Kind.SORTER):
        if s.input_obj is not None:
            consumers.add(s.input_obj)
    for run in ctx.runs:
        tail = run.tail
        o = bs[tail].output_obj
        if o is None and tail not in consumers:
            yield Finding(
                "belt.termination",
                Severity.WARNING,
                f"belt run ending at {tail} stops without a consumer or onward link",
                (tail,),
                {"tail": tail},
            )


# --- power -----------------------------------------------------------------


def _tower_centres(ctx: Context) -> list[tuple[int, Fraction, Fraction, Fraction, Fraction]]:
    out = []
    for i, b in ctx.of_kind(Kind.POWER):
        info = cat.building(b.item_id)
        cx = Fraction(2 * b.x + b.width, 2)
        cy = Fraction(2 * b.y + b.height, 2)
        out.append((i, cx, cy, info.cover_radius, info.connect_distance))
    return out


@check("power.coverage")
def _coverage(ctx: Context) -> Iterable[Finding]:
    towers = _tower_centres(ctx)
    for i, b in enumerate(ctx.placement.buildings):
        if ctx.kinds[i] not in _POWERED:
            continue
        for tx, ty, _tz in b.tiles():
            cx, cy = Fraction(2 * tx + 1, 2), Fraction(2 * ty + 1, 2)
            if not any(
                (cx - ox) ** 2 + (cy - oy) ** 2 <= r**2 for _, ox, oy, r, _ in towers
            ):
                yield Finding(
                    "power.coverage",
                    Severity.ERROR,
                    f"building {i} has tile ({tx},{ty}) outside every tower's supply "
                    f"radius; it would sit unpowered",
                    (i,),
                    {"tile": f"({tx},{ty})", "towers": len(towers)},
                )
                break


@check("power.connectivity")
def _connectivity(ctx: Context) -> Iterable[Finding]:
    towers = _tower_centres(ctx)
    if len(towers) < 2:
        return
    n = len(towers)
    adj: dict[int, list[int]] = {k: [] for k in range(n)}
    for a in range(n):
        for b in range(a + 1, n):
            _, ax, ay, _, alink = towers[a]
            _, bx, by, _, blink = towers[b]
            reach = min(alink, blink)
            if (ax - bx) ** 2 + (ay - by) ** 2 <= reach**2:
                adj[a].append(b)
                adj[b].append(a)
    seen = {0}
    q = deque([0])
    while q:
        cur = q.popleft()
        for nb in adj[cur]:
            if nb not in seen:
                seen.add(nb)
                q.append(nb)
    if len(seen) != n:
        stranded = tuple(towers[k][0] for k in range(n) if k not in seen)
        yield Finding(
            "power.connectivity",
            Severity.ERROR,
            f"{len(stranded)} of {n} power towers are not linked into the main network",
            stranded,
            {"stranded": len(stranded), "total": n},
        )


# --- machine conformance ---------------------------------------------------


@check("machine.recipe_valid")
def _recipe_valid(ctx: Context) -> Iterable[Finding]:
    for i, b in ctx.of_kind(Kind.MACHINE):
        if b.recipe_id == 0:
            yield Finding(
                "machine.recipe_valid",
                Severity.ERROR,
                f"machine {i} has no recipe set; it would sit idle",
                (i,),
                {"item_id": b.item_id},
            )


@check("machine.inputs_supplied", needs_spec=True)
def _inputs_supplied(ctx: Context) -> Iterable[Finding]:
    """Every ingredient has a sorter delivering it.

    A sorter carries one item type, so a machine needing *k* distinct
    ingredients needs at least *k* sorters feeding it.  That is checkable
    without per-lane item labelling, and it catches the failure that matters:
    a strategy that wired up some inputs and quietly forgot the rest.
    """
    assert ctx.spec is not None
    feeds: dict[int, int] = defaultdict(int)
    for _i, s in ctx.of_kind(Kind.SORTER):
        if s.output_obj is not None:
            feeds[s.output_obj] += 1
    for i, _b in ctx.of_kind(Kind.MACHINE):
        g = ctx.group_for(i)
        if g is None:
            continue
        need = len(g.inputs_per_machine)
        if need and feeds[i] < need:
            yield Finding(
                "machine.inputs_supplied",
                Severity.ERROR,
                f"machine {i} runs {g.recipe_id}, which needs {need} distinct "
                f"ingredients, but only {feeds[i]} sorters feed it",
                (i,),
                {"recipe": g.recipe_id, "needed": need, "sorters": feeds[i]},
            )


@check("machine.output_removed", needs_spec=True)
def _output_removed(ctx: Context) -> Iterable[Finding]:
    """Every product has a sorter taking it away, or the machine jams."""
    assert ctx.spec is not None
    drains: dict[int, int] = defaultdict(int)
    for _i, s in ctx.of_kind(Kind.SORTER):
        if s.input_obj is not None:
            drains[s.input_obj] += 1
    for i, _b in ctx.of_kind(Kind.MACHINE):
        g = ctx.group_for(i)
        if g is None:
            continue
        need = len(g.outputs_per_machine)
        if need and drains[i] < need:
            yield Finding(
                "machine.output_removed",
                Severity.ERROR,
                f"machine {i} runs {g.recipe_id}, which yields {need} distinct "
                f"products, but only {drains[i]} sorters drain it; it would back up",
                (i,),
                {"recipe": g.recipe_id, "products": need, "sorters": drains[i]},
            )


# --- spec conformance ------------------------------------------------------


@check("spec.machine_counts", needs_spec=True)
def _machine_counts(ctx: Context) -> Iterable[Finding]:
    assert ctx.spec is not None and ctx.ids is not None
    want: dict[tuple[int, int], int] = {}
    for g in ctx.spec.groups:
        rid = ctx.ids.recipes.get(g.recipe_id)
        mid = ctx.ids.items.get(g.machine_item_id)
        if rid is None or mid is None:
            yield Finding(
                "spec.machine_counts",
                Severity.WARNING,
                f"no id mapping for recipe {g.recipe_id!r} / machine "
                f"{g.machine_item_id!r}; cannot verify its count",
                (),
                {"recipe": g.recipe_id, "machine": g.machine_item_id},
            )
            continue
        want[(rid, mid)] = want.get((rid, mid), 0) + g.count
    got: dict[tuple[int, int], int] = {}
    for _i, b in ctx.of_kind(Kind.MACHINE):
        key = (b.recipe_id, b.item_id)
        got[key] = got.get(key, 0) + 1
    for key in sorted(set(want) | set(got)):
        w, g_ = want.get(key, 0), got.get(key, 0)
        if w != g_:
            yield Finding(
                "spec.machine_counts",
                Severity.ERROR,
                f"recipe {key[0]} on machine {key[1]}: spec demands {w}, placement has {g_}",
                (),
                {"recipe_id": key[0], "machine_id": key[1], "wanted": w, "got": g_},
            )


@check("spec.proliferator_input", needs_spec=True)
def _proliferator_input(ctx: Context) -> Iterable[Finding]:
    assert ctx.spec is not None
    if not ctx.spec.is_proliferated:
        return
    if not any(k.startswith("proliferator") for k in ctx.spec.external_inputs):
        yield Finding(
            "spec.proliferator_input",
            Severity.ERROR,
            "machines are proliferated but no proliferator appears in external_inputs; "
            "proliferator must be belted in, never produced inside the blueprint",
            (),
            {"external_inputs": sorted(ctx.spec.external_inputs)},
        )


@check("prolif.belt_required_edges_not_direct_inserted", needs_spec=True)
def _belt_required(ctx: Context) -> Iterable[Finding]:
    """A proliferated consumer's inputs must arrive on a belt.

    Spray is applied by a belt-mounted coater and does not survive crafting, so
    a directly-inserted edge can never be sprayed.  Direct-inserting one of
    these edges yields a blueprint that pastes cleanly and then silently
    under-produces -- which is why this is an ERROR, not a warning.
    """
    assert ctx.spec is not None and ctx.ids is not None
    if not ctx.spec.belt_required_edges:
        return
    bs = ctx.placement.buildings
    for i, s in ctx.of_kind(Kind.SORTER):
        src, dst = s.input_obj, s.output_obj
        if src is None or dst is None:
            continue
        if not (0 <= src < len(bs) and 0 <= dst < len(bs)):
            continue
        if ctx.kinds[src] is not Kind.MACHINE or ctx.kinds[dst] is not Kind.MACHINE:
            continue  # a belt is involved somewhere; not a direct insert
        producer = ctx.ids.recipe_name(bs[src].recipe_id)
        consumer = ctx.ids.recipe_name(bs[dst].recipe_id)
        if producer is None or consumer is None:
            continue
        if (producer, consumer) in ctx.spec.belt_required_edges:
            yield Finding(
                "prolif.belt_required_edges_not_direct_inserted",
                Severity.ERROR,
                f"edge {producer} -> {consumer} is direct-inserted by sorter {i}, but "
                f"{consumer} is proliferated and its inputs must arrive on a belt to be "
                f"sprayed; this build would silently under-produce",
                (i, src, dst),
                {"producer": producer, "consumer": consumer},
            )


@check("prolif.coaters_are_supplied", needs_spec=True)
def _coaters_supplied(ctx: Context) -> Iterable[Finding]:
    """Every Spray Coater must be able to get proliferator.

    A coater mounted on a belt with nothing feeding it proliferator sprays
    nothing, so every proliferated recipe quietly runs unproliferated and the
    build misses its rate.  Nothing about the blueprint looks wrong: it pastes,
    the machines run, and the numbers are simply lower than the spec promised.

    Two separate ways to fail, reported separately because they have different
    fixes: no proliferator lane exists anywhere (the router never made one), or
    a lane exists but some coater has no sorter drawing from it.
    """
    assert ctx.spec is not None
    coaters = [
        (i, b)
        for i, b in enumerate(ctx.placement.buildings)
        if b.item_id == cat.SPRAY_COATER_ID
    ]
    if not coaters:
        return

    prolif_items = {
        item for item in ctx.spec.external_inputs if item.startswith("proliferator")
    }
    supplying_belts = {
        i
        for i, b in enumerate(ctx.placement.buildings)
        if ctx.kinds[i] is Kind.BELT and b.carries_item in prolif_items
    }

    if prolif_items and not supplying_belts:
        yield Finding(
            "prolif.coaters_are_supplied",
            Severity.ERROR,
            f"{len(coaters)} spray coater(s) placed but no belt carries "
            f"{sorted(prolif_items)}; they would spray nothing and every "
            f"proliferated recipe would silently run unproliferated",
            tuple(i for i, _ in coaters),
            {"coaters": len(coaters), "proliferator_items": sorted(prolif_items)},
        )
        return

    fed = {
        s.output_obj
        for _, s in ctx.of_kind(Kind.SORTER)
        if s.output_obj is not None and s.input_obj in supplying_belts
    }
    starved = [i for i, _ in coaters if i not in fed]
    if starved:
        yield Finding(
            "prolif.coaters_are_supplied",
            Severity.ERROR,
            f"{len(starved)} of {len(coaters)} spray coaters have no sorter drawing "
            f"proliferator from a supplying belt",
            tuple(starved),
            {"starved": len(starved), "total": len(coaters)},
        )


# --- flow ------------------------------------------------------------------


@check("flow.conservation", needs_spec=True)
def _conservation(ctx: Context) -> Iterable[Finding]:
    """Production minus consumption balances, in exact rational arithmetic.

    Independent of any geometry: a cheap arithmetic cross-check that catches
    spec-vs-placement drift a flow model would happily rationalise away.
    """
    assert ctx.spec is not None
    net: dict[str, Fraction] = defaultdict(Fraction)
    for g in ctx.spec.groups:
        for item, rate in g.outputs_per_machine.items():
            net[item] += rate * g.count
        for item, rate in g.inputs_per_machine.items():
            net[item] -= rate * g.count
    for item, rate in ctx.spec.external_inputs.items():
        net[item] += rate
    for item, rate in ctx.spec.outputs.items():
        net[item] -= rate
    for item in sorted(net):
        if net[item] < 0:
            yield Finding(
                "flow.conservation",
                Severity.ERROR,
                f"{item} is over-consumed by {net[item]} items/s; demand exceeds supply",
                (),
                {"item": item, "net": str(net[item])},
            )


@check("flow.belt_capacity", needs_spec=True)
def _belt_capacity(ctx: Context) -> Iterable[Finding]:
    """No belt run may be asked to carry more than its tier sustains."""
    assert ctx.spec is not None
    demand = _run_demand(ctx)
    for ridx, required in sorted(demand.items()):
        run = ctx.runs[ridx]
        capacity = cat.BELT_RATE.get(run.tier_item_id)
        if capacity is None or required <= capacity:
            continue
        yield Finding(
            "flow.belt_capacity",
            Severity.ERROR,
            f"belt run {ridx} must carry {required} items/s but its tier sustains "
            f"only {capacity}",
            run.indices,
            {"run": ridx, "required": str(required), "capacity": str(capacity)},
        )


@check("flow.sorter_capacity", needs_spec=True)
def _sorter_capacity(ctx: Context) -> Iterable[Finding]:
    """No sorter may be asked to move more than its tier sustains at its span."""
    assert ctx.spec is not None
    for i, s in ctx.of_kind(Kind.SORTER):
        a = _anchors(s)
        if a is None:
            continue
        (x1, y1, _), (x2, y2, _) = a
        span = abs(x2 - x1) + abs(y2 - y1)
        if span < 1 or span > cat.SORTER_MAX_REACH:
            continue  # sorter.reach already reported this
        if s.item_id not in cat.SORTER_RATE_AT_1:
            continue
        capacity = cat.sorter_rate(s.item_id, span)
        required = _sorter_demand(ctx, i)
        if required is None or required <= capacity:
            continue
        yield Finding(
            "flow.sorter_capacity",
            Severity.ERROR,
            f"sorter {i} must move {required} items/s across {span} tiles but sustains "
            f"only {capacity}",
            (i,) + tuple(x for x in (s.input_obj, s.output_obj) if x is not None),
            {
                "sorter": i,
                "span": span,
                "required": str(required),
                "capacity": str(capacity),
            },
        )


def _sorter_demand(ctx: Context, index: int) -> Fraction | None:
    """Items/second one sorter must move.

    Feeding a machine, the demand is that machine's input rate divided across
    the sorters that feed it; draining one, its output rate divided across the
    sorters draining it.  Dividing rather than assuming one sorter per machine
    is what keeps this honest when a strategy parallelises a hot connection.
    """
    bs = ctx.placement.buildings
    s = bs[index]
    src, dst = s.input_obj, s.output_obj
    if src is None or dst is None:
        return None
    if not (0 <= src < len(bs) and 0 <= dst < len(bs)):
        return None
    if ctx.kinds[dst] is Kind.MACHINE:
        g = ctx.group_for(dst)
        if g is None:
            return None
        total = sum(g.inputs_per_machine.values(), Fraction(0))
        share = sum(1 for _j, o in ctx.of_kind(Kind.SORTER) if o.output_obj == dst) or 1
        return total / share
    if ctx.kinds[src] is Kind.MACHINE:
        g = ctx.group_for(src)
        if g is None:
            return None
        total = sum(g.outputs_per_machine.values(), Fraction(0))
        share = sum(1 for _j, o in ctx.of_kind(Kind.SORTER) if o.input_obj == src) or 1
        return total / share
    return None


def _run_demand(ctx: Context) -> dict[int, Fraction]:
    """Items/second each belt run must carry, from its consumers' demands."""
    demand: dict[int, Fraction] = defaultdict(Fraction)
    for i, s in ctx.of_kind(Kind.SORTER):
        d = _sorter_demand(ctx, i)
        if d is None:
            continue
        for link in (s.input_obj, s.output_obj):
            if link is not None and link in ctx.run_of:
                demand[ctx.run_of[link]] += d
    return dict(demand)


@check("flow.headroom", needs_spec=True)
def _headroom(ctx: Context) -> Iterable[Finding]:
    """Saturation per run, as an exact fraction.

    INFO rather than ERROR: the user chose "throughput-correct" over
    "throughput-correct and no starvation", so a lane tapped in series is
    accepted as long as aggregate capacity suffices.  Reporting headroom makes
    near-saturation visible before it becomes a bug.
    """
    assert ctx.spec is not None
    for ridx, required in sorted(_run_demand(ctx).items()):
        capacity = cat.BELT_RATE.get(ctx.runs[ridx].tier_item_id)
        if not capacity:
            continue
        yield Finding(
            "flow.headroom",
            Severity.INFO,
            f"belt run {ridx} carries {required} of {capacity} items/s",
            ctx.runs[ridx].indices,
            {"run": ridx, "required": str(required), "capacity": str(capacity)},
        )


# --- entry point -----------------------------------------------------------


def validate(
    placement: Placement,
    spec: BuildSpec | None = None,
    *,
    ids: IdMap | None = None,
    soft_width: int = 256,
    only: Iterable[str] | None = None,
    expect_power: bool = True,
) -> Report:
    """Judge ``placement``, optionally against the ``spec`` it should realise.

    Without a ``spec`` and ``ids``, spec-conformance and flow checks cannot run;
    they are listed in ``Report.skipped`` so an unvalidated build never reads as
    a clean one.

    ``expect_power=False`` declares that this placement was built with power
    disabled, so the power checks are *skipped* rather than reporting every
    machine as unpowered.  It is a caller declaration on purpose: the
    validator inferring it from "there are no towers" would make a dropped
    tower -- a real bug -- indistinguishable from a deliberate ``--no-power``
    build, and silently stop detecting it.
    """
    wanted = set(only) if only is not None else None
    ctx = _context(placement, spec, ids, soft_width)
    have_spec = spec is not None and ids is not None

    findings: list[Finding] = []
    ran: list[str] = []
    skipped: list[str] = []
    for cid, fn in CHECKS.items():
        if wanted is not None and cid not in wanted:
            continue
        if not expect_power and cid.startswith('power.'):
            skipped.append(cid)
            continue
        if cid in NEEDS_SPEC and not have_spec:
            skipped.append(cid)
            continue
        ran.append(cid)
        findings.extend(fn(ctx))
    return Report(tuple(findings), tuple(ran), tuple(skipped))
