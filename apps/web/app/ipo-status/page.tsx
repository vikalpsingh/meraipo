import { IPOStatusFrame } from '@/components/ipo-status-frame';

export const dynamic = 'force-dynamic';
export const metadata = {
  title: 'Check IPO bid / allotment status',
  alternates: { canonical: '/ipo-status' },
};

export default function IPOStatus() {
  return (
    <main>
      <div className="page-heading">
        <div>
          <p className="eyebrow">IPO STATUS</p>
          <h1>Check IPO bid / allotment status</h1>
          <p>
            Select your IPO on NSE and enter your PAN or application number. Bid verification
            confirms details received on NSE. Allotment information appears when provided by the
            registrar.
          </p>
        </div>
      </div>
      <IPOStatusFrame />
    </main>
  );
}
