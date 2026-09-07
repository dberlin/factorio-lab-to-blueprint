"""`Cells.best_per_url` equals each of the four scans it replaces.

Four independent re-implementations of "best CellResult per url" exist today,
all touched inside one `render_markdown()` pass: `bench/scoring.py:69-78`
`_best_per_url`, `bench/report.py:43-51` `_best` (identical logic to
`scoring.py`), the `(url_id, strategy)`-keyed loop inside `bench/report.py`'s
`_winning_candidates` (~145-152), and `bench/regression.py:64-71`
`_best_per_url`, which uses a DIFFERENT rank key: `_rank` at
`regression.py:59-61` is `(0 if valid else 1, area)`, not smallest-area-among-
valid. The different key is why this type takes `rank` rather than
hard-coding area.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from flab2bp.indexed import Cells

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flab2bp.bench.types import CellResult


@dataclass(frozen=True, slots=True)
class _FakeCell:
    url_id: str
    strategy: str
    candidate: str
    valid: bool
    area: int


def _as_cells(cells: list[_FakeCell]) -> list[CellResult]:
    """`_FakeCell` carries every field `Cells` reads (`url_id`, `strategy`,
    `candidate`, `valid`, `area`) but is not nominally a `CellResult`.
    ``cast`` tells mypy what the runtime duck-typing already guarantees --
    it changes no value."""
    return cast("list[CellResult]", cells)


def _fixture(seed: int, count: int) -> list[_FakeCell]:
    rng = random.Random(seed)
    urls = [f"url-{i}" for i in range(12)]
    return [
        _FakeCell(
            url_id=rng.choice(urls),
            strategy=rng.choice(("freeform", "sequence-pair")),
            candidate=rng.choice(("default", "no-proliferator")),
            valid=rng.random() > 0.25,
            area=rng.randrange(100, 10_000),
        )
        for _ in range(count)
    ]


def _brute_best_valid(cells: list[_FakeCell], strategy: str) -> dict[str, _FakeCell]:
    """Mirrors `bench/scoring.py::_best_per_url` / `bench/report.py::_best`."""
    best: dict[str, _FakeCell] = {}
    for cell in cells:
        if cell.strategy != strategy or not cell.valid:
            continue
        current = best.get(cell.url_id)
        if current is None or cell.area < current.area:
            best[cell.url_id] = cell
    return best


def _brute_best_ranked(cells: list[_FakeCell]) -> dict[str, _FakeCell]:
    """Mirrors `bench/regression.py::_best_per_url` with its own `_rank`."""

    def rank(cell: _FakeCell) -> tuple[int, int]:
        return (0 if cell.valid else 1, cell.area)

    best: dict[str, _FakeCell] = {}
    for cell in cells:
        current = best.get(cell.url_id)
        if current is None or rank(cell) < rank(current):
            best[cell.url_id] = cell
    return best


def test_best_per_url_equals_the_scoring_and_report_scan() -> None:
    cells = _fixture(seed=21, count=400)
    index = Cells.of(_as_cells(cells))
    for strategy in ("freeform", "sequence-pair"):
        expected = cast("dict[str, CellResult]", _brute_best_valid(cells, strategy))
        assert index.best_per_url(strategy=strategy) == expected


def test_best_per_url_equals_the_regression_scan_with_its_own_rank_key() -> None:
    cells = _fixture(seed=22, count=400)
    index = Cells.of(_as_cells(cells))
    got = index.best_per_url(
        valid_only=False,
        rank=lambda c: (0 if c.valid else 1, c.area),
    )
    expected = cast("dict[str, CellResult]", _brute_best_ranked(cells))
    assert got == expected


def test_ties_keep_the_first_cell_seen_exactly_as_the_scan_does() -> None:
    a = _FakeCell("u", "freeform", "default", True, 100)
    b = _FakeCell("u", "freeform", "no-proliferator", True, 100)
    index = Cells.of(_as_cells([a, b]))
    assert index.best_per_url(strategy="freeform")["u"] is cast("CellResult", a)


def test_for_url_returns_every_cell_for_that_url_in_input_order() -> None:
    cells = _fixture(seed=23, count=200)
    index = Cells.of(_as_cells(cells))
    for url_id in index.url_ids():
        expected = cast("tuple[CellResult, ...]", tuple(c for c in cells if c.url_id == url_id))
        assert index.for_url(url_id) == expected


def test_an_empty_collection_answers_empty() -> None:
    index = Cells.of(_as_cells([]))
    assert index.best_per_url(strategy="freeform") == {}
    assert index.url_ids() == ()


def test_best_per_url_defaults_to_smallest_area_when_strategy_is_unset() -> None:
    """valid_only + no strategy filter must still be a real filter, not a
    pass-through -- an invalid cell with a smaller area must lose to a valid
    one with a larger area, mirroring what every real caller relies on."""
    small_invalid = _FakeCell("u", "freeform", "default", False, 10)
    large_valid = _FakeCell("u", "sequence-pair", "default", True, 9000)
    index = Cells.of(_as_cells([small_invalid, large_valid]))
    assert index.best_per_url()["u"] is cast("CellResult", large_valid)
