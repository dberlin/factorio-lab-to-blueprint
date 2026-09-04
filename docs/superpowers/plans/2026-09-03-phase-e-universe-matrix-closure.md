# Phase E Universe-Matrix Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the six refusing `universe-matrix` cells by seating a both-fed ingredient on the outermost lane row, making the band ceiling bind in both strategies, reporting refusals honestly with solver stats on REFUSED audit rows, and spending the remaining clock on `universe-matrix/no-proliferator` only where measurement says it can buy something.

**Architecture:** Four independently gated groups. First, a strip-generation fix (one sort key plus a seated-row normalisation in `strip_variants._logical_strip_plans`) that R4 measured from 66/72 to 70/72 with zero regressions. Second, two height-generation changes: freeform's band-reservation witness becomes the constructive greedy seed width, and sequence-pair's height schedule is pulled below the band's core boundary with a named approach step. Third, observability: a seed gate that no longer masquerades as a validator rejection, a freeform refusal that names port seating instead of the packer, and `NoValidLayout.stats` carried onto `audit.Result.stats` so a REFUSED row is attributable. Fourth, the `no-proliferator` levers: a product probe over the sequence-pair operator portfolio with drop counters, and a staleness-guarded freeform continuation with a diversification cut and a widened window trigger.

**Tech Stack:** Python 3.14, ortools CP-SAT 9.15, Cython kernels (`_sequence_kernel`, `_route_kernel`), pytest (serial), Ruff, strict MyPy, `uv run`.

**Spec:** `docs/superpowers/specs/2026-09-03-phase-e-universe-matrix-closure-design.md`

**Research:** `docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/research/research-R1-height-ceiling.md`, `research-R2-sweep-exhaustion.md`, `research-R3-sequence-pair.md`, `research-R4-stranded-nets.md`

**Plan reviews applied:** `.superpowers/sdd/2026-09-03-phase-e-universe-matrix-closure/plan-review-A.md` (spec and structure) and `plan-review-B.md` (code grounding). Every Critical and Important finding from both, and every Minor that was a factual correction, is folded in. Where the two disagreed, the task that carries the decision says which was followed.

## Global Constraints

