import { mkdir, writeFile } from 'node:fs/promises';
import { arch, platform, release } from 'node:os';
import { expect, test } from '@playwright/test';

function percentile(values: number[], fraction: number): number {
  const ordered = [...values].sort((a, b) => a - b);
  return Math.round(ordered[Math.ceil(ordered.length * fraction) - 1]! * 100) / 100;
}

test('measure cached production workspace navigation with a persisted learning plan', async ({ page, browser }, info) => {
  test.skip(process.env.FRONTIER_PERFORMANCE_CHECKS !== 'true', 'Requires explicit measurement opt-in');
  const password = crypto.randomUUID() + crypto.randomUUID();
  const registered = await page.request.post('/api/v1/auth/register', { data: { identity: `perf-${crypto.randomUUID()}`, password, client: 'web' } });
  expect(registered.status()).toBe(201);
  const goalReply = await page.request.post('/api/v1/goals', { headers: { Origin: 'http://127.0.0.1:5175', 'Idempotency-Key': crypto.randomUUID() }, data: { title: '理解园艺的证据边界', minutes_per_day: 30 } });
  expect(goalReply.status()).toBe(201);
  const goal = await goalReply.json() as { id: string; version: number };
  const plan = await page.request.post('/api/v1/plans:generate', { headers: { Origin: 'http://127.0.0.1:5175' }, data: { goal_id: goal.id, goal_version: goal.version, expected_revision_no: 0 } });
  expect(plan.status()).toBe(200);
  const failedRequests: number[] = [];
  let transportFailures = 0;
  const pageErrors: string[] = [];
  page.on('response', response => { if (response.status() >= 400) failedRequests.push(response.status()); });
  page.on('requestfailed', () => transportFailures++);
  page.on('pageerror', () => pageErrors.push('PAGE_ERROR'));
  const network = await page.context().newCDPSession(page);
  await network.send('Network.enable');
  const assetRequests = new Set<string>();
  const servedFromCache = new Set<string>();
  const revalidated = new Set<string>();
  network.on('Network.requestWillBeSent', event => { if (new URL(event.request.url).pathname.startsWith('/assets/')) assetRequests.add(event.requestId); });
  network.on('Network.requestServedFromCache', event => servedFromCache.add(event.requestId));
  network.on('Network.responseReceived', event => { if (event.response.fromDiskCache) servedFromCache.add(event.requestId); });
  network.on('Network.responseReceivedExtraInfo', event => { if (event.statusCode === 304) revalidated.add(event.requestId); });
  const samples: { ready_ms: number; cached_assets: number; revalidated_assets: number }[] = [];
  for (let iteration = 0; iteration < 35; iteration++) {
    assetRequests.clear(); servedFromCache.clear(); revalidated.clear();
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    const action = page.getByRole('button', { name: '采纳任务', exact: true }).first();
    await expect(action).toBeVisible();
    await expect(action).toBeEnabled();
    const measurement = {
      ready_ms: await page.evaluate(() => performance.now()),
      cached_assets: [...assetRequests].filter(id => servedFromCache.has(id)).length,
      revalidated_assets: [...assetRequests].filter(id => revalidated.has(id)).length,
    };
    if (iteration >= 5) samples.push(measurement);
  }
  expect(samples).toHaveLength(30);
  expect(failedRequests).toEqual([]);
  expect(transportFailures).toBe(0);
  expect(pageErrors).toEqual([]);
  const durations = samples.map(sample => sample.ready_ms);
  const p95 = percentile(durations, 0.95);
  const cacheVerified = samples.every(sample => sample.cached_assets + sample.revalidated_assets > 0);
  const report = {
    observed_at: new Date().toISOString(),
    scope: 'LOCAL_SERIAL_LOOPBACK_NOT_PRODUCTION_OR_STANDARD_NETWORK',
    environment: { os: platform(), release: release(), arch: arch(), browser: browser.version(), build: 'vite-production-preview', cpu_throttling: false, network_throttling: false, concurrent_users: 1 },
    metric: 'navigation_start_to_first_visible_enabled_learning_task_action_ms',
    warmups: 5, sample_count: samples.length,
    p50_ms: percentile(durations, 0.5), p95_ms: p95,
    max_ms: Math.round(Math.max(...durations) * 100) / 100,
    cache_evidence: 'CDP requestServedFromCache/fromDiskCache or responseReceivedExtraInfo status 304',
    cached_condition_met: cacheVerified,
    local_target_ms: 3000, local_target_met: p95 < 3000 && cacheVerified,
    failed_http_requests: failedRequests.length, failed_transports: transportFailures, page_errors: pageErrors.length,
    samples: samples.map(sample => ({ ...sample, ready_ms: Math.round(sample.ready_ms * 100) / 100 })),
    external_model_calls: 0, external_writes: 0,
  };
  await mkdir('test-results/performance', { recursive: true });
  const artifact = 'test-results/performance/local-web.json';
  await writeFile(artifact, JSON.stringify(report, null, 2));
  await info.attach('local-web.json', { path: artifact, contentType: 'application/json' });
  expect(cacheVerified, 'Measurement must prove the asset bodies were reused').toBe(true);
});
