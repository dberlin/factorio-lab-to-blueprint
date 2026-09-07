"""Run ONE gate cell through the shipped CLI and read what the CLI itself says.

**This harness monkeypatches NOTHING.**  That is the whole difference from
v2's ``run_cell.py`` (``../2026-09-07-hierarchical-v2/run_cell.py``), which had
to wrap four production functions because no shipped surface carried the
numbers a gate needs.  Task 1 of this plan
(``docs/superpowers/plans/2026-09-07-hierarchical-v3.md``, commit ``d89b78e3``)
carries the strategy's whole ``PlacementStats`` into every ``NoValidLayout``
attempt failure, and ``flab2bp.cli.main`` prints it on the refusal path as

    ``  stats <strategy>/<candidate>: key=value key=value ...``

on **stderr**, sorted by key.  Tasks 3 and 5 fill in the values.  So this
script captures stderr, parses that line, and reads nothing else.

Which of v2's spies that replaces, one by one:

* ``strategy.HierarchicalLayout._solve_round`` -> ``nogood_skips``.  v2 summed
  the return value of a wrapped ``_solve_round`` because ``stats["nogood_skips"]``
  was written only on the SUCCESS path and every v2 cell refused, so the key
  was unreachable in principle.  It is now on the refusal line.
* ``strategy.allocate_cuts`` -> ``player_fed``.  v2 counted
  ``CutAllocation.player_fed`` pairs through a wrapper because the quantity was
  neither a ``PlacementStats`` key nor anything ``-v`` printed.  It is now
  ``player_fed`` on the refusal line.
* ``compose.pack_with_access`` -> ``gap``, plus the reservation counts.  v2
  wrapped it because ``PackedCanvas.gap`` never left ``compose`` and
  ``ComposeResult`` did not carry it.  It is now ``compose_gap``, with
  ``port_demands``, ``reservation_missing``, ``reservation_degraded`` and
  ``unrouted_cuts`` beside it.

  **v4 adds ``reservation_partial`` beside those.**  Task 1 of the
  hierarchical-v4 plan made ``freeform._match_access_corridors`` COMMIT the
  surveyed partial it holds instead of returning ``{}`` wholesale when its
  validate/cut loop runs out of rounds; Task 2 made ``compose`` act on that
  partial and count it as BOTH ``reservation_partial`` and
  ``reservation_degraded``.  So ``reservation_degraded > 0`` together with
  ``reservation_partial == 0`` is now the only surviving proof the matcher
  still gives up wholesale; ``reservation_partial > 0`` on a cell is proof it
  does not, and ``reservation_degraded == 0`` with ``reservation_partial == 0``
  on a cell that composes means the matcher converged outright.  The key does
  not exist in the stats line at the plan's merge base (``1d2a790c``) -- a
  cell measured there simply lacks it, and this script does not invent a zero
  for an absent key; it is missing from the parsed dict entirely.
* ``pipeline.build`` -> area, buildings, validator errors.  v2 wrapped it to
  read the returned ``Build``.  On the REFUSAL path there is no ``Build`` to
  read on either branch, so nothing is lost; on the SUCCESS path the CLI's own
  ``_report`` prints ``<strategy> / <candidate>: N machines, A tiles, B
  buildings`` and, if any, ``  N VALIDATION ERRORS: {check: count}``, and this
  script parses those two lines instead of wrapping anything.

**Known limit, stated rather than papered over: the ``  stats `` line exists
only on the REFUSAL path.**  ``cli.main`` prints it from the ``NoValidLayout``
handler; ``_report`` prints no ``PlacementStats`` key at all.  So a cell that
EMITS a blueprint yields an area, a building count and a validator report and
NO stats line, and this script records ``"stats": {}`` for it rather than
inventing one.  That absence is itself reported by the gate.

    uv run python run_cell.py <sidecar.json> -- <the exact flab2bp argv>

stderr is TEED, not swallowed: every byte the CLI writes still reaches the
real stderr (and so the ``.log`` file ``run_large.sh`` redirects it into),
while a copy is parsed here.
"""

from __future__ import annotations

import contextlib
import json
import re
import sys
import time
from io import StringIO
from pathlib import Path
from typing import TextIO

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from flab2bp import cli  # noqa: E402

