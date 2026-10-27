import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './apps/extension/tests/live',
  workers: 1,
  retries: 0,
  timeout: 25_000,
  outputDir: 'test-results/live-pages',
  reporter: [['list'], ['json', { outputFile: 'test-results/live-pages/report.json' }]],
  use: { headless: true, javaScriptEnabled: false, navigationTimeout: 15_000, actionTimeout: 3_000 },
});
