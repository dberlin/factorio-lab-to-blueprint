import { expect, test } from '@rstest/core';
import { frameZoom, isoPosition, shouldIgnoreKeyTarget } from '../../src/scene/CameraRig';

test('camera sits above and away from the centre', () => {
  const p = isoPosition([0, 0, 0], 10, 0);
  expect(p[1]).toBeGreaterThan(0);
  expect(Math.hypot(p[0], p[2])).toBeGreaterThan(0);
});

test('each quarter turn rotates the camera about the centre without changing height', () => {
  const center: [number, number, number] = [0, 0, 0];
  const a = isoPosition(center, 10, 0);
  const b = isoPosition(center, 10, 1);

  // Height is unchanged by a rotation about the centre.
  expect(b[1]).toBeCloseTo(a[1]);

  // Horizontal distance from the centre is unchanged by a rotation about it.
  const distA = Math.hypot(a[0] - center[0], a[2] - center[2]);
  const distB = Math.hypot(b[0] - center[0], b[2] - center[2]);
  expect(distB).toBeCloseTo(distA);

  // The (x, z) pair itself must differ from the previous turn — a 90-degree
  // rotation about the centre is not the identity. Note: at the corner-on
  // 45-degree phase this project uses, a single quarter turn can leave one
  // of the two coordinates unchanged (only the other flips sign) — that is
  // correct geometry, so this must assert on the pair, not on x alone.
  const samePosition =
    Math.abs(b[0] - a[0]) < 0.005 * Math.max(1, Math.abs(a[0])) &&
    Math.abs(b[2] - a[2]) < 0.005 * Math.max(1, Math.abs(a[2]));
  expect(samePosition).toBe(false);
});

test('four quarter turns return to the start', () => {
  const a = isoPosition([0, 0, 0], 10, 0);
  const d = isoPosition([0, 0, 0], 10, 4);
  expect(d[0]).toBeCloseTo(a[0]);
  expect(d[2]).toBeCloseTo(a[2]);
});

test('the rig is offset by the model centre', () => {
  const p = isoPosition([100, 0, -50], 10, 0);
  const o = isoPosition([0, 0, 0], 10, 0);
  expect(p[0] - o[0]).toBeCloseTo(100);
  expect(p[2] - o[2]).toBeCloseTo(-50);
});

test('the opening view is corner-on (45-degree azimuth), not axis-aligned', () => {
  // With the centre at the origin, a corner-on view puts the camera at an
  // azimuth equidistant between the +X and +Z axes, so its x and z offsets
  // from the centre must be approximately equal — and, since the camera
  // sits above and outward from the centre rather than behind it, both
  // positive. An axis-aligned default (0 or 90 degrees) would instead put
  // one of the two coordinates near zero, which this test must catch.
  const p = isoPosition([0, 0, 0], 10, 0);
  expect(p[0]).toBeGreaterThan(0);
  expect(p[2]).toBeGreaterThan(0);
  expect(p[0]).toBeCloseTo(p[2]);
});

test('zoom frames the model and shrinks as the model grows', () => {
  // The framed extent is min(width, height); a radius-10 sphere across a
  // 520px-tall viewport must fit, i.e. radius * zoom < half the short side.
  const viewport = { width: 1000, height: 520 };
  const zoom = frameZoom(10, viewport);
  expect(zoom).toBeGreaterThan(0);
  expect(10 * zoom).toBeLessThan(viewport.height / 2);
  // Twice the radius must be half the zoom, and a taller viewport zooms in.
  expect(frameZoom(20, viewport)).toBeCloseTo(zoom / 2);
  expect(frameZoom(10, { width: 1000, height: 1000 })).toBeGreaterThan(zoom);
});

// The Q/E/O camera shortcuts listen on `window`, so without this guard every
// `e`, `q` or `o` typed into the blueprint textarea would also rotate the
// camera or toggle orbit — and blueprint payloads are base64, so those
// letters are everywhere. See shouldIgnoreKeyTarget in CameraRig.tsx.
test('key shortcuts are ignored while typing in a text-entry element', () => {
  const textarea = document.createElement('textarea');
  expect(shouldIgnoreKeyTarget(textarea)).toBe(true);

  const input = document.createElement('input');
  expect(shouldIgnoreKeyTarget(input)).toBe(true);

  const select = document.createElement('select');
  expect(shouldIgnoreKeyTarget(select)).toBe(true);

  // Both spellings: happy-dom does not reflect the `contentEditable` property
  // to the attribute the way a real DOM does, so pin each independently.
  const editableProp = document.createElement('div');
  editableProp.contentEditable = 'true';
  expect(shouldIgnoreKeyTarget(editableProp)).toBe(true);

  const editableAttr = document.createElement('div');
  editableAttr.setAttribute('contenteditable', 'true');
  expect(shouldIgnoreKeyTarget(editableAttr)).toBe(true);
});

test('key shortcuts still fire from non-text targets', () => {
  expect(shouldIgnoreKeyTarget(document.createElement('div'))).toBe(false);
  expect(shouldIgnoreKeyTarget(document.createElement('canvas'))).toBe(false);
  expect(shouldIgnoreKeyTarget(document.createElement('button'))).toBe(false);
  expect(shouldIgnoreKeyTarget(document.body)).toBe(false);
  expect(shouldIgnoreKeyTarget(window)).toBe(false);
  expect(shouldIgnoreKeyTarget(null)).toBe(false);
});
