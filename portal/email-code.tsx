import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { api } from './api';

export function EmailCode({ email, purpose, card, value, onChange, password }: {
  email: string; purpose: 'register' | 'reset' | 'change_old' | 'change_new'; card?: string; password?: string;
  value: string; onChange: (value: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [until, setUntil] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [message, setMessage] = useState('');
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  useEffect(() => { onChange(''); setMessage(''); }, [email]);
  const seconds = Math.max(0, Math.ceil((until - now) / 1000));
  return <div className="field">
    <label htmlFor={'email-code-' + purpose}>邮箱验证码</label>
    <Input id={'email-code-' + purpose} value={value} onChange={e => onChange(e.target.value)}
      required inputMode="numeric" pattern="[0-9]{6}" maxLength={6} autoComplete="one-time-code" placeholder="6 位验证码" />
    <Button type="button" variant="outline" disabled={busy || seconds > 0 || !email.trim()} onClick={async () => {
      setBusy(true); setMessage('');
      try {
        await api(purpose.startsWith('change_') ? 'account/email/code' : 'email/code', { email, purpose, code: card, password });
        setUntil(Date.now() + 60000); setNow(Date.now());
        setMessage('验证码已发送，10 分钟内有效，未收到请查看垃圾箱');
      } catch (e) { setMessage(e instanceof Error ? e.message : '发送失败，请稍后重试'); }
      finally { setBusy(false); }
    }}>{busy ? '发送中…' : seconds ? `${seconds} 秒后重发` : '发送验证码'}</Button>
    {message && <small role="status" className="muted">{message}</small>}
  </div>;
}
