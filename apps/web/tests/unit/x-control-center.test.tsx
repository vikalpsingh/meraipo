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
  fireEvent.click(await screen.findByRole('button', { name: 'Market updates' }));
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
  fireEvent.click(await screen.findByRole('button', { name: 'Market updates' }));
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
    screen.queryByRole('button', { name: "Get today's market-opening draft · OpenAI" }),
  ).not.toBeInTheDocument();
});

it('requires response review before queuing GPT text to X', async () => {
  const fetcher = vi.fn().mockImplementation(async (url, options) => ({
    ok: true,
    json: async () =>
      options?.method !== 'POST'
        ? { ...overview, openai_configured: true }
        : url.endsWith('/openai-test')
          ? { openai_test: { text: 'Integration test only.', model: 'test-model', elapsed_ms: 12 } }
          : url.endsWith('/manual-draft')
            ? { id: 'manual-test', message: 'Saved' }
            : { message: 'Queued' },
  }));
  vi.stubGlobal('fetch', fetcher);
  render(<XControlCenter csrf="csrf-token" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Market updates' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Test OpenAI connection' }));
  expect(await screen.findByText('Integration test only.')).toBeInTheDocument();
  const publish = screen.getByRole('button', { name: 'Publish reviewed GPT response to X' });
  expect(publish).toBeDisabled();
  fireEvent.click(
    screen.getByRole('checkbox', {
      name: 'I reviewed this response and want to publish it publicly to @MeraIPO.',
    }),
  );
  fireEvent.click(publish);
  await waitFor(() =>
    expect(fetcher).toHaveBeenCalledWith(
      '/api/v1/admin/x/manual-test/publish',
      expect.objectContaining({ method: 'POST' }),
    ),
  );
  const calls = fetcher.mock.calls
    .filter(([, options]) => options?.method === 'POST')
    .map(([url]) => url);
  expect(calls).toEqual([
    '/api/v1/admin/x/openai-test',
    '/api/v1/admin/x/manual-draft',
    '/api/v1/admin/x/manual-test/approve',
    '/api/v1/admin/x/manual-test/publish',
  ]);
});

it('generates a market content test with the schedule disabled and shows review actions', async () => {
  let generated = false;
  const post = {
    id: 'market-test',
    kind: 'MARKET_TEST',
    status: 'DRAFT',
    content: 'Market summary #StockMarket',
    evidence: { facts: [] },
    attempts: 0,
    created_at: '2026-11-25T03:15:00Z',
  };
  const fetcher = vi.fn().mockImplementation(async (url) => ({
    ok: true,
    json: async () => {
      if (url.endsWith('/content-test')) {
        generated = true;
        return { test_id: post.id, message: 'Draft ready' };
      }
      return { ...overview, openai_configured: true, posts: generated ? [post] : [] };
    },
  }));
  vi.stubGlobal('fetch', fetcher);
  render(<XControlCenter csrf="csrf-token" />);
  fireEvent.click(await screen.findByRole('button', { name: 'Market updates' }));
  fireEvent.click(
    await screen.findByRole('button', { name: "1. Generate today's market update · test" }),
  );
  expect(await screen.findByRole('region', { name: 'Generated content test' })).toHaveTextContent(
    'Market summary #StockMarket',
  );
  expect(screen.getByRole('button', { name: 'Publish test content to X' })).toBeDisabled();
  expect(fetcher).toHaveBeenCalledWith(
    '/api/v1/admin/x/content-test',
    expect.objectContaining({ body: JSON.stringify({ kind: 'MARKET_DAILY' }) }),
  );
});

it('submits the chosen currently open IPO for an image test', async () => {
  const fetcher = vi.fn().mockImplementation(async (_url, options) => ({
    ok: true,
    json: async () =>
      options?.method === 'POST'
        ? { message: 'Generated' }
        : { ...overview, test_ipos: [{ id: 'open-ipo', name: 'Current company' }] },
  }));
  vi.stubGlobal('fetch', fetcher);
  render(<XControlCenter csrf="csrf-token" />);
  fireEvent.change(await screen.findByLabelText('Currently open IPO for test'), {
    target: { value: 'open-ipo' },
  });
  fireEvent.click(
    screen.getByRole('button', { name: '1. Generate selected IPO content and image · test' }),
  );
  await waitFor(() =>
    expect(fetcher).toHaveBeenCalledWith(
      '/api/v1/admin/x/content-test',
      expect.objectContaining({
        body: JSON.stringify({ kind: 'IPO_OPENING', ipo_id: 'open-ipo' }),
      }),
    ),
  );
});

it('separates publishing tabs and submits a company results test', async () => {
  const fetcher = vi
    .fn()
    .mockImplementation(async (_url, options) => ({
      ok: true,
      json: async () =>
        options?.method === 'POST'
          ? { message: 'Results saved' }
          : { ...overview, openai_configured: true },
    }));
  vi.stubGlobal('fetch', fetcher);
  render(<XControlCenter csrf="csrf-token" />);
  expect(await screen.findByRole('region', { name: 'IPO publishing tab' })).toBeInTheDocument();
  expect(screen.queryByLabelText('Company name or exchange symbol')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Quarterly results' }));
  fireEvent.change(screen.getByLabelText('Company name or exchange symbol'), {
    target: { value: 'Example Ltd' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Generate company results test' }));
  await waitFor(() =>
    expect(fetcher).toHaveBeenCalledWith(
      '/api/v1/admin/x/results-test',
      expect.objectContaining({ body: JSON.stringify({ company: 'Example Ltd' }) }),
    ),
  );
  expect(screen.queryByLabelText('Currently open IPO for test')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Quarterly results' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
});
