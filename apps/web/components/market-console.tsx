'use client';
import { useCallback, useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import type { Company } from '@/lib/types';
import { timestamp } from '@/lib/format';
import { BhavcopyConsole } from './bhavcopy-console';
import { ResultsConsole } from './results-console';
import { MarketConfig } from './market-config';
import { LegacyMarketConsole } from './legacy-market-console';
import { JobHistory, RunStatus } from './job-history';
import type { ScheduledJob } from './job-types';

type Overview = {
  enabled: boolean;
  driver: string;
  configuration_error: string | null;
  jobs: ScheduledJob[];
};
const sections = [
  ['jobs', 'Jobs & schedules'],
  ['history', 'Run history & errors'],
  ['prices', 'Price sources & recovery'],
  ['results', 'Results review & recovery'],
  ['config', 'Provider configuration'],
  ['advanced', 'Advanced tools'],
] as const;
type Section = (typeof sections)[number][0];

function JobCard({
  job,
  busy,
  action,
  inspect,
  configure,
}: {
  job: ScheduledJob;
  busy: boolean;
  action: (job: string, operation: string, body: object) => Promise<void>;
  inspect: (job: string, run?: string) => void;
  configure: () => void;
}) {
  const active = job.last?.status === 'QUEUED' || job.last?.status === 'RUNNING';
  const disabled = busy || active || job.paused || job.source_enabled === false;
  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    void action(job.name, 'schedule', {
      times: String(values.get('times'))
        .split(',')
        .map((v) => v.trim())
        .filter(Boolean),
      paused: job.paused,
    });
  }
  function backfill(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    void action(
      job.name,
      'run',
      job.name.includes('prices')
        ? { to_date: values.get('to') }
        : { from_date: values.get('from'), to_date: values.get('to') },
    );
  }
  return (
    <article className="job-card">
      <div className="job-card-heading">
        <div>
          <span className="eyebrow">{job.exchange || 'IPO DATA'}</span>
          <h3>{job.label}</h3>
        </div>
        <RunStatus status={job.last?.status || 'NOT_RUN'} />
      </div>
      <div className="job-control-state">
        <span>{job.paused ? 'Schedule paused' : 'Schedule active'}</span>
        {job.source_enabled === false && <strong>Source disabled</strong>}
      </div>
      <dl className="job-facts">
        <div>
          <dt>Next run (IST)</dt>
          <dd>{job.next_run ? timestamp(job.next_run) : 'Not scheduled'}</dd>
        </div>
        <div>
          <dt>Last attempt (IST)</dt>
          <dd>{job.last ? timestamp(job.last.created_at) : 'Not run yet'}</dd>
        </div>
        <div>
          <dt>Last successful run (IST)</dt>
          <dd>
            {job.last_success
              ? timestamp(job.last_success.finished_at)
              : 'No successful run recorded'}
          </dd>
        </div>
        <div>
          <dt>Last duration</dt>
          <dd>{job.last?.duration_seconds == null ? '—' : `${job.last.duration_seconds}s`}</dd>
        </div>
      </dl>
      <p className="job-outcome">
        {job.last?.summary ||
          job.last?.error ||
          'Run this job to verify connectivity and import available records.'}
      </p>
      {job.last?.counters && (
        <div className="job-counts">
          {['fetched', 'matched', 'written', 'unchanged', 'failed'].map((k) => (
            <span key={k}>
              <b>{job.last?.counters?.[k] || 0}</b>
              {k === 'written' ? 'published' : k}
            </span>
          ))}
        </div>
      )}
      <div className="job-actions">
        <button
          className="primary-button"
          disabled={disabled}
          onClick={() => void action(job.name, 'run', {})}
        >
          Run now
        </button>
        <button
          className="outline-button"
          disabled={busy}
          onClick={() => void action(job.name, 'pause', { paused: !job.paused })}
        >
          {job.paused ? 'Resume' : 'Pause'}
        </button>
        <button className="text-link" onClick={() => inspect(job.name, job.last?.id)}>
          View runs & logs
        </button>
      </div>
      <details className="job-settings">
        <summary>Schedule & configuration</summary>
        {job.configurable ? (
          <form onSubmit={save} key={(job.times || []).join(',')}>
            <label>
              Run times (IST)
              {job.name.includes('results') ? (
                <input name="times" type="time" required defaultValue={job.times?.[0] || '19:30'} />
              ) : (
                <input
                  name="times"
                  required
                  defaultValue={job.times?.join(', ')}
                  placeholder="19:00, 20:00, 22:00"
                />
              )}
            </label>
            <p className="small">
              {job.name.includes('prices')
                ? 'Comma-separated 24-hour times; up to six daily attempts. '
                : ''}
              {job.schedule_note}
            </p>
            <button className="outline-button" disabled={busy}>
              Save schedule
            </button>
          </form>
        ) : (
          <p>{job.schedule} IST</p>
        )}
        <button className="text-link" onClick={configure}>
          Open source configuration →
        </button>
      </details>
      {job.configurable && (
        <details className="job-settings">
          <summary>Run for a specific date{job.name.includes('results') ? ' range' : ''}</summary>
          <form onSubmit={backfill} className="job-date-form">
            {job.name.includes('results') && (
              <label>
                From
                <input type="date" name="from" required />
              </label>
            )}
            <label>
              {job.name.includes('prices') ? 'Trading date' : 'To'}
              <input type="date" name="to" required />
            </label>
            <button className="outline-button" disabled={disabled}>
              Queue dated run
            </button>
          </form>
        </details>
      )}
    </article>
  );
}

