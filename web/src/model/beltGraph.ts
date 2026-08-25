import type { Blueprint, BlueprintBuilding } from '../format/types';
import type { Catalog } from './catalog';
import { parseStationParams } from './stationParams';

export function isBelt(itemId: number): boolean {
  return itemId >= 2001 && itemId <= 2009;
}

export function isSorter(itemId: number): boolean {
  return itemId >= 2011 && itemId <= 2019;
}

export interface BeltRun {
  /** Building indices, head to tail. */
  belts: number[];
  /**
   * No belt feeds the head. Counts belt-to-belt inbound edges only: a sorter
   * loading the head from a station does not clear this. That is deliberate,
   * not an oversight -- suppressing it would hide real free-input
   * information in blueprints where sorter filters are left unset (the
   * heretical fixture has 0 of 18 end sorters filtered).
   */
  freeInput: boolean;
  /** The tail points at nothing at all (outputObjIdx < 0). */
  freeOutput: boolean;
  cyclic: boolean;
  /** Item ids the run carries, sorted and deduped. Filled in by inferCarried. */
  carried: number[];
  /** True if any belt in the run has an explicit item-filter tag set. */
  hasExplicitTag: boolean;
}

/**
 * Belt-to-belt successor for every belt whose output feeds another belt.
 * A belt whose `outputObjIdx` names a non-belt building, an absent index, or
 * is negative has no entry here and is treated as connected to nothing --
 * this is also what stops a run at a station rather than continuing through
 * it.
 */
export function beltSuccessors(bp: Blueprint): Map<number, number> {
  const belts = bp.buildings.filter((b) => isBelt(b.itemId));
  const beltIndices = new Set(belts.map((b) => b.index));

  const next = new Map<number, number>();
  for (const b of belts) {
    if (beltIndices.has(b.outputObjIdx)) next.set(b.index, b.outputObjIdx);
  }
  return next;
}

/**
 * Groups belts into runs.
 *
 * Blueprints are forward-linked only -- `inputObjIdx` is -1 on almost every
 * belt (277 of 283 in the heretical fixture) -- so a run's head is found by
 * inverting `outputObjIdx` rather than by reading a field.
 *
 * Segmentation is by local degree, not by walk order: a run starts at any belt
 * whose inbound count is not exactly 1, and stops before any belt whose inbound
 * count exceeds 1. Walking outward from heads instead would let whichever head
 * happened to arrive first absorb a shared tail, making the output depend on
 * building order.
 */
export function buildBeltRuns(bp: Blueprint): BeltRun[] {
  const byIndex = new Map<number, BlueprintBuilding>();
  for (const b of bp.buildings) byIndex.set(b.index, b);

  const belts = bp.buildings.filter((b) => isBelt(b.itemId));
  const next = beltSuccessors(bp);

  const inbound = new Map<number, number>();
  for (const target of next.values()) inbound.set(target, (inbound.get(target) ?? 0) + 1);

  const runs: BeltRun[] = [];
  const visited = new Set<number>();

  const makeRun = (belts: number[], cyclic: boolean): BeltRun => {
    const head = belts[0] as number;
    const tail = belts[belts.length - 1] as number;
    return {
      belts,
      freeInput: !cyclic && (inbound.get(head) ?? 0) === 0,
      freeOutput: !cyclic && (byIndex.get(tail)?.outputObjIdx ?? -1) < 0,
      cyclic,
      carried: [],
      hasExplicitTag: belts.some((i) => (byIndex.get(i)?.parameters.length ?? 0) > 0),
    };
  };

  // Pass 1: every belt whose inbound degree is not exactly 1 starts a run.
  for (const b of belts) {
    if ((inbound.get(b.index) ?? 0) === 1) continue;
    const chain: number[] = [];
    let current: number | undefined = b.index;
    while (current !== undefined && !visited.has(current)) {
      visited.add(current);
      chain.push(current);
      const successor: number | undefined = next.get(current);
      // Stop before a merge point: it begins its own run.
      if (successor === undefined || (inbound.get(successor) ?? 0) > 1) break;
      current = successor;
    }
    if (chain.length > 0) runs.push(makeRun(chain, false));
  }

  // Pass 2: anything still unvisited has inbound degree 1 everywhere, i.e. it
  // is a closed loop with no head. Walk each loop once.
  for (const b of belts) {
    if (visited.has(b.index)) continue;
    const chain: number[] = [];
    let current: number | undefined = b.index;
    while (current !== undefined && !visited.has(current)) {
      visited.add(current);
      chain.push(current);
      current = next.get(current);
    }
    if (chain.length > 0) runs.push(makeRun(chain, true));
  }

  return runs;
}

