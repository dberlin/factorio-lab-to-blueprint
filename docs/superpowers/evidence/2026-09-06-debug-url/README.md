# Refusals on the user's compressed mall URL — 2026-09-06

The URL a user reported as producing "refusals, packer failures, etc.":

```
https://factoriolab.github.io/dsp/list?z=eJzLt3Uq0zI1MFDLt3VK1jI0MNDSMgSxs5DYkQi2uZaRAVzcScsYSb0RjF2CYDolaxmZwtiVIOUIvYZwThUSuwCJHQFmw3SUI.PCtAwtLS2hMoEgC0GMMCijFEWjIdzIzKRUW2e1otQK23i13Nwi28g6pzrXukC1MltDQwBw4z6V&v=11
```

It decodes to a **titanium-glass 500/min + plane-filter + processor mall** on
belt-3 with no technology set: nine recipes, 116-172 machines, 23-33 strips
depending on the proliferation policy. Full narrative with file:line causes is
in `.superpowers/debug-url-report.md`; this directory holds the measurements.

Branch `debug-url` off `hierarchical-v1` at `8eff46d8`. A gate ran on the same
box throughout, so every run records `uptime` and only one layout build ran at a
time.

## Headline

The URL **does** build — `--strategy best --budget 30` exits 0 with a
sequence-pair layout. What the user is seeing is the verbose report of the four
of six candidate/strategy pairs that refuse alongside it. Six distinct refusal
mechanisms were separated; two were defects and are fixed.

| class | pair | mechanism | outcome |
|---|---|---|---|
| C1 | hierarchical/output-products | `flow.conservation` — composed canvas split into unbalanced components | **FIXED** `b44739e6`, now builds at 9492 tiles |
| C2 | freeform/no-proliferator | all pack solves UNKNOWN inside a fixed 0.02-unit work bound; refused with 29 s of 30 s unspent, message blamed the packer | **misattribution FIXED** `55968b1d`; the work bound itself deliberately untouched |
| C3 | freeform/all-products, /output-products | packs produced, router misses by 1-2 nets; 60 % of the budget goes to exact preparation | capacity limit, reported with numbers |
| C4 | sequence-pair/output-products | all 4 islands: deadline exhausted | budget |
| C5 | hierarchical, budget 15, every policy | funding rule refuses round 1 before any solve — 15 s is the exact knife edge | reported only (gate measures those constants) |
| C5b | hierarchical/no-proliferator, budget 60 | same rule in a later round: 5 blocks x 2 arms = 3 waves, 11.8 s / 3 < 5 s floor | reported only |

## Files

Scripts (all re-runnable, all take the URL as `argv[1]`):

| file | what it does |
|---|---|
| `characterise.py` | spec facts with no layout run: machines, groups, strips, `_logical_strip_plans`, external inputs/outputs, coaters, items above one belt, and the `2026-09-06-exp-features` routing-difficulty vector |
| `diag.py` | runs ONE (policy, strategy) pair and dumps the refusal's full sweep telemetry |
| `diag_hier.py` | wraps `validate.certify`, `contracts._apportion`, `assign_lanes` and `compose` to capture the composed spec, the lane rates, the flows and the compose result |
| `analyse_cut.py` | loads a dumped `(placement, spec)` and prints the bipartite producer→consumer reachability the max-flow reduced to one fraction |
| `funding.py` | the hierarchical funding arithmetic (reserve, jobs, pool width, waves, share) at budgets 15/30/60, with no solve run |

Measurements:

| file | contents |
|---|---|
| `spec.json` | the three candidates in full |
| `funding.json` | seed partition and the round-1 arithmetic per policy per budget |
| `best-30.{out,err}` / `best-30-after.{out,err}` | `--strategy best --budget 30 -v`, before and after |
| `hier-60.{out,err}` / `hier-60-after.{out,err}` | `--strategy hierarchical --budget 60 -v`, before and after |
| `hier-15.{out,err}` | the default-budget refusal the user reported ("doesn't even attempt"), exit 3 in 4.67 s |
| `diag-freeform-*.json` | isolated 30 s freeform runs per policy, with sweep counters |
| `diag-hier-output-products*.json` | the C1 failure and its repair, with lane rates and flows |
| `corpus-um60-{before,after}.json` | `universe-matrix --rate 60` freeform 30 s, same tree, to show the freeform edit is inert where it does not refuse |

## Key numbers

**C1 — why `flow.conservation` fired.** Every physical edge in
`validate._lane_balance` is capped at total demand, so a shortfall is
reachability, never throughput. `analyse_cut.py` on the composed canvas:

```
casimir-crystal    11 producers, 32 consumers, supply 8/3 = demand 8/3
   6 producers (16/11) reach 17 consumers (17/12)  -> surplus
   5 producers (40/33) reach 15 consumers (5/4)    -> SHORT 5/132   == the reported shortfall
microcrystalline   11 producers, 8 consumers
   6 producers (32/11) reach 4 consumers (8/3)     -> surplus
   5 producers (80/33) reach 4 consumers (8/3)     -> SHORT 8/33    == the reported shortfall
```

`contracts._apportion` rated those two tails `4/3` and `4/3` when 6 and 5
machines stand behind them, because a freeform block's boundary belts carry no
`owner_strip` and the whole group fell back to an even split — instrumented
here, **22 of 24 lane groups took that branch**. Weighting by the machines
*docked* on each lane's belt run gives `16/11` and `40/33`, the assignment's
residual becomes a cross-component flow (tail 2213 -> head 923 at 5/132), the
composer wires it, the components merge, and the build certifies.

**C2 — why "no pack was ever produced" was the wrong sentence.**

| probe | pack solves | feasible | unknown | wall of 30 s | verdict |
|---|---|---|---|---|---|
| as shipped | 5 | 0 | **5** | **1.45 s** | no pack ever produced |
| `C_SWEEP_STALE_DRAWS = 10**6` | 15 | 0 | **15** | 2.4 s | same — the sweep runs out of *candidates*, not stale draws |
| `_DETERMINISTIC_PACK_WORK = 0.5` | 4 | **4** | 0 | 30.0 s | packs found; refusal moves to the router |

**C3 — where freeform's 30 s actually goes.**

| policy | strips | attempts | preparation_s | route_s | pack_s | best miss |
|---|---|---|---|---|---|---|
| all-products | 23 | 6 | **18.1 (60 %)** | 11.0 | 0.4 | 2 nets |
| output-products | 25 | 14 | **18.0 (59 %)** | 10.3 | 1.3 | 1 net |

**C5 — hierarchical funding, this spec.** Seed partition is 2 blocks at
`strip_cap 12` (7 strips + 2 strips) for every policy; `arms = (freeform,
sequence-pair)` so `jobs = 4`, `pool_width = 4`, `waves = 1`.

| budget | reserve | remaining | share | round 1 |
|---|---|---|---|---|
| 15 | 10.0 | 5.0 | 5.0 | funded by **exactly 0.0 s** — any wall spent partitioning refuses it |
| 30 | 12.0 | 18.0 | 18.0 | funded |
| 60 | 24.0 | 36.0 | 36.0 | funded, block budget capped at 20.0 |

## Before / after

`--strategy hierarchical --budget 60`:

| candidate | before | after |
|---|---|---|
| all-products | OK 6790 | OK 6790 |
| output-products | **REFUSED (flow.conservation)** | **OK 9492** |
| no-proliferator | REFUSED (funding) | REFUSED (funding) |

`--strategy best --budget 30`: verdicts unchanged (2 OK, 4 refused); the
freeform refusals now name their mechanism.

Freeform regression check, same tree, `universe-matrix --rate 60` freeform 30 s:
**area 31898 and 5347031 expansions, before and after.**
