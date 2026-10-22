import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { RefreshCw } from 'lucide-react';
import { api } from './api';
import { notify } from './toast';
import { orderLabels } from './payments';

type AdminOrder = {
  id: string;
  label: string;
  amount: string;
  pay_amount: string;
  network: string;
  status: string;
  guest: number;
  created: number;
  updated: number;
  error: string;
  tx_hash: string;
  account_id: string | null;
  username: string | null;
  gateway_id: string | null;
  checked: number;
  attempts: number;
};
type OrderPage = {
  items: AdminOrder[];
  total: number;
  page: number;
  pages: number;
  counts: Record<string, number>;
  enabled: boolean;
};
// Orders needing a human first; the rest in lifecycle order.
const filters: [string, string][] = [
  ['all', '全部'],
  ['review', '待核对'],
  ['paid', '到账中'],
  ['pending', '待付款'],
  ['confirming', '确认中'],
  ['fulfilled', '已完成'],
  ['expired', '已过期'],
  ['creating', '创建中'],
];
const when = (n: number) => (n ? new Date(n * 1000).toLocaleString('zh-CN', { hour12: false }) : '—');
function openUser(id: string) {
  history.pushState({ ...history.state, userDetail: true }, '', '#/admin_users?user=' + encodeURIComponent(id));
  window.dispatchEvent(new Event('hashchange'));
}

export function AdminOrders() {
  const [status, setStatus] = useState('all');
  const [q, setQ] = useState('');
  const [keyword, setKeyword] = useState('');
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [data, setData] = useState<OrderPage | null>(null);
  const [error, setError] = useState('');
  const [checking, setChecking] = useState('');
  useEffect(() => {
    const timer = setTimeout(() => {
      setKeyword(q.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [q]);
  useEffect(() => {
    let active = true;
    const load = () => {
      if (document.visibilityState !== 'visible') return;
      api<OrderPage>('admin/orders?' + new URLSearchParams({ status, q: keyword, page: String(page) }))
        .then((r) => {
          if (!active) return;
          setData(r);
          setError('');
        })
        .catch((e) => active && setError(e.message));
    };
    load();
    const timer = setInterval(load, 30000);
    document.addEventListener('visibilitychange', load);
    return () => {
      active = false;
      clearInterval(timer);
      document.removeEventListener('visibilitychange', load);
    };
  }, [status, keyword, page, refresh]);
  const check = async (order: AdminOrder) => {
    setChecking(order.id);
    try {
      const result = await api<{ status: string; error: string }>('admin/order-check', { id: order.id });
      notify(
        result.error
          ? `查单完成：${orderLabels[result.status] || result.status}，${result.error}`
          : `查单完成：${orderLabels[result.status] || result.status}`,
        result.error ? 'error' : 'success',
      );
      setRefresh((n) => n + 1);
    } catch (e) {
      notify((e as Error).message, 'error');
    } finally {
      setChecking('');
    }
  };
  return (
    <>
      <header className="page-heading">
        <div>
          <h1>支付订单</h1>
          <p className="small muted">金额按下单时的套餐原价；买家实付可能带网关识别尾数。</p>
        </div>
        <Button variant="outline" onClick={() => setRefresh((n) => n + 1)}>
          <RefreshCw size={15} />
          刷新
        </Button>
      </header>
      {data && !data.enabled && <p className="message">在线支付未开启，仅可查看已有订单，不能查单。</p>}
      <div className="queue-toolbar">
        <Input
          aria-label="搜索订单"
          placeholder="订单号、支付编号、交易哈希或用户名"
          value={q}
          maxLength={100}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>
      <div className="member-filters">
        {filters
          .filter(([key]) => !data || key === 'all' || key === status || data.counts[key])
          .map(([key, label]) => (
            <button
              key={key}
              aria-pressed={status === key}
              onClick={() => {
                setStatus(key);
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
          {error}
        </p>
      )}
      {!data && !error && <p role="status">正在读取订单…</p>}
      {data && (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>套餐</th>
                <th>金额</th>
                <th>账号</th>
                <th>状态</th>
                <th>下单时间</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.items.map((o) => (
                <tr key={o.id}>
                  <td>
                    {o.label}
                    <small className="block muted mono">{o.id}</small>
                  </td>
                  <td data-label="金额">
                    {o.amount} USDT
                    {o.pay_amount && o.pay_amount !== o.amount && (
                      <small className="block muted">实付 {o.pay_amount}</small>
                    )}
                  </td>
                  <td data-label="账号">
                    {o.account_id && o.username ? (
                      <button className="text-link" onClick={() => openUser(o.account_id!)}>
                        {o.username}
                      </button>
                    ) : o.guest ? (
                      '访客'
                    ) : (
                      <span className="muted">已删除账号</span>
                    )}
                  </td>
                  <td data-label="状态">
                    <span className={`payment-status payment-status-${o.status}`}>
                      {orderLabels[o.status] || o.status}
                    </span>
                    {o.error && <small className="block payment-error">{o.error}</small>}
                  </td>
                  <td data-label="下单时间">
                    {when(o.created)}
                    {o.status !== 'fulfilled' && (
                      <small className="block muted">
                        最近查单 {when(o.checked)} · {o.attempts} 次
                      </small>
                    )}
                  </td>
                  <td className="cell-actions">
                    <details>
                      <summary className="text-link">详情</summary>
                      <dl className="small">
                        <dt>支付编号</dt>
                        <dd className="mono">{o.gateway_id || '待创建'}</dd>
                        {o.network && (
                          <>
                            <dt>网络</dt>
                            <dd>{o.network === 'binance' ? 'BSC' : o.network}</dd>
                          </>
                        )}
                        {o.tx_hash && (
                          <>
                            <dt>交易</dt>
                            <dd className="mono">{o.tx_hash}</dd>
                          </>
                        )}
                      </dl>
                    </details>
                    {data.enabled && o.status !== 'fulfilled' && (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!!checking}
                        onClick={() => void check(o)}
                      >
                        {checking === o.id ? '查单中…' : '立即查单'}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!data.items.length && <p className="empty">没有符合条件的订单。</p>}
        </div>
      )}
      {data && data.pages > 1 && (
        <div className="user-pagination">
          <Button variant="ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            上一页
          </Button>
          <span>
            第 {data.page} / {data.pages} 页 · 共 {data.total} 单
          </span>
          <Button variant="ghost" disabled={page >= data.pages} onClick={() => setPage(page + 1)}>
            下一页
          </Button>
        </div>
      )}
    </>
  );
}
