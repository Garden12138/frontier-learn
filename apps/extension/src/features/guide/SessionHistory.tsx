import { useCallback, useEffect, useState } from 'react';
import { browser } from 'wxt/browser';
import { ErrorNotice, GuideSession } from '@frontier/shared';
import type { ApiClient, SessionResponse, SessionSummary } from '@frontier/shared';
import { revealQuote } from './current-page';

export function SessionHistory({ api }: { api: ApiClient }) {
  const [history, setHistory] = useState<SessionSummary[]>([]);
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [locator, setLocator] = useState('');
  const refresh = useCallback(async () => { try { setHistory(await api.sessions()); setError(null); } catch (value) { setError(value); } }, [api]);
  useEffect(() => { void refresh(); }, [refresh]);
  return <details><summary>继续已保存的会话</summary><section className="card stack">
    {history.length === 0 && <p>还没有已保存会话；可以分析当前页后确认保存。</p>}
    {history.map(item => <button className="secondary" key={item.id} onClick={() => { setLocator(''); void api.session(item.id).then(setSession).catch(setError); }}>{item.title}</button>)}
    <button className="secondary" onClick={() => void refresh()}>刷新历史</button>
    <p className="muted compact">这里显示最近 30 次会话，更早的记录可以到 Web 历史查看。</p>
    {error !== null && <ErrorNotice error={error} onRetry={() => void refresh()} />}
  </section>{session && <GuideSession key={session.id} api={api} session={session} onChange={setSession} onLocate={async (selector, quote) => {
    const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
    const located = tab?.id !== undefined && await revealQuote(tab.id, session.url, selector, quote);
    setLocator(located ? '已回到原文位置。' : '无法精确定位：请在原页面重新点击扩展工具栏，或重新分析材料。');
  }} />}{locator && <p role="status">{locator}</p>}</details>;
}
