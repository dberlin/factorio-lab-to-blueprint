#!/usr/bin/env bash
# Throwaway driver: the four large freeform cells plus belt3, once per
# configuration, two harness runs at a time.
set -u
ROOT=/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/spike-density
D=$ROOT/docs/superpowers/evidence/2026-09-06-density-decomposition
H=$ROOT/docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py
BELT3='https://factoriolab.github.io/dsp/list?o=conveyor-belt-3*1080&ibe=conveyor-belt-3&rex=P*Y*d*k*u*BN*BU*BX*Bk~Bl*Bs*CF~CG*CQ~CR&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11'
cd "$ROOT" || exit 1
mkdir -p "$D/large"

run_one() {
  # $1 cell  $2 nd  $3 ns
  local cell=$1 nd=$2 ns=$3 out
  out="$D/large/$cell-$4"
  case $cell in
    um60)  args=(universe-matrix --rate 60  --budget 30) ;;
    um120) args=(universe-matrix --rate 120 --budget 30) ;;
    gm200) args=(gravity-matrix  --rate 200 --budget 30) ;;
    qc180) args=(quantum-chip    --rate 180 --budget 30) ;;
    belt3) args=(belt3 --url "$BELT3" --policy all-products --budget 60) ;;
  esac
  FLAB2BP_SPIKE_NO_DIRECT=$nd FLAB2BP_SPIKE_NO_SHARING=$ns PYTHONPATH=$D \
    uv run python "$H" "${args[@]}" --strategy freeform --out "$out" \
    >"$out.log" 2>&1
  echo "$cell/$4 exit $?"
}
export -f run_one
export ROOT D H BELT3

for cfg in base:0:0 nodirect:1:0 noshare:0:1 neither:1:1; do
  name=${cfg%%:*}
  rest=${cfg#*:}
  nd=${rest%%:*}
  ns=${rest##*:}
  echo "=== $name $(date -Is)"
  printf '%s\n' um60 um120 gm200 qc180 belt3 |
    xargs -P 2 -I{} bash -c 'run_one "$1" "$2" "$3" "$4"' _ {} "$nd" "$ns" "$name"
done
echo large-done
