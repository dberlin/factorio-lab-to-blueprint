import { readFileSync } from 'node:fs';
import { expect, test } from '@rstest/core';
import type { Blueprint, BlueprintBuilding } from '../../src/format';
import { parseBlueprint } from '../../src/format';
import { buildCatalog } from '../../src/model/catalog';
import { buildSceneModel } from '../../src/model/layout';
import { visualScaleFor } from '../../src/model/visualScale';

const catalog = buildCatalog({
  items: [
    {
      id: 2001,
      name: 'Belt',
      iconName: 'belt-1',
      gridIndex: 1,
      modelIndex: 35,
      canBuild: true,
      color: 0xe3a263,
    },
    {
      id: 2303,
      name: 'Assembler',
      iconName: 'assembler-1',
      gridIndex: 2,
      modelIndex: 65,
      canBuild: true,
      color: 0xedab5c,
    },
    {
      id: 2309,
      name: 'Chemical Plant',
      iconName: 'chemical-plant',
      gridIndex: 3,
      modelIndex: 70,
      canBuild: true,
      color: 0x5a8fb0,
    },
    // Mirrors the real splitter: the item's default model (38) is not the
    // model every placed record actually carries (some carry 39).
    {
      id: 2020,
      name: 'Splitter',
      iconName: 'splitter',
      gridIndex: 4,
      modelIndex: 38,
      canBuild: true,
      color: 0x9aa7b0,
    },
    {
      id: 2003,
      name: 'Conveyor Belt Mk.III',
      iconName: 'belt-3',
      gridIndex: 6,
      modelIndex: 37,
      canBuild: true,
      color: 0xe3a263,
    },
    // Resolvable via the item band of tagIconName (1000 <= id < 12000).
    {
      id: 1101,
      name: 'Iron Ore',
      iconName: 'iron-ore',
      gridIndex: 7,
      modelIndex: 35,
      canBuild: false,
      color: 0x8a8a8a,
    },
  ],
  models: {
    '35': { prefab: 'belt-1', size: [1, 0.5, 1], center: [0, 0.1, 0] },
    '37': { prefab: 'belt-3', size: [1, 0.5, 1], center: [0, 0.1, 0] },
    '65': { prefab: 'assembler-1', size: [4.2, 4.6, 4.2], center: [0, 2.3, 0] },
    // Mirrors the real chemical plant: a non-zero horizontal centre, which is
    // the case that catches a mirrored (wrong-handed) yaw rotation.
    '70': { prefab: 'chemical-plant', size: [9.2, 6.3, 5.3], center: [0.48, 3.15, 0.78] },
    // Real splitter boxes: 38 is item 2020's default, 39 is what the two
    // divergent fixture records actually carry.
    '38': { prefab: 'splitter', size: [2.7, 2.4, 2.7], center: [0, 1.2, 0] },
    '39': { prefab: 'splitter-alt', size: [2.0, 2.94, 2.7], center: [0, 1.47, 0] },
  },
  recipes: [],
});

