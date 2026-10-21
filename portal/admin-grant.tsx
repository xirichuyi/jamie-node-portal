import { useEffect, useState } from 'react';
import { Gift } from 'lucide-react';
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
import { TermsFields, termsBody, defaultTerms, expiryLabel, ruleLabel, type Terms } from './cycles';
import type { Plan } from './content';
import type { PackageBalance } from './features';
import { notify } from './toast';

type Member = {
  id: string;
  username: string;
  packages?: PackageBalance[];
};
type Mode = 'plan' | 'custom' | 'addon';

export function GrantDialog({
  member,
  plans,
  packageBilling,
  disabled,
  onGranted,
}: {
  member: Member;
  plans: Plan[];
  packageBilling: boolean;
  disabled: boolean;
  onGranted: () => Promise<void>;
}) {
  const targets = (member.packages || []).filter(
    (p) => p.status !== 'expired' && p.status !== 'revoked' && p.kind !== 'addon',
  );
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<Mode>(plans.length ? 'plan' : 'custom');
  const [planId, setPlanId] = useState('');
  const [target, setTarget] = useState('');
  const [label, setLabel] = useState('');
  const [terms, setTerms] = useState<Terms>({ ...defaultTerms, quota_gib: 10 });
  const quota = terms.quota_gib;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!open) return;
    setError('');
    setPlanId(plans[0]?.id || '');
    setTarget(targets[0]?.id || '');
    setLabel(mode === 'addon' ? '后台加流量' : '后台赠送');
  }, [open, mode]);
  const plan = plans.find((p) => p.id === planId);
  const targetPackage = targets.find((p) => p.id === target);
  const summary =
    mode === 'plan'
      ? plan
        ? `${plan.name} · ${plan.quota_gib} GiB · ${ruleLabel(plan)}`
        : '请选择套餐'
      : mode === 'addon'
        ? `${quota} GiB 加到「${targetPackage?.label || '—'}」，不延长有效期`
        : `${label || '—'} · ${quota} GiB · ${ruleLabel(termsBody(terms))}`;
  const submit = async () => {
    setBusy(true);
    setError('');
    try {
      const body =
        mode === 'plan'
          ? { id: member.id, plan_id: planId }
          : mode === 'addon'
            ? { id: member.id, label, kind: 'addon', quota_gib: quota, target }
            : { id: member.id, label, kind: 'base', ...termsBody(terms) };
      await api('admin/grant', body);
      setOpen(false);
      notify(`已为 ${member.username} 发放：${summary}`);
      await onGranted();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const modes: [Mode, string][] = [
    ['plan', '按已上架套餐'],
    ['custom', '自定义套餐'],
    ...(packageBilling && targets.length ? [['addon', '给现有套餐加流量'] as [Mode, string]] : []),
  ];
  return (
    <>
      <Button variant="outline" disabled={disabled} onClick={() => setOpen(true)}>
        <Gift />
        赠送套餐 / 加流量
      </Button>
      <Dialog open={open} onOpenChange={(v) => !busy && setOpen(v)}>
        <DialogContent className="grant-dialog">
          <DialogTitle>为 {member.username} 发放权益</DialogTitle>
          <DialogDescription>立即生效并同步到节点，不需要用户兑换卡密。</DialogDescription>
          <div className="segmented" role="radiogroup" aria-label="发放方式">
            {modes.map(([id, text]) => (
              <button
                key={id}
                role="radio"
                aria-checked={mode === id}
                disabled={id === 'plan' && !plans.length}
                onClick={() => setMode(id)}
              >
                {text}
              </button>
            ))}
          </div>
          {mode === 'plan' && (
            <label className="field">
              <span>套餐</span>
              <Select value={planId} onValueChange={(v) => setPlanId(String(v || ''))}>
                <SelectTrigger>
                  <SelectValue>{plan ? plan.name : '请选择套餐'}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {plans.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.name} · {p.quota_gib} GiB · {ruleLabel(p)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
          )}
          {mode === 'addon' && (
            <label className="field">
              <span>加到哪个套餐</span>
              <Select value={target} onValueChange={(v) => setTarget(String(v || ''))}>
                <SelectTrigger>
                  <SelectValue>
                    {targetPackage ? `${targetPackage.label} · ${expiryLabel(targetPackage.expires)} 到期` : '请选择'}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {targets.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.label} · {expiryLabel(p.expires)} 到期
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
          )}
          {mode !== 'plan' && (
            <div className="form-grid">
              <label className="field">
                <span>名称（用户可见）</span>
                <Input value={label} maxLength={60} onChange={(e) => setLabel(e.target.value)} />
              </label>
              <TermsFields
                value={terms}
                quotaOnly={mode === 'addon' || !packageBilling}
                onChange={(patch) => setTerms({ ...terms, ...patch })}
              />
            </div>
          )}
          <p className="grant-summary">
            <span className="muted">将发放</span>
            <strong>{summary}</strong>
          </p>
          {error && (
            <p className="message error" role="alert">
              {error}
            </p>
          )}
          <div className="actions">
            <Button variant="ghost" disabled={busy} onClick={() => setOpen(false)}>
              取消
            </Button>
            <Button
              disabled={
                busy ||
                (mode === 'plan' && !plan) ||
                (mode === 'addon' && !targetPackage) ||
                (mode !== 'plan' && (!label.trim() || !(quota > 0)))
              }
              onClick={() => void submit()}
            >
              {busy ? '正在发放…' : '确认发放'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

export function UserNote({
  userId,
  note,
  onSaved,
}: {
  userId: string;
  note: { body: string; updated: number; updated_by: string } | null;
  onSaved: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(note?.body || '');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!editing) setValue(note?.body || '');
  }, [note?.body, editing]);
  return (
    <section className="user-detail-section">
      <div className="section-heading compact">
        <h2>管理员备注</h2>
        {!editing && (
          <button className="text-link" onClick={() => setEditing(true)}>
            {note ? '编辑' : '添加备注'}
          </button>
        )}
      </div>
      {editing ? (
        <>
          <textarea
            aria-label="管理员备注"
            rows={3}
            maxLength={2000}
            value={value}
            placeholder="仅管理员可见，例如：付款方式、联系方式、特殊约定"
            onChange={(e) => setValue(e.target.value)}
          />
          <div className="actions">
            <Button variant="ghost" disabled={busy} onClick={() => setEditing(false)}>
              取消
            </Button>
            <Button
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await api('admin/user-note', { id: userId, body: value });
                  setEditing(false);
                  notify(value.trim() ? '备注已保存' : '备注已清除');
                  await onSaved();
                } catch (e) {
                  notify((e as Error).message, 'error');
                } finally {
                  setBusy(false);
                }
              }}
            >
              保存
            </Button>
          </div>
        </>
      ) : note ? (
        <>
          <p className="note-body">{note.body}</p>
          <p className="small muted">
            {note.updated_by || '管理员'} · {new Date(note.updated * 1000).toLocaleString('zh-CN', { hour12: false })}
          </p>
        </>
      ) : (
        <p className="small muted">仅管理员可见，用户看不到。</p>
      )}
    </section>
  );
}
