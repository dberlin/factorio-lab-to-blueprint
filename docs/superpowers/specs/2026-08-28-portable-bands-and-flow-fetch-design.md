# Portable Latitude Bands and Flow Fetch Design

**Date:** 2026-08-28

## Status

Approved in chat for specification. Implementation requires a separate reviewed plan.

## Problem

Two independent correctness gaps meet at the final build boundary.

First, `--fetch-flow` fails before Chromium starts. The published `nodriver` 0.50.3 wheel contains a raw Latin-1 `0xb1` byte in `nodriver/cdp/network.py` without a source encoding declaration. Python 3.14 raises `SyntaxError` while importing the dependency. The same defect exists in releases 0.48.0 through 0.50.3. Release 0.47.0 is the newest wheel with valid UTF-8 source and successfully captures the reported FactorioLab URL.

Second, a placement can be flat-valid but band-specific. Freeform chooses tower seats, static packing, and Spray Coater placement before the authoritative spherical projection check. Search can therefore spend its routing budget on geometry that later fails `game.power_too_close`, `geom.collide`, or `game.addon_splitter_clearance`. The finalizer correctly refuses such geometry, but refusal is late and Freeform currently collapses structured failures to check names. A successful run does not remove the defect: nine repeats of the reported URL were clean, while the user's current-server report contained two projection-related Freeform refusals. The search can produce alternate geometry.

The current finalizer also certifies one selected band. Users need a stronger default: the blueprint must work in the smallest band it fits and the next two wider, equatorward bands. A small empty latitude margin is acceptable. If a common certification is impossible, users need an explicit CLI and web band selection rather than a silent single-band fallback.

## Goals

1. Make `--fetch-flow` work on the required Python 3.14 runtime.
2. Expose safe, explicit flow fetching in the web UI.
3. Make portable three-band certification the default placement contract.
4. Keep an explicit single-band escape hatch in CLI and web UI.
5. Move known projected legality into placement search so portability does not merely increase late refusals.
6. Preserve the finalizer as the authoritative defense-in-depth check.
7. Retain structured projection evidence through user-facing refusal reports.
8. Correct the false-positive termination warning for positional addon-supply belts.
9. Measure and report material finalization overhead before shipping it.
10. Route same-group product feedback required by a pinned steady-state flow.

## Non-goals

- Do not hide or reinterpret SequencePair deadline exhaustion.
- Do not merge multiple legitimate external input lanes. `flow.external_entry_points` remains a density/usability warning.
- Do not promise every latitude band on the planet. Portable mode covers the primary band and up to two wider bands.
- Do not allow the unauthenticated web API to navigate Chromium to arbitrary origins.
- Do not silently downgrade Portable mode to one band.
- Do not suppress projection checks or globally inflate unexplained flat clearances.
- Do not reinterpret FactorioLab CSV `Items` rows or capped Input objectives in this change. Gross/net cross-check ambiguity is diagnostic-only and separate from the layout refusal.

## Evidence and Root Causes

### Flow capture

The exact reported URL fails at `importlib.import_module("nodriver")`. Wheel inspection showed:

- 0.46.2 and 0.47.0: valid UTF-8;
- 0.48.0, 0.48.1, 0.50.1, 0.50.2, and 0.50.3: invalid byte `0xb1` in `nodriver/cdp/network.py`.

Using `nodriver==0.47.0`, the exact URL captured successfully as 10 CSV lines and 877 bytes. Pinning the last valid release is smaller and less risky than replacing the existing browser driver with a new CDP implementation in the same change.

### Self-consuming pinned flow

After successful capture, the exact refined-oil CSV still refused both layout strategies. The CSV provenance, recipe selection, and steady-state rates are valid: twenty `reforming-refine` Oil Refineries produce 15 refined oil/s, recycle 10/s as their own input, and deliver the requested net 5/s.

