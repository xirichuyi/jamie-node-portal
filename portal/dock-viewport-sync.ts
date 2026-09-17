// Anchor from the top of the layout viewport, using the visible viewport's
// bottom. Avoid Safari's bottom-fixed toolbar adjustment being applied twice.
export function watchDockViewport(element: HTMLElement, win: Window) {
  const viewport = win.visualViewport;
  if (!viewport) return () => {};
  const mobile = win.matchMedia('(hover: none) and (pointer: coarse)');
  let frame: number | null = null;
  const clear = () => {
    element.style.removeProperty('--dock-visible-top');
    element.style.removeProperty('--dock-visible-height');
  };
  const update = () => {
    frame = null;
    // Keep native pinch zoom behavior; never disable or counter-scale zoom.
    if (
      !mobile.matches ||
      Math.abs(viewport.scale - 1) > 0.01 ||
      !Number.isFinite(viewport.height) ||
      viewport.height <= 0 ||
      !Number.isFinite(viewport.offsetTop)
    ) {
      clear();
      return;
    }
    element.style.setProperty(
      '--dock-visible-top',
      `${Math.max(0, viewport.offsetTop)}px`,
    );
    element.style.setProperty('--dock-visible-height', `${viewport.height}px`);
  };
  const schedule = () => {
    if (frame === null) frame = win.requestAnimationFrame(update);
  };
  const events: Array<[EventTarget, string]> = [
    [viewport, 'resize'],
    [viewport, 'scroll'],
    [viewport, 'scrollend'],
    [win, 'resize'],
    [win, 'scroll'],
    [win, 'pageshow'],
    [win, 'orientationchange'],
    [win, 'touchend'],
    [mobile, 'change'],
  ];
  for (const [target, event] of events)
    target.addEventListener(event, schedule, { passive: true });
  update();
  return () => {
    for (const [target, event] of events)
      target.removeEventListener(event, schedule);
    if (frame !== null) win.cancelAnimationFrame(frame);
    clear();
  };
}
