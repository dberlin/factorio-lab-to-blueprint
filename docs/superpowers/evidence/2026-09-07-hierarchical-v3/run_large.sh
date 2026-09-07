#!/usr/bin/env bash
# The v3 gate's eight large cells, through the SHIPPED CLI.
#
# The same eight cells and the same invocation shape as v2's `run_large.sh`
# (`../2026-09-07-hierarchical-v2/run_large.sh`) -- one candidate policy per run
# (`--candidate-policy <label>`) so each cell gets the whole budget,
# `--band portable`, `-o <stem>.blueprint.txt`, and NO `--workers` so the
# strategy sees the `None` the CLI passes by default.  Stem carries the budget:
# `large-<label>-<policy>-b<budget>-r<round>`.
#
# The one difference is the harness: `run_cell.py` no longer monkeypatches
# anything.  Task 1 puts the strategy's whole `PlacementStats` on the CLI's own
# stderr, so the wrapper parses that line.  See its module docstring.
#
# STRICTLY SEQUENTIAL: one layout build at a time, per the plan's box discipline.
#
# Usage: run_large.sh <round>   (1 or 2)
set -u
cd "$(dirname "$0")/../../../.." || exit 1
DIR=docs/superpowers/evidence/2026-09-07-hierarchical-v3
R="$1"

BELT3='https://factoriolab.github.io/dsp/list?o=conveyor-belt-3*1080&ibe=conveyor-belt-3&rex=P*Y*d*k*u*BN*BU*BX*Bk~Bl*Bs*CF~CG*CQ~CR&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11'
ZURL2='https://factoriolab.github.io/dsp/list?z=eJwVxTEKgDAMBdDbZPhTO1hcsiSom6gg2FV0EC0FRXHK2cW3vMwtvCsdZZYC4S.AO9rmlZXO9eUOEQt23JAWMkImyG5yQC5obdpAe9OBUjo5mlhlPT3s.QdXzBnL&v=11'
MALL='https://factoriolab.github.io/dsp/list?z=eJwlx7uOwjAUhOG3OcUUKAYWhWKaY4mgVRaBEBAogRQWayVyuKTys6PEzf.NNNzAZHkmDdcnzBbD0ArTXBp-YH6kod0PtyZ-hxQSqHsgk8Bd4pLQG2Ak0Fbp223yL1Em1sfkMpEPeFoY8TyPdWPLsd3YFkZc3VMn4q41rbjuybmEuucWJ5xxxwMv9FhAN9ADtILeoI-o.9Ap7CraQrwP7GIbXSzFtx0LedOYL5cQRDE_&v=11'
TITANIUM='https://factoriolab.github.io/dsp/list?z=eJzLt3Uq0zI1MFDLt3VK1jI0MNDSMgSxs5DYkQi2uZaRAVzcScsYSb0RjF2CYDolaxmZwtiVIOUIvYZwThUSuwCJHQFmw3SUI.PCtAwtLS2hMoEgC0GMMCijFEWjIdzIzKRUW2e1otQK23i13Nwi28g6pzrXukC1MltDQwBw4z6V&v=11'

run() {  # label url policy budget
  local label="$1" url="$2" policy="$3" budget="$4"
  local stem="$DIR/large-$label-$policy-b$budget-r$R"
  (uptime; vmstat 1 3 | tail -1) > "$stem-load.txt" 2>&1
  local t0 t1
  t0=$(date +%s.%N)
  uv run python "$DIR/run_cell.py" "$stem.json" -- \
      "$url" --strategy hierarchical --budget "$budget" --band portable \
      --candidate-policy "$policy" -o "$stem.blueprint.txt" \
      > "$stem.stdout.txt" 2> "$stem.log"
  local rc=$?
  t1=$(date +%s.%N)
  printf '%s\n' "EXIT=$rc" "WALL_S=$(echo "$t1 - $t0" | bc)" >> "$stem.log"
  echo "$label/$policy b$budget r$R: exit=$rc wall=$(echo "$t1 - $t0" | bc)"
}

run belt3          "$BELT3"    all-products    60
run belt3          "$BELT3"    no-proliferator 60
run zurl2          "$ZURL2"    all-products    60
run mall           "$MALL"     all-products    60
run mall           "$MALL"     no-proliferator 60
run titanium-glass "$TITANIUM" all-products    60
run titanium-glass "$TITANIUM" all-products    15
run belt3          "$BELT3"    all-products    15
