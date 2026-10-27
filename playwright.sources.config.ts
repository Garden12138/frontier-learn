import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './apps/web/tests/e2e',
  testMatch: ['sources.spec.ts', 'planning.spec.ts', 'conversation.spec.ts', 'learning-loop.spec.ts', 'real-connections.spec.ts'],
  workers: 1,
  outputDir: 'test-results/sources',
  retries: 0,
  timeout: 30_000,
  reporter: [['list'], ['html', { outputFolder: 'playwright-report/sources', open: 'never' }]],
  use: { baseURL: 'http://127.0.0.1:5175', trace: 'retain-on-failure' },
  webServer: [
    { command: 'services/api/.venv/bin/uvicorn tests.browser_server:app --app-dir services/api --host 127.0.0.1 --port 18002 --no-access-log', url: 'http://127.0.0.1:18002/api/v1/ready', reuseExistingServer: false, timeout: 20_000, gracefulShutdown: { signal: 'SIGTERM', timeout: 15_000 } },
    { command: 'pnpm --filter @frontier/web dev --port 5175', url: 'http://127.0.0.1:5175', env: { FRONTIER_API_PROXY: 'http://127.0.0.1:18002' }, reuseExistingServer: false, timeout: 15_000 },
  ],
});
