# A/B density comparison (generated)

- tiers=trivial+small+mid  budgets=['2s', '8s']  repeat=3  candidates=3  power=off  urls=8
- CP-SAT runs multi-worker (the shipping default), so it is nondeterministic by design; repeats measure that, they do not remove it.
- cross-validation: 189/189 blueprints decoded with a valid MD5F hash and a matching building count

**Winner is stable across budgets ['2s', '8s']: spine.**

## budget = 2s

```
COVERAGE at budget=2s (denominator: 8 URLs attempted)
  spine      valid on 8/8 URLs (8/8 on every repeat)
  freeform   valid on 8/8 URLs (8/8 on every repeat)
DENSITY (paired, denominator: 8/8 URLs where BOTH shipped)
  geometric mean B/A = 1.188  -> spine is 18.8% denser over those 8 URLs
  separated from run-to-run noise on 7/8 of them: spine 5, freeform 2, tie 0
  solver noise floor (median spread/median area): spine 0.0%, freeform 0.0%

spec                            spine area    ok     freeform area    ok     B/A  sep    A s    B s
---------------------------------------------------------------------------------------------------
iron-ingot                              15   3/3                20   3/3   1.33x  yes   0.0s   0.0s
magnetic-coil                           68   3/3                96   3/3   1.41x  yes   0.0s   0.1s
    freeform: only 1/3 candidates laid out
graphene                               418   3/3               440   3/3   1.05x  yes   0.1s   0.2s
    freeform: only 2/3 candidates laid out
electromagnetic-matrix                 351   3/3               340   3/3   0.97x  yes   0.1s   4.0s
    spine: only 1/3 candidates laid out
    freeform: only 1/3 candidates laid out
plastic                                460   3/3               440   3/3   0.96x  yes   0.0s   0.1s
    spine: only 2/3 candidates laid out
processor                              465   3/3     504 [418-504]   3/3   1.08x   no   0.1s   4.8s
    spine: only 1/3 candidates laid out
    freeform: only 1/3 candidates laid out
energy-matrix                          460   3/3               640   3/3   1.39x  yes   0.0s   0.1s
    spine: only 1/3 candidates laid out
    freeform: only 2/3 candidates laid out
super-magnetic-ring                   1060   3/3  1517 [1209-1710]   3/3   1.43x  yes   0.4s  41.6s
    freeform: only 1/3 candidates laid out

Composition on the paired URLs (median over repeats):
spec                       A blds   B blds   A belt   B belt  A d.ins  B d.ins
------------------------------------------------------------------------------
iron-ingot                      9       10        6        7        0        0
magnetic-coil                  42       61       31       47        1        0
graphene                      250      187      217      157        0        0
electromagnetic-matrix        216      179      177      144        0        0
plastic                       216      168      189      141        0        0
processor                     311      327      254      250        0        0
energy-matrix                 241      245      199      194        0        0
super-magnetic-ring           783     1215      662      974        0        0
```

## budget = 8s

```
COVERAGE at budget=8s (denominator: 8 URLs attempted)
  spine      valid on 8/8 URLs (8/8 on every repeat)
  freeform   valid on 8/8 URLs (8/8 on every repeat)
DENSITY (paired, denominator: 8/8 URLs where BOTH shipped)
  geometric mean B/A = 1.155  -> spine is 15.5% denser over those 8 URLs
  separated from run-to-run noise on 7/8 of them: spine 5, freeform 2, tie 0
  solver noise floor (median spread/median area): spine 0.0%, freeform 0.0%

spec                            spine area    ok     freeform area    ok     B/A  sep    A s    B s
---------------------------------------------------------------------------------------------------
iron-ingot                              15   3/3                20   3/3   1.33x  yes   0.0s   0.0s
magnetic-coil                           68   3/3                96   3/3   1.41x  yes   0.0s   0.1s
    freeform: only 1/3 candidates laid out
graphene                               418   3/3               440   3/3   1.05x  yes   0.1s   0.2s
    freeform: only 2/3 candidates laid out
electromagnetic-matrix                 351   3/3               340   3/3   0.97x  yes   0.1s   4.1s
    spine: only 1/3 candidates laid out
    freeform: only 1/3 candidates laid out
plastic                                460   3/3               440   3/3   0.96x  yes   0.0s   0.1s
    spine: only 2/3 candidates laid out
processor                              465   3/3     504 [418-504]   3/3   1.08x   no   0.1s   4.1s
    spine: only 1/3 candidates laid out
    freeform: only 1/3 candidates laid out
energy-matrix                          460   3/3               640   3/3   1.39x  yes   0.0s   0.1s
    spine: only 1/3 candidates laid out
    freeform: only 2/3 candidates laid out
super-magnetic-ring                   1060   3/3  1209 [1209-1562]   3/3   1.14x  yes   0.4s  53.7s
    freeform: only 1/3 candidates laid out

Composition on the paired URLs (median over repeats):
spec                       A blds   B blds   A belt   B belt  A d.ins  B d.ins
------------------------------------------------------------------------------
iron-ingot                      9       10        6        7        0        0
magnetic-coil                  42       61       31       47        1        0
graphene                      250      187      217      157        0        0
electromagnetic-matrix        216      179      177      144        0        0
plastic                       216      168      189      141        0        0
processor                     311      327      254      250        0        0
energy-matrix                 241      245      199      194        0        0
super-magnetic-ring           783     1035      662      845        0        0
```

## How to read this

Coverage is stated before density and the density ratio names its own
denominator, because an area ratio over the subset where both strategies
happened to succeed is not a corpus-wide claim. Only placements the
validator accepted contribute an area: invalid layouts are systematically
smaller, since an unrouted net is a belt run that does not exist, so
scoring them rewards dropping connections rather than packing well.
