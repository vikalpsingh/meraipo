import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { TrackerPageSize } from '@/components/tracker-page-size';
import { defaultTrackerPageSize, validTrackerPageSize } from '@/lib/tracker-pagination';

const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => router }));
beforeEach(() => vi.clearAllMocks());

it.each([
  [412, 10],
  [767, 10],
  [768, 20],
  [1279, 20],
  [1280, 50],
  [1920, 50],
])('defaults a %i pixel viewport to %i rows', (width, expected) => {
  expect(defaultTrackerPageSize(width)).toBe(expected);
});
it('offers only 10, 20, 50 and 100 and preserves filters when changing rows', () => {
  render(
    <TrackerPageSize query="page_size=20&page=3&sort=return_ipo&order=desc&board=SME" size={20} />,
  );
  expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual([
    '10',
    '20',
    '50',
    '100',
  ]);
  expect(router.replace).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole('combobox', { name: 'Rows per page' }), {
    target: { value: '100' },
  });
  expect(router.push).toHaveBeenCalledWith(
    '/tracker?page_size=100&sort=return_ipo&order=desc&board=SME',
    { scroll: false },
  );
});
it('sets the initial device default without retaining an out-of-range page', () => {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 412 });
  render(<TrackerPageSize query="sort=drawdown&page=8" size={20} />);
  expect(router.replace).toHaveBeenCalledWith('/tracker?sort=drawdown&page_size=10', {
    scroll: false,
  });
});
it.each(['0', '25', '101', '-10', 'foo', '', null])('rejects unsupported size %s', (value) => {
  expect(validTrackerPageSize(value)).toBe(false);
});
it('retains an explicit desktop-sized choice on mobile', () => {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 412 });
  render(<TrackerPageSize query="page_size=100" size={100} />);
  expect(screen.getByRole('combobox')).toHaveValue('100');
  expect(router.replace).not.toHaveBeenCalled();
});
