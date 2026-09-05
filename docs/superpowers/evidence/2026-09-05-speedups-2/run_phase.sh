#!/bin/zsh
# Phase-shim runs (real seconds) for the five cells x two strategies.
# Two at a time, per the box rule.  $1 = "plain" | "cprof"
set -u
ROOT=/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/speedups-2
OUT=$ROOT/docs/superpowers/evidence/2026-09-05-speedups-2
H=$ROOT/docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py
MALL=$(head -c 100000 $ROOT/docs/superpowers/evidence/2026-09-05-scale-levers/mall-profile/url.txt | tr -d '\n')
MODE=${1:-plain}
FLAG=""
[[ $MODE == cprof ]] && FLAG="--cprofile"

run() {  # name strategy extra...
  local name=$1; shift
  local strat=$1; shift
  echo "== $name/$strat $MODE $(date +%T) $(uptime | sed 's/.*load/load/')" >> $OUT/$MODE-log.txt
  ( cd $ROOT && uv run python $H "$@" --strategy $strat $FLAG \
      --out $OUT/$MODE-$name-$strat >> $OUT/$MODE-log.txt 2>&1 )
}

pair() {  # name  args...
  local name=$1; shift
  run $name freeform "$@" &
  local p1=$!
  run $name sequence-pair "$@" &
  wait $p1 $!
}

pair um60   universe-matrix --rate 60  --budget 30
pair qc180  quantum-chip    --rate 180 --budget 30
pair gm200  gravity-matrix  --rate 200 --budget 30
pair um120  universe-matrix --rate 120 --budget 30
pair mall   mall --url "$MALL" --policy all-products --budget 100
echo "DONE $MODE $(date +%T)" >> $OUT/$MODE-log.txt
