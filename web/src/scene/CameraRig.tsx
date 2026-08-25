import { OrbitControls } from '@react-three/drei';
import { useThree } from '@react-three/fiber';
import type { ComponentRef } from 'react';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { OrthographicCamera } from 'three';
import type { SceneModel } from '../model/layout';

/** The game's blueprint view looks down at roughly 35 degrees. */
const TILT = 35 * (Math.PI / 180);

// The +45-degree azimuth phase puts the camera corner-on to the grid — the
// isometric angle DSP's own blueprint camera uses — rather than staring
// straight down an axis at one face. Do not remove it: at quarterTurns=0
// this makes x and z (relative to the centre) come out equal, which is
// correct corner-on geometry, not a bug, even though the first quarter turn
// then only flips the sign of z while x stays put (see camera.test.ts).
export function isoPosition(
  center: [number, number, number],
  radius: number,
  quarterTurns: number,
): [number, number, number] {
  const dist = radius * 2.2;
  const az = (quarterTurns * Math.PI) / 2 + Math.PI / 4;
  const horiz = Math.cos(TILT) * dist;
  return [
    center[0] + Math.sin(az) * horiz,
    center[1] + Math.sin(TILT) * dist,
    center[2] + Math.cos(az) * horiz,
  ];
}

/** Orthographic zoom that frames a sphere of the given radius within the viewport. */
export function frameZoom(radius: number, viewport: { width: number; height: number }): number {
  return Math.min(viewport.width, viewport.height) / (radius * 2.6);
}

/**
 * True when a keydown came from a text-entry surface, where single-letter
 * shortcuts must not fire. The blueprint textarea is the app's primary input
 * and blueprint payloads are base64, so `q`, `e` and `o` are common characters:
 * without this guard, hand-correcting a blueprint string spins the camera on
 * almost every keystroke.
 *
 * Duck-typed rather than using `instanceof HTMLTextAreaElement` so it also
 * holds for elements from another realm (e.g. inside an iframe), where the
 * constructor identity differs.
 */
export function shouldIgnoreKeyTarget(target: EventTarget | null): boolean {
  if (!isElementLike(target)) return false;
  // `isContentEditable` is the authoritative signal in a browser — it is also
  // true for descendants of an editable host — but it is not implemented by
  // every DOM (happy-dom, used by the test suite, omits it, and does not
  // reflect the `contentEditable` property to the attribute either), so check
  // the property and the attribute too. Both catch the editable element
  // itself, which is where a keydown originates in practice.
  if (target.isContentEditable === true) return true;
  if (target.contentEditable === 'true' || target.contentEditable === 'plaintext-only') return true;
  const editable = target.getAttribute('contenteditable');
  if (editable !== null && editable !== 'false') return true;
  const tag = target.tagName.toUpperCase();
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
}

type KeyTargetElement = {
  tagName: string;
  isContentEditable?: boolean;
  contentEditable?: string;
  getAttribute(name: string): string | null;
};

function isElementLike(target: EventTarget | null): target is EventTarget & KeyTargetElement {
  const el = target as Partial<KeyTargetElement> | null;
  return el !== null && typeof el?.tagName === 'string' && typeof el.getAttribute === 'function';
}

export function CameraRig({ model }: { model: SceneModel }) {
  // `get` reads the live r3f store imperatively. We deliberately avoid
  // holding onto `camera` from a reactive `useThree` selector: this effect
  // mutates the camera in place (position/zoom/near/far), and the React
  // Compiler's immutability check forbids mutating a value obtained
  // directly from a hook. Going through `get()` — a plain function call,
  // not itself a hook — sidesteps that without disabling the rule.
  const get = useThree((s) => s.get);
  const size = useThree((s) => s.size);
  const [turns, setTurns] = useState(0);
  const [orbit, setOrbit] = useState(false);
  const controls = useRef<ComponentRef<typeof OrbitControls>>(null);

  // Frame the model whenever it changes or we rotate a quarter turn.
  useLayoutEffect(() => {
    const camera = get().camera as OrthographicCamera;
    const [x, y, z] = isoPosition(model.center, model.radius, turns);
    camera.position.set(x, y, z);
    camera.zoom = frameZoom(model.radius, size);
    camera.near = -model.radius * 20;
    camera.far = model.radius * 40;
    camera.lookAt(model.center[0], model.center[1], model.center[2]);
    camera.updateProjectionMatrix();
    if (controls.current) {
      controls.current.target.set(model.center[0], model.center[1], model.center[2]);
      controls.current.update();
    }
  }, [get, model, turns, size]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Checked on both the event target and the focused element: a real
      // keydown targets the focused control, but an event dispatched on
      // `window` targets the window, and only `activeElement` reveals that
      // the user is mid-edit in the textarea.
      if (shouldIgnoreKeyTarget(e.target) || shouldIgnoreKeyTarget(document.activeElement)) return;
      if (e.key === 'q' || e.key === 'Q') setTurns((t) => t - 1);
      if (e.key === 'e' || e.key === 'E') setTurns((t) => t + 1);
      if (e.key === 'o' || e.key === 'O') setOrbit((v) => !v);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <OrbitControls
      ref={controls}
      makeDefault
      enableRotate={orbit}
      enablePan
      enableZoom
      target={model.center}
    />
  );
}
