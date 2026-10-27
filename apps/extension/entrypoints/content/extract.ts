import type { Extraction, PageAdapter, PageBlock } from '../../src/adapters/types';

// Serialized by scripting.executeScript: this function must have no runtime imports/closure.
export function extractPage(adapter: PageAdapter): Extraction {
  const normalize = (value: string) => value.replace(/\s+/g, ' ').trim();
  const current = new URL(location.href);
  current.search = ''; current.hash = '';
  if (current.href !== adapter.url) return { ok: false, code: 'PAGE_CHANGED', message: '页面已切换，请重新点击工具栏并分析当前页。' };
  const excluded = 'script,style,noscript,template,iframe,object,embed,svg,nav,header,footer,form,input,textarea,select,button,[contenteditable="true"]';
  let truncated = false;
  let remainingNodes = 10000;
  function readable(element: Element): boolean {
    if (element.closest(excluded)) return false;
    for (let node: Element | null = element; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (node.hasAttribute('hidden') || node.getAttribute('aria-hidden') === 'true' || style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
    }
    return true;
  }
  function plain(element: Element): string {
    // Read text and visible line breaks without evaluating markup or reading form values.
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    const pieces: string[] = [];
    let visited = 0;
    let characters = 0;
    while (walker.nextNode()) {
      if (++visited > 5000 || --remainingNodes < 0) { truncated = true; break; }
      const node = walker.currentNode;
      if (node.nodeName === 'BR') { if (readable(node as Element)) pieces.push(' '); continue; }
      if (node.nodeType !== Node.TEXT_NODE) continue;
      if (node.parentElement && readable(node.parentElement)) { const piece = node.textContent ?? ''; pieces.push(piece); characters += piece.length; }
      if (characters > 4000) { truncated = true; break; }
    }
    // Inline markup may split one word or identifier; preserve the original whitespace.
    return normalize(pieces.join(''));
  }
  function selectorFor(element: Element): string {
    const parts: string[] = [];
    for (let node: Element | null = element; node && parts.length < 12; node = node.parentElement) {
      const tag = node.tagName.toLowerCase();
      const siblings = node.parentElement ? Array.from(node.parentElement.children).filter(item => item.tagName === node!.tagName) : [node];
      parts.unshift(`${tag}:nth-of-type(${siblings.indexOf(node) + 1})`);
      if (node === document.documentElement) break;
    }
    const selector = parts.join(' > ');
    return selector.length <= 500 && document.querySelector(selector) === element ? selector : '';
  }
  const root = document.querySelector(adapter.rootSelector);
  if (!root || !readable(root)) return { ok: false, code: 'NO_BODY', message: '未找到可读正文。页面可能需要登录、只有 PDF，或结构暂不支持；可改用手工粘贴。' };
  const blocks: PageBlock[] = [];
  let heading = adapter.scope === 'ABSTRACT' ? '摘要' : '正文';
  let total = 0;
  const matches = root.querySelectorAll('h1,h2,h3,h4,p,pre,li,blockquote');
  if (matches.length > 1000) truncated = true;
  const nodes: Element[] = [];
  for (let index = 0; index < Math.min(matches.length, 1000); index++) nodes.push(matches[index]!);
  const candidates = nodes.length ? nodes : [root];
  for (const node of candidates) {
    if (!readable(node)) continue;
    if (/^H[1-4]$/.test(node.tagName)) { heading = plain(node).slice(0, 200) || heading; continue; }
    if (node !== root && node.parentElement?.closest('p,pre,li,blockquote') && node.parentElement.closest('p,pre,li,blockquote') !== root) continue;
    const text = plain(node);
    if (!text) continue;
    if (blocks.length >= 40 || total >= 30000 || remainingNodes < 0) { truncated = true; break; }
    const excerpt = text.slice(0, Math.min(2000, 30000 - total));
    if (excerpt.length < text.length) truncated = true;
    blocks.push({ id: `b${blocks.length}`, heading, text: excerpt, selector: selectorFor(node) });
    total += excerpt.length;
  }
  if (total < 40) return { ok: false, code: 'NO_BODY', message: '可读正文过短，未生成导学；可选择更完整的段落或手工粘贴。' };
  const selected = window.getSelection();
  const quote = normalize(selected?.toString() ?? '');
  const block = quote.length >= 3 && quote.length <= 1000 && selected?.anchorNode && root.contains(selected.anchorNode) && selected.focusNode && root.contains(selected.focusNode)
    ? blocks.find(item => item.text.includes(quote)) : undefined;
  const title = document.querySelector(adapter.titleSelector);
  return { ok: true, page: {
    url: adapter.url, title: (title && readable(title) ? plain(title) : document.title).slice(0, 500) || '未命名页面',
    provider: adapter.provider, scope: adapter.scope, blocks,
    selection: block ? { block_id: block.id, quote } : null, truncated,
  } };
}
