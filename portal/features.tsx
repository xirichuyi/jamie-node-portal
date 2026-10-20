import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from 'react';
import type { Ticket } from './account-features';
import { api } from './api';
import { clearPendingCard, PasteCard, useCardCode } from './card-entry';
import { NodeStatus, PageTitle } from './content';
import { expiryLabel, ruleLabel } from './cycles';
import { remainingAfter } from './experience';

export type Nav = (view: string) => void;
type Subscription = {
  quota: number;
  used: number | null;
  expires: number;
  url: string | null;
  pending: boolean;
  rotating?: boolean;
  billing?: { packages: PackageBalance[]; remaining: number; next_expiry: number } | null;
};
export type PackageBalance = import('./cycles').CycleRule & { id: string; parent_id?: string | null; label: string; kind: string; granted: number; spent: number; remaining: number; expires: number; status: string; next_reset?: number };
export function PackageBalances({ packages }: { packages: PackageBalance[] }) {
  const active = packages.filter(p => p.status === 'active');
  return <section className="surface">
    <h2>套餐与流量包</h2>
    <p className="small muted">优先使用最早到期或重置的额度。周期额度不结转；加流量包随所属套餐当前周期到期，不延长时间。</p>
    {!!active.length && <p className="small">当前优先扣除：{active[0].label}</p>}
    <div className="package-detail-list">{packages.map(p => <article className="package-detail-row" key={p.id}>
      <div><strong>{p.label}</strong><small className="sync-caption">{p.kind === 'addon' ? '加流量包' : p.kind === 'transition' ? '原有剩余额度' : '独立套餐'} · {{active:'有效',expired:'已到期',exhausted:'已用完',revoked:'已撤销'}[p.status] || p.status}{p.status === 'active' ? ` · 扣除顺序 ${active.indexOf(p) + 1}` : ''}</small>
        {p.parent_id && <small className="sync-caption">所属套餐：{packages.find(parent => parent.id === p.parent_id)?.label || '查看兑换记录'}</small>}
      </div>
      <div><strong>剩余 {size(p.remaining)}</strong><small className="sync-caption">已用 {size(p.spent)} / {size(p.granted)}</small></div>
      <div><span>{expiryLabel(p.expires)}</span><small className="sync-caption">到期时间</small>{!!p.next_reset && p.next_reset < p.expires && <small className="sync-caption">下次重置 {expiryLabel(p.next_reset)} · 不结转</small>}</div>
    </article>)}</div>
  </section>;
}
export const when = (n: number | null) =>
  n
    ? new Date(n * 1000).toLocaleString('zh-CN', { hour12: false })
    : '暂无记录';
const size = (n: number) =>
  n >= 1024 ** 3
    ? `${(n / 1024 ** 3).toFixed(2)} GiB`
    : `${(n / 1024 ** 2).toFixed(1)} MiB`;