The shared strip planner deletes that physical feedback requirement. `_logical_strip_plans` records producer-to-consumer destinations only when `source != key`, so a group consuming its own product keeps an input lane but receives no output route back to it. Both strategies then emit four dry refined-oil input lanes and correctly fail `flow.lane_sourced`.

Removing only that guard is insufficient because `_nets_between` would emit `(i, i)` and CP-SAT would require a strip to be spatially separate from itself. The bounded fix is:

1. retain same-group destinations in `_logical_strip_plans`, so detailed routing sees the real feedback net;
2. omit only `i == j` from `_nets_between`, which is the packer's distance/separation proxy and not the detailed router's net list.

Runtime instrumentation with exactly those two changes produced clean 1,368-tile Freeform and SequencePair layouts at the existing 15-second budget, each with four internal feedback nets routed. Rate solving, flow pinning, validator semantics, and external input classification remain unchanged.

### Projection-related refusals

The reported non-deadline failures were:

- `freeform/all-products`: `game.addon_splitter_clearance`, `game.power_too_close`, `geom.collide`;
- `freeform/output-products`: `game.power_too_close`, `geom.collide`.

`_power_plan` accepts tower geometry using flat offsets. A diagonal pair can be legal on the flat grid and compress below DSP's 3.5-world-unit `PowerTooClose` gate after spherical projection. `_place_coaters` uses the ordinary body keepout but not the finalizer's additional projected Spray Coater/Splitter lateral keepout. Static bodies can likewise be flat-clear and overlap after projection. The finalizer detects all three correctly, but only after routing.

The proliferator `belt.termination` warning is separate. `_termination` considers sorter references to be taps, while Spray Coaters consume proliferator from a positional addon area without a sorter. A correctly supplied coater lane can therefore be called entirely wasted. The addon-area belt selected by the existing addon supply checks must also count as a tap.

## Public Contract

### Band selection

Introduce one public band selection value throughout CLI, pipeline, jobs, and TypeScript:

- `portable` — default; certify the smallest fitting band and the next two wider bands;
- one explicit terrestrial `area_segments` value: `4`, `8`, `16`, `20`, `32`, `40`, `60`, `80`, `100`, `120`, `160`, or `200`.

CLI:

```text
--band portable|4|8|16|20|32|40|60|80|100|120|160|200
```

Web UI:

```text
Latitude band: Portable (smallest + two wider) | 4 | 8 | ... | 200
```

The JSON request field is `band`, encoded as a string so the Python and TypeScript schemas have the same enum and no boolean/integer ambiguity.

An explicit band certifies only that band. If the final frame does not fit it or fails at any legal anchor, the build refuses with exact evidence.
Explicit mode uses the same minimum-area latitude-padding search, bounded to four added rows that still fit the requested band, but `certified_bands` contains only that band.

### Flow fetching

Add `fetch_flow: boolean`, default `false`, to Python `Options`, the TypeScript `BuildOptions` schema, `DEFAULT_OPTIONS`, and submitted JSON.

In a web request, `flow` and `fetch_flow` are mutually exclusive. The server rejects a request containing both. The UI disables automatic fetch while pasted/uploaded CSV text exists, and disables paste/upload controls while automatic fetch is selected.
The CLI retains its existing deliberate precedence: an explicit `--flow` file wins when `--fetch-flow` is also present. The unauthenticated web API rejects both because a checked control that is silently ignored would be misleading.

The web API accepts `fetch_flow: true` only when the URL has:

- scheme `https`;
- hostname `factoriolab.github.io`;
- no nonstandard port;
- path `/dsp/list` or `/dsp/flow`.

This closes the arbitrary top-level browser navigation identified in the existing web job documentation. CLI remains unrestricted because browser navigation is an explicit local command.
The web path passes this allowlist into capture. Capture verifies both the requested URL before launch and `location.href` after navigation; a redirect or main-frame navigation outside the allowlist refuses before any solve probe or click. CLI capture does not apply the web allowlist.

## Placement Data Model

