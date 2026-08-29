"""FactorioLab's own solved flow, read from its CSV export.

FactorioLab's list view has a "download as CSV" button (``Exporter.stepsToCsv``
in ``src/exporter/exporter.ts``).  It writes the flow it solved: one row per
step, naming the RECIPE it chose for each item.  Consuming that selection is the
whole point of this module.  We re-derive nothing about *which* recipe makes
what -- that decision is the player's, made in FactorioLab's UI.  Measured on
the corpus, 17 items have more than one permitted producer and **16 of those
choices move the blueprint's input/output boundary**, which is how a flow
containing no stone produced a blueprint asking the player to belt stone in.

What the file actually is
-------------------------

Read off FactorioLab's own exporter source, not inferred from a sample:

* **Line 1 is** ``"<window.location.href>"`` -- the source URL, wrapped in
  double quotes.  It is the provenance record :func:`verify_provenance` checks.
* **Line 2 is a header of column names** drawn from a fixed vocabulary
  (``StepKeys``), but *only the columns some row fills* are emitted.  The header
  therefore varies between downloads, so columns are read by NAME, never by
  position.
* **Rows are comma-joined.**  The fields that can contain commas -- ``Inputs``,
  ``Outputs``, ``Targets``, ``Modules``, ``Beacons`` -- are written pre-quoted by
  the exporter, so the file is ordinary RFC4180 CSV.  Rows are ragged: a row
  stops at its last filled column.
* **Every numeric cell is** ``"=" + Rational.toString()``.  The leading ``=``
  exists so a spreadsheet evaluates the cell.  ``Rational.toString()`` emits a
  plain decimal *only* when the value survives ``toFixed(3)`` unchanged, and an
  exact ``p/q`` otherwise -- so **a pristine download is exact throughout**,
  including ``Machines`` and ``Items``.

Everything parsed here becomes a ``Fraction``.  No value in this module is ever
a float: belts are sized from these rates and the validator checks capacity
exactly, so a float in this path ships a blueprint that quietly misses its rate,
which is the worst failure mode this program has.

Why not the JSON export
-----------------------

FactorioLab's flow view also offers "download as JSON" (``flowToJson``), and it
looks like the better-structured choice.  It is not, and the reasoning is worth
keeping because it is not visible from the outside -- both files describe the
same solve, and the JSON is the one that loses information:

* ``flowToJson`` writes ``JSON.stringify(flowData)`` where ``flowData`` is the
  **Sankey diagram model** (``src/flow/flow-builder.ts``), not the solve.
* ``link.value`` is a **float** via ``Rational.toNumber()``, and is not even a
  rate: it is scaled to 1/10 for fluids, floored at ``MIN_LINK_VALUE = 1e-10``,
  and its *meaning* is whatever the viewer's ``linkSize`` preference says --
  items, belts, machines, or a percentage.
* ``node.text`` and ``link.text`` are display strings: ``toLocaleString``,
  rounded to the viewer's column-precision preference and locale-formatted.
* **Item nodes are deleted.**  ``buildGraph`` prunes any item node with a single
  source or a single target and re-points the links around it -- exactly the
  shape of an external input feeding one recipe -- so its item set is incomplete
  by construction.  The ``hideExcluded`` preference removes more.
* **It contains no URL**, so a stale export whose selection still parses cannot
  be detected at all.

The decimals in the CSV that look lossy are an artefact of opening the file in a
spreadsheet: ``=25/56`` is a formula, and Excel evaluates it to ``0.446428571``.
The tell is that the *quoted* text cells in the same file keep their fractions
(``coal:2161/3571``) while only the ``=``-prefixed cells lose them.  Verified on
the real sample: ``0.083333333 = 1/12``, ``0.208333333 = 5/24``,
``0.446428571 = 25/56``, each truncated to nine places.  Such a file is still
accepted -- it is what a user is most likely to hand over -- but its mangled
values are flagged :attr:`FlowRow.exact` ``False`` and the cross-check says so
rather than reporting spurious disagreements.

How the selection is applied
----------------------------

:func:`pin_request` rewrites the request's recipe-exclusion set to "every recipe
FactorioLab did not choose".  That is the existing, well-understood lever --
``solve._excluded_recipes`` already treats the URL's exclusion set as
authoritative, "the state of FactorioLab's UI, not a delta" -- so pinning
introduces no new concept in the rate solver, and nothing changes at all for a
build that supplies no flow file.  An item whose only chosen producer is
mining-flagged still falls out as an external input for the reason it always
did: ``_buildable_producers`` cuts the 22 mining recipes because extraction
happens outside the blueprint.

There is no fallback.  Absent, malformed, for the wrong URL, or naming a recipe
we cannot build: this module raises.  Silently re-deriving the selection is the
behaviour it exists to remove.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType
from typing import Final
from urllib.parse import parse_qsl, urlsplit

from flab2bp.dsp import catalog
from flab2bp.lab.schema import Dataset, Item, Recipe
from flab2bp.lab.url import DisplayRate, LabRequest, ObjectiveType

__all__ = [
    "FlowError",
    "FlowFormatError",
    "FlowProvenanceError",
    "FlowRow",
    "FlowSelection",
    "FlowSelectionError",
    "canonical_item_id",
    "canonical_recipe_id",
    "canonicalize_dataset",
    "canonicalize_request",
    "cross_check",
    "flow_from_text",
    "load_flow",
    "parse_flow_csv",
    "pin_request",
    "pinned_exclusions",
    "unsupplied_inputs",
    "verify_against_request",
    "verify_provenance",
]


_OBSERVED_ITEM_ALIASES: Final = {
    "df-combustion-unit": "combustible-unit",
    "df-supersonic-missle-set": "supersonic-missile-set",
    "df-recomposing-assembler": "re-composing-assembler",
    "df-plasma-turret-sr": "sr-plasma-turret",
}


def canonical_item_id(item_id: str) -> str:
    """Catalog-backed identity for a FactorioLab item id.

    FactorioLab prefixes Dark Fog-era game items with ``df-`` while the DSP
    catalog uses their ordinary ids. Prefix removal is accepted only when the
    resulting (or observed spelling-corrected) id exists in the catalog; a
    genuinely DF-only/future id remains distinct.
    """
    if not item_id.startswith("df-"):
        return item_id
    candidate = _OBSERVED_ITEM_ALIASES.get(item_id, item_id.removeprefix("df-"))
    return candidate if catalog.get_item_id(candidate) is not None else item_id


def canonical_recipe_id(recipe_id: str) -> str:
    """Catalog-backed identity for a FactorioLab recipe id."""
    if not recipe_id.startswith("df-"):
        return recipe_id
    candidate = _OBSERVED_ITEM_ALIASES.get(recipe_id, recipe_id.removeprefix("df-"))
    return candidate if candidate in catalog.known_recipe_ids() else recipe_id


def _canonical_rates(values: Mapping[str, Fraction]) -> Mapping[str, Fraction]:
    merged: dict[str, Fraction] = {}
    for item_id, rate in values.items():
        canonical = canonical_item_id(item_id)
        merged[canonical] = merged.get(canonical, Fraction()) + rate
    return MappingProxyType(merged)


def canonicalize_dataset(data: Dataset) -> Dataset:
    """Return the dataset with alias and canonical production identity merged."""
    items_by_id: dict[str, Item] = {}
    for item in data.items:
        item_id = canonical_item_id(item.id)
        machine = item.machine
        if machine is not None:
            machine = replace(machine, consumption=_canonical_rates(machine.consumption))
        module = item.module
        if module is not None and module.proliferator is not None:
            module = replace(module, proliferator=canonical_item_id(module.proliferator))
        technology = item.technology
        if technology is not None:
            technology = replace(
                technology,
                recipe_unlock=tuple(canonical_recipe_id(r) for r in technology.recipe_unlock),
            )
        normalized_item = replace(
            item,
            id=item_id,
            machine=machine,
            module=module,
            technology=technology,
        )
        if item_id not in items_by_id or item.id == item_id:
            items_by_id[item_id] = normalized_item

    recipes_by_id: dict[str, Recipe] = {}
    for recipe in data.recipes:
        recipe_id = canonical_recipe_id(recipe.id)
        normalized_recipe = replace(
            recipe,
            id=recipe_id,
            inputs=_canonical_rates(recipe.inputs),
            outputs=_canonical_rates(recipe.outputs),
            producers=tuple(canonical_item_id(p) for p in recipe.producers),
        )
        if recipe_id not in recipes_by_id or recipe.id == recipe_id:
            recipes_by_id[recipe_id] = normalized_recipe

    defaults = replace(
        data.defaults,
        excluded_recipes=frozenset(
            canonical_recipe_id(recipe_id) for recipe_id in data.defaults.excluded_recipes
        ),
        min_machine_rank=tuple(canonical_item_id(i) for i in data.defaults.min_machine_rank),
        max_machine_rank=tuple(canonical_item_id(i) for i in data.defaults.max_machine_rank),
        module_rank=tuple(canonical_item_id(i) for i in data.defaults.module_rank),
        fuel_rank=tuple(canonical_item_id(i) for i in data.defaults.fuel_rank),
    )
    return Dataset(
        version=data.version,
        categories=data.categories,
        items=tuple(items_by_id.values()),
        recipes=tuple(recipes_by_id.values()),
        limitations=MappingProxyType(
            {
                name: frozenset(canonical_recipe_id(r) for r in recipes)
                for name, recipes in data.limitations.items()
            }
        ),
        defaults=defaults,
        flags=data.flags,
        icons=data.icons,
    )


def _canonical_mapping[T](values: Mapping[str, T], identity: object) -> dict[str, T]:
    canonical = canonical_item_id if identity == "item" else canonical_recipe_id
    out: dict[str, T] = {}
    for value_id, value in values.items():
        out.setdefault(canonical(value_id), value)
    return out


def _canonical_set(values: set[str] | None, *, recipes: bool = False) -> set[str] | None:
    if values is None:
        return None
    canonical = canonical_recipe_id if recipes else canonical_item_id
    return {canonical(value) for value in values}


def canonicalize_request(request: LabRequest) -> LabRequest:
    """Canonicalize every item/recipe identity carried by a URL request."""
    return replace(
        request,
        objectives=tuple(
            replace(
                objective,
                target_id=(
                    canonical_recipe_id(objective.target_id)
                    if objective.is_recipe_objective
                    else canonical_item_id(objective.target_id)
                ),
            )
            for objective in request.objectives
        ),
        items=_canonical_mapping(request.items, "item"),
        recipes=_canonical_mapping(request.recipes, "recipe"),
        excluded_item_ids=_canonical_set(request.excluded_item_ids),
        checked_item_ids=_canonical_set(request.checked_item_ids),
        excluded_recipe_ids=_canonical_set(request.excluded_recipe_ids, recipes=True),
        checked_recipe_ids=_canonical_set(request.checked_recipe_ids, recipes=True),
        machine_rank_ids=(
            None
            if request.machine_rank_ids is None
            else [canonical_item_id(i) for i in request.machine_rank_ids]
        ),
        fuel_rank_ids=(
            None
            if request.fuel_rank_ids is None
            else [canonical_item_id(i) for i in request.fuel_rank_ids]
        ),
        module_rank_ids=(
            None
            if request.module_rank_ids is None
            else [canonical_item_id(i) for i in request.module_rank_ids]
        ),
        proliferator_spray_id=(
            None
            if request.proliferator_spray_id is None
            else canonical_item_id(request.proliferator_spray_id)
        ),
    )


class FlowError(ValueError):
    """Base class for every refusal in this module.

    Derives from ``ValueError`` so the CLI reports it as a bad input (exit 2)
    rather than as a layout failure.  Every subclass means "refuse"; none of
    them means "carry on without the flow".
    """


class FlowFormatError(FlowError):
    """The file is not a FactorioLab step export, or is damaged."""


class FlowProvenanceError(FlowError):
    """The export was generated from a different URL than the one requested."""


class FlowSelectionError(FlowError):
    """The flow names a recipe this program cannot build."""


#: FactorioLab's ``StepKeys``, verbatim and in emission order.  A header naming
#: anything outside this set is not a step export.
STEP_KEYS: Final = (
    "Item",
    "Items",
    "Surplus",
    "Inputs",
    "Outputs",
    "Targets",
    "Belts",
    "Belt",
    "Wagons",
    "Wagon",
    "Rockets",
    "Recipe",
    "Machines",
    "Machine",
    "Modules",
    "Beacons",
    "Power",
    "Pollution",
)

#: Numeric columns, so a row can record whether ANY of its values lost precision
#: without every caller re-deciding which cells are numbers.
_NUMERIC: Final = (
    "Items",
    "Surplus",
    "Belts",
    "Wagons",
    "Rockets",
    "Machines",
    "Power",
    "Pollution",
)

#: Route segments that select a VIEW of the same solved state.  The download
#: button sits on more than one of them, so the view a player happened to be
#: looking at must not make their own export read as someone else's.
_VIEWS: Final = frozenset({"list", "flow", "wizard", "data"})

#: Mirrors ``rates.solve._SECONDS_PER_PERIOD``.  Duplicated rather than imported
#: to keep ``lab`` free of a dependency on ``rates``; three exact constants that
#: are facts about clocks, not about either module.
_SECONDS_PER_PERIOD: Final[Mapping[DisplayRate, Fraction]] = {
    DisplayRate.PerSecond: Fraction(1),
    DisplayRate.PerMinute: Fraction(60),
    DisplayRate.PerHour: Fraction(3600),
}

_FRACTION = re.compile(r"\A(-?\d+)\s*/\s*(\d+)\Z")
_MIXED = re.compile(r"\A(-?\d+)\s*\+\s*(\d+)\s*/\s*(\d+)\Z")
_DECIMAL = re.compile(r"\A-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?\Z")


@dataclass(frozen=True, slots=True)
class FlowRow:
    """One step of FactorioLab's flow.

    ``item_id`` and ``recipe_id`` are both optional in the source format: a row
    may carry either or both.
    """

    item_id: str = ""
    recipe_id: str = ""
    machine_item_id: str = ""
    belt_item_id: str = ""
    #: ``step.items - step.surplus``: the amount actually CONSUMED by the flow,
    #: in the URL's display rate.  Zero means nothing draws on this item, which
    #: is how a pure byproduct presents.  ``None`` means the column was blank.
    items: Fraction | None = None
    #: ``step.surplus``: produced and unused.  Never a demand.
    surplus: Fraction | None = None
    #: FactorioLab's FRACTIONAL machine count.  Ours is this, rounded up.
    machines: Fraction | None = None
    #: The ``Modules`` cell verbatim.  Deliberately unparsed: nothing here acts
    #: on it, and the one real sample carries a bare ``1`` where the exporter's
    #: own format says ``<count> <module-id>``, so any structure imposed on it
    #: would be a guess that could refuse a valid file.
    modules: str = ""
    #: False when any numeric cell in this row lost precision, which happens
    #: when the file has been round-tripped through a spreadsheet.
    exact: bool = True

    @property
    def is_demand(self) -> bool:
        """Does anything in the flow actually draw on this item?

        ``Items 0 / Surplus 125`` is a byproduct nobody consumes.  Reading that
        as a demand would put a belt of hydrogen into the blueprint's inputs.
        """
        return self.items is not None and self.items > 0


@dataclass(frozen=True, slots=True)
class FlowSelection:
    """A parsed FactorioLab CSV: the flow FactorioLab solved."""

    #: The URL from line 1, exactly as FactorioLab wrote it.
    source_url: str
    rows: tuple[FlowRow, ...]
    #: The header actually present, so a report can say what the file carried.
    columns: tuple[str, ...] = ()

    @property
    def chosen_recipe_ids(self) -> frozenset[str]:
        """Every recipe FactorioLab's flow runs.

        A SET, deliberately, not an item->recipe map.  A recipe is keyed to the
        row of the item it primarily makes, but it also produces that row's
        byproducts -- ``graphene-advanced`` makes graphene *and* hydrogen, and
        the hydrogen row names no recipe at all.  Pinning per item would strike
        out the recipe that supplies the byproduct.
        """
        return frozenset(r.recipe_id for r in self.rows if r.recipe_id)

    @property
    def by_item(self) -> Mapping[str, FlowRow]:
        return {r.item_id: r for r in self.rows if r.item_id}

    @property
    def by_recipe(self) -> Mapping[str, FlowRow]:
        return {r.recipe_id: r for r in self.rows if r.recipe_id}

    @property
    def is_exact(self) -> bool:
        """True when no numeric cell lost precision (a pristine download)."""
        return all(r.exact for r in self.rows)

    def proliferator_modules(self) -> dict[str, str]:
        """Recipe id -> the proliferator module FactorioLab sprays it with.

        The ``Modules`` cell is ``<count> <module-id>`` pairs, comma separated,
        but a real export writes ``"1 "`` -- a count with an EMPTY module id --
        for a machine whose module slot is empty.  So this keys off the *token*
        naming a proliferator rather than off position or on the cell being
        non-blank, which makes it robust to that and to a bare id with no count.

        Only proliferator modules are returned.  A recipe carrying two different
        ones is refused rather than resolved: the export would be stating two
        answers and picking one would be a guess about what the player sprayed.
        """
        out: dict[str, str] = {}
        for row in self.rows:
            if not row.recipe_id or not row.modules:
                continue
            found = {t for t in re.split(r"[,\s]+", row.modules) if "proliferator" in t}
            if len(found) > 1:
                raise FlowFormatError(
                    f"{row.recipe_id!r} names more than one proliferator module "
                    f"({sorted(found)}); the export states no single answer for "
                    "what it sprays"
                )
            if found:
                out[row.recipe_id] = found.pop()
        return out

    @property
    def uses_proliferator(self) -> bool:
        """Does this flow spray at all?

        Decides whether belting proliferator in is a boundary CHANGE or the
        known asymmetry.  FactorioLab builds ``proliferator-2`` from diamond and
        ``proliferator-1``; we belt it in because a spray coater has to be fed
        and we never build it.  That asymmetry is accepted, separately tracked
        work.  But when a flow sprays *nothing*, adding a proliferator input is
        us inventing a demand the player never chose -- a different thing
        entirely, and forbidden.

        Read from the ``Modules`` text rather than from its mere presence: a
        real export writes ``"1 "`` -- a count with an EMPTY module id -- for a
        machine with a module slot and nothing in it.  Testing "is this cell
        non-empty" would read that as proliferated.
        """
        return any(
            "proliferator" in r.modules
            or r.item_id.startswith("proliferator")
            or r.recipe_id.startswith("proliferator")
            for r in self.rows
        )

    def external_items(self, data: Dataset) -> dict[str, Fraction]:
        """Items the flow draws on that are NOT made inside the blueprint.

        Two ways an item gets here, and both are FactorioLab's own statement
        rather than our inference:

        * The row names **no recipe** -- an ``Input`` objective, declared by the
          player as arriving from outside.
        * The row names a recipe we do not build: **mining-flagged** (orbital
          collectors, mining machines, oil extractors, water pumps -- exactly
          the 22 recipes ``solve._buildable_producers`` cuts) or a technology
          recipe, which consumes goods to advance research.
        * A ``df-*`` row names one of FactorioLab's synthetic Dark Fog recipes.
          DSP has neither a machine recipe nor a belt item id for those drops,
          so an explicitly listed row is authoritative only as a source item;
          it never authorizes emitting a synthetic machine.

        Byproducts are excluded: an item with no recipe and no demand is
        surplus, and belting it in would be inventing an input.
        """
        out: dict[str, Fraction] = {}
        for row in self.rows:
            if not row.item_id or not row.is_demand:
                continue
            assert row.items is not None  # is_demand
            if row.item_id.startswith("df-"):
                out[row.item_id] = row.items
                continue
            if not row.recipe_id:
                out[row.item_id] = row.items
                continue
            recipe = data.get_recipe(row.recipe_id)
            if recipe is not None and (recipe.is_mining or recipe.is_technology):
                out[row.item_id] = row.items
        return out


def _split_lines(text: str) -> list[str]:
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _delimiter(header: str) -> str:
    """Comma for a pristine download, tab for a spreadsheet round-trip.

    Decided from the header line, where the field names are known and contain
    neither character, so the choice is unambiguous rather than sniffed.
    """
    if "\t" in header:
        return "\t"
    if "," in header:
        return ","
    raise FlowFormatError(
        f"the header row {header!r} has no comma or tab, so it names a single "
        "column; this is not a FactorioLab step export"
    )


def _number(raw: str, column: str) -> tuple[Fraction, bool] | None:
    """Parse one numeric cell into ``(value, exact)``, or ``None`` if blank.

    Always a ``Fraction``; never a float.  The exactness flag is FactorioLab's
    own rule, read off ``Rational.toString()``: it emits a decimal only when the
    value survives ``toFixed(3)`` unchanged, and an exact ``p/q`` otherwise.  So
    a value finer than a thousandth cannot have come from the exporter -- a
    spreadsheet evaluated an ``=p/q`` formula and wrote the float back.
    """
    text = raw.strip().lstrip("=").strip()
    if not text:
        return None
    if (m := _FRACTION.match(text)) is not None:
        if int(m.group(2)) == 0:
            raise FlowFormatError(f"{column}: {raw!r} divides by zero")
        return Fraction(int(m.group(1)), int(m.group(2))), True
    if (m := _MIXED.match(text)) is not None:
        whole, num, den = (int(g) for g in m.groups())
        if den == 0:
            raise FlowFormatError(f"{column}: {raw!r} divides by zero")
        sign = -1 if whole < 0 else 1
        return Fraction(abs(whole)) * sign + Fraction(num, den) * sign, True
    if _DECIMAL.match(text) is not None:
        value = Fraction(text)  # exact: Fraction parses the decimal, float never touches it
        return value, (value * 1000).denominator == 1
    raise FlowFormatError(
        f"{column}: {raw!r} is not a number FactorioLab writes. Expected an "
        "integer, a short decimal, or an exact 'p/q'."
    )


def parse_flow_csv(text: str) -> FlowSelection:
    """Parse a FactorioLab step export.  Raises :class:`FlowFormatError`.

    Nothing here is lenient about structure.  A file missing its URL line, or
    whose header names a column FactorioLab does not emit, is refused rather
    than parsed as far as it goes -- if the shape is not what we believe it is,
    every value read out of it is a guess.
    """
    lines = _split_lines(text)
    while lines and not lines[-1].strip():
        lines.pop()
    if len(lines) < 2:
        raise FlowFormatError(
            "expected at least a URL line and a header row; a FactorioLab CSV "
            "starts with the URL it was generated from"
        )

    url = lines[0].strip()
    if len(url) >= 2 and url.startswith('"') and url.endswith('"'):
        url = url[1:-1]
    if not url.lower().startswith(("http://", "https://")):
        raise FlowFormatError(
            f"line 1 is {lines[0]!r}, not a URL. FactorioLab writes the page's "
            "own address there, and it is the only provenance this file "
            "carries; without it the flow cannot be attributed to a URL at all."
        )

    reader = csv.reader(io.StringIO("\n".join(lines[1:])), delimiter=_delimiter(lines[1]))
    header = next(reader, None)
    if header is None:  # pragma: no cover - len(lines) >= 2 guarantees a row
        raise FlowFormatError("no header row")
    columns = tuple(c.strip() for c in header)
    unknown = [c for c in columns if c not in STEP_KEYS]
    if unknown:
        raise FlowFormatError(
            f"header names {unknown!r}, which FactorioLab's step export does "
            f"not emit. Known columns are {list(STEP_KEYS)}."
        )
    if "Item" not in columns and "Recipe" not in columns:
        raise FlowFormatError(
            "header carries neither 'Item' nor 'Recipe', so the file states no "
            "recipe selection and there is nothing to pin"
        )

    rows: list[FlowRow] = []
    for lineno, record in enumerate(reader, start=3):
        if not any(field.strip() for field in record):
            continue
        if len(record) > len(columns):
            raise FlowFormatError(
                f"line {lineno} has {len(record)} fields but the header has {len(columns)}"
            )
        # Rows are ragged by design: the exporter stops at the last filled
        # column, so a short row is normal and pads with blanks.
        cell = dict(zip(columns, record, strict=False))
        parsed = {
            name: _number(cell.get(name, ""), f"line {lineno}, column {name}")
            for name in _NUMERIC
        }
        rows.append(
            FlowRow(
                item_id=canonical_item_id(cell.get("Item", "").strip()),
                recipe_id=canonical_recipe_id(cell.get("Recipe", "").strip()),
                machine_item_id=canonical_item_id(cell.get("Machine", "").strip()),
                belt_item_id=canonical_item_id(cell.get("Belt", "").strip()),
                items=None if parsed["Items"] is None else parsed["Items"][0],
                surplus=None if parsed["Surplus"] is None else parsed["Surplus"][0],
                machines=None if parsed["Machines"] is None else parsed["Machines"][0],
                modules=cell.get("Modules", "").strip(),
                exact=all(got[1] for got in parsed.values() if got is not None),
            )
        )

    if not rows:
        raise FlowFormatError("the export has a header but no steps")

    seen: dict[str, int] = {}
    for index, row in enumerate(rows):
        if not row.item_id:
            continue
        if row.item_id in seen:
            raise FlowFormatError(
                f"item {row.item_id!r} appears on two rows ({seen[row.item_id] + 3} "
                f"and {index + 3}). FactorioLab emits one step per item, so the "
                "selection this file states is ambiguous."
            )
        seen[row.item_id] = index
    return FlowSelection(source_url=url, rows=tuple(rows), columns=columns)


def _url_state(url: str) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    """The part of a FactorioLab URL that determines the flow.

    Returns ``(origin, mod path, sorted query pairs)``.  The trailing route
    segment is dropped when it names a view: ``/dsp/list?...`` and
    ``/dsp/flow?...`` are the same solved state seen two ways and the download
    button is reachable from both, so treating them as different would refuse a
    player their own export.  Everything else -- host, mod, and every query
    parameter -- must match.  Parameters are compared as a sorted multiset
    because Angular's router reorders them.
    """
    parts = urlsplit(url.strip())
    query, fragment, path = parts.query, parts.fragment, parts.path
    if not query and "?" in fragment:  # legacy hash routing
        hash_path, _, query = fragment.partition("?")
        path = hash_path.lstrip("#") or path
    segments = [s for s in path.split("/") if s]
    if segments and segments[-1].lower() in _VIEWS:
        segments.pop()
    return (
        f"{parts.scheme.lower()}://{parts.netloc.lower()}",
        "/".join(segments),
        tuple(sorted(parse_qsl(query, keep_blank_values=True))),
    )


def verify_provenance(flow: FlowSelection, url: str) -> None:
    """Refuse an export generated from a different URL.

    Laying out someone else's flow, or a download taken before the player
    changed their settings, produces a blueprint that is internally consistent
    and answers the wrong question -- the silent-wrong-answer class this program
    exists to avoid.  Line 1 is the only direct evidence that the export and the
    URL agree, and it closes the hole a structural check cannot reach: a stale
    export whose recipe selection still happens to parse against the new URL.
    A mismatch names exactly what differs.
    """
    if not url.strip():
        raise FlowProvenanceError(
            "no URL to check this export against, so its provenance cannot be "
            "established; refusing rather than assuming it is the right flow"
        )
    want_origin, want_mod, want_query = _url_state(url)
    got_origin, got_mod, got_query = _url_state(flow.source_url)
    problems: list[str] = []
    if want_origin != got_origin:
        problems.append(f"origin {got_origin!r} != {want_origin!r}")
    if want_mod != got_mod:
        problems.append(f"mod path {got_mod!r} != {want_mod!r}")
    if want_query != got_query:
        want, got = dict(want_query), dict(got_query)
        problems.extend(
            f"parameter {key!r}: export has {got.get(key)!r}, URL has {want.get(key)!r}"
            for key in sorted(set(want) | set(got))
            if want.get(key) != got.get(key)
        )
    if problems:
        raise FlowProvenanceError(
            "this export is for a different URL.\n"
            f"  export line 1: {flow.source_url}\n"
            f"  requested:     {url}\n"
            "  differs in:    " + "; ".join(problems) + "\n"
            "Re-download the CSV from the URL you are building, or pass the URL "
            "the export came from."
        )


def flow_from_text(text: str, *, url: str) -> FlowSelection:
    """Parse a FactorioLab CSV and verify it was generated from ``url``.

    Parsing and provenance are paired in one function so that no caller can
    acquire a :class:`FlowSelection` without the URL check having run.  A
    captured export goes through exactly the same door as a file the user
    downloaded by hand -- driving the browser ourselves is not a reason to trust
    the bytes any less.
    """
    flow = parse_flow_csv(text)
    verify_provenance(flow, url)
    return flow


def load_flow(path: Path, *, url: str) -> FlowSelection:
    """Read a FactorioLab CSV and verify it was generated from ``url``."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise FlowFormatError(f"cannot read flow export {str(path)!r}: {exc}") from exc
    return flow_from_text(text, url=url)


