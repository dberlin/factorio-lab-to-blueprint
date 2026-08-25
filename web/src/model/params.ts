import type { Blueprint, BlueprintBuilding } from '../format';
import { type BeltRun, isBelt, isSorter, runForBelt, sorterContents } from './beltGraph';
import type { BuildingType, Catalog } from './catalog';
import { IO_DIR, LOGISTIC_STORAGE, parseStationParams } from './stationParams';

export interface ParamRow {
  label: string;
  value: string;
  /**
   * The value was derived from the surrounding blueprint, not read from this
   * building's own record. The panel marks these so a reader never mistakes
   * an inference for a recorded setting.
   */
  inferred?: boolean;
}

const at = (p: readonly number[], i: number): number | undefined => p[i];
const bool = (v: number | undefined): string | undefined =>
  v === undefined ? undefined : v > 0 ? 'yes' : 'no';
const enumName = (table: readonly string[], v: number | undefined): string =>
  v === undefined ? '?' : (table[v] ?? `#${v}`);

/** Lab mode0 (BuildingParameters.cs:1254-1263). */
const LAB_MODE = ['Idle', 'Matrix production', 'Research'] as const;
/** EPlayerDeliveryMode, verbatim from the DLL. */
const PLAYER_DELIVERY = ['None', 'Recycle', 'Both', 'Supply'] as const;
/** EStorageDeliveryMode, verbatim from the DLL. */
const STORAGE_DELIVERY = ['None', 'Supply', 'Demand'] as const;

/**
 * VSLayerMask packs a two-bit level into a field per band, so the enum's
 * composite members are unions rather than distinct values: GroundHigh (3) is
 * GroundLow (1) | GroundNormal (2). Decode by band, not by member lookup.
 */
const VS_BANDS = ['Ground', 'Air', 'Orbit', 'Space'] as const;
const VS_LEVELS = ['', 'Low', 'Normal', 'High'] as const;

function targetLayers(mask: number): string {
  const on: string[] = [];
  VS_BANDS.forEach((band, i) => {
    const level = (mask >> (i * 2)) & 0b11;
    if (level > 0) on.push(`${band} ${VS_LEVELS[level]}`);
  });
  return on.join(', ');
}

/**
 * One decoder per BuildingType, mirroring BuildingParameters.ToParamsArray.
 *
 * Every decoder must tolerate a block shorter than the current game writes:
 * the fixture corpus holds 4- and 6-word splitters and 1- and 110-word depots,
 * because older blueprints wrote fewer words. Reading past the end yields
 * undefined, so omit the row rather than printing a wrong value.
 */
// Partial, not total: Miner is a real extractor type with no parameter
// block worth decoding, so it is deliberately absent. Keying on
// BuildingType rather than string means a vocabulary change breaks the
// build here instead of silently degrading to the generic row.
const DECODERS: Partial<
  Record<BuildingType, (p: readonly number[], catalog: Catalog) => ParamRow[]>