Add an explicit immutable `AreaFrame` to finalized placements. It is the single source of truth for encoded area geometry:

```python
@dataclass(frozen=True, slots=True)
class AreaFrame:
    width: int
    height: int
    primary_band: int
    certified_bands: tuple[int, ...]
    rotated: bool
```

`Placement.frame` is `None` before finalization and populated afterward. Buildings in a finalized placement use frame-local coordinates and must lie entirely inside `[0, width) x [0, height)`. Empty latitude margins are represented by building `y` coordinates greater than zero and/or less than `height - footprint_height`; they are not inferred from building bounds.

The encoder reads `Placement.frame`, never `stats["area_segments"]`. All existing callers and tests migrate to the frame. Obsolete projection metadata in `PlacementStats` is removed rather than retained as a second source of truth.

`Placement.area` uses frame area after finalization so portability padding remains visible to candidate selection and reports. Before finalization it retains the building-bounds area used by layout search.

Any operation that changes finalized building coordinates or membership must clear the frame before recertification. Finalization is idempotent for an unchanged framed placement.

## Portable Band Invariant

For an unframed placement:

1. Consider both physical orientations.
2. Determine the globally smallest `area_segments` band `B0` in which the unpadded content fits.
3. Portable mode may use only orientations that fit `B0`; it must not move to a wider primary band to escape a failure.
4. Required bands are `B0` and the next two bands with greater `area_segments`. Near the equator, certify every remaining wider band, so `160` certifies `(160, 200)` and `200` certifies `(200,)`.
5. Search latitude padding in increasing emitted area:
   - total added rows from 0 through 4;
   - every split of those rows into south and north margins;
   - only frames that still fit `B0`.
6. For each frame, certify the same orientation, building coordinates, and frame at every legal anchor in every required band.
7. Select the first legal frame by `(frame area, added rows, rotation, south padding)`. This makes density loss deterministic and minimal.
8. If no frame passes, refuse. The refusal lists every required band that failed and preserves `(check, building indices, detail)`.

Only latitude padding is searched. A uniform longitude shift is a rotation around the planet and does not change relative projected geometry; longitude padding would add area without creating a new legality condition.

The four-row limit is the approved interpretation of “a few tiles.” It bounds both area loss and search work. It never permits padding that changes the smallest primary band. If a five-row polar band has no row slack, Portable mode must pass without padding or refuse.

## Projection-Aware Search

Finalization remains authoritative, but known deterministic failures move earlier.

### Power

Create one shared projected power-spacing predicate around `rules.power_node_condition`. Freeform's power candidate legality evaluates tower pairs against the current band policy's required projections. A pair illegal in any required band is never reserved. The existing finalizer uses the same predicate.

If the final extent is not known when an early power candidate is generated, evaluate it against the conservative frame/band envelope for the current packing extent. Do not replace the exact predicate with a larger flat radius.

### Spray Coater and Splitter

Extract the projected coater/Splitter lateral keepout into a shared helper. Coater and Splitter placement reserve/reject this region before routing. The finalizer repeats the check as defense in depth.

### Static projected collisions

Preserve the exact projected collision pair from `ProjectionRefusal.failures`. Freeform feeds that pair back into the next packing candidate as a pair-specific separation/no-good constraint. It must not blacklist an entire recipe candidate or add a blanket margin to every building.

Retries remain within the caller's existing layout budget. Exhaustion reports the repeated pair and target bands rather than only `geom.collide`.

### Refusal accounting

Freeform retains distinct structured failures instead of a `set[str]`. Its concise summary still lists checks, followed by band, building indices, and authoritative detail. SequencePair terminal refusal includes accumulated `StageObservation.validation_failures` so projection defects are not hidden behind a generic exhaustion message.

## Finalization and Encoding Flow

The resulting boundary is:

```text
URL/options
  -> rate candidates
  -> placement search using BandPolicy predicates
  -> route
  -> flat certification
  -> compact open boundary belts (clears any prior frame)
  -> portable/explicit frame search
  -> all-band, all-anchor projection certification
  -> AreaFrame attachment
  -> public validation
  -> encoding from AreaFrame
```

The finalizer checks, in order, projected power spacing, seated sorter legality, static OBB collisions, addon supply, and the special coater/Splitter keepout. Order affects diagnostics only; every accepted frame satisfies every check.

The result/report exposes `primary_band` and `certified_bands`. Portable output must never claim three bands when fewer were checked. Near-equator tuples of one or two bands are displayed literally.

## Warning Correction

Teach `_termination` that every belt selected by `_belt_in_addon_area` for a multi-area addon is a consumer tap. Dead belt length begins only after the last sorter or positional addon consumer. An otherwise identical proliferator lane with no sorter and no addon consumer still warns.

`flow.external_entry_points` is unchanged. Multiple external lanes are valid but require multiple player connections.

## Fetch-Flow Implementation

Pin `nodriver==0.47.0` in `pyproject.toml` and `uv.lock`. Add a regression that imports the installed dependency under Python 3.14; it fails against the current lock before any browser mock can hide the packaging defect.

`run_build()` passes `fetch_flow=options.fetch_flow` to `pipeline.build`. Fetch timeout remains the existing 90-second default; no new timeout control is added to the first web implementation.

The web checkbox label is `Fetch FactorioLab flow automatically`. Supporting text states that this launches a server-side browser, waits for FactorioLab's solve, and pins recipe selection. The unpinned result copy offers either automatic fetch or paste/upload instead of claiming fetch is unavailable.

The exact captured refined-oil flow must proceed through layout, not merely through CSV parsing. Same-group product destinations remain in logical strip plans. The packer excludes self edges from its spatial separation proxy, while `_prepare_routing_problem` retains them as detailed routing nets. A self-consuming product is not reclassified as an external input and its gross physical lane is not netted away.

## Performance Gate

Measure current and new finalization on the same frozen small, medium, and large placements. Report separately:

- finalization median and p95;
- end-to-end build wall time;
- number of frame candidates, projections, collider pairs, power pairs, and sorters evaluated;
- emitted area change.

A severe regression is either:

- more than 1 second added at p95; or
- more than 10% added to end-to-end wall time.

If either threshold is crossed, do not silently accept it. Profile and first cache work invariant across frame candidates:

- seated sorter reconstruction;
- power-node extraction;
- collision `Placed` records;
- per-band candidate pairs;
- projection objects for repeated `(band, frame height, anchor)` combinations.

Re-measure after caching. If the threshold still fails, report the measured tradeoff before changing the portability promise or padding limit.

## Test Strategy

Every behavior change follows red-green TDD.

### Flow fetch

- A Python 3.14 dependency-import regression fails with the current lock and passes with `nodriver==0.47.0`.
- `parse_options` defaults `fetch_flow` to false, rejects non-booleans, rejects `flow` plus `fetch_flow`, accepts the exact FactorioLab HTTPS origin, and rejects alternate schemes, hosts, ports, and paths.
- `run_build` passes the option through to `pipeline.build`.
- Frontend tests assert the checkbox default, submitted JSON, mutual exclusion, and disabled controls.
- The network-gated capture test uses the exact reported URL and asserts a non-empty provenance-valid flow.
- The exact captured refined-oil fixture produces one 20-refinery self-consuming pinned candidate with a real internal refined-oil feedback net.
- `_nets_between` excludes `(i, i)` without removing the corresponding detailed routing net.
- Fixed prepared geometry routes every feedback net and passes `flow.lane_sourced` without relying on a wall-clock CP-SAT outcome.

### Band policy and frame

