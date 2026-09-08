#!/usr/bin/env bash
# One measurement arm of the coater-node experiment, ONE BUILD AT A TIME.
#
#   ./run_arm.sh <arm> <round> [strategy]
#
# `arm` is off|seat|packed|placed, `strategy` is audit.py's (`both` by default,
# `freeform` for the `packed` arm -- sequence-pair refuses a packed node before
# it packs anything; see the README).
#
# 72 audit cells (36 specs x 2 strategies) at `--budget 30`, then the reported
# URL.  `--jobs 1` is not a convenience: three other agents build on this box,
# and cells running in parallel would make every timing in the report a
# measurement of the neighbours.
set -uo pipefail
ARM="${1:?arm}"
ROUND="${2:-1}"
STRATEGY="${3:-both}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"
OUT="$HERE/round$ROUND"
mkdir -p "$OUT"

cd "$ROOT"
{
  echo "=== arm=$ARM round=$ROUND strategy=$STRATEGY ==="
  echo "commit: $(git rev-parse --short HEAD)"
  echo "cpu pressure before (runnable, 5s mean): $("$HERE/cpu_pressure.sh")"
  date -Is
} | tee "$OUT/$ARM.log"

FLAB2BP_COATER_NODE="$ARM" uv run python scripts/audit.py \
  --budget 30 --jobs 1 --strategy "$STRATEGY" --max-seconds 7200 \
  --json "$OUT/$ARM.jsonl" 2>&1 | tee -a "$OUT/$ARM.log"
AUDIT_EXIT=${PIPESTATUS[0]}

{
  echo "audit exit: $AUDIT_EXIT"
  echo "cpu pressure after audit: $("$HERE/cpu_pressure.sh")"
  date -Is
} | tee -a "$OUT/$ARM.log"

# The reported URL from `docs/superpowers/plans/2026-09-06-self-loop-recipes.md`.
AMM_URL="https://factoriolab.github.io/dsp/list?z=eJxNjrsKwkAQRf9miql2JCbVNANGTJdGiI1oSJFi\
WUnIQ4v9dska5HbnHAbmBrWcjxR0YnHOOWahoLckP.5wtpO9IdsCMgJf8ahFOYNcON.rA2oBvOIga9DK\
loJWabYJfjCUGSXd1nz4hzRz4.7ZqdHQrXon7wdtosVTrMm.Ri1pVpEvAnpFKg__&v=11"

if [ "$STRATEGY" = "both" ]; then
  REPORTED_STRATEGIES="freeform sequence-pair"
else
  REPORTED_STRATEGIES="$STRATEGY"
fi
for S in $REPORTED_STRATEGIES; do
  for POLICY in no-proliferator all-products output-products; do
    echo "### $ARM $S $POLICY" | tee -a "$OUT/$ARM-reported.log"
    FLAB2BP_COATER_NODE="$ARM" uv run python \
      "$HERE/probes/probe_cell.py" reported "$POLICY" \
      --url "$AMM_URL" --strategy "$S" --budget 30 --workers 128 \
      2>&1 | grep -v "VIRTUAL_ENV\|^warning" | tee -a "$OUT/$ARM-reported.log"
  done
done
{
  echo "cpu pressure after reported: $("$HERE/cpu_pressure.sh")"
  date -Is
} | tee -a "$OUT/$ARM.log"
