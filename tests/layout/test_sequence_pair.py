import base64
import os
import pickle
import random
import subprocess
import sys
from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace
from itertools import combinations, permutations
from typing import cast

import pytest

import flab2bp.layout.sequence_pair as sequence_pair_module
from flab2bp.layout.base import DETERMINISTIC_WORKERS
from flab2bp.layout.freeform import (
    _direct_alignment_targets,
    _direct_net_candidates,
    _pack,
    plan_strips,
)
from flab2bp.layout.route_feedback import (
    DetailedRouteResult,
    DetailedRouteStatus,
    FeedbackState,
    LogicalNetId,
    NetFailure,
    NetId,
    NetRole,
    RouteFailureKind,
    feedback_cost_context,
    select_lns_neighbourhood,
)
from flab2bp.layout.sequence_pair import (
    AnnealConfig,
    AnnealIncumbent,
    AnnealState,
    DecodedPlacement,
    DirectInsertTarget,
    EnergyBreakdown,
    GapProfile,
    MoveKind,
    PlacementCostContext,
    PlacementKey,
    PlacementProblem,
    SearchEnergy,
    SequencePair,
    align_direct_inserts,
    anneal_stage,
    apply_move,
    apply_variant_move,
    cheap_energy,
    decode_sequence_pair,
    decode_state,
    derive_stage_seed,
    enable_variant_stage_boundary,
    merge_stage_boundary,
    repair_neighbourhood,
    split_stage_boundary,
)
from flab2bp.layout.strip_variants import (
    StripFamilyId,
    StripInstanceId,
    StripVariant,
    _variant_id,
    partition_strip_family,
    variant_with_minimum_pitch,
    variants_for_count,
)
from tests.layout.test_freeform import two_stage_spec
from tests.layout.test_strip_variants import _family, _single_machine_spec


def _boxes(
    decoded: DecodedPlacement, sizes: tuple[tuple[int, int], ...]
) -> tuple[tuple[int, int, int, int], ...]:
    return tuple(
        (decoded.x[index], decoded.y[index], decoded.x[index] + width, decoded.y[index] + height)
        for index, (width, height) in enumerate(sizes)
    )


def _assert_no_overlap(decoded: DecodedPlacement, sizes: tuple[tuple[int, int], ...]) -> None:
    boxes = _boxes(decoded, sizes)
    for first, second in combinations(range(len(sizes)), 2):
        ax0, ay0, ax1, ay1 = boxes[first]
        bx0, by0, bx1, by1 = boxes[second]
        assert ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0


def test_sequence_pair_relations_decode_to_expected_axes() -> None:
    pair = SequencePair(positive=(0, 1, 2), negative=(0, 2, 1))
    decoded = decode_sequence_pair(
        pair, GapProfile.zero(3), ((3, 2), (4, 2), (2, 3)), outline_height=10
    )
    assert decoded.x[1] >= decoded.x[0] + 3
    assert decoded.y[1] >= decoded.y[2] + 3


def test_all_four_sequence_pair_relations_use_the_expected_direction() -> None:
    sizes = ((3, 2), (4, 5))
    expected: dict[tuple[tuple[int, int], tuple[int, int]], Callable[[DecodedPlacement], bool]] = {
        ((0, 1), (0, 1)): lambda decoded: decoded.x[1] >= decoded.x[0] + 3,
        ((1, 0), (1, 0)): lambda decoded: decoded.x[0] >= decoded.x[1] + 4,
        ((0, 1), (1, 0)): lambda decoded: decoded.y[0] >= decoded.y[1] + 5,
        ((1, 0), (0, 1)): lambda decoded: decoded.y[1] >= decoded.y[0] + 2,
    }
    for (positive, negative), relation_holds in expected.items():
        decoded = decode_sequence_pair(
            SequencePair(positive, negative),
            GapProfile.zero(2),
            sizes,
            outline_height=7,
        )
        assert relation_holds(decoded)


def test_gap_profile_adds_explicit_channel_space() -> None:
    pair = SequencePair(positive=(0, 1), negative=(0, 1))
    plain = decode_sequence_pair(pair, GapProfile.zero(2), ((3, 2), (4, 2)), outline_height=6)
    gapped = decode_sequence_pair(
        pair,
        GapProfile(east=(2, 0), north=(0, 0)),
        ((3, 2), (4, 2)),
        outline_height=6,
    )
    assert gapped.x[1] == plain.x[1] + 2
    assert gapped.gap_area == 4


def test_north_gap_is_added_to_outgoing_vertical_constraints() -> None:
    pair = SequencePair(positive=(0, 1), negative=(1, 0))
    plain = decode_sequence_pair(pair, GapProfile.zero(2), ((3, 2), (4, 3)), outline_height=8)
    gapped = decode_sequence_pair(
        pair,
        GapProfile(east=(0, 0), north=(0, 2)),
        ((3, 2), (4, 3)),
        outline_height=8,
    )
    assert gapped.y[0] == plain.y[0] + 2
    assert gapped.gap_area == 8


def test_decoded_rectangles_never_overlap() -> None:
    sizes = ((3, 2), (4, 3), (2, 5), (1, 4))
    for positive in permutations(range(4)):
        for negative in permutations(range(4)):
            decoded = decode_sequence_pair(
                SequencePair(positive, negative),
                GapProfile.zero(4),
                sizes,
                outline_height=sum(height for _width, height in sizes),
            )
            _assert_no_overlap(decoded, sizes)


def test_coordinate_windows_use_forward_earliest_and_reverse_latest_paths() -> None:
    horizontal = decode_sequence_pair(
        SequencePair((0, 1), (0, 1)),
        GapProfile.zero(2),
        ((3, 2), (4, 2)),
        outline_height=6,
        outline_width=10,
    )
    assert horizontal.x == (0, 3)
    assert horizontal.x_windows == ((0, 3), (3, 6))
    assert horizontal.y_windows == ((0, 4), (0, 4))

    vertical = decode_sequence_pair(
        SequencePair((0, 1), (1, 0)),
        GapProfile.zero(2),
        ((3, 2), (4, 2)),
        outline_height=6,
    )
    assert vertical.y == (2, 0)
    assert vertical.y_windows == ((2, 4), (0, 2))


def test_latest_windows_propagate_through_a_three_rectangle_chain() -> None:
    decoded = decode_sequence_pair(
        SequencePair((0, 1, 2), (0, 1, 2)),
        GapProfile.zero(3),
        ((2, 1), (3, 1), (4, 1)),
        outline_height=2,
        outline_width=12,
    )
    assert decoded.x == (0, 2, 5)
    assert decoded.x_windows == ((0, 3), (2, 5), (5, 8))


def test_default_outline_width_is_the_compacted_width() -> None:
    decoded = decode_sequence_pair(
        SequencePair((0, 1), (0, 1)),
        GapProfile.zero(2),
        ((3, 2), (4, 2)),
        outline_height=6,
    )
    assert decoded.width == 7
    assert decoded.x_windows == ((0, 0), (3, 3))


def test_outline_overflow_returns_infeasible_windows_for_scoring() -> None:
    decoded = decode_sequence_pair(
        SequencePair((0, 1), (1, 0)),
        GapProfile.zero(2),
        ((3, 2), (4, 2)),
        outline_height=3,
    )
    assert decoded.used_height == 4
    assert decoded.y_windows == ((2, 1), (0, -1))


def _direct_alignment_scene(
    *, alignment_window: int = 3
) -> tuple[PlacementProblem, DecodedPlacement, DirectInsertTarget]:
    sizes = ((4, 2), (4, 2), (3, 2))
    problem = PlacementProblem(
        sizes=sizes,
        nets=((0, 1),),
        outline_height=4,
        area_lower_bound=5,
    )
    decoded = decode_sequence_pair(
        SequencePair((2, 1, 0), (0, 2, 1)),
        GapProfile.zero(3),
        sizes,
        outline_height=problem.outline_height,
        outline_width=7,
    )
    if alignment_window == 0:
        decoded = DecodedPlacement(
            x=decoded.x,
            y=decoded.y,
            width=decoded.width,
            used_height=decoded.used_height,
            x_windows=((decoded.x[0], decoded.x[0]), *decoded.x_windows[1:]),
            y_windows=decoded.y_windows,
            gap_area=decoded.gap_area,
        )
    target = DirectInsertTarget(
        key=(0, 1),
        producer=0,
        consumer=1,
        producer_row=1,
        consumer_row=0,
        producer_span=2,
        consumer_span=2,
        origin_deltas=(-1, 0, 1),
    )
    return problem, decoded, target


def _separation_relations(
    decoded: DecodedPlacement, sizes: tuple[tuple[int, int], ...]
) -> tuple[tuple[bool, bool, bool, bool], ...]:
    boxes = _boxes(decoded, sizes)
    return tuple(
        (
            boxes[first][2] <= boxes[second][0],
            boxes[second][2] <= boxes[first][0],
            boxes[first][3] <= boxes[second][1],
            boxes[second][3] <= boxes[first][1],
        )
        for first, second in combinations(range(len(sizes)), 2)
    )


def test_alignment_realizes_candidate_without_changing_relations() -> None:
    problem, decoded, target = _direct_alignment_scene()

    aligned = align_direct_inserts(problem, decoded, (target,))

    assert target.key in aligned.direct
    assert aligned.width <= decoded.width
    assert _separation_relations(decoded, problem.sizes) == _separation_relations(
        aligned, problem.sizes
    )
    _assert_no_overlap(aligned, problem.sizes)


def test_alignment_leaves_candidate_when_window_is_too_small() -> None:
    problem, decoded, target = _direct_alignment_scene(alignment_window=0)

    aligned = align_direct_inserts(problem, decoded, (target,))
    assert aligned is decoded
    assert aligned == decoded
    assert target.key not in aligned.direct


