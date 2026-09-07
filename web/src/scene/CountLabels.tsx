import { useLayoutEffect, useMemo, useRef } from 'react';
import { InstancedBufferAttribute, type InstancedMesh, Object3D } from 'three';
import type { CountPlacement } from '../model/overlays';
import { GLYPH_COLS, makeDigitTexture, patchDigitShader, PLUS_GLYPH } from './digitAtlas';

const DIGIT_SIZE = 0.9;
const DIGIT_SPACING = 0.62;

export interface DigitQuad {
  position: [number, number, number];
  digit: number;
  /** World-space edge length of this glyph's quad. */
  scale: number;
}

/**
 * One quad per glyph, the whole number centred on the placement.
 *
 * Blueprint counts are always integers -- the game rounds its float to int on
 * serialisation -- so this never has to deal with decimal points. It also
 * never has to deal with signs, but only because the caller (overlays.ts'
 * buildOverlays) filters out non-positive tag counts before a CountPlacement
 * is ever created; the Math.abs below is defence in depth, not the guarantee.
 *
 * `plus` prepends a '+' glyph, which is how an endpoint icon says "and N more
 * candidates" rather than "N of these". `scale` shrinks the whole label,
 * spacing included -- a badge that keeps the full-size pitch reads as a
 * number with gaps in it.
 */
export function layoutDigits(placements: readonly CountPlacement[]): DigitQuad[] {
  const quads: DigitQuad[] = [];
  for (const p of placements) {
    const scale = p.scale ?? DIGIT_SIZE;
    const spacing = DIGIT_SPACING * (scale / DIGIT_SIZE);
    const glyphs = String(Math.abs(Math.trunc(p.value)))
      .split('')
      .map(Number);
    if (p.plus) glyphs.unshift(PLUS_GLYPH);
    glyphs.forEach((digit, i) => {
      const offset = (i - (glyphs.length - 1) / 2) * spacing;
      quads.push({
        position: [p.position[0] + offset, p.position[1], p.position[2]],
        digit,
        scale,
      });
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
      a[i] = q.digit / GLYPH_COLS;
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
      dummy.scale.setScalar(q.scale);
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
