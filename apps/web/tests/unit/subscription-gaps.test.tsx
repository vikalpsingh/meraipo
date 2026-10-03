import { expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { IPOInterestTable } from '@/components/ipo-interest-table';
import type { Company } from '@/lib/types';

it('marks unverified allocations with ** and explains the denominator gap', () => {
  const company: Partial<Company> = {
    id: 'gap',
    slug: 'gap',
    name: 'SME fixture',
    board: 'SME',
    status: 'OPEN',
    open_date: '2026-09-24',
    close_date: '2026-09-28',
    price_low: 85,
    price_high: 90,
    gmp: null,
    subscription: {
      observed_at: '2026-09-25T11:30:00Z',
      source_provider: 'NSE_CONSOLIDATED',
      source_url: 'https://www.nseindia.com/',
      multiple: null,
      categories: {
        retail: { multiple: null, gap_note: 'Verified category allocation missing.' },
        qib: { multiple: '0.0000' },
        nii: { multiple: '2.5000' },
      },
    },
  };
  const { container } = render(
    <IPOInterestTable companies={[company as Company]} today="2026-09-26" />,
  );
  expect(screen.getByTitle('Verified category allocation missing.')).toHaveTextContent('—**');
  expect(screen.getByRole('cell', { name: '0×' })).toBeInTheDocument();
  expect(screen.getByRole('cell', { name: '2.5×' })).toBeInTheDocument();
  expect(container.textContent).toContain('total IPO shares are not substituted');
  expect(container.textContent).toContain('SME individual-investor bids');
});
