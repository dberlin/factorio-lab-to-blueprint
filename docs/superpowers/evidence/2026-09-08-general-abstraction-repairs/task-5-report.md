# Task5 — lossless audit comparison identity

Status: implementation and matching regressions pass Main's persisted actual comparator CLI probe and integrated/focused module proof. `task-5-identity-green-r2` preserves reordered/commit-only controls pairing two semantic budgets at ratio 1; duplicate, missing-budget, and undeclared label/rank/tower changes fail explicitly. The exact-first correction is green and independently approved in AuditLifetimeScopedReview; this worker ran no validation.

## Owner and compatible consumers

New `src/flab2bp/bench/identity.py` owns frozen/slotted `AuditCellKey(strategy, url_id, spec_index, spec_label, budget, power)`, typed `AuditCellRow` including required machine_rank/power_tower metadata, and duplicate-rejecting `index_audit_cells`. Missing, unknown or malformed exact identity is refused rather than defaulted. The original row is retained so consumers keep their metrics.

`pair_audit_cells` checks configuration separately. Explicit `treatment_fields` can name candidate label, machine rank, tower, route backend, coater arm or arrangements; omitted declarations never hide changes. Candidate-label treatment pairs the same candidate slot while retaining both actual semantic keys and refusing ambiguous slots. Commits are provenance, never pairing keys or incompatible configuration. Optional configuration present on only one side is insufficient evidence, not an invented value.

- `scripts/audit_compare.py`: no weaker three-field key or last-row overwrite; both sides indexed before any counts, ratios or verdict. Missing/unpaired cells fail, and only an observed REFUSED result can be carried in regression-only mode. TERMINATED, NOT_RUN and SPEC never become a successful gate. Actual CLI adds repeatable `--treatment` with explicit supported choices and reports identity failure before numeric scoring.
- `scripts/benchmark_projection.py`: shares exact audit indexing and configuration compatibility only; existing projection timing/atomic-grace/scoring contracts remain intact. Duplicate and scope checks no longer have a competing key implementation.
- `scripts/audit.py`: existing required identity fields remain emitted; arrangements is explicit treatment metadata, and duplicate selected jobs are refused rather than run and later overwritten.
- `bench.ab.compare`: rejects mixed power within the selected URL/strategy/budget scope. Its separate sample/trial reduction and scoring engine remain unchanged.
- Legacy `bench.regression` per-URL scope, promotion sample schema, and old evidence files are intentionally unchanged; old evidence missing required audit fields cannot silently qualify as an exact gate.

## Main baseline evidence

Main executed `task-5-identity-probe.py` against the pre-cutover comparator, preserving `task-5-identity-red.log` and every generated JSONL/log. EXIT1 was the probe's expected disagreement assertion, not evidence that identity validation existed:

- Reordered 4/30-second rows incorrectly produced geometric area ratio 2 instead of 1.
- The commit-only control failed the same numeric gate rather than pairing both budgets correctly.
- Duplicate identity was credited as two paired cells, with ratio 4, instead of being rejected before scoring.
- Changed label/tower/rank and missing-budget cases failed only the incidental numeric gate, not explicit identity/configuration incompatibility.

## Tests and exact Main commands

```sh
PYTHONPATH=src:. uv run python .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-5-identity-probe.py .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-5-identity-green
uv run pytest -q tests/scripts/test_audit_compare.py tests/scripts/test_benchmark_projection.py tests/bench/test_ab.py --tb=short
```

The probe directory must be new. It invokes the actual comparator CLI for each persisted file and prints semantic budget/area pairs; do not overwrite its red directory.

Explicit treatment CLI controls using the new green fixture directory:

```sh
uv run python scripts/audit_compare.py .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-5-identity-green/baseline.jsonl .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-5-identity-green/label.jsonl --expect-cells 2 --treatment spec_label
uv run python scripts/audit_compare.py .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-5-identity-green/baseline.jsonl .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-5-identity-green/tower.jsonl --expect-cells 2 --treatment power_tower
uv run python scripts/audit_compare.py .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-5-identity-green/baseline.jsonl .superpowers/sdd/2026-09-08-general-abstraction-repairs/task-5-identity-green/rank.jsonl --expect-cells 2 --treatment machine_rank
```

Each same-scope or explicitly declared treatment control must pair both semantic budgets and ratio 1; missing identities and duplicates must fail before counts. Projection tests retain its established scoring boundary and add rank/tower incompatibility. AB tests exercise mixed-power rejection rather than a source/import assertion. LSP references failed with the known cancellation error; scoped src/tests/scripts fallback inventory governed the cutover.

Main confirmed the persisted CLI probe behavior described above. Its earlier 12-second outer identity-probe cap was an orchestration mistake, not source failure; that evidence remains untouched. Main's integrated 351-case audit/trace run passed 350 cases; only an obsolete exact diagnostic wording assertion failed. Main removed that assertion while retaining the missing-cell failing-verdict contract, then passed 32 focused cases including the complete audit comparator module. Main owns remaining integration-wide proof, probe cleanup and commit.

## Exact-key review correction

The first pairing implementation over-rejected distinct complete keys when their label-neutral slot happened to match. Main ran `test_distinct_full_keys_share_a_slot_without_becoming_duplicates` and retained `task-5-exact-slot-red.log`: the sprayed full key incorrectly raised incompatible-slot ValueError.

After Main released that correction, pairing now reserves every exact key first. Only unresolved label-treatment/mismatch cases build label-neutral choices, and ambiguous choices still fail rather than guessing. Added consumer controls cover distinct exact keys in reversed order, one exact peer beside an explicitly renamed peer, and ambiguous unresolved treatment. The earlier scope, missing-field and exact-duplicate controls remain unchanged. Main's integrated/focused module run passed these controls; AuditLifetimeScopedReview explicitly approved the exact-first correction, including reserved exact peers, unresolved ambiguity rejection and metadata checks. Earlier CLI greens are not substituted for this later edge proof.
