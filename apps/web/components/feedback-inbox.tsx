'use client';

import { useCallback, useEffect, useState } from 'react';
import { human, timestamp } from '@/lib/format';

type Item = {
  id: string;
  kind: string;
  title: string;
  body: string;
  status: string;
  votes: number;
  created_at: string;
};

async function fetchInbox(
  page: number,
  signal?: AbortSignal,
): Promise<{ items: Item[]; has_more: boolean }> {
  const response = await fetch(`/api/v1/admin/feedback?page=${page}`, {
    cache: 'no-store',
    signal,
  });
  if (!response.ok) throw new Error('Could not load feedback. Refresh or sign in again.');
  return response.json();
}

export function FeedbackInbox({ csrf }: { csrf: string }) {
  const [items, setItems] = useState<Item[]>([]);
  const [page, setPage] = useState(1);
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const load = useCallback(
    async (signal?: AbortSignal) => {
      const data = await fetchInbox(page, signal);
      setItems(data.items);
      setMore(data.has_more);
    },
    [page],
  );
  useEffect(() => {
    const controller = new AbortController();
    fetchInbox(page, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setItems(data.items);
          setMore(data.has_more);
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) setMessage(error.message);
      });
    return () => controller.abort();
  }, [page]);
  return (
    <section aria-labelledby="feedback-inbox-heading">
      <div className="section-heading">
        <div>
          <h2 id="feedback-inbox-heading">Customer feedback</h2>
          <p>Review ideas before publishing. General feedback remains private.</p>
        </div>
        <button
          className="outline-button"
          onClick={() => load().catch((error) => setMessage(error.message))}
        >
          Refresh feedback
        </button>
      </div>
      {message && (
        <p role="status" className="notice">
          {message}
        </p>
      )}
      {items.length === 0 && <p className="panel empty">No feedback on this page yet.</p>}
      {items.map((item) => (
        <article className="panel" key={item.id}>
          <div className="section-heading">
            <h3>{item.title}</h3>
            <span className="badge">{human(item.status)}</span>
          </div>
          <p className="small">
            {human(item.kind)} · {timestamp(item.created_at)} · {item.votes} votes
          </p>
          <p className="feedback-text">{item.body}</p>
          <form
            className="scheduler-actions"
            onSubmit={async (event) => {
              event.preventDefault();
              const status = new FormData(event.currentTarget).get('status');
              setBusy(true);
              setMessage('');
              try {
                const response = await fetch(`/api/v1/admin/feedback/${item.id}`, {
                  method: 'PATCH',
                  headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
                  body: JSON.stringify({ status }),
                });
                if (!response.ok) throw new Error('Could not save review. Please retry.');
                await load();
                setMessage('Feedback review saved. The public board is updated.');
              } catch (error) {
                setMessage(error instanceof Error ? error.message : 'Could not save review.');
              } finally {
                setBusy(false);
              }
            }}
          >
            <label>
              Review {item.title}
              <select key={item.status} name="status" defaultValue={item.status} disabled={busy}>
                {(item.kind === 'FEATURE'
                  ? ['PENDING', 'OPEN', 'PLANNED', 'IN_PROGRESS', 'DONE', 'HIDDEN']
                  : ['PENDING', 'REVIEWED', 'HIDDEN']
                ).map((status) => (
                  <option key={status} value={status}>
                    {status === 'OPEN' ? 'Publish for voting' : human(status)}
                  </option>
                ))}
              </select>
            </label>
            <button className="primary-button" disabled={busy}>
              Save review
            </button>
          </form>
        </article>
      ))}
      <div className="scheduler-actions">
        <button disabled={page === 1 || busy} onClick={() => setPage(page - 1)}>
          Previous page
        </button>
        <span>Page {page}</span>
        <button disabled={!more || busy} onClick={() => setPage(page + 1)}>
          Next page
        </button>
      </div>
    </section>
  );
}
