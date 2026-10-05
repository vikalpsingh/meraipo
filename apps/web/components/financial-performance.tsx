'use client';
import { useState } from 'react';
import { money, date, human } from '@/lib/format';
export type FinancialPerformanceData = {
  status: string;
  items: {
    period_start: string;
    period_end: string;
    period_type: string;
    basis: string;
    revision: number;
    facts: Record<string, string | null>;
    exchange: string;
    filing_date: string;
    updated_at: string;
    source_url: string;
  }[];
};
export function FinancialPerformance({ data }: { data: FinancialPerformanceData }) {
  const [basis, setBasis] = useState(
    data.items.some((r) => r.basis === 'CONSOLIDATED') ? 'CONSOLIDATED' : 'STANDALONE',
  );
  const [period, setPeriod] = useState('QUARTERLY');
  const rows = data.items.filter((r) => r.basis === basis && r.period_type === period);
  const amount = (value: string | null | undefined, eps = false) =>
    value == null ? '—' : money(Number(value) / (eps ? 1 : 10000000));
  return (
    <section className="panel" aria-label="Financial Performance">
      <h2>Financial Performance</h2>
      <div className="filters">
        <label>
          Reporting period
          <select value={period} onChange={(e) => setPeriod(e.target.value)}>
            {['QUARTERLY', 'HALF_YEARLY', 'ANNUAL', 'NINE_MONTH'].map((p) => (
              <option key={p} value={p}>
                {human(p)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Accounting basis
          <select value={basis} onChange={(e) => setBasis(e.target.value)}>
            <option value="CONSOLIDATED">Consolidated</option>
            <option value="STANDALONE">Standalone</option>
          </select>
        </label>
      </div>
      <p>
        Amounts in ₹ crore; EPS in ₹ per share. PAT is total profit for the period, including
        non-controlling interests. {human(basis)} statements.
      </p>
      {rows.length ? (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                {[
                  'Period',
                  'Revenue',
                  'Total income',
                  'PBT',
                  'PAT',
                  'Basic EPS',
                  'Diluted EPS',
                  'Revenue YoY',
                  'Source',
                ].map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const prior = rows.find(
                  (p) =>
                    p.period_end.slice(5) === r.period_end.slice(5) &&
                    Number(p.period_end.slice(0, 4)) === Number(r.period_end.slice(0, 4)) - 1 &&
                    p.period_start.slice(5) === r.period_start.slice(5),
                );
                const growth =
                  !prior || prior.facts.revenue == null || r.facts.revenue == null
                    ? '—'
                    : Number(prior.facts.revenue) <= 0
                      ? 'Prior revenue is zero or negative; % not comparable'
                      : ((Number(r.facts.revenue) / Number(prior.facts.revenue) - 1) * 100).toFixed(
                          1,
                        ) + '%';
                return (
                  <tr key={r.period_start + r.period_end}>
                    <th>
                      {date(r.period_start)} – {date(r.period_end)}
                    </th>
                    <td>{amount(r.facts.revenue)}</td>
                    <td>{amount(r.facts.total_income)}</td>
                    <td>{amount(r.facts.pbt)}</td>
                    <td>{amount(r.facts.pat)}</td>
                    <td>{amount(r.facts.basic_eps, true)}</td>
                    <td>{amount(r.facts.diluted_eps, true)}</td>
                    <td>{growth}</td>
                    <td>
                      <a href={r.source_url} target="_blank" rel="noreferrer">
                        {r.exchange} filing ↗
                      </a>
                      <small>
                        Filed {date(r.filing_date)} · Updated {date(r.updated_at)}
                        {r.revision > 1 ? ` · Revision ${r.revision}` : ''}
                      </small>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p>
          {data.status === 'AWAITING_PROCESSING'
            ? 'Awaiting processing'
            : data.status === 'SOURCE_TEMPORARILY_UNAVAILABLE'
              ? 'Source temporarily unavailable'
              : 'Not yet reported'}{' '}
          for this period and basis.
        </p>
      )}
    </section>
  );
}
