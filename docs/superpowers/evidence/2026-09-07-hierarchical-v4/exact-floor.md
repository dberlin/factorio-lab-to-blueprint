# Task 6: the sequence-pair exact-preparation floor

2026-09-07, hierarchical-v4 Task 6. Worktree
`/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/hierarchical-v4`,
branch `hierarchical-v4`.

```
$ uv run python -c "import flab2bp; print(flab2bp.__file__)"
/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/hierarchical-v4/src/flab2bp/__init__.py
```

## Real signatures vs the brief's assumed shapes

Every name the brief's `floor_probe.py` sketch assumed was checked against the real tree
with `Read` + worktree-scoped `rg` (Serena's active project was the MAIN CHECKOUT, per
`mcp__serena__get_current_config`, not this worktree, and `activate_project` was not
called, per the constraints). Five of the six assumed shapes were wrong:

| Assumed | Real |
|---|---|
| `flab2bp.pipeline.spec_for(url, policy)` | Does not exist. The real production call (used verbatim by `docs/superpowers/evidence/2026-09-06-exp-trunk/spread.py`'s own `spec_for` helper, and internally by `pipeline.build`) is `build_candidates(load_vendored(), parse_url(url), candidate_policies=(policy,)).candidates[0]`, from `flab2bp.rates.candidates` / `flab2bp.lab.data` / `flab2bp.lab.url`. |
| `flab2bp.layout.sequence_pair.SequencePairLayout` | `sequence_pair.py` holds lower-level pieces (`SequencePair`, `GapProfile`, ...), not the layout backend. `SequencePairLayout` actually lives in `flab2bp.layout.sequence_solver`. |
| `SequencePairLayout(band_policy=..., time_budget_s=...)` | `SequencePairLayout.__init__` has no `time_budget_s` parameter. The budget is a `lay_out(spec, *, time_budget_s=..., absolute_deadline=None)` argument, exactly as `hierarchy.strategy._block_layout` / `_solve_block` call it. `_block_layout`'s sequence-pair construction also passes `islands=1`; the probe matches this. |
| `BandPolicy.portable()` | No such classmethod. The real call, used verbatim by `hierarchy.strategy._block_layout`, is `BandPolicy.parse("portable")`. |
| `from flab2bp.spec import CandidatePolicy` | `flab2bp.spec` holds `BuildSpec` et al., not the policy enum. `CandidatePolicy` lives in `flab2bp.rates.candidates`. |
| `unit.recipe_id` | `Unit`'s recipe attribute is `.recipe`. |

`pipeline.spec_for`, `Partition.blocks: list[list[Unit]]`, and `sub_spec(spec, block, index)`
were confirmed correct as stated (`initial_partition`, `sub_spec` both live in
`flab2bp.layout.hierarchy.partition`, `Partition.blocks` is `list[list[Unit]]`).
`initial_partition(spec, *, strip_cap: int = STRIP_CAP_DEFAULT)` was called with no
`strip_cap` override, matching the strategy's own default.

The finished `floor_probe.py` (in this directory) calls the real production path:
`build_candidates(...).candidates[0]` -> `initial_partition(spec)` ->
`sub_spec(spec, block, index)` -> `SequencePairLayout(band_policy=BandPolicy.parse("portable"),
islands=1).lay_out(sub, time_budget_s=budget_s)` -- the same construction
`hierarchy.strategy._block_layout("sequence-pair", ...)` uses, minus the pool.

## Block selection: index-to-recipe mapping, asserted against the real (pre-recut) partition

`docs/superpowers/evidence/2026-09-07-hierarchical-v3/large-mall-no-proliferator-b60-r1.json`
names 31 refusing blocks by *post-recut* index (`refusals[0]`, parsed with a `block (\d+)
\(([^)]+)\): REFUSED` regex): 9 `magnet`, 7 `iron-ingot`, 2 `copper-ingot`, 2
`magnetic-coil`, 6 `electric-motor`, 2 `electromagnetic-turbine`, 2 `super-magnetic-ring`,
1 multi-recipe (`circuit-board, sorter-1, sorter-2`) -- 31 total, matching the brief.

**Those indices are NOT `initial_partition(spec).blocks` indices.** `hierarchy.strategy.
_block_refusal` numbers blocks by position in `entries`, a list that starts as one entry
per `partition.blocks` element but is then split in place by up to `MAX_RESPLIT_ATTEMPTS`
re-cut rounds (`_next_cut` / `_recut`) before any refusal is recorded -- v3's own gate
text says "out of re-cut round(s) after 2 of 2". `floor_probe.py` deliberately does not
run that recut loop (the brief: "It must not run a whole build"), so it can only reach
`initial_partition`'s *pre-recut* blocks. Trusting the v3 refusal text's block numbers
positionally would silently probe the wrong sub-specs.

So each index below was found by listing every one of `initial_partition(spec).blocks`
(24 total, for `mall/no-proliferator`) and asserting its recipe set, not by reusing v3's
numbers:

| index | recipes (asserted) | picked as | matches v3 shape |
|---|---|---|---|
| 1 | `magnet` | one `magnet` | yes, exact match |
| 4 | `iron-ingot` | one `iron-ingot` | yes, exact match |
| 17 | `electric-motor` | one `electric-motor` | yes, exact match |
| 20 | `super-magnetic-ring` | one `super-magnetic-ring` | yes, exact match |
| 21 | `circuit-board, processor, sorter-1, sorter-2, sorter-3` | "the multi-recipe one" | **superset**, not exact: v3's post-recut multi-recipe block was `circuit-board, sorter-1, sorter-2` (3 recipes); the closest pre-recut block containing all three is block 21, which also carries `processor` and `sorter-3` because it had not yet been split. No pre-recut block in this partition has exactly `{circuit-board, sorter-1, sorter-2}` -- that shape is a recut PRODUCT, not a `initial_partition` block, so it cannot exist in a probe that skips recuts by design. |

Single-recipe blocks 1, 2, 3 are all `magnet`; 4, 5, 6 are all `iron-ingot`; 17, 18 are
`electric-motor`; 20 is the only `super-magnetic-ring`. The first index of each shape was
used. This confirms the "shapes that carry 24 of the 31" claim for the four single-recipe
shapes (9+7+6+2=24) while being explicit that the fifth pick is a superset of the v3 shape,
not an identical re-run of it.

## Step 3: the 25-cell block sweep (five blocks x budgets 5.0/7.5/10.0/15.0/20.0s)

URL: `https://factoriolab.github.io/dsp/list?z=eJwlx7uOwjAUhOG3OcUUKAYWhWKaY4mgVRaBEBAogRQWayVyuKTys6PEzf.NNNzAZHkmDdcnzBbD0ArTXBp-YH6kod0PtyZ-hxQSqHsgk8Bd4pLQG2Ak0Fbp223yL1Em1sfkMpEPeFoY8TyPdWPLsd3YFkZc3VMn4q41rbjuybmEuucWJ5xxxwMv9FhAN9ADtILeoI-o.9Ap7CraQrwP7GIbXSzFtx0LedOYL5cQRDE_&v=11`
(`large-mall`, `NO_PROLIFERATOR`), the same URL v3's gate used. `-load.txt` recorded once
per block row, immediately before that row's first run (five rows), per the constraints'
row-level relaxation.

Loads (`runnable_5s_mean`, vmstat, under 64 on all rows):

| block | load |
|---|---|
| 1 | 17.2 |
| 4 | 8.2 |
| 17 | 35.4 |
| 20 | 49.6 |
| 21 | 44.8 |

Full grid (`floor-b{block}-{budget}.json` / `.log` per cell):

| block | recipes | budget_s | ok | wall_s | verdict |
|---|---|---|---|---|---|
| 1 | magnet | 5.0 | False | 2.931 | `...after 5s: expansion budget exhausted before finding an exact layout...` |
| 1 | magnet | 7.5 | False | 3.424 | `...after 7.5s: expansion budget exhausted before finding an exact layout...` |
| 1 | magnet | 10.0 | False | 3.752 | `...after 10s: expansion budget exhausted before finding an exact layout...` |
| 1 | magnet | 15.0 | False | 3.405 | `...after 15s: expansion budget exhausted before finding an exact layout...` |
| 1 | magnet | 20.0 | False | 3.495 | `...after 20s: expansion budget exhausted before finding an exact layout...` |
| 4 | iron-ingot | 5.0 | False | 2.899 | `...after 5s: expansion budget exhausted before finding an exact layout...` |
| 4 | iron-ingot | 7.5 | False | 3.649 | `...after 7.5s: expansion budget exhausted before finding an exact layout...` |
| 4 | iron-ingot | 10.0 | False | 3.633 | `...after 10s: expansion budget exhausted before finding an exact layout...` |
| 4 | iron-ingot | 15.0 | False | 3.689 | `...after 15s: expansion budget exhausted before finding an exact layout...` |
| 4 | iron-ingot | 20.0 | False | 3.611 | `...after 20s: expansion budget exhausted before finding an exact layout...` |
| 17 | electric-motor | 5.0 | False | 1.989 | `...after 5s: expansion budget exhausted before finding an exact layout...` |
| 17 | electric-motor | 7.5 | False | 2.005 | `...after 7.5s: expansion budget exhausted before finding an exact layout...` |
| 17 | electric-motor | 10.0 | False | 2.304 | `...after 10s: expansion budget exhausted before finding an exact layout...` |
| 17 | electric-motor | 15.0 | False | 2.487 | `...after 15s: expansion budget exhausted before finding an exact layout...` |
| 17 | electric-motor | 20.0 | False | 2.544 | `...after 20s: expansion budget exhausted before finding an exact layout...` |
| 20 | super-magnetic-ring | 5.0 | False | 3.848 | `...after 5s: deadline exhausted before finding an exact layout...` |
| 20 | super-magnetic-ring | 7.5 | False | 6.503 | `...after 7.5s: deadline exhausted before finding an exact layout...` |
| 20 | super-magnetic-ring | 10.0 | False | 8.711 | `...after 10s: deadline exhausted before finding an exact layout...` |
| 20 | super-magnetic-ring | 15.0 | False | 13.31 | `...after 15s: deadline exhausted before finding an exact layout...` |
| 20 | super-magnetic-ring | 20.0 | False | 18.338 | `...after 20s: deadline exhausted before finding an exact layout...` |
| 21 | circuit-board, processor, sorter-1, sorter-2, sorter-3 | 5.0 | False | 4.508 | `...after 5s: deadline exhausted before finding an exact layout; exact validation failures: flow.conservation.` |
| 21 | circuit-board, processor, sorter-1, sorter-2, sorter-3 | 7.5 | False | 7.06 | `...after 7.5s: deadline exhausted before finding an exact layout; exact validation failures: flow.conservation.` |
| 21 | circuit-board, processor, sorter-1, sorter-2, sorter-3 | 10.0 | False | 8.68 | `...after 10s: deadline exhausted before finding an exact layout; exact validation failures: flow.conservation, geom.collide; no legal DSP latitude band/orientation accepts the final placement...` |
| 21 | circuit-board, processor, sorter-1, sorter-2, sorter-3 | 15.0 | False | 13.034 | `...after 15s: deadline exhausted before finding an exact layout; exact validation failures: flow.conservation, geom.collide; no legal DSP latitude band/orientation accepts the final placement...` |
| 21 | circuit-board, processor, sorter-1, sorter-2, sorter-3 | 20.0 | False | 17.728 | `...after 20s: deadline exhausted before finding an exact layout; exact validation failures: flow.conservation, geom.collide; no legal DSP latitude band/orientation accepts the final placement...` |

Full verdict text and every field are in the per-cell `floor-b{block}-{budget}.json` files
in this directory (25 files) plus their `.log` files. Two distinct refusal reasons appear:
blocks 1/4/17 refuse via the search's own **expansion budget** (wall stays ~2-4s regardless
of the budget given, well under every swept value -- the search exhausted its candidate
space, not the clock), while blocks 20/21 refuse via the **wall-clock deadline** (wall grows
with the swept budget, up to 18.3s at 20.0s for block 20 and 17.7s at 20.0s for block 21) --
both are real "sequence-pair could not certify an exact layout" outcomes for a coater-free
block, and both count as refusals for the constant's rule.