def pinned_exclusions(data: Dataset, flow: FlowSelection) -> frozenset[str]:
    """Every buildable recipe that FactorioLab's flow does NOT run.

    This is the pin, expressed in the one vocabulary the rate solver already
    treats as authoritative.  ``solve._excluded_recipes`` takes the request's
    exclusion set whole and ``_buildable_producers`` then offers the MILP only
    what survives, so excluding the complement of the chosen set leaves exactly
    one producer per item: FactorioLab's.

    Any ``df-*`` id that remains after catalog-backed canonicalization has no
    normal DSP recipe identity. Those synthetic rows stay excluded even when
    chosen; their item names are handled as explicit source provenance by
    :meth:`FlowSelection.external_items`.
    """
    chosen = flow.chosen_recipe_ids
    known = {r.id for r in data.recipes}
    unknown = sorted(chosen - known)
    if unknown:
        raise FlowSelectionError(
            f"the flow runs {unknown!r}, which this dataset does not define. "
            "Either the export came from a different mod, or our vendored "
            "dataset is older than FactorioLab's."
        )
    dark_fog = {recipe.id for recipe in data.recipes if recipe.id.startswith("df-")}
    return frozenset((known - chosen) | dark_fog)


def verify_against_request(flow: FlowSelection, data: Dataset, request: LabRequest) -> None:
    """Structural agreement between the flow and the URL's settings.

    Complements :func:`verify_provenance` rather than replacing it: the URL
    check proves the export came from this address, and these prove the export
    is internally consistent with what the address asks for.  Refuses a flow
    running a recipe the URL EXPLICITLY excludes, one that cannot make what the
    URL asks for, or one that builds an item the URL declares as an ``Input``.

    The mod's DEFAULT exclusions are deliberately not consulted.  Absence is not
    emptiness: a URL that says nothing about recipes leaves us falling back to
    the defaults, and those are our guess at the player's state, not the state
    itself.  The export IS that state, so it outranks the defaults -- and it
    must, since ``graphene-advanced`` and ``fire-ice-vein`` are both
    default-excluded in DSP and both are ordinary player choices.  Checking
    against the defaults here re-created ``60d5f0f`` exactly: our defaults
    overruling a selection the player had made.
    """
    data = canonicalize_dataset(data)
    request = canonicalize_request(request)
    chosen = flow.chosen_recipe_ids
    if request.excluded_recipe_ids is not None:
        forbidden = sorted(chosen & frozenset(request.excluded_recipe_ids))
        if forbidden:
            raise FlowProvenanceError(
                f"the flow runs {forbidden!r}, which this URL's own settings "
                "exclude. The export is stale or came from different settings; "
                "re-download it from the URL you are building."
            )

    producible = {
        item
        for recipe_id in chosen
        if (recipe := data.get_recipe(recipe_id)) is not None and not recipe.is_technology
        for item in recipe.outputs
    }
    wanted = {
        o.target_id
        for o in request.objectives
        if o.type is ObjectiveType.Output and not o.is_recipe_objective
    }
    unreachable = sorted(wanted - producible)
    if unreachable:
        raise FlowProvenanceError(
            f"this URL asks for {unreachable!r}, which the flow does not produce. "
            "The export is for a different objective; re-download it from the URL "
            "you are building."
        )

    supplied = {
        o.target_id
        for o in request.objectives
        if o.type is ObjectiveType.Input and not o.is_recipe_objective
    }
    contradicted = sorted(supplied & producible)
    if contradicted:
        raise FlowProvenanceError(
            f"this URL supplies {contradicted!r} from outside, but the flow builds "
            "it. The export predates that Input objective; re-download it."
        )