def _conflicting_alignment_scene() -> tuple[
    PlacementProblem,
    DecodedPlacement,
    DirectInsertTarget,
    DirectInsertTarget,
]:
    sizes = ((4, 2), (4, 2), (4, 2))
    problem = PlacementProblem(sizes, ((0, 1), (0, 2)), 8, 6)
    decoded = DecodedPlacement(
        x=(2, 0, 4),
        y=(4, 6, 6),
        width=8,
        used_height=8,
        x_windows=((0, 4), (0, 0), (4, 4)),
        y_windows=((4, 4), (6, 6), (6, 6)),
        gap_area=0,
    )
    first = DirectInsertTarget((0, 1), 0, 1, 1, 0, 1, 1, (0,))
    second = DirectInsertTarget((0, 2), 0, 2, 1, 0, 1, 1, (0,))
    return problem, decoded, first, second


def test_alignment_uses_stable_target_order() -> None:
    problem, decoded, first, second = _conflicting_alignment_scene()

    forward = align_direct_inserts(problem, decoded, (first, second))
    reverse = align_direct_inserts(problem, decoded, (second, first))

    assert forward == reverse
    assert forward.direct == frozenset({first.key})


def test_alignment_requires_geometry_for_every_carried_direct_key() -> None:
    problem, decoded, first, second = _conflicting_alignment_scene()
    aligned_first = align_direct_inserts(problem, decoded, (first,))

    with pytest.raises(ValueError, match="carried direct"):
        align_direct_inserts(problem, aligned_first, (second,))


def test_alignment_rejects_duplicate_geometry_for_a_carried_direct_key() -> None:
    problem, decoded, first, second = _conflicting_alignment_scene()
    aligned_first = align_direct_inserts(problem, decoded, (first,))

    with pytest.raises(ValueError, match="duplicate carried direct"):
        align_direct_inserts(problem, aligned_first, (first, first, second))


def test_alignment_revalidates_carried_targets_before_shared_endpoint_shift() -> None:
    problem, decoded, first, second = _conflicting_alignment_scene()
    aligned_first = align_direct_inserts(problem, decoded, (first,))

    aligned_both = align_direct_inserts(problem, aligned_first, (first, second))

    assert aligned_both.direct == frozenset({first.key})
    assert aligned_both.x[first.producer] == aligned_both.x[first.consumer]
    assert (
        aligned_both.y[first.consumer]
        + first.consumer_row
        - aligned_both.y[first.producer]
        - first.producer_row
        == 1
    )


def test_alignment_rejects_a_carried_key_whose_geometry_is_already_broken() -> None:
    problem, decoded, first, second = _conflicting_alignment_scene()
    aligned_first = align_direct_inserts(problem, decoded, (first,))
    broken = DecodedPlacement(
        x=(4, *aligned_first.x[1:]),
        y=aligned_first.y,
        width=aligned_first.width,
        used_height=aligned_first.used_height,
        x_windows=aligned_first.x_windows,
        y_windows=aligned_first.y_windows,
        gap_area=aligned_first.gap_area,
        direct=aligned_first.direct,
    )

    with pytest.raises(ValueError, match="not realized"):
        align_direct_inserts(problem, broken, (first, second))


def test_sorter_occupied_overlap_is_not_a_direct_insert() -> None:
    problem = PlacementProblem(
        sizes=((3, 1), (3, 1)),
        nets=((0, 1),),
        outline_height=2,
        area_lower_bound=6,
    )
    decoded = DecodedPlacement(
        x=(0, 0),
        y=(0, 1),
        width=4,
        used_height=2,
        x_windows=((0, 0), (0, 1)),
        y_windows=((0, 0), (1, 1)),
        gap_area=0,
    )
    target = DirectInsertTarget(
        key=(0, 1),
        producer=0,
        consumer=1,
        producer_row=0,
        consumer_row=0,
        producer_span=3,
        consumer_span=3,
        origin_deltas=(1,),
    )

    aligned = align_direct_inserts(problem, decoded, (target,))

    assert aligned.direct == frozenset({target.key})
    assert aligned.x[target.consumer] - aligned.x[target.producer] == 1

    carried_at_sorter_column = replace(
        decoded,
        direct=frozenset({target.key}),
    )
    with pytest.raises(ValueError, match="not realized"):
        align_direct_inserts(problem, carried_at_sorter_column, (target,))


def test_two_stage_alignment_retains_cp_sat_direct_opportunity() -> None:
    spec = two_stage_spec()
    strips = plan_strips(spec, strip_len=6)
    candidates = _direct_net_candidates(strips, spec)
    height = sum(strip.height + 1 for strip in strips)
    oracle = _pack(
        strips,
        height=height,
        width_bound=max(strip.width + 1 for strip in strips) * 2,
        time_budget_s=0.5,
        direct_candidates=candidates,
        workers=DETERMINISTIC_WORKERS,
    )
    assert oracle is not None
    assert oracle.direct

    targets = _direct_alignment_targets(candidates)
    sizes = tuple((strip.width, strip.height) for strip in strips)
    x = tuple(oracle.at[index][0] for index in range(len(strips)))
    y = tuple(oracle.at[index][1] for index in range(len(strips)))
    decoded = DecodedPlacement(
        x=x,
        y=y,
        width=max(coordinate + size[0] for coordinate, size in zip(x, sizes, strict=True)),
        used_height=max(coordinate + size[1] for coordinate, size in zip(y, sizes, strict=True)),
        x_windows=tuple((coordinate, coordinate) for coordinate in x),
        y_windows=tuple((coordinate, coordinate) for coordinate in y),
        gap_area=0,
    )
    problem = PlacementProblem(
        sizes=sizes,
        nets=tuple(candidates),
        outline_height=height,
        area_lower_bound=sum(width * strip_height for width, strip_height in sizes),
    )

    aligned = align_direct_inserts(problem, decoded, targets)
    promised_pairs = frozenset(
        (direct.source_strip, direct.destination_strip) for direct in oracle.direct
    )
    retained = len(promised_pairs & aligned.direct)
    missed = len(promised_pairs - aligned.direct)

    assert (len(oracle.direct), retained, missed) == (1, 1, 0)


def test_generated_cases_are_deterministic_legal_and_integer_only() -> None:
    for size in range(1, 8):
        sizes = tuple((1 + index % 4, 1 + (index * 3) % 5) for index in range(size))
        identity = tuple(range(size))
        generated = {
            (
                identity[offset:] + identity[:offset],
                tuple(reversed(identity[:offset])) + tuple(reversed(identity[offset:])),
            )
            for offset in range(size)
        }
        generated.update(
            (positive, tuple(reversed(negative))) for positive, negative in tuple(generated)
        )
        gaps = GapProfile(
            east=tuple(index % 5 for index in range(size)),
            north=tuple((index * 2) % 5 for index in range(size)),
        )
        outline_height = sum(
            height + gaps.north[index] for index, (_width, height) in enumerate(sizes)
        )
        for positive, negative in sorted(generated):
            pair = SequencePair(positive, negative)
            first = decode_sequence_pair(pair, gaps, sizes, outline_height=outline_height)
            second = decode_sequence_pair(pair, gaps, sizes, outline_height=outline_height)
            assert first == second
            assert all(type(coordinate) is int for coordinate in first.x + first.y)
            _assert_no_overlap(first, sizes)


class _ComparisonCountingOriginDeltas:
    values: tuple[int, ...]
    comparisons: int

    def __init__(self, values: tuple[int, ...]) -> None:
        self.values = values
        self.comparisons = 0

    def __contains__(self, value: object) -> bool:
        for candidate in self.values:
            self.comparisons += 1
            if candidate == value:
                return True
        return False

    def __len__(self) -> int:
        return len(self.values)

    def __getitem__(self, index: int) -> int:
        self.comparisons += 1
        return self.values[index]


def test_direct_origin_lookup_scales_sublinearly_and_preserves_holes() -> None:
    for size in (8, 128, 2_048):
        origin_deltas = tuple(range(0, size * 2, 2))
        target = DirectInsertTarget(
            (0, 1),
            0,
            1,
            0,
            0,
            size * 2,
            1,
            origin_deltas,
        )

        allowed_deltas = _ComparisonCountingOriginDeltas(origin_deltas)
        object.__setattr__(target, "origin_deltas", allowed_deltas)
        allowed = DecodedPlacement(
            x=(0, origin_deltas[-1]),
            y=(0, 1),
            width=size * 2,
            used_height=2,
            x_windows=((0, 0), (origin_deltas[-1], origin_deltas[-1])),
            y_windows=((0, 0), (1, 1)),
            gap_area=0,
        )
        assert sequence_pair_module._target_is_direct(allowed, target)
        assert allowed_deltas.comparisons <= size.bit_length() + 1

        hole_deltas = _ComparisonCountingOriginDeltas(origin_deltas)
        object.__setattr__(target, "origin_deltas", hole_deltas)
        hole = replace(
            allowed,
            x=(0, origin_deltas[-1] - 1),
            x_windows=((0, 0), (origin_deltas[-1] - 1, origin_deltas[-1] - 1)),
        )
        assert not sequence_pair_module._target_is_direct(hole, target)
        assert hole_deltas.comparisons <= size.bit_length() + 1


def test_direct_insert_target_is_immutable() -> None:
    target = DirectInsertTarget((0, 1), 0, 1, 1, 0, 2, 2, (-1, 0, 1))

    with pytest.raises(FrozenInstanceError):
        target.producer_span = 3  # type: ignore[misc]


