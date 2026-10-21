import { useEffect, useRef, useState } from 'react';
import { Copy, Download, Link2, Ticket, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { api } from './api';
import { TermsFields, termsBody, defaultTerms, ruleLabel, FOREVER, type Terms } from './cycles';
import { cardLink } from './card-entry';
import type { Plan } from './content';
import { AdminTabs, useAdminTab } from './admin-shell';
import { notify } from './toast';

export type Batch = {
  label: string;
  created: number;
  total: number;
  redeemed: number;
  available: number;
  revoked: number;
  expired: number;
  kind: string;
  quota: number;
  granted: number;
};
type Issued = { id: string; code: string; suffix: string; note: string };
type Card = {
  id: string;
  suffix: string;
  label: string;
  quota: number;
  days: number;
  kind?: string;
  permanent?: number;
  reset_period?: string;
  reset_interval?: number;
  created: number;
  redeemed_at: number | null;
  redeemed_by: string | null;
  account_id: string | null;
  revoked_at: number | null;
  redeem_before: number;
  note: string;
  granted: number;
  issued_by: string;
};
type Cards = { cards: Card[]; total: number; page: number; pages: number };
type BatchKey = { label: string; created: number };

const when = (n: number) => new Date(n * 1000).toLocaleString('zh-CN', { hour12: false });
const day = (n: number) =>
  n >= FOREVER ? '不限期' : new Date(n * 1000).toLocaleDateString('zh-CN');
const gib = (n: number) => (n / 1024 ** 3).toLocaleString('zh-CN', { maximumFractionDigits: 2 });
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}
function NoteField() {
  return (
    <Field label="备注（仅管理员可见）">
      <Input name="note" maxLength={100} placeholder="发给谁，可选" />
    </Field>
  );
}
async function issue(body: Record<string, unknown>) {
  const r = await api<{ codes: { id: string; code: string; suffix: string }[] }>('admin/cards', body);
  const note = typeof body.note === 'string' ? body.note.trim() : '';
  return r.codes.map((c) => ({ ...c, note }));
}

/** One panel-style form; a saved plan only pre-fills it and every field stays editable. */
function Issuer({
  plans,
  packageBilling,
  onIssued,
}: {
  plans: Plan[];
  packageBilling: boolean;
  onIssued: (cards: Issued[]) => void;
}) {
  const first = plans[0];
  const fromPlan = (p: Plan): Terms => ({
    quota_gib: p.quota_gib,
    days: p.days,
    permanent: p.permanent,
    reset_period: p.reset_period,
    reset_interval: p.reset_interval,
  });
  const [kind, setKind] = useState('base');
  const [label, setLabel] = useState(first?.name || '标准月卡');
  const [terms, setTerms] = useState<Terms>(first ? fromPlan(first) : defaultTerms);
  const [count, setCount] = useState(1);
  const [validDays, setValidDays] = useState(0);
  const [busy, setBusy] = useState(false);
  const addon = kind === 'addon';
  return (
    <section className="plan-issuer">
      <h2>发卡</h2>
      <div className="term-presets" aria-label="快速填入">
          <span className="small muted">快速填入</span>
          {plans.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => {
                setKind('base');
                setLabel(p.name);
                setTerms(fromPlan(p));
              }}
            >
              {p.name}
            </button>
          ))}
          <button
            type="button"
            onClick={() => {
              setKind('base');
              setLabel('不限时流量包');
              setTerms({ ...terms, days: 0, permanent: 1, reset_period: 'never' });
            }}
          >
            不限时流量包
          </button>
        </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          setBusy(true);
          void issue({
            label,
            kind,
            ...termsBody(terms),
            count,
            valid_days: validDays,
            note: f.get('note'),
          })
            .then(onIssued)
            .catch((e) => notify(e.message, 'error'))
            .finally(() => setBusy(false));
        }}
      >
        <div className="form-grid">
          {packageBilling && (
            <Field label="类型">
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="base">套餐卡</option>
                <option value="addon">加流量卡（跟随现有套餐到期）</option>
              </select>
            </Field>
          )}
          <Field label="名称（用户可见）">
            <Input value={label} onChange={(e) => setLabel(e.target.value)} required maxLength={60} />
          </Field>
          <TermsFields value={terms} quotaOnly={addon} onChange={(patch) => setTerms({ ...terms, ...patch })} />
          <Field label="数量">
            <Input type="number" value={count} onChange={(e) => setCount(Number(e.target.value))} required min={1} max={1000} />
          </Field>
          <Field label="兑换期限（天，0 = 不限）">
            <Input type="number" value={validDays} onChange={(e) => setValidDays(Number(e.target.value))} required min={0} max={365000} />
          </Field>
          <NoteField />
        </div>
        <p className="grant-summary">
          <strong>
            {count} 张 · {label || '—'} · {terms.quota_gib} GiB · {addon ? '跟随现有套餐到期' : ruleLabel(termsBody(terms))}
          </strong>
        </p>
        <Button type="submit" disabled={busy}>
          {busy ? '正在生成…' : '生成卡密'}
          <Ticket />
        </Button>
      </form>
    </section>
  );
}

