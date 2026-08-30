# Which layout strategy is denser — A (spine) or B (freeform)?

**Status: the comparison cannot yet be made over the corpus. The harness is
built, guarded, and cross-validated; the corpus coverage is not there yet.**
Numbers below are provisional and labelled as such.

Run it yourself:

```
uv run python scripts/ab_compare.py --tier small --budget 1,4 --repeat 3
uv run python scripts/ab_compare.py --tier mid --repeat 5 --markdown docs/AB_RESULTS.md
```

Current comparison runs are always powered. There is no power-mode selector;
the persisted `power: true` field is constant historical-schema metadata.

The harness is `src/flab2bp/bench/ab.py` (measurement engine, unit-tested in
`tests/bench/test_ab.py`) driven by `scripts/ab_compare.py`. It is deliberately
**not** part of `pytest`: a full sweep is minutes of CP-SAT and the suite stays
at ~21s.

---

## Why this harness exists

An earlier comparison in this project concluded **"A wins, geometric mean
1.359"** and it was an artifact. The harness was scoring layouts the validator
had rejected, and invalid layouts are *systematically smaller*: an unrouted net
is a belt run that does not exist, so the broken layout has the tighter bounding
box and wins on area. One build with **119 unrouted nets** measured as the
densest candidate on offer.

That failure mode is not noise. It reliably crowns whichever strategy is more
broken, which is the exact opposite of what the measurement is for. So this
harness is not "collect numbers and average them"; it is a set of structural
guards, each closing one route back to that conclusion.

---

## The guards, and what each is for

### 1. A rejected layout cannot hold an area

`Sample.__post_init__` raises if a non-`VALID` sample carries geometry, and
raises if a `VALID` one does not. This is a constructor invariant, not a filter
some later refactor can drop: there is no object in the system pairing a
rejected layout with an area, so no aggregate can consume one by accident.
`Sample.demoted()` re-grades and clears the geometry in one step, so a
downgrade cannot forget to un-count the area.

Pinned by `test_a_rejected_sample_cannot_carry_an_area`,
`test_a_tiny_invalid_candidate_never_beats_a_larger_valid_one`.

### 2. Four failure modes, kept apart

| Outcome | Meaning | What it indicts |
| --- | --- | --- |
| `REFUSED` | `NoValidLayout` — the strategy searched and found nothing routable | a structural gap in the strategy (or a genuinely hard instance) |
| `INVALID` | it returned a placement the validator rejected | the strategy emits something that will not run |
| `ERROR` | it raised something that was not `NoValidLayout` | a plain bug in us |
| `CROSSFAIL` | our validator accepted it, encoding or the game's own decoder did not | the encoder, or our model of the format |

A single blank cell for all four would make "B has a known structural gap" and
"B raised `AttributeError`" look identical. When one URL's candidate sweep fails
in several ways, the *worst news* is reported: `CROSSFAIL > ERROR > INVALID >
REFUSED`, so a crash is never hidden behind a refusal that also happened.

Pinned by `test_refused_invalid_and_error_are_counted_separately`,
`test_a_crash_is_never_hidden_behind_a_refusal`.

### 3. Coverage before density, denominators always

`Comparison.headline()` prints coverage **first** and the density line names the
subset it describes: *"DENSITY (paired, denominator: 1/3 URLs where BOTH
shipped)"*. When the two strategies differ on coverage it says so explicitly —
a strategy that refuses half the corpus is not "denser", whatever the median of
the other half says. When nothing is shared, `geo_mean` is `None`, not `1.0`:
"they tied" and "no comparison was possible" are different claims.

Coverage is reported at two strengths, because they answer different questions:

* **covered** — at least one repeat shipped a valid layout.
* **on every repeat** — all repeats shipped. A strategy that works 1 run in 5
  is not fixed, and multi-worker CP-SAT makes that distinction real.

A URL whose spec would not even resolve still occupies a row for both
strategies. Dropping it would make a broken URL look like a URL nobody ran and
shrink the denominator silently.

Pinned by `test_coverage_is_reported_before_density_with_both_denominators`,
`test_no_shared_success_means_no_ratio_at_all`,
`test_a_url_that_never_ran_still_counts_in_the_denominator`,
`test_reliability_is_distinct_from_coverage`.

### 4. Nondeterminism is measured, not averaged away

The shipping default is multi-worker CP-SAT, which is deliberately
nondeterministic — it is worth ~23% density over a single worker, so pinning the
worker count would measure a configuration neither strategy would ship. One
sample per cell is therefore noise.

`--repeat` takes N samples per cell and the report carries:

* the **median** area and the observed **[min–max]** interval per cell;
* a per-URL **separation** test — the honest B/A interval is
  `[min(B)/max(A), max(B)/min(A)]`, and if that interval straddles 1.0 the URL
  has *no verdict at this sample size*, whatever its medians say;
