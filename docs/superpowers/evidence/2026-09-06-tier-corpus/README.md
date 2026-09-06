# Tech-tier corpus and recipe co-occurrence mining

**Question.** What gets built in DSP is dictated by tech level and resource cost:
tier 1 things get built together, tier 2 things need tier 1 things. Across a
corpus built that way, which recipes go together, or share ingredients, often
enough that a **pregenerated semi-flexible layout block** would pay for itself?

**Answer, in one line.** Two clusters carry the corpus: an
`iron-ingot + copper-ingot + circuit-board` smelt-and-board block appears in
**52% of specs** across **all seven tiers**, and
`copper-ingot + magnet + magnetic-coil` in **51%**. Two blocks cover **68%** of
940 solved specs; eight cover **84%**. Both are trunk blocks at chain depth 2-3,
and both need to be parametric in machine count over roughly a **1x-100x** range.

Rate solves only. No layout was run: no `scripts/audit.py`, no harness.

---

## 1. Method

### 1.1 Tech tiers (`tiers.py` -> `tiers.json`)

Dataset: the vendored FactorioLab DSP set, `load_vendored()` in
`src/flab2bp/lab/data.py`, version **DSP 0.10.29.21950** — 486 items, 493
recipes.

The dataset **does** carry unlock lists, so no fallback signal was needed. The
exact fields used:

| Fact | Field | Check |
| --- | --- | --- |
| What is a technology | `Item.technology` non-`None` (`lab/schema.py::Technology`) | 306 of 486 items |
| Research cost | the `Recipe` with the **same id as the technology item**; its `Recipe.inputs` are the cubes | 306/306 technologies have a same-id recipe |
| What a technology unlocks | `Item.technology.recipe_unlock: tuple[str, ...]` | names 164 distinct recipes, 0 dangling ids |
| Prerequisites (recorded, not used for tiering) | `Item.technology.prerequisites` | — |

Tier assignment:

* **technology tier** = the highest matrix colour among its research-cost
  inputs. `electromagnetic-matrix`=1 (blue), `energy-matrix`=2 (red),
  `structure-matrix`=3 (yellow), `information-matrix`=4 (purple),
  `gravity-matrix`=5 (green), `universe-matrix`=6 (white). 295 of 306
  technologies cost cubes; the other **11 are the pre-matrix starting
  technologies** whose research cost is raw components (circuit-board,
  magnetic-coil, gear, ...) and they are tier 0.
* **recipe tier** = **MIN** over the technologies that unlock it — the question
  is "when can I first build this", and a recipe reachable by two research paths
  is available at the earlier one. A recipe named by no technology is tier 0.
* **item tier** = MIN recipe tier over the recipes producing it (technology
  research recipes excluded — a technology token never flows on a belt).

The 23 non-technology recipes that no technology unlocks are exactly the DSP
starting set: the 13 `*-vein` / `ocean` / `crude-oil-seep` extractions plus
`iron-ingot`, `copper-ingot`, `stone-brick`, `magnet`, `magnetic-coil`, `gear`,
`circuit-board`. That the derivation lands on precisely the known starting
inventory is the main correctness check on the tier map.

`df-dark-fog-matrix` is bucketed separately as tier 7. It is not a colour on the
normal ladder, and Dark Fog items have no normal DSP catalog identity —
`rates/candidates.py` refuses them outright — so tier 7 is scored in
`tiers.json` but excluded from the corpus.

### 1.2 Corpus (`build_corpus.py` -> `corpus.tsv`, `restrictions.json`)

For each tier T in 0..6, every target available at tier <= T:

| Family | Rate | Policies |
| --- | --- | --- |
| **buildings** (dataset category `buildings`/`buildings-alt`) | 1/min | no-proliferator, + all-products where a proliferator is researchable at T |
| **research matrices** | 60/min and 600/min | same |
| **components** (dataset category `components`) | 60/min | no-proliferator only, to bound the sweep |

URLs are bare FactorioLab URLs, `?o=<item>*<rate>&v=11`. `lab/url.py::_parse_objectives`
defaults the objective to `ObjectiveUnit.Items` / `ObjectiveType.Output` and
`DisplayRate` defaults to `PerMinute`, so the value reads directly as items/min
(`rates/solve.py::target_rates`).

