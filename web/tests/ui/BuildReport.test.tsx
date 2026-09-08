import { afterEach, expect, test } from '@rstest/core';
import { render, screen, within } from '@testing-library/react';
import { BuildReportPanel } from '../../src/ui/BuildReport';
import type { Attempt } from '../../src/api/build';
import { anAttempt, anAttemptDetail, aResult } from '../support/build';
import { pollBuild } from '../../src/api/build';
import { aJob, restoreFetch, serving } from '../support/build';

afterEach(restoreFetch);

test('decoded winner and losing attempt retain their own priming and entry-lane instructions', async () => {
  const seed = {
    seed_items: 7,
    recipe: 'winner-loop',
    machines: 2,
    head: { x: 3, y: 5, z: '1/2' },
  };
  const losingSeed = {
    seed_items: 11,
    recipe: 'losing-loop',
    machines: 4,
    head: { x: -9, y: 8, z: '3/2' },
  };
  const result = aResult();
  const loser = {
    ...anAttempt({ candidate: 'all-products', chosen: false }),
    detail: {
      ...anAttemptDetail(),
      self_loop_seeds: { hydrogen: { ...losingSeed, recipes: [losingSeed] } },
      belt_tiers: {
        ...result.belt_tiers,
        entry_lanes: [{ item: 'iron-ore', lanes: 3, lanes_needed: 2 }],
      },
    },
  };
  serving({
    body: aJob({
      result: {
        ...result,
        self_loop_seeds: { hydrogen: { ...seed, recipes: [seed] } },
        belt_tiers: {
          ...result.belt_tiers,
          entry_lanes: [{ item: 'iron-ore', lanes: 2, lanes_needed: 1 }],
        },
        attempts: [loser],
      },
    }),
  });
  const decoded = (await pollBuild('facts')).result!;
  const view = render(
    <BuildReportPanel result={decoded} selectedAttempt={null} onSelectAttempt={() => {}} />,
  );
  const prime = () => screen.getByRole('region', { name: 'PRIME ONCE' });
  expect(prime()).toHaveTextContent('hydrogen');
  expect(prime()).toHaveTextContent('7');
  expect(prime()).toHaveTextContent('winner-loop');
  expect(prime()).toHaveTextContent('2 machines');
  expect(prime()).toHaveTextContent('(3, 5, 1/2)');
  expect(screen.getByText('Entry lanes').nextElementSibling).toHaveTextContent(
    'iron-ore: 2 / 1 needed',
  );
  expect(screen.getByText('Belt in').nextElementSibling).not.toHaveTextContent('hydrogen');
  view.rerender(
    <BuildReportPanel
      result={decoded}
      selectedAttempt={decoded.attempts[0]!}
      onSelectAttempt={() => {}}
    />,
  );
  expect(prime()).toHaveTextContent('11');
  expect(prime()).toHaveTextContent('losing-loop');
  expect(prime()).toHaveTextContent('4 machines');
  expect(prime()).toHaveTextContent('(-9, 8, 3/2)');
  expect(within(prime()).queryByText(/winner-loop/)).toBeNull();
  expect(screen.getByText('Entry lanes').nextElementSibling).toHaveTextContent(
    'iron-ore: 3 / 2 needed',
  );
  view.rerender(
    <BuildReportPanel result={aResult()} selectedAttempt={null} onSelectAttempt={() => {}} />,
  );
  expect(screen.queryByRole('region', { name: 'PRIME ONCE' })).toBeNull();
});

test('names the selected power building in the report', () => {
  render(
    <BuildReportPanel
      result={aResult({ power_building: 'Satellite Substation' })}
      selectedAttempt={null}
      onSelectAttempt={() => {}}
    />,
  );
  expect(screen.getByText('Power').nextElementSibling).toHaveTextContent('Satellite Substation');
});

test.each([
  [160, [160]],
  [160, [160, 200]],
  [120, [120, 160, 200]],
] as const)('renders literal frame evidence for %s / %s', (primaryBand, certifiedBands) => {
  render(
    <BuildReportPanel
      result={aResult({
        primary_band: primaryBand,
        certified_bands: [...certifiedBands],
      })}
      selectedAttempt={null}
      onSelectAttempt={() => {}}
    />,
  );

  expect(screen.getByText('primary_band').nextElementSibling).toHaveTextContent(
    String(primaryBand),
  );
  expect(screen.getByText('certified_bands').nextElementSibling).toHaveTextContent(
    certifiedBands.join(', '),
  );
});

test('the report describes the selected candidate, not just the winner', () => {
  const result = aResult();
  const alternative: Attempt = anAttempt({
    candidate: 'all-products',
    chosen: false,
    area: 640,
    detail: anAttemptDetail({
      machines: 13,
      buildings: 51,
      primary_band: 200,
      certified_bands: [200],
      title: 'electromagnetic-matrix 60/min (all products)',
      external_inputs: {
        'magnetic-coil': { exact: '5/6', per_minute: 50 },
        'proliferator-mk-iii': { exact: '1', per_minute: 60 },
      },
      input_markers: 2,
    }),
  });

  render(
    <BuildReportPanel result={result} selectedAttempt={alternative} onSelectAttempt={() => {}} />,
  );

  expect(screen.getByTestId('report-title')).toHaveTextContent('(all products)');
  expect(screen.getByText('Showing').nextElementSibling).toHaveTextContent(
    'freeform / all-products',
  );
  expect(screen.getByText('Machines').nextElementSibling).toHaveTextContent('13');
  expect(screen.getByText('Area').nextElementSibling).toHaveTextContent('640 tiles');
  expect(screen.getByText('primary_band').nextElementSibling).toHaveTextContent('200');
  expect(screen.getByText('certified_bands').nextElementSibling).toHaveTextContent('200');
  expect(screen.getByText('Buildings').nextElementSibling).toHaveTextContent('51');
  expect(screen.getByText('Belt in').nextElementSibling).toHaveTextContent(
    'magnetic-coil, proliferator-mk-iii (2 marked with icons)',
  );
});

test('machine moves follow the selected attempt rather than the winner', () => {
  const alternative = anAttempt({
    chosen: false,
    detail: anAttemptDetail({
      machine_rank: 'up-to',
      machine_moves: [
        {
          recipe_id: 'iron-ingot',
          from_machine: 'plane-smelter',
          to_machine: 'arc-smelter',
          count_before: 2,
          count_after: 2,
        },
      ],
    }),
  });
  render(
    <BuildReportPanel
      result={aResult()}
      selectedAttempt={alternative}
      onSelectAttempt={() => {}}
    />,
  );

  const ranking = screen.getByText('Machine ranking').nextElementSibling;
  expect(ranking).toHaveTextContent('Up to');
  expect(ranking).toHaveTextContent('iron-ingot');
  expect(ranking).toHaveTextContent('plane-smelter');
  expect(ranking).toHaveTextContent('arc-smelter');
});