* a **noise floor** per strategy: median `(hi − lo) / median` across cells. If
  the headline effect does not exceed it, the report says so in as many words:
  *"the effect does NOT clear the solver's own run-to-run variation. Treat it as
  no difference."*
* a **sign count** (`spine N, freeform M, tie K`) over separated pairs only,
  which survives one enormous stress case in a way a mean of ratios does not.

With `--repeat 1` nothing can ever be declared separated, and the report then
prints *"NOTHING is separated from noise at this sample size. The ratio above
has no support; raise `--repeat` before quoting it."* right under the ratio —
deliberately as loud as the ratio itself, because quoting an unsupported number
is exactly how the last wrong answer travelled.

Pinned by `test_one_sample_per_cell_can_never_be_declared_separated`,
`test_overlapping_spreads_are_not_a_verdict`,
`test_an_effect_inside_the_noise_floor_is_called_out`,
`test_wins_are_counted_only_over_separated_pairs`.

### 5. The time budget is treated as a confound, not a setting

A strategy that uses its budget better looks denser at 2s and worse at 10s.
`--budget 1,4,10` sweeps it and `budget_flip()` reports whether the winner
changes. If it does, the honest headline is *"it depends on the budget"* and no
single-budget number is the result.

Pinned by `test_a_winner_that_flips_with_the_budget_is_reported_as_such`.

### 6. Cross-validation against the game's own format

Every blueprint the harness would report as valid is encoded exactly as
`pipeline.build` would emit it (external-input markers included) and decoded by
the independent TypeScript decoder in `../dsp-blueprint-viewer` via `bun`, in
one subprocess for the whole run. A blueprint is only accepted if it

1. decodes,
2. carries a valid **MD5F** hash, and
3. reports **the same building count** we placed.

Check 3 is the one our own validator structurally cannot do: we validate the
`Placement`, the decoder validates the bytes, so only the second notices an
encoder that dropped or duplicated a building. Anything failing is **demoted to
`CROSSFAIL`, which drops its area** — a layout the game's format rejects is not
a win, so it must not contribute to a density claim.

When `bun` or the viewer checkout is missing, the report says
`cross-validation SKIPPED (…)`. Zero failures with the tool absent must never
read as "everything passed".

Pinned by `test_a_missing_toolchain_reads_as_skipped_not_as_a_pass`,
`test_cross_verdict_rejects_what_the_game_format_would`,
`test_a_blueprint_the_decoder_rejects_stops_contributing_an_area`.

### 7. A skipped check is not a passed check

The harness always passes the `BuildSpec` **and** its id map to the validator.
Without them, nine spec-conformance and flow checks silently skip, and
`report.ok` degrades to "no check that ran failed" — a build that never ran its
throughput checks reads as clean. Any unexpected skip fails the sample.

Power checks are included in that policy. Current runs pass
`expect_power=True`, so a skipped `power.*` check is an unchecked powered build
and fails the sample rather than being tolerated as an off-mode declaration.

### 8. Fairness of the run itself

* Both strategies get the **same `BuildSpec` objects**, resolved once per URL
  and shared.
* Every candidate is laid out by both strategies and the **smallest valid**
  result wins, exactly as `pipeline.build` does. Picking the candidate with
  fewest machines up front would be cheaper and wrong: proliferation cuts
  machine count but forbids direct insertion on the sprayed edges, so fewer
  machines can still lay out larger.
* Loop order is `budget → trial → url → candidate → strategy`, so A and B are
  measured **back-to-back on identical inputs**. Thermal throttling, other load
  on the machine, and drift over a long sweep move both together instead of
  landing on whichever ran second.
* Nothing is self-reported. Geometry comes from
  `flab2bp.bench.metrics.measure()`, which reads the buildings, never
  `Placement.stats`.

### 9. Area is the headline, not the whole report

Alongside area the report carries, per paired URL:

* **building count** — what decides how unpleasant the blueprint is to paste,
  and currently 1224–1925 buildings on the magnetic-ring spec because lanes run
  the full content width;
* **belt tiles vs direct inserts** — *why* one strategy won. A belt run replaced
  by a single sorter is denser and cheaper at the same time, so a win driven by
  direct insertion is a different result from a win driven by tighter packing.
* wall-clock median per cell.

---

## Provisional results

**Measured against the working tree while all three of `spine.py`,
`freeform.py` and `validate.py` were mid-rewrite. These numbers describe an
hour, not a design.** Re-run before quoting any of them.

```
uv run python scripts/ab_compare.py --tier small --budget 1,4 --repeat 3
# 180 samples, 167s wall
```

### The answer today: the comparison cannot be made

