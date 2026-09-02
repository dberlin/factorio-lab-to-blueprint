# Task 11 gate record

Commit under test: a3549e6 (evaluation-throughput, HEAD before this evidence commit)
Baseline commit (Task 1): d4f7d99

## Step 1: corpus-wide preparation parity

Last line of `prepare-parity.txt`:

```
PARITY 36 specs
```

Exit code 0. 36/36 corpus specs (12 URLs x 3 candidate policies) produced
structurally identical `_PreparedRoutingProblem` values from a cold private
cache and from the shared `geometry_memo` cache, across two repeats each.

## Step 2: before/after profile (STOP CONDITION TRIPPED HERE)

Task 2 Step 5 loop re-run unchanged (`--budget 15 --workers 0`, 3 candidate
policies x 2 strategies on `universe-matrix`, plus `quantum-chip`
(output-products) and `plastic` (all-products)), written to
`profile-after.jsonl`. Comparison table produced by the brief's Step 2 script
(one line per `(url_id, strategy, budget_s)` key; because that key omits
candidate policy, each line reflects the last policy iterated for that
strategy, i.e. `output-products` for `universe-matrix`):

```
('universe-matrix', 'freeform', 15.0) prepare first 2.04 -> 1.95 astar 7.06 -> 1.56 wall 15.0 -> 16.1 REFUSED: -> REFUSED:
('universe-matrix', 'sequence-pair', 15.0) prepare first 1.96 -> 1.87 astar 2.73 -> 0.51 wall 15.2 -> 12.8 REFUSED: -> REFUSED:
('quantum-chip', 'freeform', 15.0) prepare first 1.14 -> 1.03 astar 3.03 -> 0.92 wall 14.7 -> 13.8 OK -> OK
('plastic', 'freeform', 15.0) prepare first 1.17 -> 1.15 astar 0.02 -> 0.00 wall 7.8 -> 8.4 OK -> OK
```

Brief's Step 2 goal: first-candidate `prepare` on `universe-matrix` at or
under 1.0 s, and `astar_s` at or under 0.2 s. **Both goals are missed**, and
were already missed before this task's (behavior-neutral) change: every one
of the 6 `universe-matrix` rows (3 candidate policies x 2 strategies), in
both `profile-before.jsonl` and `profile-after.jsonl`, has a first-candidate
`prepare` between 1.87 s and 4.74 s, and a total `astar_s` between 0.42 s and
7.06 s across the run. None reach the stated thresholds. Task 11 makes no
change to preparation or search code (`prepare_parity.py` only reads
`_prepare_routing_problem` and `geometry_memo.for_spec`), so before and after
are, as expected, statistically the same run-to-run noise rather than a
regression or an improvement large enough to cross the goal.

Full per-row detail (first-candidate `prepare`, total `astar_s`, and the
phase breakdown that explains where `prepare` time goes), `universe-matrix`
only:

