"""Cross-validation against the viewer's independent TypeScript decoder.

The viewer is a genuinely independent implementation, so it catches encoder bugs
our own Python decoder would share by construction -- most importantly the
centre-vs-corner ``localOffset`` convention, which is currently an unverified
guess in ``dsp/codec.py``.

The viewer is a sibling checkout, not a dependency, so every one of these skips
cleanly when it or ``bun`` is absent. CI without the sibling repo stays green.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from flab2bp.bench.crossvalidate import (
    CrossCheck,
    bun_available,
    crossvalidate,
    viewer_deps_installed,
    viewer_path,
)
from flab2bp.dsp import catalog, codec
from flab2bp.layout.base import PlacedBuilding, Placement

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

needs_viewer = pytest.mark.skipif(
    not bun_available() or viewer_path() is None or not viewer_deps_installed(),
    reason=(
        "cross-validation needs `bun`, a dsp-blueprint-viewer checkout "
        "(set DSP_VIEWER_PATH), and `bun install` run in it"
    ),
)


def test_skips_cleanly_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Absence of the sibling repo must never turn into a failure."""
    monkeypatch.setenv("DSP_VIEWER_PATH", "/nonexistent/path/for/testing")
    assert viewer_path() is None


def test_viewer_path_prefers_the_environment_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "src" / "format").mkdir(parents=True)
    (tmp_path / "src" / "format" / "index.ts").write_text("")
    monkeypatch.setenv("DSP_VIEWER_PATH", str(tmp_path))
    assert viewer_path() == tmp_path


@pytest.mark.bun
@needs_viewer
def test_real_fixtures_are_accepted_by_the_independent_decoder() -> None:
    strings = [
        p.read_text().strip()
        for p in sorted(FIXTURES.glob("*.txt"))
        if not p.read_text().lstrip().startswith("DYBP:")
    ]
    assert strings
    results = crossvalidate(strings)
    assert len(results) == len(strings)
    for text, result in zip(strings, results, strict=True):
        assert result.ok, f"{text[:40]}: {result.error}"
        assert result.hash_valid


@pytest.mark.bun
@needs_viewer
def test_our_encoder_output_matches_the_independent_decoder() -> None:
    """Building count, item histogram and bounds must all agree.

    Bounds are the load-bearing assertion: they independently pin the
    centre-vs-corner ``localOffset`` convention.
    """
    # Footprints come from the catalog, never hardcoded -- these are real
    # buildings being really encoded, so a stale literal here would silently
    # test a geometry the game does not have.
    asm_w, asm_h = catalog.footprint(2304)
    smelt_w, smelt_h = catalog.footprint(2302)
    placement = Placement(
        buildings=(
            PlacedBuilding(
                item_id=2304, model_index=66, x=0, y=0, width=asm_w, height=asm_h
            ),
            PlacedBuilding(
                item_id=2302, model_index=62, x=10, y=0, width=smelt_w, height=smelt_h
            ),
            PlacedBuilding(item_id=2002, model_index=36, x=0, y=8, output_obj=3),
            PlacedBuilding(item_id=2002, model_index=36, x=1, y=8),
        )
    )
    text = codec.encode(placement)
    (result,) = crossvalidate([text])
    assert result.ok, result.error
    assert result.hash_valid
    assert result.buildings == len(placement.buildings)
    assert result.item_ids == {2304: 1, 2302: 1, 2002: 2}

    ours = codec.decode(text)
    assert result.bounds is not None
    xs = [b.x for b in ours.buildings]
    ys = [b.y for b in ours.buildings]
    assert result.bounds["minX"] == pytest.approx(min(xs))
    assert result.bounds["maxX"] == pytest.approx(max(xs))
    assert result.bounds["minY"] == pytest.approx(min(ys))
    assert result.bounds["maxY"] == pytest.approx(max(ys))


def test_crosscheck_reports_parse_failure_rather_than_raising() -> None:
    bad = CrossCheck(ok=False, error="boom")
    assert not bad.ok
    assert bad.hash_valid is False