def pin_request(request: LabRequest, data: Dataset, flow: FlowSelection) -> LabRequest:
    """Return a canonical request with buildable recipes pinned to ``flow``.

    Verifies first: a flow that cannot be this URL's is refused rather than
    pinned, because pinning it would produce a blueprint that is internally
    consistent and answers the wrong question.

    Catalog-backed ``df-*`` aliases have already become their ordinary DSP
    identities in both the request and flow. A remaining ``df-*`` objective is
    a distinct DF-only source: it must be explicitly named by this flow and is
    removed as a machine output because no catalog recipe can build it.
    """
    data = canonicalize_dataset(data)
    request = canonicalize_request(request)
    verify_against_request(flow, data, request)
    requested_dark_fog = {
        objective.target_id
        for objective in request.objectives
        if objective.type is ObjectiveType.Output and objective.target_id.startswith("df-")
    }
    missing = sorted(requested_dark_fog - set(flow.by_item))
    if missing:
        raise FlowProvenanceError(
            f"this URL requests {missing!r}, but the supplied flow does not explicitly "
            "list those Dark Fog items. A synthetic recipe name is not provenance for "
            "a drop; re-download the flow from this exact URL."
        )
    objectives = tuple(
        objective
        for objective in request.objectives
        if not (
            objective.type is ObjectiveType.Output
            and objective.target_id.startswith("df-")
        )
    )
    return replace(
        request,
        objectives=objectives,
        excluded_recipe_ids=set(pinned_exclusions(data, flow)),
    )


