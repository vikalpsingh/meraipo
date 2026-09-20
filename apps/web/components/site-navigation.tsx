'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
export function SiteNavigation() {
  const path = usePathname();
  return (
    <nav aria-label="Main navigation">
      {[
        ['/', 'Home'],
        ['/tracker', 'IPO Tracker'],
        ['/about', 'About / Methodology'],
      ].map(([href, label]) => (
        <Link
          key={href}
          href={href}
          aria-current={
            (
              href === '/'
                ? path === '/' || path === '/ipos'
                : href === '/about'
                  ? ['/about', '/methodology'].includes(path)
                  : path === href
            )
              ? 'page'
              : undefined
          }
        >
          {label}
        </Link>
      ))}
    </nav>
  );
}
