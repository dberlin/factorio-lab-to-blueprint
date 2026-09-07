import { useFrame } from '@react-three/fiber';
import { useLayoutEffect, useMemo, useRef } from 'react';
import {
  BufferGeometry,
  Color,
  Float32BufferAttribute,
  InstancedBufferAttribute,
  type InstancedMesh,
  Object3D,
  Vector3,
} from 'three';
import { isBelt } from '../model/beltGraph';
import {
  ARROW_MID,
  ARROW_SIZE,
  arrowIsDark,
  arrowWedge,
  DIGIT_ADVANCE,
  extendEnds,
  LABEL_HEIGHT,
  layoutBlocks,
  RIBBON_THICKNESS,
  ribbonMesh,
  roundCorners,
  runColor,
  runPolyline,
  steppedClimb,
  type Vec3,
} from '../model/beltRibbons';
import type { SceneModel } from '../model/layout';
import { GLYPH_COLS, makeDigitTexture, patchDigitShader } from './digitAtlas';

/** Just clear of the strip's top face. */
const ARROW_LIFT = RIBBON_THICKNESS / 2 + 0.02;
const LABEL_LIFT = RIBBON_THICKNESS / 2 + 0.05;

const LIGHT_GLYPH = 0xf4f8ff;
const DARK_GLYPH = 0x11151b;

export interface ArrowSpec {
  at: Vec3;
  dir: Vec3;
  dark: boolean;
}

export interface RunLabelSpec {
  at: Vec3;
  dir: Vec3;
  digits: number[];
  dark: boolean;
}

export interface RibbonScene {
  positions: number[];
  normals: number[];
  colors: number[];
  arrows: ArrowSpec[];
  labels: RunLabelSpec[];
  /** Tile centres, for turning a click on a strip back into a belt. */
  belts: { index: number; at: Vec3 }[];
}

/**
 * Everything the belt layer draws, derived from the scene model.
 *
 * One strip per run, merged into a single vertex buffer with a per-vertex run
 * colour: a real blueprint has hundreds of runs and thousands of belts, and a
 * mesh each would be hundreds of draw calls for geometry that never changes.
 *
 * Direction comes from run order (`beltGraph`), never from a belt's `yaw` --
 * the game writes 0 there.
 */
export function buildRibbonScene(model: SceneModel): RibbonScene {
  const positions: number[] = [];
  const normals: number[] = [];
  const colors: number[] = [];
  const arrows: ArrowSpec[] = [];
  const labels: RunLabelSpec[] = [];
  const belts: { index: number; at: Vec3 }[] = [];

  const at = new Map<number, readonly [number, number, number]>();
  for (const inst of model.instances) {
    if (isBelt(inst.itemId)) at.set(inst.index, inst.position);
  }

  const colour = new Color();
  model.beltRuns.forEach((run, runIndex) => {
    const tiles = runPolyline(run.belts, at);
    for (const index of run.belts) {
      const p = at.get(index);
      if (p) belts.push({ index, at: [p[0], p[1], p[2]] });
    }
    if (tiles.length === 0) return;

    // A cycle has no ends to grow: closing it back onto its head is what makes
    // the loop continuous. Everything else reaches half a tile past its first
    // and last tile centres so a run arrives flush at the tile it feeds.
    const head = tiles[0] as Vec3;
    const path = run.cyclic
      ? [...tiles, [head[0], head[1], head[2]] as Vec3]
      : extendEnds(tiles, model.beltHeadings.get(run.belts[0] as number));
    if (path.length < 2) return;

    const hex = runColor(runIndex);
    colour.setHex(hex);
    const dark = arrowIsDark(hex);
    const mesh = ribbonMesh(roundCorners(steppedClimb(path)));
    // Appended one at a time, not spread: a long run's vertex list can exceed
    // the engine's argument limit, and `push(...huge)` fails as a stack
    // overflow rather than anything that names the cause.
    for (let i = 0; i < mesh.positions.length; i++) {
      positions.push(mesh.positions[i] as number);
      normals.push(mesh.normals[i] as number);
    }
    for (let i = 0; i < mesh.positions.length; i += 3) {
      colors.push(colour.r, colour.g, colour.b);
    }

    const digits = [...String(runIndex)].map(Number);
    for (const block of layoutBlocks(path, digits.length)) {
      arrows.push({
        // The wedge's extent is not centred on its origin, so the origin is
        // pulled back by half that offset to sit the glyph in its slot.
        at: [
          block.arrow[0] - block.dir[0] * ARROW_MID,
          block.arrow[1] + ARROW_LIFT,
          block.arrow[2] - block.dir[2] * ARROW_MID,
        ],
        dir: block.dir,
        dark,
      });
      if (block.label) {
        labels.push({
          at: [block.label[0], block.label[1] + LABEL_LIFT, block.label[2]],
          dir: block.dir,
          digits,
          dark,
        });
      }
    }
  });

  return { positions, normals, colors, arrows, labels, belts };
}

