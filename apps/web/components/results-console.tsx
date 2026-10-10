'use client';
import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { human, timestamp } from '@/lib/format';
import { OfficialResultsSource } from './official-results-source';
type Filing = {
  id: string;
  exchange: string;
  identifier: string;
  status: string;
  error: string | null;
};
type Source = {
  exchange: string;
  schedule: string;
  enabled: boolean;
  status: string;
  last_success: string | null;
};
type Preview = {
  attachment_id?: string;
  checksum?: string;
  publishable?: boolean;
  error?: string;
  items: unknown[];
};
export function ResultsConsole({ csrf }: { csrf: string }) {
  const [data, setData] = useState<{
    sources: Source[];
    filings: Filing[];
    bse_companies?: { id: string; name: string }[];
    official_sources?: {
      company_id: string;
      page_url: string;
      document_prefix: string;
      enabled: boolean;
    }[];
  }>({
    sources: [],
    filings: [],
  });
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [filingId, setFilingId] = useState('');
  const [csv, setCsv] = useState<File | null>(null);
  async function request(path: string, body?: BodyInit, method = 'POST') {
    const response = await fetch('/api/v1/admin/' + path, {
      method,
      headers: {
        'X-CSRF-Token': csrf,
        ...(typeof body === 'string' ? { 'Content-Type': 'application/json' } : {}),
      },
      body,
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error?.message || result.detail || 'Request failed');
    return result;
  }
  async function load() {
    setData(await request('results', undefined, 'GET'));
  }
  useEffect(() => {
    let active = true;
    const refresh = () =>
      fetch('/api/v1/admin/results')
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error('Results status unavailable'))))
        .then((d) => {
          if (active) setData(d);
        })
        .catch((e) => {
          if (active) setMessage(e.message);
        });
    void refresh();
    const timer = setInterval(refresh, 15000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);
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
  function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    void perform(async () => {
      const r = await request(
        'results/filings',
        JSON.stringify({
          exchange: f.get('exchange'),
          identifier: f.get('identifier'),
          announced_at: f.get('announced_at'),
          basis: f.get('basis'),
          source_url: f.get('source_url'),
        }),
      );
      setFilingId(r.id);
      setPreview(null);
      setMessage('Filing registered. Upload its original to preview.');
    });
  }
  return (
    <section className="panel" aria-label="Financial results importer">
      <h2>Financial results importer</h2>
      <OfficialResultsSource
        csrf={csrf}
        companies={data.bse_companies || []}
        sources={data.official_sources || []}
      />
      <p>
        Configurable discovery and a rolling 14-day reconciliation. Originals and revisions are
        retained. Unverified figures require review.
      </p>
      {message && <p role="status">{message}</p>}
      {['BSE', 'NSE'].map((exchange) => {
        const s = data.sources.find((x) => x.exchange === exchange);
        return (
          <form
            key={exchange + String(s?.enabled) + s?.schedule}
            className="filters"
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              void perform(async () => {
                await request(
                  'results/sources/' + exchange,
                  JSON.stringify({ enabled: f.has('enabled'), schedule: f.get('schedule') }),
                  'PUT',
                );
              });
            }}
          >
            <strong>{exchange}</strong>
            <label>
              Enabled
              <input name="enabled" type="checkbox" defaultChecked={s?.enabled ?? true} />
            </label>
            <label>
              Time (IST)
              <input
                name="schedule"
                type="time"
                defaultValue={s?.schedule || (exchange === 'NSE' ? '21:00' : '22:00')}
                required
              />
            </label>
            <button disabled={busy}>Save {exchange} schedule</button>
            <span>
              {human(s?.status || 'NOT_YET_RUN')} · Last success {timestamp(s?.last_success)}
            </span>
          </form>
        );
      })}
      <p className="small">
        Run individual exchange discovery from Jobs &amp; schedules. Use a bounded historical range
        below for recovery.
      </p>
      <form
        className="filters"
        onSubmit={(e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          void perform(async () => {
            await request(
              `market/sync-results-${f.get('exchange')}/run`,
              JSON.stringify({
                from_date: f.get('from'),
                to_date: f.get('to'),
                company_id: f.get('company') || null,
                confirm_backfill: true,
              }),
            );
            setMessage('Backfill queued');
          });
        }}
      >
        <label>
          Exchange
          <select name="exchange">
            <option value="nse">NSE</option>
            <option value="bse">BSE</option>
          </select>
        </label>
        <label>
          From
          <input name="from" type="date" required />
        </label>
        <label>
          To
          <input name="to" type="date" required />
        </label>
        <label>
          Company ID (optional)
          <input name="company" />
        </label>
        <button disabled={busy}>Backfill results</button>
      </form>
      <details>
        <summary>Manual discovery and original filing upload</summary>
        <label>
          BSE discovery CSV
          <input
            type="file"
            accept=".csv"
            onChange={(e) => {
              setCsv(e.target.files?.[0] || null);
              setPreview(null);
            }}
          />
        </label>
        <button
          disabled={busy || !csv}
          onClick={() =>
            void perform(async () => setPreview(await request('results/discovery', csv!)))
          }
        >
          Preview discovery
        </button>
        {csv && preview && !preview.attachment_id && preview.items.length > 0 && (
          <button
            disabled={busy}
            onClick={() =>
              void perform(async () => {
                await request('results/discovery?apply=true', csv);
                setPreview(null);
                setMessage('Discovery saved for review');
              })
            }
          >
            Save discovery rows
          </button>
        )}
        <form className="form-grid" onSubmit={create}>
          <label>
            Exchange
            <select name="exchange">
              <option>BSE</option>
              <option>NSE</option>
            </select>
          </label>
          <label>
            Scrip code / symbol
            <input name="identifier" required />
          </label>
          <label>
            Filing timestamp with timezone
            <input name="announced_at" placeholder="2026-10-05T19:00:00+05:30" required />
          </label>
          <label>
            Basis
            <select name="basis">
              <option>STANDALONE</option>
              <option>CONSOLIDATED</option>
            </select>
          </label>
          <label>
            Official original URL
            <input name="source_url" type="url" required />
          </label>
          <button disabled={busy}>Register filing</button>
        </form>
        <form
          className="filters"
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            void perform(async () => {
              await request(
                'results/filings/' + encodeURIComponent(filingId) + '/mapping',
                JSON.stringify({ company_id: f.get('mappedCompany') }),
              );
              setMessage('Mapping saved; original identity will be cross-checked during parsing.');
            });
          }}
        >
          <label>
            Verified company ID for selected filing
            <input name="mappedCompany" required />
          </label>
          <button disabled={!filingId || busy}>Save verified mapping</button>
        </form>
        <label>
          Filing ID
          <input
            value={filingId}
            onChange={(e) => {
              setFilingId(e.target.value);
              setPreview(null);
            }}
          />
        </label>
        <label>
          Original XML / XBRL / PDF / Excel (up to 1 MB)
          <input
            type="file"
            accept=".xml,.xbrl,.pdf,.xlsx,.xls,.html"
            disabled={!filingId || busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file)
                void perform(async () =>
                  setPreview(
                    await request(
                      'results/filings/' + encodeURIComponent(filingId) + '/preview',
                      file,
                    ),
                  ),
                );
            }}
          />
        </label>
        {preview && (
          <>
            <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
              {JSON.stringify(preview, null, 2)}
            </pre>
            {preview.publishable && (
              <button
                disabled={busy}
                onClick={() =>
                  void perform(async () => {
                    await request(
                      'results/publish',
                      JSON.stringify({
                        attachment_id: preview.attachment_id,
                        checksum: preview.checksum,
                      }),
                    );
                    setPreview(null);
                    setMessage('Validated results published');
                  })
                }
              >
                Publish validated preview
              </button>
            )}
          </>
        )}
      </details>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th>Exchange / identifier</th>
              <th>Status</th>
              <th>Review</th>
            </tr>
          </thead>
          <tbody>
            {data.filings.map((f) => (
              <tr key={f.id}>
                <td>
                  {f.exchange} · {f.identifier}
                  <small>{f.id}</small>
                </td>
                <td>{human(f.status)}</td>
                <td>
                  {f.error || '—'}
                  <button
                    onClick={() => {
                      setFilingId(f.id);
                      setPreview(null);
                    }}
                  >
                    Select for upload
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
