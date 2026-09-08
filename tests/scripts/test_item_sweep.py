"""The sweep harness decides what is in scope and how big each block is.

Both decisions are load-bearing: a mis-classified item is one the sweep never
tries, and a mis-derived rate turns "we cannot build this" into "we asked for
something absurd".  Neither is visible in the sweep's own output, so they are
pinned here.
"""

from __future__ import annotations

from fractions import Fraction

from flab2bp.lab.data import load_vendored
from scripts import item_sweep


def test_scope_is_the_three_physical_categories() -> None:
    data = load_vendored()
    plans = item_sweep.plans(data)

    assert {p.category for p in plans} == set(item_sweep.ITEM_CATEGORIES)
    # Research rows and the proliferator "effects" entries are not items a
    # factory outputs, so they are never planned at all.
    ids = {p.item_id for p in plans}
    assert "proliferator-1-products" not in ids
    assert not any(p.category in ("technologies", "upgrades") for p in plans)


def test_ores_are_raw_and_named_not_silently_dropped() -> None:
    data = load_vendored()
    by_id = {p.item_id: p for p in item_sweep.plans(data)}

    for item_id, recipe_id in (
        ("iron-ore", "iron-vein"),
        ("water", "ocean"),
        ("crude-oil", "crude-oil-seep"),
        ("fire-ice", "ice-giant-gas-hydrate"),
    ):
        plan = by_id[item_id]
        assert plan.kind == "RAW"
        assert recipe_id in plan.reason


def test_items_nothing_produces_are_other() -> None:
    data = load_vendored()
    by_id = {p.item_id: p for p in item_sweep.plans(data)}

    for item_id in ("log", "plant-fuel", "ray-receiver-pro", "df-energy-shard"):
        assert by_id[item_id].kind == "OTHER"
        assert "no recipe" in by_id[item_id].reason


def test_build_items_carry_a_recipe_a_machine_and_a_url() -> None:
    data = load_vendored()
    by_id = {p.item_id: p for p in item_sweep.plans(data)}

    gear = by_id["gear"]
    assert gear.kind == "BUILD"
    assert gear.recipe_id == "gear"
    # A bare URL carries no machine rank, so `select_machine` falls through to
    # `recipe.producers[0]` -- an assembler, never a Dark Fog building.
    assert gear.machine_id == "assembling-machine-1"
    assert gear.url is not None
    assert f"o=gear*{gear.rate_per_min}" in gear.url


def test_no_build_item_resolves_to_a_dark_fog_machine() -> None:
    """The dataset's ``maxMachineRank`` leads with the Dark Fog buildings.

    Deriving the rate from one would size every block against a machine the
    build will never place, so the harness must not consult that rank.
    """
    data = load_vendored()
    machines = {p.machine_id for p in item_sweep.plans(data) if p.kind == "BUILD"}
    assert not any(m and m.startswith("df-") for m in machines)


def test_every_rate_is_one_to_six_machines_of_the_target_recipe() -> None:
    data = load_vendored()
    for plan in item_sweep.plans(data):
        if plan.kind != "BUILD":
            continue
        assert plan.target_machines is not None
        assert 1.0 <= plan.target_machines <= 6.0, plan


def test_chosen_rate_is_a_round_number_biased_small() -> None:
    # One machine makes 45/min: 1.5x is 67.5, and 60 is the nearest rung that
    # still buys at least one machine.
    assert item_sweep.choose_rate(Fraction(45)) == 60
    # 11.25/min -> aim 16.875, rungs in [11.25, 67.5]: 15 is nearest.
    assert item_sweep.choose_rate(Fraction(45, 4)) == 15
    # A rate above the top rung has no round answer; take the aim rather than
    # silently clamping to a value that would ask for a fraction of a machine.
    assert item_sweep.choose_rate(Fraction(2000)) == 3000


