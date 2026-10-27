export interface PageBlock {
  id: string;
  heading: string;
  text: string;
  selector: string;
}

export interface PageSnapshot {
  url: string;
  title: string;
  provider: 'ARXIV' | 'HUGGINGFACE' | 'MANUAL';
  scope: 'ABSTRACT' | 'BODY' | 'MANUAL';
  blocks: PageBlock[];
  selection: { block_id: string; quote: string } | null;
  truncated: boolean;
}

export interface PageAdapter {
  provider: 'ARXIV' | 'HUGGINGFACE';
  scope: 'ABSTRACT' | 'BODY';
  rootSelector: string;
  titleSelector: string;
  url: string;
}

export type Extraction = { ok: true; page: PageSnapshot } | {
  ok: false;
  code: 'UNSUPPORTED' | 'NO_BODY' | 'PAGE_CHANGED';
  message: string;
};

export function safePageURL(value: string): URL | null {
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || url.port || /[\s\\]/.test(value)) return null;
    url.search = '';
    url.hash = '';
    return url;
  } catch { return null; }
}
