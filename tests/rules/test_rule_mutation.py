"""R4 -- constant-mutation coverage.  The only mechanism that proves consultation.

R2 proves a rule is *named*.  A module can name a constant and ignore it, and
from outside that is indistinguishable from consulting it.  R4 perturbs the
rule and looks for a reaction: a real validator test from
``tests/layout/test_validate.py`` going red, and a named piece of SEARCH code
computing a different answer.

What each verdict means
-----------------------

``both``
    A validator test went red and a strategy probe moved.  This is the state
    the plan's done-when clause asks for.

``validator`` / ``strategy``
    One side reacted.  Sometimes that is correct -- ``SORTER_LENGTH`` is a
    paste-time rule with no search consequence -- and sometimes it is a hole.
    Every row says which, in ``VERDICTS``.

``inert``
    Nothing anywhere moved, across a perturbation ladder spanning an order of
    magnitude in both directions.  Each such row must be explained: either
    ``provenance.frozen_captures`` shows the rule is read once at import (a
    compiled projection, working as designed), or it is a LEDGER row and says
    so.  ``test_every_inert_rule_is_explained`` is what forbids a quiet one.

Cost
----

27 seconds, against a suite that already runs 261 and a hard 300-second
ceiling.  Three things buy that, and the third is the one that needed proving:

* the ladder short-circuits -- a rule that moves both sides on its first rung
  never pays for the other three;
* the validator pool is narrowed per rule by R2's own check-reachability, so a
  rule reached by ``geom.altitude_step`` is tried against that check's tests
  and not the other 190;
* a rule no check reaches gets the whole pool, but only on the two rungs that
  move it by an order of magnitude.

None of that may change a verdict, so it was measured rather than assumed:
every rule was also run exhaustively -- all 192 tests, all four rungs, 112s --
and the two runs agreed on all 54.
"""

from __future__ import annotations

import pytest

from flab2bp.dsp import provenance, registry
from flab2bp.dsp.registry import Entry

from . import mutation, probes

