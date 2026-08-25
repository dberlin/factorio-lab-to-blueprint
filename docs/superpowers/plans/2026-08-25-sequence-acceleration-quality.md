# Sequence Search Acceleration and Quality Plan

**Goal:** Increase useful SA work per wall-clock second, then spend it on the remaining refinery height/area gap.

**Evidence:** Current refinery anneal throughput is ~822 moves/s for 14 strips and ~84 moves/s for 40 strips. The dominant costs are repeated `PlacementCostContext` validation (33.5%/80.6%) and per-move archive materialization/deep hashing (45.6%/12.2%). Decode+score is only 12.5%/4.85% of whole-stage wall. Isolated Numba integrated decode+score is 3.87×/5.51× faster than Python; Cython is 3.74×/4.99×. Numba has a 2.58s cold JIT and ~113 MiB measured RSS increase but avoids a compiler/wheel matrix and wins warm integrated throughput for 60-second solves.

## Constraints

- Exact Python reference behavior and deterministic seeds remain authoritative.
- No game-rule, routing, acceptance, or production-default changes.
- Remove Python overhead before integrating Numba.
- Numba output must match coordinates/windows/gaps/direct misses/HPWL/history/SearchEnergy exactly, including CPython 3.12 compensated summation.
- Pure-Python fallback remains available.
- No timing thresholds in pytest.
- Quality changes follow fresh per-height evidence after acceleration.

### Task 1: Remove per-move context reconstruction

- Add a scoring API accepting dynamic direct targets separately from the already validated immutable context.
- Remove `dataclasses.replace(context, direct_targets=...)` from per-candidate scoring.
- Validate stable history/net data once per stage/problem.
- Add mutation tests proving identical results and direct-target changes remain candidate-specific.
- Profile refinery/quantum 2k and 20k stages.
- Commit `Reuse validated placement cost context`.

### Task 2: Make elite archive updates lazy and hash-efficient

- Maintain category winners and blended reservoirs incrementally.
- Materialize/sort/tag the archive only when a stage result is requested, not after every move.
- Add a cached exact hash to `PlacementKey` while retaining full equality for collision safety.
- Preserve first-seen legacy tie state and canonical Pareto representatives.
- Verify incremental==batch, archive categories, scheduler trajectory, and deterministic seeds.
- Profile again.
- Commit `Reduce sequence archive overhead`.

### Task 3: Re-profile and confirm Numba integration boundary

- Repeat exact hotspot profile and Numba/Cython scratch benchmark on current code.
- Record new whole-stage kernel share, cold/warm throughput, conversion cost, RSS, and Amdahl limit.
- Select Numba unless Cython now has a material end-to-end advantage large enough to justify build-system/wheel changes.
- Commit only the benchmark decision/report if tracked documentation is requested; scratch remains ignored.

### Task 4: Integrate exact Numba decode-and-score kernel

- Add a `SequenceKernel` protocol and Python reference implementation.
- Add Numba nopython implementation over contiguous integer/float arrays, with `cache=True`.
- Convert problem-stable sizes/nets/weights/history/direct-target descriptors once.
- Convert dynamic pair/gap/variant selections at the stage boundary or per move only where required.
- Rebuild validated immutable result records at the Python boundary.
- Reproduce CPython compensated summation exactly.
- Add 384 generated and real refinery/quantum bit/value parity cases.
- Record accelerator/cold-JIT stats; preserve Python fallback.
- Add Numba dependency with exact lock update.
- Commit `Accelerate sequence decode scoring with Numba`.

### Task 5: Accelerator correctness and end-to-end verification

- Run parity, sequence, solver, game-rule, full pytest, Ruff, mypy.
- Run refinery and quantum placement-only 2k/20k throughput, cold and warm.
- Run one 30s refinery solve with Python and Numba using identical seeds/config; require identical correctness, not identical final state when wall cutoff differs.
- Report stage/move throughput, stages completed, global/detailed cadence, CPU/RSS.
- No promotion claim.

### Task 6: Diagnose and improve remaining height gap

- Record per-height discovery and quality-mode summaries: target height, narrowest width, exact incumbent key, gap, HPWL, overflow, stranded, stages, and time.
- Determine why the legal 24/26-height region does not beat the current 51×34 result: insufficient placement exploration, no routable candidate, or scheduler priority.
- Form one evidence-backed change only after this diagnosis.
- Candidate changes include lower-height exploitation, height-neighbour stages, or width/height exact-area priority; do not bundle them.
- Run 30s/60s refinery experiments and full correctness checks.
- Compare against current SequencePair 1,888/932 at 30s, 1,734/794 at 60s, and Freeform 1,196/675.
