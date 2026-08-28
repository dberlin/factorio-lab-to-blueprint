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
from typing import Protocol

import pytest

from flab2bp.layout.base import NoValidLayout, Placement
from flab2bp.layout.freeform import FreeformLayout
from flab2bp.spec import BuildSpec


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


@pytest.fixture(autouse=True)
def _layout_memo_policy(request: pytest.FixtureRequest) -> Iterator[None]:
    global _enabled
    _enabled = "monkeypatch" not in request.fixturenames
    try:
        yield
    finally:
        _enabled = True
