import { defineConfig } from '@playwright/test';
import sources from './playwright.sources.config';

export default defineConfig({
  testDir: './apps/extension/tests/e2e', workers: 1, retries: 0, timeout: 60_000,
  outputDir: 'test-results/extension',
  reporter: [['list'], ['html', { outputFolder: 'playwright-report/extension', open: 'never' }]],
  use: { trace: 'retain-on-failure' },
  webServer: [
    { command: 'pnpm --filter @frontier/extension build && services/api/.venv/bin/uvicorn tests.browser_server:app --app-dir services/api --host 127.0.0.1 --port 18002 --no-access-log', env: { FRONTIER_EXTENSION_API_ORIGIN: 'http://127.0.0.1:18002' }, url: 'http://127.0.0.1:18002/api/v1/ready', reuseExistingServer: false, timeout: 30_000, gracefulShutdown: { signal: 'SIGTERM', timeout: 15_000 } },
    ...(Array.isArray(sources.webServer) ? sources.webServer.slice(1) : []),
  ],
});