def test_outcome_classification_separates_the_four_failure_kinds() -> None:
    clean_cross = {"available": True, "ok": True, "buildings": 7}
    parsed = {"buildings": 7}

    assert item_sweep.classify_outcome(0, parsed, clean_cross) == "CLEAN"
    assert item_sweep.classify_outcome(1, parsed, clean_cross) == "INVALID"
    assert item_sweep.classify_outcome(2, parsed, clean_cross) == "CLI_ERROR"
    assert item_sweep.classify_outcome(3, parsed, clean_cross) == "REFUSED"
    assert item_sweep.classify_outcome(124, parsed, clean_cross) == "TIMEOUT"
    assert item_sweep.classify_outcome(139, parsed, clean_cross) == "CRASH"

    # A blueprint our own validator blessed and the viewer's decoder rejected is
    # an encoder bug, and it must not read as CLEAN.
    assert (
        item_sweep.classify_outcome(0, parsed, {"available": True, "ok": False, "buildings": 0})
        == "CROSS_INVALID"
    )
    assert (
        item_sweep.classify_outcome(0, parsed, {"available": True, "ok": True, "buildings": 6})
        == "CROSS_MISMATCH"
    )


def test_cpu_pressure_is_the_runnable_mean_not_the_load_average(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Load average on this box is I/O wait; only `vmstat`'s `r` column says
    whether a build was actually competing for CPU."""
    stdout = (
        "procs -----------memory---------- ---swap-- -----io----\n"
        " r  b   swpd   free   buff  cache   si   so    bi    bo\n"
        "12  0      0  1000      0      0    0    0     0     0\n"  # since boot: dropped
        " 4  1      0  1000      0      0    0    0     0     0\n"
        " 6  0      0  1000      0      0    0    0     0     0\n"
        " 5  0      0  1000      0      0    0    0     0     0\n"
        " 5  0      0  1000      0      0    0    0     0     0\n"
        "10  0      0  1000      0      0    0    0     0     0\n"
    )

    class _Proc:
        def __init__(self) -> None:
            self.stdout = stdout

    monkeypatch.setattr(item_sweep.subprocess, "run", lambda *a, **k: _Proc())
    assert item_sweep.cpu_pressure() == 6.0


def test_cpu_pressure_is_none_when_it_could_not_be_measured(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A missing measurement must read as missing, never as an idle box."""

    def _boom(*a: object, **k: object) -> object:
        raise FileNotFoundError("vmstat")

    monkeypatch.setattr(item_sweep.subprocess, "run", _boom)
    assert item_sweep.cpu_pressure() is None


def test_gate_pattern_matches_the_run_and_not_the_watchers() -> None:
    """Every agent waiting for this gate runs a shell whose command line
    contains the script name, so a bare filename pattern deadlocks the sweep on
    the other waiters -- and on itself."""
    import re

    gate = re.compile(item_sweep.GATE_PATTERN)

    assert gate.search("uv run python scripts/trace_overhead.py --purity --wall")
    assert gate.search("/repo/.venv/bin/python3 scripts/trace_overhead.py --purity")
    assert not gate.search('/bin/zsh -c until pgrep -f "scripts/trace_overhead.py"; do sleep 60')
    assert not gate.search("uv run python scripts/item_sweep.py --round 1")


def test_log_parser_reads_the_report_line_and_the_whole_error_histogram() -> None:
    log = (
        "freeform / plastic@30: 4 machines, 260 tiles, 11 buildings\n"
        "primary_band: 3\n"
        "  2 VALIDATION ERRORS: {'flow.sorter_capacity': 1, 'belt.overlap': 1}\n"
        "    flow.sorter_capacity: sorter at (3, 4) moves 1.5/s, needs 2.0/s\n"
        "    belt.overlap: two runs share (9, 2)\n"
        "  1 check(s) could not run: power.coverage\n"
    )
    parsed = item_sweep._parse_log(log)

    assert parsed["strategy"] == "freeform"
    assert parsed["spec_label"] == "plastic@30"
    assert parsed["machines"] == 4
    assert parsed["tiles"] == 260
    assert parsed["buildings"] == 11
    assert parsed["error_counts"] == {"flow.sorter_capacity": 1, "belt.overlap": 1}
    assert len(parsed["error_samples"]) == 2
    assert parsed["skipped_checks"] == ["power.coverage"]


def test_log_parser_keeps_the_refusal_message() -> None:
    log = (
        "flab2bp: no layout for plane-filter@6 in 30.0s\n"
        "  band 3 flow.entry buildings (1, 2): lane over belt capacity\n"
    )
    parsed = item_sweep._parse_log(log)

    assert parsed["nolayout"] == "no layout for plane-filter@6 in 30.0s"
    assert parsed["machines"] is None