> = {
  Station(p, catalog) {
    const { storage, beltSlots, settings } = parseStationParams(p);
    const rows: ParamRow[] = [];
    storage.forEach((s) => {
      const name = catalog.item(s.itemId)?.name ?? `#${s.itemId}`;
      // Label by role so the panel reads as intent, not as a slot dump.
      // Three-way, not a Demand/else ternary: localLogic 0 is None, a real
      // configuration where the slot is passive locally and only its remote
      // role is set. Calling that "Supplies" states the opposite of the truth.
      const role = s.localLogic === 2 ? 'Demands' : s.localLogic === 1 ? 'Supplies' : 'Stores';
      rows.push({
        // s.slot, not the array index: belt slots reference storage by
        // `storageIdx = rawSlot + 1`, and unconfigured slots are skipped, so
        // numbering by array position makes "Output -> slot 4" point at the
        // wrong row on any station with a gap (4 of the 27 stations in the
        // fixture corpus).
        label: `${role} ${s.slot + 1}`,
        value: `${name} — max ${s.max}, remote ${enumName(LOGISTIC_STORAGE, s.remoteLogic)}`,
      });
    });
    const assigned = beltSlots.filter((b) => b.dir !== 0);
    if (assigned.length > 0) {
      // The game writes all 32 storage slots densely, but only the configured
      // ones are printed, so a belt can name a slot that has no row above. Two
      // such references exist in the fixture corpus. Saying "slot 4" for a row
      // the reader cannot find is the same class of error as naming the wrong
      // row, so mark it rather than leave it dangling.
      const printed = new Set(storage.map((s) => s.slot + 1));
      const target = (idx: number): string =>
        idx <= 0 ? '' : ` → slot ${idx}${printed.has(idx) ? '' : ' (unconfigured)'}`;
      rows.push({
        label: 'Belt slots',
        value: assigned
          // storageIdx is 1-based; 0 means the slot feeds nothing specific.
          .map((b) => `${enumName(IO_DIR, b.dir)}${target(b.storageIdx)}`)
          .join(', '),
      });
    }
    if (settings) {
      // Percentages of a vessel's carrying capacity, not counts:
      // StationComponent computes (droneCarries - 1) * deliveryDrones / 100
      // (:1542) and (shipCarries - 1) * deliveryShips / 100 (:3384), and
      // defaults them to 10 and 100 (:297-298). All 27 real stations in the
      // fixture corpus are bounded by 100, consistent with a percentage.
      rows.push({
        label: 'Delivery load (drones / ships)',
        value: `${settings.deliveryDrones}% / ${settings.deliveryShips}%`,
      });
      if (settings.pilerCount > 0)
        rows.push({ label: 'Piler', value: String(settings.pilerCount) });
      rows.push({ label: 'Warper required', value: settings.warperNecessary ? 'yes' : 'no' });
    }
    return rows;
  },

  Splitter(p) {
    const letters = ['A', 'B', 'C', 'D'];
    const on = letters.filter((_, i) => (at(p, i) ?? 0) > 0);
    return on.length > 0 ? [{ label: 'Priority belts', value: on.join(', ') }] : [];
  },

  Monitor(p, catalog) {
    // No fixture contains a monitor, so this layout is transcribed from
    // BuildingParameters.cs and exercised only by synthetic tests.
    const rows: ParamRow[] = [];
    const filter = at(p, 14);
    if (filter && filter > 0) {
      rows.push({ label: 'Cargo filter', value: catalog.item(filter)?.name ?? `#${filter}` });
    }
    const target = at(p, 2);
    // targetCargoBytes is a byte-count threshold, not an item id -- name the
    // label accordingly so it doesn't read like a cargo item.
    if (target !== undefined) rows.push({ label: 'Target cargo (bytes)', value: String(target) });
    const alarm = at(p, 12);
    if (alarm !== undefined && alarm > 0) rows.push({ label: 'Alarm mode', value: String(alarm) });
    return rows;
  },

  Storage(p) {
    // [0] is storageComponent.bans (BuildingParameters.cs:1136), a bitmask of
    // banned slots -- NOT an automation toggle. Reported as the raw mask
    // because the per-bit meaning is not established.
    const bans = at(p, 0);
    return bans === undefined || bans === 0
      ? []
      : [{ label: 'Banned slots (mask)', value: String(bans) }];
  },

  BattleBase(p, catalog) {
    // mode0/mode1 are written into parameters[0]/[1] on the blueprint path
    // (BuildingParameters.cs:169-170), so [0] is storageComponent.bans and
    // [1] is the storage type -- NOT a drone mode.
    //
    // [1] also picks the layout: with a storage type the filters occupy
    // 10..69 and the module block starts at 70; without one the game writes
    // no filters at all and the module block starts at 10
    // (BuildingParameters.cs:1168-1188). All four real Battlefield Analysis
    // Bases in the fixture corpus take the second branch.
    //
    // The decoder mirrors the WRITER, which produced the bytes in the file.
    // The game's own paste path uses `10 + storageComponent.size` instead
    // (:1699), which agrees only when size is 60. That asymmetry belongs to
    // the game, and a reader must follow the writer.
    const rows: ParamRow[] = [];
    const bans = at(p, 0);
    if (bans !== undefined && bans !== 0) {
      rows.push({ label: 'Banned slots (mask)', value: String(bans) });
    }
    // `!== 0`, not `> 0`: the writer normalises the type to 0 or 9, but the
    // game's paste path branches on `mode1 == 0` (:1676), so a negative word
    // from a hand-edited blueprint takes the filtered branch there too.
    const base = (at(p, 1) ?? 0) !== 0 ? 70 : 10;

    // Every guard below is an EXISTENCE check -- `bool()` returns undefined
    // past the end of the block and 'no' for a zero word, and 'no' is truthy.
    // Spelled out so it does not read like the `!== 0` value guard above.
    const flag = (offset: number, label: string): void => {
      const v = bool(at(p, base + offset));
      if (v !== undefined) rows.push({ label, value: v });
    };
    flag(1, 'Auto-pick');
    flag(2, 'Fleet auto-replenish');
    flag(3, 'Combat module');
    flag(4, 'Auto-reconstruct');
    flag(5, 'Construction drones');
    const priority = at(p, base + 6);
    if (priority !== undefined) {
      rows.push({ label: 'Drone priority', value: String(priority) });
    }
    // base + 7 onward is combatModule.moduleFleets[0].fighters[k].itemId
    // (:1185-1188) -- the loadout, up to twelve entries, all the same item in
    // every real base in the fixture corpus.
    const fleet = [...new Set(p.slice(base + 7, base + 19).filter((v) => v > 0))];
    if (fleet.length > 0) {
      rows.push({
        label: 'Fighter loadout',
        value: fleet.map((id) => catalog.item(id)?.name ?? `#${id}`).join(', '),
      });
    }
    return rows;
  },

  Dispenser(p) {
    const rows: ParamRow[] = [];
    const player = at(p, 0);
    const storage = at(p, 1);
    if (player !== undefined)
      rows.push({ label: 'Player mode', value: enumName(PLAYER_DELIVERY, player) });
    if (storage !== undefined)
      rows.push({ label: 'Storage mode', value: enumName(STORAGE_DELIVERY, storage) });
    const replenish = bool(at(p, 3));
    if (replenish) rows.push({ label: 'Courier auto-replenish', value: replenish });
    return rows;
  },

  Turret(p) {
    // The one shifted type: _parameters[1..4] = mode0..mode3
    // (BuildingParameters.cs:303-314). group is a plain byte, not an enum.
    const rows: ParamRow[] = [];
    const group = at(p, 1);
    if (group !== undefined) rows.push({ label: 'Turret group', value: String(group) });
    const vs = at(p, 2);
    if (vs !== undefined && vs > 0) {
      // No fixture turret sets vsSettings, so this row is exercised only by
      // synthetic decoderCases -- same caveat as the Monitor decoder above.
      rows.push({ label: 'Target layers', value: targetLayers(vs) });
    }
    return rows;
  },

  Ejector(p) {
    const orbit = at(p, 0);
    return orbit === undefined ? [] : [{ label: 'Target orbit', value: String(orbit) }];
  },

  Lab(p) {
    const rows: ParamRow[] = [];
    const mode = at(p, 0);
    if (mode !== undefined) rows.push({ label: 'Lab mode', value: enumName(LAB_MODE, mode) });
    // mode1 = forceAccMode, the same toggle Assembler renders.
    const acc = at(p, 1);
    if (acc !== undefined) {
      rows.push({
        label: 'Proliferator',
        value: acc > 0 ? 'production speedup' : 'extra products',
      });
    }
    return rows;
  },

  Inserter(p) {
    const stack = at(p, 0);
    return stack === undefined ? [] : [{ label: 'Stack size', value: String(stack) }];
  },

  Tank(p) {
    // outputSwitch / inputSwitch (BuildingParameters.cs:1195-1196), and both
    // are 1 / -1 like the station booleans -- printing the raw word would
    // show "-1" where the honest answer is "no".
    const rows: ParamRow[] = [];
    const out = bool(at(p, 0));
    const inp = bool(at(p, 1));
    if (out) rows.push({ label: 'Output switch', value: out });
    if (inp) rows.push({ label: 'Input switch', value: inp });
    return rows;
  },

  Marker(p) {
    const rows: ParamRow[] = [];
    const height = at(p, 1);
    const radius = at(p, 2);
    if (height !== undefined) rows.push({ label: 'Marker height', value: String(height / 100) });
    if (radius !== undefined) rows.push({ label: 'Marker radius', value: String(radius / 100) });
    return rows;
  },

  Assembler(p) {
    // forceAccMode (BuildingParameters.cs:1205): the proliferator toggle.
    // The single most common typed block in the fixture corpus -- ~127 smelters,
    // refineries and assemblers carry it.
    const acc = at(p, 0);
    return acc === undefined
      ? []
      : [{ label: 'Proliferator', value: acc > 0 ? 'production speedup' : 'extra products' }];
  },

  Silo(p) {
    const boost = bool(at(p, 0));
    return boost ? [{ label: 'Boost', value: boost }] : [];
  },

  Geothermal(p) {
    const ruin = at(p, 0);
    return ruin === undefined ? [] : [{ label: 'Base ruin', value: String(ruin) }];
  },

  Gamma(p, catalog) {
    // mode0 = genPool[..].productId (BuildingParameters.cs:907), checked
    // against prefabDesc.powerProductId on paste (:3273) -- an item id, so
    // it resolves through the catalog exactly like a filter or a belt tag.
    const product = at(p, 0);
    if (product === undefined || product <= 0) return [];
    return [{ label: 'Gamma product', value: catalog.item(product)?.name ?? `#${product}` }];
  },

  ArtificialStar(p) {
    const boost = bool(at(p, 0));
    return boost ? [{ label: 'Boost', value: boost }] : [];
  },

  Exchanger(p) {
    // targetState = Mathf.Clamp(parameters[0], -1, 1). InputUpdate runs only
    // at state 1 and OutputUpdate only at -1 (PowerExchangerComponent.cs:249,
    // :296); input draws from the grid, so 1 is charging.
    const state = at(p, 0);
    if (state === undefined) return [];
    const name = state > 0 ? 'Charge' : state < 0 ? 'Discharge' : 'Standby';
    return [{ label: 'Exchanger mode', value: name }];
  },

  // overlays.ts renders belt tags in the 3D scene; this reads the same
  // [signalId, count] pair for the info panel, which is a separate surface
  // with nothing of its own. Nothing about scene rendering moves here.
  Belt(p, catalog) {
    const rows: ParamRow[] = [];
    const tagId = at(p, 0);
    if (tagId === undefined || tagId <= 0) return rows;
    // Prefer a real item name over the bare icon name, then the id.
    const label = catalog.item(tagId)?.name ?? catalog.tagIconName(tagId) ?? `#${tagId}`;
    rows.push({ label: 'Belt tag', value: label });
    const count = at(p, 1);
    // 0 is the unset value, not a number the player chose to show.
    if (count !== undefined && count > 0) {
      rows.push({ label: 'Belt tag count', value: String(count) });
    }
    return rows;
  },
};

