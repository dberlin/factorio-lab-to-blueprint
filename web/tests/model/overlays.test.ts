import { expect, test } from '@rstest/core';
import { buildCatalog } from '../../src/model/catalog';
import type { SceneModel } from '../../src/model/layout';
import { buildOverlays } from '../../src/model/overlays';

const catalog = buildCatalog({
  items: [
    {
      id: 2303,
      name: 'Assembler',
      iconName: 'assembler-1',
      gridIndex: 1,
      modelIndex: 65,
      canBuild: true,
      color: 1,
    },
    {
      id: 1101,
      name: 'Iron Ingot',
      iconName: 'iron-plate',
      gridIndex: 2,
      modelIndex: 0,
      canBuild: false,
      color: 2,
    },
    {
      id: 2011,
      name: 'Sorter',
      iconName: 'sorter-1',
      gridIndex: 3,
      modelIndex: 41,
      canBuild: true,
      color: 3,
    },
    {
      id: 1201,
      name: 'Gear',
      iconName: '',
      gridIndex: 4,
      modelIndex: 0,
      canBuild: false,
      color: 4,
    },
    {
      id: 1104,
      name: 'Copper Ingot',
      iconName: 'copper-plate',
      gridIndex: 5,
      modelIndex: 0,
      canBuild: false,
      color: 5,
    },
  ],
  models: {
    '65': { prefab: 'a', size: [4.2, 4.6, 4.2], center: [0, 2.3, 0] },
    '41': { prefab: 's', size: [1, 1, 1], center: [0, 0, 0] },
  },
  recipes: [
    // Has its own iconName: resolves directly.
    {
      id: 61,
      name: 'Gear',
      iconName: 'gear',
      items: [1101],
      itemCounts: [1],
      results: [1201],
      resultCounts: [1],
      timeSpend: 60,
    },
    // Empty iconName (the common case: 147 of 161 real recipes): falls back
    // to the first result item's icon (here, 1101 "Iron Ingot" -> 'iron-plate'),
    // mirroring the game's RecipeProto.Preload.
    {
      id: 62,
      name: 'Smelt',
      iconName: '',
      items: [1201],
      itemCounts: [1],
      results: [1101],
      resultCounts: [1],
      timeSpend: 60,
    },
  ],
});

const atlas = {
  cell: 64,
  cols: 4,
  rows: 2,
  entries: {
    gear: [1, 0] as [number, number],
    'iron-plate': [2, 1] as [number, number],
    'copper-plate': [3, 1] as [number, number],
  },
};

const model = (over: Partial<SceneModel['instances'][0]>[]): SceneModel => ({
  instances: over.map((o, i) => ({
    index: i,
    itemId: 2303,
    modelIndex: 65,
    position: [0, 0, 0],
    size: [4, 5, 4],
    yawRad: 0,
    color: 1,
    recipeId: 0,
    filterId: 0,
    parameters: [],
    ...o,
  })),
  bounds: { min: [0, 0, 0], max: [1, 1, 1] },
  center: [0, 0, 0],
  radius: 1,
  unknownItemIds: [],
  beltRuns: [],
  beltHeadings: new Map(),
  unresolvedTagIds: [],
});

test('places a recipe icon above a producer', () => {
  const out = buildOverlays(
    model([{ recipeId: 61, position: [3, 2, -1], size: [4, 6, 4] }]),
    catalog,
    atlas,
  );
  expect(out.icons).toHaveLength(1);
  expect(out.icons[0]!.iconName).toBe('gear');
  expect(out.icons[0]!.position[0]).toBeCloseTo(3);
  expect(out.icons[0]!.position[1]).toBeGreaterThan(2); // above the box
});

test('resolves a recipe with no icon of its own via its first result item', () => {
  // Recipe 62 has iconName '', mirroring the 147/161 real recipes that rely
  // on catalog.recipeIconName's RecipeProto.Preload fallback instead of a
  // direct recipe.iconName lookup.
  const out = buildOverlays(model([{ recipeId: 62 }]), catalog, atlas);
  expect(out.icons).toHaveLength(1);
  expect(out.icons[0]!.iconName).toBe('iron-plate');
});

test('places a filter icon on a sorter', () => {
  const out = buildOverlays(
    model([{ itemId: 2011, modelIndex: 41, filterId: 1101 }]),
    catalog,
    atlas,
  );
  expect(out.icons[0]!.iconName).toBe('iron-plate');
});

test('emits nothing for buildings with no recipe or filter', () => {
  expect(buildOverlays(model([{}]), catalog, atlas).icons).toHaveLength(0);
});

