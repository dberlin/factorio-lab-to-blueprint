import { isBelt } from './beltGraph';
import { RIBBON_WIDTH } from './beltRibbons';
import type { Catalog } from './catalog';
import type { SceneModel } from './layout';
import type { Atlas } from './schemas';

/**
 * Icon edge length, in world units, for an icon that sits on a building. The
 * building is metres across, so the icon can be too.
 */
const BUILDING_ICON_SIZE = 1.6;

/**
 * Icon edge length for an icon that sits on a BELT -- a player's tag or an
 * inferred endpoint.
 *
 * Belts were being labelled at the building size, which is over three ribbon
 * widths and about two tiles: on a blueprint with dozens of lanes the icons
 * covered the very geometry they annotate. Expressed against RIBBON_WIDTH
 * rather than as a bare number so a future change to the ribbon carries its
 * labels with it.
 */
const BELT_ICON_SIZE = RIBBON_WIDTH * 1.5;

/**
 * Glyph size for the "+N" badge beside an endpoint icon. Smaller than the
 * icon it qualifies: it is a footnote, not a second label.
 */
const BADGE_GLYPH_SIZE = BELT_ICON_SIZE * 0.7;

export interface IconPlacement {
  position: [number, number, number];
  iconName: string;
  uv: [number, number];
  /** World-space edge length of the icon quad. */
  scale: number;
}

export interface CountPlacement {
  position: [number, number, number];
  value: number;
  /** Render as "+N" rather than "N" (an endpoint's further candidates). */
  plus?: boolean;
  /** World-space glyph size; the caller's default applies when absent. */
  scale?: number;
}

export interface Overlays {
  icons: IconPlacement[];
  counts: CountPlacement[];
}

export interface OverlayOptions {
  /**
   * Draw the inferred endpoint layer. On by default; the toolbar toggle is
   * there for blueprints where the inference is noise rather than news.
   */
  endpointIcons?: boolean;
}

/**
 * One icon per building that has a configured recipe (producers) or filter
 * (sorters, storage), plus one icon (and optionally a count) per belt the
 * player tagged in-game. Icons float just above the box top.
 *
 * Recipe icons are resolved via `catalog.recipeIconName`, not
 * `catalog.recipe(id)?.iconName`: 147 of 161 real recipes have an empty
 * `iconName` and rely on the game's RecipeProto.Preload fallback to the
 * first result item's icon instead (see catalog.ts).
 */
