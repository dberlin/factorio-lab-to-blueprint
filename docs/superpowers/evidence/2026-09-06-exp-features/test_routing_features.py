"""Unit tests for the routing-difficulty feature vector.

    uv run pytest docs/superpowers/evidence/2026-09-06-exp-features/test_routing_features.py

Deliberately synthetic and catalog-free: the graph half of the module is the
half carrying the hypothesis, and a hand-built four-recipe spec states the
copper-ingot-versus-magnet contrast far more legibly than any corpus URL.
"""

from __future__ import annotations

import sys
from fractions import Fraction
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent.parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_HERE))

from routing_features import (  # noqa: E402
    cut_pressure,
    group_depths,
    item_profiles,
    items_above_one_belt,
    live_profiles,
    routing_features,
    strip_shape,
)

from flab2bp.spec import BuildSpec, MachineGroup  # noqa: E402


def _group(recipe: str, ins: dict[str, int], outs: dict[str, int], count: int = 1) -> MachineGroup:
    return MachineGroup(
        recipe_id=recipe,
        machine_item_id="assembling-machine-2",
        count=count,
        inputs_per_machine={k: Fraction(v) for k, v in ins.items()},
        outputs_per_machine={k: Fraction(v) for k, v in outs.items()},
    )


def _copper_versus_magnet() -> BuildSpec:
    """The user's contrast, as a spec.

    ``copper-ingot`` is made at depth 0 and eaten at depths 1 and 3 -- early
    and late pieces of the same block.  ``magnet`` is made at depth 0 and eaten
    once, immediately, at depth 1.
    """
    return BuildSpec(
        groups=(
            _group("copper-ingot", {"copper-ore": 1}, {"copper-ingot": 1}),
            _group("magnet", {"iron-ore": 1}, {"magnet": 1}),
            _group("magnetic-coil", {"magnet": 2, "copper-ingot": 1}, {"magnetic-coil": 1}),
            _group("circuit", {"magnetic-coil": 1}, {"circuit": 1}),
            _group("processor", {"circuit": 2, "copper-ingot": 1}, {"processor": 1}),
        ),
        external_inputs={"copper-ore": Fraction(2), "iron-ore": Fraction(2)},
        outputs={"processor": Fraction(1)},
        label="test",
    )


def test_spread_separates_a_bussed_ingot_from_an_immediately_used_intermediate() -> None:
    spec = _copper_versus_magnet()
    assert group_depths(spec) == (0, 0, 1, 2, 3)

    by_id = {p.item_id: p for p in item_profiles(spec)}

    copper = by_id["copper-ingot"]
    assert (copper.consumers, copper.earliest_consumer_depth, copper.latest_consumer_depth) == (
        2,
        1,
        3,
    )
    assert copper.span == 2
    assert copper.spread == 4

    magnet = by_id["magnet"]
    assert (magnet.consumers, magnet.span, magnet.spread) == (1, 0, 0)

    # And the aggregate picks copper out as the block's hardest item.
    features = routing_features(spec, strips=())
    assert features.chain_depth == 3
    assert features.max_spread == 4
    assert features.top_spread[0] == ("copper-ingot", 4)
    # Fan-out alone would not separate them: both have modest consumer counts.
    assert features.max_consumers == 2
    assert features.items_with_3plus_consumers == 0


