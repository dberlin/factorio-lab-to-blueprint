# Phase C baseline

Generated on 2026-09-02 (box never idle; see load snapshots below) from commit `22bf910`
(`docs: close the Phase B ledger at the merge`), which is the master that includes Phase B
(fast-forward merge of `phase-b-last-mile`, including master's rates commit `2cabb77`).

Prerequisite checks (Step 1), all passed:
- `git log --oneline -3` at HEAD `22bf910`; `git status --porcelain` clean.
- `uv run python -c "from flab2bp.layout.route_feedback import ClusterRelationNoGood; print(...)"`
  -> `cluster no-good OK`.
- `uv run python scripts/audit_compare.py --help` lists both `--regressions-only` and
  `--require-clean`.

Command, three interleaved rounds:

    uv run python scripts/audit.py --budget 30 --jobs 16 --json baseline-budget30-round<N>.jsonl

The box (128 cores, 1 TB RAM) is never idle; its load is disk I/O wait, not CPU, so rounds were
not run against an idle machine. Load immediately before each round:

| Round | uptime load avg (1/5/15m) | vmstat (r, wa, id — 3 samples) |
|---|---|---|
| 1 | 4.68 / 5.01 / 6.78 | r=3,4,7  wa=0,0,0  id=93,97,96 |
| 2 | 15.79 / 8.86 / 8.00 | r=2,4,1  wa=0,0,0  id=93,98,98 |
| 3 | 16.26 / 11.05 / 8.86 | r=1,2,1  wa=0,0,0  id=93,99,98 |

(All three rounds show near-zero `wa`, i.e. no I/O wait was actually observed during this run
despite the rising `r`/load-average figures; `id` stayed above 90% throughout. Wall times below
are essentially unaffected: 73s, 72s, 72s total for the 72-cell sweep, well under the 3-5 minute
expectation.)

| Round | CLEAN | REFUSED | INVALID | CRASH | p95 wall (s) |
|---|---:|---:|---:|---:|---:|
| 1 | 66 | 6 | 0 | 0 | 28.6 |
| 2 | 66 | 6 | 0 | 0 | 28.3 |
| 3 | 66 | 6 | 0 | 0 | 28.5 |

(p95 is a per-file `sort -n` percentile on the 72 raw `seconds` values: 28.598s / 28.262s /
28.450s for rounds 1/2/3 respectively. `audit_compare.py`'s own paired-cell p95, computed only
over the 63 cells clean on both sides of a cross-file comparison, agrees closely: 28.8s / 28.6s /
28.6s against Phase B's rounds below, and 28.6s for this task's own round-2-vs-round-1 same-arm
check.)

**This master is 66/72, not the 65/72 Phase B reported for its own three rounds.** The gate
differs by one cell net, and per Facts and Rulings below that is `2cabb77` (the rates commit),
not measurement noise — see the flip list. Nothing was tuned to reach 66; this is what
`scripts/audit.py --budget 30 --jobs 16` reports on `22bf910` as merged. Total: 216/216 lines
present, 72 per file, no round differs from its neighbours by more than one cell (all three are
identically 66/6/0/0, and the same 6 cells REFUSE in every round with identical `detail` text —
see below), so no anomalous round was seen.

Same-arm noise, round 2 against round 1 (this task's own two rounds; both post-rates-commit):

    uv run python scripts/audit_compare.py baseline-budget30-round1.jsonl baseline-budget30-round2.jsonl --regressions-only
    clean 66  refused 6  invalid 0  crashed 0  paired 66  area ratio 1.0001  p95 28.6s
    (6 CARRIED REFUSED notes, 0 REGRESSION lines)
    PASS

**Area ratio 1.0001** is the same-arm noise floor; `--noise-area` must not be tightened below
this (currently the tool's default 0.013 has ~13x headroom over observed same-arm noise).

## Cells this phase targets, and what they say in the baseline

Identical status/wall/area/detail in all three rounds (rounds' `seconds` vary by ~1s, area is
exact and unchanged); round 1 shown, all figures confirmed unchanged across rounds 2 and 3.

| Cell | Strategy | Baseline status | Wall (s) | Area | Detail |
|---|---|---|---:|---:|---|
| graphene/output-products | sequence-pair | CLEAN | 2.66 | 420.0 | (none) |
| universe-matrix/no-proliferator | sequence-pair | REFUSED | 28.90 | 0.0 | deadline exhausted before finding an exact layout |
| universe-matrix/all-products | sequence-pair | REFUSED | 28.35 | 0.0 | deadline exhausted before finding an exact layout |
| universe-matrix/no-proliferator | freeform | REFUSED | 3.32 | 0.0 | every packing that wired was rejected by our own validator (game.blueprint_area; findings: band 0 game.blueprint_area (): a 264x162 extent fits no band on a segment-200 planet: it needs 162 latitude rows in its better orientation and the tallest band (200 segments) holds 160. The game refuses this paste with EBuildCondition.BlueprintAreaCrossTropic.); a placement that fails validation is refused rather than returned, because an invalid blueprint pastes and then does not run |

Note: `sequence-pair graphene/output-products` is CLEAN on this master. Under Phase B's own
candidate rounds (pre-this-task, post-Phase-B-merge but measured before `2cabb77`) it was
REFUSED — see the flip list below. It is CLEAN here as a direct, unplanned effect of the rates
commit, not of anything Phase C does; Phase C's plan still treats it as a target cell to hold
CLEAN (or improve) through the ALNS/window-repair work, not to regress back to REFUSED.

The 6 cells that REFUSE in every one of this task's three rounds, identical `detail` each time:

| Strategy | Cell | Detail (verbatim) |
|---|---|---|
| freeform | universe-matrix/no-proliferator | every packing that wired was rejected by our own validator (game.blueprint_area; findings: band 0 game.blueprint_area (): a 264x162 extent fits no band on a segment-200 planet: it needs 162 latitude rows in its better orientation and the tallest band (200 segments) holds 160. The game refuses this paste with EBuildCondition.BlueprintAreaCrossTropic.); a placement that fails validation is refused rather than returned, because an invalid blueprint pastes and then does not run |
| freeform | universe-matrix/output-products | no packing of 43 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing |
| freeform | universe-matrix/all-products | no packing of 42 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing |
| sequence-pair | universe-matrix/output-products | deadline exhausted before finding an exact layout |
| sequence-pair | universe-matrix/all-products | deadline exhausted before finding an exact layout |
| sequence-pair | universe-matrix/no-proliferator | deadline exhausted before finding an exact layout |

## Comparison against Phase B's own candidate rounds

Phase B's candidate rounds (`docs/superpowers/evidence/2026-09-02-phase-b-last-mile/candidate-budget30-round{1,2,3}.jsonl`)
were measured before the rates commit `2cabb77` landed on master. This task's three rounds are
the first measurement of the merged tree (Phase B + `2cabb77`). Phase B's own rounds were all
65 CLEAN / 7 REFUSED; this task's are all 66 CLEAN / 6 REFUSED (net +1).

Round-by-round comparison, `scripts/audit_compare.py BASELINE=phase-B-candidate-round<N>
CANDIDATE=this-task-round<N> --expect-cells 72 --p95-seconds 31`, default mode then
`--regressions-only`, verbatim:

### Round 1

    clean 66  refused 6  invalid 0  crashed 0  paired 63  area ratio 0.7169  p95 28.8s
      FAIL REFUSED: freeform universe-matrix/no-proliferator: ...
      FAIL REFUSED: freeform universe-matrix/output-products: ...
      FAIL REFUSED: freeform universe-matrix/all-products: ...
      FAIL REFUSED: sequence-pair universe-matrix/output-products: ...
      FAIL REFUSED: sequence-pair universe-matrix/all-products: ...
      FAIL REFUSED: sequence-pair universe-matrix/no-proliferator: ...
    FAIL

    --regressions-only:
    clean 66  refused 6  invalid 0  crashed 0  paired 63  area ratio 0.7169  p95 28.8s
      FAIL REGRESSION: freeform universe-matrix/all-products: ...
      FAIL REGRESSION: sequence-pair universe-matrix/output-products: ...
      note CARRIED: freeform universe-matrix/no-proliferator: ...
      note CARRIED: freeform universe-matrix/output-products: ...
      note CARRIED: sequence-pair universe-matrix/all-products: ...
      note CARRIED: sequence-pair universe-matrix/no-proliferator: ...
    FAIL

### Round 2

    clean 66  refused 6  invalid 0  crashed 0  paired 63  area ratio 0.7168  p95 28.6s
    FAIL (same 6 FAIL REFUSED lines as round 1)

    --regressions-only:
    clean 66  refused 6  invalid 0  crashed 0  paired 63  area ratio 0.7168  p95 28.6s
    FAIL (same 2 FAIL REGRESSION + 4 note CARRIED lines as round 1)

### Round 3

    clean 66  refused 6  invalid 0  crashed 0  paired 63  area ratio 0.7167  p95 28.6s
    FAIL (same 6 FAIL REFUSED lines as round 1)

    --regressions-only:
    clean 66  refused 6  invalid 0  crashed 0  paired 63  area ratio 0.7167  p95 28.6s
    FAIL (same 2 FAIL REGRESSION + 4 note CARRIED lines as round 1)

`audit_compare.py`'s default mode fails on any REFUSED/INVALID/CRASH row, which both the Phase B
side and this task's side have (6-7 cells) — that FAIL is expected and is not itself evidence of
a regression; `--regressions-only` is the meaningful signal, and it flags exactly 2 genuine new
REFUSED cells in every round, consistently:

- `freeform universe-matrix/all-products` — CLEAN under Phase B's candidate rounds, REFUSED here
  (packer defect: "no packing of 42 strips could be wired at any candidate height").
- `sequence-pair universe-matrix/output-products` — CLEAN under Phase B's candidate rounds,
  REFUSED here ("deadline exhausted before finding an exact layout").

The paired-cell count (63 of 72) undercounts the actual status-flip picture because
`--regressions-only`'s CARRIED/REGRESSION accounting only surfaces cells that got worse; a
direct pairwise diff of all 72 `(strategy, url_id, spec_label)` statuses between Phase B's
candidate-round-N and this task's round-N (identical for N=1,2,3) shows **5 status flips**, not
2:

| Cell | Strategy | Phase B (pre-2cabb77) | This master (post-2cabb77) |
|---|---|---|---|
| universe-matrix/all-products | freeform | CLEAN | REFUSED (regression) |
| universe-matrix/output-products | sequence-pair | CLEAN | REFUSED (regression) |
| quantum-chip/all-products | freeform | REFUSED | CLEAN (fixed) |
| quantum-chip/no-proliferator | sequence-pair | REFUSED | CLEAN (fixed) |
| graphene/output-products | sequence-pair | REFUSED | CLEAN (fixed) |

Net: 65 -> 66 CLEAN (+3 fixed, -2 regressed = +1), matching the CLEAN-count difference above.
`--regressions-only` only reports the 2 that got worse (by design — it is a regression gate,
not a full diff); the 3 that got better are real too and are listed here for completeness.

**Area ratio moved substantially: ~0.717 (candidate area is ~72% of Phase B's area, geometric
mean over the 63 cells clean on both sides), far outside the `--noise-area 0.013` tolerance and
far outside the same-arm noise floor of 1.0001 measured above.** This is the rates commit
`2cabb77`, not noise or Phase C work — inspecting individual paired areas shows large,
consistent shrinkage concentrated in several `url_id`s, e.g. (baseline area -> candidate area):
`casimir-crystal` cells 6396->1175, 6048->1230, 7011->1107 (~area ratio 0.16-0.25);
`quantum-chip` cells 19836->5110, 13578->4290, 10868->3655, 9072->3300 (~0.26-0.36);
`energy-matrix`, `graphene`, `information-matrix` cells also shrink by roughly half or more.
p95 wall time is essentially unchanged (28.6-28.8s candidate vs Phase B's own comparable p95
sitting under the 31s `--p95-seconds` bound in every round).

**Summary: the rates commit moved real cells, both in area (large, consistent shrinkage — smaller
machine footprints from corrected production rates) and in CLEAN/REFUSED status (5 flips: 3
fixed, 2 regressed, net +1). None of this is measurement noise — same-arm noise (round 2 vs
round 1, both post-2cabb77) is area ratio 1.0001 with zero status flips. Nothing here was
tuned or fixed; this is what the merged master already does.**

Every later measurement in `docs/superpowers/plans/2026-09-02-phase-c-alns-window-repair.md`
compares a candidate JSONL against this task's three files
(`baseline-budget30-round{1,2,3}.jsonl`), not against Phase B's candidate rounds.
