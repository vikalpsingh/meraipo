'use client';
import { useState } from 'react';
import type { Company } from '@/lib/types';
import { indiaDay } from '@/lib/applicant';

type Props = {
  companies: Company[];
  busy: boolean;
  save: (path: string, body: unknown, method: string) => Promise<void>;
};
export function GuideEditor({ companies, busy, save }: Props) {
  const [slug, setSlug] = useState('');
  const company = companies.find((c) => c.slug === slug);
  const guide = company?.applicant_guide;
  const inputFields = [
    ['category', 'Applicant category', 'text'],
    ['min_lots', 'Minimum lots', 'number'],
    ['max_lots', 'Maximum lots (optional)', 'number'],
    ['max_amount', 'Category amount limit (₹, optional)', 'number'],
    ['bid_deadline', 'Bidding deadline (IST)', 'datetime-local'],
    ['mandate_deadline', 'UPI mandate deadline (IST)', 'datetime-local'],
    ['allotment_date', 'Expected allotment date', 'date'],
    ['unblock_date', 'Unblocking initiation date', 'date'],
    ['registrar_name', 'Official registrar name', 'text'],
    ['registrar_url', 'Official registrar allotment URL', 'url'],
    ['source_url', 'Guide source URL', 'url'],
    ['reviewed_on', 'Reviewed on', 'date'],
  ];
  return (
    <section className="panel">
      <h2>Applicant guide & company brief</h2>
      <p>
        Review the issue prospectus and current exchange notice. Enter rules for one named category;
        do not reuse Mainboard rules for SME issues. Leave unknown dates blank. Mark verified only
        after checking the source and official registrar destination.
      </p>
      <label>
        Choose IPO
        <select aria-label="Choose IPO" value={slug} onChange={(e) => setSlug(e.target.value)}>
          <option value="">Choose a company</option>
          {companies.map((c) => (
            <option key={c.id} value={c.slug}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
      {company && (
        <form
          className="form-grid"
          key={slug}
          onSubmit={(e) => {
            e.preventDefault();
            const body: Record<string, unknown> = {};
            for (const [key, value] of new FormData(e.currentTarget).entries()) {
              const text = String(value);
              body[key] = !text
                ? null
                : ['min_lots', 'max_lots', 'max_amount'].includes(key)
                  ? Number(text)
                  : ['bid_deadline', 'mandate_deadline'].includes(key)
                    ? new Date(text + ':00+05:30').toISOString()
                    : text;
            }
            void save('/admin/ipos/' + slug + '/applicant-guide', body, 'PUT');
          }}
        >
          {inputFields.map(([key, label, type]) => {
            const value = guide?.[key as keyof typeof guide];
            const display =
              type === 'datetime-local' && value
                ? new Date(new Date(String(value)).getTime() + 330 * 60000)
                    .toISOString()
                    .slice(0, 16)
                : value;
            return (
              <label key={key}>
                {label}
                <input
                  name={key}
                  type={type}
                  min={type === 'number' ? 1 : undefined}
                  step={key === 'max_amount' ? '0.0001' : undefined}
                  required={['category', 'source_url', 'reviewed_on'].includes(key)}
                  defaultValue={
                    display == null ? (key === 'reviewed_on' ? indiaDay() : '') : String(display)
                  }
                />
              </label>
            );
          })}
          <label>
            Schedule status
            <select
              aria-label="Schedule status"
              name="schedule_status"
              defaultValue={guide?.schedule_status || 'TENTATIVE'}
            >
              <option value="TENTATIVE">Tentative</option>
              <option value="CONFIRMED">Published schedule</option>
            </select>
          </label>
          <label>
            Guide verification
            <select
              aria-label="Guide verification"
              name="verification_status"
              defaultValue={guide?.verification_status || 'UNVERIFIED'}
            >
              <option value="UNVERIFIED">Unverified / draft</option>
              <option value="VERIFIED">Checked against original source</option>
              <option value="PARTIAL">Partial</option>
            </select>
          </label>
          {[
            ['business_summary', 'What the company does (plain language)', 800],
            ['strengths', 'Three strengths (one per line)', 1200],
            ['risks', 'Three risks (one per line)', 1200],
            ['proceeds', 'How the IPO proceeds will be used', 800],
          ].map(([key, label, length]) => (
            <label className="full" key={key}>
              {label}
              <textarea
                name={String(key)}
                maxLength={Number(length)}
                defaultValue={String(guide?.[key as keyof typeof guide] || '')}
              />
            </label>
          ))}
          <button className="primary-button" disabled={busy}>
            Save applicant guide
          </button>
        </form>
      )}
    </section>
  );
}
