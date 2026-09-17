import { useEffect, useState } from 'react';
import { Bell, ChevronRight } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import type { Notice } from './content';
// Once per page visit, not every route change or background content refresh.
let entryAnnouncementShown = false;
export const noticeKey = (n: Notice) => `${n.id}:${n.revision}`;
export const publicNotices = (notices: Notice[]) =>
  notices
    .filter((n) => !!n.published)
    .sort(
      (a, b) =>
        Number(b.pinned) - Number(a.pinned) ||
        b.updated - a.updated ||
        b.created - a.created,
    );
function acknowledged() {
  try {
    return new Set<string>(
      JSON.parse(localStorage.getItem('jamie-notice-read') || '[]'),
    );
  } catch {
    return new Set<string>();
  }
}
export function markNoticeRead(notice: Notice) {
  const next = acknowledged();
  next.add(noticeKey(notice));
  try {
    localStorage.setItem('jamie-notice-read', JSON.stringify([...next].slice(-200)));
    window.dispatchEvent(new Event('jamie-notice-read'));
  } catch {}
}
export function NoticeEntry({
  notices,
  ready,
  navigate,
  showStrip = true,
}: {
  notices: Notice[];
  ready: boolean;
  navigate: (view: string) => void;
  showStrip?: boolean;
}) {
  const [read, setRead] = useState(acknowledged),
    [selected, setSelected] = useState<string | null>(null);
  const visible = publicNotices(notices),
    current = visible.find((n) => n.id === selected);
  const unread = visible.filter((n) => !read.has(noticeKey(n)));
  useEffect(() => {
    if (!ready || !visible.length || entryAnnouncementShown) return;
    entryAnnouncementShown = true;
    setSelected(visible[0].id);
  }, [ready, notices]);
  useEffect(() => {
    const sync = () => setRead(acknowledged());
    window.addEventListener('jamie-notice-read', sync);
    window.addEventListener('storage', sync);
    return () => {
      window.removeEventListener('jamie-notice-read', sync);
      window.removeEventListener('storage', sync);
    };
  }, []);
  const close = () => {
    if (current) {
      const next = new Set(read);
      next.add(noticeKey(current));
      setRead(next);
      markNoticeRead(current);
    }
    setSelected(null);
  };
  if (!ready || !visible.length) return null;
  const latest = unread[0] || visible[0];
  return (
    <>
      {showStrip && <aside className="entry-notice" aria-label="站点公告">
        <button
          className="entry-notice-title"
          onClick={() => setSelected(latest.id)}
        >
          <Bell size={16} aria-hidden="true" />
          <span>{unread.length ? '新公告' : '公告'}</span>
          <strong>{latest.title}</strong>
          <ChevronRight size={14} aria-hidden="true" />
        </button>
        <button className="text-link" onClick={() => navigate('notices')}>
          全部公告
        </button>
      </aside>}
      <Dialog
        open={!!current}
        onOpenChange={(value) => {
          if (!value) close();
        }}
      >
        <DialogContent className="notice-dialog">
          <DialogTitle>{current?.title}</DialogTitle>
          <DialogDescription>
            {current
              ? new Date(current.updated * 1000).toLocaleDateString('zh-CN', {
                  year: 'numeric', month: 'long', day: 'numeric',
                })
              : ''}{' '}
            · {current?.pinned ? '置顶公告' : '站点公告'}
          </DialogDescription>
          <div className="notice-full-body">{current?.body}</div>
          <Button onClick={close}>完成</Button>
          <button
            className="text-link"
            onClick={() => {
              close();
              navigate('notices');
            }}
          >
            查看全部公告
          </button>
        </DialogContent>
      </Dialog>
    </>
  );
}
