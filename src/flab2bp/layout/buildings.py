"""One indexed view over a sequence of :class:`PlacedBuilding` records.

The layout pipeline asks the same few questions about a building sequence over
and over -- which machines run this recipe, which sorters feed that machine,
what sits on this tile -- and before this module every one of those questions
was a fresh linear scan, often inside a loop that already scaled with the
building count.

WHY A DICT AND NOT A TABLE LIBRARY

`littletable` and `polars` were both measured against real blueprints before
this module was written (see
``docs/superpowers/evidence/2026-09-07-buildings-index/backend-choice.md``).
Both LOSE to the linear scan they would replace at the sizes this project
produces -- 500 to 6000 buildings -- because each answers a lookup by
materialising a new container: on a 1969-building blueprint, one indexed
lookup costs 3246 us through littletable and 343 us through polars against a
141 us scan, while a plain dict answers in 0.2 us.  So the indexes here are
dicts built in one pass.

The backend is deliberately private to this module.  No caller imports a table
library, receives a backend object, or writes a query expression; every public
method is typed with this project's own types and returns positional building
indices.  Swapping the dicts for something else is a change to this file alone,
and ``tests/test_backend_containment.py`` fails if that boundary is breached.
"""

from __future__ import annotations

import bisect
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, MutableSequence, Sequence
from enum import Enum
from fractions import Fraction
from typing import TYPE_CHECKING, overload

from flab2bp.dsp import catalog
from flab2bp.layout.base import PlacedBuilding

if TYPE_CHECKING:
    from flab2bp.layout.base import Placement


class Kind(Enum):
    """What a building is, for the questions callers actually ask.

    Derived once per record from the catalog, so a call site never pays a
    ``catalog.is_belt`` lookup inside a loop again.
    """

    MACHINE = "machine"
    BELT = "belt"
    SORTER = "sorter"
    OTHER = "other"


def kind_for(item_id: int) -> Kind:
    if catalog.is_belt(item_id):
        return Kind.BELT
    if catalog.is_sorter(item_id):
        return Kind.SORTER
    if item_id in (catalog.SPLITTER_ID, catalog.PILER_ID):
        return Kind.OTHER
    return Kind.MACHINE


#: Shared empty result, so every ``dict.get(key, _EMPTY)`` below returns the
#: same immutable tuple rather than allocating a fresh empty one per miss.
_EMPTY: tuple[int, ...] = ()


def _index_one(
    i: int,
    b: PlacedBuilding,
    kinds: list[Kind],
    by_kind: dict[Kind, list[int]],
    by_item: dict[int, list[int]],
    by_recipe: dict[int, list[int]],
    by_owner_strip: dict[int | None, list[int]],
    by_carries: dict[str, list[int]],
    by_output_obj: dict[int, list[int]],
    by_input_obj: dict[int, list[int]],
    by_tile: dict[tuple[int, int], list[int]],
) -> None:
    """Fold one record's contributions into every bucket, in place, at index ``i``.

    Shared by the one-pass constructor build (:func:`_index_all`) and by
    ``MutableBuildings.append`` -- which calls this directly so an append is
    O(footprint) rather than a rebuild -- so a record's bucket membership can
    never be computed two different ways.

    Hand-rolled rather than ``b.tiles()``: that returns ``(x, y, z)`` triples
    and allocates a fresh list per call, while this index keys on ``(x, y)``
    alone -- routing every record through ``tiles()`` here would be strictly
    more allocation for the same tile set.
    """
    kind = kind_for(b.item_id)
    kinds.append(kind)
    by_kind[kind].append(i)
    by_item.setdefault(b.item_id, []).append(i)
    if kind is Kind.MACHINE:
        by_recipe.setdefault(b.recipe_id, []).append(i)
    by_owner_strip.setdefault(b.owner_strip, []).append(i)
    if b.carries_item is not None:
        by_carries.setdefault(b.carries_item, []).append(i)
    if b.output_obj is not None:
        by_output_obj.setdefault(b.output_obj, []).append(i)
    if b.input_obj is not None:
        by_input_obj.setdefault(b.input_obj, []).append(i)
    for dx in range(b.width):
        for dy in range(b.height):
            by_tile.setdefault((b.x + dx, b.y + dy), []).append(i)