async function saveNote(id: string, note: string) {
  await api('admin/card-note', { id, note });
}
async function copyText(text: string, done: string) {
  try {
    await navigator.clipboard.writeText(text);
    notify(done);
  } catch {
    notify('复制失败，请手动选择文本复制', 'error');
  }
}

/** One editable memo cell; saves on blur or Enter and only when it changed. */
function NoteInput({
  id,
  value,
  onSaved,
  placeholder = '发给谁？',
}: {
  id: string;
  value: string;
  onSaved: (note: string) => void;
  placeholder?: string;
}) {
  const [text, setText] = useState(value);
  const saved = useRef(value);
  useEffect(() => {
    saved.current = value;
    setText(value);
  }, [value]);
  const commit = async () => {
    const next = text.trim();
    if (next === saved.current) return;
    try {
      await saveNote(id, next);
      saved.current = next;
      onSaved(next);
      notify('备注已保存');
    } catch (e) {
      notify((e as Error).message, 'error');
      setText(saved.current);
    }
  };
  return (
    <input
      className="note-input"
      aria-label="卡密备注"
      value={text}
      maxLength={100}
      placeholder={placeholder}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => void commit()}
      onKeyDown={(e) => {
        if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
        if (e.key === 'Escape') setText(saved.current);
      }}
    />
  );
}

function IssuedCodes({
  cards,
  onChange,
  onClear,
}: {
  cards: Issued[];
  onChange: (cards: Issued[]) => void;
  onClear: () => void;
}) {
  if (!cards.length)
    return (
      <aside className="issued issued-empty">
        <Ticket size={22} aria-hidden="true" />
        <p>生成后，卡密会显示在这里。</p>
        <p className="small muted">完整卡密只显示一次。</p>
      </aside>
    );
  const link = (c: Issued) => cardLink(c.code, location.origin);
  return (
    <aside className="issued">
      <div className="issued-head">
        <strong>新卡密 · {cards.length} 张</strong>
        <span className="small muted">离开页面后无法再次查看完整卡密</span>
      </div>
      <ul className="issued-list">
        {cards.map((c, i) => (
          <li key={c.id}>
            <code>{c.code}</code>
            <NoteInput
              id={c.id}
              value={c.note}
              onSaved={(note) => onChange(cards.map((x, j) => (j === i ? { ...x, note } : x)))}
            />
            <div className="issued-row-actions">
              <button onClick={() => void copyText(link(c), `尾号 ${c.suffix} 的兑换链接已复制`)}>复制链接</button>
              <button onClick={() => void copyText(c.code, `尾号 ${c.suffix} 已复制`)}>复制卡密</button>
            </div>
          </li>
        ))}
      </ul>
      <div className="actions">
        <Button
          variant="outline"
          onClick={() => void copyText(cards.map(link).join('\n'), '全部兑换链接已复制')}
        >
          <Link2 />
          复制全部链接
        </Button>
        <Button variant="outline" onClick={() => void copyText(cards.map((c) => c.code).join('\n'), '全部卡密已复制')}>
          <Copy />
          复制全部卡密
        </Button>
        <Button
          variant="outline"
          onClick={() => {
            const text = cards.map((c) => [c.code, link(c), c.note].filter(Boolean).join('\t')).join('\n');
            const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
            const a = document.createElement('a');
            a.href = url;
            a.download = 'Jamie-Node-cards.txt';
            a.click();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
          }}
        >
          <Download />
          下载
        </Button>
        <Button variant="ghost" onClick={onClear}>
          已保存，清除
        </Button>
      </div>
    </aside>
  );
}

