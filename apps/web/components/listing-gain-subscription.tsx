'use client';
import type { Company } from '@/lib/types';
import { EmailSubscription } from './email-subscription';

export function ListingGainSubscription({
  companies = [],
  asOf = 0,
}: {
  companies?: Company[];
  asOf?: number;
}) {
  const fresh = companies.filter(
    (c) =>
      !c.is_demo &&
      c.gmp != null &&
      c.gmp > 0 &&
      c.price_high &&
      c.price_high > 0 &&
      c.gmp_timestamp &&
      asOf - Date.parse(c.gmp_timestamp) >= 0 &&
      asOf - Date.parse(c.gmp_timestamp) <= 12 * 3600000,
  );
  const money = (n: number) =>
    new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 0,
    }).format(n);
  return (
    <section className="subscription-page" aria-label="IPO Alerts">
      <div className="signup-layout">
        <aside className="signup-story">
          <p className="signup-eyebrow">MERAIPO • YOUR MARKET WATCH</p>
          <h2>
            Follow the opportunity.
            <br />
            <em>Know the risk.</em>
          </h2>
          <p>Opening-day reminders. Your GMP threshold. Straight to your inbox.</p>
          <svg
            viewBox="0 0 360 140"
            role="img"
            aria-label="Decorative market chart, not a price forecast"
            className="signup-chart"
          >
            <defs>
              <linearGradient id="signup-fill" x1="0" y1="0" x2="0" y2="1">
                <stop stopColor="#77e0b5" stopOpacity=".5" />
                <stop offset="1" stopColor="#77e0b5" stopOpacity="0" />
              </linearGradient>
            </defs>
            <path
              d="M10 115 L55 90 L95 104 L145 58 L185 75 L225 33 L265 49 L310 18 L350 30 L350 140 L10 140Z"
              fill="url(#signup-fill)"
            />
            <path
              d="M10 115 L55 90 L95 104 L145 58 L185 75 L225 33 L265 49 L310 18 L350 30"
              fill="none"
              stroke="#92f4ca"
              strokeWidth="4"
              strokeLinejoin="round"
            />
          </svg>
          <h3>Current open IPOs · GMP potential</h3>
          <p className="signup-risk">
            Latest recorded GMP, not a live quote or realised listing gain.
          </p>
          {[
            ['Mainboard', 15000],
            ['SME', 250000],
          ].map(([board, budget]) => {
            const best = fresh
              .filter((c) =>
                board === 'SME'
                  ? c.board.toUpperCase() === 'SME'
                  : c.board.toUpperCase() === 'MAINBOARD',
              )
              .sort((a, b) => b.gmp! / b.price_high! - a.gmp! / a.price_high!)[0];
            const percent = best ? (best.gmp! / best.price_high!) * 100 : null;
            return (
              <div className="signup-example" key={board}>
                <span>
                  {board} · illustrative {money(Number(budget))}
                </span>
                {best && percent !== null ? (
                  <>
                    <strong>{best.name}</strong>
                    <p>
                      <b>{money((Number(budget) * percent) / 100)}</b> hypothetical gain ·{' '}
                      {percent.toFixed(1)}% GMP
                    </p>
                    <small>
                      Recorded{' '}
                      {new Date(best.gmp_timestamp!).toLocaleString('en-IN', {
                        timeZone: 'Asia/Kolkata',
                      })}{' '}
                      IST
                    </small>
                  </>
                ) : (
                  <p>No fresh positive GMP available for currently open IPOs.</p>
                )}
              </div>
            );
          })}
          <p className="signup-risk">
            Highest fresh positive GMP % among currently open IPOs, per board. Examples use a
            hypothetical budget × GMP %, not an actual lot or minimum application. Allotment is not
            assured; fees excluded. GMP can fall and losses are possible.
          </p>
        </aside>
        <EmailSubscription />
      </div>
    </section>
  );
}
