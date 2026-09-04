# Gate E1 — seating and ceilings

Spec §7. Judges Tasks 2 to 7 (branch `phase-e-universe-matrix`, tip `ad442ca` at measurement time).

## Base and tip

```
base 60ab5f8339776b6c8020046dc1c04733f9a0c2fa
tip  ad442cac45359a5057ffc4f0de6b4b38bcae9dfb
```

`base` is the branch-point hash recorded on `baseline.md`'s first line (`branch point: 60ab5f8339776b6c8020046dc1c04733f9a0c2fa`), never `origin/master` and never `HEAD~N`.

The two archives' hand-frozen `.git/HEAD`, read back inside each archive to prove `audit._head_commit` stamps the tree that was actually measured:

```
60ab5f8339776b6c8020046dc1c04733f9a0c2fa
ad442cac45359a5057ffc4f0de6b4b38bcae9dfb
```

`.pyx` diff between `base` and `tip`:

```
(empty)
```

No `.pyx` file changed between the branch point and the tip, so copying the candidate's compiled Cython kernels into the baseline archive (rather than rebuilding each arm from its own sources) is sound.

## Round comparisons (`scripts/audit_compare.py`)

```
== round 1
clean 70  refused 2  invalid 0  crashed 0  paired 66  area ratio 1.0009  p95 29.1s
  note CARRIED: freeform universe-matrix/no-proliferator: no packing of 43 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing
  note CARRIED: sequence-pair universe-matrix/no-proliferator: deadline exhausted before finding an exact layout
PASS
== round 2
clean 70  refused 2  invalid 0  crashed 0  paired 66  area ratio 0.9994  p95 28.5s
  note CARRIED: freeform universe-matrix/no-proliferator: no packing of 43 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing
  note CARRIED: sequence-pair universe-matrix/no-proliferator: deadline exhausted before finding an exact layout
PASS
== round 3
clean 70  refused 2  invalid 0  crashed 0  paired 66  area ratio 0.9983  p95 28.4s
  note CARRIED: freeform universe-matrix/no-proliferator: no packing of 43 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing
  note CARRIED: sequence-pair universe-matrix/no-proliferator: deadline exhausted before finding an exact layout
PASS
```

Command per round:
```
uv run python scripts/audit_compare.py "$d/e1-base-round$r.jsonl" "$d/e1-cand-round$r.jsonl" \
  --noise-area 0.013 --p95-seconds 31 --expect-cells 72 --regressions-only \
  --require-clean freeform/universe-matrix/output-products \
  --require-clean freeform/universe-matrix/all-products \
  --require-clean sequence-pair/universe-matrix/output-products \
  --require-clean sequence-pair/universe-matrix/all-products
```

## Clauses `audit_compare` does not carry (Step 5 script, verbatim)

```
round1: clean 70/72  p95 29.07s  max 30.81s  invalid 0  crash 0
    no-proliferator/freeform REFUSED projection_failures=[] detail=no packing of 43 strips could be wired at any candidate height; every pack the sweep produced left nets unrout
round2: clean 70/72  p95 28.45s  max 32.80s  invalid 0  crash 0
    no-proliferator/freeform REFUSED projection_failures=[] detail=no packing of 43 strips could be wired at any candidate height; every pack the sweep produced left nets unrout
round3: clean 70/72  p95 28.36s  max 28.64s  invalid 0  crash 0
    no-proliferator/freeform REFUSED projection_failures=[] detail=no packing of 43 strips could be wired at any candidate height; every pack the sweep produced left nets unrout
```

No `NO STATS` line and no `AREA OUTLIER` line were printed in any round.

## Load

See `e1-load.txt` for `uptime` and `vmstat 1 3` recorded immediately before each of the six round/arm runs. Load ranged up to `load average: 37.63` (round 2, candidate arm). The recorded samples show the load was mostly this audit's own 16 jobs on a 128-core box (the round-1 candidate sample reads `us 88, wa 0, r 131` while the previous arm drained), not I/O wait; no round waited for it to drop.

## Clause verdicts

1. **`universe-matrix/output-products` and `universe-matrix/all-products` CLEAN under both strategies in every round.** PASS — all four `--require-clean` cells held in all three rounds; no `FAIL NOT CLEAN:` line.
2. **Zero REGRESSION lines against the paired baseline round; INVALID 0; CRASH 0.** PASS — no `FAIL REGRESSION:` line in any round; `invalid 0` and `crash 0` in all three rounds (both from `audit_compare` and the Step 5 script).
3. **Paired area ratio over the baseline-clean cells within `--noise-area` 0.013 in every round, and no single cell above 1.13x reproduced in all three rounds.** PASS — area ratios 1.0009, 0.9994, 0.9983, all within [0.987, 1.013]; no `AREA OUTLIER` line printed.
4. **p95 wall at most 31 s; max cell at most 35 s.** PASS — p95 29.07s / 28.45s / 28.36s; max 30.81s / 32.80s / 28.64s.
5. **The `no-proliferator` freeform refusal names routing, not the validator; its `projection_failures` is empty; every REFUSED row carries a non-empty `stats` object.** PASS — `no-proliferator/freeform` detail in every round reads "no packing of 43 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted" (a packer/routing defect, never `game.blueprint_area`, never "rejected by our own validator"); `projection_failures=[]` in every round; no `NO STATS` line printed for any REFUSED row (freeform or sequence-pair) across all three rounds.

**Gate E1: PASS**, all five clauses. Clause 3 did not fail, so the §5.2.1 reversion rule (Step 7) does not apply; Task 5's commit is kept as-is.