export function buildOverlays(
  model: SceneModel,
  catalog: Catalog,
  atlas: Atlas,
  options: OverlayOptions = {},
): Overlays {
  const { endpointIcons = true } = options;
  const icons: IconPlacement[] = [];
  const counts: CountPlacement[] = [];

  for (const inst of model.instances) {
    let iconName: string | undefined;
    if (inst.recipeId > 0) iconName = catalog.recipeIconName(inst.recipeId);
    else if (inst.filterId > 0) iconName = catalog.item(inst.filterId)?.iconName;
    if (iconName) {
      const cell = atlas.entries[iconName];
      if (cell) {
        icons.push({
          iconName,
          position: [inst.position[0], inst.position[1] + inst.size[1] / 2 + 0.6, inst.position[2]],
          uv: [cell[0] / atlas.cols, cell[1] / atlas.rows],
          // Machine-sized, because it labels a machine. The isBelt arm is for
          // the one case that would reach here on a belt -- a decoded belt
          // record carrying a filterId -- which must obey the belt cap like
          // every other mark drawn on a lane.
          scale: isBelt(inst.itemId) ? BELT_ICON_SIZE : BUILDING_ICON_SIZE,
        });
      }
    }

    // Belt tags: parameters is either empty or exactly [signalId, count].
    // The game writes null when no icon is set (BuildingParameters.cs).
    //
    // The isBelt gate is load-bearing, not defensive: non-belt buildings
    // reuse `parameters` for unrelated config words (sorter stack size,
    // station slot config, splitter priority, ...), and those words are
    // frequently item ids themselves. Without the gate, an Interstellar
    // Logistics Station (itemId 2104) in
    // factory-endgame-distribution-hub.txt resolves its slot-config word
    // straight through tagIconName to a confidently wrong icon (e.g.
    // "lab", "tesla-coil") plus a bogus count of 1 -- exactly the failure
    // the five-band tag resolver exists to prevent. A wrong icon is worse
    // than no icon.
    const [tagId, tagCount] = inst.parameters;
    if (isBelt(inst.itemId) && tagId !== undefined && tagId > 0) {
      const tagIcon = catalog.tagIconName(tagId);
      const tagCell = tagIcon ? atlas.entries[tagIcon] : undefined;
      if (tagIcon && tagCell) {
        const position: [number, number, number] = [
          inst.position[0],
          inst.position[1] + inst.size[1] / 2 + 0.6,
          inst.position[2],
        ];
        icons.push({
          iconName: tagIcon,
          position,
          uv: [tagCell[0] / atlas.cols, tagCell[1] / atlas.rows],
          scale: BELT_ICON_SIZE,
        });
        // 0 is the unset value, and a negative count is a value the game
        // itself clamps to 0 for display (storage keeps the negative, so a
        // blueprint can carry one) -- neither is a number the player meant
        // to show, so neither gets a CountPlacement.
        if (tagCount !== undefined && tagCount > 0) {
          counts.push({ position: [position[0], position[1], position[2] + 0.9], value: tagCount });
        }
      }
      // An unresolvable tag draws nothing; SceneModel.unresolvedTagIds is what
      // reports it, so the gap is visible without duplicating the resolution
      // here.
    }
  }

  const instanceByIndex = new Map(model.instances.map((i) => [i.index, i]));

  // Inferred endpoint icons. A run whose contents the player already labelled
  // is left alone -- explicit tags win over the inference.
  for (const run of endpointIcons ? model.beltRuns : []) {
    if (run.hasExplicitTag || run.carried.length === 0) continue;

    // A Set, not an array: a single-belt run has belts[0] === tail, so when
    // both ends are free an array would hold the same index twice and draw
    // every carried icon twice at the identical position. Such runs are real
    // -- factory-quick-start-step-3-red-cube contains one.
    const ends = new Set<number>();
    if (run.freeInput && run.belts[0] !== undefined) ends.add(run.belts[0]);
    if (run.freeOutput) {
      const tail = run.belts[run.belts.length - 1];
      if (tail !== undefined) ends.add(tail);
    }

    // One icon per end, never a fan. `carried` is the graph's shortlist, and
    // on a lane the graph pinned it holds exactly one item; where it could
    // not, spreading every candidate across the lane spent a whole run's
    // width to say "unknown". The first candidate plus a "+N" badge says the
    // same thing in one icon's worth of space, and the info panel has the
    // full list for anyone who clicks.
    const [itemId, ...rest] = run.carried;
    if (itemId === undefined) continue;
    const iconName = catalog.item(itemId)?.iconName;
    const cell = iconName ? atlas.entries[iconName] : undefined;
    if (!iconName || !cell) continue;

    for (const endIndex of ends) {
      const inst = instanceByIndex.get(endIndex);
      if (!inst) continue;
      // Same placement convention as the per-building icons above: floats
      // just above the box top, resolved through the same atlas cell.
      const position: [number, number, number] = [
        inst.position[0],
        inst.position[1] + inst.size[1] / 2 + 0.6,
        inst.position[2],
      ];
      icons.push({
        iconName,
        position,
        uv: [cell[0] / atlas.cols, cell[1] / atlas.rows],
        scale: BELT_ICON_SIZE,
      });
      if (rest.length > 0) {
        counts.push({
          position: [position[0] + BELT_ICON_SIZE * 0.75, position[1], position[2]],
          value: rest.length,
          plus: true,
          scale: BADGE_GLYPH_SIZE,
        });
      }
    }
  }

  return { icons, counts };
}
