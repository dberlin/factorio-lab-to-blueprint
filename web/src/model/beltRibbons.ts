/**
 * Geometry for drawing a belt run as one continuous strip, and for the small
 * parts that sit on it.
 *
 * Everything here is pure and renderer-free (see architecture.test.ts): it
 * emits plain number arrays that the scene layer hands to three.js. The shapes
 * it produces are the ribbon itself, the straight stretches along it, the
 * (number + arrow) blocks laid on those stretches, the arrow wedge, and the
 * oriented box the sorter parts are built from -- all through one triangle
 * emitter, so the winding rule below holds for every one of them.
 */
export type Vec3 = [number, number, number];

/** Narrower than the belt tile so parallel runs read as separate strips. */
export const RIBBON_WIDTH = 0.5;
export const RIBBON_THICKNESS = 0.14;
export const CORNER_RADIUS = 0.55;

/**
 * A number is sized to sit INSIDE its own strip. A label wider than the strip
 * it belongs to overlaps the runs either side of it as soon as several short
 * runs bundle together, which is the single worst legibility failure in a
 * dense blueprint.
 */
export const LABEL_HEIGHT = RIBBON_WIDTH * 0.86;
export const DIGIT_ADVANCE = LABEL_HEIGHT * 0.62;

export const ARROW_SIZE = RIBBON_WIDTH * 0.88;
/** Extent of the arrow wedge along travel, and the offset of that extent's
    midpoint from the glyph origin (the wedge is not symmetric about it). */
export const ARROW_LENGTH = ARROW_SIZE * 0.98;
/** Fraction of a wedge's size by which its extent's midpoint sits forward of
    its origin; multiply by the size actually used. */
export const WEDGE_MID_RATIO = 0.13;
export const ARROW_MID = ARROW_SIZE * WEDGE_MID_RATIO;

/** Space between two blocks, as a multiple of the block's own length. */
export const GAP_BLOCKS = 2;

const ARROW_TO_LABEL = 0.18;
const BLOCK_PADDING = 0.34;
/** Below this a run reads as a dash rather than a strip with a cadence. */
const MIN_BLOCK = 1.5;
/** Keeps a block clear of the turn or riser at either end of its stretch. */
const STRETCH_INSET = 0.2;

export function labelLength(digits: number): number {
  return digits * DIGIT_ADVANCE;
}

/**
 * One block is arrow + this run's own number + padding, measured in world
 * units. That is the whole point of the adaptive cadence: a run numbered 137
 * claims more room than one numbered 4, so the spacing comes out of the
 * content instead of a fixed belt count that is too dense on a trunk and too
 * sparse on a stub.
 */
export function blockLength(digits: number): number {
  const content = ARROW_LENGTH + (digits > 0 ? ARROW_TO_LABEL + labelLength(digits) : 0);
  return Math.max(content + BLOCK_PADDING, MIN_BLOCK);
}

/** Tile centres of a run, head to tail, skipping belts with no instance. */
export function runPolyline(
  belts: readonly number[],
  positions: ReadonlyMap<number, readonly [number, number, number]>,
): Vec3[] {
  const out: Vec3[] = [];
  for (const index of belts) {
    const p = positions.get(index);
    if (p) out.push([p[0], p[1], p[2]]);
  }
  return out;
}

/**
 * Grows a run by half a tile at each end.
 *
 * The polyline runs between tile CENTRES, so a strip drawn straight from it
 * stops half a tile short at both ends. Two consequences, both visible: a run
 * that merges into another leaves a gap at the junction instead of arriving
 * flush at the tile it feeds, and a one-belt run has no length at all and
 * would vanish. A single belt is extended along its own heading, which is the
 * only direction information it has.
 */
export function extendEnds(points: readonly Vec3[], heading?: number): Vec3[] {
  if (points.length === 0) return [];
  if (points.length === 1) {
    if (heading === undefined) return [];
    const p = points[0] as Vec3;
    const dir: Vec3 = [Math.sin(heading), 0, Math.cos(heading)];
    return [
      [p[0] - dir[0] * SINGLETON_HALF, p[1], p[2] - dir[2] * SINGLETON_HALF],
      [p[0] + dir[0] * SINGLETON_HALF, p[1], p[2] + dir[2] * SINGLETON_HALF],
    ];
  }
  const out = points.map(copy);
  const head = out[0] as Vec3;
  const afterHead = out[1] as Vec3;
  const tail = out[out.length - 1] as Vec3;
  const beforeTail = out[out.length - 2] as Vec3;
  out[0] = grow(head, afterHead);
  out[out.length - 1] = grow(tail, beforeTail);
  return out;
}

