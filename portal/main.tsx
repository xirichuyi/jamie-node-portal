import React, {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { createRoot } from 'react-dom/client';
import { DockViewport } from './dock-viewport';
import { AuthFlow } from './auth';
import { OrdersPage } from './payments';
import { InstallGuide } from './install';
import { captureCardLink, pendingCard } from './card-entry';
import { ruleLabel, FOREVER, type CycleRule } from './cycle-labels';
const UserManager = React.lazy(() =>
  import('./admin-users').then((module) => ({ default: module.UserManager })),
);
import { NoticeEntry } from './notice-entry';
const AdminShell = React.lazy(() => import('./admin-shell').then((m) => ({ default: m.AdminShell })));
import { Toaster, notify } from './toast';
const CardsWorkspace = React.lazy(() =>
  import('./admin-cards').then((module) => ({ default: module.CardsWorkspace })),
);
const AdminOrders = React.lazy(() =>
  import('./admin-orders').then((module) => ({ default: module.AdminOrders })),
);
const LogsWorkspace = React.lazy(() =>
  import('./admin-logs').then((module) => ({ default: module.LogsWorkspace })),
);
import {
  ArrowUpRight,
  Home,
  LogOut,
  Moon,
  Sun,
  UserRound,
  ArrowLeft,
  BookOpen,
  Package,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { PackageBalance } from './features';
import '@/app/globals.css';
import './style.css';
import './content.css';
import './glass.css';
import './features.css';
import './layout.css';
import './admin.css';
import './payments.css';
import './mobile.css';
import {
  Dashboard,
  AccountHub,
  DeviceGuide,
} from './journeys';
import {
  Connection,
  UsagePanel,
  Redemption,
  ServiceStatus,
  useData,
} from './features';
import {
  useNavigation,
  tabFor,
  isAuthenticationView,
  authModeFor,
  afterLogin,
  showDock,
  adminViews,
} from './navigation';
import { api, ApiError } from './api';
import {
  Announcements,
  PlansPage,
  HelpPage,
  PageTitle,
  type Catalog,
} from './content';

import type { TicketDraft } from './account-features';
const Tickets = React.lazy(() => import('./account-features').then(m => ({ default: m.Tickets })));
const Sessions = React.lazy(() => import('./account-features').then(m => ({ default: m.Sessions })));
const Recover = React.lazy(() => import('./account-features').then(m => ({ default: m.Recover })));
const Operations = React.lazy(() => import('./admin-operations').then(m => ({ default: m.Operations })));
const ContentAdmin = React.lazy(() => import('./admin-content').then(m => ({ default: m.ContentAdmin })));

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
  incidents: { id: string; title: string }[];
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
type Redeemed = CycleRule & {
  label: string;
  quota: number;
  days: number;
  kind?: string;
  redeemed_at: number;
};
// Fetched only on the history and redeem pages, not with every account refresh.
function RedemptionHistory() {
  const { data, placeholder } = useData<{ history: Redeemed[] }>('history');
  if (!data) return placeholder;
  return data.history.length ? (
    <div className="history">
      {data.history.map((h, i) => (
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
    <p className="empty muted">暂无记录</p>
  );
}
function returningVisitor() {
  try {
    return localStorage.getItem('jamie-returning') === '1';
  } catch {
    return false;
  }
}
function App() {
  const [justActivated, setJustActivated] = useState(false);
  const [memberScope, setMemberScope] = useState('all');
  const [historyVersion, setHistoryVersion] = useState(0);
  const { view, navigate: setView, back } = useNavigation();
  const [content, setContent] = useState<Catalog | null>(null);
  const [contentError, setContentError] = useState('');
  const contentRequest = useRef(0);
  const accountRequests = useRef(0);
  const accountVersion = useRef(0);
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
    [error, setError] = useState('');
  // Follow the system appearance until the visitor picks one with the toggle.
  const systemDark = () =>
    typeof matchMedia !== 'undefined' && matchMedia('(prefers-color-scheme: dark)').matches;
  const [dark, setDark] = useState(() => {
    try {
      const saved = localStorage.getItem('jamie-theme');
      return saved ? saved === 'dark' : systemDark();
    } catch {
      return systemDark();
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
  async function load(background = false) {
    if (background && accountRequests.current) return null;
    accountRequests.current++;
    const version = ++accountVersion.current;
    try {
      const m = await api<Me>('me');
      if (version !== accountVersion.current) return m;
      setMe(m);
      try {
        localStorage.setItem('jamie-returning', '1');
      } catch {}
      if (m.user.must_change) setView('security', true);
      return m;
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        if (version === accountVersion.current) setMe(null);
        return null;
      }
      throw e;
    } finally {
      accountRequests.current--;
      if (version === accountVersion.current) setLoaded(true);
    }
  }
  async function act(fn: () => Promise<void>) {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : '请求失败，请重试');
      if (e instanceof ApiError && e.status === 401) {
        accountVersion.current++;
        setMe(null);
      }
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
    document.addEventListener('visibilitychange', refresh);
    return () => document.removeEventListener('visibilitychange', refresh);
  }, []);
  useEffect(() => {
    if (!me) return;
    const refresh = () => {
      if (document.visibilityState === 'visible')
        void load(true).catch((e) => setError(e.message));
    };
    document.addEventListener('visibilitychange', refresh);
    return () => document.removeEventListener('visibilitychange', refresh);
  }, [me?.user.username]);
  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
  }, [dark]);
  useEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)');
    const follow = () => {
      try {
        if (localStorage.getItem('jamie-theme')) return;
      } catch {}
      setDark(media.matches);
    };
    media.addEventListener('change', follow);
    return () => media.removeEventListener('change', follow);
  }, []);
  useEffect(() => {
    if (me?.subscription.pending) {
      let stopped = false;
      let timer: ReturnType<typeof setTimeout>;
      const refresh = async () => {
        if (document.visibilityState === 'visible') await load(true).catch(() => {});
        if (!stopped) timer = setTimeout(refresh, 15000);
      };
      timer = setTimeout(refresh, 15000);
      return () => { stopped = true; clearTimeout(timer); };
    }
  }, [me?.subscription.pending]);
  // Feedback floats above the page so it stays visible after long scrolls.
  useEffect(() => {
    if (notice) {
      notify(notice);
      setNotice('');
    }
  }, [notice]);
  useEffect(() => {
    if (error) {
      notify(error, 'error');
      setError('');
    }
  }, [error]);
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
  const s = me?.subscription;
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
            onClick={() => {
              setDark(!dark);
              try {
                localStorage.setItem('jamie-theme', dark ? 'light' : 'dark');
              } catch {}
            }}
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
          (isAuthenticationView(view, !!me) ? ' auth-layout' : '') +
          (me?.user.admin && adminViews.includes(view) ? ' admin-mode' : '')
        }
      >
        <InstallGuide visible={loaded && !me?.user.must_change && !isAuthenticationView(view, !!me) && ['home', 'plans', 'guide', 'account'].includes(view)} promote={['home', 'plans'].includes(view)} />
        {loaded && tabFor(view) !== view && !me?.user.must_change && !(me?.user.admin && adminViews.includes(view)) && (
          <button className="back-link" onClick={back}>
            <ArrowLeft size={17} />
            返回
          </button>
        )}
        {view !== 'notices' && !adminViews.includes(view) && (
          <NoticeEntry
            showStrip={view === 'home'}
            deferPopup={!loaded || isAuthenticationView(view, !!me)}
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
        <React.Suspense fallback={<p className="muted" role="status">加载中…</p>}>
        {!loaded && !['plans', 'guide', 'help', 'notices', 'recover', 'orders'].includes(view) ? (
          <p className="muted" role="status">加载中…</p>
        ) : !me &&
          !['plans', 'guide', 'help', 'notices', 'recover', 'orders'].includes(view) ? (
          <AuthFlow
            mode={view === 'redeem' && pendingCard() ? (returningVisitor() ? 'login' : 'register') : authModeFor(view, returningVisitor())}
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
            {me?.user.admin && adminViews.includes(view) && (
              <AdminShell view={view} navigate={navigate}>
                <React.Suspense fallback={<p role="status">正在加载…</p>}>
                  {view === 'operations' && (
                    <Operations
                      navigate={navigate}
                      onMembers={(scope) => {
                        setMemberScope(scope);
                        navigate('admin_users');
                      }}
                    />
                  )}
                  {view === 'admin_tickets' && <Tickets staff />}
                  {view === 'admin_users' && (
                    <UserManager initialScope={memberScope} plans={content?.plans || []} packageBilling={!!content?.package_billing} />
                  )}
                  {view === 'admin_content' && (
                    <>
                      <PageTitle
                        eyebrow=""
                        title="公告与套餐"
                        description=""
                      />
                      <ContentAdmin onSaved={loadContent} />
                    </>
                  )}
                  {view === 'admin' && (
                    <CardsWorkspace plans={content?.plans || []} packageBilling={!!content?.package_billing} />
                  )}
                  {view === 'admin_logs' && <LogsWorkspace />}
                  {view === 'admin_orders' && <AdminOrders />}
                </React.Suspense>
              </AdminShell>
            )}
            {view === 'recover' && <Recover navigate={navigate} />}
            {view === 'orders' && <OrdersPage signedIn={!!me} onChanged={async () => { await load(); }} />}
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
            {adminViews.includes(view) &&
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
                username={me?.user.username}
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
                <PageTitle eyebrow="" title="公告" description="" />
                <Announcements notices={content?.notices || []} />
              </>
            )}
            {view === 'home' && s && me && (
              <Dashboard
                s={s}
                incidents={me.incidents}
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
                <PageTitle eyebrow="" title="连接与订阅" description="" />
                <div className="subscription-layout">
                  <Connection
                    s={s}
                    navigate={navigate}
                    onChanged={async () => {
                      await load();
                    }}
                  />
                  <aside className="subscription-help">
                    <h2>其他设备</h2>
                    <button
                      className="text-link"
                      onClick={() => navigate('guide')}
                    >
                      按设备查看教程 →
                    </button>
                    <hr />
                    <h2>遇到问题</h2>
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
                  setHistoryVersion((v) => v + 1);
                }}
                navigate={navigate}
              />
            )}
            {(view === 'redeem' || view === 'history') && me && (
              <>
                {view === 'history' && (
                  <PageTitle eyebrow="" title="兑换记录" description="" />
                )}
                <section className="section">
                  {view === 'redeem' && <h2>兑换记录</h2>}
                  <RedemptionHistory key={historyVersion} />
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
                    accountVersion.current++;
                    setMe(null);
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
                  <p className="message">请先修改初始密码。</p>
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
                        setNotice('密码已更新，其他设备需重新登录');
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
                      accountVersion.current++;
                      setMe(null);
                      setView('home');
                    })
                  }
                >
                  <LogOut />
                  退出登录
                </Button>
              </>
            )}
          </>
        )}
        </React.Suspense>
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
      <Toaster />
    </>
  );
}
captureCardLink();
window.addEventListener('hashchange', captureCardLink);
createRoot(document.getElementById('root')!).render(<App />);
