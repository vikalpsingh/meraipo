import type { Company } from '@/lib/types';

export function gmpPresentation(c: Company) {
  const value =
    c.gmp == null || c.price_high == null || c.price_high <= 0
      ? null
      : (c.gmp / c.price_high) * 100;
  const tone =
    value != null && value > 100
      ? 'gold'
      : value != null && value > 40
        ? 'dark-green'
        : value != null && value > 20
          ? 'light-green'
          : 'neutral';
  return { value, tone };
}
