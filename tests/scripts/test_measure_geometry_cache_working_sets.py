from scripts.measure_geometry_cache_working_sets import lru_hits, recommended_maxsize


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
