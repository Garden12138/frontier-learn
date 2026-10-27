import { afterEach, expect, it, vi } from 'vitest';
import { ApiClient } from '../src/api/client';

afterEach(() => vi.unstubAllGlobals());

it('clears the caller session on 401 and does not reuse the expired token', async () => {
  let token: string | undefined = 'temporary-session';
  const fetch = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ code: 'SESSION_EXPIRED', message: '请重新登录', request_id: 'req1' }), { status: 401 }))
    .mockResolvedValueOnce(new Response('[]'));
  vi.stubGlobal('fetch', fetch);
  const client = new ApiClient({ getToken: () => token, onUnauthorized: () => { token = undefined; } });
  await expect(client.me()).rejects.toMatchObject({ status: 401, message: '请重新登录' });
  await client.jobs();
  const firstHeaders = fetch.mock.calls[0]?.[1]?.headers as Headers;
  const secondHeaders = fetch.mock.calls[1]?.[1]?.headers as Headers;
  expect(firstHeaders.get('Authorization')).toBe('Bearer temporary-session');
  expect(secondHeaders.has('Authorization')).toBe(false);
});

it('does not expose an upstream error body that does not match the API contract', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('PRIVATE_UPSTREAM_TRACE', { status: 500 })));
  await expect(new ApiClient().jobs()).rejects.toMatchObject({ message: '请求未完成，请稍后重试。' });
});

it('a late 401 for an old token cannot revoke a newer login', async () => {
  let token: string | undefined = 'old-session';
  let complete!: (response: Response) => void;
  vi.stubGlobal('fetch', vi.fn().mockImplementation(() => new Promise<Response>(resolve => { complete = resolve; })));
  const client = new ApiClient({ getToken: () => token, onUnauthorized: () => { token = undefined; } });
  const pending = client.me();
  token = 'new-session';
  complete(new Response(JSON.stringify({ code: 'SESSION_EXPIRED', message: '请重新登录', request_id: 'req' }), { status: 401 }));
  await expect(pending).rejects.toMatchObject({ status: 401 });
  expect(token).toBe('new-session');
});

it('a late cookie-session 401 cannot revoke a completed password login', async () => {
  let complete!: (response: Response) => void;
  const unauthorized = vi.fn();
  vi.stubGlobal('fetch', vi.fn()
    .mockImplementationOnce(() => new Promise<Response>(resolve => { complete = resolve; }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ access_token: null, user_id: 'new-user', expires_at: '2030-01-01T00:00:00Z' }))));
  const client = new ApiClient({ onUnauthorized: unauthorized });
  const old = client.me();
  await client.accountLogin('new-user', 'test password only', 'web');
  complete(new Response(JSON.stringify({ code: 'SESSION_EXPIRED', message: '请重新登录', request_id: 'old' }), { status: 401 }));
  await expect(old).rejects.toMatchObject({ status: 401 });
  expect(unauthorized).not.toHaveBeenCalled();
});
