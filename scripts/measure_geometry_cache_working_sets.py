"""Measure realistic working sets for the public DSP geometry caches."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NotRequired, Protocol, TypedDict, cast

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from flab2bp.dsp import catalog, colliders, planet  # noqa: E402
from flab2bp.dsp.codec import decode  # noqa: E402
from flab2bp.dsp.envelope import BlueprintFormatError  # noqa: E402

_FUNCTION_NAMES = (
    "catalog.collider_span",
    "catalog.clearance",
    "colliders.own_centre_extent",
    "colliders.belt_keepout_offsets",
    "planet.collider_radius",
)

_ROLLBACK_REASONS = {
    "catalog.clearance": (
        "Repeatable same-machine 21-sample median regression exceeded 5% "
        "in comparison pairs 1 and 2."
    ),
    "colliders.own_centre_extent": (
        "Repeatable same-machine 21-sample median regression exceeded 5% "
        "in comparison pairs 2 and 3."
    ),
    "colliders.belt_keepout_offsets": (
        "Repeatable same-machine 21-sample median regression exceeded 5% "
        "in comparison pairs 1, 2, and 3."
    ),
    "planet.collider_radius": (
        "Repeatable same-machine 21-sample median regression exceeded 5% "
        "in comparison pairs 2 and 3."
    ),
}

type CacheKey = tuple[object, ...]
type FunctionTraces = dict[str, list[CacheKey]]
type CaseTraces = dict[str, FunctionTraces]


class _CacheInfo(Protocol):
    hits: int
    misses: int
    maxsize: int | None
    currsize: int


class _CacheFunction(Protocol):
    def __call__(self, *args: object) -> object: ...
    def cache_clear(self) -> None: ...
    def cache_info(self) -> _CacheInfo: ...


class _CandidateReport(TypedDict):
    maxsize: int
    hits: int
    retained_hit_ratio: float


class _CacheInfoReport(TypedDict):
    hits: int
    misses: int
    maxsize: int | None
    currsize: int


class _FunctionReport(TypedDict):
    calls: int
    distinct_keys: int
    peak_case_distinct: int
    unbounded_hits: int
    candidates: list[_CandidateReport]
    recommended_maxsize: int
    applied_maxsize: int | None
    rollback_reason: str | None
    samples: NotRequired[int]
    median_seconds: NotRequired[float]
    cache_info: NotRequired[_CacheInfoReport]


class _Report(TypedDict):
    skipped_blueprints: list[str]
    functions: dict[str, _FunctionReport]


_FUNCTIONS: dict[str, _CacheFunction] = {
    "catalog.collider_span": cast(_CacheFunction, cast(object, catalog.collider_span)),
    "catalog.clearance": cast(_CacheFunction, cast(object, catalog.clearance)),
    "colliders.own_centre_extent": cast(
        _CacheFunction, cast(object, colliders.own_centre_extent)
    ),
    "colliders.belt_keepout_offsets": cast(
        _CacheFunction, cast(object, colliders.belt_keepout_offsets)
    ),
    "planet.collider_radius": cast(_CacheFunction, cast(object, planet.collider_radius)),
}


def lru_hits(trace: Sequence[CacheKey], maxsize: int) -> int:
    """Return hits from replaying ``trace`` through a true bounded LRU."""
    if maxsize < 1:
        raise ValueError("maxsize must be at least 1")
    cache: dict[CacheKey, None] = {}
    hits = 0
    for key in trace:
        if key in cache:
            hits += 1
            del cache[key]
            cache[key] = None
            continue
        cache[key] = None
        if len(cache) > maxsize:
            cache.pop(next(iter(cache)))
    return hits


def _powers_of_two_through(cardinality: int) -> list[int]:
    sizes: list[int] = []
    size = 1
    while True:
        sizes.append(size)
        if size >= cardinality:
            return sizes
        size *= 2


def recommended_maxsize(case_traces: list[list[CacheKey]]) -> int:
    """Choose the smallest evidence-backed power-of-two cache bound."""
    peak_case_distinct = max((len(set(trace)) for trace in case_traces), default=1)
    combined = [key for trace in case_traces for key in trace]
    unbounded_hits = len(combined) - len(set(combined))
    for size in _powers_of_two_through(max(len(set(combined)), 1)):
        hits = lru_hits(combined, size)
        retained = 1.0 if unbounded_hits == 0 else hits / unbounded_hits
        if size >= peak_case_distinct and retained >= 0.99:
            return size
    raise AssertionError("candidate range must include an evidence-backed bound")


def _empty_function_traces() -> FunctionTraces:
    return {name: [] for name in _FUNCTION_NAMES}


def _record_catalog_building(
    traces: FunctionTraces,
    *,
    item_id: int,
    yaw: float,
    model_index: int,
) -> None:
    traces["catalog.collider_span"].append((item_id, yaw))
    traces["catalog.clearance"].append((item_id, yaw))
    traces["colliders.own_centre_extent"].append((model_index, yaw))
    traces["colliders.own_centre_extent"].append((model_index, 0.0))


def _object(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object with string keys")
    raw = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in raw):
        raise ValueError(f"{label} must be a JSON object with string keys")
    return cast(dict[str, object], value)


def _array(value: object, *, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a JSON array")
    return cast(list[object], value)


def _integer(value: object, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    return value


def _number(value: object, *, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{label} must be a number")
    return float(value)


def _collect_case_traces(root: Path) -> tuple[CaseTraces, list[str]]:
    cases: CaseTraces = {}
    skipped: list[str] = []
    known_models = {building.item_id: building.model_index for building in catalog.all_buildings()}
    splitter_model = catalog.building(catalog.SPLITTER_ID).model_index

    for path in sorted((root / "tests" / "fixtures").glob("*.txt")):
        case_name = path.relative_to(root).as_posix()
        try:
            blueprint = decode(path.read_text(encoding="utf-8").strip())
        except BlueprintFormatError:
            skipped.append(case_name)
            continue
        traces = _empty_function_traces()
        contains_splitter = False
        for building in blueprint.buildings:
            model_index = known_models.get(building.item_id)
            if model_index is None:
                continue
            _record_catalog_building(
                traces,
                item_id=building.item_id,
                yaw=building.yaw,
                model_index=model_index,
            )
            contains_splitter = contains_splitter or building.item_id == catalog.SPLITTER_ID
        if contains_splitter:
            traces["colliders.belt_keepout_offsets"].append(
                (splitter_model,)
            )
        cases[case_name] = traces

    for path in sorted((root / "tests" / "fixtures" / "projection").glob("*.json")):
        case_name = path.relative_to(root).as_posix()
        decoded = cast(object, json.loads(path.read_text(encoding="utf-8")))
        raw = _object(decoded, label=case_name)
        placement = _object(raw["placement"], label=f"{case_name}.placement")
        buildings = _array(
            placement["buildings"], label=f"{case_name}.placement.buildings"
        )
        traces = _empty_function_traces()
        contains_splitter = False
        for index, value in enumerate(buildings):
            label = f"{case_name}.placement.buildings[{index}]"
            raw_building = _object(value, label=label)
            item_id = _integer(raw_building["item_id"], label=f"{label}.item_id")
            model_index = _integer(
                raw_building["model_index"], label=f"{label}.model_index"
            )
            yaw = _number(raw_building["yaw"], label=f"{label}.yaw")
            known_model = known_models.get(item_id)
            if known_model is not None:
                _record_catalog_building(
                    traces,
                    item_id=item_id,
                    yaw=yaw,
                    model_index=known_model,
                )
                contains_splitter = contains_splitter or item_id == catalog.SPLITTER_ID
            if not catalog.is_belt(item_id) and not catalog.is_sorter(item_id):
                traces["planet.collider_radius"].append((model_index,))
        if contains_splitter:
            traces["colliders.belt_keepout_offsets"].append(
                (splitter_model,)
            )
        cases[case_name] = traces

    return cases, skipped


def collect_case_traces(root: Path) -> CaseTraces:
    """Collect deterministic, case-local traces from all realistic fixtures."""
    cases, _skipped = _collect_case_traces(root)
    return cases


def _function_report(name: str, case_traces: list[list[CacheKey]]) -> _FunctionReport:
    combined = [key for trace in case_traces for key in trace]
    distinct_keys = len(set(combined))
    unbounded_hits = len(combined) - distinct_keys
    candidates = [
        _CandidateReport(
            maxsize=size,
            hits=(hits := lru_hits(combined, size)),
            retained_hit_ratio=(1.0 if unbounded_hits == 0 else hits / unbounded_hits),
        )
        for size in _powers_of_two_through(max(distinct_keys, 1))
    ]
    recommendation = recommended_maxsize(case_traces)
    rollback_reason = _ROLLBACK_REASONS.get(name)
    return _FunctionReport(
        calls=len(combined),
        distinct_keys=distinct_keys,
        peak_case_distinct=max((len(set(trace)) for trace in case_traces), default=0),
        unbounded_hits=unbounded_hits,
        candidates=candidates,
        recommended_maxsize=recommendation,
        applied_maxsize=None if rollback_reason is not None else recommendation,
        rollback_reason=rollback_reason,
    )


def _build_report_and_traces(root: Path) -> tuple[_Report, CaseTraces]:
    cases, skipped = _collect_case_traces(root)
    functions: dict[str, _FunctionReport] = {}
    for name in _FUNCTION_NAMES:
        functions[name] = _function_report(
            name, [case[name] for case in cases.values()]
        )
    return _Report(skipped_blueprints=skipped, functions=functions), cases


def build_report(root: Path) -> _Report:
    """Build the deterministic aggregate working-set report."""
    report, _cases = _build_report_and_traces(root)
    return report


def _clear_all_caches() -> None:
    for function in _FUNCTIONS.values():
        function.cache_clear()


def _add_timings(report: _Report, cases: CaseTraces, samples: int) -> None:
    for name in _FUNCTION_NAMES:
        function = _FUNCTIONS[name]
        trace = [key for case in cases.values() for key in case[name]]
        elapsed: list[float] = []
        info: _CacheInfo | None = None
        for _sample in range(samples):
            _clear_all_caches()
            started = time.perf_counter()
            for key in trace:
                _ = function(*key)
            elapsed.append(time.perf_counter() - started)
            info = function.cache_info()
        assert info is not None
        report["functions"][name]["samples"] = samples
        report["functions"][name]["median_seconds"] = statistics.median(elapsed)
        report["functions"][name]["cache_info"] = _CacheInfoReport(
            hits=info.hits,
            misses=info.misses,
            maxsize=info.maxsize,
            currsize=info.currsize,
        )
    _clear_all_caches()


def _required_mapping(value: object, *, label: str) -> Mapping[str, object]:
    return _object(value, label=label)


def _compare(report: _Report, prior_path: Path) -> list[str]:
    prior_value = cast(object, json.loads(prior_path.read_text(encoding="utf-8")))
    prior = _required_mapping(prior_value, label=str(prior_path))
    prior_functions = _required_mapping(
        prior["functions"], label=f"{prior_path}.functions"
    )
    failures: list[str] = []
    for name in _FUNCTION_NAMES:
        current = report["functions"][name]
        prior_function = _required_mapping(
            prior_functions[name], label=f"{prior_path}.functions.{name}"
        )
        prior_median = prior_function.get("median_seconds")
        if not isinstance(prior_median, (int, float)) or isinstance(prior_median, bool):
            raise ValueError(f"{prior_path}.functions.{name}.median_seconds must be a number")
        current_median = current.get("median_seconds")
        if current_median is None:
            raise ValueError(f"current functions.{name}.median_seconds is required")
        if current_median > float(prior_median) * 1.05:
            failures.append(
                f"{name}: median {current_median:.9f}s exceeds baseline "
                + f"{float(prior_median):.9f}s by more than 5%"
            )
        recommendation = current["recommended_maxsize"]
        selected = next(
            candidate
            for candidate in current["candidates"]
            if candidate["maxsize"] == recommendation
        )
        if selected["retained_hit_ratio"] < 0.99:
            failures.append(
                f"{name}: retained hit ratio {selected['retained_hit_ratio']:.6f} is below 0.99"
            )
        cache_info = current.get("cache_info")
        if cache_info is None:
            raise ValueError(f"current functions.{name}.cache_info is required")
        actual = cache_info["maxsize"]
        applied = current["applied_maxsize"]
        if actual != applied:
            failures.append(
                f"{name}: actual maxsize {actual!r} differs from applied policy {applied!r}"
            )
    return failures


def _write_report(report: _Report, output: Path | None) -> None:
    rendered = json.dumps(report, indent=2) + "\n"
    if output is None:
        print(rendered, end="")
        return
    _ = output.write_text(rendered, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--output", type=Path)
    _ = parser.add_argument("--samples", type=int)
    _ = parser.add_argument("--compare", type=Path)
    args = parser.parse_args(argv)
    samples = cast(int | None, args.samples)
    output = cast(Path | None, args.output)
    compare = cast(Path | None, args.compare)
    if samples is not None and samples < 1:
        parser.error("--samples must be at least 1")
    if compare is not None and samples is None:
        parser.error("--compare requires --samples")

    report, cases = _build_report_and_traces(_ROOT)
    if samples is not None:
        _add_timings(report, cases, samples)
    _write_report(report, output)
    if compare is None:
        return 0
    failures = _compare(report, compare)
    for failure in failures:
        print(failure, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
