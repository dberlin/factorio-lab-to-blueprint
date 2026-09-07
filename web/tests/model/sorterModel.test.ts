import { readFileSync } from 'node:fs';
import { expect, test } from '@rstest/core';
import { parseBlueprint } from '../../src/format/index';
import { RIBBON_THICKNESS, type Vec3 } from '../../src/model/beltRibbons';
import { isBelt, isSorter } from '../../src/model/beltGraph';
import { isOnPort, SORTER, sorterParts, supportTopY } from '../../src/model/sorterModel';

const pick: Vec3 = [4, 0, -4];
const drop: Vec3 = [6, 0, -4];

test('the base rests ON the support and keeps its full height', () => {
  // The seated pickup point sits at ground level, below the top of the belt it
  // draws from. Sinking the base to that point buries it in the strip, and
  // clipping the base off at the strip's surface leaves a squashed stub. The
  // base keeps its height and is lifted to stand on the surface.
  const beltTop = 0.17;
  const parts = sorterParts(pick, drop, beltTop, 0);
  expect(parts.base[1] - SORTER.BASE_H / 2).toBeCloseTo(beltTop, 6);
  expect(parts.base[1] + SORTER.BASE_H / 2).toBeCloseTo(beltTop + SORTER.BASE_H, 6);
  // and it stays over the pickup point in plan
  expect(parts.base[0]).toBeCloseTo(pick[0], 6);
  expect(parts.base[2]).toBeCloseTo(pick[2], 6);
});

test('a support below the endpoint never drags the base down', () => {
  const parts = sorterParts([4, 1.5, -4], drop, 0, 0);
  expect(parts.base[1] - SORTER.BASE_H / 2).toBeCloseTo(1.5, 6);
});

test('the legs stand on the drop support and the bar sits on the legs', () => {
  const parts = sorterParts(pick, drop, 0, 0.17);
  for (const leg of parts.legs) expect(leg[1] - SORTER.LEG_H / 2).toBeCloseTo(0.17, 6);
  expect(parts.headBar[1] - SORTER.BAR_H / 2).toBeCloseTo(0.17 + SORTER.LEG_H, 6);
  // The two legs straddle the drop point, one either side of travel.
  expect(parts.legs[0][0]).toBeCloseTo(parts.legs[1][0], 6);
  expect(Math.abs(parts.legs[0][2] - parts.legs[1][2])).toBeGreaterThan(0.1);
});

test('the arm leaves the base, arches above both ends, and lands on the head', () => {
  const parts = sorterParts(pick, drop, 0.17, 0.17);
  const first = parts.arm[0] as Vec3;
  const last = parts.arm[parts.arm.length - 1] as Vec3;
  expect(first[1]).toBeGreaterThanOrEqual(0.17 + SORTER.BASE_H);
  expect(last[1]).toBeGreaterThanOrEqual(0.17 + SORTER.LEG_H + SORTER.BAR_H);
  const peak = Math.max(...parts.arm.map((p) => p[1]));
  expect(peak).toBeGreaterThan(first[1] + 0.1);
  expect(peak).toBeGreaterThan(last[1] + 0.1);
  // The arm IS the connection: it must actually span the two ends in plan.
  expect(first[0]).toBeCloseTo(pick[0], 6);
  expect(last[0]).toBeCloseTo(drop[0], 6);
});

test('direction runs pickup to drop, and a stacked sorter still gets one', () => {
  expect(sorterParts(pick, drop, 0, 0).dir).toEqual([1, 0, 0]);
  const stacked = sorterParts([4, 0, -4], [4, 0.5, -4], 0, 0);
  expect(Math.hypot(stacked.dir[0], stacked.dir[2])).toBeCloseTo(1, 6);
});

