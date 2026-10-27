import { browser } from 'wxt/browser';
import { extractPage } from '../../../entrypoints/content/extract';
import { adapterFor } from '../../adapters';
import type { Extraction } from '../../adapters';

export async function readCurrentPage(): Promise<Extraction & { tabId?: number }> {
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  const adapter = tab?.url ? adapterFor(tab.url) : null;
  if (!tab?.id || !adapter) return { ok: false, code: 'UNSUPPORTED', message: '请在 arXiv 摘要/HTML 或 Hugging Face 模型主页点击扩展工具栏。PDF 和其他页面可用手工粘贴。' };
  try {
    const results = await browser.scripting.executeScript({ target: { tabId: tab.id, frameIds: [0] }, func: extractPage, args: [adapter] });
    const result = results[0]?.result;
    return result ? { ...result, tabId: tab.id } : { ok: false, code: 'NO_BODY', message: '没有读取到正文，请重试或手工粘贴。' };
  } catch {
    return { ok: false, code: 'NO_BODY', message: '当前页读取权限不足或页面已关闭。请在该页面重新点击扩展工具栏，再分析当前页。' };
  }
}

// Also serialized, with no credentials, model content or arbitrary code passed into the page.
export function locateQuote(url: string, selector: string, quote: string): boolean {
  const current = new URL(location.href); current.search = ''; current.hash = '';
  if (current.href !== url || !quote || selector.length > 500) return false;
  try {
    const element = document.querySelector(selector);
    if (!element) return false;
    function readable(node: Element): boolean {
      if (node.closest('script,style,noscript,template,iframe,object,embed,svg,nav,header,footer,form,input,textarea,select,button,[contenteditable="true"]')) return false;
      for (let parent: Element | null = node; parent; parent = parent.parentElement) {
        const style = getComputedStyle(parent);
        if (parent.hasAttribute('hidden') || parent.getAttribute('aria-hidden') === 'true' || style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
      }
      return true;
    }
    if (!readable(element)) return false;
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    const pieces: string[] = [];
    let visited = 0;
    let characters = 0;
    while (walker.nextNode() && visited++ < 5000) {
      const node = walker.currentNode;
      if (node.nodeName === 'BR') { if (readable(node as Element)) pieces.push(' '); continue; }
      if (node.nodeType !== Node.TEXT_NODE) continue;
      if (node.parentElement && readable(node.parentElement)) { const piece = node.textContent ?? ''; pieces.push(piece); characters += piece.length; }
      if (characters > 4000) break;
    }
    const text = pieces.join('').replace(/\s+/g, ' ').trim();
    if (!text.includes(quote)) return false;
    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
    return true;
  } catch { return false; }
}

export async function revealQuote(tabId: number, url: string, selector: string, quote: string): Promise<boolean> {
  try {
    const result = await browser.scripting.executeScript({ target: { tabId, frameIds: [0] }, func: locateQuote, args: [url, selector, quote] });
    return result[0]?.result === true;
  } catch { return false; }
}
