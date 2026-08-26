import { expect, rstest, test } from '@rstest/core';
import { render } from '@testing-library/react';
import type { SceneModel } from '../../src/model/layout';
import { BlueprintCanvas } from '../../src/scene/BlueprintCanvas';

// r3f sizes its canvas from react-use-measure, which hands the *same* debounced
// callback to its ResizeObserver and its scroll listener, sharing one timer.
// With r3f's default `debounce: { scroll: 50, resize: 0 }` the canvas' only
// ResizeObserver delivery (the initial observation — the container size never
// changes afterwards) sits behind a 50ms timer that any scroll event resets,
// and the canvas is then never sized at all. Guard the opt-out.
const captured: { props: Record<string, unknown> } = { props: {} };

rstest.mock('@react-three/fiber', () => ({
  Canvas: (props: Record<string, unknown>) => {
    captured.props = props;
    return <div data-testid="r3f-canvas" />;
  },
}));

const sceneModel = { instances: [], unknownItemIds: [] } as unknown as SceneModel;

rstest.mock('../../src/state/BlueprintProvider', () => ({
  useBlueprint: () => ({ sceneModel, selectedIndex: null, select: () => {} }),
}));

// BlueprintCanvas loads the icon atlas on mount. Unmocked, that is a real
// fetch: happy-dom resolves '/assets/icons/atlas.json' against its default
// document origin (http://localhost:3000), so the test hits the network and
// fails or hangs depending on what happens to be listening on that port —
// surfacing as ECONNRESET/"socket hang up" when the unmount aborts it. This
// test is about a prop on <Canvas>; it should touch no I/O at all.
rstest.mock('../../src/state/assets', () => ({
  loadAtlas: () => Promise.resolve({ cell: 64, cols: 1, rows: 1, entries: {} }),
  isAbortError: () => false,
  // The atlas PNG resolves through the same production asset path as the
  // catalog JSON. The mock carries it so the component can load its texture.
  assetPath: (relative: string) => `/assets/${relative}`,
}));

test('opts out of the debounced/scroll-shared measurement that leaves the canvas unsized', () => {
  render(<BlueprintCanvas />);
  expect(captured.props.resize).toEqual({ debounce: 0, scroll: false });
});