/** The belt whose tile centre is nearest a point, for click-to-select. */
export function beltNearest(
  point: { x: number; y: number; z: number },
  belts: readonly { index: number; at: Vec3 }[],
): number | null {
  let best: number | null = null;
  let bestDistance = Infinity;
  for (const belt of belts) {
    const d =
      (belt.at[0] - point.x) ** 2 + (belt.at[1] - point.y) ** 2 + (belt.at[2] - point.z) ** 2;
    if (d < bestDistance) {
      bestDistance = d;
      best = belt.index;
    }
  }
  return best;
}

/**
 * Digit quads for one label, laid along travel and centred on the label point.
 *
 * `flip` turns the whole label around when travel points away from the
 * camera's right, so a number never reads mirrored or upside down. The offsets
 * use the flipped direction too, which is what keeps the digits in reading
 * order on screen rather than merely un-mirrored.
 */
export function digitPlacements(label: RunLabelSpec, flip: boolean): { at: Vec3; digit: number }[] {
  const dir: Vec3 = flip ? [-label.dir[0], 0, -label.dir[2]] : label.dir;
  return label.digits.map((digit, i) => {
    const offset = (i - (label.digits.length - 1) / 2) * DIGIT_ADVANCE;
    return {
      digit,
      at: [label.at[0] + dir[0] * offset, label.at[1], label.at[2] + dir[2] * offset] as Vec3,
    };
  });
}

/** True when a label pointing `dir` would read backwards for this camera. */
export function shouldFlip(dir: Vec3, cameraRight: { x: number; z: number }): boolean {
  return dir[0] * cameraRight.x + dir[2] * cameraRight.z < 0;
}

