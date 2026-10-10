export const trackerPageSizes = [10, 20, 50, 100] as const;

export function validTrackerPageSize(value: string | null | undefined): boolean {
  return trackerPageSizes.some((size) => String(size) === value);
}

export function defaultTrackerPageSize(width: number): number {
  return width < 768 ? 10 : width < 1280 ? 20 : 50;
}

export function trackerPageSizeHref(query: string, size: number): string {
  const params = new URLSearchParams(query);
  params.set('page_size', String(size));
  params.delete('page');
  return '/tracker?' + params;
}
