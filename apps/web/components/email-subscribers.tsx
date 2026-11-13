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
const statuses: Record<string, { meaning: string; action: string }> = {
  Active: {
    meaning:
      'Email confirmed; eligible for alerts matching the saved preference when production sending is enabled.',
    action: 'No confirmation action needed.',
  },
  'Pending confirmation': {
    meaning:
      'Signup saved, but the email address has not been confirmed. Scheduled alerts are not sent.',
    action:
      'Ask the user to check their inbox and spam folder and click the confirmation link. Saving a signup does not prove the confirmation email was delivered.',
  },
  Unsubscribed: {
    meaning: 'The user opted out. Scheduled alerts are not sent.',
    action: 'The user must subscribe again and confirm their email to resume alerts.',
  },
  Suppressed: {
    meaning: 'Sending is blocked by the email suppression system.',
    action: 'Review delivery, bounce and complaint records before taking action.',
  },
};
export function EmailSubscribers({ csrf }: { csrf: string }) {
  const [reminderBusy, setReminderBusy] = useState(false);
  const [reminderMessage, setReminderMessage] = useState('');
  const [reviewed, setReviewed] = useState(false);
  async function remind() {
    setReminderBusy(true);
    setReminderMessage('');
    try {
      const response = await fetch('/api/v1/admin/email/subscribers/remind', {
        method: 'POST',
        headers: { 'X-CSRF-Token': csrf },
      });
      const result = await response.json();
      if (!response.ok)
        throw new Error(result.error?.message || result.detail || 'Could not queue reminders.');
      setReminderMessage(result.message);
      setReviewed(false);
    } catch (e) {
      setReminderMessage(e instanceof Error ? e.message : 'Could not queue reminders.');
    } finally {
      setReminderBusy(false);
    }
  }
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
      <details className="admin-status-guide">
        <summary>What do subscriber statuses mean?</summary>
        <div
          className="admin-table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Subscriber status meanings"
        >
          <table>
            <caption>Status meanings and next steps</caption>
            <thead>
              <tr>
                <th scope="col">Status</th>
                <th scope="col">Meaning</th>
                <th scope="col">Next step</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(statuses).map(([status, info]) => (
                <tr key={status}>
                  <th scope="row">{status}</th>
                  <td>{info.meaning}</td>
                  <td>{info.action}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      <div className="panel">
        <h3>Confirmation reminders</h3>
        <p>
          Every Monday at 9:00 AM IST, pending users receive a fresh confirmation link, for up to
          three weekly reminders after registration. This button queues all eligible pending users
          across all pages, with the same weekly limit. It never marks an address confirmed.
        </p>
        <label>
          <input
            type="checkbox"
            checked={reviewed}
            onChange={(e) => setReviewed(e.target.checked)}
          />{' '}
          I have reviewed the pending registrations and want to send eligible confirmation
          reminders.
        </label>
        <button className="outline-button" disabled={!reviewed || reminderBusy} onClick={remind}>
          {reminderBusy ? 'Queuing…' : 'Send bulk confirmation reminders'}
        </button>
        <p role="status">{reminderMessage}</p>
      </div>
      {busy && <p role="status">Loading subscribers…</p>}
      {error && <p role="alert">{error}</p>}
      {data && (
        <>
          <div
            className="admin-table-scroll"
            tabIndex={0}
            role="region"
            aria-label="Subscriber counts"
          >
            <table>
              <caption>Registration summary</caption>
              <thead>
                <tr>
                  <th scope="col">Registration status</th>
                  <th scope="col">Users</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.counts).map(([label, count]) => (
                  <tr key={label}>
                    <th scope="row">
                      {{
                        total: 'Total registered',
                        active: 'Active',
                        pending: 'Pending confirmation',
                        unsubscribed: 'Unsubscribed',
                        suppressed: 'Suppressed',
                      }[label] || label}
                    </th>
                    <td>{count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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
          <div
            className="admin-table-scroll"
            tabIndex={0}
            role="region"
            aria-label="Subscriber directory"
          >
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
                    <td>
                      <strong>{row.status}</strong>
                      <small className="admin-cell-help">{statuses[row.status]?.meaning}</small>
                    </td>
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
