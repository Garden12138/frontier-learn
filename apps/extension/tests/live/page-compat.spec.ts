import { createHash } from 'node:crypto';
import { expect, test } from '@playwright/test';
import { extractPage } from '../../entrypoints/content/extract';
import { adapterFor } from '../../src/adapters';

// Explicit opt-in public GET-only checks; never included in offline CI or unit tests.
// Each page is isolated and scripts, model downloads, forms and third parties are blocked.
const samples = [
  'https://arxiv.org/abs/1706.03762',
  'https://arxiv.org/abs/1810.04805',
  'https://arxiv.org/abs/2005.11401',
  'https://arxiv.org/abs/2307.09288',
  'https://arxiv.org/abs/2401.04088',
  'https://arxiv.org/html/2401.04088v1',
  'https://huggingface.co/google-bert/bert-base-uncased',
  'https://huggingface.co/openai-community/gpt2',
  'https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2',
  'https://huggingface.co/mistralai/Mistral-7B-v0.1',
];

for (const url of samples) {
  test(url, async ({ page }, info) => {
    test.skip(process.env.FRONTIER_LIVE_PAGE_CHECKS !== 'true', 'Requires explicit public-network opt-in');
    let requests = 0;
    await page.route('**/*', async route => {
      const request = route.request();
      const target = new URL(request.url());
      if (++requests > 30 || request.method() !== 'GET' || target.protocol !== 'https:' || target.hostname !== new URL(url).hostname || !['document', 'stylesheet'].includes(request.resourceType())) {
        return route.abort();
      }
      return route.continue();
    });
    const response = await page.goto(url, { waitUntil: 'domcontentloaded' });
    expect(response?.status(), 'Public page must be accessible without signing in').toBe(200);
    const adapter = adapterFor(page.url());
    expect(adapter, 'Final public URL must still match a supported adapter').not.toBeNull();
    if (!adapter) throw new Error('Unsupported public destination');
    const result = await page.evaluate(extractPage, adapter);
    expect(result.ok, 'Readable source must be available; access restrictions are not bypassed').toBe(true);
    if (!result.ok) throw new Error(result.code);
    const source = result.page;
    const probes = source.blocks.slice(0, 3).map(block => ({ selector: block.selector, quote: block.text.slice(0, 80) }));
    const checks = await page.evaluate(items => items.map(item => {
      const element = document.querySelector(item.selector);
      const text = element?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
      return !!element && text.includes(item.quote) && getComputedStyle(element).visibility !== 'hidden';
    }), probes);
    expect(checks.length).toBeGreaterThan(0);
    expect(checks.every(Boolean), 'Extracted anchors must resolve to their visible source').toBe(true);
    // Save only provenance/hash/counts. Public source text is not republished as a fixture.
    await info.attach('compatibility.json', { contentType: 'application/json', body: JSON.stringify({
      observed_at: new Date().toISOString(), requested_url: url, final_url: source.url,
      scope: source.scope, block_count: source.blocks.length, truncated: source.truncated,
      source_sha256: createHash('sha256').update(source.blocks.map(block => block.text).join('\n')).digest('hex'),
      anchor_probes: checks.length, matched: checks.filter(Boolean).length,
      review: 'AUTOMATED_DOM_CHECK_NOT_HUMAN_REVIEW', page_scripts_enabled: false,
    }, null, 2) });
  });
}
