"""Behavioral checks for the corpus audit entry point."""

from scripts import audit


def test_both_selects_active_alternative_strategies() -> None:
    """The default gate covers Freeform and SequencePair, never disabled Spine."""
    assert audit.strategy_names("both") == ("freeform", "sequence-pair")


def test_spine_remains_explicitly_auditable() -> None:
    """Disabling Spine from the default does not hide its diagnostic backend."""
    assert audit.strategy_names("spine") == ("spine",)
