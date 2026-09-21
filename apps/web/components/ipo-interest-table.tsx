import type { Company } from '@/lib/types';
import { CompanyPreview } from './company-preview';
import { date, money, number, timestamp } from '@/lib/format';

export function IPOInterestTable({ companies }: { companies: Company[] }) {
  return (
    <div
      className="ipo-interest-table table-scroll"
      role="region"
      aria-label="IPO subscription overview"
      tabIndex={0}
    >
      <table className="data-table">
        <thead>
          <tr>
            <th>Company / bidding dates</th>
            <th>Security type</th>
            <th>Price band</th>
            <th>Retail %</th>
            <th>QIB %</th>
            <th>NII %</th>
            <th>Total %</th>
            <th>GMP · unofficial</th>
          </tr>
        </thead>
        <tbody>
          {companies.map((c) => (
            <tr key={c.id}>
              <td>
                <CompanyPreview company={c} />
                <small className="table-subline">
                  {c.board} · {date(c.open_date)} – {date(c.close_date)}
                </small>
              </td>
              <td>{c.board === 'SME' ? 'SME' : 'EQ'}</td>
              <td>
                {c.price_low == null || c.price_high == null
                  ? 'Not announced'
                  : `${money(c.price_low)}–${money(c.price_high)}`}
              </td>
              {['retail', 'qib', 'nii', 'total'].map((category) => {
                const value = c.subscription?.categories?.[category]?.multiple;
                return (
                  <td key={category}>
                    {value == null ? (
                      <span title="Not reported by source">—</span>
                    ) : (
                      `${number(Number(value) * 100)}%`
                    )}
                  </td>
                );
              })}
              <td>
                {c.gmp == null ? 'GMP unavailable' : money(c.gmp)}
                <small className="table-subline">
                  {c.gmp == null
                    ? 'No unofficial quote'
                    : `${c.gmp_quality === 'STALE' ? 'Stale · ' : ''}${timestamp(c.gmp_timestamp)}`}
                </small>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="small">
        Subscription is bids ÷ shares offered. 100% = 1×. Select a company for category details and
        daily history. — means not reported.
      </p>
    </div>
  );
}
