import type { MetadataRoute } from 'next';
import { api } from '@/lib/api';
import type { Company, TrackerResult } from '@/lib/types';
export const dynamic = 'force-dynamic';
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const origin = process.env.SITE_URL || 'http://localhost:3000';
  const routes = [
    '',
    '/tracker',
    '/about',
    '/methodology',
    '/data-sources',
    '/disclaimer',
    '/privacy',
    '/terms',
    '/contact',
    '/feedback',
  ];
  const [open, upcoming, recent] = await Promise.all(
    ['open', 'upcoming', 'recent'].map((status) => api<{ items: Company[] }>('/ipos/' + status)),
  );
  const slugs = new Set([...open.items, ...upcoming.items, ...recent.items].map((c) => c.slug));
  let page = 1;
  let total = 0;
  do {
    const result = await api<TrackerResult>(`/tracker?page=${page}&page_size=100`);
    result.items.forEach((c) => slugs.add(c.slug));
    total = result.total;
    page++;
  } while ((page - 1) * 100 < total);
  return [
    ...routes.map((path) => ({ url: origin + path })),
    ...[...slugs].map((slug) => ({ url: origin + '/ipo/' + slug })),
  ];
}
