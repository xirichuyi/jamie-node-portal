import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { ArrowUpRight, Copy, ReceiptText, RefreshCw } from 'lucide-react';
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
  return <div className="purchase-control">
    <Button onClick={() => setConfirm(true)}>购买套餐 <ArrowUpRight size={15} /></Button>
    <Dialog open={confirm} onOpenChange={open => { if (!busy) setConfirm(open); }}>
      <DialogContent className="purchase-dialog" showCloseButton={!busy}>
        <DialogTitle>确认购买</DialogTitle>
        <DialogDescription>{username ? `付款后自动充入 ${username}` : '付款后领取卡密，可开通或续费'}</DialogDescription>
        <div className="purchase-summary"><span>{label}</span><strong>{price / 1000000}<small>USDT</small></strong></div>
        <p className="payment-note">请按收款页的网络和准确金额转账。</p>
        {error && <p className="payment-error" role="alert">{error}</p>}
        <div className="payment-actions"><Button variant="outline" disabled={busy} onClick={() => setConfirm(false)}>取消</Button><Button disabled={busy} onClick={() => void buy()}>{busy ? '创建中…' : '继续支付'}<ArrowUpRight size={15} /></Button></div>
      </DialogContent>
    </Dialog>
  </div>;
}

const labels: Record<string, string> = { creating: '创建中', pending: '待付款', confirming: '确认中', paid: '到账中', fulfilled: '已完成', expired: '已过期', review: '待核对' };
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
  return <section className="payment-page">
    <header className="page-heading"><div><h1>{admin ? '支付订单' : '我的订单'}</h1><p className="payment-note">{admin ? '查看付款与到账状态' : '付款确认后自动更新'}</p></div><Button variant="outline" onClick={() => setRefresh(n => n + 1)}><RefreshCw size={15} />刷新</Button></header>
    {error && <p role="alert">{error}</p>}
    {!data && !error && <output>正在读取订单…</output>}
    {data && !data.enabled && <p>在线支付尚未开放，已有订单记录仍可查看。</p>}
    {data?.guestError && <p role="alert">部分访客订单暂时无法读取，领取凭证仍已保留，请稍后刷新；不要重复付款。</p>}
    <div className="payment-list">{data?.items.map(order => <article className="payment-card" key={order.id}>
      <div className="payment-card-heading"><h2>{order.label}</h2><span className={`payment-status payment-status-${order.status}`}>{labels[order.status] || order.status}</span></div>
      <div className="payment-card-summary"><strong>{order.amount}<small>USDT</small></strong><time dateTime={new Date(order.created * 1000).toISOString()}>{new Date(order.created * 1000).toLocaleString()}</time></div>
      {order.error && <p className="payment-error">{order.error}</p>}
      {order.status === 'expired' && <p className="payment-note">订单已过期，请勿转账。</p>}
      {(order.checkout_url || (!admin && !!order.guest)) && <div className="payment-actions">
        {!admin && !!order.guest && <Button variant="outline" onClick={() => void copyReceipt(order)}><Copy size={14} />{copied === order.id ? '已保存链接' : '复制领取链接'}</Button>}
        {order.checkout_url && <a className="payment-checkout" href={order.checkout_url}>去付款<ArrowUpRight size={15} /></a>}
      </div>}
      {!admin && !!order.guest && <p className="payment-note" role="status">{copied.startsWith('复制失败') ? copied : '付款前请保存领取链接，仅限本人使用。'}</p>}
      {order.code && <div className="payment-code"><label className="field">卡密<input readOnly value={order.code} /></label><a className="text-link" href={cardLink(order.code, location.origin)}>立即兑换 →</a></div>}
      <details className="payment-details"><summary>订单详情</summary><dl><dt>订单号</dt><dd>{order.id}</dd>{order.network && <><dt>支付网络</dt><dd>{order.network === 'binance' ? 'BSC' : order.network}</dd></>}{admin && <><dt>账号</dt><dd>{order.account_id || '访客'}</dd><dt>支付编号</dt><dd>{order.gateway_id || '待创建'}</dd>{order.tx_hash && <><dt>交易</dt><dd>{order.tx_hash}</dd></>}</>}</dl><p className="payment-note">已付款未到账？请提供订单号联系管理员。</p></details>
    </article>)}</div>
    {data && !data.items.length && <div className="payment-empty"><ReceiptText size={30} strokeWidth={1.3} /><h2>暂无订单</h2><p>{signedIn || admin ? '购买套餐后，订单会显示在这里。' : '请在购买时的浏览器查看，或打开领取链接。'}</p>{!admin && <a className="text-link" href="#/plans">查看套餐 →</a>}</div>}
    {data && data.pages > 1 && <div className="actions"><Button disabled={page === 1} onClick={() => setPage(p => p - 1)}>上一页</Button><span>{page} / {data.pages}</span><Button disabled={page >= data.pages} onClick={() => setPage(p => p + 1)}>下一页</Button></div>}
  </section>;
}
