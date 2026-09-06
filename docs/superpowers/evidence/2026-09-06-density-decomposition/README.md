# Decomposing freeform's density: belt sharing, direct insertion, packing

## Answer

**Neither of the two hypothesised mechanisms carries freeform's density; packing
does. Belt sharing carries FEASIBILITY instead, and direct insertion is inert.**
Measured pairwise on the freeform cells each configuration and the baseline both
build, the geomean area ratio against baseline is **0.9943 for no-direct-insert**
(36 of 36 cells), **1.0036 for no-belt-sharing** (24 of 36) and **1.0036 for
neither** (24 of 36) — so on the cells that can be compared, turning both off
costs 0.4% of area and everything else, 99.6%, is packing tightness. Both
numbers sit inside the measured noise: the direct-insert switch moves the cells
where it *cannot* matter (no direct-insert candidate at all) by 0.9950, and a
pure re-run control — the sequence-pair arm, which the direct-insert switch does
not reach — moves by 1.0103 with one cell at 1.201. But the comparison is only
available on small cells, because **belt sharing is load-bearing for
feasibility**: with it off, 12 of 36 freeform corpus cells and **all five large
cells refuse** ("no packing of N strips could be wired at any candidate height"),
and the 24 survivors are 18 tiny plus 6 mid cells with no large cell among them
(sequence-pair, which shares the same router, loses 10 of 36 the same way).
Direct insertion is not merely small, it is **never realized**: `direct_inserts`
is 0 on all 36 corpus cells and all 5 large cells, even though 19 cells offer 236
candidates — the switch measures the packer's direct-insert *reward*, not any
built machine-to-machine hand-off, and that reward is worth 10.3% of area on
exactly one measured cell (`quantum-chip@180`: 14896 with, 16434 without). The
interaction term is nil: geomean(neither) 1.0036 against
geomean(no direct) x geomean(no sharing) 1.0035, i.e. +0.0002.

**For a block-based solver:** a block that keeps sharing and direct insertion
inside itself and shares only trunk ingredients between blocks would keep
essentially all of today's density, because today's density is not in those two
mechanisms. The real constraint is the other way round: the router as built
*cannot wire a lane that serves more than one consumer without branching off a
sibling's run*, so any inter-block trunk feeding two blocks still needs exactly
the `_merge_frontier` machinery — dropping it between blocks would not cost area,
it would cost buildability. And the sharing that exists is sparse: a baseline
`universe-matrix` build wires 67 nets with 6 Splitters, `quantum-chip` 26 nets
with 7 (`sharing-probe.json`; destination-side merges build no Splitter, so that
is a lower bound). Sharing is used rarely and at load-bearing points, which is
the good news for blocks — a block boundary has few of them to preserve.

## Method

Four configurations, identical in every other respect, at budget 30, on the
72-cell corpus (`scripts/audit.py --budget 30`, both arms) and on five large
freeform cells (`prof_harness.py`):

| name | switch | file |
| --- | --- | --- |
| `base` | production defaults | - |
| `nodirect` | `FLAB2BP_SPIKE_NO_DIRECT=1` | `audit-nodirect.jsonl` |
| `noshare` | `FLAB2BP_SPIKE_NO_SHARING=1` | `audit-noshare.jsonl` |
| `neither` | both | `audit-neither.jsonl` |

**Nothing under `src` was changed.** The switches are monkeypatches in
`sitecustomize.py` in this directory, reached by putting this directory on
`PYTHONPATH`. That mechanism (rather than a patch in the parent process) is
required: `scripts/audit.py:806` fans cells out over a `ProcessPoolExecutor` and
Python 3.14 starts those children with **forkserver**, so a parent-side patch
would never reach the process that lays a cell out. `_probe_workers.py` proves
the switches do reach a pool child:

```
parent: forkserver
child: ('forkserver', False, 'no_frontier', 'unshared_external_inputs')   # both switches on
child: ('forkserver', True, '_merge_frontier', '_plan_shared_external_inputs')  # off
```

### The exact switches

* **direct insertion** — forces the production flag
  `FreeformLayout(direct_insert=False)` (`src/flab2bp/layout/freeform.py:19415`),
  read at `freeform.py:19942` and `freeform.py:20330` as
  `_direct_candidate_snapshot(strips, spec, enabled=self.direct_insert)`
  (`freeform.py:3390`). With it false the candidate map is empty, so the packer
  is rewarded for no adjacency, `pack.direct` is empty (`freeform.py:16304`) and
  `_bridge` is never attempted (`freeform.py:16338`). Freeform only:
  sequence-pair's direct insertion is `sequence_pair.align_direct_inserts:1091`
  and has no switch, so the sequence-pair `nodirect` rows are a pure re-run and
  serve as this spike's **noise control**.

