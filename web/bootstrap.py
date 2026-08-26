"""What Pyodide runs once the shim and the wheel are in place.

Fetched and ``runPython``-ed by ``worker.js``.  It lives in a real ``.py``
file rather than a JavaScript string so it is readable, lintable, and cannot
be mangled by whichever quoting the host page happens to use.

It does three jobs: wire ``ortools._wasm_bridge`` to the page's JS bridge,
report each strategy/candidate pair as the pipeline settles it, and expose a
single ``solve`` entry point that returns JSON.  Nothing else in the browser
build touches flab2bp -- the package itself is installed unmodified.

**The JSON it returns is deliberately the server arm's job snapshot.**  The
build is described by ``flab2bp.web.payload.describe``, the same function
``flab2bp.web.jobs`` calls, and a refusal by ``flab2bp.web.payload.refusal``.
That is not a convenience: the two arms exist to be compared, and a comparison
between two arms that report different things measures the reporting.  Anything
this file added by hand would be a second implementation of the CLI's report,
free to drift -- and it had already drifted, silently dropping every validator
*warning* the build produced.
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
from flab2bp.web.payload import describe, refusal  # noqa: E402

#: ``best`` lays out every candidate with both strategies.  Mirrors
#: ``flab2bp.web.jobs._STRATEGIES_FOR_BEST`` so both arms scale the wait the
#: same way.
_STRATEGIES_FOR_BEST = 2


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


def _step(step: pipeline.AttemptProgress) -> dict[str, object]:
    """One :class:`~flab2bp.pipeline.AttemptProgress` as JSON.

    Field for field what ``flab2bp.web.jobs._step`` emits, so the page renders
    a browser solve's progress with the same code that renders a server one's.
    """
    return {
        "index": step.index,
        "total": step.total,
        "candidate": step.candidate,
        "strategy": step.strategy,
        "phase": step.phase,
        "area": step.area,
        "ok": step.ok,
        "reason": step.reason,
    }


def solve(options_json: str) -> str:
    options = json.loads(options_json)
    started = time.perf_counter()
    settled: list[dict[str, object]] = []

    def on_progress(step: pipeline.AttemptProgress) -> None:
        # Straight out to the worker's message channel. The solve holds a
        # suspendable stack, not the event loop, so this arrives while the
        # build is still running rather than in a batch at the end.
        as_json = _step(step)
        if step.phase != "started":
            settled.append(as_json)
        js.__flabProgress(json.dumps(as_json))

    per_spec = _STRATEGIES_FOR_BEST if options["strategy"] == "best" else 1
    envelope: dict[str, object] = {
        "options": {
            "url": options["url"],
            "strategy": options["strategy"],
            "candidates": options["candidates"],
            "budget_s": options["budget"],
            "power": options["power"],
            "allow_invalid": bool(options.get("allow_invalid", False)),
            "name": options.get("name", ""),
        },
        "solver_ceiling_s": options["candidates"] * per_spec * options["budget"],
        "result": None,
        "refusal": None,
        "error": None,
        "viewer": None,
        "settled": settled,
    }

    def finish(state: str, **rest: object) -> str:
        envelope["state"] = state
        envelope["elapsed_s"] = round(time.perf_counter() - started, 2)
        envelope.update(rest)
        return json.dumps(envelope)

    # `catch_warnings` is process-global and not thread-safe, which is exactly
    # why the server arm does not do this: its builds run in a thread pool. One
    # tab runs one solve at a time, so here it is sound -- and a warning the
    # pipeline raised is otherwise printed to a console nobody is reading.
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
                on_progress=on_progress,
            )
        except NoValidLayout as exc:
            # Not an error. Split back into one line per pair exactly as
            # `jobs._reasons` does, so the refusal renders identically.
            reasons = [part.strip() for part in exc.reason.split(";") if part.strip()]
            return finish("refused", refusal=refusal(reasons, message=str(exc)))
        except (ValueError, KeyError) as exc:
            return finish("error", error=str(exc))
        except Exception as exc:  # noqa: BLE001 - surfaced verbatim, never hidden
            return finish(
                "error",
                error=f"{type(exc).__name__}: {exc}",
                traceback=traceback.format_exc(),
            )
        runtime_warnings = [f"{w.category.__name__}: {w.message}" for w in caught]

    described = describe(build, allow_invalid=bool(options.get("allow_invalid", False)))
    return finish(
        "done",
        result=described,
        runtime_warnings=runtime_warnings,
        # Only when there is a string to decode. `describe` withholds it when
        # the build did not validate, and drawing the placement we still had in
        # hand instead would draw something the user was never given.
        viewer=_viewer_payload(described["blueprint"]) if described["blueprint"] else None,
    )
