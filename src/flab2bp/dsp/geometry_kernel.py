"""Backend selection for exact compiled box and sphere overlap tests.

``FLAB2BP_GEOMETRY_KERNEL`` forces one backend: ``python`` or ``cython``.
Unset, the first available of ``cython`` then ``python`` is used.

This module deliberately does not import :mod:`flab2bp.dsp.colliders`:
``colliders`` imports *this* to dispatch, so an import back would close the
cycle.  The stub beside the extension names ``Box`` for typing; nothing here
needs it at runtime.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from flab2bp.dsp._geometry_kernel import (
        ProjectedBeltInputs,
        ProjectedBeltProbe,
        ProjectedBeltScan,
    )
    from flab2bp.dsp.colliders import Box, Vec3

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
#: above, so a forced ``python`` backend disables every compiled operation.
_compiled_any_overlap: Callable[..., object] | None
try:
    from flab2bp.dsp._geometry_kernel import any_box_overlap as _compiled_any_overlap
except ImportError:
    _compiled_any_overlap = None
if _backend == "python":
    _compiled_any_overlap = None

_compiled_sphere_overlap: Callable[[Vec3, float, Box], bool] | None
try:
    from flab2bp.dsp._geometry_kernel import sphere_box_overlap as _compiled_sphere_overlap
except ImportError:
    _compiled_sphere_overlap = None
if _backend == "python":
    _compiled_sphere_overlap = None

_compiled_sphere_candidates: (
    Callable[[Vec3, float, Sequence[Sequence[Box]], Sequence[int]], list[int]] | None
)
try:
    from flab2bp.dsp._geometry_kernel import sphere_box_candidates as _compiled_sphere_candidates
except ImportError:
    _compiled_sphere_candidates = None
if _backend == "python":
    _compiled_sphere_candidates = None

_compiled_belt_probe: type[ProjectedBeltProbe] | None
try:
    from flab2bp.dsp._geometry_kernel import ProjectedBeltProbe as _compiled_belt_probe
except ImportError:
    _compiled_belt_probe = None
if _backend == "python":
    _compiled_belt_probe = None

_compiled_projected_belt_scan: type[ProjectedBeltScan] | None
try:
    from flab2bp.dsp._geometry_kernel import ProjectedBeltScan as _compiled_projected_belt_scan
except ImportError:
    _compiled_projected_belt_scan = None
if _backend == "python":
    _compiled_projected_belt_scan = None

_compiled_belt_inputs: type[ProjectedBeltInputs] | None
try:
    from flab2bp.dsp._geometry_kernel import ProjectedBeltInputs as _compiled_belt_inputs
except ImportError:
    _compiled_belt_inputs = None
if _backend == "python":
    _compiled_belt_inputs = None


def compiled_available() -> bool:
    return _compiled_obb_overlap is not None


def selected_backend() -> BackendName:
    return _backend if _compiled_obb_overlap is not None else "python"
