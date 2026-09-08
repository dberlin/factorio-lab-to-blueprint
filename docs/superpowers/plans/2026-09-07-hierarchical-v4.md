# Hierarchical v4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get `--strategy hierarchical` from "0 of 8 large cells emit a blueprint" to a first emitted, validator-clean blueprint and two composing malls, by fixing the three defects the v3 gate measured: a corridor matcher that throws away a 91-corridor answer wholesale, a composed canvas whose own added splitters stand on unpowered ground, and a one-arm dispatch rule that sends 54 coater-free blocks to a solver their per-block budget cannot fund.

**Architecture:** `hierarchical` is the ORCHESTRATOR of this repo's sub-solvers, not a placer: it cuts a spec into blocks, hands each block to a solver behind the `strategy._solve_block` seam, composes what comes back, and routes the cuts between blocks on the composed canvas. v3 shipped the funding rule (`blocks_unattempted = 0` on all eight cells), the per-demand reachability goal, and the trunk-partner doorstep — and the v3 gate then measured that all of it is computed and discarded on every production build. This plan is three levers in the order of the cells each unlocks. **Lever 1** (Tasks 1-3) makes `freeform._match_access_corridors` COMMIT THE PARTIAL it already holds instead of returning `{}` when its validate/cut loop runs out of rounds, and makes `compose` act on that partial without ever letting a partial claim a trustworthy verdict. **Lever 2** (Tasks 4-5) gives the ground `compose` opens between blocks its own power pass, so the four cut-lane splitters that convicted `titanium-glass/all-products` at `validate.certify` are covered — the smallest measured distance between this branch and its first blueprint. **Lever 3** (Tasks 6-8) re-opens the arm rule for coater-free blocks whose per-block budget is below the measured sequence-pair exact-preparation floor, and takes apart the freeform packer defect that refuses 7 of `mall/all-products`'s 9 blocks. Task 9 is the gate.

**Tech Stack:** Python 3.14, `uv run`, `freeform`'s router (`_match_access_corridors`, `_reserve_port_access`, `_astar`, `_route_all`, `_power_plan`, `_place_power`), OR-Tools CP-SAT, `multiprocessing` spawn pools, `validate.certify`, `scripts/audit.py`, `scripts/audit_compare.py`.

**Spec:** `docs/superpowers/specs/2026-09-06-multi-solver-orchestrator-design.md` — §1 (coverage and bounded time first, area second), §3.1-§3.3 (a feature vector computed before any placement, a registry where a solver claims a class, the cheapest solver first with escalation), §4 E (reserved ground for the trunks, and its 2026-09-07 status note). The measurements this plan argues from are `docs/superpowers/evidence/2026-09-07-hierarchical-v3/gate.md` §1, §2.1, §2.2, §2.3, §3, §5 and §6, its `oracle.md` and `corridor-spike.md`, and `docs/superpowers/evidence/2026-09-07-hierarchical-v2/gate.md` §6 for the lever history. The previous plan is `docs/superpowers/plans/2026-09-07-hierarchical-v3.md`.

## Global Constraints

