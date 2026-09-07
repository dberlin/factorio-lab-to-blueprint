# One blueprint per item

> "One by one, generate a blueprint that creates each item/building in the game
> as its output. See what bugs arise. Classify all the bugs by group and fix
> them. Repeat until we can build at least 1 of each item." -- the user,
> 2026-09-06.

Harness: `scripts/item_sweep.py` (with `tests/scripts/test_item_sweep.py`).
Rounds are numbered; every round keeps its own `sweep-<N>.jsonl`, and
`round-<N>/` holds the blueprint and the full CLI log for every item.

## Scope

The dataset has 486 `items`, but only three categories name a physical thing a
factory produces. `technologies` (107) and `upgrades` (199) are research rows
whose output is a token that never rides a belt -- the tier corpus excludes them
for the same reason -- and `effects` (6) are the proliferator module entries,
not items at all.

| | count |
|---|---|
| in scope (`components`, `buildings`, `buildings-alt`) | **174** |
| &nbsp;&nbsp;BUILD -- a craftable non-mining recipe exists | **151** |
| &nbsp;&nbsp;RAW -- extraction only | **14** |
| &nbsp;&nbsp;OTHER -- nothing in the dataset produces it | **9** |

### RAW (14) -- out of scope, with the reason

Each is produced only by an extraction recipe. A Mining Machine is placed on a
vein and a Water Pump on an ocean tile; neither is a factory block a blueprint
can carry, so there is nothing for this tool to lay out.

| item | only recipe | extractor |
|---|---|---|
| `iron-ore` | `iron-vein` | Mining Machine |
| `copper-ore` | `copper-vein` | Mining Machine |
| `stone` | `stone-vein` | Mining Machine |
| `coal` | `coal-vein` | Mining Machine |
| `silicon-ore` | `silicium-vein` | Mining Machine |
| `titanium-ore` | `titanium-vein` | Mining Machine |
| `kimberlite-ore` | `kimberlite-vein` | Mining Machine |
| `fractal-silicon` | `fractal-silicon-vein` | Mining Machine |
| `optical-grating-crystal` | `optical-grating-crystal-vein` | Mining Machine |
| `spiniform-stalagmite-crystal` | `spiniform-stalagmite-crystal-vein` | Mining Machine |
| `unipolar-magnet` | `unipolar-magnet-vein` | Mining Machine |
| `water` | `ocean` | Water Pump |
| `crude-oil` | `crude-oil-seep` | Oil Extractor |
| `fire-ice` | `ice-giant-gas-hydrate` | Orbital Collector |

`silicon-ore` deserves a note: it *does* have a second recipe (`silicon-ore`,
from stone), but that recipe is in the dataset's own
`defaults.excludedRecipes`, so no solver may choose it and the item is
extraction-only in practice.

### OTHER (9) -- in scope by category, produced by nothing

| item | why |
|---|---|
| `log`, `plant-fuel` | gathered from trees and plants; no recipe |
| `ray-receiver-pro` | `buildings-alt`: a display-only alternate form of the Ray Receiver, with no recipe of its own |
| `df-core-element`, `df-dark-fog-matrix`, `df-energy-shard`, `df-silicon-based-neuron`, `df-negentropy-singularity`, `df-matter-recombinator` | Dark Fog drops. `rates/candidates.py:356` refuses them outright: no normal DSP catalog identity, so derived solving cannot put one in a blueprint |

### The rate

A URL carries a rate and the rate decides how big the block is. Each BUILD item
gets the round-number rung nearest `1.5 x` one machine's output of the target
recipe, clamped to `[R, 6R]` -- one to six machines of the target recipe, biased
small so the block stays a block. The machine is `recipe.producers[0]`, which is
what a bare URL (carrying no `mmr` field) actually resolves to through
`rates/adjust.py::select_machine`. Every row records `target_machines = rate/R`
so the claim is checked rather than asserted; a unit test asserts it holds for
all 151.

## Rounds

| round | items run | CLEAN | REFUSED | INVALID | CRASH | wall | base |
|---|---|---|---|---|---|---|---|
| 1 | 151 | **150** | 1 | 0 | 0 | 5.43 h | master `340f8e01` |
| 2 | 151 | **151** | 0 | 0 | 0 | 5.33 h | master `840204fc` + the group-1 fix |

**Round 2 is the answer to the question that was asked: every item in the game that a
factory can make -- all 151 of them -- builds.** 151/151 CLEAN, every one
cross-validated by the viewer's independent decoder with a valid hash and a matching
building count, zero validator errors, and not one check landing in `Report.skipped`.

