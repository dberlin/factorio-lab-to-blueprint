"""Per-machine recipe arithmetic, mirroring FactorioLab's ``adjustRecipe``.

Everything here is exact ``Fraction`` arithmetic.  The one asymmetry worth
holding in mind is that proliferator *productivity* scales a recipe's outputs
but leaves its inputs alone -- which is precisely why products mode compounds
all the way up a chain, while speed mode saves machines only at its own step.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from functools import cache
from types import MappingProxyType

from flab2bp.dsp import catalog
from flab2bp.lab.schema import Dataset, Recipe
from flab2bp.spec import ProliferatorMode


class ProliferatorTier(Enum):
    """Which proliferator the build is allowed to use, if any."""

    NONE = "none"
    MK1 = "1"
    MK2 = "2"
    MK3 = "3"

    @property
    def sprayed_item_id(self) -> str | None:
        """The item consumed by spray coaters -- belted in, never built here."""
        return None if self is ProliferatorTier.NONE else f"proliferator-{self.value}"

    def module_id(self, mode: ProliferatorMode) -> str | None:
        if self is ProliferatorTier.NONE or mode is ProliferatorMode.NONE:
            return None
        return f"proliferator-{self.value}-{mode.value}"


@dataclass(frozen=True, slots=True)
class AdjustedRecipe:
    """One recipe as run by one machine under one proliferator setting."""

    recipe_id: str
    machine_item_id: str
    mode: ProliferatorMode
    tier: ProliferatorTier
    #: Seconds one machine takes per craft, after machine speed and speed-mode.
    craft_time: Fraction
    inputs_per_craft: Mapping[str, Fraction]
    outputs_per_craft: Mapping[str, Fraction]
    #: Proliferator items consumed per craft by the coaters spraying this
    #: recipe's inputs.  Zero when unproliferated.
    proliferator_per_craft: Fraction
    proliferator_item_id: str | None

    @property
    def crafts_per_second(self) -> Fraction:
        return 1 / self.craft_time

    def input_rate(self, item_id: str) -> Fraction:
        """Items/second one machine consumes of ``item_id``."""
        return self.inputs_per_craft.get(item_id, Fraction(0)) / self.craft_time

    def output_rate(self, item_id: str) -> Fraction:
        """Items/second one machine produces of ``item_id``."""
        return self.outputs_per_craft.get(item_id, Fraction(0)) / self.craft_time

    def net_rate(self, item_id: str) -> Fraction:
        return self.output_rate(item_id) - self.input_rate(item_id)

    @property
    def proliferator_rate(self) -> Fraction:
        """Items/second of proliferator one machine's coaters draw."""
        return self.proliferator_per_craft / self.craft_time

    @property
    def footprint_area(self) -> int:
        return machine_footprint(self.machine_item_id)


def select_machine(
    data: Dataset,
    recipe: Recipe,
    rank: tuple[str, ...] | list[str] | None,
    override: str | None = None,
) -> str:
    """FactorioLab's ``bestMatch``: first ranked producer, else ``producers[0]``."""
    if override and override in recipe.producers:
        return override
    for machine_id in rank or ():
        if machine_id in recipe.producers:
            return machine_id
    if not recipe.producers:
        raise ValueError(f"recipe {recipe.id!r} has no producers")
    return recipe.producers[0]


def available_modes(
    data: Dataset, recipe: Recipe, tier: ProliferatorTier
) -> tuple[ProliferatorMode, ...]:
    """Which proliferator modes this recipe may legally run at ``tier``.

    Speed mode carries no ``limitation`` and is always legal.  Products mode is
    gated by the dataset's ``limitations.productivity`` whitelist -- 26
    non-technology recipes are speed-only, and ignoring the gate produces a
    build that silently under-produces.
    """
    if tier is ProliferatorTier.NONE:
        return (ProliferatorMode.NONE,)
    modes = [ProliferatorMode.NONE, ProliferatorMode.SPEED]
    if recipe.id in data.limitation("productivity"):
        modes.insert(1, ProliferatorMode.PRODUCTS)
    return tuple(modes)


def adjust(
    data: Dataset,
    recipe: Recipe,
    machine_item_id: str,
    mode: ProliferatorMode = ProliferatorMode.NONE,
    tier: ProliferatorTier = ProliferatorTier.NONE,
) -> AdjustedRecipe:
    """Compute one machine's exact per-craft and per-second behaviour."""
    machine = data.machine(machine_item_id)
    speed = machine.speed if machine.speed is not None else Fraction(1)

    speed_bonus = Fraction(0)
    productivity_bonus = Fraction(0)
    sprays = 0
    module_id = tier.module_id(mode)
    if module_id is not None:
        module = data.module(module_id)
        speed_bonus = module.speed or Fraction(0)
        productivity_bonus = module.productivity or Fraction(0)
        sprays = module.sprays or 0

    craft_time = recipe.time / (speed * (1 + speed_bonus))

    inputs = {k: Fraction(v) for k, v in recipe.inputs.items()}
    # Productivity scales outputs only.  Inputs are deliberately untouched.
    outputs = {k: Fraction(v) * (1 + productivity_bonus) for k, v in recipe.outputs.items()}

    proliferator_per_craft = Fraction(0)
    proliferator_item_id: str | None = None
    if module_id is not None and sprays:
        # One spray per input item; one proliferator unit supplies `sprays`.
        proliferator_per_craft = sum(inputs.values(), Fraction(0)) / sprays
        proliferator_item_id = tier.sprayed_item_id

    return AdjustedRecipe(
        recipe_id=recipe.id,
        machine_item_id=machine_item_id,
        mode=mode,
        tier=tier,
        craft_time=craft_time,
        inputs_per_craft=MappingProxyType(inputs),
        outputs_per_craft=MappingProxyType(outputs),
        proliferator_per_craft=proliferator_per_craft,
        proliferator_item_id=proliferator_item_id,
    )


# --- footprints ------------------------------------------------------------
#
# FactorioLab identifies machines by string id; the extracted DSP catalog is
# keyed by numeric item id.  Display names bridge the two, which resolves every
# machine in the dataset except `ray-receiver-pro`, a settings variant of the
# Ray Receiver building rather than a building of its own.

_NAME_ALIASES = {"ray-receiver-pro": "ray-receiver"}


@cache
def _footprints_by_lab_id() -> Mapping[str, int]:
    from flab2bp.lab.data import load_dataset

    data = load_dataset()
    by_name = {b.name.lower(): b for b in catalog.all_buildings()}
    out: dict[str, int] = {}
    for item in data.iter_items():
        if item.machine is None:
            continue
        lookup_id = _NAME_ALIASES.get(item.id, item.id)
        name = data.item(lookup_id).name.lower()
        building = by_name.get(name)
        if building is not None:
            out[item.id] = building.width * building.height
    return MappingProxyType(out)


def machine_footprint(machine_item_id: str) -> int:
    """Build-grid area in tiles.

    Area rather than machine count is the solve's objective because the two
    disagree: an arc smelter is 9 tiles and an assembler 16, so a plan with
    fewer machines can occupy more ground.
    """
    return _footprints_by_lab_id().get(machine_item_id, 0)
