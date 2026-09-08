# Indexed-scans — Task 30 evidence report

## 1. Verdict

**NO — the original strict byte/area-identity bar is not met: original controls are 11/12 MATCH and the paired corpus has 12 area differences; the separate serial quantum-chip pair MATCHES.**

This completes the prescribed **report**, not a clean final integration gate. Final corpus/control evidence describes frozen preintegration candidate **`1ca2495f6c86f96bf13053dbac6dbb134e57a2ab`** versus pinned **`2e861af02b6a5062792f8d21fca009b64aee5ab6`**. Earlier diagnostic timings below retain their actual earlier SHAs; they are not remeasurements at `1ca2495f`. Nothing here measures the later Buildings delegation or final combined master.

The original I-5/I-6 policy required measured improvement or documented de-duplication and rejected neutrality differences. The user's later ruling superseded marginal timing/retention queues, restored Task22, and allowed Tasks24/26/28 without waiting for Tasks25/27/29 microbenchmark decisions. **UNMEASURED is not “zero cost” or “did not move the clock.”** Historical rejections and failed comparisons remain evidence. Actual correctness, ordering/RNG, default-contract and deadline failures remain gates; this report neither dismisses differences as noise nor requests new marginal keep/revert measurements.

Evidence notation: **L** means this worktree's `.superpowers/sdd/2026-09-07-indexed-scans/`; **C** means [`final-correctness-VsyHfZ3l/`](final-correctness-VsyHfZ3l/). **B** is the repository-root-relative `.claude/worktrees/buildings-index/docs/superpowers/evidence/2026-09-07-buildings-index/parallel-correctness-AWM9wmPE/before/`, reused at the matching pinned baseline/operating point. `C/provenance.json` records both boundaries. The older `master-baseline.{jsonl,log}` remains archived but is not silently substituted for B.

## 2. What moved the numbers

No final whole-build speedup is established. File/line references in site tables are the scout's **baseline** coordinates, not current shifted source lines. Measurements are separated from unmeasured retained conversions.

| Site / baseline file:line | Workload and evidence | Before → after seconds | Scope / result |
|---|---|---|---|
| #5 `layout/global_router.py:79-107` | Complete capacity writes plus reads, 5 samples ×100 workloads; L/capacity-trace-{baseline,candidate}.json | Median 1.315105 → 0.530491 | Ratio 0.403383; `2e861af0`→`f3298f48`; CPU pressure 7.0→3.2. Microbenchmark, not cProfile cumulative time or whole-build speed. |
| #35 `layout/hierarchy/partition.py:200-226` | Actual 18-block universe-matrix/no-proliferator graph; construction+order, 3 samples ×1000; L/block-graph-after.json | Median inline 0.036362 → actual wrapper 0.024204 | Ratio 0.665635 at `f3298f48`, CPU pressure 8.4; all 36 real graphs faster. Not per-build cumulative time. |
| #42 `web/trace.py:147-163` | Complete append/poll workloads, 5×100; L/capacity-trace-{baseline,candidate}.json | Median 0.220398 → 0.090438 | Ratio 0.410338; `2e861af0`→`f3298f48`; CPU pressure 3.6→5.2. No whole-web/build claim. |
| #4 `layout/sequence_pair.py:1476-1481` | Historical Task23 cProfile: magnetic-coil; processor; universe-matrix | Cumulative 4.181643→4.300150; 2.158270→2.302360; 0.809629→0.586673 | Calls 132000→138000; 52000→60000; 12000→8000. Per-call changes −1.6%/−7.5%/+8.7%; mixed, not a consistent win. |
| #24 `layout/sequence_pair.py:2064-2138` | Same three historical Task23 profiles | Cumulative 0.532031→0.568061; 0.547865→0.637743; 0.114824→0.087482 | Calls 118→121; 39→45; 19→10. Per-call changes +4.1%/+0.9%/+44.8%; lower total does not prove lower cost. |

