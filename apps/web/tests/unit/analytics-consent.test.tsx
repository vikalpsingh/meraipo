import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AnalyticsConsent } from '../../components/analytics-consent';

const state = vi.hoisted(() => ({ path: '/', ready: undefined as undefined | (() => void) }));
vi.mock('next/navigation', () => ({ usePathname: () => state.path }));
vi.mock('next/script', () => ({
  default: ({ src, onReady }: { src: string; onReady: () => void }) => {
    state.ready = onReady;
    return <span data-testid="google-tag" data-src={src} />;
  },
}));
type TestWindow = Window & { gtag?: ReturnType<typeof vi.fn>; dataLayer?: unknown[] };
beforeEach(() => {
  localStorage.clear();
  state.path = '/';
  state.ready = undefined;
  delete (window as TestWindow).gtag;
  delete (window as TestWindow).dataLayer;
  window.history.replaceState({}, '', '/');
});
afterEach(() => vi.restoreAllMocks());

it('requires consent and loads the GA4 URL rather than a GTM container URL', async () => {
  render(<AnalyticsConsent measurementId="G-ZYEKCCV3J5" />);
  expect(screen.queryByTestId('google-tag')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Allow analytics' }));
  expect(await screen.findByTestId('google-tag')).toHaveAttribute(
    'data-src',
    'https://www.googletagmanager.com/gtag/js?id=G-ZYEKCCV3J5',
  );
});

it('configures once and tracks each public route without sending private query data', async () => {
  localStorage.setItem('meraipo-analytics-consent', 'granted');
  const gtag = vi.fn();
  (window as TestWindow).gtag = gtag;
  const view = render(<AnalyticsConsent measurementId="G-ZYEKCCV3J5" />);
  await screen.findByTestId('google-tag');
  act(() => state.ready?.());
  await waitFor(() => expect(gtag.mock.calls.filter((c) => c[1] === 'page_view')).toHaveLength(1));
  for (const path of ['/ipo-tracker', '/ipo/example', '/email-alerts', '/ipo-status', '/privacy']) {
    state.path = path;
    window.history.replaceState({}, '', path + '?email=private%40example.com#secret');
    view.rerender(<AnalyticsConsent measurementId="G-ZYEKCCV3J5" />);
  }
  expect(gtag.mock.calls.filter((c) => c[0] === 'config')).toHaveLength(1);
  expect(gtag.mock.calls.filter((c) => c[1] === 'page_view')).toHaveLength(6);
  expect(JSON.stringify(gtag.mock.calls)).not.toContain('private');
  expect(JSON.stringify(gtag.mock.calls)).not.toContain('secret');
  view.rerender(<AnalyticsConsent measurementId="G-ZYEKCCV3J5" />);
  expect(gtag.mock.calls.filter((c) => c[1] === 'page_view')).toHaveLength(6);
  for (const path of ['/meraadmin', '/email-alerts/confirm', '/email-alerts/unsubscribe']) {
    state.path = path;
    view.rerender(<AnalyticsConsent measurementId="G-ZYEKCCV3J5" />);
    expect(screen.queryByTestId('google-tag')).not.toBeInTheDocument();
  }
  expect(gtag.mock.calls.filter((c) => c[1] === 'page_view')).toHaveLength(6);
});

it('stops pageviews after consent is withdrawn', async () => {
  localStorage.setItem('meraipo-analytics-consent', 'granted');
  const gtag = vi.fn();
  (window as TestWindow).gtag = gtag;
  const view = render(<AnalyticsConsent measurementId="G-ZYEKCCV3J5" />);
  await screen.findByTestId('google-tag');
  act(() => state.ready?.());
  fireEvent.click(screen.getByRole('button', { name: 'Disable website analytics' }));
  state.path = '/ipo-status';
  view.rerender(<AnalyticsConsent measurementId="G-ZYEKCCV3J5" />);
  expect(gtag.mock.calls.filter((c) => c[1] === 'page_view')).toHaveLength(1);
});
