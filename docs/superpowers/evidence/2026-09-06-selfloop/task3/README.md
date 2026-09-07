# Task 3 evidence — the flanked drain row (spec §9 R2)

**`universe-matrix` REFUSES with this change. That is a FAIL, and it is the
headline of this directory, not a footnote.** The refusal is not a mixed-lane
finding and not a strip-geometry finding: it is a producer-lane fan-out, quoted
verbatim in `refusal.txt` and in context in `build-um.log`.

## The one CLI build

| file | what it is |
|---|---|
| `build-um.log` | THE build. `flab2bp <universe-matrix URL> --budget 30 -v`, exit 3, 14.7 s wall. No blueprint was produced, so there is no `bp-um.txt` and no `decode-um.txt`. |
| `refusal.txt` | the two verbatim refusal messages from that log — 15 consumer lanes under `no-proliferator`, 12 under the two `*-products` policies. |
| `uptime.txt` | `uptime` immediately before and after that build, in that order. |

Exactly one build was run, per the task's constraint on a shared box.

## The decode is an IN-PROCESS EMISSION, not a CLI decode

`bp-six-input.txt` / `decode-six-input.txt` / `emit-six.txt` come from
`probe_emit_six.py`, which lays out the **same real recipe** (`universe-matrix`
on real Matrix Labs — the spec `tests/layout/test_freeform.py::six_input_spec`
uses) in process and encodes it. It stands in for the decode the refused build
could not produce, and it is evidence for the SEATING GEOMETRY only:

* six `from run N` lines per Matrix Lab, six distinct runs, one item each;
* no `<<< SHARED-INPUT-RUN` flag anywhere in the file;
* run 1 is the gap belt `(8,9) -> (8,13)` draining into the outermost row, which
  crosses nothing because this strip holds one machine.

It is NOT evidence that the corpus block builds. It does not.

## Measurement probes

| file | what it shows |
|---|---|
| `probe_seating.py`, `probe-before.txt`, `probe-after.txt` | `_side_lane_caps(2901, 0.0, 5) == (3, 3)`, `attachable_columns` empty at the fourth row each side, `_seat_inputs` on the three cap/flank combinations, and the flanked plan and strips before (`box_height` 8, one mixed lane per side, 3 strips of 5 machines) and after (`box_height` 12, three single-item lanes per side, 15 one-machine strips, drain row span 0). |
| `probe_gap_column.py`, `probe-gap-column.txt` | **the blocker.** Per strip length: each machine's gap column against each south lane's belt extent. `machines=1` → 0 crossings; `machines=2` → 3; `machines=3` → 6; `machines=6` → 15. Only the last machine's gap column is ever clear. |
| `probe_heights.py`, `probe-heights.txt` | the re-derivation behind `test_the_schedule_replaces_the_over_band_height_with_the_boundary`: 69 strips, schedule `(166, 130, 104, 83, 62)`, widened-seed schedule `(130, 104, 83, 154, 62)`. |

## Test runs

`red-strip-variants.txt`, `red-freeform.txt` are the red step (both exit 1),
taken before any implementation existed. `green-*.txt` are the suites afterwards;
`green-layout-rest.txt` fails only
`test_two_stage_alignment_retains_cp_sat_direct_opportunity`, which is red on
master and is not touched by this change.
