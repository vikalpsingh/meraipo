import Link from 'next/link';
import { api } from '@/lib/api';
import { features } from '@/lib/features';
import type { Company, SiteMessage, Advertisement } from '@/lib/types';
import { IPOCard, Message, Ads } from '@/components/content';
import { TodayActions } from '@/components/applicant-guide';
import { IPOInterestTable } from '@/components/ipo-interest-table';
import { IPOStageTabs } from '@/components/ipo-stage-tabs';
import { IPOSearch } from '@/components/ipo-search';
import { indiaDay } from '@/lib/applicant';
export const dynamic = 'force-dynamic';
export const metadata = { alternates: { canonical: '/' } };
export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ q?: string | string[] }>;
}) {
  const params = await searchParams;
  const flags = await features();
  const query = typeof params.q === 'string' ? params.q.trim().slice(0, 120) : '';
  const [open, upcoming, recent, message, ads] = await Promise.all([
    api<{ items: Company[] }>('/ipos/open'),
    api<{ items: Company[] }>('/ipos/upcoming'),
    api<{ items: Company[] }>('/ipos/recent'),
    api<{ message: SiteMessage | null }>('/site/message'),
    api<{ items: Advertisement[] }>('/site/advertisements'),
  ]);
  const now = new Date();
  const today = indiaDay(now);
  open.items.sort((a, b) => (a.close_date || '9999').localeCompare(b.close_date || '9999'));
  const announced = upcoming.items.filter((c) => c.lifecycle === 'ANNOUNCED' || !c.open_date);
  const scheduled = upcoming.items.filter((c) => !announced.includes(c));
  const closed = recent.items.filter((c) => c.status === 'CLOSED');
  const sections: [string, Company[], string][] = [
    ['Open for subscription', open.items, 'open'],
    ['Coming next', scheduled, 'upcoming'],
    ['Closed · awaiting listing', closed, 'closed'],
    ['Announced · dates awaited', announced, 'announced'],
    ...(query
      ? [
          ['Listed companies', recent.items.filter((c) => c.status === 'LISTED'), 'listed'] as [
            string,
            Company[],
            string,
          ],
        ]
      : []),
  ];
  const matches = sections.map(
    ([title, items, id]) =>
      [
        title,
        items.filter(
          (c) =>
            !query || `${c.name} ${c.ticker || ''}`.toLowerCase().includes(query.toLowerCase()),
        ),
        id,
      ] as [string, Company[], string],
  );
  const total = matches.reduce((sum, [, items]) => sum + items.length, 0);
  function renderSection([title, items, id]: [string, Company[], string]) {
    return (
      <section id={String(id)} className="ipo-section" key={String(id)}>
        <div className="section-heading">
          <h2>{String(title)}</h2>
          <span>{(items as Company[]).length} issues</span>
        </div>
        {(items as Company[]).length ? (
          <div>
            <IPOInterestTable companies={items as Company[]} today={today} />
            <div className="ipo-grid ipo-mobile-cards">
              {(items as Company[]).map((c) => (
                <IPOCard key={c.id} company={c} today={today} />
              ))}
            </div>
          </div>
        ) : (
          <div className="panel empty">No issues in this stage right now.</div>
        )}
      </section>
    );
  }
  return (
    <main className="ipo-home">
      <div className="page-heading">
        <div>
          <p className="eyebrow">THE PRIMARY MARKET</p>
          <h1>
            IPOs at a glance<span>.</span>
          </h1>
          <p>Understand the business. Plan your application. Follow what happens next.</p>
        </div>
        <div className="home-tools">
          {flags.ipo_tracker && (
            <Link className="outline-button" href="/tracker">
              Track listed companies ↗
            </Link>
          )}
          <IPOSearch key={query} query={query} />
        </div>
      </div>
      {query ? (
        <p className="search-feedback" role="status">
          {total} {total === 1 ? 'company' : 'companies'} matching “{query}”
        </p>
      ) : (
        <TodayActions now={now} companies={[...open.items, ...upcoming.items, ...recent.items]} />
      )}
      {!query && (
        <div className="market-counts">
          <span>
            <b>{open.items.length}</b> open
          </span>
          <span>
            <b>{scheduled.length}</b> upcoming
          </span>
          <span>
            <b>{closed.length}</b> awaiting listing
          </span>
          {!!announced.length && (
            <span>
              <b>{announced.length}</b> announced
            </span>
          )}
          <a href="#upcoming">Jump to upcoming ↓</a>
        </div>
      )}
      {query && !total && (
        <section className="panel empty">
          <h2>No matching companies</h2>
          <p>Try a shorter company name or its stock symbol.</p>
          <Link className="outline-button" href="/">
            Show all IPOs
          </Link>
        </section>
      )}
      {query ? (
        matches.filter(([, items]) => items.length).map(renderSection)
      ) : (
        <>
          <IPOStageTabs
            stages={matches.slice(0, 3).map((section) => ({
              id: section[2],
              title: section[0],
              count: section[1].length,
              content: renderSection(section),
            }))}
          />
          {matches.slice(3).map(renderSection)}
        </>
      )}
      <p className="gmp-disclaimer">
        Unofficial grey-market information. GMP does not guarantee listing price or investment
        return.
      </p>
      <Message message={message.message} />
      <aside className="panel section-heading" aria-label="Help improve MeraIPO">
        <div>
          <h2>What should we build next?</h2>
          <p>Share an idea or vote for features other investors want.</p>
        </div>
        <Link href="/feedback" className="outline-button">
          Share feedback
        </Link>
      </aside>
      <Ads items={ads.items} />
    </main>
  );
}
