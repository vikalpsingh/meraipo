import { render, screen, fireEvent } from '@testing-library/react';
import { expect, it } from 'vitest';
import {
  FinancialPerformance,
  type FinancialPerformanceData,
} from '@/components/financial-performance';
const row = {
  period_start: '2026-04-01',
  period_end: '2026-06-30',
  period_type: 'QUARTERLY',
  basis: 'CONSOLIDATED',
  revision: 2,
  facts: {
    revenue: '1645400000',
    pat: '143760000',
    basic_eps: '1.65',
    diluted_eps: null,
    total_income: null,
    pbt: null,
  },
  exchange: 'NSE',
  filing_date: '2026-10-01',
  updated_at: '2026-10-05',
  source_url: 'https://nsearchives.nseindia.com/corporate/test.xml',
};
it('formats stored rupees in crore, preserves EPS and never mixes statement bases', () => {
  render(
    <FinancialPerformance
      data={
        {
          status: 'AVAILABLE',
          items: [
            row,
            { ...row, basis: 'STANDALONE', facts: { ...row.facts, revenue: '2000000000' } },
          ],
        } as FinancialPerformanceData
      }
    />,
  );
  expect(screen.getByLabelText('Accounting basis')).toHaveValue('CONSOLIDATED');
  expect(screen.getByText('₹164.54')).toBeInTheDocument();
  expect(screen.getByText('₹1.65')).toBeInTheDocument();
  expect(screen.queryByText('₹200')).not.toBeInTheDocument();
  expect(screen.getByText(/Revision 2/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Accounting basis'), { target: { value: 'STANDALONE' } });
  expect(screen.getByText('₹200')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Reporting period'), { target: { value: 'HALF_YEARLY' } });
  expect(screen.getByText(/Not yet reported/)).toBeInTheDocument();
});
it('explains nonpositive prior revenue instead of misleading growth', () => {
  render(
    <FinancialPerformance
      data={{
        status: 'AVAILABLE',
        items: [
          row,
          {
            ...row,
            period_start: '2025-04-01',
            period_end: '2025-06-30',
            facts: { ...row.facts, revenue: '0' },
          },
        ],
      }}
    />,
  );
  expect(
    screen.getByText('Prior revenue is zero or negative; % not comparable'),
  ).toBeInTheDocument();
});
