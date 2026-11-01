import { ListingGainSubscription } from '../../components/listing-gain-subscription';
import { StrictMode } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { EmailSubscription } from '../../components/email-subscription';
import { AnalyticsConsent } from '../../components/analytics-consent';
vi.mock('next/navigation', () => ({ usePathname: () => '/' }));
vi.mock('next/script', () => ({
  default: ({ src }: { src: string }) => <span data-testid="ga-script">{src}</span>,
}));
afterEach(() => {
  cleanup();
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
  await screen.findByText('Check your inbox.');
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

it('opens the automatic dialog without a homepage subscription link', () => {
  const show = vi.fn(function (this: HTMLDialogElement) {
    this.setAttribute('open', '');
  });
  const close = vi.fn(function (this: HTMLDialogElement) {
    this.removeAttribute('open');
    this.dispatchEvent(new Event('close'));
  });
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
    configurable: true,
    value: show,
  });
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: close });
  document.cookie = 'meraipo-alert-prompt=; Max-Age=0; Path=/';
  render(<ListingGainSubscription />);
  expect(screen.queryByRole('button', { name: /Listing gain email subscription/ })).toBeNull();
  expect(show).toHaveBeenCalledOnce();
  expect(screen.getByRole('dialog')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Do it later · Close ✕' }));
  expect(close).toHaveBeenCalledOnce();
  expect(window.location.pathname).toBe('/');
  show.mockRestore();
  close.mockRestore();
});

it('automatically invites a new visitor once and remembers it without contact details', () => {
  document.cookie = 'meraipo-alert-prompt=; Max-Age=0; Path=/';
  const show = vi.fn(function (this: HTMLDialogElement) {
    this.setAttribute('open', '');
  });
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
    configurable: true,
    value: show,
  });
  const first = render(<ListingGainSubscription />);
  expect(show).toHaveBeenCalledOnce();
  expect(document.cookie).toContain('meraipo-alert-prompt=seen');
  first.unmount();
  render(<ListingGainSubscription />);
  expect(show).toHaveBeenCalledOnce();
});
