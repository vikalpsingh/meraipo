import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { EmailApplicationSchedule } from '../../components/email-application-schedule';
afterEach(() => vi.unstubAllGlobals());

it('saves both days and minute precision without enabling production', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue({ ok: true, json: async () => ({ message: 'Schedule saved' }) });
  vi.stubGlobal('fetch', fetcher);
  render(
    <EmailApplicationSchedule
      csrf="csrf"
      config={{ mode: 'opening', time: '09:00' }}
      onSaved={async () => {}}
    />,
  );
  fireEvent.change(screen.getByLabelText('Send reminders on'), { target: { value: 'both' } });
  fireEvent.change(screen.getByLabelText('Send time (IST)'), { target: { value: '08:30' } });
  expect(screen.getByRole('button', { name: 'Send today’s combined test' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Save reminder schedule' }));
  await waitFor(() =>
    expect(fetcher).toHaveBeenCalledWith(
      '/api/v1/admin/email/application-schedule',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ mode: 'both', time: '08:30' }),
        headers: expect.objectContaining({ 'X-CSRF-Token': 'csrf' }),
      }),
    ),
  );
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it('queues a fixed-recipient test and exposes delivery status', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({ id: 'delivery', message: 'Queued one test' }),
    })
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({ status: 'DELIVERED', delivered_at: '2026-11-19T03:10:00Z' }),
    });
  vi.stubGlobal('fetch', fetcher);
  render(
    <EmailApplicationSchedule
      csrf="csrf"
      config={{ mode: 'both', time: '08:30' }}
      onSaved={async () => {}}
    />,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Send today’s combined test' }));
  await screen.findByText('Queued one test');
  fireEvent.click(screen.getByRole('button', { name: 'Check test delivery' }));
  expect(await screen.findByText(/Test status: DELIVERED/)).toBeInTheDocument();
  expect(fetcher.mock.calls[0][1].body).toBeUndefined(); // recipient cannot be substituted from the UI
});
