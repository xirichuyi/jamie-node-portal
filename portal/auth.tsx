import { useEffect, useRef, useState } from 'react';
import { ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Contact } from './content';
import { api, ApiError } from './api';
import { EmailCode } from './email-code';
import { pendingCard } from './card-entry';
import { ruleLabel, type CycleRule } from './cycle-labels';

type Preview = CycleRule & { label: string; quota: number; days: number };
export function ActivationSummary({ plan }: { plan: Preview }) {
  return (
    <div className="activation-summary">
      <strong>{plan.label}</strong>
      <span>
        {(plan.quota / 1024 ** 3).toLocaleString('zh-CN', {
          maximumFractionDigits: 2,
        })}{' '}
        GiB · {ruleLabel(plan)}
      </span>
      <p className="small muted">
        开通后开始计时，此前不会扣卡。
      </p>
    </div>
  );
}
export function AuthFlow({
  mode,
  navigate,
  onSuccess,
}: {
  mode: 'register' | 'login';
  navigate: (view: string) => void;
  onSuccess: (created: boolean) => Promise<void>;
}) {
  // Registration is open and card-free: email, code and password only.
  // Cards are redeemed after signing in, on the redeem page.
  const signup = mode === 'register';
  const [emailCode, setEmailCode] = useState('');
  const [username, setUsername] = useState(''),
    [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false),
    [busy, setBusy] = useState(false);
  const [error, setError] = useState(''),
    [complete, setComplete] = useState(false);
  const pending = useRef(false),
    heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    setError('');
    setShowPassword(false);
    setPassword('');
    setComplete(false);
  }, [mode]);
  useEffect(() => {
    heading.current?.focus();
  }, [mode, complete]);
  const submit = async () => {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError('');
    try {
      await api(
        signup ? 'register' : 'login',
        signup ? { username, password, email_code: emailCode } : { username, password },
      );
      setComplete(true);
      setPassword('');
      if (signup) {
        try {
          sessionStorage.removeItem('jamie-guide');
        } catch {}
      }
      // A card from a redeem link is kept and used on the redeem page after signup.
      await onSuccess(false);
    } catch (e) {
      setError(
        e instanceof ApiError && (e.status === 0 || e.status >= 500) && signup
          ? '注册结果未确认，请重试，或直接用刚设置的账号登录。'
          : e instanceof Error
            ? e.message
            : '暂时无法完成，请重试',
      );
    } finally {
      pending.current = false;
      setBusy(false);
    }
  };
  return (
    <section className="auth activation-auth">
      <span className="brand-icon auth-brand-mark" role="img" aria-label="Jamie-Node" />
      <h1 ref={heading} tabIndex={-1}>
        {complete ? (signup ? '注册成功' : '登录成功') : signup ? '注册账号' : '欢迎回来'}
      </h1>
      {complete ? (
        <Button disabled={busy} onClick={() => void onSuccess(false)}>
          继续进入
        </Button>
      ) : (
        <>
          {!!pendingCard() && (
            <div className="card-link-hint" role="status">
              <strong>{signup ? '注册后即可兑换链接中的卡密' : '登录后即可兑换链接中的卡密'}</strong>
              <button className="text-link" disabled={busy} onClick={() => navigate(signup ? 'login' : 'register')}>
                {signup ? '已有账号？去登录 →' : '还没有账号？去注册 →'}
              </button>
            </div>
          )}
          {error && (
            <p className="message error" role="alert">
              {error}
            </p>
          )}
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
            aria-busy={busy}
          >
            <label className="field">
              <span>{signup ? '邮箱' : '邮箱 / 原用户名'}</span>
              <Input
                name="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                minLength={3}
                maxLength={254}
                type={signup ? 'email' : 'text'}
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                disabled={busy}
                placeholder={signup ? '用于登录和找回密码' : '邮箱或原用户名'}
              />
            </label>
            {signup && <EmailCode email={username} purpose="register" value={emailCode} onChange={setEmailCode} />}
            <label className="field">
              <span>密码</span>
              <Input
                name="password"
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={10}
                maxLength={128}
                autoComplete={signup ? 'new-password' : 'current-password'}
                disabled={busy}
                placeholder={signup ? '至少 10 个字符' : '输入登录密码'}
              />
            </label>
            <button
              type="button"
              className="text-link password-toggle"
              aria-pressed={showPassword}
              onClick={() => setShowPassword(!showPassword)}
            >
              {showPassword ? '隐藏密码' : '显示密码'}
            </button>
            <Button type="submit" className="full" disabled={busy}>
              {busy ? (signup ? '正在注册…' : '正在登录…') : signup ? '注册' : '登录'}{' '}
              <ArrowRight size={18} />
            </Button>
          </form>
          <div className="auth-switch">
            <button
              className="text-link"
              disabled={busy}
              onClick={() => navigate(signup ? 'login' : 'register')}
            >
              {signup ? '已有账号？登录' : '还没有账号？免费注册'}
            </button>
            {!signup && (
              <button
                className="text-link"
                disabled={busy}
                onClick={() => navigate('recover')}
              >
                忘记密码？
              </button>
            )}
          </div>
        </>
      )}
      <Contact support={undefined} compact />
    </section>
  );
}
