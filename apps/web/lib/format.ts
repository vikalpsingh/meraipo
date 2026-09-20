export function money(value: number | null | undefined) {
  return value === null || value === undefined
    ? '—'
    : new Intl.NumberFormat('en-IN', {
        style: 'currency',
        currency: 'INR',
        minimumFractionDigits: 0,
        maximumFractionDigits: 2,
      }).format(value);
}
export function number(value: number | null | undefined) {
  return value === null || value === undefined
    ? '—'
    : new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(value);
}
export function percent(value: number | null | undefined) {
  return value === null || value === undefined
    ? '—'
    : `${value > 0 ? '+' : ''}${value.toFixed(1)}%`;
}
export function date(value: string | null | undefined) {
  return value
    ? new Intl.DateTimeFormat('en-IN', {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
        timeZone: 'Asia/Kolkata',
      }).format(new Date(value))
    : 'To be announced';
}
export function timestamp(value: string | null | undefined) {
  return value
    ? new Intl.DateTimeFormat('en-IN', {
        dateStyle: 'medium',
        timeStyle: 'short',
        timeZone: 'Asia/Kolkata',
      }).format(new Date(value)) + ' IST'
    : 'Timestamp unavailable';
}
export function fiscalToday(now = new Date()) {
  const year = now.getUTCFullYear(),
    month = now.getUTCMonth() + 1;
  return { fy: year + (month >= 4 ? 1 : 0), quarter: Math.floor(((month - 4 + 12) % 12) / 3) + 1 };
}
export function human(value: string) {
  return value
    .toLowerCase()
    .replaceAll('_', ' ')
    .replace(/^./, (s) => s.toUpperCase());
}
