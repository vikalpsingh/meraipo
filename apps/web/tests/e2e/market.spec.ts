import { test, expect } from './fixtures';

test('scheduler setup is protected, understandable and controllable', async ({
  page,
  request,
}, testInfo) => {
  expect((await request.get('/api/v1/admin/market')).status()).toBe(401);
  expect((await request.get('/api/v1/admin/market/errors')).status()).toBe(401);
  await page.route('**/api/v1/admin/market/errors', (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: 'error-fixture',
            run_id: 'run-fixture',
            job_name: 'sync-ipos',
            run_status: 'PARTIAL',
            created_at: '2026-09-20T15:00:00Z',
            provider: 'NSE',
            item: 'https://www.nseindia.com/api/example',
            code: 'EXCHANGE_HTTP_404',
            detail: 'Verify the official endpoint and trading date, then rerun the job.',
          },
        ],
      },
    }),
  );
  expect((await request.get('/api/cron/results')).status()).toBe(401);
  await page.goto('/meraadmin');
  await page.getByLabel('Email', { exact: true }).fill('e2e@example.com');
  await page.getByLabel('Password', { exact: true }).fill('test-only-browser-password-42');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('button', { name: 'Data & scheduler', exact: true }).click();
  const errorLog = page.getByRole('region', { name: 'Job error log' });
  await expect(
    errorLog.getByText('Verify the official endpoint and trading date, then rerun the job.'),
  ).toBeVisible();
  await errorLog.getByText('Technical details', { exact: true }).click();
  await expect(errorLog.getByText('Run ID: run-fixture', { exact: true })).toBeVisible();
  await expect(
    page.getByRole('heading', { name: 'Finish setup to start automatic updates' }),
  ).toBeVisible();
  await expect(page.getByText('23:00 daily IST', { exact: true })).toBeVisible();
  const prices = page
    .getByRole('article')
    .filter({ has: page.getByRole('heading', { name: 'Daily closing price sync', exact: true }) });
  await prices.getByRole('button', { name: 'Pause', exact: true }).click();
  await expect(prices.getByRole('button', { name: 'Run daily closing price sync' })).toBeDisabled();
  await prices.getByRole('button', { name: 'Resume', exact: true }).click();
  await expect(prices.getByRole('button', { name: 'Run daily closing price sync' })).toBeEnabled();
  await page.getByText('Provider setup and safety', { exact: true }).click();
  await expect(page.getByText('No automatic feed is configured.', { exact: false })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({
    path: testInfo.outputPath('market-admin.png'),
    fullPage: true,
    caret: 'initial',
  });
});