def _index_all(
    records: Sequence[PlacedBuilding],
) -> tuple[
    list[Kind],
    dict[Kind, list[int]],
    dict[int, list[int]],
    dict[int, list[int]],
    dict[int | None, list[int]],
    dict[str, list[int]],
    dict[int, list[int]],
    dict[int, list[int]],
    dict[tuple[int, int], list[int]],
]:
    """One pass building every list-backed bucket for ``records``.

    ``Buildings.__init__`` freezes the result to tuples afterward;
    ``MutableBuildings.__init__`` keeps the lists so later ``append`` calls
    stay O(footprint).
    """
    kinds: list[Kind] = []
    by_kind: dict[Kind, list[int]] = {k: [] for k in Kind}
    by_item: dict[int, list[int]] = {}
    by_recipe: dict[int, list[int]] = {}
    by_owner_strip: dict[int | None, list[int]] = {}
    by_carries: dict[str, list[int]] = {}
    by_output_obj: dict[int, list[int]] = {}
    by_input_obj: dict[int, list[int]] = {}
    by_tile: dict[tuple[int, int], list[int]] = {}
    for i, b in enumerate(records):
        _index_one(
            i,
            b,
            kinds,
            by_kind,
            by_item,
            by_recipe,
            by_owner_strip,
            by_carries,
            by_output_obj,
            by_input_obj,
            by_tile,
        )
    return (
        kinds,
        by_kind,
        by_item,
        by_recipe,
        by_owner_strip,
        by_carries,
        by_output_obj,
        by_input_obj,
        by_tile,
    )


def bounds_of(records: Sequence[PlacedBuilding]) -> tuple[int, int, int, int]:
    """``(min_x, min_y, max_x, max_y)`` inclusive of every footprint tile.

    The single implementation of this computation.  ``Buildings._compute_bounds``
    calls it when it builds the full index; ``Placement.bounds`` also calls it
    directly, WITHOUT building a ``Buildings``, because bounds alone does not
    need the other eight buckets -- constructing all of them (``by_tile`` in
    particular, an O(N * width * height) loop) just to answer a bounds question
    on a candidate that gets asked once and discarded would cost more than the
    four comprehensions this module replaced.
    """
    if not records:
        return (0, 0, 0, 0)
    min_x = min(b.x for b in records)
    min_y = min(b.y for b in records)
    max_x = max(b.x + b.width - 1 for b in records)
    max_y = max(b.y + b.height - 1 for b in records)
    return (min_x, min_y, max_x, max_y)


