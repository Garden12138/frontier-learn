import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

const sample = `用户：BPE 的合并规则有什么适用条件？请给出可核实的依据。
助手：BPE merges frequent token pairs. This is an unverified answer.
<img src=x onerror="window.importScriptRan=true">
\`\`\`python
example = 'illustration only'
User: this is code text, not a new message
\`\`\`
用户：如何用一个反例检查刚才的解释？`;
const share = 'https://chatgpt.com/share/11111111-1111-4111-8111-111111111111';
const denied = 'https://chatgpt.com/share/22222222-2222-4222-8222-222222222222';
const unsupported = 'https://chatgpt.com/share/33333333-3333-4333-8333-333333333333';

async function login(page: Page, identity: string) {
  await page.goto('/');
  await page.getByLabel('开发体验账号').fill(identity);
  await page.getByRole('button', { name: '进入学习空间', exact: true }).click();
  await page.getByRole('button', { name: '导入对话', exact: true }).click();
}

async function confirm(page: Page) {
  await page.getByRole('button', { name: '预览导入范围', exact: true }).click();
  const preview = page.getByRole('region', { name: '提交前预览' });
  await expect(preview).toBeVisible();
  await expect(preview.getByRole('button', { name: '确认导入对话' })).toBeDisabled();
  await preview.getByRole('checkbox').check();
  await preview.getByRole('button', { name: '确认导入对话' }).click();
}

test('private pasted preview, related evidence, explicit candidate choice and deleted material history', async ({ page, request }, testInfo) => {
  const identity = `conversation-${crypto.randomUUID()}`;
  const auth = await request.post('http://127.0.0.1:18002/api/v1/auth/mock-login', { data: { identity, client: 'extension' } });
  const headers = { Authorization: `Bearer ${(await auth.json()).access_token as string}`, 'Idempotency-Key': crypto.randomUUID() };
  const goalReply = await request.post('http://127.0.0.1:18002/api/v1/goals', { headers, data: { title: '理解 BPE', minutes_per_day: 30 } });
  const goal = await goalReply.json() as { id: string; version: number };
  const planReply = await request.post('http://127.0.0.1:18002/api/v1/plans:generate', { headers, data: { goal_id: goal.id, goal_version: goal.version, expected_revision_no: 0 } });
  expect(planReply.ok()).toBeTruthy();
  const plan = await planReply.json() as { id: string };
  const sourceReply = await request.post('http://127.0.0.1:18002/api/v1/sources', { headers, data: { external_ref: 'sample/conversation-notes', consent: true } });
  const source = await sourceReply.json() as { id: string };
  const sync = await request.post(`http://127.0.0.1:18002/api/v1/sources/${source.id}/sync`, { headers });
  const syncJob = await sync.json() as { id: string };
  await expect.poll(async () => (await (await request.get(`http://127.0.0.1:18002/api/v1/jobs/${syncJob.id}`, { headers })).json() as { status: string }).status).toBe('SUCCEEDED');
  const before = await (await request.get('http://127.0.0.1:18002/api/v1/knowledge', { headers })).json() as unknown[];
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  let submitted = 0;
  page.on('request', event => { if (event.url().endsWith('/conversations:import')) submitted++; });
  await login(page, identity);
  await expect(page.getByRole('region', { name: '对话导入历史' })).toContainText('还没有导入材料');
  await page.getByLabel('对话文本', { exact: true }).fill(sample);
  await page.getByRole('button', { name: '预览导入范围' }).click();
  expect(submitted).toBe(0);
  await expect(page.getByRole('region', { name: '提交前预览' })).toContainText('<img src=x');
  await page.getByRole('region', { name: '提交前预览' }).getByRole('checkbox').check();
  await page.getByRole('button', { name: '确认导入对话' }).click();
  const detail = page.getByRole('region', { name: '对话材料详情' });
  await expect(detail.getByRole('status').first()).toHaveText('解析完成');
  await expect(detail).toContainText('代码文本 · 未执行');
  await expect(detail).toContainText('User: this is code text');
  expect(await page.evaluate(() => !('importScriptRan' in window))).toBe(true);
  await expect(detail.getByRole('heading', { name: /用户问题（材料标注）/ })).toHaveCount(2);
  const related = detail.getByRole('button', { name: /相关知识线索：BPE/ }).first();
  await related.click();
  await expect(page.getByRole('heading', { name: '我的知识画像' })).toBeVisible();
  await expect(page.getByLabel('搜索知识点')).toHaveValue('BPE');
  await page.getByRole('button', { name: '导入对话', exact: true }).click();
  await page.getByRole('region', { name: '对话导入历史' }).getByRole('button', { name: /手工导入对话/ }).click();
  await page.getByRole('combobox', { name: '加入哪个目标', exact: true }).selectOption(goal.id);
  await expect(detail).toContainText('目标计划当前版本 1');
  const candidates = detail.getByRole('article', { name: '候选问题' });
  await expect(candidates).toHaveCount(3);
  await candidates.nth(0).getByRole('button', { name: '确认加入计划' }).click();
  await expect(candidates.nth(0)).toContainText('已加入计划');
  await candidates.nth(1).getByRole('button', { name: '不加入这个问题' }).click();
  await expect(candidates.nth(1)).toContainText('已拒绝');
  const afterPlan = await (await request.get(`http://127.0.0.1:18002/api/v1/plans/${plan.id}`, { headers })).json() as { revision_no: number; tasks: { conversation_ref?: { import_id: string } | null }[] };
  expect(afterPlan.revision_no).toBe(2);
  const importId = afterPlan.tasks[0]!.conversation_ref!.import_id;
  const after = await (await request.get('http://127.0.0.1:18002/api/v1/knowledge', { headers })).json() as unknown[];
  expect(after).toEqual(before);
  await page.screenshot({ path: testInfo.outputPath('conversation-candidates.png'), fullPage: true });
  await detail.getByRole('button', { name: '查看目标计划', exact: true }).click();
  await page.getByRole('button', { name: '打开关联对话问题', exact: true }).first().click();
  await expect(detail).toContainText('BPE 的合并规则');
  await detail.getByText('删除这份对话材料', { exact: true }).click();
  await detail.getByRole('button', { name: '确认删除材料' }).click();
  await expect(detail).toHaveCount(0);
  await page.getByRole('button', { name: '今日学习', exact: true }).click();
  await page.getByRole('button', { name: '打开关联对话问题', exact: true }).first().click();
  await expect(page.getByText('原材料已删除、不可访问或服务暂不可用；不会继续显示已删除的原文。')).toBeVisible();
  expect((await request.get(`http://127.0.0.1:18002/api/v1/conversations/${importId}`, { headers })).status()).toBe(404);
  expect(errors).toEqual([]);
});

