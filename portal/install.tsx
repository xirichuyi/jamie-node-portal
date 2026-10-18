import { useEffect, useState } from 'react';
import { Download, Share, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';

type InstallEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
};
const snoozeKey = 'jamie-install-snoozed';
const week = 7 * 24 * 60 * 60 * 1000;

export function installPlatform(ua: string, touchPoints: number) {
  if (/iPhone|iPad|iPod/i.test(ua) || (/Macintosh/i.test(ua) && touchPoints > 1)) return 'ios';
  return /Android/i.test(ua) ? 'android' : 'desktop';
}

export function InstallGuide({ visible, promote }: { visible: boolean; promote: boolean }) {
  const [prompt, setPrompt] = useState<InstallEvent | null>(null);
  const [installed, setInstalled] = useState(false);
  const [snoozed, setSnoozed] = useState(true);
  const [mobile, setMobile] = useState(false);
  const [platform, setPlatform] = useState('desktop');
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const display = matchMedia('(display-mode: standalone)');
    const screen = matchMedia('(max-width: 767px), (pointer: coarse)');
    const sync = () => {
      setInstalled(display.matches || !!(navigator as Navigator & { standalone?: boolean }).standalone);
      setMobile(screen.matches);
    };
    sync();
    setPlatform(installPlatform(navigator.userAgent, navigator.maxTouchPoints));
    try { setSnoozed(Date.now() - Number(localStorage.getItem(snoozeKey) || 0) < week); }
    catch { setSnoozed(false); }
    const available = (event: Event) => { event.preventDefault(); setPrompt(event as InstallEvent); };
    const completed = () => { setInstalled(true); setPrompt(null); setOpen(false); };
    window.addEventListener('beforeinstallprompt', available);
    window.addEventListener('appinstalled', completed);
    display.addEventListener('change', sync);
    screen.addEventListener('change', sync);
    return () => {
      window.removeEventListener('beforeinstallprompt', available);
      window.removeEventListener('appinstalled', completed);
      display.removeEventListener('change', sync);
      screen.removeEventListener('change', sync);
    };
  }, []);
  function dismiss() {
    setSnoozed(true);
    try { localStorage.setItem(snoozeKey, String(Date.now())); } catch { /* Session-only dismissal. */ }
  }
  async function install() {
    if (!prompt) { setOpen(true); return; }
    setBusy(true);
    try {
      await prompt.prompt();
      const choice = await prompt.userChoice;
      if (choice.outcome === 'accepted') { setSnoozed(true); setOpen(false); }
    } catch { setOpen(true); }
    finally { setPrompt(null); setBusy(false); }
  }
  if (!visible || installed) return null;
  const banner = mobile && promote && !snoozed;
  return <>
    {banner ? <aside className="install-banner" aria-label="添加到主屏幕">
      <img src="/apple-touch-icon-v3.png" alt="" width="40" height="40" />
      <div><strong>放到手机桌面</strong><p>下次点图标，直接打开</p></div>
      <Button variant="outline" disabled={busy} onClick={() => void install()}>添加</Button>
      <button className="install-dismiss" aria-label="暂不提示，七天后再提醒" onClick={dismiss}><X size={16} /></button>
    </aside> : <button className="install-entry text-link" onClick={() => setOpen(true)}><Download size={15} />添加到主屏幕</button>}
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="install-dialog">
        <img className="install-app-icon" src="/apple-touch-icon-v3.png" alt="" width="56" height="56" />
        <DialogTitle>把 Jamie-Node 放到桌面</DialogTitle>
        <DialogDescription>下次从桌面直接查看订阅、续费。</DialogDescription>
        {platform === 'ios' ? <ol className="install-steps"><li>用 Safari 打开本站</li><li>点击「分享」<Share size={15} />，选择「添加到主屏幕」</li><li>如有「作为网页 App 打开」，保持开启，点击「添加」</li></ol> : <ol className="install-steps"><li>用 {platform === 'android' ? 'Chrome' : 'Chrome 或 Edge'} 打开本站</li><li>打开浏览器菜单，选择「安装应用」或「添加到主屏幕」</li><li>确认添加，即可从桌面打开</li></ol>}
        {prompt && <Button disabled={busy} onClick={() => void install()}><Download size={16} />{busy ? '等待确认…' : '安装应用'}</Button>}
        <p className="install-hint">{platform === 'desktop' ? 'Safari 可在「文件」菜单中选择「添加到程序坞」。' : '微信、QQ 内请先选择「在浏览器打开」。'}</p>
      </DialogContent>
    </Dialog>
  </>;
}