function building(over: Partial<BlueprintBuilding>): BlueprintBuilding {
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

function blueprint(buildings: BlueprintBuilding[]): Blueprint {
  return {
    header: {
      headerVersion: 1,
      layout: 10,
      icons: [0, 0, 0, 0, 0],
      timestamp: 0n,
      gameVersion: '0.10.34',
      shortDesc: '',
      author: '',
      customVersion: '',
      attributes: [],
      description: '',
    },
    hashValid: true,
    version: 2,
    cursorOffsetX: 0,
    cursorOffsetY: 0,
    cursorTargetArea: 0,
    dragBoxSizeX: 0,
    dragBoxSizeY: 0,
    primaryAreaIdx: 0,
    patch: 1,
    areas: [],
    buildings,
  };
}

test('maps blueprint (x,y,z) to three (x, z, -y) with the box centre applied', () => {
  const m = buildSceneModel(blueprint([building({ x: 3, y: 21, z: 0.5 })]), catalog);
  const inst = m.instances[0]!;
  // world x = bp.x; world y = bp.z + center.y; world z = -bp.y
  expect(inst.position[0]).toBeCloseTo(3);
  expect(inst.position[1]).toBeCloseTo(0.5 + 2.3);
  expect(inst.position[2]).toBeCloseTo(-21);
});

test('yaw becomes a negative radian rotation about world Y', () => {
  const m = buildSceneModel(blueprint([building({ yaw: 90 })]), catalog);
  expect(m.instances[0]!.yawRad).toBeCloseTo(-Math.PI / 2);
});

// Independent check that the box-centre rotation matches three.js's handedness.
//
// three.js Matrix4.makeRotationY(theta) rotates a vector (x, y, z) as:
//   x' =  x*cos(theta) + z*sin(theta)
//   z' = -x*sin(theta) + z*cos(theta)
//
// Chemical plant fixture (modelIndex 70): center = (0.48, 3.15, 0.78).
// Building placed at bp (x=10, y=5, z=1), yaw=90 degrees.
//
// yawRad = -90deg * PI/180 = -PI/2
//   cos(-PI/2) = 0
//   sin(-PI/2) = -1
//
// cx = 0.48*cos + 0.78*sin = 0.48*0 + 0.78*(-1) = -0.78
// cz = -0.48*sin + 0.78*cos = -0.48*(-1) + 0.78*0 = 0.48
//
// position = [bp.x + cx, bp.z + center.y, -bp.y + cz]
//          = [10 + (-0.78), 1 + 3.15, -5 + 0.48]
//          = [9.22, 4.15, -4.52]
test('a non-zero horizontal centre rotates with the same handedness as the three.js mesh', () => {
  const m = buildSceneModel(
    blueprint([building({ itemId: 2309, modelIndex: 70, x: 10, y: 5, z: 1, yaw: 90 })]),
    catalog,
  );
  const inst = m.instances[0]!;
  expect(inst.position[0]).toBeCloseTo(9.22);
  expect(inst.position[1]).toBeCloseTo(4.15);
  expect(inst.position[2]).toBeCloseTo(-4.52);
});

// The record's modelIndex wins over the item's default modelIndex.
//
// This is not hypothetical: across the 13,690 buildings in tests/fixtures/,
// exactly two records disagree with their item's default, and both are the
// splitter — the case that makes box data derived from the game's own protos
// necessary, rather than a community table. Item 2020 defaults to model 38
// (size [2.7,2.4,2.7], center [0,1.2,0]) but those records carry model 39
// (size [2.0,2.94,2.7], center [0,1.47,0]).
//
// Expected with model 39 and the DEFAULT visual scale [0.9, 0.999, 0.9]:
//   size[0]     = 2.0 * 0.9   = 1.8      (model 38 would give 2.7*0.9 = 2.43)
//   position[1] = 0 + 1.47    = 1.47     (model 38 would give 1.2)
test("uses the record's own modelIndex, not the item's default modelIndex", () => {
  const m = buildSceneModel(
    blueprint([building({ itemId: 2020, modelIndex: 39, x: 0, y: 0, z: 0 })]),
    catalog,
  );
  const inst = m.instances[0]!;
  expect(inst.size[0]).toBeCloseTo(1.8);
  expect(inst.size[1]).toBeCloseTo(2.94 * 0.999);
  expect(inst.position[1]).toBeCloseTo(1.47);
  // Pin the negative too, so a regression to the item's default is unambiguous.
  expect(inst.size[0]).not.toBeCloseTo(2.7 * 0.9);
  expect(inst.position[1]).not.toBeCloseTo(1.2);
});

test("a bogus modelIndex still falls back to the item's default box", () => {
  const m = buildSceneModel(
    blueprint([building({ itemId: 2020, modelIndex: 9999, x: 0, y: 0, z: 0 })]),
    catalog,
  );
  const inst = m.instances[0]!;
  expect(inst.size[0]).toBeCloseTo(2.7 * 0.9);
  expect(inst.position[1]).toBeCloseTo(1.2);
});

test('belts are thinned vertically so stacked belts stay visually separate', () => {
  const m = buildSceneModel(
    blueprint([
      building({ index: 0, itemId: 2001, modelIndex: 35, z: 0 }),
      building({ index: 1, itemId: 2001, modelIndex: 35, z: 0.5 }),
    ]),
    catalog,
  );
  const [a, b] = m.instances as [(typeof m.instances)[0], (typeof m.instances)[0]];
  const height = a.size[1];
  expect(height).toBeLessThan(0.25); // raw selectSize would be 0.5
  const gap = Math.abs(b.position[1] - a.position[1]) - height;
  expect(gap).toBeGreaterThan(0); // they must not touch
});

test('non-belts keep their real footprint (only a small anti-z-fight shrink)', () => {
  const m = buildSceneModel(blueprint([building({})]), catalog);
  const s = m.instances[0]!.size;
  expect(s[0]).toBeGreaterThan(3.7);
  expect(s[0]).toBeLessThanOrEqual(4.2);
  expect(s[1]).toBeCloseTo(4.6, 1);
});

test('computes bounds and a centre for camera framing', () => {
  const m = buildSceneModel(
    blueprint([building({ index: 0, x: 0, y: 0 }), building({ index: 1, x: 10, y: 20 })]),
    catalog,
  );
  expect(m.center[0]).toBeCloseTo(5);
  expect(m.center[2]).toBeCloseTo(-10);
  expect(m.radius).toBeGreaterThan(0);
});

test('unknown items are reported and skipped rather than crashing', () => {
  const m = buildSceneModel(blueprint([building({ itemId: 9999, modelIndex: 9999 })]), catalog);
  expect(m.instances).toHaveLength(0);
  expect(m.unknownItemIds).toEqual([9999]);
});

test('visualScaleFor thins belts and leaves other buildings near full size', () => {
  expect(visualScaleFor(2003)[1]).toBeLessThan(0.5);
  expect(visualScaleFor(2303)[1]).toBeGreaterThan(0.9);
});

/** Minimal belt record, same shape as beltGraph.test.ts's `belt` helper. */
function beltBuilding(index: number): BlueprintBuilding {
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
  };
}

