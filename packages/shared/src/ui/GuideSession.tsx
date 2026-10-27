import { useEffect, useRef, useState } from 'react';
import type { ApiClient, AskRequest, SessionResponse, SettingsResponse } from '../api/client';
import { AssessmentPanel } from './AssessmentPanel';
import { ErrorNotice } from './ErrorNotice';

const modes = { INTUITIVE: '直观解释', DEEP: '深入原理', PRACTICE: '工程实践' };
const statuses = { PENDING: '等待导学', RUNNING: '正在组织导学…', SUCCEEDED: '导学已保存', FAILED: '导学失败；材料与问题已保留', CANCELLED: '导学已取消；材料与问题已保留', PARTIAL: '导学部分完成' };

export function GuideSession({ api, session, onChange, onLocate }: {
  api: ApiClient;
  session: SessionResponse;
  onChange: (value: SessionResponse) => void;
  onLocate?: (selector: string, quote: string) => Promise<void>;
}) {
  const [processing, setProcessing] = useState<SettingsResponse | null>(null);
  const [cloudConsent, setCloudConsent] = useState(false);
  useEffect(() => { let active = true; void api.settings().then(value => { if (active) setProcessing(value); }).catch(value => { if (active) setError(value); }); return () => { active = false; }; }, [api]);
  const [question, setQuestion] = useState('');
  const [mode, setMode] = useState<AskRequest['mode']>('INTUITIVE');
  const [selection, setSelection] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [pollFailed, setPollFailed] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const request = useRef<{ encoded: string; key: string } | null>(null);
  const waiting = session.turns.some(turn => ['PENDING', 'RUNNING'].includes(turn.job.status));
  useEffect(() => {
    if (!waiting || pollFailed) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await api.session(session.id);
        if (active) { onChange(next); timer = setTimeout(() => void poll(), 1000); }
      } catch (value) { if (active) { setError(value); setPollFailed(true); } }
    }
    timer = setTimeout(() => void poll(), 400);
    return () => { active = false; clearTimeout(timer); };
  }, [api, session.id, waiting, onChange, pollFailed]);
  async function action(operation: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await operation(); onChange(await api.session(session.id)); setPollFailed(false); }
    catch (value) { setError(value); }
    finally { setBusy(false); }
  }
  const scope = session.page.scope === 'ABSTRACT' ? '仅摘要；未读取正文与图表' : session.page.scope === 'MANUAL' ? '手工材料；来源未经核验' : '当前提供的结构化正文';
  return <section className="card stack" aria-label="已保存导学会话">
    <h2>{session.title}</h2><p>解析范围：{scope}</p>
    <p className="muted compact">引用匹配仅针对本次材料快照，未经服务独立在线核验。阅读和导学不增加掌握证据。</p>
    {session.page.truncated && <p>材料已截断；未保留的部分不在本次分析范围。</p>}
    {session.turns.map(turn => <article className="source-preview stack" key={turn.id}>
      <h3>{turn.question}</h3><span>{modes[turn.mode]}</span>
      <p role="status">{statuses[turn.job.status]}</p>
      {turn.job.status === 'FAILED' && <p>错误：{turn.job.error_code}。已尝试 {turn.job.attempt_count}/{turn.job.max_attempts} 次。</p>}
      {['PENDING', 'RUNNING'].includes(turn.job.status) && <button className="secondary" disabled={busy} onClick={() => void action(() => api.cancelJob(turn.job.id))}>取消导学</button>}
      {turn.job.status === 'FAILED' && turn.job.attempt_count < turn.job.max_attempts && <button disabled={busy} onClick={() => void action(() => api.retryJob(turn.job.id))}>重试导学</button>}
      {turn.guide && <>
        <strong>{turn.guide.label === 'LOCAL_RULES' ? '本地规则建议 · 尚未生成模型解释' : '模型解释/推测 · 需要核验'}</strong>
        <p>{turn.guide.summary}</p><h4>阅读重点</h4><ul>{turn.guide.points.map((point, i) => <li key={i}>{point}</li>)}</ul>
        <h4>先修与已知线索</h4><ul>{turn.guide.prerequisites.map((point, i) => <li key={i}>{point}</li>)}</ul>
        <h4>最小学习步骤</h4><ol>{turn.guide.steps.map((step, i) => <li key={i}>{step}</li>)}</ol>
        {turn.guide.citations.map((citation, i) => <div key={i}>
          <blockquote>{citation.quote}</blockquote><p>{citation.status === 'SNAPSHOT_MATCH' ? '与材料快照匹配；原文主张仍需核实' : '引用未验证'}</p>
          {citation.status === 'SNAPSHOT_MATCH' && citation.selector && onLocate && <button className="secondary" onClick={() => void onLocate(citation.selector, citation.quote)}>定位引用 {citation.block_id}</button>}
          {citation.status === 'SNAPSHOT_MATCH' && !onLocate && <p className="muted compact">精确网页定位需回到插件并重新授予当前页权限。</p>}
        </div>)}
      </>}
    </article>)}
    {session.turns.some(turn => turn.guide) && <AssessmentPanel key={session.id} api={api} sessionId={session.id} />}
    <form className="stack" onSubmit={event => {
      event.preventDefault();
      const block = session.page.blocks.find(item => item.id === selection);
      const body: AskRequest = { cloud_processing_allowed: cloudConsent && processing?.active_provider === 'OPENAI_RESPONSES', expected_version: session.version, question, mode, selection: block ? { block_id: block.id, quote: block.text.slice(0, 1000) } : null };
      const encoded = JSON.stringify(body);
      if (request.current?.encoded !== encoded) request.current = { encoded, key: crypto.randomUUID() };
      const key = request.current.key;
      void action(async () => { await api.ask(session.id, body, key); setQuestion(''); setCloudConsent(false); request.current = null; });
    }}>
      <label>追问层级<select value={mode} onChange={event => setMode(event.target.value as AskRequest['mode'])}>{Object.entries(modes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>追问片段<select value={selection} onChange={event => setSelection(event.target.value)}><option value="">沿用当前材料</option>{session.page.blocks.map(block => <option key={block.id} value={block.id}>{block.id} · {block.heading}</option>)}</select></label>
      <label>继续提问<textarea required maxLength={1000} value={question} onChange={event => { setQuestion(event.target.value); setCloudConsent(false); }} /></label>
      {processing?.cloud_provider_available && processing.cloud_processing_allowed && <label className="check-line"><input type="checkbox" checked={cloudConsent} onChange={event => setCloudConsent(event.target.checked)} />允许本次追问将最小片段发送给外部 OpenAI 模型 {processing.model}</label>}
      <p className="muted compact">未允许本次云处理时使用本地阅读方法。引用和回答仍需核验。</p>
      <button disabled={busy || waiting || session.version >= 20}>{busy ? '正在保存…' : '保存追问'}</button>
    </form>
    <button className="secondary" disabled={busy} onClick={() => void action(async () => { setProcessing(await api.settings()); setCloudConsent(false); })}>刷新会话</button>
    {error !== null && <ErrorNotice error={error} onRetry={() => void action(async () => {})} />}
    <details open={confirmDelete} onToggle={event => setConfirmDelete(event.currentTarget.open)}><summary>删除这次会话</summary><p>删除保存的材料和追问，并取消尚未完成的导学。</p><button className="danger" disabled={busy} onClick={() => { setBusy(true); void api.deleteSession(session.id).then(() => window.location.reload()).catch(value => { setError(value); setBusy(false); }); }}>确认删除会话</button></details>
  </section>;
}
