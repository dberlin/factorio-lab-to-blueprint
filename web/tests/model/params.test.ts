import { expect, test } from '@rstest/core';
import type { Blueprint, BlueprintBuilding } from '../../src/format';
import { buildBeltRuns, inferCarried } from '../../src/model/beltGraph';
import { buildCatalog } from '../../src/model/catalog';
import { describeInferred, describeParameters, type ParamRow } from '../../src/model/params';

const catalog = buildCatalog({
  items: [
    {
      id: 2303,
      name: 'Assembling Machine Mk.I',
      iconName: 'assembler-1',
      gridIndex: 1,
      modelIndex: 65,
      canBuild: true,
      color: 0xedab5c,
    },
    {
      id: 2011,
      name: 'Sorter Mk.I',
      iconName: 'sorter-1',
      gridIndex: 2,
      modelIndex: 41,
      canBuild: true,
      color: 0x8ec7d2,
    },
    {
      id: 1101,
      name: 'Iron Ingot',
      iconName: 'iron-ingot',
      gridIndex: 3,
      modelIndex: 0,
      canBuild: false,
      color: 0xb0a08c,
    },
    // The four ids describeParameters treats as stations.
    {
      id: 2103,
      name: 'Planetary Logistics Station',
      iconName: 'pls',
      gridIndex: 4,
      modelIndex: 90,
      canBuild: true,
      color: 0x6f9fd8,
    },
    {
      id: 2104,
      name: 'Interstellar Logistics Station',
      iconName: 'ils',
      gridIndex: 5,
      modelIndex: 50,
      canBuild: true,
      color: 0x6f9fd8,
    },
    {
      id: 2101,
      name: 'Storage Mk.I',
      iconName: 'storage-1',
      gridIndex: 6,
      modelIndex: 51,
      canBuild: true,
      color: 0x9a9a9a,
    },
    {
      id: 2106,
      name: 'Orbital Collector',
      iconName: 'collector',
      gridIndex: 7,
      modelIndex: 93,
      canBuild: true,
      color: 0x6f9fd8,
    },
    {
      id: 2020,
      name: 'Splitter',
      iconName: 'splitter',
      gridIndex: 8,
      modelIndex: 38,
      canBuild: true,
      color: 0x8ec7d2,
    },
  ],
  models: {
    '38': { prefab: 'splitter', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Splitter' },
    '50': { prefab: 'station-2', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Station' },
    '51': { prefab: 'depot', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Storage' },
    // The remaining sixteen typed models below exist only so the
    // table-driven decoder test can type a building via modelIndex without
    // needing a matching catalog item -- buildingTypeFor resolves through
    // modelIndex first, and none of these decoders read the item catalog
    // except Monitor's cargo-filter lookup (which degrades to "#id" for an
    // id with no catalog entry, which is fine for that test).
    '65': { prefab: 'assembler', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Assembler' },
    '100': { prefab: 'monitor', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Monitor' },
    '101': {
      prefab: 'battle-base',
      size: [1, 1, 1],
      center: [0, 0, 0],
      buildingType: 'BattleBase',
    },
    '102': { prefab: 'dispenser', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Dispenser' },
    '103': { prefab: 'turret', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Turret' },
    '104': { prefab: 'ejector', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Ejector' },
    '105': { prefab: 'lab', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Lab' },
    '106': { prefab: 'inserter', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Inserter' },
    '107': { prefab: 'tank', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Tank' },
    '108': { prefab: 'marker', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Marker' },
    '109': { prefab: 'silo', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Silo' },
    '110': { prefab: 'geothermal', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Geothermal' },
    '111': { prefab: 'gamma', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Gamma' },
    '112': { prefab: 'star', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'ArtificialStar' },
    '113': { prefab: 'exchanger', size: [1, 1, 1], center: [0, 0, 0], buildingType: 'Exchanger' },
    '120': { prefab: 'belt-1', size: [1, 0.5, 1], center: [0, 0.1, 0], buildingType: 'Belt' },
  },
  recipes: [
    {
      id: 6,
      name: 'Iron Ingot',
      iconName: 'iron-ingot',
      items: [1001],
      itemCounts: [1],
      results: [1101],
      resultCounts: [1],
      timeSpend: 60,
    },
  ],
});

function building(over: Partial<BlueprintBuilding> = {}): BlueprintBuilding {
  return {
    index: 0,
    areaIndex: 0,
    itemId: 2303,
    modelIndex: 65,
    x: 0,
    y: 0,
    z: 0,
    x2: 0,
    y2: 0,
    z2: 0,
    yaw: 0,
    yaw2: 0,
    tilt: 0,
    tilt2: 0,
    pitch: 0,
    pitch2: 0,
    // The "absent" sentinels: describeParameters must emit no row for these.
    outputObjIdx: -1,
    inputObjIdx: -1,
    outputToSlot: 0,
    inputFromSlot: 0,
    outputFromSlot: 0,
    inputToSlot: 0,
    outputOffset: 0,
    inputOffset: 0,
    recipeId: 0,
    filterId: 0,
    parameters: [],
    content: null,
    ...over,
  };
}

const rowsFor = (over: Partial<BlueprintBuilding> = {}): ParamRow[] =>
  describeParameters(building(over), catalog);
const labels = (over: Partial<BlueprintBuilding> = {}): string[] =>
  rowsFor(over).map((r) => r.label);
const rowValue = (rows: ParamRow[], label: string): string | undefined =>
  rows.find((r) => r.label === label)?.value;

test('a building with nothing set produces no rows at all', () => {
  expect(rowsFor()).toEqual([]);
});

test('a known recipe id renders the recipe name', () => {
  expect(rowValue(rowsFor({ recipeId: 6 }), 'Recipe')).toBe('Iron Ingot');
});

test('an unknown recipe id degrades to #id rather than disappearing', () => {
  expect(rowValue(rowsFor({ recipeId: 999 }), 'Recipe')).toBe('#999');
});

test('recipeId 0 means "no recipe" and emits no Recipe row', () => {
  expect(labels({ recipeId: 0 })).not.toContain('Recipe');
});

test('a known filter id renders the item name', () => {
  expect(rowValue(rowsFor({ itemId: 2011, filterId: 1101 }), 'Filter')).toBe('Iron Ingot');
});

test('an unknown filter id degrades to #id', () => {
  expect(rowValue(rowsFor({ itemId: 2011, filterId: 424242 }), 'Filter')).toBe('#424242');
});

test('filterId 0 means "no filter" and emits no Filter row', () => {
  expect(labels({ itemId: 2011, filterId: 0 })).not.toContain('Filter');
});

test('output and input targets render the building index and slot', () => {
  const rows = rowsFor({
    outputObjIdx: 12,
    outputToSlot: 3,
    inputObjIdx: 7,
    inputFromSlot: 1,
  });
  expect(rowValue(rows, 'Output to')).toBe('building 12 (slot 3)');
  expect(rowValue(rows, 'Input from')).toBe('building 7 (slot 1)');
});

// The sentinel boundary. Object indices use -1 for "not connected", so index 0
// is a real target and must produce a row -- unlike recipeId/filterId, where 0
// means "none". Tightening `>= 0` to `> 0` would silently drop every
// connection to building 0, which is a real building in every blueprint.
test('objIdx 0 is a real target, not an absent one', () => {
  const rows = rowsFor({ outputObjIdx: 0, outputToSlot: 2, inputObjIdx: 0, inputFromSlot: 5 });
  expect(rowValue(rows, 'Output to')).toBe('building 0 (slot 2)');
  expect(rowValue(rows, 'Input from')).toBe('building 0 (slot 5)');
});

test('objIdx -1 is the absent sentinel and emits no row', () => {
  expect(labels({ outputObjIdx: -1, inputObjIdx: -1 })).toEqual([]);
});

test('an empty parameter block emits no row, for stations and non-stations alike', () => {
  expect(labels({ itemId: 2104, modelIndex: 50, parameters: [] })).not.toContain('Station slots');
  expect(labels({ itemId: 2303, parameters: [] })).not.toContain('Parameters');
});

test('content renders as the Label row', () => {
  expect(rowValue(rowsFor({ content: 'North smelter bank' }), 'Label')).toBe('North smelter bank');
});

test('null or empty content emits no Label row', () => {
  expect(labels({ content: null })).not.toContain('Label');
  expect(labels({ content: '' })).not.toContain('Label');
});

// Row order is load-bearing: InfoPanel keys its <dt>/<dd> pairs by label and
// renders them in array order, so a reshuffle is a visible UI change.
test('rows come back in a stable, documented order', () => {
  const rows = rowsFor({
    itemId: 2104,
    modelIndex: 50,
    recipeId: 6,
    filterId: 1101,
    outputObjIdx: 4,
    inputObjIdx: 5,
    parameters: [1],
    content: 'hub',
  });
  expect(rows.map((r) => r.label)).toEqual([
    'Recipe',
    'Filter',
    'Output to',
    'Input from',
    'Stores 1',
    'Label',
  ]);
});

test('a station reports its storage slots by name and logistic role', () => {
  const p = new Array(2048).fill(0);
  p[0] = 1101;
  p[1] = 1;
  p[2] = 2;
  p[3] = 3500; // supply iron, demand remotely
  const rows = rowsFor({ itemId: 2104, modelIndex: 50, parameters: p });
  const v = rowValue(rows, 'Supplies 1');
  expect(v).toContain('Iron Ingot');
  expect(v).toContain('3500');
});

test('a station reports its delivery load as a percentage', () => {
  // StationComponent uses both as (carries - 1) * value / 100, and the
  // defaults are 10 and 100 -- a percentage of carrying capacity, not a
  // vessel count.
  const p = new Array(2048).fill(0);
  p[0] = 1101;
  p[1] = 1;
  p[326] = 10;
  p[327] = 100;
  const rows = rowsFor({ itemId: 2104, modelIndex: 50, parameters: p });
  expect(rowValue(rows, 'Delivery load (drones / ships)')).toBe('10% / 100%');
});

test('station row labels are unique so they can key a list', () => {
  const p = new Array(2048).fill(0);
  p[0] = 1101;
  p[1] = 1;
  p[3] = 100;
  p[6] = 2020;
  p[7] = 1;
  p[9] = 200;
  const rows = rowsFor({ itemId: 2104, modelIndex: 50, parameters: p });
  const rowLabels = rows.map((r) => r.label);
  expect(new Set(rowLabels).size).toBe(rowLabels.length);
});

test('a station numbers storage rows by raw slot, so belt references land right', () => {
  // Slot 2 (words 12..17) is left unconfigured, exactly as the heretical
  // smelter block's stations do. Numbering by array position would call the
  // slot-3 row "3", while the belt slot referencing it carries storageIdx 4.
  const p = new Array(2048).fill(0);
  p[0] = 1101; // raw slot 0
  p[1] = 1;
  p[18] = 2020; // raw slot 3 -- the gap is slot 2
  p[19] = 2;
  p[192] = 1; // belt slot 0: Output
  p[193] = 4; // ...feeding storage slot 4, i.e. raw slot 3
  const rows = rowsFor({ itemId: 2104, modelIndex: 50, parameters: p });

  expect(rows.map((r) => r.label)).toContain('Demands 4');
  expect(rows.map((r) => r.label)).not.toContain('Demands 2');
  // The cross-reference the panel prints must name a row the panel shows.
  const target = rowValue(rows, 'Belt slots');
  expect(target).toBe('Output → slot 4');
  expect(rowValue(rows, 'Demands 4')).toContain('Splitter');
});

test('a belt slot naming a storage slot with no row says so', () => {
  // The game writes all 32 storage slots; we print only the configured ones.
  // Two belt slots in the fixture corpus reference a slot whose itemId is 0, so
  // "-> slot 2" would name a row the reader cannot find.
  const p = new Array(2048).fill(0);
  p[0] = 1101; // raw slot 0 configured
  p[1] = 1;
  p[192] = 1; // belt slot 0: Output
  p[193] = 2; // ...feeding storage slot 2, whose raw slot 1 is all zeros
  const rows = rowsFor({ itemId: 2104, modelIndex: 50, parameters: p });
  expect(rowValue(rows, 'Belt slots')).toBe('Output → slot 2 (unconfigured)');
});

test('a station block that stops inside the settings region reports no settings', () => {
  // 321 words reaches SETTINGS_OFFSET but holds only 1 of its 15 words;
  // decoding it would print 0 for fourteen fields we do not have.
  const p = new Array(321).fill(0);
  p[0] = 1101;
  p[1] = 1;
  const rows = rowsFor({ itemId: 2104, modelIndex: 50, parameters: p });
  expect(rowValue(rows, 'Delivery load (drones / ships)')).toBeUndefined();
  expect(rowValue(rows, 'Supplies 1')).toContain('Iron Ingot');
});

test('a splitter reports its per-belt priority flags', () => {
  const rows = rowsFor({ itemId: 2020, modelIndex: 38, parameters: [1, 0, 0, 1, 0, 0] });
  expect(rowValue(rows, 'Priority belts')).toBe('A, D');
});

test('a 4-word splitter decodes without reading past the end', () => {
  // The fixture corpus holds both 4- and 6-word splitters.
  const rows = rowsFor({ itemId: 2020, modelIndex: 38, parameters: [0, 1, 0, 0] });
  expect(rowValue(rows, 'Priority belts')).toBe('B');
});

test('an unknown building type falls back to a word count rather than guessing', () => {
  const rows = rowsFor({ itemId: 9999, modelIndex: 4242, parameters: [7, 7, 7] });
  expect(rowValue(rows, 'Parameters')).toBe('3 word(s)');
});

test('a typed building with an empty block emits no parameter row', () => {
  const rows = rowsFor({ itemId: 2020, modelIndex: 38, parameters: [] });
  const rowLabels = rows.map((r) => r.label);
  expect(rowLabels.some((l) => l.startsWith('Priority') || l === 'Parameters')).toBe(false);
});

// --- Four decoding mistakes that are easy to reintroduce, each pinned below
// so an edit that brings one back fails loudly instead of silently.

test('a known type with nothing to report emits no fallback row', () => {
  // A splitter with every belt at default priority legitimately decodes to
  // zero rows. Falling back to "N word(s)" there would claim the block is
  // unreadable -- indistinguishable from a genuinely unknown type.
  const rows = rowsFor({ itemId: 2020, modelIndex: 38, parameters: [0, 0, 0, 0, 0, 0] });
  const rowLabels = rows.map((r) => r.label);
  expect(rowLabels).not.toContain('Parameters');
  expect(rowLabels).not.toContain('Priority belts');
});

test('a station slot with localLogic None reports as Stores, not Supplies', () => {
  const p = new Array(2048).fill(0);
  p[0] = 1101; // localLogic (p[1]) left at 0 -- None, a real passive-local config
  p[3] = 100;
  const rows = rowsFor({ itemId: 2104, modelIndex: 50, parameters: p });
  expect(rowValue(rows, 'Stores 1')).toContain('Iron Ingot');
  expect(rows.map((r) => r.label)).not.toContain('Supplies 1');
});

test('storage reports its banned-slot mask, not an invented "Automation" mode', () => {
  const rows = rowsFor({ itemId: 2101, modelIndex: 51, parameters: [5] });
  expect(rowValue(rows, 'Banned slots (mask)')).toBe('5');
  expect(rows.map((r) => r.label)).not.toContain('Automation');
});

test('storage with no bits set emits no row, at both a 1-word and a 110-word length', () => {
  // The fixture corpus holds both a 1-word and a 110-word depot; the mask lives
  // at index 0 either way, so both lengths must decode identically.
  expect(labels({ itemId: 2101, modelIndex: 51, parameters: [0] })).not.toContain(
    'Banned slots (mask)',
  );
  expect(
    labels({ itemId: 2101, modelIndex: 51, parameters: new Array(110).fill(0) }),
  ).not.toContain('Banned slots (mask)');
});

test('tank switches decode as booleans, not raw -1/1 words', () => {
  const rows = rowsFor({ itemId: 9001, modelIndex: 107, parameters: [-1, 1] });
  expect(rowValue(rows, 'Output switch')).toBe('no');
  expect(rowValue(rows, 'Input switch')).toBe('yes');
});

// --- Table-driven coverage for the sixteen decoders with no other test.
// Station and Splitter are exercised above; Storage and Tank are exercised
// by the four pinned tests just above this block. Every other typed
// decoder in DECODERS gets its case here so a swapped index or scale factor
// (e.g. Turret's at(p, 1) becoming at(p, 0), or Marker's /100 becoming
// /1000) fails a test instead of shipping silently.
const decoderCases: {
  type: string;
  modelIndex: number;
  parameters: number[];
  expect: [label: string, value: string][];
}[] = [
  {
    type: 'Monitor',
    modelIndex: 100,
    parameters: (() => {
      const p = new Array(20).fill(0);
      p[2] = 7; // target cargo
      p[12] = 3; // alarm mode
      p[14] = 42; // cargo filter (item id not in this catalog)
      return p;
    })(),
    expect: [
      ['Target cargo (bytes)', '7'],
      ['Alarm mode', '3'],
      ['Cargo filter', '#42'],
    ],
  },
  {
    // Real shape: [0] bans, [1] storage type 0 (no filters), module block at
    // 10 -- workEnergyPerTick, then the five 1/0 booleans, then the fighter
    // loadout. Matches all four Battlefield Analysis Bases in the fixtures.
    type: 'BattleBase',
    modelIndex: 101,
    parameters: [10, 0, 0, 0, 0, 0, 0, 0, 0, 0, 200000, 1, 1, 1, 1, 1, 0, 5101, 5101, 5101],
    expect: [
      ['Banned slots (mask)', '10'],
      ['Auto-pick', 'yes'],
      ['Fleet auto-replenish', 'yes'],
      ['Combat module', 'yes'],
      ['Auto-reconstruct', 'yes'],
      ['Construction drones', 'yes'],
      ['Drone priority', '0'],
      ['Fighter loadout', '#5101'],
    ],
  },
  {
    // Same building with a storage type set: the module block shifts to 70,
    // so reading it at 10 would report the filters as booleans.
    type: 'BattleBase',
    modelIndex: 101,
    parameters: (() => {
      const p = new Array(110).fill(0);
      p[0] = 12;
      p[1] = 9;
      p[10] = 1101;
      p[70] = 200000;
      p[73] = 1; // moduleEnabled
      return p;
    })(),
    expect: [
      ['Banned slots (mask)', '12'],
      ['Auto-pick', 'no'],
      ['Fleet auto-replenish', 'no'],
      ['Combat module', 'yes'],
      ['Auto-reconstruct', 'no'],
      ['Construction drones', 'no'],
      ['Drone priority', '0'],
    ],
  },
  {
    // EPlayerDeliveryMode { None, Recycle, Both, Supply }
    // EStorageDeliveryMode { None, Supply, Demand }
    type: 'Dispenser',
    modelIndex: 102,
    parameters: [2, 1, 0, 1],
    expect: [
      ['Player mode', 'Both'],
      ['Storage mode', 'Supply'],
      ['Courier auto-replenish', 'yes'],
    ],
  },
  {
    // Turret is the one shifted type: [1] is mode0 (group), [2] is mode1
    // (vsSettings). VSLayerMask packs two bits per band, and High is
    // Low|Normal -- 5 is GroundLow | AirLow.
    type: 'Turret',
    modelIndex: 103,
    parameters: [99, 5, 5, 0, 0],
    expect: [
      ['Turret group', '5'],
      ['Target layers', 'Ground Low, Air Low'],
    ],
  },
  {
    // Load-bearing: p[1] === p[2] === 5 in the case above means a [1]<->[2]
    // transposition (group <-> vsSettings) would still pass it. This case
    // uses p[2] = 3 (!= p[1] = 5) so a transposition fails it. Do not delete
    // this as redundant with the case above.
    type: 'Turret',
    modelIndex: 103,
    parameters: [99, 5, 3, 0, 0],
    expect: [
      ['Turret group', '5'],
      ['Target layers', 'Ground High'],
    ],
  },
  {
    type: 'Ejector',
    modelIndex: 104,
    parameters: [9],
    expect: [['Target orbit', '9']],
  },
  {
    // mode0 2 = research, mode1 = forceAccMode -- the same proliferator
    // toggle the Assembler decoder renders, and Lab must render it too.
    type: 'Lab',
    modelIndex: 105,
    parameters: [2, 1],
    expect: [
      ['Lab mode', 'Research'],
      ['Proliferator', 'production speedup'],
    ],
  },
  {
    type: 'Lab',
    modelIndex: 105,
    parameters: [1, 0],
    expect: [
      ['Lab mode', 'Matrix production'],
      ['Proliferator', 'extra products'],
    ],
  },
  {
    type: 'Inserter',
    modelIndex: 106,
    parameters: [4],
    expect: [['Stack size', '4']],
  },
  {
    type: 'Marker',
    // The Holo Beacon trap: [0] is a signal id, not a height. 37.5 / 5.0.
    modelIndex: 108,
    parameters: [13, 3750, 500],
    expect: [
      ['Marker height', '37.5'],
      ['Marker radius', '5'],
    ],
  },
  {
    type: 'Assembler',
    modelIndex: 65,
    parameters: [1],
    expect: [['Proliferator', 'production speedup']],
  },
  {
    type: 'Silo',
    modelIndex: 109,
    parameters: [1],
    expect: [['Boost', 'yes']],
  },
  {
    type: 'Geothermal',
    modelIndex: 110,
    parameters: [5],
    expect: [['Base ruin', '5']],
  },
  {
    // productId is an item id, so it resolves to a name like any filter.
    type: 'Gamma',
    modelIndex: 111,
    parameters: [1101],
    expect: [['Gamma product', 'Iron Ingot']],
  },
  {
    type: 'ArtificialStar',
    modelIndex: 112,
    parameters: [1],
    expect: [['Boost', 'yes']],
  },
  {
    // targetState, clamped to -1..1. InputUpdate runs only at state 1 and
    // input means drawing from the grid, so 1 is charge.
    type: 'Exchanger',
    modelIndex: 113,
    parameters: [-1],
    expect: [['Exchanger mode', 'Discharge']],
  },
  {
    type: 'Exchanger',
    modelIndex: 113,
    parameters: [1],
    expect: [['Exchanger mode', 'Charge']],
  },
  {
    type: 'Exchanger',
    modelIndex: 113,
    parameters: [0],
    expect: [['Exchanger mode', 'Standby']],
  },
  {
    // Belt is a known type -- overlays.ts renders its tag in the scene, but
    // the info panel had nothing of its own until this case existed. Both
    // rows must show for a tagged belt with a non-zero count.
    type: 'Belt',
    modelIndex: 120,
    parameters: [1101, 5],
    expect: [
      ['Belt tag', 'Iron Ingot'],
      ['Belt tag count', '5'],
    ],
  },
];

test('every remaining decoder decodes its documented fields', () => {
  for (const c of decoderCases) {
    const rows = rowsFor({
      itemId: 900000 + c.modelIndex,
      modelIndex: c.modelIndex,
      parameters: c.parameters,
    });
    for (const [label, value] of c.expect) {
      // soft, not hard: this is one test over ~30 cases, and a hard expect
      // aborts the loop at the first failure, reporting one broken decoder
      // and hiding every other break behind it.
      expect.soft(rowValue(rows, label), `${c.type}.${label}`).toBe(value);
    }
  }
});

test('a belt tag count of zero emits only the tag row', () => {
  // 0 is the unset value, not a count the player chose to show.
  const rows = rowsFor({ itemId: 900120, modelIndex: 120, parameters: [1101, 0] });
  expect(rowValue(rows, 'Belt tag')).toBe('Iron Ingot');
  expect(rows.map((r) => r.label)).not.toContain('Belt tag count');
});

test('an untagged belt emits no belt rows and no generic fallback', () => {
  const rows = rowsFor({ itemId: 900120, modelIndex: 120, parameters: [] });
  const rowLabels = rows.map((r) => r.label);
  expect(rowLabels).not.toContain('Belt tag');
  expect(rowLabels).not.toContain('Belt tag count');
  expect(rowLabels).not.toContain('Parameters');
});

// --- describeInferred: rows the blueprint implies but no single record
// states. Helpers copied from tests/model/beltGraph.test.ts rather than
// imported across test files.

/** Minimal belt record; only the fields the graph reads need to be real. */
function belt(index: number, outputObjIdx: number): BlueprintBuilding {
  return {
    index,
    areaIndex: 0,
    itemId: 2001,
    modelIndex: 35,
    x: index,
    y: 0,
    z: 0,
    x2: 0,
    y2: 0,
    z2: 0,
    yaw: 0,
    yaw2: 0,
    tilt: 0,
    tilt2: 0,
    pitch: 0,
    pitch2: 0,
    outputObjIdx,
    inputObjIdx: -1,
    outputToSlot: 0,
    inputFromSlot: 0,
    outputFromSlot: 0,
    inputToSlot: 0,
    outputOffset: 0,
    inputOffset: 0,
    recipeId: 0,
    filterId: 0,
    parameters: [],
    content: null,
  };
}

function bp(buildings: BlueprintBuilding[]): Blueprint {
  return { buildings } as unknown as Blueprint;
}

function sorter(
  index: number,
  inputObjIdx: number,
  outputObjIdx: number,
  filterId = 0,
): BlueprintBuilding {
  return { ...belt(index, -1), itemId: 2011, inputObjIdx, outputObjIdx, filterId };
}

function producer(index: number, recipeId: number): BlueprintBuilding {
  return { ...belt(index, -1), itemId: 2303, recipeId };
}

test('clicking a belt reports the contents inferred for its run', () => {
  // belt 0 <- sorter 1 <- assembler 2 making Iron Ingot. Nothing on the belt
  // record itself says "Iron Ingot"; the run is the only thing that knows.
  const parsed = bp([belt(0, -1), sorter(1, 2, 0), producer(2, 6)]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, catalog);

  const rows = describeInferred(parsed.buildings[0]!, parsed, runs, catalog);
  expect(rows).toEqual([{ label: 'Carries', value: 'Iron Ingot', inferred: true }]);
});

test('a belt whose run carries nothing gets no inferred row', () => {
  const parsed = bp([belt(0, -1)]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, catalog);
  expect(describeInferred(parsed.buildings[0]!, parsed, runs, catalog)).toEqual([]);
});

test('a non-belt, non-sorter building gets no inferred rows', () => {
  // Honest about what this proves: a non-belt, non-sorter index can never
  // appear in any run by construction, so this passes even without the
  // isBelt/isSorter gates in describeInferred. The real coverage for those
  // gates is the belt and sorter tests above and below.
  const parsed = bp([belt(0, -1), sorter(1, 2, 0), producer(2, 6)]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, catalog);
  expect(describeInferred(parsed.buildings[2]!, parsed, runs, catalog)).toEqual([]);
});

test('clicking a sorter reports what it takes off and puts on a belt', () => {
  // sorter 1 draws from assembler 2 (Iron Ingot) and puts onto belt 0.
  const parsed = bp([belt(0, -1), sorter(1, 2, 0), producer(2, 6)]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, catalog);

  const rows = describeInferred(parsed.buildings[1]!, parsed, runs, catalog);
  expect(rows).toEqual([{ label: 'Puts on belt', value: 'Iron Ingot', inferred: true }]);
});

test('a sorter draining a belt reports what it takes off it', () => {
  // sorter 1 draws from belt 0 and delivers into assembler 2, so it removes
  // that assembler's ingredients.
  const parsed = bp([belt(0, -1), sorter(1, 0, 2), producer(2, 6)]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, catalog);

  const rows = describeInferred(parsed.buildings[1]!, parsed, runs, catalog);
  // #1001 (Iron Ore), not "Iron Ingot": the sorter feeds INTO the assembler
  // here, so what it takes off the belt is the recipe's ingredient, not its
  // result -- and 1001 isn't in this test's catalog, so it degrades to #id.
  expect(rows).toEqual([{ label: 'Takes from belt', value: '#1001', inferred: true }]);
});

test('a filtered sorter gets no inferred row, because its filter is read not inferred', () => {
  // describeParameters already prints a Filter row for this building; a second
  // row saying the same thing, marked "inferred", would be false.
  const parsed = bp([belt(0, -1), sorter(1, 2, 0, 1101), producer(2, 6)]);
  const runs = buildBeltRuns(parsed);
  inferCarried(parsed, runs, catalog);
  expect(describeInferred(parsed.buildings[1]!, parsed, runs, catalog)).toEqual([]);
});
