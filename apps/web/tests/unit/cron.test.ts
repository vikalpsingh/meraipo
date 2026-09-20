// @vitest-environment node
import { afterEach, describe, expect, it, vi } from 'vitest';
import { GET } from '@/app/api/cron/[job]/route';

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});
describe('server-only cron bridge', () => {
  it('rejects missing authentication before contacting the API', async () => {
    vi.stubEnv('CRON_SECRET', 'a'.repeat(40));
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    const result = await GET(new Request('https://meraipo.example/api/cron/results'), {
      params: Promise.resolve({ job: 'results' }),
    });
    expect(result.status).toBe(401);
    expect(fetch).not.toHaveBeenCalled();
  });
  it('queues authenticated jobs and never follows backend redirects', async () => {
    vi.stubEnv('CRON_SECRET', 'a'.repeat(40));
    vi.stubEnv('API_INTERNAL_URL', 'https://api.example');
    const fetch = vi
      .fn()
      .mockResolvedValue(Response.json({ id: 'job-123', status: 'QUEUED' }, { status: 202 }));
    vi.stubGlobal('fetch', fetch);
    const result = await GET(
      new Request('https://meraipo.example/api/cron/results', {
        headers: { Authorization: 'Bearer ' + 'a'.repeat(40) },
      }),
      { params: Promise.resolve({ job: 'results' }) },
    );
    expect(result.status).toBe(202);
    expect(fetch).toHaveBeenCalledWith(
      'https://api.example/api/v1/internal/cron/results',
      expect.objectContaining({ method: 'POST', redirect: 'error', cache: 'no-store' }),
    );
    expect(await result.json()).toEqual({ id: 'job-123', status: 'QUEUED' });
  });
});
