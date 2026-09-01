import { parsePayload } from './blueprint';
import { parseEnvelope } from './envelope';
import type { Blueprint } from './types';

export { BlueprintFormatError } from './envelope';
export { decodeHtmlEntities, findBlueprintString } from './extract';
export type { Blueprint, BlueprintArea, BlueprintBuilding, BlueprintHeader } from './types';

/** Parses a full `BLUEPRINT:` string into structured data. */
export function parseBlueprint(text: string): Blueprint {
  const { header, payload, hashValid } = parseEnvelope(text);
  const parsed = parsePayload(payload);
  return {
    header,
    hashValid,
    version: parsed.version,
    cursorOffsetX: parsed.cursorOffsetX,
    cursorOffsetY: parsed.cursorOffsetY,
    cursorTargetArea: parsed.cursorTargetArea,
    dragBoxSizeX: parsed.dragBoxSizeX,
    dragBoxSizeY: parsed.dragBoxSizeY,
    primaryAreaIdx: parsed.primaryAreaIdx,
    patch: parsed.patch,
    areas: parsed.areas,
    buildings: parsed.buildings,
  };
}
