'use client';

import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';

type Config = {
  provider_mode: string;
  market_scheduler_enabled: boolean;
  market_scheduler_driver: 'celery' | 'vercel';
  exchange_direct_enabled: boolean;
  nse_subscription_categories_enabled: boolean;
  ipo_data_provider: 'exchange' | 'ipoalerts' | 'feed';
  ipoalerts_api_key_configured: boolean;
  ipoalerts_page_size: number;
  market_feeds_json: string;
  exchange_sources_json: string;
  bse_ipo_issues_json: string;
  trading_holidays: string;
  trading_calendar_year: number;
  source: string;
  updated_at: string | null;
};

export function MarketConfig({ csrf }: { csrf: string }) {
  const [config, setConfig] = useState<Config | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch('/api/v1/admin/market/config', { cache: 'no-store' })
      .then(async (response) => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.error?.message || 'Configuration unavailable');
        setConfig(body);
      })
      .catch((error: Error) => setMessage(error.message));
  }, []);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage('');
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const body = {
      provider_mode: form.get('provider_mode'),
      market_scheduler_enabled: form.has('market_scheduler_enabled'),
      market_scheduler_driver: form.get('market_scheduler_driver'),
      exchange_direct_enabled: form.has('exchange_direct_enabled'),
      nse_subscription_categories_enabled: form.has('nse_subscription_categories_enabled'),
      ipo_data_provider: form.get('ipo_data_provider'),
      ipoalerts_api_key: form.get('ipoalerts_api_key') || null,
      clear_ipoalerts_api_key: form.has('clear_ipoalerts_api_key'),
      ipoalerts_page_size: Number(form.get('ipoalerts_page_size')),
      market_feeds_json: form.get('market_feeds_json'),
      exchange_sources_json: form.get('exchange_sources_json'),
      bse_ipo_issues_json: form.get('bse_ipo_issues_json'),
      trading_holidays: form.get('trading_holidays'),
      trading_calendar_year: Number(form.get('trading_calendar_year')),
    };
    try {
      const response = await fetch('/api/v1/admin/market/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify(body),
      });
      const result = await response.json();
      if (!response.ok)
        throw new Error(result.error?.message || 'Configuration could not be saved');
      setConfig(result);
      setMessage('Configuration saved. New job runs will use these values.');
      formElement.reset();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Configuration could not be saved');
    } finally {
      setBusy(false);
    }
  }

  if (!config) return <p role="status">{message || 'Loading market configuration…'}</p>;

  return (
    <section className="panel" aria-labelledby="config-heading">
      <h2 id="config-heading">Market data configuration</h2>
      <p>
        Scheduled and manual jobs load these values when each run starts. API keys are encrypted in
        the database and are never returned to the browser.
      </p>
      <p className="muted">
        Current source: {config.source}. API key:{' '}
        {config.ipoalerts_api_key_configured ? 'configured' : 'not configured'}.
      </p>
      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}
      <form className="admin-form" onSubmit={save}>
        <fieldset>
          <legend>Provider selection</legend>
          <div className="form-grid">
            <label>
              Provider mode
              <select name="provider_mode" defaultValue={config.provider_mode}>
                <option value="manual">Manual</option>
                <option value="market-feeds">Automated market feeds</option>
              </select>
            </label>
            <label>
              IPO data provider
              <select name="ipo_data_provider" defaultValue={config.ipo_data_provider}>
                <option value="ipoalerts">IPOAlerts</option>
                <option value="exchange">NSE/BSE directly</option>
                <option value="feed">Configured feed</option>
              </select>
            </label>
            <label>
              Scheduler driver
              <select name="market_scheduler_driver" defaultValue={config.market_scheduler_driver}>
                <option value="celery">Docker / Celery</option>
                <option value="vercel">Vercel cron</option>
              </select>
            </label>
            <label>
              IPOAlerts page size
              <input
                name="ipoalerts_page_size"
                type="number"
                min="1"
                max="100"
                defaultValue={config.ipoalerts_page_size}
                required
              />
            </label>
            <label className="inline-check">
              <input
                type="checkbox"
                name="market_scheduler_enabled"
                defaultChecked={config.market_scheduler_enabled}
              />
              Enable scheduled jobs
            </label>
            <label className="inline-check">
              <input
                type="checkbox"
                name="exchange_direct_enabled"
                defaultChecked={config.exchange_direct_enabled}
              />
              Enable direct NSE/BSE collection
            </label>
            <label className="inline-check">
              <input
                type="checkbox"
                name="nse_subscription_categories_enabled"
                defaultChecked={config.nse_subscription_categories_enabled}
              />
              Collect NSE subscription categories
            </label>
          </div>
        </fieldset>
        <fieldset>
          <legend>Credentials</legend>
          <div className="form-grid">
            <label className="full">
              IPOAlerts API key
              <input
                name="ipoalerts_api_key"
                type="password"
                autoComplete="new-password"
                placeholder={
                  config.ipoalerts_api_key_configured
                    ? 'Stored securely — enter only to replace'
                    : 'Enter API key'
                }
              />
            </label>
            <label className="inline-check full">
              <input name="clear_ipoalerts_api_key" type="checkbox" /> Remove the stored API key
            </label>
          </div>
        </fieldset>
        <fieldset>
          <legend>Trading calendar</legend>
          <div className="form-grid">
            <label>
              Calendar year
              <input
                name="trading_calendar_year"
                type="number"
                min="0"
                max="2100"
                defaultValue={config.trading_calendar_year}
                required
              />
            </label>
            <label className="full">
              Holidays (YYYY-MM-DD, comma separated)
              <textarea name="trading_holidays" defaultValue={config.trading_holidays} />
            </label>
          </div>
        </fieldset>
        <fieldset>
          <legend>Advanced feed mappings</legend>
          <p className="muted">JSON is validated before anything is saved.</p>
          <div className="form-grid">
            <label className="full">
              Market feeds JSON
              <textarea name="market_feeds_json" defaultValue={config.market_feeds_json} required />
            </label>
            <label className="full">
              Exchange sources JSON
              <textarea
                name="exchange_sources_json"
                defaultValue={config.exchange_sources_json}
                required
              />
            </label>
            <label className="full">
              BSE IPO issue mappings JSON
              <textarea
                name="bse_ipo_issues_json"
                defaultValue={config.bse_ipo_issues_json}
                required
              />
            </label>
          </div>
        </fieldset>
        <button className="primary-button" disabled={busy}>
          {busy ? 'Saving…' : 'Save configuration'}
        </button>
      </form>
    </section>
  );
}
