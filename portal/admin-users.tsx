import { DeleteAccount } from './account-features';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from '@/components/ui/select';
import { LoginDiagnosis } from './admin-support';
import { expiryLabel, ruleLabel } from './cycles';
import {
  PackageBalances,
  type PackageBalance,
} from './features';
import {
  Sheet,
  SheetContent,
  SheetTitle,
  SheetDescription,
} from '@/components/ui/sheet';
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import {
  Table,
  TableHeader,
  TableRow,
  TableHead,
  TableBody,
  TableCell,
} from '@/components/ui/table';
import { api } from './api';
import { notify } from './toast';
import { auditLabels } from './admin-logs';
import { GrantDialog, UserNote } from './admin-grant';
import type { Plan } from './content';
import { remainingTime } from './experience';

export type ManagedUser = {
  id: string;
  username: string;
  admin: number;
  disabled: number;
  deleting?: number;
  quota: number;
  used: number | null;
  remaining: number | null;
  expires: number;
  final_expires?: number;
  created: number;
  plan_name: string | null;
  primary_state: string;
  subscription_state: string;
  sync_state: string;
  sync_error: string | null;
  last_sync_attempt: number;
  last_synced_at: number;
  must_change: number;
  last_web_seen: number | null;
  last_proxy_activity: number | null;
  proxy_activity: 'unknown' | 'recent' | 'unconfirmed';
  counter_reset: number;
  has_note?: number;
  packages?: PackageBalance[];
};
type Listing = {
  members: ManagedUser[];
  total: number;
  page: number;
  pages: number;
  counts: Record<string, number>;
  checked_at: number;
  usage_error: string | null;
};
type Detail = {
  member: ManagedUser;
  history: {
    label: string;
    quota: number;
    days: number;
    kind?: string;
    redeemed_at: number;
    granted?: number;
    suffix?: string;
    note?: string;
  }[];
  note: { body: string; updated: number; updated_by: string } | null;
  audit: { actor: string; action: string; created: number }[];
  sessions: number;
  last_seen: number | null;
  checked_at: number;
  usage_error: string | null;
};
export const userStates: Record<string, string> = {
  active: '可用',
  expired: '已到期',
  exhausted: '流量耗尽',
  disabled: '账号停用',
  unknown: '待确认',
  unopened: '尚未开通',
  pending: '待同步',
  error: '同步异常',
  synced: '已同步',
};
const scopes = [
  ['all', '全部'],
  ['active', '可用'],
  ['expiring', '即将到期'],
  ['expired', '已到期'],
  ['exhausted', '流量耗尽'],
  ['disabled', '账号停用'],
  ['sync_errors', '同步异常'],
  ['pending', '待同步'],
  ['unknown', '待确认'],
  ['unopened', '尚未开通'],
];
const volume = (v: number | null) =>
  v === null
    ? '—'
    : (v / 1024 ** 3).toLocaleString('zh-CN', { maximumFractionDigits: 2 });
const time = (v: number | null) =>
  v
    ? new Date(v * 1000).toLocaleString('zh-CN', { hour12: false })
    : '暂无记录';
const selectedFromURL = () =>
  typeof location === 'undefined'
    ? ''
    : new URLSearchParams(location.hash.split('?')[1] || '').get('user') || '';
export function UserStatus({ member: m }: { member: ManagedUser }) {
  return (
    <>
      <span className={'user-state state-' + m.primary_state}>
        {m.deleting ? '删除处理中' : userStates[m.primary_state] || '待确认'}
      </span>
      {m.sync_state !== 'synced' && (
        <small className="sync-caption">{userStates[m.sync_state]}</small>
      )}
    </>
  );
}
const actions: Record<string, string> = {
  ...auditLabels,
  'account.register': '开通账号',
};
const sorts: [string, string][] = [
  ['created:desc', '最新注册'],
  ['created:asc', '最早注册'],
  ['username:asc', '用户名 A–Z'],
  ['expires:asc', '最早到期'],
  ['remaining:asc', '剩余流量从少到多'],
  ['remaining:desc', '剩余流量从多到少'],
  ['used:desc', '已用流量从多到少'],
  ['last_proxy_activity:desc', '最近代理活动'],
  ['last_web_seen:desc', '最近网站活动'],
];
// Show a separate final date only when it falls on a later day than the nearest one.
const laterDay = (m: { expires: number; final_expires?: number }) =>
  !!m.final_expires && m.final_expires > m.expires && expiryLabel(m.final_expires) !== expiryLabel(m.expires);
