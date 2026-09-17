import { useEffect, useState } from 'react';

export function remainingTime(expires: number, now = Date.now() / 1000) {
  if (expires >= 253402185600) return '永久有效';
  const seconds = expires - now;
  if (!expires) return '尚未开通';
  if (seconds <= 0) return '已到期';
  if (seconds < 60) return '不足 1 分钟';
  if (seconds < 3600) return `${Math.ceil(seconds / 60)} 分钟`;
  if (seconds < 86400) return `${Math.ceil(seconds / 3600)} 小时`;
  return `${Math.ceil(seconds / 86400)} 天`;
}

export function useNow() {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const update = () => setNow(Date.now() / 1000);
    const timer = window.setInterval(update, 30000);
    window.addEventListener('focus', update);
    return () => {
      clearInterval(timer);
      window.removeEventListener('focus', update);
    };
  }, []);
  return now;
}

// Only non-sensitive, device-local tutorial preferences belong in browser storage.
export function readGuide() {
  try {
    const value = JSON.parse(sessionStorage.getItem('jamie-guide') || 'null');
    if (
      value &&
      ['windows', 'mac', 'ios', 'android', 'linux'].includes(value.device) &&
      Number.isInteger(value.step) &&
      value.step >= 0 &&
      value.step <= 2
    )
      return value as { device: string; step: number };
  } catch {}
  return null;
}

export function priceText(label: string) {
  const value = label.trim();
  return !value || /^\d+(?:\.\d+)?$/.test(value) ? '价格请咨询管理员' : value;
}

export function remainingAfter(quota: number, used: number | null | undefined) {
  return used == null ? null : Math.max(0, quota - used);
}
