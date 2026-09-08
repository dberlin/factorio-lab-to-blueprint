# Task 12 — render-transform bounds

## Boundary and evidence

Implementation prepared; Main owns GREEN/static/browser/review/commit and this worker ran no validation. Main observed pre-source semantic RED in `display-facts-bounds-red.log`, exit 1: model max x 23.36 versus actual transformed corner 21.605 (difference 1.755). The fixture uses separated rectangular plants at 0, 90 and 37 degrees rather than an isolated rectangle with invariant diagonal.

Main subsequently reported selected API/report/layout/camera GREEN: exit 0, 59 cases in `display-facts-bounds-green.log`. Actual-browser framing and final static/review remain pending integration.

## Change and ownership

Only two bounds expansion expressions change in model/layout.ts, using already computed sin/cos and actual visual size. Center rotation, visual dimensions/scales, catalog physical dimensions and BuildingInstances' instance transform are unchanged. CameraRig continues consuming the resulting center/radius. No new geometry owner or framework.

LSP references for buildSceneModel unavailable (No language server found). Complete fallback inventory: provider, model/layout tests, traceScene tests, beltRibbons tests and sorterModels tests. Signature unchanged; consumers intentionally unchanged.

## Main proof

From web run `bun run test tests/model/layout.test.ts tests/scene/camera.test.ts`. Regression `separated rotated boxes fit model bounds and camera framing` independently transforms every unit-box corner with three.js rotation/scale/translation, requires exact combined bounds extrema and checks every corner inside the framing sphere and short viewport dimension.

Actual browser: use a trace frame containing chemical plants item 2309/model 70 at blueprint (-20,0), (20,-20), (0,20) and yaws 0,90,37; turn machines solid. Select the frame deliberately, frame the scene, then use Q/E and top-down O. All three separated rotated plants must fit. Preserve their actual render dimensions and offset centers; take screenshots including the non-quarter-turn plant. Browser proof unrun; Main records actual observations and removes throwaway instrumentation.
