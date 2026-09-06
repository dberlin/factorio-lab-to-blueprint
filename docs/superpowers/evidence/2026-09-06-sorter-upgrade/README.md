# Sorter capacity on the plane-filter URL

`flab2bp <plane-filter URL> --budget 30` refused every candidate and every strategy with
`flow.sorter_capacity` on hydrogen. The report read as though the picker had failed to upgrade a
sorter. It had not: it was already on the fastest tier the save can build. The lane had been
seated on a row no tier can reach fast enough.

URL (`o=plane-filter`, three candidates, both strategies):

```
https://factoriolab.github.io/dsp/list?z=eJzLt3Uq0zI1MFDLt3VK1jI0MNDSMgSxs5DYkQi2uZaRAVzcScsYSb0RjF2CYDolaxmZwtiVIOUIvYZwThUSuwCJHQFmw3SUI.PCtAwtLS2hMoEgC0GMMCijFEWjIdzIzKRUW2e1otQK23i13Nwi2-S64rrMusC6SrUyW0NDAPYfP-s_&v=11
```

## 1. Reproduction (before the fix)

`repro_before.txt`, at `c3cf24ef`, `--budget 30 -v`, `uptime` 12:39 load 8.6 / 12:42 load 11.0.
Exit code **3**. No blueprint emitted: all six candidate/strategy pairs refused.

| candidate | strategy | verdict | findings |
| --- | --- | --- | --- |
| no-proliferator | freeform | refused | `flow.sorter_capacity` x5, all hydrogen |
| no-proliferator | sequence-pair | refused (4 islands) | `flow.sorter_capacity`, `geom.collide` |
| all-products | freeform | refused | `flow.sorter_capacity` x3, all hydrogen |
| all-products | sequence-pair | refused (4 islands) | `flow.sorter_capacity` |
| output-products | freeform | refused | `flow.sorter_capacity` x4, `geom.collide` |
| output-products | sequence-pair | refused (4 islands) | `flow.sorter_capacity`, `geom.collide` |

Every hydrogen finding is the same sentence with a different sorter index:

```
flow.sorter_capacity (45, 0, 42): sorter 45 must move 8 items/s of hydrogen across 3 tiles
but sustains only 20/3
{'sorter': 45, 'span': 3, 'item': 'hydrogen', 'required': '8', 'capacity': '20/3', 'stack': 1}
```

`20/3` is `catalog.SORTER_RATE_AT_1[2014] / 3` -- the **Pile Sorter**, the top of the ladder,
across three tiles, at stack 1.

## 2. Characterisation (`characterise.py`, `characterise.txt`)

The save: the URL carries **no** technology set, which FactorioLab reads as fully researched
(`lab/techs.py:127`), so nothing is gated.

| property | value |
| --- | --- |
| `sorter_item_ids` | `('sorter-1', 'sorter-2', 'sorter-3', 'sorter-4')` -- the full ladder |
| `sorter_pick_stacks` / `sorter_place_stacks` | `(1, 1, 1, 4)` / `(1, 1, 1, 4)` -- Pile Sorter Upgrade at level 6 |
| `piler_unlocked` | `True` |
| `belt_item_id` / `belt_stack` | `conveyor-belt-3` at 30/s / **1** |
| `planning_stack('hydrogen')` | 1 -- `BuildSpec.planning_stack` returns 1 whenever `belt_stack == 1` (design rule 1) |

The convicted lane, per candidate (`lane_seating.py`, `lane_seating_before.txt`):

| candidate | machines | item | per-machine demand | seated row | span | chosen tier | capacity |
| --- | --- | --- | --- | --- | --- | --- | --- |
| no-proliferator | 5 | hydrogen | 8/s | `input:south:0`, y=-3 | 3 | 2014 Pile Sorter | 20/3 = 6.67/s |
| all-products | 3 | hydrogen | 128/15 = 8.53/s | `input:south:0`, y=-3 | 3 | 2014 Pile Sorter | 20/3 |
| output-products | 4 | hydrogen | 8/s | `input:south:0`, y=-3 | 3 | 2014 Pile Sorter | 20/3 |

The other two ingredients of the same machine were seated where the throughput was not needed:
`graphene` at 1.33/s on y=-2 (span 2, ceiling 10/s) and `optical-grating-crystal` at 5.33/s on
y=-1 (span 1, ceiling 20/s).

