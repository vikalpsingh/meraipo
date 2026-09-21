import Link from 'next/link';
import { FeedbackBoard } from './feedback-board';

export const metadata = {
  title: 'Share feedback | MeraIPO',
  description: 'Suggest improvements to MeraIPO and vote for the features you want next.',
  alternates: { canonical: '/feedback' },
};

export default function FeedbackPage() {
  return (
    <main>
      <div className="page-heading">
        <div>
          <p className="eyebrow">BUILT WITH YOUR INPUT</p>
          <h1>
            Help shape MeraIPO<span>.</span>
          </h1>
          <p>Tell us what would make your IPO research easier. Support ideas that matter to you.</p>
        </div>
        <Link href="/" className="outline-button">
          Back to IPOs
        </Link>
      </div>
      <FeedbackBoard />
    </main>
  );
}
