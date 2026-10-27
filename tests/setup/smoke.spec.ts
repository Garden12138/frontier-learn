import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { expect, test } from '@playwright/test';

test('workspace loads and connects to the running API', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByRole('status')).toContainText('学习服务已连接');
  await expect(page.getByRole('heading', { name: '先连接你的学习空间' })).toBeVisible();
  expect(errors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath('workspace.png'), fullPage: true });
});

test('workspace can recover when the API becomes available', async ({ page }) => {
  await page.route('**/api/v1/health', route => route.abort());
  await page.goto('/');
  await expect(page.getByRole('alert')).toContainText('请启动 API 后重试');
  await page.unroute('**/api/v1/health');
  await page.getByRole('button', { name: '重新检查连接' }).click();
  await expect(page.getByRole('status')).toContainText('学习服务已连接');
});

test('built MV3 extension runs its service worker and side panel', async ({ playwright }, testInfo) => {
  const extensionPath = path.resolve('apps/extension/.output/chrome-mv3');
  const profile = await mkdtemp(path.join(tmpdir(), 'frontier-setup-'));
  const context = await playwright.chromium.launchPersistentContext(profile, {
    channel: 'chromium',
    headless: true,
    args: [`--disable-extensions-except=${extensionPath}`, `--load-extension=${extensionPath}`],
  });
  try {
    const worker = context.serviceWorkers()[0] ?? await context.waitForEvent('serviceworker');
    const extensionId = new URL(worker.url()).host;
    const page = await context.newPage();
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`chrome-extension://${extensionId}/sidepanel.html`);
    await expect(page.getByRole('heading', { name: '尚未开始导学' })).toBeVisible();
    expect(errors).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath('extension.png'), fullPage: true });
  } finally {
    await context.close();
    await rm(profile, { recursive: true, force: true });
  }
});