def test_sequence_pair_and_gap_profile_are_validated_and_immutable() -> None:
    pair = SequencePair((0, 1), (1, 0))
    gaps = GapProfile.zero(2)
    with pytest.raises(FrozenInstanceError):
        pair.positive = (1, 0)  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        gaps.east = (1, 0)  # type: ignore[misc]

    for positive, negative in (
        ((0, 0), (0, 1)),
        ((0, 1), (0, 2)),
        ((0,), (0, 1)),
        ((0, "1"), (0, 1)),
    ):
        with pytest.raises(ValueError, match="every strip exactly once"):
            SequencePair(positive, negative)  # type: ignore[arg-type]

    for east, north in (((-1,), (0,)), ((5,), (0,)), ((0,), (0, 1)), ((1.0,), (0,))):
        with pytest.raises(ValueError, match="gap"):
            GapProfile(east, north)  # type: ignore[arg-type]


def test_decode_rejects_structurally_invalid_input() -> None:
    pair = SequencePair((0,), (0,))
    gaps = GapProfile.zero(1)
    floating_sizes = cast(tuple[tuple[int, int], ...], ((1.0, 1),))
    invalid_calls: tuple[Callable[[], DecodedPlacement], ...] = (
        lambda: decode_sequence_pair(pair, GapProfile.zero(2), ((1, 1),), outline_height=1),
        lambda: decode_sequence_pair(pair, gaps, (), outline_height=1),
        lambda: decode_sequence_pair(pair, gaps, ((0, 1),), outline_height=1),
        lambda: decode_sequence_pair(pair, gaps, floating_sizes, outline_height=1),
        lambda: decode_sequence_pair(pair, gaps, ((1, 1),), outline_height=0),
        lambda: decode_sequence_pair(pair, gaps, ((1, 1),), outline_height=1, outline_width=0),
    )
    for call in invalid_calls:
        with pytest.raises(ValueError):
            call()


def test_placement_problem_validates_geometry_nets_and_bounds() -> None:
    problem = PlacementProblem(
        sizes=((3, 2), (4, 3)),
        nets=((0, 1),),
        outline_height=5,
        area_lower_bound=18,
    )
    assert problem.size == 2
    with pytest.raises(FrozenInstanceError):
        problem.outline_height = 6  # type: ignore[misc]

    invalid_calls: tuple[Callable[[], PlacementProblem], ...] = (
        lambda: PlacementProblem(((0, 2),), (), 2, 0),
        lambda: PlacementProblem(((1, 2),), ((0, 1),), 2, 2),
        lambda: PlacementProblem(((1, 2),), (), 0, 2),
        lambda: PlacementProblem(((1, 2),), (), 2, -1),
    )
    for call in invalid_calls:
        with pytest.raises(ValueError):
            call()


def _tiny_placement_problem() -> PlacementProblem:
    return PlacementProblem(
        sizes=((3, 2), (2, 4), (4, 1), (1, 3)),
        nets=((0, 1), (1, 2), (2, 3), (0, 3)),
        outline_height=6,
        area_lower_bound=20,
    )


def _refinery_variant_problem(
    *,
    variant_count: int = 2,
) -> tuple[PlacementProblem, AnnealState]:
    family = _family(_single_machine_spec("oil-refinery"))
    variants = (family.variants[0], family.variants[4])[:variant_count]
    problem = PlacementProblem(
        sizes=((variants[0].box_width, variants[0].box_height),),
        nets=(),
        outline_height=12,
        area_lower_bound=min(variant.box_width * variant.box_height for variant in variants),
        instance_ids=(StripInstanceId(family.family_id, 0, 1),),
        variant_tables=(variants,),
    )
    return problem, AnnealState.initial(problem.size, seed=17)


def test_variant_move_changes_refinery_pose_box_lane_and_attachments_atomically() -> None:
    problem, state = _refinery_variant_problem()
    original = problem.variant(0, 0)
    selected = problem.variant(0, 1)

    moved = apply_variant_move(problem, state, strip=0, variant=1)

    assert moved.variant_indices == (1,)
    assert selected.yaw != original.yaw
    assert (selected.box_width, selected.box_height) != (
        original.box_width,
        original.box_height,
    )
    assert selected.lane_plan != original.lane_plan
    assert selected.attachment_plan != original.attachment_plan
    assert decode_state(problem, moved).used_height != decode_state(problem, state).used_height


def test_variant_selection_rejects_wrong_cardinality_and_invalid_indices() -> None:
    problem, state = _refinery_variant_problem()

    with pytest.raises(ValueError, match="one variant index per strip"):
        AnnealState(
            pair=state.pair,
            gaps=state.gaps,
            variant_indices=(0, 1),
            base_seed=state.base_seed,
        )
    with pytest.raises(ValueError, match="variant index"):
        apply_variant_move(problem, state, strip=0, variant=2)
    with pytest.raises(ValueError, match="variant index"):
        decode_state(
            problem,
            AnnealState(
                pair=state.pair,
                gaps=state.gaps,
                variant_indices=(2,),
                base_seed=state.base_seed,
            ),
        )


def test_change_variant_is_a_no_op_only_when_every_strip_has_one_variant() -> None:
    problem, state = _refinery_variant_problem(variant_count=1)

    assert (
        apply_move(
            state,
            MoveKind.CHANGE_VARIANT,
            random.Random(7),
            problem=problem,
        )
        == state
    )


def test_change_variant_move_selects_another_valid_variant_and_nothing_else() -> None:
    problem, state = _refinery_variant_problem()

    moved = apply_move(
        state,
        MoveKind.CHANGE_VARIANT,
        random.Random(7),
        problem=problem,
    )

    assert moved.variant_indices == (1,)
    assert moved.pair == state.pair
    assert moved.gaps == state.gaps
    assert moved.base_seed == state.base_seed
    assert moved.stage_index == state.stage_index


def test_selected_variant_dimensions_and_identity_reach_decode_and_elite_keys() -> None:
    problem, state = _refinery_variant_problem()
    selected = apply_variant_move(problem, state, strip=0, variant=1)

    decoded = decode_state(problem, selected)
    result = anneal_stage(
        problem,
        selected,
        AnnealConfig(
            moves_per_stage=30,
            initial_temperature=1.0,
            final_temperature=0.1,
            elite_count=4,
        ),
    )

    assert decoded.variant_indices == (1,)
    assert decoded.used_height == problem.variant(0, 1).box_height
    assert all(
        elite.key.instance_ids == problem.instance_ids
        and elite.key.variant_ids == problem.selected_variant_ids(elite.state.variant_indices)
        and elite.key.dimensions == problem.selected_sizes(elite.state.variant_indices)
        for elite in result.elites
    )


def test_fixed_seed_reproduces_variant_trace() -> None:
    problem, state = _refinery_variant_problem()
    config = AnnealConfig(
        moves_per_stage=60,
        initial_temperature=1.5,
        final_temperature=0.05,
        elite_count=5,
    )

    first = anneal_stage(problem, state, config)
    second = anneal_stage(problem, state, config)

    assert tuple(elite.state.variant_indices for elite in first.elites) == tuple(
        elite.state.variant_indices for elite in second.elites
    )
    assert first.archive == second.archive
    assert all(
        elite.key.variant_ids == problem.selected_variant_ids(elite.state.variant_indices)
        for elite in first.elites
    )
    assert first.final_state.variant_indices == second.final_state.variant_indices


def _variant_at_width(template: StripVariant, width: int) -> StripVariant:
    geometry = replace(
        template.placement_geometry,
        pitch_x=width,
        east_halo=(
            width
            - template.placement_geometry.footprint_width
            - template.placement_geometry.west_halo
        ),
    )
    return replace(
        template,
        variant_id=_variant_id(
            template.variant_id.family_id,
            template.yaw,
            template.machine_origins_x,
            geometry,
            template.lane_plan,
            template.attachment_plan,
            template.port_dock_plan,
            width,
            template.box_height,
        ),
        placement_geometry=geometry,
        box_width=width,
    )


def _alignment_variant_problem(
    *,
    default_widths: tuple[int, int, int],
    selected_widths: tuple[int, int, int],
    producer_x: int,
) -> tuple[PlacementProblem, DecodedPlacement, DirectInsertTarget]:
    family = _family(_single_machine_spec("assembling-machine-1"))
    template = family.variants[0]
    tables = tuple(
        (
            _variant_at_width(template, default),
            _variant_at_width(template, selected),
        )
        if default != selected
        else (_variant_at_width(template, default),)
        for default, selected in zip(default_widths, selected_widths, strict=True)
    )
    problem = PlacementProblem(
        sizes=tuple((width, template.box_height) for width in default_widths),
        nets=((0, 1),),
        outline_height=template.box_height * 2,
        area_lower_bound=1,
        instance_ids=tuple(
            StripInstanceId(family.family_id, machine_start, 1) for machine_start in range(3)
        ),
        variant_tables=tables,
    )
    indices = tuple(1 if len(table) > 1 else 0 for table in tables)
    selected_sizes = problem.selected_sizes(indices)
    consumer_x = 6
    x = (producer_x, consumer_x, consumer_x)
    y = (0, template.box_height, 0)
    decoded = DecodedPlacement(
        x=x,
        y=y,
        width=max(
            coordinate + width
            for coordinate, (width, _height) in zip(x, selected_sizes, strict=True)
        ),
        used_height=template.box_height * 2,
        x_windows=((0, producer_x), (consumer_x, consumer_x), (consumer_x, consumer_x)),
        y_windows=tuple((coordinate, coordinate) for coordinate in y),
        gap_area=0,
        variant_indices=indices,
    )
    target = DirectInsertTarget(
        key=(0, 1),
        producer=0,
        consumer=1,
        producer_row=template.box_height - 1,
        consumer_row=0,
        producer_span=selected_sizes[0][0],
        consumer_span=selected_sizes[1][0],
        origin_deltas=tuple(
            range(-(selected_sizes[1][0] - 1), selected_sizes[0][0])
        ),
    )
    return problem, decoded, target


