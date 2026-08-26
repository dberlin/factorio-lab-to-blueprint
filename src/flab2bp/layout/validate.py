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

import math
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from fractions import Fraction

from flab2bp.dsp import catalog as cat
from flab2bp.dsp import codec, colliders, params, rules
from flab2bp.dsp import colliders as dsp_colliders
from flab2bp.layout import slots
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
    #: Check ids that were evaluated -- and evaluated over EVERYTHING they claim
    #: to cover.  A check listed here and carrying no finding is a real pass.
    checks_run: tuple[str, ...] = ()
    #: Check ids that could not be evaluated, in whole or in part, and whose
    #: silence therefore means nothing.  Surfaced explicitly so an unvalidated
    #: build never reads as a clean one.
    #:
    #: "In part" is the half that had to be added.  A check that ran over most
    #: of a placement and hit one machine it could not resolve used to sit in
    #: ``checks_run`` looking like a pass -- see :data:`NEEDS_GROUPS`.  Such a
    #: check still produces findings, and they still count; what it may not do
    #: is claim coverage it did not have.
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


#: DSP item ids of the buildings a MODE configures rather than a recipe -- the
#: Energy Exchanger and the Ray Receiver.  Derived from the catalog registry so
#: adding a mode there cannot leave this behind.
MODE_DRIVEN_ITEM_IDS = frozenset(
    entry.machine_item_id for entry in cat.MODE_DRIVEN_MACHINE.values()
)


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
    # A mode-driven building is BOTH: DSP gives an Energy Exchanger a cover
    # radius of 7 and a Ray Receiver one of 10.5, and both also consume and
    # produce items on belts like any other machine.  `Kind` has room for one
    # answer, and the machine half is the one every check downstream needs --
    # `Kind.POWER`'s only consumer is `_tower_centres`, which asks the catalog
    # directly now.  Answering POWER here is what made an entire class of
    # machine invisible to ten checks: they iterate `Kind.MACHINE`, so the
    # exchanger was never handed to any of them and every one of them reported
    # as having run.
    if b.item_id in MODE_DRIVEN_ITEM_IDS:
        return Kind.MACHINE
    if info.cover_radius > 0:
        return Kind.POWER
    if info.is_belt_addon:
        return Kind.ADDON
    return Kind.MACHINE


def _supplies_power(b: PlacedBuilding) -> bool:
    """Whether this building is a node of the power network.

    The catalog fact, asked directly rather than inferred from ``Kind``.  It is
    the same predicate ``_kind`` used to decide ``Kind.POWER`` with, so the set
    of towers is unchanged -- see
    ``test_the_set_of_power_nodes_is_unchanged_by_the_reclassification``, which
    holds the two together over the whole catalog.
    """
    try:
        return cat.building(b.item_id).cover_radius > 0
    except KeyError:
        return False


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


@dataclass
class _Cache:
    """Derived indexes, built at most once per :func:`validate` call.

    Nothing here changes a verdict.  Every field is a pure function of the
    ``Context`` it hangs off, and several checks want the same one: measured on
    a 37,225-building ``universe-matrix`` placement, ``flow.belt_capacity`` and
    ``flow.headroom`` each rebuilt the whole ``_run_demand`` propagation, and
    ``ctx.of_kind`` -- a full scan of every building -- was called once per
    sorter from inside ``_item_share``, which made the sorter checks quadratic.

    It is a mutable box on a frozen ``Context`` on purpose: the Context is the
    immutable *statement* of what was placed, and this is scratch space for
    answering questions about it.  ``compare=False`` keeps it out of ``__eq__``
    and ``__hash__`` so two Contexts over the same placement stay equal whatever
    either has happened to compute.

    WHAT COMES OUT OF HERE IS SHARED.  Several of these hold mutable sets and
    dicts, and a check that modifies one in place changes what a later check
    reads -- which is an order dependence, the one way this optimisation could
    change a verdict.  Copy before mutating.  The guard is
    ``test_a_check_alone_says_what_it_says_inside_a_whole_run``, whose docstring
    is honest about how much of that it can see on a small placement.
    """

    of_kind: dict[Kind, tuple[tuple[int, PlacedBuilding], ...]] = field(default_factory=dict)
    group_for: dict[int, MachineGroup | None] = field(default_factory=dict)
    unresolved_machines: tuple[int, ...] | None = None
    recipe_names: dict[int, str] | None = None
    item_names: dict[int, str] | None = None
    tower_centres: list[tuple[int, Fraction, Fraction, Fraction, Fraction]] | None = None
    sorter_items: dict[int, str | None] | None = None
    run_labels: dict[int, set[str]] | None = None
    run_items: dict[int, set[str | None]] | None = None
    run_components: dict[int, int] | None = None
    run_demand: dict[int, dict[str | None, Fraction]] | None = None
    entry_runs: dict[str, list[int]] | None = None
    entry_items: dict[int, set[str]] | None = None
    sorter_peers: _SorterPeers | None = None
    coater_rides: dict[int, int] | None = None


@dataclass(frozen=True)
class _SorterPeers:
    """How many sorters share a machine's load, counted once instead of per call.

    ``_item_share`` asked this question with a scan over every building, once
    per sorter, so the cost was ``sorters x buildings``: 986 x 37,225 on
    ``universe-matrix``, twice over (``flow.sorter_capacity`` and
    ``_sorter_flows``).  The counts are keyed exactly as the scans matched --
    ``output_obj`` for a sorter FEEDING a machine, ``input_obj`` for one
    DRAWING from it -- so the divisor is the same integer either way.
    """

    #: (machine, item) -> sorters feeding that machine with that named item.
    feed_item: Mapping[tuple[int, str], int]
    #: machine -> sorters feeding it at all.
    feed_any: Mapping[int, int]
    #: (machine, item) -> sorters drawing that named item from that machine.
    draw_item: Mapping[tuple[int, str], int]
    #: machine -> sorters drawing from it at all.
    draw_any: Mapping[int, int]


