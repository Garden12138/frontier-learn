import { defineConfig } from '@playwright/test';

// Setup smoke coverage only. Story E2E-001–022 remain tracked by T057–T059.
export default defineConfig({
  testDir: './tests/setup',
  workers: 1,
  outputDir: 'test-results/setup',
  retries: 0,
  timeout: 30_000,
  reporter: [['list'], ['html', { outputFolder: 'playwright-report/setup', open: 'never' }]],
  use: { baseURL: 'http://127.0.0.1:5174', trace: 'retain-on-failure' },
  webServer: [
    {
      command: 'services/api/.venv/bin/uvicorn app.main:app --app-dir services/api --host 127.0.0.1 --port 18001 --no-access-log',
      url: 'http://127.0.0.1:18001/api/v1/health',
      env: { FRONTIER_ENV: 'test' },
      reuseExistingServer: false,
      timeout: 15_000,
    },
    {
      command: 'pnpm --filter @frontier/web dev --port 5174',
      url: 'http://127.0.0.1:5174',
      env: { FRONTIER_API_PROXY: 'http://127.0.0.1:18001' },
      reuseExistingServer: false,
      timeout: 15_000,
    },
  ],
});