def test_alignment_rejects_larger_selected_variant_that_would_overlap() -> None:
    problem, decoded, target = _alignment_variant_problem(
        default_widths=(4, 4, 3),
        selected_widths=(5, 4, 4),
        producer_x=10,
    )

    aligned = align_direct_inserts(problem, decoded, (target,))

    assert aligned == decoded
    assert target.key not in aligned.direct


def test_alignment_accepts_smaller_selected_variant_without_default_overlap() -> None:
    problem, decoded, target = _alignment_variant_problem(
        default_widths=(5, 4, 4),
        selected_widths=(4, 4, 3),
        producer_x=9,
    )

    aligned = align_direct_inserts(problem, decoded, (target,))

    assert target.key in aligned.direct
    assert aligned.x == decoded.x
    assert aligned.width == 13


def _stage_boundary_variant_problem() -> tuple[PlacementProblem, AnnealState, StripVariant]:
    family = _family(_single_machine_spec("chemical-plant", count=4))
    variants = variants_for_count(family, 2)
    problem = PlacementProblem(
        sizes=tuple(
            (variants[0].box_width + padding, variants[0].box_height + 1)
            for padding in (2, 3)
        ),
        nets=((0, 1),),
        outline_height=40,
        area_lower_bound=1,
        instance_ids=(
            StripInstanceId(family.family_id, 0, 2),
            StripInstanceId(family.family_id, 2, 2),
        ),
        variant_tables=(variants, variants),
    )
    state = AnnealState(
        pair=SequencePair((1, 0), (0, 1)),
        gaps=GapProfile((2, 3), (4, 1)),
        base_seed=71,
        stage_index=5,
        variant_indices=(0, 1),
    )
    padded = variant_with_minimum_pitch(variants[0], variants[0].pitch_x + 1)
    return problem, state, padded


def test_enable_variant_stage_boundary_rebuilds_only_target_table_and_selection() -> None:
    problem, state, padded = _stage_boundary_variant_problem()

    update = enable_variant_stage_boundary(
        problem,
        state,
        strip=0,
        variant=padded,
        select_variant=True,
    )

    assert update.problem.variant_tables[0] == problem.variant_tables[0] + (padded,)
    assert update.problem.variant_tables[1] == problem.variant_tables[1]
    assert update.problem.sizes == problem.sizes
    assert update.problem.instance_ids == problem.instance_ids
    assert update.problem.nets == problem.nets
    assert update.problem.logical_net_ids == problem.logical_net_ids
    assert update.state.variant_indices[0] == len(problem.variant_tables[0])
    assert update.state.variant_indices[1] == state.variant_indices[1]
    assert update.state.pair == state.pair
    assert update.state.gaps == state.gaps
    assert update.state.base_seed == state.base_seed
    assert update.state.stage_index == state.stage_index


def test_enable_variant_stage_boundary_is_idempotent_for_selected_variant() -> None:
    problem, state, padded = _stage_boundary_variant_problem()
    enabled = enable_variant_stage_boundary(
        problem,
        state,
        strip=0,
        variant=padded,
        select_variant=True,
    )

    repeated = enable_variant_stage_boundary(
        enabled.problem,
        enabled.state,
        strip=0,
        variant=padded,
        select_variant=True,
    )

    assert repeated.problem is enabled.problem
    assert repeated.state is enabled.state


def test_enable_variant_stage_boundary_supersedes_padded_variant_and_rebases_siblings() -> (
    None
):
    problem, state, padded = _stage_boundary_variant_problem()
    enabled = enable_variant_stage_boundary(
        problem,
        state,
        strip=0,
        variant=padded,
        select_variant=True,
    )
    replacement = variant_with_minimum_pitch(padded, padded.pitch_x + 1)
    ordinary_sibling = replace(enabled.state, variant_indices=(1, 1))
    padded_sibling = replace(
        enabled.state,
        variant_indices=(len(enabled.problem.variant_tables[0]) - 1, 1),
    )

    selected = enable_variant_stage_boundary(
        enabled.problem,
        enabled.state,
        strip=0,
        variant=replacement,
        select_variant=True,
    )
    retained = enable_variant_stage_boundary(
        enabled.problem,
        ordinary_sibling,
        strip=0,
        variant=replacement,
        select_variant=False,
    )
    migrated = enable_variant_stage_boundary(
        enabled.problem,
        padded_sibling,
        strip=0,
        variant=replacement,
        select_variant=False,
    )

    replacement_index = len(problem.variant_tables[0])
    expected_table = problem.variant_tables[0] + (replacement,)
    assert selected.problem.variant_tables[0] == expected_table
    assert padded not in selected.problem.variant_tables[0]
    assert retained.problem == selected.problem == migrated.problem
    assert selected.state.variant_indices[0] == replacement_index
    assert retained.state.variant_indices[0] == ordinary_sibling.variant_indices[0]
    assert migrated.state.variant_indices[0] == replacement_index
    assert retained.state.pair == ordinary_sibling.pair
    assert migrated.state.pair == padded_sibling.pair


def test_stage_boundary_split_rebuilds_every_cardinality_owned_array() -> None:
    family = _family(_single_machine_spec("assembling-machine-1", count=4))
    parent = partition_strip_family(family, max_machine_count=4)[0]
    parent_variants = variants_for_count(family, 3)
    unrelated_variants = variants_for_count(family, 1)
    problem = PlacementProblem(
        sizes=(
            (parent_variants[0].box_width + 2, parent_variants[0].box_height + 1),
            (
                unrelated_variants[0].box_width + 2,
                unrelated_variants[0].box_height + 1,
            ),
        ),
        nets=((0, 1), (1, 0)),
        outline_height=40,
        area_lower_bound=1,
        instance_ids=(
            replace(parent.instance_id, machine_count=3),
            StripInstanceId(family.family_id, 3, 1),
        ),
        variant_tables=(parent_variants, unrelated_variants),
    )
    state = AnnealState(
        pair=SequencePair((1, 0), (0, 1)),
        gaps=GapProfile((2, 3), (4, 1)),
        base_seed=71,
        stage_index=5,
        variant_indices=(0, 1),
    )

    split = split_stage_boundary(problem, state, family, 0)

    assert tuple(
        (instance.machine_start, instance.machine_count) for instance in split.problem.instance_ids
    ) == ((0, 2), (2, 1), (3, 1))
    assert split.state.pair == SequencePair((2, 0, 1), (0, 1, 2))
    assert split.state.gaps == GapProfile((2, 0, 3), (4, 0, 1))
    assert split.state.variant_indices == (0, 0, 1)
    assert split.state.base_seed == 71
    assert split.state.stage_index == 5
    assert split.problem.nets == ((0, 2), (1, 2), (2, 0), (2, 1))
    assert all(
        len(table[0].machine_origins_x) == instance.machine_count
        for instance, table in zip(
            split.problem.instance_ids,
            split.problem.variant_tables,
            strict=True,
        )
    )


def test_compatible_stage_boundary_merge_is_exact_split_inverse() -> None:
    family = _family(_single_machine_spec("assembling-machine-1", count=3))
    (parent,) = partition_strip_family(family, max_machine_count=3)
    variants = variants_for_count(family, 3)
    internal = LogicalNetId(
        family.family_id,
        family.family_id,
        "iron-ingot",
        NetRole.INTERNAL,
    )
    proliferator = LogicalNetId(
        family.family_id,
        family.family_id,
        "proliferator",
        NetRole.PROLIFERATOR,
    )
    problem = PlacementProblem(
        sizes=((variants[0].box_width + 2, variants[0].box_height + 1),),
        nets=((0, 0), (0, 0)),
        outline_height=40,
        area_lower_bound=1,
        instance_ids=(parent.instance_id,),
        variant_tables=(variants,),
        logical_net_ids=(internal, proliferator),
    )
    state = AnnealState(
        pair=SequencePair((0,), (0,)),
        gaps=GapProfile((3,), (4,)),
        base_seed=91,
        stage_index=7,
        variant_indices=(1,),
    )

    split = split_stage_boundary(problem, state, family, 0)
    context = feedback_cost_context(
        FeedbackState(
            outline=(40, 40),
            net_weight={},
            cell_history={},
            logical_net_weight={internal: 2.0, proliferator: 4.0},
        ),
        split.problem,
    )
    merged = merge_stage_boundary(split.problem, split.state, family, 0, 1)

    assert split.problem.logical_net_ids.count(internal) == 4
    assert split.problem.logical_net_ids.count(proliferator) == 4
    assert context.net_weights == (3.0,) * 4 + (5.0,) * 4
    assert merged is not None
    assert merged.problem == problem
    assert merged.state == state


def test_every_move_preserves_both_permutations_and_gap_bounds() -> None:
    state = AnnealState.initial(size=8, seed=41)
    for kind in MoveKind:
        moved = apply_move(state, kind, random.Random(7))
        moved.pair.validate(8)
        assert all(0 <= gap <= 4 for gap in moved.gaps.east + moved.gaps.north)


@pytest.mark.parametrize(
    ("kind", "positive_changes", "negative_changes", "gap_changes"),
    (
        (MoveKind.SWAP_POSITIVE, True, False, False),
        (MoveKind.SWAP_NEGATIVE, False, True, False),
        (MoveKind.SWAP_BOTH, True, True, False),
        (MoveKind.INSERT_POSITIVE, True, False, False),
        (MoveKind.INSERT_NEGATIVE, False, True, False),
        (MoveKind.GAP_STEP, False, False, True),
    ),
)
def test_each_move_kind_mutates_only_its_owned_state(
    kind: MoveKind,
    positive_changes: bool,
    negative_changes: bool,
    gap_changes: bool,
) -> None:
    state = AnnealState(
        pair=SequencePair(tuple(range(6)), tuple(range(6))),
        gaps=GapProfile.zero(6),
        base_seed=19,
        stage_index=3,
    )

    moved = apply_move(state, kind, random.Random(7))

    assert (moved.pair.positive != state.pair.positive) is positive_changes
    assert (moved.pair.negative != state.pair.negative) is negative_changes
    assert (moved.gaps != state.gaps) is gap_changes
    assert moved.base_seed == state.base_seed
    assert moved.stage_index == state.stage_index
    if kind is MoveKind.SWAP_BOTH:
        assert moved.pair.positive == moved.pair.negative


