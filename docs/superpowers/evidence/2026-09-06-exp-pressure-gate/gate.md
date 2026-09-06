# Gate: router net order by cut pressure (arm B) vs master `4b51f81f`

**Verdict: FAIL**, on one clause only — the corpus routing-time clause — and
that clause is measured on a stand-in metric whose own run-to-run noise is
demonstrably larger than the effect it is asked to resolve. Every safety clause
passes cleanly: **0 regressions, 0 INVALID, 0 CRASH, overshoot 0.000 s on both
sides, freeform area +0.14 % (limit 1 %), no freeform cell more than 5 % worse in
even one round.** See §8 for the clause-by-clause reading and §9 for the
recommendation (which is: **do not flip the default yet**, but not because the
arm looks bad).

## 1. What was gated

| | |
| --- | --- |
| Candidate | `exp-pressure` at `77ead445`; source commit `3fc11be5` *feat(layout): default-off pressure-aware corridors and net order* |
| Baseline | master merge-base `4b51f81f`, in a throwaway detached worktree, `uv sync`, all three Cython kernels imported (`route_backend` reads `cython` in every large run) |
| Arm under test | **B**, `FLAB2BP_PRESSURE_ORDER=1`, exported for the whole audit process |
| Arm held OFF | **A**, `FLAB2BP_PRESSURE_CORRIDORS`, explicitly `unset` in every driver script — a recorded negative result, not under test |
| Corpus command | `uv run python scripts/audit.py --budget 30 --json <out>` |
| Rounds | B1 C1 B2 C2 B3 C3, strictly sequential, never two audits at once |

### The switch really reaches the workers

`pressure.order_enabled()` is `@cache`d over
`os.environ.get("FLAB2BP_PRESSURE_ORDER") == "1"` (`src/flab2bp/layout/pressure.py:89-92`),
so it is read once per process. `scripts/audit.py:806` fans cells out over a
`ProcessPoolExecutor`, whose start method on this box is **forkserver**. A probe
that mimics that exact shape confirmed inheritance both ways:

```
--- OFF ---  parent start method: forkserver
child: (2623322, None, False, False)      # env, order_enabled(), corridors_enabled()
--- ON  ---  parent start method: forkserver
child: (2623334, '1', True, False)
```

Exporting the variable for the audit process is therefore the correct way to arm
every cell, and arm A stays off in the children as well.

### One thing the README does not say

`src/flab2bp/layout/sequence_solver.py:59` imports `_build_prepared` from
`freeform` and calls it at line 4738. `_build_prepared` is the single call site
of `_net_cut_pressure` (`freeform.py:17646`). **Arm B is therefore not a
freeform-only change**: it reorders nets for the sequence-pair arm too. This
gate found real, reproducible sequence-pair movement in both directions (§4),
which the experiment's eight-cell freeform-only grid could not have seen.

### Load

One other light process shared the box throughout; the dev box is never idle and
its load is I/O wait. `(uptime; vmstat 1 3 | tail -1)` before every round:

| round | load 1/5/15 | vmstat r/b |
| --- | --- | --- |
| baseline round1 | 5.40, 8.86, 7.09 | 2 / 0 |
| candidate round1 | 30.45, 21.59, 12.44 | 4 / 0 |
| baseline round2 | 41.53, 35.08, 19.56 | 1 / 0 |
| candidate round2 | 33.50, 38.34, 24.02 | 1 / 1 |
| baseline round3 | 32.35, 36.86, 26.17 | 0 / 0 |
| candidate round3 | 29.25, 34.91, 27.49 | 2 / 0 |
| large URLs | 26.04, 33.62, 28.66 | 4 / 0 |
| flake re-runs | 3.28, 11.50, 19.95 | 1 / 0 |

Baseline round 1 ran at load 5 and every other round at load 26–42. That
asymmetry matters only for the timing metric (§5), and it is the reason the
same-arm control in §5 is not optional.

## 2. Counts

`audit.py` prints `NOT CLEAN` and exits 1 whenever any cell refuses; that is
expected on this corpus and is not read as a result. Counts and the set of
differing cells are.

