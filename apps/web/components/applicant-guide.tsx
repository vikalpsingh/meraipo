import Link from 'next/link';
import type { Company } from '@/lib/types';
import { date, timestamp } from '@/lib/format';
import { indiaDay, ipoEvents, calculatorData } from '@/lib/applicant';
import { ApplicationCalculator, ApplicationChecklist } from './applicant-tools';
import { SectionLinks } from './section-links';

export function TodayActions({
  companies,
  now = new Date(),
}: {
  companies: Company[];
  now?: Date;
}) {
  const today = indiaDay(now);
  const unique = [...new Map(companies.map((c) => [c.id, c])).values()];
  const opening = unique
    .filter((c) => c.status === 'UPCOMING' && c.open_date && c.open_date >= today)
    .sort((a, b) => a.open_date!.localeCompare(b.open_date!));
  const groups = [
    {
      title: 'Closing today',
      items: unique.filter((c) => c.status === 'OPEN' && c.close_date === today),
      anchor: 'apply',
      empty: 'No issues closing today',
    },
    {
      title: 'Opening next',
      items: opening.filter((c) => c.open_date === opening[0]?.open_date),
      anchor: 'apply',
      empty: 'Dates to be announced',
    },
    {
      title: 'Allotment due',
      items: unique.filter((c) => c.applicant_guide?.allotment_date === today),
      anchor: 'track',
      empty: 'None scheduled today',
    },
    {
      title: 'Listing today',
      items: unique.filter((c) => c.listing_date === today),
      anchor: 'track',
      empty: 'None scheduled today',
    },
  ];
  return (
    <section className="today-actions" aria-label="Your next IPO actions">
      <div className="section-heading">
        <h2>Your next move</h2>
        <span>{date(today)} · India time</span>
      </div>
      <div className="action-grid">
        {groups.map((group) => (
          <div className="action-tile" key={group.title}>
            <h3>{group.title}</h3>
            {group.items.length ? (
              <>
                <Link href={`/ipo/${group.items[0].slug}#${group.anchor}`}>
                  {group.items[0].name} ↗
                </Link>
                {group.title === 'Opening next' && <small>{date(group.items[0].open_date)}</small>}
                {group.items.length > 1 && (
                  <details>
                    <summary>+{group.items.length - 1} more</summary>
                    {group.items.slice(1).map((c) => (
                      <Link key={c.id} href={`/ipo/${c.slug}#${group.anchor}`}>
                        {c.name} ↗
                      </Link>
                    ))}
                  </details>
                )}
              </>
            ) : (
              <p>{group.empty}</p>
            )}
          </div>
        ))}
      </div>
      <p className="screen-note">
        Dates can change. Open the issue guide for its latest schedule and source.
      </p>
    </section>
  );
}

function Points({ text }: { text: string | null | undefined }) {
  return text ? (
    <ul>
      {text
        .split(/\r?\n/)
        .filter((s) => s.trim())
        .map((s, i) => (
          <li key={i}>{s}</li>
        ))}
    </ul>
  ) : (
    <p className="muted">Not reviewed yet.</p>
  );
}

export function ApplicantGuide({ company: c }: { company: Company }) {
  const g = c.applicant_guide;
  const verified = g?.verification_status === 'VERIFIED' && !c.is_demo;
  return (
    <>
      <SectionLinks />
      <section id="understand" className="panel company-brief">
        <p className="eyebrow">01 · UNDERSTAND THE BUSINESS</p>
        <h2>The company in 60 seconds</h2>
        <p className="brief-lead">
          {g?.business_summary ||
            'The business summary is awaiting editorial review. Read the original prospectus before making a decision.'}
        </p>
        <div className="brief-columns">
          <div>
            <h3>What supports the business</h3>
            <Points text={g?.strengths} />
          </div>
          <div>
            <h3>What could go wrong</h3>
            <Points text={g?.risks} />
          </div>
        </div>
        <details>
          <summary>Where will the IPO money go?</summary>
          <p>{g?.proceeds || 'Use of proceeds is awaiting review.'}</p>
          <p className="screen-note">
            Fresh issue proceeds go to the company. Offer-for-sale proceeds go to the selling
            shareholders.
          </p>
        </details>
        {g && (
          <p className="guide-source">
            {c.is_demo
              ? 'Illustrative demo summary'
              : verified
                ? 'Source reviewed'
                : 'Unverified editorial draft'}{' '}
            · Reviewed {date(g.reviewed_on)} ·{' '}
            <a href={g.source_url} target="_blank" rel="noreferrer">
              Read the source ↗
            </a>
          </p>
        )}
        <p className="screen-note">A research starting point, not an apply/avoid recommendation.</p>
      </section>
      <div className="applicant-grid">
        <div id="apply">
          <ApplicationCalculator company={calculatorData(c)} />
          <ApplicationChecklist />
        </div>
        <section id="track" className="panel ipo-timeline" aria-labelledby="timeline-title">
          <p className="eyebrow">03 · KEEP TRACK</p>
          <h2 id="timeline-title">Dates that matter</h2>
          <span className="badge">
            {verified && g?.schedule_status === 'CONFIRMED'
              ? 'Published schedule'
              : 'Tentative · check for changes'}
          </span>
          <ol>
            {ipoEvents(c).map((event) => (
              <li key={event.key}>
                <span>{event.label}</span>
                <strong>
                  {event.value
                    ? event.timed
                      ? timestamp(event.value)
                      : date(event.value)
                    : 'To be announced'}
                </strong>
              </li>
            ))}
          </ol>
          <p className="screen-note">
            All times are IST. Your broker may stop accepting bids earlier. Unblocking is an
            initiation date; bank processing times can differ.
          </p>
          <a className="outline-button" href={`/ipo/${c.slug}/calendar`} download>
            Add dates to calendar ↓
          </a>
          <p className="screen-note">
            Import these dates into your calendar. Saved dates will not update automatically if the
            schedule changes.
          </p>
          <div className="allotment-action">
            <h3>Did you get shares?</h3>
            {verified && g?.registrar_url && g.registrar_name ? (
              <>
                <a
                  className="primary-button"
                  href={g.registrar_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Check allotment with {g.registrar_name} ↗
                </a>
                <p className="screen-note">
                  Opens the issue registrar’s website. Results may not be available until the
                  registrar publishes them. Enter personal details only there.
                </p>
              </>
            ) : (
              <p>
                {c.is_demo
                  ? 'This fictional IPO has no real allotment result.'
                  : 'The official registrar link is awaiting verification.'}
              </p>
            )}
          </div>
          <details>
            <summary>UPI mandate missing?</summary>
            <p>
              Check your UPI app and application status with the broker or bank you used. Contact
              that intermediary before the applicable deadline. Submitting a bid alone does not
              confirm that funds were blocked.
            </p>
            <a
              href="https://www.nseindia.com/static/trade/e-ipo-faqs"
              target="_blank"
              rel="noreferrer"
            >
              NSE application guidance ↗
            </a>
          </details>
        </section>
      </div>
    </>
  );
}
