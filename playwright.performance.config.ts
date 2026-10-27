import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/performance',
  workers: 1,
  retries: 0,
  timeout: 90_000,
  outputDir: 'test-results/performance',
  reporter: [['list']],
  use: { baseURL: 'http://127.0.0.1:5175', headless: true },
  webServer: [
    { command: 'services/api/.venv/bin/uvicorn tests.browser_server:app --app-dir services/api --host 127.0.0.1 --port 18002 --no-access-log', url: 'http://127.0.0.1:18002/api/v1/ready', reuseExistingServer: false, timeout: 20_000, gracefulShutdown: { signal: 'SIGTERM', timeout: 15_000 } },
    { command: 'pnpm --filter @frontier/web preview --port 5175 --strictPort', url: 'http://127.0.0.1:5175', env: { FRONTIER_API_PROXY: 'http://127.0.0.1:18002' }, reuseExistingServer: false, timeout: 15_000 },
  ],
});
