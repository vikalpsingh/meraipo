'use client';
import { useState } from 'react';
type Schedule = { mode: 'opening' | 'closing' | 'both'; time: string };

export function EmailApplicationSchedule({
  csrf,
  config,
  onSaved,
}: {
  csrf: string;
  config: Schedule;
  onSaved: () => Promise<void>;
}) {
  const [mode, setMode] = useState(config.mode);
  const [time, setTime] = useState(config.time);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [testId, setTestId] = useState('');
  async function request(path: string, method: string, body?: object) {
    setBusy(true);
    try {
      const response = await fetch('/api/v1/admin/email/' + path, {
        method,
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: body ? JSON.stringify(body) : undefined,
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || result.error?.message || 'Request failed');
      if (path === 'application-test') setTestId(result.id);
      setMessage(
        result.message ||
          `Test status: ${result.status}. ${result.error_code || ''} ${result.delivered_at ? 'Recipient mail server accepted delivery.' : 'Inbox delivery not confirmed yet.'}`,
      );
      if (path === 'application-schedule') await onSaved();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Request failed');
    } finally {
      setBusy(false);
    }
  }
  const unsaved = mode !== config.mode || time !== config.time;
  return (
    <section className="category-mailer" aria-labelledby="application-reminder-heading">
      <h3 id="application-reminder-heading">IPO application reminders</h3>
      <p>
        One combined email per eligible subscriber per day, filtered by their confirmed GMP
        preference. Closing-day reminders help users check their broker before bidding ends.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void request('application-schedule', 'PUT', { mode, time });
        }}
      >
        <div className="category-mailer-fields">
          <label>
            Send reminders on
            <select
              value={mode}
              disabled={busy}
              onChange={(e) => setMode(e.target.value as Schedule['mode'])}
            >
              <option value="opening">Opening day only</option>
              <option value="closing">Last application day only</option>
              <option value="both">Opening and last application days</option>
            </select>
          </label>
          <label>
            Send time (IST)
            <input
              type="time"
              required
              value={time}
              disabled={busy}
              onChange={(e) => setTime(e.target.value)}
            />
          </label>
        </div>
        <p>
          Changes apply to the next daily snapshot. Saving this schedule does not enable production
          sending.
        </p>
        <button type="submit" disabled={busy || !time}>
          Save reminder schedule
        </button>
      </form>
      <div className="category-mailer-footer">
        <span>Today’s end-to-end test · meshanti.singh@gmail.com · All IPOs preference</span>
        <button disabled={busy || unsaved} onClick={() => void request('application-test', 'POST')}>
          Send today’s combined test
        </button>
        {testId && (
          <button disabled={busy} onClick={() => void request('application-test/' + testId, 'GET')}>
            Check test delivery
          </button>
        )}
      </div>
      <p>
        The test uses saved opening/closing rules and verified IPOs for today, through the real SES
        outbox. It sends one email, bypasses the scheduled time and production-dispatch switch, and
        does not change anyone’s subscription. Save changes before testing.
      </p>
      <p>
        Recipients are addressed separately with private unsubscribe links. Category content is
        generated once and reused in queued batches; recipient addresses are never shared.
      </p>
      <p role="status">{message}</p>
    </section>
  );
}
