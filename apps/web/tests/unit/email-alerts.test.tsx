import { ListingGainSubscription } from '../../components/listing-gain-subscription';
import { StrictMode } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { EmailSubscription } from '../../components/email-subscription';
import { AnalyticsConsent } from '../../components/analytics-consent';
const route = vi.hoisted(() => ({ path: '/' }));
vi.mock('next/navigation', () => ({ usePathname: () => route.path }));
vi.mock('next/script', () => ({
  default: ({ src, onReady }: { src: string; onReady: () => void }) => (
    <button data-testid="ga-script" onClick={onReady}>
      {src}
    </button>
  ),
}));
afterEach(() => {
  cleanup();
  route.path = '/';
  vi.unstubAllGlobals();
  localStorage.clear();
  window.history.replaceState(null, '', '/');
});
it('requires explicit consent, names and a single GMP band with optional phone', async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue({ ok: true, json: async () => ({ message: 'Check your inbox.' }) });
  vi.stubGlobal('fetch', fetch);
  render(<EmailSubscription />);
  expect(screen.getByRole('checkbox')).not.toBeChecked();
  expect(screen.getByRole('checkbox')).toBeRequired();
  fireEvent.change(screen.getByLabelText('Email address'), {
    target: { value: 'person@example.com' },
  });
  fireEvent.change(screen.getByLabelText('First name'), { target: { value: 'Test' } });
  fireEvent.change(screen.getByLabelText('Surname (last name)*'), { target: { value: 'Person' } });
  expect(screen.getByLabelText('Phone No (optional)')).not.toBeRequired();
  expect(screen.getAllByRole('radio')).toHaveLength(4);
  fireEvent.click(screen.getByLabelText('Gold: above 100%'));
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button', { name: 'Subscribe to IPO alerts' }));
  await screen.findByText('Thank you! Request saved.');
  expect(screen.getByRole('status')).toHaveTextContent('after you confirm your email');
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
    email: 'person@example.com',
    first_name: 'Test',
    last_name: 'Person',
    phone: '',
    gmp_band: 'gold',
    consent: true,
  });
});
it('preserves a private confirmation token through strict-mode effects without auto-confirming', async () => {
  const token = 'a'.repeat(64);
  window.history.replaceState(null, '', '/email-alerts/verify#' + token);
  const fetch = vi
    .fn()
    .mockResolvedValue({ ok: true, json: async () => ({ message: 'Confirmed.' }) });
  vi.stubGlobal('fetch', fetch);
  render(
    <StrictMode>
      <EmailSubscription action="verify" />
    </StrictMode>,
  );
  expect(window.location.hash).toBe('');
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Confirm subscription' }));
  await screen.findByText('Confirmed.');
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ token });
});
it('does not load Google until optional consent and supports withdrawal', async () => {
  render(<AnalyticsConsent measurementId="G-TEST123" />);
  expect(screen.queryByTestId('ga-script')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Allow analytics' }));
  await screen.findByTestId('ga-script');
  fireEvent.click(screen.getByRole('button', { name: 'Disable website analytics' }));
  await waitFor(() => expect(screen.queryByTestId('ga-script')).toBeNull());
  expect(localStorage.getItem('meraipo-analytics-consent')).toBe('denied');
});

it('renders the standalone subscription page without a popup', () => {
  render(<ListingGainSubscription />);
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(screen.getByRole('heading', { name: 'Your next IPO starts here' })).toBeVisible();
  expect(screen.queryByRole('button', { name: /Do it later/ })).toBeNull();
});

it('records consented public navigation once per pathname and excludes private routes', async () => {
  localStorage.setItem('meraipo-analytics-consent', 'granted');
  const view = render(<AnalyticsConsent measurementId="G-TEST123" />);
  fireEvent.click(await screen.findByTestId('ga-script'));
  const ga = window as Window & { dataLayer?: ArrayLike<unknown>[] };
  try {
    for (const path of [
      '/tracker',
      '/email-alerts',
      '/email-alerts/verify',
      '/email-alerts/unsubscribe',
      '/meraadmin',
      '/feedback',
    ]) {
      route.path = path;
      view.rerender(<AnalyticsConsent measurementId="G-TEST123" />);
    }
    const locations = ga.dataLayer
      ?.filter((command) => command[1] === 'page_view')
      .map((command) => new URL((command[2] as { page_location: string }).page_location).pathname);
    expect(locations).toEqual(['/', '/tracker', '/email-alerts', '/feedback']);
  } finally {
    delete ga.dataLayer;
  }
});
