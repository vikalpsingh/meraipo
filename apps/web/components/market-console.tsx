'use client';

import { useCallback, useEffect, useState } from 'react';
import { human, timestamp } from '@/lib/format';
import type { Company } from '@/lib/types';

type Run = {
  id: string;
  job_name: string;
  status: string;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  counters: Record<string, number> | null;
};
type Overview = {
  driver: string;
  staging: Record<string, number>;
  enabled: boolean;
  configuration_error: string | null;
  setup: { label: string; ready: boolean; setting: string }[];
  providers: {
    kind: string;
    name: string;
    authority: string;
    enabled: boolean;
    credential_set: boolean;
    health: string;
    last_fetched: string | null;
  }[];
  jobs: {
    name: string;
    label: string;
    schedule: string;
    paused: boolean;
    last: Run | null;
    next_run: string | null;
  }[];
  runs: Run[];
  errors: { id: string; provider: string; item: string; code: string; detail: string }[];
};

async function fetchOverview(): Promise<Overview> {
  const response = await fetch('/api/v1/admin/market', { cache: 'no-store' });
  if (!response.ok) throw new Error('Scheduler status unavailable. Refresh or sign in again.');
  return response.json();
}

export function MarketConsole({ csrf, companies }: { csrf: string; companies: Company[] }) {
  const [data, setData] = useState<Overview | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const load = useCallback(async () => {
    setData(await fetchOverview());
  }, []);
  useEffect(() => {
    let active = true;
    const refresh = () =>
      fetchOverview()
        .then((result) => {
          if (active) setData(result);
        })
        .catch((error: Error) => {
          if (active) setMessage(error.message);
        });
    refresh();
    const timer = setInterval(refresh, 15000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  async function action(job: string, operation: string, body: object) {
    setBusy(true);
    setMessage('');
    try {
      const response = await fetch(`/api/v1/admin/market/${job}/${operation}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify(body),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error?.message || 'Could not update scheduler');
      setMessage(
        operation === 'run'
          ? 'Request queued. Results will appear here when the worker finishes.'
          : 'Schedule preference saved.',
      );
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Request failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="market-heading">
      <div className="section-heading">
        <div>
          <h2 id="market-heading">Data & scheduler</h2>
          <p className="muted">
            All times are India Standard Time. Your public pages keep the last successfully imported
            data.
          </p>
        </div>
        <button
          className="outline-button"
          disabled={busy}
          onClick={() => load().catch((error: Error) => setMessage(error.message))}
        >
          Refresh status
        </button>
      </div>
      {message && (
        <p role="status" className="notice">
          {message}
        </p>
      )}
      {!data ? (
        <p>Loading scheduler…</p>
      ) : (
        <>
          <div className="panel">
            <h3>
              {data.enabled ? 'Scheduling enabled' : 'Finish setup to start automatic updates'}
            </h3>
            <p>
              Keep Docker running for automatic collection and publication. Scheduler:{' '}
              {data.driver === 'celery' ? 'Docker / Celery' : 'Vercel'}. Collect jobs save source
              records; publish jobs update the website.
            </p>
            <ul className="setup-list">
              {data.setup.map((item) => (
                <li key={item.label}>
                  <strong>
                    {item.ready ? '✓ Configured' : '○ Needs setup'} · {item.label}
                  </strong>
                  <span className="muted">{item.setting}</span>
                </li>
              ))}
            </ul>
            {data.configuration_error && <p role="alert">{data.configuration_error}</p>}
            <details>
              <summary>Provider setup and safety</summary>
              <p>
                Set provider URLs and credentials in the API and worker environment, then restart
                both services. NSE/BSE provide exchange data; GMP needs a separate unofficial source
                or an admin entry. Financial filings need a reviewed source mapping and XBRL
                taxonomy.
              </p>
              {data.providers.length ? (
                <ul>
                  {data.providers.map((provider) => (
                    <li key={`${provider.kind}:${provider.name}`}>
                      {provider.name} · {human(provider.kind)} · {provider.authority} ·{' '}
                      {human(provider.health)} · Last fetched {timestamp(provider.last_fetched)} ·{' '}
                      {provider.enabled ? 'Enabled' : 'Disabled'} ·{' '}
                      {provider.credential_set ? 'Credential configured' : 'No credential set'}
                    </li>
                  ))}
                </ul>
              ) : (
                <p>
                  No automatic feed is configured. Manual IPO, GMP and results entry remains
                  available.
                </p>
              )}
              <p>
                Configuration confirms settings only. A successful run with imported records
                confirms connectivity. Financial results update when filings arrive; no new filings
                is normal.
              </p>
            </details>
          </div>
          <p className="notice">
            {data.staging.PENDING || 0} awaiting publication · {data.staging.REJECTED || 0} rejected
            · {data.staging.PUBLISHED || 0} published. Collection does not change public data.
          </p>
          <label>
            <input
              type="checkbox"
              checked={advanced}
              onChange={(event) => setAdvanced(event.target.checked)}
            />{' '}
            Show collection, publication and legacy tools (manual only)
          </label>
          <div className="scheduler-grid">
            {data.jobs
              .filter(
                (job) =>
                  job.name !== 'backfill' &&
                  (advanced || job.name.startsWith('collect-') || job.name.startsWith('publish-')),
              )
              .map((job) => (
                <article className="panel" key={job.name}>
                  <div className="section-heading">
                    <h3>{job.label}</h3>
                    <span className="badge">
                      {job.paused ? 'Paused' : job.last ? human(job.last.status) : 'Not run yet'}
                    </span>
                  </div>
                  <p>{job.schedule} IST</p>
                  {job.next_run && (
                    <p className="muted">Next scheduled: {timestamp(job.next_run)}</p>
                  )}
                  <p className="muted">
                    Last attempt: {job.last ? timestamp(job.last.created_at) : 'None'}
                  </p>
                  {job.last?.counters && (
                    <p>
                      {job.last.counters.written || 0} saved · {job.last.counters.failed || 0}{' '}
                      errors
                    </p>
                  )}
                  {job.last?.error && <p className="small">{job.last.error}</p>}
                  <div className="scheduler-actions">
                    <button
                      className="primary-button"
                      aria-label={`Run ${job.label.toLowerCase()}`}
                      disabled={
                        busy ||
                        job.paused ||
                        job.last?.status === 'QUEUED' ||
                        job.last?.status === 'RUNNING'
                      }
                      onClick={() => action(job.name, 'run', {})}
                    >
                      Run now
                    </button>
                    {job.name.startsWith('publish-') && data.staging.REJECTED > 0 && (
                      <button
                        className="outline-button"
                        disabled={
                          busy ||
                          job.paused ||
                          job.last?.status === 'QUEUED' ||
                          job.last?.status === 'RUNNING'
                        }
                        onClick={() => action(job.name, 'run', { retry_rejected: true })}
                      >
                        Retry rejected
                      </button>
                    )}
                    <button
                      className="outline-button"
                      disabled={busy}
                      onClick={() => action(job.name, 'pause', { paused: !job.paused })}
                    >
                      {job.paused ? 'Resume' : 'Pause'}
                    </button>
                  </div>
                </article>
              ))}
          </div>
          <details className="panel">
            <summary>Refresh one company or backfill history</summary>
            <form
              className="form-grid"
              onSubmit={(event) => {
                event.preventDefault();
                const values = new FormData(event.currentTarget);
                action(String(values.get('job')), 'run', { company_id: values.get('company') });
              }}
            >
              <label>
                Refresh company
                <select name="company" required>
                  <option value="">Choose company</option>
                  {companies
                    .filter((company) => !company.is_demo)
                    .map((company) => (
                      <option key={company.id} value={company.id}>
                        {company.name}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                Data to refresh
                <select name="job">
                  <option value="results">Latest financial filings</option>
                  <option value="eod-prices">Latest closing price</option>
                  <option value="ipo-live">Subscription & GMP</option>
                </select>
              </label>
              <button className="primary-button" disabled={busy}>
                Refresh selected company
              </button>
            </form>
            <p>
              Start with the latest eight quarters and four financial years. Import one year at a
              time; existing records are safely deduplicated.
            </p>
            <form
              className="form-grid"
              onSubmit={(event) => {
                event.preventDefault();
                const values = new FormData(event.currentTarget);
                action('backfill', 'run', {
                  company_id: values.get('company'),
                  from_date: values.get('from'),
                  to_date: values.get('to'),
                  confirm_backfill: values.get('confirm') === 'on',
                });
              }}
            >
              <label>
                Company
                <select name="company" required>
                  <option value="">Choose company</option>
                  {companies
                    .filter((company) => !company.is_demo)
                    .map((company) => (
                      <option key={company.id} value={company.id}>
                        {company.name}
                      </option>
                    ))}
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
              <label className="full">
                <input name="confirm" type="checkbox" required /> I confirm this bounded import may
                use provider quota.
              </label>
              <button className="primary-button" disabled={busy}>
                Queue historical import
              </button>
            </form>
          </details>
          <details className="panel">
            <summary>Recent runs and errors ({data.runs.length})</summary>
            {data.runs.length === 0 ? (
              <p>No jobs have run yet.</p>
            ) : (
              <ul className="run-list">
                {data.runs.map((run) => (
                  <li key={run.id}>
                    <strong>
                      {human(run.job_name)} · {human(run.status)}
                    </strong>
                    <span>
                      {timestamp(run.created_at)}
                      {run.started_at && run.finished_at
                        ? ` · ${Math.max(0, Math.round((Date.parse(run.finished_at) - Date.parse(run.started_at)) / 1000))}s`
                        : ''}
                    </span>
                    {run.error && <span>{run.error}</span>}
                  </li>
                ))}
              </ul>
            )}
            {data.errors.map((error) => (
              <p key={error.id}>
                <strong>
                  {error.provider} · {error.code}
                </strong>
                <br />
                {error.item}: {error.detail}
              </p>
            ))}
          </details>
        </>
      )}
    </section>
  );
}
