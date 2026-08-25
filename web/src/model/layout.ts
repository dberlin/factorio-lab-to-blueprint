import type { Blueprint } from '../format';
import {
  type BeltRun,
  beltSuccessors,
  buildBeltRuns,
  computeBeltHeadings,
  inferCarried,
  isBelt,
} from './beltGraph';
import type { Catalog } from './catalog';
import { visualScaleFor } from './visualScale';

export interface BuildingInstance {
  index: number;
  itemId: number;
  modelIndex: number;
  position: [number, number, number];
  size: [number, number, number];
  yawRad: number;
  color: number;
  recipeId: number;
  filterId: number;
  parameters: readonly number[];
}

export interface SceneModel {
  instances: BuildingInstance[];
  bounds: { min: [number, number, number]; max: [number, number, number] };
  center: [number, number, number];
  radius: number;
  unknownItemIds: number[];
  beltRuns: BeltRun[];
  beltHeadings: Map<number, number>;
  unresolvedTagIds: number[];
}

const DEG = Math.PI / 180;

/**
 * Blueprint local offsets are (x, y, z) with z as altitude.
 * SlotConfig size/centre are already Unity Y-up (x, height, z).
 * World mapping: (bp.x, bp.z, -bp.y).
 */
export function buildSceneModel(bp: Blueprint, catalog: Catalog): SceneModel {
  const instances: BuildingInstance[] = [];
  const unknown = new Set<number>();

  const min: [number, number, number] = [Infinity, Infinity, Infinity];
  const max: [number, number, number] = [-Infinity, -Infinity, -Infinity];

  // Grows the bounds by one box's extent on one axis. Taking the axis as a
  // literal-union index rather than `number` keeps this free of non-null
  // assertions under noUncheckedIndexedAccess.
  const expandBounds = (axis: 0 | 1 | 2, centre: number, extent: number): void => {
    const half = extent / 2;
    if (centre - half < min[axis]) min[axis] = centre - half;
    if (centre + half > max[axis]) max[axis] = centre + half;
  };

  for (const b of bp.buildings) {
    // The record's own modelIndex is authoritative — the item's default model
    // is only a fallback for a record carrying a bogus index. These disagree
    // rarely but really: across the 13,690 buildings in the fixtures exactly
    // two records diverge, both splitters (item 2020, default model 38
    // size [2.7,2.4,2.7]) placed as model 39 (size [2.0,2.94,2.7]). Reading
    // the item's default first drew those at the wrong size and height.
    const box = catalog.model(b.modelIndex) ?? catalog.boxForItem(b.itemId);
    if (!box) {
      unknown.add(b.itemId);
      continue;
    }

    const scale = visualScaleFor(b.itemId);
    const yawRad = -b.yaw * DEG;

    // Rotate the box centre's horizontal component by yaw before applying it.
    // This must match three.js's Matrix4.makeRotationY(yawRad) exactly:
    //   x' =  x*cos(θ) + z*sin(θ)
    //   z' = -x*sin(θ) + z*cos(θ)
    // (the sign pattern looks "backwards" vs. a naive CCW rotation formula --
    // do not "simplify" it to x*cos - z*sin / x*sin + z*cos, that is the
    // mirror-image rotation and puts the box on the wrong side of the pivot
    // for any model with a non-zero horizontal selectCenter.)
    const cos = Math.cos(yawRad);
    const sin = Math.sin(yawRad);
    const cx = box.center[0] * cos + box.center[2] * sin;
    const cz = -box.center[0] * sin + box.center[2] * cos;

    const position: [number, number, number] = [b.x + cx, b.z + box.center[1], -b.y + cz];
    const size: [number, number, number] = [
      box.size[0] * scale[0],
      box.size[1] * scale[1],
      box.size[2] * scale[2],
    ];

    expandBounds(0, position[0], size[0]);
    expandBounds(1, position[1], size[1]);
    expandBounds(2, position[2], size[2]);

    instances.push({
      index: b.index,
      itemId: b.itemId,
      modelIndex: b.modelIndex,
      position,
      size,
      yawRad,
      color: catalog.item(b.itemId)?.color ?? 0xdddddd,
      recipeId: b.recipeId,
      filterId: b.filterId,
      parameters: b.parameters,
    });
  }

  const beltRuns = buildBeltRuns(bp);
  inferCarried(bp, beltRuns, catalog);
  const positions = new Map<number, readonly [number, number, number]>(
    instances.map((i) => [i.index, i.position]),
  );
  const beltHeadings = computeBeltHeadings(beltRuns, positions, beltSuccessors(bp));

  // Tag ids we cannot draw (tech icons are not extracted, and a future DSP
  // patch could add a band). Reported rather than silently skipped, so a gap
  // looks like a gap instead of an untagged belt.
  const unresolvedTags = new Set<number>();
  for (const inst of instances) {
    // isBelt gate, exactly as in buildOverlays: only belts carry belt tags.
    // Without it, a sorter's stack-size word and a station's slot config are
    // read as tag ids -- falk-v7-mall has ZERO tagged belts yet would report
    // "3 unrecognised belt tag(s)" from sorter values 1, 2 and 3. A diagnostic
    // that fires on every blueprint hides the one case it exists to surface.
    if (!isBelt(inst.itemId)) continue;
    const tagId = inst.parameters[0];
    if (tagId !== undefined && tagId > 0 && !catalog.tagIconName(tagId)) unresolvedTags.add(tagId);
  }
  const unresolvedTagIds = [...unresolvedTags].sort((a, b) => a - b);

  if (instances.length === 0) {
    return {
      instances,
      bounds: { min: [0, 0, 0], max: [0, 0, 0] },
      center: [0, 0, 0],
      radius: 1,
      unknownItemIds: [...unknown],
      beltRuns,
      beltHeadings,
      unresolvedTagIds,
    };
  }

  const center: [number, number, number] = [
    (min[0] + max[0]) / 2,
    (min[1] + max[1]) / 2,
    (min[2] + max[2]) / 2,
  ];
  const radius = Math.max(1, Math.hypot(max[0] - min[0], max[1] - min[1], max[2] - min[2]) / 2);

  return {
    instances,
    bounds: { min, max },
    center,
    radius,
    unknownItemIds: [...unknown],
    beltRuns,
    beltHeadings,
    unresolvedTagIds,
  };
}
