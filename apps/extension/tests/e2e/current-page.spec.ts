import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { expect, test } from '@playwright/test';
import type { BrowserContext, Page } from '@playwright/test';
import fixtures from '../fixtures/pages.json' with { type: 'json' };

test('actual MV3 permission, ten pages, selection, changed locator and safe fallback', async ({ playwright }, testInfo) => {
  const extensionPath = path.resolve('apps/extension/.output/chrome-mv3');
  const profile = await mkdtemp(path.join(tmpdir(), 'frontier-guide-'));
  const context = await playwright.chromium.launchPersistentContext(profile, {
    channel: 'chromium', headless: true,
    args: [`--disable-extensions-except=${extensionPath}`, `--load-extension=${extensionPath}`, '--enable-unsafe-extension-debugging'],
  });
  try {
    const worker = context.serviceWorkers()[0] ?? await context.waitForEvent('serviceworker');
    const extensionId = new URL(worker.url()).host;
    // The same panel document is driven as a tab; avoid a duplicate native side panel.
    await worker.evaluate('chrome.sidePanel.setOptions({enabled: false})');
    const panel = await context.newPage();
    const errors: string[] = [];
    panel.on('pageerror', error => errors.push(error.message));
    await panel.goto(`chrome-extension://${extensionId}/sidepanel.html`);
    const target = await context.newPage();

    for (const fixture of fixtures) {
      await target.route(fixture.url, route => route.fulfill({ contentType: 'text/html', body: fixture.html }));
    }
    const first = fixtures[0]!;
    await target.goto(first.url);
    await target.bringToFront();
    // Before a user action, activeTab has no authority to inspect this page.
    await target.bringToFront();
    await panel.getByRole('button', { name: '分析当前页', exact: true }).evaluate(element => (element as HTMLButtonElement).click());
    await expect(panel.getByRole('alert')).toBeVisible();
    for (const fixture of fixtures) {
      await target.goto(fixture.url);
      await target.bringToFront();
      // CDP simulates the toolbar's default action, including Chrome's real activeTab grant.
      await triggerToolbar(context, target, extensionId);
      await target.bringToFront();
    await panel.getByRole('button', { name: '分析当前页', exact: true }).evaluate(element => (element as HTMLButtonElement).click());
      const preview = panel.getByRole('region', { name: '材料预览' });
      await expect(preview).toContainText(fixture.quote);
      await expect(preview).not.toContainText('SECRET');
      await expect(preview).not.toContainText('FORM_VALUE');
      await preview.getByRole('button', { name: '回到原文 b0', exact: true }).click();
      await expect(preview.getByRole('status').last()).toContainText('已回到原文位置');
    }
    const last = fixtures.at(-1)!;
    await target.locator('[data-testid="model-card"] p').first().evaluate(element => {
      const range = document.createRange(); range.selectNodeContents(element);
      getSelection()!.removeAllRanges(); getSelection()!.addRange(range);
    });
    await target.bringToFront();
    await panel.getByRole('button', { name: '分析当前页', exact: true }).evaluate(element => (element as HTMLButtonElement).click());
    await expect(panel.getByRole('blockquote')).toContainText(last.quote);
    await panel.getByLabel('阅读层级').selectOption('PRACTICE');
    await expect(panel.getByRole('region', { name: '材料预览' })).toContainText('不自动运行代码');
    await panel.screenshot({ path: testInfo.outputPath('guided-preview.png'), fullPage: true });
    await target.locator('[data-testid="model-card"]').evaluate(element => { element.textContent = 'Page content changed'; });
    await panel.getByRole('button', { name: '回到原文 b0', exact: true }).click();
    await expect(panel.getByRole('status').last()).toContainText('无法精确定位');
    await target.route('https://example.test/unsupported', route => route.fulfill({ body: '<p>Unrelated private page.</p>', contentType: 'text/html' }));
    await target.goto('https://example.test/unsupported');
    await target.bringToFront();
    await panel.getByRole('button', { name: '分析当前页', exact: true }).evaluate(element => (element as HTMLButtonElement).click());
    await expect(panel.getByRole('alert')).toBeVisible();
    await expect(panel.getByRole('region', { name: '材料预览' })).toHaveCount(0);
    await panel.getByText('使用手工粘贴文本', { exact: true }).click();
    await panel.getByLabel('学习材料', { exact: true }).fill('这是一段手工粘贴的合成学习材料。应先解释其中的主张，再查找来源并检查适用限制；阅读本身不证明已经掌握。');
    await panel.getByRole('button', { name: '预览粘贴材料' }).click();
    await expect(panel.getByRole('region', { name: '材料预览' })).toContainText('来源未经核验');
    expect(errors).toEqual([]);
    await panel.screenshot({ path: testInfo.outputPath('manual-fallback.png'), fullPage: true });
  } finally { await context.close(); await rm(profile, { recursive: true, force: true }); }
});

