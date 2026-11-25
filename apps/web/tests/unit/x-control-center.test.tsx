import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { XControlCenter } from '../../components/x-control-center';

afterEach(() => vi.unstubAllGlobals());
const overview = {
  enabled: true,
  connected: true,
  username: 'MeraIPO',
  auto_publish: false,
  openai_configured: false,
  monthly_limit: 20,
  daily_limit: 1,
  posts: [],
  schedules: {
    MARKET_DAILY: { enabled: false, time: '08:45', auto_publish: false },
    IPO_OPENING: { enabled: false, time: '09:00' },
  },
};
it('saves only the selected schedule in IST with CSRF', async () => {
  const fetcher = vi.fn().mockImplementation(async (_url, options) => ({
    ok: true,
    json: async () => (options?.method === 'POST' ? { message: 'Schedule saved' } : overview),
  }));
  vi.stubGlobal('fetch', fetcher);
  render(<XControlCenter csrf="csrf-token" />);
  const clock = await screen.findByLabelText('Daily market update · OpenAI time in IST');
  fireEvent.change(clock, { target: { value: '08:30' } });
  fireEvent.click(screen.getByLabelText('Enable Daily market update · OpenAI'));
  fireEvent.click(screen.getAllByRole('button', { name: 'Save schedule' })[0]);
  await waitFor(() =>
    expect(fetcher).toHaveBeenCalledWith(
      '/api/v1/admin/x/schedule',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'X-CSRF-Token': 'csrf-token' }),
        body: JSON.stringify({ kind: 'MARKET_DAILY', enabled: true, time: '08:30' }),
      }),
    ),
  );
});
it('renders nested evidence safely and provides an authenticated image preview', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ...overview,
        posts: [
          {
            id: 'draft',
            kind: 'MARKET_DAILY',
            status: 'DRAFT',
            content: 'Prior close',
            has_image: true,
            evidence: {
              facts: [{ claim: 'Prior close source', url: 'https://www.nseindia.com/' }],
            },
            attempts: 0,
            created_at: '2026-11-18T03:15:00Z',
          },
        ],
      }),
    }),
  );
  render(<XControlCenter csrf="csrf-token" />);
  expect(await screen.findByRole('link', { name: 'Preview IPO image ↗' })).toHaveAttribute(
    'href',
    '/api/v1/admin/x/draft/image',
  );
  expect(screen.getByRole('link', { name: 'Prior close source ↗' })).toHaveAttribute(
    'rel',
    'noopener noreferrer',
  );
});

it('previews manual text and saves only a draft with CSRF', async () => {
  const fetcher = vi.fn().mockImplementation(async (_url, options) => ({
    ok: true,
    json: async () => (options?.method === 'POST' ? { message: 'Manual draft saved' } : overview),
  }));
  vi.stubGlobal('fetch', fetcher);
  render(<XControlCenter csrf="csrf-token" />);
  fireEvent.change(await screen.findByLabelText('Message to publish'), {
    target: { value: 'MeraIPO test message' },
  });
  expect(screen.getByText('MeraIPO test message', { selector: 'p' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Save manual draft for review' }));
  await waitFor(() =>
    expect(fetcher).toHaveBeenCalledWith(
      '/api/v1/admin/x/manual-draft',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'X-CSRF-Token': 'csrf-token' }),
        body: JSON.stringify({ content: 'MeraIPO test message' }),
      }),
    ),
  );
  expect(fetcher.mock.calls.some(([url]) => url.endsWith('/publish'))).toBe(false);
  expect(
    screen.getByRole('button', { name: "Get today's market-opening draft · OpenAI" }),
  ).toBeDisabled();
});
