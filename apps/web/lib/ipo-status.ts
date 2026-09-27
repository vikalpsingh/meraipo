import type { Company } from './types';

export function ipoStatus(c: Pick<Company, 'status' | 'open_date' | 'close_date'>, today: string) {
  if (c.status === 'LISTED') return { tone: 'neutral', label: 'Listed' };
  if (c.status === 'CLOSED' || (c.close_date && c.close_date < today))
    return { tone: 'neutral', label: 'Closed' };
  if (c.open_date && c.open_date > today) return { tone: 'upcoming', label: 'Upcoming' };
  if (c.status === 'OPEN' && c.close_date === today)
    return { tone: 'closing', label: 'Closing today' };
  if (c.status === 'OPEN') return { tone: 'open', label: 'Open' };
  return { tone: 'upcoming', label: c.open_date ? 'Upcoming' : 'Dates awaited' };
}
