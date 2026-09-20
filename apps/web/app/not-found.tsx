import Link from 'next/link';
export default function NotFound() {
  return (
    <main className="empty">
      <h1>Company or page not found.</h1>
      <p>This record may not be available yet.</p>
      <Link className="primary-button" href="/tracker">
        Back to IPO Tracker
      </Link>
    </main>
  );
}
