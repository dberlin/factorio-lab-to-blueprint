#!/usr/bin/env bash
# The v3 gate's default-unchanged corpus guard, exactly as v2's controller
# ruled it (R13): everything committed and `git status --short` empty first,
# then `git checkout --detach <merge-base>`, the BASELINE half run there
# writing to /tmp/v3gate/ (this evidence directory does not exist at the merge
# base), `git checkout hierarchical-v4` IMMEDIATELY, HEAD and cleanliness
# verified, then the CANDIDATE half, then the baseline half copied in.
#
# No `git stash`, no second worktree.
#
# Independent worktrees may run audits concurrently under the user's revised
# execution rule. This checkout's baseline and candidate halves stay sequential.
#
# Usage: run_guard.sh <worktree-root>
#
# The root is an ARGUMENT rather than derived from `$0`, because this script is
# run from a /tmp copy (see above) where `dirname "$0"` points at /tmp and the
# usual `cd "$(dirname "$0")/../../../.."` lands on `/`.  Passing it explicitly
# is what makes the /tmp copy and the tracked copy the same program.
set -eu
cd "${1:?usage: run_guard.sh <worktree-root>}" || exit 1
DIR=docs/superpowers/evidence/2026-09-07-hierarchical-v4
BASE=1d2a790c
BRANCH=hierarchical-v4
TMP=$(mktemp -d /tmp/v4gate.XXXXXX)


# ALWAYS return to the branch, on every exit path.  The first run of this
# script refused the slot AFTER detaching and left the worktree on the merge
# base; a detached worktree is the one state this procedure must never be
# walked away from, because the next thing anybody does in it is a commit.
# CPU pressure as the five-second mean of RUNNABLE processes, not load average.
# On this box load average is dominated by I/O wait, so `uptime` measures the
# wrong thing: a load average of 40 here is usually disk, not contention for
# the cores a build needs.  `vmstat`'s first column is `r`, the run queue.
# Under 64 is fine on these 128 cores.  This is RECORDED, never WAITED ON.
load_sample() {  # <path>
  local mean
  mean=$(vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print sum/5}')
  printf '%s\n' \
    "runnable_5s_mean=$mean" \
    "# mean of vmstat's r column over 5 one-second samples (vmstat 1 6, first discarded)." \
    "# CPU pressure, not load average: this box's load average is mostly I/O wait." \
    "# Under 64 is fine on these 128 cores.  Recorded, never waited on." \
    > "$1" 2>&1
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


half() {  # <name> <outdir>
  local name="$1" out="$2"
  mkdir -p "$out"
  rm -f "$out/$name-round1.jsonl"          # --json APPENDS
  load_sample "$out/$name-round1-load.txt"
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
