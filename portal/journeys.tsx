import { useEffect, useState } from 'react';
import { readGuide, remainingTime, useNow } from './experience';
import {
  ArrowRight,
  ChevronRight,
  Copy,
  Globe2,
  Shield,
  LifeBuoy,
  History,
  KeyRound,
  Monitor,
  Ticket,
  BarChart3,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { NodeStatus, type Catalog } from './content';
import {
  AccountAttention,
  Connection,
  ServiceBrief,
  UsagePanel,
  PackageBalances,
  type PackageBalance,
} from './features';
type Nav = (view: string) => void;
type Subscription = {
  quota: number;
  used: number | null;
  expires: number;
  url: string | null;
  pending: boolean;
  rotating?: boolean;
  sync_error: string | null;
  usage_error: string | null;
  enabled: boolean | null;
  plan_name: string | null;
  billing?: {packages: PackageBalance[]; remaining: number; next_expiry: number} | null;
};
const volume = (n: number) =>
  (n / 1024 ** 3).toLocaleString('zh-CN', { maximumFractionDigits: 2 });
const deadline = (n: number) =>
  n >= 253402185600 ? '永久有效' : n
    ? new Date(n * 1000).toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
    : '尚未开通';
export function Dashboard({
  s,
  incidents,
  username,
  content,
  navigate,
  refresh,
  busy,
}: {
  s: Subscription;
  incidents: { id: string; title: string }[];
  username: string;
  content: Catalog | null;
  navigate: Nav;
  refresh: () => void;
  busy: boolean;
}) {
  const now = useNow();
  const [nodesOpen, setNodesOpen] = useState(false);
  const resetDates = (s.billing?.packages || []).filter(p => p.next_reset && p.next_reset < p.expires && (p.status === 'active' || p.status === 'exhausted')).map(p => p.next_reset!);
  const nextReset = resetDates.length ? Math.min(...resetDates) : 0;
  // Base packages run in parallel; the latest one is when service really ends.
  const activeBase = (s.billing?.packages || []).filter((p) => p.status === 'active' && p.kind !== 'addon');
  const latest = activeBase.length > 1 ? Math.max(...activeBase.map((p) => p.expires)) : 0;
  const finalExpiry = latest && deadline(latest) !== deadline(s.expires) ? latest : 0;
  const hasEntitlements = !!s.quota || !!s.billing?.packages.length;
  const remaining = s.used === null ? null : Math.max(0, s.quota - s.used),
    days = Math.ceil((s.expires - now) / 86400);
  const inactive =
      hasEntitlements && (days <= 0 || remaining === 0 || s.enabled === false),
    urgent =
      !!s.quota &&
      (days <= 7 || (remaining !== null && remaining / s.quota < 0.1));
  return (
    <div className="journey-dashboard">
      <header className="page-heading">
        <div>
          <h1>
            {!hasEntitlements ? '开通订阅' : inactive ? '订阅需要处理' : '我的订阅'}
          </h1>
        </div>
        <Button variant="ghost" disabled={busy} onClick={refresh}>
          刷新状态
        </Button>
      </header>
      <ServiceBrief incidents={incidents} navigate={navigate} />
      {!hasEntitlements ? (
        <section className="welcome-flow">
          <div>
            <span className="step-caption">01 / 开通订阅</span>
            <h2>有卡密，即可开始</h2>
            <div className="actions">
              <Button onClick={() => navigate('redeem')}>
                兑换卡密 <ArrowRight size={16} />
              </Button>
              <Button variant="ghost" onClick={() => navigate('plans')}>
                查看套餐
              </Button>
            </div>
          </div>
          <ol>
            <li>
              <span>1</span>
              <div>
                <strong>兑换卡密</strong>
              </div>
            </li>
            <li>
              <span>2</span>
              <div>
                <strong>安装客户端</strong>
              </div>
              <button className="text-link" onClick={() => navigate('guide')}>
                去下载
              </button>
            </li>
            <li>
              <span>3</span>
              <div>
                <strong>导入并连接</strong>
              </div>
            </li>
          </ol>
        </section>
      ) : (
        <>
          {urgent && !inactive && (
            <div className="journey-alert">
              <span>
                {days <= 0
                  ? '订阅已到期'
                  : remaining === 0
                    ? '流量已用完'
                    : days <= 7
                      ? `订阅剩余 ${remainingTime(s.expires, now)}`
                      : '剩余流量不足 10%'}
              </span>
              <button className="text-link" onClick={() => navigate('redeem')}>
                兑换续费 →
              </button>
            </div>
          )}
          <div className="home-primary">
            <section className="quota-sheet">
              <div className="section-heading">
                <h2>{s.plan_name || '当前订阅'}</h2>
                <span className="quiet-badge">
                  {s.pending
                    ? s.url ? '可用 · 部分同步中' : '同步中'
                    : inactive
                      ? '待恢复'
                      : s.usage_error || s.enabled === null || s.used === null
                        ? '状态待确认'
                        : '使用中'}
                </span>
              </div>
              <span className="muted">剩余流量</span>
              <p className="quota-value">
                {remaining === null ? '—' : volume(remaining)}
                <span>GiB</span>
              </p>
              <Progress
                aria-label="剩余流量比例"
                value={
                  remaining === null
                    ? null
                    : s.quota > 0 ? Math.min(100, (remaining / s.quota) * 100) : 0
                }
              />
              <div className="quota-meta">
                <span>
                  已用 {s.used === null ? '—' : volume(s.used)} /{' '}
                  {volume(s.quota)} GiB
                </span>
                <button className="text-link" onClick={() => navigate('usage')}>
                  用量明细
                </button>
              </div>
              <dl className="subscription-facts">
                <div>
                  <dt>{s.billing && s.billing.packages.filter(p => p.status === 'active' && p.kind !== 'addon').length > 1 ? '最近到期' : '到期时间'}</dt>
                  <dd>{deadline(s.expires)}</dd>
                </div>
                <div>
                  <dt>{finalExpiry > s.expires ? '最晚到期' : nextReset ? '下次流量重置' : '剩余时间'}</dt>
                  <dd>{finalExpiry > s.expires ? deadline(finalExpiry) : nextReset ? deadline(nextReset) : remainingTime(s.expires, now)}</dd>
                </div>
              </dl>
            </section>
            <div className="home-connect">
              {inactive ? (
                <section className="renew-sheet">
                  <Ticket size={24} />
                  <h2>
                    {s.enabled === false && days > 0 && remaining !== 0
                      ? '订阅已暂停'
                      : '续费后继续连接'}
                  </h2>
                  <p className="muted">
                    {s.enabled === false && days > 0 && remaining !== 0
                      ? '请联系管理员确认订阅状态。'
                      : days > 0 && remaining === 0
                        ? '套餐仍有效，可兑换加流量卡继续使用。'
                        : '兑换套餐卡，重新开通。'}
                  </p>
                  <Button
                    onClick={() =>
                      navigate(
                        s.enabled === false && days > 0 && remaining !== 0
                          ? 'tickets'
                          : 'redeem',
                      )
                    }
                  >
                    {s.enabled === false && days > 0 && remaining !== 0
                      ? '联系支持'
                      : '兑换续费'}
                  </Button>
                  {!(s.enabled === false && days > 0 && remaining !== 0) && (
                    <button className="text-link" onClick={() => navigate('plans')}>
                      查看套餐 →
                    </button>
                  )}
                  <button
                    className="text-link"
                    onClick={() => navigate('subscription')}
                  >
                    查看已有订阅
                  </button>
                </section>
              ) : (
                <Connection
                  s={s}
                  navigate={navigate}
                  onChanged={async () => refresh()}
                  compact
                />
              )}
            </div>
          </div>
          {(s.sync_error || s.usage_error || s.pending) && (
            <p className="message" role="status">
              {s.sync_error || s.usage_error || '正在同步节点，无需重复兑换。'}
            </p>
          )}
        </>
      )}
      <div className="home-secondary">
        <div>
          {s.quota > 0 ? (
            <UsagePanel compact navigate={navigate} />
          ) : (
            <div className="section">
              <div className="section-heading"><h2>开始使用</h2></div>
              <button className="journey-row" onClick={() => navigate('guide')}>
                <Monitor size={18} /><span><strong>连接指南</strong></span><ChevronRight size={16} />
              </button>
            </div>
          )}
        </div>
        <div>
          <div className="section-heading">
            <h2>服务与支持</h2>
            <button className="text-link" onClick={() => navigate('status')}>
              查看状态 →
            </button>
          </div>
          <details
            className="service-disclosure"
            onToggle={(e) => setNodesOpen(e.currentTarget.open)}
          >
            <summary>
              节点状态<span>查看节点</span>
            </summary>
            {nodesOpen && <NodeStatus />}
          </details>
          <button className="journey-row" onClick={() => navigate('tickets')}>
            <LifeBuoy size={18} />
            <span>
              <strong>联系支持</strong>
            </span>
            <ChevronRight size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}
export function AccountHub({
  username,
  admin,
  s,
  navigate,
  logout,
  busy,
}: {
  username: string;
  admin: boolean;
  s: Subscription;
  navigate: Nav;
  logout: () => void;
  busy: boolean;
}) {
  const groups = [
    {
      title: '我的订阅',
      items: [
        ['subscription', '连接与订阅', Globe2],
        ['usage', '用量明细', BarChart3],
        ['history', '兑换记录', History],
        ['orders', '支付订单', History],
      ],
    },
    {
      title: '支持与帮助',
      items: [
        ['tickets', '我的工单', LifeBuoy],
        ['help', '常见问题', LifeBuoy],
        ['status', '服务状态', Globe2],
      ],
    },
    {
      title: '账号安全',
      items: [
        ['security', '登录密码', KeyRound],
        ['sessions', '邮箱与登录设备', Shield],
      ],
    },
  ];
  return (
    <>
      <header className="page-heading">
        <div className="account-identity">
          <span className="identity-avatar">
            {username.slice(0, 1).toUpperCase()}
          </span>
          <div>
            <h1>我的账号</h1>
            <p className="muted account-email">{username}{admin ? ' · 管理员' : ''}</p>
          </div>
        </div>
        <Button variant="ghost" disabled={busy} onClick={logout}>
          退出登录
        </Button>
      </header>
      <AccountAttention username={username} navigate={navigate} />
      <div className="membership-strip">
        <div>
          <span className="muted">当前套餐</span>
          <strong>{s.plan_name || '尚未开通'}</strong>
        </div>
        <div>
          <span className="muted">{s.billing ? '最近到期' : '有效期至'}</span>
          <strong>{deadline(s.expires)}</strong>
        </div>
        <Button variant="outline" onClick={() => navigate('redeem')}>
          {s.quota ? '兑换续费' : '开通订阅'}
        </Button>
      </div>
      {s.billing && <PackageBalances packages={s.billing.packages} />}
      <div className="account-groups">
        {groups.map((g) => (
          <section key={g.title}>
            <h2>{g.title}</h2>
            {g.items.map(([id, label, Icon]) => {
              const Symbol = Icon as typeof Globe2;
              return (
                <button
                  key={String(id)}
                  className="journey-row"
                  onClick={() => navigate(String(id))}
                >
                  <Symbol size={18} />
                  <span>
                    <strong>{String(label)}</strong>
                  </span>
                  <ChevronRight size={16} />
                </button>
              );
            })}
          </section>
        ))}
      </div>
      {admin && (
        <section className="admin-entry">
          <div>
            <Shield size={20} />
            <div>
              <h2>管理工作台</h2>
            </div>
          </div>
          <Button variant="outline" onClick={() => navigate('operations')}>
            进入管理 <ArrowRight size={16} />
          </Button>
        </section>
      )}
    </>
  );
}
export function AdminNavigation({
  view,
  navigate,
}: {
  view: string;
  navigate: Nav;
}) {
  return (
    <nav className="admin-navigation" aria-label="管理工作台">
      <span>管理工作台</span>
      {[
        ['operations', '概览'],
        ['admin_users', '用户'],
        ['admin', '卡密'],
        ['admin_tickets', '工单'],
        ['admin_content', '公告与套餐'],
        ['home', '返回用户端 ↗'],
      ].map(([id, label]) => (
        <button
          key={id}
          aria-current={view === id ? 'page' : undefined}
          onClick={() => navigate(id)}
        >
          {label}
        </button>
      ))}
    </nav>
  );
}

const clients = {
  windows: {
    name: 'Windows',
    client: 'Clash Verge Rev',
    url: 'https://www.clashverge.dev/install.html',
    install: '通常选 x64，ARM 设备选 arm64。',
    connect: '启用 Jamie-Node 配置，选「规则」模式，打开「系统代理」。',
  },
  mac: {
    name: 'macOS',
    client: 'Clash Verge Rev',
    url: 'https://www.clashverge.dev/install.html',
    install: 'Apple 芯片选 Apple Silicon，Intel 芯片选 Intel。',
    connect: '启用 Jamie-Node 配置，选「规则」模式，打开「系统代理」。',
  },
  ios: {
    name: 'iPhone / iPad',
    client: 'Shadowrocket',
    url: 'https://apps.apple.com/app/shadowrocket/id932747118',
    install: '用你自己的 Apple 账号购买，部分商店地区不可下载。',
    connect: '选一个地区开启连接，「全局路由」选「配置」。',
  },
  android: {
    name: 'Android',
    client: 'Clash Meta for Android',
    url: 'https://github.com/MetaCubeX/ClashMetaForAndroid/releases/latest',
    install: '多数手机下载 arm64-v8a 版 APK（需 Android 7+）。',
    connect: '启用 Jamie-Node 配置，选「规则」模式，点击启动。',
  },
  linux: {
    name: 'Linux',
    client: 'Clash Verge Rev',
    url: 'https://www.clashverge.dev/install.html',
    install: '按发行版和架构安装对应软件包。',
    connect: '启用 Jamie-Node 配置，选「规则」模式，打开系统代理。',
  },
};
type Device = keyof typeof clients;
function initialDevice(): Device {
  if (typeof navigator === 'undefined') return 'windows';
  const ua = navigator.userAgent;
  return /iPhone|iPad/.test(ua) ||
    (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)
    ? 'ios'
    : /Android/.test(ua)
      ? 'android'
      : /Macintosh/.test(ua)
        ? 'mac'
        : /Linux/.test(ua)
          ? 'linux'
          : 'windows';
}
export function DeviceGuide({
  navigate,
  url,
  pending = false,
}: {
  navigate: Nav;
  url?: string | null;
  pending?: boolean;
}) {
  const [selected, setSelected] = useState<Device>(
      () => (readGuide()?.device as Device) || initialDevice(),
    ),
    [step, setStep] = useState(() => readGuide()?.step || 0),
    [message, setMessage] = useState('');
  useEffect(() => {
    try {
      sessionStorage.setItem(
        'jamie-guide',
        JSON.stringify({ device: selected, step }),
      );
    } catch {}
  }, [selected, step]);
  const c = clients[selected];
  const steps = ['安装客户端', '导入订阅', '开启并验证'];
  const importUrl = url
    ? url +
      (url.includes('?') ? '&' : '?') +
      'format=' +
      (selected === 'ios' ? 'shadowrocket' : 'clash')
    : null;
  return (
    <>
      <header className="page-heading">
        <div>
          <h1>在你的设备上连接</h1>
        </div>
        <button className="text-link" onClick={() => navigate('help')}>
          连接排查 →
        </button>
      </header>
      <div className="device-picker" role="group" aria-label="选择设备">
        {Object.entries(clients).map(([id, c]) => (
          <button
            key={id}
            aria-pressed={selected === id}
            onClick={() => {
              setSelected(id as Device);
              setStep(0);
              setMessage('');
            }}
          >
            {c.name}
          </button>
        ))}
      </div>
      <div className="guided-workspace">
        <nav className="guide-step-nav" aria-label="连接步骤">
          {steps.map((s, i) => (
            <button
              key={s}
              aria-current={step === i ? 'step' : undefined}
              onClick={() => {
                setStep(i);
                setMessage('');
              }}
            >
              <span>{i + 1}</span>
              <div>
                <strong>{s}</strong>
                {i === 0 && <small>{c.client}</small>}
              </div>
            </button>
          ))}
        </nav>
        <section className="guide-stage">
          <h2>{steps[step]}</h2>
          {message && (
            <p role="status" className="message">
              {message}
            </p>
          )}
          {step === 0 ? (
            <>
              <p>{c.install}</p>
              <a
                className="guide-download"
                href={c.url}
                target="_blank"
                rel="noreferrer"
              >
                下载 {c.client} ↗
              </a>
            </>
          ) : step === 1 ? (
            <>
              {importUrl ? (
                <div className="actions">
                  <Button
                    onClick={() => {
                      window.location.href =
                        selected === 'ios'
                          ? 'shadowrocket://add/sub://' + btoa(importUrl)
                          : (selected === 'android' ? 'clashmeta' : 'clash') +
                            '://install-config?url=' +
                            encodeURIComponent(importUrl) +
                            '&name=Jamie-Node';
                    }}
                  >
                    导入订阅 <ArrowRight size={16} />
                  </Button>
                  <Button
                    variant="outline"
                    onClick={async () => {
                      try {
                        await navigator.clipboard.writeText(importUrl);
                        setMessage('已复制');
                      } catch {
                        setMessage('复制失败，请到「连接与订阅」手动复制');
                      }
                    }}
                  >
                    <Copy size={16} />
                    复制链接
                  </Button>
                </div>
              ) : (
                <Button disabled={pending} onClick={() => navigate('home')}>
                  {pending
                    ? '订阅准备中…'
                    : '开通后获取订阅'}
                </Button>
              )}
              <details>
                <summary>没有自动打开客户端？</summary>
                <p>
                  {selected === 'ios'
                    ? '点击右上角「+」，选择 Subscribe，粘贴链接并保存。'
                    : '在客户端「订阅」或「配置」页新建 URL 配置，粘贴链接。'}
                </p>
              </details>
            </>
          ) : (
            <>
              <p>{c.connect}</p>
              <p className="small muted">
                能打开网页即成功；打不开先更新订阅或换个地区，并关闭其他 VPN。
              </p>
            </>
          )}
          <div className="guide-step-footer">
            <Button
              variant="ghost"
              disabled={step === 0}
              onClick={() => setStep(step - 1)}
            >
              上一步
            </Button>
            {step < 2 ? (
              <Button
                variant="outline"
                onClick={() => {
                  setStep(step + 1);
                  setMessage('');
                }}
              >
                {step === 0 ? '已安装，继续' : '已导入，继续'}{' '}
                <ArrowRight size={16} />
              </Button>
            ) : (
              <Button onClick={() => navigate('home')}>完成，返回首页</Button>
            )}
          </div>
        </section>
      </div>
    </>
  );
}