* **belt sharing** — two halves:
  1. `freeform._merge_frontier` (`freeform.py:8907`) returns the empty set. It
     is the only producer of "free cells beside a sibling net's path": the
     source-side branch points for `src_group` (nets leaving the same
     item+domain+lane, `freeform.py:9517`) and the destination-side merge points
     for `dst_group` (nets arriving at the same lane tile, `freeform.py:9503`).
     Call sites: `freeform.py:10007` (source), `freeform.py:10053`
     (destination), `freeform.py:11101` and `freeform.py:11136` (look-ahead).
     With it empty every net must start on its own port access cell and end on
     its own sink — no two nets can come to share one run.
  2. `freeform._plan_shared_external_inputs` (`freeform.py:15943`) is called
     with `belt_stack` forced to 1, taking its stack-one early return
     (`freeform.py:15970`) so no shared perimeter trunk is planned and
     `_place_shared_external_input_trunks` (`freeform.py:16064`) places none.

  This switch reaches sequence-pair too, which imports `_prepare_routing_problem`
  from freeform (`sequence_solver.py:74`) and shares the detailed router.

  **Half of it is inert here.** Every measured spec has `belt_stack == 1`
  (verified: all 12 corpus URLs and the belt3 URL), so half (2) never fires and
  every effect below is `_merge_frontier` alone.

### Validity

`audit.py` validates every placement it accepts; across all four configurations
and both arms there were **0 INVALID cells**. Where separate routing makes a
cell unbuildable the audit records REFUSED, and those are counted as refusals
below rather than as areas.

### Load

Box load at the start of the corpus runs is in `load-at-start.txt` (a shared,
disk-bound 128-core box, never idle). The four corpus runs took 198s, 196s, 194s
and 195s wall.

## Results

Full generated tables: `tables.md` (regenerate with `python3 analyze.py`).

### Status counts (72 cells per configuration, budget 30)

| arm | configuration | CLEAN | REFUSED | INVALID |
| --- | --- | --- | --- | --- |
| freeform | baseline | 36 | 0 | 0 |
| freeform | no direct insert | 36 | 0 | 0 |
| freeform | no belt sharing | **24** | **12** | 0 |
| freeform | neither | **24** | **12** | 0 |
| sequence-pair | baseline | 35 | 1 | 0 |
| sequence-pair | no direct insert | 35 | 1 | 0 |
| sequence-pair | no belt sharing | **26** | **10** | 0 |
| sequence-pair | neither | **26** | **10** | 0 |

The 12 freeform refusals, all of them with sharing off and all of them the same
under `neither`:

| url_id | spec | machines |
| --- | --- | --- |
| information-matrix | no-proliferator | 97 |
| information-matrix | all-products | 56 |
| information-matrix | output-products | 84 |
| processor | no-proliferator | 21 |
| processor | output-products | 20 |
| quantum-chip | no-proliferator | 87 |
| quantum-chip | output-products | 76 |
| super-magnetic-ring | no-proliferator | 58 |
| super-magnetic-ring | output-products | 52 |
| universe-matrix | no-proliferator | 224 |
| universe-matrix | all-products | 113 |
| universe-matrix | output-products | 193 |

Every one of them refuses with a routing reason, not a packing one: *"no packing
of N strips could be wired at any candidate height; every pack the sweep produced
left nets unrouted"* (one cell instead ran out of the 30s budget after 4 packs).
That is the mechanism working as documented at `freeform.py:9509` — an out-lane
sandwiched between its neighbours is reachable only at its ends, so the second
and later consumers of a producer lane MUST branch off a sibling's path.

### Area ratio against baseline, on the cells both configurations build

| arm | configuration | cells | geomean area | median | max | geomean belt_tiles |
| --- | --- | --- | --- | --- | --- | --- |
| freeform | no direct insert | 36 | **0.9943** | 1.000 | 1.078 | 0.9923 |
| freeform | no belt sharing | 24 | **1.0036** | 1.000 | 1.091 | 1.0030 |
| freeform | neither | 24 | **1.0036** | 1.000 | 1.091 | 1.0089 |
| sequence-pair | no direct insert (control) | 35 | 1.0103 | 1.000 | 1.201 | 0.9988 |
| sequence-pair | no belt sharing | 26 | 1.0137 | 1.000 | 1.378 | 1.0074 |
| sequence-pair | neither | 26 | 1.0124 | 1.000 | 1.378 | 1.0116 |

On the 24 cells clean in all four configurations (quartiles): every
configuration has Q1 = median = Q3 = 1.000. Only one of the 24 moves at all
under `noshare` — `quantum-chip/all-products`, 3840 -> 4189 (1.091, belts
2602 -> 2685). Interaction: geomean(neither) 1.0036 vs the product of the two
singles 1.0035, **+0.0002**.

By cell size, over those 24 (18 tiny, 6 mid, 0 large — the large ones all
refuse):

| class | cells | no direct insert | no belt sharing | neither |
| --- | --- | --- | --- | --- |
| tiny (<=10 machines) | 18 | 1.0000 | 1.0000 | 1.0000 |
| mid (11-60) | 6 | 0.9993 | 1.0146 | 1.0146 |

