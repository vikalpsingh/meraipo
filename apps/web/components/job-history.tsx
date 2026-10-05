'use client';
import { useCallback, useEffect, useState } from 'react';
import { human, timestamp } from '@/lib/format';
import type { JobRun, ScheduledJob } from './job-types';

export function RunStatus({ status }: { status: string }) {
  return <span className={`job-status job-status--${status.toLowerCase()}`}>{human(status)}</span>;
}
type Detail = {
  run: JobRun;
  guidance: string;
  error_count: number;
  errors: {
    id: string;
    created_at: string;
    provider: string;
    item: string;
    code: string;
    detail: string;
    guidance: string;
  }[];
  files: {
    id: string;
    exchange: string;
    trade_date: string;
    status: string;
    error: string | null;
    guidance: string;
    source_url: string;
    retry_at: string | null;
    checksum: string | null;
    counters: Record<string, number> | null;
    row_error_count: number;
    row_errors: unknown[];
  }[];
};
export function JobHistory({
  jobs,
  initialJob = '',
  initialRun = '',
}: {
  jobs: ScheduledJob[];
  initialJob?: string;
  initialRun?: string;
}) {
  const [job, setJob] = useState(initialJob),
    [status, setStatus] = useState(''),
    [page, setPage] = useState(1);
  const [history, setHistory] = useState<{
    items: JobRun[];
    total: number;
    page_size: number;
  } | null>(null);
  const [selected, setSelected] = useState(initialRun),
    [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState('');
  const refresh = useCallback(async () => {
    const response = await fetch(
      `/api/v1/admin/market/runs?${new URLSearchParams({ job, status, page: String(page) })}`,
      { cache: 'no-store' },
    );
    if (!response.ok) throw new Error('Run history unavailable. Check your session and retry.');
    return response.json();
  }, [job, status, page]);
  useEffect(() => {
    let active = true;
    const load = () =>
      refresh()
        .then((d) => {
          if (active) {
            setHistory(d);
            setError('');
          }
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    void load();
    const timer = setInterval(load, 15000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [refresh]);
  useEffect(() => {
    if (!selected) return;
    let active = true;
    const load = () =>
      fetch(`/api/v1/admin/market/runs/${selected}`, { cache: 'no-store' })
        .then((r) => {
          if (!r.ok) throw new Error('Run details unavailable');
          return r.json();
        })
        .then((d) => {
          if (active) setDetail(d);
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    void load();
    const timer = setInterval(load, 15000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [selected]);
  return (
    <section aria-label="Run history and diagnostics">
      <h3>Run history & diagnostics</h3>
      <p className="muted">
        Filter an individual job, then inspect a run for source errors and recovery steps. Refreshes
        every 15 seconds.
      </p>
      <div className="job-history-filters">
        <label>
          Job
          <select
            value={job}
            onChange={(e) => {
              setJob(e.target.value);
              setPage(1);
              setHistory(null);
            }}
          >
            <option value="">All jobs</option>
            {jobs.map((j) => (
              <option key={j.name} value={j.name}>
                {j.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Status
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
              setHistory(null);
            }}
          >
            <option value="">All statuses</option>
            {['QUEUED', 'RUNNING', 'SUCCESS', 'PARTIAL', 'FAILED', 'SKIPPED'].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
      </div>
      {error && <p role="alert">{error}</p>}
      {!history ? (
        <p>Loading runs…</p>
      ) : (
        <>
          <div className="table-scroll">
            <table className="data-table job-history-table">
              <thead>
                <tr>
                  {['Job / run', 'Status', 'Started (IST)', 'Duration', 'Outcome', 'Details'].map(
                    (h) => (
                      <th key={h}>{h}</th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {history.items.map((r) => (
                  <tr key={r.id}>
                    <td>
                      {jobs.find((j) => j.name === r.job_name)?.label || human(r.job_name)}
                      <small>
                        {r.trigger} · {r.id.slice(0, 8)}
                      </small>
                    </td>
                    <td>
                      <RunStatus status={r.status} />
                    </td>
                    <td>{timestamp(r.started_at || r.created_at)}</td>
                    <td>{r.duration_seconds == null ? '—' : `${r.duration_seconds}s`}</td>
                    <td>{r.summary || r.error || '—'}</td>
                    <td>
                      <button
                        className="outline-button"
                        onClick={() => {
                          setDetail(null);
                          setSelected(r.id);
                        }}
                      >
                        Inspect run
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!history.items.length && <p>No runs match these filters.</p>}
          <div className="pagination">
            <button disabled={page === 1} onClick={() => setPage(page - 1)}>
              Previous
            </button>
            <span>
              Page {page} · {history.total} runs
            </span>
            <button
              disabled={page * history.page_size >= history.total}
              onClick={() => setPage(page + 1)}
            >
              Next
            </button>
          </div>
        </>
      )}
      {selected && (
        <section className="panel job-diagnostics" aria-label="Selected run details">
          <div className="section-heading">
            <h3>Run details</h3>
            <button
              onClick={() => {
                setSelected('');
                setDetail(null);
              }}
            >
              Close details
            </button>
          </div>
          {!detail ? (
            <p>Loading diagnostics…</p>
          ) : (
            <>
              <p>
                <RunStatus status={detail.run.status} /> {detail.run.summary}
              </p>
              <dl className="job-facts">
                <div>
                  <dt>Run ID · use in worker logs</dt>
                  <dd className="job-code">{detail.run.id}</dd>
                </div>
                <div>
                  <dt>Requested (IST)</dt>
                  <dd>{timestamp(detail.run.created_at)}</dd>
                </div>
                <div>
                  <dt>Started / finished (IST)</dt>
                  <dd>
                    {timestamp(detail.run.started_at)} / {timestamp(detail.run.finished_at)}
                  </dd>
                </div>
              </dl>
              <details>
                <summary>Parameters and counters</summary>
                <pre>
                  {JSON.stringify(
                    { parameters: detail.run.parameters, counters: detail.run.counters },
                    null,
                    2,
                  )}
                </pre>
              </details>
              {['FAILED', 'PARTIAL', 'SKIPPED'].includes(detail.run.status) && (
                <p className="notice">{detail.guidance}</p>
              )}
              <h4>Errors ({detail.error_count})</h4>
              {!detail.errors.length && (
                <p>No row-level errors recorded. See the run outcome and file statuses below.</p>
              )}
              {detail.errors.map((e) => (
                <article className="job-error" key={e.id}>
                  <strong>{e.code}</strong>
                  <p>
                    {e.provider} · {e.item} · {timestamp(e.created_at)}
                  </p>
                  <p>{e.detail}</p>
                  {e.guidance !== e.detail && (
                    <p>
                      <b>Next step:</b> {e.guidance}
                    </p>
                  )}
                </article>
              ))}
              {detail.error_count > detail.errors.length && (
                <p>
                  Showing the first {detail.errors.length} errors. Use the file report for all
                  rejected rows.
                </p>
              )}
              {detail.files.map((f) => (
                <article className="job-error" key={f.id}>
                  <h4>
                    {f.exchange} · {f.trade_date} · {human(f.status)}
                  </h4>
                  <p>{f.error || 'No file-level error'}</p>
                  <p>{f.guidance}</p>
                  <p className="job-code">Source: {f.source_url}</p>
                  {f.retry_at && <p>Retry after {timestamp(f.retry_at)}</p>}
                  {f.row_error_count > 0 && (
                    <a href={`/api/v1/admin/bhavcopy/${f.id}/errors.csv`}>
                      Download {f.row_error_count} rejected rows (CSV)
                    </a>
                  )}
                  <details>
                    <summary>File counters, checksum and sample errors</summary>
                    <pre>
                      {JSON.stringify(
                        { counters: f.counters, checksum: f.checksum, errors: f.row_errors },
                        null,
                        2,
                      )}
                    </pre>
                  </details>
                </article>
              ))}
            </>
          )}
        </section>
      )}
    </section>
  );
}
