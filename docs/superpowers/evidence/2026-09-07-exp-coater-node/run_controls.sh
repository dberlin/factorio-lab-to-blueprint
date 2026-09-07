#!/usr/bin/env bash
# The harness's own PASS condition: a `no-proliferator` spec must build the
# SAME BLUEPRINT in every arm, because the switch touches nothing on a path
# with no sprayed lane.
#
# It has to be asked at a DETERMINISTIC operating point.  Two runs of the SAME
# arm at `--jobs 8` differ on 8 of 72 cells (see README §5): CP-SAT with more
# than one worker under a wall-clock limit is not reproducible, so an
# arm-versus-arm digest comparison at that operating point measures the solver's
# variance and not the switch.  `--workers 1` is `base.DETERMINISTIC_WORKERS`,
# which exists for exactly this: "the one place reproducibility is the property
# under test rather than an obstacle to measuring one".
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"
OUT="$HERE/controls"
mkdir -p "$OUT"
cd "$ROOT"

URLS="iron-ingot magnetic-coil graphene electromagnetic-matrix plastic processor \
energy-matrix super-magnetic-ring casimir-crystal information-matrix quantum-chip \
universe-matrix"

: > "$OUT/controls.log"
for URL in $URLS; do
  for ARM in off seat packed placed; do
    printf '%-24s %-8s ' "$URL" "$ARM" | tee -a "$OUT/controls.log"
    FLAB2BP_COATER_NODE="$ARM" uv run python "$HERE/probes/probe_cell.py" \
      "$URL" no-proliferator --budget 30 --workers 1 2>&1 \
      | grep -v "VIRTUAL_ENV\|^warning" \
      | grep -E "digest=|REFUSED|CRASH" | tr '\n' ' ' | tee -a "$OUT/controls.log"
    echo | tee -a "$OUT/controls.log"
  done
done
echo "CONTROLS DONE" | tee -a "$OUT/controls.log"
