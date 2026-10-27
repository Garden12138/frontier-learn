import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ErrorNotice } from '@frontier/shared';
import type { ApiClient, PlanAction, PlanResponse, PlanTask } from '@frontier/shared';

const taskStatuses = { PROPOSED: '建议任务', ACCEPTED: '已采纳', PAUSED: '已暂停', SKIPPED: '已跳过（未证明掌握）', COMPLETED: '任务已完成（不等于通过验证）' };

function safeLink(value: string | null | undefined): string | null {
  try { const url = new URL(value ?? ''); return url.protocol === 'https:' && !url.username && !url.password ? url.href : null; } catch { return null; }
}

function TaskCard({ task, plan, busy, onAction, move, onOpenConversation }: { task: PlanTask; plan: PlanResponse; busy: boolean; onAction: (action: Omit<PlanAction, 'revision_no'>) => void; move?: (direction: number) => void; onOpenConversation?: ((id: string, candidateId?: string) => void) | undefined }) {
  const sourceById = new Map(plan.sources.map(source => [source.evidence_id, source]));
  const material = safeLink(task.material_url);
  return <article className="card stack learning-task" aria-label={`任务 ${task.title}`}>
    <div className="row"><span className="badge">{taskStatuses[task.status]}</span><span className="muted compact">建议投入 {task.estimated_minutes} 分钟</span></div>
    <h3>{task.title}</h3><p>{task.instruction}</p><p className="muted compact">为什么推荐：{task.why}</p>
    <p className="muted compact">先修方向：{task.prerequisite_topics.length ? `${task.prerequisite_topics.join('、')}（用户指定，未独立验证）` : '尚未确认具体技术先修，不预设你已经掌握'}</p>
    {task.prerequisite_ids.length > 0 && <p className="muted compact">建议先完成或主动跳过前面的步骤；跳过会保留不确定性。</p>}
    <div className="provenance"><strong>推荐依据</strong>{task.evidence_ids.length === 0 && <p className="muted compact">你的目标 / 自报与本地规则建议；无外部事实依据。</p>}{task.evidence_ids.map(id => { const source = sourceById.get(id); const url = safeLink(source?.url); return <p key={id} className="muted compact">{source?.label ?? '原证据不可用'}{source?.kind && ` · ${source.kind}`}{source?.observed_at && ` · ${new Date(source.observed_at).toLocaleDateString('zh-CN')}`} {url && <a href={url} target="_blank" rel="noopener noreferrer">查看原文依据 ↗</a>}</p>; })}</div>
    {material && <p><a href={material} target="_blank" rel="noopener noreferrer">打开用户提供的材料（未验证） ↗</a></p>}
    {task.conversation_ref && onOpenConversation && <div><p className="muted compact">引用的是待验证对话材料；原材料删除后不再显示原文。</p><button className="secondary" onClick={() => onOpenConversation(task.conversation_ref!.import_id, task.conversation_ref!.candidate_id)}>打开关联对话问题</button></div>}
    <div className="actions">{task.status !== 'COMPLETED' && <>
      {task.status === 'PROPOSED' && <button className="secondary" disabled={busy} onClick={() => onAction({ action: 'ACCEPT', task_id: task.id })}>采纳任务</button>}
      {['PROPOSED', 'ACCEPTED'].includes(task.status) && <><button disabled={busy || plan.status === 'PAUSED'} onClick={() => onAction({ action: 'COMPLETE', task_id: task.id })}>标记任务完成</button><button className="secondary" disabled={busy} onClick={() => onAction({ action: 'PAUSE', task_id: task.id })}>暂停任务</button><button className="secondary" disabled={busy} onClick={() => onAction({ action: 'SKIP', task_id: task.id })}>跳过任务</button></>}
      {['PAUSED', 'SKIPPED'].includes(task.status) && <button disabled={busy} onClick={() => onAction({ action: 'RESUME', task_id: task.id })}>恢复任务</button>}
    </>}{move && <><button className="secondary" disabled={busy} onClick={() => move(-1)}>向前调整</button><button className="secondary" disabled={busy} onClick={() => move(1)}>向后调整</button></>}</div>
  </article>;
}

