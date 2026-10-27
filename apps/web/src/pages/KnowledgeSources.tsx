import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { GitHubConnect, GitHubWriteAccess } from './GitHubConnect';
import { ApiError, ErrorNotice } from '@frontier/shared';
import type { ApiClient, SourceResponse } from '@frontier/shared';

const statusLabels: Record<string, string> = { PENDING: '等待同步', RUNNING: '正在同步', PARTIAL: '部分文件失败', SUCCEEDED: '同步完成', FAILED: '同步失败', CANCELLED: '已取消', CONNECTED: '只读连接', PAUSED: '已暂停', DISCONNECTED: '已断开', REAUTH_REQUIRED: '需要重新授权' };
const errorLabels: Record<string, string> = {
  GITHUB_REAUTHORIZE: 'GitHub 授权已失效或范围不足，请在上方重新连接。',
  GITHUB_INSTALLATION_CHANGED: 'App 安装范围已变化，请重新选择仓库。',
  GITHUB_APP_UNAVAILABLE: 'GitHub 暂不可用，可稍后重试。',
  GITHUB_ACCESS_DENIED: '仓库不可访问或授权失效，请重新授权或选择公开仓库。',
  GITHUB_RATE_LIMIT: 'GitHub 请求额度不足，请等待恢复后重试。',
  EMPTY_REPOSITORY: '仓库尚无提交，请添加笔记后重试。',
  SOURCE_UNAVAILABLE: '来源暂不可用，请检查连接后重试。',
  FILES_FAILED: '部分文件未能解析，成功文件的证据已保留。展开文件范围查看原因。',
  UNSUPPORTED_ENCODING: '文件不是 UTF-8 文本', FILE_TOO_LARGE: '文件超过大小限制',
  DUPLICATE_CONTENT: '内容重复，保留一个证据来源', BINARY_CONTENT: '包含二进制内容',
  JOB_TIMEOUT: '同步超时，已完成的文件会保留；重试会跳过成功文件。',
};