- **Symbol-tool activation (every implementer and reviewer, first thing).** The tools are deferred, so load them explicitly: `ToolSearch("select:mcp__serena__activate_project,mcp__serena__initial_instructions,mcp__serena__find_symbol,mcp__serena__find_referencing_symbols,mcp__serena__get_symbols_overview,LSP")`, then `mcp__serena__activate_project` with the absolute path of the checkout you are editing (the worktree, not the main repository), then `mcp__serena__initial_instructions`. Every symbol is resolved with `find_symbol` (`include_body=True` to read a body) and every call site with `find_referencing_symbols`. If either errors or returns nothing for a symbol that exists, use the `LSP` tool (goToDefinition / findReferences). Never substitute grep for a symbol lookup.
- **Serena's `find_implementations` is unusable on this language server.** Do not call it; enumerate protocol implementers by reading the module that declares the protocol and by `find_referencing_symbols` on the protocol symbol.
- **Grep for the QUOTED name whenever a signature or arity changes.** `monkeypatch.setattr(module, "name", ...)` sites are string literals and are invisible to a language server. Every task that changes a signature ends its edit step with `grep -rn '"<name>"' src tests scripts` and fixes every stub the change reaches.
- **No test may name a symbol that does not exist on master.** Resolve every helper a test calls with `find_symbol` before writing the test. Two traps this plan already paid for: `tests/layout/test_freeform.py::_routing_failures(*kinds)` returns a **ROUTED** result when called with no kinds (it is the file's fully-routed fixture), and there is no `_routed` helper at all. Every test must fail on master before its task and pass after; each test step states the failure master produces.
- **Every `file:line` in the spec and in R1 to R4 was read at `e0bf432` and is a hint only.** Resolve each target by symbol name before editing.
- **No wall-clock assertions in tests (Ruling S).** Continuation and deadline behaviour is pinned with a fake `time.monotonic` (`monkeypatch.setattr(freeform.time, "monotonic", counter)`, the pattern at `tests/layout/test_freeform.py:3941`) and injected packs. The two wall-clock tests removed during Phase B must not be reintroduced.
- **Never wait for an idle box.** This is a 128-core machine whose load is I/O wait. Record `uptime` and `vmstat 1 3` immediately before every timed run and paste the output into the evidence file; never postpone a measurement because the load average is non-zero.
- **Any constant whose value collides with a linted game value is declared through `registry.LintException` (Ruling AI), never re-spelled.** This applies to `C_SWEEP_STALE_DRAWS` and `C_CEILING_APPROACH_STEP` if either collides.
- **Commit trailer on every commit**, after a blank line:

  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01KufubYYxUsR9JHQo5xHPtv
  ```
- **Explicit-path commits only.** `git add <exact paths>`, never `git add -A` or `git add .`. Never `git stash`, never `git checkout --`, never `git reset`. A wrong edit is fixed with another edit.
- **Shared files are edited by one agent at a time**: `src/flab2bp/layout/freeform.py`, `src/flab2bp/layout/sequence_solver.py`, `src/flab2bp/layout/sequence_alns.py`, `src/flab2bp/layout/strip_variants.py`, `scripts/audit.py`. Never run two tasks that touch the same file concurrently.
- **Each task is implemented by a fresh subagent and reviewed read-only by an opus reviewer working from an archived commit** (spec §8). The reviewer never edits the worktree.
- **Every task leaves the tree green**: `uv run pytest -q` (serial, never `-n auto`: one CP-SAT solve already runs at ~700% CPU), `uv run ruff check .`, `uv run mypy` with **no new diagnostic against the locked baseline of 184**. The pytest summary line does not print in this environment; the exit code is the verdict, and the 120 s `pytest-timeout` backstop hard-kills a run rather than failing one test.
- **`scripts/audit.py --json PATH` opens PATH in APPEND mode.** `rm -f` every JSONL target before writing it, or a re-run doubles the rows and breaks `--expect-cells 72`.
- **Evidence lives under `docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/`**, except per-task intermediate probes, which may live in `/tmp` and are summarised in the commit message. Nothing under `.superpowers/` is ever committed.
- **The racing default stays `race=False` and the default budget is unchanged.** No task touches `pipeline.build`'s `race` parameter, the CLI defaults, or the web contract.
- **No geometry rule is relaxed.** `_seat_inputs`' row caps, `_side_seatings`' reach profiles, the attachment plan, sorter tiers, `finalize_placement` and the validator are untouched. Explicit `--arrangements` and `max_stages` remain hard caps.
- Commit messages: imperative, sentence case, no trailing period.
- A step whose measurement misses its stated goal is **not** committed as if it passed: record the numbers and report.

---

### Task 1: Baseline rounds and the phase evidence ledger

**Files:**
- Create: `docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/baseline-budget30-round{1,2,3}.jsonl`
- Create: `docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/baseline.md`

**Interfaces:**
- Consumes: `scripts/audit.py --budget 30 --jobs 16 --json PATH`; `scripts/audit_compare.py BASELINE CANDIDATE [--noise-area F] [--p95-seconds F] [--expect-cells N] [--regressions-only] [--require-clean strategy/url_id/spec_label]`.
- Produces: the three baseline JSONL files, and `baseline.md` whose **first line is exactly** `branch point: <40-hex hash>`. Gates E1 and E2 read that hash out of this file; they never derive it from `origin/master` or `HEAD~N`.

- [ ] **Step 1: Create the worktree and the branch**

```bash
set -e
cd /home/dannyb/sources/factorio-lab-to-blueprint
BRANCH_POINT=$(git rev-parse HEAD)
echo "branch point: $BRANCH_POINT"
git worktree add ../flab2bp-phase-e -b phase-e-universe-matrix
cd ../flab2bp-phase-e
uv sync
uv run python setup.py build_ext --inplace
```

Expected: a clean worktree at the branch point with both Cython kernels built in place. Keep `$BRANCH_POINT`: Step 6 writes it into `baseline.md`.

- [ ] **Step 2: Confirm the tree is green before measuring**

```bash
uv run pytest -q; echo "pytest exit=$?"
uv run ruff check .
uv run mypy 2>&1 | tail -3
```

Expected: `pytest exit=0`, ruff clean, mypy reporting exactly 184 errors.

- [ ] **Step 3: Record the box load and run three baseline rounds**

```bash
set -e
d=docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix
mkdir -p "$d"
for r in 1 2 3; do
  rm -f "$d/baseline-budget30-round$r.jsonl"
  { echo "== round $r"; uptime; vmstat 1 3; } >> "$d/baseline-load.txt"
  uv run python scripts/audit.py --budget 30 --jobs 16 \
    --json "$d/baseline-budget30-round$r.jsonl" | tail -8
done
wc -l "$d"/baseline-budget30-round*.jsonl
```

Expected: 72 rows per file, about two to four minutes each, `66/72` clean in every round with the six refusing cells being exactly `universe-matrix/{no-proliferator,output-products,all-products}` under both strategies (R4 §7).

- [ ] **Step 4: Extract the figures the gates will judge**

```bash
uv run python - <<'EOF'
import json, math, pathlib
d = pathlib.Path("docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix")
for r in (1, 2, 3):
    rows = [json.loads(line) for line in (d / f"baseline-budget30-round{r}.jsonl").open()]
    secs = sorted(row["seconds"] for row in rows)
    p95 = secs[min(len(secs) - 1, math.ceil(0.95 * len(secs)) - 1)]
    clean = sum(row["status"] == "CLEAN" for row in rows)
    misses = sorted(
        f'{row["strategy"]}/{row["url_id"]}/{row["spec_label"]}'
        for row in rows
        if row["status"] != "CLEAN"
    )
    print(f"round{r}: clean {clean}/{len(rows)}  p95 {p95:.2f}s  max {secs[-1]:.2f}s "
          f"invalid {sum(x['status'] == 'INVALID' for x in rows)} "
          f"crash {sum(x['status'] == 'CRASH' for x in rows)}")
    for miss in misses:
        print(f"    MISS {miss}")
EOF
```

Expected, per round: `clean 66/72`, `invalid 0`, `crash 0`, and six MISS lines all naming `universe-matrix`.

- [ ] **Step 5: Prove a REFUSED row carries no stats today**

```bash
uv run python -c "
import json
rows = [json.loads(l) for l in open('docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/baseline-budget30-round1.jsonl')]
refused = [r for r in rows if r['status'] == 'REFUSED']
print(len(refused), 'refused rows; stats keys:', sorted({k for r in refused for k in r.get('stats', {})}))
"
```

Expected: `6 refused rows; stats keys: []`. This is the blocker Task 7 removes and R3 §5.3 measured; recording it here makes Gate E1's "every REFUSED row carries a non-empty `stats` object" clause a before/after statement rather than an assertion.

- [ ] **Step 6: Write `baseline.md`**

Its **first line must be exactly** `branch point: <hash>` (the `$BRANCH_POINT` from Step 1), because Gate E1 Step 2 parses that line with `sed -n 's/^branch point: //p'` and fails the step if it does not resolve. After it, `baseline.md` contains: the three Step 4 blocks verbatim; the six refusing cells with their `detail` strings copied from the round-1 JSONL; the Step 5 output; and the three `uptime`/`vmstat` blocks from `baseline-load.txt`.

- [ ] **Step 7: Commit**

```bash
git add docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix
git commit -m "bench: record the phase E baseline at budget 30

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KufubYYxUsR9JHQo5xHPtv"
```

---

### Task 2: Seat a both-fed ingredient on the outermost lane row

Spec §5.1. Carries the seating rule, its invariant, its tests and the `twice` documentation correction together, because the docstring correction is the reason the rule is expressed on seated rows rather than on the router's demand (R4 §6 E1 proved narrowing `twice` fails).

**Files:**
- Modify: `src/flab2bp/layout/strip_variants.py` (`_logical_strip_plans`, plus a new module-level `_seat_both_fed_outermost`)
- Modify: `src/flab2bp/layout/freeform.py` (`_reserve_port_access`'s `twice` paragraph; the comment above `shared_feed` inside `_prepare_routing_problem.hold_ports`)
- Test: `tests/layout/test_strip_variants.py`, `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `strip_variants._logical_strip_plans(spec, *, prefer_shared_proliferation=False) -> tuple[_LogicalStripPlan, ...]`; `freeform._seat_inputs(items, n_sinks, above_cap, below_cap, max_per_lane, columns, *, flank_outputs=False, prefer_shared=False, lane_fits=None)`; `freeform.plan_strips(spec, *, strip_len=6, ...) -> list[Strip]`; `Strip.row_of_input(item) -> int`; `freeform._box(strip) -> tuple[int, int]`.
- **Corpus-spec construction, verified on master** (`src/flab2bp/pipeline.py` and `scripts/audit.py` use exactly these): `from flab2bp.bench.corpus import URL_CORPUS`, `from flab2bp.lab.data import load_vendored`, `from flab2bp.lab.url import parse_url`, `from flab2bp.rates.candidates import CandidatePolicy, DEFAULT_CANDIDATE_POLICIES, build_candidates`. **There is no `flab2bp.rates.vendor` and no `flab2bp.url`.**
- Produces: `strip_variants._seat_both_fed_outermost(in_above, in_below, both_fed) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...]]`. No existing signature changes.

- [ ] **Step 1: Read the four symbols before editing**

`find_symbol` with `include_body=True` on `strip_variants/_logical_strip_plans`, `strip_variants/_input_logical_lanes`, `freeform/_seat_inputs` and `freeform/Strip/row_of_input`. Confirm five facts, and stop and report if any is false:

1. `_logical_strip_plans` builds `producers: dict[str, list[str]]` over every group's outputs *before* the per-group loop, so `frozenset(producers)` is exactly the internally produced item set.
2. `_seat_inputs` slices `lanes = [tuple(items[i : i + k]) for i in range(0, n, k)]` and returns `tuple(lanes[:a]), tuple(lanes[a:])`, so lane order follows `items` order on both sides.
3. `Strip.row_of_input` returns `self.in_above.index(lane)` for an `in_above` lane and `first_row_below_band + len(out_lanes) + self.in_below.index(lane)` for an `in_below` one. **`in_above`'s outermost row is index 0; `in_below`'s outermost row is the LAST index.** That asymmetry is why the rule cannot be expressed on `input_items` order alone (R4 open item 2).
4. `_input_logical_lanes` labels `in_above` lanes `side="south", side_index=index` and `in_below` lanes `side="north", side_index=output_count + index` — the LOGICAL side names are the mirror of the `Strip` field names, and `plan_strips` reads `lane.side == "south"` into `Strip.in_above`. Order is preserved on both sides; the naming is not, so never reason from the `LogicalLane.side` string.
5. `_box` (not `_size`) is what charges the margin: `return s.width + s.west_channel + MARGIN, s.height + MARGIN` with `MARGIN = 1`. That is the coupling the rule relies on.

- [ ] **Step 2: Write the failing seating tests**

Append to `tests/layout/test_strip_variants.py`:

```python
def _corpus_spec(url_id: str, policy: CandidatePolicy) -> BuildSpec:
    from flab2bp.bench.corpus import URL_CORPUS
    from flab2bp.lab.data import load_vendored
    from flab2bp.lab.url import parse_url
    from flab2bp.rates.candidates import build_candidates

    entry = next(e for e in URL_CORPUS if e.url_id == url_id)
    return build_candidates(
        load_vendored(),
        parse_url(entry.url),
        candidate_policies=(policy,),
    ).candidates[0]


def test_an_ingredient_fed_from_outside_and_inside_takes_the_outermost_lane_row() -> None:
    """The `hydrogen` lane head must have a second free 4-neighbour.

    R4 §1.2 measured both failing ports as the WEST HEAD TILE of the MIDDLE
    input lane: east is its own lane's second tile, north is the sibling lane
    above, south is the sibling lane below or its own machine band, and only the
    `WEST_CHANNEL` tile is free.  `_reserve_port_access` then reports
    `wants=2 held=1`.  The outermost `in_above` row is the one whose north
    neighbour is the free margin row `_box` charges (`height + MARGIN`,
    MARGIN = 1) and `_greedy_pack` leaves above every strip.

    `universe-matrix` is the only corpus spec where `hydrogen` is BOTH an
    external input and internally produced (R4 §4), which is why the same two
    strips wire cleanly in `casimir-crystal`, `energy-matrix` and `quantum-chip`.
    """
    from flab2bp.rates.candidates import CandidatePolicy

    spec = _corpus_spec("universe-matrix", CandidatePolicy.NO_PROLIFERATOR)
    strips = {strip.group_key: strip for strip in plan_strips(spec)}

    for group_key in ("casimir-crystal#1", "energy-matrix#12"):
        strip = strips[group_key]
        assert strip.in_above[0] == ("hydrogen",), group_key
        assert strip.row_of_input("hydrogen") == 0, group_key


def test_the_seating_rule_changes_no_strip_dimension() -> None:
    """R4 §6 E6 measured `box_height` and `width` unchanged on both strips."""
    from flab2bp.rates.candidates import CandidatePolicy

    spec = _corpus_spec("universe-matrix", CandidatePolicy.NO_PROLIFERATOR)
    strips = {strip.group_key: strip for strip in plan_strips(spec)}

    assert (strips["casimir-crystal#1"].box_height, strips["casimir-crystal#1"].width) == (8, 12)
    assert (strips["energy-matrix#12"].box_height, strips["energy-matrix#12"].width) == (8, 36)


def test_every_both_fed_ingredient_is_seated_on_its_side_s_outermost_row() -> None:
    """The invariant, over every corpus spec.

    Stated as geometry: a lane head must have at least as many free
    4-neighbours as the number of independent feeds the lane accepts.  The strip
    builder's only lever is row order, so it can guarantee this for at most two
    lanes per strip -- `in_above`'s first row and `in_below`'s last.  A recipe
    with three both-fed ingredients would refuse again; R4 §8(B)'s staircase is
    the recorded answer and is out of this phase.

    Runs the LOGICAL planner rather than `plan_strips`: it owns the rule, it is
    pure, and it costs no physical variant enumeration.
    """
    from flab2bp.bench.corpus import URL_CORPUS
    from flab2bp.lab.data import load_vendored
    from flab2bp.lab.url import parse_url
    from flab2bp.layout.freeform import _adapt
    from flab2bp.layout.strip_variants import _logical_strip_plans
    from flab2bp.rates.candidates import DEFAULT_CANDIDATE_POLICIES, build_candidates

    vendored = load_vendored()
    checked = 0
    for entry in URL_CORPUS:
        candidates = build_candidates(
            vendored,
            parse_url(entry.url),
            candidate_policies=DEFAULT_CANDIDATE_POLICIES,
        ).candidates
        for spec in candidates:
            groups = _adapt(spec)
            internally_produced = {item for group in groups.values() for item in group.outputs}
            both_fed = frozenset(spec.external_inputs) & internally_produced
            if not both_fed:
                continue
            for plan in _logical_strip_plans(spec):
                for index, lane in enumerate(plan.in_above):
                    if both_fed & frozenset(lane):
                        assert index == 0, f"{entry.url_id} {plan.group_key} above {lane}"
                        checked += 1
                for index, lane in enumerate(plan.in_below):
                    if both_fed & frozenset(lane):
                        assert index == len(plan.in_below) - 1, (
                            f"{entry.url_id} {plan.group_key} below {lane}"
                        )
                        checked += 1
    assert checked, "no corpus spec exercised the rule; the invariant proved nothing"


def test_a_spec_with_no_both_fed_ingredient_keeps_its_alphabetical_lane_order() -> None:
    """The surgical/broad mutant guard, stated where the mutants live.

    Two mutants of `_logical_strip_plans`' sort key, and this test plus the
    `hydrogen` test above pin one each:

    * WIDENING the key to `(item not in spec.external_inputs, item)` is R4's
      broad `LANEORDER=1` rule.  `quantum-chip` has ten external inputs and an
      EMPTY both-fed set, so under the broad rule its lanes move and THIS test
      goes red; under the surgical rule they cannot move at all.  R4 §7 measured
      the broad rule at +27.2% area on `sequence-pair|quantum-chip|2`,
      reproduced across arms, and that is the one regression risk to the 66
      clean cells this phase carries.
    * DROPPING the `not in both_fed` term leaves `key=lambda item: item`, plain
      alphabetical order -- today's behaviour.  That leaves this test green and
      turns
      `test_an_ingredient_fed_from_outside_and_inside_takes_the_outermost_lane_row`
      red, which is exactly the pair spec section 5.1 test 4 asks for.
    """
    from flab2bp.layout.freeform import _adapt
    from flab2bp.layout.strip_variants import _logical_strip_plans
    from flab2bp.rates.candidates import CandidatePolicy

    spec = _corpus_spec("quantum-chip", CandidatePolicy.NO_PROLIFERATOR)
    groups = _adapt(spec)
    produced = {item for group in groups.values() for item in group.outputs}
    assert not (frozenset(spec.external_inputs) & produced), "pick a spec with no both-fed item"

    for plan in _logical_strip_plans(spec):
        items = [item for lane in (*plan.in_above, *plan.in_below) for item in lane]
        assert items == sorted(items), plan.group_key


def test_a_side_with_no_both_fed_lane_is_returned_unchanged() -> None:
    """The helper is a stable no-op wherever the rule does not apply."""
    from flab2bp.layout.strip_variants import _seat_both_fed_outermost

    in_above = (("alpha",), ("beta",))
    in_below = (("gamma",), ("delta",))

    assert _seat_both_fed_outermost(in_above, in_below, frozenset()) == (in_above, in_below)
    assert _seat_both_fed_outermost(in_above, in_below, frozenset({"zeta"})) == (
        in_above,
        in_below,
    )


def test_a_both_fed_ingredient_seated_below_takes_the_LAST_below_row() -> None:
    """The case no corpus spec exercises, pinned because the indices differ.

    `Strip.row_of_input` counts `in_above` from the strip's top (index 0 is
    outermost) and `in_below` downward from the band (the LAST index is
    outermost).  Ordering `input_items` alone puts a both-fed item at
    `in_below[0]` -- the row nearest the machine band, the worst one available --
    whenever `_seat_inputs` seats lane 0 below.
    """
    from flab2bp.layout.strip_variants import _seat_both_fed_outermost

    above, below = _seat_both_fed_outermost(
        (),
        (("hydrogen",), ("graphene",), ("titanium-crystal",)),
        frozenset({"hydrogen"}),
    )

    assert above == ()
    assert below == (("graphene",), ("titanium-crystal",), ("hydrogen",))
```

- [ ] **Step 3: Run the tests to verify they fail on master**

Run: `uv run pytest tests/layout/test_strip_variants.py -q -k "both_fed or outermost or alphabetical_lane_order or no_strip_dimension or LAST_below"`

Expected on master:
- the three `_seat_both_fed_outermost` tests FAIL with `ImportError: cannot import name '_seat_both_fed_outermost' from 'flab2bp.layout.strip_variants'`;
- `test_an_ingredient_fed_from_outside_and_inside_takes_the_outermost_lane_row` FAILS with `assert ('graphene',) == ('hydrogen',)` — measured on master, `casimir-crystal#1`'s `in_above` is `(('graphene',), ('hydrogen',), ('titanium-crystal',))`;
- `test_every_both_fed_ingredient_is_seated_on_its_side_s_outermost_row` FAILS on the same strip with `assert 1 == 0`;
- `test_the_seating_rule_changes_no_strip_dimension` and `test_a_spec_with_no_both_fed_ingredient_keeps_its_alphabetical_lane_order` PASS on master and are the guards that they still do afterwards.

- [ ] **Step 4: Add the seating rule**

In `src/flab2bp/layout/strip_variants.py`, insert directly above `_logical_strip_plans`:

```python
def _seat_both_fed_outermost(
    in_above: tuple[tuple[str, ...], ...],
    in_below: tuple[tuple[str, ...], ...],
    both_fed: frozenset[str],
) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...]]:
    """Move every lane carrying a both-fed ingredient to its side's outermost row.

    A lane fed from the boundary AND from an internal producer needs TWO belt
    approaches, and only the outermost lane of a side has two free 4-neighbours.
    Measured (R4 §1.2): the head tile of a MIDDLE lane has its own lane's second
    tile east, a sibling lane head north, a sibling lane head or its own machine
    band south, and the strip's `WEST_CHANNEL` column west -- one free side for
    two claims, at every height, in every pack, under every arrangement.

    THE UNWRITTEN COUPLING THIS RELIES ON, written down here because a packer
    change could silently remove it: the row directly north of every strip is
    free.  `freeform._box` charges each strip `height + MARGIN` with
    `MARGIN = 1`, and `freeform._greedy_pack` seats each strip at the TOP of its
    slot, so the outermost `in_above` lane head can always step north.  If that
    margin row ever goes away, `casimir-crystal#1` and `energy-matrix#12` strand
    again; the router-side pin in `tests/layout/test_freeform.py` and the corpus
    invariant in `tests/layout/test_strip_variants.py` are the tripwires.

    The two sides count rows in OPPOSITE directions -- `Strip.row_of_input`
    returns `in_above.index(lane)` for an `in_above` lane and
    `first_row_below_band + len(out_lanes) + in_below.index(lane)` for an
    `in_below` one -- so `in_above` wants the both-fed lanes FIRST and `in_below`
    wants them LAST.  Ordering `input_items` alone gets `in_above` right and
    `in_below` exactly wrong, which is why the rule is expressed here, on the
    seated rows.

    Both sorts are STABLE, so a side with no both-fed lane is returned unchanged
    and every strip without one is byte-identical to today's.
    """
    if not both_fed:
        return in_above, in_below
    above = tuple(sorted(in_above, key=lambda lane: not (both_fed & frozenset(lane))))
    below = tuple(sorted(in_below, key=lambda lane: bool(both_fed & frozenset(lane))))
    return above, below
```

Inside `_logical_strip_plans`, immediately after the `consumers` loop and before `plans: list[_LogicalStripPlan] = []`:

```python
    # An ingredient that is BOTH belted in from the boundary and produced inside
    # the block accepts two independent feeds on one lane, so its lane head needs
    # two belt approaches.  `producers` is already keyed by every internally
    # produced item, so this costs one set intersection.  `universe-matrix` is
    # the only corpus spec where it is non-empty (R4 §4); measured today it is
    # exactly `{'hydrogen'}`.
    both_fed = frozenset(spec.external_inputs) & frozenset(producers)
```

Replace the `input_items` assignment inside the per-group loop:

```python
# SURGICAL, not broad.  Sorting every external input first was measured
# too (R4 §7, `LANEORDER=1`): same coverage, +0.78% total area and a
# reproducible +27.2% on `sequence-pair|quantum-chip|2`.  Restricting the
# key to items that actually raise the corridor demand changed 2 of 66
# cells for +0.11%, inside the measured 12%-per-cell noise floor.
input_items = tuple(sorted(group.inputs, key=lambda item: (item not in both_fed, item)))
```

After the `try` / `except ValueError` block that resolves `in_above, in_below` (the block that ends by setting `flank = True`), and before `south_columns = ...`:

```python
        # The sort key above puts the both-fed items at index 0 of `input_items`,
        # which `_seat_inputs` turns into lane 0 -- the outermost `in_above` row
        # when the split leaves at least one lane there.  When it does not, lane
        # 0 is `in_below[0]`, the row nearest the machine band and the worst one
        # available.  No corpus spec takes that path today; the normalisation is
        # what makes the invariant true rather than lucky.
        #
        # BEFORE `south_columns` deliberately: `_has_exact_two_face_seating`
        # below encodes lane order into `side_index`, so it must see the seating
        # this function actually ships.  On the corpus this changes nothing --
        # only `universe-matrix` has a both-fed item and both of its affected
        # strips keep `box_height` and `width` (R4 §6 E6) -- but a reviewer
        # should know the prover is downstream of the reorder on purpose.
        in_above, in_below = _seat_both_fed_outermost(in_above, in_below, both_fed)
```

- [ ] **Step 5: Correct the `twice` documentation at both sites**

The prose the spec calls "the `twice` predicate's docstring" is in **`_reserve_port_access`'s docstring**, not at the spec's `freeform.py:14188-14196` hint (that range is `hold_ports`' `shared_feed` construction, which carries a comment). Resolve `_reserve_port_access` with `find_symbol` and locate the paragraph beginning "``twice`` names ports that need one MORE approach". **If the paragraph at the resolved site does not use the word "mixes" or "mixed", stop and report — do not invent the wording being corrected.** Replace it with:

```
    ``twice`` names ports that need one MORE approach on top of that: an input
    lane fed from BOTH the boundary and from a producer inside the block.  The
    external run and the internal net are two independent claims on the same lane
    head and they cannot share a cell, so both are staked.

    The lane need not be MIXED, and this docstring used to say it was.  Every
    port that has ever failed this demand carried ONE item (R4 §1.2:
    ``lane=('hydrogen',)``, ten distinct ports across three cells and five
    heights, all ``wants=2 held=1``).  Narrowing the predicate to mixed lanes was
    tried (R4 §6, E1) and the same ports failed again at ROUTE time with
    ``dynamic-access`` and ZERO expansions -- the external run had taken the one
    corridor and laid a belt on it, and the internal net was handed an empty goal
    set.  The demand is real; the answer is to seat such an ingredient on a lane
    head that has two free sides (``strip_variants._seat_both_fed_outermost``).
```

And replace the comment above `shared_feed` inside `_prepare_routing_problem.hold_ports`:

```python
        # A lane fed from the boundary AND from a producer inside the block has
        # two feeds to accept, not one, so it needs two ways in.  Note this is a
        # property of the ITEM, not of the lane's cardinality: a single-item lane
        # is in this set whenever that item is both external and made internally.
```

- [ ] **Step 6: Write the router-side pin**

Append to `tests/layout/test_freeform.py`, beside the other `_reserve_port_access` cases:

```python
def test_a_middle_lane_head_in_twice_cannot_hold_its_second_corridor() -> None:
    """The regression a future reordering would trip.

    Three stacked lane heads in one column, the middle one in `twice`: its east,
    north and south neighbours are the sibling belts and only the west channel
    tile is free, so it holds ONE corridor against `wants=2`.  This is R4 §1.2's
    geometry reduced to the smallest canvas that reproduces it, and it is what
    stops a later change putting a both-fed item back on a middle row.
    """
    canvas = _Canvas(limit=(-4, -2, 10, 6))
    heads = [_Port(canvas.add(_belt(0, row)), 0, row, 0, 4) for row in (0, 1, 2)]
    for row in (0, 1, 2):
        for column in (1, 2, 3, 4):
            canvas.add(_belt(column, row))
    far = _Port(canvas.add(_belt(8, 4)), 8, 4, 8, 8)
    middle = (0, 1, 0)
    failed: set[tuple[int, int, int]] = set()

    missing = _reserve_port_access(
        canvas,
        [_Net(src=far, dst=head, item="hydrogen") for head in heads],
        twice={middle},
        failed_ports=failed,
    )

    assert missing == 1
    assert failed == {middle}
```

This test passes on master as well: it pins EXISTING router behaviour and is the tripwire for a future reordering, not a test of this change. Say so in the commit message rather than claiming it as a red-to-green test.

- [ ] **Step 7: Run the tests**

```bash
uv run pytest tests/layout/test_strip_variants.py tests/layout/test_freeform.py -q; echo "exit=$?"
uv run pytest -q; echo "exit=$?"
```

Expected: `exit=0` both times. Record the wall of `test_every_both_fed_ingredient_is_seated_on_its_side_s_outermost_row` in the commit message; if it exceeds 60 s, record the number and report — do not weaken it.

- [ ] **Step 8: Prove the four cells on the corpus**

```bash
{ uptime; vmstat 1 3; } | tee -a /tmp/phase-e-task2-load.txt
rm -f /tmp/phase-e-task2.jsonl
uv run python scripts/audit.py --budget 30 --jobs 6 --only universe-matrix \
  --json /tmp/phase-e-task2.jsonl | tail -12
```

Expected (R4 §7, `LANEORDER=2`): `universe-matrix/output-products` and `universe-matrix/all-products` CLEAN under **both** strategies; `universe-matrix/no-proliferator` still REFUSED under both.

- [ ] **Step 9: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/strip_variants.py src/flab2bp/layout/freeform.py \
  tests/layout/test_strip_variants.py tests/layout/test_freeform.py
uv run mypy 2>&1 | tail -3
git add src/flab2bp/layout/strip_variants.py src/flab2bp/layout/freeform.py \
  tests/layout/test_strip_variants.py tests/layout/test_freeform.py
git commit -m "fix(layout): seat a both-fed ingredient on its side's outermost lane row

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KufubYYxUsR9JHQo5xHPtv"
```

---

### Task 3: Give the seed gate its own skipped-heights list

Spec §5.2.2. Split out of the original Task 3 on review A's recommendation: two edit sites in one file, independently reviewable, and a prerequisite of Task 7's `refusal_stats["skipped_heights"]`.

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` (`FreeformLayout._sweep`, `FreeformLayout.lay_out`)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `freeform._retain_refusal(rejected, finding)`; `freeform._RefusalFinding = str | validate.Finding | finalize.ProjectionFailure`; `freeform._band_policy_candidate_heights(strips, policy) -> tuple[int, ...]`.
- Produces: `FreeformLayout._sweep(..., skipped_heights: list[int] | None = None)` — **arity change; grep the quoted name and fix the four `_sweep` stubs.** `lay_out` gains the suffix `"; N candidate heights were skipped as over-band"` on all three post-sweep raises.

- [ ] **Step 1: Write the failing test**

Append to `tests/layout/test_freeform.py`:

```python
def test_an_over_band_seed_is_skipped_and_never_reported_as_wired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R1 §0: the 264x162 extent is a PRE-PACK seed rejection.

    Nothing wired, nothing reached the validator, and `lay_out` turned the
    retained finding into "every packing that wired was rejected by our own
    validator", which sends the reader to the finalizer instead of to the router.

    `_band_policy_candidate_heights` is stubbed rather than `_candidate_heights`:
    with `frame_candidates` empty, `reserve_boundary_height` proves height 20
    infeasible and substitutes `boundary_core_height` (154), so the sweep would
    skip 154 and the assertion would read `[154] != [20]`.
    """
    spec = two_stage_spec()
    strips = plan_strips(spec)
    monkeypatch.setattr(freeform, "_band_policy_candidate_heights", lambda _strips, _policy: (20,))
    monkeypatch.setattr(
        finalize.BandPolicySearchEnvelope,
        "frame_candidates",
        lambda _self, _width, _height: (),
    )
    skipped: list[int] = []
    rejected: list[freeform._RefusalFinding] = []

    result = FreeformLayout(band_policy=BandPolicy("portable"), arrangements=1)._sweep(
        spec,
        strips,
        1.0,
        rejected=rejected,
        skipped_heights=skipped,
        session=OperatorSession(),
    )

    assert result is None
    assert skipped == [20]
    assert rejected == []
```

- [ ] **Step 2: Run the test to verify it fails on master**

Run: `uv run pytest tests/layout/test_freeform.py::test_an_over_band_seed_is_skipped_and_never_reported_as_wired -q`
Expected: FAIL with `TypeError: _sweep() got an unexpected keyword argument 'skipped_heights'` — the parameter does not exist.

- [ ] **Step 3: Give the seed gate its own list**

Add the out-parameter to `FreeformLayout._sweep`'s signature, after `attempts`:

```python
skipped_heights: list[int] | None = (None,)
```

Document it in the docstring, after the `rejected` paragraph:

```
        ``skipped_heights`` collects candidate heights whose GREEDY SEED extent
        fits no band.  They are kept apart from ``rejected`` deliberately: that
        gate fires before `_pack`, so no pack ever existed, and feeding it into
        ``rejected`` made `lay_out` report "every packing that wired was rejected
        by our own validator" for a cell where nothing wired (R1 §0).  The
        POST-pack gate still retains a real pack's rejection.
```

Replace the seed gate's retention (the `if not projection_envelope.frame_candidates(seed_width, seed_height):` block that calls `_retain_refusal`):

```python
                if not projection_envelope.frame_candidates(
                    seed_width,
                    seed_height,
                ):
                    if skipped_heights is not None and height not in skipped_heights:
                        skipped_heights.append(height)
                    continue
```

- [ ] **Step 4: Wire it into `lay_out`**

Beside `rejected: list[_RefusalFinding] = []`:

```python
        #: Candidate heights whose greedy seed extent fits no band.  NOT a
        #: rejection: no pack existed to reject.
        skipped_heights: list[int] = []
```

Pass `skipped_heights=skipped_heights,` in the `self._sweep(...)` call. Immediately before `if rejected and not completion_expired:`:

```python
        over_band = (
            f"; {len(skipped_heights)} candidate heights were skipped as over-band"
            if skipped_heights
            else ""
        )
```

Append `+ over_band` to the `rejected` branch's reason string, add `note += over_band` immediately before the deadline branch's `raise`, and append `+ over_band` to the final unconditional raise's message.

- [ ] **Step 5: Fix every `_sweep` stub**

```bash
grep -rn '"_sweep"' src tests scripts
```

Expected: four `monkeypatch.setattr(FreeformLayout, "_sweep", ...)` sites in `tests/layout/test_freeform.py`. These **replace** `_sweep`, so `lay_out` passes `skipped_heights=` to them and each raises `TypeError` unless it accepts the keyword. Give every stub `**_kwargs: object` (or the explicit parameter where the stub spells its arguments out). The "defaulted parameter" argument does not cover a replaced callable.

- [ ] **Step 6: Run the tests**

```bash
uv run pytest tests/layout/test_freeform.py -q; echo "exit=$?"
uv run pytest -q; echo "exit=$?"
```

Expected: `exit=0` both times.

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
uv run mypy 2>&1 | tail -3
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "fix(layout): report a skipped over-band seed as skipped, not as wired

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KufubYYxUsR9JHQo5xHPtv"
```

---

### Task 4: Name port seating in a refusal no router ever reached

Spec §5.3.1. Split out of the original Task 3: seven edit sites against Task 3's two.

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` (`StrandedPort` (new), `_reserve_port_access`, `_prepare_routing_problem.hold_ports`, `_PreparedRoutingProblem`, `_BuildResult`, `_build`, `PackAttempt`, `_port_seating_refusal` (new), `FreeformLayout._sweep`, `FreeformLayout.lay_out`)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `freeform._reserve_port_access(canvas, nets, *, twice=(), failed_ports=None) -> int`; `freeform._prepare_routing_problem(...) -> _PreparedRoutingProblem`; `freeform._build(...) -> _BuildResult`; `freeform.PackAttempt`; `tests/layout/test_freeform.py::_proof_attempt(routing, strips, *, origins=None, promised_direct=frozenset(), realized_direct=frozenset()) -> PackAttempt` — the existing factory; **`Strip.sid` is a PROPERTY, not a method: write `strip.sid`, never `strip.sid()`.**
- Produces:
  - `freeform.StrandedPort` — frozen slots dataclass with `cell: tuple[int, int, int]`, `item: str`, `strip_label: str`, `held: int`, `wants: int`, `options: int`.
  - `_reserve_port_access(..., demands: dict[Cell, tuple[int, int, int]] | None = None)` — **arity change; grep the quoted name.** One stub exists (`tests/layout/test_freeform.py:17779`, `monkeypatch.setattr(freeform, "_reserve_port_access", reserve_with_a_spectator)`) and must accept the keyword.
  - `_PreparedRoutingProblem.stranded_ports`, `_BuildResult.stranded_ports`, `PackAttempt.stranded_ports`, each `tuple[StrandedPort, ...] = ()`.
  - `freeform._port_seating_refusal(attempts: Sequence[PackAttempt]) -> str | None`.

- [ ] **Step 1: Write the failing refusal tests**

Append to `tests/layout/test_freeform.py`:

```python
def _port_seating_attempt(count: int, *, expansions: int = 0) -> freeform.PackAttempt:
    """A pack whose router never ran: STATIC_ACCESS only, zero expansions.

    Built from the file's existing `_proof_attempt` factory so the `PackAttempt`
    invariants and the `_DirectCandidateSnapshot` come from one place.
    """
    strips = plan_strips(two_stage_spec())
    failures = tuple(
        NetFailure(
            NetId(0, 1, "hydrogen", RouteFailureKind and NetRole.INTERNAL, index),
            RouteFailureKind.STATIC_ACCESS,
            ((1, 10 + index, 0),),
            (),
            0,
        )
        for index in range(count)
    )
    routing = DetailedRouteResult(DetailedRouteStatus.STRANDED, (), failures, 0, expansions)
    attempt = _proof_attempt(routing, strips)
    return replace(
        attempt,
        stranded_ports=tuple(
            freeform.StrandedPort(
                cell=(1, 10 + index, 0),
                item="hydrogen",
                strip_label="casimir-crystal#1",
                held=1,
                wants=2,
                options=1,
            )
            for index in range(count)
        ),
    )


def test_a_pack_that_never_routed_is_reported_as_a_port_seating_defect() -> None:
    """`PACKER defect` is reserved for a pack the router actually ran on.

    R2 §3 measured the old message on `universe-matrix/output-products`: five
    packs, ZERO A* expansions, every failure a preparation-time STATIC_ACCESS --
    and a refusal naming the packer, which is exactly what sent that research to
    the wrong file.
    """
    message = freeform._port_seating_refusal([_port_seating_attempt(6)])

    assert message is not None
    assert "no pack was ever routed" in message
    assert "6 lane heads" in message
    assert "PORT-SEATING defect" in message
    assert "hydrogen" in message and "casimir-crystal#1" in message
    assert "wants 2" in message and "held 1" in message
    assert "PACKER defect" not in message


def test_a_pack_the_router_ran_on_is_not_reported_as_port_seating() -> None:
    assert freeform._port_seating_refusal([_port_seating_attempt(1, expansions=1200)]) is None
    assert freeform._port_seating_refusal([]) is None
```

Resolve `NetFailure`'s constructor and the `NetRole` import in the file with `find_symbol` before writing the block; the placeholder `RouteFailureKind and NetRole.INTERNAL` above is a transcription artefact — write `NetRole.INTERNAL`, matching `_routing_failures`' own `NetId(0, 1, f"item-{ordinal}", NetRole.INTERNAL, ordinal)`.

- [ ] **Step 2: Run the tests to verify they fail on master**

Run: `uv run pytest tests/layout/test_freeform.py -q -k "port_seating"`
Expected: both FAIL with `AttributeError: module 'flab2bp.layout.freeform' has no attribute 'StrandedPort'` — neither the record nor `_port_seating_refusal` exists.

- [ ] **Step 3: Add `StrandedPort` and the demand record**

Immediately above `PackAttempt` in `freeform.py`:

```python
@dataclass(frozen=True, slots=True)
class StrandedPort:
    """One lane head that could not obtain the belt approaches its feeds need.

    Carried out of preparation so a refusal can name the PORT rather than the
    nets that happened to end on it.  R2 §7 option 1 asked for exactly this: the
    old message named the packer, and the reader had to instrument
    `_reserve_port_access` to learn that `held=1 wants=2 options=1` on a
    `hydrogen` lane head was the whole story.
    """

    cell: tuple[int, int, int]
    item: str
    strip_label: str
    #: Corridors the matching actually reserved for this port.
    held: int
    #: Corridors it needed: one per role, plus one when the port is in ``twice``.
    wants: int
    #: Free 4-neighbours the port had to build a corridor from.  ``1`` is the
    #: signature of a middle lane head and is not a matching failure -- there is
    #: nothing to match.
    options: int
```

Add the out-parameter to `_reserve_port_access`:

```python
def _reserve_port_access(
    canvas: _Canvas,
    nets: list[_Net],
    *,
    twice: Collection[tuple[int, int, int]] = (),
    failed_ports: set[Cell] | None = None,
    demands: dict[Cell, tuple[int, int, int]] | None = None,
) -> int:
```

Append to its docstring:

```
    ``demands`` collects ``(held, wants, options)`` for every port that came up
    short, so a caller can say WHY without re-deriving the geometry.
```

and replace the `missing` block at the tail:

```python
missing = {key for key in order if held[key] < wants[key]}
if failed_ports is not None:
    failed_ports.update(missing)
if demands is not None:
    demands.update((key, (held[key], wants[key], len(options.get(key, ())))) for key in missing)
return len(missing)
```

Resolve the `options` local with `find_symbol` first: R4 §1.4 read it as `options[key]`, the port's free 4-neighbours, built where the corridor sets are. If the local is named differently, use the local — do not rename it, and do not invent a second computation of the free-neighbour count.

- [ ] **Step 4: Build the records in `hold_ports` and thread them out**

Beside `unreachable_ports: set[Cell] = set()` in `_prepare_routing_problem`:

```python
    stranded_ports: list[StrandedPort] = []
```

Rewrite `hold_ports`' body tail (`Strip.sid` is a **property** — no call parentheses):

```python
        unreachable_ports.clear()
        stranded_ports.clear()
        demands: dict[Cell, tuple[int, int, int]] = {}
        _reserve_port_access(
            canvas,
            nets,
            twice=shared_feed,
            failed_ports=unreachable_ports,
            demands=demands,
        )
        owner = {
            (port.x, port.y, port.z): (item, strips[strip_index].sid)
            for strip_index, ports in enumerate(strip_in_ports)
            for item, port in ports.items()
        }
        stranded_ports.extend(
            StrandedPort(
                cell=cell,
                item=owner.get(cell, ("?", "?"))[0],
                strip_label=owner.get(cell, ("?", "?"))[1],
                held=demands[cell][0],
                wants=demands[cell][1],
                options=demands[cell][2],
            )
            for cell in sorted(unreachable_ports)
        )
```

Add `stranded_ports: tuple[StrandedPort, ...] = ()` to `_PreparedRoutingProblem` beside `preparation_failures`, and pass `stranded_ports=tuple(stranded_ports),` at the constructor call at the end of `_prepare_routing_problem`.

Add the same defaulted field to `_BuildResult`, and set `stranded_ports=prepared.stranded_ports,` on every `_BuildResult` `_build` constructs AFTER `prepared` is bound. Enumerate them with `find_symbol` on `_build`; the `_PreparationDeadline` / `ProjectionCancelled` return happens before `prepared` exists and keeps the default.

Add the same defaulted field to `PackAttempt`, and fill it where `_sweep` constructs the attempt, beside `static_access=...`:

```python
stranded_ports = (result.stranded_ports,)
```

- [ ] **Step 5: Add the refusal helper**

Directly above `_refusal_summary` in `freeform.py`:

```python
def _port_seating_refusal(attempts: Sequence[PackAttempt]) -> str | None:
    """The refusal for a sweep whose router never ran, or ``None``.

    Every retained attempt failed at PREPARATION with static access only and
    expanded zero A* nodes: `_build` substitutes a synthetic STRANDED result and
    skips routing entirely when `prepared.preparation_failures` is non-empty, so
    "the packer produced packs its own router cannot wire" is false twice over --
    nothing was routed and the packer is blameless.  Measured on all three
    freeform `universe-matrix` cells at `e0bf432` (R2 §3, R4 §1).
    """
    if not attempts:
        return None
    for attempt in attempts:
        if attempt.routing.expansions:
            return None
        if not attempt.routing.failures:
            return None
        if any(
            failure.kind is not RouteFailureKind.STATIC_ACCESS
            for failure in attempt.routing.failures
        ):
            return None
    ports = {port.cell: port for attempt in attempts for port in attempt.stranded_ports}
    if not ports:
        return None
    named = ", ".join(
        f"{port.item} into {port.strip_label} at {port.cell} "
        f"(wants {port.wants}, held {port.held}, {port.options} free side(s))"
        for port in sorted(ports.values(), key=lambda port: port.cell)[:3]
    )
    counts = {len(attempt.stranded_ports) for attempt in attempts}
    same = (
        f"every candidate height produced the same {next(iter(counts))} failures"
        if len(counts) == 1
        else "the failure count varied by candidate height"
    )
    return (
        f"no pack was ever routed: {len(ports)} lane heads could not obtain the "
        f"belt approaches they need ({named}); this is a PORT-SEATING defect "
        f"independent of the packing -- {same}"
    )
```

- [ ] **Step 6: Wire it into BOTH reachable raises**

The unconditional final raise is reached only when `rejected` is empty **and** `deadline_expired` is false. On `universe-matrix` at a 30 s budget the sweep may well reach the deadline (review B I9), in which case the deadline branch fires and the new message would never appear. Wire both.

In `lay_out`'s deadline branch, immediately before its `raise`, after `note` is fully built:

```python
            # A sweep whose router never ran has a mechanism, and the deadline is
            # not it.  When every retained attempt is a preparation-time static
            # access with zero expansions, say so instead of counting packs that
            # were never routed.
            seating = _port_seating_refusal(attempts)
            if seating is not None:
                note = seating
```

and replace the final unconditional raise:

```python
raise NoValidLayout(
    (
        _port_seating_refusal(attempts)
        or (
            f"no packing of {len(strips)} strips could be wired at any candidate "
            "height; every pack the sweep produced left nets unrouted. That is a "
            "PACKER defect -- it is producing packs its own router cannot wire -- "
            "and it is reported rather than papered over with a looser packing"
        )
    )
    + over_band,
    spec_label=spec.label,
    budget_s=budgets[-1],
)
```

- [ ] **Step 7: Grep the quoted names for stubs**

```bash
grep -rn '"_reserve_port_access"\|"_build"\|"_prepare_routing_problem"\|"_sweep"' src tests scripts
```

Expected hits: one `_reserve_port_access` stub (`tests/layout/test_freeform.py:17779`) that must accept `demands=`; the `_build` stub inside `_sweep_after_first_routing`, which already takes `**_kwargs` and returns a `_BuildResult` without `stranded_ports` (fine — the field is defaulted); and the four `_sweep` stubs Task 3 already fixed. Fix every stub the change reaches.

- [ ] **Step 8: Run the tests**

```bash
uv run pytest tests/layout/test_freeform.py -q; echo "exit=$?"
uv run pytest -q; echo "exit=$?"
```

Expected: `exit=0` both times.

- [ ] **Step 9: Prove the message on the cell**

```bash
{ uptime; vmstat 1 3; } | tee -a /tmp/phase-e-task4-load.txt
rm -f /tmp/phase-e-task4.jsonl
uv run python scripts/audit.py --budget 30 --jobs 3 --only universe-matrix \
  --strategy freeform --json /tmp/phase-e-task4.jsonl | tail -8
uv run python -c "
import json
for row in map(json.loads, open('/tmp/phase-e-task4.jsonl')):
    print(row['spec_label'], row['status'], row['projection_failures'], row['detail'][:170])
"
```

Expected: `no-proliferator` REFUSED with a routing or port-seating message, `projection_failures` an empty list, and no `game.blueprint_area` text anywhere (R1 §5(c)). After Task 2 the port-seating failures are gone from `output-products` and `all-products`, so those rows are CLEAN; the message is exercised by the unit tests, and the cell probe is a check that nothing regressed.

- [ ] **Step 10: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
uv run mypy 2>&1 | tail -3
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "fix(layout): name port seating in a refusal no router ever reached

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KufubYYxUsR9JHQo5xHPtv"
```

---

### Task 5: Make freeform's band reservation witness a width the packer reaches

Spec §5.2.1.

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` (`_band_policy_candidate_heights`)
- Test: `tests/layout/test_finalize.py`, `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `freeform._minimum_pack_width(strips, height) -> int`; `freeform._greedy_pack(strips, height) -> _Pack` (`.width`, `.height`, `.at`); `finalize.BandPolicySearchEnvelope.reserve_boundary_height(ordered, *, minimum_width_for_height) -> tuple[int, ...]`; `finalize.band_policy_search_envelope(policy, *, perimeter)`.
- **`strip_outline` is a CLOSURE inside `FreeformLayout._sweep`, not a module symbol** (`hasattr(freeform, "strip_outline")` is `False`). No test may call `freeform.strip_outline`.
- Produces: no new symbol. `_band_policy_candidate_heights` keeps its signature and changes only which heights it returns.

**Deviation recorded here (review B I1).** The seed gate inside `_sweep` filters on `strip_outline(seed)`, whose height is the greedy shelf's REALISED height, while this change filters on `(max(_minimum_pack_width(strips, h), seeds[h].width), h)`. Those differ on the height axis for every candidate, so this change does not establish "every scheduled height passes the seed gate", and no test here claims it does. What it does establish is exactly what R1's E1 measured, and that is what Step 2 pins.

- [ ] **Step 1: Write the failing finalize test**

Append to `tests/layout/test_finalize.py`, beside `test_portable_schedule_reserves_the_tallest_legal_core_boundary`:

```python
def test_portable_schedule_reserves_a_boundary_when_only_rotation_admits_the_height() -> None:
    """The gap the existing sibling hides: its witnesses are 380 to 522 wide.

    `planet.band_for_extent` tries BOTH orientations, which is right for a real
    placement and wrong as a feasibility witness for a HEIGHT.  At the 92-wide
    witness `_minimum_pack_width` produced for
    `universe-matrix/no-proliferator`, a 98x166 extent fits the 200-segment band
    ROTATED (98 latitude rows of 160), so height 160 survives -- while every real
    pack of those 43 strips is 258 wide and its 264x162 extent fits nothing
    (R1 §2).
    """
    envelope = finalize.band_policy_search_envelope(
        BandPolicy("portable"),
        perimeter=3,
    )
    ordered = (125, 160, 100, 80, 60)

    loose = envelope.reserve_boundary_height(
        ordered,
        minimum_width_for_height={125: 92, 160: 92, 100: 101, 80: 126, 60: 168},
    )
    achievable = envelope.reserve_boundary_height(
        ordered,
        minimum_width_for_height={125: 258, 160: 258, 100: 292, 80: 342, 60: 439},
    )

    assert envelope.boundary_core_height == 154
    assert loose == ordered
    assert achievable == (125, 154, 100, 80, 60)
    assert len(achievable) == len(ordered)
```

This test passes on master: it exercises `reserve_boundary_height` directly with both witnesses and pins the difference between them. It is the evidence for the change, not a red-to-green test — say so in the commit message.

- [ ] **Step 2: Write the failing freeform test**

Append to `tests/layout/test_freeform.py`:

```python
def test_the_schedule_replaces_the_over_band_height_with_the_boundary() -> None:
    """R1 §2 and §3, E1, on the cell that has the defect.

    Master schedules `(125, 160, 100, 80, 60)` for
    `universe-matrix/no-proliferator` and `reserve_boundary_height` replaces
    NOTHING, because its witness is `_minimum_pack_width` = 92 while every pack
    the sweep produces is 258 wide.  Height 160's greedy seed is 258x156, its
    extent 264x162, and it dies at the pre-pack seed gate -- one of five
    candidate slots spent proving that.  With the seed's own width as the witness
    the boundary height 154 replaces it and its 258x154 pack packs and routes.
    """
    from flab2bp.bench.corpus import URL_CORPUS
    from flab2bp.lab.data import load_vendored
    from flab2bp.lab.url import parse_url
    from flab2bp.rates.candidates import CandidatePolicy, build_candidates

    entry = next(e for e in URL_CORPUS if e.url_id == "universe-matrix")
    spec = build_candidates(
        load_vendored(),
        parse_url(entry.url),
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
    ).candidates[0]
    strips = plan_strips(spec)

    heights = freeform._band_policy_candidate_heights(strips, BandPolicy("portable"))

    assert 160 not in heights
    assert 154 in heights
```

- [ ] **Step 3: Run the tests to verify they fail on master**

Run: `uv run pytest tests/layout/test_finalize.py::test_portable_schedule_reserves_a_boundary_when_only_rotation_admits_the_height tests/layout/test_freeform.py::test_the_schedule_replaces_the_over_band_height_with_the_boundary -q`
Expected: the finalize test PASSES (it is the evidence, see Step 1); the freeform test FAILS with `assert 160 not in (125, 160, 100, 80, 60)` — master's schedule keeps the over-band height. If the freeform test's schedule differs from R1's measured `(125, 160, 100, 80, 60)`, record what it actually is and report before editing: the cell's strip plan changed under Task 2 and the pin must be re-derived on evidence, not adjusted to pass.

- [ ] **Step 4: Pass the constructive witness**

Replace `_band_policy_candidate_heights`' body. The `seeds` and `ordered` lines are unchanged; the only real edit is the `max(...)`:

```python
def _band_policy_candidate_heights(
    strips: list[Strip],
    policy: BandPolicy,
) -> tuple[int, ...]:
    """Keep the measured order while reserving one proved fixed-band boundary.

    THE WITNESS IS THE GREEDY SEED'S WIDTH, not `_minimum_pack_width`'s.  The
    latter is a valid area-based LOWER bound and it is far below anything the
    packer builds: 92 against 258 on `universe-matrix/no-proliferator`, where a
    98x166 extent fits the 200-segment band rotated and a 264x162 extent fits
    nothing.  Height 160 therefore survived the filter, its greedy seed was
    rejected at the pre-pack gate, and one of five candidate slots was spent
    proving that (R1 §2).  With the seed's width the boundary height 154 replaces
    it, and its 258x154 pack packs and routes (R1 §3, E1).

    `max(...)` rather than the seed alone: `_minimum_pack_width` is still a proof
    and can exceed the seed for a height the shelf pack seats badly, and taking
    the larger of the two keeps the filter no weaker than it was.

    This is a WIDTH witness at the SCHEDULED height; the sweep's own seed gate
    filters on `strip_outline(seed)`, whose height is the shelf's realised one.
    The two are different questions and this function answers only the first.
    """
    seeds = {height: _greedy_pack(strips, height) for height in _candidate_heights(strips)}
    ordered = tuple(sorted(seeds, key=lambda height: (seeds[height].width, height)))
    envelope = finalize.band_policy_search_envelope(
        policy,
        perimeter=_ENTRY_RING,
    )
    return envelope.reserve_boundary_height(
        ordered,
        minimum_width_for_height={
            height: max(_minimum_pack_width(strips, height), seeds[height].width)
            for height in ordered
        },
    )
```

- [ ] **Step 5: Run the tests, then measure the FULL corpus**

The `max(...)` witness raises the reservation filter for **every freeform cell**, not just this one — the same blast radius that widened Task 6's probe — so this task's corpus check is the full 72 cells, with the cell probe kept for its refusal text.

```bash
uv run pytest tests/layout/test_finalize.py tests/layout/test_freeform.py -q; echo "exit=$?"
uv run pytest -q; echo "exit=$?"
{ uptime; vmstat 1 3; } | tee -a /tmp/phase-e-task5-load.txt
rm -f /tmp/phase-e-task5-full.jsonl /tmp/phase-e-task5.jsonl
uv run python scripts/audit.py --budget 30 --jobs 16 --json /tmp/phase-e-task5-full.jsonl | tail -6
uv run python scripts/audit_compare.py \
  docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/baseline-budget30-round1.jsonl \
  /tmp/phase-e-task5-full.jsonl --noise-area 0.013 --p95-seconds 31 --expect-cells 72 --regressions-only
uv run python scripts/audit.py --budget 30 --jobs 3 --only universe-matrix \
  --strategy freeform --json /tmp/phase-e-task5.jsonl | tail -8
```

Expected: `exit=0`; no REGRESSION line against the Task 1 baseline; `output-products` and `all-products` CLEAN, `no-proliferator` REFUSED for routing. R1 §3 measured the recovered slot as a `258x154` pack that routes and strands the same six nets; after Task 2 those six are gone, so the residual failures are the ordinary pack-specific ones R4 §6 E5 recorded (1 to 5 per pack, a different net each time). An area move here is what Gate E1's clause 3 and the reversion rule below exist for — record the ratio in the commit message either way.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_finalize.py tests/layout/test_freeform.py
uv run mypy 2>&1 | tail -3
git add src/flab2bp/layout/freeform.py tests/layout/test_finalize.py tests/layout/test_freeform.py
git commit -m "fix(layout): reserve the band boundary against a width the packer reaches

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KufubYYxUsR9JHQo5xHPtv"
```

**Reversion rule (spec §5.2.1).** This change buys no coverage by itself (R4 §6 E2 measured 0/3 with it and without the seating rule). If Gate E1's area clause fails and a round with this commit reverted passes, revert it in Task 8 and record the numbers in the status note; §5.2.2's seed-gate narration (Task 3) ships regardless.

---

### Task 6: Pull the sequence-pair height schedule below the band's core boundary

Spec §5.2.3.

**Files:**
- Modify: `src/flab2bp/layout/sequence_solver.py` (new module constant `C_CEILING_APPROACH_STEP`, new module function `_ceiling_bounded_schedule`, the height-schedule block and the compact-seed prepend inside `_production_run`)
- Test: `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: `finalize.BandPolicySearchEnvelope.boundary_core_height -> int | None`; `finalize.band_policy_search_envelope(policy, *, perimeter)`; `freeform._greedy_pack`, `freeform._minimum_pack_width`, `freeform._candidate_heights` (already imported into `sequence_solver`). **`_ENTRY_RING` lives in `freeform` and is NOT imported into `sequence_solver`** — a test must read `freeform._ENTRY_RING`, or better, reuse the perimeter `_production_run` itself passes.
- Produces: `sequence_solver.C_CEILING_APPROACH_STEP: int`; `sequence_solver._ceiling_bounded_schedule(ordered: tuple[int, ...], *, boundary: int | None, reserved: frozenset[int] = frozenset()) -> tuple[int, ...]`, **length- and position-preserving**.

**Two deviations from spec §5.2.3, declared here and recorded in the spec by Task 14** (review A I5):
1. The spec's clause is absolute — "never offers a height above the boundary core". The implementation leaves an over-ceiling height in place when the approach band (`C_CEILING_APPROACH_STEP + 1` slots) has no free slot, because `SequenceSolver.__init__` refuses a duplicate height (`ValueError("candidate heights must be unique positive integers in a tuple")`) and `_production_run` re-splits the schedule BY INDEX. That case is pinned as intended behaviour by a test.
2. The spec scopes the approach-band guarantee to "once the deadline-continuation restarts begin". The bounding is applied to the WHOLE schedule — coarse heights and protected follow-ups alike — so it rewrites the primary schedule of any corpus cell that ever schedules an over-ceiling height, not just `universe-matrix`. That is a live regression vector against the 66 clean cells; Gate E1 (Task 8) is what catches it, and Step 7 below runs a full-corpus compare rather than only `--only universe-matrix`.

- [ ] **Step 1: Read the schedule block before editing**

`find_symbol` `_production_run` with `include_body=True` and locate the block binding `coarse_heights`, `neighbor_heights`, `protected_followup_heights`, `legacy_heights`, `heights`, `boundary_height`, the `seeds.setdefault(boundary_height, ...)` guard, the re-split `coarse_heights = heights[:coarse_height_count]`, and — further down — the compact-seed prepend `heights = (compact_height,) + tuple(...)`. Confirm five facts and stop and report if any is false:

1. `heights` is re-split BY INDEX, so any transformation must preserve length and position.
2. `SequenceSolver.__init__` raises on a duplicate or non-positive height.
3. `problems` is built from `heights` after the split, and `seeds` is consumed by `_topology_beam_height`, so every height the schedule ends with needs a `seeds` entry.
4. `compact_height` is prepended to `heights` AFTER the split and is not produced by the schedule generator, so bounding the schedule alone does not bound it.
5. The perimeter `_production_run` passes to `band_policy_search_envelope` — read it off the `envelope = finalize.band_policy_search_envelope(...)` call — is the value any test must reuse. Do not hard-code 3.

- [ ] **Step 2: Write the failing schedule tests**

Append to `tests/layout/test_sequence_solver.py`:

```python
def test_the_schedule_never_offers_a_height_above_the_band_core_boundary() -> None:
    """R3 §3, the 300 s `universe-matrix/no-proliferator` run.

    Its heights were [99, 125, 160, 100, 80, 60, 127, 162, 102, 82, 62] --
    nothing between 128 and 160 -- and the ONLY height that routed was 160,
    whose finalized extent was 162 to 163 latitude rows against a 160-row band.
    Two to three rows over, with no candidate underneath to fall back to.
    """
    ordered = (125, 160, 100, 80, 60, 127, 162, 102, 82, 62)

    bounded = sequence_solver._ceiling_bounded_schedule(ordered, boundary=154)

    assert len(bounded) == len(ordered)
    assert len(set(bounded)) == len(bounded)
    assert max(bounded) <= 154
    assert bounded == (125, 154, 100, 80, 60, 127, 153, 102, 82, 62)


def test_the_schedule_reaches_the_approach_band_when_it_is_pulled_down() -> None:
    step = sequence_solver.C_CEILING_APPROACH_STEP
    bounded = sequence_solver._ceiling_bounded_schedule((160, 60), boundary=154)

    assert any(154 - step <= height <= 154 for height in bounded)


def test_a_schedule_already_under_the_ceiling_is_returned_unchanged() -> None:
    """Byte-identical for every cell that never scheduled an over-band height."""
    ordered = (128, 100, 80, 64, 48, 130, 102, 82, 66, 50)

    assert sequence_solver._ceiling_bounded_schedule(ordered, boundary=154) == ordered
    assert sequence_solver._ceiling_bounded_schedule(ordered, boundary=None) == ordered


def test_an_over_ceiling_height_with_no_free_approach_slot_is_left_alone() -> None:
    """Uniqueness beats the ceiling: a duplicate makes `SequenceSolver` raise.

    The approach band holds `C_CEILING_APPROACH_STEP + 1` slots.  A schedule that
    fills all of them and still carries an over-ceiling height keeps it, because
    dropping the entry would shift a protected follow-up into the coarse half of
    the index split and a duplicate would refuse the search outright.  This is
    declared deviation 1 from spec section 5.2.3.
    """
    step = sequence_solver.C_CEILING_APPROACH_STEP
    full = tuple(range(154, 154 - step - 1, -1))
    ordered = (*full, 200)

    bounded = sequence_solver._ceiling_bounded_schedule(ordered, boundary=154)

    assert bounded == ordered


def test_a_reserved_height_is_not_reused_as_a_replacement() -> None:
    """The compact-seed height is bounded against the schedule it joins."""
    bounded = sequence_solver._ceiling_bounded_schedule(
        (200,), boundary=154, reserved=frozenset({154, 153})
    )

    assert bounded == (152,)
```

- [ ] **Step 3: Run the tests to verify they fail on master**

Run: `uv run pytest tests/layout/test_sequence_solver.py -q -k "ceiling or approach_band or reserved_height"`
Expected: all five FAIL with `AttributeError: module 'flab2bp.layout.sequence_solver' has no attribute '_ceiling_bounded_schedule'`.

- [ ] **Step 4: Add the constant and the helper**

Beside the other `C_` module constants in `sequence_solver.py`:

```python
#: Rows below the band's core boundary the height schedule must be able to reach.
#:
#: MEASURED, not guessed.  R3 §3 ran `universe-matrix/no-proliferator` under
#: sequence-pair at `--budget 300`: 81 stages, heights
#: `[99, 125, 160, 100, 80, 60, 127, 162, 102, 82, 62]`, and exactly one of them
#: reached `stranded == 0` -- outline height 160, the first fully routed
#: candidate anywhere in that investigation.  Its FINALIZED extent needed 162 to
#: 163 latitude rows against the 160-row band and the finalizer refused it.  The
#: schedule offered nothing between 128 and 160, so a placement that routed had
#: nowhere legal to land.  Six is that two-to-three-row overshoot doubled: wide
#: enough that a routed placement has a fallback under the ceiling, narrow enough
#: that the approach height is an approach and not just another mid-range height.
C_CEILING_APPROACH_STEP = 6
```

If `6` collides with a linted game value, declare it through `registry.LintException` (Ruling AI).

Add the helper beside `_topology_beam_height`:

```python
def _ceiling_bounded_schedule(
    ordered: tuple[int, ...],
    *,
    boundary: int | None,
    reserved: frozenset[int] = frozenset(),
) -> tuple[int, ...]:
    """Pull every over-ceiling scheduled height into the band's approach.

    LENGTH- AND POSITION-PRESERVING, and that is a requirement rather than a
    convenience: `_production_run` re-splits this tuple BY INDEX into the coarse
    schedule and the protected follow-ups, so a dropped entry would move a
    follow-up into the coarse half.  `SequenceSolver.__init__` also refuses a
    duplicate height outright, so a replacement must be distinct from every other
    scheduled height AND from every height in ``reserved`` -- which is how a
    compact-seed height is bounded against the schedule it is about to join.
    When the approach band -- ``C_CEILING_APPROACH_STEP + 1`` slots below
    ``boundary`` -- has no free slot, the over-ceiling height is LEFT ALONE, which
    is strictly no worse than today, where every over-ceiling height is.

    ``boundary`` is `BandPolicySearchEnvelope.boundary_core_height`: 154 at a
    160-row band and 3-row entry rings.  ``None`` means the policy names no band
    and there is no ceiling to bind.
    """
    if boundary is None or boundary <= 0:
        return ordered
    taken = set(ordered) | set(reserved)
    bounded: list[int] = []
    for height in ordered:
        if height <= boundary:
            bounded.append(height)
            continue
        replacement = next(
            (
                candidate
                for candidate in range(boundary, boundary - C_CEILING_APPROACH_STEP - 1, -1)
                if candidate > 0 and candidate not in taken
            ),
            None,
        )
        if replacement is None:
            bounded.append(height)
            continue
        taken.discard(height)
        taken.add(replacement)
        bounded.append(replacement)
    return tuple(bounded)
```

- [ ] **Step 5: Apply it in `_production_run`, at both sites**

Replace the block from `heights = envelope.reserve_boundary_height(` through the two re-split lines with:

```python
heights = envelope.reserve_boundary_height(
    legacy_heights,
    minimum_width_for_height={
        height: _minimum_pack_width(strips, height) for height in legacy_heights
    },
)
boundary_height = envelope.boundary_core_height
# THE CEILING BINDS HERE.  `reserve_boundary_height` replaces at most ONE
# height and only one it can prove infeasible, against a witness that is
# an area lower bound; R3 §3 measured a schedule that kept TWO heights
# over the boundary (160 and 162) and routed only the illegal one.
heights = _ceiling_bounded_schedule(heights, boundary=boundary_height)
for height in heights:
    seeds.setdefault(height, _greedy_pack(strips, height))
coarse_heights = heights[:coarse_height_count]
protected_followup_heights = heights[coarse_height_count:]
```

This replaces the existing `if boundary_height is not None and boundary_height in heights: seeds.setdefault(...)` guard: the loop covers that case and every height the bounding introduced.

Then bound the compact-seed height at its own site, immediately before `telemetry.compact_seed_height = compact_height`:

```python
            # The compact seed joins `heights` below and is not produced by the
            # schedule generator, so the ceiling has to bind it separately or a
            # bounded schedule can be re-broken one line later.
            compact_height = _ceiling_bounded_schedule(
                (compact_height,),
                boundary=envelope.boundary_core_height,
                reserved=frozenset(heights),
            )[0]
```

`compact_height` is used afterwards for `seeds`, `problems` and the prepend; every one of those already guards on membership, so a bounded value flows through unchanged.

- [ ] **Step 6: Pin the perimeter and the boundary**

Append to `tests/layout/test_sequence_solver.py`:

```python
def test_the_portable_band_core_boundary_is_the_number_the_helper_is_given() -> None:
    """Pins 154 where a test can see it, without running a production search.

    `_ENTRY_RING` lives in `freeform` and is NOT imported into `sequence_solver`;
    reading `sequence_solver._ENTRY_RING` raises `AttributeError`.
    """
    from flab2bp.layout import freeform
    from flab2bp.layout.finalize import band_policy_search_envelope

    envelope = band_policy_search_envelope(BandPolicy("portable"), perimeter=freeform._ENTRY_RING)

    assert freeform._ENTRY_RING == 3
    assert envelope.boundary_core_height == 154
    assert (
        max(
            sequence_solver._ceiling_bounded_schedule(
                (125, 160, 100), boundary=envelope.boundary_core_height
            )
        )
        <= 154
    )
```

**No end-to-end `_production_run` test.** Review B I7: `config: SequenceSolverConfig` is keyword-only with no default, and a real production search over the 43-strip `universe-matrix` spec inside pytest risks the 120 s `pytest-timeout` backstop hard-killing the whole run. The corpus behaviour is measured in Step 7 and gated in Task 8.

- [ ] **Step 7: Run the tests and measure the FULL corpus**

The bounding touches every cell that ever schedules an over-ceiling height (declared deviation 2), so this task's corpus probe is the full 72 cells, not `--only universe-matrix`.

```bash
uv run pytest tests/layout/test_sequence_solver.py -q; echo "exit=$?"
uv run pytest -q; echo "exit=$?"
{ uptime; vmstat 1 3; } | tee -a /tmp/phase-e-task6-load.txt
rm -f /tmp/phase-e-task6.jsonl
uv run python scripts/audit.py --budget 30 --jobs 16 --json /tmp/phase-e-task6.jsonl | tail -6
uv run python scripts/audit_compare.py \
  docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/baseline-budget30-round1.jsonl \
  /tmp/phase-e-task6.jsonl --noise-area 0.013 --p95-seconds 31 --expect-cells 72 --regressions-only
```

Expected: `exit=0` both suites; no REGRESSION line; the four cells Task 2 fixed CLEAN; `no-proliferator` still REFUSED at 30 s under both strategies. R3 §6 is explicit that this cell is routing-bound at 30 and 120 s and only band-ceiling-bound at 300 s, so this task aims at the 300 s wall and Gate E2's clause is about counters, not this cell going green.

- [ ] **Step 8: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_solver.py
uv run mypy 2>&1 | tail -3
git add src/flab2bp/layout/sequence_solver.py tests/layout/test_sequence_solver.py
git commit -m "fix(layout): keep the sequence-pair height schedule under the band ceiling

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KufubYYxUsR9JHQo5xHPtv"
```

---

### Task 7: Carry solver stats onto refused audit rows

Spec §5.3.2 and §6. This is also Phase D's ranked lever 2, one phase later (R3 §5.3).

**Files:**
- Modify: `src/flab2bp/layout/base.py` (`NoValidLayout.__init__`, the module import block)
- Modify: `src/flab2bp/layout/freeform.py` (`FreeformLayout._sweep`, `FreeformLayout.lay_out`)
- Modify: `src/flab2bp/layout/sequence_solver.py` (`_refusal_stats` (new), `SequencePairLayout.lay_out`'s re-raise)
- Modify: `scripts/audit.py` (`Result`, `run_cell`, `record`)
- Test: `tests/layout/test_base.py`, `tests/layout/test_freeform.py`, `tests/scripts/test_audit.py`

**Interfaces:**
- Consumes: `NoValidLayout(reason, *, spec_label="", budget_s=0.0, attempt_reasons=(), attempt_failures=(), projection_failures=())`; `audit.Result` (frozen dataclass, CLEAN/INVALID sites build it from **12 positional args**, `field` already imported); `audit.record(tallies, r)`; `sequence_solver._ProductionRun` (`solver`, `telemetry`, `heights`, `ceiling`); `sequence_alns.operator_tally(session) -> str`.
- Produces:
  - `NoValidLayout(..., stats: Mapping[str, float | str] | None = None)` and `NoValidLayout.stats: dict[str, float | str]` (empty when not supplied). **Arity change; grep the quoted name.**
  - `FreeformLayout._sweep(..., telemetry: dict[str, float | str] | None = None)`. **Arity change; the four `_sweep` stubs Task 3 gave `**_kwargs` already absorb it — re-grep and confirm.**
  - `sequence_solver._refusal_stats(run: _ProductionRun) -> dict[str, float | str]`.
  - `audit.Result.stats: dict[str, float | str] = field(default_factory=dict)`, appended LAST so the 12 positional construction sites do not shift, and a `"stats"` key on every JSONL row that has one.

**Deviation from the spec, recorded here and amended into §5.3.2 and §6 by Task 14.** The spec declares `Mapping[str, float]` / `dict[str, float]`, but Gate E2 asserts on `alns_operators`, which `PlacementStats` types as `str` and `operator_tally` returns as a string. The value type is `float | str`. Keys absent on a row read as zero, or as the empty string for `alns_operators`.

**Scope note (review B I10).** `src/flab2bp/pipeline.py` constructs and raises its own `NoValidLayout`, and `src/flab2bp/layout/strategy_race.py` re-raises for the racing path. Neither is in this task's file list, so the CLI and web paths carry no `stats`. That is deliberate: the audit gate calls `strategy.lay_out` directly and catches `NoValidLayout` inside the worker, so nothing about the exception is pickled and the gate is unaffected. Record the gap in Task 14's status note rather than widening this task.

- [ ] **Step 1: Write the failing tests**

Append to `tests/layout/test_base.py`:

```python
def test_no_valid_layout_carries_optional_solver_stats() -> None:
    """A REFUSED row with no stats is a refusal nobody can attribute.

    R3 §5.3 measured it: every `alns_*` stat is written in
    `_with_observational_stats`, which only runs on a SUCCESSFUL placement, so a
    refused cell reported nothing about the search that refused it.
    """
    bare = NoValidLayout("nothing wired", spec_label="x", budget_s=30.0)
    carried = NoValidLayout(
        "nothing wired",
        spec_label="x",
        budget_s=30.0,
        stats={"stages": 11.0, "alns_operators": "destroy:failed-endpoints:9"},
    )

    assert bare.stats == {}
    assert carried.stats["stages"] == 11.0
    assert carried.stats["alns_operators"] == "destroy:failed-endpoints:9"
```

Append to `tests/scripts/test_audit.py` (`Job.power` is `init=False` and must not be passed):

```python
def test_a_refused_row_carries_the_solver_stats_from_the_exception() -> None:
    audit._JSONL.clear()
    job = audit.Job(
        strategy="sequence-pair",
        url_id=URL_CORPUS[0].url_id,
        url=URL_CORPUS[0].url,
        tier=URL_CORPUS[0].tier.value,
        spec_index=0,
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        budget=1.0,
        workers=1,
    )

    audit.record(
        {"sequence-pair": audit.Tally()},
        audit.Result(
            job,
            "REFUSED",
            "no-proliferator",
            "deadline exhausted",
            ("<refused>",),
            1.0,
            stats={"stages": 11.0, "alns_window_solves": 0.0},
        ),
    )

    assert audit._JSONL[0]["stats"] == {"stages": 11.0, "alns_window_solves": 0.0}


def test_a_row_without_stats_omits_the_key() -> None:
    audit._JSONL.clear()
    job = audit.Job(
        strategy="freeform",
        url_id=URL_CORPUS[0].url_id,
        url=URL_CORPUS[0].url,
        tier=URL_CORPUS[0].tier.value,
        spec_index=0,
        candidate_policies=(CandidatePolicy.NO_PROLIFERATOR,),
        budget=1.0,
        workers=1,
    )

    audit.record({"freeform": audit.Tally()}, audit.Result(job, "CRASH", "?", "", (), 1.0))

    assert "stats" not in audit._JSONL[0]
```

Append to `tests/layout/test_freeform.py`:

```python
def test_a_freeform_refusal_carries_the_sweep_s_own_counters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The keys Gate E2 reads off a REFUSED freeform row."""
    spec = two_stage_spec()
    strips = plan_strips(spec)
    monkeypatch.setattr(freeform, "_candidate_heights", lambda _strips: [20])
    telemetry: dict[str, float | str] = {}

    FreeformLayout(band_policy=BandPolicy("portable"), arrangements=1)._sweep(
        spec,
        strips,
        1.0,
        session=OperatorSession(),
        telemetry=telemetry,
    )

    assert set(telemetry) >= {
        "evaluations",
        "distinct_assignments",
        "stale_draws",
        "window_solves",
        "window_accepted",
        "alns_operators",
    }
```

- [ ] **Step 2: Run the tests to verify they fail on master**

Run: `uv run pytest tests/layout/test_base.py tests/scripts/test_audit.py tests/layout/test_freeform.py -q -k "solver_stats or refused_row or without_stats or sweep_s_own_counters"`
Expected: `TypeError: NoValidLayout.__init__() got an unexpected keyword argument 'stats'`; `TypeError: Result.__init__() got an unexpected keyword argument 'stats'`; `TypeError: _sweep() got an unexpected keyword argument 'telemetry'`. `test_a_row_without_stats_omits_the_key` passes on master and is the guard that a stats-free row stays stats-free.

- [ ] **Step 3: Add `NoValidLayout.stats`**

`src/flab2bp/layout/base.py` imports `dataclasses`, `enum`, `fractions`, `typing` and a `TYPE_CHECKING` import of `BuildSpec` — **no `collections.abc` at all**. Add to the module's import block:

```python
from collections.abc import Mapping
```

Without it, `from __future__ import annotations` keeps the module importable while strict mypy reports `Name "Mapping" is not defined` — a new diagnostic against the locked 184.

Add the keyword to `NoValidLayout.__init__` after `projection_failures` and set the attribute:

```python
stats: Mapping[str, float | str] | None = (None,)
```

```python
        #: Solver telemetry from the run that refused, or empty.  A refusal with
        #: no numbers is a refusal no gate can attribute a lever to: R3 §5.3
        #: measured every `alns_*` stat as written only on the SUCCESS path, so a
        #: REFUSED audit row carried nothing about the search that produced it.
        #: Keys absent on a row read as zero, or as the empty string for
        #: `alns_operators`, which is a tally string rather than a number.
        self.stats: dict[str, float | str] = dict(stats or {})
```

- [ ] **Step 4: Publish freeform's counters**

Add `telemetry: dict[str, float | str] | None = None` to `FreeformLayout._sweep`'s keyword-only parameters and document it:

```
        ``telemetry`` receives this sweep's counters whatever the outcome, so a
        refusal can carry them.  `best.stats` is stamped only when a placement
        exists, and a refusing cell is precisely the one whose numbers a gate
        needs.
```

Add `stale_draws = 0` beside `evaluations = 0` in `_sweep`'s counter block, with:

```python
        #: Consecutive draws that added no new entry to `routed_assignments`.
        #: Task 11 makes it move; it is published from here so the refused-row
        #: schema does not change again a task later.
        stale_draws = 0
```

Replace the guarded stamping block immediately before `return best`. **Keep the per-key assignments** — `PlacementStats` is a `TypedDict, total=False`, so `best.stats.update(<dict[str, float | str]>)` produces an `arg-type` diagnostic and a `type: ignore` with the wrong code is itself a new diagnostic under the 184 baseline:

```python
        if telemetry is not None:
            telemetry["alns_choices"] = float(len(session.choices))
            telemetry["alns_applied"] = float(session.applied)
            telemetry["alns_evaluations"] = float(evaluations)
            telemetry["alns_routing_seconds"] = session.routing_seconds
            telemetry["alns_operators"] = operator_tally(session)
            telemetry["alns_window_solves"] = float(window_solves)
            telemetry["alns_window_accepted"] = float(window_accepted)
            telemetry["alns_window_seconds"] = window_seconds
            telemetry["alns_encode_errors"] = float(window_encode_errors)
            telemetry["alns_skipped_no_goods"] = float(window_skipped_no_goods)
            # The names spec 5.3.2 asks for on a REFUSED freeform row, beside the
            # `alns_*` names the CLEAN rows already use.
            telemetry["evaluations"] = float(evaluations)
            telemetry["distinct_assignments"] = float(len(routed_assignments))
            telemetry["stale_draws"] = float(stale_draws)
            telemetry["window_solves"] = float(window_solves)
            telemetry["window_accepted"] = float(window_accepted)
        # `stats["route_backend"]` is stamped in `lay_out`, where none of these
        # locals exist, so the operator telemetry is stamped here instead --
        # guarded, because a sweep that refuses has no placement to carry it.
        if best is not None:
            best.stats["alns_choices"] = float(len(session.choices))
            ...  # the nine remaining existing assignments, verbatim and unchanged
        return best
```

- [ ] **Step 5: Attach the stats at freeform's raise sites**

In `FreeformLayout.lay_out`, beside `skipped_heights`:

```python
        sweep_telemetry: dict[str, float | str] = {}
```

Pass `telemetry=sweep_telemetry,` to `self._sweep(...)`, and immediately after `over_band` is bound:

```python
        refusal_stats: dict[str, float | str] = {
            **sweep_telemetry,
            "attempts": float(len(attempts)),
            "skipped_heights": float(len(skipped_heights)),
        }
```

Add `stats=refusal_stats,` to all three post-sweep raises (`rejected`, `deadline_expired`, and the final one).

- [ ] **Step 6: Attach the stats at sequence-pair's re-raise**

Beside `_with_observational_stats` in `sequence_solver.py`:

```python
def _refusal_stats(run: _ProductionRun) -> dict[str, float | str]:
    """Telemetry for a run that produced no placement.

    A subset of `_with_observational_stats`' keys, and deliberately only the ones
    that exist without an incumbent: there is no placement to measure area, belt
    tiles or a validation verdict on.  `stages` is the count a gate needs to
    bound the product probe's cost (R3 §4.4 measured a 45% stage loss when the
    window arm fires freely), and it is already a published `PlacementStats` key
    on CLEAN sequence-pair rows, so a gate joins the two arms on one name.
    """
    telemetry = run.telemetry
    session = run.solver.alns_session
    return {
        "stages": float(len(run.solver._stage_stats)),
        "heights": float(len(run.heights)),
        "alns_choices": float(len(session.choices)),
        "alns_applied": float(session.applied),
        "alns_evaluations": float(telemetry.alns_evaluations),
        "alns_operators": operator_tally(session),
        "alns_window_solves": float(telemetry.alns_window_solves),
        "alns_window_accepted": float(telemetry.alns_window_accepted),
        "alns_window_seconds": telemetry.alns_window_seconds,
        "alns_skipped_no_goods": float(telemetry.alns_skipped_no_goods),
        "global_routes": float(telemetry.global_routes),
        "detailed_routes": float(telemetry.detailed_routes),
    }
```

**The three `alns_window_dropped_*` / `alns_window_unchanged` fields do not exist on `_ProductionTelemetry` yet.** Task 9 adds both the fields and the three keys here. Referencing them now raises `AttributeError` on the first refusal and fails this task's whole-suite step.

Add `stats=_refusal_stats(run),` to the `except NoValidLayout` re-raise in `SequencePairLayout.lay_out` — the one where `run` is in scope. `SequenceSolver.search`'s own raise stays bare: the solver holds no telemetry object, and the re-raise is the hook R3 §5.3 named.

- [ ] **Step 7: Add `Result.stats` and the JSONL key**

In `scripts/audit.py`, add the field at the **end** of `Result` (the CLEAN and INVALID sites build it from 12 positional args; inserting earlier would silently shift them):

```python
    #: Solver telemetry for THIS cell.  Present on CLEAN rows from
    #: `PlacementStats` and on REFUSED rows from `NoValidLayout.stats` or the
    #: rejected placement's own stats; absent from the JSONL when empty, and read
    #: as empty by every consumer.  Values are numbers except `alns_operators`,
    #: which is a tally string.
    stats: dict[str, float | str] = field(default_factory=dict)
```

`run_cell` has **two** REFUSED returns, and the second is the one that is easy to miss. Resolve both with `find_symbol(include_body=True)` on `run_cell` — do NOT count them with `grep -c '"REFUSED"' scripts/audit.py`, which prints 3 because the third hit is `if r.status == "REFUSED":` inside `record`, and so confirms nothing.

1. the `except NoValidLayout` handler → `stats=dict(exc.stats),`;
2. the `except finalize.ProjectionRefusal` handler that follows the audit's own `finalize.finalize_placement` call → a placement EXISTS there, so it gains `stats=dict(placement.stats),`. Without this, Gate E1's clause 5 ("every REFUSED row carries a non-empty `stats` object") is unreachable for any cell that finalizes and is then projected out.

The CLEAN and INVALID returns, which are not REFUSED, each gain `stats=dict(placement.stats),` too — four call sites in total.

In `record`, immediately before `_JSONL.append(row)`:

```python
    # Present exactly where the strategy produced numbers.  A CRASH or SPEC row
    # never reached a solver, so it carries none and the key is absent.
    if r.stats:
        row["stats"] = dict(r.stats)
```

- [ ] **Step 8: Grep the quoted names, and check `Result` hashability**

```bash
grep -rn '"NoValidLayout"\|"_sweep"\|"Result"\|"run_cell"\|"record"' src tests scripts
grep -rn 'set\[.*Result\]\|dict\[.*Result,\|hash(.*Result\|{result\b' scripts/audit.py tests/scripts/test_audit.py
```

`Result` is `@dataclass(frozen=True)` and therefore currently hashable; adding a `dict` field makes instances unhashable at runtime. The second grep is there to prove no site hashes one or puts one in a `set`. If one does, stop and report rather than changing the field type. Expected on master: no hits for `"NoValidLayout"`, `"Result"` or `"record"`; one hit for `"run_cell"` (`tests/scripts/test_audit.py:575`); four `"_sweep"` hits already carrying `**_kwargs` from Task 3.

- [ ] **Step 9: Run the tests and prove a real row**

```bash
uv run pytest -q; echo "exit=$?"
{ uptime; vmstat 1 3; } | tee -a /tmp/phase-e-task7-load.txt
rm -f /tmp/phase-e-task7.jsonl
uv run python scripts/audit.py --budget 30 --jobs 6 --only universe-matrix \
  --json /tmp/phase-e-task7.jsonl | tail -8
uv run python -c "
import json
for row in map(json.loads, open('/tmp/phase-e-task7.jsonl')):
    print(row['strategy'], row['spec_label'], row['status'], sorted(row.get('stats', {}))[:8])
"
```

Expected: `exit=0`; every REFUSED row prints a non-empty key list, and the sequence-pair `no-proliferator` row includes `stages` and `alns_operators`.

- [ ] **Step 10: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/base.py src/flab2bp/layout/freeform.py \
  src/flab2bp/layout/sequence_solver.py scripts/audit.py \
  tests/layout/test_base.py tests/layout/test_freeform.py tests/scripts/test_audit.py
uv run mypy 2>&1 | tail -3
git add src/flab2bp/layout/base.py src/flab2bp/layout/freeform.py \
  src/flab2bp/layout/sequence_solver.py scripts/audit.py \
  tests/layout/test_base.py tests/layout/test_freeform.py tests/scripts/test_audit.py
git commit -m "feat(bench): carry solver stats onto refused audit rows

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KufubYYxUsR9JHQo5xHPtv"
```

---

### Task 8: Gate E1 — seating and ceilings

Spec §7, Gate E1. Judges Tasks 2 to 7.

**Files:**
- Create: `docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/e1-base-round{1,2,3}.jsonl`
- Create: `docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/e1-cand-round{1,2,3}.jsonl`
- Create: `docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/e1-load.txt`
- Create: `docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/gate-e1.md`

**Interfaces:**
- Consumes: Task 1's `baseline.md` (its first line is `branch point: <hash>`); `scripts/audit.py --budget 30 --jobs 16 --json PATH`; `scripts/audit_compare.py BASELINE CANDIDATE --noise-area 0.013 --p95-seconds 31 --expect-cells 72 --regressions-only --require-clean strategy/url_id/spec_label`.
- Produces: the committed Gate E1 record. Task 13 uses `e1-cand-round{1,2,3}.jsonl` as Gate E2's baseline.

- [ ] **Step 1: Confirm the tree is green**

```bash
uv run python setup.py build_ext --inplace
uv run pytest -q; echo "exit=$?"
uv run ruff check .
uv run mypy 2>&1 | tail -3
```

Expected: `exit=0`, ruff clean, mypy at exactly 184.

- [ ] **Step 2: Build the two archives**

The baseline is **the branch-point hash Task 1 recorded**, read out of `baseline.md`. It is never derived from `origin/master` (this repository's stated main branch is `sequence-pair-solver`, and `origin/master` was measured 73 commits behind) and never from `HEAD~N`. **No `|| echo` fallbacks:** a command that cannot resolve its inputs fails the step.

Both arms run from a `git archive` so neither can read the other's working tree, with a hand-frozen `.git` so `audit._head_commit` stamps every row with the tree it measured (`_head_commit` runs `git rev-parse HEAD` with `cwd=_ROOT` and returns `"unknown"` on failure). `audit.py` does `sys.path.insert(0, str(_ROOT)); sys.path.insert(0, str(_ROOT / "src"))`, so each archive's own `src/` wins over the editable install and the two arms really do run different code.

```bash
set -euo pipefail
root=$(git rev-parse --show-toplevel)
d="$root/docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix"
base=$(sed -n 's/^branch point: //p' "$d/baseline.md" | head -1)
[ -n "$base" ] || { echo "baseline.md has no 'branch point: <hash>' first line"; exit 1; }
git cat-file -e "$base^{commit}"
tip=$(git rev-parse HEAD)
[ "$base" != "$tip" ] || { echo "base == tip; the gate would measure nothing"; exit 1; }
git merge-base --is-ancestor "$base" "$tip"
echo "base $base"; echo "tip  $tip"

arch=/tmp/phase-e-gate1
rm -rf "$arch"; mkdir -p "$arch/base" "$arch/cand"
git archive "$base" | tar -x -C "$arch/base"
git archive "$tip"  | tar -x -C "$arch/cand"
for arm in base cand; do
  sha=$([ "$arm" = base ] && echo "$base" || echo "$tip")
  mkdir -p "$arch/$arm/.git/objects" "$arch/$arm/.git/refs"
  printf '%s\n' "$sha" > "$arch/$arm/.git/HEAD"
  cp "$root"/src/flab2bp/layout/_*.cpython-*-linux-gnu.so "$arch/$arm/src/flab2bp/layout/"
  ( cd "$arch/$arm" && git rev-parse HEAD )
done
git diff --no-ext-diff --name-only "$base" "$tip" -- '*.pyx' | tee /tmp/phase-e-pyx.txt
```

Expected: the two `git rev-parse HEAD` lines print `$base` and `$tip`, and `/tmp/phase-e-pyx.txt` is **empty**. Copying the candidate's compiled kernels into the base tree is only sound while no `.pyx` changed between the two commits; if that file is non-empty, build each arm's kernels from its own sources instead and record that in `gate-e1.md`.

The baseline archive keeps the branch point's `scripts/audit.py` verbatim. `audit_compare.py` reads only `strategy`, `url_id`, `spec_index`, `spec_label`, `status`, `area`, `seconds` and `detail`, all of which both trees write; the `stats` clause is judged on the CANDIDATE rows alone, where Task 7 is what puts them there.

- [ ] **Step 3: Run three interleaved rounds**

Task 1's baseline rounds are the pre-flight record. These are the paired ones: baseline and candidate alternate inside each round so a load excursion lands on both arms.

```bash
set -euo pipefail
d=docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix
arch=/tmp/phase-e-gate1
py=$(git rev-parse --show-toplevel)/.venv/bin/python
for r in 1 2 3; do
  for arm in base cand; do
    rm -f "$d/e1-$arm-round$r.jsonl"
    { echo "== round $r arm $arm"; uptime; vmstat 1 3; } >> "$d/e1-load.txt"
    "$py" "$arch/$arm/scripts/audit.py" --budget 30 --jobs 16 \
      --json "$d/e1-$arm-round$r.jsonl" | tail -6
  done
done
wc -l "$d"/e1-*-round*.jsonl
```

Expected: 72 rows in each of the six files. Never wait for the load to drop; the `uptime`/`vmstat` block before each round is the record.

- [ ] **Step 4: Compare each round**

```bash
d=docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix
for r in 1 2 3; do
  echo "== round $r"
  uv run python scripts/audit_compare.py "$d/e1-base-round$r.jsonl" "$d/e1-cand-round$r.jsonl" \
    --noise-area 0.013 --p95-seconds 31 --expect-cells 72 --regressions-only \
    --require-clean freeform/universe-matrix/output-products \
    --require-clean freeform/universe-matrix/all-products \
    --require-clean sequence-pair/universe-matrix/output-products \
    --require-clean sequence-pair/universe-matrix/all-products
done
```

Expected, per round: no `FAIL REGRESSION:` line, no `FAIL INVALID:`/`FAIL CRASH:` line, no `FAIL NOT CLEAN:` line for the four required cells, `area ratio` at or under 1.0130, `p95` at or under 31.0. The two `no-proliferator` cells appear as `CARRIED:` notes, which `--regressions-only` exists to allow and which are never counted as failures.

- [ ] **Step 5: Judge the clauses `audit_compare` does not carry**

```bash
uv run python - <<'EOF'
import json, math, pathlib
d = pathlib.Path("docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix")
per_cell: dict[tuple[str, str, str], list[float]] = {}
for r in (1, 2, 3):
    base = {(x["strategy"], x["url_id"], x["spec_label"]): x
            for x in map(json.loads, (d / f"e1-base-round{r}.jsonl").open())}
    rows = [json.loads(line) for line in (d / f"e1-cand-round{r}.jsonl").open()]
    secs = sorted(x["seconds"] for x in rows)
    p95 = secs[min(len(secs) - 1, math.ceil(0.95 * len(secs)) - 1)]
    print(f"round{r}: clean {sum(x['status'] == 'CLEAN' for x in rows)}/{len(rows)}  "
          f"p95 {p95:.2f}s  max {secs[-1]:.2f}s  "
          f"invalid {sum(x['status'] == 'INVALID' for x in rows)}  "
          f"crash {sum(x['status'] == 'CRASH' for x in rows)}")
    for x in rows:
        key = (x["strategy"], x["url_id"], x["spec_label"])
        b = base.get(key)
        if x["status"] == "CLEAN" and b and b["status"] == "CLEAN" and b["area"] > 0:
            per_cell.setdefault(key, []).append(x["area"] / b["area"])
        if x["status"] == "REFUSED" and not x.get("stats"):
            print(f"    NO STATS {x['strategy']} {x['url_id']}/{x['spec_label']}")
    np_free = next(x for x in rows
                   if x["strategy"] == "freeform" and x["url_id"] == "universe-matrix"
                   and x["spec_label"] == "no-proliferator")
    print(f"    no-proliferator/freeform {np_free['status']} "
          f"projection_failures={np_free['projection_failures']} "
          f"detail={np_free['detail'][:110]}")
for key, ratios in sorted(per_cell.items()):
    if len(ratios) == 3 and min(ratios) > 1.13:
        print(f"    AREA OUTLIER {key} {['%.3f' % v for v in ratios]}")
EOF
```

Expected: `invalid 0`, `crash 0`, `p95` at or under 31.00, `max` at or under 35.00, no `NO STATS` line, no `AREA OUTLIER` line, and the `no-proliferator/freeform` line showing `projection_failures=[]` and a detail that names routing or port seating — never `game.blueprint_area`, never "rejected by our own validator".

- [ ] **Step 6: Write `gate-e1.md`**

`gate-e1.md` contains, and nothing else:
- the base and tip hashes from Step 2, the two `git rev-parse HEAD` lines proving the frozen `.git` works, and the `.pyx` diff result;
- the three `audit_compare.py` output blocks verbatim;
- the Step 5 output verbatim;
- a pointer to `e1-load.txt`;
- one line per Gate E1 clause stating PASS or FAIL:
  1. `universe-matrix/output-products` and `universe-matrix/all-products` CLEAN under both strategies in every round.
  2. Zero REGRESSION lines against the paired baseline round; INVALID 0; CRASH 0.
  3. Paired area ratio over the baseline-clean cells within `--noise-area` 0.013 in every round, and no single cell above 1.13x reproduced in all three rounds.
  4. p95 wall at most 31 s; max cell at most 35 s.
  5. The `no-proliferator` freeform refusal names routing, not the validator; its `projection_failures` is empty; every REFUSED row carries a non-empty `stats` object.

- [ ] **Step 7: Apply the §5.2.1 reversion rule if clause 3 failed**

Only if clause 3 failed: revert Task 5's commit (`git revert --no-commit <task 5 sha>`, then commit with the trailer), rebuild, and re-run Steps 3 to 5 into `e1-cand-nowitness-round{1,2,3}.jsonl`. If that arm passes clause 3, keep the reversion and record both numbers in `gate-e1.md` and in the spec status note (Task 14). If it fails too, the witness change is not the cause: restore it and report.

- [ ] **Step 8: Commit**

```bash
git add docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix
git commit -m "bench: record gate E1 for the seating rule and the band ceilings

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KufubYYxUsR9JHQo5xHPtv"
```

If any clause fails, commit under `bench: record a failed gate E1`, name the failing cells and their `detail` strings in `gate-e1.md`, and report before starting Task 9.

---

### Task 9: Probe the operator product and count the window drops

Spec §5.5. Delivered before the freeform work so Gate E2's sequence-pair clause has its counters (spec §8 item 6).

**Files:**
- Modify: `src/flab2bp/layout/sequence_alns.py` (`OperatorSession.select`, the module docstring)
- Modify: `src/flab2bp/layout/sequence_solver.py` (`_ProductionTelemetry`, `_RepairAdapters`, `_alns_substitution`, `_production_run.window_pack`, the `_RepairAdapters` construction site, `_with_observational_stats`' stats dict, `_refusal_stats`)
- Modify: `src/flab2bp/layout/base.py` (`PlacementStats`)
- Test: `tests/layout/test_sequence_alns.py`, `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: `sequence_alns._Ledger.best(exploration, *, among=None) -> str`; `OperatorSession._affordable_repairs(context) -> tuple[str, ...]`; `SHIPPED_DESTROY = (FAILED_ENDPOINTS, BAND_BOUNDARY)`; `SHIPPED_REPAIR = (SEQUENCE_REINSERT, LOCAL_EXACT_PACK)`; `sequence_solver._RepairAdapters(window_pack=None, window_installed=None)`; `tests/layout/test_sequence_solver.py::_window_arms() -> OperatorSession` (it returns a SESSION, not a fixture tuple) and `_substitution_fixture()` / `_call_alns` / `_run_alns`, which are the helpers that return a problem/state/decoded/routing shape.
- Produces:
  - `OperatorSession.select(context) -> OperatorChoice` — **signature unchanged**; its first `|D| x |R|` draws change value.
  - `_RepairAdapters.window_dropped: Callable[[str], None] | None = None`.
  - `_ProductionTelemetry.alns_window_dropped_empty / .alns_window_dropped_whole / .alns_window_unchanged`, all `int = 0`.
  - Three new `PlacementStats` keys of the same names, typed `float`, plus the same three keys in `_refusal_stats`.

**Ruling E1 — the probe order, and why (this supersedes the earlier plan and the spec's §5.5.1 formula's ambiguity).** The product is walked **destroy-major with the repair order AS DECLARED**:

| draw | pairing | vs master |
|---|---|---|
| 0 | `(FAILED_ENDPOINTS, SEQUENCE_REINSERT)` | **identical to master** |
| 1 | `(FAILED_ENDPOINTS, LOCAL_EXACT_PACK)` | new — the window posed against the failure set |
| 2 | `(BAND_BOUNDARY, SEQUENCE_REINSERT)` | new |
| 3 | `(BAND_BOUNDARY, LOCAL_EXACT_PACK)` | master's draw 1 |

Keeping draw 0 byte-identical is what minimises the blast radius: **measured**, reversing the repair axis (so draw 0 became `(FE, LOCAL_EXACT_PACK)`) broke eight further tests in `tests/layout/test_sequence_solver.py`, six of them solver-behaviour tests whose outcome moved because the production solver's FIRST repair changed. Under Ruling E1's order those six pass unchanged. The window still gets the failure set on its first window draw, one ordinal later.

- [ ] **Step 1: Write the eight new selector tests**

Every expected value below was **measured** by installing this exact `select` body over `OperatorSession.select` on a `git archive` of master with the compiled kernels copied in.

Append to `tests/layout/test_sequence_alns.py`:

```python
def test_the_window_arm_is_paired_with_the_failure_set_on_its_first_window_draw() -> None:
    """The pairing master can never make.

    R3 §1.2 proves the two ledgers are index-isomorphic under every reward
    sequence -- `observe` credits both from the same vector and the same
    `applied` flag -- so `(FAILED_ENDPOINTS, LOCAL_EXACT_PACK)` and
    `(BAND_BOUNDARY, SEQUENCE_REINSERT)` are structurally unreachable.  Verified
    over 60,000 randomized draws and 166 real corpus selections: zero cross
    pairings.

    The probe walks the product destroy-major in declaration order, so draw 0
    stays master's `(FAILED_ENDPOINTS, SEQUENCE_REINSERT)` and the FIRST draw
    that names the window is draw 1 -- paired with the routing-failure set, which
    is the evidence the window was designed for.
    """
    session = OperatorSession()

    first = session.select(_context(remaining_fraction=C_CONTEXT_FRACTION_STEPS))
    session.observe(first, (0.0,) * REWARD_RANKS, applied=True)
    second = session.select(_context(remaining_fraction=C_CONTEXT_FRACTION_STEPS))

    assert (first.destroy, first.repair) == (
        DestroyOperator.FAILED_ENDPOINTS,
        RepairOperator.SEQUENCE_REINSERT,
    )
    assert (second.destroy, second.repair) == (
        DestroyOperator.FAILED_ENDPOINTS,
        RepairOperator.LOCAL_EXACT_PACK,
    )


def test_every_shipped_pairing_is_reachable_inside_the_probe() -> None:
    """The honest statement of the defect, as a table master cannot pass.

    Asserted WITHIN the first `|D| x |R|` draws, because that is the property
    being bought: every pairing is played once before any is played twice.
    """
    session = OperatorSession()
    rewards = [
        (1.0, 0.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 0.0, 1.0, 0.0),
    ]
    seen: set[tuple[DestroyOperator, RepairOperator]] = set()
    for reward in rewards[: len(SHIPPED_DESTROY) * len(SHIPPED_REPAIR)]:
        choice = session.select(_context(remaining_fraction=C_CONTEXT_FRACTION_STEPS))
        seen.add((choice.destroy, choice.repair))
        session.observe(choice, reward, applied=True)

    assert seen == {(destroy, repair) for destroy in SHIPPED_DESTROY for repair in SHIPPED_REPAIR}


def test_the_probe_walks_the_product_destroy_major() -> None:
    """The walk's SHAPE, which is what makes the two ledgers desynchronise.

    Master's two independent untried probes alternate in lockstep and produce
    `[FE, BB, FE, BB]` on the destroy ledger; the product walk produces
    `[FE, FE, BB, BB]`, because the destroy axis advances once per `|R|` draws.
    That difference is the whole mechanism: after the walk the two ledgers carry
    different count and reward patterns, which is what keeps all four pairings
    reachable under the D-UCB.

    Both sequences give each arm the same PLAY COUNT, so the counts alone cannot
    tell the two apart -- they are asserted here as the invariant the probe must
    not break, and the ORDER is what makes this test red on master.  The repair
    sequence is `[SR, LEP, SR, LEP]` under both and is therefore not asserted.
    """
    session = OperatorSession()
    destroys: list[DestroyOperator] = []
    repairs: list[RepairOperator] = []
    for _ in range(len(SHIPPED_DESTROY) * len(SHIPPED_REPAIR)):
        choice = session.select(_context(remaining_fraction=C_CONTEXT_FRACTION_STEPS))
        destroys.append(choice.destroy)
        repairs.append(choice.repair)
        session.observe(choice, (1.0, 0.0, 0.0, 0.0, 0.0), applied=True)

    assert destroys == [
        DestroyOperator.FAILED_ENDPOINTS,
        DestroyOperator.FAILED_ENDPOINTS,
        DestroyOperator.BAND_BOUNDARY,
        DestroyOperator.BAND_BOUNDARY,
    ]
    # The probe is not permission to skip an arm: both ledgers stay balanced.
    assert all(destroys.count(arm) == len(SHIPPED_REPAIR) for arm in SHIPPED_DESTROY)
    assert all(repairs.count(arm) == len(SHIPPED_DESTROY) for arm in SHIPPED_REPAIR)


def test_the_probe_is_a_pure_function_of_the_draw_ordinal() -> None:
    """Replayability (program invariant): no RNG, no clock, no reward.

    Six draws, not four: with only the probe's own draws the assertion would be
    true even if the probe ignored the ordinal entirely.  Draws 4 and 5 come from
    the D-UCB and MUST differ between the two reward streams, which is what
    proves the equality on draws 0 to 3 is the probe's doing.
    """

    def run(rewards: list[tuple[float, ...]]) -> list[tuple[str, str]]:
        session = OperatorSession()
        pairs: list[tuple[str, str]] = []
        for index in range(6):
            choice = session.select(_context(remaining_fraction=C_CONTEXT_FRACTION_STEPS))
            pairs.append((choice.destroy.value, choice.repair.value))
            session.observe(choice, rewards[index % len(rewards)], applied=True)
        return pairs

    hot = run([(5.0, 0.0, 0.0, 0.0, 0.0), (0.0,) * REWARD_RANKS])
    cold = run([(0.0,) * REWARD_RANKS, (5.0, 0.0, 0.0, 0.0, 0.0)])

    assert hot[:4] == cold[:4]
    # Measured: hot tails on (failed-endpoints, sequence-reinsert) twice, cold on
    # (failed-endpoints, local-exact-pack) then (band-boundary, local-exact-pack).
    assert hot[4:] != cold[4:]


def test_a_probe_naming_the_window_without_room_falls_through_to_the_ducb() -> None:
    """`_affordable_repairs` still governs: the probe cannot smuggle a window in.

    Below `C_WINDOW_FRACTION_FLOOR` the probe's LOCAL_EXACT_PACK draws fall
    through to the D-UCB for BOTH arms; the ordinal still advances, so those
    pairings lose their probe turn rather than being deferred.
    """
    session = OperatorSession()
    for _ in range(len(SHIPPED_DESTROY) * len(SHIPPED_REPAIR)):
        choice = session.select(_context(remaining_fraction=0))
        assert choice.repair is not RepairOperator.LOCAL_EXACT_PACK
        session.observe(choice, (0.0,) * REWARD_RANKS, applied=True)


def test_a_dropped_window_proposal_is_charged_a_count_and_no_reward() -> None:
    """Unchanged accounting, pinned so the probe did not start paying for a drop.

    Draw 1 is the first that names the window under Ruling E1's order.  Both
    draws are observed UNAPPLIED so `session.applied` isolates the property.
    """
    session = OperatorSession()
    first = session.select(_context(remaining_fraction=C_CONTEXT_FRACTION_STEPS))
    session.observe(first, (0.0,) * REWARD_RANKS, applied=False)
    window = session.select(_context(remaining_fraction=C_CONTEXT_FRACTION_STEPS))
    session.observe(window, (0.0,) * REWARD_RANKS, applied=False)

    assert window.repair is RepairOperator.LOCAL_EXACT_PACK
    assert math.isclose(session.credit["count:local-exact-pack"], 1.0, rel_tol=1e-12)
    assert all(
        session.credit[f"reward:local-exact-pack:{rank}"] == 0.0 for rank in range(REWARD_RANKS)
    )
    assert session.applied == 0


def test_band_boundary_on_a_vertical_only_overflow_is_the_whole_problem() -> None:
    """R3 §1.4's two drop paths, pinned as behaviour.

    `band_target_for` returns the input width unchanged when a frame already
    exists, so on a band-legal placement the strict inequality inside
    `_band_boundary` can never hold and `over` is empty.  Measured: 9 empties and
    4 whole-problem lists across 13 BAND_BOUNDARY draws, zero strict subsets.
    """
    problem = _problem()
    state = AnnealState.initial(problem.size, 7)
    decoded = decode_state(problem, state)
    short = replace(problem, outline_height=decoded.used_height - 1)

    assert _band_boundary(problem, decoded, band_target_width=decoded.width) == []
    assert len(_band_boundary(short, decoded, band_target_width=decoded.width)) == problem.size


def test_a_single_repair_arm_session_is_unchanged_by_the_probe() -> None:
    """Freeform arms ONE repair, so its draws must not move.

    `FreeformLayout.lay_out` constructs
    `OperatorSession(repair_arms=(RepairOperator.LOCAL_EXACT_PACK,))`, so
    `|D| x |R| == 2` and the probe yields exactly what master's single-arm repair
    ledger and alternating destroy ledger already produced.  Measured: the first
    four draws are FE/BB/FE/BB, all with LOCAL_EXACT_PACK.
    """
    session = OperatorSession(repair_arms=(RepairOperator.LOCAL_EXACT_PACK,))
    pairs = []
    for _ in range(4):
        choice = session.select(_context(remaining_fraction=C_CONTEXT_FRACTION_STEPS))
        pairs.append((choice.destroy, choice.repair))
        session.observe(choice, (0.0,) * REWARD_RANKS, applied=True)

    assert pairs[:2] == [
        (DestroyOperator.FAILED_ENDPOINTS, RepairOperator.LOCAL_EXACT_PACK),
        (DestroyOperator.BAND_BOUNDARY, RepairOperator.LOCAL_EXACT_PACK),
    ]
```

`_band_boundary`, `_problem`, `AnnealState` and `decode_state` are all imported in `tests/layout/test_sequence_alns.py` already (`_band_boundary` lives in `sequence_alns`, which is why the bare call is correct). **`replace` is NOT**: that file's import block has no `from dataclasses import replace`, so add it in this step. Confirm both facts with `find_symbol` on the import block before writing the test; if `PlacementProblem` turns out not to be `replace`-able, build a second `_problem()` with the shorter `outline_height` instead.

- [ ] **Step 2: Write the drop-path test**

Three facts about this file's fixtures, all resolved on master with `find_symbol(include_body=True)`:

- `_window_arms() -> OperatorSession` returns a **session** armed with `destroy_arms=(FAILED_ENDPOINTS,)` and `repair_arms=(LOCAL_EXACT_PACK,)`. It is not a fixture tuple.
- `_substitution_fixture() -> tuple[PlacementProblem, AnnealState, DecodedPlacement, DetailedRouteResult]` returns **four** values and **no `metrics`**. `metrics` has exactly one source — `metrics_from_evaluation(routing, decoded, feedback, outline_height=..., band_target_width=..., validator_clean=False)` — which `_run_alns` builds internally.
- `_run_alns(fixture, *, session, adapters, cap_scale=False)` builds that `metrics` and calls `_alns_substitution` with the full keyword set; `_call_alns(*, session, adapters)` is `_run_alns(_substitution_fixture(), ...)`. **Use `_call_alns`: do not unpack the fixture and do not rebuild `metrics` by hand.**

Because `_window_arms()` arms exactly one destroy arm, the guard is reached through `destroy_strips(FAILED_ENDPOINTS, scale=problem.size, ...)` whatever the probe does. Measured on master with that fixture: `problem.size == 4` and the neighbourhood is `{0, 1, 2, 3}` — the whole problem — so the guard fires with `"whole"`, `window_pack` is never called, and `session.applied == 0` after a single `(failed-endpoints, local-exact-pack)` choice. Note also that `_alns_substitution` takes its choice through `session.observe_and_select(...)`, not `session.select(...)`.

```python
def test_a_whole_problem_destroy_set_never_reaches_the_window() -> None:
    """Pins the guard R3 §1.4 measured, and the counter that now names it.

    `_window_arms()` arms exactly one destroy and one repair, so every draw is
    `(FAILED_ENDPOINTS, LOCAL_EXACT_PACK)` and the probe cannot change which
    guard fires.  `_substitution_fixture()`'s routing evidence reaches every one
    of its four strips, so `destroy_strips` returns the whole problem and
    `_alns_substitution` credits the choice unapplied without calling the
    adapter.
    """
    calls: list[frozenset[int]] = []
    dropped: list[str] = []
    adapters = sequence_solver_module._RepairAdapters(
        window_pack=lambda window, *_args: calls.append(window) or None,
        window_dropped=dropped.append,
    )
    session = _window_arms()

    _call_alns(session=session, adapters=adapters)

    assert calls == []
    assert dropped == ["whole"]
    assert session.applied == 0
```

`sequence_solver_module` is this file's existing alias for `flab2bp.layout.sequence_solver` (it is what the file's other `_RepairAdapters` and `_pack_window` references use); confirm the alias with `find_symbol` on the import block rather than adding a second import.

- [ ] **Step 3: Run the new tests to verify they fail on master**

Run: `uv run pytest tests/layout/test_sequence_alns.py tests/layout/test_sequence_solver.py -q -p no:randomly -k "first_window_draw or reachable_inside_the_probe or destroy_major or draw_ordinal or falls_through or charged_a_count or vertical_only or single_repair_arm or whole_problem_destroy"`

**RED on master** (measured):
- `test_the_window_arm_is_paired_with_the_failure_set_on_its_first_window_draw` — master's draw 1 is `(BAND_BOUNDARY, LOCAL_EXACT_PACK)`, so the destroy assertion fails;
- `test_every_shipped_pairing_is_reachable_inside_the_probe` — a two-element `seen`; this is the test master cannot pass and the honest statement of the defect;
- `test_the_probe_walks_the_product_destroy_major` — master's destroy sequence over four draws is `[FE, BB, FE, BB]` against the asserted `[FE, FE, BB, BB]`. The two `count` assertions below it hold on master as well (2/2 on both ledgers either way); the ORDER is what is red;
- `test_a_whole_problem_destroy_set_never_reaches_the_window` — `TypeError: _RepairAdapters.__init__() got an unexpected keyword argument 'window_dropped'`.

**GREEN on master, and they must stay green** (they pin invariants the probe must not break — say so in the commit message rather than claiming them red):
- `test_the_probe_is_a_pure_function_of_the_draw_ordinal`;
- `test_a_probe_naming_the_window_without_room_falls_through_to_the_ducb`;
- `test_a_dropped_window_proposal_is_charged_a_count_and_no_reward` — master's draw 1 IS `(BAND_BOUNDARY, LOCAL_EXACT_PACK)`, so its repair assertion already holds; it is the accounting guard that the probe did not change what a drop costs;
- `test_band_boundary_on_a_vertical_only_overflow_is_the_whole_problem`;
- `test_a_single_repair_arm_session_is_unchanged_by_the_probe`.

Record the actual red/green split you observe; if a test this list calls red comes up green, stop and report rather than adjusting it.

- [ ] **Step 4: Add the product probe**

Replace `OperatorSession.select`:

```python
    def select(self, context: OperatorContext) -> OperatorChoice:
        """Choose the next destroy/repair pairing.  Consults no RNG, no clock.

        THE FIRST ``|D| x |R|`` DRAWS WALK THE PRODUCT, and the rest is the
        discounted UCB exactly as before.  Two independent ledgers whose untried
        probes both return `untried[0]` are index-ISOMORPHIC forever: `observe`
        credits both from the same reward vector and the same ``applied`` flag,
        so `best` returns the same INDEX in each at every draw and half the
        advertised portfolio is unreachable under every reward sequence.  R3 §1.2
        proves it by induction and §1.3 confirms it over 60,000 randomized draws
        and 166 real corpus selections: zero cross pairings.

        A constant probe OFFSET does not fix it -- a shifted bijection is still a
        bijection, and it only rotates WHICH two pairings are reachable (R3 §5,
        measured).  Walking the product does, and after the walk the two ledgers
        carry genuinely different count and reward patterns, so all four pairings
        stay reachable under the D-UCB.

        THE WALK IS DESTROY-MAJOR IN DECLARATION ORDER, so draw 0 is master's own
        ``(FAILED_ENDPOINTS, SEQUENCE_REINSERT)`` and draw 1 is
        ``(FAILED_ENDPOINTS, LOCAL_EXACT_PACK)`` -- the window posed against the
        routing-failure set, the evidence it was designed for.  Keeping draw 0
        identical is deliberate: it is what the production solver's first repair
        already was, and reversing the repair axis to reach the window one draw
        sooner was measured to move six solver-behaviour tests for no gain.

        TWO LEDGERS ARE KEPT.  The product is PROBED, not LEARNED, so this
        class's reason for not learning the product still holds.

        The probe is a pure function of ``len(self._choices)`` and the two arm
        tuples: no RNG, no clock, no reward.  Replay is preserved; the VALUES of
        the replayed sequence change once, deliberately and gated.

        ``_affordable_repairs`` still governs.  A probe that would name
        LOCAL_EXACT_PACK below ``C_WINDOW_FRACTION_FLOOR`` falls through to the
        D-UCB for both arms rather than smuggling a window past the floor; the
        ordinal still advances, so that pairing loses its probe turn.
        """
        affordable = self._affordable_repairs(context)
        destroy_order = self._destroy.order
        repair_order = self._repair.order
        probe = len(self._choices)
        pairing: tuple[str, str] | None = None
        if probe < len(destroy_order) * len(repair_order):
            probed_destroy = destroy_order[probe // len(repair_order)]
            probed_repair = repair_order[probe % len(repair_order)]
            if probed_repair in affordable:
                pairing = (probed_destroy, probed_repair)
        if pairing is None:
            pairing = (
                self._destroy.best(self._exploration),
                self._repair.best(self._exploration, among=affordable),
            )
        choice = OperatorChoice(
            destroy=DestroyOperator(pairing[0]),
            repair=RepairOperator(pairing[1]),
            scale=operator_scale(context),
            ordinal=len(self._choices),
        )
        self._choices.append(choice)
        self._pending = choice
        return choice
```

Add to the module docstring, after the replayability sentence:

```
The two ledgers are otherwise phi-isomorphic -- `observe` credits both from one
reward vector and one `applied` flag -- so `select` walks the destroy x repair
product on its first `|D| x |R|` draws.  Without that walk, half the shipped
pairings are unreachable under every reward sequence (R3 section 1.2).
```

- [ ] **Step 5: Add the drop counters**

In `sequence_solver.py`, add to `_ProductionTelemetry`:

```python
    #: Window proposals dropped because the destroy set was EMPTY.  Phase C open
    #: item 3; R3 §1.4 measured 9 of 13 BAND_BOUNDARY draws at 30 s here.
    alns_window_dropped_empty: int = 0
    #: ... and because it was the WHOLE problem.  4 of 13 at 30 s.
    alns_window_dropped_whole: int = 0
    #: Windows that reached CP-SAT and returned the incumbent's own assignment.
    #: 8 of 55 in R3 §4.2's `window-always` run at 120 s.
    alns_window_unchanged: int = 0
```

Add to `_RepairAdapters`:

```python
    #: Report why a LOCAL_EXACT_PACK proposal was dropped before it reached
    #: CP-SAT: ``"empty"`` or ``"whole"``.  A callback rather than a telemetry
    #: reference because `_alns_substitution` is also driven by bare-constructed
    #: and test solvers that own no telemetry.
    window_dropped: Callable[[str], None] | None = None
```

In `_alns_substitution`, replace the empty-or-whole guard:

```python
if not neighbourhood or (problem.size > 1 and len(neighbourhood) == problem.size):
    # Credit it now, as unapplied.  Leaving it pending would charge the next
    # evaluation's outcome to a choice that never ran.
    if choice.repair is RepairOperator.LOCAL_EXACT_PACK and adapters.window_dropped is not None:
        # Counted only for the window arm: these counters exist to say why
        # `alns_window_solves` is zero, and a SEQUENCE_REINSERT proposal that
        # finds nothing to destroy is a different fact.
        adapters.window_dropped("empty" if not neighbourhood else "whole")
    session.observe(choice, (0.0,) * REWARD_RANKS, applied=False)
    return unchanged, frozenset()
```

In `_production_run.window_pack`, split the combined early return so an unchanged assignment is distinguishable from an infeasible solve:

```python
        if repaired is None:
            # INFEASIBLE, UNKNOWN or unaffordable -- CP-SAT ran and gave nothing
            # to install.  The caller credits the choice as unapplied.
            return None
        if repaired.at == pack.at:
            # It solved and returned the incumbent.  Not a repair, and a distinct
            # fact from an infeasible window: R3 §4.2 measured 8 of 55.
            telemetry.alns_window_unchanged += 1
            return None
```

**Leave `window_pack`'s own `if not window or len(window) >= problem.size: return None` guard alone.** `_alns_substitution`'s guard returns before the adapter is ever called, so an increment inside `window_pack` could not fire in production; adding one there would be a dead site whose comment implies otherwise. Record that in the commit message.

Wire the callback where `_RepairAdapters` is constructed in `_production_run` (beside `window_pack=window_pack, window_installed=window_installed`):

```python
window_dropped = (_count_window_drop,)
```

with, beside the other closures in `_production_run`:

```python
    def _count_window_drop(reason: str) -> None:
        if reason == "empty":
            telemetry.alns_window_dropped_empty += 1
        else:
            telemetry.alns_window_dropped_whole += 1
```

Publish them in `_with_observational_stats`' stats dict, beside `alns_skipped_no_goods`:

```python
            "alns_window_dropped_empty": float(telemetry.alns_window_dropped_empty),
            "alns_window_dropped_whole": float(telemetry.alns_window_dropped_whole),
            "alns_window_unchanged": float(telemetry.alns_window_unchanged),
```

and add the same three keys to `_refusal_stats` (Task 7 left them out because the fields did not exist yet). Add the three names to `PlacementStats` in `src/flab2bp/layout/base.py`, in the file's alphabetical order, each typed `float`.

- [ ] **Step 6: Re-derive the ten pinned expectations**

**This list is exhaustive and measured.** The plan's `select` body above was installed verbatim over `OperatorSession.select` on a `git archive` of master (kernels copied in) and both suites were run with `-p no:randomly`. Master is green; with the probe, exactly these ten fail. Every one is a re-derivation: an expectation that changed only because draws 1 to 3 changed. Nothing else in either file moves — in particular the six `test_sequence_solver.py` solver-behaviour tests that a reversed repair axis would have broken (`test_compact_seed_closure_preserves_expansions_for_followup_candidates`, `test_the_substitution_caps_the_destroy_set_once_the_portfolio_is_open`, `test_geometric_near_miss_substitutes_feedback_candidate_before_next_height`, `test_pending_routing_feedback_uses_zero_anneal_feedback_admission`, `test_feedback_decays_once_then_adds_only_geometric_stage_evidence`, `test_topology_change_clears_stale_quality_archives_before_restart_fallback`) **pass unchanged**, which is the whole reason Ruling E1 keeps draw 0 as it is.

In `tests/layout/test_sequence_alns.py`:

1. **`test_band_boundary_is_a_shipped_arm_the_selector_can_dispatch`** — old: one observed draw, then `select().destroy is BAND_BOUNDARY`. New: BAND_BOUNDARY first appears at draw 2, because the probe plays FE twice. Observe `len(SHIPPED_REPAIR)` draws first:

```python
    session = OperatorSession()
    for _ in range(len(SHIPPED_REPAIR)):
        session.observe(session.select(_context()), (0.0,) * REWARD_RANKS, applied=True)
    assert session.select(_context()).destroy is DestroyOperator.BAND_BOUNDARY
```

   Measured new value: draw 2's destroy is `band-boundary`. Reason: the destroy axis advances once per `|R|` probe draws.

2. **`test_every_arm_is_played_once_before_any_arm_is_played_twice`** — old: `seen_destroy[:2] == [FE, BB]` and `seen_repair[:2] == [SR, LEP]`. New: `seen_destroy[:2] == [FE, FE]`, so the assertion is false by construction. **Delete this test**; `test_the_probe_walks_the_product_destroy_major` from Step 1 is its re-derivation — it carries the same per-ledger balance assertions and adds the destroy ORDER, which is the part the product walk changes. Reason: "once before twice" is a per-ledger property that the product walk expresses over `|D| x |R|` draws, not over `max(|D|, |R|)`.

3. **`test_rank_zero_outranks_every_later_rank`** — old: warm up `len(SHIPPED_DESTROY)` (2) draws, then `select().destroy is FAILED_ENDPOINTS`; the probe leaves BAND_BOUNDARY untried at draw 2, so it wins by the untried branch. New: warm up `len(SHIPPED_DESTROY) * len(SHIPPED_REPAIR)` (4). Measured new value: `failed-endpoints`, unchanged. Reason: each arm is now credited twice with the same per-arm reward, so the MEANS the test asserts on are identical; only the warm-up length moves.

4. **`test_the_less_played_arm_wins_when_every_mean_is_tied_at_zero`** — same edit, warm-up 2 → 4. Measured: after four zero-reward draws plus one more, the next `select().destroy` is `band-boundary` against a `first.destroy` of `failed-endpoints`, so `is not first.destroy` holds. Reason: identical; only the probe has to be exhausted first.

5. **`test_a_tie_on_every_nonzero_mean_is_broken_by_the_exploration_bonus`** — old pins `reward:failed-endpoints:1 == 1.81` and `reward:band-boundary:1 == 0.9` over three draws (master plays FE, BB, FE). New: the probe plays FE, FE, BB, so measured `reward:failed-endpoints:1 == 1.71` and `reward:band-boundary:1 == 1.0`; the final `select().destroy` is still `band-boundary`. Replace the two literals and rewrite the comment to `# FAILED_ENDPOINTS was credited on draws 0 and 1, so its first credit carries two discounts (0.9*0.9 + 0.9 = 1.71); BAND_BOUNDARY was credited last and carries none.` Reason: the arms' play ORDER changed, not the decay arithmetic.

6. **`test_the_exploration_bonus_never_outvotes_even_the_last_mean`** — old: draws 0 and 1 are different destroy arms, `first` is less played and `second` leads on rank 4, and `second` wins. New: draws 0 and 1 share `FAILED_ENDPOINTS`, so `credit[count:first] < credit[count:second]` becomes `1.9 < 1.9` and the test stops discriminating. Re-derive so the rank-4 leader is the MORE-played arm, which is the stronger form of the same property:

```python
def test_the_exploration_bonus_never_outvotes_even_the_last_mean() -> None:
    """A difference on rank 4 beats a bonus, which is the whole lexicographic point."""
    session = OperatorSession()
    for _ in range(len(SHIPPED_DESTROY) * len(SHIPPED_REPAIR)):
        session.observe(session.select(_context()), (0.0,) * REWARD_RANKS, applied=True)
    leader = session.select(_context())
    session.observe(leader, (0.0, 0.0, 0.0, 0.0, 1.0), applied=True)
    # `leader` is now the MORE-played arm and so carries the SMALLER bonus, and
    # the other arm's every mean is zero; the rank-4 mean still wins.
    other = next(arm for arm in SHIPPED_DESTROY if arm is not leader.destroy)
    assert session.credit[f"count:{other.value}"] < session.credit[f"count:{leader.destroy.value}"]
    assert session.select(_context()).destroy is leader.destroy
```

   Measured: `leader.destroy` is `failed-endpoints`, counts `2.3851` against `1.71`, and the next `select().destroy` is `failed-endpoints`. Reason: the property is "a mean beats a bonus"; the probe changed which arm is the less-played one, so the fixture is rebuilt to put the reward on the less-favoured side of the bonus.

7. **`test_a_zero_exploration_coefficient_collapses_to_declaration_order`** — warm-up 2 → 4. Measured new value: `failed-endpoints`, unchanged. Reason: as item 3.

8. **`test_discounting_decays_the_reward_sums_and_not_only_the_counts`** — old: draws 0 and 1 are two different DESTROY arms, and the test pins `count:failed-endpoints == 0.9`, `reward:failed-endpoints:1 == 0.9`, `count:band-boundary == 1.0`, `reward:band-boundary:1 == 4.0`. New: draws 0 and 1 share the destroy arm and differ on the REPAIR arm, so state the same property there:

```python
    session = OperatorSession()
    first = session.select(_context())
    session.observe(first, (0.0, 1.0, 0.0, 0.0, 0.0), applied=True)
    second = session.select(_context())
    session.observe(second, (0.0, 4.0, 0.0, 0.0, 0.0), applied=True)
    # The product probe plays SEQUENCE_REINSERT then LOCAL_EXACT_PACK, so the
    # repair ledger is where two different arms are credited one draw apart.
    assert first.repair is RepairOperator.SEQUENCE_REINSERT
    assert second.repair is RepairOperator.LOCAL_EXACT_PACK
    assert math.isclose(session.credit["count:sequence-reinsert"], 0.9, rel_tol=1e-12)
    assert math.isclose(session.credit["reward:sequence-reinsert:1"], 0.9, rel_tol=1e-12)
    assert math.isclose(session.credit["count:local-exact-pack"], 1.0, rel_tol=1e-12)
    assert math.isclose(session.credit["reward:local-exact-pack:1"], 4.0, rel_tol=1e-12)
```

   Measured: exactly `0.9 / 0.9 / 1.0 / 4.0` on the repair ledger. Reason: the decay arithmetic is untouched; only which ledger holds two distinct arms one draw apart moved.

In `tests/layout/test_sequence_solver.py`:

9. **`test_the_default_session_plays_every_shipped_arm`** — old: `for _ in range(len(SHIPPED_DESTROY))`, then `played == set(SHIPPED_DESTROY)`. New: two draws now play FE twice, so `played` is missing `band-boundary`. Change the loop to `range(len(SHIPPED_DESTROY) * len(SHIPPED_REPAIR))`. Measured new value: `played == {failed-endpoints, band-boundary}`. Reason: the probe needs `|D| x |R|` draws to exercise both destroy arms; the property asserted is unchanged.

10. **`test_the_production_session_arms_the_shipped_destroy_and_repair_portfolio`** — old: `for _ in range(max(len(SHIPPED_DESTROY), len(SHIPPED_REPAIR)))`, then both ledgers' sets. New: change the bound to `len(SHIPPED_DESTROY) * len(SHIPPED_REPAIR)`. Measured: both sets complete. Reason: as item 9.

- [ ] **Step 7: Run the two suites**

```bash
uv run pytest tests/layout/test_sequence_alns.py tests/layout/test_sequence_solver.py -q -p no:randomly; echo "exit=$?"
```

Expected: `exit=0`. **Any failure NOT in Step 6's list is out of scope for re-derivation: stop and report it.** A test whose expectation changes only because draws 1 to 3 changed is a re-derivation and is already listed; a test that fails for any other reason indicates a real behavioural defect and is a decision for the controller, not for the implementer.

- [ ] **Step 8: Full suite, then the FULL-corpus check**

The probe changes the first four draws of every sequence-pair cell (36 of 72). It is the widest-blast-radius change in the phase and must not wait for Gate E2, three tasks later, for its first full-corpus view.

```bash
uv run pytest -q; echo "exit=$?"
uv run ruff check .; uv run mypy 2>&1 | tail -3
{ uptime; vmstat 1 3; } | tee -a /tmp/phase-e-task9-load.txt
rm -f /tmp/phase-e-task9-full.jsonl
uv run python scripts/audit.py --budget 30 --jobs 16 --json /tmp/phase-e-task9-full.jsonl | tail -6
uv run python scripts/audit_compare.py \
  docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/e1-cand-round1.jsonl \
  /tmp/phase-e-task9-full.jsonl --noise-area 0.013 --p95-seconds 31 --expect-cells 72 \
  --regressions-only
```

Expected: `exit=0`, mypy at 184, no REGRESSION line. The freeform half must be unmoved (Step 1's single-repair-arm test pins why); any freeform area or status move is a defect, not noise, and is reported before Task 10.

- [ ] **Step 9: Read the counters off the cell**

```bash
rm -f /tmp/phase-e-task9.jsonl
uv run python scripts/audit.py --budget 30 --jobs 6 --only universe-matrix \
  --strategy sequence-pair --json /tmp/phase-e-task9.jsonl | tail -8
uv run python -c "
import json
for row in map(json.loads, open('/tmp/phase-e-task9.jsonl')):
    s = row.get('stats', {})
    print(row['spec_label'], row['status'], s.get('stages'), s.get('alns_operators'),
          s.get('alns_window_solves'), s.get('alns_window_accepted'),
          s.get('alns_window_dropped_empty'), s.get('alns_window_dropped_whole'),
          s.get('alns_window_unchanged'))
"
```

Expected: on each `universe-matrix` row, `alns_operators` names both `destroy:failed-endpoints` and `repair:local-exact-pack` with counts of at least 1, and `alns_window_solves >= 1`. Compare `stages` against Gate E1's row for the same cell: R3 §4.4 measured `force-pairs` at 9 to 15 stages against the baseline's 11 to 17, and Gate E2 bounds the loss at 25%. If `stages` falls further here, record the numbers and report before Task 10 — this is the cheap place to see that clause fail.

- [ ] **Step 10: Commit**

```bash
git add src/flab2bp/layout/sequence_alns.py src/flab2bp/layout/sequence_solver.py \
  src/flab2bp/layout/base.py tests/layout/test_sequence_alns.py \
  tests/layout/test_sequence_solver.py
git commit -m "fix(layout): probe the destroy-repair product and count the window drops

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KufubYYxUsR9JHQo5xHPtv"
```

---

### Task 10: Keep drawing while the draws are still new

Spec §5.4.2.

**Order note (Ruling 5), and it inverts the spec's §8 sequence.** The spec lists the diversification cut (§5.4.1) before the continuation (§5.4.2). Review B C3 measured that the cut is **unobservable** in that order: the arrangement gate breaks the sweep at the first `arrangement >= 1` slot while `best is None`, so `_pack` is never called for `(height, 1)` and the cut's own test raises `KeyError` rather than asserting. Of the two options offered, this plan **reorders**: the continuation lands first, behind `C_SWEEP_STALE_DRAWS`, and the cut lands next. The alternative — testing the cut through a pre-populated dict — would have tested a private local rather than the behaviour, and merging the two would have put the phase's cheapest change and its riskiest one behind one review.

Shipping the continuation alone for one commit is bounded and safe: with no cut, every later draw is byte-identical and hits the duplicate-assignment skip, so the sweep stops after `C_SWEEP_STALE_DRAWS` extra draws — three bounded CP-SAT solves that R2 §3 priced at 0.06 to 0.09 s each on these cells. That is exactly the "cost of proving there is nothing new" the staleness guard exists to bound, and both tasks land before any gate. Spec §5.4's sentence "it ships only behind the diversification cut and a staleness guard" is honoured at the phase boundary, which is what it is protecting; Task 14 records the reordering.

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` (new module constant `C_SWEEP_STALE_DRAWS`, `FreeformLayout._sweep`, `FreeformLayout.lay_out`)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `freeform._room_for_another(deadline, soft, candidate_s) -> bool` (returns `True` when `deadline is None` and the soft clock allows); `freeform._expired(deadline)`; `freeform._portfolio_soft_deadline(...)`; the `stale_draws` local Task 7 introduced and publishes.
- **Test fixtures, verified on master:** `_routing_failures(*kinds: RouteFailureKind, exhaustive: bool = False)` — **with NO kinds it returns a ROUTED result**, so a failing fixture is `_routing_failures(RouteFailureKind.SEALED_POCKET)`. `_sweep_after_first_routing(monkeypatch, first_routing, *, arrangements=2, forbid_finalization=False, heights=(20,), subsequent_routing=None, distinct_arrangements=True, deadline=None, finalizer=None, certifier=None, before_build=None, time_budget_s=1.0, pack_transform=None) -> (result, seen, attempts)` where `seen` holds `(height, arrangement)` tuples. It does not patch `freeform.time.monotonic`; callers do.
- Produces: `freeform.C_SWEEP_STALE_DRAWS: int`; a `_routed()` fixture and a `_lay_out_with_injected_packs(...)` helper in `tests/layout/test_freeform.py`; the refusal suffix `"; the sweep stopped after K draws that produced no new packing"`; `telemetry["stale_draws"]` and `telemetry["stale_stop"]`.

- [ ] **Step 1: Add the two missing test fixtures**

`tests/layout/test_freeform.py` has no fully-routed fixture and no `lay_out`-level injector. Add both beside `_sweep_after_first_routing`, factoring its monkeypatch block out rather than duplicating it:

```python
def _routed() -> DetailedRouteResult:
    """A fully routed result.  `_routing_failures()` with no kinds is also ROUTED,
    but every call site in this file passes it as the FAILING fixture, so a
    separate, unambiguous name is what stops the two being confused again.
    """
    return DetailedRouteResult(DetailedRouteStatus.ROUTED, (), (), 1, 0)


def _lay_out_with_injected_packs(
    monkeypatch: pytest.MonkeyPatch,
    spec: BuildSpec,
    *,
    first_routing: DetailedRouteResult,
    arrangements: int = 2,
    heights: tuple[int, ...] = (20,),
    distinct_arrangements: bool = True,
    time_budget_s: float = 1e6,
    deadline_after: float | None = None,
) -> Placement:
    """Drive `lay_out` over the same injected packs `_sweep_after_first_routing` uses.

    `_sweep_after_first_routing` returns the sweep's own value, which cannot show
    the REFUSAL TEXT.  This runs the same fixtures one level up so a test can
    assert on `NoValidLayout.reason`.
    """
    ...  # same monkeypatch block as `_sweep_after_first_routing`, then:
    return FreeformLayout(
        band_policy=BandPolicy("portable"),
        arrangements=arrangements,
    ).lay_out(spec, time_budget_s=time_budget_s)
```

Extract the shared body of `_sweep_after_first_routing` (the `packs` dict, the `pack` and `build` closures, and the five `monkeypatch.setattr` calls) into a module-level `_install_injected_packs(monkeypatch, spec, strips, ...) -> tuple[list, dict]` returning `(seen, packed_candidates)`, and have both callers use it. Do not copy the block.

- [ ] **Step 2: Write the failing continuation tests**

Every clock here is a monkeypatched counter — no wall-clock assertions (Ruling S).

```python
def test_repeating_packs_stop_after_the_stale_draw_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R2 §6b, bounded.  Eighty slots, five evaluations, ten seconds of nothing.

    The staleness guard is what keeps the continuation's cost to the cost of
    PROVING there is nothing new: on `universe-matrix` the counter trips after
    one arrangement round.
    """
    _result, seen, _attempts = _sweep_after_first_routing(
        monkeypatch,
        _routing_failures(RouteFailureKind.SEALED_POCKET),
        arrangements=8,
        heights=(20,),
        distinct_arrangements=False,
        time_budget_s=1e6,
    )

    assert len(seen) == 1 + freeform.C_SWEEP_STALE_DRAWS
    assert seen[0] == (20, 0)


