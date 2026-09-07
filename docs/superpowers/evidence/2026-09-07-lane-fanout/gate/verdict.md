# Task 5: The gate — verdict

Every number below was measured on this box, this day (2026-09-07), in this worktree. Nothing is
predicted, estimated, or rounded toward a better answer.

## Arms

- **CANDIDATE**: `lane-fanout` worktree at HEAD `19da237cdb06efb01a3a93a374b04be19c7f7f33`.
- **BASELINE**: master `a1401518` (full SHA `a140151893ad0d7bcf115e1b34b2aca8f2201ea4`). Per
  controller Ruling P1, this gate REUSES Task 2's committed `gate/audit-baseline.jsonl` rather than
  re-running the baseline arm — the branch is pinned to merge base `a1401518` and has not moved on,
  and re-running an unchanged baseline arm would only add noise, not information.

## Step 1: worktree verification

```
$ uv run python -c "import flab2bp; print(flab2bp.__file__)"
/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/lane-fanout/src/flab2bp/__init__.py
$ git rev-parse HEAD
19da237cdb06efb01a3a93a374b04be19c7f7f33
$ git status --short
(empty — clean)
```

Venv resolves inside the worktree, HEAD matches the branch under test, tree is clean. Gate is valid to run.

## Step 2: the full pytest suite

Per Ruling T5-A, pytest's own exit status was captured directly (the process writing the log also
wrote its own `$?` into the log, not `tail`'s). Per Ruling T5-B, the full output is kept in
`gate/pytest-round1.log` (no tail truncation).

```
cpu_pressure before: 6.4
$ uv run pytest -q > gate/pytest-round1.log 2>&1; echo "TRUE_EXIT=$?" >> gate/pytest-round1.log
cpu_pressure after: 60.6
```

**TRUE_EXIT=1** (recorded inside the log itself, at the end, by the process that ran pytest — not by
a downstream `tail`).

Per this repo's own known quirk (`project-test-and-gate-quirks`), pytest prints no numeric
`N passed, M failed` summary line on this box; the exit code and the `short test summary info`
section are the record.

**Exactly one test failed**, named verbatim from the `short test summary info` section:

```
FAILED tests/layout/test_sequence_pair.py::test_two_stage_alignment_retains_cp_sat_direct_opportunity - AssertionError: assert frozenset()
```

This is the first of the two names given to this task as a pre-existing, known red. It failed
exactly as expected, on an assertion (`assert oracle.direct`) unrelated to this branch's changes.