def unsupplied_inputs(
    flow: FlowSelection,
    data: Dataset,
    external_inputs: Mapping[str, Fraction],
    *,
    exempt: frozenset[str] = frozenset(),
) -> tuple[str, ...]:
    """Items we would ask the player to belt in that FactorioLab does not.

    The rule this enforces is the hard one: the inputs and outputs FactorioLab
    chose may never be changed, real or implied.  A blueprint demanding an input
    that appears nowhere in the player's flow is the exact failure that motivated
    pinning -- a flow containing no stone whose blueprint asked for stone.  With
    the selection pinned this must be empty; if it is not, the pin is leaking and
    the caller must refuse rather than ship the belt.
    """
    return tuple(sorted(set(external_inputs) - set(flow.external_items(data)) - exempt))


def cross_check(
    flow: FlowSelection,
    data: Dataset,
    *,
    machines: Mapping[str, int],
    machine_items: Mapping[str, str],
    external_inputs: Mapping[str, Fraction],
    outputs: Mapping[str, Fraction] | None = None,
    display_rate: DisplayRate = DisplayRate.PerMinute,
) -> tuple[str, ...]:
    """Compare our exact solve against FactorioLab's exact numbers.

    This is the check the JSON export could not support, and it is the reason
    the CSV is the supported path: both sides are exact rationals, so a
    disagreement is a real disagreement rather than a rounding artefact.  It is
    a diagnostic and not a gate -- it exists so a divergence gets *named*
    instead of papered over -- with one exception handled by
    :func:`unsupplied_inputs`, which refuses.

    Compared:

    * **machine counts**, our integer against ``ceil(Machines)``.  Rounding up is
      where FactorioLab's fractional count and ours must meet.
    * **the machine chosen**, ours against the ``Machine`` column.
    * **external input rates** and **output rates**, converted out of the URL's
      display rate into items per second.

    Machine counts legitimately differ between our proliferation candidates, so
    the caller must say which candidate it is comparing.  When a row has been
    through a spreadsheet its value is no longer exact, and the comparison says
    so rather than reporting a difference the file cannot actually support.
    """
    findings: list[str] = []
    per_second = _SECONDS_PER_PERIOD[display_rate]
    by_recipe = flow.by_recipe

    for recipe_id, count in sorted(machines.items()):
        row = by_recipe.get(recipe_id)
        if row is None:
            findings.append(f"{recipe_id}: we build {count} machine(s); the flow has no such step")
            continue
        if row.machines is not None:
            want = -((-row.machines.numerator) // row.machines.denominator)  # ceil, exactly
            if want != count:
                findings.append(
                    f"{recipe_id}: {count} machine(s) here, ceil({row.machines}) = "
                    f"{want} in the flow"
                )
        got = machine_items.get(recipe_id, "")
        if row.machine_item_id and got and row.machine_item_id != got:
            findings.append(
                f"{recipe_id}: built in {got!r} here, {row.machine_item_id!r} in the flow"
            )
    for recipe_id in sorted(set(by_recipe) - set(machines)):
        recipe = data.get_recipe(recipe_id)
        if recipe is not None and (recipe.is_mining or recipe.is_technology):
            continue  # extraction happens outside; its output is an input belt
        findings.append(
            f"{recipe_id}: the flow runs {by_recipe[recipe_id].machines} machine(s); "
            "we build none"
        )

    supplied = flow.external_items(data)
    findings.extend(
        _rate_findings(flow, supplied, external_inputs, per_second, "belt in", "uses")
    )
    for item_id in sorted(set(supplied) - set(external_inputs)):
        findings.append(
            f"{item_id}: the flow belts in {supplied[item_id]} but this build needs none"
        )
    if outputs is not None:
        wanted = {
            r.item_id: r.items
            for r in flow.rows
            if r.item_id and r.items is not None and r.item_id in outputs
        }
        findings.extend(_rate_findings(flow, wanted, outputs, per_second, "deliver", "delivers"))
    return tuple(findings)


def _rate_findings(
    flow: FlowSelection,
    theirs: Mapping[str, Fraction],
    ours: Mapping[str, Fraction],
    per_second: Fraction,
    verb: str,
    their_verb: str,
) -> list[str]:
    """Name each item whose rate we and the flow disagree on.

    Exact when the row survived intact.  A row a spreadsheet has mangled cannot
    settle a disagreement either way, so it is reported as unverifiable rather
    than compared -- a check that silently degrades to "close enough" is how a
    rate defect ships.
    """
    out: list[str] = []
    for item_id, period_rate in sorted(theirs.items()):
        mine = ours.get(item_id)
        if mine is None:
            continue
        want = period_rate / per_second
        if want == mine:
            continue
        row = flow.by_item.get(item_id)
        if row is not None and not row.exact:
            out.append(
                f"{item_id}: we {verb} {mine}/s against ~{want}/s in the flow, but that "
                "row lost precision in a spreadsheet, so the difference cannot be "
                "confirmed from this file"
            )
        else:
            out.append(f"{item_id}: we {verb} {mine}/s; the flow {their_verb} {want}/s")
    return out