/**
 * Decodes the parameter block far enough to be useful in the info panel.
 * Unrecognised layouts fall back to a raw count rather than guessing.
 */
export function describeParameters(b: BlueprintBuilding, catalog: Catalog): ParamRow[] {
  const rows: ParamRow[] = [];

  if (b.recipeId > 0) {
    rows.push({ label: 'Recipe', value: catalog.recipe(b.recipeId)?.name ?? `#${b.recipeId}` });
  }
  if (b.filterId > 0) {
    rows.push({ label: 'Filter', value: catalog.item(b.filterId)?.name ?? `#${b.filterId}` });
  }
  if (b.outputObjIdx >= 0) {
    rows.push({ label: 'Output to', value: `building ${b.outputObjIdx} (slot ${b.outputToSlot})` });
  }
  if (b.inputObjIdx >= 0) {
    rows.push({
      label: 'Input from',
      value: `building ${b.inputObjIdx} (slot ${b.inputFromSlot})`,
    });
  }
  if (b.parameters.length > 0) {
    const type = catalog.buildingTypeFor(b.modelIndex, b.itemId);
    const decoder = type ? DECODERS[type] : undefined;
    if (decoder) {
      // A known type that yields no rows has nothing to report -- a splitter
      // with no priority belt set, say. Falling through to the word count
      // there would claim "we don't understand this block" when we do, and
      // would make that indistinguishable from a genuinely unknown type.
      rows.push(...decoder(b.parameters, catalog));
    } else {
      // Unrecognised layout: report the raw shape rather than guessing.
      rows.push({ label: 'Parameters', value: `${b.parameters.length} word(s)` });
    }
  }
  if (b.content) rows.push({ label: 'Label', value: b.content });

  return rows;
}