def test_gap_move_is_one_bounded_step_including_at_both_bounds() -> None:
    for initial_gap in (0, 2, 4):
        state = AnnealState(
            pair=SequencePair((0,), (0,)),
            gaps=GapProfile((initial_gap,), (initial_gap,)),
            base_seed=3,
            stage_index=0,
        )
        for seed in range(20):
            moved = apply_move(state, MoveKind.GAP_STEP, random.Random(seed))
            deltas = tuple(
                abs(after - before)
                for after, before in zip(
                    moved.gaps.east + moved.gaps.north,
                    state.gaps.east + state.gaps.north,
                    strict=True,
                )
            )
            assert sum(deltas) == 1
            assert all(0 <= gap <= 4 for gap in moved.gaps.east + moved.gaps.north)


def test_swap_both_swaps_the_same_strip_ids_in_each_permutation() -> None:
    state = AnnealState(
        pair=SequencePair((0, 1, 2, 3), (3, 1, 0, 2)),
        gaps=GapProfile.zero(4),
        base_seed=7,
    )

    moved = apply_move(state, MoveKind.SWAP_BOTH, random.Random(7))

    positive_strips = {
        before
        for before, after in zip(state.pair.positive, moved.pair.positive, strict=True)
        if before != after
    }
    negative_strips = {
        before
        for before, after in zip(state.pair.negative, moved.pair.negative, strict=True)
        if before != after
    }
    assert positive_strips == negative_strips


def test_moves_are_legal_no_ops_for_empty_and_singleton_states() -> None:
    for size in (0, 1):
        state = AnnealState.initial(size=size, seed=5)
        for kind in MoveKind:
            moved = apply_move(state, kind, random.Random(11))
            moved.pair.validate(size)
            assert len(moved.gaps.east) == size


def test_candidate_score_reports_independently_recomputed_components() -> None:
    problem = PlacementProblem(
        sizes=((2, 3), (4, 1)),
        nets=((0, 1),),
        outline_height=5,
        area_lower_bound=10,
    )
    decoded = DecodedPlacement(
        x=(1, 4),
        y=(2, 6),
        width=7,
        used_height=8,
        x_windows=((1, 1), (4, 4)),
        y_windows=((2, 2), (6, 6)),
        gap_area=5,
    )
    target = DirectInsertTarget((0, 1), 0, 1, 0, 0, 1, 1, (0,))
    weighted = NetId(0, 1, "iron-ingot", NetRole.INTERNAL, 0)
    context = feedback_cost_context(
        FeedbackState(
            outline=(7, 5),
            net_weight={weighted: 1.0},
            cell_history={(2, 2, 0): 3.0},
        ),
        problem,
        (target,),
    )

    breakdown = sequence_pair_module.score_candidate(problem, decoded, context)

    sizes = problem.selected_sizes(decoded.variant_indices)
    independent_box_area = sum(width * height for width, height in sizes)
    independent_hpwl = sum(
        context.net_weights[index]
        * (
            abs(decoded.x[source] - decoded.x[destination])
            + abs(decoded.y[source] - decoded.y[destination])
        )
        for index, (source, destination) in enumerate(context.net_pairs)
    )
    history_width, history_height = context.history_outline
    history_stride = history_width + 1
    independent_history = 0.0
    for source, destination in context.net_pairs:
        source_width, source_height = sizes[source]
        destination_width, destination_height = sizes[destination]
        x0 = min(history_width, max(0, min(decoded.x[source], decoded.x[destination])))
        y0 = min(history_height, max(0, min(decoded.y[source], decoded.y[destination])))
        x1 = min(
            history_width,
            max(
                decoded.x[source] + source_width,
                decoded.x[destination] + destination_width,
            ),
        )
        y1 = min(
            history_height,
            max(
                decoded.y[source] + source_height,
                decoded.y[destination] + destination_height,
            ),
        )
        independent_history += (
            context.history_summed_area[y1 * history_stride + x1]
            - context.history_summed_area[y0 * history_stride + x1]
            - context.history_summed_area[y1 * history_stride + x0]
            + context.history_summed_area[y0 * history_stride + x0]
        )

    assert breakdown.width == decoded.width
    assert breakdown.used_height == decoded.used_height
    assert breakdown.box_area == independent_box_area
    assert breakdown.gap_area == decoded.gap_area
    assert breakdown.weighted_hpwl == independent_hpwl
    assert breakdown.history_cost == independent_history
    assert breakdown.missed_direct_inserts == 1
    assert breakdown.hard_outline_overflow == max(0, decoded.used_height - problem.outline_height)
    assert breakdown.energy == cheap_energy(problem, decoded, context)
    assert breakdown.energy.scalar == pytest.approx(
        decoded.width * decoded.used_height / problem.area_lower_bound
        + 0.35 * independent_hpwl / problem.area_lower_bound
        + 0.2 * independent_history / len(problem.nets)
        + 0.1 * breakdown.missed_direct_inserts / len(problem.nets)
        + 0.05 * decoded.gap_area / problem.area_lower_bound
    )


def test_energy_breakdown_is_immutable() -> None:
    breakdown = sequence_pair_module.EnergyBreakdown(
        width=1,
        used_height=1,
        box_area=1,
        gap_area=0,
        weighted_hpwl=0.0,
        history_cost=0.0,
        missed_direct_inserts=0,
        hard_outline_overflow=0,
        outline_height=1,
        area_lower_bound=1,
        net_count=0,
    )

    with pytest.raises(FrozenInstanceError):
        breakdown.width = 2  # type: ignore[misc]


def test_missed_direct_insert_penalty_depends_on_candidate_geometry() -> None:
    problem = PlacementProblem(
        sizes=((2, 1), (2, 1)),
        nets=((0, 1),),
        outline_height=2,
        area_lower_bound=4,
    )
    aligned = DecodedPlacement(
        x=(0, 0),
        y=(0, 1),
        width=2,
        used_height=2,
        x_windows=((0, 0), (0, 0)),
        y_windows=((0, 0), (1, 1)),
        gap_area=0,
    )
    separated = DecodedPlacement(
        x=(0, 0),
        y=(1, 0),
        width=2,
        used_height=2,
        x_windows=((0, 0), (0, 0)),
        y_windows=((1, 1), (0, 0)),
        gap_area=0,
    )
    target = DirectInsertTarget((0, 1), 0, 1, 0, 0, 2, 2, (-1, 0, 1))
    context = feedback_cost_context(
        FeedbackState.empty((2, problem.outline_height)),
        problem,
        (target,),
    )

    assert cheap_energy(problem, aligned, context) < cheap_energy(problem, separated, context)


def test_dynamic_direct_targets_score_with_one_validated_context() -> None:
    problem = PlacementProblem(
        sizes=((2, 1), (2, 1)),
        nets=((0, 1),),
        outline_height=2,
        area_lower_bound=4,
    )
    decoded = DecodedPlacement(
        x=(0, 0),
        y=(1, 0),
        width=2,
        used_height=2,
        x_windows=((0, 0), (0, 0)),
        y_windows=((1, 1), (0, 0)),
        gap_area=0,
    )
    target = DirectInsertTarget((0, 1), 0, 1, 0, 0, 2, 2, (-1, 0, 1))
    context = feedback_cost_context(FeedbackState.empty((2, 2)), problem)

    without_target = sequence_pair_module.score_candidate(
        problem,
        decoded,
        context,
        direct_targets=(),
    )
    with_target = sequence_pair_module.score_candidate(
        problem,
        decoded,
        context,
        direct_targets=(target,),
    )

    assert without_target == sequence_pair_module.score_candidate(
        problem,
        decoded,
        replace(context, direct_targets=()),
    )
    assert with_target == sequence_pair_module.score_candidate(
        problem,
        decoded,
        replace(context, direct_targets=(target,)),
    )
    assert without_target.missed_direct_inserts == 0
    assert with_target.missed_direct_inserts == 1
    assert without_target.energy != with_target.energy
    assert context.direct_targets == ()


def test_cheap_energy_handles_zero_area_and_no_nets_without_zero_division() -> None:
    problem = PlacementProblem(
        sizes=(),
        nets=(),
        outline_height=5,
        area_lower_bound=0,
    )
    decoded = decode_sequence_pair(
        SequencePair((), ()),
        GapProfile.zero(0),
        (),
        outline_height=5,
    )

    context = feedback_cost_context(FeedbackState.empty((0, 5)), problem)
    assert cheap_energy(problem, decoded, context) == SearchEnergy(0, 0.0)


def test_search_energy_orders_hard_outline_overflow_before_scalar() -> None:
    assert SearchEnergy(0, 1_000_000.0) < SearchEnergy(1, -1_000_000.0)


def test_cost_context_rejects_non_finite_or_negative_values() -> None:
    invalid_calls: tuple[Callable[[], PlacementCostContext], ...] = (
        lambda: PlacementCostContext((-1.0,), ((0, 0),), (0, 0), (0.0,)),
        lambda: PlacementCostContext((float("inf"),), ((0, 0),), (0, 0), (0.0,)),
        lambda: PlacementCostContext((1.0,), ((0, 0),), (0, 0), (float("nan"),)),
        lambda: PlacementCostContext((1.0,), ((-1, 0),), (0, 0), (0.0,)),
    )
    for call in invalid_calls:
        with pytest.raises(ValueError):
            call()


