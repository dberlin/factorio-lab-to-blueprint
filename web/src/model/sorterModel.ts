/**
 * A low-poly stand-in for the game's Sorter Mk.I: a boxy base at the pickup
 * end, a slim arm arching over, and a two-legged head at the drop end.
 *
 * The point of the shape is that direction reads without any marking -- base
 * at one end, head at the other -- and that the arm IS the connection between
 * the two ports. That is why a sorter needs no tie lines except where an end
 * does not actually sit on the thing it serves.
 *
 * Pure and renderer-free, like the rest of `model/` (architecture.test.ts).
 */
import { RIBBON_THICKNESS, type Vec3 } from './beltRibbons';

export const SORTER = {
  BASE_W: 0.42,
  BASE_H: 0.2,
  BASE_L: 0.42,
  /** The orange plate on the base's top face, which is what makes the pickup
      end recognisable at a glance in the game's own part. */
  ACCENT_W: 0.3,
  ACCENT_H: 0.05,
  LEG: 0.08,
  LEG_H: 0.24,
  LEG_SPREAD: 0.13,
  BAR_W: 0.34,
  BAR_H: 0.1,
  BAR_L: 0.16,
  ARM_W: 0.12,
  ARM_T: 0.09,
} as const;

const ARM_STEPS = 4;

export interface SorterParts {
  /** Unit direction in plan, pickup -> drop. */
  dir: Vec3;
  /** Box centres. Sizes come from `SORTER`. */
  base: Vec3;
  accent: Vec3;
  legs: [Vec3, Vec3];
  headBar: Vec3;
  /** Polyline for the arm, from the base's top face to the head's top face. */
  arm: Vec3[];
  /** Where the direction marking sits, just clear of the head's top face. */
  marking: Vec3;
  /** True when the two ends are stacked, so the arm would be degenerate. */
  stacked: boolean;
}

/**
 * `pickSupportY` and `dropSupportY` are the heights of the surfaces the two
 * ends stand on, not the endpoints themselves. A sorter's seated endpoint sits
 * at the foot of what it serves -- on a belt, that is *inside* the strip -- so
 * the parts are lifted to rest on the surface rather than sunk into it or
 * clipped off at it. An endpoint already above its support keeps its own
 * height.
 */
export function sorterParts(
  pick: Vec3,
  drop: Vec3,
  pickSupportY: number,
  dropSupportY: number,
): SorterParts {
  const dx = drop[0] - pick[0];
  const dz = drop[2] - pick[2];
  const span = Math.hypot(dx, dz);
  const stacked = span < 1e-4;
  const dir: Vec3 = stacked ? [0, 0, 1] : [dx / span, 0, dz / span];
  const across: Vec3 = [dir[2], 0, -dir[0]];

  const baseFoot = Math.max(pick[1], pickSupportY);
  const headFoot = Math.max(drop[1], dropSupportY);

  const base: Vec3 = [pick[0], baseFoot + SORTER.BASE_H / 2, pick[2]];
  const accent: Vec3 = [pick[0], baseFoot + SORTER.BASE_H + SORTER.ACCENT_H / 2, pick[2]];
  const legY = headFoot + SORTER.LEG_H / 2;
  const legs: [Vec3, Vec3] = [
    [drop[0] + across[0] * SORTER.LEG_SPREAD, legY, drop[2] + across[2] * SORTER.LEG_SPREAD],
    [drop[0] - across[0] * SORTER.LEG_SPREAD, legY, drop[2] - across[2] * SORTER.LEG_SPREAD],
  ];
  const barBottom = headFoot + SORTER.LEG_H;
  const headBar: Vec3 = [drop[0], barBottom + SORTER.BAR_H / 2, drop[2]];

  const from: Vec3 = [pick[0], baseFoot + SORTER.BASE_H + SORTER.ACCENT_H, pick[2]];
  const to: Vec3 = [drop[0], barBottom + SORTER.BAR_H, drop[2]];
  const lift = Math.max(0.22, Math.min(0.42, span * 0.3));
  const arm: Vec3[] = [];
  for (let k = 0; k <= ARM_STEPS; k++) {
    const t = k / ARM_STEPS;
    arm.push([
      from[0] + (to[0] - from[0]) * t,
      from[1] + (to[1] - from[1]) * t + Math.sin(Math.PI * t) * lift,
      from[2] + (to[2] - from[2]) * t,
    ]);
  }

  return {
    dir,
    base,
    accent,
    legs,
    headBar,
    arm,
    marking: [drop[0], barBottom + SORTER.BAR_H + 0.01, drop[2]],
    stacked,
  };
}

export interface SupportTarget {
  position: Vec3 | readonly [number, number, number];
  size: Vec3 | readonly [number, number, number];
  belt: boolean;
}

/**
 * The height a sorter end stands on. A belt end stands on the strip's top
 * surface -- the strip is drawn at the tile centre, so its surface is half a
 * thickness above that. Everything else (a machine face, a station slot) is
 * already at the height the game seated it at.
 */
export function supportTopY(target: SupportTarget | undefined, endY: number): number {
  if (!target || !target.belt) return endY;
  return target.position[1] + RIBBON_THICKNESS / 2;
}

/**
 * Whether an end already sits on the building it serves.
 *
 * The game seats `lpos`/`lpos2` onto the slot pose of the building at that end
 * (BlueprintUtils.RefreshBuildPreview), so in practice nearly every end is on
 * its port and needs no tie line drawn to it -- the arm is the connection. The
 * ends that are not are the interesting ones, and those are exactly the ones
 * that keep a tie.
 *
 * Vertical slack is generous because a sorter serving a tall machine meets it
 * at the foot while the machine's centre is metres up.
 */
export function isOnPort(
  end: Vec3,
  centre: Vec3 | readonly [number, number, number],
  size: Vec3 | readonly [number, number, number],
): boolean {
  const dx = Math.max(0, Math.abs(end[0] - centre[0]) - size[0] / 2);
  const dz = Math.max(0, Math.abs(end[2] - centre[2]) - size[2] / 2);
  const dy = Math.max(0, Math.abs(end[1] - centre[1]) - size[1] / 2);
  return Math.hypot(dx, dz) < 0.35 && dy < 0.7;
}
