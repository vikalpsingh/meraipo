import { render, screen, within } from '@testing-library/react';
import { expect, it } from 'vitest';
import { IPOInterestTable } from '@/components/ipo-interest-table';
import type { Company } from '@/lib/types';

it.each([
  [null, 'neutral'],
  [0, 'neutral'],
  [-5, 'neutral'],
  [20, 'neutral'],
  [20.01, 'light-green'],
  [40, 'light-green'],
  [40.01, 'dark-green'],
  [100, 'dark-green'],
  [100.01, 'gold'],
])('highlights GMP %s using the strict threshold %s', (gmp, tone) => {
  const company: Partial<Company> = {
    id: 'color',
    slug: 'color',
    name: 'Color fixture',
    board: 'Mainboard',
    status: 'OPEN',
    price_low: 90,
    price_high: 100,
    gmp,
    gmp_quality: 'FRESH',
    gmp_timestamp: '2026-09-26T14:00:00Z',
  };
  render(<IPOInterestTable companies={[company as Company]} today="2026-09-27" />);
  const cell = within(screen.getAllByRole('row')[1]).getAllByRole('cell').at(-1);
  expect(cell).toHaveClass(`gmp-percent--${tone}`);
  expect(screen.getAllByRole('row')[1]).toHaveClass(`ipo-gmp--${tone}`);
});

it.each([
  [54, 405, '13.33%'],
  [14, 34, '41.18%'],
  [0, 100, '0%'],
  [-5, 100, '-5%'],
  [null, 100, '-NA-'],
  [14, null, '-NA-'],
  [null, null, '-NA-'],
  [14, 0, '-NA-'],
])('renders GMP % for premium %s and upper band %s', (gmp, high, expected) => {
  const company: Partial<Company> = {
    id: 'gmp-test',
    slug: 'gmp-test',
    name: 'GMP fixture',
    board: 'Mainboard',
    status: 'OPEN',
    open_date: '2026-09-24',
    close_date: '2026-09-28',
    price_low: 20,
    price_high: high,
    gmp,
    gmp_quality: 'FRESH',
    gmp_timestamp: '2026-09-26T14:00:00Z',
  };
  render(<IPOInterestTable companies={[company as Company]} today="2026-09-27" />);
  expect(screen.getByRole('columnheader', { name: 'GMP %' })).toBeInTheDocument();
  const row = screen.getAllByRole('row')[1];
  expect(within(row).getAllByRole('cell').at(-1)).toHaveTextContent(expected);
});