@dataclass(frozen=True)
class Context:
    placement: Placement
    spec: BuildSpec | None
    ids: IdMap | None
    soft_width: int
    #: Ceiling on belt altitude for THIS run, in tiles of height.  A property
    #: of the player's save rather than of the game -- how high a belt may go
    #: depends on their vertical-construction unlocks -- so it is passed in,
    #: never read from a constant.
    max_belt_z: Fraction
    #: Whether this save has the ``beltVerticalConstruction`` tech.  It
    #: switches OFF the game's slope test entirely, so with it a belt may
    #: climb straight up and without it nothing may exceed
    #: ``MAX_BELT_SLOPE``.  A save property, declared, never inferred.
    belt_vertical_construction: bool
    kinds: tuple[Kind, ...]
    #: cell -> building indices standing on it.  Sorters are absent by design:
    #: their anchors sit *on* the buildings they serve, and the tiles they span
    #: are not exclusively theirs in this model.  Belts and splitters ARE here,
    #: so sorter anchors and belt links can be resolved against them.
    occupancy: Mapping[tuple[int, int, Fraction], tuple[int, ...]]
    #: cell -> building indices that exclusively *reserve* it.  Belt-integrated
    #: buildings (belts, sorters, splitters) are absent; this is what
    #: ``geom.overlap`` judges.
    blocking: Mapping[tuple[int, int, Fraction], tuple[int, ...]]
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
    #: Scratch space for indexes several checks want; see :class:`_Cache`.
    cache: _Cache = field(default_factory=lambda: _Cache(), compare=False, repr=False)

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
        directions are counted together against
        :data:`flab2bp.dsp.rules.SPLITTER_MAX_PORTS`.
        """
        return _dedup_ints(
            (*self.junction_in.get(junction, ()), *self.junction_out.get(junction, ()))
        )

    def of_kind(self, kind: Kind) -> Iterator[tuple[int, PlacedBuilding]]:
        """Every building of one kind, with its index, in placement order.

        Bucketed once per kind rather than rescanned per call.  Thirty-odd call
        sites walk this, several of them from inside a per-sorter loop, so the
        rescan was the largest single cost in the flow checks.
        """
        got = self.cache.of_kind.get(kind)
        if got is None:
            got = tuple(
                (i, b) for i, b in enumerate(self.placement.buildings) if self.kinds[i] is kind
            )
            self.cache.of_kind[kind] = got
        return iter(got)

    def recipe_name(self, rid: int) -> str | None:
        """``IdMap.recipe_name``, over a reverse index built once.

        The map itself scans its whole ``recipes`` dict per lookup, and this is
        asked once per machine and once per sorter.  First value wins, exactly
        as the linear scan's ``return`` did.
        """
        if self.ids is None:
            return None
        table = self.cache.recipe_names
        if table is None:
            table = {}
            for name, value in self.ids.recipes.items():
                table.setdefault(value, name)
            self.cache.recipe_names = table
        return table.get(rid)

    def item_name(self, iid: int) -> str | None:
        """``IdMap.item_name``, over a reverse index built once."""
        if self.ids is None:
            return None
        table = self.cache.item_names
        if table is None:
            table = {}
            for name, value in self.ids.items.items():
                table.setdefault(value, name)
            self.cache.item_names = table
        return table.get(iid)

    def group_for(self, index: int) -> MachineGroup | None:
        """The ``MachineGroup`` a placed machine belongs to, if determinable."""
        cached = self.cache.group_for
        if index in cached:
            return cached[index]
        cached[index] = got = self._group_for(index)
        return got

    def unresolved_machines(self) -> tuple[int, ...]:
        """Placed machines this Context cannot match to a group in the spec.

        Nine checks answer their question by asking what a machine is supposed
        to be doing, and every one of them opened with ``if g is None:
        continue``.  That turns "I could not tell" into "I found nothing wrong",
        which is the one answer a validator must never give silently -- so the
        set is computed once, reported as an ERROR by ``machine.group_resolved``
        and used by :func:`validate` to keep those ten checks out of
        ``checks_run``.
        """
        got = self.cache.unresolved_machines
        if got is None:
            got = tuple(
                i for i, _ in self.of_kind(Kind.MACHINE) if self.group_for(i) is None
            )
            self.cache.unresolved_machines = got
        return got

    def recipe_of(self, index: int) -> str | None:
        """The FactorioLab recipe id a placed machine runs, if determinable.

        One door for the question "what is this machine supposed to be doing",
        so a caller cannot accidentally ask the half of it that skips a
        mode-driven machine.  ``prolif.belt_required_edges_not_direct_inserted``
        asked ``recipe_name(b.recipe_id)`` directly and was the ninth check to
        lose sight of an exchanger this way.
        """
        g = self.group_for(index)
        return None if g is None else g.recipe_id

    def _group_for(self, index: int) -> MachineGroup | None:
        if self.spec is None or self.ids is None:
            return None
        b = self.placement.buildings[index]
        if b.item_id in MODE_DRIVEN_ITEM_IDS:
            return self._mode_driven_group(b)
        name = self.recipe_name(b.recipe_id)
        if name is None:
            return None
        for g in self.spec.groups:
            if g.recipe_id == name:
                return g
        return None

    def _mode_driven_group(self, b: PlacedBuilding) -> MachineGroup | None:
        """The group a mode-driven machine realises, keyed by building and mode.

        There is no recipe id to look up and there never was: DSP has no recipe
        for a MODE, so ``catalog.recipe_id`` raises for one and
        ``pipeline._id_map`` carries no entry.  What identifies the machine is
        the pair the placement does carry -- which building it is, and which
        mode its parameter block selects.

        The parameter block is part of the key rather than a tie-break.  Charge
        and discharge run on the same Energy Exchanger and their item flows are
        exact opposites, so matching on the building alone could hand a
        charging machine the discharging group's ingredients and call it
        supplied.

        Returns ``None`` when the pair does not single a group out -- a spec
        holding both Ray Receiver photon recipes is the real case, since the
        Graviton Lens that separates them is an ITEM the receiver consumes and
        not a different setting, so both emit the same block.  Guessing between
        them would be a fallback; the caller is required to treat ``None`` as
        "could not be evaluated", never as "nothing wrong here".
        """
        assert self.spec is not None
        matched = [
            g
            for g in self.spec.groups
            if (entry := cat.MODE_DRIVEN_MACHINE.get(g.recipe_id)) is not None
            and entry.machine_item_id == b.item_id
            and params.parameters_for(g.recipe_id) == b.parameters
        ]
        return matched[0] if len(matched) == 1 else None


def _occupied_tiles(b: PlacedBuilding, kind: Kind) -> list[tuple[int, int, Fraction]]:
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
    placement: Placement,
    spec: BuildSpec | None,
    ids: IdMap | None,
    soft_width: int,
    max_belt_z: Fraction,
    belt_vertical_construction: bool,
) -> Context:
    kinds = tuple(_kind(b) for b in placement.buildings)
    occ: dict[tuple[int, int, Fraction], list[int]] = defaultdict(list)
    blocking: dict[tuple[int, int, Fraction], list[int]] = defaultdict(list)
    for i, b in enumerate(placement.buildings):
        # One question about the building, not one per tile of it: a 9x5
        # chemical plant asked it 45 times and always got the same answer.
        blocks = not cat.is_belt_integrated(b.item_id)
        for cell in _occupied_tiles(b, kinds[i]):
            occ[cell].append(i)
            if blocks:
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
        max_belt_z=max_belt_z,
        belt_vertical_construction=belt_vertical_construction,
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

#: Checks that are correct, tested, and NOT run unless a caller names them.
#:
#: EMPTY, and that is the finding.  ``geom.collide`` was here because it fired on
#: almost everything we produced: 443 of the ~530 pairs were one defect, an
#: Assembling Machine packed three tiles apart when its 3.82-unit collider needs
#: four at 1.2566 units per tile.  Spacing fixed that, the count went to 2, and
#: turning the check on cost NO coverage -- both strategies lay out exactly the
#: same 7 of 12 specs with it on as with it off.  So it runs by default now, and
#: the two remaining pairs are refusals rather than shipped defects.
#:
#: Anything put back in here needs the same shape of evidence: a measurement of
#: what it costs to leave on, not a note that it is inconvenient.
#:
#: ``game.belt_collide`` WAS here, on exactly that evidence and for exactly the
#: shape of defect ``geom.collide`` was here for: a Splitter's
#: ``catalog.footprint`` is 1x1 against a build collider that is a 2.38-unit
#: cross standing 2.30 units tall, so both strategies routed belts a tile from
#: one -- and one LEVEL above one, which is still inside it.  It came out the
#: same way ``geom.collide`` did: by giving the layouts the collider, not by
#: widening a bound.  ``colliders.belt_keepout_offsets`` measures the cells it
#: denies and ``junction.keepout_cells`` names them.
#:
#: Freeform stakes every belt before it takes a tap, so its site test is asked a
#: question that has an answer; ``_merge_frontier`` steers the router off a tap
#: whose keep-out already holds a foreign belt; and a junction guards its
#: collider's room against the passes that come after routing.  Spine lifted its
#: TRUNKS a level instead and left the bridges on the ground -- the keep-out is
#: asymmetric in ``z``, so a crossing that passes underneath is clear by
#: construction where one that passes over is not.
#:
#: Measured paired and interleaved against a pristine base checkout: 25 convicted
#: corpus cells to 0.  See the backlog entry for the distribution.
OPT_IN: set[str] = set()

#: Check ids whose COVERAGE depends on matching each placed machine to the spec
#: group it realises.  When any machine cannot be matched, these checks still
#: run and their findings still stand -- but they are reported in
#: ``Report.skipped`` rather than ``Report.checks_run``, because they did not
#: examine everything they claim to cover and their silence proves nothing.
#:
#: The membership is not a judgement call.  It is every check that reaches
#: ``Context.group_for``, transitively, through this module's own call graph.
#: That is TEN checks where the defect report named three: three call it
#: directly, five arrive through ``_lane_balance``, ``_sorter_demand``,
#: ``_run_demand`` and ``_sorter_item``, and two -- ``spec.machine_counts`` and
#: ``prolif.belt_required_edges_not_direct_inserted`` -- resolved a machine
#: through the raw recipe id instead and now go through ``recipe_of``.
#: ``test_every_check_that_consults_group_for_declares_it`` recomputes that
#: closure and fails if this set drifts from it.
NEEDS_GROUPS: set[str] = set()


def check(
    cid: str, *, needs_spec: bool = False, needs_groups: bool = False
) -> Callable[[Check], Check]:
    def register(fn: Check) -> Check:
        CHECKS[cid] = fn
        if needs_spec:
            NEEDS_SPEC.add(cid)
        if needs_groups:
            NEEDS_GROUPS.add(cid)
        return fn

    return register


# --- geometry --------------------------------------------------------------


@check("geom.footprint")
def _footprint(ctx: Context) -> Iterable[Finding]:
    """The declared footprint says where the building will actually be built.

    Not a game predicate.  It is the check that lets the game predicates mean
    anything, and it exists because of what ``PlacedBuilding.width``/``height``
    are.  Their own docstring calls them a footprint "cached here so geometry
    checks never need the catalog" -- a cache with no invalidation, filled in by
    hand by whichever strategy placed the building, and until now compared
    against nothing.

    Everything downstream reads the cache instead of the table.
    ``codec.tile_to_local_offset`` turns the min-corner anchor into DSP's
    ``localOffset`` as ``x + width / 2 - 0.5``, so the declared size decides the
    world position that gets EMITTED; ``geom.collide`` builds its
    ``colliders.Placed`` from that same offset, so a wrong size makes it test a
    real collider box at a pose that does not exist and hand back a confident
    pass.  A ported rule fed a wrong size is not a rule, it is a rubber stamp.

    TWO BRANCHES, because two conventions are in use and both are correct.

    A building that OCCUPIES TILES anchors on the minimum corner of its
    footprint, so its declared size must be
    ``catalog.oriented_footprint(item_id, yaw)`` -- the prefab's, with the
    quarter turn applied.  Copying ``catalog.footprint`` and forgetting the turn
    is a live hazard rather than a hypothetical: ``layout.spine`` carries a
    comment about exactly that case.

    A BELT ADDON anchors on the belt tile it RIDES, and must declare ``1x1`` so
    that ``tile_to_local_offset`` leaves its centre on that tile.  This is
    measured, not assumed: across ``factory-heretical-smelter-block`` and
    ``tillable-blackbox-module-...``, blueprints the game itself wrote, all
    eight Spray Coaters sit at their nearest belt's position to within
    ``(0.000, 0.000, 0.001)``.  A Spray Coater's prefab footprint is ``1x3`` and
    its collider is 3.5 world units long, and NEITHER of those is its anchor;
    ``occupies_tiles`` is false for it precisely because the tiles its collider
    covers are not tiles it reserves.  Asserting the prefab footprint here would
    convict a correct coater and, if anyone "fixed" the strategy to satisfy it,
    would move all twenty coaters a tile off their belts.  That was tried on
    this branch and reverted; the branch is here so it cannot be tried again by
    accident.

    HONEST NEGATIVE: this check convicts NOTHING in either strategy today.  A
    reported figure of 36 violations was all Spray Coaters and was the wrong
    reading above.  It is a guard on a cache, not a fix for a defect, and it is
    on by default because a check that fires on nothing costs nothing to run.
    """
    for i, b in enumerate(ctx.placement.buildings):
        try:
            info = cat.building(b.item_id)
        except KeyError:
            # Not in the catalog at all: there is no prefab to compare against,
            # and inventing one would be the same class of error as the cache.
            continue
        if info.occupies_tiles:
            want = cat.oriented_footprint(b.item_id, b.yaw)
            why = (
                f"its prefab at yaw {b.yaw:g} is {want[0]}x{want[1]} and it anchors "
                f"on the minimum corner of that footprint"
            )
        else:
            want = (1, 1)
            why = (
                "a belt addon anchors on the belt tile it rides, so it declares 1x1 "
                "and its centre stays on that tile"
            )
        if (b.width, b.height) != want:
            yield Finding(
                "geom.footprint",
                Severity.ERROR,
                f"building {i} ({info.name}) at ({b.x}, {b.y}) declares a "
                f"{b.width}x{b.height} footprint; {why}. The declared size is what "
                f"the emitter turns into a world position and what the collider "
                f"check tests, so both are wrong for it",
                (i,),
                {
                    "declared": f"{b.width}x{b.height}",
                    "expected": f"{want[0]}x{want[1]}",
                    "yaw": b.yaw,
                },
            )


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


@check("geom.collide")
def _collide(ctx: Context) -> Iterable[Finding]:
    """No two build colliders intersect -- the game's ``EBuildCondition.Collide``.

    ``geom.overlap`` asks whether two buildings claim the same TILE.  The game
    does not ask that.  It puts every preview's ``PrefabDesc.buildColliders``
    into the physics world on layer 18 and runs
    ``Physics.OverlapBoxNonAlloc(collider.pos, collider.ext, ..., mask 395264)``
    per preview (``BuildTool_BlueprintPaste.CheckBuildConditions``, decompiled
    lines 145712-145760); an un-excused hit is
    ``buildPreview2.condition = EBuildCondition.Collide`` at line 146071.  The
    two questions have different answers because a tile is 1.2566 world units
    wide, not 1.0 -- see :mod:`flab2bp.dsp.colliders` for that derivation.

    The consequence a tile model cannot see: an Assembling Machine's collider is
    3.82 units across, three tiles is 3.770, so two of them three tiles apart
    intersect by 0.05 units even though their 3x3 footprints do not share a cell.
    Every real blueprint in the corpus spaces assemblers four tiles or more, and
    none spaces them three.

    Scope.  Belts and sorters are excluded, for reasons set out on
    :func:`flab2bp.dsp.colliders.collisions`: the game excuses a sorter against
    anything that is not a sorter, and the belt model -- which IS a real rule,
    a 0.23 sphere that is not excused against machines -- still over-reports on
    blueprints the game wrote, so it is not shipped.  This check is therefore a
    lower bound on what the game will reject, never an upper one.
    """
    tested = [
        (i, b)
        for i, b in enumerate(ctx.placement.buildings)
        if ctx.kinds[i] not in (Kind.BELT, Kind.SORTER)
    ]
    # `PlacedBuilding.x` is the footprint's minimum corner; the game stores and
    # centres the collider on the CENTRE.  Going through the encoder's own
    # conversion rather than a second copy of it means the check can never be
    # testing a different building from the one that gets written out.
    placed = [
        dsp_colliders.Placed(b.model_index, *codec.tile_to_local_offset(
            b.x, b.y, b.z, b.width, b.height
        ), b.yaw)
        for _i, b in tested
    ]
    for a, c in dsp_colliders.collisions(placed):
        ia, ba = tested[a]
        ic, bc = tested[c]
        yield Finding(
            "geom.collide",
            Severity.ERROR,
            f"build colliders intersect: {cat.building(ba.item_id).name} at "
            f"({ba.x}, {ba.y}) and {cat.building(bc.item_id).name} at ({bc.x}, {bc.y}) "
            f"-- {abs(bc.x - ba.x)} x {abs(bc.y - ba.y)} tiles apart",
            (ia, ic),
            {
                "a": str((ba.x, ba.y, str(ba.z))),
                "b": str((bc.x, bc.y, str(bc.z))),
                "dx": str(bc.x - ba.x),
                "dy": str(bc.y - ba.y),
            },
        )


@check("game.sorter_collide")
def _sorter_collide(ctx: Context) -> Iterable[Finding]:
    """Two sorters whose stretched build colliders intersect.

    ``geom.collide`` leaves sorters out because the game excuses a sorter
    against everything that is not a sorter.  This is the other half of that
    sentence: sorter against SORTER is the one pairing the excusal does not
    forgive, and :func:`flab2bp.dsp.colliders.sorter_collisions` holds the C#
    for both the excusal and the box.

    Two things this check must do that a naive port would not, and both are
    load-bearing:

    * **Seat each end on the slot pose it names.**  The paste MOVES a sorter's
      machine end onto ``slotPoses[slot].GetTransformedBy(machine pose)`` before
      it tests anything (``BlueprintUtils.RefreshBuildPreview`` 2090-2190).  We
      emit tile centres; the game does not build them there.  Testing the tile
      centre would be testing a sorter the game will not paste.  A belt end is
      NOT seated -- the game's own guard is ``!desc.isBelt``.
    * **Stretch the box.**  A sorter's collider is not the prefab box at the
      record's position; it spans the two ends and grows past any end that meets
      a belt or nothing.

    WHY THIS IS AN ERROR AND NOT OPT-IN, which is the question ``game.belt_collide``
    answers the other way.  Over the 1132 sorters in the five single-area
    fixtures this reports ZERO pairs, and the sample is not vacuous -- the same
    corpus overlaps sorter bodies on a shared tile 97 times and carries 35
    belt-to-belt sorters, so a rule that convicted either shape would light it
    up.  Against that, the blueprint in ``tests/fixtures/sorter-collide-freeform.txt``
    -- which the user pasted and the game refused with "Collide with other
    object" -- is convicted on exactly the two clusters the game drew red, at
    0.30 units of penetration against a measured model noise floor of 0.002.
    """
    seats: list[tuple[int, dsp_colliders.SorterPreview]] = []
    for i, b in ctx.of_kind(Kind.SORTER):
        seat = slots.seated_sorter(b, ctx.placement.buildings)
        if seat is not None:
            seats.append((i, seat))

    for a, c in dsp_colliders.sorter_collisions([p for _i, p in seats]):
        ia, ic = seats[a][0], seats[c][0]
        ba, bc = ctx.placement.buildings[ia], ctx.placement.buildings[ic]
        yield Finding(
            "game.sorter_collide",
            Severity.ERROR,
            f"sorter colliders intersect: sorter {ia} "
            f"({ba.x},{ba.y})->({ba.x2},{ba.y2}) and sorter {ic} "
            f"({bc.x},{bc.y})->({bc.x2},{bc.y2}); the game excuses a sorter "
            f"against everything except another sorter",
            (ia, ic),
            {
                "a": str((ba.x, ba.y, ba.x2, ba.y2)),
                "b": str((bc.x, bc.y, bc.x2, bc.y2)),
            },
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
    """Machines this GENERATOR places sit on the ground.

    Not a rule of the game: DSP stacks Matrix Labs, and the corpus has 120 of
    them in 10 columns of 12 at ``z = 0, 3, 6, ... 33``.  This is our own
    invariant -- nothing we emit stacks -- and it is scoped to machines so it
    cannot be read as a claim about what the game permits.
    """
    for i, b in ctx.of_kind(Kind.MACHINE):
        if b.z != 0:
            yield Finding(
                "geom.machine_ground",
                Severity.ERROR,
                f"machine {i} sits at altitude {b.z}; this generator places every "
                f"machine on the ground (the GAME does stack: real Matrix Labs "
                f"reach z=33)",
                (i,),
                {"z": b.z},
            )


@check("geom.altitude_range")
def _altitude_range(ctx: Context) -> Iterable[Finding]:
    """Belt altitudes are half-tile multiples, within the run's ceiling.

    Scoped to BELTS.  It used to run over every building against
    ``0 .. MAX_BELT_STACK_LEVELS - 1``, which both let a belt reach ``z = 2`` by
    an illegal step and would have rejected a legal stacked machine.

    The ceiling comes from :attr:`Context.max_belt_z`, not from a constant: how
    high a belt may go is a property of the player's SAVE -- their
    vertical-construction unlocks -- and the user's own save reaches 38.
    """
    ceiling = ctx.max_belt_z
    for i, b in ctx.of_kind(Kind.BELT):
        if b.z < 0 or b.z > ceiling:
            yield Finding(
                "geom.altitude_range",
                Severity.ERROR,
                f"belt {i} at altitude {b.z}, outside 0..{ceiling} "
                f"(raise --max-belt-height if this save's vertical-construction "
                f"unlocks allow it)",
                (i,),
                {"z": b.z, "max": ceiling},
            )
        # The `b.z % cat.BELT_Z_QUANTUM != 0` clause was here, refusing a belt
        # whose altitude was not a multiple of a half level.  The game
        # quantises nothing.  Its own altitude is an integer counter that the
        # path tool increments (`BuildTool_Path.cs:388`, `altitude++`) and
        # clamps (`:444`, `if (altitude > 60) { altitude = 60; }`), converted to
        # a world radius at `:176`::
        #
        #     ... (float)altitude * 1.3333333f + ...
        #
        # and no branch anywhere compares a belt's height against a step size.
        # What bounds a belt vertically is the ceiling above -- `buildMaxHeight`
        # -- and the slope limit in `geom.altitude_step`; between them there is
        # no third rule for this one to be.
        #
        # `catalog.BELT_Z_QUANTUM` survives as what it always was: the step
        # OUR emitters climb in, which is a quality knob and is documented as
        # one at its definition.  It is no longer anything a blueprint can fail.


@check("geom.altitude_step")
def _altitude_step(ctx: Context) -> Iterable[Finding]:
    """A belt's slope may not exceed what the game allows.

    This is the game's own rule, from ``BuildTool_Path``::

        num25 = Mathf.Abs(Maths.SphericalSlopeRatio(a, b));
        if (!history.beltVerticalConstruction && num25 > 0.8f)
            buildPreview2.condition = EBuildCondition.TooSteep;

    ``SphericalSlopeRatio`` is ``(|b| - |a|) / horizontal distance`` -- WORLD
    rise over run -- and blueprint z is ``3/4`` of world height, so a link's
    slope is ``(dz / BELT_Z_PER_WORLD_UNIT) / dxy``.

    Three earlier versions of this check were all wrong, in instructive ways:

    * ``dz > 1`` let the shipped bug through, because a whole tile of height
      across one tile of run scores exactly ``1``;
    * ``dz > BELT_CLIMB_PER_TILE`` caught it but for the wrong reason, and
      would have rejected legal steeper ramps;
    * an enumeration of "ramp or vertical" was closer, but invented a
      two-form rule the game does not have -- there is one rule, on slope, and
      the vertical form is simply the case where the run is zero.

    A zero run makes the slope infinite, which only ``beltVerticalConstruction``
    permits.  That is a tech unlock and a property of the player's save, so it
    is declared per run alongside the height ceiling, never assumed.
    """
    bs = ctx.placement.buildings
    limit = cat.MAX_BELT_SLOPE
    for i, b in ctx.of_kind(Kind.BELT):
        o = b.output_obj
        if o is None or not (0 <= o < len(bs)) or ctx.kinds[o] is not Kind.BELT:
            continue
        nxt = bs[o]
        dz = nxt.z - b.z
        if dz == 0:
            continue
        dxy = abs(nxt.x - b.x) + abs(nxt.y - b.y)
        world_rise = abs(dz) / cat.BELT_Z_PER_WORLD_UNIT
        if dxy == 0:
            if not ctx.belt_vertical_construction:
                yield Finding(
                    "geom.altitude_step",
                    Severity.ERROR,
                    f"belt {i} rises {dz} to belt {o} without moving, which is "
                    f"an infinite slope; only the beltVerticalConstruction "
                    f"unlock permits that (pass --belt-vertical-construction "
                    f"if this save has it)",
                    (i, o),
                    {"dz": dz, "dxy": dxy},
                )
            continue
        if ctx.belt_vertical_construction:
            continue
        slope = world_rise / dxy
        if slope > limit:
            yield Finding(
                "geom.altitude_step",
                Severity.ERROR,
                f"belt {i} climbs {dz} to belt {o} across {dxy} tile(s): a "
                f"world slope of {float(slope):.3f}, over the {float(limit)} "
                f"the game allows without the beltVerticalConstruction unlock "
                f"(TooSteep)",
                (i, o),
                {"dz": dz, "dxy": dxy, "slope": float(slope)},
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
    # 32767, not 32768.  The count is written as a SIGNED Int16 and read back as
    # one, so 32768 does not round-trip -- it is written as -32768 and the game
    # allocates a negative array.  `BlueprintBuilding.cs:304-305`::
    #
    #     int num = ((parameters != null) ? parameters.Length : 0);
    #     w.Write((short)num);
    #
    # and back at `:121-122`::
    #
    #     int num2 = r.ReadInt16();
    #     parameters = new int[num2];
    #
    # `flab2bp.dsp.records` writes the same field the same way (`w.i16(...)`), so
    # the cap is a property of the format both ends share.  The old bound let
    # through the one value that corrupts.
    for i, b in enumerate(ctx.placement.buildings):
        if len(b.parameters) > 32767:
            yield Finding(
                "geom.bounds",
                Severity.ERROR,
                f"building {i} carries {len(b.parameters)} parameters, cap is 32767 "
                f"(the count is a signed Int16; 32768 writes as -32768)",
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


def _anchors(
    b: PlacedBuilding,
) -> tuple[tuple[int, int, Fraction], tuple[int, int, Fraction]] | None:
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


# `sorter.altitude` was here.  It refused a sorter whose two ends sat at
# different altitudes, on the evidence that `z2 - z` is exactly 0 for all 1288
# sorters in the fixture corpus.  That is a habit of the corpus's builders and
# not a rule: the game models an altitude-spanning sorter explicitly, and
# measures it.  `BuildTool_Inserter.cs:1311`::
#
#     float num4 = Mathf.Abs(lpos.magnitude - lpos2.magnitude) / 0.2f;
#
# -- the ends' difference in RADIUS, i.e. exactly the quantity the deleted check
# required to be zero -- and `:1347` uses it::
#
#     if (Mathf.Sqrt(num2 * num2 + num4 * num4) < num8)
#     {
#         buildPreview.condition = EBuildCondition.TooClose;
#         continue;
#     }
#
# where `num2` is the segments the sorter crosses.  That is a MINIMUM on the
# combined span, so altitude only ever helps a sorter satisfy it; no branch
# anywhere caps it.  A sorter reaching up to a raised belt is ordinary DSP.
#
# Nothing this repository emits produces one, so deleting the check changes no
# blueprint.  What it removes is an invented rule that would have refused a
# correct one.


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


def _addon_at(ctx: Context, link: int, cell: tuple[int, int, Fraction]) -> bool:
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


@check("sorter.own_slots")
def _own_slots(ctx: Context) -> Iterable[Finding]:
    """``output_from_slot == 0`` and ``input_to_slot == 1``, on every sorter.

    Constant on all 1288 sorters in the real corpus, with no exception at any
    tier, span or orientation.  Both strategies used to leave both at the
    dataclass default of ``0``, which made every sorter of the first build ever
    pasted in game render red -- and this suite reported ``INVALID 0`` for it,
    because nothing here looked at these fields at all.
    """
    for i, b in ctx.of_kind(Kind.SORTER):
        if (b.output_from_slot, b.input_to_slot) != (
            rules.OUTPUT_FROM_SLOT,
            rules.INPUT_TO_SLOT,
        ):
            yield Finding(
                "sorter.own_slots",
                Severity.ERROR,
                f"sorter {i} has (output_from_slot, input_to_slot) = "
                f"({b.output_from_slot}, {b.input_to_slot}); the game writes "
                f"({rules.OUTPUT_FROM_SLOT}, {rules.INPUT_TO_SLOT}) on all 1288 "
                f"sorters in the corpus",
                (i,),
                {
                    "output_from_slot": b.output_from_slot,
                    "input_to_slot": b.input_to_slot,
                },
            )


@check("sorter.peer_slots")
def _peer_slots(ctx: Context) -> Iterable[Finding]:
    """The slot a sorter names on each end matches what is standing there.

    Two distinct failures, and both paste as a broken sorter:

    * a BELT end must carry ``-1``.  All 1240 belt ends in the corpus do, and
      none carries anything else.
    * a MACHINE end must carry the perimeter slot its geometry implies.  A
      wrong index here is the difference between a sorter attached to a machine
      and one attached to nothing.
    """
    bs = ctx.placement.buildings
    for i, b in ctx.of_kind(Kind.SORTER):
        a = _anchors(b)
        if a is None:
            continue
        (x1, y1, _), (x2, y2, _) = a
        for label, link, recorded, end, other in (
            ("input", b.input_obj, b.input_from_slot, (x1, y1), (x2, y2)),
            ("output", b.output_obj, b.output_to_slot, (x2, y2), (x1, y1)),
        ):
            if link is None or not (0 <= link < len(bs)):
                continue
            peer = bs[link]
            if cat.is_belt(peer.item_id):
                if recorded != rules.BELT_SLOT:
                    yield Finding(
                        "sorter.peer_slots",
                        Severity.ERROR,
                        f"sorter {i}'s {label} end names belt {link} with slot "
                        f"{recorded}; a belt end is always {rules.BELT_SLOT}",
                        (i, link),
                        {"end": label, "slot": recorded},
                    )
                continue
            try:
                want = slots.machine_slot(
                    peer.item_id,
                    peer.yaw,
                    (
                        end[0] - (peer.x + (peer.width - 1) / 2),
                        end[1] - (peer.y + (peer.height - 1) / 2),
                    ),
                    (end[0] - other[0], end[1] - other[1]),
                )
            except slots.SlotUndetermined as exc:
                yield Finding(
                    "sorter.peer_slots",
                    Severity.ERROR,
                    f"sorter {i}'s {label} end names building {link} but no slot "
                    f"could be derived for it: {exc}",
                    (i, link),
                    {"end": label, "slot": recorded},
                )
                continue
            if recorded != want:
                yield Finding(
                    "sorter.peer_slots",
                    Severity.ERROR,
                    f"sorter {i}'s {label} end names building {link} "
                    f"({cat.building(peer.item_id).name}) with slot {recorded}; its "
                    f"geometry says {want}",
                    (i, link),
                    {"end": label, "slot": recorded, "expected": want},
                )


# --- the game's own build conditions ---------------------------------------
#
# Everything under `game.` is a port of a predicate in the decompiled
# Assembly-CSharp, named in each docstring, rather than a rule inferred from the
# fixture corpus.  They exist because inference kept being wrong in ways only an
# in-game paste revealed: a slot ring extrapolated from seven buildings, a
# "three slots per side" rule the Chemical Plant's eight-slot two-row table
# disproves, and four separate hypotheses burned against the same paste error.
#
# Where the game works on the sphere and we work on a plane, the docstring says
# so.  Distances are float because the game's are -- these are Unity
# `Vector3.magnitude` comparisons against literal `0.8f`/`1.6f` thresholds, and
# rounding them to rationals would not make them more true.
#
# THREE CONDITIONS WERE READ AND DELIBERATELY NOT PORTED
#
# `NeedGround` (23, "Foundation required") is NOT a property of a blueprint and
# no check here can predict it.  In `BuildTool_BlueprintPaste` it is a terrain
# raycast: for every `landPoint` of the footprint the game casts 18 m down and
# refuses when the hit is below `-0.3 - landOffset` of the planet radius, or
# when the ground and the water layer differ by more than `0.27 + landOffset`,
# or when nothing is hit at all.  It means "the ground you are pasting onto is
# not flat, or is water" -- the same blueprint pastes fine one tile away.  It
# does not auto-foundation because reform is a separate, opt-in pass
# (`ComputeReform`), and it is answered by levelling the ground, not by us.
#
# `OutOfVerticalConstructionHeight` (40) on the paste path applies ONLY to
# stacked Tanks, Storages, Labs and Splitters: it compares the stack level
# implied by the building's altitude against `history.labLevel` /
# `history.storageLevel`, which are tech unlocks.  We never stack any of the
# four.  The belt-height ceiling that carries the same message comes from
# `BuildTool_Path` and `BuildTool_Click`, where it is `history.buildMaxHeight`
# -- also an unlock, so a blueprint legal for one save is not for another, and
# a fixed number here would be wrong for somebody.
#
# `Collide`, `TooClose` and `TooFar` for non-sorters need the near-collider
# index of a live planet (`GetOverlappedObjectsNonAlloc` against what is already
# built), which a blueprint does not carry.  `geom.overlap` covers the part that
# is intrinsic to the placement; the rest is a property of where it is pasted.


def _slot_pose_of(
    ctx: Context, link: int, slot: int
) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    """World position and forward of ``slot`` on building ``link``.

    ``None`` exactly where the game skips its own geometry test -- no peer, a
    BELT peer (``!prefabDesc2.isBelt``), or a slot the peer's ``slotPoses`` does
    not cover (``slotPoses.Length > otherSlot``).  That last one is not a
    formality: it is why blueprints of ours with plainly wrong slots still
    pasted, and why any check built on it is silent rather than wrong for a
    Storage Tank or a Fractionator, neither of which defines a sorter slot.

    A negative index is skipped too.  In C# ``slotPoses[-1]`` throws; in Python
    it would quietly return the last slot, which is the sort of difference that
    turns a port into fiction.
    """
    bs = ctx.placement.buildings
    if not 0 <= link < len(bs):
        return None
    peer = bs[link]
    if cat.is_belt(peer.item_id):
        return None
    if not 0 <= slot < len(cat.building(peer.item_id).slot_poses):
        return None
    dx, dy, dz = slots.slot_offset(peer.item_id, peer.yaw, slot)
    centre_x = peer.x + (peer.width - 1) / 2
    centre_y = peer.y + (peer.height - 1) / 2
    return (
        (centre_x + dx, centre_y + dy, peer.z + dz),
        slots.slot_forward(peer.item_id, peer.yaw, slot),
    )


def _fpoint(p: tuple[int, int, Fraction]) -> tuple[float, float, float]:
    """A tile anchor as the float triple the game's own arithmetic uses.

    Altitude is an exact ``Fraction`` everywhere else here, and deliberately so.
    It stops being exact at this boundary and only at it: every predicate below
    is a Unity ``Vector3.magnitude`` or ``Vector3.Dot`` compared against a
    literal ``0.8f`` / ``1.6f`` / ``24f``, so carrying rationals into them would
    be precision the comparison cannot use and a claim of exactness the game
    does not make.
    """
    return (float(p[0]), float(p[1]), float(p[2]))


def _unit(
    to: tuple[float, float, float], frm: tuple[float, float, float]
) -> tuple[float, float, float]:
    """``(to - frm).normalized``.  Unity returns zero for a zero vector."""
    vx, vy, vz = to[0] - frm[0], to[1] - frm[1], to[2] - frm[2]
    n = math.sqrt(vx * vx + vy * vy + vz * vz)
    return (0.0, 0.0, 0.0) if n == 0.0 else (vx / n, vy / n, vz / n)


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


@check("game.inserter_data")
def _inserter_data(ctx: Context) -> Iterable[Finding]:
    """Port of ``BuildTool_BlueprintCopy.CheckInserterDataLegal(int _objId)``.

    The game's own answer to "is this sorter's data legal".  It runs when a
    blueprint is COPIED and again over every selected object before one is
    saved, and a sorter that fails it is drawn red with
    ``EBuildCondition.ErrorInserterData`` -- the "Sorter data error" of every
    failed in-game paste this project has produced.

    The C#, with our field names beside it::

        ReadObjectConn(_objId, 0, out isOutput,  out otherObjId,  out otherSlot)
        ReadObjectConn(_objId, 1, out isOutput2, out otherObjId2, out otherSlot2)

        if (otherObjId  != 0 && !isOutput) return false;   # own slot 0 = output
        if ((otherObjId2 != 0) & isOutput2) return false;  # own slot 1 = input

        # for the slot-0 peer, against objectPose2 (our x2/y2/z2 anchor):
        if (!isBelt && slotPoses.Length > otherSlot):
            transformedBy = slotPoses[otherSlot].GetTransformedBy(peer pose)
            if ((objectPose2.position - transformedBy.position).magnitude > 0.8f)
                return false;
            if (Dot(transformedBy.forward,
                    (objectPose.position - objectPose2.position).normalized) < 0f)
                return false;
        # ... and symmetrically for the slot-1 peer against objectPose.

    ``objectPose`` is the anchor a sorter draws FROM and ``objectPose2`` the one
    it feeds INTO, which is exactly our ``(x, y, z)`` and ``(x2, y2, z2)``.

    The first two tests overlap ``sorter.own_slots``, deliberately: that check
    states a corpus regularity, this one states the predicate the game applies,
    and they are allowed to arrive at the same place by different routes.

    The game measures on the sphere and we measure on the plane.  Over the 1206
    machine-side records in the fixture corpus the two agree on every record
    outside the latitude-compressed regions, so the difference is not what
    decides any of our builds -- see ``test_game_slot_poses``.
    """
    for i, b in ctx.of_kind(Kind.SORTER):
        anchors = _anchors(b)
        if anchors is None:
            continue
        pose, pose2 = _fpoint(anchors[0]), _fpoint(anchors[1])

        if b.output_obj is not None and b.output_from_slot != rules.OUTPUT_FROM_SLOT:
            yield Finding(
                "game.inserter_data",
                Severity.ERROR,
                f"sorter {i} has something connected at its own slot "
                f"{b.output_from_slot} that is not its output; the game requires "
                f"own slot 0 to be the output",
                (i,),
                {"output_from_slot": b.output_from_slot},
            )
        if b.input_obj is not None and b.input_to_slot != rules.INPUT_TO_SLOT:
            yield Finding(
                "game.inserter_data",
                Severity.ERROR,
                f"sorter {i} has its input at its own slot {b.input_to_slot}; the "
                f"game requires own slot 1 to be the input",
                (i,),
                {"input_to_slot": b.input_to_slot},
            )

        for label, link, slot, end, far in (
            ("output", b.output_obj, b.output_to_slot, pose2, pose),
            ("input", b.input_obj, b.input_from_slot, pose, pose2),
        ):
            if link is None:
                continue
            got = _slot_pose_of(ctx, link, slot)
            if got is None:
                continue
            slot_pos, slot_fwd = got
            gap = rules.world_gap(
                slot_pos[0] - end[0], slot_pos[1] - end[1], slot_pos[2] - end[2]
            )
            if gap > rules.SLOT_REACH:
                yield Finding(
                    "game.inserter_data",
                    Severity.ERROR,
                    f"sorter {i}'s {label} end is {gap:.2f} tiles from slot {slot} "
                    f"of building {link} "
                    f"({cat.building(ctx.placement.buildings[link].item_id).name}), "
                    f"over the game's {rules.SLOT_REACH} limit",
                    (i, link),
                    {"end": label, "slot": slot, "gap": round(gap, 3)},
                )
            if _dot(slot_fwd, _unit(far, end)) < 0.0:
                yield Finding(
                    "game.inserter_data",
                    Severity.ERROR,
                    f"sorter {i} runs into the back of slot {slot} of building "
                    f"{link}: the slot faces the other way",
                    (i, link),
                    {
                        "end": label,
                        "slot": slot,
                        "dot": round(_dot(slot_fwd, _unit(far, end)), 3),
                    },
                )




@check("game.slot_occupancy")
def _slot_occupancy(ctx: Context) -> Iterable[Finding]:
    """One connection per slot -- ``PlanetFactory``'s ``entityConnPool``.

    The game addresses a connection as ``entityConnPool[objId * 16 + slot]``:
    ONE ``int`` per ``(object, slot)``.  Occupancy is keyed on the slot INDEX
    and not on the slot's pose, because the pose never enters the address --
    see :data:`~flab2bp.dsp.rules.CONN_SLOTS_PER_OBJECT`, where the C# is
    quoted.  A second connection written to an occupied slot does not fail: it
    calls ``ClearObjectConn`` on the sitting tenant first and evicts it.

    So a blueprint that names one machine slot from two sorters is not a
    blueprint the game rejects on the pool; it is a blueprint that pastes with
    one of the two sorters silently unwired.  What the player sees is the
    geometry that goes with it -- the paste snaps BOTH ends onto the same slot
    pose, so the sorters land on top of one another and go ``Collide``, and
    every sorter attached to a building in error is reddened after them with
    ``ConnWithErrorBuilding``, "Connection target cannot be laid".  That is the
    pair of messages the paste which produced this check reported.

    Scope is every connection record carrying an EXPLICIT slot, on any peer,
    because the pool does not distinguish: belt-to-belt links occupy a belt's
    input slots 1..3 by the same arithmetic.  Ends recorded as
    :data:`~flab2bp.dsp.rules.BELT_SLOT` are exempt and must be -- ``-1`` means
    "the game picks", and ``WriteObjectConn`` then takes the first free cell in
    :data:`~flab2bp.dsp.rules.BELT_SLOT_AUTO_RANGE`, so such an end names no
    fixed cell to share.

    The negative control is the corpus: over the 10 real game blueprints in
    ``tests/fixtures``, ~10,000 connection records, this check finds nothing on
    either reading of its scope.  Our own ``freeform`` output, by contrast, put
    three sorters on slot 8 of one Assembling Machine and the whole suite
    reported ``ok=True``, because nothing here had ever looked.
    """
    bs = ctx.placement.buildings
    claims: dict[tuple[int, int], list[tuple[int, str]]] = defaultdict(list)
    for i, b in enumerate(bs):
        for label, link, slot in (
            ("output", b.output_obj, b.output_to_slot),
            ("input", b.input_obj, b.input_from_slot),
        ):
            if link is None or not 0 <= link < len(bs):
                continue
            if slot < 0:
                continue
            claims[(link, slot)].append((i, label))

    for (link, slot), occupants in sorted(claims.items()):
        if len(occupants) < 2:
            continue
        peer = bs[link]
        try:
            name = cat.building(peer.item_id).name
        except KeyError:
            name = f"item {peer.item_id}"
        who = ", ".join(f"{i} ({label})" for i, label in occupants)
        yield Finding(
            "game.slot_occupancy",
            Severity.ERROR,
            f"slot {slot} of building {link} ({name}) at ({peer.x}, {peer.y}) is "
            f"named by {len(occupants)} connections: {who}. The game stores one "
            f"connection per slot, so pasting this leaves only the last of them "
            f"attached and drops the rest",
            (link, *(i for i, _ in occupants)),
            {
                "peer": link,
                "slot": slot,
                "peer_item_id": peer.item_id,
                "claims": who,
            },
        )




@check("game.inserter_paste")
def _inserter_paste(ctx: Context) -> Iterable[Finding]:
    """Port of the ``ErrorInserterData`` ladder in ``BlueprintData`` (paste).

    A different predicate from ``game.inserter_data`` and the one that actually
    fires on a paste, which is what our users do with what we emit.  Pasting
    does not merely test a sorter's end -- it SNAPS it onto the slot pose, and
    then runs a three-branch ladder on the correction.  The game's own source
    for that ladder, and the caveat about which of its two quantities is in
    tiles and which in world units, are stated with the constants in
    :mod:`flab2bp.dsp.rules`; this function only applies them.

    ``transformedBy.right`` is reconstructed here as the slot's forward turned a
    quarter turn in the build plane.  Unity's ``right`` is ``Cross(up, forward)``
    and every slot pose is upright to within a degree, so the two agree to
    better than the :data:`~flab2bp.dsp.rules.PASTE_LATERAL_EPS` the ladder
    discriminates on -- and the ladder takes an absolute value, so the sign the
    axis mapping flips does not matter.
    """
    for i, b in ctx.of_kind(Kind.SORTER):
        anchors = _anchors(b)
        if anchors is None:
            continue
        # The input end is snapped and tested first, against the output end as
        # the blueprint still holds it; only then is the output end snapped and
        # tested against the already-snapped input.  That is the game's order,
        # and it is the reason the two ends are not symmetrical here.
        lpos: tuple[float, float, float] = _fpoint(anchors[0])
        lpos2: tuple[float, float, float] = _fpoint(anchors[1])
        for label, link, slot in (
            ("input", b.input_obj, b.input_from_slot),
            ("output", b.output_obj, b.output_to_slot),
        ):
            if link is None:
                continue
            got = _slot_pose_of(ctx, link, slot)
            if got is None:
                continue
            slot_pos, slot_fwd = got
            end = lpos if label == "input" else lpos2
            name = cat.building(ctx.placement.buildings[link].item_id).name

            zero = (slot_pos[0] - end[0], slot_pos[1] - end[1], slot_pos[2] - end[2])
            snap = rules.world_gap(*zero)
            right = (slot_fwd[1], -slot_fwd[0], 0.0)
            lateral = abs(_dot(right, zero)) * colliders.GRID_ARC
            if snap > rules.PASTE_SNAP and (
                lateral > rules.PASTE_LATERAL
                or (lateral < rules.PASTE_LATERAL_EPS and snap > rules.PASTE_RADIAL)
                or (lateral >= rules.PASTE_LATERAL_EPS and snap > rules.PASTE_SNAP)
            ):
                yield Finding(
                    "game.inserter_paste",
                    Severity.ERROR,
                    f"pasting sorter {i} would drag its {label} end {snap:.2f} tiles "
                    f"({lateral:.2f} of it sideways) onto slot {slot} of building "
                    f"{link} ({name}); the game refuses that as a sorter data error",
                    (i, link),
                    {
                        "end": label,
                        "slot": slot,
                        "snap": round(snap, 3),
                        "lateral": round(lateral, 3),
                    },
                )

            if label == "input":
                lpos = slot_pos
            else:
                lpos2 = slot_pos
            far = lpos2 if label == "input" else lpos
            near = lpos if label == "input" else lpos2
            if _dot(slot_fwd, _unit(far, near)) < 0.0:
                yield Finding(
                    "game.inserter_paste",
                    Severity.ERROR,
                    f"after snapping, sorter {i} runs into the back of slot {slot} of "
                    f"building {link} ({name})",
                    (i, link),
                    {"end": label, "slot": slot},
                )




@check("game.inserter_skew")
def _inserter_skew(ctx: Context) -> Iterable[Finding]:
    """Port of the sorter length and skew ladder in ``BuildTool_BlueprintPaste``.

    It runs on the anchors and yaws the BLUEPRINT carries, NOT on the snapped
    ones ``game.inserter_paste`` works with.  That was measured, after a first
    version assumed the opposite and the corpus threw it out: of 923 real
    sorters, the snapped reading rejects 11 -- every one an Oil Refinery in
    ``factory-quick-start-step-3-red-cube``, a blueprint the game ships -- on
    both the length test and the 24-degree one, and adding the belt-end lateral
    shift the paste path also applies fixes the angle and leaves the length.
    Read raw, all 923 pass with room: the tightest length clears its minimum by
    0.511 tiles and the worst end sits 9.9 degrees off its axis against a limit
    of 24.

    That has a consequence worth stating plainly, because an earlier commit
    message here claimed the opposite: **a backwards sorter yaw is NOT rejected
    by this**.  Read raw, ``lrot`` and ``lrot2`` are both the blueprint's own
    yaw, so their angle is zero however the sorter is turned, and the axis test
    takes an absolute value, so a reversal reads as zero too.  The yaw is still
    derived from the geometry in ``assign_sorter_slots`` -- 1250 of 1250 real
    sorters point from the end they draw from to the end they feed, and we were
    writing 69 of 125 backwards -- but that rests on the corpus being unanimous,
    not on any ported predicate refusing it.

    The game's source for the ladder, the thresholds it uses, which of its tests
    are NOT ported and why, and the caveat about what units
    :data:`~flab2bp.dsp.rules.SORTER_LENGTH` is in are all stated with the
    constants in :mod:`flab2bp.dsp.rules`; this function only applies them.

    ``Quaternion.Angle`` between two rotations that share an up axis is the angle
    between their forwards, and both of ours are upright, so the 30-degree test
    is done on forwards here.
    """
    bs = ctx.placement.buildings
    for i, b in ctx.of_kind(Kind.SORTER):
        anchors = _anchors(b)
        if anchors is None:
            continue
        lpos: tuple[float, float, float] = _fpoint(anchors[0])
        lpos2: tuple[float, float, float] = _fpoint(anchors[1])
        yaw2 = b.yaw if b.yaw2 is None else b.yaw2
        fwd = (math.sin(math.radians(b.yaw)), math.cos(math.radians(b.yaw)), 0.0)
        fwd2 = (math.sin(math.radians(yaw2)), math.cos(math.radians(yaw2)), 0.0)

        belts = 0
        for link in (b.input_obj, b.output_obj):
            if link is not None and 0 <= link < len(bs) and cat.is_belt(bs[link].item_id):
                belts += 1

        low, high = rules.SORTER_LENGTH[belts]
        length = math.dist(lpos, lpos2)
        if length > high:
            yield Finding(
                "game.inserter_skew",
                Severity.ERROR,
                f"sorter {i} is {length:.2f} tiles end to end, over the {high} the "
                f"game allows with {belts} belt end(s)",
                (i,),
                {"length": round(length, 3), "max": high, "belt_ends": belts},
            )
        if length < low:
            yield Finding(
                "game.inserter_skew",
                Severity.ERROR,
                f"sorter {i} is only {length:.2f} tiles end to end, under the {low} "
                f"the game allows with {belts} belt end(s)",
                (i,),
                {"length": round(length, 3), "min": low, "belt_ends": belts},
            )
        if length == 0.0:
            continue

        pair = math.degrees(math.acos(max(-1.0, min(1.0, _dot(fwd, fwd2)))))
        if pair > rules.SKEW_PAIR_DEG:
            yield Finding(
                "game.inserter_skew",
                Severity.ERROR,
                f"sorter {i}'s two ends face {pair:.0f} degrees apart, over the "
                f"{rules.SKEW_PAIR_DEG:.0f} the game allows (deflection too much)",
                (i,),
                {"pair_deg": round(pair, 1)},
            )
        axis = _unit(lpos2, lpos)
        for label, f in (("input", fwd), ("output", fwd2)):
            off = math.degrees(math.acos(min(1.0, abs(_dot(axis, f)))))
            if off > rules.SKEW_AXIS_DEG:
                yield Finding(
                    "game.inserter_skew",
                    Severity.ERROR,
                    f"sorter {i}'s {label} end faces {off:.0f} degrees off the line "
                    f"it runs along, over the {rules.SKEW_AXIS_DEG:.0f} the game allows "
                    f"(deflection too much)",
                    (i,),
                    {"end": label, "off_axis_deg": round(off, 1)},
                )




@check("game.addon_supply")
def _addon_supply(ctx: Context) -> Iterable[Finding]:
    """A belt addon is fed by BELT, and the game finds that belt by position.

    Port of the addon-connection pass in ``PlanetFactory``, whose source and
    whose ``sqrMagnitude < 1f`` radius are stated with
    :data:`~flab2bp.dsp.rules.ADDON_AREA_RADIUS`.

    So a Spray Coater carries no connection of its own -- all eight in the
    fixture corpus have ``input_obj`` and ``output_obj`` unset -- and is
    supplied entirely by where the belts are.  Area 0 is the cargo belt it
    rides; area 1 is the proliferator, at ``(0, -1.25, 1)``: a tile and a
    quarter behind and one altitude LEVEL up.

    This is the check that replaced a sorter both strategies used to run into a
    coater.  That sorter could never have worked, and nothing here could see it:
    the coater has no ``slotPoses``, so ``CheckInserterDataLegal`` skips the
    geometry entirely and every one of them passed.

    An addon with only the one area is not checked -- a Traffic Monitor and the
    turrets each carry a single area at the origin, which is the belt they sit
    on, and that co-location is already what places them.
    """
    bs = ctx.placement.buildings
    belts = [(b.x, b.y, float(b.z)) for b in bs if cat.is_belt(b.item_id)]
    for i, b in enumerate(bs):
        areas = cat.building(b.item_id).addon_areas
        if len(areas) < 2:
            continue
        for n, (adx, ady, adz) in enumerate(areas):
            if n == 0:
                continue
            wx, wy = slots.to_world((adx, ady), b.yaw)
            want = (b.x + wx, b.y + wy, float(b.z) + adz)
            if any(
                rules.world_gap(want[0] - p[0], want[1] - p[1], want[2] - p[2])
                < rules.ADDON_AREA_RADIUS
                for p in belts
            ):
                continue
            yield Finding(
                "game.addon_supply",
                Severity.ERROR,
                f"{cat.building(b.item_id).name} {i} has no belt in its addon "
                f"area {n}, at ({want[0]:.2f}, {want[1]:.2f}) one level up; the "
                f"game supplies an addon from there and from nowhere else",
                (i,),
                {"area": n, "x": round(want[0], 2), "y": round(want[1], 2)},
            )


def _addon_rides(
    ctx: Context,
) -> Iterable[
    tuple[int, int | None, tuple[int, int, float] | None, tuple[int, int, float] | None]
]:
    """Every belt addon, the belt on its tile, and that belt's own two neighbours.

    Yields ``(addon_index, ride_index, incoming, outgoing)``.  ``incoming`` is
    the grid step from the ridden belt's INPUT belt to it and ``outgoing`` the
    step from it to its OUTPUT belt, each ``None`` when that end of the run does
    not exist.  ``ride_index`` is ``None`` when no belt sits on the addon's tile
    at all.

    Both directions come from the ``output_obj`` LINK GRAPH and not from any
    stored yaw, because that is what the game reads: ``GetBeltOutputBeltPose``
    and ``GetBeltInputBeltPose`` follow the belt's own connections.  This is the
    one thing about a coater we did not choose, which is what makes the two
    checks below able to convict a yaw we did.
    """
    bs = ctx.placement.buildings
    forward: dict[int, int] = {}
    backward: dict[int, int] = {}
    for i, b in enumerate(bs):
        if not cat.is_belt(b.item_id):
            continue
        j = b.output_obj
        if j is None or not 0 <= j < len(bs) or not cat.is_belt(bs[j].item_id):
            continue
        forward[i] = j
        backward.setdefault(j, i)

    for i, b in enumerate(bs):
        try:
            info = cat.building(b.item_id)
        except KeyError:
            continue
        if not info.is_belt_addon:
            continue
        ride = next(
            (
                k
                for k, o in enumerate(bs)
                if cat.is_belt(o.item_id) and (o.x, o.y, o.z) == (b.x, b.y, b.z)
            ),
            None,
        )
        if ride is None:
            yield i, None, None, None
            continue
        nxt = forward.get(ride)
        prv = backward.get(ride)
        r = bs[ride]
        outgoing = (
            None
            if nxt is None
            else (bs[nxt].x - r.x, bs[nxt].y - r.y, float(bs[nxt].z - r.z))
        )
        incoming = (
            None
            if prv is None
            else (r.x - bs[prv].x, r.y - bs[prv].y, float(r.z - bs[prv].z))
        )
        yield i, ride, incoming, outgoing


@check("game.addon_facing")
def _addon_facing(ctx: Context) -> Iterable[Finding]:
    """A belt addon may not stand ACROSS the belt it rides.

    Port of the ``AddonPass`` excusal in ``BuildTool_BlueprintPaste``, which is
    what keeps a belt running under a Spray Coater from being called a
    collision.  For each of the addon's areas::

        Vector3 vector  = addon.lpos + addon.lrot * (colPose.position
                                                     + colPose.forward * size.z * 3f);
        Vector3 vector2 = addon.lpos + addon.lrot * (colPose.position
                                                     - colPose.forward * size.z * 3f);
        float num2 = Maths.DistancePointLine(belt.lpos, vector, vector2);
        float num3 = 1f;
        if (flag) num3 = Mathf.Abs(Vector3.Dot((vector2 - vector).normalized, rhs));
        flag3 |= num2 < 0.3f;
        flag3 &= num3 > 0.95f;          # <- the direction test
        flag2 |= flag3;

    ``rhs`` is the belt's own direction of travel, taken from its preview links
    and not from any stored yaw::

        if (input == null && output != null) rhs = (output.lpos - lpos).normalized;
        if (input != null && output == null) rhs = (lpos - input.lpos).normalized;

    and the line it is dotted against runs along the addon's area, which the
    addon's ``lrot`` -- its YAW -- aims.  When ``AddonPass`` returns false the
    belt is not excused, ``flag6`` is set and the belt becomes
    ``EBuildCondition.Collide``; the later re-probe at 147451 does not rescue
    it, because that clause refuses to excuse a belt that is CLOSE to an addon
    area, which the ridden belt is by definition.

    ``Mathf.Abs`` is why this convicts a right angle and not a reversal.  A
    coater yawed 180 from its belt dots to -1, passes, and pastes.  A coater
    yawed 90 dots to 0 and turns the belt under it red -- "Collide with other
    object".

    WHY ``game.addon_supply`` CANNOT CATCH THIS, which is the part worth
    keeping.  That check computes the addon area's cell FROM the addon's own yaw
    and then asks whether a belt is there -- and the strategy that chose the yaw
    put the belt at that same computed cell.  It validates our choice against
    itself, so a wrong yaw is invisible to it by construction.  This check is
    anchored to something we did not choose: the direction of flow through the
    ridden belt, read from the ``output_obj`` LINK GRAPH.

    MEASURED.  The game's own eight Spray Coaters -- five in
    ``factory-heretical-smelter-block``, three in
    ``tillable-blackbox-module-...`` -- carry the flow yaw EXACTLY, 8 of 8, over
    two different run directions.  ``spine`` matches them, 16 of 16.
    ``freeform`` does not: of the twenty coaters on the reported blueprint's
    ``max-proliferation`` candidate, ten disagree -- six standing across a belt
    that flows north and four reversed on a belt that flows west -- because it
    writes one yaw for every coater regardless of the lane it lands on.  Only
    the six are convicted here; the four reversals are recorded in the finding
    count of neither, because the game accepts them and a check that refused
    them would be ours rather than the game's.

    WHAT THIS CHECK CANNOT SEE, and ``game.addon_corner`` below can.  Reading
    the successor "or its predecessor when it has none" reads exactly ONE end of
    the ridden belt.  A belt that arrives from the north and leaves to the east
    agrees with a coater yawed 90 at the end this reads, so this check passes
    it.  Six of ``freeform``'s twenty coaters on a later blueprint the user
    pasted were in that state and this check reported nothing about any of them
    -- measured, 0 findings here against 6 there on the same file.
    """
    bs = ctx.placement.buildings
    for i, ride, incoming, outgoing in _addon_rides(ctx):
        b = bs[i]
        info = cat.building(b.item_id)
        if ride is None:
            yield Finding(
                "game.addon_facing",
                Severity.ERROR,
                f"{info.name} {i} at ({b.x}, {b.y}) rides no belt: there is no belt "
                f"on its own tile, and an addon's area 0 IS the belt it sits on",
                (i,),
                {"x": b.x, "y": b.y},
            )
            continue
        step = outgoing if outgoing is not None else incoming
        if step is None:
            # Neither successor nor predecessor: a one-tile run has no
            # direction of travel, so `rhs` is `Vector3.forward` and the
            # game's own `flag` is false -- `num3` stays 1 and the test
            # cannot fire.  Silence here is the game's answer, not ours.
            continue
        dx, dy = step[0], step[1]
        if (dx, dy) == (0, 0):
            continue
        flow = round(math.degrees(math.atan2(dx, dy))) % 360
        # The addon's areas are aimed by its yaw, so the line the game dots
        # against runs along the addon's own axis.  Both are quarter turns on
        # our grid, so the dot is 1, 0 or -1 and `> 0.95` reduces to "parallel".
        off = (round(b.yaw) - flow) % 360
        if off in (0, 180):
            continue
        yield Finding(
            "game.addon_facing",
            Severity.ERROR,
            f"{info.name} {i} at ({b.x}, {b.y}) is yawed {round(b.yaw) % 360} and "
            f"stands across the belt it rides, which flows {flow}. The game aims "
            f"an addon's areas with its yaw and refuses a belt that crosses one "
            f"at a right angle, so that belt pastes as a collision",
            (i, ride),
            {"yaw": round(b.yaw) % 360, "flow": flow, "off_by": off},
        )


@check("game.addon_corner")
def _addon_corner(ctx: Context) -> Iterable[Finding]:
    """A belt addon may not sit on a belt that TURNS on its tile.

    ``game.addon_facing`` above reads ONE end of the ridden belt -- its
    successor, or its predecessor when it has none.  A belt that arrives from
    the north and leaves to the east agrees with a coater yawed 90 at the end
    that check looks at, and disagrees at the end it does not.  This is the
    other end.

    The rule, at decompiled 145812 -- the addon half of the paste ladder, where
    a pasted addon meets a belt that is already on the planet or already a
    prebuild::

        float num23 = Maths.DistancePointLine(objectPose2.position, lineStart2, lineEnd2);
        flag10 &= num23 < 0.3f;
        if (flag10 && (objectPose2.position - buildPreview2.lpos).magnitude < 2.5f) {
            if (hasOutput) { num23 = DistancePointLine(beltOutputBeltPose.position, ...);
                             flag10 &= num23 < 0.3f; }
            if (hasInput)  { num23 = DistancePointLine(beltInputBeltPose.position, ...);
                             flag10 &= num23 < 0.3f; }
        }
        flag9 |= flag10;
        if (flag9) continue;                 # <- the excusal, not taken

    and when the excusal is not taken the addon falls through to
    ``buildPreview2.condition = EBuildCondition.Collide``.  Both the belt's own
    INPUT belt and its OUTPUT belt must lie on the addon's line, not just the
    belt itself.  A corner puts one of them a tile off it.

    The hand tool states the same rule as an ANGLE rather than a distance, over
    the same two neighbours (``BuildTool_Addon.CheckBuildConditions``), and that
    is the form :func:`flab2bp.dsp.rules.addon_ride_is_straight` ports, because
    our grid is cardinal and an angle carries the altitude clause with it.
    Placing a Spray Coater by hand on a belt that turns under it is refused.

    SCOPE, stated plainly because it bounds what a finding here proves.  The
    paste path has THREE addon-versus-belt clauses and only two carry this
    rule:

    * 145812, quoted above -- addon preview against an EXISTING belt or
      prebuild.  Corner refused.
    * ``BuildTool_Addon`` -- hand placement.  Corner refused.
    * ``AddonPass`` (BuildTool_BlueprintPaste, and its twin at 147454) -- an
      addon and a belt from the SAME paste.  **No corner clause at all**, and
      its one direction test is dead for a mid-run belt: ``flag`` is set only
      when exactly one of ``input``/``output`` is null, so a belt with both
      leaves ``num3`` at ``1f``.

    So a finding here is NOT proof that a first paste onto bare ground is
    rejected.  It is proof that the geometry is one the game refuses in the two
    places it looks at both ends -- including a re-paste over the prebuilds the
    first paste left.

    MEASURED, and it is why the assumption this closes was wrong.  The game's
    own eight Spray Coaters -- five in ``factory-heretical-smelter-block``,
    three in ``tillable-blackbox-module-...`` -- ride a straight belt 8 of 8,
    zero corners.  ``freeform``'s twenty coaters on the reported
    ``max-proliferation`` blueprint were 14 straight and **6 turning**, every
    one of them entering from ``(0, 1)`` and leaving to ``(1, 0)`` under a yaw
    of 90.  ``game.addon_facing`` passed all six: it read the outgoing step,
    which agrees with the yaw, and nothing looked at where the cargo came from.
    """
    bs = ctx.placement.buildings
    for i, ride, incoming, outgoing in _addon_rides(ctx):
        if ride is None or incoming is None or outgoing is None:
            # One end alone is `game.addon_facing`'s question.  The game tests
            # only the neighbours that exist, so an end-of-run belt has nothing
            # for this clause to disagree about.
            continue
        b = bs[i]
        info = cat.building(b.item_id)
        if rules.addon_ride_is_straight(float(b.yaw), incoming, outgoing):
            continue
        yield Finding(
            "game.addon_corner",
            Severity.ERROR,
            f"{info.name} {i} at ({b.x}, {b.y}) is yawed {round(b.yaw) % 360} and "
            f"rides a belt that arrives {incoming[:2]} and leaves {outgoing[:2]}: "
            f"the game requires the ridden belt's own input AND output to lie "
            f"along the addon's axis, so a belt that turns on the addon's tile "
            f"pastes as a collision",
            (i, ride),
            {
                "yaw": round(b.yaw) % 360,
                "incoming": list(incoming),
                "outgoing": list(outgoing),
            },
        )


@check("game.belt_crossing")
def _belt_crossing(ctx: Context) -> Iterable[Finding]:
    """A belt over a building must clear its build collider -- and it may.

    The rule this repository spent a long time NOT guessing.  A belt preview is
    not tested with its box.  ``BuildTool_BlueprintPaste.CheckBuildConditions``
    branches on ``isBelt`` inside the same query loop (decompiled 145761)::

        int num17 = ((!buildPreview2.desc.isBelt)
            ? Physics.OverlapBoxNonAlloc(colliderData.pos, colliderData.ext, ...)
            : Physics.OverlapSphereNonAlloc(buildPreview2.lpos
                  + buildPreview2.lpos.normalized * 0.2f, 0.23f, ...));

    and the excusal at 145872 is asymmetric::

        || (!buildPreview2.desc.isBelt && component.buildPreview.desc.isBelt)

    -- a machine is excused against a belt, a belt is NOT excused against a
    machine.  So the answer to "may a belt cross a building" is YES, and the
    price is height: the probe reaches ``0.23 - 0.2 = 0.03`` below the belt
    node, so a belt clears a collider whose top stands ``t`` above the ground
    when ``z > (t + 0.03) * 3/4``.  That is z > 3.53 -- four half-levels -- over
    an Assembling Machine, 2.80 over an Arc Smelter, 1.75 over a Splitter and
    0.76 over a Sorter.  :func:`flab2bp.dsp.colliders.belt_crossing_height`
    computes it per model.

    A Splitter is NOT a belt for this purpose.  ``PrefabDesc.ReadPrefab`` line
    217564 sets ``isBelt = beltSpeed > 0`` from a ``BeltDesc``; a splitter takes
    the ``SplitterDesc`` branch and sets ``isSplitter``.  An elevated splitter
    over a machine is an ordinary box-against-box question, and ``geom.collide``
    is where it is asked.

    THE LATERAL HALF IS NOT ASKED HERE.  It exists now -- the excusal that made
    it tractable was found, and ``game.belt_collide`` below is the same rule
    without this narrowing -- but that check is in :data:`OPT_IN` and this one is
    not, so this one keeps the narrowing it always had: only belts whose probe
    centre stands INSIDE a collider's footprint, and only above it.

    What HAS changed is that the excusals now apply here too, which can only
    make this weaker and more correct: a belt over the building its own run
    reaches is no longer convicted for reaching it.

    Scope, and where it is still a LOWER bound.

    * Sorters and belt addons are left out entirely because the game excuses
      them (145871 and ``AddonPass`` at 145885/147454); belt on belt is
      ``geom.belt_single_occupancy``'s question, not this one.
    * ``catalog.LOW_CONFIDENCE_FOOTPRINTS`` is left out, for the reason already
      recorded there.
    * ``multiLevel`` buildings are left out HERE, because a belt one level above
      a Splitter or Storage Tank is on its raised port rather than crossing it
      and this check cannot tell the two apart.  ``game.belt_collide`` can: the
      connection is what excuses it there, so it needs no such guess.

    Negative control: zero findings on ``catalog.GEOMETRY_SAFE_FIXTURES`` and on
    the derived ``test_local_offset.GEOMETRY_CORPUS``.  Not vacuous -- 133 belts
    in the single-area fixtures pass over or under a collider and clear it, and
    the positive controls in ``tests/layout/test_validate.py`` still fire.
    """
    yield from _belt_collide_findings(ctx, "game.belt_crossing", crossings_only=True)
    yield from _addon_crossings(ctx)


def _addon_crossings(ctx: Context) -> Iterable[Finding]:
    """A belt passing OVER a belt addon owes it the same clearance as anything else.

    This half is separate because the addon is excused twice over on the way
    here, and both excusals are right about the case they were written for and
    wrong about this one.

    * ``colliders.belt_collisions`` never reports a belt against a belt addon at
      all, on the ``AddonPass`` reading -- and ``AddonPass`` is about a belt the
      addon is ATTACHED to.  The belt it rides and the belt on its proliferator
      area are what that clause exists to excuse.
    * ``_stacks`` takes a Spray Coater out of the crossing question because
      ``PrefabDesc.multiLevel`` is set for it, and for a Splitter or a Storage
      Tank a belt one level up really is on a raised port.  A coater's raised
      port is not overhead: area 1 sits at ``(0, -1.25, 1)``, a tile and a
      quarter BEHIND it.  Directly over the coater there is no port, only 1.8975
      of collider.

    CONFIRMED IN GAME, by paste, which is why this is here rather than in the
    backlog.  The failing blueprint was cut down to one coater, its tower and
    every belt within six tiles -- no machines, no sorters -- and the game
    flagged the BELT directly over the coater.  Our proliferator chain crosses
    at ``z = 1`` and ``colliders.belt_crossing_height`` for the coater's model is
    ``1.8975``, so it owes ``z = 2``.

    MEASURED.  Over the eight coaters in the game's own blueprints there is not
    one belt above a coater and under its clearance: the belts inside a coater's
    footprint are either on the addon's own area cells or on the SAME level
    beside it, which the ``z`` test lets through.  Our own output has six such
    belts in ``freeform`` and eight in ``spine`` -- six at one level, two at one
    and a half.

    The two excusals kept: a belt at or below the addon's own level (it rides
    one, and the game's blueprints are full of belts flanking a coater at
    ground level), and a belt standing on one of the addon's area cells, which
    is a connection and is what ``game.addon_supply`` requires to be there.
    """
    bs = ctx.placement.buildings
    addons = [i for i, b in enumerate(bs) if ctx.kinds[i] is Kind.ADDON]
    if not addons:
        return
    belts = [i for i, b in enumerate(bs) if cat.is_belt(b.item_id)]
    if not belts:
        return
    for ai in addons:
        ab = bs[ai]
        try:
            info = cat.building(ab.item_id)
        except KeyError:
            continue
        # THREE-DIMENSIONAL, and it has to be.  Area 0 of a coater is
        # ``(0, 0, 0)`` -- its own tile -- so a two-dimensional exemption
        # excuses a belt flying over the coater at z + 1, which is precisely
        # the belt the game flagged.  The attached belt is the one at the
        # area's own altitude.
        areas = {
            (
                ab.x + round(slots.to_world((adx, ady), ab.yaw)[0]),
                ab.y + round(slots.to_world((adx, ady), ab.yaw)[1]),
                float(ab.z) + adz,
            )
            for adx, ady, adz in info.addon_areas
        }
        need = dsp_colliders.belt_crossing_height(ab.model_index) + float(ab.z)
        pose = dsp_colliders.Placed(
            ab.model_index,
            *codec.tile_to_local_offset(ab.x, ab.y, ab.z, ab.width, ab.height),
            ab.yaw,
        )
        for bi in belts:
            b = bs[bi]
            if b.z <= ab.z:
                continue
            if any(
                (b.x, b.y) == (ax, ay) and abs(float(b.z) - az) < 0.5
                for ax, ay, az in areas
            ):
                continue
            probe = dsp_colliders.Placed(
                b.model_index,
                *codec.tile_to_local_offset(b.x, b.y, b.z, b.width, b.height),
                b.yaw,
            )
            if not dsp_colliders.belt_crossings(
                [probe], [pose], directly_over_only=True
            ):
                continue
            yield Finding(
                "game.belt_crossing",
                Severity.ERROR,
                f"belt at ({b.x}, {b.y}) z={b.z} passes over {info.name} "
                f"{ai} at ({ab.x}, {ab.y}) z={ab.z} without clearing its build "
                f"collider; the game needs z > {need:.4f}",
                (bi, ai),
                {
                    "belt_z": str(b.z),
                    "needs_z_above": f"{need:.4f}",
                    "under": str((ab.x, ab.y, str(ab.z))),
                },
            )


@check("game.belt_collide")
def _belt_collide(ctx: Context) -> Iterable[Finding]:
    """The same rule with the LATERAL half on: a belt beside a building, too.

    ``game.belt_crossing`` above is this check narrowed to belts standing over a
    collider's footprint.  The narrowing was never part of the game's rule; it
    was there because the excusal that makes the lateral half tractable had not
    been found.  It has, and it is the pass at 147257 --
    :func:`flab2bp.dsp.colliders.belt_collisions` holds it with the C#.

    WHY THIS IS IN :data:`OPT_IN` AND ``game.belt_crossing`` IS NOT, with the
    measurement OPT_IN asks for.  On the fixture corpus it is clean: zero
    findings on every single-area fixture, against 1189 for the same geometry
    with nothing excused.  On OUR OWN output it is not, and the reason is the
    defect the backlog entry this came from exists to fix.  A Splitter's
    ``catalog.footprint`` is 1x1; its build collider is a 2.38-unit cross, which
    needs two tiles.  So both strategies route belts one tile from a Splitter --
    at ground level and, on ramps, one level up, where the probe still catches
    the 1.19-unit arm by 0.16 of its 0.23 radius.  Turning this on turns 15
    ``spine`` tests red -- ``magnetic-ring``, ``quantum-chip/no-proliferator``
    and ``free-proliferation`` -- because the strategy's own self-check then
    refuses every plan it emits.  That is a ROUTER bug, not a rule bug: the belt
    needs
    ``z > 1.7475`` or one more tile of clearance, and neither is this check's to
    arrange.  Fix the footprints (steps 1 and 2 of the entry) and this comes on
    by name first, then by default.
    """
    yield from _belt_collide_findings(ctx, "game.belt_collide", crossings_only=False)


def _belt_collide_findings(
    ctx: Context, cid: str, *, crossings_only: bool
) -> Iterable[Finding]:
    """The paste's belt verdict, optionally narrowed to the crossing question."""
    bs = ctx.placement.buildings
    previews = _paste_previews(ctx)
    if not any(p.is_belt for p in previews):
        return
    for ia, ic in dsp_colliders.belt_collisions(previews):
        if bs[ic].item_id in cat.LOW_CONFIDENCE_FOOTPRINTS:
            continue
        over = _probe_inside(previews[ia], previews[ic]) and bs[ia].z > bs[ic].z
        if crossings_only and (not over or _stacks(bs[ic].item_id)):
            continue
        need = dsp_colliders.belt_crossing_height(bs[ic].model_index) + float(bs[ic].z)
        how = "passes over" if over else "grazes"
        yield Finding(
            cid,
            Severity.ERROR,
            f"belt at ({bs[ia].x}, {bs[ia].y}) z={bs[ia].z} {how} "
            f"{cat.building(bs[ic].item_id).name} at ({bs[ic].x}, {bs[ic].y}) "
            f"without clearing its build collider; the game needs z > {need:.4f}",
            (ia, ic),
            {
                "belt_z": str(bs[ia].z),
                "needs_z_above": f"{need:.4f}",
                "under": str((bs[ic].x, bs[ic].y, str(bs[ic].z))),
            },
        )


