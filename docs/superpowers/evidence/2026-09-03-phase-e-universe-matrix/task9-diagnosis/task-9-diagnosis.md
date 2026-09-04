# Diagnosis: the `sequence-pair universe-matrix/output-products` regression under Task 9 (8f8f160)

Ruling E10. Measurement only — no committed file changed. All six arms are `git archive` checkouts under
`/tmp/claude-839601109/-home-dannyb-sources-factorio-lab-to-blueprint/8e787b45-e7bb-460a-9069-84e8ce0bea85/scratchpad/phase-e-diag/{A,B,C,D,E,F}`,
each with a frozen `.git/HEAD` and the worktree's compiled kernels copied in. The worktree itself stayed at `8f8f160`,
clean, untouched, throughout. JSONL rows and `load.txt` are kept beside this file under `phase-e-diag/out/`.

## Arms

- **A** — `554e9b2` (pre-Task-9), the control.
- **B** — `8f8f160` as committed.
- **C** — `8f8f160` with the probe branch forced off (`if False and probe < ...`), master's two-independent-ledger pairing rule restored, Task 9's counters kept.
- **D** — `8f8f160` with the probe firing only on draw 1 (`if probe == 1:` instead of `if probe < 4:`), every other draw going straight to the D-UCB.
- **E** — `8f8f160` with the repair axis reversed for the probe only (draw 0 = `(FAILED_ENDPOINTS, LOCAL_EXACT_PACK)`), the spec's rejected option.
- **F** — B, unmodified, run at `--budget 60` instead of 30.

Verified each arm's actual `select()` sequence with a standalone 4-draw script before running audits:
```
B: FE-SR, FE-LEP, BB-SR, BB-LEP
C: FE-SR, BB-LEP, FE-SR, BB-LEP   (master's alternating order)
D: FE-SR, FE-LEP, BB-SR, BB-LEP   (== B for the first four draws; see reading)
E: FE-LEP, FE-SR, BB-LEP, BB-SR   (window first)
```

Runs: `scripts/audit.py --only universe-matrix --strategy sequence-pair --jobs 3 --json <arm>-round<r>.jsonl`, budget 30 (F: 60), three rounds, interleaved A B C D E F three times. `uptime`/`vmstat 1 3` recorded before all 18 runs into `out/load.txt`; load ranged up to `load average: 37+` at points, never waited for.

## `output-products`

| arm | r1 | r2 | r3 | stages (r1/r2/r3) | window_solves (r1/r2/r3) |
|---|---|---|---|---|---|
| A (control) | REFUSED 26.74s | CLEAN 24.87s | CLEAN 25.98s | 4/4/4 | 0/0/0 |
| B (8f8f160) | REFUSED 28.21s | REFUSED 28.73s | REFUSED 28.70s | 4/4/5 | 1/1/1 |
| C (probe off) | CLEAN 26.41s | CLEAN 26.44s | CLEAN 27.16s | 5/5/4 | 0/0/0 |
| D (draw-1-only probe) | REFUSED 27.77s | REFUSED 28.50s | REFUSED 27.89s | 4/4/4 | 1/1/1 |
| E (reversed repair axis) | REFUSED 27.91s | REFUSED 27.82s | REFUSED 28.52s | 5/4/5 | 1/1/2 |
| F (B @ budget 60) | CLEAN 54.08s | CLEAN 55.25s | CLEAN 54.77s | 6/6/6 | 0/0/0 |

Detail text on every REFUSED row above: `"deadline exhausted before finding an exact layout"`.

C's window draws for this cell dropped instead of solving: `alns_window_dropped_empty` = 2, 2, 1 across its three rounds (LOCAL_EXACT_PACK was drawn but the destroy set was already empty by then). B/D/E's window draws for this cell all show `alns_window_solves = 1` (or 2 for E round 3) and `alns_window_accepted = 1` (or 2) — CP-SAT actually ran and its result was installed.

## `all-products`