class _BuildingsQueries:
    """The query surface shared, verbatim, by ``Buildings`` and ``MutableBuildings``.

    Every method here reads ``self._records``/``self._kinds``/``self._by_*``
    and never writes them -- ``Buildings`` backs them with tuples, dead after
    construction; ``MutableBuildings`` backs them with lists a handful of
    mutation methods update incrementally. Putting the questions in one place
    the two classes both inherit unchanged is what makes it impossible for
    the live and frozen answers to drift apart: a divergence between them
    would break this project's byte-identical-output bar exactly as badly as
    a wrong answer from either one alone.
    """

    __slots__ = ()

    # Declared for the two concrete subclasses' benefit (mypy and readers),
    # never assigned here. Both backings satisfy these read-only shapes;
    # `MutableBuildings` narrows them to the mutable containers it needs in
    # its own annotations, which is a legal covariant override.
    _records: Sequence[PlacedBuilding]
    _kinds: Sequence[Kind]
    _by_kind: Mapping[Kind, Sequence[int]]
    _by_item: Mapping[int, Sequence[int]]
    _by_recipe: Mapping[int, Sequence[int]]
    _by_owner_strip: Mapping[int | None, Sequence[int]]
    _by_carries: Mapping[str, Sequence[int]]
    _by_output_obj: Mapping[int, Sequence[int]]
    _by_input_obj: Mapping[int, Sequence[int]]
    _by_tile: Mapping[tuple[int, int], Sequence[int]]
    _bounds: tuple[int, int, int, int]

    # --- identity / access -------------------------------------------------

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self) -> Iterator[PlacedBuilding]:
        return iter(self._records)

    def all(self) -> tuple[PlacedBuilding, ...]:
        return tuple(self._records)

    def by_index(self, index: int | None) -> PlacedBuilding | None:
        """The record at ``index``, or ``None`` when it does not name one.

        Callers previously wrote ``0 <= i < len(buildings)`` guards at a dozen
        sites; this collapses all of them.  A NEGATIVE index is ``None``, not a
        Python tail lookup -- ``-1`` in this codebase means "no link".
        """
        if index is None or index < 0 or index >= len(self._records):
            return None
        return self._records[index]

    def kind_of(self, index: int) -> Kind:
        return self._kinds[index]

    # --- attribute indexes -------------------------------------------------

    def by_kind(self, kind: Kind) -> tuple[int, ...]:
        return tuple(self._by_kind.get(kind, _EMPTY))

    def machines(self) -> tuple[int, ...]:
        return tuple(self._by_kind[Kind.MACHINE])

    def belts(self) -> tuple[int, ...]:
        return tuple(self._by_kind[Kind.BELT])

    def sorters(self) -> tuple[int, ...]:
        return tuple(self._by_kind[Kind.SORTER])

    def by_item(self, item_id: int) -> tuple[int, ...]:
        return tuple(self._by_item.get(item_id, _EMPTY))

    def splitters(self) -> tuple[int, ...]:
        return tuple(self._by_item.get(catalog.SPLITTER_ID, _EMPTY))

    def machines_for_recipe(self, recipe_id: int) -> tuple[int, ...]:
        return tuple(self._by_recipe.get(recipe_id, _EMPTY))

    def by_owner_strip(self, owner_strip: int | None) -> tuple[int, ...]:
        return tuple(self._by_owner_strip.get(owner_strip, _EMPTY))

    def machines_for_strip(self, owner_strip: int) -> tuple[int, ...]:
        return tuple(
            i
            for i in self._by_owner_strip.get(owner_strip, _EMPTY)
            if self._kinds[i] is Kind.MACHINE
        )

    def carrying(self, item_id: str) -> tuple[int, ...]:
        return tuple(self._by_carries.get(item_id, _EMPTY))

    def belts_carrying(self, item_id: str) -> tuple[int, ...]:
        return tuple(
            i for i in self._by_carries.get(item_id, _EMPTY) if self._kinds[i] is Kind.BELT
        )

    def sorters_carrying(self, item_id: str) -> tuple[int, ...]:
        return tuple(
            i for i in self._by_carries.get(item_id, _EMPTY) if self._kinds[i] is Kind.SORTER
        )

    # --- link indexes --------------------------------------------------------

    def by_output_obj(self, index: int) -> tuple[int, ...]:
        """Every building whose ``output_obj`` names ``index``."""
        return tuple(self._by_output_obj.get(index, _EMPTY))

    def by_input_obj(self, index: int) -> tuple[int, ...]:
        """Every building whose ``input_obj`` names ``index``."""
        return tuple(self._by_input_obj.get(index, _EMPTY))

    def attached_to(self, index: int) -> tuple[int, ...]:
        """Every building linked to ``index`` from either end, ascending."""
        return tuple(sorted(set(self.by_output_obj(index)) | set(self.by_input_obj(index))))

    def belts_into(self, index: int) -> tuple[int, ...]:
        return tuple(
            i for i in self._by_output_obj.get(index, _EMPTY) if self._kinds[i] is Kind.BELT
        )

    def sorters_into(self, index: int) -> tuple[int, ...]:
        """Sorters that PUT DOWN at ``index`` (``output_obj == index``)."""
        return tuple(
            i for i in self._by_output_obj.get(index, _EMPTY) if self._kinds[i] is Kind.SORTER
        )

    def sorters_out_of(self, index: int) -> tuple[int, ...]:
        """Sorters that PICK UP at ``index`` (``input_obj == index``)."""
        return tuple(
            i for i in self._by_input_obj.get(index, _EMPTY) if self._kinds[i] is Kind.SORTER
        )

    def sorters_between(self, sources: Collection[int], sinks: Collection[int]) -> tuple[int, ...]:
        """Sorters picking up in ``sources`` and putting down in ``sinks``.

        Drives off whichever endpoint set is smaller and looks up ITS
        incident sorters via the link indexes, intersecting against the
        other set -- rather than scanning every sorter in the building set
        and testing membership in both.  ``sources``/``sinks`` need
        ``len()``, hence ``Collection`` rather than the weaker ``Container``.
        The result is always ascending positional indices, regardless of
        which branch ran.

        Whichever argument is the LARGER one pays an ``in`` test per hit on
        the smaller side's incident sorters -- pass a ``set``/``frozenset``
        for O(1) membership there, not a ``list``/``tuple``, or that
        membership test degrades to a linear scan and undoes the whole point
        of driving off the smaller side.
        """
        if len(sources) <= len(sinks):
            found = {
                i
                for s in sources
                for i in self.sorters_out_of(s)
                if self._records[i].output_obj in sinks
            }
        else:
            found = {
                i
                for t in sinks
                for i in self.sorters_into(t)
                if self._records[i].input_obj in sources
            }
        return tuple(sorted(found))

    def predecessor_of(self, index: int) -> int | None:
        """The unique building whose ``output_obj`` names ``index``.

        ``None`` covers both "nothing points here" and "more than one thing
        does" -- ambiguous fan-in has no single predecessor to report.
        Distinct from :meth:`by_output_obj`, which returns every predecessor.
        """
        preds = self._by_output_obj.get(index, _EMPTY)
        if len(preds) == 1:
            return preds[0]
        return None

    def transport_successors(self, index: int) -> tuple[int, ...]:
        """Directed belt/Splitter/Piler edges from the current link buckets.

        Belts name their destination with ``output_obj``. Splitters and Pilers
        instead feed belts naming the host with ``input_obj``; arbitrary raw
        input links do not create another forward edge.
        """
        building = self.by_index(index)
        if building is None:
            return _EMPTY
        kind = self._kinds[index]
        if kind is Kind.OTHER:
            return tuple(
                i for i in self._by_input_obj.get(index, _EMPTY) if self._kinds[i] is Kind.BELT
            )
        if kind is Kind.BELT:
            target = building.output_obj
            if (
                target is not None
                and self.by_index(target) is not None
                and self._kinds[target] in (Kind.BELT, Kind.OTHER)
            ):
                return (target,)
        return _EMPTY

    def transport_reaches_any(
        self,
        start: int,
        targets: Collection[int],
        item: str,
        *,
        sorter_item: Callable[[int], str | None] | None = None,
    ) -> bool:
        """Reach a transport tap through directed devices and same-cargo sorters.

        Validation may supply context-resolved sorter cargo; planning markers
        use the placement's attribution. Machines never become transit nodes.
        """
        pending = [start]
        seen: set[int] = set()
        while pending:
            index = pending.pop()
            if index in seen or self.by_index(index) is None:
                continue
            seen.add(index)
            if index in targets:
                return True
            pending.extend(self.transport_successors(index))
            for sorter_index in self.sorters_out_of(index):
                sorter = self._records[sorter_index]
                cargo = sorter.carries_item if sorter_item is None else sorter_item(sorter_index)
                destination = sorter.output_obj
                if (
                    cargo == item
                    and destination is not None
                    and self.by_index(destination) is not None
                    and self._kinds[destination] in (Kind.BELT, Kind.OTHER)
                ):
                    pending.append(destination)
        return False

    def transport_predecessors(self, index: int) -> tuple[int, ...]:
        """The inverse transport edges, in ascending live-bucket order."""
        building = self.by_index(index)
        if building is None or self._kinds[index] not in (Kind.BELT, Kind.OTHER):
            return _EMPTY
        predecessors = [
            i for i in self._by_output_obj.get(index, _EMPTY) if self._kinds[i] is Kind.BELT
        ]
        host = building.input_obj
        if (
            self._kinds[index] is Kind.BELT
            and host is not None
            and self.by_index(host) is not None
            and self._kinds[host] is Kind.OTHER
        ):
            bisect.insort(predecessors, host)
        return tuple(predecessors)

    def belt_run(
        self, index: int, *, forward: bool, through_any_host: bool = False
    ) -> frozenset[int]:
        """Every belt of the run anchored by belt ``index``, in one direction.

        Belt chains are forward-linked, so a tail's run is everything that
        flows INTO it (``forward=False``) and a head's run is everything it
        flows into (``forward=True``). Splitters and pilers (``Kind.OTHER``)
        are crossed rather than stopped at: the belts around one name it as
        their ``output_obj``/``input_obj`` and the cargo passes through.
        The seed must be a belt; hosts are transit points reached from a belt,
        not supported starting anchors. Cycle-safe via a visited set.

        ``through_any_host`` also crosses other valid non-belt hosts. Hierarchy
        lane weighting uses this to retain the input/output belt connection
        through port-driven machines; ordinary run queries keep the narrower
        Splitter/Piler semantics unless explicitly requested otherwise.
        """

        def forward_of(i: int) -> tuple[int, ...]:
            link = self._records[i].output_obj
            if link is None or self.by_index(link) is None:
                return _EMPTY
            if self._kinds[link] is Kind.BELT:
                return (link,)
            if self._kinds[link] is Kind.OTHER or through_any_host:
                return tuple(
                    j for j in self._by_input_obj.get(link, _EMPTY) if self._kinds[j] is Kind.BELT
                )
            return _EMPTY

        def backward_of(i: int) -> tuple[int, ...]:
            preds = self.belts_into(i)
            link = self._records[i].input_obj
            if (
                link is not None
                and self.by_index(link) is not None
                and (
                    self._kinds[link] is Kind.OTHER
                    or (through_any_host and self._kinds[link] is not Kind.BELT)
                )
            ):
                preds = preds + self.belts_into(link)
            return preds

        step = forward_of if forward else backward_of
        seen = {index}
        stack = [index]
        while stack:
            node = stack.pop()
            if self._kinds[node] is not Kind.BELT:
                continue
            for nxt in step(node):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return frozenset(seen)

    # --- spatial -------------------------------------------------------------

    def at_tile(self, x: int, y: int, z: Fraction | int | None = None) -> tuple[int, ...]:
        """Buildings whose footprint covers ``(x, y)``, optionally at ``z``."""
        hits = self._by_tile.get((x, y), _EMPTY)
        if z is None:
            return tuple(hits)
        return tuple(i for i in hits if self._records[i].z == z)

    def in_box(self, x0: int, y0: int, x1: int, y1: int) -> tuple[int, ...]:
        """Buildings whose footprint intersects the inclusive box."""
        seen: set[int] = set()
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                seen.update(self._by_tile.get((x, y), _EMPTY))
        return tuple(sorted(seen))

    def _compute_bounds(self) -> tuple[int, int, int, int]:
        return bounds_of(self._records)

    def bounds(self) -> tuple[int, int, int, int]:
        """``(min_x, min_y, max_x, max_y)`` inclusive of every footprint tile."""
        return self._bounds

    # --- counts ----------------------------------------------------------------

    def count_by_kind(self, kind: Kind) -> int:
        return len(self._by_kind.get(kind, _EMPTY))

    def count_by_item(self, item_id: int) -> int:
        return len(self._by_item.get(item_id, _EMPTY))