test('collects belt tag ids that resolve to no icon', () => {
  const bp = {
    buildings: [
      // 40001 is in the tech band, which is deliberately not extracted
      { ...beltBuilding(0), parameters: [40001, 0] },
      { ...beltBuilding(1), parameters: [1101, 0] },
    ],
    areas: [],
  } as unknown as Blueprint;

  const model = buildSceneModel(bp, catalog);
  expect(model.unresolvedTagIds).toEqual([40001]);
});

// Regression: a non-belt's parameters[0] is a different payload entirely
// (sorter stack size, station slot config, ...), not a tag id. Reading it as
// one produces a false "unrecognised belt tag" warning on almost every
// blueprint, which buries the one genuine case the diagnostic exists for.
test('ignores non-belt parameters when collecting unresolved tags', () => {
  const bp = {
    buildings: [
      // Belt with an unresolvable tag: must be reported.
      { ...beltBuilding(0), parameters: [40001, 0] },
      // Non-belt (assembler) whose parameters[0] happens to look like an
      // unresolvable tag id: must NOT be reported.
      { ...building({ index: 1 }), parameters: [40002, 0] },
    ],
    areas: [],
  } as unknown as Blueprint;

  const model = buildSceneModel(bp, catalog);
  expect(model.unresolvedTagIds).toEqual([40001]);
});

test('carries belt tag parameters onto the instance', () => {
  const bp = parseBlueprint(
    readFileSync('tests/fixtures/factory-heretical-smelter-block.txt', 'utf8'),
  );
  const model = buildSceneModel(bp, catalog);
  const tagged = model.instances.filter((i) => i.parameters.length > 0);
  // 11 tagged belts, each exactly [signalId, count]
  expect(tagged.length).toBe(11);
  expect(tagged.every((i) => i.parameters.length === 2)).toBe(true);
});