const names = (ids: readonly number[], catalog: Catalog): string =>
  ids.map((id) => catalog.item(id)?.name ?? `#${id}`).join(', ');

/**
 * Rows the blueprint implies but no single record states.
 *
 * Deliberately separate from describeParameters: that function decodes one
 * building's own parameter block and all nineteen of its decoders are pure in
 * (parameters, catalog). Inference needs the whole blueprint and the belt
 * runs, and threading those through would hand every decoder two arguments
 * none of them use.
 */
export function describeInferred(
  b: BlueprintBuilding,
  bp: Blueprint,
  runs: readonly BeltRun[],
  catalog: Catalog,
): ParamRow[] {
  if (isBelt(b.itemId)) {
    const run = runForBelt(b.index, runs);
    if (!run || run.carried.length === 0) return [];
    // Deliberate divergence from overlays.ts, which suppresses the inferred
    // icon in the 3D scene when run.hasExplicitTag is set: the scene has one
    // icon slot to spend, so an explicit tag wins there. This panel has room
    // for both, so it reports the inference regardless. Where a multi-output
    // recipe feeds the run, the inference can be an honest superset of the
    // player's tag rather than a disagreement with it.
    return [{ label: 'Carries', value: names(run.carried, catalog), inferred: true }];
  }

  if (isSorter(b.itemId)) {
    // A set filterId is read from the record, not inferred -- describeParameters
    // already emits it as the Filter row. Repeating it here, marked "inferred",
    // would misreport how confident we are.
    if (b.filterId > 0) return [];

    const beltIndices = new Set(runs.flatMap((run) => run.belts));
    const { takes, puts } = sorterContents(b, bp, catalog);
    const rows: ParamRow[] = [];
    // Report an end only when that end is actually a belt.
    if (beltIndices.has(b.inputObjIdx) && takes.length > 0) {
      rows.push({ label: 'Takes from belt', value: names(takes, catalog), inferred: true });
    }
    if (beltIndices.has(b.outputObjIdx) && puts.length > 0) {
      rows.push({ label: 'Puts on belt', value: names(puts, catalog), inferred: true });
    }
    return rows;
  }

  return [];
}
