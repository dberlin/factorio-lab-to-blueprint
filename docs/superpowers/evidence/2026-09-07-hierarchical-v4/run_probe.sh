#!/usr/bin/env bash
# Reproduces Task 3's oracle-vs-router measurement: two cells (belt3, zurl2),
# each at --strategy hierarchical --budget 60 --band portable
# --candidate-policy all-products, once at the plan's merge base ("before",
# Task 1/2 absent) and once at this branch's HEAD ("after", Task 1/2
# present).  This is the literal sequence that was actually run to produce
# the sidecars beside this script -- it is evidence of procedure, not a
# script meant to be re-run unattended: the BEFORE half detaches HEAD in
# THIS worktree, which is dangerous enough that every guard below is
# mandatory, not decorative.  Run it a stage at a time and read each
# verification line before going on.
#
# Safety invariants (see docs/superpowers/sdd/2026-09-07-hierarchical-v4/
# constraints.md and task-3-brief.md):
#   * ONE build at a time. These are 60s cells; never start a second while
#     one is running.
#   * `git status --short` MUST be empty before the detach in stage 2, and
#     is re-verified (branch name, SHA, and status) after returning in
#     stage 3. If any of those three checks fails, STOP -- the recovery is
#     `git checkout hierarchical-v4`, never a forced or destructive command.
#   * A `-load.txt` (runnable_5s_mean via vmstat) is captured immediately
#     before every cell, not waited on.
#   * probe.py's own sys.path plumbing (`ROOT = Path(__file__).resolve()
#     .parents[4]`) assumes it runs from this evidence directory, which
#     does not exist yet at the merge base -- stage 2 therefore runs a copy
#     of probe.py staged under /tmp/v4probe with only that ROOT line
#     hardcoded to this worktree's absolute path, and copies its outputs
#     back in afterward. The copy committed here (probe.py) keeps the
#     original parents[4] form unchanged, per the brief's "keep its
#     contract".
#
# Usage: read this file; run the stages by hand from the worktree root
# (/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/hierarchical-v4),
# one at a time, in order.

set -euo pipefail

WORKTREE=/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/hierarchical-v4
EVID="$WORKTREE/docs/superpowers/evidence/2026-09-07-hierarchical-v4"
TMP=/tmp/v4probe
BELT3_URL='https://factoriolab.github.io/dsp/list?o=conveyor-belt-3*1080&ibe=conveyor-belt-3&rex=P*Y*d*k*u*BN*BU*BX*Bk~Bl*Bs*CF~CG*CQ~CR&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11'
ZURL2_URL='https://factoriolab.github.io/dsp/list?z=eJwVxTEKgDAMBdDbZPhTO1hcsiSom6gg2FV0EC0FRXHK2cW3vMwtvCsdZZYC4S.AO9rmlZXO9eUOEQt23JAWMkImyG5yQC5obdpAe9OBUjo5mlhlPT3s.QdXzBnL&v=11'

# --- stage 0: verify the venv this worktree runs, before touching git -----
verify_venv() {
    cd "$WORKTREE"
    uv run python -c "import flab2bp; print(flab2bp.__file__)"
    # MUST print a path inside $WORKTREE. A path outside it means the venv
    # is not this worktree's own and no measurement here is trustworthy.
}

# --- stage 1: stage probe.py (and its hardcoded-ROOT /tmp twin) -----------
stage1_write_probe() {
    mkdir -p "$TMP"
    cp "$EVID/probe.py" "$TMP/probe.py"
    # Only the ROOT line differs from $EVID/probe.py: /tmp/v4probe/probe.py
    # sits at a different directory depth, so parents[4] would raise
    # IndexError there. Hardcode it to this worktree's root for this
    # /tmp-only copy; the committed probe.py is untouched.
    python3 - "$TMP/probe.py" "$WORKTREE" <<'PY'
import sys
path, worktree = sys.argv[1], sys.argv[2]
s = open(path).read()
old = 'ROOT = Path(__file__).resolve().parents[4]\nsys.path.insert(0, str(ROOT / "src"))'
new = f'ROOT = Path({worktree!r})\nsys.path.insert(0, str(ROOT / "src"))'
assert old in s, "probe.py ROOT line not found -- upstream script changed shape"
open(path, "w").write(s.replace(old, new))
PY
}

