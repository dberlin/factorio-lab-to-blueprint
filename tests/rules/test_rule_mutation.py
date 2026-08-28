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

Cost and scope
--------------

R4 replays only validator tests whose registered check reaches the rule, plus
independent numeric boundary controls for applicable centralized paste
predicates.  A pre-existing failure is compared with its own baseline outcome,
so it cannot make every mutation look validator-visible.  Rules outside emitted
paste (interactive ``MatchInserter``, turrets) and dead unread protocol bounds
carry an explicit ``mutation_exempt_because`` in the registry and are not
pretended into coverage.

Pytest cases are batched, while each perturbation context is still entered and
restored alone.  Applicable unconsulted predicates no longer replay the entire
validator file twice at the extreme ladder rungs; their one real boundary
witness runs instead.
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
    "catalog.BELT_RATE": ("validator", "belt-capacity witnesses cross the tier boundary"),
    "catalog.BELT_Z_PER_WORLD_UNIT": ("both", "world-to-blueprint z conversion"),
    "catalog.clearance": (
        "strategy",
        "packer reservation projection; validator checks colliders directly",
    ),
    "catalog.sorter_rate": ("both", "rate rule as a function of tier and span"),
    "catalog.footprint": ("both", "footprint drives both geometry and packing"),
    "colliders.GRID_ARC": ("both", "the tile arc; everything geometric moves"),
    "colliders.SORTER_END_EXTENSION": (
        "strategy",
        "strategy seating moves; no validator witness straddles this extension",
    ),
    "colliders.BELT_PROBE_RADIUS": ("validator", "belt crossing clearance boundary"),
    "colliders.BELT_PROBE_LIFT": ("validator", "belt crossing probe lift boundary"),
    "colliders.belt_crossing_height": ("validator", "belt crossing clearance verdict"),
    "rules.WORLD_UNITS_PER_LEVEL": ("both", "altitude in world units"),
    "rules.SLOT_REACH": ("both", "the plan's own first example"),
    "rules.SPLITTER_MAX_PORTS": ("both", "junction port cap"),
    "rules.CHEMICAL_OUTPUT_BUFFER_CRAFTS": (
        "validator",
        "flow.coproduct_buffer recomputes the exact game-backed capacity",
    ),
    "rules.BELT_INPUT_SLOTS": (
        "strategy",
        "emission allocates the range; checks inspect resulting occupied cells",
    ),
    "rules.BELT_PORT_FEED_FROM_SLOT": (
        "both",
        "emitted port feeder slot, checked against game-authored records",
    ),
    "rules.BELT_PORT_DRAW_TO_SLOT": (
        "both",
        "emitted port draw slot, checked against game-authored records",
    ),
    "rules.world_gap": ("both", "the shared world-distance helper, everywhere"),
    "rules.POWER_TOO_CLOSE_SQR": (
        "both",
        "EBuildCondition.PowerTooClose: checked by `game.power_too_close` and "
        "read by both packers through `power_node_keepout_offsets`",
    ),
    "rules.power_node_gate_sqr": ("both", "`num37`, the tier lookup the ladder opens with"),
    # --- validator only ------------------------------------------------------
    # `catalog.SORTER_SPANS_ALTITUDE` had a row here reading "a refusal, not a
    # search input".  Phase V found there was no rule to refuse on: the game
    # MEASURES a sorter's altitude span (`BuildTool_Inserter.cs:1311`) and
    # applies a MINIMUM to it (`:1347`).  Nothing caps it.  Rule and check both
    # deleted, so there is nothing left to mutate.
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
    # The two upper spacing tiers.  Neither strategy places a Wind Turbine or a
    # Geothermal Power Station, so no probe can move -- and both are checked, on
    # buildings the validator constructs, precisely so a tier we do not emit
    # cannot rot into a wrong number nobody notices.
    "rules.PASTE_POWER_NODE_IDS": (
        "validator",
        "the proto-id window the spacing loops scan; identity, not flags",
    ),
    "rules.WIND_TOO_CLOSE_SQR": ("validator", "wind-to-wind spacing; we place no turbine"),
    "rules.GEOTHERMAL_TOO_CLOSE_SQR": (
        "validator",
        "geothermal-to-geothermal spacing; we place no geothermal station",
    ),
    "rules.ADDON_NEIGHBOUR_RADIAL_GAP": ("validator", "addon corner rule, checked only"),
    "rules.addon_axis_aligned": ("validator", "addon axis predicate"),
    "rules.addon_ride_is_straight": ("validator", "the addon corner rule itself"),
    # --- strategy only -------------------------------------------------------
    "catalog.VERTICAL_STEP": ("strategy", "freeform's `_legal_link` consults it; no check does"),
    "rules.power_node_keepout_offsets": (
        "strategy",
        "the compiled projection both packers read; no CHECK reaches it, because "
        "`game.power_too_close` asks the predicate directly rather than the "
        "projection -- which is the right way round for a lower bound",
    ),
    "colliders.SORTER_HALF_LENGTH_MIN": ("strategy", "sorter seat box floor"),
    "rules.SPLITTER_INPUT_TO_SLOT": ("strategy", "written by `junction.make_splitter`"),
    "rules.SPLITTER_OUTPUT_FROM_SLOT": ("strategy", "written by `junction.make_splitter`"),
    # --- centralized paste boundary witnesses ------------------------------
    # Downstream readers are gaps; the independent controls still prove the
    # centralized predicate and threshold react at the cited boundary.
    "catalog.belt_slope_allowed": (
        "validator",
        "central TooSteep predicate has an independent 3/4 boundary witness",
    ),
    "catalog.blueprint_limit_for_technologies": (
        "validator",
        "central BlueprintNeedTech lookup has explicit researched-tier witnesses",
    ),
    "catalog.stack_pitch_z": (
        "validator",
        "prefab-derived splitter and lab pitches have independent controls",
    ),
    "catalog.vertical_construction_allowed": (
        "validator",
        "central splitter/lab stack predicate has locked and upgraded boundaries",
    ),
    "rules.PASTE_BELT_LINK_MAX_SQR": (
        "validator",
        "central TooFar threshold has an independent strict-boundary witness",
    ),
    "rules.belt_link_too_far": (
        "validator",
        "central TooFar predicate has an independent strict-boundary witness",
    ),
    "rules.COATER_RESHAPE_MAX": (
        "validator",
        "central TooSkew threshold has an independent component boundary",
    ),
    "rules.coater_reshape_allowed": (
        "validator",
        "central coater reshape predicate has an independent component boundary",
    ),
    # Declared "both" on the reasoning that `slots._drag_belt_end` reads it and
    # `validate` reaches that through the seat model.  MEASURED inert, and the
    # reasoning was the wrong kind of evidence: reachability is not exercise.
    # No test puts a sorter near the 0.5 gate, so the drag runs but the
    # threshold never decides anything.  A wrong value would ship.
    "rules.DRAG_MAX_ALIGNMENT": (
        "inert",
        "LEDGER: read by `slots._drag_belt_end` and reachable from validate, but "
        "no test puts a sorter near the 0.5 gate, so the threshold never decides "
        "anything and a wrong value would ship. A coverage hole, not a dead rule.",
    ),
    "colliders.PLANET_RADIUS": ("inert", "frozen into collider default arguments"),
    "colliders.PLANET_SEGMENT": ("inert", "frozen into collider default arguments"),
    "colliders.belt_keepout_offsets": ("inert", "frozen into `junction._KEEPOUT` at import"),
    "rules.ADDON_FROM_SLOT": (
        "strategy",
        "`slots.assign_sorter_slots` writes the game-authored addon field quartet",
    ),
    "rules.ADDON_TO_SLOT": (
        "strategy",
        "`slots.assign_sorter_slots` writes the game-authored addon field quartet",
    ),
    "rules.PASTE_LATERAL_EPS": (
        "inert",
        "LEDGER: applicable radial/lateral branch, but no emitted pose straddles 0.1",
    ),
    "rules.SKEW_PAIR_DEG": (
        "inert",
        "LEDGER: `game.inserter_skew` names it; no test straddles 30 degrees.",
    ),
    "rules.ADDON_AXIS_DEG": ("inert", "frozen into two `rules` default arguments"),
    "rules.power_node_condition": (
        "inert",
        "LEDGER, and the row is against R4 rather than against the rule.  This "
        "predicate returns `PowerSpacing | None`, and the ladder has no "
        "perturbation for that shape: `_scale` cannot move an enum or a None, "
        "so a callable returning one hands back its own answer on every rung "
        "and reads as no reaction.  What it does is nonetheless proven "
        "consulted -- the three thresholds it reads are `both`/`validator`, and "
        "`power_node_keepout_offsets`, which is nothing but a loop over this "
        "predicate, is `strategy`.  The gap is that a wrong BRANCH ORDER here "
        "would ship: reporting Wind where the game reports Power changes no "
        "assertion in the validator pool.  `tests/dsp/test_power_spacing.py` "
        "pins the branches, and it is not a pool R4 reads.",
    ),
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
def boundaries() -> dict[str, tuple[mutation.Witness, ...]]:
    return mutation.boundary_pool()