#: symbol -> (verdict, why this verdict is the right one)
#:
#: Measured, then read.  Nothing here was predicted.
VERDICTS: dict[str, tuple[str, str]] = {
    # --- both sides react.  The state the plan is aiming for. ---------------
    "catalog.SORTER_MAX_REACH": ("both", "sorter span, checked and searched"),
    "catalog.SORTER_RATE_AT_1": ("both", "rate rule, checked and searched"),
    "catalog.BELT_RATE": ("both", "lane capacity, checked and searched"),
    "catalog.BELT_Z_PER_WORLD_UNIT": ("both", "world-to-blueprint z conversion"),
    "catalog.clearance": ("both", "the compiled projection Phase 2 holds up as good"),
    "catalog.sorter_rate": ("both", "rate rule as a function of tier and span"),
    "catalog.footprint": ("both", "footprint drives both geometry and packing"),
    "colliders.GRID_ARC": ("both", "the tile arc; everything geometric moves"),
    "colliders.SORTER_END_EXTENSION": ("both", "sorter seat box"),
    "colliders.BELT_PROBE_RADIUS": ("both", "the plan's own second example"),
    "colliders.BELT_PROBE_LIFT": ("both", "companion to the probe radius"),
    "colliders.belt_crossing_height": ("both", "how high a belt flies over a machine"),
    "rules.WORLD_UNITS_PER_LEVEL": ("both", "altitude in world units"),
    "rules.SLOT_REACH": ("both", "the plan's own first example"),
    "rules.SPLITTER_MAX_PORTS": ("both", "junction port cap"),
    "rules.BELT_INPUT_SLOTS": ("both", "belt slot assignment, checked and searched"),
    "rules.world_gap": ("both", "the shared world-distance helper, everywhere"),
    # --- validator only ------------------------------------------------------
    "catalog.SORTER_SPANS_ALTITUDE": (
        "validator",
        "a refusal, not a search input: no strategy ever proposes a sloped sorter",
    ),
    "catalog.MAX_BELT_SLOPE": (
        "validator",
        "LEDGER: freeform's `_legal_link` is probed and does NOT move.  Step 2.2 "
        "wants the legal-move table rebuilt as a projection of this constant; R4 "
        "measures that it is not one today -- the router restates step legality.",
    ),
    "rules.OUTPUT_FROM_SLOT": ("validator", "emitted slot index; probes read the wired result"),
    "rules.INPUT_TO_SLOT": ("validator", "emitted slot index"),
    "rules.BELT_SLOT": ("validator", "the belt end's slot marker"),
    "rules.PASTE_SNAP": ("validator", "paste-time rule; nothing in the search consults it"),
    "rules.PASTE_RADIAL": ("validator", "paste-time rule"),
    "rules.SORTER_LENGTH": ("validator", "paste-time length bound, by endpoint kind"),
    "rules.SKEW_AXIS_DEG": (
        "validator",
        "the search reads SLOT_ALIGN_COS, which froze cos(this) at import -- see "
        "frozen_captures.  Plan step 1.5 splits this constant anyway.",
    ),
    "rules.ADDON_AREA_RADIUS": ("validator", "addon supply geometry, checked only"),
    "rules.ADDON_NEIGHBOUR_RADIAL_GAP": ("validator", "addon corner rule, checked only"),
    "rules.addon_axis_aligned": ("validator", "addon axis predicate"),
    "rules.addon_ride_is_straight": ("validator", "the addon corner rule itself"),
    # --- strategy only -------------------------------------------------------
    "catalog.VERTICAL_STEP": ("strategy", "freeform's `_legal_link` consults it; no check does"),
    "catalog.TESLA_COVER_RADIUS": (
        "strategy",
        "LEDGER: `power.coverage` takes a radius rather than consulting the rule, "
        "so no validator test moves when the game's coverage radius changes.",
    ),
    "catalog.belt_max_z": ("strategy", "the ceiling, consulted through the spec"),
    "colliders.SORTER_HALF_LENGTH_MIN": ("strategy", "sorter seat box floor"),
    "rules.SPLITTER_INPUT_TO_SLOT": ("strategy", "written by `junction.make_splitter`"),
    "rules.SPLITTER_OUTPUT_FROM_SLOT": ("strategy", "written by `junction.make_splitter`"),
    # --- inert ---------------------------------------------------------------
    "catalog.UNPOWERED_ITEM_IDS": ("inert", "LEDGER: `validate._POWERED` restates it"),
    "catalog.BELT_CROSSING_CLEARANCE": ("inert", "frozen into `spine._TRUNK_Z` at import"),
    "catalog.BEND_MIN_ANGLE_WHEN_SLOPED_RAD": ("inert", "LEDGER: the audit's headline row"),
    "catalog.SLOPE_DEADZONE": ("inert", "LEDGER: companion to the bend rule"),
    "catalog.DEFAULT_LAB_LEVEL": ("inert", "frozen into `DEFAULT_MAX_BELT_Z` at import"),
    "catalog.TESLA_LINK_DISTANCE": ("inert", "frozen into `spine.CONSTANTS` at import"),
    "colliders.PLANET_RADIUS": ("inert", "frozen into collider default arguments"),
    "colliders.PLANET_SEGMENT": ("inert", "frozen into collider default arguments"),
    "colliders.belt_keepout_offsets": ("inert", "frozen into `junction._KEEPOUT` at import"),
    "rules.ADDON_FROM_SLOT": (
        "inert",
        "LEDGER: named by slots.py, but no test and no probe moves when it does. "
        "Either the coater path is untested at this seam or the constant is dead.",
    ),
    "rules.ADDON_TO_SLOT": ("inert", "LEDGER: same seam as ADDON_FROM_SLOT"),
    "rules.CONN_SLOTS_PER_OBJECT": ("inert", "LEDGER: read by no code at all"),
    "rules.BELT_SLOT_AUTO_RANGE": ("inert", "LEDGER: plan step 3.3, enforced by nothing"),
    "rules.PASTE_LATERAL": (
        "inert",
        "LEDGER: `game.inserter_paste` names it and no test sits near the bound, "
        "so a wrong value would ship.  A test-coverage hole, not a rule hole.",
    ),
    "rules.PASTE_LATERAL_EPS": ("inert", "LEDGER: same bound as PASTE_LATERAL"),
    "rules.SKEW_PAIR_DEG": (
        "inert",
        "LEDGER: `game.inserter_skew` names it; no test straddles 30 degrees.",
    ),
    "rules.ADDON_AXIS_DEG": ("inert", "frozen into two `rules` default arguments"),
    "rules.ADDON_TURRET_AXIS_DEG": ("inert", "we never place a turret; correctly unread"),
}

