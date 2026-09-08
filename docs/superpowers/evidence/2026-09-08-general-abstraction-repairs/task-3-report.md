# Task3 implementation handoff

Status: canonical physical identity cutover implemented after Main confirmed baseline failures. Main green/cold smoke and independent review pending. This worker ran no validation or VCS commands.

## Authority and completed edits

`src/flab2bp/rates/adjust.py:machine_footprint` now directly resolves `catalog.building(catalog.item_id(machine_item_id))` and multiplies building width and height. No wrapper chain or parallel identity authority was added. Deleted `_NAME_ALIASES`, `_footprints_by_lab_id`, its `@cache`, its ambient `load_dataset`, and display-name matching. Unknown physical identity deliberately raises the catalog KeyError instead of silently contributing zero area.

The existing catalog owns known aliases (including `ray-receiver-pro`). Its own immutable data-loading/cache implementation remains unchanged. No deferred nested alias or machine override semantics were guessed.

## Source/reference inventory

Fresh LSP `references` for `machine_footprint` failed with `-32603: this._token.cancel is not a function` (tool issue reported). Complete scoped fallback search across src/tests/scripts found:

- Domain consumer: `AdjustedRecipe.footprint_area`.
- Public package export: `rates/__init__.py`; preserved because the domain operation remains, not as a compatibility shim.
- Direct tests: `tests/rates/test_adjust.py`, `tests/rates/test_candidates.py`.
- Removed private cache/alias references existed only in `rates/adjust.py`.
- Area consumers inspected in solve: `SolvedGroup.area`, `_default_objective`, continuous/lower-bound physical-area calculations.
- `_ExtractionColumn.footprint_area` remains the explicit zero override for mining/pumping/collection outside the blueprint.
- `_objective_coefficients` uses Dataset `machine.size` for FactorioLab economic costs, not catalog geometry. No arithmetic or economic-cost source changed. `tests/lab/test_machine_size.py` intentionally unchanged.

## Staged regressions/probe

- `tests/rates/test_adjust.py::test_machine_footprint_uses_identity_not_display_labels`: renamed labels, unchanged IDs, real recipe adjustment.
- `test_machine_footprint_resolves_catalog_alias`: existing receiver variant maps to the same positive physical footprint.
- `test_unknown_physical_machine_footprint_is_refused`: physical recipe with unknown identity raises deliberately.
- `tests/rates/test_solve.py::test_physical_area_ignores_machine_display_labels`: real solved one-smelter factory retains total/lower-bound area 9 and exact rates under renamed labels.
- `test_extraction_has_zero_area_without_a_physical_machine`: real mining column construction with explicitly unplaced identity retains zero-area semantics.
- Throwaway `task-3-footprint-probe.py` in this SDD workspace computes a real adjusted smelter's area in a cold process. `renamed` substitutes an ambient renamed-label dataset; `unavailable` makes ambient loading fail. Both still supply the ordinary dataset to recipe arithmetic.

## Baseline evidence (Main executed)

- `request-identity-red.log`: unknown physical identity DID NOT RAISE; renamed-column and catalog-alias controls passed (these alone do not expose the ambient cache defect).
- `task-3-renamed-red.log`: cold canonical arc-smelter area was 0 instead of 9.
- `task-3-unavailable-red.log`: old `adjust.py:180` invoked ambient loading and raised the probe AssertionError.

Main released source mutation only after those failures were retained. No unchanged baseline was rerun by this worker.

## Exact Main proof commands

From this worktree root:

```sh
uv run pytest -q tests/rates/test_adjust.py tests/rates/test_solve.py tests/lab/test_machine_size.py -k 'footprint or area or extraction or size' --tb=short
uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-3-footprint-probe.py renamed
uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-3-footprint-probe.py unavailable
```

Both cold probes must print canonical arc-smelter area 9. They are instrumentation, not permanent call-count tests. Main should remove the throwaway script after retaining green output, then perform independent review and integration/commit. No green or runtime success is claimed by this handoff.

## Main-approved identity-owner reconciliation after first green attempt

Main's first settled selected batch failed the existing all-machines consumer: raw `df-negentropy-smelter` now reached catalog lookup but was unresolved. `request-green.log` retains that failure; it is not waved away by narrowing the test to a canonicalized dataset.

Main explicitly approved expanding this task to `src/flab2bp/dsp/catalog.py`, `src/flab2bp/lab/flow.py` and `tests/dsp/test_catalog.py`. The existing shallow `canonical_item_id`, `canonical_recipe_id`, and their one shared `_OBSERVED_ITEM_ALIASES` table moved from Flow to catalog. Both normalization operations keep their independent catalog-membership guards and original spelling/prefix semantics. Flow's internal callers now qualify the catalog operations; its obsolete exports and declarations are removed without compatibility re-exports. Catalog `item_id` and `get_item_id` consume the item policy; its membership guard reads the raw cached item index to avoid recursion. Recipe lookup itself, deeper alias merging, request override precedence and collision semantics are unchanged.

Pre-edit inventory found no external callers of the two moved functions in src/tests/scripts: all references were Flow internals. Fresh LSP attempts for both owner/reference seams continued to fail with the same cancellation error, so that scoped fallback inventory governed the migration. Flow already imports catalog; catalog imports no lab/rates owner, so the move introduces no rates-to-Flow dependency or cycle.

Read-only JSON inventory identified 52 machine records, including 13 raw DF physical aliases. Existing shallow policy plus catalog assets identify production buildings 2318 (Re-composing Assembler), 2319 (Negentropy Smelter), 2902 (Self-evolution Lab), and combat buildings 3001–3010. No second alias table was added. The all-machines regression remains unchanged and covers those raw identities.

Added consumer coverage in `tests/dsp/test_catalog.py` extends numeric alias normalization across raw DF production/combat IDs, resolves actual physical geometry, and checks that a known item (critical photon) does not become a crafting recipe merely because its item identity is known. Unknown/future IDs remain distinct and unknown physical lookup still fails deliberately.

Additional Main command after reconciliation:

```sh
uv run pytest -q tests/dsp/test_catalog.py tests/lab/test_flow.py tests/rates/test_adjust.py -k 'alias or canonical or footprint or supplied' --tb=short
```

Reconciliation green, cold probes, independent review and cleanup of the throwaway probe remain pending Main. No self-validation was run.