const queryFromURL = () =>
  typeof location === 'undefined'
    ? ''
    : new URLSearchParams(location.hash.split('?')[1] || '').get('q') || '';
function csvCell(value: unknown) {
  const text = value === null || value === undefined ? '' : String(value);
  // Neutralize spreadsheet formulas and quote every cell.
  return (
    '"' + (/^[=+\-@]/.test(text) ? "'" + text : text).replace(/"/g, '""') + '"'
  );
}

export function UserManager({
  initialScope = 'all',
  plans = [],
  packageBilling = false,
}: {
  initialScope?: string;
  plans?: Plan[];
  packageBilling?: boolean;
}) {
  const [q, setQ] = useState(queryFromURL),
    [scope, setScope] = useState(initialScope),
    [page, setPage] = useState(1);
  const [sort, setSort] = useState('created:desc');
  const [data, setData] = useState<Listing | null>(null),
    [error, setError] = useState(''),
    [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState(selectedFromURL),
    [detail, setDetail] = useState<Detail | null>(null),
    [detailError, setDetailError] = useState('');
  const [confirm, setConfirm] = useState<string | null>(null),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState(''),
    [secret, setSecret] = useState(''),
    [copied, setCopied] = useState(false);
  const sequence = useRef(0),
    detailSequence = useRef(0),
    activeUser = useRef(selected),
    actionLock = useRef(false);
  const load = useCallback(async () => {
    const version = ++sequence.current;
    setLoading(true);
    setError('');
    try {
      const result = await api<Listing>(
        'admin/users?' +
          new URLSearchParams({
            q,
            scope,
            page: String(page),
            sort: sort.split(':')[0],
            direction: sort.split(':')[1],
          }),
      );
      if (version === sequence.current) setData(result);
    } catch (e) {
      if (version === sequence.current) setError((e as Error).message);
    } finally {
      if (version === sequence.current) setLoading(false);
    }
  }, [q, scope, page, sort]);
  useEffect(() => {
    setData(null);
    const timer = setTimeout(() => void load(), 250);
    return () => {
      clearTimeout(timer);
      sequence.current++;
    };
  }, [load]);
  const loadDetail = useCallback(async () => {
    if (!selected) return;
    const version = ++detailSequence.current;
    try {
      const result = await api<Detail>(
        'admin/user?id=' + encodeURIComponent(selected),
      );
      if (version === detailSequence.current) {
        setDetail(result);
        setDetailError('');
      }
    } catch (e) {
      if (version === detailSequence.current)
        setDetailError((e as Error).message);
    }
  }, [selected]);
  useEffect(() => {
    const sync = () => {
      const id = selectedFromURL();
      activeUser.current = id;
      setSelected(id);
      const query = queryFromURL();
      if (query) {
        setQ(query);
        setScope('all');
        setPage(1);
      }
    };
    window.addEventListener('popstate', sync);
    window.addEventListener('hashchange', sync);
    sync();
    return () => {
      activeUser.current = '';
      window.removeEventListener('popstate', sync);
      window.removeEventListener('hashchange', sync);
    };
  }, []);
  useEffect(() => {
    setDetail(null);
    setDetailError('');
    setMessage('');
    setConfirm(null);
    setSecret('');
    setCopied(false);
    void loadDetail();
    const refresh = () => {
      if (document.visibilityState === 'visible' && !actionLock.current)
        void loadDetail();
    };
    const timer = setInterval(refresh, 15000);
    document.addEventListener('visibilitychange', refresh);
    return () => {
      detailSequence.current++;
      clearInterval(timer);
      document.removeEventListener('visibilitychange', refresh);
    };
  }, [loadDetail]);
  const open = (id: string) => {
    history.pushState(
      { ...history.state, userDetail: true },
      '',
      '#/admin_users?user=' + encodeURIComponent(id),
    );
    window.dispatchEvent(new Event('hashchange'));
  };
  const close = () => {
    if (busy) return;
    if (history.state?.userDetail) history.back();
    else {
      history.replaceState(history.state, '', '#/admin_users');
      window.dispatchEvent(new Event('hashchange'));
    }
  };
  const perform = async () => {
    if (!detail || !confirm || actionLock.current) return;
    const m = detail.member,
      action = confirm;
    actionLock.current = true;
    setBusy(true);
    setMessage('');
    setDetailError('');
    try {
      if (action === 'password') {
        const result = await api<{ password: string }>('admin/reset-password', {
          id: m.id,
        });
        if (activeUser.current !== m.id) return;
        setSecret(result.password);
      } else if (action === 'status')
        await api('admin/member', {
          id: m.id,
          disabled: !m.disabled,
          expected_disabled: !!m.disabled,
        });
      else
        await api(
          action === 'sessions' ? 'admin/user-sessions' : 'admin/user-sync',
          { id: m.id },
        );
      if (activeUser.current !== m.id) return;
      setMessage(
        action === 'password'
          ? '密码已重置，用户下次登录必须修改密码。'
          : action === 'sessions'
            ? '网站登录已退出，代理客户端不受影响。'
            : action === 'sync'
              ? '已请求重试，请以下方节点状态为准。'
              : '账号状态已更新，请同时查看节点同步结果。',
      );
      if (action !== 'password') setConfirm(null);
      await Promise.all([loadDetail(), load()]);
    } catch (e) {
      if (activeUser.current === m.id) setDetailError((e as Error).message);
    } finally {
      actionLock.current = false;
      setBusy(false);
    }
  };
  const exportCSV = async () => {
    try {
      const result = await api<{ members: ManagedUser[] }>(
        'admin/users?' +
          new URLSearchParams({
            q,
            scope,
            sort: sort.split(':')[0],
            direction: sort.split(':')[1],
            export: '1',
          }),
      );
      const header = [
        '用户名',
        '套餐',
        '状态',
        '剩余流量(GiB)',
        '总流量(GiB)',
        '到期时间',
        '注册时间',
        '最近网站活动',
      ];
      const rows = result.members.map((u) => [
        u.username,
        u.plan_name || '',
        u.disabled ? '账号停用' : userStates[u.primary_state] || '',
        u.remaining === null ? '' : (u.remaining / 1024 ** 3).toFixed(2),
        (u.quota / 1024 ** 3).toFixed(2),
        u.expires ? expiryLabel(u.expires) : '',
        time(u.created),
        u.last_web_seen ? time(u.last_web_seen) : '',
      ]);
      const csv =
        '\ufeff' +
        [header, ...rows].map((r) => r.map(csvCell).join(',')).join('\r\n');
      const url = URL.createObjectURL(
        new Blob([csv], { type: 'text/csv;charset=utf-8' }),
      );
      const a = document.createElement('a');
      a.href = url;
      a.download = `Jamie-Node-users-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      notify(`已导出 ${rows.length} 位用户`);
    } catch (e) {
      notify((e as Error).message, 'error');
    }
  };
  const m = detail?.member;
  return (
    <>
      <header className="page-heading">
        <div>
          <h1>用户管理</h1>
          <p className="muted">查找用户，查看订阅与处理记录。</p>
        </div>
        <div className="actions">
          <Button
            variant="ghost"
            disabled={!data?.total}
            onClick={() => void exportCSV()}
          >
            导出 CSV
          </Button>
          <Button
            variant="outline"
            disabled={loading}
            onClick={() => void load()}
          >
            刷新列表
          </Button>
        </div>
      </header>
      <div className="user-toolbar">
        <Select
          value={sort}
          onValueChange={(value) => {
            if (value) setSort(value);
            setPage(1);
          }}
        >
          <SelectTrigger aria-label="用户排序">
            <SelectValue>{sorts.find(([v]) => v === sort)?.[1]}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            {sorts.map(([value, label]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input
          aria-label="搜索全部用户"
          placeholder="搜索用户名或邮箱"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setPage(1);
          }}
          maxLength={32}
        />
        <p className="small muted">
          {data
            ? `共 ${data.total} 位符合条件的用户`
            : '搜索全部用户，不限最近注册'}
        </p>
      </div>
      <details className="user-detail-section">
        <summary>排查用户登录问题</summary>
        <LoginDiagnosis />
      </details>
      <div className="member-filters user-filter-list">
        {scopes
          // Empty filters are noise; keep 全部, the active one and anything with users.
          .filter(
            ([key]) =>
              !data || key === 'all' || key === scope || data.counts[key],
          )
          .map(([key, label]) => (
            <button
              key={key}
              aria-pressed={scope === key}
              onClick={() => {
                setScope(key);
                setPage(1);
              }}
            >
              {label}
              {data ? ` ${data.counts[key] || 0}` : ''}
            </button>
          ))}
      </div>
      {error && (
        <p role="alert" className="message error">
          {error} <button onClick={() => void load()}>重试</button>
        </p>
      )}
      {data?.usage_error && (
        <p className="message" role="status">
          {data.usage_error}
        </p>
      )}
      {loading && !data && <p role="status">正在读取用户…</p>}
      <Table className="admin-table user-table">
        <TableHeader>
          <TableRow>
            {['用户', '套餐', '剩余 / 总流量', '最近到期', '状态', '活动'].map(
              (t) => (
                <TableHead key={t}>{t}</TableHead>
              ),
            )}
          </TableRow>
        </TableHeader>
        <TableBody>
          {data?.members.map((u) => (
            <TableRow
              key={u.id}
              className="managed-user-row"
              onClick={() => open(u.id)}
            >
              <TableCell className="cell-title">
                <button
                  className="text-link"
                  onClick={(e) => {
                    e.stopPropagation();
                    open(u.id);
                  }}
                >
                  {u.username}
                </button>
                {!!u.has_note && (
                  <span className="tag" title="有管理员备注">
                    备注
                  </span>
                )}
                {!!u.admin && <small className="sync-caption">管理员</small>}
              </TableCell>
              <TableCell data-label="套餐">
                {u.plan_name || '尚未开通'}
              </TableCell>
              <TableCell data-label="剩余 / 总流量">
                {volume(u.remaining)} / {volume(u.quota)} GiB
              </TableCell>
              <TableCell data-label="最近到期">
                {u.expires ? expiryLabel(u.expires) : '尚未开通'}
                <small className="sync-caption">
                  {laterDay(u)
                    ? `最晚 ${expiryLabel(u.final_expires!)}`
                    : remainingTime(u.expires)}
                </small>
              </TableCell>
              <TableCell data-label="状态">
                <UserStatus member={u} />
              </TableCell>
              <TableCell data-label="活动">
                <span>
                  {u.proxy_activity === 'recent'
                    ? '最近有流量'
                    : u.proxy_activity === 'unknown'
                      ? '代理活动未知'
                      : '暂无近期流量记录'}
                </span>
                <small className="sync-caption">
                  网站：{time(u.last_web_seen)}
                </small>
                {!!u.counter_reset && (
                  <small className="sync-caption">流量计数回退，需核对</small>
                )}
              </TableCell>
            </TableRow>
          ))}
          {data && !data.members.length && (
            <TableRow>
              <TableCell colSpan={6}>
                没有符合条件的用户。可以清空搜索或切换筛选。
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
      <p className="small muted">
        代理活动由相邻采样的流量变化判断，不等于实时在线人数；网站活动仅表示保留会话中的最近访问。
      </p>
      {data && (
        <div className="user-pagination">
          <Button
            variant="ghost"
            disabled={loading || data.page <= 1}
            onClick={() => setPage(data.page - 1)}
          >
            上一页
          </Button>
          <span>
            第 {data.page} / {data.pages} 页 · 每页 25 位
          </span>
          <Button
            variant="ghost"
            disabled={loading || data.page >= data.pages}
            onClick={() => setPage(data.page + 1)}
          >
            下一页
          </Button>
        </div>
      )}
      <Sheet
        open={!!selected}
        onOpenChange={(value) => {
          if (!value) close();
        }}
      >
        <SheetContent className="user-detail-sheet" showCloseButton={false}>
          <div className="detail-top">
            <div>
              <SheetTitle>{m?.username || '用户详情'}</SheetTitle>
              <SheetDescription>
                {m ? `注册于 ${time(m.created)}` : '正在加载账号信息'}
              </SheetDescription>
            </div>
            <Button variant="ghost" disabled={busy} onClick={close}>
              关闭
            </Button>
          </div>
          {detailError && (
            <p className="message error" role="alert">
              {detailError}{' '}
              <button className="text-link" onClick={() => void loadDetail()}>
                刷新详情
              </button>
            </p>
          )}
          {message && (
            <p className="message" role="status">
              {message}
            </p>
          )}
          {detail && m && (
            <>
              {m.packages && <PackageBalances packages={m.packages} />}
              {!m.deleting && (
                <section className="user-detail-section">
                  <h2>调整权益</h2>
                  <p className="small muted">
                    直接为该用户发放套餐或加流量，用于补偿、赠送或线下收款后开通；记录会出现在兑换与操作记录中。
                  </p>
                  <GrantDialog
                    member={m}
                    plans={plans}
                    packageBilling={packageBilling}
                    disabled={busy || !!m.disabled}
                    onGranted={async () => {
                      await Promise.all([loadDetail(), load()]);
                    }}
                  />
                  {!!m.disabled && (
                    <p className="small muted">账号已停用，恢复后才能赠送。</p>
                  )}
                </section>
              )}
              <UserNote userId={m.id} note={detail.note} onSaved={loadDetail} />
              <section className="user-detail-section">
                <h2>当前状态</h2>
                <dl className="user-facts">
                  <div>
                    <dt>账号</dt>
                    <dd>{m.disabled ? '已停用' : '允许登录'}</dd>
                  </div>
                  <div>
                    <dt>订阅</dt>
                    <dd>{userStates[m.subscription_state]}</dd>
                  </div>
                  <div>
                    <dt>节点同步</dt>
                    <dd>{userStates[m.sync_state]}</dd>
                  </div>
                </dl>
                {m.sync_error && (
                  <p className="message error">{m.sync_error}</p>
                )}
                <p className="small muted">
                  最近尝试：{time(m.last_sync_attempt)} · 最近成功：
                  {time(m.last_synced_at)}
                </p>
                {m.sync_state !== 'synced' && !m.admin && (
                  <Button
                    variant="outline"
                    disabled={busy}
                    onClick={() => setConfirm('sync')}
                  >
                    重试节点同步
                  </Button>
                )}
              </section>
              <section className="user-detail-section">
                <h2>{m.plan_name || '订阅权益'}</h2>
                <dl className="user-facts">
                  <div>
                    <dt>剩余流量</dt>
                    <dd>{volume(m.remaining)} GiB</dd>
                  </div>
                  <div>
                    <dt>已用 / 总额度</dt>
                    <dd>
                      {volume(m.used)} / {volume(m.quota)} GiB
                    </dd>
                  </div>
                  {laterDay(m) ? (
                    <>
                      <div>
                        <dt>最近到期</dt>
                        <dd>{expiryLabel(m.expires)}</dd>
                      </div>
                      <div>
                        <dt>最晚到期（服务截止）</dt>
                        <dd>{expiryLabel(m.final_expires!)}</dd>
                      </div>
                    </>
                  ) : (
                    <div>
                      <dt>有效期至</dt>
                      <dd>{m.expires ? expiryLabel(m.expires) : '尚未开通'}</dd>
                    </div>
                  )}
                </dl>
                <p className="small muted">
                  用量读取于 {time(detail.checked_at)}
                  {detail.usage_error ? ' · 读取失败，未知用量不计为零' : ''}
                </p>
              </section>
              <details className="user-detail-section">
                <summary>兑换记录 · 最近 {detail.history.length} 条</summary>
                {detail.history.length ? (
                  detail.history.map((r, i) => (
                    <div className="user-record" key={i}>
                      <strong>
                        {r.label}
                        {!!r.granted && <span className="tag">后台赠送</span>}
                      </strong>
                      <span>
                        +{volume(r.quota)} GiB ·{' '}
                        {r.kind === 'addon' ? '不增加天数' : ruleLabel(r)}
                      </span>
                      <small>
                        {time(r.redeemed_at)}
                        {r.suffix && ` · 卡密尾号 ${r.suffix}`}
                        {r.note && ` · 备注：${r.note}`}
                      </small>
                    </div>
                  ))
                ) : (
                  <p className="muted">暂无兑换记录</p>
                )}
              </details>
              <details className="user-detail-section">
                <summary>操作记录 · 最近 {detail.audit.length} 条</summary>
                {detail.audit.map((r, i) => (
                  <div className="user-record" key={i}>
                    <strong>{actions[r.action] || r.action}</strong>
                    <span>{r.actor}</span>
                    <small>{time(r.created)}</small>
                  </div>
                ))}
              </details>
              {!m.admin && (
                <section className="user-detail-section">
                  <h2>账号操作</h2>
                  {!!m.deleting && (
                    <p role="status" className="message">
                      删除处理中，清理完成后将从列表移除。
                    </p>
                  )}
                  <p className="small muted">
                    当前有效网站会话 {detail.sessions} 个 · 最近活动{' '}
                    {time(detail.last_seen)}
                  </p>
                  <div className="actions">
                    <Button
                      variant="outline"
                      disabled={busy || !!m.deleting}
                      onClick={() => setConfirm('password')}
                    >
                      重置密码
                    </Button>
                    <Button
                      variant="outline"
                      disabled={busy || !detail.sessions}
                      onClick={() => setConfirm('sessions')}
                    >
                      退出网站登录
                    </Button>
                    <Button
                      variant="outline"
                      disabled={busy || !!m.deleting}
                      onClick={() => setConfirm('status')}
                    >
                      {m.disabled ? '恢复账号' : '停用账号'}
                    </Button>
                    <DeleteAccount
                      username={m.username}
                      userId={m.id}
                      disabled={busy || !!m.deleting}
                      onDeleted={() => {
                        setMessage('删除处理中，账号已停用。');
                        history.replaceState(
                          history.state,
                          '',
                          '#/admin_users',
                        );
                        window.dispatchEvent(new Event('hashchange'));
                        void load();
                      }}
                    />
                  </div>
                </section>
              )}
            </>
          )}
          <Dialog
            open={!!confirm}
            onOpenChange={(value) => {
              if (!value && !busy) {
                setConfirm(null);
                setSecret('');
                setCopied(false);
              }
            }}
          >
            <DialogContent>
              <DialogTitle>
                {secret
                  ? `${m?.username} 的临时密码`
                  : confirm === 'password'
                    ? `重置 ${m?.username} 的密码？`
                    : confirm === 'status'
                      ? `${m?.disabled ? '恢复' : '停用'} ${m?.username}？`
                      : confirm === 'sessions'
                        ? `退出 ${m?.username} 的网站登录？`
                        : '重试节点同步？'}
              </DialogTitle>
              <DialogDescription>
                {confirm === 'password'
                  ? '旧密码、恢复码和网站会话会失效。临时密码只展示本次，用户下次登录必须修改。'
                  : confirm === 'status'
                    ? m?.disabled
                      ? '恢复网站访问并下发节点状态，不增加流量、不延长有效期。'
                      : '立即禁止网站登录，并向节点下发停用；节点生效需要等待同步。'
                    : confirm === 'sessions'
                      ? '退出该用户的所有网站会话，不会断开代理客户端，也不会修改密码。'
                      : '重试现有订阅状态，不追加流量或延长有效期。'}
              </DialogDescription>
              {detailError && (
                <p role="alert" className="message error">
                  {detailError}
                </p>
              )}
              {secret ? (
                <>
                  <p>
                    用户名：<strong>{m?.username}</strong>
                  </p>
                  <code className="temporary-password">{secret}</code>
                  <Button
                    onClick={async () => {
                      try {
                        await navigator.clipboard.writeText(
                          `用户名：${m?.username}\n临时密码：${secret}`,
                        );
                        setCopied(true);
                      } catch {
                        setDetailError('复制失败，请手动复制并私下发送。');
                      }
                    }}
                  >
                    {copied ? '已复制' : '复制账号与临时密码'}
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setConfirm(null);
                      setSecret('');
                      setCopied(false);
                    }}
                  >
                    已保存，关闭
                  </Button>
                </>
              ) : (
                <div className="actions">
                  <Button
                    variant="ghost"
                    disabled={busy}
                    onClick={() => setConfirm(null)}
                  >
                    取消
                  </Button>
                  <Button disabled={busy} onClick={() => void perform()}>
                    {busy ? '正在处理…' : '确认操作'}
                  </Button>
                </div>
              )}
            </DialogContent>
          </Dialog>
        </SheetContent>
      </Sheet>
    </>
  );
}