- **`--strategy hierarchical` stays EXPLICIT and DEFAULT-OFF.** `PRODUCTION_STRATEGIES` is unchanged; `best` is unchanged. No task here may add `hierarchical` to a default field.
- **`validate.certify` is the arbiter.** No player hand-back beyond the player-fed lane contract v2 shipped (`contracts.allocate_cuts`): a head for an item the parent spec does NOT belt in must be fully fed by cuts or the build refuses.
- **Default behaviour is unchanged, and it is judged by a PAIRED audit, not by a banner.** One `scripts/audit.py --budget 30 --json` round on the merge base and one on this branch, compared with `scripts/audit_compare.py`. `audit.py` prints `NOT CLEAN` on any refusal, and `audit_compare.py` prints `FAIL` on its own 30 s p95-wall clause which the merge base also fails — so what is read is the CLEAN COUNTS and the NAMED DIFFERING CELLS, never either banner. Zero regressions means: no cell CLEAN on the base and not CLEAN on the branch, 0 INVALID, 0 CRASH.
- **ONE LAYOUT BUILD AT A TIME on this box, and never two audits at once.** Other agents run builds in sibling worktrees. Before each audit invocation: `pgrep -af '[s]cripts/audit\.py'` must print nothing. The `[s]` bracket is what stops an enclosing `bash -c "… pattern …"` from counting itself; `pgrep` never self-matches (it excludes its own PID). **Do not use `ps -eo args | grep -c`** — that form DOES self-match, because `ps` lists the pipeline's own `grep`. Do not use `pgrep -fc 'python[0-9.]* +[^ ]*scripts/audit\.py'` as the primary form: it is self-match-proof but it missed 7 of 9 real audit processes when v3 measured it (forkserver children).
- **`--budget 30` for corpus cells.** The gate's large cells are 60 s and 15 s exactly as Task 9 states them. The strategy may overshoot `--budget` only by `pipeline.RACE_COMPLETION_GRACE_S = 6.0`.
- **Record CPU pressure into a `-load.txt` beside EVERY timing, as the five-second mean of RUNNABLE processes:** `vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print sum/5}'`. Under **64** is fine on these 128 cores. **Never wait for it to fall** — record it and run. Never use load average: on this box it is dominated by I/O wait and measures the wrong thing (v3's own files show load average 64.99 against 19 runnable).
- **Bounded time.** Every block job's deadline stays `min(parent_deadline, job_start + block_budget)`, computed in the worker.
- **Exact arithmetic** everywhere rates appear (`Fraction`, never `float`).
- **Reading code: Serena's symbolic tools** (`mcp__serena__get_symbols_overview`, `find_symbol`, `find_referencing_symbols`) or the LSP tools — `freeform.py` is 22k lines and grep misses call sites. **Editing: Read/Edit, NOT Serena's editing tools.** Serena is a shared last-activation-wins server on this box and other agents are working in sibling worktrees; a Serena write from here can land in the wrong worktree.
- **Process discipline:** work in `.claude/worktrees/hierarchical-v4` on branch `hierarchical-v4`; confirm `uv run python -c "import flab2bp; print(flab2bp.__file__)"` prints a path INSIDE the worktree before trusting any measurement (a worktree without its own venv silently tests master). Never `git stash`; never commit anything under `.superpowers/`; evidence goes to `docs/superpowers/evidence/2026-09-07-hierarchical-v4/`, **any size — file size is never a reason to shrink or omit committed evidence**. `git diff` is wired to difftastic: use `--no-ext-diff` for patches. Never run a git command that opens an editor; `export GIT_EDITOR=true` and always `git commit -m`.
- **Verification per code change:** `uv run ruff check` 0, `uv run ruff format --check` 0, `uv run mypy src` 0, and the touched test files exit 0.
- **The pytest summary line never prints here — judge by the EXIT CODE.** There is a 120 s `pytest-timeout` backstop that hard-kills a run.
- **Known reds on master, not caused by this branch:** `tests/layout/test_sequence_pair.py::test_two_stage_alignment_retains_cp_sat_direct_opportunity`, and — until Task 6 lands — `tests/test_pipeline.py::test_all_products_sequence_pair_honours_the_exact_layout_deadline`, which is red because preparation got faster and its 1.5 s budget no longer exhausts. Load flake: `tests/layout/test_strategy_race.py::test_the_real_pool_races_both_arms_end_to_end`.
- **Large URLs:** `docs/superpowers/evidence/2026-09-05-speedups-2/large-urls/urls.txt` (belt3, zurl2, mall) plus the titanium-glass mall URL in `docs/superpowers/evidence/2026-09-06-debug-url/README.md`. Best-known dense areas: belt3 all-products **12408**; zurl2 all-products **40905**; titanium-glass all-products **5727**. The mall has no best-known area.
- **As-shipped constants this plan starts from** (v3 gate §7): `SETTLEMENT_RESERVE_MIN_S = 5.0`/`_MAX_S = 40.0`/`_SHARE = 0.4`; `_POOL_CAP = 32`, `_BLOCK_WORKERS = 4`; `BLOCK_BUDGET_MIN_S = 5.0`/`_MAX_S = 20.0`; per-round block budget `clamp(remaining / rounds_left / waves, 5, 20)`; `MAX_RECUT_ROUNDS = 2` floored by `allowed_recut_rounds(wall) = min(2, max(0, int(wall // 5) - 1))`, **0 at the web UI's 15 s**; `MAX_RESPLIT_ATTEMPTS = 4` per block; `partition.STRIP_CAP_DEFAULT = 12`; `compose.GAP_LADDER = (2, 4, 6, 8, 12, 16)`, `LADDER_WALL_SHARE = 0.4`, `MIN_GAP = 2`, `RESERVE_WALL_SHARE = 0.25`, `BAND_MAX_ROWS = 160`; `freeform._ACCESS_CUT_ROUNDS = 8`, `_PORT_ACCESS_PROBE_KEEP = 2`; `dispatch.ARM_SMALL_STRIPS = 6`, `UNCOVERED_ITEMS_ABOVE_ONE_BELT = 8`, `UNCOVERED_STRIPS = 85`.

### Deliberately NOT in this plan

- **The pre-placed bus corridor (design §4 E).** Killed by measurement twice — v3's Task 7 recorded `LEVER C: SKIPPED` because `missing_sealed = 0` on all twelve judged rungs, and that verdict cannot be revisited until Lever 1 lands, because a corridor's value cannot be judged while the oracle grades no rung.
- **A cross-build solved-block cache.** Related work is already planned as the "background compound block cache" (`42c9e0e`); duplicating it would be two designs for one cache.
- **An outcome-driven strip cap.** `_ShapeNoGood` is consulted BEFORE a block solve and keyed on `(shape, arm)`, while the signal it must adapt on is the router's per-cut verdict, which arrives once per build after every block is already solved — so it needs a cross-build memory, which is the previous bullet.

## File Structure

| file | responsibility after this plan |
| --- | --- |
| `src/flab2bp/layout/freeform.py` | the router. `_match_access_corridors` returns a `_CorridorMatch` (assignment + `converged`) and commits its best surveyed partial instead of `{}`; `_reserve_port_access` gains an `assignment_survey` callback and puts `converged` on the reservation; **new** `plan_power_infill` covers powered tiles a composed canvas added, given the towers already standing |
| `src/flab2bp/layout/hierarchy/compose.py` | packing + composition. Acts on a partial reservation, counts it as `partial` AND `degraded` so no partial can ever report a trustworthy verdict; calls `plan_power_infill` + `_place_power` after `_route_all` and reports what it could not cover as a named cut |
| `src/flab2bp/layout/hierarchy/dispatch.py` | the arm rule. Gains `SEQUENCE_PAIR_EXACT_FLOOR_S` (measured, not guessed) and a `budget_s` parameter: a coater-free block funded below the floor is UNCOVERED evidence, so it races both arms |
| `src/flab2bp/layout/hierarchy/strategy.py` | orchestration only. `_arms_for` passes the round's block budget to `dispatch_arms` and keys the arm cache on `(shape, budget)`; two new stats plumbed from `ComposeResult` |
| `src/flab2bp/layout/base.py` | `PlacementStats` gains `reservation_partial`, `power_infill_towers`, `power_uncovered_tiles` |
| `tests/layout/test_freeform.py` | `_match_access_corridors` partial commit and `converged`; `plan_power_infill` |
| `tests/layout/hierarchy/test_compose.py` | the partial-commit trigger, the R7 residual guard, the composition power pass |
| `tests/layout/hierarchy/test_dispatch.py`, `test_strategy.py` | the budget-aware arm rule and the cache key |
| `tests/test_pipeline.py` | the re-measured exact-layout deadline budget |
| `docs/superpowers/evidence/2026-09-07-hierarchical-v4/` | Task 3's oracle-vs-router measurement, Task 5's titanium-glass measurement, Task 6's floor measurement, Task 8's packer diagnosis, Task 9's gate |

---

### Task 1: `_match_access_corridors` commits the partial it already holds

**Lever:** 1 (headline). v3 gate §5 lever 1: `assigned = 0` of 91 demands on all six belt3 rungs and 0 of 144 on five of six zurl2 rungs, on demands each reporting `reachable_options = 2` — the A\* had proved two corridors reachable and the matcher declined to use either. `reservation_degraded = 1` on all five composing cells in both rounds: ten production compositions out of ten, in which Tasks 4 and 5 of v3 are computed and discarded.

**The exact condition, read off the shipped tree.** `_match_access_corridors` has six `return {}` sites. The one production takes is **`freeform.py:11924`** — the fall-off-the-end of `for _round in range(_ACCESS_CUT_ROUNDS):` (`freeform.py:11876`, `_ACCESS_CUT_ROUNDS = 8` at `freeform.py:376`). Each round, `validate` (`assignment_boundary_cut`, `freeform.py:12107`) returns the **FIRST** demand whose corridor cannot reach its goal plus the demands blocking it (`freeform.py:12152`), the matcher forbids exactly that combination (`freeform.py:11922`), and re-solves. Eight rounds can therefore convict at most eight witnesses out of 91 or 144 demands; the loop exhausts, and the `assigned` dict built at `freeform.py:11904-11911` — a complete cell-disjoint assignment of every demand, of which only a handful failed the goal probe — is dropped on the floor. The two other reachable give-ups also discard a held assignment: `freeform.py:11882` (`INFEASIBLE` with a validate callback) and `freeform.py:11898` (the no-incumbent feasibility re-solve failed).

**Why the discarded answer is worth committing.** `assignment_boundary_cut` asks that every corridor stay reachable with every OTHER corridor's cells forbidden — strictly stronger than what `_route_all` then does with rip-up and negotiation. `compose.py:894-898` says so in its own comment: the belt3 measurement had it discard all 102 demands on a canvas the router still wired 65 of 89 cuts on.

**Files:**
- Modify: `src/flab2bp/layout/freeform.py:11766-11924` (`_match_access_corridors`), `:11683-11693` (`PortAccessReservation`), `:12107-12153` (`assignment_boundary_cut`), `:12155-12168` (the call), `:12189` (the return)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `freeform._CorridorMatch(assigned: dict[PortAccessDemand, PortAccessCorridor], converged: bool)` — a `NamedTuple`; `_match_access_corridors` now returns this instead of a bare dict.
  - `_match_access_corridors(demands, corridors, *, validate=None, survey=None, cancelled=None, deadline=None) -> _CorridorMatch`, with `survey: Callable[[Mapping[PortAccessDemand, PortAccessCorridor]], Collection[PortAccessDemand]] | None`.
  - `PortAccessReservation` gains `converged: bool = True` as its last field. `PortAccessReservation.complete` is unchanged (`not self.missing`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/layout/test_freeform.py`. These are pure-function tests on the matcher: no canvas, no A\*.

```python
def _demand(index: int) -> freeform.PortAccessDemand:
    """One claim at a distinct cell, so `by_port` never groups two together."""
    return freeform.PortAccessDemand(
        cell=(10 * index, 0, 0),
        kind=freeform.PortAccessKind.INTERNAL_DEPARTURE,
        item="iron-ingot",
        belt=index,
        strip_index=None,
        columns=1,
    )


def _corridors(demand: freeform.PortAccessDemand) -> tuple[tuple[Cell, Cell], ...]:
    """Two disjoint (access, exit) pairs beside this demand's own cell."""
    x, y, z = demand.cell
    return (((x + 1, y, z), (x + 2, y, z)), ((x, y + 1, z), (x, y + 2, z)))


def test_the_matcher_commits_the_partial_when_the_cut_loop_runs_out_of_rounds() -> None:
    # Nine demands and a validate that convicts a DIFFERENT one every round:
    # eight cut rounds can never satisfy it, which is exactly the shape
    # production hits with 91 demands and _ACCESS_CUT_ROUNDS = 8.
    demands = [_demand(i) for i in range(9)]
    options = {demand: _corridors(demand) for demand in demands}
    rounds = 0

    def validate(assigned):
        nonlocal rounds
        rounds += 1
        return (demands[rounds % len(demands)],)

    def survey(assigned):
        # The two the cut loop never satisfied.
        return (demands[0], demands[1])

    match = freeform._match_access_corridors(
        demands, options, validate=validate, survey=survey
    )

    assert match.converged is False
    assert set(match.assigned) == set(demands[2:])
    assert len(match.assigned) == 7


def test_a_converged_match_reports_converged_and_assigns_everything() -> None:
    demands = [_demand(i) for i in range(4)]
    options = {demand: _corridors(demand) for demand in demands}

    match = freeform._match_access_corridors(
        demands, options, validate=lambda assigned: None, survey=lambda assigned: ()
    )

    assert match.converged is True
    assert set(match.assigned) == set(demands)


def test_no_demands_is_a_converged_empty_answer_not_a_give_up() -> None:
    # `compose`'s trigger used to spell this `goal_driven.assigned or not
    # demands`; it is now spelled by `converged`, so the empty case has to
    # keep saying yes or a demandless composition would degrade for nothing.
    match = freeform._match_access_corridors([], {}, validate=lambda a: None, survey=lambda a: ())

    assert match.converged is True
    assert match.assigned == {}


def test_a_surveyed_partial_never_keeps_a_corridor_the_survey_convicted() -> None:
    demands = [_demand(i) for i in range(5)]
    options = {demand: _corridors(demand) for demand in demands}

    match = freeform._match_access_corridors(
        demands,
        options,
        validate=lambda assigned: (demands[0],),
        survey=lambda assigned: tuple(assigned),
    )

    assert match.converged is False
    assert match.assigned == {}


def test_a_matcher_with_no_survey_gives_up_wholesale_as_before() -> None:
    # freeform's own default path passes `validate` and no `survey`; without a
    # survey there is no way to know which corridors are safe, so the old
    # wholesale give-up is what it must keep doing.
    demands = [_demand(i) for i in range(9)]
    options = {demand: _corridors(demand) for demand in demands}

    match = freeform._match_access_corridors(
        demands, options, validate=lambda assigned: (demands[0],)
    )

    assert match.converged is False
    assert match.assigned == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_freeform.py -k "matcher_commits or converged or surveyed_partial or wholesale_as_before or no_demands_is_a_converged" -x`
Expected: FAIL — `AttributeError: 'dict' object has no attribute 'converged'` (the function still returns a bare dict).

- [ ] **Step 3: Add `_CorridorMatch` above `_match_access_corridors`**

Insert immediately before `def _match_access_corridors(` at `freeform.py:11766`:

```python
class _CorridorMatch(NamedTuple):
    """What the joint matcher decided, and whether the decision is a verdict.

    ``converged`` is True ONLY when the validate/cut loop reached a fixed point
    -- every assigned corridor still reaching its own goal with every other
    corridor's cells forbidden -- or when there was no validator at all.  Every
    give-up is False, INCLUDING the ones that now hand back a partial, because
    a partial is ground the router can use and NOT an answer to the question
    the ladder asked.  `compose` must be able to tell those apart: see
    `hierarchy/compose.pack_with_access`, where a partial increments
    `degraded` precisely so that `reservation_degraded == 0` keeps meaning
    "the oracle answered, completely".
    """

    assigned: dict[PortAccessDemand, PortAccessCorridor]
    converged: bool
```

`NamedTuple` is already imported in `freeform.py`; if `mypy` says otherwise, add it to the `typing` import line.

- [ ] **Step 4: Rewrite the matcher's signature, give-ups and returns**

In `_match_access_corridors`, change the signature's return annotation to `-> _CorridorMatch` and add the `survey` parameter after `validate`:

```python
    survey: (
        Callable[
            [Mapping[PortAccessDemand, PortAccessCorridor]],
            Collection[PortAccessDemand],
        ]
        | None
    ) = None,
```

Append to the docstring, after the `_ACCESS_CUT_ROUNDS` sentence:

```
    WHEN THE CUT LOOP RUNS OUT OF ROUNDS, THE ASSIGNMENT IS NOT DISCARDED.
    ``validate`` names ONE witness per round, so ``_ACCESS_CUT_ROUNDS`` rounds
    can convict at most that many demands out of however many there are -- and
    a composed canvas raises 91 or 144 (v3 gate §5 lever 1).  Returning ``{}``
    there threw away a complete cell-disjoint assignment because a handful of
    its corridors failed a probe STRICTER than the router that follows: the
    probe forbids every other corridor's cells outright, while ``_route_all``
    negotiates and rips up.  So on give-up, ``survey`` -- which reports EVERY
    failing demand rather than the first -- is asked once, and what survives it
    is committed with ``converged=False``.  Dropping the failures can only free
    ground, so a corridor that reached its goal against the FULL selection
    still reaches it against the smaller one; the survivors need no re-check.
    Without a ``survey`` there is no way to know which corridors are safe, and
    the wholesale give-up is kept.
```

Replace the two early give-ups (currently `freeform.py:11858` and `:11863`):

```python
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return _CorridorMatch({}, False)
```

```python
    ordered_choices = tuple(choices)
    if not ordered_choices:
        # No demand had a single free option -- or there were no demands.  The
        # second is a COMPLETE answer to an empty question and must not make a
        # caller degrade; the first is a give-up.
        return _CorridorMatch({}, not demands)
```

Then replace the cut loop's body-end and its terminal return. The full block, from `for _round in range(_ACCESS_CUT_ROUNDS):` to the function's end:

```python
    best_partial: dict[PortAccessDemand, PortAccessCorridor] = {}

    def surrender() -> _CorridorMatch:
        """The largest assignment seen, minus everything the survey convicts."""
        if not best_partial or survey is None:
            return _CorridorMatch({}, False)
        failing = set(survey(best_partial))
        return _CorridorMatch(
            {demand: corridor for demand, corridor in best_partial.items() if demand not in failing},
            False,
        )

    for _round in range(_ACCESS_CUT_ROUNDS):
        status = solve_model(_ACCESS_TIE_DETERMINISTIC_WORK)
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            selected_values = solution_values()
        elif status == cp_model.INFEASIBLE:
            if validate is not None or fallback_values is None:
                return surrender()
            selected_values = fallback_values
        elif fallback_values is not None:
            selected_values = fallback_values
        else:
            # The bounded tie polish found no incumbent after a validation cut.
            # Re-establish a model-valid fallback without the polish objective;
            # the previous ranked solution is forbidden by the new cut.  The
            # feasibility solve carries the rank cap, so no solve here runs
            # unbounded; a cap that expires first leaves the candidate unmatched.
            model.clear_objective()  # type: ignore[no-untyped-call]
            try:
                fallback_status = solve_model(_ACCESS_RANK_DETERMINISTIC_WORK)
            finally:
                model.minimize(tie_objective)
            if fallback_status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                return surrender()
            fallback_values = solution_values()
            model.clear_hints()  # type: ignore[no-untyped-call]
            for choice, variable in choices.items():
                model.add_hint(variable, int(fallback_values[choice]))
            selected_values = fallback_values
        assigned: dict[PortAccessDemand, PortAccessCorridor] = {}
        selected_by_demand: dict[PortAccessDemand, cp_model.IntVar] = {}
        for choice in ordered_choices:
            if not selected_values[choice]:
                continue
            demand, access, exit_cell = choice
            assigned[demand] = PortAccessCorridor(access, exit_cell, demand.kind)
            selected_by_demand[demand] = choices[choice]
        witness = None if validate is None else validate(assigned)
        if (cancelled is not None and cancelled()) or _expired(deadline):
            raise _PreparationDeadline
        if validate is None or witness is None:
            return _CorridorMatch(assigned, True)
        # STRICTLY larger, so the FIRST round to reach a given size keeps it:
        # the rank solves already fixed each rank's total, so later rounds are
        # tie-break re-arrangements of the same size and re-surveying one buys
        # nothing but A* probes.
        if len(assigned) > len(best_partial):
            best_partial = assigned
        cut_variables = [
            selected_by_demand[demand] for demand in witness if demand in selected_by_demand
        ]
        if not cut_variables:
            return surrender()
        model.add(sum(cut_variables) <= len(cut_variables) - 1)
        fallback_values = None
    return surrender()
```

- [ ] **Step 5: Give `_reserve_port_access` a survey, and put `converged` on the reservation**

In `freeform.py`, replace `assignment_boundary_cut` (`:12107-12153`) with a factored pair. The per-demand probe is lifted out verbatim so the cut and the survey cannot drift apart:

```python
    def _selection(
        assigned: Mapping[PortAccessDemand, PortAccessCorridor],
    ) -> tuple[dict[Cell, PortAccessDemand], dict[PortAccessDemand, int], dict[int, PortAccessDemand]]:
        selected_cells: dict[Cell, PortAccessDemand] = {
            cell: owner
            for owner, selected in assigned.items()
            for cell in (selected.access, selected.exit)
        }
        ordered_owners = tuple(assigned)
        owner_index = {owner: index for index, owner in enumerate(ordered_owners)}
        return selected_cells, owner_index, dict(enumerate(ordered_owners))

    def _wall_between(
        demand: PortAccessDemand,
        corridor: PortAccessCorridor,
        selected_cells: Mapping[Cell, PortAccessDemand],
        owner_index: Mapping[PortAccessDemand, int],
    ) -> tuple[Cell, ...] | None:
        """The wall between this corridor and its goal, or None if it reaches.

        A ``BUDGET`` refusal is NOT a wall: the A* ran out of expansions, which
        says nothing about the ground, and convicting on it would drop
        corridors for the searcher's clock rather than for geometry.
        """
        goal = _goal_for(demand)
        if goal is None:
            return None
        result = _astar(
            canvas,
            [corridor.exit],
            goal,
            {},
            0.0,
            bounds,
            deadline=deadline,
            grid=shared_grid,
            forbidden={cell for cell, owner in selected_cells.items() if owner != demand},
            blocking_owners={
                cell: owner_index[owner]
                for cell, owner in selected_cells.items()
                if owner != demand
            },
        )
        check_cancelled()
        if result.path is not None or result.kind is RouteFailureKind.BUDGET:
            return None
        frontiers[demand].update(result.wall)
        return tuple(result.wall)

    def assignment_boundary_cut(
        assigned: Mapping[PortAccessDemand, PortAccessCorridor],
    ) -> Collection[PortAccessDemand] | None:
        if not probed or bounds is None:
            return None
        selected_cells, owner_index, owner_by_index = _selection(assigned)
        cell_owner_index = {cell: owner_index[owner] for cell, owner in selected_cells.items()}
        for demand, corridor in assigned.items():
            wall = _wall_between(demand, corridor, selected_cells, owner_index)
            if wall is None:
                continue
            blocking_demands = {
                owner_by_index[index]
                for cell in wall
                for index in (cell_owner_index.get(cell),)
                if index is not None
            }
            return (demand, *sorted(blocking_demands, key=lambda blocked: blocked.cell))
        return None

    def assignment_survey(
        assigned: Mapping[PortAccessDemand, PortAccessCorridor],
    ) -> Collection[PortAccessDemand]:
        """EVERY demand whose corridor cannot reach its goal, not just the first.

        ``assignment_boundary_cut`` short-circuits because one witness is all a
        no-good needs.  A partial commit needs the WHOLE failing set: committing
        a corridor the survey never looked at is exactly the wrong half of
        Ruling R7's residual.  This runs ONCE per reservation, on give-up only.
        """
        if not probed or bounds is None:
            return ()
        selected_cells, owner_index, _ = _selection(assigned)
        return tuple(
            demand
            for demand, corridor in assigned.items()
            if _wall_between(demand, corridor, selected_cells, owner_index) is not None
        )
```

Then the call site (`:12155-12162`) and the return:

```python
    try:
        match = _match_access_corridors(
            demands,
            reachable_options,
            validate=assignment_boundary_cut if probed else None,
            survey=assignment_survey if probed else None,
            cancelled=cancelled,
            deadline=deadline,
        )
    except _PreparationDeadline:
        canvas.reserved.clear()
        canvas.reserved.update(saved_reserved)
        canvas.port_corridors.clear()
        canvas.port_corridors.update(saved_corridors)
        raise
    assignments = match.assigned
```

and add `converged=match.converged,` as the last argument of the `PortAccessReservation(...)` return at `freeform.py:12189`.

Add the field to `PortAccessReservation` (`freeform.py:11684-11689`), last so the existing positional construction sites keep working:

```python
    #: Whether the joint matcher reached a fixed point, or handed back what it
    #: had.  `missing` on a NON-converged reservation is "what the survey
    #: convicted plus whatever was never assigned", which is a weaker claim
    #: than "the ground will not serve these".  A caller that reads
    #: `complete`/`missing` as a verdict MUST read this too.
    converged: bool = True
```

- [ ] **Step 6: Fix the direct callers in the test suite**

`_match_access_corridors` is called directly by `tests/layout/test_freeform.py`, `tests/layout/hierarchy/test_compose.py` and `tests/layout/test_sequence_solver.py`. Find every call with `mcp__serena__find_referencing_symbols` (grep misses aliased calls), and at each one replace `result = _match_access_corridors(...)` usage of the bare dict with `.assigned`. Do not change any assertion's meaning: a test that asserted `== {}` on a validate-carrying give-up still asserts `match.assigned == {}` unless it passes a `survey`.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/layout/test_freeform.py tests/layout/hierarchy/test_compose.py tests/layout/test_sequence_solver.py -x`
Expected: exit 0. Then `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src` — all 0.

- [ ] **Step 8: Commit**

```bash
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py \
        tests/layout/hierarchy/test_compose.py tests/layout/test_sequence_solver.py
git commit -m "fix(freeform): commit the corridor matcher's partial instead of giving up wholesale"
```

---

### Task 2: `compose` acts on a partial, and no partial ever reports a trustworthy verdict

**Lever:** 1. This is the half that closes v3 gate §6's open residual: "Ruling R7's discard triggers only on an assignment of exactly zero (`compose.py:899`, `goal_driven.assigned or not demands`). A small PARTIAL assignment — one corridor staked where v2 staked ~102 — would commit and report `reservation_degraded = 0`, i.e. a stats line claiming a trustworthy verdict when the oracle had in effect been thrown away."

With Task 1 shipped, that residual stops being hypothetical: partials become the common case. The rule this task ships is: **`reservation_degraded == 0` means and only means "the matcher converged"**, and a new `reservation_partial` counter says how many rungs committed a surveyed partial, so the gate can tell a partial from a discard.

**Files:**
- Modify: `src/flab2bp/layout/hierarchy/compose.py:173-196` (`PackedCanvas`), `:880-930` (`pack_with_access`'s degradation), `:134-153` (`ComposeResult`), `:1028-1037` (the return)
- Modify: `src/flab2bp/layout/base.py:452` (after `reservation_degraded: float`)
- Modify: `src/flab2bp/layout/hierarchy/strategy.py:759-763` (`_StrategyStats` plumbing), `:1128-1152` (`_StrategyStats`)
- Test: `tests/layout/hierarchy/test_compose.py`

**Interfaces:**
- Consumes: `PortAccessReservation.converged` and `_CorridorMatch` (Task 1).
- Produces:
  - `PackedCanvas` gains `partial: int = 0` (a ladder TOTAL, like `degraded`).
  - `ComposeResult` gains `reservation_partial: int = 0`.
  - `PlacementStats` gains `reservation_partial: float`; `_StrategyStats` gains `reservation_partial: float = 0.0`. The CLI prints it with no change, because `cli.py:558-565` formats the whole sorted stats dict.

- [ ] **Step 1: Write the failing tests**

Add to `tests/layout/hierarchy/test_compose.py`. These drive `pack_with_access`'s trigger directly by monkeypatching `compose_mod._reserve_port_access`, which is how the existing degradation tests in that file already work — read them first and reuse their `two_solved_blocks` fixture.

```python
def _reservation(demands, assigned_count, *, converged):
    """A `PortAccessReservation` over the first `assigned_count` demands."""
    served = demands[:assigned_count]
    return freeform.PortAccessReservation(
        assigned=tuple(
            (demand, freeform.PortAccessCorridor((0, 0, 0), (0, 1, 0), demand.kind))
            for demand in served
        ),
        missing=tuple(demands[assigned_count:]),
        evidence=(),
        converged=converged,
    )


def test_a_committed_partial_is_counted_as_partial_and_as_degraded(
    two_solved_blocks, monkeypatch
) -> None:
    # THE R7 RESIDUAL, PINNED. A one-corridor partial must never reach the
    # stats line with reservation_degraded=0, because that pair -- degraded 0,
    # missing 0 -- is the only way a reader can trust `missing`.
    seen: list[tuple[int, int]] = []

    def fake_reserve(canvas, demands, **kwargs):
        if kwargs.get("goals"):
            return _reservation(list(demands), 1, converged=False)
        raise AssertionError("the local-only oracle must not be re-asked for a partial")

    monkeypatch.setattr(compose_mod, "_reserve_port_access", fake_reserve)
    packed = compose_mod.pack_with_access(*two_solved_blocks, gap=2, deadline=None, ramped=False)

    assert len(packed.reservation.assigned) == 1
    assert packed.partial >= 1
    assert packed.degraded >= 1


def test_a_wholesale_empty_answer_still_falls_back_to_the_local_only_oracle(
    two_solved_blocks, monkeypatch
) -> None:
    asked_local = 0

    def fake_reserve(canvas, demands, **kwargs):
        nonlocal asked_local
        if kwargs.get("goals"):
            return _reservation(list(demands), 0, converged=False)
        asked_local += 1
        return _reservation(list(demands), len(list(demands)), converged=True)

    monkeypatch.setattr(compose_mod, "_reserve_port_access", fake_reserve)
    packed = compose_mod.pack_with_access(*two_solved_blocks, gap=2, deadline=None, ramped=False)

    assert asked_local >= 1
    assert packed.degraded >= 1
    assert packed.partial == 0


def test_a_converged_answer_is_neither_partial_nor_degraded(
    two_solved_blocks, monkeypatch
) -> None:
    def fake_reserve(canvas, demands, **kwargs):
        assert kwargs.get("goals"), "a converged trunk answer must not be re-asked"
        return _reservation(list(demands), len(list(demands)), converged=True)

    monkeypatch.setattr(compose_mod, "_reserve_port_access", fake_reserve)
    packed = compose_mod.pack_with_access(*two_solved_blocks, gap=2, deadline=None, ramped=False)

    assert packed.degraded == 0
    assert packed.partial == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/hierarchy/test_compose.py -k "committed_partial or wholesale_empty_answer or neither_partial_nor_degraded" -x`
Expected: FAIL — `AttributeError: 'PackedCanvas' object has no attribute 'partial'`.

- [ ] **Step 3: Add the counter to `PackedCanvas` and `ComposeResult`**

In `compose.py`, after `PackedCanvas.degraded`:

```python
    #: How many rungs committed a SURVEYED PARTIAL from the trunk-goal oracle
    #: -- an assignment the matcher handed back without converging, with the
    #: demands its own survey convicted already removed.  A ladder total, like
    #: `degraded`, and always <= it: every partial is also degraded, because
    #: `reservation_degraded == 0` has exactly one meaning and it is "the
    #: matcher converged".  This counter is what separates "the oracle was
    #: thrown away and v2's local question re-asked" (degraded, not partial)
    #: from "the oracle answered for most lane heads and named the rest"
    #: (both).  See v3 gate.md §6's open residual.
    partial: int = 0
```

After `ComposeResult.reservation_degraded`:

```python
    #: Of `reservation_degraded`, how many rungs committed a surveyed partial
    #: rather than falling back to the local-only oracle.
    reservation_partial: int = 0
```

- [ ] **Step 4: Rewrite the degradation branch**

In `pack_with_access`, replace the trigger at `compose.py:899` and the `else` that follows. Keep the existing long comment above it and append the new paragraph:

```python
        # A PARTIAL IS GROUND, NOT A VERDICT.  Since the matcher stopped giving
        # up wholesale it hands back the corridors its own survey did not
        # convict, and those are strictly better ground for `_route_all` than
        # the local-only answer -- the corridors are staked where the trunk
        # probe said they reach.  What a partial is NOT is an answer to the
        # ladder's question, so it counts as degraded as well as partial, and
        # `reservation_degraded == 0` keeps its one meaning.  An assignment of
        # NOTHING AT ALL while there were demands is still the wholesale
        # give-up Ruling R7 discards: it stakes no corridors, so acting on it
        # would leave the router worse off than v2's local-only oracle.
        if goal_driven is not None and goal_driven.converged:
            reservation = goal_driven
        elif goal_driven is not None and goal_driven.assigned:
            partial_rungs += 1
            degraded += 1
            reservation = goal_driven
        else:
            degraded += 1
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
                if best is None:
                    raise _PackingDeadline(packing) from None
                break
```

Initialise `partial_rungs = 0` beside the existing `degraded = 0` at the top of the ladder loop (find it with `find_symbol`; it is the accumulator `degraded += 1` writes to). **Name it `partial_rungs`, not `partial`** — `functools.partial` is imported in this module and used three lines below.

Carry it on the candidate and on the final return:

```python
        candidate = PackedCanvas(
            *packing,
            reservation=reservation,
            gap=rung,
            degraded=degraded,
            partial=partial_rungs,
        )
```

```python
    return replace(best, degraded=degraded, partial=partial_rungs)
```

- [ ] **Step 5: Plumb it out through `compose` and the stats**

`compose.py`'s `ComposeResult(...)` return (`:1028`) gains `reservation_partial=packed.partial,`.

`base.py`, immediately after `reservation_degraded: float` (`:452`):

```python
    #: Of `reservation_degraded`, the rungs that committed a SURVEYED PARTIAL
    #: from the trunk-goal oracle instead of falling back to v2's local-only
    #: question.  `degraded > 0, partial == 0` is "the oracle was thrown away";
    #: `partial > 0` is "the oracle answered for most lane heads and named the
    #: rest", and `reservation_missing` is then that named rest.
    reservation_partial: float
```

`strategy.py`: add `reservation_partial: float = 0.0` to `_StrategyStats` (after `reservation_degraded`), and at `:761` add
`stats.reservation_partial = float(composition.reservation_partial)`.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/layout/hierarchy/test_compose.py tests/layout/hierarchy/test_strategy.py tests/test_cli.py -x`
Expected: exit 0. Then `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src` — all 0.

- [ ] **Step 7: Commit**

```bash
git add src/flab2bp/layout/hierarchy/compose.py src/flab2bp/layout/base.py \
        src/flab2bp/layout/hierarchy/strategy.py tests/layout/hierarchy/test_compose.py
git commit -m "feat(hierarchy): act on a partial corridor reservation, and never let one claim a verdict"
```

---

### Task 3: Measure whether the oracle now predicts the router, on belt3 and zurl2

**Lever:** 1. v3 gate §5 lever 1 states the failure as a prediction failure: belt3's `missing` was constant at 91 while the router went 15, 16, 7, 9, 6, 3 across the ladder — the oracle's number tracked nothing. This task is the controlled before/after that lets Task 9's gate say whether it does now. **No production code changes here.**

**Files:**
- Create: `docs/superpowers/evidence/2026-09-07-hierarchical-v4/oracle-vs-router.md`, `run_probe.sh`, `probe.py`, `probe-{belt3,zurl2}-all-products-{before,after}.{json,log}` and their `-load.txt`

**Interfaces:**
- Consumes: Tasks 1 and 2 as shipped.
- Produces: the two numbers Task 9 §5 quotes — `missing` and `unrouted_cuts` per cell, before and after — and a written verdict on whether `missing` now moves with `unrouted`.

- [ ] **Step 1: Write `probe.py`**

Copy `docs/superpowers/evidence/2026-09-07-hierarchical-v3/run_cell.py` into the v4 evidence directory as `probe.py` and keep its contract: it calls `flab2bp.cli.main(argv)` with exactly the argv it is given, **monkeypatches nothing**, tees stderr, and parses the `  stats <strategy>/<candidate>: key=value ...` line the CLI prints on the refusal path (`cli.py:565`) into a JSON sidecar. Update its module docstring to say that `reservation_partial` is new in v4 and what it distinguishes.

- [ ] **Step 2: Take the BEFORE half at the merge base**

`git status --short` empty and everything committed first. Then:

```bash
export GIT_EDITOR=true
BASE=$(git merge-base master hierarchical-v4)
git checkout --detach "$BASE"
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "runnable_5s_mean=" sum/5}' \
    > /tmp/v4probe/probe-belt3-all-products-before-load.txt
uv run python /tmp/v4probe/probe.py /tmp/v4probe/probe-belt3-all-products-before.json \
    -- "<belt3 url>" --strategy hierarchical --budget 60 --band portable \
    --candidate-policy all-products -o /tmp/v4probe/belt3-before.blueprint.txt
# ... the same for zurl2 ...
git checkout hierarchical-v4
```

The evidence directory does not exist at the merge base, so the BEFORE half writes to `/tmp/v4probe/` and is copied in afterwards — the same procedure v3's `run_guard.sh` used, with **no `git stash` and no second worktree**. Verify `git rev-parse HEAD` and `git status --short` after the checkout back.

**ONE BUILD AT A TIME.** These are 60 s cells; run them sequentially, each with its own `-load.txt` taken immediately before.

- [ ] **Step 3: Take the AFTER half on the branch**

The same two cells at the branch's HEAD, writing directly into `docs/superpowers/evidence/2026-09-07-hierarchical-v4/`, each with its own `-load.txt`.

- [ ] **Step 4: Write `oracle-vs-router.md`**

A table with one row per cell and these columns, before and after: `cut_lanes`, `port_demands`, `reservation_degraded`, `reservation_partial`, `reservation_missing`, `unrouted_cuts`, `compose_gap`, in-process wall. Then answer, in prose, the three questions the gate needs:

1. **Does the matcher still give up wholesale?** `reservation_partial > 0` on a cell is the proof it does not. `reservation_degraded > 0` with `reservation_partial == 0` is the proof it still does, and that is a FAILED Lever 1 — say so plainly.
2. **Does `missing` now predict `unrouted`?** State `reservation_missing` and `unrouted_cuts` for both cells before and after. The claim to test is directional, not exact: the oracle predicts the router if `missing` moved in the same direction as `unrouted` on both cells. If `missing` is still constant while `unrouted` moves, Lever 1 is not delivered.
3. **Did `compose_gap` move off 2?** v3 pinned it at 2 on every cell because no rung could ever be ranked. A rung above 2 being committed is the first evidence in four gates that the ladder can rank.

**A caveat this document must carry**: zurl2's refusals were 69 of 70 (r1) and 71 of 73 (r2) `BUDGET` at 60 s in v3 — the router ran out of clock, not ground. Report zurl2's unrouted breakdown by class, and do not read a zurl2 `unrouted_cuts` change as geometry unless its non-`BUDGET` count changed.

- [ ] **Step 5: Commit**

```bash
git add -A docs/superpowers/evidence/2026-09-07-hierarchical-v4/
git commit -m "evidence: the corridor oracle against the router, before and after the partial commit"
```

---

### Task 4: Power the ground the composition adds

**Lever:** 2. v3 gate §2.3: `titanium-glass/all-products` at 60 s is the first hierarchical build in three gates to compose, wire **all 26 of its cut lanes** and reach `validate.certify` (`strategy.py:807`). It then refuses with `errors_by_check == {power.coverage: 4}` — one check, four findings, **nothing else wrong with the placement**. All four are DSP item 2020 `SPLITTER_ID` (`dsp/catalog.py:219`), 1x1, at tiles (63,3) and (62,1) at z=0 and z=2. The canvas has 5993 buildings, 80 splitters and 61 Tesla towers; **76 splitters are covered and 4 are not**, because each block brought towers sized for its own footprint and the ground `compose` opens between blocks carries none.

**The design, in three lines.** (1) Every powered tile the composed canvas holds is checked against the discs of the towers already standing, using the same doubled-integer predicate `validate._coverage` and `_place_power` use, so the pass and the validator cannot disagree about the radius. (2) The tiles nothing covers are covered by a greedy that is the composition-scoped twin of `_power_plan`'s: it stands towers only on cells that are free right now, refuses any site inside `rules.power_node_keepout_offsets` of an existing node (`game.power_too_close`), and requires every new site to be within link distance of a node already present so `power.connectivity` still holds. (3) It runs AFTER `_route_all`, because the powered things composition adds are splitters the ROUTER creates at taps (`_tap_source`) and no pre-routing pass can know where they will land — and what it cannot cover is reported as a named cut rather than left for `certify` to convict by building index.

**Files:**
- Create: `src/flab2bp/layout/freeform.py` — `plan_power_infill`, immediately after `_place_power` (`:15795-15838`)
- Modify: `src/flab2bp/layout/hierarchy/compose.py:36-54` (imports), `:1010-1037` (`compose`'s tail), `:134-153` (`ComposeResult`)
- Modify: `src/flab2bp/layout/base.py` (after `reservation_partial`), `src/flab2bp/layout/hierarchy/strategy.py` (`_StrategyStats` and the plumbing at `:759-763`)
- Test: `tests/layout/test_freeform.py`, `tests/layout/hierarchy/test_compose.py`

**Interfaces:**
- Consumes: `ComposeResult` and `_StrategyStats` as Task 2 left them.
- Produces:
  - `freeform.plan_power_infill(canvas: _Canvas, *, cancelled: Callable[[], bool] | None = None) -> tuple[list[tuple[int, int]], tuple[tuple[int, int], ...]]` — `(sites, uncovered_tiles)`. Sites are ground coordinates for `_place_power`; `uncovered_tiles` are the tiles no legal site could reach.
  - `ComposeResult` gains `power_infill: int = 0` and `power_uncovered: int = 0`.
  - `PlacementStats`/`_StrategyStats` gain `power_infill_towers: float` and `power_uncovered_tiles: float`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/layout/test_freeform.py`. Build the canvas with whatever helper the existing `_power_plan` tests in that file use — read them first; they are the construction shape this must match.

```python
def test_the_infill_covers_a_splitter_the_blocks_towers_do_not_reach() -> None:
    # One tower at the origin, and a splitter far enough away to be dark. The
    # shape of v3 gate §2.3: 76 of 80 splitters covered, 4 not.
    canvas = _canvas_with_limit((0, 0, 60, 20))
    _stand_tower(canvas, 0, 0)
    _stand_splitter(canvas, 20, 0)

    sites, uncovered = freeform.plan_power_infill(canvas)

    assert uncovered == ()
    assert len(sites) == 1


def test_the_infill_places_nothing_when_every_powered_tile_is_already_covered() -> None:
    canvas = _canvas_with_limit((0, 0, 60, 20))
    _stand_tower(canvas, 10, 0)
    _stand_splitter(canvas, 11, 0)

    assert freeform.plan_power_infill(canvas) == ([], ())


def test_the_infill_never_strands_a_tower_outside_the_existing_network() -> None:
    # A splitter beyond every legal linked site: covering it would place a
    # tower `power.connectivity` then convicts, which is a worse blueprint
    # than a named uncovered tile.
    canvas = _canvas_with_limit((0, 0, 400, 20))
    _stand_tower(canvas, 0, 0)
    _stand_splitter(canvas, 380, 0)

    sites, uncovered = freeform.plan_power_infill(canvas)

    assert sites == []
    assert (380, 0) in uncovered


def test_the_infill_refuses_a_site_inside_another_nodes_keepout() -> None:
    # `game.power_too_close`: two power nodes closer than 3.5 world units are
    # refused by the paste, and a Tesla Tower has no build collider, so
    # nothing else in this file could see it.
    canvas = _canvas_with_limit((0, 0, 60, 20))
    _stand_tower(canvas, 20, 0)
    _stand_splitter(canvas, 33, 0)

    sites, uncovered = freeform.plan_power_infill(canvas)

    keepout = {
        (20 + dx, 0 + dy)
        for dx, dy, dz in rules.power_node_keepout_offsets(
            catalog.building(catalog.TESLA_TOWER_ID).power_node,
            catalog.building(catalog.TESLA_TOWER_ID).power_node,
        )
        if dz == 0
    }
    assert not set(sites) & keepout
```

And to `tests/layout/hierarchy/test_compose.py`:

```python
def test_composition_reports_a_tile_it_could_not_power_as_a_named_cut(
    two_solved_blocks, monkeypatch
) -> None:
    monkeypatch.setattr(
        compose_mod, "plan_power_infill", lambda canvas, **kwargs: ([], ((63, 3),))
    )

    result = compose_mod.compose(*two_solved_blocks, gap=2, ramped=False, deadline=None)

    assert result.power_uncovered == 1
    assert any("power.coverage" in failure and "(63,3)" in failure for failure in result.failures)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_freeform.py -k plan_power_infill tests/layout/hierarchy/test_compose.py -k could_not_power -x`
Expected: FAIL — `AttributeError: module 'flab2bp.layout.freeform' has no attribute 'plan_power_infill'`.

- [ ] **Step 3: Write `plan_power_infill`**

Insert after `_place_power` in `freeform.py`:

```python
def plan_power_infill(
    canvas: _Canvas,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[list[tuple[int, int]], tuple[tuple[int, int], ...]]:
    """Towers for powered tiles the towers already standing do not reach.

    :func:`_power_plan` decides a whole block's network BEFORE routing, from an
    envelope, and that is the right shape for a block: the pack is known, the
    ground is free, and a tower planned there is held in ``keep_out`` until it
    is stood.  A COMPOSED canvas cannot be planned that way, and the reason is
    not tidiness.  Each block arrives with its own network already built and
    sized for its own footprint; what the composition ADDS is belts (unpowered)
    and the Splitters :func:`_commit_paths` creates at taps -- and where a tap
    lands is decided by the router, on ground that only exists once the blocks
    are packed.  Planning the composed envelope before routing would either
    re-plan 61 towers that are already correct or blanket the gap with towers
    for tiles nothing will ever occupy.

    So this is a COVER OF WHAT IS ACTUALLY THERE, run after ``_route_all``.  It
    is small by construction -- v3 measured 76 of 80 Splitters already covered
    on ``titanium-glass/all-products`` -- and it is honest about its one
    weakness: the ground is whatever routing left, so a tile with no legal free
    site is REPORTED rather than papered over.  A reported tile is a named cut
    the composer refuses on; the alternative is ``validate.certify`` convicting
    it several stages later by building index (v3 gate.md §2.3).

    Three legality rules, all consulted rather than restated:

    * **Coverage** uses the doubled-integer predicate ``validate._coverage``
      and :func:`_place_power` use, so this pass and the validator cannot
      disagree about a radius.
    * **``game.power_too_close``** -- no site inside
      ``rules.power_node_keepout_offsets`` of any node already present, tower
      or mode-driven machine.
    * **``power.connectivity``** -- every new site must lie within link
      distance of a node already present, taking ``max`` of the two link
      distances exactly as ``validate._connectivity`` does, so a new tower
      joins the network instead of stranding itself.

    Returns ``(sites, uncovered)``: ground coordinates for
    :func:`_place_power`, and the tiles no legal site could reach.
    """
    tower = catalog.building(catalog.TESLA_TOWER_ID)
    reach2 = math.floor((2 * tower.cover_radius) ** 2)
    link2 = math.floor((2 * tower.connect_distance) ** 2)

    #: (doubled centre x, doubled centre y, doubled cover radius squared,
    #: doubled connect distance squared) for every node already standing.
    nodes: list[tuple[int, int, int, int]] = []
    keepout: set[tuple[int, int]] = set()
    for b in canvas.buildings:
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        try:
            info = catalog.building(b.item_id)
        except KeyError:
            continue
        if info.cover_radius > 0:
            nodes.append(
                (
                    2 * b.x + b.width,
                    2 * b.y + b.height,
                    math.floor((2 * info.cover_radius) ** 2),
                    math.floor((2 * info.connect_distance) ** 2),
                )
            )
        if info.power_node.is_power_node:
            cx, cy = b.x + b.width // 2, b.y + b.height // 2
            for dx, dy, dz in rules.power_node_keepout_offsets(info.power_node, tower.power_node):
                if not dz:
                    keepout.add((cx + dx, cy + dy))

    def covered(tx: int, ty: int) -> bool:
        dx, dy = 2 * tx + 1, 2 * ty + 1
        return any(
            (dx - ox) * (dx - ox) + (dy - oy) * (dy - oy) <= lim for ox, oy, lim, _link in nodes
        )

    # EVERY NON-BELT BUILDING, INCLUDING THE SUPPLIERS.  `validate`'s `_POWERED`
    # is {MACHINE, SORTER, SPLITTER, PILER, ADDON} and a mode-driven machine
    # that also supplies power is a MACHINE, so it is checked for coverage
    # there too -- and it covers itself, so including it here costs nothing and
    # keeps the two sets from drifting.  Altitude is not in the predicate: a
    # stack of belts over one ground cell is one question, not three.
    dark: set[tuple[int, int]] = set()
    for b in canvas.buildings:
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        if catalog.is_belt(b.item_id):
            continue
        for tx, ty, _tz in b.tiles():
            if (tx, ty) not in dark and not covered(tx, ty):
                dark.add((tx, ty))
    if not dark:
        return [], ()

    limit = canvas.limit
    if limit is None:  # pragma: no cover - `canvas_for` always sets it
        return [], tuple(sorted(dark))
    min_x, min_y, max_x, max_y = limit
    blocked_columns = {(bx, by) for (bx, by, _level) in canvas.blocked}

    def free_site(x: int, y: int) -> bool:
        return (
            min_x <= x <= max_x
            and min_y <= y <= max_y
            and (x, y) not in keepout
            and (x, y) not in blocked_columns
            and (x, y) not in canvas.solid
            and canvas.free((x, y, 0))
        )

    reach = int(tower.cover_radius) + 1
    sites: list[tuple[int, int]] = []
    while dark:
        if cancelled is not None and cancelled():
            raise _PreparationDeadline
        # Only a cell within reach of a still-dark tile can cover anything, so
        # the candidate set is the dark set dilated by the coverage disc rather
        # than the whole composed canvas.
        candidates = sorted(
            {
                (tx + dx, ty + dy)
                for tx, ty in dark
                for dx in range(-reach, reach + 1)
                for dy in range(-reach, reach + 1)
                if free_site(tx + dx, ty + dy)
            }
        )
        best_site: tuple[int, int] | None = None
        best_cover: set[tuple[int, int]] = set()
        for cx, cy in candidates:
            ox, oy = 2 * cx + tower.width, 2 * cy + tower.height
            if not any(
                (ox - px) * (ox - px) + (oy - py) * (oy - py) <= (link2 if link2 > plink else plink)
                for px, py, _cover, plink in nodes
            ):
                continue
            cover = {
                (tx, ty)
                for tx, ty in dark
                if (ox - (2 * tx + 1)) ** 2 + (oy - (2 * ty + 1)) ** 2 <= reach2
            }
            # STRICTLY more, so the first site in sorted order wins a tie and
            # the answer does not depend on set iteration order.
            if len(cover) > len(best_cover):
                best_site, best_cover = (cx, cy), cover
        if best_site is None:
            break
        sites.append(best_site)
        dark -= best_cover
        ox, oy = 2 * best_site[0] + tower.width, 2 * best_site[1] + tower.height
        nodes.append((ox, oy, reach2, link2))
        for dx, dy, dz in rules.power_node_keepout_offsets(tower.power_node, tower.power_node):
            if not dz:
                keepout.add((best_site[0] + dx, best_site[1] + dy))
    return sites, tuple(sorted(dark))
```

Add `plan_power_infill` to `freeform.py`'s `__all__` if that module has one covering this region; if it does not, no export change is needed.

- [ ] **Step 4: Call it from `compose`**

Add `_Unpowerable` and `plan_power_infill` to the `from flab2bp.layout.freeform import (...)` block at `compose.py:36`, keeping the list alphabetised as it is now.

In `compose()`, immediately after the `accounted` block that extends `failures` and before `return ComposeResult(...)` (`compose.py:1027`):

```python
    # THE GROUND THE COMPOSITION OPENED IS NOT POWERED BY ANY BLOCK'S PLAN.
    # Each block brought towers sized for its own footprint; the Splitters the
    # router just created at taps between blocks stand on ground none of them
    # reaches.  v3 gate.md §2.3: 76 of 80 covered, 4 not, and those 4 were the
    # ONLY thing wrong with the first placement this strategy ever composed.
    infill_sites, unpowered = plan_power_infill(canvas, cancelled=partial(_spent, deadline))
    try:
        _place_power(canvas, infill_sites)
    except _Unpowerable as exc:
        # A planned site taken between the plan and the stand is a reservation
        # bug, and it is REPORTED here rather than raised: this runs after the
        # router, so there is a composed placement worth naming a cut on.
        infill_sites = []
        failures.append(f"composition power infill: {exc}")
    failures.extend(
        f"power.coverage: composed tile ({tx},{ty}) is outside every tower's supply "
        "radius and no free, linked, legal site can cover it"
        for tx, ty in unpowered
    )
```

`_place_power` is already imported? Check the import block; if not, add it. Then the return gains:

```python
        power_infill=len(infill_sites),
        power_uncovered=len(unpowered),
```

and `ComposeResult` gains, after `reservation_partial`:

```python
    #: Towers the composition stood for powered tiles no block's plan reached,
    #: and tiles it could not cover at all.  A non-zero `power_uncovered` is
    #: always accompanied by one `failures` entry per tile.
    power_infill: int = 0
    power_uncovered: int = 0
```

- [ ] **Step 5: Plumb the two stats**

`base.py`, after `reservation_partial`:

```python
    #: Towers the COMPOSITION stood, over and above what the blocks brought,
    #: for powered tiles its own added Splitters put on unreached ground.
    power_infill_towers: float
    #: Composed tiles the infill could not cover with a free, linked, legal
    #: site.  Every one of them is also a named cut in the refusal.
    power_uncovered_tiles: float
```

`strategy.py`: the same two fields on `_StrategyStats` (defaulting to `0.0`), and beside the existing plumbing at `:759-763`:

```python
        stats.power_infill_towers = float(composition.power_infill)
        stats.power_uncovered_tiles = float(composition.power_uncovered)
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/layout/test_freeform.py tests/layout/hierarchy/ tests/test_cli.py -x`
Expected: exit 0. Then `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src` — all 0.

- [ ] **Step 7: Commit**

```bash
git add src/flab2bp/layout/freeform.py src/flab2bp/layout/hierarchy/compose.py \
        src/flab2bp/layout/base.py src/flab2bp/layout/hierarchy/strategy.py \
        tests/layout/test_freeform.py tests/layout/hierarchy/test_compose.py
git commit -m "feat(hierarchy): power the ground the composition adds"
```

---

### Task 5: Measure titanium-glass at 60 s, immediately

**Lever:** 2. This is the cell that was four `power.coverage` findings away from the first blueprint this project has ever emitted from `hierarchical`. It is measured here, on its own, rather than waiting for Task 9, because if it now emits then Lever 2 is delivered and Task 9 only has to confirm it — and if it does not, Tasks 6-8 need to know what convicted it instead. **No production code changes here.**

**Files:**
- Create: `docs/superpowers/evidence/2026-09-07-hierarchical-v4/titanium-glass-b60-{r1,r2}.{json,log}`, their `-load.txt`, `titanium-glass-b60.blueprint.txt` if one is emitted, `certify-titanium-glass.{json,log}` and `power.md`
- Copy in: `certify_probe.py` from `../2026-09-07-hierarchical-v3/`

**Interfaces:**
- Consumes: Task 4's `power_infill_towers` / `power_uncovered_tiles` stats and the `power.coverage` failure strings.
- Produces: the `area / best_known` datapoint Task 9 reports for this cell, and the `errors_by_check` breakdown if it still refuses.

- [ ] **Step 1: Run the cell twice, one build at a time**

```bash
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "runnable_5s_mean=" sum/5}' \
    > docs/superpowers/evidence/2026-09-07-hierarchical-v4/titanium-glass-b60-r1-load.txt
uv run python docs/superpowers/evidence/2026-09-07-hierarchical-v4/probe.py \
    docs/superpowers/evidence/2026-09-07-hierarchical-v4/titanium-glass-b60-r1.json \
    -- "<titanium-glass url>" --strategy hierarchical --budget 60 --band portable \
    --candidate-policy all-products \
    -o docs/superpowers/evidence/2026-09-07-hierarchical-v4/titanium-glass-b60.blueprint.txt
```

Then r2, with its own `-load.txt`. The URL is in `docs/superpowers/evidence/2026-09-06-debug-url/README.md`.

- [ ] **Step 2: If it EMITS — certify the artifact independently**

`-o` writing a file is not the same claim as "zero certify errors". Run `certify_probe.py` (copied from v3's evidence directory — a read-only wrapper on `validate.certify` with the same argv) and record `errors_by_check`, the building count, the area, the tower count and the splitter count. v3's numbers to compare against: 5993 buildings, area **11297** against a best-known **5727** (1.97x), 80 splitters, 61 towers, 76 of 80 covered.

- [ ] **Step 3: If it REFUSES — say exactly what convicted it**

Three shapes and each means something different:

* `power.coverage` findings again, with `power_uncovered_tiles = 0` in the stats: the infill covered everything it saw, and something between `compose` and `certify` moved a building or added one. `strategy.py:788-800` runs `assign_sorter_slots`, `finalize.compact_open_boundary_belts` and `finalize.finalize_placement` after `compose` returns and before `certify` — name which one, by re-certifying the placement at each stage in a throwaway probe script.
* `power.coverage` named as a composed cut, with `power_uncovered_tiles > 0`: the infill ran out of legal ground. Record how many tiles and where; that is a real Lever 2 residual and it goes in `power.md` and in Task 9 §5.
* A different check entirely: record `errors_by_check` in full. A new check firing is the composed canvas's next defect and it is Task 9's §5 lever material.

- [ ] **Step 4: Write `power.md`**

The two rounds' verdicts, walls and loads; the stats line from each; `power_infill_towers` and `power_uncovered_tiles`; and the certify breakdown. State the comparison to v3 explicitly: **v3 measured 4 `power.coverage` findings, one check, nothing else wrong.** Whether that is now zero is the whole content of this document.

- [ ] **Step 5: Commit**

```bash
git add -A docs/superpowers/evidence/2026-09-07-hierarchical-v4/
git commit -m "evidence: titanium-glass at 60s after the composition power pass"
```

---

### Task 6: Measure the sequence-pair exact-preparation floor, and re-point the red deadline test

**Lever:** 3(a). v3 gate §2.2: `mall/no-proliferator` refuses in both rounds with **31 blocks, all 31 `REFUSED: deadline exhausted before finding an exact layout`** (`sequence_solver.py:1602`), with `exact validation failures: geom.collide`. The dispatch column says why the whole cell is on one arm: `arm_dispatch_freeform = 0`, because that policy creates no spray lanes, `coaters == 0` on every block, and `dispatch.py:122-125` can then only return `(ARM_SEQUENCE_PAIR,)`. The measured cost is **6 blocks never placed under both arms against 31 under one** — a 5x regression on the clause the plan exists to close, on the one cell where the feature key has no signal.

Before the rule can be changed, the floor has to exist as a number. This task measures it and ships it as a constant, and takes the same measurement's by-product to fix the red test.

**Files:**
- Create: `docs/superpowers/evidence/2026-09-07-hierarchical-v4/exact-floor.md`, `floor_probe.py`, `floor-{block}-{budget}.{json,log}` and their `-load.txt`
- Modify: `src/flab2bp/layout/hierarchy/dispatch.py:41-43` (the constant block)
- Modify: `tests/test_pipeline.py:707-768`
- Test: `tests/layout/hierarchy/test_dispatch.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `dispatch.SEQUENCE_PAIR_EXACT_FLOOR_S: float` — the per-block budget below which `sequence-pair` did not once produce an exact layout for a coater-free mall block in this measurement. Task 7 consumes it.

- [ ] **Step 1: Write `floor_probe.py`, which solves ONE named block at ONE budget**

It must not run a whole build. It partitions the mall spec exactly as the strategy does and hands one block's sub-spec to one arm:

```python
"""Solve one partitioned block at one budget, with one arm, and report.

No monkeypatching: this calls the same `partition.initial_partition` /
`partition.sub_spec` / `SequencePairLayout` the strategy calls, at the same
`STRIP_CAP_DEFAULT`, so a refusal here is the refusal a block would get in a
build -- minus the pool, which is what makes it cheap enough to sweep.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from flab2bp import pipeline
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import NoValidLayout
from flab2bp.layout.hierarchy.partition import initial_partition, sub_spec
from flab2bp.spec import CandidatePolicy


def main(argv: list[str]) -> int:
    out, url, policy_name, block_index, budget_s = (
        Path(argv[0]),
        argv[1],
        argv[2],
        int(argv[3]),
        float(argv[4]),
    )
    spec = pipeline.spec_for(url, CandidatePolicy[policy_name])
    partitioned = initial_partition(spec)
    block = partitioned.blocks[block_index]
    sub = sub_spec(spec, block, block_index)
    started = time.monotonic()
    record: dict[str, object] = {
        "block": block_index,
        "budget_s": budget_s,
        "recipes": sorted({unit.recipe_id for unit in block}),
    }
    try:
        from flab2bp.layout.sequence_pair import SequencePairLayout

        placement = SequencePairLayout(
            band_policy=BandPolicy.portable(), time_budget_s=budget_s
        ).lay_out(sub)
        record |= {"ok": True, "area": placement.area}
    except NoValidLayout as refusal:
        record |= {"ok": False, "verdict": str(refusal)[:600]}
    record["wall_s"] = round(time.monotonic() - started, 3)
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

**The names `pipeline.spec_for`, `Partition.blocks`, `SequencePairLayout(...)` and `BandPolicy.portable()` are the shapes to verify before running**, with `mcp__serena__find_symbol` on `pipeline`, `partition.Partition` and `sequence_pair`. If the real constructor differs, use the real one — this script's job is to be the production call, not a re-implementation of it.

- [ ] **Step 2: Pick the blocks to sweep, from v3's own evidence**

`docs/superpowers/evidence/2026-09-07-hierarchical-v3/large-mall-no-proliferator-b60-r1.json` names the 31 refusing blocks and their recipes: 9 `magnet`, 7 `iron-ingot`, 6 `electric-motor`, 2 each of `copper-ingot`, `magnetic-coil`, `electromagnetic-turbine` and `super-magnetic-ring`, plus one multi-recipe block (`circuit-board, sorter-1, sorter-2`). Sweep **five** blocks: one `magnet`, one `iron-ingot`, one `electric-motor`, one `super-magnetic-ring`, and the multi-recipe one — the shapes that carry 24 of the 31.

- [ ] **Step 3: Sweep the budget ladder, one build at a time**

For each of the five blocks, at budgets **5.0, 7.5, 10.0, 15.0, 20.0** seconds — `BLOCK_BUDGET_MIN_S` to `BLOCK_BUDGET_MAX_S`, the whole range the funding rule can ever hand a block — with a `-load.txt` beside every run:

```bash
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "runnable_5s_mean=" sum/5}' > floor-b20-5.0-load.txt
uv run python floor_probe.py floor-b20-5.0.json "<mall url>" NO_PROLIFERATOR 20 5.0
```

- [ ] **Step 4: Decide the constant, by a stated rule**

**`SEQUENCE_PAIR_EXACT_FLOOR_S` is the smallest swept budget at which every one of the five blocks produced an exact layout.** If no swept budget does — i.e. `sequence-pair` refuses some block even at 20.0 s — set the constant to `BLOCK_BUDGET_MAX_S + 1.0 = 21.0` and say in `exact-floor.md` that **no per-block budget the funding rule can produce is above the floor**, which makes Task 7's abstain unconditional for coater-free blocks and is a stronger finding, not a weaker one. Record the full 25-cell grid (five blocks x five budgets) with wall and verdict for each. Never round a measured number into a nicer one.

- [ ] **Step 5: Ship the constant**

In `dispatch.py`, after `UNCOVERED_STRIPS = 85`:

```python
#: The smallest per-block budget at which `sequence-pair` produced an exact
#: layout for EVERY coater-free mall block measured in
#: `docs/superpowers/evidence/2026-09-07-hierarchical-v4/exact-floor.md`.
#: Below it, the arm's own exact preparation is cancelled mid-flight and the
#: block comes back "deadline exhausted before finding an exact layout"
#: (`sequence_solver.py:1602`) -- which is what 31 of `mall/no-proliferator`'s
#: 54 blocks did in the v3 gate, on an arm the rule had chosen for them.
#:
#: THIS IS A MEASUREMENT, NOT A TUNING KNOB.  Re-measure it with
#: `floor_probe.py` before changing it; a value picked to make a cell pass is
#: the thing the `UNCOVERED_*` thresholds exist to avoid.
SEQUENCE_PAIR_EXACT_FLOOR_S = <the measured value>
```

Add it to `__all__`. Add a test to `tests/layout/hierarchy/test_dispatch.py`:

```python
def test_the_exact_preparation_floor_is_inside_the_block_budget_range_or_above_it() -> None:
    # A floor below BLOCK_BUDGET_MIN_S would mean the rule can never fire and
    # the constant is dead; the measurement is what decides which side it is
    # on, so this only pins that it is a real second and not a placeholder.
    assert dispatch.SEQUENCE_PAIR_EXACT_FLOOR_S >= strategy.BLOCK_BUDGET_MIN_S
```

- [ ] **Step 6: Re-measure the red test's ceiling and lower its budget**

`tests/test_pipeline.py::test_all_products_sequence_pair_honours_the_exact_layout_deadline` is red on master because preparation got faster and 1.5 s no longer exhausts. Its own comment says what to do — "Lower the budget until the refusal is reliable again (and re-measure the ceiling), rather than relaxing the assertion."

Sweep `DEADLINE_REGRESSION_URL` at budgets 0.4, 0.6, 0.8, 1.0, 1.25, 1.5 s, **three runs each**, recording verdict and wall into `exact-floor.md`:

```bash
uv run pytest tests/test_pipeline.py::test_all_products_sequence_pair_honours_the_exact_layout_deadline -x
```
after editing `budget` to each value; a run that raises `NoValidLayout` with `deadline exhausted` is a pass.

**The new ceiling is the smallest swept budget at which any of the three runs SUCCEEDED**, and the new `budget` is the largest swept value strictly below it that refused 3 of 3. Update the constant AND the comment's measured numbers — the comment carries the date, the ceiling and the reason, and a stale comment there is worse than none:

```python
    # Re-measured 2026-09-07 (hierarchical v4 Task 6, `exact-floor.md`): the
    # 2026-09-01 budget of 1.5s no longer exhausts -- preparation got faster
    # again -- so this build SUCCEEDED at 1.5s and the test was red on master.
    # THE CEILING IS <measured>s, MEASURED: at <ceiling> the solver sometimes
    # SUCCEEDS on this URL, so the budget has to stay strictly below it or the
    # test is flaky rather than wrong. <new budget> refused 3 of 3 runs.
    #
    # So this budget is a moving target by design: the next preparation
    # speedup that makes <new budget>s enough to finish will fail here with
    # `DID NOT RAISE NoValidLayout`. That failure is the test working. Lower
    # the budget until the refusal is reliable again (and re-measure the
    # ceiling), rather than relaxing the assertion.
    budget = <new budget>
```

Leave the `sequence_islands=1` paragraph and the `preparation_deadline_fires > 0` assertion exactly as they are: both are load-bearing and neither is what went stale.

- [ ] **Step 7: Run the tests and write `exact-floor.md`**

Run: `uv run pytest tests/test_pipeline.py::test_all_products_sequence_pair_honours_the_exact_layout_deadline tests/layout/hierarchy/test_dispatch.py -x`
Expected: exit 0 — and this is the commit that takes that test off the known-reds list.

`exact-floor.md` carries: the 25-cell block grid, the 18-run deadline-test grid, the two derived numbers with the rule that derived each, and every `-load.txt`.

- [ ] **Step 8: Commit**

```bash
git add -A docs/superpowers/evidence/2026-09-07-hierarchical-v4/ \
        src/flab2bp/layout/hierarchy/dispatch.py tests/test_pipeline.py \
        tests/layout/hierarchy/test_dispatch.py
git commit -m "fix(dispatch): measure the sequence-pair exact-preparation floor; re-point the deadline test"
```

---

### Task 7: A coater-free block funded below the floor races both arms

**Lever:** 3(a). v3 gate §5 lever 3: "The lever is to give `dispatch_arms` an 'abstain' answer for a feature vector the evidence does not cover — `coaters == 0` with `strips` below `UNCOVERED_STRIPS = 85` is currently indistinguishable from a genuine sequence-pair block — and to re-measure both malls under it." Task 6 turned "the evidence does not cover it" into a number. This task spends it.

**The rule, and why it is a third `UNCOVERED_*` branch rather than a tuning.** The cross-tab `dispatch.py`'s own docstring quotes measured an AREA RATIO between two arms that both finished. A block whose budget is below the exact-preparation floor has no such ratio: the sequence-pair arm does not finish at all, so the evidence the rule is read off says nothing about it. That is exactly the condition `UNCOVERED_ITEMS_ABOVE_ONE_BELT` and `UNCOVERED_STRIPS` already handle by racing both arms, and it gets the same answer.

**Files:**
- Modify: `src/flab2bp/layout/hierarchy/dispatch.py:102-126` (`dispatch_arms`)
- Modify: `src/flab2bp/layout/hierarchy/strategy.py:572` (`arm_cache` type), `:613`, `:625`, `:672`, `:842-882` (`_arms_for`), `:908`, `:940`
- Test: `tests/layout/hierarchy/test_dispatch.py`, `tests/layout/hierarchy/test_strategy.py`

**Interfaces:**
- Consumes: `dispatch.SEQUENCE_PAIR_EXACT_FLOOR_S` (Task 6).
- Produces:
  - `dispatch_arms(features: BlockFeatures, arms: tuple[str, ...], *, budget_s: float | None = None) -> tuple[str, ...]`. `budget_s=None` keeps v3's exact behaviour, so every existing caller and test is unchanged by construction.
  - `HierarchicalLayout._arms_for(self, spec, entry, cache, *, block_budget: float) -> tuple[str, ...]`, with `cache: dict[tuple[ShapeKey, float], tuple[str, ...]]`.

- [ ] **Step 1: Write the failing tests**

`tests/layout/hierarchy/test_dispatch.py`:

```python
def test_a_coater_free_block_below_the_exact_floor_races_both_arms() -> None:
    features = dispatch.BlockFeatures(strips=4, coaters=0, items_above_one_belt=0)
    arms = (dispatch.ARM_FREEFORM, dispatch.ARM_SEQUENCE_PAIR)

    assert dispatch.dispatch_arms(
        features, arms, budget_s=dispatch.SEQUENCE_PAIR_EXACT_FLOOR_S - 0.1
    ) == arms


def test_a_coater_free_block_at_or_above_the_floor_still_goes_to_sequence_pair() -> None:
    features = dispatch.BlockFeatures(strips=4, coaters=0, items_above_one_belt=0)
    arms = (dispatch.ARM_FREEFORM, dispatch.ARM_SEQUENCE_PAIR)

    assert dispatch.dispatch_arms(
        features, arms, budget_s=dispatch.SEQUENCE_PAIR_EXACT_FLOOR_S
    ) == (dispatch.ARM_SEQUENCE_PAIR,)


def test_a_coatered_block_below_the_floor_is_unaffected() -> None:
    # The floor is about sequence-pair's exact preparation. A block the rule
    # sends to FREEFORM is not funded against that floor at all.
    features = dispatch.BlockFeatures(strips=3, coaters=2, items_above_one_belt=0)
    arms = (dispatch.ARM_FREEFORM, dispatch.ARM_SEQUENCE_PAIR)

    assert dispatch.dispatch_arms(features, arms, budget_s=1.0) == (dispatch.ARM_FREEFORM,)


def test_omitting_the_budget_keeps_the_v3_answer_exactly() -> None:
    features = dispatch.BlockFeatures(strips=4, coaters=0, items_above_one_belt=0)
    arms = (dispatch.ARM_FREEFORM, dispatch.ARM_SEQUENCE_PAIR)

    assert dispatch.dispatch_arms(features, arms) == (dispatch.ARM_SEQUENCE_PAIR,)
```

`tests/layout/hierarchy/test_strategy.py`:

```python
def test_the_arm_cache_is_keyed_on_the_budget_as_well_as_the_shape(monkeypatch) -> None:
    # Two rounds of the same build hand the same shape different budgets, and
    # the answer legitimately differs across the floor. A shape-only key would
    # serve round 2 with round 1's answer.
    seen: list[float | None] = []

    def spy(features, arms, *, budget_s=None):
        seen.append(budget_s)
        return arms

    monkeypatch.setattr(dispatch, "dispatch_arms", spy)
    layout = HierarchicalLayout(block_strategy="best", ...)  # the file's own construction
    cache: dict[tuple[ShapeKey, float], tuple[str, ...]] = {}
    entry = ...  # the file's own single-block `_Entry` fixture

    layout._arms_for(spec, entry, cache, block_budget=5.0)
    layout._arms_for(spec, entry, cache, block_budget=5.0)
    layout._arms_for(spec, entry, cache, block_budget=20.0)

    assert seen == [5.0, 20.0]
    assert len(cache) == 2
```

Fill the two `...` placeholders from the constructions the surrounding tests in `test_strategy.py` already use — read the file first; do not invent a `HierarchicalLayout` signature.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/hierarchy/test_dispatch.py tests/layout/hierarchy/test_strategy.py -k "below_the_exact_floor or at_or_above_the_floor or coatered_block_below or omitting_the_budget or keyed_on_the_budget" -x`
Expected: FAIL — `TypeError: dispatch_arms() got an unexpected keyword argument 'budget_s'`.

- [ ] **Step 3: Add the branch to `dispatch_arms`**

```python
def dispatch_arms(
    features: BlockFeatures, arms: tuple[str, ...], *, budget_s: float | None = None
) -> tuple[str, ...]:
```

Append to its docstring:

```
    A THIRD UNCOVERED REGION, AND IT IS ABOUT THE CLOCK RATHER THAN THE SHAPE.
    The cross-tab above is a ratio between two arms that both FINISHED.  A
    coater-free block funded below `SEQUENCE_PAIR_EXACT_FLOOR_S` has no such
    ratio, because the sequence-pair arm does not finish: it is cancelled
    inside exact preparation and refuses "deadline exhausted before finding an
    exact layout".  The v3 gate measured 31 of `mall/no-proliferator`'s 54
    blocks doing exactly that, against 6 unplaced when both arms were raced.
    So an underfunded coater-free block is evidence the cross-tab does not
    cover, and it gets the same answer the other two uncovered regions get.
    ``budget_s=None`` means "no budget was supplied", which keeps v3's answer
    for every caller that does not pass one.
```

The body, replacing lines 116-126:

```python
    if len(arms) < 2:
        return arms
    if features.items_above_one_belt >= UNCOVERED_ITEMS_ABOVE_ONE_BELT:
        return arms
    if features.strips >= UNCOVERED_STRIPS:
        return arms
    if features.coaters > 0 and features.strips <= ARM_SMALL_STRIPS:
        chosen = ARM_FREEFORM
    else:
        if features.coaters == 0 and budget_s is not None and budget_s < SEQUENCE_PAIR_EXACT_FLOOR_S:
            return arms
        chosen = ARM_SEQUENCE_PAIR
    return (chosen,) if chosen in arms else arms
```

- [ ] **Step 4: Pass the budget through `_arms_for` and re-key the cache**

`_arms_for` gains a keyword-only `block_budget: float`, its `cache` becomes `dict[tuple[ShapeKey, float], tuple[str, ...]]`, and the lookup becomes:

```python
        key = (shape_key(entry.units), block_budget)
        chosen = cache.get(key)
        if chosen is None:
            try:
                chosen = dispatch.dispatch_arms(
                    dispatch.block_features(sub_spec(spec, entry.units, 0)),
                    arms,
                    budget_s=block_budget,
                )
            except Exception:  # noqa: BLE001 - a crashed feature vector races both arms, not an abort
                chosen = arms
            cache[key] = chosen
```

Append to `_arms_for`'s docstring:

```
        THE CACHE KEY CARRIES THE BUDGET.  Two rounds of one build hand the
        same shape different per-block budgets (`clamp(remaining / rounds_left
        / waves, 5, 20)`), and the answer legitimately differs across
        `dispatch.SEQUENCE_PAIR_EXACT_FLOOR_S` -- so a shape-only key would
        serve a later, better-funded round with an earlier round's answer.
        `plan_strips` still runs at most once per (shape, budget), which is
        what the cache is for.
```

Update every call site: `strategy.py:572` (the declaration), `:613`, `:625`, `:940`. Lines 613 and 625 are inside `lay_out`'s round loop where `block_budget` is already computed — pass that same variable, not a recomputed one. `_solve_round`'s signature (`:908`) takes the cache with the new type and already has `block_budget`; it passes it at `:940`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/layout/hierarchy/ -x`
Expected: exit 0. Then `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src` — all 0.

- [ ] **Step 6: Re-measure both malls, twice each**

The whole point of the lever, and it is measured here rather than deferred to Task 9 so a regression is caught while the change is one commit old.

```bash
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "runnable_5s_mean=" sum/5}' > mall-no-proliferator-b60-r1-load.txt
uv run python probe.py mall-no-proliferator-b60-r1.json -- "<mall url>" \
    --strategy hierarchical --budget 60 --band portable \
    --candidate-policy no-proliferator -o mall-no-proliferator-b60.blueprint.txt
```

and the same for `all-products`; two rounds each; one build at a time. Write `arm-rule.md` with the `blocks`, `blocks_unattempted`, `arm_dispatch_freeform / sequence_pair / both`, and blocks-never-placed counts for both cells in both rounds, **against v3's**: `mall/all-products` 39 blocks / 44-6-13 dispatch / 9 unplaced; `mall/no-proliferator` 54 blocks / 0-73-19 dispatch / 31 unplaced. The number this task exists to move is 31.

- [ ] **Step 7: Commit**

```bash
git add src/flab2bp/layout/hierarchy/dispatch.py src/flab2bp/layout/hierarchy/strategy.py \
        tests/layout/hierarchy/ docs/superpowers/evidence/2026-09-07-hierarchical-v4/
git commit -m "feat(dispatch): race both arms for a coater-free block funded below the exact floor"
```

---

### Task 8: The packer defect on `mall/all-products`'s seven blocks

**Lever:** 3(b). v3 gate §2.2: `mall/all-products` refuses in both rounds with 9 blocks never placed, of which **7 carry `freeform.py:20015`'s own message** — "no packing of N strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing". The refusal names `block 20 (steel, titanium-alloy)` with 3 strips. One more carries the port-seating refusal (`freeform.py:19519`) and one a per-block deadline.

**This task is a diagnosis before it is a fix, and it is written that way on purpose.** The refusal is the placer convicting itself; what is not known is which of the packer's own invariants is wrong. So: reproduce, diagnose in writing, then fix or bound against a stated rule.

**Files:**
- Create: `docs/superpowers/evidence/2026-09-07-hierarchical-v4/packer-defect.md`, `block_probe.py`, `block-20-*.{json,log}` and their `-load.txt`
- Test: `tests/layout/test_freeform.py` (the reproduction), and whatever the fix touches
- Modify (fix-dependent): `src/flab2bp/layout/freeform.py`

**Interfaces:**
- Consumes: `floor_probe.py`'s partition-and-solve shape (Task 6 Step 1) — `block_probe.py` is the same script with the arm switched to freeform and the per-attempt records dumped.
- Produces: either a `freeform.py` fix with its own corpus guard, or a written bound with the reason a fix was not attempted.

- [ ] **Step 1: Reproduce one refusing block as a test**

Add to `tests/layout/test_freeform.py`, marked `@pytest.mark.slow`:

```python
@pytest.mark.slow
def test_the_mall_block_the_packer_convicts_itself_on_is_placed_or_names_a_reason() -> None:
    # v3 gate.md §2.2: 7 of `mall/all-products`'s 9 unplaced blocks came back
    # "no packing of N strips could be wired at any candidate height; every
    # pack the sweep produced left nets unrouted. That is a PACKER defect".
    # This is the smallest of them, at a budget far above the 9.7s the gate's
    # build could afford, so a refusal here is a defect and not a clock.
    spec = _mall_spec(CandidatePolicy.ALL_PRODUCTS)
    block = initial_partition(spec).blocks[20]

    placement = FreeformLayout(
        band_policy=BandPolicy.portable(), time_budget_s=60.0
    ).lay_out(sub_spec(spec, block, 20))

    assert placement.buildings
```

`_mall_spec` reads the mall URL from `docs/superpowers/evidence/2026-09-05-speedups-2/large-urls/urls.txt` and calls the same `pipeline` entry point `floor_probe.py` uses. **Verify block index 20 still names `(steel, titanium-alloy)`** before trusting it — `partition` is unchanged on this branch, but the index is a positional claim and the test must assert the recipes it expects:

```python
    assert sorted({unit.recipe_id for unit in block}) == ["steel", "titanium-alloy"]
```

If it does not, find the block whose recipes match and use that index, and say so in `packer-defect.md`.

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/layout/test_freeform.py::test_the_mall_block_the_packer_convicts_itself_on_is_placed_or_names_a_reason -x`
Expected: FAIL with `NoValidLayout: no packing of 3 strips could be wired at any candidate height`. **If it PASSES at 60 s**, the defect is budget-bound rather than structural: record that in `packer-defect.md`, change the test's budget to the per-block budget the gate cell actually gave it (from `large-mall-all-products-b60-r1.json`), and re-run. A block that is placed at 60 s and refused at 9.7 s is a FUNDING finding, and it goes to Task 9 §5 as one rather than being fixed here.

- [ ] **Step 3: Diagnose, in writing, before touching production code**

`_sweep`'s refusal already carries the material: `attempts` holds one record per routed-or-refused candidate height, with the unrouted nets and `stranded_ports` for each. Write `block_probe.py` to dump every attempt's record for this block — candidate height, packed strips, nets attempted, nets routed, per-net failure kind, stranded ports — as JSON, and answer these three questions in `packer-defect.md`:

1. **Is it the same net every height, or a different one each time?** The same net across every candidate height is a net-level defect (a source or sink the packer places where no path can reach); different nets is a density defect (the pack is simply too tight and the sweep never widens enough).
2. **What is the failure KIND?** `SEALED_POCKET` and `DYNAMIC_ACCESS` are geometry; `BUDGET` is clock and means the diagnosis above is wrong. Break the counts down by kind, per height.
3. **Does the sweep ever try a height the pack would fit at?** `over_band`/`skipped_heights` in the refusal text says whether candidate heights were skipped as over-band before they were ever routed. A pack refused because every viable height was band-skipped is a BAND defect, not a packer one, and it is a different fix.

- [ ] **Step 4: Fix or bound, against a stated rule**

**Fix** if the diagnosis names a single wrong invariant with a local repair — for example, the packer offering a net's source and sink on opposite sides of a strip the router cannot cross, where the seating rule already knows better. Write the failing unit test first, on the smallest reproduction the diagnosis supports, then the fix.

**Bound** if the diagnosis says the sweep is exploring the wrong space — in that case widening the search is a design change and this plan does not have the evidence to make it. A bound is: the refusal names the diagnosed cause instead of the generic "PACKER defect" sentence, so the next plan starts from the finding rather than re-deriving it. That is a message change in `freeform.py` and it still needs a test.

**Either way, say which one happened and why in `packer-defect.md`.** "Neither, it was too hard" is not an outcome this task may produce; a written bound is cheap and is the outcome when a fix is not warranted.

- [ ] **Step 5: If `freeform.py` changed, run its own corpus guard**

A `freeform.py` change is not inert to the default path — v3 gate §4.1 makes exactly this point about its own diff. Before Task 9's gate, run one paired `scripts/audit.py --budget 30 --json` round (base and branch, `pgrep -af '[s]cripts/audit\.py'` empty before each, `-load.txt` beside each), compare with `audit_compare.py`, and record the CLEAN counts and named differing cells in `packer-defect.md`. **Zero regressions is the bar**; if a cell goes CLEAN → not CLEAN, revert the fix and take the bound instead.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/layout/test_freeform.py -x` and `uv run pytest tests/layout/hierarchy/ -x`
Expected: exit 0. Then `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src` — all 0.

- [ ] **Step 7: Commit**

```bash
git add -A docs/superpowers/evidence/2026-09-07-hierarchical-v4/ \
        src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "fix(freeform): the mall packer defect the v3 gate named, diagnosed and <fixed|bounded>"
```

---

### Task 9: The v4 gate

**Files:**
- Create: `docs/superpowers/evidence/2026-09-07-hierarchical-v4/gate.md`, `run_large.sh`, `run_cell.py`, `run_guard.sh`, `judge.py` (copied byte-identical from `../2026-09-07-hierarchical-v3/`, so all three gates' corpus comparisons are computed by the same program), `large-*.{json,log,stdout.txt}` and their `-load.txt`, `baseline-round1.{jsonl,txt}`, `candidate-round1.{jsonl,txt}`, `compare-round1.txt`, `judge-round1.txt`
- Modify: `docs/speedup-idea-backlog.md`

**The eight cells, the same as v2's and v3's**, one candidate policy per run so each cell gets the whole budget, `--band portable`, `-o`, and **no `--workers`** so the strategy sees the `None` the CLI passes by default:

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

- [ ] **Step 1: Declare the rule, in `gate.md`, BEFORE running anything, and commit it**

Write §0 first and commit it alone, so the rule cannot be amended afterwards. Verbatim:

> **PASS** if all five hold: (a) `titanium-glass/all-products` at 60 s emits a blueprint whose `validate.certify` report has **zero errors**; (b) every OTHER cell that COMPOSES either emits a blueprint with zero `certify` errors, or its refusal NAMES the lever that would unlock it — Lever 1 if it refuses with `reservation_partial > 0` and unrouted cuts that are not `BUDGET`, Lever 2 if it refuses on `power.coverage`, Lever 3 if it refuses with blocks never placed; (c) both malls compose — every block placed, the build reaching `compose`; (d) `titanium-glass` builds at `--budget 15`, emitting a blueprint; (e) the default-unchanged corpus guard has zero regressions — no cell CLEAN on the merge base and not CLEAN on the branch, 0 INVALID, 0 CRASH.
> **FAIL** otherwise, naming the clause AND the lever that failed (1 the corridor matcher, 2 composition power, 3 the block solvers), and ranking the next three levers with the file:line and the number behind each, exactly as v3's §5 did.

Also record in §0, as v3's §0 did: the area clauses are **reported but NOT gating** — `area / best_known` for every cell that emits, with no threshold — against belt3 **12408**, zurl2 **40905**, titanium-glass **5727**; the mall has no best-known area. And the wall clause is reported, not gating: within budget plus `RACE_COMPLETION_GRACE_S = 6.0`.

- [ ] **Step 2: The eight cells, twice each, ONE BUILD AT A TIME, AT THE BRANCH'S FINAL HEAD**

**This is a v3 residual and it is a gating condition of this step** (v3 gate §8.1: `src` and `tests` changed at `0af741ed` AFTER every measurement, and that gate could only argue the diff was inert rather than re-measure). Before the first cell runs: every fix wave, every review response and every doc change must already be committed. Record `git rev-parse HEAD` in `gate.md` §0 and **re-check it after the last cell**; if `src` or `tests` changed in between, the affected cells are re-run rather than argued about. `git diff --stat <declared HEAD> HEAD -- src tests` must be empty when the gate is written.

`run_cell.py` calls `flab2bp.cli.main(argv)` with exactly this argv and **monkeypatches nothing** — every number comes off the CLI's own `  stats ` line (`cli.py:565`):

```
uv run python run_cell.py <stem>.json -- "<url>" --strategy hierarchical \
    --budget <60|15> --band portable --candidate-policy <policy> -o <stem>.blueprint.txt
```

A `-load.txt` beside each run, taken immediately before it (`vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print sum/5}'`), recorded rather than waited on. Record per cell: verdict, in-process wall AND shell wall, area, `area / best_known`, validator errors by class, and the whole stats line — `blocks`, `blocks_unattempted`, `recut_rounds`, `nogood_skips`, `player_fed`, `cut_lanes`, `arm_dispatch_*`, `compose_gap`, `port_demands`, `reservation_degraded`, **`reservation_partial`**, `reservation_missing`, **`power_infill_towers`**, **`power_uncovered_tiles`**, `unrouted_cuts`. **Both rounds' numbers go in the table**, r1 quoted with r2 in parentheses wherever they differ.

- [ ] **Step 3: Certify every emitted blueprint independently**

For each cell that writes a `.blueprint.txt`, run `certify_probe.py` (v3's, copied in) on the same argv and record `errors_by_check` in full, plus buildings, area, tower count and splitter count. **A written `-o` file is not the clause; a zero-error `certify` report is.** The CLI truncates to `report.errors[:3]`, so the probe is the only thing that can say "four findings, not three".

- [ ] **Step 4: The default-unchanged corpus guard, paired**

Everything committed, `git status --short` empty. Then, scripted as `run_guard.sh` so the procedure is part of the record:

```bash
export GIT_EDITOR=true
pgrep -af '[s]cripts/audit\.py'                  # must print NOTHING before EACH half
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print "runnable_5s_mean=" sum/5}' > <half>-round1-load.txt
rm -f <half>-round1.jsonl                        # `--json` APPENDS; a stale target doubles the file
uv run python scripts/audit.py --budget 30 --json <half>-round1.jsonl > <half>-round1.txt 2>&1
```

`--json` takes a PATH on this master (`scripts/audit.py` ~741, "append one JSON record per cell to this file"), so the JSONL is an argument and the redirect takes the human-readable report. The BASELINE half runs on `git checkout --detach $(git merge-base master hierarchical-v4)` writing to `/tmp/v4gate/` — the evidence directory does not exist at the merge base — then `git checkout hierarchical-v4` immediately, HEAD and cleanliness re-verified, then the CANDIDATE half, then the baseline half copied in. **No `git stash`, no second worktree.** `run_guard.sh` must **print the `pgrep -af` matching lines next to the count**, so every slot claim in §4 is auditable rather than asserted.

Then `uv run python scripts/audit_compare.py baseline-round1.jsonl candidate-round1.jsonl > compare-round1.txt` and `judge.py` for the readable summary. **Read the CLEAN COUNTS and the NAMED DIFFERING CELLS, never the banners:** `audit.py` prints `NOT CLEAN` on any refusal, and `audit_compare.py` prints `FAIL` on its own 30 s p95-wall clause, which the merge base also fails (v3 measured baseline p95 31.42 s). If any cell differs in status, re-run just that URL on BOTH trees before calling it a regression, and record both trees' values — v3's control found five of seven moved cells moving on both trees.

- [ ] **Step 5: Write the rest of `gate.md`**

Sections, in this order, matching v3's shape so the three gates are readable against each other:

* **§1 the verdict**, as a clause-by-clause table with `required` / `measured` / verdict columns.
* **§2 the eight cells**, with §2.1's stats table (including the three keys new in v4) and §2.2's verbatim refusals.
* **§2.3 the cell that got furthest**, in whatever direction that turns out to be.
* **§3 where the strategy dies**, in the order a build meets the sites, and per-task agreement or disagreement with each implementer's own measurement, citing each as theirs. Where this gate cannot confirm a task's payload in production, say so rather than softening it — v3's Task 4 bullet is the model.
* **§4 the corpus guard**, with the counts and, if any cell moved, the both-trees control.
* **§5 the next three levers from the measurement**, each with a `file:line` and the number behind it, ranked by the size of the number and by distance to a first blueprint.
* **§6 the residuals still open.** Carry forward whichever of these this plan did not close, and add any new one: the cross-build solved-block cache, the outcome-driven strip cap, and — if Task 8 took the bound rather than the fix — the packer defect with its diagnosis.
* **§7 the as-shipped constants**, superseding v3's §7, including `SEQUENCE_PAIR_EXACT_FLOOR_S`, the matcher's new partial-commit behaviour, and the composition power pass.
* **§8 files**, and **§8.1 whether `src`/`tests` changed after the measurement** — with `git diff --stat <declared HEAD> HEAD -- src tests` quoted. This gate's target is that it is EMPTY.

**Provenance discipline, carried from v3.** Any figure this gate quotes that no committed file carries must be listed in one table with its tree, where it is cited, and whether it can be re-measured. If there are none, say "none" rather than omitting the section.

- [ ] **Step 6: Update the backlog**

In `docs/speedup-idea-backlog.md`, move out the entries this plan closed and leave the deliberately-unplanned ones with one sentence each and no new plan:

* **A cross-build solved-block cache** — not planned here; related work is already planned as the "background compound block cache" (`42c9e0e`).
* **A strip cap that moves with outcomes** — not attached to `_ShapeNoGood`, which is consulted before a block solve and keyed on `(shape, arm)`, while the signal is the router's per-cut verdict; it needs the cross-build memory above.
* **The pre-placed bus corridor (design §4 E)** — killed by measurement twice; revisit only if a gate ever measures a rung rejected for a sealed-trunk reason.

- [ ] **Step 7: Commit**

```bash
git add -A docs/superpowers/evidence/2026-09-07-hierarchical-v4/ docs/speedup-idea-backlog.md
git commit -m "evidence: hierarchical v4 gate on the large URLs"
```

---

## Self-review

**1. Spec coverage.**

| requirement | task |
| --- | --- |
| design §1: coverage and bounded time first, area second | Task 9 §0 — coverage clauses gate, area clauses report |
| design §3.1: a feature vector computed once, before any placement | unchanged from v3; Task 7 keys its cache on `(shape, budget)` so it is still computed once per distinct question |
| design §3.2: a registry where a solver claims a class | Task 7's third `UNCOVERED_*` region — a class the evidence does not cover is claimed by nobody and raced |
| design §3.3: the cheapest solver first, escalate only while outside the band | Task 7; the widen-before-cut escalation is unchanged |
| design §4 E: reserved ground for the trunks | explicitly NOT planned; the Global Constraints section says why in one line |
| v3 gate §5 lever 1: the matcher gives up wholesale | Tasks 1, 2, 3 |
| v3 gate §5 lever 2: power the ground composition adds | Tasks 4, 5 |
| v3 gate §5 lever 3: the malls' block solvers and the one-arm rule | Tasks 6, 7, 8 |
| v3 gate §6 residual: a partial must not commit reporting `reservation_degraded = 0` | Task 2 Step 1's first test, and the `partial` counter that makes the pair readable |
| v3 gate §8.1 residual: measured one fix wave earlier than HEAD | Task 9 Step 2's HEAD declaration and post-check |
| brief: measure `missing` vs unrouted on belt3 and zurl2, before and after | Task 3 |
| brief: order titanium-glass@60 right after Lever 2 lands | Task 5 |
| brief: re-measure the red deadline test's ceiling and lower its budget | Task 6 Step 6 |
| brief: a freeform change gets its own corpus guard | Task 8 Step 5 |

**2. Placeholder scan.** Every code step carries its code and every test step its test. Four things are deliberately decided by a measurement rather than by this document, and each states the rule that will decide it rather than the answer: `SEQUENCE_PAIR_EXACT_FLOOR_S` (Task 6 Step 4 — "the smallest swept budget at which every one of the five blocks produced an exact layout", with a stated fallback if none does), the deadline test's new budget and ceiling (Task 6 Step 6 — "the smallest swept budget at which any of three runs SUCCEEDED", and the largest below it that refused 3 of 3), Task 8's fix-or-bound (Step 4, with both outcomes defined and "neither" excluded), and Task 5's three refusal shapes (each with what it means and what to do). Three code sites are marked to be read from the surrounding file before being written — `test_strategy.py`'s `HierarchicalLayout` construction and `_Entry` fixture (Task 7 Step 1), `test_freeform.py`'s canvas helpers (Task 4 Step 1), and `floor_probe.py`'s `pipeline`/`SequencePairLayout` entry points (Task 6 Step 1) — because inventing a constructor signature is worse than pointing at the real one; each names the exact symbol to look up.

**3. Type consistency.** `_CorridorMatch(assigned: dict[PortAccessDemand, PortAccessCorridor], converged: bool)` is returned by `_match_access_corridors` in Task 1 and read as `.assigned` / `.converged` in Task 1 Step 5 and Task 2 Step 4. `PortAccessReservation.converged: bool = True` is the last field, added after `evidence`, so every positional construction still works. `PackedCanvas.partial: int` and `ComposeResult.reservation_partial: int` are distinct names for the same ladder total, and `ComposeResult.reservation_partial` is what `strategy.py` reads into `_StrategyStats.reservation_partial: float` — the same spelling as `PlacementStats.reservation_partial: float`. `ComposeResult.power_infill` / `power_uncovered` (ints) map to `PlacementStats.power_infill_towers` / `power_uncovered_tiles` (floats); the two names differ deliberately and both spellings appear in Task 4 Steps 4 and 5. `plan_power_infill(canvas, *, cancelled) -> tuple[list[tuple[int, int]], tuple[tuple[int, int], ...]]` returns exactly what `_place_power(canvas, sites: Sequence[tuple[int, int]])` consumes. `dispatch_arms(features, arms, *, budget_s=None) -> tuple[str, ...]` and `_arms_for(spec, entry, cache, *, block_budget) -> tuple[str, ...]` return the same type `self._arms()` does, which `_solve_round`'s `slots_by_key` and `_recut`'s `arms` already consume. The arm cache's key changes from `ShapeKey` to `tuple[ShapeKey, float]` at all six sites Task 7 Step 4 lists. `Cell` is `(x, y, level)` throughout.

**4. Ordering.** Task 2 depends on Task 1's `converged`. Task 3 depends on both and changes no production code. Task 4 depends on Task 2 only for where its two new `ComposeResult` fields sit. Task 5 depends on Task 4. Task 7 depends on Task 6's constant. Task 8 is independent of Tasks 6-7 and could run in parallel, but it shares `floor_probe.py`'s partition-and-solve shape so it is ordered after. Task 9 is last and depends on all of them, and its Step 2 requires that nothing in `src` or `tests` moves once it starts.
