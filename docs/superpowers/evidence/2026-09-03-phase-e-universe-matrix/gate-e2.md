tip 2561a08af964c6289896f0b02965ef2d4096f81a
2561a08af964c6289896f0b02965ef2d4096f81a

```text
== round 1
clean 70  refused 2  invalid 0  crashed 0  paired 70  area ratio 0.9990  p95 28.2s
  note CARRIED: freeform universe-matrix/no-proliferator: no packing of 43 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing
  note CARRIED: sequence-pair universe-matrix/no-proliferator: deadline exhausted before finding an exact layout
PASS
== round 2
clean 70  refused 2  invalid 0  crashed 0  paired 70  area ratio 0.9977  p95 28.7s
  note CARRIED: freeform universe-matrix/no-proliferator: no packing of 43 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing
  note CARRIED: sequence-pair universe-matrix/no-proliferator: deadline exhausted before finding an exact layout
PASS
== round 3
clean 70  refused 2  invalid 0  crashed 0  paired 70  area ratio 1.0004  p95 28.4s
  note CARRIED: freeform universe-matrix/no-proliferator: no packing of 43 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is producing packs its own router cannot wire -- and it is reported rather than papered over with a looser packing
  note CARRIED: sequence-pair universe-matrix/no-proliferator: deadline exhausted before finding an exact layout
PASS
```

```text
round1: clean 70/72  p95 28.24s  max 28.72s  invalid 0  crash 0
    freeform no-proliferator REFUSED 20.8s {'stages': None, 'alns_operators': 'destroy:failed-endpoints:1|destroy:band-boundary:0|repair:sequence-reinsert:0|repair:local-exact-pack:1', 'alns_window_solves': 1.0, 'alns_window_accepted': 1.0, 'alns_window_dropped_empty': None, 'alns_window_dropped_whole': None, 'alns_window_unchanged': None, 'evaluations': 6.0, 'distinct_assignments': 6.0, 'stale_draws': 0.0, 'stale_stop': 0.0}
      detail: no packing of 43 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is pro
    sequence-pair no-proliferator REFUSED 27.6s {'stages': 5.0, 'alns_operators': 'destroy:failed-endpoints:4|destroy:band-boundary:1|repair:sequence-reinsert:4|repair:local-exact-pack:1', 'alns_window_solves': 0.0, 'alns_window_accepted': 0.0, 'alns_window_dropped_empty': 0.0, 'alns_window_dropped_whole': 1.0, 'alns_window_unchanged': 0.0, 'evaluations': None, 'distinct_assignments': None, 'stale_draws': None, 'stale_stop': None}
      detail: deadline exhausted before finding an exact layout
round2: clean 70/72  p95 28.67s  max 29.90s  invalid 0  crash 0
    freeform no-proliferator REFUSED 21.7s {'stages': None, 'alns_operators': 'destroy:failed-endpoints:1|destroy:band-boundary:0|repair:sequence-reinsert:0|repair:local-exact-pack:1', 'alns_window_solves': 1.0, 'alns_window_accepted': 1.0, 'alns_window_dropped_empty': None, 'alns_window_dropped_whole': None, 'alns_window_unchanged': None, 'evaluations': 6.0, 'distinct_assignments': 6.0, 'stale_draws': 0.0, 'stale_stop': 0.0}
      detail: no packing of 43 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is pro
    sequence-pair no-proliferator REFUSED 24.4s {'stages': 4.0, 'alns_operators': 'destroy:failed-endpoints:3|destroy:band-boundary:1|repair:sequence-reinsert:3|repair:local-exact-pack:1', 'alns_window_solves': 0.0, 'alns_window_accepted': 0.0, 'alns_window_dropped_empty': 0.0, 'alns_window_dropped_whole': 1.0, 'alns_window_unchanged': 0.0, 'evaluations': None, 'distinct_assignments': None, 'stale_draws': None, 'stale_stop': None}
      detail: deadline exhausted before finding an exact layout
round3: clean 70/72  p95 28.40s  max 31.89s  invalid 0  crash 0
    freeform no-proliferator REFUSED 25.3s {'stages': None, 'alns_operators': 'destroy:failed-endpoints:1|destroy:band-boundary:0|repair:sequence-reinsert:0|repair:local-exact-pack:1', 'alns_window_solves': 1.0, 'alns_window_accepted': 1.0, 'alns_window_dropped_empty': None, 'alns_window_dropped_whole': None, 'alns_window_unchanged': None, 'evaluations': 6.0, 'distinct_assignments': 6.0, 'stale_draws': 0.0, 'stale_stop': 0.0}
      detail: no packing of 43 strips could be wired at any candidate height; every pack the sweep produced left nets unrouted. That is a PACKER defect -- it is pro
    sequence-pair no-proliferator REFUSED 27.7s {'stages': 5.0, 'alns_operators': 'destroy:failed-endpoints:4|destroy:band-boundary:1|repair:sequence-reinsert:4|repair:local-exact-pack:1', 'alns_window_solves': 0.0, 'alns_window_accepted': 0.0, 'alns_window_dropped_empty': 0.0, 'alns_window_dropped_whole': 1.0, 'alns_window_unchanged': 0.0, 'evaluations': None, 'distinct_assignments': None, 'stale_draws': None, 'stale_stop': None}
      detail: deadline exhausted before finding an exact layout
verdicts: {'freeform': ['REFUSED', 'REFUSED', 'REFUSED'], 'sequence-pair': ['REFUSED', 'REFUSED', 'REFUSED']}
```

Load record: [e2-load.txt](e2-load.txt)

1. FAIL — `universe-matrix/no-proliferator` was REFUSED under both strategies in all three rounds; Gate E2 is not 72/72 and Gate E3 did not run.
2. PASS — every round had 70/72 CLEAN, INVALID 0, CRASH 0, no regression, area ratios 0.9990/0.9977/1.0004, p95 28.24/28.67/28.40 s, and max 28.72/29.90/31.89 s.
3. FAIL — sequence-pair universe-matrix rows had `alns_window_solves=0` in all nine cells and all-products had `repair:local-exact-pack=0`; `destroy:failed-endpoints>=1` and the stage-cost floor passed (minimum E2/E1 ratio 0.80, no `STAGE COST`).
4. FAIL — freeform no-proliferator had `distinct_assignments=6` in every round but refused with forbidden `PACKER defect` wording rather than CLEAN, staleness, or deadline wording.
