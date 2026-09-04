# Evaluation Throughput Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one candidate evaluation on the largest corpus cells cheap enough that both production strategies clear the whole 72-cell corpus at a 30-second budget with no area regression, without changing what any evaluation concludes.

**Architecture:** Two halves gated by one profiler. Preparation: remove repeated exact-projection work from `_prepare_routing_problem` and strip planning by reordering cheap filters ahead of expensive materialization, sharing pure offset caches process-wide, and sharing the attempt-local staged-static cache across candidates and strategies for one spec. Routing: move the A* inner loop and the relaxed global search into a Cython extension over the existing flat-integer grid, selected the way the sequence kernel selects its backend, with the Python loops kept as the fallback and the oracle.

**Tech Stack:** Python 3.14, Cython 3.1.3 via setuptools (existing `setup.py`), `array` module buffers, pytest, cProfile, Ruff, strict MyPy, `uv run`.

**Spec:** `docs/superpowers/specs/2026-09-01-evaluation-throughput-design.md`

## Global Constraints

- No change to the compact seed share, expansion budgets (`_MAX_EXPANSIONS = 200_000`, `_ROUTING_BUDGET = 2_000_000`), stage caps, or restart schedules.
- No change to strip variants, pitches, junction geometry, coater seating rules, or power coverage rules.
- No new search operator, no-good, or acceptance rule.
- No cross-process or on-disk cache. Memo state lives in one process and dies with it.
- No Rust, C++, Numba, or JAX. Cython is the one compiled toolchain.
- No change to CLI, web, or pipeline interfaces.
- Every prepared problem, path, expansion count, and refusal reason identical to the Python implementation on the same inputs.
- Each task is a separate commit that leaves the tree green: `uv run pytest -q`, `uv run ruff check .`, `uv run mypy` (no new diagnostic against the locked baseline).
- Run the full test suite from the repo root with `uv run pytest -q` (serial; never `-n auto`, CP-SAT already saturates the box).
- Build the extensions before testing kernel tasks: `uv run python setup.py build_ext --inplace`.
- Corpus gate: `scripts/audit.py --budget 30 --jobs 16`, both strategies, three rounds: 72/72 CLEAN in every round, INVALID 0, CRASH 0, wall p95 per cell at or under 30 s, paired area over cells clean in both arms no worse than the baseline beyond the same-arm noise floor.
- Evidence files are tracked under `docs/superpowers/evidence/2026-09-01-evaluation-throughput/`. The `.superpowers/sdd/` workspace is git-ignored and holds only task briefs and reports.
- Commit messages: imperative, sentence case, no trailing period, e.g. `perf(layout): share junction ban offsets across attempts`.
- A step whose measurement misses its stated goal is not committed as if it passed: record the numbers and report.
- **Work in flight on 2026-09-01.** The main checkout carries an uncommitted boundary-routing rewrite (routing requested outputs to the block boundary) touching `_prepare_routing_problem`, `_route_all`, `_build_prepared`, `_commit_paths`, `_PreparedRoutingProblem`, `_RoutingWorkspace`, `_route_external_inputs` (split into `_route_boundary_nets`, `_route_external_inputs`, `_route_external_outputs`), `sequence_solver._production_run`, `_variant_search_inputs`, and `finalize.compact_open_boundary_belts_certified`. Do not start this plan until that work has landed on master. Create this plan's worktree from that master. Every `file:line` reference below was taken at commit 4c09a85 and is a hint only: resolve each target by symbol name (Serena `find_symbol`) before editing.
- Baselines are generated on the same master the plan starts from, never copied from `/tmp` files produced before the in-flight work landed.

---

### Task 1: Baseline evidence and the paired audit comparison

**Files:**
- Create: `docs/superpowers/evidence/2026-09-01-evaluation-throughput/baseline-budget30.jsonl`
- Create: `docs/superpowers/evidence/2026-09-01-evaluation-throughput/baseline-budget15.jsonl`
- Create: `scripts/audit_compare.py`
- Test: `tests/scripts/test_audit_compare.py`

**Interfaces:**
- Consumes: `scripts/audit.py --json PATH` JSONL rows with keys `strategy`, `url_id`, `spec_index`, `spec_label`, `power`, `budget`, `status`, `area`, `seconds`, `detail`.
- Produces: `audit_compare.compare(baseline_rows, candidate_rows, *, noise_area, p95_seconds) -> Verdict` and the CLI `uv run python scripts/audit_compare.py BASELINE.jsonl CANDIDATE.jsonl [--noise-area 0.013] [--p95-seconds 30]`. Later tasks call the CLI as the gate.

- [ ] **Step 1: Generate the baselines on the starting master**

```bash
git log --oneline -1   # record this hash in the commit message: it is the baseline commit
mkdir -p docs/superpowers/evidence/2026-09-01-evaluation-throughput
uv run python scripts/audit.py --budget 30 --jobs 16 --json docs/superpowers/evidence/2026-09-01-evaluation-throughput/baseline-budget30.jsonl | tail -4
uv run python scripts/audit.py --budget 15 --jobs 16 --json docs/superpowers/evidence/2026-09-01-evaluation-throughput/baseline-budget15.jsonl | tail -4
wc -l docs/superpowers/evidence/2026-09-01-evaluation-throughput/*.jsonl
```

Expected: 72 lines in each file, about 3 minutes each. Record each run's clean count in the commit message. The pre-in-flight figures (freeform 36/36 and sequence-pair 32/36 at 30 s; 63/72 at 15 s) are the reference; if the new baseline differs by more than two cells, say so in the commit message and continue, the gate compares against this file.

- [ ] **Step 2: Write the failing tests for the comparison**

```python
# tests/scripts/test_audit_compare.py
from __future__ import annotations

import json
from pathlib import Path

from scripts import audit_compare


def _row(
    strategy: str, url_id: str, spec_index: int, status: str, area: float, seconds: float
) -> dict[str, object]:
    return {
        "strategy": strategy,
        "url_id": url_id,
        "spec_index": spec_index,
        "spec_label": f"label-{spec_index}",
        "power": True,
        "budget": 30.0,
        "status": status,
        "area": area,
        "seconds": seconds,
        "detail": "",
    }


def test_compare_pairs_cells_and_reports_area_ratio() -> None:
    baseline = [
        _row("freeform", "plastic", 0, "CLEAN", 100.0, 5.0),
        _row("freeform", "plastic", 1, "CLEAN", 200.0, 6.0),
        _row("sequence-pair", "plastic", 0, "REFUSED", 0.0, 30.0),
    ]
    candidate = [
        _row("freeform", "plastic", 0, "CLEAN", 101.0, 2.0),
        _row("freeform", "plastic", 1, "CLEAN", 190.0, 3.0),
        _row("sequence-pair", "plastic", 0, "CLEAN", 150.0, 12.0),
    ]

    verdict = audit_compare.compare(baseline, candidate, noise_area=0.013, p95_seconds=30.0)

    assert verdict.candidate_clean == 3
    assert verdict.candidate_refused == 0
    assert verdict.candidate_invalid == 0
    assert verdict.candidate_crashed == 0
    assert verdict.paired_cells == 2
    # geometric mean of 101/100 and 190/200
    assert abs(verdict.area_ratio - ((1.01 * 0.95) ** 0.5)) < 1e-9
    assert verdict.p95_seconds == 12.0
    assert verdict.passed


def test_compare_fails_on_refusal_invalid_or_area_regression() -> None:
    baseline = [_row("freeform", "plastic", 0, "CLEAN", 100.0, 5.0)]

    refused = audit_compare.compare(
        baseline,
        [_row("freeform", "plastic", 0, "REFUSED", 0.0, 30.0)],
        noise_area=0.013,
        p95_seconds=30.0,
    )
    assert not refused.passed
    assert "REFUSED" in refused.reasons[0]

    invalid = audit_compare.compare(
        baseline,
        [_row("freeform", "plastic", 0, "INVALID", 90.0, 5.0)],
        noise_area=0.013,
        p95_seconds=30.0,
    )
    assert not invalid.passed

    larger = audit_compare.compare(
        baseline,
        [_row("freeform", "plastic", 0, "CLEAN", 102.0, 5.0)],
        noise_area=0.013,
        p95_seconds=30.0,
    )
    assert not larger.passed
    assert "area" in larger.reasons[0]

    slow = audit_compare.compare(
        baseline,
        [_row("freeform", "plastic", 0, "CLEAN", 100.0, 31.0)],
        noise_area=0.013,
        p95_seconds=30.0,
    )
    assert not slow.passed
    assert "p95" in slow.reasons[0]


def test_cli_reads_jsonl_and_exits_nonzero_on_failure(tmp_path: Path) -> None:
    baseline = tmp_path / "base.jsonl"
    candidate = tmp_path / "cand.jsonl"
    baseline.write_text(json.dumps(_row("freeform", "plastic", 0, "CLEAN", 100.0, 5.0)) + "\n")
    candidate.write_text(json.dumps(_row("freeform", "plastic", 0, "REFUSED", 0.0, 30.0)) + "\n")

    assert audit_compare.main([str(baseline), str(candidate)]) == 1

    candidate.write_text(json.dumps(_row("freeform", "plastic", 0, "CLEAN", 100.0, 5.0)) + "\n")
    assert audit_compare.main([str(baseline), str(candidate)]) == 0
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/scripts/test_audit_compare.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.audit_compare'`

- [ ] **Step 4: Write the comparison script**

```python
# scripts/audit_compare.py
"""Compare one audit JSONL against a committed baseline, paired by cell.

    uv run python scripts/audit_compare.py BASELINE.jsonl CANDIDATE.jsonl

A cell is ``(strategy, url_id, spec_index)``.  The verdict passes only when
the candidate has zero REFUSED / INVALID / CRASH rows, its p95 wall per cell
is at or under ``--p95-seconds``, and the geometric mean area ratio over cells
clean in BOTH files is at most ``1 + noise_area``.  ``--noise-area`` defaults
to the 1.3% same-arm median measured in ``docs/BACKLOG.md``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

CellKey = tuple[str, str, int]


@dataclass(frozen=True)
class Verdict:
    candidate_clean: int
    candidate_refused: int
    candidate_invalid: int
    candidate_crashed: int
    paired_cells: int
    area_ratio: float
    p95_seconds: float
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return not self.reasons


def _key(row: Mapping[str, object]) -> CellKey:
    return (str(row["strategy"]), str(row["url_id"]), int(str(row["spec_index"])))


def _p95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[max(index, 0)]


def compare(
    baseline: Iterable[Mapping[str, object]],
    candidate: Iterable[Mapping[str, object]],
    *,
    noise_area: float,
    p95_seconds: float,
) -> Verdict:
    base_by_key = {_key(row): row for row in baseline}
    counts: dict[str, int] = {}
    reasons: list[str] = []
    log_ratios: list[float] = []
    seconds: list[float] = []
    for row in candidate:
        status = str(row["status"])
        counts[status] = counts.get(status, 0) + 1
        seconds.append(float(str(row["seconds"])))
        if status != "CLEAN":
            reasons.append(
                f"{status}: {row['strategy']} {row['url_id']}/{row['spec_label']}: {row['detail']}"
            )
            continue
        base = base_by_key.get(_key(row))
        if base is None or str(base["status"]) != "CLEAN":
            continue
        base_area = float(str(base["area"]))
        cand_area = float(str(row["area"]))
        if base_area > 0 and cand_area > 0:
            log_ratios.append(math.log(cand_area / base_area))
    ratio = math.exp(sum(log_ratios) / len(log_ratios)) if log_ratios else 1.0
    p95 = _p95(seconds)
    if ratio > 1.0 + noise_area:
        reasons.append(f"area ratio {ratio:.4f} exceeds 1 + {noise_area}")
    if p95 > p95_seconds:
        reasons.append(f"p95 wall {p95:.1f}s exceeds {p95_seconds}s")
    return Verdict(
        candidate_clean=counts.get("CLEAN", 0),
        candidate_refused=counts.get("REFUSED", 0),
        candidate_invalid=counts.get("INVALID", 0),
        candidate_crashed=counts.get("CRASH", 0),
        paired_cells=len(log_ratios),
        area_ratio=ratio,
        p95_seconds=p95,
        reasons=tuple(reasons),
    )


def _read(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("baseline", type=Path)
    ap.add_argument("candidate", type=Path)
    ap.add_argument("--noise-area", type=float, default=0.013)
    ap.add_argument("--p95-seconds", type=float, default=30.0)
    args = ap.parse_args(argv)
    verdict = compare(
        _read(args.baseline),
        _read(args.candidate),
        noise_area=args.noise_area,
        p95_seconds=args.p95_seconds,
    )
    print(
        f"clean {verdict.candidate_clean}  refused {verdict.candidate_refused}  "
        f"invalid {verdict.candidate_invalid}  crashed {verdict.candidate_crashed}  "
        f"paired {verdict.paired_cells}  area ratio {verdict.area_ratio:.4f}  "
        f"p95 {verdict.p95_seconds:.1f}s"
    )
    for reason in verdict.reasons:
        print(f"  FAIL {reason}")
    print("PASS" if verdict.passed else "FAIL")
    return 0 if verdict.passed else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/scripts/test_audit_compare.py -v`
