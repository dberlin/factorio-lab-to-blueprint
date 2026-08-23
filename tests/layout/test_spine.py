"""Strategy A end-to-end properties.

Specs are hand-built here rather than taken from ``rates/``, which is being
implemented concurrently -- these tests must pin the layout's behaviour, not the
rate solver's.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from fractions import Fraction

import pytest

from flab2bp.dsp import catalog
from flab2bp.layout import validate
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


# --- helpers ---------------------------------------------------------------


def blocking_tiles(p: Placement) -> list[tuple[int, int, int]]:
    """Tiles that genuinely exclude another building.

    Belt-integrated buildings share tiles rather than consuming them: belts,
    sorters and splitters all sit at dx=dy=0.00 from a belt in real blueprints.
    Belt addons such as the Spray Coater occupy no grid tile at all.  Neither
    class may be counted as blocking, or every valid layout would fail.
    """
    tiles: list[tuple[int, int, int]] = []
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
        heterogeneity is proven by the larger plants instead -- a 9x5 chemical
        plant is five times the area of a 3x3 smelter, and the 3x7 refinery is
        the case where width and height differ.
        """
        smelter = machine_group_footprint(group("x", "arc-smelter", 1))
        assembler = machine_group_footprint(group("x", "assembling-machine-2", 1))
        chemical = machine_group_footprint(group("x", "chemical-plant", 1))
        lab = machine_group_footprint(group("x", "matrix-lab", 1))
        refinery = machine_group_footprint(group("x", "oil-refinery", 1))

        assert smelter == (3, 3)
        assert assembler == (3, 3)
        assert chemical == (9, 5)
        assert lab == (5, 5)
        assert refinery == (3, 7)

        # Genuinely heterogeneous: at least three distinct sizes, spanning a 5x
        # area range, including a non-square one.
        assert len({smelter, chemical, lab, refinery}) >= 3
        assert chemical[0] * chemical[1] >= 5 * smelter[0] * smelter[1]
        assert refinery[0] != refinery[1]

    def test_every_derived_footprint_dimension_is_odd(self) -> None:
        """The derived rule is ``2 * ceil(box / 2) - 1``, so never even.

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
        occupied: set[tuple[int, int, int]] = set()
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

    Asserted as the physical rule -- no two consecutive links may both change
    altitude -- rather than as a column count, so a different margin layout that
    is equally honest still passes.
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
            prev = upstream.get(i)
            assert prev is not None, (
                f"belt {i} at ({bs[i].x},{bs[i].y},z={bs[i].z}) changes level with "
                f"nothing feeding it, so it had no tile of run-up"
            )
            assert bs[prev].z == bs[i].z, (
                f"belts {prev} -> {i} -> {bs[i].output_obj} change level on "
                f"consecutive tiles; a belt needs "
                f"{catalog.RAMP_TILES_PER_LEVEL} tiles per level"
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
    def test_spray_coater_consumes_no_grid_tile(self) -> None:
        spec = two_stage_spec()
        prolif = BuildSpec(
            groups=spec.groups,
            # Proliferator has to be belted in. This test used to omit it, and
            # the layout it then produced had coaters with nothing feeding them
            # -- it passed only because the test asked whether a coater consumes
            # a grid tile, never whether it could spray.
            external_inputs={**spec.external_inputs, "proliferator-3": F(1) / 2},
            outputs=spec.outputs,
            belt_item_id=spec.belt_item_id,
            belt_items_per_second=spec.belt_items_per_second,
            spray_lanes={"iron-ingot": False},
            label="prolif",
        )
        p = SpineLayout(power=False).lay_out(prolif, time_budget_s=0.5)
        coaters = [b for b in p.buildings if b.item_id == catalog.SPRAY_COATER_ID]
        assert coaters
        assert not catalog.building(catalog.SPRAY_COATER_ID).occupies_tiles
        tiles = blocking_tiles(p)
        assert len(tiles) == len(set(tiles))

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

    What closes it is that the cap is on LANES and the overflow is in ITEMS.
    Two items ride one lane with each tapping sorter filtered to its own item,
    which is a mechanism freeform has shipped since ``six_input_spec`` and the
    validator already reads: ``_sorter_item`` trusts ``filter_id`` above every
    other source, so nothing in ``validate`` had to change for this.
    """

    @staticmethod
    def _filters(p: Placement) -> list[PlacedBuilding]:
        return [b for b in p.buildings if b.filter_id]

    @pytest.mark.parametrize("power", [True, False], ids=["power", "no-power"])
    def test_it_lays_out_and_validates_clean(self, power: bool) -> None:
        from flab2bp.pipeline import _id_map

        spec = seven_item_spec()
        p = SpineLayout(power=power).lay_out(spec, time_budget_s=0.5)
        assert p.stats["fallback_reason"] == FALLBACK_NONE
        report = validate.validate(p, spec, ids=_id_map(spec), expect_power=power)
        assert report.ok, [f.message for f in report.errors]

    def test_exactly_one_lane_carries_two_items(self) -> None:
        """Seven items on six lanes is ONE shared lane, not seven halves."""
        plan = fallback_plan(seven_item_spec())
        assert sum(len(c) for c in plan.lanes) == 2 * catalog.SORTER_MAX_REACH
        assert len(plan.mixed) == 1
        (shared,) = plan.mixed.values()
        assert len(shared) == 2
        # The product owns its lane's exit, so it is never one of the pair.
        assert "universe-matrix" not in shared

    def test_both_sorters_on_the_shared_lane_are_filtered(self) -> None:
        """An unfiltered sorter on a shared lane starves the other machine.

        It grabs whatever passes, and the blueprint still pastes perfectly
        cleanly -- which is why this is pinned rather than trusted.
        """
        spec = seven_item_spec()
        plan = fallback_plan(spec)
        (shared,) = plan.mixed.values()
        p = SpineLayout(power=False).lay_out(spec, time_budget_s=0.5)
        filtered = self._filters(p)
        assert {b.filter_id for b in filtered} == {
            catalog.get_item_id(i) for i in shared
        }
        # And no sorter anywhere else got a filter it does not need: the zero is
        # the signal `validate` uses to tell a shared lane from a plain one.
        assert len(filtered) == 2

    def test_the_two_sorters_do_not_share_an_anchor_column(self) -> None:
        """One column each, or the second sorter lands on top of the first."""
        p = SpineLayout(power=False).lay_out(seven_item_spec(), time_budget_s=0.5)
        columns = {b.x for b in self._filters(p)}
        assert len(columns) == 2

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

        plan, reason, detail = _solve_plan(
            two_lab_spec(), time_budget_s=0.5, workers=DETERMINISTIC_WORKERS
        )
        assert plan is None
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
            spine, "_solve_plan", lambda *a, **k: (None, spine.FALLBACK_UNROUTABLE, "")
        )
        with pytest.raises(NoValidLayout):
            SpineLayout(power=False).lay_out(spec, time_budget_s=0.5)

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


