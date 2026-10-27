import { useRef, useState } from 'react';
import { readCurrentPage, revealQuote } from './current-page';
import type { PageSnapshot } from '../../adapters';
import type { AnalyzePageRequest, ApiClient } from '@frontier/shared';
import { ConnectedGuide } from './ConnectedGuide';

export function PagePreview({ api, signedIn = false }: { api?: ApiClient; signedIn?: boolean }) {
  const [snapshot, setSnapshot] = useState<PageSnapshot | null>(null);
  const [tabId, setTabId] = useState<number | undefined>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [locator, setLocator] = useState('');
  const [text, setText] = useState('');
  const [mode, setMode] = useState<AnalyzePageRequest['mode']>('INTUITIVE');
  const generation = useRef(0);
  async function read() {
    const run = ++generation.current;
    setBusy(true); setError(''); setSnapshot(null); setLocator('');
    try {
      const result = await readCurrentPage();
      if (run !== generation.current) return;
      if (result.ok) { setSnapshot(result.page); setTabId(result.tabId); }
      else setError(result.message);
    } catch { if (run === generation.current) setError('当前页读取失败，请重试或手工粘贴。'); }
    finally { if (run === generation.current) setBusy(false); }
  }
  async function locate(selector: string, quote: string) {
    if (!snapshot || tabId === undefined) { setLocator('手工文本没有原网页定位。'); return; }
    setLocator(await revealQuote(tabId, snapshot.url, selector, quote) ? '已回到原文位置。' : '无法精确定位：页面、内容或权限可能已变化。请重新分析当前页。');
  }
  return <>
    <section className="card stack">
      <h2>{snapshot ? '已读取当前材料' : '尚未开始导学'}</h2>
      <p className="muted">点击后，仅在当前页读取可见正文和可定位选区。支持 arXiv 摘要/HTML、Hugging Face 模型主页；不读取其他标签页或表单。</p>
      <button disabled={busy} onClick={() => void read()}>{busy ? '正在读取当前页…' : '分析当前页'}</button>
      {busy && <><p role="status">正在检查权限并提取正文…</p><button className="secondary" onClick={() => { generation.current++; setBusy(false); setError('已取消本次读取。'); }}>取消读取</button></>}
      {error && <p role="alert">{error}</p>}
      <p className="muted compact">如果切换了站点，请在该页面重新点击扩展工具栏以授予临时读取权限。</p>
      <details><summary>使用手工粘贴文本</summary><form className="stack" onSubmit={event => {
        event.preventDefault(); generation.current++; setBusy(false); setError(''); setTabId(undefined); setLocator('');
        const blocks = text.trim().match(/[\s\S]{1,2000}/g)?.slice(0, 15).map((value, index) => ({ id: `b${index}`, heading: '手工材料', text: value, selector: '' })) ?? [];
        setSnapshot({ url: '', title: '手工粘贴材料', provider: 'MANUAL', scope: 'MANUAL', blocks, selection: null, truncated: false });
        setText('');
      }}><label>学习材料<textarea required minLength={40} maxLength={30000} rows={6} value={text} onChange={event => setText(event.target.value)} /></label><p className="muted compact">请先移除不需要的私人信息和密钥。此预览保留在面板内，尚未发送到服务或模型。</p><button>预览粘贴材料</button></form></details>
    </section>
    {snapshot && <section className="card stack" aria-label="材料预览">
      <span className="eyebrow">材料预览</span><h2>{snapshot.title}</h2>
      <p role="status">解析范围：{snapshot.scope === 'ABSTRACT' ? '仅摘要；未读取论文正文、图表或 PDF' : snapshot.scope === 'MANUAL' ? '用户粘贴文本；来源未经核验' : '当前可见结构化正文；未读取附件、权重或完整图表'}</p>
      {snapshot.url && <a href={snapshot.url} target="_blank" rel="noreferrer">打开材料页面</a>}
      {snapshot.truncated && <p className="muted">材料较长，本次仅保留部分正文。请缩小选区或分段学习。</p>}
      {snapshot.selection ? <blockquote>选区：{snapshot.selection.quote}</blockquote> : <p className="muted">没有可定位选区。跨段落或正文外选区不会被冒充为已定位引用。</p>}
      <label>阅读层级<select value={mode} onChange={event => setMode(event.target.value as AnalyzePageRequest['mode'])}><option value="INTUITIVE">直观解释</option><option value="DEEP">深入原理</option><option value="PRACTICE">工程实践</option></select></label>
      <p className="muted">规则式阅读建议；尚未生成模型解释，也不构成理解验证。</p>
      <ol><li>{mode === 'INTUITIVE' ? '用自己的话提出一个问题，再选一段原文尝试举例。' : mode === 'DEEP' ? '找出原文的前提、论证步骤与适用范围，标记尚不理解的环节。' : '先核对原文中的输入、环境和限制，写一个可检查的小实验计划；不自动运行代码。'}</li><li>{snapshot.provider === 'HUGGINGFACE' ? '分别查看用途、评估条件和限制；模型卡中的主张仍需要核验。' : '区分原文提出的主张、支持材料与自己的推测，缺少正文时保留未知。'}</li><li>用一个新例子说明理解，再检查反例。阅读或 AI 回答不代表掌握。</li></ol>
      <details open><summary>来源片段（{snapshot.blocks.length}）</summary>{snapshot.blocks.map(block => <article key={block.id} className="source-preview"><h3>{block.heading}</h3><p>{block.text}</p>{block.selector && <button className="secondary" onClick={() => void locate(block.selector, block.text.slice(0, 180))}>回到原文 {block.id}</button>}</article>)}</details>
      {locator && <p role="status">{locator}</p>}
    </section>}
    {snapshot && signedIn && api && <ConnectedGuide key={JSON.stringify(snapshot)} api={api} snapshot={snapshot} mode={mode} onLocate={locate} />}
    {snapshot && !signedIn && <p className="muted">登录你的学习账号后，可将预览保存为跨端导学会话。</p>}
  </>;
}