Expected: 3 passed

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check scripts/audit_compare.py tests/scripts/test_audit_compare.py
uv run mypy scripts/audit_compare.py tests/scripts/test_audit_compare.py
git add docs/superpowers/evidence/2026-09-01-evaluation-throughput scripts/audit_compare.py tests/scripts/test_audit_compare.py
git commit -m "bench: add paired audit comparison and 30s baseline evidence"
```

---

### Task 2: Profiler split for preparation and planning

**Files:**
- Modify: `scripts/route_profile.py:94-111` (`Tally`), `scripts/route_profile.py:114-310` (`install`), `scripts/route_profile.py:398-519` (`main`)
- Modify: `tests/bench/test_route_profile.py:35-92`
- Create: `docs/superpowers/evidence/2026-09-01-evaluation-throughput/profile-before.jsonl`

**Interfaces:**
- Consumes: module attributes `freeform._prepare_routing_problem`, `freeform._place_coaters`, `freeform._projected_coater_junction_bans_by_frame`, `freeform._prepared_junction_ban`, `freeform._power_plan`, `freeform._staged_static_relation_projection_risks_uncached`, `freeform.plan_strips`, `freeform.generate_strip_families`, `global_router._search_relaxed`, `finalize.finalize_placement`, `validate.validate`.
- Produces: JSON field `"phases": {name: {"s": seconds, "n": calls}}` for the names `prepare`, `place_coaters`, `coater_frame_bans`, `junction_ban`, `power_plan`, `static_risks`, `plan_strips`, `strip_families`, `relaxed_search`, `finalize`, `validate`; plus `"prepare_calls_s": [seconds per call in order]`. All existing fields unchanged.

- [ ] **Step 1: Extend the JSON schema test**

In `tests/bench/test_route_profile.py`, inside `test_json_profile_emits_one_bounded_machine_readable_record`, change the tally setup to:

```python
    tally = route_profile.Tally()
    tally.t = {"route_all": 4.0, "astar": 1.25, "prepare": 2.5, "plan_strips": 0.5}
    tally.n = {"route_all": 1, "astar": 3, "prepare": 2, "plan_strips": 1}
    tally.prepare_calls = [2.0, 0.5]
    tally.expansions = 123
    tally.astar_hit = 2
    tally.astar_none = 1
```

and extend the expected dict with:

```python
        "phases": {
            "prepare": {"s": 2.5, "n": 2},
            "plan_strips": {"s": 0.5, "n": 1},
        },
        "prepare_calls_s": [2.0, 0.5],
```

Add a second test that the shims are installed and restored:

```python
def test_install_wraps_preparation_phases_and_restores() -> None:
    tally = route_profile.Tally()
    original = freeform._prepared_junction_ban
    restore = route_profile.install(tally)
    try:
        assert freeform._prepared_junction_ban is not original
        freeform._prepared_junction_ban((), ())
    finally:
        restore()
    assert freeform._prepared_junction_ban is original
    assert tally.n["junction_ban"] == 1
    assert tally.t["junction_ban"] >= 0.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/bench/test_route_profile.py -v`
Expected: the JSON test FAILS on the missing `phases` key; the install test FAILS with `KeyError: 'junction_ban'`.

- [ ] **Step 3: Add the phase shims and fields**

In `Tally.__init__` add:

```python
        #: Seconds per `_prepare_routing_problem` call, in call order, so a
        #: cold first candidate and a warm second one are both visible.
        self.prepare_calls: list[float] = []
```

At the top of the script, beside the existing `freeform` import, add:

```python
from flab2bp.layout import finalize, global_router, validate
```

In `install`, after the existing shims and before `freeform._astar = astar`, add a generic timing wrapper and apply it:

```python
def timed(target: str, key: str, module: object) -> Callable[[], None]:
    original = getattr(module, target)

    def shim(*args: object, **kwargs: object) -> object:
        t0 = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            dt = time.perf_counter() - t0
            tally.add(key, dt)
            if key == "prepare":
                tally.prepare_calls.append(dt)

    setattr(module, target, shim)

    def undo() -> None:
        setattr(module, target, original)

    return undo


phase_undo = [
    timed("_prepare_routing_problem", "prepare", freeform),
    timed("_place_coaters", "place_coaters", freeform),
    timed("_projected_coater_junction_bans_by_frame", "coater_frame_bans", freeform),
    timed("_prepared_junction_ban", "junction_ban", freeform),
    timed("_power_plan", "power_plan", freeform),
    timed("_staged_static_relation_projection_risks_uncached", "static_risks", freeform),
    timed("plan_strips", "plan_strips", freeform),
    timed("generate_strip_families", "strip_families", freeform),
    timed("_search_relaxed", "relaxed_search", global_router),
    timed("finalize_placement", "finalize", finalize),
    timed("validate", "validate", validate),
]
```

In `restore()`, add `for undo in phase_undo: undo()`.

Define the phase name tuple once at module level:

```python
PHASES = (
    "plan_strips",
    "strip_families",
    "prepare",
    "place_coaters",
    "coater_frame_bans",
    "junction_ban",
    "power_plan",
    "static_risks",
    "relaxed_search",
    "finalize",
    "validate",
)
```

In `main`, inside the `if args.json:` dict, add:

```python
                "phases": {
                    key: {"s": tally.t[key], "n": tally.n[key]}
                    for key in PHASES
                    if key in tally.t
                },
                "prepare_calls_s": list(tally.prepare_calls),
```

In the human-readable branch, after the `_route_all` breakdown loop, print the same phases:

```python
for key in PHASES:
    if key in tally.t:
        print(
            f"      {key:<22} {tally.t[key]:7.2f}s  n={tally.n[key]:<7} "
            f"{100 * tally.t[key] / max(wall, 1e-9):5.1f}% of wall"
        )
if tally.prepare_calls:
    print("      prepare per call: " + ", ".join(f"{s:.2f}" for s in tally.prepare_calls))
```

`plan_strips` looks `generate_strip_families` up in the `freeform` module globals at call time (`tuple(generate_strip_families(spec)) if families is None else ...`), so the `strip_families` shim sees those calls.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/bench/test_route_profile.py tests/scripts/test_route_profile.py -v`
Expected: all pass

- [ ] **Step 5: Record the pre-change profile**

```bash
out=docs/superpowers/evidence/2026-09-01-evaluation-throughput/profile-before.jsonl
: > "$out"
for policy in no-proliferator all-products output-products; do
  for strategy in freeform sequence-pair; do
    uv run python scripts/route_profile.py universe-matrix --budget 15 --workers 0 \
      --candidate-policy "$policy" --strategy "$strategy" --json >> "$out"
  done
done
uv run python scripts/route_profile.py quantum-chip --budget 15 --workers 0 --candidate-policy output-products --json >> "$out"
uv run python scripts/route_profile.py plastic --budget 15 --workers 0 --candidate-policy all-products --json >> "$out"
uv run python - <<'EOF'
import json
for line in open("docs/superpowers/evidence/2026-09-01-evaluation-throughput/profile-before.jsonl"):
    r = json.loads(line)
    print(r["url_id"], r["strategy"], f"wall {r['wall_s']:.1f}",
          {k: round(v["s"], 2) for k, v in r["phases"].items()},
          [round(s, 2) for s in r["prepare_calls_s"]])
EOF
```

Expected: eight rows. On `universe-matrix` the first `prepare` call is several seconds. Copy the printed summary into the commit message.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check scripts/route_profile.py tests/bench/test_route_profile.py
uv run mypy scripts/route_profile.py tests/bench/test_route_profile.py
git add scripts/route_profile.py tests/bench/test_route_profile.py docs/superpowers/evidence/2026-09-01-evaluation-throughput/profile-before.jsonl
git commit -m "bench: profile preparation and planning phases per candidate"
```

---

### Task 3: Generate strip families once per Freeform `lay_out`

**Files:**
- Modify: `src/flab2bp/layout/freeform.py:15139-15185` (`FreeformLayout.lay_out`: the `plan_strips` calls and the `_coarsen_saturated_strip_plan` call)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `plan_strips(spec, *, strip_len, band_policy, families=None, cancelled=None)` and `_coarsen_saturated_strip_plan(spec, strips, *, strip_len, band_policy, families=None, cancelled=None)`, both already accepting `families`.
- Produces: `FreeformLayout.lay_out` calls `generate_strip_families` exactly once per call.

- [ ] **Step 1: Write the failing test**

Add to `tests/layout/test_freeform.py` near `test_prepared_net_ids_are_stable`:

```python
def test_lay_out_generates_strip_families_once(monkeypatch: pytest.MonkeyPatch) -> None:
    import flab2bp.layout.freeform as freeform_module
    from flab2bp.layout.strip_variants import StripFamily

    spec = two_stage_spec()
    calls: list[object] = []
    original = freeform_module.generate_strip_families

    def counting(spec_arg: BuildSpec) -> tuple[StripFamily, ...]:
        calls.append(spec_arg)
        return tuple(original(spec_arg))

    monkeypatch.setattr(freeform_module, "generate_strip_families", counting)
    layout = FreeformLayout(band_policy=BandPolicy("portable"), workers=1)
    layout.lay_out(spec, time_budget_s=4.0)

    assert len(calls) == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/layout/test_freeform.py::test_lay_out_generates_strip_families_once -v`
Expected: FAIL with `assert 2 == 1` (the coarsening pass regenerates the families).

- [ ] **Step 3: Thread one family tuple through every planner call**

In `FreeformLayout.lay_out`, immediately after `def planning_cancelled() -> bool: ...`, add:

```python
        families = tuple(generate_strip_families(spec))
```

Then pass `families=families` to every `plan_strips(...)` call in that method (the first attempt, the coarsest-legal retry, and any later one in the same method) and to the `_coarsen_saturated_strip_plan(...)` call. Each call keeps its other keyword arguments unchanged.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_freeform.py -q -k "strip_families_once or prepared_net_ids or prepared_problem"`
Expected: all pass

- [ ] **Step 5: Confirm the profiler shows one `strip_families` call**

Run: `uv run python scripts/route_profile.py universe-matrix --budget 15 --workers 0 --candidate-policy all-products --json | python3 -c "import json,sys; r=json.loads(sys.stdin.read()); print(r['phases'].get('strip_families'))"`
Expected: `{'s': <seconds>, 'n': 1}`

- [ ] **Step 6: Lint, type-check, run the layout suite, commit**

```bash
uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
uv run mypy src/flab2bp/layout/freeform.py
uv run pytest tests/layout/test_freeform.py -q
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "perf(layout): generate strip families once per Freeform lay_out"
```

