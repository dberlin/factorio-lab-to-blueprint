# Gate D2 — the portfolio corpus gate, budget 30, `--strategy all` (108 cells)

Verdict: **FAIL** — the area clause (spec §3, fourth Gate D2 bullet) fails in all three rounds.
Coverage, wall-max, and "not worse than Gate D1" all PASS. Per the brief: a FAIL is a valid
outcome, nothing was tuned, and Task 17 does not start.

## What was measured, and from where

- **Commit under test: `6b33e361a3aa54612913b71a2c3feca581fc221e`** (`6b33e36`, branch
  `phase-d-portfolio`) — Tasks 1–11, 13–15 with their fix rounds landed; Task 12 deferred by
  Ruling AN. HEAD of the worktree at dispatch time, confirmed via `git rev-parse HEAD`.
- **Serial baseline: `9fd65121c956c5479f0f50c6522e0ef885a45a01`** (`9fd6512` = `master`, the
  branch point; Ruling AG), file `baseline-budget30.jsonl` from Task 1, **not regenerated**
  (Ruling AH: read with `row.get` defaults — its rows carry no `commit`/`route_backend`).
- The three rounds were run **from a `git archive 6b33e36` extracted at
  `/home/dannyb/.claude/jobs/8e787b45/tmp/d2-gate/`**, not from the live worktree, reproducing
  Gate D1's method (`gate-d1.md`) exactly: the archive stays immune to any other implementer's
  in-flight edits.
- **Compiled kernels copied, not rebuilt.** `git diff --stat master 6b33e36 -- '*.pyx' '*.pxd'
  setup.py pyproject.toml` is **empty**, so the worktree's `_route_kernel.cpython-314-…so` and
  `_sequence_kernel.cpython-314-…so` were copied into the archive's `src/flab2bp/layout/`. Every
  row reports `route_backend == "cython"` (confirmed below).
- **Frozen `.git`, reproducing Gate D1's trick.** `git archive` carries no `.git`, so
  `audit.py:_head_commit()` would stamp `"unknown"`. A minimal `.git` was hand-built in the
  archive: `.git/HEAD` holding the raw `6b33e361a3aa54612913b71a2c3feca581fc221e` sha (detached),
  empty `.git/refs/`, and `.git/objects/info/alternates` pointing at the repository's real object
  store (`/home/dannyb/sources/factorio-lab-to-blueprint/.git/objects`). (Note beyond D1's method:
  an empty `.git` also needs a `refs/` directory present, not only `HEAD` + `objects/info` — git
  2.55 reports "not a git repository" without it; added and verified `git rev-parse HEAD` /
  `git cat-file -t` resolve the commit before freezing read-only.) Verified: all 324 rows across
  the three rounds carry `commit == 6b33e361a3aa54612913b71a2c3feca581fc221e` and
  `route_backend == "cython"`.
- Interpreter: the worktree's `.venv/bin/python` (CPython 3.14) driving the archive's
  `scripts/audit.py`.

### Green-tree check (brief Step 1), run on the live worktree

The live tree was clean at `6b33e36` (only untracked evidence JSONL, no other agent's WIP) at
dispatch, so — unlike Gate D1, which had to skip this step for concurrency reasons — it was safe
to run here:

- `pytest -q`: **exit 0** (Ruling S: the summary line never prints in this environment; exit code
  is the pass signal).
- `ruff check .`: **All checks passed!** exit 0.
- `mypy` (bare, using `pyproject.toml`'s `files = ["src", "tests"]`; `mypy .` on its own resolves
  the wrong package roots and is not the right invocation): **Found 184 errors in 16 files**,
  matching the branch-point baseline exactly (184 = 184, no new diagnostic).
- `setup.py build_ext --inplace`: **failed** — `ModuleNotFoundError: No module named 'Cython'` in
  this worktree's `.venv`. This is a pre-existing environment gap (Cython was never installed here
  for a source build), not a Task 16 change: the `.pyx`/`.pxd`/`setup.py`/`pyproject.toml` diff
  against master is empty (above), and the already-compiled `.so` files were reused unmodified, so
  the measurement is unaffected. Stated plainly rather than worked around.

### Invocation (per round r ∈ {1,2,3}), run from the archive root

