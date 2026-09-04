# Gate R0 — sequence-pair receiver evidence

## Provenance

Branch-point implementation commit: `891d09e`

The existing native extensions were inspected without rebuilding by running:

```bash
uv run python - <<'PY'
from flab2bp.layout import route_kernel, sequence_kernel
print("route_selected", route_kernel.selected_backend())
print("route_compiled_available", route_kernel.compiled_available())
print("sequence_compiled_available", sequence_kernel.compiled_backend_available())
PY
```

Observed:

```text
route_selected cython
route_compiled_available True
sequence_compiled_available True
```

## Audit rounds

Before each audit, `uptime` and `vmstat 1 3` were appended to `r0-load.txt`. The audit exit code was accepted only when it was 0 or 1, and each output was checked for exactly three JSONL rows.

Round 1:

```bash
uv run python scripts/audit.py --budget 30 --jobs 3 --max-seconds 180 --only universe-matrix --strategy sequence-pair --json "docs/superpowers/evidence/2026-09-04-phase-e-residual-closure/r0-sequence-round1.jsonl"
```

Accepted exit code: `1`; JSONL rows: `3`.

Round 2:

```bash
uv run python scripts/audit.py --budget 30 --jobs 3 --max-seconds 180 --only universe-matrix --strategy sequence-pair --json "docs/superpowers/evidence/2026-09-04-phase-e-residual-closure/r0-sequence-round2.jsonl"
```

Accepted exit code: `1`; JSONL rows: `3`.

Round 3:

```bash
uv run python scripts/audit.py --budget 30 --jobs 3 --max-seconds 180 --only universe-matrix --strategy sequence-pair --json "docs/superpowers/evidence/2026-09-04-phase-e-residual-closure/r0-sequence-round3.jsonl"
```

Accepted exit code: `1`; JSONL rows: `3`.

## Extracted no-proliferator rows

| Round | status | seconds | stages | best_stranded | best_overflow | route_backend | accelerator | relation_no_goods_produced | relation_no_goods_unique | relation_no_goods_repeated |
|---:|---|---:|---:|---:|---:|---|---|---:|---:|---:|
| 1 | REFUSED | 25.610740717034787 | 5.0 | 2.0 | 8.0 | cython | cython | 0.0 | 0.0 | 0.0 |
| 2 | REFUSED | 24.978468051180243 | 5.0 | 2.0 | 8.0 | cython | cython | 0.0 | 0.0 | 0.0 |
| 3 | REFUSED | 25.357717132894322 | 5.0 | 2.0 | 8.0 | cython | cython | 0.0 | 0.0 | 0.0 |

Across all nine rows: `INVALID=0`; `CRASH=0`.

## Invariant evaluation

- `relation_no_goods_produced >= 1` in every target round: **FAIL** — rounds 1, 2, and 3 each reported `0.0`.
- `relation_no_goods_unique >= 1` in every target round: **FAIL** — rounds 1, 2, and 3 each reported `0.0`.
- `relation_no_goods_repeated >= 1` in every target round: **FAIL** — rounds 1, 2, and 3 each reported `0.0`.
- `stats.route_backend == "cython"` and `stats.accelerator == "cython"` in every target round: **PASS** — both fields were `cython` in all three rounds.
- `stages >= 4` unless CLEAN: **PASS** — all target rows were REFUSED with `stages=5.0`.
- No INVALID or CRASH row among all nine rows: **PASS** — both counts were zero.

All backend, stage, and validity checks pass, while every target round has zero produced and zero repeated proofs. The mechanical Gate R0 outcome is therefore SKIP.

R0: SKIP — receiver evidence absent