class Buildings(_BuildingsQueries):
    """An immutable indexed view over a building sequence."""

    __slots__ = (
        "_records",
        "_kinds",
        "_by_kind",
        "_by_item",
        "_by_recipe",
        "_by_owner_strip",
        "_by_carries",
        "_by_output_obj",
        "_by_input_obj",
        "_by_tile",
        "_bounds",
    )

    def __init__(self, records: Sequence[PlacedBuilding]) -> None:
        self._records = tuple(records)
        (
            kinds,
            by_kind,
            by_item,
            by_recipe,
            by_owner_strip,
            by_carries,
            by_output_obj,
            by_input_obj,
            by_tile,
        ) = _index_all(self._records)
        self._kinds = tuple(kinds)
        self._by_kind = {k: tuple(v) for k, v in by_kind.items()}
        self._by_item = {k: tuple(v) for k, v in by_item.items()}
        self._by_recipe = {k: tuple(v) for k, v in by_recipe.items()}
        self._by_owner_strip = {k: tuple(v) for k, v in by_owner_strip.items()}
        self._by_carries = {k: tuple(v) for k, v in by_carries.items()}
        self._by_output_obj = {k: tuple(v) for k, v in by_output_obj.items()}
        self._by_input_obj = {k: tuple(v) for k, v in by_input_obj.items()}
        self._by_tile = {k: tuple(v) for k, v in by_tile.items()}
        self._bounds = self._compute_bounds()

    @classmethod
    def of(cls, placement: Placement) -> Buildings:
        """The shared index for a frozen ``Placement``, building it once.

        Every caller that asks a question about ``placement`` -- ``bounds``
        today, more of ``_BuildingsQueries`` as later tasks convert their call
        sites -- gets the SAME index rather than each building its own: the
        first call memoises it onto ``placement.buildings_index`` via
        ``object.__setattr__`` (the field is ``init=False`` precisely so
        ``dataclasses.replace`` never carries a stale one onto different
        records), and every later call for that placement answers from it.
        """
        cached = placement.buildings_index
        if cached is not None:
            return cached
        index = cls(placement.buildings)
        object.__setattr__(placement, "buildings_index", index)
        return index