Round 1 ran on master `340f8e01`; the branch was then rebased onto master `840204fc`
(64 commits of other work had landed meanwhile) and the one refusal was confirmed to
reproduce there unchanged before anything was fixed.

Round 2 is not slower or bigger for the fix: 127.0 s mean per item against round 1's
129.4 s, and the geometric mean of round-2 area over round-1 area across the 150 items
both rounds built is 0.9893, with a median of exactly 1.0000 -- that is, almost every
block is byte-identical in size and the handful that moved got slightly smaller. CPU
pressure over the round (five-second mean of `vmstat`'s runnable count, taken before
each build) averaged 4.5 and peaked at 54.8 on 128 cores, so no timing here was taken
on a contended box.

"CLEAN" is a strong word here and is meant to be. It requires all four of: the CLI
exiting 0 (so the validator found no errors, since the CLI refuses to emit an invalid
blueprint without `--allow-invalid`); the viewer's independent TypeScript decoder
parsing the blueprint; that decoder's hash checking out; and its building count matching
what our own report claimed. Beyond that, **no build in round 1 had a single check land
in `Report.skipped`** -- nothing was clean merely because it went unchecked -- and the
only warning any of the 150 logs carries is the expected "this URL carried no technology
set, so a FULLY-RESEARCHED save is ASSUMED", which is a property of a bare URL rather
than of the build.

Cost: 129.4 s mean per item, 193.9 s worst. The biggest block was `orbital-collector`
(471 machines); the smallest specs are single-machine.

## Groups

### Group 1 -- a shard repair aimed at a lane too small to take it

**1 item** (`df-strange-annihilation-fuel-rod` @ 2/min). **Planner bug.**

Reproducer:

```
uv run flab2bp "https://factoriolab.github.io/dsp/list?o=df-strange-annihilation-fuel-rod*2&v=11" \
    --budget 30 -v -o /tmp/bp.txt
```

Symptom: every packing that wired was rejected by our own validator, on
`flow.conservation` -- "6 machine(s) consume 2 items/s of copper-ingot but only 29/15
items/s of it can reach them in flow order; short by 1/15" -- from both strategies and
all three candidate policies, so the build refused (exit 3).

Where it goes wrong: `src/flab2bp/layout/freeform.py::_join_shard_islands`
(the sink-lane choice and the transfer credit inside its repair loop).

Why it is a planner bug and not a wrong conviction: the validator is right. copper-ingot
has two producer machines at 1 item/s and six consumers drawing exactly 2 items/s, so the
spec nets to zero and there is no slack anywhere. `_shard_sinks` divides the producer's
destinations between two shards and `_allocate_machines` gives each shard one machine;
in the placement, one machine ends up serving consumers that draw 16/15 and the other
consumers that draw 14/15. The validator's own min cut says so exactly --
`consumer#206 -> SINK cap=2`, `consumer#913 -> SINK cap=4`, `consumer#951 -> SINK cap=4`,
`consumer#952 -> SINK cap=4`, `SOURCE -> producer#217 cap=15`, which is 29 units at
scale 15. In game that block would run at 29/30 of its rate; refusing it is correct.

`_join_shard_islands` exists precisely to repair this, and it fired -- but it aimed
wrong. Measured from the real build, its lane graph was
`supply={213: 1, 216: 0, 224: 1, 227: 0}` (216 and 227 are sibling output lanes of the
same machines, so their production is credited to 213 and 224),
`demand={199: 2/15, 815: 16/15, 906: 4/15, 917: 8/15}`, joined as
`[(213,199), (216,815), (224,906), (227,917), (213,216), (224,227)]`. That is a deficit
island owing 18/15 against 15/15 and a surplus island owing 12/15 against 15/15 -- 3/15
each way. It emitted one net, `(224, 199)`, because it picked the receiving lane by
fewest taps. **A belt arrives at one lane, and a lane can take no more than its own
consumers draw**, so at most 2/15 could ever reach lane 199; the loop nonetheless
credited the whole 3/15 and stopped, leaving exactly the 1/15 the validator then found.

Fix: give each lane a residual credit equal to its draw and never credit a transfer
beyond it; keep aiming at the least-tapped lane whenever it can hold the whole transfer,
and reach for the hungriest only when spreading would under-deliver; buy a second net
when no single lane can absorb the deficit, and let two surplus islands belt the same
starving lane when neither covers it alone. On this build the repair is still ONE net,
now `(224, 815)`, so it costs no extra belt.

