import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { api } from './api';
import { cardLink } from './card-entry';

type Order = { id: string; label: string; amount: string; pay_amount: string; network: string; status: string; guest: number; created: number; error: string; checkout_url: string | null; code?: string; account_id?: string; gateway_id?: string; tx_hash: string };
type Listing = { items: Order[]; total: number; page: number; pages: number; enabled: boolean; guestError?: boolean };
type Receipt = { id?: string; plan: string; key: string; slot: string };
const storageKey = 'jamie-payment-receipts';
function receipts(): Receipt[] {
  try {
    const data: unknown = JSON.parse(sessionStorage.getItem(storageKey) || '[]');
    return Array.isArray(data) ? data.filter((r): r is Receipt => !!r && typeof r === 'object' && typeof r.key === 'string' && typeof r.slot === 'string' && typeof r.plan === 'string') : [];
  } catch { return []; }
}
function saveReceipt(receipt: Receipt) {
  const entries = receipts().filter(r => r.slot !== receipt.slot);
  sessionStorage.setItem(storageKey, JSON.stringify([...entries, receipt].slice(-20)));
}
function captureReceipt() {
  if (typeof location === 'undefined') return;
  const params = new URLSearchParams(location.hash.split('?')[1]);
  const id = params.get('order'), key = params.get('key');
  if (id && key && /^sub_[a-f0-9]{32}$/.test(id) && /^[A-Za-z0-9_-]{32,128}$/.test(key)) {
    try {
      saveReceipt({ id, key, plan: '', slot: 'guest-recovered-' + id });
      history.replaceState(history.state, '', '#/orders');
    } catch { /* Keep the recovery link if browser storage is unavailable. */ }
  }
}
export function PurchaseButton({ planId, label, price, username, navigate }: { planId: string; label: string; price: number; username?: string; navigate: (view: string) => void }) {
  const [confirm, setConfirm] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const running = useRef(false);
  async function buy() {
    if (running.current) return;
    running.current = true; setBusy(true); setError('');
    try {
      const slot = (username || 'guest') + ':' + planId;
      const previous = receipts().find(r => r.slot === slot);
      const receipt = previous || { plan: planId, key: crypto.randomUUID().replace(/-/g, ''), slot };
      saveReceipt(receipt); // Never create an unrecoverable guest payment if storage is blocked.
      const order = await api<Order>(username ? 'orders' : 'checkout', { plan_id: planId, request_key: receipt.key, expected_amount: price });
      saveReceipt({ ...receipt, id: order.id });
      navigate('orders');
    } catch (e) { setError(e instanceof Error ? e.message : '无法创建订单；请允许本站存储后重试'); }
    finally { running.current = false; setBusy(false); }
  }
  return <div>
    {!confirm ? <Button onClick={() => setConfirm(true)}>USDT 购买 · {price / 1000000}</Button> : <div className="surface">
      <strong>{label} · {price / 1000000} USDT</strong>
      <p className="small muted">{username ? `付款后自动充入当前账号 ${username}，续费沿用现有顺延规则。` : '付款后领取卡密，可用于邮箱注册开通或给已有账号兑换。请保存订单领取链接。'}</p>
      <p className="small muted">收款页选择网络并显示准确金额，可能包含识别订单的小额尾数；请勿提前转账或自行凑整。</p>
      <Button disabled={busy} onClick={() => void buy()}>{busy ? '创建订单…' : '确认并创建支付订单'}</Button>
      <Button variant="ghost" disabled={busy} onClick={() => setConfirm(false)}>取消</Button>
    </div>}
    {error && <p role="alert">{error}</p>}
  </div>;
}