def test_cost_context_must_match_problem_net_count() -> None:
    problem = PlacementProblem(((1, 1),), ((0, 0),), 1, 1)
    decoded = decode_sequence_pair(
        SequencePair((0,), (0,)),
        GapProfile.zero(1),
        problem.sizes,
        outline_height=1,
    )
    with pytest.raises(ValueError, match="net identities"):
        cheap_energy(
            problem,
            decoded,
            PlacementCostContext((), (), (0, 1), (0.0, 0.0)),
        )


class _HashProbe(int):
    calls = 0

    def __hash__(self) -> int:
        type(self).calls += 1
        return super().__hash__()


class _CollidingInt(int):
    def __hash__(self) -> int:
        return 0


def test_placement_key_caches_deep_hash_and_keeps_collision_safe_equality() -> None:
    _HashProbe.calls = 0
    probed = PlacementKey(
        x=(_HashProbe(1),),
        y=(2,),
        dimensions=((3, 4),),
        east_gaps=(5,),
        north_gaps=(6,),
    )

    assert _HashProbe.calls == 1
    expected_hash = hash(probed)
    assert hash(probed) == expected_hash
    assert _HashProbe.calls == 1

    first = replace(probed, x=(_CollidingInt(1),))
    second = replace(probed, x=(_CollidingInt(2),))
    assert hash(first) == hash(second)
    assert first != second
    collision_map = {first: "first", second: "second"}
    assert len(collision_map) == 2
    assert collision_map[first] == "first"
    assert collision_map[second] == "second"


def test_placement_key_cache_preserves_pickle_and_ordering() -> None:
    lower = PlacementKey(
        x=(1,),
        y=(2,),
        dimensions=((3, 4),),
        east_gaps=(5,),
        north_gaps=(6,),
    )
    higher = replace(lower, x=(2,))

    restored = pickle.loads(pickle.dumps(higher))

    assert restored == higher
    assert hash(restored) == hash(higher)
    assert lower < restored


def test_placement_key_pickle_rehashes_under_destination_process_seed() -> None:
    family_id = StripFamilyId("process-seeded-hash", 0)
    key = PlacementKey(
        x=(1,),
        y=(2,),
        dimensions=((3, 4),),
        east_gaps=(5,),
        north_gaps=(6,),
        instance_ids=(StripInstanceId(family_id, 0, 1),),
    )
    payload = base64.b64encode(pickle.dumps(key)).decode()
    script = """
import base64
import pickle
import sys

key = pickle.loads(base64.b64decode(sys.argv[1]))
fresh = type(key)(
    key.x,
    key.y,
    key.dimensions,
    key.east_gaps,
    key.north_gaps,
    key.instance_ids,
    key.variant_ids,
)
assert key == fresh
assert hash(key) == hash(fresh)
assert {key: "present"}[fresh] == "present"
assert fresh in {key}
print(hash(key))
"""

    hashes = tuple(
        subprocess.run(
            (sys.executable, "-c", script, payload),
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        ).stdout.strip()
        for seed in ("101", "202")
    )

    assert hashes[0] != hashes[1]


def _archive_incumbent(
    *,
    width: int,
    hpwl: float,
    history: float,
    missed_direct: int = 0,
    overflow: int = 0,
    used_height: int = 1,
    seed: int = 0,
) -> AnnealIncumbent:
    state = AnnealState(
        pair=SequencePair((0,), (0,)),
        gaps=GapProfile.zero(1),
        base_seed=seed,
        variant_indices=(0,),
    )
    decoded = DecodedPlacement(
        x=(0,),
        y=(0,),
        width=width,
        used_height=used_height,
        x_windows=((0, 0),),
        y_windows=((0, 0),),
        gap_area=0,
        variant_indices=(0,),
    )
    dimensions = ((width, used_height),)
    return AnnealIncumbent(
        state=state,
        decoded=decoded,
        breakdown=EnergyBreakdown(
            width=width,
            used_height=used_height,
            box_area=width * used_height,
            gap_area=0,
            weighted_hpwl=hpwl,
            history_cost=history,
            missed_direct_inserts=missed_direct,
            hard_outline_overflow=overflow,
            outline_height=1,
            area_lower_bound=1,
            net_count=1,
        ),
        key=PlacementKey(
            x=(0,),
            y=(0,),
            dimensions=dimensions,
            east_gaps=(0,),
            north_gaps=(0,),
        ),
    )


def test_quality_archive_key_prefers_scored_projected_area_over_width() -> None:
    problem = PlacementProblem(
        sizes=((4, 4), (1, 4)),
        nets=(),
        outline_height=8,
        area_lower_bound=20,
    )
    context = PlacementCostContext(
        net_weights=(),
        net_pairs=(),
        history_outline=(0, problem.outline_height),
        history_summed_area=(0.0,) * (problem.outline_height + 1),
    )
    horizontal = AnnealState(
        pair=SequencePair((0, 1), (0, 1)),
        gaps=GapProfile.zero(2),
        base_seed=0,
        variant_indices=(0, 0),
    )
    vertical = replace(
        horizontal,
        pair=SequencePair((0, 1), (1, 0)),
    )
    area_aligned = sequence_pair_module._score_state(problem, horizontal, context)
    narrower = sequence_pair_module._score_state(problem, vertical, context)

    assert (
        area_aligned.breakdown.box_area
        == narrower.breakdown.box_area
        == problem.area_lower_bound
    )
    assert (
        area_aligned.breakdown.width,
        area_aligned.breakdown.used_height,
    ) == (5, 4)
    assert (
        narrower.breakdown.width,
        narrower.breakdown.used_height,
    ) == (4, 8)
    assert sequence_pair_module.quality_archive_key(
        area_aligned
    ) < sequence_pair_module.quality_archive_key(narrower)


def test_quality_archive_key_preserves_overflow_proxy_and_placement_tie_order() -> None:
    best = _archive_incumbent(width=5, hpwl=1.0, history=2.0)
    missed = replace(best, breakdown=replace(best.breakdown, missed_direct_inserts=1))
    overflowing = replace(
        best,
        breakdown=replace(
            best.breakdown,
            hard_outline_overflow=1,
            missed_direct_inserts=0,
            weighted_hpwl=0.0,
            history_cost=0.0,
        ),
    )
    later_key = replace(best, key=replace(best.key, x=(1,)))

    assert sequence_pair_module.quality_archive_key(
        best
    ) < sequence_pair_module.quality_archive_key(missed)
    assert sequence_pair_module.quality_archive_key(
        missed
    ) < sequence_pair_module.quality_archive_key(overflowing)
    assert sorted(
        (later_key, best),
        key=sequence_pair_module.quality_archive_key,
    ) == [best, later_key]


def _archive_relation_incumbent(
    *,
    pair: SequencePair,
    width: int,
    key_offset: int,
) -> AnnealIncumbent:
    candidate = _archive_incumbent(
        width=width,
        hpwl=10.0,
        history=10.0,
    )
    size = len(pair.positive)
    x = tuple(range(key_offset, key_offset + size))
    y = (0,) * size
    gaps = GapProfile.zero(size)
    return replace(
        candidate,
        state=AnnealState(
            pair=pair,
            gaps=gaps,
            base_seed=0,
            variant_indices=(0,) * size,
        ),
        decoded=replace(
            candidate.decoded,
            x=x,
            y=y,
            x_windows=tuple((coordinate, coordinate) for coordinate in x),
            y_windows=((0, 0),) * size,
            variant_indices=(0,) * size,
        ),
        key=PlacementKey(
            x=x,
            y=y,
            dimensions=((1, 1),) * size,
            east_gaps=gaps.east,
            north_gaps=gaps.north,
        ),
    )


def test_elite_archive_substitutes_one_redundant_relation_under_fixed_cap() -> None:
    mandatory = _archive_incumbent(width=1, hpwl=0.0, history=0.0)
    shared_relation = SequencePair((0, 1), (0, 1))
    first_shared = _archive_relation_incumbent(
        pair=shared_relation,
        width=10,
        key_offset=10,
    )
    second_shared = _archive_relation_incumbent(
        pair=shared_relation,
        width=11,
        key_offset=20,
    )
    distinct_relation = _archive_relation_incumbent(
        pair=SequencePair((0, 1), (1, 0)),
        width=12,
        key_offset=30,
    )
    candidates = (
        second_shared,
        distinct_relation,
        mandatory,
        first_shared,
    )

    forward = sequence_pair_module.build_elite_archive(candidates, elite_count=3)
    reverse = sequence_pair_module.build_elite_archive(
        reversed(candidates),
        elite_count=3,
    )

    assert forward == reverse
    assert len(forward) == 3
    assert tuple(entry.incumbent for entry in forward) == (
        mandatory,
        first_shared,
        distinct_relation,
    )
    assert forward[0].categories == tuple(sequence_pair_module.EliteCategory)
    assert tuple(entry.categories for entry in forward[1:]) == (
        (sequence_pair_module.EliteCategory.BLENDED,),
        (sequence_pair_module.EliteCategory.BLENDED,),
    )




def test_incremental_archive_matches_batch_for_variant_distinct_keys() -> None:
    problem, state = _refinery_variant_problem()
    context = PlacementCostContext(
        net_weights=(),
        net_pairs=(),
        history_outline=(0, problem.outline_height),
        history_summed_area=(0.0,) * (problem.outline_height + 1),
    )
    original = sequence_pair_module._score_state(problem, state, context)
    rotated = sequence_pair_module._score_state(
        problem,
        apply_variant_move(problem, state, strip=0, variant=1),
        context,
    )
    assert original.key.variant_ids != rotated.key.variant_ids

    batch = sequence_pair_module.build_elite_archive((original, rotated), elite_count=2)
    builder = sequence_pair_module.EliteArchiveBuilder(elite_count=2)
    builder.add(rotated)
    builder.add(original)

    assert builder.archive == batch


