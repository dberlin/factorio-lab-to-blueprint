#!/bin/zsh
set -u
D=/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/debug-sorters/docs/superpowers/evidence/2026-09-06-sorter-upgrade/guard
(uptime; vmstat 1 3 | tail -1) > $D/flake-load.txt
for r in 1 2 3; do
  cd /home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/gate-base-c3cf24ef && uv run python scripts/audit.py --budget 30 --only universe-matrix --strategy sequence-pair --json $D/flake-base-um-round$r.jsonl > $D/flake-base-um-round$r.txt 2>&1
  cd /home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/debug-sorters && uv run python scripts/audit.py --budget 30 --only universe-matrix --strategy sequence-pair --json $D/flake-cand-um-round$r.jsonl > $D/flake-cand-um-round$r.txt 2>&1
done
echo DONE > $D/flake.done
