import { useLayoutEffect, useRef } from 'react';
import { type InstancedMesh, Object3D } from 'three';
import { isBelt } from '../model/beltGraph';
import type { SceneModel } from '../model/layout';

const CHEVRON_SIZE = 0.42;

export interface ChevronTransform {
  position: [number, number, number];
  yawRad: number;
}

/**
 * Euler angles (XYZ order, matching `Object3D.rotation.set`) that lay the
 * chevron flat on the XZ plane and point its apex along the belt's heading.
 *
 * `circleGeometry(1, 3)`'s first outer vertex — the apex — sits at local
 * `+X`. The heading convention (see `computeBeltHeadings`) is
 * `atan2(dx, dz)`, whose zero points along world `+Z`. Rotating `-π/2` about
 * X lays the shape flat and leaves local `+X` mapped to world
 * `(cos z, -sin z)` for a subsequent Z rotation of `z`; reaching the wanted
 * `(sin yaw, cos yaw)` therefore needs `z = yaw - π/2`, not `-yaw`. Do not
 * "simplify" this back to `-yaw` — that point-across-the-belt bug shipped
 * once already.
 */
export function chevronRotationEuler(yawRad: number): [number, number, number] {
  return [-Math.PI / 2, 0, yawRad - Math.PI / 2];
}

/**
 * One transform per belt, sitting just above the belt's top face, carrying
 * the heading (world-space bearing) the arrow should point along.
 *
 * Direction comes from the run topology rather than the belt's own yaw: the
 * game zeroes yaw when it serialises a belt, so the stored value says nothing
 * about which way cargo moves. Turning `yawRad` into an actual on-screen
 * rotation still requires composing it with the arrow mesh's own local
 * orientation — see `chevronRotationEuler` for that step.
 */
export function chevronTransforms(model: SceneModel): ChevronTransform[] {
  const out: ChevronTransform[] = [];
  for (const inst of model.instances) {
    if (!isBelt(inst.itemId)) continue;
    const yawRad = model.beltHeadings.get(inst.index);
    if (yawRad === undefined) continue;
    out.push({
      position: [inst.position[0], inst.position[1] + inst.size[1] / 2 + 0.05, inst.position[2]],
      yawRad,
    });
  }
  return out;
}

export function BeltChevrons({ model }: { model: SceneModel }) {
  const meshRef = useRef<InstancedMesh>(null);
  const transforms = chevronTransforms(model);
  const count = transforms.length;

  useLayoutEffect(() => {
    const mesh = meshRef.current;
    if (!mesh) return;
    const dummy = new Object3D();
    transforms.forEach((t, i) => {
      dummy.position.set(t.position[0], t.position[1], t.position[2]);
      dummy.rotation.set(...chevronRotationEuler(t.yawRad));
      dummy.scale.setScalar(CHEVRON_SIZE);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [transforms]);

  if (count === 0) return null;

  return (
    <instancedMesh
      key={count}
      ref={meshRef}
      args={[undefined, undefined, count]}
      raycast={() => null}
    >
      {/* A 3-sided circle is a triangle -- an arrowhead without a custom geometry. */}
      <circleGeometry args={[1, 3]} />
      <meshBasicMaterial color="#dfe9ff" transparent opacity={0.75} depthWrite={false} />
    </instancedMesh>
  );
}