`variant_search.py` (`variant_search_before.txt`) settles that it was not a variant-selection
accident: of the 8 variants generated for `casimir-crystal-advanced`, **0** were servable; the
Re-composing Assembler offers south rows at spans 1, 2, 3 and north rows at spans 2, 3, and the
lane order pinned hydrogen to the furthest one in every one of them. Every other family was
100% servable.

## 3. Verdict: none of (a)-(d)

- **(a) picker chose a slower tier than the save allows** -- NO. `_pick_sorter`
  (`src/flab2bp/layout/freeform.py:5979`) walks `_sorter_tiers_for(spec)` slowest-first and falls
  back to `tiers[-1]`; the emitted sorter is `item_id=2014`, the Pile Sorter, which the finding
  itself names by capacity.
- **(b) demand figure wrong (per-machine vs per-lane, stack vs items)** -- NO. 8/s is exactly
  `casimir-crystal-advanced`'s per-machine hydrogen rate
  (`_prepare_routing_problem`, `freeform.py:16220`), and `validate._item_share`
  (`src/flab2bp/layout/validate.py:5875`) divides by the sorters carrying *that item* to *that
  machine* -- one. Planner and validator agree to the fraction.
- **(c) ladder truncated by researched technologies** -- NO. The URL is fully researched: all
  four tiers, Pile Sorter Upgrade at level 6, piler unlocked. There is no technology to name and
  nothing to refuse.
- **(d) validator measures something different from what the picker sized against** -- NO. Picker
  and validator both evaluate the Pile Sorter at span 3 and stack 1 and both get 20/3.

The killing predicate is `catalog.sorter_rate(tier, span) >= per_machine` at
**`src/flab2bp/layout/freeform.py:6011`**, evaluated with `span == 3`: no tier satisfies it, so
`_pick_sorter` returns `tiers[-1]` (line 6013) and `validate._sorter_capacity`
(`src/flab2bp/layout/validate.py:5638`) convicts. The span is the free variable, and nothing
chose it against the rate.

The row came from `_seat_inputs` (`freeform.py:2170`), which returns the first split that fits by
rows and columns -- all three ingredients above the band -- and then
`_seat_both_fed_outermost` (`strip_variants.py:1045`) pins hydrogen to the outermost of those
rows, because hydrogen is belted in *and* made by `graphene-advanced` and a both-fed lane needs a
second belt approach. Neither step consults a rate. Seating one ingredient below instead leaves
hydrogen on the two-tile row, where the same Pile Sorter carries 10/s.

## 4. The fix (`b368a028`)

`_seat_inputs` gains a `seating_fits` predicate over the whole candidate split.
`_logical_strip_plans` supplies one (`_split_is_servable`, `_side_rows_serve`,
`_fastest_lane_rate`) that walks the machine's reach profiles exactly as `_side_seatings` and
`_output_side_assignments` do, applies `_seat_both_fed_outermost` first, and asks whether the
fastest tier the save can build carries each lane's rate at the row it would land on.

It is a **preference, not a filter**: when no split satisfies it the search runs again without it,
so a lane no row can serve keeps the seating it had and is still reported by
`flow.sorter_capacity` with the numbers rather than becoming "the spec cannot be planned into
strips". The predicate is deliberately generous -- a profile's shortest span, the fastest tier's
rate at the lane's full planned stack, and an output item's rate divided between the lanes that
carry it -- so only a split that *cannot* work is skipped.

Tests (`tests/layout/test_strip_variants.py`):
`test_a_lane_is_never_seated_on_a_row_no_sorter_tier_can_serve` (failing first: `assert not
[('hydrogen', 3, Fraction(8, 1))]`) and
`test_a_seating_no_row_can_serve_still_plans_and_is_judged_downstream`.

## 5. After (`repro_after.txt`, `lane_seating_after.txt`)

`uptime` 13:20 load 7.7 / 13:23 load 6.2. Exit code **0**, blueprint emitted, **0 errors on all
six pairs**.

```
sequence-pair / all-products: 45 machines, 2530 tiles, 1716 buildings
candidate           strategy      area  errors
all-products        sequence-pair    2530       0
output-products     sequence-pair    2666       0
all-products        freeform         2688       0
output-products     freeform         2744       0
no-proliferator     sequence-pair    3300       0
no-proliferator     freeform         4488       0
```

The casimir strip now seats hydrogen at span 2 (Pile Sorter, 10/s vs 8/s needed) and moves
`optical-grating-crystal` below at span 3 (6.67/s vs 5.33/s needed). No lane in any candidate is
over capacity.

