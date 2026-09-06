# Why direct insertion never lands on the corpus

Follow-up to `2026-09-06-density-decomposition`, which measured `direct_inserts
= 0` on all 41 builds it made while 19 cells offered 236 candidates.

## Verdict: TUNING

**The mechanism is not broken and the flow-order rule is not wrong. A direct
insert is never taken because every bridged arrangement measured COSTS AREA, and
the packer's objective is lexicographic on width, so the reward cannot buy the
column the bridge needs — by construction, not by weight.**

Pin one direct Boolean to 1 in `_pack_model` and the whole pipeline builds a real
bridge that the validator passes with zero errors and zero skipped checks:

| cell | area free | area forced | Δ area | belt tiles free | forced | Δ belt | `direct_inserts` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `electromagnetic-matrix` | 609 | 630 | **+21 (+3.4%)** | 166 | 152 | −14 | 0 → **1** |
| `casimir-crystal` | 1107 | 1248 | **+141 (+12.7%)** | 398 | 350 | −48 | 0 → **1** |
| `processor` | 810 | 1044 | +234 (+28.9%) | 271 | 299 | +28 | 0 → 0 |
| `graphene` | 363 | *refuses* | — | 70 | — | — | 0 → — |
| `magnetic-coil` | 198 | *refuses* | — | 50 | — | — | 0 → — |

So one bridge buys 14–48 belt tiles for 21–141 tiles of area: an exchange rate of
**1.5 to 2.9 area tiles per belt tile saved**. Direct insertion on this corpus is
an area LOSS, and the objective is right to refuse it. Two of the five cells
cannot even be packed with the bridge forced.

The killing predicate, in one line:

> `freeform.py:4740` — `model.minimize(w_var * cap + base_tier)` with
> `cap = tie_break_cap(...) = n_terms * (width_bound + height) + MU_DIRECT * n_direct + 1`
> (`freeform.py:3514-3526`), so one extra column of width outweighs *every*
> direct-insert reward in the model put together, and the bridged alignment
> `origin_delta == permitted_delta` (`freeform.py:4587-4592`) always costs at
> least one column on a real spec.

The code already says this, at `freeform.py:4575-4578`, about the east/west
variant of the same idea: *"it forces the two strips side by side, which WIDENS
the pack, and width outranks the direct-insert reward lexicographically. The
solver correctly refused every such pair, so the feature never fired."* The
north/south variant that replaced it has the same fate for the same reason; it
just takes a measurement to see it, because the alignment constraint is a fixed
`origin_delta`, not an obviously-wider geometry.

## History: when it went to zero

`history.py` reads every committed evidence JSONL, groups rows by the commit each
run recorded and orders by author date. No build is run — this is the record the
corpus already made. (`history.json`; rows in commit-less `profile-*.jsonl` /
`ladder.jsonl` files are grouped under `?` and excluded from the claim below.)

| commit | when | freeform rows | Σ `direct_inserts` | Σ `direct_insert_candidates` |
| --- | --- | --- | --- | --- |
| `a232f0a` | 09-05 16:23 | 108 | 57 | 708 |
| **`c3d7229`** | **09-05 19:21** | **108** | **57** | **708** |
| **`79eed92`** | **09-05 20:42** | **108** | **0** | **708** |
| `ef2207a` | 09-05 21:44 | 108 | 0 | 708 |
| `b01f6fc` | 09-05 22:08 | 228 | 0 | 1224 |
| `811190a` | 09-05 22:59 | 108 | 0 | 708 |

`c3d7229` is the last commit whose evidence has a freeform direct insert;
`79eed92` is the first with none, and it is a test-only commit. The only source
change in `c3d7229..79eed92` that touches the layout is the merge
`c3e8bca "Merge branch 'broke8-flow-order'"` (`8bba914 "Enforce directional
cargo flow"` .. `ba962ac`); the other five commits are `rates/`, deadlines and
formatting. Post-merge the corpus has **0 freeform direct inserts in 562 rows**
across `2026-09-06-speedups-2-batch2` (216), `-batch3` (226) and
`-density-decomposition` (120).

Note `direct_insert_candidates` is unchanged at 708 across the boundary: that
stat counts RECIPE pairs (`_direct_insert_candidates`, `freeform.py:2714`), which
the flow-order rule does not touch. The strip-level candidates the packer
actually sees come from `_direct_net_candidates` (`freeform.py:3307`).

## The trace, stage by stage

