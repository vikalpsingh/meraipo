import Image from 'next/image';
import { nseIpoStatusUrl } from '@/lib/nse-ipo-status';

export function IPOStatusFrame() {
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
      </div>
      <p>
        Select the preview below to check your status on NSE in a new tab. Your MeraIPO page stays
        open.
      </p>
      <p className="small">
        Enter your details only in NSE’s form. MeraIPO does not receive your PAN, application number
        or results.
      </p>
      <a
        className="ipo-status-preview"
        href={nseIpoStatusUrl}
        target="_blank"
        rel="noopener noreferrer"
        aria-label="Check IPO bid or allotment status on NSE (opens in a new tab)"
      >
        <span className="ipo-status-preview-caption">NSE form preview · Open on NSE ↗</span>
        <Image
          src="/ipo-status/nse-status-preview.png"
          width={897}
          height={500}
          sizes="(max-width: 760px) 90vw, 897px"
          alt="Preview of NSE’s IPO bid and allotment form with IPO selection, PAN or application number fields. This is an image, not an interactive form."
        />
      </a>
    </section>
  );
}
