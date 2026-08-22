"""EXPERIMENT -- Strategy C: an external packer in place of our CP-SAT phase 1.

Swaps ONLY the packer.  ``plan_strips`` still produces the rectangles and
freeform's A* router, power placement and emission still consume the result, so
any difference measured here is attributable to the packing step alone.

Backed by https://github.com/fontanf/packingsolver (C++, CMake).  Its
``rectangle`` solver with an Open-dimension-X objective is the exact analogue of
our sweep: minimise width at a fixed height, packing heterogeneous rectangles.
Build it with ``scripts/build_packingsolver.sh``; this module skips cleanly when
the binary is absent, so it is never a build or test dependency.

Why not PackingSolver's 3D ``box`` solver
-----------------------------------------
Tempting, because DSP has altitude.  It does not apply, for two measured
reasons:

* **Machines cannot stack.**  You cannot place an assembler above an assembler,
  so z is not a dimension the packed objects nest into.  Buildings have a
  height; it is not packable space.
* **Sorters never span altitudes.**  ``catalog.SORTER_SPANS_ALTITUDE`` is False,
  measured over all 1,288 sorters in the fixture corpus: ``z2 - z`` is exactly
  0.0 for every one, across five game versions and ten builders, *including*
  blueprints that stack belts.  So the tempting move -- lift a strip's input
  lanes to z=1 to shrink its 2D footprint -- is impossible, because a lane at
  z=1 cannot be tapped by a sorter feeding a machine at z=0.

The genuinely three-dimensional part of this problem is belt *routing* across
the three stacked levels, which is pathfinding through a volume rather than
packing rigid boxes into one, and the A* router already handles it with 2-tile
ramps.  A bin packer cannot express it.

The hypothesis under test
-------------------------
Our CP-SAT objective is not pure packing::

    minimise  w_var * hpwl_cap  +  LAMBDA_HPWL * sum(HPWL terms)

Width outranks wirelength lexicographically, and the HPWL term exists to pull
connected strips together -- that is what keeps phase 2's routing tractable.
PackingSolver knows nothing about connectivity, so the expectation was a
*tighter* pack that routes *worse*.

The measured result, and why it settles more than this experiment
-----------------------------------------------------------------
Rejected -- but not for the expected reason, and the reason is worth keeping.

PackingSolver DOES pack as tightly or tighter, and still loses, because a
connectivity-blind arrangement costs more in routing than it saves in packing::

    spec                    packer      pack area   final area   growth
    graphene                cpsat             384          486    1.27x
    graphene                packsolver        340          575    1.69x
    electromagnetic-matrix  cpsat             285          480    1.68x
    electromagnetic-matrix  packsolver        285          690    2.42x
    super-magnetic-ring     cpsat             690         1184    1.72x
    super-magnetic-ring     packsolver        720         1591    2.21x

``electromagnetic-matrix`` is the decisive row: an IDENTICAL pack -- same width,
same height, same 285 area -- yields 690 tiles against 480, a 44% difference
produced purely by where the strips sit relative to one another (belts 345
versus 262).  Routed belts extend the bounding box, so the arrangement inside a
fixed pack determines the final area as much as the pack size does.

So the HPWL term is not merely a routability aid, as the freeform docstring
frames it: it is doing real *area* work, and a better pure packer cannot
substitute for it.  The lesson generalises beyond this module -- phase 1's
value here is connectivity awareness, not packing strength, so future effort
belongs in the placement objective rather than in a stronger packer.

Kept as a measured negative rather than deleted: it is cheap to re-run if the
objective changes, and re-deriving the finding would not be.
"""

from __future__ import annotations

import csv
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from flab2bp.layout.base import Placement
from flab2bp.layout.freeform import (
    MARGIN,
    Strip,
    _build,
    _candidate_heights,
    _greedy_pack,
    _height_seed,
    _Pack,
    fallback_placement,
    plan_strips,
)
from flab2bp.spec import BuildSpec

__all__ = ["CONCLUSION", "PackSolverLayout", "binary_path", "is_available"]