The two-stage shape of that rule is the reviewer's, and it matters. Aiming
unconditionally at the hungriest lane -- the first version of this fix -- is wrong in
two reachable ways, both demonstrated with runnable cases:

* The hungriest lane is *by construction* the most crowded: `_merge_lanes` packs the
  most destinations onto the lane with the most draw, and each tap at a lane end is one
  side of a four-sided junction. Preferring it always aims every repair at the junctions
  least able to take one.
* A lane can be hungry and already full. With `supply={1: 10, 2: 3, 3: 5}`,
  `demand={101: 10, 102: 8, 103: 0}` and producer 1 having nowhere but lane 101 to go,
  the hungriest lane 101 is saturated from inside its own island, so a net aimed there
  delivers nothing while the loop credits 5 and stops -- the same failure this group is
  about, with the sign flipped.

Letting a lane receive only one net ever (also in the first version) *lost* a repair
master already makes: a deficit of 10 owed by two surplus islands of 6 and 4 needs both
belts, and master emits both.

Red-green: five tests in `TestAShardThatCannotFeedItself` (`tests/layout/test_freeform.py`).
Three fail on unmodified master -- `test_the_repair_goes_to_the_lane_that_can_absorb_it`
(`[(224, 199)]`), `test_a_deficit_wider_than_one_lane_buys_a_second_net` (`[(20, 30)]`)
and `test_a_lane_that_draws_nothing_is_never_belted` (`[(20, 30)]`). The other two pass
on master and guard behaviour the first version of the fix would have broken.

Guard: `scripts/audit.py --budget 30` gives 72/72 clean before and after
(`guard-baseline.jsonl`, `guard-shard-lane.jsonl`); `audit_compare.py` reports
`clean 72 refused 0 invalid 0 crashed 0 paired 72 area ratio 1.0052 p95 31.7s`. It
prints FAIL on its `p95 > 30 s` arm only -- the baseline compared against ITSELF gives
31.4 s and the same FAIL, so that arm is a property of the 30 s default at budget 30 and
not a regression. Area is 0.52 % up, inside the 1.3 % same-arm noise band the script
itself uses.

Reproducing the pytest evidence: run it through `uv run` from inside the worktree. A bare
`pytest` inherits `VIRTUAL_ENV` from the parent checkout, whose editable install points at
*master's* `src`, and the new tests then fail against code that does not contain the fix.
`uv run` ignores that variable (it says so) and resolves the worktree's own `.venv`;
verified by importing `flab2bp.layout.freeform` and printing `__file__`.

## Genuine limits and non-bugs

No refusal in round 1 was a physical limit at the chosen settings: there was only one
refusal and it was ours.

## Pre-existing test failures, not from this work

These two fail identically with `src/flab2bp/layout/freeform.py` reverted to master
`840204fc`, so they are neither caused nor fixed here:

- `tests/layout/test_sequence_pair.py::test_two_stage_alignment_retains_cp_sat_direct_opportunity`
  (`AssertionError: assert frozenset()`)
- `tests/test_pipeline.py::test_all_products_sequence_pair_honours_the_exact_layout_deadline`
  (`DID NOT RAISE NoValidLayout`)

## Parked

**`_join_shard_islands` is a greedy heuristic where a max flow would be exact.**
Raised by the reviewer and not taken here, because it is a redesign rather than a fix and
the corpus gives no evidence it is needed today. Two things it would close by
construction rather than by tie-break:

* The credit cap is the lane's *gross* draw, so a transfer is only provably deliverable
  when the deficit island's internal producers that already reach that lane have
  somewhere else inside the island to go. Sibling output lanes always give that freedom,
  which is why the two-stage rule above is sound on every case measured; a real max flow
  would not need the argument.
* Island membership is **undirected** union-find, so a component's supply is pooled even
  where the flow cannot traverse it (`P1 -> L1`, `P2 -> L1`, `P2 -> L2` is one island,
  but `P1` can only ever reach `L1`). That over-crediting predates this work.

The graphs are a handful of lanes per cargo, so an explicit max flow is affordable. The
honest version builds the lane graph and credits each candidate edge with the actual
increase in flow.

**`_shard_sinks` splits destinations by COUNT, not by demand**
(`freeform.py`, `per = math.ceil(len(dests) / n)`). Splitting by demand would make this
whole residue smaller and rarer, and is worth doing on its own merits, but it cannot
retire the repair: the docstring's own `universe-matrix` case proves an integer split of
machines cannot serve a fractional split of demand however the destinations divide.

## Needs the user

Nothing. Every failure round 1 found was ours and was fixable in code.
