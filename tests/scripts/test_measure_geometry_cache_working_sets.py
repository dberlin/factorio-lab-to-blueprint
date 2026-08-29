from pathlib import Path

from scripts.measure_geometry_cache_working_sets import (
    build_report,
    collect_case_traces,
    lru_hits,
    recommended_maxsize,
)


def test_lru_hits_respects_recency_not_insertion_order() -> None:
    trace = [("a",), ("b",), ("a",), ("c",), ("a",), ("b",)]
    assert lru_hits(trace, 2) == 2


def test_recommendation_holds_peak_case_and_retains_observed_hits() -> None:
    cases: list[list[tuple[object, ...]]] = [
        [("a",), ("b",), ("a",)],
        [("c",), ("d",), ("c",)],
    ]
    assert recommended_maxsize(cases) == 2


def test_no_repeat_trace_still_holds_one_complete_case() -> None:
    cases: list[list[tuple[object, ...]]] = [[("a",), ("b",), ("c",)], [("d",)]]
    assert recommended_maxsize(cases) == 4


def test_splitter_trace_uses_the_real_one_argument_cache_key() -> None:
    cases = collect_case_traces(Path(__file__).parents[2])
    keys = [
        key
        for case in cases.values()
        for key in case["colliders.belt_keepout_offsets"]
    ]
    assert keys
    assert all(len(key) == 1 and isinstance(key[0], int) for key in keys)


def test_report_separates_recommendation_from_applied_rollback_policy() -> None:
    functions = build_report(Path(__file__).parents[2])["functions"]
    finite = functions["catalog.collider_span"]
    assert finite["applied_maxsize"] == finite["recommended_maxsize"]
    assert finite["rollback_reason"] is None

    for name in (
        "catalog.clearance",
        "colliders.own_centre_extent",
        "colliders.belt_keepout_offsets",
        "planet.collider_radius",
    ):
        assert functions[name]["recommended_maxsize"] > 0
        assert functions[name]["applied_maxsize"] is None
        assert functions[name]["rollback_reason"]
