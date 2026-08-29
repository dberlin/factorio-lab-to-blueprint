from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, TypedDict, cast

import pytest

from flab2bp.dsp import catalog, colliders, planet


class _CacheInfo(Protocol):
    hits: int
    misses: int
    maxsize: int | None
    currsize: int


class _CacheFunction(Protocol):
    def __call__(self, *args: object) -> object: ...
    def cache_clear(self) -> None: ...
    def cache_info(self) -> _CacheInfo: ...


class _FunctionReport(TypedDict):
    recommended_maxsize: int
    applied_maxsize: int | None
    rollback_reason: str | None


class _Report(TypedDict):
    functions: dict[str, _FunctionReport]


_REPORT = cast(
    _Report,
    cast(
        object,
        json.loads(
            (Path(__file__).parents[1] / "fixtures" / "geometry_cache_working_sets.json").read_text(
                encoding="utf-8"
            )
        ),
    ),
)
_FUNCTIONS: tuple[tuple[str, _CacheFunction], ...] = (
    (
        "catalog.collider_span",
        cast(_CacheFunction, cast(object, catalog.collider_span)),
    ),
    ("catalog.clearance", cast(_CacheFunction, cast(object, catalog.clearance))),
    (
        "colliders.own_centre_extent",
        cast(_CacheFunction, cast(object, colliders.own_centre_extent)),
    ),
    (
        "colliders.belt_keepout_offsets",
        cast(_CacheFunction, cast(object, colliders.belt_keepout_offsets)),
    ),
    (
        "planet.collider_radius",
        cast(_CacheFunction, cast(object, planet.collider_radius)),
    ),
)
_ASSEMBLER_MODEL = catalog.building(2303).model_index
_SPLITTER_MODEL = catalog.building(catalog.SPLITTER_ID).model_index
_CANONICAL_CALLS: tuple[tuple[_CacheFunction, tuple[object, ...]], ...] = (
    (cast(_CacheFunction, cast(object, catalog.collider_span)), (2303, 0.0)),
    (cast(_CacheFunction, cast(object, catalog.clearance)), (2303, 0.0)),
    (
        cast(_CacheFunction, cast(object, colliders.own_centre_extent)),
        (_ASSEMBLER_MODEL, 0.0),
    ),
    (
        cast(_CacheFunction, cast(object, colliders.belt_keepout_offsets)),
        (_SPLITTER_MODEL,),
    ),
    (
        cast(_CacheFunction, cast(object, planet.collider_radius)),
        (_ASSEMBLER_MODEL,),
    ),
)


type _CallArgs = tuple[object, ...]


def _yaw_eviction_args(name: str, identifier: int) -> tuple[_CallArgs, ...]:
    maxsize = _REPORT["functions"][name]["recommended_maxsize"]
    return tuple((identifier, float(yaw)) for yaw in range(1, maxsize + 2))


def _model_eviction_args(name: str, canonical_model: int) -> tuple[_CallArgs, ...]:
    maxsize = _REPORT["functions"][name]["recommended_maxsize"]
    models = tuple(
        building.model_index
        for building in catalog.all_buildings()
        if building.model_index != canonical_model
    )
    return tuple((model_index,) for model_index in models[: maxsize + 1])




_EVICTION_CALLS: tuple[
    tuple[str, _CacheFunction, _CallArgs, tuple[_CallArgs, ...]], ...
] = (
    (
        "catalog.collider_span",
        cast(_CacheFunction, cast(object, catalog.collider_span)),
        (2303, 0.0),
        _yaw_eviction_args("catalog.collider_span", 2303),
    ),
    (
        "colliders.belt_keepout_offsets",
        cast(_CacheFunction, cast(object, colliders.belt_keepout_offsets)),
        (_SPLITTER_MODEL,),
        _model_eviction_args("colliders.belt_keepout_offsets", _SPLITTER_MODEL),
    ),
)

_ROLLED_BACK_CALLS: tuple[tuple[str, _CacheFunction, _CallArgs], ...] = (
    (
        "catalog.clearance",
        cast(_CacheFunction, cast(object, catalog.clearance)),
        (2303, 0.0),
    ),
    (
        "colliders.own_centre_extent",
        cast(_CacheFunction, cast(object, colliders.own_centre_extent)),
        (_ASSEMBLER_MODEL, 0.0),
    ),
    (
        "planet.collider_radius",
        cast(_CacheFunction, cast(object, planet.collider_radius)),
        (_ASSEMBLER_MODEL,),
    ),
)


@pytest.mark.parametrize(("name", "function"), _FUNCTIONS)
def test_public_geometry_cache_uses_applied_measured_policy(
    name: str,
    function: _CacheFunction,
) -> None:
    report = _REPORT["functions"][name]
    assert report["recommended_maxsize"] > 0
    assert function.cache_info().maxsize == report["applied_maxsize"]
    if report["applied_maxsize"] is None:
        assert report["rollback_reason"]
    else:
        assert report["applied_maxsize"] == report["recommended_maxsize"]
        assert report["rollback_reason"] is None


@pytest.mark.parametrize(
    ("name", "function", "canonical_args"),
    _ROLLED_BACK_CALLS,
)
def test_performance_rollback_restores_unbounded_recomputation(
    name: str,
    function: _CacheFunction,
    canonical_args: _CallArgs,
) -> None:
    report = _REPORT["functions"][name]
    assert report["applied_maxsize"] is None
    assert report["rollback_reason"]
    assert function.cache_info().maxsize is None
    function.cache_clear()
    expected = function(*canonical_args)
    function.cache_clear()
    assert function(*canonical_args) == expected
    function.cache_clear()


@pytest.mark.parametrize(("function", "args"), _CANONICAL_CALLS)
def test_cache_clear_recomputes_the_same_geometry(
    function: _CacheFunction,
    args: tuple[object, ...],
) -> None:
    function.cache_clear()
    expected = function(*args)
    assert function.cache_info().currsize == 1
    function.cache_clear()
    assert function(*args) == expected
    assert function.cache_info().currsize == 1
    function.cache_clear()


@pytest.mark.parametrize(
    ("name", "function", "canonical_args", "eviction_args"),
    _EVICTION_CALLS,
)
def test_eviction_recomputes_the_same_geometry(
    name: str,
    function: _CacheFunction,
    canonical_args: _CallArgs,
    eviction_args: tuple[_CallArgs, ...],
) -> None:
    maxsize = _REPORT["functions"][name]["recommended_maxsize"]
    assert len(eviction_args) > maxsize
    assert len(set(eviction_args)) == len(eviction_args)
    assert canonical_args not in eviction_args

    function.cache_clear()
    expected = function(*canonical_args)
    for args in eviction_args:
        _ = function(*args)
    before_recompute = function.cache_info()
    assert function(*canonical_args) == expected
    assert function.cache_info().misses == before_recompute.misses + 1
    function.cache_clear()
