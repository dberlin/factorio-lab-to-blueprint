import { expect, rstest, test } from '@rstest/core';
import { render, screen } from '@testing-library/react';
import type { Blueprint } from '../../src/format/types';
import type { SceneModel } from '../../src/model/layout';
import { Toolbar } from '../../src/ui/Toolbar';

const sceneModel = {
  instances: [],
  beltRuns: [],
  beltHeadings: new Map(),
  unknownItemIds: [],
  unresolvedTagIds: [40001, 40002],
} as unknown as SceneModel;

// Toolbar returns "No blueprint loaded" and renders nothing else when
// `blueprint` is null, so the mock must supply one or the assertion can
// never pass.
const blueprint = {
  header: { shortDesc: 'Test', gameVersion: '0.10.34' },
  buildings: [],
  areas: [],
} as unknown as Blueprint;

rstest.mock('../../src/state/BlueprintProvider', () => ({
  useBlueprint: () => ({ blueprint, sceneModel, selectedIndex: null, select: () => {} }),
}));

test('reports unresolved belt tags', () => {
  render(<Toolbar />);
  expect(screen.getByText(/2 unrecognised belt tag/)).toBeDefined();
});
