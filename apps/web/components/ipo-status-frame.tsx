'use client';

import { useState } from 'react';
import { nseIpoStatusUrl } from '@/lib/nse-ipo-status';

export function IPOStatusFrame({ embedEnabled = true }: { embedEnabled?: boolean }) {
  const [failed, setFailed] = useState(false);
  const showFrame = embedEnabled && !failed;
  return (
    <section className="panel ipo-status-panel" aria-label="NSE IPO bid verification">
      <div className="ipo-status-actions">
        <a
          className="primary-button"
          href={nseIpoStatusUrl}
          target="_blank"
          rel="noopener noreferrer"
        >
          Open on NSE ↗
        </a>
        {showFrame && (
          <button className="outline-button" type="button" onClick={() => setFailed(true)}>
            Hide embedded form
          </button>
        )}
      </div>
      <p role="status">
        {showFrame
          ? 'If the form is blank or blocked, open it on NSE in a new tab. Your MeraIPO page stays open.'
          : 'The embedded form is unavailable or hidden. Open on NSE to check your status; your MeraIPO page stays open.'}
      </p>
      <p className="small">
        Enter your details only in NSE’s form. MeraIPO does not receive your PAN, application number
        or results.
      </p>
      {showFrame && (
        <iframe
          className="ipo-status-frame"
          src={nseIpoStatusUrl}
          title="NSE IPO bid and allotment verification form"
          referrerPolicy="no-referrer"
          sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox"
          onError={() => setFailed(true)}
        />
      )}
    </section>
  );
}