def test_packs_that_keep_producing_new_assignments_run_to_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = 0.0

    def monotonic() -> float:
        nonlocal clock
        clock += 0.5
        return clock

    monkeypatch.setattr(freeform.time, "monotonic", monotonic)
    _result, seen, _attempts = _sweep_after_first_routing(
        monkeypatch,
        _routing_failures(RouteFailureKind.SEALED_POCKET),
        arrangements=8,
        heights=(20,),
        distinct_arrangements=True,
        deadline=12.0,
        time_budget_s=1e6,
    )

    assert len(seen) > 1 + freeform.C_SWEEP_STALE_DRAWS
    assert len(seen) <= 8


def test_a_stale_stop_names_staleness_in_the_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = two_stage_spec()

    with pytest.raises(NoValidLayout) as stale:
        _lay_out_with_injected_packs(
            monkeypatch,
            spec,
            first_routing=_routing_failures(RouteFailureKind.SEALED_POCKET),
            arrangements=8,
            distinct_arrangements=False,
        )

    assert "produced no new packing" in stale.value.reason


def test_a_cell_with_an_incumbent_after_arrangement_zero_draws_exactly_as_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The continuation runs only where `best is None`; a wiring cell is untouched."""
    _result, seen, _attempts = _sweep_after_first_routing(
        monkeypatch,
        _routed(),
        arrangements=2,
        heights=(20, 30),
        subsequent_routing=_routed(),
        time_budget_s=1e6,
    )

    assert len(seen) == 4


def test_one_explicit_arrangement_still_makes_one_draw_per_height(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--arrangements` stays a hard cap: the continuation never re-seeds."""
    _result, seen, _attempts = _sweep_after_first_routing(
        monkeypatch,
        _routing_failures(RouteFailureKind.SEALED_POCKET),
        arrangements=1,
        heights=(20, 30),
        distinct_arrangements=False,
        time_budget_s=1e6,
    )

    assert seen == [(20, 0), (30, 0)]
