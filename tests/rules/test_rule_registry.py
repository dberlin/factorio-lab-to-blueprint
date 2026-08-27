"""R1 and R2 of ``docs/RULE_CONSOLIDATION_PLAN.md``, as tests that print a number.

R1 -- no game constant outside ``dsp/``.
R2 -- every rule constant in ``dsp/`` is named by at least one check.

The plan's done-when clause is *"'100%' is a number a test prints, not a claim
in a document."*  ``test_the_consolidation_number`` is that test.  Run it with
``-s`` (or ``uv run python -m scripts.rule_report``) to read the table.

Every mechanism here has a companion test that plants a defect and confirms the
mechanism catches it.  A registry test that cannot fail prints a reassuring
number that means nothing, which is this project's most expensive recurring
failure -- so each of the three (``_would_catch_``) tests below exists to show
that the corresponding check has teeth.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from flab2bp.dsp import provenance, registry
from flab2bp.dsp.provenance import Graph
from flab2bp.dsp.registry import Kind

#: Ratchet, not a target.  These are the numbers at the time the mechanism was
#: built; the assertions below are ``>=`` so the consolidation can only improve.
#: Lowering one of these is a deliberate act that shows up in review.
BASELINE_CONSULTED_BY_A_CHECK = 35
BASELINE_CONSULTED_BY_A_STRATEGY = 37
BASELINE_CONSULTED_BY_BOTH = 24

#: Rules known to be read by nothing at all.  Every one carries its reason in
#: ``registry.py``.  This is a LEDGER, not an excuse: the test asserts the set
#: matches exactly, so a rule that gains a reader must be struck off here and a
#: rule that loses its last reader fails the suite.
EXPECTED_UNCONSULTED = {
    # Centralized values/predicates not yet consumed by emitted paste.
    "catalog.DEFAULT_STORAGE_LEVEL",
    "catalog.DEFAULT_LAB_LEVEL",
    "catalog.belt_max_z",
    "planet.SORTER_ALTITUDE_UNIT",
    "planet.SORTER_COMBINED_MIN",
    "planet.SORTER_SEGMENTS_MAX",
    # Paste-applicable rules centralized here but not yet migrated into
    # strategy/validation.  The report prints each registry reason.
    "catalog.blueprint_limit_for_technologies",
    "catalog.stack_pitch_z",
    "catalog.vertical_construction_allowed",
    "planet.SORTER_PARAM_BIAS",
    "planet.sorter_parameter",
    "rules.PASTE_BELT_LINK_MAX_SQR",
    "rules.belt_link_too_far",
    "rules.COATER_RESHAPE_MAX",
    "rules.coater_reshape_allowed",
    # MatchInserter is unreachable for blueprint-carried sorter peers.
    "rules.MATCH_SNAP_MAX_SQR",
    "rules.MATCH_ALIGN_COS",
    # These model non-refusing/silent protocol behavior or an unemitted turret.
    "rules.BELT_SLOT_AUTO_RANGE",
    "rules.ADDON_TURRET_AXIS_DEG",
}


@pytest.fixture(scope="module")
def graph() -> Graph:
    return provenance.build_graph()


# --- the registry itself ---------------------------------------------------


def _dsp_constants() -> dict[str, int]:
    """Every module-level ``UPPER_CASE`` name ``dsp`` binds, by AST.

    By AST rather than by ``dir()`` because a re-export would otherwise look
    like a declaration, and because a constant must be classified in the module
    that *writes* it.
    """
    root = Path(provenance.__file__).parent
    out: dict[str, int] = {}
    for path in sorted(root.glob("*.py")):
        module = path.stem
        if module in {"registry", "provenance", "__init__"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for stmt in tree.body:
            names: list[str] = []
            if isinstance(stmt, ast.Assign):
                names = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                names = [stmt.target.id]
            for name in names:
                if name.isupper() and not name.startswith("_"):
                    out[f"{module}.{name}"] = stmt.lineno
    return out


def test_every_dsp_constant_is_classified() -> None:
    """A new constant in ``dsp/`` must say what kind of thing it is.

    This is the gate that keeps the registry from decaying into a snapshot.
    """
    declared = set(registry.declared_symbols())
    found = set(_dsp_constants()) - registry.EXEMPT
    missing = sorted(found - declared)
    assert not missing, (
        "these dsp constants are not classified in flab2bp.dsp.registry -- "
        "add an Entry saying RULE / KNOB / DATA / DERIVED, and for a RULE that "
        f"varies, what it depends on: {missing}"
    )


def test_no_declaration_names_a_symbol_that_is_gone() -> None:
    for entry in registry.ENTRIES:
        registry.resolve(entry)  # raises if the declaration has rotted


def test_derived_entries_name_the_thing_they_project() -> None:
    symbols = set(registry.declared_symbols())
    for entry in registry.ENTRIES:
        if entry.kind is not Kind.DERIVED:
            continue
        assert entry.projection_of is not None, f"{entry.symbol} is DERIVED from nothing"
        assert entry.projection_of in symbols, (
            f"{entry.symbol} projects {entry.projection_of}, which is not declared"
        )


def test_mutation_exemptions_are_explicit_rule_scope() -> None:
    exempt = [e for e in registry.ENTRIES if e.mutation_exempt_because]
    assert exempt
    assert all(e.kind is Kind.RULE for e in exempt)
    for entry in exempt:
        reason = entry.mutation_exempt_because
        assert reason is not None and reason.strip()


def test_a_rule_that_varies_says_what_resolves_the_variation() -> None:
    """The plan's tech clause, mechanised.

    A rule declared to depend on tech level, tier or unlock state must either BE
    a lookup or name the ``dsp`` callable that resolves it.  A scalar with a
    declared dependency and nothing resolving it is a flattened rule: right by
    coincidence at one tech level, silently wrong at every other.
    """
    flat = provenance.flattened()
    assert not flat, (
        "flattened tech-indexed rules -- each is right by coincidence at one "
        f"tech level: {[e.symbol for e in flat]}"
    )


def test_resolvers_named_by_the_registry_exist() -> None:
    for entry in registry.ENTRIES:
        for name in filter(None, (entry.resolved_by, entry.projection_of)):
            module_name, attr = name.split(".", 1)
            module = __import__(f"flab2bp.dsp.{module_name}", fromlist=[attr])
            assert hasattr(module, attr), f"{entry.symbol} names {name}, which does not exist"


# --- R1 --------------------------------------------------------------------


def test_no_game_constant_lives_outside_dsp() -> None:
    """R1.  A rule constant's VALUE may not be typed as a literal in the search."""
    unexplained = provenance.unexplained_literals()
    stale = provenance.stale_lint_exceptions()
    hint = ""
    if stale and unexplained:
        hint = (
            "\n\nNOTE: these declared coincidences no longer match any site, so a "
            "rename may have moved one of them rather than a new constant "
            f"appearing: {[(e.module, e.where, e.value) for e in stale]}"
        )
    assert not unexplained, "\n".join(str(v) for v in unexplained) + hint


