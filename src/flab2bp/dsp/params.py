"""Parameter blocks for machines configured by a MODE rather than a recipe.

Most DSP machines are told what to make through ``recipe_id``.  A few are not:
their job is selected by a word in the building's ``parameters`` block, and
``recipe_id`` stays zero.  FactorioLab still models these as ordinary recipes
with real item flow, so they belt, sort and lay out like anything else -- only
the emission differs.

``BuildingParameters.ToParamsArray`` branches once per building type and fixes
both the word count and the layout.  The two types that matter here:

===============  =====  ==========================================
BuildingType     words  contents
===============  =====  ==========================================
``Exchanger``    1      ``[0]`` ``targetState``
``Gamma``        1      ``[0]`` ``productId``
===============  =====  ==========================================

Every builder RAISES on an argument it does not recognise.  A wrong parameter
block is worse than a missing one: the blueprint pastes cleanly and then runs
the wrong way round -- an exchanger set to discharge where the factory wanted
charge drains the accumulators it was supposed to fill, and nothing about the
paste looks wrong.
"""

from __future__ import annotations

from enum import IntEnum

from flab2bp.dsp import catalog

__all__ = [
    "ExchangerMode",
    "GammaMode",
    "energy_exchanger",
    "parameters_for",
    "ray_receiver",
]

#: Critical Photon.  What a Ray Receiver makes when it is not making power.
CRITICAL_PHOTON_ITEM_ID = 1208


class ExchangerMode(IntEnum):
    """Energy Exchanger ``targetState``.

    The value IS the stored word -- ``BuildingParameters.cs:3290`` writes
    ``targetState = Mathf.Clamp(parameters[0], -1, 1)``, so the tri-state is the
    parameter, not an index into one.

    Which pole means which is settled by ``PowerExchangerComponent``: each update
    path refuses to run unless ``state`` has reached its own pole --
    ``InputUpdate`` at ``1`` (:249) and ``OutputUpdate`` at ``-1`` (:296).  Input
    draws energy from the grid into the exchanger, which is charging.

    Confirmed against real blueprints rather than left at the decompiled clamp:
    the fixture corpus holds 45 exchangers, 13 at ``1`` and 32 at ``-1``, and
    ``factory-endgame-distribution-hub`` alone carries twelve of each.  Both
    poles appearing in one working blueprint pins the sign directly.
    """

    CHARGE = 1
    STANDBY = 0
    DISCHARGE = -1


class GammaMode(IntEnum):
    """Ray Receiver ``productId``: the item id it generates, or zero for power.

    ``BuildingParameters.cs:907`` stores the word as ``genPool[..].productId``
    and checks it against ``prefabDesc.powerProductId`` when the blueprint is
    pasted (:3273), so it is an item id like a sorter filter or a belt tag --
    not an enum the game interprets separately.

    .. warning::
       Unlike :class:`ExchangerMode` this is **not** corroborated by any real
       blueprint.  Ray Receivers appear zero times in the fixture corpus, so
       this rests on the dispatch table alone.  ``test_params.py`` asserts that
       absence, so the day a fixture contains one the claim gets rechecked
       instead of quietly inheriting unearned confidence.
    """

    POWER = 0
    PHOTON = CRITICAL_PHOTON_ITEM_ID


def energy_exchanger(mode: ExchangerMode) -> tuple[int, ...]:
    """The one-word block that puts an Energy Exchanger into ``mode``."""
    if not isinstance(mode, ExchangerMode):
        raise TypeError(
            f"expected an ExchangerMode, got {type(mode).__name__}. Passing the raw "
            f"word risks writing a pole the game clamps into the opposite mode."
        )
    return (int(mode),)


def ray_receiver(mode: GammaMode) -> tuple[int, ...]:
    """The one-word block that sets what a Ray Receiver generates."""
    if not isinstance(mode, GammaMode):
        raise TypeError(f"expected a GammaMode, got {type(mode).__name__}")
    return (int(mode),)


#: FactorioLab's mode name -> the word each machine expects.  Kept here rather
#: than in :mod:`catalog` so the catalog stays free of parameter-block detail.
_EXCHANGER_MODES = {
    "charge": ExchangerMode.CHARGE,
    "discharge": ExchangerMode.DISCHARGE,
    "standby": ExchangerMode.STANDBY,
}

_GAMMA_MODES = {
    "photon": GammaMode.PHOTON,
    "power": GammaMode.POWER,
}


def parameters_for(factoriolab_recipe_id: str) -> tuple[int, ...]:
    """The parameter block realising a mode-driven FactorioLab recipe.

    Note both photon recipes return the SAME block.  FactorioLab splits
    ``critical-photon`` from ``critical-photon-graviton`` because a Graviton
    Lens doubles the yield (6/s to 12/s), but that is a machine-level
    *consumption* -- an item fed into the same Ray Receiver -- not a different
    setting.  The lens is a belting problem for the layout stage, exactly like
    proliferator; emitting a different parameter block for it would be wrong.
    """
    entry = catalog.MODE_DRIVEN_MACHINE.get(factoriolab_recipe_id)
    if entry is None:
        raise KeyError(
            f"{factoriolab_recipe_id!r} is not a mode-driven recipe. Ordinary "
            f"crafts carry a recipe id instead -- see catalog.recipe_id()."
        )
    if entry.machine_item_id == catalog.ENERGY_EXCHANGER_ID:
        return energy_exchanger(_EXCHANGER_MODES[entry.mode])
    if entry.machine_item_id == catalog.RAY_RECEIVER_ID:
        return ray_receiver(_GAMMA_MODES[entry.mode])
    raise KeyError(
        f"no parameter-block builder for machine {entry.machine_item_id} "
        f"({entry.machine_name}); add one rather than emitting an empty block"
    )