const labels: Record<string, string> = { creating: '正在创建收款单', pending: '等待付款', confirming: '链上确认中', paid: '已付款，套餐到账处理中', fulfilled: '已完成', expired: '订单已过期，请勿继续付款', review: '需要管理员核对' };
export function OrdersPage({ signedIn = false, admin = false, onChanged }: { signedIn?: boolean; admin?: boolean; onChanged?: () => Promise<void> }) {
  const [page, setPage] = useState(1), [refresh, setRefresh] = useState(0);
  const [state, setState] = useState<{ key: string; data?: Listing; error?: string } | null>(null);
  const [copied, setCopied] = useState('');
  const delivered = useRef(new Set<string>());
  const changed = useRef(onChanged);
  useEffect(() => { changed.current = onChanged; }, [onChanged]);
  const key = `${signedIn}:${admin}:${page}:${refresh}`;
  const data = state?.key === key ? state.data : null;
  const error = state?.key === key ? state.error : '';
  useEffect(() => {
    let active = true, timer: ReturnType<typeof setTimeout>;
    captureReceipt();
    const load = async () => {
      try {
        let result: Listing = { items: [], total: 0, page: 1, pages: 1, enabled: true };
        if (signedIn || admin) result = await api<Listing>(`${admin ? 'admin/' : ''}orders?page=${page}`);
        if (!admin && page === 1) {
          for (const receipt of receipts().filter(r => r.slot.startsWith('guest') && r.id).slice(-10)) {
            try {
              const order = await api<Order>('checkout/status', { id: receipt.id, access_key: receipt.key });
              if (!result.items.some(r => r.id === order.id)) result.items.unshift(order);
            } catch { result.guestError = true; /* Preserve the receipt for retry. */ }
          }
        }
        if (!active) return;
        setState({ key, data: result });
        for (const order of result.items) {
          if (['fulfilled', 'expired'].includes(order.status)) {
            // Keep guest claim credentials, but let the same plan be purchased again.
            for (const receipt of receipts().filter(r => r.id === order.id && !r.slot.startsWith('guest-recovered-'))) {
              sessionStorage.setItem(storageKey, JSON.stringify(receipts().filter(r => r.slot !== receipt.slot)));
              if (order.guest) saveReceipt({ ...receipt, slot: 'guest-recovered-' + order.id });
            }
          }
          if (order.status === 'fulfilled' && !order.guest && !delivered.current.has(order.id) && !admin) {
            delivered.current.add(order.id); void changed.current?.().catch(() => {});
          }
        }
      } catch (e) { if (active) setState({ key, error: e instanceof Error ? e.message : '订单加载失败' }); }
      finally { if (active) timer = setTimeout(() => void load(), 15000); }
    };
    void load();
    return () => { active = false; clearTimeout(timer); };
  }, [key, page, signedIn, admin]);
  async function copyReceipt(order: Order) {
    const receipt = receipts().find(r => r.id === order.id);
    if (!receipt) return;
    try { await navigator.clipboard.writeText(location.origin + '/#/orders?order=' + order.id + '&key=' + receipt.key); setCopied(order.id); }
    catch { setCopied('复制失败，请允许剪贴板权限并保留当前页面。'); }
  }
  return <section className="section">
    <h1>{admin ? '支付订单' : '我的支付订单'}</h1>
    <p className="small muted">付款以支付网关确认结果为准，返回本站不会直接判定已付款。过期后不要继续转账；已转账但未到账请提供订单号联系管理员。</p>
    <Button variant="outline" onClick={() => setRefresh(n => n + 1)}>刷新订单</Button>
    {error && <p role="alert">{error}</p>}
    {!data && !error && <output>正在读取订单…</output>}
    {data && !data.enabled && <p>在线支付尚未开放，已有订单记录仍可查看。</p>}
    {data?.guestError && <p role="alert">部分访客订单暂时无法读取，领取凭证仍已保留，请稍后刷新；不要重复付款。</p>}
    {data?.items.map(order => <article className="surface" key={order.id}>
      <h2>{order.label} · {order.amount} USDT</h2>
      <p>{labels[order.status] || order.status}</p>
      <p className="small muted">订单号：{order.id} · {new Date(order.created * 1000).toLocaleString()}</p>
      {order.error && <p>{order.error}</p>}
      {order.checkout_url && <a className="text-link" href={order.checkout_url}>前往 USDT 收款页 →</a>}
      {!admin && !!order.guest && <div><Button variant="outline" onClick={() => void copyReceipt(order)}>复制订单领取链接</Button><p className="small muted">此链接可领取卡密，请私下保存，不要发给他人。{copied === order.id ? '已复制。' : copied.startsWith('复制失败') ? copied : ''}</p></div>}
      {order.code && <div><label className="field">已购买的卡密<input readOnly value={order.code} /></label><a className="text-link" href={cardLink(order.code, location.origin)}>使用卡密开通或兑换 →</a></div>}
      {admin && <p className="small muted">{order.account_id ? `账号编号：${order.account_id}` : '访客订单'} · 支付编号：{order.gateway_id || '待创建'}{order.tx_hash && ` · 交易：${order.tx_hash}`}</p>}
    </article>)}
    {data && !data.items.length && <p>暂无订单。访客请在创建订单的浏览器中查看，或打开保存的订单领取链接。</p>}
    {data && data.pages > 1 && <div className="actions"><Button disabled={page === 1} onClick={() => setPage(p => p - 1)}>上一页</Button><span>{page} / {data.pages}</span><Button disabled={page >= data.pages} onClick={() => setPage(p => p + 1)}>下一页</Button></div>}
  </section>;
}