```

- [ ] **Step 3: Run the tests to verify they fail on master**

Run: `uv run pytest tests/layout/test_freeform.py -q -k "stale_draw or keep_producing or stale_stop or exactly_as_today or one_explicit_arrangement"`

Expected on master:
- `test_repeating_packs_stop_after_the_stale_draw_limit` FAILS with `AttributeError: module 'flab2bp.layout.freeform' has no attribute 'C_SWEEP_STALE_DRAWS'`, and would otherwise see `len(seen) == 1` because the arrangement gate breaks at slot 2;
- `test_packs_that_keep_producing_new_assignments_run_to_the_deadline` FAILS with `assert 1 > 4` — the gate breaks at the first `arrangement >= 1` slot;
- `test_a_stale_stop_names_staleness_in_the_refusal` FAILS because the refusal is the unconditional "PACKER defect"/port-seating one and carries no staleness text;
- `test_a_cell_with_an_incumbent_after_arrangement_zero_draws_exactly_as_today` and `test_one_explicit_arrangement_still_makes_one_draw_per_height` PASS on master and are the guards that they still do.

- [ ] **Step 4: Add the constant**

Beside `_ARRANGEMENTS` in `freeform.py`:

```python
#: Consecutive draws that may add no new entry to ``routed_assignments`` before
#: the sweep stops looking, when nothing has wired yet.
#:
#: MEASURED, not guessed.  R2 §6b bypassed the arrangement gate on
#: `universe-matrix` at `--arrangements 16`: EIGHTY candidate slots produced FIVE
#: routing evaluations and cost up to 10 s per cell, because every slot past
#: arrangement 0 returned a byte-identical CP-SAT assignment and hit the
#: duplicate-assignment skip.  Three draws is enough to see that the draw is not
#: moving -- each costs one bounded CP-SAT solve at 0.06 to 0.09 s on those cells
#: -- and it bounds the continuation's cost at the cost of PROVING there is
#: nothing new, which is the only thing that makes it affordable at the audit's
#: `--jobs 16`.
C_SWEEP_STALE_DRAWS = 3
```

If `3` collides with a linted game value, declare it through `registry.LintException` (Ruling AI).

- [ ] **Step 5: Replace the arrangement gate**

Add `stale_stop = False` beside `stale_draws = 0` in `_sweep`'s counter block. Replace:

```python
                if not projection_retry and arrangement and best is None:
                    break