const SINGLETON_HALF = 0.45;
const MAX_END_PAD = 0.5;

/** Moves `from` away from `toward` by half their separation, capped. */
function grow(from: Vec3, toward: Vec3): Vec3 {
  const d = sub(from, toward);
  const l = length(d);
  if (l < 1e-6) return from;
  const pad = Math.min(MAX_END_PAD, l / 2);
  return add(from, scale(d, pad / l));
}

/**
 * The direction arrow: a low triangular wedge that sits proud of the strip.
 *
 * Raised rather than flat so it still reads when the camera is low and a flat
 * glyph would be edge-on, and open underneath because it is always drawn
 * sitting on a strip.
 */
export function arrowWedge(size: number = ARROW_SIZE): RibbonMesh {
  const mesh: RibbonMesh = { positions: [], normals: [] };
  const h = size * 0.25;
  const apex: Vec3 = [0, h, 0.62 * size];
  const left: Vec3 = [-0.46 * size, h, -0.36 * size];
  const right: Vec3 = [0.46 * size, h, -0.36 * size];
  const apex0: Vec3 = [0, 0, 0.62 * size];
  const left0: Vec3 = [-0.46 * size, 0, -0.36 * size];
  const right0: Vec3 = [0.46 * size, 0, -0.36 * size];
  pushTri(mesh, apex, left, right, UP);
  pushQuad(mesh, apex, left, left0, apex0, normalize([-0.62, 0, 0.35]));
  pushQuad(mesh, apex, right, right0, apex0, normalize([0.62, 0, 0.35]));
  pushQuad(mesh, left, right, right0, left0, [0, 0, -1]);
  return mesh;
}

/**
 * A box sized (across travel, up, along travel) and turned to face `dir`.
 *
 * The sorter's base, legs and head bar are built from this rather than from
 * three.js BoxGeometry so they go through the same winding-checked emitter as
 * everything else and can be merged into one buffer without a matrix each.
 */
export function orientedBox(
  centre: Vec3,
  across: number,
  up: number,
  along: number,
  dir: Vec3,
): RibbonMesh {
  const mesh: RibbonMesh = { positions: [], normals: [] };
  const f: Vec3 = normalize([dir[0], 0, dir[2]]);
  const s: Vec3 = [f[2], 0, -f[0]];
  const corner = (sx: number, sy: number, sz: number): Vec3 => [
    centre[0] + s[0] * (across / 2) * sx + f[0] * (along / 2) * sz,
    centre[1] + (up / 2) * sy,
    centre[2] + s[2] * (across / 2) * sx + f[2] * (along / 2) * sz,
  ];
  const [a, b, c, d] = [corner(-1, 1, 1), corner(1, 1, 1), corner(1, 1, -1), corner(-1, 1, -1)];
  const [e, g, h, i] = [corner(-1, -1, 1), corner(1, -1, 1), corner(1, -1, -1), corner(-1, -1, -1)];
  pushQuad(mesh, a, b, c, d, UP);
  pushQuad(mesh, e, g, h, i, DOWN);
  pushQuad(mesh, a, b, g, e, f);
  pushQuad(mesh, d, c, h, i, negate(f));
  pushQuad(mesh, b, c, h, g, negate(s));
  pushQuad(mesh, a, d, i, e, s);
  return mesh;
}

/** Appends one mesh's triangles onto another. */
export function appendMesh(target: RibbonMesh, source: RibbonMesh): void {
  for (let i = 0; i < source.positions.length; i++) {
    target.positions.push(source.positions[i] as number);
    target.normals.push(source.normals[i] as number);
  }
}

/**
 * Turns each altitude change into a short, very steep riser instead of a long
 * ramp, so a level change reads as a step up rather than a slope.
 *
 * The riser leans along travel by `RISER_LEAN` and is never exactly vertical.
 * A strictly vertical segment makes the strip's top and bottom faces coplanar
 * -- they occupy the same plane, offset only in Y -- and they z-fight into a
 * flickering fringe. The lean is far too small to see and removes the
 * degeneracy completely.
 */
const RISER_LEAN = 0.05;

