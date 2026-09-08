#!/usr/bin/env bash
# One full ROUND: every arm, every cell, at one fixed operating point.
#
#   ./run_round.sh <round-name>
#
# `--jobs 8` runs eight cells at a time with sixteen CP-SAT workers each.
# `audit.py` sizes workers as `cores // jobs`, so a run targets the box's whole
# core count WHATEVER `--jobs` is: parallelism here trades workers-per-cell
# against cells-in-flight and does NOT oversubscribe.  That is also why the
# ARMS still run one after another -- two arms at once would be 2x the box --
# and why every arm must use the SAME `--jobs`, since a cell solved by sixteen
# workers is not the same experiment as one solved by a hundred and twenty-eight.
#
# `packed` is freeform-only: sequence-pair refuses a packed coater node before
# it packs anything (`_variant_search_inputs`, see README §5).
#
# Chunked by URL because `audit.py` writes its JSONL only at the end, and a
# native SIGSEGV in one cell threw away twelve completed cells on the first
# attempt.  Re-running the script skips URLs already recorded.
set -uo pipefail
ROUND="${1:?round name}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"
OUT="$HERE/$ROUND"
JOBS=8
mkdir -p "$OUT"
cd "$ROOT"

URLS="iron-ingot magnetic-coil graphene electromagnetic-matrix plastic processor \
energy-matrix super-magnetic-ring casimir-crystal information-matrix quantum-chip \
universe-matrix"

AMM_URL="https://factoriolab.github.io/dsp/list?z=eJxNjrsKwkAQRf9miql2JCbVNANGTJdGiI1oSJFi\
WUnIQ4v9dska5HbnHAbmBrWcjxR0YnHOOWahoLckP.5wtpO9IdsCMgJf8ahFOYNcON.rA2oBvOIga9DK\
loJWabYJfjCUGSXd1nz4hzRz4.7ZqdHQrXon7wdtosVTrMm.Ri1pVpEvAnpFKg__&v=11"

for ARM in off seat placed packed; do
  if [ "$ARM" = "packed" ]; then STRATEGY=freeform; else STRATEGY=both; fi
  {
    echo "=== arm=$ARM round=$ROUND strategy=$STRATEGY jobs=$JOBS ==="
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
      --only "$URL" --budget 30 --jobs "$JOBS" --strategy "$STRATEGY" \
      --max-seconds 3600 --json "$OUT/$ARM.jsonl" 2>&1 | tee -a "$OUT/$ARM.log"
    echo "  [$URL exit ${PIPESTATUS[0]}] cpu=$("$HERE/cpu_pressure.sh")" | tee -a "$OUT/$ARM.log"
  done
  echo "ARM $ARM DONE $(date -Is)" | tee -a "$OUT/$ARM.log"

  if [ "$STRATEGY" = "both" ]; then RS="freeform sequence-pair"; else RS="$STRATEGY"; fi
  : > "$OUT/$ARM-reported.log"
  for S in $RS; do
    for POLICY in no-proliferator all-products output-products; do
      echo "### $ARM $S $POLICY" >> "$OUT/$ARM-reported.log"
      FLAB2BP_COATER_NODE="$ARM" uv run python "$HERE/probes/probe_cell.py" \
        reported "$POLICY" --url "$AMM_URL" --strategy "$S" --budget 30 \
        --workers 32 2>&1 | grep -v "VIRTUAL_ENV\|^warning" \
        >> "$OUT/$ARM-reported.log"
    done
  done
  echo "ARM $ARM REPORTED DONE $(date -Is)" | tee -a "$OUT/$ARM.log"
done
echo "ROUND $ROUND DONE"
