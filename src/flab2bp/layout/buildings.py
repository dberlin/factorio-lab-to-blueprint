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

from collections.abc import Container, Iterator, Sequence
from enum import Enum
from fractions import Fraction

from flab2bp.dsp import catalog
from flab2bp.layout.base import PlacedBuilding


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


#: Every attribute the survey found a call site filtering on, and the accessor
#: that reads it.  Adding a key here adds an index; nothing else changes.
_EMPTY: tuple[int, ...] = ()


class Buildings:
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
        self._records: tuple[PlacedBuilding, ...] = tuple(records)
        kinds: list[Kind] = []
        by_kind: dict[Kind, list[int]] = {k: [] for k in Kind}
        by_item: dict[int, list[int]] = {}
        by_recipe: dict[int, list[int]] = {}
        by_owner_strip: dict[int | None, list[int]] = {}
        by_carries: dict[str, list[int]] = {}
        by_output_obj: dict[int, list[int]] = {}
        by_input_obj: dict[int, list[int]] = {}
        by_tile: dict[tuple[int, int], list[int]] = {}
        for i, b in enumerate(self._records):
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
        self._kinds: tuple[Kind, ...] = tuple(kinds)
        self._by_kind = {k: tuple(v) for k, v in by_kind.items()}
        self._by_item = {k: tuple(v) for k, v in by_item.items()}
        self._by_recipe = {k: tuple(v) for k, v in by_recipe.items()}
        self._by_owner_strip = {k: tuple(v) for k, v in by_owner_strip.items()}
        self._by_carries = {k: tuple(v) for k, v in by_carries.items()}
        self._by_output_obj = {k: tuple(v) for k, v in by_output_obj.items()}
        self._by_input_obj = {k: tuple(v) for k, v in by_input_obj.items()}
        self._by_tile = {k: tuple(v) for k, v in by_tile.items()}
        self._bounds = self._compute_bounds()

    # NOTE: ``Buildings.of(placement)`` is deliberately NOT in this task.  It
    # needs the ``Placement.buildings_index`` field, which Task 3 adds; writing
    # it here would not type-check against a field that does not yet exist, and
    # would require importing ``Placement`` from ``flab2bp.layout.base`` for no
    # reason this task needs.  Task 3 Step 4 adds both the field and ``of``.

    # --- identity / access -------------------------------------------------

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self) -> Iterator[PlacedBuilding]:
        return iter(self._records)

    def all(self) -> tuple[PlacedBuilding, ...]:
        return self._records

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
        return self._by_kind.get(kind, _EMPTY)

    def machines(self) -> tuple[int, ...]:
        return self._by_kind[Kind.MACHINE]

    def belts(self) -> tuple[int, ...]:
        return self._by_kind[Kind.BELT]

    def sorters(self) -> tuple[int, ...]:
        return self._by_kind[Kind.SORTER]

    def by_item(self, item_id: int) -> tuple[int, ...]:
        return self._by_item.get(item_id, _EMPTY)

    def splitters(self) -> tuple[int, ...]:
        return self._by_item.get(catalog.SPLITTER_ID, _EMPTY)

    def machines_for_recipe(self, recipe_id: int) -> tuple[int, ...]:
        return self._by_recipe.get(recipe_id, _EMPTY)

    def by_owner_strip(self, owner_strip: int | None) -> tuple[int, ...]:
        return self._by_owner_strip.get(owner_strip, _EMPTY)

    def machines_for_strip(self, owner_strip: int) -> tuple[int, ...]:
        return tuple(
            i
            for i in self._by_owner_strip.get(owner_strip, _EMPTY)
            if self._kinds[i] is Kind.MACHINE
        )

    def carrying(self, item_id: str) -> tuple[int, ...]:
        return self._by_carries.get(item_id, _EMPTY)

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
        return self._by_output_obj.get(index, _EMPTY)

    def by_input_obj(self, index: int) -> tuple[int, ...]:
        """Every building whose ``input_obj`` names ``index``."""
        return self._by_input_obj.get(index, _EMPTY)

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

    def sorters_between(self, sources: Container[int], sinks: Container[int]) -> tuple[int, ...]:
        """Sorters picking up in ``sources`` and putting down in ``sinks``.

        Drives off the sorter index rather than off the building list, which is
        the whole point: the old shape walked every building once per group
        member, and the group is always the smaller set.
        """
        return tuple(
            i
            for i in self._by_kind[Kind.SORTER]
            if self._records[i].input_obj in sources and self._records[i].output_obj in sinks
        )

    # --- spatial -------------------------------------------------------------

    def at_tile(self, x: int, y: int, z: Fraction | int | None = None) -> tuple[int, ...]:
        """Buildings whose footprint covers ``(x, y)``, optionally at ``z``."""
        hits = self._by_tile.get((x, y), _EMPTY)
        if z is None:
            return hits
        return tuple(i for i in hits if self._records[i].z == z)

    def in_box(self, x0: int, y0: int, x1: int, y1: int) -> tuple[int, ...]:
        """Buildings whose footprint intersects the inclusive box."""
        seen: set[int] = set()
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                seen.update(self._by_tile.get((x, y), _EMPTY))
        return tuple(sorted(seen))

    def _compute_bounds(self) -> tuple[int, int, int, int]:
        if not self._records:
            return (0, 0, 0, 0)
        min_x = min(b.x for b in self._records)
        min_y = min(b.y for b in self._records)
        max_x = max(b.x + b.width - 1 for b in self._records)
        max_y = max(b.y + b.height - 1 for b in self._records)
        return (min_x, min_y, max_x, max_y)

    def bounds(self) -> tuple[int, int, int, int]:
        """``(min_x, min_y, max_x, max_y)`` inclusive of every footprint tile."""
        return self._bounds

    # --- counts ----------------------------------------------------------------

    def count_by_kind(self, kind: Kind) -> int:
        return len(self._by_kind.get(kind, _EMPTY))

    def count_by_item(self, item_id: int) -> int:
        return len(self._by_item.get(item_id, _EMPTY))
