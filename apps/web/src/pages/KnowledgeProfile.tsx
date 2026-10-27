import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ErrorNotice } from '@frontier/shared';
import type { ApiClient, CorrectionRequest } from '@frontier/shared';

const levels = { UNKNOWN: '证据不足', EXPOSED: '有学习证据／待验证', UNDERSTANDING: '通过理解验证', APPLIED: '有实践验证', PROFICIENT: '有多场景验证' };

function citationUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  try { const url = new URL(value); return url.protocol === 'https:' && url.hostname === 'github.com' ? url.href : null; } catch { return null; }
}

export function KnowledgeProfile({ api, userId, initialQuery = '' }: { api: ApiClient; userId: string; initialQuery?: string }) {
  const client = useQueryClient();
  const [search, setSearch] = useState(initialQuery);
  const [filter, setFilter] = useState(initialQuery);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [level, setLevel] = useState<CorrectionRequest['level']>(null);
  const [reason, setReason] = useState('');
  const states = useQuery({ queryKey: ['user', userId, 'knowledge', filter, offset], queryFn: ({ signal }) => api.knowledge(filter, offset, signal) });
  const evidence = useQuery({ queryKey: ['user', userId, 'evidence', selected], queryFn: ({ signal }) => api.evidence(selected!, signal), enabled: selected !== null });
  const selectedState = states.data?.find(state => state.concept_id === selected);
  const correct = useMutation({ mutationFn: () => api.correctKnowledge(selected!, { level, reason, version: selectedState!.version }), onSuccess: async () => { setReason(''); await client.invalidateQueries({ queryKey: ['user', userId] }); } });
  return <section className="stack" aria-labelledby="profile-title">
    <div><span className="eyebrow">02 / 认识学习起点</span><h1 id="profile-title">我的知识画像</h1><p className="muted">笔记、代码和自报都是学习线索。它们不能单独证明你已掌握；每条状态都保留证据和验证方式。</p></div>
    <form className="actions" onSubmit={event => { event.preventDefault(); setFilter(search); setOffset(0); setSelected(null); }}><label className="grow">搜索知识点<input value={search} onChange={event => setSearch(event.target.value)} maxLength={200} placeholder="例如 Attention 或园艺基础" /></label><button type="submit">搜索</button></form>
    {states.isPending && <p role="status">正在加载知识画像…</p>}
    {states.isError && <ErrorNotice error={states.error} onRetry={() => void states.refetch()} />}
    {states.data?.length === 0 && <div className="card muted">还没有对应的知识证据。你可以先同步笔记，之后也可以从学习目标开始。</div>}
    <div className="knowledge-grid">{states.data?.map(state => <button className={`knowledge-card ${selected === state.concept_id ? 'selected' : ''}`} key={state.concept_id} onClick={() => { setSelected(state.concept_id); setLevel(null); setReason(''); correct.reset(); }}>
      <strong>{state.name}</strong><span className="badge">{state.override_level ? '用户修正（未经验证）' : levels[state.level]}</span><span>{state.evidence_count} 条证据 · 判断依据{state.confidence === 'LOW' ? '有限' : '中等'}</span>{state.review_due && <span>建议复习</span>}
    </button>)}</div>
    <div className="actions"><button className="secondary" disabled={offset === 0} onClick={() => { setOffset(Math.max(0, offset - 50)); setSelected(null); }}>上一页</button><span>第 {offset / 50 + 1} 页</span><button className="secondary" disabled={!states.data || states.data.length < 50} onClick={() => { setOffset(offset + 50); setSelected(null); }}>下一页</button></div>
    {selectedState && <article className="card stack" aria-label="知识证据详情"><h2>{selectedState.name} 的依据</h2>
      {selectedState.override_reason && <p>用户修正理由：{selectedState.override_reason}</p>}
      {evidence.isPending && <p role="status">正在加载原文依据…</p>}
      {evidence.isError && <ErrorNotice error={evidence.error} onRetry={() => void evidence.refetch()} />}
      {evidence.data?.length === 0 && <p>无可靠依据，状态保留不确定性。</p>}
      {evidence.data?.map(item => { const url = citationUrl(item.source_locator.url); return <div className="evidence" key={item.id}>
        <div className="row"><span className="badge">{item.kind === 'CODE_ARTIFACT' ? '代码材料（未验证运行）' : item.kind === 'USER_CORRECTION' ? '用户自报' : '笔记提及（待验证）'}</span><time dateTime={item.observed_at}>{new Date(item.observed_at).toLocaleString()}</time></div>
        <blockquote>{item.excerpt}</blockquote><p className="muted compact">验证方式：{item.method === 'SOURCE_TEXT' ? '原文定位，仅表示内容存在' : item.method === 'FILE_TITLE' ? '文件名线索，内容深度尚未验证' : '用户陈述，尚未独立验证'} · 证据强度：{item.reliability === 'LOW' ? '低' : item.reliability}</p>
        {url ? <a href={url} target="_blank" rel="noopener noreferrer">{String(item.source_locator.path)} · 第 {String(item.source_locator.line_start)}–{String(item.source_locator.line_end)} 行 ↗</a> : <p className="muted">无外部引用，用户陈述尚未验证。</p>}
      </div>; })}
      <details><summary>纠正这条知识状态</summary><form className="stack" onSubmit={event => { event.preventDefault(); correct.mutate(); }}>
        <p className="muted">你的修正会保留理由并标记为用户自报，不会替代原始证据。</p>
        <label>状态<select value={level ?? ''} onChange={event => setLevel(event.target.value === '' ? null : event.target.value as CorrectionRequest['level'])}><option value="">恢复基于证据的判断</option>{Object.entries(levels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label>修正理由<textarea required minLength={3} maxLength={1000} value={reason} onChange={event => setReason(event.target.value)} /></label>
        <button disabled={correct.isPending}>保存修正</button>{correct.isError && <ErrorNotice error={correct.error} />}{correct.isSuccess && <p role="status">修正已保存，可随时复查。</p>}
      </form></details>
    </article>}
  </section>;
}
