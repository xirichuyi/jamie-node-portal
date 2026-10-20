import { Button } from '@/components/ui/button';
import {
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Check,
  Globe2,
  LifeBuoy,
  Megaphone,
  Package,
  RefreshCw,
  Ticket,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { api, lastRead } from './api';
import { expiryLabel, ruleLabel, type CycleRule } from './cycle-labels';
import { priceText } from './experience';
import { markNoticeRead, publicNotices } from './notice-entry';
import { PurchaseButton } from './payments';

export type Plan = CycleRule & {
  id: string;
  name: string;
  description: string;
  quota_gib: number;
  days: number;
  price_label: string;
  usdt_micros?: number;
  usdt_price?: string;
  badge: string;
  published: number;
  sort_order: number;
  revision: number;
};
export type Notice = {
  id: string;
  title: string;
  body: string;
  category: string;
  published: number;
  pinned: number;
  created: number;
  updated: number;
  revision: number;
};
export type Support = {
  contact_label: string;
  contact_url: string;
  contact_note: string;
  revision: number;
};
export type Catalog = { plans: Plan[]; notices: Notice[]; support: Support; package_billing?: boolean; payments_enabled?: boolean };
type Node = {
  id: number;
  name: string;
  status: string;
  heartbeat: number;
  latency_ms: number | null;
};
export type Telemetry = { checked_at: number; nodes: Node[] };
const when = (t: number) =>
  t
    ? new Date(t * 1000).toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      })
    : '等待首次采集';