**The second named known red did NOT fail this round.**
`test_all_products_sequence_pair_honours_the_exact_layout_deadline`
(`tests/test_pipeline.py:707`) does not appear in the `FAILED` list, in the `FAILURES` section, or
anywhere in the failure output — it passed. Confirmed present and collected: `grep` finds its
`def` at `tests/test_pipeline.py:707`, it carries only `@pytest.mark.slow` (which this repo's
`pyproject.toml` explicitly runs by default — "The default run is the WHOLE suite. There is no
`-m 'not slow'` here any more"), so it was not deselected. Its own body documents why it can swing:
it asserts a real build refuses inside a `budget = 1.5` deadline, and its own comment says the
budget is deliberately close to a measured ceiling ("THE CEILING IS 2.0s, MEASURED: at 2.0 the
solver sometimes SUCCEEDS on this URL, so the budget has to stay strictly below it or the test is
flaky rather than wrong") — i.e. it is a wall-clock race against machine load by the test's own
design, not a code path this branch touched. **This is a discrepancy from the task's stated
premise, recorded here rather than silently reconciled**: this run measured ONE pre-existing
failure, not two. No third failure occurred; the gate's own rule ("any third failure fails the
gate") is not triggered — fewer failures than expected is not a third failure. No source file was
touched to produce or explain this; it is reported as measured.

## Steps 3-4: two rounds of the paired corpus round

One build at a time; round 2 started only after round 1's process exited. Audit slot confirmed free
(`pgrep -fc 'python[0-9.]* +[^ ]*scripts/audit\.py'` → `0`) before each round.

| round | cpu before | cpu after | command | wall | exit |
|---|---|---|---|---|---|
| 1 | 6.8 | 12.8 | `uv run python scripts/audit.py --tier stress --budget 30 --strategy both --json gate/audit-candidate-r1.jsonl` | 197s, 72/72 cells | audit.py's own process exit 1 (its "NOT CLEAN" convention — see below) |
| 2 | 2.4 | 37.4 | identical, into `gate/audit-candidate-r2.jsonl` | 197s, 72/72 cells | 1 (same convention) |

Per the brief, `audit.py`'s own NOT CLEAN / `audit_compare.py`'s FAIL verdict words are ignored here
in favor of counts and named cells — both tools report FAIL/NOT CLEAN on ANY refusal at all and on
p95 above the 30s budget, which is a stricter, different question than "did anything regress."

### `audit_compare.py` verdict lines, verbatim

Round 1 full compare (`gate/audit-compare-r1.txt`):
```
clean 66  refused 6  invalid 0  crashed 0  paired 66  area ratio 1.0000  p95 31.3s
  FAIL REFUSED: freeform universe-matrix/all-products: the 30s deadline passed with no completed packing of 53 strips; 1 pack was routed in that time and the best of them still left 30 nets unrouted (worst 30), so a longer clock alone would not have wired this spec; 1 other pack stopped during exact preparation. This is a REFUSAL and not a verdict on the spec
  FAIL REFUSED: freeform universe-matrix/no-proliferator: the 30s deadline passed with no completed packing of 57 strips; 2 packs were routed in that time and the best of them still left 3 nets unrouted (worst 5), so a longer clock alone would not have wired this spec. This is a REFUSAL and not a verdict on the spec
  FAIL REFUSED: freeform universe-matrix/output-products: the 30s deadline passed with no completed packing of 54 strips; 2 packs were routed in that time and the best of them still left 12 nets unrouted (worst 60), so a longer clock alone would not have wired this spec. This is a REFUSAL and not a verdict on the spec
  FAIL REFUSED: sequence-pair universe-matrix/no-proliferator: all 4 sequence islands refused: island 0: deadline exhausted before finding an exact layout; island 1: deadline exhausted before finding an exact layout; island 2: deadline exhausted before finding an exact layout; island 3: deadline exhausted before finding an exact layout
  FAIL REFUSED: sequence-pair universe-matrix/all-products: all 4 sequence islands refused: island 0: deadline exhausted before finding an exact layout; island 1: deadline exhausted before finding an exact layout; island 2: deadline exhausted before finding an exact layout; island 3: deadline exhausted before finding an exact layout
  FAIL REFUSED: sequence-pair universe-matrix/output-products: all 4 sequence islands refused: island 0: deadline exhausted before finding an exact layout; island 1: deadline exhausted before finding an exact layout; island 2: deadline exhausted before finding an exact layout; island 3: deadline exhausted before finding an exact layout
  FAIL p95 wall 31.3s exceeds 30.0s
FAIL
```

Round 1 regressions-only (`gate/audit-compare-r1-regressions.txt`): same header line, `FAIL p95 wall
31.3s exceeds 30.0s`, and all six lines above as `note CARRIED:` (not new failures — carried over
from baseline) — no `FAIL REGRESSION:` line appears anywhere.

Round 2 full compare (`gate/audit-compare-r2.txt`):
```
clean 66  refused 6  invalid 0  crashed 0  paired 66  area ratio 0.9994  p95 31.4s
  FAIL REFUSED: freeform universe-matrix/all-products: the 30s deadline passed with no completed packing of 53 strips; 1 pack was routed in that time and the best of them still left 30 nets unrouted (worst 30), so a longer clock alone would not have wired this spec; 1 other pack stopped during exact preparation. This is a REFUSAL and not a verdict on the spec
  FAIL REFUSED: freeform universe-matrix/no-proliferator: the 30s deadline passed with no completed packing of 57 strips; 2 packs were routed in that time and the best of them still left 3 nets unrouted (worst 59), so a longer clock alone would not have wired this spec. This is a REFUSAL and not a verdict on the spec
  FAIL REFUSED: freeform universe-matrix/output-products: the 30s deadline passed with no completed packing of 54 strips; 2 packs were routed in that time and the best of them still left 12 nets unrouted (worst 74), so a longer clock alone would not have wired this spec. This is a REFUSAL and not a verdict on the spec
  FAIL REFUSED: sequence-pair universe-matrix/no-proliferator: all 4 sequence islands refused: island 0: deadline exhausted before finding an exact layout; island 1: deadline exhausted before finding an exact layout; island 2: deadline exhausted before finding an exact layout; island 3: deadline exhausted before finding an exact layout
  FAIL REFUSED: sequence-pair universe-matrix/all-products: all 4 sequence islands refused: island 0: deadline exhausted before finding an exact layout; island 1: deadline exhausted before finding an exact layout; island 2: deadline exhausted before finding an exact layout; island 3: deadline exhausted before finding an exact layout
  FAIL REFUSED: sequence-pair universe-matrix/output-products: all 4 sequence islands refused: island 0: deadline exhausted before finding an exact layout; island 1: deadline exhausted before finding an exact layout; island 2: deadline exhausted before finding an exact layout; island 3: deadline exhausted before finding an exact layout
  FAIL p95 wall 31.4s exceeds 30.0s
FAIL
```

Round 2 regressions-only (`gate/audit-compare-r2-regressions.txt`): same header line, `FAIL p95 wall
31.4s exceeds 30.0s`, and all six lines above as `note CARRIED:` — no `FAIL REGRESSION:` line
appears anywhere.

**Zero `FAIL REGRESSION:` lines in either round.** Every `FAIL` line in both rounds is either
`FAIL REFUSED:` (carried from baseline, confirmed by the matching `note CARRIED:` line in the
regressions-only file) or the absolute `FAIL p95 wall ... exceeds 30.0s` threshold check, which
compares to the fixed 30s budget, not to the baseline arm.

### Per-arm counts, status changes, area ratio, wall percentiles

Computed directly from the three committed JSONL files (`audit-baseline.jsonl`,
`audit-candidate-r1.jsonl`, `audit-candidate-r2.jsonl`), pairing by
`(strategy, url_id, spec_label, power, budget)` per Task 2's method. Raw JSONL row order
differs; `(strategy, url_id, spec_index)` also pairs all 72 cells correctly.

| arm | strategy | CLEAN | REFUSED | INVALID | CRASHED |
|---|---|---|---|---|---|
| baseline | freeform | 33 | 3 | 0 | 0 |
| baseline | sequence-pair | 33 | 3 | 0 | 0 |
| baseline | **total** | **66** | **6** | **0** | **0** |
| candidate r1 | freeform | 33 | 3 | 0 | 0 |
| candidate r1 | sequence-pair | 33 | 3 | 0 | 0 |
| candidate r1 | **total** | **66** | **6** | **0** | **0** |
| candidate r2 | freeform | 33 | 3 | 0 | 0 |
| candidate r2 | sequence-pair | 33 | 3 | 0 | 0 |
| candidate r2 | **total** | **66** | **6** | **0** | **0** |

Status changes between baseline and candidate, both directions, both rounds:

| round | paired keys | CLEAN -> not CLEAN | not CLEAN -> CLEAN |
|---|---|---|---|
| 1 | 72 of 72 | **0** | **0** |
| 2 | 72 of 72 | **0** | **0** |

Zero cells changed bucket in either direction in either round. All 66 baseline-CLEAN cells stayed
CLEAN in both candidate rounds; all 6 baseline-REFUSED cells (all `universe-matrix`) stayed REFUSED
in both candidate rounds.

Geomean area ratio, over cells CLEAN in both arms:

| round | paired CLEAN/CLEAN cells | geomean area ratio |
|---|---|---|
| 1 | 66 of 66 | **1.000000** |
| 2 | 66 of 66 | **0.999424** |

p50 / p95 wall (`build_wall_time_s`, all 72 cells per arm):
Percentiles use nearest rank: `index = ceil(p*n) - 1` into sorted values.

| round | arm | p50 | p95 |
|---|---|---|---|
| 1 | baseline | 23.0540s | 30.8735s |
| 1 | candidate | 28.0621s | 31.3292s |
| 2 | baseline | 23.0540s | 30.8735s |
| 2 | candidate | 27.2657s | 31.4475s |

p95 relative change, candidate vs. baseline: **round 1: +1.4761%**, **round 2: +1.8591%**. Both
figures are above Task 2's measured same-arm noise floor (1.3%, from `control-task2.md`) — this is a
measured rise, reported as measured; it is not part of this task's PASS condition (which names the
six `universe-matrix` cells, lane invariants, and zero regressions, not a p95 ceiling) but it is a
real number and is not softened here.

### Attribution of the wall-time increase

Recomputed from the committed JSONL using the same nearest-rank definition:

| arm | non-universe-matrix p50 | non-universe-matrix p95 | p95 change |
|---|---|---|---|
| baseline (66 cells) | 26.9928s | 30.8735s | — |
| candidate r1 (66 cells) | 27.2560s | 31.2729s | +1.2935% |
| candidate r2 (66 cells) | 27.0594s | 31.1150s | +0.7820% |

The non-universe-matrix p95 changes remain within the 1.3% noise floor. Paired
wall-time deltas sum to **+175.0838s / +170.8763s** for the six universe-matrix
cells, versus **+6.3235s / -4.8346s** for the other 66, changing sign between rounds.
The aggregate cost is concentrated in the six refusing cells; the remaining changes
are consistent with noise, not a demonstrated corpus-wide slowdown.

On the baseline those six cells hit the plan-time guard in 0.2315–3.5649s.
After its deletion and the pack-work scaling, they spend approximately the 30s
budget searching before refusing. Moving six values from the bottom into the tail
changes both percentiles; p95 is the 69th of the 72 sorted values.
Task 2's intermediate capture isolates the stages: its three sequence-pair cells
already took 27.7601–30.7607s, while its freeform cells still took 0.7276–2.6943s.
Task 1 removed the sequence-pair fast refusal; Task 3 let freeform proceed past its
undersized deterministic pack allowance.

Summed per-cell wall time is **1272.5527s → 1453.9599s / 1438.5943s**
(approximately +14.3% / +13.0%); these sums are not the concurrent audit's elapsed
wall time. The worst candidate cell is sequence-pair universe-matrix/output-products
at **33.9875s**, compared with a baseline maximum of **31.2071s**: maximum end-to-end
overrun against 30s grew from about **4.0% to 13.3%**.

The baseline was captured in Task 2's earlier session under different CPU pressure,
so this is not a same-session paired timing experiment. The per-cell breakdown
nevertheless supports the attribution above. The final review accepted this real,
concentrated cost: retaining a guard that rejects routable fan-out merely to save
about 175s would trade correctness for an early false refusal. **Coverage still FAILS.**

## Step 5: the six `universe-matrix` cells, named, both rounds, both arms

| strategy | cell | round 1 candidate | round 2 candidate | baseline (both rounds, reused) |
|---|---|---|---|---|
| freeform | no-proliferator | REFUSED | REFUSED | REFUSED |
| freeform | all-products | REFUSED | REFUSED | REFUSED |
| freeform | output-products | REFUSED | REFUSED | REFUSED |
| sequence-pair | no-proliferator | REFUSED | REFUSED | REFUSED |
| sequence-pair | all-products | REFUSED | REFUSED | REFUSED |
| sequence-pair | output-products | REFUSED | REFUSED | REFUSED |

None of the six is CLEAN in either round on either arm. Refusal text, verbatim, per cell:

**freeform / universe-matrix/no-proliferator**
- Round 1: "the 30s deadline passed with no completed packing of 57 strips; 2 packs were routed in that time and the best of them still left 3 nets unrouted (worst 5), so a longer clock alone would not have wired this spec. This is a REFUSAL and not a verdict on the spec"
- Round 2: "the 30s deadline passed with no completed packing of 57 strips; 2 packs were routed in that time and the best of them still left 3 nets unrouted (worst 59), so a longer clock alone would not have wired this spec. This is a REFUSAL and not a verdict on the spec"
- Baseline: "a producer lane has fewer tiles than the consumers it must tap, so two junctions would have to share one tile. antimatter: mass-energy-storage#23 lane is 10 tile(s) wide but must tap 15 consumer lane(s) of universe-matrix#37"

**freeform / universe-matrix/all-products**
- Round 1: "the 30s deadline passed with no completed packing of 53 strips; 1 pack was routed in that time and the best of them still left 30 nets unrouted (worst 30), so a longer clock alone would not have wired this spec; 1 other pack stopped during exact preparation. This is a REFUSAL and not a verdict on the spec"
- Round 2: identical text to round 1 (same "1 pack ... worst 30 ... 1 other pack stopped during exact preparation")
- Baseline: "a producer lane has fewer tiles than the consumers it must tap, so two junctions would have to share one tile. antimatter: mass-energy-storage#23 lane is 10 tile(s) wide but must tap 12 consumer lane(s) of universe-matrix#37"

**freeform / universe-matrix/output-products**
- Round 1: "the 30s deadline passed with no completed packing of 54 strips; 2 packs were routed in that time and the best of them still left 12 nets unrouted (worst 60), so a longer clock alone would not have wired this spec. This is a REFUSAL and not a verdict on the spec"
- Round 2: "the 30s deadline passed with no completed packing of 54 strips; 2 packs were routed in that time and the best of them still left 12 nets unrouted (worst 74), so a longer clock alone would not have wired this spec. This is a REFUSAL and not a verdict on the spec"
- Baseline: "a producer lane has fewer tiles than the consumers it must tap, so two junctions would have to share one tile. antimatter: mass-energy-storage#23 lane is 10 tile(s) wide but must tap 12 consumer lane(s) of universe-matrix#37"

**sequence-pair / universe-matrix/no-proliferator** (rounds 1 and 2 identical text)
- Candidate (both rounds): "all 4 sequence islands refused: island 0: deadline exhausted before finding an exact layout; island 1: deadline exhausted before finding an exact layout; island 2: deadline exhausted before finding an exact layout; island 3: deadline exhausted before finding an exact layout"
- Baseline: "all 4 sequence islands refused: island 0: a producer lane has fewer tiles than the consumers it must tap, so two junctions would have to share one tile. antimatter: mass-energy-storage#23 lane is 10 tile(s) wide but must tap 15 consumer lane(s) of universe-matrix#37; island 1: [same]; island 2: [same]; island 3: [same]"

**sequence-pair / universe-matrix/all-products** (rounds 1 and 2 identical text)
- Candidate (both rounds): "all 4 sequence islands refused: island 0: deadline exhausted before finding an exact layout; island 1: deadline exhausted before finding an exact layout; island 2: deadline exhausted before finding an exact layout; island 3: deadline exhausted before finding an exact layout"
- Baseline: "all 4 sequence islands refused: island 0: a producer lane has fewer tiles than the consumers it must tap, so two junctions would have to share one tile. antimatter: mass-energy-storage#23 lane is 10 tile(s) wide but must tap 12 consumer lane(s) of universe-matrix#37; island 1: [same]; island 2: [same]; island 3: [same]"

**sequence-pair / universe-matrix/output-products** (rounds 1 and 2 identical text)
- Candidate (both rounds): "all 4 sequence islands refused: island 0: deadline exhausted before finding an exact layout; island 1: deadline exhausted before finding an exact layout; island 2: deadline exhausted before finding an exact layout; island 3: deadline exhausted before finding an exact layout"
- Baseline: "all 4 sequence islands refused: island 0: a producer lane has fewer tiles than the consumers it must tap, so two junctions would have to share one tile. antimatter: mass-energy-storage#23 lane is 10 tile(s) wide but must tap 12 consumer lane(s) of universe-matrix#37; island 1: [same]; island 2: [same]; island 3: [same]"

Note what moved and what didn't: the CANDIDATE refusal text no longer says "must tap" anywhere (the
fan-out guard this branch deleted, per Task 1, is gone from all 6 messages, both rounds) — but all 6
cells are still not CLEAN, now for the two different reasons ranked in `residual.md`: the freeform
arm's clock-limited packing shortfall (residual.md item 3) and the sequence-pair arm's
non-converging per-island exact search (residual.md item 2). The sequence-pair text is byte-identical
across both rounds for all three cells; the freeform text's strip counts are stable (57/53/54) but
the "worst" unrouted-net figures and pack counts vary slightly round to round (e.g.
no-proliferator's worst count: 5 in round 1, 59 in round 2) — consistent with `residual.md`'s framing
that this is a budget-limited search that varies run to run, which is exactly why the brief calls for
two rounds.

## The two known reds

- `test_two_stage_alignment_retains_cp_sat_direct_opportunity`
  (`tests/layout/test_sequence_pair.py`) — **failed**, as expected. Pre-existing, not caused by this
  branch's work (Global Constraints name it as a known red; nothing on this branch touches
  `_pack`'s `direct` scoring).
- `test_all_products_sequence_pair_honours_the_exact_layout_deadline` (`tests/test_pipeline.py:707`)
  — **passed** this run, contrary to being named a pre-existing known red. Recorded, not
  reconciled: see Step 2 above for why (a load-timing-sensitive test whose own comments document it
  as racing a measured ceiling). No third failure occurred either way.

## Reading

**PASS condition** (per the brief and Ruling text): all six `universe-matrix` cells CLEAN in both
rounds and both arms; every lane single-item; 72/72 paired against master with zero regressions.

**Measured against that condition:**

1. *Six `universe-matrix` cells CLEAN, both rounds, both arms* — **NOT MET**. All 6 cells are
   REFUSED on the candidate in both rounds (Step 5 table), and REFUSED on the reused baseline as
   well (for a different, older reason — the fan-out guard this branch deleted). Zero of six are
   CLEAN anywhere.
2. *Every lane single-item* — **not established either way, and the gate says so plainly rather than
   claiming the invariant held.** No cell in this corpus round produced a placement for the six
   refusing cells to check `flow.lane_single_item` against (all six refused before emission). The
   real enforcement mechanism, per `residual.md`, is `validate._lane_single_item`
   (`src/flab2bp/layout/validate.py:6318`), reached via `scripts/audit.py:446` (`report =
   validate.validate(placement, spec, ...)`) and `:463` (`if report.ok and not skipped_power`) — a
   cell is only marked CLEAN if that check, among all registered `CHECKS`, passed. So: **every one
   of the 66 CLEAN cells in this corpus, in both rounds, passed `flow.lane_single_item` by
   construction** (a CLEAN status is proof the check ran and did not fire). That establishes the
   invariant held for the 66 cells that built successfully. It establishes **nothing** for the six
   refusing `universe-matrix` cells specifically — there is no placement for those six to run the
   check against, in either round, on either arm. This is a coverage gap, not a finding of a defect.
3. *72/72 paired against master with zero regressions* — **MET**. 72 of 72 keys paired in both
   rounds; 0 cells moved CLEAN -> not CLEAN or not CLEAN -> CLEAN in either round (Step 4 table);
   every `FAIL` line in both `audit_compare` runs is either the absolute p95-vs-30s threshold check
   or a `FAIL REFUSED:`/`note CARRIED:` pair for one of the six pre-existing `universe-matrix`
   refusals — never a `FAIL REGRESSION:` line.

**Verdict: FAIL.** Condition 1 is not met, so the gate cannot PASS regardless of conditions 2 and 3.

**Which residual blocker is still standing:** both of the two blockers `residual.md` ranks as having
"no measured fix in hand" are the ones this round's own refusal text shows, one per arm, matching
`residual.md`'s own framing of spec §4.3 blocker 3:

- **freeform arm** — `residual.md` item 3 ("the freeform failure mode is still partly clock-limited"
  at a 30s budget, as opposed to item 1's distinct "PACKER defect" symptom which `residual.md`
  measured only at a 300s budget this gate does not use). This round's own text confirms the 30s
  framing directly: *"the 30s deadline passed with no completed packing of 57 strips; 2 packs were
  routed in that time and the best of them still left 3 nets unrouted (worst 5), so a longer clock
  alone would not have wired this spec"* (round 1, no-proliferator) — the refusal text itself already
  concedes a longer clock would not fix it, while still being (per `residual.md`'s own distinction) a
  budget-limited search whose numbers vary round to round, which this gate's two rounds confirm (the
  "worst" figure moved from 5 to 59 between rounds for this same cell).
- **sequence-pair arm** — `residual.md` item 2, quoted there as: *"The sequence-pair per-island exact-
  layout search does not converge with a longer clock"* (`src/flab2bp/layout/sequence_islands.py:223`,
  `src/flab2bp/layout/sequence_solver.py:1601`). This round's text is byte-identical to
  `residual.md`'s own build 2 and build 4 (30s and 300s) captures for all three cells: *"all 4
  sequence islands refused: island 0: deadline exhausted before finding an exact layout; ..."* — and
  is byte-identical between this gate's round 1 and round 2 as well, confirming `residual.md`'s
  finding that this failure mode does not vary with either clock or run.

No task in this branch's plan claims a fix for either of these (per the plan's own self-review:
"No task for §4.2's fixes. Deliberate ... Task 4 measures and ranks them rather than a task
pretending to fix them"). This gate's measurement agrees with `residual.md`'s and `control-task2.md`'s
prior conclusions and with spec §4.3's own stated expectation of a coverage FAIL — that agreement
does not license softening this verdict, and this verdict was not declared without running both
rounds.

## Bottom line

- Coverage: **66/72 CLEAN** on both arms, both rounds (6 `universe-matrix` cells REFUSED throughout).
- Regressions: **zero**, both rounds (0/72 cells moved CLEAN -> not CLEAN).
- Area ratio (paired CLEAN/CLEAN): **1.000000** (round 1), **0.999424** (round 2).
- **FAIL** — six-cell coverage condition not met. Ranked residual blockers: freeform's clock-limited
  packing shortfall and sequence-pair's non-converging per-island search, both named above with this
  round's own verbatim refusal text.
