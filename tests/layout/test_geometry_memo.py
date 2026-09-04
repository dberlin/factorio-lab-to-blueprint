from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

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


@pytest.mark.parametrize("make_spec", [two_stage_spec, plastic_spec, captured_output_products_spec])
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


def test_for_spec_is_thread_safe_under_concurrent_eviction() -> None:
    """Regression for the unlocked get/move_to_end/evict race.

    A `--workers N` build (`src/flab2bp/web/jobs.py`) calls `for_spec` from
    several threads at once, each with its own spec object. With more
    distinct specs in flight than `MEMO_SPECS_RETAINED`, one thread's `get`
    could previously race another thread's insert-and-evict and raise
    `KeyError` on `move_to_end`. This drives many more calls than distinct
    specs, from several threads, and asserts nothing blows up.
    """
    geometry_memo.clear()
    specs = [two_stage_spec() for _ in range(2 * geometry_memo.MEMO_SPECS_RETAINED)]
    calls = [specs[i % len(specs)] for i in range(300)]

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(geometry_memo.for_spec, calls))

    assert len(results) == len(calls)
    assert all(isinstance(cache, _StagedStaticCache) for cache in results)