```

with:

```python
# A SECOND ARRANGEMENT WITH NOTHING TO IMPROVE USED TO BE A HARD
# STOP, and it stopped the sweep at slot 6 of 15 with 25 to 28 s
# of a 30 s ceiling still in hand (R2 §3).  That was right while
# every later draw was a byte-identical copy of the first; with a
# diversification cut behind it, a later draw is a genuinely
# different pack, and the honest stop condition is that the draws
# have stopped being new.
#
# `_room_for_another(deadline, improvement_soft, turn_cost)`, the
# `completion_reserve_s` check and the hard `remaining <= 0`
# break all sit immediately BELOW this gate and are unchanged, so
# a draw this gate now lets through still has to buy its clock
# from them: it can only ever extend a sweep INSIDE clock it
# already had.  (The `_room_for_another` call ABOVE this gate is
# the improvement one, guarded by `best is not None`; it never
# fires on this path.)
#
# `--arrangements` remains the hard cap: `candidate_packs` is not
# re-seeded, so the continuation cannot draw a slot the caller
# did not ask for.
if not projection_retry and arrangement and best is None and stale_draws >= C_SWEEP_STALE_DRAWS:
    stale_stop = True
    break
```

Maintain the counter at the two places a draw can fail to be new:

```python
                if pack is None:
                    stale_draws += 1
                    continue
