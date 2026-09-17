import { useEffect, useRef, useState } from 'react';
import { ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Contact } from './content';
import { api, ApiError } from './api';
import { EmailCode } from './email-code';
import { ruleLabel, type CycleRule } from './cycles';

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
        开通成功后开始计时，验证卡密不会扣卡。
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
  const signup = mode === 'register';
  const [emailCode, setEmailCode] = useState('');
  const [code, setCode] = useState(''),
    [plan, setPlan] = useState<Preview | null>(null);
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
  }, [mode, !!plan, complete]);
  const submit = async () => {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError('');
    try {
      if (signup && !plan)
        setPlan(await api<Preview>('register/preview', { code }));
      else {
        await api(
          signup ? 'register' : 'login',
          signup ? { code, username, password, email_code: emailCode } : { username, password },
        );
        setComplete(true);
        setCode('');
        setPassword('');
        if (signup) {
          try {
            sessionStorage.removeItem('jamie-guide');
          } catch {}
        }
        await onSuccess(signup);
      }
    } catch (e) {
      setError(
        e instanceof ApiError &&
          (e.status === 0 || e.status >= 500) &&
          signup &&
          plan
          ? '暂未确认开通结果。请保留当前信息重试确认，系统不会重复扣卡；也可以用刚设置的账号密码登录。'
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
        {complete
          ? signup
            ? '账号已开通'
            : '登录成功'
          : signup
            ? plan
              ? '设置你的账号'
              : '用卡密开通账号'
            : '欢迎回来'}
      </h1>
      {complete ? (
        <>
          <p className="muted">
            账号操作已成功，无需再次开通。继续查看你的订阅。
          </p>
          <Button disabled={busy} onClick={() => void onSuccess(signup)}>
            继续进入
          </Button>
        </>
      ) : (
        <>
          {signup ? (
            <ol className="activation-steps" aria-label="开通步骤">
              <li aria-current={!plan ? 'step' : undefined}>1 验证卡密</li>
              <li aria-current={plan ? 'step' : undefined}>2 验证邮箱并开通</li>
            </ol>
          ) : (
            <p className="muted">登录，继续你的连接。</p>
          )}
          {plan && signup && <ActivationSummary plan={plan} />}
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
            {signup && !plan ? (
              <label className="field">
                <span>卡密</span>
                <Input
                  name="code"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  required
                  maxLength={100}
                  autoComplete="off"
                  autoCapitalize="none"
                  spellCheck={false}
                  disabled={busy}
                  placeholder="粘贴你收到的卡密"
                />
                <small className="muted">
                  验证不扣卡、不计时。
                </small>
              </label>
            ) : (
              <>
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
                {signup && <EmailCode email={username} purpose="register" card={code} value={emailCode} onChange={setEmailCode} />}
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
                    placeholder="至少 10 个字符"
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
              </>
            )}
            <Button type="submit" className="full" disabled={busy}>
              {busy
                ? signup && !plan
                  ? '正在验证…'
                  : signup
                    ? '正在开通…'
                    : '正在登录…'
                : signup
                  ? plan
                    ? '确认开通'
                    : '验证卡密，继续'
                  : '登录'}{' '}
              <ArrowRight size={18} />
            </Button>
            {signup && plan && (
              <button
                type="button"
                className="text-link"
                disabled={busy}
                onClick={() => {
                  setPlan(null);
                  setError('');
                  setShowPassword(false);
                }}
              >
                ← 返回修改卡密
              </button>
            )}
          </form>
          <div className="auth-switch">
            <button
              className="text-link"
              disabled={busy}
              onClick={() => navigate(signup ? 'login' : 'register')}
            >
              {signup ? '已经开通过？登录账号' : '有卡密？开通账号'}
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
          {signup && (
            <p className="small muted">
              已有账号需续费？请先登录，再兑换卡密。
            </p>
          )}
        </>
      )}
      <Contact support={undefined} compact />
    </section>
  );
}
