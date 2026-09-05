"""Backend selection for the compiled oriented-box overlap test.

``FLAB2BP_GEOMETRY_KERNEL`` forces one backend: ``python`` or ``cython``.
Unset, the first available of ``cython`` then ``python`` is used.

This module deliberately does not import :mod:`flab2bp.dsp.colliders`:
``colliders`` imports *this* to dispatch, so an import back would close the
cycle.  The stub beside the extension names ``Box`` for typing; nothing here
needs it at runtime.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Literal

BackendName = Literal["python", "cython"]

_candidates: dict[BackendName, Callable[..., object] | None] = {"python": None}
try:
    from flab2bp.dsp._geometry_kernel import obb_overlap as _cython_obb_overlap

    _candidates["cython"] = _cython_obb_overlap
except ImportError:
    _candidates["cython"] = None

_PREFERENCE: tuple[BackendName, ...] = ("cython", "python")


def _choose() -> BackendName:
    forced = os.environ.get("FLAB2BP_GEOMETRY_KERNEL")
    if forced in ("python", "cython"):
        return forced  # type: ignore[return-value]
    for name in _PREFERENCE:
        if name == "python" or _candidates.get(name) is not None:
            return name
    return "python"


_backend: BackendName = _choose()
_compiled_obb_overlap: Callable[..., object] | None = _candidates.get(_backend)

#: The boxes-against-boxes loop lives in the same extension as the single test
#: above, so a forced ``python`` backend disables both.
_compiled_any_overlap: Callable[..., object] | None
try:
    from flab2bp.dsp._geometry_kernel import any_box_overlap as _compiled_any_overlap
except ImportError:
    _compiled_any_overlap = None
if _backend == "python":
    _compiled_any_overlap = None


def compiled_available() -> bool:
    return _compiled_obb_overlap is not None


def selected_backend() -> BackendName:
    return _backend if _compiled_obb_overlap is not None else "python"
