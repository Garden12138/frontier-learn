import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App } from '../src/App';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('shows service failure and a recovery action without claiming learning data exists', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><App /></QueryClientProvider>);
  expect((await screen.findByRole('alert')).textContent).toContain('请启动 API 后重试');
  expect(screen.getByRole('button', { name: '重新检查连接' })).toBeTruthy();
  expect(screen.getByText(/登录前不读取你的知识来源/)).toBeTruthy();
  client.clear();
});
