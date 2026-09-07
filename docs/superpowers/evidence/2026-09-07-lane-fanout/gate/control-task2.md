# Task 2 control: does the corpus move when the fan-out guard goes

Measured numbers only. No source code changed by this task.

## Arms

- BASELINE: master `a1401518` (full SHA `a140151893ad0d7bcf115e1b34b2aca8f2201ea4`), clean
  detached worktree at `/tmp/flab2bp-lane-fanout-baseline`.
- CANDIDATE: `lane-fanout` worktree at HEAD `fc33bf923618650b1ab9b3c50c69afe1a479e908`.

Both runs: `--tier stress --budget 30 --strategy both`, 72 cells expected and observed for
both arms.

## Venv verification

- Baseline: `uv run python -c "import flab2bp; print(flab2bp.__file__)"` ->
  `/tmp/flab2bp-lane-fanout-baseline/src/flab2bp/__init__.py`
- Candidate: `uv run python -c "import flab2bp; print(flab2bp.__file__)"` ->
  `/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/lane-fanout/src/flab2bp/__init__.py`

## CPU pressure (mean runnable processes, `vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print sum/5}'`)

| when | value |
|---|---|
| before baseline run | 9.6 |
| after baseline run | 34.0 |
| before candidate run | 13.2 |
| after candidate run | 13.6 |

## Wall times

| arm | wall | cells |
|---|---|---|
| baseline (master a1401518) | 176s | 72/72 |
| candidate (lane-fanout fc33bf92) | 186s | 72/72 |

## Counts (per audit.py's own tally, both arms combined per strategy)

| arm | strategy | clean | refused | invalid | crashed |
|---|---|---|---|---|---|
| baseline | freeform | 33 | 3 | 0 | 0 |
| baseline | sequence-pair | 33 | 3 | 0 | 0 |
| baseline | **total** | **66** | **6** | **0** | **0** |
| candidate | freeform | 33 | 3 | 0 | 0 |
| candidate | sequence-pair | 33 | 3 | 0 | 0 |
| candidate | **total** | **66** | **6** | **0** | **0** |

Identical counts in both arms.

## Pairing, area ratio, p95 wall

Cells were paired by `(strategy, url_id, spec_label, power, budget)`. Raw JSONL row order
differs across arms, so positional pairing is unsafe; `(strategy, url_id, spec_index)` also
pairs all 72 cells correctly. The richer key used here is valid, not required by index instability.

- Paired keys: 72 of 72 on both sides (every cell present in both arms).
- Paired CLEAN/CLEAN cells: 66 of 66.
- Geomean area ratio over the 66 paired CLEAN/CLEAN cells: **0.999874** (audit_compare.py
  reports the rounded `0.9999`).
- p95 wall (`build_wall_time_s`, all 72 cells, n=72 so p95 index = ceil(0.95*72)-1 = 68,
  the 69th of 72 sorted values):
  - baseline: **30.8735 s**
  - candidate: **31.2543 s**
  - relative change: **+1.2333 %** (this repo's same-arm noise floor is 1.3 %; the measured
    rise is below that floor)
- `audit_compare.py`'s own summary line (both arms): `clean 66  refused 6  invalid 0
  crashed 0  paired 66  area ratio 0.9999  p95 31.3s` — the `31.3s` figure it prints is the
  candidate arm's own p95 (rounded), not a baseline/candidate delta; the 1.2333 % figure
  above is the delta computed directly from the paired JSONL rows.

## Status changes between arms

Computed by pairing every one of the 72 `(strategy, url_id, spec_label, power, budget)` keys
present in both arms and diffing `status`:

**Zero cells changed status in either direction.** All 6 refused cells were refused in both
arms (they carry over — `audit_compare.py --regressions-only` reports them as `note CARRIED`,
not as new failures), and all 66 clean cells stayed clean in both arms. Every refused cell in
both arms is a `universe-matrix` cell; no cell outside `universe-matrix` changed status, and
no cell of any kind changed which of `{clean, refused, invalid, crashed}` bucket it is in.

## `audit_compare.py` verdict lines (verbatim)

Full comparison (`gate/audit-compare-task2.txt`):
```
clean 66  refused 6  invalid 0  crashed 0  paired 66  area ratio 0.9999  p95 31.3s
  FAIL REFUSED: freeform universe-matrix/all-products: no pack of 53 strips was ever produced at any candidate height; all 5 pack solves ended UNKNOWN rather than INFEASIBLE, inside the 0.02-unit deterministic work bound a pack of 53 strips is given, so the SOLVE gave up before the packing was shown impossible, and 28.7s of the 30s ceiling went unspent; the sweep stopped after 5 draws that produced no new packing
  FAIL REFUSED: freeform universe-matrix/no-proliferator: no pack of 57 strips was ever produced at any candidate height; all 5 pack solves ended UNKNOWN rather than INFEASIBLE, inside the 0.02-unit deterministic work bound a pack of 57 strips is given, so the SOLVE gave up before the packing was shown impossible, and 28.5s of the 30s ceiling went unspent; the sweep stopped after 5 draws that produced no new packing
  FAIL REFUSED: freeform universe-matrix/output-products: no pack of 54 strips was ever produced at any candidate height; all 5 pack solves ended UNKNOWN rather than INFEASIBLE, inside the 0.02-unit deterministic work bound a pack of 54 strips is given, so the SOLVE gave up before the packing was shown impossible, and 29.3s of the 30s ceiling went unspent; the sweep stopped after 5 draws that produced no new packing
  FAIL REFUSED: sequence-pair universe-matrix/no-proliferator: all 4 sequence islands refused: island 0: deadline exhausted before finding an exact layout; island 1: deadline exhausted before finding an exact layout; island 2: deadline exhausted before finding an exact layout; island 3: deadline exhausted before finding an exact layout
  FAIL REFUSED: sequence-pair universe-matrix/all-products: all 4 sequence islands refused: island 0: deadline exhausted before finding an exact layout; island 1: deadline exhausted before finding an exact layout; island 2: deadline exhausted before finding an exact layout; island 3: deadline exhausted before finding an exact layout
  FAIL REFUSED: sequence-pair universe-matrix/output-products: all 4 sequence islands refused: island 0: deadline exhausted before finding an exact layout; island 1: deadline exhausted before finding an exact layout; island 2: deadline exhausted before finding an exact layout; island 3: deadline exhausted before finding an exact layout
  FAIL p95 wall 31.3s exceeds 30.0s
