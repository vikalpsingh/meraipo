'use client';

import { useState } from 'react';
import type { FormEvent } from 'react';

type Config = { company_id: string; page_url: string; document_prefix: string; enabled: boolean };
export function OfficialResultsSource({
  csrf,
  companies,
  sources,
}: {
  csrf: string;
  companies: { id: string; name: string }[];
  sources: Config[];
}) {
  const [company, setCompany] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const saved = sources.find((s) => s.company_id === company);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    setBusy(true);
    try {
      const response = await fetch('/api/v1/admin/results/official-sources/' + company, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify({
          page_url: values.get('page_url'),
          document_prefix: values.get('document_prefix'),
          enabled: values.has('enabled'),
          official_source_confirmed: values.has('confirmed'),
        }),
      });
      const data = await response.json();
      if (!response.ok)
        throw new Error(data.detail || data.error?.message || 'Unable to save source');
      setMessage(
        'Official source saved. The BSE results job will discover linked originals; unvalidated files remain in review.',
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to save source');
    } finally {
      setBusy(false);
    }
  }
  return (
    <details>
      <summary>Approved company investor-relations fallback (BSE-only)</summary>
      <p>
        Confirm the page belongs to the selected company. Documents must be on the same host and
        within the approved directory. PDFs and files without a verified publication date require
        review.
      </p>
      <label>
        Company
        <select value={company} onChange={(e) => setCompany(e.target.value)}>
          <option value="">Select BSE-only company</option>
          {companies.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
      {company && (
        <form key={company} onSubmit={submit} className="form-grid">
          <label>
            Official financial-results page
            <input name="page_url" type="url" required defaultValue={saved?.page_url || ''} />
          </label>
          <label>
            Approved document directory (ending /)
            <input
              name="document_prefix"
              type="url"
              required
              defaultValue={saved?.document_prefix || ''}
            />
          </label>
          <label>
            <input name="confirmed" type="checkbox" required />I verified this official source
            belongs to this company
          </label>
          <label>
            <input name="enabled" type="checkbox" defaultChecked={saved?.enabled ?? true} />
            Enable fallback
          </label>
          <button disabled={busy}>{busy ? 'Saving…' : 'Save approved source'}</button>
        </form>
      )}
      {message && <p role="status">{message}</p>}
    </details>
  );
}
