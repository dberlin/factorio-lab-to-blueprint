import { expect, test } from '@rstest/core';
import {
  BELT_COUNT,
  BELT_OFFSET,
  BELT_STRIDE,
  parseStationParams,
  SETTINGS_OFFSET,
  SETTINGS_WIDTH,
  STORAGE_COUNT,
  STORAGE_OFFSET,
  STORAGE_STRIDE,
} from '../../src/model/stationParams';

/** A 2048-word block with the given words set, as the game writes it. */
function block(set: Record<number, number>): number[] {
  const p = new Array(2048).fill(0);
  for (const [k, v] of Object.entries(set)) p[Number(k)] = v;
  return p;
}

test('reads storage slots at stride 6 from offset 0', () => {
  const p = block({
    0: 1101,
    1: 1,
    2: 2,
    3: 3500,
    4: 0,
    5: 50000, // slot 0
    6: 1104,
    7: 2,
    8: 0,
    9: 100,
    10: 1,
    11: 0, //    slot 1
  });
  const { storage } = parseStationParams(p);
  expect(storage.length).toBe(2);
  expect(storage[0]).toEqual({
    slot: 0,
    itemId: 1101,
    localLogic: 1,
    remoteLogic: 2,
    max: 3500,
    keepMode: 0,
    keepIncRatio: 0.5,
  });
  expect(storage[1]!.itemId).toBe(1104);
  expect(storage[1]!.localLogic).toBe(2);
});

test('an empty storage slot is omitted rather than reported as item 0', () => {
  // Only slot 2 is populated; 0 and 1 are untouched zeros.
  const { storage } = parseStationParams(block({ 12: 1005, 15: 200 }));
  expect(storage.length).toBe(1);
  expect(storage[0]!.slot).toBe(2);
});

test('the last storage slot stops before the belt-slot region', () => {
  // Slot 31 is the last: 31 * 6 = 186, and its final word is 191 -- one
  // short of the belt region. Derived from the constants so an off-by-one in
  // either region shows up here rather than as a silently shifted read.
  const last = STORAGE_OFFSET + (STORAGE_COUNT - 1) * STORAGE_STRIDE;
  expect(last).toBe(186);
  expect(last + STORAGE_STRIDE).toBe(BELT_OFFSET);
  const { storage } = parseStationParams(block({ [last]: 1006, [last + 3]: 4000 }));
  expect(storage.length).toBe(1);
  expect(storage[0]!.slot).toBe(31);
  expect(storage[0]!.max).toBe(4000);
});

test('reads belt slots at stride 4 from offset 192', () => {
  const p = block({ 192: 1, 193: 2, 196: 2, 197: 0 });
  const { beltSlots } = parseStationParams(p);
  expect(beltSlots.length).toBe(2);
  expect(beltSlots[0]).toEqual({ slot: 0, dir: 1, storageIdx: 2 });
  // dir Input with no storage assigned is still a populated slot.
  expect(beltSlots[1]).toEqual({ slot: 1, dir: 2, storageIdx: 0 });
});

test('reads settings at offset 320, unscaling and decoding 1/-1 booleans', () => {
  const p = block({
    320: 5000000,
    321: -100000000,
    322: 240000000,
    323: 1,
    324: 20000,
    325: -1,
    326: 100,
    327: 20,
    328: 0,
    329: 0,
    330: 1,
    331: 1,
    334: 3,
  });
  const { settings } = parseStationParams(p);
  expect(settings).toBeDefined();
  expect(settings!.workEnergyPerTick).toBe(5000000);
  expect(settings!.tripRangeDrones).toBeCloseTo(-1, 6); // / 1e8
  expect(settings!.tripRangeShips).toBe(24000000000); //  * 100
  expect(settings!.includeOrbitCollector).toBe(true); //   1
  expect(settings!.warperNecessary).toBe(false); //       -1, not 0
  expect(settings!.deliveryDrones).toBe(100);
  expect(settings!.droneAutoReplenish).toBe(true);
  expect(settings!.routePriority).toBe(3);
});

test('a short block yields no settings rather than reading undefined', () => {
  const { storage, beltSlots, settings } = parseStationParams([1101, 1, 0, 500, 0, 0]);
  expect(storage.length).toBe(1);
  expect(beltSlots.length).toBe(0);
  expect(settings).toBeUndefined();
});

test('the three regions tile the block without overlapping', () => {
  // The offsets are the whole contract of this module: every read is by
  // offset, so a region that overruns its neighbour reads the neighbour's
  // words and reports them as its own.
  expect(STORAGE_OFFSET + STORAGE_COUNT * STORAGE_STRIDE).toBe(BELT_OFFSET);
  expect(BELT_OFFSET + BELT_COUNT * BELT_STRIDE).toBeLessThanOrEqual(SETTINGS_OFFSET);
  expect(SETTINGS_OFFSET + SETTINGS_WIDTH).toBeLessThanOrEqual(2048);
});
