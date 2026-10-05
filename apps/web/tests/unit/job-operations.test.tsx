import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { MarketConsole } from '@/components/market-console';
import { JobHistory } from '@/components/job-history';
import type { ScheduledJob } from '@/components/job-types';
const jobs: ScheduledJob[] = ['prices', 'results'].flatMap((kind) =>
  ['NSE', 'BSE'].map((exchange) => ({
    name: `sync-${kind}-${exchange.toLowerCase()}`,
    label: `${exchange} · ${kind === 'prices' ? 'Daily closing prices' : 'Quarterly results'}`,
    schedule: '19:30 daily',
    paused: false,
    source_enabled: true,
    exchange,
    configurable: true,
    times: ['19:30'],
    next_run: '2026-10-06T19:30:00+05:30',
    last: null,
    last_success: null,
  })),
);
afterEach(() => vi.restoreAllMocks());
it('runs and configures each exchange independently without loading recovery forms', async () => {
  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockImplementation(
      async (url, init) =>
        new Response(
          JSON.stringify(
            init?.method
              ? { id: 'run-nse' }
              : { enabled: true, driver: 'celery', configuration_error: null, jobs },
          ),
          { status: 200 },
        ),
    );
  render(<MarketConsole csrf="test-csrf" companies={[]} />);
  const heading = await screen.findByRole('heading', { name: 'NSE · Daily closing prices' });
  const card = heading.closest('article')!;
  expect(screen.getAllByRole('button', { name: 'Run now' })).toHaveLength(4);
  expect(screen.queryByText('Financial results importer')).not.toBeInTheDocument();
  fireEvent.click(within(card).getByRole('button', { name: 'Run now' }));
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/admin/market/sync-prices-nse/run',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'X-CSRF-Token': 'test-csrf' }),
      }),
    ),
  );
  await screen.findByText(/Run queued/);
  fireEvent.click(within(card).getByText('Schedule & configuration'));
  fireEvent.change(within(card).getByLabelText('Run times (IST)'), {
    target: { value: '18:30, 21:00' },
  });
  fireEvent.click(within(card).getByRole('button', { name: 'Save schedule' }));
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/admin/market/sync-prices-nse/schedule',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ times: ['18:30', '21:00'], paused: false }),
      }),
    ),
  );
});
it('filters history and shows failure guidance tied to the selected run', async () => {
  const run = {
    id: 'failed-run',
    job_name: 'sync-prices-bse',
    status: 'FAILED',
    created_at: '2026-10-05T14:00:00Z',
    started_at: null,
    finished_at: null,
    error: 'SOURCE_ACCESS_BLOCKED',
    trigger: 'manual',
  };
  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockImplementation(
      async (url) =>
        new Response(
          JSON.stringify(
            String(url).endsWith('/failed-run')
              ? {
                  run,
                  guidance: 'Verify permitted exchange access',
                  error_count: 1,
                  errors: [
                    {
                      id: 'e',
                      provider: 'BSE',
                      item: '2026-10-05',
                      code: 'SOURCE_ACCESS_BLOCKED',
                      detail: 'Access denied',
                      guidance: 'Verify permitted exchange access',
                    },
                  ],
                  files: [],
                }
              : { items: [run], total: 1, page_size: 25 },
          ),
          { status: 200 },
        ),
    );
  render(<JobHistory jobs={jobs} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Inspect run' }));
  expect(await screen.findAllByText('Verify permitted exchange access')).not.toHaveLength(0);
  expect(screen.getByText('failed-run')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'FAILED' } });
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('status=FAILED'),
      expect.anything(),
    ),
  );
});