| round | baseline | candidate | `NOT CLEAN` banner |
| --- | --- | --- | --- |
| 1 | CLEAN 72 | CLEAN 72 | neither |
| 2 | CLEAN 71, REFUSED 1 | **CLEAN 72** | baseline only |
| 3 | CLEAN 72 | CLEAN 72 | neither |

Master at `4b51f81f` is 72/72 on this corpus — a change from the 65/72 and 70/72
of earlier gates. The candidate is 72/72 in all three rounds.

* **Regressions (CLEAN in all three baseline rounds, non-CLEAN in all three candidate rounds): 0.**
* **INVALID in the candidate: 0. CRASH in the candidate: 0.** Same on the baseline.
* Total build wall, baseline → candidate: 1424.6 → 1410.7 s, 1414.6 → 1418.0 s,
  1422.1 → 1448.2 s. p95 build wall 31.2 → 31.4, 31.4 → 31.8, 31.4 → 32.0 s.

## 3. The one differing cell, and its ruling

| cell | round | baseline | candidate |
| --- | --- | --- | --- |
| `sequence-pair universe-matrix [1/all-products]` | 2 | REFUSED | CLEAN |

The baseline's refusal string: *"all 4 sequence islands refused: island 0:
deadline exhausted before finding an exact layout; island 1: deadline
exhausted…"*. This is the known non-bit-reproducible sequence-pair islands arm.

**Flake re-run** (`--only universe-matrix --strategy sequence-pair --budget 30`,
three runs per tree, one audit at a time):

| tree | run 1 | run 2 | run 3 |
| --- | --- | --- | --- |
| baseline | CLEAN | CLEAN | CLEAN |
| candidate | CLEAN | CLEAN | CLEAN |

**Ruling.** Baseline-side flake, not a candidate effect. The disagreement moves
in the candidate's favour, the candidate is CLEAN in all six observations of the
cell, and the baseline is CLEAN in five of six. It is not counted as an
improvement either — one refusal in six baseline observations of a cell in a
known-noisy arm is noise.

Note that the isolated re-run also shows this cell's baseline **area** is
load-dependent (25168 in the quiet isolated run, 31317 in the full rounds) while
the candidate returns 19019 in all six observations. See §4.

## 4. Area

### Freeform — the arm the gate rule is written about

| round | n | gmean ratio | cells moved | >5 % worse |
| --- | --- | --- | --- | --- |
| 1 | 36 | 1.00136 (**+0.14 %**) | 3 | 0 |
| 2 | 36 | 1.00168 (**+0.17 %**) | 3 | 0 |
| 3 | 36 | 1.00061 (**+0.06 %**) | 3 | 0 |

Same-arm control (one tree, round *i* against round *j*): baseline −0.07 / +0.04
/ −0.03 %, candidate −0.04 / −0.07 / −0.11 %. Freeform area is essentially
deterministic here, so the +0.1 % is a **real** cost rather than noise — and it
is one tenth of the 1 % allowance.

The three cells that move, and all three move by construction of the net order,
not by chance:

| cell | r1 | r2 | r3 |
| --- | --- | --- | --- |
| `super-magnetic-ring [0/no-proliferator]` | 2200 → 2255 (+2.5 %) | 2146 → 2233 (+4.1 %) | 2183 → 2220 (+1.7 %) |
| `super-magnetic-ring [2/output-products]` | 2052 → 2088 (+1.8 %) | 2052 → 2080 (+1.4 %) | 2044 → 2040 (−0.2 %) |
| `information-matrix [2/output-products]` | 5434 → 5472 (+0.70 %) | identical | identical |

**Freeform cells more than 5 % worse in all three rounds: 0.** No freeform cell
is more than 5 % worse in even one round; the worst single observation is
+4.1 %.

### Sequence-pair — better on average, with one real regression

| round | n | gmean ratio | >5 % worse | >5 % better |
| --- | --- | --- | --- | --- |
| 1 | 36 | 0.98429 (**−1.57 %**) | 1 | 2 |
| 2 | 35 | 0.99742 (−0.26 %) | 1 | 1 |
| 3 | 36 | 0.98703 (**−1.30 %**) | 2 | 2 |

