#!/usr/bin/env bash
# The remaining arms, strictly one after another.  `packed` is freeform-only:
# sequence-pair refuses a packed node before it packs anything (see README).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROUND="${1:-1}"
bash "$HERE/run_arm.sh" seat "$ROUND" both
bash "$HERE/run_arm.sh" placed "$ROUND" both
bash "$HERE/run_arm.sh" packed "$ROUND" freeform
echo "ALL ARMS DONE"
