import { useLayoutEffect, useRef } from 'react';
import { Color, type InstancedMesh, type Matrix4, Object3D } from 'three';
import type { BuildingInstance, SceneModel } from '../model/layout';

const SELECTED = new Color(0xffffff);

/** Pure: builds the world matrix for one instance. Exported for testing. */
export function instanceMatrix(inst: BuildingInstance, dummy: Object3D): Matrix4 {
  dummy.position.set(inst.position[0], inst.position[1], inst.position[2]);
  dummy.rotation.set(0, inst.yawRad, 0);
  dummy.scale.set(inst.size[0], inst.size[1], inst.size[2]);
  dummy.updateMatrix();
  return dummy.matrix;
}

export function BuildingInstances({
  model,
  selectedIndex,
  onSelect,
}: {
  model: SceneModel;
  selectedIndex: number | null;
  onSelect: (index: number | null) => void;
}) {
  const meshRef = useRef<InstancedMesh>(null);
  const count = model.instances.length;

  useLayoutEffect(() => {
    const mesh = meshRef.current;
    if (!mesh) return;
    const dummy = new Object3D();
    const color = new Color();
    model.instances.forEach((inst, i) => {
      mesh.setMatrixAt(i, instanceMatrix(inst, dummy));
      mesh.setColorAt(i, inst.index === selectedIndex ? SELECTED : color.setHex(inst.color));
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [model, selectedIndex]);

  // key on count so a differently-sized blueprint remounts with correct buffers
  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: r3f mesh, not a DOM element
    <instancedMesh
      key={count}
      ref={meshRef}
      args={[undefined, undefined, Math.max(count, 1)]}
      onClick={(e) => {
        e.stopPropagation();
        const i = e.instanceId;
        onSelect(i === undefined ? null : (model.instances[i]?.index ?? null));
      }}
      onPointerMissed={() => onSelect(null)}
    >
      <boxGeometry args={[1, 1, 1]} />
      <meshStandardMaterial roughness={0.55} metalness={0.1} />
    </instancedMesh>
  );
}
