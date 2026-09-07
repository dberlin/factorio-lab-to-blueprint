# Hierarchical v3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get `--strategy hierarchical` from "0 of 8 large cells build" to "every cell that composes emits a validator-clean blueprint, both malls compose, and titanium-glass builds at the web UI's 15 s", by fixing the two defects the v2 gate measured — an unbounded, mis-funded re-cut loop that never attempts 22 and 45 of the malls' blocks, and a port-access oracle that is structurally unable to reject the thing that actually refuses the router.

**Architecture:** `hierarchical` is the ORCHESTRATOR of this repo's sub-solvers, not a placer. It cuts a spec into blocks, hands each block to a solver behind the `strategy._solve_block` seam, and composes what comes back; every placer in the repo, and every future one (the pre-generated block library, a revived `spine`, coater-composite strips — `docs/speedup-idea-backlog.md` "Structured and specialised solvers" and "Blocks and pre-generation"), plugs in at that one seam, which Task 1 documents as a contract so a later plan can add a solver without touching `partition`, `contracts` or `compose`. Three levers, in the order of the cells they unlock. **Lever A** (Tasks 1-3) makes the orchestrator's dispatch honest: bounded re-cut rounds, a round budget that funds the blocks that exist rather than dividing by a moving target, ONE arm per block chosen from the routing-difficulty feature key (`docs/superpowers/evidence/2026-09-06-exp-features/`) instead of both, and every number the gate needs printed by the CLI on the refusal path instead of spied from a harness. **Lever B** (Tasks 4-6) makes the port-access oracle able to say no: `freeform._reserve_port_access` gains a per-demand GOAL set, `compose` gives each cut lane's demand its partner's doorstep as that goal, and the ladder's upper rungs become reachable for the first time. **Lever C** (Task 7) is a conditional spike on a shared bus corridor, run only if Lever B's measurement says the geometry — not the oracle — is what is missing. Task 8 is the gate.

**Tech Stack:** Python 3.14, `uv run`, `freeform`'s router (`_reserve_port_access`, `_astar`, `_route_all`), `multiprocessing` spawn pools, OR-Tools CP-SAT (`_match_access_corridors`), `scripts/audit.py`, `scripts/audit_compare.py`.

**Spec:** `docs/superpowers/specs/2026-09-06-multi-solver-orchestrator-design.md` — §1 (coverage and bounded time first, area second), §3.1-§3.3 (a feature vector computed before any placement, a registry where a solver claims a class, an anytime portfolio rather than "best area"), §4 E (a bus corridor reserved before block placement, and its 2026-09-07 status note). The measurements this plan argues from are `docs/superpowers/evidence/2026-09-07-hierarchical-v2/gate.md` §2.1, §2.2, §3.2, §3.4, §6, §7, §8, and the dispatch key is `docs/superpowers/evidence/2026-09-06-exp-features/README.md` §4(b) and Experiment 5's "Arm choice". The previous plan, `docs/superpowers/plans/2026-09-06-hierarchical-v2.md`, is the file structure this one extends; its 16 controller rulings live in gate.md and its own ledger is gone, so gate.md is the record.

## Global Constraints