```

```python
                if assignment in routed_assignments:
                    stale_draws += 1
                    continue
                routed_assignments.add(assignment)
                stale_draws = 0
```

Publish `stale_stop` in the telemetry block Task 7 added:

```python
            telemetry["stale_stop"] = float(stale_stop)
```

The sweep keeps its ONE `OperatorSession` (constructed in `lay_out`, passed into `_sweep`), keeps calling `_portfolio_soft_deadline` per turn, and never rebinds `soft`. Confirm all three with `find_symbol` before committing; none is touched by this task.

- [ ] **Step 6: Name staleness in the refusal**

In `lay_out`, after `over_band` is bound:

```python
        stale_note = (
            f"; the sweep stopped after {int(sweep_telemetry.get('stale_draws', 0))} "
            "draws that produced no new packing"
            if sweep_telemetry.get("stale_stop")
            else ""
        )
```

Append `+ stale_note` beside `+ over_band` on all three post-sweep raises. With more evaluations the deadline branch now applies to cells that used to fall through, and it already says "N packs were routed in that time and the best of them still left M nets unrouted" — that text is unchanged.

- [ ] **Step 7: Run the tests**

```bash
uv run pytest tests/layout/test_freeform.py -q; echo "exit=$?"
uv run pytest -q; echo "exit=$?"
```

Expected: `exit=0` both times.

- [ ] **Step 8: Measure the wall cost on the corpus**

```bash
{ uptime; vmstat 1 3; } | tee -a /tmp/phase-e-task10-load.txt
rm -f /tmp/phase-e-task10.jsonl
uv run python scripts/audit.py --budget 30 --jobs 16 --json /tmp/phase-e-task10.jsonl | tail -6
uv run python scripts/audit_compare.py \
  docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/e1-cand-round1.jsonl \
  /tmp/phase-e-task10.jsonl --noise-area 0.013 --p95-seconds 31 --expect-cells 72 --regressions-only
