"""How a Spray Coater is placed.

``placed`` -- the default and the production model.  One free-standing
four-tile belt run per sprayed input lane, sited after the pack on free ground
beside the consumer lane head, with the addon riding its third tile.  Every
producer net and external run sinks into the node's IN-PORT, one tile west of
the body, so a many-to-one merge lands off the body BY CONSTRUCTION.

``off`` -- a GEOMETRY control, retained for one release as the A/B control.
It restores the old siting: the addon rides the interior of the consumer
strip's own widened ``_COATER_WEST_CHANNEL`` channel, and its 3x1 body may
cover the lane head, which is the reported defect: five and nine coater
bodies over a belt merge on the 72-cell corpus, six on the reported URL.

``off`` is NOT a working fallback for specs that hit that defect.  This
branch's ``prolif.coater_rides_one_run`` and ``prolif.coater_supply_is_fed``
(``validate.py``) are unconditional -- neither is gated on ``coater_mode()``
-- so both judge an ``off`` build too, and ``coater_rides_one_run`` convicts
exactly the merge-under-body geometry ``off`` produces. Building the
reported URL under ``off`` in this tree refuses where the merge base builds
it.  Do not read ``off`` as reproducing master's behaviour unqualified --
the geometry is master's, but the validator that judges it is not, and it
convicts exactly what the geometry does.

Measured, both arms, ``--budget 30``, two rounds, 72 cells
(``docs/superpowers/evidence/2026-09-07-exp-coater-node/README.md``):
``placed`` is 72/72 CLEAN with zero coater-merge findings against ``off``'s
71-72/72 with five and nine, at +2.7-2.9% area and +1.4% belt tiles.  Density
may be paid for correctness.

The mode is read from ``FLAB2BP_COATER_NODE`` so a subprocess-per-cell harness
(``scripts/audit.py``, the CLI) can select the control arm without threading a
keyword through every strategy entry point.  Anything but the exact string
``off`` selects ``placed``, including the three retired experiment arms
(``seat``, ``packed``, ``packed-hpwl``), so a stale harness cannot silently
reinstate the defect.
"""

from __future__ import annotations

import os
from enum import StrEnum

__all__ = ["CoaterMode", "coater_mode", "ENV_VAR"]

ENV_VAR = "FLAB2BP_COATER_NODE"


class CoaterMode(StrEnum):
    OFF = "off"
    PLACED = "placed"

    @property
    def is_node(self) -> bool:
        """Does this arm build a free-standing coater node?"""
        return self is CoaterMode.PLACED


def coater_mode() -> CoaterMode:
    """The arm this process runs.  ``placed`` unless the switch says ``off``."""
    raw = os.environ.get(ENV_VAR, "").strip().lower()
    return CoaterMode.OFF if raw == CoaterMode.OFF.value else CoaterMode.PLACED