- **`--strategy hierarchical` stays EXPLICIT and DEFAULT-OFF.** `PRODUCTION_STRATEGIES` is unchanged; `best` is unchanged. No task in this plan may add `hierarchical` to a default field.
- **Default behaviour is unchanged, and it is judged by a PAIRED audit, not by a banner.** One `scripts/audit.py --budget 30 --json` round on master's merge base and one on this branch, compared with `scripts/audit_compare.py`. `audit.py` prints `NOT CLEAN` on any refusal, so what is read is the CLEAN COUNTS and the NAMED DIFFERING CELLS, never the banner. Zero regressions means: no cell CLEAN on the base and not CLEAN on the branch, 0 INVALID, 0 CRASH.
- **`validate.certify` is the arbiter.** No player hand-back beyond the player-fed lane contract v2 shipped (`contracts.allocate_cuts`): a head for an item the parent spec does NOT belt in must be fully fed by cuts or the build refuses.
- **Bounded time.** Every job's deadline stays `min(parent_deadline, job_start + block_budget)`, computed in the worker. The strategy may overshoot `--budget` only by `pipeline.RACE_COMPLETION_GRACE_S = 6.0`, as v2 recorded.
- **Exact arithmetic** everywhere rates appear (`Fraction`, never `float`).
- **ONE LAYOUT BUILD AT A TIME on this box, and never two audits at once.** Other agents run builds in sibling worktrees. Check `pgrep -fc '[s]cripts/audit\.py'` before each audit invocation — the `[s]` bracket makes the pattern unable to match any command line that merely CONTAINS it (a check command's own text reads `[s]cripts/...`, which the regex does not accept), which is what stops an enclosing `bash -c "… pattern …"` from counting itself. `--budget 30` for single corpus builds; the gate's 60 s and 15 s as Task 8 states them.
  - **Correction, measured on this box (Task 8).** An earlier revision of this bullet warned that `pgrep -f` "matches its OWN command line and always returns a hit" and prescribed `ps -eo args | grep -cE 'scripts/audit\.py'` instead. **That is backwards.** `pgrep` excludes its own PID (procps-ng 4.0.6 here, as do the BSDs), so it never self-matches; the only false positive it can produce is an *enclosing* shell whose argv contains the pattern, which the `[s]` form removes. What genuinely self-matches is the prescribed replacement, because `ps -eo args` lists the pipeline's own `grep`. Reading it literally cost Task 8 a wasted detached checkout. Verified here: with 9 real audit processes running, `pgrep -af 'scripts/audit\.py'` returned exactly those 9 and did not include the invoking shell. Avoid `pgrep -fc 'python[0-9.]* +[^ ]*scripts/audit\.py'` as the primary form: it is also self-match-proof but it matched only 2 of those 9, missing the forkserver children.
- **Record `(uptime; vmstat 1 3 | tail -1)` into a `-load.txt` beside EVERY timing.** The box is 128 cores, never idle, and the load is I/O wait; never wait for an idle box.
- **Reading code: use Serena's symbolic tools** — `mcp__serena__get_symbols_overview` and `mcp__serena__find_symbol` to read a symbol instead of paging a 22k-line file, `mcp__serena__find_referencing_symbols` to find call sites (grep misses them). **Editing: use Read/Edit, NOT Serena's editing tools.** Serena is a shared last-activation-wins server on this box and other agents are working in sibling worktrees; a Serena write from here can land in the wrong worktree.
- **Process discipline:** work in `.claude/worktrees/hierarchical-v3` on branch `hierarchical-v3`; never `git stash`; never commit anything under `.superpowers/`; evidence goes to `docs/superpowers/evidence/2026-09-07-hierarchical-v3/`, any size — file size is never a reason to shrink or omit committed evidence. `git diff` is wired to difftastic: use `--no-ext-diff` for patches.
- **Verification per code change:** `uv run ruff check` 0, `uv run ruff format --check` 0, `uv run mypy src` 0, and the touched test files exit 0.
- **The pytest summary line never prints here — judge by the EXIT CODE.** There is a 120 s `pytest-timeout` backstop that hard-kills a run.
- **Known red on master, not caused by this branch:** `tests/layout/test_sequence_pair.py::test_two_stage_alignment_retains_cp_sat_direct_opportunity`. Load flakes: `tests/test_pipeline.py::test_all_products_sequence_pair_honours_the_exact_layout_deadline`, `tests/layout/test_strategy_race.py::test_the_real_pool_races_both_arms_end_to_end`.
- **Large URLs:** `docs/superpowers/evidence/2026-09-05-speedups-2/large-urls/urls.txt` (belt3, zurl2, mall) plus the titanium-glass mall URL in `docs/superpowers/evidence/2026-09-06-debug-url/README.md`. Best-known dense areas: belt3 all-products 12408; zurl2 all-products 40905; titanium-glass all-products 5727 (sequence-pair, `best` at 30 s). The mall has no best-known area.
- **As-shipped constants this plan starts from** (gate.md §8): `SETTLEMENT_RESERVE_MIN_S = 5.0`, `_MAX = 40.0`, `_SHARE = 0.4`; `_POOL_CAP = 32`, `_BLOCK_WORKERS = 4`; `BLOCK_BUDGET_MIN_S = 5.0`, `_MAX_S = 20.0`; `MAX_RESPLIT_ATTEMPTS = 4` **per block, with no global round bound**; `partition.STRIP_CAP_DEFAULT = 12` counting PACKED strips; `compose.GAP_LADDER = (2, 4, 6, 8, 12, 16)`, `LADDER_WALL_SHARE = 0.4`, `MIN_GAP = 2`.

## File Structure

| file | responsibility after this plan |
| --- | --- |
| `src/flab2bp/layout/hierarchy/strategy.py` | orchestration only. Gains: a `_StrategyStats` accumulator carried into every refusal; `MAX_RECUT_ROUNDS` and the `rounds_left` funding arithmetic; per-block arm dispatch and the widen-arms-before-split fallback; the documented `_solve_block` seam contract |
| `src/flab2bp/layout/hierarchy/dispatch.py` | **new.** The block-level feature vector (`strips`, `coaters`, `items_above_one_belt`) and the arm-choice rule read off `2026-09-06-exp-features`. Pure functions, no I/O, no placer import at module scope |
| `src/flab2bp/layout/hierarchy/compose.py` | packing + composition. Gains `_trunk_goals`, passes them to the reservation, and funds rung 0's reservation out of `RESERVE_WALL_SHARE` with a documented degradation to the local-only oracle |
| `src/flab2bp/layout/freeform.py` | the router. `_reserve_port_access` gains an optional per-demand `goals` mapping; `boundary` keeps working exactly as it does for freeform's own callers |
| `src/flab2bp/layout/base.py` | `PlacementStats` gains nine hierarchical keys |
| `src/flab2bp/cli.py` | prints each attempt failure's stats on the refusal path |
| `tests/layout/hierarchy/test_dispatch.py` | **new.** Arm-choice rule tests |
| `tests/layout/hierarchy/test_strategy.py`, `test_compose.py` | funding, dispatch, goals |
| `tests/layout/test_freeform.py` | `_reserve_port_access(goals=...)` |
| `tests/test_cli.py` | the refusal-path stats line |
| `docs/superpowers/evidence/2026-09-07-hierarchical-v3/` | Task 6's oracle measurement, Task 7's spike (if run), Task 8's gate |

---

### Task 1: The `_solve_block` seam, and every gate number on the refusal path

**Lever:** A (observability), and the orchestrator role. gate.md R6/R15: `nogood_skips` is written only on the SUCCESS path and every cell of the v2 gate refused, so the key was unreachable in principle; `player_fed` and `gap` are "not exposed by any shipped surface"; the CLI "prints no `PlacementStats` key at all". This task makes the v3 gate read from the CLI instead of from a harness spy.

**Files:**
- Modify: `src/flab2bp/layout/base.py:243` (after `blocks: float`) and `:389` (after `resplits: float`)
- Modify: `src/flab2bp/layout/hierarchy/strategy.py:196-206` (the `_BlockJob` / seam docs), `:438-663` (`lay_out`), `:903-909` (`_refuser`)
- Modify: `src/flab2bp/cli.py:373-384`
- Test: `tests/layout/hierarchy/test_strategy.py`, `tests/test_cli.py`

**Interfaces:**

- Consumes: `NoValidLayout(reason, *, spec_label, budget_s, stats=...)` (`base.py:530-558`) — it ALREADY carries a `stats` mapping and `pipeline.py:1016-1021` already copies it into `LayoutAttemptFailure.stats`, which `pipeline.py:1272-1277` already threads into the outer `NoValidLayout.attempt_failures`. Nothing in `pipeline` changes.
- Produces, in `strategy.py`, the seam contract every future sub-solver plugs into. Write this verbatim as a module-level comment block immediately above `_BlockJob` (currently `strategy.py:196-200`):

```python
# THE SUB-SOLVER SEAM.  `hierarchical` is the ORCHESTRATOR (design
# §3.2-§3.3): it decides WHICH solver sees a block, at WHAT budget, and it
# composes the answers.  Everything a solver has to satisfy to be dispatched
# a block is on this page, and nothing in `partition`, `contracts` or
# `compose` needs to change to add one.
#
#   _BlockJob = (spec, arm, budget_s, vertical, workers, parent_deadline)
#     0 spec            a self-contained BuildSpec from `partition.sub_spec`:
#                       boundary items are `external_inputs`/`outputs`, belt
#                       tiers / sorter ladder / stack / piler travel verbatim,
#                       and `spray_lanes` is RECOMPUTED for the block.
#     1 arm             the solver's name, one of `BlockStrategyName`.
#     2 budget_s        the round's per-block wall, in seconds.
#     3 vertical        `belt_vertical_construction`; the composer's `ramped`
#                       is its negation.
#     4 workers         `_BLOCK_WORKERS` CP-SAT search workers for THIS block.
#     5 parent_deadline absolute `time.monotonic()` deadline, or None.  The
#                       WORKER combines it: `min(parent, start + budget_s)`.
#
#   _solve_block(job) -> (record, Placement | None)
#     record["strategy"] : str   the arm, echoed back
#     record["verdict"]  : str   "OK" | "REFUSED: ..." | "CRASH: ..."
#                                | "POOL FAILED: ..."  -- ONLY "REFUSED: " is
#                                remembered by `_ShapeNoGood`, because a crash
#                                or a dead pool says nothing about the SHAPE.
#     record["ok"]       : bool
#     record["wall_s"]   : float what the job actually spent (the memo records
#                                a refusal at THIS, not at the nominal budget)
#     record["area"]     : float on the OK path only
#     A refusal and a crash are RESULTS, not aborts: one block must never take
#     the other nine with it.
#
#   _block_layout(arm, *, vertical, workers) -> LayoutStrategy
#     THE REGISTRY POINT (design §3.2).  A new solver is added HERE, named in
#     `BlockStrategyName`, and given an arm-choice rule in
#     `hierarchy.dispatch`.  It must implement
#     `lay_out(spec, *, time_budget_s, absolute_deadline) -> Placement` and
#     raise `NoValidLayout` rather than return something invalid, and its
#     `Placement` must pickle (it crosses a spawn boundary).  Candidates
#     already named in `docs/speedup-idea-backlog.md`: the pre-generated block
#     library, a revived `spine`, coater-composite strips.
```

- Produces, in `strategy.py`, the accumulator:

```python
@dataclass
class _StrategyStats:
    """Every number the gate reads, accumulated as the build runs.

    Carried into the `NoValidLayout` of EVERY refusal, not just written onto
    a successful `Placement`: the v2 gate refused on all sixteen runs and
    could therefore read none of these from a shipped surface.
    """

    blocks: float = 0.0
    blocks_unattempted: float = 0.0
    recut_rounds: float = 0.0
    resplits: float = 0.0
    nogood_skips: float = 0.0
    player_fed: float = 0.0
    cut_lanes: float = 0.0
    compose_gap: float = 0.0
    port_demands: float = 0.0
    reservation_missing: float = 0.0
    unrouted_cuts: float = 0.0
    arm_dispatch_freeform: float = 0.0
    arm_dispatch_sequence_pair: float = 0.0
    arm_dispatch_both: float = 0.0

    def as_stats(self) -> dict[str, float]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def _refuser(
    spec: BuildSpec, budget_s: float, stats: _StrategyStats
) -> Callable[[str], NoValidLayout]:
    def refuse(reason: str) -> NoValidLayout:
        return NoValidLayout(
            reason, spec_label=spec.label, budget_s=budget_s, stats=stats.as_stats()
        )

    return refuse
```

Tasks 2, 3 and 5 fill in `recut_rounds`, `blocks_unattempted`, `arm_dispatch_*`, `compose_gap`, `port_demands`, `reservation_missing` and `unrouted_cuts`; this task ships the accumulator, the nine `PlacementStats` keys, the CLI print, and wires `blocks`, `resplits`, `nogood_skips`, `player_fed` and `cut_lanes` into it (the five that already exist as local counters in `lay_out`).

- [ ] **Step 1: Write the failing tests**

In `tests/layout/hierarchy/test_strategy.py`:

```python
def test_a_refusal_carries_the_strategy_stats(chain_spec, monkeypatch):
    """A build that never places a block still reports what it did."""
    def always_refuse(args):
        return ({"strategy": args[1], "verdict": "REFUSED: forced", "ok": False,
                 "wall_s": 0.0}, None)
    monkeypatch.setattr(strategy, "_solve_block", always_refuse)
    layout = HierarchicalLayout(
        belt_vertical_construction=True,
        band_policy=BandPolicy.parse("portable"),
        workers=8,
        strip_cap=2,
    )
    layout._executor_factory = ThreadPoolExecutor
    with pytest.raises(NoValidLayout) as caught:
        layout.lay_out(chain_spec, time_budget_s=40.0)
    stats = caught.value.stats
    assert stats["blocks"] >= 2.0
    assert "blocks_unattempted" in stats
    assert "recut_rounds" in stats
    assert "nogood_skips" in stats
    assert "player_fed" in stats
```

In `tests/test_cli.py`:

```python
def test_the_cli_prints_the_stats_of_every_refused_attempt(monkeypatch, capsys):
    """A refusal with no numbers is a refusal no gate can attribute."""
    failure = LayoutAttemptFailure(
        candidate="all-products",
        strategy="hierarchical",
        reason="22 block(s) never placed",
        stats=cast(PlacementStats, {"blocks_unattempted": 22.0, "recut_rounds": 2.0}),
    )

    def refuse(*args, **kwargs):
        raise NoValidLayout(
            "every strategy refused every candidate",
            spec_label="mall",
            budget_s=60.0,
            attempt_failures=(failure,),
        )

    monkeypatch.setattr(cli.pipeline, "build", refuse)
    exit_code = cli.main(
        ["https://factoriolab.github.io/dsp/flow?o=iron-ingot*60&v=11", "--budget", "1"]
    )
    assert exit_code == 3
    err = capsys.readouterr().err
    assert "blocks_unattempted=22" in err
    assert "recut_rounds=2" in err
```

- [ ] **Step 2: Run them, expect failure**

Run: `uv run pytest -q -p no:randomly tests/layout/hierarchy/test_strategy.py::test_a_refusal_carries_the_strategy_stats tests/test_cli.py::test_the_cli_prints_the_stats_of_every_refused_attempt`
Expected: exit code non-zero. The strategy test fails with `KeyError: 'blocks'` (today `NoValidLayout.stats` is `{}` on this path); the CLI test fails on `assert "blocks_unattempted=22" in err`.

- [ ] **Step 3: Add the nine `PlacementStats` keys**

In `src/flab2bp/layout/base.py`, after `blocks: float` (line 243):

```python
    #: Hierarchical strategy: blocks that never reached a placer at all --
    #: `_Entry.verdicts` still empty when the build refused.  Distinct from
    #: "never placed", which includes blocks a placer looked at and refused.
    blocks_unattempted: float
```

and after `resplits: float` (line 389) — one contiguous hierarchical block, next to the existing `nogood_skips`/`resplits` pair rather than scattered alphabetically, because those two already sit here:

```python
    #: Hierarchical strategy: how each block's arm was chosen.  `_both` counts
    #: the blocks raced on every arm because the feature vector fell outside
    #: what `2026-09-06-exp-features` covers, or because the dispatched arm
    #: refused and there was wall left to try the other.
    arm_dispatch_both: float
    arm_dispatch_freeform: float
    arm_dispatch_sequence_pair: float
    #: Hierarchical strategy: the `GAP_LADDER` rung the composition committed.
    compose_gap: float
    #: Hierarchical strategy: (block, item) entry heads left to the player
    #: under the both-fed lane contract.
    player_fed: float
    #: Hierarchical strategy: port-access demands the composed canvas raised.
    port_demands: float
    #: Hierarchical strategy: re-cut ROUNDS this build spent, bounded by
    #: `strategy.MAX_RECUT_ROUNDS`.  `resplits` counts the same rounds and is
    #: kept for continuity with the v1/v2 gates.
    recut_rounds: float
    #: Hierarchical strategy: demands the committed rung could not give a
    #: corridor to.  0 with a non-zero `unrouted_cuts` is the v2 finding: the
    #: oracle says every port is satisfiable and the router still refuses.
    reservation_missing: float
    #: Hierarchical strategy: cut lanes `compose` reported unwired.
    unrouted_cuts: float
```

- [ ] **Step 4: Add the seam comment and the accumulator**

In `src/flab2bp/layout/hierarchy/strategy.py`, insert the seam comment block from **Interfaces** immediately above `_BlockJob` (line 196), and add `_StrategyStats` and the new `_refuser` from **Interfaces** (replacing the existing `_refuser` at lines 903-909).

- [ ] **Step 5: Wire the accumulator through `lay_out`**

In `lay_out`, replace the five local counters with the accumulator. At line 453:

```python
        stats = _StrategyStats()
        refuse = _refuser(spec, max(0.0, deadline - started_at), stats)
```

Delete the `resplits = 0` and `nogood_skips = 0` locals (lines 459-460) and use `stats.resplits += 1` / `stats.nogood_skips += self._solve_round(...)` instead. After `entries` is first built (line 457) set `stats.blocks = float(len(entries))`, and re-set it at the top of each round after `entries = [entries[index] for index in order]` (line 499), so a refusal reports the GROWN count the message names. Immediately before every `raise refuse(...)` inside the round loop, set:

```python
                    stats.blocks_unattempted = float(
                        sum(1 for entry in entries if not entry.verdicts)
                    )
```

After `allocation = allocate_cuts(...)` (line 576) set `stats.player_fed = float(len(allocation.player_fed))` and `stats.cut_lanes = float(len(allocation.flows))`. After `composition = compose_mod.compose(...)` returns (line 587) set `stats.unrouted_cuts = float(len(composition.failures))`. Replace the `placement.stats.update({...})` block (lines 653-662) with:

```python
        placement.stats.update(
            {
                **stats.as_stats(),
                "block_wall_s": round(block_wall, 3),
                "compose_wall_s": round(compose_wall, 3),
            }
        )
```

- [ ] **Step 6: Print the stats from the CLI**

In `src/flab2bp/cli.py`, inside the `except NoValidLayout as exc:` handler (line 373), after the `projection_failures` loop (line 383) and before `return 3`:

```python
        for failure in exc.attempt_failures:
            if not failure.stats:
                continue
            numbers = " ".join(
                f"{key}={value:g}" if isinstance(value, int | float) else f"{key}={value}"
                for key, value in sorted(failure.stats.items())
            )
            pair = "/".join(part for part in (failure.strategy, failure.candidate) if part)
            print(f"  stats {pair}: {numbers}", file=sys.stderr)
```

- [ ] **Step 7: Run the tests, expect PASS**

Run: `uv run pytest -q -p no:randomly tests/layout/hierarchy tests/test_cli.py`
Expected: exit code 0.

- [ ] **Step 8: Verify the whole change**

Run: `uv run ruff check && uv run ruff format --check && uv run mypy src` — all three exit 0.
Then, one build, load sample first:

```bash
(uptime; vmstat 1 3 | tail -1) > /tmp/v3-t1-load.txt
uv run flab2bp "<mall url>" --strategy hierarchical --budget 60 \
    --candidate-policy all-products --band portable 2>&1 | tail -20
```

Expected: exit 3, and a `  stats hierarchical/all-products: ...` line naming `blocks_unattempted` with a non-zero value. Record that line in the task report; the v2 gate's §2.1 got this number from a harness spy.

- [ ] **Step 9: Commit**

```bash
git add src/flab2bp/layout/base.py src/flab2bp/layout/hierarchy/strategy.py \
        src/flab2bp/cli.py tests/layout/hierarchy/test_strategy.py tests/test_cli.py
git commit -m "feat(hierarchy): carry the strategy's stats into every refusal and print them"
```

---

### Task 2: Bound the re-cut rounds and fund the blocks that exist

**Lever:** A. gate.md §2.2: `mall/all-products` refuses with **22 blocks never placed** at 8.0 s over 2 waves, `mall/no-proliferator` with **45** at 13.8 s over 3 waves, `belt3/all-products` at 15 s with 3 blocks at **-1.5 s** — already 1.5 s inside the reserve it held back. `share = remaining / waves` is computed against a block count `_recut` keeps growing (19 -> 22, 24 -> 45) and `MAX_RESPLIT_ATTEMPTS` is per block with no global round bound (gate §8).

**The arithmetic, written out and checked against the mall's numbers.** `settlement_reserve_s(60) = min(40, max(5, 0.4 * 60)) = 24.0 s`; `settlement_reserve_s(15) = min(40, max(5, 6.0)) = 6.0 s`. `_pool_width()` on this box `= max(1, min(32, 128 // 4)) = 32`. Write `rounds_wall` for the wall the round loop has at build start (`deadline - started_at - reserve`, i.e. budget minus reserve minus the partition's own wall) and `remaining` for what is left when a round is dispatched.

The new rule, in three parts:

1. **`allowed_recut_rounds`, computed ONCE at build start**, is how many extra rounds the wall can actually hold at the floor:
   `allowed = min(MAX_RECUT_ROUNDS, max(0, int(rounds_wall // BLOCK_BUDGET_MIN_S) - 1))` with `MAX_RECUT_ROUNDS = 2`.
2. **`rounds_left = 1 + allowed_recut_rounds - recut_rounds`** — the round about to run, plus the re-cuts still permitted. `share = remaining / rounds_left / waves`.
3. **A round is refused only when it cannot afford the FLOOR at all** (`remaining / waves < BLOCK_BUDGET_MIN_S`), and **the seed round is never refused for funding**: with no block yet attempted, `share` is floored to `BLOCK_BUDGET_MIN_S` and the round runs. `block_budget = min(MAX, max(MIN, share))` as today.

Checked on the four cells the gate measured, with Task 3's one-arm dispatch (`jobs = blocks`) and, for contrast, both arms (`jobs = 2 * blocks`):

| cell | reserve | `rounds_wall` | `allowed` | round | blocks / jobs / waves | `remaining` | `rounds_left` | `share` | verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mall/all-products @60, ONE arm | 24.0 | 35.1 | `min(2, 7-1)=2` | 1 | 19 / 19 / 1 | 35.1 | 3 | **11.7** | funded |
| | | | | 2 | 22 / 22 / 1 | 23.0 | 2 | **11.5** | funded |
| | | | | 3 | 22 / 22 / 1 | 11.5 | 1 | **11.5** | funded; every block attempted |
| mall/no-proliferator @60, ONE arm | 24.0 | 35.0 | 2 | 1 | 24 / 24 / 1 | 35.0 | 3 | **11.7** | funded |
| | | | | 2 | 45 / 45 / **2** | 23.0 | 2 | **5.75** | funded |
| | | | | 3 | 45 / 45 / 2 | 17.0 | 1 | **8.5** | funded; every block attempted |
| mall/no-proliferator @60, BOTH arms | 24.0 | 35.0 | 2 | 1 | 24 / 48 / 2 | 35.0 | 3 | **5.83** | funded |
| | | | | 2 | 45 / 90 / **3** | 23.0 | 2 | **3.83** | **REFUSED** (under the 5.0 floor) |
| titanium-glass @15, ONE arm | 6.0 | 8.7 | `min(2, 1-1)=0` | 1 | 6 / 6 / 1 | 8.7 | **1** | **8.7** | funded, IDENTICAL to today |
| belt3/all-products @15, ONE arm | 6.0 | 8.7 | 0 | 1 | 9 / 9 / 1 | 8.7 | **1** | **8.7** | funded; every seed block attempted, then no re-cut is permitted at all |

