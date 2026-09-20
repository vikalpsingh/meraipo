import Link from 'next/link';
import { notFound } from 'next/navigation';
import { api } from '@/lib/api';
import { money, number, percent, date, timestamp, human } from '@/lib/format';
import type { Company, Quarter } from '@/lib/types';
import { Trust } from '@/components/content';
import { ApplicantGuide } from '@/components/applicant-guide';
import { LiveMarketData, AnnualHistory } from '@/components/market-data';
export const dynamic = 'force-dynamic';
async function getCompany(slug: string) {
  try {
    return await api<Company>('/companies/' + encodeURIComponent(slug) + '/journey');
  } catch (error) {
    if (error instanceof Error && error.message === 'NOT_FOUND') notFound();
    throw error;
  }
}
export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const c = await getCompany(slug);
  return {
    title: c.name + (c.status === 'LISTED' ? ' — Company Journey' : ' — IPO Application Guide'),
    description: `${c.name}: IPO baseline, quarterly results and stock performance.`,
    alternates: { canonical: '/ipo/' + slug },
    openGraph: {
      title: c.name + ' | MeraIPO',
      description: 'Follow the business beyond listing day.',
    },
  };
}
const metrics: [keyof Quarter, string, 'money' | 'percent'][] = [
  ['revenue', 'Revenue', 'money'],
  ['revenue_yoy', 'Revenue YoY', 'percent'],
  ['revenue_qoq', 'Revenue QoQ', 'percent'],
  ['ebitda', 'EBITDA', 'money'],
  ['ebitda_yoy', 'EBITDA YoY', 'percent'],
  ['ebitda_qoq', 'EBITDA QoQ', 'percent'],
  ['margin', 'EBITDA margin', 'percent'],
  ['margin_qoq_bps', 'Margin change QoQ (bps)', 'money'],
  ['margin_yoy_bps', 'Margin change YoY (bps)', 'money'],
  ['pat', 'PAT', 'money'],
  ['pat_yoy', 'PAT YoY', 'percent'],
  ['pat_qoq', 'PAT QoQ', 'percent'],
  ['eps', 'EPS (₹)', 'money'],
  ['cfo', 'Operating cash flow', 'money'],
  ['debt', 'Debt', 'money'],
  ['roe', 'ROE', 'percent'],
  ['roce', 'ROCE', 'percent'],
];
export default async function Journey({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ fy?: string }>;
}) {
  const [{ slug }, query] = await Promise.all([params, searchParams]);
  const c = await getCompany(slug);
  const years = [...new Set(c.quarters.map((q) => q.financial_year))].sort((a, b) => b - a);
  const year = query.fy ? Number(query.fy) : null;
  const quarters = [...c.quarters]
    .reverse()
    .filter((q) => !year || q.financial_year === year)
    .slice(0, 8);
  const displayMetrics: typeof metrics = ['BANK', 'NBFC', 'INSURANCE'].includes(
    c.company_type || '',
  )
    ? [
        ['total_income', 'Total income', 'money'],
        ['net_interest_income', 'Net interest income', 'money'],
        ['operating_profit', 'Operating profit', 'money'],
        ['pat', 'PAT', 'money'],
        ['pat_yoy', 'PAT YoY', 'percent'],
        ['eps', 'EPS (₹)', 'money'],
        ['aum', 'AUM', 'money'],
        ['gnpa', 'GNPA', 'percent'],
        ['nnpa', 'NNPA', 'percent'],
      ]
    : metrics;
  return (
    <main>
      <div className="breadcrumb">
        <Link href={c.status === 'LISTED' ? '/tracker' : '/'}>
          {c.status === 'LISTED' ? 'IPO Tracker' : 'IPO Now'}
        </Link>{' '}
        / {c.name}
      </div>
      <div className="page-heading">
        <div>
          <p className="eyebrow">
            {c.ticker || 'SYMBOL PENDING'} · {c.exchange || 'EXCHANGE PENDING'} · {c.board}
          </p>
          <h1>
            {c.name}
            <span>.</span>
          </h1>
          <p>
            {c.sector} ·{' '}
            {c.status === 'LISTED' ? 'Listed ' + date(c.listing_date) : human(c.status)}
          </p>
        </div>
        <Trust company={c} />
      </div>
      {c.status === 'LISTED' ? (
        <details className="panel" suppressHydrationWarning>
          <summary>Original IPO guide & application dates</summary>
          <ApplicantGuide company={c} />
        </details>
      ) : (
        <ApplicantGuide company={c} />
      )}
      {c.status !== 'LISTED' && <LiveMarketData company={c} />}
      <details
        id="financials"
        className="financial-details"
        suppressHydrationWarning
        open={c.status === 'LISTED'}
      >
        <summary>Financial history & source documents</summary>
        <div className="stats">
          <div>
            <small>IPO BASELINE PRICE</small>
            <strong>{money(c.issue_price ?? c.price_high)}</strong>
            <span>Original issue</span>
          </div>
          <div>
            <small>CURRENT PRICE</small>
            <strong>{money(c.cmp)}</strong>
            <span>{c.price_date ? 'EOD ' + date(c.price_date) : 'Price pending'}</span>
          </div>
          <div>
            <small>SINCE IPO</small>
            <strong>{percent(c.return_ipo)}</strong>
            <span>Price return only</span>
          </div>
          <div className="dark-stat">
            <small>FROM RECORDED ATH</small>
            <strong>{percent(c.drawdown)}</strong>
            <span>Historical peak comparison</span>
          </div>
        </div>
        <section className="business-strip">
          <div>
            <p className="eyebrow">BUSINESS VS PRICE</p>
            <h2>{c.business_vs_price}</h2>
            <p>{c.trend.reason}</p>
          </div>
          <Link href="/methodology">How this is calculated ↗</Link>
        </section>
        <section>
          <div className="section-heading">
            <h2>The quarterly journey</h2>
            <span>₹ Cr except EPS and ratios</span>
          </div>
          <nav className="screen-tabs" aria-label="Financial years">
            <Link href={'/ipo/' + slug} aria-current={!year ? 'page' : undefined}>
              Latest 8 quarters
            </Link>
            {years.map((y) => (
              <Link
                key={y}
                href={'/ipo/' + slug + '?fy=' + y}
                aria-current={y === year ? 'page' : undefined}
              >
                FY{y}
              </Link>
            ))}
          </nav>
          <div className="panel table-panel">
            <div
              className="table-scroll"
              tabIndex={0}
              role="region"
              aria-label="Quarterly financial history"
            >
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Financial metric</th>
                    <th scope="col">IPO baseline</th>
                    {quarters.map((q) => (
                      <th scope="col" key={q.label}>
                        {q.label}
                        <br />
                        <small>{human(q.statement_type || 'Standalone')}</small>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {displayMetrics.map(([key, label, format]) => (
                    <tr key={key}>
                      <th scope="row">{label}</th>
                      <td>
                        {format === 'percent'
                          ? percent(c.baseline?.[key] as number | null)
                          : number(c.baseline?.[key] as number | null)}
                      </td>
                      {quarters.map((q) => (
                        <td key={q.label}>
                          {format === 'percent'
                            ? percent(q[key] as number | null)
                            : number(q[key] as number | null)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          {!quarters.length && (
            <p className="empty">
              Quarterly results are not available yet. The original IPO baseline is retained
              separately.
            </p>
          )}
          <p className="screen-note">
            “—” means unavailable, not zero. Year-on-year growth requires a positive comparable
            period. Cash flow is shown only when reported for that period.
          </p>
        </section>
        <AnnualHistory company={c} />
        <div className="journey-grid">
          <section className="panel">
            <h2>Stock journey</h2>
            <dl className="detail-list">
              {[
                ['Listing price', money(c.listing_price)],
                ['Since listing', percent(c.return_listing)],
                ['All-time high', money(c.ath)],
                ['52-week high / low', money(c.high_52w) + ' / ' + money(c.low_52w)],
                ...Object.entries(c.performance || {}).map(([k, v]) => [k + ' return', percent(v)]),
              ].map(([k, v]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
          </section>
          <section className="panel">
            <h2>Valuation snapshot</h2>
            <p>{c.valuation_label}</p>
            <dl className="detail-list">
              {[
                ['IPO P/E', number(c.baseline?.pe)],
                ['Current P/E', number(c.valuation?.pe)],
                ['Peer median P/E', number(c.valuation?.peer_median_pe)],
                ['Market cap (₹ Cr)', number(c.valuation?.market_cap)],
                ['EV / EBITDA', number(c.valuation?.ev_ebitda)],
              ].map(([k, v]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
          </section>
        </div>
        <section className="panel">
          <h2>Sources & further research</h2>
          <details>
            <summary>Filing sources & update times</summary>
            {quarters.map((q) => (
              <p key={q.label}>
                <a href={q.source_url} target="_blank" rel="noreferrer">
                  {q.label} · {q.source_provider || 'Recorded source'} ↗
                </a>
                <br />
                <small>
                  Filed: {timestamp(q.source_timestamp)} · MeraIPO updated:{' '}
                  {timestamp(q.fetched_at)} · Revision {q.revision}
                </small>
              </p>
            ))}
          </details>
          <div className="research-links">
            {c.screener_url && (
              <a href={c.screener_url} target="_blank" rel="noreferrer">
                View on Screener ↗
              </a>
            )}
            {c.exchange_url && (
              <a href={c.exchange_url} target="_blank" rel="noreferrer">
                Exchange company page ↗
              </a>
            )}
            {c.documents?.map((d) => (
              <a href={d.url} key={d.url} target="_blank" rel="noreferrer">
                {d.kind} ↗
              </a>
            ))}
            {c.quarters.at(-1) && (
              <a href={c.quarters.at(-1)!.source_url} target="_blank" rel="noreferrer">
                Latest results document ↗
              </a>
            )}
          </div>
          {c.is_demo && (
            <p>
              These are fictional fixture records. Example source URLs illustrate provenance and are
              not actual company filings.
            </p>
          )}
          <details>
            <summary>Source and verification record</summary>
            {c.sources?.slice(0, 20).map((s, i) => (
              <p key={i}>
                <a href={s.source_url} target="_blank" rel="noreferrer">
                  {human(s.field_name)} ↗
                </a>{' '}
                · {human(s.verification_status)} · {timestamp(s.fetched_at)}
              </p>
            ))}
          </details>
        </section>
      </details>
    </main>
  );
}
