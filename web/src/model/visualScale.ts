/**
 * SlotConfig.selectSize is the game's selection (click) volume, which is
 * deliberately larger than the visible model. Drawing it raw makes belts --
 * which stack at 0.5 z-intervals with a 0.5-tall select box -- touch exactly,
 * destroying the stacking readability that is the whole point of rendering in 3D.
 *
 * So each category gets a visual multiplier applied to selectSize.
 */
const BELT: [number, number, number] = [0.64, 0.24, 0.64]; // 0.5 height -> 0.12
const SORTER: [number, number, number] = [0.5, 0.5, 0.5];
const DEFAULT: [number, number, number] = [0.9, 0.999, 0.9]; // slight shrink avoids z-fighting

export function visualScaleFor(itemId: number): [number, number, number] {
  if (itemId > 2000 && itemId < 2010) return BELT;
  if (itemId > 2010 && itemId < 2020) return SORTER;
  return DEFAULT;
}
