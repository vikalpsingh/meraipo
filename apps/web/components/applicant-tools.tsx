'use client';
import { useState } from 'react';
import { applicationEstimate, type CalculatorCompany } from '@/lib/applicant';
import { money } from '@/lib/format';

export function ApplicationCalculator({ company: c }: { company: CalculatorCompany }) {
  const [lots, setLots] = useState(String(c.applicant_guide?.min_lots || 1));
  const result = applicationEstimate(c, lots);
  const g = c.applicant_guide;
  const minimum = g?.min_lots || 1;
  const ready = !applicationEstimate(c, String(minimum)).error;
  const current = Number(lots);
  const decrease = /^\d+$/.test(lots) && current > minimum;
  const increase = /^\d+$/.test(lots) && !applicationEstimate(c, String(current + 1)).error;
  return (
    <section className="panel calculator" aria-labelledby="calculator-title">
      <p className="eyebrow">02 · PREPARE YOUR APPLICATION</p>
      <h2 id="calculator-title">How much will be blocked?</h2>
      <p>
        {g?.category || 'Category rules pending'} · {c.board}
      </p>
      {c.status !== 'OPEN' && (
        <p className="guide-note">
          {c.status === 'UPCOMING'
            ? 'Applications have not opened yet.'
            : 'Applications are closed. This is a reference calculation.'}
        </p>
      )}
      {ready && (
        <>
          <label htmlFor="application-lots">Number of lots</label>
          <p id="lot-help" className="screen-note">
            One lot = {c.lot_size} shares. Start with the minimum or adjust below.
          </p>
          <div className="lot-stepper">
            <button
              type="button"
              aria-label="Decrease lots"
              disabled={!decrease}
              onClick={() => setLots(String(current - 1))}
            >
              −
            </button>
            <input
              id="application-lots"
              inputMode="numeric"
              pattern="[0-9]*"
              value={lots}
              onChange={(e) => setLots(e.target.value)}
              aria-describedby="lot-help calculator-result"
              aria-invalid={!!result.error}
            />
            <button
              type="button"
              aria-label="Increase lots"
              disabled={!increase}
              onClick={() => setLots(String(current + 1))}
            >
              +
            </button>
          </div>
        </>
      )}
      <div id="calculator-result" aria-live="polite" className="calculator-result">
        {result.error ? (
          <>
            <p>{result.error}</p>
            {ready && (
              <button type="button" className="text-link" onClick={() => setLots(String(minimum))}>
                Reset to minimum ({minimum} {minimum === 1 ? 'lot' : 'lots'})
              </button>
            )}
          </>
        ) : (
          <>
            <strong>{money(result.amount)}</strong>
            <span>
              {result.lots} {result.lots === 1 ? 'lot' : 'lots'} × {c.lot_size} shares ={' '}
              {result.shares} shares
            </span>
          </>
        )}
      </div>
      {ready && (
        <p className="screen-note">
          Estimate at the upper price band of {money(c.price_high)} per share. Money is blocked
          under ASBA; the amount for allotted shares is debited. This does not place an application
          or predict allotment.
        </p>
      )}
      {g && ready && (
        <p className="screen-note">
          Minimum {g.min_lots} {g.min_lots === 1 ? 'lot' : 'lots'}
          {g.max_lots ? ` · Maximum ${g.max_lots} lots` : ''}
          {g.max_amount ? ` · Category limit ${money(g.max_amount)}` : ''}. Check the current
          prospectus and your broker before applying.
        </p>
      )}
    </section>
  );
}

const checks = [
  'I have read what the company does and its key risks.',
  'I have checked the issue category, amount and my broker’s deadline.',
  'I have checked my PAN, demat and payment details in my application.',
  'My broker or bank shows that my application was submitted.',
  'I have accepted the UPI mandate, if using UPI, and confirmed the amount is blocked.',
];
export function ApplicationChecklist() {
  const [checked, setChecked] = useState<string[]>([]);
  return (
    <details className="panel application-checklist">
      <summary>
        Before you finish applying{' '}
        <span>
          {checked.length}/{checks.length}
        </span>
      </summary>
      <p>Your personal checklist for this visit. MeraIPO cannot verify or submit an application.</p>
      <fieldset>
        <legend>Application checklist</legend>
        {checks.map((text) => (
          <label key={text}>
            <input
              type="checkbox"
              checked={checked.includes(text)}
              onChange={(e) =>
                setChecked(
                  e.target.checked ? [...checked, text] : checked.filter((t) => t !== text),
                )
              }
            />{' '}
            <span>{text}</span>
          </label>
        ))}
      </fieldset>
      <p className="screen-note">
        All checked? This still does not guarantee allotment. If a UPI mandate is missing, contact
        the broker or intermediary you used. ASBA through a bank may not use UPI.
      </p>
      <a href="https://www.nseindia.com/static/trade/e-ipo-faqs" target="_blank" rel="noreferrer">
        Application help from NSE ↗
      </a>
    </details>
  );
}
