"""The URL from /home/dannyb/broke6.txt: two defects, one machine.

`freeform/output-products` refused because an Energy Exchanger's two
accumulator-full output lanes wanted two north-facing docks and it has one.
Every OTHER pair built and pasted with red belts -- 8, 6, 8, 6 and 10 of them --
because the approach column climbed the exchanger's collider and validate
skipped the building.

Not a wall-clock test: it asserts on verdicts, never on seconds.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from flab2bp import pipeline
from flab2bp.dsp import colliders
from flab2bp.layout import validate
from flab2bp.layout.base import NoValidLayout
from flab2bp.rates.candidates import DEFAULT_CANDIDATE_POLICIES, CandidatePolicy

pytestmark = pytest.mark.timeout(900)

URL = (
    "https://factoriolab.github.io/dsp/list?z=eJxNzD8PgjAUBPBv0-Gm1.pvestriJsRE5WOig"
    "wKhATB6NLPbhqldPtdLncdZzCkOpYSmgjQwY.EbvYGS6JYCBYxnLCmZG0mDzOlhFlN.oTtz0X4..uZ"
    "-JxYLjHcrxWL6qs37-FwQ40RsoMcIQWk9tLAbmFzbw-qbXt2Xnzmc.Virb9KujnI&v=11"
)


@pytest.mark.parametrize("strategy", ["freeform", "sequence-pair"])
@pytest.mark.parametrize("policy", DEFAULT_CANDIDATE_POLICIES, ids=lambda p: p.value)
def test_the_pair_builds_and_pastes_clean(
    strategy: pipeline.ExplicitStrategyName, policy: CandidatePolicy
) -> None:
    try:
        build = pipeline.build(
            URL, strategy=strategy, candidate_policies=(policy,), time_budget_s=15.0
        )
    except NoValidLayout as exc:
        pytest.fail(f"{strategy}/{policy.value} refused: {exc}")
    assert build.report.ok, (strategy, policy.value, build.report.errors)
    ctx = validate._context(build.placement, build.spec, None, 0, Fraction(4), True)
    previews = validate._paste_previews(ctx)
    # The raw primitive, asked with NO exemption -- the game asks it that way.
    assert colliders.stable_belt_collisions(previews) == [], (strategy, policy.value)
    # And by check id, so a future exemption regression is caught by name.
    for cid in ("game.belt_collide", "game.belt_crossing"):
        assert not build.report.by_check(cid), (strategy, policy.value, cid)


def test_the_spec_really_contains_two_energy_exchanger_modes() -> None:
    """Guard the reproduction: output-products is the candidate with both."""
    build = pipeline.build(
        URL,
        strategy="freeform",
        candidate_policies=(CandidatePolicy.OUTPUT_PRODUCTS,),
        time_budget_s=15.0,
    )
    recipes = {g.recipe_id for g in build.spec.groups}
    assert {"accumulator-full", "accumulator-discharge"} <= recipes
