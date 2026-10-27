import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ErrorNotice } from '@frontier/shared';
import type { ApiClient } from '@frontier/shared';

export function Settings({ api, userId, onDeleted }: { api: ApiClient; userId: string; onDeleted: () => void }) {
  const cache = useQueryClient();
  const settings = useQuery({ queryKey: ['user', userId, 'settings'], queryFn: () => api.settings() });
  const sources = useQuery({ queryKey: ['user', userId, 'sources'], queryFn: () => api.sources() });
  const jobs = useQuery({ queryKey: ['user', userId, 'jobs'], queryFn: () => api.jobs(), refetchInterval: query => query.state.data?.some(job => ['PENDING', 'RUNNING'].includes(job.status)) ? 1000 : false });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [confirmation, setConfirmation] = useState('');
  const [removing, setRemoving] = useState<string | null>(null);
  const [deleteDerived, setDeleteDerived] = useState(false);
  async function act(operation: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await operation(); await cache.invalidateQueries({ queryKey: ['user', userId] }); }
    catch (value) { setError(value); } finally { setBusy(false); }
  }
  return <><section className="page-heading"><h1>设置与数据</h1><p>你可以控制内容处理授权、连接和应用内保存的记录。</p></section>
    <section className="card stack"><h2>模型内容处理</h2>
      {settings.isPending && <p role="status">正在读取设置…</p>}
      {settings.isError && <ErrorNotice error={settings.error} onRetry={() => void settings.refetch()} />}
      {settings.data && <><p>{settings.data.cloud_provider_available ? `已配置 OpenAI 模型 ${settings.data.model}；${settings.data.cloud_processing_allowed ? '已允许最小片段处理' : '当前仍使用本地规则，授权后才调用模型'}。` : '当前使用本地规则，不发送内容到外部模型。此授权只适用于之后明确启用的云模型。'}</p><p>{settings.data.processing_scope}</p>{settings.data.cloud_provider_available && <p>今日模型调用 {settings.data.calls_used_today}/{settings.data.calls_limit}，保守预留 {settings.data.tokens_reserved_today}/{settings.data.tokens_limit} tokens。达到预算后使用本地阅读方法。</p>}<p>外部模型处理授权：{settings.data.cloud_processing_allowed ? '允许最小片段处理' : '未授权'}</p><button className="secondary" disabled={busy} onClick={() => void act(() => api.updateSettings(settings.data!, !settings.data!.cloud_processing_allowed))}>{settings.data.cloud_processing_allowed ? '撤销外部模型处理授权' : '同意最小片段用于外部模型处理'}</button></>}
    </section>
    <section className="card stack"><h2>知识来源权限</h2>
      {sources.isPending && <p role="status">正在读取连接…</p>}{sources.isError && <ErrorNotice error={sources.error} />}{sources.data?.length === 0 && <p>尚无来源连接，不影响设置目标与学习。</p>}
      {sources.data?.map(source => <div className="source-preview stack" key={source.id}><strong>{source.external_ref}</strong><p>{source.status} · 写入目录：{source.write_scope.join(', ') || '未授权'}</p><div className="actions"><button className="secondary" disabled={busy || source.status === 'DISCONNECTED'} onClick={() => void act(() => api.updateSource(source, source.status === 'PAUSED' ? 'CONNECTED' : 'PAUSED'))}>{source.status === 'PAUSED' ? '恢复同步' : '暂停同步'}</button>{source.write_scope.length > 0 && <button className="secondary" disabled={busy} onClick={() => void act(() => api.revokeWrite(source.id))}>撤销写入授权</button>}<button className="secondary" disabled={busy} onClick={() => { setRemoving(source.id); setDeleteDerived(false); }}>断开并选择清理范围</button></div></div>)}
      {removing && <div role="dialog" aria-modal="true" aria-label="确认断开来源" className="stack"><p>撤销连接凭据并取消后台任务。GitHub 中的文件和 PR 会保留。</p><label className="check"><input type="checkbox" checked={deleteDerived} onChange={event => setDeleteDerived(event.target.checked)} />同时删除此来源的应用内正文和派生证据，保留其他来源及独立短测。</label><button disabled={busy} onClick={() => void act(async () => { await api.disconnectSource(removing, deleteDerived); setRemoving(null); })}>确认断开来源</button><button className="secondary" onClick={() => setRemoving(null)}>取消</button></div>}
    </section>
    <section className="card stack"><h2>后台任务与预算</h2>
      {jobs.isError && <ErrorNotice error={jobs.error} />}{jobs.data?.length === 0 && <p>还没有后台任务。</p>}
      {jobs.data?.map(job => <article className="source-preview" key={job.id}><p>{job.kind} · {job.status} · 预算 {job.spent_units}/{job.budget_units} · 尝试 {job.attempt_count}/{job.max_attempts}</p>{job.error_code && <p>{job.error_code}</p>}{['PENDING', 'RUNNING'].includes(job.status) && <button className="secondary" disabled={busy} onClick={() => void act(() => api.cancelJob(job.id))}>取消任务</button>}{['FAILED', 'PARTIAL'].includes(job.status) && job.attempt_count < job.max_attempts && job.spent_units < job.budget_units && Date.parse(job.deadline_at) > Date.now() && <button disabled={busy} onClick={() => void act(() => api.retryJob(job.id))}>重试任务</button>}</article>)}
    </section>
    <section className="card stack"><h2>导出学习数据</h2><p>JSON 包含你的笔记草稿、来源正文、短测和计划历史，不含访问凭据；Markdown 可在笔记审核页逐份下载。下载后可离线使用。</p><button disabled={busy} onClick={() => void act(async () => { const data = await api.exportData(); const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })); const link = document.createElement('a'); link.href = url; link.download = 'frontier-learning-data.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); })}>下载我的学习记录 JSON</button></section>
    <section className="card stack"><h2>删除应用内全部数据</h2><p>清除当前账号、全部连接、材料、短测、证据和草稿，并退出登录。此操作无法撤销；外部 GitHub 文件、分支及 PR 会保留。建议先导出。</p><label>输入“删除我的数据”再次确认<input value={confirmation} onChange={event => setConfirmation(event.target.value)} autoComplete="off" /></label><button className="danger" disabled={busy || confirmation !== '删除我的数据'} onClick={() => void act(async () => { await api.deleteData(); onDeleted(); })}>永久删除我的应用内数据</button></section>
    {error !== null && <ErrorNotice error={error} />}
  </>;
}
