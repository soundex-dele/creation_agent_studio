import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode, type RefObject } from 'react';
import { X } from 'lucide-react';

/** Parent-bounded overlay; keep background controls out of the focus order. */
export default function GameDialog({ title, onClose, background, extra, children }: {
  title: string; onClose: () => void; background: RefObject<HTMLDivElement>;
  extra?: ReactNode; children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null;
    const content = background.current;
    if (content) content.inert = true;
    ref.current?.querySelector<HTMLButtonElement>('button')?.focus({ preventScroll: true });
    return () => {
      if (content) content.inert = false;
      trigger?.focus({ preventScroll: true });
    };
  }, [background]);
  const onKeyDown = (event: KeyboardEvent) => {
    event.stopPropagation();
    if (event.key === 'Escape') { event.preventDefault(); onClose(); }
    if (event.key !== 'Tab') return;
    const items = Array.from(ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled), select, a[href], [tabindex="0"]') ?? []);
    const first = items[0]; const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  };
  return <div className="sokoban-overlay" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="sokoban-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} ref={ref} onKeyDown={onKeyDown}>
      <header className="sokoban-dialog-heading"><h2 id={titleId}>{title}</h2>{extra}<button aria-label="关闭弹层" onClick={onClose}><X size={20} aria-hidden="true" /></button></header>
      {children}
    </div>
  </div>;
}