def test_elite_archive_keeps_distinct_narrowest_when_blended_winner_is_wider() -> None:
    wider_blended = _archive_incumbent(width=8, hpwl=0.0, history=0.0)
    narrowest = _archive_incumbent(width=4, hpwl=100.0, history=100.0)

    archive = sequence_pair_module.build_elite_archive(
        (wider_blended, narrowest),
        elite_count=1,
    )

    assert tuple(entry.incumbent for entry in archive) == (wider_blended, narrowest)
    assert archive[0].categories == (
        sequence_pair_module.EliteCategory.BLENDED,
        sequence_pair_module.EliteCategory.LOWEST_HPWL,
        sequence_pair_module.EliteCategory.LOWEST_HISTORY,
    )
    assert archive[1].categories == (sequence_pair_module.EliteCategory.NARROWEST,)


def test_elite_archive_retains_all_distinct_category_winners_beyond_cap() -> None:
    blended = _archive_incumbent(width=8, hpwl=10.0, history=10.0)
    narrowest = _archive_incumbent(width=4, hpwl=1_000.0, history=1_000.0)
    lowest_hpwl = _archive_incumbent(width=20, hpwl=0.0, history=100.0)
    lowest_history = _archive_incumbent(width=21, hpwl=100.0, history=0.0)

    archive = sequence_pair_module.build_elite_archive(
        (lowest_history, narrowest, blended, lowest_hpwl),
        elite_count=1,
    )

    assert tuple(entry.incumbent for entry in archive) == (
        blended,
        narrowest,
        lowest_hpwl,
        lowest_history,
    )
    assert tuple(entry.categories for entry in archive) == (
        (sequence_pair_module.EliteCategory.BLENDED,),
        (sequence_pair_module.EliteCategory.NARROWEST,),
        (sequence_pair_module.EliteCategory.LOWEST_HPWL,),
        (sequence_pair_module.EliteCategory.LOWEST_HISTORY,),
    )


def test_elite_archive_fills_remaining_capacity_in_blended_order() -> None:
    blended = _archive_incumbent(width=8, hpwl=10.0, history=10.0)
    narrowest = _archive_incumbent(width=4, hpwl=1_000.0, history=1_000.0)
    lowest_hpwl = _archive_incumbent(width=20, hpwl=0.0, history=100.0)
    lowest_history = _archive_incumbent(width=21, hpwl=100.0, history=0.0)
    extra_best = _archive_incumbent(width=22, hpwl=100.0, history=100.0)
    extra_worse = _archive_incumbent(width=23, hpwl=100.0, history=100.0)
    candidates = (
        extra_worse,
        lowest_history,
        narrowest,
        extra_best,
        blended,
        lowest_hpwl,
    )

    forward = sequence_pair_module.build_elite_archive(candidates, elite_count=5)
    reverse = sequence_pair_module.build_elite_archive(
        reversed(candidates),
        elite_count=5,
    )

    assert forward == reverse
    assert tuple(entry.incumbent for entry in forward) == (
        blended,
        narrowest,
        lowest_hpwl,
        lowest_history,
        extra_best,
    )
    assert forward[-1].categories == (sequence_pair_module.EliteCategory.BLENDED,)


def test_incremental_archive_matches_batch_after_mandatory_winners_collapse() -> None:
    blended = _archive_incumbent(width=8, hpwl=10.0, history=10.0)
    narrowest = _archive_incumbent(width=4, hpwl=1_000.0, history=1_000.0)
    lowest_hpwl = _archive_incumbent(width=20, hpwl=0.0, history=100.0)
    lowest_history = _archive_incumbent(width=21, hpwl=100.0, history=0.0)
    second_blended = _archive_incumbent(width=9, hpwl=10.0, history=10.0)
    third_blended = _archive_incumbent(width=10, hpwl=10.0, history=10.0)
    collapsed_extremes = _archive_incumbent(
        width=3,
        hpwl=0.0,
        history=0.0,
        missed_direct=200,
    )
    candidates = (
        blended,
        narrowest,
        lowest_hpwl,
        lowest_history,
        second_blended,
        third_blended,
        collapsed_extremes,
    )

    builder = sequence_pair_module.EliteArchiveBuilder(elite_count=4)
    for candidate in candidates:
        builder.add(candidate)
    batch = sequence_pair_module.build_elite_archive(candidates, elite_count=4)

    assert builder.archive == batch
    assert tuple(entry.incumbent for entry in batch) == (
        blended,
        collapsed_extremes,
        second_blended,
        third_blended,
    )
    assert builder.blended_elites == (
        blended,
        second_blended,
        third_blended,
        collapsed_extremes,
    )


def test_incremental_archive_replaces_late_same_key_with_batch_canonical_candidate() -> None:
    mandatory = _archive_incumbent(width=1, hpwl=0.0, history=0.0)
    early = _archive_incumbent(width=8, hpwl=1.0, history=1.0, seed=19)
    other = _archive_incumbent(width=9, hpwl=1.0, history=1.0)
    late_canonical = replace(
        early,
        state=replace(early.state, base_seed=7),
        breakdown=replace(early.breakdown, missed_direct_inserts=1_000),
    )
    builder = sequence_pair_module.EliteArchiveBuilder(elite_count=3)
    for candidate in (mandatory, early, other):
        builder.add(candidate)
    eager_before_late = builder.archive

    builder.add(late_canonical)
    batch = sequence_pair_module.build_elite_archive(
        (mandatory, early, other, late_canonical),
        elite_count=3,
    )

    assert builder.archive != eager_before_late
    assert builder.archive == batch
    assert (
        next(entry.incumbent for entry in builder.archive if entry.incumbent.key == early.key)
        is late_canonical
    )


def test_stage_result_keeps_legacy_blended_elites_separate_from_pareto_archive() -> None:
    blended = _archive_incumbent(width=8, hpwl=10.0, history=10.0)
    second_blended = _archive_incumbent(width=9, hpwl=10.0, history=10.0)
    narrowest = _archive_incumbent(width=4, hpwl=1_000.0, history=1_000.0)
    archive = sequence_pair_module.build_elite_archive(
        (blended, second_blended, narrowest),
        elite_count=2,
    )

    result = sequence_pair_module.AnnealStageResult(
        final_state=blended.state,
        incumbent=blended,
        accepted_moves=0,
        elites=(blended, second_blended),
        archive=archive,
    )

    assert result.elites == (blended, second_blended)
    assert result.archive == archive
    assert result.backend == "python"
    restored = pickle.loads(pickle.dumps(result))
    assert restored == result
    assert restored.backend == "python"


def test_incremental_archive_separates_legacy_first_entry_from_canonical_dedupe() -> None:
    legacy_first = _archive_incumbent(width=1, hpwl=0.0, history=0.0, seed=19)
    canonical = replace(legacy_first, state=replace(legacy_first.state, base_seed=7))

    forward = sequence_pair_module.EliteArchiveBuilder(elite_count=1)
    forward.add(legacy_first)
    forward.add(canonical)
    reverse = sequence_pair_module.EliteArchiveBuilder(elite_count=1)
    reverse.add(canonical)
    reverse.add(legacy_first)

    assert forward.blended_elites == (legacy_first,)
    assert reverse.blended_elites == (canonical,)
    assert forward.archive == reverse.archive
    assert forward.archive[0].incumbent == canonical


def test_elite_archive_deduplicates_exact_keys_with_stable_category_and_seed_ties() -> None:
    later_seed = _archive_incumbent(width=1, hpwl=0.0, history=0.0, seed=19)
    earlier_seed = replace(later_seed, state=replace(later_seed.state, base_seed=7))

    forward = sequence_pair_module.build_elite_archive(
        (later_seed, earlier_seed),
        elite_count=1,
    )
    reverse = sequence_pair_module.build_elite_archive(
        (earlier_seed, later_seed),
        elite_count=1,
    )

    assert forward == reverse
    assert len(forward) == 1
    assert forward[0].incumbent.state.base_seed == 7
    assert forward[0].categories == tuple(sequence_pair_module.EliteCategory)


def test_elite_archive_orders_hard_overflow_before_every_soft_category_metric() -> None:
    legal = _archive_incumbent(width=50, hpwl=50.0, history=50.0)
    overflowing = _archive_incumbent(
        width=1,
        hpwl=0.0,
        history=0.0,
        overflow=1,
    )

    archive = sequence_pair_module.build_elite_archive(
        (overflowing, legal),
        elite_count=1,
    )

    assert archive == (
        sequence_pair_module.TaggedAnnealIncumbent(
            incumbent=legal,
            categories=tuple(sequence_pair_module.EliteCategory),
        ),
    )


def test_derived_stage_seeds_are_stable_and_stage_specific() -> None:
    assert derive_stage_seed(123, 4) == derive_stage_seed(123, 4)
    assert derive_stage_seed(123, 4) != derive_stage_seed(123, 5)
    assert derive_stage_seed(123, 4) != derive_stage_seed(124, 4)


def test_initial_states_are_seeded_reproducibly_for_multi_start() -> None:
    assert AnnealState.initial(12, 17) == AnnealState.initial(12, 17)
    assert AnnealState.initial(12, 17).pair != AnnealState.initial(12, 18).pair


def test_fixed_seed_reproduces_stage_incumbent_and_accepted_move_count() -> None:
    problem = _tiny_placement_problem()
    config = AnnealConfig.test()

    a = anneal_stage(problem, AnnealState.initial(problem.size, 17), config)
    b = anneal_stage(problem, AnnealState.initial(problem.size, 17), config)

    assert a.incumbent == b.incumbent
    assert a.accepted_moves == b.accepted_moves
    assert a.final_state == b.final_state
    assert a.elites == b.elites
    assert a.archive == b.archive




