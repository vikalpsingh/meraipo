'use client';

import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import type { Company } from '@/lib/types';

type Source = {
  exchange: string;
  enabled: boolean;
  status: string;
  url_template: string;
  verified_on: string | null;
  public_display_allowed: boolean;
  calendar_year: number;
  holidays: string[];
  special_sessions: string[];
  calendar_source: string;
  last_success: { created_at: string } | null;
};
type File = {
  id: string;
  exchange: string;
  trade_date: string;
  status: string;
  error: string | null;
  counters: Record<string, number> | null;
};
type Overview = { sources: Source[]; files: File[] };

export function BhavcopyConsole({ csrf, companies }: { csrf: string; companies: Company[] }) {
  const [data, setData] = useState<Overview | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [prices, setPrices] = useState<
    { trade_date: string; exchange: string; close: number; previous_close: number | null }[]
  >([]);
  const [preview, setPreview] = useState<{
    id: string;
    exchange: string;
    day: string;
    counters: Record<string, number>;
    sample: { symbol: string; isin: string; close: number }[];
  } | null>(null);
  async function load() {
    const response = await fetch('/api/v1/admin/bhavcopy', { cache: 'no-store' });
    if (!response.ok) throw new Error('Closing-price status unavailable');
    setData(await response.json());
  }
  useEffect(() => {
    let active = true;
    const refresh = () =>
      fetch('/api/v1/admin/bhavcopy', { cache: 'no-store' })
        .then(async (response) => {
          if (!response.ok) throw new Error('Closing-price status unavailable');
          const result = await response.json();
          if (active) setData(result);
        })
        .catch((e: Error) => {
          if (active) setMessage(e.message);
        });
    void refresh();
    const timer = setInterval(refresh, 15000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);
  async function request(path: string, body: object, method = 'POST') {
    const response = await fetch(`/api/v1/admin/bhavcopy${path}`, {
      method,
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      body: JSON.stringify(body),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error?.message || result.detail || 'Request failed');
    return result;
  }
  async function perform(task: () => Promise<void>) {
    setBusy(true);
    setMessage('');
    try {
      await task();
      await load();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Request failed');
    } finally {
      setBusy(false);
    }
  }
  function saveSource(event: FormEvent<HTMLFormElement>, source: Source) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const split = (key: string) =>
      String(form.get(key) || '')
        .split(',')
        .map((v) => v.trim())
        .filter(Boolean);
    const configs = Object.fromEntries(
      (data?.sources || []).map((s) => [
        s.exchange,
        {
          enabled: s.enabled,
          url_template: s.url_template,
          verified_on: s.verified_on,
          public_display_allowed: s.public_display_allowed,
          calendar_year: s.calendar_year,
          holidays: s.holidays,
          special_sessions: s.special_sessions,
          calendar_source: s.calendar_source,
        },
      ]),
    );
    configs[source.exchange] = {
      enabled: form.has('enabled'),
      url_template: String(form.get('url_template')),
      verified_on: String(form.get('verified_on')) || null,
      public_display_allowed: form.has('public_display_allowed'),
      calendar_year: Number(form.get('calendar_year')),
      holidays: split('holidays'),
      special_sessions: split('special_sessions'),
      calendar_source: String(form.get('calendar_source')),
    };
    void perform(async () => {
      await request('/sources', { sources_json: JSON.stringify(configs) }, 'PUT');
      setMessage('Exchange settings saved.');
    });
  }
  return (
    <section className="panel bhavcopy-console" aria-label="Exchange closing files">
      <h3>NSE / BSE daily closing files</h3>
      <p>
        Daily closing price sync runs at 19:00 Asia/Kolkata, with retries at 20:00 and 22:00.
        Original files expire after seven days; daily prices and corrections remain available.
        Prices are unadjusted.
      </p>
      {message && <p role="status">{message}</p>}
      <button className="primary-button" disabled={busy} onClick={() => void perform(load)}>
        Refresh closing-file status
      </button>
      {data?.sources.map((source) => (
        <details key={source.exchange}>
          <summary>
            {source.exchange} · {source.status} · Last import{' '}
            {source.last_success?.created_at || 'None'}
          </summary>
          <form className="form-grid" onSubmit={(e) => saveSource(e, source)}>
            <label>
              <input name="enabled" type="checkbox" defaultChecked={source.enabled} />
              Enable {source.exchange}
            </label>
            <label>
              Official URL template (use {'{yyyymmdd}'})
              <input name="url_template" defaultValue={source.url_template} />
            </label>
            <label>
              Completed session used to verify this URL
              <input name="verified_on" type="date" defaultValue={source.verified_on || ''} />
            </label>
            <p className="small full">
              Only mark a route verified after downloading and validating its official final UDiFF
              file. An inaccessible source can still be imported using the upload below.
            </p>
            <label>
              Calendar year
              <input name="calendar_year" type="number" defaultValue={source.calendar_year} />
            </label>
            <label>
              Official calendar reference
              <input name="calendar_source" defaultValue={source.calendar_source} />
            </label>
            <label>
              Holidays (comma-separated YYYY-MM-DD)
              <textarea name="holidays" defaultValue={source.holidays.join(',')} />
            </label>
            <label>
              Special trading sessions (comma-separated YYYY-MM-DD)
              <textarea name="special_sessions" defaultValue={source.special_sessions.join(',')} />
            </label>
            <label>
              <input
                name="public_display_allowed"
                type="checkbox"
                defaultChecked={source.public_display_allowed}
              />
              Public display rights confirmed for this exchange
            </label>
            <button className="primary-button" disabled={busy}>
              Save {source.exchange} settings
            </button>
          </form>
        </details>
      ))}
      <form
        className="form-grid"
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          void perform(async () => {
            await request('/run', {
              from_date: form.get('from_date'),
              to_date: form.get('to_date'),
              exchange: form.get('exchange') || null,
            });
            setMessage(
              'Daily closing sync queued for each selected date. Refresh status to see results.',
            );
          });
        }}
      >
        <h4 className="full">Run for a date or backfill up to 31 dates</h4>
        <label>
          Exchange
          <select name="exchange">
            <option value="">Both</option>
            <option>NSE</option>
            <option>BSE</option>
          </select>
        </label>
        <label>
          From
          <input required name="from_date" type="date" />
        </label>
        <label>
          To
          <input required name="to_date" type="date" />
        </label>
        <button className="primary-button" disabled={busy}>
          Queue closing-price sync
        </button>
      </form>
      <form
        className="form-grid"
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          const exchange = String(form.get('exchange')),
            day = String(form.get('trade_date'));
          setPreview(null);
          void perform(async () => {
            const response = await fetch(
              `/api/v1/admin/bhavcopy/preview?exchange=${exchange}&trade_date=${day}`,
              {
                method: 'POST',
                headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/octet-stream' },
                body: form.get('file') as Blob,
              },
            );
            const result = await response.json();
            if (!response.ok)
              throw new Error(result.error?.message || result.detail || 'Validation failed');
            setPreview({ ...result, exchange, day });
          });
        }}
      >
        <h4 className="full">Upload an original final UDiFF ZIP or CSV</h4>
        <label>
          Exchange
          <select name="exchange">
            <option>NSE</option>
            <option>BSE</option>
          </select>
        </label>
        <label>
          Trading date
          <input required name="trade_date" type="date" />
        </label>
        <label>
          Original file
          <input required name="file" type="file" accept=".zip,.csv" />
        </label>
        <button className="primary-button" disabled={busy}>
          Validate and preview
        </button>
      </form>
      {preview && (
        <div className="notice">
          <p>
            {preview.exchange} · {preview.day} ·{' '}
            {Object.entries(preview.counters)
              .map(([k, v]) => `${k}: ${v}`)
              .join(' · ')}
          </p>
          <a href={`/api/v1/admin/bhavcopy/${preview.id}/errors.csv`}>Download validation errors</a>{' '}
          <button
            className="primary-button"
            disabled={busy || !preview.counters.matched}
            onClick={() =>
              void perform(async () => {
                await request('/run', {
                  from_date: preview.day,
                  to_date: preview.day,
                  exchange: preview.exchange,
                  upload_id: preview.id,
                });
                setPreview(null);
                setMessage('Validated file queued for import.');
              })
            }
          >
            Import validated file
          </button>
        </div>
      )}
      <form
        className="form-grid"
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          void perform(async () => {
            const response = await fetch(
              `/api/v1/admin/bhavcopy/prices/${form.get('company_id')}?exchange=${form.get('exchange')}`,
              { cache: 'no-store' },
            );
            if (!response.ok) throw new Error('Private price preview unavailable');
            setPrices((await response.json()).items);
            setMessage(
              'Private unadjusted prices loaded. Public display follows the exchange permission setting.',
            );
          });
        }}
      >
        <h4 className="full">Private company price history</h4>
        <label>
          Listed company
          <select required name="company_id">
            {companies
              .filter((c) => c.status === 'LISTED' && !c.is_demo)
              .map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
          </select>
        </label>
        <label>
          Exchange
          <select name="exchange">
            <option>NSE</option>
            <option>BSE</option>
          </select>
        </label>
        <button className="primary-button" disabled={busy}>
          View stored closing prices
        </button>
      </form>
      {prices.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Exchange</th>
              <th>Close</th>
              <th>Previous close</th>
            </tr>
          </thead>
          <tbody>
            {prices.map((p) => (
              <tr key={`${p.exchange}-${p.trade_date}`}>
                <td>{p.trade_date}</td>
                <td>{p.exchange}</td>
                <td>{p.close}</td>
                <td>{p.previous_close ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <ul>
        {data?.files.slice(0, 20).map((file) => (
          <li key={file.id}>
            <strong>
              {file.exchange} · {file.trade_date} · {file.status}
            </strong>{' '}
            {file.error}
            {file.counters && (
              <p>
                {Object.entries(file.counters)
                  .map(([k, v]) => `${k}: ${v}`)
                  .join(' · ')}
              </p>
            )}
            <a href={`/api/v1/admin/bhavcopy/${file.id}/errors.csv`}>Error report</a>
          </li>
        ))}
      </ul>
    </section>
  );
}
