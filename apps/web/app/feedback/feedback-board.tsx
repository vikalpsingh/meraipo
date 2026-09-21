'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

type Feature = {
  id: string;
  title: string;
  body: string;
  votes: number;
  voted: boolean;
  status: string;
};
type Board = { items: Feature[]; summary: { published: number; delivered: number } };
const labels: Record<string, string> = {
  OPEN: 'Under consideration',
  PLANNED: 'Planned',
  IN_PROGRESS: 'In progress',
  DONE: 'Delivered',
};

async function request(path: string, init?: RequestInit) {
  const response = await fetch('/api/v1/feedback' + path, { cache: 'no-store', ...init });
  const result = await response.json();
  if (!response.ok)
    throw new Error(result.error?.message || 'Could not save your request. Please try again.');
  return result;
}

export function FeedbackBoard() {
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const submissionKey = useRef<string | null>(null);
  const load = useCallback(async () => setBoard(await request('')), []);
  useEffect(() => {
    const controller = new AbortController();
    request('', { signal: controller.signal })
      .then(setBoard)
      .catch((error) => {
        if (!controller.signal.aborted) setError(error.message);
      });
    return () => controller.abort();
  }, []);

  async function vote(feature: Feature) {
    setBusy(true);
    setError('');
    try {
      await request(`/${feature.id}/vote`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ voted: !feature.voted }),
      });
      await load();
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Could not save your vote.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {error && (
        <p role="alert" className="notice">
          {error}{' '}
          <button
            onClick={() => {
              setError('');
              load().catch((error) => setError(error.message));
            }}
          >
            Refresh feedback
          </button>
        </p>
      )}
      <div className="feedback-layout">
        <section aria-labelledby="top-features-heading">
          <div className="section-heading">
            <div>
              <h2 id="top-features-heading">Top five requested features</h2>
              <p className="muted">Most votes first. New ideas appear after admin review.</p>
            </div>
            <a href="#share-feedback" className="outline-button">
              Share an idea
            </a>
          </div>
          {board ? (
            <>
              <p className="small">
                {board.summary.published} published requests · {board.summary.delivered} delivered
              </p>
              {board.items.length === 0 ? (
                <div className="panel empty">
                  No feature requests published yet. Share the first idea below.
                </div>
              ) : (
                <ol className="feedback-list">
                  {board.items.map((feature) => (
                    <li key={feature.id} className="panel">
                      <div className="section-heading">
                        <h3>{feature.title}</h3>
                        <span className="badge">{labels[feature.status]}</span>
                      </div>
                      <p className="feedback-text">{feature.body}</p>
                      <div className="scheduler-actions">
                        <strong>
                          {feature.votes} {feature.votes === 1 ? 'vote' : 'votes'}
                        </strong>
                        {feature.status !== 'DONE' && (
                          <button
                            className={feature.voted ? 'primary-button' : 'outline-button'}
                            aria-pressed={feature.voted}
                            aria-label={`${feature.voted ? 'Remove vote for' : 'Vote for'} ${feature.title}`}
                            disabled={busy}
                            onClick={() => vote(feature)}
                          >
                            {feature.voted ? 'Voted · undo' : 'Vote for this'}
                          </button>
                        )}
                      </div>
                    </li>
                  ))}
                </ol>
              )}
              <p className="small">
                No account needed. Votes are limited to one per feature in this browser. Votes help
                us prioritise; they are not a delivery promise.
              </p>
            </>
          ) : (
            <p role="status">Loading feature requests…</p>
          )}
        </section>
        <section id="share-feedback" className="panel" aria-labelledby="share-feedback-heading">
          <h2 id="share-feedback-heading">What would you like to improve?</h2>
          <p>Suggest a feature or tell us what is working—and what could be easier.</p>
          <form
            className="form-grid"
            onChange={() => {
              submissionKey.current = null;
            }}
            onSubmit={async (event) => {
              event.preventDefault();
              const form = event.currentTarget;
              const values = new FormData(form);
              submissionKey.current ??= crypto.randomUUID();
              setBusy(true);
              setError('');
              setMessage('');
              try {
                const result = await request('', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({
                    kind: values.get('kind'),
                    title: values.get('title'),
                    body: values.get('body'),
                    request_key: submissionKey.current,
                  }),
                });
                setMessage(result.message);
                form.reset();
                submissionKey.current = null;
              } catch (error) {
                setError(error instanceof Error ? error.message : 'Could not submit feedback.');
              } finally {
                setBusy(false);
              }
            }}
          >
            <label className="full">
              Feedback type
              <select name="kind" disabled={busy}>
                <option value="FEATURE">Feature request</option>
                <option value="FEEDBACK">General feedback</option>
              </select>
            </label>
            <label className="full">
              Short title
              <input
                name="title"
                required
                minLength={4}
                maxLength={120}
                disabled={busy}
                placeholder="For example, compare IPOs side by side"
              />
            </label>
            <label className="full">
              Tell us more
              <textarea
                name="body"
                required
                minLength={10}
                maxLength={2000}
                rows={5}
                disabled={busy}
                placeholder="What would you like to do, and how would it help you?"
              />
            </label>
            <p className="small full">
              Feature requests may be published after review. General feedback stays private. Please
              leave out personal or account details.
            </p>
            <button className="primary-button full" disabled={busy || !board}>
              {busy ? 'Saving…' : 'Send feedback'}
            </button>
          </form>
          {message && (
            <p role="status" className="notice">
              {message}
            </p>
          )}
        </section>
      </div>
    </>
  );
}