export function BeltRibbons({
  model,
  showLabels,
  onSelect,
}: {
  model: SceneModel;
  showLabels: boolean;
  onSelect: (index: number | null) => void;
}) {
  const scene = useMemo(() => buildRibbonScene(model), [model]);

  const geometry = useMemo(() => {
    const g = new BufferGeometry();
    g.setAttribute('position', new Float32BufferAttribute(scene.positions, 3));
    g.setAttribute('normal', new Float32BufferAttribute(scene.normals, 3));
    g.setAttribute('color', new Float32BufferAttribute(scene.colors, 3));
    g.computeBoundingSphere();
    return g;
  }, [scene]);
  useLayoutEffect(() => () => geometry.dispose(), [geometry]);

  const wedge = useMemo(() => {
    const mesh = arrowWedge(ARROW_SIZE);
    const g = new BufferGeometry();
    g.setAttribute('position', new Float32BufferAttribute(mesh.positions, 3));
    g.setAttribute('normal', new Float32BufferAttribute(mesh.normals, 3));
    return g;
  }, []);
  useLayoutEffect(() => () => wedge.dispose(), [wedge]);

  const texture = useMemo(() => makeDigitTexture(), []);
  useLayoutEffect(() => () => texture.dispose(), [texture]);

  const arrowRef = useRef<InstancedMesh>(null);
  useLayoutEffect(() => {
    const mesh = arrowRef.current;
    if (!mesh) return;
    const dummy = new Object3D();
    const colour = new Color();
    scene.arrows.forEach((arrow, i) => {
      orient(dummy, arrow.at, arrow.dir, 1);
      mesh.setMatrixAt(i, dummy.matrix);
      mesh.setColorAt(i, colour.setHex(arrow.dark ? DARK_GLYPH : LIGHT_GLYPH));
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [scene]);

  // One instance per digit of every visible run number.
  const digitOf = useMemo(
    () =>
      scene.labels.flatMap((label, labelIndex) =>
        label.digits.map((_, digitIndex) => ({ labelIndex, digitIndex })),
      ),
    [scene],
  );

  const digitRef = useRef<InstancedMesh>(null);
  const flips = useRef<boolean[]>([]);
  const offsets = useMemo(() => {
    const a = new Float32Array(Math.max(digitOf.length, 1));
    digitOf.forEach((d, i) => {
      const label = scene.labels[d.labelIndex] as RunLabelSpec;
      a[i] = (label.digits[d.digitIndex] as number) / GLYPH_COLS;
    });
    return new InstancedBufferAttribute(a, 1);
  }, [digitOf, scene]);

  const writeDigits = useMemo(() => {
    const dummy = new Object3D();
    const colour = new Color();
    return () => {
      const mesh = digitRef.current;
      if (!mesh) return;
      let cursor = 0;
      scene.labels.forEach((label, labelIndex) => {
        const placements = digitPlacements(label, flips.current[labelIndex] ?? false);
        for (const placement of placements) {
          orient(dummy, placement.at, flips.current[labelIndex] ? negate(label.dir) : label.dir, 0);
          dummy.scale.set(LABEL_HEIGHT, LABEL_HEIGHT, 1);
          dummy.updateMatrix();
          mesh.setMatrixAt(cursor, dummy.matrix);
          mesh.setColorAt(cursor, colour.setHex(label.dark ? DARK_GLYPH : LIGHT_GLYPH));
          cursor++;
        }
      });
      mesh.instanceMatrix.needsUpdate = true;
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
      mesh.computeBoundingSphere();
    };
  }, [scene]);

  useLayoutEffect(() => {
    flips.current = scene.labels.map(() => false);
    writeDigits();
  }, [scene, writeDigits]);

  // Only the labels whose reading direction actually changed force a rewrite,
  // so orbiting costs one dot product per label per frame and nothing else.
  const right = useMemo(() => new Vector3(), []);
  useFrame(({ camera }) => {
    if (!showLabels || scene.labels.length === 0) return;
    right.setFromMatrixColumn(camera.matrixWorld, 0);
    let changed = false;
    scene.labels.forEach((label, i) => {
      const flip = shouldFlip(label.dir, right);
      if (flips.current[i] !== flip) {
        flips.current[i] = flip;
        changed = true;
      }
    });
    if (changed) writeDigits();
  });

  if (scene.positions.length === 0) return null;

  return (
    <>
      {/* oxlint-disable-next-line jsx-a11y/no-static-element-interactions -- r3f mesh, not a DOM element */}
      <mesh
        geometry={geometry}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(beltNearest(e.point, scene.belts));
        }}
      >
        <meshStandardMaterial vertexColors roughness={0.6} metalness={0.05} />
      </mesh>
      {scene.arrows.length > 0 && (
        <instancedMesh
          key={`arrows-${scene.arrows.length}`}
          ref={arrowRef}
          args={[wedge, undefined, scene.arrows.length]}
          raycast={() => null}
        >
          <meshBasicMaterial />
        </instancedMesh>
      )}
      {showLabels && digitOf.length > 0 && (
        <instancedMesh
          key={`digits-${digitOf.length}`}
          ref={digitRef}
          args={[undefined, undefined, digitOf.length]}
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
      )}
    </>
  );
}

const UP = new Vector3(0, 1, 0);
const xAxis = new Vector3();
const yAxis = new Vector3();
const zAxis = new Vector3();

/**
 * Points an object along a travel direction, lying flat on the XZ plane.
 *
 * `mode` 1 orients a solid glyph whose own forward axis is local +Z (the
 * wedge); mode 0 orients a plane, whose face normal is local +Z and whose text
 * runs along local +X. Composing this as an explicit basis rather than Euler
 * angles is deliberate: the belt chevrons shipped a bug once where a composed
 * XYZ rotation turned every arrow 90 degrees on straight runs.
 */
function orient(target: Object3D, at: Vec3, dir: Vec3, mode: 0 | 1): void {
  zAxis.set(dir[0], 0, dir[2]).normalize();
  if (mode === 1) {
    xAxis.crossVectors(UP, zAxis).normalize();
    target.matrix.makeBasis(xAxis, UP, zAxis);
  } else {
    xAxis.set(zAxis.x, 0, zAxis.z);
    yAxis.crossVectors(UP, xAxis).normalize();
    zAxis.copy(UP);
    target.matrix.makeBasis(xAxis, yAxis, zAxis);
  }
  target.matrix.setPosition(at[0], at[1], at[2]);
  target.matrix.decompose(target.position, target.quaternion, target.scale);
}

function negate(v: Vec3): Vec3 {
  return [-v[0], -v[1], -v[2]];
}