test('saved guide follows the same account across extension and Web, refresh and logout', async ({ playwright, request }, testInfo) => {
  test.setTimeout(30_000);
  const identity = `reader-${crypto.randomUUID()}`;
  const login = await request.post('http://127.0.0.1:18002/api/v1/auth/mock-login', { data: { identity, client: 'extension' } });
  expect(login.ok()).toBeTruthy();
  const headers = { Authorization: `Bearer ${(await login.json()).access_token as string}`, 'Idempotency-Key': crypto.randomUUID() };
  const goalReply = await request.post('http://127.0.0.1:18002/api/v1/goals', { headers, data: { title: '理解 Attention', minutes_per_day: 30 } });
  const goal = await goalReply.json() as { id: string; version: number };
  const planReply = await request.post('http://127.0.0.1:18002/api/v1/plans:generate', { headers, data: { goal_id: goal.id, goal_version: goal.version, expected_revision_no: 0 } });
  const plan = await planReply.json() as { tasks: { id: string; title: string }[] };
  expect(planReply.ok()).toBeTruthy();
  const profile = await mkdtemp(path.join(tmpdir(), 'frontier-handoff-'));
  const extensionPath = path.resolve('apps/extension/.output/chrome-mv3');
  const context = await playwright.chromium.launchPersistentContext(profile, {
    channel: 'chromium', headless: true,
    args: [`--disable-extensions-except=${extensionPath}`, `--load-extension=${extensionPath}`, '--enable-unsafe-extension-debugging'],
  });
  try {
    const worker = context.serviceWorkers()[0] ?? await context.waitForEvent('serviceworker');
    const extensionId = new URL(worker.url()).host;
    // The same panel document is driven as a tab; avoid a duplicate native side panel.
    await worker.evaluate('chrome.sidePanel.setOptions({enabled: false})');
    const panel = await context.newPage();
    const errors: string[] = [];
    panel.on('pageerror', value => errors.push(value.message));
    await panel.goto(`chrome-extension://${extensionId}/sidepanel.html`);
    await panel.getByLabel('开发体验账号').fill(identity);
    await panel.getByRole('button', { name: '连接体验账号', exact: true }).click();
    await expect(panel.getByText(`当前账号：${identity}`)).toBeVisible();
    const target = await context.newPage();
    const fixture = fixtures[0]!;
    await target.route(fixture.url, route => route.fulfill({ contentType: 'text/html', body: fixture.html }));
    await target.goto(fixture.url); await target.bringToFront();

    await triggerToolbar(context, target, extensionId);
    await target.bringToFront();
    await panel.getByRole('button', { name: '分析当前页', exact: true }).evaluate(element => (element as HTMLButtonElement).click());
    await expect(panel.getByRole('region', { name: '材料预览' })).toBeVisible();
    await expect(panel.getByRole('region', { name: '保存并开启导学' })).toBeVisible();
    await expect(panel.getByRole('combobox', { name: /^关联学习目标/ }).locator('option')).toHaveCount(2);
    await panel.getByRole('combobox', { name: /^关联学习目标/ }).selectOption(goal.id);
    await expect(panel.getByLabel('关联当前计划任务').locator('option')).toHaveCount(plan.tasks.length + 1);
    await panel.getByLabel('关联当前计划任务').selectOption(plan.tasks[0]!.id);
    const save = panel.getByRole('button', { name: '保存并开启导学', exact: true });
    await expect(save).toBeDisabled();
    await panel.getByRole('checkbox').check(); await save.click();
    const session = panel.getByRole('region', { name: '已保存导学会话' });
    await expect(session).toContainText('导学已保存');
    const assessment = session.getByRole('region', { name: '理解验证' });
    await assessment.getByRole('button', { name: '开始短测', exact: true }).click();
    await assessment.getByRole('radio', { name: /^B ·/ }).check();
    await assessment.getByRole('button', { name: '提交作答', exact: true }).click();
    await assessment.getByRole('button', { name: '确认评价并加入学习证据', exact: true }).click();
    await expect(assessment.getByRole('status')).toContainText('已确认低强度证据');
    await panel.screenshot({ path: testInfo.outputPath('extension-assessment.png'), fullPage: true });
    await expect(session).toContainText('理解 Attention');
    await expect(session).toContainText('与材料快照匹配');
    await session.getByRole('button', { name: '定位引用 b0' }).click();
    await expect(panel.getByText('已回到原文位置。', { exact: true })).toBeVisible();
    await session.getByLabel('追问层级').selectOption('DEEP');
    await session.getByLabel('继续提问').fill('这个主张有哪些前提需要核实？');
    await session.getByRole('button', { name: '保存追问', exact: true }).click();
    await expect(session.getByRole('status').filter({ hasText: '导学已保存' })).toHaveCount(2);
    await panel.screenshot({ path: testInfo.outputPath('saved-extension-session.png'), fullPage: true });
    const web = await context.newPage();
    await web.goto('http://127.0.0.1:5175');
    await web.getByLabel('开发体验账号').fill(identity);
    await web.getByRole('button', { name: '进入学习空间' }).click();
    await web.getByRole('button', { name: '导学会话', exact: true }).click();
    await web.getByRole('button', { name: /Synthetic A/ }).click();
    await expect(web.getByRole('heading', { name: '当前学习任务' })).toBeVisible();
    await expect(web.getByText('关联任务不在当前计划中，历史关联仍保留；不会自动完成当前任务。', { exact: true })).toBeVisible();
    const shared = web.getByRole('region', { name: '已保存导学会话' });
    await expect(shared).toContainText('已确认低强度证据');
    await expect(shared).toContainText('这个主张有哪些前提需要核实？');
    await shared.getByLabel('追问层级').selectOption('PRACTICE');
    await shared.getByLabel('继续提问').fill('如何设计一个检查理解的小实验？');
    await shared.getByRole('button', { name: '保存追问', exact: true }).click();
    await expect(shared.getByRole('status').filter({ hasText: '导学已保存' })).toHaveCount(3);
    await web.screenshot({ path: testInfo.outputPath('shared-web-session.png'), fullPage: true });
    await panel.reload();
    await expect(panel.getByText(`当前账号：${identity}`)).toBeVisible();
    await panel.getByText('继续已保存的会话', { exact: true }).click();
    await panel.getByRole('button', { name: 'Synthetic A', exact: true }).click();
    await expect(panel.getByRole('region', { name: '已保存导学会话' })).toContainText('如何设计一个检查理解的小实验？');
    // Inspect only a boolean: session credentials must never be copied to test output or DOM.
    expect(await panel.evaluate('(async () => { const {auth} = await chrome.storage.session.get("auth"); return !!auth && !document.documentElement.outerHTML.includes(auth.token); })()')).toBe(true);
    await panel.getByRole('button', { name: '插件退出登录' }).click();
    await expect(panel.getByRole('region', { name: '已保存导学会话' })).toHaveCount(0);
    await expect(panel.getByLabel('开发体验账号')).toBeVisible();
    await panel.getByLabel('开发体验账号').fill(identity);
    await panel.getByRole('button', { name: '连接体验账号', exact: true }).click();
    await expect(panel.getByText(`当前账号：${identity}`)).toBeVisible();
    // Revoke on the server without returning the session token to the test process.
    expect(await worker.evaluate('(async () => { const {auth} = await chrome.storage.session.get("auth"); const response = await fetch("http://127.0.0.1:18002/api/v1/auth/logout", {method: "POST", headers: {Authorization: "Bearer " + auth.token}}); return response.status === 204; })()')).toBe(true);
    await panel.getByText('继续已保存的会话', { exact: true }).click();
    await panel.getByRole('button', { name: '刷新历史', exact: true }).click();
    await expect(panel.getByLabel('开发体验账号')).toBeVisible();
    await expect(panel.getByRole('region', { name: '已保存导学会话' })).toHaveCount(0);
    expect(errors).toEqual([]);
  } finally { await context.close(); await rm(profile, { recursive: true, force: true }); }
});

