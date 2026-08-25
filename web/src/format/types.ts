export interface BlueprintHeader {
  headerVersion: number;
  layout: number;
  icons: number[];
  timestamp: bigint;
  gameVersion: string;
  shortDesc: string;
  author: string;
  customVersion: string;
  attributes: string[];
  description: string;
}

export interface BlueprintArea {
  index: number;
  parentIndex: number;
  tropicAnchor: number;
  areaSegments: number;
  anchorLocalOffsetX: number;
  anchorLocalOffsetY: number;
  width: number;
  height: number;
}

export interface BlueprintBuilding {
  index: number;
  areaIndex: number;
  itemId: number;
  modelIndex: number;
  x: number;
  y: number;
  z: number;
  x2: number;
  y2: number;
  z2: number;
  yaw: number;
  yaw2: number;
  tilt: number;
  tilt2: number;
  pitch: number;
  pitch2: number;
  outputObjIdx: number;
  inputObjIdx: number;
  outputToSlot: number;
  inputFromSlot: number;
  outputFromSlot: number;
  inputToSlot: number;
  outputOffset: number;
  inputOffset: number;
  recipeId: number;
  filterId: number;
  parameters: number[];
  content: string | null;
}

export interface Blueprint {
  header: BlueprintHeader;
  hashValid: boolean;
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
}