test('share parsing, access denied and unparseable failures retain records with pasted fallback', async ({ page }, testInfo) => {
  await login(page, `share-reader-${crypto.randomUUID()}`);
  await page.getByRole('combobox', { name: '材料方式', exact: true }).selectOption('SHARE');
  await page.getByLabel('分享链接', { exact: true }).fill(share);
  await confirm(page);
  const detail = page.getByRole('region', { name: '对话材料详情' });
  await expect(detail.getByRole('status').first()).toHaveText('解析完成');
  await expect(detail).toContainText('合成对话：BPE 与验证');
  await expect(detail).not.toContainText('SECRET');
  await page.screenshot({ path: testInfo.outputPath('shared-conversation.png'), fullPage: true });
  await page.getByLabel('分享链接', { exact: true }).fill(denied);
  await confirm(page);
  await expect(detail.getByRole('status').first()).toContainText('导入失败');
  await expect(detail.getByRole('alert')).toContainText('不会绕过登录');
  await detail.getByRole('button', { name: '重试这次导入' }).click();
  await expect(detail).toContainText('已尝试 2/3 次');
  await expect(detail.getByRole('status').first()).toContainText('导入失败');
  await page.screenshot({ path: testInfo.outputPath('share-access-denied.png'), fullPage: true });
  await detail.getByRole('button', { name: '改用手工粘贴' }).click();
  await page.getByLabel('对话文本', { exact: true }).fill(sample);
  await confirm(page);
  await expect(detail.getByRole('status').first()).toHaveText('解析完成');
  await expect(page.getByRole('region', { name: '对话导入历史' }).getByRole('button', { name: /导入失败/ })).toHaveCount(1);
  await page.getByRole('combobox', { name: '材料方式', exact: true }).selectOption('SHARE');
  await page.getByLabel('分享链接', { exact: true }).fill(unsupported);
  await confirm(page);
  await expect(detail.getByRole('status').first()).toContainText('导入失败');
  await expect(detail).toContainText('SHARE_PARSE_FAILED');
  await expect(detail.getByRole('button', { name: '改用手工粘贴' })).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: '导入对话', exact: true }).click();
  const history = page.getByRole('region', { name: '对话导入历史' });
  await expect(history.getByRole('button', { name: /导入失败/ })).toHaveCount(2);
  await history.getByRole('button', { name: /手工导入对话/ }).click();
  await expect(detail).toContainText('User: this is code text');
  await page.screenshot({ path: testInfo.outputPath('pasted-fallback-history.png'), fullPage: true });
});
