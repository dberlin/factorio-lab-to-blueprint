#!/usr/bin/env bash
# Corpus-scale sanity: the ten corpus cells with the largest max internal
# spread, freeform at 30 s, trunk off then on, two runs at a time.
# scripts/audit.py is deliberately NOT used (other experiments share the box);
# each cell is driven through the same prof_harness as the large cells.
set -u
ROOT=/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/exp-trunk
D=$ROOT/docs/superpowers/evidence/2026-09-06-exp-trunk
H=$ROOT/docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py
cd "$ROOT" || exit 1
mkdir -p "$D/corpus"

CELLS="universe-matrix:no-proliferator universe-matrix:output-products \
universe-matrix:all-products super-magnetic-ring:no-proliferator \
super-magnetic-ring:output-products super-magnetic-ring:all-products \
information-matrix:no-proliferator quantum-chip:no-proliferator \
information-matrix:output-products quantum-chip:output-products"

run_one() {
  local cell=$1 arm=$2 url_id policy url out trunk
  url_id=${cell%%:*}
  policy=${cell#*:}
  url=$(uv run python -c "
from flab2bp.bench.corpus import entry
print(entry('$url_id').url)
" 2>/dev/null | tail -1)
  out="$D/corpus/$url_id-$policy-$arm"
  trunk=""
  [ "$arm" = on ] && trunk=auto
  FLAB2BP_TRUNK_ITEMS="$trunk" uv run python "$H" "$url_id" --url "$url" \
    --policy "$policy" --budget 30 --strategy freeform --out "$out" \
    >"$out.log" 2>&1
  echo "$cell/$arm exit $?"
}
export -f run_one
export ROOT D H

for arm in off on; do
  echo "=== arm $arm $(date -Is) $(uptime)"
  printf '%s\n' $CELLS | xargs -P 2 -I{} bash -c 'run_one "$1" "$2"' _ {} "$arm"
done
echo corpus-done "$(uptime)"
