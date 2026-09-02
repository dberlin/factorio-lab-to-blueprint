"""Spec-scoped memo of pure projection predicates, shared across candidates.

`_StagedStaticCache` memoizes finalizer projection inputs that are pure
functions of their keys.  It used to be created once per `_sweep` and once per
`_production_run`, so the second strategy in a `best` build and every later
`lay_out` of the same spec re-derived what the first had proved.  This registry
hands out one cache per spec object for the life of the process, bounded to
`MEMO_SPECS_RETAINED` specs so a long-lived audit worker cannot grow without
limit.  Keys are spec identity: a retained spec is held strongly, so its `id`
cannot be recycled while its cache is live.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import NamedTuple

from flab2bp.layout.freeform import _StagedStaticCache
from flab2bp.spec import BuildSpec

MEMO_SPECS_RETAINED = 4

_REGISTRY: OrderedDict[int, tuple[BuildSpec, _StagedStaticCache]] = OrderedDict()
#: Guards every read and write of ``_REGISTRY``. Builds run on a
#: ``ThreadPoolExecutor`` (``--workers`` in the web server), and each job
#: constructs its own spec, so caches are never shared between threads --
#: only this registry's bookkeeping is. Without the lock, one thread's
#: ``get`` -> ``move_to_end`` is not atomic with another thread's insert and
#: eviction, and a key can vanish between the two, raising ``KeyError``.
_LOCK = threading.Lock()


class MemoStats(NamedTuple):
    tables: dict[str, int]
    broad_phase_queries: int
    broad_phase_hits: int
    exact_static_queries: int


def for_spec(spec: BuildSpec) -> _StagedStaticCache:
    """Return the process-wide cache for ``spec``, creating and bounding it."""
    key = id(spec)
    with _LOCK:
        entry = _REGISTRY.get(key)
        if entry is not None:
            _REGISTRY.move_to_end(key)
            return entry[1]
        cache = _StagedStaticCache()
        _REGISTRY[key] = (spec, cache)
        while len(_REGISTRY) > MEMO_SPECS_RETAINED:
            _REGISTRY.popitem(last=False)
        return cache


def stats_for_spec(spec: BuildSpec) -> MemoStats:
    return for_spec(spec).stats()


def clear() -> None:
    with _LOCK:
        _REGISTRY.clear()
