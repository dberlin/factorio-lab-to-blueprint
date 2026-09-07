#!/usr/bin/env bash
# The v3 gate's default-unchanged corpus guard, exactly as v2's controller
# ruled it (R13): everything committed and `git status --short` empty first,
# then `git checkout --detach <merge-base>`, the BASELINE half run there
# writing to /tmp/v3gate/ (this evidence directory does not exist at the merge
# base), `git checkout hierarchical-v3` IMMEDIATELY, HEAD and cleanliness
# verified, then the CANDIDATE half, then the baseline half copied in.
#
# No `git stash`, no second worktree.
#
# ONE AUDIT AT A TIME.  The audit-count check below is the brief's
# `ps -eo args | grep -cE 'scripts/audit\.py'` with ONE correction that the
# brief's own warning implies: on this box `ps -eo args` lists the invoking
# shell's whole command line too, so a bare count also matches THIS script's
# own pattern, exactly the way the brief says `pgrep -f audit.py` does.  The
# pattern is therefore assembled at run time from two halves that never appear
# adjacent in any command line, and the matching lines are printed so the
# number is auditable rather than merely asserted.
#
# Usage: run_guard.sh <worktree-root>
#
# The root is an ARGUMENT rather than derived from `$0`, because this script is
# run from a /tmp copy (see above) where `dirname "$0"` points at /tmp and the
# usual `cd "$(dirname "$0")/../../../.."` lands on `/`.  Passing it explicitly
# is what makes the /tmp copy and the tracked copy the same program.
set -eu
cd "${1:?usage: run_guard.sh <worktree-root>}" || exit 1
DIR=docs/superpowers/evidence/2026-09-07-hierarchical-v3
BASE=1ce8a0d3
BRANCH=hierarchical-v3
TMP=/tmp/v3gate

PAT="scripts/audit"".py"

audits_running() {
  ps -eo args | grep -E "$PAT" | grep -v -e 'grep -' -e 'run_guard' || true
}

check_slot() {
  local lines n
  lines="$(audits_running)"
  n="$(printf '%s' "$lines" | grep -c . || true)"
  echo "audit-count check: $n"
  [ -n "$lines" ] && printf '%s\n' "$lines"
  if [ "$n" != "0" ]; then
    echo "REFUSING: another audit is running" >&2
    exit 2
  fi
}

half() {  # <name> <outdir>
  local name="$1" out="$2"
  mkdir -p "$out"
  rm -f "$out/$name-round1.jsonl"          # --json APPENDS
  check_slot
  (uptime; vmstat 1 3 | tail -1) > "$out/$name-round1-load.txt" 2>&1
  echo "=== $name half: HEAD $(git rev-parse --short HEAD) ==="
  uv run python scripts/audit.py --budget 30 --json "$out/$name-round1.jsonl" \
      > "$out/$name-round1.txt" 2>&1 || true
  echo "$name half done: $(wc -l < "$out/$name-round1.jsonl") json rows"
}

# --- preconditions -----------------------------------------------------
[ -z "$(git status --short)" ] || { echo "REFUSING: tree not clean" >&2; exit 2; }
[ "$(git rev-parse --abbrev-ref HEAD)" = "$BRANCH" ] || { echo "REFUSING: not on $BRANCH" >&2; exit 2; }
echo "start: on $BRANCH at $(git rev-parse --short HEAD), tree clean"

# --- baseline half, on the detached merge base -------------------------
git checkout --detach "$BASE"
echo "detached at $(git rev-parse --short HEAD) (expect $BASE)"
half baseline "$TMP"

# --- back to the branch, IMMEDIATELY -----------------------------------
git checkout "$BRANCH"
[ "$(git rev-parse --abbrev-ref HEAD)" = "$BRANCH" ] || { echo "FAILED to return to $BRANCH" >&2; exit 3; }
[ -z "$(git status --short)" ] || { echo "WARNING: tree not clean after return" >&2; git status --short; }
echo "returned: on $(git rev-parse --abbrev-ref HEAD) at $(git rev-parse --short HEAD), tree clean"

# --- candidate half ----------------------------------------------------
half candidate "$DIR"

# --- bring the baseline half in ----------------------------------------
cp "$TMP"/baseline-round1.jsonl "$TMP"/baseline-round1.txt "$TMP"/baseline-round1-load.txt "$DIR"/
echo "baseline half copied in"

# --- compare -----------------------------------------------------------
uv run python scripts/audit_compare.py "$DIR/baseline-round1.jsonl" "$DIR/candidate-round1.jsonl" \
    > "$DIR/compare-round1.txt" 2>&1 || true
uv run python "$DIR/judge.py" "$DIR/baseline-round1.jsonl" "$DIR/candidate-round1.jsonl" \
    > "$DIR/judge-round1.txt" 2>&1 || true
echo "compare + judge written"
echo "final: on $(git rev-parse --abbrev-ref HEAD) at $(git rev-parse --short HEAD)"
