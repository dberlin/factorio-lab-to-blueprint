import { readBuilding } from './building';
import { BinaryReader } from './reader';
import type { BlueprintArea, BlueprintBuilding } from './types';

export interface ParsedPayload {
  version: number;
  cursorOffsetX: number;
  cursorOffsetY: number;
  cursorTargetArea: number;
  dragBoxSizeX: number;
  dragBoxSizeY: number;
  primaryAreaIdx: number;
  patch: number | null;
  areas: BlueprintArea[];
  buildings: BlueprintBuilding[];
  bytesConsumed: number;
}

export function parsePayload(payload: Uint8Array): ParsedPayload {
  const r = new BinaryReader(payload);

  const version = r.i32();
  const cursorOffsetX = r.i32();
  const cursorOffsetY = r.i32();
  const cursorTargetArea = r.i32();
  const dragBoxSizeX = r.i32();
  const dragBoxSizeY = r.i32();
  const primaryAreaIdx = r.i32();

  const areaCount = r.u8();
  // The game throws "Corrupt Data" on exactly these bounds.
  if (areaCount > 64 || primaryAreaIdx < -1 || primaryAreaIdx > areaCount) {
    throw new RangeError(`Corrupt Data: areaCount=${areaCount} primaryAreaIdx=${primaryAreaIdx}`);
  }

  const areas: BlueprintArea[] = new Array(areaCount);
  for (let i = 0; i < areaCount; i++) {
    areas[i] = {
      index: r.i8(),
      parentIndex: r.i8(),
      tropicAnchor: r.i16(),
      areaSegments: r.i16(),
      anchorLocalOffsetX: r.i16(),
      anchorLocalOffsetY: r.i16(),
      width: r.i16(),
      height: r.i16(),
    };
  }

  const buildingCount = r.i32();
  if (buildingCount < 0 || buildingCount > 1048576) {
    throw new RangeError(`Corrupt Data: buildingCount=${buildingCount}`);
  }
  const buildings: BlueprintBuilding[] = new Array(buildingCount);
  for (let i = 0; i < buildingCount; i++) buildings[i] = readBuilding(r);

  // version >= 2 appends a patch number and an optional terrain-reform block.
  // We stop after the flag: the reform data is irrelevant to rendering, and the
  // game's own reader likewise ignores whatever trails it.
  let patch: number | null = null;
  if (version >= 2) {
    patch = r.i32();
    r.u8();
  }

  return {
    version,
    cursorOffsetX,
    cursorOffsetY,
    cursorTargetArea,
    dragBoxSizeX,
    dragBoxSizeY,
    primaryAreaIdx,
    patch,
    areas,
    buildings,
    bytesConsumed: r.offset,
  };
}
