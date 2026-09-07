import { useLayoutEffect, useMemo, useRef } from 'react';
import { Color, type InstancedMesh, type Matrix4, Object3D } from 'three';
import { isBelt, isSorter } from '../model/beltGraph';
import type { BuildingInstance, SceneModel } from '../model/layout';
import type { MachineLook } from '../state/BlueprintProvider';

const SELECTED = new Color(0xffffff);
const GHOST_OPACITY = 0.16;

/** Pure: builds the world matrix for one instance. Exported for testing. */
export function instanceMatrix(inst: BuildingInstance, dummy: Object3D): Matrix4 {
  dummy.position.set(inst.position[0], inst.position[1], inst.position[2]);
  dummy.rotation.set(0, inst.yawRad, 0);
  dummy.scale.set(inst.size[0], inst.size[1], inst.size[2]);
  dummy.updateMatrix();
  return dummy.matrix;
}

/**
 * Boxes for everything that is NOT a belt or a sorter.
 *
 * Belts are strips (BeltRibbons) and sorters are little machines
 * (SorterModels); both draw their own geometry and handle their own clicks, so
 * drawing a box for them here would put a second, wrong shape in the same
 * place.
 */
export function drawnInstances(model: SceneModel): BuildingInstance[] {
  return model.instances.filter((i) => !isBelt(i.itemId) && !isSorter(i.itemId));
}

export function BuildingInstances({
  model,
  selectedIndex,
  onSelect,
  look,
}: {
  model: SceneModel;
  selectedIndex: number | null;
  onSelect: (index: number | null) => void;
  look: MachineLook;
}) {
  const meshRef = useRef<InstancedMesh>(null);
  const drawn = useMemo(() => drawnInstances(model), [model]);
  const count = drawn.length;

  useLayoutEffect(() => {
    const mesh = meshRef.current;
    if (!mesh) return;
    const dummy = new Object3D();
    const color = new Color();
    drawn.forEach((inst, i) => {
      mesh.setMatrixAt(i, instanceMatrix(inst, dummy));
      mesh.setColorAt(i, inst.index === selectedIndex ? SELECTED : color.setHex(inst.color));
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [drawn, selectedIndex]);

  if (look === 'hidden') return null;

  // key on count so a differently-sized blueprint remounts with correct buffers
  return (
    // oxlint-disable-next-line jsx-a11y/no-static-element-interactions -- r3f mesh, not a DOM element
    <instancedMesh
      key={count}
      ref={meshRef}
      args={[undefined, undefined, Math.max(count, 1)]}
      onClick={(e) => {
        e.stopPropagation();
        const i = e.instanceId;
        onSelect(i === undefined ? null : (drawn[i]?.index ?? null));
      }}
    >
      <boxGeometry args={[1, 1, 1]} />
      {/* Ghosted machines keep writing colour but not depth, so the belts and
          sorters underneath them stay visible instead of being swallowed. */}
      <meshStandardMaterial
        roughness={0.55}
        metalness={0.1}
        transparent={look === 'ghosted'}
        opacity={look === 'ghosted' ? GHOST_OPACITY : 1}
        depthWrite={look !== 'ghosted'}
      />
    </instancedMesh>
  );
}
