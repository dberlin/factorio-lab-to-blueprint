from __future__ import annotations

import hashlib
import pickle
import random
import struct
from array import array
from collections.abc import Iterator
from dataclasses import replace
from typing import cast

import pytest

import flab2bp.layout.sequence_kernel as sequence_kernel_module
from flab2bp.bench.corpus import entry
from flab2bp.lab.data import load_vendored
from flab2bp.lab.url import parse_url
from flab2bp.layout._sequence_kernel import decode_score
from flab2bp.layout.freeform import (
    _box,
    _candidate_heights,
    _direct_alignment_targets,
    _direct_net_candidates,
    _greedy_pack,
    plan_strips,
)
from flab2bp.layout.route_feedback import FeedbackState, feedback_cost_context
from flab2bp.layout.sequence_kernel import (
    CompiledSequenceKernel,
    PythonSequenceKernel,
    SequenceKernel,
    build_sequence_kernel,
    compiled_backend_available,
)
from flab2bp.layout.sequence_pair import (
    AnnealConfig,
    AnnealIncumbent,
    AnnealState,
    DirectInsertTarget,
    GapProfile,
    PlacementCostContext,
    PlacementProblem,
    SequencePair,
    anneal_stage,
    derive_stage_seed,
)
from flab2bp.layout.sequence_solver import (
    SequenceSolverConfig,
    _placement_nets,
    _variant_search_inputs,
)
from flab2bp.rates.candidates import build_candidates

_REFINERY_URL = (
    "https://factoriolab.github.io/dsp/list?z="
    "eJxFyrEKwkAQRdG.meJVM0GxmuYtxk4SQXFbdRGJSyCgaDPfLqJod7jc0XmGqYzO"
    "I2ZzBezt598LNPrlDs3vyLBPLo5WqhMq1TNULofilKk8vEPGCQNu4BrcgntwCF6R"
    "2kgrpD7SRmqdPAdjGb3c3ewFUJ8mgA__&v=11"
)


def _assert_exact(actual: AnnealIncumbent, expected: AnnealIncumbent) -> None:
    assert actual == expected
    assert struct.pack(
        "=ddd",
        actual.breakdown.weighted_hpwl,
        actual.breakdown.history_cost,
        actual.energy.scalar,
    ) == struct.pack(
        "=ddd",
        expected.breakdown.weighted_hpwl,
        expected.breakdown.history_cost,
        expected.energy.scalar,
    )


def _stage_digest(stage: object) -> bytes:
    return hashlib.sha256(pickle.dumps(stage, protocol=5)).digest()


def _real_case(name: str) -> tuple[PlacementProblem, AnnealState, PlacementCostContext]:
    if name == "refinery14":
        spec = build_candidates(load_vendored(), parse_url(_REFINERY_URL), count=3).candidates[2]
    elif name == "quantum40":
        quantum = entry("quantum-chip")
        spec = build_candidates(load_vendored(), parse_url(quantum.url), count=1).candidates[0]
    else:
        raise AssertionError(name)

    strips = plan_strips(spec, strip_len=6)
    seeds = {height: _greedy_pack(strips, height) for height in _candidate_heights(strips)}
    height = min(
        seeds,
        key=lambda candidate_height: (seeds[candidate_height].width, candidate_height),
    )
    instance_ids, variant_tables = _variant_search_inputs(spec, strips, strip_len=6)
    sizes = tuple(_box(strip) for strip in strips)
    placement_nets = _placement_nets(strips)
    problem = PlacementProblem(
        sizes=sizes,
        nets=tuple(endpoints for endpoints, _logical in placement_nets),
        outline_height=height,
        area_lower_bound=sum(
            min(
                (variant.box_width + sizes[strip][0] - variants[0].box_width)
                * (variant.box_height + sizes[strip][1] - variants[0].box_height)
                for variant in variants
            )
            for strip, variants in enumerate(variant_tables)
        ),
        instance_ids=instance_ids,
        logical_net_ids=tuple(logical for _endpoints, logical in placement_nets),
        variant_tables=variant_tables,
    )
    config = SequenceSolverConfig()
    height_seed = derive_stage_seed(config.seed, 0)
    state = AnnealState.initial(problem.size, derive_stage_seed(height_seed, 0))
    targets = _direct_alignment_targets(_direct_net_candidates(strips, spec))
    feedback_width = (
        sum(max(variant.box_width for variant in table) for table in variant_tables)
        + 4 * problem.size
    )
    context = feedback_cost_context(
        FeedbackState.empty((feedback_width, height)),
        problem,
        targets,
    )
    return problem, state, context