---

### Task 4: Share junction-ban offsets across attempts and both computation paths

**Files:**
- Modify: `src/flab2bp/layout/freeform.py:3863-3903` (`_junction_ban_offsets`), `:3906-3954` (`_cancellable_junction_ban_offsets`)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `_junction_site_is_clear(buildings, x, y, level) -> bool`.
- Produces: module-level `_JUNCTION_BAN_OFFSET_CACHE: dict[JunctionOffsetKey, frozenset[Cell]]` where `JunctionOffsetKey = tuple[int, int, int, int, float, Fraction]`; both offset functions read it first and write it on completion. `_prepared_junction_ban` needs no change: both paths hit the shared dict before computing.

- [ ] **Step 1: Write the failing test**

```python
def test_cancellable_junction_ban_offsets_are_shared_process_wide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flab2bp.layout.freeform as freeform_module

    freeform_module._JUNCTION_BAN_OFFSET_CACHE.clear()
    freeform_module._junction_ban_offsets.cache_clear()
    probes: list[tuple[int, int, int]] = []
    original = freeform_module._junction_site_is_clear

    def counting(buildings: Sequence[PlacedBuilding], x: int, y: int, level: int) -> bool:
        probes.append((x, y, level))
        return original(buildings, x, y, level)

    monkeypatch.setattr(freeform_module, "_junction_site_is_clear", counting)
    smelter_id = catalog.item_id("arc-smelter")
    smelter = catalog.building(smelter_id)
    key = (smelter_id, smelter.model_index, smelter.width, smelter.height, 0.0, Fraction(0))

    first = freeform_module._cancellable_junction_ban_offsets(*key, lambda: False)
    probed_once = len(probes)
    assert probed_once > 0

    second = freeform_module._cancellable_junction_ban_offsets(*key, lambda: False)
    third = freeform_module._junction_ban_offsets(*key)

    assert second == first
    assert third == first
    assert len(probes) == probed_once, "a second attempt re-derived offsets already proved"
```

`catalog`, `Fraction`, `PlacedBuilding`, and `Sequence` are imported at the top of the test module already; add any that are missing.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/layout/test_freeform.py::test_cancellable_junction_ban_offsets_are_shared_process_wide -v`
Expected: FAIL with `AttributeError: ... has no attribute '_JUNCTION_BAN_OFFSET_CACHE'`

- [ ] **Step 3: Add the shared cache**

Above `_junction_ban_offsets` add:

```python
JunctionOffsetKey = tuple[int, int, int, int, float, Fraction]

#: Relative Splitter bans per immutable obstacle pose, shared by every attempt
#: and both computation paths in this process.  An offset set is a pure
#: function of its key, so a value proved once under a deadline is exactly
#: the value the uncancellable path would return.
_JUNCTION_BAN_OFFSET_CACHE: dict[JunctionOffsetKey, frozenset[Cell]] = {}
```

Keep the `@lru_cache(maxsize=256)` on `_junction_ban_offsets` and make its body consult the shared dict first and store on exit:

```python
key: JunctionOffsetKey = (item_id, model_index, width, height, yaw, z)
cached = _JUNCTION_BAN_OFFSET_CACHE.get(key)
if cached is not None:
    return cached
obstacle = PlacedBuilding(...)  # unchanged
...  # unchanged radius / centre computation
banned = frozenset(
    (x, y, level)
    for x in range(...)  # unchanged ranges
    for y in range(...)
    for level in range(LEVELS)
    if not _junction_site_is_clear((obstacle,), x, y, level)
)
_JUNCTION_BAN_OFFSET_CACHE[key] = banned
return banned
```

In `_cancellable_junction_ban_offsets`, add the same `key` and lookup at the top (return the cached set immediately when present), and store `_JUNCTION_BAN_OFFSET_CACHE[key] = result` just before the final `return`, after the last `cancelled()` check, so a cancelled computation never stores a partial set:

```python
    if cancelled():
        raise _PreparationDeadline
    result = frozenset(banned)
    _JUNCTION_BAN_OFFSET_CACHE[key] = result
    return result
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_freeform.py -q -k "junction"`
Expected: all pass

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
uv run mypy src/flab2bp/layout/freeform.py
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "perf(layout): share junction ban offsets across attempts"
```

---

### Task 5: Reach-filter coater junction bans before materializing splitter stacks

**Files:**
- Modify: `src/flab2bp/layout/freeform.py:11134-11439` (`_projected_coater_junction_bans_by_frame`)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `finalize.materialize_frame_building(building, *, bounds, candidate)`, `_collision_pose`, `_splitter_stack_geometry(x, y, level)`.
- Produces: the same function with a new keyword `_prefilter: bool = True`; `False` runs the previous order and exists only for the parity test.

Why this is exact: every member of one splitter stack shares `x`, `y`, `width`, and `height` and differs only in `z` and `yaw`, and `materialize_frame_building` changes `x`/`y` by the same translation (and rotation) for every member. So the materialized `x`/`y` of the whole stack equals the materialized `x`/`y` of its first member, and the reach test `cell_dx * x_step > tangent_reach_x or cell_dy * y_step > tangent_reach_y` gives the same answer for every member. When it rejects every projection state for a frame, the current code materializes the stack, computes the same deltas, and `continue`s for each member without touching `banned_by_frame`. Skipping that work changes nothing observable.

If the profile after this task still shows `coater_frame_bans` above 1.0 s on `universe-matrix`, the next lever is the NumPy batching named in spec section 5.2; write it as a follow-up task with the measured phase table rather than guessing here.

- [ ] **Step 1: Write the failing parity and call-count test**

```python
def test_coater_frame_bans_prefilter_is_exact_and_materializes_less(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flab2bp.layout.finalize as finalize_module
    import flab2bp.layout.freeform as freeform_module

    spec = plastic_spec()
    strips = plan_strips(spec, strip_len=6)
    pack = _greedy_pack(strips, _height_seed(strips))
    prepared = _prepare_routing_problem(
        spec, strips, pack, policy=BandPolicy("portable"), power=True
    )
    coaters = [
        (index, building)
        for index, building in enumerate(prepared.building_templates)
        if building.item_id == catalog.SPRAY_COATER_ID
    ]
    assert coaters, "plastic/all-products carries Spray Coaters"
    frames = freeform_module._junction_projection_frames(
        prepared.core, prepared.limit or prepared.route_bounds, BandPolicy("portable")
    )
    counts: list[int] = []
    original = finalize_module.materialize_frame_building

    def counting(*args: object, **kwargs: object) -> PlacedBuilding:
        counts[-1] += 1
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(finalize_module, "materialize_frame_building", counting)

    counts.append(0)
    slow = freeform_module._projected_coater_junction_bans_by_frame(
        coaters,
        frames,
        prepared.route_bounds,
        already_banned=set(),
        splitter_index=len(prepared.building_templates),
        _prefilter=False,
    )
    slow_calls = counts[-1]
    counts.append(0)
    fast = freeform_module._projected_coater_junction_bans_by_frame(
        coaters,
        frames,
        prepared.route_bounds,
        already_banned=set(),
        splitter_index=len(prepared.building_templates),
    )
    fast_calls = counts[-1]

    assert fast == slow
    assert fast_calls < slow_calls
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/layout/test_freeform.py::test_coater_frame_bans_prefilter_is_exact_and_materializes_less -v`
Expected: FAIL with `TypeError: ... got an unexpected keyword argument '_prefilter'`

- [ ] **Step 3: Add the prefilter**

Add `_prefilter: bool = True` to the keyword parameters of `_projected_coater_junction_bans_by_frame`. Inside the cell loop, replace the block that begins `materialized_key = (cell, frame.bounds, frame.candidate)` and ends with `materialized_splitters[materialized_key] = materialized_stack` with:

```python
materialized_key = (
    cell,
    frame.bounds,
    frame.candidate,
)
materialized_stack = materialized_splitters.get(materialized_key)
if materialized_stack is None and _prefilter:
    probe = _collision_pose(
        finalize.materialize_frame_building(
            splitter_stack[0],
            bounds=frame.bounds,
            candidate=frame.candidate,
        )
    )
    probe_dx = abs(probe.x - materialized_coater[1].x)
    probe_dy = abs(probe.y - materialized_coater[1].y)
    if all(
        probe_dx * x_step > tangent_reach_x or probe_dy * y_step > tangent_reach_y
        for (
            _projection,
            x_step,
            y_step,
            _boxes,
            _coater,
            _context,
        ) in frame_projection_states
    ):
        # Every projection state would `continue` for
        # every member of this stack, because the whole
        # stack shares one materialized x/y.
        continue
if materialized_stack is None:
    materialized_stack = tuple(
        _collision_pose(
            finalize.materialize_frame_building(
                stack_member,
                bounds=frame.bounds,
                candidate=frame.candidate,
            )
        )
        for stack_member in splitter_stack
    )
    materialized_splitters[materialized_key] = materialized_stack
```

Everything after that point in the loop stays as it is.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_freeform.py -q -k "coater"`
Expected: all pass

- [ ] **Step 5: Measure**

Run: `uv run python scripts/route_profile.py universe-matrix --budget 15 --workers 0 --candidate-policy all-products --json | python3 -c "import json,sys; r=json.loads(sys.stdin.read()); print(r['phases'].get('coater_frame_bans'), r['prepare_calls_s'])"`
Expected: `coater_frame_bans` seconds below the `profile-before.jsonl` value for the same cell (3.4 to 3.8 s before). Record the number in the commit message. If it is not lower, do not commit; report the profile instead.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
uv run mypy src/flab2bp/layout/freeform.py
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "perf(layout): reach-filter coater junction bans before materializing"
```

---

### Task 6: Stop deep-copying immutable building templates

**Files:**
- Modify: `src/flab2bp/layout/freeform.py`, the `building_templates=tuple(deepcopy(canvas.buildings))` argument in the `_PreparedRoutingProblem(...)` construction at the end of `_prepare_routing_problem` (line 13146 at 4c09a85; the in-flight work rewrites this function, so locate it by the `deepcopy(canvas.buildings)` text)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `PlacedBuilding` is `@dataclass(frozen=True, slots=True)` (`src/flab2bp/layout/base.py:92`).
- Produces: `_PreparedRoutingProblem.building_templates` holds the same frozen instances the canvas holds.

- [ ] **Step 1: Write the failing test**

```python
def test_prepare_routing_problem_does_not_deepcopy_buildings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import copy

    import flab2bp.layout.freeform as freeform_module

    assert PlacedBuilding.__dataclass_params__.frozen
    spec = two_stage_spec()
    strips = plan_strips(spec, strip_len=6)
    pack = _greedy_pack(strips, _height_seed(strips))
    copied: list[type] = []
    original = copy.deepcopy

    def spy(value: object, memo: dict[int, object] | None = None) -> object:
        copied.append(type(value))
        return original(value, memo)

    monkeypatch.setattr(copy, "deepcopy", spy)
    if hasattr(freeform_module, "deepcopy"):
        monkeypatch.setattr(freeform_module, "deepcopy", spy)
    prepared = _prepare_routing_problem(
        spec, strips, pack, policy=BandPolicy("portable"), power=False
    )

    assert list not in copied
    first = prepared.new_workspace()
    second = prepared.new_workspace()
    assert first.buildings is not second.buildings
    assert first.buildings == second.buildings
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/layout/test_freeform.py::test_prepare_routing_problem_does_not_deepcopy_buildings -v`
Expected: FAIL with `assert list not in [...]`

- [ ] **Step 3: Replace the deep copy**

In the `_PreparedRoutingProblem(...)` construction at the end of `_prepare_routing_problem`, change

```python
building_templates = (tuple(deepcopy(canvas.buildings)),)
```

to

```python
# `PlacedBuilding` is frozen; the tuple is a fresh container and every
# workspace copies the container again.  Deep-copying 300 frozen
# dataclasses per candidate cost 0.38 s on `universe-matrix`.
building_templates = (tuple(canvas.buildings),)
```

