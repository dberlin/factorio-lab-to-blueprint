import { useLayoutEffect, useMemo, useRef } from 'react';
import {
  BufferGeometry,
  Color,
  Float32BufferAttribute,
  type InstancedMesh,
  Object3D,
  Vector3,
} from 'three';
import { isBelt } from '../model/beltGraph';
import {
  appendMesh,
  arrowIsDark,
  arrowWedge,
  orientedBox,
  type RibbonMesh,
  ribbonMesh,
  runColor,
  type Vec3,
  WEDGE_MID_RATIO,
} from '../model/beltRibbons';
import type { BuildingInstance, SceneModel } from '../model/layout';
import { isOnPort, SORTER, sorterParts, supportTopY } from '../model/sorterModel';

/** The canvas background, which is what a marking over bare ground sits on. */
const GROUND = 0x10141a;
const ACCENT = 0xd98a2b;
const LIGHT_GLYPH = 0xf4f8ff;
const DARK_GLYPH = 0x11151b;
const MARKING_SIZE = 0.26;
const NEUTRAL_TIE = 0x8d9bad;

export interface SorterScene {
  /** Bodies: base, legs, head bar and arm, coloured per sorter. */
  positions: number[];
  normals: number[];
  colors: number[];
  /** The orange plate on each base, drawn in one colour. */
  accent: RibbonMesh;
  markings: { at: Vec3; dir: Vec3; dark: boolean }[];
  /** Flat pairs of endpoints for the tie lines, with a colour per vertex. */
  ties: number[];
  tieColors: number[];
  /** Base centres, for turning a click on a sorter back into its index. */
  bodies: { index: number; at: Vec3 }[];
}

/**
 * The sorter layer.
 *
 * A sorter is drawn as the game's part -- base at the pickup end, arm over,
 * two-legged head at the drop -- so which way it moves goods reads from the
 * shape. Because the arm spans the two ports, the only tie lines drawn are for
 * ends that are NOT already seated on what they serve, which in real
 * blueprints is a handful out of hundreds.
 */
export function buildSorterScene(model: SceneModel): SorterScene {
  const bodyMesh: RibbonMesh = { positions: [], normals: [] };
  const colors: number[] = [];
  const accent: RibbonMesh = { positions: [], normals: [] };
  const markings: { at: Vec3; dir: Vec3; dark: boolean }[] = [];
  const ties: number[] = [];
  const tieColors: number[] = [];
  const bodies: { index: number; at: Vec3 }[] = [];

  const byIndex = new Map<number, BuildingInstance>();
  for (const inst of model.instances) byIndex.set(inst.index, inst);

  const runOfBelt = new Map<number, number>();
  model.beltRuns.forEach((run, runIndex) => {
    for (const belt of run.belts) runOfBelt.set(belt, runIndex);
  });

  const target = (index: number) => {
    const inst = byIndex.get(index);
    if (!inst) return undefined;
    return { position: inst.position, size: inst.size, belt: isBelt(inst.itemId) };
  };

  const colour = new Color();
  const tint = new Color();

  for (const sorter of model.sorters) {
    const from = target(sorter.inputIndex);
    const to = target(sorter.outputIndex);
    const parts = sorterParts(
      sorter.pick,
      sorter.drop,
      supportTopY(from, sorter.pick[1]),
      supportTopY(to, sorter.drop[1]),
    );

    const before = bodyMesh.positions.length;
    appendMesh(
      bodyMesh,
      orientedBox(parts.base, SORTER.BASE_W, SORTER.BASE_H, SORTER.BASE_L, parts.dir),
    );
    for (const leg of parts.legs) {
      appendMesh(bodyMesh, orientedBox(leg, SORTER.LEG, SORTER.LEG_H, SORTER.LEG, parts.dir));
    }
    appendMesh(
      bodyMesh,
      orientedBox(parts.headBar, SORTER.BAR_W, SORTER.BAR_H, SORTER.BAR_L, parts.dir),
    );
    if (!parts.stacked) {
      appendMesh(bodyMesh, ribbonMesh(parts.arm, SORTER.ARM_W, SORTER.ARM_T));
    }
    colour.setHex(sorter.color);
    for (let i = before; i < bodyMesh.positions.length; i += 3) {
      colors.push(colour.r, colour.g, colour.b);
    }

    appendMesh(
      accent,
      orientedBox(parts.accent, SORTER.ACCENT_W, SORTER.ACCENT_H, SORTER.ACCENT_W, parts.dir),
    );

    // What the marking is read against is whatever is under the head: the
    // strip it drops onto, or bare ground. A fixed colour fails on one or the
    // other -- yellow on a pale strip was the first thing anyone complained
    // about.
    const dropRun = to?.belt ? runOfBelt.get(sorter.outputIndex) : undefined;
    const under = dropRun === undefined ? GROUND : runColor(dropRun);
    markings.push({
      at: [
        parts.marking[0] - parts.dir[0] * MARKING_SIZE * WEDGE_MID_RATIO,
        parts.marking[1],
        parts.marking[2] - parts.dir[2] * MARKING_SIZE * WEDGE_MID_RATIO,
      ],
      dir: parts.dir,
      dark: arrowIsDark(under),
    });

    const beltEnd = from?.belt ? sorter.inputIndex : to?.belt ? sorter.outputIndex : undefined;
    const runIndex = beltEnd === undefined ? undefined : runOfBelt.get(beltEnd);
    tint.setHex(runIndex === undefined ? NEUTRAL_TIE : runColor(runIndex));

    pushTie(ties, tieColors, tint, sorter.pick, from);
    pushTie(ties, tieColors, tint, sorter.drop, to);

    bodies.push({ index: sorter.index, at: parts.base });
  }

  return {
    positions: bodyMesh.positions,
    normals: bodyMesh.normals,
    colors,
    accent,
    markings,
    ties,
    tieColors,
    bodies,
  };
}

