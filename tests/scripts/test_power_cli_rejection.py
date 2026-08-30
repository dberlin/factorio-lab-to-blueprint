from __future__ import annotations

import sys

import pytest

from scripts import ab_compare, route_bench, route_profile


def test_ab_compare_rejects_legacy_power_selector() -> None:
    with pytest.raises(SystemExit) as exc:
        ab_compare._parse_args(["--power"])

    assert exc.value.code == 2


def test_route_profile_rejects_legacy_power_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        route_profile,
        "_spec",
        lambda *_args: pytest.fail("legacy selector reached profile execution"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["route_profile.py", "plastic", "--power", "0"],
    )

    with pytest.raises(SystemExit) as exc:
        route_profile.main()

    assert exc.value.code == 2


def test_route_bench_rejects_legacy_power_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        route_bench,
        "capture",
        lambda *_args: pytest.fail("legacy selector reached capture execution"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["route_bench.py", "--capture", "plastic", "--power", "0"],
    )

    with pytest.raises(SystemExit) as exc:
        route_bench.main()

    assert exc.value.code == 2
