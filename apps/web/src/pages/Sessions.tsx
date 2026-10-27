import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ErrorNotice, GuideSession } from '@frontier/shared';
import type { ApiClient, SessionResponse } from '@frontier/shared';

export function Sessions({ api, userId }: { api: ApiClient; userId: string }) {
  const [selected, setSelected] = useState<SessionResponse | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<unknown>(null);
  const history = useQuery({ queryKey: ['user', userId, 'sessions', offset], queryFn: () => api.sessions(offset) });
  const goals = useQuery({ queryKey: ['user', userId, 'goals'], queryFn: () => api.goals() });
  const goal = goals.data?.find(item => item.id === selected?.goal_id);
  const plans = useQuery({ queryKey: ['user', userId, 'plans', goal?.id], queryFn: () => api.plans(goal!.id), enabled: !!goal });
  const task = plans.data?.flatMap(plan => plan.tasks).find(item => item.id === selected?.task_id);
  return <>
    <section className="page-heading"><span className="eyebrow">Learning history</span><h1>导学会话</h1><p className="muted">在插件确认保存的材料和追问，可以在这里继续。会话和阅读记录不代表掌握。</p></section>
    <section className="card stack"><h2>学习历史</h2>
      {history.isPending && <p role="status">正在读取会话…</p>}
      {history.isError && <ErrorNotice error={history.error} onRetry={() => void history.refetch()} />}
      {history.data?.length === 0 && <p>还没有保存的导学会话。在插件分析当前页，预览后确认保存即可开始。</p>}
      {history.data?.map(item => <button className="secondary" key={item.id} onClick={() => { setError(null); void api.session(item.id).then(setSelected).catch(setError); }}>{item.title} · {new Date(item.created_at).toLocaleDateString()} · v{item.version}</button>)}
      <div className="actions"><button className="secondary" disabled={offset === 0} onClick={() => setOffset(value => Math.max(0, value - 30))}>上一页</button><button className="secondary" disabled={(history.data?.length ?? 0) < 30} onClick={() => setOffset(value => value + 30)}>下一页</button><button className="secondary" onClick={() => void history.refetch()}>刷新历史</button></div>
    </section>
    {error !== null && <ErrorNotice error={error} />}
    {selected && <><section className="card"><h2>当前学习任务</h2><p>{goal ? `学习目标：${goal.title}` : '本次未关联目标，仍可继续学习。'}</p><p>{task ? task.title : selected.task_id ? '关联任务不在当前计划中，历史关联仍保留；不会自动完成当前任务。' : '未关联当前计划任务；不会自动完成任务或更改画像。'}</p></section><GuideSession key={selected.id} api={api} session={selected} onChange={setSelected} /></>}
  </>;
}