export function steppedClimb(points: readonly Vec3[]): Vec3[] {
  if (points.length < 2) return points.map(copy);
  const out: Vec3[] = [copy(points[0] as Vec3)];
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1] as Vec3;
    const b = points[i] as Vec3;
    if (Math.abs(b[1] - a[1]) > 0.02) {
      const mx = (a[0] + b[0]) / 2;
      const mz = (a[2] + b[2]) / 2;
      const d = horizontalDir(a, b);
      const ox = d ? d[0] * RISER_LEAN : 0;
      const oz = d ? d[2] * RISER_LEAN : 0;
      out.push([mx - ox, a[1], mz - oz]);
      out.push([mx + ox, b[1], mz + oz]);
    }
    out.push(copy(b));
  }
  return out;
}

/** Replaces each corner with a short arc, so turns read as bends rather than
    as two boxes meeting at an edge. Straight polylines come back untouched. */
export function roundCorners(points: readonly Vec3[], radius = CORNER_RADIUS): Vec3[] {
  if (points.length < 3 || radius <= 0) return points.map(copy);
  const out: Vec3[] = [copy(points[0] as Vec3)];
  for (let i = 1; i < points.length - 1; i++) {
    const a = points[i - 1] as Vec3;
    const b = points[i] as Vec3;
    const c = points[i + 1] as Vec3;
    const d1 = sub(b, a);
    const d2 = sub(c, b);
    const l1 = length(d1);
    const l2 = length(d2);
    if (l1 < 1e-4 || l2 < 1e-4) {
      out.push(copy(b));
      continue;
    }
    const u1 = scale(d1, 1 / l1);
    const u2 = scale(d2, 1 / l2);
    if (angleBetween(u1, u2) < 0.25) {
      out.push(copy(b));
      continue;
    }
    const r = Math.min(radius, l1 * 0.45, l2 * 0.45);
    const p1 = add(b, scale(u1, -r));
    const p2 = add(b, scale(u2, r));
    for (let k = 0; k <= ARC_STEPS; k++) {
      const t = k / ARC_STEPS;
      const s = 1 - t;
      out.push([
        s * s * p1[0] + 2 * s * t * b[0] + t * t * p2[0],
        s * s * p1[1] + 2 * s * t * b[1] + t * t * p2[1],
        s * s * p1[2] + 2 * s * t * b[2] + t * t * p2[2],
      ]);
    }
  }
  out.push(copy(points[points.length - 1] as Vec3));
  return out;
}

const ARC_STEPS = 4;

export interface RibbonMesh {
  positions: number[];
  normals: number[];
}

/**
 * A closed strip: top, bottom, both side walls and both end caps, mitred at
 * every vertex so a turn is a single continuous surface rather than two boxes
 * overlapping.
 *
 * Triangles are emitted non-indexed with an explicit normal each. `pushTri`
 * reverses a triangle whose winding disagrees with that normal: the materials
 * are DoubleSide and three.js flips the shading normal on a back-facing
 * fragment, so a top face wound the wrong way is lit as though the sun were
 * under the floor. That bug is invisible in a wireframe and obvious the moment
 * anything is lit -- it made every strip read as unlit dark grey.
 */
export function ribbonMesh(
  points: readonly Vec3[],
  width: number = RIBBON_WIDTH,
  thickness: number = RIBBON_THICKNESS,
): RibbonMesh {
  const mesh: RibbonMesh = { positions: [], normals: [] };
  if (points.length < 2) return mesh;

  const offsets = mitreOffsets(points, width / 2);
  const half = thickness / 2;
  const lt = (i: number): Vec3 => shift(points[i] as Vec3, offsets[i] as Vec3, half);
  const rt = (i: number): Vec3 => shift(points[i] as Vec3, negate(offsets[i] as Vec3), half);
  const lb = (i: number): Vec3 => shift(points[i] as Vec3, offsets[i] as Vec3, -half);
  const rb = (i: number): Vec3 => shift(points[i] as Vec3, negate(offsets[i] as Vec3), -half);

  for (let i = 0; i < points.length - 1; i++) {
    const outward = normalize(offsets[i] as Vec3);
    pushQuad(mesh, lt(i), lt(i + 1), rt(i + 1), rt(i), UP);
    pushQuad(mesh, lb(i), lb(i + 1), rb(i + 1), rb(i), DOWN);
    pushQuad(mesh, lt(i), lt(i + 1), lb(i + 1), lb(i), outward);
    pushQuad(mesh, rt(i), rt(i + 1), rb(i + 1), rb(i), negate(outward));
  }

  const last = points.length - 1;
  const head = horizontalDir(points[0] as Vec3, points[1] as Vec3) ?? [0, 0, 1];
  const tail = horizontalDir(points[last - 1] as Vec3, points[last] as Vec3) ?? head;
  pushQuad(mesh, lt(0), rt(0), rb(0), lb(0), negate(head));
  pushQuad(mesh, lt(last), rt(last), rb(last), lb(last), tail);
  return mesh;
}

