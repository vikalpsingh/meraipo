import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { IPOInterestTable } from '@/components/ipo-interest-table';
import type { Company } from '@/lib/types';
it('renders twelve issues without truncation and retains deadline labels and missing data', () => {
  const companies = Array.from(
    { length: 12 },
    (_, i) =>
      ({
        id: String(i),
        name: `Company ${i + 1}`,
        slug: `company-${i}`,
        status: 'OPEN',
        board: 'Mainboard',
        open_date: '2026-09-18',
        close_date: i === 0 ? '2026-09-21' : '2026-09-22',
        gmp: null,
        price_low: null,
        price_high: null,
      }) as Company,
  );
  render(<IPOInterestTable companies={companies} today="2026-09-21" />);
  expect(screen.getAllByRole('row')).toHaveLength(13);
  expect(screen.getByRole('button', { name: 'Company 12' })).toBeInTheDocument();
  expect(screen.getByText('Closing today')).toBeInTheDocument();
  expect(screen.getAllByText('Open', { exact: true })).toHaveLength(11);
  expect(screen.getAllByText('GMP unavailable')).toHaveLength(12);
});

