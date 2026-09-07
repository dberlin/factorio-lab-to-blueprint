import { expect, rstest, test } from '@rstest/core';
import { render, screen } from '@testing-library/react';
import type { Blueprint } from '../../src/format/types';
import type { SceneModel } from '../../src/model/layout';
import type { BlueprintState } from '../../src/state/BlueprintProvider';
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

// A mutable stand-in for the provider, so different tests in this file can
// exercise Toolbar against different `snapshotLabel`/`stale` combinations
// without re-mocking the module per test.
let mockState: Partial<BlueprintState> = {
  blueprint,
  sceneModel,
  selectedIndex: null,
  select: () => {},
  stale: false,
  snapshotLabel: null,
};

rstest.mock('../../src/state/BlueprintProvider', () => ({
  useBlueprint: () => mockState,
}));

test('reports unresolved belt tags', () => {
  mockState = {
    blueprint,
    sceneModel,
    selectedIndex: null,
    select: () => {},
    stale: false,
    snapshotLabel: null,
  };
  render(<Toolbar />);
  expect(screen.getByText(/2 unrecognised belt tag/)).toBeDefined();
});

test('the canvas label reads TRACE while a snapshot is on the canvas, and reverts once a real result loads', () => {
  const traceCaption = 'TRACE · freeform · all-products · incumbent · 12 tiles';
  mockState = {
    blueprint,
    sceneModel,
    selectedIndex: null,
    select: () => {},
    stale: false,
    snapshotLabel: traceCaption,
  };
  const { rerender } = render(<Toolbar />);

  // While a snapshot is shown, this caption is the ONLY label -- the real
  // title never appears alongside it, so there is nothing on the canvas
  // that could be mistaken for a named result.
  const label = screen.getByTestId('trace-label');
  expect(label).toHaveTextContent(traceCaption);
  // `<output>` carries an implicit `status` role, so this is announced on
  // each poll without an explicit `role` attribute.
  expect(label.tagName).toBe('OUTPUT');
  expect(screen.getByRole('status')).toBe(label);
  expect(screen.queryByText('Test')).toBeNull();

  // A real result clears `snapshotLabel` back to null (BlueprintProvider.load);
  // simulating that here as a re-render is what confirms the label reverts
  // rather than getting stuck showing a stale trace caption.
  mockState = { ...mockState, snapshotLabel: null };
  rerender(<Toolbar />);

  expect(screen.getByText('Test')).toBeDefined();
  expect(screen.queryByTestId('trace-label')).toBeNull();
});