test('skips icons that are absent from the atlas rather than emitting bad UVs', () => {
  const thin = { ...atlas, entries: {} };
  expect(buildOverlays(model([{ recipeId: 61 }]), catalog, thin).icons).toHaveLength(0);
});

test('uv is the normalised top-left of the atlas cell', () => {
  const out = buildOverlays(model([{ recipeId: 61 }]), catalog, atlas);
  expect(out.icons[0]!.uv[0]).toBeCloseTo(1 / 4);
  expect(out.icons[0]!.uv[1]).toBeCloseTo(0 / 2);
});

test('a tagged belt gets an icon, and a non-zero count gets a placement', () => {
  const model = {
    instances: [
      {
        index: 0,
        itemId: 2001,
        modelIndex: 35,
        position: [0, 0, 0],
        size: [1, 1, 1],
        yawRad: 0,
        color: 1,
        recipeId: 0,
        filterId: 0,
        parameters: [1101, 360],
      },
      {
        index: 1,
        itemId: 2001,
        modelIndex: 35,
        position: [1, 0, 0],
        size: [1, 1, 1],
        yawRad: 0,
        color: 1,
        recipeId: 0,
        filterId: 0,
        parameters: [1101, 0],
      },
    ],
    beltRuns: [],
    beltHeadings: new Map(),
    unknownItemIds: [],
  } as unknown as SceneModel;

  const out = buildOverlays(model, catalog, atlas);
  // both belts are tagged, so both get an icon
  expect(out.icons.filter((i) => i.iconName === 'iron-plate').length).toBe(2);
  // only the non-zero count is drawn: 0 is the unset value
  expect(out.counts.length).toBe(1);
  expect(out.counts[0]!.value).toBe(360);
});

test('a negative tag count gets an icon but no CountPlacement', () => {
  // The game clamps a negative count to 0 for display only; storage keeps
  // the negative, so a blueprint can carry one. Drawing Math.abs(-5) as "5"
  // would be a confidently wrong number, so a negative count gets the same
  // treatment as the unset value 0: an icon, but no CountPlacement.
  const model = {
    instances: [
      {
        index: 0,
        itemId: 2001,
        modelIndex: 35,
        position: [0, 0, 0],
        size: [1, 1, 1],
        yawRad: 0,
        color: 1,
        recipeId: 0,
        filterId: 0,
        parameters: [1101, -5],
      },
    ],
    beltRuns: [],
    beltHeadings: new Map(),
    unknownItemIds: [],
  } as unknown as SceneModel;

  const out = buildOverlays(model, catalog, atlas);
  expect(out.icons.filter((i) => i.iconName === 'iron-plate').length).toBe(1);
  expect(out.counts.length).toBe(0);
});

test('an unresolvable tag id draws nothing rather than a wrong icon', () => {
  const model = {
    instances: [
      {
        index: 0,
        itemId: 2001,
        modelIndex: 35,
        position: [0, 0, 0],
        size: [1, 1, 1],
        yawRad: 0,
        color: 1,
        recipeId: 0,
        filterId: 0,
        parameters: [40001, 0],
      },
    ],
    beltRuns: [],
    beltHeadings: new Map(),
    unknownItemIds: [],
  } as unknown as SceneModel;

  const out = buildOverlays(model, catalog, atlas);
  expect(out.icons.length).toBe(0);
  expect(out.counts.length).toBe(0);
});

test('a non-belt whose parameters happen to start with a resolvable item id draws nothing', () => {
  // Only belts use parameters = [signalId, count] for a player-set tag.
  // Other building kinds reuse the same `parameters` array for unrelated
  // config words (sorter stack size, station slot config, splitter
  // priority, ...), and those words are frequently item ids themselves.
  // Interstellar Logistics Stations (itemId 2104) in
  // factory-endgame-distribution-hub.txt carry paramLen=2048 slot config
  // whose first word resolves cleanly through tagIconName to a wrong icon
  // (e.g. "lab", "tesla-coil") plus a bogus count of 1 -- exactly the kind
  // of confidently-wrong icon the five-band resolver exists to prevent.
  // Gating on isBelt(inst.itemId) is what stops that.
  const model = {
    instances: [
      {
        index: 0,
        itemId: 2104,
        modelIndex: 35,
        position: [0, 0, 0],
        size: [1, 1, 1],
        yawRad: 0,
        color: 1,
        recipeId: 0,
        filterId: 0,
        parameters: [1101, 360],
      },
    ],
    beltRuns: [],
    beltHeadings: new Map(),
    unknownItemIds: [],
  } as unknown as SceneModel;

  const out = buildOverlays(model, catalog, atlas);
  expect(out.icons.length).toBe(0);
  expect(out.counts.length).toBe(0);
});

