#!/usr/bin/env bash
# The `packed-hpwl` arm, on BOTH already-measured rounds and the same cells, so
# the table can show what the one-line pack-objective fix bought against
# `packed` as first measured.  Same operating point as every other arm:
# `--budget 30 --jobs 8`, freeform only (sequence-pair refuses a packed node
# before it packs anything).  Nothing else is re-tuned.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"
ARM=packed-hpwl
JOBS=8
cd "$ROOT"

URLS="iron-ingot magnetic-coil graphene electromagnetic-matrix plastic processor \
energy-matrix super-magnetic-ring casimir-crystal information-matrix quantum-chip \
universe-matrix"

AMM_URL="https://factoriolab.github.io/dsp/list?z=eJxNjrsKwkAQRf9miql2JCbVNANGTJdGiI1oSJFi\
WUnIQ4v9dska5HbnHAbmBrWcjxR0YnHOOWahoLckP.5wtpO9IdsCMgJf8ahFOYNcON.rA2oBvOIga9DK\
loJWabYJfjCUGSXd1nz4hzRz4.7ZqdHQrXon7wdtosVTrMm.Ri1pVpEvAnpFKg__&v=11"

for ROUND in roundA roundB; do
  OUT="$HERE/$ROUND"
  mkdir -p "$OUT"
  {
    echo "=== arm=$ARM round=$ROUND strategy=freeform jobs=$JOBS ==="
    echo "commit: $(git rev-parse --short HEAD)"
    echo "cpu pressure before (runnable, 5s mean): $("$HERE/cpu_pressure.sh")"
    date -Is
  } | tee -a "$OUT/$ARM.log"
  for URL in $URLS; do
    if grep -q "\"url_id\": \"$URL\"" "$OUT/$ARM.jsonl" 2>/dev/null; then
      echo "skip $URL (already recorded)" | tee -a "$OUT/$ARM.log"
      continue
    fi
    FLAB2BP_COATER_NODE="$ARM" uv run python scripts/audit.py \
      --only "$URL" --budget 30 --jobs "$JOBS" --strategy freeform \
      --max-seconds 3600 --json "$OUT/$ARM.jsonl" 2>&1 | tee -a "$OUT/$ARM.log"
    echo "  [$URL exit ${PIPESTATUS[0]}] cpu=$("$HERE/cpu_pressure.sh")" | tee -a "$OUT/$ARM.log"
  done
  echo "ARM $ARM $ROUND DONE $(date -Is)" | tee -a "$OUT/$ARM.log"

  : > "$OUT/$ARM-reported.log"
  for POLICY in no-proliferator all-products output-products; do
    echo "### $ARM freeform $POLICY" >> "$OUT/$ARM-reported.log"
    FLAB2BP_COATER_NODE="$ARM" uv run python "$HERE/probes/probe_cell.py" \
      reported "$POLICY" --url "$AMM_URL" --strategy freeform --budget 30 \
      --workers 32 2>&1 | grep -v "VIRTUAL_ENV\|^warning" >> "$OUT/$ARM-reported.log"
  done
  echo "ARM $ARM $ROUND REPORTED DONE $(date -Is)" | tee -a "$OUT/$ARM.log"
done
echo "PACKED-HPWL DONE"
