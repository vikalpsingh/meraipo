import Image from 'next/image';
import Link from 'next/link';
import { CompanyPreview } from './company-preview';
import type { SiteMessage, Advertisement, Company } from '@/lib/types';
import { money, percent, date, timestamp, human } from '@/lib/format';
export function Message({ message }: { message: SiteMessage | null }) {
  if (!message) return null;
  return (
    <aside
      className="editorial"
      aria-label={message.kind === 'quote' ? 'Investing thought' : 'Site announcement'}
    >
      <span className="eyebrow">{message.title}</span>
      {message.kind === 'quote' ? (
        <blockquote>“{message.content}”</blockquote>
      ) : (
        <p>{message.content}</p>
      )}
      {message.attribution && <cite>— {message.attribution}</cite>}
    </aside>
  );
}
export function Ads({ items }: { items: Advertisement[] }) {
  if (!items.length) return null;
  return (
    <div>
      {items.map((ad) => (
        <aside className="advertisement" key={ad.id}>
          <small>ADVERTISEMENT</small>
          <a href={ad.destination_url} rel="sponsored noopener noreferrer" target="_blank">
            {ad.image_url && (
              <Image
                unoptimized
                src={ad.image_url}
                alt=""
                loading="lazy"
                width={600}
                height={180}
              />
            )}
            <span>{ad.text} ↗</span>
          </a>
        </aside>
      ))}
    </div>
  );
}
export function Trust({ company }: { company: Company }) {
  return (
    <span className="trust">
      {company.is_demo
        ? 'Demo data'
        : company.quality === 'VERIFIED'
          ? '✓ Verified'
          : company.quality === 'PARTIAL'
            ? 'Partial data'
            : company.quality === 'CONFLICT'
              ? 'Conflicting sources'
              : company.quality === 'STALE'
                ? 'Update pending'
                : 'Unverified'}
    </span>
  );
}
export function IPOCard({ company: c }: { company: Company }) {
  return (
    <article className="ipo-card">
      <div className="card-top">
        <span className="company-icon">{c.name.slice(0, 2).toUpperCase()}</span>
        <Trust company={c} />
      </div>
      <CompanyPreview company={c} heading />
      <p>
        {c.board} · {c.sector}
      </p>
      <p className="dates">
        {date(c.open_date)} – {date(c.close_date)}
      </p>
      <dl>
        <div>
          <dt>Price band</dt>
          <dd>
            {c.price_low === null || c.price_high === null
              ? 'To be announced'
              : `${money(c.price_low)}–${money(c.price_high)}`}
          </dd>
        </div>
        <div>
          <dt>Minimum application</dt>
          <dd>
            {c.minimum_application === null ? 'To be announced' : money(c.minimum_application)}
          </dd>
        </div>
        <div>
          <dt>Lot size</dt>
          <dd>{c.lot_size === null ? 'To be announced' : `${c.lot_size} shares`}</dd>
        </div>
        <div>
          <dt>Issue size</dt>
          <dd>{c.issue_size === null ? 'To be announced' : `${money(c.issue_size)} Cr`}</dd>
        </div>
      </dl>
      <div className="gmp">
        <span>
          GMP{' '}
          <small>
            {c.gmp_quality === 'STALE' ? 'Stale · ' : ''}
            {c.gmp === null ? 'Not available' : timestamp(c.gmp_timestamp)}
          </small>
        </span>
        <b>{c.gmp === null ? 'GMP unavailable' : `${money(c.gmp)} (${percent(c.gmp_percent)})`}</b>
      </div>
      <details>
        <summary>Issue details</summary>
        <dl>
          <div>
            <dt>Expected listing</dt>
            <dd>{date(c.listing_date)}</dd>
          </div>
          <div>
            <dt>Fresh issue</dt>
            <dd>{c.fresh_issue === null ? 'To be announced' : `${money(c.fresh_issue)} Cr`}</dd>
          </div>
          <div>
            <dt>Offer for sale</dt>
            <dd>{c.ofs === null ? 'To be announced' : `${money(c.ofs)} Cr`}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>{human(c.status)}</dd>
          </div>
        </dl>
      </details>
      <Link className="card-link" href={'/ipo/' + c.slug}>
        {c.status === 'LISTED' ? 'Company journey' : 'View IPO guide'} <span>↗</span>
      </Link>
    </article>
  );
}
