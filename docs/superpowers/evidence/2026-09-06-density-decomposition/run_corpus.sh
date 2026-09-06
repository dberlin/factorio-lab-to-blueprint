#!/usr/bin/env bash
# Throwaway driver: the 72-cell corpus at budget 30, once per configuration.
#
# The switches live in this directory's sitecustomize.py; PYTHONPATH is how they
# reach the forkserver children scripts/audit.py fans out over.
# audit.py exits non-zero whenever any cell misses, which is expected here
# (turning a mechanism off is meant to cost cells), so failures are recorded,
# not fatal.
set -u
ROOT=/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/spike-density
D=$ROOT/docs/superpowers/evidence/2026-09-06-density-decomposition
cd "$ROOT" || exit 1

{ date -Is; uptime; vmstat 1 3; } >"$D/load-at-start.txt" 2>&1

for cfg in base:0:0 nodirect:1:0 noshare:0:1 neither:1:1; do
  name=${cfg%%:*}
  rest=${cfg#*:}
  nd=${rest%%:*}
  ns=${rest##*:}
  rm -f "$D/audit-$name.jsonl"
  echo "=== $name (NO_DIRECT=$nd NO_SHARING=$ns) $(date -Is)"
  FLAB2BP_SPIKE_NO_DIRECT=$nd FLAB2BP_SPIKE_NO_SHARING=$ns PYTHONPATH=$D \
    uv run python scripts/audit.py --budget 30 --json "$D/audit-$name.jsonl"
  echo "=== $name exit $? $(date -Is)"
done
echo corpus-done
