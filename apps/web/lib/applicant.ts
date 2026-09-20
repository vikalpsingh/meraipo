import type { Company, ApplicantGuide } from './types';

export type CalculatorCompany = Pick<
  Company,
  'board' | 'status' | 'is_demo' | 'lot_size' | 'price_high'
> & {
  applicant_guide: Pick<
    ApplicantGuide,
    'category' | 'min_lots' | 'max_lots' | 'max_amount' | 'verification_status'
  > | null;
};
export function calculatorData(c: Company): CalculatorCompany {
  const g = c.applicant_guide;
  return {
    board: c.board,
    status: c.status,
    is_demo: c.is_demo,
    lot_size: c.lot_size,
    price_high: c.price_high,
    applicant_guide: g
      ? {
          category: g.category,
          min_lots: g.min_lots,
          max_lots: g.max_lots,
          max_amount: g.max_amount,
          verification_status: g.verification_status,
        }
      : null,
  };
}

export function indiaDay(now = new Date()) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(now);
}

export function applicationEstimate(c: CalculatorCompany, input: string) {
  const g = c.applicant_guide;
  if (
    !g?.min_lots ||
    (!g.max_lots && !g.max_amount) ||
    (!c.is_demo && g.verification_status !== 'VERIFIED')
  )
    return {
      error: 'Application rules are awaiting review. Check the issue prospectus or your broker.',
    };
  if (!c.price_high || !c.lot_size)
    return { error: 'Price band or lot size is not available yet.' };
  const lots = Number(input);
  if (!/^\d+$/.test(input) || !Number.isSafeInteger(lots) || lots < g.min_lots)
    return { error: `Enter a whole number of lots, at least ${g.min_lots}.` };
  const shares = lots * c.lot_size;
  const scaled = Math.round(c.price_high * 10000) * shares;
  if (!Number.isSafeInteger(scaled) || !Number.isSafeInteger(shares))
    return { error: 'This amount is outside the supported range.' };
  const amount = scaled / 10000;
  if ((g.max_lots && lots > g.max_lots) || (g.max_amount && amount > g.max_amount))
    return {
      error: `This exceeds the published limit for ${g.category}. Choose fewer lots or check another category with your broker.`,
    };
  return { shares, amount, lots };
}

export type IPOEvent = { key: string; label: string; value: string | null; timed?: boolean };
export function ipoEvents(c: Company): IPOEvent[] {
  const g = c.applicant_guide;
  return [
    { key: 'opens', label: 'Applications open', value: c.open_date },
    {
      key: 'closes',
      label: 'Applications close',
      value: g?.bid_deadline || c.close_date,
      timed: !!g?.bid_deadline,
    },
    {
      key: 'mandate',
      label: 'Accept UPI mandate by',
      value: g?.mandate_deadline || null,
      timed: true,
    },
    { key: 'allotment', label: 'Allotment expected', value: g?.allotment_date || null },
    { key: 'unblock', label: 'Unblocking starts', value: g?.unblock_date || null },
    { key: 'listing', label: 'Expected listing', value: c.listing_date },
  ];
}

const escapeICS = (s: string) =>
  s.replace(/\\/g, '\\\\').replace(/\r?\n/g, '\\n').replace(/;/g, '\\;').replace(/,/g, '\\,');
const compactUTC = (s: string) =>
  new Date(s)
    .toISOString()
    .replace(/[-:]/g, '')
    .replace(/\.\d{3}Z$/, 'Z');
function fold(line: string) {
  const lines: string[] = [];
  let current = '',
    bytes = 0;
  for (const char of line) {
    const width = new TextEncoder().encode(char).length;
    if (bytes + width > 75) {
      lines.push(current);
      current = ' ';
      bytes = 1;
    }
    current += char;
    bytes += width;
  }
  return [...lines, current].join('\r\n');
}
export function calendar(c: Company, now = new Date()) {
  const tentative =
    c.applicant_guide?.schedule_status !== 'CONFIRMED' ||
    c.applicant_guide?.verification_status !== 'VERIFIED' ||
    c.is_demo;
  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//MeraIPO//Applicant Calendar//EN',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
  ];
  for (const event of ipoEvents(c).filter((e) => e.value)) {
    lines.push(
      'BEGIN:VEVENT',
      `UID:${c.slug}-${event.key}@meraipo`,
      `DTSTAMP:${compactUTC(now.toISOString())}`,
      event.timed
        ? `DTSTART:${compactUTC(event.value!)}`
        : `DTSTART;VALUE=DATE:${event.value!.replace(/-/g, '')}`,
      `DURATION:${event.timed ? 'PT15M' : 'P1D'}`,
      `SUMMARY:${escapeICS(`${c.is_demo ? '[DEMO] ' : ''}${tentative ? '[Tentative] ' : ''}${c.name}: ${event.label}`)}`,
      `DESCRIPTION:${escapeICS('Verify the latest issue schedule and your broker cutoff before acting. This downloaded calendar does not update automatically. ' + (c.applicant_guide?.source_url || ''))}`,
      `STATUS:${tentative ? 'TENTATIVE' : 'CONFIRMED'}`,
      'TRANSP:TRANSPARENT',
      'BEGIN:VALARM',
      'ACTION:DISPLAY',
      'TRIGGER:-PT2H',
      'DESCRIPTION:Review IPO schedule',
      'END:VALARM',
      'END:VEVENT',
    );
  }
  return [...lines, 'END:VCALENDAR'].map(fold).join('\r\n') + '\r\n';
}