- A synthetic placement legal in `B0` but illegal in `B1` fails the old single-band behavior and is rejected by Portable mode.
- A placement made portable by one or more empty latitude rows selects the minimum-area frame and encodes those dimensions.
- Portable mode never changes `B0` through padding or alternate wider-band selection.
- `160` certifies `(160, 200)`; `200` certifies `(200,)`.
- Explicit band selection certifies only the requested band and refuses an extent that does not fit.
- Encoder rejects unframed placements and framed placements whose buildings escape the frame.
- Finalization is idempotent for unchanged framed placements; coordinate/building mutations require recertification.

### Source refusal fixes

- Power planning rejects a flat-legal diagonal Tesla Tower pair that falls below 3.5 world units in a required projection.
- Coater/Splitter placement rejects the known projected lateral keepout before routing.
- A projected static-collision pair creates a pair-specific retry constraint and permits a known separated alternative.
- Freeform and SequencePair terminal refusals retain structured projection evidence.
- A proliferator belt feeding a coater addon area does not receive the all-lane-wasted warning; an unconsumed control lane does.

### Behavioral verification

- Focused Python tests for capture, web options/jobs, planet, finalization, Freeform, SequencePair, validation, and encoding.
- Full Python suite, Ruff, and mypy.
- Frontend tests, Biome lint, and TypeScript typecheck.
- Actual CLI smoke for Freeform and SequencePair in Portable mode and one explicit band.
- Browser-driven web verification of the fetch checkbox, band selector, mutual exclusion, progress, and reported certified bands.
- Network-gated exact-URL capture smoke.
- The exact refined-oil URL with its captured CSV completes a valid build; both strategies have focused self-feedback coverage.
- Performance comparison against the approved thresholds.

An unseeded repeated URL solve is diagnostic, not a regression test. Once an alternate failing placement/seed is captured, preserve it as a deterministic fixture.

## Failure Semantics

- Capture dependency/browser/network failure: build error; never re-derive silently.
- Portable certification failure: layout refusal naming bands and structured checks; never emit a single-band blueprint under a Portable label.
- Explicit band failure: layout refusal naming the requested band.
- Search deadline: unchanged deadline refusal.
- Valid blueprint with multiple external entry lanes: warning, unchanged.

## Migration

This is a clean cutover:

- every `pipeline.build` caller receives the default `band="portable"` behavior;
- CLI and web expose the same values;
- encoder and tests migrate from `stats["area_segments"]` to `Placement.frame`;
- obsolete stats projection fields and comments are removed;
- no aliases, deprecated option names, or hidden legacy single-band default remain.

## Risks

1. **More refusals before search becomes projection-aware.** Mitigated by implementing shared search predicates and pair feedback before making Portable the default.
2. **Frame semantics differ from the game.** Mitigated by encoder/decoder tests, the independent TypeScript decoder, the available C# oracle where applicable, and an actual DSP paste check when no automated game surface is available.
3. **Performance multiplication across bands and anchors.** Governed by the explicit performance gate and shared-work caches.
4. **Third-party pin ages.** The exact pin is deliberate and covered by import plus live capture tests. Upgrading requires proving the replacement wheel imports under Python 3.14.
5. **Web browser navigation exposure.** Restricted to the exact supported FactorioLab HTTPS origin and paths; pasted flow remains the network-free option.

## Acceptance Criteria

The change is complete only when:

1. The exact URL reaches browser capture without the current nodriver syntax error.
2. Its valid pinned self-consuming refined-oil flow routes its internal feedback and produces a valid layout rather than `flow.lane_sourced`.
3. The web UI can request automatic flow capture safely and truthfully.
4. Portable is the CLI, pipeline, and web default.
5. Every emitted Portable blueprint carries a real area frame certified at every anchor in its primary and up to two wider bands.
6. A non-portable placement refuses or succeeds under an explicitly selected band; it never silently downgrades.
7. The known power and coater/Splitter projection defects are constrained before routing, and static collision evidence feeds a targeted retry.
8. Structured projection details survive to reports.
9. Coater supply belts no longer trigger the false all-lane-wasted warning.
10. The performance gate passes, or the measured regression is returned for an explicit product decision before completion.
