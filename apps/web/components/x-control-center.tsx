'use client';
import { useCallback, useEffect, useState } from 'react';
import { timestamp } from '@/lib/format';
type Post = {
  id: string;
  kind: string;
  has_image: boolean;
  content: string;
  status: string;
  evidence: Record<string, unknown>;
  post_id: string | null;
  created_at: string;
  approved_at: string | null;
  published_at: string | null;
  attempted_at: string | null;
  attempts: number;
  error_code: string | null;
  api_status: number | null;
  request_id: string | null;
};
type Schedule = { enabled: boolean; time: string; auto_publish?: boolean };
type Kind = 'MARKET_DAILY' | 'IPO_OPENING';
type Overview = {
  schedules: Record<Kind, Schedule>;
  openai_configured: boolean;
  enabled: boolean;
  connected: boolean;
  username: string | null;
  auto_publish: boolean;
  error: string | null;
  monthly_limit: number;
  daily_limit: number;
  posts: Post[];
};
export function XControlCenter({ csrf }: { csrf: string }) {
  const [data, setData] = useState<Overview | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const load = useCallback(async () => {
    const r = await fetch('/api/v1/admin/x', { cache: 'no-store' });
    if (!r.ok) throw new Error('Could not load X controls. Sign in again or check deployment.');
    setData(await r.json());
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/v1/admin/x', { cache: 'no-store', signal: controller.signal })
      .then(async (r) => {
        if (!r.ok) throw new Error('Could not load X controls. Sign in again or check deployment.');
        return r.json();
      })
      .then((value: Overview) => {
        if (!controller.signal.aborted) setData(value);
      })
      .catch((e: Error) => {
        if (!controller.signal.aborted) setMessage(e.message);
      });
    return () => controller.abort();
  }, []);
  async function action(path: string, body?: object) {
    setBusy(true);
    setMessage('');
    try {
      const r = await fetch('/api/v1/admin/x/' + path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify(body || {}),
      });
      const result = await r.json();
      if (!r.ok) throw new Error(result.error?.message || result.detail || 'X action failed.');
      if (path === 'connect' && result.url) {
        window.location.assign(result.url);
        return;
      }
      setMessage(result.message || 'Saved.');
      await load();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Request failed.');
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel x-publishing-panel">
      <h2>X publishing · @MeraIPO</h2>
      <p>
        Trading-day market research and opening-day IPO posts. Times are India time (IST). Both
        types start with approval; automatic publishing can be enabled after successful testing.
      </p>
      <p role="status">{message}</p>
      <button disabled={busy} onClick={() => void load().catch((e) => setMessage(e.message))}>
        Refresh status
      </button>
      {data && (
        <>
          <p>
            Integration: {data.enabled ? 'Enabled' : 'Disabled on server'} · Account:{' '}
            {data.connected ? '@' + data.username : 'Not connected'} · Mode:{' '}
            {data.auto_publish ? 'Automatic' : 'Approval required'}
          </p>
          {data.error && <p role="alert">{data.error}</p>}
          <div className="job-actions">
            <button disabled={busy || !data.enabled} onClick={() => action('connect')}>
              {data.connected ? 'Reconnect X' : 'Connect @MeraIPO'}
            </button>
            <button disabled={busy || !data.connected} onClick={() => action('disconnect')}>
              Disconnect
            </button>
          </div>
          <p>
            OpenAI research:{' '}
            {data.openai_configured ? 'Configured on server' : 'API key required on server'}. No
            ChatGPT conversation is scraped.
          </p>
          <div className="admin-table-scroll">
            <table>
              <caption>Schedules · trading days only · one-hour catch-up window</caption>
              <thead>
                <tr>
                  <th>Post type</th>
                  <th>Enabled</th>
                  <th>Start time (IST)</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {(['MARKET_DAILY', 'IPO_OPENING'] as Kind[]).map((kind) => (
                  <ScheduleRow
                    key={kind + JSON.stringify(data.schedules[kind])}
                    kind={kind}
                    value={data.schedules[kind]}
                    busy={busy}
                    save={action}
                  />
                ))}
              </tbody>
            </table>
          </div>
          <p>
            Research starts at the scheduled time, not an exact publication deadline. One market
            research request per day; incomplete or interrupted research is not automatically
            charged again. Review source dates and all figures before approval.
          </p>
          <label>
            <input
              type="checkbox"
              checked={data.auto_publish}
              disabled={busy || !data.connected}
              onChange={(e) => action('auto', { enabled: e.target.checked })}
            />{' '}
            Enable automatic publishing after source checks
          </label>
          <label>
            <input
              type="checkbox"
              checked={Boolean(data.schedules.MARKET_DAILY.auto_publish)}
              disabled={busy || !data.connected}
              onChange={(e) => action('market-auto', { enabled: e.target.checked })}
            />{' '}
            Include daily OpenAI market drafts in automatic publishing (requires an approved market
            post to succeed first)
          </label>
          <p>
            Market sources and dates are checked, but model-generated claims can still be wrong.
            Review the first live draft and monitor sources before opting into automation.
          </p>
          <p>
            Automatic publishing requires a successful approved post first. Maximum{' '}
            {data.daily_limit} publishing attempt(s) per post and {data.monthly_limit} per month,
            including failures. These are request caps, not a guarantee of your X bill; set a
            spending cap in the X Developer Console too.
          </p>
          <div className="admin-table-scroll">
            <table>
              <caption>Latest 50 drafts and publishing outcomes</caption>
              <thead>
                <tr>
                  <th>Draft and sources</th>
                  <th>Status</th>
                  <th>Times (IST)</th>
                  <th>X post</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.posts.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <strong>
                        {p.kind === 'MARKET_DAILY' ? 'Daily market update' : 'IPO opening / brief'}
                      </strong>
                      {p.has_image && (
                        <a
                          href={'/api/v1/admin/x/' + p.id + '/image'}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          Preview IPO image ↗
                        </a>
                      )}
                      <p style={{ whiteSpace: 'pre-wrap' }}>
                        {p.content || 'No publishable content'}
                      </p>
                      <details>
                        <summary>Source evidence</summary>
                        {Array.isArray(p.evidence.facts) &&
                          p.evidence.facts.map((fact, i) => {
                            const f = fact as { url?: string; claim?: string };
                            return f.url?.startsWith('https://') ? (
                              <p key={i}>
                                <a href={f.url} target="_blank" rel="noopener noreferrer">
                                  {f.claim || 'View source'} ↗
                                </a>
                              </p>
                            ) : null;
                          })}
                        <dl>
                          {Object.entries(p.evidence).map(([k, v]) => (
                            <div key={k}>
                              <dt>{k}</dt>
                              <dd>{typeof v === 'string' ? v : JSON.stringify(v, null, 2)}</dd>
                            </div>
                          ))}
                        </dl>
                      </details>
                    </td>
                    <td>
                      {p.status}
                      <p>{p.error_code}</p>
                      <small>
                        Attempts: {p.attempts} · HTTP: {p.api_status || '—'} · Reference:{' '}
                        {p.request_id || '—'}
                      </small>
                    </td>
                    <td>
                      Created: {timestamp(p.created_at)}
                      <br />
                      Attempted: {p.attempted_at ? timestamp(p.attempted_at) : '—'}
                      <br />
                      Published: {p.published_at ? timestamp(p.published_at) : '—'}
                    </td>
                    <td>
                      {p.post_id ? (
                        <a
                          href={'https://x.com/MeraIPO/status/' + p.post_id}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          View post ↗
                        </a>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td>
                      <button
                        disabled={busy || !['DRAFT', 'FAILED'].includes(p.status)}
                        onClick={() => action(p.id + '/approve')}
                      >
                        Approve
                      </button>
                      <button
                        disabled={busy || !data.connected || p.status !== 'APPROVED'}
                        onClick={() => action(p.id + '/publish')}
                      >
                        Publish now
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!data.posts.length && <p>No drafts yet.</p>}
          <p>
            FAILED: correct the source/configuration and reapprove within the daily cap. UNCERTAIN
            or interrupted SENDING: inspect @MeraIPO directly before any recovery; the app never
            blindly retries these posts.
          </p>
        </>
      )}
    </section>
  );
}

function ScheduleRow({
  kind,
  value,
  busy,
  save,
}: {
  kind: Kind;
  value: Schedule;
  busy: boolean;
  save: (path: string, body?: object) => Promise<void>;
}) {
  const [enabled, setEnabled] = useState(value.enabled);
  const [time, setTime] = useState(value.time);
  const label =
    kind === 'MARKET_DAILY' ? 'Daily market update · OpenAI' : 'IPO opening day · image included';
  return (
    <tr>
      <td>{label}</td>
      <td>
        <input
          aria-label={'Enable ' + label}
          type="checkbox"
          checked={enabled}
          disabled={busy}
          onChange={(e) => setEnabled(e.target.checked)}
        />
      </td>
      <td>
        <input
          aria-label={label + ' time in IST'}
          type="time"
          required
          value={time}
          disabled={busy}
          onChange={(e) => setTime(e.target.value)}
        />
      </td>
      <td>
        <button disabled={busy || !time} onClick={() => save('schedule', { kind, enabled, time })}>
          Save schedule
        </button>{' '}
        <button disabled={busy || !value.enabled} onClick={() => save('generate', { kind })}>
          Generate next eligible draft
        </button>
      </td>
    </tr>
  );
}