def test_archive_capacity_does_not_change_the_annealing_walk_or_blended_incumbent() -> None:
    problem = _tiny_placement_problem()
    state = AnnealState.initial(problem.size, 47)
    small_archive = AnnealConfig(
        moves_per_stage=80,
        initial_temperature=1.5,
        final_temperature=0.05,
        elite_count=1,
    )
    large_archive = replace(small_archive, elite_count=12)

    small = anneal_stage(problem, state, small_archive)
    large = anneal_stage(problem, state, large_archive)

    assert small.final_state == large.final_state
    assert small.accepted_moves == large.accepted_moves
    assert small.incumbent == large.incumbent


def test_anneal_stage_advances_once_and_retains_ordered_distinct_elites() -> None:
    problem = _tiny_placement_problem()
    state = AnnealState.initial(problem.size, 29)
    config = AnnealConfig(
        moves_per_stage=80,
        initial_temperature=1.5,
        final_temperature=0.05,
        elite_count=5,
    )

    result = anneal_stage(problem, state, config)

    assert result.final_state.stage_index == state.stage_index + 1
    assert result.final_state.base_seed == state.base_seed
    assert 0 <= result.accepted_moves <= config.moves_per_stage
    assert 1 <= len(result.elites) <= config.elite_count
    assert result.elites == tuple(
        sorted(result.elites, key=lambda elite: (elite.energy, elite.key))
    )
    assert (
        1 <= len(result.archive) <= max(config.elite_count, len(sequence_pair_module.EliteCategory))
    )
    assert len({entry.incumbent.key for entry in result.archive}) == len(result.archive)
    assert result.archive[0].categories[0] is sequence_pair_module.EliteCategory.BLENDED
    assert all(
        entry.categories
        == tuple(
            category
            for category in sequence_pair_module.EliteCategory
            if category in entry.categories
        )
        for entry in result.archive
    )
    assert result.incumbent == result.elites[0]
    result.final_state.pair.validate(problem.size)
    assert all(
        0 <= gap <= 4 for gap in result.final_state.gaps.east + result.final_state.gaps.north
    )


def test_anneal_config_rejects_invalid_schedule_values() -> None:
    invalid_calls: tuple[Callable[[], AnnealConfig], ...] = (
        lambda: AnnealConfig(moves_per_stage=0),
        lambda: AnnealConfig(initial_temperature=0.0),
        lambda: AnnealConfig(final_temperature=0.0),
        lambda: AnnealConfig(initial_temperature=0.5, final_temperature=1.0),
        lambda: AnnealConfig(elite_count=0),
    )
    for call in invalid_calls:
        with pytest.raises(ValueError):
            call()


@pytest.mark.parametrize(
    "move_kinds",
    (
        (),
        (MoveKind.SWAP_POSITIVE, MoveKind.SWAP_POSITIVE),
        (cast(MoveKind, "swap_positive"),),
        cast(tuple[MoveKind, ...], [MoveKind.SWAP_POSITIVE]),
    ),
)
def test_anneal_config_rejects_invalid_move_pools(
    move_kinds: tuple[MoveKind, ...],
) -> None:
    with pytest.raises(ValueError):
        AnnealConfig(move_kinds=move_kinds)


def _lns_failure(
    net: NetId,
    *,
    kind: RouteFailureKind = RouteFailureKind.SEALED_POCKET,
    wall: tuple[tuple[int, int, int], ...] = (),
    blocking_nets: tuple[NetId, ...] = (),
) -> DetailedRouteResult:
    return DetailedRouteResult(
        status=(
            DetailedRouteStatus.BUDGET
            if kind is RouteFailureKind.BUDGET
            else DetailedRouteStatus.STRANDED
        ),
        routed=(),
        failures=(NetFailure(net, kind, wall, blocking_nets, 10),),
        iterations=1,
        expansions=10,
    )


def _lns_geometry(
    size: int,
    *,
    gaps: GapProfile | None = None,
) -> tuple[SequencePair, GapProfile, PlacementProblem, DecodedPlacement]:
    pair = SequencePair(tuple(range(size)), tuple(range(size)))
    profile = gaps or GapProfile.zero(size)
    problem = PlacementProblem(
        sizes=((2, 2),) * size,
        nets=(),
        outline_height=4,
        area_lower_bound=4 * size,
    )
    decoded = decode_sequence_pair(
        pair,
        profile,
        problem.sizes,
        outline_height=problem.outline_height,
    )
    return pair, profile, problem, decoded


def _locked_relative_order(
    pair: SequencePair, locked: frozenset[int]
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    return (
        tuple(strip for strip in pair.positive if strip in locked),
        tuple(strip for strip in pair.negative if strip in locked),
    )


def test_lns_selects_stranded_blocking_endpoints_and_sequence_neighbours() -> None:
    pair, gaps, problem, decoded = _lns_geometry(10)
    stranded = NetId(3, 4, "iron", NetRole.INTERNAL, 0)
    blocker = NetId(7, 7, "copper", NetRole.INTERNAL, 0)

    neighbourhood = select_lns_neighbourhood(
        _lns_failure(stranded, blocking_nets=(blocker,)),
        pair,
        gaps,
        problem,
        decoded,
    )

    assert neighbourhood == frozenset({2, 3, 4, 5, 6, 7, 8})


def test_static_access_lns_selects_failed_and_blocking_endpoint_owners() -> None:
    pair, gaps, problem, decoded = _lns_geometry(10)
    stranded = NetId(3, 4, "proliferator", NetRole.PROLIFERATOR, 0)
    blocker = NetId(7, 7, "proliferator", NetRole.PROLIFERATOR, 1)

    neighbourhood = select_lns_neighbourhood(
        _lns_failure(
            stranded,
            kind=RouteFailureKind.STATIC_ACCESS,
            blocking_nets=(blocker,),
        ),
        pair,
        gaps,
        problem,
        decoded,
    )

    assert neighbourhood == frozenset({2, 3, 4, 5, 6, 7, 8})


def test_lns_selects_only_gap_strips_intersecting_failure_hot_boxes() -> None:
    gaps = GapProfile(
        east=(0, 2, 0),
        north=(0, 0, 0),
    )
    pair, gaps, problem, decoded = _lns_geometry(3, gaps=gaps)
    no_strip_net = NetId(None, None, "iron", NetRole.EXTERNAL, 0)

    neighbourhood = select_lns_neighbourhood(
        _lns_failure(no_strip_net, wall=((5, 1, 0),)),
        pair,
        gaps,
        problem,
        decoded,
    )

    assert neighbourhood == frozenset({1})


def test_budget_failure_creates_no_lns_neighbourhood() -> None:
    pair, gaps, problem, decoded = _lns_geometry(6)
    failure = _lns_failure(
        NetId(2, 3, "iron", NetRole.INTERNAL, 0),
        kind=RouteFailureKind.BUDGET,
        wall=((4, 1, 0),),
        blocking_nets=(NetId(4, 5, "copper", NetRole.INTERNAL, 0),),
    )

    assert (
        select_lns_neighbourhood(
            failure,
            pair,
            gaps,
            problem,
            decoded,
            stagnation=100,
            grow_after=2,
        )
        == frozenset()
    )


def test_lns_neighbourhood_grows_one_sequence_ring_after_stagnation() -> None:
    pair, gaps, problem, decoded = _lns_geometry(8)
    failure = _lns_failure(NetId(3, 3, "iron", NetRole.INTERNAL, 0))

    focused = select_lns_neighbourhood(
        failure, pair, gaps, problem, decoded, stagnation=0, grow_after=2
    )
    grown = select_lns_neighbourhood(
        failure, pair, gaps, problem, decoded, stagnation=2, grow_after=2
    )
    long_stagnation = select_lns_neighbourhood(
        failure, pair, gaps, problem, decoded, stagnation=200, grow_after=2
    )

    assert focused == frozenset({2, 3, 4})
    assert grown == frozenset({1, 2, 3, 4, 5})
    assert long_stagnation == grown


def test_lns_repair_preserves_exact_locked_order_and_locked_gaps() -> None:
    pair = SequencePair(tuple(range(8)), tuple(range(8)))
    gaps = GapProfile(
        east=(0, 1, 2, 3, 4, 3, 2, 1),
        north=(1, 2, 3, 4, 3, 2, 1, 0),
    )
    neighbourhood = frozenset({3, 4})
    locked = frozenset({0, 1, 2, 5, 6, 7})

    repaired = repair_neighbourhood(
        pair, gaps, neighbourhood, seed=9, strip_weights={3: 5.0, 4: 1.0}
    )

    assert _locked_relative_order(repaired.pair, locked) == _locked_relative_order(pair, locked)
    assert tuple(repaired.gaps.east[index] for index in locked) == tuple(
        gaps.east[index] for index in locked
    )
    assert tuple(repaired.gaps.north[index] for index in locked) == tuple(
        gaps.north[index] for index in locked
    )
    assert all(0 <= gap <= 4 for gap in repaired.gaps.east + repaired.gaps.north)


def test_lns_repair_is_deterministic_for_seed_and_weights() -> None:
    pair = SequencePair(tuple(range(8)), tuple(reversed(range(8))))
    gaps = GapProfile.zero(8)
    neighbourhood = frozenset({2, 3, 4, 5})
    weights = {2: 1.0, 3: 2.0, 4: 4.0, 5: 8.0}

    first = repair_neighbourhood(pair, gaps, neighbourhood, seed=91, strip_weights=weights)
    second = repair_neighbourhood(pair, gaps, neighbourhood, seed=91, strip_weights=weights)

    assert first == second
    first.pair.validate(8)
    assert first != repair_neighbourhood(
        pair,
        gaps,
        neighbourhood,
        seed=91,
        strip_weights={2: 8.0, 3: 4.0, 4: 2.0, 5: 1.0},
    )