Task23 profiles are `L/sequence-control-{baseline,candidate}/*.pstats`, directly inspected, with manifests pinning `2e861af0`→`761caa3c`. CPU pressures and profiled process walls are in §8. Neither `_topological_order` (#23) nor `merge_stage_boundary` (#25) appears in those profiles: this is an absent measurement, not a measured zero.

#39's predecessor report (`L/task-13-report.md`) records approximately 3.8× on a synthetic six-site band-lookup burst. It supplies no paired cumulative seconds, named real cell or vmstat figure; therefore it is not promoted to a final measured mover. #11's archived approximately 8ms→74ms rejection is recorded in §4 with the same provenance limitation.

## 3. Hygiene conversions and unmeasured retained work

Each row below is retained design/de-duplication work with **no established clock movement**. Except for the historical measurements explicitly listed in §2, requested before/after cumulative times are **unavailable/not measured**. This is deliberately not the stronger, unsupported assertion that every row “did not move the clock.” The superseding ruling permits retention without that old timing gate.

| Site / baseline file:line | Duplication or repeated work removed / retained boundary |
|---|---|
| #1 `layout/sequence_solver.py:1280,2030` | Stages owns append and rewrite-aware scheduled count; avoids independent growing-list counts. |
| #2 `layout/sequence_solver.py:1308-1315` | Existing ordered height-frontier walks deliberately retained; no speculative worklist, no measured improvement claim. |
| #7 `layout/freeform.py:10290-10362` | StakedPaths maintains endpoint-neighbour queries instead of rebuilding touch/sole per stranded net. |
| #8 `layout/validate.py:4609-4629` | Sorters narrows exact-item BFS link queries; does not replace item-parameterized traversal with a different graph algorithm. |
| #9 `layout/validate.py:5299-5372` | Item-independent edge descriptors are built once; fresh mutable residual flow graphs preserve per-item edge order. |
| #10 `dsp/provenance.py:505-509` | Shared ReferenceGraph holder inversion replaces a registry-rule rescan. |
| #14 `layout/sequence_solver.py:3484-3496` | Hoisted immutable permutation positions serve repeated feedback swaps. |
| #15 `lab/flow.py:1042-1073` | Built-once FlowSelection maps replace repeated by-item/by-recipe reconstruction. |
| #16 `pipeline.py:816-820`, `lab/flow.py:529-563,946` | External-item derivation reused across candidate filtering and flow checks. |
| #17 `lab/data.py:229-231` | Cached vendored dataset avoids repeated unchanged parsing/index construction. |
| #18 `layout/last_mile.py:132-152` | Finite call-local cached XY distance query over fixed stranded endpoints; no unbounded BFS field. |
| #19 `layout/freeform.py:10190-10192` | Live linked-head state replaces repeated path-tap reverse-link guard rebuilding. |
| #20 `layout/freeform.py:16694-16935` | Output-lane queries indexed by actual item/cargo-domain keys, preserving source order. |
| #21 `layout/validate.py:4182,4358,4396` | Frozen internal seed pair and closures cached by full seed set; external augmentation remains a separate query. |
| #22 `dsp/colliders.py:1742` | One BeltOverlap spatial index shared by both collision readers for identical previews. |
| #23 `layout/sequence_pair.py:1057-1088` | Heap frontier replaces pop(0)/resort; equal-key arrival ordering and cycle error preserved. Absent from saved profiles. |
| #25 `layout/sequence_pair.py:1902-1905` | Shared StripPositions answers stage-boundary adjacency queries. Absent from saved profiles. |
| #26 `layout/sequence_solver.py:5646` | Solve-local immutable instance-ID indexes, preserving tuple.index first-match behavior and object lifetime. |
| #27 `layout/freeform.py:12111-12129,17317-17321` | Nets shares ordered demand/role/ID queries across consumers. |
| #28 `layout/freeform.py:10442-10456` | One maintained path-position lookup replaces membership then index scans; first repeated-cell match retained. |
| #29 `layout/freeform.py:21630-21641` | Tuple-key strip clearance lookup replaces repeated scan; projection-map name collision subsequently fixed with behavioral proof. |
| #30 `layout/freeform.py:13629-13667` | PortReservations owns forward and reverse mappings through mutation/clone/restore; first forward insertion wins. |
| #31 `layout/freeform.py:8959-9020,16008-16236` | Shared UnionFind removes three implementations; explicit right-root policy preserves root-sensitive ties. |
| #33 `layout/validate.py:4920-5008` | Shared ordered sorter queries replace repeated spray-feed scans; unresolved cargo stays admitted where originally required. |
| #34 `layout/route_feedback.py:640-707,747-757` | Shared strip-position queries remove duplicate LNS position derivation. |
| #36 `layout/global_router.py:395-408` | First reservation per owner indexed once per routing round, preserving duplicate-owner precedence. |
| #37 `layout/hierarchy/pressure.py:194,206` | Recipe depths derived once and passed to both readers. |
| #39 `dsp/codec.py:239-246`, `dsp/splitter_ports.py:248-255` | Cached band-by-segment lookup shares equality query while retaining missing-band errors. Historical unpaired ratio caveat in §2. |
| #40 `bench/ab.py:544-630,703-778` | Frozen derived areas/comparable pairs cached once, recomputed on dataclass replacement. |
| #41 `lab/techs.py:65-154` | One dataset-items classification pass retains all three predicates. |
| #43 `bench/promotion.py:155-192` | Group trial rows once rather than refiltering each trial. |
| #44 `scripts/measure_geometry_cache_working_sets.py:134-145,259-325` | Report/timing owner shares combined traces and reductions. Paired script timing/report parity unavailable. |
| #45 `scripts/route_profile.py:660-696` | Shared partitions/sums and stable top-ten selection; full percentile sorts retained where required. |
| #46 `scripts/route_bench.py:267-277` | Counter replaces repeated list.count reductions. |
| #47 `scripts/last_mile_bench.py:142-144` | Single statistics collection replaces four independent passes. Cluster replay is not established by ordinary route cases. |
| #48 `scripts/audit.py:884-885` | Count unreached strategies once on expired-run path. |
| #49 `scripts/route_bench.py:189-260` | Deque preserves FIFO without list-front deletion. |
| Unranked `bench/{scoring,report,regression}.py` | Cells unifies four best-per-URL reductions, preserving first eligible key and tie order. |
| Unranked `bench/corpus.py` and five script call sites | Existing corpus.entry is indexed and reused; no parallel entry_for API. |

Accounting outside this table: measured #4/#5/#24/#35/#42 are in §2; reverted #11/#38 and dropped #3 are in §4; Buildings #6/#12/#13 and the plan's omitted #32 are in §6. This accounts for all 49 scout rows without repeating the brief's unsupported “49 converted/deferred/dropped” claim.

## 4. Reverted

| Conversion | Commit / decision | Evidence and present state |
|---|---|---|
| #11 hardcoding_readers via per-seed networkx descendants | `03c994e9` | Predecessor recorded approximately 74ms vs 8ms, including 438 freeform seeds; original body restored. Commit-message/report measurement, not a recovered profile. Frozen-capture inversion (#10) retained. |
| #38 scan_source literal buckets | `24d0fac0` recovery correction | Reverted for real correctness: relative-tolerance matches at large magnitudes, insertion order, infinity and overflow. Original ordered math.isclose scan restored; L/recovery-provenance-edges.log exit 0. Not merely a marginal timing rejection. |
| Task22 #4/#23/#24/#25 | Candidate `761caa3c`, revert `b5090638`, restore `a8a70b69` | Historical neutrality rejection below; user superseded retention rejection. All four restored with behavioral tests without losing Task24. They are **not currently reverted**. |
| Eager networkx BlockGraph ordering | Backend replacement `188ae9ba`, consumer `f3298f48` | Replaced after networkx/inline ratios 2.207–4.277; actual indexed adjacency/two-heap wrapper retained. See §5. |
| #3 Python decode_sequence_pair adjacency | Dropped under I-1, not an implemented conversion/revert | Authoritative reference decoder retained; compiled kernel is production scoring path where safe/available. |

Historical Task23 audit was baseline 35 CLEAN/1 REFUSED versus candidate 36 CLEAN, with six differing sequence-pair cells: universe-matrix/output-products 16032→16720; no-proliferator 18150→17836; all-products REFUSED→CLEAN 29601; information-matrix/output-products 4905→4826; plastic/no-proliferator 684→722; magnetic-coil/output-products 286→299. L/sequence-control-{baseline,candidate}/audit.jsonl and L/sequence-control-compare.log remain unchanged. These are a different run from §9's final corpus. Earlier conversions were also present, so unique attribution to Task22 was not established.

## 5. Backend decisions, as measured

| Requested decision | Evidence / outcome |
|---|---|
| Task27 StakedPaths dict vs littletable | **UNMEASURED.** One maintained dict-backed domain retained under user override; no claimed backend race, no second production backend. |
| Task20 BlockGraph | L/block-graph-decision.json at `f1d51b65`: 60 equality cases, including 36 actual initial-partition graphs with 1/2/3/4/7/18 blocks. Networkx/inline min/median/max 2.207373/3.259226/4.276924; plain heap/inline 0.456292/0.607196/0.674955; pressure 11.2. Post-cutover L/block-graph-after.json at `f3298f48`: all 60 equality cases; actual wrapper/inline 0.634295/0.824643/0.878481 over 36 real graphs, no slower rows; pressure 8.4. Lazy networkx remains only for other graph queries. |
| Task23 sequence-pair _topological_order | No calls in any of the three paired profiles, so the historical >1%-wall backend-comparison trigger did not fire. Heapq retained; no measured networkx win, no rustworkx or new strip_precedence module. |
| Task16 Cells polars alternative | **UNAVAILABLE/NOT MEASURED.** Littletable retained. Small object-valued collection is design rationale, not a measured polars build/read number. |
| Task29 validator polars alternative | **UNAVAILABLE/NOT MEASURED.** No polars adopted; no cost claim from absent build/materialization measurements. |

The post-cutover JSON's historical `networkx_heap` and `networkx_vs_inline` slots mean the **actual new wrapper**, not an eager networkx implementation. Raw field names are preserved rather than rewriting old evidence.

Other backend ownership: ReferenceGraph uses networkx; Cells/Nets/Sorters use littletable for their indexed queries at the measured freeze; Stages uses an ordered list plus maintained count; StripPositions and BeltOverlap use keyed maps; UnionFind uses arrays. New Sorters delegates building links to canonical Buildings and retains its item index, but that change is outside this measured boundary.

## 6. Still pending buildings-index integration

Canonical Buildings is already on master `f162d9e1`. Main must preserve its existing freeform/hierarchy traversals when merging the old-based indexed branch; their temporary absence here is an expected integration dependency, not a newly discovered source defect.

| Original request / site | Required canonical contract and integration status |
|---|---|
| #6 freeform splitter adjacency and five duplicate/default sites | `Buildings.splitter_successors(index)` with append-safe live maintenance through canvas.add. Already-named master traversals must survive the final merge; not covered by this branch's saved corpus. |
| #12 hierarchy compose._lane | `Buildings.predecessor_of(index)` supplies ordered reverse-link ownership; preserve master's integration. |
| #13 hierarchy contracts._belt_run | `Buildings.belt_run(index, forward=...)` crosses the proper splitter/piler boundaries; preserve master's integration. |
| Three _tap_source fallback rebuilds, scout freeform.py:13294/13319/13355 | Canonical predecessor/splitter/belt traversal queries, not new local indexes. Preserve master's existing freeform traversal cutover. |
| Request 4: Placement.buildings as well as Canvas.buildings | **Implemented, source-reviewed, untested/unmerged:** new Sorters constructor accepts canonical Buildings, validator constructs it from placement, links delegate to sorters_into/sorters_out_of while the resolved item index stays validator-owned. Three files: src/flab2bp/indexed/sorters.py, src/flab2bp/layout/validate.py, tests/indexed/test_sorters.py. |
| #32 finalize._certified_side_fallback, scout finalize.py:3719-3752 | A buildings-sequence scan omitted from the plan's claimed 49-row accounting. Outside this indexed source/report integration scope; no indexed-scans conversion or measurement claimed. Main owns its Buildings/finalization integration accounting. |

ScansDelegationReview independently reports source/spec PASS and quality PASS, no findings, for the frozen three-file delegation diff against canonical `f162d9e1`. It checked constructor callers, four validator consumers, position/subset order, named/unknown cargo, cross-kind exclusion and replacement lifetime. **Read-only review is not runtime proof.** Main owns final combined source, merge-last resolution and integrated verification. The saved `1ca2495f` corpus cannot certify the subsequently changed constructor.

## 7. Where this plan disagreed with the scout

The prescribed original table follows verbatim; its task-number references and rustworkx possibility are historical plan text, corrected by execution rulings below.

| Scout row | Scout's claim | This plan's reading (verified) | Consequence |
|---|---|---|---|
| **#1** | "a running int counter incremented at the same site as `.append()`" | **Incomplete and would change behaviour.** `_counts_as_scheduled_stage` (`sequence_solver.py:865-871`) is false when `global_skip_reason` is `"shared-pack"`, `"topology-beam"` or `"projection-feedback"`. `sequence_solver.py:2106-2107` rewrites `self._stage_stats[-1]` with `replace(observation, global_skip_reason="projection-feedback")` **after** it was appended, flipping an already-counted stage to uncounted. An append-only counter would over-count and change `stage_limit` comparisons at `:1280` and `:2036`. | The `Stages` type must own **both** mutations (`append` and `replace_last`) and recompute the predicate on each. Task 8, with an explicit staleness test. |
| **#3** | `decode_sequence_pair`'s O(N²) adjacency runs "on every candidate move inside `anneal_stage`'s per-move loop" | **False on the production path.** `anneal_stage` scores through `kernel.score_state` (`sequence_pair.py:1640`, `:1667`); `build_sequence_kernel` (`sequence_kernel.py:273-280`) returns `CompiledSequenceKernel` whenever `compiled_backend_available()` and the inputs are safe, and `layout/_sequence_kernel.cpython-314-*.so` is present in the tree. The Python `decode_sequence_pair` is reached only from `decode_state` (`sequence_pair.py:907`) and `encode_placement` (`:1048`). | **Site #3 is dropped from the conversion set** and demoted to "not worth converting". Converting the authoritative reference decoder to incremental maintenance buys nothing on the production path and puts the kernel's tie-breaking at risk for no measured gain. Recorded as Ruling I-1. |
| **#4** | position index instead of two `.index()` scans in `apply_move` SWAP_BOTH | **Confirmed and it IS hot** — `apply_move` at `sequence_pair.py:1656` is Python and runs per candidate move regardless of which kernel scores. `negative.index(...)` at `:1479-1480`. | Site #4 is the *highest-value* sequence-pair site, above #3. Task 15. |
| **#5** | "a running 'fully shared' boolean maintained by `occupy()`" | **Wrong.** `present_cost(index, compatible)` (`global_router.py:79-84`) computes `shares` against the **caller's** `compatible` frozenset, which differs per net; `occupy` cannot know a future querier's set. A cached boolean would be answering a different question. | The real win is cheaper membership: store each unit's owners as a `frozenset[NetId]` so the test is `owners <= compatible` (one C-level subset test) instead of `all(owner in compatible for owner in unit)` (a Python generator per unit). Task 11, gated on measurement. |
| **#9** | build the item-independent belt topology once and share it | **Half right.** `validate.py:5299-5313` (belts) is genuinely item-independent; `:5315-5348` (sorters) and `:5350-5372` (docks) are item-filtered. But `_add_flow_link` writes mutable residual capacities into `graph: list[list[_FlowEdge]]` that `_max_flow` consumes, so a shared skeleton **must be deep-copied per item**. The saving is the scan and the legality tests, not the allocation. | Convert to "precompute an item-independent edge list once, rebuild the flow graph from that list per item". Medium confidence, explicitly gated on the measurement task. Task 21. |
| **#15** | "`functools.cached_property` on `by_item`/`by_recipe`" | **Would raise at runtime.** `FlowSelection` is `@dataclass(frozen=True, slots=True)` (`lab/flow.py:442-443`); `functools.cached_property` needs a `__dict__` and raises `TypeError: No '__dict__' attribute on 'FlowSelection'`. | Use an `init=False` field populated in `__post_init__` through `object.__setattr__`, which works with `frozen=True, slots=True`. Task 13. |
| **Ruling 4** | "One earlier session already chose scipy over networkx for bipartite matching … check whether that code still exists and reuse its pattern." | **That code does not exist.** `grep -rn -i 'scipy'` over `src/`, `tests/`, `scripts/` returns nothing, and `uv pip list` shows no scipy in the environment. The bipartite matching from `bb6ed841` ("Freeform: access cells are a matching") is implemented in `_reserve_port_access` (`freeform.py:12041`) as an **OR-Tools CP-SAT model** (`solve_model` at `freeform.py:11911`), not scipy. | The reusable precedent is "state the combinatorial problem to a solver already in the dependency set", not "reach for scipy". This plan therefore adds **no** scipy dependency; the compiled-library escape hatch in Ruling 4 is exercised, if at all, only by the measurement tasks (Tasks 16, 20, 22), and only against `rustworkx`. Recorded as Ruling I-2. |

Further execution disagreements/corrections:

- Stages also needs reverse iteration; scheduled-count ownership must include rewrites. Current tasks are Stages5/consumer24, not the old numbers in the quoted table.
- Sorter item identity was already memoized. Unknown cargo is included in spray-feed/lane-balance but excluded from exact-item coproduct matching. The positive reachability fixture needed explicit filter IDs and IdMap, not carries labels.
- `_internal_seeds` returns two sets, not one; lane sourcing augments with external entries. Cache complete seed keys, never conflate those closures.
- BlockGraph must preserve duplicate/self-loop and cycle-fallback semantics. Eager networkx lost its actual construction+order comparison; plain adjacency/two heaps won. This is Task20, while sequence-pair backend diagnostics are Task23; P5 prohibits a rustworkx dependency or invented strip_precedence module here.
- The planned unbounded last-mile distance BFS is invalid. The implemented finite XY query preserves routed-path precedence, empty behavior and the FAR cap.
- Frozen Cells reductions must preserve the first eligible URL's order, not the first unfiltered occurrence. Trace polling must preserve exclusive cursor and Python slice behavior, including nonpositive limits.
- Immutable instance IDs are StripInstanceId, not int; the index must retain first-match semantics and solve-local source lifetime.
- `FlowSelection` and frozen AB values need init=False fields via object.__setattr__, not cached_property. Existing corpus.entry replaces the invented entry_for API.
- Source is authoritative over transcribed snippets: preserve frontier walks, RNG draws, equal-key arrival order, cycle errors and return types. The recovery preflight recorded nonexistent fixtures and malformed commands rather than following them blindly.
- Task30's bare mypy-clean expectation and root Ruff commands were invalid at baseline (P31/P32). Current static evidence is explicitly scoped below. The claimed complete scout accounting omitted #32; §6 records that gap.

## 8. Environment

All evidence is preintegration. Final runtime provenance is `L/final-runtime-provenance.log`: exit 0, import `/home/dannyb/sources/factorio-lab-to-blueprint/.claude/worktrees/indexed-scans/src/flab2bp/__init__.py`, `compiled=True`. VIRTUAL_ENV mismatch warnings explicitly say the outside environment is ignored. BlockGraph/global/capacity JSONs and sequence manifests separately record their candidate worktree imports and baseline `indexed-scans-control` imports. There is **not** a per-invocation import line for every saved final CLI/corpus process, so the stronger “verified for every run” claim is unavailable; final provenance and pinned corpus commit fields are the saved boundary evidence.

CPU pressure means the last five one-second vmstat runnable-process samples, excluding the first cumulative sample. All raw vmstat snapshots are retained beside their original timings. This report made no new timings or runtime measurements.

| Historical Task23 command | Baseline wall s / pressure | Candidate wall s / pressure |
|---|---:|---:|
| Route replay process | 2.593013 / 5.0 | 1.853283 / 10.2 |
| magnetic-coil cProfile CLI | 64.878776 / 3.6 | 64.766778 / 15.8 |
| processor cProfile CLI | 77.443459 / 5.2 | 79.611919 / 13.4 |
| universe-matrix cProfile CLI | 101.566002 / 2.2 | 100.776256 / 10.2 |
| Sequence-only audit | 151.514766 / 1.0 (exit 1) | 157.772656 / 17.0 (exit 0) |

Other recorded pressures: setup 4.2; initial archived master baseline 195s wall / 12.6 (ledger); BlockGraph decision 11.2 and after 8.4; capacity 7.0→3.2; trace 3.6→5.2; final serial quantum-chip 13.8→13.8. Final corpus wall is 1472s baseline→1464s candidate, but no corresponding per-cell pressure/paired largest-eight wall experiment is saved. Do not interpret the total as a controlled speedup. Final replay rounds are 0.176/0.188/0.175s; no final replay vmstat snapshot is saved. Missing pressure is stated rather than borrowed from an unrelated run.

## 9. Static, full-suite, replay, corpus and control evidence

### Saved static and suite outcomes

| Evidence in L | Actual outcome / boundary |
|---|---|
| settled-ruff.log | Scoped `ruff check src scripts tests`, exit 0, all checks passed. |
| settled-format.log | Scoped format check, exit 0, 247 files already formatted. |
| settled-mypy.log | mypy src exit 0, no issues in 102 source files. |
| final-mypy-scripts.log | mypy src+scripts **exit 1**, 53 errors in five files, checked 121 source files. Not a clean pass. |
| parallel-final-full-suite.log | **exit 1**, three named failures: inherited test_two_stage_alignment_retains_cp_sat_direct_opportunity; test_indexed_sorter_reachability_keeps_exact_item_and_link_boundaries; test_all_products_sequence_pair_honours_the_exact_layout_deadline. No green full-suite claim. |
| reachability-fixture-red.log → reachability-fixture-green.log | Positive reachability fixture failed; corrected explicit filter IDs/IdMap passed both focused checks (exit 0), unknown sorter deliberately left unfiltered. |
| settled-validate.log | Complete validator module passed, exit 0, after fixture correction. This does not turn the earlier full-suite log green. |
| deadline-serial.log | Exact layout deadline test passed serially, exit 0; original failure preserved. |
| clearance-cache-lifecycle-{red,green}.log | Real ProjectionRefusal→coater-clearance transition exposed dictionary collision; Main's separation restored learning (west_channel 4 rather than 3 at next height). Targeted red→green, not timing noise. |
| snapshot-reservations-{red,green}.log | Before: AttributeError, dict has no first_for, exit 1. After: PASS, replay snapshot retains independent indexed port reservations, exit 0. |

The five mypy baseline files are scripts/extract_dsp_colliders.py, scripts/extract_dsp_power.py, scripts/extract_dsp_slot_poses.py, scripts/extract_dsp_tables.py and scripts/trace_overhead.py. Direct log inspection counts 53 diagnostics in exactly those files, consistent with P32; no suppression or clean-src+scripts claim.

Main reports the three final source-review slices PASS after corrections. Earlier immutable review packages and rulings are in L/progress.md and L/recovery-report.md; that recovery handoff's older “pending” state is superseded here only where later evidence exists. The distinct new Buildings delegation also received read-only PASS/PASS (§6), but has not run or merged.

### Replay and router controls

`L/final-route-replay.log` exits 0: three rounds each **368077 expansions**, captured and replay digest **1722e54fa17970f9**, **MATCH**. The ordinary route capture was 64 of 1203 searches, all 64 found, 1763 path cells (ledger). This replay does not stand in for a stranded-cluster/last-mile replay.

Earlier `L/global-{baseline,candidate}.json/.log` at `2e861af0`→`f3298f48` contain 72 full Python/compiled global-router outcomes, MATCH, no differences, exits 0. `L/capacity-trace-{baseline,candidate}.json/.log` also MATCH with no differences, exits 0. These exercise a different router path from the ordinary freeform route replay; neither alone establishes blueprint parity.

### Final paired corpus

Direct parsing of **all** B/corpus.jsonl and C/corpus.jsonl rows yields equal sets of 72 distinct `(url_id, spec_label, strategy)` keys, all budget 30, pinned source commits as above. Both logs exit 0. Each side has **36/36 freeform CLEAN and 36/36 sequence-pair CLEAN**, with no refusal, invalid, crash or not-run cell. Both have **zero grace overruns** (`wall_overshoot_s=0` throughout).

This does not mean no completion went beyond the requested search deadline: each log records **21** such completions, largest atomic completion tail **5.2s baseline / 5.0s candidate**. The grace accounting and the exact-deadline test are separate evidence.

Twelve areas differ; all statuses remain CLEAN. No new refusal, but **strict area identity FAILS**:

| URL / spec | Strategy | Baseline area | Candidate area |
|---|---|---:|---:|
| energy-matrix / no-proliferator | sequence-pair | 616 | 504 |
| information-matrix / all-products | freeform | 5355 | 4760 |
| information-matrix / no-proliferator | freeform | 8030 | 7917 |
| information-matrix / output-products | freeform | 5856 | 5434 |
| information-matrix / output-products | sequence-pair | 5467 | 4905 |
| plastic / no-proliferator | sequence-pair | 684 | 722 |
| quantum-chip / all-products | freeform | 3840 | 3825 |
| quantum-chip / all-products | sequence-pair | 3300 | 3190 |
| super-magnetic-ring / no-proliferator | freeform | 2233 | 2257 |
| universe-matrix / all-products | sequence-pair | 33605 | 25168 |
| universe-matrix / no-proliferator | sequence-pair | 17836 | 21420 |
| universe-matrix / output-products | sequence-pair | 16720 | 16340 |

The other 60 status/area pairs match. A CLEAN status certifies that run, not byte identity or unique attribution of area differences.

### Final deterministic controls

See [deterministic-controls.md](deterministic-controls.md) for complete-file byte lengths and the mismatch hashes. Original twelve CLI pairs all exit 0; **11 MATCH, quantum-chip DIFFERS**. The separately saved serial quantum-chip baseline/candidate both exit 0 and are fully byte-identical (36156 bytes, SHA-256 `7454a4e349b367af3cf5a01134c6e9415f39184a88e3d1cfbc2ad617c4c93b6b`). They match the original candidate, not the original baseline. No raw mismatch was rewritten, no checksum-prefix comparison substituted for complete bytes, and no all-twelve serial run is claimed.

## 10. Missing requested evidence and report review boundary

- Final largest-eight paired CLI wall ratios with per-cell vmstat: **unavailable/not measured**. The saved corpus is not that experiment.
- Final per-site cumulative profiles, Task25 solver driver/stage telemetry comparison, Task27 full freeform/StakedPaths backend costs, and Task29 paired certification/profile costs on shared Placement+BuildSpec inputs: **unavailable/not measured**. Earlier Task23 profiles are preserved, not extrapolated to final source.
- Task16 and Task29 polars build/read/materialization numbers: **unavailable/not measured**. No polars performance conclusion is supported.
- Paired geometry-cache report timings and stranded-cluster/last-mile digest replay: **unavailable**; a shared certified Placement+BuildSpec capture and separate replayable stranded-cluster capture are not established by ordinary route cases.
- A settled green whole-suite run, the brief's exact budget-30 twelve-CLI control recipe, and per-invocation import confirmation for every final process are not saved. The actual failed suite, focused/module corrections, serial deadline and budget-60 controls are reported instead.
- New three-file Buildings delegation is source-reviewed but **untested/unmerged**; final combined source/merge/runtime proof remains Main-owned and is outside every saved final corpus/control figure.

Report review used the prescribed brief, scout/plan disagreement table, recovery reports and ledger, complete saved blueprint files, parsed corpus/control JSON, actual pstats and saved log/serial outcomes. It made **only documentation/ledger changes** and ran no tests, builds, lint, formatters, benchmarks or source changes. It does not replace Main's final source review, correctness adjudication or merge-last integrated verification.