`probe_direct.py` spies `_direct_net_candidate_uncached`, `_pack_model`,
`_pack_result`, `_bridge` and `slots.sorter_seat_is_clear`, and re-derives every
rejection so it can be named. Eight cells, `workers=1` so every stage stays in
one process (`probe-direct.json`).

| cell | recipe pairs | strip candidates accepted | packs solved | packs that SET a direct var | bridges attempted | realized | area |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `magnetic-coil` | 2 | 1 | 13 | 4 | 1 | 0 | 198 |
| `graphene` | 1 | 1 | 15 | 0 | 0 | 0 | 363 |
| `electromagnetic-matrix` | 6 | 4 | 16 | 6 | 4 | 0 | 609 |
| `processor` | 6 | 2 | 16 | 4 | 2 | 0 | 810 |
| `casimir-crystal` | 4 | 3 | 15 | 0 | 0 | 0 | 1107 |
| `super-magnetic-ring` | 11 | 11 | 10 | 0 | 0 | 0 | 2183 |
| `information-matrix` | 17 | 16 | 15 | 0 | 0 | 0 | 7917 |
| `quantum-chip` | 16 | 22 | 15 | 0 | 0 | 0 | 8022 |

(`workers=1` handicaps the big cells — `quantum-chip` builds 5610 under the
harness at 8 workers. The candidate and pack columns are what matter here.)

Enumeration census over the eight cells: **60 accepted**, 41 rejected
`not-enough-source-machines`, 37 `dest-flow-filter` (a clear column existed but
none west of the first pickup), 4 `dest-no-clear-column`. So the flow-order rule
removes a lot of candidates, but **it does not remove them all** — 60 survive and
reach CP-SAT.

Stage by stage:

1. **Enumeration is not the blocker.** 60 strip-level candidates survive
   `_direct_origin_deltas` (`freeform.py:3060`) including both its flow-order
   filters, `column > last_source_injection` (`:3104`) and
   `column < first_destination_pickup` (`:3114`).
2. **On the five larger cells the packer never sets a direct var at all** —
   0 of 55 pack solves, with 3 to 22 Booleans available in every model. Width.
3. **On the three smallest cells it does** (4, 6 and 4 solves out of 13-16), and
   emission then refuses every one of the 7 bridges at
   `slots.sorter_seat_is_clear` (**`freeform.py:17913`**), which makes the whole
   pack attempt fail with a `STATIC_ACCESS` preparation failure
   (`freeform.py:16938-16947`). That is the second finding, below.

## Second finding (real, separable, NOT fixed here)

