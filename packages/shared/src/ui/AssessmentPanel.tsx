import { useEffect, useState } from 'react';
import type { ApiClient, ArtifactResponse, AssessmentResponse } from '../api/client';
import { ErrorNotice } from './ErrorNotice';

export function downloadMarkdown(item: ArtifactResponse) {
  const url = URL.createObjectURL(new Blob([item.markdown], { type: 'text/markdown;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url; link.download = `learning-${item.id}.md`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function AssessmentPanel({ api, sessionId }: { api: ApiClient; sessionId: string }) {
  const [item, setItem] = useState<AssessmentResponse | null>(null);
  const [choice, setChoice] = useState<'A' | 'B' | 'C' | null>(null);
  const [draft, setDraft] = useState<ArtifactResponse | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    let active = true;
    void api.assessments().then(items => { if (active) setItem(items.find(value => value.session_id === sessionId) ?? null); })
      .catch(value => { if (active) setError(value); }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [api, sessionId]);
  async function act(operation: () => Promise<void>) {
    setBusy(true); setError(null);
    try { await operation(); } catch (value) { setError(value); } finally { setBusy(false); }
  }
  return <section className="source-preview stack" aria-label="理解验证">
    <h3>来源边界短测</h3><p>本地规则 · 仅验证原文与推断的边界，不能证明主题掌握。</p>
    {!item && <button disabled={busy} onClick={() => void act(async () => setItem(await api.createAssessment(sessionId)))}>开始短测</button>}
    {item && <>
      <h4>{item.question.prompt}</h4><blockquote>{item.question.excerpt}</blockquote>
      {Object.entries(item.question.options).map(([key, label]) => <label key={key} className="check-line"><input type="radio" name={`assessment-${item.id}`} value={key} checked={(item.answer ?? choice) === key} disabled={busy || !!item.answer} onChange={() => setChoice(key as 'A' | 'B' | 'C')} />{key} · {label}</label>)}
      <ul>{item.question.rubric.map(value => <li key={value}>{value}</li>)}</ul>
      {!item.answer && <button disabled={busy || !choice} onClick={() => { if (choice) void act(async () => setItem(await api.answerAssessment(item, choice))); }}>提交作答</button>}
      {item.feedback && <><strong>{item.feedback.result === 'SUPPORTED' ? '本次边界判断有依据' : '需要复查'}</strong><p>{item.feedback.basis}</p><p>{item.feedback.uncertainty}</p>
        {!item.confirmed_at ? <button disabled={busy} onClick={() => void act(async () => setItem(await api.confirmAssessment(item)))}>确认评价并加入学习证据</button> : <p role="status">已确认低强度证据{item.plan_revision ? ` · 已生成计划第 ${item.plan_revision} 版` : ' · 尚无可修订的活动计划'}。</p>}
        <button className="secondary" disabled={busy} onClick={() => void act(async () => setDraft(await api.createArtifact(item.id)))}>生成笔记草稿</button>
      </>}
    </>}
    {draft && <><p role="status">草稿已保存，可在网页工作台“笔记审核”编辑、预览 Diff。</p><pre className="draft-preview">{draft.markdown}</pre><button className="secondary" onClick={() => downloadMarkdown(draft)}>下载 Markdown，仅本地保存</button></>}
    {error !== null && <ErrorNotice error={error} />}
  </section>;
}
