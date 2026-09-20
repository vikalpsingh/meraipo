import { test, expect } from './fixtures';

test('imported financial and price data render without overloading the journey', async ({
  page,
  request,
}) => {
  const response = await request.get('/api/v1/companies/integration-market-fixture/journey');
  expect(response.ok()).toBe(true);
  const company = await response.json();
  expect(company.quarters).toHaveLength(10);
  expect(company.annuals).toHaveLength(4);
  expect(company.return_ipo).toBe(45);
  await page.goto('/ipo/integration-market-fixture');
  await expect(page.getByRole('heading', { name: 'Integration Market Fixture.' })).toBeVisible();
  const quarterly = page.getByRole('region', { name: 'Quarterly financial history' });
  await expect(quarterly.getByRole('columnheader')).toHaveCount(10); // metric + baseline + eight quarters
  await expect(quarterly.getByRole('columnheader').nth(2)).toContainText('Q1 FY27');
  await expect(page.getByText('+45.0%', { exact: true })).toBeVisible();
  await page.getByText('Annual financial history · latest four years', { exact: true }).click();
  const annual = page.getByRole('region', { name: 'Annual financial history' });
  await expect(annual.getByRole('row')).toHaveCount(5);
  await expect(annual.getByRole('row').nth(1)).toContainText('FY2026');
  await expect(annual).not.toContainText('FY2022');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});

test('financial companies use appropriate metrics and missing comparisons stay missing', async ({
  page,
}) => {
  await page.goto('/ipo/integration-bank-fixture');
  const table = page.getByRole('region', { name: 'Quarterly financial history' });
  await expect(
    table.getByRole('rowheader', { name: 'Net interest income', exact: true }),
  ).toBeVisible();
  await expect(table.getByRole('rowheader', { name: 'EBITDA', exact: true })).toHaveCount(0);
  await expect(
    table
      .getByRole('row')
      .filter({ has: page.getByRole('rowheader', { name: 'PAT YoY', exact: true }) }),
  ).toContainText('—');
  await expect(
    table
      .getByRole('row')
      .filter({ has: page.getByRole('rowheader', { name: 'Total income', exact: true }) }),
  ).toContainText('300');
});

test('imported subscription snapshots are readable and GMP stays unofficial', async ({
  page,
  request,
}) => {
  const response = await request.get('/api/v1/ipos/open');
  const result = await response.json();
  const slug = (result.items as { slug: string }[]).map((company) => company.slug).sort()[0];
  await page.goto('/ipo/' + slug);
  await expect(page.getByRole('heading', { name: 'Market interest', exact: true })).toBeVisible();
  await expect(page.getByText('2.5×', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Unofficial GMP', exact: true })).toBeVisible();
  await expect(
    page.getByText('Higher subscription does not guarantee returns.', { exact: false }),
  ).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});
