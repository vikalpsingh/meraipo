import { defineConfig, devices } from '@playwright/test';
import path from 'node:path';
const root = path.resolve(import.meta.dirname, '../..');
const python =
  process.env.E2E_PYTHON ||
  (process.platform === 'win32' ? path.join(root, '.venv/Scripts/python.exe') : 'python');
export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  forbidOnly: !!process.env.CI,
  timeout: 60000,
  expect: { timeout: 10000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:3001',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
  webServer: [
    {
      command: `"${python}" "${path.join(root, 'tests/e2e_server.py')}"`,
      url: 'http://127.0.0.1:8001/health/live',
      reuseExistingServer: false,
      timeout: 120000,
    },
    {
      command: 'node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 3001',
      url: 'http://127.0.0.1:3001',
      reuseExistingServer: false,
      timeout: 120000,
      env: {
        API_INTERNAL_URL: 'http://127.0.0.1:8001',
        NEXT_PUBLIC_DEMO_MODE: 'true',
        SITE_URL: 'http://127.0.0.1:3001',
        NEXT_TELEMETRY_DISABLED: '1',
      },
    },
  ],
});
