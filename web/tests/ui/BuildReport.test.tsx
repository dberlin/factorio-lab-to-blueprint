import { expect, test } from '@rstest/core';
import { render, screen } from '@testing-library/react';
import { BuildReportPanel } from '../../src/ui/BuildReport';
import { aResult } from '../support/build';

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
