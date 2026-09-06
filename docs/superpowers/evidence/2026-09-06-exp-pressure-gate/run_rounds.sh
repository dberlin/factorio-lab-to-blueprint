#!/bin/zsh
# Six paired audit rounds, strictly sequential, interleaved B1 C1 B2 C2 B3 C3.
# Baseline rounds run in the throwaway 4b51f81f worktree with no pressure env.
# Candidate rounds run in exp-pressure with FLAB2BP_PRESSURE_ORDER=1 exported and
# FLAB2BP_PRESSURE_CORRIDORS deliberately left unset (arm A stays off).
# audit.py exits 1 and prints NOT CLEAN whenever any cell refuses; that is
# expected on this corpus, so the exit code is recorded, not obeyed.
set -u
BASE=/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/gate-base-4b51f81f
CAND=/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/exp-pressure
OUT=$CAND/docs/superpowers/evidence/2026-09-06-exp-pressure-gate

unset FLAB2BP_PRESSURE_CORRIDORS
unset VIRTUAL_ENV

run () {          # run <tree> <name> <on|off>
  tree=$1; name=$2; arm=$3
  { echo "== $name  $(date -Is)"; uptime; vmstat 1 3 | tail -1 } > $OUT/$name-load.txt 2>&1
  cd $tree
  # `--json` takes a PATH and APPENDS, so a stale file would double the rows.
  rm -f $OUT/$name.jsonl
  if [[ $arm == on ]]; then
    FLAB2BP_PRESSURE_ORDER=1 uv run python scripts/audit.py --budget 30 \
      --json $OUT/$name.jsonl > $OUT/$name.txt 2>&1
  else
    unset FLAB2BP_PRESSURE_ORDER
    uv run python scripts/audit.py --budget 30 \
      --json $OUT/$name.jsonl > $OUT/$name.txt 2>&1
  fi
  echo "exit $? rows $(wc -l < $OUT/$name.jsonl)" >> $OUT/$name-load.txt
  echo "DONE $name $(date -Is) rows $(wc -l < $OUT/$name.jsonl)"
}

run $BASE baseline-round1 off
run $CAND candidate-round1 on
run $BASE baseline-round2 off
run $CAND candidate-round2 on
run $BASE baseline-round3 off
run $CAND candidate-round3 on
echo "ALL ROUNDS DONE $(date -Is)"
