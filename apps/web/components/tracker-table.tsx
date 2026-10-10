import Link from 'next/link';
import type { ReactNode } from 'react';
import type { Company } from '@/lib/types';
import { date, human, money, number, percent } from '@/lib/format';
import { Trust } from './content';
type Column = {
  label: string;
  available: (c: Company) => boolean;
  render: (c: Company) => ReactNode;
};
const metric = (label: string, key: keyof Company['latest'], percentage = false): Column => ({
  label,
  available: (c) => c.latest[key] != null,
  render: (c) => (percentage ? percent : number)(c.latest[key] as number | null | undefined),
});
const research: Column[] = [
  {
    label: 'Latest quarter',
    available: (c) => !!c.latest.label,
    render: (c) => c.latest.label || <Link href={'/ipo/' + c.slug}>No validated quarter yet</Link>,
  },
  metric('Revenue (₹ crore)', 'revenue'),
  metric('PAT (₹ crore)', 'pat'),
  metric('EPS (₹)', 'eps'),
  metric('Revenue YoY', 'revenue_yoy', true),
  metric('PAT YoY', 'pat_yoy', true),
  {
    label: 'Business trend',
    available: (c) => c.trend.state !== 'INSUFFICIENT_DATA',
    render: (c) => <span className="trend-label">{human(c.trend.state)}</span>,
  },
  metric('EBITDA margin', 'margin', true),
  metric('ROCE', 'roce', true),
  {
    label: 'From recorded high',
    available: (c) => c.drawdown != null,
    render: (c) => percent(c.drawdown),
  },
  {
    label: 'Valuation',
    available: (c) => c.valuation?.pe != null,
    render: (c) => (
      <>
        {c.valuation_label}
        <small>P/E {c.valuation?.pe ?? '—'}</small>
      </>
    ),
  },
];
function Gain({ value }: { value: number | null | undefined }) {
  return (
    <span className={value == null ? undefined : value < 0 ? 'negative' : 'positive'}>
      {percent(value)}
    </span>
  );
}
export function TrackerTable({ companies, query = '' }: { companies: Company[]; query?: string }) {
  const params = new URLSearchParams(query);
  const sortKeys: Record<string, string> = {
    'Gain since IPO': 'return_ipo',
    'From recorded high': 'drawdown',
  };
  const sortHref = (key: string) => {
    const next = new URLSearchParams(params);
    next.set('sort', key);
    next.set('order', params.get('sort') === key && params.get('order') !== 'asc' ? 'asc' : 'desc');
    next.delete('page');
    return '/tracker?' + next;
  };
  const columns = [...research].sort(
    (a, b) => Number(companies.some(b.available)) - Number(companies.some(a.available)),
  );
  return (
    <>
      <p className="small">
        Listing price is the official listing-day closing price. Listing gain and gain since IPO use
        the IPO upper price band: (price ÷ upper band − 1) × 100. Returns exclude dividends and
        corporate-action adjustments. Available research columns appear before pending fields in
        this view. Light green rows indicate gains above 100%. Missing values sort last.
      </p>
      <div className="panel table-panel">
        <div className="table-scroll" tabIndex={0} role="region" aria-label="IPO performance table">
          <table className="data-table tracker-table">
            <thead>
              <tr>
                {[
                  'Company',
                  'Issue size (₹ crore)',
                  'IPO upper band',
                  'CMP',
                  'Gain since IPO',
                  'Listing price (day close)',
                  'Listing gain',
                  ...columns.map((c) => c.label),
                  'Data',
                ].map((label) => (
                  <th
                    key={label}
                    scope="col"
                    aria-sort={
                      sortKeys[label]
                        ? params.get('sort') === sortKeys[label]
                          ? params.get('order') === 'asc'
                            ? 'ascending'
                            : 'descending'
                          : 'none'
                        : undefined
                    }
                  >
                    {sortKeys[label] ? (
                      <Link href={sortHref(sortKeys[label])} title="Click to change sort direction">
                        {label}
                        <span aria-hidden="true">
                          {' '}
                          {params.get('sort') === sortKeys[label]
                            ? params.get('order') === 'asc'
                              ? '↑'
                              : '↓'
                            : '↕'}
                        </span>
                      </Link>
                    ) : (
                      label
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {companies.map((c) => (
                <tr
                  key={c.id}
                  data-testid="company-row"
                  className={
                    c.return_ipo != null && c.return_ipo > 100 ? 'ipo-gain-highlight' : undefined
                  }
                >
                  <th scope="row">
                    <Link href={'/ipo/' + c.slug}>{c.name} ↗</Link>
                    <small>
                      {c.board} · {date(c.listing_date)}
                    </small>
                  </th>
                  <td data-label="Issue size (₹ crore)">{number(c.issue_size)}</td>
                  <td data-label="IPO upper band">{money(c.price_high)}</td>
                  <td data-label="CMP">
                    <b>{money(c.cmp)}</b>
                    {c.cmp == null && <small>Awaiting an available official close</small>}
                    {c.price_date && (
                      <small>
                        {date(c.price_date)} · {c.closing_exchange}
                      </small>
                    )}
                  </td>
                  <td data-label="Gain since IPO">
                    <Gain value={c.return_ipo} />
                  </td>
                  <td data-label="Listing price (day close)">
                    {money(c.listing_price)}
                    {c.listing_price == null ? (
                      <small>Awaiting listing-day close</small>
                    ) : (
                      <small>
                        {date(c.listing_price_date || c.listing_date)} · {c.listing_price_exchange}
                      </small>
                    )}
                  </td>
                  <td data-label="Listing gain">
                    <Gain value={c.listing_gain} />
                  </td>
                  {columns.map((column) => (
                    <td key={column.label} data-label={column.label}>
                      {column.render(c)}
                    </td>
                  ))}
                  <td data-label="Data">
                    <Trust company={c} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