```
.venv/bin/python scripts/audit.py --budget 30 --jobs 16 --strategy all \
    --json docs/superpowers/evidence/2026-09-02-phase-d-portfolio/race-budget30-round$r.jsonl
```

`--strategy all` → freeform + sequence-pair + best, 108 cells. `--jobs 16` → `per_cell_workers =
max(1, 128 // 16) = 8`; a `best` cell splits `(6, 2)` per spec §5.2, so a `best` cell forks two
CP-SAT users onto the 128-core box exactly as the brief warns. All three rounds completed inside
the default `--max-seconds`, no re-run at `--jobs 8` was needed.

## Load at the moment each round started (Ruling R: never wait for idle)

```
=== round 1 ===
 11:10:24 up 18 days, 16:56,  9 users,  load average: 3.94, 3.97, 3.93
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st gu
 3  0      0 1041246384  0 8111628   0    0 50072 15299 23435   4  5  2 93  0  0  0
 0  0      0 1041262048  0 8111620   0    0     0   737 13977 24886 1 1 98  0  0  0
 0  0      0 1041262996  0 8111620   0    0     0   328 13039 23696 1 1 98  0  0  0

=== round 2 ===
 11:12:29 up 18 days, 16:58,  9 users,  load average: 24.29, 12.85, 7.23
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st gu
 3  0      0 1041238756  0 8111756   0    0 50068 15300 23436   4  5  2 93  0  0  0
 0  0      0 1041254140  0 8111756   0    0     0   368 13758 26604 1 1 98  0  0  0
 0  0      0 1041252728  0 8111756   0    0     0     0 14833 26297 1 1 98  0  0  0

=== round 3 ===
 11:14:34 up 18 days, 17:00,  9 users,  load average: 24.70, 18.26, 9.99
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st gu
 3  0      0 1041234500  0 8111792   0    0 50064 15299 23437   4  5  2 93  0  0  0
 6  0      0 1041248440  0 8111788   0    0     0  1196 14330 22243 1 0 96  0  0  2
 5  0      0 1041245912  0 8111788   0    0    64 19612 18134 45611 1 1 97  0  0  1
```

Each round: 110 s, 110 s, 109 s wall for all 108 cells at `--jobs 16` (versus Gate D1's 71/71/72 s
for 72 cells — the extra 36 `best` cells, each doubling its own CP-SAT population, cost roughly
39 s of wall for 50% more cells). Load average climbed round to round (3.9 → 24.3 → 24.7) — never
waited on, recorded as found, per Ruling R.

## Provenance (Ruling AH)

| file | `commit` | `route_backend` | rows |
| --- | --- | --- | --- |
| `race-budget30-round1.jsonl` | `6b33e361a3aa54612913b71a2c3feca581fc221e` (all 108) | `cython` (all 108) | 108 |
| `race-budget30-round2.jsonl` | `6b33e361a3aa54612913b71a2c3feca581fc221e` (all 108) | `cython` (all 108) | 108 |
| `race-budget30-round3.jsonl` | `6b33e361a3aa54612913b71a2c3feca581fc221e` (all 108) | `cython` (all 108) | 108 |
| `baseline-budget30.jsonl` | key absent (read as `9fd6512`) | key absent (read as `cython`) | 72 |
| `wall-budget30-round1.jsonl` (Gate D1) | `842d9a0801df47fb4a4aa126b33a16793e9a22dc` (all 72) | `cython` (all 72) | 72 |

## Step 3 — explicit arms vs Gate D1 round 1, verbatim

Brief's literal invocation (**no** `--regressions-only`, so every non-CLEAN row — including the
six baseline-carried `universe-matrix` refusals both gates share — prints as a bare reason, not a
`note CARRIED`; this is the tool's documented behaviour without that flag, not a new failure):

