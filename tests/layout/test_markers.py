"""Strategy-independent labels for belts crossing the factory boundary."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

from flab2bp.dsp import catalog, codec
from flab2bp.layout import markers
from flab2bp.layout.base import AreaFrame, PlacedBuilding, Placement
from flab2bp.spec import BuildSpec, SelfLoopSeed


def _belt(
    x: int,
    y: int,
    *,
    item: str,
    output: int | None,
    input_obj: int | None = None,
    parameters: tuple[int, ...] = (),
) -> PlacedBuilding:
    item_id = min(catalog.BELT_IDS)
    return PlacedBuilding(
        item_id=item_id,
        model_index=catalog.building(item_id).model_index,
        x=x,
        y=y,
        z=Fraction(),
        output_obj=output,
        input_obj=input_obj,
        parameters=parameters,
        carries_item=item,
    )


def _sorter(*, source: int, destination: int, item: str) -> PlacedBuilding:
    item_id = min(catalog.SORTER_IDS)
    return PlacedBuilding(
        item_id=item_id,
        model_index=catalog.building(item_id).model_index,
        x=0,
        y=1,
        x2=0,
        y2=2,
        input_obj=source,
        output_obj=destination,
        carries_item=item,
    )


def _piler_output_placement() -> Placement:
    """Retained logical boundary regression; not a legal physical fixture."""

    def building(name: str, x: int, **kwargs) -> PlacedBuilding:
        item_id = catalog.item_id(name)
        return PlacedBuilding(
            item_id=item_id,
            model_index=catalog.building(item_id).model_index,
            x=x,
            y=0,
            **kwargs,
        )

    return Placement(
        buildings=(
            building("assembling-machine-1", 0, recipe_id=1),
            building("sorter-1", 1, input_obj=0, output_obj=2, carries_item="gear"),
            building("conveyor-belt-1", 2, output_obj=3, carries_item="gear"),
            building("automatic-piler", 3),
            building("conveyor-belt-1", 4, input_obj=3, carries_item="gear"),
        )
    )


def test_piler_transit_preserves_producer_boundary() -> None:
    placement = _piler_output_placement()
    assert markers.output_belt_tails(placement) == [4]
    assert 4 not in markers.input_belt_heads(placement)


def test_serial_pilers_preserve_shared_tail_and_external_input() -> None:
    buildings = list(_piler_output_placement().buildings)
    buildings[4] = replace(buildings[4], output_obj=5)
    buildings.extend(
        (
            replace(buildings[3], x=5),
            replace(buildings[4], x=6, input_obj=5, output_obj=None),
            replace(buildings[0], x=7),
            replace(buildings[1], x=8, input_obj=7, output_obj=9),
            replace(buildings[2], x=9, output_obj=2),
            _belt(10, 0, item="iron-ingot", output=None),
        )
    )
    placement = Placement(buildings=tuple(buildings))
    assert markers.output_belt_tails(placement) == [6]
    assert markers.input_belt_heads(placement) == [9, 10]


def test_marks_external_input_heads_and_output_tails_without_touching_other_belts() -> None:
    placement = Placement(
        buildings=(
            PlacedBuilding(item_id=0, model_index=0, x=0, y=0),
            _sorter(source=0, destination=2, item="gear"),
            _belt(0, 2, item="gear", output=3),
            _belt(1, 2, item="gear", output=None),
            _belt(0, 3, item="gear", output=5),
            _belt(1, 3, item="gear", output=None),
            _belt(0, 4, item="iron-ingot", output=7),
            _belt(1, 4, item="iron-ingot", output=None),
            _belt(
                0,
                5,
                item="magnetic-coil",
                output=None,
                parameters=(9999, 0),
            ),
        )
    )
    spec = BuildSpec(
        groups=(),
        external_inputs={"iron-ingot": Fraction(1)},
        outputs={"gear": Fraction(1)},
    )

    marked = markers.mark_external_belts(placement, spec)

    assert marked.buildings[6].parameters == catalog.belt_marker(catalog.item_id("iron-ingot"))
    assert marked.buildings[3].parameters == catalog.belt_marker(catalog.item_id("gear"))
    assert marked.buildings[2].parameters == ()
    assert marked.buildings[4].parameters == ()
    assert marked.buildings[5].parameters == ()
    assert marked.buildings[8] == placement.buildings[8]
    assert tuple(replace(b, parameters=()) for b in marked.buildings[:8]) == tuple(
        replace(b, parameters=()) for b in placement.buildings[:8]
    )
    assert marked.stats["input_markers"] == 1


def test_splitter_port_belts_are_not_encoded_as_external_endpoints() -> None:
    splitter = catalog.building(catalog.SPLITTER_ID)
    placement = Placement(
        buildings=(
            PlacedBuilding(
                item_id=catalog.SPLITTER_ID,
                model_index=splitter.model_index,
                x=2,
                y=2,
            ),
            # A branch originating at the Splitter has no belt predecessor.
            _belt(2, 2, item="iron-ingot", input_obj=0, output=None),
            # A one-tile run terminating at the Splitter has no belt predecessor either.
            _belt(2, 2, item="iron-ingot", output=0),
            _belt(0, 0, item="iron-ingot", output=None),
            PlacedBuilding(item_id=0, model_index=0, x=0, y=1),
            _sorter(source=4, destination=6, item="gear"),
            _belt(4, 1, item="gear", output=None),
            PlacedBuilding(item_id=0, model_index=0, x=0, y=2),
            _sorter(source=7, destination=9, item="gear"),
            # A producer-fed output run ending at the Splitter is not an exposed tail.
            _belt(2, 2, item="gear", output=0),
        ),
        frame=AreaFrame(10, 4, 4, (4,), False),
    )
    spec = BuildSpec(
        groups=(),
        external_inputs={"iron-ingot": Fraction(1)},
        outputs={"gear": Fraction(1)},
    )

    marked = markers.mark_external_belts(placement, spec)
    decoded = codec.decode(codec.encode(marked, timestamp=0))

    assert decoded.buildings[0].parameters == ()
    assert decoded.buildings[1].parameters == ()
    assert decoded.buildings[2].parameters == ()
    assert decoded.buildings[3].parameters == catalog.belt_marker(catalog.item_id("iron-ingot"))
    assert decoded.buildings[6].parameters == catalog.belt_marker(catalog.item_id("gear"))
    assert decoded.buildings[9].parameters == ()
    assert marked.stats.get("input_markers") == 1


def _machine(*, x: int, y: int, recipe_id: int) -> PlacedBuilding:
    return PlacedBuilding(item_id=0, model_index=0, x=x, y=y, recipe_id=recipe_id)


def _self_loop_placement() -> Placement:
    """A one-machine hydrogen loop: the machine's own output sorter feeds a
    belt run that returns via its own input sorter, head at (3, 21).

    Buildings 4-5 are a second, unrelated hydrogen sorter/belt pair feeding
    the SAME machine from an external belt this group never produced -- the
    same-item-different-run case ``spec.BuildSpec.planning_stack`` names
    (``universe-matrix``'s hydrogen, fed both externally and internally).
    It must NOT be picked as the loop head: proof that identification comes
    from the sorter graph, never from the item name alone.
    """
    x_ray_cracking = catalog.recipe_id("x-ray-cracking")
    return Placement(
        buildings=(
            _machine(x=0, y=0, recipe_id=x_ray_cracking),  # 0: the sole group machine
            _sorter(source=0, destination=2, item="hydrogen"),  # 1: group's OUTPUT sorter
            _belt(3, 21, item="hydrogen", output=3),  # 2: the loop head
            _sorter(source=2, destination=0, item="hydrogen"),  # 3: group's INPUT sorter
            _belt(10, 10, item="hydrogen", output=5, input_obj=None),  # 4: unrelated external head
            _sorter(source=4, destination=0, item="hydrogen"),  # 5: an external input sorter
        )
    )


def _self_loop_spec() -> BuildSpec:
    return BuildSpec(
        groups=(),
        self_loop_seeds=(
            SelfLoopSeed(
                item_id="hydrogen",
                recipe_id="x-ray-cracking",
                machine_item_id="chemical-plant",
                machines=4,
                consumed_per_craft=Fraction(2),
                produced_per_craft=Fraction(3),
                net_per_craft=Fraction(1),
                seed_items=8,
            ),
        ),
    )


def test_self_loop_lane_head_is_marked() -> None:
    """The tile the player drops the seed on carries the item's icon.

    `mark_external_belts` marked only heads whose item is in
    `spec.external_inputs`, and a self-loop item never is -- so the reporting
    URL's 107-tile hydrogen lane began at an unlabelled belt at (3,21) that
    looked exactly like a forgotten input.
    """
    placement = _self_loop_placement()  # hydrogen loop, head at (3, 21)
    spec = _self_loop_spec()
    heads = markers.self_loop_prime_heads(placement, spec)
    assert set(heads) == {"hydrogen"}
    head = placement.buildings[heads["hydrogen"]]
    assert (head.x, head.y) == (3, 21)

    marked = markers.mark_external_belts(placement, spec)
    assert marked.buildings[heads["hydrogen"]].parameters == catalog.belt_marker(
        catalog.item_id("hydrogen")
    )
    assert marked.stats["self_loop_prime_markers"] == 1
    # The unrelated external run feeding the same machine (buildings 4-5) is
    # untouched -- graph position picked the loop, not the item name.
    assert marked.buildings[4].parameters == ()


def _self_loop_placement_series_tap() -> Placement:
    """Two machines fed IN SERIES off one shared belt, head at (3, 21).

    The real corpus shape design section 1.2 decodes: one run collects from
    every machine's own output sorter and feeds every machine's own input
    sorter in series, each input sorter TAPPING an interior tile of the run
    (its ``input_obj`` names a belt mid-run, buildings 7 and 8 below) while
    the run's own forward chain carries on past both taps to an open surplus
    tail (building 6's ``output_obj`` is ``None``) -- it never terminates AT
    a sorter the way the single-machine fixture above does.  Measured against
    the real ``reforming-refine`` corpus (20 machines): every one of its input
    sorters taps an interior tile this way, so a walk that only recognised a
    terminal ``output_obj`` landing on a sorter returned no head for it at
    all.
    """
    x_ray_cracking = catalog.recipe_id("x-ray-cracking")
    return Placement(
        buildings=(
            _machine(x=0, y=0, recipe_id=x_ray_cracking),  # 0
            _machine(x=0, y=5, recipe_id=x_ray_cracking),  # 1
            _sorter(source=0, destination=3, item="hydrogen"),  # 2: OUTPUT sorter
            _belt(3, 21, item="hydrogen", output=4),  # 3: the loop head
            _belt(3, 22, item="hydrogen", output=5),  # 4: tapped by sorter 7
            _belt(3, 23, item="hydrogen", output=6),  # 5: tapped by sorter 8
            _belt(3, 24, item="hydrogen", output=None),  # 6: open surplus tail
            _sorter(source=4, destination=0, item="hydrogen"),  # 7: INPUT sorter, taps 4
            _sorter(source=5, destination=1, item="hydrogen"),  # 8: INPUT sorter, taps 5
        )
    )


def test_self_loop_lane_head_is_found_for_a_multi_machine_series_tap() -> None:
    """An interior tap closes the loop exactly as a terminal one does.

    Without this, no multi-machine self-loop group -- the shape the design's
    own real corpus example decodes -- could ever be identified: only a
    single-machine loop whose run happens to terminate right at the sorter
    would be found.
    """
    placement = _self_loop_placement_series_tap()
    spec = _self_loop_spec()
    heads = markers.self_loop_prime_heads(placement, spec)
    assert set(heads) == {"hydrogen"}
    head = placement.buildings[heads["hydrogen"]]
    assert (head.x, head.y) == (3, 21)