#: An inert rule is only acceptable when something explains it.  These are the
#: rows R4 hands to the provenance ledger; the rest must be explained by
#: ``provenance.frozen_captures``.
LEDGER_INERT = frozenset(
    symbol for symbol, (label, why) in VERDICTS.items() if label == "inert" and "LEDGER" in why
)


@pytest.fixture(scope="module")
def pool() -> list[mutation.Witness]:
    return mutation.validator_pool()


@pytest.fixture(scope="module")
def baseline() -> dict[str, str]:
    return probes.snapshot()


@pytest.fixture(scope="module")
def checks_by_rule() -> dict[str, tuple[str, ...]]:
    return {row.entry.symbol: row.checks for row in provenance.consultation()}


def test_the_probe_suite_is_healthy(baseline: dict[str, str]) -> None:
    """Every strategy probe must ANSWER before anything is perturbed.

    A probe that raises answers the same way perturbed as unperturbed, so it
    silently stops witnessing and every rule it covered starts reading as
    inert.  That is the single way this module could turn into a reassuring
    number that means nothing, so it is asserted first and loudly.
    """
    dead = {name: answer for name, answer in baseline.items() if answer.startswith("<raised")}
    assert not dead, (
        "these strategy probes no longer run -- a signature they call has "
        f"changed, and R4 is blind wherever they were the only witness: {dead}"
    )


def test_the_validator_witness_pool_is_green(pool: list[mutation.Witness]) -> None:
    """192 real validator tests, all passing before any perturbation."""
    assert len(pool) > 150, "the validator witness pool has collapsed"
    assert mutation.first_red(pool) is None


def test_the_perturbation_reaches_a_by_value_import() -> None:
    """Mutation check on R4's own machinery.

    ``slots.py`` does ``from flab2bp.dsp.rules import SLOT_REACH``, so it holds
    its own copy.  If the perturbation did not follow the copy, R4 would report
    "the search ignores SLOT_REACH" -- a false accusation, and the exact
    reasoning the plan is trying to eliminate.  So: patching only the ``dsp``
    module must MISS the copy, and ``perturbed`` must catch it.
    """
    from flab2bp.dsp import rules
    from flab2bp.layout import slots

    entry = registry.by_symbol("rules.SLOT_REACH")
    assert "flab2bp.layout.slots" in mutation.rebinding_modules(entry)

    original = rules.SLOT_REACH
    rules.SLOT_REACH = 0.4  # the naive patch
    try:
        assert original == slots.SLOT_REACH, "slots.py no longer holds its own copy"
    finally:
        rules.SLOT_REACH = original

    with mutation.perturbed(entry, 0.4):
        assert slots.SLOT_REACH == 0.4
    assert original == slots.SLOT_REACH


def test_perturbation_is_restored_everywhere() -> None:
    entry = registry.by_symbol("colliders.BELT_PROBE_RADIUS")
    before = {m: True for m in mutation.rebinding_modules(entry)}
    with mutation.perturbed(entry):
        pass
    assert {m: True for m in mutation.rebinding_modules(entry)} == before