```
== round 1 vs wall-budget30-round1.jsonl (--p95-seconds 30 --expect-cells 72, no --regressions-only) ==
clean 66  refused 6  invalid 0  crashed 0  paired 66  area ratio 0.9999  p95 28.7s
  FAIL REFUSED: freeform universe-matrix/no-proliferator: ... (validator rejection)
  FAIL REFUSED: freeform universe-matrix/output-products: ... (packer defect)
  FAIL REFUSED: freeform universe-matrix/all-products: ... (packer defect)
  FAIL REFUSED: sequence-pair universe-matrix/all-products: deadline exhausted before finding an exact layout
  FAIL REFUSED: sequence-pair universe-matrix/output-products: deadline exhausted before finding an exact layout
  FAIL REFUSED: sequence-pair universe-matrix/no-proliferator: deadline exhausted before finding an exact layout
FAIL
exit=1

== round 2 vs wall-budget30-round1.jsonl ==
clean 66  refused 6  invalid 0  crashed 0  paired 66  area ratio 1.0013  p95 28.5s
  (same six FAIL REFUSED lines)
FAIL
exit=1

== round 3 vs wall-budget30-round1.jsonl ==
clean 66  refused 6  invalid 0  crashed 0  paired 66  area ratio 0.9990  p95 28.6s
  (same six FAIL REFUSED lines)
FAIL
exit=1
```

**72 rows extracted per round** (confirmed) and **clean 66 in every round, at or equal to Gate D1
round 1's clean 66/72** — the brief's Step 3 expectation, satisfied in all three rounds.

