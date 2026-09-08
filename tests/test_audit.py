"""Behavioral checks for the corpus audit entry point."""

from scripts import audit


def test_both_selects_all_implemented_strategies() -> None:
    assert audit.strategy_names("both") == ("freeform", "sequence-pair")


def test_machine_rank_arm_reaches_every_policy_and_placer_job() -> None:
    from flab2bp.bench.corpus import Tier

    jobs = audit.build_jobs(
        ["freeform", "sequence-pair"],
        set(Tier),
        [30],
        workers=1,
        only={"iron-ingot"},
        machine_rank="up-to",
    )
    assert len(jobs) == 6
    assert {job.machine_rank for job in jobs} == {"up-to"}
    assert audit.build_parser().parse_args([]).machine_rank == "exact"
