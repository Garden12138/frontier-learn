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
  const [cloudAvailable, setCloudAvailable] = useState(false);
  const [cloudConsent, setCloudConsent] = useState(false);
  useEffect(() => {
    let active = true;
    void api.assessments(sessionId).then(items => { if (active) setItem(items.find(value => value.session_id === sessionId) ?? null); })
      .catch(value => { if (active) setError(value); }).finally(() => { if (active) setBusy(false); });
    void api.settings().then(settings => { if (active) setCloudAvailable(settings.cloud_provider_available === true && settings.cloud_processing_allowed); }).catch(() => {});
    return () => { active = false; };
  }, [api, sessionId]);
  const pending = item?.job?.status === 'PENDING' || item?.job?.status === 'RUNNING';
  useEffect(() => {
    if (!pending || !item) return;
    let active = true;
    const timer = setTimeout(() => {
      void api.assessment(item.id).then(value => { if (active) setItem(value); }).catch(value => { if (active) setError(value); });
    }, 1000);
    return () => { active = false; clearTimeout(timer); };
  }, [api, item, pending]);
  async function act(operation: () => Promise<void>) {
    setBusy(true); setError(null);
    try { await operation(); } catch (value) { setError(value); } finally { setBusy(false); }
  }
  return <section className="source-preview stack" aria-label="理解验证">
    <h3>{item?.question.scope === 'CONCEPT_CHECK' ? '概念选择题' : '来源边界短测'}</h3><p>{item?.question.scope === 'CONCEPT_CHECK' ? '模型拟题与答案依据，待复查；单题结果不能证明主题掌握。' : '本地规则 · 仅验证原文与推断的边界，不能证明主题掌握。'}</p>
    {!item && <><button disabled={busy} onClick={() => void act(async () => setItem(await api.createAssessment(sessionId)))}>开始短测</button>
      {cloudAvailable ? <><label className="check-line"><input type="checkbox" checked={cloudConsent} onChange={event => setCloudConsent(event.target.checked)} />同意将本次主题及一个原文片段（最多 1800 字符）发送给 OpenAI 生成概念题</label><button disabled={busy || !cloudConsent} onClick={() => void act(async () => setItem(await api.createAssessment(sessionId, 'CONCEPT_CHECK', cloudConsent)))}>生成概念选择题</button></> : <p className="muted">概念拟题需先配置云模型，并在“设置与数据”授权。当前仍可使用来源边界题。</p>}</>}
    {item?.job && <><p role="status">概念拟题任务：{item.job.status}{item.job.error_code ? ` · ${item.job.error_code}` : ''}</p>
      {pending && <button className="secondary" disabled={busy} onClick={() => void act(async () => { await api.cancelJob(item.job!.id); setItem(await api.assessment(item.id)); })}>取消概念拟题</button>}
      {item.job.status === 'FAILED' && <button className="secondary" disabled={busy} onClick={() => void act(async () => { await api.retryJob(item.job!.id); setItem(await api.assessment(item.id)); })}>重试概念拟题（重新计入预算）</button>}
      <button className="secondary" disabled={busy} onClick={() => void act(async () => setItem(await api.assessment(item.id)))}>刷新短测</button></>}
    {item && <>
      <h4>{item.question.prompt}</h4><blockquote>{item.question.excerpt}</blockquote>
      {Object.entries(item.question.options).map(([key, label]) => <label key={key} className="check-line"><input type="radio" name={`assessment-${item.id}`} value={key} checked={(item.answer ?? choice) === key} disabled={busy || !!item.answer} onChange={() => setChoice(key as 'A' | 'B' | 'C')} />{key} · {label}</label>)}
      <ul>{item.question.rubric.map(value => <li key={value}>{value}</li>)}</ul>
      {!item.answer && <button disabled={busy || !choice || pending || (item.job != null && item.job.status !== 'SUCCEEDED')} onClick={() => { if (choice) void act(async () => setItem(await api.answerAssessment(item, choice))); }}>提交作答</button>}
      {item.feedback && <><strong>{item.feedback.result === 'SUPPORTED' ? (item.question.scope === 'CONCEPT_CHECK' ? '本次选择符合保存的答案依据' : '本次边界判断有依据') : '需要复查'}</strong><p>{item.feedback.basis}</p><p>{item.feedback.uncertainty}</p>
        {!item.confirmed_at ? <button disabled={busy} onClick={() => void act(async () => setItem(await api.confirmAssessment(item)))}>确认评价并加入学习证据</button> : <p role="status">已确认低强度证据{item.plan_revision ? ` · 已生成计划第 ${item.plan_revision} 版` : ' · 尚无可修订的活动计划'}。</p>}
        <button className="secondary" disabled={busy} onClick={() => void act(async () => setDraft(await api.createArtifact(item.id)))}>生成笔记草稿</button>
      </>}
    </>}
    {draft && <><p role="status">草稿已保存，可在网页工作台“笔记审核”编辑、预览 Diff。</p><pre className="draft-preview">{draft.markdown}</pre><button className="secondary" onClick={() => downloadMarkdown(draft)}>下载 Markdown，仅本地保存</button></>}
    {error !== null && <ErrorNotice error={error} />}
  </section>;
}
