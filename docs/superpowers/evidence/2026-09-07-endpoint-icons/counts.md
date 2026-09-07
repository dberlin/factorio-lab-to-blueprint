# Endpoint icon counts, before and after

`count-icons.ts` runs the real render pipeline (`parseBlueprint` ->
`buildSceneModel` -> `buildOverlays`) and reports how many icon quads
`IconInstances` would draw. Endpoint icons are isolated by calling
`buildOverlays` a second time with `beltRuns: []` -- the only input the
endpoint loop reads -- and subtracting; that works identically on both
commits, so the two columns are comparable.

Run as:

    cd web && bun run docs/superpowers/evidence/2026-09-07-endpoint-icons/count-icons.ts "$PWD" <blueprint.txt ...>

before = master `ffe9e304`, after = `endpoint-icons`.

| blueprint | endpoint icons before | after | other icons (both) | "+N" badges after |
| --- | --- | --- | --- | --- |
| generated: `2026-09-06-selfloop/probes/bp-default.txt` (2105 buildings) | 117 | 30 | 95 | 11 |
| real: `factory-heretical-smelter-block.txt` (591 buildings) | 0 | 0 | 111 | 0 |
| real: `factory-endgame-distribution-hub.txt` (1969 buildings) | 0 | 0 | 97 | 0 |

Supporting numbers on the generated blueprint: 69 belt runs, of which 64 had
`freeInput` before and 47 after (the other 17 heads are fed by a sorter);
free ends fell from 119 to 102, and the icons drawn at those ends from 117
to 30 because the two-sided inference pins most lanes to one item.

The real fixtures label their belts with explicit in-game tags, so their runs
never reached the inference at all -- 0 endpoint icons on both commits. What
had to be preserved there is the 111 and 97 icons they do draw, and both
counts are unchanged. Of the heretical block's 111, 11 are belt tags (now
drawn at the ribbon-relative size) and 100 sit on machines (unchanged size);
for the endgame hub it is 47 and 50.

## Screenshots

Headless Chromium (Playwright, SwiftShader), 1600x1000, the generated
blueprint loaded through the paste box of `rsbuild dev`:

- `before-generated.png` / `after-generated.png` -- whole blueprint.
- `before-generated-zoom2.png` / `after-generated-zoom2.png` -- same camera,
  30 scroll-zoom steps in. The before frame has item icons roughly two tiles
  across lying over the lanes and hiding the run numbers; the after frame
  keeps the numbers legible.
- `after-heretical.png` -- the heretical smelter block still showing its
  icons.
