'use client';

import { useEffect, useState } from 'react';
import { human, timestamp } from '@/lib/format';

type JobError = {
  id: string;
  run_id: string;
  job_name: string;
  run_status: string;
  created_at: string;
  provider: string;
  item: string;
  code: string;
  detail: string;
};

export function JobErrorLog() {
  const [items, setItems] = useState<JobError[]>([]);
  const [message, setMessage] = useState('Loading job errors…');
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const response = await fetch('/api/v1/admin/market/errors', {
          cache: 'no-store',
          signal: controller.signal,
        });
        if (!response.ok) throw new Error('Could not load job errors. Refresh or sign in again.');
        const result = await response.json();
        if (!controller.signal.aborted) {
          setItems(result.items);
          setMessage('');
        }
      } catch (error) {
        if (!controller.signal.aborted)
          setMessage(error instanceof Error ? error.message : 'Could not load job errors.');
      }
    }
    void load();
    const timer = setInterval(load, 15000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [refresh]);
  return (
    <section className="panel" aria-labelledby="job-errors-heading">
      <div className="section-heading">
        <h2 id="job-errors-heading">Job error log</h2>
        <button className="outline-button" onClick={() => setRefresh((value) => value + 1)}>
          Refresh errors
        </button>
      </div>
      <p className="muted">
        Latest 50 errors, newest first. Times are IST. Historical errors remain visible after a
        successful retry.
      </p>
      {message && <p role="status">{message}</p>}
      {!message && items.length === 0 && <p>No job errors recorded.</p>}
      <ul className="run-list">
        {items.map((error) => (
          <li key={error.id} style={{ overflowWrap: 'anywhere' }}>
            <strong>
              {human(error.job_name)} · {error.provider} · {error.code}
            </strong>
            <span>
              {timestamp(error.created_at)} · Run {human(error.run_status)}
            </span>
            <span>{error.detail}</span>
            <details>
              <summary>Technical details</summary>
              <p>Run ID: {error.run_id}</p>
              <p>Source / record: {error.item}</p>
            </details>
          </li>
        ))}
      </ul>
    </section>
  );
}
