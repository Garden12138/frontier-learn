import { defineConfig } from 'wxt';

const apiOrigin = process.env.FRONTIER_EXTENSION_API_ORIGIN ?? 'http://127.0.0.1:8000';
const url = new URL(apiOrigin);
if (url.origin !== apiOrigin || url.username || url.password ||
    !(url.protocol === 'https:' || (url.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(url.hostname)))) throw new Error('Invalid configured API origin');

export default defineConfig({
  modules: ['@wxt-dev/module-react'],
  vite: () => ({ define: { __FRONTIER_API_ORIGIN__: JSON.stringify(apiOrigin) } }),
  manifest: {
    name: 'FrontierLearn · 网页导学',
    description: '由你主动开启的网页学习助手，连接个人学习工作台。',
    permissions: ['sidePanel', 'activeTab', 'scripting', 'storage'],
    host_permissions: [`${apiOrigin}/*`],
    action: { default_title: '打开 FrontierLearn 导学面板' },
    content_security_policy: { extension_pages: "script-src 'self'; object-src 'self'" },
  },
});
