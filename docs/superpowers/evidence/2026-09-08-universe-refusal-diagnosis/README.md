# Universe: why the earlier 72/72 is now 66/72

## Finding

The earlier indexed-scans result really was **72 CLEAN, including all six universe cells**. The final `f863ee79 → 916ea738` pair only establishes that the last indexed merge added no status losses. It does not establish preservation since the earlier source `1ca2495f`.

The intervening **six-input Matrix Lab geometry correction** changed the problem presented to both layout strategies. Commit `fa5c6be6` moved a flanked output drain beyond sorter reach and imposed one machine per strip when `drain_outermost` is true. The associated single-item input-lane cutover is `0bfff13f`. The old geometry seated mixed input lanes; the new six separate input lanes require the outer drain. Earlier machines' drain columns cross those input belts if multiple labs share that strip.

This is not a new discovery inferred solely from timing: [the correction's original evidence](../2026-09-06-selfloop/task3/README.md) explicitly headlines universe REFUSED, records 15/12 consumer lanes, and preserves uncapped drain-column probes showing 0 crossings for one machine, 3 for two, 6 for three, and 15 for six. The later lane-fanout change removed the conservative producer tap-count refusal, not every routing/access consequence of the expanded topology.

**Confirmed:** the physical correction causes the extra universe strips; the production requirements are unchanged; current routing/validation still cannot complete those cases. **Not established:** that this one commit is the exclusive cause of every current per-policy search outcome. No selective geometry rollback, validator weakening, or full-history performance bisect was used.

## Controlled current-source experiment

Source `bbc8889d`; source code is identical to the final measured `916ea738` (the later commit is evidence/docs only). Exact corpus URL, canonical three candidate policies, exact machine rank, default Tesla tower, portable band, Cython routing backend, 30-second layout budget. Each cell is a fresh guarded subprocess. Probes ran serially; all have the process's 128-CPU affinity. Requested workers change strategy worker allocation and sequence island count, not affinity. Lightweight source/spec inspection also occurred; these are not idle-host timing benchmarks.

| Explicit coater mode | Requested workers | Cells | Result |
|---|---:|---:|---|
| off | 128 | 6 | 6 REFUSED |
| off | 12 | 6 | 6 REFUSED |
| placed | 128 | 6 | 6 REFUSED |

All 18 harness processes exited 0; that means the diagnostic completed, **not** that a factory was emitted. Product status is REFUSED in every JSON. The prior final placed/12 pair and its failure-only serial reruns also refused all six; its original affinity/parallel settings differ and it is not represented as a fourth fresh arm here.

Earlier `1ca2495f` used OFF and 128 workers. Final paired integration used PLACED and 12 workers. Commit `6f1b6ab9` actually changed the default from OFF to PLACED; this was not merely an environment setting. Restoring OFF plus 128 workers on current source does **not** restore the earlier success. OFF is legacy geometry under current validators, not a safe production fallback.

Current PLACED/128 observations:

- Freeform/no-proliferator: 57 strips, two routed packs, best still 3 unrouted nets.
- Freeform/all-products: wired candidates rejected by `prolif.sprayed_cargo_reaches_machines`.
- Freeform/output-products: five lane heads cannot obtain approaches, including information-matrix into universe-matrix#37.
- Sequence-pair/all three policies: all four islands exhaust their deadline. The final 12-worker run used three islands.

The refusal text is retained verbatim; wording such as “a longer clock alone would not have wired this spec” is the solver's report, not a proof that no larger search can ever succeed.

## Exact production/topology comparison

Historical source was extracted read-only with `git archive 1ca2495f src scripts pyproject.toml uv.lock` into a temporary directory. Both sources used the current installed Python dependency environment and their own source/vendored data. This isolates source realization; it does not recreate historical dependency binaries. `flab-universe-topology-probe.py` imports the requested root explicitly and builds the same URL using each source's real candidate builder and `plan_strips`.

Machines are unchanged: **224 / 113 / 193** for no-proliferator / all-products / output-products. Groups, exact rates, input/output requirements, spray domains and required belt edges compare equal after normalizing set ordering. Added metadata is exact rank, no machine moves, default Tesla, and empty self-loop seeds.

At fixed `strip_len=6`:

| Policy | All strips, old → current | Universe recipe strips, old → current |
|---|---:|---:|
| no-proliferator | 57 → 69 | 3 → 15 |
| all-products | 46 → 56 | 2 → 12 |
| output-products | 53 → 63 | 2 → 12 |

**Only universe-matrix#37 changes strip count.** Fixed-length realization is not a replay of the adaptive packer's winning strip configuration: the old CLEAN audit reported 43/42/43 realized strips. A separate fixed-length-12 probe reports 45/42/43 → 58/53/54. Do not conflate these experiments.

## Artifact map and reproduction

- `off-{12,128}-*.{json,log}`, `placed-128-*.{json,log}`: all 18 controlled current cells, including full refusal text and worker/affinity/mode/source metadata.
- `topology-{old,current}.json`: original fixed-length-6 specs and full strip representations.
- `topology-{old,current}-len12.json`: separate fixed-length-12 records.
- Matching topology logs retain process exit and wall time.
- `flab-universe-mode-probe.py`: guarded per-cell runner, uses the normal audit path.
- `flab-universe-topology-probe.py`: final fixed-length-12 variant; use `strip_len=6` for the original topology files.

Example from the repository root:

```sh
uv run python docs/superpowers/evidence/2026-09-08-universe-refusal-diagnosis/flab-universe-mode-probe.py --mode placed --workers 128 --strategy freeform --policy output-products --output /tmp/universe-output-current.json
```

The runner's source label is frozen to this investigation; update it before using another revision. No production source was changed. No old CLEAN result was reclassified as an invalid blueprint without decoding it under the relevant rules. The unresolved work is legal six-input-lab composition/fanout plus the named current spray/access failures, not switching OFF back on.
