#!/usr/bin/env bash
# The moved-cell CONTROL: re-run only the url_ids carrying a cell whose area
# moved in the paired round, once more on each tree, to decide whether those
# cells move because of this branch or because they are the corpus's own
# run-to-run noise floor at a 30 s budget.
#
# This is a CONTROL, not a re-measurement of the guard.  No gate clause is read
# from it: clause (d) is decided by `compare-round1.txt` / `judge-round1.txt`
# alone, and it passes there outright (72 = 72 CLEAN, 0 regressions, 0 INVALID,
# 0 CRASH).  v2's gate ran the same control for the same reason
# (`../2026-09-07-hierarchical-v2/gate.md` §5b, `moved-*-r2`).
#
# Why it is worth two more audits HERE specifically, where v2 could argue the
# point from the diff alone: v2's `src/` diff touched `freeform.py` not at all,
# so it could say "no line either audited arm executes differs between the
# trees".  THIS branch changes `freeform.py` by ~100 lines on the DEFAULT path
# (Task 4's per-demand `goals` and `_PORT_ACCESS_PROBE_KEEP`), and four of the
# seven moved cells are freeform.  The reduction to the old behaviour when
# `goals` is absent was verified site by site by Task 4's implementer and again
# by its reviewer, but that is an argument; this is a measurement.
#
# Same procedure as run_guard.sh: root as an argument, wait for the audit slot
# before each invocation, restore the branch on every exit path.
#
# Usage: run_moved.sh <worktree-root>
set -eu
cd "${1:?usage: run_moved.sh <worktree-root>}" || exit 1
DIR=docs/superpowers/evidence/2026-09-07-hierarchical-v3
BASE=1ce8a0d3
BRANCH=hierarchical-v3
TMP=/tmp/v3gate
# The five url_ids carrying the seven cells that moved in the paired round.
ONLY=universe-matrix,super-magnetic-ring,plastic,magnetic-coil,quantum-chip

# `pgrep` does NOT self-match: it excludes its own PID (procps-ng 4.0.6 here,
# and every BSD does the same).  The plan's earlier warning that it "matches its
# OWN command line and always returns a hit" was backwards, and its prescribed
# replacement, `ps -eo args | grep -cE ...`, is the form that actually
# self-matches, because `ps` lists the pipeline's own `grep`.  Reading that
# literally cost this gate a wasted detached checkout.
#
# The `[s]` bracket handles the one false positive `pgrep -f` CAN produce: an
# ENCLOSING `bash -c "... pattern ..."` whose argv contains the pattern.  The
# literal text below reads `[s]cripts/audit\.py`, which the regex itself does
# not accept, so no command line carrying this check can ever match it.
#
# Measured on this box with 9 real audit processes running: this form returned
# exactly those 9 and did not include the invoking shell.  The narrower
# `pgrep -fc 'python[0-9.]* +[^ ]*scripts/audit\.py'` is also self-match-proof
# but matched only 2 of the 9, missing the forkserver children.
audits_running() {
  pgrep -af '[s]cripts/audit\.py' || true
}

restore_branch() {
  local code=$?
  if [ "$(git rev-parse --abbrev-ref HEAD)" != "$BRANCH" ]; then
    echo "restoring $BRANCH from detached HEAD" >&2
    git checkout "$BRANCH" >&2 || echo "COULD NOT RESTORE $BRANCH" >&2
  fi
  return "$code"
}
trap restore_branch EXIT

wait_for_slot() {
  local waited=0 lines n
  while :; do
    lines="$(audits_running)"
    n="$(printf '%s' "$lines" | grep -c . || true)"
    if [ "$n" = "0" ]; then
      echo "audit-count check: 0 (slot free after ${waited}s)"
      return 0
    fi
    [ "$waited" = "0" ] && { echo "audit-count check: $n -- waiting"; printf '%s\n' "$lines" | cut -c1-110; }
    sleep 20
    waited=$((waited + 20))
    [ "$waited" -gt 5400 ] && { echo "GIVING UP after ${waited}s" >&2; exit 2; }
  done
}

half() {  # <name> <outdir>
  local name="$1" out="$2"
  mkdir -p "$out"
  rm -f "$out/moved-$name-r2.jsonl"
  wait_for_slot
  (uptime; vmstat 1 3 | tail -1) > "$out/moved-$name-r2-load.txt" 2>&1
  echo "=== moved $name half: HEAD $(git rev-parse --short HEAD) ==="
  uv run python scripts/audit.py --budget 30 --only "$ONLY" --json "$out/moved-$name-r2.jsonl" \
      > "$out/moved-$name-r2.txt" 2>&1 || true
  echo "moved $name done: $(wc -l < "$out/moved-$name-r2.jsonl") rows"
}

[ -z "$(git status --short)" ] || { echo "REFUSING: tree not clean" >&2; exit 2; }
[ "$(git rev-parse --abbrev-ref HEAD)" = "$BRANCH" ] || { echo "REFUSING: not on $BRANCH" >&2; exit 2; }
echo "start: on $BRANCH at $(git rev-parse --short HEAD), tree clean"

# Candidate half FIRST, on the branch, then the baseline half after one
# checkout -- so the two halves run back to back with only a checkout between
# them, as v2's control did.
half candidate "$DIR"

git checkout --detach "$BASE"
echo "detached at $(git rev-parse --short HEAD)"
half baseline "$TMP"
git checkout "$BRANCH"
echo "returned: on $(git rev-parse --abbrev-ref HEAD) at $(git rev-parse --short HEAD)"

cp "$TMP"/moved-baseline-r2.jsonl "$TMP"/moved-baseline-r2.txt "$TMP"/moved-baseline-r2-load.txt "$DIR"/
uv run python "$DIR/judge.py" "$DIR/moved-baseline-r2.jsonl" "$DIR/moved-candidate-r2.jsonl" \
    > "$DIR/judge-moved-r2.txt" 2>&1 || true
echo "control written"
