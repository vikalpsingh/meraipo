'use client';
import Link from 'next/link';
import { useEffect, useState } from 'react';

export function EmailSubscription({
  action = 'subscribe',
  onSubscribed,
}: {
  action?: string;
  onSubscribed?: () => void;
}) {
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
      if (action === 'subscribe') onSubscribed?.();
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
          ? 'Your next IPO starts here'
          : action === 'verify'
            ? 'Confirm your email'
            : 'Unsubscribe from alerts'}
      </h1>
      <p>
        {action === 'subscribe'
          ? 'Opening-day alerts, matched to your interests. Choose all IPOs or a minimum GMP threshold. One alert per IPO. GMP is unofficial and does not guarantee a listing gain.'
          : 'Use the button below to complete your request.'}
      </p>
      {!done && (
        <form onSubmit={submit}>
          {action === 'subscribe' ? (
            <>
              <div className="signup-fields">
                <label>
                  First name
                  <input
                    name="first_name"
                    placeholder="Your first name"
                    autoComplete="given-name"
                    maxLength={80}
                    required
                  />
                </label>
                <label>
                  Surname (last name)*
                  <input
                    name="last_name"
                    placeholder="Your surname"
                    autoComplete="family-name"
                    maxLength={80}
                    required
                  />
                </label>
                <label>
                  Email address
                  <input
                    name="email"
                    placeholder="you@example.com"
                    type="email"
                    autoComplete="email"
                    maxLength={254}
                    required
                  />
                </label>
                <label>
                  Phone No (optional)
                  <input
                    name="phone"
                    placeholder="Optional phone number"
                    type="tel"
                    autoComplete="tel"
                    maxLength={24}
                  />
                </label>
              </div>
              <p className="signup-private">
                Your contact details are not shared with marketing companies or brands. No marketing
                calls.
              </p>
              <fieldset className="gmp-preferences">
                <legend>What would you like to follow? Choose one.</legend>
                {[
                  ['white', 'neutral', 'All IPOs: every GMP level, including unavailable'],
                  ['light_green', 'light-green', 'Light green: above 20%'],
                  ['strong_green', 'dark-green', 'Stronger green: above 40%'],
                  ['gold', 'gold', 'Gold: above 100%'],
                ].map(([value, tone, label]) => (
                  <label key={value}>
                    <input type="radio" name="gmp_band" value={value} required />
                    <span className={`gmp-legend-swatch ipo-gmp--${tone}`} aria-hidden="true" />
                    {label}
                  </label>
                ))}
              </fieldset>
              <label className="email-consent">
                <input name="consent" type="checkbox" required /> I agree to receive MeraIPO IPO
                reminders. I can unsubscribe at any time.
              </label>
              <p>
                Your email address is your unique subscription key. Enter the same address again to
                replace your details and preferences after email confirmation. Contact details are
                encrypted. Your preference changes apply only after confirmation. Delivery and link
                interactions are recorded to improve alerts; website analytics requires separate
                consent. <Link href="/privacy">Privacy policy</Link>.
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