uv run python -c "
import json
for row in map(json.loads, open('/tmp/phase-e-task10.jsonl')):
    if row['url_id'] == 'universe-matrix':
        s = row.get('stats', {})
        print(row['strategy'], row['spec_label'], row['status'], f\"{row['seconds']:.1f}s\",
              'evals', s.get('evaluations'), 'distinct', s.get('distinct_assignments'),
              'stale', s.get('stale_draws'), 'stop', s.get('stale_stop'))
"
```

Expected: no REGRESSION line; p95 at or under 31 s and max at or under 35 s. The continuation runs only where `best is None`, so a wall change on a clean cell is a defect — find it before Task 11. Without the cut, `distinct_assignments` on the freeform `no-proliferator` row is still 5 and `stale_stop` is 1: that is this commit doing exactly what R2 predicted and nothing more.

**Racing hazard, documented (spec §5.4).** A refusing freeform leg may now hold its workers until staleness or the deadline. The race is opt-in and unchanged by this phase; `wall_overshoot_s` on `best` rows is the number a later racing gate watches. Nothing here changes the serial path's clock on a cell that wires — which is what this step's p95 clause checks.

- [ ] **Step 9: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
uv run mypy 2>&1 | tail -3
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "feat(layout): keep sweeping while the draws are still new

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KufubYYxUsR9JHQo5xHPtv"
```

---

### Task 11: Make a second arrangement a different draw

Spec §5.4.1. Lands after the continuation so its cut is reachable — see Task 10's order note. R2 §6b proved the continuation is a no-op by construction without this: every arrangement above 0 returns a byte-identical CP-SAT assignment.

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` (`FreeformLayout._sweep`)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `freeform.ExactPackNoGood(height, outline, width, origins, evidence, projection_pair=None)` — its `__post_init__` requires positive dimensions, `len(outline) == len(origins)` and non-empty `evidence`; `finalize.ProjectionFailure(check, buildings, detail, band)`; `freeform._box(strip)`; `freeform.C_SWEEP_STALE_DRAWS` from Task 10; `_sweep_after_first_routing`'s `pack_transform(candidate, packed, exact_no_goods)` hook.
- Produces: no new module symbol. `_sweep` gains a local `diversification_no_goods: dict[tuple[int, int], tuple[ExactPackNoGood, ...]]`, observable only through the no-goods `_pack` is asked for.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_repeated_draw_becomes_a_diversification_cut_at_the_next_arrangement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R2 §6b: without this, every arrangement past 0 is a byte-identical pack.

    Eighty candidate slots produced FIVE routing evaluations, because CP-SAT
    returns the identical assignment for every arrangement seed on a 42-strip
    model it proves optimal in under 0.1 s, and the duplicate-assignment guard
    then drops it.  The cut is what makes arrangement N a different draw.

    Reachable only because Task 10 replaced the arrangement gate: on master the
    sweep breaks before `(20, 1)` is ever packed.
    """
    seen_cuts: dict[tuple[int, int], tuple[freeform.ExactPackNoGood, ...]] = {}

    def record(
        candidate: tuple[int, int],
        pack: freeform._Pack,
        exact_no_goods: tuple[freeform.ExactPackNoGood, ...],
    ) -> freeform._Pack:
        seen_cuts[candidate] = exact_no_goods
        return pack

    _sweep_after_first_routing(
        monkeypatch,
        _routing_failures(RouteFailureKind.SEALED_POCKET),
        arrangements=2,
        heights=(20, 30),
        distinct_arrangements=False,
        time_budget_s=1e6,
        pack_transform=record,
    )

    assert seen_cuts[20, 0] == ()
    assert seen_cuts[30, 0] == ()
    cuts_20 = seen_cuts[20, 1]
    assert len(cuts_20) == 1
    assert cuts_20[0].height == 20
    assert cuts_20[0].evidence[0].check == "pack.diversification"
    # Scoped to (height, arrangement + 1): the height 30 draw at arrangement 1
    # carries only ITS OWN height's cut, never height 20's.
    cuts_30 = seen_cuts[30, 1]
    assert len(cuts_30) == 1
    assert cuts_30[0].height == 30


def test_a_diversification_cut_is_never_taken_once_a_pack_has_wired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cell that wires is untouched, so no clean cell's area can move here."""
    seen_cuts: dict[tuple[int, int], tuple[freeform.ExactPackNoGood, ...]] = {}

    def record(
        candidate: tuple[int, int],
        pack: freeform._Pack,
        exact_no_goods: tuple[freeform.ExactPackNoGood, ...],
    ) -> freeform._Pack:
        seen_cuts[candidate] = exact_no_goods
        return pack

    result, _seen, _attempts = _sweep_after_first_routing(
        monkeypatch,
        _routed(),
        arrangements=2,
        heights=(20,),
        subsequent_routing=_routed(),
        time_budget_s=1e6,
        pack_transform=record,
    )

    assert result is not None
    assert all(cuts == () for cuts in seen_cuts.values())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_freeform.py -q -k "diversification"`
Expected against the tree as Task 10 left it: the first FAILS with `assert 0 == 1` on `len(cuts_20)` — `(20, 1)` IS now packed (Task 10 removed the unconditional break and the staleness counter is still 0 at that slot), so `seen_cuts[20, 1]` exists and is the empty tuple. The second PASSES already and is the mutant guard.

- [ ] **Step 3: Add the cut**

Beside `feedback_retry_no_goods` in `_sweep`:

```python
        #: Per-candidate DIVERSIFICATION cuts: the assignments already drawn at
        #: one height, excluded from that height's NEXT arrangement.  Deliberately
        #: NOT in `_ExactPackNoGoodState`: that class is sweep-wide by
        #: construction (`_sweep` reads `tuple(exact_no_good_state.no_goods)` for
        #: every candidate) and its entries are infeasibility PROOFS.  A pack that
        #: failed to route is not proved infeasible -- the same argument the
        #: feedback-retry cut makes for itself -- so the cut lives beside that
        #: state, keyed by `(height, arrangement)`, and never inside it.
        #:
        #: Never applied once a placement exists, so no cell that wires can see
        #: one.  The tuple carries every earlier draw at that height, so
        #: arrangement N + 1 cannot return arrangement N - 1's pack either.
        diversification_no_goods: dict[tuple[int, int], tuple[ExactPackNoGood, ...]] = {}
```

At the draw site, extend the no-good assembly:

```python
                retry_no_good = feedback_retry_no_goods.pop((height, arrangement), None)
                exact_pack_no_goods = tuple(exact_no_good_state.no_goods)
                if retry_no_good is not None:
                    exact_pack_no_goods += (retry_no_good,)
                diversification_cuts = diversification_no_goods.pop(
                    (height, arrangement),
                    (),
                )
                if best is not None:
                    # An improvement arrangement draws exactly what it drew
                    # before.  The cut exists to escape a repeated FAILING draw;
                    # applying it to a cell that already wired would move area on
                    # a cell that never asked for a second draw.
                    diversification_cuts = ()
                exact_pack_no_goods += diversification_cuts
```

Immediately after `routed_assignments.add(assignment)` (and after the `stale_draws = 0` reset Task 10 put there), record the cut for the next arrangement:

```python
                if best is None:
                    diversification_no_goods[height, arrangement + 1] = (
                        *diversification_cuts,
                        ExactPackNoGood(
                            height=pack.height,
                            outline=tuple(_box(strip) for strip in strips),
                            width=pack.width,
                            origins=tuple(pack.at[index] for index in range(len(strips))),
                            evidence=(
                                finalize.ProjectionFailure(
                                    check="pack.diversification",
                                    buildings=(),
                                    detail=(
                                        f"assignment already drawn at height {height} "
                                        f"arrangement {arrangement}; excluded from "
                                        f"arrangement {arrangement + 1} at this height only"
                                    ),
                                    band=0,
                                ),
                            ),
                        ),
                    )
```

The cut's shape is byte-identical to the existing `route.feedback_retry` cut, and both travel to `_pack` on the same `exact_pack_no_goods` tuple, so CP-SAT needs no new encoding.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/layout/test_freeform.py -q; echo "exit=$?"
uv run pytest -q; echo "exit=$?"
```

Expected: `exit=0` both times.

- [ ] **Step 5: Measure on the corpus**

```bash
{ uptime; vmstat 1 3; } | tee -a /tmp/phase-e-task11-load.txt
rm -f /tmp/phase-e-task11.jsonl
uv run python scripts/audit.py --budget 30 --jobs 16 --json /tmp/phase-e-task11.jsonl | tail -6
uv run python scripts/audit_compare.py \
  docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/e1-cand-round1.jsonl \
  /tmp/phase-e-task11.jsonl --noise-area 0.013 --p95-seconds 31 --expect-cells 72 --regressions-only
uv run python -c "
import json
for row in map(json.loads, open('/tmp/phase-e-task11.jsonl')):
    if row['url_id'] == 'universe-matrix' and row['strategy'] == 'freeform':
        s = row.get('stats', {})
        print(row['spec_label'], row['status'], 'distinct', s.get('distinct_assignments'))
"
```

Expected: no REGRESSION line, area ratio inside the noise band, and `distinct_assignments >= 2` on the freeform `no-proliferator` row — the number Gate E2 clause 4 asserts and the direct evidence that a second draw is now a different draw. A non-1.0000 area ratio on a cell that wires means a cut reached a draw it should not have; find it before Task 12.

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
uv run mypy 2>&1 | tail -3
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "feat(layout): cut a drawn assignment out of the next arrangement at its height

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KufubYYxUsR9JHQo5xHPtv"
```

---

### Task 12: Widen the window trigger to any routing failure with a slot

Spec §5.4.3, a change to Phase C's §5.7 recorded there by Task 14.

**Files:**
- Modify: `src/flab2bp/layout/freeform.py` (`_feedback_retry_eligible`, the `promote_retry` block in `_sweep`)
- Test: `tests/layout/test_freeform.py`

**Interfaces:**
- Consumes: `freeform.PackAttempt.routing`; `freeform.FeedbackState` — **frozen with `MappingProxyType` mappings, so it CANNOT be mutated after construction**, and `endpoint_offsets` values are validated as two integer CELLS (three-tuples), not `(x, y)` pairs; `freeform._window_candidate_seconds(dearest_remainder_s=...)`; `tests/layout/test_freeform.py::_feedback_bearing_routing(count: int = 1)`, whose failures carry the `source`/`destination` this predicate needs. **`_routing_failures` is variadic and takes no `count`; do not add one.**
- Produces: `_feedback_retry_eligible(attempt, feedback) -> bool` with the same signature and a wider truth set; the window launch predicate becomes `retry_slot_found and not retry_admitted and best_failing`.

**Interpretation, recorded here and amended into spec §5.4.3 by Task 14.** The spec says the window "is posed against the failing nets' strips of the best-failing pack (fewest unrouted nets)". `_sweep` poses a window against the pack it is holding and retains no earlier pack; re-posing against one would queue a repair at a candidate slot already consumed. The faithful minimal reading is a GUARD: a window launches only when the pack in hand is the best-failing one the sweep has seen **so far**. `best_failed_count` starts at `math.inf`, so the first failing pack always launches — that is the correct online behaviour and it is what the spec's wording promises more than the code can give.

**The comparison is strict `<`, not `<=`,** and that is an economic choice worth stating: R3 §4.2 prices one window solve at a hard ~1.006 s (CP-SAT hits its time limit every time) and R3 §4.4 measured the arm halving a search's stage count. A pack that merely TIES the incumbent failure count offers no better evidence than the solve already spent, so it does not buy a second one. Step 1 pins the tie.

- [ ] **Step 1: Write the failing tests**

```python
def _feedback_for(routing: DetailedRouteResult) -> freeform.FeedbackState:
    """A `FeedbackState` that knows every one of `routing`'s failing nets.

    `FeedbackState` is `@dataclass(frozen=True, slots=True)` and stores every
    mapping as a `MappingProxyType`, so it is constructed complete rather than
    mutated.  `endpoint_offsets` values are validated as two integer CELLS.
    """
    nets = [failure.net_id for failure in routing.failures]
    return freeform.FeedbackState(
        outline=(10, 10),
        net_weight=dict.fromkeys(nets, 1.0),
        cell_history={},
        endpoint_offsets={net: ((0, 0, 0), (0, 0, 0)) for net in nets},
    )


def test_a_multi_failure_attempt_is_now_retry_eligible() -> None:
    """R2 §4: `promote_retry` was false on every `universe-matrix` candidate.

    `learned` was false because a preparation failure forces
    `routing.exhaustive` false and `_proof_scoped_no_goods` returns nothing, and
    `_feedback_retry_eligible` demanded EXACTLY ONE failure against the 3 and 6
    those cells carry.  Affordability was never the blocker: `room=True` on every
    turn, window cost 1.00 to 2.37 s against 25+ s remaining.
    """
    routing = _feedback_bearing_routing(count=3)
    attempt = _proof_attempt(routing, plan_strips(two_stage_spec()))

    assert freeform._feedback_retry_eligible(attempt, _feedback_for(routing))


def test_a_routing_failure_with_no_feedback_is_still_not_retry_eligible() -> None:
    routing = _feedback_bearing_routing(count=3)
    attempt = _proof_attempt(routing, plan_strips(two_stage_spec()))

    assert not freeform._feedback_retry_eligible(attempt, freeform.FeedbackState.empty((10, 10)))


def test_the_window_launches_on_a_best_failing_pack_with_three_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slot and a clock, and no `learned` evidence: that is the trigger now."""
    monkeypatch.setattr(freeform, "_room_for_another", lambda *_args: True)
    launched: list[object] = []
    monkeypatch.setattr(
        freeform,
        "_pack_window",
        lambda *args, **kwargs: launched.append(kwargs) or None,
    )

    _sweep_after_first_routing(
        monkeypatch,
        _feedback_bearing_routing(count=3),
        arrangements=2,
        heights=(20,),
        time_budget_s=1e6,
    )

    assert launched


def test_the_window_is_withheld_on_a_pack_that_only_ties_the_best_failing_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One window solve costs a hard second (R3 §4.2) and halves the stage count;
    a pack that ties the incumbent offers no better evidence than the solve
    already spent, so it does not buy a second one.
    """
    monkeypatch.setattr(freeform, "_room_for_another", lambda *_args: True)
    launched: list[object] = []
    monkeypatch.setattr(
        freeform,
        "_pack_window",
        lambda *args, **kwargs: launched.append(kwargs) or None,
    )

    _sweep_after_first_routing(
        monkeypatch,
        _feedback_bearing_routing(count=3),
        arrangements=2,
        heights=(20, 30),
        subsequent_routing=_feedback_bearing_routing(count=3),
        time_budget_s=1e6,
    )

    assert len(launched) == 1


def test_the_window_is_withheld_on_a_pack_worse_than_the_best_failing_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(freeform, "_room_for_another", lambda *_args: True)
    launched: list[object] = []
    monkeypatch.setattr(
        freeform,
        "_pack_window",
        lambda *args, **kwargs: launched.append(kwargs) or None,
    )

    _sweep_after_first_routing(
        monkeypatch,
        _feedback_bearing_routing(count=1),
        arrangements=2,
        heights=(20, 30),
        subsequent_routing=_feedback_bearing_routing(count=9),
        time_budget_s=1e6,
    )

    assert len(launched) == 1
```

Resolve `_pack_window`'s call site in `_sweep` with `find_symbol` before writing the monkeypatch: it is called with keywords, and `tests/layout/test_freeform.py` already patches the quoted name `"_pack_window"` elsewhere — read that site for the house shape and match it rather than inventing an argument list.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/layout/test_freeform.py -q -k "multi_failure or no_feedback or best_failing or only_ties or worse_than_the_best"`
Expected: `test_a_multi_failure_attempt_is_now_retry_eligible` FAILS (`len(routing.failures) != 1` short-circuits the predicate to `False`); `test_the_window_launches_on_a_best_failing_pack_with_three_failures` FAILS on an empty `launched`; `test_the_window_is_withheld_on_a_pack_that_only_ties...` and `..._worse_than...` FAIL with `assert 0 == 1` — nothing launches at all today. `test_a_routing_failure_with_no_feedback_is_still_not_retry_eligible` PASSES on master and is the guard that the widening did not remove the feedback requirement.

- [ ] **Step 3: Widen `_feedback_retry_eligible`**

```python
def _feedback_retry_eligible(
    attempt: PackAttempt,
    feedback: FeedbackState,
) -> bool:
    """Whether this exact attempt earned one bounded evidence-driven retry.

    THE "EXACTLY ONE FAILURE" CONJUNCT IS GONE.  It was written for a near miss
    and it excluded every cell this program still refuses: R2 §4 measured
    `universe-matrix/all-products` at 3 failures and `output-products` at 6, so
    the retry -- and with it the Phase C window, whose launch is downstream of
    this -- never fired on the specs it was built for.  What the predicate is
    really asking is whether the sweep LEARNED something aimable: a failure the
    feedback state can weight and whose endpoints it knows.  One such failure is
    as aimable as one of six.
    """
    routing = attempt.routing
    if (
        routing.exhaustive
        or routing.status is not DetailedRouteStatus.STRANDED
        or not routing.failures
    ):
        return False
    return any(
        failure.net_id in feedback.net_weight and failure.net_id in feedback.endpoint_offsets
        for failure in routing.failures
    )
```

- [ ] **Step 4: Widen the launch predicate**

Restructure the retry block in `_sweep` so the SLOT is always resolved and only the ADMISSION stays gated:

```python
feedback_retry = feedback_state is not None and _feedback_retry_eligible(attempt, feedback_state)
promote_retry = arrangement == 0 and (learned or feedback_retry)
#: A window launches where a retry SLOT exists and was not
#: taken.  It used to also require `promote_retry`, which
#: is exactly the conjunct that never held on a refusing
#: cell (R2 §4): `learned` is false whenever a preparation
#: failure forces `routing.exhaustive` false, and the
#: feedback retry demanded a single failure.  The
#: affordability check below is untouched and is what
#: still bounds the cost.
retry_slot_found = False
retry_admitted = False
retry_candidate = (height, arrangement + 1)
try:
    next_index = candidate_packs.index(
        (*retry_candidate, False),
        candidate_index,
    )
except ValueError:
    pass
else:
    retry_slot_found = True
    if promote_retry:
        current_candidate_s = 0.0 if started_at is None else time.monotonic() - started_at
        retry_cost = max(dearest_candidate_s, current_candidate_s)
        if feedback_retry or _room_for_another(
            deadline,
            soft,
            retry_cost,
        ):
            if feedback_retry:
                ...  # the existing feedback_retry_no_goods
                # block, verbatim and unchanged
            retry_admitted = True
            candidate_packs.pop(next_index)
            candidate_packs.insert(
                candidate_index,
                (height, arrangement + 1, True),
            )
```

Keep the `feedback_retry_no_goods[retry_candidate] = ExactPackNoGood(...)` body exactly as it is; it reads `attempt.routing.failures[0]`, which is still a valid representative now that more than one failure can reach it.

Beside `evaluations = 0` in the counter block:

```python
        #: Fewest unrouted nets any evaluated pack has left.  A window is posed
        #: only against a pack that BEATS it, so one hard CP-SAT second (R3 §4.2)
        #: is never spent on evidence the sweep has already matched.
        best_failed_count = math.inf
```

Immediately after `failed = result.routing.failed_count`:

```python
                    best_failing = bool(failed) and failed < best_failed_count
                    if failed:
                        best_failed_count = min(best_failed_count, failed)
```

and the launch:

```python
                        if retry_slot_found and not retry_admitted and best_failing:
```

`math` is already imported in `freeform.py`; confirm with `find_symbol` before relying on it.

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/layout/test_freeform.py -q; echo "exit=$?"
uv run pytest -q; echo "exit=$?"
```

Expected: `exit=0` both times. A failure in an existing window or retry test is a re-derivation ONLY if it pins a launch the old `promote_retry` conjunct suppressed; read the test's own comment before touching it, and never weaken an affordability assertion. Anything else: stop and report.

- [ ] **Step 6: Measure — this is the riskiest change in the phase**

The launch predicate sits inside `if failed:`, so a fully routed pack is never affected. But a cell that ends CLEAN after an EARLIER failing pack can now spend a CP-SAT window and consume the `(height, arrangement + 1)` slot that would otherwise have been an improvement draw.

```bash
{ uptime; vmstat 1 3; } | tee -a /tmp/phase-e-task12-load.txt
rm -f /tmp/phase-e-task12.jsonl
uv run python scripts/audit.py --budget 30 --jobs 16 --json /tmp/phase-e-task12.jsonl | tail -6
uv run python scripts/audit_compare.py \
  docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/e1-cand-round1.jsonl \
  /tmp/phase-e-task12.jsonl --noise-area 0.013 --p95-seconds 31 --expect-cells 72 --regressions-only
```

Expected: no REGRESSION line, area ratio inside 1.013, p95 at or under 31 s. If the ratio exceeds it, record the numbers and report before Gate E2 rather than tuning: R2 §6c measured forced windows leaving the failure count the same or WORSE on these cells, so a large area move here is evidence the trigger is now too wide, not that the margin is too tight.

- [ ] **Step 7: Lint, type-check, commit**

```bash
uv run ruff check src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
uv run mypy 2>&1 | tail -3
git add src/flab2bp/layout/freeform.py tests/layout/test_freeform.py
git commit -m "feat(layout): pose the window at any routing failure with a slot and a clock

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KufubYYxUsR9JHQo5xHPtv"
```

---

### Task 13: Gate E2 — `universe-matrix/no-proliferator`, and Gate E3 if it closes

Spec §7, Gates E2 and E3. Judges Tasks 9 to 12 against Gate E1's candidate rounds.

**Files:**
- Create: `docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/e2-cand-round{1,2,3}.jsonl`
- Create: `docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/e2-load.txt`
- Create: `docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/gate-e2.md`
- Create (only if E2 passes at 72/72): `docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/e3-{freeform,sequence-pair}-rep{1..10}.jsonl` and `gate-e3.md`

**Interfaces:**
- Consumes: Gate E1's `e1-cand-round{1,2,3}.jsonl`; `scripts/audit.py`; `scripts/audit_compare.py` with the flags Task 8 used.
- Produces: the committed Gate E2 (and possibly E3) record, and the numbers Task 14's status notes carry.

**Baseline choice.** Gate E2's baseline is **Gate E1's candidate rounds**, per spec §7: the seating and ceiling work is already gated and this gate judges only what Tasks 9 to 12 added. The interleaving is therefore against fixed committed files rather than a re-run arm, and the load record is the control.

- [ ] **Step 1: Confirm the tree is green**

```bash
uv run python setup.py build_ext --inplace
uv run pytest -q; echo "exit=$?"
uv run ruff check .
uv run mypy 2>&1 | tail -3
```

Expected: `exit=0`, ruff clean, mypy at exactly 184.

- [ ] **Step 2: Build the candidate archive**

```bash
set -euo pipefail
root=$(git rev-parse --show-toplevel)
tip=$(git rev-parse HEAD); echo "tip $tip"
arch=/tmp/phase-e-gate2
rm -rf "$arch"; mkdir -p "$arch"
git archive "$tip" | tar -x -C "$arch"
mkdir -p "$arch/.git/objects" "$arch/.git/refs"
printf '%s\n' "$tip" > "$arch/.git/HEAD"
cp "$root"/src/flab2bp/layout/_*.cpython-*-linux-gnu.so "$arch/src/flab2bp/layout/"
( cd "$arch" && git rev-parse HEAD )
```

Expected: the last line prints `$tip`. Rows stamped `unknown` do not count. No `|| echo` fallbacks: a command that cannot resolve its inputs fails the step.

- [ ] **Step 3: Run three rounds**

```bash
set -euo pipefail
d=docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix
py=$(git rev-parse --show-toplevel)/.venv/bin/python
for r in 1 2 3; do
  rm -f "$d/e2-cand-round$r.jsonl"
  { echo "== round $r"; uptime; vmstat 1 3; } >> "$d/e2-load.txt"
  "$py" /tmp/phase-e-gate2/scripts/audit.py --budget 30 --jobs 16 \
    --json "$d/e2-cand-round$r.jsonl" | tail -6
