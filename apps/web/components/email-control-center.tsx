'use client';
import { useCallback, useEffect, useState } from 'react';
import { EmailApplicationSchedule } from './email-application-schedule';
import type { Company } from '@/lib/types';
type Check = {
  ready: boolean;
  checks: Record<string, boolean>;
  aws: {
    status: string;
    ready: boolean;
    sender: string;
    checks: Record<string, boolean>;
    max_rate: number | null;
    remaining_quota: number | null;
    message?: string;
  };
};
type Status = {
  sending_enabled: boolean;
  send_hour_ist?: number;
  application_schedule?: { mode: 'opening' | 'closing' | 'both'; time: string };
  readiness: Check;
  counts: Record<string, number>;
  subscribers: Record<string, number>;
  scheduler_seen_at: string | null;
  last_accepted_at: string | null;
  test: { id: string; status: string; delivered: boolean; received_confirmed: boolean } | null;
  last_run: {
    id: string;
    status: string;
    started_at: string;
    finished_at: string | null;
    processed: number;
    error_code: string | null;
  } | null;
  failures: {
    id: string;
    kind: string;
    status: string;
    attempts: number;
    created_at: string;
    updated_at: string;
    code: string;
    retry_at: string | null;
    eligible_retry: boolean;
  }[];
};
const date = (value: string | null) =>
  value ? new Date(value).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }) + ' IST' : 'N/A';
const categories = [
  ['white', 'All IPOs'],
  ['light_green', 'Above 20% GMP'],
  ['strong_green', 'Above 40% GMP'],
  ['gold', 'Above 100% GMP'],
] as const;

