import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { useEffect, useState } from 'react';
import { api } from './api';
import { Contact, PageTitle } from './content';
import { EmailCode } from './email-code';

import {
  Choice,
  Field,
  form,
  useData,
  useWork,
  when,
  type Nav,
} from './features';

export type Ticket = {
  unread?: number;
  id: string;
  subject: string;
  category: string;
  status: string;
  created: number;
  updated: number;
  username?: string;
  account_id?: string;
};
const ticketCategory: Record<string, string> = {
  connection: '连接问题',
  redeem: '卡密兑换',
  account: '账号问题',
  other: '其他问题',
};
// Staff shortcuts; inserted into the reply box for editing, never sent directly.
const quickReplies: [string, string][] = [
  ['更新订阅', '请在客户端里更新一次订阅（订阅 / 配置页面点刷新），然后换一个节点再试。'],
  ['切换节点', '当前线路可能有波动，请先切换到其他地区的节点，稍后我们会检查该节点。'],
  ['重新导入', '请在网站「连接与订阅」里重新导入订阅；如果重置过订阅链接，旧的配置需要删除后重新添加。'],
  ['已处理', '已为你处理完成，请刷新后查看。如果还有问题，直接回复这个工单即可。'],
  ['需要信息', '为方便排查，请告诉我们：使用的设备和客户端、出现的提示文字，以及大概发生的时间。'],
];
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
  const [filter, setFilter] = useState('waiting'),
    [page, setPage] = useState(1),
    [search, setSearch] = useState(''),
    [keyword, setKeyword] = useState('');
  useEffect(() => {
    const timer = setTimeout(() => {
      setKeyword(search.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);
  // Staff filter, search and paging run on the server so old waiting tickets never drop off.
  const path = staff ? 'admin/tickets' : 'tickets',
    { data, reload, placeholder } = useData<{
      tickets: Ticket[];
      counts?: Record<string, number>;
      page?: number;
      pages?: number;
    }>(
      staff
        ? path + '?' + new URLSearchParams({ status: filter, q: keyword, page: String(page) })
        : path,
      30000,
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
    let seen = selected.messages.at(-1)?.id;
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
          if (last && last.id !== seen) {
            seen = last.id;
            await api('tickets/read', { id, message_id: last.id });
            await reload();
          }
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
        description=""
      />
      {work.feedback}
      {!staff && <NotificationPreferences ticketOnly />}
      {staff && <StaffAlerts />}
      <div
        className={
          'feature-split ticket-workspace ' +
          (selected || creating ? 'ticket-detail-open' : '')
        }
      >
        <section className="section">
          <div className="section-heading">
            <h2>{staff ? '工单列表' : '问题记录'}</h2>
            {!staff && (
              <Button
                variant="outline"
                onClick={() => {
                  setCreating(true);
                  setSelected(null);
                }}
              >
                新建工单
              </Button>
            )}
          </div>
          {staff && (
            <>
              <Input
                aria-label="搜索工单"
                placeholder="搜索标题或用户名"
                value={search}
                maxLength={64}
                onChange={(e) => setSearch(e.target.value)}
              />
              <div className="member-filters ticket-filters">
                {(['waiting', 'replied', 'closed', 'all'] as const).map((key) => (
                  <button
                    key={key}
                    aria-pressed={filter === key}
                    onClick={() => {
                      setFilter(key);
                      setPage(1);
                    }}
                  >
                    {key === 'all' ? '全部' : key === 'waiting' ? '待回复' : ticketStatus[key]}
                    {data?.counts ? ' ' + (data.counts[key] || 0) : ''}
                  </button>
                ))}
              </div>
            </>
          )}
          {placeholder}
          {data && !data.tickets.length && (
            <p className="empty">
              {staff && filter === 'waiting' && !keyword ? '没有待回复的工单，处理完了。' : '暂时没有工单。'}
            </p>
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
                {staff ? ' · ' + t.username + ' · ' + (ticketCategory[t.category] || t.category) : ''}
              </span>
              <small>{when(t.updated)}</small>
            </button>
          ))}
          {staff && !!data?.pages && data.pages > 1 && (
            <div className="user-pagination">
              <Button variant="ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                上一页
              </Button>
              <span>
                {data.page} / {data.pages}
              </span>
              <Button variant="ghost" disabled={page >= data.pages} onClick={() => setPage(page + 1)}>
                下一页
              </Button>
            </div>
          )}
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
                  placeholder="设备、客户端、提示文字和发生时间（不要发送密码或订阅链接）"
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
              {staff && (
                <p className="small muted ticket-meta">
                  {ticketCategory[selected.ticket.category] || selected.ticket.category} · 提交于 {when(selected.ticket.created)} ·{' '}
                  {selected.ticket.account_id ? (
                    <a className="text-link strong-link" href={'#/admin_users?user=' + encodeURIComponent(selected.ticket.account_id)}>
                      {selected.ticket.username} 的账号详情 →
                    </a>
                  ) : (
                    selected.ticket.username
                  )}
                </p>
              )}
              <div className="ticket-messages">
                {selected.messages.map((m, i) => (
                  <article key={i} className={m.staff ? 'staff-reply' : ''}>
                    <small>
                      {m.staff ? '管理员' : staff ? selected.ticket.username || '用户' : '你'} · {when(m.created)}
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
                  {staff && (
                    <div className="quick-replies" aria-label="常用回复">
                      {quickReplies.map(([label, text]) => (
                        <button
                          key={label}
                          type="button"
                          onClick={() => setReply((current) => (current.trim() ? current.trimEnd() + '\n' : '') + text)}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  )}
                  <Field label={staff ? '回复用户（用户开启提醒时会收到邮件）' : '补充说明 / 回复'}>
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
                      {staff ? '标记已解决并关闭' : '问题已解决，关闭'}
                    </Button>
                  </div>
                </form>
              )}
            </>
          ) : (
            <div className="empty">
              <h2>{staff ? '选择一个工单' : '有什么可以帮你？'}</h2>
              <p className="muted">{staff ? '从左侧选择工单' : '选择左侧工单，或新建一个问题'}</p>
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
function StaffAlerts() {
  const { data, reload } = useData<{ ticket_email: boolean; available: boolean; recipients: string[] }>(
    'admin/staff-alerts',
  );
  const work = useWork();
  if (!data) return null;
  return (
    <div className="staff-alerts">
      <label>
        <input
          type="checkbox"
          checked={data.ticket_email}
          disabled={work.busy}
          onChange={(e) => {
            const enabled = e.target.checked;
            void work.run(async () => {
              await api('admin/staff-alerts', { ticket_email: enabled });
              await reload();
            });
          }}
        />{' '}
        用户提交或回复工单时邮件提醒我
      </label>
      <small className="muted">
        {data.available
          ? `发送到 ${data.recipients.join('、')}；管理员已回复的工单不再提醒。`
          : '邮件服务未配置，或管理员账号未绑定邮箱。'}
      </small>
      {work.feedback}
    </div>
  );
}
// "Chrome · macOS" instead of a raw user-agent string.
export function deviceLabel(agent: string | null | undefined) {
  if (!agent) return '未知设备';
  const browser = /Edg\//.test(agent) ? 'Edge' : /OPR\//.test(agent) ? 'Opera' : /MicroMessenger/.test(agent) ? '微信' : /Firefox\//.test(agent) ? 'Firefox' : /Chrome\/|CriOS/.test(agent) ? 'Chrome' : /Safari\//.test(agent) ? 'Safari' : '浏览器';
  const system = /iPhone/.test(agent) ? 'iPhone' : /iPad/.test(agent) ? 'iPad' : /Android/.test(agent) ? 'Android' : /Mac OS X|Macintosh/.test(agent) ? 'macOS' : /Windows/.test(agent) ? 'Windows' : /Linux/.test(agent) ? 'Linux' : '';
  return system ? `${browser} · ${system}` : browser;
}
export function NotificationPreferences({ ticketOnly = false }: { ticketOnly?: boolean }) {
  type Preference = 'ticket_email' | 'traffic_email' | 'expiry_email';
  const { data, reload } = useData<Record<Preference, boolean> & { available: boolean }>('notifications');
  const work = useWork();
  const options: [Preference, string][] = ticketOnly ? [['ticket_email', '工单有新回复时提醒']] : [
    ['traffic_email', '流量剩余不足 10% 时提醒'],
    ['expiry_email', '到期前 3 天提醒'],
    ['ticket_email', '工单有新回复时提醒'],
  ];
  if (ticketOnly && data && !data.available) return null;
  const available = !!data?.available;
  return <div className="notification-preference">
    {!ticketOnly && <h2>邮件提醒</h2>}
    {options.map(([field, label]) => <label key={field}><input type="checkbox" checked={available && !!data?.[field]} disabled={!available || work.busy} onChange={e => {
      const enabled = e.target.checked;
      void work.run(async () => { await api('notifications', { [field]: enabled }); await reload(); });
    }} /> {label}</label>)}
    {data && !data.available && <small className="muted">绑定邮箱后可开启</small>}
    {work.feedback}
  </div>;
}

function ChangeEmail({ email }: { email: string }) {
  const [next, setNext] = useState(''), [password, setPassword] = useState(''), [oldCode, setOldCode] = useState(''), [newCode, setNewCode] = useState('');
  const work = useWork();
  return <section className="section"><h2>登录邮箱</h2>
    <p className="small muted">{email || '未绑定邮箱'}</p>
    <details className="email-change-disclosure" open={!email}><summary>{email ? '更换邮箱' : '绑定邮箱'}</summary>
    <p className="small muted">更换后用新邮箱登录，其他设备需重新登录。</p>
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
        title="邮箱与登录设备"
        description=""
      />
      {work.feedback}
      {data && <ChangeEmail email={data.email || ''} />}
      <NotificationPreferences />
      <div className="feature-split">
        <section className="section">
          <h2>登录设备</h2>
          {placeholder}
          {data?.sessions.map((s) => (
            <div className="session-row" key={s.id}>
              <div>
                <strong>{s.current ? '当前会话' : '其他登录'}</strong>
                <p className="small session-agent" title={s.agent || undefined}>{deviceLabel(s.agent)}</p>
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
          <p className="muted">忘记密码时用来找回账号，请离线保存。</p>
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
            该设备需重新登录，不影响客户端连接。
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
        description=""
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
            {legacy ? '没有恢复码？' : '收不到邮件？'}请联系管理员。
          </p>
          <Contact support={undefined} compact />
        </form>
      )}
    </section>
  );
}