Because the bare `FAIL` verdict above is an artifact of the flag combination the brief specifies
(no `--regressions-only`), the same three comparisons were re-run **with** `--regressions-only`
(Gate D1's own flag set) as a cross-check that no cell regressed:

```
== round 1 (regressions-only) ==            == round 2 (regressions-only) ==            == round 3 (regressions-only) ==
clean 66  area ratio 0.9999  p95 28.7s      clean 66  area ratio 1.0013  p95 28.5s      clean 66  area ratio 0.9990  p95 28.6s
6× note CARRIED (the same baseline refusals)  6× note CARRIED                             6× note CARRIED
PASS  exit=0                                PASS  exit=0                                PASS  exit=0
```

Zero `REGRESSION:` lines in any round. The explicit freeform/sequence-pair arms are not worse than
Gate D1 round 1.

## Step 4 — portfolio conditions vs the SERIAL baseline, verbatim

```
round1: rows 108  clean 99/108  p95 28.70s  max 29.22s  invalid 0  crash 0
  coverage misses vs serial baseline: none
  area misses vs serial baseline:     ['casimir-crystal/#2 ratio 1.0400', 'electromagnetic-matrix/#1 ratio 1.1124',
                                        'energy-matrix/#1 ratio 1.0189', 'energy-matrix/#2 ratio 1.3986',
                                        'information-matrix/#1 ratio 1.1245', 'plastic/#2 ratio 1.1700',
                                        'processor/#0 ratio 1.0556', 'processor/#2 ratio 1.0246']
  commit 6b33e361a3aa  backends ['cython']
round2: rows 108  clean 99/108  p95 28.88s  max 30.26s  invalid 0  crash 0
  coverage misses vs serial baseline: none
  area misses vs serial baseline:     ['electromagnetic-matrix/#1 ratio 1.1124', 'energy-matrix/#1 ratio 1.0189',
                                        'energy-matrix/#2 ratio 1.3986', 'magnetic-coil/#2 ratio 1.0316',
                                        'plastic/#2 ratio 1.1700', 'processor/#2 ratio 1.0246',
                                        'super-magnetic-ring/#0 ratio 1.0158']
  commit 6b33e361a3aa  backends ['cython']
round3: rows 108  clean 99/108  p95 28.98s  max 29.65s  invalid 0  crash 0
  coverage misses vs serial baseline: none
  area misses vs serial baseline:     ['electromagnetic-matrix/#1 ratio 1.1124', 'energy-matrix/#1 ratio 1.0189',
                                        'energy-matrix/#2 ratio 1.3986', 'plastic/#2 ratio 1.1700',
                                        'processor/#0 ratio 1.0556', 'processor/#2 ratio 1.0246']
  commit 6b33e361a3aa  backends ['cython']
```

Max `seconds` (29.22 / 30.26 / 29.65) stays ≤ 35.0 s including `best` cells in every round.
Coverage is clean in every round. **The area clause fails in every round**, 6–8 cells per round,
worst case `energy-matrix/#2` (`output-products`) at **1.3986×** — a 40% area regression — and
that specific cell fails identically in all three rounds (not flake).

## Per-cell `best` vs `min(serial freeform, serial sequence-pair)`, all 33 clean-`best` cells

(`universe-matrix` × 3 specs REFUSED on `best` in every round, both explicit arms refused in the
serial baseline too — excluded, `n/a`. `2` = output-products, `1` = all-products, `0` =
no-proliferator throughout.)

| cell | round 1 ratio | round 2 ratio | round 3 ratio | verdict (any round) |
| --- | --- | --- | --- | --- |
| casimir-crystal/#0 | 1.0000 | 1.0000 | 1.0000 | PASS |
| casimir-crystal/#1 | 1.0000 | 1.0000 | 1.0000 | PASS |
| casimir-crystal/#2 | **1.0400** | 1.0000 | 1.0000 | FAIL (r1) |
| electromagnetic-matrix/#0 | 1.0000 | 1.0000 | 1.0000 | PASS |
| electromagnetic-matrix/#1 | **1.1124** | **1.1124** | **1.1124** | FAIL (all 3) |
| electromagnetic-matrix/#2 | 1.0000 | 1.0000 | 1.0000 | PASS |
| energy-matrix/#0 | 1.0000 | 1.0000 | 1.0000 | PASS |
| energy-matrix/#1 | **1.0189** | **1.0189** | **1.0189** | FAIL (all 3) |
| energy-matrix/#2 | **1.3986** | **1.3986** | **1.3986** | FAIL (all 3, worst) |
| graphene/#0-2 | 1.0000 | 1.0000 | 1.0000 | PASS |
| information-matrix/#0 | 1.0000 | 1.0000 | 1.0000 | PASS |
| information-matrix/#1 | **1.1245** | 1.0000 | 1.0000 | FAIL (r1) |
| information-matrix/#2 | 1.0000 | 1.0000 | 1.0000 | PASS |
| iron-ingot/#0-2 | 1.0000 | 1.0000 | 1.0000 | PASS |
| magnetic-coil/#0 | 1.0000 | 1.0000 | 1.0000 | PASS |
| magnetic-coil/#1 | 1.0000 | 1.0000 | 1.0000 | PASS |
| magnetic-coil/#2 | 1.0000 | **1.0316** | 1.0000 | FAIL (r2) |
| plastic/#0 | 1.0000 | 1.0000 | 1.0000 | PASS |
| plastic/#1 | 1.0000 | 0.9647 | 1.0000 | PASS |
| plastic/#2 | **1.1700** | **1.1700** | **1.1700** | FAIL (all 3) |
| processor/#0 | **1.0556** | 1.0000 | **1.0556** | FAIL (r1, r3) |
| processor/#1 | 1.0000 | 1.0000 | 1.0000 | PASS |
| processor/#2 | **1.0246** | **1.0246** | **1.0246** | FAIL (all 3) |
| quantum-chip/#0-2 | 1.0000 | 1.0000 | 1.0000 | PASS |
| super-magnetic-ring/#0 | 1.0000 | **1.0158** | 0.9910 | FAIL (r2) |
| super-magnetic-ring/#1-2 | 1.0000 | 1.0000 | 1.0000 | PASS |

**Root cause, cross-checked against the raced round's own explicit arms.** For every failing
cell, the raced round's own standalone `freeform` row (unraced, full `per_cell_workers=8`) matches
or beats the serial baseline (e.g. `energy-matrix/#2`: standalone-freeform 572 in all three rounds,
identical to a hypothetical serial-quality result), while `best`'s own race reports the
`sequence-pair`-equalling number (800) every time — i.e. `best`'s *internal, raced* freeform arm
(capped at 6 CP-SAT workers by the `(6, 2)` split, cold `geometry_memo`, competing on-box with a
second CP-SAT process) never reaches what the very same code reaches with 8 uncontested workers
seconds later in the same round. This is spec §11's predicted mechanism, not a new one: *"Both
arms get less CPU than either did serially… fewer effective cores buys a worse incumbent in the
same wall… Gate D2's per-cell area condition against the serial baseline arms is the detector"*
and *"the lost geometry-memo warm start… up to ~3 s of the sequence-pair arm's 30 s budget handed
back."* Both risks are visibly cashing out here.

## Gate D1 vs Gate D2, wall figures side by side

| | Gate D1 (explicit strategies only, 72 cells) | Gate D2 explicit-arm rows (72 of 108 cells) |
| --- | --- | --- |
| freeform max | 29.43 / 29.66 / 27.28 s | 29.07 / 28.43 / 29.65 s |
| freeform p95 | 26.96 / 28.67 / 27.17 s | 28.68 / 26.70 / 26.49 s |
| freeform median | ≈5.2–5.7 s | 5.37 / 4.74 / 5.66 s |
| sequence-pair max | 28.75 / 28.54 / 28.87 s | 28.71 / 28.88 / 29.20 s |
| sequence-pair p95 | 28.51 / 28.53 / 28.60 s | 28.35 / 28.56 / 28.53 s |
| sequence-pair median | ≈12.2–12.4 s | 12.83 / 12.49 / 12.54 s |
| `best` max (Gate D2 only) | — | 29.22 / 30.26 / 29.65 s |
| overall clean/72 | 66 / 66 / 66 | 66 / 66 / 66 |

Every figure sits inside Gate D1's envelope (differences under 2 s, within the corpus's own
freeform noise documented in `gate-d1.md`). Wall discipline is unaffected by racing.