**The tier restriction is a sidecar, and here is why.** `lab/url.py` encodes the
excluded-recipe set under the `rex` query key and the researched-technology set
under `tre`, both as `parse_subset` payloads indexed against the mod-hash
tables — a hand-written bare URL cannot carry either. So the restriction lives
in `restrictions.json` and is applied to the parsed `LabRequest` with
`dataclasses.replace` in `solve_corpus.py`.

**A trap worth stating plainly: the rate solver never reads
`researched_technology_ids`.** A repo-wide search finds that field used in
exactly one place, `lab/techs.py`, which derives belt/sorter altitude rules for
the **layout** stage. What actually gates `rates.solve` is
`solve.py::_excluded_recipes`, reading `request.excluded_recipe_ids` — and that
function treats a present set as *authoritative and whole*, not as a delta
against the mod defaults. So the tier gate is:

```
excluded_recipe_ids = data.default_recipe_excluded
                    | {recipe : recipe_tier > T}
                    | {every technology research recipe}
```

The researched-technology set is carried alongside so the sidecar describes a
complete save, and `machine_rank_ids` is set to the machines buildable at tier T,
best-first by speed. That last one matters: `rates/adjust.py::select_machine`
falls back to `recipe.producers[0]` when there is no rank, which would silently
hand a tier-0 save an `assembling-machine-3`.

### 1.3 Solve (`solve_corpus.py` -> `solves.jsonl`)

Policy mapping copies `rates/candidates.py::_build_candidates_canonical` exactly:

* `no-proliferator` -> `solve(..., mode_policy=ProliferatorMode.NONE)`
* `all-products` -> `solve(..., tier=<mark>, mode_policy=PRODUCTS)`, dropped when
  machine count exceeds 4x the unproliferated baseline (`_RUNAWAY_FACTOR`, that
  module's guard against the `reforming-refine`/`plasma-refining` self-feeding
  loop). It never fired.

Each record carries the recipe set, per-recipe machine counts (integer and
exact), inputs/outputs per group, external inputs, and the item flow graph as
`producer -> consumer` edges keyed by the crossing item.

### 1.4 Mining (`mine.py` -> `mining.json`)

