from __future__ import annotations

from collections.abc import Callable

import pytest

from flab2bp.layout import geometry_memo
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.freeform import (
    _greedy_pack,
    _height_seed,
    _prepare_routing_problem,
    _StagedStaticCache,
    plan_strips,
)
from flab2bp.spec import BuildSpec
from tests.layout.test_freeform import (
    captured_output_products_spec,
    plastic_spec,
    two_stage_spec,
)


def test_for_spec_returns_one_cache_per_spec_object() -> None:
    geometry_memo.clear()
    spec = two_stage_spec()
    other = two_stage_spec()

    first = geometry_memo.for_spec(spec)
    again = geometry_memo.for_spec(spec)
    different = geometry_memo.for_spec(other)

    assert isinstance(first, _StagedStaticCache)
    assert again is first
    assert different is not first


def test_registry_evicts_least_recently_used_spec() -> None:
    geometry_memo.clear()
    specs = [two_stage_spec() for _ in range(geometry_memo.MEMO_SPECS_RETAINED + 1)]
    caches = [geometry_memo.for_spec(spec) for spec in specs]

    assert geometry_memo.for_spec(specs[0]) is not caches[0]
    assert geometry_memo.for_spec(specs[-1]) is caches[-1]


@pytest.mark.parametrize(
    "make_spec", [two_stage_spec, plastic_spec, captured_output_products_spec]
)
def test_shared_cache_does_not_change_the_prepared_problem(
    make_spec: Callable[[], BuildSpec],
) -> None:
    geometry_memo.clear()
    spec = make_spec()
    strips = plan_strips(spec, strip_len=6)
    pack = _greedy_pack(strips, _height_seed(strips))
    policy = BandPolicy("portable")

    cold = _prepare_routing_problem(spec, strips, pack, policy=policy, power=True)
    shared = geometry_memo.for_spec(spec)
    warm_first = _prepare_routing_problem(
        spec, strips, pack, policy=policy, power=True, staged_static_cache=shared
    )
    warm_second = _prepare_routing_problem(
        spec, strips, pack, policy=policy, power=True, staged_static_cache=shared
    )

    assert warm_first == cold
    assert warm_second == cold
    stats = geometry_memo.stats_for_spec(spec)
    assert sum(stats.tables.values()) > 0
