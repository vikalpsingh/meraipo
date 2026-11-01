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
              ? {
                  email: values.get('email'),
                  first_name: values.get('first_name'),
                  last_name: values.get('last_name'),
                  phone: values.get('phone'),
                  gmp_band: values.get('gmp_band'),
                  consent: values.get('consent') === 'on',
                }
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
          ? 'Get an alert on the IPO opening day only when the latest available GMP matches your selected band. One alert per IPO. Stale or missing GMP counts as unavailable. GMP is unofficial and cannot guarantee listing gains. Dates can change; check the IPO guide for the latest details.'
          : 'Use the button below to complete your request.'}
      </p>
      {!done && (
        <form onSubmit={submit}>
          {action === 'subscribe' ? (
            <>
              <label>
                First name
                <input name="first_name" autoComplete="given-name" maxLength={80} required />
              </label>
              <label>
                Last name
                <input name="last_name" autoComplete="family-name" maxLength={80} required />
              </label>
              <label>
                Phone number (optional)*
                <input name="phone" type="tel" autoComplete="tel" maxLength={24} />
              </label>
              <p>
                * We do not share your contact details with marketing companies or brands. Phone is
                optional and is not used for marketing calls.
              </p>
              <fieldset className="gmp-preferences">
                <legend>Choose one GMP band (required)</legend>
                {[
                  ['white', 'neutral', 'White: 20% or below, or unavailable'],
                  ['light_green', 'light-green', 'Light green: above 20% to 40%'],
                  ['strong_green', 'dark-green', 'Stronger green: above 40% to 100%'],
                  ['gold', 'gold', 'Gold: above 100%'],
                ].map(([value, tone, label]) => (
                  <label key={value}>
                    <input type="radio" name="gmp_band" value={value} required />
                    <span className={`gmp-legend-swatch ipo-gmp--${tone}`} aria-hidden="true" />
                    {label}
                  </label>
                ))}
              </fieldset>
              <label>
                Email address
                <input name="email" type="email" autoComplete="email" maxLength={254} required />
              </label>
              <label className="email-consent">
                <input name="consent" type="checkbox" required /> I agree to receive MeraIPO IPO
                reminders. I can unsubscribe at any time.
              </label>
              <p>
                We send a confirmation first. Contact details are stored encrypted. Your preference
                changes apply only after confirmation. Delivery and link interactions are recorded
                to improve alerts; website analytics requires separate consent.{' '}
                <Link href="/privacy">Privacy policy</Link>.
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
