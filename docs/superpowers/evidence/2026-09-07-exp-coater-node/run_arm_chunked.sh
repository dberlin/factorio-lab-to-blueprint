#!/usr/bin/env bash
# One arm, run ONE URL AT A TIME, appending to the same JSONL.
#
#   ./run_arm_chunked.sh <arm> <round> [strategy]
#
# `audit.py` writes its JSONL only when the whole run finishes, so a native
# crash in one cell throws away every cell before it -- which is exactly what
# happened to the first `seat` run (SIGSEGV at cell 13 of 72, 12 cells lost).
# Chunking by URL bounds that loss to one URL and lets the arm be completed by
# re-running just the URLs that are missing.
set -uo pipefail
ARM="${1:?arm}"
ROUND="${2:-1}"
STRATEGY="${3:-both}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../../.." && pwd)"
OUT="$HERE/round$ROUND"
mkdir -p "$OUT"
cd "$ROOT"

URLS="iron-ingot magnetic-coil graphene electromagnetic-matrix plastic processor \
energy-matrix super-magnetic-ring casimir-crystal information-matrix quantum-chip \
universe-matrix"

{
  echo "=== arm=$ARM round=$ROUND strategy=$STRATEGY (chunked) ==="
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
    --only "$URL" --budget 30 --jobs 1 --strategy "$STRATEGY" --max-seconds 3600 \
    --json "$OUT/$ARM.jsonl" 2>&1 | tee -a "$OUT/$ARM.log"
  echo "  [$URL exit ${PIPESTATUS[0]}] cpu=$("$HERE/cpu_pressure.sh")" | tee -a "$OUT/$ARM.log"
done
echo "CHUNKED ARM $ARM DONE" | tee -a "$OUT/$ARM.log"