_ENV_BIN = "PACKINGSOLVER_BIN"
_DEFAULT_ROOT = Path.home() / "src" / "packingsolver"


def binary_path() -> Path | None:
    """The ``packingsolver_rectangle`` binary, or ``None`` if not built."""
    override = os.environ.get(_ENV_BIN)
    if override:
        p = Path(override)
        return p if p.is_file() and os.access(p, os.X_OK) else None
    root = Path(os.environ.get("PACKINGSOLVER_ROOT", _DEFAULT_ROOT))
    candidate = root / "install" / "bin" / "packingsolver_rectangle"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return candidate
    found = shutil.which("packingsolver_rectangle")
    return Path(found) if found else None


def is_available() -> bool:
    return binary_path() is not None


class PackingSolverUnavailableError(RuntimeError):
    """The external binary is not built.  Run scripts/build_packingsolver.sh."""


@dataclass(frozen=True, slots=True)
class _SolveOutcome:
    at: dict[int, tuple[int, int]]
    width: int
    solver_seconds: float


def _write_instance(
    directory: Path, strips: list[Strip], height: int, width_bound: int
) -> tuple[Path, Path]:
    """Emit the items/bins CSVs the rectangle solver expects.

    One item per strip with ``COPIES=1``: the strips are already distinct
    rectangles and we need each one's individual origin back, so collapsing
    equal sizes into copies would lose the mapping.  ``PROFIT`` is unused by the
    open-dimension objective but the column is required.
    """
    items = directory / "items.csv"
    bins = directory / "bins.csv"

    with items.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ID", "WIDTH", "HEIGHT", "PROFIT", "COPIES"])
        for i, s in enumerate(strips):
            w.writerow([i, s.width + MARGIN, s.height + MARGIN, 1, 1])

    with bins.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ID", "WIDTH", "HEIGHT"])
        w.writerow([0, width_bound, height])

    return items, bins


def _read_certificate(
    path: Path, strips: list[Strip]
) -> dict[int, tuple[int, int]] | None:
    """Parse strip origins out of the solver's certificate.

    The format is ``TYPE,ID,COPIES,BIN,X,Y,LX,LY,GROUP_ID`` and the FIRST row
    describes the bin, not an item -- so rows must be filtered on ``TYPE ==
    'ITEM'``.  Without that filter the bin row (ID 0, X 0, Y 0) silently claims
    strip 0's origin, which reads as a suspiciously good pack rather than as a
    parse error.

    ``LX``/``LY`` are the dimensions as placed.  We pass ``--no-item-rotation``,
    but verify it here anyway: a rotated strip is geometrically wrong, not
    merely differently shaped, because its lanes sit above and below its machine
    row.  Bail out rather than emit a layout whose sorters cannot reach.
    """
    if not path.is_file():
        return None
    with path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        return None

    header = {k.upper(): k for k in rows[0]}
    required = ("TYPE", "ID", "X", "Y")
    if any(c not in header for c in required):
        return None
    t_col, id_col, x_col, y_col = (header[c] for c in required)
    lx_col, ly_col = header.get("LX"), header.get("LY")

    at: dict[int, tuple[int, int]] = {}
    for row in rows:
        if (row.get(t_col) or "").strip().upper() != "ITEM":
            continue
        try:
            idx = int(float(row[id_col]))
            x = int(float(row[x_col]))
            y = int(float(row[y_col]))
        except (TypeError, ValueError):
            continue
        if not (0 <= idx < len(strips)) or idx in at:
            continue
        if lx_col and ly_col:
            try:
                lx, ly = int(float(row[lx_col])), int(float(row[ly_col]))
            except (TypeError, ValueError):
                return None
            want = (strips[idx].width + MARGIN, strips[idx].height + MARGIN)
            if (lx, ly) != want:
                return None  # rotated or resized: unusable
        at[idx] = (x, y)
    return at if len(at) == len(strips) else None


