import { expiryLabel, ruleLabel } from './cycles';
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from 'react';
import { remainingAfter } from './experience';
import { EmailCode } from './email-code';
import { OperationsReadiness } from './admin-support';
import QRCode from 'qrcode';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from '@/components/ui/table';
import { api } from './api';
import { Contact, PageTitle, NodeStatus } from './content';

type Nav = (view: string) => void;
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
function useWork() {
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
function useData<T>(path: string, poll = 0) {
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
      {recovery.data && !recovery.data.email_verified && !recovery.data.recovery_created && !dismissed && (
        <div className="journey-alert">
          <span>还未设置找回方式。保存恢复码，忘记密码时也能找回账号。</span>
          <div className="actions">
            <button className="text-link" onClick={() => navigate('sessions')}>
              设置恢复码 →
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
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="feature-field">
      <span>{label}</span>
      {children}
    </label>
  );
}
function form(e: FormEvent<HTMLFormElement>) {
  e.preventDefault();
  return Object.fromEntries(new FormData(e.currentTarget));
}
function Choice({
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
                    await QRCode.toDataURL(url, {
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
    [code, setCode] = useState(''),
    [preview, setPreview] = useState<Preview | null>(null),
    [done, setDone] = useState(false);
  const [target, setTarget] = useState('');
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
              {subscription?.pending
                ? '额度已到账，正在同步节点，无需重复兑换。'
                : subscription?.url
                  ? '订阅已就绪，现在可以导入客户端。'
                  : '额度已到账，请到首页查看订阅状态。'}
            </p>
            <Button
              onClick={() =>
                navigate(
                  subscription?.url && !subscription.pending
                    ? 'subscription'
                    : 'home',
                )
              }
            >
              {subscription?.url && !subscription.pending
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
                    <SelectTrigger><SelectValue placeholder="请选择有效套餐" /></SelectTrigger>
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
                    <dt>兑换后预计剩余</dt>
                    <dd>
                      {preview.package_billing ? size(preview.after_quota) : remainingAfter(preview.after_quota, used) === null
                        ? '暂无法读取，请刷新订阅状态'
                        : size(remainingAfter(preview.after_quota, used)!)}
                    </dd>
                  </div>
                  <div>
                    <dt>{preview.package_billing ? '兑换后预计可用额度' : '兑换后总额度'}</dt>
                    <dd>{size(preview.after_quota)}</dd>
                  </div>
                  <div>
                    <dt>{preview.package_billing ? '本次权益有效期至' : '兑换后有效期至'}</dt>
                    <dd>{expiryDate(preview.after_expires)}</dd>
                  </div>
                </dl>
                <p className="small muted">
                  {preview.package_billing ? '套餐兑换即计时，不延长旧套餐。加流量卡跟随所选套餐到期。' : '已用流量不清零。'}确认后卡密将绑定当前账号，不可转让。
                </p>
                <Button
                  type="button"
                  disabled={work.busy || (preview.kind === 'addon' && !target)}
                  onClick={() =>
                    void work.run(async () => {
                      await api('redeem', { code, target: target || undefined });
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
type Ticket = {
  unread?: number;
  id: string;
  subject: string;
  category: string;
  status: string;
  created: number;
  updated: number;
  username?: string;
};
const ticketStatus: Record<string, string> = {
  waiting: '等待回复',
  replied: '已回复',
  closed: '已关闭',
};
export type TicketDraft = {
  subject: string;
  body: string;
  category: string;
  replies: Record<string, string>;
};
export function Tickets({
  staff = false,
  draft,
}: {
  staff?: boolean;
  draft?: TicketDraft;
}) {
  const path = staff ? 'admin/tickets' : 'tickets',
    { data, reload, placeholder } = useData<{ tickets: Ticket[] }>(
      path,
      staff ? 0 : 30000,
    ),
    work = useWork();
  const [selected, setSelected] = useState<{
      ticket: Ticket;
      messages: { id: number; staff: number; body: string; created: number }[];
    } | null>(null),
    [creating, setCreating] = useState(!!(draft?.subject || draft?.body)),
    [reply, setReply] = useState('');
  useEffect(() => {
    if (staff || !selected) return;
    let live = true;
    const id = selected.ticket.id;
    const refresh = async () => {
      if (document.visibilityState !== 'visible') return;
      try {
        const result = await api<NonNullable<typeof selected>>(
          path + '?id=' + encodeURIComponent(id),
        );
        if (live) {
          setSelected((current) =>
            current?.ticket.id === id ? result : current,
          );
          const last = result.messages.at(-1);
          if (last) await api('tickets/read', { id, message_id: last.id });
          await reload();
        }
      } catch {
        /* Keep the user's reply draft; list polling exposes connection errors. */
      }
    };
    const timer = window.setInterval(refresh, 30000);
    document.addEventListener('visibilitychange', refresh);
    return () => {
      live = false;
      clearInterval(timer);
      document.removeEventListener('visibilitychange', refresh);
    };
  }, [staff, selected?.ticket.id, path]);
  useEffect(() => {
    if (
      (selected || creating) &&
      window.matchMedia('(max-width:700px)').matches
    )
      document
        .getElementById('ticket-detail')
        ?.scrollIntoView({ block: 'start' });
  }, [selected?.ticket.id, creating]);
  const open = async (id: string) => {
    const result = await api<NonNullable<typeof selected>>(path + '?id=' + encodeURIComponent(id));
    setSelected(result);
    const last = result.messages.at(-1);
    if (!staff && last) {
      await api('tickets/read', { id, message_id: last.id });
      await reload();
    }
    setCreating(false);
    setReply(draft?.replies[id] || '');
  };
  return (
    <>
      <PageTitle
        eyebrow="SUPPORT"
        title={staff ? '工单处理' : '我的工单'}
        description={
          staff
            ? '查看问题、回复用户并关闭已解决的工单。'
            : '连接、兑换或账号问题，在这里与管理员沟通。'
        }
      />
      {work.feedback}
      {!staff && <TicketEmailPreference />}
      <div
        className={
          'feature-split ticket-workspace ' +
          (selected || creating ? 'ticket-detail-open' : '')
        }
      >
        <section className="section">
          <div className="section-heading">
            <h2>{staff ? '最近工单' : '问题记录'}</h2>
            <Button
              variant="outline"
              onClick={() => {
                setCreating(true);
                setSelected(null);
              }}
            >
              新建工单
            </Button>
          </div>
          {placeholder}
          {data && !data.tickets.length && (
            <p className="empty">暂时没有工单。</p>
          )}
          {data?.tickets.map((t) => (
            <button
              key={t.id}
              className={
                'ticket-row ' + (selected?.ticket.id === t.id ? 'selected' : '')
              }
              onClick={() => void work.run(() => open(t.id))}
            >
              <strong>{t.subject}</strong>
              <span>
                {!staff && !!t.unread && <strong className="ticket-unread">{t.unread} 条未读 · </strong>}{ticketStatus[t.status]}
                {staff ? ' · ' + t.username : ''}
              </span>
              <small>{when(t.updated)}</small>
            </button>
          ))}
        </section>
        <section className="section" id="ticket-detail">
          {(selected || creating) && (
            <button
              className="text-link ticket-back"
              onClick={() => {
                setSelected(null);
                setCreating(false);
              }}
            >
              ← 返回工单列表
            </button>
          )}
          {creating ? (
            <form
              onSubmit={(e) => {
                const values = form(e);
                void work.run(async () => {
                  const r = await api<{ id: string }>(path, values);
                  if (draft) {
                    draft.subject = '';
                    draft.body = '';
                    draft.category = 'connection';
                  }
                  await reload();
                  await open(r.id);
                });
              }}
            >
              <h2>新建工单</h2>
              <Field label="问题类型">
                <Choice
                  name="category"
                  label="问题类型"
                  initial={draft?.category || 'connection'}
                  onChange={(value) => {
                    if (draft) draft.category = value;
                  }}
                  options={{
                    connection: '连接问题',
                    redeem: '卡密兑换',
                    account: '账号问题',
                    other: '其他问题',
                  }}
                />
              </Field>
              <Field label="标题">
                <Input
                  name="subject"
                  required
                  maxLength={100}
                  defaultValue={draft?.subject}
                  onChange={(e) => {
                    if (draft) draft.subject = e.target.value;
                  }}
                />
              </Field>
              <Field label="描述">
                <textarea
                  name="body"
                  defaultValue={draft?.body}
                  onChange={(e) => {
                    if (draft) draft.body = e.target.value;
                  }}
                  required
                  maxLength={4000}
                  rows={6}
                  placeholder="请说明设备、客户端、出现的提示和问题时间。不要发送密码或完整订阅链接。"
                />
              </Field>
              <Button type="submit" disabled={work.busy}>
                提交工单
              </Button>
            </form>
          ) : selected ? (
            <>
              <div className="section-heading">
                <h2>{selected.ticket.subject}</h2>
                <span className="small muted">
                  {ticketStatus[selected.ticket.status]}
                </span>
              </div>
              <div className="ticket-messages">
                {selected.messages.map((m, i) => (
                  <article key={i} className={m.staff ? 'staff-reply' : ''}>
                    <small>
                      {m.staff ? '管理员' : '用户'} · {when(m.created)}
                    </small>
                    <p>{m.body}</p>
                  </article>
                ))}
              </div>
              {selected.ticket.status !== 'closed' && (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    void work.run(async () => {
                      await api(path, { id: selected.ticket.id, body: reply });
                      if (draft) delete draft.replies[selected.ticket.id];
                      await open(selected.ticket.id);
                      await reload();
                    });
                  }}
                >
                  <Field label="补充说明 / 回复">
                    <textarea
                      value={reply}
                      onChange={(e) => {
                        setReply(e.target.value);
                        if (draft)
                          draft.replies[selected.ticket.id] = e.target.value;
                      }}
                      required
                      maxLength={4000}
                      rows={4}
                    />
                  </Field>
                  <div className="actions">
                    <Button type="submit" disabled={work.busy}>
                      发送回复
                    </Button>
                    <Button
                      variant="outline"
                      type="button"
                      disabled={work.busy}
                      onClick={() =>
                        void work.run(async () => {
                          await api(path, {
                            id: selected.ticket.id,
                            close: true,
                          });
                          await open(selected.ticket.id);
                          await reload();
                        })
                      }
                    >
                      问题已解决，关闭
                    </Button>
                  </div>
                </form>
              )}
            </>
          ) : (
            <div className="empty">
              <h2>有什么可以帮你？</h2>
              <p>选择左侧工单查看回复，或创建一个新问题。</p>
              <p className="small muted">
                此页每 30 秒检查回复，返回页面时也会更新。
              </p>
            </div>
          )}
        </section>
      </div>
    </>
  );
}
type Session = {
  id: string;
  agent: string;
  ip: string;
  created: number;
  seen: number;
  current: boolean;
};
function TicketEmailPreference() {
  const { data, reload } = useData<{ ticket_email: boolean; available: boolean }>('notifications');
  const work = useWork();
  return <div className="notification-preference">
    <label><input type="checkbox" checked={!!data?.ticket_email} disabled={!data || work.busy || (!data.available && !data.ticket_email)} onChange={e => {
      const enabled = e.target.checked;
      void work.run(async () => { await api('notifications', { ticket_email: enabled }); await reload(); });
    }} /> 有新回复时通过邮件提醒我</label>
    {data && !data.available && <small className="muted">需绑定邮箱且邮件服务可用。</small>}
    {work.feedback}
  </div>;
}

function ChangeEmail({ email }: { email: string }) {
  const [next, setNext] = useState(''), [password, setPassword] = useState(''), [oldCode, setOldCode] = useState(''), [newCode, setNewCode] = useState('');
  const work = useWork();
  return <section className="section"><h2>登录邮箱</h2>
    <p className="small muted">{email || '尚未绑定邮箱'}</p>
    <details className="email-change-disclosure"><summary>{email ? '更换邮箱' : '绑定邮箱'}</summary>
    <p className="small muted">完成后使用新邮箱登录，其他登录会话和旧恢复码失效，订阅不变。</p>
    <form onSubmit={e => { e.preventDefault(); void work.run(async () => {
      await api('account/email', { email: next, password, old_code: oldCode, new_code: newCode });
      setPassword(''); window.location.reload();
    }); }}>
      <Field label="当前密码"><Input type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} /></Field>
      {email && <><p className="small">验证原邮箱</p><EmailCode email={email} purpose="change_old" password={password} value={oldCode} onChange={setOldCode} /></>}
      <Field label="新邮箱"><Input type="email" autoComplete="email" required maxLength={254} value={next} onChange={e => setNext(e.target.value)} /></Field>
      <EmailCode email={next} purpose="change_new" password={password} value={newCode} onChange={setNewCode} />
      {work.feedback}<Button type="submit" disabled={work.busy}>确认更换邮箱</Button>
      {email && <p className="small muted">原邮箱无法收信？请联系支持核实身份。</p>}
    </form></details></section>;
}

export function DeleteAccount({ username, userId, onDeleted, disabled = false }: {
  username: string; userId?: string; onDeleted?: () => void; disabled?: boolean;
}) {
  const [open, setOpen] = useState(false), [password, setPassword] = useState(''), [confirmation, setConfirmation] = useState(''), [accepted, setAccepted] = useState(false);
  const work = useWork();
  return <>
    <Button variant="outline" className="delete-account-button" disabled={disabled} onClick={() => setOpen(true)}>{userId ? '删除账号' : '注销账号'}</Button>
    <Dialog open={open} onOpenChange={value => { if (!work.busy) { if (accepted && !value) { window.location.href = '/#/login'; return; } setOpen(value); setPassword(''); setConfirmation(''); } }}>
      <DialogContent>
        <DialogTitle>{accepted ? '删除处理中' : userId ? `删除 ${username}？` : '永久注销账号？'}</DialogTitle>
        <DialogDescription>{accepted ? '账号已停用。系统正在清理节点和关联数据，失败会自动重试。' : '账号、套餐、剩余流量、用量记录和工单将删除，订阅失效，已兑换卡密不能再次使用。此操作不可撤销。'}</DialogDescription>
        {accepted ? <Button onClick={() => { window.location.hash = '/login'; window.location.reload(); }}>返回登录</Button> : <form onSubmit={e => {
          e.preventDefault(); void work.run(async () => {
            await api(userId ? 'admin/user-delete' : 'account/delete', userId ? { id: userId } : { password, confirmation });
            setPassword(''); setConfirmation('');
            if (userId) { setOpen(false); onDeleted?.(); } else setAccepted(true);
          });
        }}>
          <p className="small muted">历史备份及邮件服务商日志不在本次即时清理范围。</p>
          {!userId && <><Field label="当前密码"><Input required type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /></Field>
          <Field label={`输入完整账号确认：${username}`}><Input required autoComplete="off" value={confirmation} onChange={e => setConfirmation(e.target.value)} /></Field></>}
          {work.feedback}
          <div className="actions"><Button type="button" variant="outline" disabled={work.busy} onClick={() => { setOpen(false); setPassword(''); setConfirmation(''); }}>取消</Button><Button type="submit" variant="destructive" disabled={work.busy || (!userId && confirmation !== username)}>{work.busy ? '正在提交…' : '确认永久删除'}</Button></div>
        </form>}
      </DialogContent>
    </Dialog>
  </>;
}

export function Sessions() {
  const { data, reload, placeholder } = useData<{
      sessions: Session[];
      recovery_created: number | null;
      email?: string;
      username?: string;
      admin?: boolean;
    }>('sessions'),
    work = useWork();
  const [code, setCode] = useState(''),
    [password, setPassword] = useState(''),
    [target, setTarget] = useState<Session | null>(null);
  return (
    <>
      <PageTitle
        eyebrow="SECURITY"
        title="邮箱与账号安全"
        description="管理登录邮箱、网站会话与找回方式。"
      />
      {work.feedback}
      {data && <ChangeEmail email={data.email || ''} />}
      <div className="feature-split">
        <section className="section">
          <h2>网站登录会话</h2>
          <p className="small muted">网站登录记录，不代表代理客户端连接。</p>
          {placeholder}
          {data?.sessions.map((s) => (
            <div className="session-row" key={s.id}>
              <div>
                <strong>{s.current ? '当前会话' : '其他登录'}</strong>
                <p className="small session-agent">{s.agent || '未知浏览器'}</p>
                <p className="small muted">
                  {s.ip || 'IP 未记录'} · 最近活动 {when(s.seen)}
                </p>
              </div>
              {!s.current && (
                <Button variant="outline" onClick={() => setTarget(s)}>
                  退出此会话
                </Button>
              )}
            </div>
          ))}
        </section>
        <section className="section">
          <h2>一次性恢复码</h2>
          <p className="muted">
            忘记密码时，可用用户名和恢复码自助找回。请离线保存，不要分享。
          </p>
          <p className="small muted">
            {data?.recovery_created
              ? '上次生成：' + when(data.recovery_created)
              : '尚未生成恢复码'}
          </p>
          {code ? (
            <>
              <code className="recovery-code">{code}</code>
              <p className="small muted">
                只在本次显示。使用一次即失效；重新生成会替换旧码。
              </p>
              <Button
                onClick={() =>
                  void work.run(async () => {
                    await navigator.clipboard.writeText(code);
                    work.setMessage('恢复码已复制，请妥善保存');
                  })
                }
              >
                复制恢复码
              </Button>
              <Button variant="ghost" onClick={() => setCode('')}>
                我已保存，隐藏
              </Button>
            </>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void work.run(async () => {
                  const r = await api<{ code: string }>('recovery-code', {
                    password,
                  });
                  setPassword('');
                  setCode(r.code);
                  await reload();
                });
              }}
            >
              <Field label="输入当前密码以生成新恢复码">
                <Input
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </Field>
              <Button type="submit" disabled={work.busy}>
                {data?.recovery_created ? '替换旧恢复码' : '生成恢复码'}
              </Button>
            </form>
          )}
        </section>
      </div>
      {data?.username && !data.admin && <section className="section"><h2>注销账号</h2><p className="small muted">永久删除账号与关联数据。</p><DeleteAccount username={data.username} /></section>}
      <Dialog open={!!target} onOpenChange={(v) => !v && setTarget(null)}>
        <DialogContent>
          <DialogTitle>退出这个登录会话？</DialogTitle>
          <DialogDescription>
            该浏览器需要重新登录。不会中断代理客户端的连接。
          </DialogDescription>
          {work.feedback}
          <Button
            disabled={work.busy}
            onClick={() =>
              void work.run(async () => {
                await api('sessions/revoke', { id: target?.id });
                setTarget(null);
                await reload();
              })
            }
          >
            确认退出
          </Button>
        </DialogContent>
      </Dialog>
    </>
  );
}
export function Recover({ navigate }: { navigate: Nav }) {
  const [legacy, setLegacy] = useState(false);
  const [email, setEmail] = useState('');
  const [emailCode, setEmailCode] = useState('');
  const work = useWork(),
    [done, setDone] = useState(false);
  return (
    <section className="auth">
      <PageTitle
        eyebrow="RECOVERY"
        title="找回账号"
        description={legacy ? '使用之前保存的一次性恢复码重设密码。' : '验证注册邮箱，重新设置密码。'}
      />
      {work.feedback}
      {done ? (
        <>
          <p>密码已更新，所有网站登录已退出，请重新登录。</p>
          <Button onClick={() => navigate('login')}>返回登录</Button>
        </>
      ) : (
        <form
          onSubmit={(e) => {
            const values = form(e);
            void work.run(async () => {
              if (values.new_password !== values.confirm)
                throw new Error('两次输入的密码不一致');
              await api(legacy ? 'recover' : 'email/reset', legacy ? values : {
                email, email_code: emailCode, new_password: values.new_password,
              });
              setDone(true);
            });
          }}
        >
          <button type="button" className="text-link" onClick={() => setLegacy(!legacy)}>
            {legacy ? '改用邮箱验证码找回' : '原用户名账号 / 使用恢复码找回'}
          </button>
          <Field label={legacy ? '邮箱 / 原用户名' : '注册邮箱'}>
            <Input
              name="username"
              required
              autoComplete="username"
              maxLength={254}
              type={legacy ? 'text' : 'email'}
              value={email}
              onChange={e => setEmail(e.target.value)}
            />
          </Field>
          {legacy ? <Field label="一次性恢复码">
            <Input name="code" required autoComplete="off" maxLength={100} />
          </Field> : <EmailCode email={email} purpose="reset" value={emailCode} onChange={setEmailCode} />}
          <Field label="新密码">
            <Input
              type="password"
              name="new_password"
              required
              autoComplete="new-password"
              minLength={10}
              maxLength={128}
            />
          </Field>
          <Field label="再次输入新密码">
            <Input
              type="password"
              name="confirm"
              required
              autoComplete="new-password"
              minLength={10}
              maxLength={128}
            />
          </Field>
          <Button type="submit" disabled={work.busy}>
            重设密码
          </Button>
          <p className="small muted">
            {legacy ? '没有保存恢复码？请联系管理员协助找回。' : '无法访问注册邮箱？请联系管理员协助找回。'}不要发送密码、验证码或完整订阅链接。
          </p>
          <Contact support={undefined} compact />
        </form>
      )}
    </section>
  );
}
type Incident = {
  id: string;
  title: string;
  body: string;
  status: string;
  updated: number;
};
type Status = {
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
const states: Record<string, string> = {
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
type Ops = {
  counts: Record<string, number>;
  budgets: {
    id: number;
    name: string;
    up: number | null;
    down: number | null;
    total: number | null;
    reset: string;
    enabled: boolean;
  }[];
  budgets_at: number;
  backup_at: number | null;
  batches: {
    label: string;
    created: number;
    total: number;
    redeemed: number;
    available: number;
    revoked: number;
    expired: number;
  }[];
  status: Status;
};
export function Operations({
  navigate,
  onMembers,
}: {
  navigate: Nav;
  onMembers?: (scope: string) => void;
}) {
  const { data, reload, placeholder } = useData<Ops>('admin/operations'),
    work = useWork(),
    [incident, setIncident] = useState<Incident | null>(null);
  return (
    <>
      <PageTitle
        eyebrow="OPERATIONS"
        title="运营概览"
        description="优先处理待办，及时发现服务异常。"
      />
      <div className="actions">
        <Button onClick={() => navigate('admin')}>生成卡密</Button>
        <Button variant="outline" onClick={() => navigate('admin_tickets')}>
          处理工单
        </Button>
        <Button variant="ghost" onClick={() => void reload()}>
          刷新
        </Button>
      </div>
      {placeholder}
      {work.feedback}
      <OperationsReadiness />
      {data && (
        <>
          <div className="ops-metrics">
            {[
              ['用户总数', 'users'],
              ['有效订阅', 'active'],
              ['7 天内到期', 'expiring'],
              ['等待同步', 'pending'],
              ['同步异常', 'sync_errors'],
              ['待回复工单', 'waiting_tickets'],
            ].map(([label, key]) => (
              <button
                key={key}
                onClick={() =>
                  key === 'waiting_tickets'
                    ? navigate('admin_tickets')
                    : onMembers
                      ? onMembers(key === 'users' ? 'all' : key)
                      : navigate('admin')
                }
              >
                <span>{label}</span>
                <strong>{data.counts[key] || 0}</strong>
              </button>
            ))}
          </div>
          <section className="section">
            <div className="section-heading">
              <h2>节点代理预算</h2>
              <span className="small muted">
                更新于 {when(data.budgets_at)}
              </span>
            </div>
            <p className="small muted">
              这是面板内代理累计流量，不含其他进程与系统开销，不等于服务商整机计费流量。
            </p>
            {(!data.budgets_at ||
              Date.now() / 1000 - data.budgets_at > 900) && (
              <p className="message error">
                预算数据暂未更新，请检查面板连接。
              </p>
            )}
            <div className="node-budgets">
              {data.budgets.map((b) => (
                <div key={b.id}>
                  <h3>{b.name}</h3>
                  <strong>
                    {b.up === null || b.down === null
                      ? '未知'
                      : ((b.up + b.down) / 1e12).toFixed(3)}{' '}
                    /{' '}
                    {b.total ? (b.total / 1e12).toFixed(0) + ' TB' : '未设上限'}
                  </strong>
                  <p className="small muted">
                    {b.reset === 'never'
                      ? '累计额度 · 不自动重置'
                      : '重置方式：' + b.reset}{' '}
                    · {b.enabled ? '已启用' : '已暂停'}
                  </p>
                  {b.total &&
                  b.up !== null &&
                  b.down !== null &&
                  (b.up + b.down) / b.total >= 0.9 ? (
                    <p className="message error">
                      已使用至少 90%，请检查额度。
                    </p>
                  ) : null}
                </div>
              ))}
            </div>
          </section>
          <div className="feature-split">
            <section className="section">
              <h2>发布服务事件</h2>
              <form
                key={incident?.id || 'new'}
                onSubmit={(e) => {
                  const values = form(e);
                  void work.run(async () => {
                    await api('admin/incident', {
                      ...values,
                      ...(incident ? { id: incident.id } : {}),
                    });
                    setIncident(null);
                    await reload();
                    work.setMessage('服务事件已发布');
                  });
                }}
              >
                <Field label="标题">
                  <Input
                    name="title"
                    required
                    maxLength={100}
                    defaultValue={incident?.title || ''}
                  />
                </Field>
                <Field label="状态">
                  <Choice
                    name="status"
                    label="事件状态"
                    initial={incident?.status || 'investigating'}
                    options={{
                      investigating: '正在排查',
                      maintenance: '维护中',
                      resolved: '已恢复',
                    }}
                  />
                </Field>
                <Field label="说明">
                  <textarea
                    name="body"
                    required
                    maxLength={4000}
                    rows={4}
                    defaultValue={incident?.body || ''}
                  />
                </Field>
                <Button type="submit" disabled={work.busy}>
                  {incident ? '更新事件' : '发布事件'}
                </Button>
                {incident && (
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => setIncident(null)}
                  >
                    取消编辑
                  </Button>
                )}
              </form>
              {data.status.incidents.map((i) => (
                <button
                  className="ticket-row"
                  key={i.id}
                  onClick={() => setIncident(i)}
                >
                  <strong>{i.title}</strong>
                  <span>{states[i.status]} · 编辑</span>
                </button>
              ))}
            </section>
            <section className="section">
              <h2>备份与服务</h2>
              <p>最近数据库备份：{when(data.backup_at)}</p>
              {(!data.backup_at ||
                Date.now() / 1000 - data.backup_at > 36 * 3600) && (
                <p className="message error">
                  超过 36 小时没有检测到备份，请检查备份任务。
                </p>
              )}
              <p className="small muted">
                仅检查备份文件时间，不代表已完成恢复演练。站内提醒与恢复码已启用；未配置邮件发送服务。
              </p>
              <Button variant="outline" onClick={() => navigate('status')}>
                查看服务状态
              </Button>
            </section>
          </div>
          <section className="section">
            <h2>最近发卡批次</h2>
            <Table>
              <TableHeader>
                <TableRow>
                  {[
                    '套餐 / 时间',
                    '总数',
                    '可分发',
                    '已兑换',
                    '已撤销',
                    '已过期',
                  ].map((t) => (
                    <TableHead key={t}>{t}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.batches.map((b, i) => (
                  <TableRow key={i}>
                    <TableCell>
                      {b.label}
                      <small className="block muted">{when(b.created)}</small>
                    </TableCell>
                    <TableCell>{b.total}</TableCell>
                    <TableCell>{b.available}</TableCell>
                    <TableCell>{b.redeemed}</TableCell>
                    <TableCell>{b.revoked}</TableCell>
                    <TableCell>{b.expired}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {!data.batches.length && <p className="empty">还没有发卡记录。</p>}
          </section>
        </>
      )}
    </>
  );
}
