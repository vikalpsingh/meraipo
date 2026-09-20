import { api } from '@/lib/api';
import { calendar } from '@/lib/applicant';
import type { Company } from '@/lib/types';
export const dynamic = 'force-dynamic';
export async function GET(_request: Request, { params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug)) return new Response('Not found', { status: 404 });
  try {
    const c = await api<Company>('/companies/' + slug);
    return new Response(calendar(c), {
      headers: {
        'Content-Type': 'text/calendar; charset=utf-8',
        'Content-Disposition': `attachment; filename="${slug}-ipo.ics"`,
        'Cache-Control': 'no-store',
      },
    });
  } catch (error) {
    return new Response('Calendar unavailable', {
      status: error instanceof Error && error.message === 'NOT_FOUND' ? 404 : 503,
    });
  }
}
