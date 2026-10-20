import { useEffect, useRef, useState } from 'react';

const parents: Record<string, string> = {
  login: 'account',
  register: 'account',
  home: 'home',
  plans: 'plans',
  guide: 'guide',
  account: 'account',
  redeem: 'plans',
  notices: 'home',
  help: 'account',
  security: 'account',
  history: 'account',
  orders: 'plans',
  admin_orders: 'account',
  subscription: 'account',
  admin: 'account',
  admin_users: 'account',
  admin_content: 'account',
  usage: 'account',
  tickets: 'account',
  sessions: 'account',
  recover: 'account',
  status: 'home',
  operations: 'account',
  admin_tickets: 'account',
  admin_logs: 'account',
};
export const tabFor = (view: string) => parents[view] || 'home';
// Visitors who signed in on this browser before land on login, not activation.
export const authModeFor = (view: string, returning = false): 'register' | 'login' =>
  view === 'register' || (!returning && ['home', 'redeem'].includes(view))
    ? 'register'
    : 'login';
export const afterLogin = (view: string) =>
  ['login', 'register', 'account'].includes(view) ? 'home' : view;
export const isAuthenticationView = (view: string, signedIn: boolean) =>
  ['recover', 'login', 'register'].includes(view) ||
  (!signedIn && !['plans', 'guide', 'help', 'notices', 'orders'].includes(view));
export const showDock = (
  view: string,
  signedIn: boolean,
  loaded: boolean,
  mustChange = false,
) =>
  loaded &&
  !mustChange &&
  !isAuthenticationView(view, signedIn) &&
  ![
    'admin',
    'admin_users',
    'admin_content',
    'admin_tickets',
    'admin_logs',
    'admin_orders',
    'operations',
  ].includes(view);
export const readView = () => {
  const view = location.hash.replace(/^#\/?/, '').split('?')[0];
  return Object.hasOwn(parents, view) ? view : 'home';
};
export function navigateTo(next: string, replace = false) {
  if (!Object.hasOwn(parents, next)) return false;
  if (next !== readView()) {
    window.history[replace ? 'replaceState' : 'pushState'](
      { jamieFrom: readView() },
      '',
      '#/' + next,
    );
  }
  return true;
}
export function useNavigation() {
  const [view, update] = useState(readView);
  const scrollPositions = useRef(new Map<string, number>());
  useEffect(() => {
    const sync = () => update(readView());
    window.addEventListener('popstate', sync);
    window.addEventListener('hashchange', sync);
    return () => {
      window.removeEventListener('popstate', sync);
      window.removeEventListener('hashchange', sync);
    };
  }, []);
  const navigate = (next: string, replace = false) => {
    if (navigateTo(next, replace)) update(next);
  };
  const back = () => {
    if (window.history.state?.jamieFrom) window.history.back();
    else navigate(tabFor(view), true);
  };
  useEffect(() => {
    const restored = scrollPositions.current.get(view) || 0;
    let restoring = true;
    const restore = () => {
      if (!restoring) return;
      window.scrollTo({ top: restored, behavior: 'instant' });
      if (
        document.documentElement.scrollHeight - window.innerHeight >=
        restored
      )
        restoring = false;
    };
    restore();
    // Data-backed pages may be shorter while loading. Restore once content arrives,
    // unless the user has already started scrolling or navigating themselves.
    const observer = new MutationObserver(restore);
    observer.observe(document.querySelector('main') || document.body, {
      childList: true,
      subtree: true,
    });
    const cancel = () => {
      restoring = false;
    };
    window.addEventListener('wheel', cancel, { passive: true });
    window.addEventListener('touchstart', cancel, { passive: true });
    window.addEventListener('keydown', cancel);
    document.querySelector<HTMLElement>('main')?.focus({ preventScroll: true });
    const remember = () => {
      if (!restoring) scrollPositions.current.set(view, window.scrollY);
    };
    window.addEventListener('scroll', remember, { passive: true });
    return () => {
      observer.disconnect();
      window.removeEventListener('scroll', remember);
      window.removeEventListener('wheel', cancel);
      window.removeEventListener('touchstart', cancel);
      window.removeEventListener('keydown', cancel);
    };
  }, [view]);
  return { view, navigate, back };
}
// Routing needs the admin view list; the admin shell itself loads on demand.
export const adminViews = [
  'operations',
  'admin_users',
  'admin',
  'admin_tickets',
  'admin_content',
  'admin_logs',
  'admin_orders',
];
