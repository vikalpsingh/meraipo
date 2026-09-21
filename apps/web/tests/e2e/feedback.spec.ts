import { test, expect } from './fixtures';

test('visitor submits idea, admin publishes it, and visitor votes and undoes', async ({
  page,
}, testInfo) => {
  const title = `Compare IPOs ${testInfo.project.name}`;
  await page.goto('/');
  await page.getByRole('link', { name: 'Share feedback', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Top five requested features' })).toBeVisible();
  await page.getByLabel('Short title', { exact: true }).fill(title);
  await page
    .getByLabel('Tell us more', { exact: true })
    .fill('Please compare issue prices and company fundamentals in one clear view.');
  await page.getByRole('button', { name: 'Send feedback', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Your feedback is saved for review');
  await expect(page.getByRole('heading', { name: title, exact: true })).toHaveCount(0);
  await page.goto('/meraadmin');
  await page.getByLabel('Email', { exact: true }).fill('e2e@example.com');
  await page.getByLabel('Password', { exact: true }).fill('test-only-browser-password-42');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('button', { name: 'Customer feedback', exact: true }).click();
  const idea = page
    .getByRole('article')
    .filter({ has: page.getByRole('heading', { name: title, exact: true }) });
  await idea.getByRole('combobox').selectOption('OPEN');
  await idea.getByRole('button', { name: 'Save review', exact: true }).click();
  await expect(
    page.getByText('Feedback review saved. The public board is updated.', { exact: true }),
  ).toBeVisible();
  await page.goto('/feedback');
  await page.getByRole('button', { name: `Vote for ${title}`, exact: true }).click();
  const item = page
    .getByRole('listitem')
    .filter({ has: page.getByRole('heading', { name: title, exact: true }) });
  await expect(item.getByText('1 vote', { exact: true })).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole('button', { name: `Remove vote for ${title}`, exact: true }),
  ).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: `Remove vote for ${title}`, exact: true }).click();
  await expect(item.getByText('0 votes', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('feedback-board.png'), fullPage: true });
});

test('failed feedback submission retains input and can be retried', async ({ page }, testInfo) => {
  await page.goto('/feedback');
  await page.getByLabel('Feedback type').selectOption('FEEDBACK');
  const title = `Navigation feedback ${testInfo.project.name}`;
  await page.getByLabel('Short title', { exact: true }).fill(title);
  await page
    .getByLabel('Tell us more', { exact: true })
    .fill('The company popup is useful; please keep the navigation simple.');
  await page.route('**/api/v1/feedback', (route) =>
    route.request().method() === 'POST'
      ? route.fulfill({
          status: 503,
          json: { error: { message: 'Temporarily unavailable. Please retry.' } },
        })
      : route.continue(),
  );
  await page.getByRole('button', { name: 'Send feedback', exact: true }).click();
  await expect(page.getByRole('main').getByRole('alert')).toContainText('Temporarily unavailable');
  await expect(page.getByLabel('Short title', { exact: true })).toHaveValue(title);
  await page.unroute('**/api/v1/feedback');
  await page.getByRole('button', { name: 'Send feedback', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Your feedback is saved for review');
});
