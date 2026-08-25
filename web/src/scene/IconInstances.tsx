import { useLayoutEffect, useMemo, useRef } from 'react';
import { InstancedBufferAttribute, type InstancedMesh, Object3D, type Texture } from 'three';
import type { IconPlacement } from '../model/overlays';
import type { Atlas } from '../model/schemas';

/**
 * `texture` is loaded and owned by the caller (see BlueprintCanvas), not via
 * r3f's `useLoader` here. `useLoader` suspends on first load, and the nearest
 * Suspense boundary for anything inside `<Canvas>` is r3f's own internal one
 * around its custom-renderer root — its fallback (`Block`) reflects the
 * suspend outward by having the *outer*, DOM-tree `<Canvas>` component throw
 * a promise that never resolves. With no `<Suspense>` ancestor of `<Canvas>`
 * in this app, that throw permanently stalls `<Canvas>`'s own render/effect
 * cycle, including the `useMeasure`-driven `gl.setSize` call the canvas'
 * self-sizing depends on — the canvas gets stuck at the raw default 300x150.
 * Loading the texture with a plain, non-suspending promise one level up
 * sidesteps the whole mechanism.
 */
export function IconInstances({
  placements,
  atlas,
  texture,
}: {
  placements: IconPlacement[];
  atlas: Atlas;
  texture: Texture;
}) {
  const meshRef = useRef<InstancedMesh>(null);
  const count = placements.length;

  const offsets = useMemo(() => {
    const a = new Float32Array(Math.max(count, 1) * 2);
    placements.forEach((p, i) => {
      a[i * 2] = p.uv[0];
      a[i * 2 + 1] = p.uv[1];
    });
    return new InstancedBufferAttribute(a, 2);
  }, [placements, count]);

  useLayoutEffect(() => {
    const mesh = meshRef.current;
    if (!mesh) return;
    const dummy = new Object3D();
    placements.forEach((p, i) => {
      dummy.position.set(p.position[0], p.position[1], p.position[2]);
      dummy.rotation.set(-Math.PI / 2, 0, 0); // lie flat, readable from the iso camera
      dummy.scale.setScalar(1.6);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [placements]);

  if (count === 0) return null;

  const uvScale = [1 / atlas.cols, 1 / atlas.rows];

  return (
    <instancedMesh
      key={count}
      ref={meshRef}
      args={[undefined, undefined, count]}
      raycast={() => null}
    >
      <planeGeometry args={[1, 1]}>
        <primitive object={offsets} attach="attributes-iconOffset" />
      </planeGeometry>
      <meshBasicMaterial
        map={texture}
        transparent
        depthWrite={false}
        onBeforeCompile={(shader) => {
          shader.vertexShader = shader.vertexShader
            .replace(
              '#include <common>',
              `#include <common>\nattribute vec2 iconOffset;\nvarying vec2 vIcon;`,
            )
            .replace('#include <uv_vertex>', `#include <uv_vertex>\nvIcon = iconOffset;`);
          shader.fragmentShader = shader.fragmentShader
            .replace('#include <common>', `#include <common>\nvarying vec2 vIcon;`)
            .replace(
              '#include <map_fragment>',
              // The atlas was packed with PIL, which pastes row 0 at the top of
              // the PNG (raster order: row increases downward). buildOverlays'
              // `uv` is "row / rows" in that same raster convention, with no
              // inversion (see overlays.ts).
              //
              // three.js Textures default to flipY = true: on GPU upload it
              // vertically flips the image so a normally-mapped quad displays
              // right side up, which means raster row 0 ends up at GL v ~= 1
              // (the texture's "top"), not v ~= 0. Sampling with the raw
              // `row / rows` value as a GL v-coordinate would read the wrong
              // atlas row for any atlas with more than one row (this one has
              // 12). Rather than mutate the shared texture's `flipY` (which
              // the React Compiler correctly flags as mutating a hook's
              // return value), the vertical flip is undone here in v alone;
              // u needs no correction since flipY never touches the u axis.
              `vec2 atlasUv = vec2(
                 vIcon.x + vMapUv.x * ${uvScale[0]},
                 1.0 - vIcon.y - ${uvScale[1]} + vMapUv.y * ${uvScale[1]}
               );
               vec4 sampled = texture2D( map, atlasUv );
               if ( sampled.a < 0.1 ) discard;
               diffuseColor *= sampled;`,
            );
        }}
      />
    </instancedMesh>
  );
}
