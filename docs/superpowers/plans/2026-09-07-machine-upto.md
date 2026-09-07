# "Up to" machine ranking: fewest machines under the URL's preferred tier

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a build option `machine_rank` with values `exact` (today's behaviour, byte-identical, and the default) and `up-to`. Under `up-to` the URL's ranked machine becomes a *ceiling* rather than a mandate: for each recipe the build uses the slowest unlocked producer that still meets the already-fixed craft rate in the same number of machines. The user's case: with a rate needing 0.8 Negentropy Smelters or 2.4 Arc Smelters, take 1 Negentropy; with a rate needing 0.5 of either, take 1 Arc and do not waste the Negentropy.

**Architecture:** Two-phase. The LP/MILP in `rates/solve.py` is untouched — it still builds exactly one column per recipe from `select_machine`, and still recovers exact craft rates. After `_exact_rates` returns and *before* `lower_bound` and `SolvedGroup` materialisation, a new pure module `rates/machine_choice.py` re-chooses one machine per non-extraction column and rebuilds that column with `adjust()`. This is sound because a machine changes only `craft_time` in `adjust()` — `inputs_per_craft` and `outputs_per_craft` are machine-invariant — so no balance row, demand row, or surplus term can move. It is *exactly* count-preserving because the ceiling is the phase-1 column's own machine and `ceil(r/s)` is non-increasing in `s`: the argmin over the ladder is always the ceiling's own count, so the MILP's integer capacity caps stay valid and the post-solve invariant at `solve.py:1322-1329` passes by construction.

**Tech Stack:** Python 3.14, `uv`, pydantic v2, `Fraction` exact arithmetic, OR-Tools (GLOP/SCIP), pytest; `web/` is TypeScript + React 19 + zod 4, tested with `@rstest/core` under `bun`.

**Spec:** This plan is its own spec — the design section below is binding. Where this plan and an evidence README disagree, the evidence README written during Task 11 wins, because it is measured.

---

## Global Constraints

Copy these into every task dispatch. They bind every task.

- **Branch/worktree.** Work in `/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/machine-upto`, branch `machine-upto`, merge base `ad8a6f80`. Never merge, push, rebase, or delete the branch. Never `git stash`. Master will move; stay on the merge base.
- **Environment check, before any test result is reported as evidence.** `uv sync`, then `uv run python -c "import flab2bp; print(flab2bp.__file__)"` must print a path **inside the worktree**. A test result from the wrong tree is not evidence.
- **Never a git command that opens an editor.** `export GIT_EDITOR=true`; always `-m` / `-F` / `--no-edit`.
- **`git diff` is wired to difftastic on this box.** Use `git diff --no-ext-diff` for patches. `git status` does not accept that flag — use plain `git status --porcelain`.
- **ONE layout build at a time from this branch.** Five other agents build on this box. Before starting an audit run, check `pgrep -fc '[s]cripts/audit\.py'`. Never `ps | grep`; `pgrep -f` with an interpreter-anchored or `[b]racketed` pattern (pgrep never matches its own PID).
- **CPU pressure** is recorded beside every timing as `vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print sum/5}'` (five-second mean of runnable processes; under 64 is fine on 128 cores). **Never** `uptime` / load average. Record it; never wait for it.
- **Serena is READ-ONLY here** (shared, last-activation-wins server; concurrent worktree agents corrupt each other's edits). Read with Serena/LSP; edit with Read/Edit/Write only. Never call `mcp__serena__activate_project`.
- **Never commit anything under `.superpowers/` or `web/dist`.** Evidence goes to `docs/superpowers/evidence/2026-09-07-machine-upto/`, any size — file size is never a reason to shrink or omit committed evidence.
- **pytest quirks.** The summary line does not print in this environment — **judge by the exit code**. `pytest-timeout` is set to 120 s as a per-test backstop and hard-kills a long run, so scope test commands to files or node ids and aggregate. `-q` is already in `addopts`.
- **`scripts/audit.py` prints `NOT CLEAN` on any refusal.** Never read the banner as a verdict; read counts and named cells from `scripts/audit_compare.py`.
- **Known reds on master `ad8a6f80`** (not caused by this branch): `tests/layout/test_sequence_pair.py::test_two_stage_alignment_retains_cp_sat_direct_opportunity`, `tests/test_pipeline.py::test_all_products_sequence_pair_honours_the_exact_layout_deadline`, and the load-flaky `tests/layout/test_strategy_race.py::test_the_real_pool_races_both_arms_end_to_end`. `universe-matrix` refuses on master today on producer-lane fan-out; that is separately planned and is not this branch's regression.
- **No `for b in buildings` scans inside loops.** Index once, look up inside.
- **Commit style.** Small imperative-subject commits; every commit's own tests pass. One commit per file where the batch touches several files of the same shape.
- **Durable record of rulings.** The SDD ledger under `.superpowers/` is gitignored and disposable. Every controller ruling must be restated in `docs/superpowers/evidence/2026-09-07-machine-upto/gate.md`, which is the record.

---

## Design

### The question this answers

`rates/adjust.py:84-98` is FactorioLab's `bestMatch`: the first ranked producer of the recipe, else `producers[0]`. It is a *mandate*. FactorioLab has no way to say "prefer the Negentropy Smelter, but do not waste one on an Arc Smelter's worth of throughput." `machine_rank=up-to` is that way.

### The semantics

Per recipe, with the craft rate the rate stage has already fixed:

1. **Ceiling.** The machine `select_machine(data, recipe, request.machine_rank_ids, override)` returns today. This is unchanged in both modes.
2. **Ladder.** Candidates are every `machine_id in recipe.producers` such that
   - `speed(machine_id) <= speed(ceiling)` (speed is `Machine.speed`, a `Fraction`; `None` means `Fraction(1)`), **and**
   - `machine_id` is unlocked by the request's technology set, by exactly the rule belt and sorter escalation uses (`lab/techs.py`: a thing is unlocked when some researched technology item lists it in `recipe_unlock`; `researched_technology_ids is None` means *everything* is unlocked), **and**
   - `machine_id` resolves in the DSP catalog (`catalog.get_item_id` does not raise) — a machine the layout cannot place must never be chosen.

   The ceiling itself is **always** admitted regardless of the last two, mirroring `techs.py`'s "the request's own belt is always included, researched or not, because FactorioLab chose it and FactorioLab's choice is authoritative." Ladder order is `(speed, index in recipe.producers)`.
3. **Choice.** For each candidate `c`, `machines(c) = ceil(craft_rate / adjust(data, recipe, c, mode, tier).crafts_per_second)` in exact `Fraction` arithmetic — the same ceil `solve.py:1289` already performs. Pick the candidate with the **fewest machines**; on a tie pick the **lowest tier** (slowest speed, then dataset order). This reproduces both of the user's examples: `ceil(0.8)=1` Negentropy vs `ceil(2.4)=3` Arc → Negentropy; `ceil(0.5)=1` for both → tie → Arc.
4. **Pins.** A recipe whose machine came from a pin (`select_machine`'s `override` argument, and the flow-pinned path in `_pinned_candidates`) is exact and is never re-chosen. A recipe with one producer is unchanged by construction.
5. **Mode.** `machine_rank` is a build option, `exact` by default so the corpus guard proves byte-identity. `exact` must be byte-identical to master, not merely equivalent.

### Corollary: `up-to` never changes a machine count

`ceil(r/s)` is non-increasing in `s`, and the ceiling has the maximum speed on its own ladder. So the argmin in step 3 is *always* attained at the ceiling, and the tie-break moves the choice to the slowest machine that ties. Therefore:

> **Invariant U.** Under `up-to`, every group's `machines` count, `crafts_per_second`, `inputs`, and `outputs` are identical to `exact`. Only `machine_item_id` changes, and only ever downward in speed.

This is what makes the two-phase design safe, and it is the sharpest available test. It also sets the honest expectation for the gate: the win is **build cost and power draw**, not machine count and (for the families that actually move) not area either — Arc/Plane/Negentropy Smelter are all 3x3, Assembling Machine Mk.I/II/III and the Re-composing Assembler are all 3x3, Chemical Plant and Quantum Chemical Plant are both 7x5, Matrix Lab and Self-evolution Lab are both 5x5. The gate therefore reports total power alongside area, or it will look like the feature did nothing.

### Why two-phase and not alternative columns in the MILP

Measured facts about `rates/solve.py` on `ad8a6f80`:

- Every balance row and demand row is built from `outputs_per_craft` / `inputs_per_craft` only (`solve.py:723-732` GLOP, `777-791` SCIP, `933-942` exact LP). Those vectors do not depend on the machine: `adjust()` changes only `craft_time = recipe.time / (speed * (1 + speed_bonus))` (`adjust.py:140`); productivity, sprays, and the per-craft input/output vectors come from the proliferator module, never the machine.
- The objective *does* depend on the machine (`_objective_coefficients` divides `per_machine` by `crafts_per_second`; `_default_objective` uses `footprint_area` and `crafts_per_second`), and so does the MILP capacity row `craft - crafts_per_second * machine <= 0` (`solve.py:779`) and the exact cap `Fraction(machines) * crafts_per_second` (`solve.py:958-965`).

Adding alternative columns per machine would let the MILP choose among them — but it would also change the **route** choice under `exact`, because the objective prices columns by `cost / crafts_per_second`, so `exact` would no longer be byte-identical without a second code path anyway. It would also multiply the column count by up to 4 on 449 of the dataset's recipes, for a decision that Invariant U proves is free.

Two-phase is chosen. Because the ceiling is the phase-1 column's own machine, the re-choice cannot violate any capacity row that phase 1 solved: the count is unchanged, and the new machine's capacity `machines * crafts_per_second` is lower but still `>= crafts_per_second` by the definition of the ceil. `solve.py`'s own post-solve invariant re-check at `1322-1329` verifies exactly that, and it runs on the rebuilt column.

The one thing two-phase gives up: the MILP's *recipe support* was chosen partly on the ranked machine's speed and footprint. Re-choosing afterwards does not revisit that. Under Invariant U the counts are equal, so the practical cost is nil; it is recorded here so a later reader does not mistake the omission for an oversight.

### Where exactly the swap happens

Inside `solve()`, after `crafts` is final and **before** the `lower_bound` computation (`solve.py:1245-1273`) and the group loop (`solve.py:1282-1307`). The swap rebuilds `columns` so that both the reported lower bound and every `SolvedGroup.adjusted`, `.area`, and the invariant re-check see one consistent machine. Under `exact` the rebuilt list is the original list, element for element, so byte-identity is structural rather than incidental.

`_ExtractionColumn` instances are never re-chosen: mining and pumping never become a `SolvedGroup` (`solve.py:1275-1281`), their counts are continuous, and `_ExtractionColumn` is identified by `isinstance` throughout — rebuilding one as a plain `AdjustedRecipe` would silently reclassify it.

### The corpus is live under this feature (checked, not assumed)

All twelve corpus URLs carry an `mmr` rank, so `up-to` is **not** corpus-inert:

| URLs | `machine_rank_ids` | what can move |
| --- | --- | --- |
| iron-ingot, magnetic-coil, graphene, electromagnetic-matrix, plastic, processor, energy-matrix, super-magnetic-ring, casimir-crystal, information-matrix | `arc-smelter, assembling-machine-2, chemical-plant, matrix-lab` | assemblers only: `assembling-machine-2` (speed 1) → `assembling-machine-1` (speed 3/4) wherever the count ties. Smelter/chemical/lab ceilings are already the slowest producer, so those families are inert. |
| quantum-chip, universe-matrix | `plane-smelter, assembling-machine-3, quantum-chemical-plant, matrix-lab` | smelters (`plane-smelter` 2 → `arc-smelter` 1), assemblers (`assembling-machine-3` 3/2 → mk2 1 → mk1 3/4), chemical (`quantum-chemical-plant` 2 → `chemical-plant` 1). |

All twelve URLs have `researched_technology_ids = None`, i.e. every technology researched, so the unlock filter is a pass-through on the corpus. It still has to exist and be tested, because a tech-restricted URL is exactly where choosing an unbuildable machine would be a real defect.

### Two things this plan deliberately does **not** fix

**Ruling D5 — the dataset default machine rank stays as it is.** When a URL carries no `mmr`, `request.machine_rank_ids` is `None` and `select_machine` falls through to `recipe.producers[0]`, the *slowest* producer. FactorioLab instead builds a default from `defaults.minMachineRank` / `defaults.maxMachineRank` selected by the `mpr` preset (which `lab/url.py:216,539` parses into `LabRequest.preset` and then nothing ever reads). This is **not** a small change and is out of scope:

- `maxMachineRank` is `('negentropy-smelter', 're-composing-assembler', 'self-evolution-lab', 'quantum-chemical-plant')` after canonicalization — honouring it flips **every** bare-URL build to Dark Fog machines, moving machine counts, footprints, belt sizing, and every snapshot and corpus that fixes them (`docs/superpowers/evidence/2026-09-06-tier-corpus/restrictions.json`, `src/flab2bp/bench/`).
- It contradicts a written standing decision at `scripts/item_sweep.py:172-183`, which chose `producers[0]` *deliberately* and defends it.
- Both rank defaults are only 4 entries covering 4 machine families, so `producers[0]` would remain the tail fallback for mining, refinery, collider and fractionator regardless.

Consequence to state plainly in the docs and the report: **on a URL with no `mmr`, `up-to` is a no-op**, because the ceiling is already the slowest producer. That is correct behaviour for this branch, and the default-rank fix is the follow-up that would make `up-to` valuable there too.

**Ruling D6 — `machine_footprint` is keyed on pre-canonicalization ids; not fixed here.** `rates/adjust.py:176-190` builds its lookup from `load_dataset()` (raw) and keys it on the raw item id, so after `canonicalize_dataset` the four Dark Fog machines (`negentropy-smelter`, `re-composing-assembler`, `self-evolution-lab`, and the `df-` turret family) miss the table and report a footprint of **0** — verified: `machine_footprint('negentropy-smelter') == 0` while `catalog` resolves it to item 2319, a 3x3 building. This biases the LP objective toward Dark Fog machines (they look free) and understates `SolvedGroup.area` / `RateSolution.total_area`. Fixing it would move the `exact` arm and break the byte-identity guard that is the point of this branch, so it is reported, not fixed. **The gate reads area from `scripts/audit.py`'s `area` field — the real placement bounding box — and never from `RateSolution.total_area`.**

---

## What is already true on master@`ad8a6f80` (do not re-derive)

| Fact | Citation |
| --- | --- |
| `select_machine` is `bestMatch`: `override` if it is a producer, else first ranked producer, else `producers[0]`. `data` is accepted and unused. No caller in `src/` passes `override`. | `src/flab2bp/rates/adjust.py:84-98` |
| Only `craft_time` depends on the machine; `inputs_per_craft`, `outputs_per_craft`, `proliferator_per_craft` do not. | `src/flab2bp/rates/adjust.py:119-163` |
| `AdjustedRecipe` fields: `recipe_id, machine_item_id, mode, tier, craft_time, inputs_per_craft, outputs_per_craft, proliferator_per_craft, proliferator_item_id`; derived `crafts_per_second`, `input_rate`, `output_rate`, `net_rate`, `proliferator_rate`, `footprint_area`. | `src/flab2bp/rates/adjust.py:42-81` |
| `_columns` builds exactly one column per reachable recipe; mode is fixed before the solve, never chosen by it. Extraction recipes become `_ExtractionColumn`. | `src/flab2bp/rates/solve.py:661-706`, `643-658` |
| The machine count is derived post-hoc by an exact ceil, not read out of the MILP: `exact = craft_rate / column.crafts_per_second; count = -((-exact.numerator) // exact.denominator)`. | `src/flab2bp/rates/solve.py:1288-1289` |
| The post-solve invariant re-check reads `group.adjusted.crafts_per_second`, so a swap must rebuild `adjusted`, not patch `machine_item_id`. | `src/flab2bp/rates/solve.py:1322-1329` |
| `InfeasibleError` at `solve.py:1187-1200` is a recipe-*reachability* failure raised before any solver runs; `machine_rank_ids` only appears in its text. `up-to` can neither cause nor cure it. | `src/flab2bp/rates/solve.py:1187-1200` |
| The unlock rule: a thing is unlocked when some technology item lists it in `recipe_unlock`; `researched is None` means everything. | `src/flab2bp/lab/techs.py:78-84` |
| `Recipe.producers` is a tuple of machine item ids in dataset order. Only 5 producer tuples in the dataset have more than one entry (labs 312 recipes, assemblers 125, smelters 14, mining 13, chemical 9). | `src/flab2bp/lab/schema.py:360,377` |
| Machine speeds (canonical ids): `arc-smelter 1`, `plane-smelter 2`, `negentropy-smelter 3`; `assembling-machine-1 3/4`, `-2 1`, `-3 3/2`, `re-composing-assembler 3`; `matrix-lab 1`, `self-evolution-lab 3`; `chemical-plant 1`, `quantum-chemical-plant 2`; `mining-machine 1`, `advanced-mining-machine 2`. | vendored `data.json`, verified |
| `MachineGroup.inputs_per_machine` is *throttled actual flow*, `group.inputs / count` — not machine capacity. | `src/flab2bp/rates/candidates.py:196-212`, `src/flab2bp/spec.py:79-107` |
| Nothing downstream of the rates stage reads `Machine.speed`. Sorter tier selection reads the derived per-machine rate (`layout/freeform.py:6135-6163`); lane capacity is a belt property. | grep over `src/` |
| Layout resolves geometry by machine *identity*: `catalog.get_item_id(mg.machine_item_id)` raises `KeyError(f"no DSP building known for machine {...!r}")` if unknown. | `src/flab2bp/layout/freeform.py:2096-2110` |
| `catalog.MODE_DRIVEN_MACHINE` pins the building for `accumulator-full/discharge`, `critical-photon`, `critical-photon-graviton` regardless of the rates stage's choice. | `src/flab2bp/dsp/catalog.py:1031-1037` |
| `lab/flow.py:1006-1017` cross-checks the built machine id and count against a supplied flow CSV and emits findings on a mismatch. | `src/flab2bp/lab/flow.py:1006-1017`, `src/flab2bp/pipeline.py:1409-1418` |
| Web `Options` is a frozen dataclass with a hand-written allowlist, parse, `Options(...)` construction, snapshot echo, and `pipeline.build` call — five separate edits, and the allowlist rejects unknown keys with a 400. | `src/flab2bp/web/jobs.py:64,203-215,274-287,313-325,399-414,584-605` |
| Web `BuildOptions` zod object is `.strict()`; the client's `Job` schema deliberately reads back only `options: { trace }`. | `web/src/api/build.ts:185-189,209-228,237-253` |
| `scripts/web_smoke.py:347-360` selects a control by **label text prefix** inside `.build-panel .options label`. A new label must not prefix an existing one. | `scripts/web_smoke.py:347-360` |
| The blueprint description line is one f-string; the extension idiom is a `_note` helper returning `""` in the default case (`_prime_note`). No test asserts this string today. | `src/flab2bp/pipeline.py:482-502,1265-1273` |
| `scripts/audit.py` has no build-option pass-through. Adding one means: `build_parser` (738-799), the `Job` dataclass (167-183), `build_jobs` (599-634), `main` (~823), `run_cell` (324-361), and the JSONL stamp in `record()` (~700). | `scripts/audit.py` |
| `scripts/audit_compare.py` takes two positional JSONL paths and has **no** `--json` flag. Cell key is `(strategy, url_id, spec_index)`. | `scripts/audit_compare.py` |

---

## File Structure

| File | Responsibility after this plan |
| --- | --- |
| `src/flab2bp/lab/techs.py` | Gains `unlocked_recipe_ids(request, dataset) -> frozenset[str]`, the one place the unlock rule lives; `logistics_tiers_for_request` calls it. |
| `src/flab2bp/rates/machine_choice.py` | **New.** `MachineRank` enum, `candidate_ladder`, `choose_machine`, `rechoose_columns`. Pure: dataset + columns + rates in, replacement columns out. No solver, no I/O. |
| `src/flab2bp/rates/solve.py` | `solve()` gains `machine_rank: MachineRank = MachineRank.EXACT` and calls `rechoose_columns` once, after `crafts` is final and before `lower_bound`. |
| `src/flab2bp/rates/candidates.py` | Threads `machine_rank` from `build_candidates` / `_build_candidates_canonical` to all four `solve(...)` call sites; `_pinned_candidates` forces `EXACT`. |
| `src/flab2bp/pipeline.py` | `build(..., machine_rank=...)`; `_machine_rank_note(...)` on the description line; carries the moved-recipe list onto the build result. |
| `src/flab2bp/cli.py` | `--machine-rank {exact,up-to}` in `build_parser`, threaded into `pipeline.build`. |
| `src/flab2bp/web/jobs.py` | `machine_rank` on `Options`, in the allowlist, in `parse_options`, in the `pipeline.build` call, and in `Builder.snapshot`. |
| `src/flab2bp/web/payload.py` | `describe()` reports `machine_rank` and `machine_moves`. |
| `web/src/api/build.ts` | `MachineRank` zod enum, `BuildOptions.machine_rank`, `DEFAULT_OPTIONS.machine_rank`, `BuildResult` fields. |
| `web/src/ui/BuildPanel.tsx` | The "Machine ranking" select. |
| `web/src/ui/BuildReport.tsx` | A "Machine ranking" row and the moved-recipe list. |
| `scripts/audit.py` | `--machine-rank` flag, `Job` field, threading, and a `machine_rank` stamp on every JSONL row. |
| `docs/superpowers/evidence/2026-09-07-machine-upto/` | **New.** `gate.md` (the record, including every controller ruling), the JSONLs, `run_round.sh`, `run_reported.sh`, `moved.md`. |

---

## Pre-flight for the executing controller

```bash
set -euo pipefail
export GIT_EDITOR=true
cd /home/dannyb/sources/factorio-lab-to-blueprint
git worktree list | grep machine-upto || \
  git worktree add -b machine-upto .claude/worktrees/machine-upto ad8a6f80
cd .claude/worktrees/machine-upto
uv sync
uv run python -c "import flab2bp; print(flab2bp.__file__)"   # MUST be inside this worktree
git rev-parse HEAD                                            # record as MERGE_BASE
pgrep -fc '[s]cripts/audit\.py' || true                       # must be 0 before any audit run
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print sum/5}'
```

Then `scripts/sdd-workspace docs/superpowers/plans/2026-09-07-machine-upto.md`, and make the ledger's first line name this plan file.

**Review batches** (one review per batch of same-shape work, one commit per file):

| Batch | Tasks | Shape |
| --- | --- | --- |
| A | 1, 2, 3 | Pure rates library: unlock set, ladder, chooser |
| B | 4, 5 | Solver and candidate wiring |
| C | 6, 7 | CLI flag and description line |
| D | 8, 9 | Web server and web UI |
| E | 10 | Audit harness flag |
| — | 11 | Gate (measured README; reviewed on its own) |
| — | 12 | Verification at HEAD, then final whole-branch review |

---

## Task 1: The unlock set becomes one named rule

**Files:**
- Modify: `src/flab2bp/lab/techs.py:65-84`
- Test: `tests/lab/test_techs.py`

**Interfaces:**
- Produces: `flab2bp.lab.techs.unlocked_recipe_ids(request: LabRequest, dataset: Dataset) -> frozenset[str]`. Task 2 consumes it.
- Consumes: nothing new.

The unlock rule currently lives inline inside `logistics_tiers_for_request`. Task 2 needs the same rule; duplicating it would let belts and machines drift apart. Extract it, and have the existing function call it so there is exactly one rule.

- [ ] **Step 1: Write the failing test**

Append to `tests/lab/test_techs.py` (create it if it does not exist; import style follows the file's neighbours):

```python
from flab2bp.lab.data import load_vendored
from flab2bp.lab.flow import canonicalize_dataset
from flab2bp.lab.techs import unlocked_recipe_ids
from flab2bp.lab.url import LabRequest


def test_no_researched_set_means_every_technology_is_unlocked() -> None:
    data = canonicalize_dataset(load_vendored())
    request = LabRequest(researched_technology_ids=None)
    unlocked = unlocked_recipe_ids(request, data)
    every = {
        unlock
        for item in data.items
        if item.technology is not None
        for unlock in item.technology.recipe_unlock
    }
    assert unlocked == every
    assert "arc-smelter" in unlocked
    assert "negentropy-smelter" in unlocked


def test_an_explicit_researched_set_unlocks_only_its_own_recipes() -> None:
    data = canonicalize_dataset(load_vendored())
    request = LabRequest(researched_technology_ids={"automatic-metallurgy"})
    unlocked = unlocked_recipe_ids(request, data)
    assert "arc-smelter" in unlocked
    assert "plane-smelter" not in unlocked
    assert "negentropy-smelter" not in unlocked


def test_an_empty_researched_set_unlocks_nothing() -> None:
    data = canonicalize_dataset(load_vendored())
    request = LabRequest(researched_technology_ids=set())
    assert unlocked_recipe_ids(request, data) == frozenset()
```

If `LabRequest` cannot be constructed with only that keyword, build it with whatever minimal keyword set the dataclass/model requires — read `src/flab2bp/lab/url.py:200-240` and use the same construction the existing tests in `tests/lab/` use. Do not change `LabRequest`.

- [ ] **Step 2: Run it and watch it fail**

```bash
uv run pytest tests/lab/test_techs.py -x
```
Expected: `ImportError: cannot import name 'unlocked_recipe_ids'`.

- [ ] **Step 3: Extract the rule**

In `src/flab2bp/lab/techs.py`, insert above `logistics_tiers_for_request`:

```python
def unlocked_recipe_ids(request: LabRequest, dataset: Dataset) -> frozenset[str]:
    """Everything this request's save can build.

    A thing is unlocked when some researched technology item lists it in
    ``recipe_unlock``.  ``None`` for the researched set means every
    technology, as :func:`belt_rules_for_url` documents -- FactorioLab's
    ``settings-store.ts`` defaults an absent set to the full technology list,
    not to the empty one.

    Belts, sorters, and (under ``machine_rank=up-to``) machine candidates all
    gate on this one set, so that a save which cannot build a Plane Smelter
    cannot be handed one by any of them.
    """
    researched = request.researched_technology_ids
    unlocked: set[str] = set()
    for item in dataset.items:
        if item.technology is None:
            continue
        if researched is None or item.id in researched:
            unlocked.update(item.technology.recipe_unlock)
    return frozenset(unlocked)
```

Then replace the inline loop in `logistics_tiers_for_request` (the `technology_items = ...` through the `unlocked.update(...)` loop, `techs.py:78-84`) with:

```python
    unlocked = unlocked_recipe_ids(request, dataset)
```

Leave the rest of `logistics_tiers_for_request` untouched. `unlocked` is used only with `in` afterwards, so a `frozenset` is a drop-in.

- [ ] **Step 4: Run the new tests and the belt/sorter tests**

```bash
uv run pytest tests/lab/test_techs.py -x
uv run pytest tests/lab -x
uv run pytest tests/rates -x
```
Expected: all pass (exit 0). The belt/sorter behaviour must be unchanged — this is a pure extraction.

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

- [ ] **Step 6: Commit**

```bash
git add src/flab2bp/lab/techs.py tests/lab/test_techs.py
git commit -m "refactor(techs): name the unlock rule as unlocked_recipe_ids"
```

---

## Task 2: The candidate ladder

**Files:**
- Create: `src/flab2bp/rates/machine_choice.py`
- Create: `tests/rates/test_machine_choice.py`

**Interfaces:**
- Consumes: `flab2bp.lab.techs.unlocked_recipe_ids` (Task 1).
- Produces:
  - `class MachineRank(StrEnum): EXACT = "exact"; UP_TO = "up-to"`
  - `def machine_speed(data: Dataset, machine_item_id: str) -> Fraction`
  - `def candidate_ladder(data: Dataset, recipe: Recipe, ceiling_id: str, unlocked: Collection[str]) -> tuple[str, ...]`

  Task 3 consumes `candidate_ladder` and `machine_speed`; Tasks 4-10 consume `MachineRank`.

- [ ] **Step 1: Write the failing tests**

Create `tests/rates/test_machine_choice.py`:

```python
from fractions import Fraction

import pytest

from flab2bp.lab.data import load_vendored
from flab2bp.lab.flow import canonicalize_dataset
from flab2bp.rates.machine_choice import MachineRank, candidate_ladder, machine_speed


@pytest.fixture(scope="module")
def data():
    return canonicalize_dataset(load_vendored())


ALL_UNLOCKED = None  # sentinel replaced in each test by the full unlock set


def _every_machine(data) -> frozenset[str]:
    return frozenset(item.id for item in data.items if item.machine is not None)


def test_the_mode_values_are_the_cli_spelling() -> None:
    assert MachineRank.EXACT.value == "exact"
    assert MachineRank.UP_TO.value == "up-to"
    assert [m.value for m in MachineRank] == ["exact", "up-to"]


def test_speed_of_a_machine_without_one_is_one(data) -> None:
    assert machine_speed(data, "arc-smelter") == Fraction(1)
    assert machine_speed(data, "plane-smelter") == Fraction(2)
    assert machine_speed(data, "negentropy-smelter") == Fraction(3)
    assert machine_speed(data, "assembling-machine-1") == Fraction(3, 4)


def test_the_ladder_under_the_top_smelter_is_every_smelter_slowest_first(data) -> None:
    recipe = data.recipe("iron-ingot")
    ladder = candidate_ladder(data, recipe, "negentropy-smelter", _every_machine(data))
    assert ladder == ("arc-smelter", "plane-smelter", "negentropy-smelter")


def test_the_ladder_stops_at_the_ceiling(data) -> None:
    recipe = data.recipe("iron-ingot")
    assert candidate_ladder(data, recipe, "plane-smelter", _every_machine(data)) == (
        "arc-smelter",
        "plane-smelter",
    )
    assert candidate_ladder(data, recipe, "arc-smelter", _every_machine(data)) == ("arc-smelter",)


def test_the_ladder_is_ordered_by_speed_then_dataset_order(data) -> None:
    recipe = data.recipe("tesla-tower")
    ladder = candidate_ladder(data, recipe, "re-composing-assembler", _every_machine(data))
    assert ladder == (
        "assembling-machine-1",
        "assembling-machine-2",
        "assembling-machine-3",
        "re-composing-assembler",
    )
    speeds = [machine_speed(data, m) for m in ladder]
    assert speeds == sorted(speeds)


def test_a_locked_machine_is_not_a_candidate(data) -> None:
    recipe = data.recipe("iron-ingot")
    ladder = candidate_ladder(data, recipe, "negentropy-smelter", {"arc-smelter"})
    assert ladder == ("arc-smelter", "negentropy-smelter")


def test_the_ceiling_is_always_admitted_even_when_locked(data) -> None:
    recipe = data.recipe("iron-ingot")
    assert candidate_ladder(data, recipe, "plane-smelter", frozenset()) == ("plane-smelter",)


def test_a_single_producer_recipe_has_a_one_entry_ladder(data) -> None:
    recipe = next(r for r in data.recipes if len(r.producers) == 1)
    ceiling = recipe.producers[0]
    assert candidate_ladder(data, recipe, ceiling, _every_machine(data)) == (ceiling,)


def test_every_ladder_entry_is_placeable(data) -> None:
    from flab2bp.dsp import catalog

    every = _every_machine(data)
    for recipe in data.recipes:
        if len(recipe.producers) < 2:
            continue
        for machine_id in candidate_ladder(data, recipe, recipe.producers[-1], every):
            catalog.get_item_id(machine_id)  # must not raise
```

- [ ] **Step 2: Run them and watch them fail**

```bash
uv run pytest tests/rates/test_machine_choice.py -x
```
Expected: `ModuleNotFoundError: No module named 'flab2bp.rates.machine_choice'`.

- [ ] **Step 3: Write the module**

Create `src/flab2bp/rates/machine_choice.py`:

```python
"""Choosing a machine when the URL's rank is a ceiling rather than a mandate.

FactorioLab's machine rank is a mandate: ``select_machine`` takes the first
ranked producer and builds every machine of that recipe out of it, even when
the rate needs a fraction of one.  ``MachineRank.UP_TO`` reads the same rank
as a ceiling and takes the slowest producer that still meets the already-fixed
rate in the same number of machines.

The arithmetic is exact and the ceiling is the rank's own machine, so the
choice can never need MORE machines than ``exact`` does: ``ceil(r / s)`` is
non-increasing in ``s`` and the ceiling has the greatest speed on its own
ladder.  Only the building placed changes, and only ever downward.
"""

from __future__ import annotations

from collections.abc import Collection
from enum import StrEnum
from fractions import Fraction

from flab2bp.dsp import catalog
from flab2bp.lab.schema import Dataset, Recipe


class MachineRank(StrEnum):
    """How the URL's machine rank is read."""

    #: FactorioLab's ``bestMatch``: the ranked machine, always.
    EXACT = "exact"
    #: The ranked machine is a ceiling; take the slowest producer that ties.
    UP_TO = "up-to"


def machine_speed(data: Dataset, machine_item_id: str) -> Fraction:
    """A machine's crafting speed, with ``None`` read as 1.

    ``adjust()`` makes the same substitution; keeping it in one named
    function stops the two from disagreeing about a machine whose speed the
    dataset omits.
    """
    machine = data.machine(machine_item_id)
    return machine.speed if machine.speed is not None else Fraction(1)


def _is_placeable(machine_item_id: str) -> bool:
    """Whether the layout stage could place this machine.

    ``layout/freeform.py`` resolves a group's machine through
    ``catalog.get_item_id`` and raises when it cannot.  A candidate the
    layout cannot place is not a candidate.
    """
    try:
        catalog.get_item_id(machine_item_id)
    except (KeyError, ValueError):
        return False
    return True


def candidate_ladder(
    data: Dataset,
    recipe: Recipe,
    ceiling_id: str,
    unlocked: Collection[str],
) -> tuple[str, ...]:
    """The producers of ``recipe`` at or below ``ceiling_id``, slowest first.

    A producer qualifies when it is no faster than the ceiling, the save has
    unlocked it, and the DSP catalog can place it.  The ceiling itself is
    always admitted regardless -- mirroring the belt rule in
    ``lab/techs.py``, where the request's own belt is included researched or
    not, because FactorioLab chose it and FactorioLab's choice is
    authoritative.

    Ordered by ``(speed, position in recipe.producers)`` so the tie-break in
    :func:`choose_machine` is "lowest tier, then dataset order" by
    construction rather than by a second sort.
    """
    ceiling_speed = machine_speed(data, ceiling_id)
    ladder: list[tuple[Fraction, int, str]] = []
    for index, machine_id in enumerate(recipe.producers):
        if machine_id == ceiling_id:
            ladder.append((ceiling_speed, index, machine_id))
            continue
        if machine_id not in unlocked:
            continue
        if not _is_placeable(machine_id):
            continue
        speed = machine_speed(data, machine_id)
        if speed > ceiling_speed:
            continue
        ladder.append((speed, index, machine_id))
    ladder.sort()
    return tuple(machine_id for _, _, machine_id in ladder)
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/rates/test_machine_choice.py -x
```
Expected: exit 0.

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

- [ ] **Step 6: Commit**

```bash
git add src/flab2bp/rates/machine_choice.py tests/rates/test_machine_choice.py
git commit -m "feat(rates): candidate machine ladder under a speed ceiling"
```

---

## Task 3: The chooser

**Files:**
- Modify: `src/flab2bp/rates/machine_choice.py`
- Modify: `tests/rates/test_machine_choice.py`

**Interfaces:**
- Consumes: `candidate_ladder`, `machine_speed` (Task 2); `flab2bp.rates.adjust.adjust`.
- Produces:
  - `def machines_needed(craft_rate: Fraction, crafts_per_second: Fraction) -> int`
  - `def choose_machine(data, recipe, *, ceiling_id, craft_rate, mode, tier, unlocked) -> str`

  Task 4 consumes `choose_machine` through `rechoose_columns`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/rates/test_machine_choice.py`:

```python
from flab2bp.lab.schema import ProliferatorMode, ProliferatorTier
from flab2bp.rates.adjust import adjust
from flab2bp.rates.machine_choice import choose_machine, machines_needed


def _choose(data, recipe_id: str, ceiling: str, craft_rate: Fraction) -> str:
    return choose_machine(
        data,
        data.recipe(recipe_id),
        ceiling_id=ceiling,
        craft_rate=craft_rate,
        mode=ProliferatorMode.NONE,
        tier=ProliferatorTier.NONE,
        unlocked=_every_machine(data),
    )


def test_machines_needed_is_an_exact_ceiling() -> None:
    assert machines_needed(Fraction(1, 2), Fraction(1)) == 1
    assert machines_needed(Fraction(5, 2), Fraction(1)) == 3
    assert machines_needed(Fraction(3), Fraction(1)) == 3
    assert machines_needed(Fraction(0), Fraction(1)) == 0
    # 0.1 is not representable in binary floating point; the exact form is.
    assert machines_needed(Fraction(1, 10) * 10, Fraction(1)) == 1


def test_a_rate_only_the_top_smelter_meets_in_one_machine_keeps_it(data) -> None:
    # iron-ingot: time 1s, out 1.  arc 1/s, plane 2/s, negentropy 3/s.
    # 2.4 crafts/s -> arc ceil(2.4)=3, plane ceil(1.2)=2, negentropy ceil(0.8)=1.
    assert _choose(data, "iron-ingot", "negentropy-smelter", Fraction(12, 5)) == (
        "negentropy-smelter"
    )


def test_a_rate_the_bottom_smelter_also_meets_in_one_machine_drops_to_it(data) -> None:
    # 0.5 crafts/s -> every smelter needs ceil(<=0.5) == 1; tie -> lowest tier.
    assert _choose(data, "iron-ingot", "negentropy-smelter", Fraction(1, 2)) == "arc-smelter"


def test_a_tie_between_the_middle_and_the_top_takes_the_middle(data) -> None:
    # 1.5 crafts/s -> arc 2, plane 1, negentropy 1.  Tie between plane and
    # negentropy at 1; the slower one wins.
    assert _choose(data, "iron-ingot", "negentropy-smelter", Fraction(3, 2)) == "plane-smelter"


def test_the_ceiling_bounds_the_choice_from_above(data) -> None:
    # With an arc-smelter ceiling nothing faster may be chosen, even though
    # a faster smelter would need fewer machines.
    assert _choose(data, "iron-ingot", "arc-smelter", Fraction(12, 5)) == "arc-smelter"


def test_a_locked_save_cannot_be_handed_a_machine_it_has_not_researched(data) -> None:
    chosen = choose_machine(
        data,
        data.recipe("iron-ingot"),
        ceiling_id="negentropy-smelter",
        craft_rate=Fraction(1, 2),
        mode=ProliferatorMode.NONE,
        tier=ProliferatorTier.NONE,
        unlocked=frozenset({"plane-smelter"}),
    )
    assert chosen == "plane-smelter"


def test_the_choice_never_needs_more_machines_than_the_ceiling(data) -> None:
    """Invariant U: up-to is exactly count-preserving."""
    every = _every_machine(data)
    checked = 0
    for recipe in data.recipes:
        if len(recipe.producers) < 2:
            continue
        ceiling = recipe.producers[-1]
        if not _is_placeable_for_test(ceiling):
            continue
        for numerator in (1, 2, 3, 5, 7, 11, 23, 97):
            for denominator in (1, 2, 3, 4, 10):
                rate = Fraction(numerator, denominator)
                chosen = choose_machine(
                    data,
                    recipe,
                    ceiling_id=ceiling,
                    craft_rate=rate,
                    mode=ProliferatorMode.NONE,
                    tier=ProliferatorTier.NONE,
                    unlocked=every,
                )
                before = machines_needed(
                    rate, adjust(data, recipe, ceiling).crafts_per_second
                )
                after = machines_needed(
                    rate, adjust(data, recipe, chosen).crafts_per_second
                )
                assert after == before, (recipe.id, ceiling, chosen, rate)
                checked += 1
    assert checked > 1000


def _is_placeable_for_test(machine_id: str) -> bool:
    from flab2bp.dsp import catalog

    try:
        catalog.get_item_id(machine_id)
    except (KeyError, ValueError):
        return False
    return True
```

Note: if `ProliferatorMode` / `ProliferatorTier` are exported from a different module, import them from wherever `tests/rates/test_adjust.py` imports them; do not move them.

- [ ] **Step 2: Run them and watch them fail**

```bash
uv run pytest tests/rates/test_machine_choice.py -x
```
Expected: `ImportError: cannot import name 'choose_machine'`.

- [ ] **Step 3: Implement**

Append to `src/flab2bp/rates/machine_choice.py` (and add `from flab2bp.rates.adjust import adjust` plus the mode/tier imports at the top):

```python
def machines_needed(craft_rate: Fraction, crafts_per_second: Fraction) -> int:
    """Exact ceiling of ``craft_rate / crafts_per_second``.

    The same expression ``solve.py`` uses to turn an exact rate into a
    physical count.  Kept exact: at 0.1 crafts/s a float ceiling rounds the
    wrong way often enough to move a real build.
    """
    exact = craft_rate / crafts_per_second
    return -((-exact.numerator) // exact.denominator)


def choose_machine(
    data: Dataset,
    recipe: Recipe,
    *,
    ceiling_id: str,
    craft_rate: Fraction,
    mode: ProliferatorMode,
    tier: ProliferatorTier,
    unlocked: Collection[str],
) -> str:
    """The slowest producer that meets ``craft_rate`` in the fewest machines.

    Fewest machines first, then lowest tier.  Because
    :func:`candidate_ladder` is already ordered ``(speed, dataset order)``
    and ``min`` is stable, the first candidate attaining the minimum count is
    the lowest-tier one, which is the tie-break the design asks for.

    ``mode`` and ``tier`` are the column's own -- a proliferator speed bonus
    scales every candidate equally, but the ceiling is nonlinear, so each
    candidate is measured through ``adjust()`` rather than by scaling.
    """
    ladder = candidate_ladder(data, recipe, ceiling_id, unlocked)
    if len(ladder) == 1:
        return ladder[0]
    best_id = ceiling_id
    best_count: int | None = None
    for machine_id in ladder:
        count = machines_needed(
            craft_rate, adjust(data, recipe, machine_id, mode, tier).crafts_per_second
        )
        if best_count is None or count < best_count:
            best_count = count
            best_id = machine_id
    return best_id
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/rates/test_machine_choice.py -x
```
Expected: exit 0. The invariant test is the important one; if it fails, the ladder ordering or the ceiling rule is wrong — do not weaken the test.

- [ ] **Step 5: Lint and type-check**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

- [ ] **Step 6: Commit**

```bash
git add src/flab2bp/rates/machine_choice.py tests/rates/test_machine_choice.py
git commit -m "feat(rates): choose the slowest machine that ties on count"
```

> **REVIEW BATCH A ends here** (Tasks 1-3). Dispatch `scripts/review-package` over `MERGE_BASE..HEAD` before starting Task 4.

---

## Task 4: Two-phase re-choice inside `solve()`

**Files:**
- Modify: `src/flab2bp/rates/machine_choice.py` (add `rechoose_columns`)
- Modify: `src/flab2bp/rates/solve.py` (`solve` signature; one call before `lower_bound`)
- Modify: `tests/rates/test_machine_choice.py`
- Test: `tests/rates/test_solve.py` (append)

**Interfaces:**
- Consumes: `choose_machine` (Task 3).
- Produces:
  - `def rechoose_columns(data, request, columns, crafts, *, machine_rank, tier, pinned) -> tuple[list[AdjustedRecipe], tuple[MachineMove, ...]]`
  - `@dataclass(frozen=True, slots=True) class MachineMove: recipe_id: str; from_machine: str; to_machine: str; count_before: int; count_after: int`
  - `solve(..., machine_rank: MachineRank = MachineRank.EXACT)` and `RateSolution.machine_moves: tuple[MachineMove, ...]`

  Task 5 consumes the `solve` keyword; Tasks 7-9 consume `MachineMove`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/rates/test_machine_choice.py`:

```python
def test_exact_returns_the_very_same_column_objects(data) -> None:
    """Byte-identity is structural: `exact` must not rebuild anything."""
    from flab2bp.rates.machine_choice import rechoose_columns

    columns = [adjust(data, data.recipe("iron-ingot"), "negentropy-smelter")]
    crafts = [Fraction(1, 2)]
    out, moves = rechoose_columns(
        data,
        _request_all_techs(),
        columns,
        crafts,
        machine_rank=MachineRank.EXACT,
        tier=ProliferatorTier.NONE,
        pinned=frozenset(),
    )
    assert out is columns or out == columns
    assert all(a is b for a, b in zip(out, columns, strict=True))
    assert moves == ()


def test_up_to_rebuilds_only_the_columns_that_moved(data) -> None:
    from flab2bp.rates.machine_choice import rechoose_columns

    columns = [adjust(data, data.recipe("iron-ingot"), "negentropy-smelter")]
    out, moves = rechoose_columns(
        data,
        _request_all_techs(),
        columns,
        [Fraction(1, 2)],
        machine_rank=MachineRank.UP_TO,
        tier=ProliferatorTier.NONE,
        pinned=frozenset(),
    )
    assert out[0].machine_item_id == "arc-smelter"
    assert out[0].inputs_per_craft == columns[0].inputs_per_craft
    assert out[0].outputs_per_craft == columns[0].outputs_per_craft
    assert [
        (m.recipe_id, m.from_machine, m.to_machine, m.count_before, m.count_after)
        for m in moves
    ] == [("iron-ingot", "negentropy-smelter", "arc-smelter", 1, 1)]


def test_a_zero_rate_column_is_never_rechosen(data) -> None:
    from flab2bp.rates.machine_choice import rechoose_columns

    columns = [adjust(data, data.recipe("iron-ingot"), "negentropy-smelter")]
    out, moves = rechoose_columns(
        data,
        _request_all_techs(),
        columns,
        [Fraction(0)],
        machine_rank=MachineRank.UP_TO,
        tier=ProliferatorTier.NONE,
        pinned=frozenset(),
    )
    assert out[0] is columns[0]
    assert moves == ()


def test_a_pinned_recipe_is_never_rechosen(data) -> None:
    from flab2bp.rates.machine_choice import rechoose_columns

    columns = [adjust(data, data.recipe("iron-ingot"), "negentropy-smelter")]
    out, moves = rechoose_columns(
        data,
        _request_all_techs(),
        columns,
        [Fraction(1, 2)],
        machine_rank=MachineRank.UP_TO,
        tier=ProliferatorTier.NONE,
        pinned=frozenset({"iron-ingot"}),
    )
    assert out[0] is columns[0]
    assert moves == ()
```

`_request_all_techs()` is a helper in the same file returning a `LabRequest` with `researched_technology_ids=None`, built the way Task 1's tests build one.

Append to `tests/rates/test_solve.py`:

```python
def test_up_to_downgrades_a_smelter_without_changing_counts_or_flows() -> None:
    """The whole solve, both arms, on one URL whose rank tops the smelters."""
    from flab2bp.lab.data import load_vendored
    from flab2bp.lab.flow import canonicalize_dataset, canonicalize_request
    from flab2bp.lab.url import parse_url
    from flab2bp.rates.machine_choice import MachineRank
    from flab2bp.rates.solve import solve

    data = canonicalize_dataset(load_vendored())
    request = canonicalize_request(parse_url(_SMELTER_CEILING_URL))
    exact = solve(data, request, machine_rank=MachineRank.EXACT)
    up_to = solve(data, request, machine_rank=MachineRank.UP_TO)

    assert exact.machine_moves == ()
    assert {g.recipe_id: g.machines for g in up_to.groups} == {
        g.recipe_id: g.machines for g in exact.groups
    }
    assert {g.recipe_id: dict(g.outputs) for g in up_to.groups} == {
        g.recipe_id: dict(g.outputs) for g in exact.groups
    }
    moved = {m.recipe_id: (m.from_machine, m.to_machine) for m in up_to.machine_moves}
    assert moved, "the fixture URL must actually move something"
    for group in up_to.groups:
        if group.recipe_id in moved:
            assert group.machine_item_id == moved[group.recipe_id][1]
            assert group.adjusted.machine_item_id == group.machine_item_id
```

`_SMELTER_CEILING_URL` is the `quantum-chip` corpus URL — `from flab2bp.bench.corpus import URL_CORPUS` and take the entry whose `url_id == "quantum-chip"`; its rank is `plane-smelter, assembling-machine-3, quantum-chemical-plant, matrix-lab`, so both the smelter and the assembler families have room to move. If that solve is too slow for a unit test, use `graphene` (rank tops out at `assembling-machine-2`, so only assemblers move) and keep the assertion that `moved` is non-empty.

- [ ] **Step 2: Run them and watch them fail**

```bash
uv run pytest tests/rates/test_machine_choice.py tests/rates/test_solve.py -x
```
Expected: `ImportError: cannot import name 'rechoose_columns'`.

- [ ] **Step 3: Add `MachineMove` and `rechoose_columns`**

Append to `src/flab2bp/rates/machine_choice.py`:

```python
@dataclass(frozen=True, slots=True)
class MachineMove:
    """One recipe whose machine the ``up-to`` rule moved down a tier."""

    recipe_id: str
    from_machine: str
    to_machine: str
    count_before: int
    count_after: int


def rechoose_columns(
    data: Dataset,
    request: LabRequest,
    columns: Sequence[AdjustedRecipe],
    crafts: Sequence[Fraction],
    *,
    machine_rank: MachineRank,
    tier: ProliferatorTier,
    pinned: Collection[str] = (),
) -> tuple[list[AdjustedRecipe], tuple[MachineMove, ...]]:
    """Phase two: re-choose one machine per column against the fixed rates.

    Returns the columns to use from here on and the moves that were made.
    Under :attr:`MachineRank.EXACT` the input list is returned unchanged --
    identity, not equality -- so the default arm cannot drift.

    A column is left alone when it produces nothing (rate 0), when its
    recipe is pinned by a supplied flow, or when it is an extraction column:
    mining and pumping never become a ``SolvedGroup``, their counts are
    continuous, and ``_ExtractionColumn`` is identified by ``isinstance``
    everywhere, so rebuilding one as a plain ``AdjustedRecipe`` would
    silently reclassify it.
    """
    if machine_rank is MachineRank.EXACT:
        return list(columns), ()

    unlocked = unlocked_recipe_ids(request, data)
    out: list[AdjustedRecipe] = []
    moves: list[MachineMove] = []
    for column, craft_rate in zip(columns, crafts, strict=True):
        if craft_rate <= 0 or type(column) is not AdjustedRecipe:
            out.append(column)
            continue
        if column.recipe_id in pinned:
            out.append(column)
            continue
        recipe = data.recipe(column.recipe_id)
        chosen = choose_machine(
            data,
            recipe,
            ceiling_id=column.machine_item_id,
            craft_rate=craft_rate,
            mode=column.mode,
            tier=tier,
            unlocked=unlocked,
        )
        if chosen == column.machine_item_id:
            out.append(column)
            continue
        replacement = adjust(data, recipe, chosen, column.mode, tier)
        moves.append(
            MachineMove(
                recipe_id=column.recipe_id,
                from_machine=column.machine_item_id,
                to_machine=chosen,
                count_before=machines_needed(craft_rate, column.crafts_per_second),
                count_after=machines_needed(craft_rate, replacement.crafts_per_second),
            )
        )
        out.append(replacement)
    moves.sort(key=lambda move: move.recipe_id)
    return out, tuple(moves)
```

`type(column) is not AdjustedRecipe` — not `isinstance` — is deliberate: it is the exact test that excludes the `_ExtractionColumn` subclass while admitting plain columns. Add a comment saying so.

Imports to add at the top of the module: `from dataclasses import dataclass`, `from collections.abc import Collection, Sequence`, `from flab2bp.lab.techs import unlocked_recipe_ids`, `from flab2bp.lab.url import LabRequest`, `from flab2bp.rates.adjust import AdjustedRecipe, adjust`, and the proliferator mode/tier imports. If importing `flab2bp.lab.techs` from `flab2bp.rates` creates a cycle, move the import inside `rechoose_columns` and say why in a comment.

- [ ] **Step 4: Wire it into `solve()`**

In `src/flab2bp/rates/solve.py`:

1. Add to the keyword-only block of `solve` (`solve.py:1120-1130`), after `prove_minimal`:

```python
    machine_rank: MachineRank = MachineRank.EXACT,
    pinned_machines: frozenset[str] = frozenset(),
```

2. Extend the docstring with one paragraph:

```
    ``machine_rank`` selects how the URL's machine rank is read.  ``EXACT``
    is FactorioLab's ``bestMatch`` and is byte-identical to not passing it.
    ``UP_TO`` reads the rank as a ceiling and, once the rates are final,
    re-chooses each recipe's machine as the slowest producer that meets that
    rate in the same number of machines.  The re-choice happens after the
    solve because the machine changes only ``craft_time``: the per-craft
    input and output vectors every balance row is built from do not move, so
    no rate the solve fixed can become infeasible.  ``pinned_machines`` names
    recipes whose machine a supplied flow already fixed; they are never
    re-chosen.
```

3. Immediately after the block that finalises `crafts` (i.e. after the `if used_milp:` block ending with the `crafts = _exact_rates(...)` assignment, `solve.py:~1243`) and **before** `geometric_objective = _default_objective(columns)`:

```python
    columns, machine_moves = rechoose_columns(
        data,
        request,
        columns,
        crafts,
        machine_rank=machine_rank,
        tier=tier,
        pinned=pinned_machines,
    )
```

Placing it here means the reported lower bound, every `SolvedGroup.adjusted`, `SolvedGroup.area`, and the capacity re-check at `solve.py:1322-1329` all see one consistent machine. Add that sentence as a comment above the call.

4. Add `machine_moves: tuple[MachineMove, ...] = ()` to `RateSolution` (follow the dataclass's existing field style; it must default to `()` so every existing construction site keeps working) and pass `machine_moves=machine_moves` where `RateSolution` is constructed at the end of `solve`.

5. Import at the top of `solve.py`: `from flab2bp.rates.machine_choice import MachineMove, MachineRank, rechoose_columns`.

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/rates -x
```
Expected: exit 0.

- [ ] **Step 6: Prove `exact` is byte-identical at the spec boundary**

```bash
uv run python - <<'PY'
import hashlib, json
from flab2bp.bench.corpus import URL_CORPUS
from flab2bp.lab.data import load_vendored
from flab2bp.lab.flow import canonicalize_dataset, canonicalize_request
from flab2bp.lab.url import parse_url
from flab2bp.rates.machine_choice import MachineRank
from flab2bp.rates.solve import solve

data = canonicalize_dataset(load_vendored())
for entry in URL_CORPUS:
    request = canonicalize_request(parse_url(entry.url))
    a = solve(data, request)
    b = solve(data, request, machine_rank=MachineRank.EXACT)
    key = lambda s: json.dumps(
        sorted((g.recipe_id, g.machine_item_id, g.machines, str(g.crafts_per_second))
               for g in s.groups)
    )
    assert key(a) == key(b), entry.url_id
    print(f"{entry.url_id:24s} identical  groups={len(a.groups)}")
PY
```
Every line must print `identical`. Save the output to `docs/superpowers/evidence/2026-09-07-machine-upto/task4-exact-identity.txt` and `git add` it.

- [ ] **Step 7: Lint and type-check**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

- [ ] **Step 8: Commit**

```bash
git add src/flab2bp/rates/machine_choice.py src/flab2bp/rates/solve.py \
        tests/rates/test_machine_choice.py tests/rates/test_solve.py \
        docs/superpowers/evidence/2026-09-07-machine-upto/task4-exact-identity.txt
git commit -m "feat(rates): re-choose machines under an up-to ceiling after the solve"
```

---

## Task 5: Thread `machine_rank` from `pipeline.build` to `solve`

**Files:**
- Modify: `src/flab2bp/rates/candidates.py` (`build_candidates`, `_build_candidates_canonical`, `_pinned_candidates`, and the four `solve(...)` call sites at `424`, `535`, `563`, `571`)
- Modify: `src/flab2bp/pipeline.py` (`build` signature ~`636-703`; the `_build_candidates_canonical` call ~`802-808`)
- Modify: `src/flab2bp/spec.py` (`BuildSpec` gains `machine_rank` and `machine_moves`)
- Modify: `src/flab2bp/layout/hierarchy/partition.py:329,429` (copy the new fields into both synthesized sub-specs — `BuildSpec` is `extra="forbid"`, so a missing copy silently reverts them)
- Test: `tests/rates/test_candidates.py`, `tests/test_spec.py`, `tests/layout/hierarchy/test_partition.py`

**Interfaces:**
- Consumes: `solve(..., machine_rank=, pinned_machines=)` (Task 4).
- Produces: `pipeline.build(..., machine_rank: MachineRank = MachineRank.EXACT)`; `BuildSpec.machine_rank: str = "exact"`; `BuildSpec.machine_moves: tuple[MachineMoveRecord, ...] = ()`. Tasks 6-10 consume these.

`BuildSpec` is frozen pydantic with `extra="forbid"`, so `machine_moves` cannot hold the `MachineMove` dataclass directly unless pydantic accepts it. Define a small pydantic model in `spec.py`:

```python
class MachineMoveRecord(_Frozen):
    """One recipe the ``up-to`` rule moved to a lower-tier machine."""

    recipe_id: str
    from_machine: str
    to_machine: str
    count_before: int = Field(gt=0)
    count_after: int = Field(gt=0)
```

- [ ] **Step 1: Write the failing tests**

In `tests/test_spec.py`:

```python
def test_a_spec_defaults_to_exact_machine_ranking() -> None:
    spec = _minimal_spec()          # reuse whatever helper this file already has
    assert spec.machine_rank == "exact"
    assert spec.machine_moves == ()


def test_a_spec_rejects_an_unknown_machine_rank() -> None:
    with pytest.raises(ValidationError, match="machine_rank"):
        _minimal_spec(machine_rank="whatever")
```

In `tests/rates/test_candidates.py`:

```python
def test_up_to_reaches_the_spec_and_records_its_moves() -> None:
    from flab2bp.rates.machine_choice import MachineRank

    data, request = _corpus("quantum-chip")   # reuse this file's existing helper
    exact = build_candidates(data, request, machine_rank=MachineRank.EXACT)
    up_to = build_candidates(data, request, machine_rank=MachineRank.UP_TO)
    for spec in exact.specs:
        assert spec.machine_rank == "exact"
        assert spec.machine_moves == ()
    assert any(spec.machine_moves for spec in up_to.specs)
    for spec in up_to.specs:
        assert spec.machine_rank == "up-to"
        for move in spec.machine_moves:
            assert move.count_before == move.count_after
    assert {s.label: s.machine_count for s in up_to.specs} == {
        s.label: s.machine_count for s in exact.specs
    }


def test_a_supplied_flow_pins_the_machine_even_under_up_to() -> None:
    from flab2bp.rates.machine_choice import MachineRank

    data, request, flow = _flow_fixture()     # reuse this file's existing helper
    pinned = build_candidates(data, request, machine_rank=MachineRank.UP_TO, flow=flow)
    for spec in pinned.specs:
        assert spec.machine_moves == ()
```

If `tests/rates/test_candidates.py` has no `_corpus` / `_flow_fixture` helper, write the smallest one that loads the corpus entry and a flow fixture from `tests/fixtures/`, following the construction the neighbouring tests already use.

- [ ] **Step 2: Run them and watch them fail**

```bash
uv run pytest tests/test_spec.py tests/rates/test_candidates.py -x
```

- [ ] **Step 3: Add the spec fields**

In `src/flab2bp/spec.py`, add `MachineMoveRecord` above `BuildSpec`, then to `BuildSpec` (beside `sorter_item_ids`, `spec.py:196-198`):

```python
    #: How the URL's machine rank was read: ``exact`` (FactorioLab's
    #: ``bestMatch``) or ``up-to`` (the rank as a ceiling).  Defaults to
    #: ``exact`` so a spec built without a request keeps today's behaviour.
    machine_rank: str = "exact"
    #: Under ``up-to``, every recipe whose machine moved down a tier.
    machine_moves: tuple[MachineMoveRecord, ...] = ()

    @field_validator("machine_rank")
    @classmethod
    def _known_machine_rank(cls, value: str) -> str:
        from flab2bp.rates.machine_choice import MachineRank

        allowed = tuple(rank.value for rank in MachineRank)
        if value not in allowed:
            raise ValueError(
                f"machine_rank must be one of {', '.join(allowed)}; got {value!r}"
            )
        return value
```

The deferred import mirrors the pattern `spec.py` already uses to avoid a module-level `catalog` import.

- [ ] **Step 4: Thread the keyword**

1. `candidates.py::_to_build_spec` gains `machine_rank: MachineRank = MachineRank.EXACT` and `machine_moves: tuple[MachineMove, ...] = ()`, and sets the two `BuildSpec` fields, converting each `MachineMove` into a `MachineMoveRecord`. Update all three `_to_build_spec` call sites (`candidates.py:192`-region, `:407`-region, `:488`-region) to forward `machine_rank=machine_rank, machine_moves=solution.machine_moves`.
2. `build_candidates` and `_build_candidates_canonical` gain `machine_rank: MachineRank = MachineRank.EXACT`; `build_candidates` forwards it.
3. All four `solve(...)` calls (`candidates.py:424,535,563,571`) gain `machine_rank=machine_rank`.
4. `_pinned_candidates` gains the parameter but **forces `MachineRank.EXACT`** on its `solve(...)` call and passes the flow's recipes as `pinned_machines`. Comment:

```python
    # A supplied flow pins the machine as well as the recipe and mode: the
    # player told us what FactorioLab built, and `lab/flow.py`'s cross-check
    # compares the built machine id against that flow row.  "Up to" is a
    # choice the flow already made.
```
5. `pipeline.build` gains `machine_rank: MachineRank = MachineRank.EXACT` in its keyword-only block and forwards it to `_build_candidates_canonical`.
6. `layout/hierarchy/partition.py:329,429`: add `machine_rank=spec.machine_rank, machine_moves=spec.machine_moves,` to both synthesized sub-specs.

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/test_spec.py tests/rates -x
uv run pytest tests/layout/hierarchy -x -p no:randomly
```

- [ ] **Step 6: Prove the default is unchanged end to end**

```bash
uv run python -m flab2bp.cli "$(uv run python -c "
from flab2bp.bench.corpus import URL_CORPUS
print(next(e.url for e in URL_CORPUS if e.url_id=='magnetic-coil'))")" \
  --strategy freeform --budget 30 > /tmp/head.txt 2>&1 || true
git stash list  # must be empty; never stash
```
Compare against the same command run from a clean checkout of `MERGE_BASE`; the reports must match. Save both to `docs/superpowers/evidence/2026-09-07-machine-upto/task5-default-unchanged.txt`.

- [ ] **Step 7: Lint and type-check**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

- [ ] **Step 8: Commit** (one commit per file where practical)

```bash
git add src/flab2bp/spec.py && git commit -m "feat(spec): carry the machine rank and its moves"
git add src/flab2bp/rates/candidates.py && git commit -m "feat(rates): thread machine_rank through the candidate frontier"
git add src/flab2bp/layout/hierarchy/partition.py && git commit -m "fix(hierarchy): copy machine rank into synthesized sub-specs"
git add src/flab2bp/pipeline.py && git commit -m "feat(pipeline): accept machine_rank"
git add tests docs/superpowers/evidence/2026-09-07-machine-upto && git commit -m "test: machine rank reaches the spec"
```

> **REVIEW BATCH B ends here** (Tasks 4-5).

---

## Task 6: `--machine-rank` on the CLI

**Files:**
- Modify: `src/flab2bp/cli.py` (`build_parser`, and the `pipeline.build(...)` call ~`554-571`)
- Test: `tests/test_pipeline_cli_strategy.py`

**Interfaces:**
- Consumes: `pipeline.build(machine_rank=...)` (Task 5).
- Produces: the CLI flag. Nothing consumes it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline_cli_strategy.py`, modelled exactly on `test_cli_band_choices_are_exact_and_reach_pipeline` at `:313`:

```python
def test_cli_machine_rank_choices_are_exact_and_reach_pipeline(monkeypatch, capsys) -> None:
    from flab2bp.rates.machine_choice import MachineRank

    seen: list[object] = []

    def fake_build(url, **kwargs):
        seen.append(kwargs["machine_rank"])
        raise SystemExit(0)

    monkeypatch.setattr(pipeline, "build", fake_build)

    parser = cli.build_parser()
    action = next(a for a in parser._actions if a.dest == "machine_rank")
    assert sorted(action.choices) == ["exact", "up-to"]
    assert action.default == "exact"

    for choice in ("exact", "up-to"):
        with pytest.raises(SystemExit):
            cli.main(["URL", "--machine-rank", choice])
    assert seen == [MachineRank.EXACT, MachineRank.UP_TO]

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["URL", "--machine-rank", "sometimes"])
    assert exit_info.value.code != 0
```

Adapt the monkeypatch and `cli.main` argument shapes to whatever the neighbouring band test in this file already uses — copy its structure, do not invent one.

- [ ] **Step 2: Run it and watch it fail**

```bash
uv run pytest tests/test_pipeline_cli_strategy.py -x -k machine_rank
```
Expected: `unrecognized arguments: --machine-rank`.

- [ ] **Step 3: Add the flag**

In `src/flab2bp/cli.py::build_parser`, beside the other build options:

```python
    ap.add_argument(
        "--machine-rank",
        choices=[rank.value for rank in MachineRank],
        default=MachineRank.EXACT.value,
        help=(
            "how to read the URL's machine rank: 'exact' builds every recipe "
            "in the ranked machine (FactorioLab's behaviour, the default); "
            "'up-to' treats the rank as a ceiling and drops each recipe to "
            "the slowest unlocked producer that meets the same rate in the "
            "same number of machines, so a Negentropy Smelter is not spent "
            "on an Arc Smelter's worth of throughput"
        ),
    )
```

Import `MachineRank` at the top of `cli.py`, and at the `pipeline.build(...)` call add:

```python
                machine_rank=MachineRank(args.machine_rank),
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_pipeline_cli_strategy.py tests/test_cli.py -x
uv run python -m flab2bp.cli --help | grep -A6 'machine-rank'
```

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src
git add src/flab2bp/cli.py tests/test_pipeline_cli_strategy.py
git commit -m "feat(cli): --machine-rank {exact,up-to}"
```

---

## Task 7: The description line names the mode and the moves

**Files:**
- Modify: `src/flab2bp/pipeline.py` (`_machine_rank_note`, and the description f-string at `1265-1273`)
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `BuildSpec.machine_rank`, `BuildSpec.machine_moves` (Task 5).
- Produces: `pipeline._machine_rank_note(spec: BuildSpec) -> str`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline.py`:

```python
def test_the_description_says_nothing_about_exact_machine_ranking() -> None:
    spec = _spec_with(machine_rank="exact", machine_moves=())
    assert pipeline._machine_rank_note(spec) == ""


def test_the_description_names_up_to_and_every_recipe_that_moved() -> None:
    spec = _spec_with(
        machine_rank="up-to",
        machine_moves=(
            MachineMoveRecord(
                recipe_id="iron-ingot",
                from_machine="plane-smelter",
                to_machine="arc-smelter",
                count_before=2,
                count_after=2,
            ),
        ),
    )
    note = pipeline._machine_rank_note(spec)
    assert note == "; machines up-to: iron-ingot plane-smelter->arc-smelter 2->2"


def test_up_to_with_nothing_to_move_still_says_which_mode_ran() -> None:
    spec = _spec_with(machine_rank="up-to", machine_moves=())
    assert pipeline._machine_rank_note(spec) == "; machines up-to: none moved"
```

`_spec_with` builds a minimal `BuildSpec` — reuse the helper this file or `tests/test_spec.py` already has.

- [ ] **Step 2: Run and watch it fail**

```bash
uv run pytest tests/test_pipeline.py -x -k machine_rank
```

- [ ] **Step 3: Implement**

In `src/flab2bp/pipeline.py`, beside `_prime_note` (`482-502`):

```python
def _machine_rank_note(spec: BuildSpec) -> str:
    """What the description says about how the machine rank was read.

    Empty under ``exact`` so a default build's description is byte-identical
    to what it was before the option existed.  Under ``up-to`` it names the
    mode and every recipe that moved, because the moved machines are the
    only difference a player can see in the blueprint.
    """
    if spec.machine_rank != "up-to":
        return ""
    if not spec.machine_moves:
        return "; machines up-to: none moved"
    moved = " ".join(
        f"{move.recipe_id} {move.from_machine}->{move.to_machine} "
        f"{move.count_before}->{move.count_after}"
        for move in spec.machine_moves
    )
    return f"; machines up-to: {moved}"
```

Append `f"{_machine_rank_note(spec)}"` to the description f-string at `pipeline.py:1268-1272`, after `_prime_note(spec, marked)`.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_pipeline.py -x
uv run pytest tests/dsp/test_encode.py -x
```

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src
git add src/flab2bp/pipeline.py tests/test_pipeline.py
git commit -m "feat(pipeline): the description names the machine-rank mode and its moves"
```

> **REVIEW BATCH C ends here** (Tasks 6-7).

---

## Task 8: The web server accepts and reports `machine_rank`

**Files:**
- Modify: `src/flab2bp/web/jobs.py` (`Options` at `64`, allowlist at `203-215`, `parse_options` at `274-287`, `Options(...)` at `313-325`, `pipeline.build` at `399-414`, `Builder.snapshot` at `584-605`)
- Modify: `src/flab2bp/web/payload.py` (`describe` at `203`)
- Test: `tests/web/test_options.py`, `tests/web/test_payload.py`

**Interfaces:**
- Consumes: `pipeline.build(machine_rank=...)`, `BuildSpec.machine_rank`, `BuildSpec.machine_moves`.
- Produces: request key `machine_rank`; payload keys `machine_rank` and `machine_moves` (a list of objects with `recipe_id`, `from_machine`, `to_machine`, `count_before`, `count_after`). Task 9 consumes both.

- [ ] **Step 1: Write the failing tests**

In `tests/web/test_options.py`, modelled on `test_proliferator_tier_is_optional_and_explicit` (`:167-188`):

```python
def test_machine_rank_defaults_to_exact() -> None:
    assert parse_options({"url": "URL"}).machine_rank is MachineRank.EXACT


def test_machine_rank_accepts_up_to() -> None:
    options = parse_options({"url": "URL", "machine_rank": "up-to"})
    assert options.machine_rank is MachineRank.UP_TO


def test_machine_rank_rejects_anything_else() -> None:
    with pytest.raises(InvalidOptions, match="machine_rank"):
        parse_options({"url": "URL", "machine_rank": "upto"})


def test_machine_rank_is_an_allowed_key() -> None:
    parse_options({"url": "URL", "machine_rank": "exact"})  # must not raise
```

Also extend this file's existing `test_defaults_match_the_cli` (`:74-84`) so the CLI default and the web default are asserted equal.

In `tests/web/test_payload.py`:

```python
def test_the_payload_names_the_machine_rank_and_lists_no_moves_by_default() -> None:
    body = describe(_a_build())
    assert body["machine_rank"] == "exact"
    assert body["machine_moves"] == []


def test_the_payload_lists_every_move_under_up_to() -> None:
    body = describe(_a_build(machine_rank="up-to", machine_moves=(_a_move(),)))
    assert body["machine_rank"] == "up-to"
    assert body["machine_moves"] == [
        {
            "recipe_id": "iron-ingot",
            "from_machine": "plane-smelter",
            "to_machine": "arc-smelter",
            "count_before": 2,
            "count_after": 2,
        }
    ]
```

- [ ] **Step 2: Run them and watch them fail**

```bash
uv run pytest tests/web -x
```
Expected: `InvalidOptions: unknown option(s): 'machine_rank'`.

- [ ] **Step 3: Implement, all six sites**

1. `Options` gains `machine_rank: MachineRank = MachineRank.EXACT`.
2. Add `"machine_rank"` to the `allowed` set at `jobs.py:203-215`.
3. In `parse_options`, beside the proliferator tier `match`:

```python
    raw_rank = raw.get("machine_rank", MachineRank.EXACT.value)
    match raw_rank:
        case "exact" | None:
            machine_rank = MachineRank.EXACT
        case "up-to":
            machine_rank = MachineRank.UP_TO
        case _:
            raise InvalidOptions("'machine_rank' must be one of exact, up-to")
```
4. Pass `machine_rank=machine_rank` in the `Options(...)` construction.
5. Pass `machine_rank=options.machine_rank` in the `pipeline.build(...)` call.
6. Add `"machine_rank": job.options.machine_rank.value,` to the `"options"` dict in `Builder.snapshot`.
7. In `web/payload.py::describe`, add:

```python
        "machine_rank": build.spec.machine_rank,
        "machine_moves": [
            {
                "recipe_id": move.recipe_id,
                "from_machine": move.from_machine,
                "to_machine": move.to_machine,
                "count_before": move.count_before,
                "count_after": move.count_after,
            }
            for move in build.spec.machine_moves
        ],
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/web -x
```

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src
git add src/flab2bp/web/jobs.py && git commit -m "feat(web): accept a machine_rank option"
git add src/flab2bp/web/payload.py && git commit -m "feat(web): report the machine rank and its moves"
git add tests/web && git commit -m "test(web): machine rank option and payload"
```

---

## Task 9: The web UI select and result row

**Files:**
- Modify: `web/src/api/build.ts` (enum, `BuildOptions`, `DEFAULT_OPTIONS`, `BuildResult`)
- Modify: `web/src/ui/BuildPanel.tsx` (`useId`, the select)
- Modify: `web/src/ui/BuildReport.tsx` (the row)
- Test: `web/tests/api/build.test.ts`, `web/tests/ui/BuildPanel.test.tsx`, `web/tests/ui/BuildReport.test.tsx`

**Interfaces:**
- Consumes: the request key `machine_rank` and payload keys `machine_rank` / `machine_moves` (Task 8).
- Produces: nothing downstream.

**Label:** the select's label text is exactly `Machine ranking`. `scripts/web_smoke.py:347-360` matches controls by label-text prefix, so the label must not be a prefix of, nor prefixed by, `Strategy`, `Latitude band`, `Proliferator tier`, or `Candidate policies`. `Machine ranking` is not.

`web/tests/architecture.test.ts` forbids React and three.js imports from `src/api` — keep the zod enum in `src/api/build.ts` and all JSX in `src/ui/`.

- [ ] **Step 1: Write the failing tests**

`web/tests/api/build.test.ts`:

```ts
test('machine rank defaults to exact and round-trips up-to', () => {
  expect(DEFAULT_OPTIONS.machine_rank).toBe('exact');
  expect(BuildOptions.parse({ ...DEFAULT_OPTIONS, machine_rank: 'up-to' }).machine_rank).toBe(
    'up-to',
  );
  expect(BuildOptions.safeParse({ ...DEFAULT_OPTIONS, machine_rank: 'upto' }).success).toBe(false);
});
```

`web/tests/ui/BuildPanel.test.tsx`:

```tsx
test('machine ranking exposes exact and up-to in that order', () => {
  mount();
  const rank = screen.getByLabelText('Machine ranking') as HTMLSelectElement;
  expect(Array.from(rank.options, (o) => [o.value, o.text])).toEqual([
    ['exact', 'Exact (the URL’s machine)'],
    ['up-to', 'Up to (fewest machines at or below it)'],
  ]);
  expect(rank.value).toBe('exact');
});

test('submits an explicit up-to machine ranking', async () => {
  const calls = serving({ status: 202, body: aJob() });
  mount();
  fireEvent.change(screen.getByLabelText('Machine ranking'), {
    target: { value: 'up-to' },
  });
  build();
  await waitFor(() => expect(calls).toHaveLength(1));
  const body = JSON.parse(String(calls[0]?.init?.body)) as Record<string, unknown>;
  expect(body.machine_rank).toBe('up-to');
});
```

`web/tests/ui/BuildReport.test.tsx`:

```tsx
test('the report names the machine ranking mode', () => {
  render(<BuildReport result={aResult({ machine_rank: 'exact', machine_moves: [] })} />);
  expect(screen.getByText('Machine ranking')).toBeInTheDocument();
  expect(screen.getByText('Exact')).toBeInTheDocument();
});

test('the report lists every recipe whose machine moved', () => {
  const result = aResult({
    machine_rank: 'up-to',
    machine_moves: [
      {
        recipe_id: 'iron-ingot',
        from_machine: 'plane-smelter',
        to_machine: 'arc-smelter',
        count_before: 2,
        count_after: 2,
      },
    ],
  });
  render(<BuildReport result={result} />);
  expect(screen.getByText(/iron-ingot/)).toBeInTheDocument();
  expect(screen.getByText(/plane-smelter/)).toBeInTheDocument();
  expect(screen.getByText(/arc-smelter/)).toBeInTheDocument();
});
```

Match the exact `mount` / `serving` / `build` / `aJob` / `aResult` helpers those files already use; add `machine_rank` and `machine_moves` defaults to `web/tests/support/build.ts` so every existing `aResult()` caller keeps parsing under `.strict()`.

- [ ] **Step 2: Run them and watch them fail**

```bash
cd web && bun install && bun run test 2>&1 | tail -30
```

- [ ] **Step 3: Implement**

`web/src/api/build.ts`:

```ts
export const MachineRank = z.enum(['exact', 'up-to']);
export type MachineRank = z.infer<typeof MachineRank>;

export const MachineMove = z.object({
  recipe_id: z.string(),
  from_machine: z.string(),
  to_machine: z.string(),
  count_before: z.number(),
  count_after: z.number(),
});
```

Add `machine_rank: MachineRank,` to the `BuildOptions` object; add `machine_rank: 'exact',` to `DEFAULT_OPTIONS`; add `machine_rank: MachineRank` and `machine_moves: z.array(MachineMove)` to `BuildResult`.

`web/src/ui/BuildPanel.tsx` — a `const machineRankId = useId();` beside the others at line 44, and inside the same `<div className="row options">`, after the proliferator select:

```tsx
        <label htmlFor={machineRankId}>Machine ranking</label>
        <select
          id={machineRankId}
          value={options.machine_rank}
          onChange={(event) => {
            const rank = MachineRank.safeParse(event.target.value);
            if (rank.success) set('machine_rank', rank.data);
          }}
        >
          <option value="exact">Exact (the URL&rsquo;s machine)</option>
          <option value="up-to">Up to (fewest machines at or below it)</option>
        </select>
```

`web/src/ui/BuildReport.tsx` — a `<dt>`/`<dd>` pair in the existing `<dl>`:

```tsx
        <dt>Machine ranking</dt>
        <dd>
          {result.machine_rank === 'up-to' ? 'Up to' : 'Exact'}
          {result.machine_moves.length > 0 && (
            <ul className="machine-moves">
              {result.machine_moves.map((move) => (
                <li key={move.recipe_id}>
                  {move.recipe_id}: {move.from_machine} &rarr; {move.to_machine} (
                  {move.count_before} &rarr; {move.count_after})
                </li>
              ))}
            </ul>
          )}
        </dd>
```

- [ ] **Step 4: Run typecheck, lint, tests**

```bash
cd web && bun run typecheck && bun run lint && bun run test
```
If `bun run lint` reports formatting, run `bun run format` and re-run. Never commit `web/dist`.

- [ ] **Step 5: Commit**

```bash
git add web/src/api/build.ts && git commit -m "feat(web): machine rank in the request and result schemas"
git add web/src/ui/BuildPanel.tsx && git commit -m "feat(web): a machine ranking select"
git add web/src/ui/BuildReport.tsx && git commit -m "feat(web): report which machines moved"
git add web/tests && git commit -m "test(web): machine ranking select, schema, and report"
```

> **REVIEW BATCH D ends here** (Tasks 8-9). Expect a merge conflict with the `power-tower` branch in `BuildPanel.tsx`, `build.ts`, `jobs.py`, and the `pipeline.py` description f-string if it lands first. That is fine; resolve by keeping both options.

---

## Task 10: `scripts/audit.py --machine-rank`

**Files:**
- Modify: `scripts/audit.py` (`build_parser` `738-799`, `Job` `167-183`, `build_jobs` `599-634`, `main` `~823`, `run_cell` `324-361`, `record` `~700`)
- Test: `tests/test_audit.py`

**Interfaces:**
- Consumes: `pipeline.build(machine_rank=...)`.
- Produces: the flag and the JSONL key `machine_rank`. Task 11 consumes both.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit.py`:

```python
def test_machine_rank_flag_defaults_to_exact_and_reaches_every_job() -> None:
    parser = audit.build_parser()
    action = next(a for a in parser._actions if a.dest == "machine_rank")
    assert sorted(action.choices) == ["exact", "up-to"]
    assert action.default == "exact"

    jobs = audit.build_jobs(..., machine_rank="up-to")   # match build_jobs' real signature
    assert jobs
    assert {job.machine_rank for job in jobs} == {"up-to"}
```

Read `build_jobs`' real signature at `scripts/audit.py:599-634` and call it exactly as `main` does, with the smallest tier and one URL.

- [ ] **Step 2: Run and watch it fail**

```bash
uv run pytest tests/test_audit.py -x
```

- [ ] **Step 3: Implement, all five sites**

1. `build_parser`:

```python
    ap.add_argument(
        "--machine-rank",
        choices=[rank.value for rank in MachineRank],
        default=MachineRank.EXACT.value,
        help="how to read the URL's machine rank (default: exact)",
    )
```
2. `Job` gains `machine_rank: str = "exact"` — a plain `str`, not the enum, because `Job` crosses a `ProcessPoolExecutor` boundary and must stay trivially picklable.
3. `build_jobs` gains `machine_rank: str = "exact"` and sets it on every `Job(...)`.
4. `main` passes `machine_rank=args.machine_rank` into `build_jobs(...)`.
5. `run_cell` passes `machine_rank=MachineRank(job.machine_rank)` into the `pipeline.build(...)` / strategy construction, following exactly how `--arrangements` is threaded at `scripts/audit.py:361`.
6. `record()` adds `"machine_rank": job.machine_rank,` — without this stamp two JSONLs are indistinguishable arms, which is the one thing the gate cannot recover from.

- [ ] **Step 4: Run the test and one real cell**

```bash
uv run pytest tests/test_audit.py -x
pgrep -fc '[s]cripts/audit\.py' || true      # must be 0
uv run python scripts/audit.py --tier trivial --only iron-ingot --budget 30 \
  --strategy freeform --machine-rank up-to --json /tmp/probe.jsonl
uv run python -c "
import json
row = json.loads(open('/tmp/probe.jsonl').readline())
print(row['machine_rank'], row['status'], row['area'])"
```
Expected: `up-to`, a status, and an area.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src
git add scripts/audit.py tests/test_audit.py
git commit -m "feat(audit): --machine-rank and a per-row arm stamp"
```

> **REVIEW BATCH E ends here** (Task 10).

---

## Task 11: The gate

**Files:**
- Create: `docs/superpowers/evidence/2026-09-07-machine-upto/gate.md`
- Create: `docs/superpowers/evidence/2026-09-07-machine-upto/run_round.sh`, `run_reported.sh`, `moved.py`
- Create: the JSONLs and logs those scripts produce

The deliverable is **a measured README, not a green light.**

### The operating point (copy exactly; do not tune)

```
--budget 30  --jobs 8  --strategy both  --max-seconds 3600
72 cells = 12 URLs x 3 candidate policies x 2 strategies
```

Chunk by URL, skipping URLs already present in the arm's JSONL: `audit.py` writes its JSONL only after the whole loop, and a SIGSEGV has previously destroyed twelve completed cells. Record `vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print sum/5}'` beside every round into `<round>-load.txt`. **One audit at a time**: `pgrep -fc '[s]cripts/audit\.py'` must be 0 before each round.

### The arms

| Arm | Where | Command |
| --- | --- | --- |
| `base` | a clean checkout of `MERGE_BASE` (`ad8a6f80`) at `.claude/worktrees/machine-upto-base` | `uv run python scripts/audit.py --only "$URL" --budget 30 --jobs 8 --strategy both --max-seconds 3600 --json "$OUT/base.jsonl"` |
| `exact` | this branch at HEAD | same, plus `--machine-rank exact` |
| `up-to` | this branch at HEAD | same, plus `--machine-rank up-to` |

- [ ] **Step 1: Create the base worktree and verify both trees**

```bash
export GIT_EDITOR=true
cd /home/dannyb/sources/factorio-lab-to-blueprint
git worktree add --detach .claude/worktrees/machine-upto-base ad8a6f80
cd .claude/worktrees/machine-upto-base && uv sync
uv run python -c "import flab2bp; print(flab2bp.__file__)"   # inside machine-upto-base
```
Both trees must print their own path. A test result from the wrong tree is not evidence.

- [ ] **Step 2: Run the three arms**

Write `run_round.sh` taking `ARM` and the checkout path, looping the twelve URLs, skipping ones already in the arm's JSONL, and appending to `<arm>.jsonl`. Run `base`, then `exact`, then `up-to`, **one at a time**.

- [ ] **Step 3: Gate (a) — `exact` against master**

```bash
uv run python scripts/audit_compare.py \
  docs/superpowers/evidence/2026-09-07-machine-upto/base.jsonl \
  docs/superpowers/evidence/2026-09-07-machine-upto/exact.jsonl \
  --expect-cells 72
```
**PASS requires all three:**
1. `paired` = the number of cells CLEAN in both, with **zero** `FAIL REGRESSION` and zero `FAIL MISSING`;
2. `area ratio` exactly `1.0000` — this is byte-identity, not a noise band;
3. the CLEAN / REFUSED / INVALID / CRASHED counts equal the base arm's, cell for cell. Any refusal that is not also a refusal on `base` is a FAIL, named.

Do **not** read `audit.py`'s own `NOT CLEAN` banner as the verdict; `universe-matrix` is expected to refuse on both arms.

- [ ] **Step 4: Gate (a) — deterministic controls, 12 cells, byte-identical**

Byte-identity must be asked at one CP-SAT worker: at `--jobs 8` master disagrees with *itself* on 8 of 72 cells, because CP-SAT with more than one worker under a wall clock is not reproducible. `audit.py` cannot do this (it has no `--workers`). Copy `docs/superpowers/evidence/2026-09-07-exp-coater-node/probes/probe_cell.py` into this evidence directory, add a `--machine-rank` pass-through, and run:

```bash
for URL in iron-ingot magnetic-coil graphene electromagnetic-matrix plastic processor \
           energy-matrix super-magnetic-ring casimir-crystal information-matrix \
           quantum-chip universe-matrix; do
  for ARM in exact up-to; do
    printf '%-24s %-8s ' "$URL" "$ARM"
    uv run python docs/superpowers/evidence/2026-09-07-machine-upto/probes/probe_cell.py \
      "$URL" no-proliferator --budget 30 --workers 1 --machine-rank "$ARM" 2>&1 \
      | grep -v "VIRTUAL_ENV\|^warning" | grep -E "digest=|REFUSED|CRASH" | tr '\n' ' '
    echo
  done
done | tee docs/superpowers/evidence/2026-09-07-machine-upto/controls.txt
```
Run the same twelve on the `base` checkout without the flag. **PASS: all 12 `exact` digests equal the 12 `base` digests.** Record the `up-to` digests in the same table — they are expected to differ wherever a machine moved, and that difference is the feature.

- [ ] **Step 5: Gate (b) — `up-to` against `exact` across the corpus**

```bash
uv run python scripts/audit_compare.py \
  docs/superpowers/evidence/2026-09-07-machine-upto/exact.jsonl \
  docs/superpowers/evidence/2026-09-07-machine-upto/up-to.jsonl \
  --expect-cells 72 --regressions-only
```

Then write `moved.py`, which for each of the 12 URLs and 3 policies runs `build_candidates` in both modes and prints total machines, total power draw (`sum(count * data.machine(m).usage)`), and every `MachineMove`. Power is where the win actually shows: Invariant U makes machine counts equal, and Arc/Plane/Negentropy Smelter are all 3x3 as are all four assemblers, so area is expected to be equal too.

Report as a table in `gate.md`:

| url_id | policy | strategy | CLEAN exact→up-to | machines | area | belt_tiles | power kW | recipes moved |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

**PASS requires all four:**
1. `up-to` CLEAN count ≥ `exact` CLEAN count; no cell CLEAN under `exact` and not CLEAN under `up-to`, and no `INVALID` or `CRASH` anywhere;
2. total machines identical in every cell (Invariant U; a difference is a bug in the chooser, not a result);
3. area ratio within the 1.3 % same-arm noise band (`--noise-area 0.013`, the default);
4. the moved-recipe list is non-empty — a corpus-inert arm is a **FAIL**, because it means the feature never ran. (It should not be: ten URLs rank `assembling-machine-2`, and `quantum-chip` / `universe-matrix` rank `plane-smelter` / `assembling-machine-3` / `quantum-chemical-plant`.)

- [ ] **Step 6: Gate (c) — the reported URL, six pairs, under `up-to`**

`AMM_URL` is the user's reported URL from `docs/superpowers/plans/2026-09-06-self-loop-recipes.md` (also in `docs/superpowers/evidence/2026-09-07-coater-placed-gate/run_reported.sh`). Six pairs = 3 candidate policies × 2 strategies. Write `run_reported.sh` modelled on that file:

```bash
for S in freeform sequence-pair; do
  for POLICY in no-proliferator all-products output-products; do
    uv run python docs/superpowers/evidence/2026-09-07-machine-upto/probes/probe_cell.py \
      reported "$POLICY" --url "$AMM_URL" --strategy "$S" --budget 30 --workers 32 \
      --machine-rank up-to 2>&1 | grep -v "VIRTUAL_ENV\|^warning" >> "$OUT/up-to.log"
  done
done
```
Run the same six under `--machine-rank exact` for the comparison.

**PASS: all six build CLEAN under `up-to` at `--budget 30`, with zero validator findings and zero belt collisions**, and the moved-recipe list for each is recorded. Certify green explicitly or report the failing pair by name.

- [ ] **Step 7: Write `gate.md`**

It must contain, in this order: the operating point verbatim; the three arms and their commit SHAs; the (a) / (b) / (c) tables above; the moved-recipe list; the `vmstat` figure beside every round; **every controller ruling from the ledger, restated as `Ruling: what — why — cost if wrong`**; the D5 and D6 rulings from this plan's design section; and the exact commands, so the run reproduces.

Any FAIL is reported as a FAIL, naming the cell, the strategy, the refusal message and the mechanism. **Do not re-run an arm to get a better number.**

- [ ] **Step 8: Commit**

```bash
git add docs/superpowers/evidence/2026-09-07-machine-upto
git commit -m "evidence(machine-upto): corpus gate for the exact and up-to arms"
```

---

## Task 12: Verification at HEAD

**Files:** none — this task only measures.

- [ ] **Step 1: Confirm the tree**

```bash
cd /home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/machine-upto
uv run python -c "import flab2bp; print(flab2bp.__file__)"
git status --porcelain     # must be empty
```

- [ ] **Step 2: Lint, format, types**

```bash
uv run ruff check . ; echo "ruff=$?"
uv run ruff format --check . ; echo "format=$?"
uv run mypy src ; echo "mypy=$?"
```
All three must be 0.

- [ ] **Step 3: The full suite, by exit code, by directory**

The 120 s per-test timeout hard-kills a long run, so run by directory and aggregate. The summary line does not print here — **judge by the exit code.**

```bash
for d in tests/bench tests/dsp tests/conditions tests/lab tests/fixtures tests/layout \
         tests/rates tests/rules tests/scripts tests/web; do
  uv run pytest "$d" ; echo "$d=$?"
done
for f in tests/test_pipeline.py tests/test_pipeline_cli_strategy.py tests/test_spec.py \
         tests/test_audit.py tests/test_cli.py; do
  uv run pytest "$f" ; echo "$f=$?"
done
```

- [ ] **Step 4: Name the known reds by re-running them on the merge base**

Any failure must be reproduced in `.claude/worktrees/machine-upto-base` before it is called a known red. Report only the delta.

```bash
cd /home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/machine-upto-base
uv run pytest tests/layout/test_sequence_pair.py::test_two_stage_alignment_retains_cp_sat_direct_opportunity ; echo "base=$?"
uv run pytest "tests/test_pipeline.py::test_all_products_sequence_pair_honours_the_exact_layout_deadline" ; echo "base=$?"
```

- [ ] **Step 5: Web verification**

```bash
cd /home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/machine-upto/web
bun run typecheck ; echo "typecheck=$?"
bun run lint ; echo "lint=$?"
bun run test ; echo "test=$?"
```

- [ ] **Step 6: Record the SHA and stop**

```bash
cd /home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/machine-upto
git rev-parse HEAD
git log --oneline ad8a6f80..HEAD
```

**Stop. Ready to merge, not merged.** Do not merge, push, rebase, or delete the branch.

---

## Risks

1. **`exact` is not byte-identical.** The whole default-safety argument rests on it. *Mitigation:* `rechoose_columns` returns the input list by identity under `EXACT` (Task 4 Step 3), Task 4 Step 6 hashes every corpus solve in both spellings, gate (a) demands an area ratio of exactly 1.0000, and the 12 controls are compared at one CP-SAT worker.
2. **Invariant U is wrong somewhere.** If a chosen machine ever needs *more* machines than the ceiling, the MILP's integer capacity caps are violated and `solve.py:1322-1329` raises `InfeasibleError` mid-corpus. *Mitigation:* the 1000+ case property test in Task 3 Step 1, plus gate clause (b)(2), which fails on any machine-count difference.
3. **A chosen machine cannot be placed.** `layout/freeform.py:2096-2110` raises `KeyError` for an unknown machine. *Mitigation:* `_is_placeable` in the ladder plus `test_every_ladder_entry_is_placeable`, which walks every multi-producer recipe in the dataset.
4. **`up-to` turns out corpus-inert.** Three prior branches shipped features that never fired on the corpus. *Mitigation:* the corpus ranks were checked before this plan was written (all 12 URLs carry `mmr`; ten can move assemblers, two can move three families), and gate clause (b)(4) makes an empty moved list a FAIL rather than a pass.
5. **The `power-tower` branch lands first and conflicts.** *Mitigation:* expected in `BuildPanel.tsx`, `build.ts`, `jobs.py`, `spec.py`, `candidates.py`, and the `pipeline.py` description f-string; both options are additive, so resolve by keeping both. Do not rebase — stay on the merge base until told otherwise.
6. **`machine_footprint`'s zero-area defect (D6) makes area comparisons misleading.** *Mitigation:* the gate reads `area` from `audit.py` (the real placement bounding box), never `RateSolution.total_area`, and the defect is written into `gate.md` as a reported finding.
7. **A flow CSV plus `up-to` produces a cross-check finding storm.** `lab/flow.py:1006-1017` compares the built machine against the flow row. *Mitigation:* `_pinned_candidates` forces `EXACT` (Task 5 Step 4.4), with a test.

## Out of scope

- **Honouring `mpr` / `minMachineRank` / `maxMachineRank` for URLs with no `mmr`** (Ruling D5). It flips every bare-URL build, invalidates the tier and bench corpora, and contradicts the standing decision at `scripts/item_sweep.py:172-183`. Consequence to document: `up-to` is a no-op on a URL with no `mmr`.
- **Fixing `machine_footprint`'s pre-canonicalization keying** (Ruling D6). It would move the `exact` arm and break the byte-identity guard this branch exists to prove.
- **Alternative machine columns inside the MILP.** Invariant U proves the two-phase choice is free; alternative columns would quadruple the column count on 449 recipes and change `exact`'s route selection.
- **Making `up-to` the default.** The gate measures the arm so the user can flip the default on numbers; flipping it is a separate decision.
- **`docs/WEB_UI.md` and `README.md` option prose.** Both are already stale about `candidate_policies`; correcting them belongs with that fix, not this one.
