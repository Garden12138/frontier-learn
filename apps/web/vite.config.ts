import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': process.env.FRONTIER_API_PROXY ?? 'http://127.0.0.1:8000' },
  },
  preview: { proxy: { '/api': process.env.FRONTIER_API_PROXY ?? 'http://127.0.0.1:8000' } },
  test: { environment: 'jsdom', include: ['tests/**/*.test.{ts,tsx}'] },
});