If `deepcopy` is no longer referenced anywhere in `freeform.py`, remove it from the imports.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_freeform.py -q`
Expected: all pass

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
uv run mypy src/flab2bp/layout/freeform.py
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "perf(layout): stop deep-copying frozen building templates"
```

---

### Task 7: Spec-scoped geometry memo shared across candidates and strategies

**Files:**
- Create: `src/flab2bp/layout/geometry_memo.py`
- Modify: `src/flab2bp/layout/freeform.py` (`_StagedStaticCache`, add `stats()`; the `staged_static_cache = _StagedStaticCache()` statement inside `FreeformLayout._sweep`, line 15616 at 4c09a85)
- Modify: `src/flab2bp/layout/sequence_solver.py` (the `staged_static_cache = _StagedStaticCache()` statement inside `_production_run`, line 4212 at 4c09a85; the in-flight work edits this function, so locate the statement by text)
- Test: `tests/layout/test_geometry_memo.py`

**Interfaces:**
- Consumes: `_StagedStaticCache` (attempt-local dicts: `frames`, `cleanup_bounds`, `materialized`, `materialized_bases`, `clean_contexts`, `coater_supply_failures`, `boxes`, `placed`, `junction_offsets`, `cleanup_operations`, and the three counters).
- Produces:

```python
# src/flab2bp/layout/geometry_memo.py
class MemoStats(NamedTuple):
    tables: dict[str, int]  # entries per dict field
    broad_phase_queries: int
    broad_phase_hits: int
    exact_static_queries: int


MEMO_SPECS_RETAINED: int = 4


def for_spec(spec: BuildSpec) -> _StagedStaticCache: ...
def stats_for_spec(spec: BuildSpec) -> MemoStats: ...
def clear() -> None: ...
```

`for_spec` returns the same cache object for the same `spec` object (identity) until more than `MEMO_SPECS_RETAINED` distinct specs have been seen, at which point the least recently used entry is dropped. The registry holds a strong reference to each retained spec so `id(spec)` cannot be reused while its cache lives.

- [ ] **Step 1: Write the failing tests**

```python
# tests/layout/test_geometry_memo.py
from __future__ import annotations

from collections.abc import Callable

import pytest

from flab2bp.layout import geometry_memo
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.freeform import (
    _greedy_pack,
    _height_seed,
    _prepare_routing_problem,
    _StagedStaticCache,
    plan_strips,
)
from flab2bp.spec import BuildSpec
from tests.layout.test_freeform import (
    captured_output_products_spec,
    plastic_spec,
    two_stage_spec,
)


def test_for_spec_returns_one_cache_per_spec_object() -> None:
    geometry_memo.clear()
    spec = two_stage_spec()
    other = two_stage_spec()

    first = geometry_memo.for_spec(spec)
    again = geometry_memo.for_spec(spec)
    different = geometry_memo.for_spec(other)

    assert isinstance(first, _StagedStaticCache)
    assert again is first
    assert different is not first


def test_registry_evicts_least_recently_used_spec() -> None:
    geometry_memo.clear()
    specs = [two_stage_spec() for _ in range(geometry_memo.MEMO_SPECS_RETAINED + 1)]
    caches = [geometry_memo.for_spec(spec) for spec in specs]

    assert geometry_memo.for_spec(specs[0]) is not caches[0]
    assert geometry_memo.for_spec(specs[-1]) is caches[-1]


@pytest.mark.parametrize("make_spec", [two_stage_spec, plastic_spec, captured_output_products_spec])
def test_shared_cache_does_not_change_the_prepared_problem(
    make_spec: Callable[[], BuildSpec],
) -> None:
    geometry_memo.clear()
    spec = make_spec()
    strips = plan_strips(spec, strip_len=6)
    pack = _greedy_pack(strips, _height_seed(strips))
    policy = BandPolicy("portable")

    cold = _prepare_routing_problem(spec, strips, pack, policy=policy, power=True)
    shared = geometry_memo.for_spec(spec)
    warm_first = _prepare_routing_problem(
        spec, strips, pack, policy=policy, power=True, staged_static_cache=shared
    )
    warm_second = _prepare_routing_problem(
        spec, strips, pack, policy=policy, power=True, staged_static_cache=shared
    )

    assert warm_first == cold
    assert warm_second == cold
    stats = geometry_memo.stats_for_spec(spec)
    assert sum(stats.tables.values()) > 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_geometry_memo.py -v`
Expected: FAIL with `ImportError: cannot import name 'geometry_memo'`

- [ ] **Step 3: Write the module and the `stats()` method**

```python
# src/flab2bp/layout/geometry_memo.py
"""Spec-scoped memo of pure projection predicates, shared across candidates.

`_StagedStaticCache` memoizes finalizer projection inputs that are pure
functions of their keys.  It used to be created once per `_sweep` and once per
`_production_run`, so the second strategy in a `best` build and every later
`lay_out` of the same spec re-derived what the first had proved.  This registry
hands out one cache per spec object for the life of the process, bounded to
`MEMO_SPECS_RETAINED` specs so a long-lived audit worker cannot grow without
limit.  Keys are spec identity: a retained spec is held strongly, so its `id`
cannot be recycled while its cache is live.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import NamedTuple

from flab2bp.layout.freeform import _StagedStaticCache
from flab2bp.spec import BuildSpec

MEMO_SPECS_RETAINED = 4

_REGISTRY: OrderedDict[int, tuple[BuildSpec, _StagedStaticCache]] = OrderedDict()


class MemoStats(NamedTuple):
    tables: dict[str, int]
    broad_phase_queries: int
    broad_phase_hits: int
    exact_static_queries: int


def for_spec(spec: BuildSpec) -> _StagedStaticCache:
    """Return the process-wide cache for ``spec``, creating and bounding it."""
    key = id(spec)
    entry = _REGISTRY.get(key)
    if entry is not None:
        _REGISTRY.move_to_end(key)
        return entry[1]
    cache = _StagedStaticCache()
    _REGISTRY[key] = (spec, cache)
    while len(_REGISTRY) > MEMO_SPECS_RETAINED:
        _REGISTRY.popitem(last=False)
    return cache


def stats_for_spec(spec: BuildSpec) -> MemoStats:
    return for_spec(spec).stats()


def clear() -> None:
    _REGISTRY.clear()
```

Add to `_StagedStaticCache` in `freeform.py`, with `from flab2bp.layout.geometry_memo import MemoStats` added inside the existing `if TYPE_CHECKING:` block at `freeform.py:112`:

```python
    def stats(self) -> MemoStats:
        from flab2bp.layout.geometry_memo import MemoStats as _MemoStats

        return _MemoStats(
            tables={
                "frames": len(self.frames),
                "cleanup_bounds": len(self.cleanup_bounds),
                "materialized": len(self.materialized),
                "materialized_bases": len(self.materialized_bases),
                "clean_contexts": len(self.clean_contexts),
                "coater_supply_failures": len(self.coater_supply_failures),
                "boxes": len(self.boxes),
                "placed": len(self.placed),
                "junction_offsets": len(self.junction_offsets),
            },
            broad_phase_queries=self.broad_phase_queries,
            broad_phase_hits=self.broad_phase_hits,
            exact_static_queries=self.exact_static_queries,
        )
```

Replace the two production constructions with the registry, importing lazily to avoid the import cycle:

- `freeform.py:15616` in `FreeformLayout._sweep`:

```python
        from flab2bp.layout import geometry_memo

        staged_static_cache = geometry_memo.for_spec(spec)
```

- `sequence_solver.py:4212` in `_production_run`:

```python
    from flab2bp.layout import geometry_memo

    staged_static_cache = geometry_memo.for_spec(spec)
```

Leave the constructions at `freeform.py:11010`, `:11648`, `:12469`, `:13834` alone: they are the `None` defaults that give every existing caller and test a private cache.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/layout/test_geometry_memo.py tests/layout/test_freeform.py tests/layout/test_sequence_solver.py -q`
Expected: all pass

- [ ] **Step 5: Measure the warm second candidate**

Run: `uv run python scripts/route_profile.py universe-matrix --budget 30 --workers 0 --candidate-policy all-products --strategy sequence-pair --json | python3 -c "import json,sys; r=json.loads(sys.stdin.read()); print(r['prepare_calls_s'])"`
Expected: two or more entries; the second is lower than the first. Record both in the commit message.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/geometry_memo.py src/flab2bp/layout/freeform.py src/flab2bp/layout/sequence_solver.py tests/layout/test_geometry_memo.py
uv run mypy src/flab2bp/layout/geometry_memo.py src/flab2bp/layout/freeform.py src/flab2bp/layout/sequence_solver.py
git add src/flab2bp/layout/geometry_memo.py src/flab2bp/layout/freeform.py src/flab2bp/layout/sequence_solver.py tests/layout/test_geometry_memo.py
git commit -m "perf(layout): share staged static geometry across candidates per spec"
```

---

### Task 8: Cython A* kernel with digest parity

**Files:**
- Create: `src/flab2bp/layout/_route_kernel.pyx`
- Create: `src/flab2bp/layout/_route_kernel.pyi`
- Create: `src/flab2bp/layout/route_kernel.py`
- Modify: `setup.py`
- Modify: `src/flab2bp/layout/freeform.py:5563-5723` (`_Grid`: `alt_flat` field, `build_landmarks`, `refresh_history`), `src/flab2bp/layout/freeform.py:5886-6437` (`_astar`)
- Test: `tests/layout/test_route_kernel.py`

**Interfaces:**
- Consumes: `_Grid` fields (`gx0`, `gy0`, `gh`, `xstep`, `size`, `alt`, `hist`), `_routing_flags`, `_LEVEL_TOLL`, `_STEPS`, `_EXACT_HEURISTIC_GOALS`, `_MAX_EXPANSIONS`, `_DEADLINE_CHECK_EVERY`, `_expired`, `_cut_loops`, `LEVELS`; `scripts.route_bench._snapshot`.
- Produces:

```python
# src/flab2bp/layout/_route_kernel.pyi
from array import array
from collections.abc import Callable


def astar_flat(
    flags: bytearray,
    hist: array[float],  # zero-length when there is no history this round
    pressure: float,
    alt_flat: array[int],  # landmark fields concatenated, band-major; zero-length when none
    band_count: int,
    goal_flag: bytearray,
    goal_columns: array[int],  # deduplicated (x, y) local pairs, flattened
    exact_goals: bool,  # len(goal_list) <= _EXACT_HEURISTIC_GOALS, on the undeduplicated list
    goal_box: tuple[int, int, int, int],
    starts: array[int],  # admitted start cell indices
    gh: int,
    xstep: int,
    levels: int,
    level_toll: array[float],
    max_expansions: int,
    budget_left: int,  # 1 << 62 when there is no shared budget
    deadline_every: int,
    deadline: float | None,
    expired: Callable[[float | None], bool],
) -> tuple[array[int] | None, int, int, array[int], int]:
    """(path indices with via cells spliced, oldest first, or None;
    expansions; exit kind 0 found / 1 budget / 2 sealed;
    settled cell indices in index order when sealed, else empty;
    budget_left after the same write-back rules as the Python loop)."""


# src/flab2bp/layout/route_kernel.py
BackendName = Literal["python", "cython"]
_compiled_astar: (
    Callable[..., object] | None
)  # None when the extension is absent or FLAB2BP_ROUTE_KERNEL=python


def compiled_available() -> bool: ...
def selected_backend() -> BackendName: ...
```

The wrapper in `freeform._astar` keeps every pre-check, grid selection, flags construction, goal-flag construction, heuristic-input preparation, budget write-back, path decoding, `_cut_loops`, and the sealed-pocket wall/blame computation in Python. Only the loop from the first heap push to the loop exit moves into the kernel.

- [ ] **Step 1: Write the failing tests**

