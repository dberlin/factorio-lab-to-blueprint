"""The machinery R4 needs: perturb a declared rule, everywhere it is bound.

Why this is not one ``monkeypatch.setattr``
-------------------------------------------

Most of ``layout/`` reads a rule as ``catalog.MAX_BELT_SLOPE`` -- an attribute
lookup, live on every call, so patching the ``dsp`` module reaches it.  But
``slots.py`` and ``junction.py`` use ``from flab2bp.dsp.rules import
SLOT_REACH``, which copies the VALUE into their own module globals at import.
Patching ``rules.SLOT_REACH`` alone leaves those copies untouched, R4 sees the
strategy fail to react, and the mechanism reports a consolidation defect that
does not exist.  A false accusation is as expensive here as a missed one.

So a perturbation rebinds the name in every ``flab2bp`` module whose global of
that name IS the original object, and then clears every ``lru_cache`` in the
package -- because a rule read inside a cached function was read once, at first
call, and a mutation after that would be invisible.

What it still cannot reach
--------------------------

A value already folded into another module-level constant at import time.
``rules.SLOT_ALIGN_COS`` is ``cos(SKEW_AXIS_DEG)``, computed once; perturbing
``SKEW_AXIS_DEG`` does not move it.  That is declared in the registry
(``SLOT_ALIGN_COS`` is ``DERIVED``, projecting ``SKEW_AXIS_DEG``) rather than
worked around, and it is why R4's verdict for a rule with derived projections
is read as "at least this much reacts", never "only this reacts".
"""

from __future__ import annotations

import contextlib
import functools
import importlib
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from flab2bp.dsp import registry
from flab2bp.dsp.registry import Entry

_MISSING = object()

#: What the ladder multiplies a rule by, in order.
LADDER_FACTORS: tuple[Fraction, ...] = (
    Fraction(1, 2),
    Fraction(2),
    Fraction(1, 10),
    Fraction(10),
)

#: Indices into :data:`LADDER_FACTORS` that move a rule by an order of
#: magnitude.  These are the rungs the WHOLE validator pool is spent on when
#: R2's targeting had nothing to narrow to.
EXTREME_RUNGS: tuple[int, ...] = (2, 3)


def perturb(value: Any) -> Any:
    """A different value of the same shape, chosen to TIGHTEN where it can.

    Halving a reach or a radius makes a rule refuse things it used to allow,
    which is the direction that shows up as a new finding rather than as a
    silently wider search.  ``SLOT_REACH`` 0.8 -> 0.4 is the plan's own example.
    """
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value - 1 if value > 1 else value + 1
    if isinstance(value, Fraction):
        return value / 2 if value > 0 else value - 1
    if isinstance(value, float):
        return value / 2.0 if value > 0 else value - 1.0
    if isinstance(value, str):
        return value + "-perturbed"
    if isinstance(value, tuple):
        return tuple(perturb(v) for v in value)
    if isinstance(value, frozenset):
        return frozenset(sorted(value, key=repr)[1:]) if value else frozenset({0})
    if isinstance(value, range):
        return range(value.start, max(value.start + 1, value.stop - 1))
    if isinstance(value, Mapping):
        return {k: perturb(v) for k, v in value.items()}
    if callable(value):
        fn = value

        @functools.wraps(fn)
        def perturbed(*args: Any, **kwargs: Any) -> Any:
            return perturb(fn(*args, **kwargs))

        return perturbed
    raise TypeError(f"no perturbation declared for {type(value).__name__}")


def ladder(value: Any) -> list[Any]:
    """Perturbations to try, in order, until something reacts.

    One perturbation is not enough to conclude anything.  ``SLOT_REACH`` 0.8 ->
    0.4 turns nothing red, and the tempting reading -- "the search ignores the
    reach rule" -- is wrong: it means no case in the corpus sits between 0.4 and
    0.8.  A rule is only inert if a whole RANGE of values leaves everything
    unmoved, so the ladder walks an order of magnitude in both directions before
    calling a constant dead.  Short-circuited by the caller: a rule that reacts
    on the first rung never pays for the rest.
    """
    factors = LADDER_FACTORS
    rungs = [r for r in (_scale(value, f) for f in factors) if r is not _UNSCALABLE]
    return rungs or [perturb(value)]