async function triggerToolbar(context: BrowserContext, page: Page, extensionId: string) {
  const devtools = await context.browser()!.newBrowserCDPSession();
  try {
    // Chromium's extension command requires the parent tab target, not its page target.
    const targets = await devtools.send('Target.getTargets', { filter: [{ type: 'tab', exclude: false }, { exclude: true }] });
    const tab = targets.targetInfos.find(info => info.url === page.url());
    expect(tab, 'A browser tab target must exist for the current source').toBeTruthy();
    await devtools.send('Extensions.triggerAction', { id: extensionId, targetId: tab!.targetId });
  } finally { await devtools.detach(); }
}

test('actual MV3 signs in using an independent password account', async ({ playwright, request }) => {
  const identity = `ext-real-${crypto.randomUUID()}`;
  const password = 'synthetic extension password 12345';
  const registered = await request.post('http://127.0.0.1:18002/api/v1/auth/register', { data: { identity, password, client: 'extension' } });
  expect(registered.status()).toBe(201);
  const extensionPath = path.resolve('apps/extension/.output/chrome-mv3');
  const profile = await mkdtemp(path.join(tmpdir(), 'frontier-real-auth-'));
  const context = await playwright.chromium.launchPersistentContext(profile, { channel: 'chromium', headless: true,
    args: [`--disable-extensions-except=${extensionPath}`, `--load-extension=${extensionPath}`] });
  try {
    const worker = context.serviceWorkers()[0] ?? await context.waitForEvent('serviceworker');
    const panel = await context.newPage();
    await panel.goto(`chrome-extension://${new URL(worker.url()).host}/sidepanel.html`);
    const account = panel.getByRole('region', { name: '账号登录' });
    await account.getByLabel('用户名', { exact: true }).fill(identity);
    await account.getByLabel('密码', { exact: true }).fill(password);
    await account.getByRole('button', { name: '登录学习空间', exact: true }).click();
    await expect(panel.getByText(`当前账号：${identity}`, { exact: true })).toBeVisible();
    expect(await panel.evaluate('(async () => { const {auth} = await chrome.storage.session.get("auth"); return !!auth && !document.documentElement.outerHTML.includes(auth.token); })()')).toBe(true);
    await panel.getByRole('button', { name: '插件退出登录', exact: true }).click();
    await expect(panel.getByRole('region', { name: '账号登录' })).toBeVisible();
  } finally { await context.close(); await rm(profile, { recursive: true, force: true }); }
});