```
profile-before.jsonl
  freeform      prepare[0] 2.31  astar_s 6.05  phases {junction_ban 0.46, plan_strips 0.59, power_plan 2.57, prepare 3.74, strip_families 0.57}
  sequence-pair prepare[0] 2.18  astar_s 1.87  phases {junction_ban 0.41, plan_strips 0.03, power_plan 2.18, prepare 3.58, strip_families 0.71}
  freeform      prepare[0] 4.26  astar_s 5.83  phases {coater_frame_bans 1.37, finalize 0.46, junction_ban 0.63, place_coaters 0.84, plan_strips 0.9, power_plan 0.79, prepare 4.26, static_risks 0.35, strip_families 0.6, validate 1.25}
  sequence-pair prepare[0] 4.74  astar_s 1.51  phases {coater_frame_bans 2.41, junction_ban 0.47, place_coaters 1.59, plan_strips 0.36, power_plan 1.98, prepare 7.21, static_risks 0.42, strip_families 0.48}
  freeform      prepare[0] 2.04  astar_s 7.06  phases {coater_frame_bans 0.16, junction_ban 0.48, place_coaters 0.16, plan_strips 0.92, power_plan 2.06, prepare 3.61, static_risks 0.02, strip_families 0.89}
  sequence-pair prepare[0] 1.96  astar_s 2.73  phases {coater_frame_bans 0.19, junction_ban 0.55, place_coaters 0.12, plan_strips 0.02, power_plan 1.53, prepare 3.15, static_risks 0.02, strip_families 0.44}

profile-after.jsonl
  freeform      prepare[0] 2.19  astar_s 1.48  phases {junction_ban 0.54, plan_strips 0.02, power_plan 2.94, prepare 4.39, strip_families 0.44}
  sequence-pair prepare[0] 2.19  astar_s 0.42  phases {junction_ban 0.4, plan_strips 0.02, power_plan 2.4, prepare 3.44, strip_families 0.43}
  freeform      prepare[0] 3.66  astar_s 0.65  phases {coater_frame_bans 1.4, finalize 0.46, junction_ban 0.47, place_coaters 0.6, plan_strips 0.3, power_plan 0.64, prepare 3.66, static_risks 0.34, strip_families 0.44, validate 1.23}
  sequence-pair prepare[0] 4.62  astar_s 0.56  phases {coater_frame_bans 3.72, junction_ban 0.48, place_coaters 1.55, plan_strips 0.28, power_plan 2.11, prepare 8.57, static_risks 0.34, strip_families 0.46}
  freeform      prepare[0] 1.95  astar_s 1.56  phases {coater_frame_bans 0.35, junction_ban 0.44, place_coaters 0.16, plan_strips 0.02, power_plan 3.13, prepare 4.95, static_risks 0.02, strip_families 0.43}
  sequence-pair prepare[0] 1.87  astar_s 0.51  phases {coater_frame_bans 0.19, junction_ban 0.5, place_coaters 0.12, plan_strips 0.02, power_plan 1.58, prepare 2.98, static_risks 0.02, strip_families 0.44}
```

`power_plan` is the largest single sub-phase of `prepare` in every row that
has it isolated (0.64 s - 3.13 s of a 1.9 s - 8.6 s `prepare` total), with
`coater_frame_bans` a close second on the strip-family-heavy rows (up to
3.72 s). Neither is touched by the shared `geometry_memo` work this task
verifies; both are unchanged, cell for cell, from before to after. This is
the miss the Step 2 stop condition exists to catch: preparation dominates
these cells (matching the plan's own finding that "preparation not A*
dominates the largest cells"), and the plan's 1.0 s / 0.2 s targets were not
reached by the work landed in Tasks 1-10.

## Gate conditions

Per the brief's Step 2: "If either goal is missed, stop here ... and report;
do not run the audit." Both goals were missed, so Steps 3 and 4 (the
three-round corpus audit and `audit_compare.py`) were **not run**. The
`candidate-budget30-round{1,2,3}.jsonl` files were not produced.

| Condition | Result |
|---|---|
| Step 1 parity: `PARITY 36 specs`, exit 0 | PASS |
| Step 2: first-candidate `prepare` on `universe-matrix` <= 1.0 s | FAIL (1.87 s - 4.74 s, all 6 rows, both before and after) |
| Step 2: `astar_s` on `universe-matrix` <= 0.2 s | FAIL (0.42 s - 7.06 s, all 6 rows, both before and after) |
| Step 3: 72/72 CLEAN, refused 0, invalid 0, crashed 0, three rounds | NOT RUN (Step 2 stop condition) |
| Step 3: wall p95 per cell <= 30 s | NOT RUN (Step 2 stop condition) |
| Step 4: `audit_compare.py` PASS against `baseline-budget30.jsonl`, three rounds | NOT RUN (Step 2 stop condition) |
| route_bench `BEST` lines (python, cython) | NOT RUN (Step 2 stop condition; brief's Step 4 draws these from Task 8 Step 7, not a fresh run, but the honesty rule bars fabricating them without one) |
