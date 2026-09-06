"""Throwaway A/B switches for the 2026-09-06 density decomposition spike.

WHY A ``sitecustomize``.  ``scripts/audit.py`` fans its cells out over a
``ProcessPoolExecutor`` (scripts/audit.py:806) and Python 3.14 starts those
children with *forkserver* on Linux, so a monkeypatch applied in the parent
never reaches the process that actually lays a cell out.  CPython imports
``sitecustomize`` at interpreter startup in EVERY process, and ``PYTHONPATH``
is inherited by the pool's children, so putting this directory on
``PYTHONPATH`` is the one mechanism that is guaranteed to reach the worker.

NOTHING IN ``src`` IS TOUCHED.  Each switch turns off a mechanism that already
has a seam:

* ``FLAB2BP_SPIKE_NO_DIRECT=1`` -- forces the production flag
  ``FreeformLayout(direct_insert=False)`` (src/flab2bp/layout/freeform.py:19415,
  read at freeform.py:19942 and freeform.py:20330 as
  ``_direct_candidate_snapshot(..., enabled=self.direct_insert)``, which empties
  the candidate set the packer is rewarded for aligning, so ``pack.direct`` is
  empty and no ``_bridge`` is ever attempted).  Freeform only: sequence-pair's
  direct insertion is ``sequence_pair.align_direct_inserts`` and has no switch,
  which is why the sequence-pair arm is a NOISE CONTROL for this configuration
  rather than a measurement.

* ``FLAB2BP_SPIKE_NO_SHARING=1`` -- makes every net route its own belt:

  1. ``freeform._merge_frontier`` (freeform.py:8907) returns the empty set.
     That function is the ONLY producer of "free cells beside a sibling net's
     path", i.e. the branch points (source side, ``src_group``: nets leaving
     the same item+domain+lane, freeform.py:9517) and the side-merge points
     (destination side, ``dst_group``: nets arriving at the same lane tile,
     freeform.py:9503).  Both call sites -- freeform.py:10007 for the source
     frontier and freeform.py:10053 for the destination frontier -- go through
     it, as do the look-ahead probes at freeform.py:11101/11136.  With it empty
     a net can only start on its own port access cell and can only finish on
     its own sink, so two nets can never come to share one physical run.
  2. ``freeform._plan_shared_external_inputs`` (freeform.py:15943) is called
     with ``belt_stack`` forced to 1, which takes its stack-one early return
     (freeform.py:15970) -- "every consumer strip still owns its physical input
     lane" -- so no shared perimeter trunk is planned and
     ``_place_shared_external_input_trunks`` (freeform.py:16064) places none.

  This one reaches sequence-pair too: ``sequence_solver`` imports
  ``_prepare_routing_problem`` from freeform (sequence_solver.py:74) and the
  detailed router is shared.

Both switches are OFF unless the environment variable is exactly ``1``, and a
process that cannot apply a requested switch dies rather than quietly measuring
the baseline again.
"""

from __future__ import annotations

import os

_NO_DIRECT = os.environ.get("FLAB2BP_SPIKE_NO_DIRECT") == "1"
_NO_SHARING = os.environ.get("FLAB2BP_SPIKE_NO_SHARING") == "1"


def _stack_one(spec: object) -> object:
    """``spec`` with ``belt_stack`` forced to 1, leaving the caller's copy alone."""
    if getattr(spec, "belt_stack", 1) == 1:
        return spec
    model_copy = getattr(spec, "model_copy", None)
    if model_copy is not None:
        return model_copy(update={"belt_stack": 1})
    import dataclasses

    return dataclasses.replace(spec, belt_stack=1)  # type: ignore[type-var]


def _apply() -> None:
    from flab2bp.layout import freeform

    if _NO_DIRECT:
        original_init = freeform.FreeformLayout.__init__

        def patched_init(self, **kwargs):  # type: ignore[no-untyped-def]
            kwargs["direct_insert"] = False
            original_init(self, **kwargs)

        freeform.FreeformLayout.__init__ = patched_init

    if _NO_SHARING:

        def no_frontier(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            return set()

        freeform._merge_frontier = no_frontier

        original_plan = freeform._plan_shared_external_inputs

        def unshared_external_inputs(spec, strips, strip_in_ports, per_item):  # type: ignore[no-untyped-def]
            return original_plan(_stack_one(spec), strips, strip_in_ports, per_item)

        freeform._plan_shared_external_inputs = unshared_external_inputs


if _NO_DIRECT or _NO_SHARING:
    _apply()
