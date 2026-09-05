# Speedups round 2, first batch: paired corpus gate and large-URL profile

Gate for the design's §2 first batch — **L2** (compact seed held to a twelfth
of the budget with a 2.5 s floor, `6efd447`) and **L1** (four sequence-pair
islands by default plus the race completion grace, `300116c` + `c3d7229`).

| | |
|---|---|
| baseline | master `a232f0a` (`fix: refuse an unsupported or fully supplied objective with its reason`), throwaway worktree `/tmp/speedups-2-baseline-a232f0a` |
| candidate | `speedups-2` at `c3d7229`, worktree `.claude/worktrees/speedups-2` |
| corpus command | `uv run python scripts/audit.py --budget 30 --json …` (72 cells: 12 URLs x 3 policies x 2 strategies) |
| rounds | three paired rounds per tree, `(uptime; vmstat 1 3 | tail -1)` recorded before each |
| judge | `judge.py` (this directory), extended from `2026-09-05-scale-levers/judge.py` |
| files | `baseline-a232f0a-round{1,2,3}.*`, `candidate-round{1,2,3}.*`, `compare-round{1,2,3}.txt`, `judge-round{1,2,3}.txt` |

Neither banner is the verdict: `scripts/audit.py` prints `NOT CLEAN` whenever
any cell refuses (master itself refuses one), and `scripts/audit_compare.py`
prints `FAIL` for any non-clean candidate row *and* for a p95 wall above its
own 30 s default — both of which fire here for reasons §2 does not call
regressions. The verdict below is read from status counts and the set of cells
whose status differs, per the spec's regression-only rule.

## 1. Three-round counts

| round | baseline CLEAN/REFUSED | candidate CLEAN/REFUSED | CLEAN→non-CLEAN | non-CLEAN→CLEAN | INVALID | CRASH |
|---|---|---|---|---|---|---|
| 1 | 71 / 1 | **72 / 0** | 0 | 1 | 0 | 0 |
| 2 | 71 / 1 | 71 / 1 | 0 | 0 | 0 | 0 |
| 3 | 71 / 1 | **72 / 0** | 0 | 1 | 0 | 0 |

Per arm, every round: freeform `CLEAN 36 → 36`; sequence-pair
`CLEAN 35 → 35 or 36`, `REFUSED 1 → 1 or 0`.

Run wall: baseline 133 s per round, candidate 192-193 s. Islands make more
cells spend their whole budget rather than stopping early, so the corpus run
costs ~45 % more wall for the same 72 cells; total per-cell build wall rises
from ~949 s to ~1406 s across the 72 cells.

## 2. Cells whose status differs, and the ruling on each

One cell, in one direction:

| cell | baseline r1/r2/r3 | candidate r1/r2/r3 | ruling |
|---|---|---|---|
| `sequence-pair universe-matrix [1/all-products]` | REFUSED, REFUSED, REFUSED | **CLEAN**, REFUSED, **CLEAN** | Not a regression — an improvement in two rounds of three. The design predicted exactly this cell (§L1 "a real chance at the borderline `universe-matrix*120` / sequence-pair cell"). |

No cell is CLEAN in the baseline and non-CLEAN in the candidate in any round,
so **no re-run was triggered** — the deadline-flake rule applies to partial
disagreement on a *regression*, and there is none. The one flaky cell flakes in
the candidate's favour: on the rounds it lands, three of its four islands still
refuse and one finds a layout (`islands_refused = 3`), which is the
diversification the lever was bought for.

INVALID 0 and CRASH 0 on both sides, all three rounds.

## 3. Area, per arm

Geometric-mean candidate/baseline area over the cells CLEAN in both:

| round | all | freeform | sequence-pair |
|---|---|---|---|
| 1 | 0.9594 (-4.1 %) | 0.99955 (-0.04 %) | **0.9199 (-8.0 %)** |
| 2 | 0.9602 (-4.0 %) | 1.00036 (+0.04 %) | **0.9205 (-8.0 %)** |
| 3 | 0.9597 (-4.0 %) | 1.00011 (+0.01 %) | **0.9199 (-8.0 %)** |