```
COVERAGE at budget=1s and 4s (denominator: 5 URLs attempted)
  spine      valid on 2/5 URLs (2/5 on every repeat)
  freeform   valid on 3/5 URLs (3/5 on every repeat)
DENSITY (paired, denominator: 2/5 URLs where BOTH shipped)
  geometric mean B/A = 0.921   -> freeform 7.9% denser over those 2 URLs
  separated on 2/2: spine 0, freeform 1, tie 1
```

The two paired URLs are `iron-ingot` (**one** machine, an exact 15-vs-15 tie)
and `magnetic-coil` (**four** machines, 99 vs 84). The entire 7.9% is one
4-machine spec. That is not an answer to "which strategy is denser"; it is one
data point that happens to have survived.

Per-sample outcomes, 90 samples per strategy (5 URLs x 3 candidates x 3 repeats
x 2 budgets):

| | VALID | INVALID | REFUSED | ERROR | CROSSFAIL |
| --- | --- | --- | --- | --- | --- |
| spine | 24 | 66 | 0 | 0 | 0 |
| freeform | 30 | 36 | 24 | 0 | 0 |

The two strategies fail differently, which the old single-blank-cell report
could not have shown: spine returns something the validator rejects, freeform
increasingly declines to return anything. Both failure sets are dominated by
`flow.lane_sourced` — the exact gap `docs/BACKLOG.md` describes as BLOCKING
(neither strategy can serve two destinations from one belt; spine never joins an
item's corridor copies). Spine's failures additionally carry
`machine.inputs_supplied`, `machine.output_removed` and `sorter.endpoints`.

### The candidate frontier is almost entirely broken

Grouping the same run by candidate is the most useful thing in it:

| candidate | spine | freeform |
| --- | --- | --- |
| `no-proliferator` | valid on 2/5 URLs | valid on 3/5 URLs |
| `free-proliferation` | valid on 1/5 (`iron-ingot` only) | valid on 1/5 (`iron-ingot` only) |
| `max-proliferation` | valid on 1/5 (`iron-ingot` only) | refuses 4/5, valid on 1/5 |

Every proliferated candidate fails on every spec with an internal edge.
`iron-ingot` passes only because a lone smelter has no internal edges to spray.
So today's comparison is not "spine vs freeform" — it is **spine vs freeform on
the `no-proliferator` candidate**, on 2 of 12 corpus URLs. The report calls this
out per URL (`only 1/3 candidates laid out`).

This also disarms the direct-insertion axis before it can be measured:
`free-proliferation` exists precisely so internal edges stay eligible for direct
insertion (`docs/BACKLOG.md`), and it currently never lays out.

### Composition

| spec | A blds | B blds | A belt | B belt | A direct | B direct |
| --- | --- | --- | --- | --- | --- | --- |
| iron-ingot | 9 | 9 | 6 | 6 | 0 | 0 |
| magnetic-coil | 51 | 54 | 39 | 40 | 1 | 0 |

Spine wins building count and belt tiles on `magnetic-coil` while losing area by
15%, and it is the only side emitting a direct insert at all. Even on the one
spec that produced a number, "denser" and "cheaper to paste" disagree.

### The budget sweep is currently inoperative

Median wall-clock per sample was **identical at `--budget 1` and `--budget 4`**
(spine 0.012s, freeform 0.135s at both), and every area was identical too. The
budget knob cannot discriminate here because these specs finish — or fail — long
before the budget binds. Worse, freeform's *failing* path took up to **13.5s
against a 1s budget**, so on the path that does consume time the budget is not
being honoured either. Until a spec exists that both strategies solve and that
actually consumes its budget, guard 5 is armed but has nothing to measure.

### Nondeterminism did not appear

Every valid cell produced a **byte-identical area across all 3 repeats** — noise
floor 0.0% for both strategies. That is not evidence that multi-worker CP-SAT is
deterministic; it is evidence that the only specs currently laying out are 1 and
4 machines, small enough to be solved to optimality every time. The repeat
machinery is untested against the noise it exists for, because the specs where
that noise lives all fail first.

### A mid-tier run, and the ERROR outcome earning its keep

A second run an hour later (`--tier mid --only
processor,energy-matrix,super-magnetic-ring --budget 4 --repeat 2`) caught
`spine.py` in a broken intermediate state:

```
COVERAGE at budget=4s (denominator: 3 URLs attempted)
  spine      valid on 0/3 URLs
  freeform   valid on 2/3 URLs
DENSITY: no comparison possible -- 0 URLs where both strategies shipped.

processor              -  0/2      480  2/2      -    -   0.1s  16.0s
    spine: error x2 (TypeError: unsupported operand type(s) for +: 'int' and 'lis)
energy-matrix          -  0/2      418  2/2      -    -   0.0s   2.1s
    spine: error x2 (TypeError: ...)
super-magnetic-ring    -  0/2        -  0/2      -    -   0.5s  68.6s
    spine: error x2 (TypeError: ...)
    freeform: invalid x2 (flow.external_entry_reachable,geom.belt_single_occupancy)
```

This is worth keeping only as a demonstration of guard 2. A harness that
collapsed the failure modes would have printed "freeform wins, covers 2/3 vs
0/3" — a *coverage* claim built entirely on a `TypeError` in a file someone was
editing. Naming it ERROR makes it obviously not a result about spine's design.
`super-magnetic-ring` — the project's own reference case — produced nothing from
either side, and freeform spent 68.6s against a 4s budget doing so.

### Cross-validation: the one unambiguously good result

**54/54** blueprints in the small-tier run, and **6/6** in the mid-tier run,
decoded by the independent TypeScript decoder in `../dsp-blueprint-viewer` via
`bun` — all with a valid **MD5F** hash and a building count matching what we
placed. Zero demotions. Whatever else is wrong, the encoder and the game's
format agree on everything the harness accepted.

### What this adds up to

Neither strategy covers enough of the corpus to compare. The honest headline is
**"no verdict"**, and the two numbers worth acting on are the coverage figures
(2/5 and 3/5) and the candidate table, not the 0.921.

For this to become a real answer, the BLOCKING item in `docs/BACKLOG.md` has to
land — the splitter primitive in `layout/junction.py`, plus spine's riser
geometry — so that `flow.lane_sourced` stops being the universal failure. After
that, the proliferated candidates have to lay out, or the frontier is decoration
and the direct-insertion axis stays unmeasurable. Then re-run at `--tier mid
--repeat 5 --budget 2,10`, which is the first configuration where the
nondeterminism and budget guards will have anything to bite on.

---

## Confounds

### Controlled

| Confound | How |
| --- | --- |
| Invalid layouts measuring smaller | validity gate as a constructor invariant (guard 1) |
| Refusal counted as a loss / a crash | four distinct outcomes (guard 2) |
| Ratio over an unstated subset | denominators mandatory, coverage printed first (guard 3) |
| Multi-worker CP-SAT nondeterminism | repeats, spreads, separation test, noise floor (guard 4) |
| Time budget favouring one strategy | budget sweep + explicit flip detection (guard 5) |
| Our validator being wrong about the format | independent decoder, hash + building count, demotion (guard 6) |
| Checks silently not running | spec + id map always passed; unexpected skips fail (guard 7) |
| Different inputs, different candidate choice | shared specs, pipeline-identical candidate reduction (guard 8) |
| Machine drift over a long sweep | A and B run back-to-back within each trial (guard 8) |
| Strategies marking their own homework | geometry measured from buildings, never `stats` (guard 8) |
| Area hiding a worse blueprint | building count and belt/direct composition reported (guard 9) |

### Not controlled

* **Both strategies are being rewritten as this is measured.** Today's numbers
  describe today's `spine.py`, `freeform.py`, and `validate.py`, all of which
  are mid-change. They are provisional in the strongest sense.
* **The validator is the arbiter of "valid", and it has known gaps.** Two are
  documented in `docs/BACKLOG.md`: `flow.lane_sourced` excuses any run carrying
  an external item rather than only the run the input enters on, and an orphaned
  belt run whose consumers happen to have another source is graded a WARNING
  rather than an error. Both are *permissive*, so they can only let a bad layout
  through, never fail a good one — but a strategy whose failures land in those
  blind spots will look better than it is. The cross-validation does not help
  here: it checks the bytes, not the logistics.
* **Selection effect on the paired subset.** The URLs where both strategies
  succeed are, by construction, the easy ones. A ratio computed there does not
  extrapolate to the specs one of them refuses, and the report says so rather
  than pretending otherwise.
* **Small corpus.** Twelve URLs, and the paired subset is smaller still. A sign
  count over a handful of URLs is weak evidence even when every URL is
  separated.
* **`tile_to_local_offset` is unverified against the actual game.** The decoder
  agrees with our encoder on bounds and item histograms, which pins the
  centre-vs-corner rule only indirectly. A real paste settles it; until then
  "the format accepts it" is not "the game builds it".
* **Machine, not cluster.** Wall-clock numbers and therefore the effective
  budget depend on this laptop's core count and thermal state. The *area*
  numbers depend on it too, through how much search fits in the budget.
* **`bench/runner.py` and `bench/scoring.py` are a second, older path** to a
  similar answer. `runner.py` has been fixed to pass the spec to the validator
  and to survive refusals, but `scoring.compare` still ranks on
  `CellResult.valid` rather than `verified`, and it has no notion of repeats,
  spread, or cross-validation. Treat `ab.py` as the authority; the older path is
  for the regression baseline.
