import { expect, test } from '@rstest/core';
import { render, screen } from '@testing-library/react';
import { BuildReportPanel } from '../../src/ui/BuildReport';
import type { Attempt } from '../../src/api/build';
import { anAttempt, anAttemptDetail, aResult } from '../support/build';

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