## Spawn cost and `RACE_COMPLETION_GRACE_S` (`spawn-cost.txt`)

```
spawn-to-first-instruction (INSIDE the wall, context only): runs 10  min 0.100s  median 0.104s  max 0.107s
post-deadline tail (what the grace covers): runs 10  min 0.001s  median 0.001s  max 0.001s
RACE_COMPLETION_GRACE_S = ceil(tail_max) + ATOMIC_COMPLETION_GRACE_S = 1 + 5.0 = 6.0
```

## Wall overshoot (controller addendum)

`audit.py`'s `Result.wall_overshoot_s` is computed as `max(0, attempt_wall_s − budget −
ATOMIC_COMPLETION_GRACE_S)` for **every** strategy, including `best` — it does not know a `best`
row's real contract is `RACE_COMPLETION_GRACE_S = 6.0`, not `ATOMIC_COMPLETION_GRACE_S = 5.0`. The
row's own field therefore **over-reports** a `best` cell's overshoot by up to 1.0 s. Recomputed
directly from the rows with the correct grace, `max(0, attempt_wall_s − budget − 6.0)`:

| | row-reported (`ATOMIC_COMPLETION_GRACE_S = 5.0`, wrong for `best`) | recomputed (`RACE_COMPLETION_GRACE_S = 6.0`, correct for `best`) |
| --- | --- | --- |
| round 1, max over 33 `best` CLEAN rows | 0.000 s | 0.000 s |
| round 2, max over 33 `best` CLEAN rows | 0.000 s | 0.000 s |
| round 3, max over 33 `best` CLEAN rows | 0.000 s | 0.000 s |

Both figures are 0.000 s in every round because even the closest `best` row never got near
either grace threshold: the tightest margin against the *correct* 6.0 s grace was round 2's
`super-magnetic-ring/no-proliferator` at `attempt_wall_s=30.148s`, i.e. `30.148 − 30 − 6.0 =
−5.85 s` — 5.85 s of headroom under the real contract. **Max wall overshoot across all 324 rows,
all three strategies, correct grace per strategy: 0.000 s.** This also settles which of the two
numbers the reader should trust for `best`: they agree here, but the row's own field is the wrong
one to trust in general and a future gate that sees a nonzero `best` `wall_overshoot_s` should
recompute it against 6.0, not read the field verbatim.

**This statistic excludes REFUSED rows entirely — say plainly why.** `attempt_wall_s` /
`wall_overshoot_s` are present only on rows that produced a placement (`Result.attempt_wall_s:
float | None = None`, `None` when nothing was emitted); a REFUSED cell never gets a value, even
when its attempt visibly consumed nearly its whole budget. Confirmed structurally: 0 of the 27
REFUSED rows across the three rounds (9 per round, all `universe-matrix`) carry either key. Several
came within a second of their 30 s budget without exceeding it — closest, round 2's `best
universe-matrix/no-proliferator` at `seconds=29.89s` (margin −0.11 s) — but none actually reached
or exceeded 30 s, so there is no case in this corpus where a hidden REFUSED overshoot is being
missed by the 0.000 s figure above; the point stands as a caveat about the statistic's scope, not
as an under-counted overshoot here.

**Did any wall-discipline poll fire?** `audit.py`'s own "N cells completed after their own
requested search deadline" note printed in round 2 only: `1 cells completed after their own
requested search deadline; the largest completion tail was 0.3s` — the same
`super-magnetic-ring/no-proliferator` `best` cell above (`seconds=30.256s` vs `budget=30.0s`).
This is the tool's generic `seconds > budget` check (atomic completion — emission, routing,
validation — finishing after the nominal deadline), not evidence that Tasks 2–5's mid-search polls
(compaction cancel, cold-role refusal, anneal cut, archive stop) fired: `wall_overshoot_s` is 0.000
for that row under either grace, so nothing ran anywhere near `budget + grace`. Rounds 1 and 3
printed no such note (0 cells). **Consistent with Gate D1's finding: no wall-discipline poll fired
in any of the 324 rows.**

## No-good and incumbent counters (Ruling AN)

`_StrategyRaceOutcome` (spec §5.2) defines `published_incumbents`, `consumed_incumbents`,
`published_no_goods`, `consumed_no_goods`, `dropped_messages`, and `strategy_race.py` stamps them
in the child process — but **`scripts/audit.py`'s `Result` dataclass has no fields for any of the
five**, so none of them reach the JSONL at all (confirmed: absent from every one of the 108 `best`
rows in all three rounds; `race_terminated`, stamped unconditionally per Task 13's commit, is
likewise absent from the JSONL). This is a strict superset of Gate D1's Concern #2
(`attempt_wall_s`/`wall_overshoot_s` were invisible before Task 15 widened `Result` for those two
fields only) — the widening did not extend to the race-specific counters. Per **Ruling AN**,
`published_no_goods`/`consumed_no_goods` are structurally zero **by design** regardless (Task 12's
receiver wiring is deferred, so `external_no_goods`/`publish_no_good` are unreachable in this
build), so their absence from the audit changes nothing about what this gate can measure: **Gate
D2 measures incumbent sharing only**, and even that cannot be read from the rows this run produced
— it can only be asserted from the source (Task 10's own end-to-end proof, `progress.md`: "real
pool on plastic/20 s/16 workers: freeform published 2 consumed 1, sequence-pair published 1
consumed 1"). No production evidence of incumbent sharing exists in this gate's own JSONL.

## Determinism across the three rounds (non-timing fields; `seconds`, `build_wall_time_s`,
`commit`, `route_backend`, `attempt_wall_s`, `wall_overshoot_s` excluded)

- **sequence-pair**: round1 vs round2 **0/36** differ; round1 vs round3 **1/36**; round2 vs round3
  **1/36** — the one exception is `information-matrix/#2` (`output-products`), area 5394 (r1) →
  5150 (r2 = r3), the *same* cell Gate D1 found nondeterministic at the same commit range
  (`projection_frame_candidates` 2→1, `projection_count` 76→114). Sequence-pair stays 35/36
  cell-deterministic, unchanged in character from Gate D1.
