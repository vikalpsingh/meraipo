import { test, expect } from './fixtures';

test('scheduler setup is protected, understandable and controllable', async ({
  page,
  request,
}, testInfo) => {
  expect((await request.get('/api/v1/admin/market')).status()).toBe(401);
  expect((await request.get('/api/cron/results')).status()).toBe(401);
  await page.goto('/meraadmin');
  await page.getByLabel('Email', { exact: true }).fill('e2e@example.com');
  await page.getByLabel('Password', { exact: true }).fill('test-only-browser-password-42');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('button', { name: 'Data & scheduler', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'Finish setup to start automatic updates' }),
  ).toBeVisible();
  await expect(page.getByText('07:00 daily IST', { exact: true })).toBeVisible();
  const prices = page
    .getByRole('article')
    .filter({ has: page.getByRole('heading', { name: 'Collect daily closes', exact: true }) });
  await prices.getByRole('button', { name: 'Pause', exact: true }).click();
  await expect(prices.getByRole('button', { name: 'Run collect daily closes' })).toBeDisabled();
  await prices.getByRole('button', { name: 'Resume', exact: true }).click();
  await expect(prices.getByRole('button', { name: 'Run collect daily closes' })).toBeEnabled();
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