### Direct insertion is never realized

* **0 of 36** clean baseline freeform cells realize a direct insert
  (`direct_inserts` = 0 everywhere, corpus and large cells alike).
* 19 of 36 cells offer at least one candidate, 236 candidates in total.
* Internal control — the cells where the switch **cannot** matter move as much
  as the cells where it can:

| subset | cells | geomean area (no direct / base) | cells whose area moved |
| --- | --- | --- | --- |
| candidates == 0 (switch cannot matter) | 17 | 0.9950 | 2 |
| candidates > 0 (switch can matter) | 19 | 0.9936 | 4 |

So the corpus-level `0.9943` is noise, not signal. The one place the switch
visibly bites is a large cell, and there it costs area to remove:
`quantum-chip@180` builds 14896 with the reward and 16434 without (**1.103**),
on *fewer* belt tiles (4902 vs 4466) — the packer's direct reward buys a tighter
pack even though no bridge is ever built.

### Large freeform cells (`prof_harness.py`, budget 30; belt3 at budget 60)

| cell | machines | baseline | no direct insert | no belt sharing | neither |
| --- | --- | --- | --- | --- | --- |
| universe-matrix@60 | 224 | 31898 | 31898 (1.000) | **REFUSED** | **REFUSED** |
| universe-matrix@120 | 439 | 80496 | 80496 (1.000) | **REFUSED** | **REFUSED** |
| gravity-matrix@200 | 349 | 48640 | 48640 (1.000) | **REFUSED** | **REFUSED** |
| quantum-chip@180 | 252 | 14896 | 16434 (**1.103**) | **REFUSED** | **REFUSED** |
| belt3 (all-products) | 280 | 15207 | 15207 (1.000) | **REFUSED** | **REFUSED** |

All five refuse with the same routing reason as the corpus cells. Four of the
five are bit-identical between `base` and `nodirect`, which also says the
harness path is deterministic at this budget — so `quantum-chip@180`'s 1.103 is
a real effect of the switch, not a re-run difference.

### How much sharing is there to begin with (`sharing-probe.json`)

| probe cell | machines | nets | Splitters | belt_tiles | area |
| --- | --- | --- | --- | --- | --- |
| universe-matrix@60 | 330 | 67 | 6 | 14874 | 39710 |
| quantum-chip@180 | 432 | 26 | 7 | 7582 | 25608 |
| processor@60 | 25 | 7 | 0 | 445 | 1008 |

(These probe URLs use the full machine ranking rather than `prof_harness`'s fast
rank, so the machine counts differ from the table above; the point is the ratio
of Splitters to nets, not the absolute size.) A Splitter is the physical trace
of a SOURCE-side branch; a destination-side merge builds no building, so these
are a lower bound. Sharing is sparse and concentrated.

## Files

| file | what |
| --- | --- |
| `sitecustomize.py` | the switches (throwaway; loaded via `PYTHONPATH`) |
| `run_corpus.sh` / `run_corpus.log` | the four 72-cell audit runs |
| `run_large.sh` / `run_large.log` | the four x five large-cell harness runs |
| `audit-{base,nodirect,noshare,neither}.jsonl` | raw per-cell rows |
| `large/*.json`, `large/*.log` | raw harness output per cell and configuration |
| `analyze.py` / `tables.md` | the analysis and its full output |
| `probe_sharing.py` / `sharing-probe.json` | Splitter and net counts in baseline builds |
| `_probe_workers.py` | proof the switches reach a forkserver pool child |
| `load-at-start.txt` | box load when the corpus runs began |

## Concerns

1. **The sharing arm is a feasibility measurement, not a density one.** Every
   cell where sharing could plausibly buy area refuses without it, so no area
   ratio exists for the large cells. The 1.0036 geomean is a statement about 18
   tiny and 6 mid cells only.
2. **Direct insertion could not be measured as intended** because it is never
   realized anywhere in this corpus at these budgets. What the switch measures
   is the packing objective's direct-insert reward.
3. **The shared-external-trunk half of the sharing switch never fires** — all
   measured specs are `belt_stack == 1`. A stacked-bus URL would be needed to
   measure it.
4. **A refusal is budget-sensitive.** These are 30s cells; a bigger budget might
   let some of the 12 wire without sharing, by finding a pack whose lanes are
   reachable end-on. The refusal reason ("every pack the sweep produced left
   nets unrouted") says the packs on offer were all unwireable, not that time
   ran out, in 11 of the 12.
5. `_merge_frontier` returning empty also blanks the two look-ahead probes at
   `freeform.py:11101`/`11136`, which use it to price alternative paths. Those
   probes exist to serve future branches, so blanking them is consistent with
   "no branches", but it means the no-sharing arm is slightly more crippled than
   a hypothetical router built from the start without sharing.
