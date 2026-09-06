# Does a pre-placement routing-difficulty feature vector predict outcomes?

Experiment, 2026-09-06, branch `exp-features` off master `a6da701`.

The orchestrator design
(`docs/superpowers/specs/2026-09-06-multi-solver-orchestrator-design.md`, §3)
needs a **dispatch key**: something computable before any placer runs that says
which placer, at what budget, for this spec. This experiment asks whether the
user's routing-difficulty idea is that key.

The idea, verbatim:

> The ingredients that appear in the most positions are the ones that will be
> hardest to route. If you have to get copper ingot to 6 or 7 different parts
> of the same production block (early and late pieces), that is a lot more
> difficult to route than something that starts off with magnet and immediately
> uses it.

**Headline: the idea is real and it is measurable, but it is not the dispatch
key.** Strip count and machine count beat it on every outcome we have, and one
structural fact rules it out on its own: the spread features are identical
across a URL's three candidate policies, and on the large URLs the refusal
boundary runs *exactly* along the policy. One topological feature does earn a
place — `items_above_one_belt`, the only rule in the whole sweep with zero false
positives.

## What was run

Rate solves and strip plans only. **No layout, no `scripts/audit.py`, no
harness** — three other experiments were running layouts on this box, and every
outcome number below comes from evidence that already existed.

| Step | Command | Cost |
| --- | --- | --- |
| Feature vector + unit tests | `uv run pytest docs/superpowers/evidence/2026-09-06-exp-features/test_routing_features.py` | 4 tests, seconds |
| Score every spec | `uv run python .../compute_features.py` → `features.jsonl` | 57 specs, ~2 min (dominated by the `mall`/`zurl2` MILPs) |
| Join to outcomes | `uv run python .../join_outcomes.py` → `join.tsv`, `analysis.txt` | seconds |

Per spec the strip plan costs 0.004–0.4 s. That is the whole point: the vector
is affordable at dispatch time, where a layout is not.

### Files

| File | What |
| --- | --- |
| `routing_features.py` | The feature vector. Typed, documented, importable. |
| `test_routing_features.py` | 8 unit tests: the copper/magnet contrast, cycle safety, belt pressure, spray-lane scoring, strip shape, and (experiment 5) live range, cut pressure, spray liveness, lane ceiling. |
| `compute_features.py` | Scores 19 URLs × 3 candidate policies → `features.jsonl` (57 rows). |
| `join_outcomes.py` | Joins to existing evidence → `join.tsv` (84 rows), `analysis.txt` (all tables). |
| `features.jsonl` | One row per (URL, policy): the flat vector plus every item's profile. |
| `join.tsv` | One row per (spec, arm): features + status across rounds, median wall, area, overshoot, refusal class. |
| `analysis.txt` | Every table in full. The README quotes; `analysis.txt` is authoritative. |

### Outcome sources

