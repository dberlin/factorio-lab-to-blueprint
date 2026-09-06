"""Is "pressure is hard" visible WITHIN one spec?

Arm B says: route the nets crossing the busiest band first.  The honest test of
whether that ordering carries information is to run its OPPOSITE on the same
spec -- lowest pressure first, everything else identical -- and see whether the
router notices.  If B and its reverse measure the same, cut pressure is not
ordering these nets in any way the search cares about; if they separate, the
gap between them is the size of the signal, and B's own gain against ``off``
can be read against it.

The reversal is a one-line monkeypatch of :func:`pressure.family_pressure`
(negate every score), so the key, the family grouping and the proliferator rule
are bit-for-bit the ones arm B uses.  Nothing in ``src`` is touched.

Run with ``--mode b`` or ``--mode brev``; the harness writes its usual JSON.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE.parent / "2026-09-05-scale-profile"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("b", "brev"), required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rest", nargs=argparse.REMAINDER, default=[])
    args = ap.parse_args()

    os.environ["FLAB2BP_PRESSURE_ORDER"] = "1"
    os.environ.pop("FLAB2BP_PRESSURE_CORRIDORS", None)

    from flab2bp.layout import pressure

    if args.mode == "brev":
        original = pressure.family_pressure

        def reversed_family_pressure(
            net_pressure: Sequence[int],
            families: Mapping[int, Sequence[int]],
        ) -> dict[int, int]:
            return {index: -value for index, value in original(net_pressure, families).items()}

        pressure.family_pressure = reversed_family_pressure  # type: ignore[assignment]
        #: `freeform` imported the module, not the function, so patching the
        #: module attribute is enough -- but assert it, because a `from ... import`
        #: anywhere upstream would make this silently measure arm B twice.
        from flab2bp.layout import freeform

        assert freeform.pressure_module.family_pressure is reversed_family_pressure

    import prof_harness

    sys.argv = ["prof_harness", *args.rest, "--out", args.out]
    return int(prof_harness.main())


if __name__ == "__main__":
    raise SystemExit(main())
