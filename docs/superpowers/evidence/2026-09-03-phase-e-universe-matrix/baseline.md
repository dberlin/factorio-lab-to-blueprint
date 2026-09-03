branch point: 60ab5f8339776b6c8020046dc1c04733f9a0c2fa

# Phase E baseline at budget 30

Pre-flight (Step 2): `uv run pytest -q` exit=0 (all tests pass, no failures; a first
attempt piped directly through `tail -30` printed a truncated C-stack trace from a
transient interruption under that pipe, but a clean redirect-to-file rerun completed
100% with no `F`/`E` marks and exit=0 -- the tree is green). `uv run ruff check .`:
`All checks passed!` (exit=0). `uv run mypy`: `Found 184 errors in 16 files (checked
167 source files)` -- matches the expected count exactly.

## Step 4: figures the gates will judge

```
round1: clean 66/72  p95 28.28s  max 28.74s invalid 0 crash 0
    MISS freeform/universe-matrix/all-products
    MISS freeform/universe-matrix/no-proliferator
    MISS freeform/universe-matrix/output-products
    MISS sequence-pair/universe-matrix/all-products
    MISS sequence-pair/universe-matrix/no-proliferator
    MISS sequence-pair/universe-matrix/output-products
round2: clean 66/72  p95 28.36s  max 28.92s invalid 0 crash 0
    MISS freeform/universe-matrix/all-products
    MISS freeform/universe-matrix/no-proliferator
    MISS freeform/universe-matrix/output-products
    MISS sequence-pair/universe-matrix/all-products
    MISS sequence-pair/universe-matrix/no-proliferator
    MISS sequence-pair/universe-matrix/output-products
round3: clean 66/72  p95 28.48s  max 29.76s invalid 0 crash 0
    MISS freeform/universe-matrix/all-products
    MISS freeform/universe-matrix/no-proliferator
    MISS freeform/universe-matrix/output-products
    MISS sequence-pair/universe-matrix/all-products
    MISS sequence-pair/universe-matrix/no-proliferator
    MISS sequence-pair/universe-matrix/output-products
```

All three rounds match the expected outcome: `clean 66/72`, `invalid 0`, `crash 0`,
and the same six MISS lines, all naming `universe-matrix`, in every round.

## The six refusing cells (round 1 `detail` strings, verbatim)

```json
{"strategy": "freeform", "url_id": "universe-matrix", "spec_label": "all-products", "status": "REFUSED", "detail": "no packing of 42 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing"}
{"strategy": "freeform", "url_id": "universe-matrix", "spec_label": "no-proliferator", "status": "REFUSED", "detail": "every packing that wired was rejected by our own validator (game.blueprint_area; findings: band 0 game.blueprint_area (): a 264x162 extent fits no band on a segment-200 planet: it needs 162 latitude rows in its better orientation and the tallest band (200 segments) holds 160. The game refuses this paste with EBuildCondition.BlueprintAreaCrossTropic.); a placement that fails validation is refused rather than returned, because an invalid blueprint pastes and then does not run"}
{"strategy": "freeform", "url_id": "universe-matrix", "spec_label": "output-products", "status": "REFUSED", "detail": "no packing of 43 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing"}
{"strategy": "sequence-pair", "url_id": "universe-matrix", "spec_label": "all-products", "status": "REFUSED", "detail": "deadline exhausted before finding an exact layout"}
{"strategy": "sequence-pair", "url_id": "universe-matrix", "spec_label": "no-proliferator", "status": "REFUSED", "detail": "deadline exhausted before finding an exact layout"}
{"strategy": "sequence-pair", "url_id": "universe-matrix", "spec_label": "output-products", "status": "REFUSED", "detail": "deadline exhausted before finding an exact layout"}
```

## Step 5: a REFUSED row carries no stats today

```
6 refused rows; stats keys: []
```

This is the blocker Task 7 removes and R3 §5.3 measured; recording it here makes
Gate E1's "every REFUSED row carries a non-empty `stats` object" clause a
before/after statement rather than an assertion.

## Box load (`baseline-load.txt`, verbatim)

```
== round 1
 17:08:40 up 18 days, 22:54,  9 users,  load average: 4.86, 6.53, 5.65
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st gu
 3  0      0 1038895856  0 9558020   0    0 49423 15372 23381   4  5  2 93  0  0  0
 2  0      0 1038897372  0 9558020   0    0     0 19528 19790 41754 1 1 97  0  0  0
 2  0      0 1038897420  0 9558020   0    0   228  2316 16718 33866 1 1 98  0  0  0
== round 2
 17:10:05 up 18 days, 22:56,  9 users,  load average: 14.06, 9.49, 6.79
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st gu
 1  0      0 1038730832  0 9558116   0    0 49420 15371 23381   4  5  2 93  0  0  0
 0  0      0 1038730452  0 9558116   0    0     8   160 13216 24654 1 1 98  0  0  0
 9  3      0 1038725760  0 9558316   0    0   264 41816 21014 56352 1 2 97  0  0  0
== round 3
 17:11:24 up 18 days, 22:57,  9 users,  load average: 17.61, 12.00, 7.91
procs -----------memory---------- ---swap-- -----io---- -system-- -------cpu-------
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st gu
 4  0      0 1038499764  0 9558832   0    0 49418 15372 23382   4  5  2 93  0  0  0
 8  0      0 1038502400  0 9558832   0    0   276 78136 40550 86821 2 2 93  2  0  0
 2  0      0 1038501716  0 9558832   0    0  6776 56079 40703 77435 2 3 94  1  0  1
```

The box was under concurrent load from another worktree's test/audit run throughout
all three rounds (load average climbing 4.86 -> 17.61, `wa` non-zero in round 3);
that is expected per the phase's I/O-bound-box note and was recorded, not avoided.
