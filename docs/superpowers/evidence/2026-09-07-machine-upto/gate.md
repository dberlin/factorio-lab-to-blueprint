# Machine ranking gate — execution pending

The resumed branch implements an opt-in `--machine-rank up-to`; `exact` remains
all CLI, Python, HTTP and UI defaults. FactorioLab recipe/flow choices remain
authoritative. This document is a reproducible handoff, **not a passing gate**.
No tests, formatters, builds, browser checks, probes or measurements were run in
the concurrent resume wave. Main owns execution after all lanes settle.

## Recovered authority and rulings

- Plan/spec: `docs/superpowers/plans/2026-09-07-machine-upto.md`.
- Base is `ad8a6f80`, pre-existing `machine-upto-base`; do not reset it.
- Batch A original range: `f037d206..6eb5f5a8`. Main's independent review found
  one Important: a catalog lookup returning `None` was admitted as placeable.
  Fix round 1: `6eb5f5a8..bc038dc7`. Main's independent scoped re-review
  **PASS/PASS**, no findings. Main's regression execution: pre-fix module selected
  unknown-smelter and exited 1; fixed module exited 0. Preserved logs:
  `.superpowers/sdd/2026-09-07-machine-upto/recovery-review-red.log` and
  `recovery-review-green.log`. New B–E execution remains pending.
- Ruling R4: pinned CSV recipes keep their exact machines, but report the requested
  mode. Attempt details carry their own mode/moves, so selecting a non-winning
  attempt never displays the winner's move provenance.
- Ruling R5: deterministic controls hash the complete encoded blueprint with only
  the creation timestamp fixed to zero. Both checkouts run the same external
  probe. A refused control has no digest and **cannot** prove byte identity;
  the known universe-matrix refusal must not be silently omitted.
- Ruling R6: preserve completed chunks and stop on a partial chunk, mixed SHA,
  stale provenance, or log without result. No hidden retry selects a better run.
- Ruling R7: F8's former shared git-config mutation is superseded; resumed review
  packages use explicit `--no-ext-diff`, with no shared configuration changes.
- D5 retained: absent machine rank still selects the recipe's first producer;
  no dataset-preset fallback was added.
- D6 retained: no unrelated Dark Fog footprint fix. Physical placed area is
  authoritative; rates-layer footprint aliases are not a measured gate substitute.

## Evidence prerequisites

Main must first complete independent reviews of B–E, the Batch A fix re-review,
scoped regressions, lint/type checks and browser/UI confirmation. Run long work
through supervised `hub start` processes, not the approximately 30-second tool
transport. Keep the host operating point recorded; no other audit may overlap.
Commit the tested candidate before measurement; all rows record its full SHA and
checkout import path. A changed candidate needs a fresh output directory, never
mixed evidence. Invoke the wrappers with `sh` (executable mode is unnecessary).

From the candidate worktree, use these shell variable bindings in the supervised
process environment (substitute the candidate path if Main integrates first):

```sh
ROOT=/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/machine-upto
BASE=/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/machine-upto-base
E=$ROOT/docs/superpowers/evidence/2026-09-07-machine-upto
```

### 1. Twelve single-worker exact controls

```sh
sh "$E/run_controls.sh" base "$BASE"
sh "$E/run_controls.sh" exact "$ROOT"
python3 "$E/compare_controls.py" "$E"
```

Requires twelve unique clean no-proliferator/freeform cells per arm, workers=1,
and all twelve complete blueprint digests equal. Preserve every refusal and
error. Paired refusals are status agreement, not a byte-identity PASS.

### 2. Full 72-cell base/exact/up-to rounds, serial

```sh
sh "$E/run_round.sh" base "$BASE"
sh "$E/run_round.sh" exact "$ROOT"
sh "$E/run_round.sh" up-to "$ROOT"
uv run python scripts/audit_compare.py "$E/base.jsonl" "$E/exact.jsonl" --expect-cells 72
uv run python scripts/audit_compare.py "$E/exact.jsonl" "$E/up-to.jsonl" --expect-cells 72
```

Each arm is the same 12 URLs × 3 policies × 2 placers, budget=30, jobs=8,
max-seconds=3600. The recipe chunks only by URL, retaining the original six-cell
policy/placer operating point and separate before/after runnable-load samples.
`base → exact` must preserve named statuses, with printed area ratio `1.0000`
(F7); controls provide the stronger byte claim. `exact → up-to` must introduce no
named regressions or new validation failures, no extra machines, and geometric
mean clean-pair area ratio ≤1.00. Record any refusal-to-CLEAN recovery. Never use
aggregate CLEAN counts to hide a differently named regression.

### 3. Reported antimatter URL, six exact/up-to pairs

```sh
sh "$E/run_reported.sh" exact "$ROOT"
sh "$E/run_reported.sh" up-to "$ROOT"
```

The complete inherited URL is embedded in `run_gate.py`; workers=32, budget=30,
all three policies and both placers. Preserve all twelve probe rows, full
certification findings, and blueprint text. Inspect the named pairs, not only
the best result. No lane mixing, belt cycle, or coater/run relaxation is allowed.

### 4. Moves, installed machine power, and 72-row table

```sh
uv run python "$E/moved.py" --out "$E/moved.jsonl" --layouts "$E"
```

The script asserts per-recipe counts, modes, inputs, outputs, and whole-spec
external/output/surplus rates remain identical; records both arms for all 36
policy/URL specs; and joins the complete base/exact/up-to layouts into a 72-row
Markdown table on stdout. Capture stdout as `moved-table.md` when executing.
Power is exact-Fraction installed machine nameplate usage in dataset kW, not
sorter/coater draw or measured factory consumption. Missing usage remains null
with machine IDs, never a fabricated zero. Record every recipe move and unchanged
count. Measured results and final gate ruling remain **PENDING**.

## Verification commands for Main

Run pytest groups separately: rates and hierarchy conftest fixtures collide if
combined. The user already reported pre-existing failures; preserve their names
rather than changing unrelated expectations.

```sh
uv run pytest tests/rates tests/lab -q
uv run pytest tests/layout/hierarchy/test_partition.py -q
uv run pytest tests/test_spec.py tests/test_pipeline.py tests/test_pipeline_cli_strategy.py tests/test_audit.py tests/scripts/test_audit.py tests/web -q
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src
npm --prefix web run typecheck
npm --prefix web test
npm --prefix web run build
```

Frontend commands above follow `web/package.json`. The Python proof
must include the unknown producer regression, exact/up-to count and flow equality,
pinned flow, extraction/zero-rate preservation, hierarchy fragments and HTTP
options/payloads. Browser proof must select both modes, submit, and inspect an
actual result plus a non-winning attempt's move details. Blueprint smoke proof
must exercise the production pipeline, full certification and description in
both modes, not only unit helper calls. Task 12 and every measurement/review task
remain incomplete until Main records their actual outputs and verdicts here.
