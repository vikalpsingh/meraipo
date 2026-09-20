import type { Company } from '@/lib/types';
import { human, number, money, timestamp } from '@/lib/format';

export function LiveMarketData({ company: c }: { company: Company }) {
  if (!c.subscription && c.gmp == null) return null;
  return (
    <section className="panel" aria-labelledby="market-data-title">
      <h2 id="market-data-title">Market interest</h2>
      <div className="journey-grid">
        {c.subscription && (
          <div>
            <h3>Subscription</h3>
            <dl className="detail-list">
              {Object.entries(c.subscription.categories || {}).map(([category, value]) => (
                <div key={category}>
                  <dt>
                    {category === 'qib'
                      ? 'Institutional (QIB)'
                      : category === 'retail'
                        ? 'Retail applicants'
                        : human(category)}
                  </dt>
                  <dd>{value.multiple === null ? '—' : `${number(Number(value.multiple))}×`}</dd>
                </div>
              ))}
            </dl>
            <p className="small">
              Bids received relative to shares offered. Higher subscription does not guarantee
              returns.
            </p>
            <p className="muted">
              Updated {timestamp(c.subscription.observed_at)}
              {c.subscription.source_url && (
                <>
                  {' '}
                  ·{' '}
                  <a href={c.subscription.source_url} rel="noreferrer" target="_blank">
                    {c.subscription.source_provider || 'Source'} ↗
                  </a>
                </>
              )}
            </p>
          </div>
        )}
        {c.gmp != null && (
          <div>
            <h3>Unofficial GMP</h3>
            <p className="metric">{money(c.gmp)}</p>
            <p>Implied price: {money(c.gmp_estimated_price)}</p>
            <p className="small">
              An unofficial indication, not an exchange quote or a forecast. Listing prices may
              differ substantially.
            </p>
            <p className="muted">
              {timestamp(c.gmp_timestamp)} · {human(c.gmp_quality)}
            </p>
          </div>
        )}
      </div>
    </section>
  );
}

export function AnnualHistory({ company: c }: { company: Company }) {
  return (
    <details className="panel">
      <summary>Annual financial history · latest four years</summary>
      <p className="muted">
        Separate from the original pre-IPO baseline. Amounts in ₹ crore; EPS in ₹.
      </p>
      {!c.annuals?.length ? (
        <p>No annual filings have been imported yet.</p>
      ) : (
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Annual financial history"
        >
          <table className="data-table">
            <thead>
              <tr>
                <th>Year / basis</th>
                <th>
                  {['BANK', 'NBFC', 'INSURANCE'].includes(c.company_type || '')
                    ? 'Total income'
                    : 'Revenue'}
                </th>
                <th>PAT</th>
                <th>EPS</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {c.annuals.map((year) => (
                <tr key={year.financial_year}>
                  <th>
                    FY{year.financial_year}
                    <br />
                    <small>{human(year.statement_type || 'Standalone')}</small>
                  </th>
                  <td>
                    {number(
                      ['BANK', 'NBFC', 'INSURANCE'].includes(c.company_type || '')
                        ? year.total_income
                        : year.revenue,
                    )}
                  </td>
                  <td>{number(year.pat)}</td>
                  <td>{number(year.eps)}</td>
                  <td>
                    {year.source_url ? (
                      <a href={year.source_url} target="_blank" rel="noreferrer">
                        Filing ↗
                      </a>
                    ) : (
                      'Not recorded'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </details>
  );
}