interface Served {
  position: readonly [number, number, number];
  size: readonly [number, number, number];
  belt: boolean;
}

/**
 * A tie is drawn only for an end that is not already on its port. It hugs the
 * outside of the building it serves -- out past the nearest face, then a short
 * way up it -- rather than running to the centre, which would be buried inside
 * the box and invisible.
 */
function pushTie(
  ties: number[],
  colors: number[],
  colour: Color,
  end: readonly [number, number, number],
  served: Served | undefined,
): void {
  if (!served) return;
  if (isOnPort([end[0], end[1], end[2]], served.position, served.size)) return;

  const [px, py, pz] = served.position;
  const [sx, sy, sz] = served.size;
  const dx = end[0] - px;
  const dz = end[2] - pz;
  const ox = sx / 2 + 0.14;
  const oz = sz / 2 + 0.14;
  let cornerX: number;
  let cornerZ: number;
  if (Math.abs(dx) / ox >= Math.abs(dz) / oz) {
    cornerX = px + (dx < 0 ? -ox : ox);
    cornerZ = Math.max(pz - sz / 2, Math.min(end[2], pz + sz / 2));
  } else {
    cornerZ = pz + (dz < 0 ? -oz : oz);
    cornerX = Math.max(px - sx / 2, Math.min(end[0], px + sx / 2));
  }
  const topY = Math.min(py + sy / 2 + 0.1, end[1] + 0.55);

  const segment = (a: [number, number, number], b: [number, number, number]) => {
    ties.push(a[0], a[1], a[2], b[0], b[1], b[2]);
    for (let i = 0; i < 2; i++) colors.push(colour.r, colour.g, colour.b);
  };
  segment([end[0], end[1], end[2]], [cornerX, end[1], cornerZ]);
  segment([cornerX, end[1], cornerZ], [cornerX, topY, cornerZ]);
}

/** The sorter whose base is nearest a point, for click-to-select. */
export function sorterNearest(
  point: { x: number; y: number; z: number },
  bodies: readonly { index: number; at: Vec3 }[],
): number | null {
  let best: number | null = null;
  let bestDistance = Infinity;
  for (const body of bodies) {
    const d =
      (body.at[0] - point.x) ** 2 + (body.at[1] - point.y) ** 2 + (body.at[2] - point.z) ** 2;
    if (d < bestDistance) {
      bestDistance = d;
      best = body.index;
    }
  }
  return best;
}

