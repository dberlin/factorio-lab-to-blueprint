"""Strategy A end-to-end properties.

Specs are hand-built here rather than taken from ``rates/``, which is being
implemented concurrently -- these tests must pin the layout's behaviour, not the
rate solver's.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable
from dataclasses import replace
from fractions import Fraction

import pytest

from flab2bp.dsp import catalog, rules
from flab2bp.dsp import colliders as C
from flab2bp.layout import junction, validate
from flab2bp.layout.base import (
    DETERMINISTIC_WORKERS,
    NoValidLayout,
    PlacedBuilding,
    Placement,
)
from flab2bp.layout.spine import (
    FALLBACK_NONE,
    MACHINE_ITEM_IDS,
    SpineLayout,
    _emit,
    _Plan,
    fallback_plan,
    machine_group_footprint,
)
from flab2bp.spec import BuildSpec, MachineGroup, ProliferatorMode

F = Fraction
SpecFactory = Callable[[], BuildSpec]


def group(
    recipe: str,
    machine: str,
    count: int,
    inputs: dict[str, Fraction] | None = None,
    outputs: dict[str, Fraction] | None = None,
    mode: ProliferatorMode = ProliferatorMode.NONE,
) -> MachineGroup:
    return MachineGroup(
        recipe_id=recipe,
        machine_item_id=machine,
        count=count,
        proliferator_mode=mode,
        inputs_per_machine=inputs or {},
        outputs_per_machine=outputs or {},
    )


def single_recipe_spec() -> BuildSpec:
    return BuildSpec(
        groups=(
            group("iron-ingot", "arc-smelter", 4, {"iron-ore": F(1)}, {"iron-ingot": F(1)}),
        ),
        external_inputs={"iron-ore": F(4)},
        outputs={"iron-ingot": F(4)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="single",
    )


def two_stage_spec() -> BuildSpec:
    return BuildSpec(
        groups=(
            group("iron-ingot", "arc-smelter", 4, {"iron-ore": F(1)}, {"iron-ingot": F(1)}),
            # Four, not two: four smelters make 4 iron-ingot/s, so two gear
            # assemblers left 2/s with nowhere to go and the smelters backed up.
            group(
                "gear",
                "assembling-machine-2",
                4,
                {"iron-ingot": F(1)},
                {"gear": F(1)},
            ),
        ),
        external_inputs={"iron-ore": F(4)},
        outputs={"gear": F(4)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="two-stage",
    )


def magnetic_ring_spec() -> BuildSpec:
    """Shaped like the super-magnetic-ring chain, and RATE-BALANCED.

    Nine groups, 54 machines, every machine running at 1/s.  The counts are not
    decorative: they are the unique solution of the chain's stoichiometry at two
    rings per second, so supply equals demand for every internal item and every
    external input equals what its consumers draw::

        ring 2      <- turbine 4, graphite 2, magnet 6
        turbine 4   <- motor 4, coil 4
        motor 4     <- ingot 4, gear 4, coil 4
        coil 8      <- magnet 8, copper 8
        gear 4      <- ingot 4
        ingot 8     <- iron-ore 8       magnet 14 <- iron-ore 14
        copper 8    <- copper-ore 8     graphite 2 <- coal 2

    It used to be round numbers instead -- 4 magnetic-coil/s against 12/s of
    demand, and 17 magnet/s on a 12/s belt.  Any test that asserted flow-clean
    on it therefore failed for reasons with nothing to do with geometry, which
    is worse than no test: it makes the flow checks unusable on the one spec
    with enough shape to exercise them.

    The belt is Mk.III because the busiest lane -- iron-ore at 22/s, feeding
    both the ingot and the magnet rows -- does not fit on Mk.II.  Under-sizing
    the belt would reintroduce exactly the failure this fixture exists to avoid.
    """
    return BuildSpec(
        groups=(
            group("iron-ingot", "arc-smelter", 8, {"iron-ore": F(1)}, {"iron-ingot": F(1)}),
            group("copper-ingot", "arc-smelter", 8, {"copper-ore": F(1)}, {"copper-ingot": F(1)}),
            group("magnet", "arc-smelter", 14, {"iron-ore": F(1)}, {"magnet": F(1)}),
            group(
                "energetic-graphite",
                "arc-smelter",
                2,
                {"coal": F(1)},
                {"energetic-graphite": F(1)},
            ),
            group(
                "magnetic-coil",
                "assembling-machine-2",
                8,
                {"magnet": F(1), "copper-ingot": F(1)},
                {"magnetic-coil": F(1)},
            ),
            group("gear", "assembling-machine-2", 4, {"iron-ingot": F(1)}, {"gear": F(1)}),
            group(
                "electric-motor",
                "assembling-machine-2",
                4,
                {"iron-ingot": F(1), "gear": F(1), "magnetic-coil": F(1)},
                {"electric-motor": F(1)},
            ),
            group(
                "electromagnetic-turbine",
                "assembling-machine-2",
                4,
                {"electric-motor": F(1), "magnetic-coil": F(1)},
                {"electromagnetic-turbine": F(1)},
            ),
            group(
                "super-magnetic-ring",
                "assembling-machine-2",
                2,
                {
                    "electromagnetic-turbine": F(2),
                    "energetic-graphite": F(1),
                    "magnet": F(3),
                },
                {"super-magnetic-ring": F(1)},
            ),
        ),
        external_inputs={"iron-ore": F(22), "copper-ore": F(8), "coal": F(2)},
        outputs={"super-magnetic-ring": F(2)},
        belt_item_id="conveyor-belt-3",
        belt_items_per_second=F(30),
        label="magnetic-ring",
    )


def pitch_gap_spec() -> BuildSpec:
    """Three Assembling Machines, one row, six lanes -- and every lane gapped.

    An assembler covers 3 tiles and RESERVES 4: its 3.82-unit collider does not
    fit a 3-tile pitch.  So a row of nothing but assemblers is four tall while
    every machine in it is three, and each one stops one tile above its row's
    floor -- every lane of the corridor below is that tile further away.  A band
    holds two such lanes (``_fits_band``: 1 + 0 + 1 and 1 + 1 + 1 fit, 1 + 2 + 1
    does not), and the corridor above holds three, so six lanes do not go in
    five places.

    EVERY MACHINE HERE IS THE SAME HEIGHT, and that is the point.  The model this
    fixture guards derived its thresholds from differences of TAP heights, of
    which this spec has none, and reified them against ``row_h`` -- a PITCH
    height, which is a different number entirely.  So it built no constraint at
    all and authorised the row.  Measured over the twelve corpus specs at the
    time: thresholds absent in 3 and incomplete in 6.

    Six items per second on a twelve-per-second belt, deliberately: it keeps
    every item to one lane while making every PAIR of them overflow, so
    ``_shareable`` cannot pair two taps onto one lane and rescue the row.
    """
    return BuildSpec(
        groups=(
            group("gear", "assembling-machine-2", 1, {"iron-ingot": F(7)}, {"gear": F(7)}),
            group(
                "magnetic-coil", "assembling-machine-2", 1,
                {"magnet": F(7)}, {"magnetic-coil": F(7)},
            ),
            group(
                "circuit-board", "assembling-machine-2", 1,
                {"copper-ingot": F(7)}, {"circuit-board": F(7)},
            ),
        ),
        external_inputs={"iron-ingot": F(7), "magnet": F(7), "copper-ingot": F(7)},
        outputs={"gear": F(7), "magnetic-coil": F(7), "circuit-board": F(7)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="pitch-gap",
    )


def inset_face_spec() -> BuildSpec:
    """Three Chemical Plants, one row, six lanes -- and every lane inset UPWARD.

    A plant's poses on the face looking up sit a row INSIDE a footprint five
    deep, so a sorter reaching the nearest lane above already spans two tiles and
    the third lane up is out of reach entirely.  The corridor above holds two
    such lanes, not three.  The corridor below holds three -- the plant's poses
    on THAT face are on its edge and a row of plants is exactly as tall as one --
    so six lanes want two places and three, and there is no sixth.

    The asymmetry is the whole fixture.  A model carrying one number per group
    and taking the worse of the two sides gets both halves wrong at once: it
    charges the face looking down a tile it does not owe, and charges the face
    looking up nothing.  The two errors cancel in the TOTAL -- 3 up and 2 down
    against a truth of 2 and 3, five either way -- which is exactly why an
    aggregate check cleared a model that was wrong on both sides.
    """
    return BuildSpec(
        groups=(
            group("plastic", "chemical-plant", 1, {"refined-oil": F(7)}, {"plastic": F(7)}),
            group(
                "sulfuric-acid", "chemical-plant", 1,
                {"refined-oil-2": F(7)}, {"sulfuric-acid": F(7)},
            ),
            group(
                "graphene", "chemical-plant", 1,
                {"spiniform-stalagmite-crystal": F(7)}, {"graphene": F(7)},
            ),
        ),
        external_inputs={
            "refined-oil": F(7), "refined-oil-2": F(7),
            "spiniform-stalagmite-crystal": F(7),
        },
        outputs={"plastic": F(7), "sulfuric-acid": F(7), "graphene": F(7)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="inset-face",
    )


# --- helpers ---------------------------------------------------------------


def blocking_tiles(p: Placement) -> list[tuple[int, int, Fraction]]:
    """Tiles that genuinely exclude another building.

    Belt-integrated buildings share tiles rather than consuming them: belts,
    sorters and splitters all sit at dx=dy=0.00 from a belt in real blueprints.
    Belt addons such as the Spray Coater occupy no grid tile at all.  Neither
    class may be counted as blocking, or every valid layout would fail.
    """
    tiles: list[tuple[int, int, Fraction]] = []
    for b in p.buildings:
        if catalog.is_belt_integrated(b.item_id):
            continue
        if not catalog.building(b.item_id).occupies_tiles:
            continue
        tiles.extend(b.tiles())
    return tiles


def machines_of(p: Placement) -> list[int]:
    return [
        i
        for i, b in enumerate(p.buildings)
        if not catalog.is_belt_integrated(b.item_id)
        and b.item_id != catalog.TESLA_TOWER_ID
        and catalog.building(b.item_id).occupies_tiles
    ]


class TestTheFixturesBalance:
    """A hand-built spec that does not balance makes every flow check useless.

    ``magnetic_ring_spec`` used to be round numbers -- 4 magnetic-coil/s
    supplying 12/s of demand, 17 magnet/s on a 12/s belt -- so a test asserting
    anything about flow on it failed for arithmetic reasons and told you nothing
    about the layout.  These two tests are pure arithmetic on the spec: they
    cannot be satisfied by a change to the layout, only by the numbers being
    right, so the fixture cannot rot back.
    """

    @pytest.mark.parametrize(
        "spec_fn",
        [single_recipe_spec, two_stage_spec, magnetic_ring_spec],
        ids=lambda f: f.__name__,
    )
    def test_supply_equals_demand_for_every_item(self, spec_fn: SpecFactory) -> None:
        spec = spec_fn()
        made: dict[str, Fraction] = {}
        used: dict[str, Fraction] = {}
        for g in spec.groups:
            for item, rate in g.outputs_per_machine.items():
                made[item] = made.get(item, F(0)) + rate * g.count
            for item, rate in g.inputs_per_machine.items():
                used[item] = used.get(item, F(0)) + rate * g.count
        for item in set(made) | set(used):
            supply = made.get(item, F(0)) + spec.external_inputs.get(item, F(0))
            demand = used.get(item, F(0)) + spec.outputs.get(item, F(0))
            assert supply == demand, (
                f"{item}: {supply}/s supplied against {demand}/s demanded"
            )

    @pytest.mark.parametrize(
        "spec_fn",
        [single_recipe_spec, two_stage_spec, magnetic_ring_spec],
        ids=lambda f: f.__name__,
    )
    def test_no_item_needs_more_than_one_belt_of_its_tier(
        self, spec_fn: SpecFactory
    ) -> None:
        """The spine puts an item's whole cross-corridor flow on one lane.

        Lane splitting exists (:func:`_lane_copies`), but a fixture that needs it
        for an unrelated reason turns every geometry test on that fixture into a
        capacity test as well.  These fixtures are sized to stay under one belt.
        """
        spec = spec_fn()
        belt = catalog.BELT_RATE[
            {"conveyor-belt-1": 2001, "conveyor-belt-2": 2002, "conveyor-belt-3": 2003}[
                spec.belt_item_id
            ]
        ]
        used: dict[str, Fraction] = {}
        for g in spec.groups:
            for item, rate in g.inputs_per_machine.items():
                used[item] = used.get(item, F(0)) + rate * g.count
        for item, rate in used.items():
            assert rate <= belt, f"{item} needs {rate}/s on a {belt}/s belt"


# --- adapter ---------------------------------------------------------------


class TestAdapter:
    def test_every_dsp_producer_machine_maps_to_a_building(self) -> None:
        """A missing id would surface as a KeyError deep inside emission."""
        for lab_id, item_id in MACHINE_ITEM_IDS.items():
            b = catalog.building(item_id)
            assert b.width >= 1 and b.height >= 1, lab_id

    def test_footprints_are_the_real_heterogeneous_ones(self) -> None:
        """Footprints are derived, always odd, and genuinely varied.

        Smelters and assemblers are the *same* 3x3 under the derived rule, so
        heterogeneity is proven by the larger plants instead -- a 7x5 chemical
        plant is nearly four times the area of a 3x3 smelter, and the 3x7
        refinery is the case where width and height differ.
        """
        smelter = machine_group_footprint(group("x", "arc-smelter", 1))
        assembler = machine_group_footprint(group("x", "assembling-machine-2", 1))
        chemical = machine_group_footprint(group("x", "chemical-plant", 1))
        lab = machine_group_footprint(group("x", "matrix-lab", 1))
        refinery = machine_group_footprint(group("x", "oil-refinery", 1))

        assert smelter == (3, 3)
        assert assembler == (3, 3)
        assert chemical == (7, 5)
        assert lab == (5, 5)
        assert refinery == (3, 7)

        # Genuinely heterogeneous: at least three distinct sizes, spanning a
        # near-4x area range, including a non-square one.
        assert len({smelter, chemical, lab, refinery}) >= 3
        assert chemical[0] * chemical[1] >= 3 * smelter[0] * smelter[1]
        assert refinery[0] != refinery[1]

    def test_every_derived_footprint_dimension_is_odd(self) -> None:
        """The derived rule is ``2 * ceil(e / GRID_ARC) - 1``, so never even.

        An even-width building centred on an integer would straddle tile
        boundaries, which belts (fixed 1x1 on integer centres) prove cannot
        happen.
        """
        for lab_id in MACHINE_ITEM_IDS:
            w, h = machine_group_footprint(group("x", lab_id, 1))
            assert w % 2 == 1 and h % 2 == 1, f"{lab_id} is {w}x{h}"

    def test_unknown_machine_raises_clearly(self) -> None:
        spec = BuildSpec(groups=(group("x", "not-a-machine", 1),))
        with pytest.raises(KeyError, match="not-a-machine"):
            fallback_plan(spec)


# --- planning --------------------------------------------------------------


class TestFallbackPlan:
    def test_one_group_per_row(self) -> None:
        plan = fallback_plan(magnetic_ring_spec())
        assert all(len(r) == 1 for r in plan.rows)
        assert len(plan.rows) == 9

    def test_producers_sit_above_consumers(self) -> None:
        plan = fallback_plan(two_stage_spec())
        order = [r[0] for r in plan.rows]
        assert order[0].startswith("iron-ingot")
        assert order[1].startswith("gear")

    def test_one_more_corridor_than_rows(self) -> None:
        plan = fallback_plan(magnetic_ring_spec())
        assert len(plan.lanes) == len(plan.rows) + 1

    def test_cyclic_graph_raises_rather_than_misordering(self) -> None:
        spec = BuildSpec(
            groups=(
                group("a", "arc-smelter", 1, {"b-item": F(1)}, {"a-item": F(1)}),
                group("b", "arc-smelter", 1, {"a-item": F(1)}, {"b-item": F(1)}),
            )
        )
        with pytest.raises(ValueError, match="cyclic"):
            fallback_plan(spec)


# --- emission properties ---------------------------------------------------


@pytest.mark.parametrize(
    "spec_fn", [single_recipe_spec, two_stage_spec, magnetic_ring_spec], ids=lambda f: f.__name__
)
@pytest.mark.parametrize("power", [True, False], ids=["power", "no-power"])
class TestPlacementProperties:
    def test_no_two_blocking_footprints_share_a_tile(
        self, spec_fn: SpecFactory, power: bool
    ) -> None:
        p = SpineLayout(power=power).lay_out(spec_fn(), time_budget_s=0.5)
        tiles = blocking_tiles(p)
        assert len(tiles) == len(set(tiles)), "overlapping footprints"

    def test_every_machine_is_placed(
        self, spec_fn: SpecFactory, power: bool
    ) -> None:
        spec = spec_fn()
        p = SpineLayout(power=power).lay_out(spec, time_budget_s=0.5)
        assert len(machines_of(p)) == spec.machine_count

    def test_every_sorter_is_within_reach_and_single_altitude(
        self, spec_fn: SpecFactory, power: bool
    ) -> None:
        p = SpineLayout(power=power).lay_out(spec_fn(), time_budget_s=0.5)
        for b in p.buildings:
            if not catalog.is_sorter(b.item_id):
                continue
            assert b.x2 is not None and b.y2 is not None
            span = max(abs(b.x - b.x2), abs(b.y - b.y2))
            assert 1 <= span <= catalog.SORTER_MAX_REACH, f"span {span}"
            assert b.z == (b.z2 or 0), "sorters never span altitudes"

    def test_sorter_endpoints_reference_real_buildings(
        self, spec_fn: SpecFactory, power: bool
    ) -> None:
        p = SpineLayout(power=power).lay_out(spec_fn(), time_budget_s=0.5)
        n = len(p.buildings)
        for b in p.buildings:
            if not catalog.is_sorter(b.item_id):
                continue
            assert b.input_obj is not None and 0 <= b.input_obj < n
            assert b.output_obj is not None and 0 <= b.output_obj < n
            assert b.input_obj != b.output_obj

    def test_belt_chains_step_one_tile_and_at_most_one_level(
        self, spec_fn: SpecFactory, power: bool
    ) -> None:
        """A belt hands to an orthogonal neighbour, or to a junction on its tile.

        This used to demand "strictly eastward by one tile on the same lane",
        which was only true while every belt in the block was part of a
        west-to-east corridor lane.  Risers broke all three halves of that: a
        trunk runs south, a lane the trunk feeds runs east to west so its head is
        the tile the junction hands to, and a bridge changes altitude to cross
        another trunk.  What has to hold is the physical rule -- one tile, one
        level -- not the direction.
        """
        p = SpineLayout(power=power).lay_out(spec_fn(), time_budget_s=0.5)
        for i, b in enumerate(p.buildings):
            if not catalog.is_belt(b.item_id):
                continue
            nxt = b.output_obj
            if nxt is None:
                continue
            t = p.buildings[nxt]
            if t.item_id == catalog.SPLITTER_ID:
                assert (t.x, t.y, t.z) == (b.x, b.y, b.z), (
                    f"belt {i} feeds a junction it does not stand on"
                )
                continue
            assert catalog.is_belt(t.item_id)
            assert abs(t.x - b.x) + abs(t.y - b.y) == 1, f"belt {i} jumps a tile"
            assert abs(t.z - b.z) <= 1, f"belt {i} climbs more than one level"

    def test_placement_is_non_empty_and_has_area(
        self, spec_fn: SpecFactory, power: bool
    ) -> None:
        p = SpineLayout(power=power).lay_out(spec_fn(), time_budget_s=0.5)
        assert p.buildings
        assert p.area > 0


class TestLaneExtents:
    def test_lanes_are_trimmed_to_what_they_serve(self) -> None:
        """A tapped lane carries belt only where it is tapped, plus the run to
        the block edge for external inputs and products."""
        p = SpineLayout(power=False).lay_out(magnetic_ring_spec(), time_budget_s=0.5)
        belts = [b for b in p.buildings if catalog.is_belt(b.item_id)]
        min_x, _, max_x, _ = p.bounds
        full_width = max_x - min_x + 1
        lanes: dict[int, list[int]] = {}
        for b in belts:
            lanes.setdefault(b.y, []).append(b.x)
        assert lanes
        # At least one lane must be genuinely shorter than the block width, or
        # the trim did nothing.
        assert any(len(xs) < full_width for xs in lanes.values())

    def test_trimming_does_not_change_area(self) -> None:
        """Trimming removes belt tiles inside the bounding box, never resizes it."""
        p = SpineLayout(power=False).lay_out(magnetic_ring_spec(), time_budget_s=0.5)
        assert p.area > 0
        assert p.stats["belt_tiles"] > 0

    @pytest.mark.parametrize("power", [True, False], ids=["power", "no-power"])
    def test_no_lane_is_joined_to_nothing_at_both_ends(self, power: bool) -> None:
        """A corridor holds the lanes it is TAPPED for and nothing else.

        Before risers, an item crossing corridors needed a horizontal run in each
        one; a trunk in the east margin does that job now, and the intermediate
        copies became belt joined to nothing at either end.  Measured over the
        powered corpus while they were still emitted: 321 of 975 lanes, 34,372 of
        80,620 lane belt tiles, and a tile of corridor height each -- so they cost
        area as well as buildings.

        Asserted on the emitted geometry rather than on ``_lane_requirements``,
        so it fails if either the allocation or the emission reintroduces one.
        """
        p = SpineLayout(power=power).lay_out(magnetic_ring_spec(), time_budget_s=0.5)
        bs = p.buildings
        lanes: dict[int, list[int]] = {}
        for i, b in enumerate(bs):
            if catalog.is_belt(b.item_id) and b.z == 0 and b.yaw in (90.0, 270.0):
                lanes.setdefault(b.y, []).append(i)
        assert lanes
        sorter_ends: set[int] = set()
        for b in bs:
            if catalog.is_sorter(b.item_id):
                sorter_ends |= {x for x in (b.input_obj, b.output_obj) if x is not None}
        dead = []
        for y, idxs in lanes.items():
            own = set(idxs)
            if own & sorter_ends:
                continue
            # A trunk or bridge handing into this lane, or the lane handing out
            # to one: either end counts as joined.
            outward = any(
                bs[i].output_obj is not None and bs[i].output_obj not in own for i in idxs
            )
            inward = any(
                b.output_obj in own
                for j, b in enumerate(bs)
                if j not in own and catalog.is_belt(b.item_id)
            )
            if not (outward or inward):
                dead.append(y)
        assert not dead, f"{len(dead)} of {len(lanes)} lanes are joined to nothing"


def narrow_product_spec() -> BuildSpec:
    """A wide producing row above a single-machine consumer at the west end.

    Twelve 3-wide smelters make the block 36 columns; the three assemblers that
    drain them are packed from ``x = 0``.  So the ``gear`` they make is most of
    the block from the east edge and none at all from the west, which is the case
    that decides where a product should leave.
    """
    return BuildSpec(
        groups=(
            group("iron-ingot", "arc-smelter", 12, {"iron-ore": F(1)}, {"iron-ingot": F(1)}),
            group("gear", "assembling-machine-2", 3, {"iron-ingot": F(1)}, {"gear": F(1)}),
        ),
        external_inputs={"iron-ore": F(12)},
        outputs={"gear": F(3), "iron-ingot": F(9)},
        belt_item_id="conveyor-belt-3",
        belt_items_per_second=F(30),
        label="narrow-product",
    )


class TestAProductLeavesByTheNearerEdge:
    """Both block edges are equally physical, so the product should pick.

    A product lane used to be pinned east by convention.  The block is as wide
    as its WIDEST row, so a product made by a narrow row at the west end paid the
    whole width in belt to reach a side it had no reason to prefer -- measured on
    ``quantum-chip``, whose product lane ran 288 tiles with all four of its taps
    inside the first ten.

    A lane a riser has joined keeps the east exit: its east end is already
    committed to a trunk, and two things cannot own one end of a one-way belt.
    """

    @staticmethod
    def _lane(p: Placement, item: str) -> list[PlacedBuilding]:
        return [
            b
            for b in p.buildings
            if catalog.is_belt(b.item_id) and b.carries_item == item and b.z == 0
        ]

    def test_a_product_made_at_the_west_end_leaves_west(self) -> None:
        p = SpineLayout(power=False).lay_out(narrow_product_spec(), time_budget_s=0.5)
        lane = self._lane(p, "gear")
        assert lane, "the product got no lane at all"
        xs = [b.x for b in lane]
        assert min(xs) == 0, "the product never reaches the west edge"
        # The wide row is 36 columns; reaching the far side would be ~35 tiles of
        # belt carrying the product away from every machine that fills it.
        assert max(xs) < 12, f"the product still ran east to x={max(xs)}"

    def test_it_flows_towards_the_edge_it_leaves_by(self) -> None:
        """A belt is one-way: exiting west means the chain points west.

        Pinning the lane east while running it out to ``x = 0`` would fill the
        wrong end -- the items would pile up against the tail and the product
        would never reach the boundary, with every link resolving and every
        building present.
        """
        p = SpineLayout(power=False).lay_out(narrow_product_spec(), time_budget_s=0.5)
        by_index = {i: b for i, b in enumerate(p.buildings)}
        lane = [
            i
            for i, b in by_index.items()
            if catalog.is_belt(b.item_id) and b.carries_item == "gear" and b.z == 0
        ]
        assert len(lane) > 1, "too short to have a direction"
        steps = [
            by_index[by_index[i].output_obj].x - by_index[i].x  # type: ignore[index]
            for i in lane
            if by_index[i].output_obj in lane
        ]
        assert steps and all(s < 0 for s in steps), f"lane does not flow west: {steps}"

    def test_a_product_made_at_the_east_end_still_leaves_east(self) -> None:
        """The default is not lost -- only the choice is new."""
        spec = magnetic_ring_spec()
        p = SpineLayout(power=False).lay_out(spec, time_budget_s=0.5)
        lane = self._lane(p, "super-magnetic-ring")
        assert lane
        _min_x, _min_y, max_x, _max_y = p.bounds
        # The riser margin sits east of the content, so the product's own east
        # end is short of the placement bound rather than at it.
        assert max(b.x for b in lane) > min(b.x for b in lane)


class TestLaneExtentsAreOwnedByOneLane:
    """An item may hold several lanes in one corridor; each pays its own span.

    ``extents`` used to be keyed by ``(corridor, item)`` while the belts it sized
    were keyed by ``(corridor, depth)``, so every copy of an item's lane was
    stretched to the union of all of them -- a bottom-band copy tapped at columns
    5..30 emitted from 5 to 280 because its top-band sibling reached that far.
    Corpus-wide that was 261 ``belt.termination`` warnings naming 6,928 dead
    tiles; per-lane extents cut it to 133 and 3,583, and belt tiles by 5.1%.
    """

    #: ``wide_flow_spec`` is named rather than referenced because it is defined
    #: further down the file; it is the one fixture here that gives an item
    #: PARALLEL lanes, which is the shape the union bug stretched.
    @pytest.mark.parametrize("name", ["magnetic-ring", "wide-flow", "narrow-product"])
    def test_no_internal_lane_runs_past_its_own_last_tap(self, name: str) -> None:
        """Asserted through the validator, which measures the overshoot itself.

        A lane running to a block edge is exempt by construction -- those tiles
        carry the item in or out -- so what is left is exactly the class the
        union bug created.
        """
        from flab2bp.layout.spine import _adapt, _leaving_items
        from flab2bp.pipeline import _id_map

        make = {
            "magnetic-ring": magnetic_ring_spec,
            "wide-flow": wide_flow_spec,
            "narrow-product": narrow_product_spec,
        }[name]
        spec = make()
        groups, _edges = _adapt(spec)
        boundary = set(spec.external_inputs) | _leaving_items(groups, spec)
        p = SpineLayout(power=False).lay_out(spec, time_budget_s=0.5)
        report = validate.validate(p, spec, ids=_id_map(spec), expect_power=False)
        offenders = [
            f
            for f in report.warnings
            if f.check == "belt.termination"
            and p.buildings[f.buildings[0]].carries_item not in boundary
        ]
        assert not offenders, f"{name}: {[f.message for f in offenders]}"


class TestKnownGaps:
    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Direct insertion cannot survive a multi-input recipe in this skeleton. "
            "A sorter reaches 3 tiles and the gap between two rows is the corridor's "
            "lane count plus one, so an insert needs a corridor of at most 2 lanes. "
            "super-magnetic-ring takes three inputs; the moment any sibling input is "
            "belted, that corridor holds 3+ lanes, dy reaches 4, and the insert is "
            "unreachable however well aligned it is. Needs producer/consumer x "
            "alignment to be a solver decision rather than a greedy left-to-right "
            "pack -- see the measured cascade in the report."
        ),
    )
    def test_direct_insertion_survives_on_the_realistic_chain(self) -> None:
        p = SpineLayout(power=False, workers=DETERMINISTIC_WORKERS).lay_out(
            magnetic_ring_spec(), time_budget_s=0.5
        )
        assert p.stats["direct_inserts"] >= 1



def _sourced_belts(p: Placement) -> set[int]:
    """Belt tiles items can actually reach, by walking the emitted links.

    Deliberately independent of ``validate``: it starts from the sorters that
    put items onto a belt and from the block's west edge where external inputs
    enter, then propagates along ``output_obj`` and THROUGH junctions -- a
    splitter records no links of its own, so a belt naming it as ``input_obj``
    is fed by every belt naming it as ``output_obj``.
    """
    bs = p.buildings
    min_x, _, _, _ = p.bounds
    forward: dict[int, list[int]] = {}
    feeds_junction: dict[int, list[int]] = {}
    draws_from_junction: dict[int, list[int]] = {}
    for i, b in enumerate(bs):
        if not catalog.is_belt(b.item_id):
            continue
        if b.output_obj is not None:
            if bs[b.output_obj].item_id == catalog.SPLITTER_ID:
                feeds_junction.setdefault(b.output_obj, []).append(i)
            else:
                forward.setdefault(i, []).append(b.output_obj)
        if b.input_obj is not None and bs[b.input_obj].item_id == catalog.SPLITTER_ID:
            draws_from_junction.setdefault(b.input_obj, []).append(i)

    live: set[int] = set()
    for i, b in enumerate(bs):
        if catalog.is_sorter(b.item_id) and b.output_obj is not None:
            if catalog.is_belt(bs[b.output_obj].item_id):
                live.add(b.output_obj)
        elif catalog.is_belt(b.item_id) and b.x == min_x:
            live.add(i)  # the block's edge, where the player's belt arrives

    frontier = list(live)
    while frontier:
        i = frontier.pop()
        onward = list(forward.get(i, ()))
        for j, feeders in feeds_junction.items():
            if i in feeders:
                onward.extend(draws_from_junction.get(j, ()))
        for nxt in onward:
            if nxt not in live:
                live.add(nxt)
                frontier.append(nxt)
    return live


class TestRisersJoinTheCopies:
    """An item produced two rows above its consumer must actually arrive.

    This is the defect risers exist for.  The lanes were always emitted -- a
    copy in every corridor between producer and consumer -- and every sorter
    found one; nothing joined them, so the producer filled corridor r + 1 while
    the consumer drained corridor s and the item never travelled.
    """

    def test_every_consumed_item_reaches_its_consumer(self) -> None:
        p = SpineLayout(power=False).lay_out(magnetic_ring_spec(), time_budget_s=0.5)
        live = _sourced_belts(p)
        for i, b in enumerate(p.buildings):
            if not catalog.is_sorter(b.item_id):
                continue
            src = b.input_obj
            if src is None or not catalog.is_belt(p.buildings[src].item_id):
                continue  # picks up from a machine, i.e. an output sorter
            assert src in live, (
                f"sorter {i} draws {p.buildings[src].carries_item!r} from a belt "
                f"at ({p.buildings[src].x},{p.buildings[src].y}) nothing reaches"
            )

    def test_a_long_span_item_is_joined_across_corridors(self) -> None:
        """Not just "the buildings exist": follow the links from copy to copy."""
        p = SpineLayout(power=False).lay_out(magnetic_ring_spec(), time_budget_s=0.5)
        live = _sourced_belts(p)
        rows: dict[str, set[int]] = {}
        for i, b in enumerate(p.buildings):
            if catalog.is_belt(b.item_id) and b.carries_item and i in live:
                rows.setdefault(b.carries_item, set()).add(b.y)
        spanning = {item: ys for item, ys in rows.items() if len(ys) > 1}
        assert spanning, "no item reaches lanes in more than one corridor"
        # copper-ingot is made in one row and consumed two below it, which is
        # exactly the case the docstring used to claim was "correct and routable".
        assert len(rows.get("copper-ingot", set())) > 1

    def test_no_two_risers_share_a_cell(self) -> None:
        """Trunks are interval-coloured, so overlapping spans get their own column.

        A junction tile is the one legal exception: the corpus records a belt
        running through a splitter as two belts on that tile, and a branch adds a
        third.  Every other cell holds one riser belt or none.
        """
        for spec_fn in (magnetic_ring_spec, two_stage_spec):
            p = SpineLayout(power=False).lay_out(spec_fn(), time_budget_s=0.5)
            junction_cells = {
                (b.x, b.y, b.z) for b in p.buildings if b.item_id == catalog.SPLITTER_ID
            }
            cells = [
                (b.x, b.y, b.z)
                for b in p.buildings
                if catalog.is_belt(b.item_id)
                and (b.yaw == 180.0 or b.z > 0)
                and (b.x, b.y, b.z) not in junction_cells
            ]
            assert len(cells) == len(set(cells)), "two riser belts on one cell"

    def test_a_riser_never_stands_on_a_machine_or_a_lane(self) -> None:
        """The margin is east of everything; that is what makes it collision-free."""
        p = SpineLayout(power=False).lay_out(magnetic_ring_spec(), time_budget_s=0.5)
        occupied: set[tuple[int, int, Fraction]] = set()
        for b in p.buildings:
            if catalog.is_belt_integrated(b.item_id):
                continue
            if not catalog.building(b.item_id).occupies_tiles:
                continue
            occupied |= set(b.tiles())
        for b in p.buildings:
            if catalog.is_belt(b.item_id) and b.yaw == 180.0:
                assert (b.x, b.y, b.z) not in occupied, "a trunk stands on a machine"


class TestRisersClimbAtBeltSpeed:
    """A belt climbs half a level per tile, so a level costs TWO tiles of run.

    ``geom.altitude_step`` only bounds the step at one level per tile and knows
    nothing about run-up, so the validator was complicit in bridges that gained a
    whole level in a single tile -- twice what a belt can do -- and neither side
    of the build ever complained.  Spending the tiles honestly costs a ramp
    column beside each trunk: measured over the corpus, **+5.4% area in total,
    +8.4% on the median run, and nothing at all on the 10 of 66 runs that need no
    riser**.  The worst case is a nine-machine spec whose block is narrower than
    its margin (magnetic-coil, 90 -> 126 tiles).

    Asserted as the physical rule rather than as a column count, so a different
    margin layout that is equally honest still passes.

    The rule is NOT "no two consecutive links may both change altitude", which
    is what this asserted while ``z`` held a level index.  A ramp climbs
    ``BELT_CLIMB_PER_TILE`` on EVERY tile of its run, so ``0, 1/2, 1`` changes
    altitude on two consecutive links and is exactly what the corpus shows.
    What must not happen is a single link gaining more than a ramp can, which
    is what the old reading let through: it accepted ``0 -> 1`` across one tile
    as a single change and only objected to two of them in a row.
    """

    @pytest.mark.parametrize("power", [True, False], ids=["power", "no-power"])
    def test_no_belt_changes_level_twice_in_a_row(self, power: bool) -> None:
        p = SpineLayout(power=power).lay_out(magnetic_ring_spec(), time_budget_s=0.5)
        bs = p.buildings
        upstream: dict[int, int] = {}
        for i, b in enumerate(bs):
            o = b.output_obj
            if catalog.is_belt(b.item_id) and o is not None and catalog.is_belt(bs[o].item_id):
                upstream[o] = i
        climbing = [
            i
            for i, b in enumerate(bs)
            if catalog.is_belt(b.item_id)
            and b.output_obj is not None
            and catalog.is_belt(bs[b.output_obj].item_id)
            and bs[b.output_obj].z != b.z
        ]
        assert climbing, "the fixture is supposed to need bridges over trunks"
        for i in climbing:
            b = bs[i]
            nxt = bs[b.output_obj]  # type: ignore[index]
            dz = nxt.z - b.z
            dxy = abs(nxt.x - b.x) + abs(nxt.y - b.y)
            ramp = abs(dz) == catalog.BELT_CLIMB_PER_TILE and dxy == 1
            vertical = abs(dz) == catalog.VERTICAL_STEP and dxy == 0
            assert ramp or vertical, (
                f"belt {i} at ({b.x},{b.y},z={b.z}) changes altitude by {dz} "
                f"across {dxy} tile(s) to belt {b.output_obj}; a belt climbs "
                f"{catalog.BELT_CLIMB_PER_TILE} per tile of run, or a whole "
                f"{catalog.VERTICAL_STEP} for no run at all"
            )

    def test_the_ramp_column_is_only_charged_when_a_trunk_exists(self) -> None:
        """A spec with nothing to riser must not pay for a margin it never uses."""
        from flab2bp.layout.spine import _trunk_x

        p = SpineLayout(power=False).lay_out(single_recipe_spec(), time_budget_s=0.5)
        assert p.stats["risers"] == 0
        assert p.stats["riser_columns"] == 0
        # And the spacing itself leaves a free column west of every trunk.
        xs = [_trunk_x(10, c) for c in range(4)]
        assert all(b - a >= 2 for a, b in zip(xs, xs[1:], strict=False))
        assert xs[0] > 10


class TestLanesFlowTowardsTheirConsumers:
    """A belt is one-way, so a lane's direction decides which taps it serves.

    A lane filled by a producer and drained by a consumer WEST of it starves that
    consumer: the sorter reaches into a belt nothing ever carries past it.  The
    validator cannot see it -- every link resolves, the sorter is in reach, the
    belt is continuous -- so the build pastes, looks right, and one machine never
    runs.

    Measured over the 33 powered corpus runs before the fix: 3 lanes of 656.
    Rare, which is why it survived so long, and exactly the kind of thing a
    counted stat has to keep honest.
    """

    @pytest.mark.parametrize(
        "spec_fn",
        [single_recipe_spec, two_stage_spec, magnetic_ring_spec],
        ids=lambda f: f.__name__,
    )
    @pytest.mark.parametrize("power", [True, False], ids=["power", "no-power"])
    def test_no_sorter_draws_from_a_lane_nothing_reaches_it_on(
        self, spec_fn: SpecFactory, power: bool
    ) -> None:
        p = SpineLayout(power=power).lay_out(spec_fn(), time_budget_s=0.5)
        assert p.stats["starved_taps"] == 0.0

    def test_the_stat_actually_counts_something(self) -> None:
        """Guards the stat itself: an unservable lane must not read as clean.

        Drains at columns 1 and 20 with the only fill at 7 cannot both be served
        by one belt, whichever way it points -- so ``_lane_flow_gaps`` must say 1
        for each direction, not 0.
        """
        from flab2bp.layout.spine import _lane_flow_gaps

        fills = [(7, 7)]
        drains = [(1, 1), (20, 20)]
        assert _lane_flow_gaps(fills, drains, westward=False) == 1
        assert _lane_flow_gaps(fills, drains, westward=True) == 1
        assert _lane_flow_gaps(fills, [(20, 20)], westward=False) == 0
        assert _lane_flow_gaps(fills, [(1, 1)], westward=True) == 0


def wide_flow_spec() -> BuildSpec:
    """10 iron-ingot/s reaching two rows down, on a belt that carries 6.

    Built to bottleneck, and balanced so nothing else about it can be blamed.
    The ingot is consumed by BOTH the row below it and the row below that, so it
    has to travel through a trunk rather than straight across one corridor --
    which is where the whole flow used to end up on a single belt.

    ``belt_required_edges`` covers both consumers so the solver cannot answer the
    question by direct-inserting instead: this fixture is about lanes, and a
    direct insert would quietly remove the lane under test.
    """
    return BuildSpec(
        groups=(
            group("iron-ingot", "arc-smelter", 10, {"iron-ore": F(1)}, {"iron-ingot": F(1)}),
            group("gear", "assembling-machine-2", 5, {"iron-ingot": F(1)}, {"gear": F(1)}),
            group(
                "electric-motor",
                "assembling-machine-2",
                5,
                {"iron-ingot": F(1), "gear": F(1)},
                {"electric-motor": F(1)},
            ),
        ),
        external_inputs={"iron-ore": F(10)},
        outputs={"electric-motor": F(5)},
        belt_item_id="conveyor-belt-1",
        belt_items_per_second=F(6),
        belt_required_edges=frozenset(
            {("iron-ingot", "gear"), ("iron-ingot", "electric-motor")}
        ),
        label="wide-flow",
    )


class TestOneBeltIsNotEnough:
    """An item moving more than a belt carries needs more than one lane.

    Spine used to put an item's whole cross-corridor flow on a single lane and a
    single trunk, which caps the build at the belt's rate however many machines
    it contains -- the same failure mode as an undersized sorter, and just as
    invisible: it pastes, it runs, and it misses the number the spec promised.
    Live on the corpus, not hypothetical: ``quantum-chip`` moves 48 crude-oil/s
    and 48 refined-oil/s against a 30/s Mk.III belt.
    """

    def test_the_fixture_really_does_overflow_a_belt(self) -> None:
        """Arithmetic, so the rest of this class cannot pass vacuously."""
        from flab2bp.layout.spine import belt_capacity

        spec = wide_flow_spec()
        moved = sum(
            g.inputs_per_machine.get("iron-ingot", F(0)) * g.count for g in spec.groups
        )
        assert moved > belt_capacity(spec), f"{moved}/s fits on one belt after all"

    def test_the_overflowing_item_gets_parallel_lanes(self) -> None:
        from flab2bp.layout.spine import _adapt, _lane_copies

        spec = wide_flow_spec()
        groups, edges = _adapt(spec)
        assert _lane_copies(groups, edges, set(), spec)["iron-ingot"] == 2

        p = SpineLayout(power=False).lay_out(spec, time_budget_s=0.5)
        rows = {
            b.y
            for b in p.buildings
            if catalog.is_belt(b.item_id) and b.carries_item == "iron-ingot" and b.z == 0
            and b.yaw in (90.0, 270.0)
        }
        assert len(rows) >= 4, (
            f"expected two parallel lanes in each of two corridors, got {len(rows)}"
        )

    def test_the_parallel_lanes_get_a_trunk_each(self) -> None:
        """One trunk for both copies would put the flow back on one belt."""
        p = SpineLayout(power=False).lay_out(wide_flow_spec(), time_budget_s=0.5)
        trunks = {
            b.x
            for b in p.buildings
            if catalog.is_belt(b.item_id)
            and b.yaw == 180.0
            and b.carries_item == "iron-ingot"
        }
        assert len(trunks) == 2, f"expected two trunk columns, got {sorted(trunks)}"

    def test_the_split_spec_validates_clean(self) -> None:
        """Not just belt capacity: splitting must not break anything else.

        ``flow.conservation`` is the one that catches a lazy split.  Ten
        producers deal 5 and 5, but two five-machine consumer groups both hand
        their remainder to the same lane unless the deal is rotated -- 6/s asked
        of a lane carrying 5, on a spec whose totals balance exactly.
        """
        from flab2bp.pipeline import _id_map

        spec = wide_flow_spec()
        p = SpineLayout(power=False).lay_out(spec, time_budget_s=0.5)
        report = validate.validate(p, spec, ids=_id_map(spec), expect_power=False)
        assert report.ok, "\n".join(
            f"{f.check}: {f.message}" for f in report.errors[:5]
        )

    def test_splitting_is_given_up_rather_than_the_layout(self) -> None:
        """Coverage outranks density, and it outranks throughput too.

        A corridor deep enough to hold the extra lanes may be too deep to wire.
        When that happens the split is abandoned and the build ships with an
        honest ``flow.belt_capacity`` error, because a build reported as too slow
        can be pasted and widened by hand and a build that does not exist cannot.
        """
        from flab2bp.layout.spine import _adapt, _lane_requirements, _topological_rows

        spec = wide_flow_spec()
        groups, edges = _adapt(spec)
        rows = _topological_rows(groups, edges)
        lanes, _mixed, copies = _lane_requirements(groups, edges, rows, set(), spec)
        assert copies["iron-ingot"] == 2
        assert sum(c.count("iron-ingot") for c in lanes) >= 4

        # Reach is 3 lanes a side, so an item wanting more than the whole budget
        # cannot be allocated at all -- and `_lane_requirements` must still
        # produce a layout rather than propagating that.
        from flab2bp.layout.spine import _allocate_lanes

        with pytest.raises(ValueError):
            _allocate_lanes(groups, edges, rows, set(), spec, dict.fromkeys(copies, 99))


class TestBundleLaneSeating:
    @staticmethod
    def _quantum_chip_spec() -> BuildSpec:
        from flab2bp.bench.corpus import entry
        from flab2bp.lab.data import load_vendored
        from flab2bp.lab.url import parse_url
        from flab2bp.rates.candidates import build_candidates

        candidates = build_candidates(
            load_vendored(), parse_url(entry("quantum-chip").url), count=3
        ).candidates
        buildable = [candidate for candidate in candidates if not candidate.spray_lanes]
        return min(buildable, key=lambda candidate: candidate.machine_count)

    @pytest.mark.slow
    def test_degraded_quantum_row_keeps_parallel_oil_bundles(self) -> None:
        """The real mixed-height row is feasible without flattening either oil."""
        from flab2bp.layout.spine import _adapt, _emit, _lane_requirements, _Plan
        from flab2bp.pipeline import _id_map

        spec = self._quantum_chip_spec()
        groups, edges = _adapt(spec)
        rows = [
            ["plasma-refining#11"],
            ["copper-ingot#2", "energetic-graphite#3", "iron-ingot#7"],
            ["high-purity-silicon#6", "plastic#12"],
            ["titanium-ingot#18"],
            ["sulfuric-acid#15"],
            ["graphene#5"],
            ["organic-crystal#9"],
            ["circuit-board#1", "microcrystalline-component#8"],
            ["processor#13"],
            ["glass#4", "titanium-crystal#16"],
            ["casimir-crystal#0"],
            ["titanium-glass#17"],
            ["plane-filter#10"],
            ["quantum-chip#14"],
        ]

        lanes, mixed, copies = _lane_requirements(groups, edges, rows, set(), spec)

        assert copies["crude-oil"] == 2
        assert copies["refined-oil"] == 2
        assert sum(corridor.count("crude-oil") for corridor in lanes) == 2
        assert sum(corridor.count("refined-oil") for corridor in lanes) == 8
        assert mixed == {}

        placement = _emit(spec, _Plan(rows=rows, lanes=lanes, mixed=mixed), power=True)
        report = validate.validate(
            placement, spec, ids=_id_map(spec), expect_power=True
        )
        capacity_errors = [
            finding for finding in report.errors if finding.check == "flow.belt_capacity"
        ]
        assert not capacity_errors, "\n".join(
            finding.message for finding in capacity_errors
        )

    def test_bounded_dfs_matches_brute_force_for_generated_bundle_cases(self) -> None:
        """For at most six bundles, DFS finds a seat iff exhaustive enumeration does."""
        import random

        from flab2bp.layout.spine import _seat_nonmixed_bands

        rng = random.Random(0x5E47)

        def fits(
            band: set[str], charges: dict[str, int], copies: dict[str, int], reach: int
        ) -> bool:
            depths = sorted(
                (charges[item] for item in band for _ in range(copies[item])),
                reverse=True,
            )
            return all(charge + depth + 1 <= reach for depth, charge in enumerate(depths))

        for case in range(512):
            item_count = rng.randrange(7)
            items = [f"item-{index}" for index in range(item_count)]
            reach = rng.randrange(1, 4)
            copies = dict.fromkeys(items, 1)
            for _ in range(rng.randrange(7 - item_count)):
                if not items:
                    break
                copies[rng.choice(items)] += 1
            upper_charge = {item: rng.randrange(reach + 1) for item in items}
            lower_charge = {item: rng.randrange(reach + 1) for item in items}
            prefers_upper = {item: bool(rng.randrange(2)) for item in items}

            feasible = False
            for mask in range(1 << item_count):
                upper = {item for index, item in enumerate(items) if mask & (1 << index)}
                lower = set(items) - upper
                if fits(upper, upper_charge, copies, reach) and fits(
                    lower, lower_charge, copies, reach
                ):
                    feasible = True
                    break

            seated = _seat_nonmixed_bands(
                items,
                prefers_upper,
                upper_charge,
                lower_charge,
                reach,
                copies,
            )
            assert (seated is not None) is feasible, (
                f"case {case}: items={items}, copies={copies}, "
                f"upper={upper_charge}, lower={lower_charge}, reach={reach}"
            )
            if seated is not None:
                upper, lower = seated
                assert upper.isdisjoint(lower)
                assert upper | lower == set(items)
                assert fits(upper, upper_charge, copies, reach)
                assert fits(lower, lower_charge, copies, reach)

    def test_bounded_dfs_breaks_equal_choices_deterministically(self) -> None:
        from flab2bp.layout.spine import _seat_nonmixed_bands

        args = (
            ["beta", "alpha"],
            {"alpha": True, "beta": True},
            {"alpha": 0, "beta": 0},
            {"alpha": 0, "beta": 0},
            1,
            {"alpha": 1, "beta": 1},
        )
        assert [_seat_nonmixed_bands(*args) for _ in range(3)] == [
            ({"beta"}, {"alpha"}),
            ({"beta"}, {"alpha"}),
            ({"beta"}, {"alpha"}),
        ]


class TestPower:
    def test_no_power_emits_zero_towers(self) -> None:
        p = SpineLayout(power=False).lay_out(magnetic_ring_spec(), time_budget_s=0.5)
        assert not any(b.item_id == catalog.TESLA_TOWER_ID for b in p.buildings)
        assert p.stats["towers"] == 0

    def test_power_emits_towers(self) -> None:
        p = SpineLayout(power=True).lay_out(magnetic_ring_spec(), time_budget_s=0.5)
        assert p.stats["towers"] > 0

    def test_every_powered_building_is_covered(self) -> None:
        """Checked with true Euclidean distance over every footprint tile.

        Deliberately independent of the linearised reach table, so a
        linearisation error would show up here rather than agree with itself.
        """
        p = SpineLayout(power=True).lay_out(magnetic_ring_spec(), time_budget_s=0.5)
        centres = [
            (b.x + b.width / 2, b.y + b.height / 2)
            for b in p.buildings
            if b.item_id == catalog.TESLA_TOWER_ID
        ]
        radius = float(catalog.TESLA_COVER_RADIUS)
        for b in p.buildings:
            if b.item_id in catalog.UNPOWERED_ITEM_IDS or b.item_id == catalog.TESLA_TOWER_ID:
                continue
            for tx, ty, _ in b.tiles():
                px, py = tx + 0.5, ty + 0.5
                assert any(math.dist((px, py), c) <= radius + 1e-9 for c in centres), (
                    f"unpowered tile {(tx, ty)} of item {b.item_id}"
                )

    def test_tower_network_is_connected(self) -> None:
        """Union-find over true Euclidean link distance, independent of the
        by-construction argument that placed them."""
        p = SpineLayout(power=True).lay_out(magnetic_ring_spec(), time_budget_s=0.5)
        towers = [
            (b.x + b.width / 2, b.y + b.height / 2)
            for b in p.buildings
            if b.item_id == catalog.TESLA_TOWER_ID
        ]
        assert towers
        link = float(catalog.TESLA_LINK_DISTANCE)
        seen = {0}
        frontier = [0]
        while frontier:
            i = frontier.pop()
            for j, t in enumerate(towers):
                if j not in seen and math.dist(towers[i], t) <= link + 1e-9:
                    seen.add(j)
                    frontier.append(j)
        assert len(seen) == len(towers), "tower network is disconnected"


class TestProliferation:
    def test_spine_supplies_a_proliferated_spec_from_an_elevated_spur(self) -> None:
        """This assertion has now been wrong twice, in opposite directions.

        First it asserted spine LAID THIS OUT, and checked that a coater
        consumes no grid tile -- on a placement whose coaters were fed by a
        SORTER, a connection the game cannot make. A Spray Coater ships zero
        insert poses, `BuildTool_Inserter` will not target a building with none,
        and all eight coaters in the fixture corpus carry no connection at all.

        Then it asserted spine REFUSED, and named "an elevated lane in the
        coater's own row" as the missing capability. That was wrong too:
        `_feed_coater` had always placed the drop at `z = 1`. What was missing
        was the REACH -- it wanted one proliferator tile to be the lane's tail
        and be adjacent to the drop at the same time, which nothing arranges.

        So this pins the geometry rather than either verdict: the coater is
        placed, an elevated spur reaches it, and `game.addon_supply` -- the
        game's own positional rule, one tile behind and one LEVEL up -- is
        satisfied. Each of those is asserted separately, because a placement
        with no coater in it satisfies `addon_supply` trivially and that is
        exactly how the previous version passed on geometry the game refuses.
        """
        spec = two_stage_spec()
        prolif = BuildSpec(
            groups=spec.groups,
            external_inputs={**spec.external_inputs, "proliferator-3": F(1) / 2},
            outputs=spec.outputs,
            belt_item_id=spec.belt_item_id,
            belt_items_per_second=spec.belt_items_per_second,
            spray_lanes={"iron-ingot": False},
            label="prolif",
        )
        p = SpineLayout(power=False).lay_out(prolif, time_budget_s=0.5)
        coaters = [b for b in p.buildings if b.item_id == catalog.SPRAY_COATER_ID]
        assert coaters, "no coater placed, so nothing below tests anything"
        elevated = [b for b in p.buildings if b.z and b.z > 0]
        assert elevated, "coater placed with no elevated supply anywhere"
        report = validate.validate(
            p, prolif, ids=validate.id_map(prolif), expect_power=False
        )
        assert not report.by_check("game.addon_supply"), [
            f.message for f in report.by_check("game.addon_supply")
        ]
        assert report.ok, sorted({f.check for f in report.errors})

    def test_a_placed_coater_is_anchored_on_its_belt_tile_not_on_its_collider(
        self,
    ) -> None:
        """A belt addon's placement is 1x1 whatever its collider spans.

        ``catalog.footprint`` reports a Spray Coater as 1x3, which is true of
        its collider: the box the game tests is 3.8 world units long about the
        coater's own centre, so it covers three tile centres along the belt.
        Its POSITION is still the belt tile it rides -- ``addonAreaPoses`` area
        0 is "the cargo belt it rides" -- and ``tile_to_local_offset`` reads the
        centre off the width, so emitting it 1x3 moves it a tile off the belt.
        At yaw 90 that became an Oil Refinery and a Spray Coater two tiles apart
        failing ``geom.collide``, and it cost spine ten corpus cells before the
        anchor was pinned here.
        """
        spec = two_stage_spec()
        prolif = BuildSpec(
            groups=spec.groups,
            external_inputs={**spec.external_inputs, "proliferator-3": F(1) / 2},
            outputs=spec.outputs,
            belt_item_id=spec.belt_item_id,
            belt_items_per_second=spec.belt_items_per_second,
            spray_lanes={"iron-ingot": False},
            label="prolif",
        )
        p = SpineLayout(power=False).lay_out(prolif, time_budget_s=0.5)
        coaters = [b for b in p.buildings if b.item_id == catalog.SPRAY_COATER_ID]
        assert coaters, "no coater placed, so nothing below tests anything"
        assert all((b.width, b.height) == (1, 1) for b in coaters), [
            (b.x, b.y, b.width, b.height) for b in coaters
        ]
        # And the catalog really does disagree, so this is not vacuous.
        assert catalog.footprint(catalog.SPRAY_COATER_ID) == (1, 3)
        # Every coater sits exactly on a belt tile of the lane it rides.
        belts = {(b.x, b.y, b.z) for b in p.buildings if catalog.is_belt(b.item_id)}
        assert all((b.x, b.y, b.z) in belts for b in coaters), [
            (b.x, b.y, b.z) for b in coaters
        ]

    def test_a_coater_still_consumes_no_grid_tile(self) -> None:
        """The half of the old test that was about geometry, kept.

        A coater being a belt addon is a fact about the catalog and is what
        makes proliferation nearly free in area. It never needed a placement to
        demonstrate it, which is why the old test could pass while the placement
        it built was unbuildable.
        """
        assert not catalog.building(catalog.SPRAY_COATER_ID).occupies_tiles

    def test_belt_required_edges_are_never_direct_inserted(self) -> None:
        spec = two_stage_spec()
        required = frozenset({("iron-ingot", "gear")})
        prolif = BuildSpec(
            groups=spec.groups,
            external_inputs=spec.external_inputs,
            outputs=spec.outputs,
            belt_item_id=spec.belt_item_id,
            belt_items_per_second=spec.belt_items_per_second,
            belt_required_edges=required,
            label="prolif",
        )
        layout = SpineLayout(power=False)
        p = layout.lay_out(prolif, time_budget_s=0.5)
        assert p.stats["direct_inserts"] == 0


def _forced_belt(spec: BuildSpec, edges: frozenset[tuple[str, str]]) -> BuildSpec:
    """The same spec with ``edges`` ineligible for direct insertion.

    This is the controlled A/B for direct insertion: identical geometry, one
    switch. Comparing against a *different* spec would confound the mechanism
    with whatever else changed.
    """
    return BuildSpec(
        groups=spec.groups,
        external_inputs=spec.external_inputs,
        outputs=spec.outputs,
        belt_item_id=spec.belt_item_id,
        belt_items_per_second=spec.belt_items_per_second,
        label=spec.label,
        belt_required_edges=edges,
    )


class TestDirectInsertion:
    """A producer within sorter reach of its consumer needs no belt between them.

    Every test here pins ``workers=DETERMINISTIC_WORKERS``: the shipping default
    is a multi-worker portfolio whose results vary run to run, and an A/B that
    varies with the wind proves nothing about the mechanism.
    """

    def test_an_adjacent_pair_is_direct_inserted(self) -> None:
        p = SpineLayout(power=False, workers=DETERMINISTIC_WORKERS).lay_out(
            two_stage_spec(), time_budget_s=0.5
        )
        assert p.stats["direct_inserts"] >= 1

    def test_direct_insertion_removes_belt_tiles(self) -> None:
        """The counter moving is not enough -- the belts must actually be gone."""
        spec = two_stage_spec()
        forced = _forced_belt(spec, frozenset({("iron-ingot", "gear")}))
        w = DETERMINISTIC_WORKERS
        direct = SpineLayout(power=False, workers=w).lay_out(spec, time_budget_s=0.5)
        belted = SpineLayout(power=False, workers=w).lay_out(forced, time_budget_s=0.5)

        assert direct.stats["direct_inserts"] >= 1
        assert belted.stats["direct_inserts"] == 0
        assert direct.stats["belt_tiles"] < belted.stats["belt_tiles"]

    def test_a_direct_sorter_joins_two_machines_with_no_belt(self) -> None:
        """The emitted sorter must span machine to machine, not machine to belt."""
        p = SpineLayout(power=False, workers=DETERMINISTIC_WORKERS).lay_out(
            two_stage_spec(), time_budget_s=0.5
        )
        machines = set(machines_of(p))
        joins = [
            b
            for b in p.buildings
            if catalog.is_sorter(b.item_id)
            and b.input_obj in machines
            and b.output_obj in machines
        ]
        assert joins, "no machine-to-machine sorter was emitted"
        for b in joins:
            assert b.x2 is not None and b.y2 is not None
            span = abs(b.x - b.x2) + abs(b.y - b.y2)
            assert 1 <= span <= catalog.SORTER_MAX_REACH
            assert b.z == (b.z2 or 0), "sorters never span altitudes"

    def test_a_belt_required_edge_is_never_direct_inserted(self) -> None:
        """Spray is applied by a belt-mounted coater, so a sprayed input must
        arrive belted. Direct-inserting one silently under-produces."""
        forced = _forced_belt(two_stage_spec(), frozenset({("iron-ingot", "gear")}))
        p = SpineLayout(power=False, workers=DETERMINISTIC_WORKERS).lay_out(
            forced, time_budget_s=0.5
        )
        assert p.stats["direct_inserts"] == 0
        machines = set(machines_of(p))
        assert not [
            b
            for b in p.buildings
            if catalog.is_sorter(b.item_id)
            and b.input_obj in machines
            and b.output_obj in machines
        ]

    def test_direct_insertion_never_leaves_a_machine_unfed(self) -> None:
        """Dropping a lane must be paired with emitting the sorter that replaces
        it, or the consumer is simply starved."""
        w = DETERMINISTIC_WORKERS
        for spec_fn in (two_stage_spec, magnetic_ring_spec):
            p = SpineLayout(power=False, workers=w).lay_out(spec_fn(), time_budget_s=0.5)
            fed = {b.output_obj for b in p.buildings if catalog.is_sorter(b.item_id)}
            for i in machines_of(p):
                assert i in fed or not p.buildings[i].input_obj, f"machine {i} unfed"

    def test_direct_insertion_never_leaves_a_producer_undrained(self) -> None:
        """The mirror of the test above, and the half that was missing.

        Emission paired each CONSUMER with a producer and stopped there.  When
        producers outnumbered consumers -- or when two consumers picked the same
        producer -- the leftover producers got no sorter, and their belt lane had
        already been dropped by the insert, so they backed up.  Measured over the
        66 solved corpus runs: ``machine.output_removed`` on plastic, processor,
        energy-matrix, information-matrix and quantum-chip.
        """
        w = DETERMINISTIC_WORKERS
        for spec_fn in (two_stage_spec, magnetic_ring_spec, wide_flow_spec):
            p = SpineLayout(power=False, workers=w).lay_out(spec_fn(), time_budget_s=0.5)
            drained = {b.input_obj for b in p.buildings if catalog.is_sorter(b.item_id)}
            for i in machines_of(p):
                assert i in drained, (
                    f"machine {i} produces something nothing takes away; it backs up"
                )

    def test_a_pair_must_share_a_column_in_both_directions(self) -> None:
        """The feasibility test the emission contract needs.

        A sorter runs in a straight line, so an insert is only realizable when
        every producer AND every consumer has a partner whose footprint overlaps
        it in x.  Asking only about consumers is what let producers fall out.
        """
        from flab2bp.layout.spine import _column_overlap, _every_machine_pairs

        assert _column_overlap(0, 3, 2, 3) == 2
        assert _column_overlap(0, 3, 3, 3) is None
        # Two producers, one consumer, and only one of the producers overlaps it.
        assert not _every_machine_pairs([0, 3], 3, [3], 3)
        # Both overlap: a 6-wide consumer straddles them.
        assert _every_machine_pairs([0, 3], 3, [0], 6)


#: A 24-group build whose spine plans put a machine-to-machine sorter and a belt
#: tap on the SAME slot of the same Matrix Lab.  It is here as a URL rather than
#: as a hand-built spec because a hand-built one could not be found: 256
#: generated producer/consumer shapes across four machine kinds, every plan of
#: every sweep, produced no collision at all.  The geometry needs a direct
#: insert whose span CROSSES the corridor that also feeds the consumer's north
#: face, and that only turns up on a graph with enough items to make the
#: corridor two deep.
_SHARED_SLOT_URL = (
    "https://factoriolab.github.io/dsp/list?z=eJxFyr0KwkAQReG3meJWO8GQapq7GDtJBMVt1UUkLoGA"
    "Ept5dhH.uo.DGY1naJDReMSiDoC-.Pi7QRU-3KH6HQn6zSTqt7OhlWJEkGIJQS6HbJQpz9Yh4YQBN3ANbsE9"
    "ODiviK3HFWLvcSOlTJacvvRe7qb6BOgIKRo_&v=11"
)


#: The row and lane assignment ``_solve_plan`` hands back for that URL when the
#: sweep is starved -- one group per row, which is what CP-SAT settles for at
#: the pipeline's own budget.  It is FROZEN rather than solved for, because the
#: collision only appears in this shape: give the same sweep a full second per
#: width and every plan it returns is clean, so a test that solved would go
#: green on a fast machine and stay silent about the emitter.
_SHARED_SLOT_ROWS = [
    ["circuit-board#1"],
    ["energetic-graphite#6"],
    ["gear#7"],
    ["glass#8"],
    ["graphene-advanced#9"],
    ["magnetic-coil#12"],
    ["microcrystalline-component#13"],
    ["diamond#3"],
    ["plastic#17"],
    ["titanium-glass#23"],
    ["deuterium#2"],
    ["electric-motor#4"],
    ["processor#18"],
    ["organic-crystal#14"],
    ["electromagnetic-turbine#5"],
    ["titanium-crystal#22"],
    ["particle-container#15"],
    ["casimir-crystal#0"],
    ["strange-matter#21"],
    ["plane-filter#16"],
    ["graviton-lens#10"],
    ["quantum-chip#19"],
    ["gravity-matrix#11"],
    ["space-warper-advanced#20"],
]

_SHARED_SLOT_LANES = [
    ["copper-ingot", "iron-ingot"],
    ["circuit-board", "coal"],
    ["energetic-graphite", "iron-ingot"],
    ["gear", "stone"],
    ["glass", "fire-ice"],
    ["graphene", "hydrogen", "copper-ingot", "magnet"],
    ["magnetic-coil", "copper-ingot", "high-purity-silicon"],
    ["microcrystalline-component", "energetic-graphite"],
    ["diamond", "energetic-graphite", "refined-oil"],
    ["plastic", "glass", "titanium-ingot", "water"],
    ["titanium-glass", "hydrogen"],
    ["deuterium", "gear", "iron-ingot", "magnetic-coil"],
    ["electric-motor", "circuit-board", "microcrystalline-component"],
    ["processor", "plastic", "refined-oil"],
    ["organic-crystal", "water", "electric-motor", "magnetic-coil"],
    ["electromagnetic-turbine", "organic-crystal", "titanium-ingot"],
    ["titanium-crystal", "copper-ingot", "electromagnetic-turbine", "graphene"],
    ["particle-container", "graphene", "hydrogen", "titanium-crystal"],
    ["casimir-crystal", "deuterium", "iron-ingot", "particle-container"],
    ["strange-matter", "casimir-crystal", "titanium-glass"],
    ["plane-filter", "diamond", "strange-matter"],
    ["graviton-lens", "plane-filter", "processor"],
    ["graviton-lens"],
    [],
    ["space-warper"],
]

#: Two machine-to-machine edges, and the second one is the whole test: the
#: quantum-chip row inserts straight into the Matrix Lab row below it, and the
#: lab is ALSO fed by belt out of the corridor the insert crosses.
_SHARED_SLOT_DIRECT = {
    ("gravity-matrix#11", "space-warper-advanced#20", "gravity-matrix"),
    ("quantum-chip#19", "gravity-matrix#11", "quantum-chip"),
}


class TestOneSlotHoldsOneConnection:
    """A direct insert and a belt tap may not book the same machine slot.

    ``_place_sorters`` already rationed slots among the LANE taps, and it was
    right to: ``entityConnPool[objId * 16 + slot]`` is one int per
    ``(object, slot)`` and ``WriteObjectConn`` evicts the sitting tenant rather
    than refusing, so a doubly-named slot pastes with one sorter unwired and the
    two of them standing on one tile.  What it could not ration was the
    direct-insert pass, which ran FIRST, took a slot on each of its two peers,
    and told nobody -- the ledger was declared empty on the line after it.

    Measured on this URL before the fix: the machine-to-machine sorter out of
    the quantum-chip row ended on tile (1, 157), and so did the Matrix Lab's
    input tap from the corridor above it.  Both are slot 6.  Of the eight plans
    one sweep returns, six or seven carried it, the densest one every time, and
    whether the build survived came down to whether some later plan happened to
    be clean: 3 of 20 builds at the pipeline's own 2s budget refused outright.
    """

    @staticmethod
    def _spec() -> BuildSpec:
        from flab2bp.lab.data import load_vendored
        from flab2bp.lab.url import parse_url
        from flab2bp.rates.candidates import build_candidates

        cands = build_candidates(
            load_vendored(), parse_url(_SHARED_SLOT_URL), count=3
        ).candidates
        return next(c for c in cands if c.label.endswith("no-proliferator"))

    @staticmethod
    def _plan() -> _Plan:
        return _Plan(
            rows=[list(r) for r in _SHARED_SLOT_ROWS],
            lanes=[list(c) for c in _SHARED_SLOT_LANES],
            direct=set(_SHARED_SLOT_DIRECT),
            solver_status="OPTIMAL",
        )

    @pytest.mark.slow
    def test_the_direct_insert_and_the_belt_tap_take_different_slots(self) -> None:
        from flab2bp.layout import spine

        spec = self._spec()
        placement = spine._emit(
            spec, self._plan(), power=False, belt_vertical_construction=True
        )
        report = validate.certify(placement, spec, expect_power=False)
        shared = [f for f in report.errors if f.check == "game.slot_occupancy"]
        assert not shared, shared[0].message

    @pytest.mark.slow
    def test_the_frozen_plan_still_direct_inserts_into_a_belt_fed_machine(self) -> None:
        """Without this the test above can go green by going vacuous.

        A change that stopped direct-inserting into the lab at all, or stopped
        belting anything to it, would remove the collision and prove nothing.
        """
        spec = self._spec()
        from flab2bp.layout import spine

        placement = spine._emit(
            spec, self._plan(), power=False, belt_vertical_construction=True
        )
        bs = placement.buildings
        machine_to_machine = [
            b
            for b in bs
            if catalog.is_sorter(b.item_id)
            and b.input_obj is not None
            and b.output_obj is not None
            and not catalog.is_belt(bs[b.input_obj].item_id)
            and not catalog.is_belt(bs[b.output_obj].item_id)
        ]
        assert machine_to_machine, "the frozen plan no longer direct-inserts anything"
        fed_by_both = {
            b.output_obj for b in machine_to_machine if b.output_obj is not None
        } & {
            b.output_obj
            for b in bs
            if catalog.is_sorter(b.item_id)
            and b.input_obj is not None
            and b.output_obj is not None
            and catalog.is_belt(bs[b.input_obj].item_id)
        }
        assert fed_by_both, (
            "no machine is both direct-inserted into and belt-fed, so the "
            "collision this class exists for cannot occur"
        )


class TestSolverBehaviour:
    def test_solved_area_beats_the_seed_construction_outright(self) -> None:
        """Guards the silent-fallback class of bug.

        ``lay_out`` once swallowed an exception and returned a fallback that
        looked solved on every spec; it went unnoticed until a test compared the
        two areas and found them identical.

        The comparison survives the fallback's deletion because the greedy
        construction survives it: ``fallback_plan`` is now the CP-SAT warm start
        and width-sweep seed, so emitting it directly still yields exactly the
        layout ``lay_out`` used to degrade to.  Solving must beat it.
        """
        spec = magnetic_ring_spec()
        w = DETERMINISTIC_WORKERS
        solved = SpineLayout(power=False, workers=w).lay_out(spec, time_budget_s=0.5)
        seed = _emit(spec, fallback_plan(spec), power=False)
        assert solved.stats["fallback_used"] == 0.0
        assert solved.stats["solver_rejected"] == 0.0
        assert solved.area < seed.area

    def test_no_budget_refuses_rather_than_returning_something(self) -> None:
        """A zero budget is a refusal, not a licence to hand back the seed.

        The seed construction is not routable, so returning it was returning a
        broken layout that measured SMALLER than a correct one -- and the
        bake-off would then have preferred it.
        """
        with pytest.raises(NoValidLayout) as exc:
            SpineLayout(power=True).lay_out(magnetic_ring_spec(), time_budget_s=0.0)
        assert "solver was never asked" in exc.value.reason

    @pytest.mark.uncached_layout
    def test_deterministic_for_a_fixed_budget(self) -> None:
        """Reproducibility is the property under test here, so pin workers.

        The shipping default is multi-worker, which is deliberately
        nondeterministic -- CP-SAT runs a portfolio and takes whichever
        strategy wins. That is worth 23% density, so the bake-off keeps it
        and absorbs the variance by repeating cells. This test pins
        DETERMINISTIC_WORKERS because it asserts run-to-run identity.
        """
        w = DETERMINISTIC_WORKERS
        a = SpineLayout(power=True, workers=w).lay_out(magnetic_ring_spec(), time_budget_s=0.5)
        b = SpineLayout(power=True, workers=w).lay_out(magnetic_ring_spec(), time_budget_s=0.5)
        assert a.buildings == b.buildings

    def test_solving_is_no_worse_than_the_seed_construction(self) -> None:
        spec = magnetic_ring_spec()
        solved = SpineLayout(power=False).lay_out(spec, time_budget_s=0.5)
        seed = _emit(spec, fallback_plan(spec), power=False)
        assert solved.area <= seed.area

    def test_a_refusal_says_which_failure_mode_it_was(self) -> None:
        """One flag for three failure modes is how a dead solver hid.

        ``fallback_used=1`` alone could mean "no budget", "nothing routable" or
        "emission rejected the plan", and telling them apart mattered: the
        strategy stopped solving real specs entirely and the flag looked the
        same as a deliberate ``time_budget_s=0``.

        The reasons outlived the fallback -- they ride on ``NoValidLayout`` now
        instead of on a degraded placement's stats -- and the distinction still
        earns its keep, because a structural limit in the row model and a search
        that ran out of time call for opposite fixes.
        """
        with pytest.raises(NoValidLayout) as exc:
            SpineLayout(power=False).lay_out(two_stage_spec(), time_budget_s=0.0)
        assert "never asked" in exc.value.reason
        assert exc.value.spec_label == two_stage_spec().label

        solved = SpineLayout(power=False).lay_out(two_stage_spec(), time_budget_s=0.5)
        assert solved.stats["fallback_reason"] == FALLBACK_NONE
        assert solved.stats["fallback_used"] == 0.0

    def test_stats_carry_the_bake_off_fields(self) -> None:
        p = SpineLayout(power=True).lay_out(two_stage_spec(), time_budget_s=0.5)
        for key in (
            "area",
            "machines",
            "belt_tiles",
            "sorters",
            "towers",
            "direct_inserts",
            "solver_status",
            "hit_time_budget",
            "fallback_used",
        ):
            assert key in p.stats, key


def seven_item_spec() -> BuildSpec:
    """One Matrix Lab running the real ``universe-matrix`` recipe: 6 in, 1 out.

    Shaped from the corpus spec that this skeleton cannot hold, and kept
    hand-built so the test costs no rate solve.  Every ingredient arrives as an
    external input, which is the *friendliest* possible case -- no producer group
    means no precedence edge and nothing else competing for a corridor -- and it
    still cannot be wired.
    """
    ingredients = (
        "electromagnetic-matrix",
        "energy-matrix",
        "structure-matrix",
        "information-matrix",
        "gravity-matrix",
        "antimatter",
    )
    return BuildSpec(
        groups=(
            group(
                "universe-matrix",
                "matrix-lab",
                1,
                dict.fromkeys(ingredients, F(1)),
                {"universe-matrix": F(1)},
            ),
        ),
        external_inputs=dict.fromkeys(ingredients, F(1)),
        outputs={"universe-matrix": F(1)},
        belt_item_id="conveyor-belt-3",
        belt_items_per_second=F(30),
        label="seven-item",
    )


def six_item_spec() -> BuildSpec:
    """:func:`seven_item_spec` with one ingredient removed, so it fits unshared."""
    g = seven_item_spec().groups[0]
    inputs = {k: v for k, v in g.inputs_per_machine.items() if k != "antimatter"}
    return BuildSpec(
        groups=(
            group("universe-matrix", "matrix-lab", 1, inputs, dict(g.outputs_per_machine)),
        ),
        external_inputs=dict(inputs),
        outputs={"universe-matrix": F(1)},
        belt_item_id="conveyor-belt-3",
        belt_items_per_second=F(30),
        label="six-item",
    )


def two_lab_spec() -> BuildSpec:
    """Two ``universe-matrix`` labs fed by six producers, so nothing may share.

    Each ingredient now has TWO consuming groups, which is exactly the case
    ``_shareable`` refuses: one trunk carrying two items has to deliver both to
    every stop it makes, so an item with a second destination would arrive on a
    lane whose sorters filter it out and silently back up behind them.  The row
    is over the cap and sharing cannot rescue it, so the refusal survives -- and
    survives naming the recipe and both numbers.
    """
    ingredients = tuple(seven_item_spec().groups[0].inputs_per_machine)
    producers = tuple(
        group(item, "assembling-machine-1", 1, {"iron-ore": F(1)}, {item: F(2)})
        for item in ingredients
    )
    labs = tuple(
        group(
            f"universe-matrix-{n}",
            "matrix-lab",
            1,
            dict.fromkeys(ingredients, F(1)),
            {"universe-matrix": F(1)},
        )
        for n in (0, 1)
    )
    return BuildSpec(
        groups=(*producers, *labs),
        external_inputs={"iron-ore": F(6)},
        outputs={"universe-matrix": F(2)},
        belt_item_id="conveyor-belt-3",
        belt_items_per_second=F(30),
        label="two-lab",
    )


class TestASeventhItemRidesASharedLane:
    """The recipe that is one item wider than two corridors, and how it fits.

    A row touches exactly two corridors and a sorter reaches
    ``SORTER_MAX_REACH`` lanes into each, so a machine can be wired to at most
    ``2 * reach`` = 6 distinct LANES however the rows are packed around it.
    ``universe-matrix`` takes five matrices plus antimatter and makes one
    product: 7 items.  It is the only group in the whole corpus over the cap,
    and direct insertion cannot close the gap -- measured exhaustively, not
    assumed: an insert needs the shared corridor no deeper than ``reach - 1``,
    which cuts the row's own budget to 5 and so needs two inserts, which leaves
    the producer row 3 lanes, and of the 15 producer pairs exactly one has a
    union that small -- a pair an edge between them forbids from sharing a row.

    IT DOES NOT FIT, and the tests below say so now.  The reasoning above puts
    the cap on LANES and moves the overflow into ITEMS -- two items on one lane,
    each tapping sorter filtered -- and that closes the LANE cap without
    touching the real one.  Every item still needs its own SORTER, every sorter
    needs its own machine SLOT, and a slot holds exactly one connection:
    ``entityConnPool[objId * 16 + slot]``, with ``WriteObjectConn`` evicting the
    sitting tenant rather than refusing.  A Matrix Lab offers a lane three
    insert poses per face, so six, and seven items need seven.

    The plan this class describes was emitted for months and the seventh sorter
    was silently dropped -- ``machine.output_removed`` is what it reads as now
    that the slots are rationed.  Sharing is still real and still planned; what
    is gone is the claim that it raises the ceiling past six.

    So the emission half of sharing is currently UNREACHABLE on spine: the lane
    cap and the slot cap are both six, so a spec that needs a shared lane needs
    a seventh slot too.  ``freeform`` is in exactly the same position, and
    ``docs/BACKLOG.md`` records the way out for both -- a machine's EAST and
    WEST faces, which neither strategy uses.
    """

    @staticmethod
    def _filters(p: Placement) -> list[PlacedBuilding]:
        return [b for b in p.buildings if b.filter_id]

    def test_a_seventh_item_is_refused_because_a_slot_holds_one_connection(self) -> None:
        """Seven sorters into six slots, and the refusal is the honest answer.

        THIS ASSERTED THE OPPOSITE, and what it asserted was an invalid
        blueprint: the plan emitted, the seventh sorter had nowhere to stand,
        and it was dropped without a word.  Now the slots are rationed the
        shortfall surfaces as ``machine.output_removed`` -- the product's own
        sorter is the one that loses the race -- and the layout refuses.
        """
        with pytest.raises(NoValidLayout) as exc:
            SpineLayout(power=False).lay_out(seven_item_spec(), time_budget_s=0.5)
        assert "output_removed" in str(exc.value) or "inputs_supplied" in str(exc.value)

    def test_exactly_one_lane_carries_two_items(self) -> None:
        """Seven items on six lanes is ONE shared lane, not seven halves."""
        plan = fallback_plan(seven_item_spec())
        assert sum(len(c) for c in plan.lanes) == 2 * catalog.SORTER_MAX_REACH
        assert len(plan.mixed) == 1
        (shared,) = plan.mixed.values()
        assert len(shared) == 2
        # The product owns its lane's exit, so it is never one of the pair.
        assert "universe-matrix" not in shared

    def test_the_planner_still_mixes_even_though_emission_cannot_follow(self) -> None:
        """Sharing is planned and then refused, and both halves are the point.

        Keeping this rather than deleting the feature's coverage: the planner's
        arithmetic is still correct about LANES and is what a fix would build
        on.  What it cannot do on its own is find a seventh slot.
        """
        plan = fallback_plan(seven_item_spec())
        assert len(plan.mixed) == 1
        with pytest.raises(NoValidLayout):
            SpineLayout(power=False).lay_out(seven_item_spec(), time_budget_s=0.5)

    def test_a_six_item_recipe_shares_nothing(self) -> None:
        """One item per lane is tried FIRST, so a spec that fits keeps its shape.

        Sharing opens new territory rather than trading any away, which is the
        property that lets it land without re-measuring every other spec.
        """
        spec = six_item_spec()
        plan = fallback_plan(spec)
        assert plan.mixed == {}
        p = SpineLayout(power=False).lay_out(spec, time_budget_s=0.5)
        assert p.stats["fallback_reason"] == FALLBACK_NONE
        assert self._filters(p) == []


class TestARecipeThatStillCannotBeWired:
    """Sharing has terms, and a row whose items fail them is still refused.

    An item may only share when it has exactly one destination lane, because
    the two trunks that must deliver into a shared lane are MERGED into one and
    a merged trunk carries both items past every stop it makes.  A second
    destination would take delivery of the other item too, back up behind a
    sorter that filters it out, and stall where nothing can see it -- so the
    layout refuses instead, and refuses for the right reason.
    """

    def test_it_refuses_rather_than_emitting_something_unwireable(self) -> None:
        with pytest.raises(NoValidLayout):
            SpineLayout(power=False).lay_out(two_lab_spec(), time_budget_s=0.5)

    @pytest.mark.parametrize("power", [True, False], ids=["power", "no-power"])
    def test_the_reason_names_the_recipe_and_both_numbers(self, power: bool) -> None:
        with pytest.raises(NoValidLayout) as exc:
            SpineLayout(power=power).lay_out(two_lab_spec(), time_budget_s=0.5)
        reason = exc.value.reason
        assert "universe-matrix" in reason
        assert "7 lanes" in reason
        assert str(2 * catalog.SORTER_MAX_REACH) in reason

    def test_it_is_not_reported_as_an_emission_failure(self) -> None:
        """The two failures call for opposite responses.

        A recipe too wide for the skeleton is permanent; an emission failure is
        worth retrying under a longer budget.  Conflating them cost a real
        diagnosis once, on this very recipe.
        """
        with pytest.raises(NoValidLayout) as exc:
            SpineLayout(power=False).lay_out(two_lab_spec(), time_budget_s=0.5)
        assert "could not be emitted" not in exc.value.reason
        assert "cannot be wired even alone in its own row" in exc.value.reason

    def test_the_seed_alone_no_longer_decides(self) -> None:
        """``fallback_plan`` still raises here; the strategy no longer stops there.

        The seed takes no direct inserts, so its lane count is an upper bound on
        what a solved plan needs -- which makes it a fine DIAGNOSTIC and a bad
        GATE.  It is now consulted for the message and the solver runs regardless.
        """
        from flab2bp.layout.spine import FALLBACK_SEED_UNWIRABLE, _solve_plan

        with pytest.raises(ValueError, match="taps 7 lanes"):
            fallback_plan(two_lab_spec())

        plans, reason, detail = _solve_plan(
            two_lab_spec(), time_budget_s=0.5, workers=DETERMINISTIC_WORKERS
        )
        assert plans == []
        assert reason == FALLBACK_SEED_UNWIRABLE
        assert "universe-matrix" in detail


class TestWhatMayShareALane:
    """``_shareable`` is the whole safety argument for lane sharing.

    Every other piece assumes it: the riser merge assumes one destination each,
    the coater pass assumes a lane's single item, and the sorter pass assumes a
    filter id exists.  So the categories it refuses are pinned here rather than
    left to the corpus to discover.
    """

    @staticmethod
    def _shareable(spec: BuildSpec) -> dict[str, tuple[str, Fraction]]:
        from flab2bp.layout.spine import _adapt, _lane_copies, _shareable

        groups, edges = _adapt(spec)
        return _shareable(
            groups, edges, set(), spec, _lane_copies(groups, edges, set(), spec)
        )

    def test_an_item_leaving_the_block_may_not_share(self) -> None:
        """It owns one end of its lane, which is where a product exits."""
        assert "universe-matrix" not in self._shareable(seven_item_spec())

    def test_external_inputs_may_share_with_each_other(self) -> None:
        share = self._shareable(seven_item_spec())
        assert {k: v[0] for k, v in share.items()} == dict.fromkeys(
            seven_item_spec().groups[0].inputs_per_machine, "external"
        )

    def test_an_item_with_two_consumers_may_not_share(self) -> None:
        """One trunk carrying two items delivers both at every stop it makes.

        The six matrices each feed two labs here, so each has two destination
        lanes and none of them may pair.  ``iron-ore`` still may: it is external,
        so every copy of its lane is its own entry at ``x = 0`` and no trunk is
        involved at all.
        """
        share = self._shareable(two_lab_spec())
        assert set(share) == {"iron-ore"}

    def test_an_externally_fed_sprayed_item_may_not_share(self) -> None:
        """A coater is found by the lane's PRIMARY item.

        An external item enters at ``x = 0`` on its lane and nowhere else, so a
        sprayed one that rode along could end up on a lane whose coater search
        never names it -- running unproliferated while the rate solve had costed
        it sprayed, and looking perfectly healthy while it did.  An internal
        item is safe: its source lane is unshared and carries the coater, so it
        arrives already sprayed.
        """
        g = seven_item_spec().groups[0]
        ingredients = dict(g.inputs_per_machine)
        spec = BuildSpec(
            groups=(
                group(
                    "universe-matrix",
                    "matrix-lab",
                    1,
                    ingredients,
                    dict(g.outputs_per_machine),
                ),
            ),
            external_inputs={**ingredients, "proliferator-3": F(1)},
            outputs={"universe-matrix": F(1)},
            spray_lanes={"antimatter": True},
            belt_item_id="conveyor-belt-3",
            belt_items_per_second=F(30),
            label="sprayed-entry",
        )
        share = self._shareable(spec)
        assert "antimatter" not in share
        assert "gravity-matrix" in share

    def test_a_split_item_may_not_share(self) -> None:
        """``_lane_copies`` already spent the corridor on it."""
        spec = wide_flow_spec()
        share = self._shareable(spec)
        from flab2bp.layout.spine import _adapt, _lane_copies

        groups, edges = _adapt(spec)
        copies = _lane_copies(groups, edges, set(), spec)
        assert copies["iron-ingot"] > 1
        assert "iron-ingot" not in share


class TestTrunksThatDeliverIntoOneLane:
    """Two items on one lane need ONE trunk, not two.

    Each trunk reaches its lane by bridging across the riser margin at that
    lane's y, so two of them would claim the same tiles -- an overlap the
    validator reports and the game refuses to paste.  The riser model already
    expresses the answer: ``taps`` may hold several sources.
    """

    def test_two_sources_and_a_shared_destination_become_one_trunk(self) -> None:
        from flab2bp.layout.spine import _merge_shared_risers, _Riser

        a = _Riser(item="a", taps=((1, 1, 0, True), (20, 9, 0, False)))
        b = _Riser(item="b", taps=((5, 3, 0, True), (20, 9, 0, False)))
        merged = _merge_shared_risers([a, b])
        assert len(merged) == 1
        assert merged[0].taps == ((1, 1, 0, True), (5, 3, 0, True), (20, 9, 0, False))

    def test_trunks_that_share_nothing_are_left_alone(self) -> None:
        from flab2bp.layout.spine import _merge_shared_risers, _Riser

        risers = [
            _Riser(item="a", taps=((1, 1, 0, True), (20, 9, 0, False))),
            _Riser(item="b", taps=((5, 3, 0, True), (22, 9, 1, False))),
        ]
        assert _merge_shared_risers(risers) == sorted(
            risers, key=lambda r: (r.taps[0][0], r.item)
        )


class TestLinkingATowerTheNetworkCannotReach:
    """A relay has to JOIN the network, not land halfway to it.

    A midpoint relay only links when the gap is under twice the link distance.
    Past that it reaches neither end, so the flood fill never grows, the next
    pass picks the same stray tower and the same midpoint, and the walk spends
    its whole bound piling unconnected towers on one spot -- 226 towers with 126
    stray on ``universe-matrix``, against 110 and none on the runs that missed
    the case.
    """

    @staticmethod
    def _towers(*ys: int) -> list[PlacedBuilding]:
        from flab2bp.layout.spine import CONSTANTS

        w, h = CONSTANTS.tower_size
        model = catalog.building(CONSTANTS.tesla_item_id).model_index
        return [
            PlacedBuilding(
                item_id=CONSTANTS.tesla_item_id,
                model_index=model,
                x=0,
                y=y,
                width=w,
                height=h,
            )
            for y in ys
        ]

    @staticmethod
    def _stray(buildings: list[PlacedBuilding]) -> int:
        from flab2bp.layout.spine import CONSTANTS

        link = float(CONSTANTS.link_distance)
        centres = [
            (b.x + b.width / 2, b.y + b.height / 2)
            for b in buildings
            if b.item_id == CONSTANTS.tesla_item_id
        ]
        seen, frontier = {0}, [0]
        while frontier:
            i = frontier.pop()
            for j, t in enumerate(centres):
                if j not in seen and math.dist(centres[i], t) <= link:
                    seen.add(j)
                    frontier.append(j)
        return len(centres) - len(seen)

    def test_a_gap_wider_than_two_links_is_walked(self) -> None:
        from flab2bp.layout.spine import CONSTANTS, _link_towers

        link = float(CONSTANTS.link_distance)
        model = catalog.building(CONSTANTS.tesla_item_id).model_index
        buildings = self._towers(0, 70)
        assert math.dist((0, 0), (0, 70)) > 2 * link, "not the case under test"
        added = _link_towers(buildings, model)
        assert self._stray(buildings) == 0
        # A walk, not a pile: 70 tiles at roughly two thirds of a link a step.
        assert added <= 8

    def test_a_gap_one_relay_can_close_still_costs_one(self) -> None:
        from flab2bp.layout.spine import CONSTANTS, _link_towers

        model = catalog.building(CONSTANTS.tesla_item_id).model_index
        buildings = self._towers(0, 30)
        assert _link_towers(buildings, model) == 1
        assert self._stray(buildings) == 0

    def test_a_tower_keeps_the_pastes_power_spacing_from_another_tower(self) -> None:
        """``EBuildCondition.PowerTooClose``, in the set every tower pass reads.

        A Tesla Tower has NO build collider, so its CLEARANCE halo is 0.3 world
        units -- inside its own tile -- and until this rule was ported nothing
        stopped the coverage top-up or a link relay from standing one beside
        another.  A blueprint we emitted was pasted into a real game and had two
        of its six towers reddened for exactly that;
        ``tests/fixtures/ours/power-too-close-freeform.txt`` is the paste.

        The bound is 3.5 WORLD units = 2.785 tiles, so the diagonal and the
        knight's move are refused and ``(2, 2)`` is not.  Bracketing both sides
        is what separates it from a tile-distance reading of the same constant.
        """
        from flab2bp.layout.spine import _tower_keep_out

        keep = _tower_keep_out(self._towers(10))  # one tower, at (0, 10)
        for dx, dy in ((1, 0), (1, 1), (2, 0), (2, 1), (0, 2)):
            assert (dx, 10 + dy) in keep, f"({dx},{dy}) is PowerTooClose"
        for dx, dy in ((2, 2), (3, 0), (0, 3)):
            assert (dx, 10 + dy) not in keep, f"({dx},{dy}) is legal and denied"

    def test_the_keep_out_covers_a_power_node_that_is_not_a_tower(self) -> None:
        """A Ray Receiver and an Energy Exchanger join the network too.

        The spacing rule is keyed on ``PrefabDesc.isPowerNode``, not on being a
        Tesla Tower, and two of the three power nodes this pipeline can emit are
        mode-driven MACHINES.  Exercised on a 3x3 Solar Panel because that is
        the smallest node whose halo reaches past its own footprint -- for the
        7x7 Ray Receiver and the 9x9 Energy Exchanger the 2-tile halo is inside
        the footprint, so the term is real and a no-op for them.
        """
        from flab2bp.layout.spine import _tower_keep_out

        panel = catalog.building(2205)
        assert panel.is_power_node and (panel.width, panel.height) == (3, 3)
        keep = _tower_keep_out(
            [
                PlacedBuilding(
                    item_id=2205,
                    model_index=panel.model_index,
                    x=10,
                    y=10,
                    width=panel.width,
                    height=panel.height,
                )
            ]
        )
        # Centre (11, 11); the footprint alone would stop at +/-1.
        assert (13, 11) in keep and (11, 13) in keep, "the halo must reach past 3x3"
        assert (14, 11) not in keep, "and stop where the rule stops"

    def test_the_coverage_top_up_never_stands_two_towers_too_close(self) -> None:
        """The pass that could, end to end, on ground built to force the case.

        ``_top_up_coverage`` places a tower on the nearest FREE tile to an
        uncovered building, and a tower covers 10.5 tiles -- so two of its
        towers only end up adjacent when the ground gives it no choice.  This
        gives it exactly that: solid belt everywhere except two neighbouring
        cells, and two machines positioned so the first cell covers one of them
        and misses the other by half a tile.

        Under the unfixed pass this stands towers at (20, 17) and (21, 17),
        1.777 world units apart, which the game refuses.  With the rule applied
        the second machine is genuinely unpowerable -- the only cell that could
        have covered it is inside the first tower's spacing -- so the pass says
        so through ``unfixable``, which is what ``power_uncovered`` reports and
        ``power.coverage`` refuses on.  A refusal, not an invalid paste, and
        that direction is the whole point: this ground is contrived, and a real
        build has somewhere else to stand.
        """
        from flab2bp.layout.spine import CONSTANTS, _top_up_coverage

        model = catalog.building(CONSTANTS.tesla_item_id).model_index
        free = {(20, 17), (21, 17)}
        machines = ((12, 12), (31, 17))
        buildings: list[PlacedBuilding] = [
            PlacedBuilding(item_id=2002, model_index=37, x=x, y=y)
            for x in range(-15, 55)
            for y in range(2, 33)
            if (x, y) not in free and (x, y) not in machines
        ]
        buildings += [
            PlacedBuilding(item_id=2303, model_index=65, x=x, y=y, width=1, height=1)
            for x, y in machines
        ]
        added, unfixable = _top_up_coverage(buildings, model)
        assert added + unfixable == 2, "the ground must ask the pass for two towers"
        assert unfixable == 1, (
            "the second machine's only free cell is inside the first tower's "
            "spacing, so it must be REPORTED unpowerable rather than covered by "
            "a tower the game will refuse"
        )
        towers = [
            (b.x, b.y) for b in buildings if b.item_id == CONSTANTS.tesla_item_id
        ]
        assert len(towers) == 1
        keep = {
            (dx, dy)
            for dx, dy, dz in rules.power_node_keepout_offsets(
                catalog.building(CONSTANTS.tesla_item_id).power_node,
                catalog.building(CONSTANTS.tesla_item_id).power_node,
            )
            if dz == 0
        }
        for (ax, ay), (bx, by) in itertools.combinations(towers, 2):
            assert (bx - ax, by - ay) not in keep, (
                f"top-up stood towers at {(ax, ay)} and {(bx, by)}"
            )


class TestThereIsNoSeedFallback:
    """An unroutable plan refuses. It does not degrade to the seed.

    This test used to assert the opposite, and that is the point of keeping it:
    the seed has now been removed twice.  The first removal took out a path that
    returned ``fallback_plan``'s greedy stacking unexamined.  It came back
    wearing a self-check, on the argument that a CHECKED seed differs in kind
    from an unchecked one.

    It does not.  The check proves only that the seed is not broken; it says
    nothing about why the solver had nothing to return, which is the only
    question worth asking -- a spec reaching that line has a packer producing
    rows its own allocator cannot wire.  Emitting the seed makes the defect
    invisible: the cell goes green and nobody looks again.  And it is bought in
    the currency this program exists to minimise -- the seed measured 50,512
    tiles against roughly 39,000 for a solved plan on
    ``universe-matrix``/``free-proliferation``.

    So: refusal names a bug, a fallback hides one.  If a spec that used to be
    rescued now refuses, fix the packer.
    """

    def test_it_refuses_when_every_width_was_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from flab2bp.layout import spine

        spec = magnetic_ring_spec()
        monkeypatch.setattr(
            spine, "_solve_plan", lambda *a, **k: ([], spine.FALLBACK_UNROUTABLE, "")
        )
        with pytest.raises(NoValidLayout):
            SpineLayout(power=False).lay_out(spec, time_budget_s=0.5)

    def test_a_second_solved_plan_is_not_a_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A plan that will not emit must not discard the sweep behind it.

        This is the one thing that separates trying the sweep's second plan from
        reaching for a seed.  Both look like "the first answer failed, use
        another"; only one of them hands back something CP-SAT actually returned
        under the same constraints.  So the assertion that matters here is not
        "a placement came back" -- a seed would satisfy that -- it is that the
        plan which emitted is an element of ``_solve_plan``'s own list.

        No corpus cell currently reaches past the head plan -- measured, see
        ``_solve_plan`` -- so this behaviour has to be pinned by construction
        rather than by a spec that exercises it, or it would rot unnoticed.
        That is also why the poisoning is done by identity on ``plans[0]``: it
        makes the test fail if the loop ever stops walking, which is the only
        thing it is here to catch.
        """
        from flab2bp.layout import spine

        spec = magnetic_ring_spec()
        real = spine._solve_plan
        plans, reason, detail = real(
            spec, time_budget_s=2.0, workers=DETERMINISTIC_WORKERS
        )
        assert len(plans) > 1, "this spec must give the sweep more than one plan"
        assert reason == spine.FALLBACK_NONE

        # Poison the densest plan's emission. The layout must reach past it
        # rather than refuse, and what comes back is still a solved plan.
        real_emit = spine._emit
        emitted: list[object] = []

        def _emit(spec_: BuildSpec, plan: object, **kw: object) -> object:
            if plan is plans[0]:
                raise ValueError("poisoned: the densest plan will not emit")
            emitted.append(plan)
            return real_emit(spec_, plan, **kw)  # type: ignore[arg-type]

        monkeypatch.setattr(
            spine, "_solve_plan", lambda *a, **k: (plans, reason, detail)
        )
        monkeypatch.setattr(spine, "_emit", _emit)
        placement = SpineLayout(power=False).lay_out(spec, time_budget_s=2.0)

        assert placement.stats["fallback_reason"] == spine.FALLBACK_NONE
        # The whole point: what got emitted is one of the solver's own plans,
        # reached by identity, not something this module built to fill the gap.
        assert emitted, "nothing was emitted at all"
        assert any(emitted[-1] is p for p in plans[1:])

    def test_a_plan_the_validator_rejects_does_not_discard_the_sweep(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The self-check is the gate that actually caused this, so pin it too.

        Emission failing is the easy case, and the two gates are not the same
        gate: a plan can emit perfectly well and then be rejected by OUR OWN
        validator -- ``flow.belt_capacity`` is the plausible one, a width having
        quietly put more items/s on a lane than its belt tier carries.
        ``_rejected`` is as invisible to the width sweep as emission is, so the
        loop has to walk past a validator rejection too, and a test that only
        poisons ``_emit`` would not notice if it stopped.
        """
        from flab2bp.layout import spine

        spec = magnetic_ring_spec()
        real = spine._solve_plan
        plans, reason, detail = real(
            spec, time_budget_s=2.0, workers=DETERMINISTIC_WORKERS
        )
        assert len(plans) > 1, "this spec must give the sweep more than one plan"

        real_emit = spine._emit
        from_plan: dict[int, object] = {}

        def _emit(spec_: BuildSpec, plan: object, **kw: object) -> object:
            placement = real_emit(spec_, plan, **kw)  # type: ignore[arg-type]
            from_plan[id(placement)] = plan
            return placement

        def _rejected(placement: object, *a: object, **k: object) -> str:
            if from_plan.get(id(placement)) is plans[0]:
                return "flow.belt_capacity: poisoned densest plan"
            return ""

        monkeypatch.setattr(
            spine, "_solve_plan", lambda *a, **k: (plans, reason, detail)
        )
        monkeypatch.setattr(spine, "_emit", _emit)
        monkeypatch.setattr(spine, "_rejected", _rejected)
        placement = SpineLayout(power=False).lay_out(spec, time_budget_s=2.0)

        assert any(from_plan.get(id(placement)) is p for p in plans[1:])

    def test_it_still_refuses_when_no_solved_plan_survives(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exhausting the sweep is a refusal, not a licence to invent a plan.

        The list only ever holds what the solver returned. When none of it
        emits, there is nothing else to hand back -- and that is the whole
        point.
        """
        from flab2bp.layout import spine

        spec = magnetic_ring_spec()

        def _emit(*a: object, **k: object) -> object:
            raise ValueError("nothing in this sweep emits")

        monkeypatch.setattr(spine, "_emit", _emit)
        with pytest.raises(NoValidLayout) as exc:
            SpineLayout(power=False).lay_out(spec, time_budget_s=2.0)
        assert "could not be emitted" in exc.value.reason

    def test_a_recipe_no_row_can_wire_still_refuses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The seed cannot rescue a recipe wider than two corridors, and does not try.

        ``FALLBACK_SEED_UNWIRABLE`` says the seed itself failed to allocate, so
        reaching for it again would only raise the same ValueError -- and would
        report it as an emission failure, which is the mislabelling this
        module's refusal codes exist to prevent.
        """
        with pytest.raises(NoValidLayout) as exc:
            SpineLayout(power=False).lay_out(two_lab_spec(), time_budget_s=0.5)
        assert "cannot be wired even alone in its own row" in exc.value.reason


class TestTapCapacityIsPerSide:
    """The packer may not authorise a row its own allocator then refuses.

    A row taps two corridors and a sorter reaches ``sorter_max_reach`` lanes into
    each -- but only when both corridors are fully usable, and neither is in
    general.  A group is charged for the corridor BELOW by the tiles it stops
    short of its row's floor plus what its own poses on that face cost, and for
    the corridor ABOVE by its poses alone.  The two numbers are different and the
    model has to carry both: charging one to both sides is wrong twice over, and
    the two errors cancel in the total.

    Rejecting after the fact cannot fix this: routability is a property of the
    packing, so the packer has to know.

    Two fixtures, deliberately mirror images -- `pitch_gap_spec` charges only the
    corridor below and `inset_face_spec` only the one above.  Each fails if its
    own half of the model is removed, which is what stops a single fixture from
    passing on the strength of the other half.
    """

    @staticmethod
    def _refuses(spec: BuildSpec) -> None:
        """The allocator will not seat this spec's groups in one row."""
        from flab2bp.layout.spine import _adapt, _allocate_lanes, _lane_copies

        groups, edges = _adapt(spec)
        keys = list(groups)
        copies = dict.fromkeys(_lane_copies(groups, edges, set(), spec), 1)
        # No edge between any two groups, so `_solve_one` is FREE to put all
        # three in one row: it orders producers strictly above consumers, and a
        # chain could never share a row whatever the tap model said.
        assert not edges, edges
        assert len(copies) == 2 * catalog.SORTER_MAX_REACH, sorted(copies)
        with pytest.raises(ValueError, match="no ordering of its two"):
            _allocate_lanes(groups, edges, [keys], set(), spec, copies)
        # Split so each row's own charge fits, and the same six lanes wire fine
        # -- which is what makes the refusal about REACH and not about lane count.
        _allocate_lanes(groups, edges, [keys[:1], keys[1:2], keys[2:]], set(), spec, copies)

    @staticmethod
    def _packer_will_not_take_it(spec: BuildSpec) -> None:
        """``_solve_one`` raises the allocator's ValueError, so this is the test.

        At the widest candidate width -- the densest one in the sweep -- one row
        of all three groups costs one row band and two corridors against three
        bands and four corridors.  A model blind to either charge takes it every
        time, and then throws the width away.
        """
        from flab2bp.layout.spine import (
            _adapt,
            _candidate_widths,
            _solve_one,
            _topological_rows,
        )

        groups, edges = _adapt(spec)
        order = [row[0] for row in _topological_rows(groups, edges)]
        depth = {k: i for i, k in enumerate(order)}
        plan, infeasible = _solve_one(
            spec, groups, edges, depth, len(order), _candidate_widths(groups)[0], 2.0, 1
        )
        assert not infeasible
        assert plan is not None
        assert not any(len(r) == 3 for r in plan.rows), plan.rows

    def test_the_charges_are_what_the_slot_tables_say(self) -> None:
        """Ground truth for both fixtures, asserted rather than assumed.

        This is the check rotation would have tripped: it turned the Oil Refinery
        the old fixture carried from 3x7 into 7x3, every machine became the same
        height, and the tests below went on passing over a spec that could no
        longer express what they were about.
        """
        from flab2bp.layout.spine import _adapt, _below_charge

        groups, _ = _adapt(pitch_gap_spec())
        row_h = max(g.pitch_h for g in groups.values())
        assert row_h == 4 and all(g.height == 3 for g in groups.values())
        assert sorted(g.above_charge for g in groups.values()) == [0, 0, 0]
        assert sorted(_below_charge(g, row_h) for g in groups.values()) == [1, 1, 1]

        groups, _ = _adapt(inset_face_spec())
        row_h = max(g.pitch_h for g in groups.values())
        assert row_h == 5 and all(g.height == 5 for g in groups.values())
        # A row of equal-height machines, so the row contributes NOTHING to the
        # charge below -- every tile of it is the poses' own.
        assert sorted(g.above_charge for g in groups.values()) == [1, 1, 1]
        assert sorted(_below_charge(g, row_h) for g in groups.values()) == [0, 0, 0]

    def test_the_allocator_refuses_the_clearance_gapped_row(self) -> None:
        self._refuses(pitch_gap_spec())

    def test_the_allocator_refuses_the_inset_face_row(self) -> None:
        self._refuses(inset_face_spec())

    def test_the_packer_will_not_authorise_the_clearance_gapped_row(self) -> None:
        self._packer_will_not_take_it(pitch_gap_spec())

    def test_the_packer_will_not_authorise_the_inset_face_row(self) -> None:
        self._packer_will_not_take_it(inset_face_spec())

    def test_a_spec_with_neither_charge_still_packs_its_rows(self) -> None:
        """The bound must not cost density where nothing is charged.

        A flat ``reach - charge`` cap would: it charges the whole corridor the
        worst, where ``_fits_band`` charges lane by lane.  The nine equal-height
        groups of ``magnetic_ring_spec`` build no charge variables at all, so
        this is also the check that the common case is untouched.
        """
        spec = magnetic_ring_spec()
        p = SpineLayout(power=False).lay_out(spec, time_budget_s=0.5)
        assert p.stats["fallback_used"] == 0.0
        assert p.stats["rows"] < len(spec.groups)


class TestRealCorpusSpecsActuallySolve:
    """The absence of this class is what let a dead solver ship.

    Every other spine test builds its spec by hand, and the hand-built ones are
    small enough that the solver always coped.  On real FactorioLab specs it did
    not: `_lane_requirements` refused every candidate width, `_solve_plan`
    returned None, and the strategy silently produced its greedy fallback --
    roughly twice the area, and 3.4x worse than Strategy B on the same input.

    These tests are slow because they run the rate solver and CP-SAT on real
    URLs, so they are marked; the default run stays fast.
    """

    @staticmethod
    def _spec(url_id: str) -> BuildSpec:
        from flab2bp.bench.corpus import entry
        from flab2bp.lab.data import load_vendored
        from flab2bp.lab.url import parse_url
        from flab2bp.rates.candidates import build_candidates

        candidates = build_candidates(
            load_vendored(), parse_url(entry(url_id).url), count=3
        ).candidates
        # The SMALLEST SPINE CAN BUILD, which is not simply the smallest.
        # Proliferation cuts machine count, so `min` picks a sprayed candidate,
        # and a sprayed candidate is mostly a test of the elevated coater spur:
        # a Spray Coater takes its proliferator positionally from a belt in its
        # addon area, which `TestSprayCoatersAreFed` covers on its own terms.
        # Handing that to a test about the SOLVER measures the wrong thing.
        # (This comment used to say spine REFUSED every sprayed candidate. It
        # did, until `_spur_clear` learned the game's belt-crossing height.)
        buildable = [c for c in candidates if not c.spray_lanes] or list(candidates)
        return min(buildable, key=lambda s: s.machine_count)

    @pytest.mark.slow
    @pytest.mark.parametrize(
        "url_id",
        ["graphene", "plastic", "processor", "energy-matrix", "casimir-crystal"],
    )
    def test_solver_does_not_fall_back(self, url_id: str) -> None:
        p = SpineLayout(power=False).lay_out(self._spec(url_id), time_budget_s=0.5)
        assert p.stats["fallback_used"] == 0.0, (
            f"{url_id} fell back, reason={p.stats['fallback_reason']}"
        )
        assert p.stats["fallback_reason"] == FALLBACK_NONE

    @pytest.mark.slow
    def test_a_wide_spec_packs_rows_rather_than_one_group_each(self) -> None:
        """The seed's signature is one row per group; a solve must beat it."""
        spec = self._spec("information-matrix")
        solved = SpineLayout(power=False).lay_out(spec, time_budget_s=0.5)
        assert solved.stats["fallback_used"] == 0.0
        assert solved.stats["rows"] < len(spec.groups)
        seed = _emit(spec, fallback_plan(spec), power=False)
        assert solved.area < seed.area


class TestPowerCoverageOnRealSpecs:
    """Power on real specs, which is where the coverage model broke.

    Every previous power test used a hand-built spec whose corridors are a few
    lanes deep.  A 27-group build reaches 14-lane corridors, and the reach model
    charged each row the FULL height of its neighbouring corridors -- as if that
    row's towers alone had to reach the far edge.  That put 21 of 27 rows past
    the 10.5-tile radius and made Strategy A refuse to lay out a real URL at all.

    An interior corridor is bordered by two rows, each with its own towers, so
    neither has to cross it: they meet in the middle.  Only the first and last
    corridors have a single neighbour, and the top one needs its own tower band.
    """

    @staticmethod
    def _spec(url_id: str) -> BuildSpec:
        from flab2bp.bench.corpus import entry
        from flab2bp.lab.data import load_vendored
        from flab2bp.lab.url import parse_url
        from flab2bp.rates.candidates import build_candidates

        candidates = build_candidates(
            load_vendored(), parse_url(entry(url_id).url), count=3
        ).candidates
        # The SMALLEST SPINE CAN BUILD, which is not simply the smallest.
        # Proliferation cuts machine count, so `min` picks a sprayed candidate,
        # and a sprayed candidate is mostly a test of the elevated coater spur:
        # a Spray Coater takes its proliferator positionally from a belt in its
        # addon area, which `TestSprayCoatersAreFed` covers on its own terms.
        # Handing that to a test about the SOLVER measures the wrong thing.
        # (This comment used to say spine REFUSED every sprayed candidate. It
        # did, until `_spur_clear` learned the game's belt-crossing height.)
        buildable = [c for c in candidates if not c.spray_lanes] or list(candidates)
        return min(buildable, key=lambda s: s.machine_count)

    @staticmethod
    def _report(spec: BuildSpec, placement: Placement) -> validate.Report:
        from flab2bp.pipeline import _id_map

        return validate.validate(
            placement, spec, ids=_id_map(spec), expect_power=True
        )

    @pytest.mark.slow
    @pytest.mark.parametrize(
        "url_id",
        ["processor", "casimir-crystal", "information-matrix", "quantum-chip"],
    )
    def test_every_powered_building_is_covered(self, url_id: str) -> None:
        spec = self._spec(url_id)
        p = SpineLayout(power=True).lay_out(spec, time_budget_s=0.5)
        assert p.stats["fallback_used"] == 0.0
        # No powered building left stranded. The top-up reports what it could
        # not reach rather than swallowing it, so this doubles as a check that
        # the analytic model plus the repair together actually close the gap.
        assert p.stats["power_uncovered"] == 0.0
        report = self._report(spec, p)
        power_errors = [
            f for f in report.errors if f.check.startswith("power.")
        ]
        assert not power_errors, "\n".join(f.message for f in power_errors[:5])

    @pytest.mark.slow
    def test_a_deep_corridor_spec_lays_out_at_all(self) -> None:
        """The regression proper: this raised ValueError before the fix."""
        spec = self._spec("information-matrix")
        p = SpineLayout(power=True).lay_out(spec, time_budget_s=0.5)
        assert p.stats["towers"] > 0
        assert p.area > 0

    def test_interior_corridors_are_shared_but_boundaries_are_not(self) -> None:
        """The asymmetry is the whole fix; pin it directly.

        A hand-built check so it runs in the default suite: charging a boundary
        corridor at half would under-cover the external input lanes, which real
        placements do tap all the way to their deepest lane.
        """
        from flab2bp.layout.spine import _corridor_charge

        heights = [9, 9, 9, 9]
        assert _corridor_charge(0, heights) == 9, "top corridor has one neighbour"
        assert _corridor_charge(3, heights) == 9, "bottom corridor has one neighbour"
        assert _corridor_charge(1, heights) < 9, "interior corridor is shared"
        assert _corridor_charge(2, heights) < 9
        # With a tower band above it, the top corridor gains a second neighbour.
        assert _corridor_charge(0, heights, has_top_band=True) < 9

    def test_a_tall_top_corridor_gets_its_own_tower_band(self) -> None:
        from flab2bp.layout.spine import _top_band_height

        # Shallow: row 0's own towers reach the whole corridor.
        assert _top_band_height([3], [2, 1]) == 0
        # Deep: they cannot, so a band is required.
        assert _top_band_height([3], [11, 1]) > 0


class TestBeltsCarryTheirItemLabel:
    """`carries_item` is unrecoverable once emission drops it.

    A belt's DSP record says nothing about what flows along it, so the item is
    layout knowledge that has to be carried forward deliberately.  The external
    input markers and the validator's per-item flow check both depend on it.
    """

    def test_every_emitted_belt_is_labelled(self) -> None:
        p = SpineLayout(power=False).lay_out(magnetic_ring_spec(), time_budget_s=0.5)
        belts = [b for b in p.buildings if catalog.is_belt(b.item_id)]
        assert belts
        unlabelled = [b for b in belts if b.carries_item is None]
        assert not unlabelled, f"{len(unlabelled)} of {len(belts)} belts carry no item label"

    def test_relinking_a_belt_preserves_every_field(self) -> None:
        """Guards the relink trap.

        A field-by-field rebuild silently drops whatever it forgets to list.
        The freeform copy of this helper was already discarding `parameters`
        and ate `carries_item` the instant it was added -- the markers came out
        empty and it looked like a marker bug rather than a relink one.
        """
        from flab2bp.layout.spine import _with_output

        original = PlacedBuilding(
            item_id=2002,
            model_index=36,
            x=1,
            y=2,
            carries_item="iron-ore",
            parameters=(1001, 0),
            filter_id=7,
            x2=3,
            y2=4,
            output_offset=2,
        )
        relinked = _with_output(original, 9)
        assert relinked.output_obj == 9
        for f in ("carries_item", "parameters", "filter_id", "x2", "y2", "output_offset"):
            assert getattr(relinked, f) == getattr(original, f), f"relink dropped {f}"

    def test_external_inputs_all_get_a_marker(self) -> None:
        from flab2bp.layout import markers

        spec = magnetic_ring_spec()
        p = markers.mark_external_inputs(
            SpineLayout(power=False).lay_out(spec, time_budget_s=0.5), spec
        )
        marked = {
            b.carries_item
            for b in p.buildings
            if catalog.is_belt(b.item_id) and b.parameters and b.carries_item
        }
        assert marked >= set(spec.external_inputs), (
            f"unmarked external inputs: {set(spec.external_inputs) - marked}"
        )


class TestSorterGeometryIsPhysical:
    """DSP sorters run in a straight line; a diagonal one cannot be built.

    100 of 118 sorters on the magnetic-ring spec used to be diagonal, because
    the belt-side anchor was computed from ``m.x + min(i, m.width - 1)`` while
    the machine-side anchor used bare ``m.x``.  Every sorter after the first in
    a group therefore skewed by exactly ``min(i, width - 1)``, which is why the
    observed ``dx`` values were only ever 1 or 2.

    These assert the property directly rather than through the validator, so a
    regression names the geometry rather than an error count.
    """

    @staticmethod
    def _sorters(p: Placement) -> list[PlacedBuilding]:
        return [b for b in p.buildings if catalog.is_sorter(b.item_id) and b.x2 is not None]

    @pytest.mark.parametrize("power", [False, True], ids=["no-power", "power"])
    def test_no_sorter_runs_diagonally(self, power: bool) -> None:
        p = SpineLayout(power=power).lay_out(magnetic_ring_spec(), time_budget_s=0.5)
        diagonal = [
            (i, abs(b.x2 - b.x), abs(b.y2 - b.y))
            for i, b in enumerate(p.buildings)
            if catalog.is_sorter(b.item_id)
            and b.x2 is not None
            and b.y2 is not None
            and abs(b.x2 - b.x)
            and abs(b.y2 - b.y)
        ]
        assert not diagonal, f"{len(diagonal)} diagonal sorters, e.g. {diagonal[:5]}"

    def test_every_sorter_is_within_chebyshev_reach(self) -> None:
        """Chebyshev, matching the validator and the measured corpus."""
        p = SpineLayout(power=False).lay_out(magnetic_ring_spec(), time_budget_s=0.5)
        for i, b in enumerate(self._sorters(p)):
            span = max(abs(b.x2 - b.x), abs(b.y2 - b.y))  # type: ignore[operator]
            assert 1 <= span <= catalog.SORTER_MAX_REACH, f"sorter {i} spans {span}"

    def test_sorters_never_change_altitude(self) -> None:
        p = SpineLayout(power=False).lay_out(magnetic_ring_spec(), time_budget_s=0.5)
        for i, b in enumerate(self._sorters(p)):
            assert b.z2 == b.z, f"sorter {i} spans altitude {b.z} -> {b.z2}"


class TestRealSpecsValidateClean:
    """The acceptance criterion: a spec from a real URL produces a valid build.

    Every prior spine test used hand-built specs.  That is exactly how 197
    validation errors stayed invisible -- the hand-built specs are small enough
    that the broken paths never fire.
    """

    @staticmethod
    def _spec(url_id: str) -> BuildSpec:
        from flab2bp.bench.corpus import entry
        from flab2bp.lab.data import load_vendored
        from flab2bp.lab.url import parse_url
        from flab2bp.rates.candidates import build_candidates

        candidates = build_candidates(
            load_vendored(), parse_url(entry(url_id).url), count=3
        ).candidates
        # The SMALLEST SPINE CAN BUILD, which is not simply the smallest.
        # Proliferation cuts machine count, so `min` picks a sprayed candidate,
        # and a sprayed candidate is mostly a test of the elevated coater spur:
        # a Spray Coater takes its proliferator positionally from a belt in its
        # addon area, which `TestSprayCoatersAreFed` covers on its own terms.
        # Handing that to a test about the SOLVER measures the wrong thing.
        # (This comment used to say spine REFUSED every sprayed candidate. It
        # did, until `_spur_clear` learned the game's belt-crossing height.)
        buildable = [c for c in candidates if not c.spray_lanes] or list(candidates)
        return min(buildable, key=lambda s: s.machine_count)

    @pytest.mark.slow
    @pytest.mark.parametrize(
        "url_id", ["graphene", "plastic", "processor", "energy-matrix", "casimir-crystal"]
    )
    def test_validator_reports_no_errors(self, url_id: str) -> None:
        from flab2bp.layout import validate
        from flab2bp.pipeline import _id_map

        spec = self._spec(url_id)
        p = SpineLayout(power=True).lay_out(spec, time_budget_s=0.5)
        report = validate.validate(p, spec, ids=_id_map(spec), expect_power=True)
        assert report.ok, "\n".join(f"{f.check}: {f.message}" for f in report.errors[:10])


class TestSprayCoatersAreFed:
    """A coater with no proliferator sprays nothing.

    Every proliferated recipe then quietly runs unproliferated and the build
    misses its rate -- it pastes, the machines run, and the numbers are simply
    lower than the spec promised.  Nothing about the blueprint looks wrong.
    """

    @staticmethod
    def _candidate(label: str) -> BuildSpec:
        from flab2bp.lab.data import load_vendored
        from flab2bp.lab.url import parse_url
        from flab2bp.rates.candidates import build_candidates

        url = (
            "https://factoriolab.github.io/dsp/flow?o=super-magnetic-ring*60"
            "&ibe=conveyor-belt-2"
            "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11"
        )
        cands = build_candidates(load_vendored(), parse_url(url), count=3).candidates
        return next(c for c in cands if c.label == label)

    @staticmethod
    def _corpus_candidate(label: str) -> BuildSpec:
        """The corpus entry's OWN url, which is not the one above.

        `_candidate` drops `&mps=proliferator-2-products` and asks for three
        candidates; the corpus asks for six from the URL the user actually
        supplied.  The two produce DIFFERENT specs -- eleven spray lanes against
        ten -- and only the corpus one is the cell `docs/BACKLOG.md` and
        `scripts/audit.py` name.  Measuring the ten-coater case against the
        other spec is measuring a different spec.
        """
        from flab2bp.bench.corpus import entry
        from flab2bp.lab.data import load_vendored
        from flab2bp.lab.url import parse_url
        from flab2bp.rates.candidates import build_candidates

        cands = build_candidates(
            load_vendored(), parse_url(entry("super-magnetic-ring").url), count=6
        ).candidates
        return next(c for c in cands if c.label == label)

    @pytest.mark.slow
    def test_spine_supplies_every_coater_on_a_real_spec(self) -> None:
        """Three versions of this test, three different false things asserted.

        The first asked that a proliferator lane exist; the second that every
        coater have "a sorter drawing proliferator" from it -- a sorter that
        cannot exist, because a Spray Coater has no insert pose to name and the
        game supplies an addon positionally from a belt in its addon area. Both
        passed for years on placements the game would not have built.

        The third asserted spine REFUSED and named an elevated lane as the
        missing capability. Also wrong: the drop was always emitted at `z = 1`;
        what was missing was a route to it.

        So this asserts the outcome that actually matters and asserts its own
        sample first. `game.addon_supply` yields nothing for a placement with no
        coater in it, so without the containment check a spec that lost its
        coaters would pass this silently -- which is precisely the shape of
        error this file has now made three times.
        """
        spec = self._candidate("free-proliferation")
        assert spec.spray_lanes, "sample has no spray lanes; nothing below tests anything"
        p = SpineLayout(power=False).lay_out(spec, time_budget_s=4.0)
        coaters = [b for b in p.buildings if b.item_id == catalog.SPRAY_COATER_ID]
        assert len(coaters) >= 2, f"expected the multi-coater case, got {len(coaters)}"
        assert [b for b in p.buildings if b.z and b.z > 0], "no elevated supply at all"
        report = validate.validate(
            p, spec, ids=validate.id_map(spec), expect_power=False
        )
        assert not report.by_check("game.addon_supply"), [
            f.message for f in report.by_check("game.addon_supply")
        ]
        assert report.ok, sorted({f.check for f in report.errors})

    @pytest.mark.slow
    def test_the_ten_coater_case_places_every_spur_by_climbing_over_machines(
        self,
    ) -> None:
        """The refusal that is GONE, and the check that would have caught a cheat.

        `max-proliferation` has ten spray lanes.  Nine of its ten spurs used to
        place and the tenth found no route, because `_spur_clear` refused to fly
        a belt over anything that was not a belt.  The game's rule is read now:
        `CheckBuildConditions` probes a belt preview with a 0.23 sphere rather
        than its box, so a belt MAY cross a machine and the price is height --
        `colliders.belt_crossing_height`, which `_belt_floor_over` rounds up to
        the altitude quantum.

        `game.belt_crossing` is what makes this a test and not a hope.  A spur
        that flew at `z = 1` over an Assembling Machine would place, and would
        paste as `EBuildCondition.Collide`; that check convicts it and is
        asserted separately from `report.ok` so a future default change cannot
        silently stop exercising it.  Its own sample is asserted first: the
        placement really does contain a belt above `z = 1`, so a build that lost
        its climb could not pass this quietly.

        TEN SPRAY LANES ARE MORE THAN TEN LANES.  This asserted exactly ten
        coaters, one per spray lane, and that number was the defect wearing a
        test: an item has one entry in `spray_lanes` and as many LANES in the
        corridors as the machines eating it need, and `_place_coaters` used to
        `break` after seating the first.  Measured on this exact spec with
        spine's own self-check disabled so the raw emission could be read: ten
        coaters, and **35 sorters feeding a proliferated machine off a lane no
        coater had sprayed**.  So the count is now bounded below by the spray
        lanes and the real invariant is asserted beside it --
        `prolif.sprayed_cargo_reaches_machines`, which is 0 here and was 35.
        """
        spec = self._corpus_candidate("max-proliferation")
        assert len(spec.spray_lanes) >= 10, "sample is not the ten-lane case"
        p = SpineLayout(power=False).lay_out(spec, time_budget_s=4.0)
        coaters = [b for b in p.buildings if b.item_id == catalog.SPRAY_COATER_ID]
        assert len(coaters) >= len(spec.spray_lanes), (
            f"{len(spec.spray_lanes)} spray lane(s) and {len(coaters)} coater(s)"
        )
        assert [b for b in p.buildings if b.z and b.z > 1], (
            "nothing climbed above the addon level, so the crossing rule was "
            "never exercised and the assertions below prove nothing"
        )
        report = validate.validate(p, spec, ids=validate.id_map(spec), expect_power=False)
        assert not report.by_check("game.addon_supply"), [
            f.message for f in report.by_check("game.addon_supply")
        ]
        assert not report.by_check("game.belt_crossing"), [
            f.message for f in report.by_check("game.belt_crossing")
        ]
        unsprayed = report.by_check("prolif.sprayed_cargo_reaches_machines")
        assert not unsprayed, [f.message for f in unsprayed]
        assert report.ok, sorted({f.check for f in report.errors})
    @pytest.mark.slow
    def test_every_coater_has_elevated_positional_supply_without_sorter(
        self,
    ) -> None:
        from flab2bp.layout import slots
        from flab2bp.layout.spine import _emit, _solve_plan, proliferator_item

        spec = self._prolif_spec()
        plans, _reason, _detail = _solve_plan(
            spec, time_budget_s=0.5, workers=1
        )
        placement: Placement | None = None
        for plan in plans:
            try:
                placement = _emit(spec, plan, power=False)
            except ValueError:
                continue
            break
        assert placement is not None
        proliferator = proliferator_item(spec)
        supply = {
            (building.x, building.y, building.z)
            for building in placement.buildings
            if catalog.is_belt(building.item_id)
            and building.carries_item == proliferator
        }
        coaters = [
            (index, building)
            for index, building in enumerate(placement.buildings)
            if building.item_id == catalog.SPRAY_COATER_ID
        ]
        assert coaters, "expected coaters on a max-proliferation spec"
        coater_indices = {index for index, _building in coaters}
        assert not [
            sorter
            for sorter in placement.buildings
            if catalog.is_sorter(sorter.item_id)
            and (
                sorter.input_obj in coater_indices
                or sorter.output_obj in coater_indices
            )
        ]

        _host, addon = catalog.building(catalog.SPRAY_COATER_ID).addon_areas
        for _index, coater in coaters:
            dx, dy = slots.to_world((addon[0], addon[1]), coater.yaw)
            target = (
                coater.x + round(dx),
                coater.y + round(dy),
                coater.z + F(round(addon[2])),
            )
            assert target in supply, (
                f"coater at {(coater.x, coater.y, coater.z)} has no "
                f"proliferator belt at elevated addon target {target}"
            )

    def test_a_spur_may_cross_a_machine_only_at_that_machine_s_own_height(
        self,
    ) -> None:
        """The permission is per-model, and the model is the game's.

        The whole hazard in loosening `_spur_clear` is loosening it by a
        constant.  An Arc Smelter clears at `z = 3` and an Assembling Machine
        Mk.II does not -- it needs 3.5325, so `z = 4` -- and a spur that took
        the smelter's answer for the assembler would place and then paste red.

        The bound is STRICT in the game, which is why the assertions sit on the
        quantum ABOVE it rather than on the bound itself.  Sorters are excused
        outright by `PrefabDesc` flag, in both directions.
        """
        from flab2bp.layout.spine import _spur_clear

        def _one(item_id: int) -> list[PlacedBuilding]:
            info = catalog.building(item_id)
            return [
                PlacedBuilding(
                    item_id=item_id,
                    model_index=info.model_index,
                    x=0,
                    y=0,
                    z=Fraction(0),
                    width=info.width,
                    height=info.height,
                )
            ]

        smelter = _one(MACHINE_ITEM_IDS["arc-smelter"])
        assembler = _one(MACHINE_ITEM_IDS["assembling-machine-2"])
        for z in (F(0), F(1), F(2), F(5, 2)):
            assert not _spur_clear(smelter, 0, 0, z), f"smelter cleared at {z}"
            assert not _spur_clear(assembler, 0, 0, z), f"assembler cleared at {z}"
        assert _spur_clear(smelter, 0, 0, F(3)), "an Arc Smelter clears at 3"
        assert not _spur_clear(assembler, 0, 0, F(3)), (
            "an Assembling Machine needs 3.5325, so z = 3 must still collide"
        )
        assert not _spur_clear(assembler, 0, 0, F(7, 2)), (
            "3.5325 is STRICT: rounding it down to the quantum below pastes red"
        )
        assert _spur_clear(assembler, 0, 0, F(4)), "an assembler clears at 4"

        sorter = _one(catalog.SORTER_IDS[0])
        assert _spur_clear(sorter, 0, 0, F(1, 2)), "a sorter is excused outright"
        assert not _spur_clear(sorter, 0, 0, F(0)), (
            "excused from the crossing probe is not excused from the tile"
        )

class TestModeDrivenMachines:
    """Some machines are configured by a MODE, not a recipe id.

    An Energy Exchanger's charge/discharge lives in its parameter block while
    ``recipe_id`` stays zero.  FactorioLab still models these as ordinary
    recipes with real item flow, so they belt, sort and lay out like anything
    else -- only the emission differs.

    Getting the block wrong is worse than omitting it: the blueprint pastes
    cleanly and then runs the wrong way round, draining the accumulators it was
    meant to fill, and nothing about the paste looks wrong.
    """

    @staticmethod
    def _exchanger_spec(recipe: str = "accumulator-full") -> BuildSpec:
        """Two exchangers fed by a belted accumulator supply."""
        return BuildSpec(
            groups=(
                group(
                    recipe,
                    "energy-exchanger",
                    2,
                    {"accumulator": F(1)},
                    {"accumulator-full": F(1)},
                ),
            ),
            external_inputs={"accumulator": F(2)},
            outputs={"accumulator-full": F(2)},
            belt_item_id="conveyor-belt-2",
            belt_items_per_second=F(12),
            label="exchanger",
        )

    def _exchangers(self, p: Placement) -> list[PlacedBuilding]:
        return [b for b in p.buildings if b.item_id == catalog.ENERGY_EXCHANGER_ID]

    def test_the_game_gives_an_exchanger_no_sorter_slot_at_all(self) -> None:
        """Ground truth, and the reason for the refusal below.

        ``slot_poses.json`` is extracted from the game's own prefabs, and the
        Energy Exchanger's ``slotPoses`` array is EMPTY -- as is the Ray
        Receiver's.  Every other machine in the corpus offers columns from at
        least one face.  If a later extraction fills these in, this test fails
        first and says so, rather than the refusal below quietly becoming wrong.
        """
        from flab2bp.layout import slots as sorter_slots

        probe = sorter_slots.probe_building(catalog.ENERGY_EXCHANGER_ID, 0.0)
        offsets = [*range(-catalog.SORTER_MAX_REACH, 0), *range(9, 9 + 4)]
        assert all(not sorter_slots.attachable_columns(probe, y) for y in offsets)

    def test_spine_refuses_the_machine_rather_than_shipping_it_unwired(self) -> None:
        """What this used to assert was that the layout SUCCEEDED, and it did.

        Measured on the code before the per-side tap charge: the spec emitted two
        Energy Exchangers and **zero sorters in the whole placement** -- neither
        exchanger joined to anything at either end -- and `test_the_placement_
        validates` called that report ok.  The old tap model read a face with no
        reachable pose as costing NOTHING, because it took the worst of two
        sides and both sides were "unknown"; so the allocator seated lanes for
        it, `_find_taps` found no span, and `_emit` swallowed the miss.

        A blueprint that pastes two idle exchangers is worse than a refusal that
        names the reason, so this now asserts the refusal.  See docs/BACKLOG.md
        for the open question of whether the extraction is incomplete -- that is
        where a fix belongs, not in the tap model.
        """
        with pytest.raises(NoValidLayout) as exc:
            SpineLayout(power=False).lay_out(self._exchanger_spec(), time_budget_s=0.5)
        assert "takes no sorter on any face" in exc.value.reason
        assert "energy-exchanger" in exc.value.reason

    def test_the_machine_carries_the_mode_not_a_recipe(self) -> None:
        """Asked of the unit that decides it, since no placement reaches here.

        ``_machine_config`` is where the two kinds of machine part company, and
        the contract -- exactly one of a recipe id or a parameter block, never
        half of each -- is its own, not the packer's.
        """
        from flab2bp.dsp import params
        from flab2bp.layout.spine import _machine_config

        recipe_id, parameters = _machine_config("accumulator-full")
        assert recipe_id == 0, "a mode-driven machine must not claim a recipe id"
        assert parameters == params.parameters_for("accumulator-full")

    def test_the_two_poles_emit_different_blocks(self) -> None:
        """Charge and discharge are opposite words, not the same machine twice.

        A test that only checked ``parameters != ()`` would pass with both poles
        wired to the same value, which is exactly the failure that drains a
        factory instead of filling it.
        """
        from flab2bp.layout.spine import _machine_config

        charge = _machine_config("accumulator-full")
        discharge = _machine_config("accumulator-discharge")
        assert charge == (0, (1,)) and discharge == (0, (-1,)), f"{charge} {discharge}"

    def test_ordinary_recipes_still_carry_a_recipe_id(self) -> None:
        """The mode path must not swallow normal machines."""
        p = SpineLayout(power=False).lay_out(single_recipe_spec(), time_budget_s=0.5)
        smelters = [b for b in p.buildings if b.item_id == MACHINE_ITEM_IDS["arc-smelter"]]
        assert smelters
        assert all(b.recipe_id == catalog.recipe_id("iron-ingot") for b in smelters)
        assert all(b.parameters == () for b in smelters)


class TestAMachineTheGameTakesNoSorterOn:
    """The refusal must name the PREFAB, because that is what is wrong.

    Settled from the game, not inferred.  ``BuildTool_Inserter`` drops any cast
    target whose ``PrefabDesc.slotPoses`` is empty and which is not a belt, and
    ``PrefabDesc.slotPoses`` is ``SlotConfig.insertPoses`` -- which the Ray
    Receiver and the Energy Exchanger ship EMPTY.  Their prefabs carry one
    ``SlotConfig`` each, on the root, with ``insertPoses`` length 0 and
    ``addonAreaCenter`` length 0; their only pose children are named ``slot-0``
    and ``slot(0..3)``, and those are the BELT PORTS.  The game wires them by
    docking a belt straight into a port -- all 45 Energy Exchangers in the
    fixture corpus have exactly that: 90 peers, every one a belt.

    Spine has no belt-to-port docking, so the refusal is right.  What these pin
    is that it SAYS SO.  The case used to arrive as ``FALLBACK_SEED_UNWIRABLE``
    -- "no ordering of its two corridors puts in reach; machine heights differ
    by up to 6 tiles" -- which is a statement about a packing, is not what is
    wrong here, and sends the next reader to the row model instead of to the
    prefab.
    """

    @staticmethod
    def _ray_receiver_spec() -> BuildSpec:
        """A pure SOURCE: the game gives a Ray Receiver photons, not items.

        This is the shape the ``universe-matrix`` corpus cell actually has --
        ``inputs_per_machine`` is literally empty and the only lane it wants is
        the critical-photon OUTPUT -- so the refusal cannot be waved away as
        being about a feed that does not exist.
        """
        return BuildSpec(
            groups=(
                group(
                    "critical-photon", "ray-receiver", 4, {}, {"critical-photon": F(1)}
                ),
            ),
            external_inputs={},
            outputs={"critical-photon": F(4)},
            belt_item_id="conveyor-belt-2",
            belt_items_per_second=F(12),
            label="photons",
        )

    def test_the_refusal_names_the_prefab_and_the_mechanism(self) -> None:
        with pytest.raises(NoValidLayout) as exc:
            SpineLayout(power=False).lay_out(
                self._ray_receiver_spec(), time_budget_s=0.5
            )
        reason = exc.value.reason
        assert "ray-receiver" in reason, reason
        assert "0 insert poses" in reason, reason
        assert "belt port" in reason, reason
        assert "critical-photon" in reason, reason

    def test_it_no_longer_blames_the_row_model(self) -> None:
        """The old message was not merely vague, it pointed somewhere wrong.

        Corridor ordering and a height difference are real causes of a real
        refusal.  Quoting them for a machine that takes no sorter at all is the
        failure this project keeps paying for: a message that could not have
        been produced by the actual cause.
        """
        with pytest.raises(NoValidLayout) as exc:
            SpineLayout(power=False).lay_out(
                self._ray_receiver_spec(), time_budget_s=0.5
            )
        reason = exc.value.reason
        assert "no ordering of its two corridors" not in reason, reason
        assert "machine heights differ" not in reason, reason

    def test_it_is_deterministic_and_skips_the_retry(self) -> None:
        """A prefab fact cannot be solved by spending more seconds on it."""
        from flab2bp.layout.spine import FALLBACK_SORTERLESS_MACHINE, _solve_plan

        plans, reason, detail = _solve_plan(
            self._ray_receiver_spec(),
            time_budget_s=0.5,
            workers=DETERMINISTIC_WORKERS,
        )
        assert plans == []
        assert reason == FALLBACK_SORTERLESS_MACHINE
        assert "ray-receiver" in detail

    def test_the_coater_never_reaches_the_check_at_all(self) -> None:
        """Why there is no belt-addon exclusion, pinned rather than argued.

        A Spray Coater ships zero insert poses too, and it IS fed -- positionally,
        through ``addonAreaPoses``.  Excluding it here looks obviously right and
        would be dead code: it is not a machine the spec can name, and none of
        the poseless buildings that CAN reach the check is a belt addon.  If that
        ever changes -- a coater becomes a spec group, or a belt addon is added
        to ``MACHINE_ITEM_IDS`` -- this fails, and the exclusion has to come back
        before the check starts refusing a machine the emitter would have fed.
        """
        from flab2bp.layout.spine import MACHINE_ITEM_IDS

        assert "spray-coater" not in MACHINE_ITEM_IDS
        poseless = [
            name
            for name, item_id in MACHINE_ITEM_IDS.items()
            if not catalog.building(item_id).slot_poses
        ]
        assert poseless, "the check would be unreachable if this were empty"
        assert not [n for n in poseless if catalog.building(MACHINE_ITEM_IDS[n]).is_belt_addon]

    def test_a_proliferated_spec_is_untouched_by_it(self) -> None:
        """The coater's own group -- the smelter -- takes sorters and is kept."""
        from flab2bp.layout.spine import _adapt, _sorterless_groups

        spec = BuildSpec(
            groups=(
                group(
                    "iron-ingot",
                    "arc-smelter",
                    2,
                    {"iron-ore": F(1)},
                    {"iron-ingot": F(1)},
                    mode=ProliferatorMode.PRODUCTS,
                ),
            ),
            external_inputs={"iron-ore": F(2)},
            outputs={"iron-ingot": F(2)},
            belt_item_id="conveyor-belt-2",
            belt_items_per_second=F(12),
            label="sprayed",
        )
        groups, _edges = _adapt(spec)
        assert _sorterless_groups(groups) == []

    def test_a_machine_with_nothing_to_wire_is_not_charged(self) -> None:
        """The refusal is about what the machine NEEDS, not what its prefab lacks.

        Refusing a building over a connection it never wanted would be refusing
        the wrong thing.  Nothing in the corpus is shaped that way today, so it
        is asked of the unit rather than of a spec.
        """
        from flab2bp.layout.spine import _adapt, _sorterless_groups

        spec = BuildSpec(
            groups=(group("critical-photon", "ray-receiver", 1, {}, {}),),
            external_inputs={},
            outputs={},
            belt_item_id="conveyor-belt-2",
            belt_items_per_second=F(12),
            label="idle",
        )
        groups, _edges = _adapt(spec)
        assert _sorterless_groups(groups) == []


class TestSortersAreSizedPerItem:
    """A sorter must carry the item it actually moves, not a machine average.

    A machine's ingredients have DIFFERENT rates -- ``electric-motor`` takes
    iron-ingot, gear and magnetic-coil -- so charging every feed the machine's
    mean lets the hot ingredient's sorter come up short while the cold one's is
    oversized.  The pair averages out to something that reads as fine, the
    starved sorter throttles the machine, and the build pastes, runs and quietly
    misses its rate.

    Measured before the fix on the example URL: 12 sorters asked for 1 item/s of
    iron-ingot across 2 tiles, where a Mk.I sustains 3/4.
    """

    def test_a_rate_above_the_cheap_tier_does_not_get_the_cheap_tier(self) -> None:
        """Directly pins the sizing contract, and fails under averaging.

        1/s across 2 tiles is exactly the case that shipped broken: a Mk.I
        manages 3/4 there, so it must not be chosen with a single sorter.
        """
        from flab2bp.layout.spine import SORTER_TIERS, _pick_sorter

        tier, count = _pick_sorter(F(1), span=2, available=3)  # type: ignore[misc]
        assert catalog.sorter_rate(tier, 2) * count >= F(1), (
            f"tier {tier} x{count} sustains "
            f"{catalog.sorter_rate(tier, 2) * count}, needs 1"
        )
        assert not (tier == SORTER_TIERS[0] and count == 1), (
            "a single Mk.I carries only 3/4 across two tiles"
        )

    def test_every_tier_choice_actually_carries_its_rate(self) -> None:
        """Sweep the space rather than trusting one sample."""
        from flab2bp.layout.spine import _pick_sorter

        for span in (1, 2, 3):
            for num in range(1, 25):
                rate = F(num, 4)
                pick = _pick_sorter(rate, span=span, available=4)
                if pick is None:
                    continue
                tier, count = pick
                assert catalog.sorter_rate(tier, span) * count >= rate, (
                    f"rate={rate} span={span}: {tier} x{count} is short"
                )

    @pytest.mark.slow
    def test_the_real_chain_has_no_starved_sorters(self) -> None:
        """The repro that shipped: every candidate of the example URL.

        This used to expect spine to refuse BOTH proliferated candidates,
        because a Spray Coater is supplied by an elevated belt in its own row
        and spine was thought unable to grow one.  It can: the drop was always
        emitted at ``z = 1`` and what was missing was a route to it, which is
        now an elevated spur.  ``free-proliferation`` builds.

        ``max-proliferation`` USED TO REFUSE, on its tenth coater's spur, and
        that refusal is gone: rationing machine slots forced the lane extents to
        cover every column a sorter might be pushed onto, which lengthened the
        lanes and gave the spur search room it never had.  All three candidates
        build now.

        EVERY COUNT IS STILL ASSERTED.  Skipping any of them would let this pass
        over an empty set the day candidate generation changes -- the failure
        ``mixed_height_spec`` spent a branch demonstrating, where a fixture that
        stops containing the shape under test goes on passing.
        """
        from flab2bp.lab.data import load_vendored
        from flab2bp.lab.url import parse_url
        from flab2bp.pipeline import _id_map
        from flab2bp.rates.candidates import build_candidates

        url = (
            "https://factoriolab.github.io/dsp/flow?o=super-magnetic-ring*60"
            "&ibe=conveyor-belt-2"
            "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11"
        )
        checked = refused = sprayed = 0
        for spec in build_candidates(load_vendored(), parse_url(url), count=3).candidates:
            try:
                p = SpineLayout(power=False).lay_out(spec, time_budget_s=0.5)
            except NoValidLayout as exc:
                assert "Spray Coater" in exc.reason, exc.reason
                refused += 1
                continue
            report = validate.validate(
                p,
                spec,
                ids=_id_map(spec),
                expect_power=False,
                only=["flow.sorter_capacity"],
            )
            assert report.ok, f"{spec.label}: " + "\n".join(
                f.message for f in report.errors[:5]
            )
            checked += 1
            if spec.spray_lanes:
                sprayed += 1
        assert (checked, refused) == (3, 0), (checked, refused)
        # A PROLIFERATED candidate has to be among the ones checked, or this
        # says nothing about sorter sizing on the specs that grew coaters.
        # BOTH of them are, now that neither refuses: 3 spray lanes on
        # `free-proliferation` and 11 on `max-proliferation`.
        assert sprayed == 2, sprayed


class TestABridgePassesUnderAJunctionAndNotOverIt:
    """`game.belt_collide` on the trunk margin, which is where spine met it.

    A trunk that feeds a lane and carries on needs a Splitter, and a Splitter's
    build collider is a 2.38-unit cross standing 2.30 units tall against a
    level's 4/3.  `colliders.belt_keepout_offsets` measures the consequence and
    it is ASYMMETRIC: the cells a foreign belt may not stand in run from the
    junction's own level to ONE above it, and there are none below.  So the
    crossing goes underneath -- `_TRUNK_Z` lifts the trunks and the bridges stay
    on the ground -- and the clash is gone by construction rather than by search.

    Two items on ADJACENT lane rows is the shape that cannot be ordered away:
    each trunk's bridges then run a tile from the other's junctions whichever
    column each takes.
    """

    def _previews(self, buildings: list[PlacedBuilding]) -> list[C.Preview]:
        """The placement as `CheckBuildConditions` sees it."""
        return [
            C.Preview(
                b.model_index,
                float(b.x),
                float(b.y),
                float(b.z),
                float(b.yaw),
                is_belt=catalog.is_belt(b.item_id),
                is_inserter=catalog.is_sorter(b.item_id),
                is_splitter=b.item_id == catalog.SPLITTER_ID,
                is_belt_addon=False,
                output=b.output_obj,
                input=b.input_obj,
            )
            for b in buildings
        ]

    def _scene(self) -> tuple[list[PlacedBuilding], int]:
        from flab2bp.layout.spine import _assign_columns, _emit_risers, _Riser

        content_w = 6
        belt_id, belt_model = 2001, 35
        buildings: list[PlacedBuilding] = []
        lane_tiles: dict[tuple[int, int], list[int]] = {}
        # Four lanes, two of them on ADJACENT rows (3 and 4) so the two trunks
        # tap a tile apart.
        for key, row in (((0, 0), 0), ((0, 1), 1), ((1, 0), 3), ((1, 1), 4)):
            tiles = []
            for x in range(content_w):
                tiles.append(len(buildings))
                buildings.append(
                    PlacedBuilding(
                        item_id=belt_id, model_index=belt_model, x=x, y=row,
                        width=1, height=1, carries_item="a",
                    )
                )
            for a, b in zip(tiles, tiles[1:], strict=False):
                buildings[a] = replace(buildings[a], output_obj=b)
            lane_tiles[key] = tiles
        risers = _assign_columns(
            [
                _Riser(item="a", taps=((0, 0, 0, True), (3, 1, 0, False), (6, 2, 0, False))),
                _Riser(item="b", taps=((1, 0, 1, True), (4, 1, 1, False), (7, 2, 1, False))),
            ]
        )
        lane_tiles[(2, 0)] = lane_tiles[(1, 0)]
        lane_tiles[(2, 1)] = lane_tiles[(1, 1)]
        _emit_risers(
            buildings, risers, lane_tiles,
            content_w=content_w, belt_id=belt_id, belt_model=belt_model,
        )
        return buildings, sum(
            1 for b in buildings if b.item_id == catalog.SPLITTER_ID
        )

    def test_the_margin_convicts_nothing(self) -> None:
        buildings, junctions = self._scene()
        assert junctions == 2, (
            "the scene stopped producing the junctions it exists to test, so a "
            "clean verdict below would prove nothing"
        )
        hits = C.belt_collisions(self._previews(buildings))
        named = [
            (i, j, catalog.building(buildings[j].item_id).name) for i, j in hits[:5]
        ]
        assert not hits, named

    def test_every_junction_stands_above_the_bridges_that_cross_it(self) -> None:
        """The invariant, stated where a future change to the profile would break it."""
        from flab2bp.layout.spine import _TRUNK_Z

        buildings, _ = self._scene()
        for b in buildings:
            if b.item_id != catalog.SPLITTER_ID:
                continue
            assert b.z == _TRUNK_Z
            for cell in junction.keepout_cells(b.x, b.y, int(b.z)):
                for other in buildings:
                    if other is b or not catalog.is_belt(other.item_id):
                        continue
                    if (other.x, other.y) != cell[:2]:
                        continue
                    assert math.floor(other.z) != cell[2] or other.x == b.x, (
                        f"a belt at ({other.x}, {other.y}, {other.z}) stands in "
                        f"the keep-out of a junction at ({b.x}, {b.y}, {b.z})"
                    )


class TestACoaterRidesTheHeadOfItsLane:
    """A coater sprays what passes THROUGH it, so the sorters must be behind it.

    ``_coater_tile`` used to mount the coater on the column nearest the lane's
    MIDPOINT that the corridor's proliferator lane also covered -- a supply
    convenience from before ``_feed_coater`` grew a spur.  Every sorter upstream
    of that column then fed its machine cargo that had not been sprayed, and
    nothing said so: the lane had its coater, the coater had its proliferator,
    and ``prolif.coaters_are_supplied`` passed.

    MEASURED over the first six corpus URLs and every proliferated candidate
    they offer: 15 of 61 sprayed pickups drew from upstream of their own coater,
    spread over nine of the ten candidates.  After the seat moved to the lane
    head: 0 of 61, with all ten still building.
    """

    @staticmethod
    def _lane(xs: list[int], *, westward: bool) -> list[PlacedBuilding]:
        """A lane in X order, forward-linked along its direction of travel.

        ``lane_tiles`` keeps x order whichever way a lane runs and reverses only
        the ``output_obj`` chain, which is exactly the trap ``_lane_flow_order``
        exists to avoid: a westward lane's head is its LAST entry.
        """
        out = [
            PlacedBuilding(item_id=2001, model_index=35, x=x, y=0, width=1, height=1)
            for x in xs
        ]
        chain = list(range(len(xs)))[:: -1 if westward else 1]
        for a, b in zip(chain, chain[1:], strict=False):
            out[a] = replace(out[a], output_obj=b)
        return out

    def test_the_head_of_an_eastward_lane_is_its_first_tile(self) -> None:
        from flab2bp.layout.spine import _coater_tile

        lane = self._lane([0, 1, 2, 3], westward=False)
        assert _coater_tile(lane, [0, 1, 2, 3], 90.0) == 0

    def test_the_head_of_a_westward_lane_is_its_last_tile(self) -> None:
        """X order and flow order disagree here, and flow order is the one that counts."""
        from flab2bp.layout.spine import _coater_tile

        lane = self._lane([0, 1, 2, 3], westward=True)
        assert _coater_tile(lane, [0, 1, 2, 3], 90.0) == 3

    def test_the_seat_is_never_the_midpoint_of_a_four_tile_lane(self) -> None:
        """Named explicitly: the midpoint is what the old code returned."""
        from flab2bp.layout.spine import _coater_tile

        for westward in (False, True):
            lane = self._lane([0, 1, 2, 3], westward=westward)
            assert _coater_tile(lane, [0, 1, 2, 3], 90.0) != 2, (
                "the coater is back on the lane's midpoint, and every sorter "
                "upstream of it draws unsprayed cargo"
            )

    def test_the_yaw_puts_the_drop_over_the_lane_and_not_off_its_end(self) -> None:
        """Area 1 sits BEHIND the coater, so a head seat has to face upstream.

        Facing WITH the flow puts the proliferator drop one tile off the
        upstream end of the corridor -- x = -1 on a lane starting at column 0,
        outside the box the spur search may use.  All ten proliferated
        candidates over the first six corpus URLs refused that way.
        """
        from flab2bp.layout.spine import _addon_area_step, _coater_yaw

        lane = self._lane([0, 1, 2, 3], westward=False)
        yaw = _coater_yaw(lane, 0)
        assert _addon_area_step(yaw) == (1, 0), (
            f"yaw {yaw} puts the drop at {_addon_area_step(yaw)} from the seat; "
            "it must land on the lane's own next tile"
        )

    @pytest.mark.slow
    def test_every_sprayed_pickup_on_a_real_spec_is_downstream_of_a_coater(
        self,
    ) -> None:
        """End to end, on the spec the seat defect was measured on.

        Red before the seat moved: this spec built, with a coater on every spray
        lane, and the validator convicted the pickups.
        """
        spec = TestSprayCoatersAreFed._candidate("free-proliferation")
        assert spec.spray_lanes, "sample has no spray lanes; nothing below tests anything"
        p = SpineLayout(power=False).lay_out(spec, time_budget_s=4.0)
        coaters = [b for b in p.buildings if b.item_id == catalog.SPRAY_COATER_ID]
        assert len(coaters) >= len(spec.spray_lanes), (
            f"{len(spec.spray_lanes)} spray lane(s) and {len(coaters)} coater(s): "
            "a lane without one feeds its machines unsprayed cargo"
        )
        report = validate.validate(
            p, spec, ids=validate.id_map(spec), expect_power=False
        )
        bad = report.by_check("prolif.sprayed_cargo_reaches_machines")
        assert not bad, [f.message for f in bad]
