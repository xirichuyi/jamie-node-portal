import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';

let pendingCode = '';
export function parseCard(value: string): string {
  let code = value.trim();
  if (/^https?:\/\//i.test(code)) {
    const url = new URL(code);
    if (typeof location !== 'undefined' && url.origin !== location.origin) throw new Error('请使用本站的兑换链接');
    if (!url.hash.startsWith('#/redeem?')) throw new Error('这不是兑换链接');
    code = new URLSearchParams(url.hash.split('?')[1]).get('code') || '';
  }
  if (!/^[a-fA-F0-9]{32}$/.test(code.replace(/[- ]/g, ''))) throw new Error('未识别到卡密，请手动粘贴');
  return code;
}
export function captureCardLink() {
  if (typeof location === 'undefined' || !location.hash.startsWith('#/redeem?')) return;
  try { pendingCode = parseCard(location.href); } catch { pendingCode = ''; }
  // Keep bearer credentials out of subsequent history entries and requests.
  window.history.replaceState(window.history.state, '', location.pathname + location.search + '#/redeem');
  window.dispatchEvent(new Event('jamie-card-link'));
}
export const pendingCard = () => pendingCode;
export const clearPendingCard = () => { pendingCode = ''; };
export const cardLink = (code: string, origin: string) => origin + '/#/redeem?code=' + encodeURIComponent(code);

export function useCardCode(onLink: () => void) {
  const [code, setCode] = useState(pendingCard);
  useEffect(() => {
    const receive = () => {
      setCode(pendingCard()); onLink();
    };
    window.addEventListener('jamie-card-link', receive);
    return () => window.removeEventListener('jamie-card-link', receive);
  }, [onLink]);
  return [code, setCode] as const;
}

export function PasteCard({ onCode, disabled }: { onCode: (code: string) => void; disabled?: boolean }) {
  const [message, setMessage] = useState('');
  return <>
    <Button type="button" variant="outline" disabled={disabled} onClick={() => {
      setMessage('');
      if (!navigator.clipboard?.readText) { setMessage('无法读取剪贴板，请手动粘贴'); return; }
      void navigator.clipboard.readText().then(text => {
        onCode(parseCard(text));
        setMessage('已填入卡密');
      }).catch(() => setMessage('无法读取剪贴板，请手动粘贴'));
    }}>从剪贴板粘贴卡密或兑换链接</Button>
    {message && <output className="small muted">{message}</output>}
  </>;
}