Recipe ids are unique inside a spec, so an induced subgraph is fully identified
by its node set — **the canonical string is just the sorted recipe ids**, and no
isomorphism test is needed. Connected induced subgraphs of size 2-6 are
enumerated with ESU (Wernicke's `EnumerateSubgraphs`) over the undirected
projection, run once per **distinct** spec graph (123 of them for 940 specs) and
attributed back.

A candidate is reported **closed** when no single recipe attaches to it in
*every* supporting spec. If such a recipe exists, the cluster is never seen
without that neighbour, so the cluster alone is not the block — cluster plus
neighbour is. This matters enormously: at a support floor of 25 specs there are
**2825 frequent subgraphs but only 35 closed ones**, and without the test the
top list is nothing but fragments of one big always-together cluster. The test
reads its extension candidate from the spec graph, so it correctly rejects a
size-6 set that always sits under a 7th recipe even though enumeration stops
at 6.

Support floor 25 was chosen to land the closed list in the 20-50 band the
question asks for; it yields 35.

---

## 2. Per-tier counts

From `tiers.json` (`counts`):

| Tier | Colour | Technologies | Recipes | Items | Buildings | Components |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | start (no matrix) | 11 | 45 | 34 | 9 | 25 |
| 1 | blue / electromagnetic | 34 | 72 | 36 | 16 | 20 |
| 2 | red / energy | 59 | 107 | 41 | 17 | 24 |
| 3 | yellow / structure | 77 | 116 | 27 | 9 | 18 |
| 4 | purple / information | 47 | 60 | 13 | 6 | 7 |
| 5 | green / gravity | 42 | 53 | 10 | 2 | 8 |
| 6 | white / universe | 32 | 32 | **0** | **0** | **0** |
| 7 | dark fog (off-ladder) | 4 | 8 | 4 | 3 | 1 |

(Counts are *newly available at* that tier, not cumulative.)

**The white cube unlocks no production recipe at all.** All 32 tier-6 "recipes"
are the research recipes of the 32 white-cube technologies themselves; every one
of those technologies is in the dataset's `upgrades` category. Confirmed
end-to-end downstream: across all 188 solved cells that exist at both tiers,
**tier 5 and tier 6 produce byte-identical recipe sets** — zero differences. For
a block library this means the ladder has **six** meaningful rungs, not seven,
and nothing needs a white-cube variant.

Also note the shape of the ladder: recipes peak at tier 3 (yellow) and the
*item* count falls away hard after it. Most of the catalog is unlocked by
mid-game; the late tiers are overwhelmingly stat upgrades.

`ray-receiver-pro` is the one building with no producing recipe (it is a
`buildings-alt` variant), so it has no tier and is not a corpus target.

---

## 3. Corpus size and refusals

| | |
| --- | --- |
| corpus rows (`corpus.tsv`) | **1041** |
| solved | **940** |
| refused | **101** |
| distinct targets | 129 |
| distinct spec graphs | 123 |
| total solve wall time | 26.6 s (max single solve 0.20 s) |
| groups per spec | median 7, max 38 |
| machines per spec | median 10, max 2174 |

Rows per tier: T0=36, T1=92, T2=142, T3=178, T4=189, T5=202, T6=202.
Rows per kind: building 497, component 430, matrix 57, matrix10x 57.
Rows per policy: no-proliferator 741, all-products 300.

**Every one of the 101 refusals is the same thing**, and it is not a defect:
16 distinct raw-resource targets (`iron-ore`, `copper-ore`, `stone`, `coal`,
`water`, `crude-oil`, `sulfuric-acid`, `titanium-ore`, `silicon-ore`,
`fire-ice`, `fractal-silicon`, `kimberlite-ore`, `unipolar-magnet`,
`organic-crystal`, `optical-grating-crystal`, `spiniform-stalagmite-crystal`)
requested as end products, refused with `InfeasibleError: no buildable recipes
reach <ore>`. Their only producers are the `*-vein` extraction recipes, which
sit in the dataset's `defaults.excludedRecipes`. A raw ore is belted in, not
built — the refusal is the correct answer and every other spec in the corpus
treats these items as external inputs. Refusals per tier are flat
(16/15/14/14/14/14/14); the two tier-0 extras are `sulfuric-acid` and
`organic-crystal`, which gain a chemical-plant and an assembler route by
tier 2.

**Proliferation is nearly recipe-set-inert.** Across the 300 cells solved under
both policies, `all-products` **never** increased machine count (median delta 0,
best -1198, 111 cells improved, 189 unchanged), and the *recipe set* changed in
only **12 of 300**. All 12 are the same artifact: with productivity spray the LP
prefers `accumulator-discharge` over building an `accumulator` from scratch,
collapsing a 12-recipe chain to 1-2 recipes. For a block library, this means the
proliferator policy is a machine-count parameter, not a topology parameter —
one block shape serves both, except around the accumulator.

---

## 4. Shared ingredients

Per item: how many distinct recipes across the corpus consume it, in how many
specs **two or more** recipes consume it at once (the number that argues for a
shared bus rather than a block), and how many internal graph edges carry it.

| Item | Consuming recipes | Specs with 2+ consumers | Edges carrying it | Depth |
| --- | ---: | ---: | ---: | ---: |
| `iron-ingot` | 24 | **514** | 1753 | 2 |
| `iron-ore` | 2 | 462 | 0 | 1 |
| `copper-ingot` | 8 | **430** | 1350 | 2 |
| `magnetic-coil` | 11 | 253 | 747 | 3 |
| `energetic-graphite` | 5 | 127 | 513 | 2 |
| `titanium-ingot` | 6 | 117 | 407 | 2 |
| `magnet` | 2 | 114 | 589 | 2 |
| `sulfuric-acid` | 2 | 81 | 0 | 1 |
| `high-purity-silicon` | 5 | 79 | 375 | 2 |
| `graphene` | 7 | 75 | 323 | 3 |
| `stone` | 3 | 70 | 0 | 1 |
| `circuit-board` | 17 | 57 | 540 | 3 |
| `hydrogen` | 6 | 43 | 80 | 1 |
| `gear` | 10 | 38 | 413 | 2 |
| `titanium-alloy` | 12 | 37 | 130 | 4 |

Two clean groups fall out:

* **Bus items** — `iron-ore`, `sulfuric-acid`, `stone`, `hydrogen` have many
  consumers but **zero internal edges**, because nothing in a blueprint produces
  them. These are belt inputs, full stop.
* **Block items** — `iron-ingot` (1753 edges), `copper-ingot` (1350),
  `magnetic-coil` (747), `magnet` (589), `circuit-board` (540) are produced
  *and* consumed inside the same spec constantly. These are where a block earns
  its keep.

`circuit-board` is the widest fan-out in the catalog (17 consuming recipes) but
only 57 specs have two consumers at once — it feeds one thing at a time, so it
wants to be produced next to its consumer, not bussed.

### Pairs: adjacency separates blocks from buses

The co-occurrence count alone is misleading. `copper-ingot + iron-ingot` appear
together in **627** specs — the highest pair in the corpus — with an **adjacency
rate of 0.000**: neither ever feeds the other. That is two parallel smelter
lines sharing a footprint, not a production chain.

Contrast the top pairs by *adjacency*, all at rate 1.000 — whenever both appear,
one always feeds the other:

| Pair | Specs | Adjacent | Rate |
| --- | ---: | ---: | ---: |
| `circuit-board` + `copper-ingot` | 490 | 490 | 1.000 |
| `circuit-board` + `iron-ingot` | 490 | 490 | 1.000 |
| `copper-ingot` + `magnetic-coil` | 475 | 475 | 1.000 |
| `magnet` + `magnetic-coil` | 475 | 475 | 1.000 |
| `gear` + `iron-ingot` | 382 | 382 | 1.000 |
| `electric-motor` + `gear` / `iron-ingot` / `magnetic-coil` | 271 | 271 | 1.000 |
| `copper-ingot` / `high-purity-silicon` + `microcrystalline-component` | 247 | 247 | 1.000 |
| `iron-ingot` + `steel` | 241 | 241 | 1.000 |

---

## 5. Ranked block candidates

All 35 closed candidates are in `mining.json` under `block_candidates`, ranked by
distinct targets served, then spec count, then size. The top 12:

| # | Block (recipes) | Specs | Share | Targets | Tiers | End | Machine range (min-max) |
| ---: | --- | ---: | ---: | ---: | --- | --- | --- |
| 1 | `copper-ingot + magnet + magnetic-coil` | 475 | 50.5% | 55 | 0-6 | trunk | 1-80 / 1-120 / 1-40 |
| 2 | `circuit-board + copper-ingot + iron-ingot` | 490 | 52.1% | 53 | 0-6 | trunk | 1-24 / 1-80 / 1-140 |
| 3 | `gear + iron-ingot` | 382 | 40.6% | 48 | 0-6 | trunk | 1-40 / 1-140 |
| 4 | `copper-ingot + electric-motor + gear + iron-ingot + magnet + magnetic-coil` | 271 | 28.8% | 38 | 1-6 | product | 1-80 / 1-80 / 1-40 / 1-140 / 1-120 / 1-40 |
| 5 | `circuit-board + copper-ingot + iron-ingot + magnet + magnetic-coil` | 330 | 35.1% | 36 | 0-6 | trunk | 1-24 / 1-80 / 1-140 / 1-68 / 1-30 |
| 6 | `energetic-graphite + graphene` | 225 | 23.9% | 35 | 1-6 | trunk | 1-165 / 1-53 |
| 7 | `iron-ingot + steel` | 241 | 25.6% | 34 | 1-6 | trunk | 1-140 / 1-60 |
| 8 | `copper-ingot + high-purity-silicon + microcrystalline-component` | 247 | 26.3% | 33 | 1-6 | trunk | 1-80 / 1-200 / 1-80 |
| 9 | `circuit-board + copper-ingot + high-purity-silicon + iron-ingot + microcrystalline-component` | 241 | 25.6% | 32 | 1-6 | trunk | 1-24 / 1-80 / 1-200 / 1-140 / 1-80 |
| 10 | `circuit-board + copper-ingot + gear + iron-ingot` | 255 | 27.1% | 31 | 0-6 | trunk | 1-24 / 1-80 / 1-27 / 1-140 |
| 11 | `circuit-board + copper-ingot + high-purity-silicon + iron-ingot + microcrystalline-component + processor` | 229 | 24.4% | 31 | 1-6 | product | 1-24 / 1-80 / 1-200 / 1-140 / 1-80 / 1-60 |
| 12 | `circuit-board + copper-ingot + gear + iron-ingot + magnet + magnetic-coil` | 202 | 21.5% | 26 | 0-6 | trunk | 1-24 / 1-80 / 1-27 / 1-140 / 1-68 / 1-30 |

Notable entries further down: `iron-ingot + steel + titanium-alloy + titanium-ingot`
(18 targets, T3-6, product end), `carbon-nanotube + energetic-graphite + graphene
+ titanium-ingot` (16 targets, T3-6), `glass + prism` (15 targets, T1-6),
`titanium-crystal + titanium-ingot` (15 targets, T2-6),
`diamond + energetic-graphite` (9 targets, T2-6),
`energetic-graphite + plasma-refining + plastic` (6 targets, T1-6),
`crystal-silicon + high-purity-silicon` (8 targets, T2-6).

The tail holds three single-purpose product blocks in which **every recipe is
pinned at exactly 1 machine across all seven tiers** —
`circuit-board+copper-ingot+iron-ingot+sorter-1` (4 targets),
`conveyor-belt-1+gear+iron-ingot` (3), and
`assembling-machine-1+circuit-board+copper-ingot+gear+iron-ingot` (3). Those are
the "starter kit" blocks: fixed-size, no parameters at all.

**Ingredient fan-in and external inputs** (`fan_in` in `mining.json`) confirm the
trunk/product split: candidates 1, 2, 3, 5, 10 draw only `iron-ore` and
`copper-ore` from outside; candidate 8 adds `silicon-ore`; candidate 6 needs
`coal` and `sulfuric-acid`; the titanium candidates need `titanium-ore` and
`sulfuric-acid`. No trunk block needs more than three external items.

### What a library would actually cover (greedy set cover)

Picking blocks in order of *newly covered* specs rather than raw frequency:

| Pick | Block | New specs | Cumulative |
| ---: | --- | ---: | ---: |
| 1 | `circuit-board + copper-ingot + iron-ingot` | 490 | **52.1%** |
| 2 | `copper-ingot + magnet + magnetic-coil` | 145 | **67.6%** |
| 3 | `diamond + energetic-graphite` | 39 | 71.7% |
| 4 | `iron-ingot + steel` | 35 | 75.4% |
| 5 | `energetic-graphite + energy-matrix` | 30 | 78.6% |
| 6 | `energetic-graphite + graphene` | 21 | 80.9% |
| 7 | `gear + iron-ingot` | 20 | 83.0% |
| 8 | `energetic-graphite + plasma-refining + plastic` | 11 | 84.1% |
| 9-13 | silicon / glass / titanium blocks | 4-6 each | 86.9% |

Two blocks reach 68%. Eight reach 84%. The curve is brutally steep and then
flat — which is the whole answer to "is a block library worth building".

---

## 6. What this suggests for a block library

**Build two blocks first.** `iron-ingot + copper-ingot + circuit-board` and
`copper-ingot + magnet + magnetic-coil` between them appear in 68% of every spec
in the corpus, at *every* tier from 0 to 6. They are the smelter-and-first-tier
block that DSP players hand-build over and over. Nothing else in the ranking is
close.

**Parametric in machine count, not in shape.** Within a single block the
topology is fixed across all 940 specs — same recipes, same edges, every time —
while machine counts move over roughly two orders of magnitude:
`iron-ingot` runs 1-45 machines for buildings at 1/min and 3-130 for matrices at
600/min; `high-purity-silicon` reaches 200. So the parameter that matters is
**per-recipe multiplicity**, and a block wants to be a tiled unit cell plus a
count, not a family of hand-drawn variants. The exception is the three
"starter kit" blocks at the tail of the ranking, which are pinned at exactly one
machine per recipe everywhere and can be fully static blueprints.

**Six rungs, not seven, and most blocks span all of them.** The white cube
unlocks no production recipe, and tiers 5 and 6 solve identically in all 188
shared cells. Of the top 12 candidates, 6 span T0-T6 and the other 6 span
T1-T6 — a block built for tier 1 is still the right block at tier 6, and every
one of the top 12 reaches the end of the ladder. Tier-specific variants are
only needed where a *better recipe* arrives, and the mining shows exactly where
that happens: titanium (T3), carbon nanotube (T3), casimir crystal (T3).
Everything before yellow cube is one library.

**Separate the bus from the block.** The single most co-occurring pair in the
corpus, `copper-ingot + iron-ingot` at 627 specs, has an adjacency rate of
**zero** — the two never feed each other. `iron-ore`, `stone`, `sulfuric-acid`
and `hydrogen` carry many consumers and *no* internal edges. So the library
needs two different artifacts: **blocks** for the high-adjacency clusters above,
and a **bus/trunk convention** for the five items (`iron-ore`, `copper-ore`,
`silicon-ore`, `stone`, `coal`) that every trunk block draws from outside.
Treating high co-occurrence as a block criterion, without the adjacency check,
would have produced exactly the wrong artifact here.

**One shape serves both proliferator policies.** `all-products` changed the
recipe set in 12 of 300 paired cells and never increased machine count. Blocks
can carry a spray flag as a rate parameter rather than a second layout — except
around `accumulator`/`accumulator-discharge`, which genuinely collapses to a
different chain and wants its own block.

---

## 7. Files

| File | What |
| --- | --- |
| `tiers.py` | Tier derivation from the dataset's technology records |
| `tiers.json` | tech / recipe / item / building / component -> tier, research costs, per-tier counts |
| `build_corpus.py` | Corpus generator |
| `corpus.tsv` | 1041 rows: tier, kind, label, target, target_tier, rate_per_min, policy, proliferator_mark, url |
| `restrictions.json` | Per-tier excluded recipes, researched technologies, machine rank, proliferator mark |
| `solve_corpus.py` | Rate solve driver |
| `solves.jsonl` | Per-row cache: recipe groups, machine counts, flow edges, external inputs, refusal reasons |
| `mine.py` | Co-occurrence, shared-ingredient and frequent-connected-subgraph mining |
| `mining.json` | `recipe_frequency`, `shared_ingredients`, `top_pairs`, `block_candidates` (35 closed), `greedy_cover` |

Reproduce, in order, from this directory:

```
uv run python tiers.py && uv run python build_corpus.py \
  && uv run python solve_corpus.py && uv run python mine.py
```

Verified reproducible: a full re-run reproduces `tiers.json`, `corpus.tsv`,
`restrictions.json` and `mining.json` byte-for-byte, and `solves.jsonl`
byte-for-byte apart from the per-row `solve_s` timings. (`mining.json` was not
reproducible on the first attempt — the `shared_ingredients` section fell
through to frozenset iteration order on tied sort keys, which
`PYTHONHASHSEED` randomises. The sort key now breaks ties on the item id.)

## 8. Caveats

* **The corpus is single-target.** Every spec asks for one item. Real saves ask
  for several at once, which would merge chains and probably raise the
  co-occurrence of the trunk blocks further. This is a floor, not an estimate.
* **Rates are canonical, not empirical.** 1/min for buildings and 60/600/min for
  matrices were chosen for comparability, not sampled from real URLs. The
  machine-count *ranges* reported are therefore ranges over this rate choice.
* **The component sweep uses only `no-proliferator`**, so the all-products
  numbers describe buildings and matrices only.
* **Subgraph enumeration stops at 6 nodes.** The closure test reads its
  extension from the spec graph so size-6 fragments of larger always-together
  clusters are correctly rejected, but a genuine 8-recipe block would be
  reported as its closed 6-node core. The largest spec has 38 groups, so larger
  blocks certainly exist.
* **Depth is a dataset-level fixpoint**, not per-spec, because the DSP recipe
  graph has real cycles (`reforming-refine` consumes and produces refined oil)
  and has no topological order.
