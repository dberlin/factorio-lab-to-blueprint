#!/bin/zsh
# The one partial disagreement in the three rounds: sequence-pair
# universe-matrix/all-products, REFUSED in BASELINE round 2 and CLEAN in the
# baseline's other two rounds and in all three candidate rounds.  Three more
# runs of that cell on each tree, one audit at a time, to place the refusal.
set -u
BASE=/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/gate-base-4b51f81f
CAND=/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/exp-pressure
OUT=$CAND/docs/superpowers/evidence/2026-09-06-exp-pressure-gate

unset FLAB2BP_PRESSURE_CORRIDORS
unset VIRTUAL_ENV

{ echo "== flake re-runs $(date -Is)"; uptime; vmstat 1 3 | tail -1 } > $OUT/flake-load.txt 2>&1

for i in 1 2 3; do
  for side in base cand; do
    if [[ $side == base ]]; then tree=$BASE; unset FLAB2BP_PRESSURE_ORDER
    else tree=$CAND; export FLAB2BP_PRESSURE_ORDER=1; fi
    cd $tree
    rm -f $OUT/flake-$side-um-round$i.jsonl
    uv run python scripts/audit.py --budget 30 --only universe-matrix \
      --strategy sequence-pair --json $OUT/flake-$side-um-round$i.jsonl \
      > $OUT/flake-$side-um-round$i.txt 2>&1
    echo "DONE flake-$side-um-round$i rows $(wc -l < $OUT/flake-$side-um-round$i.jsonl)"
  done
done
echo "ALL FLAKE DONE $(date -Is)"
