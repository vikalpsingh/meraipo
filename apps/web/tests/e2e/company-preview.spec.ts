import { test, expect } from './fixtures';

test('company popup has subscription percentages, history and keyboard close', async ({
  page,
  request,
}, testInfo) => {
  const response = await request.get('/api/v1/ipos/open');
  const company = (await response.json()).items.find(
    (c: { subscription?: { multiple: number } }) => c.subscription?.multiple === 3.75,
  );
  await page.goto('/');
  const trigger = page.getByRole('button', { name: company.name, exact: true });
  await trigger.click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('heading', { name: 'Who is subscribing?' })).toBeVisible();
  await expect(
    dialog
      .getByRole('region', { name: 'Subscription categories' })
      .getByText('250%', { exact: true }),
  ).toBeVisible();
  await expect(
    dialog
      .getByRole('region', { name: 'Subscription categories' })
      .getByText('375%', { exact: true }),
  ).toBeVisible();
  await dialog.getByText('Daily subscription history', { exact: true }).click();
  await expect(dialog.getByRole('region', { name: 'Daily subscription history' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('company-popup.png'), caret: 'initial' });
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await expect(trigger).toBeFocused();
  await trigger.click();
  await dialog.getByRole('link', { name: 'View company journey' }).click();
  await expect(page).toHaveURL(/\/ipo\//);
});

test('popup handles failed detail request and recovers on retry', async ({ page, request }) => {
  await page.route('**/api/v1/companies/*/journey', (route) =>
    route.fulfill({ status: 503, body: '{}' }),
  );
  const response = await request.get('/api/v1/ipos/open');
  const company = (await response.json()).items.find(
    (c: { subscription?: { multiple: number } }) => c.subscription?.multiple === 3.75,
  );
  await page.goto('/');
  await page.getByRole('button', { name: company.name, exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('alert')).toContainText('temporarily unavailable');
  await page.unroute('**/api/v1/companies/*/journey');
  await dialog.getByRole('button', { name: 'Retry' }).click();
  await expect(dialog.getByText('Daily subscription history', { exact: true })).toBeVisible();
  await expect(dialog.getByRole('alert')).toHaveCount(0);
  await dialog.getByRole('button', { name: 'Close company details' }).click();
  await expect(dialog).not.toBeVisible();
});
