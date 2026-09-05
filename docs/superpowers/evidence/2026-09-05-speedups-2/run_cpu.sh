#!/bin/zsh
set -u
ROOT=/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/speedups-2
OUT=$ROOT/docs/superpowers/evidence/2026-09-05-speedups-2
MALL=$(head -c 100000 $ROOT/docs/superpowers/evidence/2026-09-05-scale-levers/mall-profile/url.txt | tr -d '\n')
L=$OUT/cpu-log.txt

r() { # tag strategy args...
  local tag=$1; shift; local s=$1; shift
  echo "== $tag/$s $(date +%T) $(uptime|sed 's/.*load/load/')" >> $L
  ( cd $ROOT && uv run python $OUT/cpu_trace.py "$@" --strategy $s --out $OUT/cpu-$tag-$s.json >> $L 2>&1 )
}
p() { local tag=$1; shift; r $tag freeform "$@" & local a=$!; r $tag sequence-pair "$@" & wait $a $!; }

p um60  universe-matrix --rate 60  --budget 30
p qc180 quantum-chip    --rate 180 --budget 30
p gm200 gravity-matrix  --rate 200 --budget 30
p um120 universe-matrix --rate 120 --budget 30
p mall  mall --url "$MALL" --policy all-products --budget 100
echo "DONE cpu $(date +%T)" >> $L
