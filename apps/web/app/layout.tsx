import type { Metadata } from 'next';
import Link from 'next/link';
import './globals.css';
import { SiteNavigation } from '@/components/site-navigation';
import { features } from '@/lib/features';
import { Brand } from '@/components/brand';
const origin = process.env.SITE_URL || 'http://localhost:3000';
export const metadata: Metadata = {
  metadataBase: new URL(origin),
  title: { default: 'MeraIPO — From IPO to Value Creator', template: '%s | MeraIPO' },
  description:
    'Follow Indian IPOs beyond listing day. Compare business performance, quarterly results and price returns.',
  openGraph: {
    type: 'website',
    title: 'MeraIPO — From IPO to Value Creator',
    description: 'IPO research, one quarter at a time.',
  },
  twitter: { card: 'summary' },
  icons: { icon: { url: '/favicon.svg?v=market-logo-2', type: 'image/svg+xml' } },
};
export default async function Layout({ children }: { children: React.ReactNode }) {
  const flags = await features();
  return (
    <html lang="en">
      <body>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <header className="site-header">
          <Link href="/" className="brand" aria-label="MeraIPO home">
            <Brand />
          </Link>
          <SiteNavigation trackerEnabled={flags.ipo_tracker === true} />
          <span className="header-label">INDIA · LONG-TERM RESEARCH</span>
        </header>
        {process.env.NEXT_PUBLIC_DEMO_MODE === 'true' && (
          <div className="demo-banner">
            DEMO EDITION <span>Fictional companies and fixture values. No live market data.</span>
          </div>
        )}
        <div id="main" tabIndex={-1}>
          {children}
        </div>
        <footer>
          <div className="footer-top">
            <Link className="brand" href="/" aria-label="MeraIPO home">
              <Brand />
            </Link>
            <nav aria-label="Information">
              {['methodology', 'data-sources', 'disclaimer', 'privacy', 'terms', 'contact'].map(
                (path) => (
                  <Link key={path} href={'/' + path}>
                    {path.replace('-', ' ')}
                  </Link>
                ),
              )}
            </nav>
          </div>
          <p>
            MeraIPO provides IPO, market and company information for research and educational
            purposes. It does not guarantee IPO allotment, listing gains or investment returns.
          </p>
        </footer>
      </body>
    </html>
  );
}
