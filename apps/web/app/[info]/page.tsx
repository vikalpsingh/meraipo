import Link from 'next/link';
import { notFound } from 'next/navigation';
const pages: Record<string, { title: string; intro: string; sections: [string, string][] }> = {
  about: {
    title: 'From IPO to Value Creator',
    intro:
      'MeraIPO follows what happens after a company rings the listing bell. The focus is the business, quarter by quarter.',
    sections: [
      [
        'A small set of useful questions',
        'How is revenue changing? Is profitability improving? What has happened to debt and cash flow? How does the share price compare with the business record?',
      ],
      [
        'Research, not recommendations',
        'MeraIPO presents reported facts and transparent calculations. Screening views are starting points for your own research. There are no buy, sell, apply or avoid ratings.',
      ],
      [
        'An honest starting point',
        'The demo edition uses fictional companies and clearly marked fixture values. It is not a live market feed.',
      ],
    ],
  },
  methodology: {
    title: 'A method you can inspect',
    intro:
      'Financial values and business classifications are deterministic. AI does not choose financial values or overwrite scores.',
    sections: [
      [
        'Price returns',
        'Return = (current price ÷ baseline price − 1) × 100. The baseline must be positive. Returns exclude dividends and corporate actions unless the underlying series has been explicitly adjusted. Drawdown compares current price with the recorded all-time high; a 20% or larger decline is the Price corrected screen.',
      ],
      [
        'Business trend, version 1',
        'Two successive comparable results must each have revenue YoY, PAT YoY and EBITDA margin. Otherwise the state is Insufficient data. A non-positive prior-year base yields unavailable growth, not a misleading percentage.',
      ],
      [
        'Weights and thresholds',
        'Revenue YoY change: 25; PAT YoY change: 25; EBITDA-margin change: 20; ROCE change: 10; debt reduction: 10; cash-flow quality: 10. Changes over 0.5 receive +1 or −1; smaller changes receive 0. Cash flow receives +1 when at least positive PAT, −1 when negative, otherwise 0. Available weights normalize the score to −100 to +100. At least +30 is Improving; at most −30 is Weakening; otherwise Stable.',
      ],
      [
        'Reading the record',
        'Financial years end in March: FY2027 runs April 2026 to March 2027. Q1 is April–June. An IPO baseline is a separate snapshot and is never overwritten by later results. Corrections are retained as revisions. An em dash means unavailable.',
      ],
    ],
  },
  'data-sources': {
    title: 'Know where a number comes from',
    intro:
      'Official filings, derived calculations and unofficial GMP are different kinds of information.',
    sections: [
      [
        'Official source hierarchy',
        'IPO and filing records are intended to come from NSE, BSE, SEBI and company filings through permitted access. Current prices require a licensed EOD or delayed-data source. Live adapters are disabled until access and display rights are configured.',
      ],
      [
        'Provenance and conflicts',
        'Records can retain a provider, source URL, source timestamp, fetched time, verification status and verified time. Conflicting values are flagged rather than silently merged. Stale GMP is marked after its configured freshness limit.',
      ],
      [
        'Deeper research',
        'Screener is an outbound research link. MeraIPO does not scrape or republish its dataset. Demo source links point to illustrative example records only.',
      ],
    ],
  },
  disclaimer: {
    title: 'Research with perspective',
    intro:
      'MeraIPO provides IPO, market and company information for research and educational purposes. It does not guarantee IPO allotment, listing gains or investment returns.',
    sections: [
      [
        'Grey-market information',
        'Unofficial grey-market information. GMP does not guarantee listing price or investment return.',
      ],
      [
        'Your research',
        'Historical growth, financial ratios, screens and price returns do not predict future results. Check original filings, data dates and risks before making decisions. Nothing here is personalized investment advice.',
      ],
      [
        'Data limitations',
        'Prices may be delayed and reported financials may be revised. Missing data is shown explicitly. The demo edition must not be used for investment decisions.',
      ],
    ],
  },
  privacy: {
    title: 'Privacy',
    intro: 'V1 has no public registration, portfolio connection or broker integration.',
    sections: [
      [
        'What the service stores',
        'Administrator email, Argon2id password hashes, hashed session tokens, audit records and security-related request logs support site maintenance. Admin session cookies are necessary for authentication and CSRF protection.',
      ],
      [
        'What we do not request',
        'Do not send PAN, demat, UPI, bank or broker credentials. Public research does not require personal investment information.',
      ],
      [
        'Deployment configuration',
        'The operator must publish its contact details, retention periods and hosting/subprocessor information before a public production launch. No advertising tracker or analytics integration is enabled in this implementation.',
      ],
    ],
  },
  terms: {
    title: 'Terms of use',
    intro:
      'Use MeraIPO to explore and verify research information, not as an execution or advisory service.',
    sections: [
      [
        'Permitted use',
        'Respect source attribution and third-party document rights. Do not bypass access controls, disrupt the service or misuse administrator functions.',
      ],
      [
        'Information quality',
        'Data is provided with its source and freshness limitations. No guarantee of availability, completeness, allotment or investment performance is made.',
      ],
      [
        'Before public launch',
        'These product terms are a draft. The site operator must supply its legal identity and obtain appropriate review before opening the production service to the public.',
      ],
    ],
  },
  contact: {
    title: 'Contact MeraIPO',
    intro:
      'Corrections are most useful when they include the company name, reporting period and a link to the original filing.',
    sections: [
      [
        'Report a data issue',
        'The public contact channel has not been configured yet. Administrators can correct records in the protected maintenance console, preserving the prior financial revision. Do not include sensitive personal or financial credentials.',
      ],
    ],
  },
};
export function generateStaticParams() {
  return Object.keys(pages).map((info) => ({ info }));
}
export async function generateMetadata({ params }: { params: Promise<{ info: string }> }) {
  const { info } = await params;
  return { title: pages[info]?.title, alternates: { canonical: '/' + info } };
}
export default async function Info({ params }: { params: Promise<{ info: string }> }) {
  const { info } = await params;
  const page = pages[info];
  if (!page) notFound();
  return (
    <main className="prose">
      <p className="eyebrow">MERAIPO · TRUST & TRANSPARENCY</p>
      <h1>
        {page.title}
        <span>.</span>
      </h1>
      <p>{page.intro}</p>
      {page.sections.map(([title, text]) => (
        <section key={title}>
          <h2>{title}</h2>
          <p>{text}</p>
        </section>
      ))}
      <Link className="outline-button" href={info === 'methodology' ? '/tracker' : '/methodology'}>
        {info === 'methodology' ? 'Explore IPO Tracker' : 'Read our methodology'} →
      </Link>
    </main>
  );
}