# --- real corpus specs -----------------------------------------------------


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
        return min(candidates, key=lambda s: s.machine_count)

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
        return min(candidates, key=lambda s: s.machine_count)

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
        return min(candidates, key=lambda s: s.machine_count)

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
    def _prolif_spec() -> BuildSpec:
        from flab2bp.lab.data import load_vendored
        from flab2bp.lab.url import parse_url
        from flab2bp.rates.candidates import build_candidates

        url = (
            "https://factoriolab.github.io/dsp/flow?o=super-magnetic-ring*60"
            "&ibe=conveyor-belt-2"
            "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11"
        )
        cands = build_candidates(load_vendored(), parse_url(url), count=3).candidates
        return next(c for c in cands if c.label == "max-proliferation")

    @pytest.mark.slow
    def test_a_proliferator_lane_exists(self) -> None:
        from flab2bp.layout.spine import proliferator_item

        spec = self._prolif_spec()
        p = SpineLayout(power=False).lay_out(spec, time_budget_s=0.5)
        prolif = proliferator_item(spec)
        assert prolif is not None
        carried = {b.carries_item for b in p.buildings if catalog.is_belt(b.item_id)}
        assert prolif in carried, (
            f"no belt carries {prolif}; carried={sorted(x for x in carried if x)}"
        )

    @pytest.mark.slow
    def test_every_coater_has_a_sorter_drawing_proliferator(self) -> None:
        from flab2bp.layout.spine import proliferator_item

        spec = self._prolif_spec()
        p = SpineLayout(power=False).lay_out(spec, time_budget_s=0.5)
        prolif = proliferator_item(spec)
        supply = {
            i
            for i, b in enumerate(p.buildings)
            if catalog.is_belt(b.item_id) and b.carries_item == prolif
        }
        fed = {
            b.output_obj
            for b in p.buildings
            if catalog.is_sorter(b.item_id) and b.input_obj in supply
        }
        coaters = [
            i for i, b in enumerate(p.buildings) if b.item_id == catalog.SPRAY_COATER_ID
        ]
        assert coaters, "expected coaters on a max-proliferation spec"
        starved = [i for i in coaters if i not in fed]
        assert not starved, f"{len(starved)} of {len(coaters)} coaters unfed"


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

    def test_a_mode_driven_group_lays_out_at_all(self) -> None:
        """Before this, emission raised: no DSP recipe id exists for the mode."""
        p = SpineLayout(power=False).lay_out(self._exchanger_spec(), time_budget_s=0.5)
        assert len(self._exchangers(p)) == 2

    def test_the_machine_carries_the_mode_not_a_recipe(self) -> None:
        from flab2bp.dsp import params

        p = SpineLayout(power=False).lay_out(self._exchanger_spec(), time_budget_s=0.5)
        for b in self._exchangers(p):
            assert b.recipe_id == 0, "a mode-driven machine must not claim a recipe id"
            assert b.parameters == params.parameters_for("accumulator-full")

    def test_the_two_poles_emit_different_blocks(self) -> None:
        """Charge and discharge are opposite words, not the same machine twice.

        A test that only checked ``parameters != ()`` would pass with both poles
        wired to the same value, which is exactly the failure that drains a
        factory instead of filling it.
        """
        charge = SpineLayout(power=False).lay_out(
            self._exchanger_spec("accumulator-full"), time_budget_s=0.5
        )
        discharge = SpineLayout(power=False).lay_out(
            self._exchanger_spec("accumulator-discharge"), time_budget_s=0.5
        )
        (c,) = {b.parameters for b in self._exchangers(charge)}
        (d,) = {b.parameters for b in self._exchangers(discharge)}
        assert c == (1,) and d == (-1,), f"charge={c} discharge={d}"

    def test_ordinary_recipes_still_carry_a_recipe_id(self) -> None:
        """The mode path must not swallow normal machines."""
        p = SpineLayout(power=False).lay_out(single_recipe_spec(), time_budget_s=0.5)
        smelters = [b for b in p.buildings if b.item_id == MACHINE_ITEM_IDS["arc-smelter"]]
        assert smelters
        assert all(b.recipe_id == catalog.recipe_id("iron-ingot") for b in smelters)
        assert all(b.parameters == () for b in smelters)

    def test_the_placement_validates(self) -> None:
        from flab2bp.pipeline import _id_map

        spec = self._exchanger_spec()
        p = SpineLayout(power=True).lay_out(spec, time_budget_s=0.5)
        report = validate.validate(p, spec, ids=_id_map(spec), expect_power=True)
        assert report.ok, "\n".join(f"{f.check}: {f.message}" for f in report.errors[:5])


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
        """The repro that shipped: every candidate of the example URL."""
        from flab2bp.lab.data import load_vendored
        from flab2bp.lab.url import parse_url
        from flab2bp.pipeline import _id_map
        from flab2bp.rates.candidates import build_candidates

        url = (
            "https://factoriolab.github.io/dsp/flow?o=super-magnetic-ring*60"
            "&ibe=conveyor-belt-2"
            "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11"
        )
        for spec in build_candidates(load_vendored(), parse_url(url), count=3).candidates:
            p = SpineLayout(power=False).lay_out(spec, time_budget_s=0.5)
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
