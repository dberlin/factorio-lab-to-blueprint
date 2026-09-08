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
# ONE AUDIT AT A TIME.  The slot check is `pgrep -af '[s]cripts/audit\.py'`,
# which corrects the plan's prescription in the opposite direction from the one
# an earlier revision of this script assumed -- see `audits_running` below for
# the measurement.  The matching lines are printed next to the count, so the
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
DIR=docs/superpowers/evidence/2026-09-07-hierarchical-v4
BASE=1d2a790c
BRANCH=hierarchical-v4
TMP=$(mktemp -d /tmp/v4gate.XXXXXX)

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

# WAIT for the slot rather than refuse it: this box is shared and a sibling
# worktree's audit can start at any moment, so refusing turns a queue into a
# retry loop driven by hand.  Checked before EVERY audit invocation, as the
# plan's constraint requires, and the matching lines are printed each time.
wait_for_slot() {
  local waited=0 lines n
  while :; do
    lines="$(audits_running)"
    n="$(printf '%s' "$lines" | grep -c . || true)"
    if [ "$n" = "0" ]; then
      echo "audit-count check: 0 (slot free after ${waited}s)"
      return 0
    fi
    if [ "$waited" = "0" ]; then
      echo "audit-count check: $n -- waiting for the slot"
      printf '%s\n' "$lines" | cut -c1-120
    fi
    sleep 20
    waited=$((waited + 20))
    if [ "$waited" -gt 5400 ]; then
      echo "GIVING UP: the audit slot was busy for ${waited}s" >&2
      exit 2
    fi
  done
}

half() {  # <name> <outdir>
  local name="$1" out="$2"
  mkdir -p "$out"
  rm -f "$out/$name-round1.jsonl"          # --json APPENDS
  wait_for_slot
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

# Queue for the slot BEFORE detaching, so the worktree does not sit on the
# merge base waiting for somebody else's audit to finish.
wait_for_slot

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