Same-arm control: baseline −0.35 / −0.15 / −0.49 %, candidate −0.39 / +0.18 /
−0.21 %. The −1.3 to −1.6 % is outside that band; the −0.26 % of round 2 is not.

Two cells carry it, and both are reproducible:

* **`information-matrix [2/output-products]`: 4905 → 5220, +6.42 %, identical in
  all three rounds on both trees.** This is a genuine, deterministic, >5 % area
  regression. It is on the sequence-pair arm, which the gate's 5 % clause does
  not name, but it is the single worst thing this gate found and it should not
  be buried: arm B costs this cell 315 tiles every time.
* **`universe-matrix [1/all-products]`: 31317 → 19019, −39.3 %** in the two
  baseline rounds that produced a layout, and 25168 → 19019 (−24.4 %) in the
  quiet isolated re-run. The candidate returns 19019 in all six observations;
  the baseline returns three different values. A large, reproducible win.
* `universe-matrix [2/output-products]` reads +4.3 / +2.3 / +15.3 % against a
  baseline that itself ranges 15480–19458 across its own runs. **Inside
  same-cell noise**; no ruling either way.

## 5. Routing time — and why this is the clause that fails

### `route_all_s` does not exist in audit output

The `route_all` tally the experiment README quotes lives only in
`scripts/route_profile.py:251`, installed only by `prof_harness.py`. `audit.py`
emits it on **neither** tree — zero rows out of 432 carry the key. The corpus
stand-in is **`detailed_route_time_s`**, which `freeform.py` measures (line
17666) around exactly the detailed route that contains the `_route_all` call
arm B reorders.

It carries one structural confound: freeform runs to a wall-clock budget, so
total routing seconds mix "each route got cheaper" with "more candidates were
attempted in the same 30 s".

### The numbers, all 36 freeform cells

| round | gmean ratio | faster | slower >10 % | total routing s |
| --- | --- | --- | --- | --- |
| 1 | **0.9630** (−3.70 %) | 19 | 9 | 62.63 → 58.22 (−7.0 %) |
| 2 | **0.9786** (−2.14 %) | 17 | 10 | 58.79 → 56.19 (−4.4 %) |
| 3 | **1.1073** (+10.73 %) | 12 | 22 | 63.80 → 59.58 (−6.6 %) |

Round 3's geomean is above 1.0. Under the rule as written, that is the failure.

### The same-arm control says this metric cannot resolve the effect

Comparing one tree against **itself** across rounds, on the same metric:

| pair | baseline vs baseline | candidate vs candidate |
| --- | --- | --- |
| r1 → r2 | 0.9567 | 0.9722 |
| r2 → r3 | 1.0316 | **1.1672** |
| r1 → r3 | 0.9869 | **1.1348** |

The candidate compared against *itself* moves by +16.7 %. That is larger than the
+10.7 % of the round-3 cross comparison the gate is failing on. The noise floor
of this metric exceeds the effect under test, and the reason is visible in the
per-cell lists: **24–25 of the 36 freeform cells route in under 0.5 s and many
in under 0.05 s**, where a 20 ms scheduling jitter on a box at load 30–40 is a 2×
ratio that the geomean weights exactly as heavily as `universe-matrix`'s 8 s.
Round 3's slower list is full of them — `magnetic-coil[2]` 0.025 → 0.048 s,
`electromagnetic-matrix[0]` 0.035 → 0.059 s, `plastic[0]` 0.032 → 0.054 s.

### Restricting to cells where the number means something

Cells whose **baseline** routing time is at least 0.5 s:

| round | n | gmean ratio |
| --- | --- | --- |
| 1 | 11 | 0.9894 |
| 2 | 11 | 0.9580 |
| 3 | 12 | 0.9745 |

**Below 1.0 in all three rounds.** (Same-arm control at that floor: 0.911–1.091,
so these are still inside noise — but they are consistently on the right side of
it, which the all-cells geomean is not.)

