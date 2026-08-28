"""Run every ``(url, candidate, strategy, power)`` cell and measure it.

Fairness is the whole point of this module.  Both strategies get the *same*
``BuildSpec`` object, the same time budget, and the same seed, and neither is
asked how it did -- the harness measures the placement itself.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass

from flab2bp.bench.corpus import URL_CORPUS, CorpusEntry
from flab2bp.bench.metrics import measure
from flab2bp.bench.types import CellResult
from flab2bp.lab import data as lab_data
from flab2bp.lab.techs import belt_rules_for_url
from flab2bp.lab.url import parse_url
from flab2bp.layout import finalize
from flab2bp.layout import validate as validator
from flab2bp.layout.base import LayoutStrategy, NoValidLayout, Placement
from flab2bp.layout.freeform import FreeformLayout
from flab2bp.layout.sequence_solver import SequencePairLayout
from flab2bp.rates import build_candidates
from flab2bp.spec import BuildSpec

#: Fixed so CP-SAT cannot make the comparison noise.  Recorded in the JSON.
BENCH_SEED = 0


@dataclass(frozen=True, slots=True)
class StrategyHandle:
    name: str
    strategy: LayoutStrategy


def available_strategies(
    *, power: bool, belt_vertical_construction: bool = True
) -> tuple[StrategyHandle, ...]:
    """Return both implemented production strategies."""
    return (
        StrategyHandle(
            "freeform",
            FreeformLayout(
                power=power,
                belt_vertical_construction=belt_vertical_construction,
            ),
        ),
        StrategyHandle(
            "sequence-pair",
            SequencePairLayout(
                power=power,
                belt_vertical_construction=belt_vertical_construction,
            ),
        ),
    )


def _id_map(spec: BuildSpec) -> validator.IdMap:
    """Bridge FactorioLab string ids to the DSP ints a ``Placement`` carries."""
    return validator.id_map(spec)


def _run_cell(
    handle: StrategyHandle,
    entry: CorpusEntry,
    spec: BuildSpec,
    *,
    power: bool,
    time_budget_s: float,
) -> CellResult:
    started = time.perf_counter()
    try:
        placement: Placement = handle.strategy.lay_out(spec, time_budget_s=time_budget_s)
    except NoValidLayout as exc:
        # A refusal is a result, not a crash. Letting it propagate killed the
        # whole matrix on the first spec either strategy could not wire, which
        # is currently most of them -- and a bake-off that cannot run is worse
        # than one with an honest empty row.
        return _refused_cell(handle, entry, spec, power=power, reason=exc.reason)
    placement = finalize.compact_open_boundary_belts(
        placement,
        spec,
        expect_power=power,
    )
    try:
        placement = finalize.finalize_placement(placement)
    except finalize.ProjectionRefusal as exc:
        return _refused_cell(
            handle,
            entry,
            spec,
            power=power,
            reason="final spherical projection rejected " + ", ".join(exc.checks),
        )
    elapsed = time.perf_counter() - started

    m = measure(placement)
    # Pass the spec AND the id map. Without them the nine spec-dependent checks
    # (throughput, proliferator, flow) are skipped, and `valid` then means "no
    # check that ran failed" -- which for a bare call excludes every check that
    # could have caught a layout that pastes cleanly and does not run. The
    # scoring module ranks on `valid`, not `verified`, so that gap fed straight
    # into the winner.
    report = validator.validate(placement, spec, ids=_id_map(spec), expect_power=power)

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
        # Read what the STRATEGY reported, not what geometry infers.
        #
        # `metrics.measure` defines a direct insert as a sorter with a machine at
        # both ends. Freeform's bridge spans the producer's output-lane belt to
        # the consumer's input-lane belt, so that counter reports zero however
        # many are emitted -- which is why `docs/AB_RESULTS.md` showed
        # `direct_inserts = 0` for a strategy that was placing 17 of them across
        # the corpus, and why this looked for a while like a feature that never
        # fired rather than a counter that could not see it.
        #
        # Counting belt-to-belt sorters instead would count ordinary trunk taps
        # that are not direct inserts.
        direct_inserts=int(stats.get("direct_inserts", m.direct_inserts)),
        towers=m.towers,
        altitude_levels=m.altitude_levels,
        solve_seconds=elapsed,
        hit_time_budget=bool(stats.get("hit_time_budget", 0.0)),
        fallback_used=bool(stats.get("fallback_used", 0.0)),
        solver_status="OPTIMAL" if stats.get("solver_status", 0.0) else "FEASIBLE",
        valid=report.ok,
        errors=len(report.errors),
        warnings=len(report.warnings),
        # A power check skipped under `--no-power` is a caller declaration, not
        # a hole: we told the validator there would be no towers. Every other
        # skip stays, because a check that could not run is not a check that
        # passed.
        skipped_checks=tuple(c for c in report.skipped if power or not c.startswith("power.")),
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

        # The save's slope rule is a property of THIS entry's URL, so it is
        # asked per entry rather than once for the run.
        rules = belt_rules_for_url(entry.url)
        for power in powers:
            for handle in available_strategies(
                power=power,
                belt_vertical_construction=rules.vertical_construction,
            ):
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


def _refused_cell(
    handle: StrategyHandle,
    entry: CorpusEntry,
    spec: BuildSpec,
    *,
    power: bool,
    reason: str,
) -> CellResult:
    """A strategy that searched and found nothing still gets a row.

    Graded ``valid=False`` so it can never contribute an area, but tagged
    ``layout.refused`` rather than a validator check name: "B refused" and "B
    produced something the validator rejected" are opposite bugs and must stay
    distinguishable in the report.
    """
    return CellResult(
        strategy=handle.name,
        url_id=entry.url_id,
        candidate=spec.label or "default",
        power=power,
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
        solver_status=f"REFUSED: {reason[:80]}",
        valid=False,
        errors=1,
        warnings=0,
        error_checks=("layout.refused",),
    )


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
