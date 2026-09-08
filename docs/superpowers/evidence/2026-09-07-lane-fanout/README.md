# Producer-lane fan-out — probe evidence, 2026-09-07

Measured in `.claude/worktrees/lane-fanout` on master `a1401518`, with `uv run`
bound to the worktree's own `.venv` (`flab2bp.__file__` verified inside the
worktree). Spec:
`docs/superpowers/specs/2026-09-07-lane-fanout-design.md`.

CPU pressure (`vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print sum/5}'`, mean
runnable processes, 128 cores, fine below 64): **11.4** before the series,
**12.4** after.

`src/` on this branch is unmodified. Every build probe below ran against
`probes/throwaway-probe.patch`, applied and then reverted; it adds three env
switches and one diagnostic and is not a proposal.

| switch | what it does |
|---|---|
| `FLAB2BP_PROBE_NO_FANOUT_GUARD=1` | skip `_fanout_shortfall`'s refusal at both call sites |
| `FLAB2BP_PROBE_LANE_TAIL=1` | size `tail_extension` to the shortfall on every convicted producer, lengthen the emitted out-lane run to match, and let the guard count the tail (lever a) |
| `FLAB2BP_PROBE_PACK_WORK=<f>` | override the fixed `_DETERMINISTIC_PACK_WORK` |
| `FLAB2BP_PROBE_NET_DUMP=1` | print each retained pack's unrouted nets by (item, kind) and (src strip, dst strip) |

## Plan-level probes — no packing, no routing

| file | what it measures |
|---|---|
| `probes/probe_fanout_edges.py`, `probes/fanout-edges-um.csv` | every producer→consumer lane edge in `universe-matrix`'s strip plan (189 rows); exactly three offend, all `antimatter` from `mass-energy-storage#23` |
| `probes/probe_producer_budget.py`, `probes/producer-budget-um.txt` | the offending producer's tile budget (`strips=1 machines=1 pw=10`, TOTAL 10) and the sharding counterfactual for every affordable `n` |
| `probes/guard-fires-corpus.txt` | `_fanout_shortfall` over all 36 corpus specs: fires on 3, all `universe-matrix` |

## Build probes — one at a time, foreground

| id | switches | budget / arm | result |
|---|---|---|---|
| `b0` | none | 30 s, both | exit 3, 12.83 s — the shipped refusal, all six pairs |
| `p1` | no-guard | 30 s, both | exit 3 — refusal moves to the packer: no pack of 57 strips ever produced, 28.7 s of 30 s unspent |
| `p2` | no-guard | 300 s, freeform | exit 3 in **2.58 s**, 299.1 s unspent — the packer wall is not a clock |
| `p3` | no-guard + pack-work 2.0 | 300 s, freeform | exit 3, 4:48 — packs now exist (10 feasible, 1 optimal); refusal moves to routing |
| `p4` | lane-tail + pack-work 2.0 | 300 s, freeform | exit 3, 4:39 — identical outcome to `p3` |
| `p5` | lane-tail + pack-work 2.0 | 120 s, freeform | best pack leaves **1** net unrouted |
| `p6` | no-guard + pack-work 2.0 + dump | 120 s, freeform | `failed_counts=[1, 1, 3, 15, 22, 30, 212]`; the 1 is `titanium-ingot static-access` (40→38). **All twelve `antimatter` nets routed off a 10-tile lane.** |
| `p7` | lane-tail + pack-work 2.0 + dump | 120 s, freeform | identical: same count, same net |
| `p8` | no-guard | 120 s, sequence-pair | exit 3 — all four islands "deadline exhausted before finding an exact layout"; not a fan-out refusal |
| `p9` | no-guard + pack-work 0.5 + dump | 30 s, freeform | 2 packs; best leaves 30, of which `antimatter dynamic-access` ×12 from strip 26 |
| `p10` | lane-tail + pack-work 0.5 + dump | 30 s, freeform | 2 packs; best leaves 27, `antimatter dynamic-access` **×12** — the tail moves none of them |

`p6`/`p7` and `p9`/`p10` are the two A/B pairs that reject lever (a): the lane
tail changes the `antimatter` failure count by zero at both budgets.