Median-of-the-three-rounds per cell, then geomean — the round-level noise
removed:

* all 36 cells: **1.0019 (+0.19 %)**, 17 faster, 12 slower by more than 10 %
* the 11 cells with a median baseline of at least 0.5 s: **0.9866 (−1.34 %)**, 5 faster

| cell | median baseline s | median candidate s | ratio |
| --- | --- | --- | --- |
| `quantum-chip [2]` | 5.77 | 2.99 | **0.517** |
| `information-matrix [2]` | 12.13 | 7.61 | **0.628** |
| `information-matrix [0]` | 3.53 | 2.51 | **0.710** |
| `super-magnetic-ring [0]` | 5.10 | 3.74 | **0.734** |
| `information-matrix [1]` | 3.85 | 3.85 | 0.999 |
| `universe-matrix [2]` | 8.45 | 8.77 | 1.038 |
| `universe-matrix [1]` | 6.38 | 6.65 | 1.043 |
| `quantum-chip [1]` | 3.07 | 3.63 | 1.182 |
| `universe-matrix [0]` | 5.69 | 7.94 | **1.396** |
| `quantum-chip [0]` | 2.68 | 4.03 | **1.502** |
| `super-magnetic-ring [2]` | 1.42 | 2.70 | **1.905** |

The shape is bimodal and it is the same shape the experiment reported on its
large cells: arm B wins big where it wins (up to 2×) and loses substantially
where it loses (up to 1.9×). It is not a uniform speedup with noise on top.

### Cells slower by more than 10 %, per round

* round 1 (9): `super-magnetic-ring[2]` 1.91×, `super-magnetic-ring[1]` 1.49×,
  `quantum-chip[0]` 1.47×, `quantum-chip[1]` 1.32×, `universe-matrix[0]` 1.26×,
  `plastic[1]` 1.20×, `casimir-crystal[2]` 1.14×, `iron-ingot[0]` 1.14×,
  `universe-matrix[2]` 1.11×
* round 2 (10): `quantum-chip[0]` 1.86×, `electromagnetic-matrix[0]` 1.43×,
  `universe-matrix[0]` 1.40×, `energy-matrix[2]` 1.36×, `iron-ingot[2]` 1.34×,
  `super-magnetic-ring[0]` 1.33×, `quantum-chip[1]` 1.23×,
  `super-magnetic-ring[1]` 1.19×, `processor[2]` 1.16×, `universe-matrix[1]` 1.10×
* round 3 (22): led by `super-magnetic-ring[2]` 4.33×, `magnetic-coil[2]` 1.94×,
  `electromagnetic-matrix[0]` 1.71×, `plastic[0]` 1.70× — **17 of these 22 have
  a baseline under 0.5 s** (rounds 1 and 2: 4 of 9 and 5 of 10).

Only **three** cells are slower by more than 10 % in all three rounds:
`quantum-chip[0]`, `quantum-chip[1]`, `universe-matrix[0]`. Only
`super-magnetic-ring[2]` and `quantum-chip[0]` exceed 1.4× more than once.

### Cells faster

19 (round 1), 17 (round 2), 12 (round 3). Consistent across all three:
`quantum-chip[2]` (0.52 / 0.54 / 0.46), `information-matrix[2]` (0.62 / 0.64 /
0.63), `information-matrix[0]`.

## 6. Wall overshoot

`wall_overshoot_s` is already net of each cell's own allowance, so any positive
value is a cell past budget + grace.

| round | baseline max | candidate max | rows over allowance |
| --- | --- | --- | --- |
| 1 | 0.000 s | 0.000 s | 0 / 0 |
| 2 | 0.000 s | 0.000 s | 0 / 0 |
| 3 | 0.000 s | 0.000 s | 0 / 0 |

Candidate max is not above baseline max in any round. **PASS**, on a tie: no cell
on either tree overshot at all.

## 7. Large URLs

`prof_harness.py`, freeform, budget 60 s, both trees, two replicates each, at
most two runs in flight, never during an audit. Each replicate ran the two trees
concurrently so a load excursion hit both sides of the pair equally.

