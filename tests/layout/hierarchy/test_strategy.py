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
from flab2bp.layout.hierarchy.partition import Unit
from flab2bp.layout.hierarchy.strategy import HierarchicalLayout, ShapeKey
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
            result: tuple[dict[str, object], Placement | None] = (
                {"strategy": arm, "verdict": "REFUSED: forced", "ok": False, "wall_s": 0.0},
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


def test_a_budget_too_small_to_fund_one_solve_round_refuses_saying_so(
    chain_spec: BuildSpec,
) -> None:
    with pytest.raises(NoValidLayout, match=r"is under the .*s a block solve is given at all"):
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
