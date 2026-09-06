"""Spike-only monkeypatches, reached by putting this directory on PYTHONPATH.

Two switches, both off unless the environment variable is set.  ``sitecustomize``
rather than a parent-process patch because ``scripts/audit.py`` fans cells out
over a ``ProcessPoolExecutor`` that Python 3.14 starts with **forkserver**, so a
parent-side patch never reaches the process that lays a cell out.

``FLAB2BP_TRUNK_PROBE=<path>``
    Append one JSON line per ``_prepare_routing_problem`` return describing the
    prepared net population per item: net count, distinct source ports,
    distinct destination ports.  Read-only.

The trunk itself is NOT a monkeypatch -- it is a default-off flag in
``src/flab2bp/layout/freeform.py`` (``FLAB2BP_TRUNK_ITEMS`` /
``FreeformLayout(trunk_items=...)``), so that the validator sees exactly the
production code path.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict

_PROBE = os.environ.get("FLAB2BP_TRUNK_PROBE")

if _PROBE:
    import flab2bp.layout.freeform as ff

    _original = ff._prepare_routing_problem

    def _probed(*args, **kwargs):  # type: ignore[no-untyped-def]
        problem = _original(*args, **kwargs)
        try:
            nets = problem.nets
            per_item: dict[tuple[str, str], dict] = defaultdict(
                lambda: {"nets": 0, "srcs": set(), "dsts": set()}
            )
            for net in nets:
                key = (net.item, net.net_id.role.name)
                row = per_item[key]
                row["nets"] += 1
                if net.src is not None:
                    row["srcs"].add((net.src.y, net.src.x0, net.src.z))
                row["dsts"].add((net.dst.x, net.dst.y, net.dst.z))
            payload = {
                "total_nets": len(nets),
                "items": sorted(
                    (
                        {
                            "item": item,
                            "role": role,
                            "nets": row["nets"],
                            "src_lanes": len(row["srcs"]),
                            "dst_ports": len(row["dsts"]),
                        }
                        for (item, role), row in per_item.items()
                    ),
                    key=lambda r: (-r["dst_ports"], r["item"]),
                )[:12],
            }
            with open(_PROBE, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload) + "\n")
        except Exception as exc:  # noqa: BLE001 - a spike probe must never break a run
            with open(_PROBE, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({"probe_error": repr(exc)[:200]}) + "\n")
        return problem

    ff._prepare_routing_problem = _probed

    _apply = ff._apply_internal_trunks

    def _probed_trunk(*args, **kwargs):  # type: ignore[no-untyped-def]
        trunked = _apply(*args, **kwargs)
        with open(_PROBE, "a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "requested": sorted(kwargs.get("requested", ())),
                        "trunked": list(trunked),
                    }
                )
                + "\n"
            )
        return trunked

    ff._apply_internal_trunks = _probed_trunk