/**
 * The run a belt belongs to, or undefined if the index is not a belt in any
 * run. Linear in the number of belts; the info panel calls it once per click,
 * not once per frame.
 */
export function runForBelt(index: number, runs: readonly BeltRun[]): BeltRun | undefined {
  return runs.find((run) => run.belts.includes(index));
}

/**
 * Bearing for each belt, used to orient direction chevrons.
 *
 * Belt yaw cannot be used: the game zeroes it when serialising a belt
 * (BuildingParameters.cs sets `yaw = 0f` for BuildingType.Belt), so direction
 * only exists in the link topology. A belt's heading always points at its
 * true successor from the global link graph (`successors`), not merely the
 * next belt within its own run: a run's tail may hand off to a belt that
 * starts a different run (e.g. a run that stops right before a merge point,
 * or a chain that feeds into a cycle it isn't itself part of), and a
 * singleton run's one belt is its own tail. Only a belt with no successor at
 * all -- a genuinely free output, `outputObjIdx < 0` -- falls back to
 * reusing its predecessor's bearing; if it also has no predecessor (a
 * singleton run with a free output) it gets no heading at all, which is
 * correct, since it has no direction to show.
 */
export function computeBeltHeadings(
  runs: BeltRun[],
  positions: Map<number, readonly [number, number, number]>,
  successors: Map<number, number>,
): Map<number, number> {
  const headings = new Map<number, number>();

  for (const run of runs) {
    let previous: number | undefined;
    for (let i = 0; i < run.belts.length; i++) {
      const index = run.belts[i] as number;
      // A cyclic run wraps around to its own head; otherwise the true
      // successor comes from the global link graph (see above), not just
      // this run's own belts array.
      const nextIndex =
        run.cyclic && i === run.belts.length - 1 ? run.belts[0] : successors.get(index);
      const from = positions.get(index);
      const to = nextIndex === undefined ? undefined : positions.get(nextIndex);
      if (from && to) {
        const heading = Math.atan2(to[0] - from[0], to[2] - from[2]);
        headings.set(index, heading);
        previous = heading;
      } else if (previous !== undefined) {
        headings.set(index, previous);
      }
    }
  }

  return headings;
}

/**
 * Fills in each run's `carried` from the sorters attached to it.
 *
 * A sorter's own filter is authoritative when set, but it frequently is not --
 * across the fixtures, 0 of 18 and 0 of 22 sorters at run ends carry filters in
 * two of the four belt-bearing blueprints. The fallback reads the recipe of the
 * building at the sorter's other end.
 *
 * A sorter feeding a multi-input recipe is genuinely ambiguous: the blueprint
 * never records which of the inputs that particular sorter carries. Every
 * candidate is contributed rather than guessing one.
 */
export function inferCarried(bp: Blueprint, runs: BeltRun[], catalog: Catalog): void {
  const byIndex = new Map<number, BlueprintBuilding>();
  for (const b of bp.buildings) byIndex.set(b.index, b);

  const runOfBelt = new Map<number, BeltRun>();
  for (const run of runs) for (const index of run.belts) runOfBelt.set(index, run);

  const collected = new Map<BeltRun, Set<number>>();
  const add = (run: BeltRun, itemIds: readonly number[]): void => {
    let set = collected.get(run);
    if (!set) {
      set = new Set();
      collected.set(run, set);
    }
    for (const id of itemIds) if (id > 0) set.add(id);
  };

  for (const s of bp.buildings) {
    if (!isSorter(s.itemId)) continue;

    // The belt is the sorter's input: it drains the belt into `outputObjIdx`.
    const drained = runOfBelt.get(s.inputObjIdx);
    if (drained) add(drained, itemsForSorter(s, byIndex.get(s.outputObjIdx), 'inputs', catalog));

    // The belt is the sorter's output: `inputObjIdx` feeds the belt.
    const fed = runOfBelt.get(s.outputObjIdx);
    if (fed) add(fed, itemsForSorter(s, byIndex.get(s.inputObjIdx), 'results', catalog));
  }

  for (const run of runs) {
    const set = collected.get(run);
    run.carried = set ? [...set].sort((a, b) => a - b) : [];
  }
}

