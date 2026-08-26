"""What Pyodide runs once the shim and the wheel are in place.

Fetched and ``runPython``-ed by ``worker.js``.  It lives in a real ``.py``
file rather than a JavaScript string so it is readable, lintable, and cannot
be mangled by whichever quoting the host page happens to use.

It does two jobs: wire ``ortools._wasm_bridge`` to the page's JS bridge, and
expose a single ``solve`` entry point that returns JSON.  Nothing else in the
browser build touches flab2bp -- the package itself is installed unmodified.
"""

from __future__ import annotations

import json
import time
import traceback
import warnings

import js
from ortools import _wasm_bridge
from pyodide.ffi import run_sync, to_js


def _bridge(kind: str, payload: bytes) -> bytes:
    """Block this (suspendable) Python stack on the asynchronous wasm solver.

    ``run_sync`` is only legal because ``worker.js`` invokes ``solve`` through
    ``callPromising()``, which runs it on a stack the engine can suspend.  If
    the browser lacks JSPI this raises, loudly, rather than degrading.
    """
    response = run_sync(js.__flabSolverBridge(kind, to_js(bytes(payload))))
    return bytes(response.to_py())


_wasm_bridge.set_bridge(_bridge)

from flab2bp import pipeline  # noqa: E402
from flab2bp.dsp import catalog, codec  # noqa: E402
from flab2bp.layout.base import NoValidLayout  # noqa: E402


def _viewer_payload(blueprint_text: str) -> dict[str, object]:
    """Decode the string we are about to hand the user, and describe it.

    Deliberately a round trip: the viewer draws what comes back out of
    ``codec.decode``, not the placement we still had in hand.  A blueprint
    that does not decode therefore cannot be drawn, which is the point.
    """
    blueprint = codec.decode(blueprint_text)
    buildings = []
    for item in blueprint.buildings:
        try:
            width, height = catalog.oriented_footprint(item.item_id, item.yaw)
            name = catalog.building(item.item_id).name
        except (KeyError, ValueError):
            width, height, name = 1, 1, f"item {item.item_id}"
        buildings.append(
            {
                "x": item.x,
                "y": item.y,
                "z": item.z,
                "w": width,
                "h": height,
                "id": item.item_id,
                "name": name,
                "belt": catalog.is_belt(item.item_id),
                "sorter": catalog.is_sorter(item.item_id),
            }
        )
    return {
        "title": blueprint.header.short_desc,
        "buildings": buildings,
        "hashValid": blueprint.hash_valid,
        "areas": [{"w": a.width, "h": a.height} for a in blueprint.areas],
    }


def _notes(build: pipeline.Build, caught: list[warnings.WarningMessage]) -> list[str]:
    notes: list[str] = []
    rules = build.belt_rules
    if rules is not None and not rules.from_url:
        notes.append(
            "WARNING: this URL carried no technology set, so a FULLY-RESEARCHED "
            f"save is ASSUMED: belt ceiling {float(rules.max_z)} (lab level "
            f"{rules.lab_level}), vertical belt construction "
            f"{'YES' if rules.vertical_construction else 'no'}. A URL exported "
            "from FactorioLab normally does carry one; if yours did, the belts "
            "here may climb higher than your save allows."
        )
    elif rules is not None:
        notes.append(
            f"belt altitude ceiling {float(rules.max_z)} (lab level "
            f"{rules.lab_level}), vertical belt construction "
            f"{'YES' if rules.vertical_construction else 'no'} -- read from the "
            "URL's researched technologies"
        )
    if not build.flow_pinned:
        notes.append(
            "recipe selection DERIVED, not pinned -- FactorioLab's own flow export "
            "is produced by driving a headless browser, which a page cannot do to "
            "itself, so this is the tool's own recipe choice"
        )
    notes.extend(f"{w.category.__name__}: {w.message}" for w in caught)
    return notes


def solve(options_json: str) -> str:
    options = json.loads(options_json)
    started = time.perf_counter()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            build = pipeline.build(
                options["url"],
                strategy=options["strategy"],
                power=options["power"],
                candidates=options["candidates"],
                time_budget_s=options["budget"],
                name=options.get("name", ""),
            )
        except NoValidLayout as exc:
            return json.dumps(
                {
                    "ok": False,
                    "kind": "NoValidLayout",
                    "refusal": str(exc),
                    "elapsed": time.perf_counter() - started,
                }
            )
        except (ValueError, KeyError) as exc:
            return json.dumps(
                {
                    "ok": False,
                    "kind": type(exc).__name__,
                    "refusal": str(exc),
                    "elapsed": time.perf_counter() - started,
                }
            )
        except Exception as exc:  # noqa: BLE001 - surfaced verbatim, never hidden
            return json.dumps(
                {
                    "ok": False,
                    "kind": "error",
                    "refusal": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                    "elapsed": time.perf_counter() - started,
                }
            )
        notes = _notes(build, list(caught))

    return json.dumps(
        {
            "ok": True,
            "elapsed": time.perf_counter() - started,
            "strategy": build.strategy,
            "candidate": build.spec.label,
            "machines": build.spec.machine_count,
            "tiles": build.placement.area,
            "buildings": len(build.placement.buildings),
            "blueprint": build.blueprint,
            "notes": notes,
            "refused": list(build.refused),
            "errors": [f"{f.check}: {f.message}" for f in build.report.errors],
            "skipped": sorted(build.report.skipped),
            "attempts": [
                {
                    "candidate": a.candidate,
                    "strategy": a.strategy,
                    "area": a.area,
                    "errors": len(a.report.errors),
                }
                for a in build.attempts
            ],
            "viewer": _viewer_payload(build.blueprint),
        }
    )
