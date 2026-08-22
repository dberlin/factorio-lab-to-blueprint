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
from typing import Any

Number = Fraction


def _frac(value: Any) -> Fraction | None:
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


def _frac_map(value: Any) -> Mapping[str, Fraction]:
    if not value:
        return MappingProxyType({})
    out: dict[str, Fraction] = {}
    for k, v in value.items():
        parsed = _frac(v)
        if parsed is not None:
            out[k] = parsed
    return MappingProxyType(out)


def _tuple(value: Any) -> tuple[str, ...]:
    return tuple(value) if value else ()


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

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> Machine:
        return cls(
            speed=_frac(raw.get("speed")),
            usage=_frac(raw.get("usage")),
            drain=_frac(raw.get("drain")),
            consumption=_frac_map(raw.get("consumption")),
            type=raw.get("type"),
            modules=raw.get("modules"),
            total_recipe=bool(raw.get("totalRecipe", False)),
            fuel_categories=_tuple(raw.get("fuelCategories")),
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
    def parse(cls, item_id: str, raw: Mapping[str, Any]) -> Module:
        return cls(
            id=item_id,
            productivity=_frac(raw.get("productivity")),
            speed=_frac(raw.get("speed")),
            consumption=_frac(raw.get("consumption")),
            sprays=raw.get("sprays"),
            proliferator=raw.get("proliferator"),
            limitation=raw.get("limitation"),
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
    def parse(cls, raw: Mapping[str, Any]) -> Belt:
        speed = _frac(raw.get("speed"))
        return cls(speed=speed if speed is not None else Fraction(0))


@dataclass(frozen=True, slots=True)
class Fuel:
    category: str | None = None
    value: Fraction | None = None

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> Fuel:
        return cls(category=raw.get("category"), value=_frac(raw.get("value")))


@dataclass(frozen=True, slots=True)
class Technology:
    prerequisites: tuple[str, ...] = ()
    recipe_unlock: tuple[str, ...] = ()

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> Technology:
        return cls(
            prerequisites=_tuple(raw.get("prerequisites")),
            recipe_unlock=_tuple(raw.get("recipeUnlock")),
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
    def parse(cls, raw: Mapping[str, Any]) -> Item:
        item_id = raw["id"]
        return cls(
            id=item_id,
            name=raw.get("name", item_id),
            category=raw.get("category"),
            row=raw.get("row"),
            stack=raw.get("stack"),
            icon=raw.get("icon"),
            machine=Machine.parse(raw["machine"]) if raw.get("machine") else None,
            module=Module.parse(item_id, raw["module"]) if raw.get("module") else None,
            belt=Belt.parse(raw["belt"]) if raw.get("belt") else None,
            fuel=Fuel.parse(raw["fuel"]) if raw.get("fuel") else None,
            technology=Technology.parse(raw["technology"]) if raw.get("technology") else None,
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
    def parse(cls, raw: Mapping[str, Any]) -> Recipe:
        recipe_id = raw["id"]
        time = _frac(raw.get("time"))
        return cls(
            id=recipe_id,
            name=raw.get("name", recipe_id),
            time=time if time is not None else Fraction(0),
            inputs=_frac_map(raw.get("in")),
            outputs=_frac_map(raw.get("out")),
            producers=_tuple(raw.get("producers")),
            category=raw.get("category"),
            row=raw.get("row"),
            flags=frozenset(raw.get("flags") or ()),
            icon=raw.get("icon"),
            usage=_frac(raw.get("usage")),
            cost=_frac(raw.get("cost")),
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
    def parse(cls, raw: Mapping[str, Any]) -> Category:
        return cls(id=raw["id"], name=raw.get("name", raw["id"]), icon=raw.get("icon"))


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
    def parse(cls, raw: Mapping[str, Any]) -> Defaults:
        return cls(
            excluded_recipes=frozenset(raw.get("excludedRecipes") or ()),
            min_belt=raw.get("minBelt"),
            max_belt=raw.get("maxBelt"),
            min_machine_rank=_tuple(raw.get("minMachineRank")),
            max_machine_rank=_tuple(raw.get("maxMachineRank")),
            module_rank=_tuple(raw.get("moduleRank")),
            fuel_rank=_tuple(raw.get("fuelRank")),
            mod_ids=_tuple(raw.get("modIds")),
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
    def parse(cls, raw: Mapping[str, Any]) -> HashIndex:
        def col(key: str) -> tuple[str | None, ...]:
            return tuple(raw.get(key) or ())

        return cls(
            items=col("items"),
            beacons=col("beacons"),
            belts=col("belts"),
            fuels=col("fuels"),
            wagons=col("wagons"),
            machines=col("machines"),
            modules=col("modules"),
            recipes=col("recipes"),
            technologies=col("technologies"),
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
    icons: tuple[Mapping[str, Any], ...] = ()

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
    def parse(cls, raw: Mapping[str, Any]) -> Dataset:
        limitations = {
            name: frozenset(ids or ()) for name, ids in (raw.get("limitations") or {}).items()
        }
        return cls(
            version=MappingProxyType(dict(raw.get("version") or {})),
            categories=tuple(Category.parse(c) for c in raw.get("categories") or ()),
            items=tuple(Item.parse(i) for i in raw.get("items") or ()),
            recipes=tuple(Recipe.parse(r) for r in raw.get("recipes") or ()),
            limitations=MappingProxyType(limitations),
            defaults=Defaults.parse(raw.get("defaults") or {}),
            flags=frozenset(raw.get("flags") or ()),
            icons=tuple(raw.get("icons") or ()),
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
    "Item",
    "Machine",
    "Module",
    "Recipe",
    "Technology",
)
