import { afterEach, describe, expect, it, vi } from 'vitest';
import { checkHealth } from '../src/index';

afterEach(() => vi.unstubAllGlobals());

describe('health transport', () => {
  it('passes cancellation through to fetch', async () => {
    const controller = new AbortController();
    controller.abort();
    const fetch = vi.fn().mockRejectedValue(new DOMException('Aborted', 'AbortError'));
    vi.stubGlobal('fetch', fetch);
    await expect(checkHealth(controller.signal)).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetch).toHaveBeenCalledWith('/api/v1/health', { signal: controller.signal });
  });

  it('does not expose upstream error bodies', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('private detail', { status: 503 })));
    await expect(checkHealth()).rejects.toThrow('服务暂不可用');
  });
});