| cell / policy | rep | side | verdict | wall s | `route_all` s | rip-up rounds | area | belt tiles |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| belt3 / all-products | 1 | base | OK | 44.74 | 16.85 | 21 | 15207 | 6618 |
| | 1 | **cand** | OK | **38.08** | **10.82** | **12** | 15207 | 6691 |
| | 2 | base | OK | 42.67 | 16.18 | 21 | 15207 | 6618 |
| | 2 | **cand** | OK | **36.59** | **10.42** | **12** | 15207 | 6691 |
| belt3 / no-proliferator | 1 | base | REFUSED *packer* | 37.75 | 18.13 | 20 | — | — |
| | 1 | cand | REFUSED *packer* | 40.26 | 22.82 | 18 | — | — |
| | 2 | base | REFUSED *packer* | 38.73 | 19.40 | 20 | — | — |
| | 2 | cand | REFUSED *packer* | 38.47 | 21.24 | 18 | — | — |
| mall / all-products | 1 | base | REFUSED *packer* | 38.03 | 18.57 | 2 | — | — |
| | 1 | **cand** | REFUSED *packer* | **30.21** | **10.44** | 2 | — | — |
| | 2 | base | REFUSED *packer* | 38.02 | 18.38 | 2 | — | — |
| | 2 | **cand** | REFUSED *packer* | **30.75** | **10.50** | 2 | — | — |
| zurl2 / all-products | 1 | base | REFUSED *validator* | 55.82 | 19.10 | 5 | — | — |
| | 1 | **cand** | REFUSED *validator* | 56.62 | **15.13** | **4** | — | — |
| | 2 | base | REFUSED *validator* | 57.85 | 18.57 | 5 | — | — |
| | 2 | **cand** | REFUSED *validator* | 54.83 | **15.37** | **4** | — | — |

**Verdict changes: none.** All four cells return the same verdict in kind on both
trees, in both replicates. `zurl2`'s refusal text differs only in entity and lane
numbering (`lanes [48, 49, 50, 94, 241, 242]` vs `[49, 50, 51, 94, 231, 232]`) —
a different net order renumbers the lanes; the findings, the categories
(`flow.conservation`, `flow.belt_capacity`), and the physics (76 consumers want
`6404/125` items/s of magnetic-coil, `132536/2625` reach them, short by
`1948/2625`) are identical.

This table reproduces the experiment's own grid closely: `belt3/all-products`
`route_all` −36 % with rip-up rounds 21 → 12 at **identical area** and +1.1 %
belt tiles; `mall` −44 %; `zurl2` −19 % with rounds 5 → 4;
`belt3/no-proliferator` **+18 %** and still refusing. Every large-cell number in
the README replicated on this hardware, in both replicates.

## 8. The verdict, clause by clause

| clause | result | |
| --- | --- | --- |
| 0 regressions | 0 | **PASS** |
| INVALID 0 | 0 | **PASS** |
| CRASH 0 | 0 | **PASS** |
| overshoot max not above baseline | 0.000 s vs 0.000 s, all rounds | **PASS** |
| freeform area geomean within 1 % | +0.14 %, +0.17 %, +0.06 % | **PASS** |
| no freeform cell >5 % worse in all three rounds | 0 (none worse in even one round) | **PASS** |
| corpus freeform `route_all` geomean below 1.0 | 0.9630, 0.9786, **1.1073** | **FAIL** |

**Overall: FAIL**, on the last clause alone.

Three honest readings of that clause, all reported rather than one selected:

1. **As written, per round, all 36 cells** — 2 of 3 rounds below 1.0, round 3 at
   1.1073. **Fails.**
2. **Median-of-three-rounds per cell, all 36 cells** — 1.0019. Still above 1.0,
   by 0.19 %. **Fails**, marginally.
3. **Restricted to the 11–12 cells whose routing time is above 0.5 s** — 0.9894,
   0.9580, 0.9745 per round, 0.9866 pooled. **Passes** in all three rounds.

