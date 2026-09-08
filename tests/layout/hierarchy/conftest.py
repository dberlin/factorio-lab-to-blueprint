"""Fixtures shared by the hierarchy layout tests.

The composer needs BLOCKS THAT REALLY SOLVED, not hand-built placements: the
router attaches to a lane's own tiles, reads each port's altitude, and reserves
the free cells beside it, so a fixture that does not come out of
``FreeformLayout`` cannot exercise any of that.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from flab2bp.lab.techs import belt_rules_for_url
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import Placement
from flab2bp.layout.freeform import FreeformLayout
from flab2bp.layout.hierarchy.contracts import LaneEnd, LaneFlow, assign_lanes, boundary_lanes
from flab2bp.layout.hierarchy.partition import initial_partition, sub_spec
from flab2bp.spec import BuildSpec, MachineGroup

_BELT_RULES = belt_rules_for_url("https://factoriolab.github.io/dsp/list?o=iron-ingot*60&v=11")


#: How long each block gets to lay out.  The two blocks here solve in under a
#: second apiece; the budget is the ceiling the task's brief set, not a target.
_BLOCK_BUDGET_S = 10.0


def chain_build_spec() -> BuildSpec:
    """``test_pressure._chain`` with ids the catalog actually knows.

    Same graph and the same rates -- ore -> ingot (two smelters), ingot -> two
    one-machine consumers -- but ``ore``/``ingot``/``plate`` are not DSP items
    and ``sorter-1`` alone cannot sustain 1 item/s over a two-tile span, so a
    real layout of the partition tests' spec refuses on
    ``flow.sorter_capacity``.  The ids here resolve and the sorter ladder is
    the full one; nothing else about the spec changes.
    """
    groups = (
        MachineGroup(
            recipe_id="iron-ingot",
            machine_item_id="arc-smelter",
            count=2,
            inputs_per_machine={"iron-ore": Fraction(1)},
            outputs_per_machine={"iron-ingot": Fraction(1)},
        ),
        MachineGroup(
            recipe_id="gear",
            machine_item_id="assembling-machine-1",
            count=1,
            inputs_per_machine={"iron-ingot": Fraction(1)},
            outputs_per_machine={"gear": Fraction(1)},
        ),
        MachineGroup(
            recipe_id="magnet",
            machine_item_id="assembling-machine-1",
            count=1,
            inputs_per_machine={"iron-ingot": Fraction(1)},
            outputs_per_machine={"magnet": Fraction(1)},
        ),
    )
    return BuildSpec(
        groups=groups,
        external_inputs={"iron-ore": Fraction(2)},
        outputs={"gear": Fraction(1), "magnet": Fraction(1)},
        surplus_outputs={},
        belt_item_id="conveyor-belt-1",
        belt_items_per_second=Fraction(6),
        belt_upgrades=(),
        sorter_item_ids=("sorter-1", "sorter-2", "sorter-3"),
        belt_stack=1,
        sorter_pick_stacks=(1, 1, 1),
        sorter_place_stacks=(1, 1, 1),
        piler_unlocked=False,
        label="chain",
    )


@pytest.fixture
def chain_spec() -> BuildSpec:
    """:func:`chain_build_spec` as a fixture, for the tests that take a spec.

    Function-scoped and rebuilt each time: ``BuildSpec`` is frozen, but a
    strategy under test may put it through a partition and a composition, and a
    shared instance would make one test's diagnosis depend on another's.
    """
    return chain_build_spec()


@pytest.fixture(scope="module")
def two_solved_blocks() -> tuple[Placement, Placement, list[LaneFlow], BuildSpec, bool]:
    """``chain_spec`` split at its one cut, both halves laid out for real.

    Module-scoped because the two solves are the expensive part and neither
    test mutates a ``Placement`` -- the composer copies every building through
    ``dataclasses.replace`` before it touches one.
    """
    spec = chain_build_spec()
    partition = initial_partition(spec)
    assert len(partition.blocks) == 2, "the chain must split into exactly two blocks"

    layout = FreeformLayout(
        belt_rules=_BELT_RULES,
        band_policy=BandPolicy.parse("portable"),
        workers=4,
    )
    tails: dict[int, list[LaneEnd]] = {}
    heads: dict[int, list[LaneEnd]] = {}
    placements: list[Placement] = []
    for index, block in enumerate(partition.blocks):
        sub = sub_spec(spec, block, index)
        placement = layout.lay_out(sub, time_budget_s=_BLOCK_BUDGET_S)
        placements.append(placement)
        tails[index], heads[index] = boundary_lanes(placement, sub, index)

    flows = assign_lanes(partition.cuts, tails, heads)
    assert flows, "the chain's one cut must produce at least one lane flow"
    left, right = placements
    # The fully researched policy permits vertical links without the ramp limit.
    return left, right, flows, spec, False
