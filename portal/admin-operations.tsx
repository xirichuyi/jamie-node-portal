import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { lazy, Suspense, useState } from 'react';
import { api } from './api';
import { PageTitle } from './content';
const OperationsReadiness = lazy(() =>
  import('./admin-support').then((module) => ({
    default: module.OperationsReadiness,
  })),
);

import {
  Choice,
  Field,
  form,
  states,
  useData,
  useWork,
  when,
  type Incident,
  type Nav,
  type Status,
} from './features';

type Ops = {
  counts: Record<string, number>;
  budgets: {
    id: number;
    name: string;
    up: number | null;
    down: number | null;
    total: number | null;
    reset: string;
    enabled: boolean;
  }[];
  budgets_at: number;
  backup_at: number | null;
  batches: {
    label: string;
    created: number;
    total: number;
    redeemed: number;
    available: number;
    revoked: number;
    expired: number;
  }[];
  status: Status;
  trend?: { date: string; registered: number; redeemed: number }[];
  mail?: { enabled: boolean; staff_alerts: boolean };
};
function TrendBars({
  title,
  rows,
  field,
}: {
  title: string;
  rows: NonNullable<Ops['trend']>;
  field: 'registered' | 'redeemed';
}) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...rows.map((r) => r[field]));
  const total = rows.reduce((n, r) => n + r[field], 0);
  const active = hover === null ? null : rows[hover];
  return (
    <figure className="trend-card">
      <figcaption>
        <span>{title}</span>
        <strong>{total}</strong>
        <small className="muted">
          {active ? `${active.date.slice(5)} · ${active[field]}` : `近 ${rows.length} 天`}
        </small>
      </figcaption>
      <div className="trend-bars" onMouseLeave={() => setHover(null)}>
        {rows.map((r, i) => (
          <button
            key={r.date}
            type="button"
            aria-label={`${r.date} ${title} ${r[field]}`}
            className={hover === i ? 'active' : ''}
            onMouseEnter={() => setHover(i)}
            onFocus={() => setHover(i)}
            onBlur={() => setHover(null)}
          >
            <span style={{ height: r[field] ? `${Math.max(6, (r[field] / max) * 100)}%` : '2px' }} />
          </button>
        ))}
      </div>
      <div className="trend-axis small muted">
        <span>{rows[0]?.date.slice(5)}</span>
        <span>今天</span>
      </div>
    </figure>
  );
}
export function Operations({
  navigate,
  onMembers,
}: {
  navigate: Nav;
  onMembers?: (scope: string) => void;
}) {
  const { data, reload, placeholder } = useData<Ops>('admin/operations'),
    work = useWork(),
    [incident, setIncident] = useState<Incident | null>(null);
  return (
    <>
      <PageTitle
        eyebrow="OPERATIONS"
        title="运营概览"
        description="优先处理待办，及时发现服务异常。"
      />
      <div className="actions">
        <Button onClick={() => navigate('admin')}>生成卡密</Button>
        <Button variant="outline" onClick={() => navigate('admin_users')}>
          查找用户
        </Button>
        <Button variant="outline" onClick={() => navigate('admin_tickets')}>
          处理工单
        </Button>
        <Button variant="ghost" onClick={() => void reload()}>
          刷新
        </Button>
      </div>
      {placeholder}
      {work.feedback}
      {data && (
        <>
          <div className="ops-metrics">
            {[
              ['用户总数', 'users'],
              ['有效订阅', 'active'],
              ['7 天内到期', 'expiring'],
              ['等待同步', 'pending'],
              ['同步异常', 'sync_errors'],
              ['待回复工单', 'waiting_tickets'],
            ].map(([label, key]) => (
              <button
                key={key}
                onClick={() =>
                  key === 'waiting_tickets'
                    ? navigate('admin_tickets')
                    : onMembers
                      ? onMembers(key === 'users' ? 'all' : key)
                      : navigate('admin')
                }
              >
                <span>{label}</span>
                <strong>{data.counts[key] || 0}</strong>
              </button>
            ))}
          </div>
          {!!data.trend?.length && (
            <div className="trend-grid">
              <TrendBars title="新注册" rows={data.trend} field="registered" />
              <TrendBars title="卡密兑换（含后台赠送）" rows={data.trend} field="redeemed" />
            </div>
          )}
          <details className="ops-readiness">
            <summary>服务检查与告警</summary>
            <Suspense fallback={<p role="status">正在加载服务检查…</p>}>
              <OperationsReadiness />
            </Suspense>
          </details>
          <section className="section">
            <div className="section-heading">
              <h2>节点代理预算</h2>
              <span className="small muted">
                更新于 {when(data.budgets_at)}
              </span>
            </div>
            <p className="small muted">
              这是面板内代理累计流量，不含其他进程与系统开销，不等于服务商整机计费流量。
            </p>
            {(!data.budgets_at ||
              Date.now() / 1000 - data.budgets_at > 900) && (
              <p className="message error">
                预算数据暂未更新，请检查面板连接。
              </p>
            )}
            <div className="node-budgets">
              {data.budgets.map((b) => (
                <div key={b.id}>
                  <h3>{b.name}</h3>
                  <strong>
                    {b.up === null || b.down === null
                      ? '未知'
                      : ((b.up + b.down) / 1e12).toFixed(3)}{' '}
                    /{' '}
                    {b.total ? (b.total / 1e12).toFixed(0) + ' TB' : '未设上限'}
                  </strong>
                  <p className="small muted">
                    {b.reset === 'never'
                      ? '累计额度 · 不自动重置'
                      : '重置方式：' + b.reset}{' '}
                    · {b.enabled ? '已启用' : '已暂停'}
                  </p>
                  {b.total &&
                  b.up !== null &&
                  b.down !== null &&
                  (b.up + b.down) / b.total >= 0.9 ? (
                    <p className="message error">
                      已使用至少 90%，请检查额度。
                    </p>
                  ) : null}
                </div>
              ))}
            </div>
          </section>
          <div className="feature-split">
            <section className="section">
              <h2>服务事件</h2>
              <details className="incident-form" open={!!incident} key={incident?.id || 'closed'}>
              <summary>{incident ? '编辑事件' : '发布新事件'}</summary>
              <form
                key={incident?.id || 'new'}
                onSubmit={(e) => {
                  const values = form(e);
                  void work.run(async () => {
                    await api('admin/incident', {
                      ...values,
                      ...(incident ? { id: incident.id } : {}),
                    });
                    setIncident(null);
                    await reload();
                    work.setMessage('服务事件已发布');
                  });
                }}
              >
                <Field label="标题">
                  <Input
                    name="title"
                    required
                    maxLength={100}
                    defaultValue={incident?.title || ''}
                  />
                </Field>
                <Field label="状态">
                  <Choice
                    name="status"
                    label="事件状态"
                    initial={incident?.status || 'investigating'}
                    options={{
                      investigating: '正在排查',
                      maintenance: '维护中',
                      resolved: '已恢复',
                    }}
                  />
                </Field>
                <Field label="说明">
                  <textarea
                    name="body"
                    required
                    maxLength={4000}
                    rows={4}
                    defaultValue={incident?.body || ''}
                  />
                </Field>
                <Button type="submit" disabled={work.busy}>
                  {incident ? '更新事件' : '发布事件'}
                </Button>
                {incident && (
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => setIncident(null)}
                  >
                    取消编辑
                  </Button>
                )}
              </form>
              </details>
              {data.status.incidents.map((i) => (
                <button
                  className="ticket-row"
                  key={i.id}
                  onClick={() => setIncident(i)}
                >
                  <strong>{i.title}</strong>
                  <span>{states[i.status]} · 编辑</span>
                </button>
              ))}
            </section>
            <section className="section">
              <h2>备份与服务</h2>
              <p>最近数据库备份：{when(data.backup_at)}</p>
              {(!data.backup_at ||
                Date.now() / 1000 - data.backup_at > 36 * 3600) && (
                <p className="message error">
                  超过 36 小时没有检测到备份，请检查备份任务。
                </p>
              )}
              <p className="small muted">
                仅检查备份文件时间，不代表已完成恢复演练。
                {data.mail
                  ? data.mail.enabled
                    ? ` 邮件服务已配置；新工单邮件提醒${data.mail.staff_alerts ? '已开启' : '已关闭'}。`
                    : ' 邮件服务未配置，用户收不到验证码和提醒。'
                  : ''}
              </p>
              <Button variant="outline" onClick={() => navigate('status')}>
                查看服务状态
              </Button>
            </section>
          </div>
          <section className="section">
            <div className="section-heading">
              <h2>最近发卡批次</h2>
              <button className="text-link" onClick={() => { history.pushState(history.state, '', '#/admin?tab=batches'); window.dispatchEvent(new Event('hashchange')); }}>
                全部批次 →
              </button>
            </div>
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr><th>批次</th><th>总数</th><th>可用</th><th>已兑换</th><th>已作废</th><th>已过期</th></tr>
                </thead>
                <tbody>
                  {data.batches.slice(0, 5).map((b, i) => (
                    <tr key={i}>
                      <td>{b.label}<small className="block muted">{when(b.created)}</small></td>
                      <td data-label="总数">{b.total}</td><td data-label="可用">{b.available}</td><td data-label="已兑换">{b.redeemed}</td><td data-label="已作废">{b.revoked}</td><td data-label="已过期">{b.expired}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!data.batches.length && <p className="empty">还没有发卡记录。</p>}
          </section>
        </>
      )}
    </>
  );
}