def test_a_production_cycle_terminates_and_belt_pressure_is_counted() -> None:
    """Oil-chain shape: two recipes that produce each other's ingredient."""
    spec = BuildSpec(
        groups=(
            _group("refined-oil", {"crude-oil": 4}, {"refined-oil": 2, "hydrogen": 1}, count=40),
            _group("reforming", {"refined-oil": 2, "hydrogen": 1}, {"refined-oil": 3}, count=40),
            _group("plastic", {"refined-oil": 2}, {"plastic": 1}, count=10),
        ),
        external_inputs={"crude-oil": Fraction(160)},
        outputs={"plastic": Fraction(10)},
        belt_item_id="conveyor-belt-3",
        belt_items_per_second=Fraction(30),
        #: Stacked, so the capacity threshold is 60/s and not 30 -- the same
        #: arithmetic `layout/belt_tiers.py` does before it declares a run over.
        belt_stack=2,
        label="test",
    )

    # Back edges cut at 0, so this terminates.  Reforming sits one below the
    # refinery; plastic sits one below reforming, because refined oil's DEEPEST
    # producer is what sets the layer a consumer can be built in.
    assert group_depths(spec) == (0, 1, 2)

    # Refined oil is exactly the shape the hypothesis is about: two consumers,
    # one layer apart, inside a three-recipe block.
    by_id = {p.item_id: p for p in item_profiles(spec)}
    assert (by_id["refined-oil"].consumers, by_id["refined-oil"].spread) == (2, 2)

    # 40*2 + 40*3 = 200/s of refined oil against a 60/s stacked lane, and crude
    # arrives at 160/s.  Hydrogen (40/s) and plastic (10/s) both fit, so this is
    # a real threshold and not "everything is over".
    assert items_above_one_belt(spec) == ("crude-oil", "refined-oil")

    features = routing_features(spec, strips=())
    assert features.items_above_one_belt == 2
    assert features.both_fed_items == 0


def test_the_spray_is_scored_from_lanes_because_it_is_not_an_ingredient() -> None:
    """Proliferator reaches machines by coater, so the recipe DAG never has it."""
    spec = _copper_versus_magnet().model_copy(
        update={
            "external_inputs": {
                "copper-ore": Fraction(2),
                "iron-ore": Fraction(2),
                "proliferator-2": Fraction(1),
            },
            # Sprayed lanes at depth 1 (magnet, copper-ingot's early consumer)
            # and depth 3 (the processor's copper-ingot lane).
            "spray_lanes": {"magnet": False, "copper-ingot": False, "circuit": False},
        }
    )

    # The graph walk still sees nothing: no group EATS the spray.
    sprays = [p for p in item_profiles(spec) if p.item_id.startswith("proliferator")]
    assert [p.consumers for p in sprays] == [0]

    features = routing_features(spec, strips=())
    assert features.coaters == 3
    assert features.proliferator_consumers == 3
    # magnet is eaten at depth 1, circuit at depth 3 -> the spray must be
    # belted across two layers of the block.
    assert features.proliferator_span == 2
    assert features.proliferator_spread == 6

    # And an unproliferated spec scores a clean zero rather than a fiction.
    assert routing_features(_copper_versus_magnet(), strips=()).proliferator_spread == 0


def test_live_range_starts_at_the_definition_and_ignores_fan_out() -> None:
    """The two ways a live range differs from spread, on one spec."""
    spec = _copper_versus_magnet()
    by_id = {p.item_id: p for p in live_profiles(spec)}

    # copper-ingot: DEFINED at depth 0, last used at depth 3.  Spread's window
    # started at the first USE (depth 1) and multiplied by two consumers, so
    # the two numbers are 3 and 4 -- neither a scaling nor a shift of the other.
    copper = by_id["copper-ingot"]
    assert (copper.producer_depth, copper.last_use_depth, copper.live_range) == (0, 3, 3)
    assert {p.item_id: p.spread for p in item_profiles(spec)}["copper-ingot"] == 4

    # magnet: made at 0, eaten at 1.  Live range 1 where spread was 0 -- a
    # one-consumer item still occupies a belt for one layer.
    assert by_id["magnet"].live_range == 1

    # copper-ore arrives at the boundary, so it is defined in the source layer.
    assert (by_id["copper-ore"].producer_depth, by_id["copper-ore"].live_range) == (0, 0)

    # processor is the final output: nothing consumes it, so it is never live
    # across a cut inside the block.
    assert by_id["processor"].last_use_depth == -1
    assert by_id["processor"].live_range == 0

    features = routing_features(spec, strips=())
    assert features.max_live_range == 3
    assert features.top_live_range[0] == ("copper-ingot", 3)
    assert features.items_live_range_ge3 == 1


