import { useEffect, useRef, useState } from 'react';
import { ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Contact } from './content';
import { api, ApiError } from './api';
import { EmailCode } from './email-code';
import { PasteCard, useCardCode, clearPendingCard, pendingCard } from './card-entry';
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
  const signup = mode === 'register';
  const [emailCode, setEmailCode] = useState('');
  const [plan, setPlan] = useState<Preview | null>(null);
  // Registration is open: the card step may be skipped and redeemed later.
  const [skipped, setSkipped] = useState(false);
  const [code, setCode] = useCardCode(() => { setPlan(null); setSkipped(false); });
  const details = !!plan || skipped;
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
  }, [mode, details, complete]);
  const submit = async () => {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError('');
    try {
      if (signup && !details) {
        if (code.trim()) setPlan(await api<Preview>('register/preview', { code }));
        else setSkipped(true);
      } else {
        await api(
          signup ? 'register' : 'login',
          signup
            ? { code: plan ? code : '', username, password, email_code: emailCode }
            : { username, password },
        );
        setComplete(true);
        setCode('');
        setPassword('');
        if (signup) {
          clearPendingCard();
          try {
            sessionStorage.removeItem('jamie-guide');
          } catch {}
        }
        // Without a card there is nothing to install yet: land on home to open a plan.
        await onSuccess(signup && !!plan);
      }
    } catch (e) {
      setError(
        e instanceof ApiError &&
          (e.status === 0 || e.status >= 500) &&
          signup &&
          plan
          ? '开通结果未确认，请重试（不会重复扣卡），或直接用刚设置的账号登录。'
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
            ? plan
              ? '账号已开通'
              : '注册成功'
            : '登录成功'
          : signup
            ? details
              ? '设置你的账号'
              : '注册账号'
            : '欢迎回来'}
      </h1>
      {complete ? (
        <>
          <Button disabled={busy} onClick={() => void onSuccess(signup)}>
            继续进入
          </Button>
        </>
      ) : (
        <>
          {signup ? (
            <ol className="activation-steps" aria-label="开通步骤">
              <li aria-current={!details ? 'step' : undefined}>1 卡密（选填）</li>
              <li aria-current={details ? 'step' : undefined}>2 验证邮箱并注册</li>
            </ol>
          ) : null}
          {!!pendingCard() && !details && (
            <div className="card-link-hint" role="status">
              <strong>已填入兑换链接中的卡密</strong>
              <button className="text-link" disabled={busy} onClick={() => navigate(signup ? 'login' : 'register')}>
                {signup ? '已有账号？登录后兑换 →' : '还没有账号？用这张卡开通 →'}
              </button>
            </div>
          )}
          {plan && signup && <ActivationSummary plan={plan} />}
          {error && (
            <p className="message error" role="alert">
              {error}
            </p>
          )}
          {signup && !details && <PasteCard disabled={busy} onCode={setCode} />}
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
            aria-busy={busy}
          >
            {signup && !details ? (
              <label className="field">
                <span>卡密（选填）</span>
                <Input
                  name="code"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  maxLength={100}
                  autoComplete="off"
                  autoCapitalize="none"
                  spellCheck={false}
                  disabled={busy}
                  placeholder="有卡密可粘贴，没有可留空"
                />
                <small className="muted">
                  没有卡密也能注册，之后可在站内兑换或购买套餐。验证不扣卡、不计时。
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
                {signup && <EmailCode email={username} purpose="register" card={plan ? code : undefined} value={emailCode} onChange={setEmailCode} />}
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
              </>
            )}
            <Button type="submit" className="full" disabled={busy}>
              {busy
                ? signup && !details
                  ? '正在验证…'
                  : signup
                    ? '正在注册…'
                    : '正在登录…'
                : signup
                  ? details
                    ? plan
                      ? '确认开通'
                      : '注册'
                    : code.trim()
                      ? '验证卡密，继续'
                      : '不用卡密，直接注册'
                  : '登录'}{' '}
              <ArrowRight size={18} />
            </Button>
            {signup && details && (
              <button
                type="button"
                className="text-link"
                disabled={busy}
                onClick={() => {
                  setPlan(null);
                  setSkipped(false);
                  setError('');
                  setShowPassword(false);
                }}
              >
                {plan ? '← 返回修改卡密' : '← 返回填写卡密'}
              </button>
            )}
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
