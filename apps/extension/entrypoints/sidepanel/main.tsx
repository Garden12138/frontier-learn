import { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { browser } from 'wxt/browser';
import { ApiClient, AccountForm, ErrorNotice } from '@frontier/shared';
import type { UserResponse } from '@frontier/shared';
import '@frontier/shared/styles.css';
import { PagePreview } from '../../src/features/guide/PagePreview';
import { SessionHistory } from '../../src/features/guide/SessionHistory';

declare const __FRONTIER_API_ORIGIN__: string;

function SidePanel() {
  const token = useRef<string | undefined>(undefined);
  const [user, setUser] = useState<UserResponse | null>(null);
  const [identity, setIdentity] = useState('');
  const [passwordLogin, setPasswordLogin] = useState(false);
  const [mock, setMock] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const api = useMemo(() => new ApiClient({ baseUrl: `${__FRONTIER_API_ORIGIN__}/api/v1`, getToken: () => token.current,
    onUnauthorized: () => { token.current = undefined; setUser(null); void browser.storage.session.remove('auth'); },
  }), []);
  useEffect(() => {
    const changed: Parameters<typeof browser.storage.onChanged.addListener>[0] = (changes, area) => {
      if (area !== 'session' || !changes.auth) return;
      if (!changes.auth.newValue) { token.current = undefined; setUser(null); }
    };
    browser.storage.onChanged.addListener(changed);
    return () => browser.storage.onChanged.removeListener(changed);
  }, []);
  useEffect(() => {
    let active = true;
    void (async () => {
      await browser.storage.session.setAccessLevel({ accessLevel: 'TRUSTED_CONTEXTS' });
      const saved = await browser.storage.session.get('auth');
      if (!active) return;
      const auth: unknown = saved.auth;
      if (auth && typeof auth === 'object' && 'token' in auth && typeof auth.token === 'string') {
        token.current = auth.token;
        const restoredToken = auth.token;
        try { const next = await api.me(); if (active && token.current === restoredToken) setUser(next); } catch { /* Expired credentials are cleared by the client. */ }
      }
      const options = await api.authOptions(); if (active) { setMock(options.mock_login); setPasswordLogin(options.password_login); }
    })().catch(value => { if (active) setError(value); });
    return () => { active = false; };
  }, [api]);
  return <main style={{ padding: '1.5rem', maxWidth: '48rem', margin: 'auto' }}>
    <span className="eyebrow">FrontierLearn</span><h1>从这一页，开始理解。</h1>
    <p className="muted">先理解这一页，再验证自己的解释。由你主动开启读取。</p>
    <section className="card stack"><h2>连接学习工作台</h2>
      {user ? <><p>当前账号：{user.identity}</p><button className="secondary" disabled={busy} onClick={() => {
        setBusy(true); setError(null);
        void api.logout().then(async () => { await browser.storage.session.remove('auth'); token.current = undefined; setUser(null); }).catch(setError).finally(() => setBusy(false));
      }}>插件退出登录</button></> : mock ? <form className="stack" onSubmit={event => {
        event.preventDefault(); setBusy(true); setError(null);
        void api.loginMock(identity, 'extension').then(async session => {
          token.current = session.access_token;
          await browser.storage.session.set({ auth: { token: session.access_token } });
          const next = await api.me();
          if (token.current === session.access_token) { setUser(next); setIdentity(''); }
        }).catch(setError).finally(() => setBusy(false));
      }}><label>开发体验账号<input required minLength={3} maxLength={100} pattern="[a-zA-Z0-9@._+\-]+" value={identity} onChange={event => setIdentity(event.target.value)} /></label><p className="muted compact">与 Web 使用同名虚构账号即可共享目标和会话。当前没有密码验证。</p><button disabled={busy}>连接体验账号</button></form> : <p>{passwordLogin ? '使用下方账号登录，也可先在本地预览材料。' : '服务未连接或尚未开放账号登录；仍可在本地预览当前材料。'}</p>}
      {error !== null && <ErrorNotice error={error} />}
      {!user && passwordLogin && <AccountForm api={api} client="extension" onAuthenticated={async session => {
        if (!session.access_token) throw new Error('登录未返回插件凭据。');
        token.current = session.access_token;
        await browser.storage.session.set({ auth: { token: session.access_token } });
        setUser(await api.me());
      }} />}
    </section>
    {user && <SessionHistory key={`history-${user.id}`} api={api} />}
    <PagePreview key={`preview-${user?.id ?? 'anonymous'}`} api={api} signedIn={!!user} />
  </main>;
}

createRoot(document.getElementById('root')!).render(<SidePanel />);
