# Task 3: what the small-tier arms actually measure

Written in response to controller fix round 1, finding 1. The small-tier BEFORE/AFTER audit committed as
`audit-task3-small-before.jsonl` / `audit-task3-small-after.jsonl` (and their `.log` and
`audit-compare-task3-small*.txt` companions) does **not** exercise `_deterministic_pack_work` at all. The
shipped plain-linear form is licensed by static reachability, not by that corpus measurement. This file is
the honest record; the commit message on `3627121f` overstates what the small-tier arms showed, and per
the controller's ruling that commit is not being amended -- this file is the correction, and Task 5's gate
should cite it rather than the small-tier `audit_compare` output as evidence for the choice of form.

## 1. Cell counts and CLEAN counts, both arms

```
$ wc -l docs/superpowers/evidence/2026-09-07-lane-fanout/gate/audit-task3-small-before.jsonl \
        docs/superpowers/evidence/2026-09-07-lane-fanout/gate/audit-task3-small-after.jsonl
   30 audit-task3-small-before.jsonl
   30 audit-task3-small-after.jsonl
```

Per each arm's own log summary (`audit-task3-small-before.log`, `audit-task3-small-after.log`):

```
=== freeform: 15/15 clean -- CLEAN   (refused 0, invalid 0, crashed 0, not run 0)
=== sequence-pair: 15/15 clean -- CLEAN   (refused 0, invalid 0, crashed 0, not run 0)
```
30/30 CLEAN in both arms; both arms report identical areas (`audit_compare`'s `area ratio 1.0000`).

## 2. Strip counts observed, both arms -- how computed

Each row's `stats.strips` field is the strip count `_pack`/`_pack_window` were called with for that cell.
Computed directly from the two committed `.jsonl` files:

```python
import json

GATE = "docs/superpowers/evidence/2026-09-07-lane-fanout/gate"

for name in ["audit-task3-small-before.jsonl", "audit-task3-small-after.jsonl"]:
    strips = []
    with open(f"{GATE}/{name}") as f:
        for line in f:
            d = json.loads(line)
            strips.append(d["stats"]["strips"])
    print(name, "min:", min(strips), "max:", max(strips), "n:", len(strips))
```

Output:
```
audit-task3-small-before.jsonl min: 1.0 max: 6.0 n: 30
audit-task3-small-after.jsonl  min: 1.0 max: 6.0 n: 30
```

Every one of the 30 small-tier cells, in both arms, packs at most **6** strips.

## 3. Zero small cells reach `_DETERMINISTIC_PACK_STRIPS` (15)

`_DETERMINISTIC_PACK_STRIPS = 15` (`freeform.py:354`). The maximum observed strip count in either arm is
6, so `len(strips) >= _DETERMINISTIC_PACK_STRIPS` is `False` for every cell in the small tier.

## 4. The two guard sites that make `_deterministic_pack_work` unreachable below fifteen strips

`_deterministic_pack_work` has exactly two call sites in `src/`, and both are behind a guard that is
`False` for every small-tier cell:

- **The solver call site**, `freeform.py:5351` (`_pack`'s `max_deterministic_time` assignment), executes
  only `if deterministic:` (`freeform.py:5346`). `_pack`'s `deterministic` parameter defaults to `False`
  (`freeform.py:5297`, `deterministic: bool = False`). The only place in `src/` that ever passes
  `deterministic=True` is `freeform.py:21620`:
  ```python
  deterministic=len(strips) >= _DETERMINISTIC_PACK_STRIPS,
  ```
  which is `False` whenever `len(strips) < 15` -- true of every small-tier cell (max 6, see §2). The
  `sequence-pair` strategy's own `_pack` call, `sequence_solver.py:6029`, passes no `deterministic=`
  keyword at all, so it always takes the `False` default regardless of strip count -- meaning this call
  site is unreachable for `sequence-pair` cells of ANY size, not only small ones.
- **The refusal-message call site**, `freeform.py:20731` (inside the UNKNOWN-refusal sentence), is gated
  by its own `if len(strips) >= _DETERMINISTIC_PACK_STRIPS:` at `freeform.py:20733` -- same threshold,
  same reason it never fires below 15 strips.

So for every cell in the small tier, `_deterministic_pack_work` is called **zero times** in both the
BEFORE and AFTER trees. Both arms run the identical code path regardless of which form
(`_deterministic_pack_work`'s body) is shipped -- which is exactly why the two arms produced identical
areas, identical CLEAN counts, and (per the same commit-hash caveat below) look indistinguishable.

Note on the `commit` field: `task-3-report.md` originally claimed the two arms' `commit` field in their
JSONL rows "confirms the distinct trees." That claim is false and is struck in the report: `audit.py`
records `git rev-parse HEAD` (or equivalent), which reflects the last **commit**, not the working tree's
uncommitted edits -- so both arms (run against the same HEAD, one with my edits stashed out and one with
them restored) show the identical commit SHA `3208615671ec9c8c3293a4c9c656126bb119ee6d` on all 60 rows.
That field never discriminated the two trees; the reachability argument in this file is what does.

## 5. Conclusion: the shipped form is licensed by reachability, not by the small-tier measurement

Because every call to `_deterministic_pack_work` in `src/` -- both the solver site and the refusal-message
site -- is reached only when `strip_count >= _DETERMINISTIC_PACK_STRIPS` (15), and because
`_deterministic_pack_work(strip_count) = _DETERMINISTIC_PACK_WORK_AT_CALIBRATED_SIZE * strip_count / 15`
is, for every `strip_count >= 15`, numerically **identical** between the plain-linear form actually shipped
and the floored form (`max(0.02, ...)`) the brief offered as the fallback -- the two forms can only ever
differ below `strip_count = 15`, exactly where neither call site ever reaches. The small-tier corpus
measurement (30/30 CLEAN, identical in both arms) is consistent with this reachability argument but does
not, by itself, discriminate between the two candidate forms: it would have produced the same result no
matter which form had been shipped, since neither form's difference is ever evaluated on cells this small.
The plain-linear form was shipped because it is the simpler of two forms that behave identically on every
reachable input, not because the small-tier audit ruled out a regression from the floored form (there was
never a regression to rule out at this strip count either way).

## 6. `C_WINDOW_DETERMINISTIC_WORK` is unchanged

`C_WINDOW_DETERMINISTIC_WORK = 25 * _DETERMINISTIC_PACK_WORK_AT_CALIBRATED_SIZE` (`freeform.py:4421`) is a
pure rename of `25 * _DETERMINISTIC_PACK_WORK` (the pre-Task-3 name for the same `0.02` constant):

```
25 * 0.02 = 0.5
```
before this change and after it, identically -- `_DETERMINISTIC_PACK_WORK_AT_CALIBRATED_SIZE` was never
reassigned, only renamed. `_pack_window`'s `deterministic_work` default is therefore still exactly `0.5`
for every window solve, exactly as it was before Task 3.
