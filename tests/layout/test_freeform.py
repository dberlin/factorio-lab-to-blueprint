"""Tests for Strategy B -- free-form packing + belt routing.

The specs here are hand-built rather than taken from ``rates/``: this suite must
be able to fail for layout reasons alone, and a dependency on the rate solver
would let a rates regression masquerade as a layout one.
"""

from __future__ import annotations

import dataclasses
import itertools
import math
import random
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import replace
from fractions import Fraction as F
from pathlib import Path

import pytest
from ortools.sat.python import cp_model

from flab2bp.dsp import catalog, codec, colliders, planet, rules, splitter_ports
from flab2bp.layout import finalize, freeform, junction, slots, validate
from flab2bp.layout.band_policy import BandPolicy, BandSelection
from flab2bp.layout.base import (
    DETERMINISTIC_WORKERS,
    AreaFrame,
    Facing,
    NoValidLayout,
    PlacedBuilding,
    Placement,
    PlacementCompletion,
)
from flab2bp.layout.finalize import ProjectionNoGood
from flab2bp.layout.freeform import (
    _BLAME_MAX_WALL,
    _ENTRY_RING,
    _LEVEL_TOLL,
    _ROUTE_RING,
    _TENTATIVE,
    LEVELS,
    MU_DIRECT,
    CoaterSupplyPort,
    DirectInsertId,
    FreeformLayout,
    Strip,
    _astar,
    _box,
    _bridge,
    _build,
    _build_prepared,
    _BuildResult,
    _Canvas,
    _canvas_span,
    _commit_paths,
    _connect_short_cuts,
    _dests,
    _direct_column_deltas,
    _direct_net_candidates,
    _emit_strip,
    _greedy_pack,
    _Grid,
    _height_seed,
    _join_shard_islands,
    _machines_without_poses,
    _make_grid,
    _merge_lanes,
    _Net,
    _nets_between,
    _pack,
    _pair_lanes,
    _PathSearchResult,
    _Port,
    _power_plan,
    _prepare_routing_problem,
    _proliferator_nets,
    _relink,
    _reserve_port_access,
    _room_for_another,
    _route_all,
    _route_external_inputs,
    _routing_flags,
    _shard_sinks,
    _sink_for,
    _source_for,
    _Unpowerable,
    fallback_placement,
    plan_strips,
    tie_break_cap,
)
from flab2bp.layout.route_feedback import (
    Cell,
    DetailedRouteResult,
    DetailedRouteStatus,
    FeedbackState,
    NetFailure,
    NetId,
    NetRole,
    RouteFailureKind,
)
from flab2bp.layout.strip_variants import (
    CargoDomain,
    ProjectionPitchRequirement,
    StripInstance,
    StripPoseId,
    StripVariant,
    default_strip_variant,
    generate_strip_families,
    partition_strip_family,
    projection_pitch_requirement,
    strip_pose_id,
)
from flab2bp.spec import BuildSpec, MachineGroup, ProliferatorMode

type SpecFactory = Callable[[], BuildSpec]


def _identity_finalizer(
    placement: Placement,
    _policy: BandPolicy,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> Placement:
    del cancelled
    return placement

_LEGACY_BAND_BY_SPEC_LABEL: Mapping[str, BandSelection] = {
    "single": "portable",
    "two-stage": "portable",
    "magnetic-ring": "160",
    "proliferated": "portable",
}


def group(
    recipe: str,
    machine: str,
    count: int,
    inputs: dict[str, F] | None = None,
    outputs: dict[str, F] | None = None,
    *,
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


def test_junction_clearance_uses_building_centre_at_exact_boundary() -> None:
    item_id = catalog.item_id("assembling-machine-2")
    machine = PlacedBuilding(
        item_id=item_id,
        model_index=catalog.building(item_id).model_index,
        x=0,
        y=0,
        width=3,
        height=3,
    )

    assert not junction.site_is_clear([machine], 3, 1)
    assert junction.site_is_clear([machine], 4, 1)


def single_recipe_spec() -> BuildSpec:
    return BuildSpec(
        groups=(group("iron-ingot", "arc-smelter", 4, {"iron-ore": F(1)}, {"iron-ingot": F(1)}),),
        external_inputs={"iron-ore": F(4)},
        outputs={"iron-ingot": F(4)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="single",
    )


def two_stage_spec() -> BuildSpec:
    """One producer, one consumer, RATE-BALANCED and of equal width.

    Four gear assemblers, not two.  Four smelters make 4 iron-ingot/s, so two
    assemblers left 2/s with nowhere to go: every flow check on this spec then
    failed for arithmetic reasons and said nothing about the geometry.

    Equal machine counts also make it the fixture the direct-insert tests want.
    Direct insertion needs the consumer stacked under the producer, and for two
    boxes of width ``a`` and ``b`` at equal height ``h``, side-by-side costs
    ``(a+b)*h`` while stacked costs ``max(a,b)*2h`` -- identical when ``a == b``
    and strictly worse for stacking when they differ.  At 4 and 2 machines the
    widths were 12 and 6, so side-by-side won on area alone and the tie-break
    never got a say; the separate ``balanced_pair_spec`` that existed to dodge
    that is gone, because balancing the rates fixed the widths too.
    """
    return BuildSpec(
        groups=(
            group("iron-ingot", "arc-smelter", 4, {"iron-ore": F(1)}, {"iron-ingot": F(1)}),
            group("gear", "assembling-machine-2", 4, {"iron-ingot": F(1)}, {"gear": F(1)}),
        ),
        external_inputs={"iron-ore": F(4)},
        outputs={"gear": F(4)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="two-stage",
    )


def plastic_spec() -> BuildSpec:
    """The captured corpus ``plastic/all-products`` candidate."""
    from flab2bp.bench.corpus import URL_CORPUS
    from flab2bp.lab.data import load_vendored
    from flab2bp.lab.url import parse_url
    from flab2bp.rates.candidates import DEFAULT_CANDIDATE_POLICIES, build_candidates

    entry = next(candidate for candidate in URL_CORPUS if candidate.url_id == "plastic")
    return next(
        candidate
        for candidate in build_candidates(
            load_vendored(),
            parse_url(entry.url),
            candidate_policies=DEFAULT_CANDIDATE_POLICIES,
        ).candidates
        if candidate.label == "all-products"
    )

def captured_output_products_spec() -> BuildSpec:
    """The reported 17-strip casimir-crystal/output-products refusal."""
    from flab2bp.bench.corpus import URL_CORPUS
    from flab2bp.lab.data import load_vendored
    from flab2bp.lab.url import parse_url
    from flab2bp.rates.candidates import CandidatePolicy, build_candidates

    entry = next(
        candidate for candidate in URL_CORPUS if candidate.url_id == "casimir-crystal"
    )
    return build_candidates(
        load_vendored(),
        parse_url(entry.url),
        candidate_policies=(CandidatePolicy.OUTPUT_PRODUCTS,),
    ).candidates[0]


def test_prepared_problem_creates_fresh_workspaces() -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec, strip_len=6)
    pack = _greedy_pack(strips, _height_seed(strips))
    prepared = _prepare_routing_problem(
        spec,
        strips,
        pack,
        policy=BandPolicy("portable"),
        power=False
    )

    first = prepared.new_workspace()
    second = prepared.new_workspace()
    second_item = second.nets[0].item

    first.canvas.blocked[(999, 999, 0)] = -1
    first.canvas.reserved[(999, 999, 0)] = (999, 999, 0)
    first.canvas.guard.add((999, 999, 1))
    first.nets[0].item = "mutated-only-in-first"

    assert (999, 999, 0) not in second.canvas.blocked
    assert (999, 999, 0) not in second.canvas.reserved
    assert second.canvas.guard == set(prepared.guard)
    assert (999, 999, 1) not in second.canvas.guard
    assert second.nets[0].item == second_item
    assert first.buildings is not second.buildings
    assert first.nets[0] is not second.nets[0]


def test_prepared_net_ids_are_stable() -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec, strip_len=6)
    pack = _greedy_pack(strips, _height_seed(strips))
    a = _prepare_routing_problem(
        spec,
        strips,
        pack,
        policy=BandPolicy("portable"),
        power=False
    )
    b = _prepare_routing_problem(
        spec,
        strips,
        pack,
        policy=BandPolicy("portable"),
        power=False
    )

    assert tuple(net.net_id for net in a.nets) == tuple(net.net_id for net in b.nets)


def test_prepared_static_access_failure_spends_no_route_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec, strip_len=6)
    pack = _greedy_pack(strips, _height_seed(strips))
    prepared = _prepare_routing_problem(
        spec,
        strips,
        pack,
        policy=BandPolicy("portable"),
        power=False
    )
    net_id = prepared.nets[0].net_id
    failed = replace(
        prepared,
        preparation_failures=(
            NetFailure(
                net_id,
                RouteFailureKind.STATIC_ACCESS,
                ((prepared.nets[0].dst.x, prepared.nets[0].dst.y, 0),),
                (),
                0,
            ),
        ),
    )
    monkeypatch.setattr(
        freeform,
        "_route_all",
        lambda *args, **kwargs: pytest.fail("static impossibility reached routing"),
    )

    result = _build_prepared(
        spec,
        strips,
        failed,
        power=False,
        route=True,
        budget={"left": 10_000},
    )

    assert result.routing.status is DetailedRouteStatus.STRANDED
    assert result.routing.failures == failed.preparation_failures
    assert result.routing.expansions == 0

def test_prepared_budget_result_stops_before_every_emission_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec, strip_len=6)
    pack = _greedy_pack(strips, _height_seed(strips))
    prepared = _prepare_routing_problem(
        spec,
        strips,
        pack,
        policy=BandPolicy("portable"),
        power=True,
    )
    internal_net = next(
        net
        for net in prepared.nets
        if net.net_id is not None and net.net_id.role is not NetRole.EXTERNAL
    )
    assert internal_net.net_id is not None
    evidence = DetailedRouteResult(
        status=DetailedRouteStatus.BUDGET,
        routed=(),
        failures=(
            NetFailure(
                internal_net.net_id,
                RouteFailureKind.BUDGET,
                (),
                (),
                7,
            ),
        ),
        iterations=2,
        expansions=7,
    )
    empty = DetailedRouteResult(DetailedRouteStatus.ROUTED, (), (), 0, 0)

    monkeypatch.setattr(
        freeform,
        "_route_external_inputs",
        lambda *_args, **_kwargs: empty,
    )
    monkeypatch.setattr(
        freeform,
        "_route_all",
        lambda *_args, **_kwargs: evidence,
    )
    monkeypatch.setattr(
        freeform,
        "_place_power",
        lambda *_args, **_kwargs: pytest.fail(
            "a budgeted build reached power placement"
        ),
    )
    monkeypatch.setattr(
        freeform,
        "assign_sorter_slots",
        lambda *_args, **_kwargs: pytest.fail(
            "a budgeted build reached sorter-slot emission"
        ),
    )
    monkeypatch.setattr(
        freeform,
        "Placement",
        lambda *_args, **_kwargs: pytest.fail(
            "a budgeted build reached Placement construction"
        ),
    )

    result = _build_prepared(
        spec,
        strips,
        prepared,
        power=True,
        route=True,
        budget={"left": 100},
    )

    assert result.routing == evidence
    assert result.placement is None
    assert result.towers == ()


def fractionator_spec(*, machine_count: int = 2) -> BuildSpec:
    return BuildSpec(
        groups=(
            group(
                "deuterium-fractionation",
                "fractionator",
                machine_count,
                {"hydrogen": F(1)},
                {"deuterium": F(1)},
            ),
        ),
        external_inputs={"hydrogen": F(machine_count)},
        outputs={"deuterium": F(machine_count)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="fractionator",
    )


def test_belt_port_input_lane_fans_out_through_exact_machine_ports() -> None:
    spec = fractionator_spec()
    (strip,) = plan_strips(spec)
    canvas = _Canvas()
    belt_id = catalog.item_id(spec.belt_item_id)

    inputs, _outputs, _connections = _emit_strip(
        canvas,
        strip,
        0,
        0,
        belt_id,
        catalog.building(belt_id).model_index,
        {},
    )
    wired = slots.assign_sorter_slots(canvas.buildings)
    machine_indices = tuple(
        index for index, building in enumerate(wired) if building.item_id == strip.item_id
    )

    assert strip.physical_variant is None
    assert strip.attachment_plan == ()
    assert tuple(inputs) == ("hydrogen",)
    assert not [building for building in wired if catalog.is_sorter(building.item_id)]
    assert _connections == 0
    assert sum(building.item_id == catalog.SPLITTER_ID for building in wired) == 1
    for machine_index in machine_indices:
        machine = wired[machine_index]
        docks = slots.port_docks(machine)
        feeder = next(
            building
            for building in wired
            if catalog.is_belt(building.item_id)
            and building.output_obj == machine_index
            and building.carries_item == "hydrogen"
        )
        product = next(
            building
            for building in wired
            if catalog.is_belt(building.item_id)
            and building.input_obj == machine_index
            and building.carries_item == "deuterium"
        )

        assert (feeder.x, feeder.y) == docks[1].cell
        assert feeder.yaw == docks[1].facing.opposite().value
        assert feeder.output_to_slot == 1
        assert feeder.output_from_slot == rules.BELT_PORT_FEED_FROM_SLOT
        assert (product.x, product.y) == docks[0].cell
        assert product.yaw == docks[0].facing.value
        assert product.input_from_slot == 0
        assert product.input_to_slot == rules.BELT_PORT_DRAW_TO_SLOT

    report = validate.validate(Placement(tuple(wired)), expect_power=False)
    assert not report.by_check("belt.port_dock")
    assert not report.by_check("junction.colocated")
    assert not report.by_check("game.slot_occupancy")


def test_belt_port_input_supply_rejects_a_wrong_item_dock() -> None:
    spec = fractionator_spec()
    (strip,) = plan_strips(spec)
    canvas = _Canvas()
    belt_id = catalog.item_id(spec.belt_item_id)
    _emit_strip(
        canvas,
        strip,
        0,
        0,
        belt_id,
        catalog.building(belt_id).model_index,
        {},
    )
    wired = list(slots.assign_sorter_slots(canvas.buildings))
    feeder_index = next(
        index
        for index, building in enumerate(wired)
        if catalog.is_belt(building.item_id)
        and building.output_obj is not None
        and wired[building.output_obj].item_id == strip.item_id
        and building.carries_item == "hydrogen"
    )
    machine_index = wired[feeder_index].output_obj
    assert machine_index is not None
    wired[feeder_index] = replace(wired[feeder_index], carries_item="deuterium")

    report = validate.validate(
        Placement(tuple(wired)),
        spec,
        ids=_id_map_for(spec),
        expect_power=False,
    )

    assert [
        finding.buildings
        for finding in report.by_check("machine.inputs_supplied")
    ] == [(machine_index,)]


def test_belt_port_input_strip_is_not_refused_as_poseless() -> None:
    (strip,) = plan_strips(fractionator_spec())

    assert _machines_without_poses([strip]) == []


def test_belt_port_input_emission_refuses_an_unfilterable_shared_lane() -> None:
    spec = fractionator_spec()
    (strip,) = plan_strips(spec)
    strip = replace(strip, in_above=(("hydrogen", "deuterium"),))
    belt_id = catalog.item_id(spec.belt_item_id)

    with pytest.raises(NoValidLayout, match="cannot filter shared belt-port input lane"):
        _emit_strip(
            _Canvas(),
            strip,
            0,
            0,
            belt_id,
            catalog.building(belt_id).model_index,
            {},
        )


def test_freeform_fractionator_path_emits_projection_valid_port_fanout() -> None:
    spec = fractionator_spec()

    placement = FreeformLayout(
        band_policy=BandPolicy("portable"),
        workers=1,
    ).lay_out(spec, time_budget_s=4.0)

    report = validate.certify(placement, spec, expect_power=True)
    assert report.ok, "\n".join(
        f"{finding.check}: {finding.message}" for finding in report.errors
    )
    assert not [
        building for building in placement.buildings if catalog.is_sorter(building.item_id)
    ]


def test_sequence_pair_fractionator_path_emits_projection_valid_port_fanout() -> None:
    from flab2bp.layout.sequence_solver import SequencePairLayout

    spec = fractionator_spec()
    placement = SequencePairLayout(
        band_policy=BandPolicy("portable"),
    ).lay_out(spec, time_budget_s=4.0)

    report = validate.certify(placement, spec, expect_power=True)
    assert report.ok, "\n".join(
        f"{finding.check}: {finding.message}" for finding in report.errors
    )
    assert not [
        building for building in placement.buildings if catalog.is_sorter(building.item_id)
    ]


def test_strip_emission_reproduces_every_precomputed_attachment() -> None:
    spec = two_stage_spec()
    strip = next(strip for strip in plan_strips(spec) if strip.recipe_id == "gear")
    canvas = _Canvas()
    belt_id = catalog.item_id(spec.belt_item_id)
    ox, oy = 11, 7

    _inputs, _outputs, sorter_count = _emit_strip(
        canvas,
        strip,
        ox,
        oy,
        belt_id,
        catalog.building(belt_id).model_index,
        {},
    )
    wired = slots.assign_sorter_slots(canvas.buildings)

    expected = []
    machine_y = oy + strip.machine_row
    for machine_x in (ox + index * strip.pw for index in range(strip.machines)):
        for plan in strip.attachment_plan:
            for attachment in plan.attachments:
                lane_cell = (
                    machine_x + attachment.column,
                    machine_y + plan.lane_y,
                )
                machine_cell = (
                    machine_x + attachment.cell[0],
                    machine_y + attachment.cell[1],
                )
                if plan.lane.kind == "input":
                    expected.append(
                        (lane_cell, machine_cell, attachment.span, attachment.slot, "input")
                    )
                else:
                    expected.append(
                        (machine_cell, lane_cell, attachment.span, attachment.slot, "output")
                    )

    actual = []
    for sorter in (building for building in wired if catalog.is_sorter(building.item_id)):
        assert sorter.x2 is not None and sorter.y2 is not None
        head = (sorter.x, sorter.y)
        tail = (sorter.x2, sorter.y2)
        span = max(abs(sorter.x - sorter.x2), abs(sorter.y - sorter.y2))
        if (
            sorter.output_obj is not None
            and wired[sorter.output_obj].item_id == strip.item_id
        ):
            actual.append((head, tail, span, sorter.output_to_slot, "input"))
        else:
            assert (
                sorter.input_obj is not None
                and wired[sorter.input_obj].item_id == strip.item_id
            )
            actual.append((head, tail, span, sorter.input_from_slot, "output"))

    assert sorter_count == len(expected)
    assert sorted(actual) == sorted(expected)


def multi_lane_assembler_spec() -> BuildSpec:
    return BuildSpec(
        groups=(
            group(
                "gear",
                "assembling-machine-2",
                1,
                {"iron-ingot": F(1), "copper-ingot": F(1)},
                {"gear": F(1), "magnet": F(1)},
            ),
        ),
        external_inputs={"iron-ingot": F(1), "copper-ingot": F(1)},
        outputs={"gear": F(1), "magnet": F(1)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="multi-lane-assembler",
    )


def test_multi_lane_assembler_emission_uses_one_slot_per_sorter() -> None:
    spec = multi_lane_assembler_spec()
    strip = plan_strips(spec)[0]
    canvas = _Canvas()
    belt_id = catalog.item_id(spec.belt_item_id)

    _inputs, _outputs, sorter_count = _emit_strip(
        canvas,
        strip,
        0,
        0,
        belt_id,
        catalog.building(belt_id).model_index,
        {},
    )
    wired = slots.assign_sorter_slots(canvas.buildings)
    machine_index = next(
        index for index, building in enumerate(wired) if building.item_id == strip.item_id
    )
    machine_slots = tuple(
        sorter.output_to_slot if sorter.output_obj == machine_index else sorter.input_from_slot
        for sorter in wired
        if catalog.is_sorter(sorter.item_id)
        and (sorter.input_obj == machine_index or sorter.output_obj == machine_index)
    )

    assert sorter_count == 4
    assert machine_slots == (8, 7, 0, 1)
    assert len(set(machine_slots)) == len(machine_slots)


def multi_output_chemical_spec() -> BuildSpec:
    return BuildSpec(
        groups=(
            group(
                "graphene-advanced",
                "chemical-plant",
                1,
                {"fire-ice": F(2)},
                {"graphene": F(2), "hydrogen": F(1)},
            ),
        ),
        external_inputs={"fire-ice": F(2)},
        outputs={"graphene": F(2), "hydrogen": F(1)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="multi-output-chemical",
    )

def test_surplus_reuses_a_consumer_lane_when_the_combined_rate_fits() -> None:
    spec = BuildSpec(
        groups=(
            group(
                "plasma-refining",
                "oil-refinery",
                1,
                {"crude-oil": F(2)},
                {"refined-oil": F(2), "hydrogen": F(1)},
            ),
            group(
                "plastic",
                "chemical-plant",
                1,
                {"refined-oil": F(1)},
                {"plastic": F(1)},
            ),
        ),
        external_inputs={"crude-oil": F(2)},
        outputs={"plastic": F(1), "hydrogen": F(1)},
        surplus_outputs={"refined-oil": F(1)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
    )

    producer = next(
        strip for strip in plan_strips(spec) if strip.recipe_id == "plasma-refining"
    )
    lanes = [
        destination
        for item, destination, _cargo_domain in producer.out_lanes
        if item == "refined-oil"
    ]
    assert len(lanes) == 1
    assert "" in _dests(lanes[0])
    assert any(destination for destination in _dests(lanes[0]))
    assert (
        freeform._sink_demand(
            freeform._adapt(spec),
            spec,
            "refined-oil",
            lanes[0],
        )
        == 2
    )


def test_self_consuming_product_keeps_internal_and_boundary_output_lanes(
    refined_oil_feedback_spec: BuildSpec,
) -> None:
    (family,) = generate_strip_families(refined_oil_feedback_spec)
    lanes = {
        (lane.items[0], lane.destination_group_keys, lane.cargo_domain)
        for lane in family.output_lanes
    }
    assert ("refined-oil", (family.group_key,), CargoDomain.UNSPRAYED) in lanes
    assert ("refined-oil", (), CargoDomain.UNSPRAYED) in lanes


def test_packer_proxy_does_not_separate_a_strip_from_itself(
    refined_oil_feedback_spec: BuildSpec,
) -> None:
    strips = plan_strips(
        refined_oil_feedback_spec,
        strip_len=refined_oil_feedback_spec.machine_count,
    )
    assert all(left != right for left, right in _nets_between(strips))


def test_self_consuming_refined_oil_feedback_routes_and_validates(
    refined_oil_feedback_spec: BuildSpec,
) -> None:
    strips = plan_strips(
        refined_oil_feedback_spec,
        strip_len=refined_oil_feedback_spec.machine_count,
    )
    height = max(_box(strip)[1] for strip in strips)
    pack = _greedy_pack(strips, height)
    prepared = _prepare_routing_problem(
        refined_oil_feedback_spec,
        strips,
        pack,
        policy=BandPolicy("portable"),
        power=False,
    )

    feedback = [
        net
        for net in prepared.nets
        if net.item == "refined-oil"
        and net.src is not None
        and net.net_id.role is not NetRole.EXTERNAL
    ]
    assert feedback

    result = _build_prepared(
        refined_oil_feedback_spec,
        strips,
        prepared,
        power=False,
        route=True,
        budget={"left": 5_000_000},
    )
    assert result.routing.status is DetailedRouteStatus.ROUTED
    placement = result.placement
    assert placement is not None
    report = validate.certify(
        placement,
        refined_oil_feedback_spec,
        expect_power=False,
    )
    assert not [finding for finding in report.errors if finding.check == "flow.lane_sourced"]
    assert report.ok


def test_freeform_layout_rejects_removed_power_option() -> None:
    constructor: Callable[..., FreeformLayout] = FreeformLayout

    with pytest.raises(TypeError, match="unexpected keyword argument 'power'"):
        constructor(band_policy=BandPolicy("portable"), power=False)


@pytest.mark.slow
def test_freeform_routes_self_consuming_pinned_flow(
    refined_oil_feedback_spec: BuildSpec,
) -> None:
    placement = FreeformLayout(
        band_policy=BandPolicy("portable"),
        workers=1,
    ).lay_out(
        refined_oil_feedback_spec,
        time_budget_s=15.0,
    )
    assert validate.certify(
        placement,
        refined_oil_feedback_spec,
        expect_power=True,
    ).ok


def test_shared_strip_emission_filters_each_multi_output_lane() -> None:
    spec = multi_output_chemical_spec()
    strip = plan_strips(spec)[0]
    canvas = _Canvas()
    belt_id = catalog.item_id(spec.belt_item_id)

    _emit_strip(
        canvas,
        strip,
        0,
        0,
        belt_id,
        catalog.building(belt_id).model_index,
        {},
    )
    wired = slots.assign_sorter_slots(canvas.buildings)
    machine_index = next(
        index for index, building in enumerate(wired) if building.item_id == strip.item_id
    )
    output_sorters = {
        sorter.carries_item: sorter.filter_id
        for sorter in wired
        if catalog.is_sorter(sorter.item_id) and sorter.input_obj == machine_index
    }

    assert output_sorters == {
        "graphene": catalog.item_id("graphene"),
        "hydrogen": catalog.item_id("hydrogen"),
    }
    assert all(
        sorter.filter_id == 0
        for sorter in wired
        if catalog.is_sorter(sorter.item_id) and sorter.output_obj == machine_index
    )


def test_an_unmatched_variant_has_a_structured_unique_slot_refusal() -> None:
    strip = replace(
        plan_strips(multi_lane_assembler_spec())[0],
        lane_plan=None,
        attachment_plan=(),
    )

    assert _machines_without_poses([strip]) == [
        "Assembling Machine Mk.II (gear): its ingredient and output lanes cannot "
        "be assigned distinct legal sorter slots across all lanes; a machine slot "
        "holds one connection"
    ]


def test_input_lane_emission_uses_precomputed_attachment_span() -> None:
    spec = two_stage_spec()
    strip = next(strip for strip in plan_strips(spec) if strip.recipe_id == "gear")
    input_attachments = tuple(
        attachment
        for plan in strip.attachment_plan
        if plan.lane.kind == "input"
        for attachment in plan.attachments
    )
    assert input_attachments
    canvas = _Canvas()
    belt_id = catalog.item_id(spec.belt_item_id)

    _inputs, _outputs, sorter_count = _emit_strip(
        canvas,
        strip,
        0,
        0,
        belt_id,
        catalog.building(belt_id).model_index,
        {},
    )

    assert sorter_count == strip.machines * len(strip.attachment_plan)
    assert {
        max(abs(sorter.x - sorter.x2), abs(sorter.y - sorter.y2))
        for sorter in canvas.buildings
        if catalog.is_sorter(sorter.item_id)
        and sorter.output_obj is not None
        and canvas.buildings[sorter.output_obj].item_id == strip.item_id
        and sorter.x2 is not None
        and sorter.y2 is not None
    } == {attachment.span for attachment in input_attachments}


def test_strip_emission_refuses_an_attachment_that_no_longer_reproduces() -> None:
    spec = two_stage_spec()
    strip = next(strip for strip in plan_strips(spec) if strip.recipe_id == "gear")
    plan = strip.attachment_plan[0]
    bad_attachment = replace(plan.attachments[0], slot=plan.attachments[0].slot + 100)
    bad_plan = replace(
        plan,
        attachments=(bad_attachment, *plan.attachments[1:]),
    )
    bad_strip = replace(
        strip,
        attachment_plan=(bad_plan, *strip.attachment_plan[1:]),
    )
    belt_id = catalog.item_id(spec.belt_item_id)

    with pytest.raises(NoValidLayout, match="precomputed attachment"):
        _emit_strip(
            _Canvas(),
            bad_strip,
            0,
            0,
            belt_id,
            catalog.building(belt_id).model_index,
            {},
        )


def test_prepared_net_ids_preserve_routing_roles() -> None:
    spec = proliferated_spec()
    strips = plan_strips(spec, strip_len=6)
    pack = _greedy_pack(strips, _height_seed(strips))
    prepared = _prepare_routing_problem(
        spec,
        strips,
        pack,
        policy=BandPolicy("portable"),
        power=False
    )

    roles = {net.net_id.role for net in prepared.nets}
    assert NetRole.EXTERNAL in roles
    assert NetRole.PROLIFERATOR in roles


def test_prepared_proliferator_ports_round_trip_elevated_level() -> None:
    spec = proliferated_spec()
    strips = plan_strips(spec, strip_len=6)
    pack = _greedy_pack(strips, _height_seed(strips))
    prepared = _prepare_routing_problem(
        spec,
        strips,
        pack,
        policy=BandPolicy("portable"),
        power=False
    )

    proliferator_nets = [
        net for net in prepared.nets if net.net_id.role is NetRole.PROLIFERATOR
    ]
    assert proliferator_nets
    assert {net.dst.z for net in proliferator_nets} == {1}
    assert prepared.coater_supply_ports
    assert len(prepared.coater_supply_ports) == prepared.coaters
    for port in prepared.coater_supply_ports:
        host = prepared.building_templates[port.host_belt]
        supply = prepared.building_templates[port.supply_belt]
        assert port.item in spec.spray_lanes
        assert (host.x, host.y, host.z) == (
            port.host_x,
            port.host_y,
            F(port.host_z),
        )
        assert (supply.x, supply.y, supply.z) == (port.x, port.y, F(port.z))
        assert supply.carries_item in spec.external_inputs
        assert port.z == port.host_z + 1
    workspace = prepared.new_workspace()
    assert {
        net.dst.z
        for net in workspace.nets
        if net.net_id is not None and net.net_id.role is NetRole.PROLIFERATOR
    } == {1}


def test_slope_limited_prepared_coater_routing_is_structured() -> None:
    spec = proliferated_spec()
    strips = plan_strips(spec, strip_len=6)
    pack = _greedy_pack(strips, _height_seed(strips))
    prepared = _prepare_routing_problem(
        spec,
        strips,
        pack,
        policy=BandPolicy("portable"),
        power=False,
        ramped=True,
    )
    result = _build_prepared(
        spec,
        strips,
        prepared,
        power=False,
        route=True,
        budget={"left": 2_000_000},
    )

    assert prepared.ramped
    assert result.routing.status in {
        DetailedRouteStatus.ROUTED,
        DetailedRouteStatus.STRANDED,
        DetailedRouteStatus.BUDGET,
    }
    if result.routing.status is DetailedRouteStatus.ROUTED:
        placement = result.placement
        assert placement is not None
        assert not validate.certify(
            placement, spec, expect_power=False
        ).errors
    else:
        assert result.routing.failures



def test_detailed_route_terminates_at_elevated_port() -> None:
    canvas = _Canvas(limit=(0, -2, 6, 2))
    source_index = canvas.add(
        PlacedBuilding(2001, 35, 0, 0, carries_item="ore"),
        level=0,
    )
    destination_index = canvas.add(
        PlacedBuilding(2001, 35, 6, 0, z=F(1), carries_item="ore"),
        level=1,
    )
    net_id = NetId(0, 1, "ore", NetRole.PROLIFERATOR, 0)
    net = _Net(
        src=_Port(source_index, 0, 0, 0, 0, z=0),
        dst=_Port(destination_index, 6, 0, 6, 6, z=1),
        item="ore",
        net_id=net_id,
    )

    result = _route_all(
        canvas,
        [net],
        2001,
        35,
        (0, -2, 6, 2),
        budget={"left": 20_000},
    )
    assert result.status is DetailedRouteStatus.ROUTED
    assert result.routed == (net_id,)
    assert any(building.z > 0 for building in canvas.buildings[2:])


def test_commit_link_rejection_reroutes_the_same_net_before_emission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canvas = _Canvas(limit=(0, -2, 6, 2))
    source_index = canvas.add(
        PlacedBuilding(2001, 35, 0, 0, carries_item="ore"),
        level=0,
    )
    destination_index = canvas.add(
        PlacedBuilding(2001, 35, 6, 0, carries_item="ore"),
        level=0,
    )
    net_id = NetId(0, 1, "ore", NetRole.INTERNAL, 0)
    net = _Net(
        src=_Port(source_index, 0, 0, 0, 0),
        dst=_Port(destination_index, 6, 0, 6, 6),
        item="ore",
        net_id=net_id,
    )
    original = freeform._commit_paths
    attempts: list[tuple[tuple[int, int, int], ...]] = []

    def reject_first(
        attempt_canvas: _Canvas,
        attempt_nets: list[_Net],
        paths: Mapping[int, Sequence[Cell]],
        belt_id: int,
        belt_model: int,
        src_group: Mapping[int, tuple[int, ...]] | None = None,
        dst_group: Mapping[int, tuple[int, ...]] | None = None,
        *,
        source_hints: Mapping[int, Cell] | None = None,
        sink_hints: Mapping[int, Cell] | None = None,
        failure_details: dict[int, freeform._CommitFailure] | None = None,
    ) -> tuple[int, ...]:
        attempts.append(tuple(paths[0]))
        if len(attempts) == 1:
            if failure_details is not None:
                failure_details[0] = freeform._CommitFailure(
                    cell=paths[0][0],
                    side="source",
                    blocking_indices=(),
                )
            return (0,)
        return original(
            attempt_canvas,
            attempt_nets,
            paths,
            belt_id,
            belt_model,
            src_group,
            dst_group,
            source_hints=source_hints,
            sink_hints=sink_hints,
            failure_details=failure_details,
        )

    monkeypatch.setattr(freeform, "_commit_paths", reject_first)
    result = _route_all(
        canvas,
        [net],
        2001,
        35,
        (0, -2, 6, 2),
        budget={"left": 50_000},
    )

    assert result.status is DetailedRouteStatus.ROUTED
    assert result.routed == (net_id,)
    assert len(attempts) >= 3, "preflight rejection did not trigger same-pack repair"
    assert attempts[0][0] != attempts[1][0], (
        "the rejected endpoint was offered again instead of withdrawing it"
    )


def test_route_feedback_preflight_commit_link_retains_exact_endpoint_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canvas = _Canvas(limit=(0, -2, 6, 2))
    source_index = canvas.add(
        PlacedBuilding(2001, 35, 0, 0, carries_item="ore")
    )
    destination_index = canvas.add(
        PlacedBuilding(2001, 35, 6, 0, carries_item="ore")
    )
    net_id = NetId(0, 1, "ore", NetRole.INTERNAL, 0)
    net = _Net(
        src=_Port(source_index, 0, 0, 0, 0),
        dst=_Port(destination_index, 6, 0, 6, 6),
        item="ore",
        net_id=net_id,
    )
    original = freeform._commit_paths

    def reject_preflight(
        attempt_canvas: _Canvas,
        attempt_nets: list[_Net],
        paths: Mapping[int, Sequence[Cell]],
        belt_id: int,
        belt_model: int,
        src_group: Mapping[int, tuple[int, ...]] | None = None,
        dst_group: Mapping[int, tuple[int, ...]] | None = None,
        *,
        source_hints: Mapping[int, Cell] | None = None,
        sink_hints: Mapping[int, Cell] | None = None,
        failure_details: dict[int, freeform._CommitFailure] | None = None,
    ) -> tuple[int, ...]:
        if attempt_canvas is not canvas:
            if failure_details is not None:
                failure_details[0] = freeform._CommitFailure(
                    cell=paths[0][0],
                    side="source",
                )
            return (0,)
        return original(
            attempt_canvas,
            attempt_nets,
            paths,
            belt_id,
            belt_model,
            src_group,
            dst_group,
            source_hints=source_hints,
            sink_hints=sink_hints,
            failure_details=failure_details,
        )

    monkeypatch.setattr(freeform, "_commit_paths", reject_preflight)
    result = _route_all(
        canvas,
        [net],
        2001,
        35,
        (0, -2, 6, 2),
        budget={"left": 50_000},
    )

    assert result.status is DetailedRouteStatus.STRANDED
    assert result.failures[0].source == (0, 0, 0)
    assert result.failures[0].destination == (6, 0, 0)


def test_unreachable_elevated_port_returns_structured_failure_without_route() -> None:
    canvas = _Canvas(limit=(0, -2, 6, 2))
    source_index = canvas.add(
        PlacedBuilding(2001, 35, 0, 0, carries_item="proliferator-3"),
        level=0,
    )
    destination_index = canvas.add(
        PlacedBuilding(
            2001,
            35,
            6,
            0,
            z=F(1),
            carries_item="proliferator-3",
        ),
        level=1,
    )
    for cell in ((5, 0, 1), (6, -1, 1), (6, 1, 1)):
        canvas.blocked[cell] = -1
    net_id = NetId(0, 1, "proliferator-3", NetRole.PROLIFERATOR, 0)
    net = _Net(
        src=_Port(source_index, 0, 0, 0, 0, z=0),
        dst=_Port(destination_index, 6, 0, 6, 6, z=1),
        item="proliferator-3",
        net_id=net_id,
    )
    before = tuple(canvas.buildings)

    result = _route_all(
        canvas,
        [net],
        2001,
        35,
        (0, -2, 6, 2),
        budget={"left": 20_000},
    )

    assert result.status is DetailedRouteStatus.STRANDED
    assert result.routed == ()
    assert result.failures
    assert result.failures[0].net_id == net_id
    assert result.failures[0].source == (0, 0, 0)
    assert result.failures[0].destination == (6, 0, 1)
    assert tuple(canvas.buildings) == before
    assert not result.exhaustive, "bounded rip-up/reroute is not a completeness proof"



def test_external_route_world_collision_commits_no_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canvas = _Canvas()
    port_index = canvas.add(
        PlacedBuilding(
            item_id=2001,
            model_index=35,
            x=2,
            y=0,
            carries_item="ore",
        )
    )
    net_id = NetId(None, 0, "ore", NetRole.EXTERNAL, 0)
    net = _Net(
        src=None,
        dst=_Port(port_index, 2, 0, 2, 2),
        item="ore",
        net_id=net_id,
        boundary_goals=((0, 0, 0),),
    )
    canvas.world_taken.add((1, 0, F(0)))
    before_buildings = tuple(canvas.buildings)
    before_blocked = dict(canvas.blocked)
    monkeypatch.setattr(
        freeform,
        "_straight_to_edge",
        lambda _canvas, _port, _bounds: [(0, 0, 0), (1, 0, 0)],
    )

    result = _route_external_inputs(
        canvas,
        [net],
        2001,
        35,
        (0, 0, 2, 0),
    )

    assert result.status is DetailedRouteStatus.STRANDED
    assert result.failures[0].kind is RouteFailureKind.COMMIT_LINK
    assert result.failures[0].destination == (2, 0, 0)
    assert tuple(canvas.buildings) == before_buildings
    assert canvas.blocked == before_blocked


def test_external_route_order_control_is_non_exhaustive_and_emits_no_no_good(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared = (1, 0, 0)

    def scene() -> tuple[_Canvas, tuple[_Net, _Net]]:
        canvas = _Canvas(limit=(0, -2, 4, 3))
        first_port = canvas.add(
            PlacedBuilding(2001, 35, 2, 0, carries_item="ore-a")
        )
        second_port = canvas.add(
            PlacedBuilding(2001, 35, 2, 2, carries_item="ore-b")
        )
        first = _Net(
            None,
            _Port(first_port, 2, 0, 2, 2),
            "ore-a",
            net_id=NetId(None, 0, "ore-a", NetRole.EXTERNAL, 0),
            boundary_goals=((0, 0, 0), (0, -1, 0)),
        )
        second = _Net(
            None,
            _Port(second_port, 2, 2, 2, 2),
            "ore-b",
            net_id=NetId(None, 1, "ore-b", NetRole.EXTERNAL, 0),
            boundary_goals=((0, 2, 0),),
        )
        return canvas, (first, second)

    def order_sensitive_path(
        canvas: _Canvas,
        port: _Port,
        _bounds: tuple[int, int, int, int],
    ) -> list[Cell] | None:
        if port.y == 2:
            return [shared, (1, 1, 0), (1, 2, 0)] if canvas.free(shared) else None
        if canvas.free(shared):
            return [(0, 0, 0), shared]
        return [(0, -1, 0), (1, -1, 0), (2, -1, 0)]

    monkeypatch.setattr(freeform, "_straight_to_edge", order_sensitive_path)
    monkeypatch.setattr(
        freeform,
        "_astar",
        lambda *_args, **_kwargs: _PathSearchResult(
            None,
            RouteFailureKind.SEALED_POCKET,
            (shared,),
            1,
        ),
    )

    failed_canvas, (first, second) = scene()
    failed = _route_external_inputs(
        failed_canvas,
        [first, second],
        2001,
        35,
        (0, 0, 2, 2),
    )
    routed_canvas, (first, second) = scene()
    routed = _route_external_inputs(
        routed_canvas,
        [second, first],
        2001,
        35,
        (0, 0, 2, 2),
    )

    assert failed.status is DetailedRouteStatus.STRANDED
    assert not failed.exhaustive
    assert failed.failures[0].destination == (2, 2, 0)
    assert routed.status is DetailedRouteStatus.ROUTED, (
        "the same routes exist when the greedy external-input order is reversed"
    )
    spec = two_stage_spec()
    strips = plan_strips(spec)
    attempt = _proof_attempt(failed, strips)
    assert freeform._proof_scoped_no_goods(attempt, strips) == ((), None)


def test_elevated_external_port_bypasses_ground_fast_path_and_routes_a_ramp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def elevated_scene(limit: tuple[int, int, int, int]) -> tuple[_Canvas, _Net]:
        canvas = _Canvas(ramped=True, limit=limit)
        port_index = canvas.add(
            PlacedBuilding(
                item_id=2001,
                model_index=35,
                x=6,
                y=0,
                z=F(1),
                carries_item="ore",
            ),
            level=1,
        )
        return canvas, _Net(
            src=None,
            dst=_Port(port_index, 6, 0, 6, 6, z=1),
            item="ore",
            net_id=NetId(None, 0, "ore", NetRole.EXTERNAL, 0),
            boundary_goals=((0, 0, 0),),
        )

    monkeypatch.setattr(
        freeform,
        "_straight_to_edge",
        lambda *_args, **_kwargs: pytest.fail(
            "ground-only straight fast path used for elevated port"
        ),
    )
    canvas, net = elevated_scene((0, -2, 7, 2))
    routed = _route_external_inputs(
        canvas,
        [net],
        2001,
        35,
        (1, -1, 6, 1),
        budget={"left": 20_000},
    )
    assert routed.status is DetailedRouteStatus.ROUTED
    assert any(
        building.z.denominator == 2
        for building in canvas.buildings
        if catalog.is_belt(building.item_id)
    )

    blocked_canvas, blocked_net = elevated_scene((0, 0, 2, 0))
    blocked = _route_external_inputs(
        blocked_canvas,
        [blocked_net],
        2001,
        35,
        (0, 0, 2, 0),
        budget={"left": 20_000},
    )
    assert blocked.status is DetailedRouteStatus.STRANDED
    assert blocked.failures

def magnetic_ring_spec() -> BuildSpec:
    """Shaped like the super-magnetic-ring chain, and RATE-BALANCED.

    Nine groups, 54 machines, every machine running at 1/s.  The counts are the
    unique solution of the chain's stoichiometry at two rings per second, so
    supply equals demand for every internal item and every external input equals
    what its consumers draw::

        ring 2      <- turbine 4, graphite 2, magnet 6
        turbine 4   <- motor 4, coil 4
        motor 4     <- ingot 4, gear 4, coil 4
        coil 8      <- magnet 8, copper 8
        gear 4      <- ingot 4
        ingot 8     <- iron-ore 8       magnet 14 <- iron-ore 14
        copper 8    <- copper-ore 8     graphite 2 <- coal 2

    It used to be round numbers instead -- 4 magnetic-coil/s against 12/s of
    demand, and 17 magnet/s on a 12/s belt.  Any test asserting flow-clean on it
    therefore failed for reasons with nothing to do with geometry, which is worse
    than no test: it makes the flow checks unusable on the one fixture with
    enough shape to exercise them.

    The belt is Mk.III because the busiest lane -- iron-ore at 22/s, feeding both
    the ingot and the magnet rows -- does not fit on Mk.II.  Under-sizing the
    belt would reintroduce exactly the failure this fixture exists to avoid.

    These numbers are deliberately identical to ``test_spine``'s fixture of the
    same name.  The two strategies are compared on this shape, and a comparison
    across two different specs is not one.
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


def proliferated_spec() -> BuildSpec:
    """Every consumer proliferated, so the direct-insert set must be empty."""
    base = two_stage_spec()
    return BuildSpec(
        groups=(
            group("iron-ingot", "arc-smelter", 4, {"iron-ore": F(1)}, {"iron-ingot": F(1)}),
            group(
                "gear",
                "assembling-machine-2",
                4,
                {"iron-ingot": F(1)},
                {"gear": F(1)},
                mode=ProliferatorMode.PRODUCTS,
            ),
        ),
        external_inputs={**base.external_inputs, "proliferator-3": F(1) / 2},
        outputs=base.outputs,
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="proliferated",
        belt_required_edges=frozenset({("iron-ingot", "gear")}),
        spray_lanes={"iron-ingot": False},
    )


def spray_domain_spec(*, clean: bool, sprayed: bool, boundary: bool = False) -> BuildSpec:
    """One produced item with independently controlled destination domains."""
    consumers: list[MachineGroup] = []
    outputs: dict[str, F] = {}
    # A one-machine assembling strip trims its input lane to one tile, which
    # its seated input sorter already occupies.  Two clean consumers preserve
    # this fixture's independent, collision-clear direct-insert opportunity.
    clean_machines = 2 if clean else 0
    sprayed_machines = int(sprayed)
    if clean:
        consumers.append(
            group(
                "circuit-board",
                "assembling-machine-2",
                clean_machines,
                {"iron-ingot": F(1)},
                {"circuit-board": F(1)},
            )
        )
        outputs["circuit-board"] = F(clean_machines)
    if sprayed:
        consumers.append(
            group(
                "gear",
                "assembling-machine-2",
                sprayed_machines,
                {"iron-ingot": F(1)},
                {"gear": F(1)},
                mode=ProliferatorMode.PRODUCTS,
            )
        )
        outputs["gear"] = F(sprayed_machines)
    if boundary:
        outputs["iron-ingot"] = F(1)
    domains = int(clean or boundary) + int(sprayed)
    return BuildSpec(
        groups=(
            group(
                "iron-ingot",
                "arc-smelter",
                max(1, clean_machines + sprayed_machines + int(boundary)),
                {"iron-ore": F(1)},
                {"iron-ingot": F(1)},
            ),
            *consumers,
        ),
        external_inputs={
            "iron-ore": F(
                max(1, clean_machines + sprayed_machines + int(boundary))
            ),
            **({"proliferator-3": F(1)} if sprayed else {}),
        },
        outputs=outputs,
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="spray-domain",
        belt_required_edges=(
            frozenset({("iron-ingot", "gear")}) if sprayed else frozenset()
        ),
        spray_lanes={"iron-ingot": False} if sprayed else {},
        lanes_requiring_split=(
            frozenset({"iron-ingot"}) if domains > 1 else frozenset()
        ),
    )


def _spray_domain_flow(
    spec: BuildSpec,
) -> tuple[set[str], set[str], set[str], int, int]:
    family = next(
        family for family in generate_strip_families(spec) if family.recipe_id == "iron-ingot"
    )
    logical_domains = {
        lane.cargo_domain.value
        for lane in family.output_lanes
        if lane.items == ("iron-ingot",)
    }
    strips = plan_strips(spec, strip_len=6)
    strip_domains = {
        domain.value
        for strip in strips
        if strip.recipe_id == "iron-ingot"
        for item, _destination, domain in strip.out_lanes
        if item == "iron-ingot"
    }
    pack = _greedy_pack(strips, sum(_box(strip)[1] for strip in strips))
    prepared = _prepare_routing_problem(
        spec,
        strips,
        pack,
        policy=BandPolicy("portable"),
        power=False,
    )
    net_domains = {
        net.cargo_domain.value
        for net in prepared.nets
        if net.item == "iron-ingot" and net.net_id.role is NetRole.INTERNAL
    }
    assert net_domains <= strip_domains
    for net in prepared.nets:
        assert net.net_id.cargo_domain is net.cargo_domain
        assert net.dst.cargo_domain is net.cargo_domain
        assert net.src is None or net.src.cargo_domain is net.cargo_domain
    return (
        logical_domains,
        strip_domains,
        net_domains,
        prepared.coaters,
        len(_direct_net_candidates(strips, spec)),
    )

def test_uniform_sprayed_lane_preserves_requires_spray_domain() -> None:
    spec = spray_domain_spec(clean=False, sprayed=True)

    logical, strip, nets, coaters, direct = _spray_domain_flow(spec)
    assert logical == strip == {"requires-spray"}
    assert coaters == 1
    assert nets == {"requires-spray"}
    assert direct == 0
    assert not spec.lanes_requiring_split


def test_uniform_unsprayed_lane_preserves_clean_domain() -> None:
    spec = spray_domain_spec(clean=True, sprayed=False)

    logical, strip, nets, coaters, direct = _spray_domain_flow(spec)
    assert logical == strip == {"unsprayed"}
    assert coaters == 0
    assert nets == {"unsprayed"}
    assert direct == 1
    assert not spec.lanes_requiring_split


def test_mixed_internal_spray_domains_remain_disjoint() -> None:
    spec = spray_domain_spec(clean=True, sprayed=True)

    logical, strip, nets, coaters, direct = _spray_domain_flow(spec)
    assert logical == strip == {"unsprayed", "requires-spray"}
    assert coaters == 1
    assert nets == {"unsprayed", "requires-spray"}
    assert direct == 1
    assert spec.lanes_requiring_split == {"iron-ingot"}


def test_mixed_spray_domain_direct_candidate_is_clean_and_exact() -> None:
    spec = spray_domain_spec(clean=True, sprayed=True)
    strips = plan_strips(spec, strip_len=6)

    candidates = _direct_net_candidates(strips, spec)

    assert list(candidates) == [(0, 1)]
    candidate = candidates[0, 1]
    assert strips[0].recipe_id == "iron-ingot"
    assert strips[1].recipe_id == "circuit-board"
    assert strips[2].recipe_id == "gear"
    assert (
        candidate.item,
        candidate.cargo_domain,
        candidate.prod_row,
        candidate.cons_row,
        candidate.prod_span,
        candidate.cons_span,
        candidate.origin_deltas,
    ) == (
        "iron-ingot",
        CargoDomain.UNSPRAYED,
        4,
        0,
        9,
        5,
        tuple(range(-2, 8)),
    )


def test_requested_output_is_unsprayed_beside_proliferated_internal_lane() -> None:
    spec = spray_domain_spec(clean=False, sprayed=True, boundary=True)

    logical, strip, nets, coaters, direct = _spray_domain_flow(spec)
    assert logical == strip == {"unsprayed", "requires-spray"}
    assert coaters == 1
    assert nets == {"requires-spray"}
    assert direct == 0
    assert spec.lanes_requiring_split == {"iron-ingot"}


ALL_SPECS = [single_recipe_spec, two_stage_spec, magnetic_ring_spec, proliferated_spec]

#: Freeform used to refuse any strip plan where one producer lane had to feed
#: several consumer lanes, because a belt tile has one ``output_obj``.  It now
#: taps a different TILE of the lane for each consumer and junctions there with
#: a splitter, so the gap is closed and the marker that stood here is gone.
#:
#: Kept as a note rather than a marker: the tests it was attached to are the
#: ones that prove the fan-out works, and they assert it directly now.
#: ``ALL_SPECS`` for ``parametrize``, with the unservable spec marked.  Kept
#: separate because ``ALL_SPECS`` is also iterated directly, where a
#: ``pytest.param`` wrapper would not be callable.
ALL_SPEC_PARAMS = [pytest.param(f, id=f.__name__) for f in ALL_SPECS]


# --- helpers ---------------------------------------------------------------


def blocking_tiles(p: Placement) -> list[tuple[int, int, F]]:
    """Tiles that genuinely exclude another building.

    Mirrors the validator's occupancy rule: belt-integrated buildings share
    tiles rather than reserving them, and belt addons such as the Spray Coater
    consume no grid cell at all.

    ``is_belt_integrated``, not ``is_sorter``. Belts and SPLITTERS are equally
    belt-integrated, and a junction legitimately carries several belts on its
    own tile -- the lane arriving, the lane continuing past it, and the branch
    leaving. Counting those as collisions reported six overlaps in a layout the
    game accepts. Belt-on-belt overlap is still checked, by
    ``geom.belt_single_occupancy``, which knows about junctions.
    """
    tiles: list[tuple[int, int, F]] = []
    for b in p.buildings:
        if catalog.is_belt_integrated(b.item_id):
            continue
        if not catalog.building(b.item_id).occupies_tiles:
            continue
        tiles.extend(b.tiles())
    return tiles


def machines_of(p: Placement) -> list[int]:
    """Buildings that are actual machines, for counting against the spec.

    Uses ``is_belt_integrated`` rather than spelling out belts and sorters. The
    hand-written version missed SPLITTERS, which are equally belt-integrated,
    and so counted every junction as a machine -- 59 "machines" for a 58-machine
    spec, varying run to run with how many junctions the packer needed. That
    reads exactly like a layout duplicating machines, which is what it was
    reported as.
    """
    return [
        i
        for i, b in enumerate(p.buildings)
        if not catalog.is_belt_integrated(b.item_id)
        and b.item_id != catalog.TESLA_TOWER_ID
        and catalog.building(b.item_id).occupies_tiles
    ]


# --- the fixtures themselves -----------------------------------------------


class TestTheFixturesBalance:
    """A hand-built spec that does not balance makes every flow check useless.

    ``magnetic_ring_spec`` used to be round numbers -- 4 magnetic-coil/s
    supplying 12/s of demand, 17 magnet/s on a 12/s belt -- so a test asserting
    anything about flow on it failed for arithmetic reasons and told you nothing
    about the layout.  These two tests are pure arithmetic on the spec: they
    cannot be satisfied by a change to the layout, only by the numbers being
    right, so the fixtures cannot rot back.

    ``proliferated_spec`` is excluded on purpose.  Its proliferator arrives as an
    external input that no machine GROUP consumes -- the belt-mounted coaters do
    -- so a supply-equals-demand sum over groups is the wrong question there.
    """

    _BALANCED = [single_recipe_spec, two_stage_spec, magnetic_ring_spec]

    @pytest.mark.parametrize("spec_fn", _BALANCED, ids=lambda f: f.__name__)
    def test_supply_equals_demand_for_every_item(self, spec_fn: SpecFactory) -> None:
        spec = spec_fn()
        made: dict[str, F] = {}
        used: dict[str, F] = {}
        for g in spec.groups:
            for item, rate in g.outputs_per_machine.items():
                made[item] = made.get(item, F(0)) + rate * g.count
            for item, rate in g.inputs_per_machine.items():
                used[item] = used.get(item, F(0)) + rate * g.count
        for item in set(made) | set(used):
            supply = made.get(item, F(0)) + spec.external_inputs.get(item, F(0))
            demand = used.get(item, F(0)) + spec.outputs.get(item, F(0))
            assert supply == demand, f"{item}: {supply}/s supplied against {demand}/s demanded"

    @pytest.mark.parametrize("spec_fn", _BALANCED, ids=lambda f: f.__name__)
    def test_no_item_needs_more_than_one_belt_of_its_tier(
        self, spec_fn: SpecFactory
    ) -> None:
        """Freeform shards a group across strips, so a lane carries a SHARD's flow.

        A whole item's flow still has to fit the belt the spec names, because an
        external input arrives on one straight run per lane and the marker pass
        labels it with the item's full rate.  A fixture that needs the belt tier
        raised is a fixture written without checking, which is how 17 items/s
        ended up nominated for a 12/s belt.
        """
        spec = spec_fn()
        flow: dict[str, F] = dict(spec.external_inputs)
        for g in spec.groups:
            for item, rate in g.outputs_per_machine.items():
                flow[item] = flow.get(item, F(0)) + rate * g.count
        for item, rate in flow.items():
            assert rate <= spec.belt_items_per_second, (
                f"{item} moves {rate}/s on a {spec.belt_items_per_second}/s belt"
            )


# --- strip planning --------------------------------------------------------


class TestPlanStrips:
    def test_every_machine_lands_in_exactly_one_strip(self) -> None:
        spec = magnetic_ring_spec()
        strips = plan_strips(spec, strip_len=6)
        placed = sum(s.machines for s in strips)
        assert placed == spec.machine_count

    def test_strip_length_is_respected(self) -> None:
        spec = magnetic_ring_spec()
        strips = plan_strips(spec, strip_len=6)
        assert all(s.machines <= 6 for s in strips)

    def test_lanes_stay_within_sorter_reach_on_each_side(self) -> None:
        """A sorter spans three tiles, so each SIDE carries at most three lanes.

        The limit is per side, not per strip: lanes above and lanes below are
        reached by different sorters, so six lanes total is fine while four on
        one side is not.
        """
        for spec_fn in ALL_SPECS:
            for s in plan_strips(spec_fn(), strip_len=6):
                assert len(s.in_above) <= catalog.SORTER_MAX_REACH
                assert len(s.out_lanes) + len(s.in_below) <= catalog.SORTER_MAX_REACH

    def test_a_four_input_recipe_is_fed_from_both_sides(self) -> None:
        """Four ingredients is ordinary, not exotic -- orbital-collector has four.

        Three fit above; the fourth goes below alongside the output lane. Every
        prior test used recipes with three inputs or fewer, which is why this
        stayed broken until a real URL was tried.

        THE HEIGHT ASSERTION USED TO READ ``3 + s.mh + 2``, AND THAT IS FALSE.
        It believed a machine band costs as many rows as the machines are tall,
        which held only while a tile was 1.0 world units.  An Assembling Machine
        COVERS three tiles and NEEDS four -- its collider is 3.82 units against
        a 1.2566 tile -- so the band reserves ``s.ph``, and every lane below it
        begins after the CLEARANCE rather than after the footprint.  This strip
        is 9 rows, not 8, and the missing row was the one a junction beside a
        machine needs.  ``Strip.band_rows`` is the single owner of that number
        (see its docstring for the seven consumers that move together), so the
        test asks it instead of restating a literal that was right by accident.
        """
        spec = BuildSpec(
            groups=(
                group(
                    "four-in",
                    "assembling-machine-2",
                    2,
                    {"a": F(1), "b": F(1), "c": F(1), "d": F(1)},
                    {"out": F(1)},
                ),
            ),
            external_inputs={"a": F(2), "b": F(2), "c": F(2), "d": F(2)},
            outputs={"out": F(2)},
        )
        strips = plan_strips(spec, strip_len=6)
        assert len(strips) == 1
        s = strips[0]
        assert set(s.in_lanes) == {"a", "b", "c", "d"}
        assert len(s.in_above) == catalog.SORTER_MAX_REACH
        assert len(s.in_below) == 1
        # Every lane still reachable: three above, two below (one in, one out).
        assert len(s.in_above) <= catalog.SORTER_MAX_REACH
        assert len(s.in_below) + len(s.out_lanes) <= catalog.SORTER_MAX_REACH
        # The fixture must be a machine whose clearance EXCEEDS its footprint,
        # or the corrected reading and the false one are the same number and
        # this assertion could not tell them apart.
        assert (s.mh, s.ph) == (3, 4), "fixture must be a machine that pads"
        assert s.band_rows == s.ph, "the band reserves clearance, not footprint"
        assert s.height == 3 + s.band_rows + 2 == 9

    def test_a_four_input_recipe_lays_out_and_validates(self) -> None:
        """Planning it is not enough -- it has to emit and pass the neutral judge.

        Uses a REAL four-ingredient recipe, because emission needs a genuine DSP
        recipe id; a synthesised name plans fine and then fails at the catalog.
        """
        ins = {
            "annihilation-constraint-sphere": F(1),
            "antimatter": F(1),
            "hydrogen": F(1),
            "titanium-alloy": F(1),
        }
        spec = BuildSpec(
            groups=(
                group(
                    "antimatter-fuel-rod",
                    "assembling-machine-2",
                    2,
                    ins,
                    {"antimatter-fuel-rod": F(1)},
                ),
            ),
            external_inputs={k: F(2) for k in ins},
            outputs={"antimatter-fuel-rod": F(2)},
        )
        strips = plan_strips(spec, strip_len=6)
        assert len(strips[0].in_below) == 1, "the fourth ingredient must go below"
        p = FreeformLayout(
            band_policy=BandPolicy("portable"),
        ).lay_out(spec, time_budget_s=0.5)
        report = validate.validate(p, expect_power=True)
        assert report.ok, "\n".join(f"{f.check}: {f.message}" for f in report.errors[:6])

    @staticmethod
    def _many_input_spec(n: int) -> BuildSpec:
        import string

        return BuildSpec(
            groups=(
                group(
                    "impossible",
                    "assembling-machine-2",
                    1,
                    {k: F(1) for k in string.ascii_lowercase[:n]},
                    {"out": F(1)},
                ),
            )
        )

    def test_the_ceiling_is_the_machines_insert_POSES_not_its_rows(self) -> None:
        """Five ingredients on an assembler: three above, two below, output below.

        THIS SAID TWELVE, AND TWELVE NEEDED TWELVE SLOTS THAT DO NOT EXIST.  An
        Assembling Machine offers a lane THREE insert poses per face, and a slot
        holds exactly one connection -- ``entityConnPool[objId * 16 + slot]``,
        see ``validate.game.slot_occupancy``.  Mixing several items onto one lane
        saves a ROW and saves no slot at all, so a ceiling counted in rows
        counted something the machine does not have: the twelve-ingredient plan
        emitted three sorters onto slot 6 and three onto slot 7 of every machine,
        of which the game keeps one each.

        Three above plus two below is what the poses carry, the second south
        column going to the output lane.  DSP's own recipes reach six
        ingredients, so this DOES bind something real -- ``universe-matrix`` --
        and that is recorded as a refusal rather than papered over.
        """
        strips = plan_strips(self._many_input_spec(5), strip_len=6)
        assert len(strips[0].in_lanes) == 5
        assert sum(len(lane) for lane in strips[0].in_above) == 3
        assert sum(len(lane) for lane in strips[0].in_below) == 2

    def test_six_ingredients_seat_once_the_product_leaves_east(self) -> None:
        """Six fit when the output flanks; seven still do not, and must not.

        THIS TEST USED TO ASSERT THAT SIX REFUSED, and it was right about the
        arithmetic and wrong about the building.  An Assembling Machine defines
        TWELVE insert poses, three per side, and a lane-fed strip was reading two
        of the four sides.  Six ingredients and a product is seven connections
        into six slots only if the east face does not exist.

        Seven ingredients still refuse, and that is the half of this test that
        matters.  The north and south faces carry three sorters each and the east
        face carries the product; the ceiling moved from six connections to
        seven, it did not go away.  If a change makes seven pass, it has relaxed
        ``game.slot_occupancy`` rather than used another face.
        """
        strips = plan_strips(self._many_input_spec(6), strip_len=6)
        assert strips[0].flank_outputs, "six must seat by flanking, not by doubling up"
        assert len(strips[0].in_lanes) == 6
        with pytest.raises(ValueError, match="insert pose"):
            plan_strips(self._many_input_spec(7), strip_len=6)

    def test_a_flanked_output_claims_no_column_on_the_south_face(self) -> None:
        """The south face is handed back whole, not minus one.

        ``column_offset`` rations columns across every lane on a face, and it
        charged the ingredients below for the output lane sharing that face.  A
        flanked output is not on that face at all.  Charging it anyway rations
        away the column the flank exists to free, and it shows up as a lane
        trimmed one tile short of the column it was actually given.
        """
        strips = plan_strips(self._many_input_spec(6), strip_len=6)
        s = strips[0]
        assert s.flank_outputs and s.out_lanes, "this strip must have both to mean anything"
        assert s.column_offset(s.in_below[0]) == 0

    def test_a_recipe_needing_more_lanes_than_two_sides_carry_is_rejected(self) -> None:
        """Truncating an ingredient would paste cleanly and then stall."""
        with pytest.raises(ValueError, match="cannot be seated"):
            plan_strips(self._many_input_spec(13), strip_len=6)


class TestASideCarriesAsManyLanesAsItsPosesAllow:
    """Lane seating asks the slot table how many rows a side really has.

    ``_seat_inputs`` and ``out_cap`` both read ``SORTER_MAX_REACH`` and counted
    from the machine's FOOTPRINT EDGE, which is the same false premise
    ``sorter_span`` was corrected for in 5e982bb -- one layer earlier.  Three
    lanes fit above a machine only when its northern pose is ON its top row, and
    three fit below only when its clearance equals its footprint.  Neither holds
    everywhere:

    * a **Chemical Plant** anchors its north face on the row INSIDE its top
      edge, so the outermost of three lanes above is FOUR tiles from anything a
      sorter can hold and the side carries TWO;
    * an **Assembling Machine** covers three rows and reserves four, so the
      outermost of three lanes below is FOUR tiles from its bottom edge and the
      south side carries TWO.

    Seating a lane there is not a near miss -- ``slots.attachment`` returns
    ``None``, so ``_link_lane`` places no sorter at all and the machine ships
    joined to nothing on that lane.  ``_machines_without_poses`` catches it and
    refuses, which is why the ``organic-crystal`` URL refused on every
    candidate.  The fix is to never seat the lane, not to widen the reach.
    """

    @staticmethod
    def _unreachable(strips: list[Strip]) -> list[tuple[str, int, int]]:
        """Every lane row of every strip that no sorter tier could join."""
        out = []
        for s in strips:
            rows = [j for j in range(len(s.in_above))]
            rows += [s.row_of_output(k) for k in range(len(s.out_lanes))]
            rows += [s.row_of_input(lane[0]) for lane in s.in_below]
            for row in rows:
                span = s.sorter_span(row)
                if not 1 <= span <= catalog.SORTER_MAX_REACH:
                    out.append((s.recipe_id, row, span))
        return out

    @staticmethod
    def _organic_crystal_spec() -> BuildSpec:
        """The chemical-plant half of the URL that refused, and nothing else."""
        ins = {"plastic": F(2), "refined-oil": F(1), "water": F(1)}
        return BuildSpec(
            groups=(
                group("organic-crystal", "chemical-plant", 2, ins, {"organic-crystal": F(1)}),
            ),
            external_inputs={k: v * 2 for k, v in ins.items()},
            outputs={"organic-crystal": F(2)},
            belt_item_id="conveyor-belt-2",
            belt_items_per_second=F(12),
            label="organic-crystal",
        )

    def test_the_chemical_plants_north_face_is_really_inset(self) -> None:
        """The premise, checked -- without it the next test proves nothing.

        If a Chemical Plant took three lanes above like everything else, the
        seating assertion below would pass whether or not seating consults the
        slot table, and could never have shown the claim false.
        """
        from flab2bp.layout import slots as slot_table

        item_id = catalog.item_id("chemical-plant")
        probe = slot_table.probe_building(item_id, slot_table.lane_orientation(item_id))
        assert slot_table.attachable_columns(probe, -1), "the near row must work"
        assert slot_table.attachable_columns(probe, -2), "the middle row must work"
        assert not slot_table.attachable_columns(probe, -3), (
            "a Chemical Plant's third row above must be OUT of reach, or this "
            "fixture cannot distinguish a slot-table answer from the constant 3"
        )

    def test_three_ingredients_on_a_chemical_plant_seat_where_a_sorter_reaches(
        self,
    ) -> None:
        strips = plan_strips(self._organic_crystal_spec(), strip_len=6)
        assert self._unreachable(strips) == []
        assert _machines_without_poses(strips) == []
        (s,) = strips
        assert len(s.in_above) == 2, "only two rows above a Chemical Plant reach it"
        assert len(s.in_below) == 1, "the third ingredient belongs on the south side"

    def test_an_assemblers_south_side_carries_two_lanes_not_three(self) -> None:
        """Its clearance exceeds its footprint, so the third row below is 4 away.

        Three destinations is the shape ``universe-matrix`` hits: one output
        lane per consumer put a lane on a row no sorter could anchor between.
        """
        spec = BuildSpec(
            groups=(
                group("gear", "assembling-machine-2", 3, {"iron-ingot": F(1)}, {"gear": F(1)}),
                group("a", "assembling-machine-2", 1, {"gear": F(1)}, {"a": F(1)}),
                group("b", "assembling-machine-2", 1, {"gear": F(1)}, {"b": F(1)}),
                group("c", "assembling-machine-2", 1, {"gear": F(1)}, {"c": F(1)}),
            ),
            external_inputs={"iron-ingot": F(3)},
            outputs={"a": F(1), "b": F(1), "c": F(1)},
            belt_item_id="conveyor-belt-2",
            belt_items_per_second=F(12),
            label="three-consumers",
        )
        strips = plan_strips(spec, strip_len=6)
        assert self._unreachable(strips) == []
        assert _machines_without_poses(strips) == []
        gears = [s for s in strips if s.recipe_id == "gear"]
        assert gears, "the fixture must actually produce a gear strip"
        assert all(len(s.out_lanes) + len(s.in_below) <= 2 for s in gears)



# --- fallback --------------------------------------------------------------


class TestFallback:
    @pytest.mark.parametrize("spec_fn", ALL_SPECS, ids=lambda f: f.__name__)
    def test_fallback_is_complete_and_non_overlapping(
        self,
        spec_fn: SpecFactory,
    ) -> None:
        spec = spec_fn()
        placement = fallback_placement(spec, band_policy=BandPolicy("portable"), power=True)
        tiles = blocking_tiles(placement)
        assert len(tiles) == len(set(tiles)), "fallback overlaps"
        assert placement.buildings
        assert len(machines_of(placement)) == spec.machine_count


# --- placement properties --------------------------------------------------


@pytest.mark.parametrize("spec_fn", ALL_SPEC_PARAMS)
class TestPlacementProperties:
    def test_emitted_blueprint_obeys_physical_and_reference_contracts(
        self,
        spec_fn: SpecFactory,
    ) -> None:
        spec = spec_fn()
        placement = FreeformLayout(
            band_policy=BandPolicy(_LEGACY_BAND_BY_SPEC_LABEL[spec.label]),
        ).lay_out(spec, time_budget_s=1.0)
        tiles = blocking_tiles(placement)
        assert len(tiles) == len(set(tiles)), "overlapping footprints"
        assert len(machines_of(placement)) == spec.machine_count

        for index, building in enumerate(placement.buildings):
            if catalog.is_sorter(building.item_id):
                assert building.x2 is not None and building.y2 is not None
                dx, dy = abs(building.x - building.x2), abs(building.y - building.y2)
                assert not (dx and dy), "sorters run straight, never diagonally"
                assert 1 <= dx + dy <= catalog.SORTER_MAX_REACH
                assert building.z == (building.z2 or 0), "sorters never span altitudes"
                assert building.input_obj is not None
                assert building.output_obj is not None
                assert 0 <= building.input_obj < len(placement.buildings)
                assert 0 <= building.output_obj < len(placement.buildings)
                assert building.input_obj != building.output_obj
            elif catalog.is_belt(building.item_id) and building.output_obj is not None:
                target = placement.buildings[building.output_obj]
                assert abs(target.x - building.x) + abs(target.y - building.y) <= 1, (
                    f"belt {index} links non-adjacent"
                )

        report = validate.validate(placement, expect_power=True)
        assert report.ok, "\n".join(f"{f.check}: {f.message}" for f in report.errors[:10])


# --- the direct-insert / proliferation interaction -------------------------


class TestProliferationForbidsDirectInsertion:
    def test_candidate_filter_rejects_belt_required_and_prefab_port_edges(
        self,
    ) -> None:
        belt_required = magnetic_ring_spec().model_copy(
            update={"belt_required_edges": frozenset({("iron-ingot", "gear")})}
        )
        strips = plan_strips(belt_required, strip_len=6)
        candidates = _direct_net_candidates(strips, belt_required)
        assert candidates, "the other eligible recipe edges keep the filter non-vacuous"
        assert all(
            (strips[source].recipe_id, strips[destination].recipe_id)
            != ("iron-ingot", "gear")
            for source, destination in candidates
        )

        prefab = ray_receiver_spec()
        prefab_strips = plan_strips(prefab, strip_len=6)
        assert any(strip.takes_belt_ports for strip in prefab_strips)
        assert _direct_net_candidates(prefab_strips, prefab) == {}

    def test_belt_required_edges_are_never_direct_inserted(self) -> None:
        spec = proliferated_spec()
        layout = FreeformLayout(
            band_policy=BandPolicy("portable"),
        )
        p = layout.lay_out(spec, time_budget_s=0.5)
        assert p.stats["direct_inserts"] == 0.0

    def test_an_unproliferated_twin_permits_direct_insertion(self) -> None:
        """Guards the constraint against being vacuous.

        If the same spec without proliferation also reported zero candidates,
        the previous test would prove nothing about the constraint.
        """
        layout = FreeformLayout(
            band_policy=BandPolicy("portable"),
        )
        p = layout.lay_out(two_stage_spec(), time_budget_s=0.5)
        assert p.stats["direct_insert_candidates"] > 0.0

    def test_the_proliferated_spec_still_validates(self) -> None:
        """A silently under-producing build pastes cleanly, so the judge matters."""
        p = FreeformLayout(
            band_policy=BandPolicy("portable"),
        ).lay_out(proliferated_spec(), time_budget_s=0.5)
        report = validate.validate(p, expect_power=True)
        assert report.ok, "\n".join(f"{f.check}: {f.message}" for f in report.errors[:5])


# --- lane length -----------------------------------------------------------


class TestLanesStopAtTheirLastTap:
    """An input lane past its last sorter is a belt nothing draws from.

    Lanes used to run the full strip width regardless, which cost a building per
    tile to paste and -- the part that actually bit -- left occupied cells the
    router had to path around.  Freeing them is what moved a Spray Coater's drop
    belt off the neighbouring strip's face and into its own strip's interior.

    Output lanes are deliberately NOT trimmed: they are filled at every machine
    column and drained at the east end, so every tile between the first sorter
    and the port carries flow.
    """

    def test_an_input_lane_is_long_enough_and_no_longer(self) -> None:
        for s in plan_strips(magnetic_ring_spec(), strip_len=6):
            for lane in s.in_above + s.in_below:
                tiles = s.input_lane_tiles(lane)
                assert tiles <= s.width
                # Every machine still gets a sorter, so the last machine's
                # column must be on the lane.
                assert tiles >= (s.machines - 1) * s.mw + 1

    def test_emission_lays_exactly_that_many_belt_tiles(self) -> None:
        """Emission and ``Strip`` must agree on the length.

        They are two statements of the same number -- the packer uses the
        ``Strip`` one to decide whether a bridging sorter has a column to run
        down, and emission uses its own -- so a drift between them shows up as a
        rewarded direct insert whose lanes turn out to share no tile.
        """
        spec = magnetic_ring_spec()
        strips = plan_strips(spec, strip_len=max(1, spec.machine_count))
        expected = sum(
            sum(s.input_lane_tiles(lane) for lane in s.in_above + s.in_below)
            + len(s.out_lanes) * s.width
            for s in strips
        )
        untrimmed = sum(
            (len(s.in_above) + len(s.in_below) + len(s.out_lanes)) * s.width
            for s in strips
        )
        assert expected < untrimmed, "the fixture no longer exercises trimming"

        p = fallback_placement(spec, band_policy=BandPolicy("portable"), power=False)
        belts = sum(1 for b in p.buildings if catalog.is_belt(b.item_id))
        assert belts == expected


# --- direct insertion ------------------------------------------------------


def test_direct_column_deltas_match_the_exact_pairwise_oracle() -> None:
    rng = random.Random(0)
    for _ in range(100):
        source = tuple(
            sorted(rng.sample(range(-8, 17), rng.randint(1, 20)))
        )
        destination = tuple(
            sorted(rng.sample(range(-11, 14), rng.randint(1, 20)))
        )

        assert _direct_column_deltas(source, destination) == tuple(
            sorted(
                {
                    source_column - destination_column
                    for source_column in source
                    for destination_column in destination
                }
            )
        )
    for count in (255, 256):
        columns = tuple(range(count))
        assert _direct_column_deltas(columns, columns) == tuple(
            range(1 - count, count)
        )




def test_direct_column_delta_work_is_linear_in_packed_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CountedColumn(int):
        subtractions = 0

        def __sub__(self, other: object) -> int:
            type(self).subtractions += 1
            return int(self) - int(other)

    class CountedBytearray(bytearray):
        allocations = 0
        writes = 0

        def __init__(self, source: object = 0) -> None:
            super().__init__(source)
            type(self).allocations += len(self)

        def __setitem__(self, key: object, value: object) -> None:
            type(self).writes += 1
            super().__setitem__(key, value)

    extraction_reads = 0
    extract = freeform._packed_nonzero_digits

    def counted_extract(
        packed: bytes,
        coefficient_bytes: int,
        digit_count: int,
    ) -> bytearray:
        class CountedPackedBytes:
            def __iter__(self):
                nonlocal extraction_reads
                for value in packed:
                    extraction_reads += 1
                    yield value

        return extract(CountedPackedBytes(), coefficient_bytes, digit_count)

    monkeypatch.setattr(freeform, "bytearray", CountedBytearray, raising=False)
    monkeypatch.setattr(freeform, "_packed_nonzero_digits", counted_extract)
    source = tuple(CountedColumn(column) for column in range(0, 2400, 2))
    destination = tuple(CountedColumn(column) for column in range(1, 2401, 2))
    coefficient_bytes = 2
    source_digits = source[-1] - source[0] + 1
    destination_digits = destination[-1] - destination[0] + 1
    product_digits = source_digits + destination_digits - 1

    deltas = _direct_column_deltas(source, destination)

    assert deltas == tuple(range(-2399, 2399, 2))
    assert CountedColumn.subtractions <= 2 * (len(source) + len(destination))
    assert extraction_reads == product_digits * coefficient_bytes
    assert CountedBytearray.allocations == (
        (source_digits + destination_digits) * coefficient_bytes + product_digits
    )
    assert CountedBytearray.writes <= (
        len(source) + len(destination) + extraction_reads
    )


class TestDirectInsertion:
    """A direct insert replaces a routed belt net with a single sorter.

    These tests exist because the feature was previously *identified* and then
    discarded -- ``stats["direct_inserts"]`` was hardcoded to zero and the
    ``MU_DIRECT`` reward never reached the objective. Asserting the counter moved
    would not have caught that; asserting belts disappear does.
    """

    @staticmethod
    def _stacked(spec: BuildSpec, *, direct: bool) -> tuple[Placement, object]:
        """Pack at a height that forces stacking, then build.

        Deliberately below `lay_out`, because the full height sweep is area-first
        and stacking *costs* area here -- see
        ``test_the_sweep_prefers_area_over_direct_insertion``. Testing through the
        sweep would therefore assert the mechanism is broken when it is merely
        outranked. This exercises the mechanism itself.
        """
        strips = plan_strips(spec, strip_len=6)
        cands = _direct_net_candidates(strips, spec) if direct else {}
        height = sum(s.height + 1 for s in strips)
        pack = _pack(
            strips,
            height=height,
            width_bound=max(s.width + 1 for s in strips) * 2,
            time_budget_s=0.5,
            direct_candidates=cands,
            workers=DETERMINISTIC_WORKERS,
        )
        assert pack is not None
        result = _build(
            spec,
            strips,
            pack,
            power=False,
            route=True,
            policy=BandPolicy("portable"),
        )
        assert result.routing.status is DetailedRouteStatus.ROUTED
        assert result.placement is not None
        return result.placement, pack

    def test_the_bridge_is_a_lane_to_lane_transfer_not_a_machine_pair(self) -> None:
        """What freeform emits, stated plainly, because a counter disagrees.

        ``bench/metrics.py`` counts a direct insert as a sorter whose BOTH ends
        are machines.  Freeform's bridge spans the producer's output lane to the
        consumer's input lane, so that counter reports zero however many bridges
        are placed -- which is why the bake-off's ``B d.ins`` column read 0 on
        every spec while 17 bridges were being emitted across the corpus.

        The lanes are not an oversight that could be tightened away.  A strip is
        input lanes / machines / output lanes stacked top to bottom, and the pack
        keeps a margin between strips, so the closest two machine bands can come
        is ``out_lanes + margin + in_lanes >= 1 + 1 + 1`` rows of separation plus
        one to land on -- four tiles, against a sorter reach of three.  A
        machine-to-machine insert needs the strip planner to omit both lanes for
        that edge, which changes every strip's height and therefore the pack.
        """
        p, _ = self._stacked(two_stage_spec(), direct=True)
        belts = {i for i, b in enumerate(p.buildings) if catalog.is_belt(b.item_id)}
        machines = set(machines_of(p))
        transfers = [
            b
            for b in p.buildings
            if catalog.is_sorter(b.item_id)
            and b.input_obj in belts
            and b.output_obj in belts
        ]
        assert len(transfers) >= 1, "no lane-to-lane bridge was emitted"
        assert not [
            b
            for b in p.buildings
            if catalog.is_sorter(b.item_id)
            and b.input_obj in machines
            and b.output_obj in machines
        ], "a machine-to-machine sorter appeared; the reach arithmetic above is stale"

    def test_a_bridge_declines_the_column_a_strip_sorter_already_meets(self) -> None:
        """The guard, asked about the sorter the PASTE will build.

        A bridge is belt-to-belt, so the game grows its collider past BOTH ends;
        drop one on a lane tile a strip's own sorter already meets and the two
        boxes overlap by twice ``SORTER_END_EXTENSION``, which the game refuses
        as ``Collide``.  ``_bridge`` has always asked before taking a column --
        but it asked about a sorter carrying the dataclass default of zero in
        every slot field, because ``assign_sorter_slots`` does not run until
        emission.  Seated on slot 0 the standing sorter's box sits a whole
        four fifths of a tile west of where the paste will put it, so the
        colliding column looked free: 15 of 96 corpus cells came out with
        bridges ``game.sorter_collide`` then convicted.

        Column 5 here is that column.  Column 6 carries the same pair of lanes
        and nothing standing, so a bridge belongs there and the guard must not
        refuse the transfer outright.
        """
        machine = PlacedBuilding(
            item_id=2304,
            model_index=catalog.building(2304).model_index,
            x=4,
            y=4,
            width=3,
            height=3,
        )
        belt = catalog.building(2001)
        lane = [
            PlacedBuilding(item_id=2001, model_index=belt.model_index, x=x, y=y)
            for y in (2, 0)
            for x in (5, 6)
        ]
        standing = PlacedBuilding(
            item_id=2011,
            model_index=catalog.building(2011).model_index,
            x=5,
            y=2,
            x2=5,
            y2=4,
            z2=F(0),
            input_obj=1,
            output_obj=0,
        )
        canvas = _Canvas(buildings=[machine, *lane, standing])
        canvas.blocked = {
            (b.x, b.y, 0): i + 1 for i, b in enumerate(lane)
        }
        src = _Port(3, 5, 0, 5, 6, (3, 4), 1)
        dst = _Port(1, 5, 2, 5, 6, (1, 2), 1)
        boxes = slots.sorter_seat_boxes(canvas.buildings)
        assert _bridge(
            canvas,
            src,
            dst,
            {"iron-ingot": F(1)},
            "iron-ingot",
            boxes,
            DirectInsertId(0, 1, "iron-ingot", CargoDomain.UNSPRAYED),
        )
        bridge = canvas.buildings[-1]
        assert catalog.is_sorter(bridge.item_id)
        assert bridge.x == 6, "took the column a standing sorter already meets"

    def test_no_bridge_lands_on_a_sorter_the_paste_would_refuse(self) -> None:
        """The bridge guard, asked about the sorter the PASTE will build.

        A bridge is belt-to-belt, so the game grows its collider past BOTH ends;
        drop one on a lane tile a strip's own sorter already meets and the two
        boxes overlap by twice ``SORTER_END_EXTENSION``, which the game refuses
        as ``Collide``.  ``_bridge`` has always asked before taking a column --
        but it asked about a sorter carrying the dataclass default of zero in
        every slot field, because ``assign_sorter_slots`` does not run until
        emission.  Seated on slot 0 of the wrong corner, the answer had no
        bearing on the sorter about to be built, and 15 of 96 corpus cells came
        out with bridges ``game.sorter_collide`` then convicted.
        """
        p, _ = self._stacked(two_stage_spec(), direct=True)
        seats = [
            (i, seat)
            for i, b in enumerate(p.buildings)
            if catalog.is_sorter(b.item_id)
            and (seat := slots.seated_sorter(b, p.buildings)) is not None
        ]
        pairs = [
            (seats[a][0], seats[c][0])
            for a, c in colliders.sorter_collisions([s for _i, s in seats])
        ]
        assert pairs == [], f"{len(pairs)} sorter pairs the paste would refuse"

    def test_an_adjacent_pair_is_actually_direct_inserted(self) -> None:
        p, pack = self._stacked(two_stage_spec(), direct=True)
        assert pack.direct, "packer found no direct-insertable pair"  # type: ignore[attr-defined]
        assert p.stats["direct_inserts"] >= 1.0

    def test_direct_insertion_removes_belts_rather_than_only_counting(self) -> None:
        """The mechanism, not the counter.

        Same spec, same height, same worker count -- the only difference is
        whether direct insertion is permitted. If enabling it does not delete
        belt tiles then no net was actually replaced, which is precisely the bug
        this feature previously had: a hardcoded counter and no effect.
        """
        spec = two_stage_spec()
        on, _ = self._stacked(spec, direct=True)
        off, _ = self._stacked(spec, direct=False)

        assert off.stats["direct_inserts"] == 0.0
        assert on.stats["direct_inserts"] >= 1.0
        assert on.stats["nets"] < off.stats["nets"], "a direct insert must delete a net"
        assert on.stats["belt_tiles"] < off.stats["belt_tiles"], (
            f"direct insertion kept {on.stats['belt_tiles']:.0f} belt tiles versus "
            f"{off.stats['belt_tiles']:.0f} without it"
        )

    def test_a_direct_inserted_pair_still_validates(self) -> None:
        p, _ = self._stacked(two_stage_spec(), direct=True)
        assert p.stats["direct_inserts"] >= 1.0
        report = validate.validate(p, expect_power=False)
        assert report.ok, "\n".join(f"{f.check}: {f.message}" for f in report.errors[:5])

    def test_direct_insert_sorters_obey_reach_and_stay_on_one_level(self) -> None:
        p, _ = self._stacked(two_stage_spec(), direct=True)
        assert p.stats["direct_inserts"] >= 1.0
        for b in p.buildings:
            if not catalog.is_sorter(b.item_id):
                continue
            assert b.x2 is not None and b.y2 is not None
            span = abs(b.x - b.x2) + abs(b.y - b.y2)
            assert 1 <= span <= catalog.SORTER_MAX_REACH
            assert b.z == (b.z2 or 0), "sorters never span altitudes"

    def test_the_sweep_prefers_area_over_direct_insertion(self) -> None:
        """Pins the post-cleanup trade, so a later change has to argue with it.

        The sweep and the explicitly stacked alternative both realize the
        direct insert.  Certified boundary cleanup now removes the structural
        belt leaves around the smaller swept pack as well, so density no longer
        trades against belt count: the chosen pack is both smaller and uses
        fewer belts.  Reintroducing the old assertion would force weightless
        belts merely to preserve a historical trade that no longer exists.
        """
        spec = two_stage_spec()
        swept = FreeformLayout(
            band_policy=BandPolicy("portable"),
            direct_insert=True,
            workers=DETERMINISTIC_WORKERS,
        ).lay_out(spec, time_budget_s=0.5)
        stacked, _ = self._stacked(spec, direct=True)

        assert stacked.stats["direct_inserts"] >= 1.0
        assert swept.stats["direct_inserts"] >= 1.0
        assert swept.area < stacked.area, (
            "the sweep must choose the smaller direct pack"
        )
        assert swept.stats["belt_tiles"] < stacked.stats["belt_tiles"], (
            "certified cleanup should make the smaller direct pack use fewer belts "
            "than the explicitly stacked direct alternative"
        )


def test_promised_direct_candidates_have_an_occupied_collision_clear_alignment() -> None:
    spec = two_stage_spec()
    candidates = _direct_net_candidates(plan_strips(spec, strip_len=6), spec)

    assert candidates
    assert all(candidate.origin_deltas for candidate in candidates.values())


def test_unrealized_promised_direct_is_typed_evidence_not_a_restored_net(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec, strip_len=6)
    candidates = _direct_net_candidates(strips, spec)
    pack = _pack(
        strips,
        height=sum(strip.height + 1 for strip in strips),
        width_bound=max(strip.width + 1 for strip in strips) * 2,
        time_budget_s=0.5,
        direct_candidates=candidates,
        workers=DETERMINISTIC_WORKERS,
    )
    assert pack is not None and pack.direct
    monkeypatch.setattr(freeform, "_bridge", lambda *_args, **_kwargs: None)

    prepared = _prepare_routing_problem(
        spec,
        strips,
        pack,
        power=False,
        policy=BandPolicy("portable"),
    )

    assert prepared.promised_direct == pack.direct
    assert prepared.realized_direct == frozenset()
    assert prepared.preparation_failures
    assert all(
        failure.kind is RouteFailureKind.STATIC_ACCESS
        for failure in prepared.preparation_failures
    )
    routed_ids = {
        (
            net.net_id.source_strip,
            net.net_id.destination_strip,
            net.net_id.item,
            net.net_id.cargo_domain,
        )
        for net in prepared.nets
    }
    assert not {
        (
            direct.source_strip,
            direct.destination_strip,
            direct.item,
            direct.cargo_domain,
        )
        for direct in prepared.promised_direct
    } & routed_ids


def test_every_promised_direct_is_realized_direct() -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec, strip_len=6)
    candidates = _direct_net_candidates(strips, spec)
    pack = _pack(
        strips,
        height=sum(strip.height + 1 for strip in strips),
        width_bound=max(strip.width + 1 for strip in strips) * 2,
        time_budget_s=0.5,
        direct_candidates=candidates,
        workers=DETERMINISTIC_WORKERS,
    )
    assert pack is not None and pack.direct

    result = _build(
        spec,
        strips,
        pack,
        power=False,
        route=True,
        policy=BandPolicy("portable"),
    )

    assert result.routing.status is DetailedRouteStatus.ROUTED
    assert result.promised_direct == result.realized_direct == pack.direct


def test_pack_attempt_retains_complete_failed_attempt_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routing = _routing_failures(RouteFailureKind.STATIC_ACCESS)
    result, _seen, attempts = _sweep_after_first_routing(
        monkeypatch,
        routing,
        arrangements=1,
    )

    assert result is None
    assert len(attempts) == 1
    attempt = attempts[0]
    assert isinstance(attempt, freeform.PackAttempt)
    assert attempt.origins == ((0, 0), (10, 0))
    assert attempt.compact_width == 20
    assert attempt.height == 20
    assert attempt.outline == tuple(_box(strip) for strip in plan_strips(two_stage_spec()))
    assert attempt.routing is routing
    assert attempt.static_access == routing.failures
    assert attempt.promised_direct == frozenset()
    assert attempt.realized_direct == frozenset()
    changed_outline = (
        (attempt.outline[0][0] + 1, attempt.outline[0][1]),
        *attempt.outline[1:],
    )
    changed_attempt = replace(attempt, outline=changed_outline)
    assert changed_attempt != attempt
    assert len({attempt, changed_attempt}) == 2, (
        "a different physical strip outline must not reuse exact-assignment identity"
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        attempt.height = 21  # type: ignore[misc]


class TestObjectiveStaysLexicographic:
    """Width must outrank the tie-break tier absolutely.

    Blending them is what made *more* solver time produce *worse* area, since the
    blended proxy was anti-correlated with the metric actually reported. The
    direct-insert reward joins the tie-break tier, so the cap has to grow with it
    or the property silently lapses.
    """

    @pytest.mark.parametrize(
        ("n_terms", "width_bound", "height", "n_direct"),
        [(0, 8, 8, 0), (22, 64, 40, 11), (2, 4, 4, 1), (100, 500, 300, 250)],
    )
    def test_one_tile_of_width_outranks_the_entire_tie_break_tier(
        self, n_terms: int, width_bound: int, height: int, n_direct: int
    ) -> None:
        cap = tie_break_cap(n_terms, width_bound=width_bound, height=height, n_direct=n_direct)
        worst = n_terms * (width_bound + height) + MU_DIRECT * n_direct
        assert cap > worst, "a width saving must beat every possible tie-break saving"

    def test_the_cap_accounts_for_the_direct_insert_reward(self) -> None:
        """A cap ignoring direct inserts would let them buy width. Pin that."""
        without = tie_break_cap(4, width_bound=20, height=10, n_direct=0)
        with_di = tie_break_cap(4, width_bound=20, height=10, n_direct=7)
        assert with_di > without
        assert with_di - without == MU_DIRECT * 7


def _routing_failures(
    *kinds: RouteFailureKind,
    exhaustive: bool = False,
) -> DetailedRouteResult:
    failures = tuple(
        NetFailure(
            NetId(0, 1, f"item-{ordinal}", NetRole.INTERNAL, ordinal),
            kind,
            (),
            (),
            0,
        )
        for ordinal, kind in enumerate(kinds)
    )
    status = (
        DetailedRouteStatus.BUDGET
        if RouteFailureKind.BUDGET in kinds
        else (DetailedRouteStatus.STRANDED if failures else DetailedRouteStatus.ROUTED)
    )
    arguments = (status, (), failures, 0, 0)
    if exhaustive:
        return DetailedRouteResult(*arguments, exhaustive=True)
    return DetailedRouteResult(*arguments)


def _feedback_bearing_routing(
    count: int = 1,
) -> DetailedRouteResult:
    failures = tuple(
        NetFailure(
            NetId(0, 1, f"feedback-{ordinal}", NetRole.INTERNAL, ordinal),
            RouteFailureKind.SEALED_POCKET,
            ((5 + ordinal, 5, 0),),
            (),
            1,
            source=(1, 1 + ordinal, 0),
            destination=(11, 1 + ordinal, 0),
        )
        for ordinal in range(count)
    )
    return DetailedRouteResult(
        DetailedRouteStatus.STRANDED,
        (),
        failures,
        1,
        count,
    )


def _proof_attempt(
    routing: DetailedRouteResult,
    strips: list[Strip],
    *,
    origins: tuple[tuple[int, int], ...] | None = None,
    promised_direct: frozenset[DirectInsertId] = frozenset(),
    realized_direct: frozenset[DirectInsertId] = frozenset(),
) -> freeform.PackAttempt:
    return freeform.PackAttempt(
        origins=origins
        or tuple((index * 10, 0) for index in range(len(strips))),
        compact_width=20,
        height=20,
        outline=tuple(_box(strip) for strip in strips),
        routing=routing,
        budget_stage=(
            freeform._BuildBudgetStage.ROUTING
            if routing.status is DetailedRouteStatus.BUDGET
            else None
        ),
        static_access=tuple(
            failure
            for failure in routing.failures
            if failure.kind is RouteFailureKind.STATIC_ACCESS
        ),
        promised_direct=promised_direct,
        realized_direct=realized_direct,
        direct_candidates=freeform._direct_candidate_snapshot(
            strips,
            two_stage_spec(),
            enabled=True,
        ),
    )


def test_static_access_without_an_independent_relation_proof_is_evidence_only() -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec)
    attempt = _proof_attempt(
        _routing_failures(RouteFailureKind.STATIC_ACCESS),
        strips,
    )

    local, exact = freeform._proof_scoped_no_goods(attempt, strips)

    assert local == ()
    assert exact is None


def test_static_access_structurally_impossible_direct_creates_only_local_no_good() -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec)
    (source, destination), candidate = next(
        iter(_direct_net_candidates(strips, spec).items())
    )
    direct = DirectInsertId(
        source,
        destination,
        candidate.item,
        candidate.cargo_domain,
    )
    origins = [(index * 10, 0) for index in range(len(strips))]
    origins[destination] = (
        origins[source][0] + max(candidate.origin_deltas) + 1,
        origins[source][1] + 1,
    )
    routing = DetailedRouteResult(
        DetailedRouteStatus.STRANDED,
        (),
        (
            NetFailure(
                direct.net_id,
                RouteFailureKind.STATIC_ACCESS,
                (),
                (),
                0,
            ),
        ),
        0,
        0,
    )
    attempt = _proof_attempt(
        routing,
        strips,
        origins=tuple(origins),
        promised_direct=frozenset({direct}),
    )

    local, exact = freeform._proof_scoped_no_goods(attempt, strips)

    assert len(local) == 1
    assert local[0].direct_id == direct
    assert local[0].delta_x == origins[destination][0] - origins[source][0]
    assert local[0].delta_y == origins[destination][1] - origins[source][1]
    assert exact is None

def test_retained_direct_candidates_preserve_legal_relation_parity() -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec)
    (source, destination), candidate = next(
        iter(_direct_net_candidates(strips, spec).items())
    )
    direct = DirectInsertId(
        source,
        destination,
        candidate.item,
        candidate.cargo_domain,
    )
    origins = [(index * 10, 0) for index in range(len(strips))]
    origins[destination] = (
        origins[source][0] + candidate.origin_deltas[0],
        origins[source][1] + 1 + candidate.prod_row - candidate.cons_row,
    )
    attempt = _proof_attempt(
        _routing_failures(RouteFailureKind.STATIC_ACCESS),
        strips,
        origins=tuple(origins),
        promised_direct=frozenset({direct}),
    )

    assert freeform._proof_scoped_no_goods(attempt, strips) == ((), None)


def test_retained_direct_candidates_reject_a_different_strip_plan() -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec)
    attempt = _proof_attempt(
        _routing_failures(RouteFailureKind.STATIC_ACCESS),
        strips,
    )
    replanned = plan_strips(spec, strip_len=1)

    with pytest.raises(ValueError, match="different strip plan"):
        freeform._proof_scoped_no_goods(attempt, replanned)


def test_exhaustive_non_budget_failure_creates_full_assignment_no_good() -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec)
    attempt = _proof_attempt(
        _routing_failures(
            RouteFailureKind.CONGESTION_WALL,
            exhaustive=True,
        ),
        strips,
    )

    local, exact = freeform._proof_scoped_no_goods(attempt, strips)

    assert local == ()
    assert exact is not None
    assert exact.height == attempt.height
    assert exact.outline == attempt.outline
    assert exact.width == attempt.compact_width
    assert exact.origins == attempt.origins
    assert exact.evidence
    assert all(failure.check == "route.exhaustive" for failure in exact.evidence)


@pytest.mark.parametrize(
    "routing",
    [
        pytest.param(
            _routing_failures(RouteFailureKind.CONGESTION_WALL),
            id="non-exhaustive",
        ),
        pytest.param(
            _routing_failures(RouteFailureKind.BUDGET),
            id="budget",
        ),
    ],
)
def test_unproved_and_budget_failures_do_not_exclude_geometry(
    routing: DetailedRouteResult,
) -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec)
    attempt = _proof_attempt(routing, strips)

    assert freeform._proof_scoped_no_goods(attempt, strips) == ((), None)




def _sweep_after_first_routing(
    monkeypatch: pytest.MonkeyPatch,
    first_routing: DetailedRouteResult,
    *,
    arrangements: int = 2,
    forbid_finalization: bool = False,
    heights: tuple[int, ...] = (20,),
    subsequent_routing: DetailedRouteResult | None = None,
    distinct_arrangements: bool = True,
    deadline: float | None = None,
    finalizer: Callable[..., Placement] | None = None,
    certifier: Callable[..., validate.Report] | None = None,
) -> tuple[Placement | None, list[tuple[int, int]], list[freeform.PackAttempt]]:
    spec = two_stage_spec()
    strips = plan_strips(spec)
    packs = {
        (height, arrangement): freeform._Pack(
            at={
                index: (
                    index * 10 + (arrangement if distinct_arrangements else 0),
                    0,
                )
                for index in range(len(strips))
            },
            width=20,
            height=height,
            status="test",
        )
        for height in heights
        for arrangement in range(arrangements)
    }
    routed = subsequent_routing or _routing_failures()
    seen: list[tuple[int, int]] = []

    def pack(
        *_args: object,
        height: int,
        arrangement: int,
        **_kwargs: object,
    ) -> freeform._Pack:
        seen.append((height, arrangement))
        return packs[height, arrangement]

    def build(
        _spec: BuildSpec,
        _strips: list[Strip],
        pack: freeform._Pack,
        **_kwargs: object,
    ) -> _BuildResult:
        routing = first_routing if pack is packs[heights[0], 0] else routed
        placement = (
            Placement(buildings=(), stats={"belt_tiles": 0.0})
            if routing.status is DetailedRouteStatus.ROUTED
            else None
        )
        return _BuildResult(
            placement=placement,
            routing=routing,
            budget_stage=(
                freeform._BuildBudgetStage.ROUTING
                if routing.status is DetailedRouteStatus.BUDGET
                else None
            ),
            towers=(),
        )

    monkeypatch.setattr(freeform, "_candidate_heights", lambda _strips: list(heights))
    monkeypatch.setattr(
        freeform,
        "_greedy_pack",
        lambda _strips, height: packs.get((height, 0), packs[heights[0], 0]),
    )
    monkeypatch.setattr(freeform, "_pack", pack)
    monkeypatch.setattr(freeform, "_build", build)
    if forbid_finalization:
        monkeypatch.setattr(
            validate,
            "certify",
            lambda *_args, **_kwargs: pytest.fail(
                "a budgeted build reached validation"
            ),
        )
        monkeypatch.setattr(
            finalize,
            "finalize_placement",
            lambda *_args, **_kwargs: pytest.fail(
                "a budgeted build reached projection"
            ),
        )
    else:
        monkeypatch.setattr(
            validate,
            "certify",
            (
                certifier
                if certifier is not None
                else lambda *_args, **_kwargs: validate.Report(findings=())
            ),
        )
        monkeypatch.setattr(
            finalize,
            "finalize_placement",
            finalizer
            if finalizer is not None
            else lambda placement, _policy, **_kwargs: placement,
        )

    attempts: list[freeform.PackAttempt] = []
    result = FreeformLayout(
        band_policy=BandPolicy("portable"),
        arrangements=arrangements,
    )._sweep(spec, strips, 1.0, deadline=deadline, attempts=attempts)
    return result, seen, attempts


def test_fully_routed_attempt_crossing_certification_deadline_is_not_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = 0.0

    def monotonic() -> float:
        return clock

    def expire_in_certification(
        *_args: object,
        **_kwargs: object,
    ) -> validate.Report:
        nonlocal clock
        clock += 0.2
        return validate.Report(findings=())

    monkeypatch.setattr(freeform.time, "monotonic", monotonic)
    result, _seen, attempts = _sweep_after_first_routing(
        monkeypatch,
        _routing_failures(),
        arrangements=1,
        deadline=0.1,
        certifier=expire_in_certification,
        finalizer=lambda placement, *_args, **_kwargs: replace(
            placement,
            frame=AreaFrame(1, 1, 4, (4,), False),
        ),
    )

    assert result is None
    assert len(attempts) == 1
    assert attempts[0].routing.status is DetailedRouteStatus.ROUTED
    assert attempts[0].budget_stage is freeform._BuildBudgetStage.CERTIFICATION


def test_terminal_refusal_names_completion_stage_after_every_net_wired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = 0.0

    def monotonic() -> float:
        return clock

    def expire_after_routing(
        _layout: FreeformLayout,
        _spec: BuildSpec,
        strips: list[Strip],
        _sweep_s: float,
        _deadline: float,
        _budget: dict[str, int],
        rejected: list[freeform._RefusalFinding],
        attempts: list[freeform.PackAttempt],
    ) -> None:
        nonlocal clock
        rejected.append(
            validate.Finding(
                "flow.conservation",
                validate.Severity.ERROR,
                "earlier routed pack was invalid",
                (),
                {},
            )
        )
        routed = _proof_attempt(_routing_failures(), strips)
        attempts.append(
            replace(
                routed,
                budget_stage=freeform._BuildBudgetStage.CERTIFICATION,
            )
        )
        clock = 2.0
        return None

    monkeypatch.setattr(freeform.time, "monotonic", monotonic)
    monkeypatch.setattr(FreeformLayout, "_sweep", expire_after_routing)

    with pytest.raises(NoValidLayout) as caught:
        FreeformLayout(band_policy=BandPolicy("portable")).lay_out(
            two_stage_spec(),
            time_budget_s=1.0,
        )

    reason = str(caught.value)
    assert "no completed packing" in reason
    assert "at least one wired every net" in reason
    assert "deadline passed during CERTIFICATION" in reason
    assert "earlier routed pack was invalid" in reason
    assert "no wired packing" not in reason


def test_sweep_validates_exact_compacted_and_finalized_placement_before_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = validate.Report(findings=())
    compacted = Placement(
        buildings=(),
        stats={"belt_tiles": 0.0, "boundary_belts_removed": 1.0},
    )
    stages: list[str] = []

    @dataclasses.dataclass(frozen=True, slots=True)
    class CompactionResult:
        placement: Placement
        report: validate.Report | None

    def compact(
        _placement: Placement,
        _spec: BuildSpec,
        *,
        expect_power: bool,
        cancelled: Callable[[], bool] | None = None,
    ) -> CompactionResult:
        assert cancelled is not None
        assert not cancelled()
        stages.append("compaction")
        return CompactionResult(compacted, report)

    def finish(
        placement: Placement,
        _policy: BandPolicy,
        **_kwargs: object,
    ) -> Placement:
        assert placement is compacted
        stages.append("finalization")
        return replace(
            placement,
            frame=AreaFrame(1, 1, 4, (4,), False),
        )

    def certify(
        placement: Placement,
        *_args: object,
        **_kwargs: object,
    ) -> validate.Report:
        assert placement.frame is not None
        assert placement.completion is None
        stages.append("validation")
        return validate.Report(findings=())

    monkeypatch.setattr(
        finalize,
        "compact_open_boundary_belts_certified",
        compact,
        raising=False,
    )
    result, _seen, attempts = _sweep_after_first_routing(
        monkeypatch,
        _routing_failures(),
        arrangements=1,
        deadline=time.monotonic() + 10.0,
        certifier=certify,
        finalizer=finish,
    )

    assert result is not None
    assert result.buildings == compacted.buildings
    assert result.completion is PlacementCompletion.COMPACTED_AND_FINALIZED
    assert stages == ["compaction", "finalization", "validation"]
    assert len(attempts) == 1
    assert attempts[0].budget_stage is None


def test_sweep_reserves_compaction_finalization_and_validation_as_exact_sum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = 0.0
    compactions = 0

    def monotonic() -> float:
        return clock

    def compact(
        placement: Placement,
        _spec: BuildSpec,
        **_kwargs: object,
    ) -> finalize.BoundaryCompactionResult:
        nonlocal clock, compactions
        compactions += 1
        clock += 2.0
        return finalize.BoundaryCompactionResult(placement, None)

    def finish(
        placement: Placement,
        _policy: BandPolicy,
        **_kwargs: object,
    ) -> Placement:
        nonlocal clock
        clock += 3.0
        return replace(
            placement,
            frame=AreaFrame(1, 1, 4, (4,), False),
        )

    def reject(
        *_args: object,
        **_kwargs: object,
    ) -> validate.Report:
        nonlocal clock
        clock += 2.0
        return validate.Report(
            findings=(
                validate.Finding(
                    "flow.conservation",
                    validate.Severity.ERROR,
                    "forced",
                    (),
                    {},
                ),
            )
        )

    monkeypatch.setattr(freeform.time, "monotonic", monotonic)
    monkeypatch.setattr(finalize, "compact_open_boundary_belts_certified", compact)
    result, seen, attempts = _sweep_after_first_routing(
        monkeypatch,
        _routing_failures(),
        arrangements=1,
        heights=(20, 21),
        deadline=13.0,
        finalizer=finish,
        certifier=reject,
    )

    assert result is None
    assert seen == [(20, 0)]
    assert compactions == 1
    assert len(attempts) == 1


def test_sweep_finalizer_receives_search_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[dict[str, object]] = []

    def finish(
        placement: Placement,
        _policy: BandPolicy,
        **kwargs: object,
    ) -> Placement:
        observed.append(kwargs)
        return replace(
            placement,
            frame=AreaFrame(1, 1, 4, (4,), False),
        )

    result, _seen, attempts = _sweep_after_first_routing(
        monkeypatch,
        DetailedRouteResult(
            DetailedRouteStatus.ROUTED,
            (),
            (),
            0,
            0,
        ),
        arrangements=1,
        deadline=time.monotonic() + 10.0,
        finalizer=finish,
    )

    assert len(observed) == 1
    cancelled = observed[0]["cancelled"]
    assert callable(cancelled)
    assert not cancelled()
    assert result is not None
    assert result.completion is PlacementCompletion.COMPACTED_AND_FINALIZED
    assert len(attempts) == 1
    assert attempts[0].budget_stage is None


def test_sweep_reserves_measured_certify_and_finalize_cost_before_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = 0.0

    def monotonic() -> float:
        return clock

    def certify(*_args: object, **_kwargs: object) -> validate.Report:
        nonlocal clock
        clock += 0.2
        return validate.Report(findings=())

    def finish(
        placement: Placement,
        _policy: BandPolicy,
        **_kwargs: object,
    ) -> Placement:
        nonlocal clock
        clock += 0.2
        return placement

    monkeypatch.setattr(freeform.time, "monotonic", monotonic)
    result, seen, _attempts = _sweep_after_first_routing(
        monkeypatch,
        DetailedRouteResult(
            DetailedRouteStatus.ROUTED,
            (),
            (),
            0,
            0,
        ),
        arrangements=1,
        heights=(20, 21),
        deadline=0.6,
        certifier=certify,
        finalizer=finish,
    )

    assert result is not None
    assert seen == [(20, 0)]


def test_exact_one_net_feedback_admits_the_next_configured_arrangement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, seen, attempts = _sweep_after_first_routing(
        monkeypatch,
        _feedback_bearing_routing(),
    )

    assert result is not None
    assert seen == [(20, 0), (20, 1)]
    assert [attempt.routing.failed_count for attempt in attempts] == [1, 0]

def test_feedback_retry_does_not_reroute_the_same_assignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, seen, attempts = _sweep_after_first_routing(
        monkeypatch,
        _feedback_bearing_routing(),
        subsequent_routing=DetailedRouteResult(
            DetailedRouteStatus.ROUTED,
            (),
            (),
            1,
            1,
        ),
        distinct_arrangements=False,
    )

    assert result is None
    assert seen == [(20, 0), (20, 1)]
    assert [attempt.routing.failed_count for attempt in attempts] == [1]


def test_proof_scoped_near_miss_promotes_existing_feedback_retry_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _result, seen, _attempts = _sweep_after_first_routing(
        monkeypatch,
        _feedback_bearing_routing(),
        heights=(20, 21),
    )

    assert seen[:2] == [(20, 0), (20, 1)]


@pytest.mark.parametrize(
    "routing",
    [
        pytest.param(_feedback_bearing_routing(2), id="two-failures"),
        pytest.param(
            _routing_failures(RouteFailureKind.STATIC_ACCESS),
            id="static-with-empty-feedback",
        ),
    ],
)
def test_proof_scoped_ineligible_failures_preserve_base_height_order(
    monkeypatch: pytest.MonkeyPatch,
    routing: DetailedRouteResult,
) -> None:
    _result, seen, _attempts = _sweep_after_first_routing(
        monkeypatch,
        routing,
        heights=(20, 21),
    )

    assert seen[:2] == [(20, 0), (21, 0)]


def test_unaffordable_feedback_retry_preserves_later_base_height(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(freeform, "_room_for_another", lambda *_args: False)

    result, seen, _attempts = _sweep_after_first_routing(
        monkeypatch,
        _feedback_bearing_routing(),
        heights=(20, 21),
    )

    assert result is not None
    assert seen[:2] == [(20, 0), (21, 0)]

def test_feedback_retry_admission_uses_measured_nonzero_candidate_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = itertools.count()
    measured: list[float] = []

    monkeypatch.setattr(freeform.time, "monotonic", lambda: float(next(ticks)))

    def refuse_retry(
        _deadline: float | None,
        _soft: float,
        candidate_s: float,
    ) -> bool:
        measured.append(candidate_s)
        return False

    monkeypatch.setattr(freeform, "_room_for_another", refuse_retry)

    _result, seen, _attempts = _sweep_after_first_routing(
        monkeypatch,
        _feedback_bearing_routing(),
        heights=(20, 21),
    )

    assert seen[:2] == [(20, 0), (21, 0)]
    assert measured
    assert measured[0] > 0.0



def test_admitted_feedback_retry_is_not_rechecked_at_deadline_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    affordability = iter((True, False))
    monkeypatch.setattr(
        freeform,
        "_room_for_another",
        lambda *_args: next(affordability),
    )

    result, seen, _attempts = _sweep_after_first_routing(
        monkeypatch,
        _feedback_bearing_routing(),
        heights=(20, 21),
    )

    assert result is not None
    assert seen[:2] == [(20, 0), (20, 1)]


def test_failed_assignments_enumerate_direct_candidates_once_per_strip_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enumerations = 0
    enumerate_candidates = freeform._direct_net_candidates

    def counted_candidates(
        strips: list[Strip],
        spec: BuildSpec,
    ) -> dict[tuple[int, int], object]:
        nonlocal enumerations
        enumerations += 1
        return enumerate_candidates(strips, spec)

    monkeypatch.setattr(freeform, "_direct_net_candidates", counted_candidates)
    failure = _routing_failures(RouteFailureKind.CONGESTION_WALL)

    result, seen, _attempts = _sweep_after_first_routing(
        monkeypatch,
        failure,
        arrangements=1,
        heights=(20, 21, 22),
        subsequent_routing=failure,
    )

    assert result is None
    assert seen == [(20, 0), (21, 0), (22, 0)]
    assert enumerations == 1

def test_admitted_feedback_retry_cannot_cascade_to_a_third_arrangement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = _feedback_bearing_routing()

    result, seen, attempts = _sweep_after_first_routing(
        monkeypatch,
        failure,
        arrangements=3,
        subsequent_routing=failure,
    )

    assert result is None
    assert seen == [(20, 0), (20, 1)]
    assert [attempt.routing.failed_count for attempt in attempts] == [1, 1]



def test_fifteen_strip_pack_uses_reproducible_solver_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = plan_strips(two_stage_spec())
    strips = [base[index % len(base)] for index in range(15)]
    seed = freeform._Pack(
        at={index: (0, 0) for index in range(len(strips))},
        width=20,
        height=20,
        status="seed",
    )
    seen_solver_modes: list[tuple[int, bool]] = []

    def pack(
        *_args: object,
        workers: int,
        deterministic: bool,
        **_kwargs: object,
    ) -> None:
        seen_solver_modes.append((workers, deterministic))
        return None

    monkeypatch.setattr(
        freeform,
        "_band_policy_candidate_heights",
        lambda _strips, _policy: (20,),
    )
    monkeypatch.setattr(freeform, "_greedy_pack", lambda *_args: seed)
    monkeypatch.setattr(freeform, "_pack", pack)

    result = FreeformLayout(
        band_policy=BandPolicy("portable"),
        workers=8,
        arrangements=1,
    )._sweep(two_stage_spec(), strips, 1.0)

    assert result is None
    assert seen_solver_modes == [(1, True)]


def test_route_aware_height_order_preserves_exact_candidate_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec)
    original_heights = (20, 40, 30)
    widths = {20: 50, 40: 35, 30: 35}
    seeds = {
        height: freeform._Pack(
            at={index: (index * 10, 0) for index in range(len(strips))},
            width=widths[height],
            height=height,
            status="seed",
        )
        for height in original_heights
    }
    seen: list[tuple[int, int, int]] = []

    def pack(
        *_args: object,
        height: int,
        seed: freeform._Pack,
        **_kwargs: object,
    ) -> freeform._Pack:
        assert seed is seeds[height]
        seen.append((height, seed.width, seed.height))
        return seed

    failed = _routing_failures(RouteFailureKind.BUDGET)

    def build(*_args: object, **_kwargs: object) -> _BuildResult:
        return _BuildResult(
            placement=None,
            routing=failed,
            budget_stage=freeform._BuildBudgetStage.ROUTING,
            towers=(),
        )

    monkeypatch.setattr(
        freeform,
        "_band_policy_candidate_heights",
        lambda _strips, _policy: original_heights,
    )
    monkeypatch.setattr(
        freeform,
        "_greedy_pack",
        lambda _strips, height: seeds[height],
    )
    monkeypatch.setattr(freeform, "_pack", pack)
    monkeypatch.setattr(
        freeform,
        "_height_seed",
        lambda _strips: original_heights[0],
    )
    monkeypatch.setattr(freeform, "_build", build)

    result = FreeformLayout(
        band_policy=BandPolicy("portable"),
        arrangements=1,
    )._sweep(spec, strips, 1.0)

    assert result is None
    assert [height for height, _width, _seed_height in seen] == [30, 40, 20]
    assert len(seen) == len(original_heights)
    assert {height for height, _width, _seed_height in seen} == set(
        original_heights
    )
    assert all(height == seed_height for height, _width, seed_height in seen)


@pytest.mark.parametrize(
    ("seed_width", "uses_seed"),
    ((22, True), (23, False)),
)
def test_first_warm_start_substitution_is_width_bounded_and_attempt_neutral(
    monkeypatch: pytest.MonkeyPatch,
    seed_width: int,
    uses_seed: bool,
) -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec)
    height = 20
    compact = freeform._Pack(
        at={index: (index * 10, 0) for index in range(len(strips))},
        width=20,
        height=height,
        status="compact",
    )
    seed = freeform._Pack(
        at={index: (index * 10 + 1, 0) for index in range(len(strips))},
        width=seed_width,
        height=height,
        status="seed",
    )
    routed = _routing_failures(exhaustive=True)
    placement = Placement(buildings=(), stats={"belt_tiles": 0.0})
    pack_calls = 0
    routed_packs: list[freeform._Pack] = []
    pack_kwargs: dict[str, object] = {}

    def pack(*_args: object, **kwargs: object) -> freeform._Pack:
        nonlocal pack_calls
        pack_calls += 1
        pack_kwargs.update(kwargs)
        return compact

    def build(
        _spec: BuildSpec,
        _strips: list[Strip],
        selected: freeform._Pack,
        **_kwargs: object,
    ) -> _BuildResult:
        routed_packs.append(selected)
        return _BuildResult(
            placement=placement,
            routing=routed,
            budget_stage=None,
            towers=(),
        )

    monkeypatch.setattr(
        freeform,
        "_band_policy_candidate_heights",
        lambda _strips, _policy: (height,),
    )
    monkeypatch.setattr(freeform, "_greedy_pack", lambda *_args: seed)
    monkeypatch.setattr(freeform, "_pack", pack)
    monkeypatch.setattr(freeform, "_build", build)
    monkeypatch.setattr(
        finalize,
        "compact_open_boundary_belts_certified",
        lambda candidate, *_args, **_kwargs: finalize.BoundaryCompactionResult(
            candidate,
            None,
        ),
    )
    monkeypatch.setattr(
        finalize,
        "finalize_placement",
        _identity_finalizer,
    )
    monkeypatch.setattr(
        validate,
        "certify",
        lambda *_args, **_kwargs: validate.Report(findings=()),
    )

    result = FreeformLayout(
        band_policy=BandPolicy("portable"),
        arrangements=1,
    )._sweep(spec, strips, 1.0)

    assert result is not None
    assert pack_calls == len(routed_packs) == 1
    assert pack_kwargs["stop_when_seed_admissible"] is True
    selected = routed_packs[0]
    expected = seed if uses_seed else compact
    assert (selected.at, selected.width, selected.height) == (
        expected.at,
        expected.width,
        expected.height,
    )
    assert (seed.width <= freeform._width_slack_cap(compact.width)) is uses_seed


def test_width_slack_uses_exact_integer_ceiling_at_decimal_boundaries() -> None:
    assert freeform._width_slack_cap(50) == 55
    assert freeform._width_slack_cap(51) == 57


def test_proof_scoped_route_feedback_uses_only_configured_width_slack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec)
    height = 20
    compact = freeform._Pack(
        at={index: (index * 10, 0) for index in range(len(strips))},
        width=20,
        height=height,
        status="compact",
    )
    alternative = freeform._Pack(
        at={index: (index * 10 + index, 0) for index in range(len(strips))},
        width=22,
        height=height,
        status="feedback",
    )
    failed = _routing_failures(
        RouteFailureKind.CONGESTION_WALL,
        exhaustive=True,
    )
    routed = _routing_failures(exhaustive=True)
    calls: list[dict[str, object]] = []

    def pack(
        *_args: object,
        arrangement: int,
        **kwargs: object,
    ) -> freeform._Pack:
        calls.append({"arrangement": arrangement, **kwargs})
        return compact if arrangement == 0 else alternative

    def build(
        _spec: BuildSpec,
        _strips: list[Strip],
        pack: freeform._Pack,
        **_kwargs: object,
    ) -> _BuildResult:
        routing = failed if pack is compact else routed
        placement = (
            None
            if routing.failed_count
            else Placement(buildings=(), stats={"belt_tiles": 0.0})
        )
        return _BuildResult(
            placement=placement,
            routing=routing,
            budget_stage=None,
            towers=(),
        )

    monkeypatch.setattr(freeform, "_candidate_heights", lambda _strips: [height])
    monkeypatch.setattr(freeform, "_greedy_pack", lambda _strips, _height: compact)
    monkeypatch.setattr(freeform, "_pack", pack)
    monkeypatch.setattr(freeform, "_build", build)
    monkeypatch.setattr(
        validate,
        "certify",
        lambda *_args, **_kwargs: validate.Report(findings=()),
    )
    monkeypatch.setattr(
        finalize,
        "finalize_placement",
        _identity_finalizer,
    )

    attempts: list[freeform.PackAttempt] = []
    result = FreeformLayout(
        band_policy=BandPolicy("portable"),
        arrangements=2,
    )._sweep(spec, strips, 1.0, attempts=attempts)

    assert result is not None
    assert [call["arrangement"] for call in calls] == [0, 1]
    assert calls[1]["width_bound"] == freeform._width_slack_cap(compact.width)
    feedback = calls[1]["feedback"]
    assert isinstance(feedback, FeedbackState)
    assert feedback.net_weight[failed.failures[0].net_id] == 1.0
    exact_no_goods = calls[1]["exact_pack_no_goods"]
    assert isinstance(exact_no_goods, tuple) and len(exact_no_goods) == 1
    rejected = exact_no_goods[0]
    assert isinstance(rejected, freeform.ExactPackNoGood)
    assert rejected.origins == tuple(
        compact.at[index] for index in range(len(compact.at))
    )
    assert attempts[0].origins != attempts[1].origins


def test_route_feedback_objective_keeps_exact_net_terms_and_hot_walls() -> None:
    first = NetId(
        0,
        1,
        "ore",
        NetRole.INTERNAL,
        0,
        cargo_domain=CargoDomain.UNSPRAYED,
    )
    second = NetId(
        0,
        1,
        "ore",
        NetRole.INTERNAL,
        1,
        cargo_domain=CargoDomain.REQUIRES_SPRAY,
    )
    endpoints = {
        first: ((4, 2, 0), (1, 3, 0)),
        second: ((7, 5, 0), (2, 1, 0)),
    }
    cold = FeedbackState(
        outline=(60, 20),
        net_weight={first: 1.0, second: 3.0},
        cell_history={},
        endpoint_offsets=endpoints,
    )
    hot = FeedbackState(
        outline=cold.outline,
        net_weight=cold.net_weight,
        cell_history={(12, 5, 0): 2.0},
        endpoint_offsets=endpoints,
        net_cell_history={first: {(12, 5, 0): 2.0}},
    )

    cold_terms = freeform._feedback_objective_evidence(cold, strip_count=2)
    hot_terms = freeform._feedback_objective_evidence(hot, strip_count=2)

    by_net = {term.net_id: term for term in cold_terms}
    assert set(by_net) == {first, second}
    assert {net: term.weight for net, term in by_net.items()} == {
        first: 1,
        second: 3,
    }
    assert by_net[first].source_offset == (4, 2, 0)
    assert by_net[second].source_offset == (7, 5, 0)
    origins = ((0, 0), (20, 0))
    assert freeform._feedback_objective_score(
        hot_terms,
        origins,
        hot.outline,
    ) > freeform._feedback_objective_score(
        cold_terms,
        origins,
        cold.outline,
    )

def test_ground_net_retains_elevated_wall_as_an_exact_cp_term() -> None:
    net = NetId(0, 1, "ore", NetRole.INTERNAL, 0)
    wall = (12, 5, 2)
    feedback = freeform.update_feedback(
        FeedbackState.empty((60, 20)),
        DetailedRouteResult(
            DetailedRouteStatus.STRANDED,
            (),
            (
                NetFailure(
                    net,
                    RouteFailureKind.CONGESTION_WALL,
                    (wall,),
                    (),
                    1,
                    source=(4, 2, 0),
                    destination=(21, 3, 0),
                ),
            ),
            0,
            1,
        ),
        origins=((0, 0), (20, 0)),
    )

    terms = freeform._feedback_objective_evidence(feedback, strip_count=2)

    assert len(terms) == 1
    assert terms[0].source_offset[2] == terms[0].destination_offset[2] == 0
    assert terms[0].hot_cells == ((wall, 1),)


def test_route_feedback_disjoint_walls_create_only_linear_exact_terms() -> None:
    count = 6
    origins = ((0, 0), (20, 0))
    nets = tuple(
        NetId(0, 1, f"item-{index}", NetRole.INTERNAL, index)
        for index in range(count)
    )
    walls = tuple((index + 5, 10, 0) for index in range(count))
    failures = tuple(
        NetFailure(
            net,
            RouteFailureKind.CONGESTION_WALL,
            (wall,),
            (),
            1,
            source=(2, index + 1, 0),
            destination=(22, index + 1, 0),
        )
        for index, (net, wall) in enumerate(zip(nets, walls, strict=True))
    )
    feedback = freeform.update_feedback(
        FeedbackState.empty((40, 20)),
        DetailedRouteResult(
            DetailedRouteStatus.STRANDED,
            (),
            failures,
            0,
            count,
        ),
        origins=origins,
    )

    terms = freeform._feedback_objective_evidence(feedback, strip_count=2)
    by_net = {term.net_id: term for term in terms}

    assert len(terms) == count
    assert sum(len(term.hot_cells) for term in terms) == count
    assert {
        net: tuple(cell for cell, _history in by_net[net].hot_cells)
        for net in nets
    } == {
        net: (wall,)
        for net, wall in zip(nets, walls, strict=True)
    }


def test_route_feedback_exact_terms_build_a_valid_pack_model() -> None:
    strips = plan_strips(two_stage_spec(), strip_len=6)
    height = sum(_box(strip)[1] for strip in strips)
    seed = _greedy_pack(strips, height)
    net = NetId(0, 1, "ore", NetRole.INTERNAL, 0)
    feedback = FeedbackState(
        outline=(seed.width, height),
        net_weight={net: 1.0},
        cell_history={(0, 0, 0): 1.0},
        endpoint_offsets={net: ((0, 0, 0), (0, 0, 0))},
        net_cell_history={net: {(0, 0, 0): 1.0}},
    )

    packed = _pack(
        strips,
        height=height,
        width_bound=seed.width,
        time_budget_s=0.5,
        direct_candidates={},
        workers=DETERMINISTIC_WORKERS,
        seed=seed,
        feedback=feedback,
    )

    assert packed is not None
    assert packed.width <= seed.width


def test_proof_scoped_feedback_routes_captured_output_products_at_existing_deadline() -> None:
    spec = captured_output_products_spec()
    assert len(plan_strips(spec, strip_len=6)) == 17

    placement = FreeformLayout(
        band_policy=BandPolicy("portable"),
        workers=1,
    ).lay_out(spec, time_budget_s=4.0)

    report = validate.validate(placement, spec, expect_power=True)
    assert report.ok, "\n".join(
        f"{finding.check}: {finding.message}" for finding in report.errors
    )


@pytest.mark.parametrize(
    "first_routing",
    [
        pytest.param(
            _routing_failures(
                RouteFailureKind.SEALED_POCKET,
                RouteFailureKind.BUDGET,
            ),
            id="budget",
        ),
        pytest.param(
            _routing_failures(*(RouteFailureKind.DYNAMIC_ACCESS,) * 4),
            id="four-failures",
        ),
    ],
)
def test_non_rescuable_routing_does_not_admit_an_arrangement(
    monkeypatch: pytest.MonkeyPatch,
    first_routing: DetailedRouteResult,
) -> None:
    result, seen, attempts = _sweep_after_first_routing(monkeypatch, first_routing)

    assert result is None
    assert seen == [(20, 0)]
    assert [attempt.routing.failed_count for attempt in attempts] == [
        len(first_routing.failures)
    ]


def test_budget_routing_never_reaches_validation_or_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, seen, attempts = _sweep_after_first_routing(
        monkeypatch,
        _routing_failures(RouteFailureKind.BUDGET),
        forbid_finalization=True,
    )

    assert result is None
    assert seen == [(20, 0)]
    assert [attempt.routing.failed_count for attempt in attempts] == [1]


def test_a_near_miss_does_not_create_an_unconfigured_arrangement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, seen, attempts = _sweep_after_first_routing(
        monkeypatch,
        _routing_failures(RouteFailureKind.CONGESTION_WALL),
        arrangements=1,
    )

    assert result is None
    assert seen == [(20, 0)]
    assert [attempt.routing.failed_count for attempt in attempts] == [1]


@pytest.mark.parametrize(
    ("deadline_s", "soft_s", "candidate_s", "expected"),
    [
        (600.0, 1.0, 5.0, False),
        (600.0, 30.0, 5.0, True),
        (1.0, 600.0, 5.0, False),
        (None, 30.0, 5.0, True),
        (None, 1.0, 5.0, False),
        (0.001, 0.001, 0.0, True),
    ],
)
def test_arrangement_retry_requires_enough_wall_and_sweep_budget(
    deadline_s: float | None,
    soft_s: float,
    candidate_s: float,
    expected: bool,
) -> None:
    now = time.monotonic()
    deadline = None if deadline_s is None else now + deadline_s
    assert _room_for_another(deadline, now + soft_s, candidate_s) is expected


# --- solver quality --------------------------------------------------------


class TestSolverActuallyRuns:
    def test_solved_path_beats_the_greedy_construction(self) -> None:
        """The failure Strategy A shipped: a fallback wearing a solver's clothes.

        A bake-off comparing two fallbacks is worse than useless, so this asserts
        the solved path is genuinely exercised and genuinely better.

        ``fallback_placement`` is no longer reachable from ``lay_out`` -- it
        calls ``_build(route=False)``, so it never attempts the wiring it once
        claimed to guarantee -- but it is still the construction the solver has
        to beat, so it stays here as the yardstick.
        """
        spec = two_stage_spec()
        solved = FreeformLayout(
            band_policy=BandPolicy("portable"),
        ).lay_out(spec, time_budget_s=2.0)
        greedy = fallback_placement(spec, band_policy=BandPolicy("portable"), power=True)
        assert solved.stats["fallback_used"] == 0.0, "solver silently fell back"
        assert solved.stats["solver_status"] > 0.0, "no CP-SAT status: the pack was not solved"

        # NOT an area comparison any more, and the reason matters. `greedy`
        # calls `_build(route=False)`: it has no belts at all, so it is smaller
        # than any working layout and always will be. Comparing areas would ask
        # the solver to beat a layout that wins by not connecting anything --
        # the exact scoring mistake that made an earlier bake-off pick a build
        # with 119 unrouted nets as the densest on offer.
        #
        # What the solved path must beat it on is WORKING.
        assert _full_report(solved, spec).ok, "the solved layout does not validate"
        assert not _full_report(greedy, spec).ok, (
            "the greedy construction validated, so it is no longer the "
            "unrouted straw man this test compares against -- rewrite the test"
        )


    def test_a_producer_feeding_many_consumers_is_served(self) -> None:
        """The gap this used to pin as unfixable, now closed.

        A belt tile has one ``output_obj``, so a lane feeding four consumers
        cannot simply point at all four. It taps a different TILE of the lane
        for each and puts a splitter there -- the lane keeps flowing past the
        tap, and the branch draws from the junction.

        This test previously asserted the opposite (that the spec was refused),
        deliberately written to fail the moment the gap closed. It did.
        """
        spec = fan_out_spec(consumers=4)
        p = FreeformLayout(
            band_policy=BandPolicy("100"),
        ).lay_out(spec, time_budget_s=2.0)
        report = _full_report(p, spec)
        assert report.ok, "\n".join(f.message for f in report.errors[:5])
        assert p.stats["route_failures"] == 0.0

    def test_zero_budget_refuses_rather_than_falling_back(self) -> None:
        """A zero budget is a refusal, not a licence to hand back the greedy stack.

        ``fallback_placement`` never routes, so returning it returned a layout
        that was both broken and -- because an unrouted net is a belt run that
        does not exist -- smaller than a correct one.
        """
        with pytest.raises(NoValidLayout) as exc:
            FreeformLayout(
                band_policy=BandPolicy("portable"),
            ).lay_out(two_stage_spec(), time_budget_s=0.0)
        assert "packer was never asked" in exc.value.reason

    def test_a_placement_our_own_validator_rejects_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``lay_out`` promises a valid ``Placement`` or an exception.

        That promise used to be ARGUED here while ``spine`` enforced it: spine
        has called ``validate.certify`` before returning all along and this did
        not.  The gap was not theoretical -- ``quantum-chip``/free-proliferation
        emitted, about one build in sixteen, a placement whose titanium-glass
        production was cut into islands, so eleven machines could reach 16/7
        items/s of an item they consumed 11/4 of.  It wired, it pasted, and it
        did not run.

        Forcing every candidate to be rejected proves the trade goes the right
        way: a refusal that NAMES the failing check, never a placement.
        """
        rejection = validate.Report(
            findings=(
                validate.Finding(
                    "flow.conservation", validate.Severity.ERROR, "forced", (), {}
                ),
            )
        )
        validated: list[Placement] = []

        def reject(
            candidate: Placement,
            *_args: object,
            **_kwargs: object,
        ) -> validate.Report:
            validated.append(candidate)
            return rejection

        monkeypatch.setattr(
            "flab2bp.layout.freeform.validate.certify",
            reject,
        )
        with pytest.raises(NoValidLayout) as exc:
            FreeformLayout(
                band_policy=BandPolicy("portable"),
            ).lay_out(two_stage_spec(), time_budget_s=1.0)
        assert validated
        assert validated[-1].frame is not None
        assert validated[-1].completion is None
        assert "rejected by our own validator" in exc.value.reason
        assert "flow.conservation" in exc.value.reason, (
            "the refusal must name the check, or the next reader goes to the "
            f"packer for a pack that wired perfectly well: {exc.value.reason}"
        )

    def test_projection_refusal_preserves_authoritative_detail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        failure = finalize.ProjectionFailure(
            check="geom.collide",
            buildings=(0, 1),
            detail="build colliders intersect",
            band=160,
        )
        pack = freeform._Pack(
            at={0: (0, 0), 1: (8, 0)},
            width=16,
            height=8,
            status="test",
        )
        routed = _BuildResult(
            placement=Placement(buildings=(), stats={"belt_tiles": 0.0}),
            routing=DetailedRouteResult(
                status=DetailedRouteStatus.ROUTED,
                routed=(),
                failures=(),
                iterations=0,
                expansions=0,
            ),
            budget_stage=None,
            towers=(),
        )
        monkeypatch.setattr(freeform, "_candidate_heights", lambda _strips: [8])
        monkeypatch.setattr(freeform, "_greedy_pack", lambda _strips, _height: pack)
        monkeypatch.setattr(freeform, "_pack", lambda *_args, **_kwargs: pack)
        monkeypatch.setattr(freeform, "_build", lambda *_args, **_kwargs: routed)
        monkeypatch.setattr(
            validate,
            "certify",
            lambda *_args, **_kwargs: validate.Report(findings=()),
        )
        def refuse_projection(
            _placement: Placement,
            _policy: BandPolicy,
            *,
            cancelled: Callable[[], bool] | None = None,
        ) -> Placement:
            del cancelled
            raise finalize.ProjectionRefusal((failure,))

        monkeypatch.setattr(finalize, "finalize_placement", refuse_projection)

        with pytest.raises(NoValidLayout) as caught:
            FreeformLayout(
                band_policy=BandPolicy("portable"),
            ).lay_out(two_stage_spec(), time_budget_s=1.0)

        assert "geom.collide" in caught.value.reason
        assert "band 160" in caught.value.reason
        assert "(0, 1)" in caught.value.reason
        assert "build colliders intersect" in caught.value.reason


def projected_chemical_plant_spec(*, machine_count: int = 2) -> BuildSpec:
    return BuildSpec(
        groups=(
            group(
                "plastic",
                "chemical-plant",
                machine_count,
                {"refined-oil": F(1)},
                {"plastic": F(1)},
            ),
        ),
        external_inputs={"refined-oil": F(machine_count)},
        outputs={"plastic": F(machine_count)},
        label="projected-chemical-plant-collision",
    )


def test_plan_strips_applies_minimum_pitch_to_one_pose() -> None:
    ordinary = plan_strips(plastic_spec(), strip_len=6)
    chemical = next(strip for strip in ordinary if strip.item_id == 2309)
    assert chemical.physical_variant is not None
    pose_id = strip_pose_id(chemical.physical_variant)

    padded = plan_strips(
        plastic_spec(),
        strip_len=6,
        minimum_pitch_x={pose_id: chemical.pw + 1},
    )

    padded_chemical = next(strip for strip in padded if strip.family_id == chemical.family_id)
    assert padded_chemical.pw == chemical.pw + 1
    assert padded_chemical.physical_variant is not None
    assert strip_pose_id(padded_chemical.physical_variant) == pose_id
    assert all(
        after == before
        for before, after in zip(ordinary, padded, strict=True)
        if before.family_id != chemical.family_id
    )




def test_pitch_replan_does_not_contaminate_later_ordinary_strip_plans() -> None:
    spec = projected_chemical_plant_spec()
    (family,) = generate_strip_families(spec)
    ordinary_pitch = default_strip_variant(family).pitch_x
    before = plan_strips(spec, strip_len=2)
    variant = before[0].physical_variant
    assert variant is not None
    pose_id = strip_pose_id(variant)

    widened = plan_strips(
        spec,
        strip_len=2,
        minimum_pitch_x={pose_id: ordinary_pitch + 1},
    )
    after = plan_strips(spec, strip_len=2)

    assert before[0].pw == ordinary_pitch
    assert widened[0].pw == ordinary_pitch + 1
    assert after[0].pw == ordinary_pitch


def test_coarsening_preserves_pose_specific_minimum_pitch() -> None:
    spec = projected_chemical_plant_spec(machine_count=41)
    ordinary = plan_strips(spec, strip_len=1)
    assert len(ordinary) == 41
    assert ordinary[0].physical_variant is not None
    pose_id = strip_pose_id(ordinary[0].physical_variant)
    minimum_pitch_x = {pose_id: ordinary[0].pw + 1}
    padded = plan_strips(
        spec,
        strip_len=1,
        minimum_pitch_x=minimum_pitch_x,
    )

    coarse, effective_strip_len = freeform._coarsen_saturated_strip_plan(
        spec,
        padded,
        strip_len=1,
        minimum_pitch_x=minimum_pitch_x,
    )

    assert effective_strip_len == spec.machine_count
    assert len(coarse) == 1
    assert coarse[0].pw == ordinary[0].pw + 1
    assert coarse[0].physical_variant is not None
    assert strip_pose_id(coarse[0].physical_variant) == pose_id


def test_port_driven_family_remains_directly_routable_with_pitch_mapping() -> None:
    spec = mode_driven_spec()
    (strip,) = plan_strips(
        spec,
        strip_len=6,
        minimum_pitch_x={},
    )

    assert strip.physical_variant is None
    placement = FreeformLayout(
        band_policy=BandPolicy("portable"),
    ).lay_out(spec, time_budget_s=4.0)
    _assert_energy_exchanger_port_routing(placement, spec)


def test_freeform_keeps_projection_valid_with_evidence_scoped_pitch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planned_pitches: list[tuple[int, ...]] = []
    ordinary_plan_strips = freeform.plan_strips

    def recording_plan_strips(
        spec: BuildSpec,
        *,
        strip_len: int = 6,
        band_policy: BandPolicy = freeform._DEFAULT_BAND_POLICY,
        minimum_pitch_x: Mapping[StripPoseId, int] = freeform._NO_PITCH_REQUIREMENTS,
        minimum_staged_static_clearance: Mapping[
            freeform.StagedStaticClearanceKey,
            int,
        ] = freeform._NO_STAGED_STATIC_CLEARANCE,
        cancelled: Callable[[], bool] | None = None,
    ) -> list[Strip]:
        planned = ordinary_plan_strips(
            spec,
            strip_len=strip_len,
            band_policy=band_policy,
            minimum_pitch_x=minimum_pitch_x,
            minimum_staged_static_clearance=minimum_staged_static_clearance,
            cancelled=cancelled,
        )
        chemical_pitches = tuple(strip.pw for strip in planned if strip.item_id == 2309)
        if chemical_pitches:
            planned_pitches.append(chemical_pitches)
        return planned

    monkeypatch.setattr(freeform, "plan_strips", recording_plan_strips)
    spec = plastic_spec()
    placement = FreeformLayout(
        band_policy=BandPolicy("portable"),
        workers=1,
    ).lay_out(spec, time_budget_s=4.0)

    report = validate.certify(placement, spec, expect_power=True)
    assert report.ok
    assert not report.by_check("geom.collide")
    assert planned_pitches
    assert set(planned_pitches[0]) == {7}
    assert set(planned_pitches[-1]) == {8}


@pytest.fixture
def projected_chemical_plant_collision(
) -> tuple[Placement, StripInstance, StripVariant, finalize.ProjectionFailure]:
    spec = projected_chemical_plant_spec()
    (family,) = generate_strip_families(spec)
    ordinary = default_strip_variant(family)
    (instance,) = partition_strip_family(
        family,
        max_machine_count=2,
        variant_id=ordinary.variant_id,
    )
    (strip,) = plan_strips(spec, strip_len=2)
    canvas = _Canvas()
    belt_id = catalog.item_id(spec.belt_item_id)
    _emit_strip(
        canvas,
        strip,
        3,
        11,
        belt_id,
        catalog.building(belt_id).model_index,
        {},
        owner_strip=0,
    )
    machines = tuple(
        (index, building)
        for index, building in enumerate(canvas.buildings)
        if building.item_id == 2309
    )

    assert len(machines) == 2
    assert ordinary.pitch_x == 8
    assert tuple(
        (
            building.item_id,
            building.model_index,
            building.yaw,
            building.owner_strip,
        )
        for _index, building in machines
    ) == ((2309, 64, ordinary.yaw, 0), (2309, 64, ordinary.yaw, 0))
    assert machines[1][1].x - machines[0][1].x == ordinary.pitch_x
    failure = finalize.ProjectionFailure(
        "geom.collide",
        (machines[0][0], machines[1][0]),
        "build colliders intersect",
        160,
    )
    return Placement(buildings=tuple(canvas.buildings)), instance, ordinary, failure


def test_same_strip_adjacent_machine_collision_requires_next_pitch(
    projected_chemical_plant_collision: tuple[
        Placement,
        StripInstance,
        StripVariant,
        finalize.ProjectionFailure,
    ],
) -> None:
    placement, instance, ordinary, failure = projected_chemical_plant_collision

    requirement = projection_pitch_requirement(
        placement,
        instance_ids=(instance.instance_id,),
        variants=(ordinary,),
        failure=failure,
    )

    assert requirement == ProjectionPitchRequirement(
        family_id=instance.family_id,
        instance_id=instance.instance_id,
        variant_id=ordinary.variant_id,
        axis="x",
        rejected_pitch=8,
        required_pitch=9,
        failure=failure,
    )


def test_freeform_owner_adapter_uses_realized_strip_variant(
    projected_chemical_plant_collision: tuple[
        Placement,
        StripInstance,
        StripVariant,
        finalize.ProjectionFailure,
    ],
) -> None:
    placement, instance, ordinary, failure = projected_chemical_plant_collision
    strips = plan_strips(projected_chemical_plant_spec(), strip_len=2)

    (requirement,) = freeform._projection_pitch_requirements(
        placement,
        strips,
        (failure,),
    )

    assert requirement == ProjectionPitchRequirement(
        family_id=instance.family_id,
        instance_id=instance.instance_id,
        variant_id=ordinary.variant_id,
        axis="x",
        rejected_pitch=8,
        required_pitch=9,
        failure=failure,
    )


def _sweep_with_pitch_feedback(
    monkeypatch: pytest.MonkeyPatch,
    required_pitches: Sequence[int],
) -> tuple[Placement | None, list[tuple[int, int, int]], list[freeform._RefusalFinding]]:
    spec = projected_chemical_plant_spec()
    strips = plan_strips(spec, strip_len=2)
    pack = freeform._Pack(
        at={0: (3, 4)},
        width=20,
        height=20,
        status="test",
    )
    failure = finalize.ProjectionFailure(
        "geom.collide",
        (0, 1),
        "build colliders intersect",
        160,
    )
    routed = DetailedRouteResult(
        status=DetailedRouteStatus.ROUTED,
        routed=(),
        failures=(),
        iterations=0,
        expansions=0,
    )
    seen_candidates: list[tuple[int, int, int]] = []
    feedback_index = 0
    finalizations = 0

    def pack_candidate(
        current_strips: list[Strip],
        *,
        height: int,
        arrangement: int,
        **_kwargs: object,
    ) -> freeform._Pack:
        physical_variant = current_strips[0].physical_variant
        assert physical_variant is not None
        seen_candidates.append((height, arrangement, physical_variant.pitch_x))
        return pack

    def build_candidate(
        _spec: BuildSpec,
        _strips: list[Strip],
        _pack: freeform._Pack,
        **_kwargs: object,
    ) -> _BuildResult:
        return _BuildResult(
            placement=Placement(buildings=(), stats={"belt_tiles": 0.0}),
            routing=routed,
            budget_stage=None,
            towers=(),
        )

    def pitch_requirements(
        _placement: Placement,
        current_strips: list[Strip],
        failures: tuple[finalize.ProjectionFailure, ...],
    ) -> tuple[ProjectionPitchRequirement | None, ...]:
        nonlocal feedback_index
        assert len(failures) == 1
        required_pitch = required_pitches[feedback_index]
        feedback_index += 1
        strip = current_strips[0]
        physical_variant = strip.physical_variant
        assert strip.family_id is not None
        assert physical_variant is not None
        from flab2bp.layout.strip_variants import StripInstanceId

        instance_id = StripInstanceId(
            strip.family_id,
            strip.machine_start,
            strip.machines,
        )
        return (
            ProjectionPitchRequirement(
                family_id=strip.family_id,
                instance_id=instance_id,
                variant_id=physical_variant.variant_id,
                axis="x",
                rejected_pitch=required_pitch - 1,
                required_pitch=required_pitch,
                failure=failures[0],
            ),
        )

    def finalize_candidate(
        placement: Placement,
        _policy: BandPolicy,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> Placement:
        nonlocal finalizations
        del cancelled
        if finalizations < len(required_pitches):
            finalizations += 1
            raise finalize.ProjectionRefusal((failure,))
        return placement

    monkeypatch.setattr(freeform, "_candidate_heights", lambda _strips: [20])
    monkeypatch.setattr(freeform, "_greedy_pack", lambda _strips, _height: pack)
    monkeypatch.setattr(freeform, "_pack", pack_candidate)
    monkeypatch.setattr(freeform, "_build", build_candidate)
    monkeypatch.setattr(
        freeform,
        "_projection_pitch_requirements",
        pitch_requirements,
    )
    monkeypatch.setattr(
        validate,
        "certify",
        lambda *_args, **_kwargs: validate.Report(findings=()),
    )
    monkeypatch.setattr(finalize, "finalize_placement", finalize_candidate)

    rejected: list[freeform._RefusalFinding] = []
    result = FreeformLayout(
        band_policy=BandPolicy("portable"),
        arrangements=1,
    )._sweep(spec, strips, 1.0, rejected=rejected)
    return result, seen_candidates, rejected


def test_pitch_retry_affordability_is_decided_before_geometry_replan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ordinary_plan_strips = freeform.plan_strips
    geometry_replanned = False

    def recording_plan_strips(
        spec: BuildSpec,
        *,
        strip_len: int = 6,
        band_policy: BandPolicy = freeform._DEFAULT_BAND_POLICY,
        minimum_pitch_x: Mapping[StripPoseId, int] = freeform._NO_PITCH_REQUIREMENTS,
        minimum_staged_static_clearance: Mapping[
            freeform.StagedStaticClearanceKey,
            int,
        ] = freeform._NO_STAGED_STATIC_CLEARANCE,
        cancelled: Callable[[], bool] | None = None,
    ) -> list[Strip]:
        nonlocal geometry_replanned
        if minimum_pitch_x:
            geometry_replanned = True
        return ordinary_plan_strips(
            spec,
            strip_len=strip_len,
            band_policy=band_policy,
            minimum_pitch_x=minimum_pitch_x,
            minimum_staged_static_clearance=minimum_staged_static_clearance,
            cancelled=cancelled,
        )

    monkeypatch.setattr(freeform, "plan_strips", recording_plan_strips)
    monkeypatch.setattr(
        freeform,
        "_room_for_another",
        lambda *_args, **_kwargs: not geometry_replanned,
    )

    result, seen_candidates, _rejected = _sweep_with_pitch_feedback(
        monkeypatch,
        (9,),
    )

    assert result is not None
    assert seen_candidates == [(20, 0, 8), (20, 0, 9)]


def test_repeated_identical_pitch_feedback_does_not_duplicate_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, seen_candidates, rejected = _sweep_with_pitch_feedback(
        monkeypatch,
        (9, 9),
    )

    assert result is None
    assert seen_candidates == [(20, 0, 8), (20, 0, 9)]
    assert len(rejected) == 1
    assert isinstance(rejected[0], finalize.ProjectionFailure)


def test_later_exact_pitch_failure_advances_same_candidate_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, seen_candidates, rejected = _sweep_with_pitch_feedback(
        monkeypatch,
        (9, 10),
    )

    assert result is not None
    assert seen_candidates == [(20, 0, 8), (20, 0, 9), (20, 0, 10)]
    assert len(rejected) == 1
    assert isinstance(rejected[0], finalize.ProjectionFailure)


def test_unaffordable_pitch_feedback_replans_later_base_height(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = projected_chemical_plant_spec()
    strips = plan_strips(spec, strip_len=2)
    failure = finalize.ProjectionFailure(
        "geom.collide",
        (0, 1),
        "adjacent projected machines collide",
        160,
    )
    routed = DetailedRouteResult(
        status=DetailedRouteStatus.ROUTED,
        routed=(),
        failures=(),
        iterations=0,
        expansions=0,
    )
    seen_candidates: list[tuple[int, int, int]] = []

    def pack_candidate(
        current: list[Strip],
        *,
        height: int,
        arrangement: int,
        **_kwargs: object,
    ) -> freeform._Pack:
        variant = current[0].physical_variant
        assert variant is not None
        seen_candidates.append((height, arrangement, variant.pitch_x))
        return replace(_greedy_pack(current, height), status="pitch carry-forward")

    def build_candidate(
        _spec: BuildSpec,
        current: list[Strip],
        pack: freeform._Pack,
        **_kwargs: object,
    ) -> _BuildResult:
        variant = current[0].physical_variant
        assert variant is not None
        if pack.height == 21:
            assert variant.pitch_x == 9
        return _BuildResult(
            placement=Placement(
                buildings=(),
                stats={
                    "belt_tiles": 0.0,
                    "test_height": float(pack.height),
                },
            ),
            routing=routed,
            budget_stage=None,
            towers=(),
        )

    def pitch_requirements(
        _placement: Placement,
        current: list[Strip],
        failures: tuple[finalize.ProjectionFailure, ...],
    ) -> tuple[ProjectionPitchRequirement, ...]:
        assert len(failures) == 1
        strip = current[0]
        variant = strip.physical_variant
        assert strip.family_id is not None
        assert variant is not None
        from flab2bp.layout.strip_variants import StripInstanceId

        return (
            ProjectionPitchRequirement(
                family_id=strip.family_id,
                instance_id=StripInstanceId(
                    strip.family_id,
                    strip.machine_start,
                    strip.machines,
                ),
                variant_id=variant.variant_id,
                axis="x",
                rejected_pitch=8,
                required_pitch=9,
                failure=failures[0],
            ),
        )

    def finalize_candidate(
        placement: Placement,
        _policy: BandPolicy,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> Placement:
        del cancelled
        if placement.stats["test_height"] == 20.0:
            raise finalize.ProjectionRefusal((failure,))
        return placement

    monkeypatch.setattr(
        freeform,
        "_band_policy_candidate_heights",
        lambda _strips, _policy: (20, 21),
    )
    monkeypatch.setattr(freeform, "_pack", pack_candidate)
    monkeypatch.setattr(freeform, "_build", build_candidate)
    monkeypatch.setattr(
        freeform,
        "_projection_pitch_requirements",
        pitch_requirements,
    )
    monkeypatch.setattr(
        validate,
        "certify",
        lambda *_args, **_kwargs: validate.Report(findings=()),
    )
    monkeypatch.setattr(finalize, "finalize_placement", finalize_candidate)
    monkeypatch.setattr(
        freeform,
        "_room_for_another",
        lambda *_args, **_kwargs: False,
    )

    result = FreeformLayout(
        band_policy=BandPolicy("portable"),
        arrangements=1,
    )._sweep(spec, strips, 1.0)

    assert result is not None
    assert result.stats["test_height"] == 21.0
    assert seen_candidates == [(20, 0, 8), (21, 0, 9)]



def test_geometry_replan_discards_feedback_width_and_direct_cuts_from_old_strips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = projected_chemical_plant_spec()
    strips = plan_strips(spec, strip_len=2)
    failure = finalize.ProjectionFailure(
        "geom.collide",
        (0, 1),
        "adjacent projected machines collide",
        160,
    )
    routed = DetailedRouteResult(
        status=DetailedRouteStatus.ROUTED,
        routed=(),
        failures=(),
        iterations=0,
        expansions=0,
    )
    old_pitch_cut = freeform._DirectRelationNoGood(
        DirectInsertId(0, 1, "pitch-sensitive", CargoDomain.UNSPRAYED),
        delta_x=7,
        delta_y=0,
    )
    seen_pack_state: list[tuple[int, int, bool, bool]] = []

    def greedy(current: list[Strip], height: int) -> freeform._Pack:
        variant = current[0].physical_variant
        assert variant is not None
        width = 20 if variant.pitch_x == 8 else 40
        return freeform._Pack(
            at={0: (3, 4)},
            width=width,
            height=height,
            status="greedy",
        )

    def pack_candidate(
        current: list[Strip],
        *,
        height: int,
        width_bound: int,
        feedback: FeedbackState | None,
        direct_relation_no_goods: tuple[object, ...],
        **_kwargs: object,
    ) -> freeform._Pack:
        variant = current[0].physical_variant
        assert variant is not None
        seen_pack_state.append(
            (
                variant.pitch_x,
                width_bound,
                feedback is not None,
                bool(direct_relation_no_goods),
            )
        )
        candidate = greedy(current, height)
        x_offset = len(seen_pack_state) - 1
        return replace(
            candidate,
            at={
                index: (x + x_offset, y)
                for index, (x, y) in candidate.at.items()
            },
            status=f"pack-{len(seen_pack_state)}",
        )

    def build_candidate(
        _spec: BuildSpec,
        _strips: list[Strip],
        pack: freeform._Pack,
        **_kwargs: object,
    ) -> _BuildResult:
        if pack.status == "pack-1":
            return _BuildResult(
                placement=None,
                routing=_feedback_bearing_routing(),
                budget_stage=None,
                towers=(),
            )
        return _BuildResult(
            placement=Placement(buildings=(), stats={"belt_tiles": 0.0}),
            routing=routed,
            budget_stage=None,
            towers=(),
        )

    def pitch_requirements(
        _placement: Placement,
        current: list[Strip],
        failures: tuple[finalize.ProjectionFailure, ...],
    ) -> tuple[ProjectionPitchRequirement, ...]:
        assert len(failures) == 1
        strip = current[0]
        variant = strip.physical_variant
        assert strip.family_id is not None
        assert variant is not None
        from flab2bp.layout.strip_variants import StripInstanceId

        return (
            ProjectionPitchRequirement(
                family_id=strip.family_id,
                instance_id=StripInstanceId(
                    strip.family_id,
                    strip.machine_start,
                    strip.machines,
                ),
                variant_id=variant.variant_id,
                axis="x",
                rejected_pitch=8,
                required_pitch=9,
                failure=failures[0],
            ),
        )

    finalizations = 0

    def finalize_candidate(
        placement: Placement,
        _policy: BandPolicy,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> Placement:
        nonlocal finalizations
        del cancelled
        finalizations += 1
        if finalizations == 1:
            raise finalize.ProjectionRefusal((failure,))
        return placement

    monkeypatch.setattr(
        freeform,
        "_band_policy_candidate_heights",
        lambda _strips, _policy: (20,),
    )
    monkeypatch.setattr(freeform, "_greedy_pack", greedy)
    monkeypatch.setattr(freeform, "_pack", pack_candidate)
    monkeypatch.setattr(freeform, "_build", build_candidate)
    monkeypatch.setattr(
        freeform,
        "_proof_scoped_no_goods",
        lambda *_args, **_kwargs: ((old_pitch_cut,), None),
    )
    monkeypatch.setattr(
        freeform,
        "_projection_pitch_requirements",
        pitch_requirements,
    )
    monkeypatch.setattr(
        validate,
        "certify",
        lambda *_args, **_kwargs: validate.Report(findings=()),
    )
    monkeypatch.setattr(finalize, "finalize_placement", finalize_candidate)
    monkeypatch.setattr(
        freeform,
        "_room_for_another",
        lambda *_args, **_kwargs: True,
    )

    result = FreeformLayout(
        band_policy=BandPolicy("portable"),
        arrangements=2,
    )._sweep(spec, strips, 5.0)

    assert result is not None, seen_pack_state
    assert seen_pack_state == [
        (8, 40, False, False),
        (8, 22, True, True),
        (9, 80, False, False),
    ]

def test_projection_no_good_forbids_only_the_exact_failed_pair_context() -> None:
    strip = plan_strips(single_recipe_spec())[0]
    strips = [
        replace(strip, west_channel=3),
        replace(strip, west_channel=1),
        replace(strip, west_channel=1),
    ]
    height = 2 * max(_box(candidate)[1] for candidate in strips)
    width_bound = 3 * max(_box(candidate)[0] for candidate in strips)
    initial = _pack(
        strips,
        height=height,
        width_bound=width_bound,
        time_budget_s=0.5,
        direct_candidates={},
        workers=DETERMINISTIC_WORKERS,
    )
    assert initial is not None
    failure = finalize.ProjectionFailure(
        check="geom.collide",
        buildings=(0, 2),
        detail="build colliders intersect",
        band=160,
    )
    rejected_delta = (
        initial.at[0][0] - initial.at[2][0],
        initial.at[0][1] - initial.at[2][1],
    )
    unrelated_delta = (
        initial.at[0][0] - initial.at[1][0],
        initial.at[0][1] - initial.at[1][1],
    )
    bad = ProjectionNoGood(
        left_strip=0,
        right_strip=2,
        delta_x=rejected_delta[0],
        delta_y=rejected_delta[1],
        pack_width=initial.width,
        pack_height=initial.height,
        left_origin=initial.at[0],
        right_origin=initial.at[2],
        left_geometry=freeform._strip_geometry_signature(strips[0]),
        right_geometry=freeform._strip_geometry_signature(strips[2]),
        failure=failure,
    )

    retry = _pack(
        strips,
        height=height,
        width_bound=width_bound,
        time_budget_s=0.5,
        direct_candidates={},
        workers=DETERMINISTIC_WORKERS,
        projection_no_goods=(bad,),
    )

    assert retry is not None
    assert (
        retry.width,
        retry.height,
        retry.at[0],
        retry.at[2],
    ) != (
        bad.pack_width,
        bad.pack_height,
        bad.left_origin,
        bad.right_origin,
    )
    assert (
        retry.at[0][0] - retry.at[1][0],
        retry.at[0][1] - retry.at[1][1],
    ) == unrelated_delta

def test_projection_no_good_unrelated_strip_movement_cannot_erase_pair_evidence() -> None:
    strip = plan_strips(single_recipe_spec())[0]
    strips = [
        replace(strip, group_key=f"strip-{index}", west_channel=1)
        for index in range(3)
    ]
    height = 3 * max(_box(candidate)[1] for candidate in strips)
    width_bound = 3 * max(_box(candidate)[0] for candidate in strips)
    baseline = _pack(
        strips,
        height=height,
        width_bound=width_bound,
        time_budget_s=0.5,
        direct_candidates={},
        workers=DETERMINISTIC_WORKERS,
    )
    assert baseline is not None
    complete_origins = tuple(baseline.at[index] for index in range(3))
    failure = finalize.ProjectionFailure("geom.collide", (0, 1), "collision", 160)
    no_good = ProjectionNoGood(
        left_strip=0,
        right_strip=1,
        delta_x=complete_origins[0][0] - complete_origins[1][0],
        delta_y=complete_origins[0][1] - complete_origins[1][1],
        pack_width=baseline.width,
        pack_height=baseline.height,
        left_origin=complete_origins[0],
        right_origin=complete_origins[1],
        left_geometry=freeform._strip_geometry_signature(strips[0]),
        right_geometry=freeform._strip_geometry_signature(strips[1]),
        failure=failure,
    )

    def solve_with(origins: tuple[tuple[int, int], ...]) -> cp_model.CpSolverStatus:
        model = cp_model.CpModel()
        width = model.new_int_var(0, width_bound, "width")
        xs = [
            model.new_int_var(0, width_bound, f"x{index}")
            for index in range(len(strips))
        ]
        ys = [
            model.new_int_var(0, height, f"y{index}")
            for index in range(len(strips))
        ]
        freeform._add_projection_no_good(model, width, xs, ys, strips, no_good)
        model.add(width == baseline.width)
        for index, origin in enumerate(origins):
            model.add(xs[index] == origin[0] - strips[index].west_channel)
            model.add(ys[index] == origin[1])
        return cp_model.CpSolver().solve(model)

    assert solve_with(complete_origins) == cp_model.INFEASIBLE
    moved_third = (
        complete_origins[0],
        complete_origins[1],
        (complete_origins[2][0] + 1, complete_origins[2][1]),
    )
    assert solve_with(moved_third) == cp_model.INFEASIBLE
    moved_implicated = (
        complete_origins[0],
        (complete_origins[1][0] + 1, complete_origins[1][1]),
        complete_origins[2],
    )
    assert solve_with(moved_implicated) in (cp_model.FEASIBLE, cp_model.OPTIMAL)


def test_projection_no_good_changed_implicated_variant_remains_searchable() -> None:
    strip = replace(plan_strips(single_recipe_spec())[0], west_channel=1)
    strips = [replace(strip, group_key=f"strip-{index}") for index in range(2)]
    height = 2 * max(_box(candidate)[1] for candidate in strips)
    width_bound = 2 * max(_box(candidate)[0] for candidate in strips)
    baseline = _pack(
        strips,
        height=height,
        width_bound=width_bound,
        time_budget_s=0.5,
        direct_candidates={},
        workers=DETERMINISTIC_WORKERS,
    )
    assert baseline is not None
    failure = finalize.ProjectionFailure("geom.collide", (0, 1), "collision", 160)
    no_good = ProjectionNoGood(
        left_strip=0,
        right_strip=1,
        delta_x=baseline.at[0][0] - baseline.at[1][0],
        delta_y=baseline.at[0][1] - baseline.at[1][1],
        pack_width=baseline.width,
        pack_height=baseline.height,
        left_origin=baseline.at[0],
        right_origin=baseline.at[1],
        left_geometry=freeform._strip_geometry_signature(strips[0]),
        right_geometry=freeform._strip_geometry_signature(strips[1]),
        failure=failure,
    )
    changed = [replace(strips[0], yaw=(strips[0].yaw + 90.0) % 360.0), strips[1]]
    control = _pack(
        changed,
        height=height,
        width_bound=width_bound,
        time_budget_s=0.5,
        direct_candidates={},
        workers=DETERMINISTIC_WORKERS,
    )
    retry = _pack(
        changed,
        height=height,
        width_bound=width_bound,
        time_budget_s=0.5,
        direct_candidates={},
        workers=DETERMINISTIC_WORKERS,
        projection_no_goods=(no_good,),
    )

    assert control is not None
    assert retry is not None
    assert retry.at == control.at
    assert retry.width == control.width


@pytest.mark.parametrize("context_change", ["height", "width", "absolute-origin"])
def test_projection_no_good_leaves_same_displacement_free_in_another_context(
    context_change: str,
) -> None:
    strip = plan_strips(single_recipe_spec())[0]
    strips = [replace(strip, west_channel=3), replace(strip, west_channel=1)]
    height = 2 * max(_box(candidate)[1] for candidate in strips)
    width_bound = 2 * max(_box(candidate)[0] for candidate in strips)
    baseline = _pack(
        strips,
        height=height,
        width_bound=width_bound,
        time_budget_s=0.5,
        direct_candidates={},
        workers=DETERMINISTIC_WORKERS,
    )
    assert baseline is not None
    failure = finalize.ProjectionFailure("geom.collide", (0, 1), "collision", 160)
    delta = (
        baseline.at[0][0] - baseline.at[1][0],
        baseline.at[0][1] - baseline.at[1][1],
    )
    no_good = ProjectionNoGood(
        left_strip=0,
        right_strip=1,
        delta_x=delta[0],
        delta_y=delta[1],
        pack_width=baseline.width,
        pack_height=baseline.height,
        left_origin=baseline.at[0],
        right_origin=baseline.at[1],
        left_geometry=freeform._strip_geometry_signature(strips[0]),
        right_geometry=freeform._strip_geometry_signature(strips[1]),
        failure=failure,
    )
    if context_change == "height":
        other_context = replace(no_good, pack_height=999)
    elif context_change == "width":
        other_context = replace(no_good, pack_width=999)
    else:
        moved_left = (999, 999)
        other_context = replace(
            no_good,
            left_origin=moved_left,
        )

    retry = _pack(
        strips,
        height=height,
        width_bound=width_bound,
        time_budget_s=0.5,
        direct_candidates={},
        workers=DETERMINISTIC_WORKERS,
        projection_no_goods=(other_context,),
    )

    assert retry is not None
    assert retry.at == baseline.at
    assert retry.width == baseline.width


@pytest.mark.parametrize("independent", [True, False])
def test_projection_no_good_owned_strip_collision_learns_and_repacks(
    monkeypatch: pytest.MonkeyPatch,
    independent: bool,
) -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec)
    first = freeform._Pack(
        at={0: (3, 4), 1: (11, 9)},
        width=20,
        height=20,
        status="first",
    )
    separated = freeform._Pack(
        at={0: (3, 4), 1: (12, 9)},
        width=21,
        height=20,
        status="separated",
    )
    packs = iter((first, separated))
    seen_no_goods: list[tuple[ProjectionNoGood, ...]] = []
    seen_exact_no_goods: list[tuple[freeform.ExactPackNoGood, ...]] = []

    def pack_retry(*_args: object, **kwargs: object) -> freeform._Pack:
        raw_no_goods = kwargs.get("projection_no_goods", ())
        if not isinstance(raw_no_goods, tuple):
            raise AssertionError("projection_no_goods must be a tuple")
        no_goods = tuple(
            item for item in raw_no_goods if isinstance(item, ProjectionNoGood)
        )
        assert len(no_goods) == len(raw_no_goods)
        seen_no_goods.append(no_goods)
        raw_exact = kwargs.get("exact_pack_no_goods", ())
        if not isinstance(raw_exact, tuple):
            raise AssertionError("exact_pack_no_goods must be a tuple")
        assert all(isinstance(item, freeform.ExactPackNoGood) for item in raw_exact)
        seen_exact_no_goods.append(raw_exact)
        return next(packs)

    def build(
        _spec: BuildSpec,
        _strips: list[Strip],
        pack: freeform._Pack,
        **_kwargs: object,
    ) -> _BuildResult:
        buildings = tuple(
            PlacedBuilding(
                item_id=1,
                model_index=1,
                x=x,
                y=y,
                owner_strip=strip_index,
            )
            for strip_index, (x, y) in sorted(pack.at.items())
        )
        return _BuildResult(
            placement=Placement(buildings=buildings, stats={"belt_tiles": 0.0}),
            routing=DetailedRouteResult(
                status=DetailedRouteStatus.ROUTED,
                routed=(),
                failures=(),
                iterations=0,
                expansions=0,
            ),
            budget_stage=None,
            towers=(),
        )

    failure = finalize.ProjectionFailure(
        check="geom.collide",
        buildings=(0, 1),
        detail="build colliders intersect",
        band=160,
    )
    projections = 0

    def finalize_projection(
        placement: Placement,
        _policy: BandPolicy,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> Placement:
        nonlocal projections
        del cancelled
        projections += 1
        if projections == 1:
            raise finalize.ProjectionRefusal((failure,))
        return placement

    monkeypatch.setattr(freeform, "_candidate_heights", lambda _strips: [20])
    monkeypatch.setattr(freeform, "_greedy_pack", lambda _strips, _height: first)
    monkeypatch.setattr(freeform, "_pack", pack_retry)
    monkeypatch.setattr(freeform, "_build", build)
    monkeypatch.setattr(
        validate,
        "certify",
        lambda *_args, **_kwargs: validate.Report(findings=()),
    )
    monkeypatch.setattr(finalize, "finalize_placement", finalize_projection)
    monkeypatch.setattr(
        finalize,
        "independent_projection_pair",
        lambda _pair, _policy, **_kwargs: (0, 1) if independent else None,
    )

    result = FreeformLayout(
        band_policy=BandPolicy("portable"),
        arrangements=1,
    )._sweep(spec, strips, 1.0)

    assert result is not None
    assert len(seen_no_goods) == len(seen_exact_no_goods) == 2
    assert seen_no_goods[0] == seen_exact_no_goods[0] == ()
    if independent:
        learned = seen_no_goods[1]
        assert seen_exact_no_goods[1] == ()
        assert len(learned) == 1
        assert (
            learned[0].left_strip,
            learned[0].right_strip,
            learned[0].delta_x,
            learned[0].delta_y,
            learned[0].failure,
        ) == (0, 1, -8, -5, failure)
    else:
        assert seen_no_goods[1] == ()
        assert len(seen_exact_no_goods[1]) == 1
        exact = seen_exact_no_goods[1][0]
        assert (
            exact.height,
            exact.outline,
            exact.width,
            exact.origins,
            exact.evidence,
        ) == (
            first.height,
            tuple(_box(strip) for strip in strips),
            first.width,
            tuple(first.at[index] for index in range(len(strips))),
            (failure,),
        )


def test_projection_same_strip_and_unowned_failures_create_no_cut() -> None:
    failure = finalize.ProjectionFailure(
        check="geom.collide",
        buildings=(0, 1),
        detail="build colliders intersect",
        band=160,
    )
    strips = [
        replace(
            plan_strips(single_recipe_spec())[0],
            group_key=f"strip-{index}",
        )
        for index in range(2)
    ]
    pack = freeform._Pack(
        at={0: (3, 4), 1: (11, 9)},
        width=20,
        height=20,
        status="test",
    )

    same_strip = Placement(
        buildings=(
            PlacedBuilding(item_id=1, model_index=1, x=0, y=0, owner_strip=0),
            PlacedBuilding(item_id=1, model_index=1, x=1, y=0, owner_strip=0),
        )
    )
    unowned = Placement(
        buildings=(
            PlacedBuilding(item_id=1, model_index=1, x=0, y=0, owner_strip=0),
            PlacedBuilding(item_id=1, model_index=1, x=1, y=0),
        )
    )

    policy = BandPolicy("portable")
    assert (
        freeform._projection_no_good(same_strip, pack, strips, failure, policy) is None
    )
    assert freeform._projection_no_good(unowned, pack, strips, failure, policy) is None




def test_staged_static_exact_pack_no_good_forbids_only_the_full_assignment() -> None:
    strip = plan_strips(single_recipe_spec())[0]
    strips = [
        replace(strip, group_key=f"staged-static-{index}", west_channel=1)
        for index in range(2)
    ]
    height = 2 * max(_box(candidate)[1] for candidate in strips)
    width_bound = 2 * max(_box(candidate)[0] for candidate in strips)
    baseline = _pack(
        strips,
        height=height,
        width_bound=width_bound,
        time_budget_s=0.5,
        direct_candidates={},
        workers=DETERMINISTIC_WORKERS,
    )
    assert baseline is not None
    failure = finalize.ProjectionFailure(
        "geom.collide",
        (181, 255),
        "build colliders intersect",
        100,
    )
    projection_pair = freeform._exact_projection_pair(strips, (0, 1))
    assert projection_pair is not None
    no_good = freeform.ExactPackNoGood(
        height=baseline.height,
        outline=tuple(_box(candidate) for candidate in strips),
        width=baseline.width,
        origins=tuple(baseline.at[index] for index in range(len(strips))),
        evidence=(failure,),
        projection_pair=projection_pair,
    )

    assert tuple(field.name for field in dataclasses.fields(no_good)) == (
        "height",
        "outline",
        "width",
        "origins",
        "evidence",
        "projection_pair",
    )
    assert no_good.projection_pair == projection_pair
    retry = _pack(
        strips,
        height=height,
        width_bound=width_bound,
        time_budget_s=0.5,
        direct_candidates={},
        workers=DETERMINISTIC_WORKERS,
        exact_pack_no_goods=(no_good,),
    )

    assert retry is not None
    assert (
        retry.height,
        tuple(_box(candidate) for candidate in strips),
        retry.width,
        tuple(retry.at[index] for index in range(len(strips))),
    ) != (
        no_good.height,
        no_good.outline,
        no_good.width,
        no_good.origins,
    )


def _brute_junction_projection_frames(
    occupied: tuple[int, int, int, int],
    limit: tuple[int, int, int, int],
    policy: BandPolicy,
) -> tuple[freeform._JunctionProjectionFrame, ...]:
    """Four-edge oracle deduplicated by physical transform at first encounter."""
    occupied_min_x, occupied_min_y, occupied_max_x, occupied_max_y = occupied
    limit_min_x, limit_min_y, limit_max_x, limit_max_y = limit
    by_segments = {band.area_segments: band for band in planet.bands()}
    candidates_by_extent: dict[
        tuple[int, int],
        tuple[finalize.FrameCandidate, ...],
    ] = {}
    frame_specs: dict[
        tuple[bool, int],
        tuple[tuple[int, int, int, int], finalize.FrameCandidate],
    ] = {}
    projections_by_frame: dict[
        tuple[bool, int],
        dict[tuple[int, int], None],
    ] = {}
    projection_signatures_by_frame: dict[
        tuple[bool, int],
        set[tuple[int, tuple[int, ...]]],
    ] = {}
    for min_x in range(limit_min_x, occupied_min_x + 1):
        for min_y in range(limit_min_y, occupied_min_y + 1):
            for max_x in range(occupied_max_x, limit_max_x + 1):
                for max_y in range(occupied_max_y, limit_max_y + 1):
                    width = max_x - min_x + 1
                    height = max_y - min_y + 1
                    extent = (width, height)
                    candidates = candidates_by_extent.get(extent)
                    if candidates is None:
                        candidates = finalize._frame_candidates_for_extent(
                            width,
                            height,
                            policy,
                        )
                        candidates_by_extent[extent] = candidates
                    for candidate in candidates:
                        rotated = candidate.frame.rotated
                        origin = min_x if rotated else min_y
                        key = (
                            rotated,
                            candidate.south_padding - origin,
                        )
                        frame_specs.setdefault(
                            key,
                            ((min_x, min_y, max_x, max_y), candidate),
                        )
                        signature = (
                            candidate.frame.height,
                            candidate.frame.certified_bands,
                        )
                        signatures = projection_signatures_by_frame.setdefault(
                            key,
                            set(),
                        )
                        if signature in signatures:
                            continue
                        signatures.add(signature)
                        projections = projections_by_frame.setdefault(key, {})
                        for segments in candidate.frame.certified_bands:
                            band = by_segments[segments]
                            for anchor in band.anchors(candidate.frame.height):
                                projections.setdefault((segments, anchor), None)
    return tuple(
        freeform._JunctionProjectionFrame(
            bounds,
            candidate,
            tuple(
                planet.Projection(
                    by_segments[segments],
                    anchor,
                    colliders.PLANET_SEGMENT,
                    colliders.PLANET_RADIUS,
                )
                for segments, anchor in projections_by_frame.get(key, ())
            ),
        )
        for key, (bounds, candidate) in frame_specs.items()
    )


def _physical_projection_frames(
    frames: Sequence[freeform._JunctionProjectionFrame],
) -> dict[tuple[bool, int], frozenset[tuple[int, int]]]:
    physical: dict[tuple[bool, int], set[tuple[int, int]]] = {}
    for frame in frames:
        rotated = frame.candidate.frame.rotated
        origin = frame.bounds[0] if rotated else frame.bounds[1]
        key = (rotated, frame.candidate.south_padding - origin)
        projections = physical.setdefault(key, set())
        projections.update(
            (projection.band.area_segments, projection.anchor_row)
            for projection in frame.projections
        )
    return {key: frozenset(value) for key, value in physical.items()}


def _ordered_projection_frames(
    frames: Sequence[freeform._JunctionProjectionFrame],
) -> tuple[
    tuple[
        bool,
        int,
        tuple[int, int, int, int],
        finalize.FrameCandidate,
        tuple[tuple[int, int], ...],
    ],
    ...,
]:
    return tuple(
        (
            frame.candidate.frame.rotated,
            frame.candidate.south_padding
            - (
                frame.bounds[0]
                if frame.candidate.frame.rotated
                else frame.bounds[1]
            ),
            frame.bounds,
            frame.candidate,
            tuple(
                (projection.band.area_segments, projection.anchor_row)
                for projection in frame.projections
            ),
        )
        for frame in frames
    )


@pytest.mark.parametrize(
    ("occupied", "limit", "policy"),
    (
        ((0, 0, 2, 2), (-2, -1, 4, 5), BandPolicy("portable")),
        ((-1, -2, 1, 0), (-3, -4, 4, 3), BandPolicy("100")),
        ((2, 3, 4, 6), (0, 0, 7, 9), BandPolicy("portable")),
    ),
)
def test_junction_projection_frames_match_four_edge_brute_oracle(
    occupied: tuple[int, int, int, int],
    limit: tuple[int, int, int, int],
    policy: BandPolicy,
) -> None:
    expected = _brute_junction_projection_frames(occupied, limit, policy)
    actual = freeform._junction_projection_frames(occupied, limit, policy)

    assert _ordered_projection_frames(actual) == _ordered_projection_frames(expected)


def test_junction_projection_frames_preserve_legacy_first_witness() -> None:
    frames = freeform._junction_projection_frames(
        (0, 0, 0, 0),
        (-1, -1, 1, 1),
        BandPolicy("portable"),
    )

    assert frames[0].bounds == (-1, -1, 0, 0)


def test_junction_projection_frame_order_matches_randomized_small_brute_oracle() -> None:
    randomizer = random.Random(0xF24A)
    for _fixture in range(64):
        min_x = randomizer.randrange(-2, 3)
        min_y = randomizer.randrange(-2, 3)
        occupied = (
            min_x,
            min_y,
            min_x + randomizer.randrange(1, 4),
            min_y + randomizer.randrange(1, 4),
        )
        left, bottom, right, top = (
            randomizer.randrange(4) for _side in range(4)
        )
        limit = (
            occupied[0] - left,
            occupied[1] - bottom,
            occupied[2] + right,
            occupied[3] + top,
        )
        policy = BandPolicy(
            randomizer.choice(("portable", "100"))
        )

        expected = _brute_junction_projection_frames(occupied, limit, policy)
        actual = freeform._junction_projection_frames(occupied, limit, policy)

        assert _ordered_projection_frames(actual) == _ordered_projection_frames(
            expected
        )


def test_junction_projection_frame_work_is_output_sensitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_calls = 0
    original = finalize._frame_candidates_for_extent

    def counted_candidates(
        width: int,
        height: int,
        policy: BandPolicy,
        *,
        prior_rotated: bool = False,
    ) -> tuple[finalize.FrameCandidate, ...]:
        nonlocal candidate_calls
        candidate_calls += 1
        return original(
            width,
            height,
            policy,
            prior_rotated=prior_rotated,
        )

    monkeypatch.setattr(
        finalize,
        "_frame_candidates_for_extent",
        counted_candidates,
    )

    def measured(size: int) -> tuple[int, int]:
        before = candidate_calls
        frames = freeform._junction_projection_frames(
            (0, 0, 0, 0),
            (-(size // 2 - 1), -(size // 2 - 1), size // 2, size // 2),
            BandPolicy("portable"),
        )
        return candidate_calls - before, len(frames)

    small_calls, small_frames = measured(8)
    large_calls, large_frames = measured(16)

    assert large_frames < 3 * small_frames
    assert large_calls < 3 * small_calls


def test_cleanup_survivor_cache_is_scoped_to_complete_candidate_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine = catalog.building(2303)
    first = (
        PlacedBuilding(
            2303,
            machine.model_index,
            0,
            0,
            width=machine.width,
            height=machine.height,
            owner_strip=1,
        ),
    )
    second = (replace(first[0], owner_strip=2),)
    calls: list[tuple[PlacedBuilding, ...]] = []

    def survivor_bounds(
        placement: Placement,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[int, int, int, int]:
        assert cancelled is not None
        calls.append(placement.buildings)
        owner = placement.buildings[0].owner_strip
        assert owner is not None
        return (owner, 0, owner, 0)

    monkeypatch.setattr(finalize, "_cleanup_survivor_bounds", survivor_bounds)
    cache = freeform._StagedStaticCache()

    assert freeform._cached_cleanup_survivor_bounds(
        cache,
        first,
        cancelled=lambda: False,
    ) == (1, 0, 1, 0)
    assert freeform._cached_cleanup_survivor_bounds(
        cache,
        first,
        cancelled=lambda: False,
    ) == (1, 0, 1, 0)
    assert freeform._cached_cleanup_survivor_bounds(
        cache,
        second,
        cancelled=lambda: False,
    ) == (2, 0, 2, 0)
    assert calls == [first, second]


def test_cleanup_survivor_cache_omits_none_for_legacy_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine = catalog.building(2303)
    buildings = (
        PlacedBuilding(
            2303,
            machine.model_index,
            2,
            3,
            width=machine.width,
            height=machine.height,
        ),
    )
    calls: list[Placement] = []

    def legacy_survivor_bounds(
        placement: Placement,
    ) -> tuple[int, int, int, int]:
        calls.append(placement)
        return placement.bounds

    monkeypatch.setattr(
        finalize,
        "_cleanup_survivor_bounds",
        legacy_survivor_bounds,
    )

    bounds = freeform._cached_cleanup_survivor_bounds(
        freeform._StagedStaticCache(),
        buildings,
    )

    assert bounds == Placement(buildings=buildings).bounds
    assert len(calls) == 1


def test_prospective_projection_matches_finalizer_for_exact_ownerless_pair() -> None:
    belt = catalog.building(2001)
    chemical = catalog.building(2309)
    tower = catalog.building(catalog.TESLA_TOWER_ID)
    buildings = [
        PlacedBuilding(2001, belt.model_index, 0, 0)
        for _index in range(256)
    ]
    buildings[181] = PlacedBuilding(
        2309,
        chemical.model_index,
        0,
        0,
        width=chemical.width,
        height=chemical.height,
        owner_strip=2,
    )
    buildings[255] = PlacedBuilding(
        catalog.TESLA_TOWER_ID,
        tower.model_index,
        2,
        1,
        width=tower.width,
        height=tower.height,
    )
    placement = Placement(buildings=tuple(buildings))
    policy = BandPolicy("portable")
    frames = freeform._junction_projection_frames(
        placement.bounds,
        placement.bounds,
        policy,
    )

    prospective = freeform._prospective_static_failure(
        (
            (181, placement.buildings[181]),
            (255, placement.buildings[255]),
        ),
        frames,
        candidate_index=255,
    )
    with pytest.raises(finalize.ProjectionRefusal) as caught:
        finalize.finalize_placement(placement, policy)

    assert placement.buildings[181].item_id == 2309
    assert placement.buildings[181].owner_strip == 2
    assert placement.buildings[255].item_id == 2201
    assert placement.buildings[255].owner_strip is None
    assert prospective is not None
    assert prospective.buildings == (181, 255)
    assert prospective in caught.value.failures


def test_projected_obstacle_gate_preserves_exact_candidate_verdicts() -> None:
    chemical = catalog.building(2309)
    tower = catalog.building(catalog.TESLA_TOWER_ID)
    base = PlacedBuilding(
        2309,
        chemical.model_index,
        0,
        0,
        width=chemical.width,
        height=chemical.height,
    )
    frames = freeform._junction_projection_frames(
        (0, 0, 30, 5),
        (0, 0, 30, 5),
        BandPolicy("portable"),
    )
    obstacle_index = freeform._ProjectedObstacleIndex.build(((181, base),))

    for x in (0, 2, 5, 20):
        candidate = PlacedBuilding(
            catalog.TESLA_TOWER_ID,
            tower.model_index,
            x,
            1,
            width=tower.width,
            height=tower.height,
        )
        exact = freeform._prospective_static_failure(
            ((181, base), (255, candidate)),
            frames,
            candidate_index=255,
        )
        peers = obstacle_index.candidates(candidate, frames)
        gated = (
            freeform._prospective_static_failure(
                (
                    *((index, base) for index in peers),
                    (255, candidate),
                ),
                frames,
                candidate_index=255,
            )
            if peers
            else None
        )

        assert gated == exact


def test_prospective_static_cache_reuses_only_the_immutable_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chemical = catalog.building(2309)
    tower = catalog.building(catalog.TESLA_TOWER_ID)
    base = PlacedBuilding(
        2309,
        chemical.model_index,
        0,
        0,
        width=chemical.width,
        height=chemical.height,
    )
    candidates = (
        PlacedBuilding(
            catalog.TESLA_TOWER_ID,
            tower.model_index,
            x,
            1,
            width=tower.width,
            height=tower.height,
        )
        for x in (20, 25)
    )
    candidates = tuple(candidates)
    frames = freeform._junction_projection_frames(
        (0, 0, 30, 5),
        (0, 0, 30, 5),
        BandPolicy("portable"),
    )
    expected = tuple(
        freeform._prospective_static_failure(
            ((181, base), (255, candidate)),
            frames,
            candidate_index=255,
        )
        for candidate in candidates
    )

    original = finalize.materialize_frame_building
    materialized: list[PlacedBuilding] = []

    def counted(
        building: PlacedBuilding,
        *,
        bounds: tuple[int, int, int, int],
        candidate: finalize.FrameCandidate,
    ) -> PlacedBuilding:
        materialized.append(building)
        return original(building, bounds=bounds, candidate=candidate)

    monkeypatch.setattr(finalize, "materialize_frame_building", counted)
    cache = freeform._StagedStaticCache()
    actual = tuple(
        freeform._prospective_static_failure(
            ((181, base), (255, candidate)),
            frames,
            candidate_index=255,
            cache=cache,
        )
        for candidate in candidates
    )

    assert actual == expected
    assert materialized.count(base) == len(frames)
    for candidate in candidates:
        assert materialized.count(candidate) == len(frames)


def test_prospective_static_deadline_unwinds_inside_materialization_without_cache_artifact(
) -> None:
    chemical = catalog.building(2309)
    tower = catalog.building(catalog.TESLA_TOWER_ID)
    buildings = (
        (
            181,
            PlacedBuilding(
                2309,
                chemical.model_index,
                0,
                0,
                width=chemical.width,
                height=chemical.height,
            ),
        ),
        (
            255,
            PlacedBuilding(
                catalog.TESLA_TOWER_ID,
                tower.model_index,
                2,
                1,
                width=tower.width,
                height=tower.height,
            ),
        ),
    )
    placement = Placement(buildings=tuple(building for _index, building in buildings))
    frames = freeform._junction_projection_frames(
        placement.bounds,
        placement.bounds,
        BandPolicy("portable"),
    )
    cache = freeform._StagedStaticCache()
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 4

    with pytest.raises(freeform._PreparationDeadline):
        freeform._prospective_static_failure(
            buildings,
            frames,
            candidate_index=255,
            cache=cache,
            cancelled=cancelled,
        )

    assert checks == 4
    assert cache.materialized == {}
    assert cache.clean_contexts == set()
    assert cache.materialized_bases == {}


def test_staged_static_pack_dependent_exhaustion_learns_exact_no_good(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec)
    first = _greedy_pack(strips, 20)
    second = replace(
        first,
        at={
            index: (x + (1 if index == 0 else 0), y)
            for index, (x, y) in first.at.items()
        },
        width=first.width + 1,
        status="repacked",
    )
    packs = iter((first, second))
    seen_no_goods: list[tuple[freeform.ExactPackNoGood, ...]] = []
    failure = finalize.ProjectionFailure(
        "geom.collide",
        (181, 255),
        "build colliders intersect",
        100,
    )
    exact_retry_evidence = freeform._exact_retry_evidence(
        "power",
        failure,
        {
            181: PlacedBuilding(2309, 2309, 0, 0, owner_strip=0),
            255: PlacedBuilding(2201, 2201, 1, 0),
        },
    )
    assert exact_retry_evidence is not None

    def pack_retry(*_args: object, **kwargs: object) -> freeform._Pack:
        no_goods = kwargs.get("exact_pack_no_goods", ())
        assert isinstance(no_goods, tuple)
        assert all(isinstance(item, freeform.ExactPackNoGood) for item in no_goods)
        seen_no_goods.append(no_goods)
        return next(packs)

    def build(
        _spec: BuildSpec,
        _strips: list[Strip],
        pack: freeform._Pack,
        **_kwargs: object,
    ) -> _BuildResult:
        if pack is first:
            raise _Unpowerable(
                "every staged power seat collides after projection",
                failure=failure,
                exact_retry_evidence=exact_retry_evidence,
            )
        return _BuildResult(
            placement=Placement(buildings=(), stats={"belt_tiles": 0.0}),
            routing=DetailedRouteResult(
                status=DetailedRouteStatus.ROUTED,
                routed=(),
                failures=(),
                iterations=0,
                expansions=0,
            ),
            budget_stage=None,
            towers=(),
        )

    monkeypatch.setattr(
        freeform,
        "_band_policy_candidate_heights",
        lambda _strips, _policy: (20,),
    )
    monkeypatch.setattr(freeform, "_pack", pack_retry)
    monkeypatch.setattr(freeform, "_build", build)
    monkeypatch.setattr(
        validate,
        "certify",
        lambda *_args, **_kwargs: validate.Report(findings=()),
    )
    monkeypatch.setattr(
        finalize,
        "finalize_placement",
        _identity_finalizer,
    )

    result = FreeformLayout(
        band_policy=BandPolicy("portable"),
        arrangements=1,
    )._sweep(spec, strips, 1.0)

    assert result is not None
    assert seen_no_goods[0] == ()
    assert len(seen_no_goods[1]) == 1
    learned = seen_no_goods[1][0]
    assert (
        learned.height,
        learned.outline,
        learned.width,
        learned.origins,
        learned.evidence,
    ) == (
        first.height,
        tuple(_box(strip) for strip in strips),
        first.width,
        tuple(first.at[index] for index in range(len(strips))),
        (failure,),
    )


def test_plan_strips_preselects_projection_risk_clearance_for_direct_preparation() -> None:
    freeform._staged_static_preclearance_proved.cache_clear()
    spec = proliferated_spec()
    strips = plan_strips(spec)
    risky = [
        (strip, relation)
        for strip in strips
        for relation in freeform._staged_static_clearance_keys(
            replace(strip, west_channel=freeform._COATER_WEST_CHANNEL)
        )
        if freeform._staged_static_preclearance_proved(
            relation,
            BandPolicy("portable"),
        )
    ]

    assert risky
    assert all(
        strip.west_channel == freeform._COATER_WEST_CHANNEL + 1
        for strip, _relation in risky
    )
    pack = _greedy_pack(strips, _height_seed(strips))
    prepared = _prepare_routing_problem(
        spec,
        strips,
        pack,
        policy=BandPolicy("portable"),
        power=False,
    )
    assert prepared.coaters > 0
    assert prepared.coater_supply_ports


def test_plan_time_preclearance_preserves_candidate_height_schedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = band_160_all_products_spec()
    precleared = plan_strips(spec)
    freeform._staged_static_preclearance_proved.cache_clear()
    monkeypatch.setattr(
        freeform,
        "_staged_static_relation_projection_risks",
        lambda relations, _policy: tuple(False for _relation in relations),
    )
    ordinary = plan_strips(spec)
    monkeypatch.undo()
    freeform._staged_static_preclearance_proved.cache_clear()

    assert freeform._candidate_heights(precleared) == freeform._candidate_heights(
        ordinary
    )


def test_proved_clean_same_strip_relation_skips_only_its_redundant_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coater = PlacedBuilding(
        item_id=catalog.SPRAY_COATER_ID,
        model_index=catalog.building(catalog.SPRAY_COATER_ID).model_index,
        x=0,
        y=0,
        width=1,
        height=1,
        yaw=Facing.EAST.value,
        owner_strip=0,
    )
    peer = PlacedBuilding(
        item_id=catalog.item_id("assembling-machine-2"),
        model_index=catalog.building(
            catalog.item_id("assembling-machine-2")
        ).model_index,
        x=3,
        y=1,
        width=3,
        height=3,
        owner_strip=0,
    )
    other_owner = replace(peer, owner_strip=1)
    risky = replace(peer, x=2)
    monkeypatch.setattr(
        freeform,
        "_staged_static_relation_projection_risk",
        lambda relation, _policy: relation.delta_x == 2,
    )

    retained = freeform._staged_static_projection_peers(
        (peer, other_owner, risky),
        coater,
        owner_strip=0,
        policy=BandPolicy("portable"),
    )

    assert [index for index, _building in retained] == [1, 2]


def test_plan_time_projection_risks_are_batched_and_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeform._staged_static_preclearance_proved.cache_clear()
    batches: list[tuple[freeform.StagedStaticClearanceKey, ...]] = []
    original = freeform._staged_static_relation_projection_risks_uncached

    def counted(
        relations: Sequence[freeform.StagedStaticClearanceKey],
        policy: BandPolicy,
    ) -> tuple[bool, ...]:
        batches.append(tuple(relations))
        return original(relations, policy)

    monkeypatch.setattr(
        freeform,
        "_staged_static_relation_projection_risks_uncached",
        counted,
    )
    spec = proliferated_spec()

    first = plan_strips(spec)
    second = plan_strips(spec)
    monkeypatch.undo()
    freeform._staged_static_preclearance_proved.cache_clear()
    proved = tuple(relation for batch in batches for relation in batch)

    assert first == second
    assert max(map(len, batches)) > 2
    assert len(proved) == len(set(proved))


def test_static_clearance_requirement_regenerates_a_distinct_lane_variant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = proliferated_spec()
    freeform._staged_static_preclearance_proved.cache_clear()
    monkeypatch.setattr(
        freeform,
        "_staged_static_relation_projection_risks",
        lambda relations, _policy: tuple(False for _relation in relations),
    )
    ordinary = plan_strips(spec)
    selected = next(strip for strip in ordinary if "iron-ingot" in strip.in_lanes)
    assert selected.physical_variant is not None
    pose_id = strip_pose_id(selected.physical_variant)
    relation = next(iter(freeform._staged_static_clearance_keys(selected)))
    before_identity = selected.staged_static_variant_id

    extended = plan_strips(
        spec,
        minimum_staged_static_clearance={
            relation: selected.west_channel + 1,
        },
    )
    replacement = next(
        strip
        for strip in extended
        if strip.family_id == selected.family_id
        and strip.machine_start == selected.machine_start
    )
    monkeypatch.undo()
    freeform._staged_static_preclearance_proved.cache_clear()

    assert replacement.west_channel == selected.west_channel + 1
    assert _box(replacement)[0] == _box(selected)[0] + 1
    assert replacement.staged_static_variant_id != before_identity
    assert replacement.physical_variant is not None
    assert strip_pose_id(replacement.physical_variant) == pose_id


def test_staged_static_terminal_exhaustion_is_bounded_across_distinct_assignments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = proliferated_spec()
    strips = plan_strips(spec)
    seen_clearance: list[int] = []
    seen_no_goods: list[tuple[freeform.ExactPackNoGood, ...]] = []
    seen_origins: list[tuple[tuple[int, int], ...]] = []
    failure = finalize.ProjectionFailure(
        "geom.collide",
        (12, 40),
        "build colliders intersect",
        160,
    )

    def pack_retry(
        current: list[Strip],
        *,
        height: int,
        **kwargs: object,
    ) -> freeform._Pack:
        no_goods = kwargs.get("exact_pack_no_goods", ())
        assert isinstance(no_goods, tuple)
        assert all(
            isinstance(no_good, freeform.ExactPackNoGood)
            for no_good in no_goods
        )
        seen_no_goods.append(no_goods)
        assert len(no_goods) <= 1, "W4 permits only one exact-assignment retry"
        baseline = _greedy_pack(current, height)
        shift = len(no_goods)
        shifted = replace(
            baseline,
            at={
                index: (x + (shift if index == 0 else 0), y)
                for index, (x, y) in baseline.at.items()
            },
            width=baseline.width + shift,
            status=f"distinct assignment {shift}",
        )
        origins = tuple(shifted.at[index] for index in range(len(current)))
        assert all(no_good.origins != origins for no_good in no_goods)
        seen_origins.append(origins)
        return shifted

    def refuse(
        _spec: BuildSpec,
        current: list[Strip],
        _pack: freeform._Pack,
        **_kwargs: object,
    ) -> _BuildResult:
        selected_index, selected = next(
            (index, strip)
            for index, strip in enumerate(current)
            if "iron-ingot" in strip.in_lanes
        )
        seen_clearance.append(selected.west_channel)
        relation = next(iter(freeform._staged_static_clearance_keys(selected)))
        requirement = freeform._staged_static_clearance_requirement(
            selected,
            selected_index,
            failure,
            relation,
        )
        assert requirement is not None
        raise freeform._Unseatable(
            "all staged-static seats collide",
            failure=failure,
            clearance_requirement=requirement,
        )

    monkeypatch.setattr(
        freeform,
        "_band_policy_candidate_heights",
        lambda _strips, _policy: (30,),
    )
    monkeypatch.setattr(freeform, "_pack", pack_retry)
    monkeypatch.setattr(freeform, "_build", refuse)
    rejected: list[freeform._RefusalFinding] = []

    result = FreeformLayout(
        band_policy=BandPolicy("portable"),
        arrangements=1,
    )._sweep(spec, strips, 1.0, rejected=rejected)

    assert result is None
    assert seen_clearance == [
        freeform._COATER_WEST_CHANNEL + 1,
        freeform._COATER_WEST_CHANNEL + 1,
    ]
    assert [len(no_goods) for no_goods in seen_no_goods] == [0, 1]
    assert len(set(seen_origins)) == 2
    assert seen_origins[-1] != seen_origins[-2]
    assert seen_no_goods[-1][0].evidence == (failure,)
    assert rejected == [failure]


def test_clearance_feedback_replans_later_base_height_without_minting_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = proliferated_spec()
    freeform._staged_static_preclearance_proved.cache_clear()
    monkeypatch.setattr(
        freeform,
        "_staged_static_relation_projection_risks",
        lambda relations, _policy: tuple(False for _relation in relations),
    )
    strips = plan_strips(spec)
    failure = finalize.ProjectionFailure(
        "geom.collide",
        (12, 40),
        "coater enters its machine after projection",
        160,
    )
    routed = DetailedRouteResult(
        status=DetailedRouteStatus.ROUTED,
        routed=(),
        failures=(),
        iterations=0,
        expansions=0,
    )
    seen_candidates: list[tuple[int, int, int]] = []

    def pack_candidate(
        current: list[Strip],
        *,
        height: int,
        arrangement: int,
        **_kwargs: object,
    ) -> freeform._Pack:
        selected = next(strip for strip in current if "iron-ingot" in strip.in_lanes)
        seen_candidates.append((height, arrangement, selected.west_channel))
        return replace(
            _greedy_pack(current, height),
            status="clearance carry-forward",
        )

    def build_candidate(
        _spec: BuildSpec,
        current: list[Strip],
        pack: freeform._Pack,
        **_kwargs: object,
    ) -> _BuildResult:
        selected_index, selected = next(
            (index, strip)
            for index, strip in enumerate(current)
            if "iron-ingot" in strip.in_lanes
        )
        if pack.height == 20:
            relation = next(iter(freeform._staged_static_clearance_keys(selected)))
            requirement = freeform._staged_static_clearance_requirement(
                selected,
                selected_index,
                failure,
                relation,
            )
            assert requirement is not None
            raise freeform._Unseatable(
                "all staged-static seats collide",
                failure=failure,
                clearance_requirement=requirement,
            )
        assert selected.west_channel == freeform._COATER_WEST_CHANNEL + 1
        return _BuildResult(
            placement=Placement(
                buildings=(),
                stats={
                    "belt_tiles": 0.0,
                    "test_height": float(pack.height),
                },
            ),
            routing=routed,
            budget_stage=None,
            towers=(),
        )

    monkeypatch.setattr(
        freeform,
        "_band_policy_candidate_heights",
        lambda _strips, _policy: (20, 21),
    )
    monkeypatch.setattr(freeform, "_pack", pack_candidate)
    monkeypatch.setattr(freeform, "_build", build_candidate)
    monkeypatch.setattr(
        validate,
        "certify",
        lambda *_args, **_kwargs: validate.Report(findings=()),
    )
    monkeypatch.setattr(
        finalize,
        "finalize_placement",
        _identity_finalizer,
    )

    result = FreeformLayout(
        band_policy=BandPolicy("portable"),
        arrangements=1,
    )._sweep(spec, strips, 1.0)

    monkeypatch.undo()
    freeform._staged_static_preclearance_proved.cache_clear()
    assert result is not None
    assert result.stats["test_height"] == 21.0
    assert seen_candidates == [
        (20, 0, freeform._COATER_WEST_CHANNEL),
        (21, 0, freeform._COATER_WEST_CHANNEL + 1),
    ]


def test_exact_retry_evidence_ignores_assignment_coordinates_but_retains_relation() -> None:
    failure = finalize.ProjectionFailure(
        "geom.collide",
        (3, 8),
        "build colliders intersect",
        160,
    )
    first = {
        3: PlacedBuilding(2309, 64, 4, 9, width=3, height=3, owner_strip=0),
        8: PlacedBuilding(2201, 44, 7, 2, width=2, height=2),
    }
    moved = {
        index: replace(building, x=building.x + 100, y=building.y - 50)
        for index, building in first.items()
    }
    changed_relation = {
        **moved,
        3: replace(moved[3], owner_strip=1),
    }

    evidence = freeform._exact_retry_evidence("power", failure, first)

    assert evidence is not None
    assert freeform._exact_retry_evidence("power", failure, moved) == evidence
    assert (
        freeform._exact_retry_evidence("power", failure, changed_relation)
        != evidence
    )


def test_exact_retry_state_shares_one_candidate_token_across_evidence_sources() -> None:
    failure = finalize.ProjectionFailure(
        "geom.collide",
        (0, 1),
        "build colliders intersect",
        160,
    )
    buildings = {
        0: PlacedBuilding(2309, 64, 0, 0, owner_strip=0),
        1: PlacedBuilding(2201, 44, 2, 0),
    }
    power = freeform._exact_retry_evidence("power", failure, buildings)
    seating = freeform._exact_retry_evidence("seating", failure, buildings)
    assert power is not None
    assert seating is not None
    first = freeform.ExactPackNoGood(
        height=20,
        outline=((4, 5),),
        width=10,
        origins=((1, 2),),
        evidence=(failure,),
    )
    second = replace(first, width=11, origins=((2, 2),))
    state = freeform._ExactPackNoGoodState()

    assert state.admit_retry(
        freeform._ExactRetryKey(20, 0, power),
        first,
        affordable=True,
    )
    assert not state.admit_retry(
        freeform._ExactRetryKey(20, 0, seating),
        second,
        affordable=True,
    )
    assert state.no_goods == [first]


def _sweep_with_repeated_exact_feedback(
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    *,
    affordable: bool,
) -> tuple[
    Placement | None,
    list[tuple[int, int]],
    list[int],
]:
    spec = two_stage_spec()
    strips = plan_strips(spec)
    failure = finalize.ProjectionFailure(
        "geom.collide",
        (0, 1),
        f"{source} exact relation remains impossible",
        160,
    )
    seen_candidates: list[tuple[int, int]] = []
    applicable_no_good_counts: list[int] = []
    exact_retry_evidence = freeform._exact_retry_evidence(
        "power" if source == "power" else "seating",
        failure,
        {
            0: PlacedBuilding(1, 1, 0, 0, owner_strip=0),
            1: PlacedBuilding(1, 1, 1, 0, owner_strip=1),
        },
    )
    assert exact_retry_evidence is not None
    attempts_by_height: dict[int, int] = {}

    def pack_distinct_assignment(
        current: list[Strip],
        *,
        height: int,
        arrangement: int,
        **kwargs: object,
    ) -> freeform._Pack:
        exact_no_goods = kwargs.get("exact_pack_no_goods", ())
        assert isinstance(exact_no_goods, tuple)
        applicable = tuple(
            no_good
            for no_good in exact_no_goods
            if isinstance(no_good, freeform.ExactPackNoGood)
            and no_good.height == height
            and no_good.outline == tuple(_box(strip) for strip in current)
        )
        applicable_no_good_counts.append(len(applicable))
        attempt = attempts_by_height.get(height, 0)
        attempts_by_height[height] = attempt + 1
        if attempt >= 2:
            pytest.fail(
                f"{source} exact feedback admitted more than one retry "
                "for one height/arrangement"
            )
        baseline = _greedy_pack(current, height)
        candidate = replace(
            baseline,
            at={
                index: (x + (attempt if index == 0 else 0), y)
                for index, (x, y) in baseline.at.items()
            },
            width=baseline.width + attempt,
            status=f"{source} distinct assignment {attempt}",
        )
        assignment = (
            candidate.width,
            tuple(candidate.at[index] for index in range(len(current))),
        )
        assert all(
            assignment != (no_good.width, no_good.origins)
            for no_good in applicable
        ), "the fake pack must obey every accumulated exact no-good"
        seen_candidates.append((height, arrangement))
        return candidate

    routed = DetailedRouteResult(
        status=DetailedRouteStatus.ROUTED,
        routed=(),
        failures=(),
        iterations=0,
        expansions=0,
    )

    def build_or_refuse(
        _spec: BuildSpec,
        _strips: list[Strip],
        pack: freeform._Pack,
        **_kwargs: object,
    ) -> _BuildResult:
        placement = Placement(
            buildings=(
                PlacedBuilding(1, 1, 0, 0, owner_strip=0),
                PlacedBuilding(1, 1, 1, 0, owner_strip=1),
            ),
            stats={
                "belt_tiles": 0.0,
                "test_height": float(pack.height),
            },
        )
        if pack.height != 20 or source == "finalizer":
            return _BuildResult(
                placement=placement,
                routing=routed,
                budget_stage=None,
                towers=(),
            )
        if source == "power":
            raise freeform._Unpowerable(
                "exact power relation failed",
                failure=failure,
                exact_retry_evidence=exact_retry_evidence,
            )
        if source == "seating":
            raise freeform._Unseatable(
                "exact coater relation failed",
                failure=failure,
                exact_retry_evidence=exact_retry_evidence,
            )
        raise AssertionError(f"unknown exact-feedback source {source}")

    def finalize_or_refuse(
        placement: Placement,
        _policy: BandPolicy,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> Placement:
        del cancelled
        if source == "finalizer" and placement.stats["test_height"] == 20.0:
            raise finalize.ProjectionRefusal((failure,))
        return placement

    monkeypatch.setattr(
        freeform,
        "_band_policy_candidate_heights",
        lambda _strips, _policy: (20, 21),
    )
    monkeypatch.setattr(freeform, "_pack", pack_distinct_assignment)
    monkeypatch.setattr(freeform, "_build", build_or_refuse)
    monkeypatch.setattr(
        freeform,
        "_projection_pitch_requirements",
        lambda _placement, _strips, failures: (None,) * len(failures),
    )
    monkeypatch.setattr(
        finalize,
        "independent_projection_pair",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        validate,
        "certify",
        lambda *_args, **_kwargs: validate.Report(findings=()),
    )
    monkeypatch.setattr(finalize, "finalize_placement", finalize_or_refuse)
    monkeypatch.setattr(
        freeform,
        "_room_for_another",
        lambda *_args, **_kwargs: affordable,
    )

    result = FreeformLayout(
        band_policy=BandPolicy("portable"),
        arrangements=1,
    )._sweep(spec, strips, 1.0)
    return result, seen_candidates, applicable_no_good_counts


@pytest.mark.parametrize("source", ["power", "seating", "finalizer"])
def test_exact_feedback_admits_at_most_one_distinct_assignment_retry_per_candidate(
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    result, seen_candidates, applicable_counts = _sweep_with_repeated_exact_feedback(
        monkeypatch,
        source,
        affordable=True,
    )

    assert result is not None
    assert result.stats["test_height"] == 21.0
    assert seen_candidates == [(20, 0), (20, 0), (21, 0)]
    assert applicable_counts == [0, 1, 0]


@pytest.mark.parametrize("source", ["power", "seating", "finalizer"])
def test_unaffordable_exact_feedback_preserves_later_base_height(
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    result, seen_candidates, applicable_counts = _sweep_with_repeated_exact_feedback(
        monkeypatch,
        source,
        affordable=False,
    )

    assert result is not None
    assert result.stats["test_height"] == 21.0
    assert seen_candidates == [(20, 0), (21, 0)]
    assert applicable_counts == [0, 0]


def test_unaffordable_base_height_is_not_started_after_valid_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec, strip_len=2)
    routed = DetailedRouteResult(
        status=DetailedRouteStatus.ROUTED,
        routed=(),
        failures=(),
        iterations=0,
        expansions=0,
    )
    seen_heights: list[int] = []

    def pack_candidate(
        current: list[Strip],
        *,
        height: int,
        **_kwargs: object,
    ) -> freeform._Pack:
        seen_heights.append(height)
        return _greedy_pack(current, height)

    def build_candidate(
        _spec: BuildSpec,
        _strips: list[Strip],
        pack: freeform._Pack,
        **_kwargs: object,
    ) -> _BuildResult:
        return _BuildResult(
            placement=Placement(
                buildings=(),
                stats={
                    "belt_tiles": 0.0,
                    "test_height": float(pack.height),
                },
            ),
            routing=routed,
            budget_stage=None,
            towers=(),
        )

    monkeypatch.setattr(
        freeform,
        "_band_policy_candidate_heights",
        lambda _strips, _policy: (20, 21),
    )
    monkeypatch.setattr(freeform, "_pack", pack_candidate)
    monkeypatch.setattr(freeform, "_build", build_candidate)
    monkeypatch.setattr(
        validate,
        "certify",
        lambda *_args, **_kwargs: validate.Report(findings=()),
    )
    monkeypatch.setattr(
        finalize,
        "finalize_placement",
        _identity_finalizer,
    )
    monkeypatch.setattr(
        freeform,
        "_room_for_another",
        lambda *_args, **_kwargs: False,
    )

    result = FreeformLayout(
        band_policy=BandPolicy("portable"),
        arrangements=1,
    )._sweep(spec, strips, 1.0)

    assert result is not None
    assert result.stats["test_height"] == 20.0
    assert seen_heights == [20]


def test_projection_strip_static_objects_retain_non_encoded_owner() -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec)
    pack = _greedy_pack(strips, _height_seed(strips))

    prepared = _prepare_routing_problem(
        spec,
        strips,
        pack,
        policy=BandPolicy("portable"),
        power=False,
        _reserve_ports=False,
    )

    assert prepared.building_templates
    assert all(building.owner_strip is not None for building in prepared.building_templates)
    assert {building.owner_strip for building in prepared.building_templates} == set(
        range(len(strips))
    )
    assert PlacedBuilding(item_id=1, model_index=1, x=0, y=0).owner_strip is None

# --- power -----------------------------------------------------------------


class TestPower:
    def test_the_doubled_integer_reach_is_the_same_predicate(self) -> None:
        """Not a tolerance: the identical test, written twice the size.

        ``_place_power`` compares ``dx2**2 + dy2**2 <= floor((2r)**2)`` on
        doubled integers where it used to compare ``dx**2 + dy**2 <= r**2`` on
        exact rationals.  Those agree because the left side is an integer, so it
        can never land strictly between ``floor((2r)**2)`` and ``(2r)**2``.  If
        that ever stops being true this build ships dark machines, so it is
        checked over every offset a tower could be tested at, including the ring
        where the two forms would differ if the reasoning were wrong.
        """
        tower = catalog.building(catalog.TESLA_TOWER_ID)
        radius = tower.cover_radius
        reach2 = math.floor((2 * radius) ** 2)
        assert radius.denominator != 1, (
            "a whole-number radius would make this test vacuous"
        )
        span = int(radius) + 2
        checked = 0
        for dx in range(-2 * span, 2 * span + 1):
            for dy in range(-2 * span, 2 * span + 1):
                # Both a tile centre against a tower centre (offset by a half
                # tile in each axis) and two tower centres, which is the other
                # pairing the doubled form has to get right.
                for half in (0, 1):
                    exact = (
                        F(dx, 2) + F(half, 2)
                    ) ** 2 + (F(dy, 2) + F(half, 2)) ** 2 <= radius**2
                    doubled = (dx + half) ** 2 + (dy + half) ** 2 <= reach2
                    assert exact == doubled, (dx, dy, half)
                    checked += 1
        assert checked > 4000, checked

    def test_towers_appear_in_production_layout(self) -> None:
        placement = FreeformLayout(
            band_policy=BandPolicy("portable"),
        ).lay_out(two_stage_spec(), time_budget_s=0.5)

        assert placement.stats["towers"] > 0

    def test_every_powered_building_is_covered(self) -> None:
        p = FreeformLayout(
            band_policy=BandPolicy("160"),
        ).lay_out(magnetic_ring_spec(), time_budget_s=1.0)
        report = validate.validate(p, only=["power.coverage", "power.connectivity"])
        assert report.ok, "\n".join(f.message for f in report.errors[:5])

    def test_coverage_check_can_actually_fail(self) -> None:
        """A power check that cannot fail would silently bless a dark factory.

        The failing case has to be a tower that does not *reach*, not a
        placement with no towers at all.  "No towers" is what ``--no-power``
        legitimately produces, and flagging it buried real findings under one
        error per machine.  Here a single tower sits far outside its own 10.5
        supply radius of the assembler, which is a genuine defect.
        """
        assembler = catalog.building(catalog.item_id("assembling-machine-2"))
        tower = catalog.building(catalog.TESLA_TOWER_ID)
        far = int(tower.cover_radius) + 20
        p = Placement(
            buildings=(
                PlacedBuilding(
                    item_id=assembler.item_id,
                    model_index=assembler.model_index,
                    x=0,
                    y=0,
                    width=assembler.width,
                    height=assembler.height,
                ),
                PlacedBuilding(
                    item_id=tower.item_id,
                    model_index=tower.model_index,
                    x=far,
                    y=far,
                    width=tower.width,
                    height=tower.height,
                ),
            )
        )
        report = validate.validate(p, only=["power.coverage"])
        assert not report.ok, "a tower 30 tiles away must not count as covering"



# --- exact arithmetic ------------------------------------------------------


class TestNoFloatEntersCapacityDecisions:
    def test_lane_counts_are_computed_from_exact_fractions(self) -> None:
        from flab2bp.layout.freeform import lanes_for

        # 25/s over a 12/s belt needs 3 lanes; 24/s needs exactly 2, and a float
        # 24.000000001 would wrongly demand 3.
        assert lanes_for(F(25), F(12)) == 3
        assert lanes_for(F(24), F(12)) == 2
        assert lanes_for(F(1, 3), F(12)) == 1

    def test_zero_rate_needs_no_lane(self) -> None:
        from flab2bp.layout.freeform import lanes_for

        assert lanes_for(F(0), F(12)) == 0


# --- proliferator supply ---------------------------------------------------


def _id_map_for(spec: BuildSpec) -> validate.IdMap:
    """The same bridge the pipeline builds, so tests judge what shipping judges."""
    from flab2bp.pipeline import _id_map

    return _id_map(spec)


def _full_report(p: Placement, spec: BuildSpec) -> validate.Report:
    """Validate with the spec attached.

    Without it nine checks are skipped and a broken build reports clean -- which
    is exactly how the unsupplied-coater bug survived this long.
    """
    return validate.validate(p, spec, ids=_id_map_for(spec), expect_power=True)


class TestProliferatorIsActuallySupplied:
    """A coater with nothing to spray is worse than no coater at all.

    It pastes, the machines run, and every proliferated recipe quietly produces
    at the unproliferated rate -- so the build misses the objective with nothing
    visibly wrong.
    """

    def test_some_belt_carries_the_proliferator(self) -> None:
        spec = proliferated_spec()
        p = FreeformLayout(
            band_policy=BandPolicy("portable"),
        ).lay_out(spec, time_budget_s=0.5)
        prolif = {i for i in spec.external_inputs if i.startswith("proliferator")}
        assert prolif, "fixture must declare a proliferator input"
        carried = {
            b.carries_item for b in p.buildings if catalog.is_belt(b.item_id)
        }
        assert carried & prolif, (
            f"no belt carries {sorted(prolif)}; the coaters have nothing to spray with"
        )

    def test_every_coater_has_a_sorter_drawing_from_a_supply_belt(self) -> None:
        spec = proliferated_spec()
        p = FreeformLayout(
            band_policy=BandPolicy("portable"),
        ).lay_out(spec, time_budget_s=0.5)
        report = _full_report(p, spec)
        starved = report.by_check("prolif.coaters_are_supplied")
        assert not starved, "\n".join(f.message for f in starved)

    def test_coaters_sit_on_the_lane_carrying_the_item_they_spray(self) -> None:
        """A coater on some unrelated belt sprays the wrong items."""
        spec = proliferated_spec()
        p = FreeformLayout(
            band_policy=BandPolicy("portable"),
        ).lay_out(spec, time_budget_s=0.5)
        belt_at = {
            (b.x, b.y, b.z): b for b in p.buildings if catalog.is_belt(b.item_id)
        }
        coaters = [b for b in p.buildings if b.item_id == catalog.SPRAY_COATER_ID]
        assert coaters, "fixture must produce at least one coater"
        for c in coaters:
            host = belt_at.get((c.x, c.y, c.z))
            assert host is not None, f"coater at {(c.x, c.y, c.z)} is not on a belt"
            assert host.carries_item in spec.spray_lanes, (
                f"coater sits on a lane carrying {host.carries_item!r}, which is not "
                f"one of the sprayed lanes {sorted(spec.spray_lanes)}"
            )

    def test_no_proliferator_spec_places_no_supply_lane(self) -> None:
        """The machinery must cost nothing when proliferation is off."""
        spec = two_stage_spec()
        p = FreeformLayout(
            band_policy=BandPolicy("portable"),
        ).lay_out(spec, time_budget_s=0.5)
        assert p.stats["spray_coaters"] == 0
        assert not [b for b in p.buildings if b.item_id == catalog.SPRAY_COATER_ID]


class TestSortersCanCarryTheirDemand:
    def test_sorter_tiers_are_chosen_for_the_span_they_actually_span(self) -> None:
        """Tier selection must use the validator's demand basis, not its own.

        The two disagreed: selection divided one item's group total by the
        strip's machine count, while the demand is a machine's *total* input rate
        split across the sorters feeding it. A Mk.I at span 3 sustains 0.5/s and
        was being handed 0.546/s.
        """
        spec = proliferated_spec()
        p = FreeformLayout(
            band_policy=BandPolicy("portable"),
        ).lay_out(spec, time_budget_s=0.5)
        over = _full_report(p, spec).by_check("flow.sorter_capacity")
        assert not over, "\n".join(f.message for f in over)




class TestRealUrlCandidate:
    """One real, tiered, junction-bearing Freeform output contract."""

    URL = (
        "https://factoriolab.github.io/dsp/flow?o=super-magnetic-ring*60"
        "&ibe=conveyor-belt-2"
        "&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab"
        "&mps=proliferator-2-products&v=11"
    )

    @pytest.mark.slow
    def test_unproliferated_candidate_is_complete_valid_and_acyclic(self) -> None:
        from flab2bp.lab.data import load_vendored
        from flab2bp.lab.url import parse_url
        from flab2bp.rates.candidates import (
            DEFAULT_CANDIDATE_POLICIES,
            build_candidates,
        )

        candidates = build_candidates(
            load_vendored(),
            parse_url(self.URL),
            candidate_policies=DEFAULT_CANDIDATE_POLICIES,
        ).candidates
        spec = next(
            candidate for candidate in candidates if candidate.label == "no-proliferator"
        )
        placement = FreeformLayout(
            band_policy=BandPolicy("160"),
        ).lay_out(spec, time_budget_s=2.0)
        sorters = [
            building
            for building in placement.buildings
            if catalog.is_sorter(building.item_id)
        ]
        assert len(sorters) >= 100
        assert len({building.item_id for building in sorters}) >= 3
        assert any(
            building.item_id == catalog.SPLITTER_ID for building in placement.buildings
        )

        report = _full_report(placement, spec)
        assert report.ok, "\n".join(
            f"{finding.check}: {finding.message}" for finding in report.errors
        )
        assert not report.by_check("flow.sorter_capacity")

        for index, building in enumerate(placement.buildings):
            if not catalog.is_belt(building.item_id):
                continue
            seen: set[int] = set()
            current: int | None = index
            while current is not None and current not in seen:
                seen.add(current)
                output = placement.buildings[current].output_obj
                current = (
                    output
                    if output is not None
                    and catalog.is_belt(placement.buildings[output].item_id)
                    else None
                )
            assert current is None, f"belt cycle reachable from building {index}"


def _real_consumers_of(item: str, wanted: int) -> list[str]:
    """Real DSP recipes that consume ``item`` and have a known DSP recipe id.

    Chosen from the dataset rather than hardcoded so this keeps working as the
    recipe table is re-extracted -- a synthetic recipe name would fail at
    ``catalog.recipe_id`` instead of exercising the layout.
    """
    from flab2bp.lab.data import load_vendored

    data = load_vendored()
    known = catalog.known_recipe_ids()
    out: list[str] = []
    for r in data.recipes:
        if r.is_mining or r.is_technology or item not in r.inputs:
            continue
        if r.id in known and all(catalog.get_item_id(o) is not None for o in r.outputs):
            out.append(r.id)
        if len(out) == wanted:
            break
    return out


def fan_out_spec(consumers: int = 4) -> BuildSpec:
    """One producer feeding many consumers.

    A strip gets one output lane per destination, and a sorter spans at most
    three tiles, so a producer with four consumers cannot reach its own bottom
    lane. Every other spec here is small enough that this never arises, which is
    why it survived until a real URL hit it: ``copper-ingot`` feeds four recipes
    in the orbital-collector build.
    """
    sinks = _real_consumers_of("copper-ingot", consumers)
    if len(sinks) < consumers:
        pytest.skip(f"dataset has only {len(sinks)} mapped copper-ingot consumers")
    groups = [
        group(
            "copper-ingot",
            "arc-smelter",
            4 * consumers,
            {"copper-ore": F(1)},
            {"copper-ingot": F(1)},
        )
    ]
    outputs: dict[str, F] = {}
    for rid in sinks:
        from flab2bp.lab.data import load_vendored

        produced = next(iter(load_vendored().recipe(rid).outputs))
        groups.append(
            group(rid, "assembling-machine-2", 2, {"copper-ingot": F(1)}, {produced: F(1)})
        )
        outputs[produced] = F(2)
    return BuildSpec(
        groups=tuple(groups),
        external_inputs={"copper-ore": F(4 * consumers)},
        outputs=outputs,
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label=f"fan-out-{consumers}",
    )


class TestProducerWithManyConsumers:
    """Sharding a group across strips when its destinations exceed sorter reach.

    Raising ``strip_len`` -- what the old error message advised -- cannot help:
    the output-lane count comes from the number of destination GROUPS, which is
    independent of how machines are split into strips. Verified at strip_len
    6, 12, 50 and 500, all identical failures.
    """

    @pytest.mark.parametrize("consumers", [4, 5, 7])
    def test_planning_succeeds_and_respects_sorter_reach(self, consumers: int) -> None:
        strips = plan_strips(fan_out_spec(consumers), strip_len=6)
        assert strips
        for s in strips:
            assert len(s.out_lanes) <= catalog.SORTER_MAX_REACH, (
                f"strip {s.group_key} has {len(s.out_lanes)} output lanes"
            )
            assert len(s.in_lanes) <= catalog.SORTER_MAX_REACH

    def test_every_destination_is_still_served(self) -> None:
        """Sharding must not drop a consumer -- that starves it silently."""
        spec = fan_out_spec(5)
        strips = plan_strips(spec, strip_len=6)
        served = {
            dest
            for s in strips
            if s.recipe_id == "copper-ingot"
            for _item, dest, _cargo_domain in s.out_lanes
            if dest
        }
        wanted = {
            f"{g.recipe_id}#{i}"
            for i, g in enumerate(spec.groups)
            if "copper-ingot" in g.inputs_per_machine
        }
        assert served == wanted, f"missing destinations: {wanted - served}"

    def test_all_machines_survive_sharding(self) -> None:
        spec = fan_out_spec(5)
        strips = plan_strips(spec, strip_len=6)
        assert sum(s.machines for s in strips) == spec.machine_count

    def test_it_lays_out_and_validates(self) -> None:
        """Pinned to one worker, and route failures asserted separately.

        The shipping default is multi-worker CP-SAT, which is deliberately
        nondeterministic: different runs land on different packs, and the harder
        ones leave a net unrouted, which `flow.lane_sourced` then correctly
        reports as a dry lane. Left unpinned this test passed or failed by which
        worker happened to win.

        `route_failures` is asserted in its own right rather than left to
        `report.ok`, so the test cannot pass by producing a layout that quietly
        dropped a connection.
        """
        spec = fan_out_spec(4)
        p = FreeformLayout(
            band_policy=BandPolicy("160"),
            workers=DETERMINISTIC_WORKERS,
        ).lay_out(
            spec, time_budget_s=0.5
        )
        assert p.stats.get("route_failures", 0) == 0, "a net went unrouted"
        report = _full_report(p, spec)
        assert report.ok, "\n".join(f"{f.check}: {f.message}" for f in report.errors[:8])


# --- mixed-item lanes ------------------------------------------------------


def five_input_spec() -> BuildSpec:
    """A REAL five-ingredient recipe on an Assembling Machine.

    ``miniature-particle-collider`` takes five things and makes one, in an
    assembler.  Five is the most a lane-fed machine can carry -- three insert
    poses on the north face and three on the south, one of the south three spent
    on the output lane -- and an assembler's ROW caps are tighter than that, so
    seating five forces a shared lane.  That is what keeps mixed lanes under
    test now that six ingredients are refused.

    Deliberately a real recipe, not a synthesised one: a made-up name plans
    perfectly well and then dies at ``catalog.recipe_id``, so a synthetic-only
    test would pass while the feature stayed broken.
    """
    ingredients = [
        "frame-material",
        "graphene",
        "processor",
        "super-magnetic-ring",
        "titanium-alloy",
    ]
    return BuildSpec(
        groups=(
            group(
                "miniature-particle-collider",
                "assembling-machine-2",
                2,
                {i: F(1) for i in ingredients},
                {"miniature-particle-collider": F(1)},
            ),
        ),
        external_inputs={i: F(2) for i in ingredients},
        outputs={"miniature-particle-collider": F(2)},
    )


def six_input_spec() -> BuildSpec:
    """A REAL six-ingredient recipe, fed entirely from outside.

    ``universe-matrix`` takes antimatter plus all five lower matrices and runs in
    a Matrix Lab.  Six inputs plus one output is seven lanes, and two sides of
    three cannot carry that one-item-per-lane -- which is what mixing is for.

    Deliberately a real recipe, not a synthesised one: a made-up name plans
    perfectly well and then dies at ``catalog.recipe_id``, so a synthetic-only
    test would pass while the feature stayed broken.
    """
    ingredients = [
        "antimatter",
        "electromagnetic-matrix",
        "energy-matrix",
        "gravity-matrix",
        "information-matrix",
        "structure-matrix",
    ]
    return BuildSpec(
        groups=(
            group(
                "universe-matrix",
                "matrix-lab",
                2,
                {i: F(1) for i in ingredients},
                {"universe-matrix": F(1)},
            ),
        ),
        external_inputs={i: F(2) for i in ingredients},
        outputs={"universe-matrix": F(2)},
        belt_item_id="conveyor-belt-3",
        belt_items_per_second=F(30),
        label="six-input",
    )


def _lane_runs(p: Placement) -> dict[int, set[int]]:
    """Belt RUN -> the set of non-zero sorter filters drawing from it.

    This is the signal the validator keys on to spot a shared lane, and it is
    per-RUN rather than per-tile: each machine is served from its own column, so
    two items sharing a lane attach to two different belt tiles of the same
    forward-linked run. Collecting filters per tile would miss that entirely.

    A sorter only carries a filter when its lane is mixed, so a run with two
    distinct filters against it provably carries two items.
    """
    # Forward-linked belt chains, collapsed to a representative index.
    run_of: dict[int, int] = {}
    for i, b in enumerate(p.buildings):
        if not catalog.is_belt(b.item_id):
            continue
        run_of.setdefault(i, i)
        nxt = b.output_obj
        if (
            nxt is not None
            and 0 <= nxt < len(p.buildings)
            and catalog.is_belt(p.buildings[nxt].item_id)
        ):
            run_of[nxt] = run_of[i]

    filters: dict[int, set[int]] = {}
    for b in p.buildings:
        if not catalog.is_sorter(b.item_id) or not b.filter_id:
            continue
        if b.input_obj is None or b.input_obj not in run_of:
            continue
        filters.setdefault(run_of[b.input_obj], set()).add(b.filter_id)
    return filters


class TestMixedItemLanes:
    """One item per lane is our simplification, not a DSP rule.

    Measured across the fixture corpus, 236 of 1,288 real sorters carry a
    filter, and ``falk-v7-mall-full`` filters 100% of its 196 -- bus designs
    where several items share a belt and filtered sorters pick off the one they
    want.
    """

    def test_a_six_ingredient_recipe_builds_with_its_product_leaving_east(self) -> None:
        """``universe-matrix`` wants seven connections and a Matrix Lab has twelve.

        THIS TEST HAS ASSERTED BOTH ANSWERS BEFORE THIS ONE.  It first asserted
        that six ingredients seated, and the plan it was blessing put THREE
        sorters onto slot 6 and three onto slot 7 of every Matrix Lab -- four
        shared slots per build, four ingredients pasting unwired, because
        ``WriteObjectConn`` evicts rather than refuses.  It then asserted the
        refusal that replaced it, which was honest and was still reading two of
        the machine's four faces.

        What it asserts now is the whole of it: six ingredients on the north and
        south faces, the product out the EAST face into a belt in the gap column,
        and a placement the validator accepts.  ``game.slot_occupancy`` is
        unchanged and is part of what accepts it -- seven connections, seven
        distinct slots, on a building the game gives twelve.
        """
        spec = six_input_spec()
        strips = plan_strips(spec, strip_len=6)
        assert strips and all(s.flank_outputs for s in strips)
        p = FreeformLayout(
            band_policy=BandPolicy("portable"),
        ).lay_out(spec, time_budget_s=0.5)
        report = _full_report(p, spec)
        assert report.ok, "\n".join(f"{f.check}: {f.message}" for f in report.errors[:8])

    def test_the_seventh_connection_lands_on_a_face_no_lane_can_reach(self) -> None:
        """The extra slot is EARNED, not borrowed from a lane the plan already had.

        Without this the test above could pass on a build that had quietly gone
        back to seating seven sorters over six lane-reachable slots -- the
        occupancy check convicts two sorters on ONE slot, and would say nothing
        about seven sorters spread over six slots and one machine left unfed.

        So: every Matrix Lab carries seven connections with seven distinct slot
        indices, and at least one of those indices is a slot NO lane row can
        name, north or south, at any distance a sorter reaches.  That slot is on
        the east face and there is nowhere else it could have come from.
        """
        spec = six_input_spec()
        p = FreeformLayout(
            band_policy=BandPolicy("portable"),
        ).lay_out(spec, time_budget_s=0.5)
        labs = {
            i
            for i, b in enumerate(p.buildings)
            if b.item_id == catalog.item_id("matrix-lab")
        }
        assert labs, "the spec builds Matrix Labs or this proves nothing"

        from flab2bp.layout import slots as slot_table

        item_id = catalog.item_id("matrix-lab")
        yaw = slot_table.lane_orientation(item_id)
        probe = slot_table.probe_building(item_id, yaw)
        lane_reachable: set[int] = set()
        for lane_y in list(range(-catalog.SORTER_MAX_REACH, 0)) + list(
            range(probe.height, probe.height + catalog.SORTER_MAX_REACH)
        ):
            for a in slot_table.attachable_columns(probe, lane_y).values():
                lane_reachable.add(a.slot)

        named: dict[int, list[int]] = {}
        for b in p.buildings:
            for link, slot in ((b.output_obj, b.output_to_slot), (b.input_obj, b.input_from_slot)):
                if link in labs and slot >= 0:
                    named.setdefault(link, []).append(slot)
        assert named, "no connection names a Matrix Lab at all"
        for lab, slot_ids in named.items():
            assert len(slot_ids) == len(set(slot_ids)), (
                f"lab {lab} names slot(s) twice: {sorted(slot_ids)}"
            )
            assert len(slot_ids) == 7, (
                f"lab {lab} carries {len(slot_ids)} connections, not six ingredients "
                f"and a product: {sorted(slot_ids)}"
            )
            assert set(slot_ids) - lane_reachable, (
                f"lab {lab} used only slots a north or south lane can reach "
                f"({sorted(lane_reachable)}); the east face was never used"
            )

    def test_a_five_ingredient_recipe_still_mixes_and_validates(self) -> None:
        """Mixing is not dead, it is bounded.  Five fits, and has to keep fitting.

        Without this, the column bound could tighten to "one item per lane" and
        every mixed-lane test above would still pass by refusing.
        """
        spec = five_input_spec()
        strips = plan_strips(spec, strip_len=6)
        assert max(len(lane) for lane in strips[0].in_above + strips[0].in_below) > 1
        p = FreeformLayout(
            band_policy=BandPolicy("portable"),
        ).lay_out(spec, time_budget_s=0.5)
        report = _full_report(p, spec)
        assert report.ok, "\n".join(f"{f.check}: {f.message}" for f in report.errors[:8])

    def test_every_sorter_on_a_mixed_lane_is_filtered(self) -> None:
        """An unfiltered sorter on a shared lane grabs whatever passes.

        That starves the machine that needed the other item, and nothing about
        the paste looks wrong -- so this is correctness, not tidiness.
        """
        spec = five_input_spec()
        p = FreeformLayout(
            band_policy=BandPolicy("portable"),
        ).lay_out(spec, time_budget_s=0.5)
        shared = _lane_runs(p)
        assert shared, "a five-input strip must produce at least one mixed lane"
        assert any(len(f) > 1 for f in shared.values()), (
            "expected some belt to be drawn from under two different filters"
        )

    def test_unmixed_lanes_stay_unfiltered(self) -> None:
        """The signal only means something if it is absent when lanes are pure.

        If ordinary strips also filtered, the validator could not tell a shared
        lane from a plain one and would keep applying its single-commodity
        decomposition to a lane it had not actually checked.
        """
        p = fallback_placement(
            magnetic_ring_spec(),
            band_policy=BandPolicy("portable"),
            power=False,
        )
        assert not _lane_runs(p), "no lane in this spec is shared, so none may filter"


# --- mode-driven machines --------------------------------------------------


def mode_driven_spec() -> BuildSpec:
    """An Energy Exchanger charging accumulators.

    ``accumulator-full`` is a MODE, not a craft: DSP has no recipe id for it and
    the job is selected by a word in the parameter block.
    """
    return BuildSpec(
        groups=(
            group(
                "accumulator-full",
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
        label="mode-driven",
    )


def _assert_energy_exchanger_port_routing(
    placement: Placement,
    spec: BuildSpec,
) -> None:
    buildings = placement.buildings
    machine_indices = tuple(
        index
        for index, building in enumerate(buildings)
        if building.model_index == 45
    )
    assert machine_indices
    assert not any(catalog.is_sorter(building.item_id) for building in buildings)
    for machine_index in machine_indices:
        machine = buildings[machine_index]
        docks = slots.port_docks(machine)
        feeders = tuple(
            building
            for building in buildings
            if catalog.is_belt(building.item_id)
            and building.output_obj == machine_index
        )
        products = tuple(
            building
            for building in buildings
            if catalog.is_belt(building.item_id)
            and building.input_obj == machine_index
        )

        assert len(feeders) == len(products) == 1
        feeder = feeders[0]
        product = products[0]
        feed_dock = docks[feeder.output_to_slot]
        product_dock = docks[product.input_from_slot]
        assert feed_dock.port != product_dock.port
        assert (feeder.x, feeder.y, feeder.z) == (*feed_dock.cell, F(0))
        assert feeder.yaw == feed_dock.facing.opposite().value
        assert feeder.output_from_slot == rules.BELT_PORT_FEED_FROM_SLOT
        assert (product.x, product.y, product.z) == (*product_dock.cell, F(0))
        assert product.yaw == product_dock.facing.value
        assert product.input_to_slot == rules.BELT_PORT_DRAW_TO_SLOT

    assert validate.certify(placement, spec, expect_power=True).ok


class TestModeDrivenMachines:
    """Some machines are configured by a MODE, not a recipe id.

    An Energy Exchanger's charge/discharge lives in its parameter block while
    ``recipe_id`` stays zero.  FactorioLab models these as ordinary recipes with
    real item flow, so they plan like anything else -- only the emission and,
    as it turns out, the WIRING differ.
    """

    def test_empty_sorter_poses_use_exact_bidirectional_prefab_ports(self) -> None:
        info = catalog.building(catalog.ENERGY_EXCHANGER_ID)
        assert info.model_index == 45
        assert info.slot_poses == ()
        assert len(info.port_poses) == 4

        spec = mode_driven_spec()
        placement = FreeformLayout(
            band_policy=BandPolicy("portable"),
        ).lay_out(spec, time_budget_s=4.0)

        _assert_energy_exchanger_port_routing(placement, spec)

    def test_the_machine_carries_the_mode_not_a_recipe(self) -> None:
        """Asked of the unit that decides it, since no placement reaches here.

        This used to read the emitted buildings.  A refused spec has none, so
        the question moves to where it is actually answered: the strip plan
        carries the parameter block, and ``_emit_strip`` writes ``recipe_id=0``
        for exactly those strips -- the rule asserted below on a strip that DOES
        emit, so neither half of the branch is untested.
        """
        from flab2bp.dsp import params

        s = plan_strips(mode_driven_spec(), strip_len=6)[0]
        assert s.item_id == catalog.ENERGY_EXCHANGER_ID
        assert s.is_mode_driven, "a mode-driven strip must say so"
        assert s.mode_params == params.parameters_for("accumulator-full")

    def test_an_ordinary_recipe_still_carries_a_recipe_id(self) -> None:
        """The mode path must not swallow normal machines.

        The other half of ``_emit_strip``'s branch, on a spec that lays out --
        without it, deleting the branch entirely would leave every assertion
        above green.
        """
        p = FreeformLayout(
            band_policy=BandPolicy("portable"),
        ).lay_out(single_recipe_spec(), time_budget_s=0.5)
        smelters = [b for b in p.buildings if b.recipe_id]
        assert smelters, "the fixture must emit machines with a recipe id"
        assert all(b.parameters == () for b in smelters)

    def test_charge_and_discharge_differ(self) -> None:
        """A guard on the poles: emitting the wrong one drains what it should fill."""
        from flab2bp.dsp import params

        assert params.parameters_for("accumulator-full") != params.parameters_for(
            "accumulator-discharge"
        )


# --- sharded groups are fed on every shard ---------------------------------


def sharded_consumer_spec() -> BuildSpec:
    """A consumer big enough to shard, fed by a single producer strip.

    Eight machines at ``strip_len`` 6 become two strips, and each carries its
    OWN input lane. ``out_lanes`` names the destination GROUP, not the strip, so
    one output lane has to reach both shards; feeding only one leaves the other
    with belts, sorters, and nothing moving along them.
    """
    return BuildSpec(
        groups=(
            group("iron-ingot", "arc-smelter", 8, {"iron-ore": F(1)}, {"iron-ingot": F(1)}),
            group("gear", "assembling-machine-2", 8, {"iron-ingot": F(1)}, {"gear": F(1)}),
        ),
        external_inputs={"iron-ore": F(8)},
        outputs={"gear": F(8)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="sharded-consumer",
    )


class TestShardedGroupsAreFedOnEveryShard:
    """Keying ports by group let one shard overwrite another's.

    Traced on a real build: `gear#4` had one output lane to `electric-motor#1`,
    that group held two strips, and only the strip whose port happened to be
    stored last became a net sink. The other strip's lane was never filled and
    its four machines starved -- while the build reported `route_failures == 0`,
    because the net that existed did route and the missing one was never created
    to fail.
    """

    def test_the_fixture_actually_shards(self) -> None:
        """Otherwise the test below proves nothing."""
        strips = plan_strips(sharded_consumer_spec(), strip_len=6)
        consumers = [s for s in strips if s.group_key.startswith("gear")]
        assert len(consumers) >= 2, (
            f"expected the consumer to shard, got {len(consumers)} strip(s); "
            "raise the machine count or lower strip_len"
        )

    def test_no_shard_is_left_starving(self) -> None:
        spec = sharded_consumer_spec()
        p = FreeformLayout(
            band_policy=BandPolicy("100"),
            workers=DETERMINISTIC_WORKERS,
        ).lay_out(
            spec, time_budget_s=0.5
        )
        report = _full_report(p, spec)
        starved = [f for f in report.errors if f.check == "flow.lane_sourced"]
        assert not starved, "\n".join(f.message for f in starved)

    def test_a_sharded_producer_has_every_lane_drained(self) -> None:
        """The mirror case: several producer strips shipping to one consumer.

        Sharding a producer gives its strips the SAME destination set, so the
        output side collided identically and left dead belts behind.
        """
        spec = BuildSpec(
            groups=(
                group("iron-ingot", "arc-smelter", 12, {"iron-ore": F(1)}, {"iron-ingot": F(1)}),
                group("gear", "assembling-machine-2", 2, {"iron-ingot": F(1)}, {"gear": F(1)}),
            ),
            external_inputs={"iron-ore": F(12)},
            outputs={"gear": F(2)},
            belt_item_id="conveyor-belt-2",
            belt_items_per_second=F(12),
            label="sharded-producer",
        )
        producers = [
            s for s in plan_strips(spec, strip_len=6) if s.group_key.startswith("iron-ingot")
        ]
        assert len(producers) >= 2, "fixture must shard the producer"
        p = FreeformLayout(
            band_policy=BandPolicy("portable"),
            workers=DETERMINISTIC_WORKERS,
        ).lay_out(
            spec, time_budget_s=0.5
        )
        report = _full_report(p, spec)
        starved = [f for f in report.errors if f.check == "flow.lane_sourced"]
        assert not starved, "\n".join(f.message for f in starved)


# --- the block's extent -----------------------------------------------------


def _belt(x: int, y: int, *, item: str | None = None) -> PlacedBuilding:
    return PlacedBuilding(
        item_id=2001, model_index=35, x=x, y=y, width=1, height=1, carries_item=item
    )


@pytest.mark.parametrize(
    "item_id",
    (catalog.TESLA_TOWER_ID, catalog.SPRAY_COATER_ID),
)
def test_linkless_static_extension_rechecks_orthogonal_cleanup_survivors(
    item_id: int,
) -> None:
    coordinates = ((-2, 0), (1, -3), (-3, 0), (-3, -1), (5, 0), (3, 6))
    belts = tuple(
        replace(
            _belt(x, y),
            input_obj=index - 1 if index else None,
            output_obj=index + 1 if index + 1 < len(coordinates) else None,
        )
        for index, (x, y) in enumerate(coordinates)
    )
    anchor_info = catalog.building(2302)
    anchor = PlacedBuilding(
        item_id=2302,
        model_index=anchor_info.model_index,
        x=2,
        y=4,
        width=anchor_info.width,
        height=anchor_info.height,
    )
    prefix = finalize._CleanupSurvivorGraph(
        Placement(buildings=(*belts, anchor))
    )
    bounds = prefix.snapshot_bounds()
    candidate_info = catalog.building(item_id)
    candidate = PlacedBuilding(
        item_id=item_id,
        model_index=candidate_info.model_index,
        x=9,
        y=4,
        width=candidate_info.width,
        height=candidate_info.height,
    )
    direct_union = (
        min(bounds[0], candidate.x),
        min(bounds[1], candidate.y),
        max(bounds[2], candidate.x + candidate.width - 1),
        max(bounds[3], candidate.y + candidate.height - 1),
    )
    expected_prefix, expected_bounds = prefix.extended_snapshot(
        (candidate,),
        bounds,
    )

    observed_prefix, observed_bounds = (
        freeform._cleanup_snapshot_with_linkless_static(
            prefix,
            bounds,
            candidate,
        )
    )

    assert expected_bounds != direct_union
    assert expected_bounds[:2] == (-3, -3)
    assert observed_bounds == expected_bounds
    assert observed_prefix.snapshot_bounds() == expected_prefix.snapshot_bounds()


def _packable_machine_ids() -> set[int]:
    """Every machine item a recipe or mode-driven spec group can select."""
    from flab2bp.lab.data import load_vendored

    out = {
        item_id
        for recipe in load_vendored().recipes
        for producer in recipe.producers
        if (item_id := catalog.get_item_id(producer)) is not None
    }
    out.update(entry.machine_item_id for entry in catalog.MODE_DRIVEN_MACHINE.values())
    return out


class TestABuildingDeniesOnlyTheBandUnderItsCollider:
    """A machine is not solid at every altitude, and the game never said it was.

    The belt half of a blueprint paste is ONE sphere against the build
    collider -- ``BuildTool_BlueprintPaste.cs:2179``, dump line 145760 -- with
    no footprint term and no ceiling.  Colliders start at the ground and rise,
    so what a building denies a belt is a BAND, and
    :func:`colliders.belt_crossing_height` is where its top comes from.
    ``freeform`` used to blank the whole column instead, which is the invented
    constraint this class exists to keep deleted.
    """

    @staticmethod
    def _at(item_id: int, x: int, y: int) -> PlacedBuilding:
        b = catalog.building(item_id)
        return PlacedBuilding(
            item_id=item_id,
            model_index=b.model_index,
            x=x,
            y=y,
            width=b.width,
            height=b.height,
        )

    def test_a_belt_may_stand_above_a_splitters_collider(self) -> None:
        """The whole of it, on the cell that used to be blanked.

        A Splitter's collider tops out at blueprint ``z = 1.7475``, so level 2
        clears it and levels 0 and 1 do not.  Before this rule was the game's,
        all three read blocked.
        """
        top = LEVELS - 1
        assert top * freeform._LEVEL_HEIGHT > colliders.belt_crossing_height(
            catalog.building(2020).model_index
        ), "pick a shorter building: this one does not fit under the lattice"
        canvas = _Canvas()
        canvas.add(self._at(2020, 5, 5), solid=True)
        assert canvas.free((5, 5, top)), (
            f"level {top} sits above a Splitter's collider and the game sells "
            "the crossing; freeform refused it"
        )
        assert not canvas.free((5, 5, 0)) and not canvas.free((5, 5, 1)), (
            "the band under the collider is still the game's rule and must "
            "still be refused"
        )

    def test_the_flat_grid_agrees_with_free_about_that_cell(self) -> None:
        """The grid is what A* searches, so a grid that disagrees is the bug.

        Documented in ``_make_grid``: when the two disagreed the other way, A*
        returned paths ``_commit_paths`` then refused, and the net was dropped
        round after round with nothing learning anything.
        """
        canvas = _Canvas(limit=(0, 0, 10, 10))
        canvas.add(self._at(2020, 5, 5), solid=True)
        grid = _make_grid(canvas, (0, 0, 10, 10), (0, 0, 10, 10), {})
        for lvl in range(LEVELS):
            cell = (5, 5, lvl)
            assert bool(grid.occ[grid.index(cell)]) == canvas.free(cell), (
                f"grid and _Canvas.free disagree at {cell}"
            )

    def test_no_machine_is_ever_crossable_below_level_three(self) -> None:
        """Deleting an invented rule must not delete the real one under it.

        The SHORTEST collider in the packable set is a Mining Machine's at
        2.6100, so levels 0, 1 and 2 are under every production machine there
        is and a belt on any of them pastes as ``EBuildCondition.Collide``.
        That is the floor this class defends, and it is stated in levels rather
        than in ``LEVELS`` so it keeps meaning the same thing when the lattice
        grows: it was the whole column at ``LEVELS = 3``, which is why the rule
        change shipped no geometry at all, and it is still the bottom three
        when the lattice offers more.
        """
        forced = {lvl for lvl in range(LEVELS) if lvl <= 2}
        for item_id in _packable_machine_ids() | {catalog.TESLA_TOWER_ID}:
            canvas = _Canvas()
            canvas.add(self._at(item_id, 5, 5), solid=True)
            for lvl in forced:
                assert not canvas.free((5, 5, lvl)), (
                    f"{catalog.building(item_id).name} reads passable at level "
                    f"{lvl}; its collider tops out at "
                    f"{colliders.belt_crossing_height(catalog.building(item_id).model_index)}"
                )

    def test_the_band_is_exactly_what_the_full_collider_probe_says(self) -> None:
        """The band against the game's own geometry, model by model.

        ``_crossing_ban_levels`` reads one closed-form bound;
        :func:`colliders.belt_crossings` places the actual 0.23 probe sphere at
        the actual altitude against the actual collider boxes.  They are
        independent routes to the same answer, so a disagreement is a real
        defect in one of them -- under-banning ships belts the game pastes as
        ``Collide``, over-banning is the invented rule creeping back.

        Swept over the whole footprint plus a ring, because "no footprint term"
        is itself part of the claim: the collider's top governs at the centre
        and at the edge alike.
        """
        for item_id in _packable_machine_ids() | {catalog.TESLA_TOWER_ID, 2020, 2030}:
            info = catalog.building(item_id)
            banned = set(freeform._crossing_ban_levels(self._at(item_id, 0, 0)))
            placed = colliders.Placed(info.model_index, 0.0, 0.0, 0.0, 0.0)
            w, h = catalog.footprint(item_id)
            tiles = [
                (dx, dy)
                for dx in range(-(w // 2) - 1, w // 2 + 2)
                for dy in range(-(h // 2) - 1, h // 2 + 2)
            ]
            for lvl in range(LEVELS):
                z = float(lvl * freeform._LEVEL_HEIGHT)
                probe = [colliders.Placed(35, dx, dy, z, 0.0) for dx, dy in tiles]
                hits = bool(colliders.belt_crossings(probe, [placed]))
                assert (lvl in banned) == hits, (
                    f"{info.name} at level {lvl}: the band says "
                    f"{'banned' if lvl in banned else 'free'} and the probe says "
                    f"{'blocked' if hits else 'clear'}"
                )

    def test_the_bound_is_a_lookup_and_not_one_constant(self) -> None:
        """A rule that varies by model may not be flattened to a literal.

        Depot Mk.I and Mk.II are the same family and do not share a collider
        (1.897 against 2.835), so a single number here would be right by
        coincidence for one of them.  Assembling Machine Mk.I/II/III DO share
        one, which is why "it varies by tier" cannot be assumed either -- only
        the model's own collider answers.
        """
        got = {
            item_id: freeform._crossing_ban_levels(self._at(item_id, 0, 0))
            for item_id in (2011, 2020, 2101, 2102, 2303, 2305)
        }
        assert got[2011] != got[2020], "Sorter and Splitter share a ban band"
        assert got[2101] != got[2102], "Depot Mk.I and Mk.II share a ban band"
        assert got[2303] == got[2305], (
            "Assembling Machine Mk.I and Mk.III share a collider, so they must "
            "share a band -- a per-tier guess would separate them"
        )

    def test_the_band_rises_with_the_buildings_own_altitude(self) -> None:
        """The bound is measured from the building's ground, not the world's."""
        low = freeform._crossing_ban_levels(self._at(2011, 0, 0))
        high = freeform._crossing_ban_levels(
            dataclasses.replace(self._at(2011, 0, 0), z=F(2))
        )
        assert len(high) > len(low), (
            f"a Sorter lifted to z=2 must deny more of the lattice than one on "
            f"the ground; got {low} then {high}"
        )


class TestPortAccessIsReservedForEveryRole:
    """A port with two jobs needs two ways in, and never at another's expense."""

    def test_a_port_that_both_sends_and_receives_holds_two_cells(self) -> None:
        """One cell cannot serve a hop arriving and a hop leaving.

        A coater's drop belt is exactly this: the proliferator chain reaches it
        from the previous coater and leaves it for the next.  With one access
        cell the first net to route took it and built on it, and the second was
        handed an empty goal set -- which the router papered over by merging
        into a sibling path, carrying the item PAST the drop instead of into it.
        """
        canvas = _Canvas()
        for x in (0, 4, 8):
            canvas.add(_belt(x, 0))
        a = _Port(0, 0, 0, 0, 0)
        b = _Port(1, 4, 0, 4, 4)
        c = _Port(2, 8, 0, 8, 8)
        _reserve_port_access(canvas, [_Net(src=a, dst=b, item="x"), _Net(src=b, dst=c, item="x")])
        held = {
            key: sum(1 for k in canvas.reserved.values() if k == key)
            for key in ((0, 0, 0), (4, 0, 0), (8, 0, 0))
        }
        assert held[(4, 0, 0)] == 2, (
            "the middle port both sends and receives but holds "
            f"{held[(4, 0, 0)]} cells"
        )
        assert held[(0, 0, 0)] == 1 and held[(8, 0, 0)] == 1, held

    def test_a_second_cell_never_takes_another_port_s_only_one(self) -> None:
        """Every port gets its first cell before any port gets its second.

        ``q`` is served first (ties break on coordinates) and wants two.  Its
        second choice is the one and only cell ``p`` can ever be reached
        through, so taking it would not cost ``p`` a better route -- it would
        cost ``p`` every route, and hand its net an empty goal set.
        """
        canvas = _Canvas()
        canvas.add(_belt(0, 0))  # q, wants two: sends and receives
        canvas.add(_belt(-2, 0))  # p, wants one
        canvas.add(_belt(4, 0))  # somewhere for q to send to
        for cell in ((0, 1), (0, -1), (-3, 0), (-2, 1), (-2, -1)):
            canvas.add(_belt(*cell))
        q = _Port(0, 0, 0, 0, 0)
        p = _Port(1, -2, 0, -2, 0)
        far = _Port(2, 4, 0, 4, 4)
        _reserve_port_access(
            canvas, [_Net(src=p, dst=q, item="x"), _Net(src=q, dst=far, item="x")]
        )
        assert canvas.reserved.get((-1, 0, 0)) == (-2, 0, 0), (
            "the only cell that reaches p was taken by q's second claim: "
            f"{canvas.reserved.get((-1, 0, 0))}"
        )

    def test_a_port_with_a_choice_is_moved_rather_than_starving_one_without(
        self,
    ) -> None:
        """First-come-first-served is not good enough; this is a matching.

        The shape is taken from the only net that stranded on
        ``universe-matrix/max-proliferation`` at h=115, in all seven rip-up
        rounds of three separate runs.  A coater drop sits mid-chain, so it both
        receives and sends and wants two cells, and the packing leaves it
        exactly two.  A neighbouring port sorts earlier, takes one of them, and
        has somewhere else it could perfectly well have gone -- but a greedy pass
        never asks it to move, so the drop got one cell, the arriving hop took
        it, and the leaving hop was handed an EMPTY start set.  A\\* then returns
        ``None`` having expanded no nodes, which rip-up cannot price, because a
        search that expands nothing registers no conflict.

        ``d`` is the drop: free to its east and north, walled west and south.
        ``e`` is the neighbour: free into ``d``'s north cell and free further
        west.  An assignment satisfying both exists, so both must be satisfied.
        """
        canvas = _Canvas()
        canvas.add(_belt(0, 0))  # d, wants two
        canvas.add(_belt(-1, -1))  # e, wants one
        for cell in ((-1, 0), (0, 1), (-1, -2)):
            canvas.add(_belt(*cell))  # the walls that leave d only two ways out
        far = _Port(canvas.add(_belt(9, 0)), 9, 0, 9, 9)
        d = _Port(0, 0, 0, 0, 0)
        e = _Port(1, -1, -1, -1, -1)
        _reserve_port_access(
            canvas, [_Net(src=e, dst=d, item="x"), _Net(src=d, dst=far, item="x")]
        )

        held = {
            key: sorted(c for c, k in canvas.reserved.items() if k == key)
            for key in ((0, 0, 0), (-1, -1, 0))
        }
        assert len(held[(0, 0, 0)]) == 2, (
            "the drop both receives and sends but was left with "
            f"{len(held[(0, 0, 0)])} cell(s); e took one and was never asked to "
            f"take its other option: {canvas.reserved}"
        )
        assert len(held[(-1, -1, 0)]) == 1, (
            f"e was moved off its cell and given nothing: {canvas.reserved}"
        )

    def test_an_access_cell_with_one_way_out_keeps_that_way_out(self) -> None:
        """A cul-de-sac access cell is worth exactly as much as none at all.

        This is the shape the corpus refusals are made of: an output lane's
        east-end port, whose one access cell is walled north and south by its
        own siblings' claims and west by its lane, so a single cell east is the
        entire route out.  Without holding it, a passing net takes it and A*
        gets a start it can expand and a heap that empties -- which reads in the
        counters exactly like congestion and cannot be negotiated away, because
        nothing owns three of the four walls.
        """
        canvas = _Canvas()
        canvas.add(_belt(0, 0))  # the port itself
        # Wall the access cell (1, 0) north and south, leaving only (2, 0).
        canvas.add(_belt(1, 1))
        canvas.add(_belt(1, -1))
        far = _Port(canvas.add(_belt(9, 0)), 9, 0, 9, 9)
        port = _Port(0, 0, 0, 0, 0)
        _reserve_port_access(canvas, [_Net(src=port, dst=far, item="x")])

        assert canvas.reserved.get((1, 0, 0)) == (0, 0, 0), (
            f"the port did not hold its access cell: {canvas.reserved}"
        )
        assert canvas.reserved.get((2, 0, 0)) == (0, 0, 0), (
            "the access cell's ONE onward move was left for anyone to take, so "
            f"the port's only route out is not held: {canvas.reserved}"
        )

    def test_an_access_cell_with_a_choice_holds_no_extra_ground(self) -> None:
        """Two ways out is not a cul-de-sac, and holding ground costs somebody.

        The exit claim is targeted for a reason: every cell it takes is one the
        router cannot path through, so claiming one for a port that already has
        alternatives spends the same currency the claim exists to protect.
        """
        canvas = _Canvas()
        canvas.add(_belt(0, 0))
        far = _Port(canvas.add(_belt(9, 0)), 9, 0, 9, 9)
        port = _Port(0, 0, 0, 0, 0)
        _reserve_port_access(canvas, [_Net(src=port, dst=far, item="x")])

        # The port has four free neighbours, so whichever it took has three
        # onward moves of its own and nothing further is held for it.
        for_port = [c for c, k in canvas.reserved.items() if k == (0, 0, 0)]
        assert len(for_port) == 1, (
            f"an unobstructed port held {len(for_port)} cells: {for_port}"
        )

    def test_zero_onward_replay_is_deterministic(self) -> None:
        """Keep the universe-all source trap reproducible without a full solve."""

        def replay() -> tuple[
            int,
            tuple[tuple[int, int, int], ...],
            tuple[tuple[int, int, int], ...],
        ]:
            canvas = _Canvas()
            source = _Port(canvas.add(_belt(0, 0)), 0, 0, 0, 0)
            blocker = _Port(canvas.add(_belt(2, 1)), 2, 1, 2, 2)
            first_sink = _Port(canvas.add(_belt(9, 0)), 9, 0, 9, 9)
            second_sink = _Port(canvas.add(_belt(13, 0)), 13, 0, 13, 13)
            for cell in (
                (-1, 0),
                (0, -1),
                (0, 1),
                (1, -1),
                (1, 1),
                (2, 2),
                (3, 1),
            ):
                canvas.add(_belt(*cell))

            missing = _reserve_port_access(
                canvas,
                [
                    _Net(src=source, dst=first_sink, item="hydrogen"),
                    _Net(src=blocker, dst=second_sink, item="hydrogen"),
                ],
            )
            access = tuple(
                sorted(cell for cell, owner in canvas.reserved.items() if owner == (0, 0, 0))
            )
            onward = tuple(
                sorted(
                    candidate
                    for cell in access
                    for dx, dy in freeform._STEPS
                    if (
                        candidate := (cell[0] + dx, cell[1] + dy, cell[2])
                    )
                    != (0, 0, 0)
                    and canvas.free(candidate)
                )
            )
            return missing, access, onward

        first = replay()
        second = replay()

        assert first == second
        assert first == (0, ((1, 0, 0),), ())


class TestTheProliferatorChainIsOneLinearRun:
    """No splitter may carry the proliferator, and no drop may be bypassed.

    A branch drawn off a splitter is a belt run of its own that nothing inside
    the blueprint fills, so the validator -- correctly -- reads every one of them
    as another lane the player must belt proliferator into, buried in the middle
    of the block where no belt can reach.  A chain has no junctions at all.
    """

    def test_neighbouring_drops_are_linked_rather_than_routed(self) -> None:
        """Two drops one tile apart need no path between them, and no cell.

        Two coaters on neighbouring lanes of one strip put their drops in the
        same margin column, one directly above the other, and the lower one then
        has a single free neighbour in the world.  Routing between them would
        need two.
        """
        canvas = _Canvas()
        entry = _Port(canvas.add(_belt(-9, -9)), -9, -9, -9, -9)
        first_drop = canvas.add(replace(_belt(3, 0), z=F(1)), level=1)
        second_drop = canvas.add(replace(_belt(3, 1), z=F(1)), level=1)
        first = CoaterSupplyPort(
            coater=-1,
            host_belt=-1,
            supply_belt=first_drop,
            item="ore",
            yaw=90.0,
            host_x=2,
            host_y=0,
            host_z=0,
            x=3,
            y=0,
            z=1,
        )
        second = CoaterSupplyPort(
            coater=-1,
            host_belt=-1,
            supply_belt=second_drop,
            item="ore",
            yaw=90.0,
            host_x=2,
            host_y=1,
            host_z=0,
            x=3,
            y=1,
            z=1,
        )
        nets = _proliferator_nets(canvas, entry, [first, second], "proliferator-3")
        assert [
            (n.source.x, n.source.y, n.dst.x, n.dst.y) for n in nets
        ] == [(-9, -9, 3, 0)], (
            "the adjacent pair should have been linked, not routed"
        )
        assert (
            canvas.buildings[first.supply_belt].output_obj == second.supply_belt
        ), "the first drop must feed the second directly"

    def test_no_splitter_carries_the_proliferator(self) -> None:
        spec = proliferated_spec()
        p = FreeformLayout(
            band_policy=BandPolicy("portable"),
            workers=DETERMINISTIC_WORKERS,
        ).lay_out(
            spec, time_budget_s=1.0
        )
        prolif = {i for i in spec.external_inputs if i.startswith("proliferator")}
        carriers = {
            i
            for i, b in enumerate(p.buildings)
            if catalog.is_belt(b.item_id) and b.carries_item in prolif
        }
        assert carriers, "fixture must lay a proliferator lane"
        splitters = {
            i for i, b in enumerate(p.buildings) if b.item_id == catalog.SPLITTER_ID
        }
        attached = {
            i
            for i in carriers
            if p.buildings[i].output_obj in splitters
            or p.buildings[i].input_obj in splitters
        }
        assert not attached, (
            f"belts {sorted(attached)} put the proliferator through a splitter; every "
            "branch off it becomes an entry lane nobody can reach"
        )


class TestTheExtentIsDecidedBeforeAnythingRoutes:
    """The boundary must not move while passes are still assuming it is fixed.

    Every entry tile the validator used to report as walled in was on the
    boundary when it was placed and interior by the time the placement finished:
    the input runs computed the edge and ran out to it, the router then laid
    belts two tiles past that, and the proliferator entry went one tile west of
    whatever the edge happened to be at that moment.
    """

    def test_the_canvas_refuses_every_cell_beyond_the_reserved_extent(self) -> None:
        """``_Canvas.limit`` is what actually holds the boundary still.

        Every pass after the pack asks ``free`` before it places -- coater
        drops, the router, the input runs, the power lattice -- so one check in
        one place is what stops the block growing under passes that have already
        committed to where its edge is.
        """
        canvas = _Canvas(limit=(0, 0, 4, 4))
        assert canvas.free((0, 0, 0)) and canvas.free((4, 4, 0))
        for cell in ((-1, 2, 0), (5, 2, 0), (2, -1, 0), (2, 5, 0)):
            assert not canvas.free(cell), f"{cell} is outside the reserved extent"

    def test_routing_never_reaches_the_ring_the_input_runs_land_on(self) -> None:
        """The router gets ``_ROUTE_RING``; the input runs get one ring beyond.

        Sharing would put the two in competition for the cells that decide
        whether a lane can be belted into at all, and the router has alternatives
        where an external lane has none.
        """
        assert _ROUTE_RING < _ENTRY_RING

    @pytest.mark.parametrize("factory", ALL_SPEC_PARAMS)
    def test_every_lane_the_player_must_fill_can_be_reached(
        self, factory: SpecFactory
    ) -> None:
        spec = factory()
        p = FreeformLayout(
            band_policy=BandPolicy(_LEGACY_BAND_BY_SPEC_LABEL[spec.label]),
            workers=DETERMINISTIC_WORKERS,
        ).lay_out(
            spec, time_budget_s=1.0
        )
        report = _full_report(p, spec)
        walled = report.by_check("flow.external_entry_reachable")
        assert not walled, "\n".join(f.message for f in walled)

    def test_the_proliferator_entry_sits_on_the_block_boundary(self) -> None:
        """It is placed on the reserved corner, not beside whatever exists yet.

        Being on the corner is what makes it reachable: nothing else is ever
        placed further out, so it is on the finished bounding box in two
        directions at once.
        """
        spec = proliferated_spec()
        p = FreeformLayout(
            band_policy=BandPolicy("portable"),
            workers=DETERMINISTIC_WORKERS,
        ).lay_out(
            spec, time_budget_s=1.0
        )
        min_x, min_y, _, _ = p.bounds
        entries = [
            b
            for b in p.buildings
            if catalog.is_belt(b.item_id)
            and b.carries_item == "proliferator-3"
            and (b.x, b.y) == (min_x, min_y)
        ]
        assert entries, (
            "no proliferator belt sits on the block's north-west corner "
            f"{(min_x, min_y)}"
        )



class TestEveryShardDrainsEveryProduct:
    """One machine makes all of its recipe's outputs at once.

    A shard carrying lanes for only some of them has machines that fill up on
    the rest and stop -- while looking perfectly healthy, because every lane it
    does have is connected to something.
    """

    def test_a_two_product_recipe_keeps_both_lanes_on_every_shard(self) -> None:
        """Chunking the flat list of destinations is what lost the second product.

        ``plasma-refining`` yields refined-oil and hydrogen; sequential chunking
        put its one hydrogen consumer and two of its three oil consumers in the
        first shard and the last oil consumer alone in the second, so that
        shard's machines had nowhere to put their hydrogen.
        """
        sinks = [
            ("hydrogen", "casimir", CargoDomain.UNSPRAYED),
            ("refined-oil", "organic", CargoDomain.UNSPRAYED),
            ("refined-oil", "plastic", CargoDomain.UNSPRAYED),
            ("refined-oil", "sulfuric", CargoDomain.UNSPRAYED),
        ]
        shards = _shard_sinks(sinks, cap=3)
        assert len(shards) >= 2, "the fixture must need more than one shard"
        for shard in shards:
            assert {item for item, _dest, _domain in shard} == {
                "hydrogen",
                "refined-oil",
            }, shard
            assert len(shard) <= 3, shard

    def test_a_shard_that_cannot_drain_every_product_is_refused(self) -> None:
        """Better to say so than to emit machines that quietly jam."""
        sinks = [
            (item, "x", CargoDomain.UNSPRAYED)
            for item in ("a", "b", "c", "d")
        ]
        with pytest.raises(ValueError, match="never be drained"):
            _shard_sinks(sinks, cap=3)

    def test_a_sharded_two_product_producer_has_both_products_drained(self) -> None:
        spec = BuildSpec(
            groups=(
                group(
                    "plasma-refining",
                    "chemical-plant",
                    8,
                    {"crude-oil": F(2)},
                    {"refined-oil": F(1), "hydrogen": F(1)},
                ),
                group(
                    "plastic", "assembling-machine-2", 1,
                    {"refined-oil": F(1)}, {"plastic": F(1)},
                ),
                group(
                    "organic-crystal", "assembling-machine-2", 1,
                    {"refined-oil": F(1)}, {"organic-crystal": F(1)},
                ),
                group(
                    "sulfuric-acid", "chemical-plant", 1,
                    {"refined-oil": F(1)}, {"sulfuric-acid": F(1)},
                ),
                group(
                    "graphene", "chemical-plant", 1,
                    {"hydrogen": F(1)}, {"graphene": F(1)},
                ),
            ),
            external_inputs={"crude-oil": F(16)},
            outputs={
                "plastic": F(1),
                "organic-crystal": F(1),
                "sulfuric-acid": F(1),
                "graphene": F(1),
                "refined-oil": F(5),
                "hydrogen": F(7),
            },
            belt_item_id="conveyor-belt-2",
            belt_items_per_second=F(12),
            label="two-product-producer",
        )
        strips = plan_strips(spec, strip_len=6)
        refiners = [s for s in strips if s.group_key.startswith("plasma-refining")]
        assert len(refiners) >= 2, "fixture must shard the refiner"
        for s in refiners:
            assert {item for item, _dest, _domain in s.out_lanes} == {
                "refined-oil",
                "hydrogen",
            }, (
                f"shard {s.out_lanes} cannot drain both products"
            )
        p = FreeformLayout(
            band_policy=BandPolicy("portable"),
            workers=DETERMINISTIC_WORKERS,
        ).lay_out(
            spec, time_budget_s=1.0
        )
        backed_up = _full_report(p, spec).by_check("machine.output_removed")
        assert not backed_up, "\n".join(f.message for f in backed_up)


def one_machine_fan_out_spec(consumers: int = 4) -> BuildSpec:
    """A producer with FEWER MACHINES than the sorter reach needs shards.

    ``mass-energy-storage`` in the universe-matrix build is exactly this: one
    machine and four destinations.  Sharding wants two strips and there is only
    one machine to put in them, so the split has to happen on the other axis --
    several destinations sharing one output lane.
    """
    sinks = _real_consumers_of("copper-ingot", consumers)
    if len(sinks) < consumers:
        pytest.skip(f"dataset has only {len(sinks)} mapped copper-ingot consumers")
    from flab2bp.lab.data import load_vendored

    groups = [
        group(
            "copper-ingot",
            "arc-smelter",
            1,
            {"copper-ore": F(consumers)},
            {"copper-ingot": F(consumers)},
        )
    ]
    outputs: dict[str, F] = {}
    for rid in sinks:
        produced = next(iter(load_vendored().recipe(rid).outputs))
        groups.append(
            group(rid, "assembling-machine-2", 1, {"copper-ingot": F(1)}, {produced: F(1)})
        )
        outputs[produced] = F(1)
    return BuildSpec(
        groups=tuple(groups),
        external_inputs={"copper-ore": F(consumers)},
        outputs=outputs,
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label=f"one-machine-fan-out-{consumers}",
    )


class TestOneLaneCanServeSeveralDestinations:
    """The other axis, for a producer that has no second machine to shard into.

    Sharding splits destinations across STRIPS and costs one machine per shard.
    ``mass-energy-storage`` has one machine and four destinations, so the reach
    limit and the machine count are in direct contradiction and no strip plan
    exists -- the whole universe-matrix build refused inside ``plan_strips``,
    deterministically, in 0.0s.

    Folding destinations onto one lane resolves it with machinery that already
    existed: a lane serving several consumers is what a sharded CONSUMER group
    already produces, and ``_tap_source`` builds the junction at the lane end.
    """

    def test_sharding_stops_at_the_machine_count(self) -> None:
        sinks = [
            ("a", f"d{i}", CargoDomain.UNSPRAYED)
            for i in range(4)
        ]
        assert len(_shard_sinks(sinks, cap=3)) == 2, "the fixture must want two shards"
        assert len(_shard_sinks(sinks, cap=3, max_shards=1)) == 1

    def test_merging_keeps_every_destination_inside_the_reach(self) -> None:
        shard = [
            ("a", f"d{i}", CargoDomain.UNSPRAYED)
            for i in range(4)
        ]
        demand = {
            (item, dest, cargo_domain): F(1)
            for item, dest, cargo_domain in shard
        }
        lanes = _merge_lanes(shard, 3, demand, F(12))
        assert len(lanes) == 3
        assert {
            d
            for _item, dest, _cargo_domain in lanes
            for d in _dests(dest)
        } == {
            "d0",
            "d1",
            "d2",
            "d3",
        }

    def test_a_shard_that_already_fits_is_left_exactly_as_it_was(self) -> None:
        """Merging must be additive: every plan that worked plans identically."""
        shard = [
            ("a", "d1", CargoDomain.UNSPRAYED),
            ("b", "d2", CargoDomain.UNSPRAYED),
        ]
        assert _merge_lanes(shard, 3, {}, F(12)) == shard

    def test_every_product_keeps_a_lane_of_its_own(self) -> None:
        """A shard that cannot drain a product has machines that back up."""
        shard = [
            ("a", "d1", CargoDomain.UNSPRAYED),
            ("a", "d2", CargoDomain.UNSPRAYED),
            ("a", "d3", CargoDomain.UNSPRAYED),
            ("b", "d4", CargoDomain.UNSPRAYED),
        ]
        lanes = _merge_lanes(shard, 2, {}, F(12))
        assert {item for item, _dest, _domain in lanes} == {"a", "b"}

    def test_a_merged_lane_over_belt_capacity_is_refused(self) -> None:
        """Two consumers whose combined draw jams the lane is not a layout."""
        shard = [
            ("a", f"d{i}", CargoDomain.UNSPRAYED)
            for i in range(4)
        ]
        demand = {
            (item, dest, cargo_domain): F(7)
            for item, dest, cargo_domain in shard
        }
        with pytest.raises(ValueError, match="over the"):
            _merge_lanes(shard, 3, demand, F(12))

    def test_a_one_machine_producer_plans_and_serves_every_consumer(self) -> None:
        spec = one_machine_fan_out_spec(4)
        strips = plan_strips(spec, strip_len=6)
        producers = [s for s in strips if s.group_key.startswith("copper-ingot")]
        assert len(producers) == 1, "one machine cannot be split across shards"
        s = producers[0]
        assert len(s.out_lanes) + len(s.in_below) <= catalog.SORTER_MAX_REACH
        served = {
            d
            for _item, dest, _cargo_domain in s.out_lanes
            for d in _dests(dest)
        }
        wanted = {
            f"{g.recipe_id}#{i}"
            for i, g in enumerate(spec.groups)
            if "copper-ingot" in g.inputs_per_machine
        }
        assert served == wanted, f"missing destinations: {wanted - served}"

    def test_the_merged_plan_lays_out_and_validates(self) -> None:
        spec = one_machine_fan_out_spec(4)
        p = FreeformLayout(
            band_policy=BandPolicy("portable"),
            workers=DETERMINISTIC_WORKERS,
        ).lay_out(
            spec, time_budget_s=4.0
        )
        report = _full_report(p, spec)
        assert report.ok, "\n".join(f.message for f in report.errors[:5])
        assert p.stats["route_failures"] == 0.0


class TestPowerClaimsItsGroundBeforeRouting:
    """Coverage cannot be whatever the router leaves behind.

    Towers went in last, and on a dense block "last" means "nothing": measured
    on ``casimir-crystal``, a matrix lab with 349 tiles inside tower range had
    four of them free, and thirteen buildings shipped unpowered -- a blueprint
    that pastes and then sits there.
    """

    def _machine(self, x: int, y: int) -> PlacedBuilding:
        """A 3x3 powered building -- an assembler, as far as coverage cares."""
        return PlacedBuilding(
            item_id=2303, model_index=65, x=x, y=y, width=3, height=3
        )

    @staticmethod
    def _pin_projection_extent(
        canvas: _Canvas,
        core: tuple[int, int, int, int],
    ) -> None:
        """Make the synthetic planner core a real, cleanup-stable extent."""
        for x, y in ((core[0], core[1]), (core[2], core[3])):
            cell = (x, y, 0)
            index = canvas.add(_belt(x, y)) if canvas.free(cell) else canvas.blocked[cell]
            canvas.buildings[index] = replace(
                canvas.buildings[index],
                input_obj=index,
                output_obj=index,
            )

    def test_route_ring_power_is_planned_before_a_splitter_is_emitted(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A legal route-ring junction must not be the router's dark surprise."""
        demands: list[tuple[int, int, int, int]] = []
        plan = freeform._power_plan

        def observe_demand(
            canvas: _Canvas,
            demand: tuple[int, int, int, int],
            *,
            policy: BandPolicy,
        ) -> list[tuple[int, int]]:
            demands.append(demand)
            return plan(canvas, demand, policy=policy)

        monkeypatch.setattr(freeform, "_power_plan", observe_demand)
        spec = two_stage_spec()
        strips = plan_strips(spec)
        prepared = _prepare_routing_problem(
            spec,
            strips,
            _greedy_pack(strips, _height_seed(strips)),
            power=True,
            policy=BandPolicy("160"),
        )

        route_ring = (prepared.core[0], prepared.route_bounds[3])
        control = (prepared.core[0], prepared.core[3])
        workspace = prepared.new_workspace()
        assert workspace.canvas.junction_is_clear(*route_ring, 0)
        assert workspace.canvas.junction_is_clear(*control, 0)

        workspace.canvas.add(junction.make_splitter(*route_ring))
        workspace.canvas.add(junction.make_splitter(*control))
        workspace.canvas.keep_out.clear()
        freeform._place_power(workspace.canvas, prepared.power_sites)

        tower = catalog.building(catalog.TESLA_TOWER_ID)
        reach2 = math.floor((2 * tower.cover_radius) ** 2)
        assert any(
            (2 * (control[0] - x)) ** 2 + (2 * (control[1] - y)) ** 2 <= reach2
            for x, y in prepared.power_sites
        ), "the in-radius core control must stay covered"
        report = validate.validate(
            Placement(buildings=tuple(workspace.canvas.buildings)),
            only=["power.coverage"],
        )
        assert report.ok, "\n".join(f.message for f in report.errors)

        assert demands == [prepared.route_bounds]
        assert prepared.limit == (
            prepared.route_bounds[0] - 1,
            prepared.route_bounds[1] - 1,
            prepared.route_bounds[2] + 1,
            prepared.route_bounds[3] + 1,
        ), "the outer entry ring is standing capacity, not powered demand"

    def test_planned_sites_are_closed_to_everything_else(self) -> None:
        canvas = _Canvas(limit=(0, 0, 40, 40))
        canvas.add(self._machine(10, 10), solid=True)
        self._pin_projection_extent(canvas, (0, 0, 40, 40))
        sites = _power_plan(canvas, (0, 0, 40, 40), policy=BandPolicy("160"))
        assert sites, "a powered building must be given at least one tower"
        for x, y in sites:
            assert not canvas.free((x, y, 0)), f"{(x, y)} was planned but reads free"
            assert 0 <= x <= 40 and 0 <= y <= 40, (
                f"{(x, y)} was placed outside the core, onto ground the input "
                "runs need"
            )

    def test_every_powered_tile_is_covered_by_the_plan(self) -> None:
        """The guarantee, checked as a guarantee rather than as an outcome.

        This is the whole reason the repair pass is gone: the plan either covers
        every tile or refuses the pack, so there is never a dark tile left for a
        later pass to go looking for ground for.
        """
        canvas = _Canvas(limit=(0, 0, 60, 60))
        for x in range(2, 50, 6):
            for y in range(2, 50, 6):
                canvas.add(self._machine(x, y), solid=True)
        sites = _power_plan(canvas, (0, 0, 60, 60), policy=BandPolicy("portable"))
        tower = catalog.building(catalog.TESLA_TOWER_ID)
        reach2 = math.floor((2 * tower.cover_radius) ** 2)
        centres = [(2 * x + 1, 2 * y + 1) for x, y in sites]
        for b in canvas.buildings:
            if b.item_id == catalog.TESLA_TOWER_ID:
                continue
            for tx, ty, _z in b.tiles():
                px, py = 2 * tx + 1, 2 * ty + 1
                assert any(
                    (px - cx) ** 2 + (py - cy) ** 2 <= reach2 for cx, cy in centres
                ), f"tile {(tx, ty)} is outside every tower's radius"

    def test_a_pack_that_cannot_be_powered_is_refused_not_repaired(self) -> None:
        """Feasible means powerable, so an unpowerable pack is not a pack.

        Ground is solid for a full tower radius around the machine, so no cell
        can cover it.  The old code placed what it could, left the tile dark and
        let `power.coverage` catch it after a whole routing pass had been paid
        for; there is nothing to repair here and it says so instead.
        """
        canvas = _Canvas(limit=(0, 0, 40, 40))
        for x in range(0, 41):
            for y in range(0, 41):
                canvas.add(_belt(x, y))
        canvas.add(self._machine(20, 20), solid=True)
        self._pin_projection_extent(canvas, (0, 0, 40, 40))
        with pytest.raises(_Unpowerable):
            _power_plan(canvas, (0, 0, 40, 40), policy=BandPolicy("160"))

    def test_power_candidates_exact_check_only_broad_phase_hits(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        core = (0, 0, 60, 9)
        canvas = _Canvas(limit=core)
        self._pin_projection_extent(canvas, core)
        cache = freeform._StagedStaticCache()
        frame_queries = 0
        original_frames = freeform._cached_junction_projection_frames

        def counted_frames(*args: object, **kwargs: object) -> object:
            nonlocal frame_queries
            frame_queries += 1
            return original_frames(*args, **kwargs)  # type: ignore[no-any-return]

        monkeypatch.setattr(
            freeform,
            "_cached_junction_projection_frames",
            counted_frames,
        )

        sites = _power_plan(
            canvas,
            core,
            policy=BandPolicy("portable"),
            staged_static_cache=cache,
        )

        assert len(sites) >= 3
        assert cache.broad_phase_queries >= len(sites)
        assert cache.exact_static_queries == cache.broad_phase_hits
        assert cache.broad_phase_hits < cache.broad_phase_queries
        assert frame_queries <= cache.broad_phase_hits

    def test_power_candidates_do_not_recertify_boundary_cleanup(self) -> None:
        core = (0, 0, 60, 9)
        canvas = _Canvas(limit=core)
        self._pin_projection_extent(canvas, core)
        initial_buildings = len(canvas.buildings)
        cache = freeform._StagedStaticCache()

        sites = _power_plan(
            canvas,
            core,
            policy=BandPolicy("portable"),
            staged_static_cache=cache,
        )

        assert len(sites) >= 3
        assert cache.cleanup_operations.node_visits == 2 * initial_buildings, (
            "the initial graph construction and exact survivor proof each visit "
            "the packed buildings once; static tower proposals must add no visits"
        )

    def test_power_peer_broad_phase_retains_periodic_seam_failure(self) -> None:
        tower = catalog.building(catalog.TESLA_TOWER_ID)
        band = next(candidate for candidate in planet.bands() if candidate.area_segments == 8)
        projection = planet.Projection(
            band,
            band.grid_lo,
            colliders.PLANET_SEGMENT,
            colliders.PLANET_RADIUS,
        )

        def node(
            index: int,
            x: int,
        ) -> tuple[int, PlacedBuilding, rules.PowerNode]:
            return (
                index,
                PlacedBuilding(
                    item_id=catalog.TESLA_TOWER_ID,
                    model_index=tower.model_index,
                    x=x,
                    y=0,
                    width=tower.width,
                    height=tower.height,
                ),
                tower.power_node,
            )

        candidate = node(0, 0)
        contexts = (
            (
                band.columns,
                projection.rotated,
                freeform._minimum_projection_grid_scale((band,)),
            ),
        )
        seam_peer = node(1, band.columns - 1)
        seam_failure = finalize.projected_power_failure(
            (candidate, seam_peer),
            projection,
        )
        assert seam_failure is not None
        assert freeform._projected_power_peer_possible(
            candidate,
            seam_peer,
            contexts,
        )

        for index, x in enumerate((1, 2, 3, 20, 37, 38, 39), 2):
            peer = node(index, x)
            exact_failure = finalize.projected_power_failure(
                (candidate, peer),
                projection,
            )
            gated_failure = (
                exact_failure
                if freeform._projected_power_peer_possible(
                    candidate,
                    peer,
                    contexts,
                )
                else None
            )
            assert gated_failure == exact_failure

    def test_covering_by_need_beats_covering_by_grid(self) -> None:
        """Fewer towers is the density win, and it is the point.

        A tower reaches 10.5 in every direction, so it covers a 346-tile disc;
        a point every nine tiles ignores that and lays down one per 81.  The
        grid this replaced would put 5x5 = 25 points over a 41x41 core, and the
        area argument says 41*41 / 346 = 5 is the most that can ever be needed.

        Asserted against the GRID's count rather than an absolute, so the test
        keeps meaning what it says if the radius or the core ever change.
        """
        canvas = _Canvas(limit=(0, 0, 40, 40))
        for x in range(15, 24, 3):
            for y in range(15, 24, 3):
                canvas.add(self._machine(x, y), solid=True)
        self._pin_projection_extent(canvas, (0, 0, 40, 40))
        sites = _power_plan(canvas, (0, 0, 40, 40), policy=BandPolicy("160"))
        lattice = len(range(4, 41, 9)) ** 2
        assert 0 < len(sites) < lattice, (
            f"covering by need took {len(sites)}, the 9-spaced grid took {lattice}"
        )

    def test_no_two_planned_towers_are_close_enough_for_the_game_to_refuse(self) -> None:
        """``EBuildCondition.PowerTooClose``, which the greedy used to ignore.

        THE REGRESSION.  A blueprint this planner produced was pasted into a
        real game and two of its six towers were reddened at 1.777 world units
        -- ``tests/fixtures/ours/power-too-close-freeform.txt``.  Nothing could
        see it: a Tesla Tower has no build collider, so it is invisible to
        ``geom.collide``, and the greedy marked only the cell it stood on.

        The geometry is a WIDE, SHALLOW core -- 61 by 10 -- because that is
        the shape that produces it: the greedy walks left to right, and when
        what is still dark is a thin tail off the end of the last disc, the cell
        that covers most of it is the one right beside the tower it just
        placed.  The two linked belts pin that projected extent without filling
        every legal tower site with solid geometry.  Under the unfixed greedy
        this plans towers at (31, 4) and (32, 4), 1.777 world units apart.
        """
        core = (0, 0, 60, 9)
        canvas = _Canvas(limit=core)
        self._pin_projection_extent(canvas, core)
        sites = _power_plan(canvas, core, policy=BandPolicy("portable"))
        assert len(sites) >= 3, "the sample must contain several towers to be a test"
        keepout = {
            (dx, dy)
            for dx, dy, dz in rules.power_node_keepout_offsets(
                catalog.building(catalog.TESLA_TOWER_ID).power_node,
                catalog.building(catalog.TESLA_TOWER_ID).power_node,
            )
            if dz == 0
        }
        for (ax, ay), (bx, by) in itertools.combinations(sites, 2):
            assert (bx - ax, by - ay) not in keepout, (
                f"towers planned at {(ax, ay)} and {(bx, by)}; the game refuses "
                "that paste with EBuildCondition.PowerTooClose"
            )

    @staticmethod
    def _reference_projection_envelope(
        occupied: tuple[int, int, int, int],
        limit: tuple[int, int, int, int],
        policy: BandPolicy,
    ) -> tuple[planet.Projection, ...]:
        """Literal four-edge enumeration defining first-seen evidence order."""
        occupied_min_x, occupied_min_y, occupied_max_x, occupied_max_y = occupied
        limit_min_x, limit_min_y, limit_max_x, limit_max_y = limit
        by_segments = {band.area_segments: band for band in planet.bands()}
        projections: dict[planet.Projection, None] = {}
        for min_x in range(limit_min_x, occupied_min_x + 1):
            for min_y in range(limit_min_y, occupied_min_y + 1):
                for max_x in range(occupied_max_x, limit_max_x + 1):
                    for max_y in range(occupied_max_y, limit_max_y + 1):
                        candidates = finalize._frame_candidates_for_extent(
                            max_x - min_x + 1,
                            max_y - min_y + 1,
                            policy,
                        )
                        for candidate in candidates:
                            rotated = candidate.frame.rotated
                            row_origin = (
                                min_x if rotated else min_y
                            ) - candidate.south_padding
                            for segments in candidate.frame.certified_bands:
                                band = by_segments[segments]
                                for anchor in band.anchors(candidate.frame.height):
                                    projection = planet.Projection(
                                        band=band,
                                        anchor_row=anchor - row_origin,
                                        segment=colliders.PLANET_SEGMENT,
                                        radius=colliders.PLANET_RADIUS,
                                        quadrant=int(rotated),
                                    )
                                    projections.setdefault(projection, None)
        return tuple(projections)

    @pytest.mark.parametrize(
        ("occupied", "limit", "selection"),
        (
            ((3, 3, 161, 7), (0, 0, 164, 10), "portable"),
            ((0, 0, 4, 4), (0, 0, 7, 7), "32"),
            ((0, 0, 199, 4), (0, 0, 199, 4), "portable"),
            ((-2, 4, 5, 8), (-5, 1, 8, 11), "160"),
        ),
    )
    def test_projection_envelope_retains_reference_first_seen_order(
        self,
        occupied: tuple[int, int, int, int],
        limit: tuple[int, int, int, int],
        selection: BandSelection,
    ) -> None:
        policy = BandPolicy(selection)
        assert freeform._projection_envelope(
            occupied,
            limit,
            policy,
        ) == self._reference_projection_envelope(occupied, limit, policy)

    @staticmethod
    def _canvas_with_one_tower_site(
        candidate: tuple[int, int],
    ) -> _Canvas:
        limit = (0, 0, 199, 4)
        canvas = _Canvas(limit=limit)
        tower = catalog.building(catalog.TESLA_TOWER_ID)
        canvas.add(
            PlacedBuilding(
                item_id=catalog.TESLA_TOWER_ID,
                model_index=tower.model_index,
                x=0,
                y=0,
                width=tower.width,
                height=tower.height,
            ),
            solid=True,
        )
        for x in range(limit[0], limit[2] + 1):
            for y in range(limit[1], limit[3] + 1):
                if (x, y) not in {(0, 0), candidate}:
                    canvas.add(_belt(x, y))
        for index, building in enumerate(canvas.buildings):
            if catalog.is_belt(building.item_id):
                canvas.buildings[index] = replace(
                    building,
                    input_obj=index,
                    output_obj=index,
                )
        return canvas

    def test_power_plan_rejects_flat_legal_pair_in_required_projection(self) -> None:
        bounds = (0, 0, 199, 4)
        envelope = freeform._projection_envelope(
            bounds,
            bounds,
            BandPolicy("portable"),
        )
        anchors = {
            segments: sorted(
                {
                    projection.anchor_row
                    for projection in envelope
                    if projection.band.area_segments == segments
                }
            )
            for segments in (40, 60, 80)
        }
        assert {projection.quadrant for projection in envelope} == {0}
        assert anchors == {
            40: [*range(-220, -214), *range(211, 217)],
            60: [*range(-210, -199), *range(196, 207)],
            80: [*range(-195, -184), *range(181, 192)],
        }

        illegal_site = (2, 2)

        projected = self._canvas_with_one_tower_site(illegal_site)
        with pytest.raises(_Unpowerable) as caught:
            _power_plan(
                projected,
                (*illegal_site, *illegal_site),
                policy=BandPolicy("portable"),
            )

        assert projected.keep_out == set()
        assert caught.value.failure is not None
        assert caught.value.failure.check == "game.power_too_close"
        assert caught.value.failure.band in (40, 60, 80)
        assert "below the 3.5-unit PowerTooClose gate" in caught.value.failure.detail

        legal_site = (3, 2)
        control = self._canvas_with_one_tower_site(legal_site)
        assert _power_plan(
            control,
            (*legal_site, *legal_site),
            policy=BandPolicy("portable"),
        ) == [legal_site]

    def test_power_projection_envelope_covers_empty_limit_edges(self) -> None:
        occupied = (3, 3, 161, 7)
        limit = (0, 0, 164, 10)
        policy = BandPolicy("portable")
        representative = Placement(
            buildings=(
                _belt(occupied[0], occupied[1]),
                _belt(occupied[2], occupied[3]),
            )
        )
        candidates = finalize.frame_candidates(representative, policy)
        assert {candidate.frame.primary_band for candidate in candidates} == {32}

        by_segments = {band.area_segments: band for band in planet.bands()}
        expected: set[planet.Projection] = set()
        for candidate in candidates:
            rotated = candidate.frame.rotated
            row_origin = (
                occupied[0] if rotated else occupied[1]
            ) - candidate.south_padding
            for segments in candidate.frame.certified_bands:
                band = by_segments[segments]
                expected.update(
                    planet.Projection(
                        band=band,
                        anchor_row=anchor - row_origin,
                        segment=colliders.PLANET_SEGMENT,
                        radius=colliders.PLANET_RADIUS,
                        quadrant=int(rotated),
                    )
                    for anchor in band.anchors(candidate.frame.height)
                )

        envelope = freeform._projection_envelope(
            occupied,
            limit,
            policy,
        )
        assert len(envelope) == len(set(envelope)) == 98
        assert expected <= set(envelope)
        tower = catalog.building(catalog.TESLA_TOWER_ID)
        assert rules.power_node_condition(
            tower.power_node,
            tower.power_node,
            10 * colliders.GRID_ARC**2,
        ) is None
        pair = (
            (
                0,
                PlacedBuilding(
                    item_id=catalog.TESLA_TOWER_ID,
                    model_index=tower.model_index,
                    x=10,
                    y=3,
                ),
                tower.power_node,
            ),
            (
                1,
                PlacedBuilding(
                    item_id=catalog.TESLA_TOWER_ID,
                    model_index=tower.model_index,
                    x=13,
                    y=4,
                ),
                tower.power_node,
            ),
        )
        limit_only = freeform._projection_envelope(limit, limit, policy)
        assert all(
            finalize.projected_power_failure(pair, projection) is None
            for projection in limit_only
        )
        failure = next(
            (
                failure
                for projection in envelope
                if (
                    failure := finalize.projected_power_failure(
                        pair,
                        projection,
                    )
                )
                is not None
            ),
            None,
        )
        assert failure is not None
        assert (
            failure.band,
            failure.check,
            failure.buildings,
            failure.detail,
        ) == (
            60,
            "game.power_too_close",
            (0, 1),
            "3.4776 world units apart, below the 3.5-unit PowerTooClose gate "
            "(PowerTooClose)",
        )

    def test_power_projection_envelope_covers_compacted_open_boundary_belts(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class _Accepted:
            errors: tuple[object, ...] = ()

        monkeypatch.setattr(
            finalize,
            "_certify",
            lambda *_args, **_kwargs: _Accepted(),
        )
        policy = BandPolicy("portable")
        limit = (0, 0, 164, 16)
        canvas = _Canvas(limit=limit)
        canvas.add(self._machine(6, 6), solid=True)
        canvas.add(self._machine(158, 8), solid=True)
        canvas.add(_belt(3, 3))
        canvas.add(_belt(161, 13))
        planning_envelope = set(
            freeform._power_projection_envelope(
                canvas,
                policy,
            )
        )
        assert len(planning_envelope) == 204

        compacted = finalize.compact_open_boundary_belts(
            Placement(buildings=tuple(canvas.buildings)),
            two_stage_spec(),
            expect_power=False,
        )
        assert compacted.bounds == (6, 6, 160, 10)
        candidates = finalize.frame_candidates(compacted, policy)
        assert {candidate.frame.primary_band for candidate in candidates} == {32}

        by_segments = {band.area_segments: band for band in planet.bands()}
        expected: set[planet.Projection] = set()
        min_x, min_y, _max_x, _max_y = compacted.bounds
        for candidate in candidates:
            rotated = candidate.frame.rotated
            row_origin = (
                min_x if rotated else min_y
            ) - candidate.south_padding
            for segments in candidate.frame.certified_bands:
                band = by_segments[segments]
                expected.update(
                    planet.Projection(
                        band=band,
                        anchor_row=anchor - row_origin,
                        segment=colliders.PLANET_SEGMENT,
                        radius=colliders.PLANET_RADIUS,
                        quadrant=int(rotated),
                    )
                    for anchor in band.anchors(candidate.frame.height)
                )

        assert expected <= planning_envelope

    def test_build_passes_projection_policy_to_power_plan_before_routing(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        policy = BandPolicy("portable")
        failure = finalize.ProjectionFailure(
            "game.power_too_close",
            (0, 1),
            "authoritative projected pair detail",
            40,
        )
        seen: list[BandPolicy] = []

        def refuse(
            _canvas: _Canvas,
            _core: tuple[int, int, int, int],
            *,
            policy: BandPolicy,
        ) -> list[tuple[int, int]]:
            seen.append(policy)
            raise _Unpowerable("projected power refusal", failure=failure)

        monkeypatch.setattr(freeform, "_power_plan", refuse)
        monkeypatch.setattr(
            freeform,
            "_route_all",
            lambda *_args, **_kwargs: pytest.fail("routing started after a power refusal"),
        )
        spec = single_recipe_spec()
        strips = plan_strips(spec)
        pack = _greedy_pack(strips, _height_seed(strips))

        with pytest.raises(_Unpowerable) as caught:
            _build(
                spec,
                strips,
                pack,
                power=True,
                route=True,
                policy=policy,
            )

        assert seen == [policy]
        assert caught.value.failure is failure
        assert "band 40 game.power_too_close" in str(caught.value)

    def test_no_planned_tower_stands_too_close_to_a_power_NODE_MACHINE(self) -> None:
        """A power node is not only a tower, and the greedy did not know that.

        The pack places mode-driven MACHINES that join the network -- a Ray
        Receiver, an Energy Exchanger -- and ``free`` knew only that their own
        tiles were taken.  ``EBuildCondition.PowerTooClose`` does not care which
        of the two a building is.

        **The two we actually emit cannot show it, and that is worth writing
        down rather than hiding behind a passing test.**  A Ray Receiver is 7x7
        and an Energy Exchanger 9x9, while the ordinary spacing halo reaches
        only 2 tiles, so for both of them the halo lies entirely inside their own
        footprint and the footprint already excluded it.  The term is a no-op
        today.  It is ported because it is the rule, and a 3x3 Solar Panel --
        also a power node, halo reach 2 against a footprint of 1 either side --
        is the smallest building that separates the two, so the mechanism is
        exercised on that.
        """
        panel = catalog.building(2205)
        assert panel.is_power_node and (panel.width, panel.height) == (3, 3)
        canvas = _Canvas(limit=(0, 0, 20, 20))
        canvas.add(
            PlacedBuilding(
                item_id=2205,
                model_index=panel.model_index,
                x=9,
                y=9,
                width=panel.width,
                height=panel.height,
            ),
            solid=True,
        )
        self._pin_projection_extent(canvas, (0, 0, 20, 20))
        sites = _power_plan(canvas, (0, 0, 20, 20), policy=BandPolicy("100"))
        assert sites
        cx, cy = 9 + panel.width // 2, 9 + panel.height // 2
        keepout = {
            (dx, dy)
            for dx, dy, dz in rules.power_node_keepout_offsets(
                panel.power_node,
                catalog.building(catalog.TESLA_TOWER_ID).power_node,
            )
            if dz == 0
        }
        assert any(abs(dx) > 1 or abs(dy) > 1 for dx, dy in keepout), (
            "a 3x3 building whose halo is inside its own footprint would make "
            "this test vacuous"
        )
        for x, y in sites:
            assert (x - cx, y - cy) not in keepout, (
                f"tower planned at {(x, y)} against a Solar Panel centred at "
                f"{(cx, cy)}; the game refuses that paste"
            )

    def test_a_tie_is_broken_towards_open_ground_not_into_a_channel(self) -> None:
        """The tie-break points away from the corridors, and that is the point.

        A tower cell is held in ``keep_out`` for the whole of routing, so where
        it stands is the router's problem.  The scarce thing is the ONE-ROW
        CHANNEL between two strips -- a machine band is solid at every level, so
        that row is the only way past -- and a cell in one has free neighbours
        on a single axis.  A cell in the middle of a wide field has four and
        cutting it out disconnects nothing.

        Built so the choice is PURELY the tie-break: the core is small enough
        that one tower covers all of it from many cells, so every one of those
        scores identically and only the second key can separate them.  Rows 4
        and 6 are walled off, which makes row 5 a one-row channel whose cells
        cover exactly as much as the open ground at row 1 does.

        This is the regression that cost three corpus cells: the tie-break used
        to prefer the ENCLOSED cell and aimed every tower at a channel.
        """
        canvas = _Canvas(limit=(0, 0, 10, 10))
        for x in range(11):
            for y in (4, 6):
                canvas.add(_belt(x, y))
        sites = _power_plan(canvas, (0, 0, 10, 10), policy=BandPolicy("portable"))
        assert len(sites) == 1, f"one tower covers this core, not {len(sites)}"
        x, y = sites[0]
        neighbours = sum(
            canvas.free((x + dx, y + dy, 0))
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
        )
        assert neighbours == 4, (
            f"the plan stood at {(x, y)}, which has {neighbours} free "
            "neighbours, when a cell covering exactly as much was free in the "
            "open; a tower in a one-row channel plugs the only way through it"
        )

    def test_towers_still_cover_when_the_plan_claims_its_cells(self) -> None:
        p = FreeformLayout(
            band_policy=BandPolicy("portable"),
            workers=DETERMINISTIC_WORKERS,
        ).lay_out(
            proliferated_spec(), time_budget_s=1.0
        )
        report = validate.validate(p, only=["power.coverage", "power.connectivity"])
        assert report.ok, "\n".join(f.message for f in report.errors[:5])



def _lane(machines: int) -> _Port:
    """A port standing in for a lane with ``machines`` machines behind it."""
    return _Port(0, 0, 0, 0, 0, (), machines)


class TestAnIslandThatCannotFeedItself:
    """``flow.conservation``'s placement clause is a CUT argument.

    Within every island an item can physically travel across, production must
    cover consumption -- and a one-to-one pairing cuts the item's flow graph
    into as many islands as it makes pairs.  Measured on ``quantum-chip``:
    ``titanium-glass`` shards into a four-machine and a three-machine strip,
    ``plane-filter`` into sixteen machines across three lanes, and the cyclic
    pairing hands the four-machine shard eleven of them -- 11/4 of a machine's
    output where seven machines covering sixteen reach only 16/7.
    """

    #: The quantum-chip shape: two producer shards, three consumer lanes.
    SRCS = (4, 3)
    SINKS = (6, 6, 4)
    #: What the cyclic pairing makes of it.
    CYCLIC = ((0, 0), (1, 1), (0, 2))

    def _ports(self) -> tuple[list[_Port], list[_Port]]:
        return [_lane(n) for n in self.SRCS], [_lane(n) for n in self.SINKS]

    def test_islands_that_each_feed_themselves_are_left_alone(self) -> None:
        """The join costs belts, so it is bought only where it is needed.

        Connecting every sharded edge in the build was measured and thrown
        away: it removed the one ``flow.conservation`` cell and cost four
        others, 54 of 72 clean against 58.
        """
        srcs, sinks = self._ports()
        assert _connect_short_cuts(srcs, sinks, self.CYCLIC, F(4), F(1)) == []

    def test_a_short_island_is_joined_to_the_rest(self) -> None:
        srcs, sinks = self._ports()
        # 7/3 per machine against 1: the block balances (7 * 7/3 > 16), the
        # four-machine island does not (4 * 7/3 < 10).
        extra = _connect_short_cuts(srcs, sinks, self.CYCLIC, F(7, 3), F(1))
        assert extra, "the starving island was left to starve"
        merged = list(self.CYCLIC) + list(extra)
        assert _one_island(merged, len(srcs), len(sinks)), (
            f"{merged} still leaves the flow graph cut"
        )

    def test_the_join_runs_surplus_to_deficit(self) -> None:
        """The belt points from the island with spare output to the one short.

        Direction is invisible to the check that motivated this function.
        ``validate._islands`` unions ``(input_obj, output_obj)`` without regard
        to which way the belt points, so a backwards edge merges exactly the
        same two islands and ``flow.conservation`` passes identically. It is not
        invisible to the factory: a backwards edge runs from the STARVING
        island's producer into the SATISFIED island's consumer, backpressure
        makes it inert because that consumer is already fed, and the shortfall
        stays unfixed while we report clean.

        This is the smallest shape that shows it. Two producer lanes of one
        machine, consumer lanes of two and one, cyclic pairing ``[(0,0),(1,1)]``:
        island 0 is short by one machine's output, island 1 balances exactly. So
        the edge must leave island 1 and arrive at island 0.

        Ordering by union-find root -- whichever key won the path-compression
        race -- emits ``(0, 0)``, draining the island that is already starving.
        """
        srcs = [_lane(1), _lane(1)]
        sinks = [_lane(2), _lane(1)]
        extra = _connect_short_cuts(srcs, sinks, [(0, 0), (1, 1)], F(1), F(1))

        assert extra == [(1, 0)], (
            f"expected the surplus island's producer (1) to feed the starving "
            f"island's consumer (0), got {extra}"
        )

    def test_a_single_lane_on_either_side_is_already_one_island(self) -> None:
        assert _connect_short_cuts([_lane(1)], [_lane(9)], [(0, 0)], F(1), F(9)) == []
        assert _connect_short_cuts([_lane(9)], [_lane(1)], [(0, 0)], F(1), F(9)) == []

    def test_the_pairing_without_rates_is_exactly_cyclic(self) -> None:
        """Additive: every caller that does not cost its islands is unchanged."""
        srcs, sinks = self._ports()
        assert _pair_lanes(srcs, sinks) == [
            (srcs[k % len(srcs)], sinks[k % len(sinks)])
            for k in range(max(len(srcs), len(sinks)))
        ]


def _one_island(pairs: list[tuple[int, int]], n: int, m: int) -> bool:
    parent: dict[tuple[str, int], tuple[str, int]] = {}

    def find(k: tuple[str, int]) -> tuple[str, int]:
        parent.setdefault(k, k)
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for i in range(n):
        find(("s", i))
    for j in range(m):
        find(("d", j))
    for i, j in pairs:
        a, b = find(("s", i)), find(("d", j))
        if a != b:
            parent[a] = b
    return len({find(k) for k in list(parent)}) == 1


def starved_shard_spec() -> BuildSpec:
    """A producer whose shards CANNOT both be fed, however the machines split.

    ``universe-matrix/no-proliferator``'s defect, scaled down until it costs a
    fraction of a second.  Four consumers exceed the sorter reach, so
    :func:`_shard_sinks` splits them two and two; the producer makes 3/4 per
    machine on four machines, exactly 3 items/s against exactly 3 of demand.
    The first pair wants 1 items/s, which is 4/3 machines, and the second wants
    2, which is 8/3.  **No pair of integers summing to four covers 4/3 and
    8/3**, so one shard starves whatever :func:`_allocate_machines` decides --
    it hands out two and two, and the second shard reaches 3/2 of the 2 it owes.

    The real build is the same arithmetic one size up: ``energetic-graphite``
    at 41/42 on 21 machines, its shards owing 5 (5.122 machines) and 31/2
    (15.878), split 6 and 15, and ``flow.conservation`` reporting 14 machines
    reaching 205/14 items/s of the 31/2 they consume.
    """
    sinks = _real_consumers_of("copper-ingot", 4)
    if len(sinks) < 4:
        pytest.skip(f"dataset has only {len(sinks)} mapped copper-ingot consumers")
    from flab2bp.lab.data import load_vendored

    data = load_vendored()
    groups = [
        group(
            "copper-ingot",
            "arc-smelter",
            4,
            {"copper-ore": F(3, 4)},
            {"copper-ingot": F(3, 4)},
        )
    ]
    outputs: dict[str, F] = {}
    for rid, n in zip(sinks, (1, 1, 2, 2), strict=True):
        produced = next(iter(data.recipe(rid).outputs))
        groups.append(
            group(
                rid,
                "assembling-machine-2",
                n,
                {"copper-ingot": F(1, 2)},
                {produced: F(1)},
            )
        )
        outputs[produced] = outputs.get(produced, F(0)) + F(n)
    return BuildSpec(
        groups=tuple(groups),
        external_inputs={"copper-ore": F(3)},
        outputs=outputs,
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="starved-shard",
    )


def _shard_balance(spec: BuildSpec, item: str) -> list[tuple[F, F]]:
    """``(supply, demand)`` per shard of ``item``'s producer, from the PLAN.

    A shard is the set of strips sharing one ``out_lanes`` tuple; its supply is
    its machines' output and its demand is what all of its destinations draw.
    Needed as its own function because the whole point of the defect is that it
    is decided in :func:`plan_strips`, long before anything is packed.
    """
    groups = {f"{g.recipe_id}#{i}": g for i, g in enumerate(spec.groups)}
    strips = plan_strips(spec, strip_len=6)
    machines: dict[str, int] = {}
    for s in strips:
        machines[s.group_key] = machines.get(s.group_key, 0) + s.machines
    shards: dict[
        tuple[str, tuple[tuple[str, str, CargoDomain], ...]],
        int,
    ] = {}
    for s in strips:
        key = (s.group_key, s.out_lanes)
        shards[key] = shards.get(key, 0) + s.machines
    out: list[tuple[F, F]] = []
    for (gk, lanes), n in shards.items():
        g = groups[gk]
        if item not in g.outputs_per_machine:
            continue
        dests = {
            destination
            for lane_item, destination, _cargo_domain in lanes
            if lane_item == item
            for destination in _dests(destination)
        }
        if not dests:
            continue
        demand = F(0)
        for d in dests:
            if d:
                demand += machines[d] * groups[d].inputs_per_machine.get(item, F(0))
            else:
                demand += spec.outputs.get(item, F(0))
        out.append((n * g.outputs_per_machine[item], demand))
    return sorted(out)


class TestAShardThatCannotFeedItself:
    """The cut ACROSS a producer's shards, which the pairing cannot see.

    :func:`_connect_short_cuts` makes the same argument one level down and is
    handed the ports of ONE ``(producer, item, destination)`` edge, so two
    shards of a group never reach it together.  :func:`_join_shard_islands`
    is that argument over every edge carrying the item.

    Belt indices here are arbitrary integers; only the graph and the rates
    matter.
    """

    #: Two shards of one producer.  Lane 20 owes 5 and makes 41/7; lane 10 owes
    #: 31/2 and makes 205/14.  `universe-matrix/no-proliferator`, exactly.
    PAIRS = [(10, 30), (10, 31), (20, 32), (20, 33)]
    SUPPLY = {10: F(205, 14), 20: F(41, 7)}
    DEMAND = {30: F(21, 2), 31: F(5), 32: F(3), 33: F(2)}

    def test_a_shard_that_feeds_itself_buys_nothing(self) -> None:
        """Extra belts crowd the router and the power lattice -- see
        `_connect_short_cuts`, where joining every edge cost four clean cells.
        """
        plenty = {10: F(100), 20: F(100)}
        assert _join_shard_islands(self.PAIRS, plenty, self.DEMAND, F(0)) == []

    def test_the_starving_shard_is_joined_to_the_one_with_slack(self) -> None:
        extra = _join_shard_islands(self.PAIRS, self.SUPPLY, self.DEMAND, F(0))
        assert extra == [(20, 30)], (
            "the surplus shard must be the SOURCE and the starving shard's lane "
            f"the sink; got {extra}"
        )

    def test_joining_them_makes_the_whole_edge_one_island(self) -> None:
        extra = _join_shard_islands(self.PAIRS, self.SUPPLY, self.DEMAND, F(0))
        merged = self.PAIRS + extra
        seen = {b for pair in merged for b in pair}
        parent = dict.fromkeys(seen)
        root = {b: b for b in seen}

        def find(k: int) -> int:
            while root[k] != k:
                root[k] = root[root[k]]
                k = root[k]
            return k

        for a, b in merged:
            root[find(a)] = find(b)
        assert len({find(b) for b in parent}) == 1, f"{merged} still cut"
        assert sum(self.SUPPLY.values()) == sum(self.DEMAND.values()), (
            "the joined island balances EXACTLY -- the deficit was never "
            "anything but the other shard's surplus"
        )

    def test_two_lanes_of_one_shard_are_one_island(self) -> None:
        """One strip's machines drain into every one of its own output lanes.

        So the lanes are one island however the destinations divide, and the
        shard's output is credited ONCE.  Without that sibling edge lane 11
        reads as a lane with no production at all and a net is bought to feed
        something that is already fed.
        """
        supply, demand = {10: F(3), 11: F(0)}, {30: F(1), 31: F(2)}
        cut = [(10, 30), (11, 31)]
        assert _join_shard_islands(cut, supply, demand, F(0)), (
            "without the sibling edge the surplus is invisible -- if this is "
            "empty the test below proves nothing"
        )
        assert _join_shard_islands([*cut, (10, 11)], supply, demand, F(0)) == []

    def test_what_the_player_belts_in_counts_on_every_island(self) -> None:
        """`_route_external_inputs` runs an entry belt to EVERY consumer lane,
        which is the credit `flow.conservation` gives.
        """
        supply, demand = {10: F(1), 20: F(1)}, {30: F(1), 31: F(3)}
        cut = [(10, 30), (20, 31)]
        assert _join_shard_islands(cut, supply, demand, F(0)) == [(10, 31)]
        assert _join_shard_islands(cut, supply, demand, F(2)) == []

    def test_the_plan_really_does_starve_a_shard(self) -> None:
        """Verify the instrument: the fixture must contain the defect.

        Every test below it reads green on a build with no starving shard, so
        without this they would pass against the unfixed code.
        """
        balance = _shard_balance(starved_shard_spec(), "copper-ingot")
        assert len(balance) == 2, f"expected two shards, got {balance}"
        assert sum(s for s, _d in balance) == sum(d for _s, d in balance) == F(3)
        assert [(s, d) for s, d in balance if d > s] == [(F(3, 2), F(2))], (
            f"the fixture no longer starves a shard: {balance}"
        )

    def test_it_lays_out_and_conserves_flow(self) -> None:
        spec = starved_shard_spec()
        p = FreeformLayout(
            band_policy=BandPolicy("100"),
            workers=DETERMINISTIC_WORKERS,
        ).lay_out(
            spec, time_budget_s=0.5
        )
        assert p.stats.get("route_failures", 0) == 0, "a net went unrouted"
        report = _full_report(p, spec)
        assert [f for f in report.errors if f.check == "flow.conservation"] == [], (
            "\n".join(f.message for f in report.errors if f.check == "flow.conservation")
        )
        assert report.ok, "\n".join(f"{f.check}: {f.message}" for f in report.errors[:8])


class TestTheTimeBudgetIsAWall:
    """``time_budget_s`` is the one deadline shared by every search phase."""

    def test_magnetic_ring_repeated_one_second_calls_complete(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _ = monkeypatch
        spec = magnetic_ring_spec()
        for repeat in range(12):
            placement = FreeformLayout(
                band_policy=BandPolicy("160"),
            ).lay_out(spec, time_budget_s=1.0)
            assert (
                placement.completion
                is PlacementCompletion.COMPACTED_AND_FINALIZED
            ), repeat
            report = _full_report(placement, spec)
            assert report.ok, (repeat, report.errors[:3])

    def test_a_refusal_uses_exactly_the_requested_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        observed: list[tuple[float, float]] = []

        def refuse(
            _layout: FreeformLayout,
            _spec: BuildSpec,
            _strips: list[Strip],
            sweep_s: float,
            deadline: float,
            *_args: object,
        ) -> None:
            observed.append((sweep_s, deadline - time.monotonic()))
            return None

        monkeypatch.setattr(FreeformLayout, "_sweep", refuse)
        with pytest.raises(NoValidLayout):
            FreeformLayout(
                band_policy=BandPolicy("portable"),
            ).lay_out(
                magnetic_ring_spec(), time_budget_s=0.5
            )

        assert len(observed) == 1
        sweep_s, remaining = observed[0]
        assert sweep_s == 0.5
        assert 0 < remaining <= 0.5

    def test_an_expired_deadline_refuses_and_says_so(self) -> None:
        """A clock running down must be distinguishable from a spec that cannot
        be laid out -- the first is our problem, the second is the spec's."""
        spec = magnetic_ring_spec()
        strips = plan_strips(spec, strip_len=6)
        # A deadline already in the past: every phase must decline to start.
        assert (
            FreeformLayout(
                band_policy=BandPolicy("portable"),
            )._sweep(spec, strips, 4.0, time.monotonic() - 1.0)
            is None
        )

    def test_preparation_cancellation_is_not_fabricated_as_route_failures(
        self,
    ) -> None:
        """An expired preparation has no net set from which failures could exist.

        The shared deadline still discards the pack, but its typed build-stage
        evidence must distinguish that honest empty result from a routed pack
        that wired every net.
        """
        spec = magnetic_ring_spec()
        strips = plan_strips(spec, strip_len=6)
        pack = _greedy_pack(strips, _height_seed(strips))
        result = _build(
            spec,
            strips,
            pack,
            power=True,
            route=True,
            policy=BandPolicy("portable"),
            deadline=time.monotonic() - 1.0,
        )
        assert result.routing.status is DetailedRouteStatus.BUDGET
        assert result.routing.failures == ()
        assert result.budget_stage is freeform._BuildBudgetStage.PREPARATION
        assert result.placement is None


class TestThroughTrafficLeavesTheGround:
    """Three altitudes exist, and wiring the whole block on one CUTS it.

    Only machines are solid at every level, so a belt at z=0 leaves z=1 and z=2
    open above it -- but a plain step costs 1 and a ramp costs 3, so A* had no
    reason to climb and never did unless it was already blocked.  Every net
    therefore wired on one plane, and a route crossing that plane walled off
    whatever was behind it: ramping over a belt needs two free tiles of run each
    side, and a dense pack has not got them.  Measured on ``universe-matrix``,
    36% of every failed search's wall was another net's committed path and the
    largest sealed pocket held 35,105 cells -- half the canvas, behind belts.
    """

    def test_a_long_run_climbs_and_a_short_one_does_not(self) -> None:
        """The toll has to be worth paying for through traffic ONLY.

        Ports sit on the ground and have to stay reachable across it, so a short
        hop must not buy altitude it cannot use.  A run pays ``L * (1 + t)`` on
        the ground against roughly ``L + 6`` in the air, so the crossover is
        around ``6 / t`` tiles and both sides of it are checked here.
        """
        canvas = _Canvas()
        canvas.limit = (-2, -2, 200, 20)
        bounds = (-2, -2, 200, 20)

        def levels_used(distance: int) -> set[int]:
            path = _astar(
                canvas,
                [(0, 0, 0)],
                {(distance, 0, 0)},
                {},
                1.0,
                bounds,
            ).path
            assert path is not None, f"no path over {distance} tiles of empty ground"
            return {lvl for _x, _y, lvl in path}

        assert levels_used(4) == {0}, (
            "a four-tile hop bought altitude it cannot pay back; ports are on "
            "the ground and short links have to stay there"
        )
        assert levels_used(160) != {0}, (
            "a 160-tile run stayed on the ground, so it cuts the one plane every "
            "other net and every port has to cross"
        )

    def test_the_heuristic_stays_admissible(self) -> None:
        """Every step still costs at least one, so Manhattan is still a bound.

        A toll that made a step cheaper than a tile would make the A* heuristic
        an OVER-estimate, and an inadmissible heuristic does not return the
        cheapest path -- it returns whichever one it stumbled on, silently.
        """
        assert min(_LEVEL_TOLL) >= 0.0, _LEVEL_TOLL
        assert len(_LEVEL_TOLL) == LEVELS, _LEVEL_TOLL


class TestAPathThatReachesNothingIsUnrouted:
    """The sink side is counted exactly like the source side.

    ``_sink_for`` used to name the lane head even when the path ended nowhere
    near it, on the reasoning that a wrong link is at least VISIBLE as
    ``belt.link_adjacent``.  Visible to whom: ``_commit_paths`` counted only
    source-side failures, so the break came back as ``failed = 0``, the sweep
    accepted the pack as fully wired, and it surfaced two layers later as a
    placement our own validator threw out.  Measured on
    ``universe-matrix/free-proliferation`` at 120s, which emitted three belts
    linking to a lane head 35 to 40 tiles away and three more stepping two
    altitude levels in a single tile.
    """

    def test_a_tail_with_nothing_beside_it_names_no_sink(self) -> None:
        canvas = _Canvas()
        dst_belt = canvas.add(_belt(40, 40, item="x"))
        tail = canvas.add(_belt(0, 0, item="x"))
        net = _Net(
            src=_Port(canvas.add(_belt(-9, -9, item="x")), -9, -9, -9, -9),
            dst=_Port(dst_belt, 40, 40, 40, 40),
            item="x",
        )
        assert _sink_for(canvas, tail, net, {tail}, set()) is None, (
            "a path ending 80 tiles from its lane head was handed the lane head "
            "anyway, which emits a belt linking to a building it is nowhere near"
        )

    def test_a_tail_beside_its_lane_head_still_links_to_it(self) -> None:
        """The common case has to be untouched, or every net becomes a failure."""
        canvas = _Canvas()
        dst_belt = canvas.add(_belt(1, 0, item="x"))
        tail = canvas.add(_belt(0, 0, item="x"))
        net = _Net(
            src=_Port(canvas.add(_belt(-9, -9, item="x")), -9, -9, -9, -9),
            dst=_Port(dst_belt, 1, 0, 1, 1),
            item="x",
        )
        assert _sink_for(canvas, tail, net, {tail}, set()) == dst_belt

    def test_a_tail_one_level_above_its_lane_head_does_not_link(self) -> None:
        """One level apart across one tile is the ILLEGAL step, not a legal link.

        This test used to assert the opposite, on the reasoning that "belts
        climb half a tile at a time, so one level apart is a legal link".  That
        is exactly backwards: climbing half a tile at a time is precisely WHY a
        whole tile of height cannot be gained in one tile of run.  The join
        needs two tiles and a belt at ``1/2`` between them, or it needs not to
        move at all -- and a tile diagonally adjacent in z is neither.

        Asserting the defect was correct is worse than having no test here: this
        one stood while `freeform` shipped the same step mid-path, and the
        agreement between a wrong check and a wrong test is what made it look
        settled.
        """
        canvas = _Canvas(ramped=True)  # the slope-limited path
        dst_belt = canvas.add(_belt(0, 0, item="x"))
        above = PlacedBuilding(
            item_id=2001, model_index=35, x=0, y=1, z=F(1), width=1, height=1,
            carries_item="x",
        )
        tail = canvas.add(above)
        net = _Net(
            src=_Port(canvas.add(_belt(-9, -9, item="x")), -9, -9, -9, -9),
            dst=_Port(dst_belt, 0, 0, 0, 0),
            item="x",
        )
        assert _sink_for(canvas, tail, net, {tail}, set()) is None

    def test_a_tail_a_ramp_step_above_its_lane_head_links(self) -> None:
        """Half a tile up and one tile along IS the ramp, so it joins."""
        canvas = _Canvas()
        dst_belt = canvas.add(_belt(0, 0, item="x"))
        tail = canvas.add(
            PlacedBuilding(
                item_id=2001, model_index=35, x=0, y=1, z=F(1, 2),
                width=1, height=1, carries_item="x",
            )
        )
        net = _Net(
            src=_Port(canvas.add(_belt(-9, -9, item="x")), -9, -9, -9, -9),
            dst=_Port(dst_belt, 0, 0, 0, 0),
            item="x",
        )
        assert _sink_for(canvas, tail, net, {tail}, set()) == dst_belt

    def test_a_tail_directly_above_its_lane_head_does_not_link(self) -> None:
        """Climbing with no run is infinite slope, which needs a tech we do not assume.

        The game has one rule -- slope -- and zero horizontal run is the case
        the `beltVerticalConstruction` unlock exists to permit.  It is off on a
        new save, so a blueprint that relies on it would not paste for
        everyone.  We ramp instead, which is legal at any height and needs no
        unlock.
        """
        canvas = _Canvas(ramped=True)  # the slope-limited path
        dst_belt = canvas.add(_belt(0, 0, item="x"))
        tail = canvas.add(
            PlacedBuilding(
                item_id=2001, model_index=35, x=0, y=0, z=F(1),
                width=1, height=1, carries_item="x",
            )
        )
        net = _Net(
            src=_Port(canvas.add(_belt(-9, -9, item="x")), -9, -9, -9, -9),
            dst=_Port(dst_belt, 0, 0, 0, 0),
            item="x",
        )
        assert _sink_for(canvas, tail, net, {tail}, set()) is None


class TestAMergeArrivesAtItsOwnDestination:
    """A destination lane can be MIXED, and a label cannot say where a belt goes.

    ``_sink_for`` used to accept "an adjacent belt carrying my item" as the
    merge, which is wrong in both directions.

    It REFUSED merges the router had aimed at.  ``_merge_frontier`` offers the
    free cells beside a ``dst_group`` sibling's path as goals -- sharing a
    destination tile is what makes a sibling, and items never enter it -- so A*
    ends the path there and this function threw it away whenever the sibling's
    belt was labelled with the OTHER item of a mixed lane.  That is every one of
    the seven unlinked paths on ``universe-matrix/max-proliferation`` at budget
    4: ``information-matrix`` beside ``structure-matrix`` into (106,20),
    ``antimatter`` beside ``electromagnetic-matrix`` into (106,18) and (78,33),
    ``gravity-matrix`` beside ``energy-matrix`` into (106,19).  Mixed lanes are
    not an accident of this pack -- ``validate._entry_items`` documents an entry
    lane labelled ``antimatter`` down its whole length with sorters drawing both
    ``antimatter`` and ``electromagnetic-matrix`` off it.

    And it ADMITTED merges nobody offered: an adjacent belt carrying our item
    that is not a sibling runs to a DIFFERENT consumer, so handing it our items
    delivers them there.  That is the sink-side twin of the ``_source_for``
    defect fixed in ``00d1f78``.
    """

    @staticmethod
    def _tail_beside(
        canvas: _Canvas, other: PlacedBuilding
    ) -> tuple[int, int, _Net]:
        """A net whose path ends at (0,0) with ``other`` at (1,0)."""
        neighbour = canvas.add(other)
        tail = canvas.add(_belt(0, 0, item="mine"))
        dst_belt = canvas.add(_belt(40, 40, item="mine"))
        net = _Net(
            src=_Port(canvas.add(_belt(-9, -9, item="mine")), -9, -9, -9, -9),
            dst=_Port(dst_belt, 40, 40, 40, 40),
            item="mine",
        )
        return neighbour, tail, net

    def test_a_sibling_carrying_the_other_item_is_still_the_way_in(self) -> None:
        canvas = _Canvas()
        neighbour, tail, net = self._tail_beside(canvas, _belt(1, 0, item="theirs"))
        assert _sink_for(canvas, tail, net, {tail}, {(1, 0, 0)}) == neighbour, (
            "the router routed this path to a cell beside a net delivering to "
            "the same lane tile, and the linker refused it because the lane is "
            "mixed and the sibling's label names the other item"
        )

    def test_a_stranger_carrying_our_item_is_not_the_way_in(self) -> None:
        """Same geometry, same label, no sibling: it goes somewhere else."""
        canvas = _Canvas()
        _, tail, net = self._tail_beside(canvas, _belt(1, 0, item="mine"))
        assert _sink_for(canvas, tail, net, {tail}, set()) is None, (
            "a belt that carries our item but does not deliver where we deliver "
            "is a different destination, not a cheaper way to reach ours"
        )

    def test_a_sibling_that_leads_back_here_is_still_refused(self) -> None:
        """``kin`` widens WHICH belts qualify, never the cycle rule."""
        canvas = _Canvas()
        neighbour, tail, net = self._tail_beside(canvas, _belt(1, 0, item="theirs"))
        canvas.buildings[neighbour] = _relink(
            canvas.buildings[neighbour], output_obj=tail
        )
        assert _sink_for(canvas, tail, net, {tail}, {(1, 0, 0)}) is None, (
            "merging into a belt that flows back into this path closes a loop, "
            "which `belt.acyclic` reports and the game runs items round forever"
        )


class TestABranchLeavesFromItsOwnSource:
    """A belt branch must carry the items of the net that built it.

    ``_source_for`` took the first adjacent belt carrying the right item, and at
    a merge point several do.  The router only ever starts a path away from its
    own lane on a ``_merge_frontier`` cell of a net that SHARES THAT LANE
    (``_route_all``'s ``src_group``), so any other belt beside the head belongs
    to a different producer -- branching off it silently swaps one source for
    another.

    That is the whole of the intermittent ``flow.conservation`` on
    ``quantum-chip/free-proliferation``.  ``titanium-glass`` shards into a
    four-machine and a three-machine strip, ``plane-filter`` into lanes of
    6/5/5, and the cyclic pairing hands the four-machine shard eleven consumers.
    ``_connect_short_cuts`` prices that island, finds it starving, and buys ONE
    extra net -- three-machine shard to the six-machine lane -- which is the only
    thing joining the two islands.  Captured from a failing build: that net
    routed to the single tile (80,25,1), and ``_source_for`` fed it from the
    belt at (81,25,1), a tile of the FOUR-machine shard's own path into the same
    lane.  One belt taking items off a lane and handing them straight back:
    adjacent, acyclic, right item, worth nothing.  Both counters read success so
    ``failed`` was 0, the sweep accepted the pack, and eleven machines were left
    drawing 11/4 items/s of titanium-glass from the 16/7 four machines make.

    Replayed on the five packs captured from 96 builds, every one of which
    reported ``flow.conservation`` before and certifies clean after, with
    ``failed`` still 0 -- so the join is now made rather than the pack refused.
    """

    @staticmethod
    def _scene() -> tuple[_Canvas, int, int, int, _Net]:
        """A head with a sibling to the west and a stranger to the EAST.

        East is the first entry in ``_STEPS``, so a scan that merely preferred
        siblings without excluding strangers would still pick the wrong one --
        which is exactly the order the captured failure had.
        """
        canvas = _Canvas()
        head = canvas.add(_belt(0, 0, item="x"))
        stranger = canvas.add(_belt(1, 0, item="x"))
        sibling = canvas.add(_belt(-1, 0, item="x"))
        net = _Net(
            src=_Port(canvas.add(_belt(0, 40, item="x")), 0, 40, 0, 40),
            dst=_Port(canvas.add(_belt(0, 80, item="x")), 0, 80, 0, 80),
            item="x",
        )
        return canvas, head, stranger, sibling, net

    def test_the_sibling_wins_over_a_stranger_scanned_first(self) -> None:
        canvas, head, stranger, sibling, net = self._scene()
        assert _source_for(canvas, head, net, {head}, {(-1, 0, 0)}) == sibling, (
            "the branch was fed from a belt of another producer's path merely "
            "because it was the first neighbour scanned"
        )
        assert _source_for(canvas, head, net, {head}, {(-1, 0, 0)}) != stranger

    def test_a_stranger_alone_beside_the_head_is_not_a_source(self) -> None:
        """No sibling reachable means no branch, not a branch off anybody.

        And not the net's own lane belt either.  It is far from the head, so
        naming it emits a link across the map -- reported by
        ``belt.link_adjacent``, but only after the routing pass has already
        counted the net as wired and the sweep has accepted the pack.  A path
        that leaves from nothing is UNROUTED, which is what ``_sink_for``
        already says about the other end.
        """
        canvas, head, stranger, _sibling, net = self._scene()
        got = _source_for(canvas, head, net, {head}, set())
        assert got is None, (
            "a head with no sibling beside it was given a feeder anyway: "
            f"{got} (the net's own lane belt is {net.source.belt})"
        )
        assert got != stranger

    def test_an_empty_sibling_set_is_the_safe_default(self) -> None:
        """``_commit_paths`` without ``src_group`` must not reopen the hole.

        A missed call site would otherwise hand ``_source_for`` no record of the
        siblings and restore the old any-belt-will-do scan.  Threading the
        groups can only ever ADD legal branches, never permit a stranger.
        """
        # The head cell is left EMPTY for `_commit_paths` to build on. Seeding a
        # belt there instead makes `canvas.free` reject the path, so nothing is
        # linked at all and the assertion below holds without exercising
        # anything -- which is how a first draft of this test read green against
        # the very bug it is here to pin.
        canvas = _Canvas()
        stranger = canvas.add(_belt(1, 0, item="x"))
        canvas.add(_belt(-1, 0, item="x"))
        net = _Net(
            src=_Port(canvas.add(_belt(0, 40, item="x")), 0, 40, 0, 40),
            dst=_Port(canvas.add(_belt(0, 80, item="x")), 0, 80, 0, 80),
            item="x",
        )
        head = len(canvas.buildings)  # the belt `_commit_paths` is about to lay
        _commit_paths(canvas, [net], {0: [(0, 0, 0)]}, 2001, 35)
        assert (canvas.buildings[head].x, canvas.buildings[head].y) == (0, 0), (
            "the path was not built, so this test would prove nothing"
        )
        assert canvas.buildings[stranger].output_obj != head, (
            "with no sibling record, a stranger beside the head was still made "
            "its feeder"
        )

    def test_selected_sibling_tap_wins_over_an_adjacent_lane_end(self) -> None:
        canvas = _Canvas()
        src_belt = canvas.add(_belt(0, 0, item="gear"))
        sibling = canvas.add(_belt(0, 1, item="gear"))
        head = canvas.add(_belt(1, 0, item="gear"))
        net = _Net(
            src=_Port(src_belt, 0, 0, 0, 0),
            dst=_Port(canvas.add(_belt(0, 80, item="gear")), 0, 80, 0, 80),
            item="gear",
        )

        assert (
            _source_for(
                canvas,
                head,
                net,
                {head},
                {(0, 1, 0)},
                hint=(0, 1, 0),
            )
            == sibling
        )


    def test_a_head_beside_its_own_lane_is_untouched(self) -> None:
        """The common case never reaches the scan and must not change."""
        canvas = _Canvas()
        src_belt = canvas.add(_belt(0, 0, item="x"))
        head = canvas.add(_belt(1, 0, item="x"))
        net = _Net(
            src=_Port(src_belt, 0, 0, 0, 0),
            dst=_Port(canvas.add(_belt(0, 80, item="x")), 0, 80, 0, 80),
            item="x",
        )
        assert _source_for(canvas, head, net, {head}, set()) == src_belt


class TestDetailedRoutingDiagnostics:
    @staticmethod
    def _net(
        canvas: _Canvas,
        src: tuple[int, int],
        dst: tuple[int, int],
        net_id: NetId,
    ) -> _Net:
        src_belt = canvas.add(_belt(*src, item=net_id.item))
        dst_belt = canvas.add(_belt(*dst, item=net_id.item))
        return _Net(
            src=_Port(src_belt, *src, src[0], src[0]),
            dst=_Port(dst_belt, *dst, dst[0], dst[0]),
            item=net_id.item,
            net_id=net_id,
        )

    @staticmethod
    def _block(canvas: _Canvas, cells: set[tuple[int, int]]) -> None:
        for x, y in cells:
            canvas.solid.add((x, y))
            for level in range(LEVELS):
                canvas.blocked[x, y, level] = 0

    def test_prelinked_model40_carry_offers_only_lower_branch_ports(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The routing frontier respects model 40's two physical port planes.

        The onward belt descends east after leaving the elevated source. Model
        40's opposite carry ports remain on that upper z=1 plane, so another
        east start is the same occupied port and must be withheld. Its
        perpendicular branch ports are on the lower z=0 plane; north and south
        starts must be offered there, never at the carry height.
        """
        canvas = _Canvas()
        bounds = (-4, -4, 4, 6)
        canvas.limit = bounds
        predecessor = canvas.add(replace(_belt(-1, 0, item="gear"), z=F(1)))
        source = canvas.add(replace(_belt(0, 0, item="gear"), z=F(1)))
        onward = canvas.add(replace(_belt(1, 0, item="gear"), z=F(0)))
        destination = canvas.add(replace(_belt(0, 4, item="gear"), z=F(1)))
        canvas.buildings[predecessor] = _relink(
            canvas.buildings[predecessor],
            output_obj=source,
        )
        canvas.buildings[source] = _relink(
            canvas.buildings[source],
            output_obj=onward,
        )
        net = _Net(
            src=_Port(
                source,
                0,
                0,
                -1,
                1,
                (predecessor, source, onward),
                z=1,
            ),
            dst=_Port(destination, 0, 4, 0, 0, (destination,), z=1),
            net_id=NetId(source, destination, "gear", NetRole.INTERNAL, 0),
            item="gear",
        )
        observed: list[tuple[Cell, ...]] = []

        def inspect_starts(
            _canvas: _Canvas,
            starts: Sequence[Cell],
            *_args: object,
            **_kwargs: object,
        ) -> _PathSearchResult:
            observed.append(tuple(starts))
            return _PathSearchResult(
                None,
                RouteFailureKind.DYNAMIC_ACCESS,
                (),
                0,
            )

        monkeypatch.setattr("flab2bp.layout.freeform._astar", inspect_starts)
        monkeypatch.setattr("flab2bp.layout.freeform.RRR_MAX", 1)
        monkeypatch.setattr("flab2bp.layout.freeform._REPAIR_PASSES", 0)

        _route_all(canvas, [net], 2001, 35, bounds)

        assert observed
        assert (1, 0, 1) not in observed[0]
        starts = set(observed[0])
        assert {(0, -1, 0), (0, 1, 0)} <= starts
        assert not {(0, -1, 1), (0, 1, 1)} & starts

    def test_a_sealed_pocket_reports_the_failed_net_and_blocking_owner(
        self,
    ) -> None:
        canvas = _Canvas()
        bounds = (-6, -6, 6, 6)
        canvas.limit = bounds
        blocker_id = NetId(0, 1, "blocker", NetRole.INTERNAL, 0)
        failed_id = NetId(2, 3, "target", NetRole.INTERNAL, 0)
        blocker = self._net(canvas, (0, -2), (1, -1), blocker_id)
        failed = self._net(canvas, (0, 1), (0, 3), failed_id)
        self._block(
            canvas,
            {
                (-1, -2),
                (1, -2),
                (0, -3),
                (2, -1),
                (1, 0),
                (-1, -1),
                (-1, 0),
                (-1, 1),
                (1, 1),
                (0, 2),
            },
        )

        result = _route_all(canvas, [blocker, failed], 2001, 35, bounds)

        failure = result.failures[0]
        assert failure.net_id == failed_id
        assert failure.kind is RouteFailureKind.SEALED_POCKET
        assert blocker_id in failure.blocking_nets
        assert failure.wall

    def test_repair_search_cap_is_budget_unknown_without_shared_exhaustion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        canvas = _Canvas()
        bounds = (-6, -6, 6, 6)
        canvas.limit = bounds
        blocker_id = NetId(0, 1, "blocker", NetRole.INTERNAL, 0)
        failed_id = NetId(2, 3, "target", NetRole.INTERNAL, 0)
        blocker = self._net(canvas, (-4, -4), (-2, -4), blocker_id)
        failed = self._net(canvas, (0, 1), (0, 3), failed_id)
        self._block(
            canvas,
            {
                (1, 0),
                (-1, 0),
                (1, -1),
                (-1, -1),
                (0, -2),
                (-1, 1),
                (1, 1),
                (0, 2),
            },
        )
        wall = (0, -1, 0)
        original_astar = _astar
        calls = 0
        search_grids: list[_Grid] = []

        def capped_repair_astar(
            *args: object, **kwargs: object
        ) -> _PathSearchResult:
            nonlocal calls
            calls += 1
            search_grid = args[9]
            assert isinstance(search_grid, _Grid)
            search_grids.append(search_grid)
            if calls == 1:
                return _PathSearchResult((wall,), None, (), 1)
            if calls == 2:
                return _PathSearchResult(
                    None, RouteFailureKind.SEALED_POCKET, (wall,), 1
                )
            return original_astar(*args, **kwargs)  # type: ignore[arg-type]

        shared_budget = {"left": 1000}
        monkeypatch.setattr(
            "flab2bp.layout.freeform._astar", capped_repair_astar
        )
        monkeypatch.setattr("flab2bp.layout.freeform._MAX_EXPANSIONS", 1)
        monkeypatch.setattr("flab2bp.layout.freeform.RRR_MAX", 1)
        monkeypatch.setattr("flab2bp.layout.freeform._REPAIR_PASSES", 1)
        monkeypatch.setattr(
            "flab2bp.layout.freeform._commit_paths",
            lambda *_args, **_kwargs: (),
        )

        result = _route_all(
            canvas,
            [blocker, failed],
            2001,
            35,
            bounds,
            budget=shared_budget,
        )

        failure = next(f for f in result.failures if f.net_id == failed_id)
        assert calls == 3
        assert search_grids[0] is search_grids[1]
        assert search_grids[2] is not search_grids[0]
        assert search_grids[2].routing_flags is not search_grids[0].routing_flags
        assert shared_budget["left"] > 0
        assert result.status is DetailedRouteStatus.BUDGET
        assert failure.kind is RouteFailureKind.BUDGET
        assert failure.wall == ()
        assert failure.blocking_nets == ()

    def test_displaced_net_search_cap_is_budget_unknown_after_crossing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        canvas = _Canvas()
        bounds = (-8, -8, 8, 8)
        canvas.limit = bounds
        blocker_id = NetId(0, 1, "blocker", NetRole.INTERNAL, 0)
        failed_id = NetId(2, 3, "target", NetRole.INTERNAL, 0)
        blocker = self._net(canvas, (-6, -5), (-1, -5), blocker_id)
        failed = self._net(canvas, (0, 1), (0, 3), failed_id)
        wall = (0, -1, 0)
        original_astar = _astar
        calls = 0

        def capped_victim_astar(
            *args: object, **kwargs: object
        ) -> _PathSearchResult:
            nonlocal calls
            calls += 1
            if calls == 1:
                return _PathSearchResult((wall,), None, (), 1)
            if calls == 2:
                return _PathSearchResult(
                    None, RouteFailureKind.SEALED_POCKET, (wall,), 1
                )
            if calls == 3:
                return _PathSearchResult((wall,), None, (), 1)
            return original_astar(*args, **kwargs)  # type: ignore[arg-type]

        shared_budget = {"left": 1000}
        monkeypatch.setattr(
            "flab2bp.layout.freeform._astar", capped_victim_astar
        )
        monkeypatch.setattr("flab2bp.layout.freeform._MAX_EXPANSIONS", 1)
        monkeypatch.setattr("flab2bp.layout.freeform.RRR_MAX", 1)
        monkeypatch.setattr("flab2bp.layout.freeform._REPAIR_PASSES", 1)
        monkeypatch.setattr(
            "flab2bp.layout.freeform._commit_paths",
            lambda *_args, **_kwargs: (),
        )

        result = _route_all(
            canvas,
            [blocker, failed],
            2001,
            35,
            bounds,
            budget=shared_budget,
        )

        failure = next(f for f in result.failures if f.net_id == failed_id)
        assert calls == 4
        assert shared_budget["left"] > 0
        assert result.status is DetailedRouteStatus.BUDGET
        assert failure.kind is RouteFailureKind.BUDGET
        assert failure.wall == ()
        assert failure.blocking_nets == ()

    def test_budget_exhaustion_is_reported_as_unknown(self) -> None:
        canvas = _Canvas()
        bounds = (-4, -4, 8, 4)
        canvas.limit = bounds
        net_id = NetId(0, 1, "budgeted", NetRole.INTERNAL, 0)
        net = self._net(canvas, (0, 0), (4, 0), net_id)

        result = _route_all(
            canvas,
            [net],
            2001,
            35,
            bounds,
            budget={"left": 0},
        )

        assert result.status is DetailedRouteStatus.BUDGET
        assert result.failures[0].kind is RouteFailureKind.BUDGET
        assert result.failures[0].wall == ()
        assert result.failures[0].blocking_nets == ()

    def test_bottom_of_round_deadline_never_commits_and_keeps_budget_evidence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        canvas = _Canvas()
        bounds = (-8, -8, 8, 8)
        canvas.limit = bounds
        first_id = NetId(0, 1, "first", NetRole.INTERNAL, 0)
        second_id = NetId(2, 3, "second", NetRole.INTERNAL, 0)
        nets = [
            self._net(canvas, (-6, -2), (-4, -2), first_id),
            self._net(canvas, (-6, 2), (-4, 2), second_id),
        ]
        walls = (((0, -1, 0),), ((0, 1, 0),))
        searches = iter(
            (
                _PathSearchResult(
                    None, RouteFailureKind.SEALED_POCKET, walls[0], 3
                ),
                _PathSearchResult(
                    None, RouteFailureKind.SEALED_POCKET, walls[1], 5
                ),
            )
        )
        ticks = iter((0.0, 0.0, 2.0, 2.0))

        monkeypatch.setattr(
            freeform,
            "_astar",
            lambda *_args, **_kwargs: next(searches),
        )
        monkeypatch.setattr(freeform, "_REPAIR_PASSES", 0)
        monkeypatch.setattr(
            "flab2bp.layout.freeform.time.monotonic",
            lambda: next(ticks),
        )
        monkeypatch.setattr(
            freeform,
            "_commit_paths",
            lambda *_args, **_kwargs: pytest.fail(
                "an expired routing round reached path commit"
            ),
        )

        result = _route_all(
            canvas,
            nets,
            2001,
            35,
            bounds,
            deadline=1.0,
            budget={"left": 100},
        )

        assert result.status is DetailedRouteStatus.BUDGET
        assert tuple(failure.net_id for failure in result.failures) == (
            first_id,
            second_id,
        )
        assert tuple(failure.kind for failure in result.failures) == (
            RouteFailureKind.BUDGET,
            RouteFailureKind.BUDGET,
        )
        assert tuple(failure.wall for failure in result.failures) == ((), ())
        assert tuple(failure.blocking_nets for failure in result.failures) == ((), ())
        assert tuple(failure.expansions for failure in result.failures) == (3, 5)
        assert result.expansions == 8

    def test_successful_round_deadline_expires_before_commit_preflight(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        canvas = _Canvas()
        bounds = (-8, -8, 8, 8)
        canvas.limit = bounds
        first_id = NetId(0, 1, "first", NetRole.INTERNAL, 0)
        second_id = NetId(2, 3, "second", NetRole.INTERNAL, 0)
        nets = [
            self._net(canvas, (-6, -2), (-4, -2), first_id),
            self._net(canvas, (-6, 2), (-4, 2), second_id),
        ]
        searches = iter(
            (
                _PathSearchResult(((-5, -2, 0),), None, (), 3),
                _PathSearchResult(((-5, 2, 0),), None, (), 5),
            )
        )
        ticks = iter((0.0, 0.0, 2.0))

        monkeypatch.setattr(
            freeform,
            "_astar",
            lambda *_args, **_kwargs: next(searches),
        )
        monkeypatch.setattr(
            "flab2bp.layout.freeform.time.monotonic",
            lambda: next(ticks),
        )
        monkeypatch.setattr(
            freeform,
            "_commit_paths",
            lambda *_args, **_kwargs: pytest.fail(
                "an expired successful round reached commit preflight"
            ),
        )

        result = _route_all(
            canvas,
            nets,
            2001,
            35,
            bounds,
            deadline=1.0,
            budget={"left": 100},
        )

        assert result.status is DetailedRouteStatus.BUDGET
        assert result.routed == ()
        assert tuple(failure.net_id for failure in result.failures) == (
            first_id,
            second_id,
        )
        assert tuple(failure.kind for failure in result.failures) == (
            RouteFailureKind.BUDGET,
            RouteFailureKind.BUDGET,
        )
        assert tuple(failure.wall for failure in result.failures) == ((), ())
        assert tuple(failure.blocking_nets for failure in result.failures) == ((), ())
        assert tuple(failure.expansions for failure in result.failures) == (3, 5)
        assert result.iterations == 1
        assert result.expansions == 8

    def test_empty_live_starts_take_precedence_over_budget(self) -> None:
        canvas = _Canvas()
        bounds = (-2, -2, 2, 2)
        canvas.limit = bounds

        result = _astar(
            canvas,
            [],
            {(1, 0, 0)},
            {},
            1.0,
            bounds,
            budget={"left": 0},
        )

        assert result.kind is RouteFailureKind.DYNAMIC_ACCESS
        assert result.expansions == 0

    def test_repair_open_grid_excludes_passable_paths_from_the_wall(self) -> None:
        canvas = _Canvas()
        bounds = (-4, -4, 4, 4)
        canvas.limit = bounds
        self._block(
            canvas,
            {(1, 0), (-1, 0), (0, 1), (0, -2), (1, -1), (-1, -1)},
        )
        grid = _make_grid(canvas, bounds, _canvas_span(canvas, bounds), {})
        wall = (0, -1, 0)
        canvas.blocked[wall] = _TENTATIVE
        grid.block(wall)
        open_grid = replace(grid, occ=bytearray(grid.base), hist=None)
        blame: dict[tuple[int, int, int], float] = {}

        result = _astar(
            canvas,
            [(0, 0, 0)],
            {(3, 3, 0)},
            {},
            1.0,
            bounds,
            blame=blame,
            grid=open_grid,
        )

        assert result.path is None
        assert result.kind is RouteFailureKind.SEALED_POCKET
        assert result.wall == ()
        assert blame == {}

    def test_occupied_destination_docks_name_their_blocking_net(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        canvas = _Canvas()
        bounds = (-8, -8, 8, 8)
        canvas.limit = bounds
        blocker_id = NetId(0, 1, "blocker", NetRole.INTERNAL, 0)
        failed_id = NetId(2, 3, "failed", NetRole.INTERNAL, 0)
        nets = [
            self._net(canvas, (-7, -7), (7, 7), blocker_id),
            self._net(canvas, (-4, 0), (0, 0), failed_id),
        ]
        destination_docks = (
            (1, 0, 0),
            (-1, 0, 0),
            (0, 1, 0),
            (0, -1, 0),
        )
        searches = iter(
            (
                _PathSearchResult(destination_docks, None, (), 1),
                _PathSearchResult(
                    None,
                    RouteFailureKind.DYNAMIC_ACCESS,
                    (),
                    0,
                ),
            )
        )

        def scripted_astar(
            _canvas: _Canvas,
            _starts: list[Cell],
            goals: set[Cell],
            *_args: object,
            **_kwargs: object,
        ) -> _PathSearchResult:
            result = next(searches)
            if result.path is None:
                assert goals == set()
            return result

        monkeypatch.setattr("flab2bp.layout.freeform._astar", scripted_astar)
        monkeypatch.setattr("flab2bp.layout.freeform.RRR_MAX", 1)
        monkeypatch.setattr("flab2bp.layout.freeform._REPAIR_PASSES", 0)

        result = _route_all(canvas, nets, 2001, 35, bounds)

        failure = next(f for f in result.failures if f.net_id == failed_id)
        assert set(failure.wall) == set(destination_docks)
        assert failure.blocking_nets == (blocker_id,)


    def test_occupied_source_docks_name_their_blocking_net(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        canvas = _Canvas()
        bounds = (-8, -8, 8, 8)
        canvas.limit = bounds
        blocker_id = NetId(0, 1, "blocker", NetRole.INTERNAL, 0)
        failed_id = NetId(2, 3, "failed", NetRole.INTERNAL, 0)
        nets = [
            self._net(canvas, (-7, -7), (7, 7), blocker_id),
            self._net(canvas, (0, 0), (4, 0), failed_id),
        ]
        source_docks = (
            (1, 0, 0),
            (-1, 0, 0),
            (0, 1, 0),
            (0, -1, 0),
        )
        searches = iter(
            (
                _PathSearchResult(source_docks, None, (), 1),
                _PathSearchResult(
                    None,
                    RouteFailureKind.DYNAMIC_ACCESS,
                    (),
                    0,
                ),
            )
        )

        def scripted_astar(
            _canvas: _Canvas,
            starts: Sequence[Cell],
            _goals: set[Cell],
            *_args: object,
            **_kwargs: object,
        ) -> _PathSearchResult:
            result = next(searches)
            if result.path is None:
                assert starts == []
            return result

        monkeypatch.setattr("flab2bp.layout.freeform._astar", scripted_astar)
        monkeypatch.setattr("flab2bp.layout.freeform.RRR_MAX", 1)
        monkeypatch.setattr("flab2bp.layout.freeform._REPAIR_PASSES", 0)

        result = _route_all(canvas, nets, 2001, 35, bounds)

        failure = next(f for f in result.failures if f.net_id == failed_id)
        assert set(failure.wall) == set(source_docks)
        assert failure.blocking_nets == (blocker_id,)

    def test_repair_frontier_can_name_movable_splitter_keepout(self) -> None:
        canvas = _Canvas()
        path = ((0, 0, 0),)
        canvas.blocked[0, 1, 0] = _TENTATIVE

        strict = freeform._merge_frontier(
            canvas,
            {0: path},
            (0,),
            lambda _x, _y, _level: True,
        )
        provenance: dict[Cell, Cell] = {}
        repair = freeform._merge_frontier(
            canvas,
            {0: path},
            (0,),
            lambda _x, _y, _level: True,
            provenance=provenance,
            tentative_ok=True,
        )

        assert strict == set()
        assert (0, 1, 0) in repair
        assert provenance[0, 1, 0] == (0, 0, 0)

    def test_first_fanout_route_detours_to_hold_a_future_tap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        canvas = _Canvas()
        bounds = (-3, -4, 13, 3)
        canvas.limit = bounds
        source = canvas.add(_belt(0, 0, item="gear"))
        far_destination = canvas.add(_belt(10, 0, item="gear"))
        near_destination = canvas.add(_belt(2, -3, item="gear"))
        canvas.add(_belt(0, -1, item="static"))
        for x in range(1, 10):
            canvas.add(_belt(x, 1, item="static"))
        shared_port = _Port(source, 0, 0, 0, 0)
        nets = [
            _Net(
                src=shared_port,
                dst=_Port(far_destination, 10, 0, 10, 10),
                item="gear",
                net_id=NetId(0, 1, "gear", NetRole.INTERNAL, 0),
            ),
            _Net(
                src=shared_port,
                dst=_Port(near_destination, 2, -3, 2, 2),
                item="gear",
                net_id=NetId(0, 2, "gear", NetRole.INTERNAL, 1),
            ),
        ]
        searches = 0

        def scripted_astar(
            attempt_canvas: _Canvas,
            *_args: object,
            **_kwargs: object,
        ) -> _PathSearchResult:
            nonlocal searches
            searches += 1
            if searches == 1:
                return _PathSearchResult(
                    tuple((x, 0, 0) for x in range(1, 10)),
                    None,
                    (),
                    9,
                )
            if searches == 2:
                detour = (
                    (-1, 0, 0),
                    (-1, -1, 0),
                    (-1, -2, 0),
                    *(tuple((x, -2, 0) for x in range(11))),
                    (10, -1, 0),
                    (10, 0, 0),
                )
                return _PathSearchResult(detour, None, (), len(detour))
            assert attempt_canvas.guard
            return _PathSearchResult(
                None,
                RouteFailureKind.BUDGET,
                (),
                0,
            )

        monkeypatch.setattr(freeform, "_astar", scripted_astar)
        monkeypatch.setattr(freeform, "RRR_MAX", 1)
        monkeypatch.setattr(freeform, "_REPAIR_PASSES", 0)

        result = _route_all(canvas, nets, 2001, 35, bounds)

        assert result.status is DetailedRouteStatus.BUDGET
        assert searches == 3

    def test_repair_moves_a_route_out_of_a_future_fanout_junction(self) -> None:
        canvas = _Canvas()
        bounds = (-3, -4, 23, 4)
        canvas.limit = bounds
        for x in range(bounds[0], bounds[2] + 1):
            for y in range(bounds[1], bounds[3] + 1):
                canvas.belt_ban[x, y] = set(range(1, LEVELS))
        source = canvas.add(_belt(0, 0, item="gear"))
        far_destination = canvas.add(_belt(20, 0, item="gear"))
        near_destination = canvas.add(_belt(2, -2, item="gear"))
        foreign_source = canvas.add(_belt(1, 1, item="foreign"))
        foreign_destination = canvas.add(_belt(19, 1, item="foreign"))
        canvas.add(_belt(0, -1, item="static"))
        shared_port = _Port(source, 0, 0, 0, 0)
        nets = [
            _Net(
                src=shared_port,
                dst=_Port(far_destination, 20, 0, 20, 20),
                item="gear",
                net_id=NetId(0, 1, "gear", NetRole.INTERNAL, 0),
            ),
            _Net(
                src=shared_port,
                dst=_Port(near_destination, 2, -2, 2, 2),
                item="gear",
                net_id=NetId(0, 2, "gear", NetRole.INTERNAL, 1),
            ),
            _Net(
                src=_Port(foreign_source, 1, 1, 1, 1),
                dst=_Port(foreign_destination, 19, 1, 19, 19),
                item="foreign",
                net_id=NetId(3, 4, "foreign", NetRole.INTERNAL, 0),
            ),
        ]

        result = _route_all(
            canvas,
            nets,
            2001,
            35,
            bounds,
            budget={"left": 500_000},
        )

        assert result.status is DetailedRouteStatus.ROUTED
        assert result.failed_count == 0
        assert any(
            building.item_id == catalog.SPLITTER_ID
            for building in canvas.buildings
        )



    def test_blocking_owners_are_snapshotted_when_the_search_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        canvas = _Canvas()
        bounds = (-8, -8, 8, 8)
        canvas.limit = bounds
        original_id = NetId(0, 1, "original", NetRole.INTERNAL, 0)
        failed_id = NetId(2, 3, "failed", NetRole.INTERNAL, 0)
        replacement_id = NetId(4, 5, "replacement", NetRole.INTERNAL, 0)
        nets = [
            self._net(canvas, (-4, -4), (-2, -4), original_id),
            self._net(canvas, (-4, 0), (-2, 0), failed_id),
            self._net(canvas, (-4, 4), (-2, 4), replacement_id),
        ]
        wall = (5, 5, 0)
        searches = iter(
            (
                _PathSearchResult((wall,), None, (), 1),
                _PathSearchResult(
                    None, RouteFailureKind.SEALED_POCKET, (wall,), 1
                ),
                _PathSearchResult((wall,), None, (), 1),
            )
        )

        def scripted_astar(*_args: object, **_kwargs: object) -> _PathSearchResult:
            return next(searches)

        monkeypatch.setattr("flab2bp.layout.freeform._astar", scripted_astar)
        monkeypatch.setattr("flab2bp.layout.freeform.RRR_MAX", 1)
        monkeypatch.setattr("flab2bp.layout.freeform._REPAIR_PASSES", 0)
        monkeypatch.setattr(
            "flab2bp.layout.freeform._commit_paths",
            lambda *_args, **_kwargs: (),
        )

        result = _route_all(canvas, nets, 2001, 35, bounds)

        failure = next(f for f in result.failures if f.net_id == failed_id)
        assert failure.blocking_nets == (original_id,)

    def test_mixed_internal_and_proliferator_owners_have_total_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        canvas = _Canvas()
        bounds = (-8, -8, 8, 8)
        canvas.limit = bounds
        proliferator_id = NetId(
            None, 1, "spray", NetRole.PROLIFERATOR, 0
        )
        internal_id = NetId(2, 3, "internal", NetRole.INTERNAL, 0)
        failed_id = NetId(4, 5, "failed", NetRole.INTERNAL, 0)
        nets = [
            self._net(canvas, (-4, -4), (-2, -4), proliferator_id),
            self._net(canvas, (-4, 0), (-2, 0), internal_id),
            self._net(canvas, (-4, 4), (-2, 4), failed_id),
        ]
        first_wall = (5, 4, 0)
        second_wall = (5, 5, 0)
        searches = iter(
            (
                _PathSearchResult((first_wall,), None, (), 1),
                _PathSearchResult((second_wall,), None, (), 1),
                _PathSearchResult(
                    None,
                    RouteFailureKind.SEALED_POCKET,
                    (first_wall, second_wall),
                    1,
                ),
            )
        )

        def scripted_astar(*_args: object, **_kwargs: object) -> _PathSearchResult:
            return next(searches)

        monkeypatch.setattr("flab2bp.layout.freeform._astar", scripted_astar)
        monkeypatch.setattr("flab2bp.layout.freeform.RRR_MAX", 1)
        monkeypatch.setattr("flab2bp.layout.freeform._REPAIR_PASSES", 0)
        monkeypatch.setattr(
            "flab2bp.layout.freeform._commit_paths",
            lambda *_args, **_kwargs: (),
        )

        result = _route_all(canvas, nets, 2001, 35, bounds)

        failure = next(f for f in result.failures if f.net_id == failed_id)
        assert failure.blocking_nets == (proliferator_id, internal_id)



class TestAFailedSearchNamesTheWallThatCutIt:
    """A committed path is ``blocked``, not expensive, so nets never overlap and
    PathFinder's overuse signal -- what a history term exists to carry -- is
    identically zero here.  Every round would otherwise re-run the same nets in
    the same order against a uniformly, uselessly dearer map.

    The recoverable signal is the wall.  When A*'s heap empties -- the one
    ending that proves no path exists, as against a spent cap, budget or clock
    -- the settled set is the reachable pocket and the committed cells touching
    it are what cut this net off.
    """

    @staticmethod
    def _boxed_in() -> tuple[_Canvas, tuple[int, int, int, int]]:
        """One free cell, walled by machines on three sides and a belt on the
        fourth.  Machines are solid at every altitude and the ramp out needs its
        ground cell free, so this really is a pocket of one."""
        canvas = _Canvas()
        for cell in ((1, 0), (-1, 0), (0, 1)):
            canvas.solid.add(cell)
            for lvl in range(LEVELS):
                canvas.blocked[cell[0], cell[1], lvl] = 0
        canvas.blocked[0, -1, 0] = _TENTATIVE
        bounds = (-40, -40, 40, 40)
        canvas.limit = bounds
        return canvas, bounds

    def test_a_sealed_pocket_charges_the_committed_cell(self) -> None:
        canvas, bounds = self._boxed_in()
        blame: dict[tuple[int, int, int], float] = {}
        result = _astar(
            canvas,
            [(0, 0, 0)],
            {(30, 30, 0)},
            {},
            1.0,
            bounds,
            None,
            None,
            blame,
        )
        assert result.path is None
        assert blame == {(0, -1, 0): 1.0}, (
            "the one committed cell walling this net in was not charged, so "
            f"rip-up has nothing to negotiate over: {blame}"
        )

    def test_a_search_that_succeeds_charges_nobody(self) -> None:
        """Blame is for proving a seal, not for reporting traffic."""
        canvas = _Canvas()
        canvas.limit = (-40, -40, 40, 40)
        canvas.blocked[0, -1, 0] = _TENTATIVE
        blame: dict[tuple[int, int, int], float] = {}
        result = _astar(
            canvas,
            [(0, 0, 0)],
            {(4, 0, 0)},
            {},
            1.0,
            (-40, -40, 40, 40),
            None,
            None,
            blame,
        )
        assert result.path is not None
        assert blame == {}, blame

    def test_a_spent_budget_charges_nobody(self) -> None:
        """Running out of expansions says the search stopped, not that the
        pocket is sealed.  Charging a wall never shown to be one is how a
        negotiation term becomes noise."""
        canvas, bounds = self._boxed_in()
        blame: dict[tuple[int, int, int], float] = {}
        result = _astar(
            canvas,
            [(0, 0, 0)],
            {(30, 30, 0)},
            {},
            1.0,
            bounds,
            {"left": 0},
            None,
            blame,
        )
        assert result.path is None
        assert blame == {}, blame

    def test_a_wall_too_diffuse_to_accuse_anyone_charges_nobody(self) -> None:
        """A pocket walled by three cells has named a suspect.  One walled by
        hundreds is describing the corridor network, and charging all of it just
        makes every route longer -- measured as the difference between 62-66
        clean over the corpus and 64-66."""
        canvas = _Canvas()
        bounds = (-40, -40, 200, 40)
        canvas.limit = bounds
        span = _BLAME_MAX_WALL  # a corridor this long has 2x3x span wall cells
        for x in range(-1, span + 1):
            for y in (-1, 1):
                for lvl in range(LEVELS):
                    canvas.blocked[x, y, lvl] = _TENTATIVE
        for x in (-1, span):
            canvas.solid.add((x, 0))
            for lvl in range(LEVELS):
                canvas.blocked[x, 0, lvl] = 0
        blame: dict[tuple[int, int, int], float] = {}
        result = _astar(
            canvas,
            [(0, 0, 0)],
            {(150, 30, 0)},
            {},
            1.0,
            bounds,
            None,
            None,
            blame,
        )
        assert result.path is None
        assert blame == {}, f"{len(blame)} cells charged for a diffuse wall"


class TestTheFlatGridIsTheSameSearch:
    """``_astar`` runs on flat integer cell indices, and neither the index nor
    the caller-supplied grid may change what it finds.

    The whole point of ``_Grid`` is that it is an ENCODING of the canvas, not a
    second source of truth.  Two things can break that quietly, and both are
    pinned here: the index's ordering, which decides ties, and the grid's
    freshness, which decides what is passable.
    """

    @staticmethod
    def _maze() -> tuple[_Canvas, tuple[int, int, int, int]]:
        """Enough shape that a tie-break or a stale cell would show up: two
        walls with a gap, a keep-out cell, and a reservation across the way."""
        canvas = _Canvas()
        bounds = (-6, -6, 24, 12)
        canvas.limit = bounds
        for y in range(-4, 6):
            if y == 1:
                continue
            for lvl in range(LEVELS):
                canvas.blocked[6, y, lvl] = 0
            canvas.solid.add((6, y))
        for y in range(-4, 6):
            if y == 4:
                continue
            for lvl in range(LEVELS):
                canvas.blocked[13, y, lvl] = 0
            canvas.solid.add((13, y))
        canvas.keep_out.add((9, 1))
        canvas.blocked[3, 0, 0] = _TENTATIVE
        canvas.reserved[10, 2, 0] = (10, 3, 0)
        return canvas, bounds

    def test_the_index_orders_cells_the_way_tuples_did(self) -> None:
        """X-major, then y, then level -- and it is not a matter of taste.

        ``heapq`` breaks a tie on ``(f, cost)`` by comparing the third element,
        so the cell's own ordering picks between two equal-cost paths.  When
        cells were tuples that order was x, then y, then level; the flat index
        has to reproduce it exactly or the router silently makes different
        choices.  Injected as a fault, a level-major index left the expansion
        count byte-identical and moved the committed paths, so nothing else in
        this suite would catch it.
        """
        canvas, bounds = self._maze()
        grid = _make_grid(canvas, bounds, _canvas_span(canvas, bounds), {})
        cells = [
            (x, y, lvl)
            for x in range(-3, 4)
            for y in range(-3, 4)
            for lvl in range(LEVELS)
        ]
        assert sorted(cells, key=grid.index) == sorted(cells), (
            "the flat index no longer orders cells the way (x, y, level) tuples "
            "do, so every heapq tie now falls a different way and the router is "
            "making different choices than it did"
        )

    def test_a_caller_grid_finds_the_identical_path(self) -> None:
        canvas, bounds = self._maze()
        canvas.routing_ports = frozenset({(10, 3, 0)})
        alone = _astar(canvas, [(0, 0, 0)], {(20, 0, 0)}, {}, 1.0, bounds).path
        grid = _make_grid(canvas, bounds, _canvas_span(canvas, bounds), {})
        shared = _astar(
            canvas,
            [(0, 0, 0)],
            {(20, 0, 0)},
            {},
            1.0,
            bounds,
            None,
            None,
            None,
            grid,
        ).path
        assert alone is not None
        assert shared == alone, (
            "a caller-supplied grid changed the path, so it is not an encoding "
            "of the canvas but a second, disagreeing copy of it"
        )

    def test_a_grid_built_for_another_box_is_not_used(self) -> None:
        """``bounds`` is baked into the grid, so one for a different box is a
        wrong answer waiting to happen and has to be refused, not trusted."""
        canvas, bounds = self._maze()
        stale = _make_grid(
            canvas,
            (0, 0, 4, 4),
            _canvas_span(canvas, (0, 0, 4, 4)),
            {},
        )
        got = _astar(
            canvas,
            [(0, 0, 0)],
            {(20, 0, 0)},
            {},
            1.0,
            bounds,
            None,
            None,
            None,
            stale,
        ).path
        expected = _astar(
            canvas, [(0, 0, 0)], {(20, 0, 0)}, {}, 1.0, bounds
        ).path
        assert got == expected

    def test_block_and_restore_return_the_cell_to_what_it_was(self) -> None:
        """Rip-up restores from ``base``, not to 1.

        A ripped cell is not necessarily free -- it may sit outside ``bounds``,
        which a start cell is allowed to do -- so writing 1 back would hand the
        next net a cell the search was never entitled to use.
        """
        canvas, bounds = self._maze()
        grid = _make_grid(canvas, bounds, _canvas_span(canvas, bounds), {})
        before = bytes(grid.occ)
        outside = (bounds[0] - 1, 0, 0)
        for cell in ((2, 2, 0), (6, 0, 0), outside):
            grid.block(cell)
        assert grid.occ != before
        for cell in ((2, 2, 0), (6, 0, 0), outside):
            grid.restore(cell)
        assert bytes(grid.occ) == before, (
            "restoring a ripped-up cell did not put back what was there, so a "
            "later net can route through ground it does not own"
        )

    def test_routing_flags_reuse_grid_owned_storage_and_refresh_exactly(self) -> None:
        canvas, bounds = self._maze()
        grid = _make_grid(canvas, bounds, _canvas_span(canvas, bounds), {})
        open_cell = (2, 2, 0)
        reserved_cell = (10, 2, 0)
        reserved_port = (10, 3, 0)

        flags = _routing_flags(grid)
        assert flags is grid.routing_flags
        assert flags[grid.index(open_cell)] == 1
        assert flags[grid.index(reserved_cell)] == 0

        grid.block(open_cell)
        refreshed = _routing_flags(grid, routing_ports={reserved_port})
        assert refreshed is flags
        assert flags[grid.index(open_cell)] == 0
        assert flags[grid.index(reserved_cell)] == 1

        grid.restore(open_cell)
        refreshed = _routing_flags(grid)
        assert refreshed is flags
        assert flags[grid.index(open_cell)] == 1
        assert flags[grid.index(reserved_cell)] == 0

    def test_the_grid_agrees_with_canvas_free(self) -> None:
        """The encoding, cell by cell, against the predicate it encodes.

        Reservations are excluded because they are applied per net -- which
        reservations a net may use depends on ``canvas.routing_ports`` -- and
        that is checked by the identical-path test above, which routes past one.
        """
        canvas, bounds = self._maze()
        grid = _make_grid(canvas, bounds, _canvas_span(canvas, bounds), {})
        lo_x, lo_y, hi_x, hi_y = bounds
        for x in range(lo_x, hi_x + 1):
            for y in range(lo_y, hi_y + 1):
                for lvl in range(LEVELS):
                    cell = (x, y, lvl)
                    if cell in canvas.reserved:
                        continue
                    assert bool(grid.occ[grid.index(cell)]) is canvas.free(cell), cell

    def test_history_flattens_and_re_flattens(self) -> None:
        """``history` grows once per rip-up round and the search reads it flat,
        so a round that forgets to re-flatten is a round negotiating against
        last round's prices."""
        canvas, bounds = self._maze()
        grid = _make_grid(canvas, bounds, _canvas_span(canvas, bounds), {})
        assert grid.hist is None, "an empty history should cost no array at all"
        grid.refresh_history({(2, 2, 0): 7.0})
        assert grid.hist is not None
        assert grid.hist[grid.index((2, 2, 0))] == 7.0
        assert grid.hist[grid.index((2, 3, 0))] == 0.0
        grid.refresh_history({})
        assert grid.hist is None


class TestAltitudeProfile:
    """The level-index -> world-altitude boundary.

    Handing a routing level index straight to the encoder is what shipped belts
    the game drew red, so the conversion has its own tests rather than being
    covered incidentally by a layout assertion.
    """

    def test_flat_path_stays_on_the_ground(self) -> None:
        path = [(0, 0, 0), (1, 0, 0), (2, 0, 0)]
        assert freeform._altitude_profile(path, ramped=True) == [F(0), F(0), F(0)]

    def test_a_crossing_reads_exactly_as_the_corpus_does(self) -> None:
        """``0, 1/2, 1, ..., 1, 1/2, 0`` -- the shape every real elevated run has."""
        path = [(0, 0, 0), (1, 0, 0), (2, 0, 1), (3, 0, 1), (4, 0, 1), (5, 0, 0)]
        assert freeform._altitude_profile(path, ramped=True) == [
            F(0), F(1, 2), F(1), F(1), F(1, 2), F(0)
        ]

    def test_the_ramp_tile_is_one_the_router_already_reserved(self) -> None:
        """The profile adds no cells: it renames the altitude of existing ones."""
        path = [(0, 0, 0), (1, 0, 0), (2, 0, 1)]
        prof = freeform._altitude_profile(path, ramped=True)
        assert prof is not None and len(prof) == len(path)

    def test_every_step_is_a_legal_transition(self) -> None:
        path = [(0, 0, 0), (1, 0, 0), (2, 0, 1), (3, 0, 1), (4, 0, 0), (5, 0, 0)]
        prof = freeform._altitude_profile(path, ramped=True)
        assert prof is not None
        for i in range(len(path) - 1):
            dz = prof[i + 1] - prof[i]
            dxy = abs(path[i + 1][0] - path[i][0]) + abs(path[i + 1][1] - path[i][1])
            assert (
                dz == 0
                or (abs(dz) == catalog.BELT_CLIMB_PER_TILE and dxy == 1)
                or (abs(dz) == catalog.VERTICAL_STEP and dxy == 0)
            ), f"step {i}: dz={dz} dxy={dxy}"

    def test_back_to_back_ramps_are_refused_rather_than_emitted(self) -> None:
        """Two level changes with no flat cell between them cannot be ramped.

        Levels `0, 1, 2` over three cells would read `1/2, 3/2, 2`, and
        `1/2 -> 3/2` is a whole tile of height across one tile of run -- the
        exact step this module exists to stop emitting.  The cells are already
        committed to their levels, so no altitude assignment rescues it; the
        path goes back to the router as unrouted.

        Caught in the wild as `geom.altitude_step` on `magnetic-ring`, 5 times
        over 12 layouts, once `LEVELS` rose to 3 and made consecutive ramps
        reachable.
        """
        assert (
            freeform._altitude_profile(
                [(0, 0, 0), (1, 0, 1), (2, 0, 2)], ramped=True
            )
            is None
        )

    def test_commit_records_a_path_with_no_legal_altitude_profile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(freeform, "_altitude_profile", lambda *_args, **_kwargs: None)
        canvas = _Canvas(ramped=True)
        source = _Port(0, 0, 0, 0, 0)
        destination = _Port(0, 2, 0, 2, 2)
        net = _Net(source, destination, "iron")

        assert _commit_paths(
            canvas, [net], {0: ((1, 0, 0),)}, 2001, 35
        ) == (0,)


    def test_ramps_separated_by_a_flat_cell_are_fine(self) -> None:
        path = [(0, 0, 0), (1, 0, 0), (2, 0, 1), (3, 0, 1), (4, 0, 2)]
        prof = freeform._altitude_profile(path, ramped=True)
        assert prof == [F(0), F(1, 2), F(1), F(3, 2), F(2)]

    def test_a_wider_jump_than_the_ramp_table_offers_is_refused(self) -> None:
        with pytest.raises(AssertionError, match="jumps 2 levels"):
            freeform._altitude_profile([(0, 0, 0), (1, 0, 2)], ramped=True)


class TestTheSlopeLimitIsConditional:
    """The game's slope test is gated on the save, so our emission is too.

        if (!history.beltVerticalConstruction && num25 > 0.8f)
            buildPreview2.condition = EBuildCondition.TooSteep;

    WITH the tech there is no slope limit and a belt may gain a whole level in
    one tile; WITHOUT it every step must stay inside 3/4 world slope, which
    means a ramp.  Both paths are pinned, because the whole point is that the
    behaviour is conditional -- a single test would let the other path rot.

    Treating the limit as unconditional cost 19 of 72 audit cells against
    master's 2.
    """

    LEVELS_PATH = [(0, 0, 0), (1, 0, 0), (2, 0, 1), (3, 0, 1), (4, 0, 0)]

    def test_without_the_tech_we_ramp(self) -> None:
        prof = freeform._altitude_profile(self.LEVELS_PATH, ramped=True)
        assert prof == [F(0), F(1, 2), F(1), F(1, 2), F(0)]

    def test_with_the_tech_we_emit_the_dense_form(self) -> None:
        prof = freeform._altitude_profile(self.LEVELS_PATH, ramped=False)
        assert prof == [F(0), F(0), F(1), F(1), F(0)]

    def test_without_the_tech_no_step_exceeds_the_slope_limit(self) -> None:
        """The ramped profile is legal on a save with NO technologies."""
        prof = freeform._altitude_profile(self.LEVELS_PATH, ramped=True)
        assert prof is not None
        for i in range(len(prof) - 1):
            a, b = self.LEVELS_PATH[i], self.LEVELS_PATH[i + 1]
            dxy = abs(b[0] - a[0]) + abs(b[1] - a[1])
            world = abs(prof[i + 1] - prof[i]) / catalog.BELT_Z_PER_WORLD_UNIT
            assert dxy > 0, "a ramp has to travel"
            assert world / dxy <= catalog.MAX_BELT_SLOPE

    def test_with_the_tech_the_dense_form_would_break_that_limit(self) -> None:
        """Which is exactly why it is gated rather than always used."""
        prof = freeform._altitude_profile(self.LEVELS_PATH, ramped=False)
        assert prof is not None
        worst = max(
            abs(prof[i + 1] - prof[i]) / catalog.BELT_Z_PER_WORLD_UNIT
            for i in range(len(prof) - 1)
        )
        assert worst > catalog.MAX_BELT_SLOPE

    def test_the_link_rule_follows_the_same_gate(self) -> None:
        one_level_across_one_tile = (0, 0, F(0), 1, 0, F(1))
        assert not freeform._legal_link(*one_level_across_one_tile, ramped=True)
        assert freeform._legal_link(*one_level_across_one_tile, ramped=False)

    def test_the_default_save_has_the_tech_so_is_not_ramped(self) -> None:
        """An absent technology set means every technology researched."""
        assert (
            freeform.FreeformLayout(band_policy=BandPolicy("portable")).ramped
            is False
        )
        assert (
            freeform.FreeformLayout(
                band_policy=BandPolicy("portable"),
                belt_vertical_construction=False,
            ).ramped
            is True
        )


class TestAPortKnowsItsOwnAltitude:
    """A port's access cell is in the port's OWN plane, not always at z = 0.

    A Spray Coater's proliferator drop belt sits one altitude LEVEL up -- its
    addon area is at ``(0, -1.25, 1)``.  ``_Port`` carried no ``z``, so both
    ``_reserve_port_access`` and the router's start/goal construction looked for
    a free cell beside every port at level 0.  For a drop that is the plane
    BELOW it, which is solid lane belt.

    The drop therefore reported no free neighbour, no access cell could be
    held, and A* was handed an EMPTY START SET -- a search that expands zero
    nodes, registers no congestion, and so cannot be priced by any amount of
    rip-up or negotiation.  It was measured as 422 of 600 route failures and
    read as a routing problem for a long time; it was never one.
    """


    def test_at_tile_carries_the_level(self) -> None:
        """Moving a port along its lane must not drop it to the ground."""
        port = _Port(7, 3, 4, 3, 5, (7, 8, 9), 1, 1)
        assert port.z == 1
        assert port.at_tile(2).z == 1, "at_tile lost the port's altitude"



class TestTheRoutingGridAgreesWithTheCanvas:
    """A* searches ``_make_grid``'s flat array, and it must refuse what ``free`` does.

    ``_Canvas.free`` refuses a cell in a belt addon's ``belt_ban`` band and a
    cell in a junction's ``guard``.  ``_make_grid`` flattened ``blocked``,
    ``solid``, ``keep_out`` and ``reserved`` and nothing else, so the search saw
    both as open ground: it returned paths straight through a Spray Coater's
    1.8975 band, ``_commit_paths`` asked ``free`` about each cell it was about
    to build on, found one refused, and dropped the WHOLE net into ``unlinked``.
    The sweep reads that as "this pack could not be wired" and discards it, so
    the refusal blamed the packer -- and nothing in the search had learned
    anything, so the next round produced the same path.

    Measured on ``plastic/max-proliferation``: every routing pass reported
    ``5 paths, 1 unlinked``, always the same net, always refused at ``(6, 8)``
    level 1 -- the tile a coater rides.
    """

    @staticmethod
    def _grid_and_canvas() -> tuple[_Grid, _Canvas]:
        canvas = _Canvas()
        canvas.limit = (0, 0, 6, 4)
        canvas.belt_ban[3, 2] = {1}
        canvas.guard.add((5, 1, 1))
        canvas.keep_out.add((1, 4))
        box = (0, 0, 6, 4)
        span = _canvas_span(canvas, box)
        return _make_grid(canvas, box, span, {}), canvas

    def test_every_cell_free_refuses_is_impassable_in_the_grid(self) -> None:
        grid, canvas = self._grid_and_canvas()
        disagree = [
            (x, y, lvl)
            for x in range(7)
            for y in range(5)
            for lvl in range(LEVELS)
            if canvas.free((x, y, lvl)) != bool(grid.occ[grid.index((x, y, lvl))])
        ]
        assert not disagree, (
            "the router searches a grid that disagrees with `_Canvas.free` at "
            f"{disagree}; every such cell is a path A* will return and "
            "`_commit_paths` will then throw the whole net away for"
        )

    def test_the_ban_and_the_guard_are_the_cells_it_used_to_miss(self) -> None:
        """Named explicitly, so the test above cannot pass by testing nothing."""
        grid, _ = self._grid_and_canvas()
        assert grid.occ[grid.index((3, 2, 1))] == 0, "coater band is passable"
        assert grid.occ[grid.index((5, 1, 1))] == 0, "junction guard is passable"
        # And a BAND, not a floor: the levels either side of the ban stay open,
        # because a belt beside a coater is legal and the corpus is full of them.
        assert grid.occ[grid.index((3, 2, 0))] == 1
        assert grid.occ[grid.index((3, 2, 2))] == 1




class TestAJunctionIsNotBuiltBesideAForeignBelt:
    """`game.belt_collide`, at the one shape our own output kept hitting it.

    A Splitter is belt-integrated -- it shares the tile of the belts it joins
    and occupies nothing -- but its build collider is a 2.38-unit cross standing
    2.30 units tall, and the game's belt probe catches that a tile out and a
    level up (`colliders.belt_keepout_offsets`).  A belt on the junction's own
    run is excused; a stranger there is `EBuildCondition.Collide` at paste.
    """

    def _scene(
        self,
        *,
        stranger: bool,
        stranger_level: int = 0,
    ) -> tuple[_Canvas, list[_Net], dict[int, list[tuple[int, int, int]]]]:
        canvas = _Canvas()
        upstream = canvas.add(_belt(0, -1, item="x"))
        lane = canvas.add(_belt(0, 0, item="x"))
        onward = canvas.add(_belt(0, 1, item="x"))
        canvas.buildings[upstream] = _relink(
            canvas.buildings[upstream], output_obj=lane
        )
        canvas.buildings[lane] = _relink(canvas.buildings[lane], output_obj=onward)
        if stranger:
            # One tile east of the tap, carrying something else and linked to
            # nothing the tap can reach.  This is the cell the game refuses.
            canvas.add(
                replace(_belt(1, 0, item="y"), z=F(stranger_level))
            )
        dst = canvas.add(_belt(-2, 0, item="x"))
        net = _Net(
            src=_Port(lane, 0, 0, 0, 0),
            dst=_Port(dst, -2, 0, -2, 0),
            item="x",
        )
        return canvas, [net], {0: [(-1, 0, 0)]}

    def _splitters(self, canvas: _Canvas) -> list[int]:
        return [
            i
            for i, b in enumerate(canvas.buildings)
            if b.item_id == catalog.SPLITTER_ID
        ]

    def test_the_site_is_refused_when_a_stranger_holds_a_keep_out_cell(self) -> None:
        canvas, nets, paths = self._scene(stranger=True)
        unlinked = _commit_paths(canvas, nets, paths, 2001, 35)
        assert not self._splitters(canvas), (
            "a junction was built one tile from a belt that is not on its run; "
            "the game refuses that paste with EBuildCondition.Collide"
        )
        assert unlinked == (0,), (
            "the tap was refused, so net 0 must be named as unlinked"
        )

    def test_the_site_is_refused_when_an_elevated_stranger_grazes_the_collider(
        self,
    ) -> None:
        canvas, nets, paths = self._scene(stranger=True, stranger_level=1)

        unlinked = _commit_paths(canvas, nets, paths, 2001, 35)

        assert not self._splitters(canvas)
        assert unlinked == (0,)

    def test_the_same_site_is_taken_when_nothing_foreign_is_beside_it(self) -> None:
        """The control, without which the test above passes for free.

        Same scene minus the stranger.  The lane's own onward belt is still in
        the keep-out and must NOT count: it is one hop from the junction, which
        is exactly what `colliders.belt_chain_excuses` lets off.
        """
        canvas, nets, paths = self._scene(stranger=False)
        unlinked = _commit_paths(canvas, nets, paths, 2001, 35)
        assert len(self._splitters(canvas)) == 1, (
            "the junction was refused with nothing foreign beside it, so the "
            "predicate is refusing sites the game builds"
        )
        assert unlinked == ()

    def test_the_junction_holds_its_collider_against_later_passes(self) -> None:
        """A splitter reports no occupied tile, so nothing after routing knows.

        External input runs, coater spurs and the power lattice all ask
        `canvas.free`, and until the guard existed they could lay a belt into
        the cross's room after the router had gone.
        """
        canvas, nets, paths = self._scene(stranger=False)
        _commit_paths(canvas, nets, paths, 2001, 35)
        for cell in junction.keepout_cells(0, 0, 0):
            assert not canvas.free(cell), f"{cell} was left open beside a junction"
        assert canvas.free((1, 1, 0)), "the diagonal clears and must stay routable"
        assert canvas.free((2, 0, 0)), "two tiles out clears and must stay routable"
        assert canvas.free((0, 0, 2)), "two levels up clears and must stay routable"


class TestPreparedJunctionLegalityIsThreeDimensional:
    @staticmethod
    def _building(item: str, x: int, y: int) -> PlacedBuilding:
        item_id = catalog.item_id(item)
        info = catalog.building(item_id)
        return PlacedBuilding(
            item_id=item_id,
            model_index=info.model_index,
            x=x,
            y=y,
            width=info.width,
            height=info.height,
        )

    @pytest.mark.parametrize(
        ("item", "machine_x", "machine_y", "splitter_x", "splitter_y", "level"),
        [
            ("assembling-machine-2", 35, 8, 38, 11, 1),
            ("assembling-machine-3", 54, 11, 53, 10, 2),
            ("arc-smelter", 22, 34, 25, 34, 1),
            ("matrix-lab", 37, 82, 36, 82, 1),
        ],
    )
    def test_static_machine_collisions_are_banned_at_the_splitter_level(
        self,
        item: str,
        machine_x: int,
        machine_y: int,
        splitter_x: int,
        splitter_y: int,
        level: int,
    ) -> None:
        machine = self._building(item, machine_x, machine_y)
        ban = freeform._prepared_junction_ban((machine,), ())

        assert (splitter_x, splitter_y, level) in ban
        assert not freeform._junction_site_is_clear(
            (machine,), splitter_x, splitter_y, level
        )

    def test_a_reserved_tesla_tower_bans_an_elevated_neighbour(self) -> None:
        site = (30, 26)
        ban = freeform._prepared_junction_ban((), (site,))

        assert (29, 26, 2) in ban


class TestProjectedCoaterSplitterBanIsPreparedBeforeRouting:
    @staticmethod
    def _projection() -> planet.Projection:
        band = next(band for band in planet.bands() if band.area_segments == 160)
        return planet.Projection(
            band=band,
            anchor_row=-130,
            segment=colliders.PLANET_SEGMENT,
            radius=colliders.PLANET_RADIUS,
        )

    @staticmethod
    def _coater() -> PlacedBuilding:
        info = catalog.building(catalog.SPRAY_COATER_ID)
        return PlacedBuilding(
            item_id=catalog.SPRAY_COATER_ID,
            model_index=info.model_index,
            x=26,
            y=15,
            yaw=90.0,
        )

    def _ban(self) -> frozenset[Cell]:
        frames = freeform._junction_projection_frames(
            (0, 0, 42, 34),
            (0, 0, 42, 34),
            BandPolicy("portable"),
        )
        return freeform._prepared_junction_ban(
            (self._coater(),),
            (),
            projection_frames=frames,
            junction_bounds=(0, 0, 42, 34),
        )

    def test_prepared_junction_ban_adds_exact_projected_coater_splitter_keepout(
        self,
    ) -> None:
        ban = self._ban()

        assert (25, 17, 1) in ban
        assert (25, 18, 1) not in ban

    def test_prepared_junction_ban_matches_materialized_rotated_frame(
        self,
    ) -> None:
        coater = replace(self._coater(), x=5, y=5, yaw=0.0)
        frames = freeform._junction_projection_frames(
            (-8, -8, 8, 8),
            (-8, -8, 8, 8),
            BandPolicy("100"),
        )
        rotated = next(
            frame
            for frame in frames
            if frame.candidate.frame.rotated
            and frame.candidate.frame.width == 17
            and frame.candidate.frame.height == 17
            and frame.candidate.south_padding == 0
        )
        projection = next(
            projection
            for projection in rotated.projections
            if projection.band.area_segments == 100
            and projection.anchor_row == 164
        )
        materialized_coater = finalize.materialize_frame_building(
            coater,
            bounds=rotated.bounds,
            candidate=rotated.candidate,
        )
        materialized_splitter = finalize.materialize_frame_building(
            junction.make_splitter(7, 3, F(1)),
            bounds=rotated.bounds,
            candidate=rotated.candidate,
        )
        failure = finalize.projected_coater_splitter_failure(
            (0, freeform._collision_pose(materialized_coater)),
            (1, freeform._collision_pose(materialized_splitter)),
            projection,
        )
        assert failure is not None
        assert failure.check == "game.addon_splitter_clearance"
        assert failure.band == 100
        flat_only = freeform._prepared_junction_ban((coater,), ())
        ban = freeform._prepared_junction_ban(
            (coater,),
            (),
            projection_frames=frames,
            junction_bounds=(-8, -8, 8, 8),
        )

        assert (7, 3, 1) not in flat_only
        assert (7, 3, 1) in ban

    def test_preparation_skips_junction_geometry_when_no_net_can_branch(
        self,
    ) -> None:
        spec = proliferated_spec()
        strips = plan_strips(spec)
        pack = _greedy_pack(strips, _height_seed(strips))

        prepared = _prepare_routing_problem(
            spec,
            strips,
            pack,
            power=False,
            policy=BandPolicy("portable"),
        )

        assert all(
            not net.src_group
            and not net.dst_group
            and (
                net.src is None
                or prepared.building_templates[net.src.belt_index].output_obj
                is None
            )
            for net in prepared.nets
        )
        assert prepared.junction_ban == frozenset()

    def test_source_siblings_require_junction_geometry(self) -> None:
        spec = proliferated_spec()
        strips = plan_strips(spec)
        prepared = _prepare_routing_problem(
            spec,
            strips,
            _greedy_pack(strips, _height_seed(strips)),
            power=False,
            policy=BandPolicy("portable"),
        )
        source = next(net for net in prepared.nets if net.src is not None)
        source_with_sibling = replace(
            source,
            src_group=(source.net_id,),
        )

        assert freeform._junction_geometry_required(
            (source_with_sibling,),
            prepared.building_templates,
        )

    def test_an_already_linked_source_requires_junction_geometry(self) -> None:
        spec = proliferated_spec()
        strips = plan_strips(spec)
        prepared = _prepare_routing_problem(
            spec,
            strips,
            _greedy_pack(strips, _height_seed(strips)),
            power=False,
            policy=BandPolicy("portable"),
        )
        source = next(net for net in prepared.nets if net.src is not None)
        assert source.src is not None
        buildings = list(prepared.building_templates)
        buildings[source.src.belt_index] = replace(
            buildings[source.src.belt_index],
            output_obj=source.dst.belt_index,
        )

        assert freeform._junction_geometry_required(
            (source,),
            buildings,
        )

    def test_preparation_skips_junction_geometry_for_destination_only_siblings(
        self,
    ) -> None:
        base = proliferated_spec()
        producer = base.groups[0].model_copy(update={"count": 8})
        second_consumer = group(
            "circuit-board",
            "assembling-machine-2",
            4,
            {"iron-ingot": F(1)},
            {"circuit-board": F(1)},
            mode=ProliferatorMode.PRODUCTS,
        )
        spec = base.model_copy(
            update={
                "groups": (producer, base.groups[1], second_consumer),
                "external_inputs": {**base.external_inputs, "iron-ore": F(8)},
                "outputs": {**base.outputs, "circuit-board": F(4)},
                "belt_required_edges": base.belt_required_edges
                | {("iron-ingot", "circuit-board")},
            }
        )
        strips = plan_strips(spec)
        prepared = _prepare_routing_problem(
            spec,
            strips,
            _greedy_pack(strips, _height_seed(strips)),
            power=False,
            policy=BandPolicy("portable"),
        )

        assert any(net.dst_group for net in prepared.nets)
        assert all(
            not net.src_group
            and (
                net.src is None
                or prepared.building_templates[net.src.belt_index].output_obj
                is None
            )
            for net in prepared.nets
        )
        assert prepared.junction_ban == frozenset()

    def test_merge_frontier_consumes_prepared_junction_ban(self) -> None:
        ban = self._ban()

        def frontier(y: int) -> set[Cell]:
            canvas = _Canvas(
                junction_ban=set(ban),
                junction_geometry_prepared=True,
            )
            tap = (25, y, 2)
            canvas.blocked[tap] = _TENTATIVE
            return freeform._merge_frontier(
                canvas,
                {5: (tap,)},
                (5,),
                canvas.junction_is_clear,
            )

        assert frontier(17) == set()
        assert frontier(18)

    def test_tap_source_consumes_prepared_junction_ban(self) -> None:
        ban = self._ban()

        def tap(y: int) -> tuple[bool, int]:
            canvas = _Canvas(
                junction_ban=set(ban),
                junction_geometry_prepared=True,
            )
            predecessor = canvas.add(
                replace(_belt(24, y, item="x"), z=F(2))
            )
            source = canvas.add(replace(_belt(25, y, item="x"), z=F(2)))
            onward = canvas.add(replace(_belt(26, y, item="x"), z=F(2)))
            branch = canvas.add(replace(_belt(25, y - 1, item="x"), z=F(2)))
            canvas.buildings[predecessor] = _relink(
                canvas.buildings[predecessor],
                output_obj=source,
            )
            canvas.buildings[source] = _relink(
                canvas.buildings[source],
                output_obj=onward,
            )
            attached = freeform._tap_source(
                canvas,
                source,
                branch,
                2001,
                35,
                excused={
                    (24, y, 2),
                    (25, y, 2),
                    (26, y, 2),
                    (25, y - 1, 2),
                },
            )
            splitters = sum(
                building.item_id == catalog.SPLITTER_ID
                for building in canvas.buildings
            )
            return attached, splitters

        assert tap(17) == (False, 0)
        assert tap(18) == (True, 2)



class TestSourceTapMaterializesSupportedSplitterStacks:
    @staticmethod
    def _scene(
        level: int,
        *,
        branch_level: int | None = None,
    ) -> tuple[_Canvas, int, int]:
        canvas = _Canvas()
        predecessor = canvas.add(replace(_belt(-1, 0, item="gear"), z=F(level)))
        source = canvas.add(replace(_belt(0, 0, item="gear"), z=F(level)))
        onward = canvas.add(replace(_belt(1, 0, item="gear"), z=F(level)))
        branch = canvas.add(
            replace(
                _belt(0, -1, item="gear"),
                z=F(level if branch_level is None else branch_level),
            )
        )
        canvas.buildings[predecessor] = _relink(
            canvas.buildings[predecessor],
            output_obj=source,
        )
        canvas.buildings[source] = _relink(
            canvas.buildings[source],
            output_obj=onward,
        )
        return canvas, source, branch

    def test_level_one_tap_uses_model_40_with_a_lower_branch_plane(self) -> None:
        canvas, source, branch = self._scene(1, branch_level=0)

        attached = freeform._tap_source(
            canvas,
            source,
            branch,
            2001,
            35,
            excused={(-1, 0, 1), (0, 0, 1), (1, 0, 1), (0, -1, 0)},
        )

        assert attached
        splitters = [
            (index, building)
            for index, building in enumerate(canvas.buildings)
            if building.item_id == catalog.SPLITTER_ID
        ]
        assert len(splitters) == 1
        splitter_index, splitter = splitters[0]
        assert (splitter.model_index, splitter.z, splitter.yaw) == (40, F(0), 90.0)
        attachments = [
            building
            for building in canvas.buildings
            if building.output_obj == splitter_index
            or building.input_obj == splitter_index
        ]
        assert sorted(building.z for building in attachments) == [0, 1, 1]
        wired = slots.assign_belt_slots(canvas.buildings)
        assert not splitter_ports.placement_issues(wired)

    def test_level_one_model_40_carry_is_one_valid_occupancy(self) -> None:
        canvas, source, branch = self._scene(1, branch_level=0)

        assert freeform._tap_source(
            canvas,
            source,
            branch,
            2001,
            35,
            excused={(-1, 0, 1), (0, 0, 1), (1, 0, 1), (0, -1, 0)},
        )

        wired = slots.assign_belt_slots(canvas.buildings)
        report = validate.validate(
            Placement(tuple(wired)),
            only=["geom.belt_single_occupancy"],
            expect_power=False,
        )
        assert not report.errors, "\n".join(finding.message for finding in report.errors)

    def test_level_one_model_40_uses_both_lower_branch_ports(self) -> None:
        canvas, source, first_branch = self._scene(1, branch_level=0)

        assert freeform._tap_source(
            canvas,
            source,
            first_branch,
            2001,
            35,
            excused={(-1, 0, 1), (0, 0, 1), (1, 0, 1), (0, -1, 0)},
        )
        second_branch = canvas.add(replace(_belt(0, 1, item="gear"), z=F(0)))
        assert freeform._tap_source(
            canvas,
            source,
            second_branch,
            2001,
            35,
        )

        wired = slots.assign_belt_slots(canvas.buildings)
        assert not splitter_ports.placement_issues(wired)
        splitter_index = next(
            index
            for index, building in enumerate(wired)
            if building.item_id == catalog.SPLITTER_ID
        )
        ports = {
            building.output_to_slot
            if building.output_obj == splitter_index
            else building.input_from_slot
            for building in wired
            if building.output_obj == splitter_index
            or building.input_obj == splitter_index
        }
        assert ports == {0, 1, 2, 3}

    def test_level_three_tap_uses_ground_support_and_model_40_top(self) -> None:
        canvas, source, branch = self._scene(3, branch_level=2)

        assert freeform._tap_source(
            canvas,
            source,
            branch,
            2001,
            35,
            excused={(-1, 0, 3), (0, 0, 3), (1, 0, 3), (0, -1, 2)},
        )

        splitters = [
            (index, building)
            for index, building in enumerate(canvas.buildings)
            if building.item_id == catalog.SPLITTER_ID
        ]
        assert [
            (
                building.model_index,
                building.z,
                building.input_obj,
                building.carries_item,
            )
            for _index, building in splitters
        ] == [
            (38, F(0), None, None),
            (40, F(2), splitters[0][0], "gear"),
        ]
        for _index, building in splitters:
            assert set(
                junction.keepout_cells(
                    0,
                    0,
                    int(building.z),
                    model_index=building.model_index,
                    yaw=building.yaw,
                )
            ) <= canvas.guard

    def test_level_two_tap_materializes_linked_ground_support_and_upper_splitter(
        self,
    ) -> None:
        canvas, source, branch = self._scene(2)

        attached = freeform._tap_source(
            canvas,
            source,
            branch,
            2001,
            35,
            excused={(-1, 0, 2), (0, 0, 2), (1, 0, 2), (0, -1, 2)},
        )

        assert attached
        splitters = [
            (index, building)
            for index, building in enumerate(canvas.buildings)
            if building.item_id == catalog.SPLITTER_ID
        ]
        assert [
            (building.z, building.input_obj, building.carries_item)
            for _index, building in splitters
        ] == [
            (0, None, None),
            (2, splitters[0][0], "gear"),
        ]
        assert canvas.buildings[source].output_obj == splitters[1][0]
        for level in (0, 2):
            assert set(junction.keepout_cells(0, 0, level)) <= canvas.guard

    def test_level_two_tap_rejects_a_ground_belt_inside_support_keepout(self) -> None:
        canvas, source, branch = self._scene(2)
        canvas.add(_belt(1, 0, item="foreign"))
        rejected_reason: list[str] = []

        attached = freeform._tap_source(
            canvas,
            source,
            branch,
            2001,
            35,
            excused={(-1, 0, 2), (0, 0, 2), (1, 0, 2), (0, -1, 2)},
            rejected_reason=rejected_reason,
        )

        assert not attached
        assert rejected_reason == ["belt-keepout"]
        assert all(
            building.item_id != catalog.SPLITTER_ID
            for building in canvas.buildings
        )

class TestSourceTapPreservesPhysicalSplitterPortIdentity:
    @pytest.mark.parametrize(
        ("dx", "dy"),
        ((0, -1), (1, 0), (0, 1), (-1, 0)),
        ids=("north", "east", "south", "west"),
    )
    def test_parallel_outputs_at_different_altitudes_do_not_share_one_port(
        self,
        dx: int,
        dy: int,
    ) -> None:
        """A Splitter port is direction/height identity, not a free counter cell.

        Both outputs leave in the same direction from one elevated Splitter
        port. One descends after leaving and one stays level, but that later
        altitude difference cannot make the co-located attachments use distinct
        ports. The four rotations guard the model/yaw transformation.
        """
        canvas = _Canvas()
        predecessor = canvas.add(
            replace(_belt(-dx, -dy, item="gear"), z=F(2))
        )
        source = canvas.add(replace(_belt(0, 0, item="gear"), z=F(2)))
        onward = canvas.add(replace(_belt(dx, dy, item="gear"), z=F(3)))
        branch = canvas.add(replace(_belt(dx, dy, item="gear"), z=F(2)))
        canvas.buildings[predecessor] = _relink(
            canvas.buildings[predecessor],
            output_obj=source,
        )
        canvas.buildings[source] = _relink(
            canvas.buildings[source],
            output_obj=onward,
        )
        rejected_reason: list[str] = []

        attached = freeform._tap_source(
            canvas,
            source,
            branch,
            2001,
            35,
            excused={
                (-dx, -dy, 2),
                (0, 0, 2),
                (dx, dy, 3),
                (dx, dy, 2),
            },
            rejected_reason=rejected_reason,
        )

        assert not attached
        assert rejected_reason == ["splitter-port"]
        assert canvas.buildings[source].output_obj == onward
        assert all(
            building.item_id != catalog.SPLITTER_ID
            for building in canvas.buildings
        )


    def test_source_frontier_withholds_a_path_occupied_physical_port(self) -> None:
        canvas = _Canvas(limit=(-2, -2, 2, 2))
        path = ((0, -1, 2), (0, 0, 2), (0, 1, 2))
        for cell in path:
            canvas.blocked[cell] = freeform._TENTATIVE

        frontier = freeform._merge_frontier(
            canvas,
            {5: path},
            (5,),
            lambda x, y, level: (x, y, level) == (0, 0, 2),
            belt_prefab=(2001, 35),
        )

        assert frontier == {(-1, 0, 2), (1, 0, 2)}

    def test_odd_level_source_frontier_offers_the_lower_orthogonal_plane(
        self,
    ) -> None:
        canvas = _Canvas(limit=(-2, -2, 2, 2))
        path = ((0, -1, 1), (0, 0, 1), (0, 1, 1))
        for cell in path:
            canvas.blocked[cell] = freeform._TENTATIVE

        frontier = freeform._merge_frontier(
            canvas,
            {5: path},
            (5,),
            lambda x, y, level: (x, y, level) == (0, 0, 1),
            belt_prefab=(2001, 35),
        )

        assert frontier == {(-1, 0, 0), (1, 0, 0)}

    def test_distinct_physical_ports_remain_accepted(self) -> None:
        canvas = _Canvas()
        predecessor = canvas.add(replace(_belt(0, 1, item="gear"), z=F(2)))
        source = canvas.add(replace(_belt(0, 0, item="gear"), z=F(2)))
        onward = canvas.add(replace(_belt(0, -1, item="gear"), z=F(2)))
        branch = canvas.add(replace(_belt(1, 0, item="gear"), z=F(2)))
        second_branch = canvas.add(
            replace(_belt(-1, 0, item="gear"), z=F(2))
        )
        canvas.buildings[predecessor] = _relink(
            canvas.buildings[predecessor],
            output_obj=source,
        )
        canvas.buildings[source] = _relink(
            canvas.buildings[source],
            output_obj=onward,
        )
        canvas.add(
            PlacedBuilding(
                item_id=2011,
                model_index=catalog.building(2011).model_index,
                x=0,
                y=0,
                z=F(2),
                output_obj=source,
            )
        )

        assert freeform._tap_source(
            canvas,
            source,
            branch,
            2001,
            35,
            excused={
                (-1, 0, 2),
                (0, 1, 2),
                (0, 0, 2),
                (0, -1, 2),
                (1, 0, 2),
            },
        )
        assert freeform._tap_source(
            canvas,
            source,
            second_branch,
            2001,
            35,
        )

        wired = slots.assign_belt_slots(canvas.buildings)
        splitter = max(
            (
                (index, building)
                for index, building in enumerate(wired)
                if building.item_id == catalog.SPLITTER_ID
            ),
            key=lambda pair: pair[1].z,
        )[0]
        ports = [
            building.output_to_slot
            if building.output_obj == splitter
            else building.input_from_slot
            for building in wired
            if building.output_obj == splitter or building.input_obj == splitter
        ]
        assert len(ports) == 4
        assert len(set(ports)) == len(ports)


class TestTheMergeFrontierWithdrawsSitesAJunctionCannotHold:
    """The routing-time half, which is the half that had to exist.

    The backlog's failed attempt put this test inside ``_commit_paths``, where
    it refused 1147 of 1619 sites and the convictions survived anyway: a tap is
    taken while the walk is half done, so the belt that lands beside it has not
    been staked yet.  Asked at the frontier instead, it costs one of the several
    cells a sibling's path offers, and the router picks another.
    """

    def _scene(self) -> tuple[_Canvas, dict[int, list[tuple[int, int, int]]]]:
        canvas = _Canvas()
        # A stranger one tile north of the path's first cell: in that cell's
        # keep-out, and on nobody's run.
        canvas.add(_belt(0, 1, item="y"))
        path = [(0, 0, 0), (1, 0, 0), (2, 0, 0)]
        for cell in path:
            canvas.blocked[cell] = _TENTATIVE
        return canvas, {5: path}

    def test_a_cell_whose_tap_is_dirty_is_not_offered(self) -> None:
        canvas, paths = self._scene()
        got = freeform._merge_frontier(
            canvas, paths, (5,), lambda x, y, level: True
        )
        assert (-1, 0, 0) not in got and (0, -1, 0) not in got, (
            "a merge was offered whose junction would stand beside a foreign "
            f"belt: {sorted(got)}"
        )
        assert (1, 1, 0) in got, (
            "the clean cells of the same path stopped being offered, so this "
            "withdraws more than the rule asks for"
        )

    def test_the_same_cells_come_back_when_the_stranger_is_gone(self) -> None:
        """Without this the test above passes for any predicate that says no."""
        canvas = _Canvas()
        path = [(0, 0, 0), (1, 0, 0), (2, 0, 0)]
        for cell in path:
            canvas.blocked[cell] = _TENTATIVE
        got = freeform._merge_frontier(
            canvas, {5: path}, (5,), lambda x, y, level: True
        )
        assert {(-1, 0, 0), (0, -1, 0), (0, 1, 0)} <= got, sorted(got)


class TestASprayedLaneEitherGetsACoaterOrRefuses:
    """``_place_coaters`` may not ``continue`` past a lane it cannot seat.

    It used to, four times over: no port for the item, a lane too short to offer
    a straight seat, no belt on the seat tile, a drop cell already taken.  Each
    left the pack one Spray Coater short of what ``spec.spray_lanes`` asked for,
    and nothing downstream could tell -- ``game.addon_supply`` and
    ``prolif.coaters_are_supplied`` both iterate the coaters that EXIST, so a
    coater never placed is invisible to both.  The blueprint pastes, the
    machines run, and every recipe on that lane quietly runs unproliferated.

    The two cases below are the ones a caller can construct directly, and both
    are silent on the code as it stood: ``_place_coaters`` returned a SHORTER
    list and raised nothing.  So the assertion is on the exception, and the
    ``lanes`` assertion beside it is what keeps the test from passing because
    the fixture stopped asking for a coater at all.
    """

    ITEM = "iron-ingot"

    def _fixture(
        self, tiles: int
    ) -> tuple[_Canvas, BuildSpec, list[Strip], list[dict[str, _Port]]]:
        spec = proliferated_spec()
        assert self.ITEM in spec.spray_lanes, "fixture stopped asking for a coater"
        strips = [s for s in plan_strips(spec) if self.ITEM in s.in_lanes]
        assert strips, "no strip carries the sprayed lane; nothing to seat"
        canvas = _Canvas()
        indices = [canvas.add(_belt(x, 0, item=self.ITEM)) for x in range(tiles)]
        port = _Port(
            indices[0],
            0,
            0,
            0,
            tiles - 1,
            tuple(indices),
            strips[0].machines,
            0,
            cargo_domain=strips[0].cargo_domain,
        )
        return canvas, spec, strips[:1], [{self.ITEM: port}]

    def _projected_risk_obstacle(
        self,
        canvas: _Canvas,
        strip: Strip,
        port: _Port,
    ) -> int:
        """Add a same-strip peer with a real projected-only collision relation."""
        cx, cy = freeform._coater_seats(
            canvas,
            port,
            west_channel=strip.west_channel,
        )[0]
        assembler_id = catalog.item_id("assembling-machine-2")
        assembler = catalog.building(assembler_id)
        peer = PlacedBuilding(
            assembler_id,
            assembler.model_index,
            cx + 2,
            cy + 1,
            width=assembler.width,
            height=assembler.height,
            owner_strip=0,
        )
        obstacle_index = canvas.add(peer, solid=True)
        coater = catalog.building(catalog.SPRAY_COATER_ID)
        candidate = PlacedBuilding(
            catalog.SPRAY_COATER_ID,
            coater.model_index,
            cx,
            cy,
            z=F(port.z),
            width=1,
            height=1,
            yaw=Facing.EAST.value,
            owner_strip=0,
        )
        relation = freeform._staged_static_clearance_key(peer, candidate)

        assert not freeform._coater_keepout_hits(canvas.buildings, candidate)
        assert freeform._staged_static_relation_projection_risk(
            relation,
            BandPolicy("portable"),
        )
        return obstacle_index

    def _broke2_fixture(
        self,
        splitter_y: int,
    ) -> tuple[
        _Canvas,
        BuildSpec,
        list[Strip],
        list[dict[str, _Port]],
        int,
    ]:
        _unused, spec, strips, _unused_ports = self._fixture(3)
        canvas = _Canvas()
        for x, y in ((0, 0), (42, 34)):
            index = canvas.add(_belt(x, y))
            canvas.buildings[index] = replace(
                canvas.buildings[index],
                input_obj=index,
                output_obj=index,
            )
        indices = [canvas.add(_belt(x, 15, item=self.ITEM)) for x in (25, 26, 27)]
        for index in indices:
            canvas.buildings[index] = replace(
                canvas.buildings[index],
                input_obj=index,
                output_obj=index,
            )
        splitter = catalog.building(catalog.SPLITTER_ID)
        splitter_index = canvas.add(
            PlacedBuilding(
                item_id=catalog.SPLITTER_ID,
                model_index=splitter.model_index,
                x=25,
                y=splitter_y,
                z=F(1),
                width=splitter.width,
                height=splitter.height,
            )
        )
        port = _Port(
            indices[0],
            25,
            15,
            0,
            27,
            tuple(indices),
            strips[0].machines,
            0,
            cargo_domain=strips[0].cargo_domain,
        )
        return canvas, spec, strips, [{self.ITEM: port}], splitter_index

    def test_coater_seat_rejects_projected_splitter_keepout_before_emission(
        self,
    ) -> None:
        canvas, spec, strips, ports, splitter_index = self._broke2_fixture(17)
        before = tuple(canvas.buildings)
        assert canvas.limit is None

        with pytest.raises(freeform._Unseatable) as caught:
            freeform._place_coaters(
                canvas,
                spec,
                strips,
                ports,
                2001,
                35,
                policy=BandPolicy("portable"),
            )

        failure = caught.value.failure
        assert tuple(canvas.buildings) == before
        assert failure == finalize.ProjectionFailure(
            check="game.addon_splitter_clearance",
            buildings=(len(before) + 1, splitter_index),
            detail=(
                "Splitter connection body enters the Spray Coater projected "
                "lateral keepout"
            ),
            band=160,
        )
        assert caught.value.failures == (failure,)
        assert (
            f"band 160 game.addon_splitter_clearance "
            f"({len(before) + 1}, {splitter_index})"
        ) in str(caught.value)
        assert canvas.limit is None

    def test_later_projected_coater_splitter_refusal_commits_no_earlier_coater(
        self,
    ) -> None:
        canvas, spec, strips, ports, splitter_index = self._broke2_fixture(17)
        first_indices = [
            canvas.add(_belt(x, 5, item=self.ITEM))
            for x in (10, 11, 12)
        ]
        first_port = _Port(
            first_indices[0],
            10,
            5,
            0,
            12,
            tuple(first_indices),
            strips[0].machines,
            0,
            cargo_domain=strips[0].cargo_domain,
        )
        before = tuple(canvas.buildings)

        with pytest.raises(freeform._Unseatable) as caught:
            freeform._place_coaters(
                canvas,
                spec,
                [strips[0], strips[0]],
                [{self.ITEM: first_port}, ports[0]],
                2001,
                35,
                policy=BandPolicy("portable"),
            )

        assert tuple(canvas.buildings) == before
        assert canvas.limit is None
        assert caught.value.failure is not None
        assert caught.value.failure.buildings == (
            len(before) + 3,
            splitter_index,
        )


    def test_coater_seat_allows_splitter_at_known_projected_separation(self) -> None:
        canvas, spec, strips, ports, _splitter_index = self._broke2_fixture(18)

        got = freeform._place_coaters(
            canvas,
            spec,
            strips,
            ports,
            2001,
            35,
            policy=BandPolicy("portable"),
        )

        assert len(got) == 1

    def test_build_passes_policy_to_coater_splitter_check_before_routing(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        policy = BandPolicy("portable")
        failure = finalize.ProjectionFailure(
            check="game.addon_splitter_clearance",
            buildings=(12, 7),
            detail=(
                "Splitter connection body enters the Spray Coater projected "
                "lateral keepout"
            ),
            band=160,
        )
        seen: list[BandPolicy] = []

        def refuse(
            _canvas: _Canvas,
            _spec: BuildSpec,
            _strips: list[Strip],
            _ports: list[dict[str, _Port]],
            _belt_id: int,
            _belt_model: int,
            *,
            policy: BandPolicy,
        ) -> list[CoaterSupplyPort]:
            seen.append(policy)
            raise freeform._Unseatable(
                "projected coater/Splitter refusal",
                failure=failure,
            )

        monkeypatch.setattr(freeform, "_place_coaters", refuse)
        monkeypatch.setattr(
            freeform,
            "_route_all",
            lambda *_args, **_kwargs: pytest.fail(
                "detailed routing started after projected coater refusal"
            ),
        )
        spec = proliferated_spec()
        strips = plan_strips(spec)
        pack = _greedy_pack(strips, _height_seed(strips))

        with pytest.raises(freeform._Unseatable) as caught:
            _build(
                spec,
                strips,
                pack,
                power=False,
                route=True,
                policy=policy,
            )

        assert seen == [policy]
        assert caught.value.failure is failure

    def test_sprayed_lane_reserves_the_full_coater_body_west(self) -> None:
        policy = BandPolicy("portable")
        _canvas, _spec, strips, _ports = self._fixture(4)
        strip = strips[0]
        w3 = replace(strip, west_channel=freeform._COATER_WEST_CHANNEL)
        risky = tuple(
            relation
            for relation in freeform._staged_static_clearance_keys(w3)
            if freeform._staged_static_preclearance_proved(relation, policy)
        )

        assert risky, "fixture lost the exact W3 relation that requires preclearance"
        assert strip.west_channel == freeform._COATER_WEST_CHANNEL + 1 == 4
        assert all(
            not freeform._staged_static_relation_projection_risk(relation, policy)
            for relation in freeform._staged_static_clearance_keys(strip)
        )

    def test_universally_safe_sprayed_relation_keeps_the_w3_body_reservation(
        self,
    ) -> None:
        policy = BandPolicy("portable")
        safe = next(
            strip
            for strip in plan_strips(band_160_all_products_spec(), band_policy=policy)
            if strip.cargo_domain is CargoDomain.REQUIRES_SPRAY
            and strip.west_channel == freeform._COATER_WEST_CHANNEL
            and freeform._staged_static_clearance_keys(strip)
        )
        relations = freeform._staged_static_clearance_keys(safe)

        assert relations
        assert all(
            not freeform._staged_static_relation_projection_risk(relation, policy)
            for relation in relations
        )


    def test_a_lane_too_short_to_seat_a_coater_is_refused(self) -> None:
        """One tile: ``_coater_seat`` has no tile with a lane tile either side."""
        canvas, spec, strips, ports = self._fixture(1)
        with pytest.raises(freeform._Unseatable, match="tile"):
            freeform._place_coaters(
                canvas,
                spec,
                strips,
                ports,
                2001,
                35,
                policy=BandPolicy("portable"),
            )

    def test_a_taken_drop_cell_is_refused(self) -> None:
        """A lane with one legal coater seat must refuse an occupied drop cell.

        With that cell occupied there is no supply, and the old code answered
        by placing no coater -- which reads as "this lane needs none".
        """
        canvas, spec, strips, ports = self._fixture(3)
        seats = freeform._coater_seats(
            canvas,
            ports[0][self.ITEM],
            west_channel=strips[0].west_channel,
        )
        assert len(seats) == 1, "the fixture must expose exactly one legal seat"
        seat = seats[0]
        drop = slots.addon_supply_cell(
            catalog.SPRAY_COATER_ID,
            x=seat[0],
            y=seat[1],
            z=F(0),
            yaw=Facing.EAST.value,
            area=1,
        )
        canvas.blocked[drop] = 999
        assert not canvas.free(drop), "the fixture failed to block the drop cell"
        with pytest.raises(freeform._Unseatable, match="proliferator drop"):
            freeform._place_coaters(
                canvas,
                spec,
                strips,
                ports,
                2001,
                35,
                policy=BandPolicy("portable"),
            )

    def test_reported_coater_assembler_pair_is_refused_before_emission(
        self,
    ) -> None:
        fixture = Path("tests/fixtures/ours/coater-assembler-collision.txt")
        blueprint = codec.decode(fixture.read_text(encoding="utf-8").strip())
        assert blueprint.hash_valid
        coater_record = blueprint.buildings[162]
        assembler_record = blueprint.buildings[134]
        assert (
            coater_record.index,
            coater_record.item_id,
            coater_record.x,
            coater_record.y,
            coater_record.yaw,
        ) == (162, catalog.SPRAY_COATER_ID, 13.0, 7.0, 90.0)
        assembler_id = catalog.item_id("assembling-machine-2")
        assert (
            assembler_record.index,
            assembler_record.item_id,
            assembler_record.x,
            assembler_record.y,
        ) == (134, assembler_id, 14.0, 9.0)

        _old_canvas, spec, strips, _old_ports = self._fixture(4)
        canvas = _Canvas()
        assembler_info = catalog.building(assembler_id)
        assembler = PlacedBuilding(
            item_id=assembler_id,
            model_index=assembler_record.model_index,
            x=round(assembler_record.x - (assembler_info.width - 1) / 2),
            y=round(assembler_record.y - (assembler_info.height - 1) / 2),
            width=assembler_info.width,
            height=assembler_info.height,
            yaw=assembler_record.yaw,
        )
        assembler_index = canvas.add(assembler, solid=True)
        indices = [
            canvas.add(_belt(x, 7, item=self.ITEM))
            for x in (12, 13, 14)
        ]
        port = _Port(
            indices[0],
            12,
            7,
            12,
            14,
            tuple(indices),
            strips[0].machines,
            0,
            cargo_domain=strips[0].cargo_domain,
        )
        proposed = PlacedBuilding(
            item_id=catalog.SPRAY_COATER_ID,
            model_index=coater_record.model_index,
            x=round(coater_record.x),
            y=round(coater_record.y),
            yaw=coater_record.yaw,
        )
        assert freeform._coater_keepout_hits(
            canvas.buildings,
            proposed,
        ) == (assembler_index,)

        with pytest.raises(freeform._Unseatable, match="keepout"):
            freeform._place_coaters(
                canvas,
                spec,
                strips,
                [{self.ITEM: port}],
                2001,
                35,
                policy=BandPolicy("portable"),
            )
    def test_coater_keepout_prepares_flat_candidates_in_one_pass(self) -> None:
        class CountedBuildings(Sequence[PlacedBuilding]):
            def __init__(self, buildings: tuple[PlacedBuilding, ...]) -> None:
                self.buildings = buildings
                self.iterations = 0

            def __len__(self) -> int:
                return len(self.buildings)

            def __getitem__(self, index: int) -> PlacedBuilding:
                return self.buildings[index]

            def __iter__(self) -> Iterator[PlacedBuilding]:
                self.iterations += 1
                return iter(self.buildings)

        coater = catalog.building(catalog.SPRAY_COATER_ID)
        buildings = CountedBuildings(
            (
                _belt(0, 0, item=self.ITEM),
                PlacedBuilding(
                    item_id=2303,
                    model_index=catalog.building(2303).model_index,
                    x=20,
                    y=20,
                    width=3,
                    height=3,
                ),
            )
        )
        candidate = PlacedBuilding(
            item_id=catalog.SPRAY_COATER_ID,
            model_index=coater.model_index,
            x=2,
            y=2,
            width=coater.width,
            height=coater.height,
        )

        freeform._coater_keepout_hits(buildings, candidate)

        assert buildings.iterations == 1


    def test_staged_static_alternate_seat_advances_in_order(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        canvas, spec, strips, ports = self._fixture(4)
        obstacle_index = self._projected_risk_obstacle(
            canvas,
            strips[0],
            ports[0][self.ITEM],
        )
        attempted: list[int] = []

        def projected_failure(
            indexed: Sequence[tuple[int, PlacedBuilding]],
            _frames: Sequence[freeform._JunctionProjectionFrame],
            *,
            candidate_index: int,
            cache: freeform._StagedStaticCache,
            cancelled: Callable[[], bool] | None = None,
        ) -> finalize.ProjectionFailure | None:
            candidate = next(
                building for index, building in indexed if index == candidate_index
            )
            attempted.append(candidate.x)
            if candidate.x != 1:
                return None
            return finalize.ProjectionFailure(
                "geom.collide",
                (obstacle_index, candidate_index),
                "build colliders intersect",
                160,
            )

        monkeypatch.setattr(
            freeform,
            "_coater_keepout_hits",
            lambda _buildings, _candidate: (),
        )
        monkeypatch.setattr(
            freeform,
            "_prospective_static_failure",
            projected_failure,
        )

        got = freeform._place_coaters(
            canvas,
            spec,
            strips,
            ports,
            2001,
            35,
            policy=BandPolicy("portable"),
        )

        assert attempted[:2] == [1, 2]
        assert len(got) == 1
        assert got[0].host_x == 2

    def test_staged_static_alternate_seat_never_passes_the_first_pickup(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        canvas, spec, strips, ports = self._fixture(6)
        assert strips[0].west_channel == freeform._COATER_WEST_CHANNEL + 1 == 4
        first_pickup_x = strips[0].west_channel
        obstacle_index = self._projected_risk_obstacle(
            canvas,
            strips[0],
            ports[0][self.ITEM],
        )
        attempted: list[int] = []

        def projected_failure(
            indexed: Sequence[tuple[int, PlacedBuilding]],
            _frames: Sequence[freeform._JunctionProjectionFrame],
            *,
            candidate_index: int,
            cache: freeform._StagedStaticCache,
            cancelled: Callable[[], bool] | None = None,
        ) -> finalize.ProjectionFailure | None:
            candidate = next(
                building for index, building in indexed if index == candidate_index
            )
            attempted.append(candidate.x)
            if candidate.x >= first_pickup_x:
                return None
            return finalize.ProjectionFailure(
                "geom.collide",
                (obstacle_index, candidate_index),
                "build colliders intersect",
                160,
            )

        monkeypatch.setattr(
            freeform,
            "_coater_keepout_hits",
            lambda _buildings, _candidate: (),
        )
        monkeypatch.setattr(
            freeform,
            "_prospective_static_failure",
            projected_failure,
        )

        with pytest.raises(freeform._Unseatable) as caught:
            freeform._place_coaters(
                canvas,
                spec,
                strips,
                ports,
                2001,
                35,
                policy=BandPolicy("portable"),
            )

        assert attempted == [1, 2, 3]
        assert caught.value.failure is not None
        assert caught.value.failure.check == "geom.collide"
        assert caught.value.clearance_requirement is not None
        assert (
            caught.value.clearance_requirement.required_west_channel
            == strips[0].west_channel + 1
        )
        assert caught.value.exact_retry_evidence is None

    def test_staged_static_mixed_same_strip_seat_failures_request_clearance(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        canvas, spec, strips, ports = self._fixture(4)
        obstacle_index = self._projected_risk_obstacle(
            canvas,
            strips[0],
            ports[0][self.ITEM],
        )
        projected: list[int] = []
        keepout: list[int] = []

        def keepout_hits(
            _buildings: Sequence[PlacedBuilding],
            candidate: PlacedBuilding,
        ) -> tuple[int, ...]:
            keepout.append(candidate.x)
            return (obstacle_index,) if candidate.x == 2 else ()

        def projected_failure(
            indexed: Sequence[tuple[int, PlacedBuilding]],
            _frames: Sequence[freeform._JunctionProjectionFrame],
            *,
            candidate_index: int,
            cache: freeform._StagedStaticCache,
            cancelled: Callable[[], bool] | None = None,
        ) -> finalize.ProjectionFailure | None:
            candidate = next(
                building for index, building in indexed if index == candidate_index
            )
            projected.append(candidate.x)
            return finalize.ProjectionFailure(
                "geom.collide",
                (obstacle_index, candidate_index),
                "build colliders intersect",
                160,
            )

        monkeypatch.setattr(freeform, "_coater_keepout_hits", keepout_hits)
        monkeypatch.setattr(
            freeform,
            "_prospective_static_failure",
            projected_failure,
        )

        with pytest.raises(freeform._Unseatable) as caught:
            freeform._place_coaters(
                canvas,
                spec,
                strips,
                ports,
                2001,
                35,
                policy=BandPolicy("portable"),
            )

        assert keepout == [1, 2]
        assert projected == [1]
        assert caught.value.failure is not None
        assert caught.value.failure.check == "geom.collide"
        assert caught.value.clearance_requirement is not None
        assert caught.value.exact_retry_evidence is None


    def test_the_same_fixture_unblocked_seats_one(self) -> None:
        """Without this the two above pass for a fixture that seats nothing."""
        canvas, spec, strips, ports = self._fixture(4)
        got = freeform._place_coaters(
            canvas,
            spec,
            strips,
            ports,
            2001,
            35,
            policy=BandPolicy("portable"),
        )
        assert len(got) == 1, f"expected one coater on the sprayed lane, got {got}"
        assert canvas.buildings[got[0].coater].owner_strip == 0
        assert canvas.buildings[got[0].supply_belt].owner_strip == 0

    def test_coater_candidates_do_not_recertify_boundary_cleanup(self) -> None:
        canvas, spec, strips, ports = self._fixture(4)
        initial_buildings = len(canvas.buildings)
        cache = freeform._StagedStaticCache()

        got = freeform._place_coaters(
            canvas,
            spec,
            strips,
            ports,
            2001,
            35,
            policy=BandPolicy("portable"),
            staged_static_cache=cache,
        )

        assert len(got) == 1
        assert cache.cleanup_operations.node_visits == 2 * initial_buildings, (
            "the initial graph construction and exact survivor proof each visit "
            "the lane once; static coater proposals must add no visits"
        )

    def test_items_sharing_one_lane_share_one_positional_coater(self) -> None:
        canvas, spec, strips, ports = self._fixture(4)
        other = "gear"
        spec = spec.model_copy(
            update={"spray_lanes": {self.ITEM: False, other: False}}
        )
        strips[0] = replace(
            strips[0],
            in_above=((self.ITEM, other),),
            in_below=(),
        )
        ports[0][other] = ports[0][self.ITEM]

        got = freeform._place_coaters(
            canvas,
            spec,
            strips,
            ports,
            2001,
            35,
            policy=BandPolicy("portable"),
        )

        assert len(got) == 1
        assert len(
            [
                building
                for building in canvas.buildings
                if building.item_id == catalog.SPRAY_COATER_ID
            ]
        ) == 1

    def test_a_sprayed_item_no_strip_carries_is_refused(self) -> None:
        """The loop never reaches such an item, so the clauses inside cannot fire."""
        canvas, spec, strips, ports = self._fixture(4)
        spec = spec.model_copy(
            update={"spray_lanes": {**spec.spray_lanes, "gear": False}}
        )
        with pytest.raises(freeform._Unseatable, match="gear"):
            freeform._place_coaters(
                canvas,
                spec,
                strips,
                ports,
                2001,
                35,
                policy=BandPolicy("portable"),
            )

# --- belt docked into a building PORT ---------------------------------------


def ray_receiver_spec() -> BuildSpec:
    """A Ray Receiver making critical photons, and something that eats them.

    The machine at the centre of every ``universe-matrix`` refusal.  Its prefab
    ships ZERO insert poses and two belt PORTS, so no sorter can attach to it on
    any face at any distance -- ``BuildTool_Inserter`` drops a cast target whose
    ``slotPoses`` is empty -- and the only join it has is a belt docked into a
    port.  It is also a pure SOURCE: it is fed nothing, and the lane it wants is
    its output.
    """
    return BuildSpec(
        groups=(
            group("critical-photon", "ray-receiver", 2, {}, {"critical-photon": F(1)}),
            group("graphene", "chemical-plant", 2, {"critical-photon": F(1)}, {"graphene": F(1)}),
        ),
        external_inputs={},
        outputs={"graphene": F(2)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="ray-receiver",
    )



def _port_docks(
    buildings: tuple[PlacedBuilding, ...] | list[PlacedBuilding],
) -> list[tuple[int, PlacedBuilding]]:
    return [
        (index, building)
        for index, building in enumerate(buildings)
        if catalog.is_belt(building.item_id)
        and building.input_obj is not None
        and buildings[building.input_obj].item_id == catalog.RAY_RECEIVER_ID
    ]


class TestPreparedBeltPortDocking:
    def test_preparation_emits_the_game_record_for_every_receiver(self) -> None:
        spec = ray_receiver_spec()
        strips = plan_strips(spec)
        assert _machines_without_poses(strips) == []
        pack = _greedy_pack(strips, _height_seed(strips))

        prepared = _prepare_routing_problem(
            spec,
            strips,
            pack,
            policy=BandPolicy("portable"),
            power=False
        )
        buildings = prepared.building_templates
        receivers = [
            building
            for building in buildings
            if building.item_id == catalog.RAY_RECEIVER_ID
        ]
        docks = _port_docks(buildings)

        assert len(receivers) == 2
        assert len(docks) == len(receivers)
        for _index, dock in docks:
            assert dock.input_obj is not None
            host = buildings[dock.input_obj]
            assert dock.input_to_slot == rules.BELT_PORT_DRAW_TO_SLOT
            assert 0 <= dock.input_from_slot < len(
                catalog.building(catalog.RAY_RECEIVER_ID).port_poses
            )
            assert slots.port_gap(
                host, (dock.x, dock.y), dock.input_from_slot
            ) <= rules.BELT_PORT_MAX_TILE_GAP
            assert dock.output_obj is not None
            assert host.input_obj is None and host.output_obj is None

        workspace = prepared.new_workspace()
        rebound = _port_docks(workspace.buildings)
        assert [
            (
                dock.input_obj,
                dock.input_from_slot,
                dock.input_to_slot,
                dock.output_obj,
            )
            for _index, dock in rebound
        ] == [
            (
                dock.input_obj,
                dock.input_from_slot,
                dock.input_to_slot,
                dock.output_obj,
            )
            for _index, dock in docks
        ]

    @pytest.mark.parametrize(
        ("yaw", "port"),
        [(0.0, 0), (180.0, 1)],
    )
    def test_docking_uses_the_port_facing_the_lane(
        self, yaw: float, port: int
    ) -> None:
        info = catalog.building(catalog.RAY_RECEIVER_ID)
        canvas = _Canvas()
        machine = canvas.add(
            PlacedBuilding(
                item_id=catalog.RAY_RECEIVER_ID,
                model_index=info.model_index,
                x=0,
                y=0,
                width=info.width,
                height=info.height,
                yaw=yaw,
            ),
            solid=True,
        )
        lane_y = 10
        lane = [
            canvas.add(
                PlacedBuilding(
                    item_id=2002,
                    model_index=36,
                    x=x,
                    y=lane_y,
                    width=1,
                    height=1,
                )
            )
            for x in range(info.width)
        ]

        assert (
            freeform._dock_lane(
                canvas,
                [machine],
                lane,
                lane_y,
                "critical-photon",
                2002,
                36,
                {},
            )
            == 1
        )
        docks = [
            building
            for building in canvas.buildings
            if catalog.is_belt(building.item_id)
            and building.input_obj == machine
        ]
        assert [dock.input_from_slot for dock in docks] == [port]



def band_120_control_spec() -> BuildSpec:
    """A routing-light fixed-band control whose old schedule drops height 26."""
    count = 24
    return BuildSpec(
        groups=(
            group(
                "iron-ingot",
                "arc-smelter",
                count,
                {"iron-ore": F(1)},
                {"iron-ingot": F(1)},
            ),
        ),
        external_inputs={"iron-ore": F(count)},
        outputs={"iron-ingot": F(count)},
        belt_item_id="conveyor-belt-2",
        belt_items_per_second=F(12),
        label="band-120-control",
    )


def test_freeform_band_policy_height_reserves_one_band_120_boundary_slot() -> None:
    strips = plan_strips(band_120_control_spec(), strip_len=6)
    portable = freeform._band_policy_candidate_heights(
        strips,
        BandPolicy("portable"),
    )
    fixed = freeform._band_policy_candidate_heights(
        strips,
        BandPolicy("120"),
    )

    assert portable == (26, 33, 12, 16, 21)
    assert fixed == (19, 33, 12, 16, 21)
    assert len(fixed) == len(portable)


@pytest.mark.parametrize(
    ("selection", "height"),
    (("portable", 26), ("120", 19)),
)
def test_freeform_band_120_dropped_height_has_actual_clean_layout_control(
    selection: str,
    height: int,
) -> None:
    spec = band_120_control_spec()
    strips = plan_strips(spec, strip_len=6)
    seed = _greedy_pack(strips, height)
    pack = _pack(
        strips,
        height=height,
        width_bound=max(8, 2 * seed.width),
        time_budget_s=1.0,
        direct_candidates=_direct_net_candidates(strips, spec),
        workers=1,
        seed=seed,
    )

    assert pack is not None
    result = _build(
        spec,
        strips,
        pack,
        power=False,
        route=True,
        policy=BandPolicy(selection),
        budget={"left": 5_000_000},
    )
    assert result.routing.status is DetailedRouteStatus.ROUTED
    assert result.placement is not None
    assert validate.certify(result.placement, spec, expect_power=False).ok
    assert finalize.finalize_placement(
        result.placement,
        BandPolicy(selection),
    ).frame is not None


def test_freeform_portable_schedule_preserves_legacy_order() -> None:
    strips = plan_strips(two_stage_spec(), strip_len=6)
    seeds = {
        height: _greedy_pack(strips, height)
        for height in freeform._candidate_heights(strips)
    }
    legacy = tuple(sorted(seeds, key=lambda height: (seeds[height].width, height)))

    assert (
        freeform._band_policy_candidate_heights(
            strips,
            BandPolicy("portable"),
        )
        == legacy
    )


@pytest.mark.parametrize(
    ("core_width", "core_height"),
    ((595, 19), (19, 595)),
)
def test_freeform_extent_gate_stops_before_power_planning_in_both_orientations(
    core_width: int,
    core_height: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec, strip_len=6)
    pack = replace(
        _greedy_pack(strips, core_height),
        width=core_width,
        height=core_height,
    )
    monkeypatch.setattr(
        freeform,
        "_power_plan",
        lambda *_args, **_kwargs: pytest.fail("infeasible extent reached power planning"),
    )
    monkeypatch.setattr(
        freeform,
        "_core_bounds",
        lambda _canvas: (0, 0, core_width - 1, core_height - 1),
    )

    with pytest.raises(finalize.ProjectionRefusal) as caught:
        _prepare_routing_problem(
            spec,
            strips,
            pack,
            policy=BandPolicy("120"),
            power=True,
        )

    assert caught.value.checks == ("game.blueprint_area",)


def test_freeform_extent_gate_uses_realized_core_not_nominal_pack_ceiling() -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec, strip_len=6)
    nominally_oversized = replace(
        _greedy_pack(strips, 595),
        width=19,
        height=595,
    )

    prepared = _prepare_routing_problem(
        spec,
        strips,
        nominally_oversized,
        policy=BandPolicy("120"),
        power=False,
    )

    core_width = prepared.core[2] - prepared.core[0] + 1
    core_height = prepared.core[3] - prepared.core[1] + 1
    assert finalize.band_policy_search_envelope(
        BandPolicy("120"),
        perimeter=_ENTRY_RING,
    ).frame_candidates(core_width, core_height)


@pytest.mark.parametrize(
    "band",
    (
        next(band for band in planet.bands() if band.is_equatorial),
        next(band for band in planet.bands() if not band.is_equatorial and band.rows >= 10),
    ),
)
def test_staged_static_effective_anchor_ranges_replace_padding_cross_product(
    band: planet.Band,
) -> None:
    pair_height = band.rows - 2 * _ENTRY_RING - 2
    reference = {
        anchor + row
        for frame_height in range(
            pair_height + 2 * _ENTRY_RING,
            band.rows + 1,
        )
        for anchor in band.anchors(frame_height)
        for row in range(
            _ENTRY_RING,
            frame_height - pair_height - _ENTRY_RING + 1,
        )
    }

    ranges = freeform._staged_static_effective_anchor_ranges(pair_height, band)

    assert len(ranges) <= 2
    assert tuple(anchor for interval in ranges for anchor in interval) == tuple(
        sorted(reference)
    )


def test_staged_static_projection_risk_uses_one_exact_pair_per_relation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strip = next(
        strip
        for strip in plan_strips(proliferated_spec())
        if freeform._staged_static_clearance_keys(strip)
    )
    relation = next(iter(freeform._staged_static_clearance_keys(strip)))
    original = planet.collisions_at
    pair_counts: list[int] = []

    def counted(
        buildings: Sequence[colliders.Placed],
        projection: planet.Projection,
        pairs: Sequence[tuple[int, int]] | None = None,
        **kwargs: object,
    ) -> list[tuple[int, int]]:
        pair_counts.append(0 if pairs is None else len(pairs))
        return original(buildings, projection, pairs, **kwargs)

    monkeypatch.setattr(planet, "collisions_at", counted)

    result = freeform._staged_static_relation_projection_risk_uncached(
        relation,
        BandPolicy("160"),
    )

    assert isinstance(result, bool)
    assert pair_counts
    assert set(pair_counts) == {1}


def test_staged_static_preclearance_batches_both_exact_relations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    peer = catalog.building(2305)
    coater = catalog.building(catalog.SPRAY_COATER_ID)
    relation = freeform.StagedStaticClearanceKey(
        peer_item_id=2305,
        peer_model_index=peer.model_index,
        peer_width=peer.width,
        peer_height=peer.height,
        peer_yaw=0.0,
        candidate_item_id=catalog.SPRAY_COATER_ID,
        candidate_model_index=coater.model_index,
        candidate_width=coater.width,
        candidate_height=coater.height,
        candidate_yaw=Facing.EAST.value,
        delta_x=2,
        delta_y=1,
        delta_z=F(0),
    )
    original = planet.collisions_at
    pair_counts: list[int] = []

    def counted(
        buildings: Sequence[colliders.Placed],
        projection: planet.Projection,
        pairs: Sequence[tuple[int, int]] | None = None,
        **kwargs: object,
    ) -> list[tuple[int, int]]:
        pair_counts.append(0 if pairs is None else len(pairs))
        return original(buildings, projection, pairs, **kwargs)

    monkeypatch.setattr(planet, "collisions_at", counted)

    assert freeform._staged_static_preclearance_proof_uncached(
        relation,
        BandPolicy("160"),
    )
    assert max(pair_counts) >= 2, (
        "the rejected and one-tile-cleared relations must share each exact "
        "candidate projection rather than rebuilding it separately"
    )


def band_160_all_products_spec() -> BuildSpec:
    from flab2bp.lab.data import load_vendored
    from flab2bp.lab.url import parse_url
    from flab2bp.rates.candidates import CandidatePolicy, build_candidates

    url = (
        "https://factoriolab.github.io/dsp/flow?"
        "z=eJzLt63SMjQwUMu3dQrWMgPTzlrGILpEywgi7qRlaGZgoKVlqJZvaw4ShLLDQBrB"
        "7MykVFsntdzcItvIOqc617pAtdyCYls3tTJbQ0MAjnsZAA__&v=11"
    )
    return next(
        candidate
        for candidate in build_candidates(
            load_vendored(),
            parse_url(url),
            candidate_policies=(CandidatePolicy.ALL_PRODUCTS,),
        ).candidates
        if candidate.label == "all-products"
    )


def test_staged_static_clearance_reuses_only_the_same_physical_relation() -> None:
    policy = BandPolicy("portable")
    spec = band_160_all_products_spec()
    ordinary = plan_strips(spec, band_policy=policy)
    unsafe = next(
        strip
        for strip in ordinary
        if strip.item_id == catalog.item_id("assembling-machine-2")
        and strip.west_channel == freeform._COATER_WEST_CHANNEL + 1
        and any(
            freeform._staged_static_preclearance_proved(relation, policy)
            for relation in freeform._staged_static_clearance_keys(
                replace(strip, west_channel=freeform._COATER_WEST_CHANNEL)
            )
        )
    )
    unsafe_w3 = replace(
        unsafe,
        west_channel=freeform._COATER_WEST_CHANNEL,
    )
    relation = next(
        relation
        for relation in freeform._staged_static_clearance_keys(unsafe_w3)
        if freeform._staged_static_preclearance_proved(relation, policy)
    )
    assert freeform._staged_static_relation_projection_risk(relation, policy)
    assert not freeform._staged_static_relation_projection_risk(
        replace(relation, delta_x=relation.delta_x + 1),
        policy,
    )

    safe = next(
        strip
        for strip in ordinary
        if strip.cargo_domain is CargoDomain.REQUIRES_SPRAY
        and strip.west_channel == freeform._COATER_WEST_CHANNEL
        and freeform._staged_static_clearance_keys(strip)
        and all(
            not freeform._staged_static_relation_projection_risk(candidate, policy)
            for candidate in freeform._staged_static_clearance_keys(strip)
        )
    )
    assert relation not in freeform._staged_static_clearance_keys(safe)

    regenerated = plan_strips(
        spec,
        band_policy=policy,
        minimum_staged_static_clearance={
            relation: freeform._COATER_WEST_CHANNEL + 1,
        },
    )
    equivalent = [
        strip
        for strip in regenerated
        if relation
        in freeform._staged_static_clearance_keys(
            replace(strip, west_channel=freeform._COATER_WEST_CHANNEL)
        )
    ]
    safe_replacement = next(
        strip
        for strip in regenerated
        if strip.family_id == safe.family_id
        and strip.machine_start == safe.machine_start
    )

    assert len(equivalent) > 1
    assert all(
        strip.west_channel == freeform._COATER_WEST_CHANNEL + 1
        for strip in equivalent
    )
    assert safe_replacement.west_channel == freeform._COATER_WEST_CHANNEL

def test_all_products_band_160_cold_proof_reaches_a_valid_layout() -> None:
    spec = band_160_all_products_spec()
    freeform._staged_static_preclearance_proved.cache_clear()

    placement = FreeformLayout(
        band_policy=BandPolicy("portable"),
    ).lay_out(spec, time_budget_s=15.0)

    assert placement.frame is not None
    assert placement.frame.primary_band == 160
    assert validate.certify(placement, spec, expect_power=True).ok


def test_plan_strips_batches_all_exact_preclearance_relations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeform._staged_static_preclearance_proved.cache_clear()
    original = planet.collisions_at
    pair_counts: list[int] = []

    def counted(
        buildings: Sequence[colliders.Placed],
        projection: planet.Projection,
        pairs: Sequence[tuple[int, int]] | None = None,
        **kwargs: object,
    ) -> list[tuple[int, int]]:
        pair_counts.append(0 if pairs is None else len(pairs))
        return original(buildings, projection, pairs, **kwargs)

    monkeypatch.setattr(planet, "collisions_at", counted)

    plan_strips(proliferated_spec(), band_policy=BandPolicy("portable"))

    assert max(pair_counts) > 2, (
        "all strip relations sharing a projected candidate must use one exact "
        "predicate rather than one rejected/cleared pair at a time"
    )
    assert len(pair_counts) < 2_000, (
        "candidate-relative anchors must share one exact predicate per absolute "
        "latitude rather than replaying each pair-height frame"
    )


def test_batched_relation_anchor_collection_cancels_without_caching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strip = next(
        strip
        for strip in plan_strips(proliferated_spec())
        if freeform._staged_static_clearance_keys(strip)
    )
    relation = next(iter(freeform._staged_static_clearance_keys(strip)))

    class InstrumentedAnchors:
        yielded = 0
        exhausted = False

        def __iter__(self) -> Iterator[int]:
            self.yielded += 1
            yield 0
            self.exhausted = True
            yield 1

    class AnchorBounds:
        start = 0
        stop = 2

    anchors = InstrumentedAnchors()
    monkeypatch.setattr(
        freeform,
        "_staged_static_effective_anchor_ranges",
        lambda _pair_height, _band: (AnchorBounds(),),
    )
    monkeypatch.setattr(
        freeform,
        "range",
        lambda _start, _stop: anchors,
        raising=False,
    )
    freeform._STAGED_STATIC_RELATION_RISK_CACHE.clear()
    token = freeform._STAGED_STATIC_PROOF_CANCELLED.set(
        lambda: anchors.yielded >= 1
    )
    try:
        with pytest.raises(freeform._PreparationDeadline):
            freeform._staged_static_relation_projection_risks(
                (relation,),
                BandPolicy("portable"),
            )
    finally:
        freeform._STAGED_STATIC_PROOF_CANCELLED.reset(token)

    assert not anchors.exhausted
    assert not freeform._STAGED_STATIC_RELATION_RISK_CACHE


def test_staged_static_preclearance_cancels_inside_cold_proof_without_caching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strip = next(
        strip
        for strip in plan_strips(proliferated_spec())
        if freeform._staged_static_clearance_keys(strip)
    )
    relation = next(iter(freeform._staged_static_clearance_keys(strip)))
    freeform._staged_static_preclearance_proved.cache_clear()
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 8

    with pytest.raises(freeform._PreparationDeadline):
        freeform._staged_static_preclearance_proved(
            relation,
            BandPolicy("portable"),
            cancelled=cancelled,
        )

    monkeypatch.setattr(
        freeform,
        "_staged_static_preclearance_proof_uncached",
        lambda _relation, _policy: True,
    )
    assert freeform._staged_static_preclearance_proved(
        relation,
        BandPolicy("portable"),
    )
    assert checks == 8
    monkeypatch.undo()
    freeform._staged_static_preclearance_proved.cache_clear()


def test_power_projection_envelope_cancels_inside_rectangle_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine = catalog.building(2303)
    canvas = _Canvas()
    canvas.add(
        PlacedBuilding(
            2303,
            machine.model_index,
            0,
            0,
            width=machine.width,
            height=machine.height,
        ),
        solid=True,
    )
    canvas.limit = (-3, -3, 6, 6)

    def cleanup_bounds(
        placement: Placement,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[int, int, int, int]:
        assert cancelled is not None
        return placement.bounds

    monkeypatch.setattr(finalize, "_cleanup_survivor_bounds", cleanup_bounds)
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 8

    with pytest.raises(freeform._PreparationDeadline):
        freeform._power_projection_envelope(
            canvas,
            BandPolicy("portable"),
            cancelled=cancelled,
        )

    assert checks == 8


def test_cancelled_junction_frame_cache_miss_never_installs_partial_frames() -> None:
    cache = freeform._StagedStaticCache()
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 10

    with pytest.raises(freeform._PreparationDeadline):
        freeform._cached_junction_projection_frames(
            cache,
            (0, 0, 1, 1),
            (-3, -3, 4, 4),
            BandPolicy("portable"),
            cancelled=cancelled,
        )

    assert checks == 10
    assert cache.frames == {}


def test_prepared_junction_ban_cancels_inside_cell_level_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine = catalog.building(2303)
    obstacle = PlacedBuilding(
        2303,
        machine.model_index,
        0,
        0,
        width=machine.width,
        height=machine.height,
    )
    cache = freeform._StagedStaticCache()
    sites = 0

    def site_is_clear(
        _buildings: Sequence[PlacedBuilding],
        _x: int,
        _y: int,
        _level: int,
    ) -> bool:
        nonlocal sites
        sites += 1
        return True

    monkeypatch.setattr(freeform, "_junction_site_is_clear", site_is_clear)

    with pytest.raises(freeform._PreparationDeadline):
        freeform._prepared_junction_ban(
            (obstacle,),
            (),
            cancelled=lambda: sites >= 1,
            cache=cache,
        )

    assert sites == 1
    assert cache.junction_offsets == {}


def test_prepared_junction_ban_reuses_complete_immutable_offsets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine = catalog.building(2303)
    obstacles = tuple(
        PlacedBuilding(
            2303,
            machine.model_index,
            x,
            0,
            width=machine.width,
            height=machine.height,
        )
        for x in (0, 20)
    )
    expected = freeform._prepared_junction_ban(obstacles, ())
    original = freeform._cancellable_junction_ban_offsets
    calls = 0

    def counted(
        item_id: int,
        model_index: int,
        width: int,
        height: int,
        yaw: float,
        z: F,
        cancelled: Callable[[], bool],
    ) -> frozenset[Cell]:
        nonlocal calls
        calls += 1
        return original(
            item_id,
            model_index,
            width,
            height,
            yaw,
            z,
            cancelled,
        )

    monkeypatch.setattr(freeform, "_cancellable_junction_ban_offsets", counted)
    cache = freeform._StagedStaticCache()
    actual = freeform._prepared_junction_ban(
        obstacles,
        (),
        cancelled=lambda: False,
        cache=cache,
    )

    assert actual == expected
    assert calls == 1


def test_prepared_junction_ban_reuses_complete_geometry_offsets_per_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine = catalog.building(2303)
    obstacles = (
        PlacedBuilding(
            2303,
            machine.model_index,
            x,
            4,
            width=machine.width,
            height=machine.height,
        )
        for x in (2, 20)
    )
    calls = 0

    def offsets(*_args: object) -> frozenset[Cell]:
        nonlocal calls
        calls += 1
        return frozenset({(-1, 1, 2)})

    monkeypatch.setattr(
        freeform,
        "_cancellable_junction_ban_offsets",
        offsets,
    )

    ban = freeform._prepared_junction_ban(
        tuple(obstacles),
        (),
        cancelled=lambda: False,
    )

    assert calls == 1
    assert ban == frozenset({(1, 5, 2), (19, 5, 2)})




def test_projected_coater_junction_ban_reuses_identical_exact_relations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coater_info = catalog.building(catalog.SPRAY_COATER_ID)
    coater = PlacedBuilding(
        catalog.SPRAY_COATER_ID,
        coater_info.model_index,
        0,
        0,
        width=coater_info.width,
        height=coater_info.height,
    )
    placement = Placement(buildings=(coater,))
    candidate = finalize.frame_candidates(placement, BandPolicy("portable"))[0]
    band = next(
        band
        for band in planet.bands()
        if band.area_segments == candidate.frame.certified_bands[0]
    )
    projection = planet.Projection(
        band,
        next(iter(band.anchors(candidate.frame.height))),
        colliders.PLANET_SEGMENT,
        colliders.PLANET_RADIUS,
    )
    frame = freeform._JunctionProjectionFrame(
        placement.bounds,
        candidate,
        (projection,),
    )
    overlaps = 0
    keepouts = 0
    boxes = (object(), object())

    def no_overlap(_left: object, _right: object) -> bool:
        nonlocal overlaps
        overlaps += 1
        return False

    def coater_boxes(*_args: object) -> tuple[object, object]:
        nonlocal keepouts
        keepouts += 1
        return boxes

    monkeypatch.setattr(
        finalize,
        "projected_coater_keepout_boxes",
        coater_boxes,
    )
    monkeypatch.setattr(colliders, "target_boxes", lambda *_args: boxes)
    monkeypatch.setattr(colliders, "obb_overlap", no_overlap)

    freeform._projected_coater_junction_ban(
        ((0, coater), (1, coater)),
        (frame,),
        placement.bounds,
        already_banned=set(),
        splitter_index=2,
    )

    assert overlaps == 3 * LEVELS * len(boxes) ** 2
    assert keepouts == 1




def test_projected_coater_junction_ban_cancels_inside_obb_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coater_info = catalog.building(catalog.SPRAY_COATER_ID)
    coater = PlacedBuilding(
        catalog.SPRAY_COATER_ID,
        coater_info.model_index,
        0,
        0,
        width=coater_info.width,
        height=coater_info.height,
    )
    placement = Placement(buildings=(coater,))
    candidate = finalize.frame_candidates(placement, BandPolicy("portable"))[0]
    band = next(
        band
        for band in planet.bands()
        if band.area_segments == candidate.frame.certified_bands[0]
    )
    projection = planet.Projection(
        band,
        next(iter(band.anchors(candidate.frame.height))),
        colliders.PLANET_SEGMENT,
        colliders.PLANET_RADIUS,
    )
    frame = freeform._JunctionProjectionFrame(
        placement.bounds,
        candidate,
        (projection,),
    )
    overlaps = 0
    boxes = (object(), object())

    def overlap_once(_left: object, _right: object) -> bool:
        nonlocal overlaps
        overlaps += 1
        return False

    monkeypatch.setattr(finalize, "projected_coater_keepout_boxes", lambda *_args: boxes)
    monkeypatch.setattr(colliders, "target_boxes", lambda *_args: boxes)
    monkeypatch.setattr(colliders, "obb_overlap", overlap_once)

    with pytest.raises(freeform._PreparationDeadline):
        freeform._projected_coater_junction_ban(
            ((0, coater),),
            (frame,),
            placement.bounds,
            already_banned=set(),
            splitter_index=1,
            cancelled=lambda: overlaps >= 1,
        )

    assert overlaps == 1

def test_power_peer_broad_phase_cancels_before_no_hit_pruning() -> None:
    tower = catalog.building(catalog.TESLA_TOWER_ID)
    band = planet.bands()[0]

    def node(index: int, x: int) -> tuple[int, PlacedBuilding, rules.PowerNode]:
        return (
            index,
            PlacedBuilding(
                catalog.TESLA_TOWER_ID,
                tower.model_index,
                x,
                0,
                width=tower.width,
                height=tower.height,
            ),
            tower.power_node,
        )

    context = (
        band.columns,
        False,
        freeform._minimum_projection_grid_scale((band,)),
    )
    candidate = node(0, 0)
    peer = node(1, band.columns // 2)
    assert not freeform._projected_power_peer_possible(candidate, peer, (context,))

    for context_count in (1, 8):
        checks = 0

        def active() -> bool:
            nonlocal checks
            checks += 1
            return False

        assert not freeform._projected_power_peer_possible(
            candidate,
            peer,
            (context,) * context_count,
            cancelled=active,
        )
        assert checks == 3

    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 3

    with pytest.raises(freeform._PreparationDeadline):
        freeform._projected_power_peer_possible(
            candidate,
            peer,
            (context,) * 8,
            cancelled=cancelled,
        )

    assert checks == 3



def test_power_plan_cancels_inside_proposal_projection_node_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tower = catalog.building(catalog.TESLA_TOWER_ID)
    canvas = _Canvas()
    canvas.add(
        PlacedBuilding(
            catalog.TESLA_TOWER_ID,
            tower.model_index,
            0,
            0,
            width=tower.width,
            height=tower.height,
        ),
        solid=True,
    )
    canvas.limit = (-5, -5, 8, 8)
    band = planet.bands()[0]
    projections = (
        planet.Projection(
            band,
            anchor,
            colliders.PLANET_SEGMENT,
            colliders.PLANET_RADIUS,
        )
        for anchor in tuple(band.anchors(1))[:2]
    )
    proposal_pairs = 0

    def power_failure(
        nodes: Sequence[tuple[int, PlacedBuilding, rules.PowerNode]],
        _projection: planet.Projection,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> finalize.ProjectionFailure | None:
        nonlocal proposal_pairs
        assert cancelled is not None
        if len(nodes) == 2:
            proposal_pairs += 1
        return None

    monkeypatch.setattr(
        freeform,
        "_power_projection_envelope",
        lambda *_args, **_kwargs: tuple(projections),
    )
    monkeypatch.setattr(finalize, "projected_power_failure", power_failure)
    def retain_power_peer(
        _candidate: tuple[int, PlacedBuilding, rules.PowerNode],
        _peer: tuple[int, PlacedBuilding, rules.PowerNode],
        _contexts: Sequence[tuple[int, bool, float]],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> bool:
        assert cancelled is not None
        return True

    monkeypatch.setattr(
        freeform,
        "_projected_power_peer_possible",
        retain_power_peer,
    )
    cache = freeform._StagedStaticCache()

    with pytest.raises(freeform._PreparationDeadline):
        _power_plan(
            canvas,
            (-2, -2, 4, 4),
            policy=BandPolicy("portable"),
            staged_static_cache=cache,
            cancelled=lambda: proposal_pairs >= 1,
        )

    assert proposal_pairs == 1
    assert cache.frames == {}


def test_regular_build_maps_cancelled_preparation_to_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec, strip_len=6)
    pack = _greedy_pack(strips, max(_box(strip)[1] for strip in strips))

    def cancel_preparation(
        *_args: object,
        cancelled: Callable[[], bool] | None = None,
        **_kwargs: object,
    ) -> freeform._PreparedRoutingProblem:
        assert cancelled is not None
        assert cancelled()
        raise freeform._PreparationDeadline

    monkeypatch.setattr(freeform, "_prepare_routing_problem", cancel_preparation)

    result = _build(
        spec,
        strips,
        pack,
        power=False,
        route=True,
        policy=BandPolicy("portable"),
        deadline=time.monotonic() - 1.0,
    )

    assert result.placement is None
    assert result.routing.status is DetailedRouteStatus.BUDGET


def test_post_feedback_replan_deadline_is_a_typed_preparation_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def expire_replan(
        _layout: FreeformLayout,
        *_args: object,
        **_kwargs: object,
    ) -> Placement | None:
        raise freeform._PreparationDeadline

    monkeypatch.setattr(FreeformLayout, "_sweep", expire_replan)

    with pytest.raises(
        NoValidLayout,
        match="PREPARATION deadline passed while applying learned projection geometry",
    ) as caught:
        FreeformLayout(band_policy=BandPolicy("portable")).lay_out(
            two_stage_spec(),
            time_budget_s=1.0,
        )

    assert isinstance(caught.value.__cause__, freeform._PreparationDeadline)