**The sequence-pair arm is -8.0 % on this corpus, not the -13.6 % the design
measured.** The design's number came from four large cells (um60, qc180,
gm200, um120); the gate corpus is mostly small ones, and 16 of the 36
sequence-pair cells return byte-identical area (the serial branch was already
optimal for them, and island zero is pinned to the serial seed). The -8.0 % is
the honest corpus figure; the -13.6 % remains the honest large-cell figure.

No cell in either arm got *worse*: over the three rounds the largest
candidate/baseline area ratio on any sequence-pair cell is 1.0000.

Freeform is nominally untouched, and the movement it shows is run-to-run
jitter rather than the levers: the only freeform cells that ever move are
`super-magnetic-ring [0]` and `[2]`, and they move between the three
**baseline** rounds too (2183 → 2220 and 2050 → 2052 at the same commit). The
sequence-pair arm was bit-stable round-to-round on the baseline and now moves
on ~2 cells per round pair, which is expected: four spawned islands race on
wall-clock.

Largest movers (mean of three rounds, sequence-pair):

| cell | baseline | candidate | ratio |
|---|---|---|---|
| `information-matrix [0/no-proliferator]` | 8030 | 4560 | 0.568 |
| `energy-matrix [2/output-products]` | 800 | 572 | 0.715 |
| `energy-matrix [0/no-proliferator]` | 616 | 448 | 0.727 |
| `electromagnetic-matrix [0/no-proliferator]` | 627 | 504 | 0.804 |
| `universe-matrix [2/output-products]` | 20485 | 16800 | 0.820 |
| `plastic [2/output-products]` | 936 | 800 | 0.855 |
| `super-magnetic-ring [0/no-proliferator]` | 2604 | 2214-2236 | 0.856 |
| `processor [0/no-proliferator]` | 912 | 783 | 0.859 |

## 4. Overshoot, islands, compact seed, RSS

**Overshoot — clean.** `audit.py` reports `wall_overshoot_s` already net of
each cell's own allowance (`RACE_COMPLETION_GRACE_S` = 6 s for a cell whose
islands resolve above one, the serial grace otherwise), so any positive value
is a cell past budget + grace. **Max `wall_overshoot_s` = 0.000 s, all 72
cells, all three rounds, both trees; zero cells over allowance.** The run
banner's own tail measure agrees: 17 cells finish after their requested search
deadline with a largest completion tail of 1.4-1.6 s (baseline: 1 cell, 0.0 s),
comfortably inside the 6 s grace.

p95 build wall rises 29.1-29.3 s → 31.0-31.2 s. That crosses
`audit_compare.py`'s own `--p95-seconds 30.0` default and is why every
`compare-round*.txt` says FAIL, but it is *not* the §2 overshoot criterion and
is inside the completion grace the batch shipped for exactly this reason.

**Islands — running, at the shipped count.** Candidate sequence-pair rows carry
`islands_requested = 4` and `islands_completed = 4` on every row that produced
a placement (36/36 in rounds 1 and 3, 35/36 in round 2 — the refused cell
emits no placement and so no stats). `islands_refused` is 0 on 33 cells, 1 on
2, and 3 on 1. Baseline rows carry no island stats at all, as expected.

Winners are spread across the pool rather than concentrated on the serial
seed — round 3, `winner_island_id`: `{0: 16, 1: 6, 2: 9, 3: 5}`. Island zero
is pinned to the serial seed, so the 20 cells won by islands 1-3 are wins the
pre-batch code could not reach.

**Compact seed — L2 is visible.** Of the 36 sequence-pair cells, 19-20 report a
compact seed at all (the rest never run one):