const categoryLabel: Record<string, string> = {
  info: '使用须知',
  maintenance: '维护通知',
  update: '服务更新',
};
export function PageTitle({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <section className="intro">
      {eyebrow && <p className="eyebrow">{eyebrow}</p>}
      <h1>{title}</h1>
      {description && <p className="muted">{description}</p>}
    </section>
  );
}
export function SectionNav({
  view,
  navigate,
  disabled,
}: {
  view: string;
  navigate: (s: string) => void;
  disabled: boolean;
}) {
  return (
    <nav className="section-nav" aria-label="用户中心栏目">
      {[
        { id: 'home', label: '总览', Icon: Globe2 },
        { id: 'plans', label: '套餐', Icon: Package },
        { id: 'guide', label: '使用指南', Icon: BookOpen },
        { id: 'notices', label: '公告', Icon: Megaphone },
        { id: 'help', label: '帮助', Icon: LifeBuoy },
      ].map(({ id, label, Icon }) => (
        <button
          key={id}
          disabled={disabled}
          className={view === id ? 'current' : ''}
          aria-current={view === id ? 'page' : undefined}
          onClick={() => navigate(id)}
        >
          <Icon size={16} />
          {label}
        </button>
      ))}
    </nav>
  );
}
export function QuickActions({ navigate }: { navigate: (s: string) => void }) {
  return (
    <div className="quick-grid">
      {[
        {
          id: 'redeem',
          title: '兑换 / 续费',
          text: '卡密即时记账',
          Icon: Ticket,
        },
        {
          id: 'plans',
          title: '了解套餐',
          text: '按使用需求选择',
          Icon: Package,
        },
        {
          id: 'guide',
          title: '连接指南',
          text: '从导入到连接',
          Icon: BookOpen,
        },
      ].map(({ id, title, text, Icon }) => (
        <button className="quick-card" key={id} onClick={() => navigate(id)}>
          <span className="quick-icon">
            <Icon size={21} />
          </span>
          <span>
            <strong>{title}</strong>
            <small>{text}</small>
          </span>
          <ArrowUpRight size={17} />
        </button>
      ))}
    </div>
  );
}
export function Contact({
  support,
  compact = false,
}: {
  support: Support | undefined;
  compact?: boolean;
}) {
  return (
    <div className={compact ? 'contact-inline' : 'contact-box'}>
      <div>
        <p className="contact-title">
          <LifeBuoy size={19} />
          {compact ? '需要帮助？' : '需要卡密或使用帮助？'}
        </p>
        {!compact && <p className="muted small">购买卡密或使用遇到问题，联系支持。</p>}
      </div>
      <div className="public-support-links">
        <a className="contact-link" href="mailto:xrcy123@gmail.com">
          xrcy123@gmail.com <ArrowUpRight size={16} />
        </a>
        <a
          className="contact-link"
          href="https://t.me/xrcy97"
          target="_blank"
          rel="noreferrer"
        >
          Telegram · @xrcy97 <ArrowUpRight size={16} />
        </a>
        {support?.contact_url &&
          !['mailto:xrcy123@gmail.com', 'https://t.me/xrcy97'].includes(
            support.contact_url,
          ) && (
            <a
              className="contact-link"
              href={support.contact_url}
              target="_blank"
              rel="noreferrer"
            >
              {support.contact_label || '其他联系方式'}{' '}
              <ArrowUpRight size={16} />
            </a>
          )}
      </div>
    </div>
  );
}
// Pass telemetry when the page already loads it (service status) to avoid
// fetching the same node list twice; otherwise the panel loads its own.
export function NodeStatus({
  telemetry,
  onRefresh,
}: {
  telemetry?: Telemetry | null;
  onRefresh?: () => Promise<void>;
} = {}) {
  const shared = telemetry !== undefined;
  const [own, setData] = useState<Telemetry | null>(() => lastRead('nodes')),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false);
  const data = shared ? telemetry : own;
  async function refresh() {
    setBusy(true);
    try {
      if (shared) await onRefresh?.();
      else setData(await api<Telemetry>('nodes'));
      setError('');
    } catch {
      setError('状态暂时无法读取，请稍后重试。');
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (shared) return;
    void refresh();
    const visible = () => {
      if (!document.hidden) void refresh();
    };
    const timer = setInterval(visible, 45000);
    document.addEventListener('visibilitychange', visible);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [shared]);
  const status: Record<string, string> = {
    online: '在线',
    offline: '离线',
    unknown: '待确认',
    paused: '已暂停',
    pending: '配置同步中',
  };
  return (
    <section className="section node-panel">
      <div className="section-heading">
        <h2>节点状态</h2>
        <Button
          variant="ghost"
          disabled={busy}
          onClick={() => void refresh()}
          aria-label="刷新节点状态"
        >
          <RefreshCw size={16} />
        </Button>
      </div>
      {error && <p className="message error">{error}</p>}
      {data ? (
        <div className="region-grid">
          {data.nodes.map((n) => (
            <article className="region-card" key={n.id}>
              <div className="region-label">
                <span>{n.name}</span>
              </div>
              <p className={'region-status status-' + n.status}>
                <i className="dot" />
                {status[n.status] || status.unknown}
              </p>
            </article>
          ))}
        </div>
      ) : (
        <p className="muted">加载中…</p>
      )}
      {!!data?.checked_at && (
        <p className="small muted">更新于 {when(data.checked_at)}</p>
      )}
    </section>
  );
}
export function Announcements({
  notices,
  compact = false,
  navigate,
}: {
  notices: Notice[];
  compact?: boolean;
  navigate?: (s: string) => void;
}) {
  const visible = publicNotices(notices);
  return (
    <section className="section announcements-panel">
      <div className="section-heading">
        {compact && <h2>最新公告</h2>}
        {compact && (
          <button className="text-link" onClick={() => navigate?.('notices')}>
            全部公告
            <ArrowRight size={14} />
          </button>
        )}
      </div>
      {visible.length ? (
        <div className="notice-list">
          {visible.slice(0, compact ? 2 : 100).map((n) => (
            <details className="notice-disclosure" key={`${n.id}:${n.revision}`} onToggle={(event) => {
              if (event.currentTarget.open) markNoticeRead(n);
            }}>
              <summary>
              <div className="notice-meta">
                <span className={'notice-tag ' + n.category}>
                  {categoryLabel[n.category] || '公告'}
                </span>
                {!!n.pinned && <span className="small muted">置顶</span>}
                <time dateTime={new Date(n.updated * 1000).toISOString()}>{new Date(n.updated * 1000).toLocaleDateString('zh-CN')}</time>
              </div>
              <h3>{n.title}</h3>
              <span className="notice-expand-label">阅读详情</span>
              </summary>
              <p className="notice-body">
                {n.body}
              </p>
            </details>
          ))}
        </div>
      ) : (
        <p className="empty muted">暂无新公告</p>
      )}
    </section>
  );
}
export function PlansPage({
  content,
  navigate,
  subscription,
  failed = false,
  username,
}: {
  content: Catalog | null;
  failed?: boolean;
  username?: string;
  navigate: (s: string) => void;
  subscription?: {
    quota: number;
    expires: number;
    plan_name: string | null;
  } | null;
}) {
  return (
    <div className="plan-journey">
      <header className="page-heading">
        <div>
          <h1>套餐与续费</h1>
        </div>
        <div className="plan-heading-actions"><Button variant="outline" onClick={() => navigate('orders')}>我的订单</Button><Button onClick={() => navigate('redeem')}>
          <Ticket size={16} />
          兑换卡密
        </Button></div>
      </header>
      {subscription && subscription.quota > 0 && (
        <div className="membership-strip">
          <div>
            <span className="muted">当前套餐</span>
            <strong>{subscription.plan_name || '卡密套餐'}</strong>
          </div>
          <div>
            <span className="muted">有效期至</span>
            <strong>
              {expiryLabel(subscription.expires)}
            </strong>
          </div>
          <button className="text-link" onClick={() => navigate('history')}>
            兑换记录 →
          </button>
        </div>
      )}
      <section className="catalog-section">
        <div className="section-heading">
          <h2>可选套餐</h2>
        </div>
        <div className="compact-plan-grid">
          {content?.plans.map((p) => (
            <article className="compact-plan" key={p.id}>
              <header>
                <h3>{p.name}</h3>
                {p.badge && <span className="quiet-badge">{p.badge}</span>}
              </header>
              <p className="compact-plan-quota">
                {p.quota_gib}
                <span>GiB · {ruleLabel(p)}</span>
              </p>
              <ul>
                <li>
                  <Check size={15} />
                  多地区节点
                </li>
                <li>
                  <Check size={15} />
                  Clash / 小火箭 / Android
                </li>
              </ul>
              <footer>
                {content.payments_enabled && (p.usdt_micros || 0) > 0 ? <>
                  <strong className="plan-online-price">{p.usdt_micros! / 1000000}<small>USDT</small></strong>
                  <PurchaseButton planId={p.id} label={p.name} price={p.usdt_micros!} username={username} navigate={navigate} />
                </> : <>
                <strong>{priceText(p.price_label)}</strong>
                {content.support.contact_url ? (
                  <a
                    className="text-link"
                    href={content.support.contact_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    联系管理员 ↗
                  </a>
                ) : (
                  <button
                    className="text-link"
                    onClick={() => navigate('help')}
                  >
                    如何获取卡密 →
                  </button>
                )}</>}
              </footer>
            </article>
          ))}
        </div>
        {content?.plans.length === 0 && (
          <p className="empty">暂无上架套餐，请联系管理员。</p>
        )}
        {!content && !failed && (
          <p role="status" className="muted">
            正在加载套餐…
          </p>
        )}
      </section>
      <div className="plan-footnotes">
        <details><summary>套餐规则</summary><p>{content?.package_billing ? '周期额度不结转；加流量卡随所属套餐到期。' : '续费叠加流量和有效期。'}</p></details>
        <button className="text-link" onClick={() => navigate('help')}>
          兑换遇到问题？
        </button>
      </div>
    </div>
  );
}
export function HelpPage({
  support,
  navigate,
  packageBilling = false,
}: {
  support: Support | undefined;
  navigate: (s: string) => void;
  packageBilling?: boolean;
}) {
  const faqs = [
    [
      '如何获得卡密？',
      '在套餐页用 USDT 购买（请按收款页显示的准确金额付款），或联系管理员。',
    ],
    [
      '订阅链接导入失败？',
      '确认复制的是完整订阅链接。也可以在链接末尾加 ?format=clash 或 ?format=shadowrocket。',
    ],
    [
      '兑换后没有节点？',
      '节点同步需要一点时间，首页显示「同步中」时请稍候，不要重复兑换。',
    ],
    [
      '有流量但连不上？',
      '先更新订阅，再换个地区。仍不行请提交工单。',
    ],
    [
      '续费会清空流量吗？',
      packageBilling ? '不会。新套餐接在现有套餐后计时，流量立即可用，先扣最早到期的额度。' : '不会。新额度叠加，有效期顺延。',
    ],
    [
      '忘记密码？',
      '在登录页点「忘记密码」，用注册邮箱验证码重设。',
    ],
    [
      '提交工单写什么？',
      '客户端名称、地区、出错时间和截图。不要发送密码、卡密或订阅链接。',
    ],
  ];
  return (
    <>
      <PageTitle
        eyebrow=""
        title="帮助"
        description=""
      />
      <Contact support={support} />
      <section className="section">
        <h2>常见问题</h2>
        <div className="faq-list">
          {faqs.map(([q, a]) => (
            <details key={q}>
              <summary>{q}</summary>
              <p>{a}</p>
            </details>
          ))}
        </div>
      </section>
      <div className="help-links">
        <button onClick={() => navigate('guide')}>
          <BookOpen size={20} />
          <span>客户端教程</span>
          <ArrowRight size={17} />
        </button>
        <button onClick={() => navigate('notices')}>
          <Megaphone size={20} />
          <span>服务公告</span>
          <ArrowRight size={17} />
        </button>
      </div>
      <section className="section">
        <h2>服务说明</h2>
        <div className="faq-list">
          <details><summary>流量统计</summary><p>按上传加下载合计扣除，约每 5 分钟更新一次。</p></details>
          <details><summary>账号与数据</summary><p>我们保存账号邮箱、密码哈希、套餐与兑换记录、流量统计、工单，以及登录设备的 IP 和浏览器信息，仅用于登录安全、计费和问题处理。邮件经 Resend 发送。</p></details>
          <details><summary>订阅安全</summary><p>订阅链接等同于连接凭据，请勿分享。泄露时请在「连接与订阅」中更换连接凭据。</p></details>
        </div>
      </section>
    </>
  );
}