test('an unconnected run shows its contents at both free ends', () => {
  const model = {
    instances: [
      {
        index: 0,
        itemId: 2001,
        modelIndex: 35,
        position: [0, 0, 0],
        size: [1, 1, 1],
        yawRad: 0,
        color: 1,
        recipeId: 0,
        filterId: 0,
        parameters: [],
      },
      {
        index: 1,
        itemId: 2001,
        modelIndex: 35,
        position: [4, 0, 0],
        size: [1, 1, 1],
        yawRad: 0,
        color: 1,
        recipeId: 0,
        filterId: 0,
        parameters: [],
      },
    ],
    beltRuns: [
      {
        belts: [0, 1],
        freeInput: true,
        freeOutput: true,
        cyclic: false,
        carried: [1101],
        hasExplicitTag: false,
      },
    ],
    beltHeadings: new Map(),
    unknownItemIds: [],
  } as unknown as SceneModel;

  const out = buildOverlays(model, catalog, atlas);
  // one icon at the head, one at the tail
  expect(out.icons.length).toBe(2);
  expect(out.icons[0]!.position[0]).toBe(0);
  expect(out.icons[1]!.position[0]).toBe(4);
});

test('a run with its own tag is not second-guessed', () => {
  const model = {
    instances: [
      {
        index: 0,
        itemId: 2001,
        modelIndex: 35,
        position: [0, 0, 0],
        size: [1, 1, 1],
        yawRad: 0,
        color: 1,
        recipeId: 0,
        filterId: 0,
        parameters: [1101, 0],
      },
    ],
    beltRuns: [
      {
        belts: [0],
        freeInput: true,
        freeOutput: true,
        cyclic: false,
        carried: [1101],
        hasExplicitTag: true,
      },
    ],
    beltHeadings: new Map(),
    unknownItemIds: [],
  } as unknown as SceneModel;

  const out = buildOverlays(model, catalog, atlas);
  // exactly the explicit tag, no inferred endpoint icons
  expect(out.icons.length).toBe(1);
});

test('a cyclic run has no free end and so no endpoint icons', () => {
  const model = {
    instances: [
      {
        index: 0,
        itemId: 2001,
        modelIndex: 35,
        position: [0, 0, 0],
        size: [1, 1, 1],
        yawRad: 0,
        color: 1,
        recipeId: 0,
        filterId: 0,
        parameters: [],
      },
    ],
    beltRuns: [
      {
        belts: [0],
        freeInput: false,
        freeOutput: false,
        cyclic: true,
        carried: [1101],
        hasExplicitTag: false,
      },
    ],
    beltHeadings: new Map(),
    unknownItemIds: [],
  } as unknown as SceneModel;

  expect(buildOverlays(model, catalog, atlas).icons.length).toBe(0);
});

test('several carried items fan out so they do not overlap', () => {
  const model = {
    instances: [
      {
        index: 0,
        itemId: 2001,
        modelIndex: 35,
        position: [0, 0, 0],
        size: [1, 1, 1],
        yawRad: 0,
        color: 1,
        recipeId: 0,
        filterId: 0,
        parameters: [],
      },
    ],
    beltRuns: [
      {
        belts: [0],
        freeInput: true,
        freeOutput: false,
        cyclic: false,
        carried: [1101, 1104],
        hasExplicitTag: false,
      },
    ],
    beltHeadings: new Map(),
    unknownItemIds: [],
  } as unknown as SceneModel;

  const out = buildOverlays(model, catalog, atlas);
  expect(out.icons.length).toBe(2);
  expect(out.icons[0]!.position[0]).not.toBe(out.icons[1]!.position[0]);
});

test('a single-belt run that is free at both ends draws its icon once, not twice', () => {
  // belts[0] === tail for a single-belt run, so when freeInput and freeOutput
  // are both true, a naive array of "ends" holds the same belt index twice
  // and every carried icon gets drawn twice at the identical position.
  const model = {
    instances: [
      {
        index: 0,
        itemId: 2001,
        modelIndex: 35,
        position: [0, 0, 0],
        size: [1, 1, 1],
        yawRad: 0,
        color: 1,
        recipeId: 0,
        filterId: 0,
        parameters: [],
      },
    ],
    beltRuns: [
      {
        belts: [0],
        freeInput: true,
        freeOutput: true,
        cyclic: false,
        carried: [1101],
        hasExplicitTag: false,
      },
    ],
    beltHeadings: new Map(),
    unknownItemIds: [],
  } as unknown as SceneModel;

  const out = buildOverlays(model, catalog, atlas);
  expect(out.icons.length).toBe(1);
});