| | baseline r1/r2/r3 | candidate r1/r2/r3 |
|---|---|---|
| `optimal` | 13 / 13 / 13 | 13 / 13 / 13 |
| `feasible` | 2 / 2 / 2 | 3 / 2 / 3 |
| `unknown` | 4 / 4 / 4 | 2 / 3 / 3 |
| `cancelled` | 0 / 0 / 0 | **2 / 1 / 1** |
| max `compact_seed_wall_time_s` | 8.26 / 9.03 / 8.68 s | **2.62 / 2.54 / 2.63 s** |
| mean `compact_seed_wall_time_s` | 1.56 / 1.59 / 1.52 s | 0.91 / 0.78 / 0.88 s |

The cap moved from budget/3 (10 s at 30 s) to max(budget/12, 2.5 s) = 2.5 s,
and the measured maximum tracks it to within settle time. One or two cells per
round now report `cancelled` — the seed was cut off at the new wall — and
those are the cells that were spending 8-9 s on it; the 13 `optimal` seeds are
unaffected, which is the "identical area, more search" the lever claimed.

**Peak RSS — NOT RECORDED; §2's fourth gate item is unmet by the harness.**
No `*rss*` key exists in either tree's JSONL. `strategy_race._peak_rss_kib`
measures raced *children*, and the explicit `sequence-pair` arm `audit.py`
runs is not raced — it spawns islands through `sequence_islands`, which emits
`islands_requested/completed/refused`, `island_result_reserve_s` and
`winner_island_*` but no RSS. Recording it needs a change to
`sequence_islands._island_stats`; nothing here fakes a number. Judged only by
what is observable: four island processes per cell at `--jobs 8` did not
disturb a 128-core box carrying an unrelated load average of 5-30 during these
runs, and no cell was lost to the OOM killer in six full corpus runs.

## 5. Large URLs, before and after

Three large FactorioLab URLs (`large-urls/urls.txt`), each at two candidate
policies, both strategies and budgets 60 s and 100 s — 24 rows, paired
one-for-one with `large-urls/before.jsonl` (recorded from master `a232f0a`
with the same harness).

Harness note, and the one deviation in this task:
`docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py` reaches
the solver through `route_profile._strategy`, which builds
`SequencePairLayout(band_policy=…)` **with no island argument** — i.e. always
one island. Islands become the default inside
`pipeline.resolve_sequence_islands`, which that path never calls, so an
unmodified harness would have measured L2 alone and reported it as the batch.
The harness therefore gained an optional `--islands N` flag (default: absent,
old behaviour, so `before.jsonl` stays reproducible), and every after-run of
the sequence-pair arm passes `--islands 4` — the same count
`resolve_sequence_islands` returns for a single-candidate 16-worker build and
the same count `scripts/audit.py` runs. The before rows are one island because
one island was the shipped shape at `a232f0a`. Freeform is untouched in both.

`machines` per label/policy: belt3 280 / 537, zurl2 436 / 868, mall 449 / 935
(all-products / no-proliferator).