FAIL
```

Regressions-only (`gate/audit-compare-task2-regressions.txt`):
```
clean 66  refused 6  invalid 0  crashed 0  paired 66  area ratio 0.9999  p95 31.3s
  FAIL p95 wall 31.3s exceeds 30.0s
  note CARRIED: freeform universe-matrix/all-products: no pack of 53 strips was ever produced at any candidate height; all 5 pack solves ended UNKNOWN rather than INFEASIBLE, inside the 0.02-unit deterministic work bound a pack of 53 strips is given, so the SOLVE gave up before the packing was shown impossible, and 28.7s of the 30s ceiling went unspent; the sweep stopped after 5 draws that produced no new packing
  note CARRIED: freeform universe-matrix/no-proliferator: no pack of 57 strips was ever produced at any candidate height; all 5 pack solves ended UNKNOWN rather than INFEASIBLE, inside the 0.02-unit deterministic work bound a pack of 57 strips is given, so the SOLVE gave up before the packing was shown impossible, and 28.5s of the 30s ceiling went unspent; the sweep stopped after 5 draws that produced no new packing
  note CARRIED: freeform universe-matrix/output-products: no pack of 54 strips was ever produced at any candidate height; all 5 pack solves ended UNKNOWN rather than INFEASIBLE, inside the 0.02-unit deterministic work bound a pack of 54 strips is given, so the SOLVE gave up before the packing was shown impossible, and 29.3s of the 30s ceiling went unspent; the sweep stopped after 5 draws that produced no new packing
  note CARRIED: sequence-pair universe-matrix/no-proliferator: all 4 sequence islands refused: island 0: deadline exhausted before finding an exact layout; island 1: deadline exhausted before finding an exact layout; island 2: deadline exhausted before finding an exact layout; island 3: deadline exhausted before finding an exact layout
  note CARRIED: sequence-pair universe-matrix/all-products: all 4 sequence islands refused: island 0: deadline exhausted before finding an exact layout; island 1: deadline exhausted before finding an exact layout; island 2: deadline exhausted before finding an exact layout; island 3: deadline exhausted before finding an exact layout
  note CARRIED: sequence-pair universe-matrix/output-products: all 4 sequence islands refused: island 0: deadline exhausted before finding an exact layout; island 1: deadline exhausted before finding an exact layout; island 2: deadline exhausted before finding an exact layout; island 3: deadline exhausted before finding an exact layout