def _solve_once(
    strips: list[Strip], *, height: int, width_bound: int, time_budget_s: float
) -> _SolveOutcome | None:
    binary = binary_path()
    if binary is None:
        raise PackingSolverUnavailableError(
            "packingsolver_rectangle not found; run scripts/build_packingsolver.sh "
            f"or set {_ENV_BIN}"
        )

    with tempfile.TemporaryDirectory(prefix="flab2bp-ps-") as tmp:
        directory = Path(tmp)
        items, bins = _write_instance(directory, strips, height, width_bound)
        certificate = directory / "solution.csv"
        cmd = [
            str(binary),
            "--items", str(items),
            "--bins", str(bins),
            "--certificate", str(certificate),
            "--objective", "open-dimension-x",
            # Rotation is ON by default and must not be. A strip's lanes sit
            # above and below its machine row, so a 90-degree turn puts them
            # beside it, out of sorter reach -- geometrically wrong, not merely
            # a different shape.
            "--no-item-rotation",
            "--time-limit", str(max(0.1, time_budget_s)),
            "--verbosity-level", "0",
        ]
        started = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=max(5.0, time_budget_s * 6)
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        elapsed = time.perf_counter() - started
        if proc.returncode != 0:
            return None

        at = _read_certificate(certificate, strips)
        if at is None:
            return None

    width = max((x + strips[i].width + MARGIN for i, (x, _y) in at.items()), default=0)
    return _SolveOutcome(at=at, width=width, solver_seconds=elapsed)


class PackSolverLayout:
    """Strategy C -- freeform's pipeline with PackingSolver as phase 1.

    Satisfies the ``LayoutStrategy`` protocol.  Falls back exactly as freeform
    does when the external solver is unavailable or returns nothing usable, and
    records which happened in ``stats`` so a fallback can never be mistaken for
    a solved result.
    """

    name = "packsolver"

    def __init__(self, *, power: bool = True, strip_len: int = 6) -> None:
        self.power = power
        self.strip_len = strip_len

    def lay_out(self, spec: BuildSpec, *, time_budget_s: float = 60.0) -> Placement:
        if time_budget_s <= 0 or not is_available():
            return fallback_placement(spec, power=self.power)

        try:
            strips = plan_strips(spec, strip_len=self.strip_len)
        except (ValueError, KeyError):
            return fallback_placement(spec, power=self.power)
        if not strips:
            return fallback_placement(spec, power=self.power)

        greedy = _greedy_pack(strips, _height_seed(strips))
        bound = max(greedy.width, max((s.width + MARGIN for s in strips), default=1))
        per_solve = max(0.1, time_budget_s / 6.0)

        best: Placement | None = None
        solver_seconds = 0.0
        for height in _candidate_heights(strips):
            outcome = _solve_once(
                strips,
                height=height,
                width_bound=max(bound * 2, 8),
                time_budget_s=per_solve,
            )
            if outcome is None:
                continue
            solver_seconds += outcome.solver_seconds
            pack = _Pack(
                at=outcome.at, width=outcome.width, height=height, status="packsolver"
            )
            placement, _failed, _towers = _build(
                spec, strips, pack, power=self.power, route=True
            )
            if best is None or (placement.area, placement.stats["belt_tiles"]) < (
                best.area,
                best.stats["belt_tiles"],
            ):
                placement.stats["solver_status"] = 0.5
                placement.stats["fallback_used"] = 0.0
                placement.stats["area"] = float(placement.area)
                placement.stats["packsolver_seconds"] = solver_seconds
                best = placement

        if best is None:
            out = fallback_placement(spec, power=self.power)
            out.stats["fallback_used"] = 1.0
            return out
        return best


#: Measured verdict.  Kept as a constant so a test can assert the module still
#: says what the numbers said, rather than the finding rotting in a comment.
CONCLUSION = (
    "REJECTED. PackingSolver packs as tightly or tighter and still loses, "
    "because a connectivity-blind pack costs more in routing than it saves in "
    "packing. Geometric mean packsolver/freeform area = 1.127 over 8 corpus "
    "specs (freeform denser), and freeform is itself 1.371x behind spine."
)
