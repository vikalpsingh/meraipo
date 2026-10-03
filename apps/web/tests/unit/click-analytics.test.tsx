import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ClickAnalytics } from '@/components/click-analytics';
import { clickSection } from '@/components/click-tracker';
afterEach(() => vi.unstubAllGlobals());
it('excludes admin routes and collapses detail paths into one fixed bucket', () => {
  expect(clickSection('/meraadmin')).toBeNull();
  expect(clickSection('/meraadmin/settings')).toBeNull();
  expect(clickSection('/ipo/example')).toBe('company');
  expect(clickSection('/company/123')).toBe('company');
});
it('shows daily counts and groups dates into calendar weeks and months', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        today: '2026-10-03',
        timezone: 'Asia/Kolkata',
        retention_days: 400,
        totals: { today: 2, week: 5, month: 5 },
        daily: [
          { day: '2026-10-03', section: 'home', clicks: 2 },
          { day: '2026-10-01', section: 'company', clicks: 3 },
        ],
      }),
    }),
  );
  render(<ClickAnalytics />);
  await screen.findByText('2026-10-03');
  fireEvent.change(screen.getByLabelText('View'), { target: { value: 'Weekly' } });
  expect(screen.getByText('2026-09-28')).toBeInTheDocument();
  expect(screen.getByText('2026-09-28').closest('tr')).toHaveTextContent('5');
  fireEvent.change(screen.getByLabelText('View'), { target: { value: 'Monthly' } });
  expect(screen.getByText('2026-10').closest('tr')).toHaveTextContent('5');
});
it('displays a recoverable error when the admin endpoint fails', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
  render(<ClickAnalytics />);
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Could not load'));
});
