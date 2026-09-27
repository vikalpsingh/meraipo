import { test, expect } from '@playwright/test';

test('admin can hide and release the tracker', async ({ page }) => {
  await page.goto('/meraadmin');
  await page.getByLabel('Email', { exact: true }).fill('e2e@example.com');
  await page.getByLabel('Password', { exact: true }).fill('test-only-browser-password-42');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('button', { name: 'Feature releases', exact: true }).click();
  const toggle = page.getByRole('switch', { name: 'IPO Tracker' });
  await expect(toggle).toHaveAttribute('aria-checked', 'true');
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-checked', 'false');
  await expect(
    page
      .getByRole('navigation', { name: 'Main navigation' })
      .getByRole('link', { name: 'IPO Tracker' }),
  ).toHaveCount(0);
  expect((await page.request.get('/api/v1/tracker')).status()).toBe(404);
  await page.goto('/tracker');
  await expect(page.getByText('Company or page not found.', { exact: true })).toBeVisible();
  await page.goto('/');
  await expect(page.getByRole('link', { name: /Track listed companies/ })).toHaveCount(0);
  await page.goto('/meraadmin');
  await page.getByRole('button', { name: 'Feature releases', exact: true }).click();
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-checked', 'true');
  expect((await page.request.get('/api/v1/tracker')).status()).toBe(200);
  await page.goto('/');
  await expect(page.getByRole('link', { name: /Track listed companies/ })).toBeVisible();
});
