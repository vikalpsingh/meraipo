'use client';
import { useEffect, useRef } from 'react';
import type { Company } from '@/lib/types';
import { EmailSubscription } from './email-subscription';

const COOKIE = 'meraipo-alert-prompt';
function remember() {
  document.cookie = `${COOKIE}=seen; Max-Age=31536000; Path=/; SameSite=Lax${location.protocol === 'https:' ? '; Secure' : ''}`;
}
export function ListingGainSubscription({
  companies = [],
  asOf = 0,
}: {
  companies?: Company[];
  asOf?: number;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (!document.cookie.split(';').some((part) => part.trim().startsWith(`${COOKIE}=`))) {
      dialog.current?.showModal();
      remember();
    }
  }, []);
  function dismiss() {
    remember();
    dialog.current?.close();
  }
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
    <>
      <dialog
        ref={dialog}
        className="subscription-dialog"
        aria-label="Listing gain email subscription"
        onClose={() => {
          remember();
        }}
      >
        <button type="button" className="subscription-close" onClick={dismiss}>
          Do it later · Close ✕
        </button>
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
            <h3>A snapshot of GMP potential</h3>
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
                    <p>No fresh positive GMP example available.</p>
                  )}
                </div>
              );
            })}
            <p className="signup-risk">
              Highest fresh positive GMP % among the homepage IPOs, per board. Examples use a
              hypothetical budget × GMP %, not an actual lot or minimum application. Allotment is
              not assured; fees excluded. GMP can fall and losses are possible.
            </p>
          </aside>
          <EmailSubscription onSubscribed={remember} />
        </div>
      </dialog>
    </>
  );
}
