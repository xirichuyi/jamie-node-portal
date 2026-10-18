import { useEffect, useState, type ReactNode } from 'react';
import {
  LayoutDashboard,
  Users,
  Ticket,
  LifeBuoy,
  Megaphone,
  ScrollText,
  ArrowLeft,
  Search,
} from 'lucide-react';
import { api } from './api';

type Badges = { tickets: number; sync_errors: number; pending: number };
export const adminViews = [
  'operations',
  'admin_users',
  'admin',
  'admin_tickets',
  'admin_content',
  'admin_logs',
];
const items = [
  { id: 'operations', label: '概览', Icon: LayoutDashboard },
  { id: 'admin_users', label: '用户', Icon: Users },
  { id: 'admin', label: '卡密', Icon: Ticket },
  { id: 'admin_tickets', label: '工单', Icon: LifeBuoy },
  { id: 'admin_content', label: '公告与套餐', Icon: Megaphone },
  { id: 'admin_logs', label: '日志', Icon: ScrollText },
];
export function openUserSearch(q: string) {
  history.pushState(history.state, '', '#/admin_users?q=' + encodeURIComponent(q));
  window.dispatchEvent(new Event('hashchange'));
}
// Card codes, tails and redemption links go to the card ledger; anything else is a user search.
const looksLikeCard = (q: string) =>
  /[?&]code=/.test(q) || /^[0-9a-fA-F]{4,8}$/.test(q) || /^[0-9a-fA-F]{8}(-?[0-9a-fA-F]{8}){3}$/.test(q.replace(/\s/g, ''));
function openCardSearch(q: string) {
  history.pushState(history.state, '', '#/admin?tab=records&q=' + encodeURIComponent(q));
  window.dispatchEvent(new Event('hashchange'));
}
export function AdminShell({
  view,
  navigate,
  children,
}: {
  view: string;
  navigate: (view: string) => void;
  children: ReactNode;
}) {
  const [badges, setBadges] = useState<Badges | null>(null);
  const [q, setQ] = useState('');
  useEffect(() => {
    let active = true;
    const load = () => {
      if (document.visibilityState !== 'visible') return;
      api<Badges>('admin/badges')
        .then((b) => active && setBadges(b))
        .catch(() => {});
    };
    load();
    const timer = setInterval(load, 60000);
    document.addEventListener('visibilitychange', load);
    return () => {
      active = false;
      clearInterval(timer);
      document.removeEventListener('visibilitychange', load);
    };
  }, [view]);
  const badge = (id: string) =>
    id === 'admin_tickets'
      ? badges?.tickets
      : id === 'admin_users'
        ? (badges?.sync_errors || 0) + (badges?.pending || 0)
        : 0;
  return (
    <div className="admin-shell">
      <aside className="admin-sidebar" aria-label="管理工作台">
        <p className="admin-sidebar-title">管理工作台</p>
        <form
          className="admin-quick-search"
          role="search"
          onSubmit={(e) => {
            e.preventDefault();
            const value = q.trim();
            if (value) (looksLikeCard(value) ? openCardSearch : openUserSearch)(value);
            setQ('');
          }}
        >
          <Search size={15} aria-hidden="true" />
          <input
            aria-label="快速查找用户或卡密"
            placeholder="查找用户或卡密…"
            value={q}
            maxLength={32}
            onChange={(e) => setQ(e.target.value)}
          />
        </form>
        <nav>
          {items.map(({ id, label, Icon }) => {
            const count = badge(id);
            return (
              <button
                key={id}
                aria-current={view === id ? 'page' : undefined}
                onClick={() => navigate(id)}
              >
                <Icon size={17} aria-hidden="true" />
                <span>{label}</span>
                {!!count && (
                  <em
                    className={id === 'admin_users' && badges?.sync_errors ? 'alert' : ''}
                    aria-label={`${count} 项待处理`}
                  >
                    {count > 99 ? '99+' : count}
                  </em>
                )}
              </button>
            );
          })}
        </nav>
        <button className="admin-exit" onClick={() => navigate('home')}>
          <ArrowLeft size={16} aria-hidden="true" />
          返回用户端
        </button>
      </aside>
      <div className="admin-content">{children}</div>
    </div>
  );
}

/** Underlined section tabs inside one admin page; state lives in the URL hash query. */
export function useAdminTab(initial: string) {
  const read = () =>
    new URLSearchParams(location.hash.split('?')[1] || '').get('tab') || initial;
  const [tab, setTab] = useState(read);
  useEffect(() => {
    const sync = () => setTab(read());
    window.addEventListener('hashchange', sync);
    window.addEventListener('popstate', sync);
    return () => {
      window.removeEventListener('hashchange', sync);
      window.removeEventListener('popstate', sync);
    };
  }, []);
  const change = (next: string) => {
    const base = location.hash.split('?')[0];
    history.replaceState(history.state, '', base + (next === initial ? '' : '?tab=' + next));
    setTab(next);
  };
  return [tab, change] as const;
}
export function AdminTabs({
  tabs,
  value,
  onChange,
}: {
  tabs: [string, string, number?][];
  value: string;
  onChange: (tab: string) => void;
}) {
  return (
    <div className="admin-tabs" role="tablist">
      {tabs.map(([id, label, count]) => (
        <button
          key={id}
          role="tab"
          aria-selected={value === id}
          onClick={() => onChange(id)}
        >
          {label}
          {count !== undefined && <small>{count}</small>}
        </button>
      ))}
    </div>
  );
}
