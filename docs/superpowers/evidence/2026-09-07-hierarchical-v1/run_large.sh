#!/usr/bin/env bash
# The gate's five large cells, through the SHIPPED CLI.
#
# One candidate policy per run (`--candidate-policy <label>`) rather than the
# CLI's default three, so each cell is exactly the (url, policy) pair the gate
# names and gets the whole `--budget` to itself.  `--no-proliferator` is the
# other way to reach that policy, but it is a FILTER over whatever candidates
# the URL produces rather than a name, so it does not pin the cell.
#
# Usage: run_large.sh <round>   (1 or 2)
set -u
cd "$(dirname "$0")/../../../.." || exit 1
DIR=docs/superpowers/evidence/2026-09-07-hierarchical-v1
R="$1"

BELT3='https://factoriolab.github.io/dsp/list?o=conveyor-belt-3*1080&ibe=conveyor-belt-3&rex=P*Y*d*k*u*BN*BU*BX*Bk~Bl*Bs*CF~CG*CQ~CR&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11'
ZURL2='https://factoriolab.github.io/dsp/list?z=eJwVxTEKgDAMBdDbZPhTO1hcsiSom6gg2FV0EC0FRXHK2cW3vMwtvCsdZZYC4S.AO9rmlZXO9eUOEQt23JAWMkImyG5yQC5obdpAe9OBUjo5mlhlPT3s.QdXzBnL&v=11'
MALL='https://factoriolab.github.io/dsp/list?z=eJwlx7uOwjAUhOG3OcUUKAYWhWKaY4mgVRaBEBAogRQWayVyuKTys6PEzf.NNNzAZHkmDdcnzBbD0ArTXBp-YH6kod0PtyZ-hxQSqHsgk8Bd4pLQG2Ak0Fbp223yL1Em1sfkMpEPeFoY8TyPdWPLsd3YFkZc3VMn4q41rbjuybmEuucWJ5xxxwMv9FhAN9ADtILeoI-o.9Ap7CraQrwP7GIbXSzFtx0LedOYL5cQRDE_&v=11'

run() {  # label url policy
  local label="$1" url="$2" policy="$3"
  local stem="$DIR/large-$label-$policy-r$R"
  (uptime; vmstat 1 3 | tail -1) > "$stem-load.txt" 2>&1
  local t0 t1
  t0=$(date +%s.%N)
  uv run flab2bp "$url" --strategy hierarchical --budget 60 --band portable \
      --candidate-policy "$policy" -o "$stem.blueprint.txt" > "$stem.stdout.txt" 2> "$stem.log"
  local rc=$?
  t1=$(date +%s.%N)
  printf '%s\n' "EXIT=$rc" "WALL_S=$(echo "$t1 - $t0" | bc)" >> "$stem.log"
  echo "$label/$policy r$R: exit=$rc wall=$(echo "$t1 - $t0" | bc)"
}

run belt3 "$BELT3" all-products
run belt3 "$BELT3" no-proliferator
run zurl2 "$ZURL2" all-products
run mall  "$MALL"  all-products
run mall  "$MALL"  no-proliferator