export function SorterModels({
  model,
  showTies,
  onSelect,
}: {
  model: SceneModel;
  showTies: boolean;
  onSelect: (index: number | null) => void;
}) {
  const scene = useMemo(() => buildSorterScene(model), [model]);

  const bodies = useMemo(() => {
    const g = new BufferGeometry();
    g.setAttribute('position', new Float32BufferAttribute(scene.positions, 3));
    g.setAttribute('normal', new Float32BufferAttribute(scene.normals, 3));
    g.setAttribute('color', new Float32BufferAttribute(scene.colors, 3));
    g.computeBoundingSphere();
    return g;
  }, [scene]);
  useLayoutEffect(() => () => bodies.dispose(), [bodies]);

  const accent = useMemo(() => {
    const g = new BufferGeometry();
    g.setAttribute('position', new Float32BufferAttribute(scene.accent.positions, 3));
    g.setAttribute('normal', new Float32BufferAttribute(scene.accent.normals, 3));
    g.computeBoundingSphere();
    return g;
  }, [scene]);
  useLayoutEffect(() => () => accent.dispose(), [accent]);

  const wedge = useMemo(() => {
    const mesh = arrowWedge(MARKING_SIZE);
    const g = new BufferGeometry();
    g.setAttribute('position', new Float32BufferAttribute(mesh.positions, 3));
    g.setAttribute('normal', new Float32BufferAttribute(mesh.normals, 3));
    return g;
  }, []);
  useLayoutEffect(() => () => wedge.dispose(), [wedge]);

  const tieGeometry = useMemo(() => {
    const g = new BufferGeometry();
    g.setAttribute('position', new Float32BufferAttribute(scene.ties, 3));
    g.setAttribute('color', new Float32BufferAttribute(scene.tieColors, 3));
    g.computeBoundingSphere();
    return g;
  }, [scene]);
  useLayoutEffect(() => () => tieGeometry.dispose(), [tieGeometry]);

  const markingRef = useRef<InstancedMesh>(null);
  useLayoutEffect(() => {
    const mesh = markingRef.current;
    if (!mesh) return;
    const dummy = new Object3D();
    const colour = new Color();
    scene.markings.forEach((marking, i) => {
      point(dummy, marking.at, marking.dir);
      mesh.setMatrixAt(i, dummy.matrix);
      mesh.setColorAt(i, colour.setHex(marking.dark ? DARK_GLYPH : LIGHT_GLYPH));
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [scene]);

  if (scene.positions.length === 0) return null;

  return (
    <>
      {/* oxlint-disable-next-line jsx-a11y/no-static-element-interactions -- r3f mesh, not a DOM element */}
      <mesh
        geometry={bodies}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(sorterNearest(e.point, scene.bodies));
        }}
      >
        <meshStandardMaterial vertexColors roughness={0.5} metalness={0.15} />
      </mesh>
      <mesh geometry={accent} raycast={() => null}>
        <meshStandardMaterial color={ACCENT} roughness={0.6} />
      </mesh>
      {showTies && scene.markings.length > 0 && (
        <instancedMesh
          key={`markings-${scene.markings.length}`}
          ref={markingRef}
          args={[wedge, undefined, scene.markings.length]}
          raycast={() => null}
        >
          <meshBasicMaterial />
        </instancedMesh>
      )}
      {showTies && scene.ties.length > 0 && (
        <lineSegments geometry={tieGeometry} raycast={() => null}>
          <lineBasicMaterial vertexColors />
        </lineSegments>
      )}
    </>
  );
}

const UP = new Vector3(0, 1, 0);
const xAxis = new Vector3();
const zAxis = new Vector3();

/** Lays a glyph flat, pointing along `dir` (its own forward axis is +Z). */
function point(target: Object3D, at: Vec3, dir: Vec3): void {
  zAxis.set(dir[0], 0, dir[2]).normalize();
  xAxis.crossVectors(UP, zAxis).normalize();
  target.matrix.makeBasis(xAxis, UP, zAxis);
  target.matrix.setPosition(at[0], at[1], at[2]);
}