**Every one of the 25 cells refused.** No swept budget produced an exact layout for even
one block, let alone all five.

### Deriving `SEQUENCE_PAIR_EXACT_FLOOR_S`

Rule (brief Step 4): *the smallest swept budget at which every one of the five blocks
produced an exact layout; if no swept budget does, set the constant to
`BLOCK_BUDGET_MAX_S + 1.0 = 21.0` and say that no per-block budget the funding rule can
produce is above the floor.*

Applied: no swept budget (5.0, 7.5, 10.0, 15.0, or 20.0s -- the full
`[BLOCK_BUDGET_MIN_S, BLOCK_BUDGET_MAX_S]` range the funding rule can ever hand a block)
got all five blocks to an exact layout; in fact none got even one. So:

**`SEQUENCE_PAIR_EXACT_FLOOR_S = BLOCK_BUDGET_MAX_S + 1.0 = 21.0`.**

**No per-block budget the funding rule can produce is above this floor.** Every legal
per-block budget `hierarchy.strategy` can compute is `<= BLOCK_BUDGET_MAX_S = 20.0 <
21.0 = SEQUENCE_PAIR_EXACT_FLOOR_S`. This is a stronger finding than a mid-range floor
would have been: it means Task 7's "abstain from sequence-pair below the floor" rule is
**unconditional** for a coater-free mall block -- there is no budget size at which handing
such a block to `sequence-pair` alone, on this evidence, is expected to produce an exact
layout. (This measurement covers five specific block shapes at one URL; it is evidence
for the rule, not a proof that no coater-free block anywhere can ever clear 20.0s -- the
same caveat the `UNCOVERED_*` thresholds' own docstring carries.)

## Step 5: the constant

Shipped in `src/flab2bp/layout/hierarchy/dispatch.py`, after `UNCOVERED_STRIPS = 85`:

```python
SEQUENCE_PAIR_EXACT_FLOOR_S = 21.0
```

with the doc-comment the brief specifies (date, mechanism, and the "measurement, not a
tuning knob" warning), updated with the actual 2026-09-07 measurement summary, and added
to `__all__`. Test:
`tests/layout/hierarchy/test_dispatch.py::test_the_exact_preparation_floor_is_inside_the_block_budget_range_or_above_it`.

## Step 6: the red deadline test's ceiling and new budget

Test: `tests/test_pipeline.py::test_all_products_sequence_pair_honours_the_exact_layout_deadline`.
URL: `DEADLINE_REGRESSION_URL` (`tests/test_pipeline.py:53`) =
`https://factoriolab.github.io/dsp/flow?z=eJzLt923SMjQwUMu3dQrWMgPTzlrGILpEywgi7qRlaGZgoKVlqJZvaw4ShLLDQBrB7MykVFsntdzcItvIOqc617pAtdyCYls3tTJbQ0MAjnsZAA__&v=11`.

Baseline confirmation, at the pre-existing `budget = 1.5`: `1 failed` -- `Failed: DID NOT
RAISE NoValidLayout` (load `runnable_5s_mean=21.2`, `deadline-baseline-1.5-load.txt`) --
confirms the test was genuinely red on master before this task's edit, for the reason its
own comment already named (preparation got faster; the build now completes inside 1.5s).

Swept budgets 0.4, 0.6, 0.8, 1.0, 1.25, 1.5s, three runs each, by editing the `budget =`
line and running:
```
uv run pytest tests/test_pipeline.py::test_all_products_sequence_pair_honours_the_exact_layout_deadline -x
```
Full 18-run grid (`deadline-{budget}-run{n}.log` / `-load.txt` per run):

| budget_s | run | pytest result | reason | wall_s | load (runnable_5s_mean) |
|---|---|---|---|---|---|
| 0.4 | 1 | FAIL | refused (deadline exhausted) but NOT inside exact prep: `preparation_deadline_fires==0` | 0.67 | 10.8 |
| 0.4 | 2 | FAIL | refused (deadline exhausted) but NOT inside exact prep: `preparation_deadline_fires==0` | 0.58 | 10.8 |
| 0.4 | 3 | FAIL | refused (deadline exhausted) but NOT inside exact prep: `preparation_deadline_fires==0` | 0.84 | 17.4 |
| 0.6 | 1 | FAIL | refused (deadline exhausted) but NOT inside exact prep: `preparation_deadline_fires==0` | 1.07 | 14 |
| 0.6 | 2 | PASS | raised deadline-exhausted inside exact prep (correct refusal) | 0.78 | 21 |
| 0.6 | 3 | PASS | raised deadline-exhausted inside exact prep (correct refusal) | 0.79 | 11.8 |
| 0.8 | 1 | PASS | raised deadline-exhausted inside exact prep (correct refusal) | 1.23 | 7.6 |
| 0.8 | 2 | PASS | raised deadline-exhausted inside exact prep (correct refusal) | 0.97 | 9.2 |
| 0.8 | 3 | PASS | raised deadline-exhausted inside exact prep (correct refusal) | 0.96 | 9 |
| 1.0 | 1 | PASS | raised deadline-exhausted inside exact prep (correct refusal) | 1.40 | 11.2 |
| 1.0 | 2 | PASS | raised deadline-exhausted inside exact prep (correct refusal) | 1.17 | 7.6 |
| 1.0 | 3 | PASS | raised deadline-exhausted inside exact prep (correct refusal) | 1.18 | 10.2 |
| 1.25 | 1 | FAIL | refused (deadline exhausted) but NOT inside exact prep: `preparation_deadline_fires==0` | 1.69 | 9.2 |
| 1.25 | 2 | FAIL | refused (deadline exhausted) but NOT inside exact prep: `preparation_deadline_fires==0` | 1.59 | 8.2 |
| 1.25 | 3 | FAIL | `DID NOT RAISE NoValidLayout` (build SUCCEEDED) | 2.38 | 15.4 |
| 1.5 | 1 | FAIL | `DID NOT RAISE NoValidLayout` (build SUCCEEDED) | 2.67 | 4 |
| 1.5 | 2 | FAIL | `DID NOT RAISE NoValidLayout` (build SUCCEEDED) | 2.61 | 11.4 |
| 1.5 | 3 | PASS | raised deadline-exhausted inside exact prep (correct refusal) | 1.72 | 10.6 |

Note the behaviour is not monotonic in budget: at 0.4s and 1.25s some/all runs fail via a
DIFFERENT mechanism than at 1.5s (0.4s: the deadline fires before exact preparation is even
reached, so `preparation_deadline_fires` stays 0 and the test's own guard --
`assert preparation_deadline_fires > 0` -- catches that as a failure, correctly, since that
is not the code path 0d2a69b guards; 1.25s/1.5s: the build sometimes completes before the
deadline fires at all). This is real measured system noise (candidate ordering, scheduler
timing under box load), not a bug in the probe.

### Deriving the ceiling and the new budget

Rule (brief Step 6): *the new ceiling is the smallest swept budget at which any of the
three runs SUCCEEDED (i.e. the build completed -- `DID NOT RAISE NoValidLayout`); the new
budget is the largest swept value strictly below it that refused 3 of 3.*

Applied:
- Smallest swept budget with any run SUCCEEDING (build completed, "DID NOT RAISE"): **1.25s**
  (0.4s, 0.6s, 0.8s, 1.0s never once succeeded across their 3 runs each). **Ceiling = 1.25s.**
- Swept values strictly below 1.25s: 0.4, 0.6, 0.8, 1.0. Of these, the ones that refused 3 of
  3 **and** where the refusal is the correct one under test (inside exact preparation, so the
  whole test -- including `preparation_deadline_fires > 0` -- passes 3/3) are 0.8s and 1.0s.
  0.4s refused 3/3 but NOT the correct way (`preparation_deadline_fires==0` every time -- the
  deadline fires before reaching exact preparation at that budget, so the test itself would
  stay red at 0.4s for a different reason). The **largest** qualifying value is **1.0s**.

**Ceiling: 1.25s. New budget: 1.0s** (refused correctly, 3 of 3, with margin below the
0.6s/1.25s-observed flakiness on both sides).

`tests/test_pipeline.py`'s `budget = 1.5` line and its preceding comment block were updated
to `budget = 1.0` with the re-measured numbers (date, ceiling 1.25s, "1.0s refused 3 of 3
runs"). The `sequence_islands=1` paragraph and the `assert preparation_deadline_fires > 0`
line were left untouched, as instructed.

## Step 7: verification

```
$ uv run pytest tests/test_pipeline.py::test_all_products_sequence_pair_honours_the_exact_layout_deadline tests/layout/hierarchy/test_dispatch.py -x
exit=0
11 passed in 1.30s
```
(load before this run: `runnable_5s_mean=70.6`, `step7-final-load.txt` -- over the 64
guideline, recorded and run anyway per the constraints: "never wait for it to fall".)

```
$ uv run ruff check src tests        -> exit 0, "All checks passed!"
$ uv run ruff format --check src tests -> exit 0, "199 files already formatted"
$ uv run mypy src                    -> exit 0, "Success: no issues found in 88 source files"
```

This is the commit that takes
`tests/test_pipeline.py::test_all_products_sequence_pair_honours_the_exact_layout_deadline`
off the branch's known-reds list.

## Files in this directory from this task

- `floor_probe.py` -- the probe script, with its deviations from the brief documented in its
  own module docstring.
- `floor-b{1,4,17,20,21}-{5.0,7.5,10.0,15.0,20.0}.json` / `.log` -- 25 sweep cells.
- `floor-b{1,4,17,20,21}-row-load.txt` -- five row-level loads.
- `deadline-{0.4,0.6,0.8,1.0,1.25,1.5}-run{1,2,3}.log` / `-load.txt` -- 18 deadline-test runs.
- `deadline-baseline-1.5-load.txt` -- the load beside the baseline red-confirmation run.
- `step7-final-load.txt` -- the load beside the final combined verification run.