function cardStatus(c: Card) {
  if (c.redeemed_at) return { key: 'redeemed', text: c.granted ? '后台赠送' : '已兑换' };
  if (c.revoked_at) return { key: 'revoked', text: '已作废' };
  if (c.redeem_before * 1000 < Date.now()) return { key: 'expired', text: '已过期' };
  return { key: 'available', text: '未使用' };
}

export function CardLedger({
  batch,
  onClearBatch,
}: {
  batch: BatchKey | null;
  onClearBatch: () => void;
}) {
  const initialQuery = () =>
    typeof location === 'undefined' ? '' : new URLSearchParams(location.hash.split('?')[1] || '').get('q') || '';
  const [query, setQuery] = useState(initialQuery);
  const [applied, setApplied] = useState(initialQuery);
  useEffect(() => {
    const sync = () => {
      const q = initialQuery();
      if (q) {
        setQuery(q);
        setApplied(q);
        setScope('all');
        setPage(1);
      }
    };
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, []);
  // Search as the admin types; the button stays for keyboard users.
  useEffect(() => {
    const timer = setTimeout(() => {
      if (query.trim() !== applied) {
        setApplied(query.trim());
        setPage(1);
      }
    }, 350);
    return () => clearTimeout(timer);
  }, [query]);
  const [scope, setScope] = useState('all');
  const [page, setPage] = useState(1);
  const [version, setVersion] = useState(0);
  const [data, setData] = useState<Cards | null>(null);
  const [error, setError] = useState('');
  const [revoking, setRevoking] = useState<Card | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    api<Cards>('admin/card-search', { query: applied, scope, page, ...(batch ? { batch } : {}) })
      .then((r) => active && (setData(r), setError('')))
      .catch((e) => active && setError(e.message));
    return () => {
      active = false;
    };
  }, [applied, scope, page, batch, version]);
  const scopes: [string, string][] = [
    ['all', '全部'],
    ['available', '未使用'],
    ['redeemed', '已兑换'],
    ['expired', '已过期'],
    ['revoked', '已作废'],
  ];
  return (
    <section className="section">
      {batch && (
        <p className="batch-filter">
          正在查看批次：<strong>{batch.label}</strong> · {when(batch.created)}
          <button aria-label="清除批次筛选" onClick={onClearBatch}>
            <X size={14} />
            查看全部
          </button>
        </p>
      )}
      <div className="log-toolbar">
        <div className="member-filters">
          {scopes.map(([id, label]) => (
            <button
              key={id}
              aria-pressed={scope === id}
              onClick={() => {
                setScope(id);
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
            setApplied(query.trim());
            setPage(1);
          }}
        >
          <Input
            aria-label="搜索卡密"
            placeholder="卡密 / 尾号 / 兑换链接 / 账号 / 备注 / 卡名"
            autoComplete="off"
            spellCheck={false}
            value={query}
            maxLength={300}
            onChange={(e) => setQuery(e.target.value)}
          />
          <Button variant="outline">搜索</Button>
        </form>
      </div>
      {error && <p className="message error">{error}</p>}
      {!data && !error && <p role="status">正在读取卡密…</p>}
      {data && (
        <>
          <p className="small muted">
            共 {data.total} 张。备注栏可直接编辑，回车或点击别处保存；点击兑换账号查看用户详情。
          </p>
          <div className="admin-table-wrap">
            <table className="admin-table card-ledger">
              <thead>
                <tr>
                  <th>尾号 / 套餐</th>
                  <th>发给谁 / 备注</th>
                  <th>状态</th>
                  <th>兑换账号</th>
                  <th>时间</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.cards.map((c) => {
                  const status = cardStatus(c);
                  return (
                    <tr key={c.id}>
                      <td>
                        <code className="suffix">{c.suffix}</code>
                        <small className="block muted">
                          {c.label} · {gib(c.quota)} GiB · {c.kind === 'addon' ? '加流量' : ruleLabel(c)}
                        </small>
                      </td>
                      <td data-label="发给" className="note-cell">
                        <NoteInput
                          id={c.id}
                          value={c.note}
                          placeholder="未填写"
                          onSaved={(note) =>
                            setData((d) =>
                              d && { ...d, cards: d.cards.map((x) => (x.id === c.id ? { ...x, note } : x)) },
                            )
                          }
                        />
                      </td>
                      <td data-label="状态">
                        <span className={'card-state state-' + status.key}>{status.text}</span>
                      </td>
                      <td data-label="兑换账号">
                        {c.redeemed_at ? (
                          c.account_id ? (
                            <a className="text-link strong-link" href={'#/admin_users?user=' + encodeURIComponent(c.account_id)}>
                              {c.redeemed_by} →
                            </a>
                          ) : (
                            <span className="muted">账号已删除</span>
                          )
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td data-label="时间" className="nowrap">
                        {c.redeemed_at ? (
                          <>
                            兑换 {when(c.redeemed_at)}
                            <small className="block muted">发卡 {day(c.created)}</small>
                          </>
                        ) : (
                          <>
                            发卡 {day(c.created)}
                            <small className="block muted">
                              {c.revoked_at ? `作废 ${day(c.revoked_at)}` : `兑换截止 ${day(c.redeem_before)}`}
                            </small>
                          </>
                        )}
                      </td>
                      <td className="cell-actions">
                        {status.key === 'available' && (
                          <Button variant="ghost" onClick={() => setRevoking(c)}>
                            作废
                          </Button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {!data.cards.length && (
            <div className="empty search-help">
              <p>没有找到符合条件的卡密。</p>
              {scope !== 'all' && (
                <p className="small muted">
                  当前只在「{scopes.find(([id]) => id === scope)?.[1]}」中搜索。
                  <button className="text-link" onClick={() => { setScope('all'); setPage(1); }}>
                    在全部状态中搜索 →
                  </button>
                </p>
              )}
              {batch && (
                <p className="small muted">
                  当前只在所选批次中搜索。
                  <button className="text-link" onClick={onClearBatch}>在全部卡密中搜索 →</button>
                </p>
              )}
              {scope === 'all' && !batch && /^[0-9a-fA-F-]{8,}$/.test(applied) && applied.replace(/-/g, '').length < 32 && (
                <p className="small muted">
                  出于安全，系统只保存卡密的最后 8 位：请输入完整卡密，或卡密末尾的 4–8 位，卡密开头或中间的部分无法搜索。
                </p>
              )}
            </div>
          )}
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
      <Dialog open={!!revoking} onOpenChange={(open) => !open && !busy && setRevoking(null)}>
        <DialogContent>
          <DialogTitle>作废尾号 {revoking?.suffix}？</DialogTitle>
          <DialogDescription>
            {revoking?.note ? `备注：${revoking.note}。` : ''}作废后不能再兑换，已开通的订阅不受影响。
          </DialogDescription>
          <div className="actions">
            <Button variant="ghost" disabled={busy} onClick={() => setRevoking(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              disabled={busy}
              onClick={() => {
                if (!revoking) return;
                setBusy(true);
                void api('admin/revoke', { id: revoking.id })
                  .then(() => {
                    notify(`尾号 ${revoking.suffix} 已作废`);
                    setRevoking(null);
                    setVersion((v) => v + 1);
                  })
                  .catch((e) => notify(e.message, 'error'))
                  .finally(() => setBusy(false));
              }}
            >
              确认作废
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}

function Batches({ reloadKey, onOpen }: { reloadKey: number; onOpen: (batch: BatchKey) => void }) {
  const [data, setData] = useState<Batch[] | null>(null);
  const [error, setError] = useState('');
  const [confirm, setConfirm] = useState<Batch | null>(null);
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let active = true;
    api<{ batches: Batch[] }>('admin/batches')
      .then((r) => active && (setData(r.batches), setError('')))
      .catch((e) => active && setError(e.message));
    return () => {
      active = false;
    };
  }, [reloadKey, version]);
  return (
    <section className="section">
      <p className="small muted">每次发卡为一个批次（最近 100 批）。点击批次查看每张卡发给了谁、被谁兑换。</p>
      {error && <p className="message error">{error}</p>}
      {!data && !error && <p role="status">正在读取批次…</p>}
      {data && !data.length && <p className="empty">还没有发卡记录。</p>}
      {!!data?.length && (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>批次</th>
                <th>总数</th>
                <th>可用</th>
                <th>已兑换</th>
                <th>已作废</th>
                <th>已过期</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.map((b) => (
                <tr key={b.created + b.label} className="clickable" onClick={() => onOpen(b)}>
                  <td>
                    <button className="text-link strong-link" onClick={(e) => { e.stopPropagation(); onOpen(b); }}>
                      {b.label}
                    </button>
                    {b.granted === b.total && <span className="tag">后台赠送</span>}
                    <small className="block muted">
                      {when(b.created)} · {gib(b.quota)} GiB{b.kind === 'addon' ? ' · 加流量' : ''}
                    </small>
                  </td>
                  <td data-label="总数">{b.total}</td>
                  <td data-label="可用">{b.available}</td>
                  <td data-label="已兑换">{b.redeemed}</td>
                  <td data-label="已作废">{b.revoked}</td>
                  <td data-label="已过期">{b.expired}</td>
                  <td className="cell-actions">
                    {b.available > 0 && (
                      <Button
                        variant="ghost"
                        onClick={(e) => {
                          e.stopPropagation();
                          setConfirm(b);
                        }}
                      >
                        作废未用
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Dialog open={!!confirm} onOpenChange={(open) => !open && !busy && setConfirm(null)}>
        <DialogContent>
          <DialogTitle>作废「{confirm?.label}」批次中 {confirm?.available} 张未使用卡密？</DialogTitle>
          <DialogDescription>
            只作废尚未兑换且未过期的卡密，已兑换的订阅不受影响。此操作不可撤销。
          </DialogDescription>
          <div className="actions">
            <Button variant="ghost" disabled={busy} onClick={() => setConfirm(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              disabled={busy}
              onClick={() => {
                if (!confirm) return;
                setBusy(true);
                void api<{ revoked: number }>('admin/revoke-batch', {
                  label: confirm.label,
                  created: confirm.created,
                })
                  .then((r) => {
                    notify(`已作废 ${r.revoked} 张卡密`);
                    setConfirm(null);
                    setVersion((v) => v + 1);
                  })
                  .catch((e) => notify(e.message, 'error'))
                  .finally(() => setBusy(false));
              }}
            >
              {busy ? '正在作废…' : '确认作废'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}

export function CardsWorkspace({
  plans,
  packageBilling,
}: {
  plans: Plan[];
  packageBilling: boolean;
}) {
  const [tab, setTab] = useAdminTab('issue');
  const [cards, setCards] = useState<Issued[]>([]);
  const [issued, setIssued] = useState(0);
  const [batch, setBatch] = useState<BatchKey | null>(null);
  const received = (values: Issued[]) => {
    setCards(values);
    setIssued((n) => n + 1);
    notify(`已生成 ${values.length} 张卡密，请及时保存`);
  };
  return (
    <>
      <header className="page-heading">
        <div>
          <h1>卡密</h1>
          
        </div>
      </header>
      <AdminTabs
        value={tab}
        onChange={(next) => {
          if (next !== 'records') setBatch(null);
          setTab(next);
        }}
        tabs={[
          ['issue', '发卡'],
          ['records', '卡密查询'],
          ['batches', '发卡批次'],
        ]}
      />
      {tab === 'issue' && (
        <div className="issue-layout">
          <div>
            <Issuer plans={plans} packageBilling={packageBilling} onIssued={received} />
          </div>
          <IssuedCodes cards={cards} onChange={setCards} onClear={() => setCards([])} />
        </div>
      )}
      {tab === 'records' && <CardLedger batch={batch} onClearBatch={() => setBatch(null)} />}
      {tab === 'batches' && (
        <Batches
          reloadKey={issued}
          onOpen={(b) => {
            setBatch({ label: b.label, created: b.created });
            setTab('records');
          }}
        />
      )}
    </>
  );
}
