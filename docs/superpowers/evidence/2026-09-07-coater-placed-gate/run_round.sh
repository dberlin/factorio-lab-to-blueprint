#!/usr/bin/env bash
# One full ROUND of the coater-placed gate: both arms, all 72 cells, at one
# fixed operating point.
#
#   ./run_round.sh roundA
#   ./run_round.sh roundB
#
# THE TWO ARMS
#
#   baseline -- the branch's merge base `2e861af0` (docs-only on top of shipped
#               `master@ffc5e88b`), run from its OWN detached worktree with its
#               own `uv sync`, with NO env var set.  A separate checkout rather
#               than `FLAB2BP_COATER_NODE=off` on this branch, because the `off`
#               path on this branch is code that was edited by this branch and
#               therefore is not the thing under test.
#   placed   -- this branch's HEAD, NO env var set: `placed` is the new default.
#
# `env -u FLAB2BP_COATER_NODE` on both arms, so an inherited value from the
# shell can never silently pick an arm.
#
# `--jobs 8` runs eight cells at a time; `audit.py` sizes CP-SAT workers as
# `cores // jobs`, so ONE run targets the whole box whatever `--jobs` is.  That
# is why the arms run one after another: two arms at once is 2x the box and
# every timing becomes a measurement of the neighbour.
#
# Chunked by URL because `audit.py` appends its JSONL only after its loop, and a
# native SIGSEGV in one cell threw away twelve completed cells on the coater
# experiment's first attempt.  Re-running this script skips URLs already
# recorded in the arm's JSONL.
set -uo pipefail
ROUND="${1:?round name (roundA|roundB)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$HERE/$ROUND"
JOBS=8
BUDGET=30
MAX_SECONDS=3600

PLACED_ROOT=/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/coater-placed
BASE_ROOT=/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/coater-placed-base

mkdir -p "$OUT"

URLS="iron-ingot magnetic-coil graphene electromagnetic-matrix plastic processor \
energy-matrix super-magnetic-ring casimir-crystal information-matrix quantum-chip \
universe-matrix"

for ARM in baseline placed; do
  if [ "$ARM" = "baseline" ]; then ROOT="$BASE_ROOT"; else ROOT="$PLACED_ROOT"; fi
  cd "$ROOT" || exit 1
  {
    echo "=== arm=$ARM round=$ROUND strategy=both jobs=$JOBS budget=$BUDGET ==="
    echo "root: $ROOT"
    echo "commit: $(git rev-parse HEAD)"
    echo "flab2bp: $(env -u FLAB2BP_COATER_NODE uv run python -c 'import flab2bp; print(flab2bp.__file__)' 2>/dev/null | tail -n 1)"
    echo "cpu pressure before (runnable, 5s mean): $("$HERE/cpu_pressure.sh")"
    date -Is
  } | tee -a "$OUT/$ARM.log"
  for URL in $URLS; do
    if grep -q "\"url_id\": \"$URL\"" "$OUT/$ARM.jsonl" 2>/dev/null; then
      echo "skip $URL (already recorded)" | tee -a "$OUT/$ARM.log"
      continue
    fi
    env -u FLAB2BP_COATER_NODE uv run python scripts/audit.py \
      --only "$URL" --budget "$BUDGET" --jobs "$JOBS" --strategy both \
      --max-seconds "$MAX_SECONDS" --json "$OUT/$ARM.jsonl" 2>&1 | tee -a "$OUT/$ARM.log"
    echo "  [$URL exit ${PIPESTATUS[0]}] cpu=$("$HERE/cpu_pressure.sh")" | tee -a "$OUT/$ARM.log"
  done
  {
    echo "cpu pressure after (runnable, 5s mean): $("$HERE/cpu_pressure.sh")"
    echo "ARM $ARM $ROUND DONE $(date -Is)"
  } | tee -a "$OUT/$ARM.log"
done
echo "ROUND $ROUND DONE $(date -Is)"