/**
 * What one sorter is inferred to move, per end.
 *
 * `inferCarried` answers the same question but attributes the result to belt
 * runs; this attributes it to the sorter, which is what the info panel needs
 * when a sorter is the selected building. A sorter belongs to no run.
 *
 * The two ends are reported separately, never merged: a sorter that takes
 * Iron Ore off a belt and puts Iron Ingot on another moves both, but not in
 * the same direction, and one merged list would say it moves each in both.
 */
export function sorterContents(
  s: BlueprintBuilding,
  bp: Blueprint,
  catalog: Catalog,
): { takes: number[]; puts: number[] } {
  const byIndex = new Map<number, BlueprintBuilding>();
  for (const b of bp.buildings) byIndex.set(b.index, b);

  // Mirrors inferCarried exactly. Draining a belt delivers into outputObjIdx,
  // so what comes off the belt is that building's inputs; feeding a belt draws
  // from inputObjIdx, so what goes on is that building's results.
  return {
    takes: [...itemsForSorter(s, byIndex.get(s.outputObjIdx), 'inputs', catalog)],
    puts: [...itemsForSorter(s, byIndex.get(s.inputObjIdx), 'results', catalog)],
  };
}

function itemsForSorter(
  sorter: BlueprintBuilding,
  other: BlueprintBuilding | undefined,
  side: 'inputs' | 'results',
  catalog: Catalog,
): readonly number[] {
  if (sorter.filterId > 0) return [sorter.filterId];
  if (!other) return [];

  // A station carries no recipe, but its storage slots say what it holds.
  // Direction matters exactly as it does for recipes: a sorter draining a
  // belt INTO a station delivers what that station demands, and one feeding
  // a belt FROM a station carries what it supplies. A slot set to None
  // (ELogisticStorage 0) is configured for neither and contributes to
  // neither -- contributing it to both would invent traffic.
  const otherType = catalog.buildingTypeFor(other.modelIndex, other.itemId);

  if (otherType === 'Station') {
    const wanted = side === 'inputs' ? 2 : 1; // 2 Demand, 1 Supply
    return parseStationParams(other.parameters)
      .storage.filter((s) => s.localLogic === wanted)
      .map((s) => s.itemId);
  }

  // A Storage building (Depot Mk.I / Mk.II) writes its
  // per-slot item filters from word 10 onward:
  //   parameters[10 + i] = storageComponent.grids[i].filter
  // (BuildingParameters.cs:1147-1149). Unfiltered slots are 0.
  //
  // Unlike a station slot, a storage filter carries NO direction: it says
  // "this slot holds item X", not whether the building supplies or demands
  // it. A depot is genuinely both a source and a sink for what it holds, so
  // the filters apply to both directions. That is not the same as the
  // station's localLogic 0 case, where the game explicitly records "neither".
  if (otherType === 'Storage') {
    return [...new Set(other.parameters.slice(10).filter((v) => v > 0))];
  }

  // A Battlefield Analysis Base is NOT laid out like a depot, even though
  // both are backed by a StorageComponent. mode0/mode1 land in
  // parameters[0]/[1] (BuildingParameters.cs:169-170); [1] is the storage
  // type, and it selects the layout. With a type, the filters occupy 10..69
  // and the module block follows at 70. Without one -- which is what all four
  // real Battlefield Analysis Bases in the fixture corpus do -- the game
  // writes no filters at all and puts the module block at 10
  // (BuildingParameters.cs:1168-1188).
  //
  // Reading `slice(10)` unconditionally would hand back workEnergyPerTick
  // (200000), five 1/0 booleans and the twelve fighter itemIds of the drone
  // loadout as if they were belt cargo.
  if (otherType === 'BattleBase') {
    // `=== 0`, not `<= 0`: the writer normalises the type to 0 or 9, but the
    // game's paste path branches on `mode1 == 0` (:1676), so a negative word
    // from a hand-edited blueprint reads as filtered there too.
    if ((other.parameters[1] ?? 0) === 0) return [];
    return [...new Set(other.parameters.slice(10, 70).filter((v) => v > 0))];
  }

  if (other.recipeId <= 0) return [];
  const recipe = catalog.recipe(other.recipeId);
  if (!recipe) return [];
  return side === 'inputs' ? recipe.items : recipe.results;
}
