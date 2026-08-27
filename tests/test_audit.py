"""Behavioral checks for the corpus audit entry point."""

from scripts import audit


def test_both_selects_all_implemented_strategies() -> None:
    assert audit.strategy_names("both") == ("freeform", "sequence-pair")