def _stacks(item_id: int) -> bool:
    """``PrefabDesc.multiLevel`` -- may another building stand on this one.

    Only ``game.belt_crossing`` asks: the game lets a building stand ON a
    Splitter, Depot, Storage Tank, Matrix Lab or Spray Coater, and their belt
    ports rise with the stack, so a belt a level above one is a connection
    rather than a crossing.  ``game.belt_collide`` does not need the guess --
    the connection is what excuses it there.
    """
    try:
        return bool(cat.building(item_id).multi_level)
    except KeyError:
        return False


def _paste_previews(ctx: Context) -> tuple[dsp_colliders.Preview, ...]:
    """This placement as the paste sees it: world poses plus the preview graph.

    Index-preserving, because a ``Finding`` names building indices and because
    the excusal at 147451 is expressed in preview links, which are indices too.
    """
    return tuple(
        dsp_colliders.Preview(
            b.model_index,
            *codec.tile_to_local_offset(b.x, b.y, b.z, b.width, b.height),
            b.yaw,
            is_belt=ctx.kinds[i] is Kind.BELT,
            is_inserter=ctx.kinds[i] is Kind.SORTER,
            is_splitter=ctx.kinds[i] is Kind.SPLITTER,
            is_belt_addon=ctx.kinds[i] is Kind.ADDON,
            output=b.output_obj,
            input=b.input_obj,
        )
        for i, b in enumerate(ctx.placement.buildings)
    )