export function MarketConsole({ csrf, companies }: { csrf: string; companies: Company[] }) {
  const [data, setData] = useState<Overview | null>(null),
    [message, setMessage] = useState(''),
    [error, setError] = useState('');
  const [busy, setBusy] = useState(false),
    [section, setSection] = useState<Section>('jobs');
  const [selection, setSelection] = useState({ job: '', run: '' });
  const [refreshed, setRefreshed] = useState<string | null>(null);
  const load = useCallback(async () => {
    const response = await fetch('/api/v1/admin/market', { cache: 'no-store' });
    if (!response.ok) throw new Error('Job status unavailable. Check your session and retry.');
    return response.json() as Promise<Overview>;
  }, []);
  useEffect(() => {
    let active = true;
    const refresh = () =>
      load()
        .then((d) => {
          if (active) {
            setData(d);
            setRefreshed(new Date().toISOString());
            setError('');
          }
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    void refresh();
    const timer = setInterval(refresh, 15000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [load]);
  async function action(job: string, operation: string, body: object) {
    setBusy(true);
    setMessage('');
    try {
      const r = await fetch(`/api/v1/admin/market/${job}/${operation}`, {
        method: operation === 'schedule' ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify(body),
      });
      const result = await r.json();
      if (!r.ok) throw new Error(result.error?.message || result.detail || 'Request failed');
      setMessage(
        operation === 'run'
          ? `Run queued · ${result.id}. Inspect it in Run history & errors.`
          : operation === 'schedule'
            ? 'Schedule saved. The next scheduler tick uses these times.'
            : 'Job schedule preference saved.',
      );
      setData(await load());
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Request failed');
    } finally {
      setBusy(false);
    }
  }
  function inspect(job: string, run = '') {
    setSelection({ job, run });
    setSection('history');
  }
  const primary = data?.jobs.filter((j) => j.configurable || j.name === 'sync-ipos') || [];
  return (
    <section className="job-operations" aria-labelledby="market-heading">
      <div className="section-heading">
        <div>
          <p className="eyebrow">OPERATIONS</p>
          <h2 id="market-heading">Data & scheduler</h2>
          <p className="muted">
            Configure → schedule → run → inspect. All times are India Standard Time.
          </p>
        </div>
        <button
          className="outline-button"
          disabled={busy}
          onClick={() =>
            load()
              .then((d) => {
                setData(d);
                setRefreshed(new Date().toISOString());
                setError('');
              })
              .catch((e) => setError(e.message))
          }
        >
          Refresh status
        </button>
      </div>
      <div className="job-overview">
        <div>
          <span>Automatic scheduling</span>
          <strong>{data ? (data.enabled ? 'Enabled' : 'Disabled') : 'Loading…'}</strong>
        </div>
        <div>
          <span>Scheduler</span>
          <strong>{data?.driver === 'celery' ? 'Docker / Celery' : data?.driver || '—'}</strong>
        </div>
        <div>
          <span>Jobs needing attention</span>
          <strong>
            {primary.filter((j) => ['FAILED', 'PARTIAL'].includes(j.last?.status || '')).length}
          </strong>
        </div>
        <div>
          <span>Last status refresh (IST)</span>
          <strong>{timestamp(refreshed)}</strong>
        </div>
      </div>
      {data && !data.enabled && (
        <p className="notice">
          Automatic scheduling is disabled. Manual runs remain available. Enable scheduling in
          Provider configuration.
        </p>
      )}
      {data?.driver === 'vercel' && (
        <p className="notice">
          Exchange schedule editing requires the Celery scheduler. External cron timings must be
          configured separately.
        </p>
      )}
      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}
      {(error || data?.configuration_error) && (
        <p role="alert">{error || data?.configuration_error}</p>
      )}
      <nav className="job-navigation" aria-label="Data operations">
        <div>
          {sections.map(([key, label]) => (
            <button
              key={key}
              aria-current={section === key ? 'page' : undefined}
              onClick={() => setSection(key)}
            >
              {label}
            </button>
          ))}
        </div>
      </nav>
      {section === 'jobs' && (
        <>
          <p className="small">
            NSE and BSE run independently. Successful imports remain available if another source
            fails. Jobs scheduled together are processed sequentially. Counts refer to records, not
            companies.
          </p>
          <div className="job-grid">
            {primary.map((job) => (
              <JobCard
                key={job.name}
                job={job}
                busy={busy}
                action={action}
                inspect={inspect}
                configure={() =>
                  setSection(
                    job.name.includes('prices')
                      ? 'prices'
                      : job.name.includes('results')
                        ? 'results'
                        : 'config',
                  )
                }
              />
            ))}
          </div>
          {!data && <p>Loading jobs…</p>}
        </>
      )}
      {section === 'history' && (
        <JobHistory
          key={selection.job + selection.run}
          jobs={data?.jobs || []}
          initialJob={selection.job}
          initialRun={selection.run}
        />
      )}
      {section === 'prices' && <BhavcopyConsole csrf={csrf} companies={companies} />}
      {section === 'results' && <ResultsConsole csrf={csrf} />}
      {section === 'config' && <MarketConfig csrf={csrf} />}
      {section === 'advanced' && <LegacyMarketConsole csrf={csrf} companies={companies} />}
    </section>
  );
}
