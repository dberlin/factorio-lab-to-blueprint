import { expect, rstest, test } from '@rstest/core';
import { fireEvent, render, screen } from '@testing-library/react';
import type { Blueprint } from '../../src/format/types';
import type { SceneModel } from '../../src/model/layout';
import type { BlueprintState } from '../../src/state/BlueprintProvider';
import { Toolbar } from '../../src/ui/Toolbar';
import type { TraceFrame } from '../../src/api/trace';

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
const view = {
  beltLabels: true,
  sorterTies: true,
  endpointIcons: true,
  machines: 'ghosted' as const,
};

let mockState: Partial<BlueprintState> = {
  blueprint,
  sceneModel,
  selectedIndex: null,
  select: () => {},
  stale: false,
  snapshotLabel: null,
  view,
  setView: () => {},
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
    view,
    setView: () => {},
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
    document: {
      kind: 'trace',
      generation: 1,
      blueprint,
      jobId: 'trace',
      frame: {} as TraceFrame,
      label: traceCaption,
    },
    view,
    setView: () => {},
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

  // A successful artifact publication replaces trace provenance atomically.
  mockState = {
    ...mockState,
    document: { kind: 'artifact', generation: 2, blueprint, text: '', source: { kind: 'import' } },
  };
  rerender(<Toolbar />);

  expect(screen.getByText('Test')).toBeDefined();
  expect(screen.queryByTestId('trace-label')).toBeNull();
});

test('the layer switches report what the viewer should stop drawing', () => {
  const calls: unknown[] = [];
  mockState = {
    blueprint,
    sceneModel,
    selectedIndex: null,
    select: () => {},
    stale: false,
    snapshotLabel: null,
    view,
    setView: (next) => calls.push(next),
  };
  render(<Toolbar />);

  // Both layers start on: a blueprint is more legible with them than without,
  // and the switches exist for the busy cases.
  const labels = screen.getByLabelText('belt numbers') as HTMLInputElement;
  const ties = screen.getByLabelText('sorter ties') as HTMLInputElement;
  expect(labels.checked).toBe(true);
  expect(ties.checked).toBe(true);

  fireEvent.click(labels);
  expect(calls[0]).toEqual({ ...view, beltLabels: false });

  fireEvent.click(ties);
  expect(calls[1]).toEqual({ ...view, sorterTies: false });

  // The inferred endpoint icons are a third quietable layer, and the one most
  // worth quieting: a generated blueprint infers an item at nearly every lane
  // end, and sometimes the shapes alone are what you want to look at.
  const endpoints = screen.getByLabelText('endpoint icons') as HTMLInputElement;
  expect(endpoints.checked).toBe(true);
  fireEvent.click(endpoints);
  expect(calls[2]).toEqual({ ...view, endpointIcons: false });

  // Machines ghost by default, because at ground level almost everything worth
  // reading is underneath them.
  const machines = screen.getByLabelText('machines') as HTMLSelectElement;
  expect(machines.value).toBe('ghosted');
  fireEvent.change(machines, { target: { value: 'solid' } });
  expect(calls[3]).toEqual({ ...view, machines: 'solid' });
});