_UNSCALABLE = object()


def _scale(value: Any, factor: Fraction) -> Any:
    """``value`` with every number in it multiplied, shape preserved.

    A rule is often a TABLE -- ``SORTER_LENGTH`` keyed by endpoint kind,
    ``BELT_RATE`` by tier -- and scaling the whole table is what a tech-indexed
    rule's ladder has to look like.  Perturbing one entry of a lookup and
    watching everything stay green proves nothing, because the corpus may not
    use that key.
    """
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        moved = int(value * factor)
        return moved if moved != value else value + 1
    if isinstance(value, Fraction):
        return value * factor
    if isinstance(value, float):
        return value * float(factor)
    if isinstance(value, tuple):
        items = [_scale(v, factor) for v in value]
        return _UNSCALABLE if any(p is _UNSCALABLE for p in items) else tuple(items)
    if isinstance(value, frozenset | set):
        # A COMPILED PROJECTION is a set of offsets, and until this clause
        # existed the ladder could not move one: `_scale` fell through to
        # `_UNSCALABLE`, and for a CALLABLE returning a set that is invisible --
        # the `scaled` wrapper below hands back the unscaled value and every
        # rung reads as no reaction.  `rules.power_node_keepout_offsets` was
        # measured inert for exactly that reason while both packers read it.
        scaled_items = [_scale(v, factor) for v in value]
        if any(p is _UNSCALABLE for p in scaled_items):
            return _UNSCALABLE
        return frozenset(scaled_items)
    if isinstance(value, Mapping):
        pairs = {k: _scale(v, factor) for k, v in value.items()}
        return _UNSCALABLE if any(p is _UNSCALABLE for p in pairs.values()) else pairs
    if callable(value):
        fn = value

        @functools.wraps(fn)
        def scaled(*args: Any, **kwargs: Any) -> Any:
            got = _scale(fn(*args, **kwargs), factor)
            return fn(*args, **kwargs) if got is _UNSCALABLE else got

        return scaled
    return _UNSCALABLE


def _flab2bp_modules() -> list[Any]:
    return [
        m
        for name, m in list(sys.modules.items())
        if name.startswith("flab2bp") and m is not None
    ]


def _clear_caches() -> None:
    for module in _flab2bp_modules():
        for obj in list(vars(module).values()):
            clear = getattr(obj, "cache_clear", None)
            if callable(clear) and hasattr(obj, "cache_info"):
                clear()


@contextlib.contextmanager
def perturbed(entry: Entry, value: Any = _MISSING) -> Iterator[Any]:
    """Rebind ``entry`` to a perturbed value everywhere in the package."""
    home = importlib.import_module(f"flab2bp.dsp.{entry.module}")
    original = getattr(home, entry.name)
    replacement = perturb(original) if value is _MISSING else value

    holders = [
        m for m in _flab2bp_modules() if getattr(m, entry.name, _MISSING) is original
    ]
    for module in holders:
        setattr(module, entry.name, replacement)
    _clear_caches()
    try:
        yield replacement
    finally:
        for module in holders:
            setattr(module, entry.name, original)
        _clear_caches()


def rebinding_modules(entry: Entry) -> tuple[str, ...]:
    """Every module holding its own reference to this rule.  Diagnostics only."""
    home = importlib.import_module(f"flab2bp.dsp.{entry.module}")
    original = getattr(home, entry.name)
    return tuple(
        sorted(
            m.__name__
            for m in _flab2bp_modules()
            if getattr(m, entry.name, _MISSING) is original
        )
    )


def rule_entries() -> tuple[Entry, ...]:
    return registry.rules()


Probe = Callable[[], Any]
Witness = tuple[str, Callable[[], None]]


def validator_pool() -> list[Witness]:
    """Every no-fixture test in ``tests/layout/test_validate.py``.

    192 of its 199, called directly.  "A validator test goes red" is what the
    plan asks R4 to assert, and these are real tests from the real suite rather
    than assertions written to be perturbed.
    """
    from tests.layout import test_validate

    return [
        (name, fn)
        for name, fn in sorted(vars(test_validate).items())
        if name.startswith("test_")
        and callable(fn)
        and getattr(fn, "__code__", None) is not None
        and fn.__code__.co_argcount == 0
    ]


