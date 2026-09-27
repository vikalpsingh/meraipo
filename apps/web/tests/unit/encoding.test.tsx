import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { IPOInterestTable } from '@/components/ipo-interest-table';
import type { Company } from '@/lib/types';

it('renders readable Indian currency, ranges, separators and missing values', () => {
  const company = {
    id: 'encoding',
    slug: 'encoding',
    name: 'Readable Company',
    board: 'Mainboard',
    status: 'OPEN',
    open_date: '2026-09-20',
    close_date: '2026-09-22',
    price_low: 1700,
    price_high: 1785,
    gmp: null,
  } as Company;
  const { container } = render(<IPOInterestTable companies={[company]} today="2026-09-22" />);
  expect(screen.getByRole('cell', { name: '₹1,700–₹1,785' })).toBeInTheDocument();
  expect(screen.getAllByTitle('Not reported by source')).toHaveLength(4);
  expect(container.textContent).toContain('Mainboard ·');
  expect(container.textContent).toContain('— means not reported');
  expect(container.textContent).not.toMatch(/\u00c2\u00b7|\u00e2\u20ac|\ufffd/);
});

it('keeps UI source files free of known UTF-8 decoding corruption', () => {
  const failures: string[] = [];
  function scan(dir: string) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const file = path.join(dir, entry.name);
      if (entry.isDirectory()) scan(file);
      else if (
        /\.(tsx?|css)$/.test(file) &&
        /\u00c2\u00b7|\u00c3[\u00b7\u2014]|\u00e2\u20ac|\ufffd/.test(readFileSync(file, 'utf8'))
      )
        failures.push(file);
    }
  }
  for (const directory of ['app', 'components', 'lib']) scan(directory);
  expect(failures).toEqual([]);
});