FAIL
```

Note: `audit_compare.py`'s own `FAIL`/`PASS` verdict word is not the control's verdict — per
the task brief and controller rulings, it is ignored here in favor of the counts and named
cells above. Its `FAIL REFUSED` / `FAIL p95 wall ... exceeds 30.0s` lines are checks against
a fixed absolute threshold (any refusal at all; p95 above the 30 s budget itself), which is a
different, stricter question than this control's own pass condition (whether anything moved
relative to baseline).

## Universe-matrix refusal messages — verbatim, per arm

### Baseline (master `a1401518`) — the fan-out guard is still present

All 6 baseline `universe-matrix` cells refuse with the fan-out-guard message
(`freeform` and `sequence-pair` differ only in wrapping):

- `freeform universe-matrix/no-proliferator`: "a producer lane has fewer tiles than the
  consumers it must tap, so two junctions would have to share one tile. antimatter:
  mass-energy-storage#23 lane is 10 tile(s) wide but must tap 15 consumer lane(s) of
  universe-matrix#37"
- `freeform universe-matrix/all-products`: "a producer lane has fewer tiles than the
  consumers it must tap, so two junctions would have to share one tile. antimatter:
  mass-energy-storage#23 lane is 10 tile(s) wide but must tap 12 consumer lane(s) of
  universe-matrix#37"
- `freeform universe-matrix/output-products`: "a producer lane has fewer tiles than the
  consumers it must tap, so two junctions would have to share one tile. antimatter:
  mass-energy-storage#23 lane is 10 tile(s) wide but must tap 12 consumer lane(s) of
  universe-matrix#37"
- `sequence-pair universe-matrix/no-proliferator`: "all 4 sequence islands refused: island
  0: a producer lane has fewer tiles than the consumers it must tap, so two junctions would
  have to share one tile. antimatter: mass-energy-storage#23 lane is 10 tile(s) wide but must
  tap 15 consumer lane(s) of universe-matrix#37; island 1: [same]; island 2: [same]; island 3:
  [same]"
- `sequence-pair universe-matrix/all-products`: same pattern, "... must tap 12 consumer
  lane(s) of universe-matrix#37" x4 islands
- `sequence-pair universe-matrix/output-products`: same pattern, "... must tap 12 consumer
  lane(s) of universe-matrix#37" x4 islands

### Candidate (lane-fanout `fc33bf92`) — the fan-out guard is gone; two other blockers fire

None of the 6 candidate `universe-matrix` cells say "must tap" anywhere. The refusal reason
changed completely:

- `freeform universe-matrix/all-products`: "no pack of 53 strips was ever produced at any
  candidate height; all 5 pack solves ended UNKNOWN rather than INFEASIBLE, inside the
  0.02-unit deterministic work bound a pack of 53 strips is given, so the SOLVE gave up
  before the packing was shown impossible, and 28.7s of the 30s ceiling went unspent; the
  sweep stopped after 5 draws that produced no new packing"
- `freeform universe-matrix/no-proliferator`: "no pack of 57 strips was ever produced at any
  candidate height; all 5 pack solves ended UNKNOWN rather than INFEASIBLE, inside the
  0.02-unit deterministic work bound a pack of 57 strips is given, so the SOLVE gave up
  before the packing was shown impossible, and 28.5s of the 30s ceiling went unspent; the
  sweep stopped after 5 draws that produced no new packing"
- `freeform universe-matrix/output-products`: "no pack of 54 strips was ever produced at any
  candidate height; all 5 pack solves ended UNKNOWN rather than INFEASIBLE, inside the
  0.02-unit deterministic work bound a pack of 54 strips is given, so the SOLVE gave up
  before the packing was shown impossible, and 29.3s of the 30s ceiling went unspent; the
  sweep stopped after 5 draws that produced no new packing"
- `sequence-pair universe-matrix/no-proliferator`: "all 4 sequence islands refused: island 0:
  deadline exhausted before finding an exact layout; island 1: deadline exhausted before
  finding an exact layout; island 2: deadline exhausted before finding an exact layout;
  island 3: deadline exhausted before finding an exact layout"
- `sequence-pair universe-matrix/all-products`: "all 4 sequence islands refused: island 0:
  deadline exhausted before finding an exact layout; island 1: deadline exhausted before
  finding an exact layout; island 2: deadline exhausted before finding an exact layout;
  island 3: deadline exhausted before finding an exact layout"
- `sequence-pair universe-matrix/output-products`: "all 4 sequence islands refused: island 0:
  deadline exhausted before finding an exact layout; island 1: deadline exhausted before
  finding an exact layout; island 2: deadline exhausted before finding an exact layout;
  island 3: deadline exhausted before finding an exact layout"

## The control's pass condition — evaluated

1. No cell that was CLEAN on master is not CLEAN here: **holds** — 0 status changes
   observed across all 72 paired cells; all 66 baseline-CLEAN cells are CLEAN in the
   candidate.
2. No cell outside `universe-matrix` changed status at all: **holds** — the only 6 cells
   with any status other than CLEAN, in either arm, are the 6 `universe-matrix` cells; 0
   status changes total, so trivially 0 non-`universe-matrix` cells changed.
3. `universe-matrix`'s refusal MESSAGE changed, and does not still say "must tap": **holds**
   — see verbatim messages above; the fan-out-guard wording is entirely absent from the
   candidate arm's 6 refusal messages.
4. p95 wall did not rise by more than the 1.3 % same-arm noise floor: **holds** — measured
   rise is +1.2333 %, which is below 1.3 %.

## PASS / FAIL

**PASS.** The single number that decides it: p95 wall rose **+1.2333 %** run-over-run
(30.8735 s -> 31.2543 s), under this repo's 1.3 % same-arm noise floor, with zero cells
changing status in either direction and the `universe-matrix` refusal message no longer
saying "must tap" in either strategy.