Reading 1 governs, because it is the rule that was set. But the same-arm control
in §5 shows the metric moves by up to 16.7 % when nothing changes at all, so
reading 1 is failing on a number this instrument cannot measure. The aggregate
that *is* stable — total freeform routing seconds — favours the candidate in all
three rounds (−7.0 %, −4.4 %, −6.6 %).

## 9. Recommendation on flipping the default

**Do not flip `FLAB2BP_PRESSURE_ORDER` on by default. Leave the switch
default-off.** The rule ties the recommendation to a PASS, and this is not one.
Two independent reasons make that the right call on the merits as well, not
merely on the letter:

**How many cells are slower, and by how much.** Per round, 9 / 10 / 22 of 36
freeform cells route more than 10 % slower. Across the three-round medians, 12
of 36 are more than 10 % slower. Of those, only three are slower in all three
rounds — `quantum-chip[0]` (1.50×), `quantum-chip[1]` (1.18×) and
`universe-matrix[0]` (1.40×) — plus `super-magnetic-ring[2]` at 1.91× on its
median, which is one of the two largest single regressions in the set. **Are
they within same-arm noise? Partly and not entirely.** The small cells that
dominate the counts are: the candidate's own r2→r3 self-comparison is +16.7 %,
which reproduces most of the round-3 slower list. The four named cells are not:
they route for 1.4–5.8 s, they are slower on their medians rather than on one
round, and 1.4× to 1.9× is outside the ±9 % band the same-arm control shows for
cells above 0.5 s. So the honest statement is: **roughly 12 of 36 cells read
slower, most of that is noise, and about four cells are genuinely slower by
18–90 %.**

**The area regression the freeform clause does not see.** `sequence-pair
information-matrix/output-products` is +6.42 % area, bit-identical in all three
rounds. Arm B reaches the sequence-pair arm through
`sequence_solver.py` → `freeform._build_prepared`, which the experiment's
freeform-only grid never exercised. Flipping the default would ship that cost
site-unseen.

**What the arm is worth, and what would earn the flip.** Arm B is not a bad
change — it is a bimodal one, and its wins are large and reproducible where they
land: `belt3/all-products` at −36 % `route_all` and 21 → 12 rip-up rounds at
identical area, `mall` at −44 %, `quantum-chip[2]` at −48 %,
`information-matrix[2]` at −37 %, and `sequence-pair universe-matrix/all-products`
at −39 % *area*. What it is missing is a rule for **when** to apply it. The
natural next step is not another gate at the same setting but a predicate — apply
the pressure term only where the spec's peak cut pressure clears a threshold, so
`belt3`, `mall` and `quantum-chip[2]` get it and `quantum-chip[0]`,
`universe-matrix[0]` and `super-magnetic-ring[2]` do not — and then gate that.
The reversed-order control in the experiment's §6 already shows the ordering
carries real information on the cells where it wins, so the signal exists to
predicate on.

Until then: **keep it default-off, keep the switch, ship this gate as its
evidence.**

## 10. Files

| file | what |
| --- | --- |
| `run_rounds.sh` | the six paired audit rounds, strictly sequential, load recorded per round |
| `run_large.sh` | the 16 large-URL harness runs, two at a time, both trees paired |
| `run_flake.sh` | the §3 flake re-runs, `--only universe-matrix --strategy sequence-pair` |
| `judge.py` | batch-3's copy plus one added section: freeform routing time (see its docstring for the `route_all_s` / `detailed_route_time_s` substitution) |
| `analyze.py` → `analysis.txt` | every derived number above, including the same-arm controls; **authoritative**, this file quotes it |
| `prof_harness.py` | the harness, copied unchanged from `2026-09-05-scale-profile` |
| `baseline-round{1,2,3}.jsonl` / `.txt`, `candidate-round{1,2,3}.jsonl` / `.txt` | the corpus rounds |
| `judge-round{1,2,3}.txt` | `judge.py` per round |
| `*-load.txt` | `(uptime; vmstat 1 3 \| tail -1)` before every round |
| `runs-large/` | 16 per-run JSON + logs |
| `flake-{base,cand}-um-round{1,2,3}.{jsonl,txt}` | the §3 re-runs |