`_direct_clear_columns` (**`freeform.py:2796-2816`**) claims more than it proves.
Its docstring says excluding the lane's own planned attachment columns
*"proves the collider precondition before CP-SAT can reward the candidate"*, and
`_pack_model` repeats the claim at `freeform.py:4582-4586`
(*"keeps an unprovable candidate out of the objective instead of letting emission
discover the missing precondition after the reward has already influenced the
pack"*). Emission discovers a missing precondition anyway.

The traced case, `electromagnetic-matrix`, source strip 3 → destination strip 0,
item `iron-ingot` (`probe-direct.json`, `seat_rejects[0]`):

```
destination lanes:  y=-2  cols=[0]  items=('copper-ingot',)      <- outer
                    y=-1  cols=[1]  items=('iron-ingot',)        <- bridged
machine band:       y= 0
emitted:  belt (12,6) copper lane      sorter (12,6)->(12,8)  copper -> machine
          belt (12,7),(13,7) iron lane sorter (13,7)->(13,8)  iron   -> machine
          machine (12,8)
bridge wanted: column 12, y 4 -> 7
```

`first_destination_pickup` is local column 1, so flow order leaves exactly local
column 0 (absolute 12). `_direct_clear_columns` says column 0 is clear, because
the iron lane's own attachment is column 1. But the COPPER lane's sorter sits at
column 0 and runs from row −2 to row 0 — it crosses the iron lane's row on its
way to the machine. Two vertical sorters in one column: `sorter_box`
(`colliders.py:1213`) stretches both between their seated ends and grows 0.35
past every belt end, so the boxes overlap (measured: centres 0.256 apart in x
with half-extents 0.26 each, z ranges `[4.71, 9.11]` and `[7.23, 9.83]`), and
`sorter_seat_is_clear` refuses — correctly, this is the one pairing the paste
does not excuse.

It is not incidental. Per accepted candidate, the columns flow order leaves and
the columns other lanes' crossing sorters occupy:

| candidate | flow-legal cols | crossing cols | legal − crossing |
| --- | --- | --- | --- |
| `magnet` → `magnetic-coil` | [0] | [0] | **[]** |
| `iron-ingot` → `circuit-board` | [0] | [0] | **[]** |
| `microcrystalline-component` → `processor` | [0] | [0] | **[]** |
| `titanium-ingot` → `titanium-crystal` | [0] | [0] | **[]** |
| `titanium-crystal` → `casimir-crystal` | [0, 1] | [0, 1] | **[]** |
| `magnetic-coil` → `electromagnetic-matrix` | [0, 1] | [1] | [0] |
| `circuit-board` → `electromagnetic-matrix` | [0] | [] | [0] |
| `energetic-graphite` → `graphene` | [0, 1] | [] | [0, 1] |

The shape is structural: input lanes attach at consecutive west-most columns, so
for a consumer whose bridged ingredient rides the lane NEAREST the machine band,
the columns strictly west of its attachment are exactly the columns the outer
lanes use — and every outer lane's sorter crosses the bridged lane's row. Five of
eight candidates are dead on arrival, and `magnetic-coil` → `electromagnetic-matrix`
dies too once the source-side filter is applied in the same absolute frame.

**The exact fix**, when someone wants it: `_direct_clear_columns` must also
subtract, for every OTHER plan in `strip.attachment_plan`, the columns of its
attachments whose sorter row interval `[min(lane_y, cell[1]), max(lane_y,
cell[1])]` strictly contains this plan's `lane_y`. `LaneAttachmentPlan`
guarantees `attachment.cell[0] == attachment.column` (`strip_variants.py:239`),
so those sorters are vertical and the test is exact. It applies to the source
side (`freeform.py:3103`) as well as the destination side (`:3109`).

**It is deliberately not applied in this experiment**, because it deletes direct
Booleans from the model and the density decomposition measured that those
Booleans are worth 10.3% of area on `quantum-chip@180` as a pure search
perturbation (14896 with, 16434 without) — removing them re-tunes the objective
by a side effect, which is the one thing this experiment was told not to do. It
costs no density today: it costs discarded pack attempts on small cells.

## What a block library should assume about direct insertion

1. **Do not assume the packer will choose it.** It never has on the corpus since
   the flow-order merge and, on the numbers above, it never should: a bridge is
   worth 14–48 belt tiles and costs 21–141 tiles of area.
2. **It does work, and it validates.** A block may bake a bridge into its own
   fixed internal geometry. `sorter_seat_is_clear` and the flow-order rule are
   both real game constraints, so a hand-built block must respect them: the
   bridge lands strictly west of the consumer's first pickup, draws strictly east
   of enough producer injections, and its column must be free of every sorter
   crossing either lane's row — including sorters serving the consumer's OTHER
   input lanes.
3. **The seatable column is essentially unique.** Flow order leaves the consumer
   at most `attachment.column` candidate columns for machine 0 and none later, so
   a block that wants direct insertion must put the bridged ingredient on the
   consumer's OUTERMOST input lane (nothing crosses it) or leave a deliberate
   column gap in the attachment plan. Both are geometry decisions, not solver
   decisions.
4. **Inside a fixed block the width objection disappears.** The area cost
   measured above is the cost of forcing a relative offset on a free packer. A
   block pays it once, at design time, and can then amortise it — which is the
   argument for putting direct insertion in the block library rather than in the
   packer.

## Files

* `probe_direct.py` / `probe-direct.json` — per-stage instrumentation and the
  named rejection for every candidate, pack and bridge on eight cells.
* `probe_forced.py` / `probe-forced.json` — free vs one-bridge-forced build of
  five cells, with the validator run on both.
* `history.py` / `history.json` — the commit-ordered evidence census.

## Concerns

* `probe_direct.py` runs with `workers=1` so the spies see every stage; the big
  cells are therefore packed worse than the harness packs them (`quantum-chip`
  8022 here vs 5610 in `audit-base.jsonl`). The candidate and pack-decision
  columns are worker-count independent; the areas in that table are not
  comparable to harness areas.
* `probe_forced.py` pins `min(direct_vars)` — the lexicographically first pair —
  in every model, so the Δ area is one specific bridge per cell, not the cheapest
  one. It is a lower bound on how good forcing can be and an existence proof that
  a bridge builds and validates, not an optimum.
* Two of the five forced cells refuse outright. That is the bridge constraint
  interacting with the height schedule, not a claim that those cells have no
  bridged packing at some other height.
* No `scripts/audit.py` run: the box is shared and no source changed, so there is
  nothing to gate.