def targeted(pool: list[Witness], checks: Sequence[str]) -> list[Witness]:
    """The subset of the pool that tests the checks which reach this rule.

    The whole pool costs ~0.55s, which fifty-four rules times four ladder rungs
    turns into two minutes -- and the full suite is already 261s against a hard
    300s ceiling.  So R2's own reference graph picks the subset: a rule reached
    by ``geom.altitude_step`` is tried against the tests whose names carry
    ``geom_altitude_step``, which is this module's naming convention throughout.

    The narrowing is an OPTIMISATION, and it was CHECKED rather than assumed.
    Every one of the 54 rules was run twice -- once the fast way, once
    exhaustively against all 192 tests on all four rungs -- and the two agreed
    on every verdict: 112s exhaustive against 27s targeted, zero
    disagreements.  Getting there caught two real false negatives, which is why
    the ladder scales whole tables and function RETURNS rather than perturbing
    one entry: ``SORTER_LENGTH`` and ``sorter_rate`` both read as inert under a
    single-entry perturbation and neither is.

    A rule reached by no check at all gets the whole pool, since there is
    nothing to narrow to and its silence is the claim being tested -- but only
    on the two extreme rungs, per :data:`EXTREME_RUNGS`.
    """
    fragments = [c.replace(".", "_") for c in checks]
    if not fragments:
        return []
    return [w for w in pool if any(f in w[0] for f in fragments)]


def first_red(pool: Sequence[Witness]) -> str | None:
    for name, fn in pool:
        try:
            fn()
        except Exception:  # noqa: BLE001 - the failure IS the measurement
            return name
    return None


@dataclass(frozen=True, slots=True)
class Verdict:
    symbol: str
    #: The validator test that went red, if any.
    validator: str | None
    #: The strategy probes whose answer changed, if any.
    probes: tuple[str, ...]
    #: The perturbation that produced the reaction.
    rung: str | None

    @property
    def label(self) -> str:
        if self.validator and self.probes:
            return "both"
        if self.validator:
            return "validator"
        if self.probes:
            return "strategy"
        return "inert"


def verdict(
    entry: Entry,
    *,
    pool: Sequence[Witness],
    checks: Sequence[str],
    baseline: dict[str, str],
    snapshot: Callable[[], dict[str, str]],
    changed: Callable[[dict[str, str], dict[str, str]], tuple[str, ...]],
) -> Verdict:
    """Walk the ladder until both sides react, or the ladder runs out."""
    narrow = targeted(list(pool), checks)
    home = importlib.import_module(f"flab2bp.dsp.{entry.module}")
    rungs = ladder(getattr(home, entry.name))

    # The whole pool only when targeting found nothing to run.  When a check
    # names the rule and its tests exist, their silence IS the answer; running
    # the other 190 as well costs 0.55s a rung and was measured to change no
    # verdict (see the module docstring's note on the full-pool cross-check).
    witnesses = narrow if narrow else list(pool)
    # When nothing narrowed it, 192 tests times four rungs is 3.5s of a suite
    # that has 39s of headroom in total.  The probes still see every rung --
    # they cost nothing -- and the pool sees the two EXTREME ones, an order of
    # magnitude either way.  A rule any check truly consults does not survive
    # being multiplied by ten.
    tested_rungs = set(range(len(rungs))) if narrow else set(EXTREME_RUNGS)
    best = Verdict(entry.symbol, None, (), None)
    for index, rung in enumerate(rungs):
        try:
            with perturbed(entry, rung):
                red = first_red(witnesses) if index in tested_rungs else None
                moved = changed(baseline, snapshot())
        except Exception as exc:  # noqa: BLE001 - a crash is a reaction
            red, moved = f"<{type(exc).__name__} perturbing {entry.symbol}>", ()
        best = Verdict(
            entry.symbol,
            red or best.validator,
            moved or best.probes,
            repr(rung) if (red or moved) else best.rung,
        )
        if best.validator and best.probes:
            return best
    return best
