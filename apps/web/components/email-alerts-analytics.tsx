'use client';
import { useEffect, useState } from 'react';
type Campaign = {
  ipo_id: string;
  name: string;
  listing_date: string | null;
  send_date: string;
  delivered: number;
  clickers: number;
  ctr: number | null;
  sessions: number | null;
  engagement_seconds: number | null;
  unsubscribes: number;
};
type Data = {
  start: string;
  end: string;
  enabled: boolean;
  sender: string | null;
  sending_configured: boolean;
  send_hour_ist: number;
  definitions: string;
  summary: string;
  metrics: Record<string, number | null>;
  operations: Record<string, number>;
  ga4: {
    status: string;
    message: string;
    fetched_at?: number;
    totals?: { sessions: number; engagedSessions: number; userEngagementDuration: number };
    returning_users?: number | null;
  };
  growth: { day: string; new: number; verified: number; sessions: number | null }[];
  rows: Campaign[];
  total_rows: number;
};
const number = (value: number | null | undefined, suffix = '') =>
  value == null ? 'N/A' : value.toLocaleString('en-IN', { maximumFractionDigits: 2 }) + suffix;
function todayIST() {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date());
}
function Chart({
  title,
  values,
}: {
  title: string;
  values: { label: string; value: number | null }[];
}) {
  const max = Math.max(1, ...values.map((v) => v.value || 0));
  return (
    <section className="panel email-chart">
      <h3>{title}</h3>
      <div className="email-chart-bars">
        {values.map((v) => (
          <div className="email-bar" key={v.label} title={`${v.label}: ${number(v.value)}`}>
            <span>{v.label}</span>
            <meter min={0} max={max} value={v.value || 0} aria-label={v.label} />
            <strong>{number(v.value)}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}
export function EmailAlertsAnalytics() {
  const [range, setRange] = useState('30');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [sort, setSort] = useState('sessions');
  const [direction, setDirection] = useState('desc');
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    let from = start,
      to = end;
    if (range !== 'custom') {
      to = todayIST();
      const date = new Date(to + 'T00:00:00Z');
      date.setUTCDate(date.getUTCDate() - Number(range) + 1);
      from = date.toISOString().slice(0, 10);
    }
    if (!from || !to) return;
    // Start loading when the selected query changes; the request below owns completion.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setBusy(true);
    setError('');
    fetch(
      '/api/v1/admin/email-analytics?' +
        new URLSearchParams({ start: from, end: to, sort, direction, page: String(page) }),
      { cache: 'no-store', signal: controller.signal },
    )
      .then(async (response) => {
        const result = await response.json();
        if (!response.ok) throw new Error(result.error?.message || 'Analytics unavailable');
        setData(result);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(err.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    return () => controller.abort();
  }, [range, start, end, sort, direction, page]);
  function order(key: string) {
    if (sort === key) setDirection(direction === 'asc' ? 'desc' : 'asc');
    else {
      setSort(key);
      setDirection('desc');
    }
  }
  const m = data?.metrics || {};
  const totals = data?.ga4.totals;
  const cards: [string, number | null | undefined, string][] = [
    ['Total subscribers', m.total_subscribers, ''],
    ['Active verified subscribers', m.active_subscribers, ''],
    ['New subscribers', m.new_subscribers, ''],
    ['Emails sent · SES accepted', m.sent, ''],
    ['Confirmed deliveries', m.delivered, ''],
    ['Delivery rate', m.delivery_rate, '%'],
    ['Open rate · tracking dependent', m.open_rate, '%'],
    ['Unique clickers / delivered', m.click_rate, '%'],
    ['Website sessions · GA4', totals?.sessions, ''],
    ['Returning users · GA4', data?.ga4.returning_users, ''],
    ['Unsubscribe rate', m.unsubscribe_rate, '%'],
    [
      'Engagement rate · GA4',
      totals?.sessions ? (100 * totals.engagedSessions) / totals.sessions : null,
      '%',
    ],
  ];
  const columns = [
    ['name', 'IPO'],
    ['send_date', 'First send (IST)'],
    ['delivered', 'Delivered'],
    ['clickers', 'Unique clickers'],
    ['ctr', 'CTR'],
    ['sessions', 'Site sessions'],
    ['unsubscribes', 'Unsubscribes'],
  ];
  return (
    <section className="email-analytics" aria-busy={busy}>
      <h2>Email Alerts Analytics</h2>
      <div className="email-filters">
        <label>
          Period (IST)
          <select
            value={range}
            onChange={(e) => {
              setRange(e.target.value);
              setPage(1);
            }}
          >
            {[
              ['1', 'Today'],
              ['7', '7 Days'],
              ['30', '30 Days'],
              ['90', '90 Days'],
              ['custom', 'Custom'],
            ].map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
        </label>
        {range === 'custom' && (
          <>
            <label>
              From
              <input
                type="date"
                value={start}
                onChange={(e) => {
                  setStart(e.target.value);
                  setPage(1);
                }}
              />
            </label>
            <label>
              Through
              <input
                type="date"
                value={end}
                onChange={(e) => {
                  setEnd(e.target.value);
                  setPage(1);
                }}
              />
            </label>
          </>
        )}
      </div>
      <p role="status">{busy ? 'Loading analytics…' : error}</p>
      {data && (
        <>
          <p>
            <strong>{data.enabled ? 'Email sending enabled' : 'Email sending disabled'}</strong> ·{' '}
            {data.start} – {data.end} (IST)
          </p>
          <p>
            Pre-listing reminders run after {String(data.send_hour_ist).padStart(2, '0')}:00 IST
            with the latest stored GMP. Sender: {data.sender || 'Not configured'}.{' '}
            {data.sending_configured
              ? 'Server sending configuration enabled; delivery still depends on SES verification and account access.'
              : 'SES setup required before enabling the feature in Feature releases.'}
          </p>
          <div className="email-kpis">
            {cards.map(([label, value, suffix]) => (
              <div className="panel" key={label}>
                <span>{label}</span>
                <strong>{number(value, suffix)}</strong>
              </div>
            ))}
          </div>
          <p>{data.summary}</p>
          <p className="muted">
            {data.ga4.message}
            {data.ga4.fetched_at &&
              ` Cached report fetched ${new Date(data.ga4.fetched_at * 1000).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })} IST.`}
          </p>
          <details>
            <summary>Metric definitions and delivery queue</summary>
            <p>{data.definitions}</p>
            <p>
              Delivery rate = confirmed / accepted. Open rate = opened delivered messages /
              delivered. Unsubscribe rate = distinct unsubscribing recipients / delivered. N/A means
              unavailable or no denominator. Open tracking may be affected by mail privacy proxies.
              GA4 returning users are not proof of a later return caused by this email.
            </p>
            <p>
              Pending: {data.operations.PENDING || 0} · Sending: {data.operations.SENDING || 0} ·
              Uncertain: {data.operations.UNCERTAIN || 0}. Uncertain sends need reconciliation
              before any retry.
            </p>
            <p>
              Total click events: {number(m.total_click_events)} · Suspected scanners:{' '}
              {number(m.suspected_bot_events)}.
            </p>
          </details>
          <div className="email-charts">
            <Chart
              title="Daily new subscribers"
              values={data.growth.map((r) => ({ label: r.day, value: r.new }))}
            />
            <Chart
              title="Cumulative verified subscribers"
              values={data.growth.map((r) => ({ label: r.day, value: r.verified }))}
            />
            <Chart
              title="Email funnel · sessions use activity dates"
              values={[
                { label: 'SES accepted', value: m.sent },
                { label: 'Delivered', value: m.delivered },
                { label: 'Unique clickers', value: m.clickers },
                { label: 'GA4 sessions', value: totals?.sessions ?? null },
              ]}
            />
            <Chart
              title="Daily email-attributed sessions"
              values={data.growth.map((r) => ({ label: r.day, value: r.sessions }))}
            />
          </div>
          <h3>IPO campaign performance</h3>
          <p>
            One row per IPO; sessions cover the selected activity dates. Engagement is GA4
            engagement seconds per session.
          </p>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  {columns.map(([key, label]) => (
                    <th
                      key={key}
                      aria-sort={
                        sort === key ? (direction === 'asc' ? 'ascending' : 'descending') : 'none'
                      }
                    >
                      <button type="button" onClick={() => order(key)}>
                        {label}
                        {sort === key ? (direction === 'asc' ? ' ↑' : ' ↓') : ' ↕'}
                      </button>
                    </th>
                  ))}
                  <th>Engagement / session</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.ipo_id}>
                    <td>
                      {r.name}
                      <small>Listing: {r.listing_date || 'Awaited'}</small>
                    </td>
                    <td>
                      {new Date(r.send_date).toLocaleDateString('en-IN', {
                        timeZone: 'Asia/Kolkata',
                      })}
                    </td>
                    <td>{number(r.delivered)}</td>
                    <td>{number(r.clickers)}</td>
                    <td>{number(r.ctr, '%')}</td>
                    <td>{number(r.sessions)}</td>
                    <td>{number(r.unsubscribes)}</td>
                    <td>{number(r.engagement_seconds, 's')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!data.total_rows && <p>No IPO alert messages were accepted in this date range.</p>}
          <div className="email-filters">
            <button disabled={page === 1 || busy} onClick={() => setPage(page - 1)}>
              Previous
            </button>
            <span>
              Page {page} of {Math.max(1, Math.ceil(data.total_rows / 20))}
            </span>
            <button
              disabled={page * 20 >= data.total_rows || busy}
              onClick={() => setPage(page + 1)}
            >
              Next
            </button>
          </div>
        </>
      )}
    </section>
  );
}
