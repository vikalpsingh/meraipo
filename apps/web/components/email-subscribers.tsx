'use client';
import { useEffect, useState } from 'react';
import { timestamp } from '@/lib/format';
type Data = {
  items: {
    id: string;
    first_name: string | null;
    last_name: string | null;
    email: string;
    gmp_band: string | null;
    status: string;
    created_at: string;
  }[];
  counts: Record<string, number>;
  page: number;
  pages: number;
};
const bands: Record<string, string> = {
  white: 'All IPOs',
  light_green: 'Above 20%',
  strong_green: 'Above 40%',
  gold: 'Above 100%',
};
export function EmailSubscribers() {
  const [data, setData] = useState<Data | null>(null);
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(20);
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      setBusy(true);
      setError('');
      setData(null);
      try {
        const response = await fetch(
          `/api/v1/admin/email/subscribers?page=${page}&page_size=${size}`,
          { cache: 'no-store', signal: controller.signal },
        );
        if (!response.ok) throw new Error('Could not load subscribers. Refresh or sign in again.');
        const result = await response.json();
        if (!controller.signal.aborted) setData(result);
      } catch (e) {
        if (!controller.signal.aborted)
          setError(e instanceof Error ? e.message : 'Could not load subscribers.');
      } finally {
        if (!controller.signal.aborted) setBusy(false);
      }
    }
    void load();
    return () => controller.abort();
  }, [page, size, refresh]);
  return (
    <section className="panel" aria-labelledby="subscribers-heading">
      <div className="section-heading">
        <h2 id="subscribers-heading">Email subscribers</h2>
        <button className="outline-button" disabled={busy} onClick={() => setRefresh((v) => v + 1)}>
          Refresh subscribers
        </button>
      </div>
      <p>
        Registered IPO alert users, newest first. Test-only recipients are excluded. Pending users
        must confirm their email before receiving alerts.
      </p>
      {busy && <p role="status">Loading subscribers…</p>}
      {error && <p role="alert">{error}</p>}
      {data && (
        <>
          <dl className="job-facts">
            {Object.entries(data.counts).map(([label, count]) => (
              <div key={label}>
                <dt>{label === 'total' ? 'Total registered' : label}</dt>
                <dd>{count}</dd>
              </div>
            ))}
          </dl>
          <label>
            Rows per page{' '}
            <select
              value={size}
              onChange={(e) => {
                setSize(Number(e.target.value));
                setPage(1);
              }}
            >
              {[10, 20, 50, 100].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <div style={{ overflowX: 'auto' }}>
            <table>
              <caption>Subscriber names, email addresses and alert preferences</caption>
              <thead>
                <tr>
                  <th>First name</th>
                  <th>Last name</th>
                  <th>Email</th>
                  <th>GMP preference</th>
                  <th>Status</th>
                  <th>Registered (IST)</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.id}>
                    <td>{row.first_name || '—'}</td>
                    <td>{row.last_name || '—'}</td>
                    <td>{row.email}</td>
                    <td>{bands[row.gmp_band || ''] || 'Not selected'}</td>
                    <td>{row.status}</td>
                    <td>{timestamp(row.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!data.items.length && <p>No registered subscribers yet.</p>}
          <nav className="job-actions" aria-label="Subscriber pagination">
            <button
              className="outline-button"
              disabled={data.page <= 1}
              onClick={() => setPage(data.page - 1)}
            >
              Previous
            </button>
            <span aria-live="polite">
              Page {data.page} of {data.pages}
            </span>
            <button
              className="outline-button"
              disabled={data.page >= data.pages}
              onClick={() => setPage(data.page + 1)}
            >
              Next
            </button>
          </nav>
        </>
      )}
    </section>
  );
}
