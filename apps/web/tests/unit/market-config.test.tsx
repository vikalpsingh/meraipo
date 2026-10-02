import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { MarketConfig } from '../../components/market-config';

const config = {
  provider_mode: 'manual',
  market_scheduler_enabled: false,
  market_scheduler_driver: 'celery',
  exchange_direct_enabled: false,
  nse_subscription_categories_enabled: true,
  ipo_data_provider: 'ipoalerts',
  ipoalerts_api_key_configured: true,
  ipoalerts_page_size: 25,
  market_feeds_json: '{}',
  exchange_sources_json: '[]',
  bse_ipo_issues_json: '[]',
  trading_holidays: '',
  trading_calendar_year: 2026,
  source: 'admin',
  updated_at: '2026-10-02T12:00:00Z',
};

afterEach(() => vi.restoreAllMocks());

it('masks a configured API key and saves market settings', async () => {
  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify(config), { status: 200 }))
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ...config,
          provider_mode: 'market-feeds',
          market_scheduler_enabled: true,
        }),
        { status: 200 },
      ),
    );
  render(<MarketConfig csrf="csrf-token" />);
  expect(await screen.findByText(/API key: configured/)).toBeInTheDocument();
  const secret = screen.getByLabelText('IPOAlerts API key');
  expect(secret).toHaveAttribute('type', 'password');
  expect(secret).toHaveValue('');
  fireEvent.change(screen.getByLabelText('Provider mode'), {
    target: { value: 'market-feeds' },
  });
  fireEvent.click(screen.getByLabelText('Enable scheduled jobs'));
  fireEvent.change(secret, { target: { value: 'replacement-secret' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }));
  await screen.findByText(/New job runs will use these values/);
  const request = fetchMock.mock.calls[1][1];
  expect(request?.headers).toEqual({
    'Content-Type': 'application/json',
    'X-CSRF-Token': 'csrf-token',
  });
  expect(JSON.parse(String(request?.body))).toMatchObject({
    provider_mode: 'market-feeds',
    market_scheduler_enabled: true,
    ipoalerts_api_key: 'replacement-secret',
  });
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
});
