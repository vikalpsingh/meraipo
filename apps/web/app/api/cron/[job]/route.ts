import { timingSafeEqual } from 'node:crypto';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
const jobs = new Set([
  'ipo-master',
  'ipo-live',
  'eod-prices',
  'results',
  'reconcile',
  'sync-ipos',
  'sync-prices',
  'sync-results',
  'collect-ipos',
  'collect-prices',
  'collect-results',
  'publish-ipos',
  'publish-prices',
  'publish-results',
]);

export async function GET(request: Request, context: { params: Promise<{ job: string }> }) {
  const secret = process.env.CRON_SECRET || '';
  const supplied = Buffer.from(request.headers.get('authorization') || '');
  const expected = Buffer.from(`Bearer ${secret}`);
  if (
    secret.length < 32 ||
    supplied.length !== expected.length ||
    !timingSafeEqual(supplied, expected)
  )
    return Response.json({ error: 'Unauthorized' }, { status: 401 });
  const { job } = await context.params;
  if (!jobs.has(job)) return Response.json({ error: 'Unknown job' }, { status: 404 });
  const api = process.env.API_INTERNAL_URL;
  if (!api) return Response.json({ error: 'API is not configured' }, { status: 503 });
  try {
    const response = await fetch(`${api}/api/v1/internal/cron/${job}`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${secret}` },
      signal: AbortSignal.timeout(8000),
      cache: 'no-store',
      redirect: 'error',
    });
    if (!response.ok)
      return Response.json(
        { error: 'Job could not be queued; check admin setup' },
        { status: 503 },
      );
    return Response.json(await response.json(), {
      status: 202,
      headers: { 'Cache-Control': 'no-store' },
    });
  } catch {
    return Response.json({ error: 'Scheduler backend unavailable' }, { status: 503 });
  }
}
