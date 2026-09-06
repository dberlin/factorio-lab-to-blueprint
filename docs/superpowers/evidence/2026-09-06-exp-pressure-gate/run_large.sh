#!/bin/zsh
# Step 3: the four large URLs at 60 s, freeform, both trees, two replicates each.
# 16 runs, at most TWO in flight at any moment, and never while an audit round is
# running (this script is only started after run_rounds.sh has printed ALL ROUNDS
# DONE).  Each tree runs its OWN copy of prof_harness.py so `uv run` imports that
# tree's `flab2bp` and its own `scripts/route_profile.py` shim -- the candidate's
# shim is the one that carries the `net_pressure` keyword.
set -u
BASE=/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/gate-base-4b51f81f
CAND=/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/exp-pressure
OUT=$CAND/docs/superpowers/evidence/2026-09-06-exp-pressure-gate
URLS=$CAND/docs/superpowers/evidence/2026-09-05-speedups-2/large-urls/urls.txt
mkdir -p $OUT/runs-large

unset FLAB2BP_PRESSURE_CORRIDORS
unset VIRTUAL_ENV

url_of () { grep -P "^$1\t" $URLS | cut -f2 }

one () {          # one <tree> <side> <cell> <policy> <rep>
  tree=$1; side=$2; cell=$3; policy=$4; rep=$5
  tag=$cell-$policy-$side-r$rep
  cd $tree
  if [[ $side == cand ]]; then export FLAB2BP_PRESSURE_ORDER=1; else unset FLAB2BP_PRESSURE_ORDER; fi
  uv run python docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py \
    $cell --url "$(url_of $cell)" --policy $policy --strategy freeform \
    --budget 60 --out $OUT/runs-large/$tag \
    > $OUT/runs-large/$tag.log 2>&1
  echo "DONE $tag exit $?"
}

# Two at a time: one baseline and one candidate of the same cell, so a load
# excursion hits both sides of a pair equally.
pair () {         # pair <cell> <policy> <rep>
  { echo "== $1 $2 rep$3  $(date -Is)"; uptime; vmstat 1 3 | tail -1 } \
    >> $OUT/large-load.txt 2>&1
  ( one $BASE base $1 $2 $3 ) &
  ( one $CAND cand $1 $2 $3 ) &
  wait
}

for rep in 1 2; do
  pair belt3 all-products    $rep
  pair belt3 no-proliferator $rep
  pair mall  all-products    $rep
  pair zurl2 all-products    $rep
done
echo "ALL LARGE DONE $(date -Is)"