const expiryDate = expiryLabel;
export function useWork() {
  const [busy, setBusy] = useState(false),
    [message, setMessage] = useState(''),
    [error, setError] = useState('');
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : '操作失败，请重试');
    } finally {
      setBusy(false);
    }
  };
  return {
    busy,
    setMessage,
    run,
    feedback: (
      <>
        {error && (
          <p className="message error" role="alert">
            {error}
          </p>
        )}
        {message && (
          <p className="message success" role="status">
            {message}
          </p>
        )}
      </>
    ),
  };
}
export function useData<T>(path: string, poll = 0) {
  const [data, setData] = useState<T | null>(null),
    [error, setError] = useState('');
  const request = useRef(0);
  const reload = useCallback(async () => {
    const version = ++request.current;
    try {
      const result = await api<T>(path);
      if (version === request.current) {
        setData(result);
        setError('');
      }
    } catch (e) {
      if (version === request.current)
        setError(e instanceof Error ? e.message : '读取失败');
    }
  }, [path]);
  useEffect(() => {
    setData(null);
    setError('');
    void reload();
    const visible = () => {
      if (document.visibilityState === 'visible') void reload();
    };
    if (poll) document.addEventListener('visibilitychange', visible);
    const timer = poll ? window.setInterval(visible, poll) : undefined;
    return () => {
      request.current++;
      if (timer) clearInterval(timer);
      if (poll) document.removeEventListener('visibilitychange', visible);
    };
  }, [path, poll, reload]);
  return {
    data,
    reload,
    placeholder: error ? (
      <p className="message error" role="alert">
        {error}{' '}
        <button className="text-link" onClick={() => void reload()}>
          重试
        </button>
      </p>
    ) : !data ? (
      <p className="muted" role="status">
        正在加载…
      </p>
    ) : null,
  };
}
export function AccountAttention({
  username,
  navigate,
}: {
  username: string;
  navigate: Nav;
}) {
  const recovery = useData<{ recovery_created: number | null; email_verified?: boolean }>(
    'sessions',
    60000,
  );
  const tickets = useData<{ tickets: Ticket[] }>('tickets', 30000);
  const [dismissed, setDismissed] = useState(() => {
    try {
      return (
        sessionStorage.getItem('jamie-recovery-hint:' + username) ===
        'dismissed'
      );
    } catch {
      return false;
    }
  });
  const replied =
    tickets.data?.tickets.filter((t) => t.status === 'replied').length || 0;
  return (
    <div className="account-attention">
      {recovery.data && !recovery.data.email_verified && !dismissed && (
        <div className="journey-alert">
          <span>还没有绑定邮箱：绑定后可收到兑换到账、服务到期和流量不足提醒，忘记密码也能找回。</span>
          <div className="actions">
            <button className="text-link" onClick={() => navigate('sessions')}>
              去绑定邮箱 →
            </button>
            <button
              className="text-link"
              onClick={() => {
                setDismissed(true);
                try {
                  sessionStorage.setItem(
                    'jamie-recovery-hint:' + username,
                    'dismissed',
                  );
                } catch {}
              }}
            >
              暂不提醒
            </button>
          </div>
        </div>
      )}
      {replied > 0 && (
        <div className="journey-alert">
          <span>{replied} 条工单已回复</span>
          <button className="text-link" onClick={() => navigate('tickets')}>
            查看回复 →
          </button>
        </div>
      )}
    </div>
  );
}
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="feature-field">
      <span>{label}</span>
      {children}
    </label>
  );
}
export function form(e: FormEvent<HTMLFormElement>) {
  e.preventDefault();
  return Object.fromEntries(new FormData(e.currentTarget));
}
export function Choice({
  name,
  label,
  initial,
  options,
  onChange,
}: {
  name: string;
  label: string;
  initial: string;
  options: Record<string, string>;
  onChange?: (value: string) => void;
}) {
  const [value, setValue] = useState(initial);
  return (
    <Select
      name={name}
      value={value}
      onValueChange={(v) => {
        if (v) {
          setValue(String(v));
          onChange?.(String(v));
        }
      }}
    >
      <SelectTrigger aria-label={label} className="w-full">
        <SelectValue>{options[value]}</SelectValue>
      </SelectTrigger>
      <SelectContent>
        {Object.entries(options).map(([key, title]) => (
          <SelectItem key={key} value={key}>
            {title}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
export function GettingStarted({
  s,
  navigate,
}: {
  s: Subscription;
  navigate: Nav;
}) {
  if (!s.quota && !s.billing?.packages.length)
    return (
      <section className="onboarding">
        <div>
          <h2>三步开始使用</h2>
          <p className="muted">兑换卡密 → 安装客户端 → 导入并连接</p>
        </div>
        <div className="actions">
          <Button onClick={() => navigate('redeem')}>兑换卡密</Button>
          <Button variant="outline" onClick={() => navigate('guide')}>
            下载客户端
          </Button>
        </div>
      </section>
    );
  const days = Math.ceil((s.expires - Date.now() / 1000) / 86400),
    low = s.used !== null && s.used / s.quota >= 0.9;
  if (days > 7 && !low) return null;
  return (
    <div className="account-alert" role="status">
      <span>
        {days <= 0
          ? '订阅已到期'
          : days <= 7
            ? `订阅将在 ${days} 天内到期`
            : ''}
        {days <= 7 && low ? ' · ' : ''}
        {low ? (s.used! >= s.quota ? '流量已用完' : '剩余流量不足 10%') : ''}
      </span>
      <button className="text-link" onClick={() => navigate('redeem')}>
        兑换续费 →
      </button>
    </div>
  );
}
function device() {
  const ua = typeof navigator === 'undefined' ? '' : navigator.userAgent;
  return /iPhone|iPad|iPod/.test(ua) ||
    (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)
    ? 'ios'
    : /Android/.test(ua)
      ? 'android'
      : 'desktop';
}
export function Connection({
  s,
  navigate,
  onChanged,
  compact = false,
}: {
  s: Subscription;
  navigate: Nav;
  onChanged: () => Promise<void>;
  compact?: boolean;
}) {
  const work = useWork(),
    [copied, setCopied] = useState(false),
    [visible, setVisible] = useState(false),
    [qr, setQr] = useState(''),
    [showQr, setShowQr] = useState(false),
    [reset, setReset] = useState(false),
    [resetCredentials, setResetCredentials] = useState(false),
    [password, setPassword] = useState('');
  const platform = device(),
    url = s.url;
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);
  useEffect(() => {
    setVisible(false);
    setQr('');
    setShowQr(false);
  }, [url]);
  const forced = (format: string) => {
    const u = new URL(url!);
    u.searchParams.set('format', format);
    return u.href;
  };
  const launch = (client: string) => {
    window.location.href =
      client === 'ios'
        ? 'shadowrocket://add/sub://' + btoa(forced('shadowrocket'))
        : (client === 'android' ? 'clashmeta' : 'clash') +
          '://install-config?url=' +
          encodeURIComponent(forced('clash')) +
          '&name=Jamie-Node';
  };
  return (
    <section className="section connection-panel">
      <div className="section-heading">
        <h2>连接你的设备</h2>
        <button className="text-link" onClick={() => navigate('guide')}>
          下载与教程 →
        </button>
      </div>
      {work.feedback}
      {url ? (
        <>
          <div className="actions">
            <Button onClick={() => launch(platform)}>
              导入
              {platform === 'ios'
                ? '小火箭'
                : platform === 'android'
                  ? '安卓 Clash'
                  : ' Clash Verge'}
            </Button>
            <Button
              variant="outline"
              onClick={() =>
                void work.run(async () => {
                  await navigator.clipboard.writeText(url);
                  setCopied(true);
                })
              }
            >
              <span role="status">{copied ? '已复制' : '复制订阅'}</span>
            </Button>
            <Button
              variant="outline"
              onClick={() =>
                void work.run(async () => {
                  setQr(
                    // Loaded on demand: most visits never open the QR code.
                    await (await import('qrcode')).default.toDataURL(url, {
                      width: 288,
                      margin: 3,
                      errorCorrectionLevel: 'M',
                    }),
                  );
                  setShowQr(true);
                })
              }
            >
              二维码
            </Button>
          </div>
          {!compact && <p className="small muted">
            未安装客户端？先查看下载教程。
          </p>}
          {compact ? (
            <button
              className="text-link connection-more"
              onClick={() => navigate('subscription')}
            >
              订阅设置 →
            </button>
          ) : (
            <details>
              <summary>其他客户端与订阅安全</summary>
              <div className="actions">
                <Button variant="outline" onClick={() => launch('desktop')}>
                  Clash
                </Button>
                <Button variant="outline" onClick={() => launch('ios')}>
                  小火箭
                </Button>
                <Button variant="outline" onClick={() => launch('android')}>
                  Android
                </Button>
              </div>
              <p className="small muted">
                Clash 含国内直连、国外代理规则。小火箭使用客户端内的分流配置。
              </p>
              <div className="subscription-secret">
                <code>{visible ? url : '••••••••••••••••••••••••'}</code>
                <button
                  className="text-link"
                  onClick={() => setVisible(!visible)}
                >
                  {visible ? '隐藏' : '显示链接'}
                </button>
              </div>
              <div className="actions">
                <a href={forced('clash')}>下载 Clash 配置</a>
                <Button
                  variant="ghost"
                  onClick={() => {
                    setResetCredentials(false);
                    setReset(true);
                  }}
                >
                  重置订阅链接
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => {
                    setResetCredentials(true);
                    setReset(true);
                  }}
                >
                  泄露处理：更换连接凭据
                </Button>
              </div>
            </details>
          )}
        </>
      ) : (
        <div className="empty">
          <p>
            {s.rotating
              ? '正在更新订阅链接，请稍候…'
              : s.pending
                ? '正在开通，完成后即可导入。'
                : '兑换卡密后，即可连接。'}
          </p>
          {!s.pending && (
            <Button onClick={() => navigate('redeem')}>兑换卡密</Button>
          )}
        </div>
      )}
      <Dialog open={showQr} onOpenChange={setShowQr}>
        <DialogContent>
          <DialogTitle>订阅二维码</DialogTitle>
          <DialogDescription>
            用客户端扫码导入。二维码包含访问凭证，请勿公开分享。
          </DialogDescription>
          {qr && (
            <img
              className="subscription-qr"
              src={qr}
              alt="Jamie-Node 私人订阅二维码"
              width="288"
              height="288"
            />
          )}
        </DialogContent>
      </Dialog>
      <Dialog
        open={reset}
        onOpenChange={(v) => {
          setReset(v);
          setPassword('');
        }}
      >
        <DialogContent>
          <DialogTitle>
            {resetCredentials ? '更换所有连接凭据？' : '重置订阅链接？'}
          </DialogTitle>
          <DialogDescription>
            {resetCredentials
              ? '将同时更换订阅链接与节点密码，额度和到期时间不变。同步完成后，所有设备必须删除旧节点并重新导入。同步期间可能短暂断开，已建立的连接是否立即断开取决于节点内核。'
              : '旧链接会失效，你需要在所有客户端重新导入。已导入的节点凭据不会因此失效；如已泄露，请取消并选择“更换连接凭据”。'}
          </DialogDescription>
          {work.feedback}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void work.run(async () => {
                await api(
                  resetCredentials
                    ? 'subscription/reset-credentials'
                    : 'subscription/reset',
                  { password },
                );
                setPassword('');
                setReset(false);
                await onChanged();
                work.setMessage('正在同步新链接，完成后请重新导入');
              });
            }}
          >
            <Field label="当前登录密码">
              <Input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </Field>
            <Button type="submit" disabled={work.busy}>
              确认重置
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  );
}
type Usage = {
  days: { day: string; bytes: number | null; partial: boolean }[];
  sampled: number;
  started: number;
  timezone: string;
};
export function usageWindow(days: Usage['days'], compact: boolean) {
  const range = days.slice(compact ? -7 : -30);
  const first = range.findIndex(d => d.bytes !== null);
  return first < 0 ? [] : range.slice(first);
}
export function UsagePanel({
  compact = false,
  navigate,
}: {
  compact?: boolean;
  navigate: Nav;
}) {
  const { data, placeholder } = useData<Usage>('usage');
  const days = usageWindow(data?.days || [], compact);
  return (
    <section className="section usage-panel">
      {compact && <div className="section-heading">
        <h2>{days.length === 1 ? '今日用量' : '最近用量'}</h2>
        {compact && (
          <button className="text-link" onClick={() => navigate('usage')}>
            查看明细 →
          </button>
        )}
      </div>}
      {placeholder}
      {data && (
        <>
          {!days.length && <p className="empty muted">暂无用量记录</p>}
          {!!days.length && <div className="usage-summary">
            <strong>
              {days.some(d => d.bytes !== null) ? size(days.reduce((sum, d) => sum + (d.bytes || 0), 0)) : '—'}
            </strong>
          </div>}
          {!!days.length && <div className={compact ? 'usage-bars usage-bars-compact' : 'usage-bars usage-bars-detail'} aria-label="每日已记录流量">
            {days.map((d, index) => (
              <div
                key={d.day}
                title={`${d.day}：${d.bytes === null ? '暂无数据' : size(d.bytes) + (d.partial ? '（部分记录）' : '')}`}
              >
                <div
                  className={
                    'usage-track ' + (d.bytes === null ? 'missing' : '')
                  }
                >
                  <span
                    style={{
                      height:
                        d.bytes === null || d.bytes === 0
                          ? 0
                          : `${Math.max(2, (100 * d.bytes) / Math.max(1, ...days.map((v) => v.bytes || 0)))}%`,
                    }}
                  />
                </div>
                <small>
                  {compact || days.length <= 7 || index % 5 === 0 || index === days.length - 1
                    ? d.day.slice(5).replace('-', '/')
                    : '\u00a0'}
                </small>
              </div>
            ))}
          </div>}
          {data.sampled > 0 && Date.now() / 1000 - data.sampled > 900 && (
            <p className="message error">
              用量暂未更新，最后采样：{when(data.sampled)}
            </p>
          )}
          {!compact && days.length > 0 && (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>日期</TableHead>
                    <TableHead>用量</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {[...days].reverse().filter(d => d.bytes !== null).map((d) => (
                    <TableRow key={d.day}>
                      <TableCell>{d.day}</TableCell>
                      <TableCell title={d.partial ? '部分记录' : undefined}>
                        {d.bytes === null ? '—' : size(d.bytes)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </>
          )}
        </>
      )}
    </section>
  );
}
type Preview = import('./cycles').CycleRule & {
  label: string;
  quota: number;
  days: number;
  after_quota: number;
  after_expires: number;
  kind?: 'base' | 'addon';
  package_billing?: boolean;
  targets?: {id: string; label: string; expires: number}[];
};
export function Redemption({
  onChanged,
  navigate,
  subscription,
}: {
  onChanged: () => Promise<void>;
  navigate: Nav;
  subscription?: Subscription;
}) {
  const work = useWork(),
    [preview, setPreview] = useState<Preview | null>(null),
    [done, setDone] = useState(false);
  const [target, setTarget] = useState('');
  const [code, setCode] = useCardCode(() => { setPreview(null); setDone(false); setTarget(''); });
  const used = subscription?.quota === 0 ? 0 : subscription?.used;
  return (
    <>
      <PageTitle
        eyebrow="REDEEM"
        title="兑换卡密"
        description="先确认套餐，再充入你的账号。"
      />
      <section className="surface feature-form">
        {work.feedback}
        {done ? (
          <>
            <h2>兑换成功</h2>
            <p>
              {subscription?.url
                ? '订阅已就绪，现在可以导入客户端。'
                : subscription?.pending
                  ? '额度已到账，正在同步节点，无需重复兑换。'
                  : '额度已到账，请到首页查看订阅状态。'}
            </p>
            <Button
              onClick={() =>
                navigate(
                  subscription?.url
                    ? 'subscription'
                    : 'home',
                )
              }
            >
              {subscription?.url
                ? '导入并连接'
                : '查看订阅状态'}
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                setDone(false);
                setCode('');
              }}
            >
              继续兑换
            </Button>
          </>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void work.run(async () => {
                setPreview(await api<Preview>('redeem/preview', { code }));
                setTarget('');
              });
            }}
          >
            <PasteCard disabled={work.busy} onCode={value => { setCode(value); setPreview(null); setTarget(''); }} />
            <Field label="卡密">
              <Input
                required
                autoComplete="off"
                value={code}
                maxLength={100}
                onChange={(e) => {
                  setCode(e.target.value);
                  setPreview(null);
                }}
                placeholder="输入管理员发放的卡密"
                disabled={work.busy}
              />
            </Field>
            {preview ? (
              <div className="redemption-preview">
                <h2>{preview.label}</h2>
                {preview.kind === 'addon' && <Field label="选择要增加流量的套餐">
                  <Select value={target} onValueChange={value => { setTarget(value || ''); setPreview({...preview, after_expires:preview.targets?.find(p => p.id===value)?.expires || 0}); }}>
                    <SelectTrigger><SelectValue placeholder="请选择有效套餐">{(() => { const p = preview.targets?.find(p => p.id === target); return p ? `${p.label} · ${expiryDate(p.expires)} 到期` : '请选择有效套餐'; })()}</SelectValue></SelectTrigger>
                    <SelectContent>{preview.targets?.map(p => <SelectItem key={p.id} value={p.id}>{p.label} · {expiryDate(p.expires)} 到期</SelectItem>)}</SelectContent>
                  </Select>
                </Field>}
                <dl>
                  <div>
                    <dt>本次增加</dt>
                    <dd>
                      {size(preview.quota)} · {preview.kind === 'addon' ? '不增加天数' : ruleLabel(preview)}
                    </dd>
                  </div>
                  <div>
                    <dt>{preview.package_billing ? '兑换后可用流量' : '兑换后预计剩余'}</dt>
                    <dd>
                      {preview.package_billing ? size(preview.after_quota) : remainingAfter(preview.after_quota, used) === null
                        ? '暂无法读取，请刷新订阅状态'
                        : size(remainingAfter(preview.after_quota, used)!)}
                    </dd>
                  </div>
                  {!preview.package_billing && (
                    <div>
                      <dt>兑换后总额度</dt>
                      <dd>{size(preview.after_quota)}</dd>
                    </div>
                  )}
                  <div>
                    <dt>{preview.package_billing ? '本次权益有效期至' : '兑换后有效期至'}</dt>
                    <dd>{expiryDate(preview.after_expires)}</dd>
                  </div>
                </dl>
                <p className="small muted">
                  {preview.package_billing ? '有效套餐未到期时，新套餐接在其后计时，流量兑换后立即可用。加流量卡跟随所选套餐到期。' : '已用流量不清零。'}确认后卡密将绑定当前账号，不可转让。
                </p>
                <Button
                  type="button"
                  disabled={work.busy || (preview.kind === 'addon' && !target)}
                  onClick={() =>
                    void work.run(async () => {
                      await api('redeem', { code, target: target || undefined });
                      clearPendingCard();
                      setDone(true);
                      setPreview(null);
                      setCode('');
                      await onChanged();
                    })
                  }
                >
                  确认兑换
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setPreview(null)}
                >
                  返回修改
                </Button>
              </div>
            ) : (
              <Button type="submit" disabled={work.busy}>
                查看卡密内容
              </Button>
            )}
          </form>
        )}
      </section>
    </>
  );
}
export type Incident = {
  id: string;
  title: string;
  body: string;
  status: string;
  updated: number;
};
export type Status = {
  incidents: Incident[];
  events: { name: string; status: string; created: number }[];
};
export function ServiceBrief({ navigate }: { navigate: Nav }) {
  const { data } = useData<Status>('service-status');
  const active = data?.incidents.filter((i) => i.status !== 'resolved') || [];
  if (!active.length) return null;
  return (
    <div className="account-alert" role="status">
      <span>
        {active[0].title}
        {active.length > 1 ? ` · 另有 ${active.length - 1} 条服务动态` : ''}
      </span>
      <button className="text-link" onClick={() => navigate('status')}>
        查看详情 →
      </button>
    </div>
  );
}
export const states: Record<string, string> = {
  online: '在线',
  offline: '离线',
  unknown: '待确认',
  paused: '已暂停',
  pending: '同步中',
  investigating: '正在排查',
  maintenance: '维护中',
  resolved: '已恢复',
};
export function ServiceStatus() {
  const { data, placeholder } = useData<Status>('service-status');
  return (
    <>
      <PageTitle
        eyebrow="SERVICE"
        title="服务状态"
        description="节点状态、维护安排与最近变化。"
      />
      <div className="feature-split">
        <div>
          <NodeStatus />
          <section className="section">
            <h2>维护与事件</h2>
            {placeholder}
            {data && !data.incidents.length && (
              <p className="muted">暂无维护事件。</p>
            )}
            {data?.incidents.map((i) => (
              <article className="incident" key={i.id}>
                <small>
                  {states[i.status]} · {when(i.updated)}
                </small>
                <h3>{i.title}</h3>
                <p>{i.body}</p>
              </article>
            ))}
          </section>
        </div>
        <section className="section">
          <h2>节点状态记录</h2>
          <p className="small muted">
            仅反映面板报告的状态，不代表端到端连接测速。
          </p>
          {data && !data.events.length && (
            <p className="empty">开始监测后会显示状态变化。</p>
          )}
          {data?.events.map((e, i) => (
            <div className="event-row" key={i}>
              <span>
                {e.name} · {states[e.status] || e.status}
              </span>
              <small>{when(e.created)}</small>
            </div>
          ))}
        </section>
      </div>
    </>
  );
}
