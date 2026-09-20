'use client';
export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <main className="empty">
      <h1>Data is temporarily unavailable.</h1>
      <p>Your research records are safe. Please try again in a moment.</p>
      <button onClick={reset} className="primary-button">
        Try again
      </button>
    </main>
  );
}
