"""The hierarchical strategy end to end: partition, solve, compose, certify.

Every test here drives the real placers on ``chain_spec``.  A mocked block
solve would only prove the orchestration talks to itself; what has to hold is
that two independently solved blocks, wired by the lane contract and packed by
the composer, come back as ONE placement the validator accepts.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from fractions import Fraction

import pytest

from flab2bp.layout import validate
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.base import NoValidLayout, Placement, PlacementCompletion
from flab2bp.layout.hierarchy import compose as compose_mod
from flab2bp.layout.hierarchy import strategy
from flab2bp.layout.hierarchy.partition import Unit, initial_partition
from flab2bp.layout.hierarchy.strategy import HierarchicalLayout, ShapeKey, _Entry
from flab2bp.spec import BuildSpec, MachineGroup


def _layout() -> HierarchicalLayout:
    return HierarchicalLayout(
        belt_vertical_construction=True,
        band_policy=BandPolicy.parse("portable"),
        workers=8,
        strip_cap=2,
    )


#: `strategy._solve_block` captured at IMPORT time, before any test can
#: monkeypatch that name.  `_refuse_first_shape_then_real` is itself installed
#: as the `strategy._solve_block` a test monkeypatches, so it must not look the
#: real worker up by that name at call time -- it would recurse into itself.
_REAL_SOLVE_BLOCK = strategy._solve_block


def _refuse_first_shape_then_real(
    args: strategy._BlockJob,
) -> tuple[dict[str, object], Placement | None]:
    """Refuse the unsplit ingot block once; solve everything else for real.

    Same shape as `refuse_first_shape` inside
    `test_a_block_that_refuses_is_re_cut_before_the_whole_spec_refuses`, lifted
    to module scope so more than one test can force exactly one re-cut round
    without also wanting that test's own `calls` instrumentation.
    """
    sub = args[0]
    if sub.machine_count == 2 and len(sub.groups) == 1:  # the unsplit ingot block
        return ({"verdict": "REFUSED: forced", "ok": False, "strategy": args[1]}, None)
    return _REAL_SOLVE_BLOCK(args)


def test_pool_width_comes_from_the_affinity_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """No `workers` named -> the pool is sized from the box, capped at 32."""
    monkeypatch.setattr(strategy, "_available_cpu_count", lambda: 128)
    layout = HierarchicalLayout(
        belt_vertical_construction=True, band_policy=BandPolicy.parse("portable")
    )
    assert layout._pool_width() == 32
    # An explicit `workers` still wins over the affinity set.
    layout = HierarchicalLayout(
        belt_vertical_construction=True,
        band_policy=BandPolicy.parse("portable"),
        workers=16,
    )
    assert layout._pool_width() == 4


def test_a_fifteen_second_build_funds_one_round(
    chain_spec: BuildSpec, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The web UI's 15 s default must fund at least one real block solve.

    v1's reserve floor (10 s) left exactly `BLOCK_BUDGET_MIN_S` (5 s) of round
    at this budget, so any wall spent partitioning tipped the round under the
    floor and the build refused without ever calling `_solve_block`.

    ``workers=16`` here, not the file's usual 8: the chain splits into 2
    blocks and both arms race each (`best`), so a round is 4 jobs, and 8
    workers is only a pool 2 wide -- 2 waves at this budget's ~9 s remaining
    is 4.5 s a wave, UNDER the floor by itself, independent of `_pool_width`'s
    own fix.  16 workers is a pool 4 wide, one wave, 9 s a job -- what this
    test exists to exercise.
    """
    seen: list[float] = []
    real = strategy._solve_block

    def spy(args: strategy._BlockJob) -> tuple[dict[str, object], Placement | None]:
        seen.append(args[2])  # index 2 is the block's own budget_s
        return real(args)

    monkeypatch.setattr(strategy, "_solve_block", spy)
    layout = HierarchicalLayout(
        belt_vertical_construction=True,
        band_policy=BandPolicy.parse("portable"),
        workers=16,
        strip_cap=2,
    )
    layout._executor_factory = ThreadPoolExecutor
    layout.lay_out(chain_spec, time_budget_s=15.0)
    assert seen and min(seen) >= strategy.BLOCK_BUDGET_MIN_S