```python
# tests/layout/test_route_kernel.py
from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from typing import Any

import pytest

import flab2bp.layout.freeform as freeform_module
from flab2bp.layout import route_kernel
from flab2bp.layout.band_policy import BandPolicy
from flab2bp.layout.freeform import (
    FreeformLayout,
    NoValidLayout,
    RouteFailureKind,
    _PathSearchResult,
)
from flab2bp.spec import BuildSpec
from scripts.route_bench import _snapshot
from tests.layout.test_freeform import plastic_spec, two_stage_spec

Cell = tuple[int, int, int]
Case = dict[str, Any]


def _capture_searches(spec: BuildSpec, budget_s: float) -> list[Case]:
    """Replayable snapshots of every real search one Freeform lay_out makes."""
    original = freeform_module._astar
    cases: list[Case] = []

    def spy(
        canvas: Any,
        starts: list[Cell],
        goals: set[Cell],
        history: dict[Cell, float],
        pressure: float,
        bounds: tuple[int, int, int, int],
        budget: dict[str, int] | None = None,
        deadline: float | None = None,
        blame: dict[Cell, float] | None = None,
        grid: Any = None,
        owned_starts: Collection[Cell] = (),
        released_starts: Collection[Cell] = (),
        forbidden: Collection[Cell] = (),
        blocking_owners: Mapping[Cell, int] | None = None,
    ) -> _PathSearchResult:
        shot_canvas, shot_grid, shot_hist = _snapshot(canvas, grid, history)
        cases.append(
            {
                "canvas": shot_canvas,
                "grid": shot_grid,
                "history": shot_hist,
                "starts": list(starts),
                "goals": set(goals),
                "pressure": pressure,
                "bounds": bounds,
                "owned_starts": tuple(owned_starts),
                "released_starts": tuple(released_starts),
                "forbidden": tuple(forbidden),
                "blocking_owners": None if blocking_owners is None else dict(blocking_owners),
            }
        )
        return original(
            canvas,
            starts,
            goals,
            history,
            pressure,
            bounds,
            budget,
            deadline,
            blame,
            grid,
            owned_starts,
            released_starts,
            forbidden,
            blocking_owners,
        )

    freeform_module._astar = spy
    try:
        FreeformLayout(band_policy=BandPolicy("portable"), workers=1).lay_out(
            spec, time_budget_s=budget_s
        )
    except NoValidLayout:
        pass
    finally:
        freeform_module._astar = original
    return cases


def _replay(case: Case, budget: dict[str, int] | None = None) -> _PathSearchResult:
    return freeform_module._astar(
        case["canvas"],
        case["starts"],
        case["goals"],
        case["history"],
        case["pressure"],
        case["bounds"],
        {"left": 1 << 40} if budget is None else budget,
        None,
        {},
        case["grid"],
        case["owned_starts"],
        case["released_starts"],
        case["forbidden"],
        case["blocking_owners"],
    )


@pytest.mark.parametrize("make_spec", [two_stage_spec, plastic_spec])
def test_compiled_astar_matches_python_on_real_searches(
    make_spec: Callable[[], BuildSpec], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert route_kernel.compiled_available()
    cases = _capture_searches(make_spec(), budget_s=4.0)
    assert cases

    compiled = [_replay(case) for case in cases]
    monkeypatch.setattr(route_kernel, "_compiled_astar", None)
    assert route_kernel.selected_backend() == "python"
    python = [_replay(case) for case in cases]

    for compiled_result, python_result in zip(compiled, python, strict=True):
        assert compiled_result.path == python_result.path
        assert compiled_result.kind == python_result.kind
        assert compiled_result.wall == python_result.wall
        assert compiled_result.expansions == python_result.expansions


def test_compiled_astar_honours_expansion_cap_and_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    cases = _capture_searches(two_stage_spec(), budget_s=2.0)
    found = [case for case in cases if _replay(case).expansions >= 3]
    assert found
    case = found[0]

    tiny = {"left": 3}
    result = _replay(case, tiny)
    assert result.path is None
    assert result.kind is RouteFailureKind.BUDGET
    assert result.expansions == 3
    assert tiny["left"] == 0

    monkeypatch.setattr(freeform_module, "_MAX_EXPANSIONS", 2)
    capped = {"left": 1 << 40}
    result = _replay(case, capped)
    assert result.kind is RouteFailureKind.BUDGET
    assert result.expansions == 3  # cap + 1, exactly as the Python loop counts it
    assert capped["left"] == (1 << 40) - 2


def test_backend_falls_back_when_extension_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(route_kernel, "_compiled_astar", None)
    assert not route_kernel.compiled_available()
    assert route_kernel.selected_backend() == "python"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_route_kernel.py -v`
Expected: FAIL with `ImportError: cannot import name 'route_kernel'`

- [ ] **Step 3: Store landmark fields and history as buffers on `_Grid`**

In `_Grid`, add a field after `alt`:

```python
    #: ``alt`` concatenated band-major into one buffer, for the compiled loop.
    alt_flat: array[int] = field(default_factory=lambda: array("q"))
```

Change the `hist` annotation to `hist: array[float] | list[float] | None` (the repair path at `freeform.py:7848` assigns a list; both loops index it and the wrapper converts a list to an array once per search). At the end of `build_landmarks`, after `self.alt = tuple(fields)`, add:

```python
        flat = array("q")
        for field_ in fields:
            flat.extend(field_)
        self.alt_flat = flat
```

In `refresh_history`, build `flat = array("d", bytes(8 * self.size))` instead of `[0.0] * self.size`; the indexed assignments below it are unchanged. Import `array` from the `array` module and `field` from `dataclasses` at the top of `freeform.py` if not already present.

`scripts/route_bench.py:195-198` resets `grid.alt = ()` before `build_landmarks`; that path recomputes `alt_flat` through `build_landmarks`, so no change there. `_snapshot` copies `hist` with `list(grid.hist)`; leave it, the wrapper converts.

- [ ] **Step 4: Write the extension**

