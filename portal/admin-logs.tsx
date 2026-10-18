import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { api } from './api';
import { MailHistory } from './admin-support';
import { AdminTabs, useAdminTab } from './admin-shell';

type AuditItem = {
  action: string;
  created: number;
  actor: string;
  target_user_id: string | null;
  target_user: string | null;
  card_label: string | null;
  card_suffix: string | null;
};
type AuditPage = { items: AuditItem[]; total: number; page: number; pages: number };

export const auditLabels: Record<string, string> = {
  'card.issue': '生成卡密',
  'card.redeem': '兑换卡密',
  'card.revoke': '作废卡密',
  'card.note': '修改卡密备注',
  'account.register': '注册账号',
  'account.password': '修改密码',
  'account.disable': '停用账号',
  'account.enable': '恢复账号',
  'account.reset_password': '重置密码',
  'account.revoke_sessions': '退出网站登录',
  'account.retry_sync': '重试节点同步',
  'account.grant': '后台赠送权益',
  'account.note': '更新用户备注',
  'package.queue_fix': '按顺延规则修正到期',
  'plan.save': '更新套餐',
  'notice.save': '更新公告',
  'support.save': '更新联系方式',
  'incident.save': '发布服务事件',
  'ticket.create': '提交工单',
  'ticket.reply': '回复工单',
  'ticket.close': '关闭工单',
  'staff.alerts': '修改工单邮件提醒',
  'mail.test': '发送测试邮件',
};
const filters: [string, string][] = [
  ['', '全部操作'],
  ['card.', '卡密相关'],
  ['account.', '账号相关'],
  ['account.grant', '后台赠送'],
  ['card.revoke', '作废卡密'],
  ['account.disable', '停用账号'],
];
const when = (n: number) => new Date(n * 1000).toLocaleString('zh-CN', { hour12: false });
function userLink(id: string) {
  return '#/admin_users?user=' + encodeURIComponent(id);
}

function AuditLog() {
  const [action, setAction] = useState('');
  const [q, setQ] = useState('');
  const [keyword, setKeyword] = useState('');
  const [page, setPage] = useState(1);
  const [data, setData] = useState<AuditPage | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    setError('');
    api<AuditPage>('admin/audit?' + new URLSearchParams({ action, q: keyword, page: String(page) }))
      .then((r) => active && setData(r))
      .catch((e) => active && setError(e.message));
    return () => {
      active = false;
    };
  }, [action, keyword, page]);
  return (
    <section className="section">
      <div className="log-toolbar">
        <div className="member-filters">
          {filters.map(([id, label]) => (
            <button
              key={id}
              aria-pressed={action === id}
              onClick={() => {
                setAction(id);
                setPage(1);
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <form
          className="support-search"
          onSubmit={(e) => {
            e.preventDefault();
            setKeyword(q.trim());
            setPage(1);
          }}
        >
          <Input
            aria-label="按用户名或卡密尾号筛选"
            placeholder="用户名或 8 位卡密尾号"
            value={q}
            maxLength={64}
            onChange={(e) => setQ(e.target.value)}
          />
          <Button variant="outline">筛选</Button>
        </form>
      </div>
      {error && <p className="message error">{error}</p>}
      {!data && !error && <p role="status">正在读取操作记录…</p>}
      {data && (
        <>
          <p className="small muted">共 {data.total} 条</p>
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>时间</th>
                  <th>操作人</th>
                  <th>操作</th>
                  <th>对象</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((a, i) => (
                  <tr key={i}>
                    <td data-label="时间" className="nowrap muted">{when(a.created)}</td>
                    <td data-label="操作人">{a.actor}</td>
                    <td data-label="操作">{auditLabels[a.action] || a.action}</td>
                    <td data-label="对象">
                      {a.target_user_id ? (
                        <a className="text-link" href={userLink(a.target_user_id)}>
                          {a.target_user}
                        </a>
                      ) : a.card_suffix ? (
                        <span>
                          {a.card_label} · 尾号 {a.card_suffix}
                        </span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!data.items.length && <p className="empty muted">没有符合条件的记录。</p>}
          <div className="user-pagination">
            <Button variant="ghost" disabled={data.page <= 1} onClick={() => setPage(data.page - 1)}>
              上一页
            </Button>
            <span>
              第 {data.page} / {data.pages} 页
            </span>
            <Button variant="ghost" disabled={data.page >= data.pages} onClick={() => setPage(data.page + 1)}>
              下一页
            </Button>
          </div>
        </>
      )}
    </section>
  );
}

export function LogsWorkspace() {
  const [tab, setTab] = useAdminTab('audit');
  return (
    <>
      <header className="page-heading">
        <div>
          <h1>日志</h1>
          <p className="muted">管理操作与邮件发送记录，便于排查和追溯。</p>
        </div>
      </header>
      <AdminTabs
        value={tab}
        onChange={setTab}
        tabs={[
          ['audit', '操作记录'],
          ['mail', '邮件记录'],
        ]}
      />
      {tab === 'audit' ? <AuditLog /> : <MailHistory />}
    </>
  );
}
