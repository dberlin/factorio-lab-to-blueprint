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
from types import CodeType, ModuleType
from typing import Protocol, TypeGuard

from flab2bp.dsp import registry
from flab2bp.dsp.registry import Entry

_MISSING = object()


class _ZeroArgTest(Protocol):
    def __call__(self) -> None: ...


def _is_zero_arg_test(value: object) -> TypeGuard[_ZeroArgTest]:
    code: object = getattr(value, "__code__", None)
    return callable(value) and isinstance(code, CodeType) and code.co_argcount == 0


def _perturb_callable[**P](fn: Callable[P, object]) -> Callable[P, object]:
    @functools.wraps(fn)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> object:
        return perturb(fn(*args, **kwargs))

    return wrapped


def _scale_callable[**P](
    fn: Callable[P, object], factor: Fraction
) -> Callable[P, object]:
    @functools.wraps(fn)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> object:
        got = _scale(fn(*args, **kwargs), factor)
        return fn(*args, **kwargs) if got is _UNSCALABLE else got

    return wrapped


#: What the ladder multiplies a rule by, in order.
LADDER_FACTORS: tuple[Fraction, ...] = (
    Fraction(1, 2),
    Fraction(2),
    Fraction(1, 10),
    Fraction(10),
)


def perturb(value: object) -> object:
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
        return _perturb_callable(value)
    raise TypeError(f"no perturbation declared for {type(value).__name__}")


def ladder(value: object) -> list[object]:
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


def _scale(value: object, factor: Fraction) -> object:
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
        return _scale_callable(value, factor)
    return _UNSCALABLE


def _flab2bp_modules() -> list[ModuleType]:
    return [
        module
        for name, module in list(sys.modules.items())
        if name.startswith("flab2bp") and module is not None
    ]


def _clear_caches() -> None:
    for module in _flab2bp_modules():
        for value in list(vars(module).values()):
            obj: object = value
            clear: object = getattr(obj, "cache_clear", None)
            if callable(clear) and hasattr(obj, "cache_info"):
                clear()


@contextlib.contextmanager
def perturbed(entry: Entry, value: object = _MISSING) -> Iterator[object]:
    """Rebind ``entry`` to a perturbed value everywhere in the package."""
    home = importlib.import_module(f"flab2bp.dsp.{entry.module}")
    original: object = getattr(home, entry.name)
    replacement: object = perturb(original) if value is _MISSING else value

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
    original: object = getattr(home, entry.name)
    return tuple(
        sorted(
            m.__name__
            for m in _flab2bp_modules()
            if getattr(m, entry.name, _MISSING) is original
        )
    )


def rule_entries() -> tuple[Entry, ...]:
    """Rules with an observable emitted-paste seam for R4 to perturb."""
    return tuple(e for e in registry.rules() if e.mutation_exempt_because is None)


def exempt_rule_entries() -> tuple[Entry, ...]:
    """Explicitly inapplicable/dead rules excluded from R4."""
    return tuple(e for e in registry.rules() if e.mutation_exempt_because is not None)


def rule_batches(size: int = 8) -> tuple[tuple[Entry, ...], ...]:
    """Small pytest batches; each entry is still perturbed and restored alone."""
    entries = rule_entries()
    return tuple(entries[i : i + size] for i in range(0, len(entries), size))


Probe = Callable[[], object]
Witness = tuple[str, Callable[[], None]]


def validator_pool() -> list[Witness]:
    """No-fixture tests in ``tests/layout/test_validate.py``.

    R4 runs only the tests whose check id reaches the rule.  The normal pytest
    run already executes the whole file; replaying all of it for an unrelated
    or unconsulted rule both wastes time and lets a pre-existing failure masquerade
    as a reaction to every perturbation.
    """
    from tests.layout import test_validate

    return [
        (name, fn)
        for name, fn in sorted(vars(test_validate).items())
        if name.startswith("test_") and _is_zero_arg_test(fn)
    ]


def boundary_pool() -> dict[str, tuple[Witness, ...]]:
    """Independent numeric controls for applicable centralized paste rules."""
    from tests.rules import test_paste_rules

    return {
        symbol: tuple((f"paste.{fn.__name__}", fn) for fn in functions)
        for symbol, functions in test_paste_rules.MUTATION_WITNESSES.items()
    }


def targeted(pool: list[Witness], checks: Sequence[str]) -> list[Witness]:
    """The subset of the pool that tests the checks which reach this rule.

    Replaying the whole validator file for every rule is both expensive and
    semantically wrong: a failure in an unrelated check is not a reaction at
    this rule's seam.  R2's reference graph therefore selects checks that reach
    the rule, and :func:`boundary_pool` supplies independent numeric witnesses
    for centralized paste predicates whose downstream reader is still a gap.

    A rule reached by no check and carrying no boundary witness runs no
    validator test.  Its strategy probes and explicit frozen/exempt
    classification are the only claims R4 can honestly make.
    """
    fragments = [c.replace(".", "_") for c in checks]
    if not fragments:
        return []
    return [w for w in pool if any(f in w[0] for f in fragments)]


def outcome(fn: Callable[[], None]) -> str:
    """Stable result used to compare a witness before and after perturbation."""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - the failure IS the measurement
        return f"{type(exc).__name__}: {exc}"
    return "<passed>"


def first_changed(
    pool: Sequence[Witness], baseline: dict[str, str]
) -> str | None:
    """First witness whose outcome changes from its unperturbed outcome."""
    for name, fn in pool:
        if name not in baseline:
            baseline[name] = outcome(fn)
        if outcome(fn) != baseline[name]:
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
    boundaries: Mapping[str, Sequence[Witness]],
    checks: Sequence[str],
    probes_enabled: bool,
    witness_baseline: dict[str, str],
    baseline: dict[str, str],
    snapshot: Callable[[], dict[str, str]],
    changed: Callable[[dict[str, str], dict[str, str]], tuple[str, ...]],
) -> Verdict:
    """Walk the ladder until both observable sides react, or it runs out."""
    witnesses = [
        *targeted(list(pool), checks),
        *boundaries.get(entry.symbol, ()),
    ]
    # Capture the unperturbed outcome before entering any mutation context.
    # A stale imported test that is already red is not evidence that this rule
    # moved; only a changed outcome is.
    for name, fn in witnesses:
        if name not in witness_baseline:
            witness_baseline[name] = outcome(fn)

    home = importlib.import_module(f"flab2bp.dsp.{entry.module}")
    original: object = getattr(home, entry.name)
    rungs = ladder(original)
    best = Verdict(entry.symbol, None, (), None)
    for rung in rungs:
        try:
            with perturbed(entry, rung):
                red = first_changed(witnesses, witness_baseline)
                moved = changed(baseline, snapshot()) if probes_enabled else ()
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
