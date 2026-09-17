import { useEffect, useState, type ReactNode } from 'react';
import { priceText } from './experience';
import { publicNotices, markNoticeRead } from './notice-entry';
import {
  ArrowUpRight,
  ArrowRight,
  BookOpen,
  Check,
  Clock3,
  Globe2,
  LifeBuoy,
  Megaphone,
  Monitor,
  Package,
  RefreshCw,
  ShieldCheck,
  Smartphone,
  Ticket,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from '@/components/ui/select';
import { api } from './api';

export type Plan = {
  id: string;
  name: string;
  description: string;
  quota_gib: number;
  days: number;
  price_label: string;
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
export type Catalog = { plans: Plan[]; notices: Notice[]; support: Support; package_billing?: boolean };
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
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}
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
  const [data, setData] = useState<Telemetry | null>(null),
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
    const timer = setInterval(() => void refresh(), 45000);
    return () => clearInterval(timer);
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
}: {
  content: Catalog | null;
  failed?: boolean;
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
        <Button onClick={() => navigate('redeem')}>
          <Ticket size={16} />
          兑换卡密
        </Button>
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
              {new Date(subscription.expires * 1000).toLocaleDateString(
                'zh-CN',
              )}
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
                <span>GiB / {p.days} 天</span>
              </p>
              <ul>
                <li>
                  <Check size={15} />
                  日本 · 新加坡 · 马来西亚
                </li>
                <li>
                  <Check size={15} />
                  Clash / 小火箭 / Android
                </li>
              </ul>
              <footer>
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
                )}
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
        <details><summary>套餐规则</summary><p>{content?.package_billing ? '兑换后独立计时，到期剩余流量作废。加流量卡不延长有效期。' : '续费叠加流量和有效期，不按月重置。'}</p></details>
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
      '本站暂不提供在线付款。通过原发卡渠道联系管理员，确认套餐后获取卡密。已配置的官方联系方式会显示在本页。',
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
      packageBilling ? '每份套餐从兑换时独立计时，优先扣除最早到期套餐的流量，未用完的流量到期作废。加流量卡必须选择一个有效套餐，跟随该套餐到期，不增加天数。' : '不会清零已用流量。新卡额度叠加到总额度，有效期从原到期时间与当前时间中较晚的一者继续延长。本服务为总流量包，不按月自动重置。',
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
        eyebrow="HELP & SUPPORT"
        title="遇到问题，先从这里开始"
        description="导入、续费和连接问题的常见解答。"
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
          <details><summary>流量与有效期</summary><p>额度按节点记录的上传与下载合计扣除，页面使用 GiB / MiB（1 GiB = 1024 MiB）。用量记录约每 5 分钟更新，不是实时读数；缺失记录不补算。{packageBilling ? '每份套餐独立到期，先扣最早到期的额度；同到期时间按发放顺序扣除。加流量包不增加有效期。' : '套餐额度与有效期以兑换确认页为准。'}历史用量包含过去已到期套餐的使用，不等于当前套餐已用流量。</p></details>
          <details><summary>支持范围</summary><p>我们协助处理卡密兑换、账号、订阅导入及本站节点连接问题。不保证特定网站或第三方平台始终可用；节点状态也不代表你的本地网络一定畅通。遇到问题可提交工单。</p></details>
          <details><summary>账号与数据</summary><p>服务保存账号邮箱、密码哈希、套餐与兑换记录、流量统计、工单内容，以及网站登录会话的 IP、浏览器信息和活动时间，用于登录安全、计费与问题处理。验证与提醒邮件由 Resend 发送，需要向其提供收件邮箱。网站与邮件服务商可能另行处理技术日志。请勿在工单中提交密码、验证码或完整订阅链接。</p></details>
          <details><summary>邮件与订阅安全</summary><p>工单邮件提醒默认关闭，可在工单页开启或关闭。订阅链接相当于连接凭据，请勿公开分享；仅重置链接不会使已导入的节点密码失效，确认泄露时应更换连接凭据。</p></details>
        </div>
      </section>
    </>
  );
}

