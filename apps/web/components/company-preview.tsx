'use client';

import { useId, useRef, useState } from 'react';
import Link from 'next/link';
import type { Company } from '@/lib/types';
import { date, money, number, timestamp, human } from '@/lib/format';

export function CompanyPreview({
  company,
  heading: asHeading = false,
}: {
  company: Company;
  heading?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const controller = useRef<AbortController | null>(null);
  const heading = useId();
  const [detail, setDetail] = useState<Company | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const c = detail || company;
  async function open() {
    dialog.current?.showModal();
    if (detail) return;
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setLoading(true);
    setError('');
    try {
      const response = await fetch(
        `/api/v1/companies/${encodeURIComponent(company.slug)}/journey`,
        { signal: request.signal },
      );
      if (!response.ok) throw new Error('Company details are temporarily unavailable.');
      const data: Company = await response.json();
      if (!request.signal.aborted) setDetail(data);
    } catch {
      if (!request.signal.aborted)
        setError('Company details are temporarily unavailable. Please retry.');
    } finally {
      if (!request.signal.aborted) setLoading(false);
    }
  }
  function close() {
    controller.current?.abort();
    dialog.current?.close();
  }
  const trigger = (
    <button className="company-preview-trigger" onClick={open} aria-haspopup="dialog">
      {company.name}
    </button>
  );
  return (
    <>
      {asHeading ? <h3>{trigger}</h3> : trigger}
      <dialog
        ref={dialog}
        className="company-preview"
        aria-labelledby={heading}
        onCancel={() => controller.current?.abort()}
      >
        <div className="section-heading">
          <div>
            <p className="eyebrow">IPO SNAPSHOT</p>
            <h2 id={heading}>{c.name}</h2>
          </div>
          <button className="outline-button" onClick={close} aria-label="Close company details">
            Close ×
          </button>
        </div>
        <p>
          {c.board} · {human(c.status)} · {date(c.open_date)} – {date(c.close_date)}
        </p>
        <div className="preview-metrics">
          <div>
            <span>Price band</span>
            <strong>
              {money(c.price_low)}–{money(c.price_high)}
            </strong>
          </div>
          <div>
            <span>Lot size</span>
            <strong>{c.lot_size == null ? 'Not announced' : `${number(c.lot_size)} shares`}</strong>
          </div>
          <div>
            <span>GMP · unofficial</span>
            <strong>{c.gmp == null ? 'Not available' : money(c.gmp)}</strong>
            <small>
              {c.gmp == null
                ? 'NSE/BSE do not publish GMP'
                : `${timestamp(c.gmp_timestamp)} · ${human(c.gmp_quality)}`}
            </small>
          </div>
        </div>
        <h3>Who is subscribing?</h3>
        <p className="muted">
          100% means fully subscribed; 250% means 2.5×. This is demand, not an allotment
          probability.
        </p>
        <div
          className="table-scroll"
          role="region"
          aria-label="Subscription categories"
          tabIndex={0}
        >
          <table className="data-table">
            <thead>
              <tr>
                <th>Category</th>
                <th>Subscribed</th>
                <th>Times</th>
              </tr>
            </thead>
            <tbody>
              {['retail', 'qib', 'nii', 'employee', 'shareholder', 'total'].map((key) => {
                const value = c.subscription?.categories?.[key]?.multiple;
                const multiple = value == null ? null : Number(value);
                return (
                  <tr key={key}>
                    <th scope="row">
                      {key === 'qib'
                        ? 'Institutions (QIB)'
                        : key === 'nii'
                          ? 'Non-institutional (NII)'
                          : human(key)}
                    </th>
                    <td>{multiple == null ? 'Not reported' : `${number(multiple * 100)}%`}</td>
                    <td>{multiple == null ? '—' : `${number(multiple)}×`}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {c.subscription && (
          <p className="small">
            Updated {timestamp(c.subscription.observed_at)} ·{' '}
            {c.subscription.source_provider || 'Source'}
            {c.subscription.source_url && (
              <>
                {' '}
                ·{' '}
                <a href={c.subscription.source_url} target="_blank" rel="noreferrer">
                  View source ↗
                </a>
              </>
            )}
          </p>
        )}
        {loading && <p role="status">Loading daily history…</p>}
        {error && (
          <div role="alert">
            <p>{error}</p>
            <button className="outline-button" onClick={open}>
              Retry
            </button>
          </div>
        )}
        {!!c.subscription_history?.length && (
          <details>
            <summary>Daily subscription history</summary>
            <div
              className="table-scroll"
              tabIndex={0}
              role="region"
              aria-label="Daily subscription history"
            >
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Date / exchange</th>
                    <th>Category</th>
                    <th>Subscribed</th>
                    <th>Bids / offered shares</th>
                  </tr>
                </thead>
                <tbody>
                  {c.subscription_history.map((row) => (
                    <tr key={`${row.date}-${row.exchange}-${row.category}`}>
                      <td>
                        {date(row.date)} · {row.exchange}
                      </td>
                      <td>{human(row.category)}</td>
                      <td>
                        {row.subscription_pct == null ? '—' : `${number(row.subscription_pct)}%`}
                      </td>
                      <td>
                        {number(row.bid_shares)} / {number(row.offered_shares)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
        <p className="small">
          Unofficial GMP does not guarantee listing gains. Missing values are not zero.
        </p>
        <Link className="primary-button" href={`/ipo/${c.slug}`}>
          View company journey →
        </Link>
      </dialog>
    </>
  );
}
