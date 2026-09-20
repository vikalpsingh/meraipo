import { describe, it, expect } from 'vitest';
import { money, number, percent, date, fiscalToday } from '../../lib/format';
describe('financial presentation', () => {
  it('distinguishes a missing value from zero', () => {
    expect(money(null)).toBe('—');
    expect(number(undefined)).toBe('—');
    expect(money(0)).toBe('₹0');
    expect(percent(0)).toBe('0.0%');
  });
  it('keeps signs visible without color', () => {
    expect(percent(-12.3)).toBe('-12.3%');
    expect(percent(12)).toBe('+12.0%');
  });
  it('does not fabricate upcoming dates', () => {
    expect(date(null)).toBe('To be announced');
  });
  it('uses Indian financial year boundaries', () => {
    expect(fiscalToday(new Date('2026-03-31T12:00:00Z'))).toEqual({ fy: 2026, quarter: 4 });
    expect(fiscalToday(new Date('2026-04-01T12:00:00Z'))).toEqual({ fy: 2027, quarter: 1 });
  });
});
