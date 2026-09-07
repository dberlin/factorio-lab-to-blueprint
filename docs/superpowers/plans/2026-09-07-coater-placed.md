# Ship the PLACED Spray Coater node as the production coater model

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the separately placed Spray Coater node (`FLAB2BP_COATER_NODE=placed`) the
default and only production coater model for both placers, delete the `seat`, `packed` and
`packed-hpwl` experiment arms, retire the strip-channel machinery the node makes unreachable,
and prove by gate that the reported coater-over-a-merge defect is gone at no cost in coverage.

**Architecture:** A sprayed input lane stops being a widened strip channel with an addon
decorating its interior. Instead `_prepare_routing_problem` emits one free-standing four-tile
belt run per sprayed input lane — the node — sited by a post-pack Chebyshev ring search on free
ground beside the consumer lane head, with the addon riding its third tile. Every producer net
and external run that used to sink into the consumer lane head now sinks into the node's
in-port; one new net carries the node's out-port to the consumer lane head, which reverts to an
ordinary `WEST_CHANNEL = 1` lane. The packer is untouched: only the router sees the extra net.
Because the merge cell is the node's in-port one tile west of the body **by construction**, the
"coater rides a belt merge" defect becomes structurally impossible rather than checked, and
`prolif.coater_rides_one_run` becomes a regression test rather than the fix.

**Tech Stack:** Python 3.13, `uv`, pytest, OR-Tools CP-SAT, ruff, mypy. Web viewer: TypeScript,
rsbuild, rstest (`web/`).

