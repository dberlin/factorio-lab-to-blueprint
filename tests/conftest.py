"""Suite-wide sharing of the one genuinely expensive thing in these tests.

Almost all of the suite's wall-clock is CP-SAT, and almost all of *that* was
spent re-deriving placements the suite already had.  The dominant shape is a
class of six tests that each assert a different property of the *same*
placement, and each one opened with its own ``lay_out`` call::

    p = SpineLayout(power=power).lay_out(spec_fn(), time_budget_s=0.5)

Multiplied by the ``(spec, power)`` parametrisations that is dozens of
identical solves per module.  Nothing in those tests mutates the result --
``Placement`` and ``BuildSpec`` are both frozen -- so solving once and handing
the same object to every assertion preserves every assertion exactly while
paying for the solve once.

Rather than hoist each cluster into its own fixture (which would have meant
rewriting ~200 call sites across two 1,200-line modules, and re-writing them
again after every ``lay_out`` signature change), the memo is applied once here,
at the seam.  The key is the full call -- strategy class, its configuration,
the spec's exact value, and every argument -- so two calls share a result only
when they would genuinely have computed the same one.

Tests requesting ``monkeypatch`` are automatically uncached, so a test that
patches solver internals can never be served a placement built before the patch
was applied.
"""

from __future__ import annotations

import functools
from collections.abc import Iterator
from typing import Any, cast

import pytest

from flab2bp.layout.base import NoValidLayout
from flab2bp.layout.freeform import FreeformLayout
from flab2bp.layout.spine import SpineLayout

_MISS = object()
_CACHE: dict[tuple[str, ...], Any] = {}
#: Flipped per-test by the autouse policy fixture below.
_enabled = True


def _key(
    layout: object, spec: Any, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> tuple[str, ...]:
    """Identify a ``lay_out`` call by everything that can change its result.

    ``BuildSpec`` is frozen but unhashable (it holds ``dict`` fields), so its
    JSON dump stands in for its value; it costs ~8us against solves measured in
    seconds.  Strategy configuration is read straight off the instance rather
    than from a hand-written field list, so a new knob on ``SpineLayout`` or
    ``FreeformLayout`` joins the key automatically instead of silently aliasing
    two different configurations onto one cache entry.
    """
    return (
        f"{type(layout).__module__}.{type(layout).__qualname__}",
        repr(sorted(vars(layout).items(), key=lambda kv: kv[0])),
        cast(str, spec.model_dump_json()),
        repr(args),
        repr(sorted(kwargs.items())),
    )


def _install_memo(cls: type) -> None:
    original = cls.lay_out  # type: ignore[attr-defined]

    @functools.wraps(original)
    def lay_out(self: object, spec: Any, *args: Any, **kwargs: Any) -> Any:
        if not _enabled:
            return original(self, spec, *args, **kwargs)
        key = _key(self, spec, args, kwargs)
        hit = _CACHE.get(key, _MISS)
        if hit is _MISS:
            try:
                hit = original(self, spec, *args, **kwargs)
            except NoValidLayout as refusal:
                # A refusal is an outcome, not a transient error, and it is the
                # *expensive* one: the strategy burns its budget, retries for
                # RETRY_BUDGET_S, and only then gives up. Re-deriving a refusal
                # per test costs far more than re-deriving a success.
                hit = refusal
            _CACHE[key] = hit
        if isinstance(hit, NoValidLayout):
            raise hit
        return hit

    cls.lay_out = lay_out  # type: ignore[attr-defined]


_install_memo(SpineLayout)
_install_memo(FreeformLayout)


@pytest.fixture(autouse=True)
def _layout_memo_policy(request: pytest.FixtureRequest) -> Iterator[None]:
    global _enabled
    _enabled = "monkeypatch" not in request.fixturenames
    try:
        yield
    finally:
        _enabled = True
