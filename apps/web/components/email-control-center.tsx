'use client';
import { useCallback, useEffect, useState } from 'react';
import type { Company } from '@/lib/types';
type Check = {
  ready: boolean;
  checks: Record<string, boolean>;
  aws: {
    status: string;
    ready: boolean;
    sender: string;
    checks: Record<string, boolean>;
    max_rate: number | null;
    remaining_quota: number | null;
    message?: string;
  };
};
type Status = {
  sending_enabled: boolean;
  readiness: Check;
  counts: Record<string, number>;
  subscribers: Record<string, number>;
  scheduler_seen_at: string | null;
  last_accepted_at: string | null;
  test: { id: string; status: string; delivered: boolean; received_confirmed: boolean } | null;
  last_run: {
    id: string;
    status: string;
    started_at: string;
    finished_at: string | null;
    processed: number;
    error_code: string | null;
  } | null;
  failures: {
    id: string;
    kind: string;
    status: string;
    attempts: number;
    code: string;
    retry_at: string | null;
    eligible_retry: boolean;
  }[];
};
const date = (value: string | null) =>
  value ? new Date(value).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }) + ' IST' : 'N/A';
export function EmailControlCenter({ csrf, companies }: { csrf: string; companies: Company[] }) {
  const [data, setData] = useState<Status | null>(null);
  const [days, setDays] = useState('30');
  const [ipo, setIpo] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<{ subject: string; html: string; text: string } | null>(
    null,
  );
  const refresh = useCallback(
    async (aws = false) => {
      const response = await fetch(`/api/v1/admin/email/status?days=${days}&refresh=${aws}`, {
        cache: 'no-store',
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error?.message || 'Email status unavailable');
      setData(body);
    },
    [days],
  );
  useEffect(() => {
    let active = true;
    // Fetch completion updates state asynchronously after the selected period changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh().catch((error) => {
      if (active) setMessage(error.message);
    });
    return () => {
      active = false;
    };
  }, [refresh]);
  async function action(path: string, method = 'POST', body?: unknown) {
    setBusy(true);
    setMessage('');
    try {
      const response = await fetch('/api/v1/admin/email/' + path, {
        method,
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const value = await response.json();
      if (!response.ok) throw new Error(value.error?.message || 'Request failed');
      if (path.startsWith('preview/')) setPreview(value);
      else {
        setMessage(value.message || 'Sending control saved.');
        await refresh();
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Request failed');
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel email-analytics">
      <h2>Email control centre</h2>
      <p>
        Pre-listing alerts · 08:00 IST by default · sender alerts@meraipo.com. Production sending
        stays off until readiness passes.
      </p>
      <div className="email-filters">
        <label>
          Operational period
          <select value={days} onChange={(e) => setDays(e.target.value)}>
            <option value="7">7 days</option>
            <option value="30">30 days</option>
            <option value="90">90 days</option>
          </select>
        </label>
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await refresh(true);
              setMessage('Status refreshed.');
            } catch {
              setMessage('Status unavailable.');
            } finally {
              setBusy(false);
            }
          }}
        >
          Refresh readiness and metrics
        </button>
      </div>
      <p role="status">{message}</p>
      {data && (
        <>
          <h3>Production dispatch</h3>
          <p>
            {data.sending_enabled ? 'Enabled · every dispatch still checks readiness' : 'Disabled'}
          </p>
          <button
            disabled={busy || (!data.sending_enabled && !data.readiness.ready)}
            role="switch"
            aria-checked={data.sending_enabled}
            onClick={() => action('sending', 'PUT', { enabled: !data.sending_enabled })}
          >
            {data.sending_enabled ? 'Disable production sending' : 'Enable production sending'}
          </button>
          <p>
            SES: {data.readiness.aws.status.replaceAll('_', ' ')} · {data.readiness.aws.sender}
          </p>
          <p>
            Quota remaining: {data.readiness.aws.remaining_quota ?? 'N/A'} · Maximum send rate:{' '}
            {data.readiness.aws.max_rate ?? 'N/A'}/second
          </p>
          <ul>
            {Object.entries({ ...data.readiness.checks, ...data.readiness.aws.checks }).map(
              ([key, value]) => (
                <li key={key}>
                  {key.replaceAll('_', ' ')}: {value ? 'Passed' : 'Not ready'}
                </li>
              ),
            )}
          </ul>
          <p>{data.readiness.aws.message}</p>
          <p>
            Scheduler heartbeat: {date(data.scheduler_seen_at)} · Last SES acceptance:{' '}
            {date(data.last_accepted_at)}
          </p>
          <h3>Subscribers</h3>
          <div className="email-kpis">
            {Object.entries(data.subscribers).map(([key, value]) => (
              <div className="panel" key={key}>
                {key}
                <strong>{value}</strong>
              </div>
            ))}
          </div>
          <h3>Campaign operations</h3>
          <p>
            TEST and confirmation emails are excluded. Accepted means SES accepted the request;
            delivered means the recipient mail server accepted it, not that someone read it.
          </p>
          <div className="email-kpis">
            {[
              'SCHEDULED',
              'PENDING',
              'UNSUBSCRIBED',
              'ATTEMPTED',
              'SES_ACCEPTED',
              'DELIVERED',
              'FAILED',
              'UNCERTAIN',
              'RETRY',
              'REJECTED',
              'BOUNCED',
              'COMPLAINT',
              'DELAYED',
              'SOFT_BOUNCE',
              'SUPPRESSED',
              'CANCELLED',
            ].map((key) => (
              <div className="panel" key={key}>
                {key.replaceAll('_', ' ')}
                <strong>{data.counts[key] || 0}</strong>
              </div>
            ))}
          </div>
          <h3>Preview and test</h3>
          <label>
            IPO
            <select
              value={ipo}
              onChange={(e) => {
                setIpo(e.target.value);
                setPreview(null);
              }}
            >
              <option value="">Select an IPO</option>
              {companies.map((c) => (
                <option key={c.ipo_id} value={c.ipo_id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <div className="email-filters">
            <button disabled={!ipo || busy} onClick={() => action('preview/' + ipo, 'GET')}>
              Preview HTML and text
            </button>
            <button
              disabled={!ipo || !preview || busy}
              onClick={() => action('test', 'POST', { ipo_id: ipo })}
            >
              Send one TEST to my admin email
            </button>
          </div>
          <p>
            A test sends only to your administrator email. SES sandbox requires a verified
            recipient. This does not enable production sending.
          </p>
          {preview && (
            <details open>
              <summary>{preview.subject}</summary>
              <iframe
                title="Test email preview"
                sandbox=""
                srcDoc={preview.html}
                style={{ width: '100%', minHeight: 540, border: '1px solid #ddd' }}
              />
              <h4>Plain text</h4>
              <pre style={{ whiteSpace: 'pre-wrap' }}>{preview.text}</pre>
            </details>
          )}
          {data.test && (
            <p>
              Latest test: {data.test.status} ·{' '}
              {data.test.received_confirmed
                ? 'Inbox receipt confirmed'
                : 'Receipt not yet confirmed'}{' '}
              <button
                disabled={busy || !data.test.delivered || data.test.received_confirmed}
                onClick={() => action(`test/${data.test!.id}/received`)}
              >
                I received this test in my inbox
              </button>
            </p>
          )}
          <h3>Last dispatch</h3>
          {data.last_run ? (
            <p>
              {data.last_run.id} · {data.last_run.status} · {data.last_run.processed} processed ·{' '}
              {date(data.last_run.finished_at)} · {data.last_run.error_code || 'No recorded error'}
            </p>
          ) : (
            <p>No dispatch recorded.</p>
          )}
          <h3>Recent failures</h3>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Delivery ID</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Attempts</th>
                  <th>Reason</th>
                  <th>Retry</th>
                </tr>
              </thead>
              <tbody>
                {data.failures.map((row) => (
                  <tr key={row.id}>
                    <td>{row.id}</td>
                    <td>{row.kind}</td>
                    <td>{row.status}</td>
                    <td>{row.attempts}</td>
                    <td>{row.code}</td>
                    <td>
                      {date(row.retry_at)}
                      {row.eligible_retry && (
                        <button disabled={busy} onClick={() => action('retry/' + row.id)}>
                          Retry eligible delivery
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>Uncertain sends are never blindly retried. Reconcile their SES events first.</p>
        </>
      )}
    </section>
  );
}