Three readings this table forces, and they are why the rule is shaped this way:

* **`allowed = 0` at 15 s is what protects the web-UI path.** `rounds_wall // 5 - 1 = 0`, so `rounds_left` is 1, the seed round gets the whole wall exactly as it does today (8.7 s, not 8.7/3), and there is no re-cut round to be starved by. That IS "attempt every seed block at least once before any re-cut" — structurally, not as a special case. A build that then still has a refusing block refuses naming that, with `blocks_unattempted = 0`.
* **`mall/no-proliferator` is the cell the one-arm dispatch is load-bearing for.** With both arms its round 2 is 3 waves and `3.83 < 5.0` — today's failure, reproduced by the new rule. With one arm it is 2 waves and `5.75`. Task 3 is not an optimisation here; it is what unlocks the cell.
* **`mall/all-products` would be unlocked by the divisor alone** (both arms: 35.1/3/2 = 5.85, 23.0/2/2 = 5.75, 11.5/1/2 = 5.75 — all above the floor). It is the second mall that needs both changes.

**Files:**
- Modify: `src/flab2bp/layout/hierarchy/strategy.py:46-100` (the constants list in the module docstring), `:175` (beside `MAX_RESPLIT_ATTEMPTS`), `:438-540` (`lay_out`'s round loop), `:892-900` (`_block_refusal`)
- Test: `tests/layout/hierarchy/test_strategy.py`

**Interfaces:**
- Consumes: `_StrategyStats` and the `_refuser(spec, budget_s, stats)` signature from Task 1.
- Produces:

```python
#: Global bound on how many times ONE BUILD may re-cut, however many blocks
#: refuse.  `MAX_RESPLIT_ATTEMPTS` is per BLOCK and does not bound this: a
#: child created by a re-cut starts at attempt 0, so a build can grow its
#: block list without limit -- v2 measured 19 seed blocks becoming 22
#: unattempted and 24 becoming 45, each round's wall divided by a count the
#: previous round grew.
MAX_RECUT_ROUNDS = 2


def allowed_recut_rounds(rounds_wall_s: float) -> int:
    """How many re-cut rounds this wall can hold at the floor.

    A re-cut round that cannot be given `BLOCK_BUDGET_MIN_S` per wave is a
    round that will refuse the moment it is dispatched, and reserving wall
    for it only takes that wall away from the round that CAN run.  At the web
    UI's 15 s this is 0, which is what keeps the seed round's share at the
    whole `rounds_wall` rather than a third of it.
    """
    return min(MAX_RECUT_ROUNDS, max(0, int(rounds_wall_s // BLOCK_BUDGET_MIN_S) - 1))
```

- [ ] **Step 1: Write the failing tests**

```python
def test_allowed_recut_rounds_is_zero_when_the_wall_holds_one_round():
    # 15 s budget: reserve 6.0, so the round loop has ~9 s -- one round.
    assert strategy.allowed_recut_rounds(8.7) == 0
    assert strategy.allowed_recut_rounds(12.0) == 1
    assert strategy.allowed_recut_rounds(35.1) == strategy.MAX_RECUT_ROUNDS


def test_the_seed_round_keeps_the_whole_wall_when_no_recut_is_affordable(
    chain_spec, monkeypatch
):
    """The web-UI path: a 15 s build must not fund rounds it can never run."""
    seen: list[float] = []
    real = strategy._solve_block

    def spy(args):
        seen.append(args[2])
        return real(args)

    monkeypatch.setattr(strategy, "_solve_block", spy)
    layout = HierarchicalLayout(
        belt_vertical_construction=True,
        band_policy=BandPolicy.parse("portable"),
        workers=8,
        strip_cap=2,
    )
    layout._executor_factory = ThreadPoolExecutor
    layout.lay_out(chain_spec, time_budget_s=15.0)
    # reserve 6.0, ~9 s of round, one wave -> the whole wall, not a third.
    assert seen and min(seen) > 2 * strategy.BLOCK_BUDGET_MIN_S


def test_a_build_stops_re_cutting_after_the_global_bound(chain_spec, monkeypatch):
    """`MAX_RESPLIT_ATTEMPTS` is per block; this bound is per build."""
    rounds: list[int] = []

    def always_refuse(args):
        rounds.append(1)
        return ({"strategy": args[1], "verdict": "REFUSED: forced", "ok": False,
                 "wall_s": 0.0}, None)

    monkeypatch.setattr(strategy, "_solve_block", always_refuse)
    layout = HierarchicalLayout(
        belt_vertical_construction=True,
        band_policy=BandPolicy.parse("portable"),
        workers=8,
        strip_cap=1,
    )
    layout._executor_factory = ThreadPoolExecutor
    with pytest.raises(NoValidLayout) as caught:
        layout.lay_out(chain_spec, time_budget_s=60.0)
    assert caught.value.stats["recut_rounds"] <= float(strategy.MAX_RECUT_ROUNDS)
    assert "re-cut round" in caught.value.reason


def test_a_round_that_cannot_afford_the_floor_names_the_wall_not_the_waves(
    chain_spec, monkeypatch
):
    def always_refuse(args):
        return ({"strategy": args[1], "verdict": "REFUSED: forced", "ok": False,
                 "wall_s": 0.0}, None)

    monkeypatch.setattr(strategy, "_solve_block", always_refuse)
    layout = HierarchicalLayout(
        belt_vertical_construction=True,
        band_policy=BandPolicy.parse("portable"),
        workers=8,
        strip_cap=2,
    )
    layout._executor_factory = ThreadPoolExecutor
    with pytest.raises(NoValidLayout) as caught:
        layout.lay_out(chain_spec, time_budget_s=9.0)
    # The seed round runs anyway: nothing was attempted, so nothing is refused
    # for funding before a placer has seen a single block.
    assert caught.value.stats["blocks_unattempted"] == 0.0
```

- [ ] **Step 2: Run them, expect failure**

Run: `uv run pytest -q -p no:randomly tests/layout/hierarchy/test_strategy.py -k "allowed_recut or seed_round_keeps or global_bound or afford_the_floor"`
Expected: non-zero exit; `AttributeError: module 'flab2bp.layout.hierarchy.strategy' has no attribute 'allowed_recut_rounds'`.

- [ ] **Step 3: Implement**

Add `MAX_RECUT_ROUNDS` and `allowed_recut_rounds` from **Interfaces** next to `MAX_RESPLIT_ATTEMPTS` (`strategy.py:175`). In `lay_out`, immediately after `reserve = settlement_reserve_s(time_budget_s)` (line 454):

```python
        # Computed ONCE, before the partition, from the wall the ROUND LOOP
        # will have: re-planning it each round would let a slow round argue
        # itself more re-cuts.
        rounds_wall = max(0.0, deadline - time.monotonic() - reserve)
        allowed_recuts = allowed_recut_rounds(rounds_wall)
        recut_rounds = 0
```

Replace the funding block (`strategy.py:503-518`) with:

```python
                jobs = sum(len(self._arms_for(entries[index])) for index in todo)
                waves = math.ceil(jobs / width)
                remaining = deadline - time.monotonic() - reserve
                attempted = any(entry.verdicts for entry in entries)
                # FUND THE ROUNDS THAT CAN STILL RUN, not the wall divided by
                # a block count the NEXT round will have grown.  `rounds_left`
                # is this round plus the re-cuts still permitted.
                rounds_left = 1 + allowed_recuts - recut_rounds
                share = remaining / rounds_left / waves
                if remaining / waves < BLOCK_BUDGET_MIN_S:
                    if attempted:
                        stats.blocks_unattempted = float(
                            sum(1 for entry in entries if not entry.verdicts)
                        )
                        raise refuse(
                            _block_refusal(
                                entries,
                                todo,
                                why=(
                                    f"{remaining:.1f}s left over {waves} wave(s) is under "
                                    f"the {BLOCK_BUDGET_MIN_S:g}s a block solve is given "
                                    f"at all"
                                ),
                            )
                        )
                    # THE SEED ROUND ALWAYS RUNS.  A build that refuses having
                    # attempted nothing tells nobody anything, and the job's
                    # own deadline is still clipped to the parent's, so the
                    # floor can only spend into the settlement reserve, never
                    # past `--budget`.
                    share = BLOCK_BUDGET_MIN_S
                block_budget = min(BLOCK_BUDGET_MAX_S, max(BLOCK_BUDGET_MIN_S, share))
```

Replace the re-cut tail (`strategy.py:530-539`) with:

```python
                still = [index for index in todo if entries[index].placement is None]
                if not still:
                    break
                if recut_rounds >= allowed_recuts:
                    stats.blocks_unattempted = float(
                        sum(1 for entry in entries if not entry.verdicts)
                    )
                    raise refuse(
                        _block_refusal(
                            entries,
                            still,
                            why=(
                                f"out of re-cut round(s) after {recut_rounds} of "
                                f"{allowed_recuts} the {rounds_wall:.1f}s round wall allows"
                            ),
                        )
                    )
                grown, progress = _recut(
                    entries, still, nogood=nogood, arms=self._arms(), budget_s=block_budget
                )
                if not progress:
                    stats.blocks_unattempted = float(
                        sum(1 for entry in entries if not entry.verdicts)
                    )
                    raise refuse(_block_refusal(entries, still, why="out of re-cut attempts"))
                entries = grown
                recut_rounds += 1
                stats.recut_rounds = float(recut_rounds)
                stats.resplits = float(recut_rounds)
```

`self._arms_for(entry)` is Task 3's; **until Task 3 lands, define it in this task as `def _arms_for(self, entry: _Entry) -> tuple[str, ...]: return self._arms()`** so this task is independently testable and Task 3 replaces only the body.

Update the module docstring's constants list (`strategy.py:75-77`) so the `MAX_RESPLIT_ATTEMPTS` bullet reads:

```
* ``MAX_RESPLIT_ATTEMPTS = 4`` is counted PER BLOCK, not as a global round
  bound: a child created by a re-cut starts at attempt 0.  The GLOBAL bound
  is ``MAX_RECUT_ROUNDS = 2``, floored further by
  :func:`allowed_recut_rounds` to what the round wall can actually hold at
  ``BLOCK_BUDGET_MIN_S`` -- 0 at the web UI's 15 s, which is what gives the
  seed round the whole wall there (v3 Task 2).
* Per round, ``block_budget = clamp(remaining / rounds_left / waves, 5, 20)``
  seconds, where ``rounds_left`` is this round plus the re-cuts still
  permitted.  Dividing by ``waves`` alone let one round spend the wall the
  NEXT round -- against a block count that round had grown -- would need:
  v2 measured both malls refusing with 22 and 45 blocks never placed.
```

- [ ] **Step 4: Run the tests, expect PASS**

Run: `uv run pytest -q -p no:randomly tests/layout/hierarchy` — exit 0.
Then `uv run ruff check && uv run ruff format --check && uv run mypy src` — all 0.

- [ ] **Step 5: Measure the two malls and the 15 s path**

One build at a time, each with its load sample:

```bash
for cell in "mall all-products 60" "mall no-proliferator 60" "titanium-glass all-products 15"; do
  set -- $cell
  (uptime; vmstat 1 3 | tail -1) > /tmp/v3-t2-$1-$2-$3-load.txt
  uv run flab2bp "<url for $1>" --strategy hierarchical --budget $3 \
      --candidate-policy $2 --band portable > /dev/null 2> /tmp/v3-t2-$1-$2-$3.log
done
```

Expected and recorded in the task report: both malls' `stats hierarchical/...` lines show `blocks_unattempted=0`, and the refusal (if any) names composition or the router rather than the funding rule; titanium-glass at 15 s still composes all 6 blocks. **If titanium-glass at 15 s regresses to fewer blocks placed than v2's 6, stop and report it** — the `allowed = 0` branch is exactly what is supposed to prevent that, and a regression means the arithmetic above is wrong rather than the cell being hard.

- [ ] **Step 6: Commit**

```bash
git add src/flab2bp/layout/hierarchy/strategy.py tests/layout/hierarchy/test_strategy.py
git commit -m "fix(hierarchy): bound re-cut rounds and fund the blocks that exist at dispatch"
```

---

### Task 3: One arm per block, dispatched from the routing-difficulty feature key

**Lever:** A, and the orchestrator role (design §3.1-§3.3: a feature vector computed before any placement, and the cheapest solver that meets the floor rather than always racing). Every block today is funded for BOTH arms (`strategy._arms()` returns `("freeform", "sequence-pair")` under `block_strategy == "best"`), which doubles `jobs` and therefore `waves`; Task 2's table shows that is the difference between 2 and 3 waves on `mall/no-proliferator`'s second round, and between `5.75` and `3.83` seconds a block.

**The rule, read off the evidence, not invented.** `docs/superpowers/evidence/2026-09-06-exp-features/README.md` §4(b) item 3 names `coaters` as "the arm-choice feature" and gives the cross-tab of mean freeform/sequence-pair AREA RATIO (below 1.0 means freeform packs smaller):

| mean ff/sp area ratio | `coaters = 0` | `coaters > 0` |
| --- | --- | --- |
| `strips <= 6` | 1.059 (n=7) | **0.987 (n=15)** |
| `strips > 6` | 1.399 (n=5) | 1.142 (n=10) |

"Freeform wins only in the coated, small cell" — so `coaters > 0 and strips <= 6` dispatches `freeform`, and every other cell dispatches `sequence-pair`. Experiment 5's "Arm choice" section re-tested this against the whole pressure family and concluded "Arm choice stays with `coaters`"; nothing displaces it. The two axes partition the space, so coverage is not about them — it is about the two places the same evidence explicitly declines to speak about a placer at all:

* **`items_above_one_belt >= 8`** — README §4(a): "the only rule in the entire sweep that never fires on a spec that builds", precision 1.00 on the large URLs, and §4(b) item 2 plus "What this suggests next": this branch "argues for a different intervention (split lanes, upgrade tiers) rather than more seconds", and four of the nine refusals behind it are `flow.belt_capacity`. No arm was observed succeeding here. **Race both.**
* **`strips >= 85`** — the refusal rule (F1 0.95), and far above the largest spec in any cross-tab cell. **Race both.**

Both thresholds are copied from that README verbatim. Its own caveat — "Treat the thresholds (436 machines, 85 strips, 8 over-belt items) as *this evidence's* boundaries, not as constants" — is why they are named constants with the citation on them, and why the fallback below exists.

**The fallback, which is the other half of the rule.** A block whose dispatched arm REFUSES is re-offered to the FULL arm set in the next round, before `split_block` is spent on it: widening the arms is strictly cheaper than growing the block list, and it is the "escalate only while the incumbent is outside the band" of design §3.3. Only when a block has been offered every arm does `_recut` cut it.

**Files:**
- Create: `src/flab2bp/layout/hierarchy/dispatch.py`
- Create: `tests/layout/hierarchy/test_dispatch.py`
- Modify: `src/flab2bp/layout/hierarchy/strategy.py:398-410` (`_Entry`), `:665-669` (`_arms`), `:684-829` (`_solve_round`), `:832-889` (`_recut` / `_next_cut`)
- Test: `tests/layout/hierarchy/test_strategy.py`

**Interfaces:**
- Consumes: `partition.sub_spec(spec, block, index) -> BuildSpec` (`partition.py:259`), `freeform.plan_strips(spec, *, strip_len=6, band_policy=_DEFAULT_BAND_POLICY) -> list[Strip]` (`freeform.py:2469`), `BuildSpec.spray_lanes` (`spec.py:189`), `BuildSpec.belt_tiers` (`spec.py:304`), `BuildSpec.belt_stack` (`spec.py:161`), `strategy.ShapeKey` and `strategy.shape_key(units)` (`strategy.py:356-366`).
- Produces, in `dispatch.py`:

```python
ARM_FREEFORM = "freeform"
ARM_SEQUENCE_PAIR = "sequence-pair"

#: The `strips` axis of the arm cross-tab in
#: `docs/superpowers/evidence/2026-09-06-exp-features/README.md` §4(b): the
#: table's rows are `strips <= 6` and `strips > 6`.
ARM_SMALL_STRIPS = 6
#: `items_above_one_belt` at or above which that evidence has no arm to
#: recommend: it is the only precision-1.00 refusal rule in the sweep, no
#: spec at or above it was ever observed building on EITHER arm, and the
#: README's own reading is that this branch needs lane splitting or a
#: belt-tier decision rather than a placer choice.
UNCOVERED_ITEMS_ABOVE_ONE_BELT = 8
#: `strips` at or above which the same evidence's refusal rule fires
#: (`strips >= 85`, F1 0.95) -- far outside every cell of the arm cross-tab.
UNCOVERED_STRIPS = 85


@dataclass(frozen=True, slots=True)
class BlockFeatures:
    """The three dispatch-key features that are cheap on ONE block."""

    strips: int
    coaters: int
    items_above_one_belt: int


def lane_capacity(spec: BuildSpec) -> Fraction: ...
def item_flows(spec: BuildSpec) -> dict[str, Fraction]: ...
def block_features(sub: BuildSpec) -> BlockFeatures: ...
def dispatch_arms(features: BlockFeatures, arms: tuple[str, ...]) -> tuple[str, ...]: ...
```

- Produces, in `strategy.py`: `_Entry` gains `arms_tried: frozenset[str] = frozenset()`; `HierarchicalLayout` gains

```python
def _arms_for(self, spec: BuildSpec, entry: _Entry) -> tuple[str, ...]: ...
```

returning the arms THIS block is dispatched to this round, and `_solve_round` keys its jobs by `(shape, arm)` over `self._arms_for(...)` rather than `self._arms()`.

- [ ] **Step 1: Write the failing tests**

`tests/layout/hierarchy/test_dispatch.py`:

```python
"""The arm-choice rule, read off `2026-09-06-exp-features`.

Every threshold here is that evidence's; nothing is tuned locally.  The
cross-tab it implements is README §4(b) item 3.
"""

from __future__ import annotations

from fractions import Fraction

from flab2bp.layout.hierarchy import dispatch
from flab2bp.layout.hierarchy.dispatch import BlockFeatures

_BOTH = ("freeform", "sequence-pair")


def test_a_small_coated_block_goes_to_freeform_alone():
    # cross-tab cell `coaters > 0, strips <= 6`: mean ff/sp ratio 0.987
    got = dispatch.dispatch_arms(
        BlockFeatures(strips=5, coaters=2, items_above_one_belt=0), _BOTH
    )
    assert got == ("freeform",)


def test_a_small_uncoated_block_goes_to_sequence_pair_alone():
    # cell `coaters = 0, strips <= 6`: 1.059 -- freeform is the larger pack
    got = dispatch.dispatch_arms(
        BlockFeatures(strips=5, coaters=0, items_above_one_belt=0), _BOTH
    )
    assert got == ("sequence-pair",)


def test_a_large_block_goes_to_sequence_pair_whether_or_not_it_is_coated():
    for coaters in (0, 3):
        got = dispatch.dispatch_arms(
            BlockFeatures(strips=11, coaters=coaters, items_above_one_belt=0), _BOTH
        )
        assert got == ("sequence-pair",), coaters


def test_a_block_above_the_belt_capacity_branch_races_both_arms():
    got = dispatch.dispatch_arms(
        BlockFeatures(strips=5, coaters=2, items_above_one_belt=8), _BOTH
    )
    assert got == _BOTH


def test_a_block_bigger_than_the_evidence_covers_races_both_arms():
    got = dispatch.dispatch_arms(
        BlockFeatures(strips=85, coaters=0, items_above_one_belt=0), _BOTH
    )
    assert got == _BOTH


def test_an_explicit_single_arm_is_never_widened():
    got = dispatch.dispatch_arms(
        BlockFeatures(strips=200, coaters=0, items_above_one_belt=99), ("freeform",)
    )
    assert got == ("freeform",)


def test_items_above_one_belt_uses_the_fastest_tier_and_the_cargo_stack(chain_spec):
    # `lane_capacity` is `max(tier.items_per_second) * belt_stack`, the same
    # threshold `validate`'s `flow.belt_capacity` uses.
    capacity = dispatch.lane_capacity(chain_spec)
    assert capacity == Fraction(6) * chain_spec.belt_stack
    assert dispatch.block_features(chain_spec).items_above_one_belt == 0


def test_block_features_counts_the_blocks_own_spray_lanes(chain_spec):
    assert dispatch.block_features(chain_spec).coaters == len(chain_spec.spray_lanes)
```

`tests/layout/hierarchy/test_strategy.py`:

```python
def test_a_dispatched_block_is_offered_one_arm_not_two(chain_spec, monkeypatch):
    arms: list[str] = []
    real = strategy._solve_block

    def spy(args):
        arms.append(args[1])
        return real(args)

    monkeypatch.setattr(strategy, "_solve_block", spy)
    layout = HierarchicalLayout(
        belt_vertical_construction=True,
        band_policy=BandPolicy.parse("portable"),
        workers=8,
        strip_cap=2,
    )
    layout._executor_factory = ThreadPoolExecutor
    placement = layout.lay_out(chain_spec, time_budget_s=40.0)
    assert len(set(arms)) == 1, f"both arms were funded: {sorted(set(arms))}"
    dispatched = (
        placement.stats["arm_dispatch_freeform"]
        + placement.stats["arm_dispatch_sequence_pair"]
    )
    assert dispatched == placement.stats["blocks"]
    assert placement.stats["arm_dispatch_both"] == 0.0


def test_a_refused_block_is_offered_the_other_arm_before_it_is_cut(
    chain_spec, monkeypatch
):
    """Widening the arms is cheaper than growing the block list."""
    cut = []
    real_next_cut = strategy._next_cut

    def watch(entry, **kw):
        cut.append(strategy.shape_key(entry.units))
        return real_next_cut(entry, **kw)

    monkeypatch.setattr(strategy, "_next_cut", watch)
    seen: list[str] = []
    real = strategy._solve_block

    def refuse_first_arm(args):
        seen.append(args[1])
        if len(seen) <= 2:
            return ({"strategy": args[1], "verdict": "REFUSED: forced", "ok": False,
                     "wall_s": 0.0}, None)
        return real(args)

    monkeypatch.setattr(strategy, "_solve_block", refuse_first_arm)
    layout = HierarchicalLayout(
        belt_vertical_construction=True,
        band_policy=BandPolicy.parse("portable"),
        workers=8,
        strip_cap=2,
    )
    layout._executor_factory = ThreadPoolExecutor
    layout.lay_out(chain_spec, time_budget_s=40.0)
    assert len(set(seen)) == 2, "the other arm was never tried"
    assert not cut, "a block was cut before every arm had been offered"
```

- [ ] **Step 2: Run them, expect failure**

Run: `uv run pytest -q -p no:randomly tests/layout/hierarchy/test_dispatch.py tests/layout/hierarchy/test_strategy.py -k "dispatch or other_arm"`
Expected: non-zero exit; `ModuleNotFoundError: No module named 'flab2bp.layout.hierarchy.dispatch'`.

- [ ] **Step 3: Write `dispatch.py`**

```python
"""Which sub-solver sees a block, chosen before any placer runs.

`hierarchical` is the ORCHESTRATOR (design
`docs/superpowers/specs/2026-09-06-multi-solver-orchestrator-design.md`
§3.1-§3.3): the feature vector is computed once, from the rate solution plus
one strip plan, and the cheapest solver that meets the class's floor is run
FIRST rather than every solver being run always.

THE RULE IS READ OFF EVIDENCE, NOT TUNED HERE.
`docs/superpowers/evidence/2026-09-06-exp-features/README.md` §4(b) item 3
names `coaters` "the arm-choice feature" and cross-tabs the mean freeform /
sequence-pair AREA RATIO against `coaters` and `strips`:

    ratio          coaters = 0        coaters > 0
    strips <= 6    1.059 (n=7)        0.987 (n=15)
    strips >  6    1.399 (n=5)        1.142 (n=10)

A ratio below 1.0 is a freeform win, and there is exactly one such cell.
Experiment 5 re-tested this against the whole live-range and pressure family
and concluded "Arm choice stays with `coaters`".

WHY THERE IS STILL A BOTH-ARMS FALLBACK.  That README's own caveat is that
its thresholds are "this evidence's boundaries, not constants", fitted on 9
refusals over 3 URLs.  So two regions where it explicitly declines to
recommend a placer race both arms (see `UNCOVERED_*`), and `strategy`
re-offers the full arm set to any block whose dispatched arm refused while
wall remains -- escalation, which is design §3.3's rule, rather than a
speculative race up front.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from flab2bp.spec import BuildSpec

ARM_FREEFORM = "freeform"
ARM_SEQUENCE_PAIR = "sequence-pair"

ARM_SMALL_STRIPS = 6
UNCOVERED_ITEMS_ABOVE_ONE_BELT = 8
UNCOVERED_STRIPS = 85


@dataclass(frozen=True, slots=True)
class BlockFeatures:
    """The three dispatch-key features that are cheap on ONE block."""

    strips: int
    coaters: int
    items_above_one_belt: int


def lane_capacity(spec: BuildSpec) -> Fraction:
    """Items per second the FASTEST belt this save can build carries.

    The fastest tier, not the floor: `layout/belt_tiers.py` raises a run to
    the cheapest tier that carries its demand, so an item is only genuinely
    above one belt when the best available belt still cannot hold it.  This
    is the same threshold `validate`'s `flow.belt_capacity` uses, which is
    what makes the count comparable to a refusal reason.
    """
    best = max(tier.items_per_second for tier in spec.belt_tiers)
    return best * spec.belt_stack


def item_flows(spec: BuildSpec) -> dict[str, Fraction]:
    """Block-wide items/second per item: the larger of made and eaten."""
    produced: dict[str, Fraction] = {}
    consumed: dict[str, Fraction] = {}
    for group in spec.groups:
        for item_id, rate in group.outputs_per_machine.items():
            produced[item_id] = produced.get(item_id, Fraction(0)) + rate * group.count
        for item_id, rate in group.inputs_per_machine.items():
            consumed[item_id] = consumed.get(item_id, Fraction(0)) + rate * group.count
    for item_id, rate in spec.external_inputs.items():
        produced[item_id] = max(produced.get(item_id, Fraction(0)), rate)
    return {
        item_id: max(produced.get(item_id, Fraction(0)), consumed.get(item_id, Fraction(0)))
        for item_id in set(produced) | set(consumed)
    }


def block_features(sub: BuildSpec) -> BlockFeatures:
    """Score ONE block's own sub-spec.

    `plan_strips` is imported lazily, the same import-cycle shape
    `partition.strip_count` uses: `freeform` is a ~22k-line module and
    nothing else here needs it paid for up front.
    """
    from flab2bp.layout.freeform import plan_strips

    capacity = lane_capacity(sub)
    return BlockFeatures(
        strips=len(plan_strips(sub)),
        coaters=len(sub.spray_lanes),
        items_above_one_belt=sum(
            1 for flow in item_flows(sub).values() if flow > capacity
        ),
    )


def dispatch_arms(features: BlockFeatures, arms: tuple[str, ...]) -> tuple[str, ...]:
    """The arms this block is offered THIS round, narrowest first."""
    if len(arms) < 2:
        return arms
    if features.items_above_one_belt >= UNCOVERED_ITEMS_ABOVE_ONE_BELT:
        return arms
    if features.strips >= UNCOVERED_STRIPS:
        return arms
    if features.coaters > 0 and features.strips <= ARM_SMALL_STRIPS:
        return (ARM_FREEFORM,)
    return (ARM_SEQUENCE_PAIR,)


__all__ = [
    "ARM_FREEFORM",
    "ARM_SEQUENCE_PAIR",
    "ARM_SMALL_STRIPS",
    "UNCOVERED_ITEMS_ABOVE_ONE_BELT",
    "UNCOVERED_STRIPS",
    "BlockFeatures",
    "block_features",
    "dispatch_arms",
    "item_flows",
    "lane_capacity",
]
```

- [ ] **Step 4: Wire the dispatch into `strategy.py`**

Add `arms_tried: frozenset[str] = frozenset()` to `_Entry` (`strategy.py:398-410`), documented:

```python
    #: Arms this block has already been offered.  A block whose dispatched
    #: arm refused is re-offered the FULL set before `_recut` spends an
    #: attempt on it: widening the arms is strictly cheaper than growing the
    #: block list, and it is design §3.3's escalate-only-if-needed rule.
    arms_tried: frozenset[str] = frozenset()
```

Replace the Task-2 placeholder `_arms_for` with the real one, and add the per-build cache:

```python
    def _arms_for(self, spec: BuildSpec, entry: _Entry, cache: dict[ShapeKey, tuple[str, ...]]) -> tuple[str, ...]:
        """Which arms this block is offered this round.

        Cached on `ShapeKey` for the build: `sub_spec` is a pure function of
        the units (its `index` argument reaches only a diagnostic label -- see
        `_solve_round`'s docstring), so two same-shaped blocks score the same
        features, and `plan_strips` is the only expensive thing here.

        A block that has already been offered its dispatched arm and refused
        gets the FULL set.
        """
        arms = self._arms()
        if len(arms) < 2:
            return arms
        key = shape_key(entry.units)
        chosen = cache.get(key)
        if chosen is None:
            chosen = dispatch.dispatch_arms(
                dispatch.block_features(sub_spec(spec, entry.units, 0)), arms
            )
            cache[key] = chosen
        if entry.arms_tried >= set(chosen):
            return arms
        return chosen
```

In `lay_out`, create `arm_cache: dict[ShapeKey, tuple[str, ...]] = {}` beside `nogood` (line 463) and thread it into every `_arms_for` call. In `_solve_round`, replace `arms = self._arms()` (line 725) with a per-slot arm list:

```python
        arms_by_slot = [self._arms_for(spec, entries[index], arm_cache) for index in todo]
        shapes = [shape_key(entries[index].units) for index in todo]
        slots_by_key: dict[tuple[ShapeKey, str], list[int]] = {}
        for slot in range(len(todo)):
            for arm in arms_by_slot[slot]:
                slots_by_key.setdefault((shapes[slot], arm), []).append(slot)
```

and in the per-slot outcome loop (lines 821-828) replace `for arm in arms` with `for arm in arms_by_slot[slot]`, and record what was tried:

```python
        for slot, index in enumerate(todo):
            slot_arms = arms_by_slot[slot]
            outcomes = [
                outcome_by_key.get((shapes[slot], arm), skip_record) for arm in slot_arms
            ]
            winners = [placement for _record, placement in outcomes if placement is not None]
            entries[index].verdicts = tuple(
                str(record.get("verdict", "no verdict")) for record, _placement in outcomes
            )
            entries[index].arms_tried = entries[index].arms_tried | set(slot_arms)
            if winners:
                entries[index].placement = min(winners, key=lambda p: p.area)
```

Count the dispatch into `stats`, once per block per round, in `lay_out` immediately after `_solve_round` returns:

```python
                for index in todo:
                    chosen = self._arms_for(spec, entries[index], arm_cache)
                    if len(chosen) > 1:
                        stats.arm_dispatch_both += 1.0
                    elif chosen[0] == dispatch.ARM_FREEFORM:
                        stats.arm_dispatch_freeform += 1.0
                    else:
                        stats.arm_dispatch_sequence_pair += 1.0
```

Task 2's `jobs = sum(len(self._arms_for(entries[index])) for index in todo)` becomes `jobs = sum(len(self._arms_for(spec, entries[index], arm_cache)) for index in todo)` — this is what makes the wave arithmetic in Task 2's table real.

Finally, in `_recut` (`strategy.py:832-861`), skip a block that still has an untried arm — widening it is the next round's job, not a cut:

```python
    for index, entry in enumerate(entries):
        if index not in refusing:
            grown.append(entry)
            continue
        if not entry.arms_tried >= set(arms):
            # An arm this block has never been offered is cheaper than a cut.
            # Leaving the entry alone is `progress` because `_arms_for` will
            # widen it next round.
            grown.append(entry)
            progress = True
            continue
        children = _next_cut(entry, nogood=nogood, arms=arms, budget_s=budget_s)
```

- [ ] **Step 5: Run the tests, expect PASS**

Run: `uv run pytest -q -p no:randomly tests/layout/hierarchy` — exit 0.
Then `uv run ruff check && uv run ruff format --check && uv run mypy src` — all 0.

- [ ] **Step 6: Measure the malls again, and record the waves**

```bash
for cell in "mall all-products" "mall no-proliferator"; do
  set -- $cell
  (uptime; vmstat 1 3 | tail -1) > /tmp/v3-t3-$1-$2-load.txt
  uv run flab2bp "<url for $1>" --strategy hierarchical --budget 60 \
      --candidate-policy $2 --band portable > /dev/null 2> /tmp/v3-t3-$1-$2.log
done
```

Expected and recorded in the task report: both cells print `blocks_unattempted=0`, `arm_dispatch_freeform + arm_dispatch_sequence_pair + arm_dispatch_both` equal to `blocks`, and `arm_dispatch_both` small. Compare the measured `recut_rounds` against Task 2's table.

- [ ] **Step 7: Commit**

```bash
git add src/flab2bp/layout/hierarchy/dispatch.py src/flab2bp/layout/hierarchy/strategy.py \
        tests/layout/hierarchy/test_dispatch.py tests/layout/hierarchy/test_strategy.py
git commit -m "feat(hierarchy): dispatch one arm per block from the routing-difficulty key"
```

---

### Task 4: Give `_reserve_port_access` a per-demand goal

**Lever:** B, the headline finding. gate.md §6 lever 1, re-verified against master `1ce8a0d3` for this plan (the gate's own freeform line numbers were taken at `bf8b1f40` and are ~26 lines low on master — see this plan's report):

* `compose` calls `_port_access_inventory(packing.nets)` with no `boundary_inputs`/`boundary_outputs` (`compose.py:695`; the parameters exist and default to `()` at `freeform.py:11606-11607`), so every demand is `INTERNAL_DEPARTURE` or `INTERNAL_ARRIVAL` (`freeform.py:11634-11635`).
* Both answer `reaches_boundary` False (`freeform.py:11571-11576`).
* `_reserve_port_access` gates its ENTIRE reachability probe on that flag — `if boundary is None or not demand.kind.reaches_boundary:` takes the early continue for every demand (`freeform.py:11997-12000`) — and `assignment_boundary_cut` skips every non-boundary demand and always returns `None` (`freeform.py:12043-12045`).
* `compose` knows this and does not even build the ring: `boundary = _outer_ring(bounds) if any(d.kind.reaches_boundary for d in demands) else None` (`compose.py:712`) is always `None`.

So the ladder can only ever reject a LOCAL doorstep, which is exactly what §3.4 measured: the one time it fired, at cap 8, it rejected an `internal-arrival` on a cell-disjointness failure, gap 4 satisfied every port, **and the router still refused 8 cut lanes**. `GAP_LADDER`'s four upper rungs have never been exercised.

**The design decision, and why.** Neither of the brief's two options is taken as stated, because both are physically wrong for a composed canvas and the code says why. Passing the composed canvas's outer ring as `boundary_inputs`/`boundary_outputs` would RECLASSIFY a cut lane's head as `BOUNDARY_ARRIVAL` — but a cut lane does not arrive from outside the packing, it arrives from another block, and probing it to the rim asks a question whose answer does not constrain the trunk. Admitting internal demands into the probe against the rim has the same defect one layer down. What the router actually refuses is a TRUNK — `COMMIT_LINK`, `SEALED_POCKET`, `DYNAMIC_ACCESS` between a source block's port and a sink block's port — so the probe must be given that trunk's own endpoints. That is the brief's third instruction ("give the reachability probe the cut lanes' actual trunk paths ... not just the doorstep"), and it generalises `boundary` from "one goal set shared by every demand" to "a goal set per demand", which is a strictly additive change: `boundary` keeps working byte-for-byte for freeform's own callers.

**Files:**
- Modify: `src/flab2bp/layout/freeform.py:11916-12128` (`_reserve_port_access`)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `_astar(canvas, starts, goals, history, pressure, bounds, deadline=..., grid=..., forbidden=..., blocking_owners=...) -> _PathSearchResult` (`freeform.py:8125-8140`), `_make_grid` (`:7742`), `_span_for(box, starts, goals)` (`:7689`), `_route_box` (`:7712`), `_match_access_corridors(demands, corridors, *, validate, cancelled, deadline)` (`:11755`), `_STEPS` (`:7247`), `PortAccessDemand` (`:11579`), `RouteFailureKind.SEALED_POCKET`.
- Produces: the same `PortAccessReservation`, from

```python
def _reserve_port_access(
    canvas: _Canvas,
    demands: Sequence[PortAccessDemand],
    *,
    boundary: Sequence[Cell] | None = None,
    bounds: tuple[int, int, int, int] | None = None,
    cancelled: Callable[[], bool] | None = None,
    deadline: float | None = None,
    goals: Mapping[PortAccessDemand, frozenset[Cell]] | None = None,
) -> PortAccessReservation: ...
```

`goals[demand]` REPLACES `boundary` as that demand's probe target, and a demand present in `goals` is probed whatever its `kind` says. A demand in neither keeps today's behaviour exactly: every local option is admitted, unprobed.

- [ ] **Step 1: Write the failing tests**

In `tests/layout/test_freeform.py` (next to the existing `_reserve_port_access` tests):

```python
def test_a_goal_makes_an_internal_demand_probed_where_the_boundary_flag_cannot():
    """`INTERNAL_ARRIVAL.reaches_boundary` is False, so `boundary` alone can
    never move this demand into `missing`; a per-demand goal can."""
    canvas, demand, walled_goal = _walled_in_internal_demand()   # helper below
    without = _reserve_port_access(canvas, [demand], bounds=canvas.limit)
    assert without.complete, "today's oracle admits every local option"
    with_goal = _reserve_port_access(
        canvas, [demand], bounds=canvas.limit, goals={demand: walled_goal}
    )
    assert with_goal.missing == (demand,)
    assert with_goal.evidence[0].reachable_options == 0
    assert with_goal.evidence[0].exhaustive


def test_a_goal_a_demand_can_reach_is_assigned_a_corridor():
    canvas, demand, open_goal = _open_internal_demand()
    reservation = _reserve_port_access(
        canvas, [demand], bounds=canvas.limit, goals={demand: open_goal}
    )
    assert reservation.complete
    assert reservation.assigned[0][0] is demand


def test_a_demand_with_no_goal_keeps_todays_local_only_behaviour():
    """The freeform callers must be byte-identical: no goal, no probe."""
    canvas, demand, walled_goal = _walled_in_internal_demand()
    other = _second_internal_demand(canvas)
    reservation = _reserve_port_access(
        canvas, [demand, other], bounds=canvas.limit, goals={demand: walled_goal}
    )
    assert reservation.missing == (demand,)
    assert other in dict(reservation.assigned)
```

The three helpers build a tiny `_Canvas` by hand rather than through a placer: `_walled_in_internal_demand` puts a one-cell lane head in a pocket whose only free neighbours are enclosed by occupied cells, with the goal set two cells outside the wall; `_open_internal_demand` is the same head with the wall removed. Write them beside the tests using the same `_Canvas` construction the existing `_reserve_port_access` tests in this file already use — read them first with `mcp__serena__find_symbol` on `_reserve_port_access` and then `mcp__serena__find_referencing_symbols` to locate them.

- [ ] **Step 2: Run them, expect failure**

Run: `uv run pytest -q -p no:randomly tests/layout/test_freeform.py -k "goal"`
Expected: non-zero exit; `TypeError: _reserve_port_access() got an unexpected keyword argument 'goals'`.

- [ ] **Step 3: Implement the `goals` parameter**

In `freeform.py`, add the parameter to the signature (line 11916-11924) and, immediately after `boundary_set = set(boundary or ())` (line 11954):

```python
    goal_by_demand = dict(goals or {})
    # WHETHER ANY PROBE RUNS AT ALL.  With neither a boundary nor a goal this
    # function is the purely LOCAL oracle it has always been: every free
    # (access, exit) pair is admitted unprobed, `exhaustive` is False, and no
    # grid is built.  That is the path every freeform caller takes today and
    # it is unchanged.
    probed = boundary is not None or bool(goal_by_demand)

    def _goal_for(demand: PortAccessDemand) -> set[Cell] | None:
        """Where this demand's corridor must be able to reach, or None.

        An explicit goal WINS over the boundary and is honoured whatever the
        demand's kind says.  A composed canvas's cut lanes are all
        `INTERNAL_*` -- `reaches_boundary` False -- and their trunks run to
        another BLOCK's port rather than to the rim, so the kind flag is the
        wrong question for them; see
        `docs/superpowers/evidence/2026-09-07-hierarchical-v2/gate.md` §6.
        """
        explicit = goal_by_demand.get(demand)
        if explicit is not None:
            return set(explicit)
        if boundary is not None and demand.kind.reaches_boundary:
            return boundary_set
        return None
```

Replace the shared-grid guard (lines 11968-11980):

```python
    shared_grid: _Grid | None = None
    if bounds is not None and probed:
        probe_box = _route_box(canvas, bounds)
        probe_cells = [
            (key[0] + dx + ex, key[1] + dy + ey, key[2])
            for demand in demands
            for key in (demand.cell,)
            for dx, dy in _STEPS
            for ex, ey in _STEPS
        ]
        # EVERY goal cell has to be inside the span, not just the boundary's:
        # `_astar` falls back to a private grid for a goal outside it, which
        # would cost a fresh flatten per probe -- the 872 rebuilds and 3.9s
        # this shared grid exists to avoid.
        goal_cells = sorted(
            boundary_set.union(*goal_by_demand.values()) if goal_by_demand else boundary_set
        )
        shared_grid = _make_grid(
            canvas, probe_box, _span_for(probe_box, probe_cells, goal_cells), {}
        )
```

Replace the per-demand gate (lines 11997-12000) and the probe's goal (line 12011):

```python
        goal = _goal_for(demand)
        if goal is None:
            reachable_options[demand] = options
            exhaustive[demand] = probed
            continue
        if bounds is None:
            reachable_options[demand] = options
            exhaustive[demand] = False
            continue
        candidates: list[tuple[Cell, Cell]] = []
        complete = True
        for access, exit_cell in options:
            # STOP ONCE TWO OPTIONS ARE PROVEN.  The joint matcher needs
            # alternatives, not every alternative, and probing all twelve
            # options of every satisfiable demand is what would spend the
            # router's wall to re-confirm what the first probe already said.
            # A demand that is genuinely walled in still probes every option,
            # which is the case worth paying for.
            if len(candidates) >= _PORT_ACCESS_PROBE_KEEP:
                complete = False
                break
            result = _astar(
                canvas,
                [exit_cell],
                goal,
                {},
                0.0,
                bounds,
                deadline=deadline,
                grid=shared_grid,
            )
            check_cancelled()
            if result.path is not None:
                candidates.append((access, exit_cell))
            elif result.kind is RouteFailureKind.SEALED_POCKET:
                frontiers[demand].update(result.wall)
            else:
                complete = False
                candidates.append((access, exit_cell))
        reachable_options[demand] = tuple(candidates)
        exhaustive[demand] = complete
```

with, beside `_STEPS` or the other port-access constants:

```python
#: Reachable options a probe stops after.  The joint matcher assigns ONE
#: corridor per demand and only needs a second to have something to swap to
#: under a cut; proving a third buys nothing and costs an A* per rung per
#: demand.
_PORT_ACCESS_PROBE_KEEP = 2
```

Replace `assignment_boundary_cut`'s two gates (lines 12032-12033 and 12043-12045):

```python
    def assignment_boundary_cut(
        assigned: Mapping[PortAccessDemand, PortAccessCorridor],
    ) -> Collection[PortAccessDemand] | None:
        if not probed or bounds is None:
            return None
        ...
        for demand, corridor in assigned.items():
            goal = _goal_for(demand)
            if goal is None:
                continue
            result = _astar(
                canvas,
                [corridor.exit],
                goal,
                ...
```

and the matcher call (line 12080): `validate=assignment_boundary_cut if probed else None`.

Update `_reserve_port_access`'s docstring (line 11925-11931) to say that the final pass filters claims through a static ground component towards **their own goal** — the boundary for a true boundary claim, an explicit `goals` entry for anything else.

- [ ] **Step 4: Run the tests, expect PASS**

Run: `uv run pytest -q -p no:randomly tests/layout/test_freeform.py` — exit 0.
Then the freeform regression surface, because this function is on the default path: `uv run pytest -q -p no:randomly tests/layout` — exit 0 except the known-red `test_two_stage_alignment_retains_cp_sat_direct_opportunity`.
Then `uv run ruff check && uv run ruff format --check && uv run mypy src` — all 0.

- [ ] **Step 5: Commit**

```bash
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "feat(freeform): let a port-access demand carry its own reachability goal"
```

---

### Task 5: Give every cut lane's demand its partner's doorstep

**Lever:** B. This is the change that makes the ladder's oracle able to reject a rung for the reason the router actually refuses.

**Files:**
- Modify: `src/flab2bp/layout/hierarchy/compose.py:628-738` (`pack_with_access`), `:765-843` (`compose`)
- Modify: `src/flab2bp/layout/hierarchy/strategy.py` (record `compose_gap`, `port_demands`, `reservation_missing`)
- Modify: `src/flab2bp/layout/hierarchy/compose.py:119-131` (`ComposeResult` gains the three numbers so `strategy` can read them)
- Test: `tests/layout/hierarchy/test_compose.py`

**Interfaces:**
- Consumes: Task 4's `_reserve_port_access(..., goals=...)`; `_Net.src`/`.dst` (`_Port`, with `.x`, `.y`, `.z`), `_Canvas.free(cell)`, `_Packing.nets`, `_STEPS`-equivalent neighbour offsets (compose has none of its own; define `_NEIGHBOURS` locally rather than importing a freeform private).
- Produces, in `compose.py`:

```python
#: The share of the wall on entry that rung 0's RESERVATION may spend.
#:
#: Rung 0 used to run on the caller's own clock because its reservation was
#: the local-only oracle and cost almost nothing.  With trunk goals it runs
#: an A* per option per demand, so an unbounded rung 0 could spend the wall
#: `_route_all` needs and refuse on BUDGET the cuts a cheaper oracle would
#: have wired -- the same trade `LADDER_WALL_SHARE` exists for one rung up.
#: On its own expiry rung 0 is RE-JUDGED with the local-only oracle
#: (`goals=None`) on the caller's full clock, so the degradation is to v2's
#: behaviour rather than to a refusal.
RESERVE_WALL_SHARE = 0.25


def _trunk_goals(
    packing: _Packing,
) -> dict[PortAccessDemand, frozenset[Cell]]: ...
```

`_trunk_goals` returns, for each demand raised by `_port_access_inventory(packing.nets)`, the free cells adjacent to the OTHER end of every net that demand's lane head belongs to. `ComposeResult` gains:

```python
    #: The `GAP_LADDER` rung the composition committed.
    gap: int = 0
    #: Port-access demands the committed rung raised, and how many of them the
    #: reservation could not give a corridor to.
    port_demands: int = 0
    reservation_missing: int = 0
```

- [ ] **Step 1: Write the failing tests**

```python
def test_trunk_goals_point_each_lane_head_at_its_partners_doorstep(two_solved_blocks):
    left, right, flows, spec, ramped = two_solved_blocks
    packing = compose_mod._pack_at(
        [left, right], flows, spec, gap=2, ramped=ramped, margin=8
    )
    goals = compose_mod._trunk_goals(packing)
    assert goals, "every cut lane must raise a goal"
    net = packing.nets[0]
    src_cell = (net.src.x, net.src.y, net.src.z)
    dst_cell = (net.dst.x, net.dst.y, net.dst.z)
    departure = next(d for d in goals if d.cell == src_cell)
    # The departure's goal is the ARRIVAL's free neighbours, not the rim.
    assert goals[departure] <= {
        (dst_cell[0] + dx, dst_cell[1] + dy, dst_cell[2])
        for dx, dy in compose_mod._NEIGHBOURS
    }
    assert all(packing.canvas.free(cell) for cell in goals[departure])


def test_pack_with_access_hands_the_reservation_the_trunk_goals(
    two_solved_blocks, monkeypatch
):
    left, right, flows, spec, ramped = two_solved_blocks
    captured: dict[str, object] = {}
    real = compose_mod._reserve_port_access

    def spy(canvas, demands, **kw):
        captured.setdefault("goals", kw.get("goals"))
        return real(canvas, demands, **kw)

    monkeypatch.setattr(compose_mod, "_reserve_port_access", spy)
    compose_mod.pack_with_access(
        [left, right], flows, spec, ramped=ramped, deadline=None, margin=8
    )
    assert captured["goals"], "the reservation was still asked the local-only question"


def test_a_walled_in_trunk_rejects_the_narrow_rung(two_solved_blocks, monkeypatch):
    """The upper rungs must become reachable: today rung 0 always commits."""
    left, right, flows, spec, ramped = two_solved_blocks
    real = compose_mod._reserve_port_access

    def scripted(canvas, demands, **kw):
        reservation = real(canvas, demands, **kw)
        if kw["bounds"][2] - kw["bounds"][0] < _WIDE:   # the narrowest packing
            return replace(reservation, missing=demands[:1],
                           assigned=reservation.assigned[1:])
        return reservation

    monkeypatch.setattr(compose_mod, "_reserve_port_access", scripted)
    packed = compose_mod.pack_with_access(
        [left, right], flows, spec, ramped=ramped, deadline=None, margin=8
    )
    assert packed.gap > compose_mod.GAP_LADDER[0]
    assert packed.reservation.complete


def test_rung_zero_falls_back_to_the_local_oracle_on_its_own_deadline(
    two_solved_blocks, monkeypatch
):
    """A slow trunk probe must not cost the router its wall."""
    calls: list[object] = []
    real = compose_mod._reserve_port_access

    def slow_first(canvas, demands, **kw):
        calls.append(kw.get("goals"))
        if len(calls) == 1:
            raise compose_mod._PreparationDeadline
        return real(canvas, demands, **kw)

    monkeypatch.setattr(compose_mod, "_reserve_port_access", slow_first)
    packed = compose_mod.pack_with_access(
        [left, right], flows, spec, ramped=ramped, deadline=time.monotonic() + 30.0,
        margin=8,
    )
    assert len(calls) == 2
    assert calls[0] is not None and calls[1] is None, "the retry must drop the goals"
    assert packed.gap == compose_mod.GAP_LADDER[0]


def test_compose_reports_the_rung_and_the_reservation_it_committed(two_solved_blocks):
    left, right, flows, spec, ramped = two_solved_blocks
    result = compose_mod.compose(
        [left, right], flows, spec, gap=2, ramped=ramped, deadline=None
    )
    assert result.gap in compose_mod.GAP_LADDER
    assert result.port_demands > 0
    assert result.reservation_missing == 0
    assert result.failures == () and result.routed == len(flows)
```

- [ ] **Step 2: Run them, expect failure**

Run: `uv run pytest -q -p no:randomly tests/layout/hierarchy/test_compose.py -k "trunk or rung or reservation_it_committed"`
Expected: non-zero exit; `AttributeError: module ... has no attribute '_trunk_goals'`.

- [ ] **Step 3: Implement `_trunk_goals`**

In `compose.py`, beside `_outer_ring` (line 555):

```python
#: The four von Neumann neighbours, spelled here rather than imported from
#: `freeform._STEPS`: this module already imports eleven freeform privates and
#: a two-line constant is not worth a twelfth.
_NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _free_doorstep(canvas: _Canvas, cell: Cell) -> frozenset[Cell]:
    """The free cells a belt can stand on beside ``cell``.

    The lane head's OWN tile is occupied -- it is a belt -- so a goal set
    naming it would be a goal no search can settle.  What a trunk actually has
    to reach is a free cell touching it, which is exactly the `access_cells`
    set `_reserve_port_access` enumerates for that demand.
    """
    return frozenset(
        neighbour
        for dx, dy in _NEIGHBOURS
        for neighbour in ((cell[0] + dx, cell[1] + dy, cell[2]),)
        if canvas.free(neighbour)
    )


def _trunk_goals(packing: _Packing) -> dict[PortAccessDemand, frozenset[Cell]]:
    """Each cut lane's demand, pointed at the doorstep of its own partners.

    THIS IS WHAT MAKES THE ORACLE ABLE TO SAY NO.  Every demand
    `_port_access_inventory` builds from a composed packing is an
    `INTERNAL_DEPARTURE` or `INTERNAL_ARRIVAL`, both `reaches_boundary` False,
    so `_reserve_port_access` admits every local option unprobed and
    `assignment_boundary_cut` returns `None` on every assignment -- the v2
    gate committed rung 0 with `missing` 0 on all five composing cells while
    the router refused up to 28 cut lanes on the same canvas
    (`docs/superpowers/evidence/2026-09-07-hierarchical-v2/gate.md` §6).

    The question this asks instead is the one the router answers: can this
    lane head's corridor reach the far end of the trunk it is an end of.

    WHAT IS DELIBERATELY WEAKER THAN ROUTING.  A demand is deduplicated by
    `(cell, kind)`, so one lane head can be the end of several nets; the goal
    is the UNION of its partners' doorsteps, which asks "can it reach AT LEAST
    ONE of them" rather than all of them.  That is a necessary condition, not
    a sufficient one: it can still admit a rung the router then refuses, but
    it can no longer admit a rung on which a lane head is sealed away from
    every partner it has.  Probing per partner would multiply the A* count by
    the fan-out for a claim the router re-checks anyway.
    """
    demands = _port_access_inventory(packing.nets).demands
    by_cell: dict[Cell, list[PortAccessDemand]] = {}
    for demand in demands:
        by_cell.setdefault(demand.cell, []).append(demand)
    goals: dict[PortAccessDemand, set[Cell]] = {demand: set() for demand in demands}
    for net in packing.nets:
        if net.prelinked or net.src is None:
            continue
        src_cell = (net.src.x, net.src.y, net.src.z)
        dst_cell = (net.dst.x, net.dst.y, net.dst.z)
        src_door = _free_doorstep(packing.canvas, src_cell)
        dst_door = _free_doorstep(packing.canvas, dst_cell)
        for demand in by_cell.get(src_cell, ()):
            goals[demand].update(dst_door)
        for demand in by_cell.get(dst_cell, ()):
            goals[demand].update(src_door)
    # A demand whose every partner is walled in raises no goal rather than an
    # EMPTY one: an empty goal set is a search that can never settle, which
    # would convict the demand for its PARTNER's pocket.  The router names
    # that lane itself, with the class that actually stopped it.
    return {demand: frozenset(cells) for demand, cells in goals.items() if cells}
```

Add `PortAccessDemand` to the `flab2bp.layout.freeform` import block (`compose.py:35-52`).

- [ ] **Step 4: Pass the goals and fund rung 0's reservation**

In `pack_with_access`, replace the reservation call (`compose.py:695-728`) with:

```python
        demands = _port_access_inventory(packing.nets).demands
        # THE BOUNDARY IS STILL ONLY PASSED WHEN A DEMAND'S KIND COULD USE IT
        # -- compose has no boundary ports of its own, so this stays None --
        # but `goals` now carries the question that DOES apply to a cut lane:
        # each demand's own trunk partners.  See `_trunk_goals`.
        boundary = _outer_ring(bounds) if any(d.kind.reaches_boundary for d in demands) else None
        goals = _trunk_goals(packing)
        # Rung 0's reservation is funded out of `RESERVE_WALL_SHARE` and
        # DEGRADES rather than refusing: see the constant's docstring.
        reserve_deadline = (
            rung_deadline
            if not first or rung_deadline is None
            else min(
                rung_deadline,
                entered + (rung_deadline - entered) * RESERVE_WALL_SHARE,
            )
        )
        try:
            reservation = _reserve_port_access(
                packing.canvas,
                demands,
                boundary=boundary,
                bounds=bounds,
                cancelled=partial(_spent, reserve_deadline),
                deadline=reserve_deadline,
                goals=goals,
            )
        except _PreparationDeadline:
            if not first:
                if best is None:
                    raise _PackingDeadline(packing) from None
                break
            # RUNG 0 ONLY: the trunk probe outran its own share, so ask the
            # LOCAL-ONLY question on the caller's full clock.  That is exactly
            # v2's oracle, so the worst case of this whole lever is v2's
            # behaviour rather than a refusal on BUDGET.
            try:
                reservation = _reserve_port_access(
                    packing.canvas,
                    demands,
                    boundary=boundary,
                    bounds=bounds,
                    cancelled=partial(_spent, rung_deadline),
                    deadline=rung_deadline,
                )
            except _PreparationDeadline:
                raise _PackingDeadline(packing) from None
```

Note the `cancelled=partial(...)` stays a `partial` rather than a lambda for the reason the existing comment at `compose.py:719-721` gives.

In `compose` (`compose.py:838-843`), carry the three numbers out:

```python
    return ComposeResult(
        Placement(buildings=tuple(canvas.buildings), description="hierarchical composition"),
        blocks,
        len(result.routed),
        tuple(failures),
        gap=packed.gap,
        port_demands=len(reservation.assigned) + len(reservation.missing),
        reservation_missing=len(reservation.missing),
    )
```

and in `_budget_refusal` (`compose.py:750-762`) leave the three at their defaults, which is honest: nothing was judged.

In `strategy.lay_out`, after `composition` returns (line 587):

```python
            stats.compose_gap = float(composition.gap)
            stats.port_demands = float(composition.port_demands)
            stats.reservation_missing = float(composition.reservation_missing)
```

- [ ] **Step 5: Run the tests, expect PASS**

Run: `uv run pytest -q -p no:randomly tests/layout/hierarchy` — exit 0.
Then `uv run ruff check && uv run ruff format --check && uv run mypy src` — all 0.

- [ ] **Step 6: One build, to see whether the ladder now moves**

```bash
(uptime; vmstat 1 3 | tail -1) > /tmp/v3-t5-load.txt
uv run flab2bp "<belt3 url>" --strategy hierarchical --budget 60 \
    --candidate-policy all-products --band portable > /dev/null 2> /tmp/v3-t5-belt3.log
```

Expected and recorded in the task report: the `stats hierarchical/all-products:` line's `compose_gap`, `port_demands`, `reservation_missing` and `unrouted_cuts`. v2's numbers for this exact cell were gap **2**, 102 demands, `missing` **0**, 28 unrouted. **Any of `compose_gap > 2` or `reservation_missing > 0` is the first time in three gates that the oracle has spoken about a trunk; report it either way, including if nothing moved.**

- [ ] **Step 7: Commit**

```bash
git add src/flab2bp/layout/hierarchy/compose.py src/flab2bp/layout/hierarchy/strategy.py \
        tests/layout/hierarchy/test_compose.py
git commit -m "feat(hierarchy): probe each cut lane's trunk, not just its doorstep"
```

---

### Task 6: Measure, per rung, what the oracle predicts about the router

**Lever:** B. gate.md §3.4 could only report the rung the composer COMMITTED, because both its harnesses wrapped `pack_with_access`; the rung-by-rung view needed a probe one level lower. This task produces the equivalent for the new oracle, on the two cells with the most cut lanes: **belt3/all-products** (89 cut lanes, 102 demands, 28 unrouted in v2) and **zurl2/all-products** (127 cut lanes, 144 demands, 18/15 unrouted).

**Files:**
- Create: `docs/superpowers/evidence/2026-09-07-hierarchical-v3/rung_probe.py`
- Create: `docs/superpowers/evidence/2026-09-07-hierarchical-v3/rung-{belt3,zurl2}-all-products.{json,log}` and their `-load.txt`
- Create: `docs/superpowers/evidence/2026-09-07-hierarchical-v3/oracle.md`
- No `src/` change.

**Interfaces:**
- Consumes: `compose._pack_at(placements, flows, spec, *, gap, ramped, margin) -> _Packing`, `compose._trunk_goals(packing)`, `compose._outer_ring`, `freeform._port_access_inventory`, `freeform._reserve_port_access`, `freeform._route_all(canvas, nets, belt_id, belt_model, bounds, deadline=...)`, `compose._belt_id_for`, `compose._belt_model_for`, `flab2bp.cli.main`.
- Produces `rung_probe.py`, which monkeypatches `compose.pack_with_access` with a wrapper that, for EVERY rung of `GAP_LADDER` (not just until one is complete), packs, reserves WITH the trunk goals, and then runs `_route_all` on that rung's canvas, recording per rung:

```python
{
  "gap": int,
  "demands": int,
  "missing": int,               # reservation.missing
  "missing_sealed": int,        # missing demands whose evidence has a frontier
  "assigned": int,
  "routed": int,                # _route_all's routed nets
  "unrouted": int,
  "unrouted_by_kind": {"DYNAMIC_ACCESS": int, "SEALED_POCKET": int, ...},
  "reserve_wall_s": float,
  "route_wall_s": float,
}
```

and then returns the rung `pack_with_access` would really have committed, so the build proceeds normally and the whole thing is ONE build per cell.

- [ ] **Step 1: Write `rung_probe.py`**

Model it on `docs/superpowers/evidence/2026-09-07-hierarchical-v2/ladder_probe.py`, which already wraps `compose._pack_at` and `compose._reserve_port_access` for exactly this purpose — read it first and keep its module docstring's provenance discipline (what it wraps, what it does NOT change, and that the numbers are read rather than produced). The one behavioural difference: v2's probe stopped at the committed rung; this one judges every rung and routes each, so its wall is roughly `len(GAP_LADDER)` times a composition. Give it its own `--budget` argument and use **180 s per cell**, stating in the docstring that this is a MEASUREMENT budget and not a gate budget, so no gate clause is read from it.

- [ ] **Step 2: Run it on belt3, one build**

```bash
cd docs/superpowers/evidence/2026-09-07-hierarchical-v3
(uptime; vmstat 1 3 | tail -1) > rung-belt3-all-products-load.txt
uv run python rung_probe.py rung-belt3-all-products.json -- "<belt3 url>" \
    --strategy hierarchical --budget 180 --band portable \
    --candidate-policy all-products 2>&1 | tee rung-belt3-all-products.log
```

- [ ] **Step 3: Run it on zurl2, one build, after belt3 has finished**

```bash
(uptime; vmstat 1 3 | tail -1) > rung-zurl2-all-products-load.txt
uv run python rung_probe.py rung-zurl2-all-products.json -- "<zurl2 url>" \
    --strategy hierarchical --budget 180 --band portable \
    --candidate-policy all-products 2>&1 | tee rung-zurl2-all-products.log
```

- [ ] **Step 4: Write `oracle.md`**

It answers one question, and it must answer it in the form of a table, not a paragraph: **per rung, does `missing` predict `unrouted`?** One table per cell:

| gap | demands | `missing` | of which sealed | routed | unrouted | by kind | reserve wall | route wall |

Then three findings, each a sentence with a number in it:

1. **Does the oracle now reject anything?** If `missing` is 0 on every rung of both cells, the lever did not move the oracle and Task 7 does not run — say so in those words. If it rejects, name the rung, the demand and its kind.
2. **Are the upper rungs reachable?** Name the widest rung any cell's reservation was complete at. gate.md §6 records that rungs 6, 8, 12 and 16 "have never been exercised by any measurement here"; this is the measurement that either exercises them or confirms they still are not.
3. **Does `missing` track `unrouted`?** Give the per-rung correlation in the crudest honest form: the rung with the fewest `missing` and the rung with the fewest `unrouted`, and whether they are the same rung. That is the whole question — a rung ordering the oracle gets right is a rung ordering the ladder can act on.

State plainly, as gate.md §3.4 did, what the measurement is NOT: two cells, one policy, one round each, at a budget no gate uses.

- [ ] **Step 5: Decide Lever C, in writing, in `oracle.md`**

Task 7 runs **only if BOTH** of these hold, and `oracle.md` must record which:

* the reservation rejected at least ONE rung on at least one cell **for a sealed-trunk reason** (a `missing` demand whose `PortAccessEvidence.frontier` is non-empty — the A* proved a pocket rather than running out of budget), AND
* the WIDEST rung judged still leaves at least one unrouted cut.

If the first fails, the oracle is still not the binding constraint and the next lever is elsewhere. If the second fails, a wide-enough rung already routes everything and a corridor buys nothing the ladder cannot. Write the verdict as `LEVER C: RUN` or `LEVER C: SKIPPED, because <clause>`.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/evidence/2026-09-07-hierarchical-v3/
git commit -m "evidence: what the boundary-aware oracle predicts about the router"
```

---

### Task 7 (CONDITIONAL on Task 6 Step 5): Shared ground for the trunks — a spike

**Lever:** C. gate.md §6 lever 3 and design §4 E: "a shared bus corridor reserved before block placement". v1 ranked this first; v2 demoted it one place precisely so that Task 6's measurement could say whether the geometry is what is missing. **Run this task ONLY if `oracle.md` says `LEVER C: RUN`. If it says SKIPPED, do Step 0 and stop.**

**Files:**
- Modify: `src/flab2bp/layout/hierarchy/compose.py` (`pack_blocks`, `_pack_at`, `canvas_for`)
- Create: `docs/superpowers/evidence/2026-09-07-hierarchical-v3/corridor-spike.md`
- Test: `tests/layout/hierarchy/test_compose.py`

**The kill criterion, stated before anything is built.** The spike is one 60 s build of **belt3/all-products** with the corridor on. **If that build's `unrouted_cuts` is not 7 or fewer, the spike is killed, reverted, and recorded as killed.** Seven is not arbitrary: gate.md §3.2 measured the same cell at 8 unrouted lanes under strip cap 8 against 28 at the shipped cap 12, so a 4x reduction is a factor this geometry has already been observed to produce by a cheaper means, and a corridor that cannot match it is not worth a new subsystem. A second stop condition applies at any point: **if the corridor pushes the packing past `compose.BAND_MAX_ROWS = 160`, the spike is killed**, because `finalize.finalize_placement` refuses a deeper paste with `game.blueprint_area` and a composition that cannot be pasted is not an answer.

- [ ] **Step 0 (ALWAYS): Record the decision**

If `oracle.md` says `LEVER C: SKIPPED`, write `corridor-spike.md` containing only the verdict, the clause it failed, and the two numbers behind it, then commit and stop. Do not implement anything.

- [ ] **Step 1: Write the failing test**

```python
def test_a_reserved_corridor_is_free_ground_between_the_block_rows(two_solved_blocks):
    left, right, flows, spec, ramped = two_solved_blocks
    packing = compose_mod._pack_at(
        [left, right], flows, spec, gap=2, ramped=ramped, margin=8, corridor=4
    )
    rows = compose_mod.corridor_rows(packing)
    assert rows, "a corridor was asked for and none was reserved"
    assert all(
        packing.canvas.free((x, y, 0))
        for y in rows
        for x in range(packing.canvas.limit[0], packing.canvas.limit[2] + 1)
    )
    assert all(b.y not in rows for b in packing.buildings)
```

- [ ] **Step 2: Run it, expect failure**

Run: `uv run pytest -q -p no:randomly tests/layout/hierarchy/test_compose.py -k corridor`
Expected: non-zero exit; `_pack_at() got an unexpected keyword argument 'corridor'`.

- [ ] **Step 3: Implement the corridor in the packer**

`pack_blocks(sizes, gap)` gains `corridor: int = 0`: `_skyline` shelves blocks as it does today, and after each shelf row it advances `y` by `corridor` extra tiles, recording the reserved row range. `_pack_at` threads `corridor` through and returns the rows on `_Packing`; `canvas_for` is unchanged, because a corridor is simply ground no building was placed on. `pack_with_access` passes `corridor = rung` (the same ladder rung it is already paying for, spent vertically as well as horizontally), so no new ladder and no new constant is introduced by the spike.

- [ ] **Step 4: Run the test, expect PASS, then the verification**

Run: `uv run pytest -q -p no:randomly tests/layout/hierarchy` — exit 0.
Then `uv run ruff check && uv run ruff format --check && uv run mypy src` — all 0.

- [ ] **Step 5: The kill-criterion build**

```bash
(uptime; vmstat 1 3 | tail -1) > docs/superpowers/evidence/2026-09-07-hierarchical-v3/corridor-load.txt
uv run flab2bp "<belt3 url>" --strategy hierarchical --budget 60 \
    --candidate-policy all-products --band portable \
    > /dev/null 2> docs/superpowers/evidence/2026-09-07-hierarchical-v3/corridor-belt3.log
```

Read `unrouted_cuts` and `compose_gap` off the `stats hierarchical/all-products:` line.

- [ ] **Step 6: Write `corridor-spike.md` and act on the criterion**

If `unrouted_cuts <= 7` and the placement pastes: keep, and say by how much it beat 28. Otherwise `git revert` the Step 3 commit, and write down the measured number against the criterion's 7 — a killed spike with a number is a result.

- [ ] **Step 7: Commit**

```bash
git add -A docs/superpowers/evidence/2026-09-07-hierarchical-v3/ \
        src/flab2bp/layout/hierarchy/compose.py tests/layout/hierarchy/test_compose.py
git commit -m "spike(hierarchy): shared ground for the trunks, against a stated kill criterion"
```

---

### Task 8: The v3 gate

**Files:**
- Create: `docs/superpowers/evidence/2026-09-07-hierarchical-v3/gate.md`, `run_large.sh`, `run_cell.py`, `judge.py` (copied from `../2026-09-07-hierarchical-v2/`), `large-*.{json,log,stdout.txt}` and their `-load.txt`, `baseline-round1.{jsonl,txt}`, `candidate-round1.{jsonl,txt}`, `compare-round1.txt`
- Modify: `docs/speedup-idea-backlog.md` (move the levers this plan closed)

**The eight cells, the same as v2's**, one candidate policy per run so each cell gets the whole budget, `--band portable`, `-o`, and **no `--workers`** so the strategy sees the `None` the CLI passes by default:

| cell | policy | budget |
| --- | --- | --- |
| belt3 | all-products | 60 |
| belt3 | no-proliferator | 60 |
| zurl2 | all-products | 60 |
| mall | all-products | 60 |
| mall | no-proliferator | 60 |
| titanium-glass | all-products | 60 |
| titanium-glass | all-products | 15 |
| belt3 | all-products | 15 |

- [ ] **Step 1: Declare the rule, in `gate.md`, BEFORE running anything**

Write §0 of `gate.md` first and commit it, so the rule cannot be amended afterwards. Verbatim:

> **PASS** if all four hold: (a) every cell that COMPOSES emits a blueprint whose `validate.certify` report has zero errors; (b) both malls compose — every block placed, the build reaching `compose`; (c) titanium-glass builds at `--budget 15`, emitting a blueprint; (d) the default-unchanged corpus guard has zero regressions — no cell CLEAN on the merge base and not CLEAN on the branch, 0 INVALID, 0 CRASH.
> **FAIL** otherwise, naming the clause AND the lever that failed (A funding/dispatch, B the oracle, C the corridor), and ranking the next three levers with the file:line and the number behind each, as v2's §6 did.

Note in §0 that the area clauses v2 carried (belt3 ≤ 1.25 x 12408, zurl2 ≤ 1.0 x 40905, titanium-glass ≤ 1.25 x 5727) are **reported but not gating** this time, because v2 demonstrated none of them — no cell emitted a blueprint — and a coverage gate that also fails on area cannot say which one it failed on. Report `area / best_known` for every cell that emits.

- [ ] **Step 2: The eight cells, twice each, ONE BUILD AT A TIME**

`run_cell.py` calls `flab2bp.cli.main(argv)` with exactly the argv below and changes nothing about the build. **Unlike v2's, it reads NOTHING by monkeypatching the strategy**: Tasks 1, 3 and 5 put every number it needs on the CLI's stderr and on `NoValidLayout.attempt_failures[].stats`, so it captures stderr and parses the `  stats ` line. Say that in its module docstring, and say which of v2's spies it therefore replaces (`nogood_skips`, `player_fed`, `gap`).

```
uv run python run_cell.py <stem>.json -- "<url>" --strategy hierarchical \
    --budget <60|15> --band portable --candidate-policy <policy> -o <stem>.blueprint.txt
```

Beside each run, a `-load.txt` with `uptime` and one `vmstat 1 3` sample taken immediately before it. Record per cell: verdict, in-process wall AND shell wall, area, `area / best_known`, validator errors by class, and the whole stats line — `blocks`, `blocks_unattempted`, `recut_rounds`, `nogood_skips`, `player_fed`, `cut_lanes`, `arm_dispatch_*`, `compose_gap`, `port_demands`, `reservation_missing`, `unrouted_cuts`. **Both rounds' numbers go in the table**, r1 quoted with r2 in parentheses wherever they differ, as v2's §2 did.

- [ ] **Step 3: The default-unchanged corpus guard**

Everything committed, `git status --short` empty. Then, exactly as v2's §5 ran it (controller ruling R13): `git checkout --detach $(git merge-base master hierarchical-v3)`, run the BASELINE half there writing to `/tmp/v3gate/` (the evidence directory does not exist at the merge base), `git checkout hierarchical-v3` immediately, verify HEAD and cleanliness, run the CANDIDATE half, copy the baseline half in. No `git stash`, no second worktree.

```bash
pgrep -fc '[s]cripts/audit\.py'                 # must be 0 before EACH invocation
(uptime; vmstat 1 3 | tail -1) > <half>-round1-load.txt
uv run python scripts/audit.py --budget 30 --json <half>-round1.jsonl > <half>-round1.txt 2>&1
```

Two corrections to that block, both measured in Task 8:

* **The slot check.** `pgrep` does not self-match (it excludes its own PID); the
  `ps -eo args | grep -cE` form an earlier revision prescribed DOES, because
  `ps` lists the pipeline's own `grep`. The `[s]` bracket additionally stops an
  enclosing `bash -c "… pattern …"` from counting itself. See the Global
  Constraints bullet for the measurement.
* **`--json` takes a PATH on this master and APPENDS to it** (`scripts/audit.py`
  ~741: "append one JSON record per cell to this file"). It is not a flag whose
  output can be redirected, so the JSONL is named as an argument and the
  human-readable report is what goes to the redirect. Delete a stale target
  first, or a second run doubles the file.

Then `uv run python scripts/audit_compare.py baseline-round1.jsonl candidate-round1.jsonl > compare-round1.txt`. **`audit.py` prints `NOT CLEAN` on any refusal, so read the CLEAN COUNTS and the NAMED DIFFERING CELLS, not the banner.** If any cell differs, re-run just that URL on both trees before calling it a regression — v2's §5 found all six moved cells moving on BOTH trees, and a seventh whose instability was on the baseline side.

- [ ] **Step 4: Write the rest of `gate.md`**

Sections, in this order: §0 the rule (already committed in Step 1, unamended); §1 the verdict as a clause-by-clause table; §2 the eight cells with §2.1's stats table and §2.2's verbatim refusals; §3 where the strategy dies, and per-task agreement or disagreement with each implementer's own measurement, citing each as theirs; §4 the corpus guard; §5 the next three levers from the measurement, each with a file:line and a number; §6 the two adaptive memories still open; §7 the as-shipped constants, superseding v2's §8, including `MAX_RECUT_ROUNDS`, `allowed_recut_rounds`, the `rounds_left` funding rule, `dispatch.ARM_SMALL_STRIPS` / `UNCOVERED_*`, `_PORT_ACCESS_PROBE_KEEP` and `RESERVE_WALL_SHARE`; §8 files.

**On FAIL, §5 must name the lever that failed** — A if a mall still refuses with blocks unattempted, B if the cells compose and the router still refuses with `reservation_missing == 0`, C if the corridor spike ran and missed its criterion — and rank the next three with evidence, exactly as v2's §6 did.

- [ ] **Step 5: Update the backlog**

In `docs/speedup-idea-backlog.md`, move the entries this plan closed out of "Hierarchical" and leave the two adaptive memories where they are, with one sentence each and no new plan:

* **A cross-build solved-block cache** — deliberately NOT planned here; related work is already planned as the "background compound block cache" (`42c9e0e`) and duplicating it would be two designs for one cache.
* **A strip cap that moves with outcomes** — deliberately NOT attached to the `_ShapeNoGood` memo shipped in v2, because it is not cheap to attach: `_ShapeNoGood` is consulted BEFORE a block solve and keyed on `(shape, arm)`, while the signal gate.md §7 says the cap should adapt on is the ROUTER's verdict (unrouted lanes per cut), which arrives once per build after every block has already been solved and composed. There is no second composition within a build to feed it, so an outcome-driven cap needs a cross-build memory, which is the previous bullet.

- [ ] **Step 6: Commit**

```bash
git add -A docs/superpowers/evidence/2026-09-07-hierarchical-v3/ docs/speedup-idea-backlog.md
git commit -m "evidence: hierarchical v3 gate on the large URLs"
```

---

## Self-review

**1. Spec coverage.**

| requirement | task |
| --- | --- |
| design §1: coverage and bounded time first, area second | Task 8's gate rule — coverage clauses gate, area clauses report |
| design §3.1: a feature vector computed once, before any placement | Task 3 (`dispatch.block_features`, cached per `ShapeKey` per build) |
| design §3.2: a registry where a solver claims a class | Task 1's `_block_layout` seam contract; Task 3's `dispatch_arms` |
| design §3.3: the cheapest solver first, escalate only while outside the band | Task 3's one-arm dispatch plus the widen-arms-before-cut fallback |
| design §4 E: a bus corridor reserved before block placement | Task 7, conditional on Task 6's measurement |
| gate §6 lever 1: the oracle can only judge a doorstep | Tasks 4, 5, 6 |
| gate §6 lever 2: fund the re-cut rounds, bound the growth | Tasks 2, 3 |
| gate §6 lever 3: shared ground for the trunks | Task 7 |
| gate §7: the two remaining adaptive memories | Task 8 Step 5 — backlog, one sentence each, with the reason neither is planned |
| gate R6/R15: the stats the CLI does not print | Task 1 |
| brief: `blocks_unattempted`, `recut_rounds`, `player_fed`, `nogood_skips` on `PlacementStats`, read from the CLI | Task 1 (keys + CLI), Tasks 2/3/5 (values) |
| brief: the 15 s path attempts every seed block before any re-cut | Task 2, via `allowed_recut_rounds(8.7) == 0` — structurally, not as a special case |
| brief: make the ladder's upper rungs reachable in a measurement | Task 6 Step 4 finding 2 |
| brief: measure `missing` vs the router's unrouted count on belt3 and zurl2 | Task 6 |

**2. Placeholder scan.** No task says "add appropriate handling", "similar to Task N", or "write tests for the above". Every code step carries the code; every test step carries the test. Two things are deliberately deferred and both name their decision procedure rather than the decision: Task 6's `LEVER C: RUN`/`SKIPPED` verdict (two stated clauses, both measurable from `rung_probe.py`'s own JSON) and Task 7's kill criterion (the number is 7, and where 7 comes from is stated). Task 4's three test helpers are described by what they must construct rather than written out, because they depend on the `_Canvas` construction shape the existing `_reserve_port_access` tests in `tests/layout/test_freeform.py` use, which the implementer reads first — that is a pointer to real existing code, not a TBD.

**3. Type consistency.** `_StrategyStats` (Task 1) is the single writer of every `PlacementStats` key Tasks 2, 3 and 5 fill in, and the names in `as_stats()` are exactly the keys added to `base.py`. `BlockFeatures(strips, coaters, items_above_one_belt)` has the same three fields in `dispatch.py`, in `block_features`'s return, and in every test. `dispatch_arms(features, arms) -> tuple[str, ...]` and `_arms_for(spec, entry, cache) -> tuple[str, ...]` return the same type `self._arms()` does, which is what `_solve_round`'s `slots_by_key` and `_recut`'s `arms` already consume. `goals: Mapping[PortAccessDemand, frozenset[Cell]] | None` in `_reserve_port_access` (Task 4) is exactly what `_trunk_goals` returns (Task 5) — `dict[PortAccessDemand, frozenset[Cell]]`. `ComposeResult`'s three new fields (`gap: int`, `port_demands: int`, `reservation_missing: int`) are read in `strategy.lay_out` as `float(...)` into `_StrategyStats`'s float fields. `Cell` is `(x, y, level)` throughout, as `route_feedback` defines it.

**4. Ordering.** Task 2 depends on Task 1's `_refuser(spec, budget_s, stats)` signature and defines a one-line `_arms_for` placeholder so it is testable before Task 3 exists. Task 3 replaces only that body. Task 5 depends on Task 4's `goals` parameter. Task 6 depends on Task 5. Task 7 depends on Task 6's written verdict. Task 8 is last and depends on all of them.