def test_the_lint_would_catch_a_planted_constant() -> None:
    """Mutation check on R1 itself: plant ``SLOT_REACH``'s value and see it caught."""
    planted = "def _seat(dx: float) -> bool:\n    return dx < 0.8\n"
    hits = provenance.scan_source("flab2bp.layout.planted", planted)
    assert [h.matches for h in hits], "R1 missed a bare 0.8 in a layout module"
    assert hits[0].where == "_seat"
    assert "rules.SLOT_REACH" in hits[0].matches


def test_the_lint_would_catch_a_fraction_spelling_of_one() -> None:
    """``Fraction(3, 4)`` is ``MAX_BELT_SLOPE`` written out, and must not hide."""
    planted = "def _step() -> object:\n    return Fraction(3, 4)\n"
    hits = provenance.scan_source("flab2bp.layout.planted", planted)
    assert any("catalog.MAX_BELT_SLOPE" in h.matches for h in hits)


def test_the_lint_ignores_a_quality_knob() -> None:
    """Search-quality constants are not game-rule lint targets."""
    planted = "LEVELS = 3\nUNIFORM_ROW_PITCH = 7\n_PRESSURE = 0.5\n"
    assert provenance.scan_source("flab2bp.layout.planted", planted) == ()


# --- R2 --------------------------------------------------------------------


def test_every_declared_rule_is_consulted_or_declared_unconsulted(graph: Graph) -> None:
    """R2 clause (c).  A rule with no readers is an unported rule in disguise."""
    rows = provenance.consultation(graph)
    silent = {r.entry.symbol for r in rows if not r.consulted}
    declared_silent = {r.entry.symbol for r in rows if r.entry.unconsulted_because}

    assert silent == EXPECTED_UNCONSULTED, (
        "the set of rules nothing reads has changed.\n"
        f"  now unread: {sorted(silent - EXPECTED_UNCONSULTED)}\n"
        f"  now read:   {sorted(EXPECTED_UNCONSULTED - silent)}"
    )
    assert silent == declared_silent, (
        "a rule is unread without saying why in registry.py, or says why and is "
        f"in fact read: {sorted(silent ^ declared_silent)}"
    )