#: Record fields ``MutableBuildings.__setitem__`` treats as immutable after
#: insertion. Deliberately excludes ``z``: freeform relinks it in place at two
#: call sites, and no index here keys on it -- ``at_tile``'s z filter reads
#: ``self._records[i].z`` live, so a relinked z is correct the moment the
#: record is stored, with nothing else to update.
_GEOMETRY_FIELDS: tuple[str, ...] = (
    "item_id",
    "model_index",
    "x",
    "y",
    "width",
    "height",
    "owner_strip",
    "recipe_id",
    "carries_item",
)


def _pop_expect(bucket: list[int], expected: int, *, where: str) -> int:
    """Pop the tail of ``bucket`` and confirm it was ``expected``; return it.

    ``MutableBuildings`` relies on every bucket staying sorted ascending --
    ``append`` only ever grows at the high end, and ``__setitem__`` relinks
    insert via ``bisect.insort`` -- so the index being tail-removed, always
    the current global maximum, is always the LAST entry of any bucket it
    belongs to. That lets a tail removal pop every bucket in O(1) instead of
    searching each one for the value. This checks the invariant rather than
    trusting it silently: a violation would otherwise corrupt the index
    without ever raising.
    """
    got = bucket.pop()
    if got != expected:
        bucket.append(got)
        raise RuntimeError(
            f"MutableBuildings: internal invariant violated popping {where} -- "
            f"expected the tail index {expected}, found {got}"
        )
    return got


