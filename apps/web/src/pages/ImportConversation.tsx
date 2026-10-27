import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ErrorNotice } from '@frontier/shared';
import type { ApiClient, CandidateDecision, ConversationResponse, ImportConversationRequest } from '@frontier/shared';

const statuses = { PENDING: '等待解析', RUNNING: '正在获取并解析…', SUCCEEDED: '解析完成', FAILED: '导入失败；原记录已保留', CANCELLED: '已取消导入', PARTIAL: '部分完成' };
const roles = { USER: '用户问题（材料标注）', ASSISTANT: 'AI 回答（未经核实）', UNKNOWN: '角色未识别' };
const failures: Record<string, string> = {
  SHARE_ACCESS_DENIED: '分享页限制访问。不会绕过登录或访问控制，可粘贴你能访问的内容。',
  SHARE_PARSE_FAILED: '没有找到可读取的公开对话。页面可能需要脚本或已改变，请手工粘贴。',
  SHARE_NOT_AVAILABLE: '分享页已失效或不存在，请手工粘贴。',
  SHARE_RATE_LIMITED: '分享页暂时限流，可稍后重试或改用粘贴。',
  UNSAFE_URL: '分享页的网络目标未通过安全检查，请手工粘贴。',
};

export function ImportConversation({ api, userId, initialId, initialCandidateId, onOpenKnowledge, onOpenPlan }: {
  api: ApiClient; userId: string; initialId: string | null; initialCandidateId: string | null;
  onOpenKnowledge: (name: string) => void; onOpenPlan: (goalId: string) => void;
}) {
  const cache = useQueryClient();
  const [source, setSource] = useState<'PASTED' | 'SHARE'>('PASTED');
  const [text, setText] = useState('');
  const [url, setUrl] = useState('');
  const [preview, setPreview] = useState<ImportConversationRequest | null>(null);
  const [consent, setConsent] = useState(false);
  const [selected, setSelected] = useState<string | null>(initialId);
  const [offset, setOffset] = useState(0);
  const [goalId, setGoalId] = useState('');
  const [minutes, setMinutes] = useState(5);
  const operation = useRef<{ encoded: string; key: string } | null>(null);
  const history = useQuery({ queryKey: ['user', userId, 'conversations', offset], queryFn: () => api.conversations(offset) });
  const detailKey = ['user', userId, 'conversation', selected];
  const detail = useQuery({ queryKey: detailKey, queryFn: () => api.conversation(selected!), enabled: selected !== null,
    refetchInterval: query => query.state.data && ['PENDING', 'RUNNING'].includes(query.state.data.job.status) ? 800 : false });
  const goals = useQuery({ queryKey: ['user', userId, 'goals'], queryFn: () => api.goals() });
  const goal = goals.data?.find(item => item.id === goalId);
  const plans = useQuery({ queryKey: ['user', userId, 'plans', goalId], queryFn: () => api.plans(goalId), enabled: !!goalId });
  const plan = plans.data?.[0];
  const refresh = () => cache.invalidateQueries({ queryKey: ['user', userId] });
  const create = useMutation({ mutationFn: async () => {
    if (!preview || !consent) throw new Error('请先预览并确认导入范围。');
    const encoded = JSON.stringify(preview);
    if (operation.current?.encoded !== encoded) operation.current = { encoded, key: crypto.randomUUID() };
    return api.importConversation(preview, operation.current.key);
  }, onSuccess: async value => {
    operation.current = null; setSelected(value.id); setPreview(null); setConsent(false); setText(''); setUrl('');
    cache.setQueryData(['user', userId, 'conversation', value.id], value);
    await refresh();
  } });
  const job = useMutation({ mutationFn: ({ id, action }: { id: string; action: 'retry' | 'cancel' }) => action === 'retry' ? api.retryJob(id) : api.cancelJob(id), onSuccess: refresh });
  const decide = useMutation({ mutationFn: ({ candidate, action }: { candidate: string; action: CandidateDecision['action'] }) => api.decideConversation(selected!, candidate, {
    expected_version: detail.data!.version, action, estimated_minutes: minutes,
    ...(action === 'ADD' ? { plan_id: plan!.id, expected_revision_no: plan!.revision_no, estimated_minutes: minutes } : {}),
  }), onSuccess: async value => { cache.setQueryData(detailKey, value); await refresh(); } });
  const remove = useMutation({ mutationFn: () => api.deleteConversation(selected!), onSuccess: async () => {
    cache.removeQueries({ queryKey: detailKey }); setSelected(null); await refresh();
  } });
  const row = detail.isError ? undefined : detail.data;
  const importStatus = row?.job.status;
  const importId = row?.id;
  useEffect(() => {
    if (importId && importStatus && !['PENDING', 'RUNNING'].includes(importStatus)) {
      void cache.invalidateQueries({ queryKey: ['user', userId, 'conversations'] });
    }
  }, [cache, userId, importId, importStatus]);
  useEffect(() => {
    if (importId && importStatus === 'SUCCEEDED' && initialCandidateId) {
      document.getElementById(`candidate-${importId}-${initialCandidateId}`)?.scrollIntoView({ block: 'center' });
    }
  }, [importId, importStatus, initialCandidateId]);
  const busy = job.isPending || decide.isPending || remove.isPending;
  const pending = row && ['PENDING', 'RUNNING'].includes(row.job.status);
  const retryable = row?.job.status === 'FAILED' && row.job.attempt_count < row.job.max_attempts && row.job.spent_units < row.job.budget_units && new Date(row.job.deadline_at).getTime() > Date.now();
  function locate(conversation: ConversationResponse, message: string, part: number) {
    document.getElementById(`conversation-${conversation.id}-${message}-${part}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
  return <section className="stack" aria-labelledby="conversation-title">
    <div><span className="eyebrow">从疑问开始验证</span><h1 id="conversation-title">导入对话</h1><p className="muted">把你能访问的分享对话或粘贴文本作为学习材料。AI 回答与代码未经核实，导入和加入计划均不证明掌握。</p></div>
    <section className="card stack" aria-label="对话导入表单"><h2>选择要学习的片段</h2>
      <form className="stack" onSubmit={event => { event.preventDefault(); setConsent(false); create.reset(); setPreview({ consent: true, ...(source === 'SHARE' ? { url: url.trim() } : { pasted_text: text }) }); }}>
        <label>材料方式<select aria-label="材料方式" value={source} onChange={event => { setSource(event.target.value as typeof source); setPreview(null); setConsent(false); }}><option value="PASTED">手工粘贴对话</option><option value="SHARE">公共 ChatGPT 分享链接</option></select></label>
        {source === 'PASTED' ? <><label>对话文本<textarea required minLength={20} maxLength={30000} rows={8} value={text} onChange={event => { setText(event.target.value); setPreview(null); setConsent(false); }} placeholder={'用户：我想理解的问题…\n助手：待核实的回答…'} /></label><p className="muted compact">用“用户：/ 助手：”或“User: / Assistant:”标注角色。代码放在代码围栏中；未识别角色会保留未知。</p></> : <label>分享链接<input required type="url" maxLength={2048} value={url} onChange={event => { setUrl(event.target.value); setPreview(null); setConsent(false); }} placeholder="https://chatgpt.com/share/…" /></label>}
        <p className="muted compact">请移除私人信息和密钥，只保留必要片段。当前不向外部模型发送材料，不读取你的其他对话或登录凭据。</p><button disabled={create.isPending}>预览导入范围</button>
      </form>
      {preview && <section className="source-preview stack" aria-label="提交前预览"><h3>确认这次导入</h3>{preview.pasted_text ? <pre className="conversation-text">{preview.pasted_text}</pre> : <p>{preview.url} · 仅尝试读取这个公开分享页；受限时保留错误并提供粘贴入口。</p>}
        <p>确认后会将这份材料保存到你的个人学习库，仅进行本地解析。可删除内部副本；不会删除外部分享页。</p>
        <label className="check"><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} />我已检查敏感信息，同意保存并解析上述范围。</label>
        <button disabled={!consent || create.isPending} onClick={() => create.mutate()}>{create.isPending ? '正在提交…' : '确认导入对话'}</button>
      </section>}{create.isError && <ErrorNotice error={create.error} />}
    </section>
    <section className="card stack" aria-label="对话导入历史"><h2>我的对话材料</h2>
      {history.isPending && <p role="status">正在加载导入历史…</p>}{history.isError && <ErrorNotice error={history.error} onRetry={() => void history.refetch()} />}
      {history.data?.length === 0 && <p>还没有导入材料。没有 GitHub 或学习计划也可以先整理问题。</p>}
      {history.data?.map(item => <button className="secondary" key={item.id} onClick={() => { setSelected(item.id); decide.reset(); job.reset(); remove.reset(); }}>{item.title} · {item.source === 'SHARE' ? '分享页' : '手工文本'} · {statuses[item.status]}</button>)}
      <div className="actions"><button className="secondary" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 30))}>上一页</button><button className="secondary" disabled={(history.data?.length ?? 0) < 30} onClick={() => setOffset(offset + 30)}>下一页</button><button className="secondary" onClick={() => void history.refetch()}>刷新历史</button></div>
    </section>
    {selected && detail.isPending && <p role="status">正在读取对话材料…</p>}
    {selected && detail.isError && <div className="card"><p>原材料已删除、不可访问或服务暂不可用；不会继续显示已删除的原文。</p><ErrorNotice error={detail.error} onRetry={() => void detail.refetch()} /></div>}
    {row && <section className="card stack" aria-label="对话材料详情">
      <h2>{row.document?.title ?? '正在处理导入材料'}</h2><p role="status">{statuses[row.job.status]}</p>
      {row.url && /^https:\/\/(?:chatgpt\.com|chat\.openai\.com)\/share\/[0-9a-f-]{36}$/.test(row.url) && <a href={row.url} target="_blank" rel="noopener noreferrer">打开原分享页（当前可访问性未验证）</a>}
      {row.job.status === 'FAILED' && <><p role="alert">{failures[row.job.error_code ?? ''] ?? '这份材料暂时无法导入，可在预算内重试，或重新粘贴必要片段。'}</p><p className="muted compact">错误：{row.job.error_code} · 已尝试 {row.job.attempt_count}/{row.job.max_attempts} 次。</p><button className="secondary" onClick={() => { setSource('PASTED'); setText(row.pasted_text ?? ''); setPreview(null); setConsent(false); }}> {row.source === 'PASTED' ? '编辑原始文本重新导入' : '改用手工粘贴'}</button></>}
      {pending && <button className="secondary" disabled={busy} onClick={() => job.mutate({ id: row.job.id, action: 'cancel' })}>取消这次导入</button>}
      {retryable && <button disabled={busy} onClick={() => job.mutate({ id: row.job.id, action: 'retry' })}>重试这次导入</button>}
      <button className="secondary" onClick={() => void detail.refetch()}>刷新材料</button>
      {row.document && <><p className="muted compact">角色与引用仅对应导入快照，不代表作者身份或独立事实核验。</p>{row.document.warnings.map((warning, index) => <p className="muted compact" key={index}>{warning}</p>)}
        {row.document.messages.map(message => <article className="source-preview stack" key={message.id}><h3>{roles[message.role]} · {message.id}</h3>{message.parts.map((part, index) => <div id={`conversation-${row.id}-${message.id}-${index}`} key={index}><span className="badge">{part.kind === 'CODE' ? '代码文本 · 未执行' : message.role === 'ASSISTANT' ? '未核实结论' : '材料原文'}</span><pre className="conversation-text">{part.text}</pre></div>)}</article>)}
        <section className="stack" aria-label="候选学习问题"><h2>可以继续验证的问题</h2><p className="muted compact">本地规则候选，仅指向材料中尚待核实的问题。你可以拒绝；没有计划时仍可先保存材料。</p>
          <label>加入哪个目标<select aria-label="加入哪个目标" value={goalId} onChange={event => setGoalId(event.target.value)}><option value="">暂不选择目标</option>{goals.data?.map(item => <option value={item.id} key={item.id}>{item.title}</option>)}</select></label>
          {goalId && plans.isPending && <p role="status">正在读取目标的计划…</p>}
          {(goals.isError || plans.isError) && <ErrorNotice error={goals.error ?? plans.error} />}
          {goalId && plans.isSuccess && !plan && <p>这个目标尚无计划。<button className="secondary" onClick={() => onOpenPlan(goalId)}>到今日学习生成计划</button></p>}
          {plan && <><p className="muted compact">目标计划当前版本 {plan.revision_no}；确认加入会追加修订。{plan.status === 'PAUSED' ? '计划已暂停，加入后保持暂停。' : ''}</p><label>建议投入分钟<input type="number" min={5} max={Math.min(goal?.minutes_per_day ?? 5, plan.goal_snapshot.minutes_per_day)} value={minutes} onChange={event => setMinutes(Number(event.target.value))} /></label><button className="secondary" onClick={() => onOpenPlan(goalId)}>查看目标计划</button></>}
          {row.candidates.map(candidate => <article className="source-preview stack" key={candidate.id} id={`candidate-${row.id}-${candidate.id}`} aria-label="候选问题"><h3>{candidate.question}</h3><blockquote>{candidate.quote}</blockquote><button className="secondary" onClick={() => locate(row, candidate.message_id, candidate.part_index)}>定位材料 {candidate.message_id}</button>
            {candidate.related.length ? candidate.related.map(item => <button key={item.concept_id} className="secondary" onClick={() => onOpenKnowledge(item.name)}>相关知识线索：{item.name}（{item.override_level ? '用户修正，未验证' : '查看原有证据'}）</button>) : <p className="muted compact">尚无匹配的个人知识线索；不能据此推断已掌握。</p>}
            {candidate.status === 'PROPOSED' ? <div className="actions"><button disabled={busy || !plan || !Number.isInteger(minutes) || minutes < 5 || minutes > Math.min(goal?.minutes_per_day ?? 5, plan?.goal_snapshot.minutes_per_day ?? 5)} onClick={() => decide.mutate({ candidate: candidate.id, action: 'ADD' })}>确认加入计划</button><button className="secondary" disabled={busy} onClick={() => decide.mutate({ candidate: candidate.id, action: 'DISMISS' })}>不加入这个问题</button></div> : <p role="status">{candidate.status === 'ADDED' ? '已加入计划；任务完成不代表掌握' : '已拒绝；计划保持原样'}</p>}
          </article>)}
        </section></>}
      {job.isError && <ErrorNotice error={job.error} />}{decide.isError && <ErrorNotice error={decide.error} onRetry={() => void refresh()} />}
      <details><summary>删除这份对话材料</summary><p>删除内部原文、候选问题和导入任务。已加入计划的任务保留，原材料将显示不可用；外部分享页不受影响。</p><button className="danger" disabled={busy} onClick={() => remove.mutate()}>确认删除材料</button>{remove.isError && <ErrorNotice error={remove.error} />}</details>
    </section>}
  </section>;
}
