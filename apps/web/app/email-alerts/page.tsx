import { features } from '@/lib/features';
import { api } from '@/lib/api';
import type { Company } from '@/lib/types';
import { notFound } from 'next/navigation';
import { ListingGainSubscription } from '@/components/listing-gain-subscription';
export const dynamic = 'force-dynamic';
export const metadata = { title: 'IPO Alerts', robots: { index: false, follow: false } };
export default async function Page() {
  if (!(await features()).email_alerts) notFound();
  const open = await api<{ items: Company[] }>('/ipos/open');
  const now = new Date();
  return (
    <main className="container">
      <ListingGainSubscription companies={open.items} asOf={now.getTime()} />
    </main>
  );
}