export function KnowledgeSources({ api, userId }: { api: ApiClient; userId: string }) {
  const client = useQueryClient();
  const [repository, setRepository] = useState('');
  const [folders, setFolders] = useState('');
  const [scopeEdits, setScopeEdits] = useState<Record<string, string>>({});
  const [consent, setConsent] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [disconnecting, setDisconnecting] = useState<SourceResponse | null>(null);
  const [deleteDerived, setDeleteDerived] = useState(false);
  const sources = useQuery({ queryKey: ['user', userId, 'sources'], queryFn: ({ signal }) => api.sources(signal) });
  const jobs = useQuery({ queryKey: ['user', userId, 'jobs'], queryFn: ({ signal }) => api.jobs(signal), refetchInterval: query => query.state.data?.some(job => ['PENDING', 'RUNNING'].includes(job.status)) ? 1000 : false });
  const docs = useQuery({ queryKey: ['user', userId, 'documents', selected], queryFn: ({ signal }) => api.documents(selected!, signal), enabled: selected !== null });
  const signature = jobs.data?.map(job => `${job.id}:${job.status}`).join(',');
  useEffect(() => {
    void client.invalidateQueries({ queryKey: ['user', userId, 'sources'] });
    void client.invalidateQueries({ queryKey: ['user', userId, 'knowledge'] });
    void client.invalidateQueries({ queryKey: ['user', userId, 'documents'] });
  }, [signature, client, userId]);
  const refresh = () => client.invalidateQueries({ queryKey: ['user', userId] });
  const connect = useMutation({ mutationFn: () => api.connectSource(repository.trim(), folders), onSuccess: async () => { setRepository(''); setFolders(''); setConsent(false); await refresh(); } });
  const action = useMutation({ mutationFn: async ({ source, action, prefixes }: { source: SourceResponse; action: 'sync' | 'pause' | 'resume' | 'scope'; prefixes?: string }) => {
    if (action === 'sync') await api.syncSource(source.id, crypto.randomUUID());
    else if (action === 'scope') await api.updateSourceScope(source, prefixes ?? '');
    else await api.updateSource(source, action === 'pause' ? 'PAUSED' : 'CONNECTED');
  }, onSuccess: refresh });
  const jobAction = useMutation({ mutationFn: ({ id, retry }: { id: string; retry: boolean }) => retry ? api.retryJob(id) : api.cancelJob(id), onSuccess: refresh });
  const remove = useMutation({ mutationFn: () => api.disconnectSource(disconnecting!.id, deleteDerived), onSuccess: async () => { setDisconnecting(null); setSelected(null); await refresh(); } });
  return <section className="stack" aria-labelledby="sources-title">
    <div><span className="eyebrow">01 / 连接已有知识</span><h1 id="sources-title">我的知识来源</h1><p className="muted">只读分析你选择的仓库。笔记中的内容会作为学习线索，掌握程度仍需要验证。</p></div>
    {new URLSearchParams(window.location.search).get('github') === 'denied' && <p role="alert">GitHub 授权已取消，尚未建立新连接。可以重新授权或继续使用公开仓库。</p>}
    <GitHubConnect api={api} userId={userId} />
    <form className="card stack" onSubmit={event => { event.preventDefault(); connect.mutate(); }}>
      <h2>连接 GitHub 笔记</h2>
      <label>仓库网址或 owner/repository<input required maxLength={256} placeholder="https://github.com/owner/notes" value={repository} onChange={event => setRepository(event.target.value)} /></label>
      <label>只导入指定文件夹（可选，多个用逗号分隔）<input maxLength={1000} placeholder="例如 notes/ai/；留空读取全部支持目录" value={folders} onChange={event => setFolders(event.target.value)} /></label>
      <p className="muted compact">支持 Markdown 与受限大小的代码文本；每个来源最多 200 份文件、10MB 可解析文本。忽略构建产物、二进制与超限文件。不会执行代码或修改仓库。</p>
      <label className="check"><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} required />我同意只读导入此仓库，用于我的学习画像。</label>
      <button disabled={!consent || connect.isPending} type="submit">{connect.isPending ? '正在连接…' : '添加只读来源'}</button>
      {connect.isError && <ErrorNotice error={connect.error} onRetry={() => connect.mutate()} />}
    </form>
    {sources.isPending && <p role="status">正在加载知识来源…</p>}
    {sources.isError && <ErrorNotice error={sources.error} onRetry={() => void sources.refetch()} />}
    {sources.data?.length === 0 && <div className="card muted">还没有知识来源。连接笔记后，你可以查看每条知识线索的原文依据。</div>}
    {sources.data?.map(source => {
      const job = jobs.data?.find(item => item.source_id === source.id && item.kind === 'GITHUB_SYNC');
      return <article className="card stack" key={source.id} aria-label={`来源 ${source.external_ref}`}>
        <div className="row"><h2>{source.external_ref}</h2><span className="badge">{source.status === 'CONNECTED' && source.write_scope.length ? '已连接 · 已限定 PR 写入' : statusLabels[source.status]}</span></div>
        <p className="muted compact">读取范围：{source.read_scope.join(', ')} · {source.path_prefixes.length ? source.path_prefixes.join(', ') : '全部支持目录'} · 写入权限：{source.write_scope.length ? source.write_scope.join(', ') : '未授权'}</p>
        <details><summary>修改导入范围</summary><form className="stack" onSubmit={event => { event.preventDefault(); action.mutate({ source, action: 'scope', prefixes: scopeEdits[source.id] ?? source.path_prefixes.join(', ') }); }}><label>文件夹范围<input maxLength={1000} value={scopeEdits[source.id] ?? source.path_prefixes.join(', ')} onChange={event => setScopeEdits({ ...scopeEdits, [source.id]: event.target.value })} /></label><p className="muted compact">保存会取消当前同步并恢复连接。下次同步会撤回范围外文件的当前证据；历史内容可在断开来源时一并删除。</p><button disabled={action.isPending}>保存范围并连接</button></form></details>
        {source.github_connection_id && source.status === 'CONNECTED' && <GitHubWriteAccess api={api} source={source} onChanged={refresh} />}
        {source.last_sync_at && <p className="muted compact">上次同步 {new Date(source.last_sync_at).toLocaleString()} · 提交 {source.last_revision?.slice(0, 8)}</p>}
        <div className="actions">
          <button disabled={source.status !== 'CONNECTED' || action.isPending || (job && ['PENDING', 'RUNNING'].includes(job.status))} onClick={() => action.mutate({ source, action: 'sync' })}>同步笔记</button>
          <button className="secondary" disabled={action.isPending} onClick={() => action.mutate({ source, action: source.status === 'CONNECTED' ? 'pause' : 'resume' })}>{source.status === 'CONNECTED' ? '暂停同步' : '恢复连接'}</button>
          <button className="secondary" onClick={() => setSelected(selected === source.id ? null : source.id)}>查看文件范围</button>
          <button className="secondary" onClick={() => { setDisconnecting(source); setDeleteDerived(false); remove.reset(); }}>断开来源</button>
        </div>
        {job && <div className="job" aria-label="同步状态"><strong>{statusLabels[job.status]}</strong><progress aria-label="导入进度" max={1} value={job.progress} /><p className="muted compact">尝试 {job.attempt_count}/{job.max_attempts}</p>
          {job.error_code && <p role="alert">{errorLabels[job.error_code] ?? '同步未完成，请检查文件范围并重试。'}</p>}
          {['PENDING', 'RUNNING'].includes(job.status) && <button className="secondary" disabled={jobAction.isPending} onClick={() => jobAction.mutate({ id: job.id, retry: false })}>取消同步</button>}
          {['FAILED', 'PARTIAL'].includes(job.status) && job.attempt_count < job.max_attempts && job.spent_units < job.budget_units && Date.parse(job.deadline_at) > Date.now() && <button disabled={jobAction.isPending} onClick={() => jobAction.mutate({ id: job.id, retry: true })}>重试失败文件</button>}
        </div>}
        {selected === source.id && <div className="file-list">
          {docs.isPending && <p role="status">正在加载文件范围…</p>}
          {docs.isError && <ErrorNotice error={docs.error} onRetry={() => void docs.refetch()} />}
          {docs.data?.length === 0 && <p className="muted">尚无文件记录，请先同步。空仓库不会生成虚构知识。</p>}
          {docs.data?.map(document => <div key={document.id} className="file-row"><code>{document.path}</code><span>{document.parse_status === 'PARSED' ? '已解析' : errorLabels[document.error_code ?? ''] ?? document.parse_status}</span>{document.renamed_from && <small>疑似从 {document.renamed_from} 移动（内容一致）</small>}</div>)}
        </div>}
      </article>;
    })}
    {(action.isError || jobAction.isError) && <ErrorNotice error={action.error ?? jobAction.error} />}
    {jobs.isError && <ErrorNotice error={jobs.error} onRetry={() => void jobs.refetch()} />}
    {disconnecting && <div className="card stack confirmation" role="dialog" aria-modal="true" aria-labelledby="disconnect-title">
      <h2 id="disconnect-title">断开 {disconnecting.external_ref}</h2><p>连接凭据会撤销，正在运行的同步会取消。GitHub 上的原文件会保留。</p>
      <label className="check"><input type="checkbox" checked={deleteDerived} onChange={event => setDeleteDerived(event.target.checked)} />同时删除此来源在应用中的正文及派生证据</label>
      <p className="muted compact">其他来源及独立学习记录会保留。未勾选时保留已有证据。</p>
      <div className="actions"><button disabled={remove.isPending} onClick={() => remove.mutate()}>确认断开</button><button className="secondary" onClick={() => setDisconnecting(null)}>取消</button></div>
      {remove.isError && <ErrorNotice error={remove.error instanceof ApiError ? remove.error : new Error()} />}
    </div>}
  </section>;
}
