import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { applicationEstimate, calendar, indiaDay } from '@/lib/applicant';
import type { Company } from '@/lib/types';
import { ApplicationCalculator, ApplicationChecklist } from '@/components/applicant-tools';
import { ApplicantGuide, TodayActions } from '@/components/applicant-guide';

const c = {
  id: 'one',
  name: 'Example Company',
  slug: 'example-company',
  board: 'Mainboard',
  status: 'OPEN',
  is_demo: false,
  price_high: 150,
  lot_size: 50,
  open_date: '2026-09-19',
  close_date: '2026-09-22',
  listing_date: '2026-09-25',
  applicant_guide: {
    category: 'Retail individual',
    min_lots: 1,
    max_lots: null,
    max_amount: 200000,
    verification_status: 'VERIFIED',
    schedule_status: 'TENTATIVE',
    reviewed_on: '2026-09-19',
    source_url: 'https://example.com/rhp',
    allotment_date: '2026-09-23',
    unblock_date: '2026-09-24',
    bid_deadline: null,
    mandate_deadline: '2026-09-22T17:00:00+05:30',
    registrar_name: 'Example Registrar',
    registrar_url: 'https://example.com/allotment',
    business_summary: '<script>unsafe</script>',
    strengths: null,
    risks: null,
    proceeds: null,
  },
} as Company;

describe('application calculator', () => {
  it('offers bounded stepper controls and recovery after an invalid entry', () => {
    render(<ApplicationCalculator company={c} />);
    expect(screen.getByRole('button', { name: 'Decrease lots' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Increase lots' }));
    expect(screen.getByLabelText('Number of lots')).toHaveValue('2');
    fireEvent.change(screen.getByLabelText('Number of lots'), { target: { value: '100' } });
    expect(screen.getByLabelText('Number of lots')).toHaveAttribute('aria-invalid', 'true');
    fireEvent.click(screen.getByRole('button', { name: /Reset to minimum/ }));
    expect(screen.getByLabelText('Number of lots')).toHaveValue('1');
    expect(screen.getByLabelText('Number of lots')).toHaveAttribute('aria-invalid', 'false');
  });
  it('does not offer unusable controls when rules are missing', () => {
    render(<ApplicationCalculator company={{ ...c, applicant_guide: null }} />);
    expect(screen.queryByLabelText('Number of lots')).not.toBeInTheDocument();
    expect(screen.getByText(/Application rules are awaiting review/)).toBeInTheDocument();
  });
  it('calculates lots, shares and blocked amount', () => {
    expect(applicationEstimate(c, '2')).toEqual({ shares: 100, amount: 15000, lots: 2 });
  });
  it.each(['', '0', '-1', '1.5', 'NaN', '10000000000000000000', '100'])(
    'rejects invalid/out-of-category lots %s',
    (input) => {
      expect(applicationEstimate(c, input).error).toBeTruthy();
    },
  );
  it('supports issue-specific SME two-lot bounds', () => {
    const sme = {
      ...c,
      board: 'SME',
      lot_size: 1000,
      applicant_guide: {
        ...c.applicant_guide!,
        category: 'Individual investor',
        min_lots: 2,
        max_lots: 2,
        max_amount: null,
      },
    };
    expect(applicationEstimate(sme, '2').amount).toBe(300000);
    expect(applicationEstimate(sme, '1').error).toBeTruthy();
    expect(applicationEstimate(sme, '3').error).toBeTruthy();
  });
  it('does not invent missing or unreviewed application rules', () => {
    expect(applicationEstimate({ ...c, applicant_guide: null }, '1').error).toBeTruthy();
    expect(applicationEstimate({ ...c, price_high: null }, '1').error).toBeTruthy();
    expect(
      applicationEstimate(
        { ...c, applicant_guide: { ...c.applicant_guide!, verification_status: 'UNVERIFIED' } },
        '1',
      ).error,
    ).toBeTruthy();
  });
  it('updates the accessible result and handles invalid input', () => {
    render(<ApplicationCalculator company={c} />);
    fireEvent.change(screen.getByLabelText('Number of lots'), { target: { value: '2' } });
    expect(screen.getByText('₹15,000')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Number of lots'), { target: { value: '' } });
    expect(screen.getByText(/Enter a whole number/)).toBeInTheDocument();
  });
});

it('uses Indian calendar days at UTC midnight boundaries', () => {
  expect(indiaDay(new Date('2026-09-19T20:00:00Z'))).toBe('2026-09-20');
});
it('builds escaped, folded calendars with stable IDs and timezone-safe deadlines', () => {
  const file = calendar(
    { ...c, name: 'Example, company\nBEGIN:VEVENT ' + '₹'.repeat(60) },
    new Date('2026-09-19T00:00:00Z'),
  );
  expect(file).toContain('DTSTART:20260922T113000Z');
  expect(file).toContain('DTSTART;VALUE=DATE:20260919');
  expect(file).toContain('UID:example-company-mandate@meraipo');
  expect(file).toContain('Example\\, company\\nBEGIN');
  expect(file).toContain('STATUS:TENTATIVE');
  expect(file.split('\r\n').every((line) => new TextEncoder().encode(line).length <= 75)).toBe(
    true,
  );
});
it('uses personal checklist state without claiming a verified application', () => {
  render(<ApplicationChecklist />);
  fireEvent.click(screen.getAllByRole('checkbox', { hidden: true })[0]);
  expect(screen.getByText('1/5')).toBeInTheDocument();
  expect(screen.getByText(/MeraIPO cannot verify/)).toBeInTheDocument();
});
it('renders a reviewed registrar link and escapes the business summary', () => {
  render(<ApplicantGuide company={c} />);
  expect(
    screen.getByRole('link', { name: /Check allotment with Example Registrar/ }),
  ).toHaveAttribute('href', 'https://example.com/allotment');
  expect(document.querySelector('script')).toBeNull();
});
it('hides unverified registrar destinations', () => {
  render(
    <ApplicantGuide
      company={{
        ...c,
        applicant_guide: { ...c.applicant_guide!, verification_status: 'UNVERIFIED' },
      }}
    />,
  );
  expect(screen.queryByRole('link', { name: /Check allotment with/ })).not.toBeInTheDocument();
  expect(
    screen.getByText('The official registrar link is awaiting verification.'),
  ).toBeInTheDocument();
});
it('shows only relevant current actions and deduplicates issues', () => {
  render(<TodayActions companies={[c, c]} now={new Date('2026-09-22T03:00:00Z')} />);
  expect(screen.getAllByRole('link', { name: 'Example Company ↗' })).toHaveLength(1);
  expect(screen.getByText('Closing today')).toBeInTheDocument();
});