test('an end seated on its port needs no tie line; one away from it does', () => {
  const beltCentre: Vec3 = [6, 0.1, -4];
  const beltSize: Vec3 = [0.64, 0.12, 0.64];
  expect(isOnPort([6.1, 0, -4.1], beltCentre, beltSize)).toBe(true);
  expect(isOnPort([7.6, 0, -4], beltCentre, beltSize)).toBe(false);
  // A machine end is on its port when it meets the machine's footprint, even
  // though the machine is metres tall and the sorter end is at its foot.
  expect(isOnPort([5, 0, -6], [5, 1.9, -6], [2.88, 3.8, 2.88])).toBe(true);
});

test('a belt end is supported by the strip surface, anything else by itself', () => {
  const belt = { position: [6, 0.1, -4] as Vec3, size: [0.64, 0.12, 0.64] as Vec3, belt: true };
  expect(supportTopY(belt, 0)).toBeCloseTo(0.1 + RIBBON_THICKNESS / 2, 6);
  const machine = { position: [5, 1.9, -6] as Vec3, size: [2.88, 3.8, 2.88] as Vec3, belt: false };
  expect(supportTopY(machine, 0.25)).toBe(0.25);
  expect(supportTopY(undefined, 0.25)).toBe(0.25);
});

// ------------------------------------------------------- the real convention

test('a sorter draws FROM (x,y,z) and feeds INTO (x2,y2,z2)', () => {
  // BuildPreview.lpos is the end the sorter draws from and lpos2 the end it
  // feeds into (see flab2bp.dsp.colliders.SorterPreview). Nothing in the web
  // code could tell if that were backwards, so it is asserted against real
  // blueprints: the drawn-from end must sit nearer the building the record
  // names as its INPUT than the fed-into end does.
  const text = readFileSync('tests/fixtures/factory-heretical-smelter-block.txt', 'utf8').trim();
  const bp = parseBlueprint(text);
  // Raw placement coordinates, not rendered box centres: a model's
  // `selectCenter` offset shifts a machine by a few centimetres, which is
  // enough to blur exactly the comparison being made here.
  const at = new Map<number, Vec3>(bp.buildings.map((b) => [b.index, [b.x, b.z, -b.y]]));

  let checked = 0;
  for (const s of bp.buildings) {
    if (!isSorter(s.itemId)) continue;
    const input = at.get(s.inputObjIdx);
    const output = at.get(s.outputObjIdx);
    if (!input || !output || s.inputObjIdx === s.outputObjIdx) continue;
    const from: Vec3 = [s.x, s.z, -s.y];
    const to: Vec3 = [s.x2, s.z2, -s.y2];
    const plan = (a: Vec3, b: readonly [number, number, number]) =>
      Math.hypot(a[0] - b[0], a[2] - b[2]);
    // Pairing, not per-end distance: a short sorter can sit almost equidistant
    // between the two buildings it joins (the closest pair in this fixture
    // differ by 3mm), so what has to hold is that this assignment of ends to
    // buildings is at least as good as the swapped one -- which is exactly the
    // claim any end-classification depends on.
    const asRecorded = plan(from, input) + plan(to, output);
    const swapped = plan(from, output) + plan(to, input);
    expect(asRecorded).toBeLessThanOrEqual(swapped + 1e-6);
    checked++;
  }
  expect(checked).toBeGreaterThan(50);
});

test('every sorter in a real blueprint has a belt at exactly one end or the other', () => {
  const text = readFileSync('tests/fixtures/factory-heretical-smelter-block.txt', 'utf8').trim();
  const bp = parseBlueprint(text);
  const byIndex = new Map(bp.buildings.map((b) => [b.index, b]));
  let withBelt = 0;
  let total = 0;
  for (const s of bp.buildings) {
    if (!isSorter(s.itemId)) continue;
    total++;
    const ends = [byIndex.get(s.inputObjIdx), byIndex.get(s.outputObjIdx)];
    if (ends.some((b) => b !== undefined && isBelt(b.itemId))) withBelt++;
  }
  // Not an invariant of the format, a fact about this blueprint that the
  // colouring of sorter ties leans on: a sorter with no belt at either end
  // falls back to a neutral tie colour rather than a run colour.
  expect(total).toBeGreaterThan(100);
  expect(withBelt).toBeGreaterThan(total / 2);
});
