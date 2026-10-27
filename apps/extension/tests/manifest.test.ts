import { expect, it } from 'vitest';
import config from '../wxt.config';

it('does not request all-site hosts or inject an automatic content script', () => {
  const manifest = config.manifest;
  expect(typeof manifest).toBe('object');
  expect(manifest).toHaveProperty('host_permissions', [`${process.env.FRONTIER_EXTENSION_API_ORIGIN ?? 'http://127.0.0.1:8000'}/*`]);
  expect(manifest).not.toHaveProperty('content_scripts');
  expect(manifest).toHaveProperty('permissions', ['sidePanel', 'activeTab', 'scripting', 'storage']);
});
