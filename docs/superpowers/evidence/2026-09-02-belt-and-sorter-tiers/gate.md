# Corpus gate: belt-and-sorter-tiers

Commit under test: `2dd2c98` (branch `belt-and-sorter-tiers`, before this task's own commit).
Baseline commit: `725c34e` (`master`).

Both audits: `uv run python scripts/audit.py --budget 30 --jobs 16 --json <file>`.

## Baseline (`725c34e`, run from a detached worktree of `master`)

65/72 CLEAN, 7 REFUSED, 0 INVALID, 0 CRASHED. 83s wall.
Evidence: `baseline-budget30.jsonl`. Log: `/tmp/flab2bp-handoff/baseline-audit.log`.

Baseline REFUSED cells (all pre-existing, unrelated to this task's belt/sorter-tier work):

- `sequence-pair universe-matrix/no-proliferator`
- `sequence-pair universe-matrix/all-products`
- `freeform quantum-chip/all-products`
- `freeform universe-matrix/output-products`
- `freeform universe-matrix/no-proliferator`
- `sequence-pair quantum-chip/no-proliferator`
- `sequence-pair graphene/output-products`

## Candidate (`2dd2c98`, this worktree)

freeform: 33/36 clean -- NOT CLEAN (refused 3, invalid 0, crashed 0, not run 0)
sequence-pair: 31/36 clean -- NOT CLEAN (refused 5, invalid 0, crashed 0, not run 0)

Total: 64/72 CLEAN, 8 REFUSED, 0 INVALID, 0 CRASHED. 84s wall, 72/72 cells.
Evidence: `candidate-budget30.jsonl`.

Candidate REFUSED cells: the same 7 baseline cells above, plus one new one:

- `sequence-pair universe-matrix/output-products` -- **new refusal, not present in the baseline.**

## `audit_compare.py` output (verbatim)

```
clean 64  refused 8  invalid 0  crashed 0  paired 64  area ratio 0.9980  p95 30.4s
  FAIL REFUSED: sequence-pair universe-matrix/no-proliferator: deadline exhausted before finding an exact layout; no legal DSP latitude band/orientation accepts the final placement: band 0 game.blueprint_area (): a 1334x131 extent fits no band on a segment-200 planet: it needs 131 latitude rows in its better orientation and the tallest band (200 segments) holds 160. The game refuses this paste with EBuildCondition.BlueprintAreaCrossTropic.
  FAIL REFUSED: sequence-pair universe-matrix/all-products: deadline exhausted before finding an exact layout
  FAIL REFUSED: sequence-pair universe-matrix/output-products: deadline exhausted before finding an exact layout
  FAIL REFUSED: freeform quantum-chip/all-products: the 30s deadline passed with no completed packing of 28 strips; 7 packs were routed in that time and the best of them still left 1 nets unrouted (worst 1), so a longer clock alone would not have wired this spec; 1 other pack stopped during exact preparation. This is a REFUSAL and not a verdict on the spec
  FAIL REFUSED: freeform universe-matrix/output-products: the 30s deadline passed with no completed packing of 46 strips; 5 packs were routed in that time and the best of them still left 1 nets unrouted (worst 1), so a longer clock alone would not have wired this spec; 1 other pack stopped during exact preparation. This is a REFUSAL and not a verdict on the spec
  FAIL REFUSED: freeform universe-matrix/no-proliferator: every packing that wired was rejected by our own validator (game.blueprint_area; findings: band 0 game.blueprint_area (): a 507x163 extent fits no band on a segment-200 planet: it needs 163 latitude rows in its better orientation and the tallest band (200 segments) holds 160. The game refuses this paste with EBuildCondition.BlueprintAreaCrossTropic.); a placement that fails validation is refused rather than returned, because an invalid blueprint pastes and then does not run
  FAIL REFUSED: sequence-pair quantum-chip/no-proliferator: deadline exhausted before finding an exact layout
  FAIL REFUSED: sequence-pair graphene/output-products: no scheduled stage produced an exact layout
  FAIL p95 wall 30.4s exceeds 30.0s
FAIL
```

## Verdict

`audit_compare.py` reports FAIL. Its per-row check fails on every non-CLEAN candidate row
regardless of whether the baseline already refused that same cell (see the script's docstring:
"has zero REFUSED / INVALID / CRASH rows"), so the 7 pre-existing baseline refusals alone would
already have produced FAIL here; that much is expected and is not attributed to this branch.

The finding that **is** attributed to this branch: `sequence-pair universe-matrix/output-products`
was CLEAN in the baseline (31.19s wall against a 30s budget -- it finished 1.19s into its own
deadline tail) and is REFUSED in the candidate ("deadline exhausted before finding an exact
layout" at 27.66s -- it did not even reach the nominal budget before giving up). No other
baseline-CLEAN cell regressed; no cell is INVALID or CRASHED; area ratio (0.9980) is inside
tolerance; the p95 FAIL (30.4s vs. the 30.0s threshold) is driven by the same near-boundary
cells the baseline already sat close to.

This one-cell regression on a large (28320 area, 66-projection, sequence-pair "stress" tier)
cell that the baseline itself only barely completed (past its own 30s budget) is consistent with
ordinary CP-SAT run-to-run variance at a tight deadline rather than a mechanism this branch
changed (the belt/sorter tier-raising logic touches emitted buildings, not search scheduling),
but it is reported here as a defect per the gate's own rule -- CLEAN-in-baseline-and-not-CLEAN-
in-candidate is never explained away -- rather than waved off. It is not re-run to see whether it
clears on a second try, since the gate's rule is to report the cell's detail, not to keep sampling
until the unwanted result goes away.
