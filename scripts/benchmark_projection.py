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
from typing import TypedDict, cast

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from flab2bp.layout import finalize  # noqa: E402
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


class BenchmarkResult(TypedDict):
    cases: dict[str, CaseResult]


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
            _building(building, index=index)
            for index, building in enumerate(building_values)
        ),
        description=_string(placement["description"], label=f"{name}.placement.description"),
        short_desc=_string(placement["short_desc"], label=f"{name}.placement.short_desc"),
        icons=tuple(_integer(icon, label=f"{name}.placement.icons") for icon in icon_values),
        stats=cast(PlacementStats, cast(object, numeric_stats)),
    )


def _time_case(placement: Placement, samples: int) -> CaseResult:
    if samples < 1:
        raise ValueError("samples must be at least 1")
    elapsed: list[float] = []
    finalized: Placement | None = None
    for _ in range(samples):
        started = time.perf_counter_ns()
        finalized = finalize.finalize_placement(placement)
        elapsed.append((time.perf_counter_ns() - started) / 1_000_000_000)
    assert finalized is not None
    ordered = sorted(elapsed)
    p95 = ordered[math.ceil(0.95 * len(ordered)) - 1]
    return CaseResult(
        median_s=statistics.median(ordered),
        p95_s=p95,
        frame_candidates=int(finalized.stats.get("projection_frame_candidates", 0)),
        projections=int(finalized.stats.get("projection_count", 0)),
        collider_pairs=int(finalized.stats.get("projection_collider_pairs", 0)),
        power_pairs=int(finalized.stats.get("projection_power_pairs", 0)),
        sorters=int(finalized.stats.get("projection_sorters", 0)),
        area=finalized.area,
    )


def run_benchmark(samples: int) -> BenchmarkResult:
    if samples < 1:
        raise ValueError("samples must be at least 1")
    placements = {name: _load_case(name) for name in _CASES}
    return BenchmarkResult(
        cases={name: _time_case(placement, samples) for name, placement in placements.items()}
    )


def _positive_int(raw: str) -> int:
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--samples", type=_positive_int, default=20)
    _ = parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    samples = cast(int, args.samples)
    output = cast(Path | None, args.output)

    payload = json.dumps(run_benchmark(samples), indent=2, sort_keys=True) + "\n"
    if output is None:
        print(payload, end="")
    else:
        _ = output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
