import { test, expect } from './fixtures';
test('home is clear, missing GMP stays missing, navigation is small', async ({
  page,
}, testInfo) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'IPOs at a glance.' })).toBeVisible();
  await expect(
    page.locator('#upcoming').getByText('GMP unavailable').filter({ visible: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link'),
  ).toHaveCount(3);
  await expect(
    page.getByRole('navigation', { name: 'Main navigation' }).getByText('Admin'),
  ).toHaveCount(0);
  await expect(
    page.getByText(
      'Unofficial grey-market information. GMP does not guarantee listing price or investment return.',
    ),
  ).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({
    path: testInfo.outputPath('home.png'),
    fullPage: true,
    caret: 'initial',
  });
  await page.goto('/ipos');
  await expect(page.getByRole('heading', { name: 'IPOs at a glance.' })).toBeVisible();
});
test('tracker filters and company journey work', async ({ page }, testInfo) => {
  await page.goto('/tracker?fy=&quarter=');
  // Ten original listed fixtures plus two companies imported through the market pipeline.
  await expect(page.getByTestId('company-row')).toHaveCount(12);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({
    path: testInfo.outputPath('tracker.png'),
    fullPage: true,
    caret: 'initial',
  });
  await page.getByLabel('Board', { exact: true }).selectOption('SME');
  await page.getByRole('button', { name: 'Apply filters' }).click();
  await expect(page.getByTestId('company-row')).toHaveCount(2);
  await page.goto('/ipo/prava-technologies');
  await expect(page.getByRole('heading', { name: 'Prava Technologies.' })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'IPO baseline' })).toBeVisible();
  await page.getByRole('link', { name: 'FY2025', exact: true }).click();
  await expect(
    page.getByRole('columnheader', { name: 'Q1 FY25 Standalone', exact: true }),
  ).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});
