import React, {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from 'react';
import { createRoot } from 'react-dom/client';
import { DockViewport } from './dock-viewport';
import { AuthFlow } from './auth';
import { captureCardLink, pendingCard, cardLink } from './card-entry';
import { CycleFields, ruleLabel, FOREVER } from './cycles';
const UserManager = React.lazy(() =>
  import('./admin-users').then((module) => ({ default: module.UserManager })),
);
import { NoticeEntry } from './notice-entry';
import { CardSearch, LoginDiagnosis, MailHistory } from './admin-support';
import {
  ArrowUpRight,
  ArrowRight,
  Check,
  Copy,
  Download,
  Globe2,
  Home,
  KeyRound,
  LogOut,
  Moon,
  RefreshCw,
  Shield,
  Sun,
  Ticket,
  UserRound,
  ArrowLeft,
  ChevronRight,
  BookOpen,
  Package,
  History,
  LifeBuoy,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select';
import type { PackageBalance } from './features';
import { Progress } from '@/components/ui/progress';
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from '@/components/ui/table';
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
} from '@/components/ui/alert-dialog';
import '@/app/globals.css';
import './style.css';
import './content.css';
import './glass.css';
import './features.css';
import './layout.css';
import {
  Dashboard,
  AccountHub,
  DeviceGuide,
  AdminNavigation,
} from './journeys';
import {
  Connection,
  GettingStarted,
  UsagePanel,
  Redemption,
  Tickets,
  type TicketDraft,
  Sessions,
  Recover,
  ServiceStatus,
  ServiceBrief,
  Operations,
} from './features';
import {
  useNavigation,
  tabFor,
  isAuthenticationView,
  authModeFor,
  afterLogin,
  showDock,
} from './navigation';
import { api, ApiError } from './api';
import {
  NodeStatus,
  Announcements,
  PlansPage,
  HelpPage,
  Contact,
  PageTitle,
  ContentAdmin,
  PlanIssuer,
  type Catalog,
} from './content';

type Me = {
  user: { username: string; admin: boolean; must_change: boolean };
  subscription: {
    quota: number;
    used: number | null;
    expires: number;
    pending: boolean;
    rotating?: boolean;
    sync_error: string | null;
    usage_error: string | null;
    enabled: boolean | null;
    url: string | null;
    plan_name: string | null;
    billing?: {packages: PackageBalance[]; remaining: number; next_expiry: number} | null;
  };
  history: {
    label: string;
    quota: number;
    days: number;
    kind?: string;
    redeemed_at: number;
  }[];
  nodes: string[];
};
type Card = {
  id: string;
  suffix: string;
  label: string;
  quota: number;
  days: number;
  redeem_before: number;
  redeemed_at: number | null;
  revoked_at: number | null;
  redeemed_by: string | null;
};
type Admin = {
  cards: Card[];
  audit: { actor: string; action: string; target: string; created: number }[];
};
const gib = (bytes: number) =>
  new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(
    bytes / 1024 ** 3,
  );
const date = (seconds: number) =>
  seconds >= FOREVER ? '永久有效' : seconds
    ? new Date(seconds * 1000).toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      })
    : '尚未开通';
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}
function App() {
  const [customKind, setCustomKind] = useState('base');
  const [customCycle, setCustomCycle] = useState<import('./cycles').CycleRule>({ permanent: 0, reset_period: 'never', reset_interval: 30 });
  const [justActivated, setJustActivated] = useState(false);
  const [memberScope, setMemberScope] = useState('all');
  const { view, navigate: setView, back } = useNavigation();
  const [content, setContent] = useState<Catalog | null>(null);
  const [contentError, setContentError] = useState('');
  const contentRequest = useRef(0);
  async function loadContent() {
    const version = ++contentRequest.current;
    try {
      const result = await api<Catalog>('content');
      if (version === contentRequest.current) {
        setContent(result);
        setContentError('');
      }
    } catch {
      if (version === contentRequest.current)
        setContentError('套餐和公告暂时无法加载，请重试。');
    }
  }
  const [me, setMe] = useState<Me | null>(null),
    [loaded, setLoaded] = useState(false),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState(''),
    [error, setError] = useState(''),
    [admin, setAdmin] = useState<Admin | null>(null),
    [codes, setCodes] = useState<string[]>([]),
    [confirm, setConfirm] = useState<{
      title: string;
      text: string;
      run: () => Promise<void>;
    } | null>(null);
  const [dark, setDark] = useState(() => {
    try {
      return localStorage.getItem('jamie-theme') === 'dark';
    } catch {
      return false;
    }
  });
  const ticketDraft = useMemo<TicketDraft>(
    () => ({ subject: '', body: '', category: 'connection', replies: {} }),
    [me?.user.username],
  );
  useEffect(() => {
    if (me && !me.user.must_change && ['login', 'register'].includes(view))
      setView(pendingCard() ? 'redeem' : 'home', true);
  }, [me, view, setView]);
  async function load() {
    try {
      const m = await api<Me>('me');
      setMe(m);
      if (m.user.must_change) setView('security', true);
      return m;
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setMe(null);
        return null;
      }
      throw e;
    } finally {
      setLoaded(true);
    }
  }
  async function loadAdmin() {
    setAdmin(await api<Admin>('admin/cards-overview'));
  }
  async function act(fn: () => Promise<void>) {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : '请求失败，请重试');
      if (e instanceof ApiError && e.status === 401) setMe(null);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    void load().catch((e) => setError(e.message));
    void loadContent();
    const refresh = () => {
      if (document.visibilityState === 'visible') void loadContent();
    };
    const timer = setInterval(refresh, 60000);
    document.addEventListener('visibilitychange', refresh);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', refresh);
    };
  }, []);
  useEffect(() => {
    if (!me) return;
    const refresh = () => {
      if (document.visibilityState === 'visible')
        void load().catch((e) => setError(e.message));
    };
    document.addEventListener('visibilitychange', refresh);
    return () => document.removeEventListener('visibilitychange', refresh);
  }, [me?.user.username]);
  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
    try {
      localStorage.setItem('jamie-theme', dark ? 'dark' : 'light');
    } catch {}
  }, [dark]);
  useEffect(() => {
    if (me?.subscription.pending) {
      const id = setInterval(() => void load().catch(() => {}), 5000);
      return () => clearInterval(id);
    }
  }, [me?.subscription.pending]);
  useEffect(() => {
    if (view === 'admin' && me?.user.admin && !me.user.must_change)
      void act(loadAdmin);
  }, [view, me?.user.admin, me?.user.must_change]);
  useEffect(() => {
    setError('');
    setNotice('');
    if (me?.user.must_change && view !== 'security') setView('security', true);
  }, [view, me?.user.must_change]);
  useEffect(() => {
    const context = (
      document as Document & {
        modelContext?: {
          registerTool: (tool: unknown, opts: unknown) => unknown;
        };
      }
    ).modelContext;
    if (!context) return;
    const controller = new AbortController();
    try {
      Promise.resolve(
        context.registerTool(
          {
            name: 'view_subscription_summary',
            title: '查看订阅用量',
            description: '读取当前登录用户的额度和有效期，不返回私密订阅链接。',
            inputSchema: {
              type: 'object',
              properties: {},
              additionalProperties: false,
            },
            annotations: { readOnlyHint: true },
            execute: async () => {
              const m = await load();
              if (!m) throw new Error('请先登录');
              setView('home');
              return {
                quota: m.subscription.quota,
                used: m.subscription.used,
                expires: m.subscription.expires,
                pending: m.subscription.pending,
              };
            },
          },
          { signal: controller.signal },
        ),
      ).catch(() => {});
    } catch {}
    return () => controller.abort();
  }, []);
  function navigate(next: string) {
    setView(next);
    setError('');
    setNotice('');
  }
  async function copy(value: string) {
    await navigator.clipboard.writeText(value);
    setNotice('已复制');
  }
  function exportCodes() {
    const url = URL.createObjectURL(
      new Blob([codes.join('\n')], { type: 'text/plain;charset=utf-8' }),
    );
    const a = document.createElement('a');
    a.href = url;
    a.download = 'Jamie-Node-cards.txt';
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const s = me?.subscription;
  const status = !s?.quota
    ? '尚未开通'
    : s.pending
      ? '同步中'
      : s.expires * 1000 < Date.now()
        ? '已到期'
        : s.used !== null && s.used >= s.quota
          ? '流量已用完'
          : s.enabled === false
            ? '已暂停'
            : '已开通';
  return (
    <>
      <header className="brand">
        <a
          href="#/home"
          className="brand-lockup"
          aria-label="Jamie-Node 首页"
          onClick={(e) => {
            e.preventDefault();
            navigate('home');
          }}
        >
          <span className="brand-icon" aria-hidden="true" />
          <span className="brand-wordmark">Jamie<span>-Node</span></span>
        </a>
        <div className="header-right">
          {me && <span className="username">{me.user.username}</span>}
          <button
            className="icon-button"
            onClick={() => setDark(!dark)}
            aria-label={dark ? '切换浅色' : '切换深色'}
          >
            {dark ? <Sun size={18} /> : <Moon size={18} />}
          </button>
        </div>
      </header>
      <main
        tabIndex={-1}
        className={
          'wide view-' +
          view +
          (isAuthenticationView(view, !!me) ? ' auth-layout' : '')
        }
      >
        {loaded && tabFor(view) !== view && !me?.user.must_change && (
          <button className="back-link" onClick={back}>
            <ArrowLeft size={17} />
            返回
          </button>
        )}
        {![
          'notices',
          'admin',
          'admin_users',
          'admin_content',
          'admin_tickets',
          'operations',
        ].includes(view) && (
          <NoticeEntry
            showStrip={view === 'home'}
            notices={content?.notices || []}
            ready={!!content}
            navigate={navigate}
          />
        )}
        {contentError && (
          <div className="message error">
            {contentError}
            <button className="text-link" onClick={() => void loadContent()}>
              重新加载
            </button>
          </div>
        )}
        {error && (
          <div className="message error" role="alert">
            {error}
          </div>
        )}
        {notice && (
          <div className="message success" role="status">
            <Check size={17} />
            {notice}
          </div>
        )}
        {!loaded ? (
          <section className="intro">
            <p className="eyebrow">JAMIE-NODE</p>
            <h1>正在读取你的订阅</h1>
          </section>
        ) : !me &&
          !['plans', 'guide', 'help', 'notices', 'recover'].includes(view) ? (
          <AuthFlow
            mode={view === 'redeem' && pendingCard() ? 'login' : authModeFor(view)}
            navigate={navigate}
            onSuccess={async (created) => {
              await act(async () => {
                const current = await load();
                if (!current) throw new Error('登录状态暂未确认，请重试进入。');
                setJustActivated(created);
                setView(
                  current.user.must_change
                    ? 'security'
                    : created
                      ? 'guide'
                      : pendingCard() ? 'redeem' : afterLogin(view),
                  true,
                );
              });
            }}
          />
        ) : (
          <>
            {me?.user.admin &&
              [
                'admin',
                'admin_users',
                'admin_content',
                'operations',
                'admin_tickets',
              ].includes(view) && (
                <AdminNavigation view={view} navigate={navigate} />
              )}
            {view === 'recover' && <Recover navigate={navigate} />}
            {view === 'usage' && me && (
              <>
                <PageTitle
                  eyebrow=""
                  title="用量明细"
                  description=""
                />
                <UsagePanel navigate={navigate} />
              </>
            )}
            {view === 'tickets' && me && <Tickets draft={ticketDraft} />}
            {view === 'sessions' && me && <Sessions />}
            {view === 'status' && me && <ServiceStatus />}
            {view === 'operations' && me?.user.admin && (
              <Operations
                navigate={navigate}
                onMembers={(scope) => {
                  setMemberScope(scope);
                  navigate('admin_users');
                }}
              />
            )}
            {view === 'admin_tickets' && me?.user.admin && <Tickets staff />}
            {view === 'admin_users' && me?.user.admin && (
              <React.Suspense fallback={<p role="status">正在加载用户管理…</p>}>
                <UserManager initialScope={memberScope} />
              </React.Suspense>
            )}
            {view === 'admin_content' && me?.user.admin && (
              <>
                <PageTitle
                  eyebrow=""
                  title="公告与套餐"
                  description="发布后显示在用户端，置顶公告优先展示。"
                />
                <ContentAdmin onSaved={loadContent} />
              </>
            )}
            {[
              'operations',
              'admin_tickets',
              'admin_users',
              'admin_content',
            ].includes(view) &&
              me &&
              !me.user.admin && (
                <p className="message error">此页面仅管理员可访问。</p>
              )}
            {view === 'plans' && (
              <PlansPage
                content={content}
                failed={!!contentError}
                navigate={navigate}
                subscription={s}
              />
            )}
            {view === 'guide' && (
              <>
                {justActivated && me && (
                  <div className="activation-welcome" role="status">
                    <strong>
                      {s?.pending
                        ? '账号已开通，正在准备订阅'
                        : '账号已开通，开始连接你的设备'}
                    </strong>
                    <p className="small muted">
                      先安装客户端，订阅就绪后即可导入。建议稍后保存恢复码，方便找回账号。
                    </p>
                    <button
                      className="text-link"
                      onClick={() => navigate('sessions')}
                    >
                      设置恢复码 →
                    </button>
                  </div>
                )}
                <DeviceGuide
                  navigate={navigate}
                  url={s?.url}
                  pending={!!s?.pending}
                />
              </>
            )}
            {view === 'help' && (
              <HelpPage support={content?.support} navigate={navigate} packageBilling={content?.package_billing} />
            )}
            {view === 'notices' && (
              <>
                <PageTitle
                  eyebrow=""
                  title="公告"
                  description="维护通知与服务动态。"
                />
                <Announcements notices={content?.notices || []} />
              </>
            )}
            {view === 'home' && s && me && (
              <Dashboard
                s={s}
                username={me.user.username}
                content={content}
                navigate={navigate}
                busy={busy}
                refresh={() =>
                  void act(async () => {
                    await load();
                  })
                }
              />
            )}
            {view === 'subscription' && s && (
              <>
                <PageTitle
                  eyebrow=""
                  title="连接与订阅"
                  description="常用连接方式与订阅安全设置。"
                />
                <div className="subscription-layout">
                  <Connection
                    s={s}
                    navigate={navigate}
                    onChanged={async () => {
                      await load();
                    }}
                  />
                  <aside className="subscription-help">
                    <h2>在其他设备上使用</h2>
                    <p className="muted">
                      扫描二维码或复制链接，在对应客户端添加订阅。
                    </p>
                    <button
                      className="text-link"
                      onClick={() => navigate('guide')}
                    >
                      按设备查看教程 →
                    </button>
                    <hr />
                    <h2>链接泄露怎么办？</h2>
                    <p className="muted">
                      在订阅安全中重置链接，再为你的设备重新导入。已导入节点的访问凭证泄露，请联系管理员处理。
                    </p>
                    <button
                      className="text-link"
                      onClick={() => navigate('tickets')}
                    >
                      联系支持 →
                    </button>
                  </aside>
                </div>
              </>
            )}
            {view === 'redeem' && me && (
              <Redemption
                subscription={me.subscription}
                onChanged={async () => {
                  await load();
                }}
                navigate={navigate}
              />
            )}
            {(view === 'redeem' || view === 'history') && me && (
              <>
                {view === 'history' && (
                  <PageTitle
                    eyebrow=""
                    title="兑换记录"
                    description="已兑换到当前账号的卡密。"
                  />
                )}
                <section className="section">
                  {view === 'redeem' && <h2>兑换记录</h2>}
                  {me.history.length ? (
                    <div className="history">
                      {me.history.map((h, i) => (
                        <div className="history-row" key={i}>
                          <div>
                            <strong>{h.label}</strong>
                            <p className="small muted">{date(h.redeemed_at)}</p>
                          </div>
                          <span>
                            +{gib(h.quota)} GiB · {h.kind === 'addon' ? '不增加天数' : ruleLabel(h)}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="empty muted">尚无兑换记录。</p>
                  )}
                </section>
              </>
            )}
            {view === 'account' && me && s && (
              <AccountHub
                username={me.user.username}
                admin={me.user.admin}
                s={s}
                navigate={navigate}
                busy={busy}
                logout={() =>
                  void act(async () => {
                    await api('logout', {});
                    setMe(null);
                    setAdmin(null);
                    setCodes([]);
                    setView('account', true);
                  })
                }
              />
            )}
            {view === 'security' && me && (
              <>
                <section className="intro">
                  <p className="eyebrow">ACCOUNT</p>
                  <h1>账号与安全</h1>
                  <p className="muted">
                    {me.user.username}
                    {me.user.admin ? ' · 管理员' : ''}
                  </p>
                </section>
                {me.user.must_change && (
                  <p className="message">
                    请先修改初始密码，之后即可使用全部功能。
                  </p>
                )}
                <section className="surface">
                  <h2>修改密码</h2>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      const form = e.currentTarget;
                      const f = new FormData(form);
                      if (f.get('new_password') !== f.get('confirm')) {
                        setError('两次新密码不一致');
                        return;
                      }
                      void act(async () => {
                        await api('password', {
                          old_password: f.get('old_password'),
                          new_password: f.get('new_password'),
                        });
                        form.reset();
                        await load();
                        setNotice('密码已更新，其他设备的登录已失效。');
                      });
                    }}
                  >
                    <Field label="当前密码">
                      <Input
                        name="old_password"
                        type="password"
                        autoComplete="current-password"
                        required
                        maxLength={128}
                      />
                    </Field>
                    <Field label="新密码">
                      <Input
                        name="new_password"
                        type="password"
                        autoComplete="new-password"
                        required
                        minLength={10}
                        maxLength={128}
                      />
                    </Field>
                    <Field label="再次输入新密码">
                      <Input
                        name="confirm"
                        type="password"
                        autoComplete="new-password"
                        required
                        minLength={10}
                        maxLength={128}
                      />
                    </Field>
                    <Button type="submit" disabled={busy}>
                      保存新密码
                    </Button>
                  </form>
                </section>
                <Button
                  className="logout"
                  variant="outline"
                  disabled={busy}
                  onClick={() =>
                    void act(async () => {
                      await api('logout', {});
                      setMe(null);
                      setAdmin(null);
                      setCodes([]);
                      setView('home');
                    })
                  }
                >
                  <LogOut />
                  退出登录
                </Button>
              </>
            )}
            {view === 'admin' && me?.user.admin && (
              <>
                <section className="intro">
                  <p className="eyebrow">ADMINISTRATION</p>
                  <div className="title-row">
                    <h1>卡密管理</h1>
                    <Button
                      variant="outline"
                      onClick={() => void act(loadAdmin)}
                      disabled={busy}
                    >
                      <RefreshCw />
                      刷新
                    </Button>
                  </div>
                  <p className="muted">
                    生成卡密后私下发给用户，不接入在线支付。
                  </p>
                </section>
                <nav className="admin-local-nav" aria-label="管理页面分区">
                  {[
                    ['admin-issue', '发卡'],
                    ['admin-cards', '卡密记录'],
                    ['admin-audit', '操作记录'],
                  ].map(([id, label]) => (
                    <button
                      key={id}
                      onClick={() => {
                        const el = document.getElementById(id);
                        if (el?.tagName === 'DETAILS')
                          el.setAttribute('open', '');
                        el?.scrollIntoView({
                          block: 'start',
                          behavior: 'smooth',
                        });
                      }}
                    >
                      {label}
                    </button>
                  ))}
                </nav>
                <div id="admin-issue">
                  <PlanIssuer
                    plans={content?.plans || []}
                    disabled={busy}
                    onIssued={async (values) => {
                      setCodes(values);
                      await loadAdmin();
                      setNotice('套餐卡密已生成，请在下方复制或下载。');
                    }}
                  />
                </div>
                <section className="surface">
                  <details className="custom-issue">
                    <summary>自定义额度发卡</summary>
                    <form
                      onSubmit={(e) => {
                        e.preventDefault();
                        const f = new FormData(e.currentTarget);
                        void act(async () => {
                          const data = {
                            label: f.get('label'),
                            kind: f.get('kind') || 'base',
                            quota_gib: Number(f.get('quota_gib')),
                            days: Number(f.get('days')),
                            count: Number(f.get('count')),
                            valid_days: Number(f.get('valid_days')),
                            permanent: customKind === 'base' && f.get('permanent') === '1',
                            reset_period: customKind === 'base' ? f.get('reset_period') || 'never' : 'never',
                            reset_interval: Number(f.get('reset_interval') || 30),
                          };
                          const r = await api<{ codes: { code: string }[] }>(
                            'admin/cards',
                            data,
                          );
                          setCodes(r.codes.map((c) => c.code));
                          await loadAdmin();
                          setNotice(
                            '卡密已生成，请立即保存。完整卡密只显示这一次。',
                          );
                        });
                      }}
                    >
                      <div className="form-grid">
                        {content?.package_billing && <Field label="卡密类型">
                          <Select name="kind" value={customKind} onValueChange={v => setCustomKind(v || 'base')}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="base">独立套餐卡</SelectItem><SelectItem value="addon">加流量卡（不增加天数）</SelectItem></SelectContent></Select>
                        </Field>}
                        <Field label="卡名称">
                          <Input
                            name="label"
                            defaultValue="标准月卡"
                            required
                            maxLength={60}
                          />
                        </Field>
                        <Field label="流量额度（GiB）">
                          <Input
                            type="number"
                            name="quota_gib"
                            defaultValue={100}
                            required
                            min={1}
                            max={8388607}
                          />
                        </Field>
                        {customKind === 'base' && <CycleFields value={customCycle} onChange={setCustomCycle} />}
                        <Field label="套餐天数（永久 / 加流量卡忽略）">
                          <Input
                            type="number"
                            name="days"
                            disabled={customKind === 'addon' || !!customCycle.permanent}
                            defaultValue={30}
                            required
                            min={1}
                            max={365000}
                          />
                        </Field>
                        <Field label="生成数量">
                          <Input
                            type="number"
                            name="count"
                            defaultValue={1}
                            required
                            min={1}
                            max={100}
                          />
                        </Field>
                        <Field label="兑换期限（天，0 为不限）">
                          <Input
                            type="number"
                            name="valid_days"
                            defaultValue={90}
                            required
                            min={0}
                            max={365000}
                          />
                        </Field>
                      </div>
                      <Button type="submit" disabled={busy}>
                        {busy ? '处理中…' : '生成卡密'}
                        <Ticket />
                      </Button>
                    </form>
                  </details>
                  {codes.length > 0 && (
                    <div className="issued">
                      <p>
                        新卡密 · {codes.length} 张{' '}
                        <span className="small muted">
                          刷新页面后无法再次查看
                        </span>
                      </p>
                      <textarea
                        readOnly
                        aria-label="新生成的卡密"
                        value={codes.join('\n')}
                        rows={Math.min(8, codes.length + 1)}
                      />
                      <div className="actions">
                        <Button
                          variant="outline"
                          onClick={() => void act(() => copy(codes.join('\n')))}
                        >
                          <Copy />
                          复制全部
                        </Button>
                        <Button variant="outline" onClick={exportCodes}>
                          <Download />
                          下载卡密
                        </Button>
                        <Button variant="outline" onClick={() => void act(() => copy(codes.map(code => cardLink(code, location.origin)).join('\n')))}>复制兑换链接</Button>
                      </div>
                    </div>
                  )}
                </section>
                <CardSearch
                  onRevoke={async (id) => {
                    await api('admin/revoke', { id });
                    await loadAdmin();
                  }}
                />
                <LoginDiagnosis />
                <MailHistory />
                <section className="section" id="admin-audit">
                  <h2>
                    操作记录 <span className="muted small">最近 100 条</span>
                  </h2>
                  <div className="audit-list">
                    {admin?.audit.map((a, i) => (
                      <div key={i}>
                        <span>
                          {a.actor} ·{' '}
                          {(
                            {
                              'card.issue': '生成卡密',
                              'card.redeem': '兑换卡密',
                              'card.revoke': '作废卡密',
                              'account.register': '注册账号',
                              'account.password': '修改密码',
                              'account.disable': '停用账号',
                              'account.enable': '恢复账号',
                              'account.reset_password': '重置密码',
                              'plan.save': '更新套餐',
                              'notice.save': '更新公告',
                              'support.save': '更新联系方式',
                            } as Record<string, string>
                          )[a.action] || a.action}
                        </span>
                        <time className="small muted">{date(a.created)}</time>
                      </div>
                    ))}
                  </div>
                </section>
              </>
            )}
            {view === 'admin' && me && !me.user.admin && (
              <p className="message">此页面仅管理员可用，请返回「我的」。</p>
            )}
          </>
        )}
        <footer>
          Jamie-Node <span>·</span>{' '}
          <a href="https://blog.chuyi.uk" target="_blank" rel="noreferrer">
            chuyi’s blog <ArrowUpRight size={12} />
          </a>
        </footer>
      </main>
      {showDock(view, !!me, loaded, !!me?.user.must_change) && (
        <DockViewport>
          <nav className="dock" aria-label="主导航">
            {[
              { id: 'home', label: '首页', Icon: Home },
              { id: 'plans', label: '套餐', Icon: Package },
              { id: 'guide', label: '使用', Icon: BookOpen },
              { id: 'account', label: '我的', Icon: UserRound },
            ].map(({ id, label, Icon }) => (
              <button
                key={id}
                disabled={!!me?.user.must_change}
                onClick={() => navigate(id)}
                className={tabFor(view) === id ? 'selected' : ''}
                aria-current={tabFor(view) === id ? 'page' : undefined}
              >
                <Icon size={20} />
                <span>{label}</span>
              </button>
            ))}
          </nav>
        </DockViewport>
      )}
      <AlertDialog
        open={!!confirm}
        onOpenChange={(open) => {
          if (!open) setConfirm(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogTitle>{confirm?.title}</AlertDialogTitle>
          <AlertDialogDescription>{confirm?.text}</AlertDialogDescription>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              disabled={busy}
              onClick={() => {
                const action = confirm;
                void act(async () => {
                  await action?.run();
                  setConfirm(null);
                  setNotice('操作已完成');
                });
              }}
            >
              确认
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
captureCardLink();
window.addEventListener('hashchange', captureCardLink);
createRoot(document.getElementById('root')!).render(<App />);
