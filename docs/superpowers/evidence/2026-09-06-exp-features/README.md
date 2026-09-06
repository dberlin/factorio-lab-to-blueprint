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
| `test_routing_features.py` | 4 unit tests: the copper/magnet contrast, cycle safety, belt pressure, spray-lane scoring, strip shape. |
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

## What this suggests next

* Put `strips`, `items_above_one_belt` and `coaters` in the orchestrator's
  dispatch key and leave the graph features out of v1.
* `items_above_one_belt >= 8` deserves its own branch — not "spend more
  seconds" but "this spec needs lane splitting or a belt-tier decision before a
  placer sees it". Four of nine refusals are `flow.belt_capacity`, and two more
  (`pack-never-produced`, at 0.5 s wall) are the packer giving up instantly,
  which no budget fixes either.
* The spray finding is actionable independently: with 47 coaters spanning 8
  layers on `universe-matrix/all-products`, the spray is the widest net in the
  block and the router has no idea. If the fan-out-first net ordering is ever
  revisited, that is where to look first.
