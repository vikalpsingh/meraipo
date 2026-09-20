'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { Company, SiteMessage, Advertisement } from '@/lib/types';
import { human, timestamp } from '@/lib/format';
import { GuideEditor } from '@/components/guide-editor';
import { MarketConsole } from '@/components/market-console';
type Session = { email: string; csrf_token: string };
type Dashboard = {
  companies: Company[];
  imports: { id: string; provider: string; status: string; error: string | null }[];
  provider_mode: string;
  active: number;
  upcoming: number;
  tracked: number;
  missing_results: number;
  missing_symbols: number;
  missing_ipo_data: number;
  stale_gmp: number;
  stale_prices: number;
  conflicts: number;
  failed_jobs: number;
};
type Field = [string, string, string?, boolean?];
type Values = Record<string, string | number | boolean | null | undefined>;
const metrics: Field[] = [
  ['revenue', 'Revenue (₹ Cr)', 'number'],
  ['ebitda', 'EBITDA (₹ Cr)', 'number'],
  ['pat', 'PAT (₹ Cr)', 'number'],
  ['eps', 'EPS (₹)', 'number'],
  ['debt', 'Debt (₹ Cr)', 'number'],
  ['cfo', 'Operating cash flow (₹ Cr)', 'number'],
  ['roe', 'ROE (%)', 'number'],
  ['roce', 'ROCE (%)', 'number'],
];
function Fields({ fields, values = {} }: { fields: Field[]; values?: Values }) {
  return (
    <>
      {fields.map(([name, label, type = 'text', required = false]) => (
        <label key={name}>
          {label}
          <input
            name={name}
            type={type}
            step={type === 'number' ? 'any' : undefined}
            required={required}
            defaultValue={
              values[name] === null || values[name] === undefined ? '' : String(values[name])
            }
          />
        </label>
      ))}
    </>
  );
}
function Source() {
  return (
    <>
      <label className="full">
        Source URL
        <input name="source_url" type="url" placeholder="https://…" required />
      </label>
      <label>
        Verification
        <select name="verification_status">
          <option value="UNVERIFIED">Unverified</option>
          <option value="VERIFIED">Verified against original source</option>
          <option value="PARTIAL">Partial data</option>
        </select>
      </label>
      <label>
        Provider
        <input name="provider" defaultValue="manual" required />
      </label>
    </>
  );
}
function parse(form: HTMLFormElement, numeric: string[] = []) {
  const values: Record<string, unknown> = {};
  for (const [key, value] of new FormData(form).entries()) {
    values[key] = numeric.includes(key)
      ? value === ''
        ? null
        : Number(value)
      : value === ''
        ? null
        : String(value);
  }
  return values;
}
async function request<T>(
  path: string,
  session: Session | null,
  body?: unknown,
  method = 'POST',
): Promise<T> {
  const response = await fetch('/api/v1' + path, {
    method: body === undefined ? 'GET' : method,
    headers: {
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...(session ? { 'X-CSRF-Token': session.csrf_token } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      data.error?.fields
        ?.map((f: { field: string; message: string }) => `${f.field}: ${f.message}`)
        .join('; ') ||
        data.error?.message ||
        'Request failed',
    );
  return data as T;
}
export default function Console() {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [messages, setMessages] = useState<SiteMessage[]>([]);
  const [ads, setAds] = useState<Advertisement[]>([]);
  const [audit, setAudit] = useState<{ id: string; action: string; created_at: string }[]>([]);
  const [tab, setTab] = useState('Dashboard');
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const [edit, setEdit] = useState<SiteMessage | null>(null);
  const [editAd, setEditAd] = useState<Advertisement | null>(null);
  const [editCompany, setEditCompany] = useState<Company | null>(null);
  const [formKey, setFormKey] = useState(0);
  const importKey = useRef<string | null>(null);
  const load = useCallback(async (auth: Session) => {
    const [d, m, a, h] = await Promise.all([
      request<Dashboard>('/admin/dashboard', auth),
      request<{ items: SiteMessage[] }>('/admin/messages', auth),
      request<{ items: Advertisement[] }>('/admin/advertisements', auth),
      request<{ items: typeof audit }>('/admin/audit', auth),
    ]);
    setDashboard(d);
    setMessages(m.items);
    setAds(a.items);
    setAudit(h.items);
  }, []);
  useEffect(() => {
    let active = true;
    request<Session>('/admin/session', null)
      .then(async (auth) => {
        if (active) {
          setSession(auth);
          await load(auth);
        }
      })
      .catch(() => {})
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [load]);
  async function login(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setStatus('');
    try {
      const auth = await request<Session>('/admin/login', null, parse(event.currentTarget));
      setSession(auth);
      await load(auth);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : 'Sign-in failed');
    } finally {
      setBusy(false);
    }
  }
  async function save(path: string, body: unknown, method = 'POST') {
    setBusy(true);
    setStatus('');
    try {
      await request(path, session, body, method);
      await load(session!);
      setStatus('Saved successfully.');
      setFormKey((k) => k + 1);
      importKey.current = null;
      setEdit(null);
      setEditAd(null);
      setEditCompany(null);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : 'Could not save. Your entries are preserved.');
    } finally {
      setBusy(false);
    }
  }
  const companies = dashboard?.companies || [];
  const picker = (
    <label>
      Company
      <select name="slug" required>
        <option value="">Choose a company</option>
        {companies.map((c) => (
          <option value={c.slug} key={c.id}>
            {c.name}
          </option>
        ))}
      </select>
    </label>
  );
  if (loading) return <p role="status">Checking your session…</p>;
  if (!session)
    return (
      <section className="panel admin-login">
        <h2>Administrator sign-in</h2>
        <p>Only provisioned administrators can maintain this site.</p>
        <form className="form-grid" onSubmit={login}>
          <label className="full">
            Email
            <input name="email" type="email" autoComplete="username" required />
          </label>
          <label className="full">
            Password
            <input name="password" type="password" autoComplete="current-password" required />
          </label>
          <button className="primary-button full" disabled={busy}>
            Sign in
          </button>
        </form>
        <p role="alert">{status}</p>
      </section>
    );
  return (
    <>
      <div className="section-heading">
        <span>Signed in as {session.email}</span>
        <button
          className="outline-button"
          onClick={async () => {
            try {
              await request('/admin/logout', session, {});
              setSession(null);
              setDashboard(null);
              setStatus('');
            } catch {
              setStatus('Logout failed. Please retry.');
            }
          }}
        >
          Log out
        </button>
      </div>
      <nav className="screen-tabs admin-tabs" aria-label="Admin sections">
        {[
          'Dashboard',
          'Data & scheduler',
          'IPOs',
          'Applicant guides',
          'GMP',
          'Quarterly results',
          'Messages & quotes',
          'Advertisements',
          'Audit',
        ].map((t) => (
          <button
            key={t}
            aria-current={t === tab ? 'page' : undefined}
            onClick={() => {
              setTab(t);
              setStatus('');
            }}
          >
            {t}
          </button>
        ))}
      </nav>
      <p className="admin-status" role="status" aria-live="polite">
        {status}
      </p>
      {tab === 'Applicant guides' && <GuideEditor companies={companies} busy={busy} save={save} />}
      {tab === 'Data & scheduler' && session && (
        <MarketConsole csrf={session.csrf_token} companies={dashboard?.companies || []} />
      )}
      {tab === 'Dashboard' && dashboard && (
        <>
          <div className="admin-counters">
            {(
              [
                'active',
                'upcoming',
                'tracked',
                'missing_results',
                'missing_symbols',
                'missing_ipo_data',
                'stale_gmp',
                'stale_prices',
                'conflicts',
                'failed_jobs',
              ] as const
            ).map((k) => (
              <div key={k}>
                <strong>{dashboard[k]}</strong>
                <span>{human(k)}</span>
              </div>
            ))}
          </div>
          <section className="panel">
            <h2>Data pipeline</h2>
            <p>
              Provider mode: {dashboard.provider_mode}. Automated live providers require configured
              access.
            </p>
            {dashboard.imports.length ? (
              dashboard.imports.map((r) => (
                <p key={r.id}>
                  {r.provider} · {r.status} {r.error && '· ' + r.error}
                </p>
              ))
            ) : (
              <p>No import runs yet.</p>
            )}
          </section>
        </>
      )}
      {tab === 'Messages & quotes' && (
        <section className="panel">
          <h2>{edit ? 'Edit message' : 'A thought for your readers'}</h2>
          <p>
            Write an original investing thought or credit a verified quotation. Plain text only. No
            promised returns.
          </p>
          <form
            className="form-grid"
            key={'message' + formKey + (edit?.id || '')}
            onSubmit={(e) => {
              e.preventDefault();
              const body = parse(e.currentTarget);
              body.enabled = new FormData(e.currentTarget).has('enabled');
              for (const k of ['active_from', 'active_to'])
                body[k] = body[k] ? new Date(String(body[k])).toISOString() : null;
              void save(
                '/admin/messages' + (edit ? '/' + edit.id : ''),
                body,
                edit ? 'PUT' : 'POST',
              );
            }}
          >
            <Fields
              fields={[
                ['title', 'Title', 'text', true],
                ['attribution', 'Attribution'],
              ]}
              values={edit ? { ...edit } : {}}
            />
            <label>
              Type
              <select name="kind" defaultValue={edit?.kind || 'quote'}>
                <option value="quote">Investing quote / thought</option>
                <option value="message">Site announcement</option>
              </select>
            </label>
            <label className="inline-check">
              <input type="checkbox" name="enabled" defaultChecked={edit?.enabled ?? true} />
              Enabled
            </label>
            <label className="full">
              Content
              <textarea
                name="content"
                maxLength={2000}
                defaultValue={edit?.content || ''}
                required
              />
            </label>
            <Fields
              fields={[
                ['active_from', 'Active from (your local time)', 'datetime-local'],
                ['active_to', 'Active until (your local time)', 'datetime-local'],
              ]}
              values={Object.fromEntries(
                ['active_from', 'active_to'].map((k) => {
                  const value = edit?.[k as 'active_from' | 'active_to'];
                  return [
                    k,
                    value
                      ? new Date(
                          new Date(value).getTime() - new Date(value).getTimezoneOffset() * 60000,
                        )
                          .toISOString()
                          .slice(0, 16)
                      : '',
                  ];
                }),
              )}
            />
            <button className="primary-button" disabled={busy}>
              Save message
            </button>
            {edit && (
              <button type="button" className="outline-button" onClick={() => setEdit(null)}>
                Cancel edit
              </button>
            )}
          </form>
          <div className="admin-records">
            {messages.map((m) => (
              <article key={m.id}>
                <div>
                  <b>{m.title}</b>
                  <p>{m.content}</p>
                  <small>
                    {m.enabled ? 'Enabled' : 'Disabled'} ·{' '}
                    {m.active_from ? timestamp(m.active_from) : 'No start limit'} ·{' '}
                    {m.active_to ? timestamp(m.active_to) : 'No end limit'}
                  </small>
                </div>
                <button onClick={() => setEdit(m)}>Edit {m.title}</button>
              </article>
            ))}
          </div>
        </section>
      )}
      {tab === 'GMP' && (
        <section className="panel">
          <h2>Record a GMP update</h2>
          <p>Each save adds to history. Leave the value empty when unavailable.</p>
          <form
            className="form-grid"
            key={'gmp' + formKey}
            onSubmit={(e) => {
              e.preventDefault();
              const body = parse(e.currentTarget, ['value']);
              const slug = body.slug;
              delete body.slug;
              body.observed_at = new Date(String(body.observed_at)).toISOString();
              body.import_key = importKey.current ??= crypto.randomUUID();
              void save('/admin/ipos/' + slug + '/gmp', body);
            }}
          >
            {picker}
            <Fields
              fields={[
                ['value', 'GMP (₹)', 'number'],
                ['observed_at', 'Observed at (your local time)', 'datetime-local', true],
              ]}
            />
            <Source />
            <button className="primary-button" disabled={busy}>
              Save GMP
            </button>
          </form>
        </section>
      )}
      {tab === 'Quarterly results' && (
        <section className="panel">
          <h2>Add or correct quarterly results</h2>
          <p>
            A correction creates a new revision. The original IPO baseline and previous revisions
            are retained.
          </p>
          <form
            className="form-grid"
            key={'quarter' + formKey}
            onSubmit={(e) => {
              e.preventDefault();
              const body = parse(e.currentTarget, [
                ...metrics.map((m) => m[0]),
                'financial_year',
                'quarter',
              ]);
              const slug = body.slug;
              delete body.slug;
              body.import_key = importKey.current ??= crypto.randomUUID();
              void save('/admin/companies/' + slug + '/quarters', body);
            }}
          >
            {picker}
            <Fields
              fields={[
                ['financial_year', 'Financial year ending', 'number', true],
                ['quarter', 'Quarter (1–4)', 'number', true],
                ...metrics,
              ]}
            />
            <Source />
            <button className="primary-button" disabled={busy}>
              Save result revision
            </button>
          </form>
          <details className="panel">
            <summary>Import several quarters</summary>
            <p>
              Paste a JSON array of up to 100 quarterly records. Every record needs a unique
              import_key, financial_year, quarter and source_url. The entire batch is validated
              before saving.
            </p>
            <form
              className="form-grid"
              key={'import' + formKey}
              onSubmit={(event) => {
                event.preventDefault();
                const values = new FormData(event.currentTarget);
                try {
                  const records = JSON.parse(String(values.get('records')));
                  if (!Array.isArray(records) || records.length < 1 || records.length > 100)
                    throw new Error('Provide an array containing 1–100 records.');
                  void save('/admin/companies/' + values.get('slug') + '/quarters/import', records);
                } catch (error) {
                  setStatus(error instanceof Error ? error.message : 'Invalid JSON');
                }
              }}
            >
              {picker}
              <label className="full">
                Quarterly records (JSON)
                <textarea
                  name="records"
                  required
                  maxLength={900000}
                  placeholder={
                    '[{"import_key":"company-fy2026-q1-v1","financial_year":2026,"quarter":1,"revenue":100,"source_url":"https://example.com/results"}]'
                  }
                />
              </label>
              <button className="primary-button" disabled={busy}>
                Import quarters
              </button>
            </form>
          </details>
        </section>
      )}
      {tab === 'IPOs' && (
        <section className="panel">
          <div className="section-heading">
            <h2>{editCompany ? 'Edit ' + editCompany.name : 'Add IPO'}</h2>
            <label>
              Edit existing
              <select
                value={editCompany?.slug || ''}
                onChange={(e) =>
                  setEditCompany(companies.find((c) => c.slug === e.target.value) || null)
                }
              >
                <option value="">New company</option>
                {companies.map((c) => (
                  <option key={c.id} value={c.slug}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <form
            className="admin-form"
            key={'ipo' + formKey + (editCompany?.id || '')}
            onSubmit={(e) => {
              e.preventDefault();
              const numeric = [
                'price_low',
                'price_high',
                'issue_price',
                'listing_price',
                'lot_size',
                'issue_size',
                'fresh_issue',
                'ofs',
                'baseline_pe',
                'baseline_market_cap',
                ...metrics.map((m) => 'baseline_' + m[0]),
              ];
              const body = parse(e.currentTarget, numeric);
              const baseline: Record<string, unknown> = {};
              for (const key of metrics.map((m) => m[0])) {
                if (body['baseline_' + key] !== undefined) baseline[key] = body['baseline_' + key];
                delete body['baseline_' + key];
              }
              if (!editCompany && Object.values(baseline).some((v) => v !== null))
                body.baseline = baseline;
              void save(
                '/admin/ipos' + (editCompany ? '/' + editCompany.slug : ''),
                body,
                editCompany ? 'PUT' : 'POST',
              );
            }}
          >
            <fieldset>
              <legend>Company & issue</legend>
              <div className="form-grid">
                <Fields
                  fields={[
                    ['name', 'Company name', 'text', true],
                    ['slug', 'Public slug', 'text', true],
                    ['sector', 'Sector', 'text', true],
                    ['ticker', 'Ticker'],
                  ]}
                  values={
                    editCompany
                      ? {
                          name: editCompany.name,
                          slug: editCompany.slug,
                          sector: editCompany.sector,
                          ticker: editCompany.ticker,
                        }
                      : {}
                  }
                />
                <label>
                  Exchange
                  <select name="exchange" defaultValue={editCompany?.exchange || 'NSE'}>
                    <option>NSE</option>
                    <option>BSE</option>
                  </select>
                </label>
                <label>
                  Board
                  <select name="board" defaultValue={editCompany?.board || 'Mainboard'}>
                    <option>Mainboard</option>
                    <option>SME</option>
                  </select>
                </label>
                <label>
                  IPO status
                  <select name="status" defaultValue={editCompany?.status || 'UPCOMING'}>
                    {['UPCOMING', 'OPEN', 'CLOSED', 'LISTED'].map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                </label>
                <Fields
                  fields={[
                    ['open_date', 'Open date', 'date'],
                    ['close_date', 'Close date', 'date'],
                    ['listing_date', 'Listing date', 'date'],
                    ['price_low', 'Lower price (₹)', 'number'],
                    ['price_high', 'Upper price (₹)', 'number'],
                    ['issue_price', 'Final issue price (₹)', 'number'],
                    ['listing_price', 'Listing price (₹)', 'number'],
                    ['lot_size', 'Lot size', 'number'],
                    ['issue_size', 'Issue size (₹ Cr)', 'number'],
                    ['fresh_issue', 'Fresh issue (₹ Cr)', 'number'],
                    ['ofs', 'OFS (₹ Cr)', 'number'],
                    ['screener_url', 'Screener URL', 'url'],
                    ['exchange_url', 'Exchange company URL', 'url'],
                    ['rhp_url', 'RHP URL', 'url'],
                  ]}
                  values={(editCompany as unknown as Values) || {}}
                />
                <Source />
              </div>
            </fieldset>
            {!editCompany && (
              <fieldset>
                <legend>IPO baseline · immutable after creation</legend>
                <div className="form-grid">
                  <Fields
                    fields={[
                      ...metrics.map(([k, label, type]) => ['baseline_' + k, label, type] as Field),
                      ['baseline_pe', 'IPO P/E', 'number'],
                      ['baseline_market_cap', 'IPO market cap (₹ Cr)', 'number'],
                    ]}
                  />
                </div>
              </fieldset>
            )}
            <button className="primary-button" disabled={busy}>
              Save IPO
            </button>
          </form>
        </section>
      )}
      {tab === 'Advertisements' && (
        <section className="panel">
          <h2>{editAd ? 'Edit advertisement' : 'Advertisement'}</h2>
          <p>Disabled placements render nothing on the public site.</p>
          <form
            className="form-grid"
            key={'ad' + formKey + (editAd?.id || '')}
            onSubmit={(e) => {
              e.preventDefault();
              const body = parse(e.currentTarget);
              body.enabled = new FormData(e.currentTarget).has('enabled');
              void save(
                '/admin/advertisements' + (editAd ? '/' + editAd.id : ''),
                body,
                editAd ? 'PUT' : 'POST',
              );
            }}
          >
            <Fields
              fields={[
                ['text', 'Ad text', 'text', true],
                ['destination_url', 'Destination URL', 'url', true],
                ['image_url', 'Image URL (optional)', 'url'],
              ]}
              values={editAd ? { ...editAd } : {}}
            />
            <label>
              Placement
              <select name="placement" defaultValue={editAd?.placement || 'home'}>
                <option value="home">Home</option>
                <option value="tracker">Tracker</option>
              </select>
            </label>
            <label className="inline-check">
              <input type="checkbox" name="enabled" defaultChecked={editAd?.enabled ?? false} />
              Enabled
            </label>
            <button className="primary-button" disabled={busy}>
              Save advertisement
            </button>
          </form>
          <div className="admin-records">
            {ads.map((a) => (
              <article key={a.id}>
                <p>
                  {a.text} · {a.enabled ? 'Enabled' : 'Disabled'}
                </p>
                <button onClick={() => setEditAd(a)}>Edit {a.text}</button>
              </article>
            ))}
          </div>
        </section>
      )}
      {tab === 'Audit' && (
        <section className="panel">
          <h2>Recent administrator activity</h2>
          {audit.map((a) => (
            <p key={a.id}>
              {human(a.action)} · {timestamp(a.created_at)}
            </p>
          ))}
        </section>
      )}
    </>
  );
}