```cython
# src/flab2bp/layout/_route_kernel.pyx
# cython: language_level=3, boundscheck=False, wraparound=False, initializedcheck=False, cdivision=True
"""Flat-grid A* inner loop.  Byte-identical to ``freeform._astar``'s loop.

The heap orders on ``(f, g, index)`` exactly as ``heapq`` orders the Python
tuples, costs are accumulated in the same association order, and the
expansion checkpoint arithmetic is copied rather than simplified, so the
replay digest in ``scripts/route_bench.py`` is unchanged.
"""

from array import array

from libc.math cimport INFINITY
from libc.stdlib cimport free, malloc


cdef struct Entry:
    double f
    double g
    long long index


cdef inline bint entry_less(Entry a, Entry b) noexcept nogil:
    if a.f != b.f:
        return a.f < b.f
    if a.g != b.g:
        return a.g < b.g
    return a.index < b.index


cdef class _Heap:
    cdef Entry* data
    cdef Py_ssize_t size
    cdef Py_ssize_t capacity

    def __cinit__(self, Py_ssize_t capacity):
        self.capacity = capacity if capacity > 16 else 16
        self.data = <Entry*> malloc(self.capacity * sizeof(Entry))
        if self.data == NULL:
            raise MemoryError()
        self.size = 0

    def __dealloc__(self):
        if self.data != NULL:
            free(self.data)

    cdef int push(self, double f, double g, long long index) except -1:
        cdef Entry* grown
        cdef Py_ssize_t pos, parent
        cdef Entry item
        if self.size == self.capacity:
            grown = <Entry*> malloc(self.capacity * 2 * sizeof(Entry))
            if grown == NULL:
                raise MemoryError()
            for pos in range(self.size):
                grown[pos] = self.data[pos]
            free(self.data)
            self.data = grown
            self.capacity *= 2
        item.f = f
        item.g = g
        item.index = index
        pos = self.size
        self.size += 1
        while pos > 0:
            parent = (pos - 1) >> 1
            if entry_less(item, self.data[parent]):
                self.data[pos] = self.data[parent]
                pos = parent
            else:
                break
        self.data[pos] = item
        return 0

    cdef Entry pop(self) noexcept nogil:
        cdef Entry top = self.data[0]
        cdef Entry last
        cdef Py_ssize_t pos = 0, child
        self.size -= 1
        if self.size > 0:
            last = self.data[self.size]
            while True:
                child = 2 * pos + 1
                if child >= self.size:
                    break
                if child + 1 < self.size and entry_less(self.data[child + 1], self.data[child]):
                    child += 1
                if entry_less(self.data[child], last):
                    self.data[pos] = self.data[child]
                    pos = child
                else:
                    break
            self.data[pos] = last
        return top


cdef double _h(
    long long col, long long gh, bint single, bint exact,
    long long only_x, long long only_y,
    const long long[::1] goal_columns, Py_ssize_t goal_count,
    long long bx0, long long by0, long long bx1, long long by1,
    Py_ssize_t bands, const long long* band_index, const long long* band_lo,
    const long long* band_hi, const long long[::1] alt_flat, long long columns,
) noexcept nogil:
    cdef long long x = col // gh
    cdef long long y = col - x * gh
    cdef long long dx, dy, dsum, best_d, fx, fy, dial, gap
    cdef double far
    cdef Py_ssize_t k, b
    if single:
        dx = x - only_x
        dy = y - only_y
        far = <double> ((dx if dx >= 0 else -dx) + (dy if dy >= 0 else -dy))
    elif exact:
        best_d = 1 << 30
        for k in range(goal_count):
            fx = goal_columns[2 * k]
            fy = goal_columns[2 * k + 1]
            dx = x - fx
            dy = y - fy
            dsum = (dx if dx >= 0 else -dx) + (dy if dy >= 0 else -dy)
            if dsum < best_d:
                best_d = dsum
        far = <double> best_d
    else:
        dx = bx0 - x
        if x - bx1 > dx:
            dx = x - bx1
        if dx < 0:
            dx = 0
        dy = by0 - y
        if y - by1 > dy:
            dy = y - by1
        if dy < 0:
            dy = 0
        far = <double> (dx + dy)
    for b in range(bands):
        dial = alt_flat[band_index[b] * columns + col]
        if dial < 0:
            continue
        gap = band_lo[b] - dial
        if <double> gap > far:
            far = <double> gap
        gap = dial - band_hi[b]
        if <double> gap > far:
            far = <double> gap
    return far


def astar_flat(
    unsigned char[::1] flags,
    const double[::1] hist,
    double pressure,
    const long long[::1] alt_flat,
    long long band_count,
    unsigned char[::1] goal_flag,
    const long long[::1] goal_columns,
    bint exact_goals,
    tuple goal_box,
    const long long[::1] starts,
    long long gh,
    long long xstep,
    long long levels,
    const double[::1] level_toll,
    long long max_expansions,
    long long budget_left,
    long long deadline_every,
    object deadline,
    object expired,
):
    cdef Py_ssize_t size = flags.shape[0]
    cdef long long columns = size // levels
    cdef bint negotiating = hist.shape[0] > 0
    cdef Py_ssize_t goal_count = goal_columns.shape[0] // 2
    cdef bint single = goal_count == 1
    cdef long long only_x = goal_columns[0] if goal_count else 0
    cdef long long only_y = goal_columns[1] if goal_count else 0
    cdef long long bx0 = goal_box[0], by0 = goal_box[1], bx1 = goal_box[2], by1 = goal_box[3]
    cdef Py_ssize_t b, k, i, bands = 0
    cdef long long lo, hi, dial, at
    cdef long long* band_index = NULL
    cdef long long* band_lo = NULL
    cdef long long* band_hi = NULL
    cdef double* best = NULL
    cdef long long* prev = NULL
    cdef long long* via = NULL
    cdef double* hcache = NULL
    cdef _Heap heap
    cdef long long si, col, expansions = 0, start_left = budget_left
    cdef long long checkpoint, due, q, lvl, nxt, run, top, step, node, found = -1
    cdef double g, cost, step_toll, run_base, far, toll2, h0
    cdef int kind = 2
    cdef Py_ssize_t d, r
    cdef long long one, two, colone, coltwo
    cdef long long moves[4][4]
    cdef long long ramp_steps[2]

    if band_count > 0:
        band_index = <long long*> malloc(band_count * sizeof(long long))
        band_lo = <long long*> malloc(band_count * sizeof(long long))
        band_hi = <long long*> malloc(band_count * sizeof(long long))
        if band_index == NULL or band_lo == NULL or band_hi == NULL:
            raise MemoryError()
    best = <double*> malloc(size * sizeof(double))
    prev = <long long*> malloc(size * sizeof(long long))
    via = <long long*> malloc(size * sizeof(long long))
    hcache = <double*> malloc(columns * sizeof(double))
    if best == NULL or prev == NULL or via == NULL or hcache == NULL:
        raise MemoryError()
    try:
        # Landmark bands: the goals occupy [lo, hi] on each landmark's dial; a
        # landmark that cannot reach every goal is DROPPED, as in Python.
        for b in range(band_count):
            lo = -1
            hi = -1
            for k in range(goal_count):
                at = goal_columns[2 * k] * gh + goal_columns[2 * k + 1]
                dial = alt_flat[b * columns + at]
                if dial < 0:
                    lo = -1
                    break
                if lo < 0 or dial < lo:
                    lo = dial
                if dial > hi:
                    hi = dial
            if lo >= 0:
                band_index[bands] = b
                band_lo[bands] = lo
                band_hi[bands] = hi
                bands += 1

        for i in range(size):
            best[i] = INFINITY
            prev[i] = -1
            via[i] = -1
        for i in range(columns):
            hcache[i] = -1.0

        # (one-step cell offset, two-step cell offset, one-step column offset,
        # two-step column offset) for _STEPS = ((1, 0), (-1, 0), (0, 1), (0, -1)).
        moves[0][0] = xstep;   moves[0][1] = 2 * xstep;   moves[0][2] = gh;   moves[0][3] = 2 * gh
        moves[1][0] = -xstep;  moves[1][1] = -2 * xstep;  moves[1][2] = -gh;  moves[1][3] = -2 * gh
        moves[2][0] = levels;  moves[2][1] = 2 * levels;  moves[2][2] = 1;    moves[2][3] = 2
        moves[3][0] = -levels; moves[3][1] = -2 * levels; moves[3][2] = -1;   moves[3][3] = -2
        ramp_steps[0] = 1
        ramp_steps[1] = -1

        heap = _Heap(1024)
        for i in range(starts.shape[0]):
            si = starts[i]
            best[si] = 0.0
            prev[si] = -1
            col = si // levels
            h0 = _h(col, gh, single, exact_goals, only_x, only_y, goal_columns, goal_count,
                    bx0, by0, bx1, by1, bands, band_index, band_lo, band_hi, alt_flat, columns)
            heap.push(h0, 0.0, si)

        checkpoint = max_expansions + 1
        if checkpoint > deadline_every:
            checkpoint = deadline_every
        if start_left < checkpoint:
            checkpoint = start_left

        while heap.size > 0:
            cur = heap.pop()
            g = cur.g
            if g > best[cur.index]:
                continue
            expansions += 1
            if expansions >= checkpoint:
                if expansions > max_expansions:
                    kind = 1
                    budget_left = start_left - expansions + 1
                    break
                if expansions % deadline_every == 0 and expired(deadline):
                    kind = 1
                    budget_left = start_left - expansions + 1
                    break
                if expansions >= start_left:
                    kind = 1
                    budget_left = start_left - expansions
                    break
                checkpoint = max_expansions + 1
                due = (expansions // deadline_every + 1) * deadline_every
                if due < checkpoint:
                    checkpoint = due
                if start_left < checkpoint:
                    checkpoint = start_left
            if goal_flag[cur.index]:
                kind = 0
                found = cur.index
                budget_left = start_left - expansions
                break
            q = cur.index // levels
            lvl = cur.index - q * levels
            step_toll = 1.0 + level_toll[lvl]
            run_base = g + 3.0
            for d in range(4):
                one = moves[d][0]
                two = moves[d][1]
                colone = moves[d][2]
                coltwo = moves[d][3]
                nxt = cur.index + one
                if not flags[nxt]:
                    continue
                cost = g + step_toll
                if negotiating:
                    cost += hist[nxt] * pressure
                if cost < best[nxt]:
                    best[nxt] = cost
                    prev[nxt] = cur.index
                    via[nxt] = -1
                    col = q + colone
                    far = hcache[col]
                    if far < 0.0:
                        far = _h(col, gh, single, exact_goals, only_x, only_y, goal_columns,
                                 goal_count, bx0, by0, bx1, by1, bands, band_index, band_lo,
                                 band_hi, alt_flat, columns)
                        hcache[col] = far
                    heap.push(cost + far, cost, nxt)
                run = cur.index + two
                for r in range(2):
                    step = ramp_steps[r]
                    if lvl + step < 0 or lvl + step >= levels:
                        continue
                    toll2 = level_toll[lvl + step]
                    top = run + step
                    if not flags[top]:
                        continue
                    cost = run_base + toll2
                    if negotiating:
                        cost += hist[top] * pressure
                    if cost < best[top]:
                        best[top] = cost
                        prev[top] = cur.index
                        via[top] = nxt
                        col = q + coltwo
                        far = hcache[col]
                        if far < 0.0:
                            far = _h(col, gh, single, exact_goals, only_x, only_y, goal_columns,
                                     goal_count, bx0, by0, bx1, by1, bands, band_index, band_lo,
                                     band_hi, alt_flat, columns)
                            hcache[col] = far
                        heap.push(cost + far, cost, top)
        else:
            # The heap emptied: sealed.  Same write-back as the Python loop.
            budget_left = start_left - expansions

        path = None
        settled = array("q")
        if kind == 0:
            out = array("q")
            node = found
            while node != -1:
                out.append(node)
                if via[node] != -1:
                    out.append(via[node])
                node = prev[node]
            out.reverse()
            path = out
        elif kind == 2:
            for i in range(size):
                if best[i] != INFINITY:
                    settled.append(i)
        return path, expansions, kind, settled, budget_left
    finally:
        free(best)
        free(prev)
        free(via)
        free(hcache)
        if band_index != NULL:
            free(band_index)
            free(band_lo)
            free(band_hi)
```

`cur` is declared with `cdef Entry cur` in the declaration block at the top of `astar_flat` (add it beside `cdef int kind = 2`). Cython requires every `cdef` declaration before the first statement of the function, which is why the declarations are grouped at the top and none appear inside `try` or loops.

Two points the implementer must keep exactly:

1. The Python `via` dict only records a via cell for ramp targets and clears it on a plain-step improvement; `via[nxt] = -1` on plain improvement and `via[top] = nxt` on ramps reproduces that, including the `via.pop(nxt, None)` for a `nxt` that was never a ramp target.
2. `_RAMPS[lvl]` in Python iterates `+1` then `-1`, each only when in range, and each ramp's toll is `_LEVEL_TOLL[lvl + step]`; the `ramp_steps` loop reproduces that order.

Write the `.pyi` stub with the signature shown in Interfaces, and add the extension to `setup.py`:

```python
(
    Extension(
        "flab2bp.layout._route_kernel",
        ["src/flab2bp/layout/_route_kernel.pyx"],
    ),
)
```

Write `src/flab2bp/layout/route_kernel.py`:

```python
"""Backend selection for the compiled routing loops.

``FLAB2BP_ROUTE_KERNEL`` forces one backend: ``python`` or ``cython``.
Unset, the first available of ``cython`` then ``python`` is used.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Literal

BackendName = Literal["python", "cython"]

_candidates: dict[BackendName, Callable[..., object] | None] = {"python": None}
try:
    from flab2bp.layout._route_kernel import astar_flat as _cython_astar

    _candidates["cython"] = _cython_astar
except ImportError:
    _candidates["cython"] = None

_PREFERENCE: tuple[BackendName, ...] = ("cython", "python")


def _choose() -> BackendName:
    forced = os.environ.get("FLAB2BP_ROUTE_KERNEL")
    if forced in ("python", "cython"):
        return forced  # type: ignore[return-value]
    for name in _PREFERENCE:
        if name == "python" or _candidates.get(name) is not None:
            return name
    return "python"


_backend: BackendName = _choose()
_compiled_astar: Callable[..., object] | None = _candidates.get(_backend)


def compiled_available() -> bool:
    return _compiled_astar is not None


def selected_backend() -> BackendName:
    return _backend if _compiled_astar is not None else "python"
```

A forced backend whose extension is missing falls through to `python`, which is what `selected_backend()` then reports.

- [ ] **Step 5: Split `freeform._astar` into wrapper plus loop**

Move the existing loop portion of `_astar` (from `hcache = [-1.0] * (size // LEVELS)` through the end of the `while open_heap:` loop, inclusive, plus the sealed-pocket write-back `if budget is not None: budget["left"] = start_left - expansions` that follows it) into a new module function:

```python
def _astar_python_loop(
    flags: bytearray,
    hist: Sequence[float] | None,
    pressure: float,
    goal_flag: bytearray,
    start_indices: Sequence[int],
    h: Callable[[int], float],
    size: int,
    gh: int,
    xstep: int,
    budget: dict[str, int] | None,
    start_left: int,
    deadline: float | None,
) -> tuple[list[int] | None, int, int, list[int]]:
    """The A* loop as it stood; returns (path indices oldest first, expansions,
    kind 0 found / 1 budget / 2 sealed, settled indices in index order)."""
```

Its body is the moved code with three mechanical changes: it pushes `start_indices` instead of recomputing them from `starts`; on the goal branch it builds the index path (`prev`/`via` walk, then `reversed`) and returns `(path_indices, expansions, 0, [])` after the existing `budget["left"]` write-back; on the budget exits it returns `(None, expansions, 1, [])` after the existing write-backs; when the heap empties it returns `(None, expansions, 2, [i for i, seen_at in enumerate(best) if seen_at != inf])` after the existing write-back. The `AssertionError` cycle guard stays in the walk.

In `_astar`, after `goal_flag` is built, compute the admitted start indices once (the same filter the old push loop used):

```python
start_indices = [
    (s[0] - gx0) * xstep + (s[1] - gy0) * ystep + s[2]
    for s in starts
    if not (s in forbidden_cells or (not canvas.free(s) and s not in owned and s not in released))
]
if not start_indices:
    return _PathSearchResult(None, RouteFailureKind.DYNAMIC_ACCESS, (), 0)
start_left = budget["left"] if budget is not None else 1 << 62
from flab2bp.layout import route_kernel

if route_kernel._compiled_astar is not None:
    near = tuple({(c[0] - gx0, c[1] - gy0) for c in goal_list})
    goal_columns = array("q", [v for pair in near for v in pair])
    goal_box = (
        min(c[0] for c in goal_list) - gx0,
        min(c[1] for c in goal_list) - gy0,
        max(c[0] for c in goal_list) - gx0,
        max(c[1] for c in goal_list) - gy0,
    )
    if not negotiating:
        hist_buffer = array("d")
    elif isinstance(hist, array):
        hist_buffer = hist
    else:
        hist_buffer = array("d", hist)
    path_indices, expansions, kind, settled, left = route_kernel._compiled_astar(
        flags,
        hist_buffer,
        pressure,
        flat.alt_flat,
        len(flat.alt),
        goal_flag,
        goal_columns,
        len(goal_list) <= _EXACT_HEURISTIC_GOALS,
        goal_box,
        array("q", start_indices),
        gh,
        xstep,
        LEVELS,
        array("d", _LEVEL_TOLL),
        _MAX_EXPANSIONS,
        start_left,
        _DEADLINE_CHECK_EVERY,
        deadline,
        _expired,
    )
    if budget is not None:
        budget["left"] = left
else:
    path_indices, expansions, kind, settled = _astar_python_loop(
        flags,
        hist if negotiating else None,
        pressure,
        goal_flag,
        start_indices,
        h,
        size,
        gh,
        xstep,
        budget,
        start_left,
        deadline,
    )
```

