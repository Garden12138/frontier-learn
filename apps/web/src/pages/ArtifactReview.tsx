import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { downloadMarkdown, ErrorNotice } from '@frontier/shared';
import type { ApiClient, ArtifactResponse, JobResponse, PreviewRequest } from '@frontier/shared';

function Review({ api, initial, onChange, userId }: { api: ApiClient; initial: ArtifactResponse; onChange: () => void; userId: string }) {
  const [item, setItem] = useState(initial);
  const [markdown, setMarkdown] = useState(initial.markdown);
  const [sourceId, setSourceId] = useState(initial.preview?.source_id ?? '');
  const [path, setPath] = useState(initial.preview?.path ?? `notes/learning-${initial.id}.md`);
  const [mode, setMode] = useState<PreviewRequest['mode']>(initial.preview?.mode ?? 'NEW');
  const [confirmed, setConfirmed] = useState(false);
  const [job, setJob] = useState<JobResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [pollFailed, setPollFailed] = useState(false);
  const sources = useQuery({ queryKey: ['user', userId, 'write-sources'], queryFn: () => api.sources() });
  const trackedJobId = job?.id ?? item.job_id;
  const waiting = !!job && ['PENDING', 'RUNNING'].includes(job.status);
  useEffect(() => {
    if (!trackedJobId || pollFailed || (job && !waiting)) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const [jobs, items] = await Promise.all([api.job(trackedJobId!), api.artifacts()]);
        if (active) { setJob(jobs); const value = items.find(value => value.id === item.id); if (value) setItem(value); timer = setTimeout(() => void poll(), 1000); }
      } catch (value) { if (active) { setError(value); setPollFailed(true); } }
    }
    timer = setTimeout(() => void poll(), 500);
    return () => { active = false; clearTimeout(timer); };
  }, [api, item.id, trackedJobId, waiting, job, pollFailed]);
  async function act(operation: () => Promise<void>) {
    setBusy(true); setError(null);
    try { await operation(); onChange(); } catch (value) { setError(value); } finally { setBusy(false); }
  }
  const changed = markdown !== item.markdown;
  const matchesPreview = item.preview?.source_id === sourceId && item.preview.path === path && item.preview.mode === mode;
  return <article className="card stack" aria-label="笔记草稿审核"><h2>{item.title}</h2><p>草稿 v{item.version} · 内容尚需核验。保存草稿不会上传或发布。</p>
    <label>Markdown 草稿<textarea rows={18} maxLength={50000} value={markdown} onChange={event => { setMarkdown(event.target.value); setConfirmed(false); }} /></label>
    <div className="actions"><button disabled={busy || !changed} onClick={() => void act(async () => { const value = await api.editArtifact(item, markdown); setItem(value); setConfirmed(false); })}>保存草稿</button><button className="secondary" onClick={() => downloadMarkdown({ ...item, markdown })}>下载 Markdown，仅本地保存</button></div>
    <details><summary>GitHub 分支与 PR</summary><div className="stack">
      <p>需单独授权笔记目录。请先保存编辑，再审核 Diff；创建 PR 后由你在 GitHub 审查并合并。</p>
      {sources.isError && <ErrorNotice error={sources.error} />}
      <label>写回仓库<select value={sourceId} onChange={event => { setSourceId(event.target.value); setConfirmed(false); }}><option value="">选择已授权仓库</option>{sources.data?.filter(source => source.status === 'CONNECTED' && source.write_scope.length).map(source => <option value={source.id} key={source.id}>{source.external_ref} · {source.write_scope.join(', ')}</option>)}</select></label>
      <label>处理方式<select value={mode} onChange={event => { setMode(event.target.value as PreviewRequest['mode']); setConfirmed(false); }}><option value="NEW">新建笔记</option><option value="MANUAL_MERGE">手工合并：草稿作为完整目标文件</option></select></label>
      <label>目标 Markdown 路径<input maxLength={200} value={path} onChange={event => { setPath(event.target.value); setConfirmed(false); }} /></label>
      {mode === 'MANUAL_MERGE' && <p>先查看 Diff，再把需要保留的旧内容加入上方草稿并保存，重新预览。不会自动合并内容。</p>}
      <button className="secondary" disabled={busy || changed || !sourceId} onClick={() => void act(async () => { setItem(await api.previewArtifact(item.id, { version: item.version, source_id: sourceId, path, mode })); setConfirmed(false); })}>预览 Diff</button>
      {item.preview && <><p>{item.preview.repository}/{item.preview.path} · 基于 {item.preview.base_sha.slice(0, 10)}</p><pre className="draft-preview" aria-label="笔记 Diff">{item.preview.diff}</pre>
        <label className="check-line"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />我已审核这份 Diff，确认在所示仓库创建分支与 PR。</label>
        <button disabled={busy || changed || !confirmed || !matchesPreview || !!item.job_id} onClick={() => void act(async () => { setJob(await api.approveArtifact(item, crypto.randomUUID())); setConfirmed(false); })}>确认创建分支与 PR</button></>}
      {job && <div role="status"><p>写回状态：{job.status} · 尝试 {job.attempt_count}/{job.max_attempts} · 预算 {job.spent_units}/{job.budget_units}</p>{job.error_code && <p>{job.error_code} · 草稿已保留。</p>}
        {waiting && <button className="secondary" disabled={busy} onClick={() => void act(async () => setJob(await api.cancelJob(job.id)))}>取消写回</button>}
        {['FAILED', 'PARTIAL'].includes(job.status) && job.attempt_count < job.max_attempts && job.spent_units < job.budget_units && Date.parse(job.deadline_at) > Date.now() && <button disabled={busy} onClick={() => void act(async () => setJob(await api.retryJob(job.id)))}>重试并核对已有 PR</button>}
      </div>}
      {item.pr_url && <><a href={item.pr_url} target="_blank" rel="noreferrer">打开 GitHub PR #{item.pr_number}</a><button className="secondary" disabled={busy || !!item.reindexed_at} onClick={() => void act(async () => { setJob(await api.reindexArtifact(item)); })}>{item.reindexed_at ? '已重新索引' : '我已合并 PR，核对并重新索引'}</button><p>核对合并后重新同步来源；笔记不直接证明掌握。</p></>}
      {pollFailed && <button onClick={() => { setPollFailed(false); setJob(null); }}>重新读取任务状态</button>}
    </div></details>
    {error !== null && <ErrorNotice error={error} />}
  </article>;
}

export function ArtifactReview({ api, userId }: { api: ApiClient; userId: string }) {
  const items = useQuery({ queryKey: ['user', userId, 'artifacts'], queryFn: () => api.artifacts() });
  return <><section className="page-heading"><h1>笔记审核</h1><p>从短测生成草稿，检查来源、限制和未解疑问，再选择本地保存或明确批准 PR。</p></section>
    {items.isPending && <p role="status">正在读取草稿…</p>}{items.isError && <ErrorNotice error={items.error} onRetry={() => void items.refetch()} />}
    {items.data?.length === 0 && <section className="card">还没有笔记草稿。完成一次导学短测后，选择“生成笔记草稿”。</section>}
    {items.data?.map(item => <Review key={item.id} userId={userId} api={api} initial={item} onChange={() => void items.refetch()} />)}
  </>;
}
