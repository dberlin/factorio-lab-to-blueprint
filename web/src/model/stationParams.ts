/**
 * The logistics station parameter block.
 *
 * The game allocates 2048 words (BuildingParameters.cs:1293-1350) but only
 * the first ~384 are meaningful; the rest is zero padding, which is why
 * stations dominate blueprint size. Three fixed regions, read by offset
 * rather than by walking the array.
 */

export const STORAGE_OFFSET = 0;
export const STORAGE_STRIDE = 6;
export const STORAGE_COUNT = 32;
export const BELT_OFFSET = 192;
export const BELT_STRIDE = 4;
export const BELT_COUNT = 32;
export const SETTINGS_OFFSET = 320;
/** Words in the settings region: workEnergyPerTick (+0) .. routePriority (+14). */
export const SETTINGS_WIDTH = 15;

/** ELogisticStorage, verbatim from the DLL. */
export const LOGISTIC_STORAGE = ['None', 'Supply', 'Demand'] as const;
/** IODir, verbatim from the DLL. */
export const IO_DIR = ['None', 'Output', 'Input'] as const;

export interface StationStorageSlot {
  slot: number;
  itemId: number;
  localLogic: number;
  remoteLogic: number;
  max: number;
  keepMode: number;
  keepIncRatio: number;
}

export interface StationBeltSlot {
  slot: number;
  dir: number;
  /** 1-based into `storage`; 0 means unassigned. */
  storageIdx: number;
}

export interface StationSettings {
  workEnergyPerTick: number;
  tripRangeDrones: number;
  tripRangeShips: number;
  includeOrbitCollector: boolean;
  warpEnableDist: number;
  warperNecessary: boolean;
  /** Percentage of a vessel's carrying capacity (StationComponent.cs:1542), not a count. */
  deliveryDrones: number;
  /** Percentage of a vessel's carrying capacity (StationComponent.cs:3384), not a count. */
  deliveryShips: number;
  pilerCount: number;
  minerSpeed: number;
  droneAutoReplenish: boolean;
  shipAutoReplenish: boolean;
  routePriority: number;
}

export interface StationParams {
  storage: StationStorageSlot[];
  beltSlots: StationBeltSlot[];
  settings: StationSettings | undefined;
}

const at = (p: readonly number[], i: number): number => p[i] ?? 0;

export function parseStationParams(p: readonly number[]): StationParams {
  const storage: StationStorageSlot[] = [];
  for (let s = 0; s < STORAGE_COUNT; s++) {
    const o = STORAGE_OFFSET + s * STORAGE_STRIDE;
    const itemId = at(p, o);
    // An unconfigured slot is all zeros; reporting it as "item 0" would be
    // noise on every station, most of which use far fewer than 32 slots.
    if (itemId <= 0) continue;
    storage.push({
      slot: s,
      itemId,
      localLogic: at(p, o + 1),
      remoteLogic: at(p, o + 2),
      max: at(p, o + 3),
      keepMode: at(p, o + 4),
      keepIncRatio: at(p, o + 5) / 100000,
    });
  }

  const beltSlots: StationBeltSlot[] = [];
  for (let s = 0; s < BELT_COUNT; s++) {
    const o = BELT_OFFSET + s * BELT_STRIDE;
    const dir = at(p, o);
    const storageIdx = at(p, o + 1);
    if (dir === 0 && storageIdx === 0) continue;
    beltSlots.push({ slot: s, dir, storageIdx });
  }

  // A block that never reaches the settings region carries none. Older
  // blueprints and shorter variants are real: the fixture corpus holds both
  // 4- and 6-word splitters and both 1- and 110-word depots.
  const settings =
    // The region is 15 words wide (routePriority is the last, at +14). A
    // block that reaches SETTINGS_OFFSET but stops short of the end would
    // report 0 for every field it does not contain, which is the "print a
    // wrong value" case this module refuses to do elsewhere.
    p.length >= SETTINGS_OFFSET + SETTINGS_WIDTH
      ? {
          workEnergyPerTick: at(p, SETTINGS_OFFSET),
          tripRangeDrones: at(p, SETTINGS_OFFSET + 1) / 1e8,
          tripRangeShips: at(p, SETTINGS_OFFSET + 2) * 100,
          // 1 / -1, not 1 / 0 -- `!== 0` would report -1 as true.
          includeOrbitCollector: at(p, SETTINGS_OFFSET + 3) > 0,
          warpEnableDist: at(p, SETTINGS_OFFSET + 4),
          warperNecessary: at(p, SETTINGS_OFFSET + 5) > 0,
          deliveryDrones: at(p, SETTINGS_OFFSET + 6),
          deliveryShips: at(p, SETTINGS_OFFSET + 7),
          pilerCount: at(p, SETTINGS_OFFSET + 8),
          minerSpeed: at(p, SETTINGS_OFFSET + 9),
          droneAutoReplenish: at(p, SETTINGS_OFFSET + 10) > 0,
          shipAutoReplenish: at(p, SETTINGS_OFFSET + 11) > 0,
          routePriority: at(p, SETTINGS_OFFSET + 14),
        }
      : undefined;

  return { storage, beltSlots, settings };
}
