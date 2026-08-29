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


@pytest.mark.parametrize(("name", "function"), _FUNCTIONS)
def test_public_geometry_cache_uses_measured_finite_bound(
    name: str,
    function: _CacheFunction,
) -> None:
    expected = _REPORT["functions"][name]["recommended_maxsize"]
    info = function.cache_info()
    assert expected > 0
    assert info.maxsize == expected


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