@pytest.fixture(scope="module")
def witness_baseline() -> dict[str, str]:
    return {}


@pytest.fixture(scope="module")
def baseline() -> dict[str, str]:
    return probes.snapshot()


@pytest.fixture(scope="module")
def consultation_by_rule() -> dict[str, provenance.Consultation]:
    return {row.entry.symbol: row for row in provenance.consultation()}


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
    "batch",
    mutation.rule_batches(),
    ids=lambda batch: f"{batch[0].symbol}..{batch[-1].symbol}",
)
def test_rules_react_the_way_they_are_declared_to(
    batch: tuple[Entry, ...],
    pool: list[mutation.Witness],
    boundaries: dict[str, tuple[mutation.Witness, ...]],
    witness_baseline: dict[str, str],
    baseline: dict[str, str],
    consultation_by_rule: dict[str, provenance.Consultation],
) -> None:
    """Perturb and restore each rule independently; report one pytest batch."""
    failures: list[str] = []
    for entry in batch:
        expected, why = VERDICTS[entry.symbol]
        consultation = consultation_by_rule[entry.symbol]
        got = mutation.verdict(
            entry,
            pool=pool,
            boundaries=boundaries,
            checks=consultation.checks,
            probes_enabled=bool(consultation.strategies),
            witness_baseline=witness_baseline,
            baseline=baseline,
            snapshot=probes.snapshot,
            changed=probes.changed,
        )
        if got.label != expected:
            failures.append(
                f"{entry.symbol} was declared '{expected}' ({why}) and measured "
                f"'{got.label}'.\n"
                f"  boundary/validator witness that moved: {got.validator}\n"
                f"  strategy probes that moved:          {list(got.probes)}\n"
                f"  perturbation:                        {got.rung}"
            )
    assert not failures, "\n\n".join(failures)


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


def test_perturbation_does_not_rewrite_frozen_projections() -> None:
    from flab2bp.dsp import rules
    from flab2bp.layout import junction

    alignment = rules.SLOT_ALIGN_COS
    keepout = junction._KEEPOUT
    with mutation.perturbed(registry.by_symbol("rules.SKEW_AXIS_DEG"), 12.0):
        assert alignment == rules.SLOT_ALIGN_COS
    with mutation.perturbed(registry.by_symbol("colliders.belt_keepout_offsets")):
        assert keepout == junction._KEEPOUT


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
        print(f"  explicitly exempt ....... {len(mutation.exempt_rule_entries()):>3}")
    assert total == len(VERDICTS)
