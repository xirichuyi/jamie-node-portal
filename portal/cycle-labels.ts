// Pure labels shared by user pages; CycleFields (admin only) stays in cycles.tsx
// so the user bundle does not pull in the popup select.
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
