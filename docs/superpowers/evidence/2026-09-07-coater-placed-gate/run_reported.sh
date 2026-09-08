#!/usr/bin/env bash
# Step 4 of the gate: the REPORTED URL, six pairs per arm.
#
#   ./run_reported.sh
#
# `AMM_URL` is the URL from `docs/superpowers/plans/2026-09-06-self-loop-recipes.md:613`
# -- the one the defect was reported on.  Three candidate policies
# (no-proliferator, all-products, output-products) x two strategies (freeform,
# sequence-pair) = six pairs, run under BOTH arms.
#
# The probe is the coater probe from the experiment that justified this branch:
# `docs/superpowers/evidence/2026-09-07-exp-coater-node/probes/probe_cell.py`.
# It prints every validator finding, the coater count, and one
# `MERGE-UNDER-BODY` line per coater body that covers a belt tile with more than
# one belt predecessor -- the reported defect, stated directly.  The probe is
# run from each ARM'S OWN checkout, so it imports that arm's `flab2bp`.
#
# One build at a time: never run this while a round is running.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$HERE/reported"
mkdir -p "$OUT"

PLACED_ROOT=/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/coater-placed
BASE_ROOT=/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/coater-placed-base
PROBE=docs/superpowers/evidence/2026-09-07-exp-coater-node/probes/probe_cell.py

AMM_URL="https://factoriolab.github.io/dsp/list?z=eJxNjrsKwkAQRf9miql2JCbVNANGTJdGiI1oSJFi\
WUnIQ4v9dska5HbnHAbmBrWcjxR0YnHOOWahoLckP.5wtpO9IdsCMgJf8ahFOYNcON.rA2oBvOIga9DK\
loJWabYJfjCUGSXd1nz4hzRz4.7ZqdHQrXon7wdtosVTrMm.Ri1pVpEvAnpFKg__&v=11"

for ARM in baseline placed; do
  if [ "$ARM" = "baseline" ]; then ROOT="$BASE_ROOT"; else ROOT="$PLACED_ROOT"; fi
  cd "$ROOT" || exit 1
  : > "$OUT/$ARM.log"
  {
    echo "=== reported arm=$ARM ==="
    echo "root: $ROOT"
    echo "commit: $(git rev-parse HEAD)"
    echo "cpu pressure before (runnable, 5s mean): $("$HERE/cpu_pressure.sh")"
    date -Is
  } >> "$OUT/$ARM.log"
  for S in freeform sequence-pair; do
    for POLICY in no-proliferator all-products output-products; do
      echo "### $ARM $S $POLICY" >> "$OUT/$ARM.log"
      env -u FLAB2BP_COATER_NODE uv run python "$PROBE" \
        reported "$POLICY" --url "$AMM_URL" --strategy "$S" --budget 30 \
        --workers 32 2>&1 | grep -v "VIRTUAL_ENV\|^warning" >> "$OUT/$ARM.log"
    done
  done
  {
    echo "cpu pressure after (runnable, 5s mean): $("$HERE/cpu_pressure.sh")"
    echo "ARM $ARM REPORTED DONE $(date -Is)"
  } >> "$OUT/$ARM.log"
done
echo "REPORTED DONE $(date -Is)"