| arm | r1 | r2 | r3 |
|---|---|---|---|
| A | CLEAN 30.88s | CLEAN 29.40s | CLEAN 25.17s |
| B | CLEAN 24.92s | CLEAN 29.70s | CLEAN 27.88s |
| C | CLEAN 28.21s | CLEAN 25.18s | CLEAN 28.44s |
| D | CLEAN 24.67s | CLEAN 25.17s | CLEAN 26.34s |
| E | **REFUSED 26.71s** | **REFUSED 24.40s** | **REFUSED 24.62s** |
| F | **REFUSED 51.95s** | **REFUSED 49.70s** | **REFUSED 51.97s** |

`all-products` is CLEAN in 2 stages under every arm except E and F. Under E it moves because the reversed axis forces LOCAL_EXACT_PACK as literally the first operator choice (`alns_window_solves=1` on every round), which this cell never pays under any other arm's first draw. Under F its detail text is `"deadline exhausted before finding an exact layout"` with `alns_window_accepted=0` (window solved but rejected) or `alns_window_unchanged=1` (window solved, returned the incumbent) on all three rounds — a different mechanism from E, discussed below.

## `no-proliferator`

| arm | r1 | r2 | r3 |
|---|---|---|---|
| A | REFUSED 28.04s | REFUSED 27.79s | REFUSED 25.40s |
| B | REFUSED 27.93s | REFUSED 28.63s | REFUSED 26.00s |
| C | REFUSED 26.16s | REFUSED 25.08s | REFUSED 25.97s |
| D | REFUSED 26.16s | REFUSED 28.48s | REFUSED 28.93s |
| E | REFUSED 26.53s | REFUSED 25.43s | REFUSED 26.34s |
| F | REFUSED 52.60s | REFUSED 56.25s | REFUSED 52.62s |

REFUSED under every arm in every round — its known, pre-existing state, unmoved by any of A-F.

## Reading

The numbers support **(c), both, with a causal chain from (b) to (a)**: order determines *when* LOCAL_EXACT_PACK is first drawn, and that timing determines whether it costs anything. Under C (master's order restored), LOCAL_EXACT_PACK is drawn but the destroy neighbourhood is already empty by then — `alns_window_dropped_empty` = 2/2/1, `alns_window_solves` = 0 every round — so it's free, and `output-products` is CLEAN all three rounds. Under B and D, the SAME window arm is forced onto draw 1, against a still-live destroy set, and actually reaches CP-SAT (`alns_window_solves` = 1 every round) — a real time cost master's order never paid on this cell — and `output-products` REFUSES in all six B+D rounds. D reproduces B almost exactly (draws 0-3 come out identical: with only 2 destroy and 2 repair arms, forcing draw 1 to the window leaves exactly one untried destroy arm and one untried repair arm for draws 2-3, which the D-UCB's own untried-first fallback plays in declaration order anyway — so restricting the probe to "draw 1 only" does not actually isolate anything here). E is strictly worse: forcing the window onto draw 0 costs even the trivially-easy `all-products` cell its clean run, confirming Ruling E1's choice to reject the reversed axis. F shows the mechanism is budget-sensitive, not a hard wall: doubling the budget lets `output-products` absorb the extra CP-SAT cost and come back CLEAN in all three rounds — but at 60s `all-products` now REFUSES instead (window solved-but-rejected or solved-unchanged on every round), which the control arm A never does even once, so more time is not a clean fix; it moves the problem cell rather than only rescuing the sick one. One caution the raw rows also show: even the pure control (A) REFUSED `output-products` once out of three rounds here (at `--jobs 3`, unlike Gate E1's `--jobs 16` full-corpus measurement, which was CLEAN in all three rounds) — the smaller job count used for this isolated diagnosis changes per-cell CPU allocation and reintroduces some baseline CP-SAT run-to-run variance that the wider corpus run did not show, so the size of the regression should be read as "B is worse than A" rather than "A is perfectly stable."

Only **C** (probe disabled, master's order) keeps `output-products` CLEAN in all three rounds at `--budget 30`; **F** (B, unmodified, at `--budget 60`) also keeps it CLEAN in all three rounds but at double the budget and at the cost of moving `all-products` to REFUSED instead.