def _probe_inside(belt: dsp_colliders.Preview, other: dsp_colliders.Preview) -> bool:
    """Whether the belt's probe centre is inside ``other``'s collider footprint.

    Only decides the wording of a finding: "passes over" reads wrong for a belt
    that grazes a collider from beside it.
    """
    probe = dsp_colliders.belt_probe(belt.x, belt.y, belt.z)
    pose = dsp_colliders.flat_pose(other.x, other.y, other.z, other.yaw)
    return any(
        dsp_colliders.probe_inside_footprint(probe, box)
        for box in dsp_colliders.target_boxes(other, *pose)
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
        if len(attached) <= rules.SPLITTER_MAX_PORTS:
            continue
        yield Finding(
            "junction.ports",
            Severity.ERROR,
            f"splitter {j} at ({b.x},{b.y}) has {len(attached)} belts attached but a "
            f"splitter has {rules.SPLITTER_MAX_PORTS} sides; it would paste as a junction "
            f"silently dropping {len(attached) - rules.SPLITTER_MAX_PORTS} connection(s)",
            (j, *attached),
            {"junction": j, "attached": len(attached), "max": rules.SPLITTER_MAX_PORTS},
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
    cached = ctx.cache.tower_centres
    if cached is not None:
        return cached
    out: list[tuple[int, Fraction, Fraction, Fraction, Fraction]] = []
    # Selected on the catalog fact rather than on `Kind`, because a mode-driven
    # machine is a power node AND a machine and `Kind` can only say one.  Still
    # walked in placement order, because `power.connectivity` roots its BFS at
    # the first tower and reports the complement of THAT tower's component --
    # reordering this list would change which towers a finding names.  POWER and
    # MACHINE are the only kinds that can qualify: `_kind` decides BELT, SORTER
    # and SPLITTER before it ever reads the radius, ADDON and OTHER only after
    # the radius came back zero or absent.
    for i, b in enumerate(ctx.placement.buildings):
        if ctx.kinds[i] not in (Kind.POWER, Kind.MACHINE) or not _supplies_power(b):
            continue
        info = cat.building(b.item_id)
        cx = Fraction(2 * b.x + b.width, 2)
        cy = Fraction(2 * b.y + b.height, 2)
        out.append((i, cx, cy, info.cover_radius, info.connect_distance))
    ctx.cache.tower_centres = out
    return out


@check("power.coverage")
def _coverage(ctx: Context) -> Iterable[Finding]:
    towers = _tower_centres(ctx)
    # Exact, in DOUBLED integer coordinates.  A tile centre sits at (2tx+1)/2
    # and a tower centre at (2x+w)/2, so doubling clears the only halves in the
    # comparison and the squared distance becomes an integer.  An integer `d2`
    # satisfies `d2 <= (2r)**2` exactly when `d2 <= floor((2r)**2)`, so the
    # floor is not a tolerance -- it is the same predicate, decided without
    # allocating four Fractions and two Fraction powers per tower per tile.
    # Measured on universe-matrix (1330 powered buildings, 7054 tiles, 141
    # towers): 2.37s of an 8.13s certify, down to 0.06s.
    discs = [(int(2 * ox), int(2 * oy), int((2 * r) ** 2)) for _, ox, oy, r, _ in towers]
    # Altitude is not in the predicate, so a stack of belts over one ground
    # cell is one question, not three.
    covered: dict[tuple[int, int], bool] = {}
    for i, b in enumerate(ctx.placement.buildings):
        if ctx.kinds[i] not in _POWERED:
            continue
        for tx, ty, _tz in b.tiles():
            here = covered.get((tx, ty))
            if here is None:
                dx, dy = 2 * tx + 1, 2 * ty + 1
                here = any(
                    (dx - ox) * (dx - ox) + (dy - oy) * (dy - oy) <= lim
                    for ox, oy, lim in discs
                )
                covered[(tx, ty)] = here
            if not here:
                yield Finding(
                    "power.coverage",
                    Severity.ERROR,
                    f"building {i} has tile ({tx},{ty}) outside every tower's supply "
                    f"radius; it would sit unpowered",
                    (i,),
                    {"tile": f"({tx},{ty})", "towers": len(towers)},
                )
                break


def _power_nodes(ctx: Context) -> list[tuple[int, PlacedBuilding, rules.PowerNode]]:
    """Every ``PrefabDesc.isPowerNode`` in the placement, in placement order.

    NOT :func:`_supplies_power`, which asks ``cover_radius > 0`` and is the
    right question for ``power.coverage``.  Three of the catalog's thirteen
    power nodes -- Solar Panel, Accumulator, Geothermal Power Station -- cover
    nothing and are still nodes, still join the network, and are still subject
    to ``EBuildCondition.PowerTooClose``.
    """
    out: list[tuple[int, PlacedBuilding, rules.PowerNode]] = []
    for i, b in enumerate(ctx.placement.buildings):
        try:
            info = cat.building(b.item_id)
        except KeyError:
            continue
        if not info.is_power_node:
            continue
        out.append(
            (
                i,
                b,
                rules.PowerNode(
                    is_power_node=True,
                    is_accumulator=info.is_accumulator,
                    wind_forced_power=info.wind_forced_power,
                    geothermal=info.geothermal,
                ),
            )
        )
    return out


@check("game.power_too_close")
def _power_too_close(ctx: Context) -> Iterable[Finding]:
    """Two power nodes closer than the game's spacing rule allows.

    ``EBuildCondition.PowerTooClose`` and its wind and geothermal tiers, ported
    in :func:`flab2bp.dsp.rules.power_node_condition` with the C# quoted.  This
    is not a collision and ``geom.collide`` cannot stand in for it: a Tesla
    Tower has NO build collider -- ``colliders.build_colliders(2201)`` is empty
    -- so two of them may sit on the same tile without any box intersecting.

    WHY THIS IS AN ERROR AND NOT OPT-IN.  It was found by shipping: the user
    pasted ``tests/fixtures/ours/power-too-close-freeform.txt`` into the game
    and every sorter, belt and machine built, while two of its six Tesla Towers
    were refused at 1.777 world units apart.  The other four sit 11.24 units
    and further from everything and built.  So the bound is bracketed by
    observation as well as by citation, and the citation puts it at 3.5.

    The control is the corpus.  Over the seven single-area blueprints in
    ``tests/fixtures`` -- 75 power nodes and 1468 pairs, in blueprints the GAME
    wrote -- this convicts **zero**, and the sample is not vacuous in kind: it
    carries 54 Tesla Towers in one blueprint and pairs as close as 6.00 tiles
    against a bound of 2.785.  Multi-area fixtures are excluded for the reason
    ``tests/dsp/test_colliders.py`` excludes them from every geometric test: a
    building's local offset is relative to its own area, and the flat frame puts
    two areas' buildings tens of tiles from where they belong.

    ORDERED pairs, not unordered, because the rule is not symmetric -- twice
    over.  The guard at ``:2527`` exempts an ACCUMULATOR being placed while the
    loop it guards asks only ``isPowerNode`` of the building it looks at, so an
    Accumulator may stand on top of another Accumulator and a Tesla Tower may
    not stand on top of either.  And the loop scans only protos in
    :data:`~flab2bp.dsp.rules.PASTE_POWER_NODE_IDS`, which the Signal Tower is a
    power node OUTSIDE of.  Both asymmetries land on the same case: the game
    reaches its verdict when it evaluates the OTHER preview, so testing one
    direction would report the pair clean.
    """
    nodes = _power_nodes(ctx)
    if len(nodes) < 2:
        return
    lo, hi = rules.PASTE_POWER_NODE_IDS
    poses = [
        colliders.flat_pose(*codec.tile_to_local_offset(b.x, b.y, b.z, b.width, b.height), b.yaw)[
            0
        ]
        for _i, b, _n in nodes
    ]
    for a in range(len(nodes)):
        ia, ba, na = nodes[a]
        for c in range(a + 1, len(nodes)):
            ic, bc, nc = nodes[c]
            d2 = sum((p - q) ** 2 for p, q in zip(poses[a], poses[c], strict=True))
            cond = None
            if lo <= bc.item_id < hi:
                cond = rules.power_node_condition(na, nc, d2)
            if cond is None and lo <= ba.item_id < hi:
                cond = rules.power_node_condition(nc, na, d2)
            if cond is None:
                continue
            yield Finding(
                "game.power_too_close",
                Severity.ERROR,
                f"{cat.building(ba.item_id).name} at ({ba.x},{ba.y}) and "
                f"{cat.building(bc.item_id).name} at ({bc.x},{bc.y}) are "
                f"{math.sqrt(d2):.3f} world units apart; the game refuses the paste "
                f"with EBuildCondition.{cond}",
                (ia, ic),
                {
                    "a": str((ba.x, ba.y, str(ba.z))),
                    "b": str((bc.x, bc.y, str(bc.z))),
                    "gap": f"{math.sqrt(d2):.4f}",
                    "condition": str(cond),
                },
            )


@check("power.connectivity")
def _connectivity(ctx: Context) -> Iterable[Finding]:
    towers = _tower_centres(ctx)
    if len(towers) < 2:
        return
    n = len(towers)
    adj: dict[int, list[int]] = {k: [] for k in range(n)}
    # Doubled integer coordinates, exactly as in `power.coverage`: the squared
    # separation is an integer, so `d2 <= (2*reach)**2` is `d2 <=
    # floor((2*reach)**2)`, and floor commutes with max -- max picks one of the
    # two operands and floor is monotone -- so the per-pair reach can be taken
    # over the already-floored squares.  This is n^2 in the tower count and it
    # was 6.6% of certify at 141 towers.
    pts = [(int(2 * ax), int(2 * ay), int((2 * link) ** 2)) for _, ax, ay, _, link in towers]
    for a in range(n):
        ax, ay, asq = pts[a]
        for b in range(a + 1, n):
            bx, by, bsq = pts[b]
            # max, not min: OnNodeAdded links when the separation is within
            # max(a.connDistance2, b.connDistance2), so a long-reach node pulls
            # a short-reach one into its network -- a Wireless Power Tower
            # (45.5) links to a Tesla Tower at up to 45.5, not 22.5.  See
            # catalog.TESLA_LINK_DISTANCE, read off Assembly-CSharp.dll.
            if (ax - bx) ** 2 + (ay - by) ** 2 <= (asq if asq > bsq else bsq):
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
    """Every machine is configured -- by a recipe id, or by a mode block.

    Exactly one of the two, never half of each: that is ``_machine_config``'s
    contract, and this is where a placement is held to it.  A mode-driven
    building carries ``recipe_id == 0`` legitimately -- an Energy Exchanger's
    charge/discharge and a Ray Receiver's photon mode live in the parameter
    block -- so demanding a recipe id of one would be a false error.  Demanding
    NOTHING of one would be worse: an exchanger with neither pastes cleanly and
    sits idle, which is the very failure this check is named for.
    """
    for i, b in ctx.of_kind(Kind.MACHINE):
        if b.item_id in MODE_DRIVEN_ITEM_IDS:
            if not b.parameters:
                yield Finding(
                    "machine.recipe_valid",
                    Severity.ERROR,
                    f"machine {i} is mode-driven but carries no parameter block, so "
                    f"no mode is selected; it would sit idle",
                    (i,),
                    {"item_id": b.item_id},
                )
            continue
        if b.recipe_id == 0:
            yield Finding(
                "machine.recipe_valid",
                Severity.ERROR,
                f"machine {i} has no recipe set; it would sit idle",
                (i,),
                {"item_id": b.item_id},
            )


@check("machine.group_resolved", needs_spec=True)
def _group_resolved(ctx: Context) -> Iterable[Finding]:
    """Every placed machine matches a group in the spec it is supposed to realise.

    This exists because the alternative is silence.  Ten checks -- three of
    them ERROR checks -- answer their question by first asking what a machine is
    supposed to be doing, and each of them opened with ``if g is None:
    continue``.  A machine nothing could resolve was therefore not judged
    leniently; it was not judged, while every one of those checks reported as
    having run.  Measured on the code before this: a placement of two Energy
    Exchangers and NOT ONE SORTER anywhere validated clean.

    So the inability is reported once, here, as the ERROR it is -- one finding
    per machine rather than nine, and a build that cannot be validated fails
    rather than passing by default.  :data:`NEEDS_GROUPS` carries the other half
    of the invariant: those ten checks leave ``checks_run`` while this is
    outstanding.

    It cannot fire on a machine whose recipe is in the spec, because the IdMap
    is built from the spec's own groups -- so a finding here means one of two
    real things: a placement holding a machine the spec never asked for, or a
    mode-driven machine whose building-and-mode pair does not single out a
    group.
    """
    assert ctx.spec is not None
    bs = ctx.placement.buildings
    for i in ctx.unresolved_machines():
        b = bs[i]
        yield Finding(
            "machine.group_resolved",
            Severity.ERROR,
            f"machine {i} (item {b.item_id}, recipe id {b.recipe_id}, parameters "
            f"{b.parameters!r}) matches no group in the spec, so nothing can say "
            f"what it is meant to make; {len(NEEDS_GROUPS)} checks including "
            f"machine.inputs_supplied and machine.output_removed cannot judge it",
            (i,),
            {"item_id": b.item_id, "recipe_id": b.recipe_id},
        )


@check("machine.inputs_supplied", needs_spec=True, needs_groups=True)
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
    cached = ctx.cache.run_components
    if cached is not None:
        return cached
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
    ctx.cache.run_components = component
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


@check("flow.lane_sourced", needs_spec=True, needs_groups=True)
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
    cached = ctx.cache.entry_runs
    if cached is not None:
        return cached
    external = set(ctx.spec.external_inputs)
    internal = _close_over_junctions(ctx, _internal_seeds(ctx)[1])
    out: dict[str, list[int]] = defaultdict(list)
    for r, run in enumerate(ctx.runs):
        if r in internal:
            continue
        item = _external_item(ctx, run, external)
        if item is not None:
            out[item].append(r)
    ctx.cache.entry_runs = dict(out)
    return ctx.cache.entry_runs


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
    cached = ctx.cache.entry_items
    if cached is not None:
        return cached
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
    ctx.cache.entry_items = out
    return out


def _reachable_from_outside(ctx: Context, level: Fraction) -> set[tuple[int, int]]:
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
    free: dict[Fraction, set[tuple[int, int]]] = {}
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


@check("machine.output_removed", needs_spec=True, needs_groups=True)
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


@check("spec.machine_counts", needs_spec=True, needs_groups=True)
def _machine_counts(ctx: Context) -> Iterable[Finding]:
    """The placement holds the machines the spec asked for, and no others.

    Counted by RESOLVED group rather than by the raw ``(recipe_id, item_id)``
    pair the buildings carry.  The raw pair cannot count a mode-driven machine
    at all: its recipe id is zero by design and the spec side has no numeric id
    to compare against, so the group fell out as an unverifiable WARNING while
    the placement side counted the exchangers under recipe 0 -- "spec demands 0,
    placement has 2" for a spec that demands exactly 2.
    """
    assert ctx.spec is not None and ctx.ids is not None
    want: dict[tuple[str, int], int] = {}
    for g in ctx.spec.groups:
        mid = ctx.ids.items.get(g.machine_item_id)
        if mid is None:
            yield Finding(
                "spec.machine_counts",
                Severity.WARNING,
                f"no id mapping for machine {g.machine_item_id!r}; cannot verify "
                f"the count of {g.recipe_id!r}",
                (),
                {"recipe": g.recipe_id, "machine": g.machine_item_id},
            )
            continue
        want[(g.recipe_id, mid)] = want.get((g.recipe_id, mid), 0) + g.count
    got: dict[tuple[str, int], int] = {}
    for i, b in ctx.of_kind(Kind.MACHINE):
        name = ctx.recipe_of(i)
        if name is None:
            continue  # machine.group_resolved owns this, and this check is
            # reported in `skipped` for it -- see NEEDS_GROUPS
        key = (name, b.item_id)
        got[key] = got.get(key, 0) + 1
    for key in sorted(set(want) | set(got)):
        w, g_ = want.get(key, 0), got.get(key, 0)
        if w != g_:
            yield Finding(
                "spec.machine_counts",
                Severity.ERROR,
                f"recipe {key[0]!r} on machine {key[1]}: spec demands {w}, "
                f"placement has {g_}",
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


@check("prolif.belt_required_edges_not_direct_inserted", needs_spec=True, needs_groups=True)
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
        # Through `recipe_of`, not `recipe_name`: a mode-driven machine has no
        # recipe id to name, and this check reading the raw id was the ninth
        # place an exchanger became invisible.
        producer = ctx.recipe_of(src)
        consumer = ctx.recipe_of(dst)
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
    a lane exists but does not pass through some coater's addon area.

    IT IS VACUOUS ON A PLACEMENT WITH NO COATER, and deliberately so: it speaks
    only about coaters that exist.  Whether a sprayed lane HAS one, and whether
    the one it has is upstream of the machines drinking from it, is
    ``prolif.sprayed_cargo_reaches_machines`` below.  The two were confused
    once already -- a strategy silently skipped a coater it could not seat, this
    check found no coater to complain about, and the build shipped
    unproliferated.

    It used to look for a SORTER drawing from a proliferator belt.  That
    connection does not exist in the game -- a coater ships zero insert poses and
    `BuildTool_Inserter` will not target a building with none -- so the check was
    asserting the presence of something that could never have worked.  What
    supplies a coater is a belt inside its addon area, which is what
    `game.addon_supply` measures; this adds only the part that needs the spec,
    namely that the belt there carries PROLIFERATOR rather than just any cargo.
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

    supply_at = [
        (
            ctx.placement.buildings[i].x,
            ctx.placement.buildings[i].y,
            float(ctx.placement.buildings[i].z),
        )
        for i in supplying_belts
    ]
    starved = []
    for i, b in coaters:
        areas = cat.building(b.item_id).addon_areas
        ok = False
        for n, (adx, ady, adz) in enumerate(areas):
            if n == 0:
                continue
            wx, wy = slots.to_world((adx, ady), b.yaw)
            want = (b.x + wx, b.y + wy, float(b.z) + adz)
            ok = ok or any(
                rules.world_gap(want[0] - p[0], want[1] - p[1], want[2] - p[2])
                < rules.ADDON_AREA_RADIUS
                for p in supply_at
            )
        if not ok:
            starved.append(i)
    if starved:
        yield Finding(
            "prolif.coaters_are_supplied",
            Severity.ERROR,
            f"{len(starved)} of {len(coaters)} spray coaters have no proliferator "
            f"belt in their addon area, a tile behind and one level up",
            tuple(starved),
            {"starved": len(starved), "total": len(coaters)},
        )


def _coater_rides(ctx: Context) -> dict[int, int]:
    """Belt index -> the Spray Coater riding it.

    A coater has no links of its own, so the belt it sprays is the one on its
    own tile -- ``addonAreaPoses`` area 0.  :func:`_addon_rides` already
    resolves that, and this is the coater-only slice of it, cached because three
    clauses of the check below ask for it.
    """
    cached = ctx.cache.coater_rides
    if cached is not None:
        return cached
    out: dict[int, int] = {}
    for i, ride, _incoming, _outgoing in _addon_rides(ctx):
        if ride is None:
            continue
        if ctx.placement.buildings[i].item_id != cat.SPRAY_COATER_ID:
            continue
        out[ride] = i
    ctx.cache.coater_rides = out
    return out


def _unsprayed_belts(ctx: Context, item: str) -> set[int]:
    """Belt tiles ``item`` can reach WITHOUT having passed a Spray Coater.

    Forward reachability over the belt graph from every point unsprayed cargo
    can enter it, stopped at each coater.  Spray rides on the items and does not
    survive crafting, so the question a proliferated machine asks is not "is
    there a coater on my lane" but "did what I am eating go through one" -- and
    those differ by exactly the defects this exists to catch: a coater seated
    downstream of a sorter, and a lane that got no coater at all.

    THREE WAYS UNSPRAYED CARGO GETS ONTO A BELT, and missing any one of them
    would make this lenient in a way a strategy could sit inside:

    * a run head with no belt or junction feeding it -- cargo from outside the
      block, which is every external ingredient;
    * a sorter putting onto a belt from a MACHINE -- an internally produced
      ingredient, which ``prolif.belt_required_edges_not_direct_inserted`` has
      just forced onto a belt precisely so it can be sprayed;
    * a run head fed only by junctions or runs that are themselves unsprayed.

    A SORTER FROM BELT TO BELT IS AN EDGE, NOT A SOURCE -- a lane-to-lane
    transfer, which is how a trunk is tapped onto a branch without spending a
    splitter.  It carries whatever it draws, sprayed or not, so it has to be
    FOLLOWED: ``_belt_successors`` reads ``output_obj`` and splitters and stops
    dead at one of these, which would leave every branch fed only by a transfer
    reading as clean whatever its trunk carries.  ``_build_graph`` already links
    the two runs, so the branch's head is not mistaken for a source; what is
    missing there is the tile-level edge, and that is what ``hops`` is.

    Cargo AT the coater's own tile counts as sprayed.  The coater is an addon on
    that belt and the items pass through it there, which is why both strategies
    aim to seat one at the first tile of a lane rather than the tile before it.

    Restricted to belts that can plausibly carry ``item``: a run whose
    ``carries_item`` labels name other items and not this one cannot put this
    item into anything, and treating it as a source of unsprayed cargo would
    convict a lane for what a neighbouring lane carries.  An UNLABELLED run
    counts, because "we do not know" is not "nothing here".
    """
    bs = ctx.placement.buildings
    rides = _coater_rides(ctx)
    labels = _run_labels(ctx)

    def carries(belt: int) -> bool:
        r = ctx.run_of.get(belt)
        if r is None:
            return not bs[belt].carries_item or bs[belt].carries_item == item
        known = labels.get(r)
        return not known or item in known

    entry: set[int] = set()
    #: belt -> belts a sorter moves cargo onto from it.  An edge, not a source.
    hops: dict[int, list[int]] = defaultdict(list)
    # An internally produced ingredient arrives through a sorter off a machine;
    # a belt-to-belt sorter is a hop, and the run it lands on is already NOT a
    # source here because ``_build_graph`` links the two runs, so its head has a
    # predecessor and the clause below passes it over.
    for _i, s in ctx.of_kind(Kind.SORTER):
        src, dst = s.input_obj, s.output_obj
        if src is None or dst is None:
            continue
        if not (0 <= src < len(bs) and 0 <= dst < len(bs)):
            continue
        if ctx.kinds[dst] is not Kind.BELT or not carries(dst):
            continue
        if ctx.kinds[src] is Kind.MACHINE:
            entry.add(dst)
        elif ctx.kinds[src] is Kind.BELT:
            hops[src].append(dst)
    # An external ingredient arrives on a run nothing inside feeds.
    for r, run in enumerate(ctx.runs):
        head = run.head
        if not carries(head):
            continue
        if not ctx.pred.get((RUN, r)):
            entry.add(head)

    dirty: set[int] = set()
    stack = [b for b in entry if b not in rides]
    while stack:
        b = stack.pop()
        if b in dirty:
            continue
        dirty.add(b)
        for nxt in (*_belt_successors(ctx, b), *hops.get(b, ())):
            if nxt in dirty or nxt in rides or not carries(nxt):
                continue
            stack.append(nxt)
    return dirty


@check("prolif.sprayed_cargo_reaches_machines", needs_spec=True, needs_groups=True)
def _sprayed_cargo_reaches_machines(ctx: Context) -> Iterable[Finding]:
    """A proliferated machine must eat cargo that went THROUGH a coater.

    ``spec.spray_lanes`` names the ingredients whose lanes carry a Spray Coater,
    and until now nothing checked that any of them did.  Both strategies could
    skip a coater silently -- ``freeform._place_coaters`` ``continue``d when the
    drop cell was taken or the lane was too short to offer a legal seat, and
    ``spine`` seated one and then let the sorters draw from upstream of it.  The
    blueprint pastes either way, the machines run either way, and the build
    simply misses its rate: the same silent class as a coater at the tail of its
    own lane and as two sorters on one machine slot, both of which shipped.

    So the question is asked from the MACHINE's end, which is where the
    correctness lives.  For each proliferated group and each of its ingredients
    that ``spray_lanes`` names, every belt a sorter feeds that machine from must
    be downstream of a coater -- :func:`_unsprayed_belts` decides which are not.

    ``prolif.coaters_are_supplied`` cannot answer this and never could.  It asks
    whether proliferator reaches the coater; it says nothing about whether the
    coater reaches the machines, and on a placement with no coater at all it
    yields nothing, because it iterates the coaters that exist.

    MEASURED at the time it landed, over the first six corpus URLs and every
    proliferated candidate they offer: ``freeform`` 0 of 61 sprayed pickups
    unsprayed, ``spine`` 15 of 61 -- every one of the fifteen a coater seated
    DOWNSTREAM of the sorter that drew from its lane, on lanes that each had
    their coater and each passed ``prolif.coaters_are_supplied``.
    """
    assert ctx.spec is not None
    spec = ctx.spec
    if not spec.spray_lanes:
        return
    bs = ctx.placement.buildings
    items = _sorter_items(ctx)

    feeds: dict[int, list[tuple[int, int, str | None]]] = defaultdict(list)
    for i, s in ctx.of_kind(Kind.SORTER):
        src, dst = s.input_obj, s.output_obj
        if src is None or dst is None:
            continue
        if not (0 <= src < len(bs) and 0 <= dst < len(bs)):
            continue
        if ctx.kinds[src] is not Kind.BELT or ctx.kinds[dst] is not Kind.MACHINE:
            continue
        feeds[dst].append((i, src, items.get(i)))

    unsprayed: dict[str, set[int]] = {}
    for m, _b in ctx.of_kind(Kind.MACHINE):
        g = ctx.group_for(m)
        if g is None or not g.is_proliferated:
            continue
        for item in g.inputs_per_machine:
            if item not in spec.spray_lanes:
                continue
            # An unresolvable sorter is INCLUDED, not skipped.  "I could not
            # tell what this one carries" is the answer a validator may never
            # give silently, and a machine whose only feed of a sprayed
            # ingredient is unattributable is exactly the case where the
            # geometry needs looking at.
            candidates = [
                (i, src) for i, src, got in feeds.get(m, ()) if got in (item, None)
            ]
            if not candidates:
                continue  # `machine.inputs_supplied` owns the missing-feed case
            bad = unsprayed.get(item)
            if bad is None:
                bad = unsprayed[item] = _unsprayed_belts(ctx, item)
            for i, src in candidates:
                if src not in bad:
                    continue
                yield Finding(
                    "prolif.sprayed_cargo_reaches_machines",
                    Severity.ERROR,
                    f"sorter {i} feeds machine {m} with {item}, which "
                    f"{ctx.recipe_of(m)} is proliferated on, from belt {src} at "
                    f"({bs[src].x}, {bs[src].y}) -- and that belt is reachable by "
                    f"{item} that has not passed a Spray Coater. The build would "
                    f"paste, run, and quietly miss its rate",
                    (i, m, src),
                    {"item": item, "machine": m, "belt": src},
                )


# --- flow ------------------------------------------------------------------


@check("flow.conservation", needs_spec=True, needs_groups=True)
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


@check("flow.belt_capacity", needs_spec=True, needs_groups=True)
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


@check("flow.sorter_capacity", needs_spec=True, needs_groups=True)
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

    Resolved once per Context: this is a fixpoint over the whole flow graph and
    ``_sorter_item`` consults it per sorter, so rebuilding it per call made
    resolving a placement's items quadratic in the graph.
    """
    cached = ctx.cache.run_labels
    if cached is not None:
        return cached
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
    ctx.cache.run_labels = {
        r: labels[(RUN, r)] for r in range(len(ctx.runs)) if labels.get((RUN, r))
    }
    return ctx.cache.run_labels


def _sorter_item(ctx: Context, index: int) -> str | None:
    """The FactorioLab item id a sorter moves, or ``None`` if undeterminable.

    Three sources, most reliable first: an explicit ``filter_id``, the
    ``carries_item`` label on the belt it touches, and -- only when the machine
    leaves no ambiguity -- the single item that machine consumes or produces.
    """
    bs = ctx.placement.buildings
    s = bs[index]

    if s.filter_id and ctx.ids is not None:
        named = ctx.item_name(s.filter_id)
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
    would make every check quadratic in the sorter count -- and cached, because
    five separate checks ask for "one pass" and five passes is the same problem
    with a smaller constant.
    """
    cached = ctx.cache.sorter_items
    if cached is not None:
        return cached
    ctx.cache.sorter_items = {i: _sorter_item(ctx, i) for i, _ in ctx.of_kind(Kind.SORTER)}
    return ctx.cache.sorter_items


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

    The two divisors used to be counted by scanning every sorter in the
    placement, once per sorter asking.  :func:`_sorter_peers` tallies the same
    two things in one pass; see there for why the tally is the same integer.
    """
    peers = _sorter_peers(ctx, items)
    if item is not None and item in rates:
        table = peers.feed_item if feeding else peers.draw_item
        return rates[item] / (table.get((machine, item), 0) or 1)
    total = sum(rates.values(), Fraction(0))
    share = (peers.feed_any if feeding else peers.draw_any).get(machine, 0)
    return total / (share or 1)


def _sorter_peers(ctx: Context, items: Mapping[int, str | None]) -> _SorterPeers:
    """Tally, in one pass, how many sorters share each machine's load.

    Mirrors the two scans it replaces exactly.  A sorter with a ``None`` link
    matched no integer ``machine`` in the old comparison, so it is not counted
    here either; a sorter whose item is unresolved contributes to the ``any``
    tallies and to no ``item`` one, which is what ``items.get(j) == item`` did
    for a non-``None`` ``item``.

    Cached only against the canonical table from :func:`_sorter_items`, so a
    caller with a table of its own gets a tally computed from that table.
    """
    if items is ctx.cache.sorter_items and ctx.cache.sorter_peers is not None:
        return ctx.cache.sorter_peers
    feed_item: dict[tuple[int, str], int] = defaultdict(int)
    feed_any: dict[int, int] = defaultdict(int)
    draw_item: dict[tuple[int, str], int] = defaultdict(int)
    draw_any: dict[int, int] = defaultdict(int)
    for j, o in ctx.of_kind(Kind.SORTER):
        named = items.get(j)
        if o.output_obj is not None:
            feed_any[o.output_obj] += 1
            if named is not None:
                feed_item[(o.output_obj, named)] += 1
        if o.input_obj is not None:
            draw_any[o.input_obj] += 1
            if named is not None:
                draw_item[(o.input_obj, named)] += 1
    got = _SorterPeers(
        feed_item=feed_item, feed_any=feed_any, draw_item=draw_item, draw_any=draw_any
    )
    if items is ctx.cache.sorter_items:
        ctx.cache.sorter_peers = got
    return got


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

    Cached only for the canonical ``items`` table -- the one
    :func:`_sorter_items` hands out.  Every caller passes that one, but keying
    on identity means a caller with a different table still gets an answer
    computed from ITS table rather than a stale one.
    """
    canonical = items is ctx.cache.sorter_items
    if canonical and ctx.cache.run_items is not None:
        return ctx.cache.run_items
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

    out = {r: carried[(RUN, r)] for r in range(len(ctx.runs)) if carried.get((RUN, r))}
    if canonical:
        ctx.cache.run_items = out
    return out


@check("flow.lane_attribution", needs_spec=True, needs_groups=True)
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

    Two checks want this -- ``flow.belt_capacity`` and ``flow.headroom`` -- and
    it is the most expensive index the validator builds (two full propagations
    over the flow graph, in Fractions).  Building it twice was 20% of certify.
    """
    cached = ctx.cache.run_demand
    if cached is not None:
        return cached
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
    ctx.cache.run_demand = out
    return out


@check("flow.headroom", needs_spec=True, needs_groups=True)
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


def id_map(spec: BuildSpec) -> IdMap:
    """Bridge FactorioLab string ids to the DSP numeric ids a Placement uses.

    Built from the spec rather than the whole catalog, so an unmappable recipe
    elsewhere in the dataset cannot break a build that does not use it.

    Lives here rather than in the pipeline because a strategy needs it to check
    its own work, and a strategy cannot import the pipeline that imports it.
    """
    recipes: dict[str, int] = {}
    items: dict[str, int] = {}
    known = cat.known_recipe_ids()
    for g in spec.groups:
        if g.recipe_id in known:
            recipes[g.recipe_id] = cat.recipe_id(g.recipe_id)
        # The MACHINE is an item too, and `spec.machine_counts` needs it to
        # match a group against the buildings actually placed. Omitting it made
        # every group read as "spec demands 0" while the placement was correct.
        machine = cat.get_item_id(g.machine_item_id)
        if machine is not None:
            items[g.machine_item_id] = machine
        for item in (*g.inputs_per_machine, *g.outputs_per_machine):
            got = cat.get_item_id(item)
            if got is not None:
                items[item] = got
    for item in (*spec.external_inputs, *spec.outputs):
        got = cat.get_item_id(item)
        if got is not None:
            items[item] = got
    return IdMap(recipes=recipes, items=items)


def certify(placement: Placement, spec: BuildSpec, *, expect_power: bool) -> Report:
    """Judge a strategy's own output, so it cannot return something broken.

    ``LayoutStrategy.lay_out`` promises a valid ``Placement`` or
    :class:`NoValidLayout`.  For most of this project's life that promise was
    ARGUED rather than enforced -- a fallback construction was documented as
    "always valid", was not, and returned a layout that pasted cleanly and then
    did not run.  Deleting it helped; it did not make the promise true, because
    the solved path can be wrong too and nothing downstream of ``lay_out`` was
    obliged to look.

    This is what makes it true.  A strategy calls this before returning, and a
    rejected placement becomes a refusal.  That trade is deliberate and it goes
    the right way: refusing emits nothing, while an invalid blueprint pastes and
    is not discovered until somebody is standing in front of it in game.

    Returns the report rather than raising, so the caller can put the failing
    check names into its own error message.
    """
    return validate(placement, spec, ids=id_map(spec), expect_power=expect_power)


def validate(
    placement: Placement,
    spec: BuildSpec | None = None,
    *,
    ids: IdMap | None = None,
    soft_width: int = 256,
    only: Iterable[str] | None = None,
    expect_power: bool = True,
    max_belt_z: Fraction = cat.DEFAULT_MAX_BELT_Z,
    belt_vertical_construction: bool = True,
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

    ``max_belt_z`` and ``belt_vertical_construction`` are how high a belt may go
    in the SAVE this blueprint is for, and whether that save is under the
    game's belt slope limit at all.  They are caller declarations for the same
    reason: both are properties of the player's researched technologies.

    Checks in :data:`OPT_IN` run only when ``only`` names them, and are listed in
    ``Report.skipped`` otherwise.  See that set for the one member and why.

    ``belt_vertical_construction`` defaults to TRUE because an absent technology
    set means every technology researched -- FactorioLab's own default, see
    ``catalog.belt_rules_for_technologies``.  Defaulting it False would have the
    validator judge by a rule most saves are not under, and reject geometry the
    game accepts.
    """
    wanted = set(only) if only is not None else None
    ctx = _context(
        placement, spec, ids, soft_width, max_belt_z, belt_vertical_construction
    )
    have_spec = spec is not None and ids is not None
    # A check that could not resolve every machine did not examine everything it
    # claims to cover, so it may not be reported as having run.  It still runs:
    # the findings it DID make are real, and dropping them to preserve a tidy
    # verdict would trade one silence for another.
    unresolved = ctx.unresolved_machines() if have_spec else ()

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
        if cid in OPT_IN and wanted is None:
            skipped.append(cid)
            continue
        if unresolved and cid in NEEDS_GROUPS:
            skipped.append(cid)
        else:
            ran.append(cid)
        findings.extend(fn(ctx))
    return Report(tuple(findings), tuple(ran), tuple(skipped))
