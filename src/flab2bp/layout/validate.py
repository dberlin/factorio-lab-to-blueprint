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
from flab2bp.layout import junction as junc
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


#: Tags for the two node types in the flow graph.  A junction is a node in its
#: own right rather than an edge between runs because its ARITY is what the rate
#: arithmetic needs: a splitter with two inputs feeding one output charges each
#: input half the load, and collapsing it into a plain run-to-run edge would
#: charge both of them all of it -- inventing a violation on a lane that is
#: correctly split.
RUN = 0
JUNCTION = 1

#: ``(RUN, run index)`` or ``(JUNCTION, building index)``.
Node = tuple[int, int]

#: Rates keyed by FactorioLab item id; ``None`` is the unattributable bucket.
ItemRates = Mapping[str | None, Fraction]


def _dedup(seq: Iterable[Node]) -> tuple[Node, ...]:
    return tuple(dict.fromkeys(seq))


def _dedup_ints(seq: Iterable[int]) -> tuple[int, ...]:
    return tuple(dict.fromkeys(seq))


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
    #: splitter index -> belts that FEED it (they name it as ``output_obj``).
    #:
    #: A splitter is a run boundary -- ``_build_runs`` chains belt to belt only
    #: -- so without these two maps every run leaving a junction reads as
    #: unsourced and every run entering one reads as unterminated.  That would
    #: report the splitter, the whole point of which is to source several runs
    #: from one, as the very defect it fixes.
    junction_in: Mapping[int, tuple[int, ...]]
    #: splitter index -> belts that DRAW from it (they name it as ``input_obj``).
    junction_out: Mapping[int, tuple[int, ...]]
    #: Flow graph over runs and junctions.  Every check that reasons about what
    #: a lane must carry, what it may be fed by, or where it ends needs to cross
    #: a junction to answer the question; before this existed each of them
    #: stopped dead at one and read the far side as unconnected.
    succ: Mapping[Node, tuple[Node, ...]]
    pred: Mapping[Node, tuple[Node, ...]]

    def junctions_feeding(self, run: int) -> tuple[int, ...]:
        """Splitters that put items onto ``run``.

        A run is fed by a junction when its HEAD draws from one.  Only the head
        can: every other belt in a run has exactly one belt predecessor, which
        is what made it part of the run rather than the start of a new one.
        """
        head = self.runs[run].head
        b = self.placement.buildings[head]
        if b.input_obj is None:
            return ()
        if self.kinds[b.input_obj] is not Kind.SPLITTER:
            return ()
        return (b.input_obj,)

    def runs_feeding_junction(self, junction: int) -> tuple[int, ...]:
        """Runs that put items into ``junction``."""
        return tuple(
            dict.fromkeys(
                self.run_of[b] for b in self.junction_in.get(junction, ()) if b in self.run_of
            )
        )

    def runs_drawing_from_junction(self, junction: int) -> tuple[int, ...]:
        """Runs that take items out of ``junction``."""
        return tuple(
            dict.fromkeys(
                self.run_of[b] for b in self.junction_out.get(junction, ()) if b in self.run_of
            )
        )

    def junction_attachments(self, junction: int) -> tuple[int, ...]:
        """Every belt attached to ``junction``, on either side.

        Each attachment occupies one side of the splitter, which is why the two
        directions are counted together against :data:`junction.MAX_PORTS`.
        """
        return _dedup_ints(
            (*self.junction_in.get(junction, ()), *self.junction_out.get(junction, ()))
        )

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


