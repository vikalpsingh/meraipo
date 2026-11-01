import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { EmailControlCenter } from '../../components/email-control-center';
import type { Company } from '../../lib/types';
afterEach(() => vi.unstubAllGlobals());
const status = {
  sending_enabled: false,
  readiness: {
    ready: false,
    checks: { test_received: false },
    aws: {
      status: 'NOT_CONFIGURED',
      ready: false,
      sender: 'MeraIPO Alerts <alerts@meraipo.com>',
      checks: {},
      max_rate: null,
      remaining_quota: null,
    },
  },
  counts: {},
  subscribers: {},
  scheduler_seen_at: null,
  last_accepted_at: null,
  test: null,
  last_run: null,
  failures: [],
};
const companies = [{ id: 'company', ipo_id: 'ipo', name: 'Fixture IPO' } as Company];
it('shows unavailable setup and prevents activating production', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => status }));
  render(<EmailControlCenter csrf="token" companies={companies} />);
  expect(await screen.findByRole('switch')).toBeDisabled();
  expect(screen.getByText(/NOT CONFIGURED/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Send one TEST to my admin email' })).toBeDisabled();
});
it('requires preview before an explicit test request and passes CSRF', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce({ ok: true, json: async () => status })
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        subject: 'TEST — Fixture',
        html: '<p>Fixture</p>',
        text: 'Fixture text',
      }),
    })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ message: 'TEST queued.' }) })
    .mockResolvedValue({ ok: true, json: async () => status });
  vi.stubGlobal('fetch', fetcher);
  render(<EmailControlCenter csrf="token" companies={companies} />);
  await screen.findByRole('switch');
  fireEvent.change(screen.getByLabelText('IPO'), { target: { value: 'ipo' } });
  fireEvent.click(screen.getByRole('button', { name: 'Preview HTML and text' }));
  expect(await screen.findByTitle('Test email preview')).toHaveAttribute('sandbox', '');
  expect(fetcher).toHaveBeenCalledTimes(2);
  fireEvent.click(screen.getByRole('button', { name: 'Send one TEST to my admin email' }));
  await screen.findByText('TEST queued.');
  expect(fetcher).toHaveBeenCalledWith(
    '/api/v1/admin/email/test',
    expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ 'X-CSRF-Token': 'token' }),
      body: '{"ipo_id":"ipo"}',
    }),
  );
});
