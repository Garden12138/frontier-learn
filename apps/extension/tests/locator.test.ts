// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
vi.mock('wxt/browser', () => ({ browser: {} }));
import { locateQuote } from '../src/features/guide/current-page';

declare const jsdom: { reconfigure(options: { url: string }): void };
afterEach(() => { document.body.innerHTML = ''; });

it('rechecks visible text with the same whitespace rules and rejects hidden descendants', () => {
  jsdom.reconfigure({ url: 'https://arxiv.org/abs/2410.12345' });
  document.body.innerHTML = '<article><p>First <em>visible</em> source statement.<span hidden>SECRET</span></p></article>';
  const paragraph = document.querySelector('p')!;
  paragraph.scrollIntoView = vi.fn();
  expect(locateQuote(location.href, 'p', 'First visible source statement.')).toBe(true);
  expect(locateQuote(location.href, 'p', 'SECRET')).toBe(false);
  document.querySelector('article')!.style.display = 'none';
  expect(locateQuote(location.href, 'p', 'First visible source statement.')).toBe(false);
  expect(locateQuote('https://arxiv.org/abs/2410.12346', 'p', 'First')).toBe(false);
});

it('locates exact inline words and punctuation without fabricating separating spaces', () => {
  jsdom.reconfigure({ url: 'https://huggingface.co/sample/model' });
  document.body.innerHTML = '<p>The <a>Model-7B</a>-v0.1 uses <em>fine</em>tuning.<br>Further review.</p>';
  document.querySelector('p')!.scrollIntoView = vi.fn();
  expect(locateQuote(location.href, 'p', 'Model-7B-v0.1 uses finetuning.')).toBe(true);
  expect(locateQuote(location.href, 'p', 'Model-7B -v0.1 uses fine tuning.')).toBe(false);
  expect(locateQuote(location.href, 'p', 'finetuning. Further review.')).toBe(true);
});
