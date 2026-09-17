import { type ReactNode } from 'react';
import { createPortal } from 'react-dom';

export function DockViewport({ children }: { children: ReactNode }) {
  return createPortal(
    <div className="dock-viewport">{children}</div>,
    document.body,
  );
}
