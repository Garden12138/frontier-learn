import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ErrorNotice } from '@frontier/shared';
import type { ApiClient, GoalInput, GoalResponse } from '@frontier/shared';

const levels: Record<NonNullable<GoalInput['self_report']>, string> = { UNKNOWN: '暂不自评，保持未知', EXPOSED: '接触过一些材料', UNDERSTANDING: '自认为能够解释', APPLIED: '自认为做过实践', PROFICIENT: '自认为熟悉多种场景' };
const directions = (value: string) => value.split(/[,，]/).map(item => item.trim()).filter(Boolean);

function GoalForm({ api, goal, onSaved, onCancel }: { api: ApiClient; goal?: GoalResponse; onSaved: (goal: GoalResponse) => void; onCancel?: () => void }) {
  const [title, setTitle] = useState(goal?.title ?? '');
  const [minutes, setMinutes] = useState(goal?.minutes_per_day ?? 30);
  const [priorities, setPriorities] = useState(goal?.priorities?.join(', ') ?? '');
  const [baseline, setBaseline] = useState<NonNullable<GoalInput['self_report']>>(goal?.self_report ?? 'UNKNOWN');
  const [reason, setReason] = useState(goal?.self_report_reason ?? '');
  const [timezone, setTimezone] = useState(goal?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone);
  const [status, setStatus] = useState<'ACTIVE' | 'PAUSED'>(goal?.status ?? 'ACTIVE');
  const [edges, setEdges] = useState<NonNullable<GoalInput['prerequisite_edges']>>(goal?.prerequisite_edges ?? []);
  const [before, setBefore] = useState('');
  const [after, setAfter] = useState('');
  const creation = useRef({ payload: '', key: '' });
  const topics = directions(priorities);
  const save = useMutation({ mutationFn: async () => {
    const body: GoalInput = { title, minutes_per_day: minutes, priorities: topics, self_report: baseline, self_report_reason: baseline === 'UNKNOWN' ? '' : reason, timezone, status, prerequisite_edges: edges };
    if (goal) return api.updateGoal(goal.id, { ...body, version: goal.version });
    const payload = JSON.stringify(body);
    if (creation.current.payload !== payload) creation.current = { payload, key: crypto.randomUUID() };
    return api.createGoal(body, creation.current.key);
  }, onSuccess: onSaved });
  return <form className="card stack" onSubmit={event => { event.preventDefault(); save.mutate(); }}>
    <h2>{goal ? '编辑学习目标' : '设定一个学习目标'}</h2>
    <label>想学会什么<input required maxLength={500} value={title} onChange={event => setTitle(event.target.value)} placeholder="例如：理解记忆与检索，或学会照料植物" /></label>
    <div className="form-grid"><label>当前目标每日可用时间（分钟）<input type="number" required min={5} max={240} value={minutes} onChange={event => setMinutes(Number(event.target.value))} /></label><label>优先方向（可选，逗号分隔，最多 8 项）<input maxLength={1000} value={priorities} onChange={event => setPriorities(event.target.value)} placeholder="例如：土壤, 浇水" /></label></div>
    <label>我的学习起点（可选）<select value={baseline} onChange={event => setBaseline(event.target.value as NonNullable<GoalInput['self_report']>)}>{Object.entries(levels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    <p className="muted compact">可以跳过自评，知识状态会保留未知。自报仅帮助安排起点，不证明已经掌握，也不需要先连接 GitHub。</p>
    {baseline !== 'UNKNOWN' && <label>自报依据<textarea required minLength={3} maxLength={1000} value={reason} onChange={event => setReason(event.target.value)} placeholder="写下能说明起点的具体例子；之后仍需验证。" /></label>}
    <details><summary>时间与先修方向</summary><div className="stack">
      <label>日计划使用的时区<input required maxLength={64} value={timezone} onChange={event => setTimezone(event.target.value)} list="timezones" /></label><datalist id="timezones"><option value="Asia/Shanghai" /><option value="UTC" /><option value="America/New_York" /><option value="Europe/London" /></datalist>
      <label>目标状态<select value={status} onChange={event => setStatus(event.target.value as 'ACTIVE' | 'PAUSED')}><option value="ACTIVE">进行中</option><option value="PAUSED">暂停</option></select></label>
      <p className="muted compact">如果你已明确希望先学某个方向，可以记录顺序。这里只记录你的指定，不当作已经验证的技术先修关系；关系只能引用已有方向且不能形成循环。</p>
      {topics.length >= 2 && <div className="actions"><label>先学<select value={before} onChange={event => setBefore(event.target.value)}><option value="">选择方向</option>{topics.map(topic => <option key={topic}>{topic}</option>)}</select></label><label>再学<select value={after} onChange={event => setAfter(event.target.value)}><option value="">选择方向</option>{topics.map(topic => <option key={topic}>{topic}</option>)}</select></label><button type="button" className="secondary" disabled={!before || !after || before === after || edges.length >= 16} onClick={() => { setEdges([...edges, { topic: after, prerequisite: before }]); setBefore(''); setAfter(''); }}>添加顺序</button></div>}
      {edges.map((edge, index) => <div className="row" key={`${edge.topic}-${edge.prerequisite}-${index}`}><span>{edge.prerequisite} → {edge.topic}（用户指定）</span><button type="button" className="secondary" onClick={() => setEdges(edges.filter((_, item) => item !== index))}>移除关联</button></div>)}
    </div></details>
    <div className="actions"><button disabled={save.isPending}>{save.isPending ? '正在保存…' : goal ? '保存目标' : '创建目标'}</button>{onCancel && <button type="button" className="secondary" onClick={onCancel}>取消编辑</button>}</div>
    {save.isError && <ErrorNotice error={save.error} onRetry={() => save.mutate()} />}
  </form>;
}

export function Goals({ api, userId, onOpenPlan }: { api: ApiClient; userId: string; onOpenPlan: (goalId: string) => void }) {
  const client = useQueryClient();
  const [editing, setEditing] = useState<GoalResponse | null>(null);
  const [deleting, setDeleting] = useState<GoalResponse | null>(null);
  const [formVersion, setFormVersion] = useState(0);
  const goals = useQuery({ queryKey: ['user', userId, 'goals'], queryFn: ({ signal }) => api.goals(signal) });
  const remove = useMutation({ mutationFn: () => api.deleteGoal(deleting!.id), onSuccess: async () => { setDeleting(null); setEditing(null); await client.invalidateQueries({ queryKey: ['user', userId] }); } });
  const saved = async (goal: GoalResponse) => { setEditing(null); setFormVersion(value => value + 1); await client.invalidateQueries({ queryKey: ['user', userId] }); onOpenPlan(goal.id); };
  return <section className="stack" aria-labelledby="goals-title">
    <div><span className="eyebrow">从目标开始</span><h1 id="goals-title">目标与学习方向</h1><p className="muted">先说清想学什么，再结合已有证据安排下一步。没有知识库，也可以开始。</p></div>
    {editing ? <GoalForm key={editing.id} api={api} goal={editing} onSaved={goal => void saved(goal)} onCancel={() => setEditing(null)} /> : <GoalForm key={formVersion} api={api} onSaved={goal => void saved(goal)} />}
    {goals.isPending && <p role="status">正在加载目标…</p>}
    {goals.isError && <ErrorNotice error={goals.error} onRetry={() => void goals.refetch()} />}
    {goals.data?.length === 0 && <p className="muted">还没有目标。用上面的表单创建第一个，暂不自评也可以。</p>}
    {goals.data?.map(goal => <article className="card stack" key={goal.id} aria-label={`目标 ${goal.title}`}><div className="row"><h2>{goal.title}</h2><span className="badge">{goal.status === 'ACTIVE' ? '进行中' : '已暂停'}</span></div><p className="muted compact">当前目标每天 {goal.minutes_per_day} 分钟 · {goal.timezone} · 目标版本 {goal.version}</p><p>{goal.priorities?.length ? goal.priorities.join(' / ') : '以目标整体作为学习方向'}</p><p className="muted compact">起点：{levels[goal.self_report ?? 'UNKNOWN']}。{goal.self_report !== 'UNKNOWN' ? '仅为自报，尚未独立验证。' : ''}</p><div className="actions"><button onClick={() => onOpenPlan(goal.id)}>查看 / 生成计划</button><button className="secondary" onClick={() => setEditing(goal)}>编辑目标</button><button className="secondary" onClick={() => { setDeleting(goal); remove.reset(); }}>删除目标</button></div></article>)}
    {deleting && <div className="card stack confirmation" role="dialog" aria-labelledby="delete-goal-title" aria-modal="true"><h2 id="delete-goal-title">删除「{deleting.title}」</h2><p>会删除这个目标、计划历史和任务进度。独立的知识来源与学习证据会保留，不会修改外部仓库。</p><div className="actions"><button disabled={remove.isPending} onClick={() => remove.mutate()}>确认删除目标</button><button className="secondary" onClick={() => setDeleting(null)}>取消</button></div>{remove.isError && <ErrorNotice error={remove.error} />}</div>}
  </section>;
}