## 6. Corpus guard

`docs/superpowers/evidence/2026-09-05-scale-profile/prof_harness.py`, same tree, budget 30,
`guard/*.json`. `uptime` before-pass 13:36 load 6.9 / 13:38 load 9.8; after-pass 13:34 load 6.6 /
13:36 load 7.2.

| cell | verdict before | verdict after | area before | area after | moved |
| --- | --- | --- | --- | --- | --- |
| universe-matrix\*60 freeform | OK | OK | 31898 | 31898 | no |
| universe-matrix\*60 sequence-pair | OK | OK | 22032 | 22032 | no |
| quantum-chip\*180 freeform | OK | OK | 14896 | 14896 | no |
| quantum-chip\*180 sequence-pair | REFUSED (deadline) | REFUSED (deadline) | -- | -- | no |

`seating_delta.py` on the `test_reported_sequence_output_products_keeps_machine_inputs_separate`
URL reports **0 of 26 families moved**, which is the shape of the guard for every spec that
already seats servably.

Full suite: `uv run pytest -q -p no:randomly tests` leaves two failures,
`test_two_stage_alignment_retains_cp_sat_direct_opportunity` and
`test_all_products_sequence_pair_honours_the_exact_layout_deadline`, both of which fail
identically at `c3cf24ef` with the fix reverted in the same tree (checked). `ruff check`,
`ruff format --check` and `mypy src` are clean.

## 7. What remains

The predicate is a **model** of the seating, not a replay of it, and it is wider of production in
four ways. None of them can raise an error: it only steers `_seat_inputs` between splits it would
otherwise take in order, and a split it judges wrongly is one the fallback pass takes anyway.

- **Yaw.** Production tries every yaw in `_CARDINAL_YAWS` and keeps the first output-side
  assignment that yields a variant at *any* of them; the predicate reads `lane_reach_profiles` at
  `group.yaw` alone. 8 of the 18 machine types have yaw-varying profiles (Chemical Plant, Quantum
  Chemical Plant, Oil Refinery and Miniature Particle Collider among them), so the assignment
  judged here can differ from the one shipped -- a different seating, never a failure.
- **Slot matching.** Production seats items into slots through `_match_attachment_plans`; the
  predicate only counts a row's attachments and charges every item on the lane the row's
  *shortest* span. It also ignores port docks, box height and pitch, which production's break
  depends on.
- **Variant selection.** The predicate asks only that *some* seating of the judged assignment is
  servable; `default_strip_variant` picks by `sort_key`, not by servability. A family whose
  default variant is unservable while a sibling is would still be convicted downstream. Not
  observed on this URL or the corpus.
- **Generosity.** The shortest span and the lane's full planned stack mean the preference can
  accept a split the validator still convicts. That is deliberate -- it degrades to today's
  behaviour -- but it is why this is not a proof of servability.

Beyond the model:
- A lane that genuinely cannot be served from any row is still reported late, by
  `flow.sorter_capacity`, after the budget is spent. Turning that into an early structured
  refusal (the shape `BuildSpec.planning_stack` uses for the Pile Sorter) is a separate change and
  would want its own before/after, since it changes what a refusing corpus cell reports.
- `_seat_both_fed_outermost` remains rate-blind; it is the *reason* the outermost row was chosen,
  and this fix works around it by choosing a split whose outermost row is closer, not by relaxing
  it. A both-fed lane whose rate exceeds the closest available outer row is still unbuildable.
- Every stack-dependent branch of the predicate is inert at `belt_stack == 1`, which is every
  corpus URL and this one, so the corpus guard cannot exercise it. The three `belt_stack > 1`
  unit tests in `tests/layout/test_strip_variants.py` are what cover it, and each was checked
  against a mutant restoring the pre-review behaviour.

## Files

- `characterise.py` / `characterise.txt` -- save, ladder, stacks, per-lane demand
- `lane_seating.py`, `lane_seating_before.txt`, `lane_seating_after.txt` -- per-lane row, span,
  rate, chosen tier and capacity for every family of every candidate
- `variant_search.py`, `variant_search_before.txt` -- servable-variant count per family, and the
  machine's reach profiles at all four yaws
- `seating_delta.py` -- which families a spec's seating moves under the preference
- `repro_before.txt`, `repro_after.txt` -- the CLI runs
- `guard/*.json` -- the corpus guard rows