**Spec:** `docs/superpowers/specs/2026-09-07-coater-node-design.md` — **read its status note
first: its recommendation (variant A, the seat fix) is SUPERSEDED.** The binding authority for
this plan is the measurement that superseded it:
`docs/superpowers/evidence/2026-09-07-exp-coater-node/README.md` (especially §1 "the node,
exactly", §5 learnings, §7 recommendation). Where the design and the experiment disagree, the
experiment wins; where the experiment is silent, the design's §4 migration table and §5.4
over-proliferation reasoning still apply.

---

## Global Constraints

Copy these into every task dispatch. They bind every task.

- **Branch/worktree.** All work happens on branch `coater-placed` in the worktree
  `.claude/worktrees/coater-placed`, cut from `master@ffc5e88b`. Never merge, never push,
  never delete the branch.
- **Environment check before any test result counts.** Run `uv sync` in the worktree, then
  `uv run python -c "import flab2bp; print(flab2bp.__file__)"` and confirm the printed path is
  inside `.claude/worktrees/coater-placed`. A test result from the wrong tree is not evidence.
- **Never a git command that opens an editor.** Use `-m` / `--no-edit`, and `GIT_EDITOR=true`
  where a command might still try.
- **Never `ps | grep`.** Use `pgrep -f` with an interpreter-anchored pattern, e.g.
  `pgrep -f 'python.*audit\.py'`.
- **Never `uptime` / load average for CPU pressure.** This box has 128 cores and its load is
  disk I/O wait, not CPU. Measure only as
  `vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print sum/5}'` (five-second mean of runnable
  processes). Under 64 is not busy.
- **ONE build at a time.** Other agents build on this box. Never run two `audit.py`,
  `probe_cell.py` or corpus builds concurrently, and never raise `--jobs` above what the task
  text says.
- **Serena is for READING only.** The Serena MCP server is shared across worktrees and its
  last `activate_project` wins, so a Serena write from here can land in another agent's
  worktree. Use `Read`/`Edit`/`Write` and the LSP tools for every modification.
- **The user's standing rulings outrank density arguments.** (1) No mixed-item input lanes.
  (2) A coater rides exactly one belt run. (3) Density may be paid for correctness.
  (4) Over-proliferation is acceptable — "over-proliferating is fine if it makes life easier".
  If a review finding argues for area against any of these, the ruling wins.
- **`off` stays reachable for one release.** `FLAB2BP_COATER_NODE=off` must continue to
  reproduce today's master behaviour exactly, as the A/B control. Every guard that today reads
  `coater_mode().is_node` keeps reading it. Deleting a guard is only allowed where the code it
  guards is deleted for BOTH arms.
- **Env-var contract after Task 1.** Unset, empty, or unrecognised → `PLACED`. The single
  string `"off"` → `OFF`. The single string `"placed"` → `PLACED`. `"seat"`, `"packed"`,
  `"packed-hpwl"` are no longer values and fall through to `PLACED` like any other unknown
  string.
- **Evidence size is never a concern.** Anything under gigabytes is fine. Never shrink or omit
  committed evidence to save space.
- **Test-quirk facts for this repo.** The pytest summary line does not print here — use the
  exit code. A 120 s `pytest-timeout` backstop hard-kills long runs; scope test commands to
  files or node ids. `scripts/audit.py` prints `NOT CLEAN` on any refusal, so compare CELL
  COUNTS and NAMED CELLS via `scripts/audit_compare.py`, never the headline verdict.
- **Commit style.** Frequent, small, imperative-subject commits. Each commit's tests pass.

---

## What is already true on `master@ffc5e88b` (do not re-derive)

The `exp-coater-node` branch is merged. All four arms exist behind `FLAB2BP_COATER_NODE`,
default `off`. Facts the tasks below rely on, each verified against master:

| Fact | Where |
|---|---|
| The mode switch and its four arms | `src/flab2bp/layout/coater_mode.py:54-97` |
| `_COATER_WEST_CHANNEL = 3` | `src/flab2bp/layout/freeform.py:211-213` |
| `Strip.coater_node` field (packed arms only) | `freeform.py:958-966` |
| `coater_node` listed in `_UNREAD_BY_STAGED_CLEARANCE` | `freeform.py:1318` |
| `coater_node` listed in the two direct-geometry field sets | `freeform.py:3044`, `freeform.py:3275` |
| `_staged_static_clearance_keys` returns empty under a node arm | `freeform.py:1348-1351` |
| `needs_coater_keepout` is false under a node arm, so the strip pays `WEST_CHANNEL` | `freeform.py:2559-2562`, `freeform.py:2652` |
| `_packed_coater_node_strips` (packed arms only) | `freeform.py:2734-2800` |
| `_nets_between`'s node-wirelength block (`packed-hpwl` only) | `freeform.py:4021-4027` |
| `_coater_keepout_hits` | `freeform.py:5333` |
| The prepended-head / two-tile floor, skipped under a node arm | `freeform.py:6667` |
| `_Unseatable` | `freeform.py:13855` |
| `_projected_coater_junction_bans_by_frame` | `freeform.py:14821` |
| `packed_node_sites` and the `_emit_strip` bypass | `freeform.py:16539-16547` |
| Node emission, in-port rewiring, `_Unseatable` sites | `freeform.py:16605-16673` |
| The node's out-net, appended after `_join_shard_islands` | `freeform.py:16860-16875` |
| `_COATER_NODE_TILES = 4` and `_emit_coater_node` | `freeform.py:18335-18398` |
| `_coater_node_site_is_clear` (the 6x3 ring) | `freeform.py:18401-18434` |
| `_coater_node_site` (the ring search) | `freeform.py:18437-18479` |
| `_coater_body_half_span` | `freeform.py:18482-18491` |
| `_coater_seats`, with the `narrow_seats` start index | `freeform.py:18494-18523` |
| `_coater_seat` — **no production caller anywhere** | `freeform.py:18526-18583` |
| `_reserve_staged_coater_belt_ban`, with the `narrow_seats` ban block | `freeform.py:18586-18637` |
| `_place_coaters`, and its `seat_channel = len(port.tiles) - 1` node branch | `freeform.py:18640`, `freeform.py:18749` |
| The `_Unseatable` height discard in the freeform sweep | `freeform.py:21595-21612` |
| `_candidate_height_box`'s `_COATER_WEST_CHANNEL` subtraction | `freeform.py:22693-22699` |
| Sequence-pair reaches the SAME `_prepare_routing_problem` | `sequence_solver.py:74`, `sequence_solver.py:5366` |
| **Sequence-pair lifts a sprayed strip's `west_channel` to `_COATER_WEST_CHANNEL + 1` — unguarded by `coater_mode()`** | `sequence_solver.py:3744-3758` |
| **`_selected_strips` lifts it to `_COATER_WEST_CHANNEL` (or +1) — also unguarded** | `sequence_solver.py:3851-3877` |
| `prolif.coaters_are_supplied` | `validate.py:4832` |
| `prolif.sprayed_cargo_reaches_machines`, and its `forbids_spray` ERROR clause | `validate.py:5011`, `validate.py:5066`, `validate.py:5088-5099` |
| `game.addon_supply` | `validate.py:2188` |
| Run-level sourcedness closure, reusable | `validate.py:_internal_seeds`, `validate.py:_close_over_junctions`, used at `validate.py:4177-4183` |
| `prolif.coater_rides_one_run` **is NOT on master** — it lives unmerged on branch `selfloop` | `.claude/worktrees/selfloop/src/flab2bp/layout/validate.py:4997-5085` |
| Web belt-run/endpoint inference | `web/src/model/beltGraph.ts:83-110` |
| Experiment tests (all four arms) | `tests/layout/test_coater_node_experiment.py` (419 lines) |

**Verified for this plan and not stated in the experiment README:** the README says `placed`
"reaches sequence-pair untouched", and that is true of *correctness* — it is the same shared
`_prepare_routing_problem`. It is **not** true of cost. `sequence_solver._sequence_reservation_strips`
and `_selected_strips` re-lift every `REQUIRES_SPRAY` strip's `west_channel` to 4 and then 3,
with no `coater_mode()` guard, so on the sequence-pair arm a sprayed strip still pays a
three-wide channel for an addon that no longer rides it. Freeform does not: its own lift at
`freeform.py:2715-2733` maxes over `_staged_static_clearance_keys`, which returns empty under a
node arm, so it defaults to the strip's own (narrow) channel. **Task 2 retires the sequence-pair
lifts.** This is a real deviation from what the experiment measured — the `placed` numbers in
the README were taken WITH those lifts in place — so the gate in Task 7 is the arbiter and its
area budget is stated against master's merge base, not against the experiment's `placed` column.

---

## File Structure

| File | Responsibility after this plan |
|---|---|
| `src/flab2bp/layout/coater_mode.py` | Two modes: `PLACED` (default) and `OFF` (the one-release A/B control). One property, `is_node`. No experiment prose. |
| `src/flab2bp/layout/freeform.py` | Node emission, ring search, seat search, keepout, staged-static and supply certification. Loses `Strip.coater_node`, `_packed_coater_node_strips`, `packed_node_sites`, the `_nets_between` node-wirelength block, `_coater_seat`, and the `narrow_seats` property's call sites. |
| `src/flab2bp/layout/sequence_solver.py` | Loses the two unguarded `_COATER_WEST_CHANNEL` lifts under `placed`; keeps them under `off`. |
| `src/flab2bp/layout/validate.py` | Gains `prolif.coater_rides_one_run` (ported verbatim in meaning from `selfloop`) and `prolif.coater_supply_is_fed`. `forbids_spray` half of `prolif.sprayed_cargo_reaches_machines` drops to WARNING. |
| `tests/layout/test_coater_node.py` | Renamed from `test_coater_node_experiment.py`. Two arms, not four. Structural tests for the node. |
| `tests/layout/test_validate.py` (or the existing prolif test module) | The two new checks. |
| `tests/layout/test_sequence_solver.py` | Sequence-pair parity: a sprayed spec through `SequencePairLayout` produces the node. |
| `web/tests/model/beltGraph.test.ts` | Node run decode/endpoint-icon assertions, only if Task 6 measures a defect. |
| `docs/superpowers/evidence/2026-09-07-coater-placed-gate/` | New. Gate runners, JSONL, logs, `README.md` with the measured table. |
| `docs/superpowers/specs/2026-09-07-coater-node-design.md` | Gains a status note (already written in the plan commit) saying it is superseded. |

---

## Pre-flight for the executing controller

Before Task 1:

```bash
cd /home/dannyb/sources/factorio-lab-to-blueprint
git worktree add -b coater-placed .claude/worktrees/coater-placed master
cd .claude/worktrees/coater-placed
uv sync
uv run python -c "import flab2bp; print(flab2bp.__file__)"   # must print a path inside this worktree
```

Record `git rev-parse HEAD` as the branch merge base — Task 7's gate and the final review
package both need it.

---

## Task 1: Promote `placed` to the default; delete `seat`, `packed` and `packed-hpwl`

**Files:**
- Modify: `src/flab2bp/layout/coater_mode.py` (whole file)
- Modify: `src/flab2bp/layout/freeform.py:958-966`, `:1318`, `:2734-2800`, `:3040-3046`,
  `:3270-3278`, `:4021-4027`, `:16539-16547`, `:16633-16643`, `:18520`, `:18597`
- Rename + rewrite: `tests/layout/test_coater_node_experiment.py` →
  `tests/layout/test_coater_node.py`
- Check for fallout: `tests/layout/test_freeform.py`, `tests/layout/test_finalize.py`,
  `tests/layout/test_sequence_solver.py`, `scripts/route_profile.py`

**Interfaces:**
- Produces: `CoaterMode.PLACED`, `CoaterMode.OFF`, `coater_mode() -> CoaterMode`,
  `CoaterMode.is_node: bool`. Every later task reads `coater_mode().is_node`.
- Produces: `Strip` no longer has a `coater_node` field. Task 2 and Task 4 rely on that.

- [ ] **Step 1: Write the failing tests** in `tests/layout/test_coater_node.py`

```python
def test_the_default_arm_is_placed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FLAB2BP_COATER_NODE", raising=False)
    assert coater_mode() is CoaterMode.PLACED
    assert coater_mode().is_node


@pytest.mark.parametrize("raw", ["", "  ", "seat", "packed", "packed-hpwl", "nonsense"])
def test_a_retired_or_unknown_arm_falls_back_to_placed(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    """The three retired arms are not values any more, and must not be `off`.

    Falling back to `off` would silently reinstate the defect on any stale
    harness that still exports `FLAB2BP_COATER_NODE=seat`.
    """
    monkeypatch.setenv("FLAB2BP_COATER_NODE", raw)
    assert coater_mode() is CoaterMode.PLACED


def test_off_is_still_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLAB2BP_COATER_NODE", "off")
    assert coater_mode() is CoaterMode.OFF
    assert not coater_mode().is_node


def test_strip_has_no_coater_node_field() -> None:
    """The packed arms are gone, so no Strip is a rectangle of belt."""
    assert not hasattr(Strip(...minimal...), "coater_node")
```

- [ ] **Step 2: Run them and watch them fail**

`uv run pytest tests/layout/test_coater_node.py -x -q`
Expected: FAIL — `CoaterMode.PLACED` is not the default, `Strip` still has `coater_node`.

- [ ] **Step 3: Rewrite `coater_mode.py`**

Replace the whole module. It is no longer an experiment switch; it is a one-release A/B
control. Keep the docstring short and factual — the evidence lives in the README, not here.

```python
"""How a Spray Coater is placed.

``placed`` -- the default and the production model.  One free-standing
four-tile belt run per sprayed input lane, sited after the pack on free ground
beside the consumer lane head, with the addon riding its third tile.  Every
producer net and external run sinks into the node's IN-PORT, one tile west of
the body, so a many-to-one merge lands off the body BY CONSTRUCTION.

``off`` -- master's behaviour before 2026-09-07, retained for one release as
the A/B control.  The addon rides the interior of the consumer strip's own
widened ``_COATER_WEST_CHANNEL`` channel and its 3x1 body may cover the lane
head, which is the reported defect: five and nine coater bodies over a belt
merge on the 72-cell corpus, six on the reported URL.

Measured, both arms, ``--budget 30``, two rounds, 72 cells
(``docs/superpowers/evidence/2026-09-07-exp-coater-node/README.md``):
``placed`` is 72/72 CLEAN with zero coater-merge findings against ``off``'s
71-72/72 with five and nine, at +2.7-2.9% area and +1.4% belt tiles.  Density
may be paid for correctness.

The mode is read from ``FLAB2BP_COATER_NODE`` so a subprocess-per-cell harness
(``scripts/audit.py``, the CLI) can select the control arm without threading a
keyword through every strategy entry point.  Anything but the exact string
``off`` selects ``placed``, including the three retired experiment arms
(``seat``, ``packed``, ``packed-hpwl``), so a stale harness cannot silently
reinstate the defect.
"""

from __future__ import annotations

import os
from enum import StrEnum

__all__ = ["CoaterMode", "coater_mode", "ENV_VAR"]

ENV_VAR = "FLAB2BP_COATER_NODE"


class CoaterMode(StrEnum):
    OFF = "off"
    PLACED = "placed"

    @property
    def is_node(self) -> bool:
        """Does this arm build a free-standing coater node?"""
        return self is CoaterMode.PLACED


def coater_mode() -> CoaterMode:
    """The arm this process runs.  ``placed`` unless the switch says ``off``."""
    raw = os.environ.get(ENV_VAR, "").strip().lower()
    return CoaterMode.OFF if raw == CoaterMode.OFF.value else CoaterMode.PLACED
```

- [ ] **Step 4: Delete the packed-arm machinery in `freeform.py`**

Delete, in this order, running `uv run pytest tests/layout/test_coater_node.py -x -q` after
each deletion so a broken step is attributable:

1. `_packed_coater_node_strips` (`:2739-2800`) and its call site (`:2734-2735`, the
   `if coater_mode().packs_nodes:` block). `_plan_strips` returns `piled` directly.
2. The `_nets_between` node-wirelength block (`:4021-4027`) and the `packed-hpwl` paragraphs
   of that docstring (`:3993-4011`). Keep the docstring's first line and the ordinary
   `out_lanes` derivation.
3. `Strip.coater_node` (`:958-966`) and its three field-set entries with their EXPERIMENT
   comments: `_UNREAD_BY_STAGED_CLEARANCE` (`:1316-1319`), `_UNREAD_BY_DIRECT_GEOMETRY`
   (`:3042-3045`), and the second direct-geometry set (`:3273-3277`).
4. `packed_node_sites` (`:16539`), the `if s.coater_node is not None:` bypass in the emit
   loop (`:16540-16547`), and — in the node-emission block — the
   `site = packed_node_sites.get(...)` lookup plus the "the packed … node at … is not clear"
   `_Unseatable` (`:16636-16643`). What remains is unconditional:
   `site = _coater_node_site(canvas, (consumer_port.x, consumer_port.y))`, then the
   "no free ground" `_Unseatable` when it is `None`.

**There is very likely a test asserting that the two direct-geometry field sets, plus the
fields the geometry actually reads, exhaust `Strip`'s field names.** Find it before you start
(`grep -rn "_UNREAD_BY_DIRECT_GEOMETRY\|_UNREAD_BY_STAGED_CLEARANCE" tests/`) and update it in
the same commit; a stale exhaustiveness set is how a deleted field turns into a silent read.

- [ ] **Step 5: Collapse the two dead properties**

`CoaterMode.narrow_seats` was "every arm but `off`", which after the deletions is exactly
`is_node`. Replace its two call sites — `_coater_seats` (`:18520`) and
`_reserve_staged_coater_belt_ban` (`:18597`) — with `coater_mode().is_node`, and delete the
property along with `packs_nodes` and `node_wirelength`. Do **not** change what those two
blocks do in this task; Task 3 decides their fate on evidence.

- [ ] **Step 6: Rewrite the test module**

`git mv tests/layout/test_coater_node_experiment.py tests/layout/test_coater_node.py`, then:

- **Delete** every test that only exists to characterise a retired arm:
  `test_packed_gives_the_packer_one_rectangle_per_sprayed_lane`,
  `test_off_plans_no_coater_node_strips`,
  `test_only_packed_hpwl_puts_the_node_out_net_in_the_pack_objective`,
  `test_seat_bans_the_body_level_and_the_area_one_rival` (its `seat`-only half; see below).
- **Keep and de-parametrise** to `off` / `placed`:
  `test_half_span_is_derived_per_yaw_not_assumed_to_be_one`,
  `test_off_offers_a_seat_whose_body_covers_the_lane_head`,
  `test_a_narrowed_seat_never_covers_its_own_in_port`,
  `test_off_and_seat_buy_the_wide_channel_and_the_node_arms_do_not` (rename to
  `test_off_buys_the_wide_channel_and_placed_does_not`),
  `test_a_node_arm_emits_a_four_tile_run_with_the_addon_on_its_third_tile`,
  `test_no_coater_body_covers_a_belt_merge`,
  `test_a_node_arm_leaves_the_consumer_lane_ordinary`.
- Any parametrisation over `["off", "seat", "packed", "packed-hpwl", "placed"]` becomes
  `["off", "placed"]`.
- The module docstring stops calling itself an experiment and points at the evidence README.

**Deleting a test is only correct when the behaviour it covered is deleted.** A test that
covered `placed` through an arm-parametrised loop must survive as a `placed` test, not vanish
with the loop.

- [ ] **Step 7: Sweep the rest of the tree**

`grep -rn "seat\b.*COATER_NODE\|packed-hpwl\|packs_nodes\|node_wirelength\|narrow_seats\|coater_node" --include='*.py' src/ tests/ scripts/`
must return nothing outside `docs/`. Check `scripts/route_profile.py` (two references) and
`tests/layout/test_finalize.py`, `tests/layout/test_freeform.py`,
`tests/layout/test_sequence_solver.py`, `tests/test_pipeline.py`,
`tests/layout/hierarchy/test_compose.py` for arm strings.

- [ ] **Step 8: Verify**

```
uv run pytest tests/layout/test_coater_node.py -q
uv run pytest tests/layout/test_freeform.py -q -x
uv run pytest tests/layout/test_finalize.py tests/layout/test_sequence_solver.py -q
uv run ruff check . && uv run ruff format --check . && uv run mypy src
```
Scope pytest to files, not the whole suite: the 120 s `pytest-timeout` backstop hard-kills a
long run and the summary line does not print here, so read the exit code.

- [ ] **Step 9: Commit** — `layout: make the placed coater node the default arm`

---

## Task 2: Retire what the node makes dead; keep and justify what still fires

**Files:**
- Modify: `src/flab2bp/layout/sequence_solver.py:3744-3758`, `:3851-3877`
- Modify: `src/flab2bp/layout/freeform.py:18526-18583` (delete `_coater_seat`),
  `:18586-18637` (the ban block), `:18664-18670` (a docstring cross-reference)
- Test: `tests/layout/test_coater_node.py`, `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: `coater_mode().is_node` from Task 1.
- Produces: under `placed`, a `REQUIRES_SPRAY` strip has `west_channel == WEST_CHANNEL` on
  BOTH placers. Task 7's area numbers depend on this.

**The rule for this task.** A mechanism is retired only when a test proves it cannot fire
under `placed`. A mechanism that still fires is KEPT, and the task's report says in one
sentence why. Do not delete on the strength of an argument.

### 2a. The sequence-pair west-channel lifts — RETIRE

Freeform already stops paying `_COATER_WEST_CHANNEL` for a node arm, and sequence-pair does
not: `_sequence_reservation_strips` lifts every sprayed strip to `_COATER_WEST_CHANNEL + 1`
and `_selected_strips` lifts it to `_COATER_WEST_CHANNEL`, neither guarded. Under `placed`
nothing rides that channel, so the strip is paying two extra columns per sprayed strip for a
reservation against an addon that is somewhere else entirely.

- [ ] **Step 1: Write the failing test** in `tests/layout/test_sequence_solver.py`

```python
def test_placed_stops_the_sequence_pair_sprayed_channel_lift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sprayed strip pays WEST_CHANNEL under `placed`, W3/W4 under `off`.

    The lift reserves room for a 3x1 addon riding the strip's own channel.
    Under `placed` the addon is on its own four-tile run, so the reservation
    buys nothing and costs two columns per sprayed strip.
    """
    strips = _sprayed_strips_for(proliferated_spec())   # existing helper
    monkeypatch.setenv("FLAB2BP_COATER_NODE", "off")
    assert {s.west_channel for s in _sequence_reservation_strips(strips)} == {
        _COATER_WEST_CHANNEL + 1
    }
    monkeypatch.setenv("FLAB2BP_COATER_NODE", "placed")
    assert {s.west_channel for s in _sequence_reservation_strips(strips)} == {WEST_CHANNEL}
```

Add the mirror assertion for `_selected_strips`, driving it through whichever entry point the
existing tests in that file already use so you do not have to fabricate a `StripVariant`.

- [ ] **Step 2: Run it and watch it fail** —
  `uv run pytest tests/layout/test_sequence_solver.py -k channel_lift -q`

- [ ] **Step 3: Guard both lifts**

In `_sequence_reservation_strips`, return `list(strips)` unchanged when
`coater_mode().is_node`, and say why in the docstring: the W4 reservation exists so a later
exact pose swap cannot outgrow its proxy box *for an addon on the strip's channel*, and under
`placed` there is no such addon. In `_selected_strips`, make the whole
`if strip.cargo_domain is CargoDomain.REQUIRES_SPRAY:` re-lift block conditional on
`not coater_mode().is_node`, and make the `west_channel=` argument in the constructed
`selected_strip` read `WEST_CHANNEL` under a node arm.

- [ ] **Step 4: Run the sequence-pair suite** —
  `uv run pytest tests/layout/test_sequence_solver.py -q`

- [ ] **Step 5: Commit** — `layout: stop sequence-pair reserving a coater channel it does not use`

### 2b. `_coater_seat` — DELETE (dead code)

`_coater_seat` (`freeform.py:18526-18583`) has **no production caller** on master: the only
references are its own definition, a `:func:` cross-reference in `_place_coaters`'s docstring
(`:18669`), and two test docstrings. Its 55-line docstring documents a second-tile seat rule
that `_place_coaters` no longer follows.

- [ ] **Step 1** — Confirm the finding yourself before deleting:
  `grep -rn "_coater_seat\b" --include='*.py' src/ tests/ scripts/`. If a caller exists,
  STOP and report it; the deletion is then wrong and the task text is the defect.
- [ ] **Step 2** — Delete the function. Move the two paragraphs of its docstring that are
  still true and not stated elsewhere — *why the seat is upstream of every sorter*, and the
  measured "all 12 coaters were the last belt of their own chain" evidence — into
  `_coater_seats`'s docstring. That history is the reason the rule exists; losing it with the
  function is the failure mode.
- [ ] **Step 3** — Fix the `:func:` reference in `_place_coaters`'s docstring to point at
  `_coater_seats`.
- [ ] **Step 4** — `uv run pytest tests/layout/test_freeform.py -q -x`
- [ ] **Step 5: Commit** — `layout: delete the uncalled _coater_seat and keep its evidence`

### 2c. The `narrow_seats` ban block — MEASURE, then decide

`_reserve_staged_coater_belt_ban` (`:18597-18614`) bans two things under a node arm: (a) the
body's own level across `[-body_half, +body_half]`, and (b) the "area-1 rival" cell mirroring
the drop across the seat.

- [ ] **Step 1: Write a test that measures whether (a) can fire**

Under `placed` the body tiles are the node's own tiles 1-3, which are occupied belts, and
`_merge_frontier` only offers cells `_Canvas.free` accepts. Write a test that builds a
proliferated spec under `placed`, collects `canvas.belt_ban` entries added by clause (a), and
asserts whether any of them names a cell that was free at the time the ban was added.

```python
def test_the_body_level_ban_is_or_is_not_reachable_under_placed(...):
    """Records which clause of the coater belt ban is load-bearing under `placed`."""
```

- [ ] **Step 2: Decide on the measurement**
  - If **no** banned body cell is ever free: clause (a) cannot change any routing decision.
    Delete it, and turn the test into the proof — assert that every node body tile is an
    occupied belt at ban time, so the ban would be a no-op. Name the assertion
    `test_a_node_body_tile_is_always_an_occupied_belt_so_no_merge_can_be_offered_there`.
  - If **any** is free: KEEP clause (a) unchanged and say so in the report and in a code
    comment naming the case that made it fire.
- [ ] **Step 3: Clause (b) — the area-1 rival — is KEPT either way.** It bans a level-1 cell
  that is not part of the node and is exactly the reported area-1 ambiguity (coater#768's drop
  at (53,20,1) against a cargo lane at (55,20,1), both inside the 1.0 radius). It is not made
  structural by the node. Add a one-line comment saying that, so the next reader does not
  delete it with (a).
- [ ] **Step 4: Commit** — `layout: <retire|keep> the coater body-level belt ban, on evidence`

### 2d. Mechanisms that STAY — write the reasons down, do not delete

Add a short block comment (or extend the existing docstring) for each, so a future reader does
not repeat this analysis. The task report must contain this table with the implementer's own
verification of each row.

| Mechanism | Verdict | Reason it still fires under `placed` |
|---|---|---|
| `_coater_keepout_hits` (`:5333`) | **STAYS** | Called twice under `placed`: from `_coater_node_site_is_clear` to reject a site whose addon body would clip a machine, and from `_place_coaters` on the committed seat. The addon's collider reaches machines a belt does not. |
| `_coater_node_site_is_clear`'s full 6x3 ring (`:18410-18422`) | **STAYS, and is load-bearing** | Measured in the experiment (README §5.2): the first `placed` implementation demanded only the four belt tiles and two level-1 cells, and `information-matrix/all-products` then refused on `geom.collide` at bands 160 and 200. The ring is what keeps the node's belts far enough from a machine for the spherical projection. Do not narrow it. |
| `_projected_coater_junction_bans_by_frame` (`:14821`) | **STAYS** | Splitter-versus-coater clearance is a pack-level fact about a committed coater, and `placed` commits coaters. |
| `_Unseatable` (`:13855`) and the height discard (`:21595`) | **STAYS** | Still raised under `placed`, from a new place: "no free ground for the … node near the lane head". A pack that cannot site a node is not a pack, exactly as one that cannot seat a coater is not. |
| `_COATER_WEST_CHANNEL` and the freeform lift (`:2715-2733`) | **STAYS** | Reached only under `off`, which stays for one release. `_staged_static_clearance_keys` already returns empty under a node arm, so freeform's lift is inert under `placed` without a further guard. |
| `_place_coaters`'s seat search, projected-static, addon-supply and splitter certification | **STAYS ENTIRELY** | This is the point of the node being shaped like a four-tile lane (README §1): every rule that governs a coater on a strip channel governs it here unchanged. Under `placed` `seat_channel = len(port.tiles) - 1 = 3` and `_coater_seats` starts at `1 + half_span = 2`, so the search yields exactly one candidate — tile 2, the seat — which is the node's design and not a coincidence to be hard-coded. |
| `hierarchy/compose.py:_coater_belt_ban` | **STAYS** | Reconstructs the ban from a committed building and is agnostic to who seated it. |
| `CargoDomain` / `REQUIRES_SPRAY` | **STAYS** | It is what types the node's two ports; `_Net.__post_init__` refuses a net whose ports disagree. |

- [ ] **Commit** — `docs(layout): record why the surviving coater mechanisms survive`

---

## Task 3: The validator is the arbiter — port, extend, and pin the checks

**Files:**
- Modify: `src/flab2bp/layout/validate.py`
- Test: the existing proliferator-validator test module (find it with
  `grep -rln "prolif.coaters_are_supplied" tests/`)

**Interfaces:**
- Consumes: `placed` as the default (Task 1).
- Produces: check names `prolif.coater_rides_one_run` and `prolif.coater_supply_is_fed`.
  Task 7's gate greps for both.

### 3a. `prolif.coater_rides_one_run` — port it, same name, note the duplication

This check is **not on master**. It exists, complete and green, on the unmerged branch
`selfloop` at `.claude/worktrees/selfloop/src/flab2bp/layout/validate.py:4997-5085`, together
with its helpers `_coater_rides`, `_coater_body_tiles`,
`_coater_belt_predecessor_counts`, `_coater_supply_area_candidates`. Master already has
`_coater_rides` (`validate.py:4899`); confirm which of the others it has before you copy.

- [ ] **Step 1** — Re-check master first: `grep -n "coater_rides_one_run" src/flab2bp/layout/validate.py`.
  If it is present (because `selfloop` landed in the meantime), skip 3a entirely, note that in
  the report, and go to 3b.
- [ ] **Step 2** — Copy the check and any missing helpers verbatim in meaning from `selfloop`,
  keeping the check name `prolif.coater_rides_one_run` byte-identical and keeping the
  docstring's measured evidence (belt#0 at (53,20,0) with predecessors [817, 1872] under
  coater#768; the "narrowed from a second belt to a second RUN" ruling and why the literal
  rule convicted every coater this tool has ever placed).
- [ ] **Step 3** — Add ONE paragraph the `selfloop` copy does not have, at the top of the
  docstring:

```
    **Duplicated deliberately.**  This check also exists on the unmerged branch
    ``selfloop``.  Both copies carry the same name and the same meaning; when
    ``selfloop`` merges, keep ONE and delete the other rather than renaming
    either.  It is duplicated because it is this branch's regression test: the
    placed coater node makes a merge under the body structurally impossible
    (the merge cell is the node's in-port, one tile west of the body, by
    construction), and a structural property with no check is a property the
    next strategy can silently drop.
```

- [ ] **Step 4** — Copy the `selfloop` tests for this check too, adapted to master's fixtures.
- [ ] **Step 5** — `uv run pytest <the prolif validator test module> -q`
- [ ] **Step 6: Commit** — `validate: add prolif.coater_rides_one_run as the node's regression test`

### 3b. `prolif.coater_supply_is_fed` — the new check

`prolif.coaters_are_supplied` asks whether a belt *carrying* proliferator sits in the coater's
addon area 1. It does not ask whether anything ever puts proliferator on that belt. Under
`placed` the node's proliferator port is two belts of the node's own making — the supply belt
on `slots.addon_supply_cell(..., area=1)` and the approach belt one tile further out — and it
is `_proliferator_supply_tree` that connects them to the external entry. A node whose approach
belt is a dangling stub validates clean today.

- [ ] **Step 1: Write the failing test.** Build a proliferated placement, then mutate it: sever
  the link feeding one coater's approach belt (set the feeding belt's `output_obj` to `None`).
  Assert the placement is clean before the mutation and yields exactly one
  `prolif.coater_supply_is_fed` ERROR after it, naming that coater.

- [ ] **Step 2: Run it and watch it fail** — the check does not exist.

- [ ] **Step 3: Implement, reusing the sourcedness machinery that already exists.**

Do **not** write a new graph walk. `validate.py` already computes run-level sourcedness for
`flow.lane_sourced` (`:4177-4183`): `_internal_seeds(ctx)` gives the runs a sorter or machine
seeds, `_external_item(ctx, run, external)` marks runs carrying an external input, and
`_close_over_junctions(ctx, seeds)` closes the seed set over junctions. Reuse exactly that.

```python
@check("prolif.coater_supply_is_fed", needs_spec=True)
def _coater_supply_is_fed(ctx: Context) -> Iterable[Finding]:
    """The belt in a coater's addon area 1 must be fed by something.

    ``prolif.coaters_are_supplied`` asks whether a belt CARRYING proliferator
    sits in area 1.  It cannot ask whether anything ever puts proliferator on
    that belt, because ``carries_item`` is a label the emitter writes, not a
    flow.  A Spray Coater node's proliferator port is two belts of the node's
    own making -- the supply belt on ``slots.addon_supply_cell(..., area=1)``
    and the approach belt one tile further out -- and the run they form is
    joined to the external proliferator entry by
    ``freeform._proliferator_supply_tree``.  If that join is missing, the node
    is a coater with a two-belt stub beside it: it pastes, the machines run,
    the recipe runs unproliferated, and every other check passes.

    Sourcedness is asked the same way ``flow.lane_sourced`` asks it, over the
    same run graph and the same junction closure, so the two cannot disagree
    about what "fed" means.
    """
```

The finding: `Severity.ERROR`, affected `(coater_index, supply_belt_index)`, detail
`{"coater": …, "supply_belt": …, "run": …}`, message naming the coater index, the supply
belt's coordinates, and the fact that its run is reachable from no source.

**Vacuity guard.** A check that passes because it found nothing is not a check. Assert in a
test that on a proliferated placement the check actually *examined* at least one coater — for
example by having the check yield nothing but the test asserting
`len(_coater_rides(ctx)) > 0` on the same context.

- [ ] **Step 4: Run the tests, then the whole validator module.**
- [ ] **Step 5: Commit** — `validate: convict a Spray Coater whose proliferator port is unfed`

### 3c. Pin the three existing arbiters on `placed` output

- [ ] **Step 1** — Add one integration test that builds a proliferated spec under `placed`
  (both placers, via the existing build fixtures) and asserts **zero findings** from all of:
  `prolif.coater_rides_one_run`, `prolif.sprayed_cargo_reaches_machines`,
  `prolif.coaters_are_supplied`, `prolif.coater_supply_is_fed`, `game.addon_supply`,
  `game.addon_facing`, `game.addon_corner`.
- [ ] **Step 2** — The assertion is on the named checks, not on "no findings at all": a broad
  assertion turns any unrelated regression into a mystery here.
- [ ] **Step 3: Commit** — `tests: pin every coater arbiter green on a placed build`

---

## Task 4: Sequence-pair parity

**Files:**
- Test: `tests/layout/test_sequence_solver.py`

**Interfaces:**
- Consumes: Task 2a's guarded lifts; Task 1's default.

The experiment README says `placed` "was clean on sequence-pair from the first run" and needs
none of the three `sequence_solver` changes that variant B would have needed. That is an
observation about a corpus run, not a test. This task makes it a test.

- [ ] **Step 1: Write the test**

```python
def test_sequence_pair_builds_the_placed_coater_node() -> None:
    """`placed` reaches sequence-pair through the SHARED preparation.

    Sequence-pair calls the same `_prepare_routing_problem`
    (`sequence_solver.py:5366`), which is where the node is emitted, so the arm
    needs none of the `_variant_search_inputs` / `_selected_strips` /
    encoding work that a PACKED node would have needed
    (evidence README §5.1).  Asserted rather than assumed.
    """
    placement = SequencePairLayout(...).build(proliferated_spec())
    coaters = [b for b in placement.buildings if b.item_id == catalog.SPRAY_COATER_ID]
    assert coaters, "a proliferated spec must place at least one coater"
    for coater in coaters:
        run = _run_carrying(placement, coater)         # the belts the addon rides
        assert len(run) == _COATER_NODE_TILES, (
            "a coater must ride a free-standing four-tile node, not a strip channel"
        )
        # the addon is on the THIRD tile, and both ports are off the body
        assert run.index(_ridden_belt(placement, coater)) == 2
```

- [ ] **Step 2: Run it and watch it fail first** — with `FLAB2BP_COATER_NODE=off` it must
  fail (the coater rides a strip channel, not a four-tile run). That is the test's negative
  control; write it as a parametrised pair, `off` expecting a strip channel and `placed`
  expecting the node, so the assertion has something to discriminate.
- [ ] **Step 3: Run** — `uv run pytest tests/layout/test_sequence_solver.py -k placed -q`
- [ ] **Step 4: Commit** — `tests: pin the placed coater node on the sequence-pair arm`

---

## Task 5: Apply the over-proliferation ruling

**Files:**
- Modify: `src/flab2bp/layout/validate.py:5060-5105`
- Modify: `src/flab2bp/spec.py:191-195` (docstring only)
- Test: the prolif validator test module

The user's ruling, 2026-09-07: *"over-proliferating is fine if it makes life easier"*. The
design's §5.4 works out what that permits, and the measurement in §6.5 is that it buys **zero**
lanes and **zero** coaters on this corpus — it is permission, not a saving, and it is applied
for the refusal class it removes.

- [ ] **Step 1: Write the failing test**

```python
def test_a_shared_lane_through_a_node_warns_rather_than_refusing() -> None:
    """Over-proliferation is a WARNING: the user ruled it acceptable.

    A sprayed lane that reaches an unproliferated consumer over-produces that
    consumer's proliferator cost.  It does not break the build, it does not
    miss a rate, and forbidding it refuses a legal placement.  The build is
    still told, so it reaches the report.
    """
    findings = [f for f in validate(placement, spec=spec)
                if f.check == "prolif.sprayed_cargo_reaches_machines"]
    over = [f for f in findings if "over-produce" in f.message]
    assert over, "the case must still be reported"
    assert all(f.severity is Severity.WARNING for f in over)


def test_a_machine_eating_unsprayed_cargo_is_still_an_ERROR() -> None:
    """The requires_spray half is untouched: a proliferated machine eating
    cargo that never passed a coater still misses its rate silently, which is
    the whole reason this check exists."""
```

- [ ] **Step 2: Run and watch the first fail** (it is ERROR today), and the second pass.

- [ ] **Step 3: Change the severity of ONE clause only**

In `_sprayed_cargo_reaches_machines`, the `forbids_spray` branch's `Finding` becomes
`Severity.WARNING`. The `requires_spray` branch stays `Severity.ERROR`. Because the two share
one `yield Finding(...)`, split the severity out:
`severity = Severity.ERROR if requires_spray else Severity.WARNING`.

Amend the `forbids_spray` message so it says the build over-produces **by design**, names the
item, and does not read like a defect.

- [ ] **Step 4: Keep the hard split where it is still hard.** Do not touch the case of two
  consumers of one item wanting *different proliferator modes*: a coater holds one proliferator
  item and `RateSolution.tier` (`solve.py:118`) is global to the solve, so that split stays
  mandatory. Say so in the docstring and add a test asserting the differing-mode case is
  unaffected — if the corpus has no such spec, construct a minimal one.

- [ ] **Step 5: Retitle `BuildSpec.lanes_requiring_split`'s docstring** (`spec.py:191-195`) to
  say it is now a REPORT of which items get over-proliferated, not a correctness constraint. Do
  not delete the field or its computation (`rates/candidates.py:220-229`).

- [ ] **Step 6: Check the refusal path.** `_Unseatable`'s retained failure label defaults to
  `"prolif.sprayed_cargo_reaches_machines"` (`freeform.py:21605-21607`). Confirm that a
  WARNING-only finding cannot cause a height to be discarded — i.e. that the sweep's
  clean/refused decision reads ERROR severity, not finding count. If it reads count, that is
  the refusal class the ruling removes and it must be fixed here; name it in the report either
  way.

- [ ] **Step 7: Run** — the prolif validator module, then `tests/layout/test_freeform.py -q -x`.
- [ ] **Step 8: Commit** — `validate: downgrade the over-proliferation clause to a WARNING`

---

## Task 6: Web viewer — verify the node decodes and renders, adjust only if measured wrong

**Files:**
- Read: `web/src/model/beltGraph.ts:83-110`, `web/src/scene/BeltRibbons.tsx`,
  `web/src/scene/BuildingInstances.tsx`
- Modify (only on evidence): `web/src/model/beltGraph.ts`
- Test: `web/tests/model/beltGraph.test.ts`
- Evidence: `docs/superpowers/evidence/2026-09-07-coater-placed-gate/web/`

**This is a verification task with a conditional fix. Measuring "it is already correct" and
changing nothing is a successful outcome and must be reported as one.**

The viewer renders coaters from the blueprint and has no coater-specific code at all
(`grep -rl "coater\|Coater\|SPRAY" web/src/` returns nothing), so the node is only ever
belts + an addon building. Three things to measure:

- [ ] **Step 1: Produce a `placed` blueprint to look at.** Build the reported URL under
  `placed` (Task 7's runner will do this; if Task 7 has not run yet, use the CLI directly with
  `--budget 30`) and save the blueprint string under the evidence directory.

- [ ] **Step 2: The four-tile run decodes as one run.** `buildBeltRuns` segments by local
  in-degree: a run starts at any belt whose inbound count is not exactly 1 and stops before a
  belt whose inbound count exceeds 1. The node's `n0` has inbound ≥ 1 from the router path(s)
  that merge into it — **and if two producer paths merge there, `n0`'s inbound is 2, which
  starts its own run.** Assert what actually happens: write a `beltGraph.test.ts` case over the
  saved blueprint that finds the belts under each coater and asserts the addon's ridden belt
  (`n2`) and its neighbours `n1`, `n3` are in ONE run. Report the observed run boundaries.

- [ ] **Step 3: The endpoint-icon inference does not flood.** `freeInput` is
  `!cyclic && inbound == 0 && !sorterFed.has(head)`. The node's `n0` is the sink of producer
  nets, so it is fed by BELTS, not by a sorter — meaning `inbound > 0` and `freeInput` is
  false, which is correct. The failure mode to look for is the opposite: a node whose in-port
  the router reached by a path that terminates rather than links, leaving `inbound == 0` and
  `sorterFed` false, which would put an endpoint icon on every node. **Count the endpoint
  icons on a `placed` blueprint and on the same spec under `off`** (reuse
  `docs/superpowers/evidence/2026-09-07-endpoint-icons/count-icons.ts`, which already does
  exactly this counting) and put both counts in the report.

- [ ] **Step 4: The coater renders on the third tile.** Confirm the addon building appears at
  the node's `n2` in the scene, not floating. A screenshot into the evidence directory is
  enough; the viewer has no coater-specific transform, so this is a smoke check.

- [ ] **Step 5: Adjust `beltGraph.ts` ONLY if a measurement is wrong.** If the icon count
  under `placed` is not materially different from `off`, change nothing and say so. If it
  floods, the fix is in the `freeInput` predicate and it gets its own test asserting the count
  before and after on the saved blueprint.

- [ ] **Step 6: Run the web tests** — from `web/`: `bun run test` (or the project's configured
  rstest command; check `web/package.json`).
- [ ] **Step 7: Commit** — `web: pin the coater node's run and endpoint icons` (or
  `docs(web): record that the coater node needs no viewer change`).

---

## Task 7: The gate

**Files:**
- Create: `docs/superpowers/evidence/2026-09-07-coater-placed-gate/` — `run_round.sh`,
  `run_reported.sh`, `cpu_pressure.sh`, `analyse.py`, `roundA/`, `roundB/`, `README.md`

**This task's deliverable is a measured README, not a green light. Report a FAIL as a FAIL,
naming the cell and the mechanism.**

### The operating point (copy exactly; do not tune)

- The full 72-cell corpus (36 specs × 2 strategies), `--budget 30`, `--jobs 8`,
  `--strategy both`, `--max-seconds 3600`.
- `audit.py` sizes CP-SAT workers as `cores // jobs`, so `--jobs 8` gives sixteen workers per
  cell and targets the whole box. **Never run two arms at once** — that is 2× the box and every
  timing becomes a measurement of the neighbour.
- **Two rounds** (`roundA`, `roundB`). CP-SAT with more than one worker under a wall-clock
  limit is not reproducible (`base.DEFAULT_SEARCH_WORKERS`'s own docstring); the experiment
  measured **two runs of the SAME arm differing on 8 of 72 cells**. One round is not evidence.
- **Chunk by URL and skip URLs already recorded.** `audit.py` appends its JSONL only after the
  loop, and a native `SIGSEGV` in cell 13 destroyed twelve completed cells on the experiment's
  first attempt. Copy the skip-guard from
  `docs/superpowers/evidence/2026-09-07-exp-coater-node/run_round.sh`.
- Record CPU pressure before each arm as
  `vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print sum/5}'`.
- The twelve corpus URL ids: `iron-ingot magnetic-coil graphene electromagnetic-matrix plastic
  processor energy-matrix super-magnetic-ring casimir-crystal information-matrix quantum-chip
  universe-matrix`.

### The arms

Two, in this order, each a complete pass over the corpus:

1. **baseline** — this branch's **merge base** (`master@ffc5e88b`) with no env var set, i.e.
   today's shipped behaviour. Run it from a separate checkout of the merge base, or from this
   worktree with `FLAB2BP_COATER_NODE=off` **only after confirming that `off` on this branch
   is byte-identical to the merge base on at least three control specs** — if it is not, the
   `off` arm has drifted and you must use a merge-base checkout. Say which you used.
2. **placed** — this branch's HEAD, no env var set (the new default).

### Steps

- [ ] **Step 1: Write the runners** in the new evidence directory, adapted from the
  experiment's `run_round.sh` (chunking, skip-guard, per-arm log, CPU pressure line). Two arms
  instead of five; no `packed` special-casing.
- [ ] **Step 2: Round A.** Both arms, sequentially. Nothing else building on this box from
  this session.
- [ ] **Step 3: Round B.** Both arms again.
- [ ] **Step 4: The reported URL, six pairs.** `AMM_URL` from
  `docs/superpowers/plans/2026-09-06-self-loop-recipes.md:613`, three candidate policies
  (`no-proliferator`, `all-products`, `output-products`) × two strategies (`freeform`,
  `sequence-pair`), `--budget 30`, with the coater probe
  (`docs/superpowers/evidence/2026-09-07-exp-coater-node/probes/probe_cell.py`, which prints
  every validator finding, the coater count, and `MERGE-UNDER-BODY` lines). Both arms. Master
  reproduces the defect on `coater#768`/`coater#771` over `belt#0`/`belt#19`; report whether
  those exact indices are clean under `placed`.
- [ ] **Step 5: Pair the rounds** with
  `uv run python scripts/audit_compare.py <baseline.jsonl> <placed.jsonl> --json <path>`.
  **`audit.py` says NOT CLEAN on any refusal**, so the verdict line is not the answer: read
  the compare's **counts** and **named differing cells**.
- [ ] **Step 6: Write `README.md`** with, at minimum:
  - the per-round verdict table: arm × cells / CLEAN / REFUSED / INVALID / CRASH /
    coater-merge findings / coaters / route p50 / route p95 / rip-ups;
  - **area delta** as a geometric mean over the cells clean in BOTH arms, per round, with the
    larger/smaller split;
  - **belt tiles and nets** over the proliferated cells clean in both arms, per round;
  - **every named mover**, both directions, with the refusal message for each lost cell;
  - the reported URL's six pairs: builds and coater-bodies-over-a-merge, per arm;
  - the CPU-pressure range across the rounds;
  - the exact commands, so the run reproduces.

### PASS / FAIL

**PASS requires all four:**

1. **72/72 CLEAN in both rounds** on the `placed` arm.
2. **Zero coater-merge findings** — zero `prolif.coater_rides_one_run` findings across the
   corpus, and zero `MERGE-UNDER-BODY` lines on all six reported-URL pairs.
3. **Area within +3.5%** of the merge base, as the geometric mean over cells clean in both
   arms, in **both** rounds. (The experiment measured +2.74–2.89%; the headroom is noise plus
   the sequence-pair channel retirement of Task 2a, which can only reduce it.)
4. **No cell lost** — every cell CLEAN on the baseline is CLEAN under `placed` in the same
   round.

**Any FAIL is reported as a FAIL**, naming the cell, the strategy, the refusal message and the
mechanism. Do not re-run an arm to get a better number; a cell that moves between rounds is
the flake signal the two rounds exist to expose, and it is reported as a flake with both
observations.

- [ ] **Step 7: Commit** — `docs: gate the placed coater node on the 72-cell corpus`

---

## Task 8: Verification at HEAD

**Files:** none — this is the branch's final evidence.

- [ ] **Step 1** — `uv run ruff check .` — must be clean.
- [ ] **Step 2** — `uv run ruff format --check .` — must be clean.
- [ ] **Step 3** — `uv run mypy src` — must be clean.
- [ ] **Step 4** — The full suite, exit code recorded. The pytest summary line does not print
  in this environment, so **use the exit code**, and scope the run so the 120 s
  `pytest-timeout` backstop does not hard-kill it (run by directory and aggregate).
- [ ] **Step 5** — Name the **known reds**: run the same command set on the merge base and
  report only the delta. A test that was red before this branch is not this branch's failure,
  and a test that turned red is.
- [ ] **Step 6** — `git rev-parse HEAD` — the branch SHA for the final report.
- [ ] **Step 7** — Stop. **Ready to merge, not merged.** Do not merge, push, or delete the
  branch.

---

## Risks

1. **The sequence-pair channel retirement (Task 2a) changes what was measured.** The
   experiment's `placed` numbers were taken with those lifts still in place. Retiring them can
   only narrow sprayed strips, so area should fall and coverage should not — but a narrower
   strip changes the pack, and the pack is a CP-SAT search. Mitigation: the gate is against the
   merge base, not against the experiment's column, and Task 7's PASS criteria are stated in
   those terms. If Task 7 loses a cell that the experiment's `placed` arm kept, revert Task 2a
   alone (it is a self-contained commit) and re-gate.
2. **`off` drifts and stops being a control.** Every guard reads `coater_mode().is_node`, so a
   deletion done "because `placed` does not need it" silently changes `off`. Mitigation: Task
   2's rule — a mechanism is retired only when a test proves it cannot fire — plus Task 7's
   requirement to confirm `off` matches the merge base on three control specs before using it
   as the baseline arm.
3. **`prolif.coater_rides_one_run` collides on the `selfloop` merge.** Two copies of one check
   name. Mitigation: Task 3a's mandated docstring paragraph says explicitly that when
   `selfloop` merges, one copy is deleted and neither is renamed.
4. **The new `prolif.coater_supply_is_fed` is vacuous.** A check that examines nothing passes
   forever. Mitigation: Task 3b's mandated vacuity guard — a test asserting the check actually
   examined at least one coater — and the mutation test that makes it fire.
5. **The over-proliferation downgrade hides a real miss.** Mitigation: only the `forbids_spray`
   clause moves; the `requires_spray` clause — the one that catches a proliferated machine
   eating unsprayed cargo, which is a silent rate miss — stays ERROR, with its own test.
6. **Task 7 is the long pole and another agent's build corrupts it.** Two rounds × two arms ×
   72 cells at 30 s budget is hours. Mitigation: one build at a time, `pgrep -f` before
   starting, CPU pressure recorded per arm with `vmstat`, and URL-level chunking so a crash
   costs one URL rather than the arm.

---

## Out of scope

- **Variant B (`packed`) and its sequence-pair work.** The experiment's §7.2 is explicit: B's
  remaining gap to C is two `universe-matrix` cells caused by handing the packer 3.6× the
  rectangles, nothing in the pack objective addresses it, and the `sequence_solver` work of
  §5.1 should not be started for B. The `packed-hpwl` finding — that giving a node a real HPWL
  term halves its area cost — is recorded in the README and is not carried here.
- **Variant A (`seat`).** Superseded and deleted. Branch `coater-node` is retained unmerged
  for its evidence only.
- **Raising `_COATER_WEST_CHANNEL` to 4.** That was the seat design's fallback for a coverage
  loss that only the seat arm suffers. `placed` is 72/72 and does not need it.
- **Making the node a first-class producer/consumer in the pack's vocabulary** (real
  `out_lanes` / `in_above`). Untested, argued against in README §5.3, and irrelevant to
  `placed`, whose ring search already sites the node against the lane head.
- **Fixing `audit.py` to write its JSONL incrementally** (README §5.6). Worth doing; not this
  branch. The gate's runners chunk by URL instead.