Then the common tail: on `kind == 1` return `_PathSearchResult(None, RouteFailureKind.BUDGET, (), expansions)`; on `kind == 0` decode each index with `q, lvl = divmod(index, LEVELS); px, py = divmod(q, gh)` to `(px + gx0, py + gy0, lvl)` and return `_PathSearchResult(tuple(_cut_loops(cells)), None, (), expansions)`; on `kind == 2` run the existing sealed-pocket wall computation iterating `settled` instead of `enumerate(best)`: the `blocking_owners` branch iterates `settled`, and the pocket branch becomes `if len(settled) <= _BLAME_MAX_POCKET:` over `settled`. The heuristic closures (`h`) stay in the wrapper because the Python loop still uses them.

- [ ] **Step 6: Build and run the tests**

```bash
uv run python setup.py build_ext --inplace
uv run pytest tests/layout/test_route_kernel.py -v
uv run pytest tests/layout/test_freeform.py -q
```

Expected: all pass. If the parity test fails on `expansions` or `path`, replay the first differing case under both backends printing each heap pop `(f, g, index)`; the usual causes are the tie order and the float association `run_base + toll2` (add `3.0` to `g` first, then the toll, as the Python code does).

- [ ] **Step 7: Replay digest on captured corpora under both backends**

```bash
uv run python scripts/route_bench.py --capture universe-matrix --budget 8 --cases /tmp/rk-universe.pkl
uv run python scripts/route_bench.py --capture quantum-chip --budget 8 --cases /tmp/rk-quantum.pkl
uv run python scripts/route_bench.py --capture plastic --budget 8 --cases /tmp/rk-plastic.pkl
for f in /tmp/rk-universe.pkl /tmp/rk-quantum.pkl /tmp/rk-plastic.pkl; do
  FLAB2BP_ROUTE_KERNEL=python uv run python scripts/route_bench.py --cases "$f" --rounds 1 --check
  uv run python scripts/route_bench.py --cases "$f" --rounds 3 --check
done
```

Expected: `MATCH` on every file for both backends, and the compiled `us/exp` at least 10x lower than the Python one. Paste the six `BEST` lines into the commit message.

