#!/usr/bin/env bash
# Throwaway driver: the large cells, twice each, trunk off then trunk on.
# Two harness runs at a time -- other experiments share this box.
set -u
ROOT=/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/exp-trunk
D=$ROOT/docs/superpowers/evidence/2026-09-06-exp-trunk
H=$ROOT/docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py
MALL=$(tr -d '\n' < "$ROOT/docs/superpowers/evidence/2026-09-05-scale-levers/mall-profile/url.txt")
ZURL2=$(grep '^zurl2' "$ROOT/docs/superpowers/evidence/2026-09-05-speedups-2/large-urls/urls.txt" | cut -f2)
cd "$ROOT" || exit 1
mkdir -p "$D/large"

run_one() {
  # $1 cell  $2 arm(off|on)  $3 round
  local cell=$1 arm=$2 round=$3 out trunk args
  out="$D/large/$cell-$arm-$round"
  trunk=""
  [ "$arm" = on ] && trunk=auto
  case $cell in
    um60)    args=(universe-matrix --rate 60  --budget 60 --policy no-proliferator --strategy freeform) ;;
    um120)   args=(universe-matrix --rate 120 --budget 60 --policy no-proliferator --strategy freeform) ;;
    qc180)   args=(quantum-chip    --rate 180 --budget 60 --policy all-products    --strategy freeform) ;;
    mall)    args=(mall  --url "$MALL"  --policy all-products --budget 60 --strategy freeform) ;;
    zurl2)   args=(zurl2 --url "$ZURL2" --policy all-products --budget 60 --strategy freeform) ;;
    um60sp)  args=(universe-matrix --rate 60  --budget 60 --policy no-proliferator --strategy sequence-pair --islands 4) ;;
    um120sp) args=(universe-matrix --rate 120 --budget 60 --policy no-proliferator --strategy sequence-pair --islands 4) ;;
    qc180sp) args=(quantum-chip    --rate 180 --budget 60 --policy all-products --strategy sequence-pair --islands 4) ;;
    mallsp)  args=(mall  --url "$MALL"  --policy all-products --budget 60 --strategy sequence-pair --islands 4) ;;
    zurl2sp) args=(zurl2 --url "$ZURL2" --policy all-products --budget 60 --strategy sequence-pair --islands 4) ;;
  esac
  FLAB2BP_TRUNK_ITEMS="$trunk" uv run python "$H" "${args[@]}" --out "$out" \
    >"$out.log" 2>&1
  echo "$cell/$arm/$round exit $?"
}
export -f run_one
export ROOT D H MALL ZURL2

CELLS=${CELLS:-"um60 um120 qc180 mall zurl2 um60sp um120sp qc180sp mallsp zurl2sp"}
for round in 1 2; do
  for arm in off on; do
    echo "=== round $round arm $arm $(date -Is) $(uptime)"
    printf '%s\n' $CELLS |
      xargs -P 2 -I{} bash -c 'run_one "$1" "$2" "$3"' _ {} "$arm" "$round"
  done
done
echo large-done "$(uptime)"
