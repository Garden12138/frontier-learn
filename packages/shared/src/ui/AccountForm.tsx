import { useState } from 'react';
import type { ApiClient, AccountSession } from '../api/client';
import { ErrorNotice } from './ErrorNotice';

export function downloadRecovery(code: string, identity = '') {
  const url = URL.createObjectURL(new Blob([`FrontierLearn account recovery code\nUsername: ${identity}\n${code}\nKeep this file private. The code is replaced after recovery.\n`], { type: 'text/plain;charset=utf-8' }));
  const link = document.createElement('a'); link.href = url; link.download = 'frontier-recovery-code.txt'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function AccountForm({ api, client, onAuthenticated }: { api: ApiClient; client: 'web' | 'extension'; onAuthenticated: (session: AccountSession) => Promise<void> }) {
  const [mode, setMode] = useState<'login' | 'register' | 'recover'>('login');
  const [identity, setIdentity] = useState('');
  const [password, setPassword] = useState('');
  const [recovery, setRecovery] = useState('');
  const [pending, setPending] = useState<AccountSession | null>(null);
  const [replacement, setReplacement] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function submit() {
    setBusy(true); setError(null);
    try {
      if (mode === 'recover') {
        const value = await api.recoverAccount(identity, password, recovery, client);
        setReplacement(value.recovery_code); setSaved(false); setRecovery(''); setPassword('');
      } else {
        const value = await api.accountLogin(identity, password, client, mode === 'register');
        setPassword('');
        if (value.recovery_code) { setPending(value); setSaved(false); }
        else await onAuthenticated(value);
      }
    } catch (value) { setError(value); } finally { setBusy(false); }
  }
  const code = pending?.recovery_code ?? replacement;
  return <section className="stack" aria-label="账号登录">
    {code ? <><h3>保存账号恢复文件</h3><p>忘记密码时使用此文件恢复账号。恢复后会撤销旧登录，并更换恢复码。服务不会通过邮件找回密码。</p><button onClick={() => { downloadRecovery(code, identity); setSaved(true); }}>下载恢复文件</button><button disabled={!saved || busy} onClick={() => { if (pending) { setBusy(true); void onAuthenticated(pending).catch(setError).finally(() => setBusy(false)); } else { setReplacement(null); setMode('login'); } }}>{pending ? '进入学习空间' : '返回密码登录'}</button></> : <>
      <div className="actions"><button className="secondary" disabled={busy} onClick={() => { setMode('login'); setError(null); }}>密码登录</button><button className="secondary" disabled={busy} onClick={() => { setMode('register'); setError(null); }}>创建账号</button><button className="secondary" disabled={busy} onClick={() => { setMode('recover'); setError(null); }}>恢复账号</button></div>
      <form className="stack" onSubmit={event => { event.preventDefault(); void submit(); }}>
        <label>用户名<input required minLength={3} maxLength={64} autoComplete="username" value={identity} onChange={event => setIdentity(event.target.value)} /></label>
        <label>{mode === 'recover' ? '新密码' : '密码'}<input required type="password" minLength={12} maxLength={128} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={password} onChange={event => setPassword(event.target.value)} /></label>
        {mode === 'recover' && <label>恢复码<input required type="password" minLength={32} maxLength={100} autoComplete="off" value={recovery} onChange={event => setRecovery(event.target.value)} /></label>}
        <p className="muted compact">用户名可用文字、数字和 ._-，至少 3 个字符；密码至少 12 个字符。不需要 GitHub 账号。</p>
        <button disabled={busy}>{busy ? '正在处理…' : mode === 'login' ? '登录学习空间' : mode === 'register' ? '注册并保存恢复码' : '确认恢复并撤销旧登录'}</button>
      </form></>}
    {error !== null && <ErrorNotice error={error} />}
  </section>;
}