export function EmailControlCenter({ csrf, companies }: { csrf: string; companies: Company[] }) {
  const [data, setData] = useState<Status | null>(null);
  const [days, setDays] = useState('30');
  const [categoryMessage, setCategoryMessage] = useState('');
  const [sampleAddress, setSampleAddress] = useState('');
  const [sampleMessage, setSampleMessage] = useState('');
  const [sampleBusy, setSampleBusy] = useState(false);
  const sampleIpo =
    companies.find((c) => c.ipo_id && c.status === 'OPEN' && !c.is_demo) ??
    companies.find((c) => c.ipo_id && !c.is_demo);
  const [recipient, setRecipient] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [ipo, setIpo] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<{ subject: string; html: string; text: string } | null>(
    null,
  );
  const refresh = useCallback(
    async (aws = false) => {
      const response = await fetch(`/api/v1/admin/email/status?days=${days}&refresh=${aws}`, {
        cache: 'no-store',
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error?.message || 'Email status unavailable');
      setData(body);
    },
    [days],
  );
  useEffect(() => {
    let active = true;
    // Fetch completion updates state asynchronously after the selected period changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh().catch((error) => {
      if (active) setMessage(error.message);
    });
    return () => {
      active = false;
    };
  }, [refresh]);
  async function action(path: string, method = 'POST', body?: unknown) {
    const report = path === 'category-tests' ? setCategoryMessage : setMessage;
    report('');
    setBusy(true);
    setMessage('');
    try {
      const response = await fetch('/api/v1/admin/email/' + path, {
        method,
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const value = await response.json();
      if (!response.ok) throw new Error(value.error?.message || 'Request failed');
      if (path.startsWith('preview/')) setPreview(value);
      else {
        report(value.message || 'Sending control saved.');
        await refresh();
      }
    } catch (error) {
      report(error instanceof Error ? error.message : 'Request failed');
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel email-analytics email-control-centre">
      <header className="email-control-header">
        <div>
          <span className="email-eyebrow">MERAADMIN · EMAIL OPERATIONS</span>
          <h2>Email control centre</h2>
          <p>Manage delivery, schedule reminders and test with confidence.</p>
        </div>
        <nav aria-label="Email control sections">
          <a href="#email-production">1. Readiness</a>
          <a href="#email-schedule">2. Schedule</a>
          <a href="#email-testing">3. Test emails</a>
          <a href="#email-reports">4. Delivery reports</a>
        </nav>
      </header>
      <div className="email-filters">
        <label>
          Operational period
          <select value={days} onChange={(e) => setDays(e.target.value)}>
            <option value="7">7 days</option>
            <option value="30">30 days</option>
            <option value="90">90 days</option>
          </select>
        </label>
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await refresh(true);
              setMessage('Status refreshed.');
            } catch {
              setMessage('Status unavailable.');
            } finally {
              setBusy(false);
            }
          }}
        >
          Refresh readiness and metrics
        </button>
      </div>
      <p role="status">{message}</p>

      {!data && <p role="status">Loading email status…</p>}
      {data && (
        <section
          id="email-production"
          className="email-control-card"
          aria-label="Production dispatch"
        >
          <div className="email-section-heading">
            <span className="email-step">01</span>
            <div>
              <h3>Production dispatch</h3>
              <p>Check readiness before enabling subscriber emails.</p>
            </div>
          </div>
          {!data.sending_enabled && !data.readiness.ready && (
            <div
              className="email-setup-note"
              role="note"
              aria-label="Why subscriber emails are paused"
            >
              <h4>Subscriber emails are paused until setup is complete</h4>
              <p>
                A healthy scheduler does not mean emails are enabled. The worker skips subscriber
                campaigns while these readiness checks fail.
              </p>
              <details className="email-setup-details">
                <summary>View setup steps</summary>
                <ol>
                  {data.readiness.aws.checks.ses_events === false && (
                    <li>
                      In AWS SES → Configuration sets → meraipo-ipo-alerts → meraipo-ses-events,
                      enable publishing and select Send, Delivery, Bounce, Complaint, Reject and
                      Delivery delay. Then refresh readiness.
                    </li>
                  )}
                  {data.readiness.aws.checks.sns_subscription === false && (
                    <li>Confirm the SNS HTTPS subscription for the app’s SES event endpoint.</li>
                  )}
                  {data.readiness.checks.test_received === false && (
                    <li>
                      Under Preview and test, preview an IPO and send the designated TEST to your
                      admin email. After the delivery event arrives, confirm receipt using the test
                      controls.
                    </li>
                  )}
                  {data.readiness.checks.unsubscribe_verified === false && (
                    <li>
                      Use the unsubscribe link in that designated test email to verify the
                      unsubscribe flow.
                    </li>
                  )}
                </ol>
                <p>
                  Resolve any other “Not ready” checks below, refresh readiness, then select Enable
                  production sending.
                </p>

                <p>
                  A recipient sample checks email sending but does not replace the designated
                  readiness test.
                </p>
              </details>
              <a href="#email-recipient-test">Send a test email to a specific recipient ↓</a>
            </div>
          )}
          <p>
            Application reminders start at{' '}
            {data.application_schedule?.time ||
              String(data.send_hour_ist ?? 9).padStart(2, '0') + ':00'}{' '}
            IST. One combined email per eligible subscriber, matched to their confirmed GMP
            preference, with an unsubscribe link.
          </p>
          <p className="email-dispatch-state" data-enabled={data.sending_enabled}>
            {data.sending_enabled ? 'Enabled · every dispatch still checks readiness' : 'Disabled'}
          </p>
          <button
            disabled={busy || (!data.sending_enabled && !data.readiness.ready)}
            role="switch"
            aria-checked={data.sending_enabled}
            onClick={() => action('sending', 'PUT', { enabled: !data.sending_enabled })}
          >
            {data.sending_enabled ? 'Disable production sending' : 'Enable production sending'}
          </button>
          <p>
            SES: {data.readiness.aws.status.replaceAll('_', ' ')} · {data.readiness.aws.sender}
          </p>
          <p>
            Quota remaining: {data.readiness.aws.remaining_quota ?? 'N/A'} · Maximum send rate:{' '}
            {data.readiness.aws.max_rate ?? 'N/A'}/second
          </p>
          <details className="email-readiness-details">
            <summary>
              All readiness checks ·{' '}
              {
                Object.values({ ...data.readiness.checks, ...data.readiness.aws.checks }).filter(
                  (value) => !value,
                ).length
              }{' '}
              need attention
            </summary>
            <ul className="email-readiness-grid">
              {Object.entries({ ...data.readiness.checks, ...data.readiness.aws.checks }).map(
                ([key, value]) => (
                  <li key={key} data-ready={value}>
                    <span>{key.replaceAll('_', ' ')}</span>
                    <strong>{value ? 'Passed' : 'Not ready'}</strong>
                  </li>
                ),
              )}
            </ul>
          </details>
          <p>{data.readiness.aws.message}</p>
          <p>
            Scheduler heartbeat: {date(data.scheduler_seen_at)} · Last SES acceptance:{' '}
            {date(data.last_accepted_at)}
          </p>
        </section>
      )}
      <section id="email-schedule" className="email-control-card" aria-label="Reminder schedule">
        <div className="email-section-heading">
          <span className="email-step">02</span>
          <div>
            <h3>Reminder schedule</h3>
            <p>Choose which application days to cover and when reminders start.</p>
          </div>
        </div>
        {data && (
          <EmailApplicationSchedule
            csrf={csrf}
            config={
              data.application_schedule || {
                mode: 'opening',
                time: String(data.send_hour_ist ?? 9).padStart(2, '0') + ':00',
              }
            }
            onSaved={() => refresh()}
          />
        )}
      </section>
      <section id="email-testing" className="email-control-card" aria-label="Test emails">
        <div className="email-section-heading">
          <span className="email-step">03</span>
          <div>
            <h3>Test emails</h3>
            <p>Send a quick sample, then complete the inbox readiness test before going live.</p>
          </div>
        </div>
        <form
          id="email-recipient-test"
          aria-labelledby="email-recipient-test-heading"
          className="category-mailer"
          onSubmit={async (event) => {
            event.preventDefault();
            if (!sampleIpo || sampleBusy) return;
            setSampleBusy(true);
            setSampleMessage('');
            try {
              const response = await fetch('/api/v1/admin/email/category-tests', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
                body: JSON.stringify({
                  ipo_id: sampleIpo.ipo_id,
                  email: sampleAddress.trim(),
                  categories: ['white'],
                }),
              });
              const result = await response.json();
              if (!response.ok)
                throw new Error(
                  result.error?.message || result.detail || 'Could not queue the sample email.',
                );
              setSampleMessage(
                `One sample email queued for ${sampleAddress.trim()}. Check the inbox and spam folder.`,
              );
            } catch (error) {
              setSampleMessage(
                error instanceof Error ? error.message : 'Could not queue the sample email.',
              );
            } finally {
              setSampleBusy(false);
            }
          }}
        >
          <h3 id="email-recipient-test-heading">Send a sample email</h3>
          <p>
            Enter the recipient below to send one real TEST email through SES. This works while
            production dispatch is disabled and does not enable subscriber alerts or change their
            preferences.
          </p>
          <p>
            {sampleIpo
              ? `Preview an IPO alert for ${sampleIpo.name} in your inbox.`
              : 'An IPO record is needed before a sample can be sent.'}
          </p>
          <div className="category-mailer-fields">
            <label>
              Recipient email address
              <input
                type="email"
                required
                maxLength={254}
                placeholder="you@example.com"
                value={sampleAddress}
                disabled={sampleBusy}
                onChange={(e) => {
                  setSampleAddress(e.target.value);
                  setSampleMessage('');
                }}
              />
            </label>
          </div>
          <div className="category-mailer-footer">
            <span>In the SES sandbox, use a verified recipient.</span>
            <button
              className="primary-button"
              type="submit"
              disabled={!sampleIpo || sampleBusy || !sampleAddress.trim()}
            >
              {sampleBusy ? 'Queuing sample…' : 'Send sample email'}
            </button>
          </div>
          <p role="status">{sampleMessage}</p>
        </form>
        <details className="email-test-details">
          <summary>Inbox readiness and category tests</summary>
          {data && (
            <div className="email-test-content">
              <h3>Preview and test</h3>
              <label>
                IPO
                <select
                  value={ipo}
                  onChange={(e) => {
                    setIpo(e.target.value);
                    setPreview(null);
                  }}
                >
                  <option value="">Select an IPO</option>
                  {companies.map((c) => (
                    <option key={c.ipo_id} value={c.ipo_id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </label>
              <div className="email-filters">
                <button disabled={!ipo || busy} onClick={() => action('preview/' + ipo, 'GET')}>
                  Preview HTML and text
                </button>
                <button
                  disabled={!ipo || !preview || busy}
                  onClick={() => action('test', 'POST', { ipo_id: ipo })}
                >
                  Send one TEST to my admin email
                </button>
              </div>
              <p>
                The inbox readiness test sends to your signed-in administrator address. SES sandbox
                requires a verified recipient. This does not enable production sending.
              </p>
              <form
                className="category-mailer"
                onSubmit={(event) => {
                  event.preventDefault();
                  void action('category-tests', 'POST', {
                    ipo_id: ipo,
                    email: recipient.trim(),
                    categories: selected,
                  });
                }}
              >
                <h3>Send category test emails</h3>
                <p>Send one email per selected category using the IPO’s latest recorded GMP.</p>
                <div className="category-mailer-fields">
                  <label>
                    IPO for category tests
                    <select
                      required
                      value={ipo}
                      onChange={(event) => {
                        setIpo(event.target.value);
                        setPreview(null);
                      }}
                    >
                      <option value="">Choose an IPO</option>
                      {companies.map((company) => (
                        <option key={company.ipo_id} value={company.ipo_id}>
                          {company.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Test recipient email
                    <input
                      required
                      type="email"
                      maxLength={254}
                      value={recipient}
                      placeholder="name@example.com"
                      onChange={(event) => setRecipient(event.target.value)}
                    />
                  </label>
                </div>
                <fieldset>
                  <legend>Choose test categories</legend>
                  <button
                    type="button"
                    className="category-mailer-select"
                    onClick={() =>
                      setSelected(
                        selected.length === categories.length ? [] : categories.map(([key]) => key),
                      )
                    }
                  >
                    {selected.length === categories.length ? 'Clear selection' : 'Select all four'}
                  </button>
                  <div className="category-mailer-options">
                    {categories.map(([key, label]) => (
                      <label key={key}>
                        <input
                          type="checkbox"
                          checked={selected.includes(key)}
                          onChange={(event) => {
                            const checked = event.target.checked;
                            setSelected((previous) =>
                              checked
                                ? [...previous, key]
                                : previous.filter((item) => item !== key),
                            );
                          }}
                        />
                        {label}
                      </label>
                    ))}
                  </div>
                </fieldset>
                <div className="category-mailer-footer">
                  <span aria-live="polite">
                    {!ipo
                      ? 'Choose an IPO to continue.'
                      : !recipient.trim()
                        ? 'Enter a recipient email address.'
                        : !selected.length
                          ? 'Select at least one category.'
                          : `${selected.length} of 4 selected · ${recipient.trim()}`}
                  </span>
                  <button
                    className="primary-button"
                    type="submit"
                    disabled={busy || !ipo || !recipient.trim() || !selected.length}
                  >
                    Queue {selected.length || ''} test email{selected.length === 1 ? '' : 's'}
                  </button>
                </div>
                <p role="status">{categoryMessage}</p>
              </form>
              {preview && (
                <details open>
                  <summary>{preview.subject}</summary>
                  <iframe
                    title="Test email preview"
                    sandbox=""
                    srcDoc={preview.html}
                    style={{ width: '100%', minHeight: 540, border: '1px solid #ddd' }}
                  />
                  <h4>Plain text</h4>
                  <pre style={{ whiteSpace: 'pre-wrap' }}>{preview.text}</pre>
                </details>
              )}
              {data.test && (
                <p>
                  Latest test: {data.test.status} ·{' '}
                  {data.test.received_confirmed
                    ? 'Inbox receipt confirmed'
                    : 'Receipt not yet confirmed'}{' '}
                  <button
                    disabled={busy || !data.test.delivered || data.test.received_confirmed}
                    onClick={() => action(`test/${data.test!.id}/received`)}
                  >
                    I received this test in my inbox
                  </button>
                </p>
              )}
            </div>
          )}
        </details>
      </section>
      {data && (
        <section id="email-reports" className="email-control-card" aria-label="Delivery reports">
          <div className="email-section-heading">
            <span className="email-step">04</span>
            <div>
              <h3>Delivery reports</h3>
              <p>Review subscriber activity and delivery outcomes for the selected period.</p>
            </div>
          </div>
          <h3>Subscribers</h3>
          <div className="email-kpis">
            {Object.entries(data.subscribers).map(([key, value]) => (
              <div className="email-metric" key={key}>
                {key}
                <strong>{value}</strong>
              </div>
            ))}
          </div>
          <h3>Campaign operations</h3>
          <p>
            TEST and confirmation emails are excluded. Accepted means SES accepted the request;
            delivered means the recipient mail server accepted it, not that someone read it.
          </p>
          <div className="email-kpis">
            {[
              'SCHEDULED',
              'PENDING',
              'UNSUBSCRIBED',
              'ATTEMPTED',
              'SES_ACCEPTED',
              'DELIVERED',
              'FAILED',
              'UNCERTAIN',
              'RETRY',
              'REJECTED',
              'BOUNCED',
              'COMPLAINT',
              'DELAYED',
              'SOFT_BOUNCE',
              'SUPPRESSED',
              'CANCELLED',
            ].map((key) => (
              <div className="email-metric" key={key}>
                {key.replaceAll('_', ' ')}
                <strong>{data.counts[key] || 0}</strong>
              </div>
            ))}
          </div>
          <h3>Last dispatch</h3>
          {data.last_run ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Dispatch run ID</th>
                    <th>Status</th>
                    <th>Processed</th>
                    <th>Started (IST)</th>
                    <th>Finished (IST)</th>
                    <th>Error</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>{data.last_run.id}</td>
                    <td>{data.last_run.status}</td>
                    <td>{data.last_run.processed}</td>
                    <td>{date(data.last_run.started_at)}</td>
                    <td>{date(data.last_run.finished_at)}</td>
                    <td>{data.last_run.error_code || 'No recorded error'}</td>
                  </tr>
                </tbody>
              </table>
              {data.last_run.status === 'TEST_ONLY' && (
                <p>
                  Subscriber alert dispatch was not enabled or did not pass readiness. Only
                  confirmation and test emails were eligible for processing. This run ID identifies
                  a worker batch, not an individual delivery.
                </p>
              )}
            </div>
          ) : (
            <p>No dispatch recorded.</p>
          )}
          <h3>Recent failures</h3>
          <p>
            Latest 25 error records updated within the selected operational period. Historical
            failures do not establish that sending is still failing. Updated time is the record
            timestamp, not a confirmed delivery time.
          </p>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Delivery ID</th>
                  <th>Created (IST)</th>
                  <th>Updated (IST)</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Attempts</th>
                  <th>Reason</th>
                  <th>Retry</th>
                </tr>
              </thead>
              <tbody>
                {data.failures.map((row) => (
                  <tr key={row.id}>
                    <td>{row.id}</td>
                    <td>{date(row.created_at)}</td>
                    <td>{date(row.updated_at)}</td>
                    <td>{row.kind}</td>
                    <td>{row.status}</td>
                    <td>{row.attempts}</td>
                    <td>
                      {row.code}
                      {row.code === 'SES_ACCESS_DENIED' && (
                        <small className="admin-cell-help">
                          SES rejected authorization. Review the worker IAM send policy and
                          sender/configuration-set permissions. Automatic retry is not enabled for
                          this error.
                        </small>
                      )}
                    </td>
                    <td>
                      {date(row.retry_at)}
                      {row.eligible_retry && (
                        <button disabled={busy} onClick={() => action('retry/' + row.id)}>
                          Retry eligible delivery
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>Uncertain sends are never blindly retried. Reconcile their SES events first.</p>
        </section>
      )}
    </section>
  );
}
