import { useState } from 'react';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from '@/components/ui/select';
export type CycleRule = {
  permanent?: number | boolean;
  reset_period?: string;
  reset_interval?: number;
  days?: number;
};
export const FOREVER = 253402185600;
export const expiryLabel = (n: number) =>
  n >= FOREVER
    ? '永久有效'
    : n
      ? new Date(n * 1000).toLocaleDateString('zh-CN')
      : '—';
export function ruleLabel(rule: CycleRule) {
  const duration = rule.permanent ? '永久有效' : `${rule.days} 天`;
  const reset =
    rule.reset_period === 'monthly'
      ? '按开通日每月重置'
      : rule.reset_period === 'interval'
        ? `每 ${rule.reset_interval || 30} 天重置`
        : '不重置';
  return `${duration} · ${reset}`;
}
export function CycleFields({
  value,
  onChange,
}: {
  value?: CycleRule;
  onChange?: (rule: CycleRule) => void;
}) {
  const [local, setLocal] = useState<CycleRule>({
    permanent: 0,
    reset_period: 'never',
    reset_interval: 30,
  });
  const rule = value || local;
  const change = (patch: CycleRule) => {
    const next = { ...rule, ...patch };
    setLocal(next);
    onChange?.(next);
  };
  return (
    <>
      <label className="field">
        <span>订阅期限</span>
        <Select
          name="permanent"
          value={rule.permanent ? '1' : '0'}
          onValueChange={(v) => change({ permanent: v === '1' ? 1 : 0 })}
        >
          <SelectTrigger>
            <SelectValue>
              {rule.permanent ? '永久有效' : '指定天数'}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="0">指定天数</SelectItem>
            <SelectItem value="1">永久有效</SelectItem>
          </SelectContent>
        </Select>
      </label>
      <label className="field">
        <span>流量重置</span>
        <Select
          name="reset_period"
          value={rule.reset_period || 'never'}
          onValueChange={(v) => change({ reset_period: v || 'never' })}
        >
          <SelectTrigger>
            <SelectValue>
              {
                {
                  never: '不重置（总流量包）',
                  monthly: '按开通日每月重置',
                  interval: '每隔指定天数',
                }[rule.reset_period || 'never']
              }
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="never">不重置（总流量包）</SelectItem>
            <SelectItem value="monthly">按开通日每月重置</SelectItem>
            <SelectItem value="interval">每隔指定天数</SelectItem>
          </SelectContent>
        </Select>
      </label>
      {rule.reset_period === 'interval' && (
        <label className="field">
          <span>重置间隔（天）</span>
          <Input
            name="reset_interval"
            type="number"
            min={1}
            max={365000}
            required
            value={rule.reset_interval || 30}
            onChange={(e) => change({ reset_interval: Number(e.target.value) })}
          />
        </label>
      )}
    </>
  );
}
