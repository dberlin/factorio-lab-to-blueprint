import { useLayoutEffect, useMemo, useRef } from 'react';
import { InstancedBufferAttribute, type InstancedMesh, Object3D } from 'three';
import type { CountPlacement } from '../model/overlays';
import { DIGIT_COLS, makeDigitTexture, patchDigitShader } from './digitAtlas';

const DIGIT_SIZE = 0.9;
const DIGIT_SPACING = 0.62;

export interface DigitQuad {
  position: [number, number, number];
  digit: number;
}

/**
 * One quad per digit, the whole number centred on the placement.
 *
 * Blueprint counts are always integers -- the game rounds its float to int on
 * serialisation -- so this never has to deal with decimal points. It also
 * never has to deal with signs, but only because the caller (overlays.ts'
 * buildOverlays) filters out non-positive tag counts before a CountPlacement
 * is ever created; the Math.abs below is defence in depth, not the guarantee.
 */
export function layoutDigits(placements: readonly CountPlacement[]): DigitQuad[] {
  const quads: DigitQuad[] = [];
  for (const p of placements) {
    const digits = String(Math.abs(Math.trunc(p.value)))
      .split('')
      .map(Number);
    digits.forEach((digit, i) => {
      const offset = (i - (digits.length - 1) / 2) * DIGIT_SPACING;
      quads.push({ position: [p.position[0] + offset, p.position[1], p.position[2]], digit });
    });
  }
  return quads;
}

export function CountLabels({ placements }: { placements: CountPlacement[] }) {
  const meshRef = useRef<InstancedMesh>(null);
  const quads = layoutDigits(placements);
  const count = quads.length;

  // The texture owns a GPU handle, so it is created once and disposed on
  // unmount rather than rebuilt whenever the placements change.
  const texture = useMemo(() => makeDigitTexture(), []);
  useLayoutEffect(() => () => texture.dispose(), [texture]);

  const offsets = useMemo(() => {
    const a = new Float32Array(Math.max(count, 1));
    quads.forEach((q, i) => {
      a[i] = q.digit / DIGIT_COLS;
    });
    return new InstancedBufferAttribute(a, 1);
  }, [quads, count]);

  useLayoutEffect(() => {
    const mesh = meshRef.current;
    if (!mesh) return;
    const dummy = new Object3D();
    quads.forEach((q, i) => {
      dummy.position.set(q.position[0], q.position[1], q.position[2]);
      dummy.rotation.set(-Math.PI / 2, 0, 0); // lie flat, as the icons do
      dummy.scale.setScalar(DIGIT_SIZE);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [quads]);

  if (count === 0) return null;

  return (
    <instancedMesh
      key={count}
      ref={meshRef}
      args={[undefined, undefined, count]}
      raycast={() => null}
    >
      <planeGeometry args={[1, 1]}>
        <primitive object={offsets} attach="attributes-digitOffset" />
      </planeGeometry>
      <meshBasicMaterial
        map={texture}
        transparent
        depthWrite={false}
        onBeforeCompile={patchDigitShader}
      />
    </instancedMesh>
  );
}