def test_cut_pressure_counts_belts_crossing_each_band() -> None:
    spec = _copper_versus_magnet()
    live = live_profiles(spec)
    profile = cut_pressure(live, chain_depth=3)
    assert [entry[0] for entry in profile] == [0, 1, 2]

    # Cut 0 (between layer 0 and 1): copper-ingot (0..3) and magnet (0..1).
    # Cut 1: copper-ingot only -- magnet died at layer 1.
    # Cut 2: copper-ingot, plus magnetic-coil?  No: coil is made at 1 and eaten
    # at 2, so it dies before this cut.  circuit is made at 2, eaten at 3.
    assert [entry[1] for entry in profile] == [2, 2, 2]

    # Every rate here is 1-2/s against the default belt, so lanes == items.
    assert [entry[2] for entry in profile] == [2, 2, 2]

    features = routing_features(spec, strips=())
    assert features.max_pressure == 2
    assert features.max_lane_pressure == 2
    # The identity the join relies on: an item crosses one cut per layer of
    # its range, so total item-cuts is exactly the summed live range.
    assert features.sum_pressure == features.sum_live_range


def test_the_spray_is_live_from_the_boundary_to_the_deepest_coater() -> None:
    spec = _copper_versus_magnet().model_copy(
        update={
            "external_inputs": {
                "copper-ore": Fraction(2),
                "iron-ore": Fraction(2),
                "proliferator-2": Fraction(1),
            },
            "spray_lanes": {"magnet": False, "circuit": False},
        }
    )
    spray = next(p for p in live_profiles(spec) if p.is_spray)
    # magnet is eaten at depth 1, circuit at depth 3: the spray belt has to run
    # from the block edge (0) down to layer 3.
    assert (spray.producer_depth, spray.last_use_depth, spray.live_range) == (0, 3, 3)
    assert spray.live_lanes >= 1

    features = routing_features(spec, strips=())
    assert features.proliferator_live_range == 3
    # And it really does add pressure to every cut it spans.
    assert features.max_pressure == features.max_pressure_no_spray + 1

    # Excluding it drops the row entirely rather than zeroing it.
    assert not any(p.is_spray for p in live_profiles(spec, include_spray=False))


def test_live_lanes_ceil_the_flow_against_the_best_belt() -> None:
    """An item over capacity crosses a cut on several belts, not one."""
    spec = BuildSpec(
        groups=(
            _group("ingot", {"ore": 1}, {"ingot": 1}, count=100),
            _group("plate", {"ingot": 1}, {"plate": 1}, count=100),
        ),
        external_inputs={"ore": Fraction(100)},
        outputs={"plate": Fraction(100)},
        belt_item_id="conveyor-belt-3",
        belt_items_per_second=Fraction(30),
        label="test",
    )
    by_id = {p.item_id: p for p in live_profiles(spec)}
    assert by_id["ingot"].live_lanes == 4  # ceil(100/30)
    assert by_id["ingot"].live_range == 1

    features = routing_features(spec, strips=())
    # One cut, crossed by ingot alone, on four belts.
    assert (features.max_pressure, features.max_lane_pressure) == (1, 4)


def test_strip_shape_counts_distinct_items_not_lanes() -> None:
    class _FakeStrip:
        def __init__(self, above: tuple[tuple[str, ...], ...], below: tuple[tuple[str, ...], ...]):
            self.in_above = above
            self.in_below = below

    strips = [
        # One item split across two lanes is still one ingredient.
        _FakeStrip((("iron-ingot",), ("iron-ingot",)), ()),
        _FakeStrip((("copper-ingot", "magnet"),), (("graphite",),)),
    ]
    assert strip_shape(strips) == (2, 3, 2.0)  # type: ignore[arg-type]
    assert strip_shape([]) == (0, 0, 0.0)
