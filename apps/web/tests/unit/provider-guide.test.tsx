import { render, screen, fireEvent } from '@testing-library/react';
import { expect, it } from 'vitest';
import { ApplicantGuide } from '@/components/applicant-guide';
import type { Company } from '@/lib/types';
it('shows full provider research and date-only schedules without claiming editorial verification', () => {
  const company = {
    id: 'provider-test',
    slug: 'provider-test',
    name: 'Provider test',
    board: 'SME',
    status: 'UPCOMING',
    is_demo: false,
    applicant_guide: null,
    lot_size: 1200,
    price_high: 106,
    open_date: '2026-09-22',
    close_date: '2026-09-24',
    listing_date: '2026-09-29',
    provider_details: {
      provider: 'IPOALERTS',
      source_url: 'https://api.ipoalerts.in/ipos',
      fetched_at: '2026-09-21T10:00:00Z',
      about: 'Manufactures products for customers.',
      strengths: ['Distribution network'],
      risks: ['Customer concentration'],
      minimum_amount: '127200',
      schedule: [{ event: 'UPI mandate deadline', date: '2026-09-24' }],
    },
  } as Company;
  render(<ApplicantGuide company={company} />);
  expect(screen.getByText('Manufactures products for customers.')).toBeInTheDocument();
  expect(screen.getByText('Customer concentration')).toBeInTheDocument();
  expect(screen.getByText(/Not independently reviewed/)).toBeInTheDocument();
  fireEvent.click(screen.getByText('Full provider schedule'));
  expect(screen.getByText(/UPI mandate deadline: 24 Sept 2026/)).toBeInTheDocument();
  expect(screen.getByText(/no deadline time was provided/)).toBeInTheDocument();
});
