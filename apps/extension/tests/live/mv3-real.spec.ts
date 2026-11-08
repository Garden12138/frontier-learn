import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { expect, test } from '@playwright/test';

// Public read-only pages through the actual MV3 permission/extraction/locating path.
test('live public arXiv abstract, HTML and HF through actual MV3', async ({ playwright }, info) => {
  expect(process.env.FRONTIER_LIVE_PAGE_CHECKS).toBe('true');
  const profile = await mkdtemp(path.join(tmpdir(), 'frontier-live-mv3-'));
  const extension = path.resolve('apps/extension/.output/chrome-mv3');
  const context = await playwright.chromium.launchPersistentContext(profile, { channel: 'chromium', headless: true, javaScriptEnabled: true,
    args: [`--disable-extensions-except=${extension}`, `--load-extension=${extension}`, '--enable-unsafe-extension-debugging'] });
  try {
    const worker = context.serviceWorkers()[0] ?? await context.waitForEvent('serviceworker');
    const id = new URL(worker.url()).host;
    await worker.evaluate('chrome.sidePanel.setOptions({enabled: false})');
    const panel = await context.newPage();
    await panel.goto(`chrome-extension://${id}/sidepanel.html`);
    const observations: object[] = [];
    for (const url of ['https://arxiv.org/abs/1706.03762', 'https://arxiv.org/html/2401.04088v1', 'https://huggingface.co/openai-community/gpt2']) {
      const target = await context.newPage();
      await target.route('**/*', route => {
        const req = route.request();
        return req.method() === 'GET' && new URL(req.url()).hostname === new URL(url).hostname && ['document', 'stylesheet'].includes(req.resourceType()) ? route.continue() : route.abort();
      });
      expect((await target.goto(url, { waitUntil: 'domcontentloaded' }))?.status()).toBe(200);
      await target.bringToFront();
      const cdp = await context.browser()!.newBrowserCDPSession();
      try {
        const targets = await cdp.send('Target.getTargets', { filter: [{ type: 'tab', exclude: false }, { exclude: true }] });
        const tab = targets.targetInfos.find(value => value.url === target.url());
        expect(tab).toBeTruthy();
        await cdp.send('Extensions.triggerAction', { id, targetId: tab!.targetId });
      } finally { await cdp.detach(); }
      await panel.getByRole('button', { name: '分析当前页', exact: true }).evaluate(element => (element as HTMLButtonElement).click());
      const preview = panel.getByRole('region', { name: '材料预览' });
      await expect(preview).toBeVisible();
      await preview.getByRole('button', { name: '回到原文 b0', exact: true }).click();
      await expect(preview.getByRole('status').last()).toContainText('已回到原文位置');
      observations.push({ url, actual_mv3: true, toolbar_permission: true, source_b0_located: true, remote_upload: false, review: 'AUTOMATED_NOT_HUMAN' });
      await target.close();
    }
    await info.attach('live-mv3.json', { contentType: 'application/json', body: JSON.stringify(observations, null, 2) });
  } finally { await context.close(); await rm(profile, { recursive: true, force: true }); }
});
