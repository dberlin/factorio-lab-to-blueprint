#!/usr/bin/env bash
# After-profile for the three large URLs, paired with `before.jsonl` (master
# a232f0a).  Same grid: 3 labels x 2 policies x 2 strategies x budgets 60/100.
#
# The sequence-pair arm gets `--islands 4` explicitly.  `route_profile._strategy`
# -- which `prof_harness.py` uses when the flag is omitted -- builds
# `SequencePairLayout` directly with no island argument, so it would measure the
# one-island shape rather than the four `pipeline.resolve_sequence_islands` now
# returns and `scripts/audit.py` now runs.  `before.jsonl` predates the levers,
# where one island WAS the shipped shape, so the pairing stays honest.
#
# Two runs at a time, no more: the box is shared.
set -u
cd "$(dirname "$0")/../../../../.." || exit 1
E=docs/superpowers/evidence/2026-09-05-speedups-2
H=docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py

jobs=()
while IFS=$'\t' read -r label url; do
  [ -z "${label:-}" ] && continue
  for policy in all-products no-proliferator; do
    for strategy in freeform sequence-pair; do
      for budget in 60 100; do
        jobs+=("$label|$url|$policy|$strategy|$budget")
      done
    done
  done
done < "$E/large-urls/urls.txt"

run_one() {
  IFS='|' read -r label url policy strategy budget <<<"$1"
  out="$E/large-urls/after-$label-$policy-$strategy-$budget"
  extra=()
  [ "$strategy" = "sequence-pair" ] && extra=(--islands 4)
  echo "START $label $policy $strategy $budget"
  uv run python "$H" "$label" --url "$url" --policy "$policy" \
    --strategy "$strategy" --budget "$budget" "${extra[@]}" --out "$out" \
    >"$out.log" 2>&1
  echo "DONE  $label $policy $strategy $budget exit=$?"
}

i=0
while [ $i -lt ${#jobs[@]} ]; do
  run_one "${jobs[$i]}" &
  p1=$!
  p2=""
  if [ $((i + 1)) -lt ${#jobs[@]} ]; then
    run_one "${jobs[$((i + 1))]}" &
    p2=$!
  fi
  wait "$p1"
  [ -n "$p2" ] && wait "$p2"
  i=$((i + 2))
done
echo "ALL DONE"
