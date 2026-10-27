import { useEffect, useRef, useState } from 'react';
import { ErrorNotice, GuideSession } from '@frontier/shared';
import type { AnalyzePageRequest, ApiClient, GoalResponse, PlanTask, SessionResponse, SettingsResponse } from '@frontier/shared';
import type { PageSnapshot } from '../../adapters';

export function ConnectedGuide({ api, snapshot, mode, onLocate }: {
  api: ApiClient; snapshot: PageSnapshot; mode: AnalyzePageRequest['mode'];
  onLocate: (selector: string, quote: string) => Promise<void>;
}) {
  const [goals, setGoals] = useState<GoalResponse[]>([]);
  const [goalId, setGoalId] = useState('');
  const [tasks, setTasks] = useState<PlanTask[]>([]);
  const [taskId, setTaskId] = useState('');
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [consent, setConsent] = useState(false);
  const [cloudConsent, setCloudConsent] = useState(false);
  const [processing, setProcessing] = useState<SettingsResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const request = useRef<{ encoded: string; key: string } | null>(null);
  useEffect(() => { let active = true; void api.settings().then(value => { if (active) setProcessing(value); }).catch(value => { if (active) setError(value); }); return () => { active = false; }; }, [api]);
  useEffect(() => { let active = true; void api.goals().then(value => { if (active) setGoals(value); }).catch(value => { if (active) setError(value); }); return () => { active = false; }; }, [api]);
  useEffect(() => {
    let active = true; setTasks([]); setTaskId('');
    if (goalId) void api.plans(goalId).then(value => { if (active) setTasks(value.flatMap(plan => plan.tasks)); }).catch(value => { if (active) setError(value); });
    return () => { active = false; };
  }, [api, goalId]);
  if (session) return <GuideSession key={session.id} api={api} session={session} onChange={setSession} onLocate={onLocate} />;
  return <section className="card stack" aria-label="保存并开启导学"><h2>让这一页接上你的学习目标</h2>
    <form className="stack" onSubmit={event => {
      event.preventDefault(); setBusy(true); setError(null);
      const body: AnalyzePageRequest = { page: snapshot, goal_id: goalId || null, task_id: taskId || null, mode, consent: true, cloud_processing_allowed: cloudConsent && processing?.active_provider === 'OPENAI_RESPONSES' };
      const encoded = JSON.stringify(body);
      if (request.current?.encoded !== encoded) request.current = { encoded, key: crypto.randomUUID() };
      void api.analyzePage(body, request.current.key).then(setSession).catch(setError).finally(() => setBusy(false));
    }}>
      <label>关联学习目标<select aria-label="关联学习目标" value={goalId} onChange={event => setGoalId(event.target.value)}><option value="">暂不关联目标</option>{goals.map(goal => <option key={goal.id} value={goal.id}>{goal.title}</option>)}</select></label>
      {goalId && <label>关联当前计划任务<select aria-label="关联当前计划任务" value={taskId} onChange={event => setTaskId(event.target.value)}><option value="">暂不关联任务</option>{tasks.map(task => <option key={task.id} value={task.id}>{task.title}</option>)}</select></label>}
      <label className="checkbox-label"><input required type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} />我确认预览范围，同意将这些材料保存到学习服务，用于本次导学和跨端历史。</label>
      <p className="muted compact">请移除私人信息与密钥。默认只使用本地阅读方法，可在会话中删除保存内容。</p>
      {processing?.cloud_provider_available && processing.cloud_processing_allowed && <label className="checkbox-label"><input type="checkbox" checked={cloudConsent} onChange={event => setCloudConsent(event.target.checked)} />允许本次导学将最小片段发送给外部 OpenAI 模型 {processing.model}；不勾选时仅用本地规则。</label>}
      <button disabled={!consent || busy}>{busy ? '正在保存材料…' : '保存并开启导学'}</button>
    </form>{error !== null && <ErrorNotice error={error} />}
  </section>;
}