#: ``  stats hierarchical/all-products: blocks=9 compose_gap=2 ...``
_STATS = re.compile(r"^\s+stats (?P<pair>\S+): (?P<numbers>.*)$")
#: ``hierarchical / all-products: 812 machines, 12408 tiles, 940 buildings``
_BUILT = re.compile(
    r"^(?P<strategy>\S+) / (?P<candidate>.+?): (?P<machines>\d+) machines, "
    r"(?P<area>\d+) tiles, (?P<buildings>\d+) buildings$"
)
#: ``  17 VALIDATION ERRORS: {'geom.collide': 17}``
_ERRORS = re.compile(r"^\s+(?P<count>\d+) VALIDATION ERRORS: (?P<classes>\{.*\})$")
#: ``flab2bp: no valid layout for all-products after 60s: ...``
_REFUSAL = re.compile(r"^flab2bp: (?P<text>no valid layout .*)$")


class _Tee:
    """Write through to `stream` and keep a copy for parsing.

    ``fileno`` is NOT optional here and delegating it is not cosmetic.  The
    strategy's block pool is a ``spawn`` ``ProcessPoolExecutor``; constructing
    it starts ``multiprocessing.resource_tracker``, whose ``_launch`` builds
    ``fds_to_pass`` from ``sys.stderr.fileno()`` and then does
    ``tuple(sorted(map(int, passfds)))``.  A tee without a real ``fileno``
    makes that ``int(None)``, and the strategy's own guard converts the
    ``TypeError`` into ``block pool unavailable: TypeError: ...`` -- a REFUSAL
    that looks exactly like a branch defect and is entirely the harness's.
    That happened once here and is why this class does not subclass
    ``typing.TextIO``: its abstract method bodies return ``None`` silently
    rather than raising.
    """

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self.copy = StringIO()

    def write(self, text: str) -> int:
        self.copy.write(text)
        return self._stream.write(text)

    def flush(self) -> None:
        self._stream.flush()

    def fileno(self) -> int:
        return self._stream.fileno()

    def isatty(self) -> bool:
        return self._stream.isatty()

    def writable(self) -> bool:
        return True


def _parse(text: str) -> dict:
    """Everything the gate reports about one cell, from the CLI's own stderr."""
    stats: dict[str, dict[str, str]] = {}
    built: dict[str, str] = {}
    errors: dict[str, object] = {}
    refusals: list[str] = []
    for line in text.splitlines():
        match = _STATS.match(line)
        if match is not None:
            numbers: dict[str, str] = {}
            for token in match.group("numbers").split():
                key, _, value = token.partition("=")
                numbers[key] = value
            stats[match.group("pair")] = numbers
            continue
        match = _BUILT.match(line)
        if match is not None:
            built = match.groupdict()
            continue
        match = _ERRORS.match(line)
        if match is not None:
            errors = {"count": int(match.group("count")), "classes": match.group("classes")}
            continue
        match = _REFUSAL.match(line)
        if match is not None:
            refusals.append(match.group("text"))
    return {
        "stats": stats,
        "built": built,
        "validation_errors": errors,
        "refusals": refusals,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[2] != "--":
        print(__doc__)
        return 2
    sidecar = Path(argv[1])
    cell_argv = argv[3:]

    record: dict = {"argv": cell_argv}
    tee = _Tee(sys.stderr)
    started = time.perf_counter()
    try:
        with contextlib.redirect_stderr(tee):
            code = cli.main(cell_argv)
    except BaseException as exc:  # noqa: BLE001 - a crash is a recorded outcome
        record["crash"] = f"{type(exc).__name__}: {exc}"
        code = 70
    record["wall_s"] = round(time.perf_counter() - started, 2)
    record["exit"] = code
    record.update(_parse(tee.copy.getvalue()))

    # `-o <path>`: whether a blueprint was actually emitted, and how big.
    if "-o" in cell_argv:
        out = Path(cell_argv[cell_argv.index("-o") + 1])
        record["blueprint"] = {
            "path": str(out),
            "exists": out.exists(),
            "bytes": out.stat().st_size if out.exists() else 0,
        }
    sidecar.write_text(json.dumps(record, indent=1, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