/**
 * Half-width offset at each vertex, mitred so the strip keeps a constant
 * width through a turn. The `0.4` clamp bounds the mitre on a hairpin, where
 * the exact mitre length goes to infinity.
 */
export function mitreOffsets(points: readonly Vec3[], half: number): Vec3[] {
  const out: Vec3[] = [];
  let previous: Vec3 = [1, 0, 0];
  for (let i = 0; i < points.length; i++) {
    const before = i > 0 ? horizontalDir(points[i - 1] as Vec3, points[i] as Vec3) : null;
    const after =
      i < points.length - 1 ? horizontalDir(points[i] as Vec3, points[i + 1] as Vec3) : null;
    let m: Vec3;
    if (before && after) {
      const sum = add(perpendicular(before), perpendicular(after));
      if (length(sum) < 1e-8) {
        m = perpendicular(after);
      } else {
        const unit = normalize(sum);
        m = scale(unit, 1 / Math.max(0.4, dot(unit, perpendicular(after))));
      }
    } else if (before || after) {
      m = perpendicular((before ?? after) as Vec3);
    } else {
      m = previous;
    }
    previous = m;
    out.push(scale(m, half));
  }
  return out;
}

export interface Stretch {
  /** Distance along the polyline where this stretch starts and ends. */
  start: number;
  end: number;
  dir: Vec3;
  /** World position at `start`. */
  at: Vec3;
}

/**
 * Maximal stretches that are straight in plan AND flat.
 *
 * Both conditions matter: an arrow or a number laid across a turn is bent, and
 * one laid on a riser is stood on its side. Segments that turn or climb belong
 * to no stretch at all, so nothing can be placed on them.
 */
export function straightStretches(points: readonly Vec3[]): Stretch[] {
  const out: Stretch[] = [];
  let current: Stretch | null = null;
  let travelled = 0;
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i] as Vec3;
    const b = points[i + 1] as Vec3;
    const step = length(sub(b, a));
    const dir = horizontalDir(a, b);
    const flat = Math.abs(b[1] - a[1]) < 0.02;
    if (!dir || !flat) {
      current = null;
      travelled += step;
      continue;
    }
    if (current && dot(current.dir, dir) > 0.995) {
      current.end = travelled + step;
    } else {
      current = { start: travelled, end: travelled + step, dir, at: copy(a) };
      out.push(current);
    }
    travelled += step;
  }
  return out;
}

export interface Block {
  /** Where the arrow glyph's origin goes, and which way it points. */
  arrow: Vec3;
  /** Centre of the run number, or null when the run only had room for an arrow. */
  label: Vec3 | null;
  dir: Vec3;
}

/**
 * Lays (number + arrow) blocks along a run.
 *
 * Travel order inside a block is number first, arrow last: the arrow leads and
 * the number trails it. Blocks are separated by `gapBlocks` times their own
 * length, and a block is only ever placed where it fits entirely within one
 * straight, flat stretch -- if it does not fit, it waits for the next one
 * rather than bending around the turn.
 *
 * A run with no room for a whole block still gets a bare arrow if an arrow
 * alone fits, because a strip with no direction on it at all is worse than a
 * strip with no number on it.
 */
export function layoutBlocks(
  points: readonly Vec3[],
  digits: number,
  options: { gapBlocks?: number } = {},
): Block[] {
  const stretches = straightStretches(points);
  const block = blockLength(digits);
  const gap = block * (options.gapBlocks ?? GAP_BLOCKS);
  const labelWidth = digits > 0 ? labelLength(digits) : 0;

  const out: Block[] = [];
  let lastEnd = -Infinity;
  for (const stretch of stretches) {
    const limit = stretch.end - STRETCH_INSET;
    let cursor = stretch.start + STRETCH_INSET;
    while (cursor + block <= limit) {
      const at = Math.max(cursor, lastEnd + gap);
      if (at + block > limit) break;
      out.push(blockAt(stretch, at, block, labelWidth));
      lastEnd = at + block;
      cursor = at + block;
    }
  }

  if (out.length === 0) {
    for (const stretch of stretches) {
      if (stretch.end - stretch.start >= ARROW_LENGTH + STRETCH_INSET) {
        const at = (stretch.start + stretch.end) / 2 - ARROW_LENGTH / 2;
        const only = blockAt(stretch, at, ARROW_LENGTH, 0);
        out.push({ arrow: only.arrow, label: null, dir: only.dir });
        break;
      }
    }
  }
  return out;
}

