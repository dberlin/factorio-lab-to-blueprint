import type { BinaryReader } from './reader';
import type { BlueprintBuilding } from './types';

const isBelt = (itemId: number) => itemId > 2000 && itemId < 2010;
const isSorter = (itemId: number) => itemId > 2010 && itemId < 2020;

/**
 * Reads one BlueprintBuilding. The leading i32 is a *path number*:
 *   <= -102  layout A, with a trailing content string
 *   <= -101  layout A, without content
 *   <= -100  layout B, with tilt
 *   else     layout B, without tilt, and the value itself is the index
 */
export function readBuilding(r: BinaryReader): BlueprintBuilding {
  const path = r.i32();

  let index: number;
  let areaIndex: number;
  let itemId: number;
  let modelIndex: number;
  let x: number;
  let y: number;
  let z: number;
  let x2: number;
  let y2: number;
  let z2: number;
  let yaw: number;
  let yaw2: number;
  let tilt = 0;
  let tilt2 = 0;
  let pitch = 0;
  let pitch2 = 0;

  if (path <= -101) {
    index = r.i32();
    itemId = r.i16();
    modelIndex = r.i16();
    areaIndex = r.i8();
    x = r.f32();
    y = r.f32();
    z = r.f32();
    yaw = r.f32();

    if (isBelt(itemId)) {
      tilt = r.f32();
      x2 = x;
      y2 = y;
      z2 = z;
      yaw2 = yaw;
      tilt2 = tilt;
    } else if (isSorter(itemId)) {
      tilt = r.f32();
      pitch = r.f32();
      x2 = r.f32();
      y2 = r.f32();
      z2 = r.f32();
      yaw2 = r.f32();
      tilt2 = r.f32();
      pitch2 = r.f32();
    } else {
      x2 = x;
      y2 = y;
      z2 = z;
      yaw2 = yaw;
    }
  } else {
    index = path <= -100 ? r.i32() : path;
    areaIndex = r.i8();
    x = r.f32();
    y = r.f32();
    z = r.f32();
    x2 = r.f32();
    y2 = r.f32();
    z2 = r.f32();
    yaw = r.f32();
    yaw2 = r.f32();
    if (path <= -100) tilt = r.f32();
    itemId = r.i16();
    modelIndex = r.i16();
  }

  const outputObjIdx = r.i32();
  const inputObjIdx = r.i32();
  const outputToSlot = r.i8();
  const inputFromSlot = r.i8();
  const outputFromSlot = r.i8();
  const inputToSlot = r.i8();
  const outputOffset = r.i8();
  const inputOffset = r.i8();
  const recipeId = r.i16();
  const filterId = r.i16();

  const paramCount = r.i16();
  if (paramCount < 0 || paramCount > 32768) {
    throw new RangeError(`Corrupt Data: implausible parameter count ${paramCount}`);
  }
  const parameters: number[] = new Array(paramCount);
  for (let i = 0; i < paramCount; i++) parameters[i] = r.i32();

  let content: string | null = null;
  if (path <= -102 && r.i32() > 0) content = r.string();

  return {
    index,
    areaIndex,
    itemId,
    modelIndex,
    x,
    y,
    z,
    x2,
    y2,
    z2,
    yaw,
    yaw2,
    tilt,
    tilt2,
    pitch,
    pitch2,
    outputObjIdx,
    inputObjIdx,
    outputToSlot,
    inputFromSlot,
    outputFromSlot,
    inputToSlot,
    outputOffset,
    inputOffset,
    recipeId,
    filterId,
    parameters,
    content,
  };
}