| label | policy | strategy | budget | before | after |
|---|---|---|---|---|---|
| belt3 | all-products | freeform | 60 | OK 14430, 47.4 s | OK 14430, 44.6 s |
| belt3 | all-products | freeform | 100 | OK 14430, 46.4 s | OK 14430, 45.1 s |
| belt3 | all-products | sequence-pair | 60 | OK 14256, 50.5 s | **OK 14062 (-1.4 %)**, 53.2 s |
| belt3 | all-products | sequence-pair | 100 | OK 12862, 85.7 s | **OK 12408 (-3.5 %)**, 90.7 s |
| belt3 | no-proliferator | freeform | 60 / 100 | REFUSED (26 strips, none wired) | REFUSED, same reason |
| belt3 | no-proliferator | sequence-pair | 60 / 100 | REFUSED (deadline exhausted) | REFUSED (all 4 islands refused) |
| zurl2 | all-products | freeform | 60 / 100 | REFUSED (validator: `flow.belt_capacity`) | REFUSED, same reason |
| zurl2 | all-products | sequence-pair | 60 | REFUSED (deadline exhausted) | **OK — area 40905, 49.7 s, island 1 won, 2 of 4 islands refused** |
| zurl2 | all-products | sequence-pair | 100 | REFUSED (deadline exhausted) | **OK — area 42255, 88.1 s, island 2 won, 3 of 4 islands refused** |
| zurl2 | no-proliferator | freeform | 60 / 100 | REFUSED (no pack of 50 strips) | REFUSED, same reason |
| zurl2 | no-proliferator | sequence-pair | 60 / 100 | REFUSED (deadline exhausted) | REFUSED (all 4 islands refused) |
| mall | all-products | freeform | 60 / 100 | REFUSED (46 strips, none wired) | REFUSED, same reason |
| mall | all-products | sequence-pair | 60 / 100 | REFUSED (deadline exhausted) | REFUSED (all 4 islands refused) |
| mall | no-proliferator | freeform | 60 / 100 | REFUSED (no pack of 54 strips, 0.6 s) | REFUSED, same reason |
| mall | no-proliferator | sequence-pair | 60 / 100 | REFUSED (deadline exhausted) | REFUSED (all 4 islands refused) |

**Two rows changed verdict, both REFUSED → OK: `zurl2` / `all-products` /
`sequence-pair` at both budgets** — a 436-machine, 40-strip build that master
could not lay out at either budget now lays out at both. That is currency (c),
a refusal becoming a success, on a URL the corpus does not contain.

No row went the other way. Every freeform row keeps its verdict and its area
to the digit; the one textual difference is the finding count inside
`zurl2/all-products/freeform/100`'s refusal message, which is the same refusal.

Two further observations, stated because they are what the data says:

* **More budget is not monotonically better**, again. `zurl2` returns 40905 at
  60 s and 42255 at 100 s — the 100 s run is 3.3 % *worse*. The design's §0.3
  finding survives the batch, and the compact seed is not the cause: at 60 s
  the seed spent 4.52 s of its 5.0 s cap and at 100 s it spent 5.22 s of its
  8.33 s cap, both `unknown`.
* **The remaining refusals are the freeform packer and genuine deadline
  exhaustion, not the levers.** Both `mall` policies and `zurl2`
  /`no-proliferator` still refuse in both arms; the sequence-pair refusals now
  read "all 4 sequence islands refused" where they read "deadline exhausted"
  before, which is the same outcome reported at island granularity. The two
  `mall`/`no-proliferator` and `zurl2`/`no-proliferator` freeform rows refuse
  in 0.5-0.8 s without ever producing a pack, which is a spec-shape problem
  (50-54 strips), not a search-time one.

## 6. Verdict

**PASS on §2's regression-only gate: across three paired 30 s rounds
(a232f0a → c3d7229) zero cells went CLEAN → non-CLEAN, INVALID 0, CRASH 0, max
`wall_overshoot_s` 0.000 s, `sequence-pair universe-matrix/all-products` went
REFUSED → CLEAN in two rounds of three, sequence-pair area is -8.0 % and
freeform is unchanged — with one gate item unmet: peak RSS is not recorded
anywhere for the non-raced sequence-pair arm, so §2's item 3 rests on
inference rather than measurement.**

Costs the batch does incur, none of them a §2 failure but all of them real:
a corpus round takes 192 s instead of 133 s, p95 per-cell wall goes 29.2 s →
31.1 s (inside the 6 s grace, outside `audit_compare`'s own 30 s p95 default,
which is why its banner reads FAIL), and the sequence-pair arm stops being
bit-reproducible round to round — four spawned islands race on wall-clock, so
about two cells per round pair land on a different island's answer. If
reproducibility matters more than 8 % of area somewhere, `islands=1` is still
bit-identical to `a232f0a`.
