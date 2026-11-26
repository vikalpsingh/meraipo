'use client';
import { AdminActionFeedback, adminMessage } from './admin-action-feedback';
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
type Kind = 'MARKET_DAILY' | 'IPO_OPENING' | 'IPO_CLOSING';
type Overview = {
  test_ipos?: { id: string; name: string }[];
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
  const [contentTestId, setContentTestId] = useState<string | null>(null);
  const [manualText, setManualText] = useState('');
  const [openaiTest, setOpenaiTest] = useState<{
    text: string;
    model: string;
    elapsed_ms: number;
  } | null>(null);
  const [testReviewed, setTestReviewed] = useState(false);
  const [publishingTest, setPublishingTest] = useState(false);
  const [review, setReview] = useState<{
    kind: Kind;
    items: {
      title: string;
      content: string;
      checks: Record<string, boolean>;
      evidence: Record<string, unknown>;
    }[];
  } | null>(null);
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
      if (result.review) setReview(result.review);
      if (result.test_id) setContentTestId(result.test_id);
      if (result.openai_test) {
        setOpenaiTest(result.openai_test);
        setTestReviewed(false);
      }
      if (path === 'connect' && result.url) {
        window.location.assign(result.url);
        return;
      }
      setMessage(result.message || 'Saved.');
      await load();
      return result;
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Request failed.');
    } finally {
      setBusy(false);
    }
  }
  async function publishTest() {
    if (!openaiTest || !testReviewed || publishingTest) return;
    setPublishingTest(true);
    try {
      const draft = await action('manual-draft', { content: openaiTest.text });
      if (!draft?.id) return;
      const approved = await action(draft.id + '/approve');
      if (!approved) return;
      const queued = await action(draft.id + '/publish');
      if (queued) setTestReviewed(false);
    } finally {
      setPublishingTest(false);
    }
  }
  return (
    <section className="panel x-publishing-panel">
      <h2>X publishing · @MeraIPO</h2>
      <p>
        Weekday market research and opening/closing IPO posts. Times are India time (IST). IPO
        reminders can publish automatically from public-feed data. Market research requires an
        approved test first.
      </p>
      <AdminActionFeedback role="status">{message}</AdminActionFeedback>
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
          {data.error && <AdminActionFeedback role="alert">{data.error}</AdminActionFeedback>}
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
            {data.openai_configured
              ? 'Key present on server; access and quota require a successful test'
              : 'API key required on server'}
            . No ChatGPT conversation is scraped.
          </p>
          <div className="admin-table-scroll">
            <table>
              <caption>
                Schedules · IST · one-hour catch-up window. Market: weekdays including holiday
                briefs; IPOs: trading days.
              </caption>
              <thead>
                <tr>
                  <th>Post type</th>
                  <th>Enabled</th>
                  <th>Start time (IST)</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {(['MARKET_DAILY', 'IPO_OPENING', 'IPO_CLOSING'] as Kind[]).map((kind) => (
                  <ScheduleRow
                    key={kind + JSON.stringify(data.schedules[kind])}
                    kind={kind}
                    value={data.schedules[kind] || { enabled: false, time: '09:15' }}
                    busy={busy}
                    save={action}
                    ipos={data.test_ipos || []}
                    openaiConfigured={data.openai_configured}
                  />
                ))}
              </tbody>
            </table>
          </div>
          {contentTestId &&
            data.posts
              .filter((post) => post.id === contentTestId)
              .map((post) => (
                <section className="panel" aria-label="Generated content test" key={post.id}>
                  <h3>
                    2. Review generated{' '}
                    {post.kind === 'MARKET_TEST' ? 'market update' : 'current IPO post'}
                  </h3>
                  <p>Status: {post.status}. Generation never publishes automatically.</p>
                  <p style={{ whiteSpace: 'pre-wrap' }}>
                    {post.content ||
                      adminMessage(post.error_code || 'Generation has not completed.')}
                  </p>
                  {post.has_image && (
                    <a
                      href={'/api/v1/admin/x/' + post.id + '/image'}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      Review generated IPO image ↗
                    </a>
                  )}
                  <details>
                    <summary>Private source evidence and skip reason</summary>
                    <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
                      {JSON.stringify(post.evidence, null, 2)}
                    </pre>
                  </details>
                  <p>
                    3. Approve the exact text and image, then publish. This sends a real public post
                    to @MeraIPO.
                  </p>
                  <button
                    disabled={busy || post.status !== 'DRAFT'}
                    onClick={() => action(post.id + '/approve')}
                  >
                    Approve test content
                  </button>{' '}
                  <button
                    disabled={busy || !data.connected || post.status !== 'APPROVED'}
                    onClick={() => action(post.id + '/publish')}
                  >
                    Publish test content to X
                  </button>
                  {post.post_id && (
                    <a
                      href={'https://x.com/MeraIPO/status/' + post.post_id}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      View published test ↗
                    </a>
                  )}
                  <p>
                    4. After verifying the published result, save the schedules and enable
                    automation below. Market automation accepts a successfully published approved
                    market test; manual text and connection tests do not qualify.
                  </p>
                </section>
              ))}
          <section className="panel" aria-label="OpenAI connection test">
            <h3>Test OpenAI connection and GPT response</h3>
            <p>
              Generate a short integration-test message using the server API. This is a small paid
              request, limited to once every five minutes. It does not use web search, verify live
              market research, or consume the daily market-research allowance.
            </p>
            <button
              disabled={busy || publishingTest || !data.openai_configured}
              onClick={() => {
                setOpenaiTest(null);
                setTestReviewed(false);
                void action('openai-test');
              }}
            >
              Test OpenAI connection
            </button>
            {openaiTest && (
              <>
                <p>
                  Connected · {openaiTest.model} · {openaiTest.elapsed_ms} ms
                </p>
                <h4>GPT response · not yet published</h4>
                <p style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
                  {openaiTest.text}
                </p>
                <label>
                  <input
                    type="checkbox"
                    checked={testReviewed}
                    disabled={busy || publishingTest}
                    onChange={(event) => setTestReviewed(event.target.checked)}
                  />{' '}
                  I reviewed this response and want to publish it publicly to @MeraIPO.
                </label>
                <button
                  disabled={busy || publishingTest || !data.connected || !testReviewed}
                  onClick={() => void publishTest()}
                >
                  Publish reviewed GPT response to X
                </button>
                <p>
                  This creates an approved manual test post. It does not unlock automated market
                  research. Track the queued post in the table below.
                </p>
              </>
            )}
          </section>
          <section className="panel" aria-label="Manual X test post">
            <h3>Write a test post for @MeraIPO</h3>
            <p>
              This is a real public X post, not a sandbox message. Review any market claims
              yourself. Saving creates a draft only; use Approve and Publish now below to send it.
            </p>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void action('manual-draft', { content: manualText });
              }}
            >
              <label htmlFor="x-manual-content">Message to publish</label>
              <textarea
                id="x-manual-content"
                value={manualText}
                onChange={(event) => setManualText(event.target.value)}
                rows={5}
                maxLength={4000}
                required
                style={{ width: '100%', padding: 12, marginBlock: 12 }}
                placeholder="Paste or write the exact message you want to post…"
              />
              <p>
                X allows 280 weighted characters; links and emoji count differently. The server
                validates your draft.
              </p>
              <button type="submit" disabled={busy || !data.connected || !manualText.trim()}>
                Save manual draft for review
              </button>
            </form>
            {manualText.trim() && (
              <div>
                <h4>Preview · not yet published</h4>
                <p style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{manualText}</p>
              </div>
            )}
          </section>
          <p>
            Research starts at the scheduled time, not an exact publication deadline. One market
            scheduled research request plus one optional content test per IST day; incomplete or
            interrupted research is not automatically charged again. Review source dates and all
            figures before approval.
          </p>
          {review && (
            <section aria-label="Pulled content for review" className="panel">
              <h3>
                {review.kind === 'MARKET_DAILY'
                  ? 'Market research'
                  : review.kind === 'IPO_CLOSING'
                    ? "Today's closing IPOs"
                    : "Today's opening IPOs"}{' '}
                · review only
              </h3>
              <p>
                Pull reads saved application data without publishing or making a paid research
                request. ChatGPT chat content is not imported. Generate creates a draft for
                approval; market research remains limited to one request per day.
              </p>
              {!review.items.length && (
                <p>
                  No stored content found for today. Check IPO dates or generate the first market
                  draft.
                </p>
              )}
              {review.items.map((item, i) => (
                <article key={i}>
                  <h4>{item.title}</h4>
                  <p style={{ whiteSpace: 'pre-wrap' }}>{item.content}</p>
                  {Object.keys(item.checks).length > 0 && (
                    <div className="admin-table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th>Publishing requirement</th>
                            <th>Result</th>
                          </tr>
                        </thead>
                        <tbody>
                          {Object.entries(item.checks).map(([name, passed]) => (
                            <tr key={name}>
                              <td>{name}</td>
                              <td>{passed ? 'Passed' : 'Needs attention'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  <dl>
                    {Object.entries(item.evidence).map(([name, value]) => (
                      <div key={name}>
                        <dt>{name}</dt>
                        <dd style={{ overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' }}>
                          {typeof value === 'string' ? value : JSON.stringify(value)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </article>
              ))}
            </section>
          )}
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
            Automatic IPO publishing uses public-feed checks without manual guide approval. Market
            automation requires an approved market post first. Maximum {data.daily_limit} publishing
            attempt(s) per post and {data.monthly_limit} per month, including failures. These are
            request caps, not a guarantee of your X bill; set a spending cap in the X Developer
            Console too.
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
                        {p.kind === 'MANUAL'
                          ? 'Manual admin post'
                          : p.kind === 'MARKET_TEST'
                            ? 'Market content test'
                            : p.kind === 'IPO_TEST'
                              ? 'Current IPO content test'
                              : p.kind === 'MARKET_DAILY'
                                ? 'Daily market update'
                                : p.kind === 'IPO_CLOSING'
                                  ? 'IPO closing day'
                                  : 'IPO opening / brief'}
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
                      <p>{adminMessage(p.error_code || '')}</p>
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
  ipos,
  openaiConfigured,
}: {
  kind: Kind;
  value: Schedule;
  busy: boolean;
  save: (path: string, body?: object) => Promise<void>;
  ipos: { id: string; name: string }[];
  openaiConfigured: boolean;
}) {
  const [testIpo, setTestIpo] = useState('');
  const [enabled, setEnabled] = useState(value.enabled);
  const [time, setTime] = useState(value.time);
  const label =
    kind === 'MARKET_DAILY'
      ? 'Daily market update · OpenAI'
      : kind === 'IPO_CLOSING'
        ? 'IPO closing day · image included'
        : 'IPO opening day · image included';
  return (
    <tr>
      <td>{label}</td>
      <td>
        {kind === 'MARKET_DAILY' && (
          <div>
            <button
              disabled={busy || !openaiConfigured}
              onClick={() => save('content-test', { kind })}
            >
              1. Generate today&apos;s market update · test
            </button>
            <p>
              Paid research: one test per IST day, separate from the scheduled request. Uses the
              market prompt, not a ChatGPT chat. Weekends or insufficient core data return
              SKIP_POST. Tests work with the schedule disabled.
            </p>
          </div>
        )}
        {kind === 'IPO_OPENING' && (
          <div>
            <label>
              Currently open IPO for test
              <select
                value={testIpo}
                onChange={(event) => setTestIpo(event.target.value)}
                disabled={busy}
              >
                <option value="">Choose an IPO</option>
                {ipos.map((ipo) => (
                  <option key={ipo.id} value={ipo.id}>
                    {ipo.name}
                  </option>
                ))}
              </select>
            </label>
            <button
              disabled={busy || !testIpo}
              onClick={() => save('content-test', { kind, ipo_id: testIpo })}
            >
              1. Generate selected IPO content and image · test
            </button>
            <p>
              Uses an open IPO even after its opening day. Test text and image say open for
              subscription. Scheduled posts still use the actual opening date.
            </p>
          </div>
        )}
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
        <button disabled={busy} onClick={() => save('review', { kind })}>
          Pull content for review
        </button>{' '}
        <button disabled={busy || !time} onClick={() => save('schedule', { kind, enabled, time })}>
          Save schedule
        </button>{' '}
        <button disabled={busy || !value.enabled} onClick={() => save('generate', { kind })}>
          {kind === 'MARKET_DAILY'
            ? "Get today's market-opening draft · OpenAI"
            : 'Generate next eligible draft'}
        </button>
      </td>
    </tr>
  );
}
