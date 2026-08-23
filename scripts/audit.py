"""Can both strategies lay out everything, cleanly, right now?

    uv run python scripts/audit.py                    # every tier, both power settings
    uv run python scripts/audit.py --tier mid         # up to mid
    uv run python scripts/audit.py --budget 1,4,15    # sweep the solver budget
    uv run python scripts/audit.py --strategy spine

Exits non-zero if any cell is not clean, so it works as a gate.

WHY THIS IS A SCRIPT AND NOT A TEST
-----------------------------------
The whole matrix is minutes of CP-SAT and the test suite is deliberately ~24s.
Putting this in ``pytest`` would either make the suite unusable in an edit loop
or force it down to a sample so small it stops being the guarantee it exists to
be.  It is the gate you run before believing "both strategies work".

WHAT COUNTS AS A FAILURE, AND WHY THE DISTINCTION MATTERS
--------------------------------------------------------
Three ways a cell can miss, and they call for opposite fixes:

* ``REFUSED`` -- the strategy searched and raised ``NoValidLayout``.  Honest, and
  the *better* failure: nothing broken is emitted.
* ``INVALID`` -- it produced a placement the validator rejected.  Worse than
  refusing, because a blueprint that pastes and then does not run is the one
  outcome nobody discovers until they are standing in front of it in game.
* ``CRASH`` -- an unexpected exception.  Always a bug here, never the spec's
  fault.

A budget sweep is not optional padding.  CP-SAT is time-limited and multi-worker
by default, so a spec that validates at 4s may not at 1s, and "clean" that only
holds at one budget is not clean.  A LOW budget producing INVALID rather than
REFUSED is a serious finding: it means the feasibility check is budget-dependent
somewhere it should not be.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from flab2bp.bench.corpus import URL_CORPUS, Tier  # noqa: E402
from flab2bp.lab.data import load_vendored  # noqa: E402
from flab2bp.lab.url import parse_url  # noqa: E402
from flab2bp.layout import validate  # noqa: E402
from flab2bp.layout.base import LayoutStrategy, NoValidLayout  # noqa: E402
from flab2bp.layout.freeform import FreeformLayout  # noqa: E402
from flab2bp.layout.spine import SpineLayout  # noqa: E402
from flab2bp.pipeline import _id_map  # noqa: E402
from flab2bp.rates.candidates import build_candidates  # noqa: E402

_TIER_ORDER = (Tier.TRIVIAL, Tier.SMALL, Tier.MID, Tier.LARGE, Tier.STRESS)
_STRATEGIES: dict[str, type[LayoutStrategy]] = {
    "spine": SpineLayout,
    "freeform": FreeformLayout,
}


@dataclass
class Tally:
    clean: int = 0
    refused: int = 0
    invalid: int = 0
    crashed: int = 0
    checks: Counter[str] = field(default_factory=Counter)
    misses: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.clean + self.refused + self.invalid + self.crashed


def audit(
    strategies: list[str], tiers: set[Tier], budgets: list[float], candidates: int
) -> dict[str, Tally]:
    data = load_vendored()
    entries = [e for e in URL_CORPUS if e.tier in tiers]

    # Resolve every spec ONCE and share it, so both strategies are judged on
    # identical input and a rate-solver hiccup cannot look like a layout fault.
    specs: dict[str, tuple[object, ...]] = {}
    for e in entries:
        try:
            specs[e.url_id] = build_candidates(
                data, parse_url(e.url), count=candidates
            ).candidates
        except Exception as exc:  # noqa: BLE001
            print(f"  SPEC FAILED {e.url_id}: {type(exc).__name__}: {exc}", file=sys.stderr)

    out = {name: Tally() for name in strategies}
    for name in strategies:
        cls = _STRATEGIES[name]
        for e in entries:
            for spec in specs.get(e.url_id, ()):
                for budget in budgets:
                    for power in (False, True):
                        t = out[name]
                        label = (
                            f"{e.url_id}/{spec.label}"  # type: ignore[attr-defined]
                            f" power={int(power)} budget={budget:g}s"
                        )
                        try:
                            p = cls(power=power).lay_out(spec, time_budget_s=budget)  # type: ignore[arg-type]
                        except NoValidLayout as exc:
                            t.refused += 1
                            t.checks["<refused>"] += 1
                            t.misses.append(f"REFUSED  {label}  {exc.reason[:60]}")
                            continue
                        except Exception as exc:  # noqa: BLE001
                            t.crashed += 1
                            t.checks["<crash>"] += 1
                            t.misses.append(
                                f"CRASH    {label}  {type(exc).__name__}: {str(exc)[:48]}"
                            )
                            continue
                        report = validate.validate(
                            p,
                            spec,  # type: ignore[arg-type]
                            ids=_id_map(spec),  # type: ignore[arg-type]
                            expect_power=power,
                        )
                        if report.ok:
                            t.clean += 1
                            continue
                        t.invalid += 1
                        for f in report.errors:
                            t.checks[f.check] += 1
                        t.misses.append(
                            f"INVALID  {label}  {len(report.errors)}e "
                            + ",".join(sorted({f.check for f in report.errors}))[:52]
                        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tier", default="stress", choices=[t.value for t in _TIER_ORDER])
    ap.add_argument(
        "--budget",
        default="4",
        help="comma-separated solver budgets in seconds; sweeping is the point",
    )
    ap.add_argument("--candidates", type=int, default=3)
    ap.add_argument("--strategy", default="both", choices=("both", "spine", "freeform"))
    ap.add_argument(
        "--quiet", action="store_true", help="totals only, no per-cell miss list"
    )
    args = ap.parse_args()

    cutoff = _TIER_ORDER.index(Tier(args.tier))
    tiers = set(_TIER_ORDER[: cutoff + 1])
    budgets = [float(b) for b in args.budget.split(",")]
    names = list(_STRATEGIES) if args.strategy == "both" else [args.strategy]

    t0 = time.time()
    results = audit(names, tiers, budgets, args.candidates)

    failed = False
    for name, t in results.items():
        status = "CLEAN" if t.clean == t.total else "NOT CLEAN"
        print(
            f"\n=== {name}: {t.clean}/{t.total} clean -- {status}"
            f"   (refused {t.refused}, invalid {t.invalid}, crashed {t.crashed})"
        )
        if t.clean != t.total:
            failed = True
            print(f"    by check: {dict(t.checks.most_common())}")
            if not args.quiet:
                for m in t.misses:
                    print(f"    {m}")

    print(f"\n{time.time() - t0:.0f}s")
    if failed:
        print(
            "\nNOT CLEAN. An INVALID cell is worse than a REFUSED one: refusing "
            "emits nothing, while an invalid blueprint pastes and then does not "
            "run. Fix the invalid ones first."
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