def test_one_pool_serves_every_round(
    chain_spec: BuildSpec, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One re-cut, still exactly one pool built for the whole `lay_out` call."""
    made: list[int] = []

    class Counting(ThreadPoolExecutor):
        def __init__(self, width: int) -> None:
            made.append(width)
            super().__init__(width)

    monkeypatch.setattr(strategy, "_solve_block", _refuse_first_shape_then_real)
    layout = _layout()
    layout._executor_factory = Counting
    layout.lay_out(chain_spec, time_budget_s=40.0)
    assert len(made) == 1


def test_hierarchical_lays_out_the_chain_as_two_blocks_and_certifies(
    chain_spec: BuildSpec,
) -> None:
    layout = _layout()
    placement = layout.lay_out(chain_spec, time_budget_s=30.0)
    assert placement.completion is PlacementCompletion.COMPACTED_AND_FINALIZED
    assert placement.stats["blocks"] == 2
    assert placement.stats["cut_lanes"] >= 1
    assert validate.certify(placement, chain_spec, expect_power=True).ok


def test_a_block_that_refuses_is_re_cut_before_the_whole_spec_refuses(
    chain_spec: BuildSpec,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    real = strategy._solve_block

    def refuse_first_shape(
        args: strategy._BlockJob,
    ) -> tuple[dict[str, object], Placement | None]:
        sub = args[0]
        calls.append(sub.machine_count)
        if sub.machine_count == 2 and len(sub.groups) == 1:  # the unsplit ingot block
            return ({"verdict": "REFUSED: forced", "ok": False, "strategy": args[1]}, None)
        return real(args)

    monkeypatch.setattr(strategy, "_solve_block", refuse_first_shape)
    layout = _layout()
    # The patched worker only exists in THIS process.
    layout._executor_factory = ThreadPoolExecutor
    placement = layout.lay_out(chain_spec, time_budget_s=40.0)
    assert placement.stats["resplits"] >= 1
    assert 1 in calls  # the ingot block was split into 1 + 1


def shape_key_from_spec(spec: BuildSpec) -> ShapeKey:
    """`strategy.shape_key`, but from the sub-spec a solved job actually carries.

    Not part of the production interface: `_solve_block`'s job carries a
    `BuildSpec`, not the `Unit` list `strategy.shape_key` takes, so a test
    spying on `_solve_block` derives the same key from the spec's own groups
    instead.  ONE `(recipe_id, count)` pair per group -- NOT aggregated by
    recipe id -- so the two agree on the same block: `sub_spec` builds
    exactly one `MachineGroup` per input `Unit` (`partition.sub_spec`'s
    `groups` tuple), so a spec's groups and the block's units are in
    one-to-one correspondence.
    """
    return tuple(sorted((group.recipe_id, group.count) for group in spec.groups))


def test_shape_key_does_not_conflate_different_group_shapes() -> None:
    """Two blocks `sub_spec` treats as different questions must hash different.

    `[Unit(iron, 1), Unit(iron, 2)]` builds a TWO-`MachineGroup` sub-spec;
    `[Unit(iron, 3)]` builds a ONE-`MachineGroup` sub-spec with the combined
    count.  Aggregating `shape_key` by recipe id would hash these equal and
    let the second silently receive a `Placement` solved for the first --
    the exact hazard `ShapeKey`'s own comment explains.  `partition.coalesce`
    happens to prevent `split_block` from ever producing the first shape
    today, but `shape_key` must not depend on that.
    """
    group = MachineGroup(
        recipe_id="iron-ingot",
        machine_item_id="arc-smelter",
        count=1,
        inputs_per_machine={"iron-ore": Fraction(1)},
        outputs_per_machine={"iron-ingot": Fraction(1)},
    )
    split = [Unit(1, group, 1), Unit(2, group, 2)]
    combined = [Unit(3, group, 3)]
    assert strategy.shape_key(split) != strategy.shape_key(combined)


def test_a_refused_shape_is_not_re_solved_at_a_budget_the_memo_already_covers(
    chain_spec: BuildSpec, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `(shape, arm)` refused at budget B is never asked again at `<= B`.

    Forcing the two-machine ingot block to refuse drives the same re-cut as
    `test_a_block_that_refuses_is_re_cut_before_the_whole_spec_refuses`:
    `split_block`'s "halve" attempt on a single-recipe block hands back two
    one-machine children of the IDENTICAL shape.  Both land in the same
    round, so this also exercises the same-round half of the no-good design,
    not only the across-round half its name suggests.

    Scoped to exactly what `_ShapeNoGood` promises -- NOT "no `(shape, arm)`
    is ever solved twice".  The memo is keyed on the HIGHEST budget refused
    at (`remembers`'s `seen >= budget_s`), because more wall time never makes
    a placer do worse, so a LATER round asking at a HIGHER budget is a
    legitimate re-ask, not a bug: `chain_spec`'s own budget sequence happens
    not to rise, but a partition change that shrinks `waves` between rounds
    could, and a same-shape re-solve there would be correct, not a defect
    this test should flag.
    """
    calls: list[tuple[ShapeKey, str, float, bool]] = []
    real = strategy._solve_block

    def spy(args: strategy._BlockJob) -> tuple[dict[str, object], Placement | None]:
        arm, budget = args[1], args[2]
        if len(args[0].groups) == 1 and args[0].machine_count == 2:
            # `wall_s` reports the FULL nominal budget, not a fixed 0.0: a
            # real timeout-driven refusal spends the wall it was actually
            # given, and only reporting that makes `_ShapeNoGood`'s "refused
            # at this budget or higher" memo mean what its own docstring
            # says -- a mock that always claims 0.0 wall spent understates
            # every refusal and can let a same-or-lower-budget re-ask through
            # that the real worker's bookkeeping would have skipped.
            result: tuple[dict[str, object], Placement | None] = (
                {"strategy": arm, "verdict": "REFUSED: forced", "ok": False, "wall_s": budget},
                None,
            )
        else:
            result = real(args)
        refused = str(result[0].get("verdict", "")).startswith("REFUSED:")
        calls.append((shape_key_from_spec(args[0]), arm, budget, refused))
        return result

    monkeypatch.setattr(strategy, "_solve_block", spy)
    layout = HierarchicalLayout(
        belt_vertical_construction=True,
        band_policy=BandPolicy.parse("portable"),
        workers=8,
        strip_cap=2,
    )
    layout._executor_factory = ThreadPoolExecutor
    placement = layout.lay_out(chain_spec, time_budget_s=40.0)

    worst_refused_at: dict[tuple[ShapeKey, str], float] = {}
    for key, arm, budget, refused in calls:
        seen = worst_refused_at.get((key, arm))
        assert seen is None or budget > seen, (
            f"{key} on {arm} was re-solved at budget {budget}, but the memo already saw it "
            f"refused at {seen}"
        )
        if refused:
            worst_refused_at[(key, arm)] = max(seen or 0.0, budget)
    # The halve split's two identical-shape children force at least one
    # same-round share (see the docstring above), so this is provable here,
    # not just non-negative -- Controller Ruling R12.
    assert placement.stats["nogood_skips"] > 0


class _InlinePool:
    """An `Executor.map` that runs the jobs right here, in this process.

    `_solve_round` only ever asks its pool for `map`, and a test that patches
    `strategy._solve_block` needs the patch to be in the process that runs it.
    `ThreadPoolExecutor` would do as much but would also hide the ORDER the
    round submits its jobs in, which is what the no-good assertions read.
    """

    def map(self, fn: object, jobs: object) -> list[object]:
        assert callable(fn)
        return [fn(job) for job in jobs]  # type: ignore[union-attr]

    def __enter__(self) -> _InlinePool:
        return self

    def __exit__(self, *args: object) -> None:
        pass


def test_identical_recut_children_do_not_create_unfunded_waves(
    chain_spec: BuildSpec, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two equal children need one five-second wave, not two."""

    class _Clock:
        now = time.monotonic()

        def monotonic(self) -> float:
            return self.now

    clock = _Clock()
    started = clock.now

    def refuse_parent(args: strategy._BlockJob) -> tuple[dict[str, object], Placement | None]:
        if shape_key_from_spec(args[0]) == (("iron-ingot", 2),):
            # Of the initial 24s block wall, leave 7.5s for the child round.
            clock.now = started + 16.5
            return (
                {"strategy": args[1], "verdict": "REFUSED: forced", "ok": False, "wall_s": 0.0},
                None,
            )
        return _REAL_SOLVE_BLOCK(args)

    monkeypatch.setattr(strategy, "time", clock)
    monkeypatch.setattr(strategy, "_solve_block", refuse_parent)
    layout = HierarchicalLayout(
        belt_vertical_construction=True,
        band_policy=BandPolicy.parse("portable"),
        workers=4,
        strip_cap=2,
        block_strategy="freeform",
    )
    layout._executor_factory = lambda _width: _InlinePool()  # type: ignore[assignment,return-value]
    placement = layout.lay_out(chain_spec, time_budget_s=40.0)
    assert placement.completion is PlacementCompletion.COMPACTED_AND_FINALIZED
    assert validate.certify(placement, chain_spec, expect_power=True).ok


def test_a_ten_second_no_good_is_retried_at_the_funded_fifteen_seconds(
    chain_spec: BuildSpec, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A shared shape refused at 10s becomes solvable at the next round's 15s."""
    from dataclasses import replace

    class _Clock:
        now = time.monotonic()

        def monotonic(self) -> float:
            return self.now

    clock = _Clock()
    started = clock.now
    partition = initial_partition(chain_spec, strip_cap=2)
    blocks = [
        child
        for block in partition.blocks
        for child in (
            strategy.split_block(list(block), attempt=0)
            if strategy.shape_key(list(block)) == (("iron-ingot", 2),)
            else [list(block)]
        )
    ]
    monkeypatch.setattr(
        strategy, "initial_partition", lambda *_args, **_kwargs: replace(partition, blocks=blocks)
    )

    def budget_sensitive(args: strategy._BlockJob) -> tuple[dict[str, object], Placement | None]:
        if shape_key_from_spec(args[0]) == (("iron-ingot", 1),) and args[2] <= 10.0:
            # R=60, L=3, two unique seed jobs -> 10s. After the consumer
            # places, R=30, L=2, one unique job -> 15s (raw slots give 7.5s).
            clock.now = started + 30.0
            return (
                {"strategy": args[1], "verdict": "REFUSED: forced", "ok": False, "wall_s": 10.0},
                None,
            )
        return _REAL_SOLVE_BLOCK(args)

    retried = False

    def retry_unchanged(
        entries: list[_Entry], still: list[int], **kwargs: object
    ) -> tuple[list[_Entry], bool]:
        # Allow one unchanged retry, isolating funding from split policy.
        nonlocal retried
        progress = not retried
        retried = True
        return entries, progress

    monkeypatch.setattr(strategy, "time", clock)
    monkeypatch.setattr(strategy, "_solve_block", budget_sensitive)
    monkeypatch.setattr(strategy, "_recut", retry_unchanged)
    layout = HierarchicalLayout(
        belt_vertical_construction=True,
        band_policy=BandPolicy.parse("portable"),
        workers=4,
        strip_cap=2,
        block_strategy="freeform",
    )
    layout._executor_factory = lambda _width: _InlinePool()  # type: ignore[assignment,return-value]
    placement = layout.lay_out(chain_spec, time_budget_s=100.0)
    assert placement.completion is PlacementCompletion.COMPACTED_AND_FINALIZED
    assert validate.certify(placement, chain_spec, expect_power=True).ok


def test_a_remembered_budget_breakpoint_funds_the_remaining_block(
    chain_spec: BuildSpec, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unseen job can use 10s when a second job is remembered at 10s."""
    entries = [_Entry(list(block)) for block in initial_partition(chain_spec, strip_cap=2).blocks]
    nogood = strategy._ShapeNoGood()
    nogood.record(strategy.shape_key(entries[1].units), "freeform", 10.0)

    def needs_ten_seconds(
        args: strategy._BlockJob,
    ) -> tuple[dict[str, object], Placement | None]:
        if args[2] < 10.0:
            return (
                {
                    "strategy": args[1],
                    "verdict": "REFUSED: insufficient wall",
                    "ok": False,
                    "wall_s": args[2],
                },
                None,
            )
        return _REAL_SOLVE_BLOCK(args)

    monkeypatch.setattr(strategy, "_solve_block", needs_ten_seconds)
    plan = strategy._plan_round(
        entries,
        [0, 1],
        [("freeform",), ("freeform",)],
        nogood=nogood,
        width=1,
        remaining=15.0,
        rounds_left=1,
    )
    _layout()._solve_round(
        chain_spec,
        entries,
        [0, 1],
        pool=_InlinePool(),  # type: ignore[arg-type]
        plan=plan,
        deadline=time.monotonic() + 60.0,
        nogood=nogood,
    )
    assert entries[0].placement is not None, entries[0].verdicts
    assert entries[1].placement is None


@pytest.mark.parametrize(
    ("spent", "retry_budget", "should_retry"),
    [(0.05, 20.0, True), (10.0, 10.0, False), (20.0, 20.0, False)],
)
def test_a_deadline_clipped_refusal_is_not_remembered_at_the_full_budget(
    chain_spec: BuildSpec,
    monkeypatch: pytest.MonkeyPatch,
    spent: float,
    retry_budget: float,
    should_retry: bool,
) -> None:
    """A job whose wall was clipped to nothing has not answered for its shape.

    `_solve_block` computes `min(parent_deadline, started + budget_s)` at job
    start, so a job in a later wave can be handed a clock with nearly nothing
    on it and refuse instantly with "deadline exhausted" -- its own docstring
    records a pool two wide doing exactly that to four of six jobs.
    `_ShapeNoGood` is only sound because a placer given MORE wall never does
    worse; remembering such a refusal at the round's NOMINAL budget claims the
    shape was tried with wall it never got, and then skips it for the rest of
    the build.  That is the one way this backend can refuse a build that would
    otherwise have placed.
    """
    spec = chain_spec
    entries = [_Entry(list(block)) for block in initial_partition(spec, strip_cap=2).blocks]
    offered: list[int] = []

    def clipped(args: strategy._BlockJob) -> tuple[dict[str, object], Placement | None]:
        offered.append(args[0].machine_count)
        return (
            {
                "strategy": args[1],
                "verdict": "REFUSED: deadline exhausted",
                "ok": False,
                "wall_s": spent,
            },
            None,
        )

    monkeypatch.setattr(strategy, "_solve_block", clipped)
    layout = _layout()
    nogood = strategy._ShapeNoGood()
    todo = list(range(len(entries)))
    # `dispatch.dispatch_arms` would send this shape (uncoated, few strips) to
    # `sequence-pair` alone above `SEQUENCE_PAIR_EXACT_FLOOR_S` -- but
    # `chain_spec` is coater-free and every budget here is below the floor
    # (Task 7), so both arms race; this test only cares about `sequence-pair`
    # specifically, which is on offer either way. `_solve_round` no longer
    # derives `arms_by_slot` itself (Task 7 fix round 1) -- the caller does,
    # once, the same way `lay_out`'s round loop does.
    arm_cache: dict[tuple[ShapeKey, float], tuple[str, ...]] = {}
    arms_by_slot = [
        layout._arms_for(spec, entries[index], arm_cache, block_budget=20.0) for index in todo
    ]

    def run_round(remaining: float) -> None:
        plan = strategy._plan_round(
            entries,
            todo,
            arms_by_slot,
            nogood=nogood,
            width=2,
            remaining=remaining,
            rounds_left=1,
        )
        layout._solve_round(
            spec,
            entries,
            todo,
            pool=_InlinePool(),  # type: ignore[arg-type]
            plan=plan,
            deadline=time.monotonic() + 600.0,
            nogood=nogood,
        )

    run_round(40.0)
    assert offered, "the first round must have offered every block to a placer"

    shape = strategy.shape_key(entries[0].units)
    assert nogood.remembers(shape, "sequence-pair", spent), (
        "the refusal is still evidence about the wall the job actually got"
    )
    assert nogood.remembers(shape, "sequence-pair", retry_budget) is not should_retry

    offered.clear()
    run_round(2.0 * retry_budget)
    assert bool(offered) is should_retry
    assert all(entry.placement is None and entry.verdicts for entry in entries)


def test_a_cut_whose_every_child_is_a_known_no_good_is_spent_without_a_solve() -> None:
    """`_next_cut` pays for a hopeless cut out of the attempt counter, not a round.

    A cut every one of whose children is already remembered refused, for every
    arm, at this budget or higher would cost a whole solve round to rediscover
    exactly the refusal an earlier round already paid for.  The skip is not
    free -- it spends one of `MAX_RESPLIT_ATTEMPTS`, and can drive a block to
    "out of re-cut attempts" without a placer being asked -- so what it must
    not do is fire on a cut some arm has never answered for.
    """
    ingot = MachineGroup(
        recipe_id="iron-ingot",
        machine_item_id="arc-smelter",
        count=1,
        inputs_per_machine={"iron-ore": Fraction(1)},
        outputs_per_machine={"iron-ingot": Fraction(1)},
    )
    arms = ("freeform", "sequence-pair")
    halves: ShapeKey = (("iron-ingot", 3),)

    every_arm = strategy._ShapeNoGood()
    for arm in arms:
        every_arm.record(halves, arm, 10.0)
    entry = _Entry([Unit(0, ingot, 6)])
    children = strategy._next_cut(entry, nogood=every_arm, arms=arms, budget_s=10.0)
    assert children is not None
    # Attempt 0 halves six machines into 3 + 3 -- both remembered -- so what
    # comes back is attempt 1's thirds, and BOTH attempts are spent.
    assert sorted(sum(u.count for u in child) for child in children) == [2, 2, 2]
    assert entry.attempts == 2

    one_arm = strategy._ShapeNoGood()
    one_arm.record(halves, "freeform", 10.0)
    unanswered = _Entry([Unit(0, ingot, 6)])
    children = strategy._next_cut(unanswered, nogood=one_arm, arms=arms, budget_s=10.0)
    assert children is not None
    assert sorted(sum(u.count for u in child) for child in children) == [3, 3]
    assert unanswered.attempts == 1

    at_a_lower_budget = strategy._ShapeNoGood()
    for arm in arms:
        at_a_lower_budget.record(halves, arm, 5.0)
    richer = _Entry([Unit(0, ingot, 6)])
    children = strategy._next_cut(richer, nogood=at_a_lower_budget, arms=arms, budget_s=10.0)
    assert children is not None
    assert sorted(sum(u.count for u in child) for child in children) == [3, 3]
    assert richer.attempts == 1


def _starved_chain_spec() -> BuildSpec:
    """A chain whose internal supply cannot cover both consumers.

    Three smelters make 3 ingot/s; two gear machines and two magnet machines
    want 4/s between them, and the missing 1/s is what the parent belts in
    (`external_inputs["iron-ingot"]`).  At `strip_cap=1` that partitions into
    one producer block and two single-recipe consumer blocks of 2/s each, so
    `allocate_cuts` serves the first WHOLE and cannot serve the second -- one
    player-fed `(block, item)` pair, which is the only shape of build that
    reaches `composed_spec`'s `player_fed` arithmetic at all.
    """
    groups = (
        MachineGroup(
            recipe_id="iron-ingot",
            machine_item_id="arc-smelter",
            count=3,
            inputs_per_machine={"iron-ore": Fraction(1)},
            outputs_per_machine={"iron-ingot": Fraction(1)},
        ),
        MachineGroup(
            recipe_id="gear",
            machine_item_id="assembling-machine-1",
            count=2,
            inputs_per_machine={"iron-ingot": Fraction(1)},
            outputs_per_machine={"gear": Fraction(1)},
        ),
        MachineGroup(
            recipe_id="magnet",
            machine_item_id="assembling-machine-1",
            count=2,
            inputs_per_machine={"iron-ingot": Fraction(1)},
            outputs_per_machine={"magnet": Fraction(1)},
        ),
    )
    return BuildSpec(
        groups=groups,
        external_inputs={"iron-ore": Fraction(3), "iron-ingot": Fraction(1)},
        outputs={"gear": Fraction(2), "magnet": Fraction(2)},
        surplus_outputs={},
        belt_item_id="conveyor-belt-1",
        belt_items_per_second=Fraction(6),
        belt_upgrades=(),
        sorter_item_ids=("sorter-1", "sorter-2", "sorter-3"),
        belt_stack=1,
        sorter_pick_stacks=(1, 1, 1),
        sorter_place_stacks=(1, 1, 1),
        piler_unlocked=False,
        label="starved-chain",
    )


def test_a_player_fed_block_is_declared_to_the_validator_and_certifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole player-fed path, end to end, with the declared rate pinned.

    `allocate_cuts` leaves one (block, item) entirely to the player, its entry
    heads are never offered to `assign_lanes`, `composed_spec` declares the
    deficit those unwired heads carry, and `validate.certify` has to accept the
    result -- which it can only do if `validate._entry_items` classifies that
    unwired head as an EXTERNAL ENTRY run, since `_lane_balance` injects
    `external_inputs` into no other kind of run and `flow.external_entry_points`
    demands a reachable entry for every declared external item.  Nothing else
    on this branch executes that line: every gate cell refused at or before the
    router.

    THE DECLARED RATE IS PINNED EXACTLY, not bounded.  It is the whole build's
    own make/take deficit (1/s, which is also what the parent belts in) PLUS
    the player-fed block's whole deficit (2/s).  The 3/s that makes is one more
    than the 2/s the unwired heads physically want, and that one is the
    whole-or-nothing rule's stranded remainder: the producer's third ingot per
    second has no consumer left to be wired to.  Over-declaring is the safe
    direction -- both `flow.conservation` clauses convict only on a SHORTFALL
    -- but it is arithmetic, and an inequality would not have noticed a factor
    in it.  Under-declaring is NOT safe, and that is what makes this an
    integration test rather than an arithmetic one: dropping the player-fed
    term convicts `flow.conservation` with "4 machine(s) consume 4 items/s of
    iron-ingot but only 3 items/s ... can reach them", because only 2/s of the
    production can reach a consumer at all.
    """
    spec = _starved_chain_spec()
    seen: dict[str, object] = {}
    real_allocate = strategy.allocate_cuts
    real_composed = strategy.composed_spec

    def spy_allocate(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        allocation = real_allocate(*args, **kwargs)  # type: ignore[arg-type]
        seen["player_fed"] = allocation.player_fed
        return allocation

    def spy_composed(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        built = real_composed(*args, **kwargs)  # type: ignore[arg-type]
        seen["built"] = built
        return built

    monkeypatch.setattr(strategy, "allocate_cuts", spy_allocate)
    monkeypatch.setattr(strategy, "composed_spec", spy_composed)
    layout = HierarchicalLayout(
        belt_vertical_construction=True,
        band_policy=BandPolicy.parse("portable"),
        workers=8,
        strip_cap=1,
        block_strategy="freeform",
    )
    layout._executor_factory = ThreadPoolExecutor
    placement = layout.lay_out(spec, time_budget_s=40.0)

    assert seen["player_fed"] == frozenset({(2, "iron-ingot")})
    built = seen["built"]
    assert isinstance(built, BuildSpec)
    assert built.external_inputs["iron-ingot"] == Fraction(3)
    report = validate.certify(placement, built, expect_power=True)
    assert report.ok, "; ".join(f"{f.check}: {f.message}" for f in report.errors[:5])


def test_the_memo_forgets_across_lay_out_calls(chain_spec: BuildSpec) -> None:
    """The no-good memo lives on the `lay_out` call, not the instance.

    In-process executor and a modest budget: this only needs one `lay_out`
    call to finish and asserts a single `hasattr`, so a real spawned pool and
    this project's default 30 s budget would only add wall a load flake
    could burn through the 120 s per-test timeout on a box that is never
    idle. 20 s is the smallest that still clears `BLOCK_BUDGET_MIN_S` after
    `settlement_reserve_s` for this two-block, two-arm round at `width=2`.
    """
    layout = HierarchicalLayout(
        belt_vertical_construction=True,
        band_policy=BandPolicy.parse("portable"),
        workers=8,
        strip_cap=2,
    )
    layout._executor_factory = ThreadPoolExecutor
    layout.lay_out(chain_spec, time_budget_s=20.0)
    assert not hasattr(layout, "_nogood")


def test_an_unwired_cut_is_a_refusal_not_a_handback(
    chain_spec: BuildSpec,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        strategy.compose_mod,
        "compose",
        lambda *a, **k: compose_mod.ComposeResult(
            Placement(buildings=()), [], 0, ("ingot: block 0 -> block 1: BUDGET",)
        ),
    )
    layout = _layout()
    with pytest.raises(NoValidLayout, match=r"ingot: block 0 -> block 1"):
        layout.lay_out(chain_spec, time_budget_s=30.0)


def test_no_block_outlives_the_parent_deadline(
    chain_spec: BuildSpec,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[float | None] = []
    real = strategy._solve_block

    def spy(args: strategy._BlockJob) -> tuple[dict[str, object], Placement | None]:
        seen.append(args[5])
        return real(args)

    monkeypatch.setattr(strategy, "_solve_block", spy)
    layout = _layout()
    layout._executor_factory = ThreadPoolExecutor
    started = time.monotonic()
    layout.lay_out(chain_spec, time_budget_s=30.0)
    assert seen and all(d is not None for d in seen)
    assert all(d is not None and d <= started + 30.0 + 1.0 for d in seen)


def test_a_job_is_capped_at_its_own_budget_when_it_starts_not_when_the_round_did(
    chain_spec: BuildSpec,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wall a job gets is computed IN the worker, at job start.

    The pool runs the round's jobs in waves.  A deadline the parent computed
    before the pool started is already spent by the time a second-wave job
    runs, and that job refuses instantly with "deadline exhausted" without
    searching at all -- so index 5 carries the parent's wall and the worker
    combines it with the budget itself.
    """
    seen: dict[str, float | None] = {}

    class _Stub:
        def lay_out(
            self,
            spec: BuildSpec,
            *,
            time_budget_s: float = 15.0,
            absolute_deadline: float | None = None,
        ) -> Placement:
            seen["deadline"] = absolute_deadline
            raise NoValidLayout("stub")

    monkeypatch.setattr(strategy, "_block_layout", lambda *a, **k: _Stub())
    started = time.monotonic()
    # A parent wall ten minutes out, and a three-second job budget.
    record, placement = strategy._solve_block(
        (chain_spec, "freeform", 3.0, True, 4, started + 600.0)
    )
    assert placement is None and record["ok"] is False
    deadline = seen["deadline"]
    assert deadline is not None
    assert started + 2.0 <= deadline <= started + 4.0


def test_a_budget_too_small_to_fund_a_round_still_attempts_the_seed_round(
    chain_spec: BuildSpec,
) -> None:
    """The seed round is never refused for funding, even under the reserve.

    At 1.0 s the settlement reserve alone (5.0 s) exceeds the whole budget --
    the OLD pre-attempt funding check would have refused here before a
    placer ever saw a block.  The new rule floors the seed round's share to
    `BLOCK_BUDGET_MIN_S` and runs it anyway; each block's own deadline
    (still clipped to the parent's) is what actually refuses it, and the
    build then runs out of the zero re-cut rounds this budget's wall allows.

    THE REAL SPAWNED POOL IS DELIBERATE HERE, and it is the one test in this
    file that must NOT set `_executor_factory = ThreadPoolExecutor` (final
    review raised the omission as an oversight; it is not).  What makes the
    refusal deterministic is that a spawned `ProcessPoolExecutor`'s start-up
    alone outlasts the 1.0 s parent deadline every block's own clock is
    clipped to, so every block refuses on time and the build lands on the
    out-of-re-cut-rounds refusal this asserts.  On threads there is no
    start-up to outlast it: `chain_spec` is four machines, the real placers
    finish inside the second, and this test PLACES instead of refusing --
    measured, not supposed.  Swapping the pool would not make the test cheaper,
    it would make it assert the opposite of its own name on a fast box and
    flip back on a loaded one.
    """
    with pytest.raises(NoValidLayout, match=r"out of re-cut round\(s\)"):
        _layout().lay_out(chain_spec, time_budget_s=1.0)


def test_a_dead_pool_is_a_refusal_not_a_crash(chain_spec: BuildSpec) -> None:
    """A parent-side pool failure must not escape as a raw exception.

    `Executor.map` re-raises a `BrokenProcessPool`, an unpicklable argument and
    an interpreter that failed to start, all on the parent side.  Losing the
    build to one is the mistake `_solve_block`'s own CRASH arm exists to avoid,
    one level up.
    """

    class _DeadPool:
        def __init__(self, max_workers: int) -> None:
            self.max_workers = max_workers

        def __enter__(self) -> _DeadPool:
            return self

        def __exit__(self, *exc_info: object) -> bool:
            return False

        def map(self, fn: object, jobs: object) -> object:
            raise BrokenProcessPool("a worker process died abruptly")

    # One arm, so every re-cut round the dead pool provokes is still funded and
    # the refusal that lands is the one carrying the pool's verdict rather than
    # an unfunded-round one.
    layout = HierarchicalLayout(
        belt_vertical_construction=True,
        band_policy=BandPolicy.parse("portable"),
        workers=8,
        strip_cap=2,
        block_strategy="freeform",
    )
    layout._executor_factory = _DeadPool  # type: ignore[assignment]
    with pytest.raises(NoValidLayout, match="BrokenProcessPool"):
        layout.lay_out(chain_spec, time_budget_s=30.0)


def test_a_pool_that_cannot_be_constructed_is_a_refusal_not_a_crash(chain_spec: BuildSpec) -> None:
    """A pool built once per build means a construction failure is possible
    exactly once, before any round -- and it must refuse, not escape as a raw
    `OSError`.

    `ProcessPoolExecutor.__init__` does not spawn a worker, but it does build
    the multiprocessing queues a worker will use (pipes plus a POSIX
    semaphore), which is real work that can fail with `OSError` on a shared,
    permanently loaded box: fd exhaustion (EMFILE) or a full `/dev/shm`
    (ENOSPC).  A different failure point from the dead-pool test above, which
    only exercises `map` raising on an already-constructed pool.
    """

    class _UnbuildablePool:
        def __init__(self, max_workers: int) -> None:
            raise OSError(24, "Too many open files")

    layout = HierarchicalLayout(
        belt_vertical_construction=True,
        band_policy=BandPolicy.parse("portable"),
        workers=8,
        strip_cap=2,
        block_strategy="freeform",
    )
    layout._executor_factory = _UnbuildablePool  # type: ignore[assignment]
    with pytest.raises(NoValidLayout, match="block pool unavailable: OSError"):
        layout.lay_out(chain_spec, time_budget_s=30.0)


def test_a_composer_crash_is_a_refusal_not_a_traceback(
    chain_spec: BuildSpec,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`lay_out` promises a `Placement` or a `NoValidLayout`, never a crash.

    The composer reads geometry assembled out of independently solved blocks --
    shapes no single block showed its own placer -- and `compose._port` asserts
    on one of them (`lane at N is not one contiguous row`, seen on belt3). That
    is the same kind of event as a placer crashing inside a block and is handled
    the same way.
    """

    def explode(*args: object, **kwargs: object) -> compose_mod.ComposeResult:
        raise AssertionError("lane at 9865 is not one contiguous row")

    monkeypatch.setattr(strategy.compose_mod, "compose", explode)
    with pytest.raises(NoValidLayout, match=r"composition crashed: AssertionError: lane at 9865"):
        _layout().lay_out(chain_spec, time_budget_s=30.0)


def test_a_deadline_spent_by_composition_refuses_before_finalization(
    chain_spec: BuildSpec,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Settlement is entered only with wall left to enter it with.

    `assign_sorter_slots` takes no `cancelled` and `certify` is atomic, so a
    composition that ran the clock out must refuse rather than start them.
    """
    real = compose_mod.compose

    class _SkewedClock:
        """`time`, plus a skew the composition applies on its way out.

        A composition that really ran the clock out would have to SLEEP the
        whole settlement reserve, which buys nothing the skew does not: what is
        under test is the guard's reading of the clock, not the sleeping.  The
        skew is applied only after the block rounds are finished, so nothing but
        the guard and its neighbours ever see it.
        """

        skew = 0.0

        def monotonic(self) -> float:
            return time.monotonic() + self.skew

    clock = _SkewedClock()

    def stall(*args: object, **kwargs: object) -> compose_mod.ComposeResult:
        result = real(*args, **kwargs)  # type: ignore[arg-type]
        clock.skew = 1_000_000.0
        return result

    monkeypatch.setattr(strategy, "time", clock)
    monkeypatch.setattr(strategy.compose_mod, "compose", stall)
    with pytest.raises(NoValidLayout, match="deadline exhausted before finalization"):
        _layout().lay_out(chain_spec, time_budget_s=30.0)


def test_a_refusal_carries_the_strategy_stats(
    chain_spec: BuildSpec, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A build that never places a block still reports what it did."""

    def always_refuse(args: strategy._BlockJob) -> tuple[dict[str, object], Placement | None]:
        return (
            {"strategy": args[1], "verdict": "REFUSED: forced", "ok": False, "wall_s": 0.0},
            None,
        )

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


def test_allowed_recut_rounds_is_zero_when_the_wall_holds_one_round():
    # 15 s budget: reserve 6.0, so the round loop has ~9 s -- one round.
    assert strategy.allowed_recut_rounds(8.7) == 0
    assert strategy.allowed_recut_rounds(12.0) == 1
    assert strategy.allowed_recut_rounds(35.1) == strategy.MAX_RECUT_ROUNDS


def test_the_seed_round_keeps_the_whole_wall_when_no_recut_is_affordable(chain_spec, monkeypatch):
    """The web-UI path: a 15 s build must not fund rounds it can never run.

    ``workers=16`` for the same reason as
    ``test_a_fifteen_second_build_funds_one_round``: the chain is 2 blocks x
    2 arms (``best``) = 4 jobs, and only a pool 4 wide (``workers=16``) makes
    that one wave -- at ``workers=8`` (pool 2 wide, 2 waves) the share is
    already under the floor by the wave split alone, before this rule's own
    ``rounds_left`` divisor ever enters into it, so the two are not
    distinguishable there.
    """
    seen: list[float] = []
    real = strategy._solve_block

    def spy(args):
        seen.append(args[2])
        return real(args)

    monkeypatch.setattr(strategy, "_solve_block", spy)
    layout = HierarchicalLayout(
        belt_vertical_construction=True,
        band_policy=BandPolicy.parse("portable"),
        workers=16,
        strip_cap=2,
    )
    layout._executor_factory = ThreadPoolExecutor
    layout.lay_out(chain_spec, time_budget_s=15.0)
    # reserve 6.0, ~9 s of round, one wave -> the whole wall (~9s), not a
    # third of it (~3s, which the floor would then clamp up to 5.0).
    assert seen and min(seen) > 1.5 * strategy.BLOCK_BUDGET_MIN_S


def test_a_build_stops_re_cutting_after_the_global_bound(chain_spec, monkeypatch):
    """`MAX_RESPLIT_ATTEMPTS` is per block; this bound is per build.

    `chain_spec` is 4 machines total and saturates its OWN splittability
    after exactly one real re-cut (2 blocks -> 4 single-machine, indivisible
    ones), one round short of `MAX_RECUT_ROUNDS = 2` -- so with the real
    `_recut`, `_next_cut`'s per-block exhaustion (`out of re-cut attempts`)
    would fire first and this test would never reach the GLOBAL bound it
    means to exercise.  `_recut` is faked to always report progress, unchanged,
    so the only thing left driving the loop is the round counter this task
    adds.
    """
    solves: list[str] = []

    def always_refuse(args):
        solves.append(args[1])
        return (
            {"strategy": args[1], "verdict": "REFUSED: forced", "ok": False, "wall_s": 0.0},
            None,
        )

    def always_progress(entries, still, *, nogood, arms, budget_s):
        return entries, True

    monkeypatch.setattr(strategy, "_solve_block", always_refuse)
    monkeypatch.setattr(strategy, "_recut", always_progress)
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
    # The bound has to be what STOPPED the loop, not an unfunded round dressed
    # up as one: the faked placer must actually have been handed jobs.
    assert solves, "no block was ever offered to a placer"


def test_a_round_that_cannot_afford_the_floor_names_the_wall_not_the_waves(chain_spec, monkeypatch):
    def always_refuse(args):
        return (
            {"strategy": args[1], "verdict": "REFUSED: forced", "ok": False, "wall_s": 0.0},
            None,
        )

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
    # And the refusal that DOES land names the round WALL, not the wave count.
    # At 9 s the reserve is the 5 s floor, leaving a ~4 s round wall, so
    # `allowed_recut_rounds` is 0 and the seed round -- floored to
    # `BLOCK_BUDGET_MIN_S` and run anyway -- is the whole build.  Only the
    # stable half of the message is pinned: `rounds_wall` is real elapsed wall
    # and prints to one decimal.
    reason = caught.value.reason
    assert "out of re-cut round(s) after 0 of 0" in reason
    assert "round wall allows" in reason
    assert "wave(s)" not in reason


def test_an_unregistered_arm_raises_rather_than_being_solved_by_sequence_pair() -> None:
    """`_block_layout` is THE REGISTRY POINT; an unknown arm must not fall through.

    Inert against the arms shipped today: every `_BlockJob` this branch builds
    takes its arm from `_arms_for`, which returns a subset of `_arms()`, which
    is exactly `("freeform", "sequence-pair")` -- so no reachable call can
    take the raise.  It exists for the SUB-SOLVER SEAM's next arm: a solver
    named in `BlockStrategyName` and given a dispatch rule but never
    registered here would otherwise be quietly solved by sequence-pair and
    have the verdict recorded against the arm that never ran.
    """
    assert isinstance(
        strategy._block_layout("freeform", vertical=True, workers=2), strategy.FreeformLayout
    )
    assert isinstance(
        strategy._block_layout("sequence-pair", vertical=True, workers=2),
        strategy.SequencePairLayout,
    )
    with pytest.raises(ValueError, match="block-library"):
        strategy._block_layout("block-library", vertical=True, workers=2)


def test_a_dispatched_block_is_offered_both_arms_below_the_exact_floor(chain_spec, monkeypatch):
    """`chain_spec`'s blocks are coater-free, and `lay_out` never hands a
    block a per-block budget at or above `BLOCK_BUDGET_MAX_S` (20.0s) --
    itself a whole second under `dispatch.SEQUENCE_PAIR_EXACT_FLOOR_S`
    (21.0s, Task 6).  So Task 7's abstain fires unconditionally here: BOTH
    arms are funded for every block, not just the one the v3 cross-tab
    would have preferred.  See `dispatch.dispatch_arms`'s own docstring for
    why that is the intended outcome, not a regression -- this test used to
    assert the opposite (`arm_dispatch_both == 0`) before Task 7.
    """
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
    assert set(arms) == {"freeform", "sequence-pair"}, (
        f"expected both arms, got {sorted(set(arms))}"
    )
    assert placement.stats["arm_dispatch_both"] == placement.stats["blocks"]
    assert placement.stats["arm_dispatch_freeform"] == 0.0
    assert placement.stats["arm_dispatch_sequence_pair"] == 0.0


def test_a_refused_block_is_offered_the_other_arm_before_it_is_cut(chain_spec, monkeypatch):
    """Widening the arms is cheaper than growing the block list.

    `chain_spec`'s blocks are coater-free, so left unpatched
    `dispatch.dispatch_arms` now abstains for them from round 1 (Task 7,
    see `test_a_dispatched_block_is_offered_both_arms_below_the_exact_floor`)
    -- both arms would already be offered together, leaving nothing left to
    widen TO once both refuse.  That is a different, already-covered
    concern; pinning `dispatch_arms` to v3's old single-arm answer here
    isolates the widen-before-cut escalation this test exists to check.
    """
    monkeypatch.setattr(
        strategy.dispatch,
        "dispatch_arms",
        lambda features, arms, **kwargs: (strategy.dispatch.ARM_SEQUENCE_PAIR,),
    )
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
            return (
                {"strategy": args[1], "verdict": "REFUSED: forced", "ok": False, "wall_s": 0.0},
                None,
            )
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


def test_a_crashing_feature_computation_falls_back_to_racing_both_arms(chain_spec, monkeypatch):
    """`_arms_for` runs unguarded in `lay_out`'s round loop (v3 Task 3 fix round 1).

    `dispatch.block_features` calls `plan_strips` -- real freeform packer
    internals -- from the orchestrator, not from a `_solve_block` worker, so
    there is no enclosing guard between it and `lay_out`'s
    `Placement`-or-`NoValidLayout` contract.  A crash there must degrade to
    racing the full arm set, the same escape-valve shape as the two
    `dispatch.UNCOVERED_*` branches, rather than escape as a raw traceback
    and take the whole build with it.
    """

    def boom(sub):
        raise ValueError("synthetic plan_strips defect")

    monkeypatch.setattr(strategy.dispatch, "block_features", boom)
    layout = _layout()
    entries = [_Entry(list(block)) for block in initial_partition(chain_spec, strip_cap=2).blocks]
    arms = layout._arms_for(chain_spec, entries[0], {}, block_budget=20.0)
    assert arms == ("freeform", "sequence-pair")

    # And the round loop itself must still complete a real build rather than
    # crash: the whole point is that `lay_out`'s contract survives.
    layout._executor_factory = ThreadPoolExecutor
    placement = layout.lay_out(chain_spec, time_budget_s=40.0)
    assert placement.completion is PlacementCompletion.COMPACTED_AND_FINALIZED


def test_the_arm_cache_is_keyed_on_the_budget_as_well_as_the_shape(
    monkeypatch: pytest.MonkeyPatch, chain_spec: BuildSpec
) -> None:
    # Two rounds of the same build hand the same shape different budgets, and
    # the answer legitimately differs across the floor. A shape-only key would
    # serve round 2 with round 1's answer.
    seen: list[float | None] = []

    def spy(features, arms, *, budget_s=None):
        seen.append(budget_s)
        return arms

    monkeypatch.setattr(strategy.dispatch, "dispatch_arms", spy)
    layout = _layout()
    cache: dict[tuple[ShapeKey, float], tuple[str, ...]] = {}
    ingot = MachineGroup(
        recipe_id="iron-ingot",
        machine_item_id="arc-smelter",
        count=1,
        inputs_per_machine={"iron-ore": Fraction(1)},
        outputs_per_machine={"iron-ingot": Fraction(1)},
    )
    entry = _Entry([Unit(0, ingot, 6)])

    layout._arms_for(chain_spec, entry, cache, block_budget=5.0)
    layout._arms_for(chain_spec, entry, cache, block_budget=5.0)
    layout._arms_for(chain_spec, entry, cache, block_budget=20.0)

    assert seen == [5.0, 20.0]
    assert len(cache) == 2
