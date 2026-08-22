"""Shared access to the real-game blueprint fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
from _pytest.mark import ParameterSet

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"

#: The one fixture that is a Dyson-sphere blueprint, not a factory blueprint.
DYSON_FIXTURE = "dyson-sphere-iridescent"


def fixture_paths(*, include_dyson: bool = True) -> list[Path]:
    paths = sorted(FIXTURE_DIR.glob("*.txt"))
    if not include_dyson:
        paths = [p for p in paths if p.stem != DYSON_FIXTURE]
    return paths


def fixture_texts(*, include_dyson: bool = True) -> list[ParameterSet]:
    """``(name, text)`` params for ``pytest.mark.parametrize``.

    Each carries an explicit id; without one pytest would splice the entire
    blueprint string -- tens of kilobytes of base64 -- into the test name.
    """
    return [
        pytest.param(p.stem, p.read_text(encoding="utf-8").strip(), id=p.stem)
        for p in fixture_paths(include_dyson=include_dyson)
    ]


def fixture_text(name: str) -> str:
    return (FIXTURE_DIR / f"{name}.txt").read_text(encoding="utf-8").strip()