const blankPlan = {
  id: '',
  name: '',
  description: '',
  quota_gib: 100,
  days: 30,
  price_label: '',
  badge: '',
  published: 0,
  sort_order: 0,
  revision: 1,
};
const blankNotice = {
  id: '',
  title: '',
  body: '',
  category: 'info',
  published: 0,
  pinned: 0,
  created: 0,
  updated: 0,
  revision: 1,
};
export function ContentAdmin({ onSaved }: { onSaved: () => Promise<void> }) {
  const [data, setData] = useState<Catalog | null>(null),
    [plan, setPlan] = useState<Plan>(blankPlan),
    [notice, setNotice] = useState<Notice>(blankNotice),
    [support, setSupport] = useState<Support | null>(null),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState(''),
    [error, setError] = useState('');
  async function load() {
    const d = await api<Catalog>('admin/content');
    setData(d);
    setSupport(d.support);
    return d;
  }
  useEffect(() => {
    void load().catch((e) => setError(e.message));
  }, []);
  async function save(kind: string, value: unknown) {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      await api('admin/' + kind, value);
      const d = await load();
      if (kind === 'plan') setPlan(blankPlan);
      if (kind === 'notice') setNotice(blankNotice);
      await onSaved();
      setMessage(
        kind === 'notice'
          ? (value as Notice).published
            ? '公告已发布，用户进入网站即可看到；已打开的页面会在一分钟内更新。'
            : '公告已保存为草稿，不会在用户端展示。'
          : '已保存，前台内容已更新。',
      );
      return d;
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存失败');
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="section cms">
      <h2>内容管理</h2>
      <p className="small muted">
        套餐、公告与客服入口都可以在这里更新，无需重新部署。
      </p>
      {error && (
        <p className="message error" role="alert">
          {error}
        </p>
      )}
      {message && (
        <p className="message" role="status">
          {message}
        </p>
      )}
      <Tabs defaultValue="notices">
        <TabsList>
          <TabsTrigger value="plans">套餐管理</TabsTrigger>
          <TabsTrigger value="notices">公告管理</TabsTrigger>
          <TabsTrigger value="support">联系设置</TabsTrigger>
        </TabsList>
        <TabsContent value="plans">
          <div className="cms-list">
            {data?.plans.map((p) => (
              <div key={p.id}>
                <span>
                  <strong>{p.name}</strong>
                  <small>
                    {p.quota_gib} GiB · {p.days} 天 ·{' '}
                    {p.published ? '已上架' : '草稿 / 已下架'}
                  </small>
                </span>
                <Button
                  variant="outline"
                  onClick={() => {
                    setPlan({ ...p });
                    setMessage('');
                  }}
                >
                  编辑
                </Button>
              </div>
            ))}
          </div>
          <form
            className="surface"
            onSubmit={(e) => {
              e.preventDefault();
              void save('plan', { ...plan, published: !!plan.published });
            }}
          >
            <div className="section-heading">
              <h2>{plan.id ? '编辑套餐' : '新建套餐'}</h2>
              {plan.id && (
                <Button variant="ghost" onClick={() => setPlan(blankPlan)}>
                  取消编辑
                </Button>
              )}
            </div>
            <div className="form-grid">
              <Field label="套餐名称">
                <Input
                  required
                  maxLength={60}
                  value={plan.name}
                  onChange={(e) => setPlan({ ...plan, name: e.target.value })}
                />
              </Field>
              <Field label="价格说明（选填）">
                <Input
                  maxLength={40}
                  placeholder="例如 ¥20 / 张，不填写则显示联系管理员"
                  value={plan.price_label}
                  onChange={(e) =>
                    setPlan({ ...plan, price_label: e.target.value })
                  }
                />
              </Field>
              <Field label="流量（GiB）">
                <Input
                  type="number"
                  required
                  min={1}
                  max={8192}
                  value={plan.quota_gib}
                  onChange={(e) =>
                    setPlan({ ...plan, quota_gib: Number(e.target.value) })
                  }
                />
              </Field>
              <Field label="有效期（天）">
                <Input
                  type="number"
                  required
                  min={1}
                  max={730}
                  value={plan.days}
                  onChange={(e) =>
                    setPlan({ ...plan, days: Number(e.target.value) })
                  }
                />
              </Field>
              <Field label="标签（选填）">
                <Input
                  maxLength={20}
                  value={plan.badge}
                  onChange={(e) => setPlan({ ...plan, badge: e.target.value })}
                />
              </Field>
              <Field label="排序（小的在前）">
                <Input
                  type="number"
                  required
                  min={0}
                  max={999}
                  value={plan.sort_order}
                  onChange={(e) =>
                    setPlan({ ...plan, sort_order: Number(e.target.value) })
                  }
                />
              </Field>
            </div>
            <Field label="套餐说明">
              <Textarea
                maxLength={500}
                value={plan.description}
                onChange={(e) =>
                  setPlan({ ...plan, description: e.target.value })
                }
              />
            </Field>
            <label className="check-line">
              <Checkbox
                checked={!!plan.published}
                onCheckedChange={(v) =>
                  setPlan({ ...plan, published: v ? 1 : 0 })
                }
              />
              上架，在前台展示
            </label>
            <p className="small muted">
              取消上架后保存即可下架。修改套餐不影响已发出的卡密。
            </p>
            <Button type="submit" disabled={busy}>
              保存套餐
            </Button>
          </form>
        </TabsContent>
        <TabsContent value="notices">
          <div className="cms-list">
            {data?.notices.map((n) => (
              <div key={n.id}>
                <span>
                  <strong>{n.title}</strong>
                  <small>
                    {categoryLabel[n.category]} ·{' '}
                    {n.published ? '已发布' : '草稿'}
                    {n.pinned ? ' · 置顶' : ''}
                  </small>
                </span>
                <Button
                  variant="outline"
                  onClick={() => {
                    setNotice({ ...n });
                    setMessage('');
                  }}
                >
                  编辑
                </Button>
              </div>
            ))}
          </div>
          <form
            className="surface"
            onSubmit={(e) => {
              e.preventDefault();
              void save('notice', {
                ...notice,
                published: !!notice.published,
                pinned: !!notice.pinned,
              });
            }}
          >
            <div className="section-heading">
              <h2>{notice.id ? '编辑公告' : '新建公告'}</h2>
              {notice.id && (
                <Button variant="ghost" onClick={() => setNotice(blankNotice)}>
                  取消编辑
                </Button>
              )}
            </div>
            <Field label="标题">
              <Input
                required
                maxLength={120}
                value={notice.title}
                onChange={(e) =>
                  setNotice({ ...notice, title: e.target.value })
                }
              />
            </Field>
            <div className="field">
              <span id="notice-kind">公告类型</span>
              <Select
                value={notice.category}
                onValueChange={(v) =>
                  setNotice({ ...notice, category: String(v) })
                }
              >
                <SelectTrigger aria-labelledby="notice-kind">
                  <SelectValue>{categoryLabel[notice.category]}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(categoryLabel).map(([key, label]) => (
                    <SelectItem key={key} value={key}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Field label="正文（纯文本）">
              <Textarea
                required
                rows={6}
                maxLength={4000}
                value={notice.body}
                onChange={(e) => setNotice({ ...notice, body: e.target.value })}
              />
            </Field>
            <div className="actions">
              <label className="check-line">
                <Checkbox
                  checked={!!notice.published}
                  onCheckedChange={(v) =>
                    setNotice({ ...notice, published: v ? 1 : 0 })
                  }
                />
                发布到前台
              </label>
              <label className="check-line">
                <Checkbox
                  checked={!!notice.pinned}
                  onCheckedChange={(v) =>
                    setNotice({ ...notice, pinned: v ? 1 : 0 })
                  }
                />
                置顶并在首次进入时提醒
              </label>
            </div>
            <Button type="submit" disabled={busy}>
              保存公告
            </Button>
          </form>
        </TabsContent>
        <TabsContent value="support">
          {support && (
            <form
              className="surface"
              onSubmit={(e) => {
                e.preventDefault();
                void save('support', support);
              }}
            >
              <Field label="联系按钮文字">
                <Input
                  required
                  maxLength={40}
                  value={support.contact_label}
                  onChange={(e) =>
                    setSupport({ ...support, contact_label: e.target.value })
                  }
                />
              </Field>
              <Field label="客服链接（选填）">
                <Input
                  maxLength={400}
                  placeholder="https://t.me/你的用户名 或 mailto:邮箱"
                  value={support.contact_url}
                  onChange={(e) =>
                    setSupport({ ...support, contact_url: e.target.value })
                  }
                />
              </Field>
              <Field label="联系说明">
                <Textarea
                  maxLength={1000}
                  value={support.contact_note}
                  onChange={(e) =>
                    setSupport({ ...support, contact_note: e.target.value })
                  }
                />
              </Field>
              <p className="small muted">
                仅支持 HTTPS 或
                mailto:邮箱。留空时显示联系说明，不生成无效按钮。
              </p>
              <Button type="submit" disabled={busy}>
                保存联系方式
              </Button>
            </form>
          )}
        </TabsContent>
      </Tabs>
    </section>
  );
}
export function PlanIssuer({
  plans,
  onIssued,
  disabled,
}: {
  plans: Plan[];
  onIssued: (codes: string[]) => Promise<void>;
  disabled: boolean;
}) {
  const [selected, setSelected] = useState<string>(''),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const p = plans.find((p) => p.id === selected);
  return (
    <section className="plan-issuer">
      <h2>按套餐发卡</h2>
      <p className="small muted">
        额度和天数使用后台已保存的套餐，不会修改现有卡密。
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          setBusy(true);
          setError('');
          void api<{ codes: { code: string }[] }>('admin/cards', {
            plan_id: selected,
            count: Number(f.get('count')),
            valid_days: Number(f.get('valid_days')),
          })
            .then((r) => onIssued(r.codes.map((c) => c.code)))
            .catch((e) => setError(e.message))
            .finally(() => setBusy(false));
        }}
      >
        <div className="form-grid">
          <div className="field">
            <span id="issue-plan">选择已上架套餐</span>
            <Select
              value={selected}
              onValueChange={(v) => setSelected(String(v))}
            >
              <SelectTrigger aria-labelledby="issue-plan">
                <SelectValue>{p ? p.name : '请选择套餐'}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {plans.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.name} · {p.quota_gib} GiB / {p.days} 天
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Field label="生成数量">
            <Input
              name="count"
              required
              type="number"
              min={1}
              max={100}
              defaultValue={1}
            />
          </Field>
          <Field label="卡密兑换期限（天）">
            <Input
              name="valid_days"
              required
              type="number"
              min={1}
              max={730}
              defaultValue={90}
            />
          </Field>
        </div>
        {error && <p className="message error">{error}</p>}
        <Button type="submit" disabled={disabled || busy || !p}>
          按套餐生成卡密
          <Ticket />
        </Button>
      </form>
    </section>
  );
}
