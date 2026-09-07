"""EXPERIMENT SWITCH: how a Spray Coater is placed.

This module exists for the ``exp-coater-node`` experiment and nothing else
reads it when the switch is off, which is the default.  Four arms:

``off``
    Today's behaviour.  ``_place_coaters`` seats the addon on the interior of
    the consumer strip's own west channel, ``_coater_seats`` offers
    ``tiles[1:west_channel]``, and the body may cover the lane head.

``seat``
    Variant A, the design's fix
    (``docs/superpowers/specs/2026-09-07-coater-node-design.md`` §5.1-§5.2):
    the seat starts at ``1 + half_span`` so the 3x1 body cannot cover the lane
    head, and the body's own level plus the area-1 rival cell join
    ``canvas.belt_ban`` so no merge can be offered there.

``packed``
    Variant B: one packed object per sprayed input lane -- a four-tile belt run
    with the coater riding its third tile -- placed by CP-SAT as its own
    rectangle, with three ports (item-in, item-out, proliferator-in).  The
    consumer strip's lane reverts to an ordinary ``WEST_CHANNEL`` lane.

``packed-hpwl``
    Variant B plus ONE line of pack objective: the node/consumer pair joins
    ``_nets_between``, so the wirelength term can see the node's out-net.
    Measured because ``packed`` bought +50% belt tiles against ``placed``'s
    +1.4% for the same nets, and the reason is exactly that a node contributes
    no HPWL term -- ``_nets_between`` derives its pairs from ``out_lanes`` and a
    node has none, so CP-SAT fits each node wherever the width objective is
    happiest and the router pays for the distance.  A separate arm rather than a
    change to ``packed`` so the evidence can report B both ways on the same
    cells.

``placed``
    Variant C: the same node, placed by a post-pack pass on free ground beside
    the consumer strip rather than by CP-SAT.  The packer is untouched.

The mode is read from ``FLAB2BP_COATER_NODE`` so a subprocess-per-cell harness
(``scripts/audit.py``, the CLI) can select an arm without threading a keyword
through every strategy entry point.
"""

from __future__ import annotations

import os
from enum import StrEnum

__all__ = ["CoaterMode", "coater_mode", "ENV_VAR"]

ENV_VAR = "FLAB2BP_COATER_NODE"


class CoaterMode(StrEnum):
    OFF = "off"
    SEAT = "seat"
    PACKED = "packed"
    PACKED_HPWL = "packed-hpwl"
    PLACED = "placed"

    @property
    def is_node(self) -> bool:
        """Does this arm build a free-standing coater node?"""
        return self in (CoaterMode.PACKED, CoaterMode.PACKED_HPWL, CoaterMode.PLACED)

    @property
    def packs_nodes(self) -> bool:
        """Does CP-SAT own the node's ground, rather than a post-pack search?"""
        return self in (CoaterMode.PACKED, CoaterMode.PACKED_HPWL)

    @property
    def node_wirelength(self) -> bool:
        """Does the pack objective see the node's out-net?

        Only ``packed-hpwl``.  ``packed`` is kept exactly as first measured so
        the evidence can report what this one line buys.
        """
        return self is CoaterMode.PACKED_HPWL

    @property
    def narrow_seats(self) -> bool:
        """Does this arm forbid a body that covers its own in-port?

        True for every arm but ``off``: the node arms emit a four-tile run
        whose head is the in-port, and seating the body over it would put the
        merge under the body exactly as today.
        """
        return self is not CoaterMode.OFF


def coater_mode() -> CoaterMode:
    """The arm this process runs.  ``off`` unless the switch says otherwise."""
    raw = os.environ.get(ENV_VAR, "").strip().lower()
    try:
        return CoaterMode(raw)
    except ValueError:
        return CoaterMode.OFF
