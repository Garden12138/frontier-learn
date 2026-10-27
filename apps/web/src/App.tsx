import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiClient, AccountForm, ErrorNotice, checkHealth } from '@frontier/shared';
import type { UserResponse } from '@frontier/shared';
import { KnowledgeSources } from './pages/KnowledgeSources';
import { KnowledgeProfile } from './pages/KnowledgeProfile';
import { Goals } from './pages/Goals';
import { Today } from './pages/Today';
import { Sessions } from './pages/Sessions';
import { Settings } from './pages/Settings';
import { Assessment } from './pages/Assessment';
import { ArtifactReview } from './pages/ArtifactReview';
import { ImportConversation } from './pages/ImportConversation';

export function App() {
  const client = useQueryClient();
  const [user, setUser] = useState<UserResponse | null>(null);
  const [page, setPage] = useState<'today' | 'goals' | 'sources' | 'knowledge' | 'sessions' | 'conversations' | 'assessments' | 'artifacts' | 'settings'>(new URLSearchParams(window.location.search).has('github') ? 'sources' : 'today');
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversationCandidateId, setConversationCandidateId] = useState<string | null>(null);
  const [knowledgeQuery, setKnowledgeQuery] = useState('');
  const [selectedGoalId, setSelectedGoalId] = useState<string | null>(null);
  const [identity, setIdentity] = useState('');
  const [checkingSession, setCheckingSession] = useState(true);
  const token = useRef<string | undefined>(undefined);
  const api = useMemo(() => new ApiClient({ getToken: () => token.current, onUnauthorized: () => { token.current = undefined; setUser(null); client.removeQueries({ queryKey: ['user'] }); } }), [client]);
  useEffect(() => {
    let active = true;
    void api.me().then(value => { if (active) setUser(value); }).catch(() => {}).finally(() => { if (active) setCheckingSession(false); });
    return () => { active = false; };
  }, [api]);
  const options = useQuery({ queryKey: ['auth-options'], queryFn: () => api.authOptions() });
  const health = useQuery({ queryKey: ['health'], queryFn: ({ signal }) => checkHealth(signal) });
  const login = useMutation({ mutationFn: async () => { const session = await api.loginMock(identity); token.current = session.access_token; return api.me(); }, onSuccess: value => { setUser(value); setIdentity(''); } });
  const logout = useMutation({ mutationFn: () => api.logout(), onSuccess: () => { token.current = undefined; setUser(null); client.removeQueries({ queryKey: ['user'] }); } });
  return (
    <div className="workspace">
      <aside className="rail" aria-label="工作台介绍">
        <strong className="brand">FrontierLearn<span>从已有知识，走向下一步。</span></strong>
        <div className="rail-note">个人学习工作台<p>有来源的理解，<br />可验证的进步。</p></div>
        {user && <nav aria-label="工作台导航"><button className={page === 'today' ? 'nav-active' : ''} onClick={() => setPage('today')}>今日学习</button><button className={page === 'goals' ? 'nav-active' : ''} onClick={() => setPage('goals')}>学习目标</button><button className={page === 'sources' ? 'nav-active' : ''} onClick={() => setPage('sources')}>知识来源</button><button className={page === 'knowledge' ? 'nav-active' : ''} onClick={() => setPage('knowledge')}>知识画像</button><button className={page === 'sessions' ? 'nav-active' : ''} onClick={() => setPage('sessions')}>导学会话</button><button className={page === 'conversations' ? 'nav-active' : ''} onClick={() => { setConversationId(null); setConversationCandidateId(null); setPage('conversations'); }}>导入对话</button><button className={page === 'assessments' ? 'nav-active' : ''} onClick={() => setPage('assessments')}>理解验证</button><button className={page === 'artifacts' ? 'nav-active' : ''} onClick={() => setPage('artifacts')}>笔记审核</button><button className={page === 'settings' ? 'nav-active' : ''} onClick={() => setPage('settings')}>设置与数据</button></nav>}
        <span className="eyebrow">MVP · 开发预览</span>
      </aside>
      <main>
        <header><span className="eyebrow">Learning workspace</span>{user ? <div className="actions"><span>{user.identity}</span><button className="secondary" disabled={logout.isPending} onClick={() => logout.mutate()}>退出登录</button></div> : <span className="muted">学习，从一个目标开始</span>}</header>
        {user ? <div className="page">
          {page === 'today' && <Today key={user.id} api={api} userId={user.id} selectedGoalId={selectedGoalId} onSelectGoal={setSelectedGoalId} onManageGoals={() => setPage('goals')} onOpenConversation={(id, candidateId) => { setConversationId(id); setConversationCandidateId(candidateId ?? null); setPage('conversations'); }} />}
          {page === 'settings' && <Settings key={user.id} api={api} userId={user.id} onDeleted={() => { token.current = undefined; setUser(null); client.removeQueries({ queryKey: ['user'] }); }} />}
          {page === 'assessments' && <Assessment key={user.id} api={api} userId={user.id} />}
          {page === 'artifacts' && <ArtifactReview key={user.id} api={api} userId={user.id} />}
          {page === 'goals' && <Goals key={user.id} api={api} userId={user.id} onOpenPlan={goalId => { setSelectedGoalId(goalId); setPage('today'); }} />}
          {page === 'sources' && <KnowledgeSources api={api} userId={user.id} />}
          {page === 'knowledge' && <KnowledgeProfile key={`${user.id}-${knowledgeQuery}`} api={api} userId={user.id} initialQuery={knowledgeQuery} />}
          {page === 'sessions' && <Sessions key={user.id} api={api} userId={user.id} />}
          {page === 'conversations' && <ImportConversation key={`${user.id}-${conversationId}-${conversationCandidateId}`} api={api} userId={user.id} initialId={conversationId} initialCandidateId={conversationCandidateId} onOpenKnowledge={name => { setKnowledgeQuery(name); setPage('knowledge'); }} onOpenPlan={id => { setSelectedGoalId(id); setPage('today'); }} />}
          {logout.isError && <ErrorNotice error={logout.error} />}</div> : <>
        <section className="welcome">
          <span className="eyebrow">你的学习空间</span>
          <h1>让每一次学习，<br />都有下一步。</h1>
          <p className="muted">连接已有笔记，建立有依据的知识画像。根据你的目标安排学习，<br className="desktop-break" />通过验证和笔记复盘，让下一次计划更贴近你。</p>
        </section>
        <section className="card" aria-labelledby="setup-title">
          <span className="eyebrow">你的学习空间</span>
          <h2 id="setup-title">先连接你的学习空间</h2>
          <p className="muted">登录后可以连接 GitHub 笔记，查看可追溯的知识线索与文件同步状态。</p>
          {health.isPending && <p role="status">正在检查学习服务…</p>}
          {health.isError && <p role="alert">无法连接学习服务。请启动 API 后重试。</p>}
          {health.isSuccess && <p role="status">学习服务已连接 · v{health.data.version}</p>}
          <button disabled={health.isFetching} onClick={() => void health.refetch()}>重新检查连接</button>
          {checkingSession && <p>正在检查登录状态…</p>}
          {!checkingSession && options.data?.password_login && <AccountForm api={api} client="web" onAuthenticated={async () => { token.current = undefined; setUser(await api.me()); }} />}
          {!checkingSession && options.data?.mock_login && <form className="stack login-form" onSubmit={event => { event.preventDefault(); login.mutate(); }}><label>开发体验账号<input required minLength={3} maxLength={100} pattern="[a-zA-Z0-9@._+\-]+" value={identity} onChange={event => setIdentity(event.target.value)} placeholder="输入体验账号名称" autoComplete="username" /></label><p className="muted compact">当前为本地开发体验，无密码验证。请使用虚构账号和测试笔记。</p><button disabled={login.isPending}>{login.isPending ? '正在登录…' : '进入学习空间'}</button>{login.isError && <ErrorNotice error={login.error} />}</form>}
          {!checkingSession && options.data && !options.data.mock_login && !options.data.password_login && <p className="muted">当前服务尚未开放账号登录。开发体验入口需要由本机服务开启。</p>}
          {options.isError && health.isSuccess && <ErrorNotice error={options.error} onRetry={() => void options.refetch()} />}
        </section>
        <p className="footnote muted">登录前不读取你的知识来源 · 当前不向外部模型发送内容</p>
        </>}
      </main>
    </div>
  );
}
