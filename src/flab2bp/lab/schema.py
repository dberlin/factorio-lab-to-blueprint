"""Typed view over the FactorioLab dataset (``data.json``).

Two decisions worth knowing about:

**Exact arithmetic.**  Every quantity that feeds rate maths is a
:class:`~fractions.Fraction`, never a float.  ``data.json`` is full of decimals
like ``0.32`` and ``1.2`` that have no exact binary representation, and
FactorioLab itself computes in BigInt rationals.  Parsing goes through
``json.loads(..., parse_float=Fraction)`` so the decimal literal in the file
becomes the exact rational it denotes -- ``0.32`` is ``8/25``, not
``0.32000000000000001``.

**Lenient parsing.**  Unknown keys are ignored and absent optional sub-objects
become ``None``, so a dataset refresh that adds fields cannot break the loader.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from types import MappingProxyType
from typing import Final, TypedDict

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

type RawNumber = Fraction | int | float | str


class _RawModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)


class _RawMachine(_RawModel):
    speed: RawNumber | None = None
    usage: RawNumber | None = None
    drain: RawNumber | None = None
    consumption: dict[str, RawNumber] | None = None
    type: str | None = None
    modules: int | None = None
    total_recipe: bool = Field(False, alias="totalRecipe")
    fuel_categories: list[str] | None = Field(None, alias="fuelCategories")
    size: list[int] | None = None


class _RawModule(_RawModel):
    productivity: RawNumber | None = None
    speed: RawNumber | None = None
    consumption: RawNumber | None = None
    sprays: int | None = None
    proliferator: str | None = None
    limitation: str | None = None


class _RawBelt(_RawModel):
    speed: RawNumber | None = None


class _RawFuel(_RawModel):
    category: str | None = None
    value: RawNumber | None = None


class _RawTechnology(_RawModel):
    prerequisites: list[str] | None = None
    recipe_unlock: list[str] | None = Field(None, alias="recipeUnlock")


class _RawItem(_RawModel):
    id: str
    name: str | None = None
    category: str | None = None
    row: int | None = None
    stack: int | None = None
    icon: str | None = None
    machine: _RawMachine | None = None
    module: _RawModule | None = None
    belt: _RawBelt | None = None
    fuel: _RawFuel | None = None
    technology: _RawTechnology | None = None


class _RawRecipe(_RawModel):
    id: str
    name: str | None = None
    time: RawNumber | None = None
    inputs: dict[str, RawNumber] | None = Field(None, alias="in")
    outputs: dict[str, RawNumber] | None = Field(None, alias="out")
    producers: list[str] | None = None
    category: str | None = None
    row: int | None = None
    flags: list[str] | None = None
    icon: str | None = None
    usage: RawNumber | None = None
    cost: RawNumber | None = None


class _RawCategory(_RawModel):
    id: str
    name: str | None = None
    icon: str | None = None


class _RawDefaults(_RawModel):
    excluded_recipes: list[str] | None = Field(None, alias="excludedRecipes")
    min_belt: str | None = Field(None, alias="minBelt")
    max_belt: str | None = Field(None, alias="maxBelt")
    min_machine_rank: list[str] | None = Field(None, alias="minMachineRank")
    max_machine_rank: list[str] | None = Field(None, alias="maxMachineRank")
    module_rank: list[str] | None = Field(None, alias="moduleRank")
    fuel_rank: list[str] | None = Field(None, alias="fuelRank")
    mod_ids: list[str] | None = Field(None, alias="modIds")


class _RawHashIndex(_RawModel):
    items: list[str | None] | None = None
    beacons: list[str | None] | None = None
    belts: list[str | None] | None = None
    fuels: list[str | None] | None = None
    wagons: list[str | None] | None = None
    machines: list[str | None] | None = None
    modules: list[str | None] | None = None
    recipes: list[str | None] | None = None
    technologies: list[str | None] | None = None


class _RawIcon(_RawModel):
    id: str
    x: int
    y: int
    color: str


class _RawDataset(_RawModel):
    version: dict[str, str] | None = None
    categories: list[_RawCategory] | None = None
    items: list[_RawItem] | None = None
    recipes: list[_RawRecipe] | None = None
    limitations: dict[str, list[str] | None] | None = None
    defaults: _RawDefaults | None = None
    flags: list[str] | None = None
    icons: list[_RawIcon] | None = None


_DATASET_ADAPTER: Final[TypeAdapter[_RawDataset]] = TypeAdapter(_RawDataset)
_HASH_INDEX_ADAPTER: Final[TypeAdapter[_RawHashIndex]] = TypeAdapter(_RawHashIndex)

Number = Fraction


def _frac(value: RawNumber | None) -> Fraction | None:
    """Coerce a parsed JSON number to an exact ``Fraction``."""
    if value is None:
        return None
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, (str, float)):
        # Only reachable if a caller bypasses parse_float=Fraction.
        return Fraction(str(value))
    raise TypeError(f"expected a number, got {type(value).__name__}: {value!r}")


def _frac_map(value: Mapping[str, RawNumber] | None) -> Mapping[str, Fraction]:
    if not value:
        return MappingProxyType({})
    out: dict[str, Fraction] = {}
    for key, raw_number in value.items():
        parsed = _frac(raw_number)
        if parsed is not None:
            out[key] = parsed
    return MappingProxyType(out)


def _tuple(value: Sequence[str] | None) -> tuple[str, ...]:
    return tuple(value) if value else ()


class IconData(TypedDict):
    id: str
    x: int
    y: int
    color: str


def _icon(raw: _RawIcon) -> IconData:
    return {"id": raw.id, "x": raw.x, "y": raw.y, "color": raw.color}


# ---------------------------------------------------------------------------
# Item sub-objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Machine:
    """The ``machine`` sub-object: something that can run recipes.

    ``total_recipe`` marks the mining machines, whose "recipe" is really a
    whole-vein aggregate rather than a per-craft cycle.

    ``consumption`` is a *map* of item id to units consumed per second, not a
    scalar -- it exists only on ``ray-receiver-pro``, which burns graviton
    lenses while it runs.
    """

    speed: Fraction | None = None
    usage: Fraction | None = None
    drain: Fraction | None = None
    consumption: Mapping[str, Fraction] = MappingProxyType({})
    type: str | None = None
    modules: int | None = None
    total_recipe: bool = False
    fuel_categories: tuple[str, ...] = ()
    #: FactorioLab's ``machine.size`` (width, height) in tiles, used by its
    #: ``adjustCosts`` to scale the machine cost.  No DSP machine declares one,
    #: so for this dataset every machine costs exactly ``costs.machine``.
    size: tuple[int, int] | None = None

    @classmethod
    def parse(cls, raw: _RawMachine) -> Machine:
        size: tuple[int, int] | None = None
        if raw.size is not None:
            if len(raw.size) != 2:
                raise ValueError(f"machine size must be [width, height], got {raw.size!r}")
            size = (raw.size[0], raw.size[1])
        return cls(
            speed=_frac(raw.speed),
            usage=_frac(raw.usage),
            drain=_frac(raw.drain),
            consumption=_frac_map(raw.consumption),
            type=raw.type,
            modules=raw.modules,
            total_recipe=raw.total_recipe,
            fuel_categories=_tuple(raw.fuel_categories),
            size=size,
        )


@dataclass(frozen=True, slots=True)
class Module:
    """A proliferator effect.

    Each proliferator tier appears twice, once as ``-products`` (carrying
    ``productivity``) and once as ``-speed`` (carrying ``speed``).  Only the
    productivity variants set ``limitation``, which names the whitelist of
    recipes they may be applied to; speed variants apply universally.

    ``sprays`` is how many item-sprays one unit of the underlying
    ``proliferator`` item provides, and therefore sets the proliferator input
    belt's rate.
    """

    id: str
    productivity: Fraction | None = None
    speed: Fraction | None = None
    consumption: Fraction | None = None
    sprays: int | None = None
    proliferator: str | None = None
    limitation: str | None = None

    @classmethod
    def parse(cls, item_id: str, raw: _RawModule) -> Module:
        return cls(
            id=item_id,
            productivity=_frac(raw.productivity),
            speed=_frac(raw.speed),
            consumption=_frac(raw.consumption),
            sprays=raw.sprays,
            proliferator=raw.proliferator,
            limitation=raw.limitation,
        )

    @property
    def is_productivity(self) -> bool:
        return self.productivity is not None

    @property
    def is_speed(self) -> bool:
        return self.speed is not None


@dataclass(frozen=True, slots=True)
class Belt:
    speed: Fraction

    @classmethod
    def parse(cls, raw: _RawBelt) -> Belt:
        speed = _frac(raw.speed)
        return cls(speed=speed if speed is not None else Fraction(0))


@dataclass(frozen=True, slots=True)
class Fuel:
    category: str | None = None
    value: Fraction | None = None

    @classmethod
    def parse(cls, raw: _RawFuel) -> Fuel:
        return cls(category=raw.category, value=_frac(raw.value))


@dataclass(frozen=True, slots=True)
class Technology:
    prerequisites: tuple[str, ...] = ()
    recipe_unlock: tuple[str, ...] = ()

    @classmethod
    def parse(cls, raw: _RawTechnology) -> Technology:
        return cls(
            prerequisites=_tuple(raw.prerequisites),
            recipe_unlock=_tuple(raw.recipe_unlock),
        )


# ---------------------------------------------------------------------------
# Top-level records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Item:
    id: str
    name: str
    category: str | None = None
    row: int | None = None
    stack: int | None = None
    icon: str | None = None
    machine: Machine | None = None
    module: Module | None = None
    belt: Belt | None = None
    fuel: Fuel | None = None
    technology: Technology | None = None

    @classmethod
    def parse(cls, raw: _RawItem) -> Item:
        return cls(
            id=raw.id,
            name=raw.name if raw.name is not None else raw.id,
            category=raw.category,
            row=raw.row,
            stack=raw.stack,
            icon=raw.icon,
            machine=Machine.parse(raw.machine) if raw.machine is not None else None,
            module=Module.parse(raw.id, raw.module) if raw.module is not None else None,
            belt=Belt.parse(raw.belt) if raw.belt is not None else None,
            fuel=Fuel.parse(raw.fuel) if raw.fuel is not None else None,
            technology=(Technology.parse(raw.technology) if raw.technology is not None else None),
        )


@dataclass(frozen=True, slots=True)
class Recipe:
    id: str
    name: str
    time: Fraction
    inputs: Mapping[str, Fraction]
    outputs: Mapping[str, Fraction]
    producers: tuple[str, ...]
    category: str | None = None
    row: int | None = None
    flags: frozenset[str] = frozenset()
    icon: str | None = None
    usage: Fraction | None = None
    cost: Fraction | None = None

    @classmethod
    def parse(cls, raw: _RawRecipe) -> Recipe:
        time = _frac(raw.time)
        return cls(
            id=raw.id,
            name=raw.name if raw.name is not None else raw.id,
            time=time if time is not None else Fraction(0),
            inputs=_frac_map(raw.inputs),
            outputs=_frac_map(raw.outputs),
            producers=_tuple(raw.producers),
            category=raw.category,
            row=raw.row,
            flags=frozenset(raw.flags or ()),
            icon=raw.icon,
            usage=_frac(raw.usage),
            cost=_frac(raw.cost),
        )

    @property
    def is_mining(self) -> bool:
        """Mined/pumped/collected from the world rather than crafted.

        This is the cut line for blueprint generation: mining recipes are not
        built, their products arrive on input belts instead.
        """
        return "mining" in self.flags

    @property
    def is_technology(self) -> bool:
        return "technology" in self.flags

    @property
    def is_locked(self) -> bool:
        return "locked" in self.flags


@dataclass(frozen=True, slots=True)
class Category:
    id: str
    name: str
    icon: str | None = None

    @classmethod
    def parse(cls, raw: _RawCategory) -> Category:
        return cls(
            id=raw.id,
            name=raw.name if raw.name is not None else raw.id,
            icon=raw.icon,
        )


@dataclass(frozen=True, slots=True)
class Defaults:
    """The ``defaults`` block, which for DSP stands in for a ``defaults.json``."""

    excluded_recipes: frozenset[str] = frozenset()
    min_belt: str | None = None
    max_belt: str | None = None
    min_machine_rank: tuple[str, ...] = ()
    max_machine_rank: tuple[str, ...] = ()
    module_rank: tuple[str, ...] = ()
    fuel_rank: tuple[str, ...] = ()
    mod_ids: tuple[str, ...] = ()

    @classmethod
    def parse(cls, raw: _RawDefaults | None) -> Defaults:
        if raw is None:
            return cls()
        return cls(
            excluded_recipes=frozenset(raw.excluded_recipes or ()),
            min_belt=raw.min_belt,
            max_belt=raw.max_belt,
            min_machine_rank=_tuple(raw.min_machine_rank),
            max_machine_rank=_tuple(raw.max_machine_rank),
            module_rank=_tuple(raw.module_rank),
            fuel_rank=_tuple(raw.fuel_rank),
            mod_ids=_tuple(raw.mod_ids),
        )


@dataclass(frozen=True, slots=True)
class HashIndex:
    """``hash.json`` -- id lists indexed by the compact ids used in ``z=`` URLs.

    Holes (``None``) are preserved: the index of an id is its identity, so
    dropping holes would silently renumber everything downstream.
    """

    items: tuple[str | None, ...] = ()
    beacons: tuple[str | None, ...] = ()
    belts: tuple[str | None, ...] = ()
    fuels: tuple[str | None, ...] = ()
    wagons: tuple[str | None, ...] = ()
    machines: tuple[str | None, ...] = ()
    modules: tuple[str | None, ...] = ()
    recipes: tuple[str | None, ...] = ()
    technologies: tuple[str | None, ...] = ()

    @classmethod
    def parse(cls, raw: object) -> HashIndex:
        parsed = _HASH_INDEX_ADAPTER.validate_python(raw)
        return cls(
            items=tuple(parsed.items or ()),
            beacons=tuple(parsed.beacons or ()),
            belts=tuple(parsed.belts or ()),
            fuels=tuple(parsed.fuels or ()),
            wagons=tuple(parsed.wagons or ()),
            machines=tuple(parsed.machines or ()),
            modules=tuple(parsed.modules or ()),
            recipes=tuple(parsed.recipes or ()),
            technologies=tuple(parsed.technologies or ()),
        )


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Dataset:
    """The whole DSP dataset, with lookup indexes built once at construction."""

    version: Mapping[str, str]
    categories: tuple[Category, ...]
    items: tuple[Item, ...]
    recipes: tuple[Recipe, ...]
    limitations: Mapping[str, frozenset[str]]
    defaults: Defaults
    flags: frozenset[str]
    icons: tuple[IconData, ...] = ()

    _items_by_id: Mapping[str, Item] = field(init=False, repr=False, compare=False)
    _recipes_by_id: Mapping[str, Recipe] = field(init=False, repr=False, compare=False)
    _producers: Mapping[str, tuple[Recipe, ...]] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        producers: dict[str, list[Recipe]] = {}
        for recipe in self.recipes:
            for item_id in recipe.outputs:
                producers.setdefault(item_id, []).append(recipe)

        object.__setattr__(self, "_items_by_id", MappingProxyType({i.id: i for i in self.items}))
        object.__setattr__(
            self, "_recipes_by_id", MappingProxyType({r.id: r for r in self.recipes})
        )
        object.__setattr__(
            self,
            "_producers",
            MappingProxyType({k: tuple(v) for k, v in producers.items()}),
        )

    # -- construction -------------------------------------------------------

    @classmethod
    def parse(cls, raw: object) -> Dataset:
        parsed = _DATASET_ADAPTER.validate_python(raw)
        limitations = {
            name: frozenset(ids or ()) for name, ids in (parsed.limitations or {}).items()
        }
        return cls(
            version=MappingProxyType(dict(parsed.version or {})),
            categories=tuple(Category.parse(category) for category in parsed.categories or ()),
            items=tuple(Item.parse(item) for item in parsed.items or ()),
            recipes=tuple(Recipe.parse(recipe) for recipe in parsed.recipes or ()),
            limitations=MappingProxyType(limitations),
            defaults=Defaults.parse(parsed.defaults),
            flags=frozenset(parsed.flags or ()),
            icons=tuple(_icon(icon) for icon in parsed.icons or ()),
        )

    # -- lookups ------------------------------------------------------------

    def item(self, item_id: str) -> Item:
        try:
            return self._items_by_id[item_id]
        except KeyError:
            raise KeyError(f"unknown item id: {item_id!r}") from None

    def get_item(self, item_id: str) -> Item | None:
        return self._items_by_id.get(item_id)

    def recipe(self, recipe_id: str) -> Recipe:
        try:
            return self._recipes_by_id[recipe_id]
        except KeyError:
            raise KeyError(f"unknown recipe id: {recipe_id!r}") from None

    def get_recipe(self, recipe_id: str) -> Recipe | None:
        return self._recipes_by_id.get(recipe_id)

    def machine(self, item_id: str) -> Machine:
        """The machine profile of an item, e.g. ``assembling-machine-2``."""
        machine = self.item(item_id).machine
        if machine is None:
            raise KeyError(f"item {item_id!r} is not a machine")
        return machine

    def get_machine(self, item_id: str) -> Machine | None:
        item = self.get_item(item_id)
        return item.machine if item else None

    def module(self, item_id: str) -> Module:
        module = self.item(item_id).module
        if module is None:
            raise KeyError(f"item {item_id!r} is not a module")
        return module

    def belt_speed(self, item_id: str) -> Fraction:
        """Belt throughput in items/second."""
        belt = self.item(item_id).belt
        if belt is None:
            raise KeyError(f"item {item_id!r} is not a belt")
        return belt.speed

    def limitation(self, name: str) -> frozenset[str]:
        """The recipe whitelist a limited module may be applied to."""
        return self.limitations.get(name, frozenset())

    # -- derived views ------------------------------------------------------

    @property
    def default_recipe_excluded(self) -> frozenset[str]:
        return self.defaults.excluded_recipes

    @property
    def module_ids(self) -> tuple[str, ...]:
        return tuple(i.id for i in self.items if i.module is not None)

    @property
    def machine_ids(self) -> tuple[str, ...]:
        return tuple(i.id for i in self.items if i.machine is not None)

    @property
    def belt_ids(self) -> tuple[str, ...]:
        return tuple(i.id for i in self.items if i.belt is not None)

    def recipes_producing(self, item_id: str) -> list[Recipe]:
        """Every recipe with ``item_id`` in its outputs, excluded or not.

        Filtering is left to the caller so this stays a neutral index; use
        :attr:`default_recipe_excluded` and :attr:`Recipe.is_technology` to
        narrow it.
        """
        return list(self._producers.get(item_id, ()))

    def craftable_recipes_producing(self, item_id: str) -> list[Recipe]:
        """Producers that a solver may actually choose.

        Drops the dataset's default exclusions and technology recipes, which
        consume items to advance research rather than producing goods.
        """
        excluded = self.default_recipe_excluded
        return [
            r
            for r in self._producers.get(item_id, ())
            if r.id not in excluded and not r.is_technology
        ]

    def items_with_multiple_producers(self) -> dict[str, tuple[str, ...]]:
        """Items whose production genuinely needs a linear program.

        For DSP this is a short list -- everything else is a unique-producer
        DAG that a plain recursive walk resolves exactly.
        """
        out: dict[str, tuple[str, ...]] = {}
        for item in self.items:
            recipes = self.craftable_recipes_producing(item.id)
            if len(recipes) > 1:
                out[item.id] = tuple(r.id for r in recipes)
        return out

    def mining_recipes(self) -> tuple[Recipe, ...]:
        """The raw-input cut line: recipes whose product comes from the world."""
        return tuple(r for r in self.recipes if r.is_mining)

    def iter_items(self) -> Iterable[Item]:
        return iter(self.items)


__all__: Sequence[str] = (
    "Belt",
    "Category",
    "Dataset",
    "Defaults",
    "Fuel",
    "HashIndex",
    "IconData",
    "Item",
    "Machine",
    "Module",
    "Recipe",
    "Technology",
)