class MutableBuildings(_BuildingsQueries, MutableSequence[PlacedBuilding]):
    """The live-canvas counterpart to :class:`Buildings`.

    Every query method is inherited from :class:`_BuildingsQueries` unchanged,
    so the live and frozen answers cannot drift apart. What this class adds is
    the narrow mutation grammar freeform's canvas actually uses -- tail
    :meth:`append`, tail :meth:`pop`/:meth:`__delitem__`, and an
    :meth:`__setitem__` replacement that preserves indexed identity and footprint
    fields. Links are maintained; unindexed fields (including altitude and DSP
    port slots) are read from the current record. Unsupported indexed geometry
    changes raise rather than silently answering from a stale index.

    The backing buckets are ``dict[key, list[int]]`` rather than
    ``Buildings``'s ``dict[key, tuple[int, ...]]``, so :meth:`append` can grow
    them in place -- O(footprint), never a rebuild.
    """

    __slots__ = (
        "_records",
        "_kinds",
        "_by_kind",
        "_by_item",
        "_by_recipe",
        "_by_owner_strip",
        "_by_carries",
        "_by_output_obj",
        "_by_input_obj",
        "_by_tile",
        "_bounds",
    )

    # Narrows the mixin's read-only ``Sequence``/``Mapping`` declarations to
    # the concrete mutable containers this class actually stores -- a
    # covariant override, legal because every one of these types is a subtype
    # of what the mixin declared. Needed so this class's own mutation methods
    # (below) type-check calling ``.append``/``.remove``/``bisect.insort`` on
    # them, not just the read-only ``Buildings`` side.
    _records: list[PlacedBuilding]
    _kinds: list[Kind]
    _by_kind: dict[Kind, list[int]]
    _by_item: dict[int, list[int]]
    _by_recipe: dict[int, list[int]]
    _by_owner_strip: dict[int | None, list[int]]
    _by_carries: dict[str, list[int]]
    _by_output_obj: dict[int, list[int]]
    _by_input_obj: dict[int, list[int]]
    _by_tile: dict[tuple[int, int], list[int]]

    def __init__(self, records: Sequence[PlacedBuilding] = ()) -> None:
        self._records = list(records)
        (
            kinds,
            by_kind,
            by_item,
            by_recipe,
            by_owner_strip,
            by_carries,
            by_output_obj,
            by_input_obj,
            by_tile,
        ) = _index_all(self._records)
        self._kinds = kinds
        self._by_kind = by_kind
        self._by_item = by_item
        self._by_recipe = by_recipe
        self._by_owner_strip = by_owner_strip
        self._by_carries = by_carries
        self._by_output_obj = by_output_obj
        self._by_input_obj = by_input_obj
        self._by_tile = by_tile
        self._bounds = self._compute_bounds()

    # --- MutableSequence machinery -------------------------------------------

    @overload
    def __getitem__(self, index: int) -> PlacedBuilding: ...
    @overload
    def __getitem__(self, index: slice) -> list[PlacedBuilding]: ...

    def __getitem__(self, index: int | slice) -> PlacedBuilding | list[PlacedBuilding]:
        return self._records[index]

    def __setitem__(
        self, index: int | slice, value: PlacedBuilding | Iterable[PlacedBuilding]
    ) -> None:
        """Replace a record without changing indexed identity or footprint.

        Links update their buckets; unindexed fields such as ``z`` and port
        slots may change freely. Fields in ``_GEOMETRY_FIELDS`` must match the
        original, or this raises ``ValueError`` rather than retaining a stale
        index.
        """
        if isinstance(index, slice) or not isinstance(value, PlacedBuilding):
            raise ValueError("MutableBuildings: slice assignment is not supported")
        n = len(self._records)
        i = index if index >= 0 else index + n
        if not (0 <= i < n):
            raise IndexError(f"MutableBuildings: index {index} out of range (len={n})")
        old = self._records[i]
        new = value
        for field_name in _GEOMETRY_FIELDS:
            old_value = getattr(old, field_name)
            new_value = getattr(new, field_name)
            if old_value != new_value:
                raise ValueError(
                    "MutableBuildings: geometry is immutable after insertion; "
                    f"{field_name} changed from {old_value!r} to {new_value!r} at "
                    f"index {i}. Indexed identity and footprint fields "
                    "must remain unchanged via __setitem__."
                )
        if old.output_obj != new.output_obj:
            self._relink(self._by_output_obj, old.output_obj, new.output_obj, i)
        if old.input_obj != new.input_obj:
            self._relink(self._by_input_obj, old.input_obj, new.input_obj, i)
        self._records[i] = new

    @staticmethod
    def _relink(
        bucket_map: dict[int, list[int]], old_link: int | None, new_link: int | None, index: int
    ) -> None:
        """Move ``index`` from ``old_link``'s bucket to ``new_link``'s, sorted.

        Insertion via :func:`bisect.insort` (not append) is what keeps every
        link bucket in ascending order under a relink that may target an
        index smaller than entries already there -- the same ordering
        :func:`_pop_expect` later relies on to tail-pop in O(1).
        """
        if old_link is not None:
            bucket_map[old_link].remove(index)
        if new_link is not None:
            bisect.insort(bucket_map.setdefault(new_link, []), index)

    def __delitem__(self, index: int | slice) -> None:
        if isinstance(index, slice):
            raise ValueError("MutableBuildings: slice deletion is not supported")
        n = len(self._records)
        i = index if index >= 0 else index + n
        if n == 0 or i != n - 1:
            raise ValueError(
                f"MutableBuildings: __delitem__ only supports the tail index "
                f"(len={n}); got {index}. A non-tail delete would renumber "
                "every positional index that follows it."
            )
        self._remove_tail()

    def insert(self, index: int, value: PlacedBuilding) -> None:
        """Delegates to :meth:`append` at the tail; raises everywhere else.

        A mid-sequence insert would renumber every positional index in the
        tree, which nothing here (or in freeform) is built to survive.
        """
        if index == len(self._records):
            self.append(value)
            return
        raise ValueError(
            "MutableBuildings: insert only supports the tail position "
            f"(len={len(self._records)}); got index {index}. A mid-sequence "
            "insert would renumber every positional index in the tree."
        )

    def append(self, value: PlacedBuilding) -> None:
        """The only growth this class supports. O(footprint), never a rebuild."""
        i = len(self._records)
        self._records.append(value)
        _index_one(
            i,
            value,
            self._kinds,
            self._by_kind,
            self._by_item,
            self._by_recipe,
            self._by_owner_strip,
            self._by_carries,
            self._by_output_obj,
            self._by_input_obj,
            self._by_tile,
        )
        self._widen_bounds(value)

    def pop(self, index: int = -1) -> PlacedBuilding:
        """Tail-only. Raises ``ValueError`` mentioning "tail" for anything else."""
        n = len(self._records)
        if n == 0:
            raise IndexError("MutableBuildings: pop from an empty sequence")
        i = index if index >= 0 else index + n
        if i != n - 1:
            raise ValueError(
                f"MutableBuildings: pop only supports the tail index (len={n}); "
                f"got {index}. A non-tail pop would renumber every positional "
                "index that follows it."
            )
        return self._remove_tail()

    def snapshot(self) -> Buildings:
        """A frozen :class:`Buildings` view over the records as they stand now."""
        return Buildings(self._records)

    # --- internal --------------------------------------------------------------

    def _widen_bounds(self, b: PlacedBuilding) -> None:
        x0, y0 = b.x, b.y
        x1, y1 = b.x + b.width - 1, b.y + b.height - 1
        if len(self._records) == 1:
            # The record just appended was the first one; there was nothing
            # to widen against.
            self._bounds = (x0, y0, x1, y1)
            return
        min_x, min_y, max_x, max_y = self._bounds
        self._bounds = (min(min_x, x0), min(min_y, y0), max(max_x, x1), max(max_y, y1))

    def _remove_tail(self) -> PlacedBuilding:
        """Undo exactly what :func:`_index_one` did for the tail record.

        Every bucket pop here is O(1) via :func:`_pop_expect`, not a search --
        see that function for the ordering invariant this relies on. Bounds
        cannot be maintained incrementally on the way down (removing the
        record that set the max/min leaves no cheap answer), so this always
        recomputes them from what remains -- acceptable because a pop happens
        once per rolled-back path prefix, not once per query.
        """
        i = len(self._records) - 1
        b = self._records[i]
        kind = self._kinds[i]
        _pop_expect(self._by_kind[kind], i, where="by_kind")
        _pop_expect(self._by_item[b.item_id], i, where="by_item")
        if kind is Kind.MACHINE:
            _pop_expect(self._by_recipe[b.recipe_id], i, where="by_recipe")
        _pop_expect(self._by_owner_strip[b.owner_strip], i, where="by_owner_strip")
        if b.carries_item is not None:
            _pop_expect(self._by_carries[b.carries_item], i, where="by_carries")
        if b.output_obj is not None:
            _pop_expect(self._by_output_obj[b.output_obj], i, where="by_output_obj")
        if b.input_obj is not None:
            _pop_expect(self._by_input_obj[b.input_obj], i, where="by_input_obj")
        for dx in range(b.width):
            for dy in range(b.height):
                _pop_expect(self._by_tile[(b.x + dx, b.y + dy)], i, where="by_tile")
        self._kinds.pop()
        self._records.pop()
        self._bounds = self._compute_bounds()
        return b
