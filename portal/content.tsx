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
import { expiryLabel, ruleLabel, type CycleRule } from './cycles';
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
type Telemetry = { checked_at: number; nodes: Node[] };
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
export function NodeStatus() {
  const [data, setData] = useState<Telemetry | null>(() => lastRead('nodes')),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false);
  async function refresh() {
    setBusy(true);
    try {
      setData(await api<Telemetry>('nodes'));
      setError('');
    } catch {
      setError('状态暂时无法读取，请稍后重试。');
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
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
  }, []);
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
        <div>
          <h2>节点状态</h2>
          <p className="small muted">服务器上报状态</p>
        </div>
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
                <span className="protocol">HY2</span>
              </div>
              <p className={'region-status status-' + n.status}>
                <i className="dot" />
                {status[n.status] || status.unknown}
              </p>
            </article>
          ))}
        </div>
      ) : (
        <p className="muted">正在读取节点状态…</p>
      )}
      <details className="telemetry-note">
        <summary>监测详情</summary>
        <p>
          更新于 {when(data?.checked_at || 0)}
          。在线状态来自服务器心跳，实际连接请以客户端测试为准。
        </p>
        {data?.nodes.map((n) => (
          <p key={n.id}>
            {n.name} · 管理链路{' '}
            {n.latency_ms === null ? '—' : n.latency_ms + ' ms'} · 心跳{' '}
            {when(n.heartbeat)}
          </p>
        ))}
      </details>
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
        <details><summary>套餐规则</summary><p>{content?.package_billing ? '套餐按所选期限与重置周期生效。周期额度不结转；加流量卡随所属套餐当前周期到期。' : '续费叠加流量和有效期，不按月重置。'}</p></details>
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
      '支持在线支付的套餐会显示 USDT 购买按钮。已有账号付款后自动到账；访客付款后领取卡密，再验证邮箱开通。请在收款页选择正确网络，支付显示的准确金额，并保存订单号。也可通过官方联系方式向管理员获取卡密。',
    ],
    [
      '订阅链接为什么不能导入？',
      '先确认复制的是首页显示的完整订阅链接，不是网站首页地址。Clash 可在链接末尾添加 ?format=clash；小火箭可添加 ?format=shadowrocket 强制指定格式。也可以在首页下载对应配置。',
    ],
    [
      '兑换后没有马上出现节点？',
      '卡密先记账，再同步节点。首页显示「同步中」时请稍候，系统会自动重试，重复兑换同一张卡不会重复增加额度。长时间未完成请联系管理员。',
    ],
    [
      '有剩余流量，但连不上怎么办？',
      '同时检查到期时间、客户端是否启用了正确配置、节点是否暂停。先更新订阅，再切换地区尝试。面板心跳在线并不能保证你本地到节点的网络畅通。',
    ],
    [
      '续费会清空流量吗？',
      packageBilling ? '提前续费的套餐接在现有套餐到期后计时，流量兑换后立即可用，优先扣除最早到期或重置的额度。按开通日每月恢复固定额度，剩余不结转；加流量包随当前周期到期，不改变重置日。短月份取月末，后续月份仍按原开通日计算。' : '不会清零已用流量。新卡额度叠加到总额度，有效期从原到期时间与当前时间中较晚的一者继续延长。本服务为总流量包，不按月自动重置。',
    ],
    [
      '节点显示的延迟和我测的不一样？',
      '这里显示管理服务器到节点的管理链路探测值，可能经过管理隧道。它不是你设备到节点的延迟，请以客户端实际测试为准。',
    ],
    [
      '忘记密码怎么办？',
      '在登录页选择找回密码，通过注册邮箱验证码重设。原邮箱无法使用时，联系支持核实身份。重设密码会退出旧登录会话。',
    ],
    [
      '如何描述问题，方便排查？',
      '提供用户名、客户端名称和版本、所选地区、出错时间与截图。不要发送登录密码、完整卡密或订阅链接。',
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
          <span>查看客户端教程</span>
          <ArrowRight size={17} />
        </button>
        <button onClick={() => navigate('notices')}>
          <Megaphone size={20} />
          <span>查看维护与服务公告</span>
          <ArrowRight size={17} />
        </button>
      </div>
      <section className="section">
        <h2>服务说明</h2>
        <div className="faq-list">
          <details><summary>流量与有效期</summary><p>额度按节点记录的上传与下载合计扣除，页面使用 GiB / MiB（1 GiB = 1024 MiB）。用量记录约每 5 分钟更新，不是实时读数；缺失记录不补算。{packageBilling ? '提前续费时，新套餐接在现有套餐到期后计时，流量兑换后立即可用；先扣最早到期的额度，同到期时间按发放顺序扣除。加流量包不增加有效期。' : '套餐额度与有效期以兑换确认页为准。'}历史用量包含过去已到期套餐的使用，不等于当前套餐已用流量。</p></details>
          <details><summary>支持范围</summary><p>我们协助处理卡密兑换、账号、订阅导入及本站节点连接问题。不保证特定网站或第三方平台始终可用；节点状态也不代表你的本地网络一定畅通。遇到问题可提交工单。</p></details>
          <details><summary>账号与数据</summary><p>服务保存账号邮箱、密码哈希、套餐与兑换记录、流量统计、工单内容，以及网站登录会话的 IP、浏览器信息和活动时间，用于登录安全、计费与问题处理。验证与提醒邮件由 Resend 发送，需要向其提供收件邮箱。网站与邮件服务商可能另行处理技术日志。请勿在工单中提交密码、验证码或完整订阅链接。</p></details>
          <details><summary>邮件与订阅安全</summary><p>工单邮件提醒默认关闭，可在工单页开启或关闭。订阅链接相当于连接凭据，请勿公开分享；仅重置链接不会使已导入的节点密码失效，确认泄露时应更换连接凭据。</p></details>
        </div>
      </section>
    </>
  );
}
