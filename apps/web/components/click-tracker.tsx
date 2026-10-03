'use client';
import { useEffect } from 'react';
import { usePathname } from 'next/navigation';

export function clickSection(path: string): string | null {
  if (path === '/meraadmin' || path.startsWith('/meraadmin/')) return null;
  if (path === '/') return 'home';
  if (path === '/ipos') return 'ipos';
  if (path.startsWith('/ipo/') || path.startsWith('/company/')) return 'company';
  if (path === '/tracker') return 'tracker';
  if (path === '/feedback') return 'feedback';
  if (
    [
      '/about',
      '/methodology',
      '/data-sources',
      '/disclaimer',
      '/privacy',
      '/terms',
      '/contact',
    ].includes(path)
  )
    return 'information';
  return 'other';
}

export function ClickTracker() {
  const path = usePathname();
  useEffect(() => {
    const section = clickSection(path);
    if (!section || navigator.doNotTrack === '1') return;
    let pending = 0;
    function flush() {
      if (!pending) return;
      const body = JSON.stringify({ section, count: pending });
      pending = 0;
      // Best effort: never retry or block navigation if analytics is unavailable.
      try {
        if (
          navigator.sendBeacon?.(
            '/api/v1/analytics/clicks',
            new Blob([body], { type: 'application/json' }),
          )
        )
          return;
        void fetch('/api/v1/analytics/clicks', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body,
          keepalive: true,
        }).catch(() => {});
      } catch {
        /* Analytics must never interrupt the site. */
      }
    }
    function clicked(event: MouseEvent) {
      if (!event.isTrusted || !(event.target instanceof Element)) return;
      const control = event.target.closest('a,button,[role="button"]');
      if (!control || control.matches(':disabled,[aria-disabled="true"]')) return;
      if (
        control instanceof HTMLAnchorElement &&
        new URL(control.href, location.href).pathname.startsWith('/meraadmin')
      )
        return;
      pending += 1;
      if (pending >= 100) flush();
    }
    function hidden() {
      if (document.visibilityState === 'hidden') flush();
    }
    document.addEventListener('click', clicked, true);
    document.addEventListener('visibilitychange', hidden);
    window.addEventListener('pagehide', flush);
    const timer = window.setInterval(flush, 15000);
    return () => {
      document.removeEventListener('click', clicked, true);
      document.removeEventListener('visibilitychange', hidden);
      window.removeEventListener('pagehide', flush);
      window.clearInterval(timer);
      flush();
    };
  }, [path]);
  return null;
}
