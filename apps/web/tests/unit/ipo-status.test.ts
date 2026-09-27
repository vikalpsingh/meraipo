import { expect, it } from 'vitest';
import { indiaDay } from '@/lib/applicant';
import { ipoStatus } from '@/lib/ipo-status';
const issue = { status: 'OPEN', open_date: '2026-09-18', close_date: '2026-09-21' } as const;
it('changes deadline label at midnight IST', () => {
  expect(ipoStatus(issue, indiaDay(new Date('2026-09-20T18:29:59Z'))).tone).toBe('open');
  expect(ipoStatus(issue, indiaDay(new Date('2026-09-20T18:30:00Z'))).label).toBe('Closing today');
});
it('handles stale source status, future dates and listed issues', () => {
  expect(ipoStatus(issue, '2026-09-22').label).toBe('Closed');
  expect(ipoStatus(issue, '2026-09-17').tone).toBe('upcoming');
  expect(ipoStatus({ ...issue, close_date: null }, '2026-09-21').label).toBe('Open');
  expect(ipoStatus({ ...issue, status: 'CLOSED' }, '2026-09-21').label).toBe('Closed');
  expect(ipoStatus({ ...issue, status: 'LISTED' }, '2026-09-21').label).toBe('Listed');
});