def test_the_consolidation_number(graph: Graph, capsys: pytest.CaptureFixture[str]) -> None:
    """The number the plan asks for, printed, with a ratchet under it."""
    rows = provenance.consultation(graph)
    counts = provenance.summary(rows)

    with capsys.disabled():
        print()
        print("--- R2: declared game rules in flab2bp/dsp, and who consults them ---")
        print(f"  declared rules ............ {counts['declared']}")
        for key, label in (
            ("by_a_check", "named by a validator check"),
            ("by_a_strategy", "named by a search strategy"),
            ("by_both", "named by BOTH"),
            ("by_nothing", "named by NOTHING"),
        ):
            pct = 100.0 * counts[key] / counts["declared"]
            print(f"  {label:.<26} {counts[key]:>3}  ({pct:5.1f}%)")
        print("  (a rule is 'named' when the reference graph reaches it; R4 is")
        print("   what proves the value is actually consulted rather than read.)")

    assert counts["by_a_check"] >= BASELINE_CONSULTED_BY_A_CHECK
    assert counts["by_a_strategy"] >= BASELINE_CONSULTED_BY_A_STRATEGY
    assert counts["by_both"] >= BASELINE_CONSULTED_BY_BOTH


def test_consultation_is_transitive_through_dsp_helpers(graph: Graph) -> None:
    """The property that makes R2 worth more than a grep.

    ``ADDON_NEIGHBOUR_RADIAL_GAP`` appears nowhere under ``layout/``.  A grep
    calls it unread; it is read, by ``game.addon_corner`` through
    ``rules.addon_ride_is_straight``.
    """
    rows = {r.entry.symbol: r for r in provenance.consultation(graph)}
    gap = rows["rules.ADDON_NEIGHBOUR_RADIAL_GAP"]
    assert "game.addon_corner" in gap.checks


def test_strategy_reach_does_not_launder_itself_through_the_validator(graph: Graph) -> None:
    """A strategy calling ``certify()`` must not inherit every check's rules.

    The canary must be a rule a CHECK reads and no search code does.  If the
    strategy closure were allowed through ``validate``, it would come back
    consulted -- and every "the search consults the rule" claim in the R2 table
    would be worthless.

    The canary is a rule a validator check reads and no search code does. If
    strategy closure were allowed through ``validate``, every strategy would
    appear to consult it and the R2 table would be meaningless.
    """
    canary = "rules.PASTE_SNAP"
    rows = {r.entry.symbol: r for r in provenance.consultation(graph)}
    assert rows[canary].checks, f"{canary} is no longer read by any check"
    assert not rows[canary].strategies, (
        f"{canary} is now reachable from the search, so it can no longer detect "
        "laundering. Pick another rule that only a check reads -- "
        "`provenance.consultation()` lists them -- rather than deleting this test."
    )


def test_the_registry_would_report_a_rule_that_lost_its_last_reader() -> None:
    """Mutation check on R2 itself.

    Hand ``consultation`` a graph with every edge cut and it must report every
    rule unread.  If it cannot produce that answer it cannot produce a true one.
    """
    empty = Graph(edges={}, owner={})
    rows = provenance.consultation(empty)
    assert rows, "the registry declares no rules at all"
    assert all(not r.consulted for r in rows)
    assert provenance.summary(rows)["by_nothing"] == len(rows)


def test_a_rule_consulted_only_at_a_hardcoded_tech_level_is_reported(graph: Graph) -> None:
    """The plan's tech clause, second half.

    ``DEFAULT_MAX_BELT_Z`` is ``belt_max_z()`` frozen at the starting lab level.
    Reading it is consulting the ceiling at an assumed tech level, which is not
    the same thing as consulting the rule -- so the mechanism names the readers
    rather than counting them as clean.
    """
    readers = provenance.hardcoding_readers(graph)
    assert readers["catalog.DEFAULT_MAX_BELT_Z"], (
        "nothing reads the frozen ceiling any more -- strike the hardcodes "
        "declaration in registry.py"
    )