def _build_graph(
    buildings: Sequence[PlacedBuilding],
    kinds: Sequence[Kind],
    runs: Sequence[BeltRun],
    run_of: Mapping[int, int],
    j_in: Mapping[int, Sequence[int]],
    j_out: Mapping[int, Sequence[int]],
) -> tuple[dict[Node, tuple[Node, ...]], dict[Node, tuple[Node, ...]]]:
    """Edges between runs, through junctions and through native belt merges.

    THREE kinds of run boundary exist and all of them need crossing.  The
    obvious one is the splitter.  The second is a plain DSP merge:
    ``_build_runs`` ends a chain at any belt with more than one predecessor, so
    two lanes pointing at one tile leave three runs where the items see one
    continuous path.  A check that followed only junctions would still read a
    merged lane's downstream half as fed by nothing.

    The third is a **sorter with a belt on both ends** -- a lane-to-lane
    transfer, which is how both strategies tap a trunk onto a branch without
    spending a splitter.  It is an EDGE and not a flow source: what it moves is
    whatever the far lane needs, so modelling it as a graph edge lets
    ``_propagate`` derive that rate instead of guessing it.  It was invisible
    here, and invisible in ``_sorter_flows`` too (``_sorter_demand`` returns
    ``None`` when neither end is a machine), which left two holes: a branch fed
    only by a transfer read as supplied by nothing, and -- the one that mattered
    -- a trunk drained by a transfer was charged ZERO for that draw, so
    ``flow.belt_capacity`` could not see load leaving a lane this way at all.
    """
    succ: dict[Node, list[Node]] = defaultdict(list)
    pred: dict[Node, list[Node]] = defaultdict(list)

    def link(a: Node, b: Node) -> None:
        succ[a].append(b)
        pred[b].append(a)

    for r, run in enumerate(runs):
        onward = buildings[run.tail].output_obj
        if onward is None or not (0 <= onward < len(kinds)):
            continue
        if kinds[onward] is not Kind.BELT:
            continue
        other = run_of.get(onward)
        if other is not None and other != r:
            link((RUN, r), (RUN, other))

    for j, belts in j_in.items():
        for b in belts:
            feeder = run_of.get(b)
            if feeder is not None:
                link((RUN, feeder), (JUNCTION, j))
    for j, belts in j_out.items():
        for b in belts:
            tapped = run_of.get(b)
            if tapped is not None:
                link((JUNCTION, j), (RUN, tapped))

    for i, s in enumerate(buildings):
        if kinds[i] is not Kind.SORTER:
            continue
        src, dst = s.input_obj, s.output_obj
        if src is None or dst is None:
            continue
        from_run, to_run = run_of.get(src), run_of.get(dst)
        if from_run is None or to_run is None or from_run == to_run:
            continue
        link((RUN, from_run), (RUN, to_run))

    return (
        {n: _dedup(v) for n, v in succ.items()},
        {n: _dedup(v) for n, v in pred.items()},
    )


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
    # The corpus convention: a splitter names nobody, and the belts around it
    # name it -- as their `output_obj` to feed it, as their `input_obj` to draw
    # from it. Both directions are collected here once so no check has to
    # rediscover it.
    j_in: dict[int, list[int]] = defaultdict(list)
    j_out: dict[int, list[int]] = defaultdict(list)
    for i, b in enumerate(placement.buildings):
        if kinds[i] is not Kind.BELT:
            continue
        o, n = b.output_obj, b.input_obj
        if o is not None and 0 <= o < len(kinds) and kinds[o] is Kind.SPLITTER:
            j_in[o].append(i)
        if n is not None and 0 <= n < len(kinds) and kinds[n] is Kind.SPLITTER:
            j_out[n].append(i)
    succ, pred = _build_graph(placement.buildings, kinds, runs, run_of, j_in, j_out)
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
        junction_in={k: tuple(v) for k, v in j_in.items()},
        junction_out={k: tuple(v) for k, v in j_out.items()},
        succ=succ,
        pred=pred,
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
    """One belt per tile -- unless the tile is a junction, where several is how
    the game itself records it.

    A belt running THROUGH a splitter is two belt buildings on the splitter's
    tile, one ending at the junction and one starting from it, and a branch adds
    a third.  Splitter 140 in ``factory-quick-start-step-3-red-cube`` has exactly
    that: three belts co-located with it, one drawing and two feeding.  Reporting
    it would flag a blueprint the game produced.

    The exemption is narrow on purpose.  Every belt on the tile must be ATTACHED
    to the splitter standing there -- naming it as ``input_obj`` or
    ``output_obj``.  A belt that merely happens to share a junction's tile
    without naming it is not part of the junction; it is the ordinary collision
    this check exists to catch, wearing a splitter as cover.
    """
    for cell, occupants in sorted(ctx.occupancy.items()):
        belts = [i for i in occupants if ctx.kinds[i] is Kind.BELT]
        if len(belts) < 2:
            continue
        junctions = [i for i in occupants if ctx.kinds[i] is Kind.SPLITTER]
        attached = {b for j in junctions for b in ctx.junction_attachments(j)}
        loose = [i for i in belts if i not in attached]
        if junctions and not loose:
            continue
        yield Finding(
            "geom.belt_single_occupancy",
            Severity.ERROR,
            f"{len(belts)} belts share cell {cell}; one belt per tile"
            + (
                f", and {len(loose)} of them name no splitter on that tile"
                if junctions
                else ""
            ),
            tuple(loose or belts),
            {"cell": str(cell), "belts": len(belts), "unattached": len(loose)},
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
    """Every belt link names a real building, and every junction joins two sides.

    The junction half needs no ``BuildSpec``, which is the point of putting it
    here: a splitter with belts on only one side is a break in the belt path
    itself, visible from the placement alone.  Items poured into a junction
    nothing draws from vanish; a belt drawing from a junction nothing feeds
    carries nothing.  Both read as perfectly linked belts to any check that
    stops at the junction, which is exactly the class of miss this validator
    exists to close.
    """
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
    for j, s in ctx.of_kind(Kind.SPLITTER):
        feeding = ctx.junction_in.get(j, ())
        drawing = ctx.junction_out.get(j, ())
        if feeding:
            continue  # the far side is `belt.termination`'s question
        if not drawing:
            yield Finding(
                "belt.continuity",
                Severity.ERROR,
                f"splitter {j} at ({s.x},{s.y}) has no belt attached to it at all; "
                f"a junction that joins nothing is a building with no function",
                (j,),
                {"junction": j, "feeding": 0, "drawing": 0},
            )
            continue
        yield Finding(
            "belt.continuity",
            Severity.ERROR,
            f"splitter {j} at ({s.x},{s.y}) is drawn from by {len(drawing)} belt(s) but "
            f"nothing feeds it; every lane leaving this junction carries nothing",
            (j, *drawing),
            {"junction": j, "feeding": 0, "drawing": len(drawing)},
        )


# --- junctions -------------------------------------------------------------


@check("junction.ports")
def _junction_ports(ctx: Context) -> Iterable[Finding]:
    """A splitter has four sides, so at most four belts may attach to one.

    Exceeding it is the worst kind of failure this project has: the blueprint
    pastes cleanly and the game quietly drops a connection, so the build looks
    right and under-produces.  :func:`junction.check_ports` raises on this at
    emission; the same rule is enforced here so a placement that reached the
    validator by another route -- a decoded blueprint, a hand-built test, a
    strategy that forgot to call it -- is still judged.
    """
    for j, b in ctx.of_kind(Kind.SPLITTER):
        attached = ctx.junction_attachments(j)
        if len(attached) <= junc.MAX_PORTS:
            continue
        yield Finding(
            "junction.ports",
            Severity.ERROR,
            f"splitter {j} at ({b.x},{b.y}) has {len(attached)} belts attached but a "
            f"splitter has {junc.MAX_PORTS} sides; it would paste as a junction "
            f"silently dropping {len(attached) - junc.MAX_PORTS} connection(s)",
            (j, *attached),
            {"junction": j, "attached": len(attached), "max": junc.MAX_PORTS},
        )


@check("junction.colocated")
def _junction_colocated(ctx: Context) -> Iterable[Finding]:
    """Every belt attached to a junction sits on the junction's own tile.

    Measured on all 25 splitters in the fixture corpus and round-tripped through
    the viewer: ``dx = dy = 0``, without exception.  A belt that names a splitter
    from an adjacent tile is not an error the game reports -- it pastes as a
    junction with that side unconnected -- so nothing downstream of the missing
    side ever receives items while every building involved exists and every link
    resolves.  Reported per attachment rather than per junction so the finding
    names the belt to move.
    """
    bs = ctx.placement.buildings
    for j, s in ctx.of_kind(Kind.SPLITTER):
        for belt_idx in ctx.junction_attachments(j):
            b = bs[belt_idx]
            dx, dy, dz = b.x - s.x, b.y - s.y, b.z - s.z
            if dx == 0 and dy == 0 and dz == 0:
                continue
            yield Finding(
                "junction.colocated",
                Severity.ERROR,
                f"belt {belt_idx} at ({b.x},{b.y},{b.z}) attaches to splitter {j} at "
                f"({s.x},{s.y},{s.z}), offset ({dx},{dy},{dz}); every attachment must "
                f"share the junction's tile or that side pastes unconnected",
                (belt_idx, j),
                {"junction": j, "belt": belt_idx, "dx": dx, "dy": dy, "dz": dz},
            )


@check("junction.records_no_links")
def _junction_records_no_links(ctx: Context) -> Iterable[Finding]:
    """A splitter names nobody; the belts around it do the naming.

    Unanimous across the corpus: ``output_obj`` and ``input_obj`` are both unset
    on all 25 splitters.  A splitter that names a neighbour encodes a link the
    game does not expect on that building, and -- because ``_context`` reads the
    junction's attachments off the BELTS -- such a link is invisible to every
    other check here, so the connection it claims is never verified by anything.
    """
    for j, b in ctx.of_kind(Kind.SPLITTER):
        named = {
            label: link
            for label, link in (("output_obj", b.output_obj), ("input_obj", b.input_obj))
            if link is not None
        }
        if not named:
            continue
        yield Finding(
            "junction.records_no_links",
            Severity.ERROR,
            f"splitter {j} at ({b.x},{b.y}) records {named}; a junction records no "
            f"links of its own and the belts around it name it instead, so this "
            f"connection is verified by nothing",
            (j,),
            {"junction": j, **{k: str(v) for k, v in named.items()}},
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


def _belt_successors(ctx: Context, i: int) -> tuple[int, ...]:
    """Where items on building ``i`` go next, junctions included.

    A splitter has no ``output_obj`` of its own, so following links alone stops
    dead at one.  Its successors are the belts that named it as their
    ``input_obj`` -- which is how a loop that closes THROUGH a junction, the
    shape a fan-out router most easily produces, stays invisible to a
    link-following walk.
    """
    bs = ctx.placement.buildings
    if ctx.kinds[i] is Kind.SPLITTER:
        return ctx.junction_out.get(i, ())
    o = bs[i].output_obj
    if o is None or not (0 <= o < len(bs)):
        return ()
    if ctx.kinds[o] in (Kind.BELT, Kind.SPLITTER):
        return (o,)
    return ()


@check("belt.acyclic")
def _acyclic(ctx: Context) -> Iterable[Finding]:
    """No belt path returns to itself, following splitters as well as links.

    Iterative rather than recursive: a corridor lane in a real build runs to 51
    tiles and a chain of them would put a recursive walk within reach of the
    interpreter's stack limit, turning a validation failure into a crash.

    Colour 1 means "on the path being walked now", colour 2 means "settled,
    provably not on a cycle".  Every node the walk leaves has to be settled:
    leaving them grey made the NEXT chain that merged into them look like a
    cycle, and DSP belts merge natively -- two chains pointing at one tile is
    how many-to-one is built -- so that fired on correct layouts.
    """
    colour: dict[int, int] = {}
    reported: set[frozenset[int]] = set()

    starts = [i for i, _ in ctx.of_kind(Kind.BELT)]
    starts += [j for j, _ in ctx.of_kind(Kind.SPLITTER)]
    for start in starts:
        if colour.get(start):
            continue
        colour[start] = 1
        path: list[int] = [start]
        stack: list[tuple[int, Iterator[int]]] = [(start, iter(_belt_successors(ctx, start)))]
        while stack:
            node, pending = stack[-1]
            nxt = next(pending, None)
            if nxt is None:
                colour[node] = 2
                stack.pop()
                path.pop()
                continue
            seen = colour.get(nxt, 0)
            if seen == 2:
                continue
            if seen == 1:
                cycle = path[path.index(nxt) :] if nxt in path else [nxt]
                key = frozenset(cycle)
                if key not in reported:
                    reported.add(key)
                    yield Finding(
                        "belt.acyclic",
                        Severity.ERROR,
                        f"belt chain forms a cycle through {cycle}",
                        tuple(cycle),
                        {"cycle": str(cycle)},
                    )
                continue
            colour[nxt] = 1
            path.append(nxt)
            stack.append((nxt, iter(_belt_successors(ctx, nxt))))


#: Belt tiles a lane may run past its last tap before the overshoot is called
#: waste.  ``SORTER_MAX_REACH`` because within it a sorter could have been stood
#: anywhere along the surplus and still served the same machine, so the tiles are
#: tolerance in where the tap was placed rather than lane nobody could ever use.
_TERMINATION_SLACK = cat.SORTER_MAX_REACH


@check("belt.termination")
def _termination(ctx: Context) -> Iterable[Finding]:
    """A run ends at a live junction, an onward link, or near its last tap.

    The junction clause is the one that needed adding.  A run whose tail feeds a
    splitter has a non-``None`` ``output_obj``, so the original test passed it
    without ever asking whether anything draws from the far side.  A junction
    with no taps is a hole items fall into: the run terminates, the link
    resolves, and the flow stops.  That is graded an ERROR while dead lane stays
    a WARNING, because wasted belt costs area and a dead junction means the items
    routed into it never arrive.

    The warning half used to ask only whether the TAIL TILE was tapped, which is
    not the same question as whether the lane wastes anything.  Both strategies
    end a lane a couple of tiles past its last consumer, so a correct lane failed
    a tail-tile test while wasting two tiles out of fifty, and the check reported
    on 73% of belt runs across both strategies' fixtures -- a warning nobody
    reads.  What is worth acting on is the SIZE of the overshoot, so that is what
    is measured and reported, judged against :data:`_TERMINATION_SLACK`.

    Measured as a controlled A/B, old rule against new on IDENTICAL placements:
    26% -> 2% over 123 belt runs of the hand-built fixtures, and 23% -> 13% over
    535 belt runs of the twelve-URL bake-off corpus.  (Both "before" figures are
    lower than the 73% above because lane trimming landed in between; the rule
    change and the trimming are separate wins and this is the rule change's
    half.)  The survivors carry their own justification: a median of 8 dead tiles
    and a tail of 44, with four lanes across the corpus that no sorter touches
    anywhere.  Each finding names the number of tiles to cut.

    A lane with no tap at all is always reported however short it is -- that is
    not an overshoot, it is a lane serving nothing.
    """
    bs = ctx.placement.buildings
    touched: set[int] = set()
    for _, s in ctx.of_kind(Kind.SORTER):
        for link in (s.input_obj, s.output_obj):
            if link is not None:
                touched.add(link)
    for r, run in enumerate(ctx.runs):
        tail = run.tail
        o = bs[tail].output_obj
        if o is not None and 0 <= o < len(bs) and ctx.kinds[o] is Kind.SPLITTER:
            if not ctx.junction_out.get(o, ()):
                yield Finding(
                    "belt.termination",
                    Severity.ERROR,
                    f"belt run {r} ends by feeding splitter {o}, which nothing draws "
                    f"from; everything routed down this run stops there",
                    (tail, o),
                    {"tail": tail, "junction": o, "run": r},
                )
            continue
        if o is not None:
            continue
        taps = [k for k, i in enumerate(run.indices) if i in touched]
        dead = len(run.indices) - (max(taps) + 1) if taps else len(run.indices)
        if taps and dead <= _TERMINATION_SLACK:
            continue
        head = bs[run.head]
        yield Finding(
            "belt.termination",
            Severity.WARNING,
            (
                f"belt run {r} (head building {run.head} at ({head.x},{head.y}), "
                f"carrying {head.carries_item!r}) runs {len(run.indices)} tiles and "
                f"no sorter touches any of them; the whole lane is wasted"
                if not taps
                else f"belt run {r} (head building {run.head} at ({head.x},{head.y}), "
                f"carrying {head.carries_item!r}) runs {dead} of its "
                f"{len(run.indices)} tiles past its last tap and then stops; those "
                f"tiles serve nothing"
            ),
            (tail,),
            {"run": r, "tail": tail, "length": len(run.indices), "dead": dead,
             "taps": len(taps)},
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


def _external_item(ctx: Context, run: BeltRun, external: set[str]) -> str | None:
    """The external input this run carries, if it carries one.

    Carrying an external item exempts a run from ``flow.lane_sourced``: the
    player fills it, so nothing inside the blueprint needs to.

    That exemption was briefly narrowed to runs touching the placement bounding
    box, on the theory that the entry lane is where the player's belt meets the
    block.  Measured against both strategies, that rule is wrong in both
    directions and has been reverted.  It catches nothing in spine, whose
    ``_emit`` extends every corridor copy of an external item to x=0, so all
    copies touch the left edge and all stay exempt -- including the ``iron-ore``
    duplicate the rule was written for.  And it invents errors in freeform, which
    seats each consumer strip's in-lane where the strip lands: on
    ``fan_out_spec(4)`` two ``copper-ore`` lanes sit inland at (7,15) and (14,9)
    and were reported as starving six machines each, while the player can belt
    into both perfectly well.

    Bounding-box contact is simply not the discriminator.  What separates a
    legitimate second entry point from a lane copy nobody feeds is whether the
    player can REACH it, which is a question about free space rather than about
    labelling -- see ``flow.external_entry_reachable``, which measures exactly
    that and does find a real defect the boundary rule only caught by accident.
    """
    bs = ctx.placement.buildings
    for i in run.indices:
        item = bs[i].carries_item
        if item in external:
            return item
    return None


def _sorter_span(b: PlacedBuilding) -> int | None:
    """Chebyshev span of a sorter, matching ``sorter.reach``."""
    a = _anchors(b)
    if a is None:
        return None
    (x1, y1, _), (x2, y2, _) = a
    return max(abs(x2 - x1), abs(y2 - y1))


def _deliverable(ctx: Context, index: int) -> Fraction | None:
    """Items/second sorter ``index`` can move, or ``None`` when unknowable."""
    b = ctx.placement.buildings[index]
    span = _sorter_span(b)
    if span is None or span < 1 or span > cat.SORTER_MAX_REACH:
        return None
    if b.item_id not in cat.SORTER_RATE_AT_1:
        return None
    return cat.sorter_rate(b.item_id, span)


def _internal_seeds(ctx: Context) -> tuple[set[int], set[int]]:
    """``(runs a sorter draws from, runs the blueprint itself fills)``.

    "The blueprint itself" deliberately excludes the external-input exemption,
    so the same computation answers both questions asked of it: which lanes are
    fed at all (add the exemption), and which lanes the player is expected to
    fill (subtract this from the lanes carrying an external item).
    """
    bs = ctx.placement.buildings
    drains: set[int] = set()
    seeds: set[int] = set()
    for _i, s in ctx.of_kind(Kind.SORTER):
        if s.input_obj is not None and s.input_obj in ctx.run_of:
            drains.add(ctx.run_of[s.input_obj])
        if s.output_obj is not None and s.output_obj in ctx.run_of:
            seeds.add(ctx.run_of[s.output_obj])

    # Belts point FORWARD via `output_obj`, so "who feeds this belt" is the set
    # of belts naming it as their output -- not `input_obj`, which belts do not
    # use for chaining.  This matters because `_build_runs` starts a new run at
    # any belt with more than one predecessor, so a MERGE POINT heads its own
    # run while being perfectly well fed.  Reading `input_obj` here reported
    # every such merge as unsourced.
    fed_by_belt: set[int] = set()
    for i, b in enumerate(bs):
        if ctx.kinds[i] is not Kind.BELT:
            continue
        o = b.output_obj
        if o is not None and 0 <= o < len(bs) and ctx.kinds[o] is Kind.BELT:
            fed_by_belt.add(o)
    seeds |= {r for r, run in enumerate(ctx.runs) if run.head in fed_by_belt}
    return drains, seeds


def _run_components(ctx: Context) -> dict[int, int]:
    """Run -> id of the connected lane network it belongs to.

    Undirected on purpose.  Two runs joined by a junction are one lane network
    whichever way the items travel, and the questions asked of this -- what a
    lane carries, whose sorter made it ambiguous -- are properties of the
    network rather than of a direction through it.
    """
    component: dict[int, int] = {}
    for r in range(len(ctx.runs)):
        if r in component:
            continue
        cid = len(set(component.values()))
        queue = deque([(RUN, r)])
        seen: set[Node] = {(RUN, r)}
        while queue:
            node = queue.popleft()
            if node[0] == RUN:
                component[node[1]] = cid
            for nxt in (*ctx.succ.get(node, ()), *ctx.pred.get(node, ())):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
    return component


def _close_over_junctions(ctx: Context, seeds: set[int]) -> set[int]:
    """Every run reachable from ``seeds`` through splitters.

    Sourcing is TRANSITIVE THROUGH JUNCTIONS.  A splitter with something feeding
    it sources every run drawn from it, and those runs may feed further
    junctions -- a chain of splitters is exactly how one lane comes to serve four
    consumers.  A single lookup would credit the first hop and report the rest as
    dry, reporting the splitter as the very defect it fixes, so this is a
    fixpoint.
    """
    sourced = set(seeds)
    changed = True
    while changed:
        changed = False
        for j, taps in ctx.junction_out.items():
            if not any(fr in sourced for fr in ctx.runs_feeding_junction(j)):
                continue
            for belt in taps:
                tapped = ctx.run_of.get(belt)
                if tapped is not None and tapped not in sourced:
                    sourced.add(tapped)
                    changed = True
    return sourced


@check("flow.lane_sourced", needs_spec=True)
def _lane_sourced(ctx: Context) -> Iterable[Finding]:
    """A belt run that feeds machines must itself be fed by something.

    ``machine.inputs_supplied`` counts sorters adjacent to a machine, which is
    not the same question.  A strategy that attaches lanes to each machine and
    then fails to ROUTE those lanes to their producers leaves every machine with
    its full complement of sorters, all drawing from belt runs that nothing ever
    fills.  Measured on a real build: 119 nets, 0 routed, 119 route failures --
    and the validator reported ONE error, because every machine had its sorters
    and every lane existed.  Nothing was connected to anything.

    Worse, such a build scores as *denser*: 119 unrouted nets are 119 missing
    belt runs, so its bounding box is smaller than a correct layout's.  A
    strategy comparison that does not catch this rewards failing to route.

    A run is sourced if a sorter puts onto it, another run feeds it, or it
    carries an item the spec belts in from outside.

    Severity splits on whether anything actually starves.  When a machine drawing
    from a dry lane gets the same item from somewhere else -- typically a direct
    insertion the packer arranged, which serves the machine and leaves the lane
    it no longer needs in place -- nothing stops running and the finding is a
    WARNING about wasted belts.  When there is no other source, the machine
    starves and it is an ERROR.
    """
    assert ctx.spec is not None
    external = set(ctx.spec.external_inputs)
    bs = ctx.placement.buildings

    drains, seeds = _internal_seeds(ctx)
    seeds |= {
        r
        for r, run in enumerate(ctx.runs)
        if _external_item(ctx, run, external) is not None
    }
    sourced = _close_over_junctions(ctx, seeds)
    items = _sorter_items(ctx)

    dry = {r for r in range(len(ctx.runs)) if r not in sourced}

    def surviving_supply(machine: int, item: str | None) -> Fraction | None:
        """What the machine's OTHER sorters for ``item`` can still deliver.

        ``None`` means unbounded, and therefore not judgeable as starvation: at
        least one surviving sorter has an unknown tier or an unresolvable item,
        so no honest upper bound exists and the finding stays a WARNING.

        Every DRY run is excluded, not merely the one being reported.  Excluding
        only the current run let two unfed lanes excuse each other -- each read
        as the other's "alternative source" -- so a machine fed exclusively by
        lanes nothing filled reported clean twice over.
        """
        total = Fraction(0)
        for j, s in ctx.of_kind(Kind.SORTER):
            if s.output_obj != machine:
                continue
            other = items.get(j)
            if other is not None and item is not None and other != item:
                continue
            src = s.input_obj
            if src is None:
                continue
            if src in ctx.run_of and ctx.run_of[src] in dry:
                continue  # itself fed by a lane nothing fills
            if other is None:
                return None  # unresolvable item: cannot bound what it delivers
            rate = _deliverable(ctx, j)
            if rate is None:
                return None
            total += rate
        return total

    for r, run in enumerate(ctx.runs):
        if r not in drains:
            continue  # feeds nothing, so nothing starves on it
        if r in sourced:
            continue

        starved: list[int] = []
        for j, s in ctx.of_kind(Kind.SORTER):
            src, dst = s.input_obj, s.output_obj
            if src is None or dst is None:
                continue
            if ctx.run_of.get(src) != r:
                continue
            item = items.get(j)
            # A lane is only genuinely redundant when what remains can carry the
            # machine's WHOLE demand.  "Some other sorter also feeds it" is not
            # the same claim: a machine wanting 10/s from two lanes gets 5/s when
            # one of them is dry, which is a machine that under-produces for
            # ever while the validator calls the dead lane wasted belts.  That is
            # the freeform fan-out miss -- the "other source" was one net of
            # several, carrying its share and no more.
            g = ctx.group_for(dst) if ctx.kinds[dst] is Kind.MACHINE else None
            need = g.inputs_per_machine.get(item) if g is not None and item else None
            supply = surviving_supply(dst, item)
            if supply is None:
                continue  # unbounded alternative: not judgeable as starvation
            if need is None:
                if supply == 0:
                    starved.append(dst)
                continue
            if supply < need:
                starved.append(dst)

        if starved:
            yield Finding(
                "flow.lane_sourced",
                Severity.ERROR,
                f"belt run {r} (head building {run.head}) feeds "
                f"{len(starved)} machine(s) that have no other source of "
                f"{bs[run.head].carries_item!r}, and nothing puts items onto it",
                (run.head, *starved[:4]),
                {
                    "run": r,
                    "length": len(run.indices),
                    "carries": bs[run.head].carries_item,
                    "starved": len(starved),
                },
            )
        else:
            yield Finding(
                "flow.lane_sourced",
                Severity.WARNING,
                f"belt run {r} (head building {run.head}) is never filled, but "
                f"every machine drawing from it is fed another way; these "
                f"{len(run.indices)} belts and their sorters are wasted",
                (run.head,),
                {
                    "run": r,
                    "length": len(run.indices),
                    "carries": bs[run.head].carries_item,
                    "starved": 0,
                },
            )


def _entry_runs(ctx: Context) -> dict[str, list[int]]:
    """Runs the PLAYER has to fill, grouped by the item they want.

    A run carrying an external input that nothing inside the blueprint fills is,
    by elimination, an entry point: it exists to be belted into, and
    :mod:`flab2bp.layout.markers` puts an icon on its head saying which item.
    """
    assert ctx.spec is not None
    external = set(ctx.spec.external_inputs)
    internal = _close_over_junctions(ctx, _internal_seeds(ctx)[1])
    out: dict[str, list[int]] = defaultdict(list)
    for r, run in enumerate(ctx.runs):
        if r in internal:
            continue
        item = _external_item(ctx, run, external)
        if item is not None:
            out[item].append(r)
    return dict(out)


def _entry_items(ctx: Context) -> dict[int, set[str]]:
    """Run -> EVERY external item the player has to put onto it.

    ``_entry_runs`` answers the sibling question -- which lanes want a given
    item -- and settles for the first external label it finds on a run, which is
    all its callers need.  Seeding flow needs the other direction and needs it
    complete: ``six_input_spec`` mixes two external items onto one lane (six
    ingredients, four belt sides), and crediting such a lane with one item's rate
    while charging it both items' demand invents a shortfall on a build the
    player feeds perfectly well.

    The ``carries_item`` labels alone are not enough for exactly that lane.  A
    strategy labels a mixed belt with one of the items it carries -- the entry
    lane at ``(-1,0)`` says ``antimatter`` down its whole length while sorters
    draw both ``antimatter`` and ``electromagnetic-matrix`` off it -- so the
    sorters' own item resolution is unioned in.  That is safe here and only
    here: a run reaching this point is by construction one NOTHING inside the
    blueprint fills, so every item a sorter names on it is an item the player
    must supply.
    """
    assert ctx.spec is not None
    external = set(ctx.spec.external_inputs)
    bs = ctx.placement.buildings
    internal = _close_over_junctions(ctx, _internal_seeds(ctx)[1])
    drawn = _run_items(ctx, _sorter_items(ctx))
    out: dict[int, set[str]] = {}
    for r, run in enumerate(ctx.runs):
        if r in internal:
            continue
        seen: set[str | None] = {bs[i].carries_item for i in run.indices}
        seen |= drawn.get(r, set())
        carried = {item for item in seen if item is not None} & external
        if carried:
            out[r] = carried
    return out


def _reachable_from_outside(ctx: Context, level: int) -> set[tuple[int, int]]:
    """Cells at altitude ``level`` a NEW belt could occupy, coming from outside.

    Flood fill from a ring one tile beyond the bounding box, through cells no
    building stands on.  ``occupancy`` is the right blocking set here rather than
    ``blocking``: the question is where the player could lay a belt, and an
    existing belt's tile is taken even though it reserves nothing exclusively.
    Sorters are absent from both maps, which is correct -- a sorter arm passes
    over a tile without claiming it.
    """
    min_x, min_y, max_x, max_y = ctx.placement.bounds
    taken = {(x, y) for (x, y, z) in ctx.occupancy if z == level}
    lo_x, lo_y, hi_x, hi_y = min_x - 1, min_y - 1, max_x + 1, max_y + 1
    start = (lo_x, lo_y)
    seen = {start}
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for nxt in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if not (lo_x <= nxt[0] <= hi_x and lo_y <= nxt[1] <= hi_y):
                continue
            if nxt in seen or nxt in taken:
                continue
            seen.add(nxt)
            queue.append(nxt)
    return seen


@check("flow.external_entry_reachable", needs_spec=True)
def _external_entry_reachable(ctx: Context) -> Iterable[Finding]:
    """The player must be able to reach every lane they are asked to fill.

    This is the discriminator the bounding-box rule was reaching for and missed.
    An external input lane seated inland is perfectly legitimate -- freeform puts
    one wherever the consumer strip lands, and the player belts into it.  A lane
    walled in on every side by machines is not: no belt can ever be run to it, so
    the item never arrives however the blueprint is labelled.

    Measured across both strategies, this separates the two cleanly.  Spine's
    corridor lanes all reach x=0 and pass.  Freeform's inland ``copper-ore``
    lanes on ``fan_out_spec(4)``, at (7,15) and (14,9), have free ground beside
    them and pass -- they are the false positives the boundary rule invented.
    Freeform's ``iron-ore`` lane on ``proliferated_spec``, head at (7,0), is
    sealed in, and every machine downstream of it starves on paste.  That is a
    genuine defect no check caught, and it is why this is an ERROR: nothing about
    the blueprint looks wrong, and the item simply cannot be delivered.

    Deliberately generous about where the belt may join: ANY tile of the run
    reaching free ground counts, not just its head.  A belt pointed into the
    middle of a lane feeds everything downstream of that point, so demanding the
    head would fail lanes that are perfectly fillable.
    """
    assert ctx.spec is not None
    bs = ctx.placement.buildings
    free: dict[int, set[tuple[int, int]]] = {}
    for item, runs in sorted(_entry_runs(ctx).items()):
        for r in runs:
            run = ctx.runs[r]
            walled: list[int] = []
            for i in run.indices:
                b = bs[i]
                plane = free.get(b.z)
                if plane is None:
                    plane = _reachable_from_outside(ctx, b.z)
                    free[b.z] = plane
                if any(
                    (b.x + dx, b.y + dy) in plane
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                ):
                    break
                walled.append(i)
            else:
                head = bs[run.head]
                yield Finding(
                    "flow.external_entry_reachable",
                    Severity.ERROR,
                    f"belt run {r} wants {item!r} belted in from outside, but all "
                    f"{len(walled)} of its tiles are walled in -- no belt can be run "
                    f"to it from beyond the block, so {item!r} never arrives",
                    (run.head, *walled[:4]),
                    {
                        "run": r,
                        "item": item,
                        "head": f"({head.x},{head.y},{head.z})",
                        "tiles": len(walled),
                    },
                )


@check("flow.external_entry_points", needs_spec=True)
def _external_entry_points(ctx: Context) -> Iterable[Finding]:
    """One item wanted at several separate entry lanes costs the player belts.

    Legitimate -- the player can belt an item into as many lanes as there are --
    but it is a real cost the density comparison would otherwise hide entirely.
    Spine's magnetic-ring output asks for ``coal`` at FIVE separate lanes and for
    ``iron-ore`` at two; a strategy that needs five input belts where another
    needs one has not won merely because its bounding box is smaller.

    A WARNING and not an ERROR on purpose.  Nothing starves: every one of those
    lanes works once fed.  Promoting it would make the tool refuse builds that
    run correctly, and separating "several genuine entry points" from "one entry
    point and four copies nobody feeds" is not something the item name can do --
    ``flow.external_entry_reachable`` is the check that can tell them apart.
    """
    assert ctx.spec is not None
    bs = ctx.placement.buildings
    for item, runs in sorted(_entry_runs(ctx).items()):
        if len(runs) < 2:
            continue
        heads = [bs[ctx.runs[r].head] for r in runs]
        where = ", ".join(f"({b.x},{b.y})" for b in heads[:6])
        yield Finding(
            "flow.external_entry_points",
            Severity.WARNING,
            f"{item!r} is belted in at {len(runs)} separate lanes ({where}); the "
            f"player must connect a supply to every one of them",
            tuple(ctx.runs[r].head for r in runs),
            {"item": item, "entry_lanes": len(runs), "runs": sorted(runs)},
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
    """Supply meets demand -- first in the spec's arithmetic, then on the belts.

    Two clauses, run in that order, because they answer different questions and
    the second is only meaningful once the first passes.

    **Spec arithmetic.**  Production minus consumption over the whole block.
    Independent of any geometry, and cheap.

    **Reachability balance, read off the PLACEMENT.**  Production must cover
    consumption not merely in total but within every set of machines and lanes
    an item can actually travel between.  This is the class the validator could
    not see at all: a build whose geometry is impeccable, whose every lane is
    sourced, whose every belt is under tier capacity, and which still
    under-produces because a producer group's output was cut into islands that
    do not serve their consumers.  See :func:`_lane_balance` for why it is a cut
    argument rather than a per-lane one.

    This was previously declined on the reasoning that external input lanes have
    no sorter pushing onto them, so a per-junction balance could not be seeded
    without guessing how a block's external rate divides across its entry lanes.
    The cited counter-example does not survive checking.  Junction 1639 showed
    downstream demand 12 against upstream supply 4 because the hand-built
    ``magnetic_ring_spec`` runs 4 magnetic-coil machines at 1/s against 8
    electric-motor plus 4 electromagnetic-turbine machines wanting 1/s each --
    still visible in ``tests/layout/test_freeform.py``, where the spec clause
    below reports ``magnetic-coil`` over-consumed by exactly 8/s along with
    three more items on the same fixture.  ``magnetic-coil`` is not an external
    input at all.  The reading was of a genuinely unbalanced fixture, not of a
    correct build, and no seeding question was involved.

    (The seeding is nonetheless soluble and :func:`_entry_items` does it, since
    the placement clause needs to know which lanes the player fills.  What the
    measurement changed was the shape of the check, not whether it could be
    written.)

    The placement clause STOPS when the spec clause fires.  When the recipe
    balance itself is short, every island carrying the short item is short, and
    the placement clause would restate one spec defect once per island --
    eight findings on ``magnetic_ring_spec`` saying what one already said.
    Routing is only a question worth asking once the arithmetic balances.

    Measured across the twelve-URL bake-off corpus (both strategies, three
    candidates each, 512 belt runs) the placement clause fires ten times, every
    one of them on a build already refused by ``machine.inputs_supplied``, and
    not once on a build that otherwise validates clean.
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
    short = [item for item in sorted(net) if net[item] < 0]
    for item in short:
        yield Finding(
            "flow.conservation",
            Severity.ERROR,
            f"{item} is over-consumed by {net[item]} items/s; demand exceeds supply",
            (),
            {"item": item, "net": str(net[item])},
        )
    if short:
        return
    yield from _lane_balance(ctx)


#: Union-find key: ``("g", flow-graph node)`` or ``("m", machine index)``.
_Island = tuple[str, object]


def _islands(ctx: Context, item: str, items: Mapping[int, str | None]) -> dict[_Island, _Island]:
    """Union-find over everything ``item`` can physically move between.

    Belts, junctions and transfer sorters connect lanes to lanes; a sorter
    carrying ``item`` connects a machine to a lane, or to another machine when
    the edge is direct-inserted.  What comes out is a partition into ISLANDS:
    inside one, the item can get from any producer to any consumer, so nothing
    a splitter or a machine's second output sorter does can starve anyone.
    Between two, no path exists at all.

    A sorter whose item cannot be resolved is treated as carrying EVERY item, so
    it merges islands rather than separating them.  That direction is chosen
    deliberately: merging can only hide a shortfall, and a check whose ERROR
    depends on an item guess is not one this validator should be making.
    """
    parent: dict[_Island, _Island] = {}

    def find(k: _Island) -> _Island:
        parent.setdefault(k, k)
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def union(a: _Island, b: _Island) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for node, nbrs in ctx.succ.items():
        for m in nbrs:
            union(("g", node), ("g", m))
    for j, _ in ctx.of_kind(Kind.SPLITTER):
        find(("g", (JUNCTION, j)))
    for r in range(len(ctx.runs)):
        find(("g", (RUN, r)))

    bs = ctx.placement.buildings
    for i, s in ctx.of_kind(Kind.SORTER):
        moved = items.get(i)
        if moved is not None and moved != item:
            continue
        ends: list[_Island] = []
        for link in (s.input_obj, s.output_obj):
            if link is None or not (0 <= link < len(bs)):
                continue
            if link in ctx.run_of:
                ends.append(("g", (RUN, ctx.run_of[link])))
            elif ctx.kinds[link] is Kind.MACHINE:
                ends.append(("m", link))
        if len(ends) == 2:
            union(ends[0], ends[1])
    for i, _ in ctx.of_kind(Kind.MACHINE):
        find(("m", i))
    return {k: find(k) for k in list(parent)}


def _lane_balance(ctx: Context) -> Iterable[Finding]:
    """The placement half of ``flow.conservation``.

    A CUT argument, not a per-lane one, and the difference is the whole
    soundness of the check.  Three separate things in this model divide a rate
    evenly where the game does not: a splitter feeds whichever output has room,
    a machine with two output sorters fills whichever lane is not backed up, and
    a lane fed by two producers draws from whichever is not empty.  Every one of
    those self-balances, so a per-lane verdict computed from an even split
    invents shortfalls on builds that run perfectly.  Measured on the real
    corpus, the per-lane version reported 15 lanes short across ``processor``
    and ``super-magnetic-ring``, and every one of them was a machine draining to
    two lanes off one fan-out.

    What does NOT self-balance is a cut with no path across it.  So the claim
    made here is the one backpressure cannot rescue: within each connected
    ISLAND for an item -- everything that item can physically reach, machines
    and lanes alike -- production plus what the player belts in must cover
    consumption.  Under that shortfall the machines in the island starve at a
    fixed ratio and no routing inside the block can help, which is why it is an
    ERROR.

    ``flow.lane_sourced`` is the degenerate case of this (supply exactly zero on
    a lane); this generalises it to a rate, and to the whole island rather than
    the single lane.

    External inputs are credited in full to every island holding an entry lane
    for that item, rather than divided across them.  The player decides how much
    goes down each belt and can simply put more on one, so an island short only
    of an external item is not a defect in the placement -- and the aggregate
    version of that question is what the spec clause above already answers.
    """
    assert ctx.spec is not None
    items = _sorter_items(ctx)
    bs = ctx.placement.buildings
    makes: dict[int, Mapping[str, Fraction]] = {}
    needs: dict[int, Mapping[str, Fraction]] = {}
    for i, _ in ctx.of_kind(Kind.MACHINE):
        g = ctx.group_for(i)
        if g is None:
            continue
        makes[i] = g.outputs_per_machine
        needs[i] = g.inputs_per_machine
    wanted_items = sorted(
        {it for rates in needs.values() for it in rates}
        & {it for rates in makes.values() for it in rates}
    )
    entry = _entry_items(ctx)
    for item in wanted_items:
        roots = _islands(ctx, item, items)
        supply: dict[_Island, Fraction] = defaultdict(Fraction)
        demand: dict[_Island, Fraction] = defaultdict(Fraction)
        starving: dict[_Island, list[int]] = defaultdict(list)
        belted_in: set[_Island] = set()
        for i, rates in makes.items():
            if item in rates:
                supply[roots[("m", i)]] += rates[item]
        for i, rates in needs.items():
            if item in rates:
                key = roots[("m", i)]
                demand[key] += rates[item]
                starving[key].append(i)
        for r, carried in entry.items():
            if item in carried:
                belted_in.add(roots[("g", (RUN, r))])
        external = ctx.spec.external_inputs.get(item, Fraction(0))
        for key in sorted(demand, key=lambda k: str(k)):
            have = supply[key] + (external if key in belted_in else Fraction(0))
            want = demand[key]
            if want <= have:
                continue
            hungry = sorted(starving[key])
            if not have and len(hungry) == 1 and not supply[key]:
                # A lone machine with nothing at all attached for this item is
                # `machine.inputs_supplied`'s finding word for word, naming the
                # same building.  Saying it twice does not make it truer.
                continue
            lanes = sorted(
                r
                for r in range(len(ctx.runs))
                if roots.get(("g", (RUN, r))) == key
                and any(bs[b].carries_item == item for b in ctx.runs[r].indices)
            )
            yield Finding(
                "flow.conservation",
                Severity.ERROR,
                f"{len(hungry)} machine(s) consume {want} items/s of {item} but only "
                f"{have} items/s of it is produced or belted in anywhere they can "
                f"reach (lanes {lanes[:6] or 'none'}); short by {want - have} items/s "
                f"and no routing inside the block can make it up",
                tuple(hungry[:5]),
                {
                    "item": item,
                    "demand": str(want),
                    "supply": str(have),
                    "shortfall": str(want - have),
                    "starved": len(hungry),
                    "lanes": lanes,
                },
            )


@check("flow.belt_capacity", needs_spec=True)
def _belt_capacity(ctx: Context) -> Iterable[Finding]:
    """No belt run may be asked to carry more than its tier sustains.

    The comparison is against the SUM across every item on the run, because a
    lane is one pipe: 7/s of copper and 7/s of iron do not each fit in a 12/s
    belt merely because neither exceeds 12 alone.
    """
    assert ctx.spec is not None
    for ridx, per_item in sorted(_run_demand(ctx).items()):
        run = ctx.runs[ridx]
        capacity = cat.BELT_RATE.get(run.tier_item_id)
        required = sum(per_item.values(), Fraction(0))
        if capacity is None or required <= capacity:
            continue
        breakdown = {(k or "unattributed"): str(v) for k, v in sorted(
            per_item.items(), key=lambda kv: (kv[0] is None, kv[0] or "")
        )}
        shared = " across " + ", ".join(breakdown) if len(per_item) > 1 else ""
        yield Finding(
            "flow.belt_capacity",
            Severity.ERROR,
            f"belt run {ridx} must carry {required} items/s{shared} but its tier "
            f"sustains only {capacity}",
            run.indices,
            {
                "run": ridx,
                "required": str(required),
                "capacity": str(capacity),
                "per_item": breakdown,
            },
        )


@check("flow.sorter_capacity", needs_spec=True)
def _sorter_capacity(ctx: Context) -> Iterable[Finding]:
    """No sorter may be asked to move more than its tier sustains at its span."""
    assert ctx.spec is not None
    items = _sorter_items(ctx)
    for i, s in ctx.of_kind(Kind.SORTER):
        a = _anchors(s)
        if a is None:
            continue
        (x1, y1, _), (x2, y2, _) = a
        # Chebyshev, matching `sorter.reach`. For a straight sorter one axis is
        # zero so the two agree, but keeping them in step stops a future
        # non-integer anchor from being charged a longer span here than the
        # reach check measured -- they must not disagree about the same sorter.
        span = max(abs(x2 - x1), abs(y2 - y1))
        if span < 1 or span > cat.SORTER_MAX_REACH:
            continue  # sorter.reach already reported this
        if s.item_id not in cat.SORTER_RATE_AT_1:
            continue
        capacity = cat.sorter_rate(s.item_id, span)
        required = _sorter_demand(ctx, i, items)
        if required is None or required <= capacity:
            continue
        moves = f" of {items[i]}" if items.get(i) else ""
        yield Finding(
            "flow.sorter_capacity",
            Severity.ERROR,
            f"sorter {i} must move {required} items/s{moves} across {span} tiles but "
            f"sustains only {capacity}",
            (i,) + tuple(x for x in (s.input_obj, s.output_obj) if x is not None),
            {
                "sorter": i,
                "span": span,
                "item": items.get(i),
                "required": str(required),
                "capacity": str(capacity),
            },
        )


def _sorter_demand(
    ctx: Context, index: int, items: Mapping[int, str | None] | None = None
) -> Fraction | None:
    """Items/second one sorter must move.

    Attributed PER ITEM wherever the sorter's item is known: a sorter feeding
    copper carries the copper rate, not an average.  Splitting a machine's total
    evenly across its sorters -- which is what this did -- hides an overloaded
    sorter behind an underloaded one the moment a recipe's ingredient rates
    differ, which is most recipes.  Measured: a machine wanting copper 2/s and
    iron 10/s reported both sorters at 6/s and passed, while the iron sorter was
    moving 10/s against a 6/s tier.

    Falls back to the even split only when the item cannot be determined, which
    ``flow.lane_attribution`` reports separately whenever it matters.
    """
    bs = ctx.placement.buildings
    s = bs[index]
    src, dst = s.input_obj, s.output_obj
    if src is None or dst is None:
        return None
    if not (0 <= src < len(bs) and 0 <= dst < len(bs)):
        return None
    table = items if items is not None else _sorter_items(ctx)
    item = table.get(index)
    if ctx.kinds[dst] is Kind.MACHINE:
        g = ctx.group_for(dst)
        if g is None:
            return None
        return _item_share(ctx, g.inputs_per_machine, item, dst, table, feeding=True)
    if ctx.kinds[src] is Kind.MACHINE:
        g = ctx.group_for(src)
        if g is None:
            return None
        return _item_share(ctx, g.outputs_per_machine, item, src, table, feeding=False)
    return None


def _run_labels(ctx: Context) -> dict[int, set[str]]:
    """``carries_item`` labels on each run, carried across junctions.

    Independent of sorters, so it can be consulted while resolving what a sorter
    moves without the two definitions chasing each other.
    """
    bs = ctx.placement.buildings
    labels: dict[Node, set[str]] = defaultdict(set)
    for r, run in enumerate(ctx.runs):
        for i in run.indices:
            carried = bs[i].carries_item
            if carried:
                labels[(RUN, r)].add(carried)
    changed = True
    while changed:
        changed = False
        for edges in (ctx.succ, ctx.pred):
            for node, neighbours in edges.items():
                here = labels.get(node)
                if not here:
                    continue
                for m in neighbours:
                    if not here <= labels[m]:
                        labels[m] |= here
                        changed = True
    return {r: labels[(RUN, r)] for r in range(len(ctx.runs)) if labels.get((RUN, r))}


def _sorter_item(ctx: Context, index: int) -> str | None:
    """The FactorioLab item id a sorter moves, or ``None`` if undeterminable.

    Three sources, most reliable first: an explicit ``filter_id``, the
    ``carries_item`` label on the belt it touches, and -- only when the machine
    leaves no ambiguity -- the single item that machine consumes or produces.
    """
    bs = ctx.placement.buildings
    s = bs[index]

    if s.filter_id and ctx.ids is not None:
        named = ctx.ids.item_name(s.filter_id)
        if named is not None:
            return named

    for link in (s.input_obj, s.output_obj):
        if link is None or not (0 <= link < len(bs)):
            continue
        if ctx.kinds[link] is Kind.BELT and bs[link].carries_item:
            return bs[link].carries_item

    # A branch belt may carry no label of its own while the trunk filling it
    # does -- a strategy that labels the lane it routes and not the stub it taps
    # from is the normal case, and the label does not survive the junction.
    # When every labelled belt in the lane network agrees on ONE item, there is
    # nothing ambiguous to resolve and the sorter moves that item.  Without
    # this, `flow.sorter_capacity` skipped the sorter entirely and
    # `flow.lane_attribution` reported an ambiguity the geometry does not have.
    labels = _run_labels(ctx)
    for link in (s.input_obj, s.output_obj):
        if link is None or link not in ctx.run_of:
            continue
        known = labels.get(ctx.run_of[link], set())
        if len(known) == 1:
            return next(iter(known))

    # Unambiguous only when the machine deals in exactly one item on that side.
    src, dst = s.input_obj, s.output_obj
    if dst is not None and 0 <= dst < len(bs) and ctx.kinds[dst] is Kind.MACHINE:
        g = ctx.group_for(dst)
        if g is not None and len(g.inputs_per_machine) == 1:
            return next(iter(g.inputs_per_machine))
    if src is not None and 0 <= src < len(bs) and ctx.kinds[src] is Kind.MACHINE:
        g = ctx.group_for(src)
        if g is not None and len(g.outputs_per_machine) == 1:
            return next(iter(g.outputs_per_machine))
    return None


def _sorter_items(ctx: Context) -> dict[int, str | None]:
    """Item per sorter, resolved once.

    Built in one pass because both flow checks need it and resolving per call
    would make every check quadratic in the sorter count.
    """
    return {i: _sorter_item(ctx, i) for i, _ in ctx.of_kind(Kind.SORTER)}


def _item_share(
    ctx: Context,
    rates: Mapping[str, Fraction],
    item: str | None,
    machine: int,
    items: Mapping[int, str | None],
    *,
    feeding: bool,
) -> Fraction | None:
    """This sorter's slice of a machine's demand for one item.

    When the item is known, the slice is that item's rate divided among the
    sorters moving *that same item* to or from the machine.  When it is not, the
    old even split across every sorter is the only available estimate, and
    ``flow.lane_attribution`` reports the cases where relying on it would matter.
    """
    if item is not None and item in rates:
        peers = sum(
            1
            for j, o in ctx.of_kind(Kind.SORTER)
            if (o.output_obj if feeding else o.input_obj) == machine and items.get(j) == item
        )
        return rates[item] / (peers or 1)
    total = sum(rates.values(), Fraction(0))
    share = sum(
        1
        for _j, o in ctx.of_kind(Kind.SORTER)
        if (o.output_obj if feeding else o.input_obj) == machine
    )
    return total / (share or 1)


def _run_items(ctx: Context, items: Mapping[int, str | None]) -> dict[int, set[str | None]]:
    """Items drawn from or put onto each belt run, ``None`` for undeterminable.

    A run holding more than one entry is a SHARED lane -- several item types on
    one belt, which DSP supports natively and real builds use heavily (236 of
    1,288 corpus sorters set a filter; falk-v7-mall-full sets one on all 196).

    Item identity CROSSES a junction, in both directions.  An item put onto a
    trunk reaches every branch drawn from it, and an item taken off a branch must
    have travelled the trunk to get there.  Reading only the sorters that touch a
    run left every belt between two junctions carrying nothing at all, so a
    mixed trunk with an unfiltered sorter downstream -- the case
    ``flow.lane_attribution`` exists to refuse to judge -- read as a clean
    single-item lane.
    """
    carried: dict[Node, set[str | None]] = defaultdict(set)
    for i, s in ctx.of_kind(Kind.SORTER):
        for link in (s.input_obj, s.output_obj):
            if link is not None and link in ctx.run_of:
                carried[(RUN, ctx.run_of[link])].add(items.get(i))

    changed = True
    while changed:
        changed = False
        for edges in (ctx.succ, ctx.pred):
            for node, neighbours in edges.items():
                here = carried.get(node)
                if not here:
                    continue
                for m in neighbours:
                    if not here <= carried[m]:
                        carried[m] |= here
                        changed = True

    return {r: carried[(RUN, r)] for r in range(len(ctx.runs)) if carried.get((RUN, r))}


@check("flow.lane_attribution", needs_spec=True)
def _lane_attribution(ctx: Context) -> Iterable[Finding]:
    """A shared lane whose shares cannot be attributed is not judgeable.

    An unfiltered sorter drawing from a lane that carries several item types
    takes whatever passes, so its slice of the lane's capacity is unknown -- and
    a capacity verdict computed from the even-split estimate would be a verdict
    the build never earned.  Reported rather than assumed, because a check that
    quietly stops applying is worse than one that fails.

    A single-input machine is NOT ambiguous even without a filter: the recipe
    names the item.  Only genuine ambiguity is reported.
    """
    assert ctx.spec is not None
    items = _sorter_items(ctx)
    network = _run_components(ctx)
    for ridx, carried in sorted(_run_items(ctx, items).items()):
        if len(carried) < 2 or None not in carried:
            continue  # single-item lane, or shared but fully attributed
        # The unnameable sorter need not stand on THIS run.  Once items cross a
        # junction, a trunk can be a mixed lane because of a sorter two branches
        # away, and naming only the sorters touching the trunk produced a
        # finding with an empty culprit list -- an error nobody could act on.
        # The ambiguity belongs to the connected lane network, so the culprits
        # are drawn from it.
        here = network.get(ridx)
        culprits = tuple(
            i
            for i, s in ctx.of_kind(Kind.SORTER)
            if items.get(i) is None
            and any(
                link is not None
                and link in ctx.run_of
                and network.get(ctx.run_of[link]) == here
                for link in (s.input_obj, s.output_obj)
            )
        )
        known = sorted(c for c in carried if c is not None)
        yield Finding(
            "flow.lane_attribution",
            Severity.ERROR,
            f"belt run {ridx} carries several items ({', '.join(known)} and at least one "
            f"more) but sorter(s) {list(culprits)} name no item, so their share of the "
            f"lane cannot be determined and its capacity cannot be judged",
            culprits,
            {"run": ridx, "known_items": known, "unattributed": list(culprits)},
        )


def _propagate(
    ctx: Context, own: Mapping[Node, ItemRates], *, downstream: bool
) -> dict[Node, dict[str | None, Fraction]]:
    """Accumulate per-item rates along the flow graph, in exact rationals.

    ``downstream=True`` answers "what is taken off past here" by walking
    ``succ``; ``downstream=False`` answers "what is put on before here" by
    walking ``pred``.

    A junction DIVIDES.  Reaching node *m* from *n*, only ``1/len(preds(m))`` of
    *m*'s downstream demand is charged to *n*, because *m*'s other predecessors
    supply the rest -- charging each input a merge's whole load is how a
    correctly split lane acquires an invented violation.  Symmetrically, a
    junction's supply divides among its outputs.  Both divisions are exact
    ``Fraction`` arithmetic; a float here would produce capacity verdicts that
    depend on rounding, which is the one thing these checks exist to rule out.

    That even split is a fair-share ESTIMATE and not a bound, which is why
    ``flow.conservation`` does not use this function at all: a DSP splitter is
    not a fixed divider -- it feeds whichever output has room -- so charging a
    lane its arithmetic share is right for "how loaded is this belt" and wrong
    for "does anything starve".  See :func:`_lane_balance`.

    Cycles contribute nothing rather than looping forever.  A belt cycle is a
    real defect, but it is ``belt.acyclic``'s to report -- a capacity check that
    hung on one would be strictly worse than one that under-reports it.
    """
    onward = ctx.succ if downstream else ctx.pred
    splits = ctx.pred if downstream else ctx.succ
    memo: dict[Node, dict[str | None, Fraction]] = {}
    visiting: set[Node] = set()

    def walk(n: Node) -> dict[str | None, Fraction]:
        cached = memo.get(n)
        if cached is not None:
            return cached
        if n in visiting:
            return {}
        visiting.add(n)
        acc: dict[str | None, Fraction] = defaultdict(Fraction)
        for item, rate in own.get(n, {}).items():
            acc[item] += rate
        for m in onward.get(n, ()):
            share = len(splits.get(m, ())) or 1
            for item, rate in walk(m).items():
                acc[item] += rate / share
        visiting.discard(n)
        memo[n] = dict(acc)
        return memo[n]

    for r in range(len(ctx.runs)):
        walk((RUN, r))
    for j, _ in ctx.of_kind(Kind.SPLITTER):
        walk((JUNCTION, j))
    return memo


def _sorter_flows(ctx: Context) -> tuple[dict[Node, dict[str | None, Fraction]], ...]:
    """Per run, what sorters PUT onto it and what they TAKE off it."""
    items = _sorter_items(ctx)
    put: dict[Node, dict[str | None, Fraction]] = defaultdict(lambda: defaultdict(Fraction))
    take: dict[Node, dict[str | None, Fraction]] = defaultdict(lambda: defaultdict(Fraction))
    for i, s in ctx.of_kind(Kind.SORTER):
        rate = _sorter_demand(ctx, i, items)
        if rate is None:
            continue
        item = items.get(i)
        if s.output_obj is not None and s.output_obj in ctx.run_of:
            put[(RUN, ctx.run_of[s.output_obj])][item] += rate
        if s.input_obj is not None and s.input_obj in ctx.run_of:
            take[(RUN, ctx.run_of[s.input_obj])][item] += rate
    return put, take


def _run_demand(ctx: Context) -> dict[int, dict[str | None, Fraction]]:
    """Items/second each belt run must carry, broken down by item.

    Two independent lower bounds on what a lane carries, and the answer is the
    larger: what is taken OFF it (its own consumers, plus its share of every
    consumer past the junctions it feeds) and what is put ON it (its own
    producers, plus its share of everything pushed into the junctions that feed
    it).  Both cross junctions, which is the whole point -- a trunk feeding four
    branches through a splitter has no sorter of its own, so summing only the
    sorters that touch it charged that trunk ZERO and missed every genuine
    overload on it.

    The max is also what un-inflates the ordinary case.  Adding the two used to
    charge a lane its producer's 10/s *plus* its consumers' 10/s and call it
    20/s, which is not what a belt carries: put 10 on and take 10 off and the
    belt is carrying 10.  Measured on freeform's real output, five runs on
    ``fan_out_spec`` were being double-charged this way.

    The breakdown matters for shared lanes: a bare total says a lane is over
    capacity without saying which items put it there.  The flows on one lane are
    coupled by ONE capacity, so callers compare the SUM against the tier --
    judging items independently would accept 7/s plus 7/s on a 12/s belt because
    neither exceeds 12 alone.
    """
    put, take = _sorter_flows(ctx)
    pull = _propagate(ctx, take, downstream=True)
    push = _propagate(ctx, put, downstream=False)
    out: dict[int, dict[str | None, Fraction]] = {}
    for r in range(len(ctx.runs)):
        n = (RUN, r)
        drawn, filled = pull.get(n, {}), push.get(n, {})
        per_item = {
            item: max(drawn.get(item, Fraction(0)), filled.get(item, Fraction(0)))
            for item in (*drawn, *filled)
        }
        per_item = {item: rate for item, rate in per_item.items() if rate}
        if per_item:
            out[r] = per_item
    return out


@check("flow.headroom", needs_spec=True)
def _headroom(ctx: Context) -> Iterable[Finding]:
    """Saturation per run, as an exact fraction.

    INFO rather than ERROR: the user chose "throughput-correct" over
    "throughput-correct and no starvation", so a lane tapped in series is
    accepted as long as aggregate capacity suffices.  Reporting headroom makes
    near-saturation visible before it becomes a bug.
    """
    assert ctx.spec is not None
    for ridx, per_item in sorted(_run_demand(ctx).items()):
        capacity = cat.BELT_RATE.get(ctx.runs[ridx].tier_item_id)
        if not capacity:
            continue
        required = sum(per_item.values(), Fraction(0))
        breakdown = {(k or "unattributed"): str(v) for k, v in sorted(
            per_item.items(), key=lambda kv: (kv[0] is None, kv[0] or "")
        )}
        shared = f" ({', '.join(f'{k} {v}' for k, v in breakdown.items())})" if len(
            per_item
        ) > 1 else ""
        yield Finding(
            "flow.headroom",
            Severity.INFO,
            f"belt run {ridx} carries {required} of {capacity} items/s{shared}",
            ctx.runs[ridx].indices,
            {
                "run": ridx,
                "required": str(required),
                "capacity": str(capacity),
                "per_item": breakdown,
            },
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