done
wc -l "$d"/e2-cand-round*.jsonl
```

Expected: 72 rows per file.

- [ ] **Step 4: Compare against Gate E1's candidate rounds**

```bash
d=docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix
for r in 1 2 3; do
  echo "== round $r"
  uv run python scripts/audit_compare.py "$d/e1-cand-round$r.jsonl" "$d/e2-cand-round$r.jsonl" \
    --noise-area 0.013 --p95-seconds 31 --expect-cells 72 --regressions-only \
    --require-clean freeform/universe-matrix/output-products \
    --require-clean freeform/universe-matrix/all-products \
    --require-clean sequence-pair/universe-matrix/output-products \
    --require-clean sequence-pair/universe-matrix/all-products
done
```

Expected, per round: no REGRESSION, INVALID or CRASH line; the four required cells CLEAN; area ratio at or under 1.0130; p95 at or under 31.0.

- [ ] **Step 5: Judge the clauses `audit_compare` does not carry**

Cells are joined on `(strategy, url_id, spec_label)` — the same key the gate clauses name and the same one Task 8 Step 5 uses.

```bash
uv run python - <<'EOF'
import json, math, pathlib
d = pathlib.Path("docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix")
CELL = ("universe-matrix", "no-proliferator")
KEYS = ("stages", "alns_operators", "alns_window_solves", "alns_window_accepted",
        "alns_window_dropped_empty", "alns_window_dropped_whole",
        "alns_window_unchanged", "evaluations", "distinct_assignments",
        "stale_draws", "stale_stop")
verdicts: dict[str, list[str]] = {"freeform": [], "sequence-pair": []}
for r in (1, 2, 3):
    e1 = {(x["strategy"], x["url_id"], x["spec_label"]): x
          for x in map(json.loads, (d / f"e1-cand-round{r}.jsonl").open())}
    rows = [json.loads(line) for line in (d / f"e2-cand-round{r}.jsonl").open()]
    secs = sorted(x["seconds"] for x in rows)
    p95 = secs[min(len(secs) - 1, math.ceil(0.95 * len(secs)) - 1)]
    print(f"round{r}: clean {sum(x['status'] == 'CLEAN' for x in rows)}/{len(rows)}  "
          f"p95 {p95:.2f}s  max {secs[-1]:.2f}s  "
          f"invalid {sum(x['status'] == 'INVALID' for x in rows)}  "
          f"crash {sum(x['status'] == 'CRASH' for x in rows)}")
    for strategy in ("freeform", "sequence-pair"):
        row = next(x for x in rows
                   if x["strategy"] == strategy and (x["url_id"], x["spec_label"]) == CELL)
        verdicts[strategy].append(row["status"])
        stats = row.get("stats", {})
        print(f"    {strategy} no-proliferator {row['status']} {row['seconds']:.1f}s "
              f"{ {k: stats.get(k) for k in KEYS} }")
        print(f"      detail: {row['detail'][:150]}")
    # Stage-cost clause: sequence-pair universe-matrix rows only.
    for row in rows:
        if row["strategy"] != "sequence-pair" or row["url_id"] != "universe-matrix":
            continue
        base = e1.get((row["strategy"], row["url_id"], row["spec_label"]), {})
        before = float(base.get("stats", {}).get("stages", 0.0))
        after = float(row.get("stats", {}).get("stages", 0.0))
        if before and after < 0.75 * before:
            print(f"    STAGE COST {row['spec_label']}: {before} -> {after}")
print("verdicts:", verdicts)
EOF
```

Expected:
- `invalid 0`, `crash 0`, p95 at or under 31.00, max at or under 35.00 in every round.
- No `STAGE COST` line (sequence-pair `stages` not more than 25% below E1's row for the same cell).
- On every sequence-pair `universe-matrix` row: `alns_operators` carrying `repair:local-exact-pack:N` with `N >= 1` **and** `destroy:failed-endpoints:M` with `M >= 1`, and `alns_window_solves >= 1`.
- On the freeform `no-proliferator` row: `distinct_assignments >= 2`, and either CLEAN or a refusal naming staleness or the deadline — **never** "PACKER defect".

- [ ] **Step 6: Record the verdict**

- **PASS** — `universe-matrix/no-proliferator` CLEAN under both strategies in all three rounds (72/72). Go to Step 7.
- **PARTIAL** — CLEAN under exactly one strategy in all three rounds. Record which, and why the other refuses, with the counters from Step 5. Skip Step 7; Task 14's status note carries spec §5.6's conditional levers and schedules the program's item 8 (the deterministic feasibility fallback) if sequence-pair is the one still refusing.
- **FAIL** — anything else. Record the counters and the `detail` strings and report before Task 14; do not tune a constant to reach a verdict.

- [ ] **Step 7: Gate E3, only if E2 passed at 72/72**

```bash
set -euo pipefail
d=docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix
py=$(git rev-parse --show-toplevel)/.venv/bin/python
for s in freeform sequence-pair; do
  for rep in $(seq 1 10); do
    rm -f "$d/e3-$s-rep$rep.jsonl"
    { echo "== E3 $s rep $rep"; uptime; vmstat 1 3; } >> "$d/e2-load.txt"
    "$py" /tmp/phase-e-gate2/scripts/audit.py --budget 30 --jobs 16 --strategy "$s" \
      --json "$d/e3-$s-rep$rep.jsonl" | tail -3
  done
done
uv run python -c "
import json, pathlib
d = pathlib.Path('docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix')
for s in ('freeform', 'sequence-pair'):
    counts = []
    for rep in range(1, 11):
        rows = [json.loads(l) for l in (d / f'e3-{s}-rep{rep}.jsonl').open()]
        counts.append(sum(r['status'] == 'CLEAN' for r in rows))
    print(s, counts, 'PASS' if all(c == 36 for c in counts) else 'FAIL')
"
```

Expected: `freeform [36]*10 PASS` and `sequence-pair [36]*10 PASS`. The full 720/720 production-concurrency gate and any default-budget change stay with the program's item 4 and are **not** part of this phase.

- [ ] **Step 8: Write `gate-e2.md` (and `gate-e3.md`)**

`gate-e2.md` contains, and nothing else: the tip hash and the `git rev-parse HEAD` line from Step 2; the three `audit_compare.py` blocks verbatim; the Step 5 output verbatim; a pointer to `e2-load.txt`; and one line per Gate E2 clause stating PASS, PARTIAL or FAIL:
1. `universe-matrix/no-proliferator` CLEAN under both strategies in every round (PASS) or under one (PARTIAL).
2. No regression against Gate E1's rounds; INVALID 0; CRASH 0; area within 0.013; p95 at most 31 s; max at most 35 s.
3. Sequence-pair `universe-matrix` rows carry `repair:local-exact-pack >= 1` paired with `destroy:failed-endpoints >= 1`, `alns_window_solves >= 1`, and `stages` not more than 25% below E1's row.
4. Freeform `no-proliferator` carries `distinct_assignments >= 2` and either CLEAN or a refusal naming staleness or the deadline, never "PACKER defect".

`gate-e3.md`, if it ran, contains the two ten-element count lists and the PASS/FAIL line.

- [ ] **Step 9: Commit**

```bash
git add docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix
git commit -m "bench: record gate E2 for the universe-matrix no-proliferator levers

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KufubYYxUsR9JHQo5xHPtv"
```

Use `bench: record a partial gate E2` or `bench: record a failed gate E2` for those verdicts, and report before Task 14.

---

### Task 14: Status notes, memory, and the final repository gate

Spec §8 item 9.

**Files:**
- Modify: `docs/superpowers/specs/2026-09-03-phase-e-universe-matrix-closure-design.md` (status header)
- Modify: `docs/superpowers/specs/2026-09-02-phase-c-alns-window-repair-design.md` (§5.7 status note)
- Modify: `docs/superpowers/specs/2026-09-02-phase-d-portfolio-racing-design.md` (lever 2 status note)
- Create: `/home/dannyb/.claude/projects/-home-dannyb-sources-factorio-lab-to-blueprint/memory/phase-e-universe-matrix-outcome.md`
- Modify: `/home/dannyb/.claude/projects/-home-dannyb-sources-factorio-lab-to-blueprint/memory/MEMORY.md`

**Interfaces:**
- Consumes: `gate-e1.md`, `gate-e2.md`, `gate-e3.md` (if it ran), and the branch's commit list.
- Produces: three status notes and one memory entry. No code changes.

- [ ] **Step 1: Run the final repository gate**

```bash
uv run python setup.py build_ext --inplace
uv run pytest -q; echo "pytest exit=$?"
uv run ruff check .
uv run mypy 2>&1 | tail -3
uv run python -m build 2>&1 | tail -5
( cd web && npm ci && npm run lint && npm run typecheck && npm test && npm run build ) 2>&1 | tail -8
```

Expected: `pytest exit=0`; ruff clean; mypy at exactly 184 with no new diagnostic; the package builds including the Cython sequence kernel; the frozen web install lints, typechecks, tests and builds. Resolve the web commands from `web/package.json` before running them; use the scripts it declares.

- [ ] **Step 2: Live CLI smoke on `universe-matrix`, both strategies**

```bash
url=$(uv run python -c "
from flab2bp.bench.corpus import URL_CORPUS
print(next(e.url for e in URL_CORPUS if e.url_id == 'universe-matrix'))
")
uv run python -m flab2bp --help | head -40
for s in freeform sequence-pair; do
  { uptime; } >> /tmp/phase-e-smoke-load.txt
  uv run python -m flab2bp "$url" --strategy "$s" --budget 30 > /tmp/phase-e-smoke-$s.txt 2>&1
  echo "$s exit=$? bytes=$(wc -c < /tmp/phase-e-smoke-$s.txt)"
done
```

Resolve the CLI's real flag names from the `--help` output before running the loop; the point is that the shipped entry point produces a blueprint or a refusal that names its mechanism, not a traceback. Record both outcomes in the status note.

- [ ] **Step 3: Write this spec's status header and the accepted deviations**

Add directly under the spec's `# Phase E: Universe-Matrix Closure` heading:

```markdown
**Status:** Executed 2026-09-03 on branch `phase-e-universe-matrix`. Tasks 1 to 14 landed with
review. Gate E1 <PASSED/FAILED> (<clean>/72 in three rounds, area ratio <r1>/<r2>/<r3>, p95
<p1>/<p2>/<p3> s); Gate E2 <PASSED/PARTIAL/FAILED>; Gate E3 <ran/not run>. The four cells section 5.1
targeted -- `universe-matrix/{output-products,all-products}` under both strategies -- are CLEAN.
`universe-matrix/no-proliferator` is <CLEAN under both / CLEAN under X, refusing under Y / refusing
under both>, with counters <...>. Line numbers in this document pre-date the branch; resolve symbols
with Serena.

**Delivery-order note.** Sections 5.4.1 and 5.4.2 shipped in the opposite order to section 8's list.
The diversification cut is unobservable while the arrangement gate still breaks the sweep at the
first `arrangement >= 1` slot with no incumbent, so the staleness-guarded continuation landed first
and the cut immediately after. Shipping the continuation alone for one commit is bounded by
`C_SWEEP_STALE_DRAWS` -- three duplicate draws at 0.06 to 0.09 s each -- and both landed before any
gate.
```

Fill every angle bracket from `gate-e1.md` and `gate-e2.md`. If Gate E2 was PARTIAL or FAILED, add a paragraph ranking what is left, taken from spec §5.6: the intra-arm no-good receiver first (a relation-exclusion collection in sequence-pair fed by the solver's own cluster no-goods across restarts, needing none of Ruling AN's cross-process identity vector), then warm-starting sequence-pair from the freeform placement through the race, then the program's item 8 — and state plainly that item 8 is now scheduled if `no-proliferator` still refuses under sequence-pair.

If Task 8's Step 7 reversion ran, add: `Section 5.2.1's witness change was reverted after Gate E1's area clause failed with it and passed without it; section 5.2.2's seed-gate narration shipped regardless.` with both area ratios.

**The spec body is already amended.** Six deviations were folded into it when this plan's fix round landed, and they are the `git diff` on the spec that the branch inherits. This step does **not** re-apply them; it VERIFIES that each is still present and still agrees with what actually shipped, then adds the status header and the delivery-order note above. If any of the six no longer matches the code — for instance because Gate E1's reversion rule removed §5.2.1's witness change — correct that one and say which in the commit message.

The six to verify, and what each must say:

1. **§5.3.2 and §6** — the stats mapping is typed `Mapping[str, float | str]` and `Result.stats: dict[str, float | str]`, because `alns_operators` is a tally STRING (`operator_tally` returns `str`, `PlacementStats` types it `str`) and Gate E2 asserts on it; "keys absent on a row are read as zero" carries "…or as the empty string for `alns_operators`"; and §5.3.2 says `run_cell` has **two** REFUSED returns, the second being the `finalize.ProjectionRefusal` handler.
2. **§5.5.1** — the probe walks the product DESTROY-MAJOR with the repair order as declared, so draw 0 stays master's `(FAILED_ENDPOINTS, SEQUENCE_REINSERT)` and draw 1 is `(FAILED_ENDPOINTS, LOCAL_EXACT_PACK)`, and §5.5's test list reads "the first draw that names `LOCAL_EXACT_PACK` is paired with `FAILED_ENDPOINTS`". Confirm the sentence recording that keeping draw 0 identical to master leaves six sequence-solver behaviour tests untouched that a reversed repair axis moved.
3. **§5.1** — the "Docstring correction" names "`_reserve_port_access`'s docstring (the `twice` paragraph), plus the `shared_feed` comment in `_prepare_routing_problem.hold_ports`", rather than the original `freeform.py:14188-14196` hint, which is a comment and not the docstring.
4. **§5.4.1** — the cut is "kept in a per-candidate `(height, arrangement)` collection BESIDE `_ExactPackNoGoodState`, never inside it", with the reason (that class is sweep-wide by construction and its entries are infeasibility proofs, which a diversification cut is not).
5. **§5.4.3** — the window is "posed against the failing nets' strips of the best-failing pack the sweep has seen SO FAR, implemented as a launch guard", with the strict-comparison rule and its ~1 s-per-solve reason.
6. **§5.2.3** — both deviations are stated: the schedule offers no height above the boundary core **whenever a distinct approach slot is free** (a duplicate would make `SequenceSolver.__init__` raise and a drop would break `_production_run`'s index re-split), and the bounding applies to the WHOLE schedule rather than only to the deadline-continuation restarts, with the compact-seed height bounded at its own site.

- [ ] **Step 4: Record the change to Phase C's §5.7**

Append to the Phase C spec's §5.7:

```markdown
**Status note (Phase E, 2026-09-03).** The trigger described here never fired on a refusing cell.
`promote_retry` required `arrangement == 0 and (learned or feedback_retry)`, and both disjuncts are
false whenever a preparation failure forces `routing.exhaustive` false: `_proof_scoped_no_goods`
returns nothing, and `_feedback_retry_eligible` demanded EXACTLY ONE routing failure against the 3
and 6 the `universe-matrix` cells carry (R2 section 4, measured at `e0bf432`). Affordability was
never the blocker -- `room=True` on every turn, window cost 1.00 to 2.37 s against 25+ s remaining.
Phase E section 5.4.3 drops both conjuncts: `_feedback_retry_eligible` now admits ANY routing failure
the feedback state can weight and whose endpoints it knows, and the window launches on
`retry_slot_found and not retry_admitted` alone, guarded so it is posed only against a pack that
strictly beats the fewest unrouted nets the sweep has seen. The affordability check is unchanged.
Gate E2's numbers are in
`docs/superpowers/evidence/2026-09-03-phase-e-universe-matrix/gate-e2.md`.
```

- [ ] **Step 5: Record the change to Phase D's lever 2**

Append to the Phase D spec beside its ranked lever 2:

```markdown
**Status note (Phase E, 2026-09-03).** Lever 2 -- "put the counters on `audit.Result` so a gate can
see sharing" -- shipped as Phase E section 5.3.2. `NoValidLayout` gained an optional `stats` mapping,
filled at freeform's three post-sweep raises and at `SequencePairLayout.lay_out`'s re-raise, and
`audit.Result.stats` carries it onto all three of `run_cell`'s REFUSED returns as well as the CLEAN
and INVALID ones; rows without it read as empty. Before this, every `alns_*` stat was written in
`_with_observational_stats`, which runs only on a successful placement, so a REFUSED row carried no
stats at all (R3 section 5.3, measured). Two paths are deliberately NOT covered and are the remaining
gap: `pipeline.py` constructs and raises its own `NoValidLayout`, and `strategy_race.py` re-raises
for the racing path, so the CLI and web surfaces carry no `stats`. The audit gate is unaffected --
it calls `strategy.lay_out` directly and flattens the exception inside the worker, so nothing about
it is pickled. Ruling AN is untouched: no cross-process no-good identity vector was added.
```

- [ ] **Step 6: Write the memory entry**

Create `phase-e-universe-matrix-outcome.md` in the memory directory with: the branch and merge commit; each gate's verdict and its headline numbers; the mechanism sentence ("`universe-matrix` is the only corpus spec where `hydrogen` is both an external input and internally produced, which raised the middle lane head's corridor demand from 1 to 2"); what stayed corpus-inert; the six spec amendments; and the ranked levers left. Then add one line to `MEMORY.md` in the existing style:

```markdown
- [Phase E universe-matrix closure](phase-e-universe-matrix-outcome.md) — executed 2026-09-03; seating rule took the gate 66/72 to 70/72 with zero regressions; E1 <verdict>, E2 <verdict>; `no-proliferator` <state>; product probe and refused-row stats shipped
```

- [ ] **Step 7: Whole-branch review, then commit and merge**

```bash
git log --oneline origin/master..HEAD
git diff --no-ext-diff origin/master...HEAD --stat
```

Request a read-only whole-branch review from an opus reviewer working from an archived commit, then:

```bash
git add docs/superpowers/specs/2026-09-03-phase-e-universe-matrix-closure-design.md \
  docs/superpowers/specs/2026-09-02-phase-c-alns-window-repair-design.md \
  docs/superpowers/specs/2026-09-02-phase-d-portfolio-racing-design.md
git commit -m "docs(spec): record the phase E gates and the deviations it accepted

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KufubYYxUsR9JHQo5xHPtv"
git checkout master
git merge --ff-only phase-e-universe-matrix
```

The memory files live outside the repository and are not committed. If the merge is not a fast-forward, stop and report; never rebase or reset this branch.

---

## Self-review record

Run after the fix round; findings were fixed inline.

**Spec coverage.** §5.1 → Task 2 (including the surgical/broad mutant guard on `quantum-chip`, spec test 4). §5.2.1 → Task 5, with §7's reversion rule as Task 8 Step 7. §5.2.2 → Task 3. §5.2.3 → Task 6, with its two deviations declared in-task and amended into the spec by Task 14 Step 3 item 6. §5.3.1 → Task 4, wired into BOTH the deadline branch and the final raise. §5.3.2 → Task 7 (all three `run_cell` REFUSED returns) with the three window-drop keys completed in Task 9. §5.4.1 → Task 11. §5.4.2 → Task 10. §5.4.3 → Task 12. §5.5.1 and §5.5.2 → Task 9. §5.6 → not a deliverable; Task 14 Step 3 records the conditional levers. §6 public interfaces → Tasks 6, 7, 9, 10. §7 Gate E1 → Task 8; Gates E2 and E3 → Task 13; final repository gate → Task 14 Steps 1 and 2. §8 delivery order → Tasks 1 to 14, with the single declared inversion of §5.4.1/§5.4.2. §9 risks → Task 2 Step 4 (the margin-row coupling, written into `strip_variants.py`) and its invariant test (a both-fed item seated below), Task 4 (three both-fed ingredients named by the refusal), Task 10 Step 8 and Task 12 Step 6 (area churn, the racing hazard, the widened trigger), Task 9 Steps 8 and 9 and Task 13 Step 5 (probe stage cost), Tasks 8 and 13 (three-round agreement against 12% per-cell noise).

**Fix-round-2 re-review (Tasks 2, 5, 9 and 14 only).** Coverage: unchanged — no task gained or lost a spec section. Task 9 Step 2 now drives `_call_alns(session=..., adapters=...)`, whose four-value fixture and internally built `metrics` were read with `find_symbol(include_body=True)`, so the block no longer unpacks a five-tuple or names a `metrics` the fixture does not return; the whole-problem drop path was executed on master and produced `neighbourhood == {0, 1, 2, 3}` of `problem.size == 4`, `window_pack` uncalled and `session.applied == 0`, which is exactly what the test asserts. Task 9 Step 1's balance test became `test_the_probe_walks_the_product_destroy_major`, asserting the destroy SEQUENCE (`[FE, FE, BB, BB]`) that is red on master (`[FE, BB, FE, BB]`, measured) and keeping the two count assertions as the invariant they always were; Step 3's red/green split is now two explicit lists and names five tests as green-on-master guards. Task 9's `replace` is declared as a MISSING import to add rather than as a name to resolve. Task 2's mutant-guard docstring now names both mutants correctly — widening the key is the broad rule this test catches, dropping the `not in both_fed` term is plain alphabetical order and is caught by the `hydrogen` test. Task 5 Step 5 was widened from one cell to the full 72, matching Task 6, because the `max(...)` witness raises the filter on every freeform cell. Task 7 Step 7 and spec §5.3.2 now say `run_cell` has TWO REFUSED returns and drop the `grep -c '"REFUSED"'` check, whose third hit is in `record`. Task 14 Step 3 verifies the six spec amendments instead of re-applying them, and adds only the status header and the delivery-order note.

**Placeholder scan.** No "TBD", no "similar to Task N", no "add appropriate …". Nine steps instruct the executor to resolve a local or fixture name with Serena before writing an edit (`_reserve_port_access`'s `options` local, `Strip.sid`, the `sequence_solver_module` alias, `_pack_window`'s call shape, `_band_boundary` / `_problem`, `_production_run`'s envelope perimeter, `NetFailure` / `NetRole`, `math`'s import, the `web/package.json` scripts and the CLI's flags); each names what the value must be and what to do if it is not there, which is a verification instruction rather than a gap. Five traps are now stated as measured FACTS rather than left to resolution: `_routing_failures()` with no kinds is ROUTED; `_routed` has to be written; `_substitution_fixture()` returns four values and no `metrics`, so `_call_alns` is what the drop-path test uses; `replace` is missing from `test_sequence_alns.py`'s imports; and `run_cell` has two REFUSED returns, not three.

**Type consistency across the renumbered tasks.** `NoValidLayout.stats`, `Result.stats`, `_refusal_stats` and `_sweep`'s `telemetry` are all `dict[str, float | str]`, declared once in Task 7 and amended into the spec by Task 14. `StrandedPort` is defined in Task 4 and read only there. `_ceiling_bounded_schedule(ordered, *, boundary, reserved=frozenset())` and `_seat_both_fed_outermost(in_above, in_below, both_fed)` are each defined once and used only by their own task and tests. `C_SWEEP_STALE_DRAWS` (Task 10) and `C_CEILING_APPROACH_STEP` (Task 6) are each defined once. `stale_draws` and `stale_stop` are introduced in Task 7 (as published zeros), made to move in Task 10, and read in Task 13's gate script. The three `alns_window_dropped_*` / `alns_window_unchanged` fields are added in Task 9 and Task 7 explicitly does not reference them; Task 9 Step 5 is the step that adds them to `_refusal_stats`. `_routed()` and `_lay_out_with_injected_packs(...)` are created in Task 10 Step 1 and reused in Task 11.