test('empty screens and unknown companies are honest', async ({ page }) => {
  await page.goto('/tracker?fy=2099&quarter=');
  await expect(
    page.getByRole('heading', { name: 'No companies match these filters.' }),
  ).toBeVisible();
  await page.goto('/ipo/does-not-exist');
  await expect(page.getByRole('heading', { name: 'Company or page not found.' })).toBeVisible();
});
test('admin publishes, edits and disables a quote; logout protects writes', async ({
  page,
  request,
}, testInfo) => {
  await page.goto('/meraadmin');
  await page.getByLabel('Email', { exact: true }).fill('e2e@example.com');
  await page.getByLabel('Password', { exact: true }).fill('test-only-browser-password-42');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('button', { name: 'Messages & quotes', exact: true }).click();
  const title = 'A patient thought ' + testInfo.project.name;
  await page.getByLabel('Title', { exact: true }).fill(title);
  await page.getByLabel('Attribution', { exact: true }).fill('MeraIPO editorial');
  await page
    .getByLabel('Content', { exact: true })
    .fill('Read the business before reading the price.');
  await page.getByRole('button', { name: 'Save message', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Saved successfully.');
  await page.goto('/');
  await expect(page.getByLabel('Investing thought')).toContainText(
    'Read the business before reading the price.',
  );
  await page.goto('/meraadmin');
  await page.getByRole('button', { name: 'Messages & quotes', exact: true }).click();
  await page.getByRole('button', { name: 'Edit ' + title, exact: true }).click();
  await page.getByLabel('Enabled', { exact: true }).uncheck();
  await page.getByRole('button', { name: 'Save message', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Saved successfully.');
  await page.goto('/');
  await expect(
    page.getByText('Read the business before reading the price.', { exact: false }),
  ).toHaveCount(0);
  await page.goto('/meraadmin');
  await page.getByRole('button', { name: 'Log out', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
  expect(
    (
      await request.post('/api/v1/admin/messages', {
        data: { title: 'unauthorized', content: 'no' },
      })
    ).status(),
  ).toBe(401);
});
test('SEO and trust routes exist', async ({ page, request }) => {
  await page.goto('/methodology');
  await expect(page.getByRole('heading', { name: 'A method you can inspect.' })).toBeVisible();
  expect((await request.get('/robots.txt')).status()).toBe(200);
  const sitemap = await request.get('/sitemap.xml');
  expect(sitemap.status()).toBe(200);
  expect(await sitemap.text()).toContain('/ipo/prava-technologies');
});

test('admin publishes an applicant guide and a visitor calculates, checks and downloads dates', async ({
  page,
}, testInfo) => {
  await page.goto('/meraadmin');
  await page.getByLabel('Email', { exact: true }).fill('e2e@example.com');
  await page.getByLabel('Password', { exact: true }).fill('test-only-browser-password-42');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Applicant guides', exact: true })).toBeVisible();
  const auth = await (await page.request.get('/api/v1/admin/session')).json();
  const slug = 'applicant-test-' + testInfo.project.name;
  const day = (n: number) => new Date(Date.now() + n * 86400000).toISOString().slice(0, 10);
  const created = await page.request.post('/api/v1/admin/ipos', {
    headers: { origin: 'http://127.0.0.1:3001', 'x-csrf-token': auth.csrf_token },
    data: {
      slug,
      name: 'Applicant Test ' + testInfo.project.name,
      sector: 'Manufacturing',
      status: 'OPEN',
      price_low: 140,
      price_high: 150,
      lot_size: 50,
      open_date: day(0),
      close_date: day(3),
      listing_date: day(8),
      source_url: 'https://example.com/rhp',
    },
  });
  expect(created.status()).toBe(201);
  await page.reload();
  await page.getByRole('button', { name: 'Applicant guides', exact: true }).click();
  await page.getByLabel('Choose IPO', { exact: true }).selectOption(slug);
  await page.getByLabel('Applicant category', { exact: true }).fill('Retail individual');
  await page.getByLabel('Minimum lots', { exact: true }).fill('1');
  await page.getByLabel('Category amount limit (₹, optional)', { exact: true }).fill('200000');
  await page.getByLabel('Expected allotment date', { exact: true }).fill(day(6));
  await page.getByLabel('Unblocking initiation date', { exact: true }).fill(day(7));
  await page.getByLabel('Bidding deadline (IST)', { exact: true }).fill(day(3) + 'T16:00');
  await page.getByLabel('UPI mandate deadline (IST)', { exact: true }).fill(day(3) + 'T17:00');
  await page.getByLabel('Official registrar name', { exact: true }).fill('Test Registrar');
  await page
    .getByLabel('Official registrar allotment URL', { exact: true })
    .fill('https://example.com/allotment');
  await page.getByLabel('Guide source URL', { exact: true }).fill('https://example.com/rhp');
  await page.getByLabel('Guide verification', { exact: true }).selectOption('VERIFIED');
  await page
    .getByLabel('What the company does (plain language)', { exact: true })
    .fill('Makes precision components for industrial customers.');
  await page
    .getByLabel('Three strengths (one per line)', { exact: true })
    .fill('Recurring demand\nExperienced management\nDistribution network');
  await page
    .getByLabel('Three risks (one per line)', { exact: true })
    .fill('Customer concentration\nInput costs\nExpansion execution');
  await page
    .getByLabel('How the IPO proceeds will be used', { exact: true })
    .fill('Factory expansion and working capital.');
  await page.getByRole('button', { name: 'Save applicant guide', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Saved successfully.');
  await page.goto('/ipo/' + slug);
  await expect(
    page.getByText('Makes precision components for industrial customers.'),
  ).toBeVisible();
  await page.getByRole('link', { name: '2 · Prepare to apply', exact: true }).click();
  await page.getByLabel('Number of lots', { exact: true }).fill('2');
  await expect(page.getByText('₹15,000', { exact: true })).toBeVisible();
  await page.getByLabel('Number of lots', { exact: true }).fill('100');
  await expect(page.getByText(/This exceeds the published limit/)).toBeVisible();
  await page.getByLabel('Number of lots', { exact: true }).fill('2');
  await page.getByText('Before you finish applying', { exact: false }).click();
  await page.getByRole('checkbox').first().check();
  await expect(page.getByText('1/5', { exact: true })).toBeVisible();
  await page.getByRole('link', { name: '3 · Track dates', exact: true }).click();
  await expect(
    page.getByRole('link', { name: 'Check allotment with Test Registrar ↗' }),
  ).toHaveAttribute('href', 'https://example.com/allotment');
  const download = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Add dates to calendar ↓' }).click();
  expect((await download).suggestedFilename()).toBe(slug + '-ipo.ics');
  const calendar = await page.request.get('/ipo/' + slug + '/calendar');
  expect(calendar.headers()['content-type']).toContain('text/calendar');
  expect(await calendar.text()).toContain('T113000Z');
  expect(await calendar.text()).toContain('BEGIN:VALARM');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath('applicant-guide.png'),
    fullPage: true,
    caret: 'initial',
  });
});

test('unreviewed SME guide remains honest and accessible', async ({ page, request }) => {
  await page.goto('/ipo/cedar-foods');
  await expect(
    page.getByText('Application rules are awaiting review.', { exact: false }),
  ).toBeVisible();
  await expect(page.getByRole('link', { name: /Check allotment with/ })).toHaveCount(0);
  await expect(page.getByText('The company in 60 seconds', { exact: true })).toBeVisible();
  expect((await request.get('/ipo/unknown-ipo/calendar')).status()).toBe(404);
});

test('visitors find companies, recover from empty search and follow section links', async ({
  page,
}, testInfo) => {
  await page.goto('/');
  await expect(
    page
      .getByRole('navigation', { name: 'Main navigation' })
      .getByRole('link', { name: 'Home', exact: true }),
  ).toHaveAttribute('aria-current', 'page');
  await page.getByLabel('Find an IPO or company').fill('Aarya');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('1 company matching');
  await expect(page.locator('.ipo-card')).toHaveCount(1);
  await page.getByRole('button', { name: 'Aarya Energy', exact: true }).click();
  await page.getByRole('dialog').getByRole('link', { name: 'View company journey' }).click();
  await page.getByRole('button', { name: 'Increase lots' }).click();
  await expect(page.getByLabel('Number of lots')).toHaveValue('2');
  await page.getByRole('link', { name: 'Financial history ↓', exact: true }).click();
  await expect(page.locator('#financials')).toHaveAttribute('open', '');
  await page.goto('/ipo/prava-technologies#track');
  await expect(page.getByRole('heading', { name: 'Dates that matter' })).toBeVisible();
  await expect(page.locator('#track')).toBeFocused();
  await page.goto('/?q=no-such-company');
  await expect(page.getByRole('heading', { name: 'No matching companies' })).toBeVisible();
  await page.getByRole('link', { name: 'Show all IPOs', exact: true }).click();
  await expect(page.getByLabel('Find an IPO or company')).toHaveValue('');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath('home-usability.png'),
    fullPage: true,
    caret: 'initial',
  });
});
