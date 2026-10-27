import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ErrorNotice } from '@frontier/shared';
import type { ApiClient, SourceResponse } from '@frontier/shared';

export function GitHubConnect({ api, userId }: { api: ApiClient; userId: string }) {
  const cache = useQueryClient();
  const [installation, setInstallation] = useState('');
  const [repository, setRepository] = useState('');
  const [folders, setFolders] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [page, setPage] = useState(1);
  const [installationPage, setInstallationPage] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const status = useQuery({ queryKey: ['user', userId, 'github-status'], queryFn: () => api.githubStatus() });
  const installations = useQuery({ queryKey: ['user', userId, 'github-installations', installationPage], queryFn: () => api.githubInstallations(installationPage), enabled: !!status.data?.connected });
  const repos = useQuery({ queryKey: ['user', userId, 'github-repositories', installation, page], queryFn: () => api.githubRepositories(Number(installation), page), enabled: !!installation && !!status.data?.connected });
  async function act(operation: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await operation(); await cache.invalidateQueries({ queryKey: ['user', userId] }); }
    catch (value) { setError(value); } finally { setBusy(false); }
  }
  return <section className="card stack" aria-label="GitHub App 连接"><h2>连接 GitHub 账号与仓库</h2>
    <p>由 GitHub 授权，选择需要学习的仓库；读取与写回权限分开确认。</p>
    {status.isPending && <p role="status">正在检查连接…</p>}{status.isError && <ErrorNotice error={status.error} onRetry={() => void status.refetch()} />}
    {status.data && !status.data.available && <p>此学习服务尚未配置 GitHub App。仍可在下方连接公开仓库，或下载笔记到本地。</p>}
    {status.data?.available && <><button disabled={busy} onClick={() => void act(async () => { const result = await api.githubAuthorize(); window.location.assign(result.authorization_url); })}>{status.data.connected ? '重新授权 GitHub 账号' : '通过 GitHub 授权连接'}</button>
      {status.data.connected && <><p>已连接：{status.data.login}</p>{status.data.install_url && <a href={status.data.install_url} target="_blank" rel="noreferrer">在 GitHub 安装或调整 App，只选择需要的仓库</a>}
      <button className="secondary" disabled={busy} onClick={() => void act(() => api.githubDisconnect())}>断开 GitHub 账号和关联来源</button><p>断开会取消相关后台任务并撤销应用内凭据，保留学习证据及 GitHub 上的文件。</p>
      <form className="stack" onSubmit={event => { event.preventDefault(); const selected = repos.data?.items.find(item => String(item.id) === repository); if (selected) void act(async () => { await api.githubConnectRepository(Number(installation), selected, folders); setConfirmed(false); }); }}>
        <label>App 安装位置<select aria-label="App 安装位置" required value={installation} onChange={event => { setInstallation(event.target.value); setRepository(''); setPage(1); setConfirmed(false); }}><option value="">选择已授权位置</option>{installations.data?.items.map(item => <option key={item.id} value={item.id}>{item.account}</option>)}</select></label>
        {installations.data?.items.length === 0 && <p>尚无已安装位置，请先在 GitHub 安装 App，再刷新。</p>}
        <div className="actions"><button type="button" className="secondary" disabled={installationPage <= 1} onClick={() => setInstallationPage(value => value - 1)}>上一页安装位置</button><button type="button" className="secondary" disabled={!installations.data?.has_more || installationPage >= 3} onClick={() => setInstallationPage(value => value + 1)}>下一页安装位置</button><button type="button" className="secondary" onClick={() => void installations.refetch()}>刷新安装位置</button></div>
        <label>已授权仓库<select aria-label="已授权仓库" required value={repository} onChange={event => { setRepository(event.target.value); setConfirmed(false); }}><option value="">选择仓库</option>{repos.data?.items.map(item => <option key={item.id} value={item.id}>{item.full_name}{item.private ? ' · 私有' : ' · 公开'}</option>)}</select></label>
        {repos.data?.items.length === 0 && <p>该位置没有可读取仓库，请到 GitHub 调整 App 安装范围。</p>}
        <div className="actions"><button type="button" className="secondary" disabled={page <= 1} onClick={() => { setPage(value => value - 1); setRepository(''); }}>上一页仓库</button><button type="button" className="secondary" disabled={!repos.data?.has_more || page >= 3} onClick={() => { setPage(value => value + 1); setRepository(''); }}>下一页仓库</button></div>
        <label>读取文件夹（可选，逗号分隔）<input maxLength={1000} value={folders} onChange={event => { setFolders(event.target.value); setConfirmed(false); }} /></label>
        <label className="check"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />确认只读连接所选仓库，用于我的学习证据。</label>
        <button disabled={busy || !confirmed || !repository}>连接所选仓库</button>
      </form></>}
    </>}
    {installations.isError && <ErrorNotice error={installations.error} />}{repos.isError && <ErrorNotice error={repos.error} />}{error !== null && <ErrorNotice error={error} />}
  </section>;
}

export function GitHubWriteAccess({ api, source, onChanged }: { api: ApiClient; source: SourceResponse; onChanged: () => Promise<unknown> }) {
  const [scope, setScope] = useState(source.write_scope.join(', ') || source.path_prefixes.join(', ') || 'notes');
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  return <details><summary>单独授权笔记 PR 写入目录</summary><form className="stack" onSubmit={event => { event.preventDefault(); setBusy(true); setError(null); void api.githubGrantWrite(source, scope).then(async () => { setConfirm(false); await onChanged(); }).catch(setError).finally(() => setBusy(false)); }}>
    <label>允许写入的笔记目录<input required maxLength={1000} value={scope} onChange={event => { setScope(event.target.value); setConfirm(false); }} /></label><p>仅在你的 GitHub 用户也有写权限时授权。创建 PR 仍须逐份审核 Diff，不会直接更新默认分支。</p>
    <label className="check"><input type="checkbox" checked={confirm} onChange={event => setConfirm(event.target.checked)} />确认该仓库的上述目录可用于我审核后的 PR。</label><button disabled={busy || !confirm}>确认授权 PR 写入目录</button>{error !== null && <ErrorNotice error={error} />}
  </form></details>;
}