def _generated_cases(
    count: int = 384, seed: int = 90210
) -> Iterator[tuple[PlacementProblem, AnnealState, PlacementCostContext]]:
    rng = random.Random(seed)
    for _index in range(count):
        size = rng.randint(1, 40)
        positive = list(range(size))
        negative = list(range(size))
        rng.shuffle(positive)
        rng.shuffle(negative)
        sizes = tuple((rng.randint(1, 12), rng.randint(1, 12)) for _ in range(size))
        east = tuple(rng.randrange(5) for _ in range(size))
        north = tuple(rng.randrange(5) for _ in range(size))
        net_count = rng.randint(0, max(1, size * 2))
        nets = tuple((rng.randrange(size), rng.randrange(size)) for _ in range(net_count))
        outline_height = rng.randint(1, max(1, sum(height for _width, height in sizes)))
        history_width = rng.randint(1, max(1, sum(width for width, _height in sizes) // 2))
        cells = [
            [rng.random() if rng.random() < 0.08 else 0.0 for _ in range(history_width)]
            for _ in range(outline_height)
        ]
        table = [0.0] * ((history_width + 1) * (outline_height + 1))
        stride = history_width + 1
        for y in range(1, outline_height + 1):
            running = 0.0
            for x in range(1, history_width + 1):
                running += cells[y - 1][x - 1]
                table[y * stride + x] = running + table[(y - 1) * stride + x]
        targets: list[DirectInsertTarget] = []
        for ordinal in range(rng.randint(0, min(5, max(0, size - 1)))):
            producer = rng.randrange(size)
            consumer = rng.randrange(size - 1) if size > 1 else producer
            if size > 1 and consumer >= producer:
                consumer += 1
            producer_width, producer_height = sizes[producer]
            consumer_width, consumer_height = sizes[consumer]
            targets.append(
                DirectInsertTarget(
                    key=(producer, ordinal),
                    producer=producer,
                    consumer=consumer,
                    producer_row=rng.randrange(producer_height),
                    consumer_row=rng.randrange(consumer_height),
                    producer_span=rng.randint(1, producer_width),
                    consumer_span=rng.randint(1, consumer_width),
                )
            )
        problem = PlacementProblem(
            sizes=sizes,
            nets=nets,
            outline_height=outline_height,
            area_lower_bound=sum(width * height for width, height in sizes),
        )
        state = AnnealState(
            pair=SequencePair(tuple(positive), tuple(negative)),
            gaps=GapProfile(east, north),
            base_seed=0,
            variant_indices=(0,) * size,
        )
        context = PlacementCostContext(
            net_weights=tuple(rng.random() * 8.0 for _ in nets),
            net_pairs=nets,
            history_outline=(history_width, outline_height),
            history_summed_area=tuple(table),
            direct_targets=tuple(targets),
        )
        yield problem, state, context


def test_compiled_decode_score_returns_coordinate_workspace_arrays() -> None:
    earliest_x = array("q", [0])
    earliest_y = array("q", [0])
    latest_x = array("q", [0])
    latest_y = array("q", [0])

    result = decode_score(
        array("q", [0]),
        array("q", [0]),
        array("q", [0]),
        array("q", [0]),
        array("q", [1, 1]),
        array("q"),
        array("d"),
        array("d", [0.0, 0.0]),
        array("q"),
        array("q", [0]),
        bytearray(1),
        bytearray(1),
        earliest_x,
        earliest_y,
        latest_x,
        latest_y,
        1,
        0,
        6,
    )

    coordinates = result[:4]
    assert all(type(values) is array and values.typecode == "q" for values in coordinates)
    assert all(
        actual is expected
        for actual, expected in zip(
            coordinates,
            (earliest_x, earliest_y, latest_x, latest_y),
            strict=True,
        )
    )


def test_backend_selection_uses_aot_extension() -> None:
    problem = PlacementProblem(((1, 1),), (), 1, 1)
    context = PlacementCostContext((), (), (0, 1), (0.0, 0.0))

    kernel = build_sequence_kernel(problem, context)

    assert compiled_backend_available()
    assert isinstance(kernel, SequenceKernel)
    assert isinstance(kernel, CompiledSequenceKernel)
    assert kernel.backend == "cython"


def test_backend_selection_falls_back_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    problem = PlacementProblem(
        sizes=((2, 1), (1, 2), (2, 2)),
        nets=((0, 1), (1, 2)),
        outline_height=4,
        area_lower_bound=10,
    )
    context = PlacementCostContext(
        net_weights=(1.0, 2.0),
        net_pairs=problem.nets,
        history_outline=(0, 4),
        history_summed_area=(0.0,) * 5,
    )
    state = AnnealState.initial(problem.size, 17)
    config = AnnealConfig(
        moves_per_stage=24,
        initial_temperature=1.0,
        final_temperature=0.05,
        elite_count=4,
    )
    compiled_stage = anneal_stage(problem, state, config, context)
    assert compiled_stage.backend == "cython"
    monkeypatch.setattr(sequence_kernel_module, "_compiled_decode_score", None)

    kernel = build_sequence_kernel(problem, context)

    assert not compiled_backend_available()
    assert isinstance(kernel, SequenceKernel)
    assert isinstance(kernel, PythonSequenceKernel)
    assert kernel.backend == "python"
    _assert_exact(
        kernel.score_state(state),
        PythonSequenceKernel(problem, context).score_state(state),
    )
    fallback_stage = anneal_stage(problem, state, config, context)
    assert fallback_stage.backend == "python"
    assert fallback_stage == compiled_stage


def test_catastrophic_scale_hpwl_is_bit_exact_for_scores_and_full_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = (0, 1, 2, 3)
    problem = PlacementProblem(
        sizes=((1, 1),) * 4,
        nets=((0, 1), (1, 2), (2, 3)),
        outline_height=1,
        area_lower_bound=4,
    )
    context = PlacementCostContext(
        net_weights=(1e16, 1.0, 1.0),
        net_pairs=problem.nets,
        history_outline=(0, 1),
        history_summed_area=(0.0, 0.0),
    )
    state = AnnealState(
        pair=SequencePair(order, order),
        gaps=GapProfile.zero(4),
        base_seed=9007199254740993,
        variant_indices=(0,) * 4,
    )

    expected = PythonSequenceKernel(problem, context).score_state(state)
    actual = CompiledSequenceKernel(problem, context).score_state(state)
    expected_hpwl = sum((1e16, 1.0, 1.0))

    assert struct.pack("=d", expected.breakdown.weighted_hpwl) == struct.pack("=d", expected_hpwl)
    assert struct.pack("=d", actual.breakdown.weighted_hpwl) == struct.pack("=d", expected_hpwl)
    _assert_exact(actual, expected)

    config = AnnealConfig(
        moves_per_stage=48,
        initial_temperature=1.0,
        final_temperature=0.05,
        elite_count=4,
    )
    compiled_stage = anneal_stage(problem, state, config, context)
    monkeypatch.setattr(sequence_kernel_module, "_compiled_decode_score", None)
    python_stage = anneal_stage(problem, state, config, context)

    assert compiled_stage.backend == "cython"
    assert python_stage.backend == "python"
    assert _stage_digest(replace(compiled_stage, backend="python")) == _stage_digest(python_stage)


def test_backend_selection_falls_back_before_signed_64_geometry_overflow() -> None:
    maximum = 2**63 - 1
    problem = PlacementProblem(
        sizes=((maximum, 1), (1, 1)),
        nets=(),
        outline_height=1,
        area_lower_bound=maximum + 1,
    )
    context = PlacementCostContext((), (), (0, 1), (0.0, 0.0))
    state = AnnealState(
        pair=SequencePair((0, 1), (0, 1)),
        gaps=GapProfile.zero(2),
        base_seed=0,
        variant_indices=(0, 0),
    )

    kernel = build_sequence_kernel(problem, context)

    assert isinstance(kernel, PythonSequenceKernel)
    assert kernel.score_state(state).decoded.width == 2**63


def test_backend_selection_falls_back_for_non_float_score_inputs() -> None:
    problem = PlacementProblem(
        sizes=((1, 1), (1, 1)),
        nets=((0, 1),),
        outline_height=1,
        area_lower_bound=2,
    )
    integer_weight = PlacementCostContext(
        net_weights=cast(tuple[float, ...], (2**53 + 1,)),
        net_pairs=problem.nets,
        history_outline=(0, 1),
        history_summed_area=(0.0, 0.0),
    )
    integer_history = PlacementCostContext(
        net_weights=(1.0,),
        net_pairs=problem.nets,
        history_outline=(1, 1),
        history_summed_area=cast(tuple[float, ...], (0, 0, 0, 0)),
    )

    assert isinstance(build_sequence_kernel(problem, integer_weight), PythonSequenceKernel)
    assert isinstance(build_sequence_kernel(problem, integer_history), PythonSequenceKernel)


def test_compiled_kernel_reuses_size_dependent_workspace() -> None:
    problem = PlacementProblem(
        sizes=((2, 1), (1, 2), (2, 2)),
        nets=((0, 1), (1, 2)),
        outline_height=4,
        area_lower_bound=10,
    )
    context = PlacementCostContext(
        net_weights=(1.0, 2.0),
        net_pairs=problem.nets,
        history_outline=(0, 4),
        history_summed_area=(0.0,) * 5,
    )
    kernel = CompiledSequenceKernel(problem, context)
    workspace = kernel._workspace_buffers
    identities = tuple(id(buffer) for buffer in workspace)

    kernel.score_state(AnnealState.initial(problem.size, 17))
    kernel.score_state(AnnealState.initial(problem.size, 23))

    assert kernel._workspace_buffers is workspace
    assert tuple(id(buffer) for buffer in kernel._workspace_buffers) == identities


@pytest.mark.slow
def test_compiled_kernel_is_bit_exact_on_real_and_generated_corpus() -> None:
    cases = (
        _real_case("refinery14"),
        _real_case("quantum40"),
        *_generated_cases(),
    )
    assert len(cases) == 386
    for problem, state, context in cases:
        direct_targets = tuple(reversed(context.direct_targets))
        expected = PythonSequenceKernel(problem, context).score_state(
            state,
            direct_targets=direct_targets,
        )
        actual = CompiledSequenceKernel(problem, context).score_state(
            state,
            direct_targets=direct_targets,
        )
        _assert_exact(actual, expected)
