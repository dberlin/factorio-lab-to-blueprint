"""Benchmark cells, indexed by url, with the "best per url" reduction shared.

Three implementations of this scan share one body -- `bench/scoring.py:69-78`
`_best_per_url`, `bench/report.py:43-51` `_best`, and the `(url_id, strategy)`-
keyed loop inside `bench/report.py`'s `_winning_candidates` (~145-152) -- and a
fourth, `bench/regression.py:64-71` `_best_per_url`, uses a DIFFERENT rank key:
`_rank` at `regression.py:59-61` is `(0 if cell.valid else 1, cell.area)`, not
smallest-area-among-valid. That is why `best_per_url` below takes `rank` as a
parameter instead of hard-coding "smallest area" -- the shared thing across
the four call sites is the per-url index, not the reduction.

`CellResult` (real source read at HEAD) lives in `flab2bp.bench.types`, not
`flab2bp.bench.scoring` -- the brief's import path was wrong; this module
imports from the real location, for typing only.

Backend: littletable, indexed on `url_id`. At <=72 rows read once per report
there is nothing measurable to gain in speed (Ruling I-3 keeps polars out of
the conversation at this size); the win under Ruling I-5 is removing three
duplicate re-implementations of the same reduction, not throughput.

TIE-BREAKING IS PART OF THE CONTRACT. Every scan above keeps the FIRST cell
seen on an equal rank (`if current is None or cell.area < current.area`), so
`best_per_url` does too: it walks candidates in input order and only replaces
the running best on a STRICT improvement. A `<=` here would change which
candidate a report names, and Task 16's conversion would then produce a
report that differs from master byte for byte.

Ruling P-18: `best_per_url` queries the littletable index per url
(`self._table.by.url_id[url_id]`, then `.where(...)` on that result) rather
than looping the flat `self._cells` sequence directly. A backend that is
bypassed on its own hot accessor would be decorative and would fail Ruling
I-5 on its own terms.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import littletable

from flab2bp.indexed._record import IndexRecord

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flab2bp.bench.types import CellResult


@dataclass
class _CellRecord(IndexRecord):
    url_id: str = ""
    strategy: str = ""
    valid: bool = False
    position: int = -1


def _area_rank(cell: CellResult) -> tuple[int, ...]:
    """Default rank: smallest area, matching `scoring.py` and `report.py`."""
    return (cell.area,)


class Cells:
    """One benchmark run's cells, reduced by key instead of by rescan."""

    def __init__(self, cells: Sequence[CellResult]) -> None:
        table: littletable.Table = littletable.Table("cells")
        table.create_index("url_id")
        for position, cell in enumerate(cells):
            table.insert(
                _CellRecord(
                    payload=cell,
                    url_id=cell.url_id,
                    strategy=cell.strategy,
                    valid=cell.valid,
                    position=position,
                )
            )
        self._table = table
        self._url_ids = tuple(dict.fromkeys(cell.url_id for cell in cells))

    @classmethod
    def of(cls, cells: Sequence[CellResult]) -> Cells:
        """Index one benchmark run's cells."""
        return cls(cells)

    def url_ids(self) -> tuple[str, ...]:
        """Every url id, first-seen order."""
        return self._url_ids

    def for_url(self, url_id: str) -> tuple[CellResult, ...]:
        """Every cell for one url, in input order."""
        records = sorted(self._table.by.url_id[url_id], key=lambda r: r.position)
        return tuple(record.payload for record in records)

    def best_per_url(
        self,
        *,
        strategy: str | None = None,
        valid_only: bool = True,
        rank: Callable[[CellResult], tuple[int, ...]] | None = None,
    ) -> dict[str, CellResult]:
        """The cell each of the four scans this replaces would pick, per url.

        ``rank`` defaults to smallest area, matching `bench/scoring.py`'s
        `_best_per_url` and `bench/report.py`'s `_best`. `bench/regression.py`
        passes ``lambda c: (0 if c.valid else 1, c.area)``. Ties keep the
        first cell in input order, exactly as every scan above does.
        """
        key = _area_rank if rank is None else rank
        selected: list[tuple[int, str, CellResult]] = []
        for url_id in self._url_ids:
            candidates: littletable.Table = self._table.by.url_id[url_id]
            if strategy is not None:
                candidates = candidates.where(strategy=strategy)
            if valid_only:
                candidates = candidates.where(valid=True)
            ordered = sorted(candidates, key=lambda r: r.position)
            best_cell: CellResult | None = None
            for record in ordered:
                cell = record.payload
                if best_cell is None or key(cell) < key(best_cell):
                    best_cell = cell
            if best_cell is not None:
                selected.append((ordered[0].position, url_id, best_cell))
        return {url_id: cell for _position, url_id, cell in sorted(selected)}
