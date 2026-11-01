import { features } from '@/lib/features';
import { notFound } from 'next/navigation';
import { EmailSubscription } from '@/components/email-subscription';
export const metadata = { title: 'IPO email alerts', robots: { index: false, follow: false } };
export default async function Page() {
  if (!(await features()).email_alerts) notFound();
  return (
    <main className="container">
      <EmailSubscription />
    </main>
  );
}
