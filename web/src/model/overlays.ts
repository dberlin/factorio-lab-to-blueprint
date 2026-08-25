import { isBelt } from './beltGraph';
import type { Catalog } from './catalog';
import type { SceneModel } from './layout';
import type { Atlas } from './schemas';

export interface IconPlacement {
  position: [number, number, number];
  iconName: string;
  uv: [number, number];
}

export interface CountPlacement {
  position: [number, number, number];
  value: number;
}

export interface Overlays {
  icons: IconPlacement[];
  counts: CountPlacement[];
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
export function buildOverlays(model: SceneModel, catalog: Catalog, atlas: Atlas): Overlays {
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
  for (const run of model.beltRuns) {
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

    for (const endIndex of ends) {
      const inst = instanceByIndex.get(endIndex);
      if (!inst) continue;
      run.carried.forEach((itemId, slot) => {
        const iconName = catalog.item(itemId)?.iconName;
        const cell = iconName ? atlas.entries[iconName] : undefined;
        if (!iconName || !cell) return;
        // Fan multiple items apart so they do not stack on one another.
        const spread = (slot - (run.carried.length - 1) / 2) * 1.2;
        // Same placement convention as the per-building icons above: floats
        // just above the box top, resolved through the same atlas cell.
        icons.push({
          iconName,
          position: [
            inst.position[0] + spread,
            inst.position[1] + inst.size[1] / 2 + 0.6,
            inst.position[2],
          ],
          uv: [cell[0] / atlas.cols, cell[1] / atlas.rows],
        });
      });
    }
  }

  return { icons, counts };
}
