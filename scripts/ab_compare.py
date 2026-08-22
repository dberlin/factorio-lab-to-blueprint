"""Head-to-head area comparison of the two layout strategies on real URLs.

Lighter than the full bake-off: no matrix, no cross-validation, no report files.
It answers one question -- is Strategy B's extra machinery buying area on specs
that came from actual FactorioLab URLs, rather than on hand-built fixtures.

    uv run python scripts/ab_compare.py                       # trivial + small
    uv run python scripts/ab_compare.py --tier mid            # add mid
    uv run python scripts/ab_compare.py --budget 2 --repeat 3

Why ``--repeat`` matters: the shipping default is multi-worker CP-SAT, which is
deliberately nondeterministic (it is worth ~23% density over a single worker, so
pinning it would compare a configuration neither strategy would ship).  A single
sample per cell is therefore noise, and two runs can land on different packings
entirely -- which is exactly how an earlier comparison here reached a wrong
conclusion.  Repeats report the median and the spread instead.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from flab2bp.bench.corpus import URL_CORPUS, Tier  # noqa: E402
from flab2bp.layout.freeform import FreeformLayout  # noqa: E402
from flab2bp.layout.spine import SpineLayout  # noqa: E402

_TIER_ORDER = [Tier.TRIVIAL, Tier.SMALL, Tier.MID, Tier.LARGE, Tier.STRESS]


@dataclass
class Result:
    areas: list[int]
    belts: list[int]
    direct: list[int]
    walls: list[float]
    fallbacks: int
    errors: list[str]

    @property
    def area(self) -> int | None:
        return int(statistics.median(self.areas)) if self.areas else None

    @property
    def spread(self) -> str:
        if len(self.areas) < 2:
            return ""
        return f"{min(self.areas)}-{max(self.areas)}"


def _spec_for(url: str, candidates: int) -> object:
    """Resolve a URL to a BuildSpec, preferring the densest candidate."""
    from flab2bp.lab.data import load_vendored
    from flab2bp.lab.url import parse_url
    from flab2bp.rates.candidates import build_candidates

    ds = load_vendored()
    req = parse_url(url)
    specs = build_candidates(ds, req, count=candidates)
    # Pick the candidate with the fewest machines as a stand-in for "densest".
    # The real bake-off lays out every candidate and keeps the smallest RESULT,
    # which is not the same thing -- proliferation cuts machines but forbids
    # direct insertion on the sprayed edges, so fewer machines can still lay out
    # larger. This script is the cheap approximation; do not read it as the
    # bake-off's answer.
    return min(specs.candidates, key=lambda s: s.machine_count)


def run(entry: object, budget: float, repeat: int, candidates: int) -> tuple[Result, Result]:
    url = entry.url  # type: ignore[attr-defined]
    try:
        spec = _spec_for(url, candidates)
    except Exception as exc:  # noqa: BLE001 - one bad URL must not kill the sweep
        err = f"{type(exc).__name__}: {exc}"
        blank = Result([], [], [], [], 0, [err])
        return blank, blank

    out = []
    for cls in (SpineLayout, FreeformLayout):
        r = Result([], [], [], [], 0, [])
        for _ in range(repeat):
            t = time.time()
            try:
                p = cls(power=False).lay_out(spec, time_budget_s=budget)  # type: ignore[arg-type]
            except Exception as exc:  # noqa: BLE001
                r.errors.append(f"{type(exc).__name__}: {exc}")
                continue
            r.areas.append(p.area)
            r.belts.append(int(p.stats.get("belt_tiles", 0)))
            r.direct.append(int(p.stats.get("direct_inserts", 0)))
            r.walls.append(time.time() - t)
            r.fallbacks += int(p.stats.get("fallback_used", 0))
        out.append(r)
    return out[0], out[1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tier", default="small", choices=[t.value for t in _TIER_ORDER])
    ap.add_argument("--budget", type=float, default=2.0, help="seconds per lay_out call")
    ap.add_argument("--repeat", type=int, default=3, help="samples per cell; median is reported")
    ap.add_argument("--candidates", type=int, default=3)
    args = ap.parse_args()

    cutoff = _TIER_ORDER.index(Tier(args.tier))
    wanted = {t for t in _TIER_ORDER[: cutoff + 1]}
    entries = [e for e in URL_CORPUS if e.tier in wanted]

    print(f"budget={args.budget}s  repeat={args.repeat}  power=off  {len(entries)} URLs\n")
    cols = ("spec", "A area", "A di", "B area", "B di", "B/A", "A s", "B s")
    head = (
        f"{cols[0]:<26}{cols[1]:>8}{cols[2]:>6}{cols[3]:>8}"
        f"{cols[4]:>6}{cols[5]:>7}{cols[6]:>7}{cols[7]:>7}"
    )
    print(head)
    print("-" * len(head))

    ratios = []
    for e in entries:
        a, b = run(e, args.budget, args.repeat, args.candidates)
        name = e.url_id[:25]
        if a.errors or a.area is None or b.area is None:
            print(f"{name:<26}{'ERROR':>8}  {(a.errors or b.errors)[0][:40]}")
            continue
        ratio = b.area / a.area
        ratios.append(ratio)
        flag = " *" if b.fallbacks or a.fallbacks else ""
        print(
            f"{name:<26}{a.area:>8}{max(a.direct, default=0):>6}"
            f"{b.area:>8}{max(b.direct, default=0):>6}"
            f"{ratio:>6.2f}x{statistics.median(a.walls):>6.1f}s"
            f"{statistics.median(b.walls):>6.1f}s{flag}"
        )
        if a.spread or b.spread:
            print(f"{'':<26}{'spread:':>8} A {a.spread or '-':<12} B {b.spread or '-'}")

    if ratios:
        geo = statistics.geometric_mean(ratios)
        print(f"\ngeometric mean B/A = {geo:.3f}  ({'B denser' if geo < 1 else 'A denser'})")
        print(f"best for B: {min(ratios):.2f}x   worst for B: {max(ratios):.2f}x")
    print("\n* = a fallback layout was used somewhere in that cell")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
