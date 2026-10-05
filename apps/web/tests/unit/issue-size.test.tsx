import { render, screen, within } from '@testing-library/react';
import { expect, it } from 'vitest';
import { IPOInterestTable } from '@/components/ipo-interest-table';
import { IPOCard } from '@/components/content';
import type { Company } from '@/lib/types';

it.each([
  [1234.56, '1,234.56'],
  [0, '0'],
  [null, '—'],
])('shows total offer size %s in crore without rescaling', (issue_size, expected) => {
  render(
    <IPOInterestTable
      today="2026-10-05"
      companies={[
        {
          id: 'issue',
          name: 'Offer',
          slug: 'offer',
          board: 'SME',
          status: 'OPEN',
          issue_size,
        } as Company,
      ]}
    />,
  );
  expect(
    screen
      .getAllByRole('columnheader')
      .slice(0, 4)
      .map((h) => h.textContent),
  ).toEqual(['Company / bidding dates', 'Security type', 'Issue size (₹ crore)', 'Price band']);
  expect(screen.getByRole('columnheader', { name: 'Issue size (₹ crore)' })).toHaveAttribute(
    'title',
    'Total offer value in ₹ crore',
  );
  expect(within(screen.getAllByRole('row')[1]).getAllByRole('cell')[2]).toHaveTextContent(
    expected as string,
  );
});

it.each(['OPEN', 'UPCOMING', 'ANNOUNCED', 'CLOSED', 'LISTED'])(
  'shows issue size first in the %s company card',
  (status) => {
    const { container } = render(
      <IPOCard
        today="2026-10-05"
        company={
          {
            id: 'issue',
            name: 'Offer',
            slug: 'offer',
            board: 'SME',
            status,
            issue_size: 1234.56,
          } as Company
        }
      />,
    );
    const firstMetric = container.querySelector('article > dl > div');
    expect(firstMetric?.querySelector('dt')).toHaveTextContent('Issue size (₹ crore)');
    expect(firstMetric?.querySelector('dd')).toHaveTextContent('1,234.56');
  },
);

it.each([
  [0, '0'],
  [null, 'To be announced'],
])('preserves zero and missing issue sizes in company cards: %s', (issue_size, expected) => {
  const { container } = render(
    <IPOCard
      company={
        { id: 'issue', name: 'Offer', slug: 'offer', status: 'UPCOMING', issue_size } as Company
      }
      today="2026-10-05"
    />,
  );
  expect(container.querySelector('article > dl > div > dd')).toHaveTextContent(expected as string);
});
