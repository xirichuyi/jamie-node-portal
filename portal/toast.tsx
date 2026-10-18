import { useEffect, useState } from 'react';
import { Check, TriangleAlert, X } from 'lucide-react';

type Toast = { id: number; text: string; tone: 'success' | 'error' };
let next = 0;
// Floating feedback stays visible wherever the action happened on a long page.
export function notify(text: string, tone: Toast['tone'] = 'success') {
  window.dispatchEvent(new CustomEvent('jamie-toast', { detail: { text, tone } }));
}
export function Toaster() {
  const [items, setItems] = useState<Toast[]>([]);
  useEffect(() => {
    const add = (event: Event) => {
      const { text, tone } = (event as CustomEvent<Omit<Toast, 'id'>>).detail;
      const id = ++next;
      setItems((list) => [...list.filter((t) => t.text !== text), { id, text, tone }].slice(-3));
      setTimeout(
        () => setItems((list) => list.filter((t) => t.id !== id)),
        tone === 'error' ? 8000 : 3500,
      );
    };
    window.addEventListener('jamie-toast', add);
    return () => window.removeEventListener('jamie-toast', add);
  }, []);
  if (!items.length) return null;
  return (
    <div className="toaster" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={'toast-item toast-' + t.tone} role={t.tone === 'error' ? 'alert' : 'status'}>
          {t.tone === 'error' ? <TriangleAlert size={17} /> : <Check size={17} />}
          <span>{t.text}</span>
          <button
            aria-label="关闭提示"
            onClick={() => setItems((list) => list.filter((x) => x.id !== t.id))}
          >
            <X size={15} />
          </button>
        </div>
      ))}
    </div>
  );
}
