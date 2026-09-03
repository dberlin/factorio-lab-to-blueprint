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

## Controller ruling on the regressed cell

The cell was re-run three times on each tree with the same audit settings
(`--budget 30 --only universe-matrix --candidate-policy output-products --strategy sequence-pair`),
on the same loaded box (other agents' test suites running; `vmstat` showed ~7 runnable, 97% idle,
I/O-bound). Evidence: `rerun-baseline-umop.jsonl` and `rerun-candidate-umop.jsonl`.

| tree | run 1 | run 2 | run 3 |
| --- | --- | --- | --- |
| baseline `725c34e` | REFUSED 27.2 s | CLEAN 29.2 s | REFUSED 26.0 s |
| candidate `2dd2c98` | REFUSED 25.9 s | REFUSED 26.5 s | CLEAN 29.7 s |

Both trees clear the cell one time in three, both at the deadline's edge. The cell straddles the
30 s budget under load on master as well; the branch did not cost it. Ruling: not a regression
attributable to this branch, and not fixed here. It joins the seven refusing cells as a candidate
for the reliability program (Phases B to D), which owns deadline-bound sequence-pair cells.

## Post-merge gate (master 22bf910 merged)

Merge commit: `08fad7c` (`Merge branch 'master' into belt-and-sorter-tiers`, merging local
`master` at `22bf910` -- which fast-forwarded the extraction-recipe rates change `2cabb77` and the
Phase B last-mile router merge `c5daa3a` -- into `belt-and-sorter-tiers` at `3950f98`).

Both audits: `uv run python scripts/audit.py --budget 30 --jobs 16 --json <file>` on the same 72-cell
corpus as the pre-merge gate above.

### Baseline2 (`master` `22bf910`, run by the controller from a separate worktree)

freeform: 33/36 clean -- NOT CLEAN (refused 3, invalid 0, crashed 0, not run 0)
sequence-pair: 33/36 clean -- NOT CLEAN (refused 3, invalid 0, crashed 0, not run 0)

Total: 66/72 CLEAN, 6 REFUSED, 0 INVALID, 0 CRASHED. 73s wall, 72/72 cells.
Evidence: `baseline2-master-budget30.jsonl` (copied verbatim from the controller's
`/tmp/flab2bp-handoff/baseline2-budget30.jsonl`). Log: `/tmp/flab2bp-handoff/baseline2-audit.log`
(`EXIT 1`).

Baseline2 REFUSED cells:

- `freeform universe-matrix/no-proliferator` -- validator rejection (`game.blueprint_area`): a
  264x162 extent fits no band on a segment-200 planet (needs 162 latitude rows, tallest band holds
  160; `EBuildCondition.BlueprintAreaCrossTropic`).
- `freeform universe-matrix/output-products` -- no packing of 43 strips could be wired at any
  candidate height (packer defect: produces packs its own router cannot wire).
- `freeform universe-matrix/all-products` -- no packing of 42 strips could be wired at any
  candidate height (same packer defect).
- `sequence-pair universe-matrix/output-products` -- deadline exhausted before finding an exact
  layout.
- `sequence-pair universe-matrix/all-products` -- deadline exhausted before finding an exact
  layout.
- `sequence-pair universe-matrix/no-proliferator` -- deadline exhausted before finding an exact
  layout.

### Candidate2 (merge commit `08fad7c`, this worktree)

freeform: 33/36 clean -- NOT CLEAN (refused 3, invalid 0, crashed 0, not run 0)
sequence-pair: 33/36 clean -- NOT CLEAN (refused 3, invalid 0, crashed 0, not run 0)

Total: 66/72 CLEAN, 6 REFUSED, 0 INVALID, 0 CRASHED. 72s wall, 72/72 cells.
Evidence: `candidate2-merged-budget30.jsonl`. Log: `/tmp/flab2bp-candidate2-audit.log`.

Candidate2 REFUSED cells: the same six cells as baseline2, with the same detail strings verbatim
(`freeform universe-matrix/{no-proliferator,output-products,all-products}` and
`sequence-pair universe-matrix/{output-products,all-products,no-proliferator}`).

### `audit_compare.py` output (verbatim)