- **freeform**: 5, 6, 6 of 36 cells differ across the three round pairs — the noisy arm, as in
  Gate D1; `casimir-crystal/#2`, `information-matrix/#1`, `super-magnetic-ring/#0-2`,
  `magnetic-coil/#1-2` move between rounds at the identical commit. No freeform code changed in
  Phase D; this is the arm's own wall-clock-bound CP-SAT nondeterminism, present at the baseline.
- **best**: 6, 3, 5 of 36 cells differ — a strict function of which arm's raced result won each
  round (freeform's own instability propagates into `best` whenever `best`'s internal freeform arm
  is the winner). No new source of nondeterminism: every `best`-cell movement corresponds to a
  freeform-side movement already characterized above, or to the same sequence-pair
  `information-matrix/#2` split.
- **Deadline-cut differences: none, in any pair, any strategy.** No cell in any round reached
  `deadline_reached` (max `seconds` 30.26 s against a 30 s budget with a 6 s race grace / 5 s
  atomic grace; the one 0.256 s-over-budget cell is the atomic completion tail, not a mid-search
  cut) — Tasks 2–5's wall-discipline polls stayed dormant, as in Gate D1.

## The gate, clause by clause (spec §3 Gate D2 wording, verbatim)

| # | Clause | round 1 | round 2 | round 3 | verdict |
| --- | --- | --- | --- | --- | --- |
| 1 | every `best` cell whose freeform **or** sequence-pair cell is CLEAN in the baseline is CLEAN | coverage misses: none | none | none | **PASS** |
| 2 | per-cell `seconds` maximum at or under 35.0 s, including `best` cells | max 29.22 s | max 30.26 s | max 29.65 s | **PASS** |
| 3 | the freeform and sequence-pair cells are not worse than Gate D1's rounds | clean 66/72, area 0.9999, p95 28.7s (PASS regressions-only) | clean 66/72, area 1.0013, p95 28.5s (PASS) | clean 66/72, area 0.9990, p95 28.6s (PASS) | **PASS** |
| 4 | for each `best` cell clean in both arms, `best` area ≤ 1.013 × min(freeform, sequence-pair) from the SERIAL baseline | 8 cells over 1.013× (worst 1.3986) | 7 cells over 1.013× (worst 1.3986) | 6 cells over 1.013× (worst 1.3986) | **FAIL** |
| — | INVALID 0 (context, not a spec-D2 bullet but tracked per the addendum) | 0 | 0 | 0 | PASS |
| — | CRASH 0 | 0 | 0 | 0 | PASS |

