import type { Company } from '@/lib/types';
import { CompanyPreview } from './company-preview';
import { date, money, number, timestamp } from '@/lib/format';

import { indiaDay } from '@/lib/applicant';
import { ipoStatus } from '@/lib/ipo-status';

function gmpPresentation(c: Company) {
  const value =
    c.gmp == null || c.price_high == null || c.price_high <= 0
      ? null
      : (c.gmp / c.price_high) * 100;
  const tone =
    value != null && value > 100
      ? 'gold'
      : value != null && value > 40
        ? 'dark-green'
        : value != null && value > 20
          ? 'light-green'
          : 'neutral';
  return { value, tone };
}

function GMPPercentage({ company: c }: { company: Company }) {
  const { value, tone } = gmpPresentation(c);
  return (
    <td
      className={`gmp-percent gmp-percent--${tone}`}
      title="Indicative GMP premium; actual listing gains may differ."
    >
      {value == null ? '-NA-' : `${number(value)}%`}
    </td>
  );
}

export function IPOInterestTable({
  companies,
  today = indiaDay(),
}: {
  companies: Company[];
  today?: string;
}) {
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
            <th>Retail ×</th>
            <th>QIB ×</th>
            <th>NII ×</th>
            <th>Total ×</th>
            <th>GMP · unofficial</th>
            <th title="GMP ÷ upper price band × 100">GMP %</th>
          </tr>
        </thead>
        <tbody>
          {companies.map((c) => (
            <tr
              key={c.id}
              className={`ipo-row ipo-tone-${ipoStatus(c, today).tone} ipo-gmp--${gmpPresentation(c).tone}`}
            >
              <td>
                <div className="ipo-company-line">
                  <CompanyPreview company={c} />
                  <span className={`ipo-status ipo-tone-${ipoStatus(c, today).tone}`}>
                    {ipoStatus(c, today).label}
                  </span>
                </div>
                <small className="table-subline">
                  {c.board} · {date(c.open_date)} – {date(c.close_date)}
                </small>
              </td>
              <td>
                <span
                  className={`security-type security-type--${c.board === 'SME' ? 'sme' : c.board === 'Mainboard' ? 'eq' : 'unknown'}`}
                >
                  {c.board === 'SME' ? 'SME' : c.board === 'Mainboard' ? 'EQ' : 'Not announced'}
                </span>
              </td>
              <td>
                {c.price_low == null || c.price_high == null
                  ? 'Not announced'
                  : `${money(c.price_low)}–${money(c.price_high)}`}
              </td>
              {['retail', 'qib', 'nii', 'total'].map((category) => {
                const value = c.subscription?.categories?.[category]?.multiple;
                const gap = c.subscription?.categories?.[category]?.gap_note;
                return (
                  <td key={category}>
                    {value == null ? (
                      <span title={gap || 'Not reported by source'}>—{gap && '**'}</span>
                    ) : (
                      `${number(Number(value))}×`
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
              <GMPPercentage company={c} />
            </tr>
          ))}
        </tbody>
      </table>
      <p className="small">
        Subscription is bids ÷ shares offered, shown in times (×). 1× means fully subscribed. Select
        a company for category details and daily history. — means not reported.
      </p>
      {companies.some((c) =>
        Object.values(c.subscription?.categories || {}).some((category) => category.gap_note),
      ) && (
        <p className="small">
          ** Verified category allocations are missing or reported as zero. Multiples remain blank;
          total IPO shares are not substituted. Select the company for source-gap details.
        </p>
      )}
    </div>
  );
}
