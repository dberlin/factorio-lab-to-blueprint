# Task 3 control: single-cell byte-identical build (branch vs master)

Reversed from a Step-7 skip in the original dispatch: `bounds` sits on nearly
every code path and eight more tasks build on it, so this proof is done now
rather than deferred to Task 11's twelve-cell control.

## Preconditions

```
$ pgrep -fc 'python[0-9.]* +[^ ]*scripts/audit\.py'
0
$ vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print sum/5}'
6.2
```

No `audit.py` running; CPU pressure 6.2, well below the 64 threshold. One
build ran at a time.

## Cell

The smallest corpus cell, `URL_CORPUS`'s `"iron-ingot"` entry (Tier.TRIVIAL,
1 machine, "a single smelter, no belts between machines"):

```
https://factoriolab.github.io/dsp/list?o=iron-ingot*60&ibe=conveyor-belt-2&mmr=arc-smelter~assembling-machine-2~chemical-plant~matrix-lab&v=11
```

## Branch build

Built in this worktree (`.claude/worktrees/buildings-index`, commit
`ac4e77c2` at the time of this build, `uv sync`'d, `flab2bp.__file__`
confirmed inside the worktree):

```
$ uv run flab2bp "$URL" --workers 1 --sequence-islands 1 -o /tmp/task3-cell-branch.txt -v
...
written to /tmp/task3-cell-branch.txt
$ wc -c /tmp/task3-cell-branch.txt
544 /tmp/task3-cell-branch.txt
```

## Master build

Built in a throwaway worktree at the merge base `2e861af0`, added under
`/tmp` (NOT under `.claude/worktrees/`):

```
$ git worktree add /tmp/flab2bp-master-control 2e861af0
$ cd /tmp/flab2bp-master-control && uv sync
$ uv run python -c "import flab2bp; print(flab2bp.__file__)"
/tmp/flab2bp-master-control/src/flab2bp/__init__.py       # confirmed inside the throwaway tree
$ uv run flab2bp "$URL" --workers 1 --sequence-islands 1 -o /tmp/task3-cell-master.txt -v
...
written to /tmp/task3-cell-master.txt
$ wc -c /tmp/task3-cell-master.txt
544 /tmp/task3-cell-master.txt
```

Removed afterward: `git worktree remove /tmp/flab2bp-master-control`.

## Byte diff

```
$ cmp -l /tmp/task3-cell-branch.txt /tmp/task3-cell-master.txt | wc -l
41
```

41 of 544 bytes differ. Isolating exactly which bytes, with a small Python
script over both files:

```python
a = open('/tmp/task3-cell-branch.txt','rb').read()
b = open('/tmp/task3-cell-master.txt','rb').read()
# payload region 46-512 equal: True
```

- **Bytes 46-512 (the entire base64 gzip payload `H4sI...UDAAA=`, which is
  the serialized layout geometry) are byte-for-byte IDENTICAL.**
- The only differing bytes are:
  - **Bytes 36-45**: the blueprint header's timestamp field —
    `639243953396986880` (branch) vs `639243954100647296` (master).
  - **Bytes 513-544** (minus the closing `"` at 529, which matches): the
    trailing checksum — `4C0771E30043C093A39ADF045902AB24` (branch) vs
    `FBEC97408A0C08C4A0E7FDDBC4B308F9` (master).

## Why the timestamp and checksum differ, and why that is not a divergence

`src/flab2bp/dsp/codec.py:376`:
```python
timestamp=timestamp if timestamp is not None else dotnet_ticks(time.time()),
```
The CLI's default blueprint encoding path stamps the current wall-clock time
(as .NET ticks) into the header whenever no explicit timestamp is passed —
this is true on both master and this branch, unchanged by Task 3, and
guarantees two separate invocations of the *same* binary will already differ
here even with no code change at all between them. The trailing checksum is
computed over the full string including that timestamp, so it changes as a
direct, mechanical consequence of the timestamp changing — not from anything
this task touched.

## Conclusion

The one thing this task could plausibly have changed — the serialized
building layout, i.e. the compressed payload between the header and the
checksum — is byte-for-byte identical between master at the merge base
(`2e861af0`) and this branch's `Placement.bounds` memoisation. The two
differing regions are the wall-clock timestamp and its downstream checksum,
both accounted for by a specific, unrelated line of pre-existing code
(`codec.py:376`), present identically on both sides. This is not "explaining
away" a divergence in what this task controls — it is showing precisely
which bytes differ, and that none of them fall inside the geometry this
task's memoisation could have affected.
