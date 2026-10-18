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
import { CycleFields, ruleLabel, FOREVER, type CycleRule } from './cycles';
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
    <Field label="发给谁 / 备注（可选，仅管理员可见）">
      <Input name="note" maxLength={100} placeholder="例如：张三 微信；之后可逐张修改" />
    </Field>
  );
}
async function issue(body: Record<string, unknown>) {
  const r = await api<{ codes: { id: string; code: string; suffix: string }[] }>('admin/cards', body);
  const note = typeof body.note === 'string' ? body.note.trim() : '';
  return r.codes.map((c) => ({ ...c, note }));
}

function PlanIssuer({ plans, onIssued }: { plans: Plan[]; onIssued: (cards: Issued[]) => void }) {
  const [selected, setSelected] = useState(plans[0]?.id || '');
  const [busy, setBusy] = useState(false);
  const p = plans.find((p) => p.id === selected);
  return (
    <section className="plan-issuer">
      <h2>按套餐发卡</h2>
      <p className="small muted">使用已保存的套餐规则，不会修改现有卡密。</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          setBusy(true);
          void issue({
            plan_id: selected,
            count: Number(f.get('count')),
            valid_days: Number(f.get('valid_days')),
            note: f.get('note'),
          })
            .then(onIssued)
            .catch((e) => notify(e.message, 'error'))
            .finally(() => setBusy(false));
        }}
      >
        <div className="form-grid">
          <div className="field">
            <span id="issue-plan">套餐</span>
            <Select value={selected} onValueChange={(v) => setSelected(String(v))}>
              <SelectTrigger aria-labelledby="issue-plan">
                <SelectValue>{p ? p.name : '请选择套餐'}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {plans.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.name} · {p.quota_gib} GiB · {ruleLabel(p)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Field label="生成数量">
            <Input name="count" required type="number" min={1} max={100} defaultValue={1} />
          </Field>
          <Field label="兑换期限（天，0 为不限）">
            <Input name="valid_days" required type="number" min={0} max={365000} defaultValue={90} />
          </Field>
          <NoteField />
        </div>
        <Button type="submit" disabled={busy || !p}>
          {busy ? '正在生成…' : '生成卡密'}
          <Ticket />
        </Button>
      </form>
    </section>
  );
}

function CustomIssuer({
  packageBilling,
  onIssued,
}: {
  packageBilling: boolean;
  onIssued: (cards: Issued[]) => void;
}) {
  const [kind, setKind] = useState('base');
  const [cycle, setCycle] = useState<CycleRule>({ permanent: 0, reset_period: 'never', reset_interval: 30 });
  const [busy, setBusy] = useState(false);
  return (
    <details className="surface custom-issue">
      <summary>自定义额度发卡</summary>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          setBusy(true);
          void issue({
            label: f.get('label'),
            kind,
            quota_gib: Number(f.get('quota_gib')),
            days: Number(f.get('days') || 1),
            count: Number(f.get('count')),
            valid_days: Number(f.get('valid_days')),
            permanent: kind === 'base' && f.get('permanent') === '1',
            reset_period: kind === 'base' ? f.get('reset_period') || 'never' : 'never',
            reset_interval: Number(f.get('reset_interval') || 30),
            note: f.get('note'),
          })
            .then(onIssued)
            .catch((e) => notify(e.message, 'error'))
            .finally(() => setBusy(false));
        }}
      >
        <div className="form-grid">
          {packageBilling && (
            <Field label="卡密类型">
              <Select value={kind} onValueChange={(v) => setKind(v || 'base')}>
                <SelectTrigger>
                  <SelectValue>{kind === 'addon' ? '加流量卡（不增加天数）' : '独立套餐卡'}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="base">独立套餐卡</SelectItem>
                  <SelectItem value="addon">加流量卡（不增加天数）</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          )}
          <Field label="卡名称（用户可见）">
            <Input name="label" defaultValue="标准月卡" required maxLength={60} />
          </Field>
          <Field label="流量额度（GiB）">
            <Input type="number" name="quota_gib" defaultValue={100} required min={1} max={8388607} />
          </Field>
          {kind === 'base' && <CycleFields value={cycle} onChange={setCycle} />}
          {kind === 'base' && !cycle.permanent && (
            <Field label="套餐天数">
              <Input type="number" name="days" defaultValue={30} required min={1} max={365000} />
            </Field>
          )}
          <Field label="生成数量">
            <Input type="number" name="count" defaultValue={1} required min={1} max={100} />
          </Field>
          <Field label="兑换期限（天，0 为不限）">
            <Input type="number" name="valid_days" defaultValue={90} required min={0} max={365000} />
          </Field>
          <NoteField />
        </div>
        <Button type="submit" disabled={busy}>
          {busy ? '处理中…' : '生成卡密'}
          <Ticket />
        </Button>
      </form>
    </details>
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
        <p className="small muted">
          完整卡密只显示一次。建议逐张填写「发给谁」，之后在「卡密查询」里就能看到每张卡发给了谁、被哪个账号兑换。
        </p>
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
  const [query, setQuery] = useState('');
  const [applied, setApplied] = useState('');
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
            placeholder="卡密 / 尾号 / 兑换账号 / 备注"
            autoComplete="off"
            spellCheck={false}
            value={query}
            maxLength={100}
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
            <p className="empty muted">没有符合条件的卡密。可以换个关键词或切换状态。</p>
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
          <p className="muted">生成卡密后私下发给用户，不接入在线支付。</p>
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
            {plans.length ? (
              <PlanIssuer plans={plans} onIssued={received} />
            ) : (
              <p className="message">还没有上架套餐。可在「公告与套餐」中添加，或使用下方自定义发卡。</p>
            )}
            <CustomIssuer packageBilling={packageBilling} onIssued={received} />
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