```
clean 66  refused 6  invalid 0  crashed 0  paired 66  area ratio 1.0018  p95 28.7s
  FAIL REFUSED: freeform universe-matrix/no-proliferator: every packing that wired was rejected by our own validator (game.blueprint_area; findings: band 0 game.blueprint_area (): a 264x162 extent fits no band on a segment-200 planet: it needs 162 latitude rows in its better orientation and the tallest band (200 segments) holds 160. The game refuses this paste with EBuildCondition.BlueprintAreaCrossTropic.); a placement that fails validation is refused rather than returned, because an invalid blueprint pastes and then does not run
  FAIL REFUSED: freeform universe-matrix/output-products: no packing of 43 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing
  FAIL REFUSED: freeform universe-matrix/all-products: no packing of 42 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing
  FAIL REFUSED: sequence-pair universe-matrix/output-products: deadline exhausted before finding an exact layout
  FAIL REFUSED: sequence-pair universe-matrix/all-products: deadline exhausted before finding an exact layout
  FAIL REFUSED: sequence-pair universe-matrix/no-proliferator: deadline exhausted before finding an exact layout
FAIL
```

`audit_compare.py` reports FAIL for the same structural reason noted above: its per-row check
fails on any non-CLEAN candidate row regardless of whether the baseline already refused that same
cell. All six candidate2 refusals are pre-existing baseline2 refusals (the `universe-matrix`
"stress" tier, a known-tight corpus cell family per the Phase B/C/D reliability program), so this
FAIL is expected and not attributable to the merge.

### Cells whose status differs between baseline2 and candidate2

Diffed all 72 `(strategy, url_id, spec_index, spec_label)` cells between
`baseline2-master-budget30.jsonl` and `candidate2-merged-budget30.jsonl` by exact `status` field:
**zero cells differ in either direction.** Every CLEAN cell in baseline2 is CLEAN in candidate2 and
every REFUSED cell in baseline2 is REFUSED in candidate2 (same six cells, same detail text). No
cell is INVALID or CRASHED in either run. The merge introduces no CLEAN->non-CLEAN regression and
no non-CLEAN->CLEAN change.

### `uv run pytest -q -p no:cacheprovider` result

Full run: one hard failure --
`tests/test_pipeline.py::test_without_planetary_logistics_the_same_url_is_refused` --
`Failed: Timeout (>120.0s) from pytest-timeout`, raised at
`src/flab2bp/layout/freeform.py:12484` (inside the coater/splitter projected-relation-overlap
collision scan). Because `pytest-timeout`'s default "thread" method calls `os._exit(1)` on a
timeout, this single failure hard-killed the whole pytest process at 48% collected, so no summary
line was printed and every test after that point in collection order never ran.

Investigated per the task's own warning that the deuteron end-to-end tests
(`test_a_mk2_url_whose_lanes_need_mk3_builds`,
`test_without_planetary_logistics_the_same_url_is_refused`) might be affected by the rates change
raising hydrogen to 40 items/s:

- Re-ran the failing test alone with `--timeout=600`: it **passed**, 126.97s wall
  (`1 passed in 126.97s (0:02:06)`), i.e. `pipeline.build(...)` did correctly raise
  `pipeline.NoValidLayout` matching `flow.belt_capacity` as the test asserts -- just 6.97s past the
  project's 120s pytest-timeout backstop (`pyproject.toml`: `timeout = 120`, documented there as
  "generous on purpose", not a search budget). `tests/test_pipeline.py` itself is unchanged between
  the merge-base and `master` (`git diff 725c34e 22bf910 -- tests/test_pipeline.py` is empty), so
  this is not a merge-resolution mistake in that file; it is the combined branch (belt/sorter tier
  raising) and merged master (hydrogen at 40 items/s, Phase B last-mile router) making this one
  refusal path slower than the existing 120s backstop tolerates.
- Reran the full suite with `--deselect
  tests/test_pipeline.py::test_without_planetary_logistics_the_same_url_is_refused`: completed
  100% collected, zero `FAILED`/`ERROR` markers (exit code not independently captured because the
  run was launched via a detached background process; judged, as the task allows, by marker
  absence and full progress-bar completion since the final summary line is not reliably captured
  here either).

Verdict: the suite is clean except for this one pre-existing-test timing regression against a
120s backstop. The layout's refusal reasoning itself (`flow.belt_capacity`) is correct and
unchanged; nothing here was weakened to make the test pass. This is reported, not fixed, per the
task's instruction; it is a candidate for the reliability program's deadline-budget work (mirrors
the `sequence-pair universe-matrix/output-products` near-boundary finding in the pre-merge gate
above).

### mypy / ruff

`ruff check src tests`: all checks passed, no findings.

`mypy src`: 8 errors, all in `src/flab2bp/layout/freeform.py` (lines 4648, 4649, 15559, 15565,
15568, 15571, 15579, 15656) -- matches the branch's previously-documented 8 pre-existing errors in
that file exactly in count and file; no new mypy errors were introduced by the merge.
