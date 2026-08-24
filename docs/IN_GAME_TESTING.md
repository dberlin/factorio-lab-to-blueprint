# In-game testing

Everything else in this project is our validator agreeing with itself. The only
check that is not circular is pasting a blueprint into Dyson Sphere Program, and
that costs a human a context switch -- so each paste should be a repeatable
experiment rather than a fresh unknown.

## The fixed test location

    galaxy seed  77415848
    planet       Rotanen 4

Planet data for a seed can be generated without launching the game with
**DSP-Seed-Finder** (<https://github.com/DoubleUTH/DSP-Seed-Finder>); the live
instance for this galaxy is
<https://doubleuth.github.io/DSP-Seed-Finder/galaxy/77415848/0>.

**Use the same planet, and as near as practical the same spot, for every test
paste.** Two of the four errors from the first real paste (2026-08-24) are
sensitive to *where* you paste, not to what the blueprint contains:

* **`NeedGround` ("Foundation required")** is a per-landing-point terrain
  raycast at paste time -- it fires when the ray hits below `-0.3 - landOffset`,
  when ground and water differ by more than `0.27 + landOffset`, or when nothing
  is hit at all. The identical blueprint pastes cleanly one tile away. **No
  offline check can predict it**, and levelling the ground answers it. A paste
  onto uneven terrain therefore tells us nothing about our data.
* **`Collide` ("Collide with other object")** is only diagnostic on genuinely
  empty ground. With veins, rocks or an earlier build in range there is no way
  to tell an internal collision from a world one.

A result is only comparable to an earlier result if the location matches. When a
fixed blueprint is handed back with "does this still error?", the answer means
nothing if the spot changed.

## What the seed does NOT give us

The seed makes the human's pastes cheap and repeatable. It does **not** move the
verification loop onto the build machine: nothing here runs the game, so a paste
cannot be reproduced locally. Whether the seed finder exposes enough terrain
detail to predict `NeedGround` offline is **unverified** -- it would need actual
per-point heights, not just planet type and vein layout. Do not assume it does.

## Protocol

1. Same planet, same spot, ground levelled if the test is not about terrain.
2. Record which blueprint file was pasted, and keep the file -- blueprint
   strings are long enough that transcribing one is its own source of error.
3. Report the exact error text. The English strings map to `EBuildCondition`
   members via `Locale/1033/base.txt` (UTF-16LE, tab-separated), and the member
   is what the decompiled source can be searched for. Note that the mapping is
   not always the obvious one: `偏角太大` / "Deflection too much" is `TooSkew`,
   **not** `TooBend`.
4. If the game re-serialises the blueprint (copying it back out after a paste),
   that output is worth capturing -- the game's own normalisation is the closest
   thing to a specification we get, and it is how we established that our
   encoder is byte-faithful.
