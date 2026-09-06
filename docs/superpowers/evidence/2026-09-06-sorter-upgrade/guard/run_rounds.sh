#!/bin/zsh
set -u
D=/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/debug-sorters/docs/superpowers/evidence/2026-09-06-sorter-upgrade/guard
cd /home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/gate-base-c3cf24ef && (uptime; vmstat 1 3 | tail -1) > $D/baseline-round1-load.txt && uv run python scripts/audit.py --budget 30 --json $D/baseline-round1.jsonl > $D/baseline-round1.txt 2>&1; echo "baseline exit $?" >> $D/baseline-round1-load.txt
cd /home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/debug-sorters && (uptime; vmstat 1 3 | tail -1) > $D/candidate-round1-load.txt && uv run python scripts/audit.py --budget 30 --json $D/candidate-round1.jsonl > $D/candidate-round1.txt 2>&1; echo "candidate exit $?" >> $D/candidate-round1-load.txt
echo DONE > $D/rounds.done
