"""What `validate.certify` convicts on the ONE cell that wires every cut lane.

`titanium-glass / all-products` at `--budget 60` is the first cell in three
hierarchical gates to compose, route all 26 of its cut lanes
(``unrouted_cuts=0``) and reach certification.  It then refuses with three
``power.coverage`` findings, bit-identical across both gate rounds:

    composed placement failed validation: power.coverage: building 5952 has
    tile (63,3) outside every tower's supply radius; it would sit unpowered;
    ... 5953 ... (63,3) ...; ... 5959 ... (62,1) ...

The CLI truncates to the first three findings
(``hierarchy/strategy.py`` ~789, ``report.errors[:3]``) and names buildings by
id only, so the gate cannot say from the refusal alone HOW MANY findings there
are or WHAT those buildings are.  Both are needed to rank the lever: "three
belt tiles fell outside a tower disc" and "the whole composed canvas is
unpowered" are different defects with different fixes.

So this wraps ``validate.certify`` -- read-only, calling through and returning
the callee's own report -- and dumps, for every ``power.coverage`` finding,
the convicted building's kind and footprint, plus a census of the composed
placement's power buildings.  It changes nothing about the build and runs the
same argv the gate cell runs.

    uv run python certify_probe.py <out.json> -- <the exact flab2bp argv>
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from flab2bp import cli  # noqa: E402
from flab2bp.layout import validate as validate_mod  # noqa: E402
from flab2bp.layout.hierarchy import strategy as strategy_mod  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[2] != "--":
        print(__doc__)
        return 2
    out = Path(argv[1])
    record: dict = {"argv": argv[3:], "certifications": []}

    original = strategy_mod.validate.certify

    def certify_spy(placement, built, **kwargs):
        report = original(placement, built, **kwargs)
        # `Finding.buildings` holds INDICES into `placement.buildings`, and the
        # message renders that index -- so "building 5952" is the 5952nd
        # building of the composed placement, not a DSP id.
        buildings = placement.buildings
        convicted = []
        for finding in report.errors:
            if finding.check != "power.coverage":
                continue
            for index in finding.buildings:
                building = buildings[index] if index < len(buildings) else None
                convicted.append(
                    {
                        "index": index,
                        "item_id": getattr(building, "item_id", None),
                        "model_index": getattr(building, "model_index", None),
                        "x": getattr(building, "x", None),
                        "y": getattr(building, "y", None),
                        "z": str(getattr(building, "z", None)),
                        "width": getattr(building, "width", None),
                        "height": getattr(building, "height", None),
                        "detail": dict(finding.detail),
                        "message": finding.message,
                    }
                )
        record["certifications"].append(
            {
                "ok": report.ok,
                "errors_total": len(report.errors),
                "errors_by_check": dict(Counter(f.check for f in report.errors)),
                "power_coverage_findings": sum(
                    1 for f in report.errors if f.check == "power.coverage"
                ),
                "convicted": convicted,
                "buildings_total": len(buildings),
                "convicted_item_ids": dict(Counter(str(c["item_id"]) for c in convicted)),
                "all_item_ids": dict(Counter(str(b.item_id) for b in buildings)),
                "area": placement.area,
            }
        )
        return report

    strategy_mod.validate.certify = certify_spy
    try:
        code = cli.main(argv[3:])
    except BaseException as exc:  # noqa: BLE001 - a crash is a recorded outcome
        record["crash"] = f"{type(exc).__name__}: {exc}"
        code = 70
    finally:
        strategy_mod.validate.certify = original
    record["exit"] = code
    assert validate_mod is not None  # the module the spy calls through to
    out.write_text(json.dumps(record, indent=1, sort_keys=True, default=str))
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