export function Today({ api, userId, selectedGoalId, onSelectGoal, onManageGoals, onOpenConversation }: { api: ApiClient; userId: string; selectedGoalId: string | null; onSelectGoal: (id: string) => void; onManageGoals: () => void; onOpenConversation?: ((id: string, candidateId?: string) => void) | undefined }) {
  const client = useQueryClient();
  const goals = useQuery({ queryKey: ['user', userId, 'goals'], queryFn: ({ signal }) => api.goals(signal) });
  const goal = goals.data?.find(item => item.id === selectedGoalId) ?? goals.data?.find(item => item.status === 'ACTIVE') ?? goals.data?.[0];
  const plans = useQuery({ queryKey: ['user', userId, 'plans', goal?.id], queryFn: ({ signal }) => api.plans(goal!.id, signal), enabled: !!goal });
  const plan = plans.data?.[0];
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [viewingRevision, setViewingRevision] = useState<number | null>(null);
  const [interestTitle, setInterestTitle] = useState('');
  const [interestMinutes, setInterestMinutes] = useState(5);
  const [interestUrl, setInterestUrl] = useState('');
  const history = useQuery({ queryKey: ['user', userId, 'plan-history', plan?.id, historyOffset], queryFn: () => api.planHistory(plan!.id, historyOffset), enabled: !!plan && historyOpen });
  const revision = useQuery({ queryKey: ['user', userId, 'plan-revision', plan?.id, viewingRevision], queryFn: () => api.planRevision(plan!.id, viewingRevision!), enabled: !!plan && viewingRevision !== null });
  const refresh = () => client.invalidateQueries({ queryKey: ['user', userId] });
  const generate = useMutation({ mutationFn: () => api.generatePlan(goal!, plan?.revision_no ?? 0), onSuccess: refresh });
  const act = useMutation({ mutationFn: (body: Omit<PlanAction, 'revision_no'>) => api.planAction(plan!.id, { ...body, revision_no: plan!.revision_no }), onSuccess: async (_, body) => { if (body.action === 'INSERT') { setInterestTitle(''); setInterestUrl(''); } await refresh(); } });
  const move = (task: PlanTask, direction: number) => {
    if (!plan) return;
    const ids = plan.tasks.map(item => item.id);
    const index = ids.indexOf(task.id);
    const target = index + direction;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target]!, ids[index]!];
    act.mutate({ action: 'REORDER', ordered_task_ids: ids });
  };
  return <section className="stack" aria-labelledby="today-title">
    <div><span className="eyebrow">一步一步，验证理解</span><h1 id="today-title">今日学习</h1><p className="muted">以目标、个人证据和最近验证为起点。每次建议都保留依据，任务完成不会自动提升能力状态。</p></div>
    {goals.isPending && <p role="status">正在加载学习目标…</p>}{goals.isError && <ErrorNotice error={goals.error} onRetry={() => void goals.refetch()} />}
    {goals.data?.length === 0 && <div className="card stack"><h2>先选一个想学会的目标</h2><p className="muted">没有知识库也可以开始。你可以暂不自评，系统会保留未知并建议第一步。</p><button onClick={onManageGoals}>设定学习目标</button></div>}
    {goal && <>
      <div className="row"><label className="grow">当前目标<select value={goal.id} onChange={event => { onSelectGoal(event.target.value); setViewingRevision(null); setHistoryOpen(false); }}>{goals.data?.map(item => <option value={item.id} key={item.id}>{item.title}</option>)}</select></label><button className="secondary" onClick={onManageGoals}>管理目标</button></div>
      <p className="muted compact">当前目标：每日 {goal.minutes_per_day} 分钟 · {goal.timezone}{goal.status === 'PAUSED' ? ' · 目标已暂停' : ''}</p>
      {plans.isPending && <p role="status">正在加载学习计划…</p>}{plans.isError && <ErrorNotice error={plans.error} onRetry={() => void plans.refetch()} />}
      {plans.isSuccess && !plan && <div className="card stack"><h2>安排下一步</h2><p className="muted">会读取与当前目标相关的个人证据，保留不确定性；没有证据时仍能规划。</p><button disabled={generate.isPending || goal.status !== 'ACTIVE'} onClick={() => generate.mutate()}>{generate.isPending ? '正在规划…' : '生成学习计划'}</button></div>}
    </>}
    {generate.isError && <ErrorNotice error={generate.error} onRetry={() => generate.mutate()} />}
    {plan && <>
      <div className="card stack"><div className="row"><h2>当前计划 · 版本 {plan.revision_no}</h2><span className="badge">{plan.status === 'PAUSED' ? '已暂停' : plan.status === 'ACTIVE' ? '已采纳' : '待采纳'}</span></div><p className="muted compact">{plan.uncertainty}</p>{plan.goal_changed && <p role="alert">目标已修改，这份计划仍基于旧版本。请重新规划以更新路线。</p>}<p className="muted compact">今日完成任务的建议投入合计：{plan.today_completed_minutes} 分钟（非计时）；当前目标剩余建议预算 {plan.today_remaining_minutes} 分钟。</p><div className="actions">{plan.status === 'PROPOSED' && <button disabled={act.isPending} onClick={() => act.mutate({ action: 'ACCEPT' })}>采纳整个计划</button>}<button className="secondary" disabled={act.isPending} onClick={() => act.mutate({ action: plan.status === 'PAUSED' ? 'RESUME' : 'PAUSE' })}>{plan.status === 'PAUSED' ? '恢复计划' : '暂停计划'}</button><button className="secondary" disabled={generate.isPending || act.isPending || goal?.status !== 'ACTIVE'} onClick={() => generate.mutate()}>根据最新证据重新规划</button><button className="secondary" onClick={() => setHistoryOpen(!historyOpen)}>查看计划历史</button><button className="secondary" onClick={() => void refresh()}>刷新计划</button></div></div>
      <h2>今天可以做什么</h2>
      {plan.today_task_ids.length === 0 && <div className="card muted">当前没有可安排的任务。可能是计划已暂停、今日建议预算已用完，或前面的任务需要先处理；可以查看阶段任务、恢复任务或调整目标。</div>}
      {plan.tasks.filter(task => plan.today_task_ids.includes(task.id)).map(task => <TaskCard key={task.id} task={task} plan={plan} busy={act.isPending} onOpenConversation={onOpenConversation} onAction={body => act.mutate(body)} />)}
      {act.isError && <ErrorNotice error={act.error} onRetry={() => void refresh()} />}
      <details className="card"><summary>长期方向与阶段任务</summary><div className="stack"><h2>长期方向</h2>{plan.roadmap.map(theme => <div className="route-theme" key={theme.topic}><h3>{theme.topic}</h3><p>{theme.why}</p><p className="muted compact">先修方向：{theme.prerequisite_topics.join('、') || '未指定，保持不确定性'} · 当前步骤建议投入合计 {theme.estimated_minutes} 分钟，可分多日完成。</p></div>)}<h2>阶段安排</h2>{plan.stages.map(stage => <p key={stage.title}><strong>{stage.title}</strong> · 建议投入 {stage.estimated_minutes} 分钟<br /><span className="muted compact">{stage.why}</span></p>)}<h2>全部任务</h2>{plan.tasks.map(task => <TaskCard key={task.id} task={task} plan={plan} busy={act.isPending} onOpenConversation={onOpenConversation} onAction={body => act.mutate(body)} move={direction => move(task, direction)} />)}</div></details>
      <details className="card"><summary>插入临时兴趣内容</summary><form className="stack" onSubmit={event => { event.preventDefault(); act.mutate({ action: 'INSERT', interest: { title: interestTitle, estimated_minutes: interestMinutes, material_url: interestUrl.trim() || null } }); }}><p className="muted compact">可以插入任何学习主题，材料由你选择，结论尚未核实。完成或跳过后，重新规划会把它保留在历史中。</p><label>兴趣内容<input required maxLength={500} value={interestTitle} onChange={event => setInterestTitle(event.target.value)} /></label><label>建议投入分钟<input required type="number" min={5} max={Math.min(goal?.minutes_per_day ?? 5, plan.goal_snapshot.minutes_per_day)} value={interestMinutes} onChange={event => setInterestMinutes(Number(event.target.value))} /></label><label>材料链接（可选，HTTPS）<input type="url" maxLength={2048} value={interestUrl} onChange={event => setInterestUrl(event.target.value)} /></label><button disabled={act.isPending}>插入计划</button></form></details>
      {historyOpen && <section className="card stack" aria-label="计划修订历史"><h2>计划修订历史</h2><p className="muted compact">恢复会追加一份新修订，保留已有版本与完成记录。</p>{history.isPending && <p role="status">正在加载历史…</p>}{history.isError && <ErrorNotice error={history.error} onRetry={() => void history.refetch()} />}{history.data?.map(item => <div key={item.revision_no} className="row"><span>版本 {item.revision_no} · {new Date(item.created_at).toLocaleString('zh-CN')}<br /><small>{item.rationale}</small></span><div className="actions"><button className="secondary" onClick={() => setViewingRevision(item.revision_no)}>查看版本 {item.revision_no}</button><button className="secondary" disabled={act.isPending} onClick={() => act.mutate({ action: 'RESTORE', restore_revision_no: item.revision_no })}>恢复版本 {item.revision_no}（追加修订）</button></div></div>)}<div className="actions"><button className="secondary" disabled={!historyOffset} onClick={() => setHistoryOffset(Math.max(0, historyOffset - 50))}>较新修订</button><button className="secondary" disabled={!history.data || history.data.length < 50} onClick={() => setHistoryOffset(historyOffset + 50)}>较早修订</button></div>{revision.isPending && viewingRevision !== null && <p role="status">正在加载历史版本…</p>}{revision.isError && <ErrorNotice error={revision.error} />}{revision.data && viewingRevision !== null && <div className="revision-preview"><h3>历史版本 {revision.data.revision_no}（只读）</h3><p>{revision.data.rationale}</p>{revision.data.tasks.map(task => <p key={task.id}>{task.title} · {taskStatuses[task.status]}</p>)}</div>}</section>}
    </>}
  </section>;
}
