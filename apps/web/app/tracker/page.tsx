import Link from 'next/link';
import { api } from '@/lib/api';
import { money, percent, date, human, fiscalToday } from '@/lib/format';
import type { TrackerResult, Advertisement } from '@/lib/types';
import { Trust, Ads } from '@/components/content';
export const dynamic = 'force-dynamic';
export const metadata = { title: 'IPO Tracker', alternates: { canonical: '/tracker' } };
const views = [
  ['recent', 'Recent IPOs'],
  ['improving', 'Business improving'],
  ['corrected', 'Price corrected'],
  ['improving-corrected', 'Improving + corrected'],
  ['below-ipo', 'Below IPO price'],
  ['high-growth', 'High growth'],
  ['pending', 'Data pending'],
];
export default async function Tracker({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const input = await searchParams;
  const today = fiscalToday();
  const query = new URLSearchParams();
  for (const [k, v] of Object.entries(input)) if (v !== undefined) query.set(k, v);
  if (input.fy === undefined) query.set('fy', String(today.fy));
  if (input.quarter === undefined) query.set('quarter', String(today.quarter));
  const apiQuery = new URLSearchParams([...query].filter(([, value]) => value !== ''));
  const [data, ads] = await Promise.all([
    api<TrackerResult>('/tracker?' + apiQuery),
    api<{ items: Advertisement[] }>('/site/advertisements?placement=tracker'),
  ]);
  const href = (key: string, value: string) => {
    const q = new URLSearchParams(query);
    q.set(key, value);
    if (key !== 'page') q.delete('page');
    return '/tracker?' + q;
  };
  return (
    <main>
      <div className="page-heading">
        <div>
          <p className="eyebrow">THE LONG-TERM VIEW</p>
          <h1>
            Follow the business<span>.</span>
          </h1>
          <p>One company. Every quarter. A clearer perspective.</p>
        </div>
        <span className="badge">{data.total} companies in this view</span>
      </div>
      <nav className="screen-tabs" aria-label="Screening views">
        {views.map(([value, label]) => (
          <Link
            aria-current={(query.get('view') || 'recent') === value ? 'page' : undefined}
            key={value}
            href={href('view', value)}
          >
            {label}
          </Link>
        ))}
      </nav>
      {(query.get('fy') || query.get('quarter')) && (
        <p className="listing-scope">
          Listing dates: {query.get('fy') ? `FY${query.get('fy')}` : 'all years'}
          {query.get('quarter') ? ` · Q${query.get('quarter')}` : ' · all quarters'}.{' '}
          <Link href="/tracker?fy=&quarter=">Browse all listing dates →</Link>
        </p>
      )}
      <p className="screen-note">
        Screening views for further research, not investment recommendations. “Corrected” means at
        least 20% below the recorded all-time high.
      </p>
      <form className="filters" action="/tracker">
        <input type="hidden" name="view" value={query.get('view') || 'recent'} />
        <label>
          Financial year
          <select aria-label="Financial year" name="fy" defaultValue={query.get('fy') || ''}>
            <option value="">All years</option>
            {[...new Set([today.fy, ...data.financial_years])]
              .sort((a, b) => b - a)
              .map((y) => (
                <option key={y} value={y}>
                  FY{y}
                </option>
              ))}
          </select>
        </label>
        <label>
          Listing quarter
          <select
            aria-label="Listing quarter"
            name="quarter"
            defaultValue={query.get('quarter') || ''}
          >
            <option value="">All quarters</option>
            {[1, 2, 3, 4].map((q) => (
              <option key={q} value={q}>
                Q{q}
              </option>
            ))}
          </select>
        </label>
        <label>
          Board
          <select aria-label="Board" name="board" defaultValue={input.board || ''}>
            <option value="">All boards</option>
            <option>Mainboard</option>
            <option>SME</option>
          </select>
        </label>
        <label>
          Sector
          <select aria-label="Sector" name="sector" defaultValue={input.sector || ''}>
            <option value="">All sectors</option>
            {data.sectors.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <button className="primary-button">Apply filters</button>
        <Link href="/tracker?fy=&quarter=" className="text-link">
          Clear filters
        </Link>
        <details className="advanced-filters">
          <summary>More research filters</summary>
          <div className="form-grid">
            {[
              ['min_return', 'Min IPO return (%)'],
              ['max_return', 'Max IPO return (%)'],
              ['min_drawdown', 'Min drawdown (%)'],
              ['max_drawdown', 'Max drawdown (%)'],
              ['min_revenue_growth', 'Min revenue YoY (%)'],
              ['min_pat_growth', 'Min PAT YoY (%)'],
              ['min_roce', 'Min ROCE (%)'],
              ['max_debt', 'Max debt (₹ Cr)'],
            ].map(([key, label]) => (
              <label key={key}>
                {label}
                <input name={key} type="number" step="any" defaultValue={input[key] || ''} />
              </label>
            ))}
            <label>
              Business trend
              <select name="trend" defaultValue={input.trend || ''}>
                <option value="">All trends</option>
                {['IMPROVING', 'STABLE', 'WEAKENING', 'INSUFFICIENT_DATA'].map((t) => (
                  <option key={t} value={t}>
                    {human(t)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Data quality
              <select name="quality" defaultValue={input.quality || ''}>
                <option value="">All data</option>
                {['VERIFIED', 'PARTIAL', 'STALE', 'UNVERIFIED', 'CONFLICT'].map((t) => (
                  <option key={t} value={t}>
                    {human(t)}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </details>
      </form>
      {data.items.length ? (
        <div className="panel table-panel">
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="IPO performance table"
          >
            <table className="data-table tracker-table">
              <thead>
                <tr>
                  {[
                    'Company',
                    'IPO / listing price',
                    'CMP / IPO return',
                    'Business trend',
                    'Latest quarter',
                    'Revenue YoY',
                    'PAT YoY',
                    'EBITDA margin',
                    'ROCE',
                    'From ATH',
                    'Valuation',
                    'Data',
                  ].map((h) => (
                    <th key={h} scope="col">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.items.map((c) => (
                  <tr key={c.id} data-testid="company-row">
                    <th scope="row">
                      <Link href={'/ipo/' + c.slug}>{c.name} ↗</Link>
                      <small>
                        {c.board} · {date(c.listing_date)}
                      </small>
                    </th>
                    <td>
                      {money(c.issue_price)}
                      <small>Listed {money(c.listing_price)}</small>
                    </td>
                    <td>
                      <b>{money(c.cmp)}</b>
                      <small
                        className={
                          c.return_ipo !== null && c.return_ipo < 0 ? 'negative' : 'positive'
                        }
                      >
                        {percent(c.return_ipo)} since IPO
                      </small>
                      <small>{percent(c.return_listing)} since listing</small>
                    </td>
                    <td>
                      <span className="trend-label">{human(c.trend.state)}</span>
                    </td>
                    <td>{c.latest.label || 'Data pending'}</td>
                    <td>{percent(c.latest.revenue_yoy)}</td>
                    <td>{percent(c.latest.pat_yoy)}</td>
                    <td>{percent(c.latest.margin)}</td>
                    <td>{percent(c.latest.roce)}</td>
                    <td>{percent(c.drawdown)}</td>
                    <td>
                      {c.valuation_label}
                      <small>P/E {c.valuation?.pe ?? '—'}</small>
                    </td>
                    <td>
                      <Trust company={c} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <section className="panel empty">
          <h2>No companies match these filters.</h2>
          <p>Try another financial year, quarter or screening view.</p>
          <Link className="outline-button" href="/tracker?fy=&quarter=">
            Show all companies
          </Link>
        </section>
      )}
      <div className="pagination">
        {data.page > 1 && <Link href={href('page', String(data.page - 1))}>← Previous</Link>}
        <span>
          Page {data.page} · {data.total} companies
        </span>
        {data.page * data.page_size < data.total && (
          <Link href={href('page', String(data.page + 1))}>Next →</Link>
        )}
      </div>
      <Ads items={ads.items} />
    </main>
  );
}
