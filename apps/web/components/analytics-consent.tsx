'use client';
import Script from 'next/script';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
type AnalyticsWindow = Window & {
  dataLayer?: unknown[];
  gtag?: (...args: unknown[]) => void;
} & Partial<Record<`ga-disable-${string}`, boolean>>;
export function AnalyticsConsent({ measurementId }: { measurementId: string }) {
  const pathname = usePathname();
  const [consent, setConsent] = useState('');
  const [ready, setReady] = useState(false);
  const excluded = pathname.startsWith('/meraadmin') || pathname.startsWith('/email-alerts/');
  const configured = /^G-[A-Z0-9]+$/.test(measurementId);
  useEffect(() => {
    try {
      // Hydrate the browser-only consent choice after server rendering.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setConsent(localStorage.getItem('meraipo-analytics-consent') || '');
    } catch {
      setConsent('denied');
    }
  }, []);
  useEffect(() => {
    if (!configured) return;
    const w = window as unknown as AnalyticsWindow;
    w[`ga-disable-${measurementId}`] = consent !== 'granted' || excluded;
    if (!ready || consent !== 'granted' || excluded) return;
    const location = new URL(window.location.origin + pathname);
    const source = new URLSearchParams(window.location.search);
    // Only fixed attribution values and the actual public IPO slug may reach Google.
    if (
      source.get('utm_source') === 'meraipo_email' &&
      (pathname === '/' || /^\/ipo\/[a-z0-9-]+$/.test(pathname))
    ) {
      location.search = new URLSearchParams({
        utm_source: 'meraipo_email',
        utm_medium: 'email',
        utm_campaign:
          source.get('utm_campaign') === 'ipo_opening' ? 'ipo_opening' : 'ipo_prelisting',
        utm_content: pathname === '/' ? 'homepage' : pathname.split('/').pop()!,
      }).toString();
    }
    // Use the page's public title, omitting any user-entered query or fragment.
    const title = document.title.split('?')[0].split('#')[0] || 'MeraIPO';
    w.gtag?.('config', measurementId, {
      send_page_view: false,
      allow_google_signals: false,
      allow_ad_personalization_signals: false,
      page_location: location.toString(),
      page_referrer: '',
      page_title: title,
    });
    w.gtag?.('event', 'page_view', {
      page_location: location.toString(),
      page_referrer: '',
      page_title: title,
    });
  }, [pathname, consent, ready, excluded, configured, measurementId]);
  function choose(value: string) {
    const w = window as unknown as AnalyticsWindow;
    w[`ga-disable-${measurementId}`] = value !== 'granted';
    try {
      localStorage.setItem('meraipo-analytics-consent', value);
    } catch {
      /* This choice still applies for this page. */
    }
    setConsent(value);
    if (value === 'denied') {
      w.gtag?.('consent', 'update', { analytics_storage: 'denied' });
      for (const cookie of document.cookie.split(';')) {
        const name = cookie.split('=')[0].trim();
        if (!name.startsWith('_ga')) continue;
        const parts = window.location.hostname.split('.');
        document.cookie = `${name}=; Max-Age=0; path=/; SameSite=Lax`;
        for (let i = 0; i < parts.length - 1; i++)
          document.cookie = `${name}=; Max-Age=0; path=/; domain=.${parts.slice(i).join('.')}; SameSite=Lax`;
      }
    } else w.gtag?.('consent', 'update', { analytics_storage: 'granted' });
  }
  if (!configured || excluded) return null;
  return (
    <div className="analytics-consent">
      {consent === 'granted' && (
        <Script
          id="meraipo-ga4"
          src={`https://www.googletagmanager.com/gtag/js?id=${measurementId}`}
          strategy="afterInteractive"
          onReady={() => {
            const w = window as unknown as AnalyticsWindow;
            w.dataLayer = w.dataLayer || [];
            w.gtag =
              w.gtag ||
              function () {
                // gtag expects the standard Arguments command shape.
                // eslint-disable-next-line prefer-rest-params
                w.dataLayer!.push(arguments);
              };
            w.gtag('consent', 'default', {
              analytics_storage: 'granted',
              ad_storage: 'denied',
              ad_user_data: 'denied',
              ad_personalization: 'denied',
            });
            w.gtag('js', new Date());
            setReady(true);
          }}
        />
      )}
      {!consent ? (
        <>
          <p>
            Allow optional Google Analytics to help us understand website visits? Email alerts work
            without it.
          </p>
          <button onClick={() => choose('granted')}>Allow analytics</button>{' '}
          <button onClick={() => choose('denied')}>Decline</button>
        </>
      ) : (
        <button onClick={() => choose(consent === 'granted' ? 'denied' : 'granted')}>
          {consent === 'granted' ? 'Disable website analytics' : 'Enable website analytics'}
        </button>
      )}
    </div>
  );
}
