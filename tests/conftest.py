"""Suite-wide sharing of the one genuinely expensive thing in these tests.

Almost all of the suite's wall-clock is CP-SAT, and repeated assertions often
ask for the same frozen ``Placement`` from the same frozen ``BuildSpec``.
Solving once and handing the same object to every assertion preserves each
assertion while paying for the solve once.

The memo is applied at the strategy seam. Its key is the full call -- strategy
class, configuration, exact spec value and every argument -- so calls share a
result only when they would genuinely compute the same one. Tests that
monkeypatch solver internals disable the memo automatically.
"""

from __future__ import annotations

import functools
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

import pytest

from flab2bp.lab.data import load_vendored
from flab2bp.lab.flow import flow_from_text, pin_request
from flab2bp.lab.url import parse_url
from flab2bp.layout import freeform
from flab2bp.layout.base import NoValidLayout, Placement
from flab2bp.layout.freeform import FreeformLayout
from flab2bp.rates.candidates import build_candidates
from flab2bp.spec import BuildSpec

_REFINED_OIL_FLOW = Path(__file__).parent / "fixtures" / "flow_refined_oil_self_feedback.csv"
_REFINED_OIL_URL = (
    "https://factoriolab.github.io/dsp/list?z=eJxFxrEKgzAUBdC.yXCnxCpOb7mhuEkVW8hadSgqQqRil.ftYqn0TGcWBlysNbOwRZpZwB3..J8jsb8-kGTnSbjzzdHvX89eaGK.yQ0BHQa8wRK8g4NyBBf4Ar5SX5tpihKUetXKrOLcDk0nJEA_&v=11"
)


@pytest.fixture(scope="session")
def refined_oil_feedback_spec() -> BuildSpec:
    data = load_vendored()
    selection = flow_from_text(_REFINED_OIL_FLOW.read_text(), url=_REFINED_OIL_URL)
    request = pin_request(parse_url(_REFINED_OIL_URL), data, selection)
    (spec,) = build_candidates(data, request, flow=selection).candidates
    assert spec.label == "flow-pinned"
    return spec


class _Layout(Protocol):
    def lay_out(self, spec: BuildSpec, *, time_budget_s: float = 15.0) -> Placement: ...


_CACHE: dict[tuple[str, ...], Placement | NoValidLayout] = {}
#: Flipped per-test by the autouse policy fixture below.
_enabled = True


def _key(layout: _Layout, spec: BuildSpec, time_budget_s: float) -> tuple[str, ...]:
    """Identify a ``lay_out`` call by everything that can change its result.

    ``BuildSpec`` is frozen but unhashable (it holds ``dict`` fields), so its
    JSON dump stands in for its value; it costs ~8us against solves measured in
    seconds.  Strategy configuration is read straight off the instance rather
    than from a hand-written field list, so a new knob joins the key
    automatically instead of silently aliasing two configurations.
    """
    return (
        f"{type(layout).__module__}.{type(layout).__qualname__}",
        repr(sorted(vars(layout).items(), key=lambda kv: kv[0])),
        spec.model_dump_json(),
        repr(time_budget_s),
    )


def _install_memo(cls: type[_Layout]) -> None:
    original = cls.lay_out

    @functools.wraps(original)
    def lay_out(
        self: _Layout, spec: BuildSpec, *, time_budget_s: float = 15.0
    ) -> Placement:
        if not _enabled:
            return original(self, spec, time_budget_s=time_budget_s)
        key = _key(self, spec, time_budget_s)
        try:
            hit = _CACHE[key]
        except KeyError:
            try:
                hit = original(self, spec, time_budget_s=time_budget_s)
            except NoValidLayout as refusal:
                # Refusals are outcomes and are cached like successful layouts.
                hit = refusal
            _CACHE[key] = hit
        if isinstance(hit, NoValidLayout):
            raise hit
        return hit

    layout_method = "lay_out"
    setattr(cls, layout_method, lay_out)


_install_memo(FreeformLayout)


def _reset_junction_ban_offset_cache() -> None:
    """Drop every offset a test may have proved under a patched dependency.

    ``_JUNCTION_BAN_OFFSET_CACHE`` and ``_junction_ban_offsets``'s ``lru_cache``
    are process-lifetime memos keyed on obstacle pose alone; they do not know
    when ``_junction_site_is_clear`` (or any other dependency) has been
    monkeypatched for the duration of one test.  A test that patches it could
    otherwise read a stale answer proved by an earlier, unpatched call for the
    same pose -- or leave a real answer behind for a later test to patch
    around unknowingly.
    """
    freeform._JUNCTION_BAN_OFFSET_CACHE.clear()
    freeform._junction_ban_offsets.cache_clear()


@pytest.fixture(autouse=True)
def _layout_memo_policy(request: pytest.FixtureRequest) -> Iterator[None]:
    global _enabled
    uses_monkeypatch = "monkeypatch" in request.fixturenames
    _enabled = not uses_monkeypatch
    if uses_monkeypatch:
        _reset_junction_ban_offset_cache()
    try:
        yield
    finally:
        _enabled = True
        if uses_monkeypatch:
            _reset_junction_ban_offset_cache()