function blockAt(stretch: Stretch, at: number, block: number, labelWidth: number): Block {
  const content = labelWidth > 0 ? labelWidth + ARROW_TO_LABEL + ARROW_LENGTH : ARROW_LENGTH;
  const lead = at + (block - content) / 2;
  const along = (offset: number): Vec3 => {
    const d = offset - stretch.start;
    return [
      stretch.at[0] + stretch.dir[0] * d,
      stretch.at[1] + stretch.dir[1] * d,
      stretch.at[2] + stretch.dir[2] * d,
    ];
  };
  return {
    label: labelWidth > 0 ? along(lead + labelWidth / 2) : null,
    arrow: along(lead + content - ARROW_LENGTH / 2),
    dir: copy(stretch.dir),
  };
}

/**
 * A run's colour, from a golden-angle walk around the hue circle so adjacent
 * run indices land far apart and the same run always gets the same colour.
 */
export function runColor(index: number): number {
  return hslToHex(((index * 137.508) % 360) / 360, 0.62, 0.56);
}

/**
 * Whether the arrow on a given ribbon colour should be drawn dark.
 *
 * A fixed light glyph is crisp on a navy run and invisible on a pale yellow
 * one. Perceived brightness (sRGB-weighted, deliberately not linearised --
 * this is a legibility threshold, not a colour-science calculation) decides it
 * per run.
 */
export function arrowIsDark(color: number): boolean {
  const r = (color >> 16) & 0xff;
  const g = (color >> 8) & 0xff;
  const b = color & 0xff;
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 > 0.45;
}

function hslToHex(h: number, s: number, l: number): number {
  const f = (n: number): number => {
    const k = (n + h * 12) % 12;
    const a = s * Math.min(l, 1 - l);
    const v = l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
    return Math.round(Math.max(0, Math.min(1, v)) * 255);
  };
  return (f(0) << 16) | (f(8) << 8) | f(4);
}

// ---------------------------------------------------------------- vectors

const UP: Vec3 = [0, 1, 0];
const DOWN: Vec3 = [0, -1, 0];

function copy(v: Vec3): Vec3 {
  return [v[0], v[1], v[2]];
}
function add(a: Vec3, b: Vec3): Vec3 {
  return [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
}
function sub(a: Vec3, b: Vec3): Vec3 {
  return [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
}
function scale(v: Vec3, k: number): Vec3 {
  return [v[0] * k, v[1] * k, v[2] * k];
}
function negate(v: Vec3): Vec3 {
  return [-v[0], -v[1], -v[2]];
}
function dot(a: Vec3, b: Vec3): number {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}
function length(v: Vec3): number {
  return Math.hypot(v[0], v[1], v[2]);
}
function normalize(v: Vec3): Vec3 {
  const l = length(v);
  return l < 1e-12 ? [0, 0, 1] : scale(v, 1 / l);
}
function angleBetween(a: Vec3, b: Vec3): number {
  return Math.acos(Math.max(-1, Math.min(1, dot(a, b))));
}
/** Unit direction in plan; null when the two points are vertically stacked. */
function horizontalDir(a: Vec3, b: Vec3): Vec3 | null {
  const dx = b[0] - a[0];
  const dz = b[2] - a[2];
  const l = Math.hypot(dx, dz);
  return l < 1e-6 ? null : [dx / l, 0, dz / l];
}
function perpendicular(d: Vec3): Vec3 {
  return [d[2], 0, -d[0]];
}
function shift(p: Vec3, offset: Vec3, dy: number): Vec3 {
  return [p[0] + offset[0], p[1] + dy, p[2] + offset[2]];
}

function pushTri(mesh: RibbonMesh, a: Vec3, b: Vec3, c: Vec3, n: Vec3): void {
  const u = sub(b, a);
  const v = sub(c, a);
  const g: Vec3 = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
  const [first, second] = dot(g, n) < 0 ? [c, b] : [b, c];
  mesh.positions.push(
    a[0],
    a[1],
    a[2],
    first[0],
    first[1],
    first[2],
    second[0],
    second[1],
    second[2],
  );
  for (let i = 0; i < 3; i++) mesh.normals.push(n[0], n[1], n[2]);
}

function pushQuad(mesh: RibbonMesh, a: Vec3, b: Vec3, c: Vec3, d: Vec3, n: Vec3): void {
  pushTri(mesh, a, b, c, n);
  pushTri(mesh, a, c, d, n);
}
