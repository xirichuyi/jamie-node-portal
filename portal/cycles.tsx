import { Input } from '@/components/ui/input';
export { FOREVER, expiryLabel, ruleLabel, type CycleRule } from './cycle-labels';
import type { CycleRule } from './cycle-labels';

/** Panel-style package terms: fractional GiB, 0 days = no expiry, optional reset. */
export type Terms = CycleRule & { quota_gib: number; days: number };
export const defaultTerms: Terms = {
  quota_gib: 100,
  days: 30,
  permanent: 0,
  reset_period: 'never',
  reset_interval: 30,
};
/** Request fields for admin/cards, admin/grant and admin/plan. */
export const termsBody = (t: Terms) => ({
  quota_gib: t.quota_gib,
  days: t.permanent ? 0 : t.days,
  permanent: !!t.permanent || !t.days,
  reset_period: t.reset_period || 'never',
  reset_interval: t.reset_interval || 30,
});
const quotaChips = [10, 50, 100, 300, 1000];
const dayChips: [number, string][] = [[7, '7 天'], [30, '30 天'], [90, '90 天'], [365, '1 年'], [0, '永久']];

function Chips<T>({ items, value, onPick }: { items: [T, string][]; value: T; onPick: (v: T) => void }) {
  return (
    <span className="term-chips">
      {items.map(([v, text]) => (
        <button key={text} type="button" aria-pressed={v === value} onClick={() => onPick(v)}>
          {text}
        </button>
      ))}
    </span>
  );
}

export function TermsFields({
  value,
  onChange,
  quotaOnly = false,
}: {
  value: Terms;
  onChange: (patch: Partial<Terms>) => void;
  quotaOnly?: boolean;
}) {
  const days = value.permanent ? 0 : value.days;
  const setDays = (d: number) => onChange({ days: d, permanent: d ? 0 : 1 });
  return (
    <>
      <label className="field">
        <span>流量（GiB）</span>
        <Input
          name="quota_gib"
          type="number"
          required
          min={0.01}
          step="any"
          max={8388607}
          value={value.quota_gib}
          onChange={(e) => onChange({ quota_gib: Number(e.target.value) })}
        />
        <Chips items={quotaChips.map((q) => [q, q + ' G'])} value={value.quota_gib} onPick={(q) => onChange({ quota_gib: q })} />
      </label>
      {!quotaOnly && (
        <>
          <label className="field">
            <span>有效期（天，0 = 永久）</span>
            <Input
              name="days"
              type="number"
              required
              min={0}
              max={365000}
              value={days}
              onChange={(e) => setDays(Math.max(0, Math.trunc(Number(e.target.value))))}
            />
            <Chips items={dayChips} value={days} onPick={setDays} />
          </label>
          <label className="field">
            <span>流量重置</span>
            <select
              name="reset_period"
              value={value.reset_period || 'never'}
              onChange={(e) => onChange({ reset_period: e.target.value })}
            >
              <option value="never">不重置（用完为止）</option>
              <option value="monthly">每月（按开通日）</option>
              <option value="interval">每 N 天</option>
            </select>
          </label>
          {value.reset_period === 'interval' && (
            <label className="field">
              <span>重置间隔（天）</span>
              <Input
                name="reset_interval"
                type="number"
                min={1}
                max={365000}
                required
                value={value.reset_interval || 30}
                onChange={(e) => onChange({ reset_interval: Number(e.target.value) })}
              />
            </label>
          )}
        </>
      )}
    </>
  );
}
