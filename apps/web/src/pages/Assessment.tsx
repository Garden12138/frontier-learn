import { useQuery } from '@tanstack/react-query';
import { AssessmentPanel, ErrorNotice } from '@frontier/shared';
import type { ApiClient } from '@frontier/shared';

export function Assessment({ api, userId }: { api: ApiClient; userId: string }) {
  const sessions = useQuery({ queryKey: ['user', userId, 'assessment-sessions'], queryFn: () => api.sessions() });
  return <><section className="page-heading"><h1>理解验证</h1><p>复查短测、评价依据与证据确认。当前默认验证范围为来源边界。</p></section>
    {sessions.isPending && <p role="status">正在读取学习记录…</p>}
    {sessions.isError && <ErrorNotice error={sessions.error} onRetry={() => void sessions.refetch()} />}
    {sessions.data?.length === 0 && <section className="card">还没有导学会话，请先从插件保存一次导学。</section>}
    {sessions.data?.map(session => <section className="card stack" key={session.id}><h2>{session.title}</h2><AssessmentPanel api={api} sessionId={session.id} /></section>)}
  </>;
}
