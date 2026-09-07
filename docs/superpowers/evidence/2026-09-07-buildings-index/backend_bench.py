"""Which index backend should ``Buildings`` use: dict, littletable, or polars?

The brief asked for ``littletable``; the coordinator relayed ``polars`` as an
allowed alternative for immutable holders.  Neither is free: both answer an
indexed lookup by materialising a new container (a ``littletable.Table``, a
polars ``DataFrame``), and that materialisation costs more than the linear
scan it is meant to replace at the building counts this project actually
produces (roughly 500 to 6000 records per blueprint).

This script measures all three against REAL blueprint records decoded from the
committed fixtures, so the answer is not a synthetic-microbenchmark artefact.

    uv run python docs/superpowers/evidence/2026-09-07-buildings-index/backend_bench.py

It is committed as evidence, not wired into the suite: it needs littletable and
polars installed, and the whole point of running it was to decide NOT to depend
on them.  Install them into a throwaway environment to reproduce:

    uv run --with littletable --with polars python <this file>
"""

from __future__ import annotations

import statistics
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from flab2bp.dsp.codec import decode  # noqa: E402
from flab2bp.dsp.records import BlueprintBuilding  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[4] / "tests" / "fixtures"

#: Real blueprints, smallest to largest, spanning the corpus's building counts.
CASES = (
    "factory-quick-start-step-3-red-cube.txt",
    "factory-heretical-smelter-block.txt",
    "factory-endgame-distribution-hub.txt",
    "tillable-blackbox-module-polar-artificial-stars-x85-warper-production-x24.txt",
)

#: Every key the survey found a call site filtering on.
KEYS = ("recipe_id", "item_id", "model_index", "output_obj_idx", "input_obj_idx")


def _time(fn: Callable[[], object], repeats: int = 200) -> float:
    """Microseconds per call, median of three batches (median resists a stray GC)."""
    fn()
    batches = []
    for _ in range(3):
        start = time.perf_counter()
        for _ in range(repeats):
            fn()
        batches.append((time.perf_counter() - start) / repeats * 1e6)
    return statistics.median(batches)


def _dict_index(rows: Sequence[BlueprintBuilding]) -> dict[str, dict[object, tuple[int, ...]]]:
    groups: dict[str, dict[object, list[int]]] = {key: {} for key in KEYS}
    for row in rows:
        for key in KEYS:
            groups[key].setdefault(getattr(row, key), []).append(row.index)
    return {key: {k: tuple(v) for k, v in m.items()} for key, m in groups.items()}


def main() -> int:
    try:
        import littletable  # type: ignore[import-not-found]
        import polars  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - reproduction aid
        print(f"needs littletable and polars to reproduce: {exc}")
        print("try: uv run --with littletable --with polars python", __file__)
        return 2

    print("| fixture | N | build dict | build littletable | build polars "
          "| scan | littletable | polars | dict |")
    print("|---|---|---|---|---|---|---|---|---|")
    for name in CASES:
        rows = decode((FIXTURES / name).read_text()).buildings
        probe = max(
            (r.recipe_id for r in rows if r.recipe_id),
            default=0,
        )

        start = time.perf_counter()
        groups = _dict_index(rows)
        dict_build = (time.perf_counter() - start) * 1e3

        start = time.perf_counter()
        table = littletable.Table()
        table.insert_many(rows)
        for key in KEYS:
            table.create_index(key, accept_none=True)
        lt_build = (time.perf_counter() - start) * 1e3

        start = time.perf_counter()
        frame = polars.DataFrame([{k: getattr(r, k) for k in (*KEYS, "index")} for r in rows])
        pl_build = (time.perf_counter() - start) * 1e3

        scan = _time(lambda: tuple(r.index for r in rows if r.recipe_id == probe))
        lt_q = _time(lambda: tuple(r.index for r in table.by.recipe_id[probe]))
        pl_q = _time(
            lambda: frame.filter(polars.col("recipe_id") == probe)["index"].to_list()
        )
        dict_q = _time(lambda: groups["recipe_id"].get(probe, ()))

        print(
            f"| {name[:44]} | {len(rows)} | {dict_build:.2f} ms | {lt_build:.2f} ms "
            f"| {pl_build:.2f} ms | {scan:.1f} us | {lt_q:.1f} us | {pl_q:.1f} us "
            f"| {dict_q:.3f} us |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
