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
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

import pytest

from flab2bp.lab.data import load_vendored
from flab2bp.lab.flow import flow_from_text, pin_request
from flab2bp.lab.url import parse_url
from flab2bp.layout import freeform, geometry_memo
from flab2bp.layout.base import NoValidLayout, Placement
from flab2bp.layout.freeform import FreeformLayout
from flab2bp.rates.candidates import build_candidates
from flab2bp.spec import BuildSpec

_REFINED_OIL_FLOW = Path(__file__).parent / "fixtures" / "flow_refined_oil_self_feedback.csv"
_REFINED_OIL_URL = "https://factoriolab.github.io/dsp/list?z=eJxFxrEKgzAUBdC.yXCnxCpOb7mhuEkVW8hadSgqQqRil.ftYqn0TGcWBlysNbOwRZpZwB3..J8jsb8-kGTnSbjzzdHvX89eaGK.yQ0BHQa8wRK8g4NyBBf4Ar5SX5tpihKUetXKrOLcDk0nJEA_&v=11"


def pytest_configure(config: pytest.Config) -> None:
    """Pop ``FLAB2BP_COATER_NODE`` once, at session start, so it can't leak in.

    The variable selects the Spray Coater placement arm (``off``/``placed``,
    see ``flab2bp.layout.coater_mode``) and is read straight from the shell
    environment. Several tests -- ``test_every_coater_arbiter_is_green_on_a_
    placed_build``, the ``test_coater_*`` checks in ``test_validate.py``, and
    others -- rely on it being UNSET to mean "the placed default", and on
    this box the variable leaks from the shell of whoever is running pytest.
    Popping it here means a developer's exported override can no longer
    silently make a "placed" test measure "off" instead; the gate's own
    scripts already run both arms under ``env -u FLAB2BP_COATER_NODE`` for
    exactly this reason.

    This is a `pytest_configure` hook and NOT an autouse fixture on purpose:
    ``_layout_memo_policy`` below branches on ``"monkeypatch" in
    request.fixturenames`` to decide whether to disable the layout memo for
    a test. An autouse fixture that took a ``monkeypatch`` parameter (or used
    ``monkeypatch.delenv``) would put ``"monkeypatch"`` in every test's
    fixturenames and silently disable that memo for the WHOLE suite. Do not
    "improve" this into a fixture.

    ``off_arm`` (this file has no copy; see ``test_freeform.py``,
    ``test_sequence_solver.py`` and ``hierarchy/test_compose.py``) and
    ``tests/layout/test_coater_node.py`` set the variable per-test with
    ``monkeypatch.setenv``, which runs after this hook, once per test -- they
    are unaffected by a one-time pop at session start.
    """
    os.environ.pop("FLAB2BP_COATER_NODE", None)


@pytest.fixture(scope="session")
def refined_oil_feedback_spec() -> BuildSpec:
    data = load_vendored()
    selection = flow_from_text(_REFINED_OIL_FLOW.read_text(), url=_REFINED_OIL_URL)
    request = pin_request(parse_url(_REFINED_OIL_URL), data, selection)
    (spec,) = build_candidates(data, request, flow=selection).candidates
    assert spec.label == "flow-pinned"
    return spec


class _Layout(Protocol):
    def lay_out(
        self,
        spec: BuildSpec,
        *,
        time_budget_s: float = 15.0,
        absolute_deadline: float | None = None,
    ) -> Placement: ...


_CACHE: dict[tuple[str, ...], Placement | NoValidLayout] = {}
#: Flipped per-test by the autouse policy fixture below.
_enabled = True


def _key(
    layout: _Layout,
    spec: BuildSpec,
    time_budget_s: float,
    absolute_deadline: float | None,
) -> tuple[str, ...]:
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
        # An absolute deadline changes the result, so it MUST be in the key: a
        # memo that omits an input returns the wrong answer, which is worse than
        # being slow.  `None` and a float are distinct keys.
        repr(absolute_deadline),
    )


def _install_memo(cls: type[_Layout]) -> None:
    original = cls.lay_out

    @functools.wraps(original)
    def lay_out(
        self: _Layout,
        spec: BuildSpec,
        *,
        time_budget_s: float = 15.0,
        absolute_deadline: float | None = None,
    ) -> Placement:
        if not _enabled:
            return original(
                self,
                spec,
                time_budget_s=time_budget_s,
                absolute_deadline=absolute_deadline,
            )
        key = _key(self, spec, time_budget_s, absolute_deadline)
        try:
            hit = _CACHE[key]
        except KeyError:
            try:
                hit = original(
                    self,
                    spec,
                    time_budget_s=time_budget_s,
                    absolute_deadline=absolute_deadline,
                )
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
    geometry_memo.clear()


@pytest.fixture(autouse=True)
def _cross_test_geometry_memos_start_clean() -> None:
    """Clear the process-lifetime geometry/sequencing memos before each test.

    ``freeform._DIRECT_ORIGIN_DELTAS_MEMO``, ``freeform._STAGED_CLEARANCE_KEYS_MEMO``
    and ``sequence_solver._REFINED_TARGET_MEMO`` are keyed on value-equal
    inputs across the whole process, exactly like ``_JUNCTION_BAN_OFFSET_CACHE``
    above -- a test that monkeypatches one of their dependencies could
    otherwise read an answer proved by an earlier, unpatched test for the
    same value-equal key, or leave one behind for a later test to patch
    around unknowingly.  Imported lazily to avoid a module-load-order
    dependency between ``freeform`` and ``sequence_solver``.
    """
    from flab2bp.layout import sequence_solver

    freeform._DIRECT_ORIGIN_DELTAS_MEMO.clear()
    freeform._STAGED_CLEARANCE_KEYS_MEMO.clear()
    sequence_solver._REFINED_TARGET_MEMO.clear()


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
