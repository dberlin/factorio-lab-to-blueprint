"""Choosing a machine when the URL's rank is a ceiling rather than a mandate.

FactorioLab's machine rank is a mandate: ``select_machine`` takes the first
ranked producer and builds every machine of that recipe out of it, even when
the rate needs a fraction of one.  ``MachineRank.UP_TO`` reads the same rank
as a ceiling and takes the slowest producer that still meets the already-fixed
rate in the same number of machines.

The arithmetic is exact and the ceiling is the rank's own machine, so the
choice can never need MORE machines than ``exact`` does: ``ceil(r / s)`` is
non-increasing in ``s`` and the ceiling has the greatest speed on its own
ladder.  Only the building placed changes, and only ever downward.
"""

from __future__ import annotations

from collections.abc import Collection
from enum import StrEnum
from fractions import Fraction

from flab2bp.dsp import catalog
from flab2bp.lab.schema import Dataset, Recipe
from flab2bp.rates.adjust import ProliferatorTier, adjust
from flab2bp.spec import ProliferatorMode


class MachineRank(StrEnum):
    """How the URL's machine rank is read."""

    #: FactorioLab's ``bestMatch``: the ranked machine, always.
    EXACT = "exact"
    #: The ranked machine is a ceiling; take the slowest producer that ties.
    UP_TO = "up-to"


def machine_speed(data: Dataset, machine_item_id: str) -> Fraction:
    """A machine's crafting speed, with ``None`` read as 1.

    ``adjust()`` makes the same substitution; keeping it in one named
    function stops the two from disagreeing about a machine whose speed the
    dataset omits.
    """
    machine = data.machine(machine_item_id)
    return machine.speed if machine.speed is not None else Fraction(1)


def _is_placeable(machine_item_id: str) -> bool:
    """Whether the layout stage could place this machine.

    ``layout/freeform.py`` resolves a group's machine through
    ``catalog.get_item_id`` and raises when it cannot.  A candidate the
    layout cannot place is not a candidate.
    """
    try:
        catalog.get_item_id(machine_item_id)
    except KeyError, ValueError:
        return False
    return True


def candidate_ladder(
    data: Dataset,
    recipe: Recipe,
    ceiling_id: str,
    unlocked: Collection[str],
) -> tuple[str, ...]:
    """The producers of ``recipe`` at or below ``ceiling_id``, slowest first.

    A producer qualifies when it is no faster than the ceiling, the save has
    unlocked it, and the DSP catalog can place it.  The ceiling itself is
    always admitted regardless -- mirroring the belt rule in
    ``lab/techs.py``, where the request's own belt is included researched or
    not, because FactorioLab chose it and FactorioLab's choice is
    authoritative.

    Ordered by ``(speed, position in recipe.producers)`` so the tie-break in
    :func:`choose_machine` is "lowest tier, then dataset order" by
    construction rather than by a second sort.
    """
    ceiling_speed = machine_speed(data, ceiling_id)
    ladder: list[tuple[Fraction, int, str]] = []
    for index, machine_id in enumerate(recipe.producers):
        if machine_id == ceiling_id:
            ladder.append((ceiling_speed, index, machine_id))
            continue
        if machine_id not in unlocked:
            continue
        if not _is_placeable(machine_id):
            continue
        speed = machine_speed(data, machine_id)
        if speed > ceiling_speed:
            continue
        ladder.append((speed, index, machine_id))
    ladder.sort()
    return tuple(machine_id for _, _, machine_id in ladder)


def machines_needed(craft_rate: Fraction, crafts_per_second: Fraction) -> int:
    """Exact ceiling of ``craft_rate / crafts_per_second``.

    The same expression ``solve.py`` uses to turn an exact rate into a
    physical count.  Kept exact: at 0.1 crafts/s a float ceiling rounds the
    wrong way often enough to move a real build.
    """
    exact = craft_rate / crafts_per_second
    return -((-exact.numerator) // exact.denominator)


def choose_machine(
    data: Dataset,
    recipe: Recipe,
    *,
    ceiling_id: str,
    craft_rate: Fraction,
    mode: ProliferatorMode,
    tier: ProliferatorTier,
    unlocked: Collection[str],
) -> str:
    """The slowest producer that meets ``craft_rate`` in the fewest machines.

    Fewest machines first, then lowest tier.  Because
    :func:`candidate_ladder` is already ordered ``(speed, dataset order)``
    and ``min`` is stable, the first candidate attaining the minimum count is
    the lowest-tier one, which is the tie-break the design asks for.

    ``mode`` and ``tier`` are the column's own -- a proliferator speed bonus
    scales every candidate equally, but the ceiling is nonlinear, so each
    candidate is measured through ``adjust()`` rather than by scaling.
    """
    ladder = candidate_ladder(data, recipe, ceiling_id, unlocked)
    if len(ladder) == 1:
        return ladder[0]
    best_id = ceiling_id
    best_count: int | None = None
    for machine_id in ladder:
        count = machines_needed(
            craft_rate, adjust(data, recipe, machine_id, mode, tier).crafts_per_second
        )
        if best_count is None or count < best_count:
            best_count = count
            best_id = machine_id
    return best_id
