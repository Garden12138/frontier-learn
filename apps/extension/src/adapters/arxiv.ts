import { safePageURL } from './types';
import type { PageAdapter } from './types';

export function arxivAdapter(value: string): PageAdapter | null {
  const url = safePageURL(value);
  if (!url || url.hostname !== 'arxiv.org') return null;
  const match = /^\/(abs|html)\/((?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?\/\d{7})(?:v\d+)?)\/?$/.exec(url.pathname);
  if (!match) return null;
  const abstract = match[1] === 'abs';
  return {
    provider: 'ARXIV', scope: abstract ? 'ABSTRACT' : 'BODY', url: url.href,
    rootSelector: abstract ? 'blockquote.abstract' : 'article.ltx_document, .ltx_document',
    titleSelector: abstract ? 'h1.title' : 'h1.ltx_title, .ltx_title_document',
  };
}