* **Corpus, 72 cells** — `2026-09-06-speedups-2-batch3/candidate-round{1,2,3}.jsonl`
  (HEAD's code, 30 s budget) with `…-batch2/…` as a second point in time.
  12 URLs × 3 policies × 2 strategies.
* **Large URLs, 12 arms** — `2026-09-05-speedups-2/large-urls/{after,before}.jsonl`.
  `mall`, `zurl2`, `belt3` × {`all-products`, `no-proliferator`} × 2 strategies,
  pooling the 60 s and 100 s runs. This is where the refusals live.

**84 spec × arm points.** Nine are refused in every round, all nine on the large
URLs. The corpus gate at HEAD refuses once in 216 cell-rounds
(`universe-matrix/all-products/sequence-pair`, 1 of 3 rounds — a flake, not a
refusal), so the corpus contributes zero refused-in-all-rounds points.

## The feature vector

Everything is derived from the solved `BuildSpec` plus `plan_strips(spec,
strip_len=6, band_policy=BandPolicy("portable"))` — the same call both placers
make before they start.

**Size**: `machines`, `groups`, `recipes`, `strips`, `distinct_items`.

**Strip shape**: `max_ingredients_per_strip`, `mean_ingredients_per_strip` —
*distinct input items* reaching a strip from either side, not lane count, since
one item split across two lanes is still one thing that has to arrive.

**Belt pressure**:
* `coaters` — sprayed lanes (`spec.spray_lanes`), one Spray Coater each.
* `items_above_one_belt` — items whose block-wide flow (the larger of produced
  and consumed) exceeds the *fastest* belt tier the save can build × the cargo
  stack. Fastest, not the floor, because `layout/belt_tiers.py` upgrades a run
  before it gives up; this is the same threshold the validator's
  `flow.belt_capacity` finding uses.
* `both_fed_items` — items that arrive externally *and* are made inside, the
  case `strip_variants._seat_both_fed_outermost` exists for.

**Topology** — the part the router does not currently see. `freeform._route_all`
orders nets fan-out-first, longest-first with negotiated rip-up; it has no
topological notion at all.

* `depth(group)` = 0 when every ingredient is external, else 1 + the deepest
  ingredient's producer. Back edges through a production cycle contribute 0, so
  the oil chain terminates. `chain_depth` is the maximum.
* Per item: `consumers` (groups eating it), `earliest`/`latest_consumer_depth`,
  `span` = latest − earliest.
* **`spread` = `consumers × span`.** Zero for a one-consumer item *and* for an
  item whose consumers all sit in one layer — deliberately, because fan-out is
  reported separately as `max_consumers` and span is the half of the idea the
  router does not already have. Aggregates: `max_spread`, `sum_spread`,
  `items_with_3plus_consumers`, and `top_spread` (the three widest items).

**The spray, separately.** This was the first surprise and it is worth stating
plainly: **proliferator is never an ingredient.** It reaches machines through
`spray_lanes` and a belt-mounted coater, so it appears in `external_inputs` and
in nobody's `inputs_per_machine`, and the ordinary graph walk scores the widest
item on every `all-products` spec as spread 0. `proliferator_profile` therefore
scores it from the *lanes*: consumers = sprayed lanes, span measured over the
layer each coater must sit in. On `universe-matrix/all-products` that is 47
lanes spanning 8 layers, `proliferator_spread` = 376 — against a `max_spread`
of 16 for the widest real ingredient. The spray genuinely is the widest item in
the block; it just is not in the recipe DAG.

## Results

### 4(a) Is max-spread a better predictor than strip count or machine count?

**No, on every axis we can measure — with one exception that is not max-spread.**

*Wall clock.* Sequence-pair spends its whole budget on almost every corpus cell
(median wall 30.06 s of a 30 s budget, on specs as small as 4 machines), so its
wall carries no difficulty signal at all and its correlations are noise. The
freeform arm is the only informative one:

| feature | Spearman vs median wall (freeform, n=36) |
| --- | --- |
| `distinct_items` | **+0.925** |
| `chain_depth` | +0.909 |
| `groups` / `recipes` | +0.889 |
| `strips` | +0.881 |
| `machines` | +0.845 |
| `max_consumers` | +0.786 |
| `max_spread` / `sum_spread` | +0.591 |
| `items_above_one_belt` | +0.285 |

Same ordering against area (`machines` +0.957, `strips` +0.905, `max_spread`
+0.531). `wall_overshoot_s` is identically zero across all 72 corpus cells, so
no correlation is defined for it.

*Refusal.* Best single-feature threshold for "refused in every round", swept
over all 84 points (9 positive):

| rule | precision | recall | F1 | TP | FP |
| --- | --- | --- | --- | --- | --- |
| `machines >= 436` | 0.90 | 1.00 | **0.95** | 9 | 1 |
| `strips >= 85` | 0.90 | 1.00 | **0.95** | 9 | 1 |
| `items_above_one_belt >= 4` | 0.75 | 1.00 | 0.86 | 9 | 3 |
| `max_consumers >= 6` | 0.88 | 0.78 | 0.82 | 7 | 1 |
| `chain_depth >= 5` | 0.50 | 1.00 | 0.67 | 9 | 9 |
| `max_spread >= 12` | 0.50 | 0.78 | 0.61 | 7 | 7 |

The single false positive for `machines >= 436` is `zurl2/all-products` under
sequence-pair, which does build. No feature *pair* beats `machines` alone: every
top pair rule is `machines >= 436 AND <vacuous second condition>`.

Restricted to the 12 large-URL arms, where the refusals actually are, one rule
is different in kind:

| rule (large URLs only, 9 positive of 12) | precision | recall | F1 |
| --- | --- | --- | --- |
| `machines >= 436` / `strips >= 85` | 0.90 | 1.00 | 0.95 |
| **`items_above_one_belt >= 8`** | **1.00** | 0.67 | 0.80 |
| everything topological (`max_spread >= 12`, …) | 0.88 | 0.78 | 0.82 |

`items_above_one_belt >= 8` is the only rule in the entire sweep that never
fires on a spec that builds, and it names its own mechanism: four of the nine
refusals are `flow.belt_capacity` failures.

*The structural argument, which is stronger than any of the statistics.* A
candidate policy changes machine counts — spraying means fewer machines for the
same output — but it does not change the recipe graph. So across a URL's three
candidates:

| feature | URLs (of 19) where it moves between policies |
| --- | --- |
| `coaters`, `distinct_items`, `proliferator_consumers` | 19 |
| `machines` | 18 |
| `proliferator_span`, `proliferator_spread` | 16 |
| `strips` | 12 |
| `mean_ingredients_per_strip` | 10 |
| `items_above_one_belt` | 6 |
| `both_fed_items` | 1 |
| `chain_depth`, `max_spread`, `sum_spread`, `max_consumers`, `groups`, `recipes`, `max_ingredients_per_strip`, `items_with_3plus_consumers` | **0** |

And the large-URL refusal boundary runs exactly along the policy:

```
belt3/all-products      280 machines,  52 strips, 4 items>belt, maxspr  6  ->  CLEAN both arms
belt3/no-proliferator   537 machines,  90 strips, 8 items>belt, maxspr  6  ->  REFUSED both arms
zurl2/all-products      436 machines,  85 strips, 4 items>belt, maxspr 12  ->  freeform REFUSED, sequence-pair CLEAN
zurl2/no-proliferator   868 machines, 160 strips, 9 items>belt, maxspr 12  ->  REFUSED both arms
mall/all-products       449 machines,  95 strips, 4 items>belt, maxspr 14  ->  REFUSED both arms
mall/no-proliferator    935 machines, 178 strips, 9 items>belt, maxspr 14  ->  REFUSED both arms
```

`max_spread` is 6 for both `belt3` rows — one builds, one refuses. A purely
topological feature is *definitionally* blind to the only distinction that
matters here. `machines` and `strips`, by contrast, order the six specs
monotonically against outcome.

### 4(b) Which two or three features go in the dispatch key?

**`strips`, `items_above_one_belt`, `coaters`.**

1. **`strips`** — the size axis, and the right one. It is what both placers
   actually consume (freeform packs strips; sequence-pair partitions them into
   islands), it moves with policy where the graph features do not, and it ties
   `machines` on refusal (F1 0.95) while correlating nearly as well with wall
   (+0.881 freeform). Prefer it to `machines` because the refusal *messages*
   count strips: "no pack of 54 strips was ever produced".
2. **`items_above_one_belt`** — the only precision-1.0 refusal signal, and the
   only one that names a mechanism a dispatcher could act on rather than just
   widening a budget. At ≥ 8 it says *this will hit belt capacity*, which argues
   for a different intervention (split lanes, upgrade tiers) rather than more
   seconds.
3. **`coaters`** — the arm-choice feature. It decides who packs smaller, and it
   confirms batch 1's finding once size is controlled for:

   | mean ff/sp area ratio | `coaters = 0` | `coaters > 0` |
   | --- | --- | --- |
   | `strips <= 6` | 1.059 (n=7) | **0.987 (n=15)** |
   | `strips > 6` | 1.399 (n=5) | 1.142 (n=10) |

   Freeform wins only in the coated, small cell; sequence-pair's advantage grows
   to 40 % on large uncoated specs (`universe-matrix/no-proliferator`: 31 898 vs
   17 836, ratio 1.788). Raw Spearman of `coaters` against log(ff/sp) is −0.110
   — near zero — precisely because size swamps it; the cross-tab is the honest
   view.

Add `max_spread` only as a tie-break. It is not useless — it is +0.591 against
freeform wall and it is the one feature that separates `universe-matrix` (the
corpus's slowest cell and its only refusal) from everything else its size — but
it earns a fourth slot, not a first.

### 4(c) Copper ingot vs green cube, in numbers

| spec | machines | groups | strips | items | depth | max cons. | **max_spread** | sum_spread | items ≥3 cons. |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `copper-ingot` @ 2000/min | 34 | 1 | 6 | 2 | 0 | 1 | **0** | 0 | 0 |
| `copper-ingot` @ 12000/min | **200** | 1 | 34 | 2 | 0 | 1 | **0** | 0 | 0 |
| `information-matrix` @ 120/min | 193 | 15 | 38 | 23 | 4 | 2 | **0** | 0 | 0 |
| `universe-matrix` @ 60/min | **224** | 38 | 57 | 49 | 8 | 4 | **16** | 52 | 7 |

(All rows `no-proliferator`, so the spray does not confound. Full table
including `all-products` is in `analysis.txt`.)

The user's rate lands at 34 machines, which is not a fair comparison against a
200-machine matrix block, so the table also carries copper ingot scaled until
the machine counts match. **At 200 vs 224 machines the topology numbers are 0
vs 16 max-spread, 0 vs 8 chain depth, 2 vs 49 distinct items** — the contrast is
entirely topology and not size, which is exactly the claim. `universe-matrix`'s
widest items:

```
iron-ingot     4 consumers spanning depths 1..5   spread 16
copper-ingot   4 consumers spanning depths 1..4   spread 12
diamond        ...                                spread  8
```

That *is* copper ingot going to several different parts of the same block, and
`universe-matrix` is the corpus's slowest cell (31.9 s of a 30 s budget on both
arms) and its only refusal.

The instructive middle row is `information-matrix`: 15 recipes, depth 4, 23
items — and `max_spread` **0**. Fifteen recipes that never re-use an
intermediate at two different depths. Chain depth and recipe count do not imply
spread, which is a point in the hypothesis's favour: spread measures something
the size features genuinely do not.

## Caveats

* **84 points is small, and 9 refusals is smaller.** Every refusal-separation
  number above is fitted on 9 positives by exhaustive threshold sweep. Treat the
  thresholds (436 machines, 85 strips, 8 over-belt items) as *this evidence's*
  boundaries, not as constants. The rank orderings are more trustworthy than the
  cut points.
* **The corpus contributes no refusals.** 215 CLEAN of 216 cell-rounds at HEAD.
  Everything about refusal prediction rests on the 12 large-URL arms, and those
  are 3 URLs — the 6 specs are not 6 independent draws.
* **The two outcome sources are not comparable.** Corpus at 30 s; large URLs
  pooled over 60 s and 100 s. A cell that is slow rather than impossible reads
  differently at the two budgets.
* **Sequence-pair wall is budget-bound, not difficulty-bound.** Median 30.06 s
  of a 30 s budget across all 36 corpus specs. Its wall correlations are noise
  and are reported only for completeness.
* **`max_spread` and `sum_spread` are monotone-equivalent on this data** — they
  produce identical Spearman values in every table. With 18 URLs there are too
  few distinct spread values to tell them apart; that is a corpus limitation,
  not a claim that they are the same feature.
* **The spread definition is a choice.** `consumers × span` scores a six-consumer
  item in one layer as 0. That is intentional (fan-out lives in `max_consumers`)
  but a different weighting, e.g. `consumers × (span + 1)`, would rank specs
  differently and was not tried.
* **Nothing here was validated by running a layout.** The claim is about
  *predicting* outcomes from existing evidence. `copper-ingot` at 12000/min has
  never been laid out; its row is a feature vector, not a result.

## Experiment 5: live range and pressure

Follow-up, same worktree and same rules. The question: does **live range**, in
the register-allocation sense, predict outcomes better than `spread` — and are
they the same measurement wearing two names?

**They are not the same measurement, and the difference is two things, not
one.** `spread` = consumers × (last consumer depth − *first consumer* depth). A
live range runs from the **definition** — the producing recipe's depth, or
layer 0 for anything arriving at the block boundary — to the **last use**, with
no fan-out multiplier. So an item made at depth 0 and eaten once at depth 5 has
live range 5 and spread 0.

### New features

* `live_range` = last use depth − producer depth, per item. Raw ore and
  external inputs are defined in layer 0; a final output nothing consumes has
  range 0.
* `live_lanes` = `ceil(flow / lane capacity)`, sharing `item_flows` with
  `items_above_one_belt` so the two cannot disagree about an item's rate.
* **Cut pressure.** Cut *d* is the horizontal band between layer *d* and
  *d*+1. `pressure(d)` counts items live across it; `lane_pressure(d)` sums
  their `live_lanes`. This is the register-pressure analog and it is not a
  metaphor — both placers build in bands, so it is literally the number of
  belts that must cross one.
* Aggregates: `max_live_range`, `sum_live_range`, `items_live_range_ge3`,
  `max_pressure` (+ its depth), `max_lane_pressure` (+ its depth),
  `sum_pressure`, `lane_pressure_per_strip`, and `_no_spray` variants.

**`sum_pressure ≡ sum_live_range`, exactly, on all 84 points** — an item
crosses one cut per layer of its range, so the identity is structural, not
empirical. Both columns are kept only so the join can verify it.

**Proliferator: counted as live across every cut it spans.** The spray belt
runs from the block edge (layer 0) to the deepest coated lane, so it is live
the whole way and does cross every band in between — a Spray Coater sits on the
lane it coats and the spray has to reach it. On
`universe-matrix/all-products` that is `proliferator_live_range` 8, and it moves
`max_pressure` 17 → 18. Its lane count comes from its external-input rate, which
**under-counts** if each coater needs its own spur rather than drinking from a
shared bus, so the number is a floor. The `_no_spray` columns give the delta for
anyone who wants it excluded.

### Head to head

Spearman is on the freeform corpus arm (n=36) — sequence-pair is budget-bound
and carries no signal. Refusal F1 is the best threshold over all 84 points
(9 positive), and separately over the 12 large-URL arms.

| feature | ρ wall | ρ area | refusal F1 (all) | P | R | F1 (large) | distinct values |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `sum_live_range` | **+0.930** | +0.924 | 0.61 | 0.50 | 0.78 | 0.82 | 20 |
| `distinct_items` | +0.925 | +0.946 | 0.61 | 0.50 | 0.78 | 0.82 | 24 |
| `max_live_range` | +0.920 | +0.893 | 0.67 | 0.50 | 1.00 | **0.00** | 7 |
| `max_pressure` | +0.914 | +0.921 | 0.61 | 0.50 | 0.78 | 0.82 | 16 |
| `max_lane_pressure` | +0.914 | +0.921 | 0.82 | 0.88 | 0.78 | **0.95** | 17 |
| `max_lane_pressure_no_spray` | +0.880 | +0.937 | 0.82 | 0.88 | 0.78 | 0.95 | 12 |
| `strips` | +0.881 | +0.907 | **0.95** | 0.90 | 1.00 | **0.95** | 23 |
| `items_live_range_ge3` | +0.774 | +0.698 | 0.61 | 0.50 | 0.78 | 0.82 | 11 |
| `max_spread` | +0.591 | +0.531 | 0.61 | 0.50 | 0.78 | 0.82 | 5 |
| `items_above_one_belt` | +0.285 | +0.285 | 0.86 | 0.75 | 1.00 | 0.80 | 5 |
| `lane_pressure_per_strip` | **−0.282** | −0.301 | 0.21 | 0.12 | 1.00 | 0.74 | 25 |

On the 12 large-URL arms, `max_lane_pressure >= 15` and `strips >= 85` produce
the **identical** confusion matrix — 9 TP, 1 FP, 0 FN, the same single false
positive (`zurl2/all-products` under sequence-pair, which does build):

```
belt3/all-products      strips  52   lane pressure 11   ->  CLEAN both arms
belt3/no-proliferator   strips  90   lane pressure 15   ->  REFUSED both arms
zurl2/all-products      strips  85   lane pressure 24   ->  freeform REFUSED, sequence-pair CLEAN
mall/all-products       strips  95   lane pressure 20   ->  REFUSED both arms
zurl2/no-proliferator   strips 160   lane pressure 30   ->  REFUSED both arms
mall/no-proliferator    strips 178   lane pressure 25   ->  REFUSED both arms
```

Across all 84 points `strips` wins (0.95 vs 0.82) because `universe-matrix`'s
lane pressure (17–18) lands inside the refusing band while its strip count
(46–57) does not.

Two structural notes on the lane refinement. **`max_lane_pressure` equals
`max_pressure` at every one of the 72 corpus points** and differs only on the
12 large ones — no corpus item is above one belt — so it is a large-spec-only
refinement, and its entire advantage over item pressure comes from the same
place `items_above_one_belt` gets its precision. And **`max_live_range` is 5 on
all twelve large arms**, which is why its large-URL F1 is 0.00: it is the second
best wall predictor here and completely blind where the refusals are.

### Monotone equivalence

**No pair in the headline set is monotone-equivalent** (`|ρ| = 1`). But almost
everything is close, which matters more:

| pair | ρ |
| --- | --- |
| `max_pressure` vs `max_lane_pressure` | +0.987 |
| `sum_live_range` vs `max_lane_pressure` | +0.986 |
| `sum_live_range` vs `distinct_items` | +0.981 |
| `strips` vs `distinct_items` | +0.950 |
| `strips` vs `max_live_range` | +0.925 |
| **`max_spread` vs `max_live_range`** | **+0.792** |
| `max_spread` vs `items_above_one_belt` | +0.698 |

The live-range and pressure family is a near-relabelling of `distinct_items`
and `strips` (+0.94 to +0.99). `max_spread` is the odd one out at +0.79 — the
one feature genuinely ordering these specs differently, and also the one that
performs worst.

The qualitative version of the same point, and the best single argument for
live range over spread: **`information-matrix` scores `max_spread` 0 at all
three candidate policies**, while live range moves and tracks the wall.

| `information-matrix` (freeform) | max_spread | max_live_range | sum_live_range | max_pressure | median wall |
| --- | --- | --- | --- | --- | --- |
| `no-proliferator` | 0 | 2 | 19 | 7 | 12.5 s |
| `all-products` | 0 | 4 | 23 | 8 | 29.5 s |
| `output-products` | 0 | 4 | 23 | 8 | 26.2 s |

Spread says these three specs are identical. They are not: the freeform arm
takes 2.4× longer on one of them, and live range sees it.

### Arm choice

`max_pressure_no_spray` (+0.607) and `max_lane_pressure_no_spray` (+0.600) rank
second and third against log(ff/sp) area behind `machines` (+0.667), ahead of
`strips` (+0.561) — but the tercile split shows why this does not displace
`coaters`:

```
max_lane_pressure         < 3: 1.028 (n=7)   3..6: 1.002 (n=16)   >= 6: 1.244 (n=14)
max_live_range            < 1: 1.000 (n=3)   1..2: 1.018 (n=14)   >= 2: 1.169 (n=20)
lane_pressure_per_strip   < 0.47: 1.177      0.47..1: 1.115       >= 1: 1.011
```

Pressure only restates "big specs favour sequence-pair". It never predicts a
freeform *win* (no tercile mean below 1.00), where the coating cross-tab does
(0.987 for coated specs at ≤ 6 strips). Arm choice stays with `coaters`.

### Copper ingot vs green cube, in the new numbers

| spec (`no-proliferator`) | machines | strips | depth | max_spread | max_live_range | sum_live_range | max_pressure | peak cut |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `copper-ingot` @ 2000/min | 34 | 6 | 0 | 0 | 0 | 0 | 0 | — (no cuts) |
| `copper-ingot` @ 12000/min | 200 | 34 | 0 | 0 | 0 | 0 | 0 | — (no cuts) |
| `information-matrix` @ 120/min | 193 | 38 | 4 | **0** | 2 | 19 | 7 | cut 0 |
| `universe-matrix` @ 60/min | 224 | 57 | 8 | 16 | 7 | 90 | **17** | cut 2 |

`universe-matrix`'s pressure profile — the number of belts that must cross each
band — is `13, 16, 17, 13, 10, 8, 7, 6`; `information-matrix`'s is `7, 6, 4, 2`;
copper ingot's is empty, because a one-recipe block has no band to cross. The
longest ranges on `universe-matrix` are `antimatter` 7,
`electromagnetic-matrix` 6, `energy-matrix` 6 — note these are *different items*
from the widest-spread ones (`iron-ingot` 16, `copper-ingot` 12), which is the
def-to-last-use versus first-use-to-last-use difference showing up concretely.

### Answers

**(a) Is live range monotone-equivalent to spread here?** No — pairwise Spearman
is +0.792 and no headline pair reaches `|ρ| = 1`; qualitatively they disagree,
since `max_spread` is identically 0 across `information-matrix`'s three policies
while `max_live_range` moves 2 → 4 and tracks a 12.5 s → 29.5 s freeform wall
gap. Live range is closer to `strips` (+0.925) than to spread.

**(b) Does pressure beat strips / items_above_one_belt on wall or refusal?** On
wall, yes: `sum_live_range` +0.930 and `max_live_range` +0.920 beat `strips`
+0.881, and `sum_live_range` is the best wall predictor in the whole study. On
refusal, no overall — `max_lane_pressure` F1 0.82 against `strips` 0.95 over 84
points — though on the 12 large-URL arms `max_lane_pressure >= 15` ties
`strips >= 85` with the identical 9 TP / 1 FP; `max_live_range` is useless there
(constant 5 on all twelve) and `lane_pressure_per_strip` is actively harmful
(ρ −0.282, F1 0.21).

**(c) What changes in the dispatch key?** `max_spread` is dropped and
`sum_live_range` replaces it: live range strictly dominates spread here — better
on wall, better on area, and it sees the `information-matrix` case spread is
blind to. The key becomes **`strips`** (refusal, F1 0.95), **`sum_live_range`**
(budget estimate — the best available predictor of how long freeform will take),
**`items_above_one_belt`** (the zero-false-positive belt-capacity branch), and
**`coaters`** (arm choice, still the only feature that predicts a freeform win).
`max_lane_pressure` is a reasonable substitute for `strips` on large specs but
not an addition to it.

### Experiment 5 caveats

* Same 84 points, same 9 refusals. Every F1 above is fitted by exhaustive
  threshold sweep on 9 positives.
* **The wall improvement is inside the noise this data can resolve.** +0.930 vs
  +0.881 on 36 points is not a distinguishable difference, and the whole
  live-range family correlates +0.94 to +0.99 with `distinct_items` — treat "as
  good as the size features, on a more principled basis" as the claim, not "a
  better predictor".
* Wall is measured on the freeform arm only. The sequence-pair arm spends its
  entire budget on every corpus cell, so half the data cannot test any of this.
* Pressure assumes one belt per item per band. Real routing shares corridors,
  splits and merges; a lane count is an upper bound on distinct commodities and
  a lower bound on belt segments.
* The spray's lane count is a floor (shared-bus assumption), and its depth comes
  from each sprayed lane's *earliest* consumer, so a coater seated deeper than
  that would extend the range beyond what is measured here.

## What this suggests next

* Put `strips`, `sum_live_range`, `items_above_one_belt` and `coaters` in the
  orchestrator's dispatch key (experiment 5 replaced `max_spread` with
  `sum_live_range`) and leave the rest of the graph features out of v1.
* `items_above_one_belt >= 8` deserves its own branch — not "spend more
  seconds" but "this spec needs lane splitting or a belt-tier decision before a
  placer sees it". Four of nine refusals are `flow.belt_capacity`, and two more
  (`pack-never-produced`, at 0.5 s wall) are the packer giving up instantly,
  which no budget fixes either.
* The spray finding is actionable independently: with 47 coaters spanning 8
  layers on `universe-matrix/all-products`, the spray is the widest net in the
  block and the router has no idea. If the fan-out-first net ordering is ever
  revisited, that is where to look first.
