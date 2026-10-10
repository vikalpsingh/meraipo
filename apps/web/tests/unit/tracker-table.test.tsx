import { render, screen, within } from '@testing-library/react';
import { expect, it } from 'vitest';
import { TrackerTable } from '@/components/tracker-table';
import type { Company } from '@/lib/types';

const company = {
  id: 'test',
  slug: 'test',
  name: 'Example',
  board: 'SME',
  issue_size: 0,
  price_high: 100,
  issue_price: 80,
  cmp: 150,
  return_ipo: 50,
  listing_price: 120,
  listing_gain: 20,
  listing_date: '2026-10-01',
  listing_price_date: '2026-10-01',
  listing_price_exchange: 'NSE',
  latest: { label: 'Q1 FY2027', revenue: 0, pat: 12, eps: 1.2 },
  trend: { state: 'INSUFFICIENT_DATA' },
  quality: 'PARTIAL',
} as Company;
it('keeps price and gain columns first and prioritizes populated quarterly metrics', () => {
  render(<TrackerTable companies={[company]} />);
  const headers = screen
    .getAllByRole('columnheader')
    .map((h) => h.textContent?.replace(/ [↕↑↓]$/, ''));
  expect(headers.slice(0, 7)).toEqual([
    'Company',
    'Issue size (₹ crore)',
    'IPO upper band',
    'CMP',
    'Gain since IPO',
    'Listing price (day close)',
    'Listing gain',
  ]);
  expect(headers.indexOf('Revenue (₹ crore)')).toBeLessThan(headers.indexOf('Business trend'));
  const row = screen.getByTestId('company-row');
  expect(within(row).getByText('+50.0%')).toBeInTheDocument();
  expect(within(row).getByText('+20.0%')).toBeInTheDocument();
  expect(row.querySelector('[data-label="IPO upper band"]')).toHaveTextContent('₹100');
  expect(row.querySelector('[data-label="Revenue (₹ crore)"]')).toHaveTextContent('0');
  expect(Array.from(row.querySelectorAll('td')).map((td) => td.dataset.label)).toEqual(
    headers.slice(1),
  );
});
it('shows unavailable listing data without inventing a price or gain', () => {
  render(
    <TrackerTable
      companies={[{ ...company, listing_price: null, listing_gain: null, return_ipo: null }]}
    />,
  );
  expect(screen.getByText('Awaiting listing-day close')).toBeInTheDocument();
  expect(
    screen.getByTestId('company-row').querySelector('[data-label="Listing gain"]'),
  ).toHaveTextContent('—');
});

it('sorts through links preserving filters and resets pagination', () => {
  render(
    <TrackerTable companies={[company]} query="sort=return_ipo&order=desc&board=SME&page=3" />,
  );
  const link = screen.getByRole('link', { name: 'Gain since IPO' });
  expect(link).toHaveAttribute('href', '/tracker?sort=return_ipo&order=asc&board=SME');
  expect(link.closest('th')).toHaveAttribute('aria-sort', 'descending');
});
it('highlights only gains strictly above 100 percent', () => {
  render(
    <TrackerTable
      companies={[101, 100, -2, null].map((value, i) => ({
        ...company,
        id: String(i),
        return_ipo: value,
      }))}
    />,
  );
  expect(
    screen.getAllByTestId('company-row').map((r) => r.classList.contains('ipo-gain-highlight')),
  ).toEqual([true, false, false, false]);
});
