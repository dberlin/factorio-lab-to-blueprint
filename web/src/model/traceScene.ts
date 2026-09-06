/**
 * A trace frame, rendered by the viewer that already exists.
 *
 * `buildSceneModel` (model/layout.ts) reads only `bp.buildings`, so a frame
 * needs no header, no areas, no hash and no patch — and therefore no
 * `parseBlueprint`, no base64, no gzip and no md5f. This is the entire reason
 * a snapshot is raw rows rather than an encoded blueprint: `codec.encode`
 * asserts a finalized frame (dsp/codec.py) that a mid-search pack does not
 * have, and costs seconds.
 *
 * Free of React and three.js, per web/tests/architecture.test.ts.
 */
import type { TraceFrame } from '../api/trace';
import type { Blueprint, BlueprintBuilding } from '../format/types';

const EMPTY_HEADER = {
  headerVersion: 0,
  layout: 10,
  icons: [],
  timestamp: 0n,
  gameVersion: '0.0.0.0',
  shortDesc: '',
  author: 'flab2bp-trace',
  customVersion: '',
  attributes: [],
  description: '',
};

/**
 * Ten trace-row values map onto ten `BlueprintBuilding` fields; the remaining
 * eighteen (Ruling 2, task-5-addendum.md) get neutral defaults — `0` for the
 * unused connection slot/offset fields, `[]` for parameters, `null` for
 * content. A trace row carries no per-connection slot detail, only which
 * building it points at, so those defaults are exact rather than approximate.
 */
export function traceFrameToBlueprint(frame: TraceFrame): Blueprint {
  const [minX, minY, maxX, maxY] = frame.bounds;
  const buildings: BlueprintBuilding[] = frame.buildings.map((row, index) => {
    const [itemId, modelIndex, x, y, z, yaw, recipeId, filterId, outputObj, inputObj] = row;
    return {
      index,
      areaIndex: 0,
      itemId,
      modelIndex,
      x,
      y,
      z,
      x2: x,
      y2: y,
      z2: z,
      yaw,
      yaw2: yaw,
      tilt: 0,
      tilt2: 0,
      pitch: 0,
      pitch2: 0,
      outputObjIdx: outputObj,
      inputObjIdx: inputObj,
      outputToSlot: 0,
      inputFromSlot: 0,
      outputFromSlot: 0,
      inputToSlot: 0,
      outputOffset: 0,
      inputOffset: 0,
      recipeId,
      filterId,
      parameters: [],
      content: null,
    };
  });
  return {
    header: EMPTY_HEADER,
    // A trace frame was never hashed and never encoded. Saying `true` here
    // would be a claim about an artifact that does not exist.
    hashValid: false,
    version: 1,
    cursorOffsetX: 0,
    cursorOffsetY: 0,
    cursorTargetArea: 0,
    dragBoxSizeX: Math.max(1, maxX - minX + 1),
    dragBoxSizeY: Math.max(1, maxY - minY + 1),
    primaryAreaIdx: 0,
    patch: null,
    areas: [
      {
        index: 0,
        parentIndex: -1,
        tropicAnchor: 0,
        areaSegments: 0,
        anchorLocalOffsetX: 0,
        anchorLocalOffsetY: 0,
        width: Math.max(1, maxX - minX + 1),
        height: Math.max(1, maxY - minY + 1),
      },
    ],
    buildings,
  };
}

/** The caption shown over a snapshot, so it is never read as a result. */
export function traceFrameLabel(frame: TraceFrame): string {
  const parts = [`TRACE · ${frame.strategy} · ${frame.candidate} · ${frame.phase}`];
  if (frame.height !== null) parts.push(`h=${frame.height}`);
  if (frame.restart !== null) parts.push(`r=${frame.restart}`);
  if (frame.round !== null) parts.push(`round ${frame.round}`);
  if (frame.block !== null) parts.push(`block ${frame.block}`);
  if (frame.area !== null) parts.push(`${frame.area} tiles`);
  if (frame.belt_tiles !== null) parts.push(`${frame.belt_tiles} belt`);
  if (frame.reason !== null) parts.push(frame.reason);
  return parts.join(' · ');
}
