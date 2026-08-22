"""Run every ``(url, candidate, strategy, power)`` cell and measure it.

Fairness is the whole point of this module.  Both strategies get the *same*
``BuildSpec`` object, the same time budget, and the same seed, and neither is
asked how it did -- the harness measures the placement itself.
"""

from __future__ import annotations

import importlib
import time
from collections.abc import Sequence
from dataclasses import dataclass

from flab2bp.bench.corpus import URL_CORPUS, CorpusEntry
from flab2bp.bench.metrics import measure
from flab2bp.bench.types import CellResult
from flab2bp.lab import data as lab_data
from flab2bp.lab.url import parse_url
from flab2bp.layout import validate as validator
from flab2bp.layout.base import LayoutStrategy, Placement
from flab2bp.rates import build_candidates
from flab2bp.spec import BuildSpec

#: Fixed so CP-SAT cannot make the comparison noise.  Recorded in the JSON.
BENCH_SEED = 0


@dataclass(frozen=True, slots=True)
class StrategyHandle:
    name: str
    strategy: LayoutStrategy


def available_strategies(*, power: bool) -> tuple[StrategyHandle, ...]:
    """Discover implemented strategies.

    Strategy B may not exist yet, so this imports defensively rather than
    assuming.  A missing strategy is simply absent from the bake-off; it is not
    an error, and it must not be scored as a loss.
    """
    handles: list[StrategyHandle] = []

    try:
        from flab2bp.layout.spine import SpineLayout
    except ImportError:  # pragma: no cover - spine is implemented
        pass
    else:
        handles.append(StrategyHandle("spine", SpineLayout(power=power)))

    # Imported dynamically, not statically: Strategy B may legitimately not
    # exist yet, and a static import cannot typecheck against a module that is
    # absent by design.  A missing strategy is simply not in the bake-off.
    try:
        module = importlib.import_module("flab2bp.layout.freeform")
        freeform_cls = module.FreeformLayout
    except (ImportError, AttributeError):
        pass
    else:
        handles.append(StrategyHandle("freeform", freeform_cls(power=power)))

    return tuple(handles)


def _id_map(spec: BuildSpec) -> validator.IdMap:
    """Bridge FactorioLab string ids to the DSP ints a ``Placement`` carries."""
    from flab2bp.layout.spine import MACHINE_ITEM_IDS

    dataset = lab_data.load_vendored()
    recipes: dict[str, int] = {}
    for index, recipe in enumerate(dataset.recipes, start=1):
        recipes[recipe.id] = index
    items = dict(MACHINE_ITEM_IDS)
    return validator.IdMap(recipes=recipes, items=items)


def _run_cell(
    handle: StrategyHandle,
    entry: CorpusEntry,
    spec: BuildSpec,
    *,
    power: bool,
    time_budget_s: float,
) -> CellResult:
    started = time.perf_counter()
    placement: Placement = handle.strategy.lay_out(spec, time_budget_s=time_budget_s)
    elapsed = time.perf_counter() - started

    m = measure(placement)
    report = validator.validate(placement)

    stats = placement.stats
    return CellResult(
        strategy=handle.name,
        url_id=entry.url_id,
        candidate=spec.label or "default",
        power=power,
        area=m.area,
        used_tiles=m.used_tiles,
        width=m.width,
        height=m.height,
        machines=m.machines,
        belt_tiles=m.belt_tiles,
        sorters=m.sorters,
        direct_inserts=m.direct_inserts,
        towers=m.towers,
        altitude_levels=m.altitude_levels,
        solve_seconds=elapsed,
        hit_time_budget=bool(stats.get("hit_time_budget", 0.0)),
        fallback_used=bool(stats.get("fallback_used", 0.0)),
        solver_status="OPTIMAL" if stats.get("solver_status", 0.0) else "FEASIBLE",
        valid=report.ok,
        errors=len(report.errors),
        warnings=len(report.warnings),
        skipped_checks=report.skipped,
        error_checks=tuple(sorted({f.check for f in report.errors})),
        checks_run=len(report.checks_run),
    )


def specs_for(entry: CorpusEntry, *, candidates: int) -> tuple[BuildSpec, ...]:
    """Compute the candidate frontier once, to be shared by every strategy."""
    dataset = lab_data.load_vendored()
    # Every corpus URL is bare (no `z=`), so no hash index is needed to resolve
    # ids.  Deliberately not passing one: `lab.data.HashIndex` does not satisfy
    # `lab.url.ModHash` (it has no `locations`), and forcing it here would
    # paper over that seam rather than surface it.
    request = parse_url(entry.url)
    return build_candidates(dataset, request, count=candidates).candidates


def run_corpus(
    entries: Sequence[CorpusEntry] = URL_CORPUS,
    *,
    time_budget_s: float | None = None,
    candidates: int = 3,
    powers: Sequence[bool] = (True, False),
) -> list[CellResult]:
    """Run the matrix.

    ``time_budget_s`` overrides the per-tier budget; leave it ``None`` to use
    each entry's tier default.
    """
    results: list[CellResult] = []
    for entry in entries:
        budget = time_budget_s if time_budget_s is not None else entry.tier.time_budget_s
        try:
            specs = specs_for(entry, candidates=candidates)
        except Exception as exc:  # noqa: BLE001 - a bad URL must not kill the run
            results.append(_failed_cell(entry, str(exc)))
            continue

        for power in powers:
            for handle in available_strategies(power=power):
                for spec in specs:
                    results.append(
                        _run_cell(
                            handle,
                            entry,
                            spec,
                            power=power,
                            time_budget_s=budget,
                        )
                    )
    return results


def _failed_cell(entry: CorpusEntry, message: str) -> CellResult:
    """A spec that could not even be computed still gets a row.

    Silently dropping it would make a broken URL look like a URL nobody ran.
    """
    return CellResult(
        strategy="-",
        url_id=entry.url_id,
        candidate="-",
        power=False,
        area=0,
        used_tiles=0,
        width=0,
        height=0,
        machines=0,
        belt_tiles=0,
        sorters=0,
        direct_inserts=0,
        towers=0,
        altitude_levels=0,
        solve_seconds=0.0,
        hit_time_budget=False,
        fallback_used=False,
        solver_status=f"SPEC-ERROR: {message[:80]}",
        valid=False,
        errors=1,
        warnings=0,
        error_checks=("rates.spec",),
    )
