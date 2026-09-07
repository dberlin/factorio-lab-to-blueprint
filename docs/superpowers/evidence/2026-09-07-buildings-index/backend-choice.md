# Which index backend does `Buildings` use?

The brief asked for `littletable`; the user later offered `polars` as an
alternative for immutable holders. Both were measured before the plan chose,
because the point of the abstraction is to be *faster*, and an indexed lookup
that costs more than the scan it replaces is a pessimisation wearing a
library's name.

Reproduce with:

```
uv run --with littletable --with polars python \
  docs/superpowers/evidence/2026-09-07-buildings-index/backend_bench.py
```

## Real blueprints (decoded from `tests/fixtures/*.txt`)

`littletable==3.0.2`, `polars==1.44.1`, CPython 3.14. One indexed lookup by
`recipe_id`; build columns are the one-time cost of constructing the index over
every key. CPU pressure during the run: 6 runnable procs (`vmstat 1 6`, mean of
last 5), well under the box's 64 threshold.

| fixture | N | build dict | build littletable | build polars | query: scan | littletable | polars | dict |
|---|---|---|---|---|---|---|---|---|
| factory-quick-start-step-3-red-cube | 287 | 3.83 ms | 0.30 ms | 1.55 ms | 8.4 us | 23.7 us | 189.1 us | **0.100 us** |
| factory-heretical-smelter-block | 591 | 0.98 ms | 0.83 ms | 1.08 ms | 21.7 us | 155.9 us | 206.5 us | **0.100 us** |
| factory-endgame-distribution-hub | 1969 | 4.83 ms | 4.38 ms | 5.21 ms | 141.0 us | 3245.9 us | 342.6 us | **0.208 us** |
| tillable-blackbox-module-polar-artificial-stars | 351 | 0.94 ms | 1.72 ms | 1.16 ms | 7.3 us | 14.2 us | 220.7 us | **0.181 us** |

## Synthetic sweep at this project's real building counts

Realistic record shape (`recipe_id`, `kind`, `carries_item`, `input_obj`,
`output_obj`), 40 distinct recipes, 25 distinct items. Corpus blueprints run
roughly 500 to 6000 buildings (largest observed: 5993, hierarchical-v3 gate).

| N | build dict | build littletable | build polars | query: scan | littletable | polars | dict |
|---|---|---|---|---|---|---|---|
| 1000 | 5.69 ms | 1.40 ms | 1.75 ms | 27.3 us | 62.2 us | 200.5 us | **0.130 us** |
| 2100 | 5.20 ms | 2.96 ms | 2.95 ms | 56.7 us | 112.5 us | 219.9 us | **0.101 us** |
| 6000 | 17.34 ms | 9.11 ms | 7.64 ms | 163.4 us | 292.4 us | 295.8 us | **0.140 us** |

Two further measurements that closed off the obvious workarounds:

- Harvesting every group out of a littletable index once, so later lookups
  could hit a plain dict, costs **203 ms at N=4000** and **1175 ms at
  N=20000** — the harvest alone is more expensive than every scan it would
  save. `Table.get_index(attr)[key]` materialises a `Table` per key, so
  bulk extraction pays that cost once per distinct key value.
- `table.where(recipe_id=3)` measured 181 us at N=4000, indistinguishable
  from `table.by.recipe_id[3]` — the index is not the slow part; the
  per-query `Table` construction is.

## Finding

At every size this project produces, both libraries are **slower than the
linear scan they would replace**:

- `littletable.Table.by.<attr>[value]` : 1.7x to **23x slower** than the scan
  (it builds a new `Table` per query).
- `polars.DataFrame.filter(...)` : 1.5x to 22x slower on small collections,
  and only ~1.8x faster than the scan at N=20000 — far above anything the
  corpus emits. Its fixed per-call overhead is ~200 us regardless of N.
- A plain `dict[key, tuple[int, ...]]` built in one O(n) pass: **0.1-0.2 us**
  per query, 200x to 1600x faster than the scan, with a build cost in the
  same order as the library builds.

Polars would also be the wrong shape for a second reason the coordinator
anticipated: it is a columnar frame, and the queries here return *positional
indices into the buildings tuple* which callers then use to index back into
Python objects. Every polars answer would pay a `to_list()` boundary crossing
to get back to the Python ints the callers need.

## Ruling

`Buildings` gets the interface the user asked for — a real abstraction with
named, indexed queries — backed by plain dict indexes built in one pass.
**Neither littletable nor polars is added.** This benchmark is committed so
the decision is reproducible and so a future maintainer who wants the library
back can re-run it rather than re-argue it.

Cost if wrong: the user wanted a named library in the tree. The backend lives
behind the `Buildings` interface in one module, so swapping a dict index for a
`littletable.Table` later is a single-file change with no call-site churn.
