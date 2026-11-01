'use client';
import Link from 'next/link';
import { useEffect, useState } from 'react';

export function EmailSubscription({ action = 'subscribe' }: { action?: string }) {
  const [token, setToken] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  useEffect(() => {
    if (action !== 'subscribe' && window.location.hash) {
      // Transfer a private fragment to memory once, then remove it from the address bar.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setToken(window.location.hash.slice(1));
      window.history.replaceState(window.history.state, '', window.location.pathname);
    }
  }, [action]);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage('');
    const values = new FormData(event.currentTarget);
    try {
      const response = await fetch(
        `/api/v1/ipo-alerts/${action === 'verify' ? 'confirm' : action}`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(
            action === 'subscribe'
              ? { email: values.get('email'), consent: values.get('consent') === 'on' }
              : { token },
          ),
        },
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data.error?.message || 'Please try again later.');
      setMessage(data.message);
      setDone(true);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Service unavailable');
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="email-signup panel">
      <h1>
        {action === 'subscribe'
          ? 'IPO email alerts'
          : action === 'verify'
            ? 'Confirm your email'
            : 'Unsubscribe from alerts'}
      </h1>
      <p>
        {action === 'subscribe'
          ? 'Get an IPO reminder the day before confirmed listing with the latest recorded GMP, source and timestamp. GMP is unofficial and cannot guarantee listing gains. Dates can change; check the IPO guide for the latest details.'
          : 'Use the button below to complete your request.'}
      </p>
      {!done && (
        <form onSubmit={submit}>
          {action === 'subscribe' ? (
            <>
              <label>
                Email address
                <input name="email" type="email" autoComplete="email" maxLength={254} required />
              </label>
              <label className="email-consent">
                <input name="consent" type="checkbox" required /> I agree to receive MeraIPO IPO
                reminders. I can unsubscribe at any time.
              </label>
              <p>
                We send a confirmation first. Email addresses are stored encrypted. Delivery and
                link interactions are recorded to improve alerts; website analytics requires
                separate consent. <Link href="/privacy">Privacy policy</Link>.
              </p>
            </>
          ) : (
            !token && <p>Open the complete link from your email, or request a new confirmation.</p>
          )}
          <button type="submit" disabled={busy || (action !== 'subscribe' && !token)}>
            {busy
              ? 'Please wait…'
              : action === 'subscribe'
                ? 'Subscribe to IPO alerts'
                : action === 'verify'
                  ? 'Confirm subscription'
                  : 'Unsubscribe'}
          </button>
        </form>
      )}
      <p role="status">{message}</p>
    </section>
  );
}
