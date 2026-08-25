import { expect, rstest, test } from '@rstest/core';
import { act, render } from '@testing-library/react';
import type { SceneModel } from '../../src/model/layout';
import { CameraRig } from '../../src/scene/CameraRig';

// The Q/E/O shortcuts listen on `window`, so they also see keystrokes aimed at
// the blueprint textarea. Blueprint payloads are base64, which means `q`, `e`
// and `o` are everywhere: without the shouldIgnoreKeyTarget guard in onKey,
// hand-correcting a blueprint string rotates the camera and toggles orbit on
// almost every keystroke. These tests pin the guard at its call site — the
// pure-predicate tests in camera.test.ts cannot catch the call being deleted.
//
// Every key is asserted individually and immediately: a q after an e cancels
// it out, so a batch of keystrokes can leave the camera back where it started
// even with no guard at all.

const camera = {
  position: {
    x: 0,
    y: 0,
    z: 0,
    set(x: number, y: number, z: number) {
      this.x = x;
      this.y = y;
      this.z = z;
    },
  },
  zoom: 1,
  near: 0,
  far: 0,
  lookAt() {},
  updateProjectionMatrix() {},
};

// Stable references: CameraRig's framing effect depends on `get` and `size`.
const state = { get: () => ({ camera }), size: { width: 800, height: 600 } };
let orbitProps: Record<string, unknown> = {};

rstest.mock('@react-three/fiber', () => ({
  useThree: (selector: (s: typeof state) => unknown) => selector(state),
}));
rstest.mock('@react-three/drei', () => ({
  OrbitControls: (props: Record<string, unknown>) => {
    orbitProps = props;
    return null;
  },
}));

const model = { center: [0, 0, 0], radius: 10 } as unknown as SceneModel;

const press = (key: string, target: EventTarget) =>
  act(() => {
    target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
  });

const pos = () => [camera.position.x, camera.position.y, camera.position.z];

test('typing in the blueprint textarea neither rotates the camera nor toggles orbit', () => {
  render(<CameraRig model={model} />);
  const before = pos();
  expect(orbitProps.enableRotate).toBe(false);

  const textarea = document.createElement('textarea');
  document.body.appendChild(textarea);
  textarea.focus();

  for (const key of ['e', 'q', 'o', 'E', 'Q', 'O']) {
    press(key, textarea);
    expect(pos()).toEqual(before);
    expect(orbitProps.enableRotate).toBe(false);
  }

  textarea.remove();
});

test('typing in a plain text input is ignored too', () => {
  render(<CameraRig model={model} />);
  const before = pos();

  const input = document.createElement('input');
  document.body.appendChild(input);
  input.focus();

  press('e', input);
  expect(pos()).toEqual(before);

  input.remove();
});

test('the same keys still work when focus is not in a text field', () => {
  render(<CameraRig model={model} />);
  const start = pos();

  press('e', document.body);
  const afterE = pos();
  expect(afterE).not.toEqual(start);

  press('q', document.body);
  expect(pos()).toEqual(start);

  press('o', document.body);
  expect(orbitProps.enableRotate).toBe(true);
});