def test_every_declared_rule_has_a_verdict() -> None:
    declared = {e.symbol for e in mutation.rule_entries()}
    assert declared == set(VERDICTS), (
        "R4's verdict table has drifted from the registry.\n"
        f"  no verdict: {sorted(declared - set(VERDICTS))}\n"
        f"  no rule:    {sorted(set(VERDICTS) - declared)}"
    )


@pytest.mark.parametrize(
    "entry", mutation.rule_entries(), ids=lambda e: e.symbol if isinstance(e, Entry) else str(e)
)
def test_a_rule_reacts_the_way_it_is_declared_to(
    entry: Entry,
    pool: list[mutation.Witness],
    baseline: dict[str, str],
    checks_by_rule: dict[str, tuple[str, ...]],
) -> None:
    """Perturb the rule; assert the reaction matches what is written down."""
    expected, why = VERDICTS[entry.symbol]
    got = mutation.verdict(
        entry,
        pool=pool,
        checks=checks_by_rule.get(entry.symbol, ()),
        baseline=baseline,
        snapshot=probes.snapshot,
        changed=probes.changed,
    )
    assert got.label == expected, (
        f"{entry.symbol} was declared '{expected}' ({why}) and measured "
        f"'{got.label}'.\n"
        f"  validator test that went red: {got.validator}\n"
        f"  strategy probes that moved:   {list(got.probes)}\n"
        f"  perturbation:                 {got.rung}\n"
        "If this is an improvement, update VERDICTS.  If a probe stopped "
        "working, test_the_probe_suite_is_healthy will say so."
    )


def test_every_inert_rule_is_explained() -> None:
    """No rule may move nothing without saying why.

    Two acceptable reasons: it is compiled at import (Phase 2's pattern, which
    ``provenance.frozen_captures`` detects), or it is a ledger row.  Anything
    else is a rule the codebase believes it enforces and does not.
    """
    frozen = provenance.frozen_captures()
    unexplained = [
        symbol
        for symbol, (label, _why) in VERDICTS.items()
        if label == "inert"
        and symbol not in LEDGER_INERT
        and symbol not in frozen
        and registry.by_symbol(symbol).unconsulted_because is None
    ]
    assert not unexplained, (
        "these rules move nothing, and nothing accounts for it -- neither an "
        f"import-time capture nor a declared ledger row: {unexplained}"
    )


def test_a_frozen_rule_is_not_mistaken_for_an_ignored_one() -> None:
    """The distinction R4 would otherwise get wrong, asserted on known cases.

    ``ADDON_AXIS_DEG`` sits in two default arguments and ``SKEW_AXIS_DEG`` is
    folded into ``SLOT_ALIGN_COS``.  Both are plainly consulted and neither can
    react to a perturbation.  Reporting them as ignored would be a confident
    wrong answer, so the mechanism has to name the freezer.
    """
    frozen = provenance.frozen_captures()
    assert "flab2bp.dsp.rules.addon_axis_aligned.<defaults>" in frozen["rules.ADDON_AXIS_DEG"]
    assert "flab2bp.dsp.rules.SLOT_ALIGN_COS" in frozen["rules.SKEW_AXIS_DEG"]
    assert "flab2bp.layout.junction._KEEPOUT" in frozen["colliders.belt_keepout_offsets"]


def test_the_mutation_coverage_number(capsys: pytest.CaptureFixture[str]) -> None:
    """R4's summary, printed alongside R2's."""
    counts = {label: 0 for label in ("both", "validator", "strategy", "inert")}
    for label, _why in VERDICTS.values():
        counts[label] += 1
    total = sum(counts.values())
    with capsys.disabled():
        print()
        print("--- R4: what a perturbation actually moves ---")
        for label in ("both", "validator", "strategy", "inert"):
            pct = 100.0 * counts[label] / total
            print(f"  {label:.<26} {counts[label]:>3}  ({pct:5.1f}%)")
        print(f"  of which LEDGER rows ..... {len(LEDGER_INERT):>3}")
    assert total == len(VERDICTS)