**Overall Gate D2 verdict: FAIL** (clause 4, all three rounds). Per the brief: commit under
`bench: record a failed phase D portfolio gate`; **do not start Task 17**.

## §11 risk readings this run speaks to

- **"Both arms get less CPU than either did serially… the regression is silent and shows up only
  as area."** Directly confirmed: every failing cell's `best` area equals its own round's
  *raced* sequence-pair arm (never below it), while the *unraced* standalone freeform cell in the
  same round reaches the serial-quality number. `best`'s internal, worker-capped freeform race arm
  is the one losing.
- **"Spawn cost is inside the wall."** Consistent with the measured 0.10–0.11 s spawn figure
  (`spawn-cost.txt`): no cell's `wall_overshoot_s` (either grace) is nonzero, so spawn cost alone
  did not push any cell over budget+grace on this corpus — but it is one plausible contributor to
  `best`'s internal freeform arm losing to its own unraced sibling by seconds of effective search
  time, alongside the worker-count cut.
- **"The lost geometry-memo warm start, knowingly paid."** Also consistent: the risk section names
  up to ~3 s handed back on `universe-matrix`-scale preparation; several of the failing cells
  (`electromagnetic-matrix`, `energy-matrix`, `processor`) are mid-tier cells where a few seconds
  of lost warm-start plus a worker cut is enough to keep the raced freeform arm from reaching what
  it reaches unraced.
- **"Two CP-SAT users on one box… the explicit split (5.2) is the mitigation… the residual risk is
  that both arms get less search than either did serially and `best` area regresses."** This is
  exactly the failure mode observed; the mitigation (the `(6, 2)` split) bounds the *count* of
  workers but does not recover the *serial* level of search this corpus's cells were getting.

## Next levers (a clause failed — nothing here was tuned)

The brief names exactly two knobs and forbids turning either without re-running the gate:
`RACE_FREEFORM_WORKER_SHARE` (currently `Fraction(3, 4)` → `(6, 2)` at `--jobs 16`) and `--jobs`.
Neither was touched. Candidates for a follow-up task, not applied here:

1. **Re-measure at a wider CPU allotment** (`--jobs 8`, doubling `per_cell_workers` to 16 → a
   `(12, 4)` split) to see whether the area regression is a worker-count effect that scales away,
   or persists — the brief's own fallback path for a CPU-contention failure.
2. **Investigate whether `RACE_FREEFORM_WORKER_SHARE` under-provisions freeform specifically for
   this corpus's mid-tier cells** — `energy-matrix/#2` fails by 40% every round, which is larger
   than pure worker-halving would predict for `_pack`'s bounded-by-wall-clock objective; worth a
   direct A/B (raced freeform at 6 workers vs. standalone freeform at 6 workers, same budget, no
   sequence-pair competing) before concluding the second CP-SAT process is the dominant cause
   rather than the worker cut alone.
3. **The lost geometry-memo warm start is architecturally out of scope for this phase** (spec §4
   non-goals: no cross-process geometry cache) — not a lever, a known, accepted cost; the numbers
   above are consistent with it contributing but do not isolate its share from the worker cut.

No source file, constant, or configuration was changed to produce or in reaction to these
numbers.
