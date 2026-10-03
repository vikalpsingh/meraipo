'use client';
import { useEffect, useState } from 'react';

type Data = {
  today: string;
  timezone: string;
  retention_days: number;
  totals: { today: number; week: number; month: number };
  daily: { day: string; section: string; clicks: number }[];
};
type Period = 'Daily' | 'Weekly' | 'Monthly';
const sections = ['home', 'ipos', 'company', 'tracker', 'feedback', 'information', 'other'];
function periodKey(day: string, period: Period) {
  if (period === 'Monthly') return day.slice(0, 7);
  if (period === 'Daily') return day;
  const date = new Date(day + 'T00:00:00Z');
  date.setUTCDate(date.getUTCDate() - ((date.getUTCDay() + 6) % 7));
  return date.toISOString().slice(0, 10);
}
export function ClickAnalytics() {
  const [data, setData] = useState<Data | null>(null);
  const [period, setPeriod] = useState<Period>('Daily');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(true);
  async function refresh() {
    setBusy(true);
    setError('');
    try {
      const response = await fetch('/api/v1/admin/analytics', { cache: 'no-store' });
      if (!response.ok) throw new Error('Could not load click analytics. Please sign in or retry.');
      setData(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Analytics unavailable');
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/v1/admin/analytics', { cache: 'no-store', signal: controller.signal })
      .then(async (response) => {
        if (!response.ok)
          throw new Error('Could not load click analytics. Please sign in or retry.');
        const result: Data = await response.json();
        if (!controller.signal.aborted) setData(result);
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setError(error instanceof Error ? error.message : 'Analytics unavailable');
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    return () => controller.abort();
  }, []);
  const groups = new Map<string, Record<string, number>>();
  if (data) {
    // Include zero-activity days. Weeks start Monday; months are calendar months in IST.
    for (let offset = 0; offset < data.retention_days; offset++) {
      const day = new Date(data.today + 'T00:00:00Z');
      day.setUTCDate(day.getUTCDate() - offset);
      groups.set(periodKey(day.toISOString().slice(0, 10), period), {});
    }
    for (const row of data.daily) {
      const group = groups.get(periodKey(row.day, period))!;
      group[row.section] = (group[row.section] || 0) + row.clicks;
    }
  }
  const entries = [...groups].slice(0, period === 'Daily' ? 30 : period === 'Weekly' ? 12 : 13);
  return (
    <section aria-label="Click analytics">
      <div className="section-heading">
        <div>
          <h2>Site clicks</h2>
          <p>Link and button clicks, grouped by the page where the click happened.</p>
        </div>
        <button onClick={refresh} disabled={busy}>
          {busy ? 'Loading…' : 'Refresh'}
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
      {data && (
        <>
          <div className="click-analytics-totals">
            {(
              [
                ['Today', data.totals.today],
                ['This week', data.totals.week],
                ['This month', data.totals.month],
              ] as const
            ).map(([label, count]) => (
              <div key={label}>
                <span>{label}</span>
                <strong>{count.toLocaleString('en-IN')}</strong>
              </div>
            ))}
          </div>
          <p className="small">
            Indian time (IST). Weeks start Monday. Current periods are in progress.
          </p>
          <label>
            View{' '}
            <select value={period} onChange={(e) => setPeriod(e.target.value as Period)}>
              {(['Daily', 'Weekly', 'Monthly'] as const).map((p) => (
                <option key={p}>{p}</option>
              ))}
            </select>
          </label>
          {!data.daily.length && (
            <p>
              No clicks recorded yet. Tracking starts after deployment; previous traffic cannot be
              recovered.
            </p>
          )}
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>
                    {period === 'Weekly'
                      ? 'Week starting'
                      : period === 'Monthly'
                        ? 'Month'
                        : 'Date'}
                  </th>
                  <th>Total clicks</th>
                  {sections.map((s) => (
                    <th key={s}>{s === 'company' ? 'Company / IPO detail' : s}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {entries.map(([key, counts]) => (
                  <tr key={key}>
                    <td>{key}</td>
                    <td>
                      <strong>
                        {Object.values(counts)
                          .reduce((a, b) => a + b, 0)
                          .toLocaleString('en-IN')}
                      </strong>
                    </td>
                    {sections.map((s) => (
                      <td key={s}>{(counts[s] || 0).toLocaleString('en-IN')}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small">
            Anonymous daily totals retained for 400 days (at most 2,800 rows). No analytics cookies,
            visitor identifiers, URLs, or click text are stored. Admin-page activity is excluded.
            These are best-effort click counts, not unique visitors: blocked requests, Do Not Track,
            bots, or interrupted navigation can affect totals. Clicks are assigned to the day
            received; allow up to 15 seconds before refreshing.
          </p>
        </>
      )}
    </section>
  );
}
