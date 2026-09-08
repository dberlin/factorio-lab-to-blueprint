# Final fix round — evidence (2026-09-07)

The single fix wave after the whole-branch review's **SHIP WITH FIXES** verdict.
Nothing here changes what a shipped blueprint looks like; it is two record
corrections backed by measurement, plus the bisect that attributed the branch's
last unexplained refusal.

Reported URL ("AMM-URL") is the one in `../README.md`, verified byte-for-byte by
`probe_amm_strips.py`'s own constant.

Machine: 128 cores. CPU pressure is `vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END
{print sum/5}'` (mean runnable procs), never load average. Below 64 is fine.

## Spec §9 R2 — a non-corpus spec DOES move (plan probe, no build)

`probe_amm_strips.py` runs `generate_strip_families` and `plan_strips` only. It
reads every branch-only field through `getattr` with the master default, so the
identical file runs on both trees.

| file | tree |
|---|---|
| `amm-strips-master.txt` | master `0d88d247` (`.claude/worktrees/selfloop-baseline`) |
| `amm-strips-branch.txt` | this branch |
| `amm-strips-diff.txt` | `diff -u` of the two |
| `cpu-pressure-probe-master.txt` | 7.4 before / 34.2 after |
| `cpu-pressure-probe-branch.txt` | 8.6 before / 7.4 after |

`advanced-mining-machine`: master plans **1 non-flanked strip of 2 machines**
(`box_height` 7, `machine_cap` 18/21/21); the branch plans **2 flanked strips of
1 machine each**, `drain_outermost=True`, `machine_cap=1`, in **all three**
candidate policies. Whole-spec `total_box_height`: `no-proliferator` 148 → 161,
`all-products` 141 → 154, `output-products` 149 → 162. Master plans zero flanked
strips on this URL; the branch plans two.

The point is not the +13. It is that flanked-ness is an OUTPUT of R1's ban, not
a fixed input, so counting flanked plans on master counts the wrong thing.

## Spec §9 R9 — the bisect, two builds, one at a time

`/usr/bin/time -v uv run flab2bp "<AMM-URL>" --budget 30 -v -o bp-bisect-<sha>.txt`,
each in its own `git worktree add --detach` (both removed afterwards), each
`uv sync`'d and verified to resolve `flab2bp.__file__` inside itself.

| commit | what it is | wall | CPU | pressure before/after | `freeform/all-products` | pairs built |
|---|---|---|---|---|---|---|
| `af8d04c9` | Task 1: validator check only, **no seat filter** | 2:28.47 | 359% | 4.6 / 11.6 | REFUSED, `prolif.coater_rides_one_run` | 2 of 6 |
| `46cac580` | Task 2: seat filter added, addon-area narrowed to runs | 2:26.80 | 355% | 10.2 / 6 | REFUSED, `prolif.coater_rides_one_run` | 2 of 6 |

Both refuse the same four pairs on the same check and build the same two.

**Verdict: "the validator convicts what the emitter always made."** The cell was
already lost at `af8d04c9`, before the seat filter existed. The `geom.collide
(31, 809)` seen at branch head is a re-symptomisation of an already-refusing
pair, not a new loss.

Logs: `build-bisect-af8d04c9.log`, `build-bisect-46cac580.log`, and the
`cpu-pressure-bisect-*.txt` beside each.

## The M-2 / L103 test

`red-coater-two-runs.txt` — exit **1**, on the pre-fix message, showing the
contradiction verbatim:

```
coater 6 rides a belt merge under its body: belt(s) [] on its body tiles have two
or more predecessors, and its body tiles carry 2 distinct belt runs; ...
```

`green-coater-two-runs.txt` — exit **0**, 24 coater tests.

`pytest-validate-web.txt` — exit **0**, full `tests/layout/test_validate.py` plus
`tests/web`.
