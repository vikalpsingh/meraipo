import { notFound } from 'next/navigation';
import { EmailSubscription } from '@/components/email-subscription';
export const metadata = {
  title: 'Email preferences',
  robots: { index: false, follow: false },
  referrer: 'no-referrer' as const,
};
export default async function Page({ params }: { params: Promise<{ action: string }> }) {
  const { action } = await params;
  if (!['verify', 'unsubscribe'].includes(action)) notFound();
  return (
    <main className="container">
      <EmailSubscription action={action} />
    </main>
  );
}
