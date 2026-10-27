import { safePageURL } from './types';
import type { PageAdapter } from './types';

export function huggingfaceAdapter(value: string): PageAdapter | null {
  const url = safePageURL(value);
  if (!url || url.hostname !== 'huggingface.co') return null;
  const segments = url.pathname.split('/').filter(Boolean);
  if (segments.length < 1 || segments.length > 2 || segments.some(part => !/^[\w.-]+$/.test(part))) return null;
  if (['models', 'datasets', 'spaces', 'docs', 'organizations', 'orgs', 'collections', 'blog', 'papers', 'tasks', 'settings', 'login', 'join', 'api'].includes(segments[0] ?? '')) return null;
  return { provider: 'HUGGINGFACE', scope: 'BODY', url: url.href,
    rootSelector: 'main #readme, main .prose, main [data-testid="model-card"]',
    titleSelector: 'main h1',
  };
}
