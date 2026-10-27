import { expect, test } from '@playwright/test';
import type { APIRequestContext } from '@playwright/test';

const base = 'http://127.0.0.1:18002/api/v1';
async function prepare(request: APIRequestContext, identity: string) {
  const login = await request.post(`${base}/auth/mock-login`, { data: { identity, client: 'extension' } });
  const headers = { Authorization: `Bearer ${(await login.json()).access_token as string}`, 'Idempotency-Key': crypto.randomUUID() };
  const goalReply = await request.post(`${base}/goals`, { headers, data: { title: '理解 Attention 的来源边界', minutes_per_day: 30 } });
  const goal = await goalReply.json() as { id: string; version: number };
  expect((await request.post(`${base}/plans:generate`, { headers, data: { goal_id: goal.id, goal_version: goal.version, expected_revision_no: 0 } })).ok()).toBe(true);
  const reply = await request.post(`${base}/pages:analyze`, { headers, data: {
    consent: true, goal_id: goal.id,
    page: { url: 'https://arxiv.org/abs/2410.12345', title: 'Synthetic Attention learning material', provider: 'ARXIV', scope: 'ABSTRACT', truncated: false, selection: null,
      blocks: [{ id: 'b0', heading: '摘要', selector: 'blockquote', text: 'Attention is discussed in this synthetic source. Its claims need independent verification. <script>window.quizInjected=true</script>' }] },
  } });
  expect(reply.ok()).toBe(true);
  const session = await reply.json() as { id: string; turns: { job: { id: string } }[] };
  await expect.poll(async () => (await (await request.get(`${base}/jobs/${session.turns[0]!.job.id}`, { headers })).json() as { status: string }).status).toBe('SUCCEEDED');
  return { headers, session, goal };
}

test('short verification, confirmed evidence, editable draft, scoped diff and one PR', async ({ page, request }, testInfo) => {
  const identity = `learning-${crypto.randomUUID()}`;
  const { headers } = await prepare(request, identity);
  const source = await (await request.post(`${base}/sources`, { headers, data: { external_ref: 'sample/notes', consent: true } })).json() as { id: string };
  expect((await request.put(`${base}/sources/${source.id}/write-permission`, { headers, data: { version: 1, confirm: true, credential: 'browser-fixture-secret', path_prefixes: ['notes'] } })).status()).toBe(204);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.getByLabel('开发体验账号').fill(identity);
  await page.getByRole('button', { name: '进入学习空间', exact: true }).click();
  await page.getByRole('button', { name: '理解验证', exact: true }).click();
  await page.getByRole('button', { name: '开始短测', exact: true }).click();
  await expect(page.getByRole('button', { name: '提交作答', exact: true })).toBeDisabled();
  await page.getByRole('radio', { name: /^B ·/ }).check();
  await page.getByRole('button', { name: '提交作答', exact: true }).click();
  await expect(page.getByRole('region', { name: '理解验证' })).toContainText('证据强度低');
  await page.getByRole('button', { name: '确认评价并加入学习证据', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('已生成计划第 2 版');
  await page.getByRole('button', { name: '生成笔记草稿', exact: true }).click();
  await expect(page.getByRole('status').last()).toContainText('草稿已保存');
  await page.getByRole('button', { name: '笔记审核', exact: true }).click();
  const draft = page.getByRole('article', { name: '笔记草稿审核' });
  await expect(draft).toContainText('内容尚需核验');
  const original = await draft.getByLabel('Markdown 草稿').inputValue();
  await draft.getByLabel('Markdown 草稿').fill(`${original}\n## 我的复查\n仍需构造独立例子。\n`);
  await draft.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect(draft).toContainText('草稿 v2');
  const downloaded = page.waitForEvent('download');
  await draft.getByRole('button', { name: '下载 Markdown，仅本地保存', exact: true }).click();
  expect((await downloaded).suggestedFilename()).toMatch(/^learning-.*\.md$/);
  await draft.getByText('GitHub 分支与 PR', { exact: true }).click();
  await draft.getByLabel('写回仓库').selectOption(source.id);
  await draft.getByRole('button', { name: '预览 Diff', exact: true }).click();
  await expect(draft.getByLabel('笔记 Diff')).toContainText('+## 我的复查');
  await expect(draft.getByRole('button', { name: '确认创建分支与 PR', exact: true })).toBeDisabled();
  await page.screenshot({ path: testInfo.outputPath('draft-diff-review.png'), fullPage: true });
  await draft.getByRole('checkbox').check();
  await draft.getByRole('button', { name: '确认创建分支与 PR', exact: true }).click();
  await expect(draft.getByRole('link', { name: /打开 GitHub PR/ })).toBeVisible();
  await expect(draft).toContainText('SUCCEEDED');
  await page.reload();
  await page.getByRole('button', { name: '笔记审核', exact: true }).click();
  await expect(page.getByLabel('Markdown 草稿')).toHaveValue(/我的复查/);
  expect(await page.evaluate(() => !('quizInjected' in window))).toBe(true);
  expect(errors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath('pr-created.png'), fullPage: true });
});

test('ownership settings export, explicit delete, stale session and another account preserved', async ({ page, request }, testInfo) => {
  const identity = `ownership-${crypto.randomUUID()}`;
  const { headers } = await prepare(request, identity);
  const other = await request.post(`${base}/auth/mock-login`, { data: { identity: `other-${crypto.randomUUID()}`, client: 'extension' } });
  const otherHeaders = { Authorization: `Bearer ${(await other.json()).access_token as string}` };
  await page.goto('/');
  await page.getByLabel('开发体验账号').fill(identity);
  await page.getByRole('button', { name: '进入学习空间', exact: true }).click();
  await page.getByRole('button', { name: '设置与数据', exact: true }).click();
  await expect(page.getByText('外部模型处理授权：未授权', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '同意最小片段用于外部模型处理', exact: true }).click();
  await expect(page.getByRole('button', { name: '撤销外部模型处理授权', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '撤销外部模型处理授权', exact: true }).click();
  const downloaded = page.waitForEvent('download');
  await page.getByRole('button', { name: '下载我的学习记录 JSON', exact: true }).click();
  expect((await downloaded).suggestedFilename()).toBe('frontier-learning-data.json');
  const exported = await request.get(`${base}/settings/export`, { headers });
  expect(exported.ok()).toBe(true);
  expect(await exported.text()).not.toContain('token_digest');
  await expect(page.getByRole('button', { name: '永久删除我的应用内数据', exact: true })).toBeDisabled();
  await page.getByLabel('输入“删除我的数据”再次确认').fill('删除我的数据');
  await page.screenshot({ path: testInfo.outputPath('ownership-confirmation.png'), fullPage: true });
  await page.getByRole('button', { name: '永久删除我的应用内数据', exact: true }).click();
  await expect(page.getByRole('button', { name: '进入学习空间', exact: true })).toBeVisible();
  expect((await request.get(`${base}/auth/me`, { headers })).status()).toBe(401);
  expect((await request.get(`${base}/auth/me`, { headers: otherHeaders })).status()).toBe(200);
});
