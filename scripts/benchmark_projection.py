"""Benchmark final spherical projection against frozen routed placements."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections.abc import Mapping, Sequence
from fractions import Fraction
from pathlib import Path
from typing import Literal, TypedDict, cast

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from flab2bp.layout import finalize  # noqa: E402
from flab2bp.layout.band_policy import BandPolicy  # noqa: E402
from flab2bp.layout.base import PlacedBuilding, Placement, PlacementStats  # noqa: E402

_FIXTURES = _ROOT / "tests" / "fixtures" / "projection"
_CASES = ("small", "medium", "large")


class CaseResult(TypedDict):
    median_s: float
    p95_s: float
    frame_candidates: int
    projections: int
    collider_pairs: int
    power_pairs: int
    sorters: int
    area: int
    invariant_cache_hits: int
    pair_cache_hits: int
    projection_cache_hits: int
    sorter_result_cache_hits: int
    static_result_cache_hits: int
    power_result_cache_hits: int
    addon_result_cache_hits: int
    addon_splitter_result_cache_hits: int
    refused: bool
    refusal_checks: list[str]


class BenchmarkResult(TypedDict):
    cases: dict[str, CaseResult]


class ProjectionCaseComparison(TypedDict):
    baseline: CaseResult
    after: CaseResult
    median_delta_s: float
    p95_delta_s: float
    p95_threshold_s: float
    threshold_passed: bool


class ProjectionComparison(TypedDict):
    passed: bool
    cases: dict[str, ProjectionCaseComparison]


class BuildCaseIdentity(TypedDict):
    strategy: str
    url_id: str
    spec_index: int
    spec_label: str
    power: bool
    budget: float


class BuildMetrics(TypedDict):
    build_wall_time_s: float
    status: str
    area: float
    projection_frame_candidates: int
    projection_count: int
    projection_collider_pairs: int
    projection_power_pairs: int
    projection_sorters: int


type BuildGateKind = Literal["audit_deadline_grace"]


class BuildCaseComparison(TypedDict):
    case: BuildCaseIdentity
    baseline: BuildMetrics
    after: BuildMetrics
    wall_time_delta_s: float
    wall_time_delta_ratio: float
    wall_time_delta_percent: float
    wall_time_threshold_ratio: float
    historical_regression: bool
    gate_kind: BuildGateKind
    semantic_change_reasons: list[str]
    governing_limit_s: float
    measured_wall_s: float
    gate_passed: bool


class BuildComparison(TypedDict):
    passed: bool
    cases: list[BuildCaseComparison]


class BenchmarkAfterResult(BenchmarkResult):
    projection_comparison: ProjectionComparison


class GateThresholds(TypedDict):
    projection_added_p95_s: float
    build_wall_time_ratio: float
    build_atomic_completion_grace_s: float


class ComparisonResult(TypedDict):
    passed: bool
    thresholds: GateThresholds
    projection: ProjectionComparison
    builds: BuildComparison


_PROJECTION_P95_THRESHOLD_S = 1.0
_BUILD_WALL_TIME_THRESHOLD_RATIO = 0.1
# Product gate for finishing the one atomic candidate already in flight after a
# single-island search deadline, including scheduler variance on loaded machines.
# This is neither audit.py's reporting-only slow threshold nor
# sequence_islands.py's multi-island process completion grace.
_BUILD_ATOMIC_COMPLETION_GRACE_S = 5.0
_BUILD_COUNTERS = (
    "projection_frame_candidates",
    "projection_count",
    "projection_collider_pairs",
    "projection_power_pairs",
    "projection_sorters",
)
_BuildKey = tuple[str, str, int, str, bool, float]


def _object(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return cast(dict[str, object], value)


def _integer(value: object, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    return value


def _optional_integer(value: object, *, label: str) -> int | None:
    if value is None:
        return None
    return _integer(value, label=label)


def _number(value: object, *, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{label} must be a number")
    return float(value)


def _optional_number(value: object, *, label: str) -> float | None:
    if value is None:
        return None
    return _number(value, label=label)


def _boolean(value: object, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def _fraction(value: object, *, label: str) -> Fraction:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a rational string")
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"{label} must be a rational string") from exc


def _optional_fraction(value: object, *, label: str) -> Fraction | None:
    if value is None:
        return None
    return _fraction(value, label=label)


def _case_result(value: object, *, label: str) -> CaseResult:
    raw = _object(value, label=label)
    refusal_checks_raw = raw.get("refusal_checks", [])
    if not isinstance(refusal_checks_raw, list) or not all(
        isinstance(check, str) for check in refusal_checks_raw
    ):
        raise ValueError(f"{label}.refusal_checks must be an array of strings")
    return CaseResult(
        median_s=_number(raw["median_s"], label=f"{label}.median_s"),
        p95_s=_number(raw["p95_s"], label=f"{label}.p95_s"),
        frame_candidates=_integer(raw["frame_candidates"], label=f"{label}.frame_candidates"),
        projections=_integer(raw["projections"], label=f"{label}.projections"),
        collider_pairs=_integer(raw["collider_pairs"], label=f"{label}.collider_pairs"),
        power_pairs=_integer(raw["power_pairs"], label=f"{label}.power_pairs"),
        sorters=_integer(raw["sorters"], label=f"{label}.sorters"),
        area=_integer(raw["area"], label=f"{label}.area"),
        invariant_cache_hits=_integer(
            raw.get("invariant_cache_hits", 0),
            label=f"{label}.invariant_cache_hits",
        ),
        pair_cache_hits=_integer(
            raw.get("pair_cache_hits", 0),
            label=f"{label}.pair_cache_hits",
        ),
        projection_cache_hits=_integer(
            raw.get("projection_cache_hits", 0),
            label=f"{label}.projection_cache_hits",
        ),
        sorter_result_cache_hits=_integer(
            raw.get("sorter_result_cache_hits", 0),
            label=f"{label}.sorter_result_cache_hits",
        ),
        static_result_cache_hits=_integer(
            raw.get("static_result_cache_hits", 0),
            label=f"{label}.static_result_cache_hits",
        ),
        power_result_cache_hits=_integer(
            raw.get("power_result_cache_hits", 0),
            label=f"{label}.power_result_cache_hits",
        ),
        addon_result_cache_hits=_integer(
            raw.get("addon_result_cache_hits", 0),
            label=f"{label}.addon_result_cache_hits",
        ),
        addon_splitter_result_cache_hits=_integer(
            raw.get("addon_splitter_result_cache_hits", 0),
            label=f"{label}.addon_splitter_result_cache_hits",
        ),
        refused=_boolean(raw.get("refused", False), label=f"{label}.refused"),
        refusal_checks=cast(list[str], refusal_checks_raw),
    )


def _benchmark_result(value: object, *, label: str) -> BenchmarkResult:
    raw = _object(value, label=label)
    cases = _object(raw["cases"], label=f"{label}.cases")
    return BenchmarkResult(
        cases={
            name: _case_result(case, label=f"{label}.cases.{name}") for name, case in cases.items()
        }
    )


def _string(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    return value


def _building(value: object, *, index: int) -> PlacedBuilding:
    raw = _object(value, label=f"building {index}")
    prefix = f"building {index}"
    parameters = raw["parameters"]
    if not isinstance(parameters, list):
        raise ValueError(f"{prefix}.parameters must be an array")
    parameter_values = cast(list[object], parameters)
    carries_item = raw["carries_item"]
    if carries_item is not None and not isinstance(carries_item, str):
        raise ValueError(f"{prefix}.carries_item must be a string or null")
    return PlacedBuilding(
        item_id=_integer(raw["item_id"], label=f"{prefix}.item_id"),
        model_index=_integer(raw["model_index"], label=f"{prefix}.model_index"),
        x=_integer(raw["x"], label=f"{prefix}.x"),
        y=_integer(raw["y"], label=f"{prefix}.y"),
        z=_fraction(raw["z"], label=f"{prefix}.z"),
        width=_integer(raw["width"], label=f"{prefix}.width"),
        height=_integer(raw["height"], label=f"{prefix}.height"),
        yaw=_number(raw["yaw"], label=f"{prefix}.yaw"),
        x2=_optional_integer(raw["x2"], label=f"{prefix}.x2"),
        y2=_optional_integer(raw["y2"], label=f"{prefix}.y2"),
        z2=_optional_fraction(raw["z2"], label=f"{prefix}.z2"),
        yaw2=_optional_number(raw["yaw2"], label=f"{prefix}.yaw2"),
        recipe_id=_integer(raw["recipe_id"], label=f"{prefix}.recipe_id"),
        filter_id=_integer(raw["filter_id"], label=f"{prefix}.filter_id"),
        output_obj=_optional_integer(raw["output_obj"], label=f"{prefix}.output_obj"),
        input_obj=_optional_integer(raw["input_obj"], label=f"{prefix}.input_obj"),
        output_to_slot=_integer(raw["output_to_slot"], label=f"{prefix}.output_to_slot"),
        input_from_slot=_integer(raw["input_from_slot"], label=f"{prefix}.input_from_slot"),
        output_from_slot=_integer(raw["output_from_slot"], label=f"{prefix}.output_from_slot"),
        input_to_slot=_integer(raw["input_to_slot"], label=f"{prefix}.input_to_slot"),
        output_offset=_integer(raw["output_offset"], label=f"{prefix}.output_offset"),
        input_offset=_integer(raw["input_offset"], label=f"{prefix}.input_offset"),
        parameters=tuple(
            _integer(parameter, label=f"{prefix}.parameters") for parameter in parameter_values
        ),
        carries_item=carries_item,
    )


def _load_case(name: str) -> Placement:
    if name not in _CASES:
        raise ValueError(f"unknown benchmark case: {name}")
    decoded = cast(
        object,
        json.loads((_FIXTURES / f"{name}.json").read_text(encoding="utf-8")),
    )
    raw = _object(decoded, label=name)
    placement = _object(raw["placement"], label=f"{name}.placement")
    buildings = placement["buildings"]
    icons = placement["icons"]
    stats = placement["stats"]
    if not isinstance(buildings, list):
        raise ValueError(f"{name}.placement.buildings must be an array")
    if not isinstance(icons, list):
        raise ValueError(f"{name}.placement.icons must be an array")
    if not isinstance(stats, dict):
        raise ValueError(f"{name}.placement.stats must be an object")
    building_values = cast(list[object], buildings)
    icon_values = cast(list[object], icons)
    numeric_stats: dict[str, float] = {}
    for key, value in cast(dict[object, object], stats).items():
        if not isinstance(key, str):
            raise ValueError(f"{name}.placement.stats keys must be strings")
        numeric_stats[key] = _number(value, label=f"{name}.placement.stats.{key}")
    return Placement(
        buildings=tuple(
            _building(building, index=index) for index, building in enumerate(building_values)
        ),
        description=_string(placement["description"], label=f"{name}.placement.description"),
        short_desc=_string(placement["short_desc"], label=f"{name}.placement.short_desc"),
        icons=tuple(_integer(icon, label=f"{name}.placement.icons") for icon in icon_values),
        stats=cast(PlacementStats, cast(object, numeric_stats)),
    )


def _refusal_counters(placement: Placement) -> finalize._ProjectionCounters:
    counters = finalize._ProjectionCounters()
    cache = finalize._ProjectionCache(counters)
    for candidate in finalize.frame_candidates(placement, BandPolicy("portable")):
        counters.frame_candidates += 1
        framed = finalize._materialize_frame(placement, candidate)
        if not finalize._certify_frame(
            framed,
            candidate.frame,
            counters,
            cache=cache,
        ):
            break
    return counters


def _time_case(placement: Placement, samples: int) -> CaseResult:
    if samples < 1:
        raise ValueError("samples must be at least 1")
    elapsed: list[float] = []
    finalized: Placement | None = None
    refusal: finalize.ProjectionRefusal | None = None
    for _ in range(samples):
        started = time.perf_counter_ns()
        try:
            finalized = finalize.finalize_placement(placement, BandPolicy("portable"))
        except finalize.ProjectionRefusal as exc:
            refusal = exc
        elapsed.append((time.perf_counter_ns() - started) / 1_000_000_000)
    ordered = sorted(elapsed)
    p95 = ordered[math.ceil(0.95 * len(ordered)) - 1]
    if finalized is None:
        assert refusal is not None
        counters = _refusal_counters(placement)
        return CaseResult(
            median_s=statistics.median(ordered),
            p95_s=p95,
            frame_candidates=counters.frame_candidates,
            projections=counters.projections,
            collider_pairs=counters.collider_pairs,
            power_pairs=counters.power_pairs,
            sorters=counters.sorters,
            area=placement.area,
            invariant_cache_hits=counters.invariant_cache_hits,
            pair_cache_hits=counters.pair_cache_hits,
            projection_cache_hits=counters.projection_cache_hits,
            sorter_result_cache_hits=counters.sorter_result_cache_hits,
            static_result_cache_hits=counters.static_result_cache_hits,
            power_result_cache_hits=counters.power_result_cache_hits,
            addon_result_cache_hits=counters.addon_result_cache_hits,
            addon_splitter_result_cache_hits=counters.addon_splitter_result_cache_hits,
            refused=True,
            refusal_checks=list(refusal.checks),
        )
    return CaseResult(
        median_s=statistics.median(ordered),
        p95_s=p95,
        frame_candidates=int(finalized.stats.get("projection_frame_candidates", 0)),
        projections=int(finalized.stats.get("projection_count", 0)),
        collider_pairs=int(finalized.stats.get("projection_collider_pairs", 0)),
        power_pairs=int(finalized.stats.get("projection_power_pairs", 0)),
        sorters=int(finalized.stats.get("projection_sorters", 0)),
        area=finalized.area,
        invariant_cache_hits=cast(
            int,
            finalized.stats.get("projection_invariant_cache_hits", 0),
        ),
        pair_cache_hits=cast(
            int,
            finalized.stats.get("projection_pair_cache_hits", 0),
        ),
        projection_cache_hits=cast(
            int,
            finalized.stats.get("projection_object_cache_hits", 0),
        ),
        sorter_result_cache_hits=cast(
            int,
            finalized.stats.get("projection_sorter_result_cache_hits", 0),
        ),
        static_result_cache_hits=cast(
            int,
            finalized.stats.get("projection_static_result_cache_hits", 0),
        ),
        power_result_cache_hits=cast(
            int,
            finalized.stats.get("projection_power_result_cache_hits", 0),
        ),
        addon_result_cache_hits=cast(
            int,
            finalized.stats.get("projection_addon_result_cache_hits", 0),
        ),
        addon_splitter_result_cache_hits=cast(
            int,
            finalized.stats.get("projection_addon_splitter_result_cache_hits", 0),
        ),
        refused=False,
        refusal_checks=[],
    )


def run_benchmark(samples: int) -> BenchmarkResult:
    if samples < 1:
        raise ValueError("samples must be at least 1")
    placements = {name: _load_case(name) for name in _CASES}
    return BenchmarkResult(
        cases={name: _time_case(placement, samples) for name, placement in placements.items()}
    )


def compare_projection_results(
    baseline: BenchmarkResult,
    after: BenchmarkResult,
) -> ProjectionComparison:
    baseline_names = set(baseline["cases"])
    after_names = set(after["cases"])
    if baseline_names != after_names:
        raise ValueError(
            "projection cases differ: "
            f"baseline-only={sorted(baseline_names - after_names)}, "
            f"after-only={sorted(after_names - baseline_names)}"
        )
    cases: dict[str, ProjectionCaseComparison] = {}
    for name, baseline_case in baseline["cases"].items():
        after_case = after["cases"][name]
        p95_delta = after_case["p95_s"] - baseline_case["p95_s"]
        cases[name] = ProjectionCaseComparison(
            baseline=baseline_case,
            after=after_case,
            median_delta_s=after_case["median_s"] - baseline_case["median_s"],
            p95_delta_s=p95_delta,
            p95_threshold_s=_PROJECTION_P95_THRESHOLD_S,
            threshold_passed=p95_delta <= _PROJECTION_P95_THRESHOLD_S,
        )
    return ProjectionComparison(
        passed=all(case["threshold_passed"] for case in cases.values()),
        cases=cases,
    )


def _build_identity(
    record: Mapping[str, object],
    *,
    label: str,
) -> tuple[_BuildKey, BuildCaseIdentity]:
    identity = BuildCaseIdentity(
        strategy=_string(record["strategy"], label=f"{label}.strategy"),
        url_id=_string(record["url_id"], label=f"{label}.url_id"),
        spec_index=_integer(record["spec_index"], label=f"{label}.spec_index"),
        spec_label=_string(record["spec_label"], label=f"{label}.spec_label"),
        power=_boolean(record["power"], label=f"{label}.power"),
        budget=_number(record["budget"], label=f"{label}.budget"),
    )
    key = (
        identity["strategy"],
        identity["url_id"],
        identity["spec_index"],
        identity["spec_label"],
        identity["power"],
        identity["budget"],
    )
    return key, identity


def _build_metrics(record: Mapping[str, object], *, label: str) -> BuildMetrics:
    return BuildMetrics(
        status=_string(record["status"], label=f"{label}.status"),
        build_wall_time_s=_number(
            record["build_wall_time_s"],
            label=f"{label}.build_wall_time_s",
        ),
        area=_number(record["area"], label=f"{label}.area"),
        projection_frame_candidates=_integer(
            record["projection_frame_candidates"],
            label=f"{label}.projection_frame_candidates",
        ),
        projection_count=_integer(
            record["projection_count"],
            label=f"{label}.projection_count",
        ),
        projection_collider_pairs=_integer(
            record["projection_collider_pairs"],
            label=f"{label}.projection_collider_pairs",
        ),
        projection_power_pairs=_integer(
            record["projection_power_pairs"],
            label=f"{label}.projection_power_pairs",
        ),
        projection_sorters=_integer(
            record["projection_sorters"],
            label=f"{label}.projection_sorters",
        ),
    )


def _index_build_records(
    records: Sequence[Mapping[str, object]],
    *,
    label: str,
) -> tuple[list[_BuildKey], dict[_BuildKey, tuple[BuildCaseIdentity, BuildMetrics]]]:
    order: list[_BuildKey] = []
    indexed: dict[_BuildKey, tuple[BuildCaseIdentity, BuildMetrics]] = {}
    for index, record in enumerate(records):
        record_label = f"{label}[{index}]"
        key, identity = _build_identity(record, label=record_label)
        if key in indexed:
            raise ValueError(f"{record_label} duplicates build case {identity}")
        order.append(key)
        indexed[key] = (identity, _build_metrics(record, label=record_label))
    return order, indexed


def compare_build_results(
    baseline: Sequence[Mapping[str, object]],
    after: Sequence[Mapping[str, object]],
) -> BuildComparison:
    order, baseline_cases = _index_build_records(baseline, label="baseline")
    _, after_cases = _index_build_records(after, label="after")
    baseline_keys = set(baseline_cases)
    after_keys = set(after_cases)
    if baseline_keys != after_keys:
        raise ValueError(
            "build cases differ: "
            f"baseline-only={len(baseline_keys - after_keys)}, "
            f"after-only={len(after_keys - baseline_keys)}"
        )
    cases: list[BuildCaseComparison] = []
    for key in order:
        identity, baseline_metrics = baseline_cases[key]
        _, after_metrics = after_cases[key]
        baseline_wall_time = baseline_metrics["build_wall_time_s"]
        if baseline_wall_time <= 0.0:
            raise ValueError(f"baseline build wall time must be positive for {identity}")
        after_wall_time = after_metrics["build_wall_time_s"]
        delta = after_wall_time - baseline_wall_time
        ratio = delta / baseline_wall_time
        historical_limit = baseline_wall_time * (1.0 + _BUILD_WALL_TIME_THRESHOLD_RATIO)
        historical_regression = after_wall_time > historical_limit
        semantic_change_reasons: list[str] = []
        if baseline_metrics["status"] != after_metrics["status"]:
            semantic_change_reasons.append(
                f"status: {baseline_metrics['status']} -> {after_metrics['status']}"
            )
        if baseline_metrics["area"] != after_metrics["area"]:
            semantic_change_reasons.append(
                f"area: {baseline_metrics['area']} -> {after_metrics['area']}"
            )
        gate_kind: BuildGateKind = "audit_deadline_grace"
        governing_limit = identity["budget"] + _BUILD_ATOMIC_COMPLETION_GRACE_S
        cases.append(
            BuildCaseComparison(
                case=identity,
                baseline=baseline_metrics,
                after=after_metrics,
                wall_time_delta_s=delta,
                wall_time_delta_ratio=ratio,
                wall_time_delta_percent=ratio * 100.0,
                wall_time_threshold_ratio=_BUILD_WALL_TIME_THRESHOLD_RATIO,
                historical_regression=historical_regression,
                gate_kind=gate_kind,
                semantic_change_reasons=semantic_change_reasons,
                governing_limit_s=governing_limit,
                measured_wall_s=after_wall_time,
                gate_passed=after_wall_time <= governing_limit,
            )
        )
    return BuildComparison(
        passed=all(case["gate_passed"] for case in cases),
        cases=cases,
    )


def _read_json(path: Path, *, label: str) -> object:
    return cast(object, json.loads(path.read_text(encoding="utf-8")))


def _read_json_lines(path: Path, *, label: str) -> list[Mapping[str, object]]:
    records: list[Mapping[str, object]] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if line.strip():
            records.append(
                _object(
                    cast(object, json.loads(line)),
                    label=f"{label}[{index}]",
                )
            )
    return records


def _projection_after_path(build_after: Path) -> Path:
    projection_name = build_after.name.replace("-build-", "-", 1)
    if projection_name == build_after.name:
        raise ValueError("after-build filename must contain '-build-' to locate projection results")
    return build_after.with_name(projection_name)


def _comparison_result(
    build_baseline: Path,
    build_after: Path,
) -> ComparisonResult:
    projection_payload = _object(
        _read_json(_projection_after_path(build_after), label="projection after"),
        label="projection after",
    )
    projection = cast(
        ProjectionComparison,
        _object(
            projection_payload["projection_comparison"],
            label="projection after.projection_comparison",
        ),
    )
    builds = compare_build_results(
        _read_json_lines(build_baseline, label="build baseline"),
        _read_json_lines(build_after, label="build after"),
    )
    return ComparisonResult(
        passed=projection["passed"] and builds["passed"],
        thresholds=GateThresholds(
            projection_added_p95_s=_PROJECTION_P95_THRESHOLD_S,
            build_wall_time_ratio=_BUILD_WALL_TIME_THRESHOLD_RATIO,
            build_atomic_completion_grace_s=_BUILD_ATOMIC_COMPLETION_GRACE_S,
        ),
        projection=projection,
        builds=builds,
    )


def _emit(payload: object, output: Path | None) -> None:
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(encoded, end="")
    else:
        _ = output.write_text(encoded, encoding="utf-8")


def _positive_int(raw: str) -> int:
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--samples", type=_positive_int, default=20)
    _ = parser.add_argument("--baseline", type=Path)
    _ = parser.add_argument("--compare-builds", nargs=2, type=Path)
    _ = parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    samples = cast(int, args.samples)
    baseline = cast(Path | None, args.baseline)
    compare_builds = cast(list[Path] | None, args.compare_builds)
    output = cast(Path | None, args.output)

    if compare_builds is not None:
        if baseline is not None:
            parser.error("--baseline cannot be combined with --compare-builds")
        comparison = _comparison_result(compare_builds[0], compare_builds[1])
        _emit(comparison, output)
        return 0 if comparison["passed"] else 1

    result = run_benchmark(samples)
    if baseline is None:
        _emit(result, output)
        return 0
    projection_comparison = compare_projection_results(
        _benchmark_result(_read_json(baseline, label="baseline"), label="baseline"),
        result,
    )
    after = BenchmarkAfterResult(
        cases=result["cases"],
        projection_comparison=projection_comparison,
    )
    _emit(after, output)
    return 0 if projection_comparison["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