# --- stage 2: BEFORE half, detached at the merge base ----------------------
stage2_before() {
    cd "$WORKTREE"
    export GIT_EDITOR=true
    [ -z "$(git status --short)" ] || { echo "BLOCKED: worktree not clean" >&2; exit 1; }
    BASE=$(git merge-base master hierarchical-v4)
    git rev-parse HEAD > "$TMP/pre-detach-head.txt"
    git checkout --detach "$BASE"
    git rev-parse --abbrev-ref HEAD   # expect: HEAD (detached)
    git rev-parse HEAD                # expect: $BASE
    [ -z "$(git status --short)" ] || { echo "BLOCKED: dirty after detach" >&2; exit 1; }
    verify_venv                        # re-verify AT THE MERGE BASE too

    vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "runnable_5s_mean=" sum/5}' \
        > "$TMP/probe-belt3-all-products-before-load.txt"
    uv run python "$TMP/probe.py" "$TMP/probe-belt3-all-products-before.json" \
        -- "$BELT3_URL" --strategy hierarchical --budget 60 --band portable \
        --candidate-policy all-products -o "$TMP/belt3-before.blueprint.txt" \
        > "$TMP/probe-belt3-all-products-before.log" 2>&1 || true
    # ONE BUILD AT A TIME: zurl2 starts only after belt3's process exits.
    vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "runnable_5s_mean=" sum/5}' \
        > "$TMP/probe-zurl2-all-products-before-load.txt"
    uv run python "$TMP/probe.py" "$TMP/probe-zurl2-all-products-before.json" \
        -- "$ZURL2_URL" --strategy hierarchical --budget 60 --band portable \
        --candidate-policy all-products -o "$TMP/zurl2-before.blueprint.txt" \
        > "$TMP/probe-zurl2-all-products-before.log" 2>&1 || true

    git checkout hierarchical-v4
    # Verify ALL THREE before trusting anything past this point:
    git rev-parse --abbrev-ref HEAD   # MUST print: hierarchical-v4
    git rev-parse HEAD                # MUST match the SHA in $TMP/pre-detach-head.txt
    git status --short                # MUST be empty
}

# --- stage 3: copy the BEFORE evidence into the tracked directory ---------
stage3_copy_before() {
    cp "$TMP"/pre-detach-head.txt "$EVID/"
    cp "$TMP"/probe-belt3-all-products-before*.{json,log,txt} "$EVID/" 2>/dev/null || true
    cp "$TMP"/probe-zurl2-all-products-before*.{json,log,txt} "$EVID/" 2>/dev/null || true
}

# --- stage 4: AFTER half, on the branch's own HEAD -------------------------
stage4_after() {
    cd "$WORKTREE"
    verify_venv

    vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "runnable_5s_mean=" sum/5}' \
        > "$EVID/probe-belt3-all-products-after-load.txt"
    uv run python "$EVID/probe.py" "$EVID/probe-belt3-all-products-after.json" \
        -- "$BELT3_URL" --strategy hierarchical --budget 60 --band portable \
        --candidate-policy all-products -o "$EVID/belt3-after.blueprint.txt" \
        > "$EVID/probe-belt3-all-products-after.log" 2>&1 || true
    # ONE BUILD AT A TIME: zurl2 starts only after belt3's process exits.
    vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "runnable_5s_mean=" sum/5}' \
        > "$EVID/probe-zurl2-all-products-after-load.txt"
    uv run python "$EVID/probe.py" "$EVID/probe-zurl2-all-products-after.json" \
        -- "$ZURL2_URL" --strategy hierarchical --budget 60 --band portable \
        --candidate-policy all-products -o "$EVID/zurl2-after.blueprint.txt" \
        > "$EVID/probe-zurl2-all-products-after.log" 2>&1 || true
}

# Nothing runs on `source run_probe.sh` -- each stage is invoked by hand:
#   source run_probe.sh
#   verify_venv
#   stage1_write_probe
#   stage2_before      # reads the three verification lines before continuing
#   stage3_copy_before
#   stage4_after
