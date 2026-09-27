import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { FeatureControls } from '@/components/feature-controls';
import { SiteNavigation } from '@/components/site-navigation';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ refresh: vi.fn() }),
  usePathname: () => '/',
}));
afterEach(() => vi.unstubAllGlobals());
const item = {
  key: 'ipo_tracker',
  label: 'IPO Tracker',
  description: 'Tracker access',
  enabled: false,
};

it('hides the tracker by default and shows it only when enabled', () => {
  const view = render(<SiteNavigation />);
  expect(screen.queryByRole('link', { name: 'IPO Tracker' })).not.toBeInTheDocument();
  view.rerender(<SiteNavigation trackerEnabled />);
  expect(screen.getByRole('link', { name: 'IPO Tracker' })).toHaveAttribute('href', '/tracker');
});

it('saves a release with CSRF and updates the switch', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ items: [item] }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ ...item, enabled: true }) });
  vi.stubGlobal('fetch', fetcher);
  render(<FeatureControls csrf="test-token" />);
  fireEvent.click(await screen.findByRole('switch', { name: 'IPO Tracker' }));
  await waitFor(() => expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true'));
  expect(fetcher).toHaveBeenLastCalledWith(
    '/api/v1/admin/features/ipo_tracker',
    expect.objectContaining({
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'test-token' },
      body: '{"enabled":true}',
    }),
  );
});

it('keeps the switch hidden and reports failed saves', async () => {
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ items: [item] }) })
      .mockResolvedValueOnce({ ok: false }),
  );
  render(<FeatureControls csrf="test-token" />);
  fireEvent.click(await screen.findByRole('switch'));
  await screen.findByText(/Could not save/);
  expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false');
});
