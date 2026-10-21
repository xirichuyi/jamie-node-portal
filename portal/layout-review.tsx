// Local Vite-only visual fixtures. Not a production entrypoint or auth bypass.
import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Dashboard,
  AccountHub,
  DeviceGuide,
  AdminNavigation,
} from './journeys';
import { PlansPage, Announcements, PageTitle, type Catalog } from './content';
import { NoticeEntry } from './notice-entry';
import { Connection, UsagePanel } from './features';
import { Tickets, Sessions, DeleteAccount } from './account-features';
import { Operations } from './admin-operations';
import { Button } from '@/components/ui/button';
import { TermsFields, defaultTerms } from './cycles';
import '@/app/globals.css';
import './style.css';
import './content.css';
import './glass.css';
import './features.css';
import './layout.css';
const now = Math.floor(Date.now() / 1000);
const nodes = [
  {
    id: 1,
    name: '🇯🇵 日本 · 东京',
    status: 'online',
    heartbeat: now,
    latency_ms: 30,
  },
  {
    id: 2,
    name: '🇸🇬 新加坡',
    status: 'online',
    heartbeat: now,
    latency_ms: 45,
  },
  {
    id: 3,
    name: '🇲🇾 马来西亚 · 柔佛',
    status: 'online',
    heartbeat: now,
    latency_ms: 55,
  },
];
const status = { checked_at: now, nodes, incidents: [], events: [] };
const samples = Array.from({ length: 30 }, (_, i) => ({
  day: new Date((now - (29 - i) * 86400) * 1000).toISOString().slice(0, 10),
  bytes: i < 23 ? null : ((i % 5) + 1) * 2 ** 28,
  partial: i === 23,
}));
const responses: Record<string, unknown> = {
  nodes: status,
  'service-status': status,
  usage: {
    days: samples,
    sampled: now,
    started: now - 7 * 86400,
    timezone: 'Asia/Shanghai',
  },
  'admin/operations': {
    counts: {
      users: 12,
      active: 8,
      expiring: 2,
      pending: 1,
      sync_errors: 1,
      waiting_tickets: 2,
    },
    budgets: nodes.map((n) => ({
      ...n,
      up: 1e10,
      down: 5e11,
      total: 9e12,
      reset: 'never',
      enabled: true,
    })),
    budgets_at: now,
    backup_at: now,
    status,
    batches: [],
  },
  tickets: { tickets: [] },
  notifications: { ticket_email: false, available: true },
  'admin/tickets': { tickets: [] },
  sessions: {
    sessions: [
      {
        id: 'fixture',
        agent: '示例浏览器',
        ip: '127.0.0.1',
        created: now,
        seen: now,
        current: true,
      },
    ],
    recovery_created: null,
    email_verified: true,
    email: 'jamie@example.com',
    username: 'jamie@example.com',
    admin: false,
  },
};
window.fetch = async (input, init) => {
  const key = String(input).replace('/api/', '');
  if (init?.method === 'POST')
    return new Response(
      JSON.stringify({ error: '布局验收模式不执行数据修改' }),
      { status: 403 },
    );
  return new Response(JSON.stringify(responses[key] || {}), {
    headers: { 'Content-Type': 'application/json' },
  });
};
const subscription = {
  quota: 100 * 1024 ** 3,
  used: 23 * 1024 ** 3,
  expires: now + 26 * 86400,
  url: 'https://example.invalid/sub/layout-fixture',
  pending: false,
  sync_error: null,
  usage_error: null,
  enabled: true,
  plan_name: '标准月卡',
};
const catalog: Catalog = {
  plans: [
    {
      id: 'fixture',
      name: '标准月卡',
      description: '三个地区节点，适合日常使用。',
      quota_gib: 100,
      days: 30,
      price_label: '价格请咨询管理员',
      badge: '月度方案',
      published: 1,
      sort_order: 0,
      revision: 1,
    },
  ],
  notices: [
    { id: 'review-maintenance', title: '日本节点维护通知', body: '日本节点将在今晚进行短时维护。\n维护期间可切换至新加坡或马来西亚节点。', category: 'maintenance', pinned: 1, published: 1, created: now, updated: now, revision: 1 },
    { id: 'review-update', title: '订阅与客户端使用说明', body: '添加新设备时，前往首页导入订阅即可。\n请妥善保管订阅链接，不要公开分享。', category: 'update', pinned: 0, published: 1, created: now - 86400, updated: now - 86400, revision: 1 },
  ],
  support: {
    contact_label: '联系管理员',
    contact_url: '',
    contact_note: '示例联系方式',
    revision: 1,
  },
};
function Review() {
  const [view, setView] = useState(new URLSearchParams(location.search).get('view') || 'home'),
    [scenario, setScenario] = useState('active'),
    [dark, setDark] = useState(false);
  const navigate = (next: string) => {
    setView(next);
    window.scrollTo(0, 0);
  };
  const s =
    scenario === 'new'
      ? { ...subscription, quota: 0, used: 0, expires: 0, url: null }
      : scenario === 'expired'
        ? { ...subscription, expires: now - 100 }
        : subscription;
  return (
    <>
      <header className="brand">
        <strong>Jamie-Node</strong>
        <span>本地布局验收 · 示例数据</span>
        <button
          onClick={() => {
            document.documentElement.classList.toggle('dark');
            setDark(!dark);
          }}
        >
          {dark ? '浅色' : '深色'}
        </button>
      </header>
      <main className={'wide view-' + view}>
        <div
          style={{
            display: 'flex',
            gap: 12,
            marginBottom: 24,
            flexWrap: 'wrap',
          }}
        >
          <label>
            页面{' '}
            <select
              aria-label="验收页面"
              value={view}
              onChange={(e) => navigate(e.target.value)}
            >
              {[
                ['home', '首页'],
                ['notices', '公告'],
                ['plans', '套餐'],
                ['guide', '使用'],
                ['account', '我的'],
                ['subscription', '订阅'],
                ['usage', '用量明细'],
                ['operations', '运营概览'],
                ['tickets', '工单'],
                ['sessions', '会话与恢复码'],
                ['delete-admin', '管理员删除确认'],
                ['cycles', '周期套餐设置'],
              ].map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          <label>
            场景{' '}
            <select
              aria-label="订阅场景"
              value={scenario}
              onChange={(e) => setScenario(e.target.value)}
            >
              <option value="active">正常使用</option>
              <option value="new">尚未开通</option>
              <option value="expired">订阅到期</option>
            </select>
          </label>
        </div>
        {view === 'home' && <NoticeEntry notices={catalog.notices} ready navigate={navigate} />}
        {view === 'notices' && <><PageTitle eyebrow="" title="公告" description="维护通知与服务动态。" /><Announcements notices={catalog.notices} /></>}
        {view === 'home' && (
          <Dashboard
            s={s}
            incidents={[]}
            username="Jamie"
            content={catalog}
            navigate={navigate}
            refresh={() => {}}
            busy={false}
          />
        )}
        {view === 'plans' && (
          <PlansPage content={catalog} navigate={navigate} subscription={s} />
        )}
        {view === 'guide' && <DeviceGuide navigate={navigate} url={s.url} />}
        {view === 'account' && (
          <AccountHub
            username="jamie.long.email@example.com"
            admin
            s={s}
            navigate={navigate}
            logout={() => {}}
            busy={false}
          />
        )}
        {view === 'subscription' && (
          <Connection s={s} navigate={navigate} onChanged={async () => {}} />
        )}
        {view === 'operations' && (
          <>
            <AdminNavigation view={view} navigate={navigate} />
            <Operations navigate={navigate} />
          </>
        )}
        {view === 'tickets' && <Tickets />}
        {view === 'sessions' && <Sessions />}
        {view === 'cycles' && <section className="surface"><h2>周期套餐设置</h2><div className="form-grid"><TermsFields value={defaultTerms} onChange={() => {}} /></div></section>}
        {view === 'delete-admin' && <section className="user-detail-section"><h2>账号操作</h2><div className="actions"><Button variant="outline">重置密码</Button><Button variant="outline">退出网站登录</Button><Button variant="outline">停用账号</Button><DeleteAccount username="jamie@example.com" userId="fixture-user" /></div></section>}
        {view === 'usage' && <><PageTitle eyebrow="" title="用量明细" description="" /><UsagePanel navigate={navigate} /></>}
      </main>
      <nav className="dock" aria-label="主导航">
        {[
          ['home', '首页'],
          ['plans', '套餐'],
          ['guide', '使用'],
          ['account', '我的'],
        ].map(([v, l]) => (
          <button
            className={view === v ? 'selected' : ''}
            key={v}
            onClick={() => navigate(v)}
          >
            {l}
          </button>
        ))}
      </nav>
    </>
  );
}
createRoot(document.getElementById('root')!).render(
  new URLSearchParams(location.search).has('mobile')
    ? <iframe title="390px 移动端验收" src={'/layout-review.html?view=' + encodeURIComponent(new URLSearchParams(location.search).get('view') || 'home')} style={{display:'block',width:390,height:844,margin:'20px auto',border:'1px solid #dce3de',borderRadius:20}} />
    : <Review />
);
