/**
 * The two "learned state" layers: nets the router could not wire, and strips
 * a proved no-good forbids. Neither is a building, so neither belongs in
 * `SceneModel` -- they are drawn straight from the raw `TraceFrame` fields a
 * frame already carries (`stranded`, `no_goods`), independently toggleable,
 * and safe when the frame is `null` or either array is empty (the common
 * case: most sampled frames wire cleanly and prove nothing).
 *
 * `overlayGeometry` is exported separately from the component so it is
 * testable without a renderer -- exactly the split `chevronTransforms` /
 * `BeltChevrons` already uses in this directory.
 */
import { useLayoutEffect, useRef } from 'react';
import { type InstancedMesh, Object3D } from 'three';
import type { TraceFrame } from '../api/trace';

/** Segments float just above the floor so they read as an overlay, not a belt. */
const SEGMENT_Y = 0.5;
const CELL_HEIGHT = 0.5;
const CELL_Y = CELL_HEIGHT / 2;

/**
 * One world unit per strip index. A frame carries no per-strip physical
 * pitch -- only the index a no-good names -- so this is an illustrative
 * placeholder footprint, not a to-scale one.
 */
const STRIP_PITCH = 1;

export type OverlaySegment = readonly [number, number, number, number, number, number];

export interface OverlayCell {
  position: readonly [number, number, number];
  size: readonly [number, number, number];
}

export interface OverlayShow {
  stranded: boolean;
  noGoods: boolean;
}

export interface OverlayGeometry {
  segments: OverlaySegment[];
  cells: OverlayCell[];
}

/**
 * Pure: derives world-space overlay geometry from a trace frame.
 *
 * World mapping is `(bp.x, bp.z, -bp.y)`, exactly as `buildSceneModel` has it
 * (model/layout.ts) -- an overlay drawn in a different frame would sit beside
 * the buildings it is meant to indict. `stranded` pairs and `no_goods` strip
 * indices are already absolute coordinates (like every `TraceBuildingRow`),
 * so neither needs an offset by `frame.bounds`.
 */
export function overlayGeometry(frame: TraceFrame | null, show: OverlayShow): OverlayGeometry {
  const segments: OverlaySegment[] = [];
  const cells: OverlayCell[] = [];
  if (!frame) return { segments, cells };

  if (show.stranded) {
    for (const [x0, y0, x1, y1] of frame.stranded) {
      segments.push([x0, SEGMENT_Y, -y0, x1, SEGMENT_Y, -y1]);
    }
  }

  if (show.noGoods) {
    const [minX, minY, , maxY] = frame.bounds;
    const depth = Math.max(1, maxY - minY + 1);
    const centerZ = -(minY + maxY) / 2;
    for (const noGood of frame.no_goods) {
      for (const strip of noGood) {
        cells.push({
          position: [minX + strip + 0.5, CELL_Y, centerZ],
          size: [STRIP_PITCH, CELL_HEIGHT, depth],
        });
      }
    }
  }

  return { segments, cells };
}

function segmentPositions(segments: OverlaySegment[]): Float32Array {
  const out = new Float32Array(segments.length * 6);
  segments.forEach((segment, i) => out.set(segment, i * 6));
  return out;
}

export function TraceOverlay({ frame, show }: { frame: TraceFrame | null; show: OverlayShow }) {
  const meshRef = useRef<InstancedMesh>(null);
  const { segments, cells } = overlayGeometry(frame, show);
  const cellCount = cells.length;

  useLayoutEffect(() => {
    const mesh = meshRef.current;
    if (!mesh) return;
    const dummy = new Object3D();
    cells.forEach((cell, i) => {
      dummy.position.set(cell.position[0], cell.position[1], cell.position[2]);
      dummy.scale.set(cell.size[0], cell.size[1], cell.size[2]);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [cells]);

  return (
    <>
      {segments.length > 0 && (
        // oxlint-disable-next-line jsx-a11y/no-static-element-interactions -- r3f mesh, not a DOM element
        <lineSegments raycast={() => null}>
          <bufferGeometry>
            <bufferAttribute attach="attributes-position" args={[segmentPositions(segments), 3]} />
          </bufferGeometry>
          <lineBasicMaterial color="#ff5566" />
        </lineSegments>
      )}
      {cellCount > 0 && (
        <instancedMesh
          key={cellCount}
          ref={meshRef}
          args={[undefined, undefined, cellCount]}
          raycast={() => null}
        >
          <boxGeometry args={[1, 1, 1]} />
          <meshBasicMaterial color="#ffaa00" transparent opacity={0.35} depthWrite={false} />
        </instancedMesh>
      )}
    </>
  );
}