- [ ] **Step 8: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/route_kernel.py src/flab2bp/layout/freeform.py tests/layout/test_route_kernel.py
uv run mypy src/flab2bp/layout/route_kernel.py src/flab2bp/layout/freeform.py tests/layout/test_route_kernel.py
git add setup.py src/flab2bp/layout/_route_kernel.pyx src/flab2bp/layout/_route_kernel.pyi src/flab2bp/layout/route_kernel.py src/flab2bp/layout/freeform.py tests/layout/test_route_kernel.py
git commit -m "perf(layout): compile the detailed A* loop with digest parity"
```

---

### Task 9: Cython relaxed global search

**Files:**
- Modify: `src/flab2bp/layout/_route_kernel.pyx`, `src/flab2bp/layout/_route_kernel.pyi`, `src/flab2bp/layout/route_kernel.py`
- Modify: `src/flab2bp/layout/global_router.py:458-551` (`_search_relaxed`)
- Test: `tests/layout/test_global_router.py`

**Interfaces:**
- Consumes: `_routing_transitions(xstep)` tuples `(target offset, via offset, dx, dy, base cost)` per level; `_CapacityLedger.present_cost(index, compatible)`; `feedback.net_weight`; `route_global_once(problem, feedback, budget, *, cancelled=None)`.
- Produces:

```python
def relaxed_search_flat(
    flags: bytearray,
    present: array[float],          # dense: _PRESENT_COST * ledger.present_cost(index, compatible), 0.0 elsewhere
    history: array[float],          # grid.hist as doubles, or zero-length when None
    weight: float,
    transitions_target: array[int], # per level: [count, offsets...] repeated for each level
    transitions_via: array[int],    # same layout; 0 for a flat step
    transitions_cost: array[float], # same layout; the count slot holds 0.0
    starts: array[int],
    goals: array[int],              # sorted goal indices
    goal_xy: array[int],            # (x, y) local pairs in the same sorted order
    gh: int,
    levels: int,
    budget: int,
    cancelled: Callable[[], bool] | None,
) -> tuple[array[int] | None, int, bool, bool]:  # (path indices oldest first, expansions, exhausted, cancelled)
```

`route_kernel._compiled_relaxed` is the imported `relaxed_search_flat` or `None`, with the same `FLAB2BP_ROUTE_KERNEL=python` override as `_compiled_astar`.

- [ ] **Step 1: Write the failing parity test**

Add to `tests/layout/test_global_router.py` (add `import random` and `from flab2bp.layout.freeform import LEVELS` at the top if absent; `route_global_once`, `NetId`, `NetRole`, `_problem`, `_feedback` are already used there):

```python
def test_compiled_relaxed_search_matches_python(monkeypatch: pytest.MonkeyPatch) -> None:
    from flab2bp.layout import route_kernel

    assert route_kernel.compiled_available()
    rng = random.Random(7)
    for trial in range(20):
        width = rng.randint(6, 18)
        height = rng.randint(4, 12)
        bounds = (0, 0, width - 1, height - 1)
        blocked = {
            (rng.randrange(width), rng.randrange(height), rng.randrange(LEVELS))
            for _ in range(rng.randint(0, width * height // 3))
        }
        a = NetId(0, 1, "iron", NetRole.INTERNAL, 0)
        b = NetId(2, 3, "copper", NetRole.INTERNAL, 1)
        problem = _problem(
            (
                (a, (0, 1), (width - 1, 1), (), (), ()),
                (b, (0, height - 2), (width - 1, height - 2), (), (), ()),
            ),
            bounds=bounds,
            blocked=sorted(blocked),
        )
        history = {cell: rng.random() for cell in blocked} if trial % 2 else {}
        feedback = _feedback(problem, history)

        compiled_result = route_global_once(problem, feedback, 5000)
        monkeypatch.setattr(route_kernel, "_compiled_relaxed", None)
        python_result = route_global_once(problem, feedback, 5000)
        monkeypatch.undo()

        assert compiled_result == python_result, f"trial {trial}"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/layout/test_global_router.py::test_compiled_relaxed_search_matches_python -v`
Expected: FAIL with `AttributeError: module 'flab2bp.layout.route_kernel' has no attribute '_compiled_relaxed'`

- [ ] **Step 3: Add the kernel function and wrapper**

Append to `_route_kernel.pyx` (reusing `_Heap`; the relaxed heap also orders on `(f, cost, index)` because `heapq` compares the whole tuple):

```cython
cdef inline double _congestion(long long index, double weight, const double[::1] present,
                               bint has_history, const double[::1] history) noexcept nogil:
    cdef double historical = history[index] if has_history else 0.0
    return weight * (present[index] + historical)


cdef inline double _relaxed_h(long long index, long long gh, long long levels,
                              const long long[::1] goal_xy) noexcept nogil:
    cdef long long column = index // levels
    cdef long long x = column // gh
    cdef long long y = column - x * gh
    cdef long long closest = -1, distance, k, gx, gy
    cdef long long count = goal_xy.shape[0] // 2
    for k in range(count):
        gx = goal_xy[2 * k]
        gy = goal_xy[2 * k + 1]
        distance = (x - gx if x >= gx else gx - x) + (y - gy if y >= gy else gy - y)
        if closest < 0 or distance < closest:
            closest = distance
    return <double> closest


def relaxed_search_flat(
    unsigned char[::1] flags,
    const double[::1] present,
    const double[::1] history,
    double weight,
    const long long[::1] transitions_target,
    const long long[::1] transitions_via,
    const double[::1] transitions_cost,
    const long long[::1] starts,
    const long long[::1] goals,
    const long long[::1] goal_xy,
    long long gh,
    long long levels,
    long long budget,
    object cancelled,
):
    cdef Py_ssize_t size = flags.shape[0]
    cdef bint has_history = history.shape[0] > 0
    cdef double* best = NULL
    cdef long long* predecessor = NULL
    cdef long long* via = NULL
    cdef unsigned char* is_goal = NULL
    cdef long long level_start[16]
    cdef long long level_count[16]
    cdef Py_ssize_t i, pos = 0
    cdef long long lv, s, level, t, target, run, node, found = -1, expansions = 0
    cdef double cost0, cost, next_cost
    cdef bint exhausted = False, was_cancelled = False
    cdef _Heap heap
    cdef Entry cur

    if levels > 16:
        raise ValueError("relaxed_search_flat supports at most 16 levels")
    best = <double*> malloc(size * sizeof(double))
    predecessor = <long long*> malloc(size * sizeof(long long))
    via = <long long*> malloc(size * sizeof(long long))
    is_goal = <unsigned char*> malloc(size)
    if best == NULL or predecessor == NULL or via == NULL or is_goal == NULL:
        raise MemoryError()
    try:
        for i in range(size):
            best[i] = INFINITY
            predecessor[i] = -2
            via[i] = -1
            is_goal[i] = 0
        for i in range(goals.shape[0]):
            is_goal[goals[i]] = 1
        for lv in range(levels):
            level_count[lv] = transitions_target[pos]
            level_start[lv] = pos + 1
            pos += 1 + level_count[lv]

        heap = _Heap(1024)
        for i in range(starts.shape[0]):
            s = starts[i]
            cost0 = _congestion(s, weight, present, has_history, history)
            if cost0 < best[s]:
                best[s] = cost0
                predecessor[s] = -1
                heap.push(cost0 + _relaxed_h(s, gh, levels, goal_xy), cost0, s)

        while heap.size > 0:
            if cancelled is not None and cancelled():
                was_cancelled = True
                break
            cur = heap.pop()
            cost = cur.g
            if cost > best[cur.index]:
                continue
            if expansions >= budget:
                exhausted = True
                break
            expansions += 1
            if is_goal[cur.index]:
                found = cur.index
                break
            level = cur.index % levels
            for t in range(level_count[level]):
                target = cur.index + transitions_target[level_start[level] + t]
                if not flags[target]:
                    continue
                run = -1
                if transitions_via[level_start[level] + t] != 0:
                    run = cur.index + transitions_via[level_start[level] + t]
                    if not flags[run]:
                        continue
                next_cost = (
                    cost
                    + transitions_cost[level_start[level] + t]
                    + _congestion(target, weight, present, has_history, history)
                )
                if run != -1:
                    next_cost += _congestion(run, weight, present, has_history, history)
                if next_cost >= best[target]:
                    continue
                best[target] = next_cost
                predecessor[target] = cur.index
                via[target] = run
                heap.push(next_cost + _relaxed_h(target, gh, levels, goal_xy), next_cost, target)

        path = None
        if found != -1:
            out = array("q")
            node = found
            while node != -1:
                out.append(node)
                if via[node] != -1:
                    out.append(via[node])
                node = predecessor[node]
            out.reverse()
            path = out
        return path, expansions, exhausted, was_cancelled
    finally:
        free(best)
        free(predecessor)
        free(via)
        free(is_goal)
```

Exactness notes: Python computes `weight * (_PRESENT_COST * present + historical)` with `_PRESENT_COST = 1.0`; the wrapper pre-multiplies `present` by `_PRESENT_COST` so the kernel's `weight * (present + historical)` is the same double. Python's `next_cost = cost + base_cost + congestion(target)` associates left to right; the kernel's expression keeps that order. The Python heuristic is an `int`; the kernel returns it as a double, and `next_cost + heuristic` is the same double either way.

In `global_router._search_relaxed`, keep the early returns and, after `weight` is computed, branch on the backend:

```python
from flab2bp.layout import route_kernel

if route_kernel._compiled_relaxed is not None:
    present = array("d", bytes(8 * grid.size))
    for index in ledger.units:
        present[index] = _PRESENT_COST * ledger.present_cost(index, compatible)
    targets = array("q")
    vias = array("q")
    costs = array("d")
    for level_transitions in _routing_transitions(grid.xstep):
        targets.append(len(level_transitions))
        vias.append(len(level_transitions))
        costs.append(0.0)
        for target_offset, via_offset, _dx, _dy, base_cost in level_transitions:
            targets.append(target_offset)
            vias.append(via_offset)
            costs.append(base_cost)
    sorted_goals = sorted(goal_set)
    goal_xy = array("q", [value for goal in sorted_goals for value in _local_xy(grid, goal)])
    if history is None:
        history_buffer = array("d")
    elif isinstance(history, array):
        history_buffer = history
    else:
        history_buffer = array("d", history)
    path_indices, expansions, exhausted, was_cancelled = route_kernel._compiled_relaxed(
        flags,
        present,
        history_buffer,
        weight,
        targets,
        vias,
        costs,
        array("q", starts),
        array("q", sorted_goals),
        goal_xy,
        grid.gh,
        LEVELS,
        budget,
        cancelled,
    )
    if path_indices is None:
        return _SearchResult(None, expansions, exhausted, was_cancelled)
    cells = [_decode_cell(grid, index) for index in path_indices]
    return _SearchResult(tuple(_cut_loops(cells)), expansions, exhausted, was_cancelled)
```

The Python loop below it is unchanged. In `route_kernel.py`, add beside `_compiled_astar`:

```python
_compiled_relaxed: Callable[..., object] | None
try:
    from flab2bp.layout._route_kernel import relaxed_search_flat as _compiled_relaxed
except ImportError:
    _compiled_relaxed = None
if _backend == "python":
    _compiled_relaxed = None
```

The relaxed search and the A* loop share the one Cython extension; a forced `python` backend disables both. Add the `.pyi` entry for `relaxed_search_flat`.

- [ ] **Step 4: Build and run the tests**

```bash
uv run python setup.py build_ext --inplace
uv run pytest tests/layout/test_global_router.py tests/layout/test_sequence_solver.py -q
```

Expected: all pass, including the 20-trial parity test.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/global_router.py src/flab2bp/layout/route_kernel.py tests/layout/test_global_router.py
uv run mypy src/flab2bp/layout/global_router.py src/flab2bp/layout/route_kernel.py tests/layout/test_global_router.py
git add src/flab2bp/layout/_route_kernel.pyx src/flab2bp/layout/_route_kernel.pyi src/flab2bp/layout/route_kernel.py src/flab2bp/layout/global_router.py tests/layout/test_global_router.py
git commit -m "perf(layout): compile the relaxed global search"
```

---

### Task 10: Record the routing backend in placement stats and the profiler

**Files:**
- Modify: `scripts/route_profile.py` (JSON field `route_backend`)
- Modify: `src/flab2bp/layout/sequence_solver.py:5352` (the `placement.stats` dict that sets `"backend": "sequence-pair"`)
- Modify: `src/flab2bp/layout/freeform.py` (`FreeformLayout.lay_out`, before each `return placement`)
- Test: `tests/bench/test_route_profile.py`, `tests/layout/test_sequence_solver.py:5368`

**Interfaces:**
- Consumes: `route_kernel.selected_backend()`.
- Produces: `"route_backend": "cython" | "python"` in the profiler JSON and in `placement.stats["route_backend"]` for both strategies.

- [ ] **Step 1: Write the failing tests**

In `tests/bench/test_route_profile.py`, add `"route_backend": route_kernel.selected_backend(),` to the expected JSON dict of `test_json_profile_emits_one_bounded_machine_readable_record`, importing `from flab2bp.layout import route_kernel`. In `tests/layout/test_sequence_solver.py` at line 5368, beside `assert backend == "sequence-pair"`, add:

```python
    assert placement.stats["route_backend"] == route_kernel.selected_backend()
```

with the same import. In `tests/layout/test_freeform.py`, add:

```python
def test_freeform_placement_records_route_backend() -> None:
    from flab2bp.layout import route_kernel

    placement = FreeformLayout(band_policy=BandPolicy("portable"), workers=1).lay_out(
        two_stage_spec(), time_budget_s=4.0
    )
    assert placement.stats["route_backend"] == route_kernel.selected_backend()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/bench/test_route_profile.py tests/layout/test_sequence_solver.py tests/layout/test_freeform.py -q -k "json_profile or backend"`
Expected: FAIL on the missing key.

- [ ] **Step 3: Add the field**

In `route_profile.main` JSON dict: `"route_backend": route_kernel.selected_backend(),` with `from flab2bp.layout import route_kernel` at the top. In `sequence_solver.py:5352`, add `"route_backend": route_kernel.selected_backend(),` beside `"backend": "sequence-pair",` with a module-level import. In `FreeformLayout.lay_out`, set `placement.stats["route_backend"] = route_kernel.selected_backend()` immediately before every `return placement` in that method, with a lazy import inside the method.

- [ ] **Step 4: Run the tests, lint, type-check, commit**

```bash
uv run pytest tests/bench/test_route_profile.py tests/layout/test_sequence_solver.py tests/layout/test_freeform.py -q
uv run ruff check scripts/route_profile.py src/flab2bp/layout/sequence_solver.py src/flab2bp/layout/freeform.py
uv run mypy scripts/route_profile.py src/flab2bp/layout/sequence_solver.py src/flab2bp/layout/freeform.py
git add scripts/route_profile.py src/flab2bp/layout/sequence_solver.py src/flab2bp/layout/freeform.py tests/bench/test_route_profile.py tests/layout/test_sequence_solver.py tests/layout/test_freeform.py
git commit -m "bench: report the routing kernel backend in placement stats"
```

---

### Task 11: Corpus-wide preparation parity, the 30-second gate, and evidence

**Files:**
- Create: `scripts/prepare_parity.py`
- Create: `docs/superpowers/evidence/2026-09-01-evaluation-throughput/profile-after.jsonl`
- Create: `docs/superpowers/evidence/2026-09-01-evaluation-throughput/prepare-parity.txt`
- Create: `docs/superpowers/evidence/2026-09-01-evaluation-throughput/candidate-budget30-round{1,2,3}.jsonl`
- Create: `docs/superpowers/evidence/2026-09-01-evaluation-throughput/gate.md`

**Interfaces:**
- Consumes: `scripts/audit.py --json`, `scripts/audit_compare.py` (Task 1), `scripts/route_profile.py --json` (Task 2), `geometry_memo.for_spec` (Task 7), `flab2bp.bench.corpus.URL_CORPUS`, `flab2bp.rates.candidates.build_candidates`, `flab2bp.lab.data.load_vendored`, `flab2bp.lab.url.parse_url`.
- Produces: the committed gate record.

- [ ] **Step 1: Write the corpus-wide preparation parity script**

```python
# scripts/prepare_parity.py
"""Prove the shared geometry memo changes no prepared problem on any corpus spec.

    uv run python scripts/prepare_parity.py

For every corpus URL and candidate policy, prepare the greedy pack once with a
private cache and twice with the spec-scoped memo, and require structural
equality.  Exits non-zero on the first mismatch.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from flab2bp.bench.corpus import URL_CORPUS  # noqa: E402
from flab2bp.lab.data import load_vendored  # noqa: E402
from flab2bp.lab.url import parse_url  # noqa: E402
from flab2bp.layout import geometry_memo  # noqa: E402
from flab2bp.layout.band_policy import BandPolicy  # noqa: E402
from flab2bp.layout.freeform import (  # noqa: E402
    _greedy_pack,
    _height_seed,
    _prepare_routing_problem,
    plan_strips,
)
from flab2bp.rates.candidates import DEFAULT_CANDIDATE_POLICIES, build_candidates  # noqa: E402


def main() -> int:
    data = load_vendored()
    policy = BandPolicy("portable")
    checked = 0
    for entry in URL_CORPUS:
        specs = build_candidates(
            data, parse_url(entry.url), candidate_policies=DEFAULT_CANDIDATE_POLICIES
        ).candidates
        for spec in specs:
            strips = plan_strips(spec, strip_len=6, band_policy=policy)
            pack = _greedy_pack(strips, _height_seed(strips))
            cold = _prepare_routing_problem(spec, strips, pack, policy=policy, power=True)
            shared = geometry_memo.for_spec(spec)
            for repeat in (1, 2):
                warm = _prepare_routing_problem(
                    spec, strips, pack, policy=policy, power=True, staged_static_cache=shared
                )
                if warm != cold:
                    print(f"MISMATCH {entry.url_id}/{spec.label} on repeat {repeat}")
                    return 1
            checked += 1
            print(f"ok {entry.url_id}/{spec.label}")
    print(f"PARITY {checked} specs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Run it and save the output:

```bash
uv run python scripts/prepare_parity.py | tee docs/superpowers/evidence/2026-09-01-evaluation-throughput/prepare-parity.txt
```

Expected: the last line is `PARITY 36 specs` and the exit code is 0.

- [ ] **Step 2: Record the after profile on the same cells as Task 2**

Run the Task 2 Step 5 loop writing to `profile-after.jsonl`, then print before and after side by side:

```bash
uv run python - <<'EOF'
import json
d = "docs/superpowers/evidence/2026-09-01-evaluation-throughput/"
def load(name):
    return {(r["url_id"], r["strategy"], r["budget_s"]): r for r in map(json.loads, open(d + name))}
before, after = load("profile-before.jsonl"), load("profile-after.jsonl")
for key in before:
    b, a = before[key], after.get(key)
    if a is None:
        continue
    pb = (b["prepare_calls_s"] or [0.0])[0]
    pa = (a["prepare_calls_s"] or [0.0])[0]
    print(key, f"prepare first {pb:.2f} -> {pa:.2f}", f"astar {b['astar_s']:.2f} -> {a['astar_s']:.2f}",
          f"wall {b['wall_s']:.1f} -> {a['wall_s']:.1f}", b["verdict"][:8], "->", a["verdict"][:8])
EOF
```

Expected: first-candidate `prepare` on `universe-matrix` at or under 1.0 s and `astar_s` at or under 0.2 s. If either goal is missed, stop here, write the numbers and the phase breakdown that explains the miss into `gate.md`, commit the evidence under `bench: record an evaluation throughput profile that misses its goal`, and report; do not run the audit.

- [ ] **Step 3: Run the three-round corpus audit**

```bash
d=docs/superpowers/evidence/2026-09-01-evaluation-throughput
for r in 1 2 3; do
  uv run python scripts/audit.py --budget 30 --jobs 16 --json "$d/candidate-budget30-round$r.jsonl" | tail -5
done
for r in 1 2 3; do
  uv run python scripts/audit_compare.py "$d/baseline-budget30.jsonl" "$d/candidate-budget30-round$r.jsonl" --p95-seconds 30
done
```

Expected: every round prints `clean 72  refused 0  invalid 0  crashed 0 ... PASS`, and the audit's own summary reports 72/72.

- [ ] **Step 4: Write the gate record**

`gate.md` contains: the commit hash under test and the baseline commit hash from Task 1; the three `audit_compare` output lines verbatim; the before/after profile table from Step 2; the last line of `prepare-parity.txt`; the `route_bench` `BEST` lines under `python` and `cython` from Task 8 Step 7; and one line per gate condition stating pass or fail. No prose beyond that.

- [ ] **Step 5: Full suite, lint, type-check, commit**

```bash
uv run python setup.py build_ext --inplace
uv run pytest -q
uv run ruff check .
uv run mypy
git add scripts/prepare_parity.py docs/superpowers/evidence/2026-09-01-evaluation-throughput
git commit -m "bench: record the 30s corpus gate for evaluation throughput"
```

If any round fails the gate, commit the evidence under the message `bench: record a failed 30s corpus gate` with `gate.md` naming the failing cells and their `detail` strings, and report.
